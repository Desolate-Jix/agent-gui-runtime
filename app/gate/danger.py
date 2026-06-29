from __future__ import annotations

import re
from typing import Any


FINAL_SUBMIT_SCOPE_CONTRACT = "scoped_final_submit_guard_v1"
FINAL_SUBMIT_TERMS = {
    "submit application",
    "submit your application",
    "send application",
    "send your application",
    "complete application",
    "complete your application",
    "confirm application",
    "finish application",
    "提交申请",
    "发送申请",
    "确认提交",
}


def scoped_final_submit_visible_blocker(
    items: list[dict[str, Any]],
    *,
    active_container: dict[str, Any] | None = None,
    active_flow_started: bool = False,
) -> dict[str, Any]:
    scoped_items = [
        item
        for item in items
        if _item_in_active_scope(item, active_container=active_container, active_flow_started=active_flow_started)
    ]
    matched_terms: list[str] = []
    matched_items: list[dict[str, Any]] = []
    for item in scoped_items:
        text = str(item.get("text") or item.get("label") or "")
        item_terms = _final_submit_terms_in_text(text)
        if not item_terms:
            continue
        if _is_search_submit(item, text):
            continue
        if _is_negative_or_instructional_submit_text(text):
            continue
        if not _is_final_submit_action_like(item, text):
            continue
        matched_terms.extend(item_terms)
        matched_items.append(
            {
                "collection": item.get("collection"),
                "id": item.get("id"),
                "text": text,
                "role": item.get("role"),
                "bbox": item.get("bbox"),
                "matched_terms": item_terms,
            }
        )
    return {
        "contract_version": FINAL_SUBMIT_SCOPE_CONTRACT,
        "enabled": True,
        "active_flow_started": bool(active_flow_started),
        "active_container": active_container or None,
        "blocked": bool(matched_items),
        "matched_terms": sorted(set(matched_terms)),
        "matched_items": matched_items[:20],
        "reason": "final_submit_visible_stop_before_submission" if matched_items else "no_scoped_final_submit_visible",
    }


def _item_in_active_scope(
    item: dict[str, Any],
    *,
    active_container: dict[str, Any] | None,
    active_flow_started: bool,
) -> bool:
    if not active_flow_started:
        return False
    if not active_container:
        return True
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else None
    if not bbox:
        return False
    return _center_inside(bbox, active_container)


def _final_submit_terms_in_text(text: str) -> list[str]:
    key = text.casefold()
    matched: list[str] = []
    for term in FINAL_SUBMIT_TERMS:
        pattern = r"(?<![a-z0-9])" + re.escape(term.casefold()) + r"(?![a-z0-9])"
        if re.search(pattern, key):
            matched.append(term)
    return matched


def _is_search_submit(item: dict[str, Any], text: str) -> bool:
    key = " ".join([str(text or ""), str(item.get("id") or ""), str(item.get("role") or "")]).casefold()
    return "submit search" in key or "search" in key and _clean_text(text).casefold() in {"submit", "submit search"}


def _is_negative_or_instructional_submit_text(text: str) -> bool:
    key = text.casefold()
    return any(
        marker in key
        for marker in (
            "do not",
            "don't",
            "never",
            "must not",
            "should not",
            "not click",
            "forbidden",
            "禁止",
            "不要",
            "不能",
            "不允许",
        )
    )


def _is_final_submit_action_like(item: dict[str, Any], text: str) -> bool:
    role = str(item.get("role") or "").casefold()
    collection = str(item.get("collection") or "").casefold()
    if collection == "available_actions":
        return True
    if any(token in role for token in ("button", "link", "action", "menuitem", "submit")):
        return True
    normalized = _clean_text(text)
    return len(normalized) <= 40 and len(normalized.split()) <= 5


def _center_inside(bbox: dict[str, Any], container: dict[str, Any]) -> bool:
    try:
        x = float(bbox.get("x"))
        y = float(bbox.get("y"))
        w = float(bbox.get("w") if bbox.get("w") is not None else bbox.get("width"))
        h = float(bbox.get("h") if bbox.get("h") is not None else bbox.get("height"))
        cx = x + w / 2
        cy = y + h / 2
        bx = float(container.get("x"))
        by = float(container.get("y"))
        bw = float(container.get("w") if container.get("w") is not None else container.get("width"))
        bh = float(container.get("h") if container.get("h") is not None else container.get("height"))
    except (TypeError, ValueError):
        return False
    return bx <= cx <= bx + bw and by <= cy <= by + bh


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())
