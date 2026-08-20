from __future__ import annotations

import json
from pathlib import Path

from app.learn.draft_review import load_learning_draft_review
from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
from app.learn.recognition import build_learning_recognition_trial
from app.learn.recognition import two_stage
from app.learn.recognition.two_stage import (
    _render_message_context_review_overlay,
    _render_two_stage_overlay,
    _stage1_5_overlay_style,
    build_stage1_region_localization_report as _build_stage1_region_localization_report,
    build_two_stage_screen_understanding as _build_two_stage_screen_understanding,
)
from app.learn.recognition.trace_input import observe_bundle_from_trace_result as _observe_bundle_from_trace_result


def _stage2_region_with_item(
    result: dict,
    item_id: str,
    *,
    region_prefix: str = "structure_region_primary_area",
) -> dict:
    regions = result["stage2_numbering"]["regions"]
    for region in regions:
        if any(item.get("item_id") == item_id for item in region.get("numbered_items", [])):
            return region
    for region in regions:
        region_id = str(region.get("region_id") or "")
        if not region_id.startswith(region_prefix):
            continue
        return region
    return next(
        item
        for item in regions
        if str(item.get("zone_id") or "") in {"primary_area", "main_content"}
    )


def _synthetic_stage1_override(
    layout_graph: dict,
    screen_inventory: list[dict],
    screen_size: dict | None = None,
) -> dict:
    items_by_id = {
        str(item.get("item_id") or ""): item
        for item in screen_inventory
        if isinstance(item, dict) and str(item.get("item_id") or "")
    }
    regions = []
    zones = layout_graph.get("zones") if isinstance(layout_graph.get("zones"), dict) else {}
    valid_zone_ids = [str(zone_id) for zone_id, zone in zones.items() if isinstance(zone, dict)]
    single_full_content_zone = len(valid_zone_ids) == 1 and valid_zone_ids[0] in {"primary_area", "main_content"}
    screen_width = int((screen_size or {}).get("width") or 0)
    screen_height = int((screen_size or {}).get("height") or 0)
    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        item_ids = [str(item_id) for item_id in zone.get("item_ids") or [] if str(item_id or "")]
        boxes = [items_by_id[item_id].get("bbox") for item_id in item_ids if item_id in items_by_id]
        boxes = [box for box in boxes if isinstance(box, dict) and box.get("w") and box.get("h")]
        if not boxes:
            continue
        left = min(int(box["x"]) for box in boxes)
        top = min(int(box["y"]) for box in boxes)
        right = max(int(box["x"]) + int(box["w"]) for box in boxes)
        bottom = max(int(box["y"]) + int(box["h"]) for box in boxes)
        slug = str(zone_id).strip().casefold().replace(" ", "_")
        region_bbox = {"x": left, "y": top, "w": right - left, "h": bottom - top}
        if single_full_content_zone and screen_width > 0 and screen_height > 0:
            region_bbox = {"x": 0, "y": 0, "w": screen_width, "h": screen_height}
        elif len(valid_zone_ids) == 1 and str(zone_id) in {"browser_chrome", "top_bar", "page_header"}:
            region_bbox = {
                "x": 0,
                "y": 0,
                "w": screen_width,
                "h": min(screen_height, max(48, bottom)),
            }
        regions.append(
            {
                "contract_version": "learn_stage1_structure_region_v1",
                "region_no": len(regions) + 1,
                "region_id": f"structure_region_{slug}",
                "label": str(zone_id).replace("_", " ").title(),
                "zone_id": str(zone_id),
                "role": str(zone_id),
                "bbox": region_bbox,
                "item_ids": item_ids,
                "item_count": len(item_ids),
                "stage": "stage1_page_structure",
                "source": "test_explicit_stage1_override",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    top_regions = [
        region for region in regions if region["zone_id"] in {"browser_chrome", "top_bar", "page_header"}
    ]
    left_regions = [region for region in regions if region["zone_id"] == "left_nav"]
    if screen_width > 0 and screen_height > 0 and len(top_regions) == 1 and len(left_regions) == 1 and len(regions) == 2:
        top_region = top_regions[0]
        left_region = left_regions[0]
        top_end = min(screen_height - 1, max(48, top_region["bbox"]["y"] + top_region["bbox"]["h"]))
        left_width = min(screen_width - 1, max(56, left_region["bbox"]["x"] + left_region["bbox"]["w"]))
        top_region["bbox"] = {"x": 0, "y": 0, "w": screen_width, "h": top_end}
        left_region["bbox"] = {
            "x": 0,
            "y": top_end,
            "w": left_width,
            "h": screen_height - top_end,
        }
        regions.append(
            {
                "contract_version": "learn_stage1_structure_region_v1",
                "region_no": 3,
                "region_id": "structure_region_main_content",
                "label": "Main Content",
                "zone_id": "main_content",
                "role": "main_content",
                "bbox": {
                    "x": left_width,
                    "y": top_end,
                    "w": screen_width - left_width,
                    "h": screen_height - top_end,
                },
                "item_ids": [],
                "item_count": 0,
                "stage": "stage1_page_structure",
                "source": "test_authoritative_partition_fixture",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return {
        "contract_version": "learn_stage1_structure_regions_v1",
        "region_count": len(regions),
        "structure_regions": regions,
        "source": "test_explicit_stage1_override",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def build_two_stage_screen_understanding(**kwargs) -> dict:
    bundle = kwargs.get("bundle") if isinstance(kwargs.get("bundle"), dict) else {}
    kwargs.setdefault(
        "stage1_structure_override",
        _synthetic_stage1_override(
            kwargs["layout_graph"],
            kwargs["screen_inventory"],
            bundle.get("screen_size") if isinstance(bundle.get("screen_size"), dict) else None,
        ),
    )
    return _build_two_stage_screen_understanding(**kwargs)


def build_stage1_region_localization_report(**kwargs) -> dict:
    kwargs.setdefault(
        "stage1_structure_override",
        _synthetic_stage1_override(kwargs["layout_graph"], kwargs["screen_inventory"]),
    )
    return _build_stage1_region_localization_report(**kwargs)


def test_bottom_status_bar_candidate_is_not_promoted_to_tile_card_parent() -> None:
    assert not two_stage._looks_like_tile_card_parent_candidate(
        {
            "item_id": "card_bottom_bar_0",
            "label": "第 1 行，第 1 列 100% Windows (CRLF)",
            "role": "recommendation_item",
            "item_type": "review_only",
            "bbox": {"x": 1200, "y": 742, "w": 400, "h": 58},
        }
    )


def test_bottom_status_bar_candidate_is_normalized_to_read_only_structure_evidence() -> None:
    assert two_stage._normalized_structural_evidence_role(
        {
            "item_id": "card_bottom_bar_0",
            "role": "recommendation_item",
            "layout": "bottom_bar",
        },
        "recommendation_item",
    ) == "status_bar_evidence"


def test_direct_top_bar_refinement_keeps_leading_edge_controls(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "top_bar_with_leading_controls.png"
    image = Image.new("RGB", (800, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 30, 30), fill="black")
    draw.rectangle((8, 55, 30, 78), fill="black")
    for x in (100, 150, 200, 250, 300, 350):
        draw.rectangle((x, 18, x + 20, 38), fill="black")
    image.save(image_path)
    numbered_items = [
        {
            "number": f"1.{index}",
            "item_id": f"control_{index}",
            "label": f"control {index}",
            "role": "control",
            "bbox": {"x": x - 6, "y": 12, "w": 34, "h": 32},
            "children": [],
        }
        for index, x in enumerate((100, 150, 200, 250), start=1)
    ]

    refined, report = two_stage._refine_direct_region_small_controls(
        numbered_items,
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 800, "h": 90},
        region_family="top_bar",
    )

    assert report["leading_edge_candidate_count"] >= 2
    assert sum(1 for item in refined if item["bbox"]["x"] < 56) >= 2


def test_primary_region_recovers_dense_embedded_top_control_strip(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "embedded_top_controls.png"
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for x in (50, 95, 140, 240, 420, 600, 720):
        draw.rectangle((x, 16, x + 28, 46), fill="black")
    draw.rectangle((120, 200, 300, 420), outline="black", width=4)
    image.save(image_path)
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "content_card",
            "label": "Content card",
            "role": "media_card",
            "item_type": "review_only",
            "bbox": {"x": 120, "y": 200, "w": 180, "h": 220},
        }
    ]

    refined, report = two_stage._refine_primary_embedded_top_controls(
        numbered_items,
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 800, "h": 600},
    )

    controls = [item for item in refined if item.get("source") == "embedded_top_control_visual_segmenter"]
    assert report["applied"] is True
    assert report["recovered_control_count"] >= 7
    assert len(controls) >= 7
    assert all(item["bbox"]["y"] < 80 for item in controls)
    assert any(item.get("item_id") == "content_card" for item in refined)


def test_primary_region_does_not_invent_embedded_top_strip_below_existing_header(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "content_below_header.png"
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for x in (50, 95, 140, 240, 420, 600, 720):
        draw.rectangle((x, 96, x + 28, 126), fill="black")
    image.save(image_path)

    refined, report = two_stage._refine_primary_embedded_top_controls(
        [],
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 80, "w": 800, "h": 520},
    )

    assert refined == []
    assert report["applied"] is False
    assert report["reason"] == "primary_region_does_not_start_at_window_top"

def test_direct_sidebar_refinement_adds_unmatched_visual_control(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "sidebar_with_unmatched_bottom_control.png"
    image = Image.new("RGB", (100, 800), "white")
    draw = ImageDraw.Draw(image)
    centers = (40, 100, 160, 220, 280, 340, 740)
    for center_y in centers:
        draw.rectangle((18, center_y - 10, 38, center_y + 10), fill="black")
    image.save(image_path)
    numbered_items = [
        {
            "number": f"2.{index}",
            "item_id": f"nav_{index}",
            "label": f"nav {index}",
            "role": "nav_item",
            "bbox": {"x": 12, "y": center_y - 16, "w": 40, "h": 32},
            "children": [],
        }
        for index, center_y in enumerate(centers[:-1], start=1)
    ]

    refined, report = two_stage._refine_direct_region_small_controls(
        numbered_items,
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 100, "h": 800},
        region_family="left_bar",
    )

    assert report["unmatched_visual_candidate_count"] == 1
    assert any(item["bbox"]["y"] > 700 for item in refined)


def test_unmatched_direct_visual_control_merges_overlapping_ocr_label() -> None:
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "ocr_bundle_text_37",
            "label": "\u5927\u5c0f",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 713, "y": 206, "w": 34, "h": 20},
            "children": [],
            "source": "ocr_bundle",
        },
        {
            "number": "1.2",
            "item_id": "unrelated_text",
            "label": "modified date",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 520, "y": 206, "w": 110, "h": 20},
            "children": [],
            "source": "ocr_bundle",
        },
    ]

    refined, unmatched_count = two_stage._append_unmatched_direct_visual_controls(
        numbered_items,
        [{"x": 731, "y": 178, "w": 72, "h": 52}],
        region_family="top_bar",
    )

    merged = next(item for item in refined if item["label"] == "\u5927\u5c0f")
    assert unmatched_count == 0
    assert merged["role"] == "control"
    assert merged["item_type"] == "visual_control"
    assert merged["bbox"] == {"x": 713, "y": 178, "w": 90, "h": 52}
    assert merged["source"] == "visual_control_with_ocr_label"
    assert merged["calibration_target_kind"] == "atomic_control_parent"
    assert merged["children"][0]["item_id"] == "ocr_bundle_text_37"
    assert any(item["item_id"] == "unrelated_text" for item in refined)


def test_semantic_container_cannot_consume_atomic_visual_controls() -> None:
    numbered_items = [
        {
            "number": "2.1",
            "item_id": "semantic_navigation_menu",
            "label": "Navigation menu",
            "role": "navigation",
            "item_type": "container",
            "bbox": {"x": 10, "y": 20, "w": 52, "h": 720},
            "source": "model_semantic_proposal",
            "evidence_level": "semantic_region_only",
            "review_only": True,
        }
    ]
    candidates = [
        {"x": 18, "y": 48, "w": 32, "h": 30},
        {"x": 18, "y": 92, "w": 32, "h": 30},
        {"x": 18, "y": 136, "w": 32, "h": 30},
    ]

    refined, unmatched_count = two_stage._append_unmatched_direct_visual_controls(
        numbered_items,
        candidates,
        region_family="left_bar",
    )

    assert unmatched_count == 3
    assert [
        item["bbox"]
        for item in refined
        if item.get("source") == "visual_small_control_unmatched_candidate"
    ] == candidates


def test_stage2_dual_streams_keep_atomic_objects_independent_from_semantic_groups() -> None:
    numbered_items = [
        {
            "item_id": "visual_control_1",
            "label": "Chat",
            "role": "nav_item",
            "item_type": "visual_control",
            "bbox": {"x": 18, "y": 48, "w": 32, "h": 30},
            "source": "visual_small_control_unmatched_candidate",
            "review_only": True,
        },
        {
            "item_id": "ocr_chat_label",
            "label": "Chat",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 22, "y": 54, "w": 20, "h": 12},
            "source": "ocr_bundle",
            "review_only": True,
        },
    ]
    semantic_groups = [
        {
            "group_id": "navigation_group",
            "label": "Navigation",
            "role": "navigation_group",
            "bbox": {"x": 10, "y": 20, "w": 52, "h": 720},
            "member_item_ids": ["visual_control_1", "ocr_chat_label"],
            "source": "model_semantic_proposal",
        }
    ]
    ownership_audit = {
        "source_item_owner_map": {
            "visual_control_1": "navigation_group",
            "ocr_chat_label": "navigation_group",
        }
    }

    streams = two_stage._build_stage2_dual_streams(
        numbered_items=numbered_items,
        semantic_groups=semantic_groups,
        ownership_audit=ownership_audit,
    )

    assert streams["contract_version"] == "learn_stage2_dual_streams_v1"
    assert {item["object_id"] for item in streams["visual_objects"]} == {
        "visual_control_1",
        "ocr_chat_label",
    }
    assert [group["group_id"] for group in streams["semantic_groups"]] == ["navigation_group"]
    assert len(streams["associations"]) == 2
    assert streams["integrity"] == {
        "visual_object_count": 2,
        "semantic_group_count": 1,
        "control_parent_count": 0,
        "associated_count": 2,
        "review_only_count": 0,
        "explicitly_rejected_count": 0,
        "silent_loss_count": 0,
    }
    assert all(item["disposition"] == "associated" for item in streams["visual_objects"])


def test_non_bar_visual_candidates_stay_in_evidence_stream_instead_of_numbering(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from PIL import Image

    image_path = tmp_path / "conversation_list.png"
    Image.new("RGB", (500, 600), "white").save(image_path)
    candidates = [
        {"x": 30, "y": 40, "w": 34, "h": 30},
        {"x": 30, "y": 92, "w": 34, "h": 30},
    ]
    monkeypatch.setattr(two_stage, "_visual_small_control_boxes", lambda **_: candidates)

    refined, report = two_stage._refine_direct_region_small_controls(
        [
            {
                "number": "2.1",
                "item_id": "conversation_title",
                "label": "Alice",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 82, "y": 42, "w": 80, "h": 20},
                "source": "ocr_bundle",
            }
        ],
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 500, "h": 600},
        region_family="center",
    )

    assert [item["item_id"] for item in refined] == ["conversation_title"]
    assert report["candidate_compilation_status"] == "evidence_only"
    assert report["uncompiled_visual_candidate_count"] == 2
    assert report["evidence_only_visual_candidates"] == candidates


def test_dual_streams_preserve_uncompiled_visual_candidate_evidence() -> None:
    streams = two_stage._build_stage2_dual_streams(
        numbered_items=[],
        semantic_groups=[],
        ownership_audit={},
        visual_candidates=[{"x": 30, "y": 40, "w": 34, "h": 30}],
    )

    assert streams["visual_objects"] == [
        {
            "object_id": "raw_visual_candidate_1",
            "label": "visual candidate 1",
            "role": "visual_candidate",
            "item_type": "visual_candidate",
            "bbox": {"x": 30, "y": 40, "w": 34, "h": 30},
            "source": "visual_small_control_candidate_stream",
            "disposition": "review_only",
            "display_only": True,
            "execute_binding_enabled": False,
        }
    ]
    assert streams["integrity"]["silent_loss_count"] == 0


def test_atomic_control_parents_use_complete_factual_hit_areas_and_attach_text_evidence() -> None:
    numbered_items = [
        {
            "item_id": "percent_button",
            "label": "Percent",
            "role": "button",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 347, "w": 138, "h": 104},
            "source": "structure_region_item",
        },
        {
            "item_id": "percent_text",
            "label": "%",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 72, "y": 388, "w": 20, "h": 24},
            "source": "ocr_bundle",
        },
        {
            "item_id": "clear_button",
            "label": "Clear",
            "role": "button",
            "item_type": "actionable",
            "bbox": {"x": 152, "y": 347, "w": 137, "h": 104},
            "source": "structure_region_item",
        },
        {
            "item_id": "clear_text",
            "label": "C",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 214, "y": 389, "w": 15, "h": 23},
            "source": "ocr_bundle",
        },
    ]

    parents = two_stage._atomic_control_parent_objects(
        numbered_items=numbered_items,
        visual_candidates=[],
        region_bbox={"x": 0, "y": 320, "w": 570, "h": 680},
        region_family="main_content",
    )

    assert [parent["bbox"] for parent in parents] == [
        {"x": 12, "y": 347, "w": 138, "h": 104},
        {"x": 152, "y": 347, "w": 137, "h": 104},
    ]
    assert parents[0]["member_object_ids"] == ["percent_button", "percent_text"]
    assert parents[1]["member_object_ids"] == ["clear_button", "clear_text"]
    assert all(parent["role"] == "atomic_control_parent" for parent in parents)
    assert all(parent["bbox_policy"] == "factual_control_hit_area" for parent in parents)


def test_atomic_control_parent_can_use_visual_background_with_ocr_evidence() -> None:
    parents = two_stage._atomic_control_parent_objects(
        numbered_items=[
            {
                "item_id": "search_text",
                "label": "Search",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 104, "y": 56, "w": 50, "h": 18},
                "source": "ocr_bundle",
            }
        ],
        visual_candidates=[{"x": 92, "y": 44, "w": 96, "h": 42}],
        region_bbox={"x": 80, "y": 20, "w": 420, "h": 560},
        region_family="main_content",
    )

    assert len(parents) == 1
    assert parents[0]["bbox"] == {"x": 92, "y": 44, "w": 96, "h": 42}
    assert parents[0]["member_object_ids"] == ["search_text"]
    assert parents[0]["bbox_policy"] == "visual_background_with_internal_evidence"


def test_atomic_control_parents_merge_repeated_visual_anchors_with_aligned_row_text() -> None:
    numbered_items = [
        {
            "item_id": "row_1_title",
            "label": "Alice",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 118, "y": 108, "w": 62, "h": 18},
        },
        {
            "item_id": "row_1_preview",
            "label": "Hello",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 118, "y": 130, "w": 94, "h": 18},
        },
        {
            "item_id": "row_2_title",
            "label": "Bob",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 118, "y": 172, "w": 52, "h": 18},
        },
        {
            "item_id": "row_2_preview",
            "label": "World",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 118, "y": 194, "w": 90, "h": 18},
        },
        {
            "item_id": "row_3_title",
            "label": "Carol",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 118, "y": 236, "w": 58, "h": 18},
        },
    ]
    visual_candidates = [
        {"x": 66, "y": 104, "w": 46, "h": 42},
        {"x": 65, "y": 168, "w": 46, "h": 42},
        {"x": 66, "y": 232, "w": 46, "h": 42},
    ]

    parents = two_stage._atomic_control_parent_objects(
        numbered_items=numbered_items,
        visual_candidates=visual_candidates,
        region_bbox={"x": 55, "y": 80, "w": 190, "h": 240},
        region_family="main_content",
    )

    repeated_rows = [
        parent
        for parent in parents
        if parent["source"] == "repeated_visual_anchor_with_row_evidence"
    ]
    assert len(repeated_rows) == 3
    assert repeated_rows[0]["bbox"] == {"x": 66, "y": 104, "w": 146, "h": 44}
    assert repeated_rows[0]["member_object_ids"] == [
        "raw_visual_candidate_1",
        "row_1_title",
        "row_1_preview",
    ]
    assert repeated_rows[1]["bbox"] == {"x": 65, "y": 168, "w": 143, "h": 44}
    assert repeated_rows[2]["bbox"] == {"x": 66, "y": 232, "w": 110, "h": 42}


def test_atomic_control_parents_do_not_promote_misaligned_visual_fragments_as_rows() -> None:
    parents = two_stage._atomic_control_parent_objects(
        numbered_items=[
            {
                "item_id": "text_1",
                "label": "One",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 120, "y": 108, "w": 40, "h": 18},
            },
            {
                "item_id": "text_2",
                "label": "Two",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 120, "y": 172, "w": 40, "h": 18},
            },
            {
                "item_id": "text_3",
                "label": "Three",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 120, "y": 236, "w": 48, "h": 18},
            },
        ],
        visual_candidates=[
            {"x": 66, "y": 104, "w": 46, "h": 42},
            {"x": 18, "y": 168, "w": 24, "h": 24},
            {"x": 180, "y": 232, "w": 62, "h": 30},
        ],
        region_bbox={"x": 0, "y": 80, "w": 260, "h": 240},
        region_family="main_content",
    )

    assert all(parent["source"] != "repeated_visual_anchor_with_row_evidence" for parent in parents)


def test_atomic_control_parent_does_not_infer_a_hit_area_from_ocr_alone() -> None:
    parents = two_stage._atomic_control_parent_objects(
        numbered_items=[
            {
                "item_id": "orphan_text",
                "label": "Unresolved",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 104, "y": 56, "w": 70, "h": 18},
                "source": "ocr_bundle",
            }
        ],
        visual_candidates=[],
        region_bbox={"x": 80, "y": 20, "w": 420, "h": 560},
        region_family="main_content",
    )

    assert parents == []


def test_atomic_control_parent_rejects_visual_box_that_only_tightly_wraps_ocr() -> None:
    parents = two_stage._atomic_control_parent_objects(
        numbered_items=[
            {
                "item_id": "timestamp_text",
                "label": "13:54",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 202, "y": 105, "w": 34, "h": 17},
                "source": "ocr_bundle",
            }
        ],
        visual_candidates=[{"x": 200, "y": 99, "w": 39, "h": 28}],
        region_bbox={"x": 70, "y": 40, "w": 180, "h": 800},
        region_family="main_content",
    )

    assert parents == []


def test_atomic_control_parent_rejects_thin_action_text_as_complete_hit_area() -> None:
    parents = two_stage._atomic_control_parent_objects(
        numbered_items=[
            {
                "item_id": "search_action_text",
                "label": "Search",
                "role": "button",
                "item_type": "actionable",
                "bbox": {"x": 76, "y": 58, "w": 49, "h": 17},
                "source": "structure_region_item",
            }
        ],
        visual_candidates=[],
        region_bbox={"x": 70, "y": 40, "w": 180, "h": 800},
        region_family="main_content",
    )

    assert parents == []


def test_dual_stream_keeps_atomic_control_parents_without_semantic_containers() -> None:
    control_parents = [
        {
            "object_id": "control_parent_search",
            "label": "Search",
            "role": "atomic_control_parent",
            "bbox": {"x": 92, "y": 44, "w": 96, "h": 42},
            "member_object_ids": ["search_text"],
            "source": "visual_candidate_with_internal_evidence",
            "display_only": True,
            "execute_binding_enabled": False,
        }
    ]

    streams = two_stage._build_stage2_dual_streams(
        numbered_items=[
            {
                "item_id": "search_text",
                "label": "Search",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 104, "y": 56, "w": 50, "h": 18},
                "source": "ocr_bundle",
            }
        ],
        semantic_groups=[],
        ownership_audit={},
        control_parents=control_parents,
    )

    assert streams["semantic_groups"] == []
    assert streams["control_parents"] == control_parents
    assert streams["control_associations"] == [
        {
            "object_id": "search_text",
            "control_parent_id": "control_parent_search",
            "relationship": "evidence_for_control_parent",
            "source": "atomic_control_parent_synthesis",
        }
    ]
    assert streams["visual_objects"][0]["disposition"] == "review_only"
    assert streams["integrity"]["control_parent_count"] == 1


def test_ownership_audit_preserves_deduplicated_source_item_lineage() -> None:
    audit = two_stage._expand_ownership_source_aliases(
        [
            {
                "item_id": "winner_item",
                "merged_source_item_ids": ["winner_item", "suppressed_source_item"],
            }
        ],
        {"source_item_owner_map": {"winner_item": "control_parent"}},
    )

    assert audit["source_item_owner_map"] == {
        "winner_item": "control_parent",
        "suppressed_source_item": "control_parent",
    }
    assert audit["source_item_alias_map"] == {"suppressed_source_item": "winner_item"}
    assert audit["source_alias_owner_count"] == 1


def test_stage2_numbering_publishes_dual_stream_contract() -> None:
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_left_bar",
                "zone_id": "left_bar",
                "label": "Left bar",
                "bbox": {"x": 0, "y": 0, "w": 80, "h": 400},
                "item_ids": ["chat_button"],
            }
        ],
        items_by_id={
            "chat_button": {
                "item_id": "chat_button",
                "label": "Chat",
                "role": "nav_item",
                "item_type": "actionable",
                "bbox": {"x": 18, "y": 48, "w": 32, "h": 30},
                "grounding_eligible": True,
            }
        },
    )

    streams = result["regions"][0]["stage2_streams"]
    assert streams["contract_version"] == "learn_stage2_dual_streams_v1"
    assert [item["object_id"] for item in streams["visual_objects"]] == ["chat_button"]
    assert streams["integrity"]["silent_loss_count"] == 0


def test_stage2_numbering_publishes_atomic_control_parents_for_main_content() -> None:
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "zone_id": "main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 300, "w": 570, "h": 700},
                "item_ids": ["percent_button", "percent_text"],
            }
        ],
        items_by_id={
            "percent_button": {
                "item_id": "percent_button",
                "label": "Percent",
                "role": "button",
                "item_type": "actionable",
                "bbox": {"x": 12, "y": 347, "w": 138, "h": 104},
                "grounding_eligible": True,
            },
            "percent_text": {
                "item_id": "percent_text",
                "label": "%",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 72, "y": 388, "w": 20, "h": 24},
                "grounding_eligible": False,
            },
        },
    )

    region = result["regions"][0]
    assert region["control_parents"][0]["bbox"] == {"x": 12, "y": 347, "w": 138, "h": 104}
    assert region["stage2_streams"]["control_parents"] == region["control_parents"]
    assert region["stage2_streams"]["integrity"]["control_parent_count"] == 1


def test_stage2_numbering_suppresses_oversized_uia_structural_container() -> None:
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "zone_id": "main_content",
                "label": "Main content",
                "bbox": {"x": 100, "y": 80, "w": 900, "h": 600},
                "item_ids": ["root_pane", "real_button"],
            }
        ],
        items_by_id={
            "root_pane": {
                "item_id": "root_pane",
                "label": "Application content",
                "role": "pane",
                "item_type": "pane",
                "source": "uia",
                "bbox": {"x": 100, "y": 80, "w": 900, "h": 600},
                "grounding_eligible": False,
            },
            "real_button": {
                "item_id": "real_button",
                "label": "Play",
                "role": "button",
                "item_type": "actionable",
                "source": "uia",
                "bbox": {"x": 140, "y": 120, "w": 90, "h": 36},
                "grounding_eligible": True,
            },
        },
    )

    region = result["regions"][0]
    assert [item["item_id"] for item in region["numbered_items"]] == ["real_button"]
    assert region["structural_container_suppression"] == {
        "contract_version": "learn_stage2_structural_container_suppression_v1",
        "suppressed_count": 1,
        "suppressed_item_ids": ["root_pane"],
        "reason_counts": {"oversized_uia_structural_container": 1},
        "policy": "structural UIA containers covering nearly the active region remain context evidence and are not numbered as atomic targets",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    assert all(
        "root_pane" not in group.get("member_item_ids", [])
        for group in region["subregion_groups"]
    )


def test_semantic_container_is_not_a_precise_calibration_target() -> None:
    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(
        {
            "numbered_items": [
                {
                    "item_id": "semantic_navigation_menu",
                    "label": "Navigation menu",
                    "role": "navigation",
                    "item_type": "container",
                    "bbox": {"x": 10, "y": 20, "w": 52, "h": 720},
                    "source": "model_semantic_proposal",
                    "evidence_level": "semantic_region_only",
                },
                {
                    "item_id": "chat_button",
                    "label": "Chat",
                    "role": "nav_item",
                    "item_type": "visual_control",
                    "bbox": {"x": 18, "y": 48, "w": 32, "h": 30},
                    "source": "visual_small_control_unmatched_candidate",
                    "calibration_target_kind": "atomic_control_parent",
                },
            ],
            "subregion_groups": [],
        }
    )

    assert [item["item_id"] for item in calibratable] == ["chat_button"]
    assert [item["item_id"] for item in child_evidence] == ["semantic_navigation_menu"]
    assert child_evidence[0]["display_hierarchy"]["demotion_reason"] == (
        "semantic_container_is_not_an_atomic_calibration_target"
    )


def test_atomic_control_parent_replaces_member_fragments_in_precise_calibration_partition() -> None:
    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(
        {
            "numbered_items": [
                {
                    "item_id": "avatar_1",
                    "label": "Avatar",
                    "role": "icon",
                    "bbox": {"x": 40, "y": 90, "w": 42, "h": 42},
                },
                {
                    "item_id": "title_1",
                    "label": "Conversation title",
                    "role": "text",
                    "bbox": {"x": 94, "y": 98, "w": 130, "h": 20},
                },
                {
                    "item_id": "new_chat",
                    "label": "New chat",
                    "role": "button",
                    "item_type": "actionable",
                    "bbox": {"x": 250, "y": 32, "w": 80, "h": 34},
                },
            ],
            "control_parents": [
                {
                    "object_id": "control_parent_row_1",
                    "final_control_parent_id": "final-control:rev:0001",
                    "label": "Conversation row",
                    "role": "atomic_control_parent",
                    "bbox": {"x": 40, "y": 90, "w": 230, "h": 46},
                    "member_object_ids": ["avatar_1", "title_1"],
                    "source": "repeated_visual_anchor_with_row_evidence",
                }
            ],
            "subregion_groups": [],
        }
    )

    assert [item["item_id"] for item in calibratable] == ["new_chat", "control_parent_row_1"]
    parent = calibratable[1]
    assert parent["source_item_id"] == "control_parent_row_1"
    assert parent["final_item_id"] == "final-control:rev:0001"
    assert parent["calibration_target_kind"] == "atomic_control_parent"
    assert [child["child_id"] for child in parent["children"]] == ["avatar_1", "title_1"]
    assert {item["item_id"] for item in child_evidence} == {"avatar_1", "title_1"}


def test_tile_card_row_with_individual_card_parents_is_structural_detail_only() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "zone_id": "primary_area",
        "label": "Primary Area",
        "bbox": {"x": 0, "y": 0, "w": 700, "h": 400},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "card_a",
            "label": "Card A",
            "role": "card",
            "item_type": "card",
            "source": "visual_card_segmenter",
            "bbox": {"x": 40, "y": 80, "w": 220, "h": 100},
        },
        {
            "number": "1.2",
            "item_id": "card_a_text",
            "label": "Card A details",
            "role": "text",
            "bbox": {"x": 70, "y": 110, "w": 150, "h": 24},
        },
        {
            "number": "1.3",
            "item_id": "card_b",
            "label": "Card B",
            "role": "card",
            "item_type": "card",
            "source": "visual_card_segmenter",
            "bbox": {"x": 300, "y": 80, "w": 220, "h": 100},
        },
        {
            "number": "1.4",
            "item_id": "card_b_text",
            "label": "Card B details",
            "role": "text",
            "bbox": {"x": 330, "y": 110, "w": 150, "h": 24},
        },
    ]

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=numbered_items,
    )
    row = next(group for group in groups if group["role"] == "tile_card_group")
    card_parents = [group for group in groups if group["role"] == "tile_card_parent"]

    assert len(card_parents) == 2
    assert set(row["child_group_ids"]) == {group["group_id"] for group in card_parents}
    hierarchy = two_stage._group_display_hierarchy(
        row,
        {item["item_id"]: item for item in numbered_items},
    )
    assert hierarchy["display_layer"] == "structural_container"
    assert hierarchy["render_in_main_overlay"] is False


def test_notice_parent_does_not_use_tile_card_with_notification_text_as_notice_anchor() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "zone_id": "primary_area",
        "label": "Primary Area",
    }
    numbered_items = [
        {
            "number": "2.1",
            "item_id": "system_tile",
            "label": "显示、声音、通知、电源",
            "role": "tile_card",
            "bbox": {"x": 90, "y": 310, "w": 210, "h": 64},
        },
        {
            "number": "2.2",
            "item_id": "personalization_title",
            "label": "个性化",
            "role": "text",
            "bbox": {"x": 140, "y": 420, "w": 64, "h": 24},
        },
        {
            "number": "2.3",
            "item_id": "personalization_body",
            "label": "背景、锁屏、颜色",
            "role": "text",
            "bbox": {"x": 140, "y": 446, "w": 120, "h": 22},
        },
    ]

    groups = two_stage._notice_parent_groups(region=region, numbered_items=numbered_items)

    assert groups == []


def test_notice_parent_requires_explicit_notice_semantics_in_main_content() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "zone_id": "primary_area",
        "label": "Primary Area",
    }
    numbered_items = [
        {
            "number": "2.1",
            "item_id": "system_tile_text",
            "label": "显示、声音、通知、电源",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 140, "y": 330, "w": 180, "h": 24},
        },
        {
            "number": "2.2",
            "item_id": "personalization_title",
            "label": "个性化",
            "role": "text",
            "bbox": {"x": 140, "y": 418, "w": 64, "h": 24},
        },
        {
            "number": "2.3",
            "item_id": "personalization_body",
            "label": "背景、锁屏、颜色",
            "role": "text",
            "bbox": {"x": 140, "y": 444, "w": 120, "h": 22},
        },
    ]

    groups = two_stage._notice_parent_groups(region=region, numbered_items=numbered_items)

    assert groups == []


def test_observe_bundle_from_trace_preserves_screen_reading_texts(tmp_path):
    trace_path = tmp_path / "observe_trace.json"
    result = {
        "app_name": "calculator",
        "image_path": "screen.png",
        "image_size": {"width": 1000, "height": 760},
        "screen_reading": {
            "texts": [
                {
                    "text": "Ad astra",
                    "bbox": {"x": 772, "y": 420, "w": 64, "h": 20},
                    "source": "ocr_fallback",
                }
            ]
        },
    }

    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)

    assert bundle["screen_reading"]["texts"][0]["text"] == "Ad astra"
    assert bundle["screen_reading"]["texts"][0]["bbox"] == {"x": 772, "y": 420, "w": 64, "h": 20}
    assert bundle["app_name"] == "calculator"


def test_observe_bundle_from_trace_preserves_top_level_model_semantics(tmp_path):
    trace_path = tmp_path / "observe_trace.json"
    result = {
        "app_name": "demo",
        "image_path": "screen.png",
        "image_size": {"width": 1200, "height": 800},
        "screen_summary": "Media library with repeated album cards",
        "state_guess": "library home",
        "interface_classification": {
            "category": "media_catalog",
            "confidence": 0.93,
            "reason": "repeated visual media cards",
        },
        "modules": [{"id": "albums", "role_guess": "card"}],
        "ui": {"summary": {"module_count": 1}},
    }

    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)

    assert bundle["screen_reading"]["screen_summary"] == result["screen_summary"]
    assert bundle["screen_reading"]["state_guess"] == "library home"
    assert bundle["screen_reading"]["interface_classification"]["category"] == "media_catalog"
    assert bundle["screen_reading"]["modules"] == result["modules"]
    assert bundle["screen_reading"]["ui"] == result["ui"]


def test_interface_classification_selects_review_only_class_policy() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "media_catalog",
                    "confidence": 0.92,
                    "reason": "repeated media cards",
                }
            }
        }
    )

    assert classification["category"] == "media_catalog"
    assert classification["source"] == "model_output"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "visual_card_first"
    assert classification["class_rule_profile"]["allow_media_card_synthesis"] is True
    assert classification["display_only"] is True
    assert classification["artifact_is_authorization"] is False


def test_aggregate_portal_classification_keeps_independent_module_policy() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "aggregate_portal",
                    "confidence": 0.94,
                    "reason": "peer weather, markets, sports, news, and media modules",
                    "structure_signals": {
                        "mixed_content_modules": True,
                        "feed_items": False,
                        "news_items": True,
                        "media_cards": True,
                    },
                }
            }
        }
    )

    assert classification["category"] == "aggregate_portal"
    assert classification["status"] == "accepted"
    assert classification["evidence_validation_status"] == "validated"
    assert (
        classification["class_rule_profile"]["primary_content_strategy"]
        == "independent_content_modules"
    )
    assert classification["class_rule_profile"]["allow_media_card_synthesis"] is False
    assert classification["artifact_is_authorization"] is False


def test_media_feed_classification_enables_visual_card_candidate_check() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "feed_workspace",
                    "confidence": 0.92,
                    "reason": "repeated visual media cards in a feed",
                    "structure_signals": {
                        "feed_items": True,
                        "media_cards": True,
                    },
                }
            }
        }
    )

    assert classification["status"] == "accepted"
    assert classification["evidence_validation_status"] == "validated"
    assert (
        classification["class_rule_profile"]["primary_content_strategy"]
        == "visual_feed_card_first"
    )
    assert (
        classification["class_rule_profile"]["allow_media_card_synthesis"]
        is True
    )


def test_text_feed_classification_keeps_visual_card_synthesis_disabled() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "feed_workspace",
                    "confidence": 0.92,
                    "reason": "repeated text posts",
                    "structure_signals": {
                        "feed_items": True,
                        "media_cards": False,
                    },
                }
            }
        }
    )

    assert classification["status"] == "accepted"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "feed_items"
    assert (
        classification["class_rule_profile"]["allow_media_card_synthesis"]
        is False
    )


def test_interface_classification_reads_actual_parser_vision_source() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "sources": {
                "vision": {
                    "interface_classification": {
                        "category": "conversation_workspace",
                        "confidence": 0.94,
                        "reason": "conversation rows beside an empty detail pane",
                        "structure_signals": {
                            "people_or_conversation_rows": True,
                            "media_cards": False,
                        },
                    }
                }
            }
        }
    )

    assert classification["category"] == "conversation_workspace"
    assert classification["source"] == "model_output"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "conversation_rows"


def test_interface_classification_selects_dense_table_policy_for_file_browser() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "file_browser",
                    "confidence": 0.91,
                    "reason": "navigation tree beside a dense multi-column file list",
                }
            }
        }
    )

    assert classification["category"] == "file_browser"
    assert classification["source"] == "model_output"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "row_table_first"
    assert classification["class_rule_profile"]["allow_media_card_synthesis"] is False


def test_interface_classification_rejects_local_form_inside_dominant_workspace() -> None:
    inventory = [
        {
            "item_id": "change_list",
            "role": "list",
            "item_type": "list",
            "bbox": {"x": 0, "y": 80, "w": 280, "h": 640},
        },
        {
            "item_id": "diff_document",
            "role": "document",
            "item_type": "document",
            "bbox": {"x": 280, "y": 80, "w": 920, "h": 640},
        },
        *[
            {
                "item_id": f"diff_line_{index}",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 310, "y": 100 + index * 20, "w": 520, "h": 18},
            }
            for index in range(20)
        ],
        {
            "item_id": "summary",
            "role": "input",
            "item_type": "input",
            "bbox": {"x": 20, "y": 600, "w": 220, "h": 34},
        },
        {
            "item_id": "description",
            "role": "input",
            "item_type": "textarea",
            "bbox": {"x": 20, "y": 640, "w": 220, "h": 54},
        },
        {
            "item_id": "summary_review_copy",
            "role": "text_input",
            "item_type": "review_only",
            "bbox": {"x": 20, "y": 600, "w": 220, "h": 34},
        },
        {
            "item_id": "description_review_copy",
            "role": "text_input",
            "item_type": "review_only",
            "bbox": {"x": 20, "y": 640, "w": 220, "h": 54},
        },
    ]

    classification = two_stage.classify_interface_surface(
        {
            "image_size": {"width": 1200, "height": 800},
            "screen_reading": {
                "interface_classification": {
                    "category": "form_workflow",
                    "confidence": 0.99,
                    "reason": "visible summary and description fields",
                    "structure_signals": {"form_fields": True},
                }
            },
        },
        screen_inventory=inventory,
    )

    assert classification["category"] == "generic"
    assert classification["status"] == "needs_review"
    assert classification["evidence_validation_status"] == "local_form_subordinate_to_dominant_workspace"
    assert classification["rejected_model_category"] == "form_workflow"


def test_interface_classification_keeps_form_without_dominant_workspace_evidence() -> None:
    inventory = [
        {
            "item_id": f"field_{index}",
            "role": "input",
            "item_type": "input",
            "bbox": {"x": 300, "y": 140 + index * 70, "w": 420, "h": 42},
        }
        for index in range(3)
    ]

    classification = two_stage.classify_interface_surface(
        {
            "screen_size": {"width": 1000, "height": 700},
            "screen_reading": {
                "interface_classification": {
                    "category": "form_workflow",
                    "confidence": 0.92,
                    "structure_signals": {"form_fields": True},
                }
            },
        },
        screen_inventory=inventory,
    )

    assert classification["category"] == "form_workflow"
    assert classification["status"] == "accepted"


def test_interface_classification_rejects_file_browser_when_model_signals_describe_people_rows() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "file_browser",
                    "confidence": 0.95,
                    "reason": "list of friends with online status",
                    "structure_signals": {
                        "file_or_folder_rows": False,
                        "people_or_conversation_rows": True,
                    },
                }
            }
        }
    )

    assert classification["category"] == "generic"
    assert classification["status"] == "needs_review"
    assert classification["rejected_model_category"] == "file_browser"
    assert classification["evidence_validation_status"] == "category_signal_conflict"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "evidence_balanced"


def test_interface_classification_rejects_unknown_model_category_to_generic() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "interface_classification": {
                    "category": "apple_music_special",
                    "confidence": 0.99,
                    "reason": "application-specific category",
                }
            }
        }
    )

    assert classification["category"] == "generic"
    assert classification["status"] == "needs_review"
    assert classification["class_rule_profile"]["primary_content_strategy"] == "evidence_balanced"
    assert classification["rejected_model_category"] == "apple_music_special"


def test_interface_classification_does_not_infer_class_from_summary_when_model_field_is_missing() -> None:
    classification = two_stage.classify_interface_surface(
        {
            "screen_reading": {
                "screen_summary": "Media library with repeated album cards",
                "state_guess": "library home",
            }
        }
    )

    assert classification["category"] == "generic"
    assert classification["source"] == "missing_model_classification"
    assert classification["status"] == "needs_review"
    assert classification["confidence"] == 0.0
    assert classification["class_rule_profile"]["primary_content_strategy"] == "evidence_balanced"


def test_two_stage_screen_understanding_splits_structure_then_numbers_items(tmp_path):
    image_path = tmp_path / "apple_music.png"
    image_path.write_bytes(b"not a real image")
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 140, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 240, "w": 260, "h": 190},
            "review_only": True,
            "metadata": {
                "text_lines": [
                    {"label": "能量充电", "bbox": {"x": 170, "y": 330, "w": 140, "h": 30}},
                    {"label": "ATLUS Sound Team", "bbox": {"x": 170, "y": 370, "w": 160, "h": 20}},
                ]
            },
        },
        {
            "item_id": "misassigned_left_icon",
            "label": "Playlist icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 18, "y": 210, "w": 24, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home", "misassigned_left_icon"]},
            "main_content": {"item_ids": ["card_1"]},
        },
        "nodes": {
            "nav_home": inventory[0],
            "card_1": inventory[1],
            "misassigned_left_icon": inventory[2],
        },
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 900, "height": 650},
            "screen_reading": {
                "interface_classification": {
                    "category": "media_catalog",
                    "confidence": 0.94,
                    "reason": "repeated visual media cards",
                }
            },
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert result["contract_version"] == "learn_two_stage_screen_understanding_v1"
    assert result["interface_classification"]["category"] == "media_catalog"
    assert result["class_rule_profile"]["primary_content_strategy"] == "visual_card_first"
    assert result["pipeline_contract"]["contract_version"] == "learn_mode_deterministic_hierarchy_pipeline_contract_v1"
    assert result["pipeline_contract"]["center_policy"] == "nested_content_groups_may_be_built_inside_root_partitions"
    assert result["flow_compliance"]["stage1_region_split_present"] is True
    assert result["flow_compliance"]["single_screenshot_patch_strategy_used"] is False
    assert (
        result["stage2_numbering"]["layout_review_enhancement"]["contract_version"]
        == "learn_card_layout_review_enhancement_v1"
    )
    assert (
        result["stage2_numbering"]["layout_review_enhancement"]["artifact_is_authorization"]
        is False
    )
    peer_inventory = result["stage2_numbering"]["agent_peer_card_inventory"]
    assert peer_inventory["contract_version"] == "agent_peer_card_inventory_v1"
    assert peer_inventory["peer_item_family"] == "media_card"
    assert peer_inventory["item_count"] >= 1
    assert peer_inventory["artifact_is_authorization"] is False
    assert "bbox" not in str(peer_inventory)


    assert result["stage1_structure"]["region_count"] == 2
    assert result["stage1_region_localization"]["localized_region_count"] == 2
    assert [item["region_id"] for item in result["stage1_structure"]["structure_regions"]] == [
        "structure_region_left_nav",
        "structure_region_main_content",
    ]
    left_region = next(
        item for item in result["stage1_structure"]["structure_regions"] if item["region_id"] == "structure_region_left_nav"
    )
    main_region = next(
        item for item in result["stage1_structure"]["structure_regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert "misassigned_left_icon" in left_region["item_ids"]
    assert "misassigned_left_icon" not in main_region["item_ids"]
    assert main_region["bbox"]["x"] > 96
    localized_left = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )
    assert localized_left["rough_bbox"] == left_region["bbox"]
    assert localized_left["precise_bbox"] == left_region["bbox"]
    localized_main = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert localized_main["rough_bbox"] == main_region["bbox"]
    assert localized_main["precise_bbox"] == main_region["bbox"]
    assert localized_main["coordinate_validation"]["status"] == "authoritative_partition_geometry"
    assert localized_main["bbox_policy"] == "authoritative_deterministic_root_partition"
    assert result["stage2_numbering"]["regions"][1]["input_region_bbox"] == main_region["bbox"]
    assert result["stage2_numbering"]["region_count"] == 2
    assert len(result["source_graph_revision"]) == 64
    assert result["source_graph_revision"] == two_stage.stage2_graph_revision(
        result["stage2_numbering"]
    )
    left_numbered_region = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )
    assert left_numbered_region["region_processing_contract"]["mode"] == "direct_numbering_within_precise_region"
    assert left_numbered_region["bar_numbering"]["applied"] is True
    assert (
        left_numbered_region["bar_numbering"]["spacing_policy"]
        == "spacing_may_split_control_groups_but_must_not_shrink_region_bbox"
    )
    main_numbered_region = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert main_numbered_region["region_processing_contract"]["mode"] == "subdivide_then_number"
    assert main_numbered_region["main_content_subdivision"]["subdivision_required"] is True
    assert main_numbered_region["bar_numbering"]["applied"] is False
    assert main_numbered_region["numbered_items"][0]["number"] == "2.1"
    assert main_numbered_region["numbered_items"][0]["children"][0]["label"] == "能量充电"
    assert result["fusion"]["fused_review_box_count"] >= 4
    assert "model_call_plan" not in result
    assert result["execution_evidence"]["actual_model_calls"] == 0
    assert result["execution_evidence"]["stage1_engine"] == "test_explicit_stage1_override"
    assert result["execution_evidence"]["stage1_geometry_authoritative"] is True


def test_aggregate_portal_policy_reaches_stage1_root_partition() -> None:
    inventory = [
        {
            "item_id": "left_module",
            "label": "Weather",
            "role": "content_module",
            "item_type": "card",
            "bbox": {"x": 10, "y": 20, "w": 80, "h": 180},
            "review_only": True,
        },
        {
            "item_id": "middle_module",
            "label": "News",
            "role": "content_module",
            "item_type": "card",
            "bbox": {"x": 160, "y": 20, "w": 300, "h": 180},
            "review_only": True,
        },
        {
            "item_id": "right_module",
            "label": "Markets",
            "role": "content_module",
            "item_type": "card",
            "bbox": {"x": 540, "y": 20, "w": 430, "h": 180},
            "review_only": True,
        },
    ]
    bundle = {
        "screen_size": {"width": 1000, "height": 600},
        "screen_reading": {
            "interface_classification": {
                "category": "aggregate_portal",
                "confidence": 0.95,
                "reason": "independently framed peer modules",
                "structure_signals": {
                    "mixed_content_modules": True,
                    "feed_items": False,
                    "news_items": True,
                    "media_cards": True,
                },
            }
        },
    }

    result = _build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=inventory,
        layout_graph={"nodes": {item["item_id"]: item for item in inventory}, "zones": {}},
    )

    assert result["interface_classification"]["category"] == "aggregate_portal"
    assert (
        result["stage1_structure"]["diagnostics"]["root_selection"][
            "primary_content_strategy"
        ]
        == "independent_content_modules"
    )
    assert [region["zone_id"] for region in result["stage1_structure"]["structure_regions"]] == [
        "main_content"
    ]


def test_production_two_stage_uses_authoritative_deterministic_root_without_model_plan(tmp_path) -> None:
    image_path = tmp_path / "surface.png"
    image_path.write_bytes(b"not a real image")
    inventory = [
        {
            "item_id": "left_control",
            "label": "Navigation",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 12, "y": 100, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "main_card",
            "label": "Content card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 180, "y": 120, "w": 300, "h": 220},
            "review_only": True,
        },
    ]

    result = _build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 800, "height": 600}},
        screen_inventory=inventory,
        layout_graph={"nodes": {item["item_id"]: item for item in inventory}, "zones": {}},
    )

    structure_by_id = {
        region["region_id"]: region for region in result["stage1_structure"]["structure_regions"]
    }
    assert result["stage1_source"] == "deterministic_root_partition_v1"
    assert result["stage1_region_localization"]["legacy_bar_postprocessing_applied"] is False
    assert result["stage1_region_localization"]["actual_model_calls"] == 0
    for localized in result["stage1_region_localization"]["regions"]:
        authoritative = structure_by_id[localized["region_id"]]["bbox"]
        assert localized["rough_bbox"] == authoritative
        assert localized["precise_bbox"] == authoritative
        assert localized["bbox"] == authoritative
    assert "model_call_plan" not in result
    assert result["execution_evidence"] == {
        "contract_version": "learn_recognition_execution_evidence_v1",
        "stage1_engine": "deterministic_root_partition_v1",
        "stage2_engine": "deterministic_partition_content_recognition_v1",
        "actual_model_calls": 0,
        "stage1_model_calls": 0,
        "stage2_model_calls": 0,
        "model_assisted": False,
        "stage1_geometry_authoritative": True,
        "legacy_bar_postprocessing_applied": False,
        "interpretation": (
            "Execution evidence for this run; no model call or legacy bar-localization postprocessor was used."
        ),
    }


def test_documentation_class_rule_skips_media_card_synthesis(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("documentation policy must not run media-card synthesis")

    monkeypatch.setattr(two_stage, "_synthesize_primary_media_cards", fail_if_called)
    region = {
        "region_no": 1,
        "region_id": "structure_region_primary_area",
        "label": "Primary Area",
        "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
        "item_ids": ["doc_title"],
    }
    items_by_id = {
        "doc_title": {
            "item_id": "doc_title",
            "label": "Documentation",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 40, "y": 40, "w": 220, "h": 32},
            "grounding_eligible": False,
        }
    }

    result = two_stage._stage2_numbering(
        [region],
        items_by_id=items_by_id,
        class_rule_profile={
            "primary_content_strategy": "text_structure_first",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
        },
    )

    numbered_region = result["regions"][0]
    assert numbered_region["class_rule_profile"]["primary_content_strategy"] == "text_structure_first"
    assert numbered_region["visual_small_control_refinement"]["media_card_synthesis"] == {
        "applied": False,
        "reason": "disabled_by_interface_class_rule",
        "candidate_count": 0,
    }


def test_explicit_non_chat_class_rule_blocks_local_chat_semantic_reactivation(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("explicit non-chat policy must block chat-only refinement")

    monkeypatch.setattr(two_stage, "_synthesize_chat_image_messages", fail_if_called)
    monkeypatch.setattr(two_stage, "_normalize_text_only_message_bubble_backgrounds", fail_if_called)
    region = {
        "region_no": 1,
        "region_id": "structure_region_main_content",
        "label": "Media feed",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 620},
        "item_ids": ["thumbnail_chatgpt"],
    }
    items_by_id = {
        "thumbnail_chatgpt": {
            "item_id": "thumbnail_chatgpt",
            "label": "ChatGPT",
            "role": "message_text",
            "item_type": "message_text",
            "bbox": {"x": 120, "y": 160, "w": 240, "h": 48},
            "grounding_eligible": False,
        }
    }

    result = two_stage._stage2_numbering(
        [region],
        items_by_id=items_by_id,
        class_rule_profile={
            "primary_content_strategy": "visual_feed_card_first",
            "allow_media_card_synthesis": True,
            "allow_chat_semantics": False,
        },
    )

    refinement = result["regions"][0]["visual_small_control_refinement"]
    assert refinement["chat_image_message_synthesis"]["reason"] == "disabled_by_interface_class_rule"
    assert refinement["message_bubble_hit_area"]["reason"] == "disabled_by_interface_class_rule"


def test_documentation_class_rule_keeps_text_lists_without_tile_card_parent_inference() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items: list[dict] = []
    for index, y in enumerate((140, 178, 216), start=1):
        items.extend(
            [
                {
                    "number": f"1.{index * 2 - 1}",
                    "item_id": f"metadata_{index}",
                    "label": f"2026-07-{index:02d}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                },
                {
                    "number": f"1.{index * 2}",
                    "item_id": f"title_{index}",
                    "label": f"Entry title {index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 200, "y": y, "w": 150, "h": 20},
                },
            ]
        )

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "text_structure_first"},
    )

    assert any(group.get("role") == "list_group" for group in groups)
    assert all(group.get("role") not in {"tile_card_group", "tile_card_parent"} for group in groups)
    assert all(
        group.get("source")
        not in {
            "stage2_primary_content_card_row_grouping",
            "stage2_primary_tile_card_parent_grouping",
            "stage2_primary_text_tile_card_parent_grouping",
            "stage2_repeated_text_column_parent_grouping",
        }
        for group in groups
    )


def test_documentation_class_rule_keeps_explicit_content_card_parent() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "docs_card",
            "label": "Documentation",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 80, "y": 80, "w": 240, "h": 140},
        },
        {
            "number": "1.2",
            "item_id": "docs_title",
            "label": "Docs",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 104, "y": 104, "w": 80, "h": 24},
        },
        {
            "number": "1.3",
            "item_id": "docs_description",
            "label": "Read the Python documentation",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 104, "y": 140, "w": 180, "h": 42},
        },
    ]

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "text_structure_first"},
    )

    explicit_card = next(group for group in groups if group.get("role") == "tile_card_parent")
    assert explicit_card["source"] == "stage2_primary_tile_card_parent_grouping"
    assert explicit_card["bbox"] == items[0]["bbox"]
    assert set(explicit_card["member_item_ids"]) == {"docs_card", "docs_title", "docs_description"}


def test_dense_code_workspace_rejects_semantic_news_card_interpretation() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 1000, "h": 700},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "changed_files",
            "label": "7 changed files",
            "role": "list",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 120, "w": 230, "h": 420},
        },
        {
            "number": "1.2",
            "item_id": "model_card_code_hunk",
            "label": "@@ -31, 6 +31, 7 @@ def build_regions(",
            "role": "tile_card",
            "original_role": "news_card",
            "item_type": "review_only",
            "bbox": {"x": 330, "y": 130, "w": 410, "h": 110},
        },
        {
            "number": "1.3",
            "item_id": "model_card_code_line",
            "label": "if item.get('role') == 'text':",
            "role": "tile_card",
            "original_role": "recommendation_item",
            "item_type": "review_only",
            "bbox": {"x": 750, "y": 130, "w": 210, "h": 110},
        },
        {
            "number": "1.4",
            "item_id": "code_line_1",
            "label": "for value in candidates:",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 350, "y": 155, "w": 220, "h": 20},
        },
        {
            "number": "1.5",
            "item_id": "code_line_2",
            "label": "if item.get('role') == 'text':",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 350, "y": 182, "w": 270, "h": 20},
        },
    ]
    for index in range(6, 25):
        items.append(
            {
                "number": f"1.{index}",
                "item_id": f"document_line_{index}",
                "label": f"return normalized_item_{index}",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 350, "y": 210 + (index - 6) * 20, "w": 250, "h": 18},
            }
        )

    normalized_items, normalization = two_stage._normalize_dense_document_semantic_card_roles(items)
    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=normalized_items,
        class_rule_profile={"primary_content_strategy": "evidence_balanced"},
    )

    assert normalization["applied"] is True
    assert normalization["normalized_count"] == 2
    assert {
        item["role"]
        for item in normalized_items
        if item["item_id"].startswith("model_card_")
    } == {"document_section"}
    assert all(
        group.get("role") not in {"tile_card_parent", "tile_card_group"}
        for group in groups
    )


def test_dense_code_workspace_keeps_explicit_visual_content_card() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 1000, "h": 700},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "changed_files",
            "label": "7 changed files",
            "role": "list",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 120, "w": 230, "h": 420},
        },
        {
            "number": "1.2",
            "item_id": "release_card",
            "label": "Release summary",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 690, "y": 430, "w": 250, "h": 130},
        },
        {
            "number": "1.3",
            "item_id": "release_title",
            "label": "Release summary",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 710, "y": 450, "w": 150, "h": 22},
        },
    ]
    for index in range(4, 24):
        items.append(
            {
                "number": f"1.{index}",
                "item_id": f"code_line_{index}",
                "label": f"if value_{index}.get('enabled'):",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 300, "y": 120 + (index - 4) * 20, "w": 270, "h": 18},
            }
        )

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "evidence_balanced"},
    )

    card_groups = [group for group in groups if group.get("role") == "tile_card_parent"]
    assert len(card_groups) == 1
    assert card_groups[0]["member_item_ids"] == ["release_card", "release_title"]


def test_documentation_card_parent_absorbs_attached_title_above_partial_card_bbox() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "download_title",
            "label": "Download",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 90, "w": 110, "h": 26},
        },
        {
            "number": "1.2",
            "item_id": "download_partial_card",
            "label": "Python source code and installers",
            "role": "tile_card",
            "item_type": "card",
            "bbox": {"x": 98, "y": 108, "w": 250, "h": 142},
        },
        {
            "number": "1.3",
            "item_id": "download_description",
            "label": "Python source code and installers",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 118, "y": 130, "w": 205, "h": 42},
        },
    ]

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "text_structure_first"},
    )

    card = next(group for group in groups if group.get("role") == "tile_card_parent")
    assert set(card["member_item_ids"]) == {
        "download_title",
        "download_partial_card",
        "download_description",
    }
    assert card["bbox"] == {"x": 98, "y": 90, "w": 250, "h": 160}


def test_tile_card_fragment_inside_parent_is_not_rendered_as_peer_overlay() -> None:
    item = {
        "number": "1.2",
        "item_id": "download_partial_card",
        "label": "Python source code and installers",
        "role": "tile_card",
        "item_type": "card",
        "bbox": {"x": 98, "y": 108, "w": 250, "h": 142},
    }

    hierarchy = two_stage._item_display_hierarchy(
        item,
        [{"group_id": "download_parent", "role": "tile_card_parent"}],
    )

    assert hierarchy["display_layer"] == "child_evidence"
    assert hierarchy["render_in_main_overlay"] is False


def test_generic_card_fragment_inside_tile_group_is_not_rendered_as_peer_overlay() -> None:
    item = {
        "number": "1.2",
        "item_id": "settings_card_fragment",
        "label": "System settings",
        "role": "card",
        "item_type": "card",
        "bbox": {"x": 60, "y": 280, "w": 420, "h": 180},
    }

    hierarchy = two_stage._item_display_hierarchy(
        item,
        [{"group_id": "settings_row", "role": "tile_card_group"}],
    )

    assert hierarchy["display_layer"] == "child_evidence"
    assert hierarchy["render_in_main_overlay"] is False


def test_documentation_class_rule_prefers_list_group_over_overlapping_explicit_card() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "false_news_card",
            "label": "Latest news",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 70, "y": 120, "w": 360, "h": 150},
        }
    ]
    for index, y in enumerate((140, 178, 216), start=1):
        items.extend(
            [
                {
                    "number": f"1.{index * 2}",
                    "item_id": f"metadata_{index}",
                    "label": f"2026-07-{index:02d}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                },
                {
                    "number": f"1.{index * 2 + 1}",
                    "item_id": f"title_{index}",
                    "label": f"Entry title {index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 200, "y": y, "w": 150, "h": 20},
                },
            ]
        )

    groups = two_stage._primary_content_subregion_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "text_structure_first"},
    )

    assert any(group.get("role") == "list_group" for group in groups)
    assert all(group.get("role") != "tile_card_parent" for group in groups)


def test_two_stage_global_no_partition_numbers_items_on_full_screen_canvas(tmp_path):
    image_path = tmp_path / "apple_music.png"
    image_path.write_bytes(b"not a real image")
    inventory = [
        {
            "item_id": "top_play",
            "label": "Play",
            "role": "control",
            "item_type": "review_only",
            "bbox": {"x": 160, "y": 24, "w": 28, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "left_home",
            "label": "Home",
            "role": "nav_item",
            "item_type": "review_only",
            "bbox": {"x": 18, "y": 110, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 180, "y": 220, "w": 180, "h": 240},
            "review_only": True,
        },
    ]
    layout_graph = {
        "zones": {
            "top_bar": {"item_ids": ["top_play"]},
            "left_nav": {"item_ids": ["left_home"]},
            "main_content": {"item_ids": ["card_1"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        stage2_region_strategy="global_no_partition",
    )

    assert result["stage2_input_policy"]["stage2_region_strategy"] == "global_no_partition"
    assert result["stage2_input_policy"]["input_region_count"] == 1
    region = result["stage2_numbering"]["regions"][0]
    assert region["region_id"] == "global_no_partition"
    assert region["input_region_bbox"] == {"x": 0, "y": 0, "w": 900, "h": 650}
    assert {item["item_id"] for item in region["numbered_items"]} >= {"top_play", "left_home", "card_1"}


def test_fusion_marks_group_child_text_as_child_evidence_not_main_overlay() -> None:
    structure_regions = [
        {
            "region_no": 1,
            "label": "Primary",
            "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_primary_area",
            "subregion_groups": [
                {
                    "group_id": "hero_panel_1",
                    "label": "hero panel",
                    "role": "hero_panel",
                    "bbox": {"x": 20, "y": 20, "w": 460, "h": 160},
                    "member_item_ids": ["hero_title", "hero_cta"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                }
            ],
            "numbered_items": [
                {
                    "item_id": "hero_title",
                    "number": "1.1",
                    "label": "Quick and Easy",
                    "role": "text",
                    "bbox": {"x": 40, "y": 40, "w": 200, "h": 28},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
                {
                    "item_id": "hero_card",
                    "number": "1.2",
                    "label": "Download card",
                    "role": "news_card",
                    "bbox": {"x": 40, "y": 220, "w": 200, "h": 140},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
                {
                    "item_id": "hero_extra",
                    "number": "1.3",
                    "label": "Extra hero copy",
                    "role": "text",
                    "bbox": {"x": 70, "y": 90, "w": 220, "h": 26},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
            ],
        }
    ]

    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    boxes = {item["number"]: item for item in fusion["fused_review_boxes"] if item.get("box_type") == "numbered_item"}
    assert boxes["1.1"]["parent_group_ids"] == ["hero_panel_1"]
    assert boxes["1.1"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.1"]["render_in_main_overlay"] is False
    assert boxes["1.2"]["display_hierarchy"]["display_layer"] == "primary_region"
    assert boxes["1.2"]["render_in_main_overlay"] is True
    assert boxes["1.3"]["parent_group_ids"] == ["hero_panel_1"]
    assert boxes["1.3"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.3"]["render_in_main_overlay"] is False


def test_fusion_demotes_model_text_cards_inside_parent_groups_but_keeps_visual_cards() -> None:
    structure_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_primary_area",
            "subregion_groups": [
                {
                    "group_id": "latest_news_section",
                    "label": "Latest News",
                    "role": "section_parent",
                    "bbox": {"x": 40, "y": 40, "w": 360, "h": 220},
                    "member_item_ids": ["model_news_card"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
                {
                    "group_id": "media_row",
                    "label": "Media row",
                    "role": "media_card_group",
                    "bbox": {"x": 460, "y": 40, "w": 360, "h": 260},
                    "member_item_ids": ["visual_media_card"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
            ],
            "numbered_items": [
                {
                    "item_id": "model_news_card",
                    "number": "1.1",
                    "label": "Thinking about running for the board?",
                    "role": "news_card",
                    "source": "structure_region_item",
                    "bbox": {"x": 56, "y": 96, "w": 300, "h": 96},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
                {
                    "item_id": "visual_media_card",
                    "number": "1.2",
                    "label": "Album card",
                    "role": "media_card",
                    "source": "visual_card_segmenter",
                    "bbox": {"x": 500, "y": 88, "w": 180, "h": 220},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
            ],
        }
    ]

    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    boxes = {item["number"]: item for item in fusion["fused_review_boxes"] if item.get("box_type") == "numbered_item"}
    assert boxes["1.1"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.1"]["display_hierarchy"]["demotion_reason"] == "model_card_like_text_evidence_inside_parent_group"
    assert boxes["1.1"]["render_in_main_overlay"] is False
    assert boxes["1.2"]["display_hierarchy"]["display_layer"] == "primary_region"
    assert boxes["1.2"]["render_in_main_overlay"] is True


def test_fusion_demotes_structural_container_groups_with_child_groups_from_main_overlay() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "hero_panel_1",
                        "label": "Hero panel",
                        "role": "hero_panel",
                        "bbox": {"x": 40, "y": 40, "w": 520, "h": 180},
                        "child_group_ids": ["hero_text_panel_1", "hero_code_panel_1"],
                        "child_group_roles": ["hero_text_panel", "hero_code_panel"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
                    },
                    {
                        "group_id": "hero_text_panel_1",
                        "label": "Hero text",
                        "role": "hero_text_panel",
                        "bbox": {"x": 320, "y": 60, "w": 220, "h": 130},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
                    },
                ],
                "numbered_items": [],
            }
        ],
    )

    groups = {item["number"]: item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group"}
    assert groups["hero_panel_1"]["group_display_hierarchy"]["display_layer"] == "structural_container"
    assert groups["hero_panel_1"]["render_in_main_overlay"] is False
    assert groups["hero_text_panel_1"]["render_in_main_overlay"] is True


def test_fusion_keeps_ungrouped_review_region_detail_only() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "ungrouped_review_region_1",
                        "label": "ungrouped review region",
                        "role": "ungrouped_review_region",
                        "bbox": {"x": 80, "y": 80, "w": 480, "h": 220},
                        "member_item_ids": ["review_text"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "review_text",
                        "number": "1.1",
                        "label": "fallback text evidence",
                        "role": "text",
                        "bbox": {"x": 110, "y": 110, "w": 240, "h": 24},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
                    }
                ],
            }
        ],
    )

    group = next(item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group")
    child = next(item for item in result["fused_review_boxes"] if item.get("box_type") == "numbered_item")
    assert group["group_display_hierarchy"]["display_layer"] == "detail_only_review_region"
    assert group["render_in_main_overlay"] is False
    assert child["display_hierarchy"]["display_layer"] == "child_evidence"
    assert child["display_hierarchy"]["demotion_reason"] == "ungrouped_review_region_detail_only"
    assert child["render_in_main_overlay"] is False


def test_fusion_demotes_media_group_without_visual_card_evidence() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "text_card_row",
                        "label": "visual media card row",
                        "role": "media_card_group",
                        "bbox": {"x": 80, "y": 420, "w": 700, "h": 170},
                        "member_item_ids": ["news_card_a", "news_card_b", "more_link"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "group_id": "visual_card_row",
                        "label": "visual media card row",
                        "role": "media_card_group",
                        "bbox": {"x": 80, "y": 80, "w": 700, "h": 260},
                        "member_item_ids": ["album_card_a", "album_card_b"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                ],
                "numbered_items": [
                    {
                        "item_id": "news_card_a",
                        "number": "1.1",
                        "label": "Python 3.15 beta is here",
                        "role": "news_card",
                        "source": "structure_region_item",
                        "bbox": {"x": 90, "y": 430, "w": 300, "h": 120},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "news_card_b",
                        "number": "1.2",
                        "label": "Use Python for...",
                        "role": "news_card",
                        "source": "structure_region_item",
                        "bbox": {"x": 470, "y": 430, "w": 260, "h": 120},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "more_link",
                        "number": "1.3",
                        "label": "More",
                        "role": "button",
                        "source": "structure_region_item",
                        "bbox": {"x": 740, "y": 430, "w": 60, "h": 24},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "album_card_a",
                        "number": "1.4",
                        "label": "Album A",
                        "role": "media_card",
                        "source": "visual_card_segmenter",
                        "bbox": {"x": 100, "y": 100, "w": 180, "h": 220},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "album_card_b",
                        "number": "1.5",
                        "label": "Album B",
                        "role": "media_card",
                        "source": "visual_card_segmenter",
                        "bbox": {"x": 320, "y": 100, "w": 180, "h": 220},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                ],
            }
        ],
    )

    groups = {item["number"]: item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group"}
    assert groups["text_card_row"]["group_display_hierarchy"]["display_layer"] == "detail_only_text_card_group"
    assert groups["text_card_row"]["render_in_main_overlay"] is False
    assert groups["visual_card_row"]["render_in_main_overlay"] is True


def test_stage1_localization_suppresses_tiny_contained_duplicate_main_region(tmp_path):
    from PIL import Image

    image_path = tmp_path / "generic_app.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "primary_area",
            "label": "Primary work area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 100, "y": 100, "w": 800, "h": 500},
            "review_only": True,
        },
        {
            "item_id": "tiny_duplicate",
            "label": "Tiny duplicate content hint",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 140, "y": 140, "w": 50, "h": 30},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["primary_area"]},
            "main_content": {"item_ids": ["tiny_duplicate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    localization = report["stage1_region_localization"]
    assert localization["suppressed_duplicate_region_count"] == 1
    assert localization["localized_region_count"] == 1
    assert localization["suppressed_duplicate_regions"][0]["region_id"] == "structure_region_main_content"
    assert localization["suppressed_duplicate_regions"][0]["contained_by_region_id"] == "structure_region_primary_area"
    kept_region_ids = [item["region_id"] for item in localization["regions"]]
    assert kept_region_ids == ["structure_region_primary_area"]
    assert report["region_selection_audit"]["passed"] is True
    assert "main_region_too_small" not in report["region_selection_audit"]["failure_categories"]












def test_stage1_recovers_adjacent_header_and_main_from_shallow_fullscreen_backfill(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shallow_fullscreen_backfill.png"
    Image.new("RGB", (1000, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_control_row",
            "label": "Top controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 180, "y": 60, "w": 640, "h": 100},
            "review_only": True,
        },
        {
            "item_id": "top_navigation_row",
            "label": "Navigation row",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 220, "y": 180, "w": 560, "h": 60},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    assert [(region["zone_id"], region["bbox"]) for region in regions] == [
        ("page_header", {"x": 0, "y": 0, "w": 1000, "h": 240}),
        ("main_content", {"x": 0, "y": 240, "w": 1000, "h": 560}),
    ]
    assert result["region_selection_audit"]["passed"] is True


def test_two_stage_uses_ocr_content_recovery_when_existing_items_cover_only_top(tmp_path, monkeypatch):
    from PIL import Image

    from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

    image_path = tmp_path / "undercovered_main.png"
    Image.new("RGB", (1000, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_navigation",
            "label": "Navigation",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 100, "y": 40, "w": 800, "h": 120},
            "review_only": True,
        }
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": ["top_navigation"]}},
        "nodes": {"top_navigation": inventory[0]},
    }
    ocr_result = OCRResult(
        image_path=str(image_path),
        matches=[
            OCRTextMatch("Body section", 0.95, OCRBoundingBox(120, 420, 180, 28)),
            OCRTextMatch("Lower content", 0.93, OCRBoundingBox(120, 690, 200, 28)),
        ],
        metadata={"engine": "test_ocr"},
    )
    monkeypatch.setattr("app.learn.recognition.two_stage.ocr_service.scan_image", lambda _path: ocr_result)

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        enable_ocr_content_recovery=True,
    )

    recovery = result["content_recovery"]
    assert recovery["status"] == "applied"
    assert recovery["ocr_match_count"] == 2
    assert recovery["added_item_count"] == 2
    labels = {
        item["label"]
        for region in result["stage2_numbering"]["regions"]
        for item in region.get("numbered_items", [])
    }
    assert {"Body section", "Lower content"} <= labels


def test_two_stage_uses_recovered_ocr_items_for_stage1_root_partition(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

    image_path = tmp_path / "ocr_recovered_header_and_body.png"
    image = Image.new("RGB", (1000, 800), "white")
    ImageDraw.Draw(image).line((0, 120, 999, 120), fill="black", width=2)
    image.save(image_path)
    ocr_result = OCRResult(
        image_path=str(image_path),
        matches=[
            OCRTextMatch("Docs", 0.98, OCRBoundingBox(40, 48, 90, 28)),
            OCRTextMatch("Guides", 0.97, OCRBoundingBox(260, 48, 100, 28)),
            OCRTextMatch("Reference", 0.97, OCRBoundingBox(520, 48, 130, 28)),
            OCRTextMatch("Main heading", 0.98, OCRBoundingBox(120, 210, 190, 36)),
            OCRTextMatch("Main body text", 0.96, OCRBoundingBox(120, 470, 240, 30)),
            OCRTextMatch("Lower body text", 0.96, OCRBoundingBox(120, 690, 240, 30)),
        ],
        metadata={"engine": "test_ocr"},
    )
    monkeypatch.setattr("app.learn.recognition.two_stage.ocr_service.scan_image", lambda _path: ocr_result)

    result = _build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 800}},
        screen_inventory=[],
        layout_graph={"contract_version": "learn_layout_graph_v1", "zones": {}, "nodes": {}},
        enable_ocr_content_recovery=True,
        require_stage1_gate=True,
    )

    assert result["content_recovery"]["status"] == "applied"
    assert [region["role"] for region in result["stage1_region_localization"]["regions"]] == [
        "top_bar",
        "main_content",
    ]


def test_stage1_keeps_incomplete_semantic_card_columns_in_main_grid(tmp_path):
    from PIL import Image

    image_path = tmp_path / "incomplete_semantic_card_grid.png"
    Image.new("RGB", (1000, 760), "white").save(image_path)
    inventory = []
    for row, y in enumerate((160, 430), start=1):
        inventory.extend(
            [
                {
                    "item_id": f"row_{row}_left_card",
                    "label": f"Row {row} left card",
                    "role": "media_card",
                    "item_type": "card",
                    "bbox": {"x": 80, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
                {
                    "item_id": f"row_{row}_middle_item",
                    "label": f"Row {row} middle item",
                    "role": "listitem",
                    "item_type": "layout",
                    "bbox": {"x": 340, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
                {
                    "item_id": f"row_{row}_right_card",
                    "label": f"Row {row} right card",
                    "role": "recommendation_item",
                    "item_type": "card",
                    "bbox": {"x": 700, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
            ]
        )
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 760}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    region_ids = {region["region_id"] for region in result["stage1_region_localization"]["regions"]}
    assert "structure_region_right_sidebar" not in region_ids








def test_conversation_class_does_not_split_bottom_list_continuation_without_section_boundary() -> None:
    corrected_zone_items = {
        "main_content": ["last_chat_row", "last_chat_preview"],
        "primary_area": ["privacy_footer"],
    }
    items_by_id = {
        "last_chat_row": {
            "item_id": "last_chat_row",
            "label": "LeetCode",
            "role": "conversation_row",
            "item_type": "listitem",
            "bbox": {"x": 90, "y": 890, "w": 300, "h": 70},
        },
        "last_chat_preview": {
            "item_id": "last_chat_preview",
            "label": "This business uses a secure service",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 160, "y": 935, "w": 220, "h": 20},
        },
        "privacy_footer": {
            "item_id": "privacy_footer",
            "label": "Private messages are end-to-end encrypted",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 110, "y": 990, "w": 260, "h": 18},
        },
    }

    correction = two_stage._split_conversation_bottom_panel(
        corrected_zone_items,
        items_by_id=items_by_id,
        screen_size={"width": 952, "height": 1029},
        class_rule_profile={"primary_content_strategy": "conversation_rows"},
    )

    assert correction is None
    assert corrected_zone_items == {
        "main_content": ["last_chat_row", "last_chat_preview"],
        "primary_area": ["privacy_footer"],
    }


def test_stage1_primary_area_expands_full_width_without_sidebar(tmp_path):
    from PIL import Image

    image_path = tmp_path / "centered_web_page.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_back",
            "label": "Back",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 18, "y": 20, "w": 32, "h": 28},
            "review_only": True,
            "metadata": {"surface_zone": "browser_chrome"},
        },
        {
            "item_id": "page_header",
            "label": "Header",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 100},
            "review_only": True,
        },
        {
            "item_id": "centered_hero",
            "label": "Centered hero",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 330, "y": 160, "w": 540, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "centered_card",
            "label": "Centered card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 360, "y": 460, "w": 260, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_back"]},
            "top_bar": {"item_ids": ["page_header"]},
            "primary_area": {"item_ids": ["centered_hero", "centered_card"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )
    assert primary["precise_bbox"]["x"] == 0
    assert primary["precise_bbox"]["w"] == 1200
    assert primary["coordinate_validation"]["calibration_strategy"] == "main_content_full_width_when_no_sidebars"


def test_stage1_main_boundary_ignores_readable_duplicate_of_explicit_top_candidate(tmp_path):
    from PIL import Image

    image_path = tmp_path / "top_summary_with_duplicate_readable_evidence.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_shell",
            "label": "Top summary",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 150},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "summary_readable",
            "label": "Account summary",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 220, "y": 108, "w": 150, "h": 24},
            "review_only": True,
            "metadata": {"source": "screen_reading.texts", "surface_zone": "primary_area"},
        },
        {
            "item_id": "summary_top_candidate",
            "label": "Account summary",
            "role": "nav_text_action",
            "item_type": "review_only",
            "bbox": {"x": 220, "y": 108, "w": 150, "h": 24},
            "review_only": True,
            "metadata": {"source": "screen_map.candidates", "surface_zone": "top_bar"},
        },
        {
            "item_id": "summary_peer_readable",
            "label": "Secondary summary",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 220, "y": 126, "w": 150, "h": 22},
            "review_only": True,
            "metadata": {"source": "screen_reading.texts", "surface_zone": "primary_area"},
        },
        *[
            {
                "item_id": f"top_peer_{index}",
                "label": f"Top peer {index}",
                "role": "nav_text_action",
                "item_type": "review_only",
                "bbox": {"x": x, "y": 112, "w": 70, "h": 22},
                "review_only": True,
                "metadata": {"source": "screen_map.candidates", "surface_zone": "top_bar"},
            }
            for index, x in enumerate((500, 700, 900), start=1)
        ],
        {
            "item_id": "search_field",
            "label": "Search",
            "role": "input",
            "item_type": "actionable",
            "bbox": {"x": 450, "y": 170, "w": 300, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "main_grid",
            "label": "Settings grid",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 150, "w": 1200, "h": 650},
            "review_only": True,
        },
        {
            "item_id": "first_tile",
            "label": "Category",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 80, "y": 230, "w": 240, "h": 90},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {
                "item_ids": ["top_shell", "summary_top_candidate", "top_peer_1", "top_peer_2", "top_peer_3"]
            },
            "primary_area": {
                "item_ids": [
                    "summary_readable",
                    "summary_peer_readable",
                    "search_field",
                    "main_grid",
                    "first_tile",
                ]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    top = next(item for item in regions if item["region_id"] == "structure_region_top_bar")
    primary = next(item for item in regions if item["region_id"] == "structure_region_primary_area")
    assert primary["bbox"]["y"] >= 140
    assert top["bbox"]["y"] + top["bbox"]["h"] == primary["bbox"]["y"]


def test_stage1_primary_area_with_left_nav_preserves_visible_media_grid_right_edge(tmp_path):
    from PIL import Image

    image_path = tmp_path / "media_grid_with_left_nav.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_toolbar",
            "label": "Player controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 96, "y": 0, "w": 1104, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "media_grid_shell",
            "label": "Recently played media grid",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 96, "y": 110, "w": 1104, "h": 620},
            "metadata": {"source": "screen_map.sections"},
            "review_only": True,
        },
        {
            "item_id": "visible_card_1",
            "label": "Energy album",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 128, "y": 170, "w": 220, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "visible_card_2_text",
            "label": "Second card text only",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 520, "y": 360, "w": 210, "h": 30},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "top_bar": {"item_ids": ["top_toolbar"]},
            "primary_area": {"item_ids": ["media_grid_shell", "visible_card_1", "visible_card_2_text"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )

    assert primary["precise_bbox"]["x"] >= 90
    assert primary["precise_bbox"]["x"] + primary["precise_bbox"]["w"] == 1200
    assert primary["coordinate_validation"]["right_edge_preservation"]["status"] == (
        "main_content_right_edge_preserved_from_visual_region_hint"
    )


def test_stage1_primary_area_right_edge_preservation_reports_sidebar_clamp(tmp_path):
    from PIL import Image

    image_path = tmp_path / "media_grid_with_right_sidebar.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "media_grid_shell",
            "label": "Recently played media grid",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 96, "y": 110, "w": 1104, "h": 620},
            "metadata": {"source": "screen_map.sections"},
            "review_only": True,
        },
        {
            "item_id": "visible_card",
            "label": "Energy album",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 128, "y": 170, "w": 220, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Detail panel",
            "role": "right_sidebar",
            "item_type": "section",
            "bbox": {"x": 900, "y": 110, "w": 300, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "primary_area": {"item_ids": ["media_grid_shell", "visible_card"]},
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )

    assert primary["precise_bbox"]["x"] + primary["precise_bbox"]["w"] == 900
    preservation = primary["coordinate_validation"]["right_edge_preservation"]
    assert preservation["status"] == "main_content_right_edge_preserved_then_clamped_to_sibling_region"
    assert preservation["preserved_right"] == 1200
    assert preservation["final_right"] == 900


def test_stage1_topbar_preserves_full_width_and_sidebars_start_below_it(tmp_path):
    from PIL import Image

    image_path = tmp_path / "app_with_left_nav_and_topbar.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_toolbar",
            "label": "Toolbar",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 100, "y": 0, "w": 880, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "primary_grid",
            "label": "Primary content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 120, "w": 820, "h": 520},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "top_bar": {"item_ids": ["top_toolbar"]},
            "primary_area": {"item_ids": ["primary_grid"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    left_nav = next(region for region in regions if region["region_id"] == "structure_region_left_nav")
    top_bar = next(region for region in regions if region["region_id"] == "structure_region_top_bar")
    assert top_bar["bbox"]["x"] == 0
    assert top_bar["bbox"]["x"] + top_bar["bbox"]["w"] == 1000
    assert left_nav["bbox"]["y"] == top_bar["bbox"]["y"] + top_bar["bbox"]["h"]
    assert top_bar["coordinate_validation"]["sibling_lane"]["reason"] == (
        "horizontal_bar_full_bbox_preserved_non_sidebar_lane_recorded"
    )
    assert left_nav["coordinate_validation"]["sibling_partition"]["reason"] == (
        "sidebar_must_use_non_horizontal_bar_lane"
    )
    assert report["region_selection_audit"]["passed"] is True


def test_stage2_does_not_number_structure_section_hints_as_primary_cards(tmp_path):
    from PIL import Image

    image_path = tmp_path / "section_hint.png"
    Image.new("RGB", (900, 650), "white").save(image_path)
    inventory = [
        {
            "item_id": "primary_section_hint",
            "label": "Primary area",
            "role": "content",
            "item_type": "layout",
            "bbox": {"x": 90, "y": 90, "w": 760, "h": 520},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "primary_area"},
        },
        {
            "item_id": "card_1",
            "label": "Album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 180, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "card_2",
            "label": "Second album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 370, "y": 180, "w": 220, "h": 260},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    labels = [item["label"] for item in primary["numbered_items"]]
    assert "Primary area" not in labels
    assert "Album card" in labels
    assert "Second album card" in labels


def test_stage2_filters_items_to_current_region_bbox_after_sidebar_split(tmp_path):
    from PIL import Image

    image_path = tmp_path / "split_regions.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_text",
            "label": "Central chat message",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 300, "y": 300, "w": 220, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "right_notice",
            "label": "Right notice",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 120, "w": 220, "h": 230},
            "review_only": True,
        },
        {
            "item_id": "right_member",
            "label": "Right member",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 780, "y": 410, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_members_panel",
            "label": "Right members panel",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 370, "w": 220, "h": 310},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["chat_text"]},
            "right_sidebar": {"item_ids": ["right_notice", "right_member", "right_members_panel"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "chat_text")
    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    primary_labels = {item["label"] for item in primary["numbered_items"]}
    right_labels = {item["label"] for item in right["numbered_items"]}
    assert "Central chat message" in primary_labels
    assert "Right member" not in primary_labels
    assert "Right member" in right_labels


def test_two_stage_reconstructs_notice_parent_in_direct_sidebar(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "notice_sidebar.png"
    image = Image.new("RGB", (1000, 720), "white")
    draw = ImageDraw.Draw(image)
    for y in (124, 160, 194):
        draw.rectangle((774, y, 925, y + 10), fill="black")
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat",
            "label": "Central conversation",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 90, "w": 610, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 770, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_a",
            "label": "Maintenance tonight",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_b",
            "label": "Pinned note",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 188, "w": 120, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["main_chat"]},
            "right_sidebar": {"item_ids": ["notice_title", "notice_body_a", "notice_body_b"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    notice_groups = [group for group in right["subregion_groups"] if group["role"] == "notice_region"]
    assert notice_groups
    notice = notice_groups[0]
    assert notice["parent_child_policy"] == "notice_heading_binds_to_nearby_body_lines"
    assert set(notice["member_item_ids"]) == {"notice_title", "notice_body_a", "notice_body_b"}
    assert notice["bbox"]["x"] <= 770
    assert notice["bbox"]["h"] >= 90
    notice_items = [
        item for item in right["numbered_items"] if item["item_id"] in {"notice_title", "notice_body_a", "notice_body_b"}
    ]
    assert notice_items
    assert {item["role"] for item in notice_items} == {"notice_item"}
    assert all(item["execute_binding_enabled"] is False for item in notice_items)
    fused_notices = [
        item for item in result["fusion"]["fused_review_boxes"] if item.get("role") == "notice_region"
    ]
    assert fused_notices


def test_two_stage_downgrades_nav_item_crossing_notice_member_boundary(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "mixed_notice_member_nav_item.png"
    image = Image.new("RGB", (1000, 720), "white")
    draw = ImageDraw.Draw(image)
    for y in (124, 160, 194):
        draw.rectangle((774, y, 925, y + 10), fill="black")
    draw.rectangle((774, 224, 925, 236), fill="black")
    draw.rectangle((774, 312, 925, 326), fill="black")
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat",
            "label": "Central conversation",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 90, "w": 610, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 770, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_a",
            "label": "Maintenance tonight",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_b",
            "label": "Pinned note",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 188, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "mixed_notice_member",
            "label": "Pinned note / Group members 1263",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 768, "y": 170, "w": 190, "h": 118},
            "review_only": True,
        },
        {
            "item_id": "member_row",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 770, "y": 306, "w": 170, "h": 42},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["main_chat"]},
            "right_sidebar": {
                "item_ids": [
                    "notice_title",
                    "notice_body_a",
                    "notice_body_b",
                    "mixed_notice_member",
                    "member_row",
                ]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    mixed = next(item for item in right["numbered_items"] if item["item_id"] == "mixed_notice_member")
    assert mixed["role"] == "boundary_review_region"
    assert mixed["original_role"] == "nav_item"
    assert mixed["action_candidate"] is False
    assert mixed["execute_binding_enabled"] is False
    assert mixed["bbox_policy"] == "cross_parent_boundary_nav_item_needs_review"
    assert mixed["boundary_violation"]["category"] == "notice_member_boundary_leak"
    member = next(item for item in right["numbered_items"] if item["item_id"] == "member_row")
    assert member["role"] == "nav_item"


def test_two_stage_reconstructs_message_item_parent_in_primary_content(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_parent.png"
    Image.new("RGB", (900, 640), "white").save(image_path)
    inventory = [
        {
            "item_id": "sender_avatar",
            "label": "Sender avatar",
            "role": "avatar",
            "item_type": "image",
            "bbox": {"x": 130, "y": 220, "w": 44, "h": 44},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Alex",
            "role": "sender_label",
            "item_type": "text",
            "bbox": {"x": 190, "y": 214, "w": 60, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "message_text",
            "label": "Can you check the draft?",
            "role": "message_text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 244, "w": 230, "h": 30},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared screenshot",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 190, "y": 286, "w": 180, "h": 110},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 640}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = message_groups[0]
    assert message["parent_child_policy"] == "message_core_absorbs_nearby_context_fragments"
    assert set(message["member_item_ids"]) == {"sender_avatar", "sender_name", "message_text", "image_message"}
    assert set(message["child_item_ids"]) == {"message_text", "image_message"}
    assert set(message["context_item_ids"]) == {"sender_avatar", "sender_name"}
    assert set(message["core_item_ids"]) == {"message_text", "image_message"}
    assert message["message_child_breakdown"]["core_item_count"] == 2
    assert message["message_child_breakdown"]["context_item_count"] == 2
    assert "image_message" in message["child_group_roles"]
    assert message["bbox"]["x"] <= 130
    assert message["bbox"]["h"] >= 170
    fused_messages = [
        item for item in result["fusion"]["fused_review_boxes"] if item.get("role") == "message_item"
    ]
    assert fused_messages


def test_two_stage_reconstructs_chat_image_and_text_bubble_parents(tmp_path):
    from PIL import Image

    image_path = tmp_path / "chat_fragments.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 130, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "sticker_image",
            "label": "Shared sticker image",
            "role": "image",
            "item_type": "image",
            "bbox": {"x": 360, "y": 180, "w": 150, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "message_time",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 320, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This is a longer message bubble that spans a visible chat row",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 370, "w": 310, "h": 64},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    roles_by_id = {item["item_id"]: item["role"] for item in primary["numbered_items"]}
    assert roles_by_id["sticker_image"] == "image_message"
    assert roles_by_id["long_text_bubble"] == "message_bubble"
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert len(message_groups) >= 2
    grouped_ids = {item_id for group in message_groups for item_id in group["member_item_ids"]}
    assert {"sticker_image", "long_text_bubble"}.issubset(grouped_ids)


def test_two_stage_recovers_visual_chat_image_message_without_inventory_item(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "visual_chat_image.png"
    image = Image.new("RGB", (980, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((380, 190, 520, 330), radius=24, fill=(66, 190, 88))
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 90, "w": 560, "h": 590},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 130, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "message_time",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 350, "w": 44, "h": 18},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    image_messages = [item for item in primary["numbered_items"] if item["role"] == "image_message"]
    assert image_messages
    assert image_messages[0]["source"] == "chat_visual_image_message_synthesis"
    assert image_messages[0]["bbox"]["w"] >= 120
    assert image_messages[0]["bbox"]["h"] >= 120
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    grouped_ids = {item_id for group in message_groups for item_id in group["member_item_ids"]}
    assert image_messages[0]["item_id"] in grouped_ids


def test_chat_image_synthesis_accepts_stage1_5_message_thread_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        two_stage,
        "_visual_chat_image_message_boxes",
        lambda **_kwargs: [{"x": 420, "y": 180, "w": 120, "h": 100}],
    )

    items, audit = two_stage._synthesize_chat_image_messages(
        [],
        image_path="unused.png",
        region_bbox={"x": 200, "y": 80, "w": 600, "h": 700},
        chat_surface_confirmed=True,
    )

    assert audit["applied"] is True
    assert audit["chat_surface_evidence"] == "stage1_5_message_thread"
    assert [item["role"] for item in items] == ["image_message"]


def test_visual_chat_image_detector_recovers_repeated_small_stickers(tmp_path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "repeated_small_stickers.png"
    image = Image.new("RGB", (500, 500), "white")
    draw = ImageDraw.Draw(image)
    for top in (80, 180, 300):
        draw.rounded_rectangle((390, top, 441, top + 41), radius=8, fill=(245, 105, 75))
    draw.rectangle((120, 220, 154, 250), fill=(75, 165, 245))
    image.save(image_path)

    boxes = two_stage._visual_chat_image_message_boxes(
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 500, "h": 500},
        min_x=0,
    )

    repeated = [box for box in boxes if box["x"] >= 380 and 35 <= box["h"] <= 50]
    assert len(repeated) == 3
    assert all(box["w"] >= 45 for box in repeated)
    assert not any(box["x"] < 200 and box["w"] < 56 for box in boxes)


def test_two_stage_expands_text_only_send_button_hit_area(tmp_path):
    from PIL import Image

    image_path = tmp_path / "send_text_button.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 90, "w": 560, "h": 590},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 120, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "send_text",
            "label": "Send",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 820, "y": 660, "w": 38, "h": 18},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    send = next(item for item in primary["numbered_items"] if item["item_id"] == "send_text")
    assert send["role"] == "text_button"
    assert send["bbox"]["w"] >= 72
    assert send["bbox"]["h"] >= 34
    assert send["execute_binding_enabled"] is False
    assert send["bbox_policy"] == "text_only_button_hit_area_normalized"


def test_two_stage_message_item_absorbs_nearby_sender_and_timestamp(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 150, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Alex LV75",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 185, "w": 90, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared sticker image",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 360, "y": 215, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = next(group for group in message_groups if "image_message" in group["member_item_ids"])
    assert {"timestamp", "sender_name", "image_message"}.issubset(set(message["member_item_ids"]))
    assert message["bbox"]["y"] <= 150
    assert message["parent_child_policy"] == "message_core_absorbs_nearby_context_fragments"


def test_two_stage_message_bubble_absorbs_timestamp_context(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_context.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 280, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This is a visible text bubble that needs one message parent",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 330, "w": 310, "h": 56},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = next(group for group in message_groups if "long_text_bubble" in group["member_item_ids"])
    assert {"timestamp", "long_text_bubble"}.issubset(set(message["member_item_ids"]))
    assert message["bbox_policy"] == "message_item_core_display_bbox_context_externalized"
    assert message["bbox"]["y"] > 280


def test_two_stage_text_only_message_parent_expands_to_bubble_background(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_background.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    message = next(
        group for group in primary["subregion_groups"]
        if group["role"] == "message_item" and "long_text_bubble" in group["member_item_ids"]
    )
    assert message["bbox"]["x"] < message["raw_bbox_before_policy"]["x"]
    assert {"timestamp", "long_text_bubble"}.issubset(set(message["member_item_ids"]))
    assert message["bbox"]["w"] >= 250
    assert message["bbox"]["h"] < message["raw_bbox_before_policy"]["h"]
    assert message["bbox_policy"] == "message_item_core_display_bbox_context_externalized"
    assert message["display_only"] is True
    assert message["execute_binding_enabled"] is False


def test_message_parent_externalizes_context_gap_when_bubble_child_is_already_expanded():
    timestamp = {
        "item_id": "timestamp",
        "label": "15:10",
        "role": "text",
        "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
    }
    bubble = {
        "item_id": "bubble",
        "label": "message text",
        "role": "message_bubble",
        "bbox": {"x": 348, "y": 295, "w": 274, "h": 76},
        "bbox_policy": "message_bubble_background_expanded_needs_review",
    }

    bbox, policy = two_stage._message_parent_display_bbox(
        [timestamp, bubble],
        region_bbox={"x": 300, "y": 80, "w": 520, "h": 600},
    )

    assert policy == "message_item_core_display_bbox_context_externalized"
    assert bbox["y"] > timestamp["bbox"]["y"]
    assert bbox["y"] <= bubble["bbox"]["y"]
    assert bbox["h"] < 100


def test_two_stage_text_only_message_bubble_child_expands_to_review_background(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_child_background.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "long_text_bubble")
    assert bubble["role"] == "message_bubble"
    assert bubble["bbox"]["x"] < bubble["raw_bbox_before_policy"]["x"]
    assert bubble["bbox"]["w"] >= 250
    assert bubble["bbox"]["h"] > bubble["raw_bbox_before_policy"]["h"]
    assert bubble["bbox"]["h"] < 72
    assert bubble["bbox_policy"] == "message_bubble_background_expanded_needs_review"
    assert bubble["review_required"] is True
    assert bubble["display_only"] is True
    assert bubble["execute_binding_enabled"] is False


def test_message_bubble_review_background_uses_conservative_padding():
    raw = {"x": 302, "y": 609, "w": 249, "h": 24}
    expanded = two_stage._message_bubble_review_background_bbox(
        raw,
        parent_bbox={"x": 250, "y": 90, "w": 380, "h": 760},
    )

    assert expanded["x"] < raw["x"]
    assert expanded["w"] > raw["w"]
    assert expanded["w"] <= raw["w"] + 48
    assert expanded["h"] <= raw["h"] + 44


def test_two_stage_system_new_messages_notice_is_not_message_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "new_messages_notice.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "new_messages_notice",
            "label": "87条新消息",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 520, "y": 104, "w": 90, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "new_messages_notice")
    notice = next(item for item in primary["numbered_items"] if item["item_id"] == "new_messages_notice")
    assert notice["role"] == "text"
    assert notice["bbox"] == {"x": 520, "y": 104, "w": 90, "h": 28}
    assert notice["bbox_policy"] == "numbered_region_candidate_hint_only"
    assert "raw_bbox_before_policy" not in notice


def test_two_stage_message_card_child_text_is_not_expanded_as_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_card_child_text.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "forwarded_message_card",
            "label": "Forwarded message card with image preview",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "inner_forward_text",
            "label": "查看2条转发消息",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 315, "y": 438, "w": 96, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "inner_forward_title",
            "label": "Forwarded card title",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 315, "y": 405, "w": 140, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "regular_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 560, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "inner_forward_text")
    inner = next(item for item in primary["numbered_items"] if item["item_id"] == "inner_forward_text")
    assert inner["role"] == "message_card_content"
    assert inner["bbox"] == {"x": 315, "y": 438, "w": 96, "h": 18}
    assert inner["bbox_policy"] == "message_card_child_content_not_message_bubble"
    assert "raw_bbox_before_policy" not in inner
    inner_title = next(item for item in primary["numbered_items"] if item["item_id"] == "inner_forward_title")
    assert inner_title["role"] == "message_card_content"
    media_groups = [group for group in primary["subregion_groups"] if group["role"] == "media_card_group"]
    assert all("inner_forward_text" not in group["member_item_ids"] for group in media_groups)
    assert all("inner_forward_title" not in group["member_item_ids"] for group in media_groups)
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "regular_text_bubble")
    assert bubble["role"] == "message_bubble"
    assert bubble["bbox_policy"] == "message_bubble_background_expanded_needs_review"


def test_two_stage_image_message_parent_expands_to_review_slot(tmp_path):
    from PIL import Image

    image_path = tmp_path / "image_message_review_slot.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "standalone_image_message",
            "label": "image_message shared sticker",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 380, "y": 240, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "standalone_image_message")
    message = next(
        group for group in primary["subregion_groups"]
        if group["role"] == "message_item" and "standalone_image_message" in group["member_item_ids"]
    )
    assert message["bbox"]["x"] < message["raw_bbox_before_policy"]["x"]
    assert message["raw_bbox_before_policy"]["x"] - message["bbox"]["x"] >= 48
    assert message["bbox"]["w"] > message["raw_bbox_before_policy"]["w"]
    assert message["bbox"]["h"] > message["raw_bbox_before_policy"]["h"]
    assert message["bbox_policy"] == "message_item_image_background_expanded_needs_review"
    assert message["review_required"] is True
    assert message["display_only"] is True
    assert message["execute_binding_enabled"] is False


def test_two_stage_timestamp_above_sender_attaches_to_following_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_timestamp_sender_gap.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "previous_message_card",
            "label": "Previous forwarded message card",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "这是一条很长的聊天消息内容用于测试父框归属",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 609, "w": 249, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    previous = next(group for group in primary["subregion_groups"] if "previous_message_card" in group["member_item_ids"])
    following = next(group for group in primary["subregion_groups"] if "long_text_bubble" in group["member_item_ids"])
    assert "timestamp" not in previous["member_item_ids"]
    assert {"timestamp", "sender_name", "long_text_bubble"}.issubset(set(following["member_item_ids"]))
    timestamp = next(item for item in primary["numbered_items"] if item["item_id"] == "timestamp")
    sender = next(item for item in primary["numbered_items"] if item["item_id"] == "sender_name")
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "long_text_bubble")
    assert timestamp["semantic_parent_group_id"] == following["group_id"]
    assert timestamp["message_context_role"] == "timestamp"
    assert sender["semantic_parent_group_id"] == following["group_id"]
    assert sender["message_context_role"] == "sender_or_level"
    assert bubble["semantic_parent_group_id"] == following["group_id"]


def test_message_parent_bbox_map_reads_subregion_group_parents():
    parent_map = two_stage._message_parent_bbox_map(
        [
            {
                "subregion_groups": [
                    {
                        "group_id": "message_item_3",
                        "role": "message_item",
                        "bbox": {"x": 38, "y": 70, "w": 160, "h": 90},
                    }
                ],
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 50, "y": 42, "w": 48, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    }
                ],
            }
        ]
    )

    assert parent_map["message_item_3"] == {"x": 38, "y": 70, "w": 160, "h": 90}


def test_two_stage_overlay_renders_message_context_children_with_distinct_style(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_overlay.png"
    Image.new("RGB", (220, 160), (255, 255, 255)).save(image_path)

    overlay_path = _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=[],
        numbered_regions=[
            {
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 20, "y": 30, "w": 50, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    },
                    {
                        "number": "3.35",
                        "role": "message_bubble",
                        "bbox": {"x": 80, "y": 60, "w": 90, "h": 42},
                        "semantic_parent_group_id": "message_item_3",
                    },
                ]
            }
        ],
    )

    assert overlay_path
    with Image.open(overlay_path) as overlay:
        assert overlay.getpixel((20, 30)) == (0, 150, 170)


def test_two_stage_writes_message_context_review_overlay_and_zoom(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_review.png"
    Image.new("RGB", (260, 220), (255, 255, 255)).save(image_path)

    result = _render_message_context_review_overlay(
        image_path=str(image_path),
        numbered_regions=[
            {
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 50, "y": 42, "w": 48, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    },
                    {
                        "group_id": "message_item_3",
                        "role": "message_item",
                        "bbox": {"x": 38, "y": 70, "w": 160, "h": 90},
                    },
                    {
                        "number": "3.35",
                        "role": "message_bubble",
                        "bbox": {"x": 62, "y": 96, "w": 120, "h": 42},
                    },
                ]
            }
        ],
    )

    assert result["contract_version"] == "learn_message_context_review_overlay_v1"
    assert result["display_only"] is True
    assert result["execute_binding_enabled"] is False
    assert result["message_parent_count"] == 1
    assert result["message_context_count"] == 1
    assert Path(result["overlay_path"]).exists()
    assert Path(result["zoom_path"]).exists()


def test_two_stage_context_only_short_message_gets_review_parent(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_only_short.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "previous_message_card",
            "label": "Previous forwarded message card",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "short_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "short_sender",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "short_timestamp")
    short_parent = next(
        group for group in primary["subregion_groups"] if {"short_timestamp", "short_sender"}.issubset(group["member_item_ids"])
    )
    assert short_parent["role"] == "message_item"
    assert short_parent["parent_child_policy"] == "message_context_only_short_message_parent"
    assert short_parent["bbox_policy"] == "message_context_only_short_message_needs_review"
    assert short_parent["review_required"] is True
    assert short_parent["execute_binding_enabled"] is False
    assert "previous_message_card" not in short_parent["member_item_ids"]


def test_two_stage_message_parent_does_not_cross_multiple_timestamps(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_multiple_timestamps.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "old_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "old_sender_name",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "new_timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 407, "y": 554, "w": 37, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "这是一条很长的聊天消息内容用于测试父框归属",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 609, "w": 249, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    following = next(group for group in primary["subregion_groups"] if "long_text_bubble" in group["member_item_ids"])
    assert {"new_timestamp", "long_text_bubble"}.issubset(set(following["member_item_ids"]))
    assert "old_timestamp" not in following["member_item_ids"]
    assert "old_sender_name" not in following["member_item_ids"]


def test_two_stage_message_context_does_not_absorb_left_conversation_list(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_boundary.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_row_title",
            "label": "Project group",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 170, "y": 170, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared sticker image",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 360, "y": 190, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message = next(group for group in primary["subregion_groups"] if group["role"] == "message_item")
    assert "image_message" in message["member_item_ids"]
    assert "left_row_title" not in message["member_item_ids"]


def test_two_stage_splits_message_parent_at_new_timestamp_anchor(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_parent_split.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 90, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "first_sender",
            "label": "Alex LV75",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 288, "w": 90, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "first_message_card",
            "label": "message shared card with image",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 320, "y": 320, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "second_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 452, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "second_message_bubble",
            "label": "Second message bubble should start a separate parent",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 486, "w": 300, "h": 60},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "second_message_bubble")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert len(message_groups) >= 2
    first_group = next(group for group in message_groups if "first_message_card" in group["member_item_ids"])
    second_group = next(group for group in message_groups if "second_message_bubble" in group["member_item_ids"])
    first_card = next(item for item in primary["numbered_items"] if item["item_id"] == "first_message_card")
    assert first_group["group_id"] != second_group["group_id"]
    assert "second_message_bubble" not in first_group["member_item_ids"]
    assert "first_message_card" not in second_group["member_item_ids"]
    assert "second_timestamp" in second_group["member_item_ids"]
    assert "second_timestamp" not in first_group["member_item_ids"]
    assert first_card["bbox"]["y"] + first_card["bbox"]["h"] < 452
    assert first_card["bbox_policy"] == "message_card_clipped_before_following_start_anchor"


def test_two_stage_reconstructs_member_list_region_in_sidebar(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_list.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "member_header",
            "label": "Group members 1263",
            "role": "text",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 270, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_user",
            "label": "Blue cat / member",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    member_groups = [group for group in right["subregion_groups"] if group["role"] == "member_list_region"]
    assert member_groups
    assert set(member_groups[0]["member_item_ids"]) == {
        "member_header",
        "member_owner",
        "member_admin",
        "member_user",
    }
    assert member_groups[0]["bbox"]["h"] >= 160


def test_two_stage_adds_same_column_ocr_member_continuation_rows_from_bundle(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_list_ocr_continuation.png"
    Image.new("RGB", (1000, 760), "white").save(image_path)
    inventory = [
        {
            "item_id": "right_sidebar_panel",
            "label": "Right sidebar panel",
            "role": "boundary_review_region",
            "item_type": "panel",
            "bbox": {"x": 740, "y": 100, "w": 230, "h": 610},
            "review_only": True,
        },
        {
            "item_id": "member_header",
            "label": "Group members 1263",
            "role": "member_list_header",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 270, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 1000, "height": 760},
            "screen_reading": {
                "texts": [
                    {
                        "text": "Ad astra",
                        "bbox": {"x": 772, "y": 420, "w": 64, "h": 20},
                        "source": "ocr_fallback",
                    },
                    {
                        "text": "ADaChi",
                        "bbox": {"x": 772, "y": 456, "w": 58, "h": 20},
                        "source": "ocr_fallback",
                    },
                    {
                        "text": "Central chat text",
                        "bbox": {"x": 400, "y": 456, "w": 120, "h": 20},
                        "source": "ocr_fallback",
                    },
                ]
            },
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    labels = {item["label"] for item in right["numbered_items"]}
    assert "Ad astra" in labels
    assert "ADaChi" in labels
    assert "Central chat text" not in labels
    member_group = next(
        group
        for group in right["subregion_groups"]
        if group["role"] == "member_list_region"
        and {"ocr_bundle_text_1", "ocr_bundle_text_2"}.issubset(set(group["member_item_ids"]))
    )
    assert {"ocr_bundle_text_1", "ocr_bundle_text_2"}.issubset(set(member_group["member_item_ids"]))
    assert member_group["bbox"]["y"] + member_group["bbox"]["h"] >= 476


def test_two_stage_uses_child_member_header_inside_oversized_sidebar_boundary(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_header_child_proxy.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body",
            "label": "Pinned note for members",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "mixed_notice_member",
            "label": "Pinned note / Group members 1263",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 748, "y": 142, "w": 212, "h": 190},
            "children": [
                {
                    "child_id": "member_header_text",
                    "label": "Group members 1263",
                    "role": "text",
                    "bbox": {"x": 762, "y": 270, "w": 158, "h": 24},
                }
            ],
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_user",
            "label": "Blue cat / member",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    member_group = next(group for group in right["subregion_groups"] if group["role"] == "member_list_region")
    assert member_group["bbox"]["y"] <= 320
    assert {"member_owner", "member_admin", "member_user"}.issubset(set(member_group["member_item_ids"]))
    merged = next(item for item in right["numbered_items"] if item["item_id"].startswith("merged_"))
    assert merged["role"] == "sidebar_review_region"
    assert merged["execute_binding_enabled"] is False


def test_member_list_parent_groups_extracts_header_child_from_boundary_container():
    groups = two_stage._member_list_parent_groups(
        region={"region_id": "structure_region_right_sidebar"},
        numbered_items=[
            {
                "number": "4.2",
                "item_id": "mixed_notice_member",
                "label": "Pinned note / Group members 1263",
                "role": "nav_item",
                "bbox": {"x": 748, "y": 142, "w": 212, "h": 190},
                "children": [
                    {
                        "child_id": "member_header_text",
                        "label": "Group members 1263",
                        "role": "text",
                        "bbox": {"x": 762, "y": 270, "w": 158, "h": 24},
                    }
                ],
            },
            {
                "number": "4.8",
                "item_id": "member_owner",
                "label": "Cateek / owner",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            },
            {
                "number": "4.9",
                "item_id": "member_admin",
                "label": "Alex / admin",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            },
            {
                "number": "4.10",
                "item_id": "member_user",
                "label": "Blue cat / member",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            },
        ],
    )

    assert groups
    member_group = groups[0]
    assert member_group["bbox"]["y"] == 270
    assert "member_header_text" in member_group["member_item_ids"]
    assert member_group["label"] == "Group members 1263"


def test_member_list_parent_groups_keep_plain_continuation_rows_after_header():
    groups = two_stage._member_list_parent_groups(
        region={"region_id": "structure_region_right_sidebar"},
        numbered_items=[
            {
                "number": "4.1",
                "item_id": "notice_title",
                "label": "Group announcement",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 120, "w": 190, "h": 30},
            },
            {
                "number": "4.2",
                "item_id": "member_header",
                "label": "Group members 1263",
                "role": "member_list_header",
                "bbox": {"x": 760, "y": 270, "w": 190, "h": 28},
            },
            {
                "number": "4.3",
                "item_id": "member_admin",
                "label": "Alex / admin",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            },
            {
                "number": "4.4",
                "item_id": "plain_member_one",
                "label": "AAA谢尔曼批发",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            },
            {
                "number": "4.5",
                "item_id": "plain_member_two",
                "label": "AAA煤炭批发小王",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            },
        ],
    )

    assert groups
    member_group = groups[0]
    assert "notice_title" not in member_group["member_item_ids"]
    assert {"member_header", "member_admin", "plain_member_one", "plain_member_two"}.issubset(
        set(member_group["member_item_ids"])
    )
    assert member_group["bbox"]["y"] == 270
    assert member_group["bbox"]["h"] >= 164


def test_two_stage_reconstructs_conversation_rows_in_primary_list_column(tmp_path):
    from PIL import Image

    image_path = tmp_path / "conversation_rows.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "row_one_title",
            "label": "Project group",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 140, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_one_preview",
            "label": "Latest message preview",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 166, "w": 180, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_one_time",
            "label": "18:55",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 270, "y": 140, "w": 42, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "row_two_title",
            "label": "Design chat",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 220, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_two_preview",
            "label": "Another message preview",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 246, "w": 180, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "chat_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 430, "y": 180, "w": 120, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    conversation_groups = [group for group in primary["subregion_groups"] if group["role"] == "conversation_row"]
    assert len(conversation_groups) >= 2
    assert {"row_one_title", "row_one_preview", "row_one_time"}.issubset(
        set(conversation_groups[0]["member_item_ids"])
    )


def test_conversation_class_prefers_complete_repeated_row_containers_over_text_fragments() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "label": "Primary Area",
        "bbox": {"x": 78, "y": 104, "w": 874, "h": 925},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "chat_filters",
            "label": "chat-list-filters",
            "role": "message_bubble",
            "item_type": "message_bubble",
            "bbox": {"x": 78, "y": 143, "w": 340, "h": 83},
        },
        {
            "number": "1.2",
            "item_id": "row_one",
            "label": "Project group 18:55 Latest message",
            "role": "dataitem",
            "item_type": "dataitem",
            "bbox": {"x": 78, "y": 228, "w": 315, "h": 77},
        },
        {
            "number": "1.3",
            "item_id": "row_one_title",
            "label": "Project group",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 241, "w": 110, "h": 22},
        },
        {
            "number": "1.4",
            "item_id": "row_one_preview",
            "label": "Latest message",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 267, "w": 120, "h": 20},
        },
        {
            "number": "1.4a",
            "item_id": "row_one_visual_card",
            "label": "Project group latest message",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 140, "y": 230, "w": 240, "h": 60},
        },
        {
            "number": "1.5",
            "item_id": "row_two",
            "label": "Design chat Thursday Another message",
            "role": "dataitem",
            "item_type": "dataitem",
            "bbox": {"x": 78, "y": 304, "w": 315, "h": 77},
        },
        {
            "number": "1.6",
            "item_id": "row_two_title",
            "label": "Design chat",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 317, "w": 110, "h": 22},
        },
        {
            "number": "1.7",
            "item_id": "row_two_preview",
            "label": "Another message",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 343, "w": 130, "h": 20},
        },
        {
            "number": "1.8",
            "item_id": "row_three",
            "label": "Support chat Monday Resolved",
            "role": "message_bubble",
            "item_type": "message_bubble",
            "bbox": {"x": 78, "y": 380, "w": 315, "h": 77},
        },
        {
            "number": "1.9",
            "item_id": "row_three_title",
            "label": "Support chat",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 393, "w": 110, "h": 22},
        },
        {
            "number": "1.10",
            "item_id": "right_pane_action",
            "label": "Send document",
            "role": "text_button",
            "item_type": "actionable",
            "bbox": {"x": 516, "y": 304, "w": 113, "h": 48},
        },
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "conversation_rows",
            "allow_chat_semantics": True,
        },
    )

    conversation_groups = [group for group in groups if group.get("role") == "conversation_row"]
    assert [group["bbox"] for group in conversation_groups] == [
        {"x": 78, "y": 228, "w": 315, "h": 77},
        {"x": 78, "y": 304, "w": 315, "h": 77},
        {"x": 78, "y": 380, "w": 315, "h": 77},
    ]
    assert conversation_groups[0]["member_item_ids"][0] == "row_one"
    assert {"row_one_title", "row_one_preview"}.issubset(conversation_groups[0]["member_item_ids"])
    assert all("right_pane_action" not in group["member_item_ids"] for group in conversation_groups)
    assert all(group.get("role") != "tile_card_parent" for group in groups), [
        (group.get("role"), group.get("bbox")) for group in groups
    ]
    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(
        {**region, "numbered_items": numbered_items, "subregion_groups": conversation_groups}
    )
    assert [item["item_id"] for item in calibratable] == [
        "chat_filters",
        "right_pane_action",
        "conversation_row_1",
        "conversation_row_2",
        "conversation_row_3",
    ]
    assert {"row_one", "row_one_title", "row_one_preview"}.issubset(
        {item["item_id"] for item in child_evidence}
    )


def test_ungrouped_review_region_keeps_actionable_controls_for_calibration() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 640, "h": 480},
        "numbered_items": [
            {
                "item_id": "empty_state_description",
                "label": "Choose an action",
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 220, "y": 180, "w": 160, "h": 24},
            },
            {
                "item_id": "send_document",
                "label": "Send document",
                "role": "button",
                "item_type": "actionable",
                "bbox": {"x": 220, "y": 220, "w": 120, "h": 64},
            },
        ],
        "subregion_groups": [
            {
                "group_id": "ungrouped_review_region_1",
                "role": "ungrouped_review_region",
                "bbox": {"x": 180, "y": 140, "w": 280, "h": 180},
                "member_item_ids": ["empty_state_description", "send_document"],
            }
        ],
    }

    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(region)

    assert [item["item_id"] for item in calibratable] == ["send_document"]
    assert calibratable[0]["display_hierarchy"]["display_layer"] == "primary_region"
    assert [item["item_id"] for item in child_evidence] == ["empty_state_description"]


def test_ungrouped_review_region_keeps_visual_controls_for_calibration() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
        "numbered_items": [
            {
                "item_id": "embedded_top_control_1",
                "label": "visual control 1",
                "role": "control",
                "item_type": "visual_control",
                "bbox": {"x": 80, "y": 12, "w": 40, "h": 36},
                "review_only": True,
                "execute_binding_enabled": False,
            }
        ],
        "subregion_groups": [
            {
                "group_id": "ungrouped_review_region_1",
                "role": "ungrouped_review_region",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 80},
                "member_item_ids": ["embedded_top_control_1"],
            }
        ],
    }

    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(region)

    assert [item["item_id"] for item in calibratable] == ["embedded_top_control_1"]
    assert child_evidence == []


def test_ungrouped_review_region_ids_are_scoped_to_parent_region() -> None:
    numbered_items = [
        {
            "number": f"1.{index}",
            "item_id": f"item_{index}",
            "label": f"item {index}",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 40 + index * 28, "w": 100, "h": 20},
        }
        for index in range(1, 6)
    ]
    seed_group = {
        "group_id": "seed",
        "role": "review_only",
        "bbox": {"x": 90, "y": 60, "w": 120, "h": 24},
        "member_item_ids": ["item_1"],
    }

    def generated_id(region_id: str) -> str:
        groups = two_stage._ensure_primary_items_have_subregion_parent(
            region={
                "region_id": region_id,
                "bbox": {"x": 0, "y": 0, "w": 640, "h": 480},
            },
            numbered_items=numbered_items,
            groups=[seed_group],
        )
        return next(group["group_id"] for group in groups if group.get("role") == "ungrouped_review_region")

    message_id = generated_id("structure_region_main_content__stage1_5__message_thread")
    auxiliary_id = generated_id("structure_region_main_content__stage1_5__auxiliary_pane")

    assert message_id != auxiliary_id
    assert "message_thread" in message_id
    assert "auxiliary_pane" in auxiliary_id


def test_stage2_reports_actual_calibration_parent_count_separately_from_numbered_items() -> None:
    stage2 = {
        "numbered_item_count": 4,
        "regions": [
            {
                "region_id": "conversation_list",
                "numbered_items": [
                    {
                        "item_id": "row_title",
                        "label": "Alice",
                        "role": "text",
                        "bbox": {"x": 20, "y": 100, "w": 80, "h": 20},
                    },
                    {
                        "item_id": "row_preview",
                        "label": "Hello",
                        "role": "text",
                        "bbox": {"x": 20, "y": 124, "w": 120, "h": 18},
                    },
                    {
                        "item_id": "filter_button",
                        "label": "Filter",
                        "role": "button",
                        "bbox": {"x": 180, "y": 40, "w": 60, "h": 28},
                    },
                    {
                        "item_id": "new_chat",
                        "label": "New chat",
                        "role": "button",
                        "bbox": {"x": 250, "y": 40, "w": 80, "h": 28},
                    },
                ],
                "subregion_groups": [
                    {
                        "group_id": "conversation_row_1",
                        "role": "conversation_row",
                        "bbox": {"x": 8, "y": 92, "w": 340, "h": 64},
                        "member_item_ids": ["row_title", "row_preview"],
                        "adjacent_fragment_merged": True,
                    }
                ],
            }
        ],
    }

    summary = two_stage.summarize_stage2_calibration_partition(stage2)

    assert summary["numbered_item_count"] == 4
    assert summary["calibration_candidate_count"] == 3
    assert summary["calibration_child_evidence_count"] == 2
    assert summary["calibration_region_count"] == 1
    assert summary["count_basis"] == "parent_or_standalone_items_after_display_hierarchy_partition"


def test_chat_resize_control_is_not_reclassified_as_message_bubble() -> None:
    item = {
        "item_id": "chat_panel_resize_control",
        "label": "\u8c03\u6574\u804a\u5929\u5217\u8868\u9762\u677f\u5927\u5c0f",
        "role": "button",
        "item_type": "actionable",
        "bbox": {"x": 392, "y": 39, "w": 25, "h": 982},
    }

    assert two_stage._message_child_role(item, chat_context=True) != "message_bubble"


def test_actionable_structural_container_stays_detail_only_inside_ungrouped_review_region() -> None:
    hierarchy = two_stage._item_display_hierarchy(
        {
            "item_id": "uia_document",
            "label": "Document",
            "role": "document",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 127, "w": 2552, "h": 1277},
        },
        [{"group_id": "ungrouped_review_region_1", "role": "ungrouped_review_region"}],
    )

    assert hierarchy["display_layer"] == "child_evidence"
    assert hierarchy["render_in_main_overlay"] is False
    assert hierarchy["demotion_reason"] == "ungrouped_review_region_detail_only"


def test_conversation_class_rows_include_avatar_gutter_and_exclude_section_heading() -> None:
    region = {
        "region_id": "structure_region_main_content__stage1_5__conversation_list",
        "label": "Conversation list",
        "bbox": {"x": 0, "y": 80, "w": 420, "h": 520},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "online_heading",
            "label": "在线好友 (12)",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 14, "y": 92, "w": 110, "h": 18},
        },
        *[
            item
            for index, (name, y) in enumerate((("Friend One", 124), ("Friend Two", 168), ("Friend Three", 212)), start=1)
            for item in (
                {
                    "number": f"1.{index * 3 - 1}",
                    "item_id": f"avatar_{index}",
                    "label": f"{name} avatar",
                    "role": "avatar",
                    "item_type": "review_only",
                    "bbox": {"x": 16, "y": y, "w": 32, "h": 32},
                },
                {
                    "number": f"1.{index * 3}",
                    "item_id": f"friend_{index}",
                    "label": name,
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 54, "y": y, "w": 110, "h": 18},
                },
                {
                    "number": f"1.{index * 3 + 1}",
                    "item_id": f"status_{index}",
                    "label": "Online",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 54, "y": y + 18, "w": 52, "h": 16},
                },
            )
        ],
        {
            "number": "1.11",
            "item_id": "offline_heading",
            "label": "离线 (44)",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 14, "y": 264, "w": 86, "h": 18},
        },
        {
            "number": "1.12",
            "item_id": "offline_expand",
            "label": "↓",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 104, "y": 264, "w": 18, "h": 18},
        },
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "conversation_rows",
            "allow_chat_semantics": True,
        },
    )

    conversation_groups = [group for group in groups if group.get("role") == "conversation_row"]
    assert len(conversation_groups) == 3
    assert all(group["bbox"]["x"] <= 16 for group in conversation_groups)
    assert [group["member_item_ids"][0] for group in conversation_groups] == ["avatar_1", "avatar_2", "avatar_3"]
    assert all("offline_heading" not in group["member_item_ids"] for group in conversation_groups)
    assert all(group["leading_visual_gutter"]["source"] == "class_repeated_layout_inference" for group in conversation_groups)


def test_two_stage_refines_sparse_top_bar_and_clips_left_child_to_authoritative_partition(tmp_path):
    image_path = tmp_path / "toolbar.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 240), "white")
    draw = ImageDraw.Draw(image)
    for x in (242, 292, 342, 442):
        draw.rectangle((x, 24, x + 14, 38), fill="black")
    for y in (82, 132, 182):
        draw.rectangle((16, y, 38, y + 22), outline="black", width=3)
    image.save(image_path)

    inventory = [
        {
            "item_id": "top_1",
            "label": "Top control 1",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 120, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_2",
            "label": "Top control 2",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 140, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_3",
            "label": "Top control 3",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 160, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_4",
            "label": "Top control 4",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 180, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "nav_1",
            "label": "Nav 1",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 72, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_2",
            "label": "Nav 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 122, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_3",
            "label": "Nav 3",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 172, "w": 43, "h": 43},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "page_header": {"item_ids": ["top_1", "top_2", "top_3", "top_4"]},
            "left_nav": {"item_ids": ["nav_1", "nav_2", "nav_3"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 240}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    header = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    assert header["grouping_strategy"] == "direct_region_numbering_without_subgrouping"
    assert header["visual_small_control_refinement"]["applied"] is True
    assert header["visual_small_control_refinement"]["refined_count"] == 4
    assert header["numbered_items"][0]["bbox"]["x"] >= 230
    assert header["numbered_items"][0]["bbox_refinement"]["source"] == "visual_small_control_segmenter"

    assert left_nav["grouping_strategy"] == "direct_region_numbering_without_subgrouping"
    assert left_nav["visual_small_control_refinement"]["applied"] is False, left_nav[
        "visual_small_control_refinement"
    ]
    assert left_nav["visual_small_control_refinement"]["reason"] in {
        "model_boxes_already_overlap_visual_candidates",
        "insufficient_visual_candidates",
    }
    assert [item["bbox"] for item in left_nav["numbered_items"]] == [
        {"x": 10, "y": 80, "w": 43, "h": 35},
        {"x": 10, "y": 122, "w": 43, "h": 43},
        {"x": 10, "y": 172, "w": 43, "h": 43},
    ]


def test_two_stage_synthesizes_top_controls_when_text_inventory_is_sparse(tmp_path):
    image_path = tmp_path / "sparse_top_controls.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (620, 260), "white")
    draw = ImageDraw.Draw(image)
    for x in (124, 164, 204, 244, 384, 504):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    for y in (94, 144):
        draw.rectangle((16, y, 38, y + 22), outline="black", width=3)
    image.save(image_path)

    inventory = [
        {
            "item_id": "title_text",
            "label": "x",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 600, "y": 8, "w": 12, "h": 14},
            "review_only": True,
        },
        {
            "item_id": "nav_1",
            "label": "Nav 1",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 92, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_2",
            "label": "Nav 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 142, "w": 43, "h": 43},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["title_text"]},
            "left_nav": {"item_ids": ["nav_1", "nav_2"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 620, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_browser_chrome"
    )
    assert top["input_region_bbox"]["x"] == 0
    assert top["input_region_bbox"]["w"] == 620
    assert top["visual_small_control_refinement"]["reason"] == "visual_candidates_replace_sparse_text_inventory"
    assert top["numbered_item_count"] >= 6
    assert {item["role"] for item in top["numbered_items"]} == {"control"}
    assert all(item["bbox"]["w"] >= 36 for item in top["numbered_items"])
    assert all(item["bbox"]["h"] >= 30 for item in top["numbered_items"])


def test_two_stage_creates_topbar_control_strip_parent_group(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_parent.png"
    image = Image.new("RGB", (720, 280), "white")
    draw = ImageDraw.Draw(image)
    for x in (120, 164, 208, 328, 520, 604, 652):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": x, "y": 18, "w": 28, "h": 28},
            "review_only": True,
        }
        for index, x in enumerate((118, 162, 206, 326, 518, 602, 650), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"page_header": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 280}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    strip_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_control_strip"]
    assert strip_groups
    strip = strip_groups[0]
    assert strip["display_only"] is True
    assert strip["execute_binding_enabled"] is False
    assert strip["artifact_is_authorization"] is False
    assert strip["bbox"]["x"] <= 118
    assert strip["bbox"]["w"] >= 560
    assert strip["bbox"]["h"] >= 48
    assert set(strip["member_item_ids"]) == {item["item_id"] for item in top["numbered_items"]}


def test_two_stage_splits_topbar_controls_into_display_only_clusters(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_clusters.png"
    image = Image.new("RGB", (720, 280), "white")
    draw = ImageDraw.Draw(image)
    for x in (120, 164, 208, 328, 520, 604, 652):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": x, "y": 18, "w": 28, "h": 28},
            "review_only": True,
        }
        for index, x in enumerate((118, 162, 206, 326, 518, 602, 650), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"page_header": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 280}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    strip = next(group for group in top["subregion_groups"] if group["role"] == "topbar_control_strip")
    clusters = [group for group in top["subregion_groups"] if group["role"] == "topbar_control_cluster"]
    assert len(clusters) >= 3
    assert all(group["display_only"] is True for group in clusters)
    assert all(group["execute_binding_enabled"] is False for group in clusters)
    assert all(group["artifact_is_authorization"] is False for group in clusters)
    assert all(group["bbox"]["w"] < strip["bbox"]["w"] * 0.65 for group in clusters)

    clustered_item_ids = [item_id for group in clusters for item_id in group["member_item_ids"]]
    assert set(clustered_item_ids) == {item["item_id"] for item in top["numbered_items"]}
    assert len(clustered_item_ids) == len(set(clustered_item_ids))


def test_two_stage_adds_sparse_center_topbar_semantic_parent(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_sparse_status_parent.png"
    image = Image.new("RGB", (1154, 260), "white")
    draw = ImageDraw.Draw(image)
    for x in (112, 151, 193, 232, 273, 371, 575, 830, 877, 923, 1012, 1058, 1104):
        draw.rectangle((x + 14, 20, x + 26, 32), fill="black")
    draw.rounded_rectangle((330, 12, 710, 62), radius=6, outline="#dddddd", width=2)
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": x + 16, "y": 20, "w": 12, "h": 12},
            "review_only": True,
        }
        for index, x in enumerate((112, 151, 193, 232, 273, 371, 575, 830, 877, 923, 1012, 1058, 1104), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1154, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    semantic_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_semantic_group"]
    assert semantic_groups
    group = semantic_groups[0]
    assert group["display_only"] is True
    assert group["execute_binding_enabled"] is False
    assert group["artifact_is_authorization"] is False
    assert group["parent_child_policy"] == "sparse_center_topbar_controls_share_display_only_semantic_parent"
    assert group["bbox_policy"] == "topbar_sparse_aligned_controls_expand_to_status_parent"
    assert group["bbox"]["x"] <= 342
    assert group["bbox"]["x"] + group["bbox"]["w"] >= 700
    assert set(group["member_item_ids"]) == {"top_control_6", "top_control_7"}
    assert not any({"top_control_8", "top_control_9"} & set(group["member_item_ids"]) for group in semantic_groups)


def test_two_stage_does_not_add_sparse_semantic_parent_for_text_nav_bar(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_text_nav.png"
    image = Image.new("RGB", (1200, 260), "white")
    draw = ImageDraw.Draw(image)
    for x, text in (
        (120, "Python"),
        (360, "About"),
        (520, "Downloads"),
        (710, "Documentation"),
        (920, "Community"),
        (1080, "Success Stories"),
    ):
        draw.text((x, 30), text, fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"nav_{index}",
            "label": label,
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": x, "y": 28, "w": w, "h": 24},
            "review_only": True,
        }
        for index, (label, x, w) in enumerate(
            (
                ("Python", 120, 72),
                ("About", 360, 62),
                ("Downloads", 520, 112),
                ("Documentation", 710, 156),
                ("Community", 920, 124),
                ("Success Stories", 1080, 148),
            ),
            start=1,
        )
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    semantic_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_semantic_group"]
    assert semantic_groups == []


def test_settings_topbar_status_tile_replaces_text_fragments_for_calibration() -> None:
    region = {
        "region_id": "structure_region_top_bar",
        "label": "Top/header area",
        "bbox": {"x": 0, "y": 0, "w": 1216, "h": 163},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "profile_control",
            "label": "profile",
            "role": "control",
            "item_type": "visual_control",
            "bbox": {"x": 144, "y": 51, "w": 72, "h": 52},
        },
        {
            "number": "1.2",
            "item_id": "rewards_icon",
            "label": "visual control 2",
            "role": "control",
            "item_type": "visual_control",
            "bbox": {"x": 855, "y": 51, "w": 72, "h": 52},
        },
        {
            "number": "1.3",
            "item_id": "rewards_title",
            "label": "Rewards",
            "role": "nav_text_action",
            "item_type": "review_only",
            "bbox": {"x": 864, "y": 114, "w": 57, "h": 18},
        },
        {
            "number": "1.4",
            "item_id": "rewards_points",
            "label": "17325积分",
            "role": "control",
            "item_type": "visual_control",
            "bbox": {"x": 862, "y": 116, "w": 72, "h": 47},
            "children": [
                {
                    "item_id": "rewards_points_text",
                    "label": "17325积分",
                    "role": "text",
                    "bbox": {"x": 863, "y": 133, "w": 63, "h": 20},
                }
            ],
        },
        {
            "number": "1.5",
            "item_id": "help_control",
            "label": "help",
            "role": "control",
            "item_type": "visual_control",
            "bbox": {"x": 1080, "y": 51, "w": 52, "h": 52},
        },
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "interface_class": "settings_dashboard",
            "primary_content_strategy": "independent_control_cards",
            "allow_chat_semantics": False,
        },
    )

    status_tile = next(group for group in groups if group.get("role") == "settings_status_tile")
    assert set(status_tile["member_item_ids"]) == {"rewards_icon", "rewards_title", "rewards_points"}
    assert status_tile["adjacent_fragment_merged"] is True
    assert status_tile["bbox"]["x"] <= 838 < status_tile["bbox"]["x"] + status_tile["bbox"]["w"]
    assert status_tile["bbox"]["y"] <= 65 < status_tile["bbox"]["y"] + status_tile["bbox"]["h"]

    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(
        {"numbered_items": numbered_items, "subregion_groups": groups}
    )
    assert {item["item_id"] for item in calibratable} == {
        "profile_control",
        "help_control",
        status_tile["group_id"],
    }
    assert {item["item_id"] for item in child_evidence} >= {
        "rewards_icon",
        "rewards_title",
        "rewards_points",
    }


def test_finalized_parent_group_candidate_preserves_source_id_and_uses_final_id() -> None:
    calibratable, child_evidence = two_stage.partition_stage2_calibration_items(
        {
            "numbered_items": [
                {
                    "item_id": "source_title",
                    "final_item_id": "final-item:rev:00001",
                    "label": "Result title",
                    "role": "text",
                    "bbox": {"x": 20, "y": 20, "w": 120, "h": 24},
                }
            ],
            "subregion_groups": [
                {
                    "group_id": "source_card",
                    "final_group_id": "final-group:rev:00001",
                    "label": "Result card",
                    "role": "tile_card_parent",
                    "bbox": {"x": 10, "y": 10, "w": 180, "h": 90},
                    "member_item_ids": ["source_title"],
                }
            ],
        }
    )

    assert child_evidence
    assert len(calibratable) == 1
    assert calibratable[0]["item_id"] == "source_card"
    assert calibratable[0]["source_item_id"] == "source_card"
    assert calibratable[0]["final_item_id"] == "final-group:rev:00001"






def test_authoritative_partition_does_not_apply_app_specific_browser_chrome_suppression(tmp_path):
    from PIL import Image

    image_path = tmp_path / "native_settings_surface.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "native_window_title",
            "label": "Settings",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 16, "y": 8, "w": 80, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "account_header",
            "label": "Account",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 180, "y": 72, "w": 120, "h": 32},
            "review_only": True,
        },
        {
            "item_id": "settings_main_panel",
            "label": "Settings categories",
            "role": "container",
            "item_type": "container",
            "bbox": {"x": 0, "y": 150, "w": 1200, "h": 650},
            "review_only": True,
        },
        {
            "item_id": "settings_search",
            "label": "Find a setting",
            "role": "input",
            "item_type": "input",
            "bbox": {"x": 430, "y": 210, "w": 340, "h": 36},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["native_window_title"]},
            "top_bar": {"item_ids": ["native_window_title", "account_header"]},
            "primary_area": {"item_ids": ["settings_main_panel", "settings_search"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 1200, "height": 800},
            "request": {"app_name": "native_settings_host"},
            "result": {"app_name": "native_settings_host"},
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    localized = result["stage1_region_localization"]
    assert any(region["region_id"] == "structure_region_browser_chrome" for region in localized["regions"])
    assert localized["legacy_bar_postprocessing_applied"] is False
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"
    assert result["stage2_numbering_skipped"] is True


def test_file_browser_interface_category_is_not_treated_as_web_browser_app() -> None:
    assert two_stage._is_browser_app_name("file_browser_system_drive") is False
    assert two_stage._is_browser_app_name("windows_file_browser") is False
    assert two_stage._is_browser_app_name("msedge_browser") is True


def test_authoritative_partition_preserves_fixture_regions_without_app_specific_rewrite(tmp_path):
    from PIL import Image

    image_path = tmp_path / "native_file_browser_with_model_chrome_label.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "model_window_toolbar",
            "label": "Window toolbar",
            "role": "browser_chrome",
            "item_type": "container",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "native_toolbar",
            "label": "File toolbar",
            "role": "toolbar",
            "item_type": "container",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 110},
            "review_only": True,
        },
        {
            "item_id": "folder_tree",
            "label": "Folder tree",
            "role": "left_nav",
            "item_type": "tree",
            "bbox": {"x": 0, "y": 110, "w": 190, "h": 590},
            "review_only": True,
        },
        {
            "item_id": "file_table",
            "label": "Files and folders",
            "role": "table",
            "item_type": "list",
            "bbox": {"x": 190, "y": 110, "w": 810, "h": 590},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["model_window_toolbar"]},
            "top_bar": {"item_ids": ["native_toolbar"]},
            "left_nav": {"item_ids": ["folder_tree"]},
            "main_content": {"item_ids": ["file_table"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 1000, "height": 700},
            "request": {"app_name": "file_explorer"},
            "result": {"app_name": "file_explorer"},
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    region_ids = {
        region["region_id"]
        for region in result["stage1_region_localization"]["regions"]
    }
    assert "structure_region_browser_chrome" in region_ids
    assert "structure_region_floating_controls" not in region_ids
    assert result["stage1_region_localization"]["legacy_bar_postprocessing_applied"] is False
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"




def test_left_nav_calibration_prefers_complete_rough_boundary_over_screen_width_floor() -> None:
    region = {
        "region_id": "structure_region_left_nav",
        "zone_id": "left_nav",
        "bbox": {"x": 17, "y": 141, "w": 141, "h": 1268},
        "item_ids": ["back_button"],
    }
    items = {
        "back_button": {
            "item_id": "back_button",
            "label": "Back button",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 32, "y": 225, "w": 32, "h": 32},
        }
    }

    calibrated = two_stage._calibrated_stage1_bbox(
        region,
        items_by_id=items,
        screen_size={"width": 2576, "height": 1416},
    )

    assert calibrated["bbox"]["x"] == 0
    assert calibrated["bbox"]["w"] == 158
    assert calibrated["bbox"]["w"] < int(2576 * 0.08)






def test_conversation_bottom_panel_normalizes_generic_news_card_to_group_chat_row() -> None:
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 3,
                "region_id": "structure_region_conversation_bottom_panel",
                "zone_id": "conversation_bottom_panel",
                "label": "Conversation bottom panel",
                "bbox": {"x": 0, "y": 850, "w": 800, "h": 150},
                "item_ids": ["group_chat"],
            }
        ],
        items_by_id={
            "group_chat": {
                "item_id": "group_chat",
                "label": "GIFTHub",
                "role": "news_card",
                "item_type": "card",
                "bbox": {"x": 8, "y": 890, "w": 410, "h": 72},
                "review_only": True,
            }
        },
        class_rule_profile={
            "primary_content_strategy": "conversation_rows",
            "allow_chat_semantics": True,
        },
    )

    item = result["regions"][0]["numbered_items"][0]
    assert item["role"] == "group_chat_row"
    assert item["original_role"] == "news_card"


def test_non_conversation_surface_preserves_news_card_role() -> None:
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "zone_id": "main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 80, "w": 800, "h": 720},
                "item_ids": ["news"],
            }
        ],
        items_by_id={
            "news": {
                "item_id": "news",
                "label": "Latest news",
                "role": "news_card",
                "item_type": "card",
                "bbox": {"x": 20, "y": 100, "w": 300, "h": 180},
                "review_only": True,
            }
        },
        class_rule_profile={
            "primary_content_strategy": "text_structure_first",
            "allow_chat_semantics": False,
        },
    )

    item = result["regions"][0]["numbered_items"][0]
    assert item["role"] == "news_card"
    assert "original_role" not in item


def test_stage1_suppresses_text_only_column_without_sidebar_structure_evidence():
    import app.learn.recognition.two_stage as two_stage

    regions = [
        {
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "label": "Main content",
            "bbox": {"x": 0, "y": 80, "w": 900, "h": 920},
            "item_ids": ["keypad"],
        },
        {
            "region_id": "structure_region_left_sidebar",
            "zone_id": "left_sidebar",
            "label": "Left sidebar",
            "bbox": {"x": 40, "y": 300, "w": 260, "h": 650},
            "item_ids": ["digit_7", "digit_4", "digit_1"],
        },
    ]
    items = {
        "keypad": {"item_id": "keypad", "role": "group", "item_type": "container"},
        "digit_7": {"item_id": "digit_7", "role": "text", "item_type": "ocr_text"},
        "digit_4": {"item_id": "digit_4", "role": "text", "item_type": "ocr_text"},
        "digit_1": {"item_id": "digit_1", "role": "text", "item_type": "ocr_text"},
    }

    resolved, audit = two_stage._resolve_stage1_surface_conflicts(
        regions,
        items_by_id=items,
        app_name="calculator",
    )

    assert [region["region_id"] for region in resolved] == ["structure_region_main_content"]
    assert audit["suppressed_regions"][0]["reason"] == (
        "text_only_column_without_sidebar_structure_evidence"
    )


def test_stage1_preserves_full_height_edge_aligned_text_sidebar():
    import app.learn.recognition.two_stage as two_stage

    regions = [
        {
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "bbox": {"x": 0, "y": 100, "w": 1000, "h": 700},
            "item_ids": ["content"],
        },
        {
            "region_id": "structure_region_left_sidebar",
            "zone_id": "left_sidebar",
            "bbox": {"x": 0, "y": 100, "w": 220, "h": 700},
            "item_ids": ["row_1", "row_2", "row_3"],
        },
    ]
    items = {
        "content": {"item_id": "content", "role": "container"},
        "row_1": {"item_id": "row_1", "role": "text", "source": "ocr"},
        "row_2": {"item_id": "row_2", "role": "text", "source": "ocr"},
        "row_3": {"item_id": "row_3", "role": "text", "source": "ocr"},
    }

    resolved, audit = two_stage._resolve_stage1_surface_conflicts(
        regions,
        items_by_id=items,
        app_name="chat_surface",
    )

    assert {region["region_id"] for region in resolved} == {
        "structure_region_main_content",
        "structure_region_left_sidebar",
    }
    assert audit["suppressed_region_count"] == 0


def test_stage1_merges_contained_native_top_bars_but_keeps_browser_chrome_separate():
    import app.learn.recognition.two_stage as two_stage

    top_bar = {
        "region_id": "structure_region_top_bar",
        "zone_id": "top_bar",
        "item_ids": ["ribbon", "toolbar"],
    }
    page_header = {
        "region_id": "structure_region_page_header",
        "zone_id": "page_header",
        "item_ids": ["address", "search"],
    }
    outer = {"x": 0, "y": 0, "w": 1200, "h": 240}
    inner = {"x": 0, "y": 100, "w": 1200, "h": 140}

    assert two_stage._same_family_structure_region_duplicate(top_bar, page_header, outer, inner) is True

    browser_chrome = {
        "region_id": "structure_region_browser_chrome",
        "zone_id": "browser_chrome",
        "item_ids": ["address_bar", "tabs"],
    }
    assert two_stage._same_family_structure_region_duplicate(browser_chrome, page_header, outer, inner) is False


def test_stage1_merges_adjacent_native_top_regions_when_rough_evidence_is_the_same_bar():
    import app.learn.recognition.two_stage as two_stage

    regions = [
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "item_ids": ["toolbar"],
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 109},
            "precise_bbox": {"x": 0, "y": 0, "w": 800, "h": 109},
            "rough_bbox": {"x": 0, "y": 0, "w": 800, "h": 163},
        },
        {
            "region_id": "structure_region_page_header",
            "zone_id": "page_header",
            "item_ids": ["title", "search"],
            "bbox": {"x": 0, "y": 108, "w": 800, "h": 32},
            "precise_bbox": {"x": 0, "y": 108, "w": 800, "h": 32},
            "rough_bbox": {"x": 11, "y": 26, "w": 773, "h": 84},
        },
    ]

    merged, events = two_stage._merge_overlapping_same_family_structure_regions(regions)

    assert len(merged) == 1
    assert merged[0]["bbox"] == {"x": 0, "y": 0, "w": 800, "h": 140}
    assert set(merged[0]["item_ids"]) == {"toolbar", "title", "search"}
    assert events[0]["reason"] == "same_family_structure_regions_had_near_identical_geometry"


def test_stage1_partitions_page_topbar_that_contains_browser_chrome_from_y_zero():
    import app.learn.recognition.two_stage as two_stage

    regions = [
        {
            "region_id": "structure_region_browser_chrome",
            "zone_id": "browser_chrome",
            "bbox": {"x": 0, "y": 0, "w": 1216, "h": 56},
            "precise_bbox": {"x": 0, "y": 0, "w": 1216, "h": 56},
            "coordinate_validation": {},
        },
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "bbox": {"x": 0, "y": 0, "w": 1216, "h": 163},
            "precise_bbox": {"x": 0, "y": 0, "w": 1216, "h": 163},
            "coordinate_validation": {},
        },
    ]

    two_stage._partition_nested_page_topbar_below_browser_chrome(regions)

    browser, page_topbar = regions
    assert browser["bbox"] == {"x": 0, "y": 0, "w": 1216, "h": 56}
    assert page_topbar["bbox"] == {"x": 0, "y": 56, "w": 1216, "h": 107}
    assert page_topbar["coordinate_validation"]["browser_chrome_page_header_partition"]["reason"] == (
        "page_topbar_contained_browser_chrome_from_same_top_origin"
    )


def test_stage1_does_not_suppress_precisely_adjacent_top_regions_from_stale_rough_containment():
    import app.learn.recognition.two_stage as two_stage

    regions = [
        {
            "region_id": "structure_region_browser_chrome",
            "zone_id": "browser_chrome",
            "label": "Browser chrome",
            "bbox": {"x": 0, "y": 0, "w": 2521, "h": 122},
            "rough_bbox": {"x": 727, "y": 11, "w": 1094, "h": 111},
        },
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "label": "Top bar",
            "bbox": {"x": 0, "y": 122, "w": 2521, "h": 88},
            "rough_bbox": {"x": 0, "y": 0, "w": 2521, "h": 208},
        },
    ]

    kept, suppressed = two_stage._suppress_contained_duplicate_structure_regions(regions)

    assert [region["region_id"] for region in kept] == [
        "structure_region_browser_chrome",
        "structure_region_top_bar",
    ]
    assert suppressed == []


def test_primary_subpane_evidence_does_not_join_tokens_across_items():
    import app.learn.recognition.two_stage as two_stage

    region = {"item_ids": ["search_value", "result_list"]}
    items_by_id = {
        "search_value": {
            "item_id": "search_value",
            "role": "input",
            "item_type": "text_input",
            "label": "chat",
        },
        "result_list": {
            "item_id": "result_list",
            "role": "listitem",
            "item_type": "actionable",
            "label": "Installed application",
        },
    }

    assert two_stage._primary_subpane_evidence(region, items_by_id=items_by_id) == []


def test_stage1_recovers_left_sidebar_from_owned_vertical_list_container():
    import app.learn.recognition.two_stage as two_stage

    localized_regions = [
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "label": "Top bar",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 100},
            "precise_bbox": {"x": 0, "y": 0, "w": 1200, "h": 100},
            "item_ids": ["window_title"],
        },
        {
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "label": "Main content",
            "bbox": {"x": 0, "y": 100, "w": 1200, "h": 700},
            "precise_bbox": {"x": 0, "y": 100, "w": 1200, "h": 700},
            "item_ids": ["nav_list", "nav_1", "nav_2", "nav_3", "detail_panel"],
        },
    ]
    items_by_id = {
        "nav_list": {
            "item_id": "nav_list",
            "role": "list",
            "item_type": "layout",
            "bbox": {"x": 8, "y": 180, "w": 312, "h": 610},
        },
        **{
            f"nav_{index}": {
                "item_id": f"nav_{index}",
                "role": "listitem",
                "item_type": "actionable",
                "bbox": {"x": 8, "y": 180 + (index - 1) * 48, "w": 312, "h": 48},
            }
            for index in range(1, 4)
        },
        "detail_panel": {
            "item_id": "detail_panel",
            "role": "group",
            "item_type": "layout",
            "bbox": {"x": 350, "y": 120, "w": 820, "h": 600},
        },
    }

    resolved, evidence = two_stage._recover_stage1_left_sidebar_from_list_container(
        localized_regions,
        items_by_id=items_by_id,
        screen_size={"width": 1200, "height": 800},
    )

    regions = {two_stage._stage1_region_family(region): region for region in resolved}
    assert evidence["recovered_region_count"] == 1
    assert regions["left_bar"]["bbox"] == {"x": 0, "y": 100, "w": 320, "h": 700}
    assert regions["main_content"]["bbox"] == {"x": 320, "y": 100, "w": 880, "h": 700}
    assert set(regions["left_bar"]["item_ids"]) == {"nav_list", "nav_1", "nav_2", "nav_3"}
    assert regions["main_content"]["item_ids"] == ["detail_panel"]


def test_semantic_parent_groups_do_not_infer_messages_without_chat_surface_evidence():
    import app.learn.recognition.two_stage as two_stage

    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 320, "y": 100, "w": 880, "h": 700},
    }
    numbered_items = [
        {
            "number": f"3.{index}",
            "item_id": item_id,
            "label": label,
            "role": "text",
            "item_type": "readable",
            "bbox": bbox,
        }
        for index, (item_id, label, bbox) in enumerate(
            (
                ("settings_notice_uia", "Some settings are managed", {"x": 350, "y": 110, "w": 260, "h": 20}),
                ("settings_notice_ocr", "Some settings are managed", {"x": 352, "y": 108, "w": 250, "h": 20}),
                ("install_policy_uia", "Choose where to get apps", {"x": 350, "y": 180, "w": 250, "h": 20}),
                ("install_policy_ocr", "Choose where to get apps", {"x": 352, "y": 182, "w": 245, "h": 20}),
                ("source_value_uia", "Anywhere", {"x": 360, "y": 225, "w": 80, "h": 20}),
                ("source_value_ocr", "Anywhere", {"x": 362, "y": 226, "w": 78, "h": 20}),
                ("search_query", "chat", {"x": 350, "y": 360, "w": 280, "h": 32}),
            ),
            start=1,
        )
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "text_structure_first",
            "allow_chat_semantics": False,
        },
    )

    assert all(group["role"] not in {"message_item", "conversation_row"} for group in groups)


def test_conversation_class_profile_reconstructs_rows_from_generic_main_region() -> None:
    import app.learn.recognition.two_stage as two_stage

    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 140, "w": 267, "h": 714},
    }
    numbered_items = [
        {
            "number": f"2.{index}",
            "item_id": item_id,
            "label": label,
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 54, "y": y, "w": width, "h": 16},
        }
        for index, (item_id, label, y, width) in enumerate(
            (
                ("friend_1", "Friend One", 328, 110),
                ("status_1", "Online", 344, 52),
                ("friend_2", "Friend Two", 371, 112),
                ("status_2", "Online", 388, 52),
                ("friend_3", "Friend Three", 416, 126),
                ("status_3", "Away", 432, 44),
            ),
            start=1,
        )
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "conversation_rows",
            "allow_chat_semantics": True,
        },
    )
    conversation_groups = [group for group in groups if group["role"] == "conversation_row"]

    assert [group["member_item_ids"] for group in conversation_groups] == [
        ["friend_1", "status_1"],
        ["friend_2", "status_2"],
        ["friend_3", "status_3"],
    ]
    assert all(group["role"] != "tile_card_parent" for group in groups)


def test_message_thread_stage1_5_region_does_not_generate_conversation_rows() -> None:
    import app.learn.recognition.two_stage as two_stage

    region = {
        "region_id": "structure_region_main_content__stage1_5__message_thread",
        "label": "Stage1.5 message/detail pane",
        "role": "message_thread",
        "bbox": {"x": 400, "y": 0, "w": 600, "h": 700},
        "input_stage1_5_subregion": {"role": "message_thread"},
    }
    numbered_items = [
        {
            "number": f"2.{index}",
            "item_id": item_id,
            "label": label,
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 520, "y": y, "w": width, "h": 18},
        }
        for index, (item_id, label, y, width) in enumerate(
            (
                ("action_1", "Send document", 320, 120),
                ("status_1", "Ready", 338, 60),
                ("action_2", "Add contact", 375, 110),
                ("status_2", "Ready", 393, 60),
                ("action_3", "Ask assistant", 430, 105),
                ("status_3", "Ready", 448, 60),
            ),
            start=1,
        )
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "conversation_rows",
            "allow_chat_semantics": True,
        },
    )

    assert all(group["role"] != "conversation_row" for group in groups)


def test_conversation_list_builds_one_parent_per_name_status_row() -> None:
    region = {
        "region_id": "structure_region_main_content__stage1_5__conversation_list",
        "label": "Conversation list",
        "bbox": {"x": 0, "y": 80, "w": 420, "h": 520},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "section_heading",
            "label": "Online friends",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 14, "y": 92, "w": 120, "h": 18},
        },
        {
            "number": "1.2",
            "item_id": "broad_visual_container",
            "label": "Friend list container",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 20, "y": 118, "w": 370, "h": 240},
        },
        *[
            {
                "number": f"1.{index + 3}",
                "item_id": item_id,
                "label": label,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 54, "y": y, "w": width, "h": 18},
            }
            for index, (item_id, label, y, width) in enumerate(
                (
                    ("friend_1", "Friend One", 124, 110),
                    ("status_1", "Online", 141, 52),
                    ("friend_2", "Friend Two", 167, 112),
                    ("status_2", "Online", 184, 52),
                    ("friend_3", "Friend Three", 210, 126),
                    ("status_3", "Away", 227, 44),
                    ("friend_4", "Friend Four", 268, 118),
                )
            )
        ],
    ]

    semantic_groups = two_stage._semantic_parent_groups(region=region, numbered_items=numbered_items)
    groups = [group for group in semantic_groups if group.get("role") == "conversation_row"]

    assert [group["member_item_ids"] for group in groups] == [
        ["friend_1", "status_1"],
        ["friend_2", "status_2"],
        ["friend_3", "status_3"],
        ["friend_4"],
    ]
    assert all("broad_visual_container" not in group["member_item_ids"] for group in groups)
    assert all(group.get("role") != "tile_card_parent" for group in semantic_groups)


def test_generic_primary_region_uses_explicit_friends_list_evidence_for_rows() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 80, "y": 100, "w": 720, "h": 700},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "friends_list_window",
            "label": "好友列表",
            "role": "window",
            "item_type": "container",
            "bbox": {"x": 80, "y": 100, "w": 720, "h": 700},
        },
        *[
            {
                "number": f"1.{index + 2}",
                "item_id": item_id,
                "label": label,
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 96, "y": y, "w": width, "h": 18},
            }
            for index, (item_id, label, y, width) in enumerate(
                (
                    ("friend_1", "Friend One", 140, 110),
                    ("status_1", "Online", 157, 52),
                    ("friend_2", "Friend Two", 190, 112),
                    ("status_2", "Away", 207, 44),
                    ("friend_3", "Friend Three", 240, 126),
                    ("status_3", "Online", 257, 52),
                )
            )
        ],
    ]

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=numbered_items)
    conversation_groups = [group for group in groups if group.get("role") == "conversation_row"]

    assert [group["member_item_ids"] for group in conversation_groups] == [
        ["friend_1", "status_1"],
        ["friend_2", "status_2"],
        ["friend_3", "status_3"],
    ]


def test_stage2_dedupes_same_semantic_item_from_uia_and_ocr():
    import app.learn.recognition.two_stage as two_stage

    items = [
        {
            "item_id": "page_text_1_apps_and_features",
            "label": "Apps and features",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 350, "y": 300, "w": 160, "h": 24},
        },
        {
            "item_id": "action_uia_1_apps_and_features",
            "label": "Apps and features",
            "role": "text",
            "item_type": "actionable",
            "bbox": {"x": 348, "y": 298, "w": 164, "h": 26},
        },
        {
            "item_id": "page_text_2_default_apps",
            "label": "Default apps",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 350, "y": 350, "w": 100, "h": 24},
        },
    ]

    deduped, audit = two_stage._dedupe_region_items_by_semantic_overlap(items)

    assert [item["item_id"] for item in deduped] == [
        "action_uia_1_apps_and_features",
        "page_text_2_default_apps",
    ]
    assert deduped[0]["merged_source_item_ids"] == [
        "action_uia_1_apps_and_features",
        "page_text_1_apps_and_features",
    ]
    assert audit["suppressed_duplicate_count"] == 1






def test_two_stage_exposes_stage1_and_fusion_overlay_paths_from_same_run(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "triad_source.png"
    Image.new("RGB", (800, 500), "white").save(image_path)
    inventory = [
        {
            "item_id": "main",
            "label": "Main content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 500},
            "review_only": True,
        }
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": ["main"]}},
        "nodes": {"main": inventory[0]},
    }
    monkeypatch.setattr(two_stage, "_render_stage1_region_localization_overlay", lambda **kwargs: "stage1.png")
    monkeypatch.setattr(two_stage, "_render_two_stage_overlay", lambda **kwargs: "fusion.png")

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 800, "height": 500}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert result["source_image_path"] == str(image_path)
    assert result["stage1_region_localization"]["overlay_path"] == "stage1.png"
    assert result["fusion"]["stage1_structure_overlay_path"] == "stage1.png"
    assert result["fusion"]["compiled_overlay_path"] == "fusion.png"


def test_authoritative_partition_rejects_overlapping_override_instead_of_clamping(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_main_overlap.png"
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 899, 68), fill="#f7f7f7")
    draw.text((120, 22), "top controls", fill="black")
    draw.text((100, 100), "Home", fill="black")
    draw.rectangle((100, 150, 300, 320), fill="#db3030")
    image.save(image_path)

    inventory = [
        {
            "item_id": "top_bar_hint",
            "label": "Top bar coarse hint",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 150},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "top_controls",
            "label": "top controls",
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": 120, "y": 22, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "misassigned_main_title",
            "label": "Home",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 100, "w": 70, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "primary_area",
            "label": "Primary area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 92, "w": 720, "h": 380},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_bar_hint", "top_controls", "misassigned_main_title"]},
            "primary_area": {"item_ids": ["primary_area"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    top = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_top_bar"
    )
    primary = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_primary_area"
    )
    assert top["bbox"] == {"x": 0, "y": 0, "w": 900, "h": 150}
    assert primary["bbox"] == {"x": 90, "y": 92, "w": 720, "h": 380}
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"
    assert result["stage2_numbering_skipped"] is True


def test_stage1_preserves_topbar_and_moves_main_for_shallow_boundary_overlap() -> None:
    regions = [
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 200},
            "precise_bbox": {"x": 0, "y": 0, "w": 1000, "h": 200},
            "rough_bbox": {"x": 0, "y": 0, "w": 1000, "h": 200},
            "coordinate_validation": {},
        },
        {
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "bbox": {"x": 0, "y": 170, "w": 1000, "h": 630},
            "precise_bbox": {"x": 0, "y": 170, "w": 1000, "h": 630},
            "rough_bbox": {"x": 0, "y": 170, "w": 1000, "h": 630},
            "coordinate_validation": {},
        },
    ]

    two_stage._clamp_topbar_against_main_regions(regions)

    top, main = regions
    assert top["bbox"] == {"x": 0, "y": 0, "w": 1000, "h": 200}
    assert main["bbox"] == {"x": 0, "y": 200, "w": 1000, "h": 600}
    assert main["coordinate_validation"]["sibling_partition"]["reason"] == (
        "main_content_must_follow_shallow_overlapping_horizontal_bar"
    )


def test_authoritative_partition_preserves_valid_header_and_main_fixture_geometry(tmp_path):
    from PIL import Image

    image_path = tmp_path / "native_header_children.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "account_name",
            "label": "Account name",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 180, "y": 72, "w": 180, "h": 38},
            "review_only": True,
        },
        {
            "item_id": "account_status",
            "label": "Account status",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 180, "y": 116, "w": 220, "h": 30},
            "review_only": True,
        },
        {
            "item_id": "settings_grid",
            "label": "Settings grid",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 70, "y": 205, "w": 860, "h": 430},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "page_header": {"item_ids": ["account_name", "account_status"]},
            "main_content": {"item_ids": ["settings_grid"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    header = next(region for region in regions if region["region_id"] == "structure_region_page_header")
    main = next(region for region in regions if region["region_id"] == "structure_region_main_content")
    header_bottom = header["bbox"]["y"] + header["bbox"]["h"]
    assert header_bottom == 146
    assert main["bbox"] == {"x": 70, "y": 205, "w": 860, "h": 430}
    assert header["coordinate_validation"]["calibration_strategy"] == "identity_from_validated_root_partition"


def test_stage1_sparse_native_header_discards_unsupported_coarse_tail():
    from app.learn.recognition import two_stage

    region = {
        "region_id": "structure_region_top_bar",
        "zone_id": "top_bar",
        "bbox": {"x": 0, "y": 0, "w": 1000, "h": 180},
        "item_ids": ["coarse_top_bar", "window_title", "menu_row"],
    }
    items_by_id = {
        "coarse_top_bar": {
            "item_id": "coarse_top_bar",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 180},
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        "window_title": {
            "item_id": "window_title",
            "bbox": {"x": 10, "y": 8, "w": 130, "h": 22},
            "role": "text",
        },
        "menu_row": {
            "item_id": "menu_row",
            "bbox": {"x": 12, "y": 34, "w": 260, "h": 22},
            "role": "menu_item",
        },
    }

    result = two_stage._calibrated_stage1_bbox(
        region,
        items_by_id=items_by_id,
        screen_size={"width": 1000, "height": 800},
    )

    assert result["bbox"] == {"x": 0, "y": 0, "w": 1000, "h": 64}
    assert result["strategy"] == "top_bar_sparse_tail_trimmed_to_assigned_children"
    assert result["unsupported_tail_trimmed"] == 116

    localized = two_stage._stage1_region_localization(
        [region],
        items_by_id=items_by_id,
        screen_size={"width": 1000, "height": 800},
    )["regions"][0]
    assert localized["coordinate_validation"]["unsupported_tail_trimmed"] == 116

    duplicate_page_header = {
        **region,
        "region_id": "structure_region_page_header",
        "zone_id": "page_header",
        "bbox": {"x": 10, "y": 8, "w": 980, "h": 50},
        "item_ids": ["window_title", "menu_row"],
    }
    duplicate_result = two_stage._calibrated_stage1_bbox(
        duplicate_page_header,
        items_by_id=items_by_id,
        screen_size={"width": 1000, "height": 800},
    )
    assert duplicate_result["bbox"] == {"x": 0, "y": 0, "w": 1000, "h": 64}


def test_authoritative_partition_rejects_duplicate_main_overlap_without_rewriting_geometry(tmp_path):
    from PIL import Image

    image_path = tmp_path / "native_header_duplicate_main_items.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "header_account",
            "label": "Account",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 180, "y": 112, "w": 180, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "header_status",
            "label": "Account status",
            "role": "nav_text_action",
            "item_type": "nav_text_action",
            "bbox": {"x": 540, "y": 134, "w": 220, "h": 21},
            "review_only": True,
        },
        {
            "item_id": "duplicate_account_status",
            "label": "Account status",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 540, "y": 134, "w": 220, "h": 21},
            "review_only": True,
        },
        {
            "item_id": "settings_search",
            "label": "Find a setting",
            "role": "input",
            "item_type": "input",
            "bbox": {"x": 360, "y": 215, "w": 300, "h": 32},
            "review_only": True,
        },
        {
            "item_id": "settings_grid",
            "label": "Settings grid",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 70, "y": 300, "w": 860, "h": 330},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "page_header": {"item_ids": ["header_account", "header_status"]},
            "main_content": {
                "item_ids": ["duplicate_account_status", "settings_search", "settings_grid"]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    localized = result["stage1_region_localization"]["regions"]
    header = next(region for region in localized if region["region_id"] == "structure_region_page_header")
    main = next(region for region in localized if region["region_id"] == "structure_region_main_content")
    header_bottom = header["bbox"]["y"] + header["bbox"]["h"]
    assert header_bottom == 155
    assert main["bbox"]["y"] == 134
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"
    assert result["stage2_numbering_skipped"] is True


def test_two_stage_required_stage1_gate_blocks_item_numbering_when_stage1_fails(tmp_path):
    from PIL import Image

    image_path = tmp_path / "stage1_gate_main_too_small.png"
    Image.new("RGB", (900, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_bar_hint",
            "label": "Top bar",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 72},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "primary_area",
            "label": "Primary area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 80, "y": 100, "w": 120, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_bar_hint"]},
            "primary_area": {"item_ids": ["primary_area"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_gate"]["required"] is True
    assert result["stage1_gate"]["allow_stage2_numbering"] is False
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"
    assert "main_region_too_small" in result["stage1_gate"]["failure_categories"]
    assert result["stage2_numbering_skipped"] is True
    assert result["stage2_numbering"]["numbered_item_count"] == 0
    assert result["fusion"]["region_content_boundary_summary"]["boundary_contract_status"] == "not_evaluated_stage2_skipped"
    assert result["fusion"]["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert "stage2_numbering_skipped" in result["fusion"]["region_content_boundary_summary"]["promotion_blockers"]




def test_two_stage_overlay_suppresses_browser_chrome_child_item_labels(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "browser_chrome_overlay_suppression.png"
    Image.new("RGB", (600, 180), "white").save(image_path)
    drawn_labels: list[str] = []

    def fake_draw_box(draw, bbox, label, *, color, font, width=1):
        drawn_labels.append(str(label))

    monkeypatch.setattr(two_stage, "_draw_box", fake_draw_box)

    _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=[
            {
                "region_no": 1,
                "region_id": "structure_region_browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
            },
            {
                "region_no": 2,
                "region_id": "structure_region_top_bar",
                "label": "Top/header area",
                "bbox": {"x": 0, "y": 72, "w": 600, "h": 60},
            },
        ],
        numbered_regions=[
            {
                "region_id": "structure_region_browser_chrome",
                "numbered_items": [
                    {
                        "number": "1.0",
                        "label": "https://example.test",
                        "role": "address_bar",
                        "bbox": {"x": 120, "y": 20, "w": 260, "h": 24},
                    },
                    {
                        "number": "1.1",
                        "role": "control",
                        "bbox": {"x": 20, "y": 20, "w": 80, "h": 24},
                    }
                ],
            },
            {
                "region_id": "structure_region_top_bar",
                "numbered_items": [
                    {
                        "number": "2.1",
                        "role": "nav_item",
                        "bbox": {"x": 120, "y": 84, "w": 72, "h": 20},
                    }
                ],
            },
        ],
    )

    assert "S1: Browser chrome" in drawn_labels
    assert "1.1 control" not in drawn_labels
    assert "2.1 nav_item" in drawn_labels


def test_two_stage_overlay_and_fusion_keep_native_toolbar_children(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "native_toolbar_overlay.png"
    Image.new("RGB", (600, 180), "white").save(image_path)
    drawn_labels: list[str] = []

    def fake_draw_box(draw, bbox, label, *, color, font, width=1):
        drawn_labels.append(str(label))

    monkeypatch.setattr(two_stage, "_draw_box", fake_draw_box)
    structure_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_browser_chrome",
            "label": "Legacy top toolbar",
            "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_browser_chrome",
            "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
            "numbered_items": [
                {
                    "item_id": "play_control",
                    "number": "1.1",
                    "label": "Play",
                    "role": "button",
                    "bbox": {"x": 180, "y": 18, "w": 36, "h": 28},
                    "parent_region_id": "structure_region_browser_chrome",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
                }
            ],
            "subregion_groups": [],
        }
    ]

    _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
    )
    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    assert "1.1 button" in drawn_labels
    assert any(
        box.get("box_type") == "numbered_item" and box.get("number") == "1.1"
        for box in fusion["fused_review_boxes"]
    )


def test_two_stage_overlay_and_fusion_publish_atomic_control_parents(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "atomic_control_parent_overlay.png"
    Image.new("RGB", (520, 260), "white").save(image_path)
    drawn: list[tuple[str, tuple[int, int, int]]] = []

    def fake_draw_box(draw, bbox, label, *, color, font, width=1):
        drawn.append((str(label), color))

    monkeypatch.setattr(two_stage, "_draw_box", fake_draw_box)
    structure_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_main",
            "label": "Main",
            "bbox": {"x": 0, "y": 0, "w": 520, "h": 260},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_main",
            "bbox": {"x": 0, "y": 0, "w": 520, "h": 260},
            "numbered_items": [],
            "subregion_groups": [],
            "control_parents": [
                {
                    "object_id": "control_parent_conversation_row_1",
                    "label": "Conversation row",
                    "role": "atomic_control_parent",
                    "bbox": {"x": 42, "y": 70, "w": 210, "h": 46},
                    "member_object_ids": ["avatar_1", "title_1"],
                    "source": "repeated_visual_anchor_with_row_evidence",
                    "review_only": True,
                }
            ],
        }
    ]

    _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
    )
    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    assert ("CP Conversation row", (0, 158, 115)) in drawn
    parent_box = next(
        box
        for box in fusion["fused_review_boxes"]
        if box.get("box_type") == "control_parent"
    )
    assert parent_box["object_id"] == "control_parent_conversation_row_1"
    assert parent_box["member_object_ids"] == ["avatar_1", "title_1"]
    assert parent_box["render_in_main_overlay"] is True
    assert parent_box["display_only"] is True


def test_two_stage_synthesizes_web_list_row_parents_for_date_title_rows(tmp_path):
    image_path = tmp_path / "date_title_rows.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 96), "Latest News", fill="black")
    for y, date, title in (
        (140, "2026-07-02", "Thinking about running for the PSF Board? Let's talk!"),
        (178, "2026-06-29", "Python Packaging Council Inaugural Election Dates"),
    ):
        draw.text((90, y), date, fill="black")
        draw.text((200, y), title, fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": "section_latest_news",
            "label": "Latest News",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 90, "y": 96, "w": 140, "h": 24},
            "review_only": True,
        },
        *[
            {
                "item_id": f"date_{index}",
                "label": date,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                "review_only": True,
            }
            for index, (y, date) in enumerate(
                ((140, "2026-07-02"), (178, "2026-06-29")),
                start=1,
            )
        ],
        *[
            {
                "item_id": f"title_{index}",
                "label": title,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 200, "y": y, "w": w, "h": 20},
                "review_only": True,
            }
            for index, (y, title, w) in enumerate(
                (
                    (140, "Thinking about running for the PSF Board? Let's talk!", 360),
                    (178, "Python Packaging Council Inaugural Election Dates", 330),
                ),
                start=1,
            )
        ],
        {
            "item_id": "below_list_content",
            "label": "Below list content",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 90, "y": 360, "w": 160, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["grouping_strategy"] == "primary_region_homogeneous_grouping_with_visual_card_segmenter"
    )
    list_rows = [group for group in primary["subregion_groups"] if group["role"] == "list_row"]
    list_groups = [group for group in primary["subregion_groups"] if group["role"] == "list_group"]
    section_parents = [group for group in primary["subregion_groups"] if group["role"] == "section_parent"]

    assert len(list_rows) == 2
    assert len(list_groups) == 1
    assert list_groups[0]["child_group_roles"] == ["list_row", "list_row"]
    assert section_parents
    assert "list_group" in section_parents[0]["child_group_roles"]


def test_list_groups_take_precedence_over_inferred_text_tile_cards() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items: list[dict] = []
    for index, y in enumerate((140, 178, 216), start=1):
        items.extend(
            [
                {
                    "number": f"1.{index * 2 - 1}",
                    "item_id": f"metadata_{index}",
                    "label": f"2026-07-{index:02d}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                },
                {
                    "number": f"1.{index * 2}",
                    "item_id": f"title_{index}",
                    "label": f"Entry title {index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 200, "y": y, "w": 150, "h": 20},
                },
            ]
        )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    list_groups = [group for group in groups if group.get("role") == "list_group"]
    assert len(list_groups) == 1
    list_member_ids = set(list_groups[0]["member_item_ids"])
    resolution = two_stage.resolve_group_ownership(groups)
    conflicting_text_tiles = [
        group
        for group in resolution["accepted_groups"]
        if group.get("source") == "stage2_primary_text_tile_card_parent_grouping"
        and list_member_ids.intersection(group.get("member_item_ids", []))
    ]
    assert conflicting_text_tiles == []
    assert resolution["audit"]["rejected_claims"]


def test_dense_aligned_table_rows_take_precedence_over_text_column_cards() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 180, "y": 120, "w": 900, "h": 620},
    }
    items: list[dict] = []
    for row_index, y in enumerate(range(170, 426, 32), start=1):
        for column_index, (x, label) in enumerate(
            (
                (210, f"Item {row_index}"),
                (510, f"2026-07-{row_index:02d}"),
                (690, "Folder"),
                (820, f"{row_index} KB"),
            ),
            start=1,
        ):
            items.append(
                {
                    "number": f"1.{len(items) + 1}",
                    "item_id": f"row_{row_index}_column_{column_index}",
                    "label": label,
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": y, "w": 96, "h": 20},
                }
            )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    table_groups = [group for group in groups if group.get("role") == "table_group"]
    assert len(table_rows) == 8
    assert len(table_groups) == 1
    assert table_groups[0]["child_group_roles"] == ["table_row"] * 8
    table_member_ids = set(table_groups[0]["member_item_ids"])
    assert not [
        group
        for group in groups
        if group.get("role") == "tile_card_parent"
        and table_member_ids.intersection(group.get("member_item_ids", []))
    ]


def test_independent_content_modules_do_not_merge_aligned_card_text_into_table_rows() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 100, "w": 1200, "h": 700},
    }
    items: list[dict] = []
    for row_index, y in enumerate(range(150, 406, 32), start=1):
        for column_index, x in enumerate((80, 360, 640, 920), start=1):
            items.append(
                {
                    "number": f"1.{len(items) + 1}",
                    "item_id": f"module_{column_index}_text_{row_index}",
                    "label": f"Module {column_index} content {row_index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": y, "w": 180, "h": 20},
                }
            )

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "independent_content_modules"},
    )

    assert not [group for group in groups if group.get("role") in {"table_row", "table_group"}]


def test_independent_content_modules_require_visual_evidence_for_tile_card_parents() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 100, "w": 1200, "h": 700},
    }
    items = [
        {
            "number": "1.1",
            "item_id": "visual_card",
            "label": "Weather module",
            "role": "content_card",
            "item_type": "visual",
            "bbox": {"x": 760, "y": 180, "w": 260, "h": 140},
        },
        {
            "number": "1.2",
            "item_id": "weather_title",
            "label": "Weather",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 780, "y": 200, "w": 100, "h": 24},
        },
    ]
    for index, y in enumerate(range(160, 416, 32), start=1):
        items.append(
            {
                "number": f"1.{len(items) + 1}",
                "item_id": f"unboxed_text_{index}",
                "label": f"Unboxed content {index}",
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 80, "y": y, "w": 280, "h": 20},
            }
        )

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "independent_content_modules"},
    )

    tile_groups = [group for group in groups if group.get("role") == "tile_card_parent"]
    assert len(tile_groups) == 1
    assert tile_groups[0]["source"] == "stage2_primary_tile_card_parent_grouping"
    assert tile_groups[0]["member_item_ids"] == ["visual_card", "weather_title"]


def test_independent_content_modules_do_not_merge_orphans_across_peer_columns() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 100, "w": 1200, "h": 700},
    }
    items = [
        {
            "number": f"1.{index}",
            "item_id": f"left_{index}",
            "label": f"Left module {index}",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 80, "y": 160 + index * 30, "w": 180, "h": 20},
        }
        for index in range(1, 5)
    ]
    items.extend(
        {
            "number": f"1.{index + 4}",
            "item_id": f"right_{index}",
            "label": f"Right module {index}",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 760, "y": 160 + index * 30, "w": 180, "h": 20},
        }
        for index in range(1, 5)
    )

    groups = two_stage._ensure_primary_items_have_subregion_parent(
        region=region,
        numbered_items=items,
        groups=[
            {
                "group_id": "seed",
                "role": "review_only",
                "bbox": {"x": 500, "y": 120, "w": 80, "h": 30},
                "member_item_ids": [],
            }
        ],
        class_rule_profile={"primary_content_strategy": "independent_content_modules"},
    )

    orphan_groups = [group for group in groups if group.get("role") == "ungrouped_review_region"]
    assert len(orphan_groups) == 2
    assert {tuple(group["member_item_ids"]) for group in orphan_groups} == {
        ("left_1", "left_2", "left_3", "left_4"),
        ("right_1", "right_2", "right_3", "right_4"),
    }
    assert all(group["bbox"]["w"] < 240 for group in orphan_groups)


def test_sparse_aligned_table_rows_use_shared_column_anchors_instead_of_vertical_cards() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 140, "w": 1162, "h": 851},
    }
    columns = (32, 398, 446, 514, 589, 690, 731, 932, 1030)
    items: list[dict] = []
    for row_index, y in enumerate(range(176, 456, 28), start=1):
        missing_columns = {2} if row_index % 3 == 0 else ({5, 7} if row_index % 4 == 0 else set())
        for column_index, x in enumerate(columns):
            if column_index in missing_columns:
                continue
            items.append(
                {
                    "number": f"2.{len(items) + 1}",
                    "item_id": f"sparse_row_{row_index}_column_{column_index}",
                    "label": f"value {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "readable",
                    "bbox": {
                        "x": x + (row_index % 2),
                        "y": y + (column_index % 3),
                        "w": 46 if column_index else 150,
                        "h": 17 + (column_index % 2),
                    },
                }
            )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    table_group = next(group for group in groups if group.get("role") == "table_group")
    table_rows = [group for group in groups if group.get("role") == "table_row"]
    table_member_ids = set(table_group["member_item_ids"])

    assert len(table_rows) == 10
    assert all(row["bbox"]["x"] <= 33 for row in table_rows)
    assert all(row["bbox"]["x"] + row["bbox"]["w"] >= 1076 for row in table_rows)
    assert not [
        group
        for group in groups
        if group.get("role") == "tile_card_parent"
        and table_member_ids.intersection(group.get("member_item_ids", []))
    ]


def test_dense_table_keeps_rows_with_indented_first_column() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 160, "y": 120, "w": 2420, "h": 620},
    }
    items: list[dict] = []
    for row_index, y in enumerate(range(170, 458, 24), start=1):
        name_x = 208 if row_index in {2, 5, 9} else 191
        for column_index, (x, label) in enumerate(
            (
                (name_x, f"Folder {row_index}"),
                (451, f"2026-07-{row_index:02d}"),
                (593, "Folder"),
            ),
            start=1,
        ):
            items.append(
                {
                    "number": f"2.{len(items) + 1}",
                    "item_id": f"indented_row_{row_index}_column_{column_index}",
                    "label": label,
                    "role": "text",
                    "item_type": "readable",
                    "bbox": {
                        "x": x,
                        "y": y,
                        "w": 60 if column_index == 1 else (105 if column_index == 2 else 48),
                        "h": 20,
                    },
                }
            )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    assert len(table_rows) == 12
    assert {
        f"indented_row_{row_index}_column_1" for row_index in {2, 5, 9}
    }.issubset(
        {
            item_id
            for group in table_rows
            for item_id in group.get("member_item_ids", [])
        }
    )


def test_dense_table_keeps_rhythmic_row_with_one_missing_shared_column() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 160, "y": 120, "w": 760, "h": 760},
    }
    items: list[dict] = []
    for row_index, y in enumerate(range(170, 842, 24), start=1):
        columns = [
            (191, f"Item {row_index}"),
            (451, f"2026-07-{row_index:02d}"),
            (593, "Folder" if row_index <= 18 else "Text document"),
        ]
        if row_index > 18:
            columns.append((752, f"{row_index} KB"))
        if row_index == 23:
            columns = [column for column in columns if column[0] != 593]
        for column_index, (x, label) in enumerate(columns, start=1):
            items.append(
                {
                    "number": f"2.{len(items) + 1}",
                    "item_id": f"missing_cell_row_{row_index}_column_{column_index}",
                    "label": label,
                    "role": "text",
                    "item_type": "readable",
                    "bbox": {"x": x, "y": y, "w": 92, "h": 20},
                }
            )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    assert len(table_rows) == 28
    recovered_row = next(
        group
        for group in table_rows
        if any(item_id.startswith("missing_cell_row_23_") for item_id in group.get("member_item_ids", []))
    )
    assert len(recovered_row["member_item_ids"]) == 3


def test_dense_table_keeps_bottom_edge_partial_cells_as_a_partial_table_row() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 140, "w": 1162, "h": 851},
    }
    columns = (32, 398, 446, 514, 589, 690, 731, 932, 1030)
    items: list[dict] = []
    for row_index, y in enumerate(range(176, 400, 28), start=1):
        for column_index, x in enumerate(columns):
            items.append(
                {
                    "number": f"2.{len(items) + 1}",
                    "item_id": f"full_row_{row_index}_column_{column_index}",
                    "label": f"value {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "readable",
                    "bbox": {"x": x, "y": y, "w": 46 if column_index else 150, "h": 18},
                }
            )
    for column_index, x in enumerate((55, 409, 459, 598, 701, 930, 1030), start=1):
        items.append(
            {
                "number": f"2.{len(items) + 1}",
                "item_id": f"partial_row_column_{column_index}",
                "label": f"partial {column_index}",
                "role": "partial_visible_card",
                "bbox": {"x": x, "y": 404 + (column_index % 2), "w": 45, "h": 17},
                "partial_visible": True,
                "children": [],
            }
        )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    partial_row = next(group for group in table_rows if group.get("partial_visible") is True)

    assert len(table_rows) == 9
    assert partial_row["source"] == "stage2_dense_aligned_table_partial_row_synthesis"
    assert partial_row["bbox"]["x"] <= 33
    assert partial_row["bbox"]["x"] + partial_row["bbox"]["w"] >= 1076


def test_explicit_datagrid_with_narrow_columns_keeps_rows_instead_of_vertical_cards() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 94, "w": 1162, "h": 953},
    }
    items: list[dict] = [
        {
            "number": "2.1",
            "item_id": "process_grid",
            "label": "process table",
            "role": "datagrid",
            "item_type": "action_uia",
            "bbox": {"x": 9, "y": 135, "w": 1145, "h": 855},
        },
        {
            "number": "2.2",
            "item_id": "false_card_fragment",
            "label": "process group",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 15, "y": 187, "w": 185, "h": 87},
        },
        {
            "number": "2.3",
            "item_id": "row_action_cell",
            "label": "very low",
            "role": "input",
            "item_type": "action_uia",
            "bbox": {"x": 1030, "y": 176, "w": 45, "h": 21},
        },
    ]
    columns = ((32, 120), (398, 34), (446, 58), (513, 66), (589, 64), (691, 34), (731, 72), (930, 46))
    for row_index, y in enumerate(range(176, 456, 28), start=1):
        for column_index, (x, width) in enumerate(columns, start=1):
            items.append(
                {
                    "number": f"2.{len(items) + 1}",
                    "item_id": f"process_{row_index}_column_{column_index}",
                    "label": f"value {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": y, "w": width, "h": 20},
                }
            )

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "row_table_first"},
    )

    table_group = next(group for group in groups if group.get("role") == "table_group")
    table_rows = [group for group in groups if group.get("role") == "table_row"]
    table_member_ids = set(table_group["member_item_ids"])

    assert table_group["bbox"] == {"x": 9, "y": 135, "w": 1145, "h": 855}
    assert "process_grid" in table_member_ids
    assert {"false_card_fragment", "row_action_cell"}.issubset(table_member_ids)
    assert len(table_rows) == 10
    assert all(row["bbox"]["x"] == 9 and row["bbox"]["w"] == 1145 for row in table_rows)
    memberships = two_stage._group_membership_for_region(
        {"numbered_items": items, "subregion_groups": groups}
    )
    assert all(
        two_stage._item_display_hierarchy(
            next(item for item in items if item["item_id"] == item_id),
            memberships[item_id],
        )["render_in_main_overlay"]
        is False
        for item_id in ("process_grid", "false_card_fragment", "row_action_cell")
    )
    assert not [
        group
        for group in groups
        if group.get("role") == "tile_card_parent"
        and table_member_ids.intersection(group.get("member_item_ids", []))
    ]


def test_explicit_datagrid_completes_visually_evidenced_rows_after_text_evidence_ends(tmp_path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "datagrid_visual_rows.png"
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    row_centers = [150 + index * 28 for index in range(10)]
    for center_y in row_centers:
        for x, width in ((40, 180), (330, 45), (405, 70), (610, 90)):
            draw.rectangle((x, center_y - 4, x + width, center_y + 4), fill="#202020")
    image.save(image_path)

    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 90, "w": 900, "h": 420},
    }
    items: list[dict] = [
        {
            "number": "1.1",
            "item_id": "process_grid",
            "label": "process table",
            "role": "datagrid",
            "item_type": "action_uia",
            "bbox": {"x": 10, "y": 110, "w": 880, "h": 390},
        }
    ]
    for row_index, center_y in enumerate(row_centers[:6], start=1):
        for column_index, (x, width) in enumerate(((40, 180), (330, 45), (405, 70), (610, 90)), start=1):
            items.append(
                {
                    "number": f"1.{len(items) + 1}",
                    "item_id": f"row_{row_index}_column_{column_index}",
                    "label": f"value {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": center_y - 9, "w": width, "h": 18},
                }
            )

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "row_table_first"},
        image_path=str(image_path),
    )

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    visual_rows = [
        group
        for group in table_rows
        if group.get("source") == "stage2_datagrid_visual_row_completion"
    ]
    assert len(table_rows) == 10
    assert len(visual_rows) == 4
    assert [row["bbox"]["y"] + row["bbox"]["h"] // 2 for row in visual_rows] == row_centers[6:]
    assert all(row["visual_evidence"]["passed"] is True for row in visual_rows)
    assert all(row["member_item_ids"] == [] for row in visual_rows)


def test_explicit_datagrid_does_not_complete_rows_without_visual_evidence(tmp_path) -> None:
    from PIL import Image, ImageDraw

    image_path = tmp_path / "datagrid_blank_tail.png"
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    row_centers = [150 + index * 28 for index in range(10)]
    for center_y in row_centers[:6]:
        for x, width in ((40, 180), (330, 45), (405, 70), (610, 90)):
            draw.rectangle((x, center_y - 4, x + width, center_y + 4), fill="#202020")
    image.save(image_path)

    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 90, "w": 900, "h": 420},
    }
    items: list[dict] = [
        {
            "number": "1.1",
            "item_id": "process_grid",
            "label": "process table",
            "role": "datagrid",
            "item_type": "action_uia",
            "bbox": {"x": 10, "y": 110, "w": 880, "h": 390},
        }
    ]
    for row_index, center_y in enumerate(row_centers[:6], start=1):
        for column_index, (x, width) in enumerate(((40, 180), (330, 45), (405, 70), (610, 90)), start=1):
            items.append(
                {
                    "number": f"1.{len(items) + 1}",
                    "item_id": f"row_{row_index}_column_{column_index}",
                    "label": f"value {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": center_y - 9, "w": width, "h": 18},
                }
            )

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=items,
        class_rule_profile={"primary_content_strategy": "row_table_first"},
        image_path=str(image_path),
    )

    table_rows = [group for group in groups if group.get("role") == "table_row"]
    assert len(table_rows) == 6
    assert not [
        group
        for group in table_rows
        if group.get("source") == "stage2_datagrid_visual_row_completion"
    ]


def test_dense_table_overlay_renders_rows_without_repeating_cell_text() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 180, "y": 120, "w": 900, "h": 620},
    }
    items: list[dict] = []
    for row_index, y in enumerate(range(170, 426, 32), start=1):
        for column_index, x in enumerate((210, 510, 690, 820), start=1):
            items.append(
                {
                    "number": f"1.{len(items) + 1}",
                    "item_id": f"row_{row_index}_column_{column_index}",
                    "label": f"cell {row_index}-{column_index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": x, "y": y, "w": 96, "h": 20},
                }
            )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)
    table_group = next(group for group in groups if group.get("role") == "table_group")
    table_rows = [group for group in groups if group.get("role") == "table_row"]
    memberships = two_stage._group_membership_for_region(
        {"numbered_items": items, "subregion_groups": groups}
    )

    assert two_stage._group_display_hierarchy(table_group)["render_in_main_overlay"] is False
    assert all(two_stage._group_display_hierarchy(row)["render_in_main_overlay"] is True for row in table_rows)
    assert all(
        two_stage._item_display_hierarchy(item, memberships[item["item_id"]])["render_in_main_overlay"] is False
        for item in items
    )


def test_two_stage_synthesizes_hero_code_and_text_panels(tmp_path):
    image_path = tmp_path / "hero_code_text_panels.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1100, 620), "#1f4b6d")
    draw = ImageDraw.Draw(image)
    for y, text in (
        (180, ">>> name = input('What is your name?')"),
        (214, ">>> print('Hi ' + name + '.')"),
        (248, "Hi Python."),
    ):
        draw.text((180, y), text, fill="white")
    draw.text((610, 178), "Quick & Easy to Learn", fill="yellow")
    draw.text((610, 218), "Experienced programmers in any other language can pick up Python quickly.", fill="white")
    draw.text((610, 258), "Learn More", fill="yellow")
    draw.text((180, 460), "Below hero content", fill="white")
    image.save(image_path)

    inventory = [
        *[
            {
                "item_id": f"code_{index}",
                "label": label,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 180, "y": y, "w": w, "h": 24},
                "review_only": True,
            }
            for index, (y, label, w) in enumerate(
                (
                    (180, ">>> name = input('What is your name?')", 330),
                    (214, ">>> print('Hi ' + name + '.')", 260),
                    (248, "Hi Python.", 86),
                ),
                start=1,
            )
        ],
        {
            "item_id": "hero_heading",
            "label": "Quick & Easy to Learn",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 610, "y": 178, "w": 210, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "hero_paragraph",
            "label": "Experienced programmers in any other language can pick up Python quickly.",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 610, "y": 218, "w": 430, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "hero_cta",
            "label": "Learn More",
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": 610, "y": 258, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "below_hero",
            "label": "Below hero content",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 180, "y": 460, "w": 160, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1100, "height": 620}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["grouping_strategy"] == "primary_region_homogeneous_grouping_with_visual_card_segmenter"
    )
    roles = {group["role"]: group for group in primary["subregion_groups"]}
    assert roles["hero_code_panel"]["member_item_ids"] == ["code_1", "code_2", "code_3"]
    assert roles["hero_text_panel"]["member_item_ids"] == ["hero_heading", "hero_paragraph", "hero_cta"]
    assert roles["hero_panel"]["child_group_roles"] == ["hero_code_panel", "hero_text_panel"]


def test_two_stage_expands_sparse_sidebar_visual_fragments_to_hit_area_items(tmp_path):
    image_path = tmp_path / "sparse_sidebar_controls.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (360, 420), "white")
    draw = ImageDraw.Draw(image)
    for y in (42, 92, 142, 192, 242, 292):
        draw.rectangle((18, y, 32, y + 14), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": "left_nav_region_hint",
            "label": "Left nav",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 72, "h": 360},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "left_nav"},
        },
        {
            "item_id": "left_nav_sparse_text",
            "label": "Nav",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 14, "y": 8, "w": 22, "h": 16},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"left_nav": {"item_ids": ["left_nav_region_hint", "left_nav_sparse_text"]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 360, "height": 420}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    assert left_nav["visual_small_control_refinement"]["applied"] is True
    assert left_nav["visual_small_control_refinement"]["sidebar_item_grouping"]["applied"] is True
    assert left_nav["numbered_item_count"] >= 6
    assert {item["role"] for item in left_nav["numbered_items"]} == {"nav_item"}
    assert all(item["bbox"]["w"] >= left_nav["bbox"]["w"] * 0.55 for item in left_nav["numbered_items"])
    assert all(
        item.get("bbox_refinement", {}).get("source") == "sidebar_item_hit_area_normalizer"
        for item in left_nav["numbered_items"]
    )


def test_two_stage_sidebar_blank_fragments_do_not_promote_to_nav_items(tmp_path):
    image_path = tmp_path / "blank_sidebar.png"
    from PIL import Image

    Image.new("RGB", (280, 320), (246, 246, 246)).save(image_path)
    inventory = [
        {
            "item_id": "left_nav_region_hint",
            "label": "Left nav",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "left_nav"},
        },
        {
            "item_id": "blank_fragment",
            "label": "Maybe button",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 150, "w": 22, "h": 23},
            "review_only": True,
        },
        {
            "item_id": "blank_fragment_2",
            "label": "Maybe button 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 210, "w": 22, "h": 23},
            "review_only": True,
        },
        {
            "item_id": "blank_fragment_3",
            "label": "Maybe button 3",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 260, "w": 22, "h": 23},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"left_nav": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 280, "height": 320}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    roles = {item["role"] for item in left_nav["numbered_items"]}
    assert roles == {"sidebar_review_region"}
    assert left_nav["numbered_item_count"] == 1
    assert left_nav["visual_small_control_refinement"]["sidebar_item_grouping"]["merged_review_region_count"] == 2
    assert left_nav["numbered_items"][0]["bbox"]["w"] < left_nav["bbox"]["w"] * 0.55
    assert left_nav["numbered_items"][0]["overlay_style"] == {
        "tone": "background_review_region",
        "label_policy": "review_only_badge",
        "stroke": "muted_dashed",
        "display_layer": "review_background",
        "number_policy": "hide_stage_number",
        "action_candidate_visual_weight": "low",
    }
    assert left_nav["numbered_items"][0].get("bbox_refinement", {}).get("reason") == (
        "merge_consecutive_sidebar_review_regions_without_visual_evidence"
    )
    fused = [
        item
        for item in result["fusion"]["fused_review_boxes"]
        if item.get("role") == "sidebar_review_region"
    ]
    assert fused
    assert fused[0]["overlay_style"]["tone"] == "background_review_region"
    assert fused[0]["overlay_style"]["display_layer"] == "review_background"
    assert fused[0]["overlay_style"]["number_policy"] == "hide_stage_number"


def test_sidebar_review_regions_with_semantic_labels_are_merged() -> None:
    items = [
        {
            "item_id": f"vision_region_{index}",
            "label": "Play",
            "role": "sidebar_review_region",
            "item_type": "actionable",
            "source": "sidebar_item_evidence_filter",
            "bbox": {"x": 16, "y": 342 + index * 50, "w": 20, "h": 20},
            "review_only": True,
        }
        for index in range(3)
    ]

    merged, merged_count = two_stage._merge_sidebar_review_regions(items)

    assert merged_count == 2
    assert len(merged) == 1
    assert merged[0]["role"] == "sidebar_review_region"
    assert merged[0]["label"] == "sidebar background / empty review region"
    assert merged[0]["bbox_refinement"]["reason"] == (
        "merge_consecutive_sidebar_review_regions_without_visual_evidence"
    )


def test_two_stage_synthesizes_primary_media_card_parents_from_visual_rows(tmp_path):
    image_path = tmp_path / "media_cards.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 240), fill=(220, 30, 30))
    draw.rectangle((250, 100, 370, 240), fill=(20, 140, 220))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 300, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "card_1_text",
            "label": "Card One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 248, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_2_text",
            "label": "Card Two",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 258, "y": 248, "w": 90, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 360}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert main["visual_small_control_refinement"]["media_card_synthesis"]["applied"] is True
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert len(cards) == 2
    assert all(card["children"] for card in cards)


def test_two_stage_groups_each_primary_tile_card_with_internal_text(tmp_path):
    image_path = tmp_path / "settings_tiles.png"
    from PIL import Image

    Image.new("RGB", (760, 420), "white").save(image_path)
    inventory = [
        {
            "item_id": "tile_a",
            "label": "System tile",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 120, "w": 220, "h": 88},
            "review_only": True,
        },
        {
            "item_id": "tile_a_title",
            "label": "System",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 154, "y": 138, "w": 70, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_a_subtitle",
            "label": "Display, sound, notifications",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 154, "y": 166, "w": 170, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_b",
            "label": "Network tile",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 380, "y": 120, "w": 220, "h": 88},
            "review_only": True,
        },
        {
            "item_id": "tile_b_title",
            "label": "Network",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 414, "y": 138, "w": 82, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_b_subtitle",
            "label": "Wi-Fi, airplane mode, VPN",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 414, "y": 166, "w": 164, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 420}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if any(item["item_id"] == "tile_a" for item in region["numbered_items"])
    )
    tile_groups = [group for group in primary["subregion_groups"] if group["role"] == "tile_card_parent"]
    assert len(tile_groups) == 2
    by_card = {next(item_id for item_id in group["member_item_ids"] if item_id.startswith("tile_") and item_id in {"tile_a", "tile_b"}): group for group in tile_groups}
    assert set(by_card["tile_a"]["member_item_ids"]) == {"tile_a", "tile_a_title", "tile_a_subtitle"}
    assert set(by_card["tile_b"]["member_item_ids"]) == {"tile_b", "tile_b_title", "tile_b_subtitle"}
    assert by_card["tile_a"]["bbox"] == {"x": 120, "y": 120, "w": 220, "h": 88}
    assert by_card["tile_b"]["bbox"] == {"x": 380, "y": 120, "w": 220, "h": 88}
    assert by_card["tile_a"]["bbox"]["x"] + by_card["tile_a"]["bbox"]["w"] < by_card["tile_b"]["bbox"]["x"]
    assert all(group["execute_binding_enabled"] is False for group in tile_groups)


def test_two_stage_groups_text_only_settings_tiles_without_visible_card_bbox(tmp_path):
    inventory = [
        {
            "number": "3.1",
            "item_id": "device_title",
            "label": "设备",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 411, "y": 313, "w": 33, "h": 19},
            "review_only": True,
        },
        {
            "number": "3.2",
            "item_id": "device_icon",
            "label": "device icon",
            "role": "icon",
            "item_type": "review_only",
            "bbox": {"x": 370, "y": 314, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.3",
            "item_id": "device_subtitle",
            "label": "蓝牙、打印机、鼠标",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 409, "y": 330, "w": 116, "h": 22},
            "review_only": True,
        },
        {
            "number": "3.4",
            "item_id": "apps_title",
            "label": "应用",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 411, "y": 418, "w": 33, "h": 19},
            "review_only": True,
        },
        {
            "number": "3.5",
            "item_id": "apps_icon",
            "label": "apps icon",
            "role": "icon",
            "item_type": "review_only",
            "bbox": {"x": 370, "y": 419, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.6",
            "item_id": "apps_subtitle",
            "label": "卸载、默认值",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 409, "y": 434, "w": 79, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.7",
            "item_id": "settings_search",
            "label": "查找设置",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 452, "y": 222, "w": 57, "h": 18},
            "review_only": True,
        },
    ]
    groups = two_stage._tile_card_parent_groups(
        region={"region_id": "structure_region_primary_area", "label": "Primary Area", "bbox": {"x": 0, "y": 0, "w": 760, "h": 520}},
        numbered_items=inventory,
    )
    tile_groups = [
        group
        for group in groups
        if group["role"] == "tile_card_parent" and group["source"] == "stage2_primary_text_tile_card_parent_grouping"
    ]

    assert len(tile_groups) == 2
    by_title = {group["member_item_ids"][0]: group for group in tile_groups}
    assert by_title["device_title"]["member_item_ids"] == ["device_title", "device_subtitle"]
    assert by_title["apps_title"]["member_item_ids"] == ["apps_title", "apps_subtitle"]
    assert by_title["device_title"]["bbox"]["x"] <= 393
    assert by_title["device_title"]["bbox"]["w"] >= 150
    assert by_title["device_title"]["bbox"]["h"] >= 64
    assert all(group["execute_binding_enabled"] is False for group in tile_groups)
    assert all(group["artifact_is_authorization"] is False for group in tile_groups)


def test_settings_class_parent_includes_leading_visual_gutter_and_icon() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "label": "Primary Area",
        "bbox": {"x": 80, "y": 240, "w": 760, "h": 360},
    }
    numbered_items = [
        {
            "number": "1.1",
            "item_id": "system_icon",
            "label": "system icon",
            "role": "icon",
            "item_type": "review_only",
            "bbox": {"x": 112, "y": 296, "w": 30, "h": 30},
        },
        {
            "number": "1.2",
            "item_id": "system_title",
            "label": "System",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 294, "w": 62, "h": 20},
        },
        {
            "number": "1.3",
            "item_id": "system_subtitle",
            "label": "Display, sound, notifications, power",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 160, "y": 316, "w": 230, "h": 20},
        },
        {
            "number": "1.4",
            "item_id": "devices_title",
            "label": "Devices",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 430, "y": 294, "w": 72, "h": 20},
        },
        {
            "number": "1.5",
            "item_id": "devices_subtitle",
            "label": "Bluetooth, printers, mouse",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 430, "y": 316, "w": 190, "h": 20},
        },
    ]

    groups = two_stage._semantic_parent_groups(
        region=region,
        numbered_items=numbered_items,
        class_rule_profile={
            "primary_content_strategy": "independent_control_cards",
            "allow_chat_semantics": False,
        },
    )

    tile_groups = [group for group in groups if group.get("role") == "tile_card_parent"]
    system_group = next(group for group in tile_groups if "system_title" in group.get("member_item_ids", []))
    devices_group = next(group for group in tile_groups if "devices_title" in group.get("member_item_ids", []))
    assert "system_icon" in system_group["member_item_ids"]
    assert system_group["bbox"]["x"] <= 112
    assert devices_group["bbox"]["x"] <= 382
    assert system_group["leading_visual_gutter"]["source"] == "class_repeated_layout_inference"
    assert devices_group["leading_visual_gutter"]["source"] == "class_repeated_layout_inference"


def test_two_stage_groups_repeated_text_tiles_when_uia_reports_text_as_buttons() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "label": "Primary Area",
        "bbox": {"x": 0, "y": 180, "w": 1200, "h": 750},
    }
    items = []
    for index, (x, y, title, subtitle) in enumerate(
        (
            (140, 310, "System", "Display, sound, notifications, power"),
            (410, 310, "Devices", "Bluetooth, printers, mouse"),
            (680, 310, "Mobile devices", "Connect Android devices and iPhone"),
            (950, 310, "Network and Internet", "Wi-Fi, airplane mode, VPN"),
            (140, 418, "Personalization", "Background, lock screen, colors"),
            (410, 418, "Apps", "Uninstall, defaults"),
            (680, 418, "Accounts", "Email, sync, work, family"),
            (950, 418, "Time and language", "Speech, region, date"),
        ),
        start=1,
    ):
        items.extend(
            (
                {
                    "number": f"3.{index}.1",
                    "item_id": f"tile_{index}_title",
                    "label": title,
                    "role": "button",
                    "item_type": "action_uia",
                    "bbox": {"x": x, "y": y, "w": 150, "h": 20},
                },
                {
                    "number": f"3.{index}.2",
                    "item_id": f"tile_{index}_subtitle",
                    "label": subtitle,
                    "role": "button",
                    "item_type": "action_uia",
                    "bbox": {"x": x, "y": y + 22, "w": 170, "h": 18},
                },
            )
        )
    items.extend(
        (
            {
                "number": "3.9.1",
                "item_id": "tile_1_title_ocr_duplicate",
                "label": "System",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 142, "y": 311, "w": 145, "h": 19},
            },
            {
                "number": "3.9.2",
                "item_id": "tile_1_subtitle_ocr_duplicate",
                "label": "Display, sound, notifications, power",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": 142, "y": 333, "w": 168, "h": 18},
            },
        )
    )

    groups = two_stage._tile_card_parent_groups(region=region, numbered_items=items)
    tile_groups = [
        group
        for group in groups
        if group.get("source") == "stage2_primary_text_tile_card_parent_grouping"
    ]

    assert len(tile_groups) == 8
    assert {group["member_item_ids"][0] for group in tile_groups} == {
        f"tile_{index}_title" for index in range(1, 9)
    }
    system_group = next(group for group in tile_groups if group["member_item_ids"][0] == "tile_1_title")
    assert set(system_group["member_item_ids"]) == {
        "tile_1_title",
        "tile_1_subtitle",
        "tile_1_title_ocr_duplicate",
        "tile_1_subtitle_ocr_duplicate",
    }
    assert all(len(group["member_item_ids"]) >= 2 for group in tile_groups)
    assert all(group["execute_binding_enabled"] is False for group in tile_groups)


def test_section_parent_does_not_reuse_text_tile_child_as_section_title() -> None:
    numbered_items = [
        {
            "number": "3.1",
            "item_id": "apps_title",
            "label": "应用",
            "role": "text",
            "bbox": {"x": 411, "y": 418, "w": 33, "h": 19},
        },
        {
            "number": "3.2",
            "item_id": "apps_subtitle",
            "label": "卸载、默认值",
            "role": "text",
            "bbox": {"x": 409, "y": 434, "w": 79, "h": 24},
        },
        {
            "number": "3.3",
            "item_id": "card_a",
            "label": "Card A",
            "role": "card",
            "bbox": {"x": 410, "y": 506, "w": 180, "h": 72},
        },
        {
            "number": "3.4",
            "item_id": "card_b",
            "label": "Card B",
            "role": "card",
            "bbox": {"x": 610, "y": 506, "w": 180, "h": 72},
        },
    ]
    content_groups = [
        {
            "group_id": "apps_tile",
            "role": "tile_card_parent",
            "member_item_ids": ["apps_title", "apps_subtitle"],
            "member_numbers": ["3.1", "3.2"],
            "bbox": {"x": 393, "y": 400, "w": 186, "h": 73},
        },
        {
            "group_id": "tile_row",
            "role": "tile_card_group",
            "member_item_ids": ["card_a", "card_b"],
            "member_numbers": ["3.3", "3.4"],
            "bbox": {"x": 410, "y": 506, "w": 380, "h": 72},
        },
    ]

    parents = two_stage._section_parent_groups(
        numbered_items=numbered_items,
        content_groups=content_groups,
    )

    assert parents == []


def test_two_stage_binds_section_title_to_following_card_group(tmp_path):
    image_path = tmp_path / "section_cards.png"
    from PIL import Image

    Image.new("RGB", (720, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "Recommended for you",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 120, "w": 180, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_a",
            "label": "First card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 170, "w": 180, "h": 180},
            "review_only": True,
        },
        {
            "item_id": "card_b",
            "label": "Second card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 330, "y": 170, "w": 180, "h": 180},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if any(item["item_id"] == "section_title" for item in region["numbered_items"])
    )
    groups_by_role = {group["role"]: group for group in primary["subregion_groups"]}
    assert "tile_card_group" in groups_by_role
    assert "section_parent" in groups_by_role
    section = groups_by_role["section_parent"]
    assert section["title_item_id"] == "section_title"
    assert section["child_group_ids"] == [groups_by_role["tile_card_group"]["group_id"]]
    assert section["parent_child_policy"] == "section_title_binds_to_following_card_or_list_group"
    assert section["bbox"]["y"] <= inventory[0]["bbox"]["y"]
    assert section["bbox"]["h"] > groups_by_role["tile_card_group"]["bbox"]["h"]
    fused_sections = [
        item
        for item in result["fusion"]["fused_review_boxes"]
        if item.get("role") == "section_parent"
    ]
    assert fused_sections


def test_primary_card_row_uses_visual_media_evidence_with_scaffolding_items() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 500},
    }
    items = [
        {
            "item_id": "row_scaffold",
            "number": "1.1",
            "label": "Recommendations",
            "role": "listitem",
            "item_type": "actionable",
            "source": "structure_region_item",
            "bbox": {"x": 80, "y": 100, "w": 720, "h": 240},
        },
        {
            "item_id": "media_a",
            "number": "1.2",
            "label": "Album A",
            "role": "media_card",
            "source": "visual_card_segmenter",
            "bbox": {"x": 100, "y": 120, "w": 220, "h": 200},
        },
        {
            "item_id": "media_b",
            "number": "1.3",
            "label": "Album B",
            "role": "media_card",
            "source": "visual_card_segmenter",
            "bbox": {"x": 350, "y": 120, "w": 220, "h": 200},
        },
    ]

    groups = two_stage._primary_content_subregion_groups(region=region, numbered_items=items)

    media_group = next(group for group in groups if group.get("role") == "media_card_group")
    assert {"media_a", "media_b"} <= set(media_group["member_item_ids"])
    assert media_group["expected_item_role"] == "media_card"


def test_card_row_semantic_kind_prefers_two_trusted_visual_media_cards() -> None:
    row = [
        {"role": "listitem", "source": "structure_region_item"},
        {"role": "group", "source": "structure_region_item"},
        {"role": "media_card", "source": "visual_card_segmenter"},
        {"role": "media_card", "source": "visual_card_segmenter"},
        {"role": "text", "source": "structure_region_item"},
    ]

    assert two_stage._card_row_semantic_kind(row) == "media_card"
    assert two_stage._card_row_semantic_kind(row[:2]) == "tile_card"


def test_media_card_bbox_prefers_containing_actionable_parent_over_oversized_visual_box() -> None:
    bbox = two_stage._media_card_bbox_with_children(
        {"x": 301, "y": 614, "w": 186, "h": 300},
        [
            {
                "item_id": "favorite_card",
                "label": "Favorite songs",
                "role": "listitem",
                "item_type": "actionable",
                "bbox": {"x": 299, "y": 610, "w": 194, "h": 260},
            },
            {
                "item_id": "favorite_title",
                "label": "Favorite songs",
                "role": "text",
                "bbox": {"x": 303, "y": 806, "w": 160, "h": 16},
            },
            {
                "item_id": "favorite_metadata",
                "label": "text",
                "role": "text",
                "bbox": {"x": 303, "y": 822, "w": 186, "h": 16},
            },
        ],
        parent_bbox={"x": 97, "y": 95, "w": 1057, "h": 910},
    )

    assert bbox == {"x": 299, "y": 610, "w": 194, "h": 260}


def test_landscape_media_card_accepts_adjacent_title_and_metadata_as_children() -> None:
    card_boxes = [
        {
            "x": 100,
            "y": 120,
            "w": 420,
            "h": 180,
            "visual_bbox": {"x": 100, "y": 120, "w": 420, "h": 180},
        }
    ]
    title = {
        "item_id": "video_title",
        "label": "Getting Started with a product",
        "role": "text",
        "item_type": "readable",
        "bbox": {"x": 536, "y": 126, "w": 430, "h": 28},
    }
    metadata = {
        "item_id": "video_metadata",
        "label": "137k views · 2 years ago",
        "role": "text",
        "item_type": "readable",
        "bbox": {"x": 536, "y": 160, "w": 210, "h": 24},
    }

    assert two_stage._best_media_card_child_index(title, card_boxes) == 0
    assert two_stage._best_media_card_child_index(metadata, card_boxes) == 0


def test_media_card_child_prefers_containing_card_over_adjacent_landscape_card() -> None:
    card_boxes = [
        {
            "x": 100,
            "y": 100,
            "w": 300,
            "h": 120,
            "visual_bbox": {"x": 100, "y": 100, "w": 300, "h": 120},
        },
        {
            "x": 430,
            "y": 100,
            "w": 180,
            "h": 300,
            "visual_bbox": {"x": 430, "y": 100, "w": 180, "h": 300},
        },
    ]
    contained_label = {
        "item_id": "neighbor_card_metric",
        "label": "3,000",
        "role": "text",
        "item_type": "readable",
        "bbox": {"x": 430, "y": 100, "w": 20, "h": 10},
    }

    assert two_stage._best_media_card_child_index(contained_label, card_boxes) == 1


def test_media_card_child_uses_visual_bbox_when_inferred_bbox_is_shorter() -> None:
    card_boxes = [
        {
            "x": 100,
            "y": 100,
            "w": 300,
            "h": 120,
            "visual_bbox": {"x": 100, "y": 100, "w": 300, "h": 120},
        },
        {
            "x": 430,
            "y": 100,
            "w": 180,
            "h": 90,
            "visual_bbox": {"x": 430, "y": 100, "w": 180, "h": 300},
        },
    ]
    contained_label = {
        "item_id": "neighbor_card_metric",
        "label": "3,000",
        "role": "text",
        "item_type": "readable",
        "bbox": {"x": 435, "y": 240, "w": 40, "h": 18},
    }

    assert two_stage._best_media_card_child_index(contained_label, card_boxes) == 1


def test_fragmented_visual_media_card_boxes_merge_before_row_grouping() -> None:
    merged = two_stage._merge_fragmented_visual_media_card_boxes(
        [
            {"x": 100, "y": 100, "w": 220, "h": 340},
            {"x": 340, "y": 100, "w": 220, "h": 340},
            {"x": 580, "y": 210, "w": 205, "h": 125},
            {"x": 590, "y": 346, "w": 204, "h": 96},
            {"x": 820, "y": 100, "w": 220, "h": 340},
        ]
    )

    assert sorted(merged, key=lambda box: box["x"]) == [
        {"x": 100, "y": 100, "w": 220, "h": 340},
        {"x": 340, "y": 100, "w": 220, "h": 340},
        {"x": 580, "y": 210, "w": 214, "h": 232},
        {"x": 820, "y": 100, "w": 220, "h": 340},
    ]
    rows = two_stage._media_card_rows(merged)
    assert len(rows) == 1
    assert len(rows[0]) == 4


def test_fragment_merge_keeps_adjacent_full_landscape_media_rows_separate() -> None:
    merged = two_stage._merge_fragmented_visual_media_card_boxes(
        [
            {"x": 100, "y": 100, "w": 500, "h": 280},
            {"x": 100, "y": 396, "w": 500, "h": 180},
            {"x": 700, "y": 700, "w": 220, "h": 340},
            {"x": 940, "y": 700, "w": 220, "h": 340},
        ]
    )

    assert {"x": 100, "y": 100, "w": 500, "h": 280} in merged
    assert {"x": 100, "y": 396, "w": 500, "h": 180} in merged
    assert len(merged) == 4


def test_visual_media_card_matches_same_label_structured_parent_boundary() -> None:
    structured_parent = {
        "number": "3.12",
        "item_id": "favorite_card",
        "label": "Favorite songs",
        "role": "listitem",
        "item_type": "actionable",
        "bbox": {"x": 299, "y": 610, "w": 194, "h": 260},
        "source": "structure_region_item",
    }

    matched = two_stage._matching_structured_media_card_parent(
        {"x": 301, "y": 614, "w": 186, "h": 300},
        [structured_parent],
        label="Favorite songs",
    )

    assert matched is structured_parent


def test_structured_media_card_boundary_overrides_inferred_dense_slot(monkeypatch) -> None:
    visual_cards = [
        {"x": 10, "y": 20, "w": 100, "h": 100},
        {"x": 130, "y": 20, "w": 100, "h": 120},
    ]
    monkeypatch.setattr(
        two_stage,
        "_visual_media_card_boxes",
        lambda **_kwargs: visual_cards,
    )
    monkeypatch.setattr(two_stage, "_media_card_rows", lambda _boxes: [visual_cards])
    monkeypatch.setattr(
        two_stage,
        "_infer_dense_row_placeholder_card_slot",
        lambda card_bbox, **_kwargs: (
            dict(card_bbox),
            {
                "contract_version": "learn_dense_row_placeholder_slot_inference_v1",
                "applied": True,
                "reason": "dense_row_placeholder_visual_slot_inferred",
            },
        ),
    )

    items, audit = two_stage._synthesize_primary_media_cards(
        [
            {
                "number": "3.1",
                "item_id": "favorite_card",
                "label": "Favorite songs",
                "role": "listitem",
                "item_type": "actionable",
                "bbox": {"x": 130, "y": 20, "w": 100, "h": 100},
                "source": "structure_region_item",
            }
        ],
        image_path="unused.png",
        region_bbox={"x": 0, "y": 0, "w": 260, "h": 180},
    )

    favorite = next(item for item in items if item["label"] == "Favorite songs")
    assert favorite["bbox"] == {"x": 130, "y": 20, "w": 100, "h": 100}
    assert favorite["bbox_reconciliation"]["reason"] == "same_label_high_overlap_structured_parent_boundary"
    assert audit["structured_parent_reconciliation_count"] == 1
    assert all(item.get("item_id") != "favorite_card" for item in items)


def test_tile_group_normalizes_generic_card_leaf_roles_without_media_evidence() -> None:
    items = [
        {"item_id": "settings_a", "role": "recommendation_item", "source": "structure_region_item"},
        {"item_id": "settings_b", "role": "news_card", "source": "structure_region_item"},
    ]
    groups = [{"group_id": "settings_row", "role": "tile_card_group", "member_item_ids": ["settings_a", "settings_b"]}]

    normalized = two_stage._normalize_tile_group_member_roles(items, groups)

    assert [item["role"] for item in normalized] == ["tile_card", "tile_card"]
    assert [item["original_role"] for item in normalized] == ["recommendation_item", "news_card"]


def test_tile_parent_normalizes_generic_card_leaf_roles_without_media_evidence() -> None:
    items = [
        {"item_id": "settings_a", "role": "recommendation_item", "source": "structure_region_item"},
        {"item_id": "settings_b", "role": "news_card", "source": "structure_region_item"},
    ]
    groups = [
        {
            "group_id": "settings_tile_a",
            "role": "tile_card_parent",
            "source": "stage2_primary_tile_card_parent_grouping",
            "member_item_ids": ["settings_a", "settings_b"],
        }
    ]

    normalized = two_stage._normalize_tile_group_member_roles(items, groups)

    assert [item["role"] for item in normalized] == ["tile_card", "tile_card"]
    assert [item["original_role"] for item in normalized] == ["recommendation_item", "news_card"]


def test_two_stage_marks_incomplete_visual_card_parent_as_needs_review(tmp_path):
    image_path = tmp_path / "incomplete_card_parent.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (760, 430), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 150, 260, 310), radius=8, fill=(40, 90, 180))
    draw.rounded_rectangle((300, 150, 460, 310), radius=8, fill=(180, 80, 40))
    draw.rounded_rectangle((500, 150, 680, 310), radius=8, fill=(232, 232, 232), outline=(214, 214, 214))
    draw.polygon([(590, 178), (612, 224), (664, 232), (626, 264), (636, 310), (590, 284), (544, 310), (554, 264), (516, 232), (568, 224)], fill=(240, 36, 48))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "Recent cards",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 110, "w": 150, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_1_text",
            "label": "Card One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 322, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_2_text",
            "label": "Card Two",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 308, "y": 322, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "incomplete_title",
            "label": "Favorite songs",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 508, "y": 322, "w": 130, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 430}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    incomplete = next(item for item in primary["numbered_items"] if item["label"] == "Favorite songs")
    assert incomplete["role"] == "card_parent_incomplete"
    assert incomplete["needs_review"] is True
    assert incomplete["review_required"] is True
    assert incomplete["action_candidate"] is False
    assert incomplete["incomplete_reason"] == "missing_card_slot_or_click_area"
    assert incomplete["overlay_style"]["tone"] == "needs_review_incomplete_card"
    assert incomplete["bbox_policy"] == "incomplete_visual_card_parent_needs_review"
    assert incomplete["execute_binding_enabled"] is False


def test_two_stage_infers_dense_row_slot_for_placeholder_media_card(tmp_path):
    image_path = tmp_path / "placeholder_dense_row_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1120, 520), "white")
    draw = ImageDraw.Draw(image)
    slots = [
        (100, 150, 260, 310, (40, 90, 180)),
        (300, 150, 460, 310, (248, 248, 248)),
        (500, 150, 660, 310, (180, 80, 40)),
        (700, 150, 860, 310, (40, 160, 100)),
        (900, 150, 1060, 310, (180, 40, 140)),
    ]
    for index, (x1, y1, x2, y2, color) in enumerate(slots):
        outline = None if index == 1 else (214, 214, 214)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=color, outline=outline)
        if index == 1:
            draw.polygon(
                [
                    (380, 190),
                    (398, 224),
                    (436, 230),
                    (408, 254),
                    (416, 288),
                    (380, 268),
                    (344, 288),
                    (352, 254),
                    (324, 230),
                    (362, 224),
                ],
                fill=(240, 36, 48),
            )
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_gallery",
            "label": "Main gallery",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 120, "w": 990, "h": 250},
            "review_only": True,
        },
        *[
        {
            "item_id": f"card_{index}_text",
            "label": label,
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": x, "y": 322, "w": w, "h": 24},
            "review_only": True,
        }
        for index, (label, x, w) in enumerate(
            [
                ("Card One", 108, 90),
                ("Favorite songs", 308, 130),
                ("Card Three", 508, 110),
                ("Card Four", 708, 100),
                ("Card Five", 908, 100),
            ],
            start=1,
        )
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1120, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in result["stage2_numbering"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
        or item["region_id"].endswith("__stage1_5__message_thread")
    )
    favorite = next(item for item in primary["numbered_items"] if item["label"] == "Favorite songs")
    assert favorite["role"] == "media_card"
    assert favorite["bbox"]["x"] <= 308
    assert favorite["bbox"]["w"] >= 150
    assert 190 <= favorite["bbox"]["h"] <= 210
    assert favorite["card_parent_validation"]["complete"] is True
    assert favorite["card_parent_validation"]["slot_inference"]["applied"] is True
    assert favorite["card_parent_validation"]["slot_inference"]["reason"] == "dense_row_placeholder_visual_slot_inferred"
    assert favorite["bbox_policy"] == "visual_media_card_parent_with_inferred_dense_row_slot"
    assert favorite["execute_binding_enabled"] is False


def test_two_stage_media_card_children_do_not_cross_next_section_heading(tmp_path):
    image_path = tmp_path / "card_section_boundary.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (760, 560), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 110, 260, 270), radius=8, fill=(40, 90, 180))
    draw.rounded_rectangle((300, 110, 460, 270), radius=8, fill=(180, 80, 40))
    draw.rectangle((100, 510, 260, 559), fill=(40, 160, 100))
    draw.rectangle((300, 510, 460, 559), fill=(180, 40, 140))
    image.save(image_path)
    inventory = [
        {
            "item_id": "first_section",
            "label": "Recently played",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 72, "w": 150, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "first_card_title",
            "label": "Station One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 106, "y": 286, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "next_section",
            "label": "Game music",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 334, "w": 130, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "next_card_title",
            "label": "Eorzean Symphony",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 106, "y": 512, "w": 160, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 560}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    first_card = next(item for item in primary["numbered_items"] if item["label"] == "Station One")
    first_child_ids = {child["item_id"] for child in first_card["children"]}
    assert "next_section" not in first_child_ids
    assert "next_card_title" not in first_child_ids
    assert first_card["bbox"]["y"] + first_card["bbox"]["h"] <= inventory[2]["bbox"]["y"]


def test_two_stage_groups_bottom_edge_text_fragments_as_partial_visible_cards(tmp_path):
    image_path = tmp_path / "partial_cards.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((112, 450, 286, 519), fill=(40, 80, 180))
    draw.rectangle((340, 450, 480, 519), fill=(180, 80, 40))
    draw.rectangle((560, 450, 690, 519), fill=(40, 160, 100))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "2010 年代粤语流行代表专辑",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 360, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "partial_left_a",
            "label": "Eorzean",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 480, "w": 72, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "partial_left_b",
            "label": "Symphony",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 482, "w": 82, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "partial_right",
            "label": "Expedition",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 360, "y": 478, "w": 100, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if any(item["item_id"] == "section_title" for item in region["numbered_items"])
    )
    synthesis = primary["visual_small_control_refinement"]["partial_visible_card_synthesis"]
    assert synthesis["applied"] is True
    partial_cards = [item for item in primary["numbered_items"] if item["role"] == "partial_visible_card"]
    assert len(partial_cards) == 3
    assert any(item["item_id"] == "section_title" and item["role"] == "text" for item in primary["numbered_items"])
    assert all(item["partial_visible"] is True for item in partial_cards)
    child_label_sets = [{child["label"] for child in item["children"]} for item in partial_cards]
    assert {"Eorzean", "Symphony"} in child_label_sets
    assert {"Expedition"} in child_label_sets
    assert any(not item["children"] for item in partial_cards)
    assert {item["item_id"] for item in partial_cards} == {
        "partial_visible_card_1",
        "partial_visible_card_2",
        "partial_visible_card_3",
    }
    assert "partial_left_a" not in {item["item_id"] for item in primary["numbered_items"]}
    partial_group = next(group for group in primary["subregion_groups"] if group["role"] == "partial_visible_card_group")
    assert len(partial_group["member_numbers"]) == 3
    section_parent = next(group for group in primary["subregion_groups"] if group["role"] == "section_parent")
    assert section_parent["child_group_ids"] == [partial_group["group_id"]]


def test_partial_card_section_title_accepts_year_heading_but_rejects_numeric_noise() -> None:
    assert two_stage._has_meaningful_section_title_text({"label": "2010 年代粤语流行代表专辑"}) is True
    assert two_stage._has_meaningful_section_title_text({"label": "17:12"}) is False
    assert two_stage._has_meaningful_section_title_text({"label": "99+"}) is False
    assert two_stage._has_meaningful_section_title_text({"label": "2010"}) is False
    assert two_stage._has_meaningful_section_title_text({"label": "2026-07-22"}) is False


def test_two_stage_recovers_bottom_partial_cards_when_ocr_is_sparse(tmp_path) -> None:
    image_path = tmp_path / "sparse_ocr_partial_cards.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((112, 450, 286, 519), fill=(40, 80, 180))
    draw.rectangle((340, 450, 480, 519), fill=(180, 80, 40))
    draw.rectangle((560, 450, 690, 519), fill=(40, 160, 100))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "2010 年代粤语流行代表专辑",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 360, "w": 210, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "only_ocr_fragment",
            "label": "EASONCHAN",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 360, "y": 480, "w": 100, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "section_title")
    synthesis = primary["visual_small_control_refinement"]["partial_visible_card_synthesis"]
    partial_cards = [item for item in primary["numbered_items"] if item["role"] == "partial_visible_card"]
    assert synthesis["applied"] is True
    assert synthesis["visual_candidate_count"] >= 3
    assert len(partial_cards) >= 3


def test_partial_card_reconciliation_merges_fragments_using_peer_card_width() -> None:
    def fragment(item_id: str, label: str, x: int, y: int, w: int) -> dict:
        return {
            "number": item_id,
            "item_id": item_id,
            "label": label,
            "role": "text",
            "bbox": {"x": x, "y": y, "w": w, "h": 22},
        }

    left_title = fragment("1.1", "First panel", 110, 472, 96)
    left_action = fragment("1.2", "More", 302, 476, 46)
    right_title = fragment("1.3", "Second panel", 390, 472, 112)
    right_action = fragment("1.4", "More", 592, 476, 46)

    entries = two_stage._merge_partial_text_clusters_with_visual_boxes(
        [[left_title], [left_action], [right_title], [right_action]],
        [{"x": 100, "y": 450, "w": 250, "h": 70}],
    )

    assert len(entries) == 2
    assert [{item["item_id"] for item in entry["items"]} for entry in entries] == [
        {"1.1", "1.2"},
        {"1.3", "1.4"},
    ]
    assert entries[0]["visual_bbox"] == {"x": 100, "y": 450, "w": 250, "h": 70}
    assert entries[1]["visual_bbox"]["y"] == 450
    assert entries[1]["visual_bbox"]["h"] == 70
    assert entries[1]["visual_bbox"]["w"] >= 248


def test_bottom_partial_card_visual_segmentation_rejects_full_width_activity_band(tmp_path) -> None:
    image_path = tmp_path / "full_width_bottom_band.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 450, 719, 519), fill=(35, 45, 65))
    image.save(image_path)

    boxes = two_stage._visual_bottom_partial_card_boxes(
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 720, "h": 520},
        title_bbox={"x": 80, "y": 360, "w": 120, "h": 24},
    )

    assert boxes == []


def test_partial_visible_synthesis_suppresses_duplicates_over_existing_structured_cards(tmp_path):
    image_path = tmp_path / "partial_cards_with_existing_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((112, 450, 286, 519), fill=(40, 80, 180))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "More music",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 360, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "existing_bottom_card",
            "label": "Eorzean Symphony",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 112, "y": 448, "w": 176, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "partial_left_a",
            "label": "Eorzean",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 480, "w": 72, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "partial_left_b",
            "label": "Symphony",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 482, "w": 82, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if any(item["item_id"] == "section_title" for item in region["numbered_items"])
    )
    numbered_items = [
        item
        for region in result["stage2_numbering"]["regions"]
        for item in region.get("numbered_items", [])
    ]
    partial_cards = [item for item in numbered_items if item["role"] == "partial_visible_card"]
    assert not partial_cards
    assert any(item["item_id"] == "existing_bottom_card" and item["role"] == "news_card" for item in primary["numbered_items"])
    synthesis = primary["visual_small_control_refinement"]["partial_visible_card_synthesis"]
    assert synthesis["suppressed_duplicate_partial_card_count"] >= 1


def test_two_stage_does_not_turn_bottom_toolbar_text_into_partial_cards(tmp_path):
    image_path = tmp_path / "chat_toolbar.png"
    from PIL import Image

    Image.new("RGB", (720, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_message",
            "label": "hello there",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 220, "y": 300, "w": 160, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "toolbar_icon",
            "label": "?",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 260, "y": 460, "w": 24, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "send_text",
            "label": "发送",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 560, "y": 480, "w": 42, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage2_numbering"]["regions"]
    assert not [
        item
        for region in regions
        for item in region.get("numbered_items", [])
        if item["role"] == "partial_visible_card"
    ]
    toolbar_groups = [
        group
        for region in regions
        for group in region.get("subregion_groups", [])
        if group["role"] == "input_toolbar_region"
    ]
    for toolbar_group in toolbar_groups:
        assert toolbar_group["parent_child_policy"] == "bottom_toolbar_controls_and_send_button_form_display_only_input_area"
        assert toolbar_group["display_only"] is True
        assert toolbar_group["execute_binding_enabled"] is False
        assert toolbar_group["artifact_is_authorization"] is False


def test_two_stage_merges_caption_when_visual_artwork_bbox_is_narrow(tmp_path):
    image_path = tmp_path / "narrow_artwork_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((92, 92, 220, 220), fill=(215, 40, 40))
    draw.rectangle((310, 92, 438, 220), fill=(245, 245, 245), outline=(225, 225, 225), width=2)
    draw.polygon([(374, 118), (392, 154), (438, 154), (400, 178), (414, 216), (374, 194), (334, 216), (348, 178), (310, 154), (356, 154)], fill=(235, 30, 48))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 360, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "red_title",
            "label": "Red card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 102, "y": 230, "w": 80, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "star_title",
            "label": "Star card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 230, "w": 80, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 360}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    star_card = next(
        item
        for item in main["numbered_items"]
        if item["role"] == "media_card" and any(child["label"] == "Star card" for child in item["children"])
    )
    assert any(child["label"] == "Star card" for child in star_card["children"])
    assert star_card["bbox"]["x"] <= 302
    assert star_card["bbox"]["w"] < 180


def test_two_stage_does_not_expand_one_media_card_to_oversized_row_container(tmp_path):
    image_path = tmp_path / "media_cards_with_oversized_row_container.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (980, 440), "white")
    draw = ImageDraw.Draw(image)
    card_boxes = [
        (60, 90, 250, 320),
        (280, 90, 470, 320),
        (500, 90, 690, 320),
        (720, 90, 910, 320),
    ]
    for box, color in zip(card_boxes, ((210, 40, 40), (40, 110, 210), (40, 170, 90), (170, 50, 170))):
        draw.rounded_rectangle(box, radius=8, fill=color)
    image.save(image_path)

    inventory = [
        {
            "item_id": "whole_card_row",
            "label": "Card row",
            "role": "listitem",
            "item_type": "layout",
            "bbox": {"x": 40, "y": 70, "w": 900, "h": 290},
            "review_only": True,
        },
        *[
            {
                "item_id": f"card_title_{index}",
                "label": f"Card {index}",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": x + 10, "y": 330, "w": 100, "h": 22},
                "review_only": True,
            }
            for index, (x, _y1, _x2, _y2) in enumerate(card_boxes, start=1)
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 440}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert len(cards) == 4
    assert all(card["bbox"]["w"] < 260 for card in cards)
    assert all(child["item_id"] != "whole_card_row" for card in cards for child in card["children"])


def test_two_stage_keeps_inter_row_section_heading_outside_media_card(tmp_path):
    image_path = tmp_path / "section_heading_between_card_rows.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 220), fill=(220, 30, 30))
    draw.rectangle((250, 100, 370, 220), fill=(20, 140, 220))
    draw.rectangle((100, 340, 220, 460), fill=(60, 60, 120))
    draw.rectangle((250, 340, 370, 460), fill=(70, 130, 60))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 300, "h": 390},
            "review_only": True,
        },
        {
            "item_id": "top_card_title",
            "label": "Top Card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 230, "w": 90, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "next_section_title",
            "label": "Next Section",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 100, "y": 286, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "lower_card_title",
            "label": "Lower Card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 468, "w": 96, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert cards
    assert all("Next Section" not in [child["label"] for child in card["children"]] for card in cards)
    assert any(item["label"] == "Next Section" and item["role"] == "text" for item in main["numbered_items"])
    top_card = next(card for card in cards if any(child["label"] == "Top Card" for child in card["children"]))
    assert top_card["bbox"]["y"] + top_card["bbox"]["h"] < 286


def test_two_stage_keeps_following_section_heading_outside_single_row_media_card(tmp_path):
    image_path = tmp_path / "single_row_following_section.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 260, 260), fill=(220, 30, 30))
    draw.rectangle((300, 100, 460, 260), fill=(20, 140, 220))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 390, "h": 380},
            "review_only": True,
        },
        {
            "item_id": "first_card_title",
            "label": "First card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 272, "w": 90, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "second_card_title",
            "label": "Second card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 308, "y": 272, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "next_section_title",
            "label": "Next Section",
            "role": "heading",
            "item_type": "heading",
            "bbox": {"x": 100, "y": 330, "w": 140, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert cards
    assert all("Next Section" not in [child["label"] for child in card["children"]] for card in cards)
    assert any(item["label"] == "Next Section" and item["role"] == "heading" for item in main["numbered_items"])
    assert all(card["bbox"]["y"] + card["bbox"]["h"] < 330 for card in cards)


def test_stage1_region_localization_report_skips_numbering_and_exposes_calibration_prompt(tmp_path):
    image_path = tmp_path / "apple_music.png"
    from PIL import Image

    Image.new("RGB", (900, 650), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 140, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 240, "w": 260, "h": 190},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "main_content": {"item_ids": ["card_1"]},
        },
        "nodes": {
            "nav_home": inventory[0],
            "card_1": inventory[1],
        },
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["contract_version"] == "learn_stage1_region_localization_report_v1"
    assert report["scope"] == "stage1_region_localization_only"
    assert report["stage2_numbering_skipped"] is True
    assert report["pathgraph_generation_skipped"] is True
    assert "stage2_numbering" not in report
    assert report["model_call_plan"]["semantic_model"] == "qwen3_vl_8b_q4_k_m"
    assert report["model_call_plan"]["coordinate_model"] == "vista_4b_transformers"
    prompt = report["model_call_plan"]["prompt"]
    assert "Do not number inner buttons" in prompt
    assert "replace it completely" in prompt
    assert "full screenshot coordinates" in prompt
    assert report["stage1_region_localization"]["localized_region_count"] == 2
    assert report["calibration_diagnostics"]["geometry_only_region_count"] == 0
    assert report["calibration_diagnostics"]["needs_prompt_or_model_calibration"] is False
    assert {
        item["risk"] for item in report["calibration_diagnostics"]["diagnostics"]
    } == {"heuristic_calibrated_needs_visual_review"}
    assert report["display_readiness"]["stage1_overlay_available"] is True
    assert Path(report["overlay_path"]).exists()




def test_stage1_granularity_review_flags_chat_primary_as_stage1_5_candidate(tmp_path):
    image_path = tmp_path / "chat_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["region_selection_audit"]["passed"] is True
    granularity = report["stage1_granularity_review"]
    assert granularity["status"] == "stage1_geometry_passed_needs_granularity_review"
    assert any(issue["issue"] == "primary_contains_multiple_work_panes" for issue in granularity["issues"])
    evidence = {
        item
        for issue in granularity["issues"]
        if issue["issue"] == "primary_contains_multiple_work_panes"
        for item in issue["evidence"]
    }
    assert {
        "conversation_or_list_pane_signal",
        "message_thread_signal",
        "bottom_composer_signal",
    }.issubset(evidence)


def test_stage1_granularity_review_uses_validated_chat_profile_when_item_roles_are_generic() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "role": "main_content",
        "bbox": {"x": 60, "y": 80, "w": 940, "h": 620},
        "item_ids": ["row_1", "row_2", "message", "composer"],
    }
    items_by_id = {
        "row_1": {
            "item_id": "row_1",
            "role": "dataitem",
            "item_type": "dataitem",
            "label": "Person one 10:20 Preview",
            "bbox": {"x": 70, "y": 140, "w": 260, "h": 64},
        },
        "row_2": {
            "item_id": "row_2",
            "role": "dataitem",
            "item_type": "dataitem",
            "label": "Person two 10:21 Preview",
            "bbox": {"x": 70, "y": 210, "w": 260, "h": 64},
        },
        "message": {
            "item_id": "message",
            "role": "text",
            "item_type": "readable",
            "label": "Hello there",
            "bbox": {"x": 430, "y": 220, "w": 180, "h": 28},
        },
        "composer": {
            "item_id": "composer",
            "role": "input",
            "item_type": "input",
            "label": "Write a message",
            "bbox": {"x": 390, "y": 620, "w": 520, "h": 48},
        },
    }

    review = two_stage._stage1_granularity_review(
        localized_regions=[region],
        items_by_id=items_by_id,
        screen_size={"width": 1000, "height": 700},
        region_selection_audit={"passed": True},
        class_rule_profile={"allow_chat_semantics": True},
    )

    assert review["status"] == "stage1_geometry_passed_needs_granularity_review"
    issue = next(item for item in review["issues"] if item["issue"] == "primary_contains_multiple_work_panes")
    assert "validated_conversation_profile" in issue["evidence"]


def test_stage1_5_partition_suggests_web_content_column_without_shrinking_stage1(tmp_path):
    image_path = tmp_path / "web_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_address",
            "label": "https://python.org",
            "role": "browser_address_bar",
            "item_type": "browser_chrome",
            "bbox": {"x": 80, "y": 8, "w": 900, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "site_nav",
            "label": "Docs Community Jobs",
            "role": "nav_item",
            "item_type": "section",
            "bbox": {"x": 0, "y": 80, "w": 1200, "h": 58},
            "review_only": True,
        },
        {
            "item_id": "hero_content_column",
            "label": "Centered web content column",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 170, "w": 600, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "floating_translate",
            "label": "translate",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 470, "w": 32, "h": 32},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_address"]},
            "top_bar": {"item_ids": ["site_nav"]},
            "primary_area": {"item_ids": ["hero_content_column", "floating_translate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(region for region in report["stage1_region_localization"]["regions"] if region["zone_id"] == "primary_area")
    assert primary["bbox"]["x"] == 0
    assert primary["bbox"]["w"] == 1200
    partition = report["stage1_5_partition"]
    assert partition["status"] == "stage1_5_suggested"
    assert partition["stage1_regions_unchanged"] is True
    assert partition["pathgraph_generation_skipped"] is True
    content_columns = [item for item in partition["subregions"] if item["role"] == "content_column"]
    assert len(content_columns) == 1
    assert content_columns[0]["parent_region_id"] == primary["region_id"]
    assert content_columns[0]["bbox"]["x"] == 300
    assert content_columns[0]["bbox"]["w"] == 600
    assert "hero_content_column" in content_columns[0]["item_ids"]
    assert report["stage1_5_overlay_path"]


def test_two_stage_numbers_stage1_5_web_content_column_instead_of_broad_primary(tmp_path):
    image_path = tmp_path / "web_surface_two_stage.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_address",
            "label": "https://python.org",
            "role": "browser_address_bar",
            "item_type": "browser_chrome",
            "bbox": {"x": 80, "y": 8, "w": 900, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "site_nav",
            "label": "Docs Community Jobs",
            "role": "nav_item",
            "item_type": "section",
            "bbox": {"x": 0, "y": 80, "w": 1200, "h": 58},
            "review_only": True,
        },
        {
            "item_id": "hero_content_column",
            "label": "Centered web content column",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 170, "w": 600, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "hero_card",
            "label": "Hero card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 340, "y": 250, "w": 220, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "floating_translate",
            "label": "translate",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 470, "w": 32, "h": 32},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_address"]},
            "top_bar": {"item_ids": ["site_nav"]},
            "primary_area": {"item_ids": ["hero_content_column", "hero_card", "floating_translate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = _build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_5_partition"]["status"] == "stage1_5_suggested"
    region_ids = {region["region_id"] for region in result["stage2_numbering"]["regions"]}
    assert "structure_region_primary_area" not in region_ids
    assert "structure_region_main_content__stage1_5__content_column" in region_ids
    content_column = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["region_id"] == "structure_region_main_content__stage1_5__content_column"
    )
    assert content_column["input_stage1_5_subregion"]["role"] == "content_column"
    assert content_column["bbox"]["x"] == 300
    assert content_column["bbox"]["w"] == 600
    labels = {item["label"] for item in content_column["numbered_items"]}
    assert "Hero card" in labels
    assert "translate" not in labels


def test_stage1_5_stage2_selection_only_accepts_contained_main_content_subregions():
    localized_regions = [
        {
            "region_id": "structure_region_top_bar",
            "label": "Top bar",
            "bbox": {"x": 80, "y": 0, "w": 920, "h": 70},
        },
        {
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 80, "y": 70, "w": 920, "h": 650},
        },
    ]
    subregions = [
        {
            "subregion_id": "top_controls",
            "parent_region_id": "structure_region_top_bar",
            "role": "top_controls",
            "bbox": {"x": 120, "y": 8, "w": 180, "h": 42},
        },
        {
            "subregion_id": "content_column",
            "parent_region_id": "structure_region_primary_area",
            "role": "content_column",
            "bbox": {"x": 180, "y": 120, "w": 620, "h": 520},
        },
    ]

    annotated, report = two_stage._stage1_5_stage2_selection_report(
        subregions=subregions,
        localized_regions=localized_regions,
    )

    by_id = {item["subregion_id"]: item for item in annotated}
    assert by_id["top_controls"]["stage2_numbering_eligible"] is False
    assert by_id["top_controls"]["stage2_numbering_selection_reason"] == "stage1_5_only_main_content_may_replace_stage2_input"
    assert by_id["content_column"]["stage2_numbering_eligible"] is True
    assert report["eligible_count"] == 1
    assert report["rejected_count"] == 1


def test_stage1_5_stage2_selection_rejects_partition_that_drops_parent_evidence() -> None:
    parent_item_ids = [f"item_{index}" for index in range(10)]
    localized_regions = [
        {
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 80, "y": 70, "w": 920, "h": 650},
            "item_ids": parent_item_ids,
        }
    ]
    subregions = [
        {
            "subregion_id": "misread_message_thread",
            "parent_region_id": "structure_region_primary_area",
            "role": "message_thread",
            "bbox": {"x": 100, "y": 100, "w": 300, "h": 260},
            "item_ids": ["item_0"],
        },
        {
            "subregion_id": "misread_composer",
            "parent_region_id": "structure_region_primary_area",
            "role": "bottom_composer",
            "bbox": {"x": 100, "y": 360, "w": 300, "h": 80},
            "item_ids": ["item_1"],
        },
    ]

    annotated, report = two_stage._stage1_5_stage2_selection_report(
        subregions=subregions,
        localized_regions=localized_regions,
    )

    assert report["eligible_count"] == 0
    assert report["rejected_count"] == 2
    assert report["parent_evidence_coverage"]["structure_region_primary_area"]["coverage"] == 0.2
    assert all(item["stage2_numbering_eligible"] is False for item in annotated)
    assert {
        item["stage2_numbering_selection_reason"] for item in annotated
    } == {"stage1_5_partition_drops_parent_evidence"}


def test_stage2_input_ignores_unstable_stage1_5_partition_for_structure_bars():
    localized_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_top_bar",
            "label": "Top bar",
            "bbox": {"x": 80, "y": 0, "w": 920, "h": 70},
            "item_ids": ["play"],
        },
        {
            "region_no": 2,
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 80, "y": 70, "w": 920, "h": 650},
            "item_ids": ["card"],
        },
    ]
    unstable_partition = {
        "subregions": [
            {
                "subregion_id": "bad_top_split",
                "parent_region_id": "structure_region_top_bar",
                "role": "top_controls",
                "bbox": {"x": 120, "y": 8, "w": 180, "h": 42},
                "item_ids": ["play"],
                "stage2_numbering_eligible": False,
            }
        ]
    }

    regions = two_stage._stage2_input_regions(
        localized_regions=localized_regions,
        stage1_5_partition=unstable_partition,
        items_by_id={
            "play": {"item_id": "play", "bbox": {"x": 140, "y": 20, "w": 24, "h": 24}},
            "card": {"item_id": "card", "bbox": {"x": 120, "y": 120, "w": 240, "h": 260}},
        },
    )

    assert [region["region_id"] for region in regions] == [
        "structure_region_top_bar",
        "structure_region_primary_area",
    ]
    assert all(region.get("stage") != "stage1_5_subregion_for_stage2_numbering" for region in regions)


def test_stage1_5_partition_suggests_chat_subpanes_inside_primary(tmp_path):
    image_path = tmp_path / "chat_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    partition = report["stage1_5_partition"]
    roles = {item["role"] for item in partition["subregions"]}
    assert partition["status"] == "stage1_5_suggested"
    assert {"conversation_list", "message_thread", "bottom_composer"}.issubset(roles)
    message_thread = next(item for item in partition["subregions"] if item["role"] == "message_thread")
    conversation_list = next(item for item in partition["subregions"] if item["role"] == "conversation_list")
    bottom_composer = next(item for item in partition["subregions"] if item["role"] == "bottom_composer")
    assert message_thread["bbox"]["y"] + message_thread["bbox"]["h"] == bottom_composer["bbox"]["y"]
    assert conversation_list["bbox"]["y"] + conversation_list["bbox"]["h"] == (
        conversation_list["parent_region_bbox"]["y"] + conversation_list["parent_region_bbox"]["h"]
    )
    assert conversation_list["bbox"]["x"] == conversation_list["parent_region_bbox"]["x"]
    assert conversation_list["bbox"]["x"] + conversation_list["bbox"]["w"] == message_thread["bbox"]["x"]
    assert bottom_composer["bbox"]["x"] == message_thread["bbox"]["x"]
    assert bottom_composer["bbox"]["w"] == message_thread["bbox"]["w"]
    assert bottom_composer["stage1_5_boundary_review"]["status"] == "composer_bbox_constrained_to_message_channel"
    assert bottom_composer["stage1_5_boundary_review"]["previous_bbox"]["x"] == conversation_list["parent_region_bbox"]["x"]
    assert "bottom_tool_row" in bottom_composer["item_ids"]
    assert "bottom_tool_row" not in message_thread["item_ids"]
    assert "bottom_icon_glyphs" in bottom_composer["item_ids"]
    assert "bottom_icon_glyphs" not in message_thread["item_ids"]
    assert bottom_composer["bbox"]["y"] <= 604
    assert all(item["display_only"] is True for item in partition["subregions"])
    assert all(item["execute_binding_enabled"] is False for item in partition["subregions"])


def test_stage1_5_partition_uses_neutral_work_panes_without_chat_evidence(tmp_path):
    image_path = tmp_path / "generic_work_panes.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "file_1",
            "label": "README.md",
            "role": "list_item",
            "item_type": "row",
            "bbox": {"x": 100, "y": 120, "w": 220, "h": 42},
        },
        {
            "item_id": "file_2",
            "label": "app/runtime.py",
            "role": "list_item",
            "item_type": "row",
            "bbox": {"x": 100, "y": 172, "w": 220, "h": 42},
        },
        {
            "item_id": "diff_header",
            "label": "Changed lines",
            "role": "detail_header",
            "item_type": "text",
            "bbox": {"x": 430, "y": 120, "w": 320, "h": 36},
        },
        {
            "item_id": "diff_body",
            "label": "Source code diff",
            "role": "detail_content",
            "item_type": "document",
            "bbox": {"x": 430, "y": 166, "w": 620, "h": 480},
        },
    ]
    items_by_id = {item["item_id"]: item for item in inventory}
    localized_regions = [
        {
            "region_id": "structure_region_main_content",
            "role": "main_content",
            "zone_id": "primary_area",
            "bbox": {"x": 80, "y": 90, "w": 1000, "h": 620},
            "item_ids": [item["item_id"] for item in inventory],
        }
    ]

    partition = two_stage._stage1_5_partition(
        localized_regions=localized_regions,
        items_by_id=items_by_id,
        screen_size={"width": 1200, "height": 780},
        region_selection_audit={"passed": True},
        granularity_review={
            "issues": [
                {
                    "region_id": "structure_region_main_content",
                    "issue": "primary_contains_multiple_work_panes",
                }
            ]
        },
        source_image_path=str(image_path),
    )

    roles = {item["role"] for item in partition["subregions"]}
    assert partition["status"] == "stage1_5_suggested"
    assert {"list_pane", "detail_pane"}.issubset(roles)
    assert roles.isdisjoint({"conversation_list", "message_thread", "bottom_composer"})
    assert {
        item_id
        for subregion in partition["subregions"]
        for item_id in subregion["item_ids"]
    } == {item["item_id"] for item in inventory}


def test_stage1_5_plain_page_text_cannot_select_chat_semantic_family():
    items_by_id = {
        "code_1": {
            "item_id": "code_1",
            "label": "def conversation_bottom_panel():",
            "role": "text",
            "item_type": "readable",
        },
        "code_2": {
            "item_id": "code_2",
            "label": "composer = build_message_thread()",
            "role": "text",
            "item_type": "readable",
        },
    }

    evidence = two_stage._primary_subpane_evidence(
        {"item_ids": ["code_1", "code_2"]},
        items_by_id=items_by_id,
    )

    assert evidence == []


def test_stage1_5_neutral_work_panes_do_not_enable_chat_semantics(tmp_path):
    image_path = tmp_path / "generic_work_panes_two_stage.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "file_1",
            "label": "README.md",
            "role": "list_item",
            "item_type": "row",
            "bbox": {"x": 100, "y": 120, "w": 220, "h": 42},
        },
        {
            "item_id": "file_2",
            "label": "app/runtime.py",
            "role": "list_item",
            "item_type": "row",
            "bbox": {"x": 100, "y": 172, "w": 220, "h": 42},
        },
        {
            "item_id": "diff_header",
            "label": "Changed lines",
            "role": "detail_header",
            "item_type": "text",
            "bbox": {"x": 430, "y": 120, "w": 320, "h": 36},
        },
        {
            "item_id": "diff_body",
            "label": "Source code diff",
            "role": "detail_content",
            "item_type": "document",
            "bbox": {"x": 430, "y": 166, "w": 620, "h": 480},
        },
    ]
    items_by_id = {item["item_id"]: item for item in inventory}
    localized_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_main_content",
            "role": "main_content",
            "zone_id": "primary_area",
            "bbox": {"x": 80, "y": 90, "w": 1000, "h": 620},
            "item_ids": [item["item_id"] for item in inventory],
        }
    ]
    partition = two_stage._stage1_5_partition(
        localized_regions=localized_regions,
        items_by_id=items_by_id,
        screen_size={"width": 1200, "height": 780},
        region_selection_audit={"passed": True},
        granularity_review={
            "issues": [
                {
                    "region_id": "structure_region_main_content",
                    "issue": "primary_contains_multiple_work_panes",
                }
            ]
        },
        source_image_path=str(image_path),
        class_rule_profile={"allow_chat_semantics": False},
    )
    stage1_5_roles = {item["role"] for item in partition["subregions"]}
    assert {"list_pane", "detail_pane"}.issubset(stage1_5_roles)
    input_regions = two_stage._stage2_input_regions(
        localized_regions=localized_regions,
        stage1_5_partition=partition,
        items_by_id=items_by_id,
    )
    stage2 = two_stage._stage2_numbering(
        input_regions,
        items_by_id=items_by_id,
        image_path=str(image_path),
        class_rule_profile={"allow_chat_semantics": False},
    )
    groups = [
        group
        for region in stage2["regions"]
        for group in region.get("subregion_groups", [])
    ]
    assert all(group.get("role") not in {"conversation_row", "message_item"} for group in groups)


def test_two_stage_numbers_stage1_5_chat_subpanes_instead_of_broad_primary(tmp_path):
    image_path = tmp_path / "chat_surface_two_stage.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = _build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_5_partition"]["status"] == "stage1_5_suggested"
    region_ids = {region["region_id"] for region in result["stage2_numbering"]["regions"]}
    assert "structure_region_primary_area" not in region_ids
    assert {
        "structure_region_main_content__stage1_5__conversation_list",
        "structure_region_main_content__stage1_5__message_thread",
        "structure_region_main_content__stage1_5__bottom_composer",
    }.issubset(region_ids)
    bottom_composer = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["region_id"] == "structure_region_main_content__stage1_5__bottom_composer"
    )
    assert bottom_composer["input_stage1_5_subregion"]["role"] == "bottom_composer"
    labels = {item["label"] for item in bottom_composer["numbered_items"]}
    assert "Attach emoji voice send tools" in labels
    assert ">□>" in labels


def test_stage1_5_bottom_composer_constrains_tall_shell_to_vertical_evidence(tmp_path):
    image_path = tmp_path / "chat_surface_tall_composer_shell.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer_input",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 540, "w": 830, "h": 176},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 604, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer_input",
                    "bottom_bar",
                    "bottom_tool_row",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    bottom_composer = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "bottom_composer"
    )
    message_thread = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "message_thread"
    )
    conversation_list = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "conversation_list"
    )
    assert bottom_composer["bbox"]["y"] == 604
    assert bottom_composer["bbox"]["h"] == 110
    assert message_thread["bbox"]["y"] + message_thread["bbox"]["h"] == bottom_composer["bbox"]["y"]
    assert conversation_list["bbox"]["y"] + conversation_list["bbox"]["h"] == (
        conversation_list["parent_region_bbox"]["y"] + conversation_list["parent_region_bbox"]["h"]
    )
    vertical_review = bottom_composer["stage1_5_vertical_review"]
    assert vertical_review["status"] == "composer_bbox_constrained_to_evidence_vertical_span"
    assert vertical_review["previous_bbox"]["y"] == 540
    assert vertical_review["evidence_bbox"]["y"] == 604
    assert "bottom_bar" in vertical_review["excluded_shell_item_ids"]


def test_stage1_5_overlay_styles_distinguish_adjacent_chat_panes():
    styles = {
        role: _stage1_5_overlay_style(role, index=index)
        for index, role in enumerate(("conversation_list", "message_thread", "bottom_composer"), start=1)
    }

    colors = {role: style["color"] for role, style in styles.items()}

    assert len(set(colors.values())) == 3
    assert colors["conversation_list"] != colors["bottom_composer"]
    assert all(style["width"] >= 4 for style in styles.values())


def test_stage1_5_partition_does_not_split_stage1_ready_media_surface(tmp_path):
    image_path = tmp_path / "apple_music_like.png"
    from PIL import Image

    Image.new("RGB", (1200, 760), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Home Browse Radio",
            "role": "left_nav",
            "item_type": "nav",
            "bbox": {"x": 0, "y": 70, "w": 96, "h": 690},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "player controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 96, "y": 0, "w": 1104, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "media_grid",
            "label": "Recently played music cards",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 120, "y": 120, "w": 980, "h": 520},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {"item_ids": ["media_grid"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 760}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["stage1_granularity_review"]["status"] == "stage1_geometry_ready"
    assert report["stage1_5_partition"]["status"] == "not_needed_stage1_geometry_ready"
    assert report["stage1_5_partition"]["subregion_count"] == 0
    assert report["stage1_5_overlay_path"] == ""


def test_two_stage_expands_topbar_icon_fragments_to_review_hit_areas(tmp_path):
    image_path = tmp_path / "topbar_controls.png"
    from PIL import Image

    Image.new("RGB", (640, 240), "white").save(image_path)
    inventory = [
        {
            "item_id": "prev_icon",
            "label": "previous",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 122, "y": 18, "w": 12, "h": 14},
            "review_only": True,
        },
        {
            "item_id": "play_icon",
            "label": "play",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 164, "y": 17, "w": 14, "h": 16},
            "review_only": True,
        },
        {
            "item_id": "next_icon",
            "label": "next",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 206, "y": 18, "w": 12, "h": 14},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 640, "height": 240}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    topbar = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    assert topbar["visual_small_control_refinement"]["topbar_item_grouping"]["applied"] is True
    assert topbar["visual_small_control_refinement"]["topbar_item_grouping"]["bbox_policy"] == (
        "topbar_controls_must_not_remain_icon_or_ocr_fragments"
    )
    controls = topbar["numbered_items"]
    assert len(controls) == 3
    assert all(item["display_only"] is True for item in controls)
    assert all(item["execute_binding_enabled"] is False for item in controls)
    assert all(item["bbox"]["w"] >= 48 for item in controls)
    assert all(item["bbox"]["h"] >= 36 for item in controls)
    assert all(item["bbox_policy"] == "topbar_control_hit_area_from_visual_or_text_fragments" for item in controls)
    assert controls[0]["bbox"]["x"] < inventory[0]["bbox"]["x"]


def test_classic_menu_ocr_line_is_split_into_anchored_menu_items() -> None:
    items = [
        {
            "number": "1.1",
            "item_id": "combined_menu",
            "label": "文件（F编辑(E）格式(O）查看(V)帮助(H)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 33, "w": 263, "h": 22},
        },
        {
            "number": "1.2",
            "item_id": "file_menu",
            "label": "文件(F)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 20, "y": 40, "w": 60, "h": 20},
        },
        {
            "number": "1.3",
            "item_id": "edit_menu",
            "label": "编辑(E)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 2426, "y": 2, "w": 52, "h": 32},
        },
        {
            "number": "1.4",
            "item_id": "window_close",
            "label": "×",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 2533, "y": 12, "w": 20, "h": 18},
        },
    ]

    normalized, report = two_stage._normalize_classic_menu_bar_items(
        items,
        region_bbox={"x": 0, "y": 0, "w": 2576, "h": 68},
    )

    assert report["applied"] is True
    assert report["menu_item_count"] == 5
    menu_items = [item for item in normalized if item["role"] == "menu_item"]
    assert {item["label"] for item in menu_items} == {"文件(F)", "编辑(E)", "格式(O)", "查看(V)", "帮助(H)"}
    assert all(12 <= item["bbox"]["x"] < 275 for item in menu_items)
    assert all(33 <= item["bbox"]["y"] < 55 for item in menu_items)
    ordered_menu_items = sorted(menu_items, key=lambda item: item["bbox"]["x"])
    assert ordered_menu_items[0]["bbox"]["x"] == 12
    assert all(
        left["bbox"]["x"] + left["bbox"]["w"] == right["bbox"]["x"]
        for left, right in zip(ordered_menu_items, ordered_menu_items[1:])
    )
    assert ordered_menu_items[-1]["bbox"]["x"] + ordered_menu_items[-1]["bbox"]["w"] == 275
    assert next(item for item in normalized if item["item_id"] == "combined_menu")["role"] == "menu_bar_evidence"
    assert next(item for item in normalized if item["item_id"] == "window_close")["bbox"]["x"] == 2533


def test_topbar_visual_refinement_does_not_move_menu_items_to_distant_window_controls(
    tmp_path,
    monkeypatch,
) -> None:
    image_path = tmp_path / "classic_menu.png"
    from PIL import Image

    Image.new("RGB", (2576, 120), "white").save(image_path)
    monkeypatch.setattr(
        two_stage,
        "_visual_small_control_boxes",
        lambda **_: [
            {"x": 65, "y": 6, "w": 31, "h": 28},
            {"x": 80, "y": 4, "w": 46, "h": 32},
            {"x": 2426, "y": 2, "w": 52, "h": 32},
            {"x": 2517, "y": 2, "w": 52, "h": 32},
        ],
    )
    items = [
        {
            "number": "1.1",
            "item_id": "combined_menu",
            "label": "文件（F编辑(E）格式(O）查看(V)帮助(H)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 12, "y": 33, "w": 263, "h": 22},
        },
        {
            "number": "1.2",
            "item_id": "file_menu",
            "label": "文件(F)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 20, "y": 40, "w": 60, "h": 20},
        },
        {
            "number": "1.3",
            "item_id": "edit_menu",
            "label": "编辑(E)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 80, "y": 40, "w": 61, "h": 20},
        },
        {
            "number": "1.4",
            "item_id": "format_menu",
            "label": "格式(O)",
            "role": "menu item",
            "item_type": "actionable",
            "bbox": {"x": 141, "y": 40, "w": 60, "h": 20},
        },
    ]

    refined, report = two_stage._refine_direct_region_small_controls(
        items,
        image_path=str(image_path),
        region_bbox={"x": 0, "y": 0, "w": 2576, "h": 68},
        region_family="top_bar",
    )

    menu_items = [item for item in refined if item["role"] == "menu_item"]
    assert len(menu_items) == 5
    assert {item["label"] for item in menu_items} == {"文件(F)", "编辑(E)", "格式(O)", "查看(V)", "帮助(H)"}
    assert len({item["number"] for item in refined}) == len(refined)
    assert max(item["bbox"]["x"] + item["bbox"]["w"] for item in menu_items) < 320
    assert min(item["bbox"]["y"] for item in menu_items) >= 23
    assert not any(pair["label"] in {"文件(F)", "编辑(E)", "格式(O)", "查看(V)", "帮助(H)"} for pair in report.get("pairs", []))
    assert not any(pair["to"]["x"] > 2000 for pair in report.get("pairs", []))


def test_topbar_hit_area_normalizer_preserves_readable_text_evidence() -> None:
    items = [
        {
            "number": "1.1",
            "item_id": "window_title",
            "label": "Untitled - Notepad",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 10, "y": 10, "w": 111, "h": 23},
        },
        {
            "number": "1.2",
            "item_id": "file_menu",
            "label": "File(F)",
            "role": "menu_item",
            "item_type": "actionable",
            "bbox": {"x": 20, "y": 40, "w": 60, "h": 20},
        },
    ]

    normalized, _ = two_stage._normalize_topbar_direct_items(
        items,
        region_bbox={"x": 0, "y": 0, "w": 800, "h": 68},
        region_family="top_bar",
        reason="test",
    )

    title = next(item for item in normalized if item["item_id"] == "window_title")
    assert title["bbox"] == {"x": 10, "y": 10, "w": 111, "h": 23}
    assert title.get("bbox_refinement") is None


def test_direct_visual_candidate_requires_meaningful_cross_axis_overlap() -> None:
    candidate = two_stage._nearest_compatible_direct_visual_candidate(
        {"x": 12, "y": 33, "w": 43, "h": 22},
        [{"x": 65, "y": 6, "w": 31, "h": 28}],
        horizontal=True,
    )

    assert candidate is None


def test_two_stage_keeps_multirow_topbar_controls_in_separate_full_height_rows() -> None:
    region = {
        "region_no": 1,
        "region_id": "structure_region_page_header",
        "label": "Top/header area",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 220},
        "item_ids": [f"row_{row}_control_{column}" for row in range(1, 4) for column in range(1, 4)],
    }
    items_by_id = {
        item_id: {
            "item_id": item_id,
            "label": item_id,
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 120 + (column - 1) * 140, "y": y, "w": 52, "h": 24},
            "review_only": True,
        }
        for row, y in ((1, 12), (2, 88), (3, 166))
        for column in range(1, 4)
        for item_id in [f"row_{row}_control_{column}"]
    }

    result = two_stage._stage2_numbering([region], items_by_id=items_by_id)

    topbar = result["regions"][0]
    assert all(item["bbox"]["h"] >= 30 for item in topbar["numbered_items"])
    assert all(item["bbox"]["y"] + item["bbox"]["h"] <= 220 for item in topbar["numbered_items"])
    strips = [group for group in topbar["subregion_groups"] if group["role"] == "topbar_control_strip"]
    assert len(strips) == 3
    assert [len(group["member_item_ids"]) for group in strips] == [3, 3, 3]
    assert [group["bbox"]["y"] for group in strips] == sorted(group["bbox"]["y"] for group in strips)


def test_stage2_suppresses_semantic_only_action_hypothesis_without_grounding_evidence() -> None:
    region = {
        "region_no": 3,
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 176, "y": 249, "w": 900, "h": 600},
        "item_ids": ["action_screen_9_up", "ocr_backed_button"],
    }
    items_by_id = {
        "action_screen_9_up": {
            "item_id": "action_screen_9_up",
            "label": "向上",
            "role": "button",
            "item_type": "actionable",
            "bbox": {"x": 451, "y": 257, "w": 32, "h": 33},
            "source": "screen_reading.ui_elements",
            "grounding_eligible": True,
            "metadata": {
                "evidence_level": "semantic_region_only",
                "uia_match": None,
            },
        },
        "ocr_backed_button": {
            "item_id": "ocr_backed_button",
            "label": "打开",
            "role": "button",
            "item_type": "actionable",
            "bbox": {"x": 520, "y": 280, "w": 64, "h": 36},
            "source": "screen_reading.ui_elements",
            "grounding_eligible": True,
            "metadata": {
                "evidence_level": "ocr_text_and_semantic_region",
                "uia_match": None,
            },
        },
    }

    result = two_stage._stage2_numbering([region], items_by_id=items_by_id)

    numbered_region = result["regions"][0]
    assert [item["item_id"] for item in numbered_region["numbered_items"]] == ["ocr_backed_button"]
    suppression = numbered_region["unsupported_semantic_action_suppression"]
    assert suppression["suppressed_count"] == 1
    assert suppression["suppressed_item_ids"] == ["action_screen_9_up"]
    assert suppression["reason"] == "semantic_action_without_ocr_uia_or_visual_grounding_evidence"


def test_stage2_preserves_suppressed_semantic_source_lineage_on_unique_factual_control() -> None:
    region = {
        "region_no": 1,
        "region_id": "structure_region_top_bar",
        "label": "Top bar",
        "bbox": {"x": 0, "y": 0, "w": 500, "h": 80},
        "item_ids": ["action_uia_file", "action_screen_help", "action_uia_help"],
    }
    items_by_id = {
        "action_uia_file": {
            "item_id": "action_uia_file",
            "label": "File",
            "role": "menu_item",
            "item_type": "actionable",
            "bbox": {"x": 150, "y": 23, "w": 50, "h": 28},
            "source": "uia",
            "grounding_eligible": True,
            "metadata": {"evidence_level": "uia_control"},
        },
        "action_screen_help": {
            "item_id": "action_screen_help",
            "label": "Help",
            "role": "menu_item",
            "item_type": "actionable",
            "bbox": {"x": 215, "y": 23, "w": 60, "h": 28},
            "source": "screen_reading.ui_elements",
            "grounding_eligible": False,
            "metadata": {
                "source_id": "element_h_170cdf28",
                "evidence_level": "semantic_region_only",
                "uia_match": None,
            },
        },
        "action_uia_help": {
            "item_id": "action_uia_help",
            "label": "Help",
            "role": "menu_item",
            "item_type": "actionable",
            "bbox": {"x": 216, "y": 23, "w": 59, "h": 28},
            "source": "uia",
            "grounding_eligible": True,
            "metadata": {
                "source_id": "uia_26_h",
                "evidence_level": "uia_control",
            },
        },
    }

    result = two_stage._stage2_numbering([region], items_by_id=items_by_id)

    numbered_region = result["regions"][0]
    help_item = next(item for item in numbered_region["numbered_items"] if item["item_id"] == "action_uia_help")
    assert help_item["merged_source_item_ids"] == [
        "action_uia_help",
        "uia_26_h",
        "action_screen_help",
        "element_h_170cdf28",
    ]
    alias_map = numbered_region["ownership_resolution"]["source_item_alias_map"]
    assert alias_map["element_h_170cdf28"] == "action_uia_help"


def test_stage2_demotes_uia_only_text_when_current_screenshot_crop_is_blank(tmp_path) -> None:
    image_path = tmp_path / "uia_current_pixels.png"
    from PIL import Image

    image = Image.new("RGB", (300, 180), "white")
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    draw.line((164, 50, 230, 50), fill="black", width=3)
    image.save(image_path)
    region = {
        "region_no": 1,
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 300, "h": 180},
        "item_ids": ["action_uia_stale", "action_uia_visible"],
    }
    items_by_id = {
        "action_uia_stale": {
            "item_id": "action_uia_stale",
            "label": "stale text",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 40, "y": 40, "w": 80, "h": 20},
            "source": "windows_uia.controls",
            "metadata": {"source_id": "uia_1_stale", "evidence_level": "uia_control"},
            "review_only": True,
        },
        "action_uia_visible": {
            "item_id": "action_uia_visible",
            "label": "visible text",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 160, "y": 40, "w": 80, "h": 20},
            "source": "windows_uia.controls",
            "metadata": {"source_id": "uia_2_visible", "evidence_level": "uia_control"},
            "review_only": True,
        },
    }

    result = two_stage._stage2_numbering(
        [region],
        items_by_id=items_by_id,
        image_path=str(image_path),
    )
    by_id = {item["item_id"]: item for item in result["regions"][0]["numbered_items"]}

    assert by_id["action_uia_stale"]["render_in_main_overlay"] is False
    assert by_id["action_uia_stale"]["visual_evidence_status"] == "blank_at_capture"
    assert by_id["action_uia_stale"]["demotion_reason"] == "uia_text_without_current_pixel_evidence"
    assert by_id["action_uia_visible"]["visual_evidence_status"] == "pixel_corroborated"
    assert by_id["action_uia_visible"].get("demotion_reason") != "uia_text_without_current_pixel_evidence"
    audit = result["regions"][0]["uia_text_pixel_corroboration"]
    assert audit["demoted_count"] == 1
    assert audit["demoted_item_ids"] == ["action_uia_stale"]


def test_item_display_hierarchy_respects_explicit_overlay_suppression() -> None:
    hierarchy = two_stage._item_display_hierarchy(
        {
            "item_id": "stale_uia_text",
            "label": "stale",
            "role": "text",
            "item_type": "text",
            "render_in_main_overlay": False,
            "demotion_reason": "uia_text_without_current_pixel_evidence",
        },
        [],
    )

    assert hierarchy["render_in_main_overlay"] is False
    assert hierarchy["display_layer"] == "child_evidence"
    assert hierarchy["demotion_reason"] == "uia_text_without_current_pixel_evidence"


def test_model_only_composer_cluster_is_demoted_inside_message_thread() -> None:
    items = [
        {
            "item_id": "element_message_input_area_abc",
            "label": "Message input area",
            "role": "message_bubble",
            "bbox": {"x": 200, "y": 700, "w": 300, "h": 80},
        },
        {
            "item_id": "action_screen_1_emoji-icon",
            "label": "Emoji icon",
            "role": "icon",
            "bbox": {"x": 220, "y": 720, "w": 20, "h": 20},
        },
        {
            "item_id": "action_screen_2_attachment-icon",
            "label": "Attachment icon",
            "role": "icon",
            "bbox": {"x": 260, "y": 720, "w": 20, "h": 20},
        },
    ]

    updated, audit = two_stage._demote_model_only_composer_cluster(
        items,
        stage1_5_role="message_thread",
    )

    assert audit["applied"] is True
    assert audit["demoted_count"] == 3
    assert all(item["render_in_main_overlay"] is False for item in updated)
    assert all(
        item["demotion_reason"] == "model_only_composer_cluster_outside_composer_region"
        for item in updated
    )


def test_subregion_group_without_renderable_current_members_is_suppressed() -> None:
    items = [
        {
            "item_id": "stale_uia_text",
            "bbox": {"x": 100, "y": 100, "w": 80, "h": 20},
            "render_in_main_overlay": False,
        }
    ]
    groups = [
        {
            "group_id": "stale_review_group",
            "role": "ungrouped_review_region",
            "bbox": {"x": 90, "y": 90, "w": 100, "h": 40},
            "member_item_ids": ["stale_uia_text", "missing_alias"],
        }
    ]

    reconciled, audit = two_stage._reconcile_subregion_group_display_evidence(items, groups)

    assert reconciled[0]["render_in_main_overlay"] is False
    assert reconciled[0]["demotion_reason"] == "group_without_renderable_current_evidence"
    assert audit["suppressed_group_ids"] == ["stale_review_group"]
    assert audit["unresolved_member_count"] == 1


def test_stage2_clips_numbered_items_to_parent_region_bbox():
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 100, "h": 60},
                "item_ids": ["overflowing_control"],
            }
        ],
        items_by_id={
            "overflowing_control": {
                "item_id": "overflowing_control",
                "label": "Overflowing control",
                "role": "icon_button",
                "item_type": "button",
                "bbox": {"x": 70, "y": 12, "w": 50, "h": 28},
                "review_only": True,
            }
        },
    )

    topbar = result["regions"][0]
    control = topbar["numbered_items"][0]
    assert control["bbox"] == {"x": 70, "y": 12, "w": 30, "h": 28}
    assert control["bbox_boundary_clip"]["reason"] == "numbered_item_must_not_extend_outside_parent_region"
    assert control["parent_region_id"] == "structure_region_main_content"
    assert control["parent_region_bbox"] == {"x": 0, "y": 0, "w": 100, "h": 60}
    assert control["parent_boundary_relation"]["relation"] == "child_of_structure_region"
    assert (
        control["parent_boundary_relation"]["child_bbox_policy"]
        == "must_be_inside_parent_region_after_boundary_enforcement"
    )
    assert control["parent_boundary_relation"]["execute_binding_enabled"] is False
    assert topbar["region_content_boundary"]["clipped_numbered_item_count"] == 1
    assert topbar["region_content_boundary"]["parent_region_id"] == "structure_region_main_content"
    assert topbar["region_content_boundary"]["annotated_numbered_item_count"] == 1


def test_stage2_clips_subregion_groups_to_parent_region_bbox():
    _items, groups, boundary = two_stage._enforce_region_content_boundary(
        [],
        [
            {
                "group_id": "media_row",
                "label": "Media row",
                "bbox": {"x": -20, "y": 8, "w": 150, "h": 44},
                "display_only": True,
            }
        ],
        region_bbox={"x": 0, "y": 0, "w": 100, "h": 60},
        region_id="structure_region_primary_area",
        region_label="Primary area",
    )

    assert groups[0]["bbox"] == {"x": 0, "y": 8, "w": 100, "h": 44}
    assert groups[0]["bbox_boundary_clip"]["reason"] == "subregion_group_must_not_extend_outside_parent_region"
    assert groups[0]["parent_region_id"] == "structure_region_primary_area"
    assert groups[0]["parent_region_label"] == "Primary area"
    assert groups[0]["parent_boundary_relation"]["relation"] == "child_group_of_structure_region"
    assert (
        groups[0]["parent_boundary_relation"]["sibling_overlap_policy"]
        == "non_parent_overlap_requires_boundary_review"
    )
    assert boundary["clipped_subregion_group_count"] == 1
    assert boundary["annotated_subregion_group_count"] == 1


def test_stage2_rejects_child_content_without_parent_overlap():
    items, groups, boundary = two_stage._enforce_region_content_boundary(
        [
            {
                "number": "1.1",
                "item_id": "sibling_button",
                "label": "Sibling button",
                "role": "button",
                "bbox": {"x": 160, "y": 20, "w": 40, "h": 24},
                "display_only": True,
            }
        ],
        [
            {
                "group_id": "sibling_group",
                "label": "Sibling group",
                "bbox": {"x": 150, "y": 8, "w": 80, "h": 44},
                "display_only": True,
            }
        ],
        region_bbox={"x": 0, "y": 0, "w": 100, "h": 60},
        region_id="structure_region_left_nav",
        region_label="Left nav",
    )

    assert items[0]["bbox"] == {}
    assert items[0]["raw_bbox_before_boundary"] == {"x": 160, "y": 20, "w": 40, "h": 24}
    assert items[0]["bbox_boundary_reject"]["reason"] == "numbered_item_outside_parent_region"
    assert items[0]["parent_boundary_relation"]["child_scope"] == "outside_parent_rejected"
    assert items[0]["parent_boundary_relation"]["inside_parent_after_enforcement"] is False
    assert items[0]["review_required"] is True
    assert items[0]["candidate_only"] is True
    assert groups[0]["bbox"] == {}
    assert groups[0]["bbox_boundary_reject"]["reason"] == "subregion_group_outside_parent_region"
    assert boundary["rejected_numbered_item_count"] == 1
    assert boundary["rejected_subregion_group_count"] == 1
    assert boundary["child_scope_policy"] == (
        "children_may_only_overlap_when_the_parent_region_contains_them_after_enforcement"
    )


def test_primary_content_orphan_items_get_internal_review_region():
    groups = two_stage._ensure_primary_items_have_subregion_parent(
        region={
            "region_id": "structure_region_primary_area",
            "bbox": {"x": 0, "y": 0, "w": 420, "h": 320},
        },
        numbered_items=[
            {
                "number": "1.1",
                "item_id": "contained_title",
                "label": "Contained title",
                "role": "text",
                "bbox": {"x": 40, "y": 32, "w": 140, "h": 24},
            },
            {
                "number": "1.2",
                "item_id": "orphan_button",
                "label": "Floating button",
                "role": "button",
                "bbox": {"x": 260, "y": 210, "w": 96, "h": 32},
            },
            {
                "number": "1.3",
                "item_id": "orphan_text_1",
                "label": "Floating text 1",
                "role": "text",
                "bbox": {"x": 260, "y": 248, "w": 120, "h": 22},
            },
            {
                "number": "1.4",
                "item_id": "orphan_text_2",
                "label": "Floating text 2",
                "role": "text",
                "bbox": {"x": 260, "y": 276, "w": 120, "h": 22},
            },
            {
                "number": "1.5",
                "item_id": "orphan_text_3",
                "label": "Floating text 3",
                "role": "text",
                "bbox": {"x": 260, "y": 304, "w": 120, "h": 22},
            },
        ],
        groups=[
            {
                "group_id": "section_parent_1",
                "label": "Section",
                "role": "section_parent",
                "bbox": {"x": 20, "y": 20, "w": 200, "h": 80},
                "member_item_ids": [],
                "member_numbers": [],
                "display_only": True,
            }
        ],
    )

    section = next(group for group in groups if group["group_id"] == "section_parent_1")
    assert "contained_title" in section["member_item_ids"]
    assert section["membership_repairs"][0]["reason"] == "item_bbox_inside_group_bbox_but_missing_member_link"
    orphan_group = next(group for group in groups if group["role"] == "ungrouped_review_region")
    assert orphan_group["member_item_ids"] == ["orphan_button", "orphan_text_1", "orphan_text_2", "orphan_text_3"]
    assert orphan_group["review_only"] is True
    assert orphan_group["candidate_only"] is True
    assert orphan_group["execute_binding_enabled"] is False
    assert orphan_group["bbox"]["x"] <= 260
    assert orphan_group["bbox"]["x"] + orphan_group["bbox"]["w"] >= 356


def test_membership_repair_expands_parent_bbox_to_contain_near_boundary_child():
    groups = two_stage._ensure_primary_items_have_subregion_parent(
        region={
            "region_id": "structure_region_primary_area",
            "bbox": {"x": 0, "y": 0, "w": 500, "h": 300},
        },
        numbered_items=[
            {
                "number": "1.1",
                "item_id": "near_edge_title",
                "label": "Near edge title",
                "role": "text",
                "bbox": {"x": 100, "y": 60, "w": 202, "h": 24},
            }
        ],
        groups=[
            {
                "group_id": "list_group_1",
                "label": "List",
                "role": "list_group",
                "bbox": {"x": 100, "y": 40, "w": 200, "h": 100},
                "member_item_ids": [],
                "member_numbers": [],
                "display_only": True,
            }
        ],
    )

    repaired = groups[0]
    assert repaired["member_item_ids"] == ["near_edge_title"]
    assert repaired["bbox"] == {"x": 100, "y": 40, "w": 202, "h": 100}
    assert repaired["membership_repairs"][0]["bbox_expanded"] is True














def test_stage1_parallel_vertical_lanes_share_main_rough_top_and_bottom_boundaries():
    regions = [
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "rough_bbox": {"x": 0, "y": 0, "w": 820, "h": 166},
            "bbox": {"x": 0, "y": 0, "w": 820, "h": 166},
            "precise_bbox": {"x": 0, "y": 0, "w": 820, "h": 166},
        },
        {
            "region_id": "structure_region_left_sidebar",
            "zone_id": "left_sidebar",
            "rough_bbox": {"x": 16, "y": 99, "w": 238, "h": 925},
            "bbox": {"x": 16, "y": 166, "w": 238, "h": 858},
            "precise_bbox": {"x": 16, "y": 166, "w": 238, "h": 858},
        },
        {
            "region_id": "structure_region_primary_area",
            "zone_id": "primary_area",
            "rough_bbox": {"x": 0, "y": 101, "w": 820, "h": 939},
            "bbox": {"x": 254, "y": 166, "w": 375, "h": 874},
            "precise_bbox": {"x": 254, "y": 166, "w": 375, "h": 874},
        },
        {
            "region_id": "structure_region_right_sidebar",
            "zone_id": "right_sidebar",
            "rough_bbox": {"x": 629, "y": 141, "w": 191, "h": 609},
            "bbox": {"x": 629, "y": 166, "w": 191, "h": 874},
            "precise_bbox": {"x": 629, "y": 166, "w": 191, "h": 874},
        },
    ]

    two_stage._align_vertical_sibling_lanes_to_main_rough_bounds(regions)

    vertical = [region for region in regions if region["zone_id"] != "top_bar"]
    assert {(region["bbox"]["y"], region["bbox"]["h"]) for region in vertical} == {(101, 939)}
    left = next(region for region in regions if region["zone_id"] == "left_sidebar")
    main = next(region for region in regions if region["zone_id"] == "primary_area")
    right = next(region for region in regions if region["zone_id"] == "right_sidebar")
    assert left["bbox"] == {"x": 0, "y": 101, "w": 254, "h": 939}
    assert main["bbox"] == {"x": 254, "y": 101, "w": 375, "h": 939}
    assert right["bbox"] == {"x": 629, "y": 101, "w": 191, "h": 939}
    assert all(
        region["coordinate_validation"]["shared_vertical_lane"]["source_region_id"]
        == "structure_region_primary_area"
        for region in vertical
    )


def test_stage1_visual_separator_recovers_narrow_left_icon_rail(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "narrow_rail.png"
    image = Image.new("RGB", (1000, 700), (244, 244, 244))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 95, 699), fill=(250, 250, 250))
    draw.line((96, 70, 96, 699), fill=(80, 80, 80), width=2)
    image.save(image_path)
    items = {
        f"icon_{index}": {
            "item_id": f"icon_{index}",
            "label": f"icon {index}",
            "role": "text",
            "bbox": {"x": 22, "y": y, "w": 24, "h": 24},
        }
        for index, y in enumerate((140, 210, 280), start=1)
    }
    items["content"] = {
        "item_id": "content",
        "label": "content",
        "role": "content",
        "bbox": {"x": 120, "y": 100, "w": 820, "h": 540},
    }
    corrected = {"primary_area": list(items)}

    two_stage._split_narrow_left_rail_from_visual_separator(
        corrected,
        items_by_id=items,
        screen_size={"width": 1000, "height": 700},
        source_image_path=str(image_path),
    )

    assert corrected["left_nav"] == ["icon_1", "icon_2", "icon_3"]
    assert corrected["primary_area"] == ["content"]
    assert all(items[item_id]["metadata"]["visual_left_rail_boundary_x"] == 96 for item_id in corrected["left_nav"])


def test_stage1_visual_separator_does_not_create_rail_without_persistent_edge(tmp_path):
    from PIL import Image

    image_path = tmp_path / "no_rail.png"
    Image.new("RGB", (1000, 700), (244, 244, 244)).save(image_path)
    items = {
        f"text_{index}": {
            "item_id": f"text_{index}",
            "label": f"text {index}",
            "role": "text",
            "bbox": {"x": 24, "y": y, "w": 60, "h": 24},
        }
        for index, y in enumerate((140, 210, 280), start=1)
    }
    corrected = {"primary_area": list(items)}

    two_stage._split_narrow_left_rail_from_visual_separator(
        corrected,
        items_by_id=items,
        screen_size={"width": 1000, "height": 700},
        source_image_path=str(image_path),
    )

    assert "left_nav" not in corrected
    assert corrected["primary_area"] == list(items)


def test_fusion_boxes_enforce_parent_region_boundary_at_display_layer():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
            }
        ],
        [
            {
                "region_id": "structure_region_top_bar",
                "subregion_groups": [
                    {
                        "group_id": "toolbar_group_1",
                        "label": "Toolbar",
                        "role": "toolbar_group",
                        "bbox": {"x": 90, "y": 4, "w": 60, "h": 36},
                        "parent_region_id": "structure_region_top_bar",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
                    }
                ],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Overflow button",
                        "role": "control",
                        "bbox": {"x": 100, "y": 8, "w": 48, "h": 24},
                        "parent_region_id": "structure_region_top_bar",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
                    }
                ],
            }
        ],
    )

    group = next(item for item in result["fused_review_boxes"] if item["box_type"] == "subregion_group")
    control = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert group["bbox"] == {"x": 90, "y": 4, "w": 30, "h": 36}
    assert control["bbox"] == {"x": 100, "y": 8, "w": 20, "h": 24}
    assert group["parent_region_id"] == "structure_region_top_bar"
    assert control["parent_region_id"] == "structure_region_top_bar"
    assert group["fusion_boundary_clip"]["reason"] == "fused_child_box_must_not_extend_outside_parent_region"
    assert control["fusion_boundary_clip"]["reason"] == "fused_child_box_must_not_extend_outside_parent_region"
    assert group["review_required"] is True
    assert control["review_required"] is True
    assert result["region_content_boundary_summary"]["clipped_fused_child_count"] == 2
    assert result["region_content_boundary_summary"]["missing_parent_child_count"] == 0
    assert result["region_content_boundary_summary"]["outside_parent_after_clip_count"] == 0
    assert result["region_content_boundary_summary"]["boundary_contract_status"] == "needs_human_review"
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["clipped_fused_child_count"]


def test_fusion_boxes_do_not_render_child_without_parent_overlap():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_left_nav",
                "label": "Left nav",
                "bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
            }
        ],
        [
            {
                "region_id": "structure_region_left_nav",
                "subregion_groups": [],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Wrong column item",
                        "role": "button",
                        "bbox": {"x": 180, "y": 20, "w": 60, "h": 32},
                        "parent_region_id": "structure_region_left_nav",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
                    }
                ],
            }
        ],
    )

    child = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert child["bbox"] == {}
    assert child["fusion_boundary_review"]["reason"] == "fused_child_box_outside_parent_region"
    assert two_stage._parent_bounded_display_bbox(child) is None
    assert result["region_content_boundary_summary"]["outside_parent_after_clip_count"] == 1
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["outside_parent_after_clip_count"]


def test_fusion_boxes_suppress_non_parent_sibling_group_overlap():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary area",
                "bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "latest_news_section",
                        "label": "Latest News",
                        "role": "section_parent",
                        "bbox": {"x": 80, "y": 120, "w": 250, "h": 190},
                        "member_item_ids": ["news_title"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
                    },
                    {
                        "group_id": "wide_media_row",
                        "label": "Wide media row",
                        "role": "media_card_group",
                        "bbox": {"x": 240, "y": 190, "w": 250, "h": 190},
                        "member_item_ids": ["media_card"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
                    },
                ],
                "numbered_items": [],
            }
        ],
    )

    media_row = next(item for item in result["fused_review_boxes"] if item["number"] == "wide_media_row")
    assert media_row["render_in_main_overlay"] is False
    assert media_row["candidate_only"] is True
    assert media_row["sibling_overlap_review"]["reason"] == "non_parent_sibling_group_overlap"
    assert result["region_content_boundary_summary"]["sibling_non_parent_overlap_count"] == 1
    assert "sibling_non_parent_overlap_count" in result["region_content_boundary_summary"]["promotion_blockers"]


def test_downstream_normalization_preserves_distinct_overlapping_table_rows():
    reviewed, records = two_stage._mark_non_parent_sibling_group_overlaps(
        [
            {
                "group_id": "table_row_1",
                "label": "Program Files",
                "role": "table_row",
                "bbox": {"x": 180, "y": 524, "w": 617, "h": 32},
            },
            {
                "group_id": "table_row_2",
                "label": "Program Files (x86)",
                "role": "table_row",
                "bbox": {"x": 180, "y": 545, "w": 617, "h": 32},
            },
        ]
    )

    assert records == []
    assert all(group.get("render_in_main_overlay") is not False for group in reviewed)


def test_fusion_boxes_missing_parent_region_blocks_promotion():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 200, "h": 120},
            }
        ],
        [
            {
                "region_id": "structure_region_main_content",
                "subregion_groups": [],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Orphan child",
                        "role": "text",
                        "bbox": {"x": 20, "y": 20, "w": 80, "h": 24},
                    }
                ],
            }
        ],
    )

    child = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert child["review_required"] is True
    assert child["candidate_only"] is True
    assert child["fusion_boundary_review"]["reason"] == "fused_child_box_missing_parent_region"
    assert result["region_content_boundary_summary"]["missing_parent_child_count"] == 1
    assert result["region_content_boundary_summary"]["boundary_contract_status"] == "needs_human_review"
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["missing_parent_child_count"]


def test_overlay_label_layout_keeps_long_labels_inside_bbox_width():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (180, 80), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 40, "y": 24, "w": 56, "h": 24}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "3.17 timestamp -> msg_2",
        font=font,
        max_width=bbox["w"],
    )

    assert layout is not None
    assert layout["rect"][0] >= bbox["x"]
    assert layout["rect"][2] <= bbox["x"] + bbox["w"]
    assert "timestamp" not in layout["text"]


def test_overlay_label_layout_keeps_label_rect_inside_bbox():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 60, "y": 80, "w": 72, "h": 28}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "3.84 button",
        font=font,
        max_width=bbox["w"],
    )

    assert layout is not None
    assert layout["rect"][0] >= bbox["x"]
    assert layout["rect"][1] >= bbox["y"]
    assert layout["rect"][2] <= bbox["x"] + bbox["w"]
    assert layout["rect"][3] <= bbox["y"] + bbox["h"]


def test_overlay_label_layout_keeps_labels_inside_canvas_right_edge():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 84, "y": 18, "w": 12, "h": 20}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "2.13 control",
        font=font,
        max_width=48,
    )

    assert layout is not None
    assert layout["rect"][2] <= image.width


def test_learning_recognition_pipeline_exposes_two_stage_overlay_in_page_details(tmp_path):
    image_path = tmp_path / "learning_screen.png"
    from PIL import Image

    Image.new("RGB", (640, 420), "white").save(image_path)
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "image_path": str(image_path),
        "screen_size": {"width": 640, "height": 420},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "candidate_id": "left_nav_home",
                        "label": "Home icon",
                        "role": "nav_rail_icon_review_only",
                        "bbox": {"x": 20, "y": 120, "w": 24, "h": 24},
                    },
                    {
                        "candidate_id": "music_card",
                        "label": "Energy album card",
                        "role": "news_card",
                        "bbox": {"x": 120, "y": 170, "w": 240, "h": 160},
                        "metadata": {
                            "text_lines": [
                                {"label": "能量充电", "bbox": {"x": 160, "y": 250, "w": 120, "h": 28}},
                            ]
                        },
                    },
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="apple_music_home",
        summary="Apple Music home screen.",
        grounding_adapter=None,
    )

    page_details = result["learning_draft"]["page_details"]
    two_stage = page_details["two_stage_understanding"]
    assert two_stage["stage1_structure"]["region_count"] >= 1
    assert two_stage["stage1_region_localization"]["localized_region_count"] >= 1
    assert two_stage["stage2_numbering"]["numbered_item_count"] >= 2
    fusion_status = page_details["pipeline_audit"]["precise_understanding_fusion_status"]
    assert fusion_status["contract_version"] == "learn_precise_understanding_fusion_status_report_v1"
    assert fusion_status["compiled_overlay_path"]
    assert Path(fusion_status["compiled_overlay_path"]).exists()
    assert fusion_status["summary"]["structure_region_count"] == two_stage["stage1_structure"]["region_count"]
    assert fusion_status["summary"]["stage1_localized_region_count"] == two_stage["stage1_region_localization"]["localized_region_count"]
    assert fusion_status["summary"]["numbered_item_count"] == two_stage["stage2_numbering"]["numbered_item_count"]


def test_learning_recognition_pipeline_outputs_reviewable_draft(tmp_path):
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1280, "height": 720},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Latest News",
                        "bbox": {"x": 80, "y": 540, "w": 260, "h": 48},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                        "patterns": ["Invoke"],
                    }
                ]
            },
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        assert item["label"] == "Search"
        return {
            "screen_point": {"x": 1024, "y": 158},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
            "debug": {"roi_contract": roi_crop["contract_version"]},
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="python_homepage",
        summary="Python homepage search and content regions.",
        grounding_adapter=fake_grounding_adapter,
    )

    assert result["contract_version"] == "learn_recognition_pipeline_result_v1"
    assert result["status"] == "draft_ready"
    assert result["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert result["layout_graph"]["node_count"] == 2
    assert result["layout_graph"]["zones"]["page_header"]["item_ids"] == ["uia_control_1"]
    assert result["layout_graph"]["zones"]["main_content"]["item_ids"] == ["ocr_text_1"]
    assert result["locator_task_cards"]["contract_version"] == "learn_locator_task_cards_v1"
    assert result["locator_task_cards"]["display_only"] is True
    assert result["locator_task_cards"]["execute_binding_enabled"] is False
    search_card = next(
        item for item in result["locator_task_cards"]["cards"] if item["source_item_id"] == "uia_control_1"
    )
    assert search_card["target_visible_text"] == "Search"
    assert search_card["target_role"] == "button"
    assert search_card["evidence_level"] == "uia_control"
    assert search_card["uia_control_type"] == "Button"
    assert search_card["rough_bbox_policy"] == "hint_only_can_be_replaced"
    assert search_card["interaction_target"].startswith("click the visible button body")
    assert "boundary_definition" in search_card
    assert "clickable_area_hint" in search_card
    assert "final submit" in search_card["must_not_click"]
    assert search_card["expected_precise_output"] == "tight visible target bbox and safe interior point in full screenshot coordinates"
    assert result["classification"]["summary"]["accepted_for_grounding_count"] == 1
    assert result["classification"]["summary"]["rejected_non_actionable_count"] == 1
    assert result["learning_draft"]["contract_version"] == "learning_template_draft_v1"
    assert result["learning_draft"]["execute_binding_enabled"] is False
    assert result["learning_draft"]["artifact_is_authorization"] is False
    assert result["learning_draft"]["final_submit_forbidden"] is True
    assert result["learning_draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert result["learning_draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert result["learning_draft"]["page_details"]["contract_version"] == "learning_draft_page_details_v1"
    assert result["learning_draft"]["page_details"]["inventory_summary"]["screen_inventory_count"] == 2
    assert result["learning_draft"]["page_details"]["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert result["learning_draft"]["page_details"]["layout_graph"]["zone_count"] >= 2
    assert result["learning_draft"]["page_details"]["locator_task_cards"]["contract_version"] == "learn_locator_task_cards_v1"
    assert result["learning_draft"]["page_details"]["locator_task_cards"]["cards"][0]["source_item_id"]
    audit = result["learning_draft"]["page_details"]["pipeline_audit"]
    assert audit["contract_version"] == "learning_draft_pipeline_audit_v1"
    assert audit["display_only"] is True
    assert audit["execute_binding_enabled"] is False
    assert audit["layout_cleanup"]["input_count"] == 2
    assert audit["layout_cleanup"]["output_count"] == 2
    assert audit["layout_cleanup"]["suppression_reason_counts"] == {}
    assert audit["grounding_eligibility_gate"]["attempted"] == 2
    assert audit["grounding_eligibility_gate"]["eligible"] == 1
    assert audit["grounding_eligibility_gate"]["blocked"] == 1
    assert audit["grounding_eligibility_gate"]["not_accuracy"] is True
    assert audit["roi_grounding"]["validation_count"] == 1
    assert audit["roi_grounding"]["valid_candidate_count"] == 1
    assert [item["label"] for item in result["learning_draft"]["page_details"]["review_only_regions"]] == ["Latest News"]
    assert [item["label"] for item in result["learning_draft"]["page_details"]["grounding_candidates"]] == ["Search"]
    assert "click_target" in result["learning_draft"]["operation_skills"]
    assert "observe_screen" in result["learning_draft"]["operation_skills"]
    assert result["learning_draft"]["gate_contracts"][0]["contract_id"] == "pre_click_decision_v1"
    assert result["learning_draft"]["action_templates"][0]["target_region_id"] == "region_1"
    assert result["learning_draft"]["action_templates"][0]["requires_gate"] is True
    assert result["learning_draft"]["action_templates"][0]["execute_binding_enabled"] is False

    draft_path = tmp_path / "artifacts" / "learning-recognition" / "draft.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(json.dumps(result["learning_draft"], ensure_ascii=False), encoding="utf-8")

    review = load_learning_draft_review(draft_path, project_root=tmp_path)

    assert review["draft_only"] is True
    assert review["execute_binding_enabled"] is False
    assert review["final_submit_forbidden"] is True
    assert review["draft"]["state_guess"] == "python_homepage"
    assert [item["label"] for item in review["draft"]["regions"]] == ["Search", "Latest News"]
    assert review["draft"]["regions"][1]["candidate_only"] is True
    assert review["draft"]["regions"][1]["execute_binding_enabled"] is False
    assert review["draft"]["action_templates"][0]["click_point"] == {"x": 1024, "y": 158}
    assert review["draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert review["draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert review["draft"]["gate_contracts"][0]["contract_id"] == "pre_click_decision_v1"
    assert review["draft"]["page_details"]["review_only_regions"][0]["label"] == "Latest News"
    assert review["draft"]["page_details"]["pipeline_audit"]["layout_cleanup"]["input_count"] == 2


def test_learning_recognition_pipeline_keeps_observe_only_regions_visible_without_actions():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1280, "height": 720},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "candidate_id": "apple_music_album_card_1",
                        "label": "Apple Music album card",
                        "role": "content_card",
                        "bbox": {"x": 120, "y": 260, "w": 240, "h": 180},
                    }
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="apple_music_home",
        summary="Apple Music home screen.",
        grounding_adapter=None,
    )

    draft = result["learning_draft"]
    assert result["status"] == "needs_human_review"
    assert result["raw_screen_inventory"]
    assert [item["label"] for item in draft["page_details"]["review_only_regions"]] == ["Apple Music album card"]
    assert [item["label"] for item in draft["regions"]] == ["Apple Music album card"]
    assert draft["regions"][0]["candidate_only"] is True
    assert draft["regions"][0]["requires_human_review"] is True
    assert draft["regions"][0]["execute_binding_enabled"] is False
    assert draft["regions"][0]["artifact_is_authorization"] is False
    assert draft["regions"][0]["grounding_status"] == "review_only"
    assert draft["action_templates"] == []


def test_learning_recognition_pipeline_restores_local_grounding_into_draft():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1200, "height": 800},
        "sources": {
            "omniparser": {
                "parsed_content_list": [
                    {
                        "type": "icon",
                        "content": "Search",
                        "bbox": [500, 300, 600, 340],
                        "interactivity": True,
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        assert roi_crop["grounding_request"]["contract_version"] == "learn_grounding_request_v1"
        return {
            "coordinate_space": "uground_0_999",
            "raw_output": "(500, 500)",
            "screen_bbox": item["bbox"],
            "evidence": {
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="python_homepage",
        summary="Search is available.",
        grounding_adapter=fake_grounding_adapter,
    )

    assert result["status"] == "draft_ready"
    assert result["grounding_validations"][0]["checks"]["coordinate_transform_replay"] is True
    assert result["grounding_validations"][0]["screen_point"] == {"x": 550, "y": 320}
    assert result["learning_draft"]["action_templates"][0]["click_point"] == {"x": 550, "y": 320}
    assert result["learning_draft"]["action_templates"][0]["low_level_action_type"] == "click"
    assert result["learning_draft"]["verification_rules"]


def test_learning_recognition_pipeline_marks_form_fields_as_draft_fill_actions():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1000, "height": 700},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Search the docs before downloading.",
                        "bbox": {"x": 80, "y": 220, "w": 360, "h": 32},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Email",
                        "control_type": "Edit",
                        "bbox": {"x": 100, "y": 220, "w": 360, "h": 40},
                        "patterns": ["Value"],
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        return {
            "screen_point": {"x": 280, "y": 240},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="simple_form",
        summary="A form with one email input.",
        grounding_adapter=fake_grounding_adapter,
    )

    action = result["learning_draft"]["action_templates"][0]
    assert action["semantic_action"] == "fill_field"
    assert action["low_level_action_type"] == "input"
    assert "type_text" in result["learning_draft"]["operation_skills"]
    assert action["requires_gate"] is True
    assert action["execute_binding_enabled"] is False
    assert result["learning_draft"]["safety"]["execute_binding_enabled"] is False


def test_learning_recognition_pipeline_draft_can_generate_non_executable_pathgraph_candidate(tmp_path):
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1000, "height": 700},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Search the docs before downloading.",
                        "bbox": {"x": 80, "y": 220, "w": 360, "h": 32},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 500, "y": 120, "w": 96, "h": 36},
                        "patterns": ["Invoke"],
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        return {
            "screen_point": {"x": 548, "y": 138},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="search_page",
        summary="A search page with one validated action.",
        grounding_adapter=fake_grounding_adapter,
    )
    draft_path = tmp_path / "artifacts" / "learning-recognition" / "draft.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(json.dumps(result["learning_draft"], ensure_ascii=False), encoding="utf-8")

    candidate = build_pathgraph_candidate_from_review(draft_path, {}, project_root=tmp_path)

    assert candidate["validation_status"] == "passed_candidate"
    assert candidate["artifact_is_authorization"] is False
    assert candidate["execute_binding_enabled"] is False
    assert candidate["final_submit_forbidden"] is True
    assert candidate["summary"]["blocker_count"] >= 1
    assert candidate["summary"]["verification_rule_count"] >= 1
    wrapper = json.loads((tmp_path / candidate["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert wrapper["validation_status"] == "passed_candidate"
    assert wrapper["execute_binding_enabled"] is False
    graph = json.loads((tmp_path / candidate["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    interface_map = json.loads((tmp_path / candidate["interface_map_candidate_path"]).read_text(encoding="utf-8"))
    for artifact in (graph, interface_map):
        assert artifact["page_details"]["contract_version"] == "learning_draft_page_details_v1"
        assert artifact["page_details"]["display_only"] is True
        assert artifact["page_details"]["candidate_only"] is True
        assert artifact["page_details"]["execute_binding_enabled"] is False
        assert artifact["page_details"]["inventory_summary"]["screen_inventory_count"] == 2
        assert artifact["page_details"]["review_only_regions"][0]["label"] == "Search the docs before downloading."
        assert artifact["page_details"]["grounding_candidates"][0]["label"] == "Search"
        assert artifact["page_details"]["pipeline_audit"]["contract_version"] == "learning_draft_pipeline_audit_v1"
        assert artifact["page_details"]["pipeline_audit"]["grounding_eligibility_gate"]["eligible"] == 1


def test_learning_recognition_pipeline_without_grounding_adapter_needs_review():
    observe_bundle = {
        "screen_size": {"width": 800, "height": 600},
        "sources": {
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 100, "y": 100, "w": 80, "h": 32},
                        "patterns": ["Invoke"],
                    }
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="search_page",
        summary="Search page.",
    )

    assert result["status"] == "needs_grounding_adapter"
    assert result["learning_draft"]["regions"] == []
    assert result["grounding_validations"] == []
    assert result["learning_draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert result["learning_draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert result["safety"]["execute_binding_enabled"] is False


def test_two_stage_groups_repeated_text_columns_into_complete_parent_modules() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "bbox": {"x": 0, "y": 200, "w": 1200, "h": 700},
    }
    items = []
    for column, x in enumerate((100, 350, 600, 850), start=1):
        for line, (y, width, label) in enumerate(
            (
                (300, 100, f"Heading {column}"),
                (340, 180, f"Body {column} first line"),
                (370, 190, f"Body {column} second line"),
                (410, 150, f"Action {column}"),
            ),
            start=1,
        ):
            items.append(
                {
                    "number": f"1.{column}.{line}",
                    "item_id": f"column_{column}_line_{line}",
                    "label": label,
                    "role": "heading" if line == 1 else "text",
                    "bbox": {"x": x, "y": y, "w": width, "h": 24},
                }
            )

    groups = two_stage._tile_card_parent_groups(region=region, numbered_items=items)

    columns = [group for group in groups if group.get("source") == "stage2_repeated_text_column_parent_grouping"]
    assert len(columns) == 4
    assert all(len(group["member_item_ids"]) == 4 for group in columns)
    assert all(group["bbox"]["y"] <= 282 for group in columns)
    assert all(group["bbox"]["h"] >= 170 for group in columns)


def test_two_stage_merges_touching_tile_parent_fragments_in_same_content_column() -> None:
    groups = [
        {
            "group_id": "column_a_top",
            "label": "Get Started",
            "role": "tile_card_parent",
            "bbox": {"x": 680, "y": 650, "w": 183, "h": 92},
            "member_numbers": ["3.1"],
            "member_item_ids": ["column_a_top"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "column_a_middle",
            "label": "Beginner guide",
            "role": "tile_card_parent",
            "bbox": {"x": 680, "y": 734, "w": 264, "h": 57},
            "member_numbers": ["3.2"],
            "member_item_ids": ["column_a_middle"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "column_a_bottom",
            "label": "Python tutorial",
            "role": "tile_card_parent",
            "bbox": {"x": 678, "y": 793, "w": 238, "h": 59},
            "member_numbers": ["3.3"],
            "member_item_ids": ["column_a_bottom"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "column_b",
            "label": "Download",
            "role": "tile_card_parent",
            "bbox": {"x": 969, "y": 684, "w": 255, "h": 144},
            "member_numbers": ["3.4"],
            "member_item_ids": ["column_b"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
    ]

    merged = two_stage._merge_adjacent_tile_card_parent_fragments(groups)

    assert len(merged) == 2
    column_a = next(group for group in merged if "column_a_top" in group["member_item_ids"])
    assert set(column_a["member_item_ids"]) == {"column_a_top", "column_a_middle", "column_a_bottom"}
    assert column_a["bbox"] == {"x": 678, "y": 650, "w": 266, "h": 202}
    assert column_a["adjacent_fragment_merge_policy"] == "same_column_strong_overlap_with_touching_vertical_spans"


def test_suppressed_overlap_group_cannot_suppress_a_third_active_group() -> None:
    reviewed, records = two_stage._mark_non_parent_sibling_group_overlaps(
        [
            {
                "group_id": "middle_priority",
                "role": "media_card_group",
                "bbox": {"x": 40, "y": 0, "w": 100, "h": 100},
            },
            {
                "group_id": "highest_priority",
                "role": "section_parent",
                "bbox": {"x": 0, "y": 0, "w": 100, "h": 100},
            },
            {
                "group_id": "independent_low_priority",
                "role": "ungrouped_review_region",
                "bbox": {"x": 100, "y": 0, "w": 100, "h": 100},
            },
        ]
    )

    by_id = {group["group_id"]: group for group in reviewed}
    assert by_id["middle_priority"]["render_in_main_overlay"] is False
    assert by_id["independent_low_priority"].get("render_in_main_overlay") is not False
    assert [record["group_id"] for record in records] == ["middle_priority"]


def test_two_stage_merges_same_column_fragments_after_attached_title_expands_overlap() -> None:
    groups = [
        {
            "group_id": "column_a_top",
            "label": "Get Started",
            "role": "tile_card_parent",
            "bbox": {"x": 680, "y": 650, "w": 183, "h": 92},
            "member_numbers": ["3.1"],
            "member_item_ids": ["column_a_top"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "column_a_body",
            "label": "Beginner guide",
            "role": "tile_card_parent",
            "bbox": {"x": 678, "y": 702, "w": 266, "h": 150},
            "member_numbers": ["3.2"],
            "member_item_ids": ["column_a_body"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
    ]

    merged = two_stage._merge_adjacent_tile_card_parent_fragments(groups)

    assert len(merged) == 1
    assert merged[0]["bbox"] == {"x": 678, "y": 650, "w": 266, "h": 202}


def test_two_stage_keeps_separate_tile_parents_when_vertical_gap_marks_distinct_cards() -> None:
    groups = [
        {
            "group_id": "settings_system",
            "label": "System",
            "role": "tile_card_parent",
            "bbox": {"x": 370, "y": 310, "w": 220, "h": 72},
            "member_numbers": ["3.1"],
            "member_item_ids": ["settings_system"],
        },
        {
            "group_id": "settings_apps",
            "label": "Apps",
            "role": "tile_card_parent",
            "bbox": {"x": 370, "y": 410, "w": 220, "h": 72},
            "member_numbers": ["3.2"],
            "member_item_ids": ["settings_apps"],
        },
    ]

    merged = two_stage._merge_adjacent_tile_card_parent_fragments(groups)

    assert len(merged) == 2
    assert [group["group_id"] for group in merged] == ["settings_system", "settings_apps"]


def test_two_stage_does_not_merge_shifted_list_rows_or_complete_text_columns() -> None:
    groups = [
        {
            "group_id": "news_row_a",
            "role": "tile_card_parent",
            "bbox": {"x": 681, "y": 981, "w": 416, "h": 58},
            "member_item_ids": ["news_row_a"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "news_row_b",
            "role": "tile_card_parent",
            "bbox": {"x": 784, "y": 1020, "w": 425, "h": 58},
            "member_item_ids": ["news_row_b"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
        {
            "group_id": "complete_text_column",
            "role": "tile_card_parent",
            "bbox": {"x": 678, "y": 944, "w": 325, "h": 196},
            "member_item_ids": ["complete_text_column"],
            "source": "stage2_repeated_text_column_parent_grouping",
        },
        {
            "group_id": "next_section_card",
            "role": "tile_card_parent",
            "bbox": {"x": 681, "y": 1121, "w": 526, "h": 81},
            "member_item_ids": ["next_section_card"],
            "source": "stage2_primary_tile_card_parent_grouping",
        },
    ]

    merged = two_stage._merge_adjacent_tile_card_parent_fragments(groups)

    assert [group["group_id"] for group in merged] == [
        "news_row_a",
        "news_row_b",
        "complete_text_column",
        "next_section_card",
    ]


def test_two_stage_normalizes_parallel_list_parent_width_from_complete_sibling_column() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "bbox": {"x": 0, "y": 200, "w": 1200, "h": 700},
    }
    items = [
        {"number": "1.1", "item_id": "date_a1", "label": "2026-07-01", "role": "text", "bbox": {"x": 100, "y": 400, "w": 80, "h": 20}},
        {"number": "1.2", "item_id": "title_a1", "label": "A deliberately long first list title", "role": "text", "bbox": {"x": 200, "y": 400, "w": 300, "h": 20}},
        {"number": "1.3", "item_id": "date_a2", "label": "2026-07-02", "role": "text", "bbox": {"x": 100, "y": 440, "w": 80, "h": 20}},
        {"number": "1.4", "item_id": "title_a2", "label": "A second complete title", "role": "text", "bbox": {"x": 200, "y": 440, "w": 250, "h": 20}},
        {"number": "1.5", "item_id": "date_b1", "label": "2026-07-03", "role": "text", "bbox": {"x": 650, "y": 400, "w": 80, "h": 20}},
        {"number": "1.6", "item_id": "title_b1", "label": "Short event title", "role": "text", "bbox": {"x": 750, "y": 400, "w": 140, "h": 20}},
        {"number": "1.7", "item_id": "date_b2", "label": "2026-07-04", "role": "text", "bbox": {"x": 650, "y": 440, "w": 80, "h": 20}},
        {"number": "1.8", "item_id": "title_b2", "label": "Another event title", "role": "text", "bbox": {"x": 750, "y": 440, "w": 150, "h": 20}},
    ]

    groups = two_stage._list_row_parent_groups(region=region, numbered_items=items)

    list_groups = sorted((group for group in groups if group.get("role") == "list_group"), key=lambda group: group["bbox"]["x"])
    assert len(list_groups) == 2
    assert list_groups[0]["bbox"]["w"] == list_groups[1]["bbox"]["w"]
    assert list_groups[1]["bbox"]["w"] >= 400


def test_stage1_shallow_fullscreen_partition_uses_reliable_horizontal_control_row_boundary() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "zone_id": "main_content",
        "bbox": {"x": 0, "y": 0, "w": 2500, "h": 1300},
        "rough_bbox": {"x": 520, "y": 134, "w": 920, "h": 187},
    }
    navigation_row = [
        {
            "item_id": f"nav_{index}",
            "label": f"Section {index}",
            "role": "text",
            "bbox": {"x": 650 + index * 120, "y": 180, "w": 72, "h": 24},
            "source": "conditional_ocr_content_recovery",
        }
        for index in range(7)
    ]
    body_evidence = [
        {
            "item_id": "hero_heading",
            "label": "Feature heading",
            "role": "text",
            "bbox": {"x": 760, "y": 245, "w": 240, "h": 30},
            "source": "conditional_ocr_content_recovery",
        },
        {
            "item_id": "hero_body",
            "label": "Feature body text",
            "role": "text",
            "bbox": {"x": 1260, "y": 245, "w": 260, "h": 30},
            "source": "conditional_ocr_content_recovery",
        },
    ]

    recovered = two_stage._recover_shallow_fullscreen_main_partition(
        [region],
        screen_size={"width": 2500, "height": 1300},
        boundary_evidence_items=[*navigation_row, *body_evidence],
    )

    assert recovered[0]["bbox"] == {"x": 0, "y": 0, "w": 2500, "h": 214}
    assert recovered[1]["bbox"] == {"x": 0, "y": 214, "w": 2500, "h": 1086}
    assert recovered[0]["boundary_recovery"]["source"] == "repeated_horizontal_control_row"
