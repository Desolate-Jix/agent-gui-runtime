from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.export_learn_recognition_fusion_calibrated_support import (
    create_support_from_fusion_report,
    export_targets_from_fusion_report,
)


def test_export_targets_from_fusion_report_keeps_only_safe_review_candidates(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (300, 200), "white").save(screenshot)
    report = tmp_path / "numbered_region_calibration_report.json"
    report.write_text(
        json.dumps(
            {
                "screenshot_path": str(screenshot),
                "compiled_overlay_path": str(tmp_path / "compiled.png"),
                "fused_precise_understanding": {
                    "items": [
                        {
                            "region_no": 1,
                            "source_item_id": "c1",
                            "label": "Search button",
                            "role": "button",
                            "rough_bbox_hint": {"x": 40, "y": 20, "w": 100, "h": 40},
                            "vista_point": {"x": 80, "y": 35},
                            "selected_click_point": {"x": 90, "y": 38},
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "trace_path": "trace.json",
                            "recognition_plan_trace_path": "plan.json",
                            "overlay_path": "overlay.png",
                            "real_clicks": 0,
                        },
                        {
                            "region_no": 2,
                            "source_item_id": "c2",
                            "label": "Wrong point",
                            "role": "button",
                            "rough_bbox_hint": {"x": 160, "y": 20, "w": 80, "h": 40},
                            "vista_point": {"x": 20, "y": 20},
                            "selected_click_point": {"x": 200, "y": 40},
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_outside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "real_clicks": 0,
                        },
                        {
                            "region_no": 3,
                            "source_item_id": "c3",
                            "label": "Gate rejected",
                            "role": "card",
                            "rough_bbox_hint": {"x": 40, "y": 90, "w": 120, "h": 50},
                            "vista_point": {"x": 60, "y": 100},
                            "selected_click_point": {"x": 60, "y": 100},
                            "calibration_status": "gate_rejected",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_rejected",
                            "real_clicks": 0,
                        },
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = export_targets_from_fusion_report(report_path=report, out_path=tmp_path / "targets.json")

    payload = json.loads(Path(result["targets_path"]).read_text(encoding="utf-8"))
    assert result["eligible_count"] == 1
    assert result["rejected_count"] == 2
    assert payload["contract_version"] == "learn_fusion_calibrated_targets_review_only_v1"
    target = payload["targets"][0]
    assert target["candidate_id"] == "fusion_region_1_c1"
    assert target["bbox"] == {"x": 40, "y": 20, "w": 100, "h": 40}
    assert target["click_point"] == {"x": 80, "y": 35}
    assert target["source_tracking"] == "assisted_generation"
    assert target["coordinate_source"] == "execute_dry_run_vista_point_with_seed_bbox"
    assert target["artifact_is_authorization"] is False
    assert target["execute_binding_enabled"] is False


def test_create_support_from_fusion_report_writes_same_screenshot_support(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (300, 200), "white").save(screenshot)
    report = tmp_path / "numbered_region_calibration_report.json"
    report.write_text(
        json.dumps(
            {
                "screenshot_path": str(screenshot),
                "fused_precise_understanding": {
                    "items": [
                        {
                            "region_no": 1,
                            "source_item_id": "c1",
                            "label": "Search input",
                            "role": "input",
                            "rough_bbox_hint": {"x": 20, "y": 30, "w": 120, "h": 35},
                            "vista_point": {"x": 45, "y": 44},
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "real_clicks": 0,
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = create_support_from_fusion_report(report_path=report, out_dir=tmp_path / "support", app_name="seek")

    support = json.loads(Path(result["support_path"]).read_text(encoding="utf-8"))
    assert support["contract_version"] == "learn_recognition_same_screenshot_support_v1"
    assert support["source_tracking"] == "assisted_generation"
    assert support["counts_as_model_ability"] is False
    target = support["sources"]["calibrated_targets"]["targets"][0]
    assert target["coordinate_validation"]["status"] == "valid"
    assert target["coordinate_source"] == "execute_dry_run_vista_point_with_seed_bbox"
    assert target["source_tracking"] == "assisted_generation"
    assert target["artifact_is_authorization"] is False
    assert target["execute_binding_enabled"] is False
