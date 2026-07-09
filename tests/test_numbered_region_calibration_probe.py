from __future__ import annotations

from scripts.run_numbered_region_calibration_probe import (
    build_seeded_candidate,
    build_tasks_from_actual_parser_locator_cards,
    enrich_regions_with_parser_context,
    classify_case_outcome,
    run_numbered_region_calibration_probe,
    request_for_region_for_test,
)


def test_build_seeded_candidate_uses_numbered_region_as_execute_seed() -> None:
    region = {
        "region_no": 2,
        "item_id": "uia_control_2",
        "label": "SEEK search button",
        "role": "button",
        "rough_bbox_hint": {"x": 1820, "y": 184, "w": 92, "h": 48},
    }

    seed = build_seeded_candidate(region)

    assert seed["contract_version"] == "seeded_candidate_v1"
    assert seed["candidate_id"] == "numbered_region_2_uia_control_2"
    assert seed["bbox"] == {"x": 1820, "y": 184, "w": 92, "h": 48}
    assert seed["click_point"] == {"x": 1866, "y": 208}
    assert seed["risk_class"] == "safe_click_allowed"


def test_classify_case_outcome_marks_model_disagreement_fallback_as_review() -> None:
    outcome = classify_case_outcome(
        success=True,
        pre_click_allowed=True,
        candidate_summary={
            "vista_point_grounding_used": True,
            "vista_point_inside_candidate_bbox": False,
            "seeded_candidate_primary_point_used": True,
        },
        error_code=None,
        evidence_level="uia_control",
    )

    assert outcome["status"] == "needs_human_review"
    assert outcome["category"] == "model_disagreed_with_seed_fallback_used"
    assert outcome["promotable_to_learning_draft"] is False


def test_classify_case_outcome_keeps_semantic_only_seed_under_review() -> None:
    outcome = classify_case_outcome(
        success=True,
        pre_click_allowed=True,
        candidate_summary={
            "vista_point_grounding_used": True,
            "vista_point_inside_candidate_bbox": True,
            "seeded_candidate_primary_point_used": False,
        },
        error_code=None,
        evidence_level="semantic_region_only",
    )

    assert outcome["status"] == "needs_human_review"
    assert outcome["category"] == "semantic_region_only_seed_requires_review"
    assert outcome["promotable_to_learning_draft"] is False


def test_enrich_regions_with_parser_context_outputs_detailed_locator_prompt() -> None:
    tasks = {
        "regions": [
            {
                "region_no": 1,
                "item_id": "uia_control_1",
                "label": "Search keyword field",
                "role": "input",
                "evidence_level": "uia_control",
                "rough_bbox_hint": {"x": 100, "y": 50, "w": 300, "h": 40},
            },
            {
                "region_no": 2,
                "item_id": "uia_control_2",
                "label": "SEEK search button",
                "role": "button",
                "evidence_level": "uia_control",
                "rough_bbox_hint": {"x": 420, "y": 50, "w": 80, "h": 40},
            },
        ]
    }
    parser_output = {
        "screen_inventory": [
            {
                "item_id": "uia_control_1",
                "label": "Search keyword field",
                "role": "input",
                "text": "Search keyword field",
                "evidence_level": "uia_control",
                "metadata": {"control_type": "Edit", "patterns": ["Value"]},
            }
        ],
        "observe_bundle": {
            "sources": {
                "vision": {
                    "regions": [
                        {
                            "region_id": "uia_control_1",
                            "description": "white rounded keyword input with search icon",
                            "text_lines": ["Describe what you’re looking for"],
                        }
                    ]
                }
            }
        },
    }

    enriched = enrich_regions_with_parser_context(tasks, parser_output)
    prompt = enriched["regions"][0]["prompt"]

    assert "Target visible text: Search keyword field" in prompt
    assert "Visual description: white rounded keyword input with search icon" in prompt
    assert "Right neighbor: #2 SEEK search button" in prompt
    assert "The rough bbox is only a hint and may be wrong" in prompt
    assert "Do not click browser toolbar, clear icons, final submit, send, confirm, payment" in prompt
    assert enriched["regions"][0]["locator_task_card"]["evidence_level"] == "uia_control"


def test_build_tasks_from_actual_parser_locator_cards_creates_calibration_regions() -> None:
    actual_parser_output = {
        "screenshot_path": "screen.png",
        "locator_task_cards": {
            "contract_version": "learn_locator_task_cards_v1",
            "cards": [
                {
                    "source_item_id": "c4",
                    "target_name": "Job listing card",
                    "target_role": "card",
                    "target_visible_text": "Job listing card",
                    "visual_description": "Job card for Software Engineer at AIA New Zealand",
                    "text_lines": [
                        "Software Engineer Specialist - Integration",
                        "AIA New Zealand",
                        "Takapuna, Auckland",
                    ],
                    "boundary_definition": "single white card, excluding next card below",
                    "clickable_area_hint": "safe interior around title and company text",
                    "evidence_level": "semantic_region_only",
                    "source_evidence": ["vision"],
                    "rough_bbox_hint": {"x": 656, "y": 518, "w": 470, "h": 378},
                    "review_policy": {"semantic_only_requires_human_review": True},
                }
            ],
        },
    }

    tasks = build_tasks_from_actual_parser_locator_cards(actual_parser_output, max_regions=5)

    assert tasks["contract_version"] == "numbered_region_calibration_tasks_v1"
    assert tasks["prompt_profile"] == "locator_task_card_execute_calibration_v1"
    assert tasks["screenshot_path"] == "screen.png"
    region = tasks["regions"][0]
    assert region["region_no"] == 1
    assert region["item_id"] == "c4"
    assert region["label"] == "Job listing card: Software Engineer Specialist - Integration"
    assert region["role"] == "card"
    assert region["rough_bbox_hint"] == {"x": 656, "y": 518, "w": 470, "h": 378}
    assert region["evidence_level"] == "semantic_region_only"
    assert region["text_lines"] == [
        "Software Engineer Specialist - Integration",
        "AIA New Zealand",
        "Takapuna, Auckland",
    ]
    assert region["locator_task_card"]["source_item_id"] == "c4"
    assert "Text lines: Software Engineer Specialist - Integration | AIA New Zealand | Takapuna, Auckland" in region["prompt"]
    assert "Boundary definition: single white card, excluding next card below" in region["prompt"]
    assert "Clickable-area hint: safe interior around title and company text" in region["prompt"]


def test_locator_card_task_label_includes_visible_text_for_generic_repeated_modules() -> None:
    actual_parser_output = {
        "screenshot_path": "screen.png",
        "locator_task_cards": {
            "contract_version": "learn_locator_task_cards_v1",
            "cards": [
                {
                    "source_item_id": "c4",
                    "target_name": "Job listing card",
                    "target_role": "card",
                    "target_visible_text": "Job listing card",
                    "text_lines": ["Software Engineer Specialist - Integration", "AIA New Zealand"],
                    "evidence_level": "semantic_region_only",
                    "source_evidence": ["vision"],
                    "rough_bbox_hint": {"x": 656, "y": 518, "w": 470, "h": 378},
                }
            ],
        },
    }

    tasks = build_tasks_from_actual_parser_locator_cards(actual_parser_output)

    region = tasks["regions"][0]
    assert region["label"] == "Job listing card: Software Engineer Specialist - Integration"
    assert region["locator_task_card"]["target_name"] == "Job listing card"
    assert "Target name: Job listing card: Software Engineer Specialist - Integration" in region["prompt"]
    assert "Text lines: Software Engineer Specialist - Integration | AIA New Zealand" in region["prompt"]


def test_request_for_job_card_region_uses_open_detail_semantic_action() -> None:
    tasks = {"app_name": "seek", "screenshot_path": "screen.png"}
    region = {
        "region_no": 4,
        "item_id": "c4",
        "label": "Job listing card: Software Engineer Specialist - Integration",
        "role": "card",
        "rough_bbox_hint": {"x": 656, "y": 518, "w": 470, "h": 378},
        "prompt": "Locate job card",
    }
    seed = build_seeded_candidate(region)

    request = request_for_region_for_test(tasks=tasks, region=region, seed=seed)

    assert request.task == "open_detail"
    assert request.operation_context.semantic_action == "open_detail"
    assert request.dry_run is True
    assert request.metadata["numbered_region_calibration"]["execute_binding_enabled"] is False


def test_probe_runs_selected_regions_with_mocked_execute_chain(tmp_path) -> None:
    tasks = {
        "case_id": "seek_demo",
        "screenshot_path": "screen.png",
        "regions": [
            {
                "region_no": 1,
                "item_id": "search",
                "label": "Search keyword field",
                "role": "input",
                "rough_bbox_hint": {"x": 10, "y": 10, "w": 100, "h": 20},
                "prompt": "locate search",
            },
            {
                "region_no": 2,
                "item_id": "button",
                "label": "SEEK search button",
                "role": "button",
                "evidence_level": "uia_control",
                "rough_bbox_hint": {"x": 120, "y": 10, "w": 40, "h": 20},
                "prompt": "locate button",
            },
        ],
    }
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(__import__("json").dumps(tasks), encoding="utf-8")

    def fake_executor(request):
        seed = request.metadata["seeded_candidate_v1"]
        inside = seed["label"] == "SEEK search button"
        return {
            "success": True,
            "message": "Recognition plan accepted; dry run did not click",
            "error": None,
            "result": {
                "trace_path": f"trace-{seed['candidate_id']}.json",
                "recognition_plan_trace_path": f"plan-{seed['candidate_id']}.json",
                "recognition_plan_overlay": {"output_path": f"overlay-{seed['candidate_id']}.png"},
                "selected_click_point": seed["click_point"],
                "recognition_plan": {
                    "candidate_result": {
                        "summary": {
                            "seeded_candidate_used": True,
                            "seeded_candidate_selected": True,
                            "vista_point_grounding_used": True,
                            "vista_point_inside_candidate_bbox": inside,
                            "seeded_candidate_primary_point_used": not inside,
                        }
                    },
                    "narrow_search_result": {"summary": {"grounded_count": 1}},
                    "pre_click_decision": {"allowed": True, "reasons": ["pre_click_candidate_allowed"]},
                    "parse_result": {"vista_point_grounding": {"point": {"x": 1, "y": 2}}},
                    "execution_path": {"action_executed": False},
                },
            },
        }

    report = run_numbered_region_calibration_probe(
        tasks_path=tasks_path,
        out_dir=tmp_path / "out",
        region_numbers=[1, 2],
        execute_fn=fake_executor,
    )

    assert report["summary"]["attempted"] == 2
    assert report["summary"]["passed"] == 1
    assert report["summary"]["needs_human_review"] == 1
    assert report["summary"]["real_clicks"] == 0
    assert report["cases"][0]["outcome"]["status"] == "needs_human_review"
    assert report["cases"][1]["outcome"]["status"] == "passed"
    fusion = report["fused_precise_understanding"]
    assert fusion["contract_version"] == "learn_precise_understanding_fusion_v1"
    assert fusion["display_only"] is True
    assert fusion["execute_binding_enabled"] is False
    assert fusion["summary"]["attempted"] == 2
    assert fusion["summary"]["promotable_to_pathgraph_candidate_review"] == 1
    assert fusion["items"][0]["calibration_status"] == "needs_human_review"
    assert fusion["items"][0]["promotion_policy"]["promotable_to_pathgraph_candidate_review"] is False
    assert fusion["items"][1]["calibration_status"] == "passed"
    assert fusion["items"][1]["promotion_policy"]["promotable_to_pathgraph_candidate_review"] is True


def test_probe_writes_full_screen_understanding_overlay_for_all_locator_cards(tmp_path) -> None:
    from PIL import Image

    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (260, 180), "white").save(screenshot_path)
    tasks = {
        "case_id": "seek_demo",
        "screenshot_path": str(screenshot_path),
        "regions": [
            {
                "region_no": 1,
                "item_id": "search",
                "label": "Search keyword field",
                "role": "input",
                "rough_bbox_hint": {"x": 10, "y": 10, "w": 120, "h": 28},
                "prompt": "locate search",
            },
            {
                "region_no": 2,
                "item_id": "button",
                "label": "Search button",
                "role": "button",
                "rough_bbox_hint": {"x": 140, "y": 10, "w": 80, "h": 28},
                "prompt": "locate button",
            },
            {
                "region_no": 3,
                "item_id": "detail",
                "label": "Job details pane",
                "role": "other",
                "rough_bbox_hint": {"x": 20, "y": 60, "w": 200, "h": 90},
                "prompt": "locate detail",
            },
        ],
    }
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(__import__("json").dumps(tasks), encoding="utf-8")

    def fake_executor(request):
        seed = request.metadata["seeded_candidate_v1"]
        return {
            "success": True,
            "message": "dry run",
            "error": None,
            "result": {
                "selected_click_point": seed["click_point"],
                "recognition_plan": {
                    "candidate_result": {
                        "summary": {
                            "seeded_candidate_used": True,
                            "seeded_candidate_selected": True,
                            "vista_point_grounding_used": True,
                            "vista_point_inside_candidate_bbox": True,
                            "seeded_candidate_primary_point_used": False,
                        }
                    },
                    "pre_click_decision": {"allowed": True, "reasons": []},
                    "parse_result": {"vista_point_grounding": {"point": seed["click_point"]}},
                },
            },
        }

    report = run_numbered_region_calibration_probe(
        tasks_path=tasks_path,
        out_dir=tmp_path / "out",
        region_numbers=[2],
        execute_fn=fake_executor,
    )

    assert report["full_screen_understanding_summary"] == {
        "total_locator_cards": 3,
        "calibrated_cases": 1,
        "uncalibrated_locator_cards": 2,
        "display_only": True,
        "execute_binding_enabled": False,
    }
    backlog = report["calibration_backlog"]
    assert backlog["contract_version"] == "numbered_region_calibration_backlog_v1"
    assert backlog["summary"] == {
        "uncalibrated_locator_cards": 2,
        "ready_for_execute_dry_run": 1,
        "review_before_calibration": 1,
        "display_only": True,
        "execute_binding_enabled": False,
    }
    assert [item["region_no"] for item in backlog["items"]] == [1, 3]
    assert backlog["items"][0]["suggested_semantic_action"] == "fill_field"
    assert backlog["items"][0]["calibration_lane"] == "ready_for_execute_dry_run"
    assert backlog["items"][0]["ready_for_execute_dry_run"] is True
    assert backlog["items"][0]["rough_bbox_hint"] == {"x": 10, "y": 10, "w": 120, "h": 28}
    assert backlog["items"][0]["execute_binding_enabled"] is False
    assert backlog["items"][0]["artifact_is_authorization"] is False
    assert "locate search" in backlog["items"][0]["prompt"]
    assert backlog["items"][1]["calibration_lane"] == "review_before_calibration"
    assert backlog["items"][1]["ready_for_execute_dry_run"] is False
    assert backlog["items"][1]["review_reason"] == "non_actionable_or_page_structure_role"
    assert report["fused_precise_understanding"]["summary"]["total_locator_cards"] == 3
    assert report["fused_precise_understanding"]["summary"]["calibrated_cases"] == 1
    assert report["fused_precise_understanding"]["summary"]["uncalibrated_locator_cards"] == 2
    assert report["fused_precise_understanding"]["calibration_backlog"]["summary"]["uncalibrated_locator_cards"] == 2
    assert report["full_screen_understanding_overlay_path"]
    assert __import__("pathlib").Path(report["full_screen_understanding_overlay_path"]).exists()


def test_probe_can_enrich_prompts_before_execute_chain(tmp_path) -> None:
    tasks = {
        "case_id": "seek_demo",
        "screenshot_path": "screen.png",
        "regions": [
            {
                "region_no": 1,
                "item_id": "uia_control_1",
                "label": "Search keyword field",
                "role": "input",
                "evidence_level": "uia_control",
                "rough_bbox_hint": {"x": 10, "y": 10, "w": 100, "h": 20},
                "prompt": "old short prompt",
            }
        ],
    }
    parser_output = {
        "screen_inventory": [
            {
                "item_id": "uia_control_1",
                "label": "Search keyword field",
                "role": "input",
                "text": "Search keyword field",
                "evidence_level": "uia_control",
                "metadata": {"control_type": "Edit", "patterns": ["Value"]},
            }
        ],
        "observe_bundle": {
            "sources": {
                "vision": {
                    "regions": [
                        {
                            "region_id": "uia_control_1",
                            "description": "white rounded keyword input with search icon",
                        }
                    ]
                }
            }
        },
    }
    tasks_path = tmp_path / "tasks.json"
    parser_path = tmp_path / "parser.json"
    enriched_path = tmp_path / "out" / "enriched.json"
    tasks_path.write_text(__import__("json").dumps(tasks), encoding="utf-8")
    parser_path.write_text(__import__("json").dumps(parser_output), encoding="utf-8")
    seen_goals: list[str] = []

    def fake_executor(request):
        seen_goals.append(request.goal)
        seed = request.metadata["seeded_candidate_v1"]
        return {
            "success": True,
            "message": "dry run",
            "error": None,
            "result": {
                "selected_click_point": seed["click_point"],
                "recognition_plan": {
                    "candidate_result": {
                        "summary": {
                            "seeded_candidate_used": True,
                            "seeded_candidate_selected": True,
                            "vista_point_grounding_used": True,
                            "vista_point_inside_candidate_bbox": True,
                            "seeded_candidate_primary_point_used": False,
                        }
                    },
                    "pre_click_decision": {"allowed": True, "reasons": []},
                    "parse_result": {"vista_point_grounding": {"point": seed["click_point"]}},
                },
            },
        }

    report = run_numbered_region_calibration_probe(
        tasks_path=tasks_path,
        out_dir=tmp_path / "out",
        region_numbers=[1],
        execute_fn=fake_executor,
        parser_output_path=parser_path,
        enrich_prompts=True,
        write_enriched_tasks=enriched_path,
    )

    assert report["prompt_profile"] == "numbered_region_detailed_locator_v1"
    assert report["enriched_tasks_path"] == str(enriched_path.resolve())
    assert "old short prompt" not in seen_goals[0]
    assert "Target visible text: Search keyword field" in seen_goals[0]
