from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "visual_asset_calibration_report.py"
SMOKE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "visual_asset_local_smoke.py"


def _load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


visual_asset_calibration_report = _load_script(SCRIPT_PATH, "visual_asset_calibration_report")
visual_asset_local_smoke = _load_script(SMOKE_PATH, "visual_asset_local_smoke_for_calibration_report")


def test_visual_asset_calibration_report_cli_updates_interface_map(tmp_path) -> None:
    smoke_dir = tmp_path / "smoke"
    assert visual_asset_local_smoke.main(["--out-dir", str(smoke_dir)]) == 0
    report_path = tmp_path / "calibration" / "visual_asset_calibration_report.json"
    updated_map_path = tmp_path / "calibration" / "updated_interface_map.json"

    exit_code = visual_asset_calibration_report.main(
        [
            "--interface-map",
            str(smoke_dir / "learned_interface_map.json"),
            "--target-image",
            str(smoke_dir / "seek_detail_local_screenshot.png"),
            "--out",
            str(report_path),
            "--updated-interface-map-out",
            str(updated_map_path),
            "--artifact-dir",
            str(tmp_path / "calibration" / "matches"),
            "--capture-id",
            "calibration-report-test-capture",
            "--viewport-width",
            "1000",
            "--viewport-height",
            "760",
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    updated_map = json.loads(updated_map_path.read_text(encoding="utf-8"))
    assert report["contract_version"] == "visual_asset_calibration_report_v1"
    assert report["summary"]["status"] == "pass"
    assert report["summary"]["final_submit_fast_lane_count"] == 0
    assert report["summary"]["final_submissions"] == 0
    quick_apply = next(match for match in report["matches"] if match["asset_id"] == "seek:visual:quick_apply_button")
    submit = next(match for match in report["matches"] if match["asset_id"] == "seek:visual:submit_application_button")
    assert quick_apply["matched"] is True
    assert quick_apply["calibration"]["fast_lane_allowed"] is True
    assert submit["matched"] is True
    assert submit["calibration"]["is_high_risk"] is True
    assert submit["calibration"]["fast_lane_allowed"] is False
    updated_submit = next(asset for asset in updated_map["fixed_visual_assets"] if asset["asset_id"] == "seek:visual:submit_application_button")
    assert updated_submit["can_authorize_click"] is False
    assert updated_submit["fast_lane_allowed"] is False
