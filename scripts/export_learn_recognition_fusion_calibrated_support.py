from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.create_learn_recognition_calibrated_support import create_calibrated_support


def export_targets_from_fusion_report(
    *,
    report_path: str | Path,
    out_path: str | Path,
    source_tracking: str = "assisted_generation",
) -> dict[str, Any]:
    report_path = Path(report_path)
    out_path = Path(out_path)
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    fusion = report.get("fused_precise_understanding") if isinstance(report.get("fused_precise_understanding"), dict) else {}
    items = fusion.get("items") if isinstance(fusion.get("items"), list) else []
    targets: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target = _target_from_fusion_item(item, source_tracking=source_tracking)
        if target is None:
            rejected.append(_rejected_item(item))
            continue
        targets.append(target)
    payload = {
        "contract_version": "learn_fusion_calibrated_targets_review_only_v1",
        "source_report_path": str(report_path),
        "source_contract": report.get("contract_version"),
        "screenshot_path": str(report.get("screenshot_path") or fusion.get("screenshot_path") or ""),
        "source_tracking": source_tracking,
        "counts_as_model_ability": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "selection_policy": {
            "requires_point_quality": "vista_point_inside_seed_bbox",
            "requires_gate_safety": "passed_allowed_dry_run",
            "requires_real_clicks": 0,
            "excluded_statuses": ["gate_rejected", "failed"],
        },
        "targets": targets,
        "rejected": rejected,
        "interpretation": (
            "Targets exported from learning fusion are same-screenshot review support only. "
            "They are not Execute authorization, not PathGraph promotion, and not model ability evidence."
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "exported",
        "targets_path": str(out_path),
        "eligible_count": len(targets),
        "rejected_count": len(rejected),
        "source_tracking": source_tracking,
        "counts_as_model_ability": False,
    }


def create_support_from_fusion_report(
    *,
    report_path: str | Path,
    out_dir: str | Path,
    app_name: str = "",
    state_hint: str = "",
    source_tracking: str = "assisted_generation",
    json_stdout: bool = False,
) -> dict[str, Any]:
    report_path = Path(report_path)
    out_dir = Path(out_dir)
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    screenshot_path = Path(str(report.get("screenshot_path") or ""))
    if not screenshot_path.exists():
        candidate = report_path.parent / screenshot_path
        if candidate.exists():
            screenshot_path = candidate
    targets_path = out_dir / "fusion_calibrated_targets_review_only.json"
    export_result = export_targets_from_fusion_report(
        report_path=report_path,
        out_path=targets_path,
        source_tracking=source_tracking,
    )
    result = create_calibrated_support(
        screenshot_path=screenshot_path,
        targets_path=targets_path,
        out_dir=out_dir,
        app_name=app_name,
        state_hint=state_hint,
        source_tracking=source_tracking,
        json_stdout=False,
    )
    result["targets_path"] = str(targets_path)
    result["eligible_count"] = export_result["eligible_count"]
    result["rejected_count"] = export_result["rejected_count"]
    result["source_report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _target_from_fusion_item(item: dict[str, Any], *, source_tracking: str) -> dict[str, Any] | None:
    if item.get("point_quality") != "vista_point_inside_seed_bbox":
        return None
    if item.get("gate_safety") != "passed_allowed_dry_run":
        return None
    if int(item.get("real_clicks") or 0) != 0:
        return None
    if item.get("calibration_status") not in {"needs_human_review", "passed"}:
        return None
    bbox = item.get("rough_bbox_hint") if isinstance(item.get("rough_bbox_hint"), dict) else {}
    click_point = item.get("vista_point") if isinstance(item.get("vista_point"), dict) else {}
    if not bbox or not click_point:
        return None
    source_item_id = str(item.get("source_item_id") or "item").strip() or "item"
    region_no = item.get("region_no")
    return {
        "candidate_id": f"fusion_region_{region_no}_{source_item_id}",
        "label": str(item.get("label") or source_item_id),
        "role": str(item.get("role") or "actionable"),
        "bbox": bbox,
        "click_point": click_point,
        "confidence": 0.72 if item.get("calibration_status") == "needs_human_review" else 0.82,
        "source": "learning_fusion_execute_dry_run",
        "coordinate_source": "execute_dry_run_vista_point_with_seed_bbox",
        "source_tracking": source_tracking,
        "counts_as_model_ability": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "evidence": {
            "calibration_status": item.get("calibration_status"),
            "point_quality": item.get("point_quality"),
            "gate_safety": item.get("gate_safety"),
            "trace_path": item.get("trace_path"),
            "recognition_plan_trace_path": item.get("recognition_plan_trace_path"),
            "overlay_path": item.get("overlay_path"),
        },
    }


def _rejected_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "calibration_status": item.get("calibration_status"),
        "point_quality": item.get("point_quality"),
        "gate_safety": item.get("gate_safety"),
        "real_clicks": int(item.get("real_clicks") or 0),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--app-name", default="")
    parser.add_argument("--state-hint", default="")
    parser.add_argument("--source-tracking", default="assisted_generation", choices=["assisted_generation", "mixed"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    create_support_from_fusion_report(
        report_path=args.report,
        out_dir=args.out,
        app_name=args.app_name,
        state_hint=args.state_hint,
        source_tracking=args.source_tracking,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
