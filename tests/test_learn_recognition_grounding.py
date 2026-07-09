from __future__ import annotations

from app.learn.recognition.grounding import (
    build_grounding_request,
    local_point_from_grounding_result,
    normalize_grounding_result_to_screen,
)
from app.learn.recognition.roi import build_roi_crop_metadata


def test_grounding_request_is_display_only_and_carries_roi_contract():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1200, "height": 800},
        candidate_bbox={"x": 500, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 200, "height": 80},
    )
    request = build_grounding_request(
        item={
            "item_id": "search_input",
            "label": "Search",
            "item_type": "form_field",
            "role": "input",
            "bbox": {"x": 500, "y": 300, "w": 100, "h": 40},
            "source_evidence": ["omniparser", "ocr"],
            "interactable_evidence": {"omniparser_interactable": True},
        },
        roi_crop=roi,
    )

    assert request["contract_version"] == "learn_grounding_request_v1"
    assert request["authorization"]["artifact_is_authorization"] is False
    assert request["authorization"]["execute_binding_enabled"] is False
    assert request["authorization"]["real_action_requires_gate"] is True
    assert request["target"]["label"] == "Search"
    assert request["roi_crop"]["contract_version"] == "learn_roi_crop_v1"
    assert request["target"]["candidate_bbox_in_roi"] == {"x": 50, "y": 20, "w": 100, "h": 40}
    assert "coordinate_space=uground_0_999 + point_999/raw_output" in request["accepted_output_contracts"]
    assert "coordinate_space=normalized_0_1000 + point_1000/raw_output" in request["accepted_output_contracts"]


def test_uground_0_999_result_restores_roi_point_to_screen():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1200, "height": 800},
        candidate_bbox={"x": 500, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 200, "height": 80},
    )

    local_point = local_point_from_grounding_result(
        {"coordinate_space": "uground_0_999", "raw_output": "(500, 500)"},
        roi_crop=roi,
    )
    normalized = normalize_grounding_result_to_screen(
        {
            "coordinate_space": "uground_0_999",
            "raw_output": "(500, 500)",
            "evidence": {"screenshot_freshness": True},
        },
        roi_crop=roi,
    )

    assert local_point == {"x": 100, "y": 40}
    assert normalized["screen_point"] == {"x": 550, "y": 320}
    assert normalized["evidence"]["coordinate_transform_replay"] is True
    assert normalized["debug"]["local_point_restored_to_screen"] is True


def test_unknown_coordinate_space_does_not_guess_point():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 800, "height": 600},
        candidate_bbox={"x": 100, "y": 100, "w": 80, "h": 40},
        crop_size={"width": 160, "height": 80},
    )

    normalized = normalize_grounding_result_to_screen(
        {"raw_output": "(500, 500)"},
        roi_crop=roi,
    )

    assert "screen_point" not in normalized


def test_normalized_0_1000_result_restores_roi_point_to_screen():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1200, "height": 800},
        candidate_bbox={"x": 500, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 200, "height": 80},
    )

    normalized = normalize_grounding_result_to_screen(
        {
            "coordinate_space": "normalized_0_1000",
            "raw_output": "[500, 500]",
            "evidence": {"screenshot_freshness": True},
        },
        roi_crop=roi,
    )

    assert normalized["screen_point"] == {"x": 550, "y": 320}
    assert normalized["evidence"]["coordinate_transform_replay"] is True


def test_roi_local_point_coordinate_space_restores_raw_output_to_screen():
    roi = build_roi_crop_metadata(
        source_image_size={"width": 1200, "height": 800},
        candidate_bbox={"x": 500, "y": 300, "w": 100, "h": 40},
        crop_size={"width": 200, "height": 80},
    )

    normalized = normalize_grounding_result_to_screen(
        {
            "coordinate_space": "roi_local_point",
            "raw_output": [100, 40],
            "evidence": {"screenshot_freshness": True},
        },
        roi_crop=roi,
    )

    assert normalized["screen_point"] == {"x": 550, "y": 320}
    assert normalized["debug"]["coordinate_space"] == "roi_local_point"
