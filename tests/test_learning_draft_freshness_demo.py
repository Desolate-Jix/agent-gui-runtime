from __future__ import annotations

import json
from pathlib import Path


def test_learning_draft_freshness_demo_generates_three_review_samples(tmp_path: Path) -> None:
    from scripts.create_learning_draft_freshness_demo_fixtures import build_learning_draft_freshness_demo_fixtures

    summary = build_learning_draft_freshness_demo_fixtures(project_root=tmp_path)

    assert summary["contract_version"] == "learning_draft_freshness_demo_fixtures_v1"
    assert [case["case_id"] for case in summary["cases"]] == [
        "freshness_matched",
        "freshness_missing_file",
        "freshness_checksum_mismatch",
    ]
    assert {case["case_id"]: case["freshness_status"] for case in summary["cases"]} == {
        "freshness_matched": "verified",
        "freshness_missing_file": "warning",
        "freshness_checksum_mismatch": "warning",
    }
    assert {case["case_id"]: case["promotion_gate_status"] for case in summary["cases"]} == {
        "freshness_matched": "passed_for_human_promotion_review",
        "freshness_missing_file": "blocked_from_promotion_review",
        "freshness_checksum_mismatch": "blocked_from_promotion_review",
    }
    assert {case["case_id"]: case["promotion_gate_failed_check_ids"] for case in summary["cases"]} == {
        "freshness_matched": [],
        "freshness_missing_file": ["current_screen_freshness"],
        "freshness_checksum_mismatch": ["current_screen_freshness"],
    }

    for case in summary["cases"]:
        reviewed_path = tmp_path / case["reviewed_template_candidate_path"]
        wrapper_path = tmp_path / case["pathgraph_candidate_path"]
        report_path = tmp_path / case["validation_report_path"]
        assert reviewed_path.exists()
        assert wrapper_path.exists()
        assert report_path.exists()

        reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert reviewed["audit"]["source_freshness_summary"]["contract_version"] == "source_freshness_summary_v1"
        assert wrapper["source_freshness_summary"] == reviewed["audit"]["source_freshness_summary"]
        assert report["source_freshness_summary"] == reviewed["audit"]["source_freshness_summary"]
        assert reviewed["execute_binding_enabled"] is False
        assert wrapper["execute_binding_enabled"] is False
        assert report["safety"]["execute_binding_enabled"] is False
        review_payload = json.loads(wrapper_path.read_text(encoding="utf-8"))
        assert review_payload["execute_binding_enabled"] is False

    summary_path = tmp_path / summary["summary_path"]
    assert summary_path.exists()
