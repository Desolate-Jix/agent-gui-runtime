from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
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
from scripts.check_learning_exploration_readiness import DEFAULT_BASELINE
from scripts.check_learning_protected_set_review import (
    _read_json,
    _resolve_project_path,
    compare_learning_protected_archive_node,
    run_learning_protected_set_review,
)
from scripts.report_learning_free_exploration_sources import classify_learning_trace_source
from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result as _observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result as _stage1_inventory_from_trace_result,
)
from scripts.run_learn_two_stage_replay import _overlay_status, _source_image_status


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _protected_comparison(
    *,
    checkpoint_id: str,
    baseline_path: str | Path,
    root: Path,
) -> dict[str, Any]:
    protected_report = run_learning_protected_set_review(checkpoint_id=checkpoint_id, root=root)
    baseline = _read_json(_resolve_project_path(baseline_path, root))
    protected_report["baseline_comparison"] = compare_learning_protected_archive_node(protected_report, baseline)
    summary = protected_report.get("summary") if isinstance(protected_report.get("summary"), dict) else {}
    baseline_comparison = (
        protected_report.get("baseline_comparison")
        if isinstance(protected_report.get("baseline_comparison"), dict)
        else {}
    )
    return {
        "passed": int(summary.get("failed") or 0) == 0 and baseline_comparison.get("status") == "pass",
        "summary": summary,
        "baseline_comparison": baseline_comparison,
        "report": protected_report,
    }


def _two_stage_replay_from_trace(
    *,
    trace_path: Path,
    require_stage1_gate: bool,
) -> dict[str, Any]:
    trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)
    screen_inventory = _stage1_inventory_from_trace_result(result)
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=bundle.get("screen_size"))
    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
        enable_ocr_content_recovery=True,
        require_stage1_gate=require_stage1_gate,
    )
    report["source_trace_path"] = str(trace_path)
    report["observe_bundle"] = bundle
    report["source_image_status"] = _source_image_status(bundle.get("image_path"))
    report["screen_inventory_count"] = len(screen_inventory)
    report["layout_graph_summary"] = {
        "node_count": layout_graph.get("node_count"),
        "zone_count": layout_graph.get("zone_count"),
    }
    report["fusion_status"] = fusion_status_from_two_stage(report)
    report["model_grounding_evidence"] = model_grounding_evidence_status_from_two_stage(report)
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    overlay_path = str(fusion.get("compiled_overlay_path") or "")
    source_image_status = report.get("source_image_status") if isinstance(report.get("source_image_status"), dict) else {}
    report["overlay_status"] = _overlay_status(overlay_path=overlay_path, source_image_status=source_image_status)
    return report


def run_learning_free_exploration_from_trace(
    *,
    trace_path: str | Path,
    out_dir: str | Path,
    baseline_path: str | Path = DEFAULT_BASELINE,
    require_stage1_gate: bool = True,
    root: Path = ROOT,
) -> dict[str, Any]:
    out = _resolve(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    selected_trace = _resolve(trace_path, root)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    classification = classify_learning_trace_source(selected_trace, root=root)
    report: dict[str, Any] = {
        "contract_version": "learning_free_exploration_from_trace_v1",
        "generated_at": _now(),
        "trace_path": _relative(selected_trace, root),
        "baseline_path": _relative(baseline_path, root),
        "intake_classification": classification,
        "status": "not_started",
        "replay_report_path": "",
        "overlay_path": "",
        "protected_before": {},
        "protected_after": {},
        "safety_boundary": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": (
            "Free exploration from a trace is review-only. It requires a non-protected real observe trace "
            "with an existing screenshot and inventory, and it runs protected-set checks before and after replay."
        ),
    }
    if classification.get("candidate_for_free_exploration") is not True:
        report["status"] = "blocked_intake_gate"
        report["blockers"] = classification.get("reasons") if isinstance(classification.get("reasons"), list) else []
        report_path = out / f"learning_free_exploration_from_trace_{timestamp}.json"
        report["report_path"] = _relative(report_path, root)
        _write_json(report_path, report)
        return report

    protected_before = _protected_comparison(
        checkpoint_id=f"free_exploration_before_{timestamp}",
        baseline_path=baseline_path,
        root=root,
    )
    report["protected_before"] = protected_before
    if protected_before.get("passed") is not True:
        report["status"] = "blocked_protected_set_before_replay"
        report["blockers"] = ["protected_set_drift_before_free_exploration"]
        report_path = out / f"learning_free_exploration_from_trace_{timestamp}.json"
        report["report_path"] = _relative(report_path, root)
        _write_json(report_path, report)
        return report

    replay = _two_stage_replay_from_trace(trace_path=selected_trace, require_stage1_gate=require_stage1_gate)
    replay_path = out / f"learn_free_exploration_two_stage_replay_{timestamp}.json"
    _write_json(replay_path, replay)
    report["replay_report_path"] = _relative(replay_path, root)
    report["overlay_path"] = _relative(
        (replay.get("fusion") or {}).get("compiled_overlay_path") if isinstance(replay.get("fusion"), dict) else "",
        root,
    )
    stage2 = replay.get("stage2_numbering") if isinstance(replay.get("stage2_numbering"), dict) else {}
    fusion = replay.get("fusion") if isinstance(replay.get("fusion"), dict) else {}
    report["replay_summary"] = {
        "stage1_gate_status": (replay.get("stage1_gate") or {}).get("status")
        if isinstance(replay.get("stage1_gate"), dict)
        else None,
        "stage2_numbering_skipped": replay.get("stage2_numbering_skipped"),
        "numbered_item_count": stage2.get("numbered_item_count"),
        "fused_review_box_count": fusion.get("fused_review_box_count"),
        "overlay_status": replay.get("overlay_status"),
        "model_grounding_evidence": replay.get("model_grounding_evidence"),
    }

    protected_after = _protected_comparison(
        checkpoint_id=f"free_exploration_after_{timestamp}",
        baseline_path=baseline_path,
        root=root,
    )
    report["protected_after"] = protected_after
    if protected_after.get("passed") is not True:
        report["status"] = "blocked_protected_set_after_replay"
        report["blockers"] = ["protected_set_drift_after_free_exploration"]
    elif int(fusion.get("fused_review_box_count") or 0) > 0:
        report["status"] = "replay_ready_for_visual_review"
        report["blockers"] = []
    else:
        report["status"] = "replay_not_demo_ready"
        report["blockers"] = ["no_fused_review_boxes"]
    report_path = out / f"learning_free_exploration_from_trace_{timestamp}.json"
    report["report_path"] = _relative(report_path, root)
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe Learning Mode free exploration from a usable observe trace.")
    parser.add_argument("--trace", required=True, help="Non-protected observe trace JSON.")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, help="Protected-set archive baseline.")
    parser.add_argument("--allow-stage2-with-failed-stage1", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_learning_free_exploration_from_trace(
        trace_path=args.trace,
        out_dir=args.out,
        baseline_path=args.baseline,
        require_stage1_gate=not args.allow_stage2_with_failed_stage1,
    )
    summary = {
        "status": report.get("status"),
        "report_path": report.get("report_path"),
        "replay_report_path": report.get("replay_report_path"),
        "overlay_path": report.get("overlay_path"),
        "blockers": report.get("blockers") or [],
        "intake_classification": (report.get("intake_classification") or {}).get("classification"),
        "safety_boundary": report.get("safety_boundary"),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0 if report.get("status") not in {"blocked_protected_set_before_replay", "blocked_protected_set_after_replay"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
