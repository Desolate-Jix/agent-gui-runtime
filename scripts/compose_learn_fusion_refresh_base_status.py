from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


STATUS_NAME = "learn_fusion_refresh_base_status.json"
REPORT_NAME = "learn_fusion_refresh_base_status_compose_result.json"


def compose_learn_fusion_refresh_base_status(
    *,
    corrected_status_path: str | Path,
    full_screen_report_path: str | Path,
    calibration_batch_plan_path: str | Path,
    pathgraph_preflight_plan_path: str | Path | None = None,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    corrected_file = _resolve_path(corrected_status_path, root)
    full_screen_file = _resolve_path(full_screen_report_path, root)
    batch_file = _resolve_path(calibration_batch_plan_path, root)
    preflight_file = _resolve_path(pathgraph_preflight_plan_path, root) if pathgraph_preflight_plan_path is not None else None
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    corrected = _read_json(corrected_file)
    full_screen = _read_json(full_screen_file)
    batch_plan = _read_json(batch_file)
    preflight = _read_json(preflight_file) if preflight_file is not None else {}

    status = deepcopy(corrected)
    full_summary = full_screen.get("summary") if isinstance(full_screen.get("summary"), dict) else {}
    status["source_corrected_status_path"] = _relative_path(corrected_file, root)
    status["source_full_screen_report_path"] = _relative_path(full_screen_file, root)
    status["source_calibration_batch_plan_path"] = _relative_path(batch_file, root)
    status["source_pathgraph_preflight_plan_path"] = _relative_path(preflight_file, root) if preflight_file is not None else None
    status["full_screen_understanding_overlay_path"] = full_screen.get("full_screen_understanding_overlay_path")
    status["compiled_overlay_path"] = corrected.get("compiled_overlay_path") or full_screen.get("compiled_overlay_path")
    status["calibration_backlog"] = _safe_backlog(full_screen.get("calibration_backlog"))
    status["calibration_batch_plan"] = _safe_batch_plan(batch_plan)
    status["pathgraph_preflight_plan"] = _safe_preflight(preflight, batch_plan=batch_plan)
    status["display_readiness"] = _display_readiness(status)
    status["summary"] = _merged_summary(
        corrected_summary=corrected.get("summary") if isinstance(corrected.get("summary"), dict) else {},
        full_summary=full_summary,
        batch_plan=batch_plan,
    )
    status["precise_understanding_readiness_summary"] = _readiness_summary(status)
    status["refresh_base_status"] = {
        "contract_version": "learn_fusion_refresh_base_status_v1",
        "intended_for": "scripts\\refresh_learn_fusion_after_calibration_batch.py --base-status",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    status["execute_binding_enabled"] = False
    status["artifact_is_authorization"] = False
    status["display_only"] = True

    status_path = out / STATUS_NAME
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_refresh_base_status_compose_result_v1",
        "refresh_base_status_path": str(status_path.resolve()),
        "corrected_status_path": _relative_path(corrected_file, root),
        "full_screen_report_path": _relative_path(full_screen_file, root),
        "calibration_batch_plan_path": _relative_path(batch_file, root),
        "pathgraph_preflight_plan_path": _relative_path(preflight_file, root) if preflight_file is not None else None,
        "summary": status.get("summary"),
        "precise_understanding_readiness_summary": status.get("precise_understanding_readiness_summary"),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "display_only": True,
    }
    report_path = out / REPORT_NAME
    result["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _merged_summary(*, corrected_summary: dict[str, Any], full_summary: dict[str, Any], batch_plan: dict[str, Any]) -> dict[str, Any]:
    pending = _pending_counts(batch_plan)
    total = _int(full_summary.get("total_locator_cards"), corrected_summary.get("total_locator_cards"), corrected_summary.get("attempted"))
    uncalibrated = _int(full_summary.get("uncalibrated_locator_cards"), pending["ready_count"] + pending["review_count"])
    calibrated = _int(full_summary.get("calibrated_cases"), max(total - uncalibrated, 0) if total else 0)
    summary = deepcopy(corrected_summary)
    summary["total_locator_cards"] = total
    summary["calibrated_cases"] = calibrated
    summary["uncalibrated_locator_cards"] = uncalibrated
    summary["calibration_coverage_rate"] = round(calibrated / total, 4) if total else "not_covered"
    summary["real_clicks"] = _int(corrected_summary.get("real_clicks"), 0)
    return summary


def _readiness_summary(status: dict[str, Any]) -> dict[str, Any]:
    summary = status.get("summary") if isinstance(status.get("summary"), dict) else {}
    pending = _pending_counts(status.get("calibration_batch_plan") if isinstance(status.get("calibration_batch_plan"), dict) else {})
    total = _int(summary.get("total_locator_cards"), 0)
    calibrated = _int(summary.get("calibrated_cases"), 0)
    return {
        "contract_version": "precise_understanding_readiness_summary_v1",
        "readiness_status": "needs_pending_calibration" if pending["ready_count"] or pending["review_count"] else "needs_pathgraph_review",
        "total_locator_cards": total,
        "calibrated_cases": calibrated,
        "uncalibrated_locator_cards": _int(summary.get("uncalibrated_locator_cards"), 0),
        "calibration_coverage_rate": round(calibrated / total, 4) if total else "not_covered",
        "pending_calibration_ready_count": pending["ready_count"],
        "pending_calibration_review_count": pending["review_count"],
        "pathgraph_status": _text((status.get("pathgraph_preparation") or {}).get("status")) if isinstance(status.get("pathgraph_preparation"), dict) else "missing",
        "display_only": True,
        "not_accuracy": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _safe_backlog(value: Any) -> dict[str, Any]:
    backlog = deepcopy(value) if isinstance(value, dict) else {}
    summary = backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {}
    summary["display_only"] = True
    summary["execute_binding_enabled"] = False
    backlog["summary"] = summary
    backlog["items"] = _list_of_dicts(backlog.get("items"))
    backlog["display_only"] = True
    backlog["execute_binding_enabled"] = False
    backlog["artifact_is_authorization"] = False
    return backlog


def _safe_batch_plan(value: dict[str, Any]) -> dict[str, Any]:
    batch = deepcopy(value)
    batch["command_executes_now"] = False
    batch["post_batch_refresh_command_executes_now"] = False
    batch["execute_binding_enabled"] = False
    batch["artifact_is_authorization"] = False
    return batch


def _safe_preflight(value: dict[str, Any], *, batch_plan: dict[str, Any]) -> dict[str, Any]:
    preflight = deepcopy(value) if isinstance(value, dict) else {}
    summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
    pending = _pending_counts(batch_plan)
    summary["pending_calibration_ready_count"] = pending["ready_count"]
    summary["pending_calibration_review_count"] = pending["review_count"]
    summary["ready_for_runtime_pathgraph_promotion"] = False
    preflight["summary"] = summary
    pending_batch = preflight.get("pending_calibration_batch") if isinstance(preflight.get("pending_calibration_batch"), dict) else {}
    pending_batch["ready_region_numbers"] = _list_of_int(batch_plan.get("ready_region_numbers"))
    pending_batch["review_blocked_region_numbers"] = _list_of_int(batch_plan.get("review_blocked_region_numbers"))
    pending_batch["run_command_preview"] = batch_plan.get("run_command_preview")
    pending_batch["command_executes_now"] = False
    pending_batch["execute_binding_enabled"] = False
    pending_batch["artifact_is_authorization"] = False
    preflight["pending_calibration_batch"] = pending_batch
    preflight["execute_binding_enabled"] = False
    preflight["artifact_is_authorization"] = False
    return preflight


def _display_readiness(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "display_ready" if _text(status.get("full_screen_understanding_overlay_path")) else "display_evidence_missing",
        "full_screen_overlay_available": bool(_text(status.get("full_screen_understanding_overlay_path"))),
        "overlay_available": bool(_text(status.get("compiled_overlay_path"))),
        "screenshot_available": bool(_text(status.get("screenshot_path"))),
        "interpretation": "display readiness only; it does not authorize Execute or PathGraph promotion",
    }


def _pending_counts(batch_plan: dict[str, Any]) -> dict[str, int]:
    return {
        "ready_count": len(_list_of_int(batch_plan.get("ready_region_numbers"))),
        "review_count": len(_list_of_int(batch_plan.get("review_blocked_region_numbers"))),
    }


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_int(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _int(*values: Any) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compose a post-batch refresh base fusion status from corrected items and full-screen pending calibration evidence.")
    parser.add_argument("--corrected-status", required=True, help="Path to corrected fusion status with items")
    parser.add_argument("--full-screen-report", required=True, help="Path to full-screen overlay/backlog preview report")
    parser.add_argument("--calibration-batch-plan", required=True, help="Path to numbered_region_calibration_batch_plan.json")
    parser.add_argument("--pathgraph-preflight-plan", help="Optional path to learn_fusion_pathgraph_preflight_plan.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    compose_learn_fusion_refresh_base_status(
        corrected_status_path=args.corrected_status,
        full_screen_report_path=args.full_screen_report,
        calibration_batch_plan_path=args.calibration_batch_plan,
        pathgraph_preflight_plan_path=args.pathgraph_preflight_plan,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
