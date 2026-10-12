"""原按键调用的真实派发前沿与零派发认证；不产生桌面输入。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.desktop_review import local_direct_step as direct
from app.core.recognition_dispatch import local_receipt_zero_input_verified
from tests.test_local_step_timings import timed_scene
from tests.test_type_text_no_dispatch import route, _POST_ACTION


REQUEST = {'key': 'Enter', 'x': 70, 'y': 80}


@pytest.fixture
def key_route(route, monkeypatch):
    from app.api import action
    from app.core import input_controller as inputs
    controller = action.input_controller
    monkeypatch.setattr(inputs, 'input_controller', controller)
    state = SimpleNamespace(failure='before')

    def verify(*args, **kwargs):
        if state.failure == 'before':
            raise ValueError('visual_field_freshness_requires_review')
        if state.failure == 'foreground_before':
            raise inputs.KeyboardForegroundMismatchError(321, 999)

    def chord(keys):
        route.events.append(tuple(keys))
        if state.failure == 'chord':
            raise RuntimeError('first_key_interrupted')
        if state.failure == 'foreground_during':
            raise inputs.KeyboardForegroundMismatchError(321, 999)

    monkeypatch.setattr(controller, '_verify_text_target', verify)
    monkeypatch.setattr(controller, '_press_chord', chord)

    def run(**changes):
        return route.coordinator.execute_local_step(target_window_handle=321, target_process_id=12,
            operation='press_key', request={**REQUEST, **changes})

    return SimpleNamespace(run=run, state=state, route=route, controller=controller)


@pytest.mark.parametrize('failure', ['before', 'foreground_before'])
def test_key_refused_before_first_chord_is_authenticated_zero_input(key_route, failure):
    key_route.state.failure = failure
    receipt = key_route.run()
    assert receipt['phase'] == 'not_dispatched'
    assert receipt['action_executed'] is False
    assert receipt['response']['data']['pressed'] is False
    assert receipt['response']['data']['key_dispatch']['dispatch'] == 'not_started'
    assert local_receipt_zero_input_verified(receipt, 'press_key')
    assert local_receipt_zero_input_verified(json.loads(json.dumps(receipt)), 'press_key')
    assert not any(isinstance(event, tuple) for event in key_route.route.events)


@pytest.mark.parametrize('failure', ['chord', 'foreground_during'])
def test_attempted_key_never_becomes_zero_even_if_error_looks_like_precheck(key_route, failure):
    key_route.state.failure = failure
    receipt = key_route.run()
    assert receipt['phase'] == 'result_unknown'
    assert receipt['response']['data'] is None
    assert not local_receipt_zero_input_verified(receipt, 'press_key')


def test_real_partial_chord_records_started_before_raising(key_route):
    from app.core.key_dispatch import key_dispatch_scope, key_dispatch_from_error
    key_route.state.failure = 'chord'
    with key_dispatch_scope(), pytest.raises(RuntimeError) as caught:
        try:
            key_route.controller.press_key(**REQUEST)
        except RuntimeError as error:
            proof = key_dispatch_from_error(error)
            assert proof['dispatch'] == 'started'
            assert proof['input_started'] is True and proof['action_executed'] is None
            raise


def test_successful_enter_remains_single_confirmed_dispatch(key_route):
    from app.core.input_controller import VK_RETURN
    key_route.state.failure = 'none'
    receipt = key_route.run()
    assert receipt['phase'] == 'returned'
    assert receipt['response']['data']['pressed'] is True
    assert key_route.route.events.count((VK_RETURN,)) == 1


def test_caller_dictionary_and_other_invocation_cannot_supply_key_zero_attestation(key_route, monkeypatch):
    receipt = key_route.run()
    response = json.loads(json.dumps(receipt['response']))
    monkeypatch.setattr(direct, '_post_action', lambda *a: deepcopy(response))
    forged = key_route.run()
    assert forged['phase'] == 'result_unknown'
    assert not local_receipt_zero_input_verified(forged, 'press_key')
    response = _POST_ACTION('press_key', direct._validated_request('press_key', REQUEST), key_route.route.manager)
    monkeypatch.setattr(direct, '_post_action', lambda *a: response)
    replayed = key_route.run()
    assert replayed['phase'] == 'result_unknown'
    assert not local_receipt_zero_input_verified(replayed, 'press_key')


def test_caller_error_attribute_cannot_replace_real_key_dispatch_receipt(key_route, monkeypatch):
    def forged(*args, **kwargs):
        error = ValueError('visual_field_freshness_requires_review')
        error._key_dispatch_receipt = {'schema': 'key_dispatch.v1', 'dispatch': 'not_started',
            'input_started': False, 'action_executed': False, 'events': [], 'artifact_is_authorization': False}
        raise error
    monkeypatch.setattr(key_route.controller, 'press_key', forged)
    receipt = key_route.run()
    assert receipt['phase'] == 'result_unknown'
    assert not local_receipt_zero_input_verified(receipt, 'press_key')


def test_real_receipt_from_another_key_invocation_is_not_reusable(key_route, monkeypatch):
    from app.core.key_dispatch import key_dispatch_scope
    with key_dispatch_scope(), pytest.raises(ValueError) as caught:
        key_route.controller.press_key(**REQUEST)
    def replay(*args, **kwargs):
        raise caught.value
    monkeypatch.setattr(key_route.controller, 'press_key', replay)
    receipt = key_route.run()
    assert receipt['phase'] == 'result_unknown'
    assert not local_receipt_zero_input_verified(receipt, 'press_key')


@pytest.mark.parametrize('damage', ['request', 'identity', 'geometry', 'proof', 'response', 'returned'])
def test_key_zero_proof_rejects_changed_persisted_binding(key_route, damage):
    receipt = json.loads(json.dumps(key_route.run()))
    if damage == 'request': receipt['request']['key'] = 'Tab'
    elif damage == 'identity': receipt['target_identity']['process_create_time'] += 1
    elif damage == 'geometry': receipt['target_window_geometry']['rect'][2] += 1
    elif damage == 'proof': receipt.pop('key_no_dispatch', None)
    elif damage == 'returned': receipt.update(phase='returned', key_no_dispatch=None)
    else: receipt['response']['data']['pressed'] = True
    assert not local_receipt_zero_input_verified(receipt, 'press_key')


def test_sequence_keeps_focus_and_type_inputs_when_only_enter_was_not_dispatched(key_route, monkeypatch):
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
    from app.desktop_review import input_sequence as sequence
    from tests.test_input_sequence import Coordinator
    original = key_route.route.coordinator.execute_local_step

    class SequenceCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            if kwargs['operation'] == 'press_key':
                return original(**kwargs)
            return super().execute_local_step(**kwargs)

    identity = TextFieldIdentity('field', 321, 12, 123.5, (1,), (0, 0, 800, 600), (1, 1, 300, 120))
    values = iter(['old', 'fresh text'])
    monkeypatch.setattr(sequence, '_read_field', lambda *a, **kw:
        TextFieldSnapshot(identity, 'capture', 'read', 1, 'uia_value', next(values), None))
    monkeypatch.setattr(sequence, '_focus_field_binding', lambda *a: {
        'control_type': 'Edit', 'runtime_id': [1], 'bbox': {'x': 1, 'y': 1, 'w': 300, 'h': 120}})
    result = sequence.run_input_sequence(SequenceCoordinator(), {'handle': 321, 'process_id': 12},
        {'field_goal': 'Fresh search', 'text': 'fresh text', 'submit_search': True})
    assert result['status'] == 'interrupted' and result['action_executed'] is True
    assert result['completed_steps'] == ['focus', 'type', 'check_input']
    assert result['steps'][-1]['name'] == 'search'
    assert result['steps'][-1]['status'] == 'not_dispatched'
    assert result['steps'][-1]['action_executed'] is False
    assert result['automatic_retry_allowed'] is False
