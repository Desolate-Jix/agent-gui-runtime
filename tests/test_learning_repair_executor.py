from __future__ import annotations

from app.learn.recognition.repair_executor import execute_deterministic_repair


def _stage2() -> dict:
    return {
        "regions": [
            {
                "region_id": "primary_region",
                "bbox": {"x": 100, "y": 50, "w": 800, "h": 700},
                "numbered_items": [
                    {"item_id": "item_a", "bbox": {"x": 650, "y": 80, "w": 180, "h": 40}},
                    {"item_id": "item_b", "bbox": {"x": 650, "y": 130, "w": 180, "h": 40}},
                    {"item_id": "item_c", "bbox": {"x": 650, "y": 180, "w": 180, "h": 40}},
                ],
                "subregion_groups": [],
            }
        ]
    }


def _request(*, child_ids: list[str]) -> dict:
    return {
        "repair_request_id": "repair_1",
        "repair_route": "stage1_repartition",
        "parent_region_id": "primary_region",
        "source_removed_region_ids": ["wrong_wrapper_a", "wrong_wrapper_b"],
        "source_child_item_ids": child_ids,
        "rough_roi": {"x": 610, "y": 60, "w": 250, "h": 220},
        "expected_role": "list_container",
        "description": "recover coherent child region",
    }


def test_executor_builds_final_geometry_from_atomic_child_evidence() -> None:
    result = execute_deterministic_repair(_stage2(), _request(child_ids=["item_a", "item_b", "item_c"]))

    assert result["status"] == "passed"
    assert result["geometry_source"] == "deterministic_atomic_evidence_union_v1"
    replacement = result["replacement_regions"][0]
    assert replacement["bbox"] == {"x": 650, "y": 80, "w": 180, "h": 140}
    assert replacement["member_item_ids"] == ["item_a", "item_b", "item_c"]
    assert replacement["bbox"] != _request(child_ids=[])["rough_roi"]
    assert result["evidence"]["atomic_union_bbox"] == replacement["bbox"]
    assert result["evidence"]["model_rough_roi"] == _request(child_ids=[])["rough_roi"]
    assert result["evidence"]["atomic_union_equals_rough_roi"] is False
    assert result["safety"]["real_clicks"] == 0


def test_executor_rejects_request_without_complete_atomic_evidence() -> None:
    result = execute_deterministic_repair(_stage2(), _request(child_ids=["item_a", "missing_item"]))

    assert result["status"] == "failed"
    assert result["failure_category"] == "atomic_evidence_missing"
    assert result["missing_child_item_ids"] == ["missing_item"]
    assert result["replacement_regions"] == []
