from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


RUNTIME_PATH_GRAPH_CONTRACT = "runtime_path_graph_v1"
LIST_DETAIL_PATH_PATTERN_CONTRACT = "list_detail_path_pattern_v1"
LEARNED_SKILL_CONTRACT = "learned_skill_v1"
VISUAL_ASSET_CONTRACT = "visual_asset_v1"
RUNTIME_PATH_GRAPH_EXPORT_CONTRACT = "runtime_path_graph_export_v1"


def build_seek_runtime_path_graph_export(seek_artifact: dict[str, Any] | None) -> dict[str, Any]:
    """Convert a SEEK manual-learning export into the generic path graph artifacts."""

    artifact = seek_artifact if isinstance(seek_artifact, dict) else {}
    runtime_path_graph = build_runtime_path_graph_from_seek_artifact(artifact)
    learned_skills = build_learned_skills_from_seek_artifact(artifact)
    visual_assets = build_visual_assets_from_seek_artifact(artifact)
    return {
        "contract_version": RUNTIME_PATH_GRAPH_EXPORT_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_contract": artifact.get("contract_version"),
        "runtime_path_graph": runtime_path_graph,
        "learned_skills": learned_skills,
        "visual_assets": visual_assets,
    }


def build_runtime_path_graph_from_seek_artifact(seek_artifact: dict[str, Any] | None) -> dict[str, Any]:
    artifact = seek_artifact if isinstance(seek_artifact, dict) else {}
    profile = _dict(artifact.get("learned_app_profile"))
    seed = _dict(artifact.get("path_graph_seed"))
    baseline = _dict(artifact.get("baseline"))
    source = _dict(artifact.get("source"))
    sample_cards = [_dict(item) for item in _dict(seed.get("sample_entities")).get("job_cards") or [] if isinstance(item, dict)]
    return {
        "contract_version": RUNTIME_PATH_GRAPH_CONTRACT,
        "graph_id": "seek_search_results_runtime_path_graph_v1",
        "app_id": "seek",
        "domain": "job_search",
        "page_type": profile.get("page_type") or seed.get("page_type") or "seek_search_results_with_detail",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "learn_mode": "manual_seeded_from_successful_seek_mvp_run",
            "source_contract": artifact.get("contract_version"),
            "source_report_path": source.get("report_path"),
            "source_trace_path": source.get("trace_path"),
            "baseline": baseline,
        },
        "coordinate_policy": {
            "coordinate_space": seed.get("coordinate_space") or "window_screenshot",
            "do_not_reuse_absolute_coordinates_without_reobserve": True,
            "bbox_is_guidance_not_authorization": True,
            "click_point_requires_current_validation": True,
            "coordinate_evidence_required_in_trace": True,
        },
        "state_match_policy": _seek_state_match_policy(),
        "states": _seek_states(),
        "regions": _regions_from_seed(seed),
        "scroll_containers": _scroll_containers_from_profile(profile),
        "entities": _entities_from_sample_cards(sample_cards),
        "dynamic_collections": [
            {
                "collection_id": "seek:job_cards",
                "entity_type": "job_card",
                "region_id": "results_list",
                "container_id": "seek:results_list",
                "entity_pattern_ref": "seek:entity_pattern:job_card",
                "load_more_action_template_id": "load_more_results",
            }
        ],
        "path_patterns": _seek_path_patterns(),
        "transitions": _seek_transitions(),
        "action_templates": _runtime_action_templates(profile),
        "verification_rules": profile.get("verification_rules") or [],
        "safety_policy": profile.get("safety_policy") or {},
        "visual_asset_refs": [
            "seek:visual:apply_button",
            "seek:visual:quick_apply_button",
            "seek:visual:save_icon",
            "seek:visual:job_card_shape",
            "seek:visual:selected_card_highlight",
            "seek:visual:results_scrollbar",
            "seek:visual:detail_scrollbar",
        ],
        "learned_skill_refs": [
            "skill.open_card_from_list",
            "skill.scroll_container_until_new_content",
            "skill.scroll_list_until_new_entities",
            "skill.read_detail_pane_until_bounded",
            "skill.click_seeded_candidate_with_point_validation",
            "skill.block_final_submit",
            "skill.open_record_from_list_or_card",
            "skill.read_fixed_detail_pane_until_complete",
            "skill.scroll_target_container_until_progress_or_boundary",
            "skill.reset_detail_container_to_header",
            "skill.block_final_submit_or_write_action",
        ],
        "metrics": {
            **baseline,
            "sample_entity_count": len(sample_cards),
            "artifact_is_authorization": False,
        },
    }


def build_learned_skills_from_seek_artifact(seek_artifact: dict[str, Any] | None) -> dict[str, Any]:
    baseline = _dict(_dict(seek_artifact).get("baseline"))
    return {
        "contract_version": LEARNED_SKILL_CONTRACT,
        "skill_set_id": "seek_extracted_generic_skills_v1",
        "source_app_id": "seek",
        "source_baseline": baseline,
        "skills": [
            {
                "skill_id": "skill.open_card_from_list",
                "intent": "Open a repeated list card and verify the detail view matches the selected entity.",
                "inputs": ["list_container_id", "entity_title", "entity_company", "seeded_candidate_v1"],
                "requires": ["current_screenshot", "current_candidate_validation", "pre_click_decision_v1"],
                "verification": ["detail_title_company_must_match_clicked_card"],
                "safety": {"artifact_is_guidance_only": True, "final_submit_allowed": False},
            },
            {
                "skill_id": "skill.scroll_container_until_new_content",
                "intent": "Scroll one named container only when visible information is incomplete.",
                "inputs": ["target_container_id", "target_pane", "completion_rule"],
                "requires": ["scroll_precondition_decision_v1", "before_after_container_evidence"],
                "verification": ["target_container_content_should_change"],
                "safety": {"wrong_scope_scroll_must_abort": True},
            },
            {
                "skill_id": "skill.scroll_list_until_new_entities",
                "intent": "Scroll a result list until additional entities are available.",
                "inputs": ["results_container_id", "entity_pattern_ref"],
                "requires": ["container_scope_evidence", "entity_count_before_after"],
                "verification": ["new_entities_or_end_of_list_detected"],
                "safety": {"wrong_scope_scroll_must_abort": True},
            },
            {
                "skill_id": "skill.read_detail_pane_until_bounded",
                "intent": "Read a detail pane by bounded scrolling until required fields are complete.",
                "inputs": ["detail_container_id", "required_evidence"],
                "requires": ["detail_identity_verification", "bounded_scroll_budget"],
                "verification": ["detail_completeness_contract_passed"],
                "safety": {"do_not_click_action_buttons_while_reading": True},
            },
            {
                "skill_id": "skill.click_seeded_candidate_with_point_validation",
                "intent": "Use a learned candidate only after current screenshot validation confirms bbox and click point.",
                "inputs": ["seeded_candidate_v1", "current_screenshot"],
                "requires": ["point_inside_bbox", "vista_or_equivalent_validation", "pre_click_decision_v1"],
                "verification": ["post_click_verification"],
                "safety": {"seed_is_not_authorization": True},
            },
            {
                "skill_id": "skill.block_final_submit",
                "intent": "Block irreversible final submission actions unless a later explicit approval policy allows them.",
                "inputs": ["candidate_label", "page_state"],
                "requires": ["final_submit_guard_v1"],
                "verification": ["blocked_decision_recorded"],
                "safety": {"final_submit": "forbidden"},
            },
            {
                "skill_id": "skill.open_record_from_list_or_card",
                "intent": "Open a repeated record from a list, card stack, table, or search result and verify identity in the detail surface.",
                "inputs": ["list_container_id", "entity_pattern_ref", "identity_mapping"],
                "requires": ["current_candidate_validation", "identity_mapping.primary_key_fields"],
                "verification": ["selected_record_identity_matches_detail"],
                "safety": {"artifact_is_guidance_only": True, "final_submit_allowed": False},
            },
            {
                "skill_id": "skill.read_fixed_detail_pane_until_complete",
                "intent": "Read a fixed detail pane with bounded adaptive scrolling while preserving detail identity.",
                "inputs": ["detail_container_id", "detail_read_policy"],
                "requires": ["detail_header_visible", "bounded_scroll_budget"],
                "verification": ["detail_required_evidence_complete"],
                "safety": {"wrong_scope_scroll_must_abort": True},
            },
            {
                "skill_id": "skill.scroll_target_container_until_progress_or_boundary",
                "intent": "Scroll only the selected container until new evidence appears or a boundary/no-progress condition is reached.",
                "inputs": ["target_container_id", "progress_signals", "stop_after_no_progress_count"],
                "requires": ["before_after_container_evidence", "non_target_stability"],
                "verification": ["progress_or_boundary_recorded"],
                "safety": {"wrong_scope_scroll_must_abort": True},
            },
            {
                "skill_id": "skill.reset_detail_container_to_header",
                "intent": "Reset a detail pane to its header before opening the next record so post-click verification starts from a clean state.",
                "inputs": ["detail_container_id", "header_region_id"],
                "requires": ["previous_action_was_detail_read", "target_container_bbox"],
                "verification": ["detail_header_visible_after_cleanup"],
                "safety": {"wrong_scope_cleanup_blocks_next_click": True},
            },
            {
                "skill_id": "skill.block_final_submit_or_write_action",
                "intent": "Block final submission or persistent write actions unless a later explicit approval policy allows them.",
                "inputs": ["candidate_label", "page_state", "safety_policy_refs"],
                "requires": ["final_submit_guard_v1"],
                "verification": ["blocked_decision_recorded"],
                "safety": {"final_submit": "forbidden", "persistent_write_requires_user_approval": True},
            },
        ],
    }


def build_visual_assets_from_seek_artifact(seek_artifact: dict[str, Any] | None) -> dict[str, Any]:
    source = _dict(_dict(seek_artifact).get("source"))
    return {
        "contract_version": VISUAL_ASSET_CONTRACT,
        "asset_set_id": "seek_visual_assets_v1",
        "source_app_id": "seek",
        "source_report_path": source.get("report_path"),
        "source_trace_path": source.get("trace_path"),
        "assets": [
            _visual_asset("seek:visual:apply_button", "Apply button", "button", ["Apply"], "job_detail"),
            _visual_asset("seek:visual:quick_apply_button", "Quick Apply button", "button", ["Quick Apply"], "job_detail"),
            _visual_asset("seek:visual:save_icon", "Save icon", "icon_button", ["Save", "bookmark"], "job_detail"),
            _visual_asset("seek:visual:job_card_shape", "Job card shape", "card", ["title", "company", "location"], "results_list"),
            _visual_asset("seek:visual:selected_card_highlight", "Selected card highlight", "selection_state", ["selected border"], "results_list"),
            _visual_asset("seek:visual:results_scrollbar", "Results list scrollbar", "scrollbar", ["left list scrollbar"], "results_list"),
            _visual_asset("seek:visual:detail_scrollbar", "Job detail scrollbar", "scrollbar", ["right detail scrollbar"], "job_detail"),
        ],
        "matching_policy": {
            "asset_match_is_evidence_only": True,
            "requires_current_screenshot": True,
            "requires_text_or_layout_corrobation": True,
            "requires_pre_click_gate_for_actions": True,
        },
    }


def _regions_from_seed(seed: dict[str, Any]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    for section in seed.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "").strip()
        if not section_id:
            continue
        regions.append(
            {
                "region_id": section_id,
                "role": section.get("role"),
                "label": section.get("label"),
                "parent_region_id": section.get("parent_section_id"),
                "container_id": section.get("container_id"),
                "repeatable": bool(section.get("repeatable")),
                "contains": section.get("contains") or [],
                "bbox_policy": {
                    "source": "learned_layout_seed",
                    "requires_current_reobserve": True,
                    "no_overlap_except_containment": True,
                },
            }
        )
    return regions


def _scroll_containers_from_profile(profile: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    for item in profile.get("scroll_containers") or []:
        if not isinstance(item, dict):
            continue
        containers.append(
            {
                **item,
                "safe_point_policy": {
                    "source": "current_observe_or_container_detection",
                    "avoid_action_buttons": item.get("container_id") == "seek:job_detail",
                    "requires_before_after_trace": True,
                },
                "artifact_is_authorization": False,
            }
        )
    return containers


def _entities_from_sample_cards(sample_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    for index, card in enumerate(sample_cards):
        entities.append(
            {
                "entity_id": f"seek:job_card:sample:{index}",
                "entity_type": "job_card",
                "region_id": "results_list",
                "container_id": "seek:results_list",
                "title": card.get("title"),
                "company": card.get("company"),
                "location": card.get("location"),
                "bbox": card.get("card_bbox"),
                "click_point": card.get("click_point"),
                "coordinate_evidence": {
                    "source_contract": "seek_job_card_v1",
                    "bbox_source": "traversal_report",
                    "click_point_policy": "seeded_safe_point_inside_card_bbox",
                    "requires_current_reobserve": True,
                    "requires_vista_or_equivalent_validation": True,
                },
            }
        )
    return entities


def _seek_path_patterns() -> list[dict[str, Any]]:
    return [
        {
            "contract_version": LIST_DETAIL_PATH_PATTERN_CONTRACT,
            "pattern_id": "seek:pattern:list_detail_right_pane",
            "pattern_type": "split_list_detail",
            "list_container_id": "seek:results_list",
            "detail_container_id": "seek:job_detail",
            "list_region_id": "results_list",
            "detail_region_id": "job_detail",
            "list_entity_type": "job_card",
            "detail_entity_type": "job_detail",
            "open_action_template_id": "open_job_card",
            "read_detail_action_template_id": "read_detail",
            "load_more_action_template_id": "load_more_results",
            "identity_mapping": {
                "list_entity_type": "job_card",
                "detail_entity_type": "job_detail_header",
                "primary_key_fields": [
                    {
                        "list_field": "title",
                        "detail_field": "title",
                        "match_type": "text_similarity",
                        "min_similarity": 0.82,
                        "required": True,
                    }
                ],
                "secondary_fields": [
                    {
                        "list_field": "company",
                        "detail_field": "company",
                        "match_type": "partial_text_match",
                        "required": False,
                    },
                    {
                        "list_field": "location",
                        "detail_field": "location",
                        "match_type": "partial_text_match",
                        "required": False,
                    },
                ],
                "reject_if_detail_title_source": ["detail_body", "unknown"],
            },
            "detail_read_policy": {
                "detail_container_id": "seek:job_detail",
                "scroll_scope": "container",
                "requires_container_bbox": True,
                "header_region_id": "detail_header",
                "body_region_id": "detail_body",
                "preserve_header_fields_on_scroll": True,
                "adaptive_scroll": {
                    "enabled": True,
                    "initial_wheel_clicks": 5,
                    "max_wheel_clicks": 10,
                    "increase_wheel_on_low_progress": True,
                    "stop_after_no_progress_count": 2,
                    "progress_signals": [
                        "new_unique_text_lines",
                        "detail_crop_hash_changed",
                        "scroll_effect_moved",
                    ],
                },
                "non_target_stability": {
                    "required": True,
                    "stable_container_id": "seek:results_list",
                    "signals": [
                        "visible_card_hashes_stable",
                        "top_card_title_stable",
                        "results_list_crop_hash_stable",
                    ],
                },
                "stop_reasons": [
                    "bottom_reached",
                    "right_detail_no_progress_after_scroll",
                    "max_scrolls_reached",
                    "wrong_scope_scroll_detected",
                ],
            },
            "pre_action_cleanup": [
                {
                    "for_action_template_id": "open_job_card",
                    "when_previous_action_in": ["read_detail", "read_detail_pane_until_bounded"],
                    "cleanup_action": "reset_detail_container_to_header",
                    "target_container_id": "seek:job_detail",
                    "direction": "up",
                    "wheel_clicks": 8,
                    "verify_after_cleanup": {
                        "detail_header_visible": True,
                        "wrong_scope_detected": False,
                    },
                    "reason": "ensure_detail_header_visible_for_next_post_click_verification",
                }
            ],
            "safety_policy_refs": ["final_submit_guard_v1", "artifact_cannot_authorize_click"],
            "artifact_is_authorization": False,
        }
    ]


def _runtime_action_templates(profile: dict[str, Any]) -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for item in profile.get("action_templates") or []:
        if not isinstance(item, dict):
            continue
        action_id = str(item.get("action_id") or "").strip()
        if not action_id:
            continue
        template = {
            **item,
            "action_template_id": action_id,
            "artifact_is_authorization": False,
            "requires_current_validation": True,
            "learned_skill_ref": _skill_for_action(action_id),
            "transition_ref": _transition_for_action(action_id),
        }
        if action_id == "apply_entry":
            template["availability_policy"] = {
                "default_available": False,
                "requires_real_profile": True,
                "requires_explicit_user_approval": True,
                "final_submit_remains_forbidden": True,
            }
        templates.append(template)
    return templates


def _seek_state_match_policy() -> dict[str, Any]:
    return {
        "minimum_confidence": 0.75,
        "required_regions": ["top_search_area", "results_list", "job_detail"],
        "required_anchors_any": ["SEEK", "jobs", "Apply", "Save"],
        "reject_if": ["application_form_detected", "external_site_detected", "login_or_captcha"],
    }


def _seek_states() -> list[dict[str, Any]]:
    return [
        {
            "state_id": "seek_search_results_empty_detail",
            "description": "SEEK results page before a job card has been selected.",
            "required_regions": ["top_search_area", "results_list"],
        },
        {
            "state_id": "seek_search_results_with_selected_job",
            "description": "SEEK results page with a selected job loaded in the detail pane.",
            "required_regions": ["results_list", "job_detail", "detail_header"],
        },
        {
            "state_id": "seek_detail_scrolled",
            "description": "The selected job detail pane has been scrolled for more evidence.",
            "required_regions": ["job_detail", "detail_body"],
        },
        {
            "state_id": "seek_results_list_scrolled",
            "description": "The results list has been scrolled to expose more job cards.",
            "required_regions": ["results_list"],
        },
        {
            "state_id": "seek_apply_entry_form",
            "description": "An apply flow entry state was reached; final submit remains forbidden.",
            "safety": {"final_submit": "forbidden"},
        },
        {
            "state_id": "seek_external_or_blocked",
            "description": "Execution should stop because the page left the learned safe surface or hit a blocker.",
            "terminal": True,
        },
    ]


def _seek_transitions() -> list[dict[str, Any]]:
    return [
        {
            "transition_id": "seek:transition:open_job_card",
            "action_template_id": "open_job_card",
            "from_state_id": "seek_search_results_empty_detail",
            "to_state_id": "seek_search_results_with_selected_job",
            "verification_refs": ["open_job_card_detail_match"],
        },
        {
            "transition_id": "seek:transition:read_detail",
            "action_template_id": "read_detail",
            "from_state_id": "seek_search_results_with_selected_job",
            "to_state_id": "seek_detail_scrolled",
            "verification_refs": ["read_detail_scroll_scope"],
        },
        {
            "transition_id": "seek:transition:load_more_results",
            "action_template_id": "load_more_results",
            "from_state_id": "seek_search_results_with_selected_job",
            "to_state_id": "seek_results_list_scrolled",
            "verification_refs": ["load_more_results_scroll_scope"],
        },
        {
            "transition_id": "seek:transition:apply_entry_guarded",
            "action_template_id": "apply_entry",
            "from_state_id": "seek_search_results_with_selected_job",
            "to_state_id": "seek_apply_entry_form",
            "verification_refs": ["final_submit_forbidden"],
            "default_available": False,
        },
    ]


def _skill_for_action(action_id: str) -> str | None:
    return {
        "open_job_card": "skill.open_card_from_list",
        "read_detail": "skill.read_detail_pane_until_bounded",
        "load_more_results": "skill.scroll_list_until_new_entities",
        "apply_entry": "skill.block_final_submit",
    }.get(action_id)


def _transition_for_action(action_id: str) -> str | None:
    return {
        "open_job_card": "seek:transition:open_job_card",
        "read_detail": "seek:transition:read_detail",
        "load_more_results": "seek:transition:load_more_results",
        "apply_entry": "seek:transition:apply_entry_guarded",
    }.get(action_id)


def _visual_asset(asset_id: str, label: str, role: str, anchors: list[str], region_id: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "label": label,
        "role": role,
        "region_id": region_id,
        "anchors": anchors,
        "source": {
            "capture_required": True,
            "crop_path": None,
            "perceptual_hash": None,
            "embedding_ref": None,
        },
        "match_policy": {
            "minimum_similarity": 0.82,
            "requires_region_match": True,
            "requires_current_validation": True,
        },
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
