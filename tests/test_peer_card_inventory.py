from __future__ import annotations

from app.learn.recognition.peer_card_inventory import build_agent_peer_card_inventory


def _policy(family: str = "news_article_card") -> dict:
    return {
        "content_adapter_id": "news_feed",
        "repeated_peer_layout_review": {
            "class_prior": "expected",
            "peer_item_family": family,
            "activation": "current_visual_repetition_required",
            "can_create_without_visual_support": False,
        },
    }


def test_peer_card_inventory_projects_current_card_evidence_without_geometry() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [
                    {
                        "item_id": "story_1",
                        "role": "content_card",
                        "label": "Council approves waterfront plan",
                        "text": "RNZ - 2h",
                        "bbox": {"x": 10, "y": 20, "w": 300, "h": 180},
                        "click_point": {"x": 100, "y": 80},
                        "source": "current_screen_inventory",
                        "interactable": True,
                        "action_semantic": "open_detail",
                    }
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    assert result["status"] == "current_peer_items_projected"
    assert result["peer_item_family"] == "news_article_card"
    assert result["current_visual_evidence_required"] is True
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["item_count"] == 1
    assert result["readable_item_count"] == 1
    assert result["review_candidate_count"] == 0
    assert result["items"] == [
        {
            "candidate_id": "story_1",
            "semantic_name": "Council approves waterfront plan",
            "content_summary": ["Council approves waterfront plan", "RNZ - 2h"],
            "source_kind": "current_screen_inventory",
            "candidate_kind": "atomic_card",
            "agent_decision_status": "readable_candidate",
            "review_status": "needs_human_review",
            "inferred_neighbor": False,
            "capabilities": {
                "read_current_content": True,
                "open_detail_candidate": True,
                "requires_fresh_localization": True,
                "requires_gate": True,
            },
        }
    ]
    assert "bbox" not in str(result)
    assert "click_point" not in str(result)


def test_peer_card_inventory_does_not_infer_action_without_explicit_evidence() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "subregion_groups": [
                    {
                        "group_id": "story_2",
                        "role": "tile_card_parent",
                        "label": "Possible article card",
                        "bbox": {"x": 10, "y": 20, "w": 300, "h": 180},
                        "layout_neighbor_proposal": True,
                        "candidate_only": True,
                    }
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    item = result["items"][0]
    assert item["inferred_neighbor"] is True
    assert item["candidate_kind"] == "inferred_neighbor"
    assert item["agent_decision_status"] == "review_only_candidate"
    assert item["capabilities"]["read_current_content"] is False
    assert item["capabilities"]["open_detail_candidate"] is False


def test_peer_card_inventory_excludes_row_level_card_containers() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "subregion_groups": [
                    {
                        "group_id": "row_1",
                        "role": "tile_card_group",
                        "label": "tile card row 1",
                        "source": "stage2_primary_content_card_row_grouping",
                    },
                    {
                        "group_id": "story_1",
                        "role": "tile_card_parent",
                        "label": "Actual story",
                        "source": "stage2_primary_tile_card_parent_grouping",
                    },
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    assert result["item_count"] == 1
    assert [item["candidate_id"] for item in result["items"]] == ["story_1"]


def test_peer_card_inventory_resolves_parent_member_content_for_agent() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [
                    {
                        "item_id": "headline_1",
                        "role": "text",
                        "label": "Council approves waterfront plan",
                    },
                    {
                        "item_id": "publisher_1",
                        "role": "text",
                        "label": "RNZ - 2h",
                    },
                ],
                "subregion_groups": [
                    {
                        "group_id": "story_1",
                        "role": "tile_card_parent",
                        "label": "Story",
                        "member_item_ids": ["headline_1", "publisher_1"],
                        "source": "stage2_primary_tile_card_parent_grouping",
                    }
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    item = result["items"][0]
    assert item["candidate_kind"] == "visual_card_parent"
    assert item["content_summary"] == [
        "Story",
        "Council approves waterfront plan",
        "RNZ - 2h",
    ]
    assert item["agent_decision_status"] == "readable_candidate"


def test_peer_card_inventory_keeps_text_only_groups_review_only() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [
                    {
                        "item_id": "category_1",
                        "role": "text",
                        "label": "News",
                    },
                    {
                        "item_id": "category_2",
                        "role": "text",
                        "label": "Sports",
                    },
                ],
                "subregion_groups": [
                    {
                        "group_id": "text_group_1",
                        "role": "tile_card_parent",
                        "label": "News",
                        "interactable": True,
                        "action_semantic": "open_detail",
                        "member_item_ids": ["category_1", "category_2"],
                        "source": "stage2_primary_text_tile_card_parent_grouping",
                    }
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    item = result["items"][0]
    assert item["candidate_kind"] == "text_only_group"
    assert item["agent_decision_status"] == "review_only_candidate"
    assert item["capabilities"]["read_current_content"] is False
    assert item["capabilities"]["open_detail_candidate"] is False
    assert result["readable_item_count"] == 0
    assert result["review_candidate_count"] == 1


def test_peer_card_inventory_collapses_duplicate_candidate_ids() -> None:
    duplicate = {
        "item_id": "story_1",
        "role": "media_card",
        "label": "Repeated story",
        "bbox": {"x": 1, "y": 1, "w": 50, "h": 50},
    }
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [duplicate],
                "subregion_groups": [{**duplicate, "group_id": "story_1"}],
            }
        ],
        stage2_policy=_policy(),
    )

    assert result["item_count"] == 1
    assert result["duplicate_candidate_ids"] == ["story_1"]


def test_peer_card_inventory_is_not_covered_without_declared_family() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [
                    {
                        "item_id": "card_1",
                        "role": "content_card",
                        "label": "Card",
                        "bbox": {"x": 1, "y": 1, "w": 50, "h": 50},
                    }
                ],
            }
        ],
        stage2_policy={
            "repeated_peer_layout_review": {
                "class_prior": "not_declared",
                "peer_item_family": "",
            }
        },
    )

    assert result["status"] == "not_covered"
    assert result["reason"] == "peer_item_family_not_declared"
    assert result["item_count"] == 0
    assert result["items"] == []


def test_peer_card_inventory_is_not_covered_without_current_cards() -> None:
    result = build_agent_peer_card_inventory(
        numbered_regions=[
            {
                "region_id": "main",
                "numbered_items": [
                    {
                        "item_id": "heading_1",
                        "role": "text",
                        "label": "News",
                        "bbox": {"x": 1, "y": 1, "w": 50, "h": 20},
                    }
                ],
            }
        ],
        stage2_policy=_policy(),
    )

    assert result["status"] == "not_covered"
    assert result["reason"] == "no_current_peer_card_evidence"
    assert result["item_count"] == 0
