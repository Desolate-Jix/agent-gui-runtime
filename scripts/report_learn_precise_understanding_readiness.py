from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_precise_understanding_readiness_report.json"


def report_precise_understanding_readiness(
    *,
    draft_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    draft_file = _resolve_path(draft_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    payload = _read_json(draft_file)
    draft = _select_draft(payload)
    fusion = _fusion_status(draft)
    pending = _pending_calibration(fusion)
    coverage = _coverage_summary(fusion, pending=pending)
    pathgraph = _pathgraph_readiness(fusion)
    safety = _safety_summary(fusion)
    evidence_integrity = _evidence_integrity(fusion, draft_file=draft_file, root=root)
    readiness_status = _readiness_status(coverage=coverage, pending=pending, pathgraph=pathgraph, safety=safety)
    report = {
        "contract_version": "learn_precise_understanding_readiness_report_v1",
        "source_draft_path": _relative_path(draft_file, root),
        "readiness_status": readiness_status,
        "coverage_summary": coverage,
        "pending_calibration": pending,
        "pathgraph_readiness": pathgraph,
        "evidence_integrity": evidence_integrity,
        "safety": safety,
        "next_required_steps": _next_required_steps(
            readiness_status=readiness_status,
            pending=pending,
            pathgraph=pathgraph,
            evidence_integrity=evidence_integrity,
        ),
        "display_only": True,
        "not_accuracy": True,
        "not_pathgraph_promotion": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Offline readiness report for fused Learn Mode understanding. "
            "It summarizes display coverage, pending calibration, and PathGraph review blockers; "
            "it does not authorize Execute, clicks, fill, submit, or Runtime PathGraph promotion."
        ),
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_precise_understanding_readiness_report_build_result_v1",
        "report_path": str(report_path.resolve()),
        "readiness_status": readiness_status,
        "coverage_summary": coverage,
        "pending_calibration": pending,
        "pathgraph_readiness": pathgraph,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _coverage_summary(fusion: dict[str, Any], *, pending: dict[str, Any]) -> dict[str, Any]:
    summary = fusion.get("summary") if isinstance(fusion.get("summary"), dict) else {}
    backlog = fusion.get("calibration_backlog") if isinstance(fusion.get("calibration_backlog"), dict) else {}
    backlog_summary = backlog.get("summary") if isinstance(backlog.get("summary"), dict) else {}
    backlog_items = _list_of_dicts(backlog.get("items"))
    has_coverage_context = (
        _has_any_int(
            summary.get("total_locator_cards"),
            summary.get("calibrated_cases"),
            summary.get("uncalibrated_locator_cards"),
        )
        or bool(backlog_items)
        or _int(backlog_summary.get("uncalibrated_locator_cards"), 0) > 0
        or _int(pending.get("ready_count"), 0) > 0
        or _int(pending.get("review_blocked_count"), 0) > 0
    )
    total = _int(summary.get("total_locator_cards"), summary.get("attempted"), 0) if has_coverage_context else 0
    uncalibrated = _int(
        summary.get("uncalibrated_locator_cards"),
        backlog_summary.get("uncalibrated_locator_cards"),
        None,
    )
    if uncalibrated == 0 and not _has_any_int(summary.get("uncalibrated_locator_cards"), backlog_summary.get("uncalibrated_locator_cards")):
        uncalibrated = _int(pending.get("ready_count"), 0) + _int(pending.get("review_blocked_count"), 0)
    calibrated = _int(summary.get("calibrated_cases"), total - uncalibrated if total else 0)
    if total and not calibrated and uncalibrated <= total:
        calibrated = total - uncalibrated
    rate = round(calibrated / total, 4) if total else "not_covered"
    return {
        "total_locator_cards": total,
        "calibrated_cases": calibrated,
        "uncalibrated_locator_cards": uncalibrated,
        "calibration_coverage_rate": rate,
    }


def _pending_calibration(fusion: dict[str, Any]) -> dict[str, Any]:
    batch = fusion.get("calibration_batch_plan") if isinstance(fusion.get("calibration_batch_plan"), dict) else {}
    preflight = fusion.get("pathgraph_preflight_plan") if isinstance(fusion.get("pathgraph_preflight_plan"), dict) else {}
    pending_batch = (
        preflight.get("pending_calibration_batch")
        if isinstance(preflight.get("pending_calibration_batch"), dict)
        else {}
    )
    source = pending_batch if pending_batch else batch
    ready = _list_of_int(source.get("ready_region_numbers"))
    review = _list_of_int(source.get("review_blocked_region_numbers"))
    return {
        "ready_region_numbers": ready,
        "review_blocked_region_numbers": review,
        "ready_count": len(ready),
        "review_blocked_count": len(review),
        "run_command_preview": _text(source.get("run_command_preview")),
        "command_executes_now": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _pathgraph_readiness(fusion: dict[str, Any]) -> dict[str, Any]:
    preparation = fusion.get("pathgraph_preparation") if isinstance(fusion.get("pathgraph_preparation"), dict) else {}
    queue = fusion.get("pathgraph_review_queue") if isinstance(fusion.get("pathgraph_review_queue"), dict) else {}
    queue_summary = queue.get("summary") if isinstance(queue.get("summary"), dict) else {}
    preflight = fusion.get("pathgraph_preflight_plan") if isinstance(fusion.get("pathgraph_preflight_plan"), dict) else {}
    preflight_summary = preflight.get("summary") if isinstance(preflight.get("summary"), dict) else {}
    return {
        "status": _text(preparation.get("status")) or "missing",
        "promotable_item_count": _int(preparation.get("promotable_item_count"), 0),
        "blocked_item_count": _int(preparation.get("blocked_item_count"), 0),
        "open_detail_candidate_review": _int(queue_summary.get("open_detail_candidate_review"), 0),
        "same_screen_action_review": _int(queue_summary.get("same_screen_action_review"), 0),
        "geometry_review_required": _int(queue_summary.get("geometry_review_required"), 0),
        "blocked_non_action": _int(queue_summary.get("blocked_non_action"), 0),
        "pending_calibration_ready_count": _int(preflight_summary.get("pending_calibration_ready_count"), 0),
        "pending_calibration_review_count": _int(preflight_summary.get("pending_calibration_review_count"), 0),
        "ready_for_runtime_pathgraph_promotion": preflight_summary.get("ready_for_runtime_pathgraph_promotion") is True,
    }


def _safety_summary(fusion: dict[str, Any]) -> dict[str, Any]:
    summary = fusion.get("summary") if isinstance(fusion.get("summary"), dict) else {}
    safety = fusion.get("safety") if isinstance(fusion.get("safety"), dict) else {}
    return {
        "real_clicks": _int(summary.get("real_clicks"), safety.get("real_clicks"), 0),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "no_dispatch": True,
    }


def _evidence_integrity(fusion: dict[str, Any], *, draft_file: Path, root: Path) -> dict[str, Any]:
    evidence_paths = {
        "screenshot": fusion.get("screenshot_path"),
        "full_screen_understanding_overlay": fusion.get("full_screen_understanding_overlay_path"),
        "compiled_overlay": fusion.get("compiled_overlay_path"),
        "source_status_report": fusion.get("source_status_report_path"),
        "source_calibration_report": fusion.get("source_calibration_report_path"),
    }
    declared: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for name, raw_path in evidence_paths.items():
        text_path = _text(raw_path)
        if not text_path:
            continue
        item = _path_evidence(name, text_path, root=root)
        declared[name] = item
        if item["exists"] is not True:
            missing.append(name)
    if missing:
        status = "missing_declared_evidence"
    elif declared:
        status = "complete"
    else:
        status = "no_declared_external_evidence"
    return {
        "contract_version": "learn_precise_understanding_evidence_integrity_v1",
        "status": status,
        "required_for_pathgraph_review": True,
        "source_draft": _existing_file_evidence("source_draft", draft_file, root=root),
        "missing_declared_evidence": missing,
        **declared,
    }


def _path_evidence(kind: str, raw_path: str, *, root: Path) -> dict[str, Any]:
    path = _resolve_path(raw_path, root)
    return _file_evidence(kind, path, raw_path=raw_path, root=root)


def _existing_file_evidence(kind: str, path: Path, *, root: Path) -> dict[str, Any]:
    return _file_evidence(kind, path, raw_path=_relative_path(path, root), root=root)


def _file_evidence(kind: str, path: Path, *, raw_path: str, root: Path) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    return {
        "kind": kind,
        "path": _relative_path(path, root),
        "declared_path": raw_path,
        "exists": exists,
        "sha256": _sha256_file(path) if exists else "",
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readiness_status(
    *,
    coverage: dict[str, Any],
    pending: dict[str, Any],
    pathgraph: dict[str, Any],
    safety: dict[str, Any],
) -> str:
    if safety.get("real_clicks") != 0:
        return "invalid_live_action_evidence"
    if pending.get("ready_count") or pending.get("review_blocked_count"):
        return "needs_pending_calibration"
    if pathgraph.get("ready_for_runtime_pathgraph_promotion") is True:
        return "ready_for_manual_runtime_promotion_review"
    if coverage.get("total_locator_cards") == 0:
        return "not_covered"
    return "needs_pathgraph_review"


def _next_required_steps(
    *,
    readiness_status: str,
    pending: dict[str, Any],
    pathgraph: dict[str, Any],
    evidence_integrity: dict[str, Any] | None = None,
) -> list[str]:
    steps: list[str] = []
    if evidence_integrity and evidence_integrity.get("status") == "missing_declared_evidence":
        steps.append("repair_missing_evidence_before_pathgraph_review")
    if readiness_status == "needs_pending_calibration" and pending.get("ready_count"):
        steps.append("run_pending_numbered_region_calibration_batch_before_pathgraph_promotion")
    if pending.get("review_blocked_count"):
        steps.append("review_non_actionable_or_ambiguous_regions_before_calibration")
    if pathgraph.get("open_detail_candidate_review"):
        steps.append("review_open_detail_transition_candidates")
    if pathgraph.get("same_screen_action_review"):
        steps.append("review_same_screen_action_candidates")
    if pathgraph.get("geometry_review_required"):
        steps.append("repair_geometry_or_collect_support_evidence")
    if pathgraph.get("blocked_non_action"):
        steps.append("keep_blocked_non_actions_out_of_pathgraph")
    if not steps:
        steps.append("manual_readiness_review_required")
    return steps


def _fusion_status(draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    direct = page_details.get("precise_understanding_fusion_status")
    if isinstance(direct, dict):
        return direct
    audit = page_details.get("pipeline_audit") if isinstance(page_details.get("pipeline_audit"), dict) else {}
    nested = audit.get("precise_understanding_fusion_status")
    if isinstance(nested, dict):
        return nested
    raise ValueError("learning draft does not contain precise_understanding_fusion_status")


def _select_draft(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("learning_draft", "best_learning_draft", "draft"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    if payload.get("contract_version") == "learning_template_draft_v1":
        return payload
    raise ValueError("source does not contain a learning draft")


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_int(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int(*values: Any) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _has_any_int(*values: Any) -> bool:
    for value in values:
        try:
            int(value)
            return True
        except (TypeError, ValueError):
            continue
    return False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a display-only precise-understanding readiness report.")
    parser.add_argument("--draft", required=True, help="Path to Learning Draft JSON with attached fusion status")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_precise_understanding_readiness(draft_path=args.draft, out_dir=args.out, json_stdout=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
