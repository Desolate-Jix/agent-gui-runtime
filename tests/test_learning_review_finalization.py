from __future__ import annotations

import hashlib
from pathlib import Path

from app.learn.recognition.review_finalization import finalize_reviewed_stage2_for_calibration


def _bbox(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h}


def _stage2() -> dict:
    return {
        "contract_version": "learn_stage2_numbering_v1",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "regions": [
            {
                "region_id": "provisional_region_main",
                "region_no": 1,
                "label": "Main",
                "bbox": _bbox(0, 0, 300, 200),
                "numbered_items": [
                    {
                        "item_id": "atom_a",
                        "number": "1.1",
                        "label": "Alpha",
                        "bbox": _bbox(10, 10, 80, 30),
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    },
                    {
                        "item_id": "atom_b",
                        "number": "1.2",
                        "label": "Beta",
                        "bbox": _bbox(10, 60, 80, 30),
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    },
                ],
                "subregion_groups": [
                    {
                        "group_id": "provisional_group_a",
                        "role": "list_container",
                        "bbox": _bbox(5, 5, 100, 100),
                        "member_item_ids": ["atom_a", "atom_b"],
                        "parent_region_id": "provisional_region_main",
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                ],
            }
        ],
    }


def _finalize(tmp_path: Path, *, source: dict | None = None, final: dict | None = None, **overrides):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fixed-screen")
    checksum = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    return finalize_reviewed_stage2_for_calibration(
        source_stage2=source or _stage2(),
        recomposed_stage2=final or _stage2(),
        screenshot_path=screenshot,
        expected_capture_sha256=overrides.pop("expected_capture_sha256", checksum),
        workflow_state=overrides.pop("workflow_state", "completed_review_only"),
        replacement_integrity_gate=overrides.pop(
            "replacement_integrity_gate",
            {"passed": True, "failure_categories": [], "needs_human_review": 0},
        ),
        repair_pending_count=overrides.pop("repair_pending_count", 0),
        **overrides,
    )


def test_finalization_creates_revision_bound_ids_without_replacing_atomic_identity(tmp_path: Path) -> None:
    result = _finalize(tmp_path)

    assert result["integrity_gate"]["passed"] is True
    assert result["calibration_permission"] is True
    assert result["source_graph_revision"] != result["final_numbering_revision"]
    final_stage2 = result["finalized_stage2"]
    region = final_stage2["regions"][0]
    assert region["region_id"] == "provisional_region_main"
    assert region["final_region_id"].startswith("final-region:")
    assert region["numbered_items"][0]["item_id"] == "atom_a"
    assert region["numbered_items"][0]["final_item_id"].startswith("final-item:")
    assert region["subregion_groups"][0]["final_group_id"].startswith("final-group:")
    assert len(
        {
            item["final_item_id"]
            for item in region["numbered_items"]
        }
    ) == 2
    assert final_stage2["final_numbering"]["source_ids_are_calibration_ids"] is False


def test_finalization_versions_and_preserves_atomic_control_parents(tmp_path: Path) -> None:
    source = _stage2()
    source["regions"][0]["control_parents"] = [
        {
            "object_id": "control_parent_atom_a",
            "label": "Alpha control",
            "role": "atomic_control_parent",
            "bbox": _bbox(5, 5, 100, 42),
            "member_object_ids": ["atom_a"],
            "source": "factual_control_hit_area",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    ]
    final = _stage2()
    final["regions"][0]["control_parents"] = [dict(source["regions"][0]["control_parents"][0])]

    result = _finalize(tmp_path, source=source, final=final)

    assert result["integrity_gate"]["passed"] is True
    parent = result["finalized_stage2"]["regions"][0]["control_parents"][0]
    assert parent["object_id"] == "control_parent_atom_a"
    assert parent["final_control_parent_id"].startswith("final-control:")
    mapping = result["finalized_stage2"]["final_numbering"]["provisional_to_final_id_map"]
    assert mapping["control_parents"]["control_parent_atom_a"] == parent["final_control_parent_id"]
    assert result["finalized_stage2"]["final_numbering"]["control_parent_count"] == 1


def test_finalization_blocks_duplicate_atomic_identity(tmp_path: Path) -> None:
    final = _stage2()
    final["regions"].append(
        {
            "region_id": "other",
            "region_no": 2,
            "label": "Other",
            "bbox": _bbox(300, 0, 100, 100),
            "numbered_items": [
                {"item_id": "atom_a", "number": "2.1", "bbox": _bbox(310, 10, 20, 20)}
            ],
            "subregion_groups": [],
        }
    )

    result = _finalize(tmp_path, final=final)

    assert result["integrity_gate"]["passed"] is False
    assert "duplicate_atomic_identity" in result["integrity_gate"]["failure_categories"]
    assert result["calibration_permission"] is False


def test_finalization_blocks_atom_loss_and_parent_escape(tmp_path: Path) -> None:
    final = _stage2()
    final["regions"][0]["numbered_items"] = [
        {
            "item_id": "atom_a",
            "number": "1.1",
            "label": "Alpha",
            "bbox": _bbox(290, 190, 40, 40),
        }
    ]

    result = _finalize(tmp_path, final=final)

    assert result["integrity_gate"]["passed"] is False
    assert "atomic_identity_set_changed" in result["integrity_gate"]["failure_categories"]
    assert "child_outside_parent" in result["integrity_gate"]["failure_categories"]


def test_finalization_blocks_stale_capture_and_unresolved_review(tmp_path: Path) -> None:
    result = _finalize(
        tmp_path,
        expected_capture_sha256="0" * 64,
        workflow_state="needs_human_review",
        replacement_integrity_gate={
            "passed": False,
            "failure_categories": ["needs_human_review"],
            "needs_human_review": 1,
        },
        repair_pending_count=1,
    )

    assert result["integrity_gate"]["passed"] is False
    assert result["integrity_gate"]["capture_status"] == "stale_capture"
    assert "stale_capture" in result["integrity_gate"]["failure_categories"]
    assert "needs_human_review" in result["integrity_gate"]["failure_categories"]
    assert "repair_pending" in result["integrity_gate"]["failure_categories"]
    assert result["calibration_permission"] is False


def test_finalization_blocks_multiple_leaf_owners_but_allows_nested_parent_group(tmp_path: Path) -> None:
    final = _stage2()
    groups = final["regions"][0]["subregion_groups"]
    groups[0]["group_id"] = "container"
    groups.append(
        {
            "group_id": "leaf_a",
            "parent_group_id": "container",
            "bbox": _bbox(5, 5, 100, 100),
            "member_item_ids": ["atom_a"],
        }
    )
    nested_ok = _finalize(tmp_path, final=final)
    assert nested_ok["integrity_gate"]["passed"] is True

    groups.append(
        {
            "group_id": "leaf_b",
            "parent_group_id": "container",
            "bbox": _bbox(5, 5, 100, 100),
            "member_item_ids": ["atom_a"],
        }
    )
    duplicate_owner = _finalize(tmp_path, final=final)
    assert duplicate_owner["integrity_gate"]["passed"] is False
    assert "multiple_leaf_ownership" in duplicate_owner["integrity_gate"]["failure_categories"]


def test_finalization_allows_removing_display_only_group_without_action_semantic_change(tmp_path: Path) -> None:
    final = _stage2()
    final["regions"][0]["subregion_groups"] = []

    result = _finalize(tmp_path, final=final)

    assert result["integrity_gate"]["passed"] is True
    assert "action_safety_semantics_changed" not in result["integrity_gate"]["failure_categories"]


def test_finalization_blocks_new_execute_authorization_flag(tmp_path: Path) -> None:
    final = _stage2()
    final["regions"][0]["numbered_items"][0]["execute_binding_enabled"] = True

    result = _finalize(tmp_path, final=final)

    assert result["integrity_gate"]["passed"] is False
    assert "unsafe_authorization_flag" in result["integrity_gate"]["failure_categories"]


def test_finalization_ignores_review_decision_action_but_not_runtime_action(tmp_path: Path) -> None:
    reviewed = _stage2()
    reviewed["regions"][0]["subregion_groups"][0]["model_review_decision"] = {
        "action": "keep",
        "reason": "correct display group",
        "display_only": True,
    }
    review_metadata = _finalize(tmp_path, final=reviewed)
    assert review_metadata["integrity_gate"]["passed"] is True

    reviewed["regions"][0]["numbered_items"][0]["action"] = "click"
    runtime_action = _finalize(tmp_path, final=reviewed)
    assert runtime_action["integrity_gate"]["passed"] is False
    assert "action_safety_semantics_changed" in runtime_action["integrity_gate"]["failure_categories"]
