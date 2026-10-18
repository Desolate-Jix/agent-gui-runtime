"""原生图标命中是独立证据类型，不将无障碍名称当作 OCR 文字。"""
from collections.abc import Mapping
import math
import re

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.operation.recognition.control_corroboration import _box, _contains, _inside

EVIDENCE_KEY = 'current_native_control_hit'
REASON = 'vista_point_matches_current_native_control'
COORDINATE_SOURCE = 'vista_point_v1_corroborated_by_native_uia'


def current_icon_control(uia, point):
    """保留完整树的唯一实例及实际重叠检查，不按网站或目标名称放行。"""
    if (not isinstance(uia, Mapping) or uia.get('status') != 'ok'
            or uia.get('scan_complete') is not True or uia.get('truncated') is not False):
        return None
    controls = uia.get('controls')
    if not isinstance(controls, list) or not all(isinstance(c, dict) for c in controls):
        return None
    ids = [c.get('control_id') for c in controls]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return None
    matches = [c for c in controls if c.get('control_type') in {'Button', 'Hyperlink'}
               and c.get('visible') is True and c.get('enabled') is True
               and 'Invoke' in (c.get('patterns') or []) and _inside(c.get('bbox'), point)]
    if len(matches) != 1:
        return None
    control = matches[0]
    runtime = control.get('runtime_id')
    if (type(runtime) is not list or not 1 <= len(runtime) <= 64
            or any(type(v) is not int for v in runtime)
            or sum(c.get('runtime_id') == runtime for c in controls) != 1
            or not isinstance(control.get('name'), str) or not control['name'].strip()):
        return None
    from app.gate.fresh_action_risk import _actionable
    for other in controls:
        if other is control or other.get('visible') is False:
            continue
        if (other.get('control_id') in (control.get('ancestor_control_ids') or [])
                and other.get('control_type') in {'Group', 'Pane', 'Document'}
                and _contains(other.get('bbox'), control['bbox'])):
            continue
        # 容器范围不等于实际遮挡；后续双次原生命中仍须直接返回目标按钮。
        if (other.get('control_type') in {'Group', 'Pane', 'Document'}
                and not (other.get('name') or '').strip()
                and set(other.get('patterns') or []) <= {'Invoke'}
                and _contains(other.get('bbox'), control['bbox'])
                and other.get('bbox') != control['bbox']):
            continue
        if (_actionable(other) or other.get('control_type') in {
                'Edit', 'ComboBox', 'TextBox', 'TabItem', 'TreeItem', 'ListItem', 'RadioButton', 'SplitButton'}) and _inside(other.get('bbox'), point):
            return None
    return control


def validated_hit_control(proof, uia, point, screenshot_sha256):
    if not isinstance(proof, Mapping) or set(proof) != {
            'contract_version', 'capture_id', 'screenshot_sha256', 'uia_snapshot_sha256',
            'capture_started_ns', 'captured_at_ns', 'before_hit_ns', 'after_hit_ns', 'target', 'hit', 'pixels'}:
        return None
    if (proof['contract_version'] != 'current_control_hit_binding_v1'
            or not isinstance(proof['capture_id'], str) or not proof['capture_id']
            or not isinstance(screenshot_sha256, str) or not re.fullmatch('[0-9a-f]{64}', screenshot_sha256)
            or proof['screenshot_sha256'] != screenshot_sha256
            or proof['uia_snapshot_sha256'] != payload_sha256(uia)):
        return None
    control = current_icon_control(uia, point)
    if control is None:
        return None
    hit, target, pixels = proof['hit'], proof['target'], proof['pixels']
    if not all(isinstance(v, dict) for v in (hit, target, pixels)):
        return None
    if (set(hit) != {'contract_version','provider','capture_id','control_id','target','accessible_name',
                    'runtime_id','control_type','bbox','point','observed_at_ns','sample_count','pattern',
                    'artifact_is_authorization','action_executed'}
            or hit['contract_version'] != 'native_control_hit_v1'
            or hit['provider'] != 'windows_uia.from_point' or type(hit['sample_count']) is not int or hit['sample_count'] != 2
            or hit['pattern'] != 'Invoke' or hit['artifact_is_authorization'] is not False
            or hit['action_executed'] is not False or hit['capture_id'] != proof['capture_id']
            or hit['target'] != target or hit['point'] != point
            or any(hit[k] != control[k] for k in ('control_id','runtime_id','control_type','bbox'))
            or hit['accessible_name'] != control['name']
            or set(target) != {'window_handle','process_id','process_create_time','window_rect'}):
        return None
    rect, created = target['window_rect'], target['process_create_time']
    window = uia.get('window', {})
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect)
            or min(rect[2:]) <= 0 or type(created) not in (float, int) or not math.isfinite(created) or created <= 0
            or any(type(target[k]) is not int or target[k] <= 0 for k in ('window_handle','process_id'))
            or window.get('handle') != target['window_handle'] or window.get('process_id') != target['process_id']
            or window.get('bbox') != {'x':0,'y':0,'w':rect[2],'h':rect[3]}):
        return None
    stamps = [proof[k] for k in ('capture_started_ns','captured_at_ns','before_hit_ns')]
    stamps += [hit['observed_at_ns'], proof['after_hit_ns']]
    if any(type(v) is not int or v <= 0 for v in stamps) or stamps != sorted(stamps):
        return None
    if (set(pixels) != {'bbox','source_rgb_sha256','before_rgb_sha256','after_rgb_sha256'}
            or pixels['bbox'] != control['bbox'] or not isinstance(pixels['source_rgb_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', pixels['source_rgb_sha256'])
            or pixels['source_rgb_sha256'] != pixels['before_rgb_sha256']
            or pixels['source_rgb_sha256'] != pixels['after_rgb_sha256']):
        return None
    return control


def has_current_native_control_hit(candidate, local, uia, screenshot_sha256):
    from .native_control_ocr_observation import DISAGREEMENT, validated_native_ocr
    observed = validated_native_ocr(candidate, local, screenshot_sha256) if local is not None else None
    # 空文字和分歧均由完整原始观测重算，不能降级成 reason 字符串自证。
    if observed is None:
        return False
    disagreement = observed['classification'] == 'target_text_present'
    if (local is None or local.status != 'grounded' or REASON not in local.reasons
            or (DISAGREEMENT in local.reasons) != disagreement
            or ('local_ocr_returned_no_text' in local.reasons) != (observed['classification'] == 'empty')
            or ('local_ocr_no_text_in_target' in local.reasons) != (observed['classification'] == 'outside_target')
            or local.coordinate_source != COORDINATE_SOURCE
            or local.matched_text is not None or local.matched_text_bbox is not None
            or local.candidate_id != candidate.candidate_id or local.element_id != candidate.element_id
            or candidate.role not in {'button','link'} or candidate.element.role != candidate.role
            or not candidate.eligible or not candidate.element.interaction_policy.allowed):
        return False
    evidence = candidate.element.evidence
    control = validated_hit_control(evidence.get(EVIDENCE_KEY), uia, local.refined_click_point, screenshot_sha256)
    if control is None:
        return False
    if observed['viewport_size'] != evidence[EVIDENCE_KEY]['target']['window_rect'][2:]:
        return False
    action, model = evidence.get('screen_inventory_action', {}), evidence.get('vista_direct_identity', {})
    bbox = candidate.element.bbox.to_dict()
    return (action.get('source') == 'windows_uia.controls' and action.get('source_id') == control['control_id']
            and action.get('bbox') == bbox == control['bbox']
            and (candidate.refined_bbox is None or candidate.refined_bbox == bbox)
            and model.get('source') == 'vista_direct_point_grounding' and model.get('point') == local.refined_click_point
            and {'button':'Button','link':'Hyperlink'}[candidate.role] == control['control_type']
            and all(v == control['name'] for v in (candidate.label,candidate.text,candidate.element.label,candidate.element.text))
            and _box(local.crop_bbox) and _contains(local.crop_bbox, bbox))


def validate_control_hit_observation(proof, evidence, uia, point):
    capture, target, app = evidence['capture'], evidence['target'], evidence['application']
    if validated_hit_control(proof, uia, point, capture['screenshot_sha256']) is None:
        raise ValueError('current native control hit binding is invalid')
    if (any(proof[k] != capture[k] for k in ('capture_id','capture_started_ns','captured_at_ns'))
            or proof['after_hit_ns'] > capture['observed_at_ns']
            or any(proof['target'][k] != target[k] for k in ('window_handle','process_id'))
            or proof['target']['window_rect'] != [target['rect'][k] for k in ('x','y','width','height')]
            or proof['target']['process_create_time'] != app.get('process_create_time')):
        raise ValueError('native control hit differs from owned capture')
