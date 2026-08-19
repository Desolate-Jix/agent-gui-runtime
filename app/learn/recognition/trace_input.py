from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def observe_bundle_from_trace_result(result: dict[str, Any], *, trace_path: Path) -> dict[str, Any]:
    """把历史或当前 observe trace 统一为学习识别输入。"""

    nested_bundle = result.get("observe_bundle") if isinstance(result.get("observe_bundle"), dict) else {}
    two_stage = (
        result.get("two_stage_understanding")
        if isinstance(result.get("two_stage_understanding"), dict)
        else {}
    )
    if not nested_bundle:
        nested_bundle = (
            two_stage.get("observe_bundle")
            if isinstance(two_stage.get("observe_bundle"), dict)
            else {}
        )
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    if not image_size:
        image_size = nested_bundle.get("image_size") if isinstance(nested_bundle.get("image_size"), dict) else {}
    if not image_size:
        image_size = nested_bundle.get("screen_size") if isinstance(nested_bundle.get("screen_size"), dict) else {}
    bundle = {
        "contract_version": "learn_trace_input_v1",
        "app_name": str(result.get("app_name") or nested_bundle.get("app_name") or "").strip(),
        "image_path": str(
            result.get("image_path")
            or result.get("screenshot_path")
            or nested_bundle.get("image_path")
            or nested_bundle.get("screenshot_path")
            or ""
        ),
        "screen_size": {
            "width": _int(image_size.get("width")),
            "height": _int(image_size.get("height")),
        },
        "capture_id": str(result.get("capture_id") or nested_bundle.get("capture_id") or ""),
        "source_run_id": str(result.get("source_run_id") or nested_bundle.get("source_run_id") or ""),
        "screenshot_sha256": str(
            result.get("screenshot_sha256")
            or result.get("image_sha256")
            or nested_bundle.get("screenshot_sha256")
            or nested_bundle.get("image_sha256")
            or ""
        ),
        "coordinate_space": str(result.get("coordinate_space") or nested_bundle.get("coordinate_space") or ""),
        "source_trace_path": str(trace_path),
    }
    nested_sources = (
        nested_bundle.get("sources")
        if isinstance(nested_bundle.get("sources"), dict)
        else {}
    )
    if nested_sources:
        bundle["sources"] = deepcopy(nested_sources)
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    if not screen_reading:
        screen_reading = (
            nested_bundle.get("screen_reading")
            if isinstance(nested_bundle.get("screen_reading"), dict)
            else {}
        )
    if not screen_reading:
        semantic_keys = (
            "screen_summary",
            "state_guess",
            "interface_classification",
            "ui",
            "ui_elements",
            "modules",
            "relationships",
            "execution_relevance",
            "uncertainties",
            "source_layers",
            "raw_refs",
        )
        screen_reading = {key: deepcopy(result[key]) for key in semantic_keys if key in result}
    if screen_reading:
        bundle["screen_reading"] = screen_reading
    texts = result.get("texts") if isinstance(result.get("texts"), list) else []
    if texts:
        bundle["texts"] = texts
    return bundle


def stage1_inventory_from_trace_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """读取 trace 中的原子证据，不推断或生成旧式栏结构。"""

    items: list[dict[str, Any]] = []
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    nested_bundle = result.get("observe_bundle") if isinstance(result.get("observe_bundle"), dict) else {}
    if not image_size:
        image_size = nested_bundle.get("image_size") if isinstance(nested_bundle.get("image_size"), dict) else {}
    height = _int(image_size.get("height"))
    screen_inventory_value = result.get("screen_inventory")
    screen_inventory = screen_inventory_value if isinstance(screen_inventory_value, dict) else {}
    items.extend(_items_from_observe_screen_inventory(screen_inventory))
    if isinstance(screen_inventory_value, list):
        items.extend(_items_from_screen_inventory_list(screen_inventory_value))
    sources = (
        nested_bundle.get("sources")
        if isinstance(nested_bundle.get("sources"), dict)
        else {}
    )
    items.extend(
        _stage1_items_from_omniparser(
            sources.get("omniparser") if isinstance(sources.get("omniparser"), dict) else {},
            image_size=image_size,
        )
    )
    screen_map = result.get("screen_map") if isinstance(result.get("screen_map"), dict) else {}
    for index, section in enumerate(screen_map.get("sections") if isinstance(screen_map.get("sections"), list) else []):
        if not isinstance(section, dict):
            continue
        items.append(
            {
                "item_id": str(section.get("section_id") or f"section_{index + 1}"),
                "label": str(section.get("label") or section.get("section_id") or f"Section {index + 1}"),
                "role": str(section.get("role") or "structure_region"),
                "item_type": "layout",
                "bbox": _bbox(section.get("bbox")),
                "review_only": True,
                "grounding_eligible": False,
                "source_evidence": ["screen_map_section"],
                "metadata": {
                    "source": "screen_map.sections",
                    "surface_zone": _surface_zone_for_section(section),
                    "description": str(section.get("description") or ""),
                    "text_sample": section.get("text_sample") if isinstance(section.get("text_sample"), list) else [],
                },
            }
        )
    for index, text in enumerate(result.get("texts") if isinstance(result.get("texts"), list) else []):
        if not isinstance(text, dict):
            continue
        label = str(text.get("text") or text.get("label") or "").strip()
        if not label:
            continue
        bbox = _bbox(text.get("bbox"))
        items.append(
            {
                "item_id": str(text.get("id") or f"ocr_text_{index + 1}"),
                "label": label,
                "role": "text",
                "item_type": "readable",
                "bbox": bbox,
                "review_only": True,
                "grounding_eligible": False,
                "source_evidence": ["ocr"],
                "metadata": {
                    "source": "screen_reading.texts",
                    "surface_zone": _surface_zone_for_text(bbox, height=height),
                    "zone_evidence": "geometry_hint_only",
                    "confidence": text.get("confidence"),
                },
            }
        )
    for index, candidate in enumerate(
        screen_map.get("candidates") if isinstance(screen_map.get("candidates"), list) else []
    ):
        if not isinstance(candidate, dict):
            continue
        items.append(
            {
                "item_id": str(candidate.get("candidate_id") or f"candidate_{index + 1}"),
                "label": str(candidate.get("label") or candidate.get("goal_hint") or f"Candidate {index + 1}"),
                "role": str(candidate.get("role") or "candidate"),
                "item_type": "review_only",
                "bbox": _bbox(candidate.get("bbox")),
                "review_only": True,
                "grounding_eligible": False,
                "source_evidence": ["screen_map_candidate"],
                "metadata": {
                    "source": "screen_map.candidates",
                    "surface_zone": str(candidate.get("section_id") or "unknown"),
                    "risk_class": str(candidate.get("risk_class") or ""),
                    "risk_reasons": candidate.get("risk_reasons")
                    if isinstance(candidate.get("risk_reasons"), list)
                    else [],
                },
            }
        )
    if not items:
        learning_draft = (
            result.get("learning_draft")
            if isinstance(result.get("learning_draft"), dict)
            else {}
        )
        items.extend(
            _items_from_learning_draft_regions(
                learning_draft.get("regions")
                if isinstance(learning_draft.get("regions"), list)
                else []
            )
        )
    return [item for item in items if item.get("bbox")]


def _stage1_items_from_omniparser(
    source: dict[str, Any],
    *,
    image_size: dict[str, Any],
) -> list[dict[str, Any]]:
    if str(source.get("status") or "success").casefold() != "success":
        return []
    elements = source.get("elements")
    if not isinstance(elements, list):
        elements = source.get("parsed_content_list") if isinstance(source.get("parsed_content_list"), list) else []
    source_size = source.get("image_size") if isinstance(source.get("image_size"), dict) else image_size
    width = _int(source_size.get("width"))
    height = _int(source_size.get("height"))
    lineage = {
        "provider": str(source.get("provider") or ""),
        "profile_id": str(source.get("profile_id") or ""),
        "model_revision": str(source.get("model_revision") or ""),
        "capture_id": str(source.get("capture_id") or ""),
        "source_run_id": str(source.get("source_run_id") or ""),
        "screenshot_sha256": str(source.get("screenshot_sha256") or ""),
        "image_size": deepcopy(source_size),
        "coordinate_space": str(source.get("coordinate_space") or ""),
        "provenance": deepcopy(
            source.get("provenance")
            if isinstance(source.get("provenance"), dict)
            else {}
        ),
        "status": str(source.get("status") or ""),
        "stale": bool(source.get("stale")),
    }
    items: list[dict[str, Any]] = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            continue
        item_id = str(element.get("element_id") or element.get("id") or f"omniparser_element_{index + 1}").strip()
        label = str(
            element.get("content")
            or element.get("label")
            or element.get("text")
            or item_id
        ).strip()
        bbox = _omniparser_bbox(
            element.get("bbox"),
            width=width,
            height=height,
            coordinate_space=lineage["coordinate_space"],
        )
        if not label or not bbox.get("w") or not bbox.get("h"):
            continue
        items.append(
            {
                "item_id": item_id,
                "label": label,
                "role": str(element.get("type") or element.get("role") or "element"),
                "item_type": "review_only",
                "bbox": bbox,
                "review_only": True,
                "grounding_eligible": False,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "real_action_requires_gate": True,
                "source_evidence": ["omniparser"],
                "metadata": {
                    "source": "omniparser.stage1_projection",
                    "provider_source": str(element.get("source") or ""),
                    "raw_type": str(element.get("type") or element.get("role") or ""),
                    "parser_lineage": deepcopy(lineage),
                },
            }
        )
    return items


def _omniparser_bbox(
    value: Any,
    *,
    width: int,
    height: int,
    coordinate_space: str,
) -> dict[str, int]:
    if coordinate_space not in {"image_normalized_xyxy", "image_pixel_xyxy"}:
        return {}
    if isinstance(value, dict):
        return _bbox(value)
    if not isinstance(value, list) or len(value) < 4:
        return {}
    try:
        x1, y1, x2, y2 = (float(part) for part in value[:4])
    except (TypeError, ValueError):
        return {}
    if coordinate_space == "image_normalized_xyxy":
        x1, x2 = x1 * width, x2 * width
        y1, y2 = y1 * height, y2 * height
    return {
        "x": max(0, _int(min(x1, x2))),
        "y": max(0, _int(min(y1, y2))),
        "w": max(0, _int(abs(x2 - x1))),
        "h": max(0, _int(abs(y2 - y1))),
    }


def _items_from_observe_screen_inventory(screen_inventory: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(screen_inventory, dict):
        return []
    items: list[dict[str, Any]] = []
    source_groups = (
        ("available_actions", "actionable", "screen_inventory_available_action"),
        ("page_elements", "readable", "screen_inventory_page_element"),
        ("cards", "layout", "screen_inventory_card"),
    )
    for group_name, default_item_type, source_name in source_groups:
        values = screen_inventory.get(group_name)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            label = str(value.get("label") or value.get("text") or value.get("id") or "").strip()
            bbox = _bbox(value.get("bbox"))
            if not label or not bbox.get("w") or not bbox.get("h"):
                continue
            item_id = str(value.get("id") or value.get("item_id") or f"{group_name}_{index + 1}")
            metadata = deepcopy(value.get("metadata")) if isinstance(value.get("metadata"), dict) else {}
            original_source = str(value.get("source") or metadata.get("source") or source_name)
            evidence_level = str(value.get("evidence_level") or metadata.get("evidence_level") or "")
            metadata.setdefault("source", original_source)
            metadata.setdefault("source_id", str(value.get("source_id") or item_id))
            if evidence_level:
                metadata.setdefault("evidence_level", evidence_level)
            items.append(
                {
                    "item_id": item_id,
                    "label": label,
                    "role": str(value.get("role") or value.get("action_type") or default_item_type),
                    "item_type": default_item_type,
                    "bbox": bbox,
                    "review_only": True,
                    "grounding_eligible": False,
                    "source_evidence": [source_name],
                    "source": original_source,
                    "evidence_level": evidence_level,
                    "metadata": metadata,
                }
            )
    return items


def _items_from_screen_inventory_list(screen_inventory: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, value in enumerate(screen_inventory):
        if not isinstance(value, dict):
            continue
        label = str(value.get("label") or value.get("text") or value.get("item_id") or value.get("id") or "").strip()
        bbox = _bbox(value.get("bbox"))
        if not label or not bbox.get("w") or not bbox.get("h"):
            continue
        source_evidence = value.get("source_evidence") if isinstance(value.get("source_evidence"), list) else []
        items.append(
            {
                "item_id": str(value.get("item_id") or value.get("id") or f"screen_inventory_item_{index + 1}"),
                "label": label,
                "role": str(value.get("role") or "item"),
                "item_type": str(value.get("item_type") or "review_only"),
                "bbox": bbox,
                "review_only": True,
                "grounding_eligible": False,
                "source_evidence": source_evidence or ["screen_inventory_item"],
                "metadata": {
                    "source": "screen_inventory.list",
                    "source_id": str(
                        value.get("source_id") or value.get("item_id") or value.get("id") or ""
                    ),
                    "evidence_level": str(value.get("evidence_level") or ""),
                },
            }
        )
    return items


def _items_from_learning_draft_regions(regions: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, value in enumerate(regions):
        if not isinstance(value, dict):
            continue
        bbox = _bbox(value.get("bbox"))
        if not bbox.get("w") or not bbox.get("h"):
            continue
        item_id = str(
            value.get("item_id")
            or value.get("region_id")
            or value.get("id")
            or f"learning_draft_region_{index + 1}"
        )
        label = str(value.get("label") or value.get("name") or item_id)
        metadata = deepcopy(value.get("metadata")) if isinstance(value.get("metadata"), dict) else {}
        metadata.setdefault("source", "learning_draft.regions")
        metadata.setdefault("source_id", item_id)
        items.append(
            {
                "item_id": item_id,
                "label": label,
                "role": str(value.get("role") or value.get("kind") or "review_region"),
                "item_type": str(value.get("item_type") or "review_only"),
                "bbox": bbox,
                "review_only": True,
                "grounding_eligible": False,
                "source_evidence": ["learning_draft_region"],
                "metadata": metadata,
            }
        )
    return items


def _surface_zone_for_text(bbox: dict[str, int], *, height: int) -> str:
    if height > 0 and bbox.get("y", 0) < max(56, int(height * 0.09)):
        return "top_bar"
    return "primary_area"


def _surface_zone_for_section(section: dict[str, Any]) -> str:
    section_id = str(section.get("section_id") or "unknown").strip()
    role = str(section.get("role") or "").casefold()
    if section_id == "bottom_bar" and role == "content":
        return "primary_area"
    return section_id or "unknown"


def _bbox(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    return {
        "x": max(0, _int(source.get("x"))),
        "y": max(0, _int(source.get("y"))),
        "w": max(0, _int(source.get("w", source.get("width")))),
        "h": max(0, _int(source.get("h", source.get("height")))),
    }


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
