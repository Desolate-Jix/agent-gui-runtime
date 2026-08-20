from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.learn.model_trial import (
    _learning_provider_from_parameters,
    build_learning_model_trial,
    score_learning_template_draft,
)
from app.main import app


def _image(path: Path) -> Path:
    Image.new("RGB", (240, 160), color=(255, 255, 255)).save(path)
    return path


def _good_draft() -> dict:
    return {
        "contract_version": "learning_template_draft_v1",
        "image_size": {"width": 240, "height": 160},
        "learning_source": "observe_model",
        "screen_summary": "search results",
        "state_guess": "results list",
        "workflow_draft": {
            "states": [{"state_id": "results", "label": "Results"}],
            "transitions": [{"transition_id": "open_detail", "action_template_id": "open_card"}],
            "action_templates": [
                {
                    "action_template_id": "open_card",
                    "label": "Open result",
                    "semantic_action": "open_detail",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "detail opens",
                },
                {
                    "action_template_id": "submit",
                    "label": "Submit application",
                    "semantic_action": "final_submit",
                    "risk_level": "high",
                    "requires_gate": True,
                    "hard_block": True,
                    "final_submit_guard_required": True,
                    "fast_lane_allowed": False,
                },
            ],
            "path_patterns": [{"pattern_id": "list_detail"}],
        },
        "interface_draft": {
            "regions": [{"region_id": "results_list", "role": "list"}],
            "visual_assets": [{"asset_id": "card", "semantic_action": "open_detail"}],
            "dynamic_areas": [],
            "danger_zones": [
                {
                    "zone_id": "submit_zone",
                    "label": "Submit application",
                    "semantic_action": "final_submit",
                    "hard_block": True,
                    "final_submit_guard_required": True,
                    "fast_lane_allowed": False,
                }
            ],
        },
        "agent_decision_points": [{"decision_id": "review_before_submit"}],
        "operation_skills": ["observe_screen", "locate_element"],
        "gate_contracts": ["final_submit_blocking"],
        "safety": {
            "observation_only": True,
            "promotion_allowed": False,
            "final_submit_blocked": True,
            "real_clicks_performed": 0,
        },
        "notes": [],
    }


def test_learning_template_score_passes_directly_usable_raw_draft() -> None:
    report = score_learning_template_draft(
        _good_draft(),
        {
            "expected_actions": [{"label": "Submit application", "semantic_action": "final_submit"}],
            "direct_use_accuracy_threshold": 0.9,
        },
    )

    assert report["overall_score"]["passed"] is True
    assert report["overall_score"]["score_ratio"] >= 0.9
    assert not [item for item in report["checks"] if item["severity"] == "hard_error" and not item["passed"]]


def test_learning_template_expected_action_matches_semantic_without_label_overfit() -> None:
    draft = _good_draft()
    draft["workflow_draft"]["action_templates"][0]["label"] = "type_job_query"
    draft["workflow_draft"]["action_templates"][0]["semantic_action"] = "type_text"

    report = score_learning_template_draft(
        draft,
        {
            "expected_actions": [{"label": "enter search query", "semantic_action": "type_text"}],
            "direct_use_accuracy_threshold": 0.9,
        },
    )

    assert report["overall_score"]["passed"] is True
    assert report["section_scores"]["actions"] == 1.0


def test_learning_template_score_uses_private_reference_template_similarity() -> None:
    reference = _good_draft()
    matching = _good_draft()
    mismatched = _good_draft()
    mismatched["workflow_draft"]["states"] = [{"state_id": "settings", "label": "Settings", "page_type": "settings"}]
    mismatched["workflow_draft"]["action_templates"] = [
        {
            "action_template_id": "toggle_dark_mode",
            "label": "Toggle dark mode",
            "semantic_action": "toggle_setting",
            "risk_level": "low",
            "requires_gate": True,
            "expected_effect": "toggle setting",
        }
    ]
    mismatched["interface_draft"]["regions"] = [{"region_id": "settings_panel", "role": "panel"}]

    target = {
        "reference_template": reference,
        "direct_use_accuracy_threshold": 0.9,
    }
    good_report = score_learning_template_draft(matching, target)
    bad_report = score_learning_template_draft(mismatched, target)

    assert good_report["overall_score"]["passed"] is True
    assert good_report["template_similarity"]["score_ratio"] == 1.0
    assert bad_report["overall_score"]["passed"] is False
    assert bad_report["template_similarity"]["score_ratio"] < 0.7


def test_learning_template_score_names_alignment_not_accuracy_and_records_human_adjudication() -> None:
    reference = _good_draft()
    report = score_learning_template_draft(
        _good_draft(),
        {
            "reference_template": reference,
            "direct_use_accuracy_threshold": 0.9,
            "human_adjudication": {
                "status": "suspected_scorer_false_negative",
                "scope": "search_input_subtask_only",
                "rationale": "Required search action and search field are present.",
            },
        },
    )

    assert report["draft_reference_alignment_score"]["score_ratio"] == report["overall_score"]["score_ratio"]
    assert report["template_similarity_score"]["score_ratio"] == report["template_similarity"]["score_ratio"]
    assert report["overall_score"]["draft_reference_alignment_threshold"] == 0.9
    assert "direct_use_accuracy_threshold" not in report["overall_score"]
    assert report["overall_score"]["legacy_direct_use_accuracy_threshold"] == 0.9
    assert report["human_adjudication"]["scope"] == "search_input_subtask_only"
    assert "model_accuracy" not in report["overall_score"]
    assert "click_success_rate" not in report["overall_score"]
    assert "e2e_success_rate" not in report["overall_score"]


def test_learning_template_similarity_normalizes_equivalent_state_and_region_roles() -> None:
    reference = {
        **_good_draft(),
        "workflow_draft": {
            **_good_draft()["workflow_draft"],
            "states": [{"state_id": "search_input", "label": "search input surface", "page_type": "job_search"}],
            "action_templates": [
                {
                    "action_template_id": "type_job_query",
                    "label": "type job query",
                    "semantic_action": "type_text",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "populate search field with job query",
                }
            ],
        },
        "interface_draft": {
            **_good_draft()["interface_draft"],
            "regions": [{"region_id": "search_input", "label": "search input", "role": "search_field"}],
        },
    }
    draft = {
        **reference,
        "workflow_draft": {
            **reference["workflow_draft"],
            "states": [{"state_id": "s1", "label": "job_search_initial", "page_type": "search_page"}],
            "action_templates": [
                {
                    "action_template_id": "a1",
                    "label": "type_job_query",
                    "semantic_action": "type_text",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "populate search field with job query",
                }
            ],
        },
        "interface_draft": {
            **reference["interface_draft"],
            "regions": [{"region_id": "r1", "label": "search_input_field", "role": "text_input"}],
        },
    }

    report = score_learning_template_draft(
        draft,
        {
            "reference_template": reference,
            "direct_use_accuracy_threshold": 0.8,
        },
    )

    assert report["template_similarity"]["subscores"]["action_templates"] == 1.0
    assert report["template_similarity"]["subscores"]["safety"] == 1.0
    assert report["template_similarity"]["subscores"]["states"] >= 0.6
    assert report["template_similarity"]["subscores"]["regions"] >= 0.6
    assert report["template_similarity"]["score_ratio"] >= 0.8


def test_learning_template_similarity_scores_homepage_search_as_transferable_template() -> None:
    reference = {
        **_good_draft(),
        "workflow_draft": {
            **_good_draft()["workflow_draft"],
            "states": [{"state_id": "home_search", "label": "home page search surface", "page_type": "search_page"}],
            "action_templates": [
                {
                    "action_template_id": "type_search_query",
                    "label": "type search query",
                    "semantic_action": "type_text",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "populate search field with query text",
                }
            ],
        },
        "interface_draft": {
            **_good_draft()["interface_draft"],
            "regions": [{"region_id": "site_search_input", "label": "search input", "role": "search_field"}],
        },
    }
    draft = {
        **reference,
        "screen_summary": "Python.org homepage with navigation menu, search bar, downloads, documentation, and community resources.",
        "state_guess": "homepage",
        "workflow_draft": {
            **reference["workflow_draft"],
            "states": [{"state_id": "s1", "label": "Python.org Home", "page_type": "homepage"}],
            "action_templates": [
                {
                    "action_template_id": "a1",
                    "label": "Search for Python content",
                    "semantic_action": "type_text",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "Search query entered into the search bar.",
                },
                {
                    "action_template_id": "a2",
                    "label": "Navigate to Downloads",
                    "semantic_action": "open_detail",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "Opens the Downloads section of the site.",
                },
            ],
        },
        "interface_draft": {
            **reference["interface_draft"],
            "regions": [
                {"region_id": "r1", "label": "Search Input", "role": "text_input"},
                {"region_id": "r2", "label": "Downloads Section", "role": "navigation_link"},
            ],
        },
    }

    report = score_learning_template_draft(
        draft,
        {
            "reference_template": reference,
            "direct_use_accuracy_threshold": 0.9,
        },
    )

    assert report["template_similarity"]["subscores"]["states"] >= 0.9
    assert report["template_similarity"]["subscores"]["action_templates"] >= 0.9
    assert report["template_similarity"]["subscores"]["regions"] >= 0.9
    assert report["template_similarity"]["score_ratio"] >= 0.9


def test_learning_template_similarity_does_not_normalize_email_input_to_search_field() -> None:
    reference = {
        **_good_draft(),
        "interface_draft": {
            **_good_draft()["interface_draft"],
            "regions": [{"region_id": "search_input", "label": "search input", "role": "search_field"}],
        },
    }
    draft = {
        **reference,
        "interface_draft": {
            **reference["interface_draft"],
            "regions": [{"region_id": "email", "label": "email input", "role": "text_input"}],
        },
    }

    report = score_learning_template_draft(
        draft,
        {
            "reference_template": reference,
            "direct_use_accuracy_threshold": 0.9,
        },
    )

    assert report["template_similarity"]["subscores"]["regions"] < 0.5


def test_learning_model_trial_retries_parameters_until_score_above_90(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "screen.png")
    seen_modes: list[str] = []

    def fake_model(request: dict) -> dict:
        mode = request["learning_parameters"]["prompt_detail_mode"]
        seen_modes.append(mode)
        if mode == "compact_contract":
            return {
                "status": "success",
                "model_json": {
                    "contract_version": "learning_template_draft_v1",
                    "image_size": {"width": 240, "height": 160},
                    "learning_source": "observe_model",
                    "screen_summary": "partial",
                    "state_guess": "partial",
                    "workflow_draft": {"states": []},
                    "interface_draft": {"regions": []},
                    "safety": {"promotion_allowed": False},
                },
            }
        return {"status": "success", "model_json": _good_draft()}

    result = build_learning_model_trial(
        image_path=image_path,
        max_attempts=3,
        target_contract={"expected_actions": [{"label": "Open result", "semantic_action": "open_detail"}]},
        model_client=fake_model,
    )

    assert result["status"] == "passed"
    assert result["best_score_ratio"] >= 0.9
    assert result["best_attempt_index"] == 1
    assert seen_modes == ["compact_contract", "enumerate_sections_then_json"]
    assert result["attempts"][0]["score_report"]["parameter_feedback"]
    assert result["safety"]["artifact_posthoc_optimization_allowed"] is False


def test_learning_model_trial_records_model_error_as_scored_attempt(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "timeout.png")

    def failing_model(_request: dict) -> dict:
        raise RuntimeError("model request timed out")

    result = build_learning_model_trial(image_path=image_path, max_attempts=1, model_client=failing_model)

    assert result["status"] == "needs_more_learning"
    assert result["attempt_count"] == 1
    assert result["attempts"][0]["result_kind"] == "model_error_no_draft"
    assert result["attempts"][0]["quality_score_applicable"] is False
    assert result["attempts"][0]["model_run"]["status"] == "model_error"
    assert "model request timed out" in result["attempts"][0]["model_run"]["error"]
    assert result["attempts"][0]["score_report"]["overall_score"]["passed"] is False
    assert result["attempts"][0]["score_report"]["parameter_feedback"]


def test_learning_model_trial_feedback_can_switch_to_fast_profile(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "profile-switch.png")
    seen_profiles: list[str] = []

    def fake_model(request: dict) -> dict:
        profile_id = request["learning_parameters"]["learning_model_profile_id"]
        seen_profiles.append(profile_id)
        if profile_id == "qwen3_vl_8b_q4_k_m":
            raise RuntimeError("timed out")
        return {"status": "success", "model_json": _good_draft()}

    result = build_learning_model_trial(
        image_path=image_path,
        max_attempts=2,
        target_contract={"expected_actions": [{"label": "Open result", "semantic_action": "open_detail"}]},
        learning_parameter_overrides={"allow_fast_profile_fallback": True},
        model_client=fake_model,
    )

    assert result["status"] == "passed"
    assert result["best_attempt_index"] == 1
    assert result["best_score_ratio"] >= 0.9
    assert seen_profiles == ["qwen3_vl_8b_q4_k_m", "qwen3_vl_4b_q4_k_m"]
    feedback = result["attempts"][0]["score_report"]["parameter_feedback"]
    assert any(item["target"] == "learning_model_profile_id" for item in feedback)


def test_learning_model_trial_timeout_keeps_quality_profile_by_default(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "no-profile-switch.png")
    seen_profiles: list[str] = []
    seen_modes: list[str] = []

    def fake_model(request: dict) -> dict:
        seen_profiles.append(request["learning_parameters"]["learning_model_profile_id"])
        seen_modes.append(request["learning_parameters"]["prompt_detail_mode"])
        raise RuntimeError("timed out")

    result = build_learning_model_trial(
        image_path=image_path,
        max_attempts=2,
        target_contract={"expected_actions": [{"label": "Open result", "semantic_action": "open_detail"}]},
        model_client=fake_model,
    )

    assert result["status"] == "needs_more_learning"
    assert seen_profiles == ["qwen3_vl_8b_q4_k_m", "qwen3_vl_8b_q4_k_m"]
    assert seen_modes == ["compact_contract", "compact_contract"]
    feedback = result["attempts"][0]["score_report"]["parameter_feedback"]
    assert not any(item["target"] == "learning_model_profile_id" for item in feedback)
    assert any(item["target"] == "learning_image_max_edge" for item in feedback)
    assert not any(item["target"] == "prompt_detail_mode" for item in feedback)
    assert result["attempts"][0]["quality_score_percent"] is None


def test_learning_model_trial_optimizes_quality_only_after_scored_draft(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "quality-after-draft.png")
    seen_modes: list[str] = []

    def fake_model(request: dict) -> dict:
        mode = request["learning_parameters"]["prompt_detail_mode"]
        seen_modes.append(mode)
        if len(seen_modes) == 1:
            raise RuntimeError("timed out")
        if len(seen_modes) == 2:
            return {
                "status": "success",
                "model_json": {
                    "contract_version": "learning_template_draft_v1",
                    "image_size": {"width": 240, "height": 160},
                    "learning_source": "observe_model",
                    "screen_summary": "partial",
                    "state_guess": "partial",
                    "workflow_draft": {"states": []},
                    "interface_draft": {"regions": []},
                    "safety": {"promotion_allowed": False},
                },
            }
        return {"status": "success", "model_json": _good_draft()}

    result = build_learning_model_trial(
        image_path=image_path,
        max_attempts=3,
        target_contract={"expected_actions": [{"label": "Open result", "semantic_action": "open_detail"}]},
        learning_parameter_overrides={"timeout_seconds": 1},
        model_client=fake_model,
    )

    assert result["status"] == "passed"
    assert seen_modes == ["compact_contract", "compact_contract", "enumerate_sections_then_json"]
    assert result["attempts"][0]["result_kind"] == "model_error_no_draft"
    assert result["attempts"][0]["quality_score_percent"] is None
    assert result["attempts"][1]["quality_score_percent"] is not None


def test_learning_model_trial_profile_id_selects_model_endpoint() -> None:
    provider = _learning_provider_from_parameters(
        {
            "learning_model_profile_id": "qwen3_vl_4b_q4_k_m",
            "timeout_seconds": 7,
        }
    )

    assert provider.endpoint == "http://127.0.0.1:13241/v1/chat/completions"
    assert provider.model_name == "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
    assert provider.timeout_seconds == 7.0


def test_learning_model_trial_strict_blind_hides_answer_context(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "blind.png")
    captured_requests: list[dict] = []

    def fake_model(request: dict) -> dict:
        captured_requests.append(request)
        return {"status": "success", "model_json": _good_draft()}

    result = build_learning_model_trial(
        image_path=image_path,
        app_name="seek",
        state_hint="search input crop",
        goal="find seek search action",
        max_attempts=1,
        target_contract={
            "expected_actions": [{"label": "Open result", "semantic_action": "open_detail"}],
            "expected_visible_text": ["search results"],
        },
        observation_evidence={"old_asset_id": "learned_seek_template"},
        model_client=fake_model,
    )

    assert result["status"] == "passed"
    assert result["validation_mode"] == "strict_blind"
    request = captured_requests[0]
    assert request["app_name"] == "unknown_app"
    assert request["state_hint"] == ""
    assert request["goal"] == "learn a reusable UI workflow template from this screenshot"
    context = request["learning_trial_context"]
    assert context["prompt_context_hidden"] is True
    assert context["observation_evidence"] == {}
    assert "expected_actions" not in context["target_contract"]
    assert "expected_visible_text" not in context["target_contract"]
    assert "reference_template" not in context["target_contract"]


def test_learning_model_trial_standard_passes_calibrated_evidence(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "standard.png")
    captured_requests: list[dict] = []
    evidence = {
        "contract_version": "panel_learning_draft_observation_evidence_v1",
        "calibrated_targets": [
            {
                "candidate_id": "search_input",
                "label": "Search",
                "role": "text_input",
                "bbox": {"x": 10, "y": 20, "w": 100, "h": 30},
                "click_point": {"x": 60, "y": 35},
            }
        ],
        "model_roles": {
            "screen_understanding": {"expected_model_family": "8B"},
            "coordinate_calibration": {"expected_model_family": "4B"},
        },
    }

    def fake_model(request: dict) -> dict:
        captured_requests.append(request)
        return {"status": "success", "model_json": _good_draft()}

    build_learning_model_trial(
        image_path=image_path,
        app_name="python.org",
        state_hint="homepage",
        goal="learn from calibrated page evidence",
        validation_mode="standard",
        max_attempts=1,
        observation_evidence=evidence,
        model_client=fake_model,
    )

    request = captured_requests[0]
    assert request["app_name"] == "python.org"
    assert request["state_hint"] == "homepage"
    context = request["learning_trial_context"]
    assert context["prompt_context_hidden"] is False
    assert context["observation_evidence"] == evidence
    assert context["observation_evidence"]["calibrated_targets"][0]["candidate_id"] == "search_input"


def test_learning_model_trial_strict_blind_cannot_pass_without_validation_answer(tmp_path: Path) -> None:
    image_path = _image(tmp_path / "no-answer.png")

    def fake_model(_request: dict) -> dict:
        return {"status": "success", "model_json": _good_draft()}

    result = build_learning_model_trial(image_path=image_path, max_attempts=1, model_client=fake_model)

    assert result["status"] == "needs_more_learning"
    assert result["best_score_percent"] < 90
    checks = result["attempts"][0]["score_report"]["checks"]
    assert any(
        item["check_id"] == "expected_action.validation_answer_present"
        and item["severity"] == "hard_error"
        and item["passed"] is False
        for item in checks
    )


def test_learning_model_trial_route_returns_structured_image_error() -> None:
    client = TestClient(app)

    response = client.get("/runtime/learning/model_trial?image_path=missing.png")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "learning_trial_image_not_found"
