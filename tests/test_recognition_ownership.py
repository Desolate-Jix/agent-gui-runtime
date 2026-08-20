from __future__ import annotations

from app.learn.recognition.ownership import resolve_group_ownership


def _group(
    group_id: str,
    *,
    role: str,
    source: str,
    members: list[str],
    bbox: dict[str, int],
    parent_group_id: str = "",
    child_group_ids: list[str] | None = None,
) -> dict:
    return {
        "group_id": group_id,
        "role": role,
        "source": source,
        "member_item_ids": members,
        "member_numbers": list(members),
        "bbox": bbox,
        "parent_group_id": parent_group_id,
        "child_group_ids": list(child_group_ids or []),
    }


def test_list_row_ownership_beats_inferred_text_tile() -> None:
    groups = [
        _group(
            "list",
            role="list_group",
            source="stage2_date_title_list_parent_synthesis",
            members=["date", "title"],
            bbox={"x": 80, "y": 100, "w": 500, "h": 160},
            child_group_ids=["row"],
        ),
        _group(
            "row",
            role="list_row",
            source="stage2_date_title_row_parent_synthesis",
            members=["date", "title"],
            bbox={"x": 90, "y": 120, "w": 420, "h": 26},
            parent_group_id="list",
        ),
        _group(
            "text_tile",
            role="tile_card_parent",
            source="stage2_primary_text_tile_card_parent_grouping",
            members=["date", "title"],
            bbox={"x": 70, "y": 102, "w": 176, "h": 92},
        ),
    ]

    result = resolve_group_ownership(groups)

    by_id = {group["group_id"]: group for group in result["accepted_groups"]}
    assert by_id["row"]["member_item_ids"] == ["date", "title"]
    assert by_id["list"]["member_item_ids"] == ["date", "title"]
    assert "text_tile" not in by_id
    assert result["audit"]["conflict_count"] == 2
    assert result["audit"]["invalidated_group_count"] == 1
    assert result["audit"]["invalidated_groups"][0]["group_id"] == "text_tile"
    assert {entry["winner_group_id"] for entry in result["audit"]["rejected_claims"]} == {"row"}
    assert {entry["loser_group_id"] for entry in result["audit"]["rejected_claims"]} == {"text_tile"}


def test_text_tile_parent_is_removed_when_ownership_leaves_only_one_member() -> None:
    groups = [
        _group(
            "row",
            role="list_row",
            source="stage2_date_title_row_parent_synthesis",
            members=["subtitle"],
            bbox={"x": 90, "y": 120, "w": 420, "h": 26},
        ),
        {
            **_group(
                "text_tile",
                role="tile_card_parent",
                source="stage2_primary_text_tile_card_parent_grouping",
                members=["title", "subtitle"],
                bbox={"x": 70, "y": 102, "w": 176, "h": 92},
            ),
            "parent_child_policy": "paired_title_subtitle_text_tile_without_visible_card_bbox",
        },
    ]

    result = resolve_group_ownership(groups)

    by_id = {group["group_id"]: group for group in result["accepted_groups"]}
    assert by_id["row"]["member_item_ids"] == ["subtitle"]
    assert "text_tile" not in by_id
    assert result["audit"]["source_item_owner_map"] == {"subtitle": "row"}
    assert result["audit"]["invalidated_groups"] == [
        {
            "group_id": "text_tile",
            "role": "tile_card_parent",
            "source": "stage2_primary_text_tile_card_parent_grouping",
            "surviving_member_item_ids": ["title"],
            "required_member_count": 2,
            "reason": "required_title_subtitle_pair_not_preserved_after_ownership",
        }
    ]


def test_explicit_visual_card_beats_inferred_text_card() -> None:
    groups = [
        _group(
            "visual_card",
            role="tile_card_parent",
            source="stage2_primary_tile_card_parent_grouping",
            members=["card_title"],
            bbox={"x": 100, "y": 100, "w": 220, "h": 120},
        ),
        _group(
            "inferred_card",
            role="tile_card_parent",
            source="stage2_primary_text_tile_card_parent_grouping",
            members=["card_title"],
            bbox={"x": 110, "y": 110, "w": 176, "h": 92},
        ),
    ]

    result = resolve_group_ownership(groups)

    assert result["audit"]["source_item_owner_map"]["card_title"] == "visual_card"
    rejection = result["audit"]["rejected_claims"][0]
    assert rejection["winner_group_id"] == "visual_card"
    assert rejection["loser_group_id"] == "inferred_card"
    assert rejection["reason"] == "stronger_semantic_or_evidence_precedence"


def test_conversation_row_beats_broad_visual_tile_parent() -> None:
    groups = [
        _group(
            "broad_tile",
            role="tile_card_parent",
            source="stage2_primary_tile_card_parent_grouping",
            members=["avatar", "friend_name"],
            bbox={"x": 20, "y": 120, "w": 420, "h": 360},
        ),
        _group(
            "friend_row",
            role="conversation_row",
            source="stage2_semantic_parent_reconstruction",
            members=["avatar", "friend_name"],
            bbox={"x": 36, "y": 148, "w": 310, "h": 48},
        ),
    ]

    result = resolve_group_ownership(groups)

    assert result["audit"]["source_item_owner_map"] == {
        "avatar": "friend_row",
        "friend_name": "friend_row",
    }
    assert {entry["winner_role"] for entry in result["audit"]["rejected_claims"]} == {"conversation_row"}


def test_nested_ancestor_claims_are_not_conflicts() -> None:
    groups = [
        _group(
            "section",
            role="section_parent",
            source="stage2_section_parent_reconciliation",
            members=["title"],
            bbox={"x": 50, "y": 50, "w": 600, "h": 400},
            child_group_ids=["list"],
        ),
        _group(
            "list",
            role="list_group",
            source="stage2_date_title_list_parent_synthesis",
            members=["title"],
            bbox={"x": 80, "y": 100, "w": 500, "h": 200},
            parent_group_id="section",
            child_group_ids=["row"],
        ),
        _group(
            "row",
            role="list_row",
            source="stage2_date_title_row_parent_synthesis",
            members=["title"],
            bbox={"x": 90, "y": 120, "w": 420, "h": 26},
            parent_group_id="list",
        ),
    ]

    result = resolve_group_ownership(groups)

    assert result["audit"]["conflict_count"] == 0
    assert result["audit"]["source_item_owner_map"]["title"] == "row"
    assert all(group["member_item_ids"] == ["title"] for group in result["accepted_groups"])


def test_equal_strength_conflict_is_deterministic_and_needs_review() -> None:
    first = _group(
        "group_b",
        role="component_group",
        source="semantic_model_proposal",
        members=["shared"],
        bbox={"x": 100, "y": 100, "w": 180, "h": 80},
    )
    second = _group(
        "group_a",
        role="component_group",
        source="semantic_model_proposal",
        members=["shared"],
        bbox={"x": 100, "y": 100, "w": 180, "h": 80},
    )

    forward = resolve_group_ownership([first, second])
    reverse = resolve_group_ownership([second, first])

    assert forward["audit"]["source_item_owner_map"] == reverse["audit"]["source_item_owner_map"] == {"shared": "group_a"}
    assert forward["audit"]["ambiguous_tie_count"] == 1
    assert forward["audit"]["rejected_claims"][0]["reason"] == "semantic_evidence_tie_geometric_tiebreak_needs_review"
    assert forward["audit"]["needs_human_review"] is True
    assert forward["audit"]["execute_binding_enabled"] is False


def test_same_semantic_and_evidence_with_different_areas_still_needs_review() -> None:
    result = resolve_group_ownership(
        [
            _group(
                "small",
                role="component_group",
                source="semantic_model_proposal",
                members=["shared"],
                bbox={"x": 100, "y": 100, "w": 100, "h": 50},
            ),
            _group(
                "large",
                role="component_group",
                source="semantic_model_proposal",
                members=["shared"],
                bbox={"x": 80, "y": 80, "w": 180, "h": 100},
            ),
        ]
    )

    assert result["audit"]["ambiguous_tie_count"] == 1
    assert result["audit"]["needs_human_review"] is True
    assert result["audit"]["rejected_claims"][0]["reason"] == "semantic_evidence_tie_geometric_tiebreak_needs_review"


def test_topbar_semantic_parent_relationship_is_persisted() -> None:
    groups = [
        _group(
            "strip",
            role="topbar_control_strip",
            source="stage2_direct_bar_parent_reconstruction",
            members=["control"],
            bbox={"x": 0, "y": 0, "w": 800, "h": 60},
            child_group_ids=["cluster"],
        ),
        _group(
            "cluster",
            role="topbar_control_cluster",
            source="stage2_direct_bar_parent_reconstruction",
            members=["control"],
            bbox={"x": 300, "y": 0, "w": 120, "h": 60},
        ),
        _group(
            "semantic",
            role="topbar_semantic_group",
            source="stage2_direct_bar_parent_reconstruction",
            members=["control"],
            bbox={"x": 280, "y": 0, "w": 180, "h": 60},
        ),
    ]

    result = resolve_group_ownership(groups)
    by_id = {group["group_id"]: group for group in result["accepted_groups"]}

    assert by_id["cluster"]["resolved_parent_group_id"] == "semantic"
    assert by_id["semantic"]["resolved_parent_group_id"] == "strip"
    assert result["audit"]["conflict_count"] == 0


def test_topbar_semantic_group_cannot_parent_a_wider_cluster() -> None:
    groups = [
        _group(
            "strip",
            role="topbar_control_strip",
            source="stage2_direct_bar_parent_reconstruction",
            members=["left", "right"],
            bbox={"x": 0, "y": 0, "w": 900, "h": 60},
            child_group_ids=["cluster"],
        ),
        _group(
            "cluster",
            role="topbar_control_cluster",
            source="stage2_direct_bar_parent_reconstruction",
            members=["left", "right"],
            bbox={"x": 200, "y": 0, "w": 600, "h": 60},
        ),
        _group(
            "semantic",
            role="topbar_semantic_group",
            source="stage2_direct_bar_parent_reconstruction",
            members=["left"],
            bbox={"x": 200, "y": 0, "w": 180, "h": 60},
        ),
    ]

    result = resolve_group_ownership(groups)
    by_id = {group["group_id"]: group for group in result["accepted_groups"]}

    assert by_id["cluster"]["resolved_parent_group_id"] == "strip"
    assert by_id["semantic"]["resolved_parent_group_id"] == "strip"


def test_resolved_parent_bbox_expands_to_contain_repaired_child_group() -> None:
    groups = [
        _group(
            "section",
            role="section_parent",
            source="stage2_section_parent_reconciliation",
            members=[],
            bbox={"x": 100, "y": 40, "w": 200, "h": 160},
            child_group_ids=["list"],
        ),
        _group(
            "list",
            role="list_group",
            source="stage2_date_title_list_parent_synthesis",
            members=["title"],
            bbox={"x": 100, "y": 80, "w": 202, "h": 100},
            parent_group_id="section",
        ),
    ]

    result = resolve_group_ownership(groups)
    by_id = {group["group_id"]: group for group in result["accepted_groups"]}

    assert by_id["section"]["bbox"] == {"x": 100, "y": 40, "w": 202, "h": 160}
    assert result["audit"]["parent_bbox_reconciliation_count"] == 1
    assert result["audit"]["parent_bbox_reconciliations"][0]["parent_group_id"] == "section"
    assert result["audit"]["parent_bbox_reconciliations"][0]["child_group_id"] == "list"
