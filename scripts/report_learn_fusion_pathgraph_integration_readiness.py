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


REPORT_NAME = "learn_fusion_pathgraph_integration_readiness_report.json"


def report_learn_fusion_pathgraph_integration_readiness(
    *,
    pathgraph_candidate_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    candidate_file = _resolve_path(pathgraph_candidate_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    candidate = _read_json(candidate_file)
    validation, validation_file = _load_validation_report(candidate, candidate_file, root)
    review = load_learning_draft_review(candidate_file, project_root=root)
    candidate_review = review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
    calibration_pre_run = (
        candidate_review.get("calibration_pre_run_check")
        if isinstance(candidate_review.get("calibration_pre_run_check"), dict)
        else {}
    )
    validation_status = str(validation.get("validation_status") or candidate.get("validation_status") or "")
    failed_checks = [
        str(item.get("check_id"))
        for item in validation.get("checks", [])
        if isinstance(item, dict) and item.get("passed") is False and item.get("check_id")
    ]
    readiness = _dict(validation.get("precise_understanding_readiness_summary")) or _dict(
        _dict(validation.get("summary")).get("precise_understanding_readiness_summary")
    ) or _dict(candidate.get("precise_understanding_readiness_summary"))
    evidence_integrity = _dict(validation.get("evidence_integrity")) or _dict(
        _dict(validation.get("summary")).get("evidence_integrity")
    ) or _dict(candidate.get("evidence_integrity"))
    pending_detail_requests = _list_of_dicts(validation.get("pending_detail_observe_requests")) or _list_of_dicts(
        candidate.get("pending_detail_observe_requests")
    )

    blockers: list[str] = []
    if validation_status == "blocked_pending_calibration":
        blockers.append("pending_calibration_required")
    elif validation_status != "passed_candidate":
        blockers.append(f"candidate_validation_not_passed:{validation_status or 'unknown'}")
    if failed_checks and validation_status != "blocked_pending_calibration":
        blockers.append("candidate_validation_failed_checks")
    if evidence_integrity.get("status") in {"missing_declared_evidence", "missing", "stale_fixture"}:
        blockers.append("evidence_integrity_not_complete")
    if pending_detail_requests:
        blockers.append("pending_detail_observe_requests")
    if _is_stale_calibration_pre_run(calibration_pre_run):
        blockers.append("stale_calibration_pre_run_evidence")
    if not _safety_flags_disabled(candidate, validation):
        blockers.append("safety_flags_not_disabled")

    integration_status = _integration_status(validation_status, blockers)
    report = {
        "contract_version": "learn_fusion_pathgraph_integration_readiness_report_v1",
        "integration_readiness_status": integration_status,
        "pathgraph_candidate_path": _relative_path(candidate_file, root),
        "validation_report_path": _relative_path(validation_file, root) if validation_file is not None else None,
        "candidate_validation_status": validation_status,
        "candidate_failed_checks": failed_checks,
        "precise_understanding_readiness_summary": readiness,
        "evidence_integrity": evidence_integrity,
        "calibration_pre_run_check": calibration_pre_run,
        "ready_for_audited_pathgraph_review": integration_status == "ready_for_audited_pathgraph_review",
        "ready_for_runtime_pathgraph_promotion": False,
        "not_runtime_promotion": True,
        "next_required_steps": _next_required_steps(integration_status),
        "blockers": blockers,
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": (
            "Offline PathGraph integration readiness report for Learning Draft fusion output. "
            "It does not start models, click, fill, submit, merge, refresh, or promote Runtime PathGraph."
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


def _integration_status(validation_status: str, blockers: list[str]) -> str:
    if "stale_calibration_pre_run_evidence" in blockers:
        return "blocked_stale_pre_run_evidence"
    if validation_status == "blocked_pending_calibration":
        return "blocked_pending_calibration"
    if blockers:
        return "blocked_before_pathgraph_review"
    return "ready_for_audited_pathgraph_review"


def _next_required_steps(status: str) -> list[str]:
    if status == "blocked_pending_calibration":
        return [
            "run_approved_numbered_region_calibration_batch",
            "run_gated_post_batch_refresh",
            "rerun_pathgraph_candidate_validation",
        ]
    if status == "blocked_stale_pre_run_evidence":
        return [
            "regenerate_calibration_pre_run_check_for_current_approval_packet",
            "review_effective_pre_run_status_before_model_start",
        ]
    if status == "ready_for_audited_pathgraph_review":
        return ["human_audit_before_runtime_pathgraph_promotion"]
    return ["repair_blockers_before_pathgraph_review"]


def _is_stale_calibration_pre_run(report: dict[str, Any]) -> bool:
    if not report:
        return False
    if report.get("stale_pre_run_evidence") is True:
        return True
    effective = str(report.get("effective_pre_run_status") or "")
    return effective == "stale_pre_run_evidence"


def _safety_flags_disabled(*payloads: dict[str, Any]) -> bool:
    for payload in payloads:
        if payload.get("execute_binding_enabled") is True or payload.get("artifact_is_authorization") is True:
            return False
        if payload.get("ready_for_runtime_pathgraph_promotion") is True:
            return False
        safety = _dict(payload.get("safety"))
        if safety.get("execute_binding_enabled") is True or safety.get("artifact_is_authorization") is True:
            return False
        if _int_value(safety.get("live_clicks")) or _int_value(safety.get("real_clicks")):
            return False
        if _int_value(safety.get("live_fills")) or _int_value(safety.get("live_submits")):
            return False
    return True


def _load_validation_report(candidate: dict[str, Any], candidate_file: Path, root: Path) -> tuple[dict[str, Any], Path | None]:
    embedded = _dict(candidate.get("validation_report"))
    if embedded:
        return embedded, None
    declared = candidate.get("validation_report_path")
    if isinstance(declared, str) and declared.strip():
        declared_path = _resolve_path(declared, root)
        if declared_path.exists():
            return _read_json(declared_path), declared_path
    sibling = candidate_file.parent / "promotion_validation_report.json"
    if sibling.exists():
        return _read_json(sibling), sibling
    return {}, None


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report Learning Draft fusion readiness for audited PathGraph review.")
    parser.add_argument("--pathgraph-candidate", required=True, help="pathgraph_candidate.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = report_learn_fusion_pathgraph_integration_readiness(
        pathgraph_candidate_path=args.pathgraph_candidate,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0 if report.get("integration_readiness_status") == "ready_for_audited_pathgraph_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
