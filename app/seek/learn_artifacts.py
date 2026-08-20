from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LEARNED_APP_PROFILE_CONTRACT = "learned_app_profile_v1"
PATH_GRAPH_SEED_CONTRACT = "path_graph_seed_v1"
LEARN_ARTIFACT_BUNDLE_CONTRACT = "seek_learn_artifact_export_v1"


def build_seek_learn_artifacts(
    report: dict[str, Any] | None,
    *,
    trace: dict[str, Any] | None = None,
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build Learn Mode artifacts from a stable SEEK traversal report and trace."""

    payload = report if isinstance(report, dict) else {}
    trace_payload = trace if isinstance(trace, dict) else {}
    learned_app_profile = build_learned_app_profile(
        payload,
        trace=trace_payload,
        report_path=report_path,
        trace_path=trace_path,
    )
    path_graph_seed = build_path_graph_seed(payload, trace=trace_payload)
    return {
        "contract_version": LEARN_ARTIFACT_BUNDLE_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "report_path": str(report_path) if report_path else None,
            "trace_path": str(trace_path) if trace_path else None,
            "report_contract": payload.get("contract_version"),
            "trace_contract": trace_payload.get("contract_version"),
        },
        "learned_app_profile": learned_app_profile,
        "path_graph_seed": path_graph_seed,
        "baseline": _baseline(payload),
    }


def build_learned_app_profile(
    report: dict[str, Any] | None,
    *,
    trace: dict[str, Any] | None = None,
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else {}
    trace_payload = trace if isinstance(trace, dict) else {}
    observed_titles = [
        str((event.get("card") or {}).get("title") or "").strip()
        for event in _events(payload, trace_payload)
        if isinstance(event.get("card"), dict) and str((event.get("card") or {}).get("title") or "").strip()
    ]
    return {
        "contract_version": LEARNED_APP_PROFILE_CONTRACT,
        "profile_id": "seek_search_results_detail_mvp_v1",
        "app_id": "seek",
        "site": "seek.co.nz",
        "page_type": "seek_search_results_with_detail",
        "source_contracts": {
            "report": payload.get("contract_version"),
            "traversal_trace": trace_payload.get("contract_version"),
            "report_path": str(report_path) if report_path else None,
            "trace_path": str(trace_path) if trace_path else None,
        },
        "evidence_summary": {
            **_baseline(payload),
            "observed_job_titles": observed_titles[:10],
            "traversal_event_count": len(_events(payload, trace_payload)),
        },
        "scroll_containers": _scroll_containers(),
        "entity_patterns": _entity_patterns(),
        "action_templates": _action_templates(),
        "verification_rules": _verification_rules(),
        "safety_policy": _safety_policy(),
    }


def build_path_graph_seed(report: dict[str, Any] | None, *, trace: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = report if isinstance(report, dict) else {}
    trace_payload = trace if isinstance(trace, dict) else {}
    sample_cards = []
    sample_visual_controls = []
    seen_visual_assets: set[str] = set()
    for event in _events(payload, trace_payload):
        card = event.get("card") if isinstance(event.get("card"), dict) else {}
        if card:
            sample_cards.append(
                {
                    "title": card.get("title"),
                    "company": card.get("company"),
                    "location": card.get("location"),
                    "card_bbox": card.get("card_bbox"),
                    "click_point": card.get("click_point"),
                }
            )
        detail = event.get("detail_read") if isinstance(event.get("detail_read"), dict) else {}
        control = _visual_control_sample_from_apply_state(detail.get("apply_button_state"))
        if control and control["asset_id"] not in seen_visual_assets:
            sample_visual_controls.append(control)
            seen_visual_assets.add(control["asset_id"])
    return {
        "contract_version": PATH_GRAPH_SEED_CONTRACT,
        "seed_id": "seek_search_results_detail_path_seed_v1",
        "app_id": "seek",
        "page_type": "seek_search_results_with_detail",
        "coordinate_space": "window_screenshot",
        "sections": [
            {
                "section_id": "top_search_area",
                "role": "search_controls",
                "label": "SEEK top search and filters area",
                "contains": ["search_keywords", "search_location", "filters"],
            },
            {
                "section_id": "results_list",
                "role": "list",
                "label": "SEEK left job results list",
                "container_id": "seek:results_list",
                "contains": ["job_card"],
            },
            {
                "section_id": "job_detail",
                "role": "detail",
                "label": "SEEK right job detail pane",
                "container_id": "seek:job_detail",
                "contains": ["detail_header", "detail_body"],
            },
            {
                "section_id": "job_card",
                "role": "entity_card",
                "label": "Job result card",
                "parent_section_id": "results_list",
                "repeatable": True,
            },
            {
                "section_id": "detail_header",
                "role": "detail_header",
                "label": "Opened job title/company/apply area",
                "parent_section_id": "job_detail",
            },
            {
                "section_id": "detail_body",
                "role": "detail_body",
                "label": "Opened job description body",
                "parent_section_id": "job_detail",
            },
        ],
        "edges": [
            {"from": "top_search_area", "to": "results_list", "relation": "filters_or_search_updates"},
            {"from": "results_list", "to": "job_card", "relation": "contains_repeated"},
            {"from": "job_card", "to": "job_detail", "relation": "open_job_card_updates_detail"},
            {"from": "job_detail", "to": "detail_header", "relation": "contains"},
            {"from": "job_detail", "to": "detail_body", "relation": "contains"},
        ],
        "action_bindings": {
            "open_job_card": {
                "source_section_id": "job_card",
                "target_section_id": "job_detail",
                "required_container_id": "seek:results_list",
            },
            "read_detail": {
                "source_section_id": "job_detail",
                "scroll_container_id": "seek:job_detail",
            },
            "load_more_results": {
                "source_section_id": "results_list",
                "scroll_container_id": "seek:results_list",
            },
        },
        "sample_entities": {
            "job_cards": sample_cards[:10],
            "visual_controls": sample_visual_controls[:20],
        },
        "safety_policy_ref": "seek_final_submit_forbidden_v1",
    }


def extract_learned_app_profile(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(artifact, dict):
        return None
    if artifact.get("contract_version") == LEARNED_APP_PROFILE_CONTRACT:
        return artifact
    profile = artifact.get("learned_app_profile")
    return profile if isinstance(profile, dict) and profile.get("contract_version") == LEARNED_APP_PROFILE_CONTRACT else None


def action_template(artifact: dict[str, Any] | None, action_id: str) -> dict[str, Any] | None:
    profile = extract_learned_app_profile(artifact)
    if not profile:
        return None
    for item in profile.get("action_templates") or []:
        if isinstance(item, dict) and item.get("action_id") == action_id:
            return item
    return None


def scroll_target_for_action(
    artifact: dict[str, Any] | None,
    action_id: str,
    *,
    default_pane: str,
    default_container_id: str,
) -> dict[str, str]:
    template = action_template(artifact, action_id) or {}
    target = template.get("scroll_target") if isinstance(template.get("scroll_target"), dict) else {}
    return {
        "target_pane": str(target.get("target_pane") or default_pane),
        "target_container_id": str(target.get("target_container_id") or default_container_id),
        "source": "learned_app_profile_v1" if target else "default_seek_runner",
    }


def action_metadata(artifact: dict[str, Any] | None, action_id: str) -> dict[str, Any]:
    template = action_template(artifact, action_id) or {}
    profile = extract_learned_app_profile(artifact) or {}
    metadata: dict[str, Any] = {}
    if profile:
        metadata["learned_app_profile_ref"] = {
            "contract_version": "learned_app_profile_ref_v1",
            "profile_id": profile.get("profile_id"),
            "page_type": profile.get("page_type"),
            "action_id": action_id,
        }
    for source_key, target_key in (
        ("candidate_constraints", "candidate_constraints"),
        ("verification_policy", "verification_policy"),
        ("safety_policy", "learned_safety_policy"),
    ):
        value = template.get(source_key) if source_key != "safety_policy" else profile.get("safety_policy")
        if isinstance(value, dict):
            metadata[target_key] = value
    return metadata


def _scroll_containers() -> list[dict[str, Any]]:
    return [
        {
            "container_id": "seek:page",
            "role": "page",
            "scroll_scope": "page",
            "axis": "vertical",
            "used_by": [],
        },
        {
            "container_id": "seek:results_list",
            "role": "results_list",
            "scroll_scope": "container",
            "axis": "vertical",
            "used_by": ["open_job_card", "load_more_results"],
        },
        {
            "container_id": "seek:job_detail",
            "role": "job_detail",
            "scroll_scope": "container",
            "axis": "vertical",
            "used_by": ["read_detail", "apply_entry"],
        },
    ]


def _entity_patterns() -> list[dict[str, Any]]:
    return [
        {
            "entity_type": "job_card",
            "section_id": "results_list",
            "source_contract": "seek_job_card_v1",
            "required_fields": ["title", "company", "card_bbox", "click_point"],
            "optional_fields": ["location", "posted_at_text", "work_type", "salary_text", "classification"],
            "reject_if": ["filter_card", "right_detail_text", "overwide_bbox", "incomplete_title"],
        },
        {
            "entity_type": "job_detail",
            "section_id": "job_detail",
            "source_contract": "seek_job_detail_v1",
            "required_fields": ["title", "company", "location", "description_sections", "role_evidence"],
            "scroll_until": "seek_job_detail_completeness_v1.complete",
        },
    ]


def _action_templates() -> list[dict[str, Any]]:
    return [
        {
            "action_id": "open_job_card",
            "goal_template": "Click the SEEK job result card titled {title} at {company}",
            "target_entity": "job_card",
            "scroll_target": {"target_pane": "results_list", "target_container_id": "seek:results_list"},
            "candidate_constraints": {
                "required_container_id": "seek:results_list",
                "use_seeded_candidate": True,
                "seed_source_contract": "seek_job_card_v1",
                "require_card_bbox": True,
                "require_click_point": True,
                "require_point_inside_seed_bbox": True,
            },
            "verification_policy": {
                "post_click": "detail_title_company_must_match_clicked_card",
                "failure_reason": "post_click_layout_drift",
            },
            "forbidden_targets": ["Apply", "Quick Apply", "Save", "Submit", "Send application", "Complete application"],
        },
        {
            "action_id": "read_detail",
            "target_entity": "job_detail",
            "scroll_target": {"target_pane": "job_detail", "target_container_id": "seek:job_detail"},
            "verification_policy": {
                "complete_contract": "seek_job_detail_completeness_v1",
                "required_evidence": ["title", "company", "location", "description_sections", "role_evidence"],
            },
        },
        {
            "action_id": "load_more_results",
            "target_entity": "results_list",
            "scroll_target": {"target_pane": "results_list", "target_container_id": "seek:results_list"},
            "verification_policy": {
                "target_container_content_should_change": True,
                "wrong_scope_detected_must_be_false": True,
            },
        },
        {
            "action_id": "apply_entry",
            "target_entity": "apply_button",
            "scroll_target": {"target_pane": "job_detail", "target_container_id": "seek:job_detail"},
            "candidate_constraints": {"required_container_id": "seek:job_detail", "forbid_final_submit": True},
            "verification_policy": {"pre_apply_detail_verification_required": True, "stop_after_application_state_observe": True},
        },
    ]


def _verification_rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "open_job_card_detail_match",
            "applies_to": ["open_job_card"],
            "required": True,
            "description": "After a card click, the right detail title/company must match the clicked card.",
        },
        {
            "rule_id": "read_detail_scroll_scope",
            "applies_to": ["read_detail"],
            "required_container_id": "seek:job_detail",
            "required": True,
        },
        {
            "rule_id": "load_more_results_scroll_scope",
            "applies_to": ["load_more_results"],
            "required_container_id": "seek:results_list",
            "required": True,
        },
        {
            "rule_id": "final_submit_forbidden",
            "applies_to": ["apply_entry", "safe_fill", "all_actions"],
            "required": True,
            "forbidden_terms": ["Submit", "Send application", "Complete application", "Review and submit", "Finish application"],
        },
    ]


def _safety_policy() -> dict[str, Any]:
    return {
        "policy_id": "seek_final_submit_forbidden_v1",
        "final_submit": "forbidden",
        "forbidden_actions": ["Submit", "Send application", "Complete application", "Review and submit", "Finish application"],
        "real_clicks_require": ["recognition_plan_v1", "pre_click_decision_v1.allowed", "post_click_verification"],
        "apply_entry_requires": ["strong_apply", "pre_apply_detail_verification_v1", "final_submit_guard_v1"],
        "safe_fill_requires": ["candidate_profile_readiness_v1.live_smoke_ready", "safe_form_fill_trace_v1", "post_fill_verification_v1"],
    }


def _events(report: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    trace_events = [item for item in trace.get("traversal_events") or [] if isinstance(item, dict)]
    if trace_events:
        return trace_events
    return [item for item in report.get("traversal_steps") or [] if isinstance(item, dict)]


def _visual_control_sample_from_apply_state(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("visible") is not True:
        return None
    label = str(value.get("label") or "").strip()
    bbox = value.get("bbox") if isinstance(value.get("bbox"), dict) else None
    if not label or not bbox:
        return None
    label_key = label.casefold()
    if any(term in label_key for term in ("submit", "send", "confirm", "payment", "complete application")):
        semantic_action = "final_submit"
        danger_level = "final_submit"
        asset_id = "seek:visual:final_submit_button"
    elif "quick" in label_key and "apply" in label_key:
        semantic_action = "open_apply_flow"
        danger_level = "low"
        asset_id = "seek:visual:quick_apply_button"
    elif "apply" in label_key:
        semantic_action = "external_apply_flow"
        danger_level = "external_flow_entry"
        asset_id = "seek:visual:apply_button"
    else:
        return None
    return {
        "asset_id": asset_id,
        "label": label,
        "semantic_action": semantic_action,
        "danger_level": danger_level,
        "region_id": "job_detail",
        "container_id": "seek:job_detail",
        "bbox": bbox,
        "click_point": value.get("click_point"),
        "source": value.get("candidate_freshness", {}).get("source") if isinstance(value.get("candidate_freshness"), dict) else "seek_apply_button_state",
    }


def _baseline(report: dict[str, Any]) -> dict[str, Any]:
    accuracy = report.get("accuracy_summary") if isinstance(report.get("accuracy_summary"), dict) else {}
    return {
        "jobs_seen": _int(report.get("jobs_seen")),
        "jobs_opened": _int(report.get("jobs_opened")),
        "jobs_fully_read": _int(report.get("jobs_fully_read")),
        "post_click_layout_drift_count": _int(accuracy.get("post_click_layout_drift_count")),
        "wrong_scope_scroll_count": _int(accuracy.get("wrong_scope_scroll_count")),
        "final_submissions": _int(report.get("final_submissions")),
        "submit_clicks": _int(report.get("submit_clicks")),
        "accuracy_status": accuracy.get("status"),
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
