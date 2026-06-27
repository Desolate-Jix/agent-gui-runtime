from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw

from app.learn.visual_asset_calibration import calibrate_interface_map_visual_assets


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "visual_asset_local_smoke.py"
spec = importlib.util.spec_from_file_location("visual_asset_local_smoke", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
visual_asset_local_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(visual_asset_local_smoke)


def test_visual_asset_local_smoke_reports_low_risk_fast_lane_and_high_risk_block(tmp_path) -> None:
    out_dir = tmp_path / "visual-smoke"

    exit_code = visual_asset_local_smoke.main(["--out-dir", str(out_dir)])

    assert exit_code == 0
    summary = json.loads((out_dir / "visual_asset_local_smoke_summary.json").read_text(encoding="utf-8"))
    report = summary["calibration_report"]
    assert report["contract_version"] == "visual_asset_calibration_report_v1"
    assert report["status"] == "pass"
    assert report["quick_apply"]["matched"] is True
    assert report["quick_apply"]["fast_lane_allowed"] is True
    assert report["quick_apply"]["elapsed_ms"] < 1000
    assert report["submit_application"]["matched"] is True
    assert report["submit_application"]["risk_class"] == "potential_side_effect_action"
    assert report["submit_application"]["fast_lane_allowed"] is False
    assert report["submit_application"]["requires_review"] is True
    assert report["final_submit_fast_lane_count"] == 0
    assert report["final_submissions"] == 0

    interface_map = json.loads((out_dir / "learned_interface_map.json").read_text(encoding="utf-8"))
    submit_asset = next(asset for asset in interface_map["fixed_visual_assets"] if asset["asset_id"] == "seek:visual:submit_application_button")
    assert submit_asset["is_high_risk"] is True
    assert submit_asset["semantic_action"] == "final_submit"
    assert submit_asset["can_authorize_click"] is False
    assert submit_asset["last_match_evidence"]["artifact_is_authorization"] is False
    assert interface_map["summary"]["danger_zone_count"] == 1


def test_visual_asset_calibration_blocks_ambiguous_low_risk_fast_lane(tmp_path) -> None:
    target = tmp_path / "duplicate-buttons.png"
    image = Image.new("RGB", (500, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 60, 230, 110), radius=8, fill=(230, 0, 125))
    draw.rounded_rectangle((80, 150, 230, 200), radius=8, fill=(230, 0, 125))
    image.save(target)
    template = tmp_path / "quick-apply-template.png"
    image.crop((80, 60, 230, 110)).save(template)
    interface_map = {
        "contract_version": "learned_interface_map_v1",
        "fixed_visual_assets": [
            {
                "asset_id": "seek:visual:quick_apply_button",
                "label": "Quick apply",
                "semantic_action": "open_apply_flow",
                "danger_level": "low",
                "can_authorize_click": False,
                "requires_gate": True,
                "allowed_region_ids": ["job_detail"],
                "template_refs": {"tight_crop_ref": str(template)},
                "source_geometry": {"bbox": {"x": 80, "y": 60, "w": 150, "h": 50}},
            }
        ],
    }

    report = calibrate_interface_map_visual_assets(
        interface_map,
        target_image_path=target,
        artifact_dir=tmp_path / "matches",
        allowed_regions_by_id={"job_detail": {"x": 40, "y": 20, "w": 240, "h": 220, "container_id": "seek:job_detail"}},
        capture_id="duplicate-button-capture",
        viewport_size={"width": 500, "height": 260},
        min_score_gap=0.05,
    )

    match = report["matches"][0]
    assert match["threshold_ok"] is True
    assert match["score_gap_ok"] is False
    assert match["ambiguous"] is True
    assert match["calibration"]["fast_lane_allowed"] is False
    assert report["summary"]["fast_lane_success_count"] == 0
