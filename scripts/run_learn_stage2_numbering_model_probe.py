from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.model_server import ensure_model_server, profile_for_stage, stop_model_server
from app.vision.local_provider import LocalVisionProvider


STAGE2_GROUPING_PROMPT = """\
You are doing learning-mode homogeneous subregion grouping.

Goal:
- You are given a crop of exactly one top-level structure region.
- Divide it into smaller homogeneous groups before item numbering.
- A group should contain objects that are visually similar in size and meaning.

Rules:
- Coordinate origin is the crop top-left corner: x=0, y=0.
- Do not use full-screen coordinates in this output.
- Do not output groups outside the crop.
- Do not put different-size cards into one group.
- Do not put different semantic areas into one group.
- Do not create horizontal text/image bands. Groups are containers, not stripes.
- A media_card_group may contain several same-size media cards in the same row.
- A media_card_group bbox must include the full visible card containers: image/artwork plus the text directly attached below or inside each card.
- A media_card_group bbox must start at the card top edge and end at the bottom of the card captions, before the next section title.
- If cards in one row have different visible sizes or layouts, split them into separate media_card_group regions.
- A group may contain same-purpose navigation icons or toolbar controls.
- Section titles may be their own groups.
- A section_title bbox must wrap only the title text, not the full content width.
- A group bbox must wrap the visible members tightly; do not include the next section title unless it is the section_title group.
- If one visible card has a different size/layout from nearby cards, make it a separate group.
- If you are uncertain, prefer a larger semantic section group over a misleading horizontal stripe, but still do not cross into the next section.
- This is review-only learning evidence. Do not output click authorization.

Output JSON only:
{
  "region_id": "...",
  "groups": [
    {
      "group_id": "g1",
      "label": "...",
      "role": "section_title|nav_icon_group|toolbar_control_group|media_card_group|text_group|single_item|mixed_review_group",
      "bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
      "expected_item_role": "nav_icon|section_title|media_card|button|text|control|other",
      "homogeneity_rule": "same size / same meaning / same row / same visual style",
      "expected_item_count": 0,
      "evidence": ["visible text or visual evidence"],
      "confidence": 0.0
    }
  ]
}
"""


STAGE2_NUMBERING_PROMPT = """\
You are doing learning-mode homogeneous-subregion UI numbering.

Goal:
- You are given a crop of one homogeneous subregion.
- Enumerate visible meaningful UI objects inside this homogeneous crop.
- Return tight crop-local pixel bboxes for each object.

Rules:
- Coordinate origin is the crop top-left corner: x=0, y=0.
- Do not use full-screen coordinates in this output.
- Do not output objects outside the crop.
- The crop already contains one group of similar UI objects. Do not infer items outside the crop.
- Keep a visual card/tile and its text as one parent item with child_texts.
- Do not duplicate card text as sibling items when it is clearly inside a card.
- Section titles may be separate items.
- Navigation rail icons may be separate items.
- For a header/top bar/control bar, number each visible icon/button/control separately.
- Do not collapse the entire top bar into one item unless it is visually one continuous search/input field.
- Keep bbox height tight. A section title should not span a whole row of cards.
- A media card bbox should cover the visible card/tile boundary, not the whole row or group.
- For card rows, number every visible card/tile separately.
- Do not merge neighboring cards or infer a fixed grid if the visible card edges disagree.
- A card bbox may include the artwork and the text directly attached below/inside that same card.
- A card bbox must not include adjacent cards, blank columns, or the next section title.
- If a card is partially visible at the right or bottom edge, include only the visible part.
- Section title bboxes must wrap the title text only, not the full content width.
- This is review-only learning evidence. Do not output click authorization.

Output JSON only:
{
  "region_id": "...",
  "items": [
    {
      "number": "3.1",
      "label": "...",
      "role": "nav_icon|section_title|media_card|button|text|control|other",
      "bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
      "child_texts": [
        {"text": "...", "bbox": {"x": 0, "y": 0, "w": 0, "h": 0}}
      ],
      "evidence": ["visual/OCR evidence"],
      "confidence": 0.0
    }
  ]
}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run actual model calls for Stage2 per-region numbering.")
    parser.add_argument("--stage1-model-report", required=True, help="Stage1 model probe report JSON.")
    parser.add_argument("--out", required=True, help="Output directory for numbering probe artifacts.")
    parser.add_argument("--profile-id", default="qwen3_vl_8b_q4_k_m", help="Launchable model profile id.")
    parser.add_argument("--wait-seconds", type=float, default=600.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--stop-after", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report_path = Path(args.stage1_model_report)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage1_report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    image_path = _resolve_path(str(stage1_report.get("image_path") or ""))
    regions = _with_numbering_bboxes(_regions_from_stage1_model_report(stage1_report))
    if not regions:
        raise ValueError("Stage1 model report has no regions to number")

    profile = profile_for_stage("learning", args.profile_id)
    start_status = ensure_model_server(
        stage="learning",
        profile_id=args.profile_id,
        wait_until_ready=True,
        wait_seconds=args.wait_seconds,
    )
    started_by_probe = bool(start_status.get("started"))
    server_after = start_status.get("after") if isinstance(start_status.get("after"), dict) else start_status.get("before")
    if not isinstance(server_after, dict) or server_after.get("status") != "running":
        raise RuntimeError(f"Model server not ready: {server_after}")

    provider = LocalVisionProvider(
        endpoint=str(profile.get("endpoint") or ""),
        model_name=str(profile.get("model_name") or ""),
        timeout_seconds=float(args.timeout_seconds),
    )
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    region_results: list[dict[str, Any]] = []
    for region in regions:
        region_result = _run_region_numbering_call(
            provider=provider,
            image_path=image_path,
            region=region,
            out_dir=out_dir,
            timestamp=timestamp,
        )
        region_results.append(region_result)

    validation = _validate_items_inside_regions(region_results)
    overlay_path = _render_numbering_overlay(
        image_path=image_path,
        region_results=region_results,
        out_dir=out_dir,
        timestamp=timestamp,
    )
    stop_status = None
    if args.stop_after and started_by_probe:
        stop_status = stop_model_server(profile)

    combined_report = {
        "contract_version": "learn_stage2_numbering_model_probe_report_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "actual_model_call": True,
        "source_stage1_model_report_path": str(report_path),
        "image_path": str(image_path),
        "profile_id": str(profile.get("profile_id") or args.profile_id),
        "model_name": str(profile.get("model_name") or ""),
        "model_start": start_status,
        "region_count": len(region_results),
        "numbered_item_count": sum(len(_items(result.get("parsed_output"))) for result in region_results),
        "region_results": region_results,
        "validation": validation,
        "overlay_path": str(overlay_path),
        "pathgraph_generation_skipped": True,
        "learning_draft_generation_skipped": True,
        "interpretation": (
            "Actual model calls for Stage2 per-region numbering only; "
            "review/display evidence, not click authorization or Runtime PathGraph promotion."
        ),
    }
    if stop_status is not None:
        combined_report["model_stop"] = stop_status
    combined_report_path = out_dir / f"stage2_numbering_model_probe_report_{timestamp}.json"
    combined_report_path.write_text(json.dumps(combined_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "report_path": str(combined_report_path),
        "overlay_path": str(overlay_path),
        "actual_model_call": True,
        "region_count": combined_report["region_count"],
        "numbered_item_count": combined_report["numbered_item_count"],
        "outside_parent_bbox_count": validation["outside_parent_bbox_count"],
        "parse_error_count": sum(1 for result in region_results if result.get("parse_error")),
        "started_model": started_by_probe,
        "stopped_model": bool(stop_status and stop_status.get("stopped")),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0


def _run_region_numbering_call(
    *,
    provider: LocalVisionProvider,
    image_path: Path,
    region: dict[str, Any],
    out_dir: Path,
    timestamp: str,
) -> dict[str, Any]:
    region_id = str(region.get("region_id") or region.get("id") or "region")
    region_no = int(region.get("region_no") or 0)
    source_region_bbox = _bbox(region.get("precise_bbox") if isinstance(region.get("precise_bbox"), dict) else region.get("bbox"))
    region_bbox = _bbox(region.get("numbering_bbox")) or source_region_bbox
    if not region_bbox:
        raise ValueError(f"Region has no bbox: {region_id}")
    crop_path = _write_region_crop(image_path=image_path, bbox=region_bbox, out_dir=out_dir, region_id=region_id, timestamp=timestamp)
    safe_region_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in region_id)

    if _is_primary_region(region_id):
        grouping_result = _run_region_grouping_call(
            provider=provider,
            crop_path=crop_path,
            region=region,
            region_bbox=region_bbox,
            out_dir=out_dir,
            safe_region_id=safe_region_id,
            timestamp=timestamp,
        )
        groups = _groups_for_numbering(
            grouping_result=grouping_result,
            image_path=image_path,
            region_id=region_id,
            parent_bbox=region_bbox,
        )
        grouping_strategy = "primary_region_homogeneous_grouping_with_visual_card_segmenter"
    else:
        grouping_result = _skipped_grouping_result(region_id=region_id, region_bbox=region_bbox)
        groups = [_whole_region_numbering_group(region_id=region_id, region_bbox=region_bbox)]
        grouping_strategy = "direct_region_numbering_without_subgrouping"
    group_numbering_results: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    cleanup_reports: list[dict[str, Any]] = []
    for group_index, group in enumerate(groups, start=1):
        numbering_result = _run_group_numbering_call(
            provider=provider,
            image_path=image_path,
            region=region,
            group=group,
            group_index=group_index,
            out_dir=out_dir,
            safe_region_id=safe_region_id,
            timestamp=timestamp,
        )
        group_numbering_results.append(numbering_result)
        if numbering_result.get("parse_error"):
            parse_errors.append(str(numbering_result.get("parse_error")))
        cleanup = numbering_result.get("display_cleanup") if isinstance(numbering_result.get("display_cleanup"), dict) else {}
        cleanup_reports.append(cleanup)
        all_items.extend(_items(numbering_result.get("parsed_output")))

    parsed = {
        "region_id": region_id,
        "coordinate_space": "screen_pixels_restored_from_homogeneous_group_crop",
        "items": _renumber_items(all_items, region_no=region_no, parent_bbox=region_bbox),
    }
    parsed, cleanup_report = _cleanup_numbered_items(parsed, parent_bbox=region_bbox)
    cleanup_report["group_cleanup_reports"] = cleanup_reports
    cleanup_report["grouping_suppressed_count"] = grouping_result.get("group_cleanup", {}).get("suppressed_count", 0)
    parse_error = "; ".join(parse_errors)

    parsed_path = out_dir / f"stage2_numbering_{safe_region_id}_{timestamp}.json"
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "region_id": region_id,
        "region_no": region_no,
        "region_label": str(region.get("label") or ""),
        "source_region_bbox": source_region_bbox,
        "region_bbox": region_bbox,
        "crop_path": str(crop_path),
        "coordinate_space": "screen_pixels_restored_from_homogeneous_group_crop",
        "grouping_strategy": grouping_strategy,
        "subregion_grouping": grouping_result,
        "group_numbering_results": group_numbering_results,
        "parsed_output_path": str(parsed_path),
        "parsed_output": parsed,
        "display_cleanup": cleanup_report,
        "parse_error": parse_error,
        "item_count": len(_items(parsed)),
    }


def _skipped_grouping_result(*, region_id: str, region_bbox: dict[str, int]) -> dict[str, Any]:
    return {
        "contract_version": "learn_stage2_homogeneous_grouping_result_v1",
        "region_id": region_id,
        "skipped": True,
        "skip_reason": "non_primary_region_uses_direct_numbering",
        "parsed_output": {
            "region_id": region_id,
            "groups": [],
            "coordinate_space": "screen_pixels",
        },
        "parse_error": "",
        "group_count": 0,
        "group_cleanup": {
            "suppressed_count": 0,
            "adjusted_count": 0,
            "interpretation": "Grouping intentionally skipped for non-primary/header/sidebar regions.",
        },
        "region_bbox": region_bbox,
    }


def _whole_region_numbering_group(*, region_id: str, region_bbox: dict[str, int]) -> dict[str, Any]:
    return {
        "group_id": "whole_region_direct",
        "label": f"{region_id} direct numbering",
        "role": "mixed_review_group",
        "bbox": region_bbox,
        "expected_item_role": "other",
        "homogeneity_rule": "direct numbering for header/sidebar; no subgrouping",
        "expected_item_count": 0,
        "source": "direct_region_numbering",
        "confidence": 0.0,
        "evidence": ["non_primary_region_direct_numbering"],
    }


def _run_region_grouping_call(
    *,
    provider: LocalVisionProvider,
    crop_path: Path,
    region: dict[str, Any],
    region_bbox: dict[str, int],
    out_dir: Path,
    safe_region_id: str,
    timestamp: str,
) -> dict[str, Any]:
    region_id = str(region.get("region_id") or region.get("id") or "region")
    prompt_input = {
        "contract_version": "learn_stage2_grouping_prompt_input_v1",
        "region": {
            "region_no": int(region.get("region_no") or 0),
            "region_id": region_id,
            "label": str(region.get("label") or ""),
            "role": str(region.get("role") or ""),
            "full_screenshot_bbox": region_bbox,
            "crop_size": {"width": region_bbox["w"], "height": region_bbox["h"]},
        },
        "instruction": (
            "First identify same-kind subregions. Different card sizes or meanings must become different groups. "
            "The next model call will number items inside each group."
        ),
    }
    prompt = f"{STAGE2_GROUPING_PROMPT}\n\n{json.dumps(prompt_input, ensure_ascii=False, indent=2)}"
    raw_response = provider._call_openai_compatible_endpoint(  # noqa: SLF001
        crop_path,
        prompt,
        max_tokens=2048,
        temperature=0.0,
    )
    raw_text = provider._extract_message_text(raw_response)  # noqa: SLF001
    parse_error = ""
    parsed: dict[str, Any] = {}
    group_cleanup: dict[str, Any] = {}
    try:
        parsed_local = provider._parse_json_object(raw_text)  # noqa: SLF001
        parsed_restored = _restore_parsed_groups_to_screen(parsed_local, origin={"x": region_bbox["x"], "y": region_bbox["y"]})
        parsed, group_cleanup = _cleanup_groups(parsed_restored, parent_bbox=region_bbox)
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)
        group_cleanup = {"suppressed_count": 0, "adjusted_count": 0, "notes": ["parse_failed"]}
    raw_path = out_dir / f"stage2_grouping_{safe_region_id}_{timestamp}.txt"
    parsed_path = out_dir / f"stage2_grouping_{safe_region_id}_{timestamp}.json"
    raw_path.write_text(raw_text + "\n", encoding="utf-8")
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "learn_stage2_homogeneous_grouping_result_v1",
        "region_id": region_id,
        "raw_model_output_path": str(raw_path),
        "parsed_output_path": str(parsed_path),
        "raw_response": raw_response,
        "parsed_output": parsed,
        "parse_error": parse_error,
        "group_count": len(_groups(parsed)),
        "group_cleanup": group_cleanup,
    }


def _run_group_numbering_call(
    *,
    provider: LocalVisionProvider,
    image_path: Path,
    region: dict[str, Any],
    group: dict[str, Any],
    group_index: int,
    out_dir: Path,
    safe_region_id: str,
    timestamp: str,
) -> dict[str, Any]:
    region_id = str(region.get("region_id") or region.get("id") or "region")
    group_id = str(group.get("group_id") or f"g{group_index}")
    group_bbox = _bbox(group.get("bbox"))
    if not group_bbox:
        raise ValueError(f"Group has no bbox: {region_id}/{group_id}")
    group_key = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in group_id)
    crop_path = _write_region_crop(
        image_path=image_path,
        bbox=group_bbox,
        out_dir=out_dir,
        region_id=f"{safe_region_id}_{group_key}",
        timestamp=timestamp,
    )
    prompt_input = {
        "contract_version": "learn_stage2_group_numbering_prompt_input_v1",
        "region": {
            "region_no": int(region.get("region_no") or 0),
            "region_id": region_id,
            "label": str(region.get("label") or ""),
            "role": str(region.get("role") or ""),
        },
        "homogeneous_group": {
            "group_id": group_id,
            "label": str(group.get("label") or ""),
            "role": str(group.get("role") or ""),
            "expected_item_role": str(group.get("expected_item_role") or ""),
            "homogeneity_rule": str(group.get("homogeneity_rule") or ""),
            "full_screenshot_bbox": group_bbox,
            "crop_size": {"width": group_bbox["w"], "height": group_bbox["h"]},
        },
        "instruction": (
            "Number only the visible items inside this homogeneous subregion crop. "
            "Return crop-local coordinates and do not invent a fixed grid."
        ),
    }
    prompt = f"{STAGE2_NUMBERING_PROMPT}\n\n{json.dumps(prompt_input, ensure_ascii=False, indent=2)}"
    raw_response = provider._call_openai_compatible_endpoint(  # noqa: SLF001
        crop_path,
        prompt,
        max_tokens=2048,
        temperature=0.0,
    )
    raw_text = provider._extract_message_text(raw_response)  # noqa: SLF001
    parse_error = ""
    parsed: dict[str, Any] = {}
    cleanup_report: dict[str, Any] = {}
    try:
        parsed_local = provider._parse_json_object(raw_text)  # noqa: SLF001
        parsed_restored = _restore_parsed_items_to_screen(parsed_local, origin={"x": group_bbox["x"], "y": group_bbox["y"]})
        parsed, cleanup_report = _cleanup_numbered_items(parsed_restored, parent_bbox=group_bbox)
        parsed, visual_refinement = _refine_direct_small_controls(
            parsed,
            image_path=image_path,
            group=group,
            group_bbox=group_bbox,
        )
        cleanup_report["visual_small_control_refinement"] = visual_refinement
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)
        cleanup_report = {"suppressed_count": 0, "adjusted_count": 0, "notes": ["parse_failed"]}
    raw_path = out_dir / f"stage2_numbering_{safe_region_id}_{group_key}_{timestamp}.txt"
    parsed_path = out_dir / f"stage2_numbering_{safe_region_id}_{group_key}_{timestamp}.json"
    raw_path.write_text(raw_text + "\n", encoding="utf-8")
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "learn_stage2_group_numbering_result_v1",
        "region_id": region_id,
        "group_id": group_id,
        "group_index": group_index,
        "group_label": str(group.get("label") or ""),
        "group_role": str(group.get("role") or ""),
        "group_bbox": group_bbox,
        "crop_path": str(crop_path),
        "raw_model_output_path": str(raw_path),
        "parsed_output_path": str(parsed_path),
        "raw_response": raw_response,
        "parsed_output": parsed,
        "parse_error": parse_error,
        "display_cleanup": cleanup_report,
        "item_count": len(_items(parsed)),
    }


def _write_region_crop(*, image_path: Path, bbox: dict[str, int], out_dir: Path, region_id: str, timestamp: str) -> Path:
    with Image.open(image_path) as image:
        width, height = image.size
        left = max(0, bbox["x"])
        top = max(0, bbox["y"])
        right = min(width, bbox["x"] + bbox["w"])
        bottom = min(height, bbox["y"] + bbox["h"])
        crop = image.crop((left, top, right, bottom)).convert("RGB")
    safe_region_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in region_id)
    crop_path = out_dir / f"stage2_crop_{safe_region_id}_{timestamp}.png"
    crop.save(crop_path)
    return crop_path


def _restore_parsed_items_to_screen(parsed: dict[str, Any], *, origin: dict[str, int]) -> dict[str, Any]:
    restored = json.loads(json.dumps(parsed, ensure_ascii=False))
    for item in _items(restored):
        if isinstance(item.get("bbox"), dict):
            item["bbox"] = _offset_bbox(item["bbox"], origin)
        child_texts = item.get("child_texts") if isinstance(item.get("child_texts"), list) else []
        for child in child_texts:
            if isinstance(child, dict) and isinstance(child.get("bbox"), dict):
                child["bbox"] = _offset_bbox(child["bbox"], origin)
    restored["coordinate_space"] = "screen_pixels_restored_from_crop_local"
    restored["crop_origin"] = {"x": origin["x"], "y": origin["y"]}
    return restored


def _restore_parsed_groups_to_screen(parsed: dict[str, Any], *, origin: dict[str, int]) -> dict[str, Any]:
    restored = json.loads(json.dumps(parsed, ensure_ascii=False))
    for group in _groups(restored):
        if isinstance(group.get("bbox"), dict):
            group["bbox"] = _offset_bbox(group["bbox"], origin)
    restored["coordinate_space"] = "screen_pixels_restored_from_region_crop_local"
    restored["crop_origin"] = {"x": origin["x"], "y": origin["y"]}
    return restored


def _offset_bbox(value: dict[str, Any], origin: dict[str, int]) -> dict[str, int]:
    bbox = _bbox(value)
    if not bbox:
        return {}
    return {"x": bbox["x"] + origin["x"], "y": bbox["y"] + origin["y"], "w": bbox["w"], "h": bbox["h"]}


def _groups_for_numbering(
    *,
    grouping_result: dict[str, Any],
    image_path: Path,
    region_id: str,
    parent_bbox: dict[str, int],
) -> list[dict[str, Any]]:
    parsed = grouping_result.get("parsed_output") if isinstance(grouping_result.get("parsed_output"), dict) else {}
    model_groups = _groups(parsed)
    visual_media_groups = _visual_media_card_row_groups(image_path=image_path, parent_bbox=parent_bbox) if _is_primary_region(region_id) else []
    if visual_media_groups:
        non_media_model_groups = [group for group in model_groups if str(group.get("role") or "") != "media_card_group"]
        groups = non_media_model_groups + visual_media_groups
    else:
        groups = model_groups
    if not groups:
        return [
            {
                "group_id": "fallback_whole_region",
                "label": "whole region fallback",
                "role": "mixed_review_group",
                "expected_item_role": "other",
                "bbox": parent_bbox,
                "homogeneity_rule": "fallback because grouping produced no valid groups",
                "expected_item_count": 0,
            }
        ]
    return sorted(groups, key=lambda item: ((_bbox(item.get("bbox")) or {"y": 0, "x": 0})["y"], (_bbox(item.get("bbox")) or {"x": 0})["x"]))


def _is_primary_region(region_id: str) -> bool:
    lowered = region_id.lower()
    return any(token in lowered for token in ("primary", "main", "content"))


def _visual_media_card_row_groups(*, image_path: Path, parent_bbox: dict[str, int]) -> list[dict[str, Any]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:  # noqa: BLE001
        return []
    with Image.open(image_path) as image:
        crop = image.crop(
            (
                parent_bbox["x"],
                parent_bbox["y"],
                parent_bbox["x"] + parent_bbox["w"],
                parent_bbox["y"] + parent_bbox["h"],
            )
        ).convert("RGB")
    arr = np.array(crop)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    mask = ((saturation > 35) | (value < 215)).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cards: list[dict[str, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 90 or h < 80 or area < 9000:
            continue
        if w > parent_bbox["w"] * 0.85 or h > parent_bbox["h"] * 0.65:
            continue
        cards.append({"x": parent_bbox["x"] + x, "y": parent_bbox["y"] + y, "w": w, "h": h})
    cards = _dedupe_bboxes(cards, iou_threshold=0.72)
    if not cards:
        return []
    rows: list[list[dict[str, int]]] = []
    for card in sorted(cards, key=lambda item: (item["y"] + item["h"] / 2, item["x"])):
        center_y = card["y"] + card["h"] / 2
        target_row = None
        for row in rows:
            row_center = sum(item["y"] + item["h"] / 2 for item in row) / len(row)
            row_height = sum(item["h"] for item in row) / len(row)
            if abs(center_y - row_center) <= max(45, row_height * 0.35):
                target_row = row
                break
        if target_row is None:
            rows.append([card])
        else:
            target_row.append(card)
    groups: list[dict[str, Any]] = []
    group_index = 1
    for row in rows:
        if len(row) < 2:
            continue
        for bucket in _split_row_by_card_size(row):
            if len(bucket) < 2:
                continue
            bbox = _row_group_bbox(bucket, parent_bbox=parent_bbox, all_cards=cards)
            groups.append(
                {
                    "group_id": f"visual_card_row_{group_index}",
                    "label": f"visual media card row {group_index}",
                    "role": "media_card_group",
                    "bbox": bbox,
                    "expected_item_role": "media_card",
                    "homogeneity_rule": "visual_card_segmenter: same row and similar artwork/card size",
                    "expected_item_count": len(bucket),
                    "source": "visual_card_segmenter",
                    "confidence": 0.0,
                    "evidence": [f"detected_card_count={len(bucket)}"],
                }
            )
            group_index += 1
    return groups


def _dedupe_bboxes(boxes: list[dict[str, int]], *, iou_threshold: float) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for box in sorted(boxes, key=lambda item: item["w"] * item["h"], reverse=True):
        if any(_iou(box, existing) >= iou_threshold for existing in result):
            continue
        result.append(box)
    return sorted(result, key=lambda item: (item["y"], item["x"]))


def _split_row_by_card_size(row: list[dict[str, int]]) -> list[list[dict[str, int]]]:
    buckets: list[list[dict[str, int]]] = []
    for card in sorted(row, key=lambda item: item["x"]):
        target = None
        for bucket in buckets:
            avg_w = sum(item["w"] for item in bucket) / len(bucket)
            avg_h = sum(item["h"] for item in bucket) / len(bucket)
            if abs(card["w"] - avg_w) / max(1, avg_w) <= 0.22 and abs(card["h"] - avg_h) / max(1, avg_h) <= 0.22:
                target = bucket
                break
        if target is None:
            buckets.append([card])
        else:
            target.append(card)
    return buckets


def _row_group_bbox(cards: list[dict[str, int]], *, parent_bbox: dict[str, int], all_cards: list[dict[str, int]]) -> dict[str, int]:
    x1 = min(card["x"] for card in cards)
    y1 = min(card["y"] for card in cards)
    x2 = max(card["x"] + card["w"] for card in cards)
    y2 = max(card["y"] + card["h"] for card in cards)
    next_row_top = min((card["y"] for card in all_cards if card["y"] > y1 + 60), default=parent_bbox["y"] + parent_bbox["h"])
    caption_extension = 78 if y2 + 24 < next_row_top else 0
    y2 = min(parent_bbox["y"] + parent_bbox["h"], next_row_top - 16, y2 + caption_extension)
    return _clip_bbox(parent_bbox, {"x": x1, "y": y1, "w": x2 - x1, "h": max(1, y2 - y1)})


def _refine_direct_small_controls(
    parsed: dict[str, Any],
    *,
    image_path: Path,
    group: dict[str, Any],
    group_bbox: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if str(group.get("source") or "") != "direct_region_numbering":
        return parsed, {
            "applied": False,
            "reason": "not_direct_region_numbering",
            "candidate_count": 0,
        }
    items = _items(parsed)
    if len(items) < 3:
        return parsed, {
            "applied": False,
            "reason": "too_few_model_items",
            "candidate_count": 0,
        }
    candidates = _visual_small_control_boxes(image_path=image_path, parent_bbox=group_bbox)
    if len(candidates) < max(3, int(len(items) * 0.55)):
        return parsed, {
            "applied": False,
            "reason": "insufficient_visual_candidates",
            "candidate_count": len(candidates),
            "model_item_count": len(items),
        }
    overlaps = [
        max((_iou(_bbox(item.get("bbox")) or {"x": 0, "y": 0, "w": 1, "h": 1}, candidate) for candidate in candidates), default=0.0)
        for item in items
    ]
    avg_overlap = sum(overlaps) / max(1, len(overlaps))
    low_overlap_count = sum(1 for value in overlaps if value < 0.08)
    if avg_overlap >= 0.16 and low_overlap_count < len(items) * 0.45:
        return parsed, {
            "applied": False,
            "reason": "model_boxes_already_overlap_visual_candidates",
            "candidate_count": len(candidates),
            "model_item_count": len(items),
            "avg_model_visual_iou": avg_overlap,
            "low_overlap_count": low_overlap_count,
        }
    refined = json.loads(json.dumps(parsed, ensure_ascii=False))
    refined_items = _items(refined)
    horizontal = group_bbox["w"] >= group_bbox["h"] * 2.5
    ordered_candidates = sorted(candidates, key=lambda item: (item["x"], item["y"]) if horizontal else (item["y"], item["x"]))
    ordered_items = sorted(refined_items, key=lambda item: ((_bbox(item.get("bbox")) or {"x": 0, "y": 0})["x"], (_bbox(item.get("bbox")) or {"y": 0})["y"]) if horizontal else ((_bbox(item.get("bbox")) or {"y": 0})["y"], (_bbox(item.get("bbox")) or {"x": 0})["x"]))
    applied_pairs: list[dict[str, Any]] = []
    for item, candidate in zip(ordered_items, ordered_candidates):
        old_bbox = _bbox(item.get("bbox"))
        if not old_bbox:
            continue
        item["bbox"] = candidate
        item["bbox_refinement"] = {
            "source": "visual_small_control_segmenter",
            "previous_bbox": old_bbox,
            "reason": "model_bbox_low_overlap_with_visual_control_candidate",
        }
        applied_pairs.append(
            {
                "number": item.get("number"),
                "label": item.get("label"),
                "from": old_bbox,
                "to": candidate,
            }
        )
    return refined, {
        "applied": bool(applied_pairs),
        "reason": "model_boxes_low_overlap_with_visual_candidates" if applied_pairs else "no_pairs_applied",
        "candidate_count": len(candidates),
        "model_item_count": len(items),
        "refined_count": len(applied_pairs),
        "avg_model_visual_iou": avg_overlap,
        "low_overlap_count": low_overlap_count,
        "orientation": "horizontal" if horizontal else "vertical",
        "pairs": applied_pairs,
    }


def _visual_small_control_boxes(*, image_path: Path, parent_bbox: dict[str, int]) -> list[dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:  # noqa: BLE001
        return []
    with Image.open(image_path) as image:
        crop = image.crop(
            (
                parent_bbox["x"],
                parent_bbox["y"],
                parent_bbox["x"] + parent_bbox["w"],
                parent_bbox["y"] + parent_bbox["h"],
            )
        ).convert("RGB")
    arr = np.array(crop)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    dark = (gray < 190).astype("uint8") * 255
    edges = cv2.Canny(gray, 40, 120)
    mask = cv2.bitwise_or(dark, edges)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_boxes: list[dict[str, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < 18 or w < 3 or h < 2:
            continue
        if w > parent_bbox["w"] * 0.38 or h > parent_bbox["h"] * 0.82:
            continue
        if w > 90 or h > 70:
            continue
        raw_boxes.append({"x": parent_bbox["x"] + x, "y": parent_bbox["y"] + y, "w": w, "h": h})
    boxes = _dedupe_bboxes(raw_boxes, iou_threshold=0.55)
    padded = [_pad_small_control_bbox(box, parent_bbox=parent_bbox) for box in boxes]
    return _dedupe_bboxes(padded, iou_threshold=0.72)


def _pad_small_control_bbox(box: dict[str, int], *, parent_bbox: dict[str, int]) -> dict[str, int]:
    target_w = min(max(24, box["w"] + 10), 38)
    target_h = min(max(22, box["h"] + 10), 36)
    cx = box["x"] + box["w"] / 2
    cy = box["y"] + box["h"] / 2
    padded = {
        "x": int(round(cx - target_w / 2)),
        "y": int(round(cy - target_h / 2)),
        "w": int(target_w),
        "h": int(target_h),
    }
    return _clip_bbox(parent_bbox, padded)


def _cleanup_groups(parsed: dict[str, Any], *, parent_bbox: dict[str, int]) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = json.loads(json.dumps(parsed, ensure_ascii=False))
    output_groups: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    adjusted: list[dict[str, Any]] = []
    kept_bboxes: list[dict[str, int]] = []
    for index, group in enumerate(_groups(cleaned), start=1):
        bbox = _bbox(group.get("bbox"))
        if not bbox:
            suppressed.append({"group_id": group.get("group_id"), "label": group.get("label"), "reason": "missing_bbox"})
            continue
        containment = _contains(parent_bbox, bbox)
        if containment < 0.25:
            suppressed.append(
                {
                    "group_id": group.get("group_id"),
                    "label": group.get("label"),
                    "reason": "outside_parent_region",
                    "containment": containment,
                }
            )
            continue
        original_bbox = dict(bbox)
        bbox = _clip_bbox(parent_bbox, bbox)
        if str(group.get("role") or "") == "section_title":
            label_len = max(2, len(str(group.get("label") or "")))
            bbox["w"] = min(bbox["w"], max(90, label_len * 24 + 48))
            bbox["h"] = min(max(24, bbox["h"]), 52)
        if bbox["w"] < 8 or bbox["h"] < 8:
            suppressed.append({"group_id": group.get("group_id"), "label": group.get("label"), "reason": "too_small_after_clip", "bbox": bbox})
            continue
        if any(_iou(existing, bbox) >= 0.92 for existing in kept_bboxes):
            suppressed.append({"group_id": group.get("group_id"), "label": group.get("label"), "reason": "duplicate_group_bbox", "bbox": bbox})
            continue
        if not group.get("group_id"):
            group["group_id"] = f"g{index}"
        if bbox != original_bbox:
            adjusted.append({"group_id": group.get("group_id"), "label": group.get("label"), "from": original_bbox, "to": bbox})
        group["bbox"] = bbox
        output_groups.append(group)
        kept_bboxes.append(bbox)
    cleaned["groups"] = sorted(output_groups, key=lambda item: (_bbox(item.get("bbox")) or {"y": 0, "x": 0})["y"] * 10000 + (_bbox(item.get("bbox")) or {"x": 0})["x"])
    return cleaned, {
        "contract_version": "learn_stage2_group_cleanup_v1",
        "display_only": True,
        "suppressed_count": len(suppressed),
        "adjusted_count": len(adjusted),
        "suppressed": suppressed,
        "adjusted": adjusted,
        "interpretation": "Homogeneous grouping cleanup clips groups to the localized structure region and removes duplicate/off-region groups.",
    }


def _validate_items_inside_regions(region_results: list[dict[str, Any]]) -> dict[str, Any]:
    outside: list[dict[str, Any]] = []
    total = 0
    for result in region_results:
        parent = _bbox(result.get("region_bbox"))
        for item in _items(result.get("parsed_output")):
            total += 1
            item_bbox = _bbox(item.get("bbox"))
            if not parent or not item_bbox:
                outside.append(
                    {
                        "region_id": result.get("region_id"),
                        "number": item.get("number"),
                        "label": item.get("label"),
                        "reason": "missing_parent_or_item_bbox",
                    }
                )
                continue
            if _contains(parent, item_bbox) < 0.92:
                outside.append(
                    {
                        "region_id": result.get("region_id"),
                        "number": item.get("number"),
                        "label": item.get("label"),
                        "parent_bbox": parent,
                        "item_bbox": item_bbox,
                        "containment": _contains(parent, item_bbox),
                    }
                )
    return {
        "contract_version": "learn_stage2_numbering_validation_v1",
        "display_only": True,
        "attempted_item_count": total,
        "outside_parent_bbox_count": len(outside),
        "outside_parent_bbox": outside,
        "interpretation": "Containment validation for review only; not a click gate or accuracy metric.",
    }


def _with_numbering_bboxes(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    left_nav = next((region for region in regions if "left" in str(region.get("region_id", "")).lower()), None)
    left_bbox = _bbox(left_nav.get("precise_bbox") if isinstance(left_nav, dict) else None) if left_nav else None
    result: list[dict[str, Any]] = []
    for region in regions:
        item = dict(region)
        bbox = _bbox(item.get("precise_bbox") if isinstance(item.get("precise_bbox"), dict) else item.get("bbox"))
        region_id = str(item.get("region_id") or "")
        if bbox and left_bbox and "top" in region_id.lower():
            left_right = left_bbox["x"] + left_bbox["w"]
            top_right = bbox["x"] + bbox["w"]
            vertical_overlap = min(bbox["y"] + bbox["h"], left_bbox["y"] + left_bbox["h"]) - max(bbox["y"], left_bbox["y"])
            if bbox["x"] < left_right < top_right and vertical_overlap > 0:
                bbox = {"x": left_right, "y": bbox["y"], "w": max(1, top_right - left_right), "h": bbox["h"]}
                item["numbering_bbox_reason"] = "excluded_left_nav_overlap_from_top_bar_crop"
        if bbox:
            item["numbering_bbox"] = bbox
        result.append(item)
    return result


def _cleanup_numbered_items(parsed: dict[str, Any], *, parent_bbox: dict[str, int]) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = json.loads(json.dumps(parsed, ensure_ascii=False))
    items = _items(cleaned)
    section_tops = sorted(
        _bbox(item.get("bbox"))["y"]
        for item in items
        if str(item.get("role") or "") == "section_title" and _bbox(item.get("bbox"))
    )
    output_items: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    adjusted: list[dict[str, Any]] = []
    kept_bboxes: list[dict[str, int]] = []
    for item in items:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            suppressed.append({"number": item.get("number"), "label": item.get("label"), "reason": "missing_bbox"})
            continue
        containment = _contains(parent_bbox, bbox)
        if containment < 0.15:
            suppressed.append(
                {
                    "number": item.get("number"),
                    "label": item.get("label"),
                    "reason": "outside_numbering_region",
                    "containment": containment,
                }
            )
            continue
        original_bbox = dict(bbox)
        bbox = _clip_bbox(parent_bbox, bbox)
        role = str(item.get("role") or "")
        if role == "section_title":
            label_len = max(2, len(str(item.get("label") or "")))
            bbox["w"] = min(bbox["w"], max(90, label_len * 24 + 48))
            bbox["h"] = min(max(24, bbox["h"]), 52)
        elif role in {"media_card", "button", "control", "text", "other"}:
            next_title_y = next((top for top in section_tops if top > bbox["y"] + 24), None)
            if next_title_y is not None:
                max_h = max(40, next_title_y - bbox["y"] - 30)
                bbox["h"] = min(bbox["h"], max_h)
            if role == "media_card":
                bbox["h"] = min(bbox["h"], max(80, int(bbox["w"] * 1.28)))
        if bbox != original_bbox:
            adjusted.append({"number": item.get("number"), "label": item.get("label"), "from": original_bbox, "to": bbox})
        duplicate = next((existing for existing in kept_bboxes if _iou(existing, bbox) >= 0.88), None)
        if duplicate is not None:
            suppressed.append(
                {
                    "number": item.get("number"),
                    "label": item.get("label"),
                    "reason": "duplicate_display_bbox",
                    "bbox": bbox,
                }
            )
            continue
        item["bbox"] = bbox
        output_items.append(item)
        kept_bboxes.append(bbox)
    cleaned["items"] = output_items
    return cleaned, {
        "contract_version": "learn_stage2_display_cleanup_v1",
        "display_only": True,
        "suppressed_count": len(suppressed),
        "adjusted_count": len(adjusted),
        "suppressed": suppressed,
        "adjusted": adjusted,
        "interpretation": "Post-model display cleanup tightens review boxes and removes off-region hallucinations; raw model output is still saved separately.",
    }


def _clip_bbox(outer: dict[str, int], inner: dict[str, int]) -> dict[str, int]:
    x1 = max(outer["x"], inner["x"])
    y1 = max(outer["y"], inner["y"])
    x2 = min(outer["x"] + outer["w"], inner["x"] + inner["w"])
    y2 = min(outer["y"] + outer["h"], inner["y"] + inner["h"])
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _iou(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = max(1, left["w"] * left["h"] + right["w"] * right["h"] - intersection)
    return intersection / union


def _render_numbering_overlay(
    *,
    image_path: Path,
    region_results: list[dict[str, Any]],
    out_dir: Path,
    timestamp: str,
) -> Path:
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for result in region_results:
        region_bbox = _bbox(result.get("region_bbox"))
        if region_bbox:
            _draw_box(draw, region_bbox, f"S{result.get('region_no')}: {result.get('region_label')}", color=(170, 40, 210), font=font, width=3)
        grouping = result.get("subregion_grouping") if isinstance(result.get("subregion_grouping"), dict) else {}
        grouping_parsed = grouping.get("parsed_output") if isinstance(grouping.get("parsed_output"), dict) else {}
        for group in _groups(grouping_parsed):
            group_bbox = _bbox(group.get("bbox"))
            if not group_bbox:
                continue
            _draw_box(draw, group_bbox, f"{group.get('group_id')} {group.get('role')}", color=(40, 145, 235), font=font, width=2)
        for item in _items(result.get("parsed_output")):
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            _draw_box(draw, bbox, f"{item.get('number')} {item.get('role')}", color=(236, 126, 0), font=font, width=2)
    overlay_path = out_dir / f"{image_path.stem}__stage2-numbering-model-probe__{timestamp}.png"
    canvas.save(overlay_path)
    return overlay_path


def _regions_from_stage1_model_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = report.get("parsed_output") if isinstance(report.get("parsed_output"), dict) else {}
    regions = parsed.get("regions") if isinstance(parsed.get("regions"), list) else []
    result: list[dict[str, Any]] = []
    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            continue
        bbox = region.get("precise_bbox") if isinstance(region.get("precise_bbox"), dict) else region.get("bbox")
        if not _bbox(bbox):
            continue
        item = dict(region)
        item["region_no"] = index
        result.append(item)
    return result


def _items(parsed: Any) -> list[dict[str, Any]]:
    root = parsed if isinstance(parsed, dict) else {}
    items = root.get("items") if isinstance(root.get("items"), list) else []
    return [item for item in items if isinstance(item, dict)]


def _groups(parsed: Any) -> list[dict[str, Any]]:
    root = parsed if isinstance(parsed, dict) else {}
    groups = root.get("groups") if isinstance(root.get("groups"), list) else []
    return [group for group in groups if isinstance(group, dict)]


def _renumber_items(items: list[dict[str, Any]], *, region_no: int, parent_bbox: dict[str, int] | None = None) -> list[dict[str, Any]]:
    horizontal_strip = bool(parent_bbox and parent_bbox["w"] >= parent_bbox["h"] * 3 and parent_bbox["h"] <= 140)
    if horizontal_strip:
        sorted_items = sorted(items, key=lambda item: ((_bbox(item.get("bbox")) or {"x": 0})["x"], (_bbox(item.get("bbox")) or {"y": 0})["y"]))
    else:
        sorted_items = sorted(items, key=lambda item: ((_bbox(item.get("bbox")) or {"y": 0, "x": 0})["y"], (_bbox(item.get("bbox")) or {"x": 0})["x"]))
    result: list[dict[str, Any]] = []
    for index, item in enumerate(sorted_items, start=1):
        copied = json.loads(json.dumps(item, ensure_ascii=False))
        copied["model_number"] = copied.get("number")
        copied["number"] = f"{region_no}.{index}"
        result.append(copied)
    return result


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _draw_box(draw: ImageDraw.ImageDraw, bbox: dict[str, int], label: str, *, color: tuple[int, int, int], font: Any, width: int) -> None:
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
    text = str(label or "")[:48]
    text_bbox = draw.textbbox((x1, y1), text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    label_y = max(0, y1 - text_h - 4)
    draw.rectangle((x1, label_y, x1 + text_w + 6, label_y + text_h + 4), fill=color)
    draw.text((x1 + 3, label_y + 2), text, fill=(255, 255, 255), font=font)


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _int(value.get("x"))
    y = _int(value.get("y"))
    w = _int(value.get("w", value.get("width")))
    h = _int(value.get("h", value.get("height")))
    if w <= 0 or h <= 0:
        return None
    return {"x": max(0, x), "y": max(0, y), "w": w, "h": h}


def _contains(outer: dict[str, int], inner: dict[str, int]) -> float:
    x1 = max(outer["x"], inner["x"])
    y1 = max(outer["y"], inner["y"])
    x2 = min(outer["x"] + outer["w"], inner["x"] + inner["w"])
    y2 = min(outer["y"] + outer["h"], inner["y"] + inner["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    inner_area = max(1, inner["w"] * inner["h"])
    return intersection / inner_area


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
