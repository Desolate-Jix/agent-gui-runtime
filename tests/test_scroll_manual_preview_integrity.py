"""关闭自动策略不关闭滚动证据完整性；通过真实预览构建入口验证。"""
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
from app.agent.fresh_learning_observation import FreshLearningActionObservation, FreshLearningObservationPacket, _canonical_bytes
from app.agent.live_runtime_composition import _run_existing_read_only_recognition
from app.operation.recognition.scroll_grounding import EVIDENCE_KEY
from tests.test_current_scroll_grounding import _controls
from tests.test_fresh_scroll_dispatch import _scroll_runtime


def _build(tmp_path, *, mutation=None, strict=False, intent_override=None):
    with _scroll_runtime(tmp_path) as (host, owner, runtime, claims, native_input, session, scope, intent):
        previous_provider = owner._uia_provider
        def snapshot(bound):
            result = previous_provider.snapshot_window(bound)
            controls = _controls()
            controls[2]["control_id"] = "fresh.scroll"
            controls[1]["scroll_axes"]["current_vertical"] = False
            result.update(controls=controls, control_count=len(controls), scan_complete=True, truncated=False)
            return result
        owner._uia_provider = SimpleNamespace(snapshot_window=snapshot)
        owner._recognition_runner = _run_existing_read_only_recognition
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001,
            goal=intent.goal, semantic_action="scroll_region", scroll_parameters=intent.scroll_parameters)
        if mutation is not None:
            evidence, original = bundle.packet.evidence(), bundle.recognition_result()
            mutation(original)
            mutation(evidence["recognition"]["result"])
            raw = _canonical_bytes(original)
            evidence["recognition"]["result_sha256"] = sha256(raw).hexdigest()
            bundle = FreshLearningActionObservation(
                packet=FreshLearningObservationPacket(bundle.packet.png_bytes, _canonical_bytes(evidence)),
                recognition_json=raw, uia_snapshot_json=bundle.uia_snapshot_json)
        capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
        source = session.source.reference()
        result = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
            observation=session.current_observation.to_dict(),
            intent=intent_override(intent.to_dict()) if intent_override else intent, source_reference=source,
            automatic_safety_interception=strict)
        assert native_input.calls == []
        return result


@pytest.mark.parametrize("strict", [True, False])
def test_valid_typed_scroll_builds_real_preview_without_input(tmp_path, strict):
    preview = _build(tmp_path, strict=strict).to_dict()
    assert preview["risk"]["risk_class"] == "low_risk_scroll"
    assert preview["action_executed"] is False


@pytest.mark.parametrize("case", ["screenshot_hash", "uia_hash", "target", "point", "proof_missing",
    "coordinate_missing", "reason_missing", "proof_and_coordinate_missing", "summary_missing_with_proof_missing",
    "all_evidence_markers_missing", "axis", "direction", "wheel_clicks"])
def test_manual_preview_rejects_tampered_typed_scroll_even_with_rehashed_original(tmp_path, case):
    def mutate(result):
        candidate = result["candidate_result"]["candidates"][0]
        local = result["narrow_search_result"]["results"][0]
        proof = candidate["element"]["evidence"][EVIDENCE_KEY]
        if case == "screenshot_hash": proof["screenshot_sha256"] = "a" * 64
        elif case == "uia_hash": proof["uia_snapshot_sha256"] = "a" * 64
        elif case == "target": proof["target"]["control_id"] = "other"
        elif case == "point": proof["point"] = {"x": 11, "y": 11}
        elif case in {"proof_missing", "proof_and_coordinate_missing", "summary_missing_with_proof_missing", "all_evidence_markers_missing"}:
            candidate["element"]["evidence"].pop(EVIDENCE_KEY)
            if case == "summary_missing_with_proof_missing": result["candidate_result"]["summary"] = {}
            if case == "proof_and_coordinate_missing": local["coordinate_source"] = "candidate_element_click_point"
            if case == "all_evidence_markers_missing":
                result["candidate_result"]["summary"] = {}
                local.update(coordinate_source="candidate_element_click_point", reasons=[])
                candidate["element"]["click_strategy"] = "candidate_element_click_point"
        elif case == "coordinate_missing": local["coordinate_source"] = "candidate_element_click_point"
        elif case == "reason_missing": local["reasons"] = []
        else: proof["scroll_parameters"][case] = {"axis": "horizontal", "direction": "up", "wheel_clicks": 1}[case]
    with pytest.raises(ValueError, match="scroll.*binding"):
        _build(tmp_path, mutation=mutate)


def test_manual_preview_rejects_scroll_proof_relabelled_as_navigation(tmp_path):
    def intent_override(value):
        value["semantic_action"] = "open_detail"
        value.pop("scroll_parameters")
        return value
    with pytest.raises(ValueError, match="scroll.*binding"):
        _build(tmp_path, intent_override=intent_override)
