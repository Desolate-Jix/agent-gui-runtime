from __future__ import annotations

from app.learn.recognition.model_review import apply_review_patch, build_missing_locator_tasks, validate_review_patch
from app.learn.recognition.repair_executor import execute_deterministic_repairs
from app.learn.recognition.review_workflow import (
    build_removal_resolutions,
    run_replacement_integrity_gate,
    run_review_repair_workflow,
)


def _stage2(*, with_child: bool = True) -> dict:
    items = []
    member_ids = []
    if with_child:
        items = [
            {
                "item_id": "member_row_1",
                "number": "1.1",
                "role": "list_item",
                "bbox": {"x": 720, "y": 100, "w": 180, "h": 50},
            }
        ]
        member_ids = ["member_row_1"]
    return {
        "contract_version": "learn_stage2_numbering_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "regions": [
            {
                "region_id": "message_thread",
                "label": "message thread",
                "bbox": {"x": 200, "y": 0, "w": 700, "h": 900},
                "numbered_items": items,
                "subregion_groups": [
                    {
                        "group_id": "false_card",
                        "role": "tile_card_parent",
                        "bbox": {"x": 700, "y": 80, "w": 200, "h": 700},
                        "member_item_ids": member_ids,
                    }
                ],
            }
        ],
    }


def _validated_remove(stage2: dict, *, missing: list[dict] | None = None) -> dict:
    return validate_review_patch(
        stage2,
        {
            "keep": [],
            "remove": [{"region_id": "false_card", "reason": "overmerged wrapper"}],
            "relabel": [],
            "missing": missing or [],
            "needs_human_review": [],
        },
    )


def test_removed_wrapper_preserves_child_items_and_resolves_by_reparenting() -> None:
    stage2 = _stage2()
    patch = _validated_remove(stage2)
    reviewed = apply_review_patch(stage2, patch)
    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/chat.png")

    resolutions = build_removal_resolutions(stage2, reviewed, patch, handoff)

    assert reviewed["regions"][0]["numbered_items"][0]["item_id"] == "member_row_1"
    assert resolutions == [
        {
            "removed_region_id": "false_card",
            "content_disposition": "children_reparented",
            "preserved_child_ids": ["member_row_1"],
            "replacement_region_ids": [],
            "replacement_parent_id": "message_thread",
            "repair_request_id": None,
            "repair_route": None,
            "coverage_status": "resolved",
            "reason": "existing atomic children remain under the Stage1 parent",
        }
    ]


def test_review_patch_preserves_atomic_control_parent_stream_when_semantic_wrapper_is_removed() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["control_parents"] = [
        {
            "object_id": "control_parent_member_row_1",
            "label": "Member row",
            "role": "atomic_control_parent",
            "bbox": {"x": 720, "y": 100, "w": 180, "h": 50},
            "member_object_ids": ["member_row_1"],
            "source": "factual_control_hit_area",
        }
    ]
    patch = _validated_remove(stage2)

    reviewed = apply_review_patch(stage2, patch)

    assert reviewed["regions"][0]["subregion_groups"] == []
    assert reviewed["regions"][0]["control_parents"] == stage2["regions"][0]["control_parents"]
    assert reviewed["regions"][0]["numbered_items"][0]["item_id"] == "member_row_1"


def test_removed_wrapper_with_overlapping_stage1_repair_stays_pending() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "right member pane",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                "repair_route": "stage1_repartition",
                "reason": "distinct edge pane",
            }
        ],
    )
    reviewed = apply_review_patch(stage2, patch)
    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/chat.png")

    resolution = build_removal_resolutions(stage2, reviewed, patch, handoff)[0]

    assert resolution["content_disposition"] == "stage1_repartition"
    assert resolution["preserved_child_ids"] == ["member_row_1"]
    assert resolution["repair_request_id"] == "model_review_missing_1"
    assert resolution["coverage_status"] == "repair_pending"


def test_removed_wrapper_with_preserved_children_ignores_independent_precise_candidate() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "independent row heading",
                "parent_region_id": "message_thread",
                "expected_role": "list_item",
                "rough_roi": {"x": 720, "y": 100, "w": 180, "h": 300},
                "repair_route": "precise_locator",
                "reason": "uncovered atomic candidate",
                "candidate_id": "M11",
                "candidate_member_item_ids": ["member_row_1"],
                "geometry_source": "uncovered_atomic_evidence_cluster_v2",
            }
        ],
    )
    reviewed = apply_review_patch(stage2, patch)
    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/chat.png")

    resolution = build_removal_resolutions(stage2, reviewed, patch, handoff)[0]

    assert resolution["content_disposition"] == "children_reparented"
    assert resolution["coverage_status"] == "resolved"
    assert resolution["repair_request_id"] is None


def test_removed_wrapper_without_children_or_repair_requires_human_review() -> None:
    stage2 = _stage2(with_child=False)
    patch = _validated_remove(stage2)
    reviewed = apply_review_patch(stage2, patch)
    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/chat.png")

    resolution = build_removal_resolutions(stage2, reviewed, patch, handoff)[0]

    assert resolution["content_disposition"] == "needs_human_review"
    assert resolution["coverage_status"] == "unresolved"


def test_workflow_stops_at_repair_pending_without_stage1_result() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "right member pane",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                "repair_route": "stage1_repartition",
                "reason": "distinct edge pane",
            }
        ],
    )

    result = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
    )

    assert result["workflow_state"] == "repair_pending"
    assert result["completed"] is False
    assert result["completed_review_only"] is False
    assert result["repair_pending_count"] == 1
    assert result["replacement_integrity_gate"]["passed"] is False
    assert result["replacement_integrity_gate"]["failure_categories"] == ["repair_pending"]
    request = result["generic_repair_requests"]["requests"][0]
    assert request["source_removed_region_ids"] == ["false_card"]
    assert request["source_child_item_ids"] == ["member_row_1"]


def test_workflow_completes_only_after_trusted_repair_recomposes_replacement() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "right member pane",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                "repair_route": "stage1_repartition",
                "reason": "distinct edge pane",
            }
        ],
    )
    repair_results = {
        "contract_version": "learning_review_repair_results_v1",
        "results": [
            {
                "repair_request_id": "model_review_missing_1",
                "status": "passed",
                "repair_route": "stage1_repartition",
                "geometry_source": "deterministic_stage1_repartition_v1",
                "replacement_regions": [
                    {
                        "region_id": "repaired_member_list",
                        "parent_region_id": "message_thread",
                        "role": "member_list",
                        "bbox": {"x": 720, "y": 0, "w": 180, "h": 900},
                    }
                ],
            }
        ],
    }

    result = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
        repair_results=repair_results,
    )

    assert result["workflow_state"] == "completed_review_only"
    assert result["completed"] is True
    assert result["completed_review_only"] is True
    assert result["replacement_integrity_gate"]["passed"] is True
    assert result["removal_resolutions"][0]["coverage_status"] == "resolved"
    assert result["removal_resolutions"][0]["replacement_region_ids"] == ["repaired_member_list"]
    groups = result["recomposed_stage2"]["regions"][0]["subregion_groups"]
    assert groups[0]["group_id"] == "repaired_member_list"
    assert groups[0]["bbox"] == {"x": 720, "y": 0, "w": 180, "h": 900}
    assert result["safety"]["real_clicks"] == 0


def test_workflow_accepts_deterministic_atomic_evidence_repair() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "right member pane",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                "repair_route": "stage1_repartition",
                "reason": "distinct edge pane",
            }
        ],
    )
    pending = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
    )
    repair_results = execute_deterministic_repairs(stage2, pending["generic_repair_requests"])

    result = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
        repair_results=repair_results,
    )

    assert result["workflow_state"] == "completed_review_only"
    assert result["replacement_integrity_gate"]["passed"] is True
    replacement = result["recomposed_stage2"]["regions"][0]["subregion_groups"][0]
    assert replacement["bbox"] == {"x": 720, "y": 100, "w": 180, "h": 50}
    assert replacement["repair_evidence"]["geometry_source"] == "deterministic_atomic_evidence_union_v1"


def test_replacement_region_reparents_semantically_owned_group_with_small_padding() -> None:
    stage2 = _stage2()
    region = stage2["regions"][0]
    region["subregion_groups"].append(
        {
            "group_id": "existing_content_hunk",
            "role": "content_region",
            "bbox": {"x": 718, "y": 98, "w": 184, "h": 54},
            "member_item_ids": ["member_row_1"],
        }
    )
    patch = validate_review_patch(
        stage2,
        {
            "keep": [{"region_id": "existing_content_hunk", "reason": "coherent local hunk"}],
            "remove": [{"region_id": "false_card", "reason": "overmerged wrapper"}],
            "relabel": [],
            "missing": [
                {
                    "description": "containing content pane",
                    "parent_region_id": "message_thread",
                    "expected_role": "content_region",
                    "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                    "repair_route": "stage1_repartition",
                    "reason": "missing structural parent",
                }
            ],
            "needs_human_review": [],
        },
    )
    pending = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
    )
    repair_results = execute_deterministic_repairs(stage2, pending["generic_repair_requests"])

    result = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
        repair_results=repair_results,
    )

    groups = result["recomposed_stage2"]["regions"][0]["subregion_groups"]
    replacement = next(group for group in groups if group["group_id"].endswith("_deterministic_region"))
    existing = next(group for group in groups if group["group_id"] == "existing_content_hunk")
    assert existing["parent_group_id"] == replacement["group_id"]
    assert replacement["child_group_ids"] == ["existing_content_hunk"]


def test_workflow_rejects_rough_roi_as_final_replacement_geometry() -> None:
    stage2 = _stage2()
    patch = _validated_remove(
        stage2,
        missing=[
            {
                "description": "right member pane",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 80, "w": 200, "h": 700},
                "repair_route": "stage1_repartition",
                "reason": "distinct edge pane",
            }
        ],
    )
    repair_results = {
        "contract_version": "learning_review_repair_results_v1",
        "results": [
            {
                "repair_request_id": "model_review_missing_1",
                "status": "passed",
                "repair_route": "stage1_repartition",
                "geometry_source": "model_rough_roi",
                "replacement_regions": [
                    {
                        "region_id": "unsafe_member_list",
                        "parent_region_id": "message_thread",
                        "role": "member_list",
                        "bbox": {"x": 700, "y": 80, "w": 200, "h": 700},
                    }
                ],
            }
        ],
    }

    result = run_review_repair_workflow(
        stage2=stage2,
        validated_patch=patch,
        screenshot_path="D:/screens/chat.png",
        repair_results=repair_results,
    )

    assert result["workflow_state"] == "repair_failed"
    assert result["completed"] is False
    assert result["replacement_integrity_gate"]["failure_categories"] == ["untrusted_repair_geometry"]


def test_integrity_gate_counts_patch_level_human_review_blockers() -> None:
    gate = run_replacement_integrity_gate(
        recomposed_stage2=_stage2(),
        validated_patch={
            "remove": [],
            "needs_human_review": [
                {"region_id": "false_card", "reason": "focused review protocol failure"},
                {"region_id": "member_row_1", "reason": "semantic ambiguity"},
            ],
        },
        resolutions=[],
    )

    assert gate["passed"] is False
    assert gate["needs_human_review"] == 2
    assert gate["failure_categories"] == ["needs_human_review"]
