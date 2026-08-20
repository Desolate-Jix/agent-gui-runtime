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

from app.core.window_manager import window_manager


PROTECTED_HINTS = ("applemusic", "apple music", "qq", "python.org", "python-org", "python_org")
PANEL_SELF_HINTS = (
    "127.0.0.1:8000",
    "localhost:8000",
    "/panel",
    "learn_replay",
    "learning draft",
    "学习草稿",
    "pathgraph",
)
CONTROL_SURFACE_HINTS = ("chatgpt", "codex")
CONTROL_PROCESS_HINTS = ("codex",)
SYSTEM_OR_OVERLAY_TITLE_HINTS = (
    "nvidia geforce overlay",
    "program manager",
    "microsoft text input application",
)
SYSTEM_OR_OVERLAY_PROCESS_HINTS = (
    "nvidia overlay.exe",
    "textinputhost.exe",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _blob(window: dict[str, Any]) -> str:
    return " ".join(
        str(window.get(key) or "")
        for key in ("title", "window_title", "process_name", "app_name")
    ).lower()


def classify_window_candidate(window: dict[str, Any]) -> dict[str, Any]:
    blob = _blob(window)
    reasons: list[str] = []
    classification = "usable_non_protected_window"
    candidate = True
    if any(hint in blob for hint in PROTECTED_HINTS):
        classification = "protected_baseline_window"
        candidate = False
        reasons.append("belongs_to_applemusic_qq_or_python_protected_set")
    elif any(hint in blob for hint in PANEL_SELF_HINTS):
        classification = "panel_self_observation_window"
        candidate = False
        reasons.append("panel_or_loaded_learning_artifact_window")
    elif any(hint in blob for hint in CONTROL_SURFACE_HINTS) or any(
        hint in str(window.get("process_name") or "").lower() for hint in CONTROL_PROCESS_HINTS
    ):
        classification = "control_or_review_window"
        candidate = False
        reasons.append("codex_or_chatgpt_control_surface_reserved")
    elif any(hint in blob for hint in SYSTEM_OR_OVERLAY_TITLE_HINTS) or any(
        hint in str(window.get("process_name") or "").lower() for hint in SYSTEM_OR_OVERLAY_PROCESS_HINTS
    ):
        classification = "system_or_overlay_window"
        candidate = False
        reasons.append("system_shell_input_or_overlay_window")
    if candidate:
        reasons.append("non_protected_visible_window")
    return {
        "window": window,
        "candidate_for_free_exploration_capture": candidate,
        "classification": classification,
        "reasons": reasons,
    }


def build_window_candidate_gate(items: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [item for item in items if item.get("candidate_for_free_exploration_capture") is True]
    by_class: dict[str, int] = {}
    for item in items:
        key = str(item.get("classification") or "unknown")
        by_class[key] = by_class.get(key, 0) + 1
    blockers: list[str] = []
    if not candidates:
        blockers.append("no_usable_non_protected_visible_window")
    return {
        "contract_version": "learning_free_exploration_window_candidate_gate_v1",
        "allowed": bool(candidates),
        "status": "ready_for_safe_bind_capture_observe" if candidates else "blocked_until_target_window_available",
        "candidate_count": len(candidates),
        "classification_counts": by_class,
        "blockers": blockers,
        "forbidden_window_types": [
            "protected_baseline_window",
            "panel_self_observation_window",
            "control_or_review_window",
            "system_or_overlay_window",
        ],
        "interpretation": (
            "This only audits visible windows for a future no-click observe capture. It does not bind, "
            "capture, run recognition, authorize Execute, or promote a Runtime PathGraph."
        ),
    }


def run_window_candidate_inventory() -> dict[str, Any]:
    windows = window_manager.list_visible_windows()
    items = [classify_window_candidate(dict(window)) for window in windows]
    candidates = [item for item in items if item.get("candidate_for_free_exploration_capture") is True]
    return {
        "contract_version": "learning_free_exploration_window_candidate_inventory_v1",
        "generated_at": _now(),
        "scanned_window_count": len(items),
        "candidate_count": len(candidates),
        "gate": build_window_candidate_gate(items),
        "candidates": candidates,
        "items": items,
        "next_action": (
            "Bind one candidate window, run /vision/observe_screen with capture_live=true, then run free-exploration preflight."
            if candidates
            else "Open or focus a real non-protected target app/window, then rerun this inventory."
        ),
        "safety_boundary": {
            "bind_performed": False,
            "capture_performed": False,
            "observe_performed": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit visible windows before Learning Mode free exploration.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_window_candidate_inventory()
    if args.out:
        _write_json(Path(args.out), report)
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("candidate_count", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
