from __future__ import annotations

import json
from typing import Any

from PIL import Image

from app.core.runtime_artifacts import ARTIFACTS_DIR
from app.learn.path_graph_resolver import resolve_runtime_path_graph
from app.operation.observe.contracts import ObserveScreenTaskInput
from app.operation.path_graph import build_available_actions
from app.learn.observe_enrichment.screen_map_builder import (
    _first_compact_text,
    _normalize_map_bbox,
    _number,
    _screen_map_texts,
    _texts_in_bbox,
)

DEFAULT_LEARNED_RUNTIME_PATH_GRAPHS = {
    "seek": ARTIFACTS_DIR / "seek" / "runtime_path_graph_seek_mvp_20260617.json",
}


def _runtime_graph_from_screen_map_for_interface_map(screen_map: dict[str, Any], *, result: dict[str, Any]) -> dict[str, Any]:
    """把 observe 的 screen_map 转成 Interface Map 所需的最小路径图。"""

    graph = screen_map if isinstance(screen_map, dict) else {}
    state_id = str(graph.get("state_id") or "observed_state")
    page_type = str(graph.get("page_type") or graph.get("state_hint") or result.get("state_guess") or "observed_page")
    regions: list[dict[str, Any]] = []
    for section in graph.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or section.get("region_id") or "").strip()
        if not section_id:
            continue
        regions.append(
            {
                "region_id": section_id,
                "label": section.get("label") or section_id,
                "role": section.get("role") or section.get("section_type") or "content",
                "bbox": section.get("bbox") if isinstance(section.get("bbox"), dict) else None,
                "container_id": section.get("container_id") or section_id,
                "repeatable": bool(section.get("repeatable")),
            }
        )
    return {
        "contract_version": "runtime_path_graph_v1",
        "graph_id": f"{graph.get('app_name') or result.get('app_name') or 'app'}:{page_type}:observe_interface_seed",
        "app_id": graph.get("app_name") or result.get("app_name"),
        "page_type": page_type,
        "states": [
            {
                "state_id": state_id,
                "label": graph.get("state_hint") or result.get("state_guess") or state_id,
                "state_fingerprint": graph.get("state_signature") if isinstance(graph.get("state_signature"), dict) else {},
            }
        ],
        "regions": regions,
        "source": {
            "contract_version": graph.get("contract_version"),
            "artifact_is_authorization": False,
            "source": "screen_map_v1",
        },
    }


def _apply_learned_path_graph_to_screen_map(
    screen_map: dict[str, Any],
    *,
    result: dict[str, Any],
    request: ObserveScreenTaskInput,
    image_path: str,
) -> dict[str, Any]:
    graph_info = _default_learned_runtime_path_graph(result, request=request)
    graph = graph_info.get("graph") if isinstance(graph_info, dict) else None
    if not isinstance(graph, dict):
        return screen_map
    screen_inventory = _observation_screen_inventory(result)
    if _observation_looks_like_seek_application_form(result, screen_inventory=screen_inventory):
        assisted = dict(screen_map)
        assisted["learned_path_graph_resolution"] = {
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "matched": False,
            "reason": "seek_application_form_not_search_results",
            "graph_path": graph_info.get("path"),
        }
        return assisted
    resolution = resolve_runtime_path_graph(
        graph,
        screen_inventory=screen_inventory,
        requested_state_id=None,
        safety={
            "forbid_final_submit": False,
            "allow_apply_entry": False,
            "allow_safe_fill": False,
        },
    )
    if not resolution.get("matched"):
        assisted = dict(screen_map)
        assisted["learned_path_graph_resolution"] = {
            **resolution,
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "graph_path": graph_info.get("path"),
        }
        return assisted
    sections = _screen_map_sections_from_runtime_path_graph(
        graph,
        result=result,
        image_path=image_path,
        fallback_sections=screen_map.get("sections") if isinstance(screen_map.get("sections"), list) else [],
    )
    actions = build_available_actions(
        graph,
        current_state_id=resolution.get("state_id"),
        include_guarded_apply=False,
        path_graph_resolution=resolution,
    )
    path_candidates = _screen_map_candidates_from_path_graph_actions(actions, sections=sections)
    observed_candidates = _resection_observed_candidates_for_path_graph(
        screen_map.get("candidates") if isinstance(screen_map.get("candidates"), list) else [],
        sections=sections,
        graph_app_id=str(graph.get("app_id") or ""),
    )
    candidates = _dedupe_screen_map_candidates([*path_candidates, *observed_candidates])
    assisted = {
        **screen_map,
        "state_id": resolution.get("state_id") or screen_map.get("state_id"),
        "state_hint": graph.get("page_type") or screen_map.get("state_hint"),
        "sections": sections,
        "candidates": candidates[:80],
        "learned_path_graph_resolution": {
            **resolution,
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "graph_path": graph_info.get("path"),
            "source": "runtime_path_graph_v1",
            "screen_map_policy": "learned_path_graph_primary_model_supplemental",
        },
        "learned_path_graph_available_actions": actions,
    }
    summary = dict(assisted.get("summary") if isinstance(assisted.get("summary"), dict) else {})
    summary.update(
        {
            "candidate_count": len(assisted["candidates"]),
            "safe_candidate_count": len([item for item in assisted["candidates"] if item.get("risk_class") == "safe_click_allowed"]),
            "blocked_candidate_count": len([item for item in assisted["candidates"] if item.get("risk_class") == "blocked"]),
            "section_count": len(sections),
            "learned_path_graph_used": True,
            "learned_path_graph_id": graph.get("graph_id"),
        }
    )
    assisted["summary"] = summary
    agent_usage = dict(assisted.get("agent_usage") if isinstance(assisted.get("agent_usage"), dict) else {})
    agent_usage["observe_role"] = "Use the learned runtime PathGraph as the primary page structure; use model output only as current text/evidence."
    agent_usage["execute_role"] = "Choose from learned_path_graph_available_actions, then validate coordinates through the gated action API."
    assisted["agent_usage"] = agent_usage
    return assisted


def _default_learned_runtime_path_graph(result: dict[str, Any], *, request: ObserveScreenTaskInput) -> dict[str, Any]:
    key = _learned_path_graph_key(result, request=request)
    path = DEFAULT_LEARNED_RUNTIME_PATH_GRAPHS.get(key)
    if not path or not path.exists():
        return {}
    try:
        graph = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(graph, dict) or graph.get("contract_version") != "runtime_path_graph_v1":
        return {}
    return {"key": key, "path": str(path), "graph": graph}


def _learned_path_graph_key(result: dict[str, Any], *, request: ObserveScreenTaskInput) -> str | None:
    haystack = " ".join(
        str(item or "")
        for item in [
            request.app_name,
            request.state_hint,
            result.get("app_name"),
            result.get("state_guess"),
            result.get("screen_summary"),
            (result.get("screen_reading") or {}).get("screen_summary") if isinstance(result.get("screen_reading"), dict) else "",
            (result.get("screen_reading") or {}).get("state_guess") if isinstance(result.get("screen_reading"), dict) else "",
        ]
    ).casefold()
    if "seek" in haystack or "nz.seek" in haystack or "job search" in haystack:
        return "seek"
    return None


def _observation_screen_inventory(result: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(result.get("screen_inventory"), dict):
        return result["screen_inventory"]
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    if isinstance(screen_reading.get("screen_inventory"), dict):
        return screen_reading["screen_inventory"]
    parse_result = result.get("parse_result") if isinstance(result.get("parse_result"), dict) else {}
    nested = parse_result.get("screen_reading") if isinstance(parse_result.get("screen_reading"), dict) else {}
    if isinstance(nested.get("screen_inventory"), dict):
        return nested["screen_inventory"]
    return None


def _observation_looks_like_seek_application_form(result: dict[str, Any], *, screen_inventory: dict[str, Any] | None) -> bool:
    labels = " ".join(_inventory_texts(screen_inventory)).casefold()
    fields = [
        result.get("screen_summary"),
        result.get("state_guess"),
        (result.get("screen_reading") or {}).get("screen_summary") if isinstance(result.get("screen_reading"), dict) else "",
        (result.get("screen_reading") or {}).get("state_guess") if isinstance(result.get("screen_reading"), dict) else "",
        labels,
    ]
    text = " ".join(str(item or "") for item in fields).casefold()
    form_terms = [
        "choose documents",
        "answer employer questions",
        "update seek profile",
        "review and submit",
        "application form",
        "cover letter",
    ]
    return any(term in text for term in form_terms)


def _screen_map_sections_from_runtime_path_graph(
    graph: dict[str, Any],
    *,
    result: dict[str, Any],
    image_path: str,
    fallback_sections: list[Any],
) -> list[dict[str, Any]]:
    width, height = _screen_map_image_size(result, image_path=image_path)
    learned_bboxes = _learned_graph_region_bboxes(graph, width=width, height=height)
    sections: list[dict[str, Any]] = []
    fallback_by_id = {str(item.get("section_id") or ""): item for item in fallback_sections if isinstance(item, dict)}
    for region in graph.get("regions") or []:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "").strip()
        if not region_id:
            continue
        bbox = learned_bboxes.get(region_id) or _normalize_map_bbox(region.get("bbox")) or _normalize_map_bbox(fallback_by_id.get(region_id, {}).get("bbox"))
        section = {
            "contract_version": "screen_map_section_v1",
            "section_id": region_id,
            "label": region.get("label") or region_id.replace("_", " ").title(),
            "role": region.get("role") or "content",
            "description": "Learned from runtime_path_graph_v1.",
            "bbox": bbox,
            "container_id": region.get("container_id"),
            "parent_section_id": region.get("parent_region_id"),
            "repeatable": bool(region.get("repeatable")),
            "contains": region.get("contains") or [],
            "source": "runtime_path_graph_v1",
            "text_count": 0,
            "text_sample": [],
        }
        texts = _texts_in_bbox(_screen_map_texts(result), bbox) if bbox else []
        section["text_count"] = len(texts)
        section["text_sample"] = [_first_compact_text(item.get("text")) for item in texts[:10] if _first_compact_text(item.get("text"))]
        sections.append(section)
    return sections or [item for item in fallback_sections if isinstance(item, dict)]


def _screen_map_candidates_from_path_graph_actions(actions: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = actions.get("actions") if isinstance(actions, dict) else []
    candidates: list[dict[str, Any]] = []
    for index, action in enumerate(payload if isinstance(payload, list) else []):
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("action_template_id") or action.get("action_id") or f"path_action_{index}")
        section_id = _section_for_path_graph_action(action_id, action)
        bbox = _section_bbox(sections, section_id)
        candidates.append(
            {
                "contract_version": "screen_map_candidate_v1",
                "candidate_id": f"path_graph_action_{action_id}",
                "label": action.get("label") or action.get("goal_template") or action_id.replace("_", " "),
                "role": action.get("action_kind") or action.get("low_level_action_type") or "action",
                "goal_hint": action.get("goal_template") or action_id,
                "expected_effect": action.get("to_state_id") or action.get("transition_id") or "",
                "risk_class": "safe_click_allowed" if action.get("low_level_action_type") in {"click", "scroll", "input"} else "safe_review_only",
                "section_id": section_id,
                "bbox": bbox,
                "click_point": _bbox_center(bbox),
                "confidence": 0.92,
                "source": "runtime_path_graph_v1",
                "action_template_id": action_id,
                "low_level_action_type": action.get("low_level_action_type"),
                "artifact_is_authorization": False,
            }
        )
    return candidates


def _resection_observed_candidates_for_path_graph(
    candidates: list[Any],
    *,
    sections: list[dict[str, Any]],
    graph_app_id: str,
) -> list[dict[str, Any]]:
    learned_sections = [item for item in sections if isinstance(item, dict) and item.get("bbox")]
    results: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        bbox = _normalize_map_bbox(candidate.get("bbox"))
        section_id = _best_section_id_for_bbox(bbox, learned_sections) if bbox else candidate.get("section_id")
        if section_id:
            candidate["section_id"] = section_id
        if graph_app_id == "seek":
            _apply_seek_path_graph_candidate_policy(candidate)
        candidate["source_before_path_graph"] = candidate.get("source")
        candidate["source"] = "model_observation_resectioned_by_runtime_path_graph"
        results.append(candidate)
    return results


def _apply_seek_path_graph_candidate_policy(candidate: dict[str, Any]) -> None:
    section_id = str(candidate.get("section_id") or "")
    role = str(candidate.get("role") or "").casefold()
    label = str(candidate.get("label") or "")
    if section_id == "results_list" and role in {"news_card", "card", "menu_item", "menu item", ""}:
        candidate["role"] = "job_card"
        candidate["risk_class"] = "safe_click_allowed"
        candidate["expected_effect"] = "open selected SEEK job in job_detail"
    elif section_id in {"job_detail", "detail_header", "detail_body"}:
        if any(term in label.casefold() for term in ("apply", "quick apply")):
            candidate["role"] = "button"
            candidate["risk_class"] = "safe_click_allowed"
            candidate["expected_effect"] = "enter guarded apply flow; final submit remains forbidden"
        else:
            candidate["risk_class"] = candidate.get("risk_class") or "safe_review_only"


def _screen_map_image_size(result: dict[str, Any], *, image_path: str) -> tuple[int, int]:
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    width = int(_number(image_size.get("width") or live_capture.get("image_width")) or 0)
    height = int(_number(image_size.get("height") or live_capture.get("image_height")) or 0)
    if width > 0 and height > 0:
        return width, height
    try:
        with Image.open(image_path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 1000, 1000


def _learned_graph_region_bboxes(graph: dict[str, Any], *, width: int, height: int) -> dict[str, dict[str, int]]:
    if graph.get("app_id") != "seek":
        return {}
    chrome_h = min(height, max(72, round(height * 0.06)))
    top_h = min(height - chrome_h, max(120, round(height * 0.12)))
    content_y = chrome_h + top_h
    content_h = max(1, height - content_y)
    results_x = round(width * 0.235)
    results_w = round(width * 0.20)
    detail_x = round(width * 0.45)
    detail_w = max(1, width - detail_x - round(width * 0.04))
    return {
        "top_search_area": {"x": 0, "y": chrome_h, "w": width, "h": top_h},
        "results_list": {"x": results_x, "y": content_y, "w": results_w, "h": content_h},
        "job_detail": {"x": detail_x, "y": content_y, "w": detail_w, "h": content_h},
        "job_card": {"x": results_x, "y": content_y, "w": results_w, "h": content_h},
        "detail_header": {"x": detail_x, "y": content_y, "w": detail_w, "h": max(1, round(content_h * 0.30))},
        "detail_body": {"x": detail_x, "y": content_y + round(content_h * 0.30), "w": detail_w, "h": max(1, round(content_h * 0.70))},
    }


def _section_for_path_graph_action(action_id: str, action: dict[str, Any]) -> str:
    if action.get("scroll_container_id") == "seek:job_detail" or action_id in {"read_detail", "apply_entry"}:
        return "job_detail"
    if action.get("scroll_container_id") == "seek:results_list" or action_id in {"open_job_card", "load_more_results"}:
        return "results_list"
    return str(action.get("source_section_id") or action.get("target_section_id") or "main_content")


def _section_bbox(sections: list[dict[str, Any]], section_id: str) -> dict[str, int] | None:
    for section in sections:
        if section.get("section_id") == section_id and isinstance(section.get("bbox"), dict):
            return _normalize_map_bbox(section["bbox"])
    return None


def _bbox_center(bbox: dict[str, Any] | None) -> dict[str, int] | None:
    normalized = _normalize_map_bbox(bbox)
    if not normalized:
        return None
    return {
        "x": int(round(normalized["x"] + normalized["w"] / 2)),
        "y": int(round(normalized["y"] + normalized["h"] / 2)),
    }


def _best_section_id_for_bbox(bbox: dict[str, Any] | None, sections: list[dict[str, Any]]) -> str | None:
    normalized = _normalize_map_bbox(bbox)
    if not normalized:
        return None
    best: tuple[float, str] | None = None
    for section in sections:
        section_bbox = _normalize_map_bbox(section.get("bbox"))
        if not section_bbox:
            continue
        overlap = _bbox_intersection_area(normalized, section_bbox)
        if overlap <= 0:
            continue
        score = overlap / max(1.0, float(normalized["w"] * normalized["h"]))
        section_id = str(section.get("section_id") or "")
        if best is None or score > best[0]:
            best = (score, section_id)
    return best[1] if best and best[0] >= 0.2 else None


def _bbox_intersection_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["w"]), by1 + float(b["h"])
    return max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))


def _dedupe_screen_map_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        label = str(candidate.get("label") or "")
        section_id = str(candidate.get("section_id") or "")
        action_id = str(candidate.get("action_template_id") or "")
        bbox = _normalize_map_bbox(candidate.get("bbox"))
        bbox_key = ""
        if bbox:
            bbox_key = f"{bbox['x']}:{bbox['y']}:{bbox['w']}:{bbox['h']}"
        key = f"{action_id}|{label.casefold()}|{section_id}|{bbox_key}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _inventory_texts(screen_inventory: dict[str, Any] | None) -> list[str]:
    inventory = screen_inventory if isinstance(screen_inventory, dict) else {}
    labels: list[str] = []
    for key in ("available_actions", "page_elements", "cards"):
        for item in inventory.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in ("label", "text", "title", "name"):
                value = item.get(field)
                if value:
                    labels.append(str(value))
    return labels


def runtime_graph_from_screen_map_for_interface_map(
    screen_map: dict[str, Any],
    *,
    result: dict[str, Any],
) -> dict[str, Any]:
    return _runtime_graph_from_screen_map_for_interface_map(screen_map, result=result)


def apply_learned_path_graph_to_screen_map(
    screen_map: dict[str, Any],
    *,
    result: dict[str, Any],
    task: ObserveScreenTaskInput,
    image_path: str,
) -> dict[str, Any]:
    return _apply_learned_path_graph_to_screen_map(
        screen_map,
        result=result,
        request=task,
        image_path=image_path,
    )
