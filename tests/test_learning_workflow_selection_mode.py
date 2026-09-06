from __future__ import annotations


def test_hybrid_v1_2_initial_request_uses_registered_selection_task() -> None:
    from app.learn.workflow_service import build_learning_pipeline_initial_worker_request

    payload = {
        "run_id": "run/selection-replay", "workflow_revision": 4,
        "hybrid_capture_bundle_ref": {"id": "bundle/one", "content_sha256": "a" * 64},
        "request_ref": {"id": "request/one", "content_sha256": "b" * 64},
        "registration_ref": {"id": "registration/one", "content_sha256": "c" * 64},
        "manifest_ref": {"id": "manifest/one", "content_sha256": "d" * 64},
        "capture_image_path": "artifacts/screenshots/one.png",
        "hybrid_config": {"config_id": "learn_hybrid_v1_2"},
        "capture_bundle": {"fixture": "validated by worker"},
        "omni_inventory": {"fixture": "validated by worker"},
        "gui_actor_selection_input": {"fixture": "validated by worker"},
        "target_text": "Quick Apply",
        "refinement_policy": {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False},
    }

    request = build_learning_pipeline_initial_worker_request(
        learning_pipeline_mode="hybrid_v1_2", payload=payload,
    )

    assert request["task_kind"] == "panel_learning_hybrid_selection"
    assert request["payload"]["learning_pipeline_mode"] == "hybrid_v1_2"
    assert request["payload"]["target_text"] == "Quick Apply"
    assert "qwen_bindings" not in request["payload"]


def test_hybrid_v1_2_is_registered_but_default_remains_incumbent() -> None:
    from app.learn.workflow_contracts import normalize_learning_pipeline_mode
    from app.learn.workflow_worker import SUPPORTED_LEARNING_STAGE_TASK_KINDS

    assert normalize_learning_pipeline_mode() == "incumbent"
    assert normalize_learning_pipeline_mode("hybrid_v1_2") == "hybrid_v1_2"
    assert "panel_learning_hybrid_selection" in SUPPORTED_LEARNING_STAGE_TASK_KINDS


def test_selection_worker_executes_replay_only_and_never_accepts_client_actual_mode(tmp_path) -> None:
    from hashlib import sha256
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from app.learn.workflow_worker import execute_learning_stage_worker_task
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(tmp_path)
    raw_text = '{"topk_points":[[0.5,0.4]]}'
    payload = {
        "learning_pipeline_mode": "hybrid_v1_2",
        "execution_origin": "replay",
        "gui_actor_provider_state": "replay_ready",
        "capture_bundle": facts["bundle"],
        "omni_inventory": omni_inventory_from_ledger(facts["ledger"]),
        "gui_actor_selection_input": {"raw_output_utf8": raw_text, "native_output_ref": {"id": "native/replay/one", "sha256": sha256(raw_text.encode("utf-8")).hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]},
        "target_text": "Quick Apply",
        "refinement_policy": {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False},
    }
    replay = execute_learning_stage_worker_task("panel_learning_hybrid_selection", payload)
    assert replay["outcome"] == "completed"
    assert replay["review_projection"]["execution_origin"] == "replay"
    assert replay["review_projection"]["screen_facts"]["execution_origin"] == "replay"
    refinement_blocked = execute_learning_stage_worker_task("panel_learning_hybrid_selection", {**payload, "refinement_policy": {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": True}})
    assert refinement_blocked["outcome"] == "safe_stopped"
    assert refinement_blocked["reason"] == "refinement_provider_not_ready"
    assert refinement_blocked["review_projection"] is None

    blocked = execute_learning_stage_worker_task("panel_learning_hybrid_selection", {**payload, "execution_origin": "actual_model", "gui_actor_provider_state": "ready"})
    assert blocked["outcome"] == "safe_stopped"
    assert blocked["reason"] == "actual_execution_required"


def test_worker_rejects_mode_task_crossovers_before_handlers() -> None:
    import pytest
    from app.learn.workflow_worker import LearningStageWorkerError, execute_learning_stage_worker_task

    with pytest.raises(LearningStageWorkerError, match="selection task requires hybrid_v1_2"):
        execute_learning_stage_worker_task("panel_learning_hybrid_selection", {"learning_pipeline_mode": "incumbent"})
    with pytest.raises(LearningStageWorkerError, match="hybrid_v1_2 supports only selection"):
        execute_learning_stage_worker_task("panel_learning_hybrid_fusion", {"learning_pipeline_mode": "hybrid_v1_2"})


def test_experimental_config_uses_actual_wire_provider_ids_and_frozen_policy():
    import json
    from pathlib import Path
    from app.learn.hybrid.refinement_policy import MODES_POLICY_VERSION, EDGE_TRIGGER_VERSION, EDGE_MARGIN_RATIO
    from app.learn.hybrid.vista_current_source import VISTA_PROVIDER
    from app.learn.recognition.uei.omniparser_shadow_adapter import PROVIDER_ID
    config = json.loads((Path(__file__).resolve().parents[1] / "configs/learn_hybrid_v1_2.json").read_text(encoding="utf-8"))
    assert config["providers"] == {"omni": PROVIDER_ID, "selection": "gui_actor_3b_bf16", "refinement": VISTA_PROVIDER}
    assert config["refinement"] == {"policy_version": MODES_POLICY_VERSION, "mode": "conditional", "trigger_version": EDGE_TRIGGER_VERSION, "threshold_ratio": EDGE_MARGIN_RATIO}
