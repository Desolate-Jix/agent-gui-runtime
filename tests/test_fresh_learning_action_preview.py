"""首次动作预览使用新生成证据，不导入已审核流程。"""

import hashlib
from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, canonical_json_bytes
from app.operation.recognition.schemas import CandidateRankResult, LocalGroundingResult, ScoreBreakdown
from tests.test_fresh_action_risk import _candidate, _local, _control
from tests.test_formal_fresh_learning_observation import _owner, _UIAProvider, _WindowManager, _OriginReader, _bound
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime


class _CurrentUIA(_UIAProvider):
    def snapshot_window(self, bound):
        result = super().snapshot_window(bound)
        result["controls"] = [_control("fresh.detail", "View details", {"x": 10, "y": 10, "w": 120, "h": 40})]
        return result


def _recognize(**kwargs):
    candidate = _candidate(kwargs["goal"])
    box = {"x": 10, "y": 10, "w": 120, "h": 40}
    from app.vision.schemas import BBox
    candidate.element.bbox = BBox(**box)
    candidate.element.click_point = {"x": 60, "y": 30}
    candidate.refined_bbox = box
    candidate.score_breakdown = ScoreBreakdown(text_similarity=1, policy_score=1, role_score=1,
                                             confidence_score=1, screen_reading_score=0.4)
    local = _local(candidate)
    local.crop_bbox = box
    local.matched_text_bbox = box
    local.refined_click_point = {"x": 60, "y": 30}
    return {"contract_version": "recognition_plan_v1", "goal": kwargs["goal"], "image_path": kwargs["image_path"],
            "candidate_result": CandidateRankResult(goal=kwargs["goal"], candidates=[candidate],
                recommended_candidate_id=candidate.candidate_id,
                summary={"control_target": deepcopy(kwargs["control_target"])} if kwargs.get("control_target") is not None else {}).to_dict(),
            "narrow_search_result": LocalGroundingResult(goal=kwargs["goal"], results=[local],
                recommended_candidate_id=candidate.candidate_id).to_dict()}


def _setup(tmp_path, *, runner=None):
    host, connection, segment, _packet, _args, staged = _stage(tmp_path)
    owner = _owner(host.fresh_learning.archive.project_root, manager=_WindowManager(*[_bound() for _ in range(18)]),
                   origin=_OriginReader(*["https://fresh.example"] * 18),
                   runner=runner or _recognize, uia=_CurrentUIA())
    runtime, backend, claims, source = _runtime(host, connection, segment, staged, observation_owner=owner)
    session = runtime.start_session_preparation(preparation_id="fresh.preview")
    intent = FreshLearningIntent.from_dict({"contract_version": "fresh_learning_action_intent_v1",
        "intent_id": "intent.preview", "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
        "source_sha256": source.reference()["source_sha256"], "action_id": "action.view",
        "semantic_action": "open_detail", "goal": "View details"})
    return host, owner, runtime, backend, claims, source, session, intent


def _preview(tmp_path, *, runner=None):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path, runner=runner)
    try:
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        reference = source.reference()
        scope = {key: reference[key] for key in ("connection_id", "task_id", "segment_id")}
        capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
        preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
            observation=session.current_observation.to_dict(), intent=intent, source_reference=reference)
        return preview, session.current_observation.to_dict(), intent, reference
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_preview_binds_new_png_original_recognition_and_recomputed_gate(tmp_path):
    preview, observation, intent, source = _preview(tmp_path)
    data = preview.to_dict()
    assert data["pre_click_decision"]["allowed"] is True
    assert data["pre_click_decision"]["selected_click_point"] == {"x": 60, "y": 30}
    assert data["risk"]["hard_blocked"] is False
    assert data["capture_source"]["capture_id"] != observation["capture"]["capture_id"]
    assert data["source_sha256"] == source["source_sha256"]
    assert data["action_executed"] is False
    assert "workflow" not in data and "reviewed_revision_hash" not in data
    data["risk"]["hard_blocked"] = True
    assert preview.to_dict()["risk"]["hard_blocked"] is False


def test_fresh_preview_preserves_typed_graph_recall_metrics_without_private_paths(tmp_path):
    metrics = {"path_graph_recall_used": False, "path_graph_recall_candidate_count": 0,
               "path_graph_recall_selected_count": 0}

    def recognize(**kwargs):
        value = _recognize(**kwargs)
        value["candidate_result"]["summary"].update(metrics)
        return value

    preview, *_ = _preview(tmp_path, runner=recognize)
    data = preview.to_dict()
    recognition = data["observation_evidence"]["recognition"]["result"]
    assert all(recognition["candidate_result"]["summary"][k] == v for k, v in metrics.items())
    assert "image_path" not in recognition
    assert all("crop_path" not in item for item in recognition["narrow_search_result"]["results"])
    assert data["pre_click_decision"]["allowed"] is True
    assert data["risk"]["hard_blocked"] is False
    assert data["artifact_is_authorization"] is False and data["action_executed"] is False


@pytest.mark.parametrize("mutation", [
    lambda p: p["pre_click_decision"]["selected_click_point"].update(x=150),
    lambda p: p["uia_snapshot"]["controls"][0].update(name="Pay now"),
    lambda p: p.update(action_executed=True),
    lambda p: p["risk"].update(risk_class="made_up"),
])
def test_rehash_cannot_promote_mutated_evidence_or_gate(tmp_path, mutation):
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
    preview, *_ = _preview(tmp_path)
    data = preview.to_dict()
    mutation(data)
    data["preview_sha256"] = hashlib.sha256(canonical_json_bytes({k: v for k, v in data.items() if k != "preview_sha256"})).hexdigest()
    with pytest.raises(ValueError):
        FreshLearningActionPreview.from_dict(data)


def _two_execution_previews(tmp_path, *, before_second=None):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview

    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    previews = []
    try:
        for index in range(2):
            if index == 1 and before_second is not None:
                before_second(owner)
            bundle = owner.observe_for_action(
                target_window_handle=4242,
                target_process_id=9001,
                goal=intent.goal,
            )
            reference = source.reference()
            scope = {
                key: reference[key]
                for key in ("connection_id", "task_id", "segment_id")
            }
            capture_source = host.fresh_learning.archive.record(bundle.packet, **scope)
            previews.append(build_fresh_learning_action_preview(
                bundle=bundle,
                capture_source=capture_source,
                observation=session.current_observation.to_dict(),
                intent=intent,
                source_reference=reference,
            ))
        return previews
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_execution_preview_accepts_only_new_equivalent_real_capture(tmp_path):
    from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview

    approved, current = _two_execution_previews(tmp_path)
    assert validate_fresh_execution_preview(approved, current) is None

    with pytest.raises(ValueError, match="newer capture"):
        validate_fresh_execution_preview(approved, approved)


def test_fresh_execution_preview_ignores_only_private_raw_recognition_path_digest(tmp_path):
    from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview

    def new_private_path(owner):
        original = owner._recognition_runner

        def changed(**kwargs):
            value = deepcopy(original(**kwargs))
            value["narrow_search_result"]["results"][0]["crop_path"] = (
                str(kwargs["image_path"]) + ".private-crop"
            )
            return value

        owner._recognition_runner = changed

    approved, current = _two_execution_previews(
        tmp_path, before_second=new_private_path,
    )
    before_sha = approved.to_dict()["observation_evidence"]["recognition"]["result_sha256"]
    after_sha = current.to_dict()["observation_evidence"]["recognition"]["result_sha256"]
    assert before_sha != after_sha
    assert validate_fresh_execution_preview(approved, current) is None


def test_fresh_execution_preview_rejects_valid_current_candidate_drift(tmp_path):
    from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview

    def drift(owner):
        original = owner._recognition_runner

        def changed(**kwargs):
            value = deepcopy(original(**kwargs))
            candidate = value["candidate_result"]["candidates"][0]
            candidate["label"] = "View details now"
            candidate["text"] = "View details now"
            candidate["element"]["label"] = "View details now"
            candidate["element"]["text"] = "View details now"
            value["narrow_search_result"]["results"][0]["matched_text"] = "View details now"
            return value

        owner._recognition_runner = changed

    approved, current = _two_execution_previews(tmp_path, before_second=drift)
    with pytest.raises(ValueError, match="drifted"):
        validate_fresh_execution_preview(approved, current)
