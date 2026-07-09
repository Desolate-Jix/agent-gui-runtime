from __future__ import annotations

from copy import deepcopy
from typing import Any


LOCATOR_TASK_CARDS_CONTRACT = "learn_locator_task_cards_v1"
LOCATOR_TASK_CARD_CONTRACT = "learn_locator_task_card_v1"


def build_locator_task_cards(items: list[dict[str, Any]]) -> dict[str, Any]:
    """把整屏理解候选转换成后续精准定位可用的只读任务卡。"""

    safe_items = [item for item in items if isinstance(item, dict)]
    cards = [_build_card(item=item, all_items=safe_items) for item in safe_items]
    return {
        "contract_version": LOCATOR_TASK_CARDS_CONTRACT,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "cards": cards,
        "interpretation": (
            "Locator task cards enrich screen-understanding output for later dry-run grounding review; "
            "they are not click authorization and do not make semantic-only regions executable."
        ),
    }


def _build_card(*, item: dict[str, Any], all_items: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    role = _text(item.get("role"), item.get("item_type"), "unknown")
    label = _text(item.get("label"), item.get("text"), item.get("item_id"), "unknown target")
    visible_text = _text(item.get("text"), item.get("label"), label)
    evidence_level = _text(item.get("evidence_level"), "unknown")
    bbox = _bbox(item.get("bbox") if isinstance(item.get("bbox"), dict) else {})
    return {
        "contract_version": LOCATOR_TASK_CARD_CONTRACT,
        "source_item_id": str(item.get("item_id") or ""),
        "target_name": label,
        "target_role": role,
        "target_visible_text": visible_text,
        "item_type": str(item.get("item_type") or ""),
        "evidence_level": evidence_level,
        "source_evidence": deepcopy(item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []),
        "rough_bbox_hint": bbox,
        "rough_bbox_policy": "hint_only_can_be_replaced",
        "visual_description": _visual_description(item=item, role=role, visible_text=visible_text),
        "text_lines": _text_lines(item=item, visible_text=visible_text),
        "boundary_definition": _boundary_definition(item=item, role=role),
        "clickable_area_hint": _clickable_area_hint(item=item, role=role, visible_text=visible_text),
        "neighbor_context": _neighbor_context(item, all_items),
        "uia_control_type": metadata.get("control_type"),
        "uia_patterns": deepcopy(metadata.get("patterns") if isinstance(metadata.get("patterns"), list) else []),
        "parser_candidate": deepcopy(item.get("parser_candidate") if isinstance(item.get("parser_candidate"), dict) else {}),
        "interaction_target": _interaction_target(label=label, role=role, visible_text=visible_text),
        "must_not_click": ["browser toolbar", "clear icon", "final submit", "send", "confirm", "payment"],
        "expected_precise_output": "tight visible target bbox and safe interior point in full screenshot coordinates",
        "review_policy": _review_policy(evidence_level),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _visual_description(*, item: dict[str, Any], role: str, visible_text: str) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for key in ("description", "visual_description", "provider_description"):
        text = _text(metadata.get(key))
        if text:
            return text
    item_type = str(item.get("item_type") or "").casefold()
    if item_type == "form_field" or "input" in role.casefold() or "edit" in role.casefold():
        return f"editable input control for {visible_text}".strip()
    if "button" in role.casefold() or item_type == "actionable":
        return f"clickable control labeled {visible_text}".strip()
    return f"visible page element for {visible_text}".strip()


def _text_lines(*, item: dict[str, Any], visible_text: str) -> list[str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    lines = metadata.get("text_lines")
    if isinstance(lines, list):
        return [str(line).strip() for line in lines if str(line or "").strip()]
    return [visible_text] if visible_text else []


def _boundary_definition(*, item: dict[str, Any], role: str) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text = _text(metadata.get("boundary_definition"))
    if text:
        return text
    if "button" in role.casefold():
        return "tight visible button boundary, excluding neighboring text or controls"
    if "input" in role.casefold() or "edit" in role.casefold():
        return "visible input body boundary, excluding clear icons and surrounding header"
    return "smallest visible module boundary, excluding neighboring modules"


def _clickable_area_hint(*, item: dict[str, Any], role: str, visible_text: str) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text = _text(metadata.get("clickable_area_hint"))
    if text:
        return text
    if "button" in role.casefold():
        return f"visual center of the button labeled {visible_text}".strip()
    if "input" in role.casefold() or "edit" in role.casefold():
        return f"inside the input body for {visible_text}".strip()
    return "safe interior point away from neighboring controls"


def _neighbor_context(item: dict[str, Any], all_items: list[dict[str, Any]]) -> dict[str, str | None]:
    bbox = _bbox(item.get("bbox") if isinstance(item.get("bbox"), dict) else {})
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
    candidates: list[tuple[str, float, str]] = []
    item_id = str(item.get("item_id") or "")
    for other in all_items:
        if str(other.get("item_id") or "") == item_id:
            continue
        obox = _bbox(other.get("bbox") if isinstance(other.get("bbox"), dict) else {})
        ox = obox["x"] + obox["w"] / 2
        oy = obox["y"] + obox["h"] / 2
        label = _text(other.get("label"), other.get("text"), other.get("item_id"))
        if abs(oy - center_y) <= max(80, bbox["h"] * 1.5):
            if ox < center_x:
                candidates.append(("left", center_x - ox, label))
            elif ox > center_x:
                candidates.append(("right", ox - center_x, label))
        if abs(ox - center_x) <= max(160, bbox["w"] * 0.75):
            if oy < center_y:
                candidates.append(("above", center_y - oy, label))
            elif oy > center_y:
                candidates.append(("below", oy - center_y, label))
    out: dict[str, str | None] = {"left": None, "right": None, "above": None, "below": None}
    for direction in out:
        matches = sorted((candidate for candidate in candidates if candidate[0] == direction), key=lambda candidate: candidate[1])
        if matches:
            out[direction] = matches[0][2]
    return out


def _interaction_target(*, label: str, role: str, visible_text: str) -> str:
    role_text = role.casefold()
    text = visible_text or label
    if "input" in role_text or "edit" in role_text or "textbox" in role_text:
        return f"click inside the input body for {text}, not the clear icon or surrounding header"
    if "button" in role_text:
        return f"click the visible button body labeled {text}, preferably near the visual center"
    return f"locate the visible target area for {text}; avoid nested unrelated controls"


def _review_policy(evidence_level: str) -> dict[str, Any]:
    semantic_only = evidence_level.casefold() == "semantic_region_only"
    return {
        "semantic_only_requires_human_review": semantic_only,
        "requires_cross_evidence_before_promotion": semantic_only,
        "interpretation": "Semantic-only regions remain review-only until OCR/UIA/DOM/calibrated support confirms the target.",
    }


def _bbox(value: dict[str, Any]) -> dict[str, int]:
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w", value.get("width")))),
        "h": max(0, _int_or_zero(value.get("h", value.get("height")))),
    }


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
