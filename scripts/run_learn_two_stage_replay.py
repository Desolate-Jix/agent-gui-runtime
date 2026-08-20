from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.two_stage import (
    build_two_stage_screen_understanding,
    fusion_status_from_two_stage,
    model_grounding_evidence_status_from_two_stage,
)
from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result as _observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result as _stage1_inventory_from_trace_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run learning-mode two-stage replay from an observe trace.")
    parser.add_argument("--trace", required=True, help="Path to a learn-mode observe trace JSON.")
    parser.add_argument("--out", required=True, help="Output directory for the two-stage report.")
    parser.add_argument(
        "--source-image",
        default="",
        help="Optional explicit screenshot path to use when the trace image is stale or missing.",
    )
    parser.add_argument(
        "--require-stage1-gate",
        action="store_true",
        help="For new interface tests, stop before Stage2 numbering unless Stage1 region selection audit passes.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()

    trace_path = Path(args.trace)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)
    source_image_override = _apply_source_image_override(bundle, args.source_image)
    screen_inventory = _stage1_inventory_from_trace_result(result)
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=bundle.get("screen_size"))

    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
        require_stage1_gate=args.require_stage1_gate,
        enable_ocr_content_recovery=True,
    )
    report["source_trace_path"] = str(trace_path)
    report["observe_bundle"] = bundle
    report["source_image_override"] = source_image_override
    report["source_image_status"] = _source_image_status(bundle.get("image_path"))
    report["screen_inventory_count"] = len(screen_inventory)
    report["layout_graph_summary"] = {
        "node_count": layout_graph.get("node_count"),
        "zone_count": layout_graph.get("zone_count"),
        "zones": {
            zone_id: len(zone.get("item_ids") if isinstance(zone, dict) and isinstance(zone.get("item_ids"), list) else [])
            for zone_id, zone in (layout_graph.get("zones") if isinstance(layout_graph.get("zones"), dict) else {}).items()
        },
    }
    report["fusion_status"] = fusion_status_from_two_stage(report)
    report["model_grounding_evidence"] = model_grounding_evidence_status_from_two_stage(report)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"learn_two_stage_replay_report_{timestamp}.json"

    stage1 = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    overlay_path = str(fusion.get("compiled_overlay_path") or "")
    source_image_status = report.get("source_image_status") if isinstance(report.get("source_image_status"), dict) else {}
    overlay_status = _overlay_status(overlay_path=overlay_path, source_image_status=source_image_status)
    report["overlay_status"] = overlay_status
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "report_path": str(report_path),
        "overlay_path": overlay_path,
        "overlay_status": overlay_status,
        "source_image_status": source_image_status,
        "source_image_override": source_image_override,
        "model_grounding_evidence": report.get("model_grounding_evidence"),
        "screen_inventory_count": len(screen_inventory),
        "stage1_localized_region_count": stage1.get("localized_region_count"),
        "stage1_suppressed_duplicate_region_count": stage1.get("suppressed_duplicate_region_count"),
        "stage2_region_count": stage2.get("region_count"),
        "numbered_item_count": stage2.get("numbered_item_count"),
        "fused_review_box_count": fusion.get("fused_review_box_count"),
        "direct_bar_region_count": report.get("flow_compliance", {}).get("direct_bar_region_count"),
        "center_region_count": report.get("flow_compliance", {}).get("center_region_count"),
        "center_subdivision_region_count": report.get("flow_compliance", {}).get("center_subdivision_region_count"),
        "stage1_gate_status": report.get("stage1_gate", {}).get("status"),
        "stage1_gate_required": report.get("stage1_gate", {}).get("required"),
        "stage2_numbering_skipped": report.get("stage2_numbering_skipped"),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0


def _apply_source_image_override(bundle: dict[str, Any], source_image: str) -> dict[str, Any]:
    override_path = str(source_image or "").strip()
    if not override_path:
        return {"applied": False, "reason": "not_requested"}
    path = Path(override_path)
    if not path.exists():
        return {"applied": False, "reason": "override_missing", "path": override_path}
    original_path = str(bundle.get("image_path") or bundle.get("source_image_path") or "")
    bundle["image_path"] = str(path)
    bundle["source_image_path"] = str(path)
    try:
        from PIL import Image

        with Image.open(path) as image:
            bundle["screen_size"] = {"width": int(image.width), "height": int(image.height)}
            bundle["image_size"] = {"width": int(image.width), "height": int(image.height)}
    except Exception:
        pass
    return {
        "applied": True,
        "reason": "explicit_source_image_override",
        "original_path": original_path,
        "path": str(path),
    }


def _source_image_status(image_path: Any) -> dict[str, Any]:
    path_text = str(image_path or "").strip()
    exists = bool(path_text and Path(path_text).exists())
    return {
        "path": path_text,
        "exists": exists,
        "status": "available" if exists else ("missing_path" if path_text else "not_provided"),
    }


def _overlay_status(*, overlay_path: str, source_image_status: dict[str, Any]) -> dict[str, Any]:
    if overlay_path:
        return {"status": "available", "reason": "", "path": overlay_path}
    if source_image_status.get("exists") is not True:
        return {
            "status": "not_rendered",
            "reason": "source_image_missing",
            "source_image_status": source_image_status,
        }
    return {"status": "not_rendered", "reason": "overlay_renderer_returned_empty", "source_image_status": source_image_status}


if __name__ == "__main__":
    raise SystemExit(main())
