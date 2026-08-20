from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.learn.interface_map import build_learned_interface_map, merge_visual_asset_match_evidence
from app.learn.path_graph_artifacts import build_seek_runtime_path_graph_export
from app.learn.visual_asset_calibration import calibrate_interface_map_visual_assets
from app.learn.visual_asset_crops import build_visual_asset_crop_export
from app.seek.learn_artifacts import build_seek_learn_artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a local screenshot-only visual asset learning smoke.")
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/visual-match-smoke/local_seek_buttons"))
    args = parser.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    source_image = args.out_dir / "seek_detail_local_screenshot.png"
    image = Image.new("RGB", (1000, 760), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 130, 410, 520), fill=(244, 247, 252), outline=(30, 64, 175), width=4)
    draw.rectangle((460, 80, 950, 690), fill=(250, 250, 250), outline=(210, 215, 225), width=2)
    draw.rounded_rectangle((640, 160, 810, 216), radius=10, fill=(230, 0, 125))
    draw.rounded_rectangle((640, 238, 810, 294), radius=10, fill=(230, 0, 125))
    draw.rounded_rectangle((650, 620, 870, 680), radius=10, fill=(25, 25, 25))
    image.save(source_image)

    seek_artifact = build_seek_learn_artifacts(_report(), trace=_trace())
    runtime_export = build_seek_runtime_path_graph_export(seek_artifact)
    crop_export = build_visual_asset_crop_export(
        runtime_export["runtime_path_graph"],
        runtime_export["visual_assets"],
        source_image_path=source_image,
        output_dir=args.out_dir / "crops",
    )
    submit_crop = args.out_dir / "crops" / "seek_visual_submit_application_button.png"
    submit_crop.parent.mkdir(parents=True, exist_ok=True)
    Image.open(source_image).crop((650, 620, 870, 680)).save(submit_crop)
    crop_export["visual_assets"]["assets"].append(
        {
            "asset_id": "seek:visual:submit_application_button",
            "label": "Submit application",
            "role": "button",
            "region_id": "application_form",
            "semantic_action": "final_submit",
            "danger_level": "final_submit",
            "can_authorize_click": False,
            "requires_gate": True,
            "source": {
                "crop_path": str(submit_crop),
                "source_image_path": str(source_image),
                "bbox": {"x": 650, "y": 620, "w": 220, "h": 60},
                "click_point": {"x": 760, "y": 650},
                "crop_status": "ok",
            },
            "scope": {
                "allowed_region_ids": ["application_form"],
                "expected_text": ["Submit application"],
                "negative_text": ["Quick apply", "Apply"],
            },
            "match_policy": {"minimum_similarity": 0.82, "requires_region_match": True},
        }
    )
    crop_export["summary"]["asset_count"] = len(crop_export["visual_assets"]["assets"])
    crop_export["summary"]["crop_count"] = int(crop_export["summary"].get("crop_count") or 0) + 1
    interface_map = build_learned_interface_map(runtime_export["runtime_path_graph"], crop_export["visual_assets"])
    assets = {item["asset_id"]: item for item in crop_export["visual_assets"]["assets"] if isinstance(item, dict)}
    quick_apply = assets["seek:visual:quick_apply_button"]
    calibration = calibrate_interface_map_visual_assets(
        interface_map,
        target_image_path=source_image,
        artifact_dir=args.out_dir / "matches",
        capture_id="local_visual_asset_smoke_capture",
        viewport_size={"width": 1000, "height": 760},
        allowed_regions_by_id={
            "job_detail": {"x": 600, "y": 130, "w": 250, "h": 96, "container_id": "seek:job_detail"},
            "application_form": {"x": 560, "y": 560, "w": 360, "h": 150, "container_id": "seek:application_form"},
        },
    )
    interface_map = calibration["updated_interface_map"]
    match = next(item for item in calibration["matches"] if item.get("asset_id") == quick_apply["asset_id"])
    submit_match = next(item for item in calibration["matches"] if item.get("asset_id") == "seek:visual:submit_application_button")
    interface_map_path = args.out_dir / "learned_interface_map.json"
    interface_map_path.write_text(json.dumps(interface_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    calibration_report = calibration["summary"]
    calibration_report["contract_version"] = calibration["contract_version"]
    calibration_report["quick_apply"] = {
        "matched": bool(match.get("matched")),
        "risk_class": (match.get("candidate") or {}).get("risk_class"),
        "fast_lane_allowed": bool(match.get("calibration", {}).get("fast_lane_allowed")),
        "elapsed_ms": match.get("elapsed_ms"),
    }
    calibration_report["submit_application"] = {
        "matched": bool(submit_match.get("matched")),
        "risk_class": (submit_match.get("candidate") or {}).get("risk_class"),
        "fast_lane_allowed": bool(submit_match.get("calibration", {}).get("fast_lane_allowed")),
        "requires_review": bool(submit_match.get("calibration", {}).get("requires_review")),
        "elapsed_ms": submit_match.get("elapsed_ms"),
    }
    summary = {
        "contract_version": "visual_asset_local_smoke_v1",
        "source_image": str(source_image),
        "interface_map_path": str(interface_map_path),
        "interface_map_summary": interface_map["summary"],
        "crop_export_summary": crop_export["summary"],
        "quick_apply_crop": quick_apply["source"]["crop_path"],
        "submit_application_crop": str(submit_crop),
        "match": {
            "matched": match["matched"],
            "elapsed_ms": match["elapsed_ms"],
            "match_score": match["match_score"],
            "score_gap_to_second": match["score_gap_to_second"],
            "risk_class": match["candidate"]["risk_class"],
            "bbox": match["bbox"],
            "click_point": match["click_point"],
            "current_roi_ref": match["current_roi_ref"],
            "current_match_ref": match["current_match_ref"],
            "candidate_freshness": match["candidate"]["candidate_freshness"],
        },
        "submit_match": {
            "matched": submit_match["matched"],
            "elapsed_ms": submit_match["elapsed_ms"],
            "match_score": submit_match["match_score"],
            "score_gap_to_second": submit_match["score_gap_to_second"],
            "risk_class": submit_match["candidate"]["risk_class"],
            "bbox": submit_match["bbox"],
            "click_point": submit_match["click_point"],
            "current_roi_ref": submit_match["current_roi_ref"],
            "current_match_ref": submit_match["current_match_ref"],
            "candidate_freshness": submit_match["candidate"]["candidate_freshness"],
            "fast_lane_allowed": False,
            "requires_review": True,
        },
        "calibration_report": calibration_report,
        "artifact_is_authorization": False,
    }
    summary_path = args.out_dir / "visual_asset_local_smoke_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"success": bool(match["matched"]), "summary_path": str(summary_path), **summary["match"]}, ensure_ascii=False))
    return 0 if calibration_report["status"] == "pass" else 1


def _report() -> dict[str, Any]:
    event = _event()
    accuracy = {
        "contract_version": "seek_mvp_accuracy_summary_v1",
        "jobs_seen": 1,
        "jobs_opened": 1,
        "jobs_fully_read": 1,
        "post_click_layout_drift_count": 0,
        "wrong_scope_scroll_count": 0,
        "status": "pass",
    }
    return {
        "contract_version": "seek_mvp_run_report_v1",
        "mode": "local_visual_asset_smoke",
        "source_url": "local://seek-visual-asset-smoke",
        "jobs_seen": 1,
        "jobs_opened": 1,
        "jobs_fully_read": 1,
        "submit_clicks": 0,
        "final_submissions": 0,
        "accuracy_summary": accuracy,
        "traversal_steps": [event],
    }


def _trace() -> dict[str, Any]:
    return {
        "contract_version": "seek_mvp_traversal_trace_v1",
        "mode": "local_visual_asset_smoke",
        "traversal_events": [_event()],
        "safety": {"submit_clicks": 0, "final_submissions": 0},
    }


def _event() -> dict[str, Any]:
    return {
        "index": 0,
        "job_id": "local-job",
        "card": {
            "title": "Graduate Software Engineer",
            "company": "Example",
            "location": "Auckland",
            "card_bbox": {"x": 30, "y": 130, "w": 380, "h": 390},
            "click_point": {"x": 220, "y": 320},
        },
        "card_click": {"opened": True, "failure_reason": None},
        "detail_read": {
            "title": "Graduate Software Engineer",
            "company": "Example",
            "complete": True,
            "scrolls": [{"target_container_id": "seek:job_detail", "target_pane": "job_detail"}],
            "apply_button_state": {
                "visible": True,
                "label": "Quick apply",
                "bbox": {"x": 640, "y": 160, "w": 170, "h": 56},
                "click_point": {"x": 725, "y": 188},
                "candidate_freshness": {"source": "local_visual_asset_smoke"},
            },
        },
        "match_decision": {"decision": "strong_apply", "score": 0.9},
    }


if __name__ == "__main__":
    raise SystemExit(main())
