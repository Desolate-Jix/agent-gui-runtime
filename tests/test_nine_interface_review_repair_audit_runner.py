from __future__ import annotations

import json
from pathlib import Path

from scripts.run_nine_interface_review_repair_audit import run_audit


def test_runner_audits_saved_stage2_reports_without_claiming_model_review(tmp_path: Path) -> None:
    case_reports: list[dict] = []
    for index, zones in enumerate((["left_nav", "main_content"], ["top_bar", "main_content"]), start=1):
        full_report_path = tmp_path / f"full_{index}.json"
        full_report_path.write_text(
            json.dumps(
                {
                    "stage1_structure": {
                        "structure_regions": [{"zone_id": zone} for zone in zones]
                    },
                    "stage2_numbering": {
                        "regions": [
                            {
                                "region_id": "primary",
                                "bbox": {"x": 0, "y": 0, "w": 400, "h": 300},
                                "numbered_items": [
                                    {"item_id": "item", "bbox": {"x": 20, "y": 20, "w": 80, "h": 30}}
                                ],
                                "subregion_groups": [
                                    {
                                        "group_id": "wrapper",
                                        "role": "list_container",
                                        "bbox": {"x": 10, "y": 10, "w": 100, "h": 50},
                                        "member_item_ids": ["item"],
                                    }
                                ],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        case_reports.append(
            {
                "case_id": f"case_{index}",
                "app_family": f"family_{index}",
                "full_report_path": str(full_report_path),
            }
        )
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps({"cases": case_reports}), encoding="utf-8")

    report = run_audit(benchmark_path, tmp_path / "out.json")

    assert report["summary"]["attempted"] == 2
    assert report["summary"]["structure_family_count"] == 2
    assert report["summary"]["model_review_coverage"]["rate"] == "not_covered"
    assert report["cases"][0]["deterministic_repair_eligible"] == 1
    assert report["safety"]["real_clicks"] == 0

