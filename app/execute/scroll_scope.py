from __future__ import annotations

from typing import Any


SCROLL_SCOPE_CONTRACT = "scroll_scope_invariant_v1"


def build_scroll_scope_invariant(
    *,
    target_container_id: str | None,
    target_changed: bool | None,
    non_target_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    changes = [item for item in non_target_changes or [] if isinstance(item, dict) and item.get("changed") is True]
    wrong_scope = bool(changes)
    if target_changed is False and not wrong_scope:
        status = "no_target_progress"
    elif wrong_scope:
        status = "wrong_scope_detected"
    else:
        status = "ok"
    return {
        "contract_version": SCROLL_SCOPE_CONTRACT,
        "target_container_id": target_container_id,
        "target_container_content_changed": target_changed,
        "non_target_panes": non_target_changes or [],
        "wrong_scope_detected": wrong_scope,
        "status": status,
        "reasons": ["non_target_pane_changed"] if wrong_scope else (["target_did_not_change"] if target_changed is False else ["target_scope_ok"]),
    }


def apply_scroll_scope_invariant(scroll_result: dict[str, Any], invariant: dict[str, Any]) -> dict[str, Any]:
    payload = dict(scroll_result)
    payload["scroll_scope_invariant"] = invariant
    payload["wrong_scope_detected"] = bool(payload.get("wrong_scope_detected") or invariant.get("wrong_scope_detected"))
    effect = payload.get("scroll_effect_validation") if isinstance(payload.get("scroll_effect_validation"), dict) else {}
    if effect:
        effect = dict(effect)
        effect["wrong_scope_detected"] = bool(effect.get("wrong_scope_detected") or invariant.get("wrong_scope_detected"))
        effect["non_target_panes_stable"] = False if invariant.get("wrong_scope_detected") else effect.get("non_target_panes_stable")
        payload["scroll_effect_validation"] = effect
    return payload
