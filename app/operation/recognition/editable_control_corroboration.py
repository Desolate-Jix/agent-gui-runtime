"""填写候选的当前可编辑 UIA 身份与局部 OCR 绑定，不生成输入权限。"""
from collections.abc import Mapping
import re
import unicodedata

from app.operation.recognition.control_corroboration import _inside, _contains, _overlaps
from app.operation.recognition.control_target import uia_control_is_action_identity, validate_control_target


REASON = 'vista_point_and_ocr_share_current_editable_uia_field'
EVIDENCE_KEY = 'current_editable_field_ocr_binding'
_FIELD_TYPES = {'edit', 'textbox', 'combobox', 'combo box'}


def _text_key(value):
    return ''.join(unicodedata.normalize('NFC', value).split()).casefold() if isinstance(value, str) else ''


def _unreadable_name(value):
    # 仅接受真实空白或对象占位符；不能把任意符号、乱码、数字当成无名称。
    return value is None or isinstance(value, str) and not value.replace('\ufffc', '').strip()


def _ocr_edge_tolerance(bbox):
    return min(8, max(2, round(bbox['h'] * 0.2)))


def _field_contains_ocr(bbox, text_box, *, native_hit_verified):
    if _contains(bbox, text_box):
        return True
    # OCR 边缘随字号有取整误差；只放宽文字关联，仍要求至少 95% 在原生命中字段内。
    if not native_hit_verified or not isinstance(bbox, Mapping):
        return False
    margin = _ocr_edge_tolerance(bbox)
    padded = {'x':max(0, bbox['x']-margin), 'y':max(0, bbox['y']-margin),
              'w':bbox['w']+margin+min(margin,bbox['x']), 'h':bbox['h']+margin+min(margin,bbox['y'])}
    if not _contains(padded, text_box):
        return False
    overlap = (max(0,min(bbox['x']+bbox['w'],text_box['x']+text_box['w'])-max(bbox['x'],text_box['x']))
               * max(0,min(bbox['y']+bbox['h'],text_box['y']+text_box['h'])-max(bbox['y'],text_box['y'])))
    return overlap >= text_box['w'] * text_box['h'] * 0.95


def _current_editable_control(uia, point, goal, control_target=None, *, native_hit=None, screenshot_sha256=None):
    """在完整原树上解析字段，不能靠清单过滤掩盖重叠或禁用控件。"""
    from app.agent.fresh_text_field import _field_uia_identity

    if (not isinstance(uia, Mapping) or uia.get('status') != 'ok'
            or uia.get('scan_complete') is not True or uia.get('truncated') is not False
            or not isinstance(uia.get('controls'), list)
            or not all(isinstance(c, dict) for c in uia['controls']) or not _text_key(goal)):
        return None
    if control_target is not None:
        try:
            target = validate_control_target(control_target)
        except ValueError:
            return None
        if target['role'] != 'input':
            return None
        label = target['label']
    else:
        label = goal
    try:
        identity = _field_uia_identity(uia, point)
    except (ValueError, TypeError, KeyError):
        return None
    selected = [c for c in uia['controls'] if c.get('runtime_id') == list(identity['runtime_id'])]
    if len(selected) != 1:
        return None
    control = selected[0]
    name, bbox = control.get('name'), control.get('bbox')
    if (not isinstance(control.get('control_id'), str) or not control['control_id']
            or sum(c.get('control_id') == control['control_id'] for c in uia['controls']) != 1
            or not _inside(bbox, point) or control.get('enabled') is not True
            or control.get('visible') is not True
            or not (_unreadable_name(name) or _text_key(name) == _text_key(label))):
        return None
    from .native_field_hit_binding import disproved_container_ids
    excluded = disproved_container_ids(native_hit, uia, point, screenshot_sha256)
    for other in uia['controls']:
        if other is control or other.get('visible') is False:
            continue
        kind = str(other.get('control_type') or '').strip().casefold()
        if (kind in _FIELD_TYPES and _text_key(other.get('name')) == _text_key(label)):
            return None
        if other.get('control_id') in excluded:
            continue
        # 已证结构祖先只提供上下文；独立 Invoke 容器仍是冲突目标。
        if (other.get('control_id') in (control.get('ancestor_control_ids') or [])
                and kind in {'group', 'pane', 'document'} and _contains(other.get('bbox'), bbox)):
            continue
        if (uia_control_is_action_identity(other) or kind in _FIELD_TYPES) and _inside(other.get('bbox'), point):
            return None
    return control


def current_editable_control_ocr_binding(candidate, local, uia, screenshot_sha256, goal, control_target=None):
    """由本帧来源重算绑定；自述 grounded 或缓存标记均不能代替证据。"""
    if (not isinstance(screenshot_sha256, str) or not re.fullmatch('[0-9a-f]{64}', screenshot_sha256)
            or candidate.role != 'input' or candidate.element.role != 'input'
            or candidate.element.interaction_type != 'focus'
            or not candidate.eligible or not candidate.element.interaction_policy.allowed
            or local.coordinate_source != 'vista_point_v1_corroborated_by_local_ocr'
            or local.candidate_id != candidate.candidate_id or local.element_id != candidate.element_id):
        return None
    point, text_box = local.refined_click_point, local.matched_text_bbox
    from .native_field_hit_binding import EVIDENCE_KEY as HIT_KEY, disproved_container_ids, validated_hit_field
    hit = candidate.element.evidence.get(HIT_KEY)
    if hit is not None and validated_hit_field(hit, uia, point, screenshot_sha256) is None:
        return None
    control = _current_editable_control(uia, point, goal, control_target,
        native_hit=hit, screenshot_sha256=screenshot_sha256)
    if control is None:
        return None
    bbox = candidate.element.bbox.to_dict()
    evidence = candidate.element.evidence
    action, model = evidence.get('screen_inventory_action'), evidence.get('vista_direct_identity')
    if not isinstance(action, Mapping) or not isinstance(model, Mapping):
        return None
    target_label = control_target['label'] if control_target is not None else goal
    if (action.get('source') != 'windows_uia.controls' or action.get('source_id') != control['control_id']
            or action.get('bbox') != bbox or action.get('label') != control.get('name')
            or model.get('source') != 'vista_direct_point_grounding' or model.get('point') != point
            or not isinstance(model.get('source_candidate_id'), str) or not model['source_candidate_id']
            or bbox != control.get('bbox') or candidate.element.click_point != point
            or candidate.refined_bbox != bbox
            or not _field_contains_ocr(bbox, text_box, native_hit_verified=hit is not None)
            or not _contains(local.crop_bbox, text_box)
            or not _text_key(local.matched_text) or _text_key(local.matched_text) != _text_key(target_label)
            or any(value != local.matched_text for value in (
                candidate.label, candidate.text, candidate.element.label, candidate.element.text))):
        return None
    excluded = disproved_container_ids(hit, uia, point, screenshot_sha256)
    for other in uia['controls']:
        if other is control or other.get('visible') is False:
            continue
        kind = str(other.get('control_type') or '').strip().casefold()
        if other.get('control_id') in excluded:
            continue
        if (other.get('control_id') in (control.get('ancestor_control_ids') or [])
                and kind in {'group', 'pane', 'document'} and _contains(other.get('bbox'), bbox)):
            continue
        if (uia_control_is_action_identity(other) or kind in _FIELD_TYPES) and _overlaps(other.get('bbox'), text_box):
            return None
    return {'contract_version': 'current_editable_field_ocr_binding_v1',
            **({'ocr_bbox_tolerance_px':_ocr_edge_tolerance(bbox)} if not _contains(bbox, text_box) else {}),
            'screenshot_sha256': screenshot_sha256, 'control_id': control['control_id'],
            'runtime_id': list(control['runtime_id']), 'control_type': control['control_type'],
            'raw_name': control['name'], 'candidate_id': candidate.candidate_id,
            'element_id': candidate.element_id, 'bbox': dict(bbox), 'point': dict(point),
            'matched_text': local.matched_text, 'matched_text_bbox': dict(text_box)}


def has_current_editable_control_ocr_binding(candidate, local, uia, screenshot_sha256, goal, control_target=None):
    if REASON not in local.reasons or local.status != 'grounded':
        return False
    expected = current_editable_control_ocr_binding(candidate, local, uia, screenshot_sha256, goal, control_target)
    return expected is not None and candidate.element.evidence.get(EVIDENCE_KEY) == expected
