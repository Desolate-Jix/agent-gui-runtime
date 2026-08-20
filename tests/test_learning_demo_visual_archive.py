from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.archive_learning_demo_visual_checkpoint import archive_learning_demo_visual_checkpoint


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_archive_learning_demo_visual_checkpoint_links_visual_and_protected_evidence(tmp_path: Path) -> None:
    contact_sheet = tmp_path / "logs" / "contact.png"
    contact_sheet.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 10), "white").save(contact_sheet)
    visual_report = _write_json(
        tmp_path / "logs" / "visual_report.json",
        {
            "contract_version": "learning_interface_demo_visual_report_v1",
            "summary": {
                "case_count": 2,
                "display_review_ready_count": 1,
                "stress_sample_display_review_count": 1,
                "runtime_pathgraph_ready_count": 0,
            },
            "contact_sheet_path": "logs/contact.png",
            "cases": [
                {
                    "case_id": "applemusic",
                    "quality_status": "display_review_ready",
                    "display_review_ready": True,
                    "visual_artifacts_present": True,
                    "page_detail_preview_path": "logs/apple/page.png",
                    "readonly_pathgraph_preview_path": "logs/apple/path.png",
                    "readonly_pathgraph_diagram_path": "logs/apple/diagram.png",
                },
                {
                    "case_id": "python_org",
                    "quality_status": "stress_sample_display_review",
                    "display_review_ready": False,
                    "visual_artifacts_present": True,
                    "readonly_pathgraph_diagram_path": "logs/python/diagram.png",
                },
            ],
            "safety": {
                "execute_binding_enabled": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
            },
        },
    )
    protected_report = _write_json(
        tmp_path / "logs" / "protected_report.json",
        {
            "contract_version": "learning_protected_set_review_check_v1",
            "summary": {"attempted": 2, "passed": 2, "failed": 0},
            "baseline_comparison": {"status": "pass", "mismatch_count": 0},
            "cases": [
                {"case_id": "applemusic", "passed": True, "structure_quality": {"status": "display_review_candidate"}},
                {"case_id": "python_org", "passed": True, "structure_quality": {"status": "stress_only_needs_review"}},
            ],
        },
    )

    report = archive_learning_demo_visual_checkpoint(
        visual_report_path=visual_report,
        protected_report_path=protected_report,
        out_path=tmp_path / "logs" / "archive.json",
        checkpoint_id="demo_v4",
        project_root=tmp_path,
    )

    assert report["status"] == "pass"
    assert report["summary"]["display_review_ready_count"] == 1
    assert report["summary"]["stress_sample_display_review_count"] == 1
    assert report["summary"]["protected_baseline_status"] == "pass"
    assert report["safety_boundary"]["execute_binding_enabled"] is False
    assert report["cases"][0]["structure_quality_status"] == "display_review_candidate"
    assert report["cases"][1]["structure_quality_status"] == "stress_only_needs_review"
    assert "not recognition accuracy" in report["summary"]["interpretation"]
    assert (tmp_path / "logs" / "archive.json").exists()
