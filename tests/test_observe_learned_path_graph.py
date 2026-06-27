from __future__ import annotations

from app.api.vision import _apply_learned_path_graph_to_screen_map
from app.models.request import VisionObserveScreenRequestModel


def test_seek_observe_screen_map_uses_learned_path_graph_for_search_results() -> None:
    screen_map = {
        "contract_version": "screen_map_v1",
        "state_id": "model_state",
        "summary": {"candidate_count": 1, "section_count": 3},
        "sections": [{"section_id": "primary_area", "bbox": {"x": 0, "y": 220, "w": 2560, "h": 1000}}],
        "candidates": [
            {
                "contract_version": "screen_map_candidate_v1",
                "candidate_id": "card_primary_area_24",
                "label": "Software Engineer Specialist - Integration",
                "role": "news_card",
                "risk_class": "safe_dry_run_only",
                "bbox": {"x": 636, "y": 692, "w": 470, "h": 352},
            }
        ],
    }
    result = {
        "app_name": "seek",
        "screen_summary": "Software engineer job search results page",
        "state_guess": "SEEK software engineer search results page",
        "image_size": {"width": 2560, "height": 1400},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Apply"}, {"label": "Save"}],
        },
    }

    assisted = _apply_learned_path_graph_to_screen_map(
        screen_map,
        result=result,
        request=VisionObserveScreenRequestModel(app_name="seek", state_hint="SEEK search results"),
        image_path="missing-test-image.png",
    )

    section_ids = {item["section_id"] for item in assisted["sections"]}
    assert {"top_search_area", "results_list", "job_detail", "job_card", "detail_header", "detail_body"} <= section_ids
    assert assisted["summary"]["learned_path_graph_used"] is True
    assert assisted["learned_path_graph_resolution"]["matched"] is True
    assert assisted["learned_path_graph_resolution"]["screen_map_policy"] == "learned_path_graph_primary_model_supplemental"
    action_ids = {item["action_template_id"] for item in assisted["learned_path_graph_available_actions"]["actions"]}
    assert {"open_job_card", "read_detail", "load_more_results"} <= action_ids

    observed_card = next(item for item in assisted["candidates"] if item["candidate_id"] == "card_primary_area_24")
    assert observed_card["section_id"] == "results_list"
    assert observed_card["role"] == "job_card"
    assert observed_card["risk_class"] == "safe_click_allowed"


def test_seek_application_form_does_not_use_search_results_path_graph() -> None:
    screen_map = {
        "contract_version": "screen_map_v1",
        "state_id": "application_form",
        "summary": {"candidate_count": 0, "section_count": 1},
        "sections": [],
        "candidates": [],
    }
    result = {
        "app_name": "seek",
        "screen_summary": "Choose documents for application form",
        "image_size": {"width": 1600, "height": 1000},
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "page_elements": [{"text": "Choose documents"}, {"text": "Review and submit"}],
        },
    }

    assisted = _apply_learned_path_graph_to_screen_map(
        screen_map,
        result=result,
        request=VisionObserveScreenRequestModel(app_name="seek", state_hint="Choose documents"),
        image_path="missing-test-image.png",
    )

    assert assisted["learned_path_graph_resolution"]["matched"] is False
    assert assisted["learned_path_graph_resolution"]["reason"] == "seek_application_form_not_search_results"
    assert assisted["sections"] == []
