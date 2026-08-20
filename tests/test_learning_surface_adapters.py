from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.learn.recognition.two_stage import build_two_stage_screen_understanding
from app.learn.recognition.surface_adapters import (
    build_surface_adapter_stage2_policy,
    build_surface_adapter_application,
    select_learning_surface_adapter,
    surface_adapter_excludes_inventory_item,
)


def _bundle(
    *,
    app_name: str = "",
    category: str = "generic",
    confidence: float = 0.95,
    structure_signals: dict[str, bool] | None = None,
) -> dict:
    return {
        "app_name": app_name,
        "screen_reading": {
            "interface_classification": {
                "category": category,
                "confidence": confidence,
                "structure_signals": structure_signals or {},
            }
        },
    }


def _chat_inventory() -> list[dict]:
    return [
        {"item_id": "conversation_1", "role": "conversation_row"},
        {"item_id": "conversation_2", "role": "conversation_row"},
        {"item_id": "thread", "role": "message_thread"},
        {"item_id": "composer", "role": "composer"},
    ]


def _mail_inventory() -> list[dict]:
    return [
        {"item_id": "mail_1", "role": "mail_row"},
        {"item_id": "mail_2", "role": "email_row"},
        {"item_id": "mailbox_nav", "role": "mailbox_navigation"},
    ]


def _media_inventory() -> list[dict]:
    return [
        {"item_id": "card_1", "role": "media_card"},
        {"item_id": "card_2", "role": "media_card"},
        {"item_id": "controls", "role": "player_controls"},
    ]


def _media_feed_inventory() -> list[dict]:
    return [
        {"item_id": "video_1", "role": "media_card"},
        {"item_id": "video_2", "role": "recommendation_item"},
        {"item_id": "feed_1", "role": "feed_item"},
        {"item_id": "feed_2", "role": "post_card"},
    ]


def _news_feed_inventory() -> list[dict]:
    return [
        {"item_id": "headline_1", "role": "news_article_card"},
        {"item_id": "headline_2", "role": "news_article_card"},
        {"item_id": "news_section", "role": "news_section"},
    ]


def _video_feed_inventory() -> list[dict]:
    return [
        {"item_id": "video_1", "role": "video_card"},
        {"item_id": "video_2", "role": "video_card"},
        {"item_id": "thumbnail_1", "role": "video_thumbnail"},
        {"item_id": "thumbnail_2", "role": "video_thumbnail"},
    ]


def _search_workspace_inventory() -> list[dict]:
    return [
        {"item_id": "search_query", "role": "search_input"},
        {"item_id": "result_1", "role": "search_result"},
        {"item_id": "result_2", "role": "search_result"},
        {"item_id": "result_3", "role": "search_result"},
    ]


def _job_results_inventory() -> list[dict]:
    return [
        {"item_id": "job_search", "role": "job_search"},
        {"item_id": "job_filters", "role": "job_filter_group"},
        {"item_id": "job_1", "role": "job_result_card"},
        {"item_id": "job_2", "role": "job_listing"},
    ]


def _application_form_inventory() -> list[dict]:
    return [
        {"item_id": "application_form", "role": "job_application_form"},
        {"item_id": "first_name", "role": "application_field"},
        {"item_id": "email", "role": "application_field"},
        {"item_id": "resume", "role": "resume_upload"},
        {"item_id": "continue", "role": "continue_next_step"},
    ]


def test_browser_app_name_alone_does_not_activate_browser_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(app_name="Microsoft Edge", category="generic"),
        screen_inventory=[],
    )

    assert decision["adapter_id"] == "generic"
    assert decision["status"] == "insufficient_surface_evidence"
    assert decision["app_name_used_as_final_decision"] is False


def test_chat_or_media_app_name_alone_does_not_activate_content_adapter() -> None:
    for app_name in ("QQ", "WeChat", "WhatsApp", "Apple Music", "Spotify"):
        decision = select_learning_surface_adapter(
            bundle=_bundle(app_name=app_name, category="generic"),
            screen_inventory=[],
        )

        assert decision["adapter_id"] == "generic"
        assert decision["content_adapter_id"] == "generic"
        assert decision["status"] == "insufficient_surface_evidence"
        assert decision["app_name_used_as_final_decision"] is False


def test_browser_adapter_requires_visible_browser_chrome_evidence() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(app_name="Microsoft Edge", category="generic"),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "label": "https://example.com",
                "surface_zone": "browser_chrome",
                "sources": ["uia"],
            }
        ],
    )

    assert decision["adapter_id"] == "browser"
    assert decision["status"] == "selected_from_visible_evidence"
    assert "browser_chrome" in decision["excluded_zones"]
    assert "browser_chrome_must_not_become_page_action" in decision["validation_rules"]


def test_semantic_browser_chrome_region_alone_does_not_activate_browser_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Native Player",
            category="media_catalog",
            structure_signals={"media_cards": True, "playback_controls": True},
        ),
        screen_inventory=[
            {
                "item_id": "model_browser_chrome",
                "role": "browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 80},
                "sources": ["vision"],
            },
            *_media_inventory(),
        ],
    )

    assert decision["adapter_id"] == "media_player"
    assert decision["excluded_item_ids"] == []


def test_semantic_browser_chrome_region_requires_contained_url_corroboration() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(app_name="Unknown Window", category="generic"),
        screen_inventory=[
            {
                "item_id": "model_browser_chrome",
                "role": "browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 80},
                "sources": ["vision"],
            },
            {
                "item_id": "url_text",
                "role": "text",
                "label": "https://example.com/docs",
                "bbox": {"x": 120, "y": 24, "w": 420, "h": 28},
                "sources": ["ocr"],
            },
        ],
    )

    assert decision["adapter_id"] == "browser"
    assert decision["excluded_item_ids"] == ["model_browser_chrome", "url_text"]


def test_validated_file_browser_category_rejects_false_browser_chrome_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="explorer.exe",
            category="file_browser",
            structure_signals={"file_or_folder_rows": True},
        ),
        screen_inventory=[
            {
                "item_id": "native_address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "This PC > Local Disk",
                "sources": ["uia"],
            }
        ],
    )

    assert decision["adapter_id"] == "generic"
    assert decision["status"] == "browser_evidence_conflicts_with_validated_native_surface"
    assert decision["rejected_adapter_id"] == "browser"


def test_chat_adapter_abstains_when_only_people_rows_are_visible() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={"people_or_conversation_rows": True},
        ),
        screen_inventory=[],
    )

    assert decision["adapter_id"] == "generic"
    assert decision["content_adapter_id"] == "generic"
    assert decision["status"] == "content_adapter_evidence_insufficient"


def test_chat_adapter_requires_thread_and_composer_topology() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=_chat_inventory(),
    )

    assert decision["adapter_id"] == "chat"
    assert "conversation_list_and_thread_are_sibling_surfaces" in decision["layout_priors"]


def test_chat_adapter_accepts_framework_generated_structure_ids() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=[
            {
                "item_id": "two_stage_review_structure_region_main_content__conversation_list_action_uia_1",
                "role": "group",
            },
            {
                "item_id": "two_stage_review_structure_region_main_content__message_thread_page_text_1",
                "role": "text",
            },
            {
                "item_id": "two_stage_review_structure_region_main_content__bottom_composer_visual_control_1",
                "role": "control",
            },
        ],
    )

    assert decision["content_adapter_id"] == "chat"
    assert decision["content_adapter_status"] == "selected_from_correlated_model_and_inventory"
    assert decision["content_topology_evidence"]["chat"]["eligible"] is True


def test_media_adapter_abstains_when_only_media_cards_are_visible() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={"media_cards": True},
        ),
        screen_inventory=[],
    )

    assert decision["adapter_id"] == "generic"
    assert decision["content_adapter_id"] == "generic"
    assert decision["status"] == "content_adapter_evidence_insufficient"


def test_media_adapter_requires_player_topology() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={
                "media_cards": True,
                "playback_controls": True,
            },
        ),
        screen_inventory=_media_inventory(),
    )

    assert decision["adapter_id"] == "media_player"
    assert "repeated_media_cards_are_peer_items" in decision["layout_priors"]


def test_mail_adapter_requires_mail_rows_and_mailbox_topology() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="mail_workspace",
            structure_signals={
                "mail_or_email_rows": True,
                "mailbox_navigation": True,
            },
        ),
        screen_inventory=_mail_inventory(),
    )

    assert decision["adapter_id"] == "mail_workspace"
    assert decision["content_adapter_id"] == "mail_workspace"
    assert decision["adapter_chain"] == ["mail_workspace"]
    assert decision["stage2_processing_policy"]["primary_content_strategy"] == "mail_rows"
    assert decision["stage2_processing_policy"]["allow_chat_semantics"] is False


def test_mail_adapter_can_validate_legacy_conversation_row_parser_output() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="mail_workspace",
            structure_signals={
                "mail_or_email_rows": True,
                "mailbox_navigation": True,
            },
        ),
        screen_inventory=[
            {"item_id": "left_navigation", "role": "left_sidebar", "label": "Mail"},
            {"item_id": "compose", "role": "nav_item", "label": "Compose"},
            {"item_id": "inbox", "role": "nav_item", "label": "Inbox"},
            {"item_id": "row_1", "role": "conversation_row", "label": "First subject"},
            {"item_id": "row_2", "role": "table_row", "label": "Second subject"},
        ],
    )

    assert decision["content_adapter_id"] == "mail_workspace"
    assert decision["content_adapter_status"] == "selected_from_correlated_model_and_inventory"
    assert decision["content_topology_evidence"]["mail_workspace"]["legacy_row_count"] == 2
    assert decision["content_topology_evidence"]["mail_workspace"]["mail_semantic_anchor_count"] == 3


def test_chat_model_claim_does_not_override_mail_inventory_topology() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=_mail_inventory(),
    )

    assert decision["content_adapter_id"] == "generic"
    assert decision["status"] == "content_adapter_evidence_conflict"
    assert decision["content_topology_evidence"]["mail_workspace"]["eligible"] is True


def test_media_feed_adapter_resolves_media_and_feed_topology_without_player_assumptions() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={
                "media_cards": True,
                "feed_items": True,
            },
        ),
        screen_inventory=_media_feed_inventory(),
    )

    assert decision["adapter_id"] == "media_feed"
    assert decision["content_adapter_id"] == "media_feed"
    assert decision["content_adapter_status"] == "selected_from_correlated_model_and_inventory"
    assert decision["stage2_processing_policy"]["primary_content_strategy"] == "visual_feed_card_first"
    assert decision["stage2_processing_policy"]["allow_media_card_synthesis"] is True
    assert "repeated_media_feed_cards_are_peer_items" in decision["layout_priors"]
    assert decision["content_topology_evidence"]["feed_workspace"]["eligible"] is True


def test_feed_workspace_category_requires_feed_topology_before_media_feed_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="feed_workspace",
            structure_signals={"feed_items": True},
        ),
        screen_inventory=_media_feed_inventory(),
    )

    assert decision["content_adapter_id"] == "media_feed"
    assert decision["status"] == "selected_from_visible_evidence"


def test_browser_host_keeps_validated_chat_content_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Microsoft Edge",
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "https://chat.example.test",
            },
            *_chat_inventory(),
        ],
    )

    assert decision["adapter_id"] == "browser"
    assert decision["host_adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "chat"
    assert decision["adapter_chain"] == ["browser", "chat"]
    assert decision["host_adapter_status"] == "selected_from_visible_evidence"
    assert decision["content_adapter_status"] == "selected_from_correlated_model_and_inventory"
    assert decision["stage2_processing_policy"]["allow_chat_semantics"] is True
    assert decision["stage2_processing_policy"]["allow_media_card_synthesis"] is False


def test_browser_host_keeps_validated_media_content_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Microsoft Edge",
            category="media_catalog",
            structure_signals={"media_cards": True, "playback_controls": True},
        ),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "https://music.example.test",
            },
            *_media_inventory(),
        ],
    )

    assert decision["adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "media_player"
    assert decision["adapter_chain"] == ["browser", "media_player"]
    assert decision["stage2_processing_policy"]["allow_media_card_synthesis"] is True
    assert decision["stage2_processing_policy"]["allow_chat_semantics"] is False


def test_browser_host_keeps_news_feed_content_adapter_without_site_name_rules() -> None:
    for app_name, url in (
        ("Microsoft Edge", "https://news.example.test"),
        ("Google Chrome", "https://daily.example.test"),
    ):
        decision = select_learning_surface_adapter(
            bundle=_bundle(
                app_name=app_name,
                category="feed_workspace",
                structure_signals={"feed_items": True, "news_items": True},
            ),
            screen_inventory=[
                {
                    "item_id": "address_bar",
                    "role": "address_bar",
                    "surface_zone": "browser_chrome",
                    "label": url,
                },
                *_news_feed_inventory(),
            ],
        )

        assert decision["host_adapter_id"] == "browser"
        assert decision["content_adapter_id"] == "news_feed"
        assert decision["adapter_chain"] == ["browser", "news_feed"]
        assert decision["stage2_processing_policy"]["primary_content_strategy"] == "news_article_rows"
        assert decision["artifact_is_authorization"] is False


def test_news_feed_accepts_repeated_peer_cards_without_explicit_section_container() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Microsoft Edge",
            category="feed_workspace",
            structure_signals={"feed_items": True, "news_items": True},
        ),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "https://portal.example.test",
            },
            {"item_id": "headline_1", "role": "news_card", "label": "Headline one"},
            {"item_id": "headline_2", "role": "news_card", "label": "Headline two"},
            {"item_id": "peer_1", "role": "tile_card", "label": "Peer card one"},
            {"item_id": "peer_2", "role": "tile_card", "label": "Peer card two"},
            {"item_id": "peer_3", "role": "tile_card", "label": "Peer card three"},
        ],
    )

    assert decision["host_adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "news_feed"
    assert decision["content_topology_evidence"]["news_feed"] == {
        "eligible": True,
        "news_article_count": 2,
        "news_section_count": 0,
        "peer_tile_card_count": 3,
    }


def test_browser_host_accepts_visible_new_tab_semantics_without_url_text() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Untitled",
            category="feed_workspace",
            structure_signals={"feed_items": True, "news_items": True},
        ),
        screen_inventory=[
            {
                "item_id": "tab_1",
                "role": "nav_item",
                "label": "新建标签页",
            },
            {
                "item_id": "toolbar_1",
                "role": "topbar_control_strip",
                "label": "top/header control strip",
            },
            *_news_feed_inventory(),
        ],
    )

    assert decision["host_adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "news_feed"
    assert decision["adapter_chain"] == ["browser", "news_feed"]
    assert any(
        item["value"] == "browser_tab_semantic_anchor"
        for item in decision["selection_evidence"]
    )


def test_browser_host_keeps_video_feed_content_adapter_without_site_name_rules() -> None:
    for app_name, url in (
        ("Microsoft Edge", "https://video.example.test"),
        ("Google Chrome", "https://clips.example.test"),
    ):
        decision = select_learning_surface_adapter(
            bundle=_bundle(
                app_name=app_name,
                category="media_catalog",
                structure_signals={
                    "media_cards": True,
                    "feed_items": True,
                    "video_items": True,
                },
            ),
            screen_inventory=[
                {
                    "item_id": "address_bar",
                    "role": "address_bar",
                    "surface_zone": "browser_chrome",
                    "label": url,
                },
                *_video_feed_inventory(),
            ],
        )

        assert decision["host_adapter_id"] == "browser"
        assert decision["content_adapter_id"] == "video_feed"
        assert decision["adapter_chain"] == ["browser", "video_feed"]
        assert decision["stage2_processing_policy"]["primary_content_strategy"] == "video_card_first"
        assert decision["artifact_is_authorization"] is False


def test_browser_host_keeps_search_workspace_content_adapter_without_site_name_rules() -> None:
    for app_name, url in (
        ("Microsoft Edge", "https://search.example.test"),
        ("Google Chrome", "https://find.example.test"),
    ):
        decision = select_learning_surface_adapter(
            bundle=_bundle(
                app_name=app_name,
                category="search_workspace",
                structure_signals={
                    "search_controls": True,
                    "search_results": True,
                },
            ),
            screen_inventory=[
                {
                    "item_id": "address_bar",
                    "role": "address_bar",
                    "surface_zone": "browser_chrome",
                    "label": url,
                },
                *_search_workspace_inventory(),
            ],
        )

        assert decision["host_adapter_id"] == "browser"
        assert decision["content_adapter_id"] == "search_workspace"
        assert decision["adapter_chain"] == ["browser", "search_workspace"]
        assert decision["stage2_processing_policy"]["primary_content_strategy"] == "search_results"
        assert decision["artifact_is_authorization"] is False


def test_browser_video_search_keeps_video_content_and_search_interaction_mode() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Microsoft Edge",
            category="search_workspace",
            structure_signals={
                "media_cards": True,
                "video_items": True,
                "search_controls": True,
                "search_results": True,
            },
        ),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "https://media.example.test/search",
            },
            *_video_feed_inventory(),
            *_search_workspace_inventory(),
        ],
    )

    assert decision["host_adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "video_feed"
    assert decision["interaction_mode_adapter_id"] == "search_workspace"
    assert decision["adapter_chain"] == ["browser", "video_feed", "search_workspace"]
    assert decision["stage2_processing_policy"]["primary_content_strategy"] == "video_card_first"
    assert decision["artifact_is_authorization"] is False


def test_browser_host_keeps_validated_employment_results_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            app_name="Microsoft Edge",
            category="employment_workflow",
            structure_signals={
                "employment_workflow": True,
                "job_result_cards": True,
            },
        ),
        screen_inventory=[
            {
                "item_id": "address_bar",
                "role": "address_bar",
                "surface_zone": "browser_chrome",
                "label": "https://jobs.example.test",
            },
            *_job_results_inventory(),
        ],
    )

    assert decision["adapter_id"] == "browser"
    assert decision["content_adapter_id"] == "employment_workflow"
    assert decision["adapter_chain"] == ["browser", "employment_workflow"]
    assert decision["employment_page_state"] == "job_search_results"
    assert decision["employment_page_state_candidates"] == ["job_search_results"]
    assert decision["stage2_processing_policy"]["primary_content_strategy"] == "employment_workflow"


def test_employment_application_form_uses_same_content_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="employment_workflow",
            structure_signals={
                "employment_workflow": True,
                "application_fields": True,
            },
        ),
        screen_inventory=_application_form_inventory(),
    )

    assert decision["adapter_id"] == "employment_workflow"
    assert decision["content_adapter_id"] == "employment_workflow"
    assert decision["employment_page_state"] == "application_form"
    assert decision["stage2_processing_policy"]["employment_page_state"] == "application_form"


def test_employment_adapter_accepts_framework_generated_structure_ids() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="employment_workflow",
            structure_signals={
                "employment_workflow": True,
                "job_result_cards": True,
            },
        ),
        screen_inventory=[
            {
                "item_id": "two_stage_review_structure_region_main__job_search_visual_control_1",
                "role": "control",
            },
            {
                "item_id": "two_stage_review_structure_region_main__job_result_card_visual_card_1",
                "role": "card",
            },
            {
                "item_id": "two_stage_review_structure_region_main__job_listing_visual_card_2",
                "role": "card",
            },
        ],
    )

    assert decision["content_adapter_id"] == "employment_workflow"
    assert decision["employment_page_state"] == "job_search_results"


def test_employment_adapter_reports_mixed_detail_and_application_drawer() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="employment_workflow",
            structure_signals={
                "employment_workflow": True,
                "job_detail_content": True,
                "application_fields": True,
            },
        ),
        screen_inventory=[
            {"item_id": "detail", "role": "job_detail"},
            {"item_id": "description", "role": "job_description"},
            {"item_id": "apply", "role": "apply_entry"},
            *_application_form_inventory(),
        ],
    )

    assert decision["content_adapter_id"] == "employment_workflow"
    assert decision["employment_page_state"] == "mixed"
    assert decision["employment_page_state_candidates"] == [
        "job_detail",
        "application_form",
    ]


def test_ordinary_form_does_not_activate_employment_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="form_workflow",
            structure_signals={"form_fields": True},
        ),
        screen_inventory=[
            {"item_id": "survey", "role": "form"},
            {"item_id": "name", "role": "form_field"},
            {"item_id": "rating", "role": "form_field"},
            {"item_id": "submit", "role": "submit"},
        ],
    )

    assert decision["content_adapter_id"] == "generic"
    assert decision["employment_page_state"] == "unknown"


def test_ecommerce_cards_do_not_activate_employment_adapter() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="generic",
            structure_signals={},
        ),
        screen_inventory=[
            {"item_id": "product_1", "role": "product_card"},
            {"item_id": "product_2", "role": "product_card"},
            {"item_id": "filters", "role": "filter_group"},
        ],
    )

    assert decision["content_adapter_id"] == "generic"
    assert decision["employment_page_state"] == "unknown"


def test_employment_stage2_policy_remains_read_only_and_submit_forbidden() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="employment_workflow",
            structure_signals={
                "employment_workflow": True,
                "application_review": True,
            },
        ),
        screen_inventory=[
            {"item_id": "review", "role": "application_review"},
            {"item_id": "summary", "role": "application_summary"},
            {"item_id": "submit", "role": "final_submit"},
        ],
    )

    policy = build_surface_adapter_stage2_policy(decision=decision)

    assert decision["employment_page_state"] == "application_review"
    assert "final_submit_controls_remain_forbidden_actions" in decision["validation_rules"]
    assert policy["policy_source"] == "surface_adapter"
    assert policy["content_adapter_id"] == "employment_workflow"
    assert policy["employment_page_state"] == "application_review"
    assert policy["final_submit_action_allowed"] is False
    assert policy["final_geometry_allowed"] is False
    assert policy["artifact_is_authorization"] is False
    assert policy["execute_binding_enabled"] is False


def test_surface_adapter_stage2_policy_is_authoritative_for_chat_and_media() -> None:
    chat_decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=_chat_inventory(),
    )

    policy = build_surface_adapter_stage2_policy(
        decision=chat_decision,
        legacy_class_rule_profile={
            "primary_content_strategy": "visual_card_first",
            "allow_media_card_synthesis": True,
            "allow_chat_semantics": False,
        },
    )

    assert policy["policy_source"] == "surface_adapter"
    assert policy["content_adapter_id"] == "chat"
    assert policy["primary_content_strategy"] == "conversation_rows"
    assert policy["allow_chat_semantics"] is True
    assert policy["allow_media_card_synthesis"] is False
    assert policy["final_geometry_allowed"] is False
    assert policy["execute_binding_enabled"] is False


def test_repeated_peer_layout_policy_is_class_prior_but_requires_current_visual_evidence() -> None:
    media_decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={
                "media_cards": True,
                "playback_controls": True,
            },
        ),
        screen_inventory=_media_inventory(),
    )
    policy = build_surface_adapter_stage2_policy(decision=media_decision)

    repeated_layout = policy["repeated_peer_layout_review"]
    assert repeated_layout["class_prior"] == "expected"
    assert repeated_layout["peer_item_family"] == "media_card"
    assert repeated_layout["activation"] == "current_visual_repetition_required"
    assert repeated_layout["neighbor_inference"] == "one_hop_review_candidates_only"
    assert repeated_layout["can_create_without_visual_support"] is False
    assert repeated_layout["artifact_is_authorization"] is False
    assert repeated_layout["execute_binding_enabled"] is False


def test_chat_policy_does_not_claim_card_layout_class_prior() -> None:
    chat_decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=_chat_inventory(),
    )
    policy = build_surface_adapter_stage2_policy(decision=chat_decision)

    repeated_layout = policy["repeated_peer_layout_review"]
    assert repeated_layout["class_prior"] == "not_declared"
    assert repeated_layout["activation"] == "current_visual_repetition_required"
    assert repeated_layout["can_create_without_visual_support"] is False


def test_legacy_class_strategy_can_declare_repeated_peer_prior_without_geometry_authority() -> None:
    policy = build_surface_adapter_stage2_policy(
        decision={"content_adapter_id": "generic"},
        legacy_class_rule_profile={
            "primary_content_strategy": "independent_content_modules",
            "allow_media_card_synthesis": False,
        },
    )

    repeated_layout = policy["repeated_peer_layout_review"]
    assert repeated_layout["class_prior"] == "expected"
    assert repeated_layout["peer_item_family"] == "independent_content_module"
    assert repeated_layout["activation"] == "current_visual_repetition_required"
    assert repeated_layout["can_create_without_visual_support"] is False
    assert policy["final_geometry_allowed"] is False


def test_only_matching_active_rules_become_non_geometric_adapter_advisories() -> None:
    active_rules = [
        {
            "rule_id": "chat_rule",
            "status": "active",
            "production_eligible": True,
            "surface": {"adapter_id": "chat"},
            "transition_history": [
                {
                    "to_status": "human_approved",
                    "evidence": {"scope": "conversation_visible_structure_only"},
                }
            ],
            "correction_entry": {
                "surface": {
                    "adapter_id": "chat",
                    "selection_evidence": [
                        {"source": "model_interface_classification", "value": "conversation_workspace"}
                    ],
                },
                "corrections": [
                    {"edit_type": "update_bbox", "before": {"x": 1}, "after": {"x": 2}}
                ],
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
        },
        {
            "rule_id": "media_rule",
            "status": "active",
            "production_eligible": True,
            "surface": {"adapter_id": "media_player"},
            "correction_entry": {
                "surface": {"adapter_id": "media_player"},
                "corrections": [{"edit_type": "update_role"}],
            },
        },
    ]

    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=_chat_inventory(),
        active_surface_rules=active_rules,
    )

    advisory = decision["active_surface_rule_advisory"]
    assert advisory["policy"] == "active_only"
    assert advisory["matched_rule_ids"] == ["chat_rule"]
    assert advisory["ignored_rule_ids"] == ["media_rule"]
    assert advisory["matched_rules"][0]["edit_types"] == ["update_bbox"]
    assert "before" not in advisory["matched_rules"][0]
    assert "after" not in advisory["matched_rules"][0]
    assert advisory["final_geometry_changed"] is False
    assert advisory["execute_binding_enabled"] is False


def test_conflicting_or_unvalidated_model_category_falls_back_to_generic() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={"people_or_conversation_rows": False},
        ),
        screen_inventory=[],
    )

    assert decision["adapter_id"] == "generic"
    assert decision["status"] == "category_signal_conflict"


def test_surface_adapter_contract_is_read_only_and_contains_no_geometry() -> None:
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={"media_cards": True, "playback_controls": True},
        ),
        screen_inventory=_media_inventory(),
    )

    assert decision["contract_version"] == "learning_surface_adapter_decision_v1"
    assert decision["display_only"] is True
    assert decision["artifact_is_authorization"] is False
    assert decision["execute_binding_enabled"] is False
    assert decision["final_geometry_allowed"] is False
    assert "bbox" not in decision
    assert "click_point" not in decision


def test_two_stage_output_exposes_surface_adapter_decision(tmp_path: Path) -> None:
    image_path = tmp_path / "browser.png"
    Image.new("RGB", (800, 600), "white").save(image_path)
    address_bar = {
        "item_id": "address_bar",
        "role": "address_bar",
        "surface_zone": "browser_chrome",
        "label": "https://example.com",
        "bbox": {"x": 80, "y": 20, "w": 600, "h": 36},
        "sources": ["uia"],
    }
    stage1_override = {
        "contract_version": "learn_stage1_structure_regions_v1",
        "source": "test_explicit_stage1_override",
        "structure_regions": [
            {
                "region_id": "structure_region_browser_chrome",
                "zone_id": "browser_chrome",
                "role": "browser_chrome",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 72},
                "item_ids": ["address_bar"],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        ],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }

    result = build_two_stage_screen_understanding(
        bundle={
            **_bundle(app_name="Microsoft Edge", category="generic"),
            "image_path": str(image_path),
            "screen_size": {"width": 800, "height": 600},
        },
        screen_inventory=[address_bar],
        layout_graph={
            "zones": {"browser_chrome": {"item_ids": ["address_bar"]}},
            "nodes": {"address_bar": address_bar},
        },
        stage1_structure_override=stage1_override,
    )

    assert result["surface_adapter_decision"]["adapter_id"] == "browser"
    assert result["surface_adapter_decision"]["final_geometry_allowed"] is False


def test_two_stage_uses_surface_adapter_policy_for_chat_content(tmp_path: Path) -> None:
    image_path = tmp_path / "chat.png"
    Image.new("RGB", (800, 600), "white").save(image_path)
    chat_inventory = _chat_inventory()
    conversation_row = {
        **chat_inventory[0],
        "label": "Alice - hello",
        "bbox": {"x": 20, "y": 100, "w": 240, "h": 64},
        "sources": ["uia"],
    }
    chat_inventory[0] = conversation_row
    stage1_override = {
        "contract_version": "learn_stage1_structure_regions_v1",
        "source": "test_explicit_stage1_override",
        "structure_regions": [
            {
                "region_id": "structure_region_main_content",
                "zone_id": "main_content",
                "role": "main_content",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
                "item_ids": [item["item_id"] for item in chat_inventory],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        ],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }

    result = build_two_stage_screen_understanding(
        bundle={
            **_bundle(
                category="conversation_workspace",
                structure_signals={
                    "people_or_conversation_rows": True,
                    "message_thread": True,
                    "message_composer": True,
                },
            ),
            "image_path": str(image_path),
            "screen_size": {"width": 800, "height": 600},
        },
        screen_inventory=chat_inventory,
        layout_graph={"zones": {}, "nodes": {item["item_id"]: item for item in chat_inventory}},
        stage1_structure_override=stage1_override,
    )

    assert result["surface_adapter_stage2_policy"]["policy_source"] == "surface_adapter"
    assert result["surface_adapter_stage2_policy"]["content_adapter_id"] == "chat"
    assert result["surface_adapter_stage2_policy"]["allow_chat_semantics"] is True
    assert result["surface_adapter_stage2_policy"]["allow_media_card_synthesis"] is False
    stage2_region = result["stage2_numbering"]["regions"][0]
    assert stage2_region["surface_adapter_processing_policy"]["content_adapter_id"] == "chat"
    assert stage2_region["surface_adapter_processing_policy"]["policy_source"] == "surface_adapter"


def test_two_stage_uses_surface_adapter_policy_for_media_content(tmp_path: Path) -> None:
    image_path = tmp_path / "media.png"
    Image.new("RGB", (800, 600), "white").save(image_path)
    media_inventory = _media_inventory()
    media_card = {
        **media_inventory[0],
        "label": "Album one",
        "bbox": {"x": 80, "y": 120, "w": 180, "h": 220},
        "sources": ["vision"],
    }
    media_inventory[0] = media_card
    stage1_override = {
        "contract_version": "learn_stage1_structure_regions_v1",
        "source": "test_explicit_stage1_override",
        "structure_regions": [
            {
                "region_id": "structure_region_main_content",
                "zone_id": "main_content",
                "role": "main_content",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
                "item_ids": [item["item_id"] for item in media_inventory],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        ],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }

    result = build_two_stage_screen_understanding(
        bundle={
            **_bundle(
                app_name="Unknown media surface",
                category="media_catalog",
                structure_signals={"media_cards": True, "playback_controls": True},
            ),
            "image_path": str(image_path),
            "screen_size": {"width": 800, "height": 600},
        },
        screen_inventory=media_inventory,
        layout_graph={"zones": {}, "nodes": {item["item_id"]: item for item in media_inventory}},
        stage1_structure_override=stage1_override,
    )

    assert result["surface_adapter_stage2_policy"]["policy_source"] == "surface_adapter"
    assert result["surface_adapter_stage2_policy"]["content_adapter_id"] == "media_player"
    assert result["surface_adapter_stage2_policy"]["allow_media_card_synthesis"] is True
    assert result["surface_adapter_stage2_policy"]["allow_chat_semantics"] is False
    stage2_region = result["stage2_numbering"]["regions"][0]
    assert stage2_region["surface_adapter_processing_policy"]["content_adapter_id"] == "media_player"
    assert stage2_region["surface_adapter_processing_policy"]["policy_source"] == "surface_adapter"


def test_browser_adapter_application_excludes_only_explicit_chrome_items() -> None:
    address_bar = {
        "item_id": "address_bar",
        "role": "address_bar",
        "surface_zone": "browser_chrome",
        "bbox": {"x": 80, "y": 20, "w": 600, "h": 36},
    }
    page_search = {
        "item_id": "page_search",
        "role": "button",
        "label": "Search",
        "bbox": {"x": 700, "y": 24, "w": 80, "h": 32},
    }
    decision = select_learning_surface_adapter(
        bundle=_bundle(app_name="Microsoft Edge", category="generic"),
        screen_inventory=[address_bar, page_search],
    )

    application = build_surface_adapter_application(
        decision=decision,
        localized_regions=[
            {
                "region_id": "deterministic_root_1",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 72},
                "item_ids": ["address_bar", "page_search"],
            }
        ],
        items_by_id={"address_bar": address_bar, "page_search": page_search},
    )

    assert application["excluded_item_ids"] == ["address_bar"]
    assert application["fixed_height_boundary_used"] is False
    assert application["final_geometry_changed"] is False
    assert surface_adapter_excludes_inventory_item(decision, address_bar) is True
    assert surface_adapter_excludes_inventory_item(decision, page_search) is False


def test_chat_adapter_application_reports_structure_evidence_without_geometry_change() -> None:
    items = {
        "conversation_1": {"item_id": "conversation_1", "role": "conversation_row"},
        "conversation_2": {"item_id": "conversation_2", "role": "conversation_row"},
        "thread": {"item_id": "thread", "role": "message_thread"},
        "composer": {"item_id": "composer", "role": "composer"},
    }
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="conversation_workspace",
            structure_signals={
                "people_or_conversation_rows": True,
                "message_thread": True,
                "message_composer": True,
            },
        ),
        screen_inventory=list(items.values()),
    )

    application = build_surface_adapter_application(
        decision=decision,
        localized_regions=[],
        items_by_id=items,
    )

    validation = application["content_surface_validation"]
    assert application["status"] == "applied_from_explicit_evidence"
    assert validation["content_adapter_id"] == "chat"
    assert validation["conversation_row_evidence_count"] == 2
    assert validation["message_thread_evidence_count"] == 1
    assert validation["composer_evidence_count"] == 1
    assert validation["validation_status"] == "visible_structure_supported"
    assert application["final_geometry_changed"] is False


def test_mail_adapter_application_reports_structure_evidence_without_geometry_change() -> None:
    items = {item["item_id"]: item for item in _mail_inventory()}
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="mail_workspace",
            structure_signals={
                "mail_or_email_rows": True,
                "mailbox_navigation": True,
            },
        ),
        screen_inventory=list(items.values()),
    )

    application = build_surface_adapter_application(
        decision=decision,
        localized_regions=[],
        items_by_id=items,
    )

    validation = application["content_surface_validation"]
    assert application["status"] == "applied_from_explicit_evidence"
    assert validation["content_adapter_id"] == "mail_workspace"
    assert validation["mail_row_evidence_count"] == 2
    assert validation["mailbox_navigation_evidence_count"] == 1
    assert validation["mail_toolbar_evidence_count"] == 0
    assert validation["validation_status"] == "visible_structure_supported"
    assert application["final_geometry_changed"] is False


def test_media_adapter_application_requires_repeated_card_evidence() -> None:
    items = {
        "card_1": {"item_id": "card_1", "role": "media_card"},
        "card_2": {"item_id": "card_2", "role": "media_card"},
        "controls": {"item_id": "controls", "role": "player_controls"},
    }
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="media_catalog",
            structure_signals={"media_cards": True, "playback_controls": True},
        ),
        screen_inventory=list(items.values()),
    )

    application = build_surface_adapter_application(
        decision=decision,
        localized_regions=[],
        items_by_id=items,
    )

    validation = application["content_surface_validation"]
    assert validation["content_adapter_id"] == "media_player"
    assert validation["media_card_evidence_count"] == 2
    assert validation["player_control_evidence_count"] == 1
    assert validation["repeated_media_card_evidence"] is True
    assert validation["validation_status"] == "visible_structure_supported"
    assert application["final_geometry_changed"] is False


def test_media_feed_application_validates_feed_and_visual_card_evidence() -> None:
    items = {item["item_id"]: item for item in _media_feed_inventory()}
    decision = select_learning_surface_adapter(
        bundle=_bundle(
            category="feed_workspace",
            structure_signals={"feed_items": True},
        ),
        screen_inventory=list(items.values()),
    )

    application = build_surface_adapter_application(
        decision=decision,
        localized_regions=[],
        items_by_id=items,
    )

    validation = application["content_surface_validation"]
    assert validation["content_adapter_id"] == "media_feed"
    assert validation["feed_item_evidence_count"] == 2
    assert validation["media_card_evidence_count"] == 2
    assert validation["validation_status"] == "visible_structure_supported"
    assert application["final_geometry_changed"] is False


def test_two_stage_browser_adapter_removes_chrome_items_but_keeps_page_controls(tmp_path: Path) -> None:
    image_path = tmp_path / "browser-stage2.png"
    Image.new("RGB", (800, 600), "white").save(image_path)
    address_bar = {
        "item_id": "address_bar",
        "role": "address_bar",
        "surface_zone": "browser_chrome",
        "label": "https://example.com",
        "bbox": {"x": 80, "y": 20, "w": 600, "h": 36},
        "sources": ["uia"],
    }
    search_button = {
        "item_id": "page_search",
        "role": "button",
        "label": "Search",
        "bbox": {"x": 650, "y": 110, "w": 90, "h": 36},
        "sources": ["uia"],
        "grounding_eligible": True,
    }
    stage1_override = {
        "contract_version": "learn_stage1_structure_regions_v1",
        "source": "test_explicit_stage1_override",
        "structure_regions": [
            {
                "region_id": "deterministic_root_1",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 72},
                "item_ids": ["address_bar"],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            {
                "region_id": "deterministic_root_2",
                "bbox": {"x": 0, "y": 72, "w": 800, "h": 528},
                "item_ids": ["page_search"],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
        ],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }

    result = build_two_stage_screen_understanding(
        bundle={
            **_bundle(app_name="Microsoft Edge", category="generic"),
            "image_path": str(image_path),
            "screen_size": {"width": 800, "height": 600},
        },
        screen_inventory=[address_bar, search_button],
        layout_graph={
            "zones": {},
            "nodes": {"address_bar": address_bar, "page_search": search_button},
        },
        stage1_structure_override=stage1_override,
    )

    numbered_ids = {
        item["item_id"]
        for region in result["stage2_numbering"]["regions"]
        for item in region["numbered_items"]
    }
    assert "address_bar" not in numbered_ids
    assert "page_search" in numbered_ids
    assert result["surface_adapter_application"]["excluded_item_ids"] == ["address_bar"]
    assert result["surface_adapter_application"]["final_geometry_changed"] is False
