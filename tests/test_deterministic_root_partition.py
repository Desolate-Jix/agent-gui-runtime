from __future__ import annotations

import inspect
from pathlib import Path

from PIL import Image, ImageDraw

from app.learn.recognition import root_partition
from app.learn.recognition.root_partition import (
    adapt_root_partition_to_stage1_contract,
    build_deterministic_root_partition,
    validate_root_partition,
)
from app.api.panel import PanelRunLearningTwoStageUnderstandingRequest
from app.learn.recognition.pipeline import build_learning_recognition_trial
from app.learn.recognition import two_stage as two_stage_module
from app.learn.recognition.two_stage import (
    _build_stage1_structure,
    _normalize_stage1_structure_override,
    build_stage1_region_localization_report,
    build_two_stage_screen_understanding,
)
def _item(item_id: str, x: int, y: int, w: int, h: int, *, role: str = "layout") -> dict:
    return {
        "item_id": item_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "role": role,
        "source": "fixture",
    }


def test_no_reliable_cut_returns_one_root_instead_of_midpoint_split() -> None:
    result = build_deterministic_root_partition([], {"width": 1000, "height": 800})
    assert [region["bbox"] for region in result["root_regions"]] == [
        {"x": 0, "y": 0, "w": 1000, "h": 800}
    ]
    assert result["diagnostics"]["fallback"] == "single_root_no_supported_cut"


def test_supported_vertical_tracks_tile_the_screen_without_overlap() -> None:
    items = [
        _item("left_1", 10, 20, 50, 80),
        _item("left_2", 10, 300, 50, 80),
        _item("left_3", 10, 500, 50, 80),
        _item("middle_1", 100, 20, 280, 80),
        _item("middle_2", 100, 300, 280, 80),
        _item("middle_3", 100, 500, 280, 80),
        _item("right_1", 450, 20, 500, 80),
        _item("right_2", 450, 300, 500, 80),
        _item("right_3", 450, 500, 500, 80),
    ]
    result = build_deterministic_root_partition(items, {"width": 1000, "height": 600})
    report = validate_root_partition(result["root_regions"], {"width": 1000, "height": 600})
    assert len(result["root_regions"]) >= 2
    assert all(region["bbox"]["h"] == 600 for region in result["root_regions"])
    assert report["valid"] is True
    assert report["coverage_ratio"] == 1.0
    assert report["sibling_overlap_area"] == 0


def test_repeated_equal_width_grid_columns_do_not_become_a_left_navigation_root() -> None:
    items = [
        _item(
            f"grid_button_{row}_{column}",
            12 + column * 140,
            350 + row * 100,
            138,
            98,
            role="button",
        )
        for row in range(6)
        for column in range(4)
    ]

    partition = build_deterministic_root_partition(items, {"width": 900, "height": 1000})
    stage1 = adapt_root_partition_to_stage1_contract(partition)

    assert [region["bbox"] for region in partition["root_regions"]] == [
        {"x": 0, "y": 0, "w": 900, "h": 1000}
    ]
    assert [region["zone_id"] for region in stage1["structure_regions"]] == ["main_content"]
    assert partition["diagnostics"]["root_selection"]["rejected_grid_internal_cut"] is True


def test_dominant_data_grid_columns_do_not_become_root_sidebar(monkeypatch) -> None:
    items = [
        _item("top_bar", 0, 0, 1162, 140, role="navigation"),
        {
            **_item("process_table", 9, 135, 1145, 855, role="datagrid"),
            "metadata": {"control_type": "DataGrid"},
        },
    ]

    def fake_axis_cuts(_elements, _screen, *, axis: str):
        if axis == "x":
            return [
                {"point": 242, "gap_ratio": 0.0, "support": 0.86, "score": 1.0},
                {"point": 508, "gap_ratio": 0.0, "support": 0.87, "score": 1.0},
                {"point": 652, "gap_ratio": 0.0, "support": 0.93, "score": 1.0},
            ]
        return []

    monkeypatch.setattr(root_partition, "_axis_cuts", fake_axis_cuts)
    monkeypatch.setattr(
        root_partition,
        "_vertical_separator_cuts",
        lambda *_args, **_kwargs: [
            {
                "point": 363,
                "support": 0.98,
                "score": 1.0,
                "source": "image_long_vertical_separator",
            }
        ],
    )
    monkeypatch.setattr(
        root_partition,
        "_horizontal_separator_cuts",
        lambda *_args, **_kwargs: [
            {
                "point": 135,
                "support": 1.0,
                "score": 1.0,
                "source": "image_long_horizontal_separator",
            }
        ],
    )
    monkeypatch.setattr(
        root_partition,
        "_edge_bands",
        lambda *_args, **_kwargs: {"top_end": 353, "bottom_start": None},
    )

    proposals, selection = root_partition._select_root_proposals(
        items,
        width=1162,
        height=1047,
        image_path="synthetic_task_table.png",
    )

    assert selection["rejected_tabular_internal_cut"] is True
    assert selection["strategy"] == "supported_top_band_above_tabular_content"
    assert [proposal["bbox"] for proposal in proposals] == [
        {"x": 0, "y": 0, "w": 1162, "h": 135},
        {"x": 0, "y": 135, "w": 1162, "h": 912},
    ]


def test_atom_on_partition_cut_has_one_root_owner() -> None:
    items = [_item("on_cut", 45, 20, 10, 20)]
    left_ids = root_partition._contained_item_ids(items, {"x": 0, "y": 0, "w": 50, "h": 100})
    right_ids = root_partition._contained_item_ids(items, {"x": 50, "y": 0, "w": 50, "h": 100})

    assert left_ids == []
    assert right_ids == ["on_cut"]


def test_long_vertical_separator_produces_image_boundary_candidate(tmp_path: Path) -> None:
    detector = getattr(root_partition, "_vertical_separator_cuts", None)
    assert detector is not None
    image_path = tmp_path / "sidebar.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 179, 599), fill=(210, 210, 210))
    image.save(image_path)

    cuts = detector(str(image_path), width=1000, height=600)

    assert cuts
    assert abs(cuts[0]["point"] - 180) <= 2
    assert cuts[0]["source"] == "image_long_vertical_separator"


def test_low_contrast_vertical_separator_requires_near_full_height_support(tmp_path: Path) -> None:
    image_path = tmp_path / "low_contrast_sidebar.png"
    image = Image.new("RGB", (1000, 600), (218, 218, 218))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 69, 599), fill=(210, 210, 210))
    image.save(image_path)

    cuts = root_partition._vertical_separator_cuts(str(image_path), width=1000, height=600)

    assert cuts
    assert abs(cuts[0]["point"] - 70) <= 2
    assert cuts[0]["low_contrast_full_height_support"] >= 0.9


def test_image_separator_refines_atomic_edge_rail_hypothesis() -> None:
    selector = root_partition._select_supported_edge_cut
    assert "image_separator_cuts" in inspect.signature(selector).parameters
    selected = selector(
        [
            {"point": 101, "score": 0.7186, "support": 0.6186},
            {"point": 451, "score": 1.0, "support": 0.9619},
        ],
        width=2576,
        image_separator_cuts=[
            {
                "point": 169,
                "score": 1.0,
                "support": 0.91,
                "source": "image_long_vertical_separator",
            }
        ],
    )
    assert selected is not None
    assert selected["point"] == 169
    assert selected["source"] == "image_long_vertical_separator"


def test_root_partition_uses_strong_image_separator_without_atomic_elements(tmp_path: Path) -> None:
    assert "image_path" in inspect.signature(build_deterministic_root_partition).parameters
    image_path = tmp_path / "two_panes.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 179, 599), fill=(210, 210, 210))
    image.save(image_path)

    result = build_deterministic_root_partition(
        [],
        {"width": 1000, "height": 600},
        image_path=str(image_path),
    )

    assert [region["bbox"] for region in result["root_regions"]] == [
        {"x": 0, "y": 0, "w": 180, "h": 600},
        {"x": 180, "y": 0, "w": 820, "h": 600},
    ]
    assert result["diagnostics"]["root_selection"]["strategy"] == "supported_image_edge_rail"


def test_formal_stage1_strategy_passes_source_image_for_separator_calibration(tmp_path: Path) -> None:
    image_path = tmp_path / "formal_two_panes.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 179, 599), fill=(210, 210, 210))
    image.save(image_path)

    stage1 = _build_stage1_structure(
        items_by_id={},
        screen_size={"width": 1000, "height": 600},
        source_image_path=str(image_path),
    )

    assert [region["bbox"] for region in stage1["structure_regions"]] == [
        {"x": 0, "y": 0, "w": 180, "h": 600},
        {"x": 180, "y": 0, "w": 820, "h": 600},
    ]


def test_long_horizontal_separator_produces_image_boundary_candidate(tmp_path: Path) -> None:
    detector = getattr(root_partition, "_horizontal_separator_cuts", None)
    assert detector is not None
    image_path = tmp_path / "header.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 999, 79), fill=(210, 210, 210))
    image.save(image_path)

    cuts = detector(str(image_path), width=1000, height=600)

    assert cuts
    assert abs(cuts[0]["point"] - 80) <= 2
    assert cuts[0]["source"] == "image_long_horizontal_separator"


def test_image_evidence_rejects_semantic_bottom_bar_without_boundary(tmp_path: Path) -> None:
    image_path = tmp_path / "no_bottom_bar.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 999, 79), fill=(210, 210, 210))
    image.save(image_path)
    items = [
        _item("toolbar", 0, 0, 1000, 70, role="toolbar"),
        _item("model_fake_bottom_bar", 0, 500, 1000, 90, role="bottom_bar"),
    ]

    result = build_deterministic_root_partition(
        items,
        {"width": 1000, "height": 600},
        image_path=str(image_path),
    )

    assert [region["bbox"] for region in result["root_regions"]] == [
        {"x": 0, "y": 0, "w": 1000, "h": 80},
        {"x": 0, "y": 80, "w": 1000, "h": 520},
    ]


def test_image_evidence_calibrates_blank_editor_between_header_and_status(tmp_path: Path) -> None:
    image_path = tmp_path / "blank_editor.png"
    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 999, 49), fill=(210, 210, 210))
    draw.rectangle((0, 570, 999, 599), fill=(210, 210, 210))
    image.save(image_path)
    items = [
        _item("oversized_toolbar", 0, 0, 1000, 100, role="toolbar"),
        _item("oversized_bottom_bar", 0, 490, 1000, 100, role="bottom_bar"),
    ]

    result = build_deterministic_root_partition(
        items,
        {"width": 1000, "height": 600},
        image_path=str(image_path),
    )

    assert [region["bbox"] for region in result["root_regions"]] == [
        {"x": 0, "y": 0, "w": 1000, "h": 50},
        {"x": 0, "y": 50, "w": 1000, "h": 520},
        {"x": 0, "y": 570, "w": 1000, "h": 30},
    ]


def test_repeated_grid_row_separators_do_not_calibrate_a_fake_bottom_bar() -> None:
    cuts = [
        {
            "point": point,
            "gap_ratio": 0.005,
            "support": 0.62,
            "score": 0.72,
            "source": "image_long_horizontal_separator",
        }
        for point in (347, 454, 561, 669, 776, 884)
    ]

    calibrated = root_partition._calibrate_edge_bands(
        {"top_end": 290, "bottom_start": 763},
        image_horizontal_cuts=cuts,
        height=1000,
        require_bottom_image_evidence=True,
    )

    assert calibrated == {"top_end": 347, "bottom_start": None}


def test_large_blank_remainder_does_not_become_vertical_column(monkeypatch) -> None:
    def fake_axis_cuts(_elements, _screen, *, axis: str):
        if axis == "x":
            return [
                {
                    "point": 492,
                    "gap_ratio": 0.8164,
                    "support": 0.1177,
                    "remainder_supported": True,
                    "score": 1.0,
                },
                {
                    "point": 985,
                    "gap_ratio": 0.0,
                    "support": 0.8929,
                    "remainder_supported": False,
                    "score": 1.0,
                },
            ]
        return []

    monkeypatch.setattr(root_partition, "_axis_cuts", fake_axis_cuts)
    monkeypatch.setattr(root_partition, "_vertical_separator_cuts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        root_partition,
        "_horizontal_separator_cuts",
        lambda *_args, **_kwargs: [
            {"point": 50, "support": 1.0, "score": 1.0},
            {"point": 570, "support": 1.0, "score": 1.0},
        ],
    )
    monkeypatch.setattr(
        root_partition,
        "_edge_bands",
        lambda *_args, **_kwargs: {"top_end": 77, "bottom_start": 545},
    )

    boxes, selection = root_partition._select_root_proposals(
        [],
        width=1000,
        height=600,
        image_path="synthetic_blank_editor.png",
    )

    assert selection["strategy"] == "supported_horizontal_edge_bands"
    assert [proposal["bbox"] for proposal in boxes] == [
        {"x": 0, "y": 0, "w": 1000, "h": 50},
        {"x": 0, "y": 50, "w": 1000, "h": 520},
        {"x": 0, "y": 570, "w": 1000, "h": 30},
    ]


def test_chat_stage1_5_uses_inner_separator_for_non_overlapping_panes(tmp_path: Path) -> None:
    builder = two_stage_module._stage1_5_chat_subregions
    assert "source_image_path" in inspect.signature(builder).parameters
    image_path = tmp_path / "chat_columns.png"
    image = Image.new("RGB", (1000, 600), (230, 230, 230))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 69, 599), fill=(210, 210, 210))
    draw.rectangle((70, 0, 299, 599), fill=(220, 220, 220))
    image.save(image_path)
    items = {
        "list": _item("list", 90, 80, 260, 420, role="conversation_list"),
        "thread": _item("thread", 120, 80, 830, 420, role="message_thread"),
        "composer": _item("composer", 300, 500, 650, 80, role="composer"),
    }
    region = {
        "region_id": "structure_region_main_content",
        "bbox": {"x": 70, "y": 0, "w": 930, "h": 600},
        "item_ids": list(items),
    }

    subregions = builder(
        region=region,
        items_by_id=items,
        source_image_path=str(image_path),
        screen_size={"width": 1000, "height": 600},
    )
    by_role = {subregion["role"]: subregion for subregion in subregions}

    assert by_role["conversation_list"]["bbox"]["x"] == 70
    assert by_role["conversation_list"]["bbox"]["x"] + by_role["conversation_list"]["bbox"]["w"] == 300
    assert by_role["message_thread"]["bbox"]["x"] == 300
    assert by_role["bottom_composer"]["bbox"]["x"] == 300


def test_chat_stage1_5_scans_beyond_root_edge_range_for_wide_list_pane(tmp_path: Path) -> None:
    image_path = tmp_path / "wide_chat_columns.png"
    image = Image.new("RGB", (1000, 600), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 69, 599), fill=(205, 205, 205))
    draw.rectangle((70, 0, 419, 599), fill=(220, 220, 220))
    image.save(image_path)
    items = {
        "list": _item("list", 90, 80, 330, 420, role="conversation_list"),
        "thread": _item("thread", 100, 80, 850, 420, role="message_thread"),
        "composer": _item("composer", 420, 500, 530, 80, role="composer"),
        "left_plain_text": _item("left_plain_text", 120, 300, 80, 24, role="text"),
        "right_plain_text": _item("right_plain_text", 600, 300, 80, 24, role="text"),
    }
    region = {
        "region_id": "structure_region_main_content",
        "bbox": {"x": 70, "y": 0, "w": 930, "h": 600},
        "item_ids": list(items),
    }

    subregions = two_stage_module._stage1_5_chat_subregions(
        region=region,
        items_by_id=items,
        source_image_path=str(image_path),
        screen_size={"width": 1000, "height": 600},
    )
    by_role = {subregion["role"]: subregion for subregion in subregions}

    assert by_role["conversation_list"]["bbox"]["x"] + by_role["conversation_list"]["bbox"]["w"] == 420
    assert by_role["message_thread"]["bbox"]["x"] == 420
    assert "left_plain_text" in by_role["conversation_list"]["item_ids"]
    assert "left_plain_text" not in by_role["message_thread"]["item_ids"]
    assert "right_plain_text" in by_role["message_thread"]["item_ids"]


def test_chat_stage1_5_rejects_mid_page_send_action_as_bottom_composer(tmp_path: Path) -> None:
    image_path = tmp_path / "empty_chat_detail.png"
    image = Image.new("RGB", (1000, 1000), (235, 235, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 69, 999), fill=(205, 205, 205))
    draw.rectangle((70, 0, 399, 999), fill=(220, 220, 220))
    image.save(image_path)
    items = {
        "list": _item("list", 90, 80, 300, 820, role="conversation_list"),
        "thread": _item("thread", 400, 80, 580, 820, role="message_thread"),
        "send_document": _item("send_document", 600, 500, 100, 40, role="button"),
    }
    items["send_document"]["label"] = "发送文档"
    region = {
        "region_id": "structure_region_main_content",
        "bbox": {"x": 70, "y": 0, "w": 930, "h": 1000},
        "item_ids": list(items),
    }

    subregions = two_stage_module._stage1_5_chat_subregions(
        region=region,
        items_by_id=items,
        source_image_path=str(image_path),
        screen_size={"width": 1000, "height": 1000},
    )
    by_role = {subregion["role"]: subregion for subregion in subregions}

    assert "bottom_composer" not in by_role
    assert by_role["conversation_list"]["bbox"]["h"] == 1000
    assert by_role["message_thread"]["bbox"]["h"] == 1000
    assert "send_document" in by_role["message_thread"]["item_ids"]


def test_stage2_child_region_excludes_seed_items_outside_child_bbox() -> None:
    items = {
        "left_text": _item("left_text", 110, 100, 80, 24, role="message_thread"),
        "thread_text": _item("thread_text", 420, 100, 80, 24, role="message_thread"),
    }
    localized_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_main_content",
            "bbox": {"x": 70, "y": 0, "w": 930, "h": 600},
            "item_ids": list(items),
        }
    ]
    partition = {
        "subregions": [
            {
                "subregion_id": "structure_region_main_content__stage1_5__message_thread",
                "parent_region_id": "structure_region_main_content",
                "role": "message_thread",
                "bbox": {"x": 300, "y": 0, "w": 700, "h": 600},
                "item_ids": list(items),
                "stage2_numbering_eligible": True,
            }
        ]
    }

    regions = two_stage_module._stage2_input_regions(
        localized_regions=localized_regions,
        stage1_5_partition=partition,
        items_by_id=items,
    )

    assert regions[0]["item_ids"] == ["thread_text"]


def test_notepad_style_blank_remainder_is_preserved() -> None:
    items = [
        _item("menu", 0, 0, 1000, 70),
        _item("status", 0, 730, 1000, 70, role="status_bar_evidence"),
    ]
    result = build_deterministic_root_partition(items, {"width": 1000, "height": 800})
    boxes = [region["bbox"] for region in result["root_regions"]]
    assert len(boxes) == 3
    assert boxes[0]["y"] == 0 and boxes[0]["h"] < 100
    assert boxes[1]["h"] > 600
    assert boxes[2]["y"] > 700 and boxes[2]["y"] + boxes[2]["h"] == 800


def test_stacked_top_controls_and_lower_edge_rail_form_mixed_root_topology(tmp_path: Path) -> None:
    image_path = tmp_path / "stacked_top_and_left_rail.png"
    image = Image.new("RGB", (1000, 600), (240, 240, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 999, 99), fill=(200, 200, 200))
    draw.rectangle((0, 100, 149, 599), fill=(220, 220, 220))
    image.save(image_path)
    items = [
        _item("browser_chrome", 0, 0, 1000, 50, role="browser_chrome"),
        _item("page_header", 0, 50, 1000, 50, role="header"),
        _item("left_tree", 0, 100, 150, 500, role="navigation"),
        _item("content", 150, 100, 850, 500, role="main_content"),
    ]

    result = build_deterministic_root_partition(
        items,
        {"width": 1000, "height": 600},
        image_path=str(image_path),
    )
    stage1 = adapt_root_partition_to_stage1_contract(result)

    assert [region["bbox"] for region in result["root_regions"]] == [
        {"x": 0, "y": 0, "w": 1000, "h": 100},
        {"x": 0, "y": 100, "w": 150, "h": 500},
        {"x": 150, "y": 100, "w": 850, "h": 500},
    ]
    assert [region["zone_id"] for region in stage1["structure_regions"]] == [
        "top_bar",
        "left_nav",
        "main_content",
    ]
    assert validate_root_partition(result["root_regions"], {"width": 1000, "height": 600})["valid"] is True


def test_bottom_content_cards_do_not_create_a_fake_root_bar() -> None:
    items = [
        _item("menu", 0, 0, 1000, 70, role="toolbar"),
        _item("content_1", 100, 160, 300, 120, role="card"),
        _item("content_2", 500, 160, 300, 120, role="card"),
        _item("continuation_1", 100, 650, 300, 100, role="card"),
        _item("continuation_2", 500, 650, 300, 100, role="card"),
    ]
    result = build_deterministic_root_partition(items, {"width": 1000, "height": 800})
    boxes = [region["bbox"] for region in result["root_regions"]]
    assert len(boxes) == 2
    assert boxes[-1]["y"] + boxes[-1]["h"] == 800


def test_semantic_bottom_panel_can_form_a_root_bar() -> None:
    items = [
        _item("menu", 0, 0, 1000, 70, role="toolbar"),
        _item("content", 100, 160, 800, 400, role="list"),
        _item("group_chat", 20, 650, 900, 100, role="group_chat_row"),
    ]
    result = build_deterministic_root_partition(items, {"width": 1000, "height": 800})
    boxes = [region["bbox"] for region in result["root_regions"]]
    assert len(boxes) == 3
    assert boxes[-1]["y"] > 600


def test_validator_uses_geometric_union_for_triple_overlap_coverage() -> None:
    regions = [
        {"bbox": {"x": 0, "y": 0, "w": 100, "h": 100}},
        {"bbox": {"x": 0, "y": 0, "w": 100, "h": 100}},
        {"bbox": {"x": 0, "y": 0, "w": 100, "h": 100}},
    ]
    report = validate_root_partition(regions, {"width": 100, "height": 100})
    assert report["coverage_ratio"] == 1.0
    assert report["sibling_overlap_area"] == 20000
    assert report["valid"] is False


def test_stage1_adapter_keeps_read_only_contract() -> None:
    partition = build_deterministic_root_partition([], {"width": 300, "height": 200})
    stage1 = adapt_root_partition_to_stage1_contract(partition)
    assert stage1["contract_version"] == "learn_stage1_structure_regions_v1"
    assert stage1["display_only"] is True
    assert stage1["execute_binding_enabled"] is False
    assert stage1["artifact_is_authorization"] is False
    assert stage1["structure_regions"][0]["bbox"] == {"x": 0, "y": 0, "w": 300, "h": 200}
    assert stage1["structure_regions"][0]["source"] == "deterministic_root_partition_v1"
    assert stage1["structure_regions"][0]["zone_id"] == "main_content"
    assert stage1["structure_regions"][0]["region_id"] == "structure_region_main_content"


def test_stage1_override_accepts_only_read_only_valid_contract() -> None:
    partition = build_deterministic_root_partition([], {"width": 300, "height": 200})
    stage1 = adapt_root_partition_to_stage1_contract(partition)
    assert _normalize_stage1_structure_override(None) is None
    normalized = _normalize_stage1_structure_override(stage1)
    assert normalized == stage1
    normalized["structure_regions"][0]["label"] = "changed"
    assert stage1["structure_regions"][0]["label"] != "changed"


def test_stage1_override_rejects_authorizing_or_empty_payload() -> None:
    partition = build_deterministic_root_partition([], {"width": 300, "height": 200})
    stage1 = adapt_root_partition_to_stage1_contract(partition)
    stage1["execute_binding_enabled"] = True
    try:
        _normalize_stage1_structure_override(stage1)
    except ValueError as exc:
        assert "read-only" in str(exc)
    else:
        raise AssertionError("authorizing Stage1 override must be rejected")

    try:
        _normalize_stage1_structure_override({"structure_regions": []})
    except ValueError as exc:
        assert "structure_regions" in str(exc)
    else:
        raise AssertionError("empty Stage1 override must be rejected")


def test_production_entry_has_one_root_partition_path() -> None:
    assert "stage1_region_strategy" not in PanelRunLearningTwoStageUnderstandingRequest.model_fields
    assert "stage1_region_strategy" not in inspect.signature(build_learning_recognition_trial).parameters
    assert "stage1_region_strategy" not in inspect.signature(build_two_stage_screen_understanding).parameters
    assert "stage1_region_strategy" not in inspect.signature(build_stage1_region_localization_report).parameters


def test_production_root_partition_does_not_import_experiment_modules() -> None:
    source = Path(root_partition.__file__).read_text(encoding="utf-8")

    assert "app.learn.experiments" not in source


def test_partition_uses_canonical_provenance() -> None:
    partition = build_deterministic_root_partition([], {"width": 300, "height": 200})
    stage1 = adapt_root_partition_to_stage1_contract(partition)

    assert partition["contract_version"] == "deterministic_root_partition_v1"
    assert stage1["partition_contract"] == "deterministic_root_partition_v1"
    assert stage1["root_validator"]["valid"] is True


def test_stage1_builder_always_uses_production_root_contract() -> None:
    items = {
        "top": _item("top", 0, 0, 1000, 70, role="toolbar"),
        "body": _item("body", 0, 80, 1000, 650, role="editor"),
        "status": _item("status", 0, 730, 1000, 70, role="status_bar_evidence"),
    }
    stage1 = _build_stage1_structure(
        items_by_id=items,
        screen_size={"width": 1000, "height": 800},
        source_image_path="",
    )

    assert stage1["contract_version"] == "learn_stage1_structure_regions_v1"
    assert stage1["source"] == "deterministic_root_partition_v1"
    assert stage1["root_validator"]["valid"] is True


def test_stage1_builder_rejects_invalid_screen_size() -> None:
    try:
        _build_stage1_structure(
        items_by_id={},
        screen_size={"width": 0, "height": 10},
        source_image_path="",
        )
    except ValueError as exc:
        assert "valid screen size" in str(exc)
    else:
        raise AssertionError("invalid Stage1 screen size must fail")


def test_vertical_root_partition_compiles_edge_rail_and_main_content() -> None:
    partition = build_deterministic_root_partition([], {"width": 1000, "height": 600})
    partition["root_regions"] = [
        {"bbox": {"x": 0, "y": 0, "w": 90, "h": 600}, "item_ids": []},
        {"bbox": {"x": 90, "y": 0, "w": 910, "h": 600}, "item_ids": []},
    ]
    partition["validator"] = validate_root_partition(partition["root_regions"], partition["image_size"])
    stage1 = adapt_root_partition_to_stage1_contract(partition)
    assert [region["zone_id"] for region in stage1["structure_regions"]] == [
        "left_nav",
        "main_content",
    ]
    assert all("root" not in region["label"].casefold() for region in stage1["structure_regions"])
