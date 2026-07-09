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
from app.learn.recognition.two_stage import build_two_stage_screen_understanding, fusion_status_from_two_stage
from scripts.run_learn_stage1_region_localization import (
    _observe_bundle_from_trace_result,
    _stage1_inventory_from_trace_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run learning-mode two-stage replay from an observe trace.")
    parser.add_argument("--trace", required=True, help="Path to a learn-mode observe trace JSON.")
    parser.add_argument("--out", required=True, help="Output directory for the two-stage report.")
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
    screen_inventory = _stage1_inventory_from_trace_result(result)
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=bundle.get("screen_size"))

    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
        require_stage1_gate=args.require_stage1_gate,
    )
    report["source_trace_path"] = str(trace_path)
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

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"learn_two_stage_replay_report_{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stage1 = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    summary = {
        "report_path": str(report_path),
        "overlay_path": fusion.get("compiled_overlay_path"),
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


if __name__ == "__main__":
    raise SystemExit(main())
