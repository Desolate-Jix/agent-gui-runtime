from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review


REPORT_NAME = "learn_fusion_handoff_consistency_report.json"


def report_learn_fusion_handoff_consistency(
    *,
    draft_path: str | Path,
    batch_plan_path: str | Path,
    handoff_report_path: str | Path,
    acceptance_report_path: str | Path,
    out_dir: str | Path,
    refresh_result_path: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    """审计当前学习模式 handoff 材料是否指向同一条安全的后续链路。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    draft_file = _resolve_path(draft_path, root)
    plan_file = _resolve_path(batch_plan_path, root)
    handoff_file = _resolve_path(handoff_report_path, root)
    acceptance_file = _resolve_path(acceptance_report_path, root)
    refresh_file = _resolve_path(refresh_result_path, root) if refresh_result_path is not None else None
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    plan = _read_json(plan_file)
    handoff = _read_json(handoff_file)
    acceptance = _read_json(acceptance_file)
    refresh = _read_json(refresh_file) if refresh_file is not None and refresh_file.exists() else {}
    review = load_learning_draft_review(draft_file, project_root=root)
    preview = review.get("screen_understanding_preview") if isinstance(review.get("screen_understanding_preview"), dict) else {}

    plan_args = _list_of_text(plan.get("post_batch_refresh_command_args"))
    handoff_commands = handoff.get("commands") if isinstance(handoff.get("commands"), dict) else {}
    handoff_args = _list_of_text(handoff_commands.get("post_batch_refresh_command_args"))
    embedded_fusion = _embedded_fusion(draft_file)
    draft_preview_text = _text(preview.get("post_batch_refresh_command_preview"))
    if not draft_preview_text:
        draft_preview_text = _embedded_post_batch_refresh_preview(embedded_fusion)

    plan_ready = _list_of_int(plan.get("ready_region_numbers"))
    handoff_ready = _list_of_int(handoff.get("ready_region_numbers"))
    expected_ready = _list_of_int((acceptance.get("coverage") or {}).get("expected_ready_region_numbers") if isinstance(acceptance.get("coverage"), dict) else [])
    readiness = preview.get("precise_understanding_readiness_summary") if isinstance(preview.get("precise_understanding_readiness_summary"), dict) else {}
    if not readiness:
        readiness = embedded_fusion.get("precise_understanding_readiness_summary") if isinstance(embedded_fusion.get("precise_understanding_readiness_summary"), dict) else {}
    pending = preview.get("pending_calibration") if isinstance(preview.get("pending_calibration"), dict) else {}
    pending_ready = _list_of_int(pending.get("ready_region_numbers"))

    refresh_required = acceptance.get("acceptance_status") == "awaiting_future_calibration_output"
    checks = {
        "draft_loads": review.get("contract_version") == "learning_draft_review_v1",
        "plan_post_batch_refresh_has_batch_plan": _has_batch_plan_arg(plan_args),
        "plan_post_batch_refresh_refs_current_batch_plan": _arg_path_matches(plan_args, "--batch-plan", plan_file, root),
        "draft_post_batch_refresh_has_batch_plan": "--batch-plan" in draft_preview_text,
        "handoff_status_ready": handoff.get("handoff_status") == "ready_for_explicit_model_start",
        "handoff_post_batch_refresh_has_batch_plan": _has_batch_plan_arg(handoff_args),
        "handoff_post_batch_refresh_refs_current_batch_plan": _arg_path_matches(handoff_args, "--batch-plan", plan_file, root),
        "ready_regions_match": plan_ready == handoff_ready == expected_ready,
        "readiness_requires_pending_calibration": readiness.get("readiness_status") == "needs_pending_calibration",
        "pending_ready_regions_match_plan": not pending_ready or pending_ready == plan_ready,
        "acceptance_is_waiting_or_ready": acceptance.get("acceptance_status") in {"awaiting_future_calibration_output", "accepted_for_post_batch_refresh"},
        "acceptance_waiting_reason_is_future_rerun": not refresh_required or "rerun_report_missing" in _list_of_text(acceptance.get("blockers")),
        "commands_are_preview_only": plan.get("command_executes_now") is not True
        and plan.get("post_batch_refresh_command_executes_now") is not True
        and handoff_commands.get("command_executes_now") is not True
        and handoff_commands.get("post_batch_refresh_command_executes_now") is not True,
        "no_start_model_flag_in_preview": "--start-model" not in plan_args and handoff_commands.get("start_model_flag_included") is not True,
        "safety_flags_disabled": _safety_flags_disabled(plan, handoff, acceptance),
    }
    if refresh_file is not None:
        checks["refresh_blocks_before_future_rerun"] = (
            refresh.get("refresh_status") == "blocked_by_calibration_batch_acceptance"
            and refresh.get("merge_skipped") is True
            and refresh.get("attach_skipped") is True
            and refresh.get("readiness_skipped") is True
        )

    blocker_map = {
        "draft_loads": "draft_not_loadable_by_learning_review",
        "plan_post_batch_refresh_has_batch_plan": "plan_post_batch_refresh_missing_batch_plan_arg",
        "plan_post_batch_refresh_refs_current_batch_plan": "plan_post_batch_refresh_batch_plan_path_mismatch",
        "draft_post_batch_refresh_has_batch_plan": "draft_post_batch_refresh_missing_batch_plan_arg",
        "handoff_status_ready": "handoff_not_ready_for_explicit_model_start",
        "handoff_post_batch_refresh_has_batch_plan": "handoff_post_batch_refresh_missing_batch_plan_arg",
        "handoff_post_batch_refresh_refs_current_batch_plan": "handoff_post_batch_refresh_batch_plan_path_mismatch",
        "ready_regions_match": "ready_region_numbers_mismatch",
        "readiness_requires_pending_calibration": "readiness_not_waiting_for_pending_calibration",
        "pending_ready_regions_match_plan": "pending_ready_regions_mismatch_plan",
        "acceptance_is_waiting_or_ready": "acceptance_status_not_waiting_or_ready",
        "acceptance_waiting_reason_is_future_rerun": "acceptance_waiting_reason_not_future_rerun",
        "commands_are_preview_only": "command_preview_marked_executable",
        "no_start_model_flag_in_preview": "start_model_flag_present_in_preview",
        "safety_flags_disabled": "safety_flags_not_disabled",
        "refresh_blocks_before_future_rerun": "refresh_does_not_block_before_future_rerun",
    }
    blockers = [blocker_map[key] for key, passed in checks.items() if not passed]
    status = "blocked" if blockers else _ready_status(acceptance)
    report = {
        "contract_version": "learn_fusion_handoff_consistency_report_v1",
        "consistency_status": status,
        "draft_path": _relative_path(draft_file, root),
        "batch_plan_path": _relative_path(plan_file, root),
        "handoff_report_path": _relative_path(handoff_file, root),
        "acceptance_report_path": _relative_path(acceptance_file, root),
        "refresh_result_path": _relative_path(refresh_file, root) if refresh_file is not None else None,
        "summary": {
            "readiness_status": readiness.get("readiness_status"),
            "handoff_status": handoff.get("handoff_status"),
            "acceptance_status": acceptance.get("acceptance_status"),
            "ready_region_numbers": plan_ready,
            "review_blocked_region_numbers": _list_of_int(plan.get("review_blocked_region_numbers")),
            "post_batch_refresh_has_batch_plan": checks["plan_post_batch_refresh_has_batch_plan"]
            and checks["draft_post_batch_refresh_has_batch_plan"]
            and checks["handoff_post_batch_refresh_has_batch_plan"],
            "refresh_blocks_before_future_rerun": checks.get("refresh_blocks_before_future_rerun"),
        },
        "checks": checks,
        "blockers": blockers,
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": bool(refresh.get("model_started")) if refresh else False,
            "live_clicks": _int_value(refresh.get("live_clicks")) if refresh else 0,
            "live_fills": _int_value(refresh.get("live_fills")) if refresh else 0,
            "live_submits": _int_value(refresh.get("live_submits")) if refresh else 0,
            "runtime_pathgraph_promotion": bool(refresh.get("runtime_pathgraph_promotion")) if refresh else False,
        },
        "interpretation": (
            "Offline consistency audit for the Learning Draft calibration handoff package. "
            "It does not start models, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
        ),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _ready_status(acceptance: dict[str, Any]) -> str:
    if acceptance.get("acceptance_status") == "accepted_for_post_batch_refresh":
        return "ready_for_post_batch_refresh"
    return "ready_for_explicit_model_start"


def _safety_flags_disabled(*payloads: dict[str, Any]) -> bool:
    for payload in payloads:
        if payload.get("execute_binding_enabled") is True or payload.get("artifact_is_authorization") is True:
            return False
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        if safety.get("execute_binding_enabled") is True or safety.get("artifact_is_authorization") is True:
            return False
        if _int_value(safety.get("real_clicks")) or _int_value(payload.get("real_clicks")):
            return False
    return True


def _embedded_fusion(draft_file: Path) -> dict[str, Any]:
    payload = _read_json(draft_file)
    draft = payload.get("learning_draft") if isinstance(payload.get("learning_draft"), dict) else payload
    details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    audit = details.get("pipeline_audit") if isinstance(details.get("pipeline_audit"), dict) else {}
    return audit.get("precise_understanding_fusion_status") if isinstance(audit.get("precise_understanding_fusion_status"), dict) else {}


def _embedded_post_batch_refresh_preview(fusion: dict[str, Any]) -> str:
    batch = fusion.get("calibration_batch_plan") if isinstance(fusion.get("calibration_batch_plan"), dict) else {}
    return _text(batch.get("post_batch_refresh_command_preview"))


def _has_batch_plan_arg(args: list[str]) -> bool:
    return "--batch-plan" in args


def _arg_path_matches(args: list[str], flag: str, expected: Path, root: Path) -> bool:
    try:
        value = args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return False
    return _resolve_path(value, root) == expected.resolve()


def _resolve_path(path: str | Path | None, root: Path) -> Path:
    resolved = Path(path or "")
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_text(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _list_of_int(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        parsed = _int_or_none(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the current Learning Draft calibration handoff package.")
    parser.add_argument("--draft", required=True, help="Current recommended Learning Draft artifact")
    parser.add_argument("--batch-plan", required=True, help="numbered_region_calibration_batch_plan.json")
    parser.add_argument("--handoff-report", required=True, help="learn_fusion_calibration_handoff_report.json")
    parser.add_argument("--acceptance-report", required=True, help="learn_fusion_calibration_batch_acceptance_report.json")
    parser.add_argument("--refresh-result", help="Optional post-batch refresh result JSON")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_learn_fusion_handoff_consistency(
        draft_path=args.draft,
        batch_plan_path=args.batch_plan,
        handoff_report_path=args.handoff_report,
        acceptance_report_path=args.acceptance_report,
        refresh_result_path=args.refresh_result,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
