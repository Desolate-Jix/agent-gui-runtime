from __future__ import annotations

import pytest

from app.api import vision as vision_api
from app.gate.actions import classify_action_taxonomy
from app.gate.candidates import (
    attach_candidate_freshness,
    validate_action_candidate_freshness,
    validate_action_candidate_target_at_point,
)
from app.gate.danger import scoped_final_submit_visible_blocker
from app.gate.dataflow import (
    merge_read_batch_into_detail_snapshot,
    put_latest_detail_snapshot,
    require_latest_detail_snapshot,
    with_detail_snapshot,
)
from app.gate.ocr import ocr_contextual_match
from app.gate.scroll import build_scroll_scope_invariant
from app.seek.application import assess_seek_application_flow_state
from app.recognition.schemas import LocalGroundingCandidateResult, LocalGroundingResult
from app.vision.schemas import ImageSize


def test_dataflow_requires_latest_detail_snapshot_for_downstream_steps() -> None:
    state: dict = {}
    first = with_detail_snapshot(
        {"title": "Generic Detail", "description_sections": [{"index": 0, "role": "body", "text": "Intro"}]},
        source="observe_detail",
    )
    put_latest_detail_snapshot(state, first)
    batch = {
        "contract_version": "read_region_batch_v1",
        "status": "ok",
        "stop_reason": "no_new_content",
        "unique_line_count": 1,
        "merged_text_lines": ["Required skill: C# integration"],
        "captures": [{"trace_path": "logs/traces/ocr.json"}],
    }
    latest = merge_read_batch_into_detail_snapshot(first, batch)
    put_latest_detail_snapshot(state, latest)

    require_latest_detail_snapshot(state, latest)
    with pytest.raises(ValueError, match="stale detail snapshot"):
        require_latest_detail_snapshot(state, first)
    assert any(section["text"] == "Required skill: C# integration" for section in latest["description_sections"])


def test_candidate_freshness_rejects_stale_capture_coordinates() -> None:
    candidate = attach_candidate_freshness(
        {
            "bbox": {"x": 10, "y": 20, "w": 100, "h": 40},
            "click_point": {"x": 50, "y": 40},
        },
        capture_id="capture-a",
        viewport_size={"width": 1280, "height": 720},
        source="path_graph_seed",
    )

    decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id="capture-b",
        current_viewport_size={"width": 1280, "height": 720},
    )

    assert decision["allowed"] is False
    assert "candidate_capture_id_stale" in decision["reasons"]


def test_candidate_target_validation_rejects_mutation_control_at_continue_point() -> None:
    decision = validate_action_candidate_target_at_point(
        {"x": 120, "y": 220},
        pre_click_decision={
            "selected_candidate_id": "model_prompt_candidate",
            "candidate_decisions": [
                {
                    "candidate_id": "model_prompt_candidate",
                    "resolved_click_point": {
                        "target_text": "Click the visible Continue button only",
                        "bbox": {"x": 100, "y": 200, "w": 160, "h": 50},
                    },
                },
                {
                    "candidate_id": "add_role_button",
                    "resolved_click_point": {
                        "target_text": "Add role",
                        "bbox": {"x": 105, "y": 205, "w": 120, "h": 42},
                    },
                },
            ],
        },
        allowed_labels={"continue", "save and continue"},
        forbidden_labels={"save", "cancel"},
        forbidden_label_prefixes=("add ", "edit "),
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "profile_mutation_candidate_at_click_point"
    assert decision["overlapping_forbidden_candidates"][0]["label"] == "add role"


def test_candidate_target_validation_allows_prompt_candidate_when_continue_overlaps() -> None:
    decision = validate_action_candidate_target_at_point(
        {"x": 120, "y": 220},
        pre_click_decision={
            "selected_candidate_id": "model_prompt_candidate",
            "candidate_decisions": [
                {
                    "candidate_id": "model_prompt_candidate",
                    "resolved_click_point": {
                        "target_text": "Click the visible Continue button only",
                        "bbox": {"x": 100, "y": 200, "w": 160, "h": 50},
                    },
                },
                {
                    "candidate_id": "continue_button",
                    "resolved_click_point": {
                        "target_text": "Continue",
                        "bbox": {"x": 105, "y": 205, "w": 120, "h": 42},
                    },
                },
            ],
        },
        allowed_labels={"continue", "save and continue"},
        forbidden_labels={"save", "cancel"},
        forbidden_label_prefixes=("add ", "edit "),
    )

    assert decision["allowed"] is True
    assert decision["reason"] == "visible_continue_candidate_at_click_point"
    assert decision["overlapping_allowed_candidates"][0]["candidate_id"] == "continue_button"


def test_recognition_trace_marks_stale_seed_refreshed_only_after_current_grounding(tmp_path) -> None:
    image = tmp_path / "current.png"
    image.write_bytes(b"fake")
    seed = attach_candidate_freshness(
        {
            "candidate_id": "apply",
            "bbox": {"x": 10, "y": 20, "w": 100, "h": 40},
            "click_point": {"x": 50, "y": 40},
        },
        capture_id="old.png",
        viewport_size={"width": 1280, "height": 720},
        source="path_graph_seed",
    )

    stale = vision_api._candidate_freshness_decision_for_trace(
        seed,
        image_path=image,
        image_size=ImageSize(width=1280, height=720),
        grounding=None,
    )
    refreshed = vision_api._candidate_freshness_decision_for_trace(
        seed,
        image_path=image,
        image_size=ImageSize(width=1280, height=720),
        grounding=LocalGroundingResult(
            goal="apply",
            results=[
                LocalGroundingCandidateResult(
                    candidate_id="seeded_apply",
                    element_id="seeded_apply",
                    status="grounded",
                    crop_path=None,
                    crop_bbox={"x": 10, "y": 20, "w": 100, "h": 40},
                    refined_click_point={"x": 50, "y": 40},
                    coordinate_source="seeded_candidate_v1_validated_by_vista_point_v1",
                    confidence=0.9,
                    matched_text="Apply",
                    matched_text_bbox={"x": 10, "y": 20, "w": 100, "h": 40},
                    reasons=["seeded_candidate_point_validated_by_vista_point"],
                )
            ],
            recommended_candidate_id="seeded_apply",
            summary={},
        ),
    )

    assert stale["allowed"] is False
    assert "candidate_capture_id_stale" in stale["reasons"]
    assert refreshed["allowed"] is True
    assert "candidate_refreshed_by_current_grounding" in refreshed["reasons"]


def test_action_taxonomy_separates_apply_entry_from_final_submit() -> None:
    apply_entry = classify_action_taxonomy("apply_entry", {"goal_template": "Open Quick Apply"})
    final_submit = classify_action_taxonomy("submit_application", {"goal_template": "Submit application"})

    assert apply_entry["kind"] == "open_apply_flow"
    assert apply_entry["final_submit"] is False
    assert final_submit["kind"] == "final_submit"
    assert final_submit["final_submit"] is True


def test_safe_open_apply_flow_allowed_but_final_submit_still_blocked() -> None:
    allowed, reason = vision_api._execution_allowed_for_risk_class(
        label="Apply",
        role="button",
        risk_class="safe_open_apply_flow",
    )
    blocked, blocked_reason = vision_api._execution_allowed_for_risk_class(
        label="Submit application",
        role="button",
        risk_class="safe_open_apply_flow",
    )

    assert (allowed, reason) == (True, "risk_class_safe_open_apply_flow")
    assert blocked is False
    assert blocked_reason == "potential_side_effect_action"


def test_scoped_final_submit_ignores_search_submit_outside_application_flow() -> None:
    items = [
        {
            "collection": "available_actions",
            "id": "action_submit_search",
            "text": "Submit search",
            "role": "button",
            "bbox": {"x": 800, "y": 90, "w": 120, "h": 40},
        }
    ]

    blocker = scoped_final_submit_visible_blocker(items, active_flow_started=False)
    flow = assess_seek_application_flow_state({"screen_inventory": {"available_actions": items}})

    assert blocker["blocked"] is False
    assert flow["final_submit_visible"] is False
    assert flow["final_submit_visible_blocker"]["blocked"] is False


def test_scoped_final_submit_blocks_inside_active_application_container() -> None:
    items = [
        {
            "collection": "available_actions",
            "id": "submit_application",
            "text": "Submit application",
            "role": "button",
            "bbox": {"x": 500, "y": 600, "w": 180, "h": 44},
        }
    ]

    blocker = scoped_final_submit_visible_blocker(
        items,
        active_flow_started=True,
        active_container={"x": 300, "y": 300, "w": 700, "h": 500},
    )

    assert blocker["blocked"] is True
    assert blocker["matched_terms"] == ["submit application"]


def test_scroll_scope_invariant_flags_non_target_pane_change() -> None:
    invariant = build_scroll_scope_invariant(
        target_container_id="generic:detail",
        target_changed=True,
        non_target_changes=[{"container_id": "generic:list", "changed": True}],
    )

    assert invariant["wrong_scope_detected"] is True
    assert invariant["status"] == "wrong_scope_detected"


def test_ocr_canonicalization_is_short_acronym_only() -> None:
    assert ocr_contextual_match("AIA New Zealand", "AlA New Zealand", context="company_name") is True
    assert ocr_contextual_match("All Auckland", "AII Auckland", context="location") is False
