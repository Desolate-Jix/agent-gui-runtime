from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.learn.recognition.layout_regularization import (
    apply_card_layout_review_enhancement,
    infer_neighbor_card_candidates,
    regularize_repeated_card_layout,
)


def _image(path: Path, cards: list[tuple[int, int, int, int]]) -> Path:
    image = Image.new("RGB", (800, 500), (210, 214, 218))
    draw = ImageDraw.Draw(image)
    for x, y, w, h in cards:
        draw.rectangle((x, y, x + w, y + h), fill=(252, 252, 252), outline=(180, 184, 188), width=2)
    image.save(path)
    return path


def _candidate(index: int, bbox: tuple[int, int, int, int]) -> dict:
    x, y, w, h = bbox
    return {
        "box_type": "subregion_group",
        "number": f"card_{index}",
        "role": "tile_card_parent",
        "label": f"Card {index}",
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "render_in_main_overlay": True,
        "display_only": True,
    }


def test_regularizer_expands_text_candidates_to_three_aligned_visual_cards(tmp_path: Path) -> None:
    source = _image(
        tmp_path / "cards.png",
        [(50, 100, 200, 220), (275, 103, 198, 217), (500, 98, 202, 222)],
    )
    candidates = [
        _candidate(1, (65, 250, 150, 32)),
        _candidate(2, (292, 246, 145, 35)),
        _candidate(3, (516, 252, 154, 31)),
    ]

    result = regularize_repeated_card_layout(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["contract_version"] == "learn_layout_regularization_experiment_v1"
    assert result["alignment_group_count"] == 1
    assert result["normalized_card_count"] == 3
    group = result["alignment_groups"][0]
    assert group["support_count"] == 3
    assert group["status"] == "layout_normalized_for_review"
    boxes = [item["layout_normalized_bbox"] for item in group["items"]]
    assert max(box["y"] for box in boxes) - min(box["y"] for box in boxes) <= 2
    assert max(box["h"] for box in boxes) - min(box["h"] for box in boxes) <= 2
    assert all(item["raw_bbox"] != item["source_candidate_bbox"] for item in group["items"])
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False


def test_regularizer_does_not_force_alignment_with_only_two_cards(tmp_path: Path) -> None:
    source = _image(tmp_path / "two-cards.png", [(50, 100, 200, 220), (275, 102, 200, 218)])
    candidates = [
        _candidate(1, (65, 250, 150, 32)),
        _candidate(2, (292, 246, 145, 35)),
    ]

    result = regularize_repeated_card_layout(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["alignment_group_count"] == 0
    assert result["normalized_card_count"] == 0
    assert result["status"] == "insufficient_repeated_layout_evidence"


def test_regularizer_keeps_different_sized_module_out_of_card_group(tmp_path: Path) -> None:
    source = _image(
        tmp_path / "mixed.png",
        [
            (50, 100, 180, 210),
            (250, 101, 182, 208),
            (450, 99, 179, 212),
            (650, 80, 130, 330),
        ],
    )
    candidates = [
        _candidate(1, (65, 250, 140, 30)),
        _candidate(2, (265, 248, 140, 32)),
        _candidate(3, (465, 252, 138, 30)),
        _candidate(4, (665, 280, 100, 35)),
    ]

    result = regularize_repeated_card_layout(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["alignment_group_count"] == 1
    group = result["alignment_groups"][0]
    assert group["support_count"] == 3
    assert {item["source_candidate_id"] for item in group["items"]} == {
        "card_1",
        "card_2",
        "card_3",
    }
    assert any(
        item["source_candidate_id"] == "card_4"
        and item["reason"] == "no_repeated_size_cluster"
        for item in result["unregularized_candidates"]
    )


def test_regularizer_recovers_grid_slots_from_repeated_partial_card_regions(
    tmp_path: Path,
) -> None:
    image = Image.new("RGB", (900, 650), (210, 214, 218))
    draw = ImageDraw.Draw(image)
    for row_y in (80, 350):
        for column_x in (60, 330, 600):
            draw.rectangle(
                (column_x, row_y, column_x + 240, row_y + 125),
                fill=(252, 252, 252),
                outline=(180, 184, 188),
                width=2,
            )
    source = tmp_path / "partial-grid.png"
    image.save(source)
    candidates = [
        _candidate(1, (80, 220, 180, 45)),
        _candidate(2, (350, 218, 180, 48)),
        _candidate(3, (620, 221, 180, 44)),
        _candidate(4, (70, 225, 400, 40)),
    ]

    result = regularize_repeated_card_layout(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["alignment_group_count"] == 1
    assert result["normalized_card_count"] == 3
    group = result["alignment_groups"][0]
    assert group["geometry_source"] == "inferred_repeated_grid_slots"
    actual_x = [item["layout_normalized_bbox"]["x"] for item in group["items"]]
    assert all(
        abs(actual - expected) <= 2
        for actual, expected in zip(actual_x, [60, 330, 600])
    )
    assert all(item["layout_normalized_bbox"]["h"] > 200 for item in group["items"])
    assert all(
        "card_4" not in item["source_candidate_ids"]
        for item in group["items"]
    )
    assert any(
        item["source_candidate_id"] == "card_4"
        and item["reason"] == "no_repeated_size_cluster"
        for item in result["unregularized_candidates"]
    )


def test_neighbor_inference_recalls_one_hop_cards_with_visual_support(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "neighbor-cards.png",
        [
            (40, 60, 150, 160),
            (210, 60, 150, 160),
            (380, 60, 150, 160),
            (550, 60, 150, 160),
            (40, 250, 150, 160),
            (210, 250, 150, 160),
            (380, 250, 150, 160),
            (550, 250, 150, 160),
        ],
    )
    candidates = [
        _candidate(1, (230, 175, 110, 30)),
        _candidate(2, (400, 175, 110, 30)),
    ]

    result = infer_neighbor_card_candidates(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["contract_version"] == "learn_neighbor_card_inference_experiment_v1"
    assert result["seed_candidate_count"] == 2
    assert result["proposal_count"] == 2
    assert all(
        abs(actual - expected) <= 2
        for actual, expected in zip(
            [proposal["bbox"]["x"] for proposal in result["proposals"]],
            [40, 550],
        )
    )
    assert all(
        proposal["status"] == "needs_human_review"
        and proposal["inference_source"] == "one_hop_same_class_neighbor_prior"
        and proposal["artifact_is_authorization"] is False
        and proposal["execute_binding_enabled"] is False
        for proposal in result["proposals"]
    )


def test_neighbor_inference_does_not_cascade_from_inferred_neighbors(
    tmp_path: Path,
) -> None:
    columns = (20, 170, 320, 470, 620)
    source = _image(
        tmp_path / "no-cascade.png",
        [
            (x, y, 130, 150)
            for y in (50, 230)
            for x in columns
        ],
    )
    candidates = [
        _candidate(1, (185, 155, 100, 28)),
        _candidate(2, (335, 155, 100, 28)),
    ]

    result = infer_neighbor_card_candidates(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    proposal_x = [proposal["bbox"]["x"] for proposal in result["proposals"]]
    assert all(
        abs(actual - expected) <= 2
        for actual, expected in zip(proposal_x, [20, 470])
    )
    assert all(abs(actual - 620) > 2 for actual in proposal_x)
    assert result["policy"]["inferred_proposals_can_seed_more_proposals"] is False


def test_neighbor_inference_rejects_empty_grid_slots_without_visual_support(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "empty-neighbors.png",
        [
            (210, 60, 150, 160),
            (380, 60, 150, 160),
            (40, 250, 150, 160),
            (210, 250, 150, 160),
            (380, 250, 150, 160),
            (550, 250, 150, 160),
        ],
    )
    candidates = [
        _candidate(1, (230, 175, 110, 30)),
        _candidate(2, (400, 175, 110, 30)),
    ]

    result = infer_neighbor_card_candidates(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["proposal_count"] == 0
    assert {
        item["reason"]
        for item in result["rejected_neighbor_slots"]
        if abs(item["bbox"]["y"] - 60) <= 2
    } == {"insufficient_direct_visual_support"}


def test_neighbor_inference_does_not_split_wide_card_covering_seed_and_neighbor(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "wide-parent.png",
        [
            (40, 60, 150, 160),
            (210, 60, 150, 160),
            (380, 60, 320, 160),
            (40, 250, 150, 160),
            (210, 250, 150, 160),
            (380, 250, 150, 160),
            (550, 250, 150, 160),
        ],
    )
    candidates = [
        _candidate(1, (230, 175, 110, 30)),
        _candidate(2, (400, 175, 110, 30)),
    ]

    result = infer_neighbor_card_candidates(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["proposal_count"] == 1
    assert abs(result["proposals"][0]["bbox"]["x"] - 40) <= 2
    assert any(
        item["reason"] == "shared_wide_parent_already_has_seed"
        and abs(item["bbox"]["x"] - 550) <= 2
        for item in result["rejected_neighbor_slots"]
    )


def test_neighbor_inference_respects_existing_wide_semantic_card(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "wide-semantic-card.png",
        [
            (40, 60, 320, 160),
            (380, 60, 150, 160),
            (550, 60, 150, 160),
            (40, 250, 150, 160),
            (210, 250, 150, 160),
            (380, 250, 150, 160),
            (550, 250, 150, 160),
        ],
    )
    candidates = [
        _candidate(1, (60, 165, 280, 35)),
        _candidate(2, (400, 175, 110, 30)),
        _candidate(3, (570, 175, 110, 30)),
    ]

    result = infer_neighbor_card_candidates(
        image_path=source,
        candidates=candidates,
        minimum_group_size=3,
    )

    assert result["proposal_count"] == 0
    assert any(
        item["reason"] == "existing_wide_semantic_card_covers_slot"
        and abs(item["bbox"]["x"] - 210) <= 2
        for item in result["rejected_neighbor_slots"]
    )


def test_layout_review_enhancement_updates_stage2_review_geometry_and_adds_neighbor(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "stage2-cards.png",
        [
            (40, 60, 150, 160),
            (210, 60, 150, 160),
            (380, 60, 150, 160),
            (550, 60, 150, 160),
            (40, 250, 150, 160),
            (210, 250, 150, 160),
            (380, 250, 150, 160),
            (550, 250, 150, 160),
        ],
    )
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 500},
            "numbered_items": [{"number": "3.1", "role": "button"}],
            "subregion_groups": [
                {
                    **_candidate(1, (55, 170, 120, 35)),
                    "group_id": "card_1",
                },
                {
                    **_candidate(2, (225, 168, 120, 38)),
                    "group_id": "card_2",
                },
                {
                    **_candidate(3, (395, 172, 120, 32)),
                    "group_id": "card_3",
                },
            ],
        }
    ]

    result = apply_card_layout_review_enhancement(
        image_path=source,
        numbered_regions=numbered_regions,
        stage2_policy={
            "content_adapter_id": "media_player",
            "repeated_peer_layout_review": {
                "class_prior": "expected",
                "peer_item_family": "media_card",
                "activation": "current_visual_repetition_required",
                "can_create_without_visual_support": False,
            },
        },
    )

    assert result["contract_version"] == "learn_card_layout_review_enhancement_v1"
    assert result["report"]["normalized_existing_card_count"] == 3
    assert result["report"]["neighbor_proposal_count"] == 1
    assert result["report"]["class_rule_context"] == {
        "content_adapter_id": "media_player",
        "class_prior": "expected",
        "peer_item_family": "media_card",
        "activation": "current_visual_repetition_required",
        "can_create_without_visual_support": False,
        "triggered_by_current_visual_evidence": True,
    }
    enhanced_region = result["regions"][0]
    assert enhanced_region["numbered_items"] == numbered_regions[0]["numbered_items"]
    groups = enhanced_region["subregion_groups"]
    updated = {group["group_id"]: group for group in groups}
    assert updated["card_1"]["source_bbox"] == {"x": 55, "y": 170, "w": 120, "h": 35}
    assert abs(updated["card_1"]["bbox"]["x"] - 40) <= 2
    assert updated["card_1"]["layout_review_regularized"] is True
    proposal = next(group for group in groups if group.get("layout_neighbor_proposal"))
    assert abs(proposal["bbox"]["x"] - 550) <= 2
    assert proposal["candidate_only"] is True
    assert proposal["review_required"] is True
    assert proposal["execute_binding_enabled"] is False
    assert proposal["artifact_is_authorization"] is False
    assert numbered_regions[0]["subregion_groups"][0]["bbox"] == {
        "x": 55,
        "y": 170,
        "w": 120,
        "h": 35,
    }


def test_layout_review_enhancement_is_noop_without_card_evidence(
    tmp_path: Path,
) -> None:
    source = _image(tmp_path / "plain-controls.png", [(50, 100, 200, 220)])
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 500},
            "numbered_items": [{"number": "1.1", "role": "button"}],
            "subregion_groups": [
                {
                    "group_id": "toolbar",
                    "role": "toolbar",
                    "bbox": {"x": 0, "y": 0, "w": 800, "h": 60},
                }
            ],
        }
    ]

    result = apply_card_layout_review_enhancement(
        image_path=source,
        numbered_regions=numbered_regions,
    )

    assert result["regions"] == numbered_regions
    assert result["report"]["status"] == "no_eligible_card_evidence"
    assert result["report"]["normalized_existing_card_count"] == 0
    assert result["report"]["neighbor_proposal_count"] == 0
    assert result["artifact_is_authorization"] is False


def test_layout_review_enhancement_does_not_use_prior_proposals_as_new_seeds(
    tmp_path: Path,
) -> None:
    source = _image(
        tmp_path / "no-second-hop.png",
        [
            (20, 50, 130, 150),
            (170, 50, 130, 150),
            (320, 50, 130, 150),
            (470, 50, 130, 150),
            (620, 50, 130, 150),
            (20, 230, 130, 150),
            (170, 230, 130, 150),
            (320, 230, 130, 150),
            (470, 230, 130, 150),
            (620, 230, 130, 150),
        ],
    )
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 500},
            "numbered_items": [],
            "subregion_groups": [
                {**_candidate(1, (185, 155, 100, 28)), "group_id": "card_1"},
                {**_candidate(2, (335, 155, 100, 28)), "group_id": "card_2"},
            ],
        }
    ]

    first = apply_card_layout_review_enhancement(
        image_path=source,
        numbered_regions=numbered_regions,
    )
    second = apply_card_layout_review_enhancement(
        image_path=source,
        numbered_regions=first["regions"],
    )

    first_proposals = [
        group
        for group in first["regions"][0]["subregion_groups"]
        if group.get("layout_neighbor_proposal")
    ]
    second_proposals = [
        group
        for group in second["regions"][0]["subregion_groups"]
        if group.get("layout_neighbor_proposal")
    ]
    assert len(first_proposals) == 2
    assert len(second_proposals) == 2
    assert all(abs(group["bbox"]["x"] - 620) > 2 for group in second_proposals)
