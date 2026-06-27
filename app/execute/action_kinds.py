from __future__ import annotations

from typing import Any


ACTION_TAXONOMY_CONTRACT = "action_taxonomy_v1"
ACTION_TAXONOMY_KINDS = {
    "open_detail",
    "open_apply_flow",
    "fill_field",
    "continue_next_step",
    "final_submit",
    "send",
    "confirm",
    "payment",
}


def normalize_low_level_action_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "type": "input",
        "type_text": "input",
        "text_input": "input",
        "fill": "input",
        "safe_fill": "input",
        "wheel": "scroll",
        "scroll_container": "scroll",
        "press": "input",
    }
    return aliases.get(raw, raw)


def infer_low_level_action_type(action_template_id: str, template: dict[str, Any] | None) -> str:
    action_id = str(action_template_id or "").strip().lower()
    tpl = template if isinstance(template, dict) else {}
    declared = normalize_low_level_action_type(
        tpl.get("low_level_action_type")
        or tpl.get("action_type")
        or tpl.get("kind")
        or tpl.get("operation")
    )
    if declared in {"click", "scroll", "input", "observe", "verify"}:
        return declared
    if _looks_like_click_action(action_id, tpl):
        return "click"
    if _looks_like_input_action(action_id, tpl):
        return "input"
    if isinstance(tpl.get("scroll_target"), dict) or action_id in {"read_detail", "load_more_results"}:
        return "scroll"
    return "click"


def infer_action_kind(action_template_id: str, template: dict[str, Any] | None) -> str:
    action_id = str(action_template_id or "").strip().lower()
    low_level = infer_low_level_action_type(action_id, template)
    if action_id.startswith("read_"):
        return "read"
    return low_level


def classify_action_taxonomy(action_template_id: str = "", template: dict[str, Any] | None = None, *, label: Any = None) -> dict[str, Any]:
    action_id = str(action_template_id or "").strip().lower()
    tpl = template if isinstance(template, dict) else {}
    declared = str(tpl.get("action_taxonomy") or tpl.get("semantic_action_type") or "").strip().lower()
    text = " ".join(
        str(value or "")
        for value in [
            action_id,
            label,
            tpl.get("label"),
            tpl.get("goal_template"),
            tpl.get("learned_skill_ref"),
            tpl.get("skill_ref"),
        ]
    ).casefold()
    if declared in ACTION_TAXONOMY_KINDS:
        kind = declared
        reason = "declared_action_taxonomy"
    elif _looks_like_final_submit(text):
        kind = "final_submit"
        reason = "final_submit_terms"
    elif "quick apply" in text or "apply_entry" in action_id or "open apply" in text:
        kind = "open_apply_flow"
        reason = "apply_entry_is_flow_open"
    elif action_id.startswith("open_") or any(token in text for token in ("open job", "open detail", "job card", "search result")):
        kind = "open_detail"
        reason = "open_detail_terms"
    elif any(token in text for token in ("continue", "next step", "下一步", "继续")):
        kind = "continue_next_step"
        reason = "continue_terms"
    elif _looks_like_input_action(action_id, tpl):
        kind = "fill_field"
        reason = "input_terms"
    else:
        kind = infer_action_kind(action_id, tpl)
        reason = "low_level_fallback"
    return {
        "contract_version": ACTION_TAXONOMY_CONTRACT,
        "kind": kind,
        "reason": reason,
        "final_submit": kind in {"final_submit", "send", "confirm", "payment"},
        "open_apply_flow": kind == "open_apply_flow",
    }


def _looks_like_input_action(action_id: str, template: dict[str, Any]) -> bool:
    if any(token in action_id for token in ("input", "type", "fill", "search", "enter_text")):
        return True
    learned_skill_ref = str(template.get("learned_skill_ref") or "").lower()
    if any(token in learned_skill_ref for token in ("input", "type", "fill", "search")):
        return True
    return any(
        isinstance(template.get(key), dict)
        for key in ("input_target", "text_input_target", "field_target")
    ) or isinstance(template.get("input_policy"), dict)


def _looks_like_click_action(action_id: str, template: dict[str, Any]) -> bool:
    if action_id.startswith(("open_", "click_", "select_", "choose_")):
        return True
    if any(token in action_id for token in ("card", "button", "link", "apply_entry")):
        return True
    learned_skill_ref = str(template.get("learned_skill_ref") or "").lower()
    return any(token in learned_skill_ref for token in ("open_card", "click", "select"))


def _looks_like_final_submit(text: str) -> bool:
    lowered = str(text or "").casefold()
    terms = (
        "submit application",
        "send application",
        "complete application",
        "confirm application",
        "payment",
        "pay now",
        "purchase",
        "final_submit",
        "最终提交",
        "提交申请",
        "确认提交",
        "付款",
    )
    return any(term in lowered for term in terms)
