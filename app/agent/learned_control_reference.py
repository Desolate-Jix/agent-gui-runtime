"""新原生界面库的确切控件引用；只提供定位约束，不产生执行权限。"""

from copy import deepcopy
import math
import re
import unicodedata

from app.agent.fresh_learning_action_contracts import payload_sha256


def validate_learned_control_selection(value):
    if (type(value) is not dict or set(value) != {'interface_id', 'version_id', 'region_id'}
            or any(not isinstance(v, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,159}', v) is None
                   for v in value.values())):
        raise ValueError('learned control requires exact interface, version and region IDs')
    return deepcopy(value)


def validate_learned_control_binding(value):
    from app.agent.fresh_learning_runtime_source import _normalized_application_identity

    keys = {'contract_version', 'reference', 'task_id', 'content_sha256', 'region',
            'application_identity', 'source_screenshot_sha256', 'binding_sha256'}
    if type(value) is not dict or set(value) != keys or value['contract_version'] != 'learned_control_binding_v1':
        raise ValueError('learned control binding fields are invalid')
    selected = validate_learned_control_selection(value['reference'])
    for key in ('content_sha256', 'source_screenshot_sha256', 'binding_sha256'):
        if not isinstance(value[key], str) or re.fullmatch(r'[0-9a-f]{64}', value[key]) is None:
            raise ValueError('learned control digest is invalid')
    if selected['version_id'] != 'interface-version-' + value['content_sha256']:
        raise ValueError('learned control version digest differs')
    if not isinstance(value['task_id'], str) or not value['task_id']:
        raise ValueError('learned control task is invalid')
    region = value['region']
    if (type(region) is not dict or set(region) != {'region_id', 'name', 'kind', 'meaning', 'recognition_text', 'bbox'}
            or region['region_id'] != selected['region_id']
            or any(not isinstance(region[k], str) for k in ('name', 'kind', 'meaning', 'recognition_text'))
            or type(region['bbox']) is not list or len(region['bbox']) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) for n in region['bbox'])
            or min(region['bbox'][:2]) < 0 or min(region['bbox'][2:]) <= 0):
        raise ValueError('learned control region is invalid')
    if _normalized_application_identity(value['application_identity']) != value['application_identity']:
        raise ValueError('learned control application is not canonical')
    if payload_sha256({k: v for k, v in value.items() if k != 'binding_sha256'}) != value['binding_sha256']:
        raise ValueError('learned control binding digest differs')
    return deepcopy(value)


def resolve_learned_control(source_owner, current_source, selection):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    from app.desktop_review.workspace import DesktopReviewError

    selected = validate_learned_control_selection(selection)
    facade = source_owner.facade
    try:
        with facade._guard:
            memory = facade.get_interface_memory(current_source['task_id'], selected['interface_id'], selected['version_id'])
            regions = [r for r in memory['content']['regions'] if r['region_id'] == selected['region_id']]
            if (memory['interface_id'] != selected['interface_id'] or memory['version_id'] != selected['version_id']
                    or len(regions) != 1):
                raise ValueError('learned control not found in exact version')
            original = facade._load_source_batch(memory['source']['task_id'], memory['source']['batch_id'])
            metadata = facade._fresh_source_for_batch(memory['source']['task_id'], memory['source']['batch_id'], original)
            if metadata is None:
                raise ValueError('learned control requires verified original capture')
            packet = source_owner.archive.read(metadata['reference'],
                **{k: metadata[k] for k in ('connection_id', 'task_id', 'segment_id')})
            application = _application_identity_from_evidence(packet.evidence())
            if (application != current_source['application_identity']
                    or metadata['reference']['screenshot_sha256'] != memory['source']['screenshot_sha256']):
                raise ValueError('learned control application or capture differs')
            binding = {'contract_version': 'learned_control_binding_v1', 'reference': selected,
                'task_id': current_source['task_id'], 'content_sha256': memory['content_sha256'],
                'region': {k: deepcopy(regions[0][k]) for k in
                    ('region_id', 'name', 'kind', 'meaning', 'recognition_text', 'bbox')}, 'application_identity': application,
                'source_screenshot_sha256': memory['source']['screenshot_sha256']}
            binding['binding_sha256'] = payload_sha256(binding)
            return validate_learned_control_binding(binding)
    except (DesktopReviewError, KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError('learned control source unavailable or does not match exact selection') from error


def revalidate_learned_control(source_owner, source, intent):
    binding = intent.learned_control
    if binding is not None and resolve_learned_control(source_owner, source.reference(), binding['reference']) != binding:
        raise ValueError('learned control changed after selection')


def recognition_target_from_learned_control(binding, *, semantic_action):
    """从确切版本派生当前定位约束；旧坐标、说明和填写值不参与目标选择。"""
    from app.operation.recognition.control_target import ROLES, validate_control_target

    if binding is None:
        return None
    checked = validate_learned_control_binding(binding)
    # 填写占位文本和滚动容器继续走各自的当前字段/容器校验，不套用按钮身份规则。
    if semantic_action in {'fill_field', 'scroll_region'}:
        return None
    role = {'menu': 'menu_item'}.get(checked['region']['kind'], checked['region']['kind'])
    if role not in ROLES:
        raise ValueError('learned control kind is not supported for navigation; select an actionable region')
    return validate_control_target({
        'contract_version': 'recognition_control_target_v1',
        'label': checked['region']['recognition_text'], 'role': role,
        'source_binding_sha256': checked['binding_sha256'],
    })


def _label(value):
    return ' '.join(unicodedata.normalize('NFC', value or '').split()).casefold()


def _placeholder_inside_current_field(local, field_bbox):
    """只将已知坐标协议的当前 OCR 文本关联到唯一字段，不猜测框的坐标系。"""
    from app.gate.fresh_action_risk import _bbox

    if getattr(local, 'status', None) != 'grounded':
        return False
    def box(value):
        if isinstance(value, dict) and set(value) == {'x', 'y', 'width', 'height'}:
            value = {'x': value['x'], 'y': value['y'], 'w': value['width'], 'h': value['height']}
        result = _bbox(value, 'OCR geometry')
        if result['x'] < 0 or result['y'] < 0:
            raise ValueError('OCR geometry is negative')
        return result
    try:
        crop = box(local.crop_bbox)
        text = box(local.matched_text_bbox)
        if local.coordinate_source == 'local_ocr_text_center':
            text = {**text, 'x': crop['x'] + text['x'], 'y': crop['y'] + text['y']}
        elif local.coordinate_source != 'vista_point_v1_corroborated_by_local_ocr':
            return False
    except (AttributeError, TypeError, ValueError):
        return False
    def contains(outer):
        return (outer['x'] <= text['x'] and outer['y'] <= text['y']
                and text['x'] + text['w'] <= outer['x'] + outer['w']
                and text['y'] + text['h'] <= outer['y'] + outer['h'])
    return contains(crop) and contains(field_bbox)


def validate_current_learned_control(binding, candidate, local, uia, application, *, semantic_action='open_detail', control_target=None,
                                    screenshot_sha256=None):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    from app.gate.fresh_action_risk import _actionable, _contains, _editable_text_controls
    from app.operation.recognition.control_corroboration import REASON, has_current_control_ocr_binding

    checked = validate_learned_control_binding(binding)
    if _application_identity_from_evidence({'application': application}) != checked['application_identity']:
        raise ValueError('learned control current application differs')
    anchor = _label(checked['region']['recognition_text'])
    if not anchor:
        raise ValueError('learned control has no supported text anchor; image-only reuse is unavailable')
    texts = [_label(s) for s in (candidate.text, candidate.label, candidate.element.text, candidate.element.label)]
    bound_ocr = False
    if REASON in getattr(local, 'reasons', ()):
        bound_ocr = has_current_control_ocr_binding(candidate, local, uia, screenshot_sha256)
        if not bound_ocr:
            raise ValueError('learned control current control OCR binding is invalid')
        from app.operation.recognition.control_target import control_target_matches
        expected = recognition_target_from_learned_control(checked, semantic_action=semantic_action)
        if expected is None or not control_target_matches(candidate.label, candidate.role, expected):
            raise ValueError('learned control current target differs')
    ocr_matches = bound_ocr or _label(local.matched_text) == anchor
    if semantic_action not in {'fill_field', 'scroll_region'} and control_target is not None:
        from app.operation.recognition.control_target import control_target_ocr_matches
        if control_target != recognition_target_from_learned_control(checked, semantic_action=semantic_action):
            raise ValueError('learned control current target differs')
        if not ocr_matches:
            # 空白容错只复用当前候选的真实全图 OCR 佐证，不凭标签或历史坐标放行。
            ocr_matches = (
                control_target_ocr_matches(local.matched_text, candidate.role, control_target,
                                           candidate_label=candidate.label)
                and local.candidate_id == candidate.candidate_id and local.element_id == candidate.element_id
                and local.coordinate_source == 'vista_point_v1_corroborated_by_local_ocr'
                and _placeholder_inside_current_field(local, candidate.element.bbox.to_dict())
                and _contains(local.matched_text_bbox, local.refined_click_point)
            )
    if anchor not in texts or not ocr_matches:
        raise ValueError('learned control current recognition differs')
    if semantic_action == 'fill_field':
        editable, reason = _editable_text_controls(uia['controls'], local.refined_click_point)
        if reason is not None:
            raise ValueError('learned control current text target is missing or ambiguous')
        target = editable[0]
        matches = [c for c in uia['controls'] if (
                       _label(c.get('name')) == anchor or _placeholder_inside_current_field(local, target['bbox']))
                   and c.get('control_id') == target['control_id']
                   and c.get('bbox') == target['bbox']]
    elif semantic_action == 'scroll_region':
        from app.agent.fresh_scroll_region import current_scroll_container
        target = current_scroll_container(uia['controls'], local.refined_click_point)
        matches = [c for c in uia['controls'] if c == target and _label(c.get('name')) == anchor]
    else:
        from app.operation.recognition.control_target import uia_control_matches
        matches = [c for c in uia['controls'] if _actionable(c) and c.get('enabled') is True
                   and c.get('visible') is True and _label(c.get('name')) == anchor
                   and (control_target is None or uia_control_matches(c, control_target))
                   and _contains(c['bbox'], local.refined_click_point)]
    if len(matches) != 1 or not _contains(matches[0]['bbox'], local.refined_click_point):
        raise ValueError('learned control current target is missing or ambiguous')
    # 旧框仅保留在版本证据中；执行坐标仍只来自当前截图的定位结果。
