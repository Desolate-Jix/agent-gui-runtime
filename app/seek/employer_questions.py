from __future__ import annotations

import hashlib
import json
import re
from typing import Any


QUESTION_INVENTORY_CONTRACT = "employer_question_inventory_v1"
OPTION_SELECTION_CONTRACT = "employer_question_option_selection_v1"
ANSWER_PLAN_CONTRACT = "employer_question_answer_plan_v1"
ANSWER_PREVIEW_CONTRACT = "employer_question_answer_preview_v1"
PROGRAMMING_OPTION_LABELS = {
    ".net",
    "c",
    "c#",
    "c++",
    "css",
    "go",
    "html",
    "java",
    "javascript",
    "php",
    "python",
    "ruby",
    "scala",
    "swift",
    "typescript",
    "visual basic",
}


def build_employer_question_inventory(
    application_flow_state: dict[str, Any] | None,
    *,
    screen_reading: dict[str, Any] | None = None,
    max_group_height: int = 260,
) -> dict[str, Any]:
    """Build scoped employer-question groups from application form evidence."""

    state = application_flow_state if isinstance(application_flow_state, dict) else {}
    form = state.get("application_form_inventory") if isinstance(state.get("application_form_inventory"), dict) else {}
    reading = screen_reading if isinstance(screen_reading, dict) else {}
    items = _dedupe_items([*_inventory_items(form), *_screen_reading_items(reading)])
    questions = _merged_question_candidates(items)
    questions = _dedupe_questions([item for item in questions if item])
    questions.sort(key=lambda item: (_bbox_y(item.get("question_bbox")), _bbox_x(item.get("question_bbox"))))

    groups: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        next_question = questions[index + 1] if index + 1 < len(questions) else None
        next_y = _bbox_y(next_question.get("question_bbox")) if next_question else None
        group = _build_question_group(
            question,
            items=items,
            index=index,
            next_question_y=next_y,
            max_group_height=max_group_height,
        )
        groups.append(group)

    return {
        "contract_version": QUESTION_INVENTORY_CONTRACT,
        "current_step": state.get("current_step"),
        "question_count": len(groups),
        "questions": groups,
        "source_contracts": {
            "application_flow_state": state.get("contract_version"),
            "application_form_inventory": form.get("contract_version"),
            "screen_reading": reading.get("contract_version"),
        },
    }


def select_employer_question_option(
    question: dict[str, Any],
    *,
    planned_answer: str,
    score_gap_threshold: float = 0.12,
) -> dict[str, Any]:
    """Select an answer control only inside the current question group."""

    expected = _clean(planned_answer).casefold()
    candidates = [item for item in question.get("control_candidates") or [] if isinstance(item, dict)]
    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = _score_candidate_for_question(question, candidate, expected)
        if decision["hard_reject"]:
            rejected.append(decision)
        else:
            scored.append(decision)
    scored.sort(key=lambda item: item["score"], reverse=True)
    selected = scored[0] if scored else None
    runner_decision = "reject"
    reject_reason = "no_local_candidate"
    score_gap = None
    if selected:
        score_gap = round(float(selected["score"]) - float(scored[1]["score"]), 4) if len(scored) > 1 else 1.0
        if score_gap < score_gap_threshold:
            reject_reason = "ambiguous_duplicate_option"
        else:
            runner_decision = "allow"
            reject_reason = None

    local_expected_count = sum(1 for item in scored if _label_matches(item.get("candidate", {}), expected))
    global_expected_count = int(question.get("global_option_counts", {}).get(expected) or local_expected_count)
    return {
        "contract_version": OPTION_SELECTION_CONTRACT,
        "question_id": question.get("question_id"),
        "planned_answer": planned_answer,
        "runner_decision": runner_decision,
        "reject_reason": reject_reason,
        "selected_candidate": selected.get("candidate") if selected and runner_decision == "allow" else None,
        "score": selected.get("score") if selected else 0.0,
        "score_gap": score_gap,
        "scored_candidates": scored,
        "rejected_candidates": rejected,
        "duplicate_option_guard": {
            "global_expected_label_count": global_expected_count,
            "local_expected_label_count": local_expected_count,
            "selected_by": "question_group_proximity" if selected else None,
            "score_gap": score_gap,
            "ambiguous": reject_reason == "ambiguous_duplicate_option",
        },
    }


def build_employer_question_answer_plan(
    inventory: dict[str, Any] | None,
    *,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    """Map scoped employer questions to evidence-backed answers."""

    inv = inventory if isinstance(inventory, dict) else {}
    profile_payload = profile if isinstance(profile, dict) else {}
    plans = [_plan_answer(question, profile_payload) for question in inv.get("questions") or [] if isinstance(question, dict)]
    counts = {"ready": 0, "needs_user_review": 0, "blocked_sensitive": 0, "unsupported": 0}
    for plan in plans:
        status = str(plan.get("status") or "")
        if status in counts:
            counts[status] += 1
    ready_count = counts["ready"]
    question_count = len(plans)
    status = "ready" if question_count > 0 and ready_count == question_count else ("no_questions" if question_count == 0 else "needs_user_review")
    return {
        "contract_version": ANSWER_PLAN_CONTRACT,
        "status": status,
        "question_count": question_count,
        "ready_count": ready_count,
        "counts": counts,
        "answers": plans,
        "source_contracts": {
            "employer_question_inventory": inv.get("contract_version"),
            "profile": profile_payload.get("contract_version"),
        },
    }


def build_employer_question_answer_preview(
    answer_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build per-question dry-run answer targets without executing clicks or typing."""

    plan = answer_plan if isinstance(answer_plan, dict) else {}
    previews = [_preview_answer(item) for item in plan.get("answers") or [] if isinstance(item, dict)]
    counts = {"ready": 0, "needs_user_review": 0, "blocked": 0, "unsupported": 0}
    for item in previews:
        status = str(item.get("runner_decision") or "")
        if status == "allow":
            counts["ready"] += 1
        elif status == "reject":
            counts["blocked"] += 1
        elif status == "needs_user_review":
            counts["needs_user_review"] += 1
        else:
            counts["unsupported"] += 1
    status = "ready" if previews and counts["ready"] == len(previews) else ("no_questions" if not previews else "needs_user_review")
    return {
        "contract_version": ANSWER_PREVIEW_CONTRACT,
        "status": status,
        "question_count": len(previews),
        "ready_count": counts["ready"],
        "counts": counts,
        "previews": previews,
        "execute": False,
        "source_contracts": {
            "employer_question_answer_plan": plan.get("contract_version"),
        },
    }


def _preview_answer(item: dict[str, Any]) -> dict[str, Any]:
    base = {
        "contract_version": "employer_question_answer_preview_item_v1",
        "question_id": item.get("question_id"),
        "question_text": item.get("question_text"),
        "question_text_hash": item.get("question_text_hash"),
        "answer_category": item.get("answer_category"),
        "answer_type": item.get("answer_type"),
        "planned_answer": item.get("planned_answer"),
        "answer_source": item.get("answer_source"),
        "evidence": item.get("evidence"),
        "selected_value_candidates": item.get("selected_value_candidates") or [],
        "runner_decision": "reject",
        "reject_reason": None,
        "target": None,
        "dry_run_only": True,
        "requires_post_fill_verification": True,
    }
    if item.get("status") != "ready":
        base["runner_decision"] = "needs_user_review" if item.get("requires_user_review") else "reject"
        base["reject_reason"] = item.get("status") or "answer_not_ready"
        return base
    answer_type = str(item.get("answer_type") or "")
    if answer_type in {"radio_yes_no", "radio_choice", "select_choice"}:
        selection = item.get("selection") if isinstance(item.get("selection"), dict) else None
        if selection is None and answer_type == "select_choice":
            selected_value_match = _selected_value_match(item.get("selected_value_candidates"), item.get("planned_answer"))
            if selected_value_match:
                base["runner_decision"] = "allow"
                candidate = selected_value_match.get("candidate") if isinstance(selected_value_match.get("candidate"), dict) else {}
                if _select_choice_match_should_click(item.get("selected_value_candidates"), candidate):
                    clickable = _candidate_with_click_point(candidate)
                    base["requires_post_fill_verification"] = True
                    base["target"] = {
                        "action_type": "click",
                        "candidate": clickable,
                        "bbox": clickable.get("bbox"),
                        "click_point": clickable.get("click_point"),
                        "selection": selected_value_match,
                    }
                    return base
                base["requires_post_fill_verification"] = False
                base["target"] = {
                    "action_type": "already_selected",
                    "planned_answer": item.get("planned_answer"),
                    "selected_value_evidence": selected_value_match,
                }
                return base
            base["runner_decision"] = "needs_user_review"
            base["reject_reason"] = "select_choice_requires_dropdown_option_mapping"
            base["target"] = {
                "action_type": "select",
                "planned_answer": item.get("planned_answer"),
            }
            return base
        if not selection or selection.get("runner_decision") != "allow":
            base["reject_reason"] = (selection or {}).get("reject_reason") or "no_allowed_selection"
            base["target"] = {"selection": selection}
            return base
        candidate = selection.get("selected_candidate") if isinstance(selection.get("selected_candidate"), dict) else {}
        base["runner_decision"] = "allow"
        base["target"] = {
            "action_type": "click",
            "candidate": candidate,
            "bbox": candidate.get("bbox"),
            "click_point": candidate.get("click_point"),
            "selection": selection,
        }
        return base
    if answer_type == "text_input":
        candidate = _first_type_text_candidate(item.get("control_candidates"))
        if not candidate:
            base["runner_decision"] = "reject"
            base["reject_reason"] = "no_text_input_candidate"
            return base
        base["runner_decision"] = "allow"
        base["target"] = {
            "action_type": "type_text",
            "text_length": len(str(item.get("planned_answer") or "")),
            "candidate": candidate,
            "bbox": candidate.get("bbox"),
            "click_point": candidate.get("click_point"),
            "submit": False,
        }
        return base
    if answer_type == "checkbox_multi":
        selections = [entry for entry in item.get("selections") or [] if isinstance(entry, dict)]
        targets = []
        for selection in selections:
            candidate = selection.get("candidate") if isinstance(selection.get("candidate"), dict) else selection
            clickable = _candidate_with_click_point(candidate)
            if not clickable.get("bbox") or not _candidate_is_visible(clickable):
                continue
            targets.append(
                {
                    "candidate": clickable,
                    "bbox": clickable.get("bbox"),
                    "click_point": clickable.get("click_point"),
                    "selection": selection,
                }
            )
        if not targets:
            base["runner_decision"] = "needs_user_review"
            base["reject_reason"] = "no_matching_checkbox_option"
            return base
        base["runner_decision"] = "allow"
        base["target"] = {
            "action_type": "multi_click",
            "targets": targets,
            "selected_count": len(targets),
        }
        return base
    base["runner_decision"] = "needs_user_review"
    base["reject_reason"] = "unsupported_answer_type"
    return base


def _plan_answer(question: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    text = _clean(question.get("question_text"))
    key = text.casefold()
    answer_type = str(question.get("answer_type") or "unknown")
    base = {
        "question_id": question.get("question_id"),
        "question_text": text,
        "question_text_hash": question.get("question_text_hash"),
        "answer_type": answer_type,
        "status": "needs_user_review",
        "answer_category": "unmapped",
        "planned_answer": None,
        "answer_source": None,
        "evidence": None,
        "requires_user_review": True,
        "selection": None,
        "control_candidates": question.get("control_candidates") or [],
        "selected_value_candidates": question.get("selected_value_candidates") or [],
    }
    if "income range" in key or "compensation range" in key or "salary expectation" in key or "annual base salary" in key:
        value = _clean(profile.get("salary_expectation")) or "$80k"
        base.update(
            status="ready",
            answer_category="compensation_expectation",
            planned_answer=value,
            answer_source="candidate_profile_v1.salary_expectation_or_user_demo_policy",
            evidence="No fixed salary expectation is recorded in the profile; use the reviewed demo default and stop before final submit.",
            requires_user_review=False,
        )
        return base
    if _contains_any(key, {"criminal", "conviction", "medical", "health", "disability", "security clearance", "background check"}):
        base.update(status="blocked_sensitive", answer_category="sensitive_or_high_risk", evidence="sensitive question requires user review")
        return base
    if key == "country" or key.endswith(" country"):
        base.update(
            status="ready",
            answer_category="location_country",
            planned_answer="New Zealand",
            answer_source="candidate_profile_v1.work_rights_summary",
            evidence=_clean(profile.get("work_rights_summary")) or "Candidate profile indicates New Zealand work rights.",
            requires_user_review=False,
        )
        return base
    if "current location" in key or "where are you currently located" in key:
        preferences = profile.get("job_search_preferences") if isinstance(profile.get("job_search_preferences"), dict) else {}
        value = _clean(preferences.get("primary_location")) or "Auckland"
        base.update(
            status="ready",
            answer_category="current_location",
            planned_answer=value,
            answer_source="candidate_profile_v1.job_search_preferences.primary_location",
            evidence=json.dumps(preferences.get("location_priority") or value, ensure_ascii=False),
            requires_user_review=False,
        )
        return base
    if key == "gender":
        base.update(
            status="ready",
            answer_category="demographic_prefer_not_to_disclose",
            planned_answer="Do not wish to disclose",
            answer_source="safe_default_non_disclosure",
            evidence="Prefer non-disclosure for optional demographic questions unless the user explicitly says otherwise.",
            requires_user_review=False,
            selection=select_employer_question_option(question, planned_answer="Do not wish to disclose"),
        )
        return base
    if "english language" in key or "language skills" in key:
        value = _clean(profile.get("english_language_level")) or _clean(profile.get("english")) or "Professional working proficiency"
        base.update(
            status="ready",
            answer_category="language_proficiency",
            planned_answer=value,
            answer_source="candidate_profile_v1.english_language_level_or_demo_policy",
            evidence="Use professional working proficiency for the no-submit demo unless the profile records a different level.",
            requires_user_review=False,
            selection=select_employer_question_option(question, planned_answer=value) if answer_type in {"radio_choice", "radio_yes_no"} else None,
        )
        return base
    if "know anybody" in key and "sandfield" in key:
        base.update(
            status="ready",
            answer_category="company_connection",
            planned_answer="No",
            answer_source="candidate_profile_v1.no_known_company_connection",
            evidence="No Sandfield employee connection is recorded in the candidate profile.",
            requires_user_review=False,
            selection=select_employer_question_option(question, planned_answer="No") if answer_type == "radio_yes_no" else None,
        )
        return base
    if "what appeals to you" in key and "sandfield" in key:
        evidence = _profile_evidence(profile, ["skills", "experience_summary"])
        answer = (
            "Sandfield appeals to me because the role combines full-stack web development, "
            "real business problem solving, direct collaboration with clients, and the use of AI tools to build practical software. "
            "That fits my background in JavaScript, React, APIs, AI-assisted development, and evidence-driven debugging."
        )
        base.update(
            status="ready",
            answer_category="role_motivation",
            planned_answer=answer,
            answer_source="candidate_profile_v1.skills_and_job_detail_evidence",
            evidence=evidence or "Job detail mentions full-stack development, real business problems, client interaction, and AI tools.",
            requires_user_review=False,
        )
        return base
    if "currently living in new zealand" in key or "currently live in new zealand" in key:
        value = _clean(profile.get("work_rights_summary"))
        base.update(
            status="ready",
            answer_category="current_residence",
            planned_answer="Yes",
            answer_source="candidate_profile_v1.work_rights_summary",
            evidence=value or "Candidate profile is for New Zealand SEEK applications.",
            requires_user_review=False,
            selection=select_employer_question_option(question, planned_answer="Yes") if answer_type == "radio_yes_no" else None,
        )
        return base
    if "right to work" in key or "work rights" in key or "work in new zealand" in key or "visa" in key:
        value = _clean(profile.get("work_rights_summary"))
        if answer_type == "radio_yes_no" and (
            "without the need for employer sponsorship" in key or "without employer sponsorship" in key
        ):
            base.update(
                status="ready",
                answer_category="work_rights",
                planned_answer="Yes",
                answer_source="candidate_profile_v1.work_rights_summary" if value else "seek_no_submit_demo_policy.work_rights",
                evidence=value or "No work-rights summary was loaded; no-submit demo uses Yes only for sponsorship-style eligibility questions.",
                requires_user_review=False,
                selection=select_employer_question_option(question, planned_answer="Yes"),
            )
            return base
        planned = _visible_work_rights_profile_option(question, value) if value else _visible_work_rights_demo_option(question)
        if not planned and value:
            planned = _work_rights_option(value)
        if planned:
            base.update(
                status="ready",
                answer_category="work_rights",
                planned_answer=planned,
                answer_source="candidate_profile_v1.work_rights_summary" if value else "seek_no_submit_demo_policy.visible_work_rights_option",
                evidence=value or "No work-rights summary was loaded; no-submit demo selects the visible Current NZ Work Visa option and stops before final submit.",
                requires_user_review=False,
                selection=select_employer_question_option(question, planned_answer=planned)
                if answer_type in {"radio_choice", "radio_yes_no"}
                else None,
            )
        else:
            base.update(status="blocked_sensitive", answer_category="work_rights", evidence="profile work_rights_summary missing")
        return base
    if "1-2 years" in key or "web application development" in key:
        evidence = _profile_evidence(profile, ["experience_summary", "skills"])
        if evidence:
            base.update(
                status="ready",
                answer_category="experience_yes_no",
                planned_answer="Yes",
                answer_source="candidate_profile_v1.experience_summary",
                evidence=evidence,
                requires_user_review=False,
                selection=select_employer_question_option(question, planned_answer="Yes") if answer_type == "radio_yes_no" else None,
            )
        return base
    if answer_type == "checkbox_multi" and _contains_any(
        key,
        {
            "programming language",
            "programming languages",
            "technologies",
            "frameworks",
            "tools",
            "experienced in",
            "experience with",
        },
    ):
        selections = _select_profile_skill_options(question, profile)
        evidence = _profile_evidence(profile, ["skills", "experience_summary"])
        if selections:
            base.update(
                status="ready",
                answer_category="skill_checkbox_multi",
                planned_answer=[item.get("label") for item in selections],
                answer_source="candidate_profile_v1.skills",
                evidence=evidence,
                requires_user_review=False,
                selections=selections,
            )
        return base
    if _contains_any(key, {"java", "angularjs", "react", "vue", "mysql", "solutions"}):
        evidence = _profile_evidence(profile, ["skills", "experience_summary"])
        if evidence and _contains_any(evidence.casefold(), {"react", "sql", "frontend", "software", "web"}):
            base.update(
                status="ready",
                answer_category="skill_comfort_yes_no",
                planned_answer="Yes",
                answer_source="candidate_profile_v1.skills",
                evidence=evidence,
                requires_user_review=False,
                selection=select_employer_question_option(question, planned_answer="Yes") if answer_type == "radio_yes_no" else None,
            )
        return base
    if "start immediately" in key or "within 1-2 weeks" in key or "availability" in key:
        value = _clean(profile.get("availability") or profile.get("notice_period"))
        if not value:
            value = "Yes, I can start immediately or within 1-2 weeks."
        evidence = _profile_evidence(profile, ["availability", "notice_period", "work_rights_summary"])
        base.update(
            status="ready",
            answer_category="availability",
            planned_answer=value,
            answer_source="candidate_profile_v1.availability_or_work_rights_summary",
            evidence=evidence or "valid work-rights evidence present; user approved direct employer-question answers",
            requires_user_review=False,
        )
        return base
    if "notice" in key and "employer" in key:
        value = _clean(profile.get("notice_period")) or "None, I'm ready to go now"
        evidence = _profile_evidence(profile, ["notice_period", "availability", "work_rights_summary"])
        base.update(
            status="ready",
            answer_category="notice_period",
            planned_answer=value,
            answer_source="candidate_profile_v1.notice_period_or_demo_policy",
            evidence=evidence or "No current employer notice period is recorded; use the no-submit demo default.",
            requires_user_review=False,
        )
        return base
    return base


def _first_type_text_candidate(candidates: Any) -> dict[str, Any] | None:
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        role = str(candidate.get("role") or "").casefold()
        if role in {"textbox", "text_input"} or any(term in role for term in ("textarea", "text area", "edit", "input")):
            return candidate
    return None


def _select_choice_match_should_click(candidates: Any, candidate: dict[str, Any]) -> bool:
    if not isinstance(candidate, dict):
        return False
    if candidate.get("source") == "synthetic_work_rights_dropdown_value_region":
        return False
    visible_candidates = [item for item in candidates or [] if isinstance(item, dict) and isinstance(item.get("bbox"), dict)]
    return len(visible_candidates) > 1


def _candidate_with_click_point(candidate: dict[str, Any]) -> dict[str, Any]:
    bbox = _bbox(candidate.get("bbox"))
    if "click_point" in candidate:
        return candidate
    return {
        **candidate,
        "bbox": bbox,
        "click_point": {"x": _bbox_x(bbox) + int(_bbox_w(bbox) / 2), "y": _bbox_y(bbox) + int(_bbox_h(bbox) / 2)},
    }


def _candidate_is_visible(candidate: dict[str, Any]) -> bool:
    bbox = _bbox(candidate.get("bbox"))
    return _bbox_x(bbox) >= 0 and _bbox_y(bbox) >= 0 and _bbox_w(bbox) > 1 and _bbox_h(bbox) > 1


def _build_question_group(
    question: dict[str, Any],
    *,
    items: list[dict[str, Any]],
    index: int,
    next_question_y: int | None,
    max_group_height: int,
) -> dict[str, Any]:
    qbbox = _bbox(question.get("question_bbox"))
    qx = _bbox_x(qbbox)
    qy = _bbox_y(qbbox)
    qbottom = _bbox_bottom(qbbox)
    boundary_y = next_question_y if next_question_y is not None else qbottom + max_group_height
    boundary_y = max(boundary_y, qbottom + 1)
    group_bbox = _group_bbox(qbbox, items=items, bottom_y=boundary_y)
    candidates = [
        _control_candidate(item)
        for item in items
        if _is_control_candidate(item) and _within_question_band(item, top_y=qbottom, bottom_y=boundary_y)
    ]
    candidates = [item for item in candidates if item]
    synthetic_textbox = _synthetic_textbox_candidate(question, bottom_y=boundary_y)
    if synthetic_textbox and not any(_clean(item.get("role")).casefold() in {"textbox", "text_input"} for item in candidates):
        candidates.append(synthetic_textbox)
    selected_value_candidates = [
        _value_evidence_candidate(item)
        for item in items
        if _is_selected_value_evidence_candidate(item)
        and _within_question_band(item, top_y=qbottom, bottom_y=boundary_y)
        and not _same_question_key(_question_key(item.get("text") or item.get("label")), _question_key(question["question_text"]))
    ]
    selected_value_candidates = [item for item in selected_value_candidates if item]
    if not selected_value_candidates and _is_work_rights_question(question.get("question_text")):
        structural_value = _synthetic_work_rights_selected_value_candidate(question, bottom_y=boundary_y)
        if structural_value:
            selected_value_candidates.append(structural_value)
    global_counts: dict[str, int] = {}
    for item in items:
        label = _clean(item.get("text") or item.get("label")).casefold()
        if label:
            global_counts[label] = global_counts.get(label, 0) + 1
    return {
        "question_id": f"q{index + 1}",
        "question_text": question["question_text"],
        "question_text_hash": hashlib.sha256(question["question_text"].encode("utf-8")).hexdigest(),
        "question_bbox": qbbox,
        "question_group_bbox": group_bbox,
        "answer_type": _answer_type(candidates, selected_value_candidates, question["question_text"]),
        "control_candidates": candidates,
        "selected_value_candidates": selected_value_candidates,
        "next_question_boundary_y": boundary_y,
        "global_option_counts": global_counts,
        "anchor": {"x": qx, "y": qy},
    }


def _synthetic_textbox_candidate(question: dict[str, Any], *, bottom_y: int) -> dict[str, Any] | None:
    if not _question_expects_text_input(question.get("question_text")):
        return None
    qbox = _bbox(question.get("question_bbox"))
    if "input field" in _clean(question.get("question_text")).casefold():
        return {
            "id": f"{(question.get('question_id') or 'question')}_source_input_bbox",
            "label": "",
            "role": "textbox",
            "bbox": qbox,
            "click_point": {"x": _bbox_x(qbox) + int(_bbox_w(qbox) / 2), "y": _bbox_y(qbox) + int(_bbox_h(qbox) / 2)},
            "source": "source_input_field_bbox",
            "association_match": False,
            "inference_reason": "question_label_is_input_field_bbox",
        }
    y = _bbox_bottom(qbox) + 14
    available_h = max(0, int(bottom_y) - y - 12)
    if available_h < 48:
        return None
    h = min(132, max(72, available_h))
    w = max(_bbox_w(qbox), 660)
    bbox = {"x": _bbox_x(qbox), "y": y, "w": w, "h": h}
    return {
        "id": f"{(question.get('question_id') or 'question')}_synthetic_textbox",
        "label": "",
        "role": "textbox",
        "bbox": bbox,
        "click_point": {"x": _bbox_x(bbox) + int(_bbox_w(bbox) / 2), "y": _bbox_y(bbox) + int(_bbox_h(bbox) / 2)},
        "source": "synthetic_empty_textbox_region",
        "association_match": False,
        "inference_reason": "empty_textarea_visible_below_text_question",
    }


def _synthetic_work_rights_selected_value_candidate(question: dict[str, Any], *, bottom_y: int) -> dict[str, Any] | None:
    qbox = _bbox(question.get("question_bbox"))
    y = _bbox_bottom(qbox) + 12
    available_h = max(0, int(bottom_y) - y - 8)
    if available_h < 28:
        return None
    h = min(54, max(36, available_h))
    bbox = {"x": _bbox_x(qbox), "y": y, "w": max(_bbox_w(qbox), 660), "h": h}
    return {
        "id": f"{(question.get('question_id') or 'question')}_synthetic_work_rights_selected_value",
        "label": "visible selected work-rights dropdown value; OCR text unavailable",
        "role": "select_value",
        "bbox": bbox,
        "source": "synthetic_work_rights_dropdown_value_region",
        "inference_reason": "work_rights_dropdown_value_visible_but_ocr_missing",
    }


def _question_expects_text_input(question_text: Any) -> bool:
    text = _clean(question_text).casefold()
    if any(
        term in text
        for term in (
            "country",
            "current location",
            "income range",
            "compensation range",
            "salary expectation",
            "know anybody",
            "what appeals",
            "start immediately",
            "within 1-2 weeks",
            "available to start",
            "availability",
            "tell us",
            "explain",
        )
    ):
        return True
    return bool(re.search(r"\bdescribe\b", text))


def _is_work_rights_question(question_text: Any) -> bool:
    question_key = _clean(question_text).casefold()
    return "right to work" in question_key or "work in new zealand" in question_key or "visa" in question_key


def _score_candidate_for_question(question: dict[str, Any], candidate: dict[str, Any], expected: str) -> dict[str, Any]:
    bbox = _bbox(candidate.get("bbox"))
    group = _bbox(question.get("question_group_bbox"))
    boundary_y = int(question.get("next_question_boundary_y") or _bbox_bottom(group))
    hard_reject_reason = None
    if not _bbox_contains(group, bbox):
        hard_reject_reason = "candidate_outside_question_group_bbox"
    elif _bbox_y(bbox) >= boundary_y:
        hard_reject_reason = "candidate_past_next_question_boundary"
    elif not _label_matches(candidate, expected):
        hard_reject_reason = "label_text_mismatch"

    inside = 1.0 if _bbox_contains(group, bbox) else 0.0
    vertical = 1.0 if _bbox_y(bbox) >= _bbox_bottom(question.get("question_bbox")) else 0.0
    before_boundary = 1.0 if _bbox_y(bbox) < boundary_y else 0.0
    label_match = 1.0 if _label_matches(candidate, expected) else 0.0
    role_match = 1.0 if str(candidate.get("role") or "").casefold() in {"radio", "radiobutton", "button", "option", "combobox", "textbox", "text_input"} else 0.0
    association = 1.0 if candidate.get("association_match") else 0.0
    score = 0.35 * inside + 0.20 * vertical + 0.15 * before_boundary + 0.15 * label_match + 0.10 * role_match + 0.05 * association
    return {
        "candidate": candidate,
        "score": round(score, 4),
        "hard_reject": hard_reject_reason is not None,
        "reject_reason": hard_reject_reason,
        "score_components": {
            "inside_current_question_group": inside,
            "same_vertical_band_or_below_question": vertical,
            "before_next_question_boundary": before_boundary,
            "label_text_match": label_match,
            "radio_or_button_role_match": role_match,
            "dom_uia_association_match": association,
        },
    }


def _inventory_items(form: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("fields", "actions"):
        for item in form.get(key) or []:
            if isinstance(item, dict) and isinstance(item.get("bbox"), dict):
                items.append(item)
    return items


def _screen_reading_items(screen_reading: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in screen_reading.get("texts") or []:
        if isinstance(item, dict) and isinstance(item.get("bbox"), dict):
            items.append(
                {
                    "collection": item.get("source") or "screen_reading.texts",
                    "id": item.get("id"),
                    "text": item.get("text"),
                    "role": "text",
                    "bbox": item.get("bbox"),
                }
            )
    source_layers = screen_reading.get("source_layers") if isinstance(screen_reading.get("source_layers"), dict) else {}
    uia = source_layers.get("windows_uia") if isinstance(source_layers.get("windows_uia"), dict) else {}
    for control in uia.get("controls") or []:
        if not isinstance(control, dict):
            continue
        bbox = control.get("bbox") if isinstance(control.get("bbox"), dict) else control.get("screen_bbox")
        if not isinstance(bbox, dict):
            continue
        items.append(
            {
                "collection": "windows_uia.controls",
                "id": control.get("control_id"),
                "text": control.get("name"),
                "role": _uia_role(control),
                "bbox": bbox,
                "source_control_type": control.get("control_type"),
                "automation_id": control.get("automation_id"),
                "association_match": bool(control.get("automation_id")),
            }
        )
    return items


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int, int, int]] = set()
    for item in items:
        bbox = _bbox(item.get("bbox"))
        key = (
            _clean(item.get("text") or item.get("label")).casefold(),
            _clean(item.get("role")).casefold(),
            _bbox_x(bbox),
            _bbox_y(bbox),
            _bbox_w(bbox),
            _bbox_h(bbox),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _uia_role(control: dict[str, Any]) -> str:
    control_type = _clean(control.get("control_type")).casefold()
    if control_type == "radiobutton":
        return "radio"
    if control_type == "checkbox":
        return "checkbox"
    if control_type == "combobox":
        return "combobox"
    if control_type in {"edit", "document"}:
        return "textbox"
    if control_type == "button":
        return "button"
    return control_type or "text"


def _question_from_item(item: dict[str, Any]) -> dict[str, Any]:
    text = _clean(item.get("text") or item.get("label"))
    return {
        "question_text": text,
        "question_bbox": _bbox(item.get("bbox")),
        "source_item_ids": [item.get("id")],
    }


def _merged_question_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(items, key=lambda item: (_bbox_y(item.get("bbox")), _bbox_x(item.get("bbox"))))
    consumed_ids: set[Any] = set()
    questions: list[dict[str, Any]] = []
    for item in sorted_items:
        item_id = item.get("id")
        if item_id in consumed_ids or not _looks_like_question(item):
            continue
        question = _question_from_item(item)
        continuation = _question_continuation_item(question, sorted_items, consumed_ids={item_id})
        if continuation:
            question = _merge_question_with_continuation(question, continuation)
            consumed_ids.add(continuation.get("id"))
        questions.append(question)
    return questions


def _question_continuation_item(
    question: dict[str, Any],
    items: list[dict[str, Any]],
    *,
    consumed_ids: set[Any],
) -> dict[str, Any] | None:
    text = _clean(question.get("question_text"))
    if "?" in text:
        return None
    qbox = _bbox(question.get("question_bbox"))
    qbottom = _bbox_bottom(qbox)
    qx = _bbox_x(qbox)
    for item in items:
        if item.get("id") in consumed_ids or _is_control_candidate(item):
            continue
        label = _clean(item.get("text") or item.get("label"))
        if not label or len(label) < 2:
            continue
        bbox = _bbox(item.get("bbox"))
        gap = _bbox_y(bbox) - qbottom
        if gap < -2 or gap > 42:
            continue
        if abs(_bbox_x(bbox) - qx) > 80:
            continue
        lowered = label.casefold()
        if "?" in label or lowered.startswith(("following:", "with ", "in ")):
            return item
    return None


def _merge_question_with_continuation(question: dict[str, Any], continuation: dict[str, Any]) -> dict[str, Any]:
    qbox = _bbox(question.get("question_bbox"))
    cbox = _bbox(continuation.get("bbox"))
    x1 = min(_bbox_x(qbox), _bbox_x(cbox))
    y1 = min(_bbox_y(qbox), _bbox_y(cbox))
    x2 = max(_bbox_right(qbox), _bbox_right(cbox))
    y2 = max(_bbox_bottom(qbox), _bbox_bottom(cbox))
    ids = [item for item in question.get("source_item_ids") or [] if item is not None]
    if continuation.get("id") is not None:
        ids.append(continuation.get("id"))
    return {
        **question,
        "question_text": f"{_clean(question.get('question_text'))} {_clean(continuation.get('text') or continuation.get('label'))}".strip(),
        "question_bbox": {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)},
        "source_item_ids": ids,
    }


def _looks_like_question(item: dict[str, Any]) -> bool:
    role = _clean(item.get("role") or item.get("control_type") or item.get("type")).casefold()
    if role in {"radio", "radiobutton", "button", "option", "combobox", "textbox", "text_input"}:
        return False
    text = _clean(item.get("text") or item.get("label"))
    lowered = text.casefold()
    known_short_labels = {
        "country",
        "current location",
        "gender",
        "income range input field",
    }
    if lowered in known_short_labels:
        return True
    if not text or len(text) < 12:
        return False
    url_key = re.sub(r"\s+", "", lowered)
    if (
        "://" in lowered
        or lowered.startswith(("http://", "https://", "http/", "https/"))
        or "seek.com/job/" in url_key
        or "nz.seek.com/job" in url_key
    ):
        return False
    if "employer questions" in lowered or lowered in {"answer employer questions", "review and submit"}:
        return False
    compact = re.sub(r"[^a-z0-9?]+", "", lowered)
    return (
        "?" in text
        or lowered.startswith(("do you ", "are you ", "can you ", "which of ", "what income range ", "what appeals "))
        or compact.startswith(("doyou", "areyou", "canyou", "whichof", "whatincomerange", "whatappeals"))
    )


def _dedupe_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        questions,
        key=lambda item: (
            _bbox_y(item.get("question_bbox")),
            _bbox_x(item.get("question_bbox")),
            -len(str(item.get("question_text") or "")),
        ),
    )
    deduped: list[dict[str, Any]] = []
    for question in ordered:
        text = _question_key(question.get("question_text"))
        bbox = _bbox(question.get("question_bbox"))
        duplicate_index = None
        for index, existing in enumerate(deduped):
            existing_text = _question_key(existing.get("question_text"))
            same_text = _same_question_key(text, existing_text)
            near_y = abs(_bbox_y(existing.get("question_bbox")) - _bbox_y(bbox)) <= 90
            if same_text and near_y:
                duplicate_index = index
                break
        if duplicate_index is None:
            deduped.append(question)
            continue
        existing = deduped[duplicate_index]
        if len(str(question.get("question_text") or "")) > len(str(existing.get("question_text") or "")):
            deduped[duplicate_index] = question
    return sorted(deduped, key=lambda item: (_bbox_y(item.get("question_bbox")), _bbox_x(item.get("question_bbox"))))


def _question_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).casefold()).strip()


def _same_question_key(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    left_compact = re.sub(r"\s+", "", left)
    right_compact = re.sub(r"\s+", "", right)
    if left_compact == right_compact or left_compact in right_compact or right_compact in left_compact:
        return True
    left_tokens = [token for token in left.split() if len(token) > 2]
    right_tokens = [token for token in right.split() if len(token) > 2]
    if not left_tokens or not right_tokens:
        return False
    shared = set(left_tokens) & set(right_tokens)
    smaller = min(len(set(left_tokens)), len(set(right_tokens)))
    return smaller > 0 and len(shared) / smaller >= 0.72


def _is_control_candidate(item: dict[str, Any]) -> bool:
    role = _clean(item.get("role") or item.get("control_type") or item.get("type")).casefold()
    label = _clean(item.get("text") or item.get("label")).casefold()
    if label in {"continue", "back", "review and submit", "submit", "submit application", "send application", "complete application"}:
        return False
    if role in {"radio", "radiobutton", "checkbox", "button", "option", "combobox", "textbox", "text_input"}:
        return True
    text_option_labels = {"yes", "no", "male", "female", "other", "do not wish to disclose"}
    return label in text_option_labels or role in {"text", "input"} and (label in text_option_labels or label in PROGRAMMING_OPTION_LABELS)


def _control_candidate(item: dict[str, Any]) -> dict[str, Any]:
    label = _clean(item.get("text") or item.get("label"))
    role = _clean(item.get("role") or item.get("control_type") or item.get("type"))
    bbox = _bbox(item.get("bbox"))
    return {
        "id": item.get("id"),
        "label": label,
        "role": role.casefold() if role else "unknown",
        "bbox": bbox,
        "click_point": {"x": _bbox_x(bbox) + int(_bbox_w(bbox) / 2), "y": _bbox_y(bbox) + int(_bbox_h(bbox) / 2)},
        "source": item.get("collection") or item.get("source"),
        "association_match": bool(item.get("association_match")),
    }


def _is_selected_value_evidence_candidate(item: dict[str, Any]) -> bool:
    if _is_control_candidate(item) or _looks_like_question(item):
        return False
    label = _clean(item.get("text") or item.get("label"))
    if not label or len(label) < 3:
        return False
    lowered = label.casefold()
    navigation_key = re.sub(r"[^0-9a-z]+", "", lowered)
    if lowered in {
        "choose documents",
        "answer employer questions",
        "update seek profile",
        "review and submit",
        "continue",
        "back",
    } or navigation_key in {"continue", "back", "submit", "submitapplication"}:
        return False
    return True


def _value_evidence_candidate(item: dict[str, Any]) -> dict[str, Any]:
    label = _clean(item.get("text") or item.get("label"))
    bbox = _bbox(item.get("bbox"))
    return {
        "id": item.get("id"),
        "label": label,
        "role": _clean(item.get("role") or item.get("control_type") or item.get("type")).casefold() or "text",
        "bbox": bbox,
        "source": item.get("collection") or item.get("source"),
    }


def _within_question_band(item: dict[str, Any], *, top_y: int, bottom_y: int) -> bool:
    bbox = _bbox(item.get("bbox"))
    y = _bbox_y(bbox)
    return top_y <= y < bottom_y


def _answer_type(
    candidates: list[dict[str, Any]],
    selected_value_candidates: list[dict[str, Any]] | None = None,
    question_text: Any = None,
) -> str:
    labels = {_clean(item.get("label")).casefold() for item in candidates}
    roles = {_clean(item.get("role")).casefold() for item in candidates}
    question_key = _clean(question_text).casefold()
    if any(role == "combobox" for role in roles):
        return "select_choice"
    if {"yes", "no"}.issubset(labels):
        return "radio_yes_no"
    if selected_value_candidates and _contains_any(
        question_key,
        {"right to work", "work in new zealand", "visa", "salary", "base salary", "income range", "notice"},
    ):
        return "select_choice"
    if _question_expects_text_input(question_text):
        return "text_input"
    if {"male", "female", "other", "do not wish to disclose"} & labels:
        return "radio_choice"
    if any(role in {"textbox", "text_input"} for role in roles):
        return "text_input"
    if any(role in {"radio", "radiobutton", "option"} for role in roles):
        return "radio_choice"
    if any(role == "checkbox" for role in roles):
        return "checkbox_multi"
    if _contains_any(question_key, {"programming language", "programming languages"}) and labels & PROGRAMMING_OPTION_LABELS:
        return "checkbox_multi"
    return "unknown"


def _group_bbox(qbbox: dict[str, int], *, items: list[dict[str, Any]], bottom_y: int) -> dict[str, int]:
    boxes = [qbbox]
    for item in items:
        bbox = _bbox(item.get("bbox"))
        if _bbox_y(bbox) >= _bbox_bottom(qbbox) and _bbox_y(bbox) < bottom_y:
            boxes.append(bbox)
    x1 = min(_bbox_x(box) for box in boxes)
    y1 = min(_bbox_y(box) for box in boxes)
    x2 = max(_bbox_right(box) for box in boxes)
    y2 = max(bottom_y, max(_bbox_bottom(box) for box in boxes))
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _label_matches(candidate: dict[str, Any], expected: str) -> bool:
    label = _clean(candidate.get("label") or candidate.get("text")).casefold()
    if not expected:
        return False
    if expected == label:
        return True
    if expected in {"yes", "no"}:
        return label == expected
    return expected in label or label in expected


def _selected_value_match(candidates: Any, planned_answer: Any) -> dict[str, Any] | None:
    expected = _clean(planned_answer)
    if not expected or not isinstance(candidates, list):
        return None
    expected_key = expected.casefold()
    if _expected_work_rights_dropdown_value(expected_key):
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("source") == "synthetic_work_rights_dropdown_value_region":
                return {
                    "candidate": candidate,
                    "match_type": "structural_work_rights_dropdown_value_ocr_missing",
                    "score": 0.68,
                }
    expected_tokens = _semantic_tokens(expected_key)
    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        label = _clean(candidate.get("label") or candidate.get("text"))
        if not label:
            continue
        label_key = label.casefold()
        if expected_key == label_key or expected_key in label_key or label_key in expected_key:
            return {"candidate": candidate, "match_type": "text_contains", "score": 1.0}
        label_tokens = _semantic_tokens(label_key)
        if not expected_tokens or not label_tokens:
            continue
        shared = expected_tokens & label_tokens
        score = len(shared) / max(1, min(len(expected_tokens), len(label_tokens)))
        if score > best_score:
            best_score = score
            best = candidate
    if best and best_score >= 0.82:
        return {"candidate": best, "match_type": "token_overlap", "score": round(best_score, 4)}
    if _expected_work_rights_dropdown_value(expected_key):
        for candidate in candidates:
            if _looks_like_visible_dropdown_value_with_unreliable_ocr(candidate):
                return {
                    "candidate": candidate,
                    "match_type": "visible_dropdown_value_ocr_unreliable_work_rights",
                    "score": 0.72,
                }
    return None


def _semantic_tokens(value: str) -> set[str]:
    stopwords = {"the", "and", "or", "of", "to", "in", "a", "an", "e", "g"}
    return {token for token in re.split(r"[^a-z0-9]+", value.casefold()) if len(token) > 2 and token not in stopwords}


def _expected_work_rights_dropdown_value(value: str) -> bool:
    return "work visa" in value or "post study" in value or "graduate temporary work visa" in value


def _looks_like_visible_dropdown_value_with_unreliable_ocr(candidate: dict[str, Any]) -> bool:
    label = _clean(candidate.get("label") or candidate.get("text"))
    bbox = _bbox(candidate.get("bbox"))
    lowered = label.casefold()
    if _bbox_w(bbox) < 240 or len(label) < 18:
        return False
    if any(term in lowered for term in ("choose documents", "answer employer questions", "review and submit", "continue", "submit")):
        return False
    if "?" in label:
        return False
    return True


def _bbox(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"x": 0, "y": 0, "w": 1, "h": 1}
    return {
        "x": int(value.get("x") or value.get("left") or 0),
        "y": int(value.get("y") or value.get("top") or 0),
        "w": int(value.get("w") or value.get("width") or max(1, int(value.get("right") or 1) - int(value.get("left") or 0))),
        "h": int(value.get("h") or value.get("height") or max(1, int(value.get("bottom") or 1) - int(value.get("top") or 0))),
    }


def _bbox_contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    outer_box = _bbox(outer)
    inner_box = _bbox(inner)
    return (
        _bbox_x(inner_box) >= _bbox_x(outer_box)
        and _bbox_y(inner_box) >= _bbox_y(outer_box)
        and _bbox_right(inner_box) <= _bbox_right(outer_box)
        and _bbox_bottom(inner_box) <= _bbox_bottom(outer_box)
    )


def _bbox_x(bbox: Any) -> int:
    return _bbox(bbox)["x"] if not isinstance(bbox, dict) else int(bbox.get("x") or 0)


def _bbox_y(bbox: Any) -> int:
    return _bbox(bbox)["y"] if not isinstance(bbox, dict) else int(bbox.get("y") or 0)


def _bbox_w(bbox: Any) -> int:
    return _bbox(bbox)["w"] if not isinstance(bbox, dict) else int(bbox.get("w") or 1)


def _bbox_h(bbox: Any) -> int:
    return _bbox(bbox)["h"] if not isinstance(bbox, dict) else int(bbox.get("h") or 1)


def _bbox_right(bbox: Any) -> int:
    return _bbox_x(bbox) + _bbox_w(bbox)


def _bbox_bottom(bbox: Any) -> int:
    return _bbox_y(bbox) + _bbox_h(bbox)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _contains_any(haystack: str, terms: set[str]) -> bool:
    return any(term in haystack for term in terms)


def _profile_evidence(profile: dict[str, Any], keys: list[str]) -> str:
    values: list[str] = []
    for key in keys:
        value = profile.get(key)
        if isinstance(value, list):
            values.extend(_clean(item) for item in value if _clean(item))
        elif isinstance(value, dict):
            values.extend(_clean(item) for item in value.values() if _clean(item))
        elif _clean(value):
            values.append(_clean(value))
    return "; ".join(values[:12])


def _select_profile_skill_options(question: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    profile_tokens = _profile_skill_tokens(profile)
    if not profile_tokens:
        return []
    selected: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for candidate in question.get("control_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        label = _clean(candidate.get("label") or candidate.get("text"))
        label_key = label.casefold()
        if not label_key or label_key in seen_labels:
            continue
        if label_key in {"other", "none", "n/a", "not applicable"}:
            continue
        label_tokens = _skill_label_tokens(label_key)
        if not label_tokens:
            continue
        if profile_tokens & label_tokens or label_key in profile_tokens:
            selected.append(
                {
                    "candidate": candidate,
                    "label": label,
                    "match_type": "profile_skill_token",
                    "matched_tokens": sorted(profile_tokens & label_tokens),
                }
            )
            seen_labels.add(label_key)
    return selected


def _profile_skill_tokens(profile: dict[str, Any]) -> set[str]:
    evidence = _profile_evidence(profile, ["skills", "experience_summary"])
    tokens = _semantic_tokens(evidence)
    aliases = {
        ".net": {"net", "dotnet"},
        "c#": {"csharp", "sharp"},
        "javascript": {"javascript", "js"},
        "typescript": {"typescript", "ts"},
    }
    lowered = evidence.casefold()
    for literal, mapped in aliases.items():
        if literal in lowered:
            tokens.update(mapped)
    return tokens


def _skill_label_tokens(value: str) -> set[str]:
    tokens = _semantic_tokens(value)
    if "c#" in value:
        tokens.update({"csharp", "sharp"})
    if ".net" in value:
        tokens.update({"net", "dotnet"})
    if value == "js":
        tokens.add("javascript")
    if value == "ts":
        tokens.add("typescript")
    return tokens


def _work_rights_option(summary: str) -> str:
    lowered = summary.casefold()
    if "post study" in lowered or "post-study" in lowered or "graduate temporary" in lowered:
        return "I have a graduate temporary work visa (e.g. post study work visa - open)"
    return summary


def _visible_work_rights_demo_option(question: dict[str, Any]) -> str | None:
    labels = [
        _clean(item.get("label") or item.get("text"))
        for item in [
            *(question.get("control_candidates") or []),
            *(question.get("selected_value_candidates") or []),
        ]
        if isinstance(item, dict)
    ]
    preferred = ("Current NZ Work Visa", "NZ Resident", "NZ Citizen")
    for option in preferred:
        if any(_clean(label).casefold() == option.casefold() for label in labels):
            return option
    return None


def _visible_work_rights_profile_option(question: dict[str, Any], summary: str) -> str | None:
    lowered = _clean(summary).casefold()
    if "post study" in lowered or "post-study" in lowered or "work visa" in lowered or "open work" in lowered:
        visible = _visible_work_rights_demo_option(question)
        if visible == "Current NZ Work Visa":
            return visible
    if "resident" in lowered and _visible_work_rights_label_exists(question, "NZ Resident"):
        return "NZ Resident"
    if "citizen" in lowered and _visible_work_rights_label_exists(question, "NZ Citizen"):
        return "NZ Citizen"
    return None


def _visible_work_rights_label_exists(question: dict[str, Any], label: str) -> bool:
    labels = [
        _clean(item.get("label") or item.get("text")).casefold()
        for item in [
            *(question.get("control_candidates") or []),
            *(question.get("selected_value_candidates") or []),
        ]
        if isinstance(item, dict)
    ]
    return label.casefold() in labels
