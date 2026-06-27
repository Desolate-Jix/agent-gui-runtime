from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from seek_debug_export_application_fill_record import build_record_from_debug_run  # noqa: E402
from seek_debug_step_runner import build_parser as build_step_parser  # noqa: E402
from seek_debug_step_runner import run_step  # noqa: E402
from seek_mvp_traversal_runner import _post_json  # noqa: E402
from app.seek.application_artifacts import build_seek_application_flow_artifact  # noqa: E402
from seek_demo_readiness_report import build_demo_readiness_report, load_step_reports  # noqa: E402


DEFAULT_SEARCH_URL = "https://nz.seek.com/software-engineer-jobs/in-All-Auckland"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SCROLL_WHEEL_CLICKS_MAX = 20


def _clamp_scroll_wheel_clicks(value: int) -> int:
    """滚动请求必须遵守 /action/scroll 的 API 上限。"""

    return max(1, min(SCROLL_WHEEL_CLICKS_MAX, int(value)))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_step(run_dir: Path, step: str, extra: list[str] | None = None) -> dict[str, Any]:
    parser = build_step_parser()
    args = parser.parse_args(["--run-dir", str(run_dir), "--step", step, *(extra or [])])
    started = time.perf_counter()
    payload = run_step(args)
    payload["_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return payload


def _step_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_index": payload.get("step_index"),
        "step_name": payload.get("step_name"),
        "status": payload.get("status"),
        "latency_ms": payload.get("_latency_ms"),
        "report_path": payload.get("report_path"),
        "next_allowed_steps": payload.get("next_allowed_steps"),
        "final_submissions": payload.get("final_submissions"),
        "submit_clicks": payload.get("submit_clicks"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def _card_prefilter_decision(card: dict[str, Any] | None, *, learned_fast_mode: bool = True) -> dict[str, Any]:
    payload = card if isinstance(card, dict) else {}
    title = str(payload.get("title") or "")
    company = str(payload.get("company") or "")
    classification = str(payload.get("classification") or "")
    text = " ".join([title, company, classification]).casefold()
    if "summer" in text:
        return {"decision": "skip", "reason": "summer_role_card_prefilter"}
    if "internship" in text:
        return {"decision": "skip", "reason": "internship_card_prefilter"}
    if "trading manager" in text:
        return {"decision": "skip", "reason": "non_software_trading_manager_card_prefilter"}
    if learned_fast_mode:
        blocked_terms = ("senior", "specialist", "lead", "principal", "architect", "manager")
        if any(term in text for term in blocked_terms):
            return {"decision": "skip", "reason": "learned_fast_mode_skip_senior_or_specialist_card"}
    return {"decision": "keep", "reason": "needs_detail_read"}


def _final_review_ready(flow_state: dict[str, Any] | None) -> bool:
    payload = flow_state if isinstance(flow_state, dict) else {}
    current_step = str(payload.get("current_step") or "").casefold()
    state_type = str(payload.get("state_type") or "").casefold()
    return (
        current_step == "review_and_submit"
        or state_type == "final_submit_visible"
        or payload.get("final_submit_visible") is True
        or payload.get("submit_application_visible") is True
    )


def _card_needs_scroll_into_safer_position(card: dict[str, Any] | None, *, window_height: int) -> bool:
    payload = card if isinstance(card, dict) else {}
    bbox = payload.get("card_bbox") if isinstance(payload.get("card_bbox"), dict) else {}
    try:
        y = int(bbox.get("y") or 0)
        h = int(bbox.get("h") or 0)
    except (TypeError, ValueError):
        return False
    if y <= 0 or h <= 0:
        return False
    return y + min(h, 80) > int(window_height * 0.86)


def _scroll_results_list(base_url: str, *, timeout: float, wheel_clicks: int) -> dict[str, Any]:
    wheel_clicks = _clamp_scroll_wheel_clicks(wheel_clicks)
    return _post_json(
        base_url,
        "/action/scroll",
        {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "container",
            "target_pane": "results_list",
            "target_container_id": "seek:results_list",
            "direction": "down",
            "wheel_clicks": wheel_clicks,
            "reason": "seek_speed_demo_try_more_visible_job_cards",
            "missing_evidence": ["no_eligible_apply_entry_in_current_visible_cards"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
            },
            "dry_run": False,
            "enable_verification": True,
        },
        timeout,
    )


def _scroll_results_page(base_url: str, *, timeout: float, wheel_clicks: int) -> dict[str, Any]:
    wheel_clicks = _clamp_scroll_wheel_clicks(wheel_clicks)
    return _post_json(
        base_url,
        "/action/scroll",
        {
            "contract_version": "scroll_request_v2",
            "scroll_scope": "page",
            "target_pane": "page",
            "target_container_id": "seek:page",
            "direction": "down",
            "wheel_clicks": wheel_clicks,
            "reason": "seek_speed_demo_results_list_container_did_not_change",
            "missing_evidence": ["results_list_card_fingerprint_repeated_after_container_scroll"],
            "expected_effect": {
                "target_container_content_should_change": True,
                "same_semantic_page_should_remain": True,
            },
            "dry_run": False,
            "enable_verification": True,
        },
        timeout,
    )


def _cards_fingerprint(cards: list[Any]) -> tuple[str, ...]:
    out: list[str] = []
    for item in cards:
        if not isinstance(item, dict):
            continue
        out.append("|".join([str(item.get("title") or ""), str(item.get("company") or ""), str(item.get("location") or "")]))
    return tuple(out)


def _apply_decision_allowed(decision: Any, *, allow_maybe_apply: bool) -> bool:
    allowed_apply_decisions = {"strong_apply", "suitable", "apply", "safe_to_apply"}
    if allow_maybe_apply:
        allowed_apply_decisions.add("maybe_apply")
    return str(decision or "") in allowed_apply_decisions


def _apply_entry_state(execute_apply: dict[str, Any]) -> dict[str, Any]:
    apply_entry = execute_apply.get("apply_entry") if isinstance(execute_apply.get("apply_entry"), dict) else {}
    wait_state = (
        ((execute_apply.get("post_apply_wait") or {}).get("application_flow_state") or {})
        if isinstance(execute_apply.get("post_apply_wait"), dict)
        else {}
    )
    merged = dict(wait_state)
    merged.update(apply_entry)
    return merged


def _station_internal_application_started(execute_apply: dict[str, Any]) -> bool:
    state = _apply_entry_state(execute_apply)
    if state.get("application_flow_started") is not True:
        return False
    state_type = str(state.get("state_type") or "").casefold()
    stop_reason = str(state.get("stop_reason") or "").casefold()
    risk_flags = {str(item).casefold() for item in state.get("risk_flags") or []}
    if state_type == "third_party_ats" or "third_party_ats" in risk_flags:
        return False
    if "third_party_ats" in stop_reason or "external" in stop_reason:
        return False
    return True


def _external_apply_flow_started(execute_apply: dict[str, Any]) -> bool:
    state = _apply_entry_state(execute_apply)
    state_type = str(state.get("state_type") or "").casefold()
    risk_flags = {str(item).casefold() for item in state.get("risk_flags") or []}
    stop_reason = str(state.get("stop_reason") or "").casefold()
    return (
        state_type == "third_party_ats"
        or "third_party_ats" in risk_flags
        or "third_party_ats" in stop_reason
        or "external" in stop_reason
    )


def _write_speed_demo_result(
    run_dir: Path,
    *,
    started: float,
    args: argparse.Namespace,
    steps: list[dict[str, Any]],
    job_attempts: list[dict[str, Any]],
    result_scrolls: list[dict[str, Any]],
    status: str,
    stop_reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_ms = round((time.perf_counter() - started) * 1000, 3)
    result = {
        "contract_version": "seek_speed_demo_run_v1",
        "status": status,
        "stop_reason": stop_reason,
        "run_dir": str(run_dir),
        "total_ms": total_ms,
        "time_budget_ms": args.time_budget_ms,
        "within_budget": total_ms <= args.time_budget_ms,
        "learned_fast_mode": not getattr(args, "disable_learned_fast_mode", False),
        "steps": steps,
        "job_attempts": job_attempts,
        "result_scrolls": result_scrolls,
        "final_submissions": 0,
        "submit_clicks": 0,
    }
    if extra:
        result.update(extra)
    _write_json(run_dir / "speed_demo_report.json", result)
    return result


def _recover_seek_results_after_external_apply(
    *,
    run,
    args: argparse.Namespace,
) -> dict[str, Any]:
    open_payload = run("open", ["--url", args.url])
    if open_payload.get("status") != "ok":
        return {
            "status": "failed",
            "reason": "open_seek_after_external_apply_failed",
            "open_status": open_payload.get("status"),
        }
    cards_payload = run("extract_cards").get("cards_payload") or {}
    visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
    return {
        "status": "ok",
        "reason": "reopened_seek_results_after_external_apply",
        "visible_jobs": len(visible_cards),
        "cards_payload": cards_payload,
        "visible_cards": visible_cards,
    }


def run_speed_demo(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    steps: list[dict[str, Any]] = []
    deadline = started + (float(args.time_budget_ms) / 1000.0) if args.time_budget_ms else None

    def budget_exhausted(*, reserve_ms: float = 0.0) -> bool:
        return bool(deadline is not None and time.perf_counter() + (reserve_ms / 1000.0) >= deadline)

    def budget_stop(reason: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason=reason,
            extra=extra,
        )

    def run(step: str, extra: list[str] | None = None) -> dict[str, Any]:
        payload = _run_step(run_dir, step, extra)
        steps.append(_step_summary(payload))
        if (
            step == "execute_apply_entry"
            and payload.get("status") == "blocked_need_user_or_gpt_decision"
            and (payload.get("apply_entry") or {}).get("application_flow_started") is True
        ):
            return payload
        if step == "execute_apply_entry" and payload.get("status") == "blocked_need_user_or_gpt_decision":
            return payload
        if step == "execute_card" and payload.get("status") == "failed":
            return payload
        if payload.get("status") in {"blocked_need_user_or_gpt_decision", "failed"} and step not in {
            "continue_application_flow",
            "extract_final_review",
        }:
            raise RuntimeError(f"{step} stopped with status {payload.get('status')}")
        return payload

    if args.close_old_windows:
        run("close_old_seek_windows", ["--allow-close-windows"])
    run("open", ["--url", args.url])
    run(
        "bind_and_resize_verify",
        ["--window-width", str(args.window_width), "--window-height", str(args.window_height)],
    )
    run("capture")
    cards_payload = run("extract_cards").get("cards_payload") or {}
    visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
    application_started = False
    application_stop_status: str | None = None
    application_stop_reason: str | None = None
    job_attempts: list[dict[str, Any]] = []
    attempted_jobs = 0
    scroll_round = 0
    result_scrolls: list[dict[str, Any]] = []
    while attempted_jobs < args.max_jobs and not application_started:
        if budget_exhausted(reserve_ms=25000):
            return budget_stop("time_budget_exhausted_before_next_job")
        visible_exhausted = False
        for visible_index in range(args.visible_jobs_per_page):
            if budget_exhausted(reserve_ms=25000):
                return budget_stop("time_budget_exhausted_before_next_job")
            if attempted_jobs >= args.max_jobs:
                break
            job_index = args.job_index + visible_index
            if job_index >= len(visible_cards):
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "visible_cards_exhausted",
                        "reason": f"job_index {job_index} out of range for {len(visible_cards)} visible jobs",
                    }
                )
                visible_exhausted = True
                break
            attempted_jobs += 1
            card = visible_cards[job_index] if isinstance(visible_cards[job_index], dict) else {}
            prefilter = _card_prefilter_decision(
                card,
                learned_fast_mode=not getattr(args, "disable_learned_fast_mode", False),
            )
            if prefilter["decision"] == "skip":
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "skipped_card_prefilter",
                        "reason": prefilter["reason"],
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                continue
            if _card_needs_scroll_into_safer_position(card, window_height=args.window_height):
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "deferred_low_visible_card",
                        "reason": "card_too_close_to_bottom_for_stable_click",
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                visible_exhausted = True
                break
            execute_card = run("execute_card", ["--job-index", str(job_index), "--fast-open-detail"])
            if execute_card.get("status") != "ok":
                job_attempts.append(
                    {
                        "job_index": job_index,
                        "scroll_round": scroll_round,
                        "status": "skipped_card_open_failed",
                        "reason": (execute_card.get("action") or {}).get("failure_reason") or execute_card.get("status"),
                        "job_title": card.get("title"),
                        "company": card.get("company"),
                    }
                )
                cards_payload = run("extract_cards").get("cards_payload") or {}
                visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
                continue
            run(
                "read_detail_batch",
                [
                    "--batch-max-captures",
                    str(args.batch_max_captures),
                    "--batch-stop-after-no-new-content",
                    str(args.batch_stop_after_no_new_content),
                    "--wheel-clicks",
                    str(args.wheel_clicks),
                ],
            )
            match = run("match")
            decision = (match.get("match_decision") or {}).get("decision")
            attempt: dict[str, Any] = {
                "job_index": job_index,
                "scroll_round": scroll_round,
                "match_decision": decision,
                "job_title": (match.get("detail") or {}).get("title"),
                "company": (match.get("detail") or {}).get("company"),
            }
            if not _apply_decision_allowed(decision, allow_maybe_apply=bool(args.allow_maybe_apply)):
                attempt["status"] = "skipped_match_not_eligible"
                if decision == "maybe_apply":
                    attempt["reason"] = "maybe_apply_requires_explicit_allow_maybe_apply"
                job_attempts.append(attempt)
                continue
            apply_args = ["--allow-maybe-apply"] if args.allow_maybe_apply else []
            execute_apply = run(
                "execute_apply_entry",
                [
                    "--post-apply-capture-wait-seconds",
                    str(args.post_apply_capture_wait_seconds),
                    *apply_args,
                ],
            )
            if execute_apply.get("status") == "skipped":
                attempt["status"] = "skipped_apply_entry_execute"
                attempt["apply_entry_stop_reason"] = (execute_apply.get("apply_entry") or {}).get("stop_reason")
                job_attempts.append(attempt)
                continue
            apply_state = _apply_entry_state(execute_apply)
            if not _station_internal_application_started(execute_apply):
                attempt["status"] = "skipped_apply_entry_execute"
                attempt["apply_entry_stop_reason"] = apply_state.get("stop_reason")
                attempt["apply_entry_state_type"] = apply_state.get("state_type")
                job_attempts.append(attempt)
                if _external_apply_flow_started(execute_apply):
                    if attempted_jobs >= args.max_jobs:
                        return _write_speed_demo_result(
                            run_dir,
                            started=started,
                            args=args,
                            steps=steps,
                            job_attempts=job_attempts,
                            result_scrolls=result_scrolls,
                            status="needs_work",
                            stop_reason="external_apply_flow_opened_no_remaining_job_budget",
                            extra={
                                "external_apply_state": apply_state,
                                "safety_note": "external ATS opened after the final allowed job attempt",
                            },
                        )
                    recovery = _recover_seek_results_after_external_apply(run=run, args=args)
                    attempt["external_apply_recovery"] = {
                        key: recovery.get(key)
                        for key in ("status", "reason", "visible_jobs", "open_status")
                        if key in recovery
                    }
                    if recovery.get("status") != "ok":
                        return _write_speed_demo_result(
                            run_dir,
                            started=started,
                            args=args,
                            steps=steps,
                            job_attempts=job_attempts,
                            result_scrolls=result_scrolls,
                            status="needs_work",
                            stop_reason="external_apply_flow_opened_cannot_recover_seek_results",
                            extra={
                                "external_apply_state": apply_state,
                                "external_apply_recovery": recovery,
                                "safety_note": "external ATS opened and SEEK result scope could not be re-established",
                            },
                        )
                    cards_payload = recovery.get("cards_payload") if isinstance(recovery.get("cards_payload"), dict) else {}
                    visible_cards = recovery.get("visible_cards") if isinstance(recovery.get("visible_cards"), list) else []
                    continue
                if attempted_jobs >= args.max_jobs:
                    continue
                cards_payload = run("extract_cards").get("cards_payload") or {}
                visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
                continue
            attempt["status"] = "application_started"
            job_attempts.append(attempt)
            application_started = True
            break
        if application_started or attempted_jobs >= args.max_jobs:
            break
        if budget_exhausted(reserve_ms=15000):
            return budget_stop("time_budget_exhausted_before_results_scroll")
        scroll_round += 1
        previous_fingerprint = _cards_fingerprint(visible_cards)
        for scroll_attempt in range(3):
            requested_wheel_clicks = args.results_scroll_wheel_clicks * (scroll_attempt + 1)
            wheel_clicks = _clamp_scroll_wheel_clicks(requested_wheel_clicks)
            if scroll_attempt < 2:
                scroll_response = _scroll_results_list(args.base_url, timeout=args.timeout, wheel_clicks=wheel_clicks)
                scroll_scope = "results_list"
            else:
                scroll_response = _scroll_results_page(args.base_url, timeout=args.timeout, wheel_clicks=wheel_clicks)
                scroll_scope = "page"
            cards_payload = run("extract_cards").get("cards_payload") or {}
            visible_cards = cards_payload.get("jobs") if isinstance(cards_payload.get("jobs"), list) else []
            current_fingerprint = _cards_fingerprint(visible_cards)
            changed = bool(current_fingerprint and current_fingerprint != previous_fingerprint)
            result_scrolls.append(
                {
                    "scroll_round": scroll_round,
                    "attempt": scroll_attempt,
                    "scope": scroll_scope,
                    "wheel_clicks": wheel_clicks,
                    "requested_wheel_clicks": requested_wheel_clicks,
                    "wheel_clicks_clamped": wheel_clicks != requested_wheel_clicks,
                    "success": scroll_response.get("success") is True,
                    "message": scroll_response.get("message"),
                    "card_fingerprint_changed": changed,
                }
            )
            if changed:
                break
        if not visible_exhausted and scroll_round >= args.max_result_scrolls:
            break
        if scroll_round >= args.max_result_scrolls:
            break
    if not application_started:
        return _write_speed_demo_result(
            run_dir,
            started=started,
            args=args,
            steps=steps,
            job_attempts=job_attempts,
            result_scrolls=result_scrolls,
            status="needs_work",
            stop_reason="no_eligible_station_internal_apply_entry",
        )
    last_flow_state: dict[str, Any] = {}
    for _ in range(args.max_application_steps):
        if budget_exhausted(reserve_ms=12000):
            return budget_stop(
                "time_budget_exhausted_before_application_step",
                extra={"application_started": application_started, "last_flow_state": last_flow_state},
            )
        payload = run(
            "continue_application_flow",
            [
                "--fill-safe-fields",
                "--allow-cover-letter-fill",
                "--max-safe-fields-to-fill",
                str(args.max_safe_fields_to_fill),
            ],
        )
        if isinstance(payload.get("application_flow_state"), dict):
            last_flow_state = payload["application_flow_state"]
        elif isinstance(payload.get("post_apply_wait"), dict) and isinstance(
            payload["post_apply_wait"].get("application_flow_state"), dict
        ):
            last_flow_state = payload["post_apply_wait"]["application_flow_state"]
        if payload.get("status") == "blocked_need_user_or_gpt_decision":
            application_stop_status = str(payload.get("status") or "")
            application_stop_reason = str(last_flow_state.get("stop_reason") or payload.get("stop_reason") or "")
            break
        if "continue_application_flow" not in (payload.get("next_allowed_steps") or []):
            break

    record_path = run_dir / "application_fill_record.json"
    record = build_record_from_debug_run(run_dir)
    _write_json(record_path, record)
    final_review: dict[str, Any] = {
        "status": "not_attempted",
        "reason": "not_at_review_and_submit",
        "application_flow_state": last_flow_state,
    }
    extraction_path = run_dir / "final_review_extraction.json"
    extraction: dict[str, Any] = {
        "contract_version": "seek_final_review_extraction_v1",
        "status": "not_attempted",
        "reason": "not_at_review_and_submit",
        "current_step": last_flow_state.get("current_step"),
        "state_type": last_flow_state.get("state_type"),
    }
    if _final_review_ready(last_flow_state):
        final_review = run("extract_final_review", ["--application-fill-record", str(record_path)])
        extraction_path = Path(str(final_review.get("final_review_extraction_path") or extraction_path))
        extraction = _read_json(extraction_path) if extraction_path.exists() else {}
    else:
        _write_json(extraction_path, extraction)
    artifact = build_seek_application_flow_artifact(
        record,
        final_review_extraction=extraction,
        record_path=record_path,
        final_review_extraction_path=extraction_path,
    )
    artifact_path = run_dir / "seek_application_flow_artifact.json"
    _write_json(artifact_path, artifact)
    readiness = build_demo_readiness_report(
        run_dir=run_dir,
        step_reports=load_step_reports(run_dir),
        application_fill_record=record,
        final_review_audit=extraction,
        long_read_benchmark=None,
        time_budget_ms=args.time_budget_ms,
    )
    readiness_path = run_dir / "demo_readiness_report.json"
    _write_json(readiness_path, readiness)
    total_ms = round((time.perf_counter() - started) * 1000, 3)
    result = {
        "contract_version": "seek_speed_demo_run_v1",
        "status": "pass" if readiness.get("status") == "pass" and extraction.get("status") == "pass" else "needs_work",
        "run_dir": str(run_dir),
        "total_ms": total_ms,
        "time_budget_ms": args.time_budget_ms,
        "within_budget": total_ms <= args.time_budget_ms,
        "steps": steps,
        "job_attempts": job_attempts,
        "result_scrolls": result_scrolls,
        "application_fill_record_path": str(record_path),
        "final_review_extraction_path": str(extraction_path),
        "artifact_path": str(artifact_path),
        "readiness_report_path": str(readiness_path),
        "readiness_status": readiness.get("status"),
        "final_review_status": extraction.get("status"),
        "application_stop_status": application_stop_status,
        "application_stop_reason": application_stop_reason,
        "final_submissions": extraction.get("final_submissions", record.get("final_submissions", 0)),
        "submit_clicks": extraction.get("submit_clicks", record.get("submit_clicks", 0)),
    }
    _write_json(run_dir / "speed_demo_report.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a timed SEEK demo path using the existing debug step runner.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--url", default=DEFAULT_SEARCH_URL)
    parser.add_argument("--job-index", type=int, default=0)
    parser.add_argument("--max-jobs", type=int, default=5)
    parser.add_argument("--allow-maybe-apply", action="store_true")
    parser.add_argument("--visible-jobs-per-page", type=int, default=4)
    parser.add_argument("--max-result-scrolls", type=int, default=3)
    parser.add_argument("--results-scroll-wheel-clicks", type=int, default=9)
    parser.add_argument("--window-width", type=int, default=2560)
    parser.add_argument("--window-height", type=int, default=1400)
    parser.add_argument("--wheel-clicks", type=int, default=9)
    parser.add_argument("--batch-max-captures", type=int, default=3)
    parser.add_argument("--batch-stop-after-no-new-content", type=int, default=2)
    parser.add_argument("--post-apply-capture-wait-seconds", type=float, default=1.0)
    parser.add_argument("--max-application-steps", type=int, default=6)
    parser.add_argument("--max-safe-fields-to-fill", type=int, default=5)
    parser.add_argument("--time-budget-ms", type=float, default=300000.0)
    parser.add_argument("--close-old-windows", action="store_true")
    parser.add_argument(
        "--disable-learned-fast-mode",
        action="store_true",
        help="Disable learned SEEK card pruning. Useful for broad exploratory runs, slower for the 3-minute demo path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        result = run_speed_demo(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"success": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
