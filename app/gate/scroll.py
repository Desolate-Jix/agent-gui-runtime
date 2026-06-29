from __future__ import annotations

from typing import Any


SCROLL_SCOPE_CONTRACT = "scroll_scope_invariant_v1"


def _point_in_rect(point: dict[str, int], rect: dict[str, int]) -> bool:
    return rect["x"] <= point["x"] <= rect["x"] + rect["width"] and rect["y"] <= point["y"] <= rect["y"] + rect["height"]


def scroll_window_size_matches(requested: Any, actual: dict[str, int]) -> bool:
    if requested is None:
        return True
    if not isinstance(requested, dict):
        return False
    try:
        width = int(requested.get("width") or requested.get("w") or 0)
        height = int(requested.get("height") or requested.get("h") or 0)
    except (TypeError, ValueError):
        return False
    return width == int(actual["width"]) and height == int(actual["height"])


def build_scroll_safe_point(container_rect: dict[str, int], *, explicit_x: int | None, explicit_y: int | None) -> dict[str, int]:
    if explicit_x is not None and explicit_y is not None:
        return {"x": int(explicit_x), "y": int(explicit_y)}
    inset_x = max(12, min(48, int(container_rect["width"]) // 8))
    inset_y = max(12, min(64, int(container_rect["height"]) // 8))
    return {
        "x": int(container_rect["x"]) + max(inset_x, int(container_rect["width"]) // 2),
        "y": int(container_rect["y"]) + max(inset_y, int(container_rect["height"]) // 2),
    }


def build_scroll_precondition_decision(
    *,
    request: Any,
    window_rect: dict[str, int],
    point: dict[str, int],
    container_rect: dict[str, int] | None,
    target_container: dict[str, Any] | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    reject_reasons: list[str] = []
    window_bounds = {"x": 0, "y": 0, "width": max(0, int(window_rect["width"]) - 1), "height": max(0, int(window_rect["height"]) - 1)}
    if _point_in_rect(point, window_bounds):
        reasons.append("point_inside_window")
    else:
        reject_reasons.append("point_outside_window")
    if scroll_window_size_matches(getattr(request, "coordinate_window_size", None), window_rect):
        reasons.append("coordinate_window_size_matched" if getattr(request, "coordinate_window_size", None) else "coordinate_window_size_not_required")
    else:
        reject_reasons.append("coordinate_window_size_mismatch")
    if getattr(request, "scroll_scope", None) == "container":
        if target_container is not None:
            reasons.append("target_container_found")
        else:
            reject_reasons.append("target_container_missing")
        if container_rect is not None:
            reasons.append("container_bbox_available")
            if _point_in_rect(point, container_rect):
                reasons.append("point_inside_container")
            else:
                reject_reasons.append("point_outside_container")
        else:
            reject_reasons.append("container_bbox_missing")
        if target_container is not None:
            direction = getattr(request, "direction", "down")
            key = "can_scroll_down" if direction == "down" else "can_scroll_up"
            if target_container.get(key) is False:
                reject_reasons.append(f"container_cannot_scroll_{direction}")
            else:
                reasons.append(f"container_can_scroll_{direction}")
    else:
        reasons.append("window_or_page_scroll_scope")
    return {
        "contract_version": "scroll_precondition_decision_v1",
        "decision": "ALLOW" if not reject_reasons else "REJECT",
        "reasons": reasons,
        "reject_reasons": reject_reasons,
    }


def build_scroll_effect_validation(
    *,
    request: Any,
    post_scroll_verification: dict[str, Any] | None,
    target_container: dict[str, Any] | None,
) -> dict[str, Any]:
    verification = post_scroll_verification if isinstance(post_scroll_verification, dict) else {}
    diff = verification.get("diff") if isinstance(verification.get("diff"), dict) else {}
    changed = bool(diff.get("changed") or verification.get("verified"))
    return {
        "contract_version": "scroll_effect_validation_v1",
        "status": "moved" if changed else "unknown",
        "target_container_id": (target_container or {}).get("container_id") or getattr(request, "target_container_id", None),
        "target_pane": (target_container or {}).get("pane_role") or getattr(request, "target_pane", None),
        "target_container_content_changed": changed,
        "target_container_scroll_offset_changed": None,
        "same_semantic_page": True,
        "non_target_panes_stable": None,
        "wrong_scope_detected": False,
        "no_effect_detected": False if changed else None,
        "verification_basis": verification.get("verification_basis"),
    }


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
