from __future__ import annotations

from app.learn.recognition.model_review import build_missing_locator_tasks, validate_review_patch
from app.learn.recognition.repair_contract import compile_generic_repair_requests
from app.learn.recognition.repair_executor import execute_deterministic_repairs


def _stage2() -> dict:
    return {
        "contract_version": "learn_stage2_numbering_v1",
        "regions": [
            {
                "region_id": "primary_region",
                "label": "primary region",
                "bbox": {"x": 100, "y": 50, "w": 800, "h": 700},
                "numbered_items": [
                    {"item_id": "item_a", "role": "list_item", "bbox": {"x": 650, "y": 80, "w": 180, "h": 40}},
                    {"item_id": "item_b", "role": "list_item", "bbox": {"x": 650, "y": 130, "w": 180, "h": 40}},
                    {"item_id": "item_c", "role": "list_item", "bbox": {"x": 650, "y": 180, "w": 180, "h": 40}},
                ],
                "subregion_groups": [
                    {
                        "group_id": "wrong_wrapper_a",
                        "role": "tile_card_parent",
                        "bbox": {"x": 620, "y": 70, "w": 230, "h": 110},
                        "member_item_ids": ["item_a", "item_b"],
                    },
                    {
                        "group_id": "wrong_wrapper_b",
                        "role": "tile_card_parent",
                        "bbox": {"x": 620, "y": 160, "w": 230, "h": 100},
                        "member_item_ids": ["item_b", "item_c"],
                    },
                ],
            }
        ],
    }


def test_compiler_aggregates_adjacent_removed_wrappers_without_application_rules() -> None:
    stage2 = _stage2()
    patch = validate_review_patch(
        stage2,
        {
            "keep": [],
            "remove": [
                {"region_id": "wrong_wrapper_a", "reason": "false parent"},
                {"region_id": "wrong_wrapper_b", "reason": "false parent"},
            ],
            "relabel": [],
            "missing": [
                {
                    "description": "recover the coherent child region",
                    "parent_region_id": "primary_region",
                    "expected_role": "list_container",
                    "rough_roi": {"x": 610, "y": 60, "w": 250, "h": 220},
                    "repair_route": "stage1_repartition",
                    "reason": "removed wrappers fragmented one semantic region",
                }
            ],
            "needs_human_review": [],
        },
    )
    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/frozen.png")

    contract = compile_generic_repair_requests(stage2, patch, handoff)

    assert contract["contract_version"] == "learning_generic_repair_requests_v1"
    assert contract["request_count"] == 1
    request = contract["requests"][0]
    assert request["source_removed_region_ids"] == ["wrong_wrapper_a", "wrong_wrapper_b"]
    assert request["source_child_item_ids"] == ["item_a", "item_b", "item_c"]
    assert request["parent_region_id"] == "primary_region"
    assert request["completion_contract"] == {
        "all_source_children_preserved": True,
        "replacement_inside_parent": True,
        "replacement_geometry_requires_evidence": True,
        "rough_roi_is_not_final_geometry": True,
        "no_duplicate_replacement_ids": True,
    }
    serialized = str(contract).lower()
    assert "application_name" not in serialized
    assert "fixed_coordinate" not in serialized
    assert contract["safety"]["real_clicks"] == 0


def test_candidate_missing_region_preserves_atomic_evidence_for_deterministic_repair() -> None:
    stage2 = _stage2()
    patch = validate_review_patch(
        stage2,
        {
            "keep": [],
            "remove": [],
            "relabel": [],
            "missing": [
                {
                    "description": "uncovered event list",
                    "parent_region_id": "primary_region",
                    "expected_role": "list_container",
                    "rough_roi": {"x": 620, "y": 60, "w": 250, "h": 220},
                    "repair_route": "stage1_repartition",
                    "reason": "accepted program-owned missing candidate",
                    "candidate_id": "M04",
                    "candidate_member_item_ids": ["item_a", "item_b", "item_c"],
                    "geometry_source": "uncovered_atomic_evidence_cluster_v2",
                }
            ],
            "needs_human_review": [],
        },
    )

    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/frozen.png")
    contract = compile_generic_repair_requests(stage2, patch, handoff)
    results = execute_deterministic_repairs(stage2, contract)

    assert handoff["stage1_repair_requests"][0]["candidate_member_item_ids"] == [
        "item_a",
        "item_b",
        "item_c",
    ]
    assert contract["requests"][0]["source_removed_region_ids"] == []
    assert contract["requests"][0]["source_child_item_ids"] == ["item_a", "item_b", "item_c"]
    repair = results["results"][0]
    assert repair["status"] == "passed"
    assert repair["replacement_regions"][0]["bbox"] == {"x": 650, "y": 80, "w": 180, "h": 140}
    assert repair["evidence"]["rough_roi_used_as_final_geometry"] is False


def test_candidate_repair_does_not_inherit_overlapping_removed_wrapper_members() -> None:
    stage2 = _stage2()
    patch = validate_review_patch(
        stage2,
        {
            "keep": [{"region_id": "wrong_wrapper_b", "reason": "unrelated surviving wrapper"}],
            "remove": [{"region_id": "wrong_wrapper_a", "reason": "overmerged wrapper"}],
            "relabel": [],
            "missing": [
                {
                    "description": "independent section heading",
                    "parent_region_id": "primary_region",
                    "expected_role": "list_item",
                    "rough_roi": {"x": 650, "y": 80, "w": 180, "h": 40},
                    "repair_route": "precise_locator",
                    "reason": "accepted uncovered atomic candidate",
                    "candidate_id": "M11",
                    "candidate_member_item_ids": ["item_a"],
                    "geometry_source": "uncovered_atomic_evidence_cluster_v2",
                }
            ],
            "needs_human_review": [],
        },
    )

    handoff = build_missing_locator_tasks(stage2, patch, "D:/screens/frozen.png")
    contract = compile_generic_repair_requests(stage2, patch, handoff)

    request = contract["requests"][0]
    assert request["source_candidate_id"] == "M11"
    assert request["source_removed_region_ids"] == []
    assert request["source_child_item_ids"] == ["item_a"]
