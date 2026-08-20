from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_DIR = ROOT / "logs" / "traces" / "vision"
PROTECTED_SURFACE_HINTS = ("applemusic", "apple-music", "qq", "python_org", "python-org")
PANEL_SELF_OBSERVATION_HINTS = (
    "127.0.0.1:8000/panel",
    "localhost:8000/panel",
    "stage=learn_replay",
    "learn_view=draft",
    "learning draft",
    "学习草稿",
    "草稿路径图",
    "pathgraph",
)


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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    return result if isinstance(result, dict) else payload


def _image_path(result: dict[str, Any]) -> str:
    for key in ("image_path", "source_image_path", "screenshot_path"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    value = str(live_capture.get("image_path") or "").strip()
    if value:
        return value
    screen_map = result.get("screen_map") if isinstance(result.get("screen_map"), dict) else {}
    return str(screen_map.get("image_path") or "").strip()


def _inventory_counts(result: dict[str, Any]) -> dict[str, int]:
    texts = result.get("texts") if isinstance(result.get("texts"), list) else []
    ui_elements = result.get("ui_elements") if isinstance(result.get("ui_elements"), list) else []
    modules = result.get("modules") if isinstance(result.get("modules"), list) else []
    relationships = result.get("relationships") if isinstance(result.get("relationships"), list) else []
    screen_map = result.get("screen_map") if isinstance(result.get("screen_map"), dict) else {}
    return {
        "texts": len(texts),
        "ui_elements": len(ui_elements),
        "modules": len(modules),
        "relationships": len(relationships),
        "screen_map": 1 if screen_map else 0,
    }


def _is_protected(path: Path, payload: dict[str, Any], image_path: str) -> bool:
    blob = " ".join(
        [
            path.name,
            image_path,
            json.dumps(payload.get("request", {}), ensure_ascii=False)[:1000],
        ]
    ).lower()
    return any(hint in blob for hint in PROTECTED_SURFACE_HINTS)


def _is_panel_self_observation(payload: dict[str, Any]) -> bool:
    result = _result_payload(payload)
    sample: list[Any] = [
        payload.get("request", {}),
        result.get("screen_map", {}),
        result.get("screen_summary"),
        result.get("state_guess"),
        result.get("suggested_state_hint"),
        result.get("app_name"),
        result.get("texts", [])[:120] if isinstance(result.get("texts"), list) else [],
    ]
    blob = json.dumps(sample, ensure_ascii=False).lower()
    return any(hint in blob for hint in PANEL_SELF_OBSERVATION_HINTS)


def classify_learning_trace_source(path: str | Path, *, root: Path = ROOT) -> dict[str, Any]:
    trace_path = _resolve(path, root)
    result: dict[str, Any] = {
        "trace_path": _relative(trace_path, root),
        "candidate_for_free_exploration": False,
        "classification": "unknown",
        "reasons": [],
    }
    if not trace_path.exists():
        result["classification"] = "missing_trace"
        result["reasons"].append("trace_missing")
        return result
    try:
        payload = _read_json(trace_path)
    except Exception as exc:  # noqa: BLE001
        result["classification"] = "invalid_json"
        result["reasons"].append(f"json_read_failed:{type(exc).__name__}")
        return result

    trace_result = _result_payload(payload)
    image_text = _image_path(trace_result)
    image = _resolve(image_text, root) if image_text else Path("")
    image_exists = bool(image_text and image.exists())
    counts = _inventory_counts(trace_result)
    inventory_count = sum(counts.values())
    protected = _is_protected(trace_path, payload, image_text)
    result.update(
        {
            "image_path": _relative(image, root) if image_text else "",
            "image_exists": image_exists,
            "protected_surface": protected,
            "inventory_counts": counts,
            "inventory_total": inventory_count,
        }
    )
    if protected:
        result["classification"] = "protected_baseline_trace"
        result["reasons"].append("belongs_to_applemusic_qq_or_python_protected_set")
        return result
    if _is_panel_self_observation(payload):
        result["classification"] = "panel_self_observation_trace"
        result["reasons"].append("panel_self_observation_or_loaded_learning_artifact")
        return result
    if "panel-model-test" in trace_path.name or "model_io" in payload and "result" not in payload:
        result["classification"] = "model_test_trace"
        result["reasons"].append("not_a_real_observe_trace")
        return result
    if not image_exists:
        result["classification"] = "missing_or_stale_image"
        result["reasons"].append("source_image_missing_or_temp_path_stale")
        return result
    if inventory_count <= 0:
        result["classification"] = "image_without_observe_inventory"
        result["reasons"].append("no_texts_ui_elements_modules_relationships_or_screen_map")
        return result
    result["classification"] = "usable_non_protected_observe_trace"
    result["candidate_for_free_exploration"] = True
    result["reasons"].append("non_protected_trace_with_existing_image_and_observe_inventory")
    return result


def build_free_exploration_intake_gate(
    *,
    candidates: list[dict[str, Any]],
    classification_counts: dict[str, int],
) -> dict[str, Any]:
    blockers: list[str] = []
    rejected_source_warnings: list[str] = []
    if not candidates:
        blockers.append("no_usable_non_protected_observe_trace")
    inventory_missing_count = int(classification_counts.get("image_without_observe_inventory") or 0)
    stale_image_count = int(classification_counts.get("missing_or_stale_image") or 0)
    if inventory_missing_count > 0:
        target = rejected_source_warnings if candidates else blockers
        target.append("screenshot_only_or_inventory_missing_not_allowed")
    if stale_image_count > 0:
        target = rejected_source_warnings if candidates else blockers
        target.append("missing_or_stale_image_not_allowed")
    panel_self_count = int(classification_counts.get("panel_self_observation_trace") or 0)
    if panel_self_count > 0:
        target = rejected_source_warnings if candidates else blockers
        target.append("panel_self_observation_not_allowed")
    if int(classification_counts.get("protected_baseline_trace") or 0) > 0 and not candidates:
        blockers.append("protected_baseline_must_not_be_used_for_free_exploration")
    allowed = not blockers and bool(candidates)
    return {
        "contract_version": "learning_free_exploration_intake_gate_v1",
        "allowed": allowed,
        "status": "ready_for_safe_free_exploration" if allowed else "blocked_until_real_observe_capture",
        "candidate_count": len(candidates),
        "blockers": blockers,
        "rejected_source_warnings": rejected_source_warnings,
        "required_source_type": "non_protected_real_observe_trace_with_existing_screenshot_and_inventory",
        "forbidden_source_types": [
            "screenshot_only",
            "panel_model_test",
            "panel_self_observation_trace",
            "protected_baseline_trace",
            "missing_or_stale_image",
            "image_without_observe_inventory",
        ],
        "interpretation": (
            "Free exploration is allowed only when at least one non-protected real observe trace has an "
            "existing screenshot and OCR/UIA/screen inventory. This gate is not recognition accuracy, "
            "model grounding, Execute authorization, or Runtime PathGraph readiness."
        ),
    }


def run_free_exploration_source_inventory(
    *,
    trace_dir: str | Path = DEFAULT_TRACE_DIR,
    root: Path = ROOT,
    limit: int = 500,
) -> dict[str, Any]:
    selected_dir = _resolve(trace_dir, root)
    traces = sorted(selected_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    items = [classify_learning_trace_source(path, root=root) for path in traces]
    candidates = [item for item in items if item.get("candidate_for_free_exploration") is True]
    by_class: dict[str, int] = {}
    for item in items:
        key = str(item.get("classification") or "unknown")
        by_class[key] = by_class.get(key, 0) + 1
    intake_gate = build_free_exploration_intake_gate(
        candidates=candidates,
        classification_counts=by_class,
    )
    return {
        "contract_version": "learning_free_exploration_source_inventory_v1",
        "generated_at": _now(),
        "trace_dir": _relative(selected_dir, root),
        "scanned_trace_count": len(items),
        "candidate_count": len(candidates),
        "classification_counts": by_class,
        "intake_gate": intake_gate,
        "candidates": candidates,
        "items": items,
        "next_action": (
            "Use a candidate trace with scripts/run_learning_free_exploration_from_trace.py"
            if candidates
            else "Capture a real non-protected window through /vision/observe_screen so OCR/UIA inventory is available"
        ),
        "interpretation": (
            "Only non-protected traces with an existing screenshot and real observe inventory are suitable for the "
            "next free-exploration recognition pass. Screenshot-only and model-test traces are not demo evidence."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory Learning Mode free-exploration source traces.")
    parser.add_argument("--trace-dir", default=str(DEFAULT_TRACE_DIR), help="Trace directory to scan.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum recent traces to scan.")
    parser.add_argument("--out", default="", help="Optional JSON output path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_free_exploration_source_inventory(trace_dir=args.trace_dir, limit=args.limit)
    if args.out:
        out_path = _resolve(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
