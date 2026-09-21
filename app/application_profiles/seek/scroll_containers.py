from __future__ import annotations

from typing import Any


SEEK_PAGE = "seek:page"
SEEK_RESULTS_LIST = "seek:results_list"
SEEK_JOB_DETAIL = "seek:job_detail"


def discover_seek_scroll_containers(
    *,
    window_title: str | None = None,
    app_name: str | None = None,
    window_size: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic SEEK three-pane scroll map for the current screenshot space."""

    size = _size(window_size)
    title = str(window_title or "")
    app = str(app_name or "")
    is_seek = "seek" in title.casefold() or "seek" in app.casefold()
    width = size["width"]
    height = size["height"]
    body_top = _clamp(int(round(height * 0.2)), 180, max(220, height - 220))
    body_bottom_margin = 16
    body_height = max(140, height - body_top - body_bottom_margin)

    content_width = min(max(720, width - 32), 1500)
    content_left = max(16, (width - content_width) // 2) if width > 1600 else 16
    content_right = min(width - 16, content_left + content_width)
    gutter = 48 if width <= 1600 else 64
    results_x = content_left
    results_width = _clamp(int(round(content_width * 0.36)), 360, 560)
    if results_x + results_width > content_right - 260:
        results_width = max(220, (content_width // 2) - gutter)
    detail_x = min(content_right - 220, results_x + results_width + gutter)
    detail_width = max(220, content_right - detail_x)
    evidence_payload = evidence if isinstance(evidence, dict) else {}
    evidence_results_bbox = _bbox(evidence_payload.get("results_list_bbox"))
    if evidence_results_bbox is not None:
        results_x = evidence_results_bbox["x"]
        results_width = evidence_results_bbox["w"]
        body_top = evidence_results_bbox["y"]
        body_height = evidence_results_bbox["h"]
        detail_x = min(width - 220, results_x + results_width + gutter)
        detail_width = max(220, min(content_right, width - 16) - detail_x)
        if detail_width <= 260:
            detail_x = min(width - 220, results_x + results_width + gutter)
            detail_width = max(220, width - detail_x - 16)
    page = {
        "container_id": SEEK_PAGE,
        "stable_key": "seek.search.page",
        "pane_role": "page",
        "scroll_scope": "page",
        "axis": "vertical",
        "bbox": {"x": 0, "y": 0, "w": width, "h": height},
        "can_scroll_up": True,
        "can_scroll_down": True,
        "confidence": 0.75 if is_seek else 0.45,
        "sources": ["seek_layout_heuristic"],
        "evidence": {
            "layout": "full_window_page",
            "title_contains_seek": "seek" in title.casefold(),
            "app_contains_seek": "seek" in app.casefold(),
            "content_left": content_left,
            "content_width": content_width,
        },
        "safe_points": [{"x": width // 2, "y": min(height - 24, max(24, body_top + body_height // 2)), "reason": "page_center"}],
    }
    results = {
        "container_id": SEEK_RESULTS_LIST,
        "stable_key": "seek.search.results_list",
        "pane_role": "results_list",
        "scroll_scope": "container",
        "axis": "vertical",
        "bbox": {"x": results_x, "y": body_top, "w": results_width, "h": body_height},
        "can_scroll_up": True,
        "can_scroll_down": True,
        "confidence": 0.9 if is_seek else 0.55,
        "sources": ["screen_inventory_job_card_bbox"] if evidence_results_bbox is not None else ["seek_layout_heuristic"],
        "evidence": {
            "layout": "left_results_right_detail",
            "role_hint": "left column repeated job cards",
            "title_contains_seek": "seek" in title.casefold(),
            "content_left": content_left,
            "content_width": content_width,
            "source": "screen_inventory_job_card_bbox" if evidence_results_bbox is not None else "seek_layout_heuristic",
        },
        "safe_points": [
            {
                "x": results_x + results_width // 2,
                "y": body_top + body_height // 2,
                "reason": "inside_results_list_not_on_edge",
            }
        ],
    }
    detail = {
        "container_id": SEEK_JOB_DETAIL,
        "stable_key": "seek.search.job_detail",
        "pane_role": "job_detail",
        "scroll_scope": "container",
        "axis": "vertical",
        "bbox": {"x": detail_x, "y": body_top, "w": detail_width, "h": body_height},
        "can_scroll_up": True,
        "can_scroll_down": True,
        "confidence": 0.9 if is_seek else 0.55,
        "sources": ["seek_layout_heuristic"],
        "evidence": {
            "layout": "left_results_right_detail",
            "role_hint": "right job detail pane",
            "title_contains_seek": "seek" in title.casefold(),
            "content_left": content_left,
            "content_width": content_width,
        },
        "safe_points": [
            {
                "x": detail_x + detail_width // 2,
                "y": body_top + body_height // 2,
                "reason": "inside_job_detail_body",
            }
        ],
    }
    return {
        "contract_version": "scroll_containers_v1",
        "site": "seek",
        "is_seek_search_page": is_seek,
        "layout_type": "left_results_right_detail" if is_seek else "seek_layout_heuristic_unconfirmed",
        "coordinate_space": "window_screenshot",
        "coordinate_window_size": size,
        "containers": [page, results, detail],
        "summary": {
            "container_count": 3,
            "roles": ["page", "results_list", "job_detail"],
            "source": "seek_layout_heuristic",
        },
    }


def get_scroll_container(containers: dict[str, Any], container_id: str | None) -> dict[str, Any] | None:
    if not isinstance(containers, dict) or not container_id:
        return None
    for item in containers.get("containers") or []:
        if isinstance(item, dict) and item.get("container_id") == container_id:
            return item
    return None


def seek_scroll_target_for_goal(goal: str | None) -> dict[str, str]:
    normalized = str(goal or "").casefold()
    detail_terms = {
        "detail",
        "description",
        "requirement",
        "requirements",
        "responsibil",
        "about the role",
        "salary",
        "benefit",
        "apply",
        "save",
        "company profile",
        "right",
        "详情",
        "要求",
        "职责",
        "薪资",
        "申请",
    }
    list_terms = {
        "job card",
        "result",
        "listing",
        "next job",
        "职位卡片",
        "列表",
        "下一个",
        "更多职位",
    }
    if any(term in normalized for term in detail_terms):
        return {
            "target_pane": "job_detail",
            "target_container_id": SEEK_JOB_DETAIL,
            "reason": "goal_likely_needs_job_detail_scroll",
        }
    if any(term in normalized for term in list_terms):
        return {
            "target_pane": "results_list",
            "target_container_id": SEEK_RESULTS_LIST,
            "reason": "goal_likely_needs_results_list_scroll",
        }
    return {
        "target_pane": "results_list",
        "target_container_id": SEEK_RESULTS_LIST,
        "reason": "default_seek_missing_candidate_scrolls_results_list",
    }


def _size(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    width = _positive_int(value.get("width") or value.get("w"), 0)
    height = _positive_int(value.get("height") or value.get("h"), 0)
    return {"width": max(1, width), "height": max(1, height)}


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    width = value.get("w", value.get("width"))
    height = value.get("h", value.get("height"))
    try:
        return {
            "x": int(float(value.get("x") or 0)),
            "y": int(float(value.get("y") or 0)),
            "w": max(1, int(float(width or 0))),
            "h": max(1, int(float(height or 0))),
        }
    except (TypeError, ValueError):
        return None


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))
