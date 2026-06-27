from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.learn.interface_map import build_learned_interface_map
from app.learn.visual_asset_crops import build_visual_assets_from_screen_map


def _sample_screen(path: Path) -> None:
    image = Image.new("RGB", (640, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((420, 60, 560, 106), radius=8, fill=(229, 0, 125))
    draw.text((452, 76), "Quick apply", fill="white")
    draw.rounded_rectangle((420, 130, 560, 176), radius=8, fill=(30, 30, 30))
    draw.text((462, 146), "Submit", fill="white")
    draw.rectangle((40, 80, 340, 260), fill=(245, 245, 245), outline=(210, 210, 210))
    draw.text((58, 104), "Graduate Software Engineer", fill=(20, 20, 20))
    image.save(path)


def test_learn_mode_auto_crops_stable_button_assets(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_job_detail",
        "candidates": [
            {
                "candidate_id": "quick_apply",
                "label": "Quick apply",
                "role": "button",
                "section_id": "seek:job_detail",
                "bbox": {"x": 420, "y": 60, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 83},
                "risk_class": "safe_open_apply_flow",
                "source": "screen_map",
            },
            {
                "candidate_id": "job_card_1",
                "label": "Graduate Software Engineer at Example Company",
                "role": "job_card",
                "section_id": "seek:results_list",
                "bbox": {"x": 40, "y": 80, "w": 300, "h": 180},
                "risk_class": "safe_click_allowed",
                "source": "screen_map",
            },
        ],
    }

    result = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_job_detail",
        capture_id="capture-1",
        learn_depth="fast",
    )

    assets = result["visual_assets"]["assets"]
    assert result["contract_version"] == "visual_asset_learning_v1"
    assert result["summary"]["candidate_count"] == 2
    assert result["summary"]["asset_count"] == 1
    assert assets[0]["asset_status"] == "draft_observed"
    assert assets[0]["semantic_action"] == "open_apply_flow"
    assert assets[0]["danger_level"] == "flow_entry"
    assert assets[0]["review_policy"]["click_permission"] == "gate_required"
    assert assets[0]["review_policy"]["fast_lane_eligible"] is False
    assert assets[0]["can_authorize_click"] is False
    assert assets[0]["source"]["capture_id"] == "capture-1"
    assert assets[0]["source_geometry"]["click_point"] == {"x": 490, "y": 83}
    assert assets[0]["artifact_is_authorization"] is False
    assert assets[0]["source_geometry"]["source_is_authorization"] is False
    assert Path(assets[0]["crop"]["tight_crop_ref"]).exists()
    assert Path(assets[0]["crop"]["context_crop_ref"]).exists()
    assert assets[0]["template_refs"]["tight_crop_ref"] == assets[0]["crop"]["tight_crop_ref"]
    assert assets[0]["template_refs"]["context_crop_ref"] == assets[0]["crop"]["context_crop_ref"]
    assert assets[0]["template_refs"]["source_image_path"] == str(image_path)
    assert all(asset["label"] != "Graduate Software Engineer at Example Company" for asset in assets)


def test_seek_standard_apply_visual_asset_is_external_flow(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_job_detail",
        "candidates": [
            {
                "candidate_id": "standard_apply",
                "label": "Apply",
                "role": "button",
                "section_id": "seek:job_detail",
                "bbox": {"x": 420, "y": 60, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 83},
                "risk_class": "safe_open_apply_flow",
                "source": "screen_map",
            },
            {
                "candidate_id": "quick_apply",
                "label": "Quick apply",
                "role": "button",
                "section_id": "seek:job_detail",
                "bbox": {"x": 420, "y": 130, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 153},
                "risk_class": "safe_open_apply_flow",
                "source": "screen_map",
            },
        ],
    }

    result = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_job_detail",
        capture_id="capture-apply",
        learn_depth="fast",
    )

    assets = {asset["label"]: asset for asset in result["visual_assets"]["assets"]}
    assert assets["Apply"]["semantic_action"] == "external_apply_flow"
    assert assets["Apply"]["danger_level"] == "external_flow_entry"
    assert assets["Quick apply"]["semantic_action"] == "open_apply_flow"
    assert assets["Quick apply"]["danger_level"] == "flow_entry"


def test_learn_mode_marks_submit_asset_as_final_submit_not_authorization(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_application_review",
        "candidates": [
            {
                "candidate_id": "submit_application",
                "label": "Submit application",
                "role": "button",
                "section_id": "seek:application_form",
                "bbox": {"x": 420, "y": 130, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 153},
                "risk_class": "potential_side_effect_action",
                "source": "screen_map",
            }
        ],
    }

    result = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_application_review",
        capture_id="capture-2",
        learn_depth="deep",
    )

    asset = result["visual_assets"]["assets"][0]
    assert asset["asset_status"] == "verified_stable"
    assert asset["semantic_action"] == "final_submit"
    assert asset["danger_level"] == "final_submit"
    assert asset["review_policy"]["click_permission"] == "manual_review_required"
    assert asset["review_policy"]["requires_manual_review_before_click"] is True
    assert asset["review_policy"]["requires_structured_authorization"] is True
    assert asset["review_policy"]["fast_lane_eligible"] is False
    assert asset["requires_gate"] is True
    assert asset["can_authorize_click"] is False
    assert asset["artifact_is_authorization"] is False


def test_learn_mode_does_not_turn_progress_label_into_final_submit_asset(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_application_choose_documents",
        "candidates": [
            {
                "candidate_id": "progress_review_submit",
                "label": "Review and submit",
                "role": "recommendation_item",
                "section_id": "seek:application_progress",
                "bbox": {"x": 420, "y": 130, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 153},
                "risk_class": "safe_read_only",
                "source": "screen_map",
            }
        ],
    }

    result = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_application_choose_documents",
        capture_id="capture-progress",
        learn_depth="fast",
    )

    assert result["summary"]["asset_count"] == 0
    assert result["visual_assets"]["assets"] == []


def test_learned_interface_map_preserves_auto_cropped_asset_geometry(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_job_detail",
        "candidates": [
            {
                "candidate_id": "quick_apply",
                "label": "Quick apply",
                "role": "button",
                "section_id": "seek:job_detail",
                "bbox": {"x": 420, "y": 60, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 83},
                "risk_class": "safe_open_apply_flow",
                "source": "screen_map",
            }
        ],
    }
    learned = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_job_detail",
        capture_id="capture-3",
        learn_depth="fast",
    )
    runtime_graph = {
        "contract_version": "runtime_path_graph_v1",
        "app_id": "seek",
        "page_type": "seek_job_detail",
        "regions": [
            {
                "region_id": "seek:job_detail",
                "label": "Job detail",
                "role": "detail_content",
                "bbox": {"x": 400, "y": 40, "w": 220, "h": 180},
            }
        ],
    }

    interface_map = build_learned_interface_map(runtime_graph, learned["visual_assets"])

    asset = interface_map["fixed_visual_assets"][0]
    assert Path(asset["template_refs"]["tight_crop_ref"]).exists()
    assert asset["region_id"] == "seek:job_detail"
    assert asset["allowed_region_ids"] == ["seek:job_detail"]
    assert asset["template_refs"]["source_image_path"] == str(image_path)
    assert asset["source_geometry"]["bbox"] == {"x": 420, "y": 60, "w": 140, "h": 46}
    assert asset["source_geometry"]["click_point"] == {"x": 490, "y": 83}
    assert asset["source_geometry"]["source_is_authorization"] is False
    assert asset["can_authorize_click"] is False
    assert asset["review_policy"]["click_permission"] == "gate_required"
    assert asset["fast_lane_eligible"] is False
    assert interface_map["regions"][0]["children"]["fixed_visual_asset_refs"] == [asset["asset_id"]]


def test_learned_interface_map_exposes_high_risk_visual_asset_review_policy(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    _sample_screen(image_path)
    screen_map = {
        "page_type": "seek_application_review",
        "candidates": [
            {
                "candidate_id": "submit_application",
                "label": "Submit application",
                "role": "button",
                "section_id": "seek:application_form",
                "bbox": {"x": 420, "y": 130, "w": 140, "h": 46},
                "click_point": {"x": 490, "y": 153},
                "risk_class": "potential_side_effect_action",
                "source": "screen_map",
            }
        ],
    }
    learned = build_visual_assets_from_screen_map(
        screen_map,
        source_image_path=image_path,
        output_dir=tmp_path / "assets",
        app_id="seek",
        page_type="seek_application_review",
        capture_id="capture-submit",
        learn_depth="deep",
    )
    runtime_graph = {
        "contract_version": "runtime_path_graph_v1",
        "app_id": "seek",
        "page_type": "seek_application_review",
        "regions": [
            {
                "region_id": "seek:application_form",
                "label": "Application form",
                "role": "form_flow",
                "bbox": {"x": 400, "y": 110, "w": 220, "h": 100},
            }
        ],
    }

    interface_map = build_learned_interface_map(runtime_graph, learned["visual_assets"])

    asset = interface_map["fixed_visual_assets"][0]
    assert asset["is_high_risk"] is True
    assert asset["click_permission"] == "manual_review_required"
    assert asset["review_policy"]["requires_manual_review_before_click"] is True
    assert asset["review_policy"]["requires_structured_authorization"] is True
    assert asset["fast_lane_eligible"] is False
    assert interface_map["summary"]["danger_zone_count"] == 1
    danger_zone = interface_map["danger_zones"][0]
    assert danger_zone["asset_id"] == asset["asset_id"]
    assert danger_zone["click_permission"] == "manual_review_required"
    assert danger_zone["review_policy"]["risk_tier"] == "high"
