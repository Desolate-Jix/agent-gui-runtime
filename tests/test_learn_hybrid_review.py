from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.learn.draft_review import load_learning_draft_review
from app.learn.hybrid.review_projection import (
    apply_hybrid_review_decisions,
    project_hybrid_review,
    validate_hybrid_review_projection,
)
from app.learn.recognition.roi import build_roi_crop_metadata
from app.learn.recognition.uei.canonical import seal_immutable
from tests.test_learn_hybrid_contracts import (
    binding_fixture,
    fusion_fixture,
    vista_fixture,
)
from tests.test_learn_hybrid_fusion import _inventory_for_capture, _verified_bundle
from tests.test_learning_hybrid_vertical_slice import _write_draft


NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


def _server_expectations(bundle: dict) -> dict:
    return {
        "run_id": bundle["run_id"],
        "workflow_revision": bundle["workflow_revision"],
        "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
    }


def _full_parent_fixture(*, candidate_count: int = 1) -> tuple[dict, dict, dict, dict, dict]:
    bundle = _verified_bundle()
    inventory = _inventory_for_capture(
        bundle["capture_identity"], candidate_count=candidate_count
    )
    bindings = binding_fixture(inventory=inventory)
    bindings["context_ref"] = deepcopy(bundle["context_ref"])
    fusion = fusion_fixture(inventory=inventory)
    for candidate in fusion["candidates"][1:]:
        candidate.update(
            state="UNBOUND",
            vista_eligible=False,
            review_required=True,
            reason="not_bound",
        )
    vista = vista_fixture(inventory=inventory)
    _bind_vista_to_trusted_roi_builder(bundle, fusion, vista)
    return bundle, inventory, bindings, fusion, vista


def _bind_vista_to_trusted_roi_builder(
    bundle: dict, fusion: dict, vista: dict,
) -> None:
    """Mirror the Task 7 request builder instead of trusting proposal-owned ROI data."""

    proposals = {item["candidate_id"]: item for item in vista["proposals"]}
    for candidate in fusion["candidates"]:
        if candidate["state"] != "BOUND":
            continue
        bbox = candidate["bbox_original"]
        metadata = build_roi_crop_metadata(
            source_image_size=bundle["capture_identity"]["image_size"],
            candidate_bbox={
                "x": bbox[0], "y": bbox[1],
                "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1],
            },
            crop_size={
                "width": max(1, (bbox[2] - bbox[0]) * 2),
                "height": max(1, (bbox[3] - bbox[1]) * 2),
            },
            expand_scale=2.0,
        )
        roi = metadata["coordinate_transform"]["roi_bbox"]
        proposals[candidate["candidate_id"]]["roi_ref"] = seal_immutable({
            "contract_version": "hybrid_permitted_roi_v1",
            "roi_id": f"roi/{candidate['candidate_id']}",
            "candidate_id": candidate["candidate_id"],
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": [roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]],
            "permitted_for_refinement": True,
        })


def _persistent_full_parent_fixture(
    root: Path, *, candidate_count: int = 1
) -> tuple[dict, dict, dict, dict, dict, Path]:
    from app.learn.hybrid.capture import (
        load_and_verify_hybrid_capture_bundle,
        seal_hybrid_capture_bundle,
    )
    from tests.test_learn_hybrid_capture import _context, _identity, _window

    image, identity = _identity(
        root,
        run_id="run-review-v2",
        revision=8,
        name="review-v2.png",
        size=(1280, 720),
    )
    saved = seal_hybrid_capture_bundle(
        project_root=root,
        image_path=image,
        run_id="run-review-v2",
        workflow_revision=8,
        window_binding=_window(),
        ocr_uia_context=_context(
            root,
            identity,
            run_id="run-review-v2",
            revision=8,
        ),
        capture_envelope=identity.capture_envelope,
    )
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=saved["bundle_ref"],
        expected_run_id="run-review-v2",
        expected_workflow_revision=8,
    )
    inventory = _inventory_for_capture(bundle["capture_identity"], candidate_count=candidate_count)
    bindings = binding_fixture(inventory=inventory)
    bindings["context_ref"] = deepcopy(bundle["context_ref"])
    fusion = fusion_fixture(inventory=inventory)
    for candidate in fusion["candidates"][1:]:
        candidate.update(
            state="UNBOUND",
            vista_eligible=False,
            review_required=True,
            reason="not_bound",
        )
    vista = vista_fixture(inventory=inventory)
    _bind_vista_to_trusted_roi_builder(bundle, fusion, vista)
    return bundle, inventory, bindings, fusion, vista, image


def test_full_parent_projection_keeps_model_evidence_immutable_and_non_authorizing() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()

    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )

    assert projection["contract_version"] == "hybrid_review_projection_v2"
    assert {
        candidate["candidate_id"] for candidate in projection["candidates"]
    } == {inventory["candidates"][0]["candidate_id"]}
    candidate = projection["candidates"][0]
    assert candidate["model_proposal"]["bbox_original"] == [10, 20, 110, 70]
    assert candidate["model_proposal"]["omni_candidate"] == inventory["candidates"][0]
    assert candidate["model_proposal"]["qwen_binding"] == bindings["bindings"][0]
    assert candidate["model_proposal"]["fusion_decision"] == fusion["candidates"][0]
    assert candidate["model_proposal"]["vista_proposal"] == vista["proposals"][0]
    assert candidate["review_decisions"] == []
    assert candidate["reviewed_geometry"]["bbox"] == [10, 20, 110, 70]
    assert candidate["reviewed_by_human"] is False
    assert projection["screen_facts"]["capture_lineage_ref"] == bundle["capture_lineage_ref"]
    assert "bbox" not in projection["screen_facts"]
    assert all(projection[field] == expected for field, expected in NON_AUTHORIZING.items())


def test_full_parent_projection_rejects_any_parent_capture_mismatch() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    mismatched = deepcopy(bindings)
    mismatched["capture_identity"]["screenshot_sha256"] = "cd" * 32

    with pytest.raises(ValueError, match="capture|lineage|sha256"):
        project_hybrid_review(
            capture_bundle=bundle,
            omni_inventory=inventory,
            qwen_bindings=mismatched,
            fusion_result=fusion,
            vista_proposals=vista,
        )


def test_full_parent_projection_rejects_well_formed_but_unpermitted_vista_roi() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    proposal = vista["proposals"][0]
    wrong_roi = deepcopy(proposal["roi_ref"])
    wrong_roi["xyxy"] = [10, 20, 90, 60]
    proposal["roi_ref"] = seal_immutable(wrong_roi)

    with pytest.raises(ValueError, match="permitted ROI"):
        project_hybrid_review(
            capture_bundle=bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            fusion_result=fusion,
            vista_proposals=vista,
        )


def test_human_and_vista_points_never_use_runtime_point_keys() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )

    forbidden = {
        "actual_point",
        "click_point",
        "confirmed_point",
        "expected_point",
        "screen_point",
        "target_point",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(projection)


def test_rebox_semantic_point_and_tombstone_are_append_only_derived_review_facts() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    candidate_id = inventory["candidates"][0]["candidate_id"]
    original_model = deepcopy(projection["candidates"][0]["model_proposal"])

    reviewed = apply_hybrid_review_decisions(
        projection,
        [
            {
                "decision_id": "decision/rebox-1",
                "decision_type": "rebox",
                "candidate_id": candidate_id,
                "bbox": [20, 24, 100, 64],
            },
            {
                "decision_id": "decision/semantic-1",
                "decision_type": "semantic_edit",
                "candidate_id": candidate_id,
                "semantics": {
                    "role": "button",
                    "label": "Continue",
                    "description": "advances one review step",
                },
            },
            {
                "decision_id": "decision/point-1",
                "decision_type": "human_point",
                "candidate_id": candidate_id,
                "human_point_proposal": {
                    "coordinate_space": "capture_pixel_xyxy",
                    "xy": [60, 44],
                },
            },
            {
                "decision_id": "decision/delete-1",
                "decision_type": "tombstone",
                "candidate_id": candidate_id,
                "reason": "not_available",
            },
        ],
    )

    candidate = reviewed["candidates"][0]
    assert candidate["model_proposal"] == original_model
    assert candidate["reviewed_geometry"]["bbox"] == [20, 24, 100, 64]
    assert candidate["reviewed_semantics"]["label"] == "Continue"
    assert candidate["human_point_proposal"]["xy"] == [60, 44]
    assert candidate["model_proposal"]["vista_proposal"] == vista["proposals"][0]
    assert candidate["tombstone"]["reason"] == "not_available"
    assert [item["decision_id"] for item in candidate["review_decisions"]] == [
        "decision/rebox-1",
        "decision/semantic-1",
        "decision/point-1",
        "decision/delete-1",
    ]
    assert candidate["reviewed_by_human"] is False
    assert validate_hybrid_review_projection(reviewed) == reviewed


def test_human_add_ids_remain_unique_after_tombstone_and_reload() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )

    first = apply_hybrid_review_decisions(
        projection,
        [{
            "decision_id": "decision/add-1",
            "decision_type": "add",
            "candidate_id": None,
            "bbox": [120, 20, 180, 60],
            "semantics": {"role": "button", "label": "Next", "description": ""},
        }],
    )
    first_human = next(item for item in first["candidates"] if item["origin_id"].startswith("human/"))
    tombstoned = apply_hybrid_review_decisions(
        first,
        [{
            "decision_id": "decision/tombstone-human-1",
            "decision_type": "tombstone",
            "candidate_id": first_human["candidate_id"],
            "reason": "deleted_by_reviewer",
        }],
    )
    reloaded = deepcopy(tombstoned)
    second = apply_hybrid_review_decisions(
        reloaded,
        [{
            "decision_id": "decision/add-2",
            "decision_type": "add",
            "candidate_id": None,
            "bbox": [125, 24, 185, 64],
            "semantics": {"role": "button", "label": "Next", "description": ""},
        }],
    )
    human_ids = [
        item["origin_id"] for item in second["candidates"] if item["origin_id"].startswith("human/")
    ]
    assert len(human_ids) == 2
    assert len(set(human_ids)) == 2
    assert second["candidates"][-2]["tombstone"] is not None
    assert validate_hybrid_review_projection(second) == second


def test_review_decisions_reject_duplicate_ids_and_out_of_bounds_geometry() -> None:
    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    candidate_id = inventory["candidates"][0]["candidate_id"]
    decision = {
        "decision_id": "decision/rebox-1",
        "decision_type": "rebox",
        "candidate_id": candidate_id,
        "bbox": [20, 24, 100, 64],
    }
    reviewed = apply_hybrid_review_decisions(projection, [decision])

    with pytest.raises(ValueError, match="duplicate review decision"):
        apply_hybrid_review_decisions(reviewed, [decision])
    with pytest.raises(ValueError, match="capture bounds"):
        apply_hybrid_review_decisions(
            projection,
            [{**decision, "decision_id": "decision/rebox-2", "bbox": [20, 24, 2000, 64]}],
        )


def test_embedded_full_parent_projection_loads_every_candidate_into_large_review(
    tmp_path: Path,
) -> None:
    bundle, inventory, bindings, fusion, vista, image = _persistent_full_parent_fixture(
        tmp_path, candidate_count=2
    )
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    facts = {"bundle": bundle, "image": image}
    source = _write_draft(
        tmp_path,
        facts,
        embedded_projection=projection,
        case="full-parent-v2",
    )

    loaded = load_learning_draft_review(
        source,
        project_root=tmp_path,
        expected_hybrid_run_id="run-review-v2",
        expected_hybrid_workflow_revision=8,
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )

    assert loaded["hybrid_review_projection_status"]["status"] == "projected"
    assert [item["candidate_id"] for item in loaded["draft"]["regions"]] == [
        item["candidate_id"] for item in projection["candidates"]
    ]
    selected = loaded["draft"]["regions"][0]
    assert selected["bbox_original"] == [10, 20, 110, 70]
    assert selected["reviewed_geometry"]["bbox"] == [10, 20, 110, 70]
    assert "raw_provider_item" not in selected["provider_provenance"]
    assert selected["provider_provenance"]["source_item_id"] == "omni-item-0"

    stale = load_learning_draft_review(
        source,
        project_root=tmp_path,
        expected_hybrid_run_id="run-review-v2",
        expected_hybrid_workflow_revision=9,
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )
    assert stale["draft"]["regions"] == []
    assert stale["hybrid_review_projection_status"]["status"] == "rejected"

    wrong_lineage = load_learning_draft_review(
        source,
        project_root=tmp_path,
        expected_hybrid_run_id="run-review-v2",
        expected_hybrid_workflow_revision=8,
        expected_current_capture_lineage_ref={
            "id": "same-image-wrong-capture",
            "content_sha256": "ef" * 32,
        },
    )
    assert wrong_lineage["draft"]["regions"] == []
    assert wrong_lineage["hybrid_review_projection_status"]["status"] == "rejected"
    assert wrong_lineage["hybrid_review_projection_status"]["reason"] == (
        "hybrid_current_capture_lineage_mismatch"
    )


def test_saved_human_and_vista_proposals_never_authorize_or_surface_runtime_points(
    tmp_path: Path,
) -> None:
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    bundle, inventory, bindings, fusion, vista, image = _persistent_full_parent_fixture(tmp_path)
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    candidate_id = inventory["candidates"][0]["candidate_id"]
    projection = apply_hybrid_review_decisions(
        projection,
        [{
            "decision_id": "decision/no-authority-point",
            "decision_type": "human_point",
            "candidate_id": candidate_id,
            "human_point_proposal": {
                "coordinate_space": "capture_pixel_xyxy",
                "xy": [60, 44],
            },
        }],
    )
    source = _write_draft(
        tmp_path,
        {"bundle": bundle, "image": image},
        embedded_projection=projection,
        case="no-authority-v2",
    )
    result = build_pathgraph_candidate_from_review(
        source,
        {
            "review_status": "needs_human_review",
            "source_after_review": "mixed",
            "hybrid_review_decisions": deepcopy(projection["review_decisions"]),
            "_server_hybrid_expectations": _server_expectations(bundle),
        },
        project_root=tmp_path,
    )

    forbidden = {
        "actual_point",
        "click_point",
        "confirmed_point",
        "expected_point",
        "screen_point",
        "target_point",
    }

    def assert_safe(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                assert_safe(child)
        elif isinstance(value, list):
            for child in value:
                assert_safe(child)

    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    for key in (
        "reviewed_template_candidate_path",
        "runtime_path_graph_candidate_path",
        "interface_map_candidate_path",
    ):
        saved = json.loads((tmp_path / result[key]).read_text(encoding="utf-8"))
        assert_safe(saved)


def test_save_reload_preserves_hybrid_decisions_and_revokes_current_approval(
    tmp_path: Path,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    bundle, inventory, bindings, fusion, vista, image = _persistent_full_parent_fixture(tmp_path)
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    model_before = deepcopy(projection["candidates"][0]["model_proposal"])
    candidate_id = inventory["candidates"][0]["candidate_id"]
    source = _write_draft(
        tmp_path,
        {"bundle": bundle, "image": image},
        embedded_projection=projection,
        case="save-reload-v2",
    )
    decision = {
        "decision_id": "decision/save-rebox-1",
        "decision_type": "rebox",
        "candidate_id": candidate_id,
        "bbox": [20, 24, 100, 64],
    }
    initial_review = load_learning_draft_review(
        source,
        project_root=tmp_path,
        expected_hybrid_run_id="run-review-v2",
        expected_hybrid_workflow_revision=8,
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )
    bound_screen = initial_review["draft"]["page_details"]["screen"]
    patch_base = {
        "contract_version": "human_review_patch_v1",
        "screenshot_path": bound_screen["source_image_path"],
        "screenshot_sha256": bound_screen["source_image_sha256"],
        "operations": [],
        "reason": "Hybrid review",
        "source": "human_panel_editor_v1",
    }

    saved = save_reviewed_template_candidate(
        source,
        {
            **patch_base,
            "review_status": "approved_as_assisted_template",
            "source_after_review": "mixed",
            "hybrid_review_decisions": [decision],
        },
        project_root=tmp_path,
        expected_hybrid_run_id=bundle["run_id"],
        expected_hybrid_workflow_revision=bundle["workflow_revision"],
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )
    reviewed_path = tmp_path / saved["reviewed_template_candidate_path"]
    durable = json.loads(reviewed_path.read_text(encoding="utf-8"))
    durable_projection = durable["draft"]["hybrid_review_projection"]
    assert durable_projection["candidates"][0]["model_proposal"] == model_before
    assert durable_projection["candidates"][0]["reviewed_geometry"]["bbox"] == [20, 24, 100, 64]
    assert len(durable_projection["review_decisions"]) == 1
    assert durable["reviewed_by_human"] is False
    assert durable["review_status"] == "needs_human_review"

    reloaded = load_learning_draft_review(
        reviewed_path,
        project_root=tmp_path,
        expected_hybrid_run_id="run-review-v2",
        expected_hybrid_workflow_revision=8,
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )
    assert reloaded["hybrid_review_projection_status"]["status"] == "projected"
    assert reloaded["draft"]["regions"][0]["reviewed_geometry"]["bbox"] == [20, 24, 100, 64]
    assert len(reloaded["hybrid_review_projection"]["review_decisions"]) == 1

    saved_again = save_reviewed_template_candidate(
        reviewed_path,
        {
            **patch_base,
            "review_status": "needs_human_review",
            "source_after_review": "mixed",
            "hybrid_review_decisions": [decision],
        },
        project_root=tmp_path,
        expected_hybrid_run_id=bundle["run_id"],
        expected_hybrid_workflow_revision=bundle["workflow_revision"],
        expected_current_capture_lineage_ref=bundle["capture_lineage_ref"],
    )
    durable_again = json.loads(
        (tmp_path / saved_again["reviewed_template_candidate_path"]).read_text(encoding="utf-8")
    )
    assert len(durable_again["draft"]["hybrid_review_projection"]["review_decisions"]) == 1
    assert saved_again["human_review_patch_revision"] > saved["human_review_patch_revision"]


def test_recognition_attachment_accepts_only_exact_displayed_full_parent_projection() -> None:
    from app.learn.workflow_tasks.recognition import _attach_hybrid_review_projection_to_draft

    bundle, inventory, bindings, fusion, vista = _full_parent_fixture()
    projection = project_hybrid_review(
        capture_bundle=bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        fusion_result=fusion,
        vista_proposals=vista,
    )
    result = {
        "learning_draft": {
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "page_details": {
                "screen": {
                    "source_image_sha256": bundle["capture_identity"]["screenshot_sha256"],
                }
            }
        }
    }

    _attach_hybrid_review_projection_to_draft(
        result,
        {"hybrid_review_projection": projection},
    )
    assert result["learning_draft"]["hybrid_review_projection"] == projection
    result["learning_draft"]["hybrid_review_projection"]["candidates"].clear()
    assert projection["candidates"]

    stale = deepcopy(result)
    stale["learning_draft"]["page_details"]["screen"]["source_image_sha256"] = "ef" * 32
    with pytest.raises(ValueError, match="displayed screenshot"):
        _attach_hybrid_review_projection_to_draft(
            stale,
            {"hybrid_review_projection": projection},
        )

    missing_lineage = deepcopy(result)
    missing_lineage["learning_draft"].pop("capture_lineage_ref", None)
    with pytest.raises(ValueError, match="capture lineage"):
        _attach_hybrid_review_projection_to_draft(
            missing_lineage,
            {"hybrid_review_projection": projection},
        )

    wrong_lineage = deepcopy(result)
    wrong_lineage["learning_draft"]["capture_lineage_ref"] = {
        "id": "same-image-wrong-capture",
        "content_sha256": "ef" * 32,
    }
    with pytest.raises(ValueError, match="capture lineage"):
        _attach_hybrid_review_projection_to_draft(
            wrong_lineage,
            {"hybrid_review_projection": projection},
        )
