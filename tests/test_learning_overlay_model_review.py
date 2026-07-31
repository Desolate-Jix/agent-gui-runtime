from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from PIL import Image

import app.learn.recognition.model_review as model_review_module
from app.learn.recognition.model_review import (
    FOCUSED_CARD_REVIEW_ROLES,
    apply_review_patch,
    build_focused_group_review_prompt,
    build_model_review_prompt,
    build_missing_locator_tasks,
    focused_card_review_records,
    enforce_focused_semantic_transition,
    merge_focused_group_reviews,
    normalize_model_review_protocol,
    merge_deterministic_review_keeps,
    parse_focused_group_review_response,
    parse_model_review_response,
    render_model_review_input_overlay,
    render_focused_group_review_overlay,
    render_review_overlays,
    score_review_against_adjudication,
    partition_model_review_scope,
    validate_review_patch,
)
from scripts.run_learning_overlay_model_review_probe import _requires_preflight_group_batches, run_probe


def _stage2() -> dict:
    return {
        "contract_version": "learn_stage2_numbering_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "regions": [
            {
                "region_id": "message_thread",
                "label": "message thread",
                "bbox": {"x": 200, "y": 0, "w": 700, "h": 900},
                "numbered_items": [
                    {
                        "item_id": "message_1",
                        "number": "3.1",
                        "role": "message_item",
                        "bbox": {"x": 260, "y": 180, "w": 320, "h": 90},
                    }
                ],
                "subregion_groups": [
                    {
                        "group_id": "false_card",
                        "role": "tile_card_parent",
                        "label": "member rows",
                        "bbox": {"x": 720, "y": 100, "w": 170, "h": 500},
                        "member_item_ids": ["message_1"],
                    },
                    {
                        "group_id": "real_message_group",
                        "role": "message_item",
                        "label": "message",
                        "bbox": {"x": 260, "y": 180, "w": 320, "h": 90},
                        "member_item_ids": ["message_1"],
                    },
                ],
            }
        ],
    }


def test_full_page_review_preflight_batches_prompts_that_exceed_safe_context_budget() -> None:
    assert _requires_preflight_group_batches("x" * 12_001) is True
    assert _requires_preflight_group_batches("x" * 12_000) is False


def test_model_review_protocol_maps_overlay_aliases_to_real_group_ids() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {"region_id": "G01", "decision": "keep", "new_role": None, "reason": "valid"},
                {"region_id": "G02", "decision": "keep", "new_role": None, "reason": "valid"},
            ],
            "missing": [],
        },
        review_id_map={"G01": "false_card", "G02": "real_message_group"},
    )

    assert [item["region_id"] for item in normalized["group_reviews"]] == [
        "false_card",
        "real_message_group",
    ]
    assert normalized["protocol_adjustments"][0]["category"] == "overlay_alias_resolved"


def test_model_review_protocol_canonicalizes_news_card_to_generic_card() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {
                    "region_id": "G01",
                    "decision": "relabel",
                    "new_role": "news_card",
                    "reason": "single visible job summary card",
                },
                {"region_id": "G02", "decision": "keep", "new_role": None, "reason": "valid"},
            ],
            "missing": [],
        },
        review_id_map={"G01": "false_card", "G02": "real_message_group"},
    )

    assert normalized["group_reviews"][0]["decision"] == "relabel"
    assert normalized["group_reviews"][0]["new_role"] == "card"
    assert any(
        item["category"] == "review_role_alias_canonicalized"
        and item["model_requested_role"] == "news_card"
        and item["canonical_role"] == "card"
        for item in normalized["protocol_adjustments"]
    )


def test_group_review_phase_cannot_create_missing_repairs() -> None:
    patch = {
        "group_reviews": [
            {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "visible"}
        ],
        "missing": [
            {
                "description": "global guess from group review",
                "parent_region_id": "message_thread",
                "expected_role": "list_container",
                "rough_roi": {"x": 1, "y": 2, "w": 3, "h": 4},
                "repair_route": "precise_locator",
                "reason": "not allowed in this phase",
            }
        ],
    }

    result = model_review_module.enforce_group_review_only_patch(patch)

    assert result["missing"] == []
    assert result["protocol_adjustments"] == [
        {
            "category": "group_review_missing_suggestion_discarded",
            "discarded_count": 1,
        }
    ]


def test_model_review_protocol_maps_overlay_alias_prefixed_real_id() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {
                    "region_id": "G01_false_card",
                    "decision": "remove",
                    "new_role": None,
                    "reason": "invalid wrapper",
                },
                {
                    "region_id": "G02_real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "valid",
                },
            ],
            "missing": [],
        },
        review_id_map={"G01": "false_card", "G02": "real_message_group"},
    )

    assert [item["region_id"] for item in normalized["group_reviews"]] == [
        "false_card",
        "real_message_group",
    ]
    assert all(
        item["category"] == "overlay_alias_resolved"
        for item in normalized["protocol_adjustments"]
    )


def test_model_review_protocol_uses_bounded_alias_when_display_suffix_is_truncated() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {
                    "region_id": "G01_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "valid",
                },
                {
                    "region_id": "G02_false_card",
                    "decision": "remove",
                    "new_role": None,
                    "reason": "invalid wrapper",
                },
            ],
            "missing": [],
        },
        review_id_map={"G01": "real_message_group", "G02": "false_card"},
    )

    assert [item["region_id"] for item in normalized["group_reviews"]] == [
        "real_message_group",
        "false_card",
    ]
    assert not normalized["needs_human_review"]


def test_model_review_protocol_turns_unsupported_relabel_into_human_review() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {
                    "region_id": "false_card",
                    "decision": "relabel",
                    "new_role": "section_parent",
                    "reason": "looks structural",
                },
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "valid",
                },
            ],
            "missing": [],
        },
        review_id_map={},
    )

    first = normalized["group_reviews"][0]
    assert first["decision"] == "needs_human_review"
    assert first["new_role"] is None
    assert first["model_requested_role"] == "section_parent"
    validated = validate_review_patch(_stage2(), normalized, require_complete_group_coverage=True)
    assert validated["needs_human_review"][0]["region_id"] == "false_card"


def test_model_review_protocol_normalizes_same_role_relabel_to_keep() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"][0]["role"] = "topbar_semantic_group"
    normalized = normalize_model_review_protocol(
        stage2,
        {
            "group_reviews": [
                {
                    "region_id": "false_card",
                    "decision": "relabel",
                    "new_role": "topbar_semantic_group",
                    "reason": "resource metrics remain a semantic topbar group",
                },
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "valid",
                },
            ],
            "missing": [],
        },
        review_id_map={},
    )

    first = normalized["group_reviews"][0]
    assert first["decision"] == "keep"
    assert first["new_role"] is None
    assert any(
        item["category"] == "same_role_relabel_normalized_to_keep"
        for item in normalized["protocol_adjustments"]
    )


def test_model_review_protocol_safe_stops_omitted_required_groups() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "seen"}
            ],
            "missing": [],
        },
        review_id_map={},
    )

    completed = {item["region_id"]: item for item in normalized["group_reviews"]}
    assert completed["real_message_group"]["decision"] == "needs_human_review"
    assert any(
        item["category"] == "omitted_group_safe_stopped"
        for item in normalized["protocol_adjustments"]
    )
    validated = validate_review_patch(_stage2(), normalized, require_complete_group_coverage=True)
    assert validated["coverage_complete"] is True
    assert validated["needs_human_review"][0]["region_id"] == "real_message_group"


def test_model_review_scope_preserves_valid_deterministic_leaf_rows_without_model_budget() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].append(
        {
            "group_id": "table_row_1",
            "role": "table_row",
            "label": "one file row",
            "bbox": {"x": 210, "y": 300, "w": 600, "h": 34},
            "member_item_ids": ["name", "date", "type"],
        }
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert model_ids == {"false_card", "real_message_group"}
    assert scope["deterministic_keep_reviews"] == [
        {
            "region_id": "table_row_1",
            "decision": "keep",
            "new_role": None,
            "reason": "deterministic leaf-row geometry and parent containment passed",
            "review_source": "deterministic_leaf_invariant",
        }
    ]
    merged = merge_deterministic_review_keeps(
        {
            "group_reviews": [
                {"region_id": "false_card", "decision": "remove", "new_role": None, "reason": "bad"},
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "good",
                },
            ],
            "missing": [],
        },
        scope["deterministic_keep_reviews"],
    )
    validated = validate_review_patch(stage2, merged, require_complete_group_coverage=True)
    assert validated["coverage_complete"] is True
    assert validated["needs_human_review"] == []


def test_model_review_scope_does_not_auto_preserve_oversized_leaf_row() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].append(
        {
            "group_id": "table_row_oversized",
            "role": "table_row",
            "bbox": {"x": 210, "y": 100, "w": 600, "h": 400},
            "member_item_ids": ["name", "date", "type"],
        }
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert "table_row_oversized" in model_ids
    assert scope["deterministic_keep_reviews"] == []


def test_model_review_scope_does_not_freeze_context_sensitive_row_semantics() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].extend(
        [
            {
                "group_id": "conversation_row_1",
                "role": "conversation_row",
                "label": "possibly misclassified file row",
                "bbox": {"x": 210, "y": 220, "w": 600, "h": 34},
                "member_item_ids": ["file_name", "change_count"],
            },
            {
                "group_id": "list_row_1",
                "role": "list_row",
                "label": "possibly misclassified generic row",
                "bbox": {"x": 210, "y": 260, "w": 600, "h": 34},
                "member_item_ids": ["label", "metadata"],
            },
        ]
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert {"conversation_row_1", "list_row_1"} <= model_ids
    assert scope["deterministic_keep_reviews"] == []


def test_model_review_scope_preserves_only_source_proven_topbar_groups() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].extend(
        [
            {
                "group_id": "trusted_topbar",
                "role": "topbar_control_strip",
                "label": "header controls",
                "bbox": {"x": 210, "y": 10, "w": 600, "h": 44},
                "member_item_ids": ["file", "edit", "view"],
                "source": "stage2_direct_bar_parent_reconstruction",
            },
            {
                "group_id": "unproven_topbar",
                "role": "topbar_control_strip",
                "label": "possibly wrong header controls",
                "bbox": {"x": 210, "y": 60, "w": 600, "h": 44},
                "member_item_ids": ["unknown"],
                "source": "semantic_model_guess",
            },
        ]
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert "trusted_topbar" not in model_ids
    assert "unproven_topbar" in model_ids
    assert any(
        review["region_id"] == "trusted_topbar"
        and review["review_source"] == "deterministic_bar_structure_invariant"
        for review in scope["deterministic_keep_reviews"]
    )


def test_model_review_scope_preserves_only_source_proven_table_parent() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].extend(
        [
            {
                "group_id": "trusted_table",
                "role": "table_group",
                "label": "aligned table",
                "bbox": {"x": 210, "y": 100, "w": 600, "h": 700},
                "member_item_ids": ["cell_1", "cell_2", "cell_3"],
                "child_group_ids": ["table_row_1", "table_row_2"],
                "child_group_roles": ["table_row", "table_row"],
                "source": "stage2_dense_aligned_table_parent_synthesis",
            },
            {
                "group_id": "unproven_table",
                "role": "table_group",
                "label": "guessed table",
                "bbox": {"x": 220, "y": 120, "w": 500, "h": 400},
                "member_item_ids": ["unknown"],
                "child_group_ids": ["row_guess"],
                "child_group_roles": ["list_row"],
                "source": "semantic_model_guess",
            },
        ]
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert "trusted_table" not in model_ids
    assert "unproven_table" in model_ids
    assert any(
        review["region_id"] == "trusted_table"
        and review["review_source"] == "deterministic_table_structure_invariant"
        for review in scope["deterministic_keep_reviews"]
    )


def test_model_review_scope_preserves_only_source_proven_partial_visible_group() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].extend(
        [
            {
                "group_id": "trusted_partial_row",
                "role": "partial_visible_card_group",
                "label": "partial visible row",
                "bbox": {"x": 210, "y": 860, "w": 600, "h": 30},
                "expected_item_role": "partial_visible_card",
                "member_item_ids": [],
                "source": "stage2_primary_content_card_row_grouping",
            },
            {
                "group_id": "unproven_partial_row",
                "role": "partial_visible_card_group",
                "label": "guessed partial row",
                "bbox": {"x": 210, "y": 820, "w": 600, "h": 30},
                "expected_item_role": "partial_visible_card",
                "member_item_ids": [],
                "source": "semantic_model_guess",
            },
        ]
    )

    scope = partition_model_review_scope(stage2)

    model_ids = {
        group["group_id"]
        for root in scope["model_stage2"]["regions"]
        for group in root.get("subregion_groups", [])
    }
    assert "trusted_partial_row" not in model_ids
    assert "unproven_partial_row" in model_ids
    assert any(
        review["region_id"] == "trusted_partial_row"
        and review["review_source"] == "deterministic_partial_visibility_invariant"
        for review in scope["deterministic_keep_reviews"]
    )


def test_model_review_protocol_rejects_unknown_reference_without_crashing_validation() -> None:
    normalized = normalize_model_review_protocol(
        _stage2(),
        {
            "group_reviews": [
                {"region_id": "invented_group", "decision": "keep", "new_role": None, "reason": "wrong"},
                {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "seen"},
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "seen",
                },
            ],
            "missing": [],
        },
        review_id_map={},
    )

    assert all(item["region_id"] != "invented_group" for item in normalized["group_reviews"])
    assert normalized["needs_human_review"][0]["region_id"] == ""
    assert normalized["protocol_adjustments"][0]["category"] == "unknown_region_reference_rejected"
    validated = validate_review_patch(_stage2(), normalized, require_complete_group_coverage=True)
    assert validated["coverage_complete"] is True
    assert validated["needs_human_review"][0]["region_id"] == ""


def test_review_patch_removes_false_card_and_relabels_existing_region_without_mutating_input() -> None:
    stage2 = _stage2()
    original = deepcopy(stage2)
    patch = {
        "contract_version": "learning_overlay_model_review_patch_v1",
        "keep": [{"region_id": "real_message_group", "reason": "matches one message"}],
        "remove": [{"region_id": "false_card", "reason": "member list is not a card"}],
        "relabel": [{"region_id": "message_1", "new_role": "list_item", "reason": "row semantic"}],
        "missing": [],
        "needs_human_review": [],
    }

    validated = validate_review_patch(stage2, patch)
    reviewed = apply_review_patch(stage2, validated)

    assert validated["status"] == "valid"
    assert stage2 == original
    groups = reviewed["regions"][0]["subregion_groups"]
    assert [group["group_id"] for group in groups] == ["real_message_group"]
    item = reviewed["regions"][0]["numbered_items"][0]
    assert item["role"] == "list_item"
    assert item["model_review_decision"]["action"] == "relabel"
    assert reviewed["model_review_summary"]["removed"] == 1


def test_review_patch_reparents_surviving_child_group_when_parent_is_removed() -> None:
    stage2 = _stage2()
    groups = stage2["regions"][0]["subregion_groups"]
    groups[1]["parent_group_id"] = "false_card"
    groups[1]["resolved_parent_group_id"] = "false_card"
    patch = validate_review_patch(
        stage2,
        {
            "keep": [{"region_id": "real_message_group", "reason": "valid child"}],
            "remove": [{"region_id": "false_card", "reason": "invalid wrapper"}],
            "relabel": [],
            "missing": [],
            "needs_human_review": [],
        },
        require_complete_group_coverage=True,
    )

    reviewed = apply_review_patch(stage2, patch)
    child = reviewed["regions"][0]["subregion_groups"][0]

    assert child["group_id"] == "real_message_group"
    assert "parent_group_id" not in child
    assert "resolved_parent_group_id" not in child
    assert child["model_review_reparenting"] == {
        "removed_parent_group_id": "false_card",
        "new_parent_group_id": None,
        "reason": "removed_review_wrapper_reparented_to_nearest_surviving_ancestor",
        "display_only": True,
    }


@pytest.mark.parametrize(
    ("patch", "error_fragment"),
    [
        (
            {
                "keep": [],
                "remove": [{"region_id": "unknown", "reason": "bad reference"}],
                "relabel": [],
                "missing": [],
                "needs_human_review": [],
            },
            "unknown region_id",
        ),
        (
            {
                "keep": [],
                "remove": [],
                "relabel": [{"region_id": "message_1", "new_role": "magic_card", "reason": "bad role"}],
                "missing": [],
                "needs_human_review": [],
            },
            "unsupported role",
        ),
        (
            {
                "keep": [],
                "remove": [],
                "relabel": [],
                "missing": [
                    {
                        "description": "missing member list",
                        "parent_region_id": "message_thread",
                        "expected_role": "member_list",
                        "bbox": {"x": 700, "y": 0, "w": 200, "h": 900},
                    }
                ],
                "needs_human_review": [],
            },
            "final geometry",
        ),
    ],
)
def test_review_patch_rejects_unknown_ids_roles_and_model_final_geometry(patch: dict, error_fragment: str) -> None:
    with pytest.raises(ValueError, match=error_fragment):
        validate_review_patch(_stage2(), patch)


def test_review_patch_accepts_tab_role_from_stage2_screen_understanding() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"][0]["member_item_ids"] = ["tab_item"]
    stage2["regions"][0]["numbered_items"] = [
        {
            "item_id": "tab_item",
            "label": "Choose documents",
            "role": "tab",
            "bbox": {"x": 20, "y": 20, "w": 160, "h": 32},
        }
    ]
    patch = {
        "keep": [],
        "remove": [],
        "relabel": [
            {
                "region_id": "false_card",
                "new_role": "tab",
                "reason": "visible workflow step tab",
            }
        ],
        "missing": [],
        "needs_human_review": [],
    }

    validated = validate_review_patch(stage2, patch)

    assert validated["relabel"][0]["new_role"] == "tab"


def test_review_patch_accepts_stage1_repartition_ticket_without_mutating_stage1() -> None:
    patch = {
        "keep": [],
        "remove": [],
        "relabel": [],
        "missing": [
            {
                "description": "right-side member list is missing as a structural child",
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "rough_roi": {"x": 700, "y": 0, "w": 200, "h": 900},
                "repair_route": "stage1_repartition",
                "reason": "current root combines message thread and member list",
            }
        ],
        "needs_human_review": [],
    }

    validated = validate_review_patch(_stage2(), patch)

    assert validated["missing"][0]["repair_route"] == "stage1_repartition"
    assert validated["missing"][0]["rough_roi"] == {"x": 700, "y": 0, "w": 200, "h": 900}


def test_missing_repairs_are_routed_to_precise_locator_or_stage1_without_authorization() -> None:
    patch = validate_review_patch(
        _stage2(),
        {
            "keep": [],
            "remove": [],
            "relabel": [],
            "missing": [
                {
                    "description": "composer send control",
                    "parent_region_id": "message_thread",
                    "expected_role": "input_region",
                    "rough_roi": {"x": 250, "y": 780, "w": 430, "h": 100},
                    "repair_route": "precise_locator",
                    "reason": "not represented in current numbered items",
                },
                {
                    "description": "right member list",
                    "parent_region_id": "message_thread",
                    "expected_role": "member_list",
                    "rough_roi": {"x": 700, "y": 0, "w": 200, "h": 900},
                    "repair_route": "stage1_repartition",
                    "reason": "structural child is merged into message thread",
                },
            ],
            "needs_human_review": [],
        },
    )

    tasks = build_missing_locator_tasks(_stage2(), patch, "D:/screenshots/chat.png")

    assert tasks["contract_version"] == "learning_overlay_missing_repair_handoff_v1"
    assert len(tasks["regions"]) == 1
    precise = tasks["regions"][0]
    assert precise["prompt"] == "Locate missing input_region: composer send control"
    assert precise["bbox"] == {"x": 250, "y": 780, "w": 430, "h": 100}
    assert precise["bbox_quality"] == "rough_roi_only_requires_precise_grounding"
    assert precise["requires_precise_grounding"] is True
    assert len(tasks["stage1_repair_requests"]) == 1
    assert tasks["stage1_repair_requests"][0]["expected_role"] == "member_list"
    assert tasks["execute_binding_enabled"] is False
    assert tasks["artifact_is_authorization"] is False
    assert tasks["real_clicks"] == 0


def test_review_prompt_contains_stage2_evidence_and_forbids_free_final_boxes() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"][0]["label"] = "@@ -31, 6 +31, 7 @@ def parse_layout"
    prompt = build_model_review_prompt(stage2)

    assert "false_card" not in prompt
    assert '"review_id":"G01"' in prompt
    assert "tile_card_parent" in prompt
    assert "Do not invent a final bbox" in prompt
    assert "stage1_repartition" in prompt
    assert '"keep"' in prompt
    assert '"missing"' in prompt
    assert '"numbered_item_count":1' in prompt
    assert '"numbered_items"' not in prompt
    assert '"member_evidence"' in prompt
    assert "@@ -31, 6 +31, 7 @@ def parse_layout" in prompt
    assert "Source roles and labels are hypotheses" in prompt
    assert "code, document, or detail pane" in prompt
    assert "Every opaque review ID must appear exactly once" in prompt
    assert '"group_reviews"' in prompt
    assert "Required opaque review IDs" in prompt
    assert '"review_id":"G01"' in prompt


def test_parse_model_review_response_accepts_fenced_json_and_rejects_non_object() -> None:
    parsed = parse_model_review_response(
        """```json
        {"keep": [], "remove": [], "relabel": [], "missing": [], "needs_human_review": []}
        ```"""
    )
    assert parsed["keep"] == []

    with pytest.raises(ValueError, match="JSON object"):
        parse_model_review_response("[]")


def test_parse_model_review_response_preserves_raw_protocol_fields_for_validator() -> None:
    parsed = parse_model_review_response(
        '{"remove":[{"region_id":"false_card","reason":"list rows"}],'
        '"keep":[],"relabel":[],"missing":[],"needs_human_review":[],"unexpected":true}'
    )

    assert parsed["remove"][0]["region_id"] == "false_card"
    assert parsed["unexpected"] is True


def test_strict_group_coverage_rejects_empty_or_partial_model_review() -> None:
    empty = {
        "keep": [],
        "remove": [],
        "relabel": [],
        "missing": [],
        "needs_human_review": [],
    }
    with pytest.raises(ValueError, match="review coverage missing subregion_group IDs"):
        validate_review_patch(_stage2(), empty, require_complete_group_coverage=True)


def test_group_review_table_is_normalized_into_downstream_patch_arrays() -> None:
    raw = {
        "group_reviews": [
            {
                "region_id": "false_card",
                "decision": "remove",
                "reason": "repeated member rows are a list, not one card",
            },
            {
                "region_id": "real_message_group",
                "decision": "relabel",
                "new_role": "message_item",
                "reason": "one coherent message",
            },
        ],
        "missing": [],
    }

    validated = validate_review_patch(_stage2(), raw, require_complete_group_coverage=True)

    assert validated["coverage_complete"] is True
    assert validated["remove"][0]["region_id"] == "false_card"
    assert validated["relabel"][0]["new_role"] == "message_item"


def test_focused_card_review_prompt_and_merge_override_full_page_keep() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"][0]["label"] = "@@ code diff"
    records = focused_card_review_records(stage2)
    assert [record["region_id"] for record in records] == ["false_card", "real_message_group"]
    prompt = build_focused_group_review_prompt(records[0])
    assert "false_card" not in prompt
    assert "G01" in prompt
    assert "@@ code diff" in prompt
    assert "one coherent card" in prompt
    assert "stage1_repartition" in prompt
    assert "list_container" in prompt
    assert "remove the wrapper" in prompt
    assert "observed_role must differ from the source role" in prompt

    merged = merge_focused_group_reviews(
        stage2=_stage2(),
        base_patch={
            "group_reviews": [
                {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "full-page default"},
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "valid message",
                },
            ],
            "missing": [],
        },
        focused_reviews=[
            {
                "region_id": "false_card",
                "decision": "relabel",
                "new_role": "member_list",
                "structural_repair": "stage1_repartition",
                "reason": "contains many independent member rows",
            }
        ],
    )

    reviewed = {item["region_id"]: item for item in merged["group_reviews"]}
    assert reviewed["false_card"]["decision"] == "relabel"
    assert reviewed["false_card"]["new_role"] == "member_list"
    assert merged["missing"][0]["parent_region_id"] == "message_thread"
    assert merged["missing"][0]["rough_roi"] == {"x": 720, "y": 100, "w": 170, "h": 500}
    assert merged["missing"][0]["repair_route"] == "stage1_repartition"
    validated = validate_review_patch(_stage2(), merged, require_complete_group_coverage=True)
    assert validated["status"] == "valid"


def test_focused_group_response_requires_exact_id_and_allowed_role() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"false_card","decision":"relabel","new_role":"member_list",'
        '"observed_role":"member_list","geometry_quality":"exact_semantic_unit",'
        '"parent_relation":"valid_child","structural_repair":"stage1_repartition",'
        '"reason":"independent member rows"}',
        expected_region_id="false_card",
    )
    assert parsed["new_role"] == "member_list"

    with pytest.raises(ValueError, match="exact region_id"):
        parse_focused_group_review_response(
            '{"region_id":"G01_false_card","decision":"remove","new_role":null,'
            '"observed_role":"member_list","geometry_quality":"overmerged",'
            '"parent_relation":"distinct_pane",'
            '"structural_repair":"none","reason":"wrong id"}',
            expected_region_id="false_card",
        )

    with pytest.raises(ValueError, match="unsupported role"):
        parse_focused_group_review_response(
            '{"region_id":"false_card","decision":"relabel","new_role":"tile_card_parent_list",'
            '"observed_role":"member_list","geometry_quality":"exact_semantic_unit",'
            '"parent_relation":"valid_child",'
            '"structural_repair":"none","reason":"unsupported role"}',
            expected_region_id="false_card",
        )


def test_focused_group_response_accepts_candidate_only_observed_role() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"section_parent_1","decision":"remove","new_role":null,'
        '"observed_role":"section_parent","geometry_quality":"overmerged",'
        '"parent_relation":"valid_child","structural_repair":"none",'
        '"reason":"contains multiple independent cards"}',
        expected_region_id="section_parent_1",
    )

    assert parsed["observed_role"] == "section_parent"
    assert parsed["decision"] == "remove"


def test_focused_group_response_normalizes_message_bubble_alias() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"chat_wrapper","decision":"remove","new_role":null,'
        '"observed_role":"message_bubble","geometry_quality":"overmerged",'
        '"parent_relation":"valid_child","structural_repair":"none",'
        '"reason":"the wrapper contains multiple independent messages"}',
        expected_region_id="chat_wrapper",
    )

    assert parsed["observed_role"] == "message_item"
    assert parsed["decision"] == "remove"


def test_focused_group_response_recovers_region_id_copied_into_observed_role() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"G40","decision":"remove","new_role":null,'
        '"observed_role":"tile_card_row_6","geometry_quality":"overmerged",'
        '"parent_relation":"valid_child","structural_repair":"stage1_repartition",'
        '"reason":"the row wrapper contains independent cards"}',
        expected_region_id="G40",
        source_region_id="tile_card_row_6",
        source_role="tile_card_group",
    )

    assert parsed["observed_role"] == "tile_card_group"
    assert parsed["observed_role_normalized"] == "source_role_from_copied_region_id"


def test_focused_group_response_does_not_recover_unrelated_unknown_role() -> None:
    with pytest.raises(ValueError, match="unsupported observed_role"):
        parse_focused_group_review_response(
            '{"region_id":"G40","decision":"remove","new_role":null,'
            '"observed_role":"unrelated_unknown_role","geometry_quality":"overmerged",'
            '"parent_relation":"valid_child","structural_repair":"stage1_repartition",'
            '"reason":"unknown structure"}',
            expected_region_id="G40",
            source_region_id="tile_card_row_6",
            source_role="tile_card_group",
        )


def test_overmerged_valid_child_can_be_relabelled_to_safe_container() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"section_parent_2","decision":"relabel","new_role":"list_container",'
        '"observed_role":"section_parent","geometry_quality":"overmerged",'
        '"parent_relation":"valid_child","structural_repair":"none",'
        '"reason":"contains repeated rows under one section"}',
        expected_region_id="section_parent_2",
    )

    assert parsed["decision"] == "relabel"
    assert parsed["new_role"] == "list_container"


def test_card_family_cannot_be_relabelled_directly_to_message_item() -> None:
    review = enforce_focused_semantic_transition(
        {"region_id": "web_card", "role": "tile_card_parent", "parent_label": "main content"},
        {
            "region_id": "web_card",
            "decision": "relabel",
            "new_role": "message_item",
            "reason": "looks like one text block",
        },
    )

    assert review["decision"] == "needs_human_review"
    assert review["new_role"] is None
    assert review["semantic_transition_blocked"] == "card_family_to_message_item"


def test_structural_repair_cannot_recreate_the_same_rejected_semantic_role() -> None:
    review = enforce_focused_semantic_transition(
        {"region_id": "suspect_message", "role": "message_item", "parent_label": "detail pane"},
        {
            "region_id": "suspect_message",
            "decision": "remove",
            "new_role": None,
            "observed_role": "message_item",
            "geometry_quality": "overmerged",
            "parent_relation": "distinct_pane",
            "structural_repair": "stage1_repartition",
            "reason": "source group is not one coherent semantic unit",
        },
    )

    assert review["decision"] == "needs_human_review"
    assert review["structural_repair"] == "none"
    assert review["semantic_transition_blocked"] == "repair_recreates_rejected_role"


def test_overmerged_same_role_wrapper_with_preserved_members_is_removed_without_repartition() -> None:
    review = enforce_focused_semantic_transition(
        {
            "region_id": "suspect_message",
            "role": "message_item",
            "parent_label": "detail pane",
            "member_count": 2,
        },
        {
            "region_id": "suspect_message",
            "decision": "remove",
            "new_role": None,
            "observed_role": "message_item",
            "geometry_quality": "overmerged",
            "parent_relation": "distinct_pane",
            "structural_repair": "stage1_repartition",
            "reason": "independent atomic children already preserve the visible evidence",
        },
    )

    assert review["decision"] == "remove"
    assert review["structural_repair"] == "none"
    assert review["semantic_transition_normalized"] == "overmerged_wrapper_children_reparented"


def test_exact_semantic_unit_remove_repartition_is_normalized_to_relabel() -> None:
    review = enforce_focused_semantic_transition(
        {"region_id": "settings_tile", "role": "tile_card_parent", "parent_label": "main content"},
        {
            "region_id": "settings_tile",
            "decision": "remove",
            "new_role": None,
            "observed_role": "card",
            "geometry_quality": "exact_semantic_unit",
            "parent_relation": "valid_child",
            "structural_repair": "stage1_repartition",
            "reason": "the pixels already form one coherent card",
        },
    )

    assert review["decision"] == "relabel"
    assert review["new_role"] == "card"
    assert review["structural_repair"] == "none"
    assert review["semantic_transition_normalized"] == "exact_unit_relabel_in_place"


def test_overmerged_wrapper_does_not_rebuild_same_atomic_union() -> None:
    review = enforce_focused_semantic_transition(
        {"region_id": "overmerged_wrapper", "role": "tile_card_parent", "parent_label": "main content"},
        {
            "region_id": "overmerged_wrapper",
            "decision": "remove",
            "new_role": None,
            "observed_role": "list_container",
            "geometry_quality": "overmerged",
            "parent_relation": "valid_child",
            "structural_repair": "stage1_repartition",
            "reason": "independent children are already preserved",
        },
    )

    assert review["decision"] == "remove"
    assert review["new_role"] is None
    assert review["structural_repair"] == "none"
    assert review["semantic_transition_normalized"] == "overmerged_wrapper_children_reparented"


def test_focused_review_evidence_removes_overmerged_wrapper_and_routes_distinct_pane() -> None:
    parsed = parse_focused_group_review_response(
        '{"region_id":"false_card","decision":"relabel","new_role":"member_list",'
        '"observed_role":"member_list","geometry_quality":"overmerged",'
        '"parent_relation":"distinct_pane","structural_repair":"none",'
        '"reason":"multiple independent rows in a separate pane"}',
        expected_region_id="false_card",
    )

    assert parsed["decision"] == "remove"
    assert parsed["new_role"] is None
    assert parsed["observed_role"] == "member_list"
    assert parsed["structural_repair"] == "stage1_repartition"

    merged = merge_focused_group_reviews(
        stage2=_stage2(),
        base_patch={
            "group_reviews": [
                {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "base"},
                {"region_id": "real_message_group", "decision": "keep", "new_role": None, "reason": "base"},
            ],
            "missing": [],
        },
        focused_reviews=[parsed],
    )
    assert merged["group_reviews"][0]["decision"] == "remove"
    assert merged["missing"][0]["expected_role"] == "member_list"


def test_focused_missing_repairs_keep_the_more_complete_containing_roi() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"][0]["bbox"] = {
        "x": 300,
        "y": 200,
        "w": 200,
        "h": 100,
    }
    stage2["regions"][0]["subregion_groups"].append(
        {
            "group_id": "large_code_pane",
            "role": "message_item",
            "label": "misclassified code pane",
            "bbox": {"x": 240, "y": 120, "w": 560, "h": 620},
            "member_item_ids": ["message_1"],
        }
    )
    merged = merge_focused_group_reviews(
        stage2=stage2,
        base_patch={
            "group_reviews": [
                {
                    "region_id": group["group_id"],
                    "decision": "keep",
                    "new_role": None,
                    "reason": "baseline",
                }
                for group in stage2["regions"][0]["subregion_groups"]
            ],
            "missing": [],
        },
        focused_reviews=[
            {
                "region_id": "false_card",
                "decision": "remove",
                "new_role": None,
                "observed_role": "content_region",
                "geometry_quality": "overmerged",
                "parent_relation": "distinct_pane",
                "structural_repair": "stage1_repartition",
                "reason": "small fragment",
            },
            {
                "region_id": "large_code_pane",
                "decision": "remove",
                "new_role": None,
                "observed_role": "content_region",
                "geometry_quality": "overmerged",
                "parent_relation": "distinct_pane",
                "structural_repair": "stage1_repartition",
                "reason": "complete pane",
            },
        ],
    )

    assert len(merged["missing"]) == 1
    assert merged["missing"][0]["rough_roi"] == {"x": 240, "y": 120, "w": 560, "h": 620}


def test_removed_aligned_list_fragments_create_one_stage1_repartition_request() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["bbox"] = {"x": 0, "y": 0, "w": 900, "h": 900}
    stage2["regions"][0]["subregion_groups"] = [
        {
            "group_id": f"right_list_{index}",
            "role": "tile_card_parent",
            "bbox": {"x": 720, "y": index * 300, "w": 180, "h": 300},
            "member_item_ids": [f"row_{index}"],
        }
        for index in range(3)
    ]
    base_patch = {
        "group_reviews": [
            {"region_id": f"right_list_{index}", "decision": "keep", "new_role": None, "reason": "base"}
            for index in range(3)
        ],
        "missing": [],
    }
    focused = [
        {
            "region_id": f"right_list_{index}",
            "decision": "remove",
            "new_role": None,
            "observed_role": "member_list",
            "geometry_quality": "overmerged",
            "parent_relation": "valid_child",
            "structural_repair": "none",
            "reason": "member rows represented by an invalid wrapper",
        }
        for index in range(3)
    ]

    merged = merge_focused_group_reviews(stage2=stage2, base_patch=base_patch, focused_reviews=focused)

    assert merged["missing"] == [
        {
            "description": "Recover edge-aligned member_list from removed review fragments",
            "parent_region_id": "message_thread",
            "expected_role": "member_list",
            "rough_roi": {"x": 720, "y": 0, "w": 180, "h": 900},
            "repair_route": "stage1_repartition",
            "reason": "multiple removed list fragments form one continuous edge pane",
        }
    ]


def test_review_scoring_reports_before_after_alignment_and_missing_recall() -> None:
    stage2 = _stage2()
    patch = validate_review_patch(
        stage2,
        {
            "keep": [{"region_id": "real_message_group", "reason": "valid message"}],
            "remove": [{"region_id": "false_card", "reason": "member list is not a card"}],
            "relabel": [{"region_id": "message_1", "new_role": "list_item", "reason": "row"}],
            "missing": [
                {
                    "description": "right member list",
                    "parent_region_id": "message_thread",
                    "expected_role": "member_list",
                    "rough_roi": {"x": 700, "y": 0, "w": 200, "h": 900},
                    "repair_route": "stage1_repartition",
                    "reason": "missing structural child",
                }
            ],
            "needs_human_review": [],
        },
    )
    reviewed = apply_review_patch(stage2, patch)
    adjudication = {
        "region_expectations": {
            "false_card": "__remove__",
            "real_message_group": "message_item",
            "message_1": "list_item",
        },
        "missing_expectations": [
            {
                "parent_region_id": "message_thread",
                "expected_role": "member_list",
                "repair_route": "stage1_repartition",
            }
        ],
    }

    score = score_review_against_adjudication(stage2, reviewed, adjudication)

    assert score["adjudicated_region_alignment"]["before"] == {"passed": 1, "attempted": 3, "rate": 0.3333}
    assert score["adjudicated_region_alignment"]["after"] == {"passed": 3, "attempted": 3, "rate": 1.0}
    assert score["adjudicated_region_alignment"]["delta"] == 0.6667
    assert score["missing_target_recall"]["before"]["rate"] == 0.0
    assert score["missing_target_recall"]["after"]["rate"] == 1.0
    assert "not general recognition accuracy" in score["interpretation"]


def test_review_overlay_renders_reviewed_and_diff_images(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"].append(
        {
            "item_id": "ungrouped_control",
            "number": "3.2",
            "role": "toolbar",
            "bbox": {"x": 20, "y": 20, "w": 80, "h": 30},
        }
    )
    patch = validate_review_patch(
        stage2,
        {
            "keep": [],
            "remove": [{"region_id": "false_card", "reason": "wrong card"}],
            "relabel": [{"region_id": "message_1", "new_role": "list_item", "reason": "row"}],
            "missing": [
                {
                    "description": "right member list",
                    "parent_region_id": "message_thread",
                    "expected_role": "member_list",
                    "rough_roi": {"x": 700, "y": 0, "w": 200, "h": 900},
                    "repair_route": "stage1_repartition",
                    "reason": "missing pane",
                }
            ],
            "needs_human_review": [],
        },
    )
    reviewed = apply_review_patch(stage2, patch)

    result = render_review_overlays(
        screenshot_path=screenshot,
        before_stage2=stage2,
        after_stage2=reviewed,
        validated_patch=patch,
        out_dir=tmp_path / "overlays",
    )

    assert Path(result["reviewed_overlay_path"]).exists()
    assert Path(result["diff_overlay_path"]).exists()
    assert result["suppressed_grouped_atomic_item_count"] == 0
    assert result["rendered_grouped_atomic_item_count"] == 1
    assert result["unlabeled_atomic_item_count"] == 2
    assert "real_message_group" in result["rendered_semantic_region_ids"]
    assert "message_1" in result["rendered_semantic_region_ids"]
    assert "ungrouped_control" in result["rendered_semantic_region_ids"]
    assert Image.open(result["reviewed_overlay_path"]).getbbox() is not None
    assert Image.open(result["diff_overlay_path"]).getbbox() is not None


def test_review_overlay_preserves_and_renders_atomic_control_parents(tmp_path: Path) -> None:
    screenshot = tmp_path / "control_parent_screen.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"] = [
        {
            "item_id": "avatar_1",
            "number": "1.1",
            "label": "Avatar",
            "role": "icon",
            "bbox": {"x": 300, "y": 300, "w": 48, "h": 48},
        },
        {
            "item_id": "title_1",
            "number": "1.2",
            "label": "Conversation title",
            "role": "text",
            "bbox": {"x": 360, "y": 310, "w": 160, "h": 20},
        },
        {
            "item_id": "unmatched_action",
            "number": "1.3",
            "label": "New chat",
            "role": "button",
            "bbox": {"x": 700, "y": 40, "w": 80, "h": 34},
        },
    ]
    stage2["regions"][0]["control_parents"] = [
        {
            "object_id": "control_parent_row_1",
            "label": "Conversation row",
            "role": "atomic_control_parent",
            "bbox": {"x": 300, "y": 300, "w": 240, "h": 52},
            "member_object_ids": ["avatar_1", "title_1"],
            "source": "repeated_visual_anchor_with_row_evidence",
            "review_only": True,
        }
    ]

    result = render_review_overlays(
        screenshot_path=screenshot,
        before_stage2=stage2,
        after_stage2=stage2,
        validated_patch={"keep": [], "remove": [], "relabel": [], "missing": []},
        out_dir=tmp_path / "control_parent_overlays",
    )

    assert result["rendered_control_parent_count"] == 1
    assert result["rendered_control_parent_ids"] == ["control_parent_row_1"]
    assert result["suppressed_control_parent_member_count"] == 2
    assert result["suppressed_control_parent_member_ids"] == ["avatar_1", "title_1"]
    assert result["unlabeled_atomic_item_count"] == 1
    assert "avatar_1" not in result["rendered_semantic_region_ids"]
    assert "title_1" not in result["rendered_semantic_region_ids"]
    assert "unmatched_action" in result["rendered_semantic_region_ids"]
    with Image.open(result["reviewed_overlay_path"]) as rendered:
        assert rendered.getpixel((300, 300)) == (0, 158, 115)


def test_review_overlay_does_not_redraw_explicitly_suppressed_atomic_item(tmp_path: Path) -> None:
    screenshot = tmp_path / "suppressed_atomic_screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot)
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"] = [
        {
            "item_id": "stale_uia_text",
            "number": "1.1",
            "label": "stale",
            "role": "text",
            "bbox": {"x": 100, "y": 100, "w": 80, "h": 20},
            "render_in_main_overlay": False,
        }
    ]
    stage2["regions"][0]["subregion_groups"] = []

    result = render_review_overlays(
        screenshot_path=screenshot,
        before_stage2=stage2,
        after_stage2=stage2,
        validated_patch={"keep": [], "remove": [], "relabel": [], "missing": []},
        out_dir=tmp_path / "suppressed_overlays",
    )

    assert "stale_uia_text" not in result["rendered_semantic_region_ids"]
    assert result["suppressed_explicit_atomic_item_count"] == 1
    assert result["unlabeled_atomic_item_count"] == 0


def test_review_overlay_does_not_redraw_explicitly_suppressed_group(tmp_path: Path) -> None:
    screenshot = tmp_path / "suppressed_group_screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot)
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"] = []
    stage2["regions"][0]["subregion_groups"] = [
        {
            "group_id": "stale_review_group",
            "label": "stale review group",
            "role": "ungrouped_review_region",
            "bbox": {"x": 100, "y": 100, "w": 80, "h": 20},
            "member_item_ids": ["stale_uia_text"],
            "render_in_main_overlay": False,
        }
    ]

    result = render_review_overlays(
        screenshot_path=screenshot,
        before_stage2=stage2,
        after_stage2=stage2,
        validated_patch={"keep": [], "remove": [], "relabel": [], "missing": []},
        out_dir=tmp_path / "suppressed_group_overlays",
    )

    assert "stale_review_group" not in result["rendered_semantic_region_ids"]
    assert result["suppressed_explicit_group_count"] == 1


def test_model_review_input_overlay_draws_only_roots_and_group_aliases(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)

    result = render_model_review_input_overlay(screenshot, _stage2(), tmp_path / "review_input.png")

    assert Path(result["overlay_path"]).exists()
    assert result["review_id_map"] == {
        "G01": "false_card",
        "G02": "real_message_group",
    }
    assert result["group_count"] == 2


def test_missing_region_audit_overlay_does_not_draw_stage1_roots_as_coverage(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)

    result = render_model_review_input_overlay(
        screenshot,
        _stage2(),
        tmp_path / "missing_audit.png",
        include_stage1_roots=False,
    )

    assert result["stage1_root_boxes_rendered"] == 0
    with Image.open(result["overlay_path"]) as rendered:
        assert rendered.getpixel((400, 0)) == (255, 255, 255)
        assert rendered.getpixel((720, 100)) != (255, 255, 255)


def test_missing_region_candidates_cluster_uncovered_atomic_evidence() -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "label": "Main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                "numbered_items": [
                    {"item_id": "owned", "role": "text", "bbox": {"x": 20, "y": 20, "w": 100, "h": 40}},
                    {"item_id": "missing_a", "role": "card", "bbox": {"x": 200, "y": 200, "w": 200, "h": 100}},
                    {"item_id": "missing_b", "role": "card", "bbox": {"x": 420, "y": 200, "w": 200, "h": 100}},
                    {"item_id": "noise", "role": "text", "bbox": {"x": 990, "y": 790, "w": 5, "h": 5}},
                ],
                "subregion_groups": [
                    {
                        "group_id": "existing",
                        "role": "content_region",
                        "bbox": {"x": 10, "y": 10, "w": 150, "h": 80},
                        "member_item_ids": ["owned"],
                    }
                ],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert result["contract_version"] == "learning_missing_region_candidates_v1"
    assert result["candidate_count"] == 1
    assert result["candidates"] == [
        {
            "candidate_id": "M01",
            "parent_region_id": "main",
                "rough_roi": {"x": 200, "y": 200, "w": 420, "h": 100},
                "member_item_ids": ["missing_a", "missing_b"],
                "source_role_counts": {"card": 2},
                "evidence_family": "visual_card",
                "generation_source": "uncovered_atomic_evidence_cluster_v2",
            }
        ]
    assert result["display_only"] is True
    assert result["artifact_is_authorization"] is False


def test_missing_region_candidates_do_not_recall_explicitly_suppressed_evidence() -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                "numbered_items": [
                    {
                        "item_id": "stale_a",
                        "role": "text",
                        "bbox": {"x": 200, "y": 200, "w": 200, "h": 40},
                        "render_in_main_overlay": False,
                    },
                    {
                        "item_id": "stale_b",
                        "role": "text",
                        "bbox": {"x": 420, "y": 200, "w": 200, "h": 40},
                        "render_in_main_overlay": False,
                    },
                ],
                "subregion_groups": [],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert result["candidate_count"] == 0
    assert result["suppressed_explicit_item_count"] == 2


def test_missing_region_candidates_do_not_bridge_separate_large_card_rows() -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                "numbered_items": [
                    {"item_id": "a1", "role": "media_card", "bbox": {"x": 50, "y": 100, "w": 200, "h": 150}},
                    {"item_id": "a2", "role": "media_card", "bbox": {"x": 270, "y": 100, "w": 200, "h": 150}},
                    {"item_id": "b1", "role": "media_card", "bbox": {"x": 50, "y": 350, "w": 200, "h": 150}},
                    {"item_id": "b2", "role": "media_card", "bbox": {"x": 270, "y": 350, "w": 200, "h": 150}},
                ],
                "subregion_groups": [],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert [item["member_item_ids"] for item in result["candidates"]] == [
        ["a1", "a2"],
        ["b1", "b2"],
    ]


def test_missing_region_candidate_budget_keeps_large_late_region_over_early_noise() -> None:
    items = [
        {
            "item_id": f"noise_{index}",
            "role": f"other_{index}",
            "bbox": {"x": 10 + (index % 8) * 110, "y": 20 + (index // 8) * 80, "w": 40, "h": 30},
        }
        for index in range(16)
    ]
    items.append(
        {
            "item_id": "late_row",
            "role": "dataitem",
            "bbox": {"x": 100, "y": 700, "w": 800, "h": 100},
        }
    )
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 1000},
                "numbered_items": items,
                "subregion_groups": [],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert result["raw_candidate_count"] == 17
    assert result["truncated_candidate_count"] == 1
    assert any("late_row" in item["member_item_ids"] for item in result["candidates"])


def test_missing_region_candidates_are_not_suppressed_by_broad_unowned_parent() -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 1000},
                "numbered_items": [
                    {"item_id": "event_a", "role": "text", "bbox": {"x": 600, "y": 700, "w": 180, "h": 30}},
                    {"item_id": "event_b", "role": "text", "bbox": {"x": 600, "y": 745, "w": 180, "h": 30}},
                ],
                "subregion_groups": [
                    {
                        "group_id": "broad_parent",
                        "role": "ungrouped_review_region",
                        "bbox": {"x": 100, "y": 600, "w": 800, "h": 350},
                        "member_item_ids": [],
                    }
                ],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert result["candidate_count"] == 1
    assert result["candidates"][0]["member_item_ids"] == ["event_a", "event_b"]


def test_missing_region_candidate_is_suppressed_by_near_duplicate_existing_box() -> None:
    stage2 = {
        "regions": [
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 1000},
                "numbered_items": [
                    {"item_id": "duplicate", "role": "card", "bbox": {"x": 100, "y": 100, "w": 300, "h": 200}},
                ],
                "subregion_groups": [
                    {
                        "group_id": "existing_card",
                        "role": "card",
                        "bbox": {"x": 95, "y": 95, "w": 310, "h": 210},
                        "member_item_ids": [],
                    }
                ],
            }
        ]
    }

    result = model_review_module.build_missing_region_candidates(stage2)

    assert result["candidate_count"] == 0


def test_missing_region_audit_selection_uses_program_candidate_geometry() -> None:
    candidates = {
        "contract_version": "learning_missing_region_candidates_v1",
        "candidates": [
            {
                "candidate_id": "M01",
                "parent_region_id": "main",
                "rough_roi": {"x": 200, "y": 200, "w": 420, "h": 100},
                "member_item_ids": ["missing_a", "missing_b"],
                "source_role_counts": {"card": 2},
                "generation_source": "uncovered_atomic_evidence_cluster_v1",
            }
        ],
    }
    audit = {
        "missing": [
            {
                "candidate_id": "M01",
                "description": "visible card row",
                "expected_role": "list_container",
                "repair_route": "precise_locator",
                "reason": "coherent uncovered repeated row",
            }
        ]
    }

    resolved = model_review_module.resolve_missing_region_audit_candidates(audit, candidates)

    assert resolved == {
        "missing": [
            {
                "description": "visible card row",
                "parent_region_id": "main",
                "expected_role": "list_container",
                "rough_roi": {"x": 200, "y": 200, "w": 420, "h": 100},
                "repair_route": "precise_locator",
                "reason": "coherent uncovered repeated row",
                "candidate_id": "M01",
                "candidate_member_item_ids": ["missing_a", "missing_b"],
                "geometry_source": "uncovered_atomic_evidence_cluster_v1",
            }
        ]
    }


def test_missing_region_candidate_review_accepts_only_binary_program_candidate_decision() -> None:
    stage2 = _stage2()
    candidate = {
        "candidate_id": "M12",
        "parent_region_id": "message_thread",
        "rough_roi": {"x": 600, "y": 650, "w": 250, "h": 150},
        "member_item_ids": ["missing_member_list_evidence"],
        "source_role_counts": {"list_item": 1},
        "evidence_family": "list_content",
        "generation_source": "uncovered_atomic_evidence_cluster_v2",
    }

    prompt = model_review_module.build_missing_region_candidate_review_prompt(stage2, candidate)
    parsed = model_review_module.parse_missing_region_candidate_review_response(
        json.dumps(
            {
                "candidate_id": "M12",
                "decision": "accept_candidate",
                "description": "right-side member list",
                "expected_role": "member_list",
                "repair_route": "precise_locator",
                "reason": "coherent repeated member rows",
            }
        ),
        expected_candidate_id="M12",
    )

    assert "Audit exactly one magenta GUI proposal M12" in prompt
    assert "not an accepted semantic region" in prompt
    assert parsed["decision"] == "accept_candidate"
    assert parsed["expected_role"] == "member_list"


def test_missing_candidate_consolidation_merges_overlapping_multimodal_evidence() -> None:
    bundle = {
        "contract_version": "learning_missing_region_candidates_v1",
        "candidates": [
            {
                "candidate_id": "M11",
                "parent_region_id": "conversation_list",
                "rough_roi": {"x": 73, "y": 151, "w": 320, "h": 43},
                "member_item_ids": ["uia_filter_group", "uia_all", "uia_unread"],
                "source_role_counts": {"tab": 3},
                "evidence_family": "navigation",
                "generation_source": "uncovered_atomic_evidence_cluster_v2",
            },
            {
                "candidate_id": "M13",
                "parent_region_id": "conversation_list",
                "rough_roi": {"x": 102, "y": 158, "w": 190, "h": 24},
                "member_item_ids": ["ocr_all", "ocr_unread"],
                "source_role_counts": {"text": 2},
                "evidence_family": "text",
                "generation_source": "uncovered_atomic_evidence_cluster_v2",
            },
        ],
        "candidate_count": 2,
    }

    result = model_review_module.consolidate_missing_region_candidates(bundle)

    assert result["candidate_count"] == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_id"] == "M11"
    assert candidate["merged_candidate_ids"] == ["M11", "M13"]
    assert candidate["member_item_ids"] == [
        "ocr_all",
        "ocr_unread",
        "uia_all",
        "uia_filter_group",
        "uia_unread",
    ]
    assert candidate["source_role_counts"] == {"tab": 3, "text": 2}
    assert candidate["evidence_families"] == ["navigation", "text"]
    assert candidate["rough_roi"] == {"x": 73, "y": 151, "w": 320, "h": 43}


@pytest.mark.parametrize(
    ("source_role_counts", "model_role", "expected_decision", "expected_role"),
    [
        ({"input": 1}, "list_item", "accept_candidate", "input_region"),
        ({"tab": 3, "text": 2}, "content_region", "accept_candidate", "navigation"),
        ({"status_bar_evidence": 1, "text": 2}, "navigation", "accept_candidate", "review_only"),
        ({"group": 1}, "input_region", "reject_candidate", "review_only"),
    ],
)
def test_missing_candidate_decision_policy_uses_atomic_evidence_roles(
    source_role_counts: dict[str, int],
    model_role: str,
    expected_decision: str,
    expected_role: str,
) -> None:
    candidate = {
        "candidate_id": "M01",
        "parent_region_id": "main",
        "rough_roi": {"x": 10, "y": 20, "w": 200, "h": 40},
        "member_item_ids": ["evidence_a"],
        "source_role_counts": source_role_counts,
        "evidence_family": "other",
    }
    decision = {
        "candidate_id": "M01",
        "decision": "accept_candidate",
        "description": "model description",
        "expected_role": model_role,
        "repair_route": "precise_locator",
        "reason": "model reason",
    }

    result = model_review_module.enforce_missing_candidate_decision_policy(decision, candidate)

    assert result["decision"] == expected_decision
    assert result["expected_role"] == expected_role
    assert result["model_expected_role"] == model_role
    assert result["policy_adjustment"]


@pytest.mark.parametrize(
    ("parent_region_id", "source_role_counts", "member_item_ids", "model_role", "expected_decision"),
    [
        ("structure_region_left_nav", {"nav_item": 3}, ["a", "b", "c"], "navigation", "reject_candidate"),
        (
            "structure_region_main_content__stage1_5__conversation_list",
            {"text": 2},
            ["a", "b"],
            "message_item",
            "reject_candidate",
        ),
        (
            "structure_region_main_content__stage1_5__bottom_composer",
            {"text": 1},
            ["a"],
            "message_item",
            "reject_candidate",
        ),
        (
            "structure_region_main_content__stage1_5__message_thread",
            {"text": 1},
            ["a"],
            "message_item",
            "reject_candidate",
        ),
        (
            "structure_region_main_content__stage1_5__message_thread",
            {"text": 3},
            ["a", "b", "c"],
            "message_item",
            "accept_candidate",
        ),
    ],
)
def test_missing_candidate_policy_rejects_redundant_or_under_evidenced_regions(
    parent_region_id: str,
    source_role_counts: dict[str, int],
    member_item_ids: list[str],
    model_role: str,
    expected_decision: str,
) -> None:
    result = model_review_module.enforce_missing_candidate_decision_policy(
        {
            "candidate_id": "M01",
            "decision": "accept_candidate",
            "description": "model description",
            "expected_role": model_role,
            "repair_route": "precise_locator",
            "reason": "model reason",
        },
        {
            "candidate_id": "M01",
            "parent_region_id": parent_region_id,
            "member_item_ids": member_item_ids,
            "source_role_counts": source_role_counts,
            "evidence_family": "text",
        },
    )

    assert result["decision"] == expected_decision
    if expected_decision == "reject_candidate":
        assert result["expected_role"] == "review_only"
        assert result["policy_adjustment"] != "none"


def test_status_bar_candidate_role_is_parsed_then_normalized_before_patch_validation() -> None:
    parsed = model_review_module.parse_missing_region_candidate_review_response(
        json.dumps(
            {
                "candidate_id": "M01",
                "decision": "accept_candidate",
                "description": "editor status information",
                "expected_role": "status_bar",
                "repair_route": "precise_locator",
                "reason": "coherent bottom status information",
            }
        ),
        expected_candidate_id="M01",
    )
    result = model_review_module.enforce_missing_candidate_decision_policy(
        parsed,
        {
            "candidate_id": "M01",
            "source_role_counts": {"status_bar_evidence": 1, "text": 2},
        },
    )

    assert result["model_expected_role"] == "status_bar"
    assert result["expected_role"] == "review_only"
    assert result["decision"] == "accept_candidate"


def test_conversation_row_candidate_role_is_parsed_then_normalized() -> None:
    parsed = model_review_module.parse_missing_region_candidate_review_response(
        json.dumps(
            {
                "candidate_id": "M10",
                "decision": "accept_candidate",
                "description": "one complete conversation row",
                "expected_role": "conversation_row",
                "repair_route": "precise_locator",
                "reason": "avatar, title, preview and timestamp form one row",
            }
        ),
        expected_candidate_id="M10",
    )
    result = model_review_module.enforce_missing_candidate_decision_policy(
        parsed,
        {
            "candidate_id": "M10",
            "source_role_counts": {"text": 3, "image": 1},
        },
    )

    assert result["model_expected_role"] == "conversation_row"
    assert result["expected_role"] == "list_item"
    assert result["decision"] == "accept_candidate"


def test_missing_region_candidate_review_prompt_excludes_unrelated_full_page_groups() -> None:
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].extend(
        {
            "group_id": f"unrelated_{index}",
            "role": "content_region",
            "label": "unrelated evidence " + ("x" * 200),
            "bbox": {"x": 10, "y": 700 + index * 2, "w": 100, "h": 20},
            "member_item_ids": [],
        }
        for index in range(100)
    )
    candidate = {
        "candidate_id": "M12",
        "parent_region_id": "message_thread",
        "rough_roi": {"x": 600, "y": 650, "w": 250, "h": 150},
        "member_item_ids": ["missing_member_list_evidence"],
        "source_role_counts": {"list_item": 1},
        "evidence_family": "list_content",
        "generation_source": "uncovered_atomic_evidence_cluster_v2",
    }

    prompt = model_review_module.build_missing_region_candidate_review_prompt(stage2, candidate)

    assert len(prompt) < 5_000
    assert "unrelated_99" not in prompt
    assert "Parent and local overlap context" in prompt


def test_missing_region_candidate_review_rejects_model_owned_geometry() -> None:
    with pytest.raises(ValueError, match="exactly the required fields"):
        model_review_module.parse_missing_region_candidate_review_response(
            json.dumps(
                {
                    "candidate_id": "M12",
                    "decision": "accept_candidate",
                    "description": "member list",
                    "expected_role": "member_list",
                    "repair_route": "precise_locator",
                    "reason": "coherent rows",
                    "rough_roi": {"x": 1, "y": 2, "w": 3, "h": 4},
                }
            ),
            expected_candidate_id="M12",
        )


def test_missing_region_candidate_review_normalizes_none_role_only_for_rejection() -> None:
    parsed = model_review_module.parse_missing_region_candidate_review_response(
        json.dumps(
            {
                "candidate_id": "M04",
                "decision": "reject_candidate",
                "description": "isolated decorative control",
                "expected_role": "none",
                "repair_route": "precise_locator",
                "reason": "not a reusable semantic unit",
            }
        ),
        expected_candidate_id="M04",
    )

    assert parsed["expected_role"] == "review_only"

    with pytest.raises(ValueError, match="expected_role"):
        model_review_module.parse_missing_region_candidate_review_response(
            json.dumps(
                {
                    "candidate_id": "M04",
                    "decision": "accept_candidate",
                    "description": "unknown unit",
                    "expected_role": "none",
                    "repair_route": "precise_locator",
                    "reason": "invalid accepted role",
                }
            ),
            expected_candidate_id="M04",
        )


def test_missing_region_candidate_rejection_ignores_unsupported_provisional_role() -> None:
    parsed = model_review_module.parse_missing_region_candidate_review_response(
        json.dumps(
            {
                "candidate_id": "M04",
                "decision": "reject_candidate",
                "description": "isolated button without a reusable semantic group",
                "expected_role": "button",
                "repair_route": "precise_locator",
                "reason": "the candidate must not be promoted into a region",
            }
        ),
        expected_candidate_id="M04",
    )

    assert parsed["decision"] == "reject_candidate"
    assert parsed["expected_role"] == "review_only"


def test_missing_region_candidates_exclude_geometry_already_covered_by_repair() -> None:
    candidates = {
        "contract_version": "learning_missing_region_candidates_v1",
        "candidate_count": 2,
        "candidates": [
            {
                "candidate_id": "M09",
                "rough_roi": {"x": 100, "y": 200, "w": 800, "h": 300},
            },
            {
                "candidate_id": "M12",
                "rough_roi": {"x": 100, "y": 600, "w": 800, "h": 220},
            },
        ],
    }
    review_patch = {
        "missing": [
            {
                "rough_roi": {"x": 90, "y": 180, "w": 850, "h": 340},
                "repair_route": "stage1_repartition",
            }
        ]
    }

    result = model_review_module.exclude_candidates_covered_by_missing_repairs(candidates, review_patch)

    assert result["candidate_count"] == 1
    assert [item["candidate_id"] for item in result["candidates"]] == ["M12"]
    assert result["excluded_candidate_ids"] == ["M09"]


def test_focused_group_overlay_isolates_target_and_adds_magnified_crop(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    record = focused_card_review_records(_stage2())[0]

    result = render_focused_group_review_overlay(screenshot, record, tmp_path / "focused.png")

    with Image.open(result["overlay_path"]) as rendered:
        assert rendered.width > 1000
        assert rendered.height == 1000
    assert result["target_region_id"] == "false_card"
    assert result["crop_bbox"] == {"x": 720, "y": 100, "w": 170, "h": 500}


def test_probe_writes_review_overlays_and_adjudication_score_from_recorded_output(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    source = {
        "two_stage_understanding": {
            "source_image_path": str(screenshot),
            "stage2_numbering": _stage2(),
            "fusion": {"compiled_overlay_path": str(overlay)},
        }
    }
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    recorded = tmp_path / "recorded.json"
    recorded.write_text(
        json.dumps(
            {
                "keep": [{"region_id": "real_message_group", "reason": "valid"}],
                "remove": [{"region_id": "false_card", "reason": "not a card"}],
                "relabel": [],
                "missing": [],
                "needs_human_review": [],
            }
        ),
        encoding="utf-8",
    )
    adjudication = tmp_path / "adjudication.json"
    adjudication.write_text(
        json.dumps(
            {
                "region_expectations": {
                    "false_card": "__remove__",
                    "real_message_group": "message_item",
                },
                "missing_expectations": [],
            }
        ),
        encoding="utf-8",
    )

    report = run_probe(
        stage2_json_path=source_path,
        out_dir=tmp_path / "out",
        recorded_response_path=recorded,
        adjudication_path=adjudication,
    )

    assert Path(report["reviewed_overlay_path"]).exists()
    assert Path(report["diff_overlay_path"]).exists()
    assert Path(report["model_review_input_overlay_path"]).exists()
    assert report["model_review_input_group_count"] == 2
    assert report["adjudication"]["adjudicated_region_alignment"]["after"]["rate"] == 1.0
    assert report["source_type"] == "recorded_model_output"
    assert report["actual_model_call"] is False
    assert report["workflow_state"] == "completed_review_only"
    assert report["replacement_integrity_gate"]["passed"] is True


def test_probe_excludes_valid_deterministic_leaf_rows_from_model_review_scope(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    stage2 = _stage2()
    stage2["regions"][0]["subregion_groups"].append(
        {
            "group_id": "table_row_1",
            "role": "table_row",
            "label": "one file row",
            "bbox": {"x": 210, "y": 300, "w": 600, "h": 34},
            "member_item_ids": ["name", "date", "type"],
        }
    )
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "source_image_path": str(screenshot),
                    "stage2_numbering": stage2,
                    "fusion": {"compiled_overlay_path": str(overlay)},
                }
            }
        ),
        encoding="utf-8",
    )
    recorded = tmp_path / "recorded.json"
    recorded.write_text(
        json.dumps(
            {
                "group_reviews": [
                    {"region_id": "false_card", "decision": "remove", "new_role": None, "reason": "bad"},
                    {
                        "region_id": "real_message_group",
                        "decision": "keep",
                        "new_role": None,
                        "reason": "good",
                    },
                ],
                "missing": [],
            }
        ),
        encoding="utf-8",
    )

    report = run_probe(
        stage2_json_path=source_path,
        out_dir=tmp_path / "out",
        recorded_response_path=recorded,
    )

    assert report["model_review_scope"] == {
        "contract_version": "learning_model_review_scope_v1",
        "source_group_count": 3,
        "model_group_count": 2,
        "deterministic_keep_count": 1,
        "deterministic_keep_roles": {"table_row": 1},
        "interpretation": "deterministic leaf invariants are not model review decisions",
    }
    assert report["model_review_input_group_count"] == 2
    assert report["workflow_state"] == "completed_review_only"
    validated = json.loads(Path(report["validated_review_patch_path"]).read_text(encoding="utf-8"))
    by_id = {item["region_id"]: item for item in validated["keep"]}
    assert by_id["table_row_1"]["review_source"] == "deterministic_leaf_invariant"


def test_probe_actual_call_runs_focused_card_review_and_reports_protocol_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    source = {
        "two_stage_understanding": {
            "source_image_path": str(screenshot),
            "stage2_numbering": _stage2(),
            "fusion": {"compiled_overlay_path": str(overlay)},
        }
    }
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
    adjudication = tmp_path / "adjudication.json"
    adjudication.write_text(
        json.dumps(
            {
                "region_expectations": {
                    "false_card": "member_list",
                    "real_message_group": "message_item",
                },
                "missing_expectations": [
                    {
                        "parent_region_id": "message_thread",
                        "expected_role": "member_list",
                        "repair_route": "stage1_repartition",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    model_images: list[str] = []

    def fake_model_call(**kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        model_images.append(str(kwargs["image_path"]))
        if "Audit uncovered visible GUI regions only" in prompt:
            content = {"missing": []}
        elif "Audit exactly one highlighted GUI group" in prompt:
            if "Exact region_id: G01" in prompt:
                content = {
                    "region_id": "G01",
                    "decision": "relabel",
                    "new_role": "member_list",
                    "observed_role": "member_list",
                    "geometry_quality": "exact_semantic_unit",
                    "parent_relation": "valid_child",
                    "structural_repair": "stage1_repartition",
                    "reason": "many independent member rows",
                }
            else:
                content = {
                    "region_id": "G02",
                    "decision": "keep",
                    "new_role": None,
                    "observed_role": "message_item",
                    "geometry_quality": "exact_semantic_unit",
                    "parent_relation": "valid_child",
                    "structural_repair": "none",
                    "reason": "one coherent message",
                }
        else:
            content = {
                "group_reviews": [
                    {"region_id": "G01", "decision": "keep", "new_role": None, "reason": "uncertain"},
                    {
                        "region_id": "G02",
                        "decision": "keep",
                        "new_role": None,
                        "reason": "one message",
                    },
                ],
                "missing": [],
            }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr("scripts.run_learning_overlay_model_review_probe._call_model", fake_model_call)
    report = run_probe(
        stage2_json_path=source_path,
        out_dir=tmp_path / "out",
        adjudication_path=adjudication,
    )

    assert report["focused_review"] == {
        "attempted": 2,
        "parsed": 2,
        "protocol_failed": 0,
        "candidate_roles": sorted(FOCUSED_CARD_REVIEW_ROLES),
    }
    assert report["adjudication"]["adjudicated_region_alignment"]["before"]["passed"] == 1
    assert report["adjudication"]["adjudicated_region_alignment"]["after"]["passed"] == 2
    assert report["adjudication"]["missing_target_recall"]["after"]["passed"] == 1
    assert len(list((tmp_path / "out" / "focused_reviews").glob("*_raw.txt"))) == 2
    assert model_images[0].endswith("model_review_input_overlay.png")
    assert model_images[1].endswith("_focused_overlay.png")
    assert model_images[2].endswith("_focused_overlay.png")
    assert report["missing_region_audit"]["candidate_count"] == 0
    assert report["missing_region_audit"]["attempted"] is False
    assert report["workflow_state"] == "repair_pending"
    assert report["completed_review_only"] is False
    assert report["repair_pending_count"] == 1
    assert report["prompt_version"] == "learning_overlay_model_review_prompt_v3"
    assert report["schema_version"] == "learning_model_review_patch_v1"
    assert report["parser_version"] == "learning_model_review_parser_v1"
    assert report["inference_parameters"] == {
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": "json_object",
    }
    assert len(report["input_capture_sha256"]) == 64


def test_probe_runs_independent_missing_region_audit_after_group_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    stage2 = _stage2()
    stage2["regions"][0]["numbered_items"].append(
        {
            "item_id": "missing_member_list_evidence",
            "role": "list_item",
            "bbox": {"x": 600, "y": 650, "w": 250, "h": 150},
        }
    )
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "source_image_path": str(screenshot),
                    "stage2_numbering": stage2,
                    "fusion": {"compiled_overlay_path": str(overlay)},
                }
            }
        ),
        encoding="utf-8",
    )
    prompts: list[str] = []

    def fake_model_call(**kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        prompts.append(prompt)
        if "Audit exactly one magenta GUI proposal" in prompt:
            content = {
                "candidate_id": "M01",
                "decision": "accept_candidate",
                "description": "right-side member list",
                "expected_role": "member_list",
                "repair_route": "stage1_repartition",
                "reason": "coherent pane has no semantic region",
            }
        elif "Audit exactly one highlighted GUI group" in prompt:
            region_id = "G01" if "Exact region_id: G01" in prompt else "G02"
            content = {
                "region_id": region_id,
                "decision": "keep",
                "new_role": None,
                "observed_role": "member_list" if region_id == "G01" else "message_item",
                "geometry_quality": "exact_semantic_unit",
                "parent_relation": "valid_child",
                "structural_repair": "none",
                "reason": "visible coherent region",
            }
        else:
            content = {
                "group_reviews": [
                    {"region_id": "G01", "decision": "keep", "new_role": None, "reason": "visible"},
                    {"region_id": "G02", "decision": "keep", "new_role": None, "reason": "visible"},
                ],
                "missing": [],
            }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr("scripts.run_learning_overlay_model_review_probe._call_model", fake_model_call)
    report = run_probe(stage2_json_path=source_path, out_dir=tmp_path / "out")

    validated = json.loads(Path(report["validated_review_patch_path"]).read_text(encoding="utf-8"))
    assert validated["missing"] == [
        {
            "description": "right-side member list",
            "parent_region_id": "message_thread",
            "expected_role": "member_list",
            "rough_roi": {"x": 600, "y": 650, "w": 250, "h": 150},
            "repair_route": "stage1_repartition",
            "reason": "coherent pane has no semantic region",
            "candidate_id": "M01",
            "candidate_member_item_ids": ["missing_member_list_evidence"],
            "geometry_source": "uncovered_atomic_evidence_cluster_v2",
        }
    ]
    assert any("Audit exactly one magenta GUI proposal" in prompt for prompt in prompts)
    assert report["missing_region_audit"]["attempted"] is True
    assert report["missing_region_audit"]["missing_count"] == 1
    assert report["workflow_state"] == "repair_pending"


def test_probe_retries_invalid_full_page_json_once_and_records_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    stage2 = _stage2()
    for group in stage2["regions"][0]["subregion_groups"]:
        group["role"] = "toolbar"
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "source_image_path": str(screenshot),
                    "stage2_numbering": stage2,
                    "fusion": {"compiled_overlay_path": str(overlay)},
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_model_call(**kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        if "Audit uncovered visible GUI regions only" in prompt:
            return {"choices": [{"message": {"content": json.dumps({"missing": []})}}]}
        if len(calls) == 1:
            content = '{"group_reviews":[{"region_id":"false_card"'
        else:
            content = json.dumps(
                {
                    "group_reviews": [
                        {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "valid"},
                        {
                            "region_id": "real_message_group",
                            "decision": "keep",
                            "new_role": None,
                            "reason": "valid",
                        },
                    ],
                    "missing": [],
                }
            )
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr("scripts.run_learning_overlay_model_review_probe._call_model", fake_model_call)
    report = run_probe(stage2_json_path=source_path, out_dir=tmp_path / "out")

    assert len(calls) == 2
    assert report["schema_repair_retry"] == {
        "attempted": True,
        "succeeded": True,
        "max_attempts": 1,
    }
    assert Path(tmp_path / "out" / "initial_parse_error.json").exists()
    assert Path(tmp_path / "out" / "schema_repair_raw_model_output.txt").exists()


def test_probe_reviews_omitted_groups_in_bounded_followup_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    stage2 = _stage2()
    for group in stage2["regions"][0]["subregion_groups"]:
        group["role"] = "toolbar"
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "source_image_path": str(screenshot),
                    "stage2_numbering": stage2,
                    "fusion": {"compiled_overlay_path": str(overlay)},
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_model_call(**kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        if "Audit uncovered visible GUI regions only" in prompt:
            return {"choices": [{"message": {"content": json.dumps({"missing": []})}}]}
        reviewed_id = "false_card" if len(calls) == 1 else "real_message_group"
        content = {
            "group_reviews": [
                {"region_id": reviewed_id, "decision": "keep", "new_role": None, "reason": "visible"}
            ],
            "missing": [],
        }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr("scripts.run_learning_overlay_model_review_probe._call_model", fake_model_call)
    report = run_probe(stage2_json_path=source_path, out_dir=tmp_path / "out")

    assert len(calls) == 2
    assert report["omitted_group_followup"] == {
        "attempted_groups": 1,
        "batch_count": 1,
        "resolved_groups": 1,
        "remaining_needs_human_review": 0,
        "batch_size": 8,
        "retry_round_count": 0,
    }
    assert report["workflow_state"] == "completed_review_only"
    assert Path(tmp_path / "out" / "omitted_group_followup" / "batch_01_raw.txt").exists()
    assert len(report["source_graph_revision"]) == 64


def test_probe_retries_only_protocol_omissions_with_smaller_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1000, 1000), "white").save(screenshot)
    Image.new("RGB", (1000, 1000), "white").save(overlay)
    stage2 = _stage2()
    for group in stage2["regions"][0]["subregion_groups"]:
        group["role"] = "toolbar"
    source_path = tmp_path / "trial_result.json"
    source_path.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "source_image_path": str(screenshot),
                    "stage2_numbering": stage2,
                    "fusion": {"compiled_overlay_path": str(overlay)},
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_model_call(**kwargs: object) -> dict:
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        if "Audit uncovered visible GUI regions only" in prompt:
            return {"choices": [{"message": {"content": json.dumps({"missing": []})}}]}
        if len(calls) == 1:
            reviews = [
                {"region_id": "false_card", "decision": "keep", "new_role": None, "reason": "visible"}
            ]
        elif len(calls) == 2:
            reviews = []
        else:
            reviews = [
                {
                    "region_id": "real_message_group",
                    "decision": "keep",
                    "new_role": None,
                    "reason": "visible in singleton retry",
                }
            ]
        return {"choices": [{"message": {"content": json.dumps({"group_reviews": reviews, "missing": []})}}]}

    monkeypatch.setattr("scripts.run_learning_overlay_model_review_probe._call_model", fake_model_call)
    report = run_probe(stage2_json_path=source_path, out_dir=tmp_path / "out")

    assert len(calls) == 3
    assert report["omitted_group_followup"] == {
        "attempted_groups": 1,
        "batch_count": 2,
        "resolved_groups": 1,
        "remaining_needs_human_review": 0,
        "batch_size": 8,
        "retry_round_count": 1,
    }
    assert report["workflow_state"] == "completed_review_only"
    assert Path(
        tmp_path / "out" / "omitted_group_followup" / "retry_01_batch_01_raw.txt"
    ).exists()
