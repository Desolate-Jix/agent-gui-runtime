import json
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_observation import (
    FreshLearningActionObservation,
    FreshLearningObservationError,
    FreshLearningObservationOwner,
    FreshLearningObservationPacket,
)
from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot


def _bundle(kind="native"):
    png = b"\x89PNG\r\n\x1a\nsynthetic"
    recognition = json.dumps({"synthetic": True}).encode()
    evidence = {
        "capture": {"capture_id": "cap-1", "screenshot_sha256": sha256(png).hexdigest(),
                    "viewport_size": {"width": 160, "height": 100}, "captured_at_ns": 10},
        "target": {"window_handle": 42, "process_id": 77,
                   "rect": {"x": 0, "y": 0, "width": 160, "height": 100}},
        "application": ({"kind": "native", "process_create_time": 12.5}
                         if kind == "native" else {"kind": "web", "canonical_origin": "https://x.example"}),
        "recognition": {"result_sha256": sha256(recognition).hexdigest()},
    }
    return FreshLearningActionObservation(
        FreshLearningObservationPacket(png, json.dumps(evidence).encode()),
        recognition, b"{}",
    )


class _Reader:
    def read_field(self, **kwargs):
        self.kwargs = kwargs
        identity = TextFieldIdentity("field-1", 42, 77, 12.5, (1, 2), (0, 0, 160, 100), (10, 20, 80, 20))
        return TextFieldSnapshot(identity, "cap-1", "read-1", 20, "uia_value", "私有值", (0, 0))


def _recognition(monkeypatch):
    candidate = SimpleNamespace(candidate_id="field-1", refined_bbox=SimpleNamespace(x=10, y=20, w=80, h=20),
                                element=SimpleNamespace(bbox=SimpleNamespace(x=10, y=20, w=80, h=20)))
    local = SimpleNamespace(candidate_id="field-1", refined_click_point=(20, 25))
    candidates = SimpleNamespace(goal="填写字段", candidates=[candidate])
    grounding = SimpleNamespace(goal="填写字段", results=[local])
    monkeypatch.setattr("app.agent.live_runtime_composition._parse_recognition", lambda value: (candidates, grounding))
    decision = {"allowed": True, "selected_candidate_id": "field-1", "selected_click_point": (20, 25)}
    monkeypatch.setattr("app.operation.recognition.decision.decide_pre_click", lambda **kwargs: SimpleNamespace(to_dict=lambda: decision))
    return decision


def test_foreign_native_bundle_cannot_override_web_owner(monkeypatch, tmp_path):
    decision = _recognition(monkeypatch)
    owner = FreshLearningObservationOwner(
        project_root=tmp_path, application_identity={"kind": "web", "canonical_origin": "https://x.example"},
        text_field_reader=_Reader(), window_manager=SimpleNamespace(), native_identity_reader=SimpleNamespace(),
        origin_reader=SimpleNamespace(), uia_provider=SimpleNamespace(),
    )
    bundle = _bundle()
    # 测试夹具把应用绑定替换为本地原生事实，避免启动任何真实窗口。
    payload = bundle.packet.evidence()
    payload["application"] = {"kind": "native", "process_create_time": 12.5}
    bundle = FreshLearningActionObservation(FreshLearningObservationPacket(bundle.packet.png_bytes, json.dumps(payload).encode()), bundle.recognition_json, bundle.uia_snapshot_json)
    with pytest.raises(FreshLearningObservationError, match="native process binding"):
        owner.read_text_field(bundle=bundle, target_field_id="field-1", decision=decision)


def test_fresh_web_without_process_creation_time_fails_closed(monkeypatch, tmp_path):
    owner = FreshLearningObservationOwner(
        project_root=tmp_path, application_identity={"kind": "web", "canonical_origin": "https://x.example"},
        text_field_reader=_Reader(), window_manager=SimpleNamespace(), native_identity_reader=SimpleNamespace(),
        origin_reader=SimpleNamespace(), uia_provider=SimpleNamespace(),
    )
    with pytest.raises(FreshLearningObservationError, match="native process binding"):
        owner.read_text_field(bundle=_bundle("web"), target_field_id="field-1", decision={})


def test_real_recognition_protocol_reads_native_field_without_patching_parser(tmp_path):
    from tests.test_fresh_text_preview import _native_owner, _intent_payload, _parameters
    from tests.text_field_fixture_support import SyntheticTextFieldReader
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from app.agent.fresh_learning_action_preview import _decision_and_risk

    owner = _native_owner(tmp_path)
    reader = SyntheticTextFieldReader()
    owner._text_field_reader = reader
    bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal='Search field')
    intent = FreshLearningIntent.from_dict(_intent_payload(_parameters()))
    decision, _ = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(), intent,
        original=bundle.recognition_result())
    snapshot = owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert snapshot.identity.target_field_id == 'fresh.search'
    assert reader.calls[0]['click_point'] == (60, 30)
    assert reader.calls[0]['target_bbox'] == (10, 10, 120, 40)
    assert reader.calls[0]['expected_runtime_id'] == (42, 12)
    assert reader.calls[0]['expected_control_type'] == 'edit'
    assert snapshot.value == reader.value
    assert reader.value not in json.dumps(snapshot.to_reference(), ensure_ascii=False)


def _real_read_fixture(tmp_path):
    from tests.test_fresh_text_preview import _native_owner, _intent_payload, _parameters
    from tests.text_field_fixture_support import SyntheticTextFieldReader
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from app.agent.fresh_learning_action_preview import _decision_and_risk

    owner = _native_owner(tmp_path)
    reader = SyntheticTextFieldReader()
    owner._text_field_reader = reader
    bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal='Search field')
    intent = FreshLearningIntent.from_dict(_intent_payload(_parameters()))
    decision, _ = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(), intent,
        original=bundle.recognition_result())
    return owner, reader, bundle, decision


@pytest.mark.parametrize('mutation', ['png', 'recognition', 'uia', 'point', 'process', 'window', 'application'])
def test_changed_capture_or_owner_is_rejected_before_native_field_read(tmp_path, mutation):
    from dataclasses import replace
    from tests.test_formal_fresh_learning_observation import _WindowManager, _bound, _NativeReader

    owner, reader, bundle, decision = _real_read_fixture(tmp_path)
    if mutation == 'png':
        bundle = replace(bundle, packet=replace(bundle.packet, png_bytes=b'invalid'))
    elif mutation == 'recognition':
        bundle = replace(bundle, recognition_json=b'{}')
    elif mutation == 'uia':
        bundle = replace(bundle, uia_snapshot_json=b'{}')
    elif mutation == 'point':
        decision['selected_click_point']['x'] = 999
    elif mutation == 'process':
        owner._native_identity_reader = _NativeReader(101.0)
    elif mutation == 'window':
        owner._window_manager = _WindowManager(_bound(pid=9002))
    elif mutation == 'application':
        owner.application = {'kind': 'native', 'executable_path': r'c:\other.exe'}
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert reader.calls == []


@pytest.mark.parametrize('mutation', ['field_id', 'capture', 'process', 'bounds', 'time', 'owner_after'])
def test_wrong_native_read_result_is_not_promoted_to_field_snapshot(tmp_path, mutation):
    from dataclasses import replace
    from tests.test_formal_fresh_learning_observation import _NativeReader

    owner, reader, bundle, decision = _real_read_fixture(tmp_path)
    original = reader.read_field

    def wrong(**kwargs):
        actual = original(**kwargs)
        if mutation == 'field_id':
            return replace(actual, identity=replace(actual.identity, target_field_id='wrong.field'))
        if mutation == 'capture':
            return replace(actual, capture_id='wrong.capture')
        if mutation == 'process':
            return replace(actual, identity=replace(actual.identity, process_id=9002))
        if mutation == 'bounds':
            return replace(actual, identity=replace(actual.identity, control_bbox=(0, 0, 5, 5)))
        if mutation == 'time':
            return replace(actual, observed_at_ns=1)
        owner._native_identity_reader = _NativeReader(101.0)
        return actual

    reader.read_field = wrong
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    assert len(reader.calls) == 1


def test_reader_error_is_sanitized_and_focus_requirement_is_forwarded(tmp_path):
    owner, reader, bundle, decision = _real_read_fixture(tmp_path)
    seen = []

    def fail(**kwargs):
        seen.append(kwargs)
        raise RuntimeError('private field contents')

    reader.read_field = fail
    with pytest.raises(FreshLearningObservationError) as error:
        owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision,
            require_keyboard_focus=True)
    assert seen[0]['require_keyboard_focus'] is True
    assert 'private field contents' not in str(error.value)


def test_post_read_uses_new_passive_capture_and_verifies_same_native_field(tmp_path):
    from tests.test_fresh_text_preview import _parameters
    from app.agent.text_field_evidence import prepare_text_field_expectation, verify_text_field_result

    owner, reader, bundle, decision = _real_read_fixture(tmp_path)
    before = owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    expected = prepare_text_field_expectation(before, _parameters())
    reader.value = expected.expected_value
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    after = owner.read_text_field_after(packet=packet, expectation=expected)
    assert verify_text_field_result(expected, after)['status'] == 'verified'
    assert after.capture_id == packet.evidence()['capture']['capture_id']
    assert reader.calls[-1]['require_keyboard_focus'] is False
    assert reader.calls[-1]['expected_runtime_id'] == before.identity.runtime_id
    assert reader.calls[-1]['expected_control_type'] == 'edit'
    assert before.capture_id != after.capture_id


def test_post_read_rejects_pre_action_capture_before_provider_call(tmp_path):
    from tests.test_fresh_text_preview import _parameters
    from app.agent.text_field_evidence import prepare_text_field_expectation

    owner, reader, bundle, decision = _real_read_fixture(tmp_path)
    before = owner.read_text_field(bundle=bundle, target_field_id='fresh.search', decision=decision)
    expected = prepare_text_field_expectation(before, _parameters())
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field_after(packet=bundle.packet, expectation=expected)
    assert len(reader.calls) == 1
