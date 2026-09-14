"""同一当前可点击控件内的模型点与独立 OCR 绑定；不扩大框或移动点击点。"""
from collections.abc import Mapping
import re
import unicodedata

from app.gate.fresh_action_risk import _actionable


REASON = 'vista_point_and_ocr_share_current_uia_control'
EVIDENCE_KEY = 'current_control_ocr_binding'


def _box(value):
    return (isinstance(value, Mapping) and set(value) == {'x', 'y', 'w', 'h'}
            and all(type(value[k]) is int for k in value)
            and min(value['x'], value['y']) >= 0 and min(value['w'], value['h']) > 0)


def _inside(box, point):
    return (_box(box) and isinstance(point, dict) and set(point) == {'x', 'y'}
            and all(type(v) is int for v in point.values())
            and box['x'] <= point['x'] < box['x'] + box['w']
            and box['y'] <= point['y'] < box['y'] + box['h'])


def _contains(outer, inner):
    return (_box(outer) and _box(inner) and outer['x'] <= inner['x']
            and outer['y'] <= inner['y'] and inner['x'] + inner['w'] <= outer['x'] + outer['w']
            and inner['y'] + inner['h'] <= outer['y'] + outer['h'])


def _overlaps(left, right):
    return (_box(left) and _box(right)
            and max(left['x'], right['x']) < min(left['x'] + left['w'], right['x'] + right['w'])
            and max(left['y'], right['y']) < min(left['y'] + left['h'], right['y'] + right['h']))


def current_control_ocr_binding(candidate, local, uia, screenshot_sha256):
    """重算证据，不信任候选自述的已验证标志；缺失任何来源则不适用。"""
    if (not isinstance(uia, Mapping) or uia.get('status') != 'ok'
            or uia.get('scan_complete') is not True or uia.get('truncated') is not False
            or not isinstance(screenshot_sha256, str) or not re.fullmatch('[0-9a-f]{64}', screenshot_sha256)
            or candidate.role not in {'button', 'link'} or candidate.element.role != candidate.role
            or local.coordinate_source != 'vista_point_v1_corroborated_by_local_ocr'
            or not candidate.eligible or not candidate.element.interaction_policy.allowed
            or local.candidate_id != candidate.candidate_id or local.element_id != candidate.element_id):
        return None
    controls = uia.get('controls')
    if not isinstance(controls, list) or not all(isinstance(c, dict) for c in controls):
        return None
    point, text_box = local.refined_click_point, local.matched_text_bbox
    bbox = candidate.element.bbox.to_dict()
    evidence = candidate.element.evidence
    action = evidence.get('screen_inventory_action') or {}
    model = evidence.get('vista_direct_identity') or {}
    if (action.get('source') != 'windows_uia.controls' or model.get('source') != 'vista_direct_point_grounding'
            or model.get('point') != point or action.get('bbox') != bbox
            or (candidate.refined_bbox is not None and candidate.refined_bbox != bbox)
            or not _inside(bbox, point) or not _contains(bbox, text_box)
            or not _contains(local.crop_bbox, text_box)):
        return None
    selected = [c for c in controls if c.get('control_id') == action.get('source_id')]
    if len(selected) != 1 or not action.get('source_id'):
        return None
    control = selected[0]
    runtime_id = control.get('runtime_id')
    if (type(runtime_id) is not list or not runtime_id
            or any(type(value) is not int for value in runtime_id)
            or sum(c.get('runtime_id') == runtime_id for c in controls) != 1):
        return None
    role_type = {'button': 'Button', 'link': 'Hyperlink'}[candidate.role]
    if (control.get('control_type') != role_type or control.get('bbox') != bbox
            or control.get('visible') is not True or control.get('enabled') is not True
            or 'Invoke' not in (control.get('patterns') or [])
            or any(label != control.get('name') for label in (
                candidate.label, candidate.text, candidate.element.label, candidate.element.text))):
        return None
    # 不能借父容器文字为重叠子按钮或邻接控件的点背书。
    for other in controls:
        if other is control or other.get('visible') is False:
            continue
        # 浏览器可能为整个事件冒泡容器暴露 Invoke；已证实的结构祖先不是独立命中目标。
        if (other.get('control_id') in (control.get('ancestor_control_ids') or [])
                and other.get('control_type') in {'Group', 'Pane', 'Document'}
                and _contains(other.get('bbox'), bbox)):
            continue
        actionable = _actionable(other) or other.get('control_type') in {
            'Edit', 'ComboBox', 'TextBox', 'TabItem', 'TreeItem', 'ListItem', 'RadioButton', 'SplitButton'}
        if actionable and (_inside(other.get('bbox'), point)
                           or _overlaps(other.get('bbox'), text_box)):
            return None
    def normalize(value):
        return ' '.join(unicodedata.normalize('NFC', str(value or '')).casefold().split())
    text, label = normalize(local.matched_text), normalize(control.get('name'))
    if len(text) < 3 or (' ' + text + ' ') not in (' ' + label + ' '):
        return None
    return {'contract_version': 'current_control_ocr_binding_v1',
            'screenshot_sha256': screenshot_sha256, 'control_id': control['control_id'],
            'runtime_id': list(runtime_id),
            'candidate_id': candidate.candidate_id, 'element_id': candidate.element_id,
            'bbox': dict(bbox), 'point': dict(point), 'matched_text': local.matched_text,
            'matched_text_bbox': dict(text_box)}


def has_current_control_ocr_binding(candidate, local, uia, screenshot_sha256):
    if REASON not in local.reasons or local.status != 'grounded':
        return False
    expected = current_control_ocr_binding(candidate, local, uia, screenshot_sha256)
    return expected is not None and candidate.element.evidence.get(EVIDENCE_KEY) == expected
