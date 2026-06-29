from __future__ import annotations

import hashlib
import re
from typing import Any

from app.gate.candidates import build_candidate_freshness
from app.operation.screen_inventory import build_screen_inventory
from app.seek.scroll_containers import SEEK_JOB_DETAIL, SEEK_RESULTS_LIST, discover_seek_scroll_containers, get_scroll_container


def extract_seek_job_cards(source: dict[str, Any] | None, *, goal: str | None = None) -> dict[str, Any]:
    """Extract visible SEEK job cards from a screen inventory or screen reading payload."""

    inventory = _inventory(source, goal=goal)
    size = _inventory_size(source)
    capture_id = _capture_id(source)
    actions = {item.get("id"): item for item in _items(inventory.get("available_actions"))}
    page_elements = {item.get("id"): item for item in _items(inventory.get("page_elements"))}
    evidence_results_bbox = infer_results_list_bbox_from_inventory(inventory, window_size=size)
    containers = discover_seek_scroll_containers(
        window_size=size,
        app_name="seek",
        evidence={"results_list_bbox": evidence_results_bbox} if evidence_results_bbox else None,
    )
    results_container = get_scroll_container(containers, SEEK_RESULTS_LIST)
    results_bbox = _bbox((results_container or {}).get("bbox"))
    jobs: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()
    for card in _items(inventory.get("cards")):
        label = _clean_text(card.get("label"))
        card_bbox = _bbox(card.get("bbox"))
        if not label or _looks_like_filter_card(label) or _looks_like_non_job_card(card, window_size=size):
            continue
        if results_bbox is not None and not _inside(card.get("bbox"), results_bbox):
            continue
        if results_bbox is not None and card_bbox is not None and card_bbox["y"] < results_bbox["y"]:
            continue
        child_actions = [actions[item_id] for item_id in card.get("child_action_ids") or [] if item_id in actions]
        child_pages = [page_elements[item_id] for item_id in card.get("child_page_element_ids") or [] if item_id in page_elements]
        primary_action = actions.get(card.get("primary_action_id"))
        if card.get("primary_action_id") and primary_action is None:
            continue
        primary_action_items = [primary_action] if isinstance(primary_action, dict) else []
        evidence_items = primary_action_items + child_pages + [item for item in child_actions if item not in primary_action_items]
        evidence_texts = [_clean_text(item.get("text") or item.get("label")) for item in evidence_items]
        evidence_texts = [item for item in evidence_texts if item]
        if _looks_like_seek_detail_body_card(label=label, evidence_texts=evidence_texts):
            continue
        generic_label = _looks_like_generic_job_label(label)
        title = _card_title(label, evidence_texts)
        if not title:
            continue
        evidence_items, evidence_texts = _truncate_job_card_evidence_items(title=title, items=evidence_items)
        if not evidence_texts:
            continue
        title, evidence_texts = _merge_split_job_title(title, evidence_texts)
        if _card_label_conflicts_with_child_title(
            label=label,
            title=title,
            evidence_texts=evidence_texts,
            generic_label=generic_label,
        ):
            continue
        if _title_needs_continuation(title):
            continue
        title_index = evidence_texts.index(title) if title in evidence_texts else -1
        company_candidates = (
            evidence_texts[title_index + 1 :]
            if generic_label and title_index >= 0
            else [text for text in evidence_texts if text != title]
        )
        company = _first_company(company_candidates, title=title)
        if not company and generic_label:
            company = _first_company([text for text in evidence_texts if text != title], title=title)
        location = _first_location(evidence_texts, company=company)
        if not _has_job_card_identity(title=title, company=company, location=location, evidence_texts=evidence_texts):
            continue
        if _looks_like_incomplete_duplicate(title=title, company=company, location=location, seen_jobs=seen_jobs):
            continue
        job_key = _job_key(title=title, company=company, location=location, bbox=card_bbox)
        if job_key in seen_jobs:
            continue
        seen_jobs.add(job_key)
        constrained_card_bbox = _constrain_job_card_bbox(card_bbox=card_bbox, evidence_items=evidence_items, title=title)
        card_bbox_was_constrained = constrained_card_bbox is not None and constrained_card_bbox != card_bbox
        job = {
            "contract_version": "seek_job_card_v1",
            "job_id": _job_id(label=title, company=company, location=location),
            "title": title,
            "company": company,
            "location": location,
            "posted_at_text": _first_by_hint(child_pages, "posted"),
            "work_type": _first_work_type(evidence_texts),
            "salary_text": _first_by_hint(child_pages, "salary") or _first_salary(evidence_texts),
            "classification": _first_classification(evidence_texts),
            "card_bbox": constrained_card_bbox or card_bbox,
            "click_point": _job_card_click_point(
                title=title,
                evidence_items=evidence_items,
                fallback=(primary_action or {}).get("click_point"),
                prefer_title_center=card_bbox_was_constrained,
            ),
            "source_url": _first_url(evidence_texts),
            "source_card_id": card.get("id"),
            "candidate_freshness": build_candidate_freshness(
                capture_id=capture_id,
                viewport_size=size,
                source="seek_job_card_extraction",
            ),
            "primary_action_id": card.get("primary_action_id"),
            "child_action_ids": [str(item.get("id")) for item in evidence_items if item.get("id") in {child.get("id") for child in child_actions}],
            "child_page_element_ids": [str(item.get("id")) for item in evidence_items if item.get("id") in {child.get("id") for child in child_pages}],
            "evidence": {
                "texts": evidence_texts,
                "source_contract": inventory.get("contract_version"),
            },
        }
        jobs.append(job)
    for job in _synthetic_jobs_from_page_elements(page_elements, results_bbox):
        if not isinstance(job.get("candidate_freshness"), dict):
            job["candidate_freshness"] = build_candidate_freshness(
                capture_id=capture_id,
                viewport_size=size,
                source="seek_job_card_extraction",
            )
        for existing_index in reversed(
            [
                index
                for index, existing in enumerate(jobs)
                if _is_less_complete_same_title_job(existing=existing, replacement=job)
            ]
        ):
            existing = jobs.pop(existing_index)
            seen_jobs.discard(
                _job_key(
                    title=existing.get("title"),
                    company=existing.get("company"),
                    location=existing.get("location"),
                    bbox=existing.get("card_bbox"),
                )
            )
        job_key = _job_key(
            title=job.get("title"),
            company=job.get("company"),
            location=job.get("location"),
            bbox=job.get("card_bbox"),
        )
        if _looks_like_incomplete_duplicate(
            title=job.get("title"),
            company=job.get("company"),
            location=job.get("location"),
            seen_jobs=seen_jobs,
        ):
            continue
        if job_key in seen_jobs:
            replacement_index = next(
                (
                    index
                    for index, existing in enumerate(jobs)
                    if _job_key(
                        title=existing.get("title"),
                        company=existing.get("company"),
                        location=existing.get("location"),
                        bbox=existing.get("card_bbox"),
                    )
                    == job_key
                    and _same_overlapping_job_candidate(existing, job)
                    and _job_candidate_quality(job) > _job_candidate_quality(existing)
                ),
                None,
            )
            if replacement_index is not None:
                jobs[replacement_index] = job
            continue
        seen_jobs.add(job_key)
        jobs.append(job)
    jobs = sorted(_dedupe_overlapping_job_candidates(jobs), key=_job_visual_order_key)
    return {
        "contract_version": "seek_job_cards_v1",
        "source_contract": inventory.get("contract_version"),
        "image_size": size,
        "results_list_container": results_container,
        "results_list_bbox_source": (results_container or {}).get("sources"),
        "jobs": jobs,
        "summary": {"jobs_seen": len(jobs)},
    }


def extract_seek_job_detail(
    source: dict[str, Any] | None,
    *,
    scroll_containers: dict[str, Any] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Extract a SEEK right-pane job-detail skeleton from visible inventory evidence."""

    inventory = _inventory(source, goal=goal)
    size = _inventory_size(source)
    capture_id = _capture_id(source)
    containers = scroll_containers or discover_seek_scroll_containers(window_size=size, app_name="seek")
    detail_container = get_scroll_container(containers, SEEK_JOB_DETAIL)
    if scroll_containers is None:
        drawer_bbox = _infer_seek_detail_drawer_bbox(inventory, window_size=size)
        if drawer_bbox is not None:
            detail_container = {
                **(detail_container or {}),
                "container_id": SEEK_JOB_DETAIL,
                "bbox": drawer_bbox,
                "sources": ["seek_detail_drawer_anchor_bbox"],
                "safe_points": [
                    {
                        "x": drawer_bbox["x"] + drawer_bbox["w"] // 2,
                        "y": drawer_bbox["y"] + drawer_bbox["h"] // 2,
                        "reason": "inside_seek_detail_drawer_body",
                    }
                ],
                "evidence": {
                    **((detail_container or {}).get("evidence") if isinstance((detail_container or {}).get("evidence"), dict) else {}),
                    "layout": "right_detail_drawer",
                    "source": "seek_detail_drawer_anchor_bbox",
                },
            }
    detail_bbox = _bbox((detail_container or {}).get("bbox"))
    detail_read_bbox = _expand_bbox_up(detail_bbox, pixels=220)
    detail_header_bbox = _expand_seek_detail_header_bbox(detail_bbox)
    header_actions = [item for item in _items(inventory.get("available_actions")) if _inside_detail_bbox(item.get("bbox"), detail_header_bbox)]
    header_page_elements = [item for item in _items(inventory.get("page_elements")) if _inside_detail_bbox(item.get("bbox"), detail_header_bbox)]
    actions = [item for item in _items(inventory.get("available_actions")) if _inside_detail_bbox(item.get("bbox"), detail_read_bbox)]
    page_elements = [item for item in _items(inventory.get("page_elements")) if _inside_detail_bbox(item.get("bbox"), detail_read_bbox)]
    texts = [_clean_text(item.get("text") or item.get("label")) for item in page_elements]
    texts = [item for item in texts if item]
    header_texts = [_clean_text(item.get("text") or item.get("label")) for item in header_page_elements]
    header_texts = [item for item in header_texts if item]
    texts = _trim_seek_detail_texts(texts)
    header_texts = _trim_seek_detail_texts(header_texts)
    header_scope_texts = header_texts or texts
    title = _first_job_title(header_scope_texts) or _first_heading(header_scope_texts)
    title_index = _first_same_title_index(header_scope_texts, title)
    company_candidates = _detail_header_company_candidates(header_scope_texts, title_index)
    company = _first_company(company_candidates, title=title)
    detail_after_title = header_scope_texts[title_index + 1 :] if title_index >= 0 else header_scope_texts
    location = _first_location(detail_after_title, company=company)
    scoped_actions = _prefer_header_items(header_actions, actions)
    scoped_page_elements = _prefer_header_items(header_page_elements, page_elements)
    apply_action = _first_text_button(scoped_page_elements, {"apply", "quick apply"}) or _first_action(scoped_actions, {"apply", "quick apply"})
    save_action = _first_action(scoped_actions, {"save", "save job"})
    requirements = [text for text in texts if _contains_any(text, {"requirement", "requirements", "must have", "skills", "experience"})]
    responsibilities = [text for text in texts if _contains_any(text, {"responsibil", "about the role", "you will", "role"})]
    benefits = [text for text in texts if _contains_any(text, {"benefit", "parking", "insurance", "flexible", "remote", "hybrid"})]
    return {
        "contract_version": "seek_job_detail_v1",
        "job_id": _job_id(label=title, company=company, location=location),
        "title": title,
        "company": company,
        "location": location,
        "work_type": _first_work_type(texts),
        "classification": _first_classification(texts),
        "salary_text": _first_salary(texts),
        "description_sections": _detail_sections(texts),
        "requirements": requirements,
        "responsibilities": responsibilities,
        "benefits": benefits,
        "apply_button_state": {
            "visible": apply_action is not None,
            "label": (apply_action or {}).get("label"),
            "bbox": _bbox((apply_action or {}).get("bbox")),
            "click_point": (apply_action or {}).get("click_point"),
            "candidate_freshness": build_candidate_freshness(
                capture_id=capture_id,
                viewport_size=size,
                source="seek_apply_button_extraction",
            )
            if apply_action is not None
            else None,
        },
        "save_button_state": {
            "visible": save_action is not None,
            "label": (save_action or {}).get("label"),
            "bbox": _bbox((save_action or {}).get("bbox")),
        },
        "detail_container": detail_container,
        "detail_read_bbox": detail_read_bbox,
        "detail_bottom_reached": bool((source or {}).get("detail_bottom_reached")) or _seek_detail_texts_show_bottom(texts),
        "detail_scroll_history": [],
        "trace_paths": [],
        "evidence": {
            "text_count": len(texts),
            "action_count": len(actions),
            "texts": texts,
            "source_contract": inventory.get("contract_version"),
        },
    }


def _inventory(source: dict[str, Any] | None, *, goal: str | None = None) -> dict[str, Any]:
    payload = source if isinstance(source, dict) else {}
    if payload.get("contract_version") == "screen_inventory_v1":
        return payload
    if isinstance(payload.get("screen_inventory"), dict):
        return payload["screen_inventory"]
    return build_screen_inventory(payload, goal=goal)


def _prefer_header_items(header_items: list[dict[str, Any]], all_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in header_items + all_items:
        item_id = str(item.get("id") or "")
        key = item_id or repr(item.get("bbox"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _detail_header_company_candidates(texts: list[str], title_index: int) -> list[str]:
    if title_index < 0:
        return texts
    for text in texts[title_index + 1 :]:
        normalized = _normalized(text)
        if _is_detail_header_action_text(normalized):
            continue
        if _looks_like_bullet_body_line(text):
            break
        if _is_detail_company_boundary(normalized) or _looks_like_detail_body_start(text):
            break
        return [text]
    return []


def _first_same_title_index(texts: list[str], title: str | None) -> int:
    if not title:
        return -1
    for index, text in enumerate(texts):
        if _same_title(text, title):
            return index
    return -1


def _is_detail_header_action_text(normalized_text: str) -> bool:
    return normalized_text in {"apply", "quick apply", "quick apply button", "save", "save button", "save job", "save job button"}


def _is_detail_company_boundary(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    return _contains_any(
        normalized_text,
        {
            "posted",
            "application volume",
            "fulltime",
            "how you match",
            "skill",
            "credential",
            "show all",
            "our why",
            "about the role",
            "responsibilities",
            "requirements",
            "benefits",
        },
    )


def _looks_like_detail_body_start(text: str) -> bool:
    normalized = _normalized(text)
    if _looks_like_bullet_body_line(text):
        return True
    if normalized in {"ourwhy", "our why", "what you ll bring", "what youll bring", "required experience", "nice to have", "requirements", "benefits"}:
        return True
    return normalized.startswith(
        (
            "about the role",
            "at the moment",
            "bachelor",
            "additional certification",
            "datacom is ",
            "we are ",
            "you ll ",
            "youll ",
            "spaces ",
            "spaces,",
            "to work",
            "work in ",
            "will never",
            "we want ",
            "your application will include",
        )
    )


def _inventory_size(source: dict[str, Any] | None) -> dict[str, int]:
    payload = source if isinstance(source, dict) else {}
    image_size = payload.get("image_size") if isinstance(payload.get("image_size"), dict) else {}
    width = int(image_size.get("width") or payload.get("image_width") or 1246)
    height = int(image_size.get("height") or payload.get("image_height") or 1194)
    return {"width": width, "height": height}


def _capture_id(source: dict[str, Any] | None) -> str | None:
    payload = source if isinstance(source, dict) else {}
    return payload.get("capture_id") or payload.get("trace_path") or payload.get("image_path")


def _infer_seek_detail_drawer_bbox(
    inventory: dict[str, Any] | None,
    *,
    window_size: dict[str, int],
) -> dict[str, int] | None:
    width = int(window_size.get("width") or 0)
    height = int(window_size.get("height") or 0)
    if width < 1800 or height < 700:
        return None
    anchors: list[dict[str, int]] = []
    min_anchor_x = int(width * 0.55)
    for item in [*_items((inventory or {}).get("available_actions")), *_items((inventory or {}).get("page_elements"))]:
        bbox = _bbox(item.get("bbox"))
        if bbox is None or bbox["x"] < min_anchor_x:
            continue
        text = _clean_text(item.get("label") or item.get("text"))
        normalized = _normalized(text)
        if not normalized:
            continue
        if normalized.startswith("apply for ") or normalized in {"quick apply", "quick apply button"}:
            anchors.append(bbox)
            continue
        if normalized == "how you match" or "skills and credentials match your profile" in normalized:
            anchors.append(bbox)
            continue
        if "application volume" in normalized or "view all jobs" in normalized:
            anchors.append(bbox)
    if not anchors:
        return None
    left = max(int(width * 0.62), min(anchor["x"] for anchor in anchors) - 80)
    top = max(80, min(anchor["y"] for anchor in anchors) - 220)
    right = width - 16
    if right - left < 360:
        right = min(width - 16, left + max(600, width - left - 16))
    bottom = height - 16
    if bottom <= top + 220:
        return None
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def infer_results_list_bbox_from_inventory(
    inventory: dict[str, Any] | None,
    *,
    window_size: dict[str, int] | None = None,
) -> dict[str, int] | None:
    payload = inventory if isinstance(inventory, dict) else {}
    size = window_size if isinstance(window_size, dict) else {}
    candidates: list[dict[str, int]] = []
    actions = {item.get("id"): item for item in _items(payload.get("available_actions"))}
    page_elements = {item.get("id"): item for item in _items(payload.get("page_elements"))}
    for card in _items(payload.get("cards")):
        label = _clean_text(card.get("label"))
        card_bbox = _bbox(card.get("bbox"))
        if not label or _looks_like_filter_card(label) or _looks_like_non_job_card(card, window_size=size):
            continue
        if card_bbox is None:
            continue
        child_actions = [actions[item_id] for item_id in card.get("child_action_ids") or [] if item_id in actions]
        child_pages = [page_elements[item_id] for item_id in card.get("child_page_element_ids") or [] if item_id in page_elements]
        primary_action = actions.get(card.get("primary_action_id"))
        if card.get("primary_action_id") and primary_action is None:
            continue
        texts = [_clean_text(item.get("text") or item.get("label")) for item in child_pages + child_actions]
        texts = [item for item in texts if item]
        title = _card_title(label, texts)
        if not title or _title_needs_continuation(title):
            continue
        company_candidates = texts[texts.index(title) + 1 :] if title in texts else [text for text in texts if text != title]
        company = _first_company(company_candidates, title=title)
        location = _first_location(texts, company=company)
        if not _has_job_card_identity(title=title, company=company, location=location, evidence_texts=texts):
            continue
        if card_bbox["w"] < 240 or card_bbox["h"] < 80:
            continue
        candidate_boxes = [card_bbox]
        for child in child_pages + child_actions:
            child_bbox = _bbox(child.get("bbox"))
            if child_bbox is not None and _is_bounded_child_bbox(child_bbox, card_bbox):
                candidate_boxes.append(child_bbox)
        candidates.append(_union_bboxes(candidate_boxes) or card_bbox)
    if not candidates:
        return None
    candidates = _dominant_results_list_column_boxes(candidates, window_size=size)
    union = _union_bboxes(candidates)
    if union is None:
        return None
    synthetic_column_boxes = _likely_results_column_text_boxes(page_elements, base_bbox=union, window_size=size)
    if synthetic_column_boxes:
        union = _union_bboxes([union, *synthetic_column_boxes]) or union
    width = int(size.get("width") or 0)
    height = int(size.get("height") or 0)
    pad_x = 18
    pad_top = 28
    pad_bottom = 80
    x = max(0, union["x"] - pad_x)
    y = max(0, union["y"] - pad_top)
    right_limit = width if width > 0 else union["x"] + union["w"] + pad_x
    bottom_limit = height if height > 0 else union["y"] + union["h"] + pad_bottom
    right = min(right_limit, union["x"] + union["w"] + pad_x)
    bottom = min(bottom_limit, max(union["y"] + union["h"] + pad_bottom, y + union["h"]))
    return {"x": x, "y": y, "w": max(1, right - x), "h": max(120, bottom - y)}


def _dominant_results_list_column_boxes(
    candidates: list[dict[str, int]],
    *,
    window_size: dict[str, int],
) -> list[dict[str, int]]:
    if len(candidates) <= 1:
        return candidates
    left_edge = min(box["x"] for box in candidates)
    width = int(window_size.get("width") or 0)
    left_column = [
        box
        for box in candidates
        if box["x"] <= left_edge + 160
        and (width <= 0 or box["x"] + box["w"] / 2 <= max(left_edge + 700, width * 0.46))
    ]
    return left_column or candidates


def _likely_results_column_text_boxes(
    page_elements: dict[Any, dict[str, Any]],
    *,
    base_bbox: dict[str, int],
    window_size: dict[str, int],
) -> list[dict[str, int]]:
    width = int(window_size.get("width") or 0)
    height = int(window_size.get("height") or 0)
    right_limit = width if width > 0 else base_bbox["x"] + base_bbox["w"] + 120
    bottom_limit = max(0, height - 80) if height > 0 else base_bbox["y"] + 1200
    column_left = max(0, base_bbox["x"] - 90)
    column_right = min(right_limit, base_bbox["x"] + base_bbox["w"] + 90)
    elements = [
        item
        for item in page_elements.values()
        if isinstance(item, dict)
        and (bbox := _bbox(item.get("bbox"))) is not None
        and column_left <= bbox["x"] + bbox["w"] / 2 <= column_right
        and base_bbox["y"] - 40 <= bbox["y"] <= bottom_limit
        and _clean_text(item.get("text") or item.get("label"))
    ]
    elements.sort(key=lambda item: (_bbox(item.get("bbox")) or {"y": 0, "x": 0})["y"])
    boxes: list[dict[str, int]] = []
    for index, item in enumerate(elements):
        text = _clean_text(item.get("text") or item.get("label"))
        title = _first_job_title([text])
        title_bbox = _bbox(item.get("bbox"))
        if not title or title_bbox is None:
            continue
        nearby_boxes = [title_bbox]
        for other in elements[index + 1 :]:
            other_bbox = _bbox(other.get("bbox"))
            if other_bbox is None:
                continue
            other_text = _clean_text(other.get("text") or other.get("label"))
            if other_bbox["y"] <= title_bbox["y"]:
                continue
            if other_bbox["y"] - title_bbox["y"] > 230:
                break
            if other_bbox["y"] - title_bbox["y"] > 45 and _first_job_title([other_text]):
                break
            if abs(other_bbox["x"] - title_bbox["x"]) > 110 and other_bbox["x"] > title_bbox["x"] + 300:
                continue
            nearby_boxes.append(other_bbox)
        if len(nearby_boxes) >= 2:
            boxes.extend(nearby_boxes)
    return boxes


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    width = value.get("w", value.get("width"))
    height = value.get("h", value.get("height"))
    try:
        return {
            "x": int(float(value.get("x") or 0)),
            "y": int(float(value.get("y") or 0)),
            "w": max(0, int(float(width or 0))),
            "h": max(0, int(float(height or 0))),
        }
    except (TypeError, ValueError):
        return None


def _inside(child: Any, container: dict[str, int] | None) -> bool:
    child_bbox = _bbox(child)
    if child_bbox is None or container is None:
        return False
    cx = child_bbox["x"] + child_bbox["w"] / 2
    cy = child_bbox["y"] + child_bbox["h"] / 2
    return container["x"] <= cx <= container["x"] + container["w"] and container["y"] <= cy <= container["y"] + container["h"]


def _inside_detail_bbox(child: Any, container: dict[str, int] | None) -> bool:
    child_bbox = _bbox(child)
    if child_bbox is None or container is None:
        return False
    if child_bbox["x"] < container["x"] - 16:
        return False
    return _inside(child_bbox, container)


def _is_bounded_child_bbox(child_bbox: dict[str, int], parent_bbox: dict[str, int]) -> bool:
    if not _inside(child_bbox, parent_bbox):
        return False
    pad = 36
    if child_bbox["w"] > parent_bbox["w"] + pad or child_bbox["h"] > parent_bbox["h"] + pad:
        return False
    if child_bbox["x"] < parent_bbox["x"] - pad:
        return False
    if child_bbox["y"] < parent_bbox["y"] - pad:
        return False
    if child_bbox["x"] + child_bbox["w"] > parent_bbox["x"] + parent_bbox["w"] + pad:
        return False
    if child_bbox["y"] + child_bbox["h"] > parent_bbox["y"] + parent_bbox["h"] + pad:
        return False
    return True


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _contains_any(value: str, terms: set[str]) -> bool:
    normalized = _normalized(value)
    return any(term in normalized for term in terms)


_SEEK_DETAIL_TRAILING_RECOMMENDATION_MARKERS = {
    "featured jobs",
    "similar jobs",
    "recommended jobs",
    "more jobs like this",
}


def _trim_seek_detail_texts(texts: list[str]) -> list[str]:
    """Keep the current job detail body and drop the trailing recommendation feed."""

    for index, text in enumerate(texts):
        if index <= 0:
            continue
        if _contains_any(text, _SEEK_DETAIL_TRAILING_RECOMMENDATION_MARKERS):
            return texts[:index]
    return texts


def _seek_detail_texts_show_bottom(texts: list[str]) -> bool:
    normalized = [_normalized(text) for text in texts if _normalized(text)]
    joined = " | ".join(normalized)
    if "report this job ad" in joined:
        return True
    if "be careful" in joined and "protect yourself" in joined:
        return True
    if "see more detailed salary information" in joined:
        return True
    return False


def _first_by_hint(items: list[dict[str, Any]], hint: str) -> str | None:
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("semantic_hint") == hint:
            text = _clean_text(item.get("text") or item.get("label"))
            if text:
                return text
    return None


def _synthetic_jobs_from_page_elements(
    page_elements: dict[str, dict[str, Any]],
    results_bbox: dict[str, int] | None,
) -> list[dict[str, Any]]:
    if results_bbox is None:
        return []
    elements = [
        item
        for item in page_elements.values()
        if _inside(item.get("bbox"), results_bbox) and _clean_text(item.get("text") or item.get("label"))
    ]
    elements.sort(key=lambda item: (_bbox(item.get("bbox")) or {"y": 0, "x": 0})["y"])
    jobs: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        title = _first_job_title([_clean_text(element.get("text") or element.get("label"))])
        title_bbox = _bbox(element.get("bbox"))
        if not title or title_bbox is None:
            continue
        nearby: list[dict[str, Any]] = [element]
        title_top = title_bbox["y"]
        title_left = title_bbox["x"]
        for other in elements[index + 1 :]:
            other_bbox = _bbox(other.get("bbox"))
            if other_bbox is None:
                continue
            other_text = _clean_text(other.get("text") or other.get("label"))
            if other_bbox["y"] <= title_top:
                continue
            if _looks_like_filter_card(other_text):
                continue
            if other_bbox["y"] - title_top > 230:
                break
            if other_bbox["y"] - title_top > 45 and _first_job_title([other_text]):
                break
            if abs(other_bbox["x"] - title_left) > 80 and other_bbox["x"] > title_left + 260:
                continue
            nearby.append(other)
        texts = [_clean_text(item.get("text") or item.get("label")) for item in nearby]
        texts = [text for text in texts if text]
        title, texts = _merge_split_job_title(title, texts)
        if _synthetic_title_low_confidence(title):
            continue
        nearby, texts = _truncate_job_card_evidence_items(title=title, items=nearby)
        if not texts:
            continue
        company = _first_company([text for text in texts[1:] if text != title], title=title)
        location = _first_location(texts, company=company)
        if not _has_synthetic_job_card_anchor(texts=texts, company=company, location=location):
            continue
        card_bbox = _union_bboxes([_bbox(item.get("bbox")) for item in nearby])
        if card_bbox is not None and card_bbox["w"] > min(results_bbox["w"] + 40, 560):
            continue
        jobs.append(
            {
                "contract_version": "seek_job_card_v1",
                "job_id": _job_id(label=title, company=company, location=location),
                "title": title,
                "company": company,
                "location": location,
                "posted_at_text": next((text for text in texts if _contains_any(text, {"posted"})), None),
                "work_type": _first_work_type(texts),
                "salary_text": _first_salary(texts),
                "classification": _first_classification(texts),
                "card_bbox": card_bbox,
                "click_point": {"x": title_bbox["x"] + title_bbox["w"] // 2, "y": title_bbox["y"] + title_bbox["h"] // 2},
                "source_url": _first_url(texts),
                "source_card_id": f"synthetic_results_text_{index}",
                "primary_action_id": None,
                "child_action_ids": [],
                "child_page_element_ids": [str(item.get("id")) for item in nearby if item.get("id")],
                "evidence": {
                    "texts": texts,
                    "source_contract": "screen_inventory_v1",
                    "synthetic_from": "results_list_page_elements",
                    "synthetic_validation": {
                        "has_location": location is not None,
                        "has_company": company is not None,
                        "has_posted_at": any(_contains_any(text, {"posted"}) for text in texts),
                        "has_work_type": _first_work_type(texts) is not None,
                        "has_salary": _first_salary(texts) is not None,
                    },
                },
            }
        )
    return jobs


def _union_bboxes(values: list[dict[str, int] | None]) -> dict[str, int] | None:
    boxes = [value for value in values if value is not None]
    if not boxes:
        return None
    min_x = min(box["x"] for box in boxes)
    min_y = min(box["y"] for box in boxes)
    max_x = max(box["x"] + box["w"] for box in boxes)
    max_y = max(box["y"] + box["h"] for box in boxes)
    return {"x": min_x, "y": min_y, "w": max_x - min_x, "h": max_y - min_y}


def _truncate_job_card_evidence_items(*, title: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    title_key = _normalized(title)
    if not title_key:
        return [], []
    kept: list[dict[str, Any]] = []
    seen_title = False
    for item in items:
        text = _clean_text(item.get("text") or item.get("label"))
        if not text:
            continue
        text_key = _normalized(text)
        candidate_title = _first_job_title([text])
        if seen_title and candidate_title and not _same_title(candidate_title, title):
            break
        if seen_title and text_key in {"featured", "this is a featured job"}:
            kept.append(item)
            break
        if not seen_title:
            if text_key == title_key or _same_title(text, title):
                seen_title = True
            elif kept:
                continue
        kept.append(item)
    if not seen_title:
        kept = [item for item in items if _clean_text(item.get("text") or item.get("label"))]
    texts = [_clean_text(item.get("text") or item.get("label")) for item in kept]
    return kept, [text for text in texts if text]


def _constrain_job_card_bbox(
    *,
    card_bbox: dict[str, int] | None,
    evidence_items: list[dict[str, Any]],
    title: str,
) -> dict[str, int] | None:
    geometry_items = _job_card_geometry_items(title=title, items=evidence_items)
    evidence_bbox = _union_bboxes([_bbox(item.get("bbox")) for item in geometry_items])
    if evidence_bbox is None:
        return card_bbox
    if card_bbox is None:
        return evidence_bbox
    title_bbox = _title_item_bbox(title=title, items=geometry_items)
    has_generic_polluter = any(
        _looks_like_generic_job_label(_clean_text(item.get("text") or item.get("label")))
        and not _same_title(_clean_text(item.get("text") or item.get("label")), title)
        and _bbox(item.get("bbox")) is not None
        for item in evidence_items
    )
    too_tall = card_bbox["h"] > max(360, evidence_bbox["h"] + 140)
    too_wide = card_bbox["w"] > max(560, evidence_bbox["w"] + 180)
    if too_tall or too_wide or has_generic_polluter:
        if title_bbox is not None:
            top = min(title_bbox["y"], evidence_bbox["y"])
            bottom = max(evidence_bbox["y"] + evidence_bbox["h"], title_bbox["y"] + title_bbox["h"])
            left = min(title_bbox["x"], evidence_bbox["x"])
            right = max(evidence_bbox["x"] + evidence_bbox["w"], title_bbox["x"] + title_bbox["w"])
            return {"x": left, "y": top, "w": right - left, "h": bottom - top}
        return evidence_bbox
    return card_bbox


def _job_card_click_point(
    *,
    title: str,
    evidence_items: list[dict[str, Any]],
    fallback: Any,
    prefer_title_center: bool = False,
) -> Any:
    if not prefer_title_center and fallback:
        return fallback
    title_bbox = _title_item_bbox(title=title, items=evidence_items)
    if title_bbox is None:
        return fallback
    return {"x": title_bbox["x"] + title_bbox["w"] // 2, "y": title_bbox["y"] + title_bbox["h"] // 2}


def _title_item_bbox(*, title: str, items: list[dict[str, Any]]) -> dict[str, int] | None:
    for item in items:
        text = _clean_text(item.get("text") or item.get("label"))
        if _same_title(text, title):
            return _bbox(item.get("bbox"))
    return None


def _job_card_geometry_items(*, title: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if _bbox(item.get("bbox")) is None:
            continue
        text = _clean_text(item.get("text") or item.get("label"))
        if not text:
            continue
        if _looks_like_generic_job_label(text) and not _same_title(text, title):
            continue
        filtered.append(item)
    return filtered or [item for item in items if _bbox(item.get("bbox")) is not None]


def _dedupe_overlapping_job_candidates(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    for job in jobs:
        replacement_index = None
        for index, existing in enumerate(deduped):
            if not _same_overlapping_job_candidate(existing, job):
                continue
            if _job_candidate_quality(job) > _job_candidate_quality(existing):
                replacement_index = index
            else:
                replacement_index = -1
            break
        if replacement_index is None:
            deduped.append(job)
        elif replacement_index >= 0:
            deduped[replacement_index] = job
    return deduped


def _same_overlapping_job_candidate(a: dict[str, Any], b: dict[str, Any]) -> bool:
    company_a = _normalized(a.get("company"))
    company_b = _normalized(b.get("company"))
    location_a = _normalized(a.get("location"))
    location_b = _normalized(b.get("location"))
    if not company_a or company_a != company_b or not location_a or location_a != location_b:
        return False
    return _bbox_overlap_ratio(_bbox(a.get("card_bbox")), _bbox(b.get("card_bbox"))) >= 0.55


def _bbox_overlap_ratio(a: dict[str, int] | None, b: dict[str, int] | None) -> float:
    if a is None or b is None:
        return 0.0
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["w"], b["x"] + b["w"])
    bottom = min(a["y"] + a["h"], b["y"] + b["h"])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    min_area = max(1, min(a["w"] * a["h"], b["w"] * b["h"]))
    return intersection / min_area


def _job_candidate_quality(job: dict[str, Any]) -> int:
    title = _clean_text(job.get("title"))
    evidence_texts = [_clean_text(text) for text in (job.get("evidence") or {}).get("texts", []) if _clean_text(text)]
    score = 0
    if job.get("location"):
        score += 4
    if job.get("company"):
        score += 2
    primary_action_id = str(job.get("primary_action_id") or "")
    source_card_id = str(job.get("source_card_id") or "")
    if primary_action_id.startswith("action_uia"):
        score += 5
    elif primary_action_id.startswith("action_screen"):
        score += 2
    if source_card_id.startswith("synthetic_results_text"):
        score += 4
    if title in evidence_texts:
        score += 2
    if len(title.split()) >= 3:
        score += 1
    if title.rstrip().endswith(("-", "|", "/")):
        score -= 4
    if _looks_like_detail_classification(title) or _looks_like_summary_sentence(title):
        score -= 5
    return score


def _expand_bbox_up(bbox: dict[str, int] | None, *, pixels: int) -> dict[str, int] | None:
    if bbox is None:
        return None
    top = max(0, bbox["y"] - max(0, int(pixels)))
    bottom = bbox["y"] + bbox["h"]
    return {"x": bbox["x"], "y": top, "w": bbox["w"], "h": bottom - top}


def _expand_seek_detail_header_bbox(bbox: dict[str, int] | None) -> dict[str, int] | None:
    if bbox is None:
        return None
    expanded = _expand_bbox_up(bbox, pixels=180)
    if expanded is None:
        return None
    top = max(48, expanded["y"])
    bottom = expanded["y"] + expanded["h"]
    if top >= bottom:
        return bbox
    return {"x": expanded["x"], "y": top, "w": expanded["w"], "h": bottom - top}


def _first_salary(texts: list[str]) -> str | None:
    for text in texts:
        if re.search(r"\$\s*\d|\b\d+\s*k\b", text, flags=re.IGNORECASE):
            return text
    return None


def _first_location(texts: list[str], *, company: str | None = None) -> str | None:
    location_terms = {"auckland", "wellington", "christchurch", "hamilton", "tauranga", "remote", "new zealand", "nz"}
    normalized_company = _normalized(company)
    for text in texts:
        if _looks_like_url_or_noise(text) or _looks_like_summary_sentence(text):
            continue
        if _looks_like_bullet_body_line(text):
            continue
        if _looks_like_detail_body_start(text):
            continue
        normalized = _normalized(text)
        if normalized.startswith("remote option") or " option in auckland" in normalized:
            continue
        if normalized_company and normalized == normalized_company:
            continue
        if re.search(r"\b(ltd|limited|pty|p/l|inc|corp|company|group)\b", normalized):
            continue
        if len(text) <= 80 and _contains_any(text, location_terms):
            return text
    return None


def _first_work_type(texts: list[str]) -> str | None:
    for text in texts:
        if _looks_like_bullet_body_line(text):
            continue
        if _looks_like_detail_body_start(text):
            continue
        normalized = _normalized(text)
        if len(text.split()) > 5:
            continue
        if _contains_any(normalized, {"auckland", "wellington", "christchurch", "hamilton", "tauranga", "new zealand", "nz"}):
            if "hybrid" in normalized:
                return "Hybrid"
            if "remote" in normalized:
                return "Remote"
            continue
        if _contains_any(text, {"full time", "fulltime", "part time", "contract", "casual", "permanent", "hybrid", "remote"}):
            return text
    return None


def _looks_like_bullet_body_line(text: str) -> bool:
    stripped = _clean_text(text).lstrip()
    return stripped.startswith(("\u00b7", "\u2022", "- "))


def _first_classification(texts: list[str]) -> str | None:
    for text in texts:
        normalized = _normalized(text)
        if _looks_like_bullet_body_line(text) or _looks_like_summary_sentence(text):
            continue
        if normalized.startswith(
            (
                "we are ",
                "internal ",
                "at least ",
                "excellent ",
                "fxcellent ",
                "understanding of ",
                "solid understanding ",
                "knowledge of ",
                "bachelor",
                "degree",
                "additional certification",
                "certification",
            )
        ):
            continue
        if "professional services" in normalized or "we have managed" in normalized:
            continue
        if len(text.split()) > 8 and "(" not in text:
            continue
        if _contains_any(normalized, {"engineering", "information", "technology", "software", "ict"}):
            return text
    return None


def _first_url(texts: list[str]) -> str | None:
    for text in texts:
        match = re.search(r"https?://\S+", text)
        if match:
            return match.group(0)
    return None


def _first_company(texts: list[str], *, title: str | None = None) -> str | None:
    skipped = {
        "posted",
        "auckland",
        "remote",
        "full time",
        "fulltime",
        "part time",
        "contract",
        "engineering",
        "software",
        "apply",
        "save",
        "job listing",
        "climate innovations",
        "over65yearsof",
        "pay",
        "type",
        "new to you",
        "strong applicant",
        "jobs",
        "save this search",
        "background",
        "this is a featured job",
        "featured job",
        "featured",
        "image",
        "key responsibilities",
        "responsibilities",
        "requirements",
        "about the role",
        "about you",
        "benefits",
        "opportunity",
        "opportunities",
        "programming",
        "show all",
        "credential",
        "profile",
    }
    normalized_title = _normalized(title)
    candidates: list[str] = []
    for text in texts:
        text = _clean_company(text)
        normalized = _normalized(text)
        if not text or any(term in normalized for term in skipped):
            continue
        if _looks_like_seek_header_control_noise(text):
            continue
        if _looks_like_bullet_body_line(text):
            continue
        if normalized_title and (normalized in normalized_title or normalized_title in normalized):
            continue
        if _looks_like_url_or_noise(text):
            continue
        if _looks_like_summary_sentence(text):
            continue
        if _looks_like_detail_body_start(text):
            continue
        if _first_job_title([text]) == text:
            continue
        if re.search(r"\$\s*\d|\b(\d+\s*[dh]|\d+\s*(day|hour|week|month)s?)\s+ago\b|\bviewed\b", normalized):
            continue
        if len(text) <= 80:
            candidates.append(text)
    if not candidates:
        return None
    return max(candidates, key=_company_candidate_quality)


def _looks_like_seek_header_control_noise(text: str | None) -> bool:
    cleaned = _clean_text(text)
    normalized = _normalized(cleaned)
    if not normalized:
        return True
    if normalized in {"x", "×", "close", "dismiss", "share", "more", "..."}:
        return True
    if len(normalized) == 1 and normalized.isalpha():
        return True
    return False


def _company_candidate_quality(text: str) -> tuple[int, int, int]:
    normalized = _normalized(text)
    score = 0
    if re.search(r"\b(ltd|limited|pty|p/l|inc|corp|company|group)\b", normalized):
        score += 5
    if len(text.split()) >= 2:
        score += 2
    if len(text.split()) > 5:
        score -= 6
    if _contains_any(normalized, {"opportunity", "culture", "progression", "growth", "benefits", "responsibilities"}):
        score -= 4
    if text.isupper() and len(text) <= 12:
        score -= 2
    return score, min(len(text), 80), -len(normalized)


def _clean_company(text: str) -> str:
    value = _clean_text(text)
    for marker in (" View all jobs", " View alljobs"):
        if marker in value:
            value = value.split(marker, 1)[0].strip()
    return value


def _card_title(label: str, evidence_texts: list[str]) -> str | None:
    cleaned_label = _clean_text(label)
    normalized = _normalized(cleaned_label)
    if normalized.endswith(" job listing"):
        candidate = cleaned_label[: -len(" job listing")].strip()
        if _first_job_title([candidate]) == candidate:
            return candidate
    if not _looks_like_generic_job_label(cleaned_label):
        return label
    return _best_job_title(evidence_texts)


def _card_label_conflicts_with_child_title(
    *,
    label: str,
    title: str,
    evidence_texts: list[str],
    generic_label: bool,
) -> bool:
    if generic_label or not title:
        return False
    child_titles = [
        candidate
        for candidate in (_first_job_title([text]) for text in evidence_texts)
        if candidate and not _same_title(candidate, title)
    ]
    if not child_titles:
        return False
    label_key = _normalized(label)
    model_card_label = "job card" in label_key or "listing card" in label_key
    return model_card_label


def _same_title(a: str | None, b: str | None) -> bool:
    a_key = _normalized(a)
    b_key = _normalized(b)
    a_compact = re.sub(r"[^a-z0-9]+", "", str(a or "").casefold())
    b_compact = re.sub(r"[^a-z0-9]+", "", str(b or "").casefold())
    if not a_key or not b_key:
        return False
    if a_key == b_key:
        return True
    if a_compact and b_compact:
        if a_compact == b_compact:
            return True
        compact_shorter, compact_longer = sorted([a_compact, b_compact], key=len)
        if len(compact_shorter) >= 8 and compact_shorter in compact_longer:
            return True
    shorter, longer = sorted([a_key, b_key], key=len)
    return len(shorter) >= 8 and shorter in longer


def _looks_like_generic_job_label(label: str) -> bool:
    normalized = _normalized(label)
    if normalized.startswith("job listing"):
        return True
    return normalized in {
        "job listing",
        "job card",
        "job list item",
        "job title",
        "job title link",
        "job listing title",
        "job listing title link",
        "job title and company name",
        "listing",
        "seek job listing",
        "hyperlink",
    }


def _first_job_title(texts: list[str]) -> str | None:
    skipped = {"apply", "save", "view all jobs", "posted", "salary", "auckland", "full time", "part time"}
    title_terms = {
        "engineer",
        "developer",
        "analyst",
        "designer",
        "manager",
        "consultant",
        "architect",
        "administrator",
        "specialist",
        "technician",
        "tester",
        "scientist",
    }
    for text in texts:
        normalized = _normalized(text)
        if not text or any(term in normalized for term in skipped):
            continue
        if _looks_like_url_or_noise(text):
            continue
        if _looks_like_summary_sentence(text):
            continue
        if re.search(r"\b(\d+\s*[dh]|\d+\s*(day|hour|week|month)s?)\s+ago\b|\bviewed\b", normalized):
            continue
        if _looks_like_detail_classification(text):
            continue
        if len(text) <= 120 and any(term in normalized for term in title_terms):
            return _repair_job_title_spacing(text)
    return None


def _best_job_title(texts: list[str]) -> str | None:
    candidates = [candidate for text in texts for candidate in [_first_job_title([text])] if candidate]
    if not candidates:
        return None
    return max(candidates, key=_job_title_quality)


def _job_title_quality(text: str) -> tuple[int, int, int]:
    normalized = _normalized(text)
    words = [word for word in normalized.split() if word]
    role_terms = {
        "engineer",
        "developer",
        "analyst",
        "designer",
        "manager",
        "consultant",
        "architect",
        "administrator",
        "specialist",
        "technician",
        "tester",
        "scientist",
        "support",
        "application",
        "software",
        "data",
        "frontend",
        "backend",
        "platform",
    }
    role_hits = sum(1 for word in words if word in role_terms)
    return (role_hits, len(words), len(text))


def _repair_job_title_spacing(text: str) -> str:
    value = _clean_text(text)
    for term in ("Android", "Software", "Engineer", "Developer", "Analyst", "Manager", "Specialist", "Architect"):
        value = re.sub(rf"(?<=[a-z])(?={term})", " ", value)
    return value


def _merge_split_job_title(title: str, texts: list[str]) -> tuple[str, list[str]]:
    if len(texts) < 2 or not _title_needs_continuation(title):
        return title, texts
    continuation = texts[1]
    if not continuation or _looks_like_url_or_noise(continuation) or _first_location([continuation]):
        return title, texts
    combined = _clean_text(f"{title} {continuation}")
    if _first_job_title([combined]) != combined:
        return title, texts
    return combined, [combined, *texts[2:]]


def _title_needs_continuation(title: str) -> bool:
    normalized = _normalized(title)
    stripped = title.strip()
    return stripped.endswith(("-", "&", "/")) or normalized.endswith(" and")


def _has_synthetic_job_card_anchor(*, texts: list[str], company: str | None, location: str | None) -> bool:
    if location:
        return True
    if not company:
        return False
    return any(
        [
            any(_contains_any(text, {"posted"}) for text in texts),
            _first_work_type(texts) is not None,
            _first_salary(texts) is not None,
        ]
    )


def _synthetic_title_low_confidence(title: str | None) -> bool:
    text = _clean_text(title)
    if not text:
        return True
    if _looks_like_sentence_fragment_title(text):
        return True
    alnum = "".join(ch for ch in text if ch.isalnum())
    if len(alnum) < 18:
        return False
    if " " in text or "/" in text or "-" in text:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / max(1, len(letters))
    return uppercase_ratio >= 0.85


def _looks_like_sentence_fragment_title(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    first_alpha = next((ch for ch in cleaned if ch.isalpha()), "")
    if "?" in cleaned:
        return True
    if len(cleaned) >= 36 and first_alpha and first_alpha.islower():
        return True
    sentence_terms = {" join ", " make ", " help ", " support ", " deliver ", " build "}
    lowered = f" {cleaned.casefold()} "
    return len(cleaned) >= 42 and any(term in lowered for term in sentence_terms)


def _has_job_card_identity(*, title: str | None, company: str | None, location: str | None, evidence_texts: list[str]) -> bool:
    title_text = _clean_text(title)
    if not title_text:
        return False
    if _looks_like_filter_card(title_text) or _looks_like_non_job_heading(title_text):
        return False
    has_secondary = bool(company or location or _first_salary(evidence_texts))
    if _first_job_title([title_text]) == title_text and has_secondary:
        return True
    evidence_title = _best_job_title(evidence_texts)
    return bool(evidence_title and _same_title(evidence_title, title_text) and has_secondary)


def _looks_like_non_job_heading(text: str) -> bool:
    normalized = _normalized(text)
    if not normalized:
        return True
    if normalized.startswith(("saved search", "saved job", "compensation range", "next button")):
        return True
    return normalized in {
        "saved searches section",
        "saved searches",
        "saved jobs",
        "compensation range selector",
        "next button",
        "want better job recommendations",
    }


def _looks_like_detail_classification(text: str) -> bool:
    normalized = _normalized(text)
    if "information communication technology" in normalized:
        return True
    if normalized.startswith("engineering software information"):
        return True
    return False


def _looks_like_summary_sentence(text: str) -> bool:
    normalized = _normalized(text)
    if text.strip().endswith((".", "!", "?")):
        return True
    return any(
        phrase in normalized
        for phrase in {
            "build and support",
            "build scalable",
            "cloud environment",
            "global decarbonisation",
            "help accelerate",
            "help build",
            "join our team",
            "mission driven",
            "make a splash",
            "purpose led",
            "real growth runway",
            "measurable impact",
            "used by",
            "users worldwide",
            "we re looking",
            "we are looking",
            "you will",
            "are you passionate",
            "opportunities for",
            "product instinct",
            "problem as the solution",
            "work on frontend",
            "design secure",
            "partnering across teams",
            "frontend experiences",
            "robust backend",
            "digital transformation",
            "embedded c",
            "lead a talented",
            "monitoring technology",
            "reporting directly",
            " and flexible",
        }
    )


def _looks_like_url_or_noise(text: str) -> bool:
    normalized = _normalized(text)
    raw = text.strip().casefold()
    if raw.startswith(("http://", "https://", "www.")):
        return True
    if "seek.com/job" in raw or "job-invite" in raw:
        return True
    return normalized in {
        "save this search",
        "strong applicant jobs",
        "new to you",
        "featured",
        "advertisement",
    }


def _first_heading(texts: list[str]) -> str | None:
    skipped = {"apply", "save", "view all jobs", "posted", "how you match", "climate innovations"}
    for text in texts:
        normalized = _normalized(text)
        compact = re.sub(r"[^a-z0-9]+", "", normalized)
        if len(compact) < 3:
            continue
        if text and len(text) <= 120 and not any(term in normalized for term in skipped) and not _looks_like_filter_card(text):
            return text
    return None


def _first_action(actions: list[dict[str, Any]], labels: set[str]) -> dict[str, Any] | None:
    for action in actions:
        label = _normalized(action.get("label"))
        if label in labels or any(item in label for item in labels):
            return action
    return None


def _first_text_button(items: list[dict[str, Any]], labels: set[str]) -> dict[str, Any] | None:
    for item in items:
        text = _normalized(item.get("text") or item.get("label"))
        if text in labels or any(_text_matches_button_label_with_icon_suffix(text, item_label) for item_label in labels):
            bbox = _bbox(item.get("bbox"))
            if bbox is None:
                continue
            return {
                "id": item.get("id"),
                "label": _clean_text(item.get("text") or item.get("label")),
                "bbox": bbox,
                "click_point": {"x": bbox["x"] + bbox["w"] // 2, "y": bbox["y"] + bbox["h"] // 2},
                "metadata": {"source": "page_element_text_button"},
            }
    return None


def _text_matches_button_label_with_icon_suffix(text: str, label: str) -> bool:
    if text == label or text.startswith(f"{label} "):
        return True
    if text.startswith(label):
        suffix = text[len(label) :].strip()
        return 0 < len(suffix) <= 2 and suffix.isalpha()
    return False


def _detail_sections(texts: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        if len(text) < 3:
            continue
        role = "body"
        if _contains_any(text, {"requirement", "responsibil", "about the role", "benefit"}):
            role = "section_hint"
        sections.append({"index": index, "role": role, "text": text})
    return sections


def _job_id(*, label: str | None, company: str | None, location: str | None) -> str:
    basis = "|".join(item for item in [label, company, location] if item)
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12] if basis else "unknown"
    return f"seek_job_{digest}"


def _job_key(*, title: str | None, company: str | None, location: str | None, bbox: dict[str, int] | None) -> str:
    if title or company or location:
        return "|".join(_normalized(item) for item in [title, company, location] if item)
    if bbox:
        return f"bbox:{bbox['x']}:{bbox['y']}:{bbox['w']}:{bbox['h']}"
    return "unknown"


def _job_visual_order_key(job: dict[str, Any]) -> tuple[int, int, str]:
    bbox = _bbox(job.get("card_bbox"))
    if bbox is None:
        return (1_000_000, 1_000_000, str(job.get("title") or ""))
    return (int(bbox["y"]), int(bbox["x"]), str(job.get("title") or ""))


def _looks_like_incomplete_duplicate(
    *,
    title: str | None,
    company: str | None,
    location: str | None,
    seen_jobs: set[str],
) -> bool:
    if location:
        return False
    normalized_title = _normalized(title)
    if not normalized_title:
        return False
    for key in seen_jobs:
        if key.startswith(normalized_title + "|"):
            return True
    return False


def _is_less_complete_same_title_job(*, existing: dict[str, Any], replacement: dict[str, Any]) -> bool:
    if _normalized(existing.get("title")) != _normalized(replacement.get("title")):
        return False
    if not replacement.get("location") and not replacement.get("company"):
        return False
    existing_company = str(existing.get("company") or "")
    replacement_company = str(replacement.get("company") or "")
    company_is_summary = bool(existing_company and _looks_like_summary_sentence(existing_company))
    missing_or_weak_company = not existing_company or company_is_summary
    replacement_has_company = bool(replacement_company and not _looks_like_summary_sentence(replacement_company))
    if not existing.get("location") and replacement.get("location"):
        return True
    if missing_or_weak_company and replacement_has_company:
        return True
    return False


def _looks_like_filter_card(label: str) -> bool:
    normalized = _normalized(label)
    normalized_without_dropdown = re.sub(r"\s+v$", "", normalized).strip()
    if normalized.startswith("filter ") or normalized.startswith("filter:"):
        return True
    if "job filter" in normalized:
        return True
    if "strong applicant jobs" in normalized:
        return True
    return normalized_without_dropdown in {
        "pay",
        "type",
        "remote",
        "classification",
        "listing time",
        "date",
        "strong applicant jobs toggle",
        "new to you",
        "save this search",
    }


def _looks_like_non_job_card(card: dict[str, Any], *, window_size: dict[str, int] | None = None) -> bool:
    label = _clean_text(card.get("label"))
    normalized = _normalized(label)
    role = _normalized(card.get("role"))
    bbox = _bbox(card.get("bbox"))
    size = window_size if isinstance(window_size, dict) else {}
    window_w = int(size.get("width") or 0)
    window_h = int(size.get("height") or 0)
    if role in {"window", "pane", "group", "app", "document"}:
        return True
    if normalized in {
        "app",
        "pane",
        "group",
        "search results",
        "perform a job search",
        "job search",
        "refine your search",
    }:
        return True
    if "microsoft edge" in normalized or "job vacancies" in normalized:
        return True
    if bbox is not None and window_w > 0 and window_h > 0:
        area = bbox["w"] * bbox["h"]
        window_area = max(1, window_w * window_h)
        if area / window_area >= 0.18:
            return True
        if bbox["w"] >= int(window_w * 0.7) or bbox["h"] >= int(window_h * 0.55):
            return True
    return False


def _looks_like_seek_detail_body_card(*, label: str, evidence_texts: list[str]) -> bool:
    normalized_label = _normalized(label)
    if not normalized_label.endswith(" job card"):
        return False
    evidence = " ".join(_normalized(text) for text in evidence_texts)
    detail_markers = {
        "apply button",
        "jobs in all new zealand seek",
        "microsoft edge",
        "your capabilities",
        "your life at aia",
        "pane",
    }
    return any(marker in evidence for marker in detail_markers)
