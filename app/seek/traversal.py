from __future__ import annotations

from typing import Any


DEFAULT_MAX_DETAIL_SCROLLS = 4
DEFAULT_REQUIRED_DETAIL_SECTIONS: tuple[str, ...] = ()


def merge_seek_job_details(details: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Merge visible SEEK detail slices collected while scrolling the right detail pane."""

    items = [item for item in details if isinstance(item, dict)]
    if not items:
        return {
            "contract_version": "seek_job_detail_v1",
            "job_id": "seek_job_unknown",
            "title": None,
            "company": None,
            "location": None,
            "work_type": None,
            "classification": None,
            "salary_text": None,
            "description_sections": [],
            "requirements": [],
            "responsibilities": [],
            "benefits": [],
            "apply_button_state": {"visible": False, "label": None, "bbox": None, "click_point": None},
            "save_button_state": {"visible": False, "label": None, "bbox": None},
            "detail_container": None,
            "detail_scroll_history": [],
            "trace_paths": [],
            "evidence": {"text_count": 0, "action_count": 0, "texts": [], "source_contract": None},
        }

    merged = dict(items[0])
    merged["contract_version"] = "seek_job_detail_v1"
    for field in ("job_id", "title", "company", "location", "work_type", "classification", "salary_text", "detail_container"):
        merged[field] = _first_present(items, field)

    merged["description_sections"] = _unique_sections(
        section for item in items for section in _list_of_dicts(item.get("description_sections"))
    )
    for field in ("requirements", "responsibilities", "benefits"):
        merged[field] = _unique_strings(text for item in items for text in _list_of_strings(item.get(field)))

    merged["apply_button_state"] = _preferred_button_state(items, "apply_button_state")
    merged["save_button_state"] = _preferred_button_state(items, "save_button_state")
    merged["detail_scroll_history"] = _unique_scroll_history(
        entry for item in items for entry in _list_of_dicts(item.get("detail_scroll_history"))
    )
    merged["trace_paths"] = _unique_strings(path for item in items for path in _list_of_strings(item.get("trace_paths")))
    merged["evidence"] = _merge_evidence(items)
    return merged


def assess_seek_job_detail_completeness(
    detail: dict[str, Any] | None,
    *,
    scroll_count: int = 0,
    max_scrolls: int = DEFAULT_MAX_DETAIL_SCROLLS,
    required_sections: tuple[str, ...] = DEFAULT_REQUIRED_DETAIL_SECTIONS,
) -> dict[str, Any]:
    """Decide whether the traversal runner should keep scrolling the SEEK detail pane."""

    payload = detail if isinstance(detail, dict) else {}
    missing: list[str] = []
    for field in ("title", "company", "location"):
        if not payload.get(field):
            missing.append(field)
    if not _list_of_dicts(payload.get("description_sections")):
        missing.append("description_sections")
    if not _has_role_evidence(payload):
        missing.append("role_evidence")
    for section in required_sections:
        if not _list_of_strings(payload.get(section)):
            missing.append(section)

    complete = not missing
    can_scroll = int(scroll_count) < int(max_scrolls)
    should_scroll = bool(missing and can_scroll)
    if complete:
        stop_reason = "complete"
    elif can_scroll:
        stop_reason = "missing_evidence"
    else:
        stop_reason = "max_scrolls_reached"
    return {
        "contract_version": "seek_job_detail_completeness_v1",
        "complete": complete,
        "should_scroll": should_scroll,
        "missing_evidence": missing,
        "scroll_count": int(scroll_count),
        "max_scrolls": int(max_scrolls),
        "stop_reason": stop_reason,
        "next_scroll_request": _next_detail_scroll_request(missing) if should_scroll else None,
    }


def _has_role_evidence(detail: dict[str, Any]) -> bool:
    return bool(_list_of_strings(detail.get("responsibilities")) or _list_of_strings(detail.get("requirements")))


def build_seek_mvp_run_report(
    *,
    job_cards: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    job_details: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    match_decisions: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    started_application_flows: int = 0,
    cover_letters_generated: int = 0,
    forms_filled_until_review: int = 0,
    elapsed_ms: float | int | None = None,
) -> dict[str, Any]:
    """Build the no-final-submit SEEK MVP report shell for traversal runs."""

    cards = [item for item in job_cards if isinstance(item, dict)]
    details = [item for item in job_details if isinstance(item, dict)]
    decisions = [item for item in match_decisions or [] if isinstance(item, dict)]
    decision_counts = {
        "strong_apply": 0,
        "maybe_apply": 0,
        "skip": 0,
        "need_user_review": 0,
    }
    for decision in decisions:
        value = decision.get("decision")
        if value in decision_counts:
            decision_counts[value] += 1
    report = {
        "contract_version": "seek_mvp_run_report_v1",
        "jobs_seen": len(cards),
        "jobs_opened": len(details),
        "jobs_fully_read": sum(
            1
            for detail in details
            if assess_seek_job_detail_completeness(detail, scroll_count=DEFAULT_MAX_DETAIL_SCROLLS)["complete"]
        ),
        **decision_counts,
        "application_flows_started": int(started_application_flows),
        "cover_letters_generated": int(cover_letters_generated),
        "forms_filled_until_review": int(forms_filled_until_review),
        "final_submissions": 0,
        "elapsed_ms": elapsed_ms,
        "match_decisions": decisions,
        "jobs": [
            {
                "job_id": detail.get("job_id") or card.get("job_id"),
                "card": card,
                "detail": detail if index < len(details) else None,
                "match_decision": decisions[index] if index < len(decisions) else None,
            }
            for index, card in enumerate(cards)
            for detail in [details[index] if index < len(details) else {}]
        ],
        "accuracy_notes": [],
    }
    report["accuracy_summary"] = build_seek_mvp_accuracy_summary(report)
    return report


def build_seek_mvp_accuracy_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    """Summarize SEEK MVP quality and safety signals from a run report."""

    payload = report if isinstance(report, dict) else {}
    jobs_seen = _int(payload.get("jobs_seen"))
    jobs_opened = _int(payload.get("jobs_opened"))
    jobs_fully_read = _int(payload.get("jobs_fully_read"))
    decisions = _list_of_dicts(payload.get("match_decisions"))
    traversal_steps = _list_of_dicts(payload.get("traversal_steps"))
    apply_entries = _list_of_dicts(payload.get("apply_entries"))
    result_scrolls = _list_of_dicts(payload.get("results_list_scrolls"))
    detail_scrolls = _detail_scrolls_from_report(payload)
    attempted_card_clicks = [step.get("card_click") for step in traversal_steps if isinstance(step.get("card_click"), dict)]
    opened_card_clicks = [click for click in attempted_card_clicks if click.get("opened") is True]
    post_click_drift_count = sum(1 for click in attempted_card_clicks if click.get("failure_reason") == "post_click_layout_drift")
    pre_click_detail_resets = [
        step.get("pre_click_detail_reset")
        for step in traversal_steps
        if isinstance(step.get("pre_click_detail_reset"), dict)
    ]
    pre_click_detail_reset_wrong_scope_count = sum(
        1
        for reset in pre_click_detail_resets
        if reset.get("wrong_scope_detected") is True or reset.get("target_container_id") != "seek:job_detail"
    )
    title_extraction_from_body_count = sum(
        1
        for click in attempted_card_clicks
        if isinstance(click.get("post_click_layout"), dict)
        and isinstance(click["post_click_layout"].get("post_click_detail_header"), dict)
        and click["post_click_layout"]["post_click_detail_header"].get("title_extraction_source") == "detail_body"
    )
    wrong_scope_scrolls = [
        {"kind": "results_list", **scroll}
        for scroll in result_scrolls
        if scroll.get("target_container_id") != "seek:results_list" or _wrong_scope(scroll)
    ] + [
        {"kind": "job_detail", **scroll}
        for scroll in detail_scrolls
        if scroll.get("target_container_id") != "seek:job_detail" or _wrong_scope(scroll)
    ]
    final_submit_blockers = [
        blocker
        for blocker in _list_of_dicts(payload.get("final_submit_visible_blockers"))
        if blocker.get("blocked") is True
    ]
    final_submissions = _int(payload.get("final_submissions"))
    submit_clicks = _int(payload.get("submit_clicks"))
    continue_clicks = _int(payload.get("continue_clicks"))
    safety_ok = bool(final_submissions == 0 and submit_clicks == 0 and not wrong_scope_scrolls)
    return {
        "contract_version": "seek_mvp_accuracy_summary_v1",
        "jobs_seen": jobs_seen,
        "jobs_opened": jobs_opened,
        "jobs_fully_read": jobs_fully_read,
        "opened_rate": _ratio(jobs_opened, jobs_seen),
        "detail_read_completion_rate": _ratio(jobs_fully_read, jobs_opened),
        "match_decision_coverage_rate": _ratio(len(decisions), jobs_opened),
        "card_click_attempts": len(attempted_card_clicks),
        "card_click_opened": len(opened_card_clicks),
        "card_click_open_rate": _ratio(len(opened_card_clicks), len(attempted_card_clicks)),
        "post_click_layout_drift_count": post_click_drift_count,
        "pre_click_detail_reset_count": len(pre_click_detail_resets),
        "pre_click_detail_reset_wrong_scope_count": pre_click_detail_reset_wrong_scope_count,
        "title_extraction_from_body_count": title_extraction_from_body_count,
        "results_list_scroll_count": len(result_scrolls),
        "detail_scroll_count": len(detail_scrolls),
        "wrong_scope_scroll_count": len(wrong_scope_scrolls),
        "wrong_scope_scrolls": [
            {
                "kind": scroll.get("kind"),
                "target_pane": scroll.get("target_pane"),
                "target_container_id": scroll.get("target_container_id"),
                "trace_path": scroll.get("trace_path"),
            }
            for scroll in wrong_scope_scrolls[:10]
        ],
        "apply_entry_count": len(apply_entries),
        "application_flow_started_count": sum(1 for entry in apply_entries if entry.get("application_flow_started") is True),
        "final_submit_visible_blocker_count": len(final_submit_blockers),
        "safety_invariants": {
            "final_submissions_zero": final_submissions == 0,
            "submit_clicks_zero": submit_clicks == 0,
            "continue_clicks_zero": continue_clicks == 0,
            "wrong_scope_scrolls_zero": not wrong_scope_scrolls,
        },
        "status": "pass" if safety_ok else "needs_review",
    }


def _first_present(items: list[dict[str, Any]], field: str) -> Any:
    for item in items:
        value = item.get(field)
        if value not in (None, "", [], {}):
            return value
    return None


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if str(item or "").strip()]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 3)


def _wrong_scope(scroll: dict[str, Any]) -> bool:
    effect = scroll.get("effect_validation") if isinstance(scroll.get("effect_validation"), dict) else {}
    if not effect and isinstance(scroll.get("scroll_effect_validation"), dict):
        effect = scroll["scroll_effect_validation"]
    return effect.get("wrong_scope_detected") is True


def _detail_scrolls_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    scrolls: list[dict[str, Any]] = []
    for job in _list_of_dicts(report.get("jobs")):
        detail = job.get("detail") if isinstance(job.get("detail"), dict) else {}
        scrolls.extend(_list_of_dicts(detail.get("detail_scroll_history")))
    for step in _list_of_dicts(report.get("traversal_steps")):
        detail_read = step.get("detail_read") if isinstance(step.get("detail_read"), dict) else {}
        scrolls.extend(_list_of_dicts(detail_read.get("detail_scrolls")))
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for scroll in scrolls:
        key = str(scroll.get("trace_path") or json_like_key(scroll))
        if key in seen:
            continue
        seen.add(key)
        unique.append(scroll)
    return unique


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _unique_sections(values: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for section in values:
        text = " ".join(str(section.get("text") or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append({**section, "index": len(result), "text": text})
    return result


def _preferred_button_state(items: list[dict[str, Any]], field: str) -> dict[str, Any]:
    fallback: dict[str, Any] = {"visible": False, "label": None, "bbox": None}
    if field == "apply_button_state":
        fallback["click_point"] = None
    for item in items:
        state = item.get(field) if isinstance(item.get(field), dict) else {}
        if state.get("visible") is True:
            return state
        if any(value not in (None, "", [], {}) for value in state.values()):
            fallback = {**fallback, **state}
    return fallback


def _merge_evidence(items: list[dict[str, Any]]) -> dict[str, Any]:
    texts = _unique_strings(
        text
        for item in items
        for text in _list_of_strings((item.get("evidence") or {}).get("texts") if isinstance(item.get("evidence"), dict) else [])
    )
    return {
        "text_count": len(texts),
        "action_count": sum(
            int((item.get("evidence") or {}).get("action_count") or 0)
            for item in items
            if isinstance(item.get("evidence"), dict)
        ),
        "texts": texts,
        "source_contract": "merged_seek_job_detail_v1",
    }


def _unique_scroll_history(values: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for entry in values:
        trace_path = str(entry.get("trace_path") or "")
        missing = ",".join(_list_of_strings(entry.get("missing_evidence")))
        key = trace_path or json_like_key(entry)
        if missing:
            key = f"{key}|{missing}"
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def json_like_key(value: Any) -> str:
    if isinstance(value, dict):
        return "|".join(f"{key}={json_like_key(value[key])}" for key in sorted(value))
    if isinstance(value, list):
        return ",".join(json_like_key(item) for item in value)
    return str(value)


def _next_detail_scroll_request(missing: list[str]) -> dict[str, Any]:
    return {
        "contract_version": "scroll_request_v2",
        "scroll_scope": "container",
        "target_pane": "job_detail",
        "target_container_id": "seek:job_detail",
        "direction": "down",
        "wheel_clicks": 4,
        "reason": "seek_detail_missing_evidence",
        "missing_evidence": missing,
        "expected_effect": {
            "target_container_content_should_change": True,
            "same_semantic_page_should_remain": True,
            "non_target_panes_should_remain_mostly_stable": True,
        },
    }
