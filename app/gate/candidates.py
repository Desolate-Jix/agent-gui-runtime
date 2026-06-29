from __future__ import annotations

from typing import Any


CANDIDATE_FRESHNESS_CONTRACT = "action_candidate_freshness_v1"
ACTION_CANDIDATE_TARGET_CONTRACT = "action_candidate_target_decision_v1"


def build_candidate_freshness(
    *,
    capture_id: str | None,
    viewport_size: dict[str, Any] | None,
    source: str,
    freshness: str = "current_capture",
) -> dict[str, Any]:
    return {
        "contract_version": CANDIDATE_FRESHNESS_CONTRACT,
        "capture_id": capture_id,
        "viewport_size": _viewport_size(viewport_size),
        "source": source,
        "freshness": freshness,
    }


def attach_candidate_freshness(
    candidate: dict[str, Any],
    *,
    capture_id: str | None,
    viewport_size: dict[str, Any] | None,
    source: str,
    freshness: str = "current_capture",
) -> dict[str, Any]:
    payload = dict(candidate)
    payload["candidate_freshness"] = build_candidate_freshness(
        capture_id=capture_id,
        viewport_size=viewport_size,
        source=source,
        freshness=freshness,
    )
    return payload


def validate_action_candidate_freshness(
    candidate: dict[str, Any],
    *,
    current_capture_id: str | None,
    current_viewport_size: dict[str, Any] | None,
) -> dict[str, Any]:
    freshness = candidate.get("candidate_freshness") if isinstance(candidate.get("candidate_freshness"), dict) else {}
    required = ["capture_id", "viewport_size", "source", "freshness"]
    missing = [key for key in required if not freshness.get(key)]
    bbox = _bbox(candidate.get("bbox") or candidate.get("card_bbox"))
    point = _point(candidate.get("click_point") or candidate.get("point"))
    reasons: list[str] = []
    if missing:
        reasons.append("candidate_freshness_missing_fields")
    if not bbox:
        reasons.append("candidate_bbox_missing")
    if not point:
        reasons.append("candidate_click_point_missing")
    if bbox and point and not _point_inside_bbox(point, bbox):
        reasons.append("candidate_click_point_outside_bbox")
    if current_capture_id and freshness.get("capture_id") and freshness.get("capture_id") != current_capture_id:
        reasons.append("candidate_capture_id_stale")
    if current_viewport_size and freshness.get("viewport_size") and freshness.get("viewport_size") != _viewport_size(current_viewport_size):
        reasons.append("candidate_viewport_size_stale")
    if freshness.get("freshness") not in {"current_capture", "reviewed_current_capture"}:
        reasons.append("candidate_not_current")
    return {
        "contract_version": "action_candidate_freshness_decision_v1",
        "allowed": not reasons,
        "reasons": reasons or ["candidate_freshness_current"],
        "candidate_freshness": freshness or None,
    }


def validate_action_candidate_target_at_point(
    point: dict[str, Any] | None,
    *,
    pre_click_decision: dict[str, Any] | None,
    allowed_labels: set[str] | frozenset[str],
    forbidden_labels: set[str] | frozenset[str] | None = None,
    forbidden_label_prefixes: tuple[str, ...] = (),
) -> dict[str, Any]:
    normalized_point = _point(point)
    if not normalized_point:
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "missing_selected_click_point",
        }
    if not isinstance(pre_click_decision, dict):
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "missing_pre_click_decision",
        }
    selected_id = pre_click_decision.get("selected_candidate_id")
    decisions = pre_click_decision.get("candidate_decisions")
    if not isinstance(decisions, list):
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "missing_candidate_decisions",
        }
    selected_decision = next(
        (
            item
            for item in decisions
            if isinstance(item, dict)
            and selected_id
            and item.get("candidate_id") == selected_id
        ),
        None,
    )
    if not isinstance(selected_decision, dict):
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "missing_selected_candidate_decision",
        }
    normalized_allowed = {_normalise_action_label(label) for label in allowed_labels if _normalise_action_label(label)}
    normalized_forbidden = {_normalise_action_label(label) for label in (forbidden_labels or set()) if _normalise_action_label(label)}
    normalized_prefixes = tuple(_normalise_action_label(prefix) for prefix in forbidden_label_prefixes if _normalise_action_label(prefix))
    selected_label = _candidate_target_text(selected_decision)
    overlapping_allowed: list[dict[str, Any]] = []
    overlapping_forbidden: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        label = _candidate_target_text(decision)
        bbox = _candidate_decision_bbox(decision)
        if not bbox or not _point_inside_bbox(normalized_point, bbox):
            continue
        if label in normalized_allowed:
            overlapping_allowed.append(
                {
                    "candidate_id": decision.get("candidate_id"),
                    "label": label,
                    "bbox": bbox,
                }
            )
        elif _label_forbidden(label, normalized_forbidden, normalized_prefixes):
            overlapping_forbidden.append(
                {
                    "candidate_id": decision.get("candidate_id"),
                    "label": label,
                    "bbox": bbox,
                }
            )
    if overlapping_forbidden:
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "profile_mutation_candidate_at_click_point",
            "selected_candidate_id": selected_id,
            "selected_candidate_label": selected_label,
            "overlapping_forbidden_candidates": overlapping_forbidden,
        }
    if selected_label not in normalized_allowed and not overlapping_allowed:
        return {
            "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
            "allowed": False,
            "reason": "continue_candidate_label_not_allowed",
            "selected_candidate_id": selected_id,
            "selected_candidate_label": selected_label,
        }
    return {
        "contract_version": ACTION_CANDIDATE_TARGET_CONTRACT,
        "allowed": True,
        "reason": "continue_candidate_label_allowed"
        if selected_label in normalized_allowed
        else "visible_continue_candidate_at_click_point",
        "selected_candidate_id": selected_id,
        "selected_candidate_label": selected_label,
        "overlapping_allowed_candidates": overlapping_allowed,
    }


def _viewport_size(value: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        width = int(value.get("width"))
        height = int(value.get("height"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x"))
        y = int(value.get("y"))
        w = int(value.get("w") if value.get("w") is not None else value.get("width"))
        h = int(value.get("h") if value.get("h") is not None else value.get("height"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _point(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {"x": int(value.get("x")), "y": int(value.get("y"))}
    except (TypeError, ValueError):
        return None


def _point_inside_bbox(point: dict[str, int], bbox: dict[str, int]) -> bool:
    return bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"] and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]


def _normalise_action_label(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return " ".join(text.replace("\n", " ").replace("\t", " ").split())


def _candidate_target_text(decision: dict[str, Any]) -> str:
    resolved = decision.get("resolved_click_point") if isinstance(decision.get("resolved_click_point"), dict) else {}
    return _normalise_action_label(resolved.get("target_text") or decision.get("target_text") or decision.get("label"))


def _candidate_decision_bbox(decision: dict[str, Any]) -> dict[str, int] | None:
    resolved = decision.get("resolved_click_point") if isinstance(decision.get("resolved_click_point"), dict) else {}
    return _bbox(resolved.get("bbox") if isinstance(resolved, dict) else None) or _bbox(decision.get("bbox"))


def _label_forbidden(label: str, forbidden_labels: set[str], forbidden_label_prefixes: tuple[str, ...]) -> bool:
    if not label:
        return False
    if label in forbidden_labels:
        return True
    return any(label.startswith(prefix) for prefix in forbidden_label_prefixes)
