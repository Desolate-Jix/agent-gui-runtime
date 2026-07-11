from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.two_stage import build_stage1_region_localization_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run learning-mode stage1 region localization only.")
    parser.add_argument("--trace", required=True, help="Path to a learn-mode observe trace JSON.")
    parser.add_argument("--out", required=True, help="Output directory for the stage1 report.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()

    trace_path = Path(args.trace)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)
    screen_inventory = _stage1_inventory_from_trace_result(result)
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=bundle.get("screen_size"))

    report = build_stage1_region_localization_report(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
    )
    report["source_trace_path"] = str(trace_path)
    report["screen_inventory_count"] = len(screen_inventory)
    report["layout_graph_summary"] = {
        "node_count": layout_graph.get("node_count"),
        "zone_count": layout_graph.get("zone_count"),
        "zones": {
            zone_id: len(zone.get("item_ids") if isinstance(zone, dict) and isinstance(zone.get("item_ids"), list) else [])
            for zone_id, zone in (layout_graph.get("zones") if isinstance(layout_graph.get("zones"), dict) else {}).items()
        },
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = out_dir / f"stage1_region_localization_report_{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "report_path": str(report_path),
        "overlay_path": report.get("overlay_path"),
        "stage1_5_overlay_path": report.get("stage1_5_overlay_path"),
        "stage1_5_status": report.get("stage1_5_partition", {}).get("status"),
        "stage1_5_subregion_count": report.get("stage1_5_partition", {}).get("subregion_count"),
        "screen_inventory_count": len(screen_inventory),
        "localized_region_count": report.get("stage1_region_localization", {}).get("localized_region_count"),
        "geometry_only_region_count": report.get("calibration_diagnostics", {}).get("geometry_only_region_count"),
        "needs_prompt_or_model_calibration": report.get("calibration_diagnostics", {}).get(
            "needs_prompt_or_model_calibration"
        ),
        "stage2_numbering_skipped": report.get("stage2_numbering_skipped"),
        "pathgraph_generation_skipped": report.get("pathgraph_generation_skipped"),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={summary['report_path']}")
        print(f"overlay_path={summary['overlay_path']}")
        print(f"localized_region_count={summary['localized_region_count']}")
    return 0


def _observe_bundle_from_trace_result(result: dict[str, Any], *, trace_path: Path) -> dict[str, Any]:
    nested_bundle = result.get("observe_bundle") if isinstance(result.get("observe_bundle"), dict) else {}
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    if not image_size:
        image_size = nested_bundle.get("image_size") if isinstance(nested_bundle.get("image_size"), dict) else {}
    if not image_size:
        image_size = nested_bundle.get("screen_size") if isinstance(nested_bundle.get("screen_size"), dict) else {}
    bundle = {
        "contract_version": "learn_stage1_region_localization_input_v1",
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
    if screen_reading:
        bundle["screen_reading"] = screen_reading
    texts = result.get("texts") if isinstance(result.get("texts"), list) else []
    if texts:
        bundle["texts"] = texts
    return bundle


def _stage1_inventory_from_trace_result(result: dict[str, Any]) -> list[dict[str, Any]]:
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
                    "risk_reasons": candidate.get("risk_reasons") if isinstance(candidate.get("risk_reasons"), list) else [],
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
                    "metadata": {
                        "source": source_name,
                        "source_id": item_id,
                    },
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
    y = bbox.get("y", 0)
    if height > 0 and y < max(56, int(height * 0.09)):
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


if __name__ == "__main__":
    raise SystemExit(main())
