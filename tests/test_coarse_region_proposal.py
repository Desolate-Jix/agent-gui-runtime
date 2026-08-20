from __future__ import annotations

from app.learn.recognition.coarse_region_proposal import (
    _axis_cuts,
    _normalize_elements,
    build_coarse_region_proposals,
)


def _item(item_id: str, x: int, y: int, w: int, h: int, source: str = "uia") -> dict:
    return {
        "item_id": item_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "source": source,
    }


def test_notepad_blank_editor_is_recovered_as_remainder_region() -> None:
    items = [
        _item("menu-file", 8, 8, 45, 24),
        _item("menu-edit", 58, 8, 45, 24),
        _item("window-controls", 930, 0, 70, 32),
        _item("status", 820, 570, 180, 30),
    ]

    result = build_coarse_region_proposals(items, {"width": 1000, "height": 600})

    proposals = result["proposals"]
    editor_candidates = [
        proposal
        for proposal in proposals
        if "remainder_region" in proposal["generation_sources"]
        and proposal["bbox"]["w"] >= 960
        and proposal["bbox"]["h"] >= 450
    ]
    assert len(editor_candidates) == 1
    assert editor_candidates[0]["contained_element_ids"] == []
    assert result["diagnostics"]["proposal_count"] <= 10


def test_three_column_layout_produces_distinct_coarse_columns() -> None:
    items = []
    for index, y in enumerate(range(30, 570, 70)):
        items.append(_item(f"rail-{index}", 8, y, 38, 65))
        items.append(_item(f"list-{index}", 90, y, 220, 65))
    items.extend(
        [
            _item("chat-header", 360, 20, 500, 55),
            _item("message-one", 520, 180, 260, 55),
            _item("composer", 370, 530, 480, 50),
        ]
    )

    result = build_coarse_region_proposals(items, {"width": 900, "height": 600})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    narrow_left = [proposal for proposal in level_one if proposal["bbox"]["x"] <= 20 and proposal["bbox"]["w"] <= 90]
    middle = [proposal for proposal in level_one if 50 <= proposal["bbox"]["x"] <= 150 and 150 <= proposal["bbox"]["w"] <= 320]
    wide_right = [proposal for proposal in level_one if proposal["bbox"]["x"] >= 300 and proposal["bbox"]["w"] >= 450]
    assert narrow_left
    assert middle
    assert wide_right


def test_full_window_container_does_not_inflate_whitespace_cut_support() -> None:
    items = [
        _item("window", 0, 0, 1000, 600),
        _item("left-rail", 0, 40, 90, 520),
        _item("middle-top", 400, 90, 170, 70),
        _item("middle-bottom", 400, 360, 170, 70),
        _item("right-top", 750, 90, 170, 70),
        _item("right-bottom", 750, 360, 170, 70),
    ]
    screen = {"x": 0, "y": 0, "w": 1000, "h": 600}

    cuts = _axis_cuts(_normalize_elements(items, screen), screen, axis="x")

    assert len(cuts) >= 2
    assert all(float(cut["support"]) < 0.72 for cut in cuts[:2])


def test_projection_finds_narrow_column_boundary_and_sparse_remainder() -> None:
    items = []
    for index, y in enumerate(range(100, 920, 80)):
        items.append(_item(f"rail-{index}", 8, y, 70, 73))
        items.append(_item(f"list-{index}", 78, y, 315, 73))
    items.extend(
        [
            _item("sparse-action-one", 516, 510, 113, 48),
            _item("sparse-action-two", 650, 510, 85, 73),
            _item("window-control", 897, 0, 48, 42),
        ]
    )

    result = build_coarse_region_proposals(items, {"width": 952, "height": 1029})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    assert any(65 <= proposal["bbox"]["w"] <= 90 for proposal in level_one)
    assert any(300 <= proposal["bbox"]["w"] <= 380 and proposal["bbox"]["x"] >= 60 for proposal in level_one)
    assert any(proposal["bbox"]["x"] >= 390 and proposal["bbox"]["w"] >= 490 for proposal in level_one)


def test_local_lower_columns_do_not_split_the_entire_page_vertically() -> None:
    items = [
        _item("top-wide", 0, 0, 1000, 80),
        _item("hero-wide", 80, 100, 840, 220),
    ]
    for row_y in (420, 620):
        for column, x in enumerate((80, 300, 520, 740)):
            items.append(_item(f"card-{row_y}-{column}", x, row_y, 180, 150))

    result = build_coarse_region_proposals(items, {"width": 1000, "height": 800})

    level_one = [proposal for proposal in result["proposals"] if proposal["proposal_level"] == 1]
    assert all(proposal["bbox"]["w"] == 1000 for proposal in level_one)
    assert result["diagnostics"]["major_partition_source"][0] == "y_whitespace_partition"


def test_proposals_are_anonymous_bounded_and_not_atomic_elements() -> None:
    items = [
        _item("nav-a", 20, 20, 40, 20),
        _item("nav-b", 80, 20, 40, 20),
        _item("content-a", 30, 130, 250, 80),
        _item("content-b", 320, 130, 250, 80),
        _item("content-c", 30, 250, 540, 100),
    ]

    result = build_coarse_region_proposals(items, {"width": 600, "height": 400})

    proposals = result["proposals"]
    assert 2 <= len([item for item in proposals if item["proposal_level"] == 1]) <= 8
    assert all(item["proposal_id"].startswith("P") for item in proposals)
    assert all(item["candidate_id"] == item["proposal_id"] for item in proposals)
    assert all(item["coordinate_space"] == "original_image" for item in proposals)
    assert all(item["bbox"]["x"] >= 0 and item["bbox"]["y"] >= 0 for item in proposals)
    assert all(item["bbox"]["x"] + item["bbox"]["w"] <= 600 for item in proposals)
    assert all(item["bbox"]["y"] + item["bbox"]["h"] <= 400 for item in proposals)
    assert all("label" not in item and "role" not in item for item in proposals)
    assert any(len(item["contained_element_ids"]) > 1 for item in proposals)
    assert len(proposals) < len(items) + 4


def test_proposal_evidence_exposes_generation_sources_and_density() -> None:
    items = [
        _item("left-1", 10, 20, 50, 30, "ocr"),
        _item("left-2", 10, 80, 50, 30, "uia"),
        _item("right-1", 260, 20, 120, 60, "parser"),
    ]

    result = build_coarse_region_proposals(items, {"width": 400, "height": 240})

    for proposal in result["proposals"]:
        assert proposal["generation_sources"]
        assert 0.0 <= proposal["area_ratio"] <= 1.0
        assert 0.0 <= proposal["evidence"]["separator_strength"] <= 1.0
        assert 0.0 <= proposal["evidence"]["whitespace_boundary_strength"] <= 1.0
        assert 0.0 <= proposal["evidence"]["element_density"] <= 1.0
