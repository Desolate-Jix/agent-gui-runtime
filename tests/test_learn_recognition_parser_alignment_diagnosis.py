from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_parser_alignment_diagnosis import run_parser_alignment_diagnosis


def test_parser_alignment_diagnosis_reports_bbox_miss(tmp_path: Path) -> None:
    actual_output = tmp_path / "actual_parser_output_v1.json"
    actual_output.write_text(
        json.dumps(
            {
                "screen_inventory": [
                    {
                        "item_id": "vision_search",
                        "label": "Job search input field",
                        "role": "input",
                        "bbox": {"x": 100, "y": 100, "w": 200, "h": 40},
                        "source_evidence": ["vision"],
                    },
                    {
                        "item_id": "vision_button",
                        "label": "SEEK button",
                        "role": "button",
                        "bbox": {"x": 420, "y": 100, "w": 80, "h": 40},
                        "source_evidence": ["vision"],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch_report = tmp_path / "batch.json"
    batch_report.write_text(
        json.dumps(
            {
                "case_results": [
                    {
                        "case_id": "seek_case",
                        "actual_parser_output_path": str(actual_output),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_manifest = tmp_path / "manifest.json"
    support_manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "seek_support",
                        "observe_bundle": {
                            "sources": {
                                "uia": {
                                    "controls": [
                                        {
                                            "name": "Search keyword field",
                                            "control_type": "Edit",
                                            "bbox": {"x": 110, "y": 105, "w": 180, "h": 35},
                                            "patterns": ["Value"],
                                        },
                                        {
                                            "name": "SEEK button",
                                            "control_type": "Button",
                                            "bbox": {"x": 700, "y": 100, "w": 80, "h": 40},
                                            "patterns": ["Invoke"],
                                        },
                                    ]
                                }
                            }
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_parser_alignment_diagnosis(
        batch_report_path=batch_report,
        support_manifest_path=support_manifest,
        support_case_id="seek_support",
        out_dir=tmp_path / "out",
        case_id_contains="seek_",
    )

    assert report["metrics"]["parser_bbox_alignment"] == {"passed": 1, "attempted": 2, "rate": 0.5}
    assert report["case_id_contains"] == "seek_"
    assert report["failure_categories"] == {"model_bbox_not_overlapping_reference": 1}
    assert report["actionability_diagnosis"]["status"] == "blocked_by_parser_bbox_alignment"
    assert report["actionability_diagnosis"]["failed_alignment_count"] == 1
    assert report["actionability_diagnosis"]["root_cause"] == "actual parser bbox does not overlap reference interactive controls"
    assert report["actionability_diagnosis"]["fix_location"] == "learn_recognition_parser_or_cross_evidence_adapter"
    assert report["actionability_diagnosis"]["recommended_intervention"] == (
        "fix parser coordinate/bbox alignment or attach same-screenshot UIA/OmniParser/calibrated target support before ROI grounding"
    )
    assert report["case_results"][0]["support_results"][0]["status"] == "passed"
    assert report["case_results"][0]["support_results"][1]["status"] == "failed"
    assert report["case_results"][0]["support_results"][1]["failure_category"] == "model_bbox_not_overlapping_reference"
    assert report["case_results"][0]["support_results"][1]["center_delta_px"] == {"dx": -280.0, "dy": 0.0}
    assert Path(report["report_path"]).exists()
