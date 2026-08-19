from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.learn.recognition.bbox_alignment import bbox_numbers, bbox_overlap, cross_evidence_overlap_is_acceptable
from app.learn.recognition.contracts import build_inventory_item, build_parser_candidate_evidence


def parse_existing_evidence_to_inventory(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    image_size = _image_size_from_bundle(bundle)
    items: list[dict[str, Any]] = []
    items.extend(_parse_ocr_texts(sources.get("ocr") if isinstance(sources.get("ocr"), dict) else {}))
    items.extend(_parse_uia_controls(sources.get("uia") if isinstance(sources.get("uia"), dict) else {}))
    items.extend(_parse_omniparser_elements(sources.get("omniparser") if isinstance(sources.get("omniparser"), dict) else {}, image_size))
    items.extend(_parse_vision_regions(sources.get("vision") if isinstance(sources.get("vision"), dict) else {}, image_size))
    items.extend(_parse_calibrated_targets(sources.get("calibrated_targets") if isinstance(sources.get("calibrated_targets"), dict) else {}))
    items.extend(_parse_execute_candidate_result(sources.get("execute_candidate_result") if isinstance(sources.get("execute_candidate_result"), dict) else {}))
    _attach_cross_evidence(items)
    _attach_parser_candidate_contract(items, bundle=bundle, image_size=image_size)
    return items


def _parse_ocr_texts(source: dict[str, Any]) -> list[dict[str, Any]]:
    texts = source.get("texts")
    if not isinstance(texts, list):
        texts = source.get("anchors") if isinstance(source.get("anchors"), list) else []
    items: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        if not isinstance(text, dict):
            continue
        label = _first_text(text.get("text"), text.get("label"), text.get("name"))
        if not label:
            continue
        item_id = _first_text(text.get("id"), text.get("text_id"), f"ocr_text_{index + 1}")
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type="readable",
                role="text",
                bbox=_bbox_from_item(text),
                source_evidence=["ocr"],
                evidence_level="ocr_text_only",
                interactable_evidence={},
                click_candidate=False,
                metadata={"source": "ocr"},
            )
        )
    return items


def _parse_uia_controls(source: dict[str, Any]) -> list[dict[str, Any]]:
    controls = source.get("controls")
    if not isinstance(controls, list):
        controls = source.get("elements") if isinstance(source.get("elements"), list) else []
    items: list[dict[str, Any]] = []
    for index, control in enumerate(controls):
        if not isinstance(control, dict):
            continue
        label = _first_text(control.get("name"), control.get("label"), control.get("text"), control.get("automation_id"))
        if not label:
            continue
        patterns = [str(item) for item in control.get("patterns", [])] if isinstance(control.get("patterns"), list) else []
        control_type = _first_text(control.get("control_type"), control.get("type"), control.get("role"))
        invokable = any(item.casefold() in {"invoke", "selectionitem", "expandcollapse", "toggle", "value"} for item in patterns)
        item_type = "form_field" if _looks_like_input_control(control_type) else ("actionable" if invokable else "readable")
        item_id = _first_text(control.get("id"), control.get("control_id"), control.get("automation_id"), f"uia_control_{index + 1}")
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type=item_type,
                role=_role_from_uia_control(control_type),
                bbox=_bbox_from_item(control),
                source_evidence=["uia"],
                evidence_level="uia_control",
                interactable_evidence={"uia_invokable": invokable},
                click_candidate=False,
                metadata={"source": "uia", "patterns": patterns, "control_type": control_type},
            )
        )
    return items


def _parse_omniparser_elements(source: dict[str, Any], image_size: dict[str, int]) -> list[dict[str, Any]]:
    elements = source.get("parsed_content_list")
    if not isinstance(elements, list):
        elements = source.get("elements") if isinstance(source.get("elements"), list) else []
    items: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        label = _first_text(element.get("content"), element.get("label"), element.get("text"), element.get("name"), element.get("id"))
        if not label:
            continue
        role = _first_text(element.get("role"), element.get("type"), "element")
        interactable = bool(element.get("interactivity") or element.get("interactable") or element.get("clickable"))
        item_id = _first_text(element.get("id"), element.get("element_id"), f"omniparser_element_{index + 1}")
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type=_item_type_from_omniparser(role, interactable),
                role=_role_from_omniparser(role),
                bbox=_bbox_from_item(element, image_size=image_size),
                source_evidence=["omniparser"],
                evidence_level="omniparser_interactable" if interactable else "omniparser_element",
                interactable_evidence={"omniparser_interactable": interactable},
                click_candidate=False,
                metadata={
                    "source": "omniparser",
                    "provider_source": element.get("source"),
                    "raw_type": role,
                },
            )
        )
    return items


def _parse_vision_regions(source: dict[str, Any], image_size: dict[str, int]) -> list[dict[str, Any]]:
    regions = source.get("regions")
    if not isinstance(regions, list):
        regions = source.get("candidates") if isinstance(source.get("candidates"), list) else []
    items: list[dict[str, Any]] = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            continue
        label = _first_text(region.get("label"), region.get("text"), region.get("name"), region.get("region_id"))
        if not label:
            continue
        item_id = _first_text(region.get("id"), region.get("region_id"), f"vision_region_{index + 1}")
        children = region.get("children") if isinstance(region.get("children"), list) else []
        child_text_lines = [
            str(child.get("label") or child.get("text") or "").strip()
            for child in children
            if isinstance(child, dict) and str(child.get("label") or child.get("text") or "").strip()
        ]
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type="layout",
                role=_first_text(region.get("role"), region.get("type"), "semantic_region"),
                bbox=_bbox_from_item(region, image_size=image_size),
                source_evidence=["vision"],
                evidence_level="semantic_region_only",
                interactable_evidence={},
                click_candidate=False,
                metadata={
                    "source": "vision",
                    "description": _first_text(region.get("description"), region.get("visual_description")),
                    "text_lines": [str(line) for line in region.get("text_lines", [])]
                    if isinstance(region.get("text_lines"), list)
                    else child_text_lines,
                    "children": children,
                    "boundary_definition": _first_text(region.get("boundary_definition"), region.get("boundary")),
                    "clickable_area_hint": _first_text(region.get("clickable_area_hint"), region.get("interaction_hint")),
                },
            )
        )
    return items


def _parse_calibrated_targets(source: dict[str, Any]) -> list[dict[str, Any]]:
    targets = source.get("targets")
    if not isinstance(targets, list):
        targets = source.get("items") if isinstance(source.get("items"), list) else []
    items: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            continue
        label = _first_text(target.get("label"), target.get("text"), target.get("name"), target.get("candidate_id"))
        if not label:
            continue
        role = _first_text(target.get("role"), target.get("type"), "actionable")
        validation = target.get("coordinate_validation") if isinstance(target.get("coordinate_validation"), dict) else {}
        validated = _is_valid_coordinate_validation(validation)
        item_id = _first_text(target.get("item_id"), target.get("candidate_id"), target.get("id"), f"calibrated_target_{index + 1}")
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type=_item_type_from_calibrated_role(role),
                role=_role_from_calibrated_target(role),
                bbox=_bbox_from_item(target),
                source_evidence=["calibrated_target"],
                evidence_level="calibrated_target" if validated else "calibrated_target_unverified",
                interactable_evidence={
                    "calibrated_target_validated": validated,
                    "vision_claim": bool(target.get("source") or target.get("coordinate_source")),
                },
                click_candidate=False,
                metadata={
                    "source": "calibrated_target",
                    "source_trace_path": source.get("source_trace_path"),
                    "source_overlay_path": source.get("source_overlay_path"),
                    "coordinate_validation": validation,
                    "click_point": target.get("click_point") if isinstance(target.get("click_point"), dict) else {},
                    "coordinate_source": target.get("coordinate_source"),
                    "location_status": target.get("location_status"),
                    "confidence": target.get("confidence"),
                },
            )
        )
    return items


def _parse_execute_candidate_result(source: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = source.get("candidates")
    if not isinstance(candidates, list):
        candidates = source.get("items") if isinstance(source.get("items"), list) else []
    items: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        element = candidate.get("element") if isinstance(candidate.get("element"), dict) else candidate
        label = _first_text(element.get("label"), element.get("text"), candidate.get("label"), candidate.get("candidate_id"))
        if not label:
            continue
        role = _first_text(element.get("role"), candidate.get("role"), "actionable")
        item_id = _first_text(element.get("element_id"), candidate.get("element_id"), candidate.get("candidate_id"), f"execute_candidate_{index + 1}")
        eligible = bool(candidate.get("eligible", True))
        items.append(
            build_inventory_item(
                item_id=item_id,
                label=label,
                item_type=_item_type_from_execute_role(role),
                role=_role_from_execute_candidate(role),
                bbox=_bbox_from_item(element),
                source_evidence=["execute_candidate_result"],
                evidence_level="execute_candidate_result" if eligible else "execute_candidate_result_rejected",
                interactable_evidence={
                    "execute_candidate_ranked": eligible,
                    "execute_candidate_score": candidate.get("score"),
                },
                click_candidate=False,
                metadata={
                    "source": "execute_candidate_result",
                    "source_trace_path": source.get("source_trace_path"),
                    "candidate_id": candidate.get("candidate_id"),
                    "rank": candidate.get("rank"),
                    "reasons": candidate.get("reasons") if isinstance(candidate.get("reasons"), list) else [],
                    "interaction_type": element.get("interaction_type"),
                    "click_point": element.get("click_point") if isinstance(element.get("click_point"), dict) else {},
                },
            )
        )
    return items


def _bbox_from_item(item: dict[str, Any], *, image_size: dict[str, int] | None = None) -> dict[str, Any]:
    value = item.get("bbox") or item.get("bounding_box") or item.get("bounds") or item.get("rect") or {}
    if isinstance(value, dict) and value:
        return value
    if isinstance(value, list) and len(value) >= 4:
        return _bbox_from_sequence(value, image_size=image_size or {})
    diagonal = item.get("diagonal")
    if isinstance(diagonal, dict):
        x1 = _int_or_zero(diagonal.get("x1"))
        y1 = _int_or_zero(diagonal.get("y1"))
        x2 = _int_or_zero(diagonal.get("x2"))
        y2 = _int_or_zero(diagonal.get("y2"))
        return {"x": min(x1, x2), "y": min(y1, y2), "w": abs(x2 - x1), "h": abs(y2 - y1)}
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _image_size_from_bundle(bundle: dict[str, Any]) -> dict[str, int]:
    for key in ("screen_size", "viewport_size", "image_size", "source_image_size"):
        value = bundle.get(key)
        if isinstance(value, dict):
            return {"width": _int_or_zero(value.get("width")), "height": _int_or_zero(value.get("height"))}
    return {"width": 0, "height": 0}


def _attach_parser_candidate_contract(items: list[dict[str, Any]], *, bundle: dict[str, Any], image_size: dict[str, int]) -> None:
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), dict) else {}
    omniparser = sources.get("omniparser") if isinstance(sources.get("omniparser"), dict) else {}
    current_screenshot_sha256 = _screenshot_sha256_from_bundle(bundle)
    current_capture_id = _first_text(bundle.get("capture_id"))
    for item in items:
        if not isinstance(item, dict):
            continue
        item_sources = item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []
        is_omniparser = "omniparser" in {str(value).casefold() for value in item_sources}
        source = omniparser if is_omniparser else bundle
        source_screenshot_sha256 = _first_text(
            source.get("screenshot_sha256"),
            source.get("image_sha256"),
        )
        source_capture_id = _first_text(source.get("capture_id"))
        source_image_size = (
            source.get("image_size")
            if isinstance(source.get("image_size"), dict)
            else image_size
        )
        stale = bool(source.get("stale") or bundle.get("stale"))
        context = {
            "source_run_id": _first_text(
                source.get("source_run_id"),
                source.get("run_id"),
                bundle.get("source_run_id"),
                bundle.get("run_id"),
                bundle.get("trace_id"),
            ),
            "screenshot_sha256": source_screenshot_sha256,
            "coordinate_space": _first_text(
                source.get("coordinate_space"),
                bundle.get("coordinate_space"),
                "image",
            ),
            "image_size": {
                "width": _int_or_zero(source_image_size.get("width")),
                "height": _int_or_zero(source_image_size.get("height")),
            },
            "window_rect": _window_rect_from_bundle(bundle),
            "raw_payload_path": _first_text(
                source.get("raw_payload_path"),
                bundle.get("raw_payload_path"),
                bundle.get("observe_bundle_path"),
            ),
            "capture_time": _first_text(source.get("capture_time"), bundle.get("capture_time"), bundle.get("timestamp")),
            "stale": stale,
            "same_screenshot": (
                bool(current_screenshot_sha256)
                and bool(current_capture_id)
                and source_screenshot_sha256 == current_screenshot_sha256
                and source_capture_id == current_capture_id
                and not stale
            ),
        }
        candidate = build_parser_candidate_evidence(item=item, source_context=context)
        candidate["capture_id"] = source_capture_id
        candidate["provider"] = _first_text(
            source.get("provider"),
            "omniparser" if is_omniparser else _candidate_provider(item_sources),
        )
        candidate["model_revision"] = _first_text(
            source.get("model_revision"),
            source.get("provider_model_revision"),
        )
        candidate["profile_id"] = _first_text(source.get("profile_id"))
        candidate["provenance"] = deepcopy(
            source.get("provenance")
            if isinstance(source.get("provenance"), dict)
            else {}
        )
        freshness_block = _parser_candidate_freshness_block(candidate)
        if freshness_block:
            candidate["review_only"] = True
            candidate["grounding_eligible"] = False
            candidate["grounding_block_reason"] = freshness_block
        item["parser_candidate"] = candidate


def _parser_candidate_freshness_block(candidate: dict[str, Any]) -> str:
    freshness = (
        candidate.get("freshness")
        if isinstance(candidate.get("freshness"), dict)
        else {}
    )
    if bool(freshness.get("stale")):
        return "parser_candidate_stale"
    if not (
        _first_text(candidate.get("screenshot_sha256"))
        and _first_text(candidate.get("capture_id"))
        and _first_text(candidate.get("source_run_id"))
    ):
        return "parser_candidate_missing_current_screenshot_identity"
    if not bool(freshness.get("same_screenshot")):
        return "parser_candidate_screenshot_mismatch"
    image_size = candidate.get("image_size") if isinstance(candidate.get("image_size"), dict) else {}
    if _int_or_zero(image_size.get("width")) <= 0 or _int_or_zero(image_size.get("height")) <= 0:
        return "parser_candidate_invalid_image_size"
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else {}
    x = _int_or_zero(bbox.get("x"))
    y = _int_or_zero(bbox.get("y"))
    width = _int_or_zero(bbox.get("w", bbox.get("width")))
    height = _int_or_zero(bbox.get("h", bbox.get("height")))
    if (
        width <= 0
        or height <= 0
        or x < 0
        or y < 0
        or x + width > _int_or_zero(image_size.get("width"))
        or y + height > _int_or_zero(image_size.get("height"))
    ):
        return "parser_candidate_invalid_bbox"
    if str(candidate.get("source_type") or "").casefold() == "omniparser" and not (
        _first_text(candidate.get("provider"))
        and _first_text(candidate.get("model_revision"))
    ):
        return "parser_candidate_missing_provider_or_model_revision"
    return ""


def _candidate_provider(sources: list[Any]) -> str:
    for source in sources:
        value = str(source or "").strip()
        if value:
            return value
    return "unknown"

def _screenshot_sha256_from_bundle(bundle: dict[str, Any]) -> str:
    screenshot = bundle.get("screenshot") if isinstance(bundle.get("screenshot"), dict) else {}
    return _first_text(
        bundle.get("screenshot_sha256"),
        bundle.get("image_sha256"),
        screenshot.get("sha256"),
    )


def _window_rect_from_bundle(bundle: dict[str, Any]) -> dict[str, int]:
    value = bundle.get("window_rect") if isinstance(bundle.get("window_rect"), dict) else {}
    if not value:
        value = bundle.get("window") if isinstance(bundle.get("window"), dict) else {}
    return {
        "x": _int_or_zero(value.get("x", value.get("left", 0))),
        "y": _int_or_zero(value.get("y", value.get("top", 0))),
        "w": _int_or_zero(value.get("w", value.get("width", 0))),
        "h": _int_or_zero(value.get("h", value.get("height", 0))),
    }


def _bbox_from_sequence(value: list[Any], *, image_size: dict[str, int]) -> dict[str, int]:
    numbers = [_float_or_zero(item) for item in value[:4]]
    width = _int_or_zero(image_size.get("width"))
    height = _int_or_zero(image_size.get("height"))
    if width > 0 and height > 0 and all(0 <= item <= 1 for item in numbers):
        x1, y1, x2, y2 = numbers
        x1 *= width
        x2 *= width
        y1 *= height
        y2 *= height
    else:
        x1, y1, x2, y2 = numbers
    return {
        "x": _int_or_zero(min(x1, x2)),
        "y": _int_or_zero(min(y1, y2)),
        "w": max(0, _int_or_zero(abs(x2 - x1))),
        "h": max(0, _int_or_zero(abs(y2 - y1))),
    }


def _item_type_from_omniparser(role: str, interactable: bool) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "form_field"
    if interactable:
        return "actionable"
    return "readable" if text == "text" else "layout"


def _role_from_omniparser(role: str) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "input"
    if "button" in text:
        return "button"
    if "icon" in text:
        return "icon_button"
    if "text" in text:
        return "text"
    return text or "element"


def _looks_like_input_control(value: str) -> bool:
    text = str(value or "").casefold()
    return any(token in text for token in ("edit", "input", "textbox", "textarea", "combo", "document"))


def _item_type_from_calibrated_role(role: str) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "form_field"
    if any(token in text for token in ("button", "link", "menu", "item", "action")):
        return "actionable"
    return "actionable"


def _role_from_calibrated_target(role: str) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "input"
    if "button" in text:
        return "button"
    if "link" in text:
        return "link"
    if "menu" in text:
        return "menu_item"
    return text or "actionable"


def _item_type_from_execute_role(role: str) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "form_field"
    if any(token in text for token in ("button", "link", "nav", "filter", "menu", "action")):
        return "actionable"
    return "actionable"


def _role_from_execute_candidate(role: str) -> str:
    text = str(role or "").casefold()
    if _looks_like_input_control(text):
        return "input"
    if "button" in text:
        return "button"
    if "link" in text:
        return "link"
    if "nav" in text:
        return "nav_action"
    if "filter" in text:
        return "filter_action"
    if "menu" in text:
        return "menu_item"
    return text or "actionable"


def _is_valid_coordinate_validation(validation: dict[str, Any]) -> bool:
    status = str(validation.get("status") or "").casefold()
    if status and status not in {"valid", "passed", "validated"}:
        return False
    required = ("bbox_present", "click_point_present", "bbox_inside_image", "click_point_inside_image", "click_point_inside_bbox")
    return all(bool(validation.get(key)) for key in required)


def _attach_cross_evidence(items: list[dict[str, Any]]) -> None:
    interactable_items = [item for item in items if _can_support_grounding(item)]
    for item in items:
        if not _is_semantic_only_vision_item(item):
            continue
        match = _best_cross_evidence_match(item, interactable_items)
        if match is None:
            continue
        evidence_item, overlap = match
        item["item_type"] = str(evidence_item.get("item_type") or item.get("item_type") or "actionable")
        item["role"] = str(evidence_item.get("role") or item.get("role") or "actionable")
        item["evidence_level"] = "cross_evidence_grounded"
        item["source_evidence"] = _merged_sources(item.get("source_evidence"), evidence_item.get("source_evidence"))
        evidence = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
        support = evidence_item.get("interactable_evidence") if isinstance(evidence_item.get("interactable_evidence"), dict) else {}
        for key, value in support.items():
            if isinstance(value, bool):
                evidence[key] = bool(evidence.get(key)) or value
            elif value is not None and key not in evidence:
                evidence[key] = value
        evidence["cross_evidence_overlap"] = True
        evidence["vision_claim"] = True
        item["interactable_evidence"] = evidence
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata["cross_evidence"] = {
            "support_item_id": evidence_item.get("item_id"),
            "support_label": evidence_item.get("label"),
            "support_sources": evidence_item.get("source_evidence") if isinstance(evidence_item.get("source_evidence"), list) else [],
            "iou": overlap["iou"],
            "vision_coverage": overlap["vision_coverage"],
            "support_coverage": overlap["support_coverage"],
        }
        item["metadata"] = metadata


def _is_semantic_only_vision_item(item: dict[str, Any]) -> bool:
    sources = item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []
    return "vision" in {str(source).casefold() for source in sources} and str(item.get("evidence_level") or "").casefold() == "semantic_region_only"


def _can_support_grounding(item: dict[str, Any]) -> bool:
    if _is_semantic_only_vision_item(item):
        return False
    if str(item.get("item_type") or "").casefold() not in {"actionable", "form_field"}:
        return False
    evidence = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    return any(
        bool(evidence.get(key))
        for key in (
            "uia_invokable",
            "dom_clickable",
            "omniparser_interactable",
            "calibrated_target_validated",
            "execute_candidate_ranked",
        )
    )


def _best_cross_evidence_match(item: dict[str, Any], support_items: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, float]] | None:
    best: tuple[dict[str, Any], dict[str, float]] | None = None
    best_score = 0.0
    for support_item in support_items:
        overlap = bbox_overlap(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}, support_item.get("bbox") if isinstance(support_item.get("bbox"), dict) else {})
        if not cross_evidence_overlap_is_acceptable(overlap):
            continue
        score = overlap["iou"] + overlap["vision_coverage"] + overlap["support_coverage"]
        if score > best_score:
            best = (support_item, overlap)
            best_score = score
    return best


def _bbox_numbers(value: dict[str, Any]) -> tuple[float, float, float, float]:
    return bbox_numbers(value)


def _merged_sources(primary: Any, secondary: Any) -> list[str]:
    sources: list[str] = []
    for source in list(primary if isinstance(primary, list) else []) + list(secondary if isinstance(secondary, list) else []):
        text = str(source or "").strip()
        if text and text not in sources:
            sources.append(text)
    return sources


def _role_from_uia_control(value: str) -> str:
    text = str(value or "").casefold()
    if _looks_like_input_control(text):
        return "input"
    if "button" in text:
        return "button"
    if "hyperlink" in text or "link" in text:
        return "link"
    if "menu" in text:
        return "menu_item"
    return text or "control"


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
