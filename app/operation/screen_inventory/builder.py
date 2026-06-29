from __future__ import annotations

import re
import time
from typing import Any


ACTION_TYPES = {
    "button",
    "icon_button",
    "input",
    "text_input",
    "search_input",
    "link",
    "tab",
    "menu",
    "menu_item",
    "checkbox",
    "radio",
    "toggle",
    "select",
    "combobox",
    "card",
    "news_card",
}

ACTION_ROLES = {
    "button",
    "icon_button",
    "input",
    "text_input",
    "search_box",
    "search_input",
    "link",
    "tab",
    "menu",
    "menu_item",
    "checkbox",
    "radio",
    "toggle",
    "switch",
    "select",
    "combobox",
    "dropdown",
    "card",
    "news_card",
}

CLICKABLE_UIA_TYPES = {
    "button",
    "hyperlink",
    "edit",
    "combo box",
    "combobox",
    "check box",
    "checkbox",
    "radio button",
    "radiobutton",
    "tab item",
    "tabitem",
    "menu item",
    "menuitem",
    "list item",
    "listitem",
}

ACTION_PATTERNS = {"Invoke", "Value", "Selection", "ExpandCollapse", "Toggle"}
METADATA_HINTS = {
    "pay",
    "date",
    "posted",
    "listed",
    "salary",
    "location",
    "company",
    "classification",
    "work type",
    "remote",
}


def build_screen_inventory(screen_reading: dict[str, Any] | None, *, goal: str | None = None) -> dict[str, Any]:
    """Build a fast agent-facing inventory from structured UI evidence."""

    started = time.perf_counter()
    screen = screen_reading if isinstance(screen_reading, dict) else {}
    ui = screen.get("ui") if isinstance(screen.get("ui"), dict) else {}
    ui_elements = _as_list(screen.get("ui_elements") or ui.get("elements"))
    texts = _as_list(screen.get("texts"))
    uia_controls = _uia_controls(screen)

    available_actions = _dedupe_items(
        [_action_from_element(item, source_index=index) for index, item in enumerate(ui_elements) if _element_is_action(item)]
        + [_action_from_uia(control, source_index=index) for index, control in enumerate(uia_controls) if _uia_is_action(control)]
    )
    page_elements = _dedupe_items(
        [_page_element_from_text(item, source_index=index) for index, item in enumerate(texts)]
        + [_page_element_from_element(item, source_index=index) for index, item in enumerate(ui_elements) if not _element_is_action(item)]
        + [_page_element_from_uia(control, source_index=index) for index, control in enumerate(uia_controls) if not _uia_is_action(control)]
    )
    cards = _build_cards(available_actions=available_actions, page_elements=page_elements)
    action_ids_in_cards = {child_id for card in cards for child_id in card.get("child_action_ids", [])}
    page_ids_in_cards = {child_id for card in cards for child_id in card.get("child_page_element_ids", [])}

    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "contract_version": "screen_inventory_v1",
        "source_contract": screen.get("contract_version"),
        "goal": goal,
        "summary": {
            "available_action_count": len(available_actions),
            "page_element_count": len(page_elements),
            "card_count": len(cards),
            "action_ids_in_cards": len(action_ids_in_cards),
            "page_element_ids_in_cards": len(page_ids_in_cards),
            "duplicate_policy": "normalized_label_role_bbox_iou",
            "build_elapsed_ms": elapsed_ms,
        },
        "available_actions": available_actions,
        "page_elements": page_elements,
        "cards": cards,
        "quality": {
            "duplicate_rate": _duplicate_rate(available_actions + page_elements),
            "coordinate_coverage": _coordinate_coverage(available_actions),
            "sources": _source_counts(available_actions + page_elements),
        },
    }


def _action_from_element(element: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    role = _role_of(element)
    bbox = _bbox_of(element)
    label = _label_of(element) or role
    uia_match = ((element.get("provider_matches") or {}).get("uia") if isinstance(element.get("provider_matches"), dict) else None)
    uia_match = uia_match if isinstance(uia_match, dict) else None
    return {
        "id": f"action_screen_{source_index}_{_slug(label or role)}",
        "contract_version": "available_action_v1",
        "label": label,
        "role": role,
        "action_type": _action_type(role),
        "bbox": bbox,
        "click_point": _point_of(element, bbox),
        "confidence": _float(element.get("confidence"), default=0.5),
        "coordinate_confidence": element.get("coordinate_confidence") or "medium",
        "source": "screen_reading.ui_elements",
        "source_id": element.get("id"),
        "metadata": {
            "interaction_type": element.get("interaction_type"),
            "evidence_level": element.get("evidence_level"),
            "uia_match": _compact_uia(uia_match),
            "reasons": _action_reasons(element=element, uia=uia_match),
        },
    }


def _action_from_uia(control: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    bbox = _bbox_of(control)
    label = _label_of(control) or _role_of(control)
    role = _uia_role(control)
    return {
        "id": f"action_uia_{source_index}_{_slug(label or role)}",
        "contract_version": "available_action_v1",
        "label": label,
        "role": role,
        "action_type": _action_type(role),
        "bbox": bbox,
        "click_point": _center(bbox),
        "confidence": 0.82,
        "coordinate_confidence": "high",
        "source": "windows_uia.controls",
        "source_id": control.get("control_id"),
        "metadata": {
            "control_type": control.get("control_type"),
            "automation_id": control.get("automation_id"),
            "patterns": list(control.get("patterns") or []),
            "reasons": _action_reasons(uia=control),
        },
    }


def _page_element_from_text(text: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    bbox = _bbox_of(text)
    label = _label_of(text)
    return {
        "id": f"page_text_{source_index}_{_slug(label)}",
        "contract_version": "page_element_v1",
        "text": label,
        "role": "text",
        "bbox": bbox,
        "source": "screen_reading.texts",
        "source_id": text.get("id"),
        "metadata": {
            "confidence": _float(text.get("confidence"), default=0.5),
            "semantic_hint": _semantic_hint(label),
        },
    }


def _page_element_from_element(element: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    bbox = _bbox_of(element)
    label = _label_of(element)
    return {
        "id": f"page_element_{source_index}_{_slug(label or _role_of(element))}",
        "contract_version": "page_element_v1",
        "text": label,
        "role": _role_of(element),
        "bbox": bbox,
        "source": "screen_reading.ui_elements",
        "source_id": element.get("id"),
        "metadata": {
            "confidence": _float(element.get("confidence"), default=0.5),
            "semantic_hint": _semantic_hint(label),
        },
    }


def _page_element_from_uia(control: dict[str, Any], *, source_index: int) -> dict[str, Any]:
    bbox = _bbox_of(control)
    label = _label_of(control)
    return {
        "id": f"page_uia_{source_index}_{_slug(label or _role_of(control))}",
        "contract_version": "page_element_v1",
        "text": label,
        "role": _uia_role(control),
        "bbox": bbox,
        "source": "windows_uia.controls",
        "source_id": control.get("control_id"),
        "metadata": {
            "control_type": control.get("control_type"),
            "automation_id": control.get("automation_id"),
            "semantic_hint": _semantic_hint(label),
        },
    }


def _build_cards(*, available_actions: list[dict[str, Any]], page_elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seed_actions = [
        item
        for item in available_actions
        if item.get("role") in {"card", "news_card"}
        or item.get("action_type") == "open_card"
        or _looks_like_card_bbox(item.get("bbox"))
    ]
    cards: list[dict[str, Any]] = []
    for index, action in enumerate(seed_actions):
        bbox = action.get("bbox")
        if not isinstance(bbox, dict):
            continue
        child_actions = [
            item["id"]
            for item in available_actions
            if item["id"] != action["id"] and _bbox_contains_center(bbox, item.get("bbox"))
        ]
        child_page_elements = [
            item["id"]
            for item in page_elements
            if _bbox_contains_center(bbox, item.get("bbox"))
        ]
        cards.append(
            {
                "id": f"card_{index}_{_slug(action.get('label') or action.get('role'))}",
                "contract_version": "card_v1",
                "label": action.get("label"),
                "role": action.get("role"),
                "bbox": bbox,
                "primary_action_id": action["id"],
                "child_action_ids": child_actions,
                "child_page_element_ids": child_page_elements,
                "metadata": {
                    "source": action.get("source"),
                    "metadata_child_count": len(child_page_elements),
                    "action_child_count": len(child_actions),
                },
            }
        )
    return _dedupe_items(cards)


def _element_is_action(element: dict[str, Any]) -> bool:
    role = _role_of(element)
    type_name = _normalize(element.get("type"))
    if role in ACTION_ROLES or type_name in ACTION_TYPES:
        return True
    interaction_type = _normalize(element.get("interaction_type"))
    if interaction_type in {"click", "focus", "input", "select", "toggle", "open"}:
        return True
    policy = ((element.get("evidence") or {}).get("interaction_policy") if isinstance(element.get("evidence"), dict) else None)
    if isinstance(policy, dict) and policy.get("allowed") is True:
        return True
    uia = ((element.get("provider_matches") or {}).get("uia") if isinstance(element.get("provider_matches"), dict) else None)
    return isinstance(uia, dict) and _uia_is_action(uia)


def _uia_is_action(control: dict[str, Any]) -> bool:
    if control.get("enabled") is False or control.get("visible") is False:
        return False
    control_type = _normalize(control.get("control_type"))
    if control_type in CLICKABLE_UIA_TYPES:
        return True
    patterns = {str(item) for item in control.get("patterns") or []}
    return bool(patterns & ACTION_PATTERNS)


def _uia_controls(screen: dict[str, Any]) -> list[dict[str, Any]]:
    source_layers = screen.get("source_layers") if isinstance(screen.get("source_layers"), dict) else {}
    uia_layer = source_layers.get("windows_uia") if isinstance(source_layers, dict) else {}
    controls = uia_layer.get("controls") if isinstance(uia_layer, dict) else None
    if isinstance(controls, list):
        return [item for item in controls if isinstance(item, dict)]
    ui = screen.get("ui") if isinstance(screen.get("ui"), dict) else {}
    provider_slots = ui.get("provider_slots") if isinstance(ui.get("provider_slots"), dict) else {}
    uia_slot = provider_slots.get("uia") if isinstance(provider_slots, dict) else {}
    controls = uia_slot.get("controls") if isinstance(uia_slot, dict) else None
    return [item for item in controls or [] if isinstance(item, dict)]


def _dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in items:
        if not item.get("bbox"):
            continue
        duplicate = _find_duplicate(kept, item)
        if duplicate is None:
            kept.append(item)
            continue
        if _item_quality(item) > _item_quality(duplicate):
            kept[kept.index(duplicate)] = item
    return kept


def _find_duplicate(items: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any] | None:
    label = _normalized_label(item.get("label") or item.get("text"))
    role = _normalize(item.get("role"))
    for existing in items:
        existing_label = _normalized_label(existing.get("label") or existing.get("text"))
        existing_role = _normalize(existing.get("role"))
        same_label = bool(label and existing_label and (label == existing_label or label in existing_label or existing_label in label))
        same_role = not role or not existing_role or role == existing_role
        if same_label and same_role and _bbox_iou(existing.get("bbox"), item.get("bbox")) >= 0.35:
            return existing
    return None


def _item_quality(item: dict[str, Any]) -> float:
    score = _float(item.get("confidence"), default=0.5)
    if item.get("source") == "windows_uia.controls":
        score += 0.15
    if item.get("coordinate_confidence") == "high":
        score += 0.1
    return score


def _action_reasons(*, element: dict[str, Any] | None = None, uia: dict[str, Any] | None = None) -> list[str]:
    reasons: list[str] = []
    if element is not None:
        role = _role_of(element)
        if role in ACTION_ROLES:
            reasons.append("action_role")
        if _normalize(element.get("interaction_type")):
            reasons.append("interaction_type")
    if uia is not None:
        if _normalize(uia.get("control_type")) in CLICKABLE_UIA_TYPES:
            reasons.append("uia_clickable_control_type")
        if set(str(item) for item in uia.get("patterns") or []) & ACTION_PATTERNS:
            reasons.append("uia_action_pattern")
    return sorted(set(reasons))


def _action_type(role: str) -> str:
    role = _normalize(role)
    if role in {"input", "text_input", "search_box", "search_input", "edit"}:
        return "input_text"
    if role in {"checkbox", "radio", "toggle", "switch"}:
        return "toggle"
    if role in {"select", "combobox", "dropdown"}:
        return "select"
    if role in {"card", "news_card"}:
        return "open_card"
    return "click"


def _uia_role(control: dict[str, Any]) -> str:
    control_type = _normalize(control.get("control_type"))
    if control_type == "hyperlink":
        return "link"
    if control_type == "edit":
        return "input"
    if control_type in {"combo box", "combobox"}:
        return "combobox"
    if control_type in {"check box", "checkbox"}:
        return "checkbox"
    if control_type in {"radio button", "radiobutton"}:
        return "radio"
    if control_type in {"tab item", "tabitem"}:
        return "tab"
    if control_type in {"menu item", "menuitem"}:
        return "menu_item"
    return control_type or "control"


def _role_of(item: dict[str, Any]) -> str:
    return _normalize(item.get("role") or item.get("role_guess") or item.get("control_type") or item.get("type") or "unknown")


def _label_of(item: dict[str, Any]) -> str:
    for key in ("label", "text", "name", "description", "automation_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _bbox_of(item: dict[str, Any]) -> dict[str, int]:
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    width = bbox.get("w", bbox.get("width", 0))
    height = bbox.get("h", bbox.get("height", 0))
    return {
        "x": int(float(bbox.get("x") or 0)),
        "y": int(float(bbox.get("y") or 0)),
        "w": max(0, int(float(width or 0))),
        "h": max(0, int(float(height or 0))),
    }


def _point_of(item: dict[str, Any], bbox: dict[str, int]) -> dict[str, int]:
    point = item.get("click_point") if isinstance(item.get("click_point"), dict) else {}
    x = point.get("x")
    y = point.get("y")
    if x is None or y is None:
        return _center(bbox)
    return {"x": int(float(x)), "y": int(float(y))}


def _center(bbox: dict[str, int]) -> dict[str, int]:
    return {"x": int(bbox["x"] + bbox["w"] / 2), "y": int(bbox["y"] + bbox["h"] / 2)}


def _bbox_contains_center(container: dict[str, Any] | None, child: dict[str, Any] | None) -> bool:
    if not isinstance(container, dict) or not isinstance(child, dict):
        return False
    normalized = _bbox_of({"bbox": child})
    point = _center(normalized)
    c = _bbox_of({"bbox": container})
    return c["x"] <= point["x"] <= c["x"] + c["w"] and c["y"] <= point["y"] <= c["y"] + c["h"]


def _bbox_iou(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return 0.0
    aa = _bbox_of({"bbox": a})
    bb = _bbox_of({"bbox": b})
    ax2 = aa["x"] + aa["w"]
    ay2 = aa["y"] + aa["h"]
    bx2 = bb["x"] + bb["w"]
    by2 = bb["y"] + bb["h"]
    overlap_w = max(0, min(ax2, bx2) - max(aa["x"], bb["x"]))
    overlap_h = max(0, min(ay2, by2) - max(aa["y"], bb["y"]))
    overlap = overlap_w * overlap_h
    union = aa["w"] * aa["h"] + bb["w"] * bb["h"] - overlap
    return overlap / union if union > 0 else 0.0


def _looks_like_card_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, dict):
        return False
    b = _bbox_of({"bbox": bbox})
    return b["w"] >= 220 and b["h"] >= 70


def _semantic_hint(label: str) -> str | None:
    normalized = _normalized_label(label)
    for hint in METADATA_HINTS:
        if hint in normalized:
            return hint
    if re.search(r"\b\d+\s*(day|hour|minute|week|month)s?\s+ago\b", str(label or "").casefold()):
        return "posted"
    if re.search(r"\$\s*\d", str(label or "")):
        return "salary"
    return None


def _compact_uia(uia: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(uia, dict):
        return None
    return {
        "control_id": uia.get("control_id"),
        "name": uia.get("name"),
        "control_type": uia.get("control_type"),
        "patterns": list(uia.get("patterns") or []),
    }


def _source_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        source = str(item.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _coordinate_coverage(actions: list[dict[str, Any]]) -> float | None:
    if not actions:
        return None
    covered = [
        item
        for item in actions
        if isinstance(item.get("bbox"), dict)
        and item["bbox"].get("w", 0) > 0
        and item["bbox"].get("h", 0) > 0
        and isinstance(item.get("click_point"), dict)
    ]
    return round(len(covered) / len(actions), 4)


def _duplicate_rate(items: list[dict[str, Any]]) -> float | None:
    if not items:
        return None
    keys: set[tuple[str, str]] = set()
    duplicates = 0
    for item in items:
        key = (_normalize(item.get("role")), _normalized_label(item.get("label") or item.get("text")))
        if key in keys:
            duplicates += 1
        keys.add(key)
    return round(duplicates / len(items), 4)


def _float(value: Any, *, default: float) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold().replace("_", " ")


def _normalized_label(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff$]+", " ", text)
    return " ".join(text.split())


def _slug(value: Any) -> str:
    text = _normalized_label(value)
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", text).strip("-")
    return text[:48] or "unnamed"
