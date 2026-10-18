"""全新填写预览绑定当前字段；纯源码检查不派发系统输入。"""

from copy import deepcopy
from dataclasses import replace
import json
import time

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, build_fresh_learning_action_preview,
    validate_fresh_execution_preview,
)
from app.agent.text_parameters import (
    ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters, text_parameter_reference,
)
from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation
from tests.test_fresh_learning_action_preview import _recognize
from tests.test_fresh_action_risk import _control
from tests.test_formal_fresh_learning_observation import _owner, _WindowManager, _NativeReader, _UIAProvider, _bound
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime


def _parameters(kind='literal', *, clear=True):
    declaration = ReviewedTextParameters('fresh.search', ReviewedTextSource(kind, '\u65b0\u5185\u5bb9' if kind == 'literal' else 'query'), clear, False)
    return resolve_text_parameters(declaration, {'query': '\u65b0\u5185\u5bb9'} if kind == 'variable' else {})


def _intent_payload(parameters=None, *, semantic='fill_field'):
    result = {'contract_version': 'fresh_learning_action_intent_v1', 'intent_id': 'intent.text',
        'session_id': 'session.text', 'observation_id': 'observation.text', 'source_sha256': 'a' * 64,
        'action_id': 'action.text', 'semantic_action': semantic, 'goal': 'Search field'}
    if parameters is not None:
        result['text_parameters_ref'] = text_parameter_reference(parameters.reviewed)
    return result


@pytest.mark.parametrize('kind', ['literal', 'variable'])
def test_fill_intent_carries_only_immutable_text_declaration_reference(kind):
    parameters = _parameters(kind)
    payload = _intent_payload(parameters)
    intent = FreshLearningIntent.from_dict(payload)
    original = deepcopy(payload)
    payload['text_parameters_ref']['target_field_id'] = 'tampered'
    assert intent.to_dict() == original
    intent.to_dict()['text_parameters_ref']['clear_existing'] = False
    assert intent.to_dict() == original
    assert parameters.text not in json.dumps(intent.to_dict(), ensure_ascii=False)
    assert parameters.text not in repr(intent)


@pytest.mark.parametrize('mutation', [
    lambda p: p.pop('text_parameters_ref'),
    lambda p: p.update(text_parameters_ref=None),
    lambda p: p.update(semantic_action='open_detail'),
    lambda p: p.update(text='private'),
    lambda p: p['text_parameters_ref'].update(submit=True),
    lambda p: p['text_parameters_ref'].update(clipboard_policy='leave_changed'),
])
def test_fill_intent_rejects_incomplete_or_overreaching_declarations(mutation):
    payload = _intent_payload(_parameters())
    mutation(payload)
    with pytest.raises(ValueError):
        FreshLearningIntent.from_dict(payload)


def test_navigation_keeps_original_exact_shape():
    payload = _intent_payload(semantic='open_detail')
    assert FreshLearningIntent.from_dict(payload).to_dict() == payload


class _TextUIA(_UIAProvider):
    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        control = _control('fresh.search', 'Search field', {'x': 10, 'y': 10, 'w': 120, 'h': 40}, control_type='Edit')
        control.update(patterns=['Value', 'Text'], class_name='Edit', runtime_id=[42, 12])
        result['controls'] = [control]
        return result


def _text_recognize(**kwargs):
    result = _recognize(**kwargs)
    candidate = result['candidate_result']['candidates'][0]
    candidate['role'] = candidate['element']['role'] = 'textbox'
    return result


def _native_owner(root):
    # 稳定窗口夹具覆盖字段前后 UIA 重采及有界重试；漂移用单独故障夹具。
    return _owner(root, application={'kind': 'native', 'executable_path': r'c:\fresh\app.exe'},
        manager=_WindowManager(*[_bound() for _ in range(100)]), native=_NativeReader(*[100.5] * 100),
        uia=_TextUIA(), runner=_text_recognize)


def _text_previews(root, *, kind='literal', value='old', mutate=None, count=1):
    owner = _native_owner(root / 'capture')
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    host, connection, segment, _packet, _args, staged = _stage(root, packet)
    owner.project_root = host.fresh_learning.archive.project_root
    runtime, backend, claims, source = _runtime(host, connection, segment, staged, observation_owner=owner)
    session = runtime.start_session_preparation(preparation_id='fresh.text.preview')
    params = _parameters(kind)
    previews = []
    try:
        intent = FreshLearningIntent.from_dict({**_intent_payload(params), 'session_id': session.session_id,
            'observation_id': session.current_observation.observation_id, 'source_sha256': source.reference()['source_sha256']})
        for index in range(count):
            bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
            evidence = bundle.packet.evidence()
            identity = TextFieldIdentity('fresh.search', 4242, 9001, 100.5, (42, 12), (10, 20, 160, 100), (10, 10, 120, 40))
            field = TextFieldSnapshot(identity, evidence['capture']['capture_id'], f'read-{index}', time.perf_counter_ns(), 'uia_value', value, (0, 0))
            if mutate is not None:
                field = mutate(field, index)
            expectation = prepare_text_field_expectation(field, params)
            reference = source.reference()
            scope = {key: reference[key] for key in ('connection_id', 'task_id', 'segment_id')}
            capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
            previews.append(build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
                observation=session.current_observation.to_dict(), intent=intent, source_reference=reference,
                text_field_expectation=expectation))
        assert backend.commands == [] and backend.attempt_count == 0
        return previews, params
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()


@pytest.mark.parametrize('kind', ['literal', 'variable'])
def test_fresh_fill_preview_binds_field_and_resolved_text_without_values(tmp_path, kind):
    previews, params = _text_previews(tmp_path, kind=kind)
    data = previews[0].to_dict()
    assert data['risk']['risk_class'] == 'low_risk_text_input'
    assert data['text_execution_ref'] == data['text_field_expectation_ref']['text_execution_ref']
    assert data['text_field_expectation_ref']['before']['capture_id'] == data['observation_evidence']['capture']['capture_id']
    assert params.text not in json.dumps(data, ensure_ascii=False)
    assert data['artifact_is_authorization'] is False and data['action_executed'] is False


@pytest.mark.parametrize('mutation', [
    lambda p: p.pop('text_execution_ref'),
    lambda p: p.update(text='private'),
    lambda p: p['text_field_expectation_ref']['before'].update(capture_id='wrong.capture'),
    lambda p: p['text_field_expectation_ref']['before']['identity'].update(process_id=9002),
    lambda p: p['text_field_expectation_ref']['before']['identity'].update(process_create_time=101.0),
    lambda p: p['text_field_expectation_ref']['before']['identity'].update(control_bbox=[0, 0, 5, 5]),
    lambda p: p['text_field_expectation_ref']['before'].update(observed_at_ns=1),
    lambda p: p['text_execution_ref'].update(text_sha256='b' * 64),
])
def test_rehashed_text_preview_rejects_wrong_binding(tmp_path, mutation):
    previews, _ = _text_previews(tmp_path)
    data = previews[0].to_dict()
    mutation(data)
    data['preview_sha256'] = payload_sha256({k: v for k, v in data.items() if k != 'preview_sha256'})
    with pytest.raises(ValueError):
        FreshLearningActionPreview.from_dict(data)


def test_text_execution_preview_allows_only_new_capture_and_field_read(tmp_path):
    previews, _ = _text_previews(tmp_path, count=2)
    assert validate_fresh_execution_preview(*previews) is None
    with pytest.raises(ValueError):
        validate_fresh_execution_preview(previews[0], previews[0])


def test_text_execution_preview_rejects_changed_old_value(tmp_path):
    previews, _ = _text_previews(tmp_path, count=2,
        mutate=lambda field, index: replace(field, value='changed') if index else field)
    with pytest.raises(ValueError, match='drifted'):
        validate_fresh_execution_preview(*previews)
