"""填写后只读复核按元素实例寻回，不把布局变化当成另一个字段。"""

from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_action_preview import _decision_and_risk
from app.agent.fresh_learning_observation import FreshLearningObservationError
from app.agent.text_field_evidence import (
    prepare_text_field_expectation, validate_text_field_precondition,
    validate_text_field_verification_reference, verify_text_field_result,
)
from app.agent.text_parameters import text_parameter_reference
from tests.test_fresh_text_preview import _TextUIA, _native_owner, _intent_payload, _parameters
from tests.test_fresh_web_text_field import web_fixture
from tests.text_field_fixture_support import SyntheticTextFieldReader


class LayoutUIA(_TextUIA):
    def __init__(self, role="Edit"):
        super().__init__()
        self.role = role
        self.bbox = {"x": 10, "y": 10, "w": 120, "h": 40}
        self.runtime = [42, 12]
        self.visible = True
        self.extra = []

    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        field = result["controls"][0]
        field.update(bbox=dict(self.bbox), runtime_id=list(self.runtime),
                     control_type=self.role, visible=self.visible)
        result["controls"].extend(deepcopy(self.extra))
        result["control_count"] = len(result["controls"])
        return result


def fixture(tmp_path, kind="native", role="Edit"):
    uia = LayoutUIA(role)
    if kind == "web":
        owner, reader, bundle, decision = web_fixture(tmp_path, uia=uia)
    else:
        owner = _native_owner(tmp_path)
        owner._uia_provider = uia
        reader = SyntheticTextFieldReader()
        owner._text_field_reader = reader
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal="Search field")
        intent = FreshLearningIntent.from_dict(_intent_payload(_parameters()))
        decision, _ = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(), intent,
                                       original=bundle.recognition_result())
    before = owner.read_text_field(bundle=bundle, target_field_id="fresh.search", decision=decision)
    expected = prepare_text_field_expectation(before, _parameters())
    reader.value = expected.expected_value
    return owner, reader, uia, expected


@pytest.mark.parametrize("kind,role", [("native", "Edit"), ("web", "ComboBox")])
@pytest.mark.parametrize("bbox", [(10, 10, 145, 40), (110, 70, 40, 20)])
def test_post_read_retains_current_geometry_for_same_runtime(tmp_path, kind, role, bbox):
    owner, reader, uia, expected = fixture(tmp_path, kind, role)
    uia.bbox = dict(zip(("x", "y", "w", "h"), bbox))
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    after = owner.read_text_field_after(packet=packet, expectation=expected)
    assert after.identity.control_bbox == bbox
    assert after.identity.runtime_id == expected.before.identity.runtime_id
    assert reader.calls[-1]["target_bbox"] == bbox
    assert reader.calls[-1]["click_point"] == (bbox[0] + bbox[2] // 2, bbox[1] + bbox[3] // 2)
    assert reader.calls[-1]["require_keyboard_focus"] is False
    verified = verify_text_field_result(expected, after)
    assert verified["status"] == "verified"
    assert verified["contract_version"] == "text_field_verification_v2"
    assert validate_text_field_verification_reference(verified, text_parameter_reference(_parameters().reviewed)) == verified
    with pytest.raises(ValueError, match="precondition"):
        validate_text_field_precondition(expected, after)


@pytest.mark.parametrize("mutation", ["replacement", "duplicate", "hidden", "outside", "overlap"])
def test_post_read_cannot_follow_a_replacement_or_ambiguous_field(tmp_path, mutation):
    owner, reader, uia, expected = fixture(tmp_path)
    if mutation == "replacement":
        uia.runtime = [99, 1]
    elif mutation == "hidden":
        uia.visible = False
    elif mutation == "outside":
        uia.bbox = {"x": 145, "y": 70, "w": 40, "h": 20}
    else:
        other = deepcopy(uia.snapshot_window(None)["controls"][0])
        other["control_id"] = "other"
        if mutation == "overlap":
            other["runtime_id"] = [99, 1]
        uia.extra = [other]
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    calls = len(reader.calls)
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field_after(packet=packet, expectation=expected)
    assert len(reader.calls) == calls


@pytest.mark.parametrize("mutation", ["bbox", "runtime", "role", "returned_bbox", "returned_capture"])
def test_post_read_rejects_changes_during_read(tmp_path, mutation):
    owner, reader, uia, expected = fixture(tmp_path)
    original = reader.read_field

    def changing(**request):
        actual = original(**request)
        if mutation == "bbox":
            uia.bbox["w"] += 5
        elif mutation == "runtime":
            uia.runtime = [99, 1]
        elif mutation == "role":
            uia.role = "ComboBox"
        elif mutation == "returned_bbox":
            return replace(actual, identity=replace(actual.identity, control_bbox=(1, 1, 5, 5)))
        else:
            return replace(actual, capture_id="stale")
        return actual

    reader.read_field = changing
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field_after(packet=packet, expectation=expected)
    assert len(reader.calls) == 2


@pytest.mark.parametrize("phase", ["before_read", "during_read"])
@pytest.mark.parametrize("drift", ["origin", "process"])
def test_post_read_web_identity_drift_remains_rejected(tmp_path, phase, drift):
    from tests.test_formal_fresh_learning_observation import _OriginReader, _NativeReader

    owner, reader, uia, expected = fixture(tmp_path, "web", "ComboBox")
    packet = owner.observe(target_window_handle=4242, target_process_id=9001)

    def change():
        if drift == "origin":
            owner._origin_reader = _OriginReader("https://elsewhere.example")
        else:
            owner._native_identity_reader = _NativeReader(101.0)

    if phase == "before_read":
        change()
    else:
        original = reader.read_field

        def changing(**request):
            actual = original(**request)
            change()
            return actual

        reader.read_field = changing
    with pytest.raises(FreshLearningObservationError):
        owner.read_text_field_after(packet=packet, expectation=expected)
    assert len(reader.calls) == (1 if phase == "before_read" else 2)
