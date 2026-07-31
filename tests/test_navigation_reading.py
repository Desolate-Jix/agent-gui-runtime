from __future__ import annotations

import pytest

from app.agent.navigation_reading import (
    build_navigation_reading_context,
    validate_navigation_reading_decision,
)


def _evidence() -> dict:
    return {
        "contract_version": "agent_evidence_context_v1",
        "interface": {
            "interface_id": "news:list",
            "display_name": "News list",
            "surface_type": "content_collection",
            "responsibility": "Show current articles and open one article.",
        },
        "deferred_reads": [
            {
                "content_id": "article_feed",
                "label": "Article feed",
                "content_behavior": "dynamic_collection",
                "read_policy": "on_demand",
                "agent_description": "Read current article titles when needed.",
                "observation_status": "requires_observation",
            }
        ],
        "available_actions": [
            {
                "action_id": "open_article",
                "action_type": "open_detail",
                "display_name": "Open selected article",
                "agent_description": "Open the selected article to read its details.",
                "operation_goal": "Open the article titled Local technology outlook",
                "source_interface_id": "news:list",
                "source_control_id": "article_card",
                "target_interface_id": "news:detail",
                "risk_level": "low",
                "review_status": "approved",
                "requires_fresh_grounding": True,
                "gate_required": True,
                "automatic_execution_allowed": False,
            }
        ],
        "forbidden_actions": [],
        "verification_rules": [{"rule_id": "detail_heading_visible"}],
        "blockers": [],
        "readiness": {"status": "agent_usable", "missing_fields": []},
        "execution_contract": {
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "operation_required": True,
            "trace_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _observation() -> dict:
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": "news:list",
        "capture_id": "capture-7",
        "screenshot_sha256": "sha256:capture-7",
        "trace_path": "logs/observe/capture-7.json",
    }


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {
            str(key)
            for key in value
        } | {
            nested
            for item in value.values()
            for nested in _all_keys(item)
        }
    if isinstance(value, list):
        return {
            nested
            for item in value
            for nested in _all_keys(item)
        }
    return set()


def test_context_exposes_reviewed_transition_and_on_demand_read_without_geometry() -> None:
    context = build_navigation_reading_context(
        goal="Find and read an article about local technology.",
        interface_evidence=_evidence(),
        observation=_observation(),
        read_progress={
            "strategy": "infinite_collection",
            "status": "reading",
            "scrolls_used": 1,
            "max_scrolls": 4,
            "items_read": 8,
            "max_items": 30,
        },
        task_progress={
            "sequence": 3,
            "visited_interfaces": ["news_list", "news_detail", "news_list"],
            "completed_choice_ids": [
                "transition:open_selected_article",
                "transition:return_to_list",
            ],
            "last_outcome": "passed",
            "bounded_read_content_ids": ["news_list:feed"],
            "completed_read_content_ids": ["news_detail:article"],
        },
    )

    choice_types = {item["decision_type"] for item in context["choices"]}
    assert choice_types == {
        "follow_transition",
        "read_region",
        "scroll_for_more",
        "stop_reading",
        "safe_stop",
    }
    assert context["current_observation"]["capture_id"] == "capture-7"
    assert context["task_progress"] == {
        "sequence": 3,
        "visited_interfaces": ["news_list", "news_detail", "news_list"],
        "completed_choice_ids": [
            "transition:open_selected_article",
            "transition:return_to_list",
        ],
        "last_outcome": "passed",
        "bounded_read_content_ids": ["news_list:feed"],
        "completed_read_content_ids": ["news_detail:article"],
    }
    assert context["execution_contract"]["artifact_is_authorization"] is False
    read_choice = next(
        item for item in context["choices"]
        if item["decision_type"] == "read_region"
    )
    assert read_choice["read_strategy"] == "infinite_collection"
    assert _all_keys(context).isdisjoint(
        {"bbox", "click_point", "coordinates", "point", "viewport_size"}
    )


def test_finite_detail_reached_bottom_does_not_offer_more_scrolling() -> None:
    evidence = _evidence()
    evidence["interface"]["interface_id"] = "news:detail"
    evidence["deferred_reads"][0]["content_id"] = "article_body"
    evidence["deferred_reads"][0]["content_behavior"] = "finite_detail"
    observation = _observation()
    observation["interface_id"] = "news:detail"

    context = build_navigation_reading_context(
        goal="Read the whole article.",
        interface_evidence=evidence,
        observation=observation,
        read_progress={
            "content_id": "article_body",
            "strategy": "finite_detail",
            "status": "reached_bottom",
            "scrolls_used": 3,
            "max_scrolls": 8,
        },
    )

    assert "scroll_for_more" not in {
        item["decision_type"] for item in context["choices"]
    }
    assert "read:article_body" not in {
        item["choice_id"] for item in context["choices"]
    }
    assert context["read_state"]["completion"] == "complete"


def test_transition_requiring_completed_read_is_hidden_until_content_reaches_bottom() -> None:
    evidence = _evidence()
    evidence["interface"]["interface_id"] = "news:detail"
    evidence["available_actions"][0]["requires_completed_read"] = "article_body"
    observation = _observation()
    observation["interface_id"] = "news:detail"

    context = build_navigation_reading_context(
        goal="Read the article, then open its implementation notes.",
        interface_evidence=evidence,
        observation=observation,
        read_progress={
            "content_id": "article_body",
            "strategy": "finite_detail",
            "status": "reading",
            "scrolls_used": 2,
            "max_scrolls": 6,
        },
    )

    assert "follow_transition" not in {
        item["decision_type"] for item in context["choices"]
    }


def test_transition_requiring_completed_read_is_available_after_content_reaches_bottom() -> None:
    evidence = _evidence()
    evidence["interface"]["interface_id"] = "news:detail"
    evidence["available_actions"][0]["requires_completed_read"] = "article_body"
    observation = _observation()
    observation["interface_id"] = "news:detail"

    context = build_navigation_reading_context(
        goal="Read the article, then open its implementation notes.",
        interface_evidence=evidence,
        observation=observation,
        read_progress={
            "content_id": "article_body",
            "strategy": "finite_detail",
            "status": "reached_bottom",
            "scrolls_used": 3,
            "max_scrolls": 6,
        },
    )

    transition = next(
        item
        for item in context["choices"]
        if item["decision_type"] == "follow_transition"
    )
    assert transition["requires_completed_read"] == "article_body"


def test_no_new_content_is_not_treated_as_finite_read_completion() -> None:
    evidence = _evidence()
    evidence["interface"]["interface_id"] = "news:detail"
    observation = _observation()
    observation["interface_id"] = "news:detail"

    context = build_navigation_reading_context(
        goal="Read the whole article.",
        interface_evidence=evidence,
        observation=observation,
        read_progress={
            "strategy": "finite_detail",
            "status": "no_new_content",
            "scrolls_used": 2,
            "max_scrolls": 5,
        },
    )

    assert context["read_state"]["completion"] == "incomplete"
    assert any(
        item["decision_type"] == "scroll_for_more"
        for item in context["choices"]
    )


def test_active_incomplete_read_hides_same_read_choice_and_requires_scroll() -> None:
    evidence = _evidence()
    evidence["interface"]["interface_id"] = "news:detail"
    evidence["deferred_reads"][0]["content_id"] = "article_body"
    observation = _observation()
    observation["interface_id"] = "news:detail"

    context = build_navigation_reading_context(
        goal="Read the whole article.",
        interface_evidence=evidence,
        observation=observation,
        read_progress={
            "content_id": "article_body",
            "strategy": "finite_detail",
            "status": "no_new_content",
            "scrolls_used": 0,
            "max_scrolls": 5,
        },
    )

    choice_ids = {item["choice_id"] for item in context["choices"]}
    assert "read:article_body" not in choice_ids
    assert "scroll:current_read_region" in choice_ids


def test_infinite_collection_budget_exhaustion_stops_more_scrolling() -> None:
    context = build_navigation_reading_context(
        goal="Scan up to 20 headlines.",
        interface_evidence=_evidence(),
        observation=_observation(),
        read_progress={
            "content_id": "article_feed",
            "strategy": "infinite_collection",
            "status": "reading",
            "scrolls_used": 4,
            "max_scrolls": 4,
            "items_read": 18,
            "max_items": 20,
        },
    )

    assert "scroll_for_more" not in {
        item["decision_type"] for item in context["choices"]
    }
    assert context["read_state"]["completion"] == "budget_exhausted"
    assert {
        item["decision_type"] for item in context["choices"]
    } == {"stop_reading", "safe_stop"}


def test_wrong_scope_only_allows_safe_stop() -> None:
    context = build_navigation_reading_context(
        goal="Read the article.",
        interface_evidence=_evidence(),
        observation=_observation(),
        read_progress={
            "strategy": "finite_detail",
            "status": "wrong_scope_detected",
            "scrolls_used": 1,
            "max_scrolls": 4,
        },
    )

    assert [item["decision_type"] for item in context["choices"]] == ["safe_stop"]


def test_transition_decision_is_bound_to_current_capture_but_has_no_coordinates() -> None:
    context = build_navigation_reading_context(
        goal="Open the matching article.",
        interface_evidence=_evidence(),
        observation=_observation(),
    )
    transition = next(
        item for item in context["choices"]
        if item["decision_type"] == "follow_transition"
    )

    plan = validate_navigation_reading_decision(
        context,
        {
            "choice_id": transition["choice_id"],
            "reason": "The article title matches the user's topic.",
        },
    )

    assert plan["semantic_action"] == "open_detail"
    assert plan["source_control_id"] == "article_card"
    assert plan["operation_goal"] == "Open the article titled Local technology outlook"
    assert plan["expected_target_interface_id"] == "news:detail"
    assert plan["freshness"]["capture_id"] == "capture-7"
    assert plan["requires_operation_resolution"] is True
    assert plan["requires_gate"] is True
    assert "bbox" not in repr(plan).casefold()
    assert "click_point" not in repr(plan).casefold()


def test_context_rejects_unreviewed_asset_or_mismatched_observation() -> None:
    unreviewed = _evidence()
    unreviewed["readiness"] = {
        "status": "needs_human_review",
        "missing_fields": ["action_linkage"],
    }
    with pytest.raises(ValueError, match="agent_usable"):
        build_navigation_reading_context(
            goal="Open an article.",
            interface_evidence=unreviewed,
            observation=_observation(),
        )

    observation = _observation()
    observation["interface_id"] = "different:interface"
    with pytest.raises(ValueError, match="identity mismatch"):
        build_navigation_reading_context(
            goal="Open an article.",
            interface_evidence=_evidence(),
            observation=observation,
        )


def test_decision_rejects_unknown_choice_and_final_action() -> None:
    context = build_navigation_reading_context(
        goal="Open an article.",
        interface_evidence=_evidence(),
        observation=_observation(),
    )
    with pytest.raises(ValueError, match="not available"):
        validate_navigation_reading_decision(
            context,
            {"choice_id": "final_submit", "reason": "not allowed"},
        )
