"""复核所有者生成的字段命中事实；不接受证据替代执行授权。"""
from collections.abc import Mapping
import math
import re

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.operation.recognition.control_corroboration import _contains

EVIDENCE_KEY = 'current_native_field_hit'


def validated_hit_field(proof, uia, point, screenshot_sha256):
    """纯数据复核供生产者与消费者共用；来源真实性由持久观察所有者保持。"""
    if not isinstance(proof, Mapping) or set(proof) != {
        'contract_version', 'capture_id', 'screenshot_sha256', 'uia_snapshot_sha256',
        'capture_started_ns', 'captured_at_ns', 'before_hit_ns', 'after_hit_ns',
        'target', 'hit', 'pixels'}:
        return None
    if (proof['contract_version'] != 'current_field_hit_binding_v1'
            or not isinstance(proof['capture_id'], str) or not proof['capture_id']
            or not isinstance(screenshot_sha256, str) or not re.fullmatch('[0-9a-f]{64}', screenshot_sha256)
            or proof['screenshot_sha256'] != screenshot_sha256
            or not isinstance(uia, Mapping) or uia.get('scan_complete') is not True
            or uia.get('truncated') is not False or uia.get('status') != 'ok'
            or proof['uia_snapshot_sha256'] != payload_sha256(uia)):
        return None
    hit, target, pixels = proof['hit'], proof['target'], proof['pixels']
    if not all(isinstance(x, dict) for x in (hit, target, pixels)):
        return None
    if (set(hit) != {'contract_version','provider','capture_id','target_field_id','target',
                    'runtime_id','control_type','bbox','point','observed_at_ns','sample_count',
                    'artifact_is_authorization','action_executed'}
            or hit['contract_version'] != 'windows_field_hit_observation_v1'
            or hit['provider'] != 'windows_uia.from_point' or hit['sample_count'] != 2
            or hit['artifact_is_authorization'] is not False or hit['action_executed'] is not False
            or hit['capture_id'] != proof['capture_id'] or hit['target'] != target or hit['point'] != point
            or set(target) != {'window_handle','process_id','process_create_time','window_rect'}):
        return None
    window = uia.get('window', {})
    rect = target['window_rect']
    created = target['process_create_time']
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
    try:
        from app.agent.fresh_text_field import _field_uia_identity
        identity = _field_uia_identity(uia, point)
    except (ValueError, KeyError, TypeError):
        return None
    fields = [c for c in uia['controls'] if c.get('runtime_id') == list(identity['runtime_id'])]
    if len(fields) != 1:
        return None
    field = fields[0]
    if (hit['runtime_id'] != field['runtime_id']
            or hit['control_type'] not in {'Edit', 'ComboBox', 'Document'}
            or hit['control_type'].casefold() != identity['control_type']
            or hit['bbox'] != field['bbox'] or hit['target_field_id'] != field['control_id']
            or set(pixels) != {'bbox','source_rgb_sha256','before_rgb_sha256','after_rgb_sha256'}
            or pixels['bbox'] != field['bbox'] or not isinstance(pixels['source_rgb_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', pixels['source_rgb_sha256'])
            or pixels['source_rgb_sha256'] != pixels['before_rgb_sha256']
            or pixels['source_rgb_sha256'] != pixels['after_rgb_sha256']):
        return None
    return field


def disproved_container_ids(proof, uia, point, screenshot_sha256):
    field = validated_hit_field(proof, uia, point, screenshot_sha256)
    if field is None:
        return set()
    controls = uia['controls']
    ids = [c.get('control_id') for c in controls]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return set()
    return {c['control_id'] for c in uia['controls']
            if str(c.get('control_type') or '').casefold() in {'group','pane','document'}
            and c.get('enabled') is True and c.get('visible') is True
            and c.get('bbox') != field['bbox'] and _contains(c.get('bbox'), field['bbox'])
            and isinstance(c.get('control_id'), str)}


def validate_hit_observation(proof, evidence, uia, point):
    """封存预览必须对应同一捕获时段与本机目标，不能重放别帧的命中。"""
    capture, target, app = evidence['capture'], evidence['target'], evidence['application']
    if validated_hit_field(proof, uia, point, capture['screenshot_sha256']) is None:
        raise ValueError('current native field hit binding is invalid')
    if (any(proof[k] != capture[k] for k in ('capture_id','capture_started_ns','captured_at_ns'))
            or proof['after_hit_ns'] > capture['observed_at_ns']
            or any(proof['target'][k] != target[k] for k in ('window_handle','process_id'))
            or proof['target']['window_rect'] != [target['rect'][k] for k in ('x','y','width','height')]
            or proof['target']['process_create_time'] != app.get('process_create_time')):
        raise ValueError('native field hit differs from owned capture')
