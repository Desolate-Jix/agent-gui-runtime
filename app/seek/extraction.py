from __future__ import annotations

import hashlib
import re
from typing import Any

from app.screen_inventory import build_screen_inventory
from app.seek.scroll_containers import SEEK_JOB_DETAIL, SEEK_RESULTS_LIST, discover_seek_scroll_containers, get_scroll_container


def extract_seek_job_cards(source: dict[str, Any] | None, *, goal: str | None = None) -> dict[str, Any]:
    """Extract visible SEEK job cards from a screen inventory or screen reading payload."""

    inventory = _inventory(source, goal=goal)
    size = _inventory_size(source)
    containers = discover_seek_scroll_containers(window_size=size, app_name="seek")
    results_container = get_scroll_container(containers, SEEK_RESULTS_LIST)
    results_bbox = _bbox((results_container or {}).get("bbox"))
    actions = {item.get("id"): item for item in _items(inventory.get("available_actions"))}
    page_elements = {item.get("id"): item for item in _items(inventory.get("page_elements"))}
    jobs: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()
    for card in _items(inventory.get("cards")):
        label = _clean_text(card.get("label"))
        if not label or _looks_like_filter_card(label):
            continue
        card_bbox = _bbox(card.get("bbox"))
        if results_bbox is not None and not _inside(card.get("bbox"), results_bbox):
            continue
        if results_bbox is not None and card_bbox is not None and card_bbox["y"] < results_bbox["y"]:
            continue
        child_actions = [actions[item_id] for item_id in card.get("child_action_ids") or [] if item_id in actions]
        child_pages = [page_elements[item_id] for item_id in card.get("child_page_element_ids") or [] if item_id in page_elements]
        primary_action = actions.get(card.get("primary_action_id"))
        evidence_texts = [_clean_text(item.get("text") or item.get("label")) for item in child_pages + child_actions]
        evidence_texts = [item for item in evidence_texts if item]
        generic_label = _looks_like_generic_job_label(label)
        title = _card_title(label, evidence_texts)
        if not title:
            continue
        if _title_needs_continuation(title):
            continue
        title_index = evidence_texts.index(title) if title in evidence_texts else -1
        company_candidates = (
            evidence_texts[title_index + 1 :]
            if generic_label and title_index >= 0
            else [text for text in evidence_texts if text != title]
        )
        company = _first_company(company_candidates)
        location = _first_location(evidence_texts)
        if _looks_like_incomplete_duplicate(title=title, company=company, location=location, seen_jobs=seen_jobs):
            continue
        job_key = _job_key(title=title, company=company, location=location, bbox=card_bbox)
        if job_key in seen_jobs:
            continue
        seen_jobs.add(job_key)
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
            "card_bbox": card_bbox,
            "click_point": (primary_action or {}).get("click_point"),
            "source_url": _first_url(evidence_texts),
            "source_card_id": card.get("id"),
            "primary_action_id": card.get("primary_action_id"),
            "child_action_ids": list(card.get("child_action_ids") or []),
            "child_page_element_ids": list(card.get("child_page_element_ids") or []),
            "evidence": {
                "texts": evidence_texts,
                "source_contract": inventory.get("contract_version"),
            },
        }
        jobs.append(job)
    for job in _synthetic_jobs_from_page_elements(page_elements, results_bbox):
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
            continue
        seen_jobs.add(job_key)
        jobs.append(job)
    jobs = _dedupe_overlapping_job_candidates(jobs)
    return {
        "contract_version": "seek_job_cards_v1",
        "source_contract": inventory.get("contract_version"),
        "image_size": size,
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
    containers = scroll_containers or discover_seek_scroll_containers(window_size=size, app_name="seek")
    detail_container = get_scroll_container(containers, SEEK_JOB_DETAIL)
    detail_bbox = _bbox((detail_container or {}).get("bbox"))
    detail_read_bbox = _expand_bbox_up(detail_bbox, pixels=220)
    actions = [item for item in _items(inventory.get("available_actions")) if _inside(item.get("bbox"), detail_read_bbox)]
    page_elements = [item for item in _items(inventory.get("page_elements")) if _inside(item.get("bbox"), detail_read_bbox)]
    texts = [_clean_text(item.get("text") or item.get("label")) for item in page_elements]
    texts = [item for item in texts if item]
    title = _first_job_title(texts) or _first_heading(texts)
    title_index = texts.index(title) if title in texts else -1
    company_candidates = texts[title_index + 1 :] if title_index >= 0 else texts
    company = _first_company(company_candidates)
    apply_action = _first_action(actions, {"apply", "quick apply"}) or _first_text_button(page_elements, {"apply", "quick apply"})
    save_action = _first_action(actions, {"save", "save job"})
    requirements = [text for text in texts if _contains_any(text, {"requirement", "requirements", "must have", "skills", "experience"})]
    responsibilities = [text for text in texts if _contains_any(text, {"responsibil", "about the role", "you will", "role"})]
    benefits = [text for text in texts if _contains_any(text, {"benefit", "parking", "insurance", "flexible", "remote", "hybrid"})]
    return {
        "contract_version": "seek_job_detail_v1",
        "job_id": _job_id(label=title, company=company, location=_first_location(texts)),
        "title": title,
        "company": company,
        "location": _first_location(texts),
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
        },
        "save_button_state": {
            "visible": save_action is not None,
            "label": (save_action or {}).get("label"),
            "bbox": _bbox((save_action or {}).get("bbox")),
        },
        "detail_container": detail_container,
        "detail_read_bbox": detail_read_bbox,
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


def _inventory_size(source: dict[str, Any] | None) -> dict[str, int]:
    payload = source if isinstance(source, dict) else {}
    image_size = payload.get("image_size") if isinstance(payload.get("image_size"), dict) else {}
    width = int(image_size.get("width") or payload.get("image_width") or 1246)
    height = int(image_size.get("height") or payload.get("image_height") or 1194)
    return {"width": width, "height": height}


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


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _contains_any(value: str, terms: set[str]) -> bool:
    normalized = _normalized(value)
    return any(term in normalized for term in terms)


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
        company = _first_company([text for text in texts[1:] if text != title])
        location = _first_location(texts)
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
        score += 1
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


def _first_salary(texts: list[str]) -> str | None:
    for text in texts:
        if re.search(r"\$\s*\d|\b\d+\s*k\b", text, flags=re.IGNORECASE):
            return text
    return None


def _first_location(texts: list[str]) -> str | None:
    location_terms = {"auckland", "wellington", "christchurch", "hamilton", "tauranga", "remote", "new zealand", "nz"}
    for text in texts:
        if _looks_like_url_or_noise(text) or _looks_like_summary_sentence(text):
            continue
        if len(text) <= 80 and _contains_any(text, location_terms):
            return text
    return None


def _first_work_type(texts: list[str]) -> str | None:
    for text in texts:
        if _contains_any(text, {"full time", "part time", "contract", "casual", "permanent", "hybrid", "remote"}):
            return text
    return None


def _first_classification(texts: list[str]) -> str | None:
    for text in texts:
        if _contains_any(text, {"engineering", "information", "technology", "software", "ict"}):
            return text
    return None


def _first_url(texts: list[str]) -> str | None:
    for text in texts:
        match = re.search(r"https?://\S+", text)
        if match:
            return match.group(0)
    return None


def _first_company(texts: list[str]) -> str | None:
    skipped = {
        "posted",
        "auckland",
        "remote",
        "full time",
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
        "jobs",
        "save this search",
        "background",
    }
    for text in texts:
        text = _clean_company(text)
        normalized = _normalized(text)
        if not text or any(term in normalized for term in skipped):
            continue
        if _looks_like_url_or_noise(text):
            continue
        if _looks_like_summary_sentence(text):
            continue
        if re.search(r"\$\s*\d|\b(\d+\s*[dh]|\d+\s*(day|hour|week|month)s?)\s+ago\b|\bviewed\b", normalized):
            continue
        if len(text) <= 80:
            return text
    return None


def _clean_company(text: str) -> str:
    value = _clean_text(text)
    for marker in (" View all jobs", " View alljobs"):
        if marker in value:
            value = value.split(marker, 1)[0].strip()
    return value


def _card_title(label: str, evidence_texts: list[str]) -> str | None:
    if not _looks_like_generic_job_label(label):
        return label
    return _first_job_title(evidence_texts)


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
            return text
    return None


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
            "mission driven",
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
            "frontend experiences",
            "robust backend",
            "digital transformation",
            "lead a talented",
            "reporting directly",
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
        if text and len(text) <= 120 and not any(term in normalized for term in skipped):
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
        if text in labels or any(text == item_label or text.startswith(f"{item_label} ") for item_label in labels):
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
    return normalized in {"pay", "type", "remote", "classification", "listing time", "date"}
