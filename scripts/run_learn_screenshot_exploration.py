from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.two_stage import (
    build_two_stage_screen_understanding,
    model_grounding_evidence_status_from_two_stage,
)


def _resolve(path: str | Path, root: Path = ROOT) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _relative(path: str | Path | None, root: Path = ROOT) -> str:
    if not path:
        return ""
    candidate = Path(str(path))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(candidate)


def run_screenshot_exploration(
    *,
    image_path: str | Path,
    require_stage1_gate: bool = True,
    stage2_region_strategy: str = "partitioned",
    root: Path = ROOT,
) -> dict[str, Any]:
    source = _resolve(image_path, root)
    if not source.exists():
        raise FileNotFoundError(f"source screenshot does not exist: {source}")
    with Image.open(source) as image:
        width, height = image.size
    bundle = {
        "image_path": str(source),
        "source_image_path": str(source),
        "screen_size": {"width": width, "height": height},
        "image_size": {"width": width, "height": height},
        "source_type": "screenshot_only",
        "trace_available": False,
    }
    screen_inventory: list[dict[str, Any]] = []
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=bundle["screen_size"])
    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
        enable_ocr_content_recovery=True,
        require_stage1_gate=require_stage1_gate,
        stage2_region_strategy=stage2_region_strategy,
    )
    report["source_provenance"] = {
        "contract_version": "learn_screenshot_only_exploration_source_v1",
        "source_type": "screenshot_only",
        "trace_available": False,
        "ocr_uia_inventory_available": False,
        "source_image_path": _relative(source, root),
        "interpretation": (
            "Screenshot-only exploration can reveal visual layout behavior, but it is not a full "
            "Learning Mode run and must not be promoted as model grounding, Execute readiness, "
            "or Runtime PathGraph evidence."
        ),
    }
    report["model_grounding_evidence"] = model_grounding_evidence_status_from_two_stage(report)
    report["model_grounding_evidence"]["model_accuracy_claim_allowed"] = False
    report["model_grounding_evidence"]["interpretation"] = (
        "Screenshot-only exploration is not model accuracy, model grounding, or full learning-flow evidence."
    )
    report["exploration_status"] = _screenshot_exploration_status(report)
    report["safety"] = {
        "live_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "execute_binding_enabled": False,
        "runtime_pathgraph_promotion": False,
    }
    return report


def _screenshot_exploration_status(report: dict[str, Any]) -> dict[str, Any]:
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    numbered = int(stage2.get("numbered_item_count") or 0)
    fused = int(fusion.get("fused_review_box_count") or 0)
    if fused > 0:
        status = "review_boxes_available"
        demo_readiness = "candidate_for_visual_review"
        reason = "fused_review_boxes_present"
    elif numbered > 0:
        status = "numbered_without_fusion"
        demo_readiness = "needs_fusion_review"
        reason = "numbered_items_present_but_no_fused_review_boxes"
    else:
        status = "no_review_boxes"
        demo_readiness = "not_demo_ready"
        reason = "screenshot_only_without_ocr_uia_inventory_or_model_boxes"
    return {
        "contract_version": "learn_screenshot_exploration_status_v1",
        "status": status,
        "demo_readiness": demo_readiness,
        "numbered_item_count": numbered,
        "fused_review_box_count": fused,
        "reason": reason,
        "interpretation": (
            "A successful command only means the safe screenshot-only pipeline ran. "
            "Demo readiness requires visible review boxes and still remains display-only."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run screenshot-only Learning Mode exploration.")
    parser.add_argument("--image", required=True, help="Source screenshot path.")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--allow-stage2-with-failed-stage1", action="store_true")
    parser.add_argument("--stage2-region-strategy", default="partitioned")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    out_dir = _resolve(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_screenshot_exploration(
        image_path=args.image,
        require_stage1_gate=not args.allow_stage2_with_failed_stage1,
        stage2_region_strategy=args.stage2_region_strategy,
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"learn_screenshot_exploration_report_{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "success": True,
        "report_path": _relative(report_path),
        "overlay_path": _relative(report.get("fusion", {}).get("compiled_overlay_path")),
        "stage1_gate": report.get("stage1_gate", {}).get("status"),
        "stage2_numbering_skipped": report.get("stage2_numbering_skipped"),
        "numbered": report.get("stage2_numbering", {}).get("numbered_item_count"),
        "fused": report.get("fusion", {}).get("fused_review_box_count"),
        "exploration_status": report.get("exploration_status", {}).get("status"),
        "demo_readiness": report.get("exploration_status", {}).get("demo_readiness"),
        "source_type": "screenshot_only",
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"wrote {summary['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
