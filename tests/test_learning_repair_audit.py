from __future__ import annotations

from app.learn.recognition.repair_audit import (
    audit_stage2_repair_readiness,
    summarize_nine_interface_repair_audits,
)


def _stage2() -> dict:
    return {
        "regions": [
            {
                "region_id": "primary",
                "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                "numbered_items": [
                    {"item_id": "a", "bbox": {"x": 20, "y": 20, "w": 100, "h": 40}},
                    {"item_id": "b", "bbox": {"x": 20, "y": 70, "w": 100, "h": 40}},
                ],
                "subregion_groups": [
                    {
                        "group_id": "eligible",
                        "role": "list_container",
                        "bbox": {"x": 10, "y": 10, "w": 130, "h": 120},
                        "member_item_ids": ["a", "b"],
                    },
                    {
                        "group_id": "missing_child",
                        "role": "card",
                        "bbox": {"x": 150, "y": 10, "w": 130, "h": 120},
                        "member_item_ids": ["missing"],
                    },
                    {
                        "group_id": "no_children",
                        "role": "card",
                        "bbox": {"x": 290, "y": 10, "w": 130, "h": 120},
                        "member_item_ids": [],
                    },
                ],
            }
        ]
    }


def test_audit_separates_repairable_wrappers_from_missing_evidence() -> None:
    audit = audit_stage2_repair_readiness(_stage2())

    assert audit["group_count"] == 3
    assert audit["deterministic_repair_eligible"] == 1
    assert audit["requires_model_or_human_review"] == 2
    assert audit["missing_atomic_evidence_group_ids"] == ["missing_child", "no_children"]
    assert audit["false_card_classification"] == "not_evaluated_without_model_review"


def test_summary_keeps_model_review_not_covered_and_emits_only_generic_rules() -> None:
    case_a = {"case_id": "case_a", "structure_signature": "left_nav+main_content", **audit_stage2_repair_readiness(_stage2())}
    case_b = {"case_id": "case_b", "structure_signature": "top_bar+main_content", **audit_stage2_repair_readiness(_stage2())}

    summary = summarize_nine_interface_repair_audits([case_a, case_b])

    assert summary["attempted"] == 2
    assert summary["structure_family_count"] == 2
    assert summary["model_review_coverage"] == {"attempted": 0, "rate": "not_covered"}
    assert "final_bbox_from_atomic_union_and_parent_clip" in summary["general_rules"]
    assert "missing_atomic_evidence_blocks_auto_repair" in summary["general_rules"]
    assert summary["interpretation"].startswith("Cross-interface repair-readiness audit")

