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

from scripts.check_learning_exploration_readiness import run_learning_exploration_readiness_check
from scripts.report_learning_free_exploration_sources import classify_learning_trace_source


DEFAULT_BASELINE = "logs/benchmarks/learning_protected_after_structure_quality_archive_fields_20260711.json"


def prepare_learning_free_exploration_preflight(
    *,
    trace_path: str | Path | None = None,
    baseline_path: str | Path = DEFAULT_BASELINE,
    checkpoint_id: str = "free_exploration_preflight",
    root: Path = ROOT,
) -> dict[str, Any]:
    readiness = run_learning_exploration_readiness_check(
        baseline_path=baseline_path,
        checkpoint_id=checkpoint_id,
        root=root,
    )
    trace_classification = (
        classify_learning_trace_source(trace_path, root=root)
        if trace_path
        else {
            "candidate_for_free_exploration": False,
            "classification": "not_provided",
            "reasons": ["trace_path_required"],
        }
    )
    protected_ready = bool(readiness.get("ready_for_new_interface_exploration") is True)
    trace_ready = bool(trace_classification.get("candidate_for_free_exploration") is True)
    blockers: list[str] = []
    if not protected_ready:
        blockers.append("protected_readiness_failed")
    if not trace_ready:
        blockers.append("usable_non_protected_observe_trace_required")
    status = "ready_for_no_click_free_exploration_replay" if not blockers else "blocked_before_replay"
    return {
        "contract_version": "learning_free_exploration_preflight_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "blockers": blockers,
        "trace_classification": trace_classification,
        "readiness_summary": readiness.get("summary") if isinstance(readiness.get("summary"), dict) else {},
        "ready_for_new_interface_exploration": protected_ready,
        "ready_for_free_exploration_replay": status == "ready_for_no_click_free_exploration_replay",
        "next_command": (
            f"uv run python scripts\\run_learning_free_exploration_from_trace.py --trace "
            f"{trace_classification.get('trace_path')} --out logs\\benchmarks\\learning_free_exploration_next --json"
            if status == "ready_for_no_click_free_exploration_replay"
            else ""
        ),
        "required_capture": {
            "source_type": "non_protected_real_observe_trace_with_existing_screenshot_and_inventory",
            "capture_route": "/vision/observe_screen",
            "must_include": [
                "existing screenshot path",
                "OCR/UIA text or element inventory",
                "non-protected surface name",
            ],
            "forbidden_sources": [
                "AppleMusic / QQ / Python protected baselines",
                "screenshot-only image",
                "panel model-test trace",
                "panel self-observation or loaded learning artifact replay",
                "missing or stale temp image",
            ],
        },
        "safety_boundary": {
            "display_review_only": True,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "interpretation": (
            "Preflight gate for the next Learning Mode free-exploration replay. Passing means the protected "
            "AppleMusic / QQ / Python baseline is intact and the supplied trace is a real non-protected observe "
            "trace with inventory. It is not recognition accuracy or Execute authorization."
        ),
    }


def _resolve(path: str | Path, root: Path = ROOT) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a no-click Learning Mode free-exploration replay.")
    parser.add_argument("--trace", default="", help="Candidate observe trace path.")
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--checkpoint-id", default="free_exploration_preflight")
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = prepare_learning_free_exploration_preflight(
        trace_path=args.trace or None,
        baseline_path=args.baseline,
        checkpoint_id=args.checkpoint_id,
    )
    if args.out:
        out = _resolve(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ready_for_no_click_free_exploration_replay" else 1


if __name__ == "__main__":
    raise SystemExit(main())
