from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.runtime_artifacts import write_trace
from app.seek.application import assess_seek_application_flow_state, build_seek_apply_flow_decision
from app.seek.answer_plan import build_application_answer_plan
from app.seek.cover_letter import build_cover_letter_draft
from app.seek.extraction import extract_seek_job_cards, extract_seek_job_detail
from app.seek.learn_artifacts import action_metadata, scroll_target_for_action
from app.seek.matching import load_candidate_profile, merge_seek_job_identity, save_suitable_job_record, score_seek_job
from app.seek.profile import assess_candidate_profile_readiness
from app.seek.traversal import (
    assess_seek_job_detail_completeness,
    build_seek_mvp_accuracy_summary,
    build_seek_mvp_run_report,
    merge_seek_job_details,
)


DEFAULT_OUTPUT = Path("logs/smoke/seek_mvp_traversal_report.json")
DEFAULT_SEEK_URL = "https://nz.seek.com/"
JOB_ARCHIVE_CONTRACT = "seek_job_archive_v1"


class SeekTraversalError(RuntimeError):
    pass


def _post_json(base_url: str, endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{endpoint}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SeekTraversalError(f"{endpoint} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise SeekTraversalError(f"{endpoint} request failed: {exc}") from exc
    return json.loads(raw)


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        return data["result"]
    return data if isinstance(data, dict) else {}


def _aligned_jobs_from_traversal_steps(steps: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        card = step.get("card") if isinstance(step.get("card"), dict) else {}
        detail_read = step.get("detail_read") if isinstance(step.get("detail_read"), dict) else {}
        detail = detail_read.get("detail") if isinstance(detail_read.get("detail"), dict) else None
        match_decision = step.get("match_decision") if isinstance(step.get("match_decision"), dict) else None
        jobs.append(
            {
                "job_id": (detail or {}).get("job_id") or card.get("job_id") or step.get("job_id"),
                "card": card,
                "detail": detail,
                "match_decision": match_decision,
            }
        )
    return jobs


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_traversal_trace(report: dict[str, Any], *, app_name: str) -> str:
    trace_payload = _build_traversal_trace(report)
    return write_trace(category="seek", operation="mvp-traversal", payload=trace_payload, name_hint=app_name)


def _build_traversal_trace(report: dict[str, Any]) -> dict[str, Any]:
    steps = [step for step in report.get("traversal_steps") or [] if isinstance(step, dict)]
    return {
        "contract_version": "seek_mvp_traversal_trace_v1",
        "source_report_contract": report.get("contract_version"),
        "mode": report.get("mode"),
        "source_url": report.get("source_url"),
        "execute_clicks": report.get("execute_clicks"),
        "candidate_profile_readiness": report.get("candidate_profile_readiness"),
        "apply_entry_profile_gate": report.get("apply_entry_profile_gate"),
        "summary": {
            "jobs_seen": report.get("jobs_seen"),
            "jobs_opened": report.get("jobs_opened"),
            "jobs_fully_read": report.get("jobs_fully_read"),
            "strong_apply": report.get("strong_apply"),
            "maybe_apply": report.get("maybe_apply"),
            "need_user_review": report.get("need_user_review"),
            "skip": report.get("skip"),
            "application_flows_started": report.get("application_flows_started"),
            "cover_letters_generated": report.get("cover_letters_generated"),
            "forms_filled_until_review": report.get("forms_filled_until_review"),
            "submit_clicks": report.get("submit_clicks"),
            "final_submissions": report.get("final_submissions"),
            "elapsed_ms": report.get("elapsed_ms"),
        },
        "traversal_events": [_trace_step_summary(step) for step in steps],
        "scroll_events": list(report.get("results_list_scrolls") or []),
        "match_decisions": list(report.get("match_decisions") or []),
        "saved_jobs": list(report.get("saved_jobs") or []),
        "apply_entries": [_trace_apply_entry_summary(entry) for entry in report.get("apply_entries") or [] if isinstance(entry, dict)],
        "application_answer_plans": list(report.get("application_answer_plans") or []),
        "safe_form_fill_attempts": list(report.get("safe_form_fill_attempts") or []),
        "accuracy_summary": report.get("accuracy_summary"),
        "safety": {
            "continue_clicks": report.get("continue_clicks"),
            "submit_clicks": report.get("submit_clicks"),
            "form_fields_filled": report.get("form_fields_filled"),
            "final_submissions": report.get("final_submissions"),
            "final_submit_guard_active": report.get("final_submit_guard_active"),
        },
    }


def _trace_step_summary(step: dict[str, Any]) -> dict[str, Any]:
    card = step.get("card") if isinstance(step.get("card"), dict) else {}
    click = step.get("card_click") if isinstance(step.get("card_click"), dict) else {}
    detail_read = step.get("detail_read") if isinstance(step.get("detail_read"), dict) else {}
    detail = detail_read.get("detail") if isinstance(detail_read.get("detail"), dict) else {}
    completeness = detail_read.get("completeness") if isinstance(detail_read.get("completeness"), dict) else {}
    match = step.get("match_decision") if isinstance(step.get("match_decision"), dict) else {}
    apply_entry = step.get("apply_entry") if isinstance(step.get("apply_entry"), dict) else {}
    return {
        "index": step.get("index"),
        "job_id": step.get("job_id"),
        "card": {
            "title": card.get("title"),
            "company": card.get("company"),
            "location": card.get("location"),
            "card_bbox": card.get("card_bbox"),
            "click_point": card.get("click_point"),
        },
        "card_click": {
            "opened": click.get("opened"),
            "failure_reason": click.get("failure_reason"),
            "approved_plan_id": click.get("approved_plan_id"),
            "trace_path": (click.get("execute_response") or click.get("dry_run_response") or {}).get("trace_path")
            if isinstance(click.get("execute_response") or click.get("dry_run_response"), dict)
            else None,
            "recognition_plan_trace_path": (click.get("execute_response") or click.get("dry_run_response") or {}).get("recognition_plan_trace_path")
            if isinstance(click.get("execute_response") or click.get("dry_run_response"), dict)
            else None,
        },
        "detail_read": {
            "title": detail.get("title"),
            "company": detail.get("company"),
            "trace_paths": detail.get("trace_paths"),
            "coordinate_strategy": detail_read.get("coordinate_strategy"),
            "read_container_id": detail_read.get("read_container_id"),
            "uses_precise_relocation": detail_read.get("uses_precise_relocation"),
            "complete": completeness.get("complete"),
            "missing_evidence": completeness.get("missing_evidence"),
            "scroll_count": len(detail_read.get("scrolls") or []),
            "scrolls": detail_read.get("scrolls") or [],
        },
        "match_decision": {
            "decision": match.get("decision"),
            "score": match.get("score"),
            "fit_summary": match.get("fit_summary"),
            "recommended_next_action": match.get("recommended_next_action"),
            "reasons": match.get("reasons"),
            "positive_evidence": match.get("positive_evidence"),
            "negative_evidence": match.get("negative_evidence"),
            "saved_job_path": match.get("saved_job_path"),
        },
        "apply_entry": _trace_apply_entry_summary(apply_entry) if apply_entry else None,
        "search_restore": step.get("search_restore"),
    }


def _trace_apply_entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": entry.get("contract_version"),
        "job_id": entry.get("job_id"),
        "title": entry.get("title"),
        "company": entry.get("company"),
        "decision": entry.get("decision"),
        "eligible": entry.get("eligible"),
        "executed": entry.get("executed"),
        "status": entry.get("status"),
        "stop_reason": entry.get("stop_reason"),
        "application_flow_started": entry.get("application_flow_started"),
        "continue_clicks": entry.get("continue_clicks"),
        "submit_clicks": entry.get("submit_clicks"),
        "form_fields_filled": entry.get("form_fields_filled"),
        "final_submission_performed": entry.get("final_submission_performed"),
        "apply_click": entry.get("apply_click"),
        "pre_apply_detail_verification": entry.get("pre_apply_detail_verification"),
        "final_submit_guard": entry.get("final_submit_guard"),
        "application_flow_state": entry.get("application_flow_state"),
        "apply_flow_decision": entry.get("apply_flow_decision"),
        "final_submit_visible_blocker": entry.get("final_submit_visible_blocker"),
        "cover_letter_draft": entry.get("cover_letter_draft"),
        "application_answer_plan": entry.get("application_answer_plan"),
        "safe_form_fill_attempt": entry.get("safe_form_fill_attempt"),
        "profile_gate": entry.get("profile_gate"),
    }


def _write_job_archives(
    steps: list[dict[str, Any]],
    *,
    output_dir: str | Path | None,
    source_url: str | None,
    mode: str,
) -> list[dict[str, Any]]:
    if output_dir is None:
        return []
    archive_dir = Path(output_dir)
    archives: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        payload = _job_archive_payload(step, source_url=source_url, mode=mode)
        path = archive_dir / _job_archive_filename(step)
        _write_json(path, payload)
        step["job_archive_path"] = str(path)
        archives.append(
            {
                "index": step.get("index"),
                "job_id": payload.get("job_id"),
                "title": payload.get("title"),
                "decision": (payload.get("match_decision") or {}).get("decision")
                if isinstance(payload.get("match_decision"), dict)
                else None,
                "path": str(path),
            }
        )
    return archives


def _job_archive_payload(step: dict[str, Any], *, source_url: str | None, mode: str) -> dict[str, Any]:
    card = step.get("card") if isinstance(step.get("card"), dict) else {}
    detail_read = step.get("detail_read") if isinstance(step.get("detail_read"), dict) else {}
    detail = detail_read.get("detail") if isinstance(detail_read.get("detail"), dict) else None
    match_decision = step.get("match_decision") if isinstance(step.get("match_decision"), dict) else None
    apply_entry = step.get("apply_entry") if isinstance(step.get("apply_entry"), dict) else None
    click = step.get("card_click") if isinstance(step.get("card_click"), dict) else {}
    completeness = detail_read.get("completeness") if isinstance(detail_read.get("completeness"), dict) else {}
    title = (detail or {}).get("title") or card.get("title") or step.get("title")
    company = (detail or {}).get("company") or card.get("company")
    return {
        "contract_version": JOB_ARCHIVE_CONTRACT,
        "source_url": source_url,
        "mode": mode,
        "index": step.get("index"),
        "job_id": (detail or {}).get("job_id") or card.get("job_id") or step.get("job_id"),
        "title": title,
        "company": company,
        "card": card,
        "card_click": {
            "opened": click.get("opened"),
            "failure_reason": click.get("failure_reason"),
            "approved_plan_id": click.get("approved_plan_id"),
            "dry_run_trace_path": (click.get("dry_run_response") or {}).get("trace_path")
            if isinstance(click.get("dry_run_response"), dict)
            else None,
            "execute_trace_path": (click.get("execute_response") or {}).get("trace_path")
            if isinstance(click.get("execute_response"), dict)
            else None,
            "recognition_plan_trace_path": (
                (click.get("execute_response") or click.get("dry_run_response") or {}).get("recognition_plan_trace_path")
                if isinstance(click.get("execute_response") or click.get("dry_run_response"), dict)
                else None
            ),
            "post_click_layout": click.get("post_click_layout"),
        },
        "detail_read": {
            "detail": detail,
            "complete": completeness.get("complete"),
            "missing_evidence": completeness.get("missing_evidence") or [],
            "coordinate_strategy": detail_read.get("coordinate_strategy"),
            "read_container_id": detail_read.get("read_container_id"),
            "uses_precise_relocation": detail_read.get("uses_precise_relocation"),
            "scroll_count": len(detail_read.get("scrolls") or []),
            "scrolls": detail_read.get("scrolls") or [],
        },
        "match_decision": match_decision,
        "apply_entry": _trace_apply_entry_summary(apply_entry) if apply_entry else None,
        "safety": {
            "submit_clicks": int((apply_entry or {}).get("submit_clicks") or 0) if isinstance(apply_entry, dict) else 0,
            "final_submission_performed": bool((apply_entry or {}).get("final_submission_performed"))
            if isinstance(apply_entry, dict)
            else False,
        },
        "search_restore": step.get("search_restore"),
    }


def _job_archive_filename(step: dict[str, Any]) -> str:
    index = int(step.get("index") or 0)
    card = step.get("card") if isinstance(step.get("card"), dict) else {}
    key_payload = {
        "index": index,
        "job_id": step.get("job_id") or card.get("job_id"),
        "title": step.get("title") or card.get("title"),
        "company": card.get("company"),
    }
    digest = hashlib.sha1(json.dumps(key_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return f"job_{index:03d}_{digest}.json"


def _apply_flow_summary(apply_entries: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [
        entry.get("apply_flow_decision")
        for entry in apply_entries
        if isinstance(entry.get("apply_flow_decision"), dict)
    ]
    state_types = [str(decision.get("state_type") or "") for decision in decisions]
    return {
        "contract_version": "seek_apply_flow_summary_v1",
        "application_flows_started": sum(1 for entry in apply_entries if entry.get("application_flow_started") is True),
        "seek_internal_flows": sum(
            1 for state_type in state_types if state_type.startswith("seek_internal_") and not state_type.endswith("_blocked")
        ),
        "third_party_ats_deferred": state_types.count("third_party_ats_deferred"),
        "blocked_flows": sum(1 for decision in decisions if decision.get("decision") == "stop"),
        "cover_letters_generated": sum(1 for entry in apply_entries if entry.get("cover_letter_generated") is True),
        "answer_plans_generated": sum(1 for entry in apply_entries if entry.get("application_answer_plan_generated") is True),
        "safe_fill_attempts": sum(1 for entry in apply_entries if isinstance(entry.get("safe_form_fill_attempt"), dict)),
        "forms_filled": sum(int(entry.get("form_fields_filled") or 0) for entry in apply_entries),
        "submit_clicks": sum(int(entry.get("submit_clicks") or 0) for entry in apply_entries),
        "final_submissions": sum(1 for entry in apply_entries if entry.get("final_submission_performed") is True),
    }


def _seek_job_seeded_candidate(job: dict[str, Any], *, learned_artifact: dict[str, Any] | None = None) -> dict[str, Any] | None:
    bbox = job.get("card_bbox") if isinstance(job.get("card_bbox"), dict) else None
    click_point = job.get("click_point") if isinstance(job.get("click_point"), dict) else None
    if not bbox and not click_point:
        return None
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    label = " | ".join(part for part in [title, company] if part) or str(job.get("job_id") or "SEEK job card")
    evidence = job.get("evidence") if isinstance(job.get("evidence"), dict) else {}
    evidence_texts = evidence.get("texts") if isinstance(evidence.get("texts"), list) else []
    seed = {
        "contract_version": "seeded_candidate_v1",
        "source": "seek_job_card_v1",
        "candidate_id": str(job.get("job_id") or hashlib.sha256(label.encode("utf-8")).hexdigest()[:12]),
        "role": "button",
        "label": label,
        "title": title,
        "company": company,
        "container_id": "seek:results_list",
        "bbox": bbox,
        "click_point": click_point,
        "evidence_texts": evidence_texts[:12],
        "risk_class": "safe_click_allowed",
        "expected_effect": "open SEEK job detail pane for the selected result",
        "safety": {
            "require_point_inside_seed_bbox": True,
            "require_post_click_detail_verification": True,
            "disallow_final_submit": True,
        },
    }
    learned_metadata = action_metadata(learned_artifact, "open_job_card")
    if learned_metadata.get("candidate_constraints"):
        seed["candidate_constraints"] = learned_metadata["candidate_constraints"]
    if learned_metadata.get("verification_policy"):
        seed["verification_policy"] = learned_metadata["verification_policy"]
    return seed


def _open_seek(base_url: str, *, url: str, app_name: str, timeout: float) -> dict[str, Any]:
    return _post_json(
        base_url,
        "/apps/open",
        {
            "app_id": app_name,
            "url": url,
            "bind_after_open": True,
            "wait_seconds": 2.0,
        },
        timeout,
    )


def _resize_bound_window(
    base_url: str,
    *,
    width: int | None,
    height: int | None,
    timeout: float,
) -> dict[str, Any] | None:
    if not width or not height:
        return None
    return _post_json(
        base_url,
        "/session/resize_bound_window",
        {"width": int(width), "height": int(height), "left": 0, "top": 0, "focus": True},
        timeout,
    )


def _observe(base_url: str, *, app_name: str, state_hint: str, timeout: float) -> dict[str, Any]:
    response = _post_json(
        base_url,
        "/vision/observe_screen",
        {
            "task": "observe_screen",
            "app_name": app_name,
            "state_hint": state_hint,
            "provider_mode": "local_understanding",
            "capture_live": True,
            "agent_mode": "execute",
            "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
        },
        timeout,
    )
    if response.get("success") is not True:
        raise SeekTraversalError(f"observe_screen failed: {response.get('error') or response.get('message')}")
    return _result_payload(response)


def _roi_bbox_payload(bbox: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(bbox, dict):
        return None
    width = bbox.get("width", bbox.get("w"))
    height = bbox.get("height", bbox.get("h"))
    if width is None or height is None:
        return None
    return {
        "x": int(bbox.get("x") or 0),
        "y": int(bbox.get("y") or 0),
        "width": int(width),
        "height": int(height),
    }


def _execute_job_card(
    base_url: str,
    *,
    app_name: str,
    job: dict[str, Any],
    execute_clicks: bool,
    timeout: float,
    learned_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = job.get("title") or "the selected job result"
    company = job.get("company")
    goal = f"Click the SEEK job result card titled {title}"
    if company:
        goal += f" at {company}"
    seeded_candidate = _seek_job_seeded_candidate(job, learned_artifact=learned_artifact)
    metadata = action_metadata(learned_artifact, "open_job_card")
    if seeded_candidate:
        metadata["seeded_candidate"] = seeded_candidate
    dry_response = _post_json(
        base_url,
        "/action/execute_recognition_plan",
        {
            "agent_mode": "execute",
            "goal": goal,
            "app_name": app_name,
            "state_hint": "SEEK search results list",
            "capture_live": True,
            "dry_run": True,
            "enable_post_click_verification": True,
            "metadata": metadata,
            "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
        },
        timeout,
    )
    dry_result = _result_payload(dry_response)
    approved_plan_id = dry_result.get("approved_plan_id") or (dry_result.get("agent_step_result") or {}).get("approved_plan_id")
    summary = {
        "goal": goal,
        "dry_run_response": _compact_action_response(dry_response),
        "executed": False,
        "execute_response": None,
        "approved_plan_id": approved_plan_id,
        "opened": False,
    }
    if dry_response.get("success") is not True or not approved_plan_id:
        summary["failure_reason"] = "dry_run_not_approved"
        return summary
    if not execute_clicks:
        summary["failure_reason"] = "execute_clicks_disabled"
        return summary
    execute_response = _post_json(
        base_url,
        "/action/execute_recognition_plan",
        {
            "agent_mode": "execute",
            "goal": goal,
            "app_name": app_name,
            "capture_live": True,
            "dry_run": False,
            "approved_plan_id": approved_plan_id,
            "enable_post_click_verification": True,
            "metadata": metadata,
            "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
        },
        timeout,
    )
    summary["executed"] = True
    summary["execute_response"] = _compact_action_response(execute_response)
    if execute_response.get("success") is not True:
        summary["opened"] = False
        summary["failure_reason"] = "execute_plan_failed"
        return summary
    post_click_layout = _verify_post_click_job_detail(base_url, app_name=app_name, job=job, timeout=timeout)
    summary["post_click_layout"] = post_click_layout
    summary["opened"] = post_click_layout.get("ok") is True
    if not summary["opened"]:
        summary["failure_reason"] = "post_click_layout_drift"
    return summary


def _reset_seek_job_detail_to_top(
    base_url: str,
    *,
    timeout: float,
    learned_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    learned_scroll = scroll_target_for_action(
        learned_artifact,
        "read_detail",
        default_pane="job_detail",
        default_container_id="seek:job_detail",
    )
    scroll_request = {
        "contract_version": "scroll_request_v2",
        "scroll_scope": "container",
        "target_pane": learned_scroll["target_pane"],
        "target_container_id": learned_scroll["target_container_id"],
        "direction": "up",
        "wheel_clicks": 8,
        "reason": "reset_seek_job_detail_before_next_card_click",
        "missing_evidence": ["detail_header_must_be_visible_for_post_click_title_check"],
        "expected_effect": {
            "target_container_content_should_change": True,
            "same_semantic_page_should_remain": True,
            "non_target_panes_should_remain_mostly_stable": True,
        },
        "dry_run": False,
        "enable_verification": True,
    }
    response = _post_json(base_url, "/action/scroll", scroll_request, timeout)
    result = _result_payload(response)
    precondition = result.get("precondition_decision") if isinstance(result.get("precondition_decision"), dict) else {}
    resolved_container_id = result.get("target_container_id") or scroll_request["target_container_id"]
    wrong_scope_detected = resolved_container_id != "seek:job_detail"
    return {
        "attempted": True,
        "success": response.get("success") is True,
        "reason": scroll_request["reason"],
        "trace_path": result.get("trace_path"),
        "scroll_trace_path": result.get("trace_path"),
        "contract_version": result.get("contract_version"),
        "scroll_scope": result.get("scroll_scope") or scroll_request["scroll_scope"],
        "target_pane": result.get("target_pane") or scroll_request["target_pane"],
        "target_container_id": resolved_container_id,
        "direction": result.get("direction") or scroll_request["direction"],
        "wheel_clicks": result.get("wheel_clicks") or scroll_request["wheel_clicks"],
        "learned_artifact_source": learned_scroll.get("source"),
        "scroll_precondition_allowed": precondition.get("allowed")
        if "allowed" in precondition
        else precondition.get("decision") == "ALLOW",
        "wrong_scope_detected": wrong_scope_detected,
        "reset_verified": response.get("success") is True and not wrong_scope_detected,
        "precondition_decision": precondition,
        "effect_validation": result.get("scroll_effect_validation"),
        "raw_message": response.get("message"),
        "raw_error": response.get("error"),
    }


def _execute_apply_entry(
    base_url: str,
    *,
    app_name: str,
    job: dict[str, Any],
    detail: dict[str, Any],
    match_decision: dict[str, Any],
    candidate_profile: dict[str, Any] | None,
    execute_clicks: bool,
    timeout: float,
    allow_maybe_apply: bool = False,
    fill_safe_fields: bool = False,
    max_safe_fields_to_fill: int = 1,
    allow_cover_letter_fill: bool = False,
) -> dict[str, Any]:
    detail = merge_seek_job_identity(job, detail)
    decision = str(match_decision.get("decision") or "")
    allowed_decisions = {"strong_apply"} | ({"maybe_apply"} if allow_maybe_apply else set())
    summary: dict[str, Any] = {
        "contract_version": "seek_apply_entry_attempt_v1",
        "job_id": match_decision.get("job_id") or detail.get("job_id") or job.get("job_id"),
        "title": detail.get("title") or job.get("title"),
        "company": detail.get("company") or job.get("company"),
        "decision": decision,
        "eligible": decision in allowed_decisions,
        "executed": False,
        "application_flow_started": False,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "form_fields_filled": 0,
        "final_submission_performed": False,
        "apply_entry_semantics": {
            "apply_click_is_final_submit": False,
            "apply_click_effect": "opens_application_form_or_external_application_flow",
            "true_final_submit_policy": "blocked_until_explicit_user_review",
        },
        "apply_click": {
            "container_id": "seek:job_detail",
            "label": (detail.get("apply_button_state") or {}).get("label") if isinstance(detail.get("apply_button_state"), dict) else None,
            "click_point": (detail.get("apply_button_state") or {}).get("click_point") if isinstance(detail.get("apply_button_state"), dict) else None,
        },
        "stop_reason": None,
    }
    if decision not in allowed_decisions:
        summary["status"] = "skipped"
        summary["stop_reason"] = "decision_not_eligible_for_apply_entry"
        return summary

    apply_state = detail.get("apply_button_state") if isinstance(detail.get("apply_button_state"), dict) else {}
    if apply_state.get("visible") is not True:
        summary["status"] = "blocked_need_user_or_gpt_decision"
        summary["stop_reason"] = "apply_or_quick_apply_not_visible"
        return summary

    pre_apply_verification = _verify_pre_apply_job_detail(
        base_url,
        app_name=app_name,
        job=job,
        detail=detail,
        timeout=timeout,
    )
    summary["pre_apply_detail_verification"] = pre_apply_verification
    if pre_apply_verification.get("ok") is not True:
        summary["status"] = "blocked_need_user_or_gpt_decision"
        summary["stop_reason"] = "pre_apply_detail_verification_failed"
        return summary

    title = detail.get("title") or job.get("title") or pre_apply_verification.get("observed_title") or "the selected job"
    company = pre_apply_verification.get("observed_company") or detail.get("company") or job.get("company")
    goal = f"Click the Apply or Quick Apply button in the right SEEK job detail pane for {title}"
    if company:
        goal += f" at {company}"
    goal += ". Do not click Submit, Send application, or Complete application."
    summary["goal"] = goal

    dry_response = _post_json(
        base_url,
        "/action/execute_recognition_plan",
        {
            "agent_mode": "execute",
            "goal": goal,
            "app_name": app_name,
            "state_hint": "SEEK opened job detail pane with Apply or Quick Apply visible",
            "capture_live": True,
            "dry_run": True,
            "enable_post_click_verification": True,
            "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
            "metadata": {
                "seek_apply_entry": True,
                "job_id": summary["job_id"],
                "forbid_final_submit": True,
                "required_container_id": "seek:job_detail",
            },
        },
        timeout,
    )
    dry_result = _result_payload(dry_response)
    approved_plan_id = dry_result.get("approved_plan_id") or (dry_result.get("agent_step_result") or {}).get("approved_plan_id")
    summary["dry_run_response"] = _compact_action_response(dry_response)
    summary["final_submit_guard"] = summary["dry_run_response"].get("final_submit_guard")
    summary["approved_plan_id"] = approved_plan_id
    if dry_response.get("success") is not True or not approved_plan_id:
        summary["status"] = "blocked_need_user_or_gpt_decision"
        summary["stop_reason"] = "apply_entry_dry_run_not_approved"
        return summary
    if not execute_clicks:
        summary["status"] = "dry_run_ready"
        summary["stop_reason"] = "execute_clicks_disabled"
        return summary

    execute_response = _post_json(
        base_url,
        "/action/execute_recognition_plan",
        {
            "agent_mode": "execute",
            "goal": goal,
            "app_name": app_name,
            "capture_live": True,
            "dry_run": False,
            "approved_plan_id": approved_plan_id,
            "enable_post_click_verification": True,
            "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
            "metadata": {
                "seek_apply_entry": True,
                "job_id": summary["job_id"],
                "forbid_final_submit": True,
                "required_container_id": "seek:job_detail",
            },
        },
        timeout,
    )
    summary["executed"] = True
    summary["execute_response"] = _compact_action_response(execute_response)
    summary["final_submit_guard"] = summary["execute_response"].get("final_submit_guard") or summary.get("final_submit_guard")
    if execute_response.get("success") is not True:
        summary["status"] = "blocked_need_user_or_gpt_decision"
        summary["stop_reason"] = "apply_entry_execute_plan_failed"
        return summary

    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK application flow after Apply or Quick Apply click; stop before form fill or final submit",
        timeout=timeout,
    )
    flow_state = assess_seek_application_flow_state(observation, source_job={**job, **detail})
    apply_flow_decision = build_seek_apply_flow_decision(flow_state)
    summary["application_flow_state"] = flow_state
    summary["apply_flow_decision"] = apply_flow_decision
    summary["final_submit_visible_blocker"] = flow_state.get("final_submit_visible_blocker")
    summary["application_flow_started"] = bool(flow_state.get("application_flow_started"))
    if apply_flow_decision.get("decision") != "continue_read_only":
        summary["status"] = "blocked_need_user_or_gpt_decision"
        summary["stop_reason"] = apply_flow_decision.get("reason") or flow_state.get("stop_reason")
        summary["cover_letter_generated"] = False
        summary["application_answer_plan_generated"] = False
        summary["form_fields_filled"] = 0
        summary["forms_filled_until_review"] = 0
        summary["final_submission_performed"] = False
        return summary

    cover_letter_draft = build_cover_letter_draft(
        profile=candidate_profile,
        detail=detail,
        match_decision=match_decision,
        application_flow_state=flow_state,
        allow_maybe_apply=allow_maybe_apply,
    )
    answer_plan = build_application_answer_plan(
        profile=candidate_profile,
        application_flow_state=flow_state,
        cover_letter_draft=cover_letter_draft,
    )
    safe_fill_attempt = _safe_form_fill_attempt(
        base_url,
        app_name=app_name,
        answer_plan=answer_plan,
        candidate_profile=candidate_profile,
        cover_letter_draft=cover_letter_draft,
        execute_fill=fill_safe_fields,
        max_safe_fields_to_fill=max_safe_fields_to_fill,
        allow_cover_letter_fill=allow_cover_letter_fill,
        timeout=timeout,
    )
    summary["status"] = flow_state["status"]
    summary["cover_letter_draft"] = cover_letter_draft
    summary["cover_letter_generated"] = cover_letter_draft.get("status") == "draft_only_not_pasted"
    summary["application_answer_plan"] = answer_plan
    summary["application_answer_plan_generated"] = answer_plan.get("status") in {"planned_only_not_filled", "blocked_final_submit_visible"}
    summary["safe_form_fill_attempt"] = safe_fill_attempt
    summary["form_fields_filled"] = int(safe_fill_attempt.get("fields_filled") or 0)
    summary["forms_filled_until_review"] = 1 if safe_fill_attempt.get("status") == "filled_until_review" else 0
    summary["stop_reason"] = safe_fill_attempt.get("stop_reason") or flow_state.get("stop_reason")
    summary["final_submission_performed"] = False
    return summary


def _apply_entry_profile_gate(
    *,
    apply_entry: bool,
    fill_safe_fields: bool,
    profile_readiness: dict[str, Any],
) -> dict[str, Any]:
    enabled = bool(apply_entry or fill_safe_fields)
    ready = profile_readiness.get("live_smoke_ready") is True
    decision = str(profile_readiness.get("decision") or "")
    return {
        "contract_version": "seek_apply_entry_profile_gate_v1",
        "enabled": enabled,
        "allowed": (not enabled) or ready,
        "profile_decision": decision,
        "live_smoke_ready": ready,
        "missing_requirements": list(profile_readiness.get("missing_requirements") or []),
        "reason": "profile_ready_for_apply_entry"
        if ready
        else ("apply_entry_disabled" if not enabled else "apply_entry_requires_real_candidate_profile"),
    }


def _blocked_apply_entry_for_profile_gate(
    *,
    job: dict[str, Any],
    detail: dict[str, Any],
    match_decision: dict[str, Any],
    profile_gate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": "seek_apply_entry_attempt_v1",
        "job_id": match_decision.get("job_id") or detail.get("job_id") or job.get("job_id"),
        "title": detail.get("title") or job.get("title"),
        "company": detail.get("company") or job.get("company"),
        "decision": match_decision.get("decision"),
        "eligible": False,
        "executed": False,
        "application_flow_started": False,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "form_fields_filled": 0,
        "final_submission_performed": False,
        "apply_entry_semantics": {
            "apply_click_is_final_submit": False,
            "apply_click_effect": "would_open_application_form_or_external_application_flow",
            "true_final_submit_policy": "blocked_until_explicit_user_review",
        },
        "status": "blocked_need_real_candidate_profile",
        "stop_reason": profile_gate.get("reason") or "apply_entry_requires_real_candidate_profile",
        "profile_gate": profile_gate,
        "apply_click": {
            "container_id": "seek:job_detail",
            "label": (detail.get("apply_button_state") or {}).get("label")
            if isinstance(detail.get("apply_button_state"), dict)
            else None,
            "click_point": (detail.get("apply_button_state") or {}).get("click_point")
            if isinstance(detail.get("apply_button_state"), dict)
            else None,
        },
    }


def _verify_pre_apply_job_detail(
    base_url: str,
    *,
    app_name: str,
    job: dict[str, Any],
    detail: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK job detail pane immediately before Apply or Quick Apply click",
        timeout=timeout,
    )
    observed = extract_seek_job_detail(observation, goal="verify current SEEK job detail before Apply click")
    apply_state = observed.get("apply_button_state") if isinstance(observed.get("apply_button_state"), dict) else {}
    expected_title = detail.get("title") or job.get("title")
    expected_company = detail.get("company") or job.get("company")
    observed_title = observed.get("title")
    observed_company = observed.get("company")
    title_matches = _titles_match(expected_title, observed_title)
    observed_company_reliable = _observed_seek_company_is_reliable(observed_company)
    company_matches = (
        _titles_match(expected_company, observed_company)
        if expected_company and observed_company_reliable
        else True
    )
    apply_visible = apply_state.get("visible") is True
    return {
        "contract_version": "pre_apply_detail_verification_v1",
        "ok": bool(title_matches and company_matches and apply_visible),
        "trace_path": observation.get("trace_path"),
        "expected_title": expected_title,
        "observed_title": observed_title,
        "title_matches": title_matches,
        "expected_company": expected_company,
        "observed_company": observed_company,
        "observed_company_reliable": observed_company_reliable,
        "company_matches": company_matches,
        "apply_visible": apply_visible,
        "apply_label": apply_state.get("label"),
        "failure_reasons": [
            reason
            for reason, failed in [
                ("detail_title_mismatch", not title_matches),
                ("detail_company_mismatch", not company_matches),
                ("apply_or_quick_apply_not_visible", not apply_visible),
            ]
            if failed
        ],
    }


def _observed_seek_company_is_reliable(company: Any) -> bool:
    text = re.sub(r"\s+", " ", str(company or "")).strip()
    normalized = re.sub(r"[^a-z0-9]+", "", text.lower())
    if not normalized:
        return False
    if normalized in {"x", "close", "dismiss", "more", "share"}:
        return False
    if len(normalized) == 1 and normalized.isalpha():
        return False
    return True


def _verify_post_click_job_detail(
    base_url: str,
    *,
    app_name: str,
    job: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK job detail pane after card click",
        timeout=timeout,
    )
    cards_payload = extract_seek_job_cards(observation, goal="verify SEEK results list still visible after job click")
    detail = extract_seek_job_detail(observation, goal="verify SEEK opened job detail after card click")
    apply_state = detail.get("apply_button_state") if isinstance(detail.get("apply_button_state"), dict) else {}
    save_state = detail.get("save_button_state") if isinstance(detail.get("save_button_state"), dict) else {}
    has_detail_title = bool(detail.get("title"))
    title_matches = _titles_match(job.get("title"), detail.get("title"))
    evidence_quality = _detail_title_evidence_quality(detail)
    title_source = "detail_body" if evidence_quality == "body_fragment_candidate" else (
        "detail_header" if evidence_quality == "header_title_candidate" else "unknown"
    )
    has_detail_action = apply_state.get("visible") is True or save_state.get("visible") is True
    failure_reasons = [
        reason
        for reason, failed in [
            ("missing_results_list_cards", not cards_payload.get("jobs")),
            ("missing_detail_title", not has_detail_title),
            ("detail_title_mismatch", has_detail_title and not title_matches),
        ]
        if failed
    ]
    return {
        "contract_version": "seek_post_click_layout_check_v1",
        "ok": bool(cards_payload.get("jobs")) and has_detail_title and title_matches,
        "trace_path": observation.get("trace_path"),
        "cards_seen": len(cards_payload.get("jobs") or []),
        "target_title": job.get("title"),
        "detail_title": detail.get("title"),
        "title_matches": title_matches,
        "apply_visible": apply_state.get("visible") is True,
        "save_visible": save_state.get("visible") is True,
        "post_click_detail_header": {
            "header_visible": title_source == "detail_header",
            "title_extraction_source": title_source,
            "title_extraction_confidence": 0.9 if title_source == "detail_header" else 0.35,
            "title_candidate": detail.get("title"),
            "title_candidate_rejected_as_body_fragment": title_source == "detail_body",
            "evidence_quality": evidence_quality,
        },
        "failure_classification": {
            "failure_reason": failure_reasons[0] if failure_reasons else None,
            "failure_group": "post_click_verification_failed" if failure_reasons else None,
            "is_layout_drift": bool(failure_reasons),
            "evidence_quality": evidence_quality,
        },
        "failure_reasons": failure_reasons,
    }


def _detail_title_evidence_quality(detail: dict[str, Any]) -> str:
    title = str(detail.get("title") or "").strip()
    if not title:
        return "no_title_candidate"
    texts = []
    evidence = detail.get("evidence") if isinstance(detail.get("evidence"), dict) else {}
    if isinstance(evidence.get("texts"), list):
        texts = [str(item or "") for item in evidence.get("texts") or []]
    try:
        title_index = texts.index(title)
    except ValueError:
        title_index = -1
    normalized = _text_key(title)
    body_indicators = {
        "lookingfor",
        "responsibilities",
        "abouttherole",
        "opportunity",
        "you will",
        "programand",
        "islooking",
    }
    if title_index >= 9:
        return "body_fragment_candidate"
    if len(title) > 80:
        return "body_fragment_candidate"
    if any(term.replace(" ", "") in normalized for term in body_indicators):
        return "body_fragment_candidate"
    return "header_title_candidate"


def _titles_match(expected: Any, observed: Any) -> bool:
    expected_key = _text_key(expected)
    observed_key = _text_key(observed)
    if not expected_key or not observed_key:
        return False
    if min(len(expected_key), len(observed_key)) < 4:
        return False
    if expected_key == observed_key:
        return True
    shorter, longer = sorted([expected_key, observed_key], key=len)
    if len(shorter) < 8:
        return False
    if len(shorter) / max(1, len(longer)) < 0.5:
        return False
    return shorter in longer


def _text_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def _read_detail_until_complete(
    base_url: str,
    *,
    app_name: str,
    max_scrolls: int,
    timeout: float,
    learned_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    slices: list[dict[str, Any]] = []
    scrolls: list[dict[str, Any]] = []
    completeness: dict[str, Any] | None = None
    last_detail_fingerprint: str | None = None
    repeated_detail_observations = 0
    for scroll_count in range(max_scrolls + 1):
        observation = _observe(
            base_url,
            app_name=app_name,
            state_hint="SEEK opened job detail pane",
            timeout=timeout,
        )
        detail = extract_seek_job_detail(observation, goal="read the opened SEEK job detail")
        detail["trace_paths"] = [path for path in [observation.get("trace_path")] if path]
        detail["detail_scroll_history"] = scrolls.copy()
        detail_fingerprint = _detail_observation_fingerprint(detail)
        if last_detail_fingerprint is not None and detail_fingerprint == last_detail_fingerprint:
            repeated_detail_observations += 1
        else:
            repeated_detail_observations = 0
        last_detail_fingerprint = detail_fingerprint
        slices.append(detail)
        merged = merge_seek_job_details(slices)
        if scroll_count > 0 and repeated_detail_observations >= 2:
            merged["detail_bottom_reached"] = True
            for item in reversed(scrolls):
                item["bottom_reached"] = True
                item["adaptive_stop_reason"] = "repeated_detail_observation_after_scroll"
                break
        completeness = assess_seek_job_detail_completeness(
            merged,
            scroll_count=scroll_count,
            max_scrolls=max_scrolls,
            require_bottom=True,
        )
        if scroll_count > 0 and repeated_detail_observations >= 1:
            for item in reversed(scrolls):
                item["bottom_reached"] = True
                item["right_detail_no_progress_after_scroll"] = True
                item["adaptive_stop_reason"] = "right_detail_content_unchanged_after_scroll"
                break
            completeness = {
                **completeness,
                "complete": False if completeness.get("missing_evidence") else True,
                "should_scroll": False,
                "stop_reason": "right_detail_no_progress_after_scroll",
                "bottom_reached": True,
                "right_detail_no_progress_after_scroll": True,
            }
            return {
                "detail": {**merged, "detail_bottom_reached": True},
                "detail_slices": slices,
                "completeness": completeness,
                "scrolls": scrolls,
                "coordinate_strategy": "fixed_seek_job_detail_container_after_card_click",
                "read_container_id": "seek:job_detail",
                "uses_precise_relocation": False,
            }
        if not completeness["should_scroll"]:
            return {
                "detail": merged,
                "detail_slices": slices,
                "completeness": completeness,
                "scrolls": scrolls,
                "coordinate_strategy": "fixed_seek_job_detail_container_after_card_click",
                "read_container_id": "seek:job_detail",
                "uses_precise_relocation": False,
            }
        learned_scroll = scroll_target_for_action(
            learned_artifact,
            "read_detail",
            default_pane="job_detail",
            default_container_id="seek:job_detail",
        )
        scroll_request = {
            **(completeness["next_scroll_request"] or {}),
            "target_pane": learned_scroll["target_pane"],
            "target_container_id": learned_scroll["target_container_id"],
            "dry_run": False,
            "enable_verification": True,
        }
        detail_container = merged.get("detail_container") if isinstance(merged.get("detail_container"), dict) else {}
        detail_container_bbox = detail_container.get("bbox") if isinstance(detail_container.get("bbox"), dict) else None
        if detail_container_bbox:
            scroll_request["container_bbox"] = _roi_bbox_payload(detail_container_bbox)
        scroll_request["wheel_clicks"] = _adaptive_wheel_clicks(
            base=int(scroll_request.get("wheel_clicks") or 4),
            repeated_observations=max(repeated_detail_observations, scroll_count),
        )
        scroll_response = _post_json(base_url, "/action/scroll", scroll_request, timeout)
        scroll_result = _result_payload(scroll_response)
        scrolls.append(
            {
                "success": scroll_response.get("success") is True,
                "trace_path": scroll_result.get("trace_path"),
                "contract_version": scroll_result.get("contract_version"),
                "scroll_scope": scroll_result.get("scroll_scope") or scroll_request.get("scroll_scope"),
                "target_pane": scroll_result.get("target_pane") or scroll_request.get("target_pane"),
                "target_container_id": scroll_result.get("target_container_id") or scroll_request.get("target_container_id"),
                "learned_artifact_source": learned_scroll.get("source"),
                "precondition_decision": scroll_result.get("precondition_decision"),
                "effect_validation": scroll_result.get("scroll_effect_validation"),
                "bottom_probe": "detail_bottom" in (completeness.get("missing_evidence") or []),
                "bottom_reached": _scroll_reached_bottom(scroll_result.get("scroll_effect_validation")),
                "wheel_clicks": scroll_result.get("wheel_clicks") or scroll_request.get("wheel_clicks"),
                "adaptive_repeated_observations": repeated_detail_observations,
                "missing_evidence": completeness.get("missing_evidence"),
            }
        )
        if scroll_response.get("success") is not True:
            break
    merged = merge_seek_job_details(slices)
    return {
        "detail": merged,
        "detail_slices": slices,
        "completeness": completeness
        or assess_seek_job_detail_completeness(
            merged,
            scroll_count=max_scrolls,
            max_scrolls=max_scrolls,
            require_bottom=True,
        ),
        "scrolls": scrolls,
        "coordinate_strategy": "fixed_seek_job_detail_container_after_card_click",
        "read_container_id": "seek:job_detail",
        "uses_precise_relocation": False,
    }


def _detail_observation_fingerprint(detail: dict[str, Any]) -> str:
    if not isinstance(detail, dict):
        return ""
    texts: list[str] = []
    for key in ("title", "company", "location", "work_type"):
        value = detail.get(key)
        if value:
            texts.append(str(value))
    for key in ("requirements", "responsibilities", "benefits"):
        values = detail.get(key)
        if isinstance(values, list):
            texts.extend(str(item) for item in values[:5])
    sections = detail.get("description_sections")
    if isinstance(sections, list):
        for section in sections[:8]:
            if isinstance(section, dict):
                texts.append(str(section.get("heading") or ""))
                body = section.get("body") or section.get("text") or section.get("content")
                if isinstance(body, list):
                    texts.extend(str(item) for item in body[:4])
                elif body:
                    texts.append(str(body))
    normalized = [_job_seen_key_part(text) for text in texts if str(text).strip()]
    return "|".join(item for item in normalized if item)


def _adaptive_wheel_clicks(*, base: int, repeated_observations: int, maximum: int = 12) -> int:
    return min(maximum, max(1, int(base)) + max(0, int(repeated_observations)) * 4)


def _scroll_reached_bottom(effect_validation: Any) -> bool:
    if not isinstance(effect_validation, dict):
        return False
    if effect_validation.get("bottom_reached") is True:
        return True
    if effect_validation.get("no_effect_detected") is True:
        return True
    if effect_validation.get("status") in {"no_effect", "at_boundary", "bottom_reached"}:
        return True
    if effect_validation.get("target_container_content_changed") is False:
        return True
    return False


def _scroll_results_list(
    base_url: str,
    *,
    timeout: float,
    missing_evidence: list[str] | None = None,
    learned_artifact: dict[str, Any] | None = None,
    container_bbox: dict[str, Any] | None = None,
    wheel_clicks: int = 4,
) -> dict[str, Any]:
    learned_scroll = scroll_target_for_action(
        learned_artifact,
        "load_more_results",
        default_pane="results_list",
        default_container_id="seek:results_list",
    )
    request_container_bbox = _roi_bbox_payload(container_bbox)
    response = _post_json(
        base_url,
        "/action/scroll",
        {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "container",
            "target_pane": learned_scroll["target_pane"],
            "target_container_id": learned_scroll["target_container_id"],
            "container_bbox": request_container_bbox,
            "direction": "down",
            "wheel_clicks": int(wheel_clicks),
            "reason": "seek_results_list_need_more_jobs",
            "missing_evidence": missing_evidence or ["more_job_cards"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
                "non_target_panes_should_remain_mostly_stable": True,
            },
            "dry_run": False,
            "enable_verification": True,
        },
        timeout,
    )
    result = _result_payload(response)
    return {
        "success": response.get("success") is True,
        "trace_path": result.get("trace_path"),
        "contract_version": result.get("contract_version"),
        "scroll_scope": result.get("scroll_scope") or "container",
        "target_pane": result.get("target_pane") or learned_scroll["target_pane"],
        "target_container_id": result.get("target_container_id") or learned_scroll["target_container_id"],
        "container_bbox": result.get("container_bbox") or request_container_bbox,
        "learned_artifact_source": learned_scroll.get("source"),
        "precondition_decision": result.get("precondition_decision"),
        "effect_validation": result.get("scroll_effect_validation"),
        "wheel_clicks": result.get("wheel_clicks") or int(wheel_clicks),
        "raw_message": response.get("message"),
        "raw_error": response.get("error"),
    }


def _job_seen_key(job: dict[str, Any]) -> str:
    parts = [job.get("title"), job.get("company"), job.get("location")]
    basis = "|".join(_job_seen_key_part(item) for item in parts if item)
    return basis or str(job.get("job_id") or "")


def _job_seen_key_part(value: Any) -> str:
    raw = str(value or "").casefold()
    raw = re.sub(
        r"\b(senior|lead|principal|staff|junior)(software|backend|frontend|fullstack|devops|data|systems|integrations|engineer|developer)",
        r"\1 \2",
        raw,
    )
    raw = re.sub(r"\b(software|backend|frontend|fullstack|devops|data|systems|integrations)(engineer|developer|analyst|manager)", r"\1 \2", raw)
    return re.sub(r"[^a-z0-9]+", " ", raw).strip()


def _append_new_jobs(queue: list[dict[str, Any]], seen: set[str], payload: dict[str, Any]) -> int:
    added = 0
    image_size = payload.get("image_size") if isinstance(payload.get("image_size"), dict) else {}
    height = int(image_size.get("height") or 1194)
    for job in payload.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        if not _job_click_point_in_safe_band(job, window_height=height):
            continue
        key = _job_seen_key(job)
        if not key or key in seen:
            continue
        seen.add(key)
        queue.append(job)
        added += 1
    return added


def _job_click_point_in_safe_band(job: dict[str, Any], *, window_height: int) -> bool:
    point = job.get("click_point") if isinstance(job.get("click_point"), dict) else None
    bbox = job.get("card_bbox") if isinstance(job.get("card_bbox"), dict) else None
    try:
        y = int(float((point or {}).get("y") if point else (bbox or {}).get("y", 0) + (bbox or {}).get("h", 0) / 2))
    except (TypeError, ValueError):
        return False
    top_safe = max(220, int(window_height * 0.28))
    bottom_safe = min(window_height - 140, int(window_height * 0.84))
    return top_safe <= y <= bottom_safe


def _compact_action_response(response: dict[str, Any]) -> dict[str, Any]:
    result = _result_payload(response)
    step = result.get("agent_step_result") if isinstance(result.get("agent_step_result"), dict) else {}
    evidence = step.get("evidence") if isinstance(step.get("evidence"), dict) else {}
    pre_click = result.get("pre_click_decision") if isinstance(result.get("pre_click_decision"), dict) else {}
    final_submit_guard = result.get("final_submit_guard") if isinstance(result.get("final_submit_guard"), dict) else {}
    return {
        "success": response.get("success"),
        "message": response.get("message"),
        "status": step.get("status"),
        "trace_path": result.get("trace_path") or evidence.get("action_trace_path"),
        "recognition_plan_trace_path": evidence.get("recognition_plan_trace_path") or result.get("recognition_plan_trace_path"),
        "coordinate_overlay_path": evidence.get("coordinate_overlay_path") or result.get("coordinate_overlay_path"),
        "approved_plan_id": step.get("approved_plan_id") or result.get("approved_plan_id"),
        "selected_click_point": step.get("selected_click_point") or result.get("selected_click_point"),
        "pre_click_allowed": pre_click.get("allowed"),
        "final_submit_guard": final_submit_guard or None,
        "error": response.get("error"),
    }


def _safe_form_fill_attempt(
    base_url: str,
    *,
    app_name: str,
    answer_plan: dict[str, Any],
    execute_fill: bool,
    candidate_profile: dict[str, Any] | None = None,
    cover_letter_draft: dict[str, Any] | None = None,
    max_safe_fields_to_fill: int = 1,
    allow_cover_letter_fill: bool = False,
    timeout: float,
) -> dict[str, Any]:
    fill_limit = max(0, int(max_safe_fields_to_fill))
    attempt: dict[str, Any] = {
        "contract_version": "safe_form_fill_attempt_v1",
        "enabled": bool(execute_fill),
        "max_safe_fields_to_fill": fill_limit,
        "allow_cover_letter_fill": bool(allow_cover_letter_fill),
        "status": "disabled",
        "filled": False,
        "fields_attempted": 0,
        "fields_filled": 0,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "final_submissions": 0,
        "stop_reason": "safe_form_fill_disabled",
        "field_results": [],
    }
    if answer_plan.get("status") == "blocked_final_submit_visible":
        attempt["status"] = "blocked_need_user_or_gpt_decision"
        attempt["stop_reason"] = "final_submit_visible_stop_before_fill"
        return attempt
    candidates, skipped = _safe_fill_candidates(
        answer_plan,
        allow_cover_letter_fill=allow_cover_letter_fill,
        candidate_profile=candidate_profile,
        cover_letter_draft=cover_letter_draft,
    )
    selected = candidates[:fill_limit] if fill_limit else []
    attempt["candidate_count"] = len(candidates)
    attempt["selected_count"] = len(selected)
    attempt["skipped_candidates"] = skipped
    if not candidates:
        attempt["status"] = "no_safe_known_fields"
        attempt["stop_reason"] = "no_auto_safe_known_fields_to_fill"
        return attempt
    if not selected:
        attempt["status"] = "no_safe_known_fields"
        attempt["stop_reason"] = "max_safe_fields_to_fill_zero"
        attempt["field_results"] = [_field_fill_preview(item, value=value, selected_for_fill=False) for item, value in candidates]
        return attempt
    if not execute_fill:
        attempt["status"] = "dry_run_ready"
        attempt["stop_reason"] = "safe_form_fill_requires_explicit_flag"
        selected_ids = {id(item) for item, _value in selected}
        attempt["field_results"] = [
            _field_fill_preview(item, value=value, selected_for_fill=id(item) in selected_ids)
            for item, value in candidates
        ]
        return attempt

    for item, value in selected:
        result = _fill_one_safe_field(base_url, app_name=app_name, item=item, value=value, timeout=timeout)
        attempt["field_results"].append(result)
        attempt["fields_attempted"] += 1
        if result.get("filled"):
            attempt["fields_filled"] += 1
        else:
            attempt["status"] = "blocked_need_user_or_gpt_decision"
            attempt["stop_reason"] = result.get("stop_reason") or "safe_field_fill_failed"
            break
    if attempt["fields_filled"] > 0 and attempt["status"] == "disabled":
        attempt["status"] = "filled_until_review"
        attempt["filled"] = True
        attempt["stop_reason"] = "safe_known_fields_filled_stop_before_navigation"
    return attempt


def _safe_fill_candidates(
    answer_plan: dict[str, Any],
    *,
    allow_cover_letter_fill: bool,
    candidate_profile: dict[str, Any] | None = None,
    cover_letter_draft: dict[str, Any] | None = None,
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    skipped: list[dict[str, Any]] = []
    for item in answer_plan.get("planned_answers") or []:
        if not isinstance(item, dict):
            continue
        value = _resolve_safe_fill_value(item, candidate_profile=candidate_profile, cover_letter_draft=cover_letter_draft)
        reason = _safe_fill_skip_reason(item, value=value, allow_cover_letter_fill=allow_cover_letter_fill)
        if reason is None:
            candidates.append((item, value))
        else:
            skipped.append(
                {
                    "label": item.get("label"),
                    "category": item.get("category"),
                    "answer_source": item.get("answer_source"),
                    "reason": reason,
                }
            )
    return _dedupe_safe_fill_candidates(candidates), skipped


def _safe_fill_skip_reason(item: dict[str, Any], *, value: str, allow_cover_letter_fill: bool) -> str | None:
    if item.get("category") != "auto_safe_known":
        return "category_not_auto_safe_known"
    if not value.strip():
        return "missing_runtime_value"
    if not _safe_fill_target_is_typeable(item):
        return "target_not_typeable"
    answer_source = str(item.get("answer_source") or "")
    label = str(item.get("label") or "").casefold()
    if (answer_source == "cover_letter_draft_v1.draft" or "cover letter" in label or "supporting statement" in label) and not allow_cover_letter_fill:
        return "cover_letter_fill_requires_explicit_flag"
    return None


def _safe_fill_target_is_typeable(item: dict[str, Any]) -> bool:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    role = str(source.get("role") or item.get("role") or "").casefold()
    if not role:
        return False
    if any(term in role for term in ("button", "checkbox", "radio", "select", "dropdown", "listitem", "group", "menu")):
        return False
    return any(term in role for term in ("input", "textarea", "textbox", "edit", "text area", "email", "tel", "phone"))


def _dedupe_safe_fill_candidates(candidates: list[tuple[dict[str, Any], str]]) -> list[tuple[dict[str, Any], str]]:
    ordered = sorted(candidates, key=lambda pair: _safe_fill_candidate_priority(pair[0]))
    seen: set[tuple[Any, ...]] = set()
    deduped: list[tuple[dict[str, Any], str]] = []
    for item, value in ordered:
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        bbox = source.get("bbox") if isinstance(source.get("bbox"), dict) else {}
        key = (
            item.get("answer_source"),
            bbox.get("x"),
            bbox.get("y"),
            bbox.get("w"),
            bbox.get("h"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append((item, value))
    return deduped


def _safe_fill_candidate_priority(item: dict[str, Any]) -> tuple[int, int, int]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    collection = str(source.get("collection") or "")
    reason = str(item.get("reason") or "")
    label = str(item.get("label") or "")
    return (
        0 if reason == "cover_letter_body_field_detected" else 1,
        0 if collection == "available_actions" else 1,
        len(label),
    )


def _resolve_safe_fill_value(
    item: dict[str, Any],
    *,
    candidate_profile: dict[str, Any] | None,
    cover_letter_draft: dict[str, Any] | None,
) -> str:
    source = str(item.get("answer_source") or "")
    profile = candidate_profile if isinstance(candidate_profile, dict) else {}
    draft = cover_letter_draft if isinstance(cover_letter_draft, dict) else {}
    if source == "cover_letter_draft_v1.draft":
        return str(draft.get("draft") or "").strip()
    if source.startswith("candidate_profile_v1."):
        key = source.split(".", 1)[1]
        value = profile.get(key)
        return str(value or "").strip()
    if source == "candidate_profile_v1":
        for key in ("candidate_name", "name", "full_name"):
            value = profile.get(key)
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _redacted_runtime_value_preview(value: str, *, answer_source: str) -> str | None:
    if not value:
        return None
    source = str(answer_source or "")
    if source == "cover_letter_draft_v1.draft":
        kind = "cover_letter"
    elif "email" in source:
        kind = "email"
    elif "phone" in source or "mobile" in source:
        kind = "phone"
    elif "name" in source:
        kind = "name"
    else:
        kind = "profile_value"
    return f"<redacted:{kind}:len={len(value)}>"


def _field_fill_preview(item: dict[str, Any], *, value: str, selected_for_fill: bool = False) -> dict[str, Any]:
    return {
        "contract_version": "safe_field_fill_result_v1",
        "enabled": False,
        "selected_for_fill": bool(selected_for_fill),
        "label": item.get("label"),
        "category": item.get("category"),
        "reason": item.get("reason"),
        "answer_source": item.get("answer_source"),
        "value_length": len(value),
        "filled": False,
        "stop_reason": "preview_only",
        "safe_form_fill_trace": _build_safe_form_fill_trace(item, value=value, enabled=False),
    }


def _fill_one_safe_field(base_url: str, *, app_name: str, item: dict[str, Any], value: str, timeout: float) -> dict[str, Any]:
    label = _safe_focus_label(item)
    result: dict[str, Any] = {
        "contract_version": "safe_field_fill_result_v1",
        "enabled": True,
        "label": label,
        "category": item.get("category"),
        "reason": item.get("reason"),
        "answer_source": item.get("answer_source"),
        "value_length": len(value),
        "filled": False,
        "focus_goal": f"Click the {label} field in the SEEK application form. Do not click Continue, Next, Review, Submit, Send application, or Complete application.",
    }
    result["safe_form_fill_trace"] = _build_safe_form_fill_trace(item, value=value, enabled=True)
    focus_payload = {
        "agent_mode": "execute",
        "goal": result["focus_goal"],
        "app_name": app_name,
        "state_hint": "SEEK application form; focus one safe known field only",
        "capture_live": True,
        "dry_run": True,
        "enable_post_click_verification": True,
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
        "metadata": {
            "seek_safe_form_fill": True,
            "forbid_final_submit": True,
            "field_label": label,
        },
    }
    dry_response = _post_json(base_url, "/action/execute_recognition_plan", focus_payload, timeout)
    result["focus_dry_run_response"] = _compact_action_response(dry_response)
    dry_result = _result_payload(dry_response)
    approved_plan_id = dry_result.get("approved_plan_id") or (dry_result.get("agent_step_result") or {}).get("approved_plan_id")
    dry_focus_point = result["focus_dry_run_response"].get("selected_click_point")
    dry_focus_point_inside_bbox = (
        isinstance(dry_focus_point, dict) and _safe_fill_point_inside_item_bbox(item, dry_focus_point)
    )
    result["safe_form_fill_trace"]["pre_focus_dry_run"] = {
        "allowed": dry_response.get("success") is True and bool(approved_plan_id),
        "trace_path": result["focus_dry_run_response"].get("trace_path"),
        "approved_plan_id": approved_plan_id,
        "selected_click_point": dry_focus_point,
        "point_inside_field_bbox": dry_focus_point_inside_bbox,
        "pre_click_allowed": result["focus_dry_run_response"].get("pre_click_allowed"),
        "final_submit_guard": result["focus_dry_run_response"].get("final_submit_guard"),
    }
    if dry_response.get("success") is not True or not approved_plan_id:
        result["stop_reason"] = "safe_field_focus_dry_run_not_approved"
        return result
    if not dry_focus_point_inside_bbox:
        result["stop_reason"] = "safe_field_focus_point_outside_field_bbox"
        return result
    execute_payload = {
        **focus_payload,
        "dry_run": False,
        "approved_plan_id": approved_plan_id,
        "write_policy": {"path_graph": False, "element_memory": True, "trace": True},
    }
    execute_response = _post_json(base_url, "/action/execute_recognition_plan", execute_payload, timeout)
    result["focus_execute_response"] = _compact_action_response(execute_response)
    result["safe_form_fill_trace"]["approved_focus_reuse"] = {
        "allowed": execute_response.get("success") is True,
        "trace_path": result["focus_execute_response"].get("trace_path"),
        "approved_plan_id": approved_plan_id,
        "selected_click_point": result["focus_execute_response"].get("selected_click_point"),
        "pre_click_allowed": result["focus_execute_response"].get("pre_click_allowed"),
        "final_submit_guard": result["focus_execute_response"].get("final_submit_guard"),
    }
    if execute_response.get("success") is not True:
        result["stop_reason"] = "safe_field_focus_execute_failed"
        return result
    focus_point = result["focus_execute_response"].get("selected_click_point")
    type_point = (
        focus_point
        if isinstance(focus_point, dict) and _safe_fill_point_inside_item_bbox(item, focus_point)
        else _safe_fill_type_point(item, window_height=1400)
    )
    type_payload = {
        "text": value,
        "dry_run": False,
        "click_before_typing": bool(type_point),
        "x": type_point.get("x") if type_point else None,
        "y": type_point.get("y") if type_point else None,
        "clear_existing": True,
        "submit": False,
        "restore_clipboard": True,
    }
    result["safe_form_fill_trace"]["type_text_request"] = {
        "click_before_typing": type_payload["click_before_typing"],
        "point": {"x": type_payload["x"], "y": type_payload["y"]} if type_point else None,
        "clear_existing": type_payload["clear_existing"],
        "submit": type_payload["submit"],
        "restore_clipboard": type_payload["restore_clipboard"],
        "text_length": len(value),
    }
    type_response = _post_json(
        base_url,
        "/action/type_text",
        type_payload,
        timeout,
    )
    result["type_text_response"] = _compact_type_response(type_response)
    if type_response.get("success") is not True:
        result["safe_form_fill_trace"]["post_fill_verification"] = {
            "contract_version": "post_fill_verification_v1",
            "decision": "failed",
            "failure_reason": "type_text_failed",
            "field_contains_expected_value": False,
            "no_navigation": None,
            "no_continue_or_next": True,
            "no_submit": result["type_text_response"].get("submit") is False,
            "type_text_trace_path": result["type_text_response"].get("trace_path"),
        }
        result["stop_reason"] = "safe_field_type_text_failed"
        return result
    verification = _post_fill_verification(
        base_url,
        app_name=app_name,
        item=item,
        value=value,
        type_text_trace_path=result["type_text_response"].get("trace_path"),
        timeout=timeout,
    )
    result["post_fill_verification"] = verification
    result["safe_form_fill_trace"]["post_fill_verification"] = verification
    if verification.get("decision") != "verified":
        result["stop_reason"] = verification.get("failure_reason") or "post_fill_verification_not_verified"
        return result
    result["filled"] = True
    result["stop_reason"] = "safe_field_filled"
    return result


def _safe_fill_point_inside_item_bbox(item: dict[str, Any], point: dict[str, Any]) -> bool:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    bbox = source.get("bbox") if isinstance(source.get("bbox"), dict) else {}
    try:
        x = int(bbox.get("x"))
        y = int(bbox.get("y"))
        w = int(bbox.get("w"))
        h = int(bbox.get("h"))
        px = int(point.get("x"))
        py = int(point.get("y"))
    except (TypeError, ValueError):
        return False
    return x <= px <= x + w and y <= py <= y + h


def _safe_fill_type_point(item: dict[str, Any], *, window_height: int | None = None) -> dict[str, int] | None:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    bbox = source.get("bbox") if isinstance(source.get("bbox"), dict) else {}
    try:
        x = int(bbox.get("x"))
        y = int(bbox.get("y"))
        w = int(bbox.get("w"))
        h = int(bbox.get("h"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    point_y = y + max(4, min(h // 2, h - 4))
    if window_height:
        point_y = min(max(8, point_y), max(8, int(window_height) - 20))
    return {"x": x + max(4, w // 2), "y": point_y}


def _safe_focus_label(item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "")
    label = str(item.get("label") or "application field")
    answer_source = str(item.get("answer_source") or "")
    if reason in {"cover_letter_body_field_detected", "cover_letter_draft_available_but_not_pasted"} or answer_source == "cover_letter_draft_v1.draft":
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        source_text = str(source.get("source_text") or "").strip()
        if source_text.casefold().startswith("dear "):
            return "existing cover letter text box containing Dear Alicia"
        return "Write a cover letter text box"
    if len(label) > 120:
        return label[:117].rstrip() + "..."
    return label


def _build_safe_form_fill_trace(item: dict[str, Any], *, value: str, enabled: bool) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    label = str(item.get("label") or "")
    return {
        "contract_version": "safe_form_fill_trace_v1",
        "enabled": bool(enabled),
        "field_id": source.get("id") or item.get("id") or label,
        "field_label": label,
        "field_category": item.get("category"),
        "field_bbox": source.get("bbox") or item.get("bbox"),
        "container_or_form_id": source.get("collection") or item.get("collection"),
        "answer_plan_ref": {
            "label": label,
            "reason": item.get("reason"),
            "answer_source": item.get("answer_source"),
        },
        "value_source": item.get("answer_source"),
        "value_preview": _redacted_runtime_value_preview(value, answer_source=str(item.get("answer_source") or "")),
        "value_length": len(value),
        "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
        "pre_focus_dry_run": None,
        "approved_focus_reuse": None,
        "type_text_request": {
            "click_before_typing": False,
            "clear_existing": True,
            "submit": False,
            "restore_clipboard": True,
            "text_length": len(value),
        },
        "post_fill_verification": {
            "status": "not_run_preview" if not enabled else "not_run_before_type_text",
            "field_contains_expected_value": None,
            "no_navigation": None,
            "no_submit": True,
        },
        "safety": {
            "continue_clicks": 0,
            "submit_clicks": 0,
            "final_submissions": 0,
        },
    }


def _post_fill_verification(
    base_url: str,
    *,
    app_name: str,
    item: dict[str, Any],
    value: str,
    type_text_trace_path: str | None,
    timeout: float,
) -> dict[str, Any]:
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    label = str(item.get("label") or "")
    observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK application form after safe field fill",
        timeout=timeout,
    )
    flow_state = assess_seek_application_flow_state(observation)
    blocker = flow_state.get("final_submit_visible_blocker") if isinstance(flow_state.get("final_submit_visible_blocker"), dict) else {}
    value_check = _verify_expected_value_from_structured_inventory(observation, item=item, value=value)
    dangerous_state = flow_state.get("state_type") in {
        "final_submit_visible",
        "review_step_detected",
        "third_party_ats",
        "login_required",
        "captcha_or_verification",
        "unknown_after_apply",
    }
    decision = "verified" if value_check["field_contains_expected_value"] and not dangerous_state and blocker.get("blocked") is not True else "unverified"
    failure_reason = None
    if blocker.get("blocked") is True:
        decision = "stop_required"
        failure_reason = "final_submit_visible_after_fill"
    elif dangerous_state:
        decision = "stop_required"
        failure_reason = f"unsafe_application_state_after_fill:{flow_state.get('state_type')}"
    elif not value_check["field_contains_expected_value"]:
        failure_reason = value_check.get("failure_reason") or "expected_value_not_verified"
    return {
        "contract_version": "post_fill_verification_v1",
        "field_id": source.get("id") or item.get("id") or label,
        "field_label": label,
        "field_category": item.get("category"),
        "expected_value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
        "expected_value_preview": _redacted_runtime_value_preview(value, answer_source=str(item.get("answer_source") or "")),
        "verification_methods": value_check["verification_methods"],
        "field_relocation": value_check["field_relocation"],
        "field_contains_expected_value": value_check["field_contains_expected_value"],
        "same_application_state": not dangerous_state,
        "no_navigation": not dangerous_state,
        "no_continue_or_next": True,
        "no_submit": True,
        "final_submit_visible_blocker": {
            "ran": True,
            "blocked": bool(blocker.get("blocked")),
            "visible_final_submit": bool(blocker.get("blocked")),
            "reason": blocker.get("reason"),
        },
        "application_flow_state": {
            "contract_version": flow_state.get("contract_version"),
            "state_type": flow_state.get("state_type"),
            "detected_states": flow_state.get("detected_states"),
            "stop_reason": flow_state.get("stop_reason"),
        },
        "decision": decision,
        "failure_reason": failure_reason,
        "type_text_trace_path": type_text_trace_path,
        "observe_trace_path": observation.get("trace_path"),
        "safety": {
            "continue_clicks": 0,
            "submit_clicks": 0,
            "final_submissions": 0,
        },
    }


def _verify_expected_value_from_structured_inventory(
    observation: dict[str, Any],
    *,
    item: dict[str, Any],
    value: str,
) -> dict[str, Any]:
    expected = _normalize_value(value)
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    target_id = str(source.get("id") or item.get("id") or "")
    target_label = _normalize_value(item.get("label"))
    source_bbox = source.get("bbox") if isinstance(source.get("bbox"), dict) else None
    allow_ocr_primary = str(item.get("answer_source") or "") == "cover_letter_draft_v1.draft"
    matched_items: list[dict[str, Any]] = []
    dom_match = False
    uia_match = False
    ocr_match = False
    ocr_evidence_texts: list[str] = []
    ocr_match_type: str | None = None
    ocr_anchor_matches: list[str] = []
    expanded_ocr_bbox = _expand_bbox(source_bbox, x_pad=80, y_pad=720) if allow_ocr_primary else source_bbox
    for visible in _iter_inventory_items(observation):
        visible_id = str(visible.get("id") or visible.get("element_id") or visible.get("action_id") or visible.get("card_id") or "")
        visible_label = _normalize_value(visible.get("label") or visible.get("text"))
        dom_value = _normalize_value(visible.get("value") or visible.get("dom_value") or visible.get("input_value"))
        uia_value = _normalize_value(visible.get("uia_value") or visible.get("value_pattern") or visible.get("text_pattern"))
        ocr_text = _normalize_value(visible.get("text") or visible.get("label"))
        same_field = (
            bool(target_id and visible_id == target_id)
            or bool(target_label and target_label in visible_label)
            or (allow_ocr_primary and bool(expected and (expected in dom_value or expected in uia_value or expected in ocr_text)))
            or (allow_ocr_primary and _bboxes_overlap(expanded_ocr_bbox, visible.get("bbox") or visible.get("card_bbox")))
        )
        if not same_field:
            continue
        if ocr_text:
            ocr_evidence_texts.append(ocr_text)
        entry = {
            "id": visible_id or None,
            "label": visible.get("label") or visible.get("text"),
            "bbox": visible.get("bbox") or visible.get("card_bbox"),
            "has_dom_value": bool(dom_value),
            "has_uia_value": bool(uia_value),
        }
        if dom_value and (dom_value == expected or expected in dom_value):
            dom_match = True
            entry["matched_by"] = "dom_value"
        elif uia_value and (uia_value == expected or expected in uia_value):
            uia_match = True
            entry["matched_by"] = "uia_value"
        elif ocr_text and expected and expected in ocr_text:
            ocr_match = True
            ocr_match_type = "single_item_contains"
            entry["matched_by"] = "ocr_text_primary" if allow_ocr_primary else "ocr_text_secondary"
        matched_items.append(entry)
    if allow_ocr_primary and not ocr_match and ocr_evidence_texts:
        combined_ocr = _normalize_value(" ".join(ocr_evidence_texts))
        anchor_check = _expected_visible_in_ocr(expected, combined_ocr)
        if anchor_check["matched"]:
            ocr_match = True
            ocr_match_type = str(anchor_check.get("match_type") or "anchor_contains")
            ocr_anchor_matches = list(anchor_check.get("matched_anchors") or [])
            anchor_keys = [_compact_value(anchor) for anchor in ocr_anchor_matches if _compact_value(anchor)]
            for entry in matched_items:
                entry_text_key = _compact_value(entry.get("label"))
                if not entry.get("matched_by") and any(anchor_key in entry_text_key for anchor_key in anchor_keys):
                    entry["matched_by"] = "ocr_text_anchor_primary"
    primary_match = dom_match or uia_match or (allow_ocr_primary and ocr_match)
    failure_reason = None
    if not matched_items:
        failure_reason = "field_relocation_failed"
    elif not primary_match:
        failure_reason = "expected_value_not_observable_without_dom_or_uia"
    matched_by = []
    for matched_item in matched_items:
        if matched_item.get("matched_by") and matched_item["matched_by"] not in matched_by:
            matched_by.append(matched_item["matched_by"])
    matched_items_for_report = sorted(matched_items, key=lambda matched_item: 0 if matched_item.get("matched_by") else 1)
    return {
        "field_contains_expected_value": primary_match,
        "failure_reason": failure_reason,
        "field_relocation": {
            "status": "matched" if matched_items else "not_matched",
            "match_confidence": 0.9 if primary_match else (0.4 if matched_items else 0.0),
            "matched_by": matched_by,
            "matched_items": matched_items_for_report[:5],
        },
        "verification_methods": {
            "dom_value": {"available": any(item["has_dom_value"] for item in matched_items), "matched": dom_match, "match_type": "exact_or_normalized_contains" if dom_match else None},
            "uia_value_pattern": {"available": any(item["has_uia_value"] for item in matched_items), "matched": uia_match, "match_type": "exact_or_normalized_contains" if uia_match else None},
            "ocr_near_field": {
                "available": bool(ocr_evidence_texts),
                "matched": ocr_match,
                "used_as_primary": bool(allow_ocr_primary and ocr_match),
                "match_type": ocr_match_type,
                "matched_anchors": ocr_anchor_matches[:6],
                "evidence_item_count": len(ocr_evidence_texts),
            },
        },
    }


def _expand_bbox(bbox: Any, *, x_pad: float = 0, y_pad: float = 0) -> dict[str, float] | None:
    if not isinstance(bbox, dict):
        return None
    try:
        x = float(bbox.get("x"))
        y = float(bbox.get("y"))
        w = float(bbox.get("w", bbox.get("width")))
        h = float(bbox.get("h", bbox.get("height")))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x - x_pad, "y": y - y_pad, "w": w + (x_pad * 2), "h": h + (y_pad * 2)}


def _bboxes_overlap(a: Any, b: Any) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    try:
        ax = float(a.get("x"))
        ay = float(a.get("y"))
        aw = float(a.get("w"))
        ah = float(a.get("h"))
        bx = float(b.get("x"))
        by = float(b.get("y"))
        bw = float(b.get("w"))
        bh = float(b.get("h"))
    except (TypeError, ValueError):
        return False
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    overlap_w = min(ax + aw, bx + bw) - max(ax, bx)
    overlap_h = min(ay + ah, by + bh) - max(ay, by)
    if overlap_w <= 0 or overlap_h <= 0:
        return False
    smaller_area = min(aw * ah, bw * bh)
    return (overlap_w * overlap_h) / smaller_area >= 0.5


def _iter_inventory_items(observation: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_item(entry: dict[str, Any], *, collection_name: str) -> None:
        copied = dict(entry)
        copied.setdefault("collection", collection_name)
        bbox = copied.get("bbox") or copied.get("card_bbox") or {}
        signature = json.dumps(
            {
                "id": copied.get("id") or copied.get("element_id") or copied.get("action_id") or copied.get("card_id"),
                "text": copied.get("text") or copied.get("label"),
                "bbox": bbox,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature in seen:
            return
        seen.add(signature)
        items.append(copied)

    inventories = []
    if isinstance(observation.get("screen_inventory"), dict):
        inventories.append(observation["screen_inventory"])
    screen_reading = observation.get("screen_reading") if isinstance(observation.get("screen_reading"), dict) else {}
    if isinstance(screen_reading.get("screen_inventory"), dict):
        inventories.append(screen_reading["screen_inventory"])
    for inventory in inventories:
        for collection_name in ("page_elements", "available_actions", "cards"):
            for entry in inventory.get(collection_name) or []:
                if isinstance(entry, dict):
                    add_item(entry, collection_name=collection_name)
    for collection_name, values in (
        ("texts", observation.get("texts")),
        ("ocr_result.texts", (observation.get("ocr_result") or {}).get("texts") if isinstance(observation.get("ocr_result"), dict) else None),
        ("screen_reading.texts", screen_reading.get("texts")),
    ):
        for index, entry in enumerate(values or []):
            if isinstance(entry, dict):
                copied = dict(entry)
                copied.setdefault("id", f"{collection_name}_{index}")
                add_item(copied, collection_name=collection_name)
    return items


def _expected_visible_in_ocr(expected: str, observed: str) -> dict[str, Any]:
    if not expected or not observed:
        return {"matched": False, "match_type": None, "matched_anchors": []}
    if expected in observed:
        return {"matched": True, "match_type": "normalized_full_contains", "matched_anchors": []}
    compact_observed = _compact_value(observed)
    compact_expected = _compact_value(expected)
    if compact_expected and compact_expected in compact_observed:
        return {"matched": True, "match_type": "compact_full_contains", "matched_anchors": []}
    anchors = _expected_ocr_anchors(expected)
    matched = [anchor for anchor in anchors if _compact_value(anchor) and _compact_value(anchor) in compact_observed]
    required = 3 if len(anchors) >= 3 else len(anchors)
    return {
        "matched": bool(required and len(matched) >= required),
        "match_type": "compact_anchor_contains" if required and len(matched) >= required else None,
        "matched_anchors": matched,
    }


def _expected_ocr_anchors(expected: str) -> list[str]:
    words = [word for word in expected.split() if word]
    anchors: list[str] = []
    for phrase in ("dear hiring team", "kind regards", "wenqing ji"):
        if phrase in expected:
            anchors.append(phrase)
    for start in (0, 8, max(0, len(words) // 2 - 4), max(0, len(words) - 8)):
        phrase = " ".join(words[start : start + 8]).strip()
        if len(_compact_value(phrase)) >= 16:
            anchors.append(phrase)
    unique: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        key = _compact_value(anchor)
        if key and key not in seen:
            unique.append(anchor)
            seen.add(key)
    return unique


def _compact_value(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _normalize_value(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _compact_type_response(response: dict[str, Any]) -> dict[str, Any]:
    payload = _result_payload(response)
    return {
        "success": response.get("success"),
        "message": response.get("message"),
        "trace_path": payload.get("trace_path") if isinstance(payload, dict) else None,
        "dry_run": payload.get("dry_run") if isinstance(payload, dict) else None,
        "text_length": payload.get("text_length") if isinstance(payload, dict) else None,
        "click_before_typing": payload.get("click_before_typing") if isinstance(payload, dict) else None,
        "submit": payload.get("submit") if isinstance(payload, dict) else None,
        "error": response.get("error"),
    }


def load_learned_artifact(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def run_traversal(
    *,
    base_url: str,
    app_name: str,
    url: str | None,
    max_jobs: int,
    max_detail_scrolls: int,
    execute_clicks: bool,
    timeout: float,
    max_results_scrolls: int = 8,
    candidate_profile: dict[str, Any] | None = None,
    saved_jobs_dir: str | Path = "artifacts/seek/saved-jobs",
    apply_entry: bool = False,
    allow_maybe_apply: bool = False,
    fill_safe_fields: bool = False,
    max_safe_fields_to_fill: int = 1,
    allow_cover_letter_fill: bool = False,
    learned_artifact: dict[str, Any] | None = None,
    window_width: int | None = 2560,
    window_height: int | None = 1400,
    job_archives_dir: str | Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    profile_readiness = assess_candidate_profile_readiness(candidate_profile)
    apply_entry_profile_gate = _apply_entry_profile_gate(
        apply_entry=apply_entry,
        fill_safe_fields=fill_safe_fields,
        profile_readiness=profile_readiness,
    )
    if url:
        open_response = _open_seek(base_url, url=url, app_name=app_name, timeout=timeout)
        if open_response.get("success") is not True:
            raise SeekTraversalError(f"failed to open SEEK URL: {open_response.get('error') or open_response.get('message')}")
        resize_response = _resize_bound_window(
            base_url,
            width=window_width,
            height=window_height,
            timeout=timeout,
        )
        if resize_response is not None and resize_response.get("success") is not True:
            raise SeekTraversalError(f"failed to resize SEEK window: {resize_response.get('error') or resize_response.get('message')}")
    else:
        resize_response = _resize_bound_window(
            base_url,
            width=window_width,
            height=window_height,
            timeout=timeout,
        )
        if resize_response is not None and resize_response.get("success") is not True:
            raise SeekTraversalError(f"failed to resize bound SEEK window: {resize_response.get('error') or resize_response.get('message')}")
    first_observation = _observe(
        base_url,
        app_name=app_name,
        state_hint="SEEK search results page",
        timeout=timeout,
    )
    cards_payload = extract_seek_job_cards(first_observation, goal="read visible SEEK job cards")
    latest_results_container = cards_payload.get("results_list_container") if isinstance(cards_payload.get("results_list_container"), dict) else None
    job_queue: list[dict[str, Any]] = []
    seen_job_keys: set[str] = set()
    _append_new_jobs(job_queue, seen_job_keys, cards_payload)
    all_card_payloads = [cards_payload]
    results_scrolls: list[dict[str, Any]] = []
    opened_details: list[dict[str, Any]] = []
    traversal_steps: list[dict[str, Any]] = []
    processed_jobs: list[dict[str, Any]] = []
    match_decisions: list[dict[str, Any]] = []
    saved_jobs: list[dict[str, Any]] = []
    apply_entries: list[dict[str, Any]] = []
    result_scroll_count = 0
    consecutive_empty_result_scrolls = 0
    stop_reason: str | None = None
    target_jobs = max(0, int(max_jobs))
    max_attempts = target_jobs if not execute_clicks else target_jobs + max_results_scrolls + 5
    while (len(opened_details) if execute_clicks else len(processed_jobs)) < target_jobs and len(processed_jobs) < max_attempts:
        if not job_queue:
            if not processed_jobs and result_scroll_count == 0:
                stop_reason = "blocked_no_initial_job_cards"
                break
            if result_scroll_count >= max_results_scrolls:
                stop_reason = "max_results_scrolls_reached"
                break
            scroll = _scroll_results_list(
                base_url,
                timeout=timeout,
                learned_artifact=learned_artifact,
                container_bbox=(latest_results_container or {}).get("bbox") if latest_results_container else None,
                wheel_clicks=_adaptive_wheel_clicks(base=4, repeated_observations=consecutive_empty_result_scrolls),
            )
            results_scrolls.append(scroll)
            result_scroll_count += 1
            if not scroll.get("success"):
                stop_reason = "results_list_scroll_failed"
                break
            observation = _observe(
                base_url,
                app_name=app_name,
                state_hint="SEEK search results page after results_list scroll",
                timeout=timeout,
            )
            payload = extract_seek_job_cards(observation, goal="read visible SEEK job cards")
            latest_results_container = payload.get("results_list_container") if isinstance(payload.get("results_list_container"), dict) else latest_results_container
            all_card_payloads.append(payload)
            added = _append_new_jobs(job_queue, seen_job_keys, payload)
            scroll["new_jobs_added"] = added
            if added == 0:
                consecutive_empty_result_scrolls += 1
            else:
                consecutive_empty_result_scrolls = 0
            if consecutive_empty_result_scrolls >= 3:
                stop_reason = "blocked_no_new_jobs_after_results_scroll"
                break
            if added == 0:
                continue
            continue

        job = job_queue.pop(0)
        index = len(processed_jobs)
        processed_jobs.append(job)
        step: dict[str, Any] = {
            "index": index,
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "card": job,
        }
        stop_after_current_step = False
        if opened_details:
            step["pre_click_detail_reset"] = _reset_seek_job_detail_to_top(
                base_url,
                timeout=timeout,
                learned_artifact=learned_artifact,
            )
        click = _execute_job_card(
            base_url,
            app_name=app_name,
            job=job,
            execute_clicks=execute_clicks,
            timeout=timeout,
            learned_artifact=learned_artifact,
        )
        step["card_click"] = click
        if click.get("opened"):
            detail_read = _read_detail_until_complete(
                base_url,
                app_name=app_name,
                max_scrolls=max_detail_scrolls,
                timeout=timeout,
                learned_artifact=learned_artifact,
            )
            step["detail_read"] = detail_read
            detail = detail_read["detail"]
            opened_details.append(detail)
            completeness = detail_read.get("completeness") if isinstance(detail_read.get("completeness"), dict) else {}
            match_decision = score_seek_job(
                profile=candidate_profile,
                card=job,
                detail=detail,
                detail_complete=completeness.get("complete") is True,
                missing_detail_evidence=[str(item) for item in completeness.get("missing_evidence") or []],
            )
            saved_path = save_suitable_job_record(
                decision=match_decision,
                card=job,
                detail=detail,
                output_dir=saved_jobs_dir,
            )
            if saved_path:
                match_decision = {**match_decision, "saved_job_path": saved_path}
                saved_jobs.append({"job_id": match_decision.get("job_id"), "path": saved_path})
            match_decisions.append(match_decision)
            step["match_decision"] = match_decision
            if apply_entry:
                if not apply_entry_profile_gate["allowed"]:
                    apply_attempt = _blocked_apply_entry_for_profile_gate(
                        job=job,
                        detail=detail,
                        match_decision=match_decision,
                        profile_gate=apply_entry_profile_gate,
                    )
                    step["apply_entry"] = apply_attempt
                    apply_entries.append(apply_attempt)
                    traversal_steps.append(step)
                    break
                apply_attempt = _execute_apply_entry(
                    base_url,
                    app_name=app_name,
                    job=job,
                    detail=detail,
                    match_decision=match_decision,
                    candidate_profile=candidate_profile,
                    execute_clicks=execute_clicks,
                    timeout=timeout,
                    allow_maybe_apply=allow_maybe_apply,
                    fill_safe_fields=fill_safe_fields,
                    max_safe_fields_to_fill=max_safe_fields_to_fill,
                    allow_cover_letter_fill=allow_cover_letter_fill,
                )
                step["apply_entry"] = apply_attempt
                apply_entries.append(apply_attempt)
                if apply_attempt.get("eligible") and apply_attempt.get("stop_reason") != "decision_not_eligible_for_apply_entry":
                    stop_after_current_step = True
        elif click.get("failure_reason") == "post_click_layout_drift" and url:
            restore_response = _open_seek(base_url, url=url, app_name=app_name, timeout=timeout)
            step["search_restore"] = {
                "success": restore_response.get("success") is True,
                "message": restore_response.get("message"),
                "error": restore_response.get("error"),
                "reason": "restore_after_post_click_layout_drift",
            }
            if restore_response.get("success") is True:
                job_queue.clear()
                observation = _observe(
                    base_url,
                    app_name=app_name,
                    state_hint="SEEK search results page restored after layout drift",
                    timeout=timeout,
                )
                payload = extract_seek_job_cards(observation, goal="read visible SEEK job cards after restore")
                all_card_payloads.append(payload)
                step["search_restore"]["new_jobs_added"] = _append_new_jobs(job_queue, seen_job_keys, payload)
        traversal_steps.append(step)
        if stop_after_current_step:
            break
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    report = build_seek_mvp_run_report(
        job_cards=processed_jobs,
        job_details=opened_details,
        match_decisions=match_decisions,
        started_application_flows=sum(1 for entry in apply_entries if entry.get("application_flow_started")),
        cover_letters_generated=sum(1 for entry in apply_entries if entry.get("cover_letter_generated")),
        forms_filled_until_review=sum(int(entry.get("forms_filled_until_review") or 0) for entry in apply_entries),
        elapsed_ms=elapsed_ms,
    )
    aligned_jobs = _aligned_jobs_from_traversal_steps(traversal_steps)
    mode = "apply_entry_traversal" if apply_entry else "no_apply_traversal"
    job_archives = _write_job_archives(
        traversal_steps,
        output_dir=job_archives_dir,
        source_url=url,
        mode=mode,
    )
    report.update(
        {
            "mode": mode,
            "execute_clicks": execute_clicks,
            "apply_entry_enabled": bool(apply_entry),
            "allow_maybe_apply": bool(allow_maybe_apply),
            "source_url": url,
            "cards_extraction": cards_payload,
            "cards_extractions": all_card_payloads,
            "results_list_scrolls": results_scrolls,
            "stop_reason": stop_reason,
            "consecutive_empty_result_scrolls": consecutive_empty_result_scrolls,
            "traversal_steps": traversal_steps,
            "jobs": aligned_jobs,
            "job_archives": job_archives,
            "jobs_opened": sum(1 for item in aligned_jobs if isinstance(item.get("detail"), dict)),
            "jobs_fully_read": sum(
                1
                for item in aligned_jobs
                if isinstance(item.get("detail"), dict)
                and assess_seek_job_detail_completeness(
                    item.get("detail"),
                    scroll_count=max_detail_scrolls,
                    max_scrolls=max_detail_scrolls,
                    require_bottom=True,
                )["complete"]
            ),
            "match_decisions": match_decisions,
            "candidate_profile_loaded": candidate_profile is not None,
            "candidate_profile_readiness": profile_readiness,
            "apply_entry_profile_gate": apply_entry_profile_gate,
            "saved_jobs": saved_jobs,
            "apply_entries": apply_entries,
            "cover_letter_drafts": [
                entry.get("cover_letter_draft")
                for entry in apply_entries
                if isinstance(entry.get("cover_letter_draft"), dict)
            ],
            "application_answer_plans": [
                entry.get("application_answer_plan")
                for entry in apply_entries
                if isinstance(entry.get("application_answer_plan"), dict)
            ],
            "safe_form_fill_enabled": bool(fill_safe_fields),
            "max_safe_fields_to_fill": max(0, int(max_safe_fields_to_fill)),
            "allow_cover_letter_fill": bool(allow_cover_letter_fill),
            "safe_form_fill_attempts": [
                entry.get("safe_form_fill_attempt")
                for entry in apply_entries
                if isinstance(entry.get("safe_form_fill_attempt"), dict)
            ],
            "apply_flow_summary": _apply_flow_summary(apply_entries),
            "continue_clicks": sum(int(entry.get("continue_clicks") or 0) for entry in apply_entries),
            "submit_clicks": sum(int(entry.get("submit_clicks") or 0) for entry in apply_entries),
            "form_fields_filled": sum(int(entry.get("form_fields_filled") or 0) for entry in apply_entries),
            "final_submit_guard_active": bool(apply_entry),
            "final_submit_visible_blockers": [
                entry.get("final_submit_visible_blocker")
                for entry in apply_entries
                if isinstance(entry.get("final_submit_visible_blocker"), dict)
            ],
            "learned_artifact_assisted": learned_artifact is not None,
        }
    )
    report["accuracy_summary"] = build_seek_mvp_accuracy_summary(report)
    report["window_resize"] = resize_response
    report["traversal_trace_path"] = _write_traversal_trace(report, app_name=app_name)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the SEEK MVP traversal slice.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--app-name", default="edge")
    parser.add_argument("--url", default=DEFAULT_SEEK_URL)
    parser.add_argument("--no-open", action="store_true", help="Use the currently bound/open SEEK page instead of opening --url.")
    parser.add_argument("--max-jobs", type=int, default=5)
    parser.add_argument("--max-detail-scrolls", type=int, default=6)
    parser.add_argument("--max-results-scrolls", type=int, default=8)
    parser.add_argument("--execute-clicks", action="store_true", help="Actually click approved job cards. Apply/Quick Apply is clicked only with --apply-entry; final Submit is never clicked.")
    parser.add_argument("--apply-entry", action="store_true", help="For strong_apply jobs, click Apply/Quick Apply through the gate, classify the application state, then stop before form fill or submit.")
    parser.add_argument("--allow-maybe-apply", action="store_true", help="Allow maybe_apply jobs to enter the apply-entry stage. Defaults to strong_apply only.")
    parser.add_argument("--fill-safe-fields", action="store_true", help="After Apply Entry, fill only application_answer_plan_v1 auto_safe_known fields. Continue/Next/Submit remain forbidden.")
    parser.add_argument("--max-safe-fields-to-fill", type=int, default=1, help="Maximum auto_safe_known fields to fill in one Apply Entry. Defaults to 1.")
    parser.add_argument("--allow-cover-letter-fill", action="store_true", help="Allow safe-fill to type a generated cover letter draft. Default is disabled.")
    parser.add_argument("--candidate-profile", type=Path, default=None, help="Optional candidate_profile_v1 JSON used for job matching.")
    parser.add_argument("--learned-artifact", type=Path, default=None, help="Optional learned_app_profile_v1 or seek_learn_artifact_export_v1 JSON used to assist SEEK execution.")
    parser.add_argument("--saved-jobs-dir", type=Path, default=Path("artifacts/seek/saved-jobs"))
    parser.add_argument(
        "--job-archives-dir",
        type=Path,
        default=None,
        help="Directory for per-job archive JSON files. Defaults to a sibling directory derived from --out.",
    )
    parser.add_argument("--window-width", type=int, default=2560, help="Resize the bound browser window before reading. Use 0 to skip.")
    parser.add_argument("--window-height", type=int, default=1400, help="Resize the bound browser window before reading. Use 0 to skip.")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    candidate_profile = load_candidate_profile(args.candidate_profile)
    learned_artifact = load_learned_artifact(args.learned_artifact)
    job_archives_dir = args.job_archives_dir or (args.out.parent / f"{args.out.stem}_job_archives")
    report = run_traversal(
        base_url=args.base_url,
        app_name=args.app_name,
        url=None if args.no_open else args.url,
        max_jobs=args.max_jobs,
        max_detail_scrolls=args.max_detail_scrolls,
        execute_clicks=args.execute_clicks,
        timeout=args.timeout,
        max_results_scrolls=args.max_results_scrolls,
        candidate_profile=candidate_profile,
        saved_jobs_dir=args.saved_jobs_dir,
        apply_entry=args.apply_entry,
        allow_maybe_apply=args.allow_maybe_apply,
        fill_safe_fields=args.fill_safe_fields,
        max_safe_fields_to_fill=args.max_safe_fields_to_fill,
        allow_cover_letter_fill=args.allow_cover_letter_fill,
        learned_artifact=learned_artifact,
        window_width=args.window_width or None,
        window_height=args.window_height or None,
        job_archives_dir=job_archives_dir,
    )
    _write_json(args.out, report)
    print(json.dumps({"success": True, "out": str(args.out), "jobs_seen": report["jobs_seen"], "jobs_opened": report["jobs_opened"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
