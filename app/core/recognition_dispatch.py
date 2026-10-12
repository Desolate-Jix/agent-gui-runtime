"""只认原执行入口在输入前生成且绑定原请求的明确未派发证明。"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from PIL import Image


def capture_visibility_point_check(capture, *, image_path, point, bound_handle, bound_rect):
    """核对原采图的全窗坐标与遮罩；缺失元数据沿用原门禁。"""
    if not isinstance(capture, dict) or capture.get('capture_visibility') is None:
        return None
    visibility = capture['capture_visibility']
    if (not isinstance(visibility, dict) or visibility.get('contract_version') != 'bound_capture_visibility_v2'
            or visibility.get('allowed') is not True or visibility.get('coordinate_space') != 'window'
            or visibility.get('bound_window_handle') != bound_handle):
        raise ValueError('capture_visibility_source_invalid')
    regions = visibility.get('occluded_regions', [])
    if type(regions) is not list or len(regions) > 256 or visibility.get('masked') is not bool(regions):
        raise ValueError('capture_visibility_source_invalid')
    if not regions:
        return None
    size, rect = capture.get('image_size'), capture.get('window_rect')
    if (capture.get('roi') is not None or not isinstance(size, dict)
            or set(size) != {'width', 'height'}
            or any(type(size[key]) is not int or size[key] <= 0 for key in size)
            or type(rect) not in (list, tuple) or list(rect) != list(bound_rect)
            or len(rect) != 4 or any(type(value) is not int for value in rect)
            or rect[2] - rect[0] != size['width'] or rect[3] - rect[1] != size['height']
            or not isinstance(point, dict) or set(point) != {'x', 'y'}
            or any(type(point[key]) is not int for key in point)
            or not (0 <= point['x'] < size['width'] and 0 <= point['y'] < size['height'])):
        raise ValueError('capture_visibility_source_invalid')
    source_regions = []
    for region in regions:
        if (type(region) is not dict or set(region) != {'x', 'y', 'width', 'height'}
                or any(type(region[key]) is not int for key in region)
                or region['x'] < 0 or region['y'] < 0 or region['width'] <= 0 or region['height'] <= 0
                or region['x'] + region['width'] > size['width']
                or region['y'] + region['height'] > size['height']):
            raise ValueError('capture_visibility_source_invalid')
        source_regions.append(region)
    try:
        source = Path(str(capture['image_path'])).resolve(strict=True)
        if source != Path(str(image_path)).resolve(strict=True):
            raise ValueError('capture_visibility_source_invalid')
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('capture_visibility_source_invalid') from error
    if not any(region['x'] <= point['x'] < region['x'] + region['width']
            and region['y'] <= point['y'] < region['y'] + region['height'] for region in source_regions):
        return None
    try:
        data = source.read_bytes()
        with Image.open(BytesIO(data)) as image:
            if image.size != (size['width'], size['height']):
                raise ValueError('capture_visibility_source_invalid')
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('capture_visibility_source_invalid') from error
    digest = sha256(data).hexdigest()
    if capture.get('sha256') not in (None, digest):
        raise ValueError('capture_visibility_source_invalid')
    source_capture = {'image_path': str(source), 'image_size': dict(size),
        'window_rect': list(rect), 'roi': None, 'sha256': digest,
        'capture_visibility': json.loads(json.dumps(visibility, ensure_ascii=False))}
    return {'contract_version': 'capture_visibility_point_check.v1', 'status': 'rejected',
        'error_code': 'capture_source_point_occluded', 'action_executed': False,
        'click_point': dict(point), 'source_sha256': digest,
        'source_image_path': str(source), 'source_capture': source_capture,
        'bound_window_handle': bound_handle, 'bound_window_rect': list(bound_rect)}


def _capture_visibility_rejection_matches(data, point, reason):
    check = data.get('capture_visibility_check')
    if (not isinstance(check, dict) or set(check) != {'contract_version', 'status', 'error_code',
            'action_executed', 'click_point', 'source_sha256', 'source_image_path',
            'source_capture', 'bound_window_handle', 'bound_window_rect'}
            or check.get('click_point') != point or check.get('error_code') != reason
            or data.get('selected_click_point_coordinate_space') != 'capture_image_pixels'):
        return False
    try:
        scene = data.get('agent_grounding_dispatch_scene')
        live_capture = data.get('live_capture')
        if (isinstance(scene, dict) and Path(str(scene.get('image_path'))).resolve()
                != Path(check['source_image_path'])):
            return False
        if scene is None and data.get('memory_grounding_dispatch_scene') is None and (
                not isinstance(live_capture, dict)
                or Path(str(live_capture.get('image_path'))).resolve() != Path(check['source_image_path'])):
            return False
        actual = capture_visibility_point_check(check['source_capture'],
            image_path=check['source_image_path'], point=point,
            bound_handle=check['bound_window_handle'], bound_rect=check['bound_window_rect'])
    except (ValueError, TypeError, KeyError, OSError):
        return False
    return actual == check


def point_visibility_sequence_has_no_input(sequence):
    """只接受输入层原样记录的零按下序列；缺省不补造序列。"""
    return sequence is None or (isinstance(sequence, dict)
        and type(sequence.get('requested_click_count')) is int
        and sequence['requested_click_count'] in (1, 2)
        and type(sequence.get('completed_clicks')) is int and sequence['completed_clicks'] == 0
        and sequence.get('input_attempted') is False
        and sequence.get('button') in ('left', 'right', 'middle'))


def point_visibility_rejection_matches(evidence, *, point, reason, input_request=None, sequence=None):
    """点或完整区域拒绝都必须与原选择坐标、原错误相互印证。"""
    if (not isinstance(evidence, dict) or evidence.get('allowed') is not False
            or not isinstance(reason, str) or not 0 < len(reason) <= 256
            or evidence.get('reason') != reason
            or not isinstance(point, dict) or set(point) != {'x', 'y'}
            or any(type(point[key]) is not int for key in point)):
        return False
    if 'input_dispatch_boundary' in evidence:
        proof = evidence['input_dispatch_boundary']
        if (not isinstance(proof, dict) or set(proof) != {'contract_version', 'stage',
                'button_down_attempted', 'window_point', 'screen_point', 'bound_window',
                'button', 'requested_click_count', 'reason_code'}
                or proof.get('contract_version') != 'click_input_boundary.v1'
                or proof.get('stage') != 'before_first_mouse_down'
                or proof.get('button_down_attempted') is not False
                or proof.get('reason_code') != reason or proof.get('window_point') != point
                or not isinstance(proof.get('window_point'), dict)
                or any(type(value) is not int for value in proof['window_point'].values())
                or not (evidence.get('contract_version') == 'nonmodal_parent_click_v1'
                    or (reason == 'popup_continuation_guard_invalid'
                        and evidence.get('stage') in ('command', 'before_mouse_down')
                        and isinstance(evidence.get('error_type'), str) and evidence['error_type']))):
            return False
        screen, bound = proof.get('screen_point'), proof.get('bound_window')
        if (not isinstance(screen, dict) or set(screen) != {'x', 'y'}
                or any(type(screen[key]) is not int for key in screen)
                or not isinstance(bound, dict) or set(bound) != {'handle', 'process_id', 'rect'}
                or any(type(bound.get(key)) is not int or bound[key] <= 0 for key in ('handle', 'process_id'))
                or not isinstance(bound.get('rect'), list) or len(bound['rect']) != 4
                or any(type(value) is not int for value in bound['rect'])
                or proof.get('button') not in ('left', 'right', 'middle')
                or type(proof.get('requested_click_count')) is not int or proof['requested_click_count'] not in (1, 2)):
            return False
        left, top, right, bottom = bound['rect']
        if (not (left < right and top < bottom and 0 <= point['x'] < right - left
                and 0 <= point['y'] < bottom - top)
                or screen != {'x': left + point['x'], 'y': top + point['y']}):
            return False
        # 与 API 在进入输入函数前冻结的请求交叉核对，不能只看证明形状合法。
        keys = {'window_point', 'bound_window', 'button', 'requested_click_count'}
        return (isinstance(input_request, dict) and set(input_request) == keys
            and input_request == {key: proof[key] for key in keys}
            and type(input_request['requested_click_count']) is int
            and all(type(value) is int for value in input_request['window_point'].values())
            and all(type(input_request['bound_window'][key]) is int for key in ('handle', 'process_id'))
            and type(input_request['bound_window']['rect']) is list
            and all(type(value) is int for value in input_request['bound_window']['rect'])
            and point_visibility_sequence_has_no_input(sequence)
            and (sequence is None or all(sequence[key] == proof[key]
                for key in ('button', 'requested_click_count'))))
    visible_point = evidence.get('point_visibility', evidence)
    if (not isinstance(visible_point, dict)
            or visible_point.get('contract_version') != 'bound_point_visibility_v1'
            or visible_point.get('window_point') != point):
        return False
    region = evidence.get('region_visibility')
    if region is not None:
        return (isinstance(region, dict) and region.get('allowed') is False
            and region.get('reason') == reason and type(visible_point.get('allowed')) is bool)
    return visible_point.get('allowed') is False


def recognition_plan_rejected_before_dispatch(response):
    if not isinstance(response, dict) or response.get('success') is not False:
        return False
    error, data = response.get('error'), response.get('data')
    if (not isinstance(error, dict)
            or not isinstance(data, dict) or data.get('dispatch_status') != 'not_dispatched'
            or data.get('input_started') is not False):
        return False
    execution = data.get('execution_path')
    recognized = data.get('recognition_plan_response')
    fallback = data.get('fallback_plan')
    step = data.get('agent_step_result')
    common = (isinstance(execution, dict) and execution.get('action_executed') is False
        and (data.get('action_executed') is None or data.get('action_executed') is False)
        and isinstance(fallback, dict) and fallback.get('contract_version') == 'execute_fallback_plan_v1'
        and type(fallback.get('attempt_count')) is int and fallback['attempt_count'] == 0
        and isinstance(step, dict) and step.get('contract_version') == 'agent_step_result_v1'
        and step.get('action_executed') is False
        and not data.get('attempts') and (point_visibility_sequence_has_no_input(data.get('click_sequence'))
            if data.get('dispatch_stage') == 'point_visibility' else not data.get('click_sequence')))
    if not common:
        return False
    if data.get('dispatch_stage') == 'recognition_plan':
        return (error.get('code') == 'recognition_plan_failed'
            and isinstance(recognized, dict) and type(recognized.get('success')) is bool
            and (recognized['success'] is False or not recognized.get('data'))
            and step.get('status') == 'blocked' and step.get('pre_click_allowed') is False
            and step.get('selected_click_point') is None)
    proof = data.get('pre_click_input_rejection')
    point = data.get('selected_click_point')
    decision = data.get('pre_click_decision')
    if data.get('dispatch_stage') == 'decision_check':
        proof = data.get('decision_check_no_dispatch')
        judgment, details = data.get('decision_judgment'), error.get('details')
        return (isinstance(proof, dict) and set(proof) == {
                'contract_version', 'stage', 'click_dispatch_started', 'reason_code'}
            and proof.get('contract_version') == 'decision_check_no_dispatch.v1'
            and proof.get('stage') == 'before_click_point' and proof.get('click_dispatch_started') is False
            and isinstance(proof.get('reason_code'), str) and 0 < len(proof['reason_code']) <= 256
            and proof['reason_code'] == error.get('code')
            and isinstance(judgment, dict) and isinstance(details, dict)
            and set(details) == {'status', 'verdict', 'reason', 'automatic_retry_allowed'}
            and isinstance(judgment.get('status'), str) and 0 < len(judgment['status']) <= 256
            and all(details.get(key) == judgment.get(key) for key in ('status', 'verdict', 'reason'))
            and details.get('automatic_retry_allowed') is False and data.get('automatic_retry_allowed') is False
            and isinstance(point, dict) and set(point) == {'x', 'y'}
            and all(type(point[key]) is int for key in point)
            and isinstance(decision, dict) and decision.get('contract_version') in {
                'pre_click_decision_v1', 'local_operator_recognition_selection_v1'}
            and decision.get('allowed') is True and decision.get('selected_click_point') == point
            and step.get('status') == 'blocked' and step.get('pre_click_allowed') is True
            and step.get('selected_click_point') == point
            and data.get('attempts') == [] and 'click_sequence' not in data)
    if data.get('dispatch_stage') == 'point_visibility':
        proof = data.get('point_visibility_no_dispatch')
        evidence = error.get('details')
        return (isinstance(proof, dict) and set(proof) == {
                'contract_version', 'stage', 'button_down_attempted', 'reason_code'}
            and proof.get('contract_version') == 'point_visibility_no_dispatch.v1'
            and proof.get('stage') == 'before_first_mouse_down'
            and proof.get('button_down_attempted') is False
            and proof.get('reason_code') == error.get('code')
            and point_visibility_rejection_matches(evidence, point=point, reason=proof.get('reason_code'),
                input_request=data.get('input_dispatch_request'), sequence=data.get('click_sequence'))
            and data.get('point_visibility') == evidence.get('point_visibility', evidence)
            and data.get('region_visibility') == evidence.get('region_visibility')
            and isinstance(decision, dict) and decision.get('contract_version') in {
                'pre_click_decision_v1', 'local_operator_recognition_selection_v1'}
            and decision.get('allowed') is True and decision.get('selected_click_point') == point
            and step.get('status') == 'blocked' and step.get('pre_click_allowed') is True
            and step.get('selected_click_point') == point and data.get('attempts') == [])
    valid = (data.get('dispatch_stage') == 'pre_click_validation'
        and error.get('code') == 'recognition_plan_click_failed'
        and isinstance(proof, dict) and set(proof) == {
            'contract_version', 'validator', 'reason_code', 'click_dispatch_started'}
        and proof.get('contract_version') == 'recognition_pre_click_rejection.v1'
        and proof.get('click_dispatch_started') is False
        and isinstance(proof.get('reason_code'), str) and 0 < len(proof['reason_code']) <= 256
        and proof['reason_code'] == error.get('details')
        and isinstance(point, dict) and set(point) == {'x', 'y'}
        and all(type(point[key]) is int for key in ('x', 'y'))
        and isinstance(decision, dict) and decision.get('contract_version') in {
            'pre_click_decision_v1', 'local_operator_recognition_selection_v1'}
        and decision.get('selected_click_point') == point
        and decision.get('allowed') is True and step.get('pre_click_allowed') is True
        and step.get('status') == 'execution_failed' and step.get('selected_click_point') == point
        and data.get('attempts') == [] and 'click_sequence' not in data)
    if not valid:
        return False
    if proof.get('validator') == 'text_focus':
        diagnostic = data.get('text_field_diagnostic')
        return isinstance(diagnostic, dict) and diagnostic.get('reason_code') == proof['reason_code']
    if proof.get('validator') == 'structured_target':
        check = data.get('task_plan_dispatch_target_check')
        return (isinstance(check, dict) and check.get('status') == 'rejected'
            and check.get('action_executed') is False and check.get('error_code') == proof['reason_code'])
    if proof.get('validator') == 'control_target':
        check = data.get('control_target_check')
        return (isinstance(check, dict) and check.get('status') == 'rejected'
            and check.get('action_executed') is False and check.get('error_code') == proof['reason_code'])
    if proof.get('validator') == 'capture_visibility':
        return _capture_visibility_rejection_matches(data, point, proof['reason_code'])
    return False


def _receipt_digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _type_text_no_dispatch_proof(receipt):
    """核对公开证明的一致性；原回执仍须经过宿主票据和文件摘要认证。"""
    from app.agent.native_identity import validate_native_identity_fact
    if (not isinstance(receipt, dict) or receipt.get('contract_version') != 'local_direct_step_v1'
            or receipt.get('operation') != 'type_text'):
        return None
    request, identity, geometry = (receipt.get(key) for key in
        ('request', 'target_identity', 'target_window_geometry'))
    response = receipt.get('response')
    if (not isinstance(request, dict) or not isinstance(identity, dict) or not isinstance(geometry, dict)
            or not isinstance(response, dict) or response.get('success') is not False
            or geometry.get('coordinate_space') != 'screen_pixels' or geometry.get('rect_format') != 'ltrb'):
        return None
    handle, pid, rect = identity.get('target_window_handle'), identity.get('process_id'), geometry.get('rect')
    if (validate_native_identity_fact(identity, target_window_handle=handle, expected_process_id=pid) is None
            or type(rect) is not list or len(rect) != 4 or any(type(v) is not int for v in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]
            or any(type(request.get(key)) is not int for key in ('x', 'y', 'text_length'))
            or request['text_length'] <= 0
            or not 0 <= request['x'] < rect[2] - rect[0] or not 0 <= request['y'] < rect[3] - rect[1]
            or type(request.get('text_sha256')) is not str or len(request['text_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in request['text_sha256'])
            or any(type(request.get(key)) is not bool for key in ('click_before_typing', 'clear_existing'))
            or request.get('dry_run') is not False or request.get('submit') is not False):
        return None
    data, error = response.get('data'), response.get('error')
    if (not isinstance(data, dict) or data.get('contract_version') != 'type_text_result_v1'
            or not isinstance(error, dict) or error.get('code') != 'type_text_failed'
            or type(error.get('details')) is not str or not error['details']
            or data.get('dry_run') is not False or data.get('submit') is not False
            or type(data.get('text_length')) is not int or data['text_length'] != request['text_length']
            or data.get('point') != {'x': request['x'], 'y': request['y']}
            or any(data.get(key) is not request[key] for key in ('click_before_typing', 'clear_existing'))
            or data.get('input_started') is not False or 'type_result' in data
            or 'action_executed' in data and data['action_executed'] is not False):
        return None
    execution, context, dispatch = (data.get(key) for key in
        ('execution_path', 'operation_context', 'typing_dispatch'))
    expected = {'schema': 'typing_dispatch.v1',
        **{key + '_dispatch': 'not_started' for key in ('focus', 'selection', 'text', 'submit')},
        'input_started': False, 'action_executed': False, 'events': [], 'artifact_is_authorization': False}
    if (not isinstance(execution, dict) or execution.get('action_executed') is not False
            or not isinstance(context, dict) or context.get('contract_version') != 'operation_runtime_context_v1'
            or context.get('skill_id') != 'type_text' or context.get('window_binding_id') != 'window:' + str(handle)
            or context.get('viewport_size') != {'width': rect[2] - rect[0], 'height': rect[3] - rect[1]}
            or not isinstance(dispatch, dict) or set(dispatch) != set(expected)
            or dispatch != expected or any(dispatch[key] is not False for key in
                ('input_started', 'action_executed', 'artifact_is_authorization'))):
        return None
    return {'contract_version': 'type_text_no_dispatch.v1', 'stage': 'before_first_input',
        'request_sha256': _receipt_digest(request), 'target_identity_sha256': _receipt_digest(identity),
        'window_geometry_sha256': _receipt_digest(geometry), 'response_sha256': _receipt_digest(response)}


def type_text_rejected_before_dispatch(receipt):
    if (not isinstance(receipt, dict) or receipt.get('phase') != 'not_dispatched'
            or receipt.get('action_executed') is not False or not isinstance(receipt.get('type_text_no_dispatch'), dict)):
        return False
    try:
        expected = _type_text_no_dispatch_proof(receipt)
        return expected is not None and receipt['type_text_no_dispatch'] == expected
    except (ValueError, TypeError, OverflowError):
        return False


def _key_no_dispatch_proof(receipt):
    from app.agent.native_identity import validate_native_identity_fact
    from app.core.editing_keys import EDITING_KEY_CHORDS
    if (not isinstance(receipt, dict) or receipt.get('contract_version') != 'local_direct_step_v1'
            or receipt.get('operation') != 'press_key'):
        return None
    request, identity, geometry, response = (receipt.get(key) for key in
        ('request', 'target_identity', 'target_window_geometry', 'response'))
    if (not isinstance(request, dict) or not isinstance(identity, dict) or not isinstance(geometry, dict)
            or not isinstance(response, dict) or response.get('success') is not False
            or geometry.get('coordinate_space') != 'screen_pixels' or geometry.get('rect_format') != 'ltrb'):
        return None
    handle, pid, rect = identity.get('target_window_handle'), identity.get('process_id'), geometry.get('rect')
    if (validate_native_identity_fact(identity, target_window_handle=handle, expected_process_id=pid) is None
            or type(rect) is not list or len(rect) != 4 or any(type(v) is not int for v in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]
            or type(request.get('key')) is not str or request['key'] not in EDITING_KEY_CHORDS
            or any(type(request.get(key)) is not int for key in ('x', 'y'))
            or not 0 <= request['x'] < rect[2] - rect[0] or not 0 <= request['y'] < rect[3] - rect[1]):
        return None
    data, error = response.get('data'), response.get('error')
    if (not isinstance(data, dict) or data.get('contract_version') != 'press_key_result_v1'
            or not isinstance(error, dict) or error.get('code') not in {'key_dispatch_failed', 'keyboard_target_not_foreground'}
            or type(error.get('details')) is not str or not error['details']
            or data.get('pressed') is not False or data.get('input_started') is not False
            or data.get('dispatch_status') != 'not_dispatched' or data.get('automatic_retry_allowed') is not False
            or data.get('key') != request['key'] or data.get('point') != {'x': request['x'], 'y': request['y']}):
        return None
    expected = {'schema': 'key_dispatch.v1', 'key': request['key'], 'point': {'x': request['x'], 'y': request['y']},
        'dispatch': 'not_started', 'input_started': False, 'action_executed': False,
        'events': [], 'artifact_is_authorization': False}
    dispatch = data.get('key_dispatch')
    if (not isinstance(dispatch, dict) or set(dispatch) != set(expected) or dispatch != expected
            or any(dispatch[key] is not False for key in ('input_started', 'action_executed', 'artifact_is_authorization'))):
        return None
    if error['code'] == 'keyboard_target_not_foreground':
        diagnostic = data.get('diagnostics')
        if (not isinstance(diagnostic, dict) or diagnostic.get('stage') != 'before_keyboard_dispatch'
                or type(diagnostic.get('expected_window_handle')) is not int or diagnostic['expected_window_handle'] != handle
                or type(diagnostic.get('observed_foreground_handle')) is not int
                or diagnostic['observed_foreground_handle'] == handle):
            return None
    return {'contract_version': 'key_no_dispatch.v1', 'stage': 'before_first_key',
        'request_sha256': _receipt_digest(request), 'target_identity_sha256': _receipt_digest(identity),
        'window_geometry_sha256': _receipt_digest(geometry), 'response_sha256': _receipt_digest(response)}


def key_rejected_before_dispatch(receipt):
    if (not isinstance(receipt, dict) or receipt.get('phase') != 'not_dispatched'
            or receipt.get('action_executed') is not False or not isinstance(receipt.get('key_no_dispatch'), dict)):
        return False
    try:
        expected = _key_no_dispatch_proof(receipt)
        return expected is not None and receipt['key_no_dispatch'] == expected
    except (ValueError, TypeError, OverflowError):
        return False


def local_receipt_zero_input_verified(receipt, operation=None):
    """外层零输入事实必须由确定的原 receipt 或严格未派发证明支持。"""
    from app.core.receipt_action import _receipt_action
    from .local_step_no_dispatch import pre_capture_failure_verified
    if pre_capture_failure_verified(receipt, operation):
        return True
    if (not isinstance(receipt, dict) or receipt.get('contract_version') != 'local_direct_step_v1'
            or receipt.get('action_executed') is not None and receipt.get('action_executed') is not False):
        return False
    operation = operation or receipt.get('operation', 'execute_recognition_plan')
    if operation == 'type_text':
        return type_text_rejected_before_dispatch(receipt)
    if operation == 'press_key':
        return key_rejected_before_dispatch(receipt)
    if _receipt_action(receipt, operation) is not False:
        return False
    if receipt.get('phase') == 'returned':
        return True
    return (operation == 'execute_recognition_plan' and receipt.get('operation') == operation
        and receipt.get('phase') == 'not_dispatched' and receipt.get('action_executed') is False
        and recognition_plan_rejected_before_dispatch(receipt.get('response')))
