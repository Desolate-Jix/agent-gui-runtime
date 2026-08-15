from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import scripts.run_learn_recognition_actual_parser_smoke as smoke_module
from scripts.run_learn_recognition_actual_parser_smoke import replay_recorded_provider_raw_text, run_actual_parser_smoke
from app.vision.schemas import VisionAnalyzeResponse


def test_actual_parser_smoke_with_fake_model_writes_inventory_and_draft(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot_path)

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        assert image_path == screenshot_path
        assert model_config["model_name"] == "fake-qwen"
        return {
            "provider": "fake-qwen",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 400, "height": 300},
            "screen_summary": "Search page",
            "state_guess": "search homepage",
            "interface_classification": {
                "category": "documentation_portal",
                "confidence": 0.91,
                "reason": "structured search and article surface",
                "structure_signals": {
                    "media_cards": False,
                    "article_or_document_sections": True,
                    "settings_controls": False,
                    "people_or_conversation_rows": False,
                    "file_or_folder_rows": False,
                    "form_fields": False,
                },
            },
            "regions": [
                {
                    "region_id": "search_area",
                    "label": "Search input",
                    "role": "input",
                    "diagonal": {"x1": 40, "y1": 50, "x2": 220, "y2": 90},
                    "description": "search field",
                    "confidence": 0.8,
                }
            ],
            "targets": [],
            "observers": [],
            "notes": [],
            "raw_text": "{\"regions\":[]}",
        }

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["actual_model_call_in_this_run"] is True
    assert report["metrics"]["actual_parser_call"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["layout_cleanup"]["contract_version"] == "learn_layout_cleanup_report_v1"
    assert report["layout_cleanup"]["input_count"] == 1
    assert report["layout_cleanup"]["output_count"] == 1
    assert report["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert report["layout_graph"]["node_count"] == 1
    assert report["counts"]["raw_screen_inventory_count"] == 1
    assert report["counts"]["layout_cleanup_suppressed_count"] == 0
    assert report["counts"]["layout_cleanup_suppression_reason_counts"] == {}
    assert report["layout_cleanup"]["suppression_reason_counts"] == {}
    assert report["grounding_eligibility_gate"]["evaluation_scope"] == "learn_mode_grounding_eligibility_gate"
    assert report["grounding_eligibility_gate"]["grounding_eligibility"] == {"attempted": 1, "eligible": 0, "blocked": 1}
    assert report["grounding_eligibility_gate"]["non_actionable_leaked_to_grounding"]["leaked_count"] == 0
    assert report["grounding_eligibility"]["grounding_eligible"] == 0
    assert report["grounding_eligibility"]["review_only"] == 1
    assert report["support_eligibility_summary"]["total_candidates"] == 1
    assert report["support_eligibility_summary"]["by_source_type"] == {"qwen_vlm": 1}
    assert report["support_eligibility_summary"]["by_evidence_kind"] == {"semantic_region": 1}
    assert report["support_eligibility_summary"]["grounding_eligible_candidates"] == 0
    assert report["support_eligibility_summary"]["semantic_or_ocr_leaked_to_grounding"] == 0
    assert report["parser_actual_call_usefulness"] == {
        "parser_inventory_generated": True,
        "parser_useful_for_review": True,
        "parser_useful_for_grounding": False,
        "semantic_only_regions": 1,
        "grounding_eligible_regions": 0,
        "accepted_for_grounding": 0,
        "blocked_from_grounding_reason": "semantic_region_only_without_interactable_evidence",
        "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
    }
    assert report["counts"]["grounding_eligible_count"] == 0
    assert report["counts"]["review_only_count"] == 1
    assert report["counts"]["same_screenshot_interactable_support_count"] == 0
    assert report["counts"]["semantic_or_ocr_leaked_to_grounding"] == 0
    assert report["safety"]["artifact_is_authorization"] is False
    assert report["safety"]["execute_binding_enabled"] is False

    output_path = Path(report["actual_parser_output_path"])
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["source_type"] == "actual_parser_call"
    assert payload["observe_bundle"]["sources"]["vision"]["interface_classification"]["category"] == "documentation_portal"
    assert payload["observe_bundle"]["sources"]["vision"]["regions"][0]["label"] == "Search input"
    assert payload["raw_screen_inventory"][0]["label"] == "Search input"
    assert payload["layout_cleanup"]["input_count"] == 1
    assert payload["layout_cleanup"]["suppression_reason_counts"] == {}
    assert payload["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert payload["layout_graph"]["node_count"] == 1
    assert payload["locator_task_cards"]["contract_version"] == "learn_locator_task_cards_v1"
    assert payload["locator_task_cards"]["cards"][0]["target_name"] == "Search input"
    assert payload["grounding_eligibility_gate"]["not_accuracy"] is True
    assert payload["screen_inventory"][0]["contract_version"] == "screen_inventory_item_v2"
    assert payload["screen_inventory"][0]["artifact_is_authorization"] is False
    assert payload["grounding_eligibility"]["blocked_reasons"]["semantic_region_only_without_interactable_evidence"] == 1
    assert payload["support_eligibility_summary"]["total_candidates"] == 1
    assert payload["support_eligibility_summary"]["semantic_or_ocr_leakage_safe"] is True
    assert payload["parser_actual_call_usefulness"]["parser_useful_for_review"] is True
    assert payload["parser_actual_call_usefulness"]["parser_useful_for_grounding"] is False
    assert payload["parser_actual_call_usefulness"]["semantic_only_regions"] == 1
    assert payload["learning_draft"]["contract_version"] == "learning_template_draft_v1"
    assert payload["learning_draft"]["page_details"]["locator_task_cards"]["cards"][0]["source_item_id"] == "search_area"
    assert payload["learning_draft"]["execute_binding_enabled"] is False


def test_actual_parser_default_model_caller_enables_learn_coordinate_recovery(tmp_path: Path, monkeypatch) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot_path)
    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, *, endpoint: str | None, model_name: str, timeout_seconds: float) -> None:
            captured["endpoint"] = endpoint
            captured["model_name"] = model_name
            captured["timeout_seconds"] = timeout_seconds

        def analyze(self, request):
            captured["metadata"] = request.metadata
            return VisionAnalyzeResponse(
                provider="fake-provider",
                screen_summary="empty",
                state_guess=request.state_hint,
                regions=[],
                raw_text="{}",
            )

    monkeypatch.setattr(smoke_module, "LocalVisionProvider", FakeProvider)

    run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:13240/v1/chat/completions",
        model_name="fake-qwen",
        timeout_seconds=3,
    )

    assert captured["endpoint"] == "http://127.0.0.1:13240/v1/chat/completions"
    assert captured["model_name"] == "fake-qwen"
    assert captured["timeout_seconds"] == 3
    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["coordinate_recovery"] == {
        "implicit_normalized_1000": True,
        "scope": "learn_recognition_actual_parser",
    }


def test_recorded_provider_replay_recovers_normalized_1000_and_remains_non_actual_call(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "python_home.png"
    Image.new("RGB", (2521, 1300), "white").save(screenshot_path)
    raw_text = json.dumps(
        {
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 1280, "height": 660},
            "screen_summary": "Python homepage",
            "state_guess": "home",
            "regions": [
                {
                    "region_id": "c1",
                    "label": "Search input",
                    "role": "input",
                    "diagonal": {"x1": 568, "y1": 68, "x2": 666, "y2": 88},
                    "confidence": 0.98,
                }
            ],
            "targets": [],
            "observers": [],
            "notes": [],
        },
        ensure_ascii=False,
    )

    report = replay_recorded_provider_raw_text(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        raw_text=raw_text,
        model_name="recorded-qwen",
        supplemental_sources={
            "calibrated_targets": {
                "targets": [
                    {
                        "candidate_id": "search_support",
                        "label": "Search input",
                        "role": "input",
                        "bbox": {"x": 1454, "y": 90, "w": 222, "h": 36},
                        "click_point": {"x": 1565, "y": 108},
                        "coordinate_validation": {
                            "status": "valid",
                            "bbox_present": True,
                            "click_point_present": True,
                            "bbox_inside_image": True,
                            "click_point_inside_image": True,
                            "click_point_inside_bbox": True,
                        },
                    }
                ]
            }
        },
    )

    assert report["status"] == "passed"
    assert report["source_type"] == "recorded_provider_replay"
    assert report["actual_model_call_in_this_run"] is False
    assert report["metrics"]["actual_parser_call"] == {"passed": 0, "attempted": 0, "rate": "not_covered"}
    assert report["counts"]["layout_cleanup_suppression_reason_counts"] == {"cross_evidence_support_duplicate": 1}
    assert report["counts"]["accepted_for_grounding_count"] >= 1
    assert report["counts"]["grounding_validation_count"] >= 1
    assert report["counts"]["learning_draft_region_count"] >= 1
    assert report["safety"]["execute_binding_enabled"] is False

    payload = json.loads(Path(report["actual_parser_output_path"]).read_text(encoding="utf-8"))
    vision_raw_response = payload["observe_bundle"]["sources"]["vision"]["raw_response"]
    model_io = vision_raw_response["attempts"][0]["model_io"]
    assert model_io["parsed_model_json"]["regions"][0]["diagonal"] == {"x1": 568, "y1": 68, "x2": 666, "y2": 88}
    assert model_io["runtime_normalized_json"]["regions"][0]["diagonal"] == {"x1": 1432, "y1": 89, "x2": 1678, "y2": 114}
    assert model_io["coordinate_recovery"]["applied"] is True
    assert payload["layout_cleanup"]["suppression_reason_counts"] == {"cross_evidence_support_duplicate": 1}
    assert any(item["evidence_level"] == "cross_evidence_grounded" for item in payload["screen_inventory"])
    assert payload["learning_draft"]["execute_binding_enabled"] is False


def test_actual_parser_smoke_can_fuse_supplemental_calibrated_targets(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot_path)

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        return {
            "provider": "fake-qwen",
            "contract_version": "vision_regions_v1",
            "screen_summary": "Search page",
            "state_guess": "homepage",
            "regions": [
                {
                    "region_id": "semantic_search",
                    "label": "Search button",
                    "role": "button",
                    "diagonal": {"x1": 40, "y1": 50, "x2": 120, "y2": 90},
                    "confidence": 0.8,
                }
            ],
        }

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
        model_caller=fake_model_caller,
        supplemental_sources={
            "calibrated_targets": {
                "source_trace_path": "logs/traces/vision/deep.json",
                "targets": [
                    {
                        "candidate_id": "calibrated_search",
                        "label": "Search button",
                        "role": "button",
                        "bbox": {"x": 42, "y": 52, "w": 76, "h": 36},
                        "click_point": {"x": 80, "y": 70},
                        "coordinate_validation": {
                            "status": "valid",
                            "bbox_present": True,
                            "click_point_present": True,
                            "bbox_inside_image": True,
                            "click_point_inside_image": True,
                            "click_point_inside_bbox": True,
                        },
                    }
                ],
            }
        },
    )

    assert report["status"] == "passed"
    assert report["counts"]["layout_cleanup_suppression_reason_counts"] == {"cross_evidence_support_duplicate": 1}
    assert report["counts"]["accepted_for_grounding_count"] >= 1
    assert report["counts"]["grounding_eligible_count"] >= 1
    assert report["parser_actual_call_usefulness"]["parser_inventory_generated"] is True
    assert report["parser_actual_call_usefulness"]["parser_useful_for_review"] is True
    assert report["parser_actual_call_usefulness"]["parser_useful_for_grounding"] is True
    assert report["parser_actual_call_usefulness"]["grounding_eligible_regions"] >= 1
    assert report["parser_actual_call_usefulness"]["accepted_for_grounding"] >= 1
    assert report["parser_actual_call_usefulness"]["blocked_from_grounding_reason"] == ""
    assert report["grounding_eligibility_gate"]["grounding_eligibility"]["eligible"] >= 1
    assert report["grounding_eligibility_gate"]["grounding_eligible_breakdown"]["human_calibrated"] >= 1
    assert report["support_eligibility_summary"]["interactable_evidence_candidates"] >= 1
    assert report["support_eligibility_summary"]["same_screenshot_interactable_support"] >= 1
    assert report["support_eligibility_summary"]["semantic_or_ocr_leaked_to_grounding"] == 0
    assert report["metrics"]["actionable_classification"]["attempted"] >= 1
    assert report["counts"]["grounding_validation_count"] >= 1
    assert report["counts"]["learning_draft_region_count"] >= 1
    assert report["counts"]["learning_draft_action_count"] >= 1
    output = json.loads(Path(report["actual_parser_output_path"]).read_text(encoding="utf-8"))
    accepted = output["classification"]["accepted_for_grounding"]
    assert any(item["label"] == "Search button" for item in accepted)
    assert output["observe_bundle"]["sources"]["calibrated_targets"]["targets"][0]["candidate_id"] == "calibrated_search"
    assert output["layout_cleanup"]["suppression_reason_counts"] == {"cross_evidence_support_duplicate": 1}
    assert output["learning_draft"]["execute_binding_enabled"] is False
    assert output["learning_draft"]["artifact_is_authorization"] is False
    assert output["learning_draft"]["regions"]
    assert output["learning_draft"]["action_templates"]
    assert output["grounding_validations"][0]["status"] == "valid_candidate"
    assert output["grounding_validations"][0]["grounding_debug"]["adapter"] == "calibrated_target_replay"


def test_actual_parser_smoke_keeps_misaligned_vision_review_only_but_accepts_uia_support(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (800, 500), "white").save(screenshot_path)

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        return {
            "provider": "fake-qwen",
            "contract_version": "vision_regions_v1",
            "screen_summary": "SEEK results",
            "state_guess": "results_page",
            "regions": [
                {
                    "region_id": "semantic_search_wrong_box",
                    "label": "Search keyword field",
                    "role": "input",
                    "diagonal": {"x1": 50, "y1": 300, "x2": 250, "y2": 340},
                    "confidence": 0.8,
                }
            ],
        }

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
        model_caller=fake_model_caller,
        supplemental_sources={
            "uia": {
                "controls": [
                    {
                        "name": "Search keyword field",
                        "control_type": "Edit",
                        "bbox": {"x": 300, "y": 100, "w": 240, "h": 40},
                        "patterns": ["Value"],
                    }
                ]
            }
        },
    )

    assert report["status"] == "passed"
    assert report["counts"]["screen_inventory_count"] == 2
    assert report["counts"]["accepted_for_grounding_count"] == 1
    assert report["counts"]["rejected_non_actionable_count"] == 1
    assert report["parser_actual_call_usefulness"]["parser_useful_for_grounding"] is True
    output = json.loads(Path(report["actual_parser_output_path"]).read_text(encoding="utf-8"))
    accepted = output["classification"]["accepted_for_grounding"]
    rejected = output["classification"]["rejected_non_actionable"]
    assert accepted[0]["source_evidence"] == ["uia"]
    assert accepted[0]["grounding_eligible"] is True
    assert rejected[0]["source_evidence"] == ["vision"]
    assert rejected[0]["grounding_block_reason"] == "semantic_region_only_without_interactable_evidence"
    assert report["support_eligibility_summary"]["total_candidates"] == 2
    assert report["support_eligibility_summary"]["by_source_type"] == {"qwen_vlm": 1, "uia": 1}
    assert report["support_eligibility_summary"]["same_screenshot_interactable_support"] == 1
    assert report["support_eligibility_summary"]["semantic_or_ocr_leaked_to_grounding"] == 0


def test_actual_parser_smoke_blocks_without_endpoint_and_does_not_count_denominator(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(screenshot_path)

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint=None,
        model_name="missing-endpoint",
    )

    assert report["status"] == "blocked"
    assert report["actual_model_call_in_this_run"] is False
    assert report["metrics"]["actual_parser_call"]["attempted"] == 0
    assert report["metrics"]["actual_parser_call"]["rate"] == "not_covered"
    assert report["safety"]["real_clicks_performed"] == 0


def test_actual_parser_smoke_resolves_learn_only_qwen_profile(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 300), "white").save(screenshot_path)

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        assert image_path == screenshot_path
        assert model_config["endpoint"] == "http://127.0.0.1:13240/v1/chat/completions"
        assert model_config["model_name"] == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
        assert model_config["model_profile"]["profile_id"] == "learn_mode_qwen3_vl_8b"
        return {
            "provider": "fake-qwen8b",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 400, "height": 300},
            "screen_summary": "Home page",
            "state_guess": "homepage",
            "regions": [
                {
                    "region_id": "download",
                    "label": "Downloads",
                    "role": "navigation",
                    "diagonal": {"x1": 40, "y1": 50, "x2": 120, "y2": 80},
                    "confidence": 0.8,
                }
            ],
        }

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint=None,
        model_name=None,
        model_profile_id="learn_mode_qwen3_vl_8b",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["actual_model_call_in_this_run"] is True
    assert report["model_profile"]["profile_id"] == "learn_mode_qwen3_vl_8b"
    assert report["model_profile"]["download_status"] == "available_local_baseline"
    assert report["model_config"]["model_profile_id"] == "learn_mode_qwen3_vl_8b"
    output = json.loads(Path(report["actual_parser_output_path"]).read_text(encoding="utf-8"))
    assert output["model_profile"]["profile_id"] == "learn_mode_qwen3_vl_8b"
    assert output["observe_bundle"]["model_config"]["model_profile_id"] == "learn_mode_qwen3_vl_8b"


def test_actual_parser_smoke_blocks_metadata_only_profile_before_model_call(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(screenshot_path)
    profile_path = tmp_path / "metadata_only_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "metadata_only_profile",
                "mode_scope": "learn_only",
                "provider_mode": "metadata_only",
                "model_family": "test",
                "download_status": "metadata_only",
                "launchable": False,
                "endpoint": "http://127.0.0.1:65530/v1/chat/completions",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "final_submit_forbidden": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        raise AssertionError("metadata-only profile must be blocked before parser model call")

    report = run_actual_parser_smoke(
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:65530/v1/chat/completions",
        model_name=None,
        model_profile_id=str(profile_path),
        model_caller=fake_model_caller,
    )

    assert report["status"] == "blocked"
    assert report["actual_model_call_in_this_run"] is False
    assert report["blocker"]["failure_category"] == "model_profile_not_downloaded"
    assert report["model_profile"]["profile_id"] == "metadata_only_profile"
    assert report["model_profile_readiness"]["contract_version"] == "learn_actual_parser_model_profile_readiness_v1"
    assert report["model_profile_readiness"]["download_status"] == "metadata_only"
    assert report["model_profile_readiness"]["endpoint_present"] is True
    assert report["metrics"]["actual_parser_call"]["attempted"] == 0
