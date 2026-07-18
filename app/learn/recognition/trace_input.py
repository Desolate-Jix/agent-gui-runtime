from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def observe_bundle_from_trace_result(result: dict[str, Any], *, trace_path: Path) -> dict[str, Any]:
    """把历史或当前 observe trace 统一为学习识别输入。"""

    nested_bundle = result.get("observe_bundle") if isinstance(result.get("observe_bundle"), dict) else {}
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
        "source_trace_path": str(trace_path),
    }
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
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
    return [item for item in items if item.get("bbox")]


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
            metadata.setdefault("source_id", item_id)
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
                    "source_id": str(value.get("item_id") or value.get("id") or ""),
                    "evidence_level": str(value.get("evidence_level") or ""),
                },
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
