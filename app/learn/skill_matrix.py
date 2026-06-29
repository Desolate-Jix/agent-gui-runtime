from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.gate.actions import infer_action_kind, infer_low_level_action_type


LEARNED_SKILL_MATRIX_CONTRACT = "learned_skill_matrix_v1"


def build_learned_skill_matrix(graphs: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize reusable learned skills across runtime PathGraph artifacts."""

    grouped: dict[str, dict[str, Any]] = {}
    for graph in graphs:
        if not isinstance(graph, dict):
            continue
        app_id = str(graph.get("app_id") or "unknown")
        transitions_by_action = defaultdict(list)
        for transition in graph.get("transitions") or []:
            if isinstance(transition, dict):
                transitions_by_action[str(transition.get("action_template_id") or "")].append(transition)

        for template in graph.get("action_templates") or []:
            if not isinstance(template, dict):
                continue
            action_id = str(template.get("action_template_id") or template.get("action_id") or "").strip()
            if not action_id:
                continue
            skill_ref = str(template.get("learned_skill_ref") or _default_skill_ref(action_id, template)).strip()
            if not skill_ref:
                continue
            item = grouped.setdefault(
                skill_ref,
                {
                    "skill_ref": skill_ref,
                    "used_by": set(),
                    "action_templates": set(),
                    "low_level_action_types": set(),
                    "action_kinds": set(),
                    "verified_cases": 0,
                    "safety_scope": set(),
                    "artifact_is_authorization": False,
                },
            )
            item["used_by"].add(app_id)
            item["action_templates"].add(action_id)
            item["low_level_action_types"].add(infer_low_level_action_type(action_id, template))
            item["action_kinds"].add(infer_action_kind(action_id, template))
            item["verified_cases"] = len(item["used_by"])
            item["artifact_is_authorization"] = bool(item["artifact_is_authorization"] or template.get("artifact_is_authorization") is True)
            _add_safety_scopes(item["safety_scope"], template, transitions_by_action.get(action_id) or [])

    skills = []
    for item in grouped.values():
        skills.append(
            {
                "skill_ref": item["skill_ref"],
                "used_by": sorted(item["used_by"]),
                "action_templates": sorted(item["action_templates"]),
                "low_level_action_types": sorted(item["low_level_action_types"]),
                "action_kinds": sorted(item["action_kinds"]),
                "verified_cases": int(item["verified_cases"]),
                "safety_scope": sorted(item["safety_scope"]),
                "artifact_is_authorization": bool(item["artifact_is_authorization"]),
            }
        )
    skills.sort(key=lambda entry: (entry["skill_ref"], entry["used_by"]))
    return {
        "contract_version": LEARNED_SKILL_MATRIX_CONTRACT,
        "baseline_count": len({str(graph.get("app_id") or "unknown") for graph in graphs if isinstance(graph, dict)}),
        "skills": skills,
        "summary": {
            "skill_count": len(skills),
            "covers_click": _covers(skills, "click"),
            "covers_scroll": _covers(skills, "scroll"),
            "covers_input": _covers(skills, "input"),
            "covers_read": any("read" in (item.get("action_kinds") or []) for item in skills),
            "covers_guarded_actions": any("guarded_or_hidden_by_default" in (item.get("safety_scope") or []) for item in skills),
            "covers_filter_or_tab": _covers_skill(skills, ("filter", "tab")),
            "covers_sort_or_filter_click": _covers_skill(skills, ("sort", "filter")),
            "covers_table_record_open": _covers_skill(skills, ("table", "row", "record")),
            "artifact_authorizes_click": any(bool(item.get("artifact_is_authorization")) for item in skills),
        },
    }


def _add_safety_scopes(target: set[str], template: dict[str, Any], transitions: list[dict[str, Any]]) -> None:
    action_id = str(template.get("action_template_id") or template.get("action_id") or "")
    low_level = infer_low_level_action_type(action_id, template)
    if low_level == "input":
        input_policy = template.get("input_policy") if isinstance(template.get("input_policy"), dict) else {}
        category = str(input_policy.get("input_category") or "").strip()
        target.add(category if category else "input_requires_agent_text")
        if input_policy.get("submit_allowed") is True:
            target.add("explicit_submit_allowed_by_policy")
    if low_level == "click":
        target.add("gated_click")
    if low_level == "scroll":
        target.add("no_write_scroll")
    if _is_guarded_action(action_id, template, transitions):
        target.add("guarded_or_hidden_by_default")
    if _mentions_final_submit(template):
        target.add("final_submit_forbidden")


def _is_guarded_action(action_id: str, template: dict[str, Any], transitions: list[dict[str, Any]]) -> bool:
    policy = template.get("availability_policy") if isinstance(template.get("availability_policy"), dict) else {}
    return (
        action_id == "apply_entry"
        or policy.get("default_available") is False
        or any(transition.get("default_available") is False for transition in transitions)
    )


def _mentions_final_submit(template: dict[str, Any]) -> bool:
    haystack = " ".join(str(value) for value in template.values() if isinstance(value, (str, int, float))).casefold()
    return "final_submit" in haystack or "submit" in haystack


def _default_skill_ref(action_id: str, template: dict[str, Any]) -> str:
    low_level = infer_low_level_action_type(action_id, template)
    if low_level == "input":
        return "skill:input_text_into_field"
    if low_level == "scroll":
        return "skill:scroll_until_more_content"
    if low_level == "click":
        return "skill:open_record_from_list"
    return ""


def _covers(skills: list[dict[str, Any]], low_level_action_type: str) -> bool:
    return any(low_level_action_type in (item.get("low_level_action_types") or []) for item in skills)


def _covers_skill(skills: list[dict[str, Any]], tokens: tuple[str, ...]) -> bool:
    for item in skills:
        haystack = " ".join(
            [
                str(item.get("skill_ref") or ""),
                " ".join(str(action_id) for action_id in item.get("action_templates") or []),
                " ".join(str(scope) for scope in item.get("safety_scope") or []),
            ]
        ).casefold()
        if any(token in haystack for token in tokens):
            return True
    return False
