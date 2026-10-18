"""网页字段同时绑定当前 origin 与浏览器进程，不派发系统输入。"""
from dataclasses import replace

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_action_preview import _decision_and_risk
from app.agent.fresh_learning_observation import FreshLearningObservationError
from app.agent.text_field_evidence import prepare_text_field_expectation, verify_text_field_result
from tests.test_fresh_text_preview import _TextUIA, _text_recognize, _intent_payload, _parameters
from tests.test_formal_fresh_learning_observation import _owner, _WindowManager, _NativeReader, _OriginReader, _bound
from tests.text_field_fixture_support import SyntheticTextFieldReader


def web_fixture(tmp_path, *, uia=None):
    owner = _owner(tmp_path, manager=_WindowManager(*[_bound() for _ in range(100)]),
        native=_NativeReader(*[100.5]*100), origin=_OriginReader(*['https://fresh.example']*100),
        uia=uia or _TextUIA(), runner=_text_recognize)
    reader = SyntheticTextFieldReader()
    owner._text_field_reader = reader
    bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal='Search field')
    intent = FreshLearningIntent.from_dict(_intent_payload(_parameters()))
    decision, _ = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(), intent, original=bundle.recognition_result())
    return owner, reader, bundle, decision


def test_web_capture_freezes_native_process_and_origin_before_field_read(tmp_path):
    owner, reader, bundle, decision = web_fixture(tmp_path)
    assert bundle.packet.evidence()['application'] == {'kind': 'web', 'canonical_origin': 'https://fresh.example',
        'executable_path': r'c:\fresh\app.exe', 'process_create_time': 100.5}
    before = owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert before.identity.process_create_time == 100.5
    expected = prepare_text_field_expectation(before, _parameters())
    reader.value = expected.expected_value
    after_packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    after = owner.read_text_field_after(packet=after_packet, expectation=expected)
    assert verify_text_field_result(expected, after)['status'] == 'verified'
    assert len(reader.calls) == 2


@pytest.mark.parametrize('drift', ['origin', 'process', 'executable', 'window'])
def test_web_drift_before_read_never_calls_field_provider(tmp_path, drift):
    owner, reader, bundle, decision = web_fixture(tmp_path)
    if drift == 'origin':
        owner._origin_reader = _OriginReader('https://elsewhere.example')
    elif drift == 'process':
        owner._native_identity_reader = _NativeReader(101.0)
    elif drift == 'executable':
        owner._native_identity_reader = _NativeReader(100.5, path=r'c:\different.exe')
    else:
        owner._window_manager = _WindowManager(_bound(pid=9002))
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert reader.calls == []


@pytest.mark.parametrize('drift', ['origin', 'process'])
def test_web_drift_during_read_rejects_result(tmp_path, drift):
    owner, reader, bundle, decision = web_fixture(tmp_path)
    original = reader.read_field
    def changing(**kwargs):
        result = original(**kwargs)
        if drift == 'origin':
            owner._origin_reader = _OriginReader('https://elsewhere.example')
        else:
            owner._native_identity_reader = _NativeReader(101.0)
        return result
    reader.read_field = changing
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert len(reader.calls) == 1


def test_pid_reuse_during_web_capture_is_rejected(tmp_path):
    owner = _owner(tmp_path, native=_NativeReader(100.5, 101.0))
    with pytest.raises(FreshLearningObservationError, match='identity changed'):
        owner.observe(target_window_handle=4242, target_process_id=9001)


def test_current_field_geometry_not_model_point_box_is_read(tmp_path):
    class ShortField(_TextUIA):
        def snapshot_window(self, bound):
            result = super().snapshot_window(bound)
            result['controls'][0]['bbox'] = {'x': 20, 'y': 20, 'w': 90, 'h': 22}
            return result
    owner, reader, bundle, decision = web_fixture(tmp_path, uia=ShortField())
    before = owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert before.identity.control_bbox == (20, 20, 90, 22)
    assert reader.calls[0]['target_bbox'] == (20, 20, 90, 22)
    assert reader.calls[0]['click_point'] == (60, 30)
    original = reader.read_field
    def enlarged(**kwargs):
        actual = original(**kwargs)
        return replace(actual, identity=replace(actual.identity, control_bbox=(10, 10, 120, 40)))
    reader.read_field = enlarged
    with pytest.raises(FreshLearningObservationError, match='binding'):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)


def test_legacy_web_memory_is_readable_but_not_new_field_evidence(tmp_path):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    import json
    owner, reader, bundle, decision = web_fixture(tmp_path)
    evidence = bundle.packet.evidence()
    legacy = {'kind': 'web', 'canonical_origin': 'https://fresh.example'}
    assert _application_identity_from_evidence({'application': legacy}) == legacy
    assert _application_identity_from_evidence(evidence) == legacy
    evidence['application'] = legacy
    bundle = replace(bundle, packet=replace(bundle.packet, evidence_json=json.dumps(evidence).encode('utf-8')))
    with pytest.raises(FreshLearningObservationError, match='native process binding'):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert reader.calls == []


@pytest.mark.parametrize('change', [
    {'process_create_time': True}, {'process_create_time': float('nan')}, {'process_create_time': 0},
    {'process_create_time': float('inf')}, {'executable_path': 'relative.exe'}, {'unexpected': 'field'},
    {'process_create_time': None},
])
def test_web_source_rejects_malformed_native_metadata(change):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    application = {'kind': 'web', 'canonical_origin': 'https://fresh.example',
                   'executable_path': r'c:\fresh\app.exe', 'process_create_time': 100.5, **change}
    with pytest.raises(ValueError):
        _application_identity_from_evidence({'application': application})


@pytest.mark.parametrize('missing', ['executable_path', 'process_create_time'])
def test_web_source_rejects_partial_native_identity(missing):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    application = {'kind': 'web', 'canonical_origin': 'https://fresh.example',
                   'executable_path': r'c:\fresh\app.exe', 'process_create_time': 100.5}
    del application[missing]
    with pytest.raises(ValueError):
        _application_identity_from_evidence({'application': application})


@pytest.mark.parametrize('path', [r'c:\program files (x86)\microsoft\edge\application\msedge.exe',
                                r'c:\program files\google\chrome\application\chrome.exe'])
def test_real_browser_process_is_web_evidence_not_a_native_application(path):
    from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
    application = {'kind': 'web', 'canonical_origin': 'https://fresh.example',
                   'executable_path': path, 'process_create_time': 100.5}
    assert _application_identity_from_evidence({'application': application}) == {
        'kind': 'web', 'canonical_origin': 'https://fresh.example'}
    with pytest.raises(ValueError):
        _application_identity_from_evidence({'application': {
            'kind': 'native', 'executable_path': path, 'process_create_time': 100.5}})
