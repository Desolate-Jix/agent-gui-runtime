from __future__ import annotations

import hashlib
import re
from typing import Any

from app.operation.observe.contracts import ObserveScreenTaskInput


def _suggested_state_hint_from_observation(result: dict[str, Any]) -> str:
    for value in (result.get("state_guess"), result.get("screen_summary")):
        hint = _compact_state_hint(value)
        if hint:
            return hint
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    for value in (screen_reading.get("state_guess"), screen_reading.get("screen_summary")):
        hint = _compact_state_hint(value)
        if hint:
            return hint
    return ""


def _compact_state_hint(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or text.casefold() in {"unknown", "none", "null"}:
        return ""
    return text[:80]


def _build_screen_map_from_observation(result: dict[str, Any], *, request: ObserveScreenTaskInput, image_path: str) -> dict[str, Any]:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    screen_summary = (
        result.get("screen_summary")
        or screen_reading.get("screen_summary")
        or result.get("message")
        or ""
    )
    state_hint = result.get("suggested_state_hint") or _suggested_state_hint_from_observation(result)
    sections = _screen_map_sections(result)
    candidates = _screen_map_candidates(result, sections=sections)
    app_name = request.app_name or result.get("app_name") or screen_reading.get("app_name") or ""
    signature = _screen_state_signature(
        app_name=app_name,
        state_hint=state_hint,
        screen_summary=screen_summary,
        image_path=image_path,
        candidates=candidates,
    )
    return {
        "contract_version": "screen_map_v1",
        "state_id": signature["state_id"],
        "app_name": app_name,
        "image_path": image_path,
        "state_hint": state_hint,
        "summary": {
            "screen_summary": screen_summary,
            "candidate_count": len(candidates),
            "safe_candidate_count": len([item for item in candidates if item.get("risk_class") == "safe_click_allowed"]),
            "blocked_candidate_count": len([item for item in candidates if item.get("risk_class") == "blocked"]),
            "section_count": len(sections),
        },
        "state_signature": signature,
        "sections": sections,
        "candidates": candidates,
        "agent_usage": {
            "observe_role": "Build the semantic page/action map.",
            "locate_role": "Locate one selected screen_map candidate precisely before any click.",
            "execute_role": "Verify the selected point and post-click transition through the gated action API.",
        },
    }


def _screen_map_sections(result: dict[str, Any]) -> list[dict[str, Any]]:
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    width = int(_number(image_size.get("width") or live_capture.get("image_width")) or 0)
    height = int(_number(image_size.get("height") or live_capture.get("image_height")) or 0)
    if width <= 0:
        width = _max_text_edge(result, axis="x") or 1000
    if height <= 0:
        height = _max_text_edge(result, axis="y") or 1000

    if not _screen_map_looks_like_browser_page(result):
        return _application_screen_map_sections(result, width=width, height=height)

    browser_chrome_bottom = min(height, max(80, round(height * 0.085)))
    page_header_bottom = min(height, max(browser_chrome_bottom + 70, round(height * 0.17)))
    promo_bottom = min(height, max(page_header_bottom + 90, round(height * 0.30)))
    main_bottom = min(height, max(promo_bottom + 260, round(height * 0.86)))

    has_right_sidebar = _screen_map_has_right_sidebar_evidence(result, width=width, height=height, top_y=promo_bottom, bottom_y=main_bottom)
    right_sidebar_x = round(width * 0.58) if has_right_sidebar else width

    sections = [
        _screen_map_section(
            "browser_chrome",
            "Browser chrome",
            "browser",
            "Browser tabs, address bar, and extension controls.",
            {"x": 0, "y": 0, "w": width, "h": browser_chrome_bottom},
            result,
        ),
        _screen_map_section(
            "page_header",
            "Top navigation",
            "navigation",
            "Website header, logo, language controls, and top navigation tabs.",
            {"x": 0, "y": browser_chrome_bottom, "w": width, "h": max(1, page_header_bottom - browser_chrome_bottom)},
            result,
        ),
        _screen_map_section(
            "promo_strip",
            "Promotion strip",
            "content",
            "Horizontal promotional or feature cards above the main tool area.",
            {"x": 0, "y": page_header_bottom, "w": width, "h": max(1, promo_bottom - page_header_bottom)},
            result,
        ),
        _screen_map_section(
            "main_content",
            "Main content",
            "content",
            "Primary page body with tool cards, panels, forms, and test areas.",
            {"x": 0, "y": promo_bottom, "w": right_sidebar_x, "h": max(1, main_bottom - promo_bottom)},
            result,
        ),
    ]
    if has_right_sidebar:
        sections.append(
            _screen_map_section(
                "right_sidebar",
                "Right sidebar",
                "content",
                "Secondary column with recommendations, related items, widgets, or quick actions.",
                {"x": right_sidebar_x, "y": promo_bottom, "w": max(1, width - right_sidebar_x), "h": max(1, main_bottom - promo_bottom)},
                result,
            )
        )
    if main_bottom < height:
        sections.append(
            _screen_map_section(
                "lower_content",
                "Lower content",
                "content",
                "Content below the first viewport's main card area.",
                {"x": 0, "y": main_bottom, "w": width, "h": max(1, height - main_bottom)},
                result,
            )
        )
    floating = _floating_overlay_section(result, width=width, height=height)
    if floating:
        sections.append(floating)
    return sections


def _screen_map_looks_like_browser_page(result: dict[str, Any]) -> bool:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    haystack = " ".join(
        str(item or "")
        for item in (
            result.get("app_name"),
            screen_reading.get("app_name"),
            result.get("suggested_state_hint"),
            result.get("state_guess"),
            result.get("screen_summary"),
            live_capture.get("process_name"),
            live_capture.get("window_title"),
            live_capture.get("title"),
        )
    ).casefold()
    browser_tokens = (
        "browser",
        "chrome",
        "edge",
        "msedge",
        "firefox",
        "brave",
        "google news",
        "news homepage",
        "web page",
        "website",
        "http://",
        "https://",
        "www.",
    )
    if any(token in haystack for token in browser_tokens):
        return True
    text_blob = " ".join(str(item.get("text") or "") for item in _screen_map_texts(result) if isinstance(item, dict)).casefold()
    web_text_hits = sum(1 for token in ("home", "for you", "following", "search", "sign in", "settings") if token in text_blob)
    return web_text_hits >= 4


def _screen_map_has_right_sidebar_evidence(result: dict[str, Any], *, width: int, height: int, top_y: int, bottom_y: int) -> bool:
    if width < 900:
        return False
    right_x = round(width * 0.58)
    right_texts: list[str] = []
    left_texts = 0
    for item in _screen_map_texts(result):
        if not isinstance(item, dict):
            continue
        bbox = _normalize_map_bbox(item.get("bbox"))
        if not bbox:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        if center_y < top_y or center_y > bottom_y:
            continue
        text = str(item.get("text") or "").strip()
        if center_x >= right_x:
            if text:
                right_texts.append(text)
        else:
            left_texts += 1
    if len(right_texts) < 3 or left_texts < 2:
        return False
    right_blob = " ".join(right_texts).casefold()
    sidebar_tokens = (
        "recommended",
        "recommendation",
        "related",
        "for you",
        "headlines",
        "perspectives",
        "weather",
        "business",
        "technology",
        "entertainment",
        "sports",
        "world",
        "local",
    )
    if any(token in right_blob for token in sidebar_tokens):
        return True
    return len(right_texts) >= 5


def _application_screen_map_sections(result: dict[str, Any], *, width: int, height: int) -> list[dict[str, Any]]:
    top_bar_bottom = _application_top_bar_bottom(result, width=width, height=height)
    bottom_bar_top = _application_bottom_bar_top(result, height=height)
    content_bottom = bottom_bar_top if bottom_bar_top is not None else height
    sections = [
        _screen_map_section(
            "top_bar",
            "Top bar",
            "navigation",
            "Application top bar with primary tabs, search, account, and window-level actions.",
            {"x": 0, "y": 0, "w": width, "h": top_bar_bottom},
            result,
        ),
        _screen_map_section(
            "primary_area",
            "Primary area",
            "content",
            "Primary application workspace with panels, controls, cards, and action areas.",
            {"x": 0, "y": top_bar_bottom, "w": width, "h": max(1, content_bottom - top_bar_bottom)},
            result,
        ),
    ]
    if bottom_bar_top is not None:
        sections.append(
            _screen_map_section(
                "bottom_bar",
                "Bottom bar",
                "status",
                "Lower application area with secondary actions, status, or footer controls.",
                {"x": 0, "y": content_bottom, "w": width, "h": max(1, height - content_bottom)},
                result,
            )
        )
    floating = _floating_overlay_section(result, width=width, height=height)
    if floating:
        sections.append(floating)
    return sections


def _application_top_bar_bottom(result: dict[str, Any], *, width: int, height: int) -> int:
    top_limit = max(80, round(height * 0.24))
    evidence_boxes: list[dict[str, int]] = []
    element_sources = [_as_list(result.get("ui_elements"))]
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    element_sources.append(_as_list(screen_reading.get("ui_elements")))
    screen_reading_ui = screen_reading.get("ui") if isinstance(screen_reading.get("ui"), dict) else {}
    element_sources.append(_as_list(screen_reading_ui.get("elements")))
    for source in element_sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            bbox = _normalize_map_bbox(item.get("bbox"))
            if not bbox or bbox["y"] >= top_limit:
                continue
            role = " ".join(str(item.get(key) or "") for key in ("type", "role", "role_guess")).casefold()
            if not any(token in role for token in ("menu", "tab", "nav", "button", "input", "search", "control")):
                continue
            # 左侧窄轨道上的纵向图标属于侧栏，不能把上栏向下拉长。
            narrow_left_icon = (
                "menu" not in role
                and bbox["x"] + bbox["w"] <= max(72, round(width * 0.12))
                and bbox["y"] >= max(56, round(height * 0.06))
            )
            if not narrow_left_icon:
                evidence_boxes.append(bbox)
    text_limit = min(top_limit, max(128, round(height * 0.12)))
    for item in _screen_map_texts(result):
        if not isinstance(item, dict):
            continue
        bbox = _normalize_map_bbox(item.get("bbox"))
        if bbox and bbox["y"] < text_limit:
            evidence_boxes.append(bbox)
    if evidence_boxes:
        evidence_bottom = max(box["y"] + box["h"] for box in evidence_boxes)
        return min(height, max(56, evidence_bottom + 8))
    return min(height, max(72, round(height * 0.10)))


def _application_bottom_bar_top(result: dict[str, Any], *, height: int) -> int | None:
    model_io = result.get("model_io") if isinstance(result.get("model_io"), dict) else {}
    raw_response = model_io.get("raw_response") if isinstance(model_io.get("raw_response"), dict) else {}
    model_json = raw_response.get("model_json") if isinstance(raw_response.get("model_json"), dict) else {}
    candidates: list[int] = []
    for item in _as_list(model_json.get("regions")):
        if not isinstance(item, dict):
            continue
        role = " ".join(str(item.get(key) or "") for key in ("role", "label", "region_id")).casefold()
        if not any(token in role for token in ("status_bar", "status bar", "bottom_bar", "bottom bar", "footer")):
            continue
        diagonal = item.get("diagonal") if isinstance(item.get("diagonal"), dict) else {}
        top = int(_number(diagonal.get("y1")) or 0)
        if top >= round(height * 0.70):
            candidates.append(top)
    return min(candidates) if candidates else None


def _screen_map_section(section_id: str, label: str, role: str, description: str, bbox: dict[str, int], result: dict[str, Any]) -> dict[str, Any]:
    texts = _texts_in_bbox(_screen_map_texts(result), bbox)
    return {
        "contract_version": "screen_map_section_v1",
        "section_id": section_id,
        "label": label,
        "role": role,
        "description": description,
        "bbox": bbox,
        "text_count": len(texts),
        "text_sample": [_first_compact_text(item.get("text")) for item in texts[:10] if _first_compact_text(item.get("text"))],
    }


def _floating_overlay_section(result: dict[str, Any], *, width: int, height: int) -> dict[str, Any] | None:
    texts = _screen_map_texts(result)
    bottom_right = []
    for text in texts:
        bbox = _normalize_map_bbox(text.get("bbox"))
        if not bbox:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if cx > width * 0.72 and cy > height * 0.65:
            label = str(text.get("text") or "")
            if label and any(token in label.casefold() for token in ["video", "help", "帮助", "房间", "密码", "join", "加入"]):
                bottom_right.append(text)
    if not bottom_right:
        return None
    bbox = _bbox_union([_normalize_map_bbox(item.get("bbox")) for item in bottom_right])
    if not bbox:
        return None
    padded = _pad_bbox(bbox, pad=28, max_width=width, max_height=height)
    return _screen_map_section(
        "floating_overlay",
        "Floating overlay",
        "overlay",
        "Floating widget or overlay above the page content.",
        padded,
        result,
    )


def _screen_map_text_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, text_item in enumerate(_screen_map_texts(result)):
        if not isinstance(text_item, dict):
            continue
        label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        confidence = _bounded_float(text_item.get("confidence"))
        if not label or not bbox:
            continue
        section_id = _section_id_for_bbox(bbox, sections)
        role = _ocr_text_candidate_role(label, bbox, section_id=section_id)
        if not role:
            continue
        min_confidence = 0.5 if section_id in {"page_header", "top_bar"} else (0.6 if len(label) <= 4 else 0.72)
        if confidence is not None and confidence < min_confidence:
            continue
        candidates.append(
            {
                "id": f"ocr_{text_item.get('id') or index}",
                "text_id": text_item.get("id"),
                "label": label,
                "type": role,
                "bbox": bbox,
                "click_point": _normalize_map_point(None, bbox),
                "confidence": confidence,
                "interaction_policy": {
                    "allowed": True if role in {"button", "text_action", "nav_text_action"} else None,
                    "reasons": ["ocr_text_candidate"],
                },
                "verification_hints": {"expected_changes": [_expected_effect_for_ocr_text(label, role)]},
                "evidence_level": "ocr_text_only",
                "screen_map_rule": (
                    "more_text_is_button"
                    if _looks_like_more_button_text(label)
                    else ("header_text_is_button" if section_id in {"page_header", "top_bar"} else "ocr_action_text")
                ),
            }
        )
    return candidates


def _screen_map_texts(result: dict[str, Any]) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    seen: set[str] = set()
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    for source in (result.get("texts"), screen_reading.get("texts")):
        for item in _as_list(source):
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("text") or "") + "|" + str(item.get("bbox") or "")
            if key in seen:
                continue
            seen.add(key)
            texts.append(item)
    return texts


def _normalize_ocr_candidate_label(label: str) -> str:
    return str(label or "").strip().strip("·•・-—→ ").strip()


def _ocr_text_candidate_role(label: str, bbox: dict[str, int], *, section_id: str | None = None) -> str | None:
    text = label.strip()
    lowered = text.casefold()
    if section_id == "top_bar":
        if _screen_map_text_is_noise(text, allow_short=True):
            return None
        if len(text) <= 1:
            return None
        if sum(1 for char in text if char.isalnum()) <= 1 and len(text) <= 3:
            return None
        digit_count = sum(1 for char in text if char.isdigit())
        alpha_count = sum(1 for char in text if char.isalpha())
        if digit_count and digit_count >= max(1, alpha_count):
            return None
        return "nav_text_action"
    if bbox["y"] < 90:
        return None
    if section_id == "page_header":
        if _screen_map_text_is_noise(text, allow_short=True):
            return None
        if _header_ocr_text_is_noise(text, bbox):
            return None
        return "nav_text_action"
    if bbox["y"] < 180 and ("." in text or "mousetester" in lowered):
        return None
    if _looks_like_more_button_text(text):
        return "button"
    if len(text) > 24:
        return None
    if any(mark in text for mark in ["、", "，", ","]) and not text.startswith(("点击", "立即")):
        return None
    if "峰值" in text or "成功次数" in text or "上次间隔" in text:
        return None
    action_terms = [
        "click",
        "start",
        "open",
        "apply",
        "test",
        "reset",
        "join",
        "点击",
        "开始",
        "启动",
        "停止",
        "测试",
        "重置",
        "左键",
        "中键",
        "右键",
        "前进",
        "后退",
        "加入",
        "参与",
    ]
    card_terms = [
        "dpi",
        "cps",
        "hz",
        "回报率",
        "双击",
        "按键",
        "滚轮",
        "平滑度",
        "灵敏度",
        "键盘",
        "白噪音",
    ]
    if any(term in lowered or term in text for term in action_terms):
        return "nav_text_action" if bbox["y"] < 180 else "text_action"
    if bbox["y"] >= 250 and any(term in lowered or term in text for term in card_terms):
        return "content_card"
    return None


def _header_ocr_text_is_noise(text: str, bbox: dict[str, int]) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    known_short_nav = {"home", "world", "local", "sports", "health", "science", "for you", "中国", "全球"}
    if lowered in known_short_nav or value in known_short_nav:
        return False
    alnum_count = sum(1 for char in value if char.isalnum())
    alpha_count = sum(1 for char in value if char.isalpha())
    digit_count = sum(1 for char in value if char.isdigit())
    # Top toolbar OCR often turns icons, avatars, extension badges, and the search icon into tiny text.
    if bbox.get("y", 0) < 130:
        if len(value) <= 3:
            return True
        if digit_count and digit_count >= alpha_count:
            return True
    if len(value) <= 2 and value not in known_short_nav:
        return True
    if alnum_count <= 1 and len(value) <= 3:
        return True
    if digit_count and digit_count >= max(1, alpha_count):
        return True
    return False


def _screen_map_text_is_noise(text: str, *, allow_short: bool = False) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    if "://" in lowered or lowered.startswith("http"):
        return True
    if len(value) == 1 and not allow_short:
        return True
    if len(value) == 1 and allow_short and not value.isalnum():
        return True
    if all(not char.isalnum() for char in value):
        return True
    return False


def _screen_map_card_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    text_items = _screen_map_texts(result)
    section_by_id = {str(section.get("section_id")): section for section in sections if isinstance(section, dict)}
    for section_id in ("main_content", "right_sidebar", "promo_strip", "lower_content", "primary_area", "bottom_bar"):
        section = section_by_id.get(section_id)
        section_bbox = _normalize_map_bbox((section or {}).get("bbox"))
        if not section_bbox:
            continue
        section_texts = _texts_in_bbox(text_items, section_bbox)
        seed_boxes = [
            bbox
            for item in section_texts
            if (bbox := _normalize_map_bbox(item.get("bbox")))
            and _is_card_seed_label(
                _normalize_ocr_candidate_label(_first_compact_text(item.get("text"))),
                section_id=section_id,
                bbox=bbox,
            )
        ]
        used_centers: list[dict[str, int]] = []
        for index, text_item in enumerate(section_texts):
            seed_bbox = _normalize_map_bbox(text_item.get("bbox"))
            label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
            if not seed_bbox or not _is_card_seed_label(label, section_id=section_id, bbox=seed_bbox):
                continue
            seed_center = _normalize_map_point(None, seed_bbox)
            if seed_center and any(_point_inside_bbox(seed_center, used) for used in used_centers):
                continue
            card_bbox = _card_bbox_for_seed(section_texts, seed_bbox=seed_bbox, seed_boxes=seed_boxes, section_bbox=section_bbox)
            if not card_bbox:
                continue
            used_centers.append(card_bbox)
            card_texts = _texts_in_bbox(section_texts, card_bbox)
            card_role = (
                "recommendation_item"
                if section_id == "right_sidebar"
                else ("news_card" if section_id == "main_content" else _card_role_for_bbox(card_bbox, section_bbox=section_bbox))
            )
            candidates.append(
                {
                    "id": f"card_{section_id}_{index}",
                    "label": label,
                    "type": card_role,
                    "section_id": section_id,
                    "bbox": card_bbox,
                    "click_point": _normalize_map_point(None, card_bbox),
                    "confidence": _bounded_float(text_item.get("confidence")) or 0.75,
                    "interaction_policy": {
                        "allowed": None,
                        "reasons": ["card_group_candidate", f"section:{section_id}"],
                    },
                    "verification_hints": {"expected_changes": [f"open or focus the {label} card"]},
                    "evidence_level": "ocr_grouped_card",
                    "text_id": text_item.get("id"),
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "text_sample": [_first_compact_text(item.get("text")) for item in card_texts[:8] if _first_compact_text(item.get("text"))],
                    "text_count": len(card_texts),
                    "children": _card_children_from_texts(card_texts, seed_text_id=text_item.get("id")),
                }
            )
    return candidates


def _is_card_seed_label(label: str, *, section_id: str, bbox: dict[str, int] | None = None) -> bool:
    text = str(label or "").strip()
    if _screen_map_text_is_noise(text):
        return False
    if _looks_like_more_button_text(text):
        return False
    lowered = text.casefold()
    if _is_generic_article_seed_label(text, bbox=bbox, section_id=section_id):
        return True
    if any(text.startswith(prefix) for prefix in ("点击", "检测", "测试鼠标", "请输入", "输入")):
        return False
    if section_id == "promo_strip":
        return len(text) >= 3 and any(term in text or term in lowered for term in ["测试", "工具", "dpi", "cps", "延迟", "灵敏度", "白噪音", "键盘"])
    return any(
        term in text or term in lowered
        for term in [
            "测试",
            "按键",
            "滚轮",
            "回报率",
            "双击",
            "轮询率",
            "平滑度",
            "灵敏度",
            "dpi",
            "cps",
            "hz",
            "键盘",
            "白噪音",
            "建房",
            "加入",
        ]
    )


def _is_generic_article_seed_label(label: str, *, bbox: dict[str, int] | None, section_id: str) -> bool:
    text = str(label or "").strip()
    if section_id in {"page_header", "top_bar"} or _screen_map_text_is_noise(text):
        return False
    if _looks_like_more_button_text(text):
        return False
    lowered = text.casefold()
    if any(token in lowered for token in ["http", "google", "search", "setting", "privacy", "cookie"]):
        return False
    if _looks_like_metadata_text(text):
        return False
    alpha_count = sum(1 for char in text if char.isalpha())
    digit_count = sum(1 for char in text if char.isdigit())
    non_ascii_count = sum(1 for char in text if ord(char) > 127)
    word_count = len([part for part in text.replace("-", " ").split() if part.strip()])
    width = int((bbox or {}).get("w") or 0)
    if digit_count and digit_count >= max(2, alpha_count):
        return False
    if len(text) >= 10 and (non_ascii_count >= 4 or word_count >= 4):
        return True
    if width >= 140 and len(text) >= 8 and (non_ascii_count >= 3 or word_count >= 3):
        return True
    return False


def _looks_like_more_button_text(label: str) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    compact = "".join(char for char in lowered if char.isalnum() or ord(char) > 127)
    if any(token in text for token in ["查看更多", "更多", "显示更多", "加载更多"]):
        return True
    more_phrases = [
        "more",
        "see more",
        "view more",
        "read more",
        "show more",
        "load more",
        "more stories",
        "more news",
        "more headlines",
    ]
    if any(phrase in lowered for phrase in more_phrases):
        return True
    return compact in {"more", "seemore", "viewmore", "readmore", "showmore", "loadmore"}


def _looks_like_metadata_text(label: str) -> bool:
    text = str(label or "").strip()
    lowered = text.casefold()
    if not text:
        return True
    if any(char.isdigit() for char in text):
        time_markers = [
            "ago",
            "hour",
            "hours",
            "minute",
            "minutes",
            "day",
            "days",
            "\u5c0f\u65f6",
            "\u5c0f\u6642",
            "\u5206\u949f",
            "\u5206\u9418",
            "\u524d",
            "\u00b7",
            "\u00c2\u00b7",
            "\u00e5\u00b0\u008f\u00e6\u0097\u00b6",
        ]
        if any(token in lowered for token in time_markers):
            return True
    metadata_tokens = [
        "ago",
        "hour",
        "hours",
        "minute",
        "minutes",
        "today",
        "yesterday",
        "source",
        "author",
        "å°æ¶",
        "åé",
        "å¤©å",
        "ä½è€",
    ]
    if any(token in lowered for token in metadata_tokens):
        return True
    if len(text) <= 14 and any(char.isdigit() for char in text) and not any(char in text for char in "!?？！“”\""):
        return True
    if len(text) <= 12 and sum(1 for char in text if char.isalpha()) <= 2 and any(ord(char) > 127 for char in text):
        return True
    return False


def _card_role_for_bbox(card_bbox: dict[str, int], *, section_bbox: dict[str, int]) -> str:
    center_x = card_bbox["x"] + card_bbox["w"] / 2
    right_threshold = section_bbox["x"] + section_bbox["w"] * 0.58
    if center_x >= right_threshold and card_bbox["w"] <= max(360, section_bbox["w"] * 0.34):
        return "recommendation_item"
    return "news_card"


def _card_children_from_texts(texts: list[dict[str, Any]], *, seed_text_id: Any) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for index, text_item in enumerate(texts[:12]):
        label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not label or not bbox or _screen_map_text_is_noise(label, allow_short=False):
            continue
        role = "title" if text_item.get("id") == seed_text_id else ("metadata" if _looks_like_metadata_text(label) else "text")
        children.append(
            {
                "contract_version": "screen_map_child_v1",
                "child_id": str(text_item.get("id") or f"text_{index}")[:100],
                "role": role,
                "label": label,
                "bbox": bbox,
                "click_point": _normalize_map_point(None, bbox),
                "confidence": _bounded_float(text_item.get("confidence")),
                "source": "ocr_text",
            }
        )
    return children


def _card_bbox_for_seed(
    texts: list[dict[str, Any]],
    *,
    seed_bbox: dict[str, int],
    seed_boxes: list[dict[str, int]],
    section_bbox: dict[str, int],
) -> dict[str, int] | None:
    seed_cx = seed_bbox["x"] + seed_bbox["w"] / 2
    half_width = min(260, max(150, int(section_bbox["w"] * 0.11)))
    x1 = max(section_bbox["x"], int(seed_cx - half_width))
    x2 = min(section_bbox["x"] + section_bbox["w"], int(seed_cx + half_width))
    x1, x2 = _card_column_bounds(seed_bbox=seed_bbox, seed_boxes=seed_boxes, fallback_x1=x1, fallback_x2=x2, section_bbox=section_bbox)
    y1 = max(section_bbox["y"], seed_bbox["y"] - 24)
    y2 = min(section_bbox["y"] + section_bbox["h"], seed_bbox["y"] + max(120, int(section_bbox["h"] * 0.34)))
    candidate_rows: list[dict[str, Any]] = []
    for text_item in texts:
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not bbox:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            candidate_rows.append({"bbox": bbox, "cy": cy})
    candidate_rows.sort(key=lambda item: (item["cy"], item["bbox"]["x"]))
    seed_cy = seed_bbox["y"] + seed_bbox["h"] / 2
    seed_index = next(
        (
            index
            for index, item in enumerate(candidate_rows)
            if _bbox_overlap_area(item["bbox"], seed_bbox) > 0
        ),
        None,
    )
    if seed_index is None:
        candidate_rows.append({"bbox": seed_bbox, "cy": seed_cy})
        candidate_rows.sort(key=lambda item: (item["cy"], item["bbox"]["x"]))
        seed_index = next(index for index, item in enumerate(candidate_rows) if item["bbox"] == seed_bbox)
    cluster = [candidate_rows[seed_index]["bbox"]]
    max_gap = 46
    previous_cy = candidate_rows[seed_index]["cy"]
    for item in reversed(candidate_rows[:seed_index]):
        if previous_cy - item["cy"] > max_gap:
            break
        cluster.append(item["bbox"])
        previous_cy = item["cy"]
    previous_cy = candidate_rows[seed_index]["cy"]
    for item in candidate_rows[seed_index + 1 :]:
        if item["cy"] - previous_cy > max_gap:
            break
        cluster.append(item["bbox"])
        previous_cy = item["cy"]
    bbox = _bbox_union(cluster)
    if not bbox:
        return None
    return _pad_bbox(bbox, pad=18, max_width=section_bbox["x"] + section_bbox["w"], max_height=section_bbox["y"] + section_bbox["h"])


def _card_column_bounds(
    *,
    seed_bbox: dict[str, int],
    seed_boxes: list[dict[str, int]],
    fallback_x1: int,
    fallback_x2: int,
    section_bbox: dict[str, int],
) -> tuple[int, int]:
    seed_cx = seed_bbox["x"] + seed_bbox["w"] / 2
    seed_cy = seed_bbox["y"] + seed_bbox["h"] / 2
    row_peers = [
        box
        for box in seed_boxes
        if abs((box["y"] + box["h"] / 2) - seed_cy) <= 80
    ]
    centers = sorted({round(box["x"] + box["w"] / 2) for box in row_peers})
    if len(centers) < 2:
        return fallback_x1, fallback_x2
    center = round(seed_cx)
    left_centers = [item for item in centers if item < center]
    right_centers = [item for item in centers if item > center]
    left_bound = section_bbox["x"]
    right_bound = section_bbox["x"] + section_bbox["w"]
    if left_centers:
        left_bound = max(left_bound, int(round((left_centers[-1] + center) / 2)))
    if right_centers:
        right_bound = min(right_bound, int(round((right_centers[0] + center) / 2)))
    return max(fallback_x1, left_bound), min(fallback_x2, right_bound)


def _expected_effect_for_ocr_text(label: str, role: str) -> str:
    if role == "content_card":
        return f"open or focus the {label} section"
    return f"activate {label}"


def _screen_map_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[tuple[str, list[Any]]] = []
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    ui = screen_reading.get("ui") if isinstance(screen_reading.get("ui"), dict) else {}
    sources.append(("screen_reading.ui.elements", _as_list(ui.get("elements"))))
    sources.append(("screen_reading.ui.icon_candidates", _as_list(ui.get("icon_candidates"))))
    sources.append(("screen_reading.ui_elements", _as_list(screen_reading.get("ui_elements"))))
    sources.append(("top_level.ui.elements", _as_list(result.get("ui", {}).get("elements") if isinstance(result.get("ui"), dict) else None)))
    sources.append(("top_level.ui.icon_candidates", _as_list(result.get("ui", {}).get("icon_candidates") if isinstance(result.get("ui"), dict) else None)))
    sources.append(("top_level.ui_elements", _as_list(result.get("ui_elements"))))
    sources.append(("top_level.elements", _as_list(result.get("elements"))))
    sources.append(("top_level.controls", _as_list(result.get("controls"))))
    sources.append(("ocr_card_groups", _screen_map_card_candidates(result, sections=sections)))
    sources.append(("ocr_text_actions", _screen_map_text_candidates(result, sections=sections)))

    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for source_name, items in sources:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            candidate = _screen_map_candidate(item, source=source_name, index=index, sections=sections)
            if candidate is None:
                continue
            dedupe_key = f"{candidate['label']}|{candidate.get('bbox')}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)
    return candidates[:80]


def _screen_map_candidate(item: dict[str, Any], *, source: str, index: int, sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    label = _first_compact_text(
        item.get("label"),
        item.get("text"),
        item.get("name"),
        item.get("title"),
        item.get("description"),
        item.get("role_guess"),
        item.get("role"),
        item.get("type"),
    )
    label = _normalize_ocr_candidate_label(label)
    if not label:
        return None
    bbox = _normalize_map_bbox(item.get("bbox") or item.get("bounding_box") or item.get("bounds") or item.get("rect") or item.get("region"))
    click_point = _normalize_map_point(item.get("click_point") or item.get("clickPoint"), bbox)
    role = _first_compact_text(item.get("type"), item.get("role_guess"), item.get("role"), item.get("control_type")) or "control"
    policy = _interaction_policy_from_item(item)
    risk_class, risk_reasons = _risk_class_for_candidate(label=label, role=role, policy=policy)
    expected_effect = _expected_effect_from_item(item, role=role)
    candidate_id = str(item.get("id") or item.get("element_id") or item.get("candidate_id") or f"screen_map_{index}")
    return {
        "contract_version": "screen_map_candidate_v1",
        "candidate_id": candidate_id[:100],
        "label": label,
        "role": role,
        "goal_hint": _goal_hint_for_candidate(label=label, role=role),
        "expected_effect": expected_effect,
        "risk_class": risk_class,
        "risk_reasons": risk_reasons,
        "section_id": _first_compact_text(item.get("section_id")) or _section_id_for_bbox(bbox, sections),
        "bbox": bbox,
        "click_point": click_point,
        "confidence": _bounded_float(item.get("confidence")),
        "source": source,
        "source_id": item.get("id") or item.get("element_id") or item.get("candidate_id"),
        "screen_map_rule": item.get("screen_map_rule"),
        "children": _as_list(item.get("children")),
        "evidence": {
            "interaction_policy": policy,
            "coordinate_confidence": item.get("coordinate_confidence"),
            "evidence_level": item.get("evidence_level"),
            "memory_key": item.get("memory_key"),
            "source_text_id": item.get("text_id"),
            "screen_map_rule": item.get("screen_map_rule"),
        },
    }


def _interaction_policy_from_item(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    policy = evidence.get("interaction_policy") if isinstance(evidence.get("interaction_policy"), dict) else {}
    if not policy and isinstance(item.get("interaction_policy"), dict):
        policy = item["interaction_policy"]
    return dict(policy)


def _risk_class_for_candidate(*, label: str, role: str, policy: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = [str(item) for item in _as_list(policy.get("reasons")) if str(item or "").strip()]
    risk_text = " ".join([label, role, " ".join(reasons), str(policy.get("zone_type") or "")]).casefold()
    if _looks_like_high_risk_action_text(risk_text):
        return "requires_user_confirmation", sorted(set([*reasons, "potential_side_effect_action"]))
    if policy.get("allowed") is False:
        if _looks_like_low_risk_navigation_candidate(label=label, role=role, extra_text=risk_text):
            return "safe_click_allowed", sorted(set([*reasons, "low_risk_navigation_policy_relaxed"]))
        return "blocked", sorted(set(reasons or ["interaction_policy_blocked"]))
    if policy.get("allowed") is True:
        return "safe_click_allowed", sorted(set(reasons))
    if any(token in str(role).casefold() for token in ["input", "textbox", "search"]):
        return "safe_click_allowed", sorted(set(reasons))
    return "safe_dry_run_only", sorted(set(reasons or ["requires_precise_location_before_click"]))


def _looks_like_high_risk_action_text(text: str) -> bool:
    normalized = str(text or "").casefold()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if "pay" in tokens and "filter" in tokens and not any(
        phrase in normalized
        for phrase in [
            "pay now",
            "pay invoice",
            "make payment",
            "payment",
            "checkout",
            "purchase",
        ]
    ):
        return False
    dangerous_phrases = [
        "quick apply",
        "submit application",
        "send application",
        "complete application",
        "confirm application",
        "make payment",
        "pay now",
        "pay invoice",
        "save changes",
        "close window",
        "删除",
        "移除",
        "支付",
        "购买",
        "发送",
        "提交",
        "申请",
        "授权",
        "关闭窗口",
    ]
    if any(term in normalized for term in dangerous_phrases):
        return True
    dangerous_tokens = {"delete", "remove", "purchase", "send", "submit", "apply", "authorize", "permission", "upload", "pay", "payment"}
    return bool(tokens & dangerous_tokens)


def _looks_like_low_risk_navigation_candidate(*, label: str, role: str, extra_text: str = "") -> bool:
    text = " ".join([label, role, extra_text]).casefold()
    role_tokens = [
        "card",
        "news_card",
        "job_card",
        "result",
        "search_result",
        "link",
        "title",
        "row",
        "list_item",
        "article",
        "detail",
    ]
    effect_tokens = [
        "open",
        "view",
        "read",
        "detail",
        "article",
        "job",
        "card",
        "result",
        "recommended",
        "recommendation",
        "listing",
    ]
    return any(token in text for token in role_tokens) or any(token in text for token in effect_tokens)


def _expected_effect_from_item(item: dict[str, Any], *, role: str) -> str:
    verification = item.get("verification_hints") if isinstance(item.get("verification_hints"), dict) else {}
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    evidence_verification = evidence.get("verification_hints") if isinstance(evidence.get("verification_hints"), dict) else {}
    for value in (
        item.get("expected_effect"),
        item.get("possible_navigation"),
        item.get("possible_destinations"),
        item.get("action"),
        item.get("interaction_type"),
        verification.get("expected_changes"),
        evidence_verification.get("expected_changes"),
    ):
        text = _first_compact_text(value)
        if text:
            return text
    role_text = str(role or "").casefold()
    if any(token in role_text for token in ["input", "textbox", "search"]):
        return "focus or edit input"
    return "click may change the current interface"


def _goal_hint_for_candidate(*, label: str, role: str) -> str:
    role_text = str(role or "control").replace("_", " ")
    return f"{role_text}: {label}"[:120]


def _section_id_for_bbox(bbox: dict[str, int] | None, sections: list[dict[str, Any]]) -> str | None:
    if not bbox:
        return None
    cx = bbox["x"] + bbox["w"] / 2
    cy = bbox["y"] + bbox["h"] / 2
    best_section = None
    best_score = -1
    for section in sections:
        section_bbox = _normalize_map_bbox(section.get("bbox"))
        if not section_bbox:
            continue
        inside = (
            section_bbox["x"] <= cx <= section_bbox["x"] + section_bbox["w"]
            and section_bbox["y"] <= cy <= section_bbox["y"] + section_bbox["h"]
        )
        overlap = _bbox_overlap_area(bbox, section_bbox)
        score = overlap + (1_000_000 if inside else 0)
        if score > best_score:
            best_score = score
            best_section = section
    return str(best_section.get("section_id")) if best_section else None


def _max_text_edge(result: dict[str, Any], *, axis: str) -> int | None:
    edge = 0
    for text in _screen_map_texts(result):
        bbox = _normalize_map_bbox(text.get("bbox"))
        if not bbox:
            continue
        if axis == "x":
            edge = max(edge, bbox["x"] + bbox["w"])
        else:
            edge = max(edge, bbox["y"] + bbox["h"])
    return edge or None


def _texts_in_bbox(texts: list[dict[str, Any]], bbox: dict[str, int]) -> list[dict[str, Any]]:
    selected = []
    for text in texts:
        text_bbox = _normalize_map_bbox(text.get("bbox"))
        if not text_bbox:
            continue
        cx = text_bbox["x"] + text_bbox["w"] / 2
        cy = text_bbox["y"] + text_bbox["h"] / 2
        if bbox["x"] <= cx <= bbox["x"] + bbox["w"] and bbox["y"] <= cy <= bbox["y"] + bbox["h"]:
            selected.append(text)
    selected.sort(key=lambda item: ((_normalize_map_bbox(item.get("bbox")) or {}).get("y", 0), (_normalize_map_bbox(item.get("bbox")) or {}).get("x", 0)))
    return selected


def _bbox_union(boxes: list[dict[str, int] | None]) -> dict[str, int] | None:
    valid = [box for box in boxes if box]
    if not valid:
        return None
    x1 = min(box["x"] for box in valid)
    y1 = min(box["y"] for box in valid)
    x2 = max(box["x"] + box["w"] for box in valid)
    y2 = max(box["y"] + box["h"] for box in valid)
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _pad_bbox(bbox: dict[str, int], *, pad: int, max_width: int, max_height: int) -> dict[str, int]:
    x = max(0, bbox["x"] - pad)
    y = max(0, bbox["y"] - pad)
    x2 = min(max_width, bbox["x"] + bbox["w"] + pad)
    y2 = min(max_height, bbox["y"] + bbox["h"] + pad)
    return {"x": x, "y": y, "w": max(1, x2 - x), "h": max(1, y2 - y)}


def _bbox_overlap_area(a: dict[str, int], b: dict[str, int]) -> int:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _screen_state_signature(*, app_name: str, state_hint: str, screen_summary: str, image_path: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [str(item.get("label") or "")[:60] for item in candidates[:20]]
    source = "|".join([app_name or "", state_hint or "", screen_summary or "", image_path or "", *labels])
    digest = hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return {
        "state_id": f"state_{digest}",
        "app_name": app_name,
        "state_hint": state_hint,
        "screen_summary_hash": hashlib.sha256(str(screen_summary or "").encode("utf-8", errors="ignore")).hexdigest()[:16],
        "image_path": image_path,
        "candidate_label_sample": labels[:12],
        "candidate_count": len(candidates),
    }


def _normalize_map_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _number(value.get("x", value.get("left", value.get("x1"))))
    y = _number(value.get("y", value.get("top", value.get("y1"))))
    right = _number(value.get("right", value.get("x2")))
    bottom = _number(value.get("bottom", value.get("y2")))
    width = _number(value.get("w", value.get("width")))
    height = _number(value.get("h", value.get("height")))
    if width is None and right is not None and x is not None:
        width = right - x
    if height is None and bottom is not None and y is not None:
        height = bottom - y
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    return {"x": int(round(x)), "y": int(round(y)), "w": int(round(width)), "h": int(round(height))}


def _normalize_map_point(value: Any, bbox: dict[str, int] | None) -> dict[str, int] | None:
    if isinstance(value, dict):
        x = _number(value.get("x"))
        y = _number(value.get("y"))
        if x is not None and y is not None:
            return {"x": int(round(x)), "y": int(round(y))}
    if bbox:
        return {"x": int(round(bbox["x"] + bbox["w"] / 2)), "y": int(round(bbox["y"] + bbox["h"] / 2))}
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _bounded_float(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(max(0.0, min(1.0, number)), 4)


def _first_compact_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            text = "; ".join(str(item).strip() for item in value if str(item or "").strip())
        else:
            text = str(value or "").strip()
        text = " ".join(text.split())
        if text:
            return text[:160]
    return ""


def _point_inside_bbox(point: dict[str, int] | None, bbox: dict[str, int] | None) -> bool:
    if not point or not bbox:
        return False
    x = int(point.get("x", 0))
    y = int(point.get("y", 0))
    return bbox["x"] <= x <= bbox["x"] + bbox["w"] and bbox["y"] <= y <= bbox["y"] + bbox["h"]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def suggested_state_hint_from_observation(result: dict[str, Any]) -> str:
    return _suggested_state_hint_from_observation(result)


def build_observation_screen_map(
    result: dict[str, Any],
    *,
    task: ObserveScreenTaskInput,
    image_path: str,
) -> dict[str, Any]:
    return _build_screen_map_from_observation(
        result,
        request=task,
        image_path=image_path,
    )
