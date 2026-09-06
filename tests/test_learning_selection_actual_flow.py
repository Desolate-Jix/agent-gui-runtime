from copy import deepcopy
from hashlib import sha256

import pytest

from tests.test_learning_selection_roundtrip import _payload


def _fixture(tmp_path, monkeypatch, *, omni_outcome="completed", cleanup="clean"):
    from app.learn.hybrid import selection_actual

    facts, original = _payload(tmp_path)
    order = []

    def omni(payload, **kwargs):
        order.append("omni")
        assert kwargs["configuration"] == "trusted-test-config"
        return {"outcome": omni_outcome, "cleanup_status": cleanup,
                "inventory": original["omni_inventory"], "provider_result_ref": {"id": "test", "content_sha256": "a" * 64}}

    def actor(**kwargs):
        order.append("actor")
        native = original["gui_actor_selection_input"]
        return {"contract_version": "gui_actor_current_source_result_v1", **deepcopy(native),
                "target_sha256": sha256(original["target_text"].encode("utf-8")).hexdigest(),
                "current_source_receipt": {"contract_version": "gui_actor_current_source_receipt_v1",
                    "source_binding": "current_source_external_v1", "code_identity": {"fixture.py": "a" * 64}},
                "child_exit_code": 0, "cleanup": {"status": "verified_exact_child_exited", "exit_code": 0}}

    monkeypatch.setattr(selection_actual, "run_hybrid_omni_discovery", omni)
    monkeypatch.setattr(selection_actual, "run_gui_actor_once", actor)
    return facts, original, order


def _run(tmp_path, original, **kwargs):
    from app.learn.workflow_service import run_learning_selection_actual_no_action
    return run_learning_selection_actual_no_action(
        project_root=tmp_path, run_id=original["run_id"], workflow_revision=original["workflow_revision"],
        capture_bundle_ref=original["capture_bundle"]["bundle_ref"], image_path=original["capture_image_path"],
        target_text=original["target_text"], omni_configuration="trusted-test-config",
        artifact_root=tmp_path / "model-fixture", out_dir=tmp_path / "actual-run", **kwargs,
    )


def test_actual_coordinator_runs_sequentially_and_persists_for_existing_review(tmp_path, monkeypatch):
    from app.learn.draft_review import load_learning_draft_review
    _, original, order = _fixture(tmp_path, monkeypatch)
    result = _run(tmp_path, original)
    assert order == ["omni", "actor"]
    assert result["outcome"] == "completed"
    assert result["execute_binding_enabled"] is False
    loaded = load_learning_draft_review(result["trial_path"], project_root=tmp_path)
    assert loaded["hybrid_review_projection"]["execution_origin"] == "actual_model"
    assert loaded["hybrid_review_projection"]["learning_state"] == "needs_semantic_review"


@pytest.mark.parametrize("outcome,cleanup", [("failed", "clean"), ("completed", "failed")])
def test_failed_omni_or_cleanup_never_launches_selector(tmp_path, monkeypatch, outcome, cleanup):
    _, original, order = _fixture(tmp_path, monkeypatch, omni_outcome=outcome, cleanup=cleanup)
    result = _run(tmp_path, original)
    assert order == ["omni"]
    assert result["outcome"] == "safe_stopped"
    assert result["trial_path"] is None


def test_mismatched_image_stops_before_any_model(tmp_path, monkeypatch):
    facts, original, order = _fixture(tmp_path, monkeypatch)
    facts["image"].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA|sha|image"):
        _run(tmp_path, original)
    assert order == []


def test_static_capture_crosses_actual_coordinator_and_existing_store(tmp_path, monkeypatch):
    from app.learn.hybrid import omni_discovery, selection_actual
    from app.learn.hybrid.static_capture import seal_static_capture_bundle
    from app.learn.draft_review import load_learning_draft_review
    from tests.test_learning_static_capture import _static_inputs
    from tests.test_learn_hybrid_omni_discovery import _RecordedAdapter

    image, asset = _static_inputs(tmp_path)
    bundle = seal_static_capture_bundle(project_root=tmp_path, image_path=image,
                                        run_id="static-flow", workflow_revision=0, static_asset=asset)
    raw = '{"topk_points":[[0.5,0.4]]}'
    proof = {"contract_version": "gui_actor_current_source_result_v1", "raw_output_utf8": raw,
             "native_output_ref": {"id": "fixture/static", "sha256": sha256(raw.encode()).hexdigest()},
             "provider_id": "gui_actor_3b_bf16", "source_score": None,
             "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16",
                                "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"},
             "image_sha256": bundle["capture_identity"]["screenshot_sha256"], "target_sha256": sha256(b"target").hexdigest(),
             "current_source_receipt": {"contract_version": "gui_actor_current_source_receipt_v1",
                "source_binding": "current_source_external_v1", "code_identity": {"fixture": "a" * 64}},
             "child_exit_code": 0, "cleanup": {"status": "verified_exact_child_exited", "exit_code": 0}}
    monkeypatch.setattr(selection_actual, "run_gui_actor_once", lambda **kwargs: deepcopy(proof))
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda **kwargs: _RecordedAdapter())
    result = selection_actual.run_actual_selection(
        project_root=tmp_path, run_id="static-flow", workflow_revision=0, capture_bundle_ref=bundle["bundle_ref"],
        image_path=image, target_text="target", omni_configuration="trusted-test-config",
        artifact_root=tmp_path, out_dir=tmp_path / "static-actual",
    )
    assert result["outcome"] == "completed"
    loaded = load_learning_draft_review(result["trial_path"], project_root=tmp_path)
    assert loaded["hybrid_review_projection"]["execution_origin"] == "actual_model"
    assert loaded["hybrid_selection_review_parent_evidence"]["capture_bundle"]["context"]["sources"] == []


def test_cli_rejects_unpinned_manifest_before_reading_case_fields():
    from scripts.run_learning_selection_actual import _verify_known_case
    with pytest.raises(ValueError, match="pinned existing public"):
        _verify_known_case({}, b"{}")


def test_actor_preflight_failure_is_visible_and_does_not_publish_trial(tmp_path, monkeypatch):
    from app.learn.hybrid import selection_actual
    _, original, order = _fixture(tmp_path, monkeypatch)
    def fail(**kwargs):
        raise selection_actual.GuiActorCurrentSourceError("GPU preflight blocked")
    monkeypatch.setattr(selection_actual, "run_gui_actor_once", fail)
    result = _run(tmp_path, original)
    assert result["outcome"] == "safe_stopped"
    assert result["trial_path"] is None
    assert "GPU preflight blocked" in result["reason"]
    assert (tmp_path / "actual-run/result.json").is_file()


def _vista(monkeypatch, order, *, cleanup_ok=True):
    from app.learn.hybrid import selection_actual
    def run(**kwargs):
        order.append("vista")
        raw = "[500,500]"
        return {"contract_version": "vista_current_source_result_v1", "provider_id": "vista_4b",
            "raw_output_utf8": raw, "source_score": None,
            "native_output_ref": {"id": "vista/actual-test", "sha256": sha256(raw.encode()).hexdigest()},
            "roi_image_sha256": sha256(kwargs["image_path"].read_bytes()).hexdigest(),
            "target_sha256": sha256(kwargs["target_text"].encode()).hexdigest(),
            "current_source_receipt": {"contract_version": "vista_current_source_receipt_v1", "code_identity": {"fixture": "a" * 64}},
            "cleanup": {"status": "verified_exact_child_killed", "owned_tree_exited": cleanup_ok, "listener_absent": cleanup_ok},
            "execute_binding_enabled": False, "artifact_is_authorization": False}
    monkeypatch.setattr(selection_actual, "run_vista_once", run)


def test_always_refinement_runs_after_actor_cleanup_and_roundtrips(tmp_path, monkeypatch):
    from app.learn.draft_review import load_learning_draft_review
    _, original, order = _fixture(tmp_path, monkeypatch)
    _vista(monkeypatch, order)
    result = _run(tmp_path, original, refinement_mode="always")
    assert order == ["omni", "actor", "vista"]
    assert result["outcome"] == "completed"
    assert result["refinement_status"] == "validated"
    assert result["canonical_capture_pixel_point"] == [80, 36]
    loaded = load_learning_draft_review(result["trial_path"], project_root=tmp_path)
    assert loaded["hybrid_review_projection"]["refinement"]["status"] == "validated"
    assert loaded["hybrid_selection_review_parent_evidence"]["vista_refinement_input"]["provider_result"]["cleanup"]["owned_tree_exited"] is True


@pytest.mark.parametrize("mode", ["never", "conditional"])
def test_untriggered_policies_do_not_run_vista(tmp_path, monkeypatch, mode):
    _, original, order = _fixture(tmp_path, monkeypatch)
    _vista(monkeypatch, order)
    result = _run(tmp_path, original, refinement_mode=mode)
    assert order == ["omni", "actor"]
    assert result["refinement_status"] == "skipped"
    assert result["refinement_trigger"]["triggered"] is False
    assert result["canonical_capture_pixel_point"] == result["original_capture_pixel_point"]


def test_invalid_refinement_mode_stops_before_models(tmp_path, monkeypatch):
    _, original, order = _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="refinement_mode"):
        _run(tmp_path, original, refinement_mode="unknown")
    assert order == []


def test_vista_cleanup_failure_is_not_published_or_fallback_scored(tmp_path, monkeypatch):
    _, original, order = _fixture(tmp_path, monkeypatch)
    _vista(monkeypatch, order, cleanup_ok=False)
    result = _run(tmp_path, original, refinement_mode="always")
    assert result["outcome"] == "safe_stopped"
    assert result["canonical_capture_pixel_point"] is None
    assert result["trial_path"] is None
    assert "cleanup" in result["reason"]


def test_geometric_trigger_uses_border_distance_not_score(tmp_path):
    from app.learn.hybrid.selection_actual import selection_geometry_trigger
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    _, payload = _payload(tmp_path)
    selection = parse_gui_actor_selection(payload["gui_actor_selection_input"], capture_bundle=payload["capture_bundle"], omni_inventory=payload["omni_inventory"], target_text=payload["target_text"])
    candidate = next(c for c in payload["omni_inventory"]["candidates"] if c["candidate_id"] == selection["candidate_id"])
    x1, y1, x2, y2 = candidate["bbox_original"]
    selection["model_proposal"]["canonical_capture_pixel_point"] = [x1 + 0.01 * (x2-x1), (y1+y2)/2]
    trigger = selection_geometry_trigger(selection=selection, inventory=payload["omni_inventory"])
    assert trigger["triggered"] is True
    assert trigger["threshold_ratio"] == 0.1
    assert trigger["source_score_used"] is False


def test_actor_unverified_cleanup_never_starts_refiner(tmp_path, monkeypatch):
    from app.learn.hybrid import selection_actual
    _, original, order = _fixture(tmp_path, monkeypatch)
    original_actor = selection_actual.run_gui_actor_once
    def dirty_actor(**kwargs):
        result = original_actor(**kwargs)
        result["cleanup"]["status"] = "cleanup_failed"
        return result
    monkeypatch.setattr(selection_actual, "run_gui_actor_once", dirty_actor)
    _vista(monkeypatch, order)
    result = _run(tmp_path, original, refinement_mode="always")
    assert order == ["omni", "actor"]
    assert result["outcome"] == "safe_stopped"
    assert result["canonical_capture_pixel_point"] is None
    assert "child_cleanup" in result["reason"]


def test_conditional_trigger_starts_refiner(tmp_path, monkeypatch):
    from app.learn.hybrid import selection_actual
    _, original, order = _fixture(tmp_path, monkeypatch)
    _vista(monkeypatch, order)
    trigger = selection_actual.selection_geometry_trigger
    monkeypatch.setattr(selection_actual, "selection_geometry_trigger", lambda **kwargs: {**trigger(**kwargs), "triggered": True})
    result = _run(tmp_path, original, refinement_mode="conditional")
    assert order == ["omni", "actor", "vista"]
    assert result["refinement_status"] == "validated"


def test_refiner_runtime_failure_leaves_explicit_stop_not_original_point(tmp_path, monkeypatch):
    from app.learn.hybrid import selection_actual
    _, original, order = _fixture(tmp_path, monkeypatch)
    def fail(**kwargs):
        order.append("vista")
        raise selection_actual.VistaCurrentSourceError("owned server request timed out")
    monkeypatch.setattr(selection_actual, "run_vista_once", fail)
    result = _run(tmp_path, original, refinement_mode="always")
    assert order == ["omni", "actor", "vista"]
    assert result["outcome"] == "safe_stopped"
    assert result["original_capture_pixel_point"] is not None
    assert result["canonical_capture_pixel_point"] is None
    assert "timed out" in result["reason"]
