"""显式行选择语义和来源证明；普通点击不享有无输入例外。"""
from copy import deepcopy
from hashlib import sha256

from app.desktop_review.external_mapping import canonical_json_bytes


def selection_requested(action):
    return isinstance(action, dict) and action.get('selection_intent') == 'ensure_selected'


def validate_selection_intent(action, strategies=None):
    if not isinstance(action, dict):
        raise ValueError('selection_action_invalid')
    if action.get('selection_intent') is None:
        return
    if (not selection_requested(action) or action.get('kind') != 'click'
            or action.get('click_kind', 'single') != 'single'):
        raise ValueError('selection_intent_invalid')
    if strategies is not None and (not isinstance(strategies, list) or len(strategies) != 1
            or not isinstance(strategies[0], dict) or strategies[0].get('kind') != 'visible_row'
            or strategies[0].get('row', {}).get('control_type') != 'ListItem'
            or strategies[0].get('action', {}).get('source') != 'row_name'):
        raise ValueError('selection_row_name_rule_required')


def request_digest(request):
    semantic = {key: deepcopy(request.get(key)) for key in ('goal', 'target_memory', 'selection_intent')}
    semantic['click_kind'] = request.get('click_kind', 'single')
    return sha256(canonical_json_bytes(semantic)).hexdigest()


def validate_selection_state(resolution, expected=None):
    from app.agent.native_identity import validate_native_identity_fact
    from .workflow_verification import _identity
    from .uia_rows import _inside
    state = resolution.get('row_selection')
    frame, candidate = resolution.get('frame', {}), resolution.get('candidate', {})
    row = resolution.get('evidence', {}).get('row', {})
    if (resolution.get('status') != 'matched' or resolution.get('context_verified') is not True
            or not isinstance(state, dict) or state.get('source') != 'windows_uia'
            or state.get('kind') != 'row_selection' or state.get('state_available') is not True
            or type(state.get('selected')) is not bool or state.get('editing') is not False
            or state.get('scan', {}).get('graph_scan_complete') is not True
            or state.get('scan', {}).get('provider_tree_valid') is not True
            or state.get('label') != candidate.get('label')):
        raise ValueError('selection_state_unavailable_or_editing')
    for key in ('runtime_id', 'container_runtime_id'):
        value = state.get(key)
        if (not isinstance(value, list) or not value or any(type(x) is not int for x in value)
                or value != row.get(key)):
            raise ValueError('selection_row_identity_changed')
    identity = frame.get('window_identity', {})
    native = state.get('window_identity', {})
    if (not _identity(identity) or validate_native_identity_fact(native,
            target_window_handle=identity.get('handle'), expected_process_id=identity.get('process_id')) is None
            or any(native.get(a) != identity.get(b) for a, b in (
            ('target_window_handle', 'handle'), ('process_id', 'process_id'), ('process_create_time', 'process_create_time')))):
        raise ValueError('selection_window_identity_changed')
    rect, window, size = frame.get('window_rect'), state.get('window_rect'), frame.get('image_size')
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(x) is not int for x in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]
            or size != {'width': rect[2] - rect[0], 'height': rect[3] - rect[1]}
            or not isinstance(window, list) or len(window) != 4 or any(type(x) is not int for x in window)
            or window[2] <= 0 or window[3] <= 0
            or not isinstance(state.get('label'), str) or not state['label'].strip()
            or candidate.get('capture_id') != frame.get('capture_id')
            or not isinstance(frame.get('capture_id'), str) or not frame['capture_id']
            or candidate.get('viewport_size') != size or candidate.get('source') != 'memory_visible_row'):
        raise ValueError('selection_capture_geometry_invalid')
    box = state.get('bbox')
    if not _inside(box, {'x': 0, 'y': 0, 'w': window[2], 'h': window[3]}):
        raise ValueError('selection_row_bbox_invalid')
    capture_box = {**box, 'x': box['x'] + window[0] - rect[0], 'y': box['y'] + window[1] - rect[1]}
    viewport = {'x': 0, 'y': 0, 'w': size['width'], 'h': size['height']}
    point, action_box = candidate.get('click_point'), candidate.get('bbox')
    if (not _inside(capture_box, viewport) or not _inside(action_box, capture_box)
            or not isinstance(point, dict) or any(type(point.get(k)) is not int for k in ('x', 'y'))
            or not (action_box['x'] <= point['x'] < action_box['x'] + action_box['w']
                    and action_box['y'] <= point['y'] < action_box['y'] + action_box['h'])):
        raise ValueError('selection_point_geometry_invalid')
    if expected is not None:
        for key in ('runtime_id', 'container_runtime_id', 'window_identity', 'window_rect', 'label', 'bbox'):
            if state.get(key) != expected.get(key):
                raise ValueError('selection_' + key + '_changed')
    return deepcopy(state)


def selection_proof(request, bindings, before, after, *, action_executed, capture_loader=None):
    from pathlib import Path
    from io import BytesIO
    from PIL import Image
    from .target_recipe import validate_target_reference
    validate_selection_intent({'kind': 'click', **request})
    if (not selection_requested(request) or not isinstance(bindings, dict)
            or any(not isinstance(bindings.get(key), str) or not bindings[key]
                   for key in ('run_id', 'step_id', 'execution_request_id', 'command_sha256'))
            or type(action_executed) is not bool):
        raise ValueError('selection_binding_required')
    validate_selection_intent(bindings.get('action'))
    if (not selection_requested(bindings['action'])
            or bindings['action'].get('target_memory') != request.get('target_memory')):
        raise ValueError('selection_original_action_binding_required')
    original = validate_selection_state(before)
    final = validate_selection_state(after, original)
    if final['selected'] is not True or original['selected'] is action_executed:
        raise ValueError('selection_effect_unproven')
    if before.get('reference') != request.get('target_memory') or after.get('reference') != before.get('reference'):
        raise ValueError('selection_recipe_changed')
    validate_target_reference(before['reference'])
    root = bindings.get('session_directory')
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError('selection_session_required')
    root = Path(root).resolve()
    for current in (before, after):
        frame = current['frame']
        path = Path(frame['image_path']).resolve()
        if not path.is_relative_to(root / 'runtime-output'):
            raise ValueError('selection_capture_outside_session')
        raw = path.read_bytes() if capture_loader is None else capture_loader(path)
        if not isinstance(raw, bytes) or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('selection_capture_png_required')
        with Image.open(BytesIO(raw)) as image:
            if image.format != 'PNG':
                raise ValueError('selection_capture_png_required')
            image.load()
            size = {'width': image.width, 'height': image.height}
        digest = sha256(raw).hexdigest()
        if digest != frame['sha256'] or size != frame['image_size']:
            raise ValueError('selection_capture_hash_changed')
    if (before['frame']['window_identity'] != after['frame']['window_identity']
            or before['frame']['window_rect'] != after['frame']['window_rect']
            or any(before['candidate'].get(k) != after['candidate'].get(k)
                   for k in ('bbox', 'click_point', 'label', 'source', 'viewport_size'))):
        raise ValueError('selection_target_geometry_changed')
    if before['frame']['capture_id'] == after['frame']['capture_id']:
        raise ValueError('selection_new_observation_required')
    body = {'contract_version': 'row_selection_effect.v1', 'status': 'selected_after_dispatch' if action_executed else 'already_satisfied',
            'request_sha256': request_digest(request), 'binding': deepcopy(bindings),
            'reference': deepcopy(request['target_memory']), 'before': deepcopy(before), 'after': deepcopy(after),
            'action_executed': action_executed, 'action_required': action_executed, 'state_satisfied': True}
    return {**body, 'sha256': sha256(canonical_json_bytes(body)).hexdigest()}


def validate_selection_receipt(report, request, *, command=None, action_executed=None,
                               session_dir=None, expected_context=None, capture_loader=None):
    if not selection_requested(request) or not isinstance(report, dict) or type(action_executed) is not bool:
        return False
    try:
        proof = report['row_selection_proof']
        from pathlib import Path
        if (session_dir is None or Path(proof['binding']['session_directory']).resolve() != Path(session_dir).resolve()
                or not isinstance(expected_context, dict)
                or any(not isinstance(expected_context.get(key), str) or not expected_context[key]
                       for key in ('run_id', 'step_id', 'execution_request_id', 'command_sha256'))
                or any(proof['binding'].get(key) != value for key, value in expected_context.items()
                       if key in {'run_id', 'step_id', 'execution_request_id', 'command_sha256', 'action', 'inputs', 'outputs'})):
            return False
        expected = selection_proof(request, proof['binding'], proof['before'], proof['after'],
                                   action_executed=proof['action_executed'], capture_loader=capture_loader)
        if (proof != expected or report.get('action_executed') is not proof['action_executed']
                or (action_executed is not None and proof['action_executed'] is not action_executed)):
            return False
        if command is not None and proof['binding']['command_sha256'] != sha256(canonical_json_bytes(command)).hexdigest():
            return False
        from app.agent.native_identity import validate_native_identity_fact
        identity = proof['before']['frame']['window_identity']
        native = report.get('target_identity')
        if (report.get('contract_version') != 'local_direct_step_v1'
                or validate_native_identity_fact(native, target_window_handle=identity['handle'],
                    expected_process_id=identity['process_id']) is None
                or native.get('process_create_time') != identity['process_create_time']):
            return False
        if proof['action_executed'] is False and (report.get('capture') != proof['before']['frame']
                or report.get('observation', {}).get('status') != 'captured'
                or report.get('observation', {}).get('capture') != proof['after']['frame']):
            return False
        if report.get('phase') != 'returned' or report.get('status', 'completed') != 'completed':
            return False
        api = report.get('response') or {}
        data = api.get('data') or {}
        result = data.get('result', data)
        if (api.get('success') is not True or result.get('row_selection_proof') != proof
                or result.get('execution_path', {}).get('action_executed') is not proof['action_executed']):
            return False
        return True
    except (KeyError, TypeError, ValueError, OSError):
        return False
