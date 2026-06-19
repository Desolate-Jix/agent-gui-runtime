from __future__ import annotations

from typing import Any


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
