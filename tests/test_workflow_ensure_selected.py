from copy import deepcopy

import pytest

from app.api.models.request import ExecuteRecognitionPlanRequest
from app.learning_memory.target_recipe import action_semantics_sha256, validate_editorial_action
from app.learning_memory.workflow_trial import _command
from test_workflow_row_self_target import name_scene


REF = {'recipe_id': 'target-recipe-' + 'c' * 64, 'interface_key': 'rows', 'state_key': 'normal'}


def action():
    return {'kind': 'click', 'goal': 'Select the bound row', 'target_memory': REF,
            'selection_intent': 'ensure_selected'}


def test_original_step_preserves_explicit_selection_intent():
    command = _command({'action': action()}, {}, {})
    assert command['request']['selection_intent'] == 'ensure_selected'
    assert command['operation'] == 'execute_recognition_plan'


def test_selection_intent_is_a_distinct_recipe_semantic():
    _, strategy, _, _ = name_scene()
    scope = {'task_id': 'test', 'interface_key': 'rows', 'state_key': 'normal'}
    ordinary = action()
    ordinary.pop('selection_intent')
    assert action_semantics_sha256(action(), scope=scope, strategies=[strategy]) != action_semantics_sha256(
        ordinary, scope=scope, strategies=[strategy])


@pytest.mark.parametrize('mutation', ['double', 'input', 'fixed', 'whole_row', 'unknown'])
def test_selection_intent_never_spreads_to_ordinary_actions(mutation):
    _, strategy, _, _ = name_scene()
    value = action()
    if mutation == 'double':
        value['click_kind'] = 'double'
    elif mutation == 'input':
        value.update(kind='input_sequence', field_goal='Field', submit_search=False)
    elif mutation == 'fixed':
        strategy = {'kind': 'uia', 'control_type': 'Button', 'name': 'Choose'}
    elif mutation == 'whole_row':
        strategy['action'] = {'source': 'row', 'control_type': 'ListItem'}
    else:
        value['selection_intent'] = 'other'
    with pytest.raises(ValueError, match='selection'):
        validate_editorial_action({'contract_version': 'target_recipe.v3', 'strategies': [strategy]}, value)


def test_api_rejects_explicit_selection_without_binding_or_non_single():
    for request in ({'goal': 'Choose', 'selection_intent': 'ensure_selected'},
                    {'goal': 'Choose', 'target_memory': REF, 'selection_intent': 'ensure_selected', 'click_kind': 'double'}):
        with pytest.raises(ValueError, match='selection'):
            ExecuteRecognitionPlanRequest.model_validate(request)
    parsed = ExecuteRecognitionPlanRequest.model_validate({'goal': 'Choose', 'target_memory': REF,
                                                           'selection_intent': 'ensure_selected'})
    assert parsed.selection_intent == 'ensure_selected'


def test_row_selection_control_guard_rechecks_state_before_input():
    from app.core.local_control_target import LocalControlTarget, LocalControlTargetError
    state = {'source': 'windows_uia', 'runtime_id': [42, 9, 1], 'container_runtime_id': [42, 9],
             'window_identity': {'target_window_handle': 9, 'process_id': 8, 'process_create_time': 7.0},
             'window_rect': [0, 0, 200, 200], 'kind': 'row_selection', 'label': 'Fresh row',
             'bbox': {'x': 4, 'y': 40, 'w': 190, 'h': 21},
             'selected': False, 'editing': False, 'state_available': True}
    target = LocalControlTarget(lambda: deepcopy(state), deepcopy(state))
    assert target({'x': 30, 'y': 50})['status'] == 'matched'
    for field, changed in [('selected', True), ('editing', True), ('selected', None), ('container_runtime_id', [42, 10])]:
        original = state[field]
        state[field] = changed
        with pytest.raises(LocalControlTargetError):
            target({'x': 30, 'y': 50})
        state[field] = original


def test_public_endpoint_cannot_silently_dispatch_selection_intent(monkeypatch):
    from app.api import action as endpoint
    value = ExecuteRecognitionPlanRequest.model_validate({'goal': 'Choose', 'target_memory': REF,
                                                           'selection_intent': 'ensure_selected'})
    response = endpoint.execute_recognition_plan(value)
    assert not response.success
    assert 'selection_context_required' in str(response)


def selection_resolution(tmp_path, selected=True):
    from PIL import Image
    from hashlib import sha256
    image = tmp_path / 'runtime-output' / 'fresh.png'
    image.parent.mkdir(exist_ok=True)
    Image.new('RGB', (200, 200)).save(image)
    frame = {'capture_id': 'fresh-1', 'image_path': str(image), 'sha256': sha256(image.read_bytes()).hexdigest(),
             'image_size': {'width': 200, 'height': 200}, 'window_rect': [10, 20, 210, 220],
             'window_identity': {'handle': 9, 'process_id': 8, 'process_create_time': 7.0}}
    state = {'source': 'windows_uia', 'kind': 'row_selection', 'runtime_id': [42, 9, 1],
             'container_runtime_id': [42, 9], 'label': 'Fresh row', 'selected': selected, 'editing': False,
             'state_available': True, 'window_rect': [0, 0, 220, 240],
             'window_identity': {'contract_version': 'windows_native_identity_observation_v1',
                 'provider': 'windows_native_identity', 'status': 'observed', 'executable_path': 'C:/Apps/Fresh.exe',
                 'target_window_handle': 9, 'process_id': 8, 'process_create_time': 7.0},
             'bbox': {'x': 14, 'y': 60, 'w': 190, 'h': 21},
             'scan': {'graph_scan_complete': True, 'provider_tree_valid': True}}
    return {'status': 'matched', 'context_verified': True, 'reference': REF, 'goal': action()['goal'],
            'frame': frame, 'candidate': {'label': 'Fresh row', 'bbox': {'x': 4, 'y': 40, 'w': 90, 'h': 21},
                'click_point': {'x': 49, 'y': 50}, 'viewport_size': frame['image_size'],
                'capture_id': frame['capture_id'], 'source': 'memory_visible_row'},
            'evidence': {'row': {'runtime_id': state['runtime_id'], 'container_runtime_id': state['container_runtime_id']}},
            'row_selection': state}


def test_memory_selection_preflight_is_explicit_and_bound_to_original_row(tmp_path):
    from app.core.memory_grounding_target import MemoryGroundingTarget
    current = selection_resolution(tmp_path)
    target = MemoryGroundingTarget(REF, current, read_current=lambda *args: deepcopy(current),
        selection_request={'goal': action()['goal'], 'target_memory': REF, 'selection_intent': 'ensure_selected'},
        selection_bindings={'run_id': 'run', 'step_id': 'step', 'execution_request_id': 'exec',
                            'command_sha256': 'a' * 64})
    assert target.selection_preflight()['selected'] is True
    current['row_selection']['editing'] = True
    with pytest.raises(ValueError, match='selection'):
        target.selection_preflight()

    current['row_selection']['editing'] = False
    current['row_selection']['runtime_id'] = [42, 9, 2]
    with pytest.raises(ValueError, match='selection'):
        target.selection_preflight()


def test_shared_proof_rejects_tampering_and_unknown_input(tmp_path):
    from hashlib import sha256
    from app.desktop_review.external_mapping import canonical_json_bytes
    from app.learning_memory.selection_satisfaction import selection_proof, validate_selection_receipt
    request = {'goal': action()['goal'], 'target_memory': REF, 'selection_intent': 'ensure_selected'}
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': request}
    bindings = {'run_id': 'run', 'step_id': 'step', 'execution_request_id': 'exec',
                'command_sha256': sha256(canonical_json_bytes(command)).hexdigest(),
                'session_directory': str(tmp_path), 'action': action(), 'inputs': {}, 'outputs': {}}
    before = selection_resolution(tmp_path)
    after = deepcopy(before)
    after['frame']['capture_id'] = 'fresh-2'
    after['candidate']['capture_id'] = 'fresh-2'
    proof = selection_proof(request, bindings, before, after, action_executed=False)
    report = {'contract_version': 'local_direct_step_v1', 'phase': 'returned', 'action_executed': False,
              'capture': before['frame'], 'observation': {'status': 'captured', 'capture': after['frame']},
              'target_identity': before['row_selection']['window_identity'], 'row_selection_proof': proof,
              'response': {'success': True, 'data': {'result': {'row_selection_proof': deepcopy(proof),
                          'execution_path': {'action_executed': False}}}}}
    assert validate_selection_receipt(report, request, command=command, action_executed=False,
                                      session_dir=tmp_path, expected_context=bindings)
    for key in ('request_sha256', 'reference', 'sha256'):
        changed = deepcopy(report)
        changed['row_selection_proof'][key] = None
        assert not validate_selection_receipt(changed, request, command=command, action_executed=False,
                                              session_dir=tmp_path, expected_context=bindings)
    changed = deepcopy(report)
    changed['action_executed'] = None
    assert not validate_selection_receipt(changed, request, command=command, action_executed=False,
                                          session_dir=tmp_path, expected_context=bindings)


@pytest.mark.parametrize('mutation', ['identity', 'native_identity', 'bbox', 'label', 'viewport', 'point', 'capture'])
def test_selection_state_requires_complete_current_identity_and_geometry(tmp_path, mutation):
    from app.learning_memory.selection_satisfaction import validate_selection_state
    current = selection_resolution(tmp_path)
    if mutation == 'identity':
        current['frame']['window_identity'] = {}
        current['row_selection']['window_identity'] = {}
    elif mutation == 'native_identity':
        current['row_selection']['window_identity'].pop('process_create_time')
    elif mutation in {'bbox', 'label'}:
        current['row_selection'].pop(mutation)
        if mutation == 'label':
            current['candidate'].pop('label')
    elif mutation == 'viewport':
        current['candidate']['viewport_size']['height'] = 1
    elif mutation == 'point':
        current['candidate']['click_point']['x'] = 199
    else:
        current['candidate']['capture_id'] = 'old'
    with pytest.raises(ValueError, match='selection'):
        validate_selection_state(current)


def satisfied_receipt(tmp_path):
    from hashlib import sha256
    from app.desktop_review.external_mapping import canonical_json_bytes
    from app.learning_memory.selection_satisfaction import selection_proof
    request = {'goal': action()['goal'], 'target_memory': REF, 'selection_intent': 'ensure_selected'}
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': request}
    bindings = {'run_id': 'run', 'step_id': 'step', 'execution_request_id': 'exec',
                'command_sha256': sha256(canonical_json_bytes(command)).hexdigest(),
                'session_directory': str(tmp_path), 'action': action(), 'inputs': {}, 'outputs': {}}
    before = selection_resolution(tmp_path)
    after = deepcopy(before)
    after['frame']['capture_id'] = after['candidate']['capture_id'] = 'fresh-2'
    proof = selection_proof(request, bindings, before, after, action_executed=False)
    report = {'contract_version': 'local_direct_step_v1', 'phase': 'returned', 'action_executed': False,
              'capture': before['frame'], 'observation': {'status': 'captured', 'capture': after['frame']},
              'target_identity': before['row_selection']['window_identity'], 'row_selection_proof': proof,
              'response': {'success': True, 'data': {'result': {'row_selection_proof': deepcopy(proof),
                          'execution_path': {'action_executed': False}}}}}
    return command, bindings, report


def test_original_trial_distinguishes_state_satisfaction_from_input(tmp_path):
    import json
    from app.learning_memory.workflow_trial import _receipt_state, _actual_action_executed
    command, bindings, report = satisfied_receipt(tmp_path)
    receipt = {'request_id': 'exec', 'status': 'returned', 'command': command, 'result': report}
    path = tmp_path / 'responses' / 'exec.json'
    path.parent.mkdir()
    (tmp_path / 'commands').mkdir()
    (tmp_path / 'commands' / 'exec.json').write_text(json.dumps(command), encoding='utf-8')
    path.write_text(json.dumps(receipt), encoding='utf-8')
    complete, _, _ = _receipt_state(receipt, path, 'exec', command, expected_context=bindings)
    assert complete is True
    assert _actual_action_executed(report) is False
    with pytest.raises(ValueError, match='selection'):
        _receipt_state(receipt, path, 'exec', command, expected_context={**bindings, 'run_id': 'another-run'})


@pytest.mark.parametrize('key', ['run_id', 'step_id', 'execution_request_id'])
def test_original_proof_cannot_be_replayed_for_another_step(tmp_path, key):
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    command, bindings, report = satisfied_receipt(tmp_path)
    assert not validate_selection_receipt(report, command['request'], command=command, session_dir=tmp_path,
        expected_context={**bindings, key: 'different'}, action_executed=False)


def test_proof_refuses_non_png_and_capture_outside_original_session(tmp_path):
    from app.learning_memory.selection_satisfaction import selection_proof
    from hashlib import sha256
    command, bindings, report = satisfied_receipt(tmp_path)
    before = deepcopy(report['row_selection_proof']['before'])
    after = deepcopy(report['row_selection_proof']['after'])
    outside = tmp_path / 'other.txt'
    outside.write_text('not an image', encoding='utf-8')
    before['frame'].update(image_path=str(outside), sha256=sha256(outside.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='outside_session'):
        selection_proof(command['request'], bindings, before, after, action_executed=False)
    invalid = tmp_path / 'runtime-output' / 'invalid.png'
    invalid.write_bytes(b'invalid image')
    before['frame'].update(image_path=str(invalid), sha256=sha256(invalid.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='png_required'):
        selection_proof(command['request'], bindings, before, after, action_executed=False)


def test_ordinary_normalized_click_preserves_old_semantic_hash():
    from app.execution.local_action_contract import _validated_request
    from app.learning_memory.target_recipe import action_semantics_sha256
    current = _validated_request('execute_recognition_plan', {'goal': 'select item'})
    assert current.get('selection_intent') is None
    original = {'kind': 'click', 'goal': 'select item'}
    scope = {'task_id': 'task', 'interface_key': 'main', 'state_key': 'ready'}
    strategies = [{'kind': 'uia', 'name': 'item', 'control_type': 'Button'}]
    assert action_semantics_sha256({**original, 'selection_intent': current.get('selection_intent')}, scope=scope, strategies=strategies) == action_semantics_sha256(original, scope=scope, strategies=strategies)


def test_selection_receipt_requires_complete_external_binding(tmp_path):
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    command, bindings, report = satisfied_receipt(tmp_path)
    for key in ('run_id', 'step_id', 'execution_request_id', 'command_sha256'):
        incomplete = {k: v for k, v in bindings.items() if k != key}
        assert not validate_selection_receipt(report, command['request'], command=command,
            action_executed=False, session_dir=tmp_path, expected_context=incomplete)


from tests.test_local_step_timings import timed_scene


def owner_selection_scene(timed_scene, tmp_path, monkeypatch, selected):
    from types import SimpleNamespace
    from app.execution import local_direct_step as direct
    from app.core.memory_grounding_target import MemoryGroundingTarget
    co, events, _, _ = timed_scene
    command, bindings, report = satisfied_receipt(tmp_path)
    current = selection_resolution(tmp_path, selected=selected)
    counter = [0]
    def read(*args):
        counter[0] += 1
        result = deepcopy(current)
        result['frame']['capture_id'] = result['candidate']['capture_id'] = 'fresh-' + str(counter[0])
        return result
    target = MemoryGroundingTarget(REF, current, read_current=read,
        selection_request=command['request'], selection_bindings=bindings)
    co._runtime_output_root = tmp_path / 'runtime-output'
    co._uses_production_factory = False
    co._windows().bind_window_by_handle = lambda handle: SimpleNamespace(handle=9, process_id=8,
        rect=SimpleNamespace(left=10, top=20, right=210, bottom=220))
    monkeypatch.setattr(direct, 'WindowsNativeIdentityReader', lambda **kwargs:
        SimpleNamespace(read_identity=lambda handle: deepcopy(current['row_selection']['window_identity'])))
    class Capture:
        def __init__(self, **kwargs): pass
        def capture_window(self, **kwargs):
            return {**deepcopy(current['frame']), 'image_width': 200, 'image_height': 200}
    monkeypatch.setattr(direct, 'ScreenshotService', Capture)
    return co, events, command, bindings, current, target


def test_original_owner_satisfied_selection_never_enters_dispatch(timed_scene, tmp_path, monkeypatch):
    from app.execution import local_direct_step as direct
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    co, events, command, bindings, current, target = owner_selection_scene(timed_scene, tmp_path, monkeypatch, True)
    monkeypatch.setattr(direct, '_post_action', lambda *args: pytest.fail('input route entered'))
    report = co.execute_local_step(target_window_handle=9, target_process_id=8,
        operation=command['operation'], request=command['request'], memory_target=target,
        selection_dispatch_boundary=lambda: pytest.fail('dispatch boundary entered'))
    assert report['action_executed'] is False
    assert validate_selection_receipt(report, command['request'], command=command, action_executed=False,
        session_dir=tmp_path, expected_context=bindings)
    assert not target.input_claimed


def test_original_owner_unselected_uses_existing_route_once(timed_scene, tmp_path, monkeypatch):
    from app.execution import local_direct_step as direct
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    co, events, command, bindings, current, target = owner_selection_scene(timed_scene, tmp_path, monkeypatch, False)
    dispatched = []
    def route(*args):
        assert dispatched == ['boundary']
        target.plan(image_path=current['frame']['image_path'], goal=command['request']['goal'],
            identity=current['row_selection']['window_identity'])
        target.before_dispatch(current['candidate']['click_point'], identity=current['row_selection']['window_identity'])
        current['row_selection']['selected'] = True
        dispatched.append('route')
        return {'success': True, 'data': {'result': {'execution_path': {'action_executed': True}}}}
    monkeypatch.setattr(direct, '_post_action', route)
    report = co.execute_local_step(target_window_handle=9, target_process_id=8,
        operation=command['operation'], request=command['request'], memory_target=target,
        selection_dispatch_boundary=lambda: dispatched.append('boundary'))
    assert dispatched == ['boundary', 'route']
    assert report['action_executed'] is True
    assert validate_selection_receipt(report, command['request'], command=command, action_executed=True,
        session_dir=tmp_path, expected_context=bindings)


def test_preclick_changed_selected_refuses_repeated_click(tmp_path):
    from app.core.memory_grounding_target import MemoryGroundingTarget
    command, bindings, report = satisfied_receipt(tmp_path)
    current = selection_resolution(tmp_path, selected=False)
    target = MemoryGroundingTarget(REF, current, read_current=lambda *args: deepcopy(current),
        selection_request=command['request'], selection_bindings=bindings)
    target.selection_preflight()
    guard = target.selection_control()
    current['row_selection']['selected'] = True
    with pytest.raises(ValueError, match='selection'):
        guard(current['candidate']['click_point'])
    target._planned = True
    with pytest.raises(ValueError, match='selection'):
        target.before_dispatch(current['candidate']['click_point'], identity=current['row_selection']['window_identity'])
    assert not target.input_claimed


from test_agent_command_jobs import env, _wait


@pytest.mark.parametrize('kind', ['input_sequence', 'form_fill'])
def test_agent_jobs_reject_selection_on_other_command_kinds(env, kind):
    from app.vision.agent_command_jobs import AgentCommandError
    jobs, co, store = env
    with pytest.raises((ValueError, AgentCommandError), match='selection'):
        jobs.start('unsupported-' + kind, {'kind': kind, 'request': {
            'selection_intent': 'ensure_selected'}}, {'handle': 100, 'process_id': 200},
            {'image_transport': 'supported', 'current_vision': 'supported'})


def test_agent_jobs_satisfied_selection_has_no_dispatch_attempt(env, tmp_path):
    jobs, co, store = env
    command, bindings, report = satisfied_receipt(tmp_path)
    co.prepare_memory_grounding = lambda **kwargs: (object(), {'status': 'matched'})
    co.execute_local_step = lambda **kwargs: deepcopy(report)
    jobs.start('satisfied', command, {'handle': 9, 'process_id': 8}, {}, workflow_bindings=bindings)
    done = _wait(jobs, 'satisfied', 'completed')
    assert done['action_executed'] is False
    assert done['dispatch_attempts'] == []
    assert done['last_execution']['attempt_index'] is None



def test_archived_capture_loader_preserves_exact_proof_and_checks_bytes(tmp_path):
    from pathlib import Path
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    command, bindings, report = satisfied_receipt(tmp_path)
    raw = Path(report['capture']['image_path']).read_bytes()
    assert validate_selection_receipt(report, command['request'], command=command,
        action_executed=False, session_dir=tmp_path, expected_context=bindings,
        capture_loader=lambda path: raw)
    for invalid in (b'not png', raw[:25], raw + b'changed'):
        assert not validate_selection_receipt(report, command['request'], command=command,
            action_executed=False, session_dir=tmp_path, expected_context=bindings,
            capture_loader=lambda path: invalid)


def test_compact_selection_reports_satisfaction_without_claiming_proof_validation(tmp_path):
    from app.instant_receipt import compact_receipt
    command, bindings, report = satisfied_receipt(tmp_path)
    compact = compact_receipt({'request_id': 'exec', 'result': report})
    assert compact['action']['action_executed'] is False
    assert compact['action']['selection']['status'] == 'already_satisfied'
    assert compact['action']['selection']['state_satisfied'] is True
    assert compact['action']['selection']['proof_verified'] is False


@pytest.mark.parametrize('mutation', ['contract', 'identity', 'capture', 'observation'])
def test_zero_input_proof_stays_bound_to_original_local_report(tmp_path, mutation):
    from app.learning_memory.selection_satisfaction import validate_selection_receipt
    command, bindings, report = satisfied_receipt(tmp_path)
    if mutation == 'contract': report['contract_version'] = 'other'
    elif mutation == 'identity': report['target_identity']['process_id'] += 1
    elif mutation == 'capture': report['capture'] = {}
    else: report['observation'] = {}
    assert not validate_selection_receipt(report, command['request'], command=command,
        action_executed=False, session_dir=tmp_path, expected_context=bindings)
