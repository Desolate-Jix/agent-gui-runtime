from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.learn.recognition.interface_classification import classify_interface_surface


_ADAPTER_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "layout_priors": ["prefer_observed_geometry_over_surface_assumptions"],
        "excluded_zones": [],
        "validation_rules": ["all_regions_require_observed_evidence"],
    },
    "browser": {
        "layout_priors": [
            "browser_chrome_is_separate_from_page_surface",
            "page_viewport_begins_after_confirmed_browser_chrome",
        ],
        "excluded_zones": ["browser_chrome"],
        "validation_rules": [
            "browser_chrome_must_not_become_page_action",
            "browser_chrome_boundary_requires_visible_evidence",
        ],
    },
    "chat": {
        "layout_priors": [
            "conversation_list_and_thread_are_sibling_surfaces",
            "composer_is_child_of_active_thread",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "conversation_rows_require_repeated_row_evidence",
            "message_content_must_remain_inside_thread_surface",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "conversation_rows",
            "stage1_nested_sidebar_policy": "main_content_child",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": True,
        },
    },
    "mail_workspace": {
        "layout_priors": [
            "mailbox_navigation_and_message_list_are_sibling_surfaces",
            "message_preview_is_child_of_the_selected_mail_row",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "mail_rows_require_repeated_row_evidence",
            "mailbox_navigation_or_toolbar_requires_visible_evidence",
            "mail_rows_must_not_inherit_chat_message_semantics",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "mail_rows",
            "stage1_nested_sidebar_policy": "main_content_child",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
        },
    },
    "media_player": {
        "layout_priors": [
            "repeated_media_cards_are_peer_items",
            "player_controls_are_separate_from_media_cards",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "media_card_requires_visual_parent_evidence",
            "card_text_must_remain_inside_its_visual_parent",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "visual_card_first",
            "allow_media_card_synthesis": True,
            "allow_chat_semantics": False,
        },
    },
    "media_feed": {
        "layout_priors": [
            "repeated_media_feed_cards_are_peer_items",
            "feed_card_text_and_metadata_belong_to_their_visual_parent",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "media_feed_requires_repeated_feed_item_evidence",
            "media_feed_requires_repeated_visual_card_evidence",
            "feed_card_children_must_remain_inside_their_visual_parent",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "visual_feed_card_first",
            "allow_media_card_synthesis": True,
            "allow_chat_semantics": False,
        },
    },
    "news_feed": {
        "layout_priors": [
            "repeated_news_articles_are_peer_items",
            "headline_summary_and_metadata_belong_to_their_article_parent",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "news_feed_requires_repeated_article_evidence",
            "article_children_must_remain_inside_their_article_parent",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "news_article_rows",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
        },
    },
    "video_feed": {
        "layout_priors": [
            "repeated_video_cards_are_peer_items",
            "thumbnail_title_and_metadata_belong_to_their_video_parent",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "video_feed_requires_repeated_video_card_evidence",
            "video_card_children_must_remain_inside_their_video_parent",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "video_card_first",
            "allow_media_card_synthesis": True,
            "allow_chat_semantics": False,
        },
    },
    "search_workspace": {
        "layout_priors": [
            "search_controls_are_separate_from_result_items",
            "repeated_search_results_are_peer_items",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "search_workspace_requires_visible_search_control",
            "search_workspace_requires_repeated_result_evidence",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "search_results",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
        },
    },
    "employment_workflow": {
        "layout_priors": [
            "job_results_detail_and_application_are_distinct_page_states",
            "application_fields_are_children_of_the_active_application_flow",
            "review_summary_is_separate_from_final_submit_controls",
        ],
        "excluded_zones": [],
        "validation_rules": [
            "employment_state_requires_correlated_model_and_inventory_evidence",
            "job_result_cards_require_repeated_job_listing_evidence",
            "application_fields_require_an_application_form_parent",
            "final_submit_controls_remain_forbidden_actions",
        ],
        "stage2_processing_policy": {
            "primary_content_strategy": "employment_workflow",
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
            "final_submit_action_allowed": False,
        },
    },
}

_REPEATED_PEER_LAYOUT_FAMILIES = {
    "media_player": "media_card",
    "media_feed": "media_feed_card",
    "news_feed": "news_article_card",
    "video_feed": "video_card",
    "search_workspace": "search_result",
    "employment_workflow": "job_result_card",
}

_REPEATED_PEER_LAYOUT_STRATEGIES = {
    "independent_content_modules": "independent_content_module",
    "feed_items": "feed_item",
    "search_results": "search_result",
    "visual_card_first": "media_card",
    "visual_feed_card_first": "media_feed_card",
    "news_article_rows": "news_article_card",
    "video_card_first": "video_card",
    "employment_workflow": "job_result_card",
}

_BROWSER_CHROME_TOKENS = {
    "address_bar",
    "browser_chrome",
    "browser_tab",
    "browser_toolbar",
    "extension_button",
    "tab_strip",
}

_STRUCTURAL_ID_TOKEN_ALIASES = {
    "conversation_list": "conversation_row",
    "message_thread": "message_thread",
    "bottom_composer": "composer",
    "message_composer": "composer",
    "input_toolbar": "input_toolbar",
    "job_search": "job_search",
    "job_result_card": "job_result_card",
    "job_listing": "job_listing",
    "job_detail": "job_detail",
    "job_description": "job_description",
    "apply_entry": "apply_entry",
    "application_form": "application_form",
    "application_field": "application_field",
    "application_review": "application_review",
    "final_submit": "final_submit",
}

_MAIL_SEMANTIC_ANCHORS = {
    "compose",
    "drafts",
    "inbox",
    "mail",
    "sent",
    "search_mail",
    "写邮件",
    "发件箱",
    "已发送",
    "收件箱",
    "草稿箱",
    "邮件",
}

_EMPLOYMENT_SEMANTIC_ANCHORS = {
    "application",
    "apply",
    "career",
    "company",
    "cover_letter",
    "cv",
    "employer",
    "job",
    "position",
    "resume",
    "role",
    "公司",
    "申请",
    "简历",
    "职位",
    "求职信",
}

_BROWSER_TAB_SEMANTIC_ANCHORS = {
    "new_tab",
    "new_inprivate_tab",
    "new_incognito_tab",
    "新建标签页",
    "新标签页",
}


def select_learning_surface_adapter(
    *,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
    active_surface_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """选择只读学习策略；应用名只能作为辅助证据。"""

    classification = classify_interface_surface(bundle, screen_inventory=screen_inventory)
    browser_evidence = _browser_chrome_evidence(screen_inventory)
    content_topology_evidence = _content_topology_evidence(screen_inventory)
    content_adapter_id = _validated_content_adapter_id(classification, content_topology_evidence)
    interaction_mode_adapter_id = _validated_interaction_mode_adapter_id(
        classification,
        content_topology_evidence,
    )
    host_adapter_id = "generic"
    adapter_id = "generic"
    status = "insufficient_surface_evidence"
    host_adapter_status = "not_applicable"
    content_adapter_status = "not_applicable"
    rejected_adapter_id = ""
    selection_evidence: list[dict[str, Any]] = []

    app_name = _app_name(bundle)
    if app_name:
        selection_evidence.append(
            {
                "source": "app_name",
                "value": app_name,
                "strength": "weak",
                "used_as_final_decision": False,
            }
        )

    if browser_evidence and _validated_native_surface_conflicts_with_browser(classification):
        status = "browser_evidence_conflicts_with_validated_native_surface"
        host_adapter_status = "evidence_conflict"
        rejected_adapter_id = "browser"
        selection_evidence.extend(browser_evidence)
    elif browser_evidence:
        host_adapter_id = "browser"
        adapter_id = "browser"
        status = "selected_from_visible_evidence"
        host_adapter_status = "selected_from_visible_evidence"
        selection_evidence.extend(browser_evidence)
    elif classification.get("evidence_validation_status") == "category_signal_conflict":
        status = "category_signal_conflict"
    elif content_adapter_id == "chat":
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif content_adapter_id == "media_player":
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif content_adapter_id == "media_feed":
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif content_adapter_id == "mail_workspace":
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif content_adapter_id == "employment_workflow":
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif content_adapter_id in {"news_feed", "video_feed", "search_workspace"}:
        adapter_id = content_adapter_id
        status = "selected_from_visible_evidence"
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    elif (
        classification.get("status") == "accepted"
        and classification.get("category")
        in {
            "conversation_workspace",
            "mail_workspace",
            "media_catalog",
            "feed_workspace",
            "search_workspace",
            "employment_workflow",
        }
    ):
        expected_adapter_id = {
            "conversation_workspace": "chat",
            "mail_workspace": "mail_workspace",
            "media_catalog": "media_player",
            "feed_workspace": "media_feed",
            "search_workspace": "search_workspace",
            "employment_workflow": "employment_workflow",
        }[str(classification.get("category"))]
        competing_adapter_ids = [
            adapter
            for adapter in (
                "chat",
                "mail_workspace",
                "media_player",
                "media_feed",
                "news_feed",
                "video_feed",
                "search_workspace",
                "feed_workspace",
                "employment_workflow",
            )
            if adapter != expected_adapter_id
            and content_topology_evidence.get(adapter, {}).get("eligible") is True
        ]
        status = (
            "content_adapter_evidence_conflict"
            if competing_adapter_ids
            else "content_adapter_evidence_insufficient"
        )
        content_adapter_status = (
            "evidence_conflict"
            if competing_adapter_ids
            else "evidence_insufficient"
        )

    if adapter_id == "browser" and content_adapter_id != "generic":
        content_adapter_status = "selected_from_correlated_model_and_inventory"
        selection_evidence.append(_classification_evidence(classification))
    adapter_chain = list(
        dict.fromkeys(
            value
            for value in (
                host_adapter_id,
                content_adapter_id,
                interaction_mode_adapter_id,
            )
            if value != "generic"
        )
    ) or ["generic"]
    profiles = [_ADAPTER_PROFILES[value] for value in adapter_chain]
    layout_priors = list(dict.fromkeys(value for profile in profiles for value in profile["layout_priors"]))
    excluded_zones = list(dict.fromkeys(value for profile in profiles for value in profile["excluded_zones"]))
    validation_rules = list(dict.fromkeys(value for profile in profiles for value in profile["validation_rules"]))
    stage2_processing_policy = deepcopy(
        _ADAPTER_PROFILES.get(content_adapter_id, {}).get("stage2_processing_policy") or {}
    )
    if interaction_mode_adapter_id != "generic":
        stage2_processing_policy["interaction_mode_adapter_id"] = interaction_mode_adapter_id
    employment_evidence = content_topology_evidence.get("employment_workflow", {})
    employment_page_state = str(employment_evidence.get("page_state") or "unknown")
    if (
        classification.get("category") == "employment_workflow"
        and classification.get("status") == "accepted"
        and employment_page_state == "unknown"
    ):
        employment_page_state = "ambiguous"
    employment_page_state_candidates = list(employment_evidence.get("page_state_candidates") or [])
    if content_adapter_id == "employment_workflow":
        stage2_processing_policy["employment_page_state"] = employment_page_state
        stage2_processing_policy["employment_page_state_candidates"] = employment_page_state_candidates
    decision = {
        "contract_version": "learning_surface_adapter_decision_v1",
        "adapter_id": adapter_id,
        "host_adapter_id": host_adapter_id,
        "content_adapter_id": content_adapter_id,
        "interaction_mode_adapter_id": interaction_mode_adapter_id,
        "adapter_chain": adapter_chain,
        "status": status,
        "host_adapter_status": host_adapter_status,
        "content_adapter_status": content_adapter_status,
        "confidence": _decision_confidence(adapter_id, classification, browser_evidence),
        "selection_evidence": selection_evidence,
        "layout_priors": layout_priors,
        "excluded_zones": excluded_zones,
        "validation_rules": validation_rules,
        "stage2_processing_policy": stage2_processing_policy,
        "employment_page_state": employment_page_state,
        "employment_page_state_candidates": employment_page_state_candidates,
        "excluded_item_ids": (
            sorted(
                {
                    str(item.get("item_id") or "")
                    for item in browser_evidence
                    if str(item.get("item_id") or "").strip()
                }
            )
            if adapter_id == "browser"
            else []
        ),
        "interface_classification": deepcopy(classification),
        "content_topology_evidence": deepcopy(content_topology_evidence),
        "app_name_used_as_final_decision": False,
        "final_geometry_allowed": False,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety_policy_override_allowed": False,
        "interpretation": (
            "Surface adapters provide read-only priors and validators. They do not create final geometry, "
            "click points, or execution authorization."
        ),
    }
    decision["active_surface_rule_advisory"] = _active_surface_rule_advisory(
        decision=decision,
        active_surface_rules=active_surface_rules or [],
    )
    if rejected_adapter_id:
        decision["rejected_adapter_id"] = rejected_adapter_id
    return decision


def _active_surface_rule_advisory(
    *,
    decision: dict[str, Any],
    active_surface_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    adapter_chain = {
        str(value).strip()
        for value in decision.get("adapter_chain", [])
        if str(value).strip() and str(value).strip() != "generic"
    }
    current_evidence_values = {
        str(item.get("value") or "").strip().casefold()
        for item in decision.get("selection_evidence", [])
        if isinstance(item, dict)
        and item.get("source") != "app_name"
        and str(item.get("value") or "").strip()
    }
    matched_rules: list[dict[str, Any]] = []
    ignored_rule_ids: list[str] = []
    for rule in active_surface_rules:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("rule_id") or "").strip()
        entry = rule.get("correction_entry") if isinstance(rule.get("correction_entry"), dict) else {}
        surface = entry.get("surface") if isinstance(entry.get("surface"), dict) else {}
        registry_surface = rule.get("surface") if isinstance(rule.get("surface"), dict) else {}
        adapter_id = str(surface.get("adapter_id") or registry_surface.get("adapter_id") or "").strip()
        rule_evidence_values = {
            str(item.get("value") or "").strip().casefold()
            for item in surface.get("selection_evidence", [])
            if isinstance(item, dict)
            and item.get("source") != "app_name"
            and str(item.get("value") or "").strip()
        }
        eligible = (
            rule.get("status") == "active"
            and rule.get("production_eligible") is True
            and adapter_id in adapter_chain
            and bool(rule_evidence_values.intersection(current_evidence_values))
        )
        if not eligible:
            if rule_id:
                ignored_rule_ids.append(rule_id)
            continue
        corrections = entry.get("corrections") if isinstance(entry.get("corrections"), list) else []
        matched_rules.append(
            {
                "rule_id": rule_id,
                "adapter_id": adapter_id,
                "human_approved_scope": _human_approved_scope(rule),
                "edit_types": sorted(
                    {
                        str(item.get("edit_type") or "").strip()
                        for item in corrections
                        if isinstance(item, dict) and str(item.get("edit_type") or "").strip()
                    }
                ),
                "correction_count": len([item for item in corrections if isinstance(item, dict)]),
                "evidence_match": sorted(rule_evidence_values.intersection(current_evidence_values)),
                "advisory_only": True,
            }
        )
    matched_rules.sort(key=lambda item: item["rule_id"])
    ignored_rule_ids.sort()
    return {
        "contract_version": "learning_active_surface_rule_advisory_v1",
        "policy": "active_only",
        "matched_rule_ids": [item["rule_id"] for item in matched_rules],
        "ignored_rule_ids": ignored_rule_ids,
        "matched_rules": matched_rules,
        "old_screenshot_geometry_reused": False,
        "final_geometry_changed": False,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety_policy_override_allowed": False,
        "interpretation": (
            "Active human correction rules are advisory metadata only. Current screenshot geometry still "
            "requires the normal recognition, precise-localization, rerank, and Gate chain."
        ),
    }


def _human_approved_scope(rule: dict[str, Any]) -> str:
    history = rule.get("transition_history") if isinstance(rule.get("transition_history"), list) else []
    for transition in reversed(history):
        if not isinstance(transition, dict) or transition.get("to_status") != "human_approved":
            continue
        evidence = transition.get("evidence") if isinstance(transition.get("evidence"), dict) else {}
        return str(evidence.get("scope") or "").strip()
    return ""


def build_surface_adapter_stage2_policy(
    *,
    decision: dict[str, Any],
    legacy_class_rule_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把已验证的内容 Adapter 编译为 Stage2 只读策略。"""

    content_adapter_id = str(decision.get("content_adapter_id") or "generic")
    adapter_policy = decision.get("stage2_processing_policy")
    adapter_policy = deepcopy(adapter_policy) if isinstance(adapter_policy, dict) else {}
    if content_adapter_id in {
        "chat",
        "mail_workspace",
        "media_player",
        "media_feed",
        "news_feed",
        "video_feed",
        "search_workspace",
        "employment_workflow",
    } and adapter_policy:
        policy = adapter_policy
        policy_source = "surface_adapter"
    else:
        policy = deepcopy(legacy_class_rule_profile) if isinstance(legacy_class_rule_profile, dict) else {}
        policy_source = "legacy_interface_classification"
    peer_item_family = _REPEATED_PEER_LAYOUT_FAMILIES.get(content_adapter_id, "")
    if not peer_item_family:
        peer_item_family = _REPEATED_PEER_LAYOUT_STRATEGIES.get(
            str(policy.get("primary_content_strategy") or ""),
            "",
        )
    policy["repeated_peer_layout_review"] = {
        "class_prior": "expected" if peer_item_family else "not_declared",
        "peer_item_family": peer_item_family,
        "activation": "current_visual_repetition_required",
        "normalization_scope": "existing_peer_candidates_for_review_only",
        "neighbor_inference": "one_hop_review_candidates_only",
        "can_create_without_visual_support": False,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    policy.update(
        {
            "contract_version": "learning_surface_adapter_stage2_policy_v1",
            "policy_source": policy_source,
            "content_adapter_id": content_adapter_id,
            "final_geometry_allowed": False,
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "safety_policy_override_allowed": False,
        }
    )
    return policy


def surface_adapter_excludes_inventory_item(
    decision: dict[str, Any],
    item: dict[str, Any],
) -> bool:
    """仅按显式证据排除浏览器外壳元素，不按位置或应用名推断。"""

    if not _browser_adapter_is_active(decision):
        return False
    item_ids = {
        str(item.get(key) or "").strip()
        for key in ("item_id", "candidate_id", "source_item_id", "source_id")
        if str(item.get(key) or "").strip()
    }
    excluded_item_ids = {
        str(value).strip()
        for value in decision.get("excluded_item_ids", [])
        if str(value).strip()
    }
    if item_ids.intersection(excluded_item_ids):
        return True
    return bool(_item_surface_tokens(item).intersection(_BROWSER_CHROME_TOKENS))


def build_surface_adapter_application(
    *,
    decision: dict[str, Any],
    localized_regions: list[dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """把 Adapter 先验编译为可审计过滤范围，不修改任何几何。"""

    browser_active = _browser_adapter_is_active(decision)
    content_adapter_id = str(decision.get("content_adapter_id") or "generic")
    content_surface_validation = _content_surface_validation(
        content_adapter_id=content_adapter_id,
        items_by_id=items_by_id,
    )
    excluded_item_ids = sorted(
        item_id
        for item_id, item in items_by_id.items()
        if browser_active and surface_adapter_excludes_inventory_item(decision, item)
    )
    excluded_set = set(excluded_item_ids)
    region_candidates: list[dict[str, Any]] = []
    for region in localized_regions:
        if not isinstance(region, dict):
            continue
        region_item_ids = {
            str(value).strip()
            for value in region.get("item_ids", [])
            if str(value).strip()
        }
        matched_ids = sorted(region_item_ids.intersection(excluded_set))
        if not matched_ids:
            continue
        bbox = region.get("bbox") if isinstance(region.get("bbox"), dict) else {}
        region_candidates.append(
            {
                "region_id": str(region.get("region_id") or ""),
                "matched_item_ids": matched_ids,
                "contains_non_chrome_items": bool(region_item_ids - excluded_set),
                "top_anchored": int(bbox.get("y") or 0) == 0,
                "candidate_only": True,
            }
        )
    return {
        "contract_version": "learning_surface_adapter_application_v1",
        "adapter_id": str(decision.get("adapter_id") or "generic"),
        "host_adapter_id": str(decision.get("host_adapter_id") or "generic"),
        "content_adapter_id": content_adapter_id,
        "status": (
            "applied_from_explicit_evidence"
            if browser_active
            or content_adapter_id
            in {
                "chat",
                "mail_workspace",
                "media_player",
                "media_feed",
                "news_feed",
                "video_feed",
                "search_workspace",
                "employment_workflow",
            }
            else "not_applicable"
        ),
        "excluded_item_ids": excluded_item_ids,
        "browser_chrome_region_candidates": region_candidates,
        "content_surface_validation": content_surface_validation,
        "fixed_height_boundary_used": False,
        "app_name_boundary_used": False,
        "final_geometry_changed": False,
        "validation_results": {
            "explicit_browser_chrome_evidence_present": bool(excluded_item_ids),
            "all_candidate_regions_top_anchored": bool(region_candidates)
            and all(item["top_anchored"] for item in region_candidates),
            "mixed_root_region_detected": any(
                item["contains_non_chrome_items"] for item in region_candidates
            ),
            "page_viewport_boundary_inferred": False,
        },
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "interpretation": (
            "Browser chrome exclusion is scoped to explicit inventory evidence. Root geometry remains the "
            "authoritative deterministic partition; no fixed-height viewport boundary is created here."
        ),
    }


def _content_surface_validation(
    *,
    content_adapter_id: str,
    items_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    token_sets = [_item_surface_tokens(item) for item in items_by_id.values() if isinstance(item, dict)]
    base = {
        "contract_version": "learning_surface_content_validation_v1",
        "content_adapter_id": content_adapter_id,
        "geometry_changed": False,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    if content_adapter_id == "chat":
        conversation_rows = sum(
            bool(tokens.intersection({"conversation_row", "contact_row", "person_row", "conversation_list_item"}))
            for tokens in token_sets
        )
        message_threads = sum(
            bool(tokens.intersection({"message_thread", "chat_thread", "message_pane"}))
            for tokens in token_sets
        )
        composers = sum(
            bool(tokens.intersection({"composer", "bottom_composer", "message_input", "input_toolbar"}))
            for tokens in token_sets
        )
        supported = conversation_rows >= 1 and message_threads >= 1 and composers >= 1
        return {
            **base,
            "conversation_row_evidence_count": conversation_rows,
            "message_thread_evidence_count": message_threads,
            "composer_evidence_count": composers,
            "validation_status": (
                "visible_structure_supported" if supported else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "mail_workspace":
        mail_rows = sum(
            bool(tokens.intersection({"mail_row", "email_row", "message_list_row"}))
            for tokens in token_sets
        )
        mailbox_navigation = sum(
            bool(tokens.intersection({"mailbox_navigation", "mail_folder_list", "mail_sidebar"}))
            for tokens in token_sets
        )
        mail_toolbars = sum(
            bool(tokens.intersection({"mail_toolbar", "mail_actions", "message_toolbar"}))
            for tokens in token_sets
        )
        supported = mail_rows >= 2 and (mailbox_navigation >= 1 or mail_toolbars >= 1)
        return {
            **base,
            "mail_row_evidence_count": mail_rows,
            "mailbox_navigation_evidence_count": mailbox_navigation,
            "mail_toolbar_evidence_count": mail_toolbars,
            "validation_status": (
                "visible_structure_supported" if supported else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "media_player":
        media_cards = sum(
            bool(tokens.intersection({"media_card", "recommendation_item", "album_card", "playlist_card"}))
            for tokens in token_sets
        )
        player_controls = sum(
            bool(
                tokens.intersection(
                    {
                        "player_controls",
                        "playback_controls",
                        "media_controls",
                        "media_library_navigation",
                        "library_navigation",
                        "player_navigation",
                    }
                )
            )
            for tokens in token_sets
        )
        return {
            **base,
            "media_card_evidence_count": media_cards,
            "player_control_evidence_count": player_controls,
            "repeated_media_card_evidence": media_cards >= 2,
            "validation_status": (
                "visible_structure_supported"
                if media_cards >= 2 and player_controls >= 1
                else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "media_feed":
        media_cards = sum(
            bool(tokens.intersection({"media_card", "recommendation_item", "album_card", "playlist_card"}))
            for tokens in token_sets
        )
        feed_items = sum(
            bool(tokens.intersection({"feed_item", "post_card", "social_post", "timeline_item"}))
            for tokens in token_sets
        )
        supported = media_cards >= 2 and feed_items >= 2
        return {
            **base,
            "media_card_evidence_count": media_cards,
            "feed_item_evidence_count": feed_items,
            "repeated_media_card_evidence": media_cards >= 2,
            "repeated_feed_item_evidence": feed_items >= 2,
            "validation_status": (
                "visible_structure_supported"
                if supported
                else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "news_feed":
        news_articles = sum(
            bool(tokens.intersection({"news_article_card", "news_item", "article_card", "headline_item"}))
            for tokens in token_sets
        )
        news_sections = sum(
            bool(tokens.intersection({"news_section", "headline_list", "article_list"}))
            for tokens in token_sets
        )
        supported = news_articles >= 2 and news_sections >= 1
        return {
            **base,
            "news_article_evidence_count": news_articles,
            "news_section_evidence_count": news_sections,
            "validation_status": (
                "visible_structure_supported"
                if supported
                else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "video_feed":
        video_cards = sum(
            bool(tokens.intersection({"video_card", "video_item", "video_result"}))
            for tokens in token_sets
        )
        video_thumbnails = sum(
            bool(tokens.intersection({"video_thumbnail", "media_thumbnail"}))
            for tokens in token_sets
        )
        supported = video_cards >= 2 and video_thumbnails >= 2
        return {
            **base,
            "video_card_evidence_count": video_cards,
            "video_thumbnail_evidence_count": video_thumbnails,
            "validation_status": (
                "visible_structure_supported"
                if supported
                else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "search_workspace":
        search_controls = sum(
            bool(tokens.intersection({"search_input", "search_box", "query_input", "search_control"}))
            for tokens in token_sets
        )
        search_results = sum(
            bool(tokens.intersection({"search_result", "result_item", "search_result_item"}))
            for tokens in token_sets
        )
        supported = search_controls >= 1 and search_results >= 2
        return {
            **base,
            "search_control_evidence_count": search_controls,
            "search_result_evidence_count": search_results,
            "validation_status": (
                "visible_structure_supported"
                if supported
                else "selected_adapter_needs_structure_review"
            ),
        }
    if content_adapter_id == "employment_workflow":
        evidence = _content_topology_evidence(list(items_by_id.values()))["employment_workflow"]
        return {
            **base,
            **deepcopy(evidence),
            "validation_status": (
                "visible_structure_supported"
                if evidence["eligible"] is True
                else "selected_adapter_needs_structure_review"
            ),
        }
    return {**base, "validation_status": "not_applicable"}


def _classification_is_validated(classification: dict[str, Any], category: str, signal: str) -> bool:
    if classification.get("category") != category or classification.get("status") != "accepted":
        return False
    structure_signals = classification.get("structure_signals")
    return isinstance(structure_signals, dict) and structure_signals.get(signal) is True


def _validated_content_adapter_id(
    classification: dict[str, Any],
    content_topology_evidence: dict[str, dict[str, Any]],
) -> str:
    if (
        _classification_is_validated(classification, "feed_workspace", "feed_items")
        and _classification_signal(classification, "news_items")
        and content_topology_evidence["news_feed"]["eligible"] is True
    ):
        return "news_feed"
    if (
        (
            _classification_is_validated(classification, "media_catalog", "media_cards")
            or _classification_is_validated(classification, "feed_workspace", "feed_items")
            or _classification_is_validated(classification, "search_workspace", "search_results")
        )
        and _classification_signal(classification, "video_items")
        and content_topology_evidence["video_feed"]["eligible"] is True
    ):
        return "video_feed"
    if (
        _classification_is_validated(classification, "search_workspace", "search_results")
        and _classification_signal(classification, "search_controls")
        and content_topology_evidence["search_workspace"]["eligible"] is True
    ):
        return "search_workspace"
    if (
        _classification_is_validated(classification, "conversation_workspace", "people_or_conversation_rows")
        and _classification_signal(classification, "message_thread")
        and _classification_signal(classification, "message_composer")
        and content_topology_evidence["chat"]["eligible"] is True
    ):
        return "chat"
    if (
        _classification_is_validated(classification, "mail_workspace", "mail_or_email_rows")
        and (
            _classification_signal(classification, "mailbox_navigation")
            or _classification_signal(classification, "mail_toolbar")
        )
        and content_topology_evidence["mail_workspace"]["eligible"] is True
    ):
        return "mail_workspace"
    if (
        (
            _classification_is_validated(classification, "feed_workspace", "feed_items")
            or (
                _classification_is_validated(classification, "media_catalog", "media_cards")
                and _classification_signal(classification, "feed_items")
            )
        )
        and content_topology_evidence["feed_workspace"]["eligible"] is True
        and content_topology_evidence["media_feed"]["eligible"] is True
    ):
        return "media_feed"
    if (
        _classification_is_validated(classification, "media_catalog", "media_cards")
        and (
            _classification_signal(classification, "playback_controls")
            or _classification_signal(classification, "media_library_navigation")
        )
        and not _classification_signal(classification, "feed_items")
        and content_topology_evidence["media_player"]["eligible"] is True
        and content_topology_evidence["feed_workspace"]["eligible"] is not True
    ):
        return "media_player"
    if (
        _classification_is_validated(
            classification,
            "employment_workflow",
            "employment_workflow",
        )
        and content_topology_evidence["employment_workflow"]["eligible"] is True
    ):
        return "employment_workflow"
    return "generic"


def _validated_interaction_mode_adapter_id(
    classification: dict[str, Any],
    content_topology_evidence: dict[str, dict[str, Any]],
) -> str:
    if (
        _classification_is_validated(classification, "search_workspace", "search_results")
        and _classification_signal(classification, "search_controls")
        and content_topology_evidence["search_workspace"]["eligible"] is True
    ):
        return "search_workspace"
    return "generic"


def _classification_signal(classification: dict[str, Any], signal: str) -> bool:
    structure_signals = classification.get("structure_signals")
    return isinstance(structure_signals, dict) and structure_signals.get(signal) is True


def _content_topology_evidence(screen_inventory: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    token_sets = [
        _item_surface_tokens(item)
        for item in screen_inventory
        if isinstance(item, dict)
    ]

    def count(*roles: str) -> int:
        expected = set(roles)
        return sum(bool(tokens.intersection(expected)) for tokens in token_sets)

    conversation_rows = count("conversation_row", "contact_row", "person_row")
    message_threads = count("message_thread", "thread_surface", "conversation_thread")
    composers = count("composer", "message_composer", "input_toolbar")
    explicit_mail_rows = count("mail_row", "email_row", "message_list_row")
    legacy_mail_rows = count("conversation_row", "table_row")
    mailbox_navigation = count(
        "mailbox_navigation",
        "mail_folder_list",
        "mail_sidebar",
        "left_sidebar",
        "nav_item",
    )
    mail_toolbars = count("mail_toolbar", "mail_actions", "message_toolbar", "top_bar")
    mail_semantic_anchors = sum(
        _item_has_mail_semantic_anchor(item)
        for item in screen_inventory
        if isinstance(item, dict)
    )
    mail_rows = explicit_mail_rows + legacy_mail_rows
    media_cards = count("media_card", "recommendation_item", "album_card", "playlist_card")
    playback_controls = count("player_controls", "playback_controls", "media_controls")
    media_navigation = count("media_library_navigation", "library_navigation", "player_navigation")
    feed_items = count("feed_item", "post_card", "social_post", "timeline_item")
    news_articles = count(
        "news_article_card",
        "news_card",
        "news_item",
        "article_card",
        "headline_item",
    )
    news_sections = count("news_section", "headline_list", "article_list")
    peer_tile_cards = count("tile_card")
    video_cards = count("video_card", "video_item", "video_result")
    video_thumbnails = count("video_thumbnail", "media_thumbnail")
    search_controls = count("search_input", "search_box", "query_input", "search_control")
    search_results = count("search_result", "result_item", "search_result_item")
    job_result_cards = count(
        "job_card",
        "job_listing",
        "job_result",
        "job_result_card",
        "search_result_job",
    )
    job_search_controls = count(
        "job_filter",
        "job_filter_group",
        "job_search",
        "job_search_bar",
        "job_search_controls",
    )
    job_detail_content = count(
        "job_detail",
        "job_description",
        "job_detail_content",
        "job_summary",
    )
    apply_entries = count(
        "apply_entry",
        "open_apply_flow",
        "quick_apply_entry",
    )
    application_forms = count(
        "application_form",
        "job_application_form",
    )
    application_fields = count(
        "application_field",
        "application_question",
        "cover_letter_field",
        "resume_upload",
    )
    application_reviews = count(
        "application_review",
        "application_summary",
        "review_application",
    )
    final_submit_controls = count(
        "complete_application",
        "final_submit",
        "send_application",
        "submit_application",
    )
    employment_semantic_anchors = sum(
        _item_has_employment_semantic_anchor(item)
        for item in screen_inventory
        if isinstance(item, dict)
    )
    employment_states = {
        "job_search_results": (
            job_result_cards >= 2
            and (job_search_controls >= 1 or employment_semantic_anchors >= 2)
        ),
        "job_detail": job_detail_content >= 1 and apply_entries >= 1,
        "application_form": application_forms >= 1 and application_fields >= 2,
        "application_review": application_reviews >= 1 and final_submit_controls >= 1,
    }
    employment_page_state_candidates = [
        state for state, eligible in employment_states.items() if eligible
    ]
    employment_page_state = (
        employment_page_state_candidates[0]
        if len(employment_page_state_candidates) == 1
        else "mixed"
        if len(employment_page_state_candidates) > 1
        else "unknown"
    )

    return {
        "chat": {
            "eligible": conversation_rows >= 1 and message_threads >= 1 and composers >= 1,
            "conversation_row_count": conversation_rows,
            "message_thread_count": message_threads,
            "composer_count": composers,
        },
        "mail_workspace": {
            "eligible": (
                mail_rows >= 2
                and (explicit_mail_rows >= 2 or mail_semantic_anchors >= 2)
                and (mailbox_navigation >= 1 or mail_toolbars >= 1)
            ),
            "mail_row_count": mail_rows,
            "explicit_mail_row_count": explicit_mail_rows,
            "legacy_row_count": legacy_mail_rows,
            "mailbox_navigation_count": mailbox_navigation,
            "mail_toolbar_count": mail_toolbars,
            "mail_semantic_anchor_count": mail_semantic_anchors,
        },
        "media_player": {
            "eligible": media_cards >= 2 and (playback_controls >= 1 or media_navigation >= 1),
            "media_card_count": media_cards,
            "playback_control_count": playback_controls,
            "media_navigation_count": media_navigation,
        },
        "media_feed": {
            "eligible": media_cards >= 2 and feed_items >= 2,
            "media_card_count": media_cards,
            "feed_item_count": feed_items,
        },
        "feed_workspace": {
            "eligible": feed_items >= 2,
            "feed_item_count": feed_items,
        },
        "news_feed": {
            "eligible": (
                news_articles >= 2
                and (news_sections >= 1 or peer_tile_cards >= 3)
            ),
            "news_article_count": news_articles,
            "news_section_count": news_sections,
            "peer_tile_card_count": peer_tile_cards,
        },
        "video_feed": {
            "eligible": video_cards >= 2 and video_thumbnails >= 2,
            "video_card_count": video_cards,
            "video_thumbnail_count": video_thumbnails,
        },
        "search_workspace": {
            "eligible": search_controls >= 1 and search_results >= 2,
            "search_control_count": search_controls,
            "search_result_count": search_results,
        },
        "employment_workflow": {
            "eligible": bool(employment_page_state_candidates),
            "page_state": employment_page_state,
            "page_state_candidates": employment_page_state_candidates,
            "job_result_card_count": job_result_cards,
            "job_search_control_count": job_search_controls,
            "job_detail_content_count": job_detail_content,
            "apply_entry_count": apply_entries,
            "application_form_count": application_forms,
            "application_field_count": application_fields,
            "application_review_count": application_reviews,
            "final_submit_control_count": final_submit_controls,
            "employment_semantic_anchor_count": employment_semantic_anchors,
        },
    }


def _validated_native_surface_conflicts_with_browser(classification: dict[str, Any]) -> bool:
    if classification.get("status") != "accepted":
        return False
    if classification.get("evidence_validation_status") != "validated":
        return False
    return classification.get("category") in {"file_browser", "settings_dashboard"}


def _classification_evidence(classification: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "model_interface_classification",
        "value": str(classification.get("category") or ""),
        "strength": "validated_structure_signal",
        "confidence": float(classification.get("confidence") or 0.0),
    }


def _browser_chrome_evidence(screen_inventory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    semantic_regions: list[dict[str, Any]] = []
    url_items: list[dict[str, Any]] = []
    browser_tab_items: list[dict[str, Any]] = []
    top_control_strips: list[dict[str, Any]] = []
    for item in screen_inventory:
        if not isinstance(item, dict):
            continue
        values = _item_surface_tokens(item)
        if _item_has_browser_tab_semantic_anchor(item):
            browser_tab_items.append(item)
        if "topbar_control_strip" in values:
            top_control_strips.append(item)
        matching_values = sorted(values.intersection(_BROWSER_CHROME_TOKENS - {"browser_chrome"}))
        if "browser_chrome" in values:
            semantic_regions.append(item)
        if _item_contains_url_evidence(item):
            url_items.append(item)
        if not matching_values:
            continue
        evidence.append(
            {
                "source": "screen_inventory",
                "item_id": str(item.get("item_id") or item.get("id") or ""),
                "value": matching_values[0],
                "strength": "visible_structure",
            }
        )
    if browser_tab_items and top_control_strips:
        for item in browser_tab_items:
            evidence.append(
                {
                    "source": "screen_inventory",
                    "item_id": str(item.get("item_id") or item.get("id") or ""),
                    "value": "browser_tab_semantic_anchor",
                    "strength": "visible_structure_with_top_control_strip",
                    "corroborating_item_ids": sorted(
                        str(candidate.get("item_id") or candidate.get("id") or "")
                        for candidate in top_control_strips
                        if str(candidate.get("item_id") or candidate.get("id") or "").strip()
                    ),
                }
            )
    for region in semantic_regions:
        corroborators = [item for item in url_items if _item_is_inside_region(item, region)]
        if not corroborators:
            continue
        region_id = str(region.get("item_id") or region.get("id") or "")
        evidence.append(
            {
                "source": "screen_inventory",
                "item_id": region_id,
                "value": "browser_chrome",
                "strength": "visible_structure_with_url_corroboration",
                "corroborating_item_ids": sorted(
                    str(item.get("item_id") or item.get("id") or "")
                    for item in corroborators
                    if str(item.get("item_id") or item.get("id") or "").strip()
                ),
            }
        )
        for item in corroborators:
            item_id = str(item.get("item_id") or item.get("id") or "")
            if not item_id:
                continue
            evidence.append(
                {
                    "source": "screen_inventory",
                    "item_id": item_id,
                    "value": "url_text_inside_browser_chrome",
                    "strength": "visible_corroboration",
                    "corroborates_item_id": region_id,
                }
            )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for item in evidence:
        key = (str(item.get("item_id") or ""), str(item.get("value") or ""))
        unique[key] = item
    return [unique[key] for key in sorted(unique)]


def _item_has_browser_tab_semantic_anchor(item: dict[str, Any]) -> bool:
    tokens = _item_surface_tokens(item)
    if not tokens.intersection({"nav_item", "browser_tab", "tab"}):
        return False
    text = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("label", "name", "description", "text")
    )
    normalized = "_".join(text.replace("/", " ").replace("-", " ").split())
    return any(anchor in normalized for anchor in _BROWSER_TAB_SEMANTIC_ANCHORS)


def _browser_adapter_is_active(decision: dict[str, Any]) -> bool:
    return (
        decision.get("adapter_id") == "browser"
        and decision.get("status") == "selected_from_visible_evidence"
        and "browser_chrome" in decision.get("excluded_zones", [])
        and decision.get("final_geometry_allowed") is False
    )


def _item_surface_tokens(item: dict[str, Any]) -> set[str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    tokens = {
        str(item.get("surface_zone") or "").casefold().replace(" ", "_"),
        str(item.get("role") or "").casefold().replace(" ", "_"),
        str(item.get("role_guess") or "").casefold().replace(" ", "_"),
        str(item.get("item_type") or "").casefold().replace(" ", "_"),
        str(metadata.get("surface_zone") or "").casefold().replace(" ", "_"),
        str(metadata.get("role") or "").casefold().replace(" ", "_"),
        str(metadata.get("semantic_role") or "").casefold().replace(" ", "_"),
    }
    structural_id = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("item_id", "candidate_id", "source_item_id", "source_id", "region_id")
    )
    tokens.update(
        canonical
        for fragment, canonical in _STRUCTURAL_ID_TOKEN_ALIASES.items()
        if fragment in structural_id
    )
    return {token for token in tokens if token}


def _item_has_mail_semantic_anchor(item: dict[str, Any]) -> bool:
    tokens = _item_surface_tokens(item)
    nav_like = bool(
        tokens.intersection(
            {
                "left_sidebar",
                "mailbox_navigation",
                "mail_folder_list",
                "mail_sidebar",
                "nav_item",
                "input",
                "top_bar",
            }
        )
    )
    if not nav_like:
        return False
    text = str(item.get("label") or item.get("name") or "").casefold()
    normalized = "_".join(text.replace("/", " ").replace("-", " ").split())
    return any(anchor in normalized for anchor in _MAIL_SEMANTIC_ANCHORS)


def _item_has_employment_semantic_anchor(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("label", "name", "description", "text")
    )
    normalized = "_".join(text.replace("/", " ").replace("-", " ").split())
    return any(anchor in normalized for anchor in _EMPLOYMENT_SEMANTIC_ANCHORS)


def _item_contains_url_evidence(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("label", "text", "name", "value", "description")
    )
    return any(token in text for token in ("http://", "https://", "www."))


def _item_is_inside_region(item: dict[str, Any], region: dict[str, Any]) -> bool:
    item_bbox = _adapter_bbox(item.get("bbox"))
    region_bbox = _adapter_bbox(region.get("bbox"))
    if item_bbox is None or region_bbox is None:
        return False
    center_x = item_bbox["x"] + item_bbox["w"] / 2
    center_y = item_bbox["y"] + item_bbox["h"] / 2
    return (
        region_bbox["x"] <= center_x <= region_bbox["x"] + region_bbox["w"]
        and region_bbox["y"] <= center_y <= region_bbox["y"] + region_bbox["h"]
    )


def _adapter_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: int(value.get(key) or 0) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return bbox if bbox["w"] > 0 and bbox["h"] > 0 else None


def _decision_confidence(
    adapter_id: str,
    classification: dict[str, Any],
    browser_evidence: list[dict[str, Any]],
) -> float:
    if adapter_id == "browser":
        return min(1.0, 0.75 + (0.05 * min(3, len(browser_evidence))))
    if adapter_id in {"chat", "mail_workspace", "media_player", "employment_workflow"}:
        return round(float(classification.get("confidence") or 0.0), 4)
    return 0.0


def _app_name(bundle: dict[str, Any]) -> str:
    request = bundle.get("request") if isinstance(bundle.get("request"), dict) else {}
    result = bundle.get("result") if isinstance(bundle.get("result"), dict) else {}
    return str(bundle.get("app_name") or request.get("app_name") or result.get("app_name") or "").strip()
