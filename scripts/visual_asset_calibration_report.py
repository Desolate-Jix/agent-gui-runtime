from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.learn.visual_asset_calibration import calibrate_interface_map_visual_assets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate learned Interface Map visual assets against a screenshot.")
    parser.add_argument("--interface-map", required=True, type=Path, help="Path to learned_interface_map_v1 JSON.")
    parser.add_argument("--target-image", required=True, type=Path, help="Current screenshot to match against.")
    parser.add_argument("--out", required=True, type=Path, help="Output visual_asset_calibration_report_v1 JSON.")
    parser.add_argument("--updated-interface-map-out", type=Path, help="Optional output for the updated interface map.")
    parser.add_argument("--artifact-dir", type=Path, help="Directory for current ROI/current match crops.")
    parser.add_argument("--allowed-regions", type=Path, help="Optional JSON object keyed by region id.")
    parser.add_argument("--capture-id", default=None)
    parser.add_argument("--viewport-width", type=int, default=None)
    parser.add_argument("--viewport-height", type=int, default=None)
    parser.add_argument("--min-score-gap", type=float, default=0.05)
    args = parser.parse_args(argv)

    interface_map = _read_json(args.interface_map)
    allowed_regions = _read_json(args.allowed_regions) if args.allowed_regions else None
    viewport_size = None
    if args.viewport_width and args.viewport_height:
        viewport_size = {"width": args.viewport_width, "height": args.viewport_height}
    artifact_dir = args.artifact_dir or (args.out.parent / "visual_asset_calibration_artifacts")
    report = calibrate_interface_map_visual_assets(
        interface_map,
        target_image_path=args.target_image,
        artifact_dir=artifact_dir,
        capture_id=args.capture_id,
        viewport_size=viewport_size,
        allowed_regions_by_id=allowed_regions if isinstance(allowed_regions, dict) else None,
        min_score_gap=args.min_score_gap,
    )
    output = {
        "contract_version": report["contract_version"],
        "interface_map_path": str(args.interface_map),
        "target_image_path": str(args.target_image),
        "artifact_dir": str(artifact_dir),
        "case_count": report["case_count"],
        "summary": report["summary"],
        "matches": report["matches"],
        "artifact_is_authorization": False,
    }
    _write_json(args.out, output)
    if args.updated_interface_map_out:
        _write_json(args.updated_interface_map_out, report["updated_interface_map"])
    print(json.dumps({"success": report["summary"].get("status") == "pass", "out": str(args.out), "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["summary"].get("status") == "pass" else 1


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
