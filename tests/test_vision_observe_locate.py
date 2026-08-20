from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.api import vision as vision_api
from app.api.models.request import OCRRegionRequest, ROIModel, VisionLocateTargetRequestModel, VisionObserveScreenRequestModel
from app.api.models.request import VisionRecognitionPlanRequestModel
from app.api.models.response import APIResponse, ErrorModel
from app.vision.schemas import ImageSize, VisionAnalyzeResponse
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def test_vista_client_timeout_allows_for_image_encoding_and_response_flush() -> None:
    assert vision_api._vista_client_timeout_seconds(12.0) == 42.0
    assert vision_api._vista_client_timeout_seconds(30.0) == 90.0


def test_learning_grounding_config_uses_requested_learn_only_profile(monkeypatch) -> None:
    config = {
        "vision": {
            "local_grounding": {
                "profile_id": "vista_4b_transformers",
                "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
                "model_name": "inclusionAI/VISTA-4B",
            }
        }
    }
    monkeypatch.setattr(
        vision_api,
        "load_model_profiles",
        lambda: [
            {
                "profile_id": "learn_mode_uground_2b",
                "mode_scope": "learn_only",
                "provider_mode": "local_grounding",
                "endpoint": "http://127.0.0.1:13245/v1/chat/completions",
                "model_name": "osunlp/UGround-V1-2B",
                "output_contract": "learn_grounding_result_v1",
            }
        ],
    )
    request = VisionLocateTargetRequestModel(
        goal="learn all visible controls",
        agent_mode="learn",
        learn_depth="deep",
        metadata={"learn_grounding_profile_id": "learn_mode_uground_2b"},
    )

    selected = vision_api._selected_learning_grounding_config(config, request)

    assert selected["profile_id"] == "learn_mode_uground_2b"
    assert selected["endpoint"] == "http://127.0.0.1:13245/v1/chat/completions"
    assert selected["model_name"] == "osunlp/UGround-V1-2B"
    options = vision_api._learn_vista_coordinate_validation_options(request, selected)
    assert options["enabled"] is True


def test_learning_grounding_config_does_not_override_execute_mode(monkeypatch) -> None:
    config = {
        "vision": {
            "local_grounding": {
                "profile_id": "vista_4b_transformers",
                "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
            }
        }
    }
    monkeypatch.setattr(
        vision_api,
        "load_model_profiles",
        lambda: [
            {
                "profile_id": "learn_mode_uground_2b",
                "mode_scope": "learn_only",
                "provider_mode": "local_grounding",
                "endpoint": "http://127.0.0.1:13245/v1/chat/completions",
            }
        ],
    )
    request = VisionLocateTargetRequestModel(
        goal="locate button",
        agent_mode="execute",
        metadata={"learn_grounding_profile_id": "learn_mode_uground_2b"},
    )

    selected = vision_api._selected_learning_grounding_config(config, request)

    assert selected["profile_id"] == "vista_4b_transformers"
    assert selected["endpoint"] == "http://127.0.0.1:13244/v1/chat/completions"


def test_learning_capture_readiness_rejects_splash_and_accepts_loaded_ui(tmp_path: Path) -> None:
    splash_path = tmp_path / "splash.png"
    splash = Image.new("RGB", (800, 600), (0, 120, 215))
    ImageDraw.Draw(splash).rectangle((385, 285, 415, 315), fill=(220, 230, 235))
    splash.save(splash_path)

    loaded_path = tmp_path / "loaded.png"
    loaded = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(loaded)
    draw.rectangle((0, 0, 800, 64), fill=(225, 230, 238))
    for row in range(4):
        for column in range(5):
            x = 40 + column * 145
            y = 95 + row * 115
            draw.rectangle((x, y, x + 112, y + 82), fill=(40 + row * 35, 70 + column * 20, 120 + row * 20))
    loaded.save(loaded_path)

    assert vision_api._learning_capture_visual_readiness(splash_path)["ready"] is False
    assert vision_api._learning_capture_visual_readiness(loaded_path)["ready"] is True


def test_learning_capture_readiness_rejects_titled_splash_with_center_icon(tmp_path: Path) -> None:
    splash_path = tmp_path / "titled_splash.png"
    splash = Image.new("RGB", (900, 1000), (0, 120, 215))
    draw = ImageDraw.Draw(splash)
    draw.rectangle((0, 0, 900, 42), fill=(0, 120, 215))
    draw.line((0, 42, 900, 42), fill=(205, 220, 230), width=1)
    draw.rectangle((815, 12, 828, 25), outline=(235, 245, 250), width=1)
    draw.line((852, 12, 865, 25), fill=(235, 245, 250), width=1)
    draw.line((865, 12, 852, 25), fill=(235, 245, 250), width=1)
    draw.rounded_rectangle((421, 470, 479, 530), radius=4, fill=(65, 90, 105))
    draw.rectangle((429, 478, 471, 489), fill=(215, 230, 235))
    for row in range(3):
        for column in range(3):
            x = 429 + column * 14
            y = 494 + row * 11
            draw.rectangle((x, y, x + 9, y + 7), fill=(190, 205, 215))
    splash.save(splash_path)

    readiness = vision_api._learning_capture_visual_readiness(splash_path)

    assert readiness["ready"] is False
    assert readiness["reason"] == "low_information_startup_surface"


def test_learning_observe_capture_retries_until_window_is_visually_ready(monkeypatch, tmp_path: Path) -> None:
    splash_path = tmp_path / "splash.png"
    Image.new("RGB", (640, 480), (0, 120, 215)).save(splash_path)
    loaded_path = tmp_path / "loaded.png"
    loaded = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(loaded)
    for index in range(12):
        x = 20 + (index % 4) * 150
        y = 40 + (index // 4) * 130
        draw.rectangle((x, y, x + 120, y + 90), fill=(30 + index * 8, 80, 150))
    loaded.save(loaded_path)

    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(splash_path), {"image_path": str(splash_path)}),
    )
    monkeypatch.setattr(
        vision_api.screenshot_service,
        "capture_window",
        lambda **_kwargs: {"image_path": str(loaded_path), "image_width": 640, "image_height": 480},
    )
    monkeypatch.setattr(vision_api.time, "sleep", lambda _seconds: None)

    image_path, live_capture = vision_api._learning_observe_image_source(
        VisionObserveScreenRequestModel(
            app_name="calculator",
            capture_live=True,
            agent_mode="learn",
            metadata={"learning_studio_draft_capture": True},
        )
    )

    assert image_path == str(loaded_path)
    assert live_capture["capture_readiness"]["ready"] is True
    assert live_capture["capture_readiness"]["attempt_count"] == 2
    assert len(live_capture["capture_readiness"]["attempts"]) == 2


def test_observe_screen_wraps_live_capture_and_screen_reading(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-trace.json")

    def fake_screen_reading(request):
        assert request.image_path == "screen.png"
        assert request.provider_mode == "local_understanding"
        assert request.metadata["ocr_anchors"]["enabled"] is True
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "image_size": {"width": 900, "height": 700},
                    "state_guess": "job results list",
                    "screen_summary": "A job results page with filters and result cards.",
                    "texts": [
                        {
                            "id": "text_docs",
                            "text": "Docs",
                            "bbox": {"x": 240, "y": 96, "w": 42, "h": 18},
                            "confidence": 0.94,
                        },
                        {
                            "id": "text_card_title",
                            "text": "回报率测试",
                            "bbox": {"x": 320, "y": 310, "w": 80, "h": 22},
                            "confidence": 0.98,
                        },
                        {
                            "id": "text_card_body",
                            "text": "Hz轮询率",
                            "bbox": {"x": 322, "y": 340, "w": 68, "h": 18},
                            "confidence": 0.96,
                        },
                        {
                            "id": "text_apply",
                            "text": "Apply now",
                            "bbox": {"x": 360, "y": 360, "w": 74, "h": 24},
                            "confidence": 0.96,
                        }
                    ],
                    "screen_reading": {
                        "ui": {
                            "elements": [
                                {
                                    "id": "element_filter",
                                    "label": "Filter",
                                    "type": "button",
                                    "bbox": {"x": 20, "y": 30, "w": 80, "h": 32},
                                    "click_point": {"x": 60, "y": 46},
                                    "confidence": 0.88,
                                    "evidence": {
                                        "interaction_policy": {
                                            "allowed": True,
                                            "reasons": ["nav_control"],
                                        }
                                    },
                                    "verification_hints": {"expected_changes": ["filter panel opens"]},
                                },
                                {
                                    "id": "element_delete",
                                    "label": "Delete",
                                    "type": "button",
                                    "bbox": {"x": 120, "y": 30, "w": 80, "h": 32},
                                    "click_point": {"x": 160, "y": 46},
                                    "confidence": 0.8,
                                },
                            ],
                        }
                    },
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo", provider_mode="local"))

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "screen_observation_v1"
    assert result["agent_mode"] == "learn"
    assert result["learn_depth"] == "fast"
    assert result["mode_contract_version"] == "learn_screen_fast_v1"
    assert result["write_policy"] == {"path_graph": True, "element_memory": False, "trace": True}
    assert result["live_capture"]["image_path"] == "screen.png"
    assert result["suggested_state_hint"] == "job results list"
    assert result["screen_map"]["contract_version"] == "screen_map_v1"
    assert result["screen_map"]["state_id"].startswith("state_")
    assert result["screen_map"]["summary"]["section_count"] >= 2
    assert not any(
        section["section_id"] == "bottom_bar"
        for section in result["screen_map"]["sections"]
    )
    assert result["screen_map"]["summary"]["candidate_count"] >= 6
    assert result["screen_map"]["sections"][0]["contract_version"] == "screen_map_section_v1"
    assert result["screen_map"]["candidates"][0]["label"] == "Filter"
    assert result["screen_map"]["candidates"][0]["section_id"]
    assert result["screen_map"]["candidates"][0]["risk_class"] == "safe_click_allowed"
    assert result["screen_map"]["candidates"][0]["expected_effect"] == "filter panel opens"
    assert result["operation_context"]["skill_id"] == "observe_screen"
    assert result["operation_context"]["requires_gate"] is False
    assert result["operation_trace_link"]["result_status"] == "success"
    assert result["screen_map"]["candidates"][1]["risk_class"] == "requires_user_confirmation"
    candidates = result["screen_map"]["candidates"]
    docs = next(item for item in candidates if item["label"] == "Docs")
    assert docs["role"] == "nav_text_action"
    assert docs["section_id"] == "top_bar"
    card = next(item for item in candidates if item["label"] == "回报率测试" and item["source"] == "ocr_card_groups")
    assert card["bbox"]["w"] > 80
    assert card["bbox"]["h"] > 22
    assert card["section_id"] == "primary_area"
    assert any(item["label"] == "Apply now" and item["source"] == "ocr_text_actions" for item in candidates)
    assert "screen_map.state_id" in result["agent_next_steps"][1]
    assert "POST /vision/locate_target" in result["agent_next_steps"][2]


def test_ocr_region_returns_read_region_operation_context(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api.screenshot_service,
        "capture_window",
        lambda **_kwargs: {
            "image_path": "roi.png",
            "roi": {"x": 1, "y": 2, "width": 50, "height": 20},
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(
        vision_api.ocr_service,
        "scan_image",
        lambda path: OCRResult(
            image_path=path,
            matches=[OCRTextMatch(text="Apply", score=0.98, bbox=OCRBoundingBox(x=1, y=2, width=40, height=12))],
        ),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "ocr-region-trace.json")

    response = vision_api.ocr_region(OCRRegionRequest(roi=ROIModel(x=1, y=2, width=50, height=20)))

    assert response.success is True
    result = response.data["result"]
    assert result["operation_context"]["skill_id"] == "read_region"
    assert result["operation_context"]["requires_gate"] is False
    assert result["operation_trace_link"]["result_status"] == "success"
    assert result["trace_path"] == "ocr-region-trace.json"


def test_observe_screen_learn_mode_outputs_interface_map_with_visual_assets(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "seek_detail.png"
    image = vision_api.Image.new("RGB", (900, 700), "white")
    draw = vision_api.ImageDraw.Draw(image)
    draw.rounded_rectangle((520, 360, 660, 408), radius=8, fill=(229, 0, 125))
    draw.text((548, 375), "Quick apply", fill="white")
    image.save(image_path)
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(image_path), {"image_path": str(image_path), "image_width": 900, "image_height": 700}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-interface-map-trace.json")

    def fake_screen_reading(_request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "image_size": {"width": 900, "height": 700},
                    "state_guess": "seek job detail",
                    "screen_summary": "A SEEK job detail page with a Quick apply button.",
                    "screen_reading": {
                        "ui": {
                            "elements": [
                                {
                                    "id": "quick_apply",
                                    "label": "Quick apply",
                                    "type": "button",
                                    "bbox": {"x": 520, "y": 360, "w": 140, "h": 48},
                                    "click_point": {"x": 590, "y": 384},
                                    "confidence": 0.92,
                                }
                            ]
                        }
                    },
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="seek", learn_depth="fast"))

    assert response.success is True
    result = response.data["result"]
    assert result["visual_asset_learning"]["contract_version"] == "visual_asset_learning_v1"
    assert result["visual_asset_learning"]["summary"]["asset_count"] == 1
    assert result["learned_interface_map"]["contract_version"] == "learned_interface_map_v1"
    assert result["learned_interface_map"]["source"]["artifact_is_authorization"] is False
    fixed_asset = result["learned_interface_map"]["fixed_visual_assets"][0]
    assert fixed_asset["semantic_action"] == "open_apply_flow"
    assert fixed_asset["can_authorize_click"] is False
    assert fixed_asset["source_geometry"]["bbox"] == {"x": 520, "y": 360, "w": 140, "h": 48}
    assert fixed_asset["source_geometry"]["click_point"] == {"x": 590, "y": 384}
    assert Path(fixed_asset["template_refs"]["tight_crop_ref"]).exists()
    assert result["screen_map"]["learned_interface_map_summary"]["fixed_visual_asset_count"] == 1


def test_observe_screen_groups_news_cards_from_ocr_text(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("news.png", {"image_path": "news.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-news-trace.json")

    def fake_screen_reading(_request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "image_size": {"width": 1200, "height": 900},
                    "state_guess": "Google News home",
                    "screen_summary": "A news homepage with top navigation, a main feed, and a recommendation column.",
                    "texts": [
                        {"id": "nav_home", "text": "Home", "bbox": {"x": 360, "y": 132, "w": 42, "h": 18}, "confidence": 0.98},
                        {"id": "nav_for_you", "text": "For you", "bbox": {"x": 430, "y": 132, "w": 62, "h": 18}, "confidence": 0.98},
                        {"id": "header_search_icon_noise", "text": "Q", "bbox": {"x": 334, "y": 102, "w": 18, "h": 17}, "confidence": 0.98},
                        {"id": "header_badge_noise", "text": "11:", "bbox": {"x": 1166, "y": 98, "w": 27, "h": 28}, "confidence": 0.98},
                        {"id": "header_avatar_noise", "text": "李杰", "bbox": {"x": 1212, "y": 105, "w": 32, "h": 18}, "confidence": 0.98},
                        {"id": "main_source", "text": "World Journal", "bbox": {"x": 330, "y": 282, "w": 88, "h": 18}, "confidence": 0.95},
                        {
                            "id": "main_title",
                            "text": "World leaders meet for climate agreement",
                            "bbox": {"x": 330, "y": 310, "w": 285, "h": 24},
                            "confidence": 0.98,
                        },
                        {"id": "main_time", "text": "5 hours ago", "bbox": {"x": 330, "y": 348, "w": 78, "h": 18}, "confidence": 0.94},
                        {
                            "id": "main_more",
                            "text": "View more top stories",
                            "bbox": {"x": 330, "y": 390, "w": 155, "h": 22},
                            "confidence": 0.96,
                        },
                        {"id": "side_source", "text": "Business News", "bbox": {"x": 820, "y": 286, "w": 96, "h": 18}, "confidence": 0.95},
                        {
                            "id": "side_metadata_mojibake",
                            "text": "Daily Mail 8 \u00e5\u00b0\u008f\u00e6\u0097\u00b6",
                            "bbox": {"x": 820, "y": 300, "w": 155, "h": 18},
                            "confidence": 0.95,
                        },
                        {
                            "id": "side_title",
                            "text": "Markets rally after earnings report",
                            "bbox": {"x": 820, "y": 314, "w": 250, "h": 22},
                            "confidence": 0.97,
                        },
                        {"id": "side_time", "text": "2 hours ago", "bbox": {"x": 820, "y": 350, "w": 78, "h": 18}, "confidence": 0.94},
                    ],
                    "screen_reading": {"ui": {"elements": []}},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="google"))

    assert response.success is True
    candidates = response.data["result"]["screen_map"]["candidates"]
    home = next(item for item in candidates if item["label"] == "Home")
    assert home["role"] == "nav_text_action"
    main_card = next(item for item in candidates if item["label"] == "World leaders meet for climate agreement")
    side_card = next(item for item in candidates if item["label"] == "Markets rally after earnings report")
    assert main_card["source"] == "ocr_card_groups"
    assert main_card["role"] == "news_card"
    assert main_card["section_id"] == "main_content"
    assert main_card["children"]
    assert any(child["role"] == "title" for child in main_card["children"])
    assert side_card["source"] == "ocr_card_groups"
    assert side_card["role"] == "recommendation_item"
    assert side_card["section_id"] == "right_sidebar"
    more_button = next(item for item in candidates if item["label"] == "View more top stories")
    assert more_button["source"] == "ocr_text_actions"
    assert more_button["role"] == "button"
    assert more_button["risk_class"] == "safe_click_allowed"
    assert more_button["screen_map_rule"] == "more_text_is_button"
    assert not any(item["label"] == "World Journal" and item["source"] == "ocr_card_groups" for item in candidates)
    assert not any(item["label"] == "5 hours ago" and item["source"] == "ocr_card_groups" for item in candidates)
    assert not any(item["label"].startswith("Daily Mail 8") and item["source"] == "ocr_card_groups" for item in candidates)
    assert not any(item["label"] == "View more top stories" and item["source"] == "ocr_card_groups" for item in candidates)
    assert not any(item["label"] in {"Q", "11:", "李杰"} and item["source"] == "ocr_text_actions" for item in candidates)


def test_screen_map_uses_application_sections_for_non_browser_layout() -> None:
    result = {
        "app_name": "lonlife_acc",
        "suggested_state_hint": "game acceleration dashboard",
        "screen_summary": "Game acceleration dashboard for 三角洲行动",
        "image_size": {"width": 1000, "height": 690},
        "texts": [
            {"id": "tab_accel", "text": "加速", "bbox": {"x": 118, "y": 19, "w": 40, "h": 25}},
            {"id": "tab_game", "text": "游戏", "bbox": {"x": 203, "y": 19, "w": 42, "h": 25}},
            {"id": "start_game", "text": "启动游戏", "bbox": {"x": 47, "y": 505, "w": 63, "h": 19}},
            {"id": "stop_accel", "text": "停止加速", "bbox": {"x": 199, "y": 505, "w": 61, "h": 19}},
            {"id": "invite", "text": "每邀请一名好友，", "bbox": {"x": 322, "y": 521, "w": 258, "h": 72}},
            {"id": "join", "text": "点击参与", "bbox": {"x": 769, "y": 571, "w": 61, "h": 23}},
        ],
    }

    sections = vision_api._screen_map_sections(result)
    section_ids = [section["section_id"] for section in sections]
    assert "browser_chrome" not in section_ids
    assert "right_sidebar" not in section_ids
    assert section_ids[:2] == ["top_bar", "primary_area"]

    candidates = vision_api._screen_map_candidates(result, sections=sections)
    accel = next(item for item in candidates if item["label"] == "加速")
    start_game = next(item for item in candidates if item["label"] == "启动游戏")
    join = next(item for item in candidates if item["label"] == "点击参与")
    assert accel["section_id"] == "top_bar"
    assert start_game["section_id"] == "primary_area"
    assert join["section_id"] == "primary_area"


def test_sparse_application_sections_follow_visible_menu_and_status_bar_evidence() -> None:
    result = {
        "app_name": "plain_text_editor",
        "suggested_state_hint": "blank document",
        "screen_summary": "Blank text editor with menu bar and status bar",
        "image_size": {"width": 2576, "height": 1416},
        "texts": [
            {"id": "title", "text": "Untitled", "bbox": {"x": 10, "y": 10, "w": 111, "h": 23}},
            {"id": "menu", "text": "File Edit Format View Help", "bbox": {"x": 12, "y": 33, "w": 263, "h": 22}},
            {"id": "line", "text": "Ln 1, Col 1", "bbox": {"x": 2146, "y": 1389, "w": 99, "h": 22}},
            {"id": "encoding", "text": "100% Windows (CRLF)", "bbox": {"x": 2279, "y": 1376, "w": 283, "h": 37}},
        ],
        "ui_elements": [
            {
                "id": "menu_file",
                "type": "menu_item",
                "role_guess": "menu_item",
                "label": "File",
                "bbox": {"x": 20, "y": 40, "w": 60, "h": 20},
            },
            {
                "id": "menu_edit",
                "type": "menu_item",
                "role_guess": "menu_item",
                "label": "Edit",
                "bbox": {"x": 80, "y": 40, "w": 61, "h": 20},
            },
        ],
        "model_io": {
            "raw_response": {
                "model_json": {
                    "regions": [
                        {
                            "region_id": "status",
                            "role": "status_bar",
                            "diagonal": {"x1": 1711, "y1": 1368, "x2": 2576, "y2": 1416},
                        }
                    ]
                }
            }
        },
    }

    sections = vision_api._screen_map_sections(result)
    by_id = {section["section_id"]: section for section in sections}

    assert by_id["top_bar"]["bbox"]["h"] <= 80
    assert by_id["primary_area"]["bbox"]["y"] == by_id["top_bar"]["bbox"]["h"]
    assert by_id["bottom_bar"]["bbox"]["y"] >= 1360
    assert by_id["bottom_bar"]["role"] == "status"
    assert (
        by_id["primary_area"]["bbox"]["y"] + by_id["primary_area"]["bbox"]["h"]
        == by_id["bottom_bar"]["bbox"]["y"]
    )


def test_more_text_is_button_before_card_grouping() -> None:
    label = "\u67e5\u770b\u66f4\u591a\u5934\u6761\u65b0\u95fb\u548c\u89c2\u70b9"
    bbox = {"x": 100, "y": 300, "w": 200, "h": 24}

    assert vision_api._looks_like_more_button_text(label) is True
    assert vision_api._ocr_text_candidate_role(label, bbox, section_id="main_content") == "button"
    assert vision_api._is_card_seed_label(label, section_id="main_content", bbox=bbox) is False


def test_path_graph_recall_filters_browser_chrome_candidates() -> None:
    recall = vision_api._build_path_graph_recall(
        observe_reuse={
            "status": "ready",
            "trace_path": "observe.json",
            "anchor_count": 0,
            "screen_map": {
                "contract_version": "screen_map_v1",
                "state_id": "state_google_news",
                "candidates": [
                    {
                        "candidate_id": "browser_refresh",
                        "label": "C",
                        "role": "button",
                        "section_id": "browser_chrome",
                        "bbox": {"x": 56, "y": 53, "w": 15, "h": 14},
                        "click_point": {"x": 64, "y": 60},
                    },
                    {
                        "candidate_id": "see_more",
                        "label": "See more headlines and perspectives",
                        "role": "button",
                        "section_id": "main_content",
                        "bbox": {"x": 338, "y": 769, "w": 263, "h": 21},
                        "click_point": {"x": 470, "y": 780},
                    },
                ],
            },
        },
        goal="See more headlines and perspectives",
        top_k=5,
        image_size=ImageSize(width=1280, height=900),
    )

    assert recall["status"] == "ready"
    assert recall["summary"]["filtered_browser_chrome_count"] == 1
    assert recall["candidates"][0]["candidate_id"] == "see_more"
    assert all(item["section_id"] != "browser_chrome" for item in recall["candidates"])


def test_observe_screen_learn_deep_reviews_path_graph(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-deep-trace.json")

    def fake_screen_reading(request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "image_size": {"width": 900, "height": 700},
                    "state_guess": "settings page",
                    "screen_summary": "A settings page with duplicated action detections.",
                    "texts": [
                        {
                            "id": "text_save",
                            "text": "Save",
                            "bbox": {"x": 32, "y": 312, "w": 42, "h": 18},
                            "confidence": 0.96,
                        }
                    ],
                    "screen_reading": {
                        "ui": {
                            "elements": [
                                {
                                    "id": "element_save_a",
                                    "label": "Save",
                                    "type": "button",
                                    "bbox": {"x": 20, "y": 300, "w": 90, "h": 42},
                                    "click_point": {"x": 65, "y": 321},
                                    "confidence": 0.9,
                                },
                                {
                                    "id": "element_save_b",
                                    "label": "Save",
                                    "type": "button",
                                    "bbox": {"x": 23, "y": 302, "w": 90, "h": 42},
                                    "click_point": {"x": 68, "y": 323},
                                    "confidence": 0.88,
                                },
                            ]
                        }
                    },
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)

    request = VisionObserveScreenRequestModel(app_name="demo", learn_depth="deep")
    assert request.write_policy.model_dump() == {"path_graph": True, "element_memory": True, "trace": True}

    response = vision_api.observe_screen(request)

    assert response.success is True
    result = response.data["result"]
    assert result["learn_depth"] == "deep"
    assert result["mode_contract_version"] == "learn_screen_deep_v1"
    assert result["path_graph_deep_review"]["contract_version"] == "path_graph_deep_review_v1"
    assert result["path_graph_deep_review"]["summary"]["duplicate_count"] == 1
    assert result["path_graph_delta"]["contract_version"] == "path_graph_delta_v1"
    assert result["path_graph_delta"]["summary"]["removal_count"] == 1
    assert result["screen_map"]["learn_depth"] == "deep"
    assert result["screen_map"]["summary"]["deep_removal_count"] == 1
    assert result["element_memory_init_plan"]["contract_version"] == "element_memory_init_plan_v1"
    assert result["element_memory_init_plan"]["status"] == "planned"
    assert result["element_memory_init_plan"]["entry_count"] >= 1


def test_observe_screen_learn_deep_applies_model_review(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(image_path), {"image_path": str(image_path)}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-deep-model-trace.json")

    def fake_screen_reading(request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "image_size": {"width": 900, "height": 700},
                    "state_guess": "settings page",
                    "screen_summary": "A settings page.",
                    "texts": [],
                    "screen_reading": {
                        "ui": {
                            "elements": [
                                {
                                    "id": "element_save",
                                    "label": "Save",
                                    "type": "button",
                                    "bbox": {"x": 20, "y": 300, "w": 90, "h": 42},
                                    "click_point": {"x": 65, "y": 321},
                                    "confidence": 0.9,
                                }
                            ]
                        }
                    },
                }
            },
            error=None,
        )

    class DummyDeepProvider:
        def analyze(self, req):
            assert req.task == "learn_deep_review"
            assert req.provider_mode == "local_grounding"
            context = req.metadata["learn_deep_review_context"]
            assert context["candidates"][0]["candidate_id"] == "element_save"
            return VisionAnalyzeResponse(
                provider="dummy_deep",
                image_size=ImageSize(width=900, height=700),
                screen_summary="reviewed settings map",
                state_guess="settings page",
                regions=[],
                raw_response={
                    "model_json": {
                        "contract_version": "learn_deep_model_review_v1",
                        "status": "ready",
                        "screen_summary": "reviewed settings map",
                        "candidate_decisions": [
                            {
                                "candidate_id": "element_save",
                                "action": "update",
                                "label": "Save settings",
                                "expected_effect": "save current settings",
                                "reasons": ["model clarified action meaning"],
                            }
                        ],
                        "additions": [
                            {
                                "candidate_id": "model_advanced",
                                "label": "Advanced",
                                "role": "nav_text_action",
                                "bbox": {"x": 130, "y": 300, "w": 120, "h": 42},
                                "section_id": "main_content",
                                "expected_effect": "open advanced settings",
                                "confidence": 0.77,
                                "reasons": ["visible navigation text missing from draft"],
                            }
                        ],
                    }
                },
            )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)
    monkeypatch.setattr(vision_api.VisionProviderFactory, "load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr(vision_api.VisionProviderFactory, "create", lambda mode=None, config=None: DummyDeepProvider())

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo", learn_depth="deep"))

    assert response.success is True
    result = response.data["result"]
    assert result["path_graph_deep_review"]["model_review"]["status"] == "ready"
    assert result["path_graph_deep_review"]["summary"]["model_addition_count"] == 1
    assert result["path_graph_deep_review"]["summary"]["model_update_count"] == 1
    save = next(item for item in result["screen_map"]["candidates"] if item["candidate_id"] == "element_save")
    advanced = next(item for item in result["screen_map"]["candidates"] if item["candidate_id"] == "model_advanced")
    assert save["label"] == "Save settings"
    assert save["expected_effect"] == "save current settings"
    assert advanced["source"] == "learn_deep_model_review"
    assert result["path_graph_delta"]["summary"]["addition_count"] == 1
    assert result["element_memory_init_plan"]["entry_count"] == 2


def test_observe_screen_degrades_to_ocr_map_when_screen_reading_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png", "image_width": 900, "image_height": 700}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-degraded-trace.json")

    def fake_screen_reading(request):
        return APIResponse(
            success=False,
            message="Screen reading failed",
            data={"trace_path": "screen-reading-failed.json"},
            error=ErrorModel(code="screen_reading_failed", details="model returned invalid JSON"),
        )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[
                    OCRTextMatch(text="Google News", score=0.98, bbox=OCRBoundingBox(x=120, y=130, width=110, height=24)),
                    OCRTextMatch(text="For you", score=0.95, bbox=OCRBoundingBox(x=280, y=180, width=70, height=20)),
                ],
            )

    monkeypatch.setattr(vision_api, "screen_reading", fake_screen_reading)
    monkeypatch.setattr(vision_api, "ocr_service", DummyOCR())
    monkeypatch.setattr(
        vision_api.uia_provider,
        "snapshot_bound_window",
        lambda: {"provider": "windows_uia", "status": "unavailable", "control_count": 0, "controls": []},
    )

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="google", learn_depth="fast"))

    assert response.success is True
    result = response.data["result"]
    assert result["status"] == "degraded"
    assert result["degraded_reason"]["code"] == "screen_reading_failed"
    assert result["execution_path"]["degraded_observe_fallback_used"] is True
    assert result["screen_map"]["contract_version"] == "screen_map_v1"
    assert result["screen_map"]["summary"]["candidate_count"] >= 1
    assert any(item["text"] == "Google News" for item in result["texts"])


def test_locate_target_wraps_recognition_plan_without_clicking(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "locate-trace.json")

    def fake_recognition_plan(request):
        assert request.goal == "click home"
        assert request.operation_context.skill_id == "locate_element"
        assert request.metadata["ocr_anchors"]["max_anchors"] == "all"
        assert "Precision-localization stage only" in request.metadata["prompt_overrides"]["additional_rules"]
        assert 'text_inclusion_policy="exclude_text"' in request.metadata["prompt_overrides"]["additional_rules"]
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 10, "y": 20}},
                    "recommended_target": {"label": "home", "element": {"bbox": {"x": 4, "y": 14, "w": 12, "h": 12}, "click_point": {"x": 10, "y": 20}}},
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="click home",
            app_name="demo",
            metadata={
                "prompt_overrides": {
                    "additional_rules": (
                        'Precision-localization stage only. '
                        'For icon-only targets set text_inclusion_policy="exclude_text".'
                    )
                }
            },
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["contract_version"] == "target_location_v1"
    assert result["agent_mode"] == "execute"
    assert result["mode_contract_version"] == "execute_plan_v1"
    assert result["write_policy"] == {"path_graph": False, "element_memory": True, "trace": True}
    assert result["selected_click_point"] == {"x": 10, "y": 20}
    assert result["located_bbox"] == {"x": 4, "y": 14, "w": 12, "h": 12}
    assert result["located_point"] == {"x": 10, "y": 20}
    assert result["location_status"] == "pre_click_verified"
    assert result["operation_context"]["skill_id"] == "locate_element"
    assert result["operation_context"]["requires_gate"] is False
    assert result["execution_path"]["action_executed"] is False
    assert result["execution_path"]["located_coordinate_source"] == "recommended_target.element.click_point"
    assert result["execution_path"]["agent_must_call_for_click"] == "POST /action/execute_recognition_plan"


def test_locate_target_surfaces_review_candidate_from_rejected_list(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", None),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "locate-trace.json")

    def fake_recognition_plan(_request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": False, "selected_click_point": None},
                    "recommended_target": None,
                    "candidate_result": {
                        "candidates": [],
                        "rejected": [
                            {
                                "candidate_id": "candidate_review_target",
                                "label": "review target",
                                "element": {
                                    "bbox": {"x": 53, "y": 425, "w": 172, "h": 21},
                                    "click_point": {"x": 139, "y": 436},
                                    "interaction_policy": {
                                        "allowed": False,
                                        "zone_type": "precise_text_target",
                                        "priority": "review",
                                        "ad_risk": 0.0,
                                        "reasons": ["precision_text_grounding_requires_confirmation"],
                                    },
                                },
                            }
                        ],
                    },
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(VisionLocateTargetRequestModel(goal="select first acceleration", app_name="demo"))

    assert response.success is True
    result = response.data["result"]
    assert result["location_status"] == "requires_pre_click_confirmation"
    assert result["located_bbox"] == {"x": 53, "y": 425, "w": 172, "h": 21}
    assert result["located_point"] == {"x": 139, "y": 436}
    assert result["recommended_target"]["candidate_id"] == "candidate_review_target"
    assert result["execution_path"]["located_coordinate_source"] == "candidate_result.rejected[0]"


def test_locate_target_reviews_observe_path_map(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 220, "height": 120},
                    "texts": [
                        {
                            "id": "text_start",
                            "text": "Start",
                            "bbox": {"x": 12, "y": 22, "w": 42, "h": 20},
                            "confidence": 0.98,
                        }
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "sections": [
                            {
                                "section_id": "main_content",
                                "bbox": {"x": 0, "y": 0, "w": 220, "h": 120},
                            }
                        ],
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "old_start",
                                "label": "Start",
                                "bbox": {"x": 150, "y": 70, "w": 40, "h": 20},
                                "source": "screen_map",
                            },
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "other",
                                "label": "Other",
                                "bbox": {"x": 80, "y": 70, "w": 40, "h": 20},
                                "source": "screen_map",
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(image_path), None),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "locate-trace.json")

    def fake_recognition_plan(_request):
        return APIResponse(
            success=True,
            message="ok",
            data={
                "result": {
                    "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 32, "y": 32}},
                    "recommended_target": {
                        "candidate_id": "ai_start",
                        "label": "Start",
                        "element": {
                            "bbox": {"x": 12, "y": 22, "w": 42, "h": 20},
                            "click_point": {"x": 32, "y": 32},
                        },
                    },
                    "candidate_result": {"candidates": [], "rejected": []},
                    "execution_path": {"ocr_anchor_grounding_used": True},
                }
            },
            error=None,
        )

    monkeypatch.setattr(vision_api, "recognition_plan", fake_recognition_plan)

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="Start",
            app_name="demo",
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    review = response.data["result"]["path_map_review"]
    assert review["contract_version"] == "path_map_review_v1"
    assert review["status"] == "ready"
    assert review["summary"]["addition_count"] == 1
    assert review["summary"]["removal_count"] == 1
    assert review["additions"][0]["label"] == "Start"
    assert review["additions"][0]["source"] == "locate_path_review"
    assert review["additions"][0]["section_id"] == "main_content"
    assert review["removals"][0]["candidate_id"] == "old_start"


def test_learn_locate_returns_all_screen_map_targets_without_single_goal_plan(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (300, 180), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 300, "height": 180},
                    "texts": [
                        {
                            "id": "text_search",
                            "text": "Search",
                            "bbox": {"x": 12, "y": 22, "w": 60, "h": 24},
                            "confidence": 0.98,
                        }
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_google_news",
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "search_box",
                                "label": "搜索框",
                                "role": "text_input",
                                "bbox": {"x": 10, "y": 20, "w": 120, "h": 32},
                                "click_point": {"x": 70, "y": 36},
                                "section_id": "page_header",
                                "confidence": 0.84,
                            },
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "settings",
                                "label": "设置",
                                "role": "button",
                                "bbox": {"x": 240, "y": 18, "w": 32, "h": 32},
                                "section_id": "page_header",
                                "confidence": 0.7,
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(image_path), None),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "learn-locate-trace.json")
    monkeypatch.setattr(
        vision_api,
        "recognition_plan",
        lambda _request: (_ for _ in ()).throw(AssertionError("Learn all-target locate should not run single-goal recognition")),
    )

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="learn all visible controls",
            app_name="google",
            agent_mode="learn",
            learn_depth="fast",
            metadata={"learn_all_targets": True},
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["location_status"] == "learn_all_targets_ready"
    assert result["learn_all_targets"]["contract_version"] == "learn_all_target_locations_v1"
    assert result["learn_all_targets"]["status"] == "ready"
    assert result["learn_all_targets"]["target_count"] == 2
    assert result["learn_all_targets"]["validated_count"] == 2
    assert result["learn_all_targets"]["invalid_count"] == 0
    assert result["learn_all_targets"]["image_size"] == {"width": 300, "height": 180}
    assert Path(result["learn_all_targets"]["overlay_path"]).exists()
    assert result["coordinate_overlay_path"] == result["learn_all_targets"]["overlay_path"]
    assert result["learn_all_targets"]["targets"][0]["label"] == "搜索框"
    assert result["learn_all_targets"]["targets"][0]["click_point"] == {"x": 70, "y": 36}
    assert result["learn_all_targets"]["targets"][0]["coordinate_validation"]["status"] == "valid"
    assert result["learn_all_targets"]["targets"][0]["coordinate_validation"]["click_point_inside_bbox"] is True
    assert result["learn_all_targets"]["targets"][1]["click_point"] == {"x": 256, "y": 34}
    assert result["learn_all_targets"]["targets"][1]["coordinate_validation"]["status"] == "valid"
    assert result["path_map_review"]["summary"]["addition_count"] == 2
    assert result["path_map_review"]["summary"]["validated_count"] == 2
    assert result["path_map_review"]["summary"]["coordinate_overlay_path"] == result["coordinate_overlay_path"]
    assert result["execution_path"]["learn_all_targets_used"] is True
    assert result["recognition_plan"] is None


def test_learn_deep_locate_applies_model_add_update_remove_before_coordinate_overlay(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (360, 220), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 360, "height": 220},
                    "texts": [
                        {"id": "text_save", "text": "Save", "bbox": {"x": 10, "y": 20, "w": 60, "h": 24}},
                        {"id": "text_profile", "text": "Profile", "bbox": {"x": 160, "y": 80, "w": 80, "h": 30}},
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_settings",
                        "state_hint": "settings page",
                        "sections": [{"section_id": "main_content", "bbox": {"x": 0, "y": 0, "w": 360, "h": 220}}],
                        "candidates": [
                            {
                                "candidate_id": "save_btn",
                                "label": "Save",
                                "role": "button",
                                "bbox": {"x": 8, "y": 18, "w": 74, "h": 34},
                                "click_point": {"x": 45, "y": 35},
                                "section_id": "main_content",
                                "confidence": 0.7,
                            },
                            {
                                "candidate_id": "duplicate_noise",
                                "label": "Save",
                                "role": "button",
                                "bbox": {"x": 9, "y": 19, "w": 72, "h": 32},
                                "click_point": {"x": 45, "y": 35},
                                "section_id": "main_content",
                                "confidence": 0.4,
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class DummyLearnLocateProvider:
        def analyze(self, req):
            assert req.task == "learn_deep_review"
            context = req.metadata["learn_deep_review_context"]
            assert context["contract_version"] == "learn_locate_path_calibration_context_v1"
            assert context["required_review_actions"]["add_missing_nodes"] is True
            assert context["required_review_actions"]["resolve_non_containment_overlaps"] is True
            return VisionAnalyzeResponse(
                provider="dummy_learn_locate",
                image_size=ImageSize(width=360, height=220),
                screen_summary="settings path calibrated",
                state_guess="settings page",
                regions=[],
                raw_response={
                    "model_json": {
                        "contract_version": "learn_deep_model_review_v1",
                        "status": "ready",
                        "candidate_decisions": [
                            {
                                "candidate_id": "save_btn",
                                "action": "update",
                                "label": "Save settings",
                                "bbox": {"x": 12, "y": 20, "w": 90, "h": 36},
                                "click_point": {"x": 57, "y": 38},
                                "reasons": ["rename and tighten coordinates"],
                            },
                            {
                                "candidate_id": "duplicate_noise",
                                "action": "remove",
                                "reasons": ["duplicate save button"],
                            },
                        ],
                        "additions": [
                            {
                                "candidate_id": "profile_card",
                                "label": "Profile",
                                "role": "button",
                                "bbox": {"x": 150, "y": 72, "w": 110, "h": 44},
                                "click_point": {"x": 205, "y": 94},
                                "section_id": "main_content",
                                "expected_effect": "open profile settings",
                                "confidence": 0.82,
                            }
                        ],
                    }
                },
            )

    monkeypatch.setattr(vision_api, "_image_path_for_live_or_saved", lambda **_kwargs: (str(image_path), None))
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "learn-deep-locate-trace.json")
    monkeypatch.setattr(vision_api.VisionProviderFactory, "load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr(vision_api.VisionProviderFactory, "create", lambda mode=None, config=None: DummyLearnLocateProvider())
    monkeypatch.setattr(
        vision_api,
        "recognition_plan",
        lambda _request: (_ for _ in ()).throw(AssertionError("Learn deep all-target locate should not run single-goal recognition")),
    )

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="learn all visible controls",
            app_name="settings",
            agent_mode="learn",
            learn_depth="deep",
            metadata={"learn_all_targets": True},
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    result = response.data["result"]
    targets = result["learn_all_targets"]["targets"]
    assert result["learn_locate_model_review"]["status"] == "ready"
    assert result["path_map_review"]["summary"]["model_addition_count"] == 1
    assert result["path_map_review"]["summary"]["model_update_count"] == 1
    assert result["path_map_review"]["summary"]["model_removal_count"] == 1
    assert {target["candidate_id"] for target in targets} == {"save_btn", "profile_card"}
    save = next(target for target in targets if target["candidate_id"] == "save_btn")
    profile = next(target for target in targets if target["candidate_id"] == "profile_card")
    assert save["label"] == "Save settings"
    assert save["bbox"] == {"x": 12, "y": 20, "w": 90, "h": 36}
    assert save["click_point"] == {"x": 57, "y": 38}
    assert save["coordinate_validation"]["status"] == "valid"
    assert profile["coordinate_validation"]["status"] == "valid"
    assert Path(result["coordinate_overlay_path"]).exists()


def test_learn_deep_locate_skips_vista_point_model_review(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (320, 180), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 320, "height": 180},
                    "texts": [{"id": "text_start", "text": "Start", "bbox": {"x": 42, "y": 50, "w": 42, "h": 16}}],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_dashboard",
                        "state_hint": "dashboard",
                        "candidates": [
                            {
                                "candidate_id": "start_btn",
                                "label": "Start",
                                "role": "button",
                                "bbox": {"x": 20, "y": 40, "w": 100, "h": 36},
                                "click_point": {"x": 70, "y": 58},
                                "section_id": "main_content",
                                "confidence": 0.8,
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(vision_api, "_image_path_for_live_or_saved", lambda **_kwargs: (str(image_path), None))
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "learn-deep-vista-skip-trace.json")
    monkeypatch.setattr(
        vision_api.VisionProviderFactory,
        "load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr(
        vision_api.VisionProviderFactory,
        "create",
        lambda mode=None, config=None: (_ for _ in ()).throw(AssertionError("VISTA point model must not run Learn Deep full-map review")),
    )

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="learn all visible controls",
            app_name="dashboard",
            agent_mode="learn",
            learn_depth="deep",
            provider_mode="local_grounding",
            metadata={"learn_all_targets": True, "learn_vista_coordinate_validation": False},
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["learn_locate_model_review"]["status"] == "skipped"
    assert result["learn_locate_model_review"]["reason"] == "vista_point_grounding_not_suitable_for_full_map_review"
    assert result["learn_all_targets"]["target_count"] == 1
    assert result["learn_all_targets"]["targets"][0]["candidate_id"] == "start_btn"
    assert result["path_map_review"]["summary"]["model_addition_count"] == 0


def test_learn_deep_locate_validates_each_target_with_vista_point(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (320, 180), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 320, "height": 180},
                    "texts": [{"id": "text_start", "text": "Start", "bbox": {"x": 42, "y": 50, "w": 42, "h": 16}}],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_dashboard",
                        "state_hint": "dashboard",
                        "candidates": [
                            {
                                "candidate_id": "start_btn",
                                "label": "Start",
                                "role": "button",
                                "bbox": {"x": 20, "y": 40, "w": 100, "h": 36},
                                "click_point": {"x": 70, "y": 58},
                                "section_id": "main_content",
                                "confidence": 0.8,
                            },
                            {
                                "candidate_id": "help_btn",
                                "label": "Help",
                                "role": "button",
                                "bbox": {"x": 160, "y": 40, "w": 80, "h": 36},
                                "click_point": {"x": 200, "y": 58},
                                "section_id": "main_content",
                                "confidence": 0.7,
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_vista_point_prompt(**kwargs):
        calls.append(kwargs)
        is_start = "Start" in kwargs["prompt"]
        point = {"x": 72, "y": 59} if is_start else {"x": 290, "y": 150}
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[225, 328]" if is_start else "[906, 833]",
            "raw_response": {"choices": [{"message": {"content": "[225, 328]" if is_start else "[906, 833]"}}]},
            "parsed": {"contract_version": "vista_point_v1", "point": {"x": float(point["x"]), "y": float(point["y"]), "coordinate_space": "pixel"}},
            "point": point,
            "image_size": {"width": 320, "height": 180},
        }

    monkeypatch.setattr(vision_api, "_image_path_for_live_or_saved", lambda **_kwargs: (str(image_path), None))
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "learn-deep-vista-targets-trace.json")
    monkeypatch.setattr(
        vision_api.VisionProviderFactory,
        "load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista_point_prompt)

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="learn all visible controls",
            app_name="dashboard",
            agent_mode="learn",
            learn_depth="deep",
            provider_mode="local_grounding",
            metadata={"learn_all_targets": True},
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    result = response.data["result"]
    targets = result["learn_all_targets"]["targets"]
    assert len(calls) == 2
    assert result["learn_all_targets"]["vista_coordinate_validation"]["validated_count"] == 2
    assert result["learn_all_targets"]["vista_coordinate_validation"]["inside_count"] == 1
    assert result["learn_all_targets"]["vista_coordinate_validation"]["outside_count"] == 1
    assert result["path_map_review"]["summary"]["vista_validated_count"] == 2
    start = next(target for target in targets if target["candidate_id"] == "start_btn")
    help_target = next(target for target in targets if target["candidate_id"] == "help_btn")
    assert start["click_point"] == {"x": 72, "y": 59}
    assert start["coordinate_source"] == "precise_locator_v1"
    assert start["vista_coordinate_validation"]["precise_locator_evidence"]["dry_run_gate"]["status"] == "locate_review_pass"
    assert start["vista_coordinate_validation"]["precise_locator_evidence"]["click_performed"] is False
    assert start["vista_coordinate_validation"]["status"] == "valid"
    assert start["vista_coordinate_validation"]["model_io"]["raw_text"] == "[225, 328]"
    assert help_target["click_point"] == {"x": 200, "y": 58}
    assert help_target["vista_coordinate_validation"]["status"] == "needs_review"


def test_learn_deep_locate_calibrates_stage2_numbered_review_items(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (320, 200), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 320, "height": 200},
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    two_stage_report = tmp_path / "two_stage_report.json"
    two_stage_report.write_text(
        __import__("json").dumps(
            {
                "contract_version": "learn_two_stage_understanding_v1",
                "source_image_path": str(image_path),
                "stage2_numbering": {
                    "regions": [
                        {
                            "region_id": "structure_region_main_content",
                            "label": "Main content",
                            "numbered_items": [
                                {
                                    "item_id": "generic_control",
                                    "number": "1.0",
                                    "label": "control 1",
                                    "role": "control",
                                    "bbox": {"x": 20, "y": 30, "w": 48, "h": 36},
                                    "review_only": True,
                                    "execute_binding_enabled": False,
                                },
                                {
                                    "item_id": "search_button",
                                    "number": "1.1",
                                    "label": "Search",
                                    "role": "button",
                                    "bbox": {"x": 220, "y": 30, "w": 70, "h": 36},
                                    "review_only": True,
                                    "execute_binding_enabled": False,
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_vista(**kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[797, 240]",
            "raw_response": {"choices": [{"message": {"content": "[797, 240]"}}]},
            "parsed": {"contract_version": "vista_point_v1", "point": {"x": 255.0, "y": 48.0, "coordinate_space": "pixel"}},
            "point": {"x": 255, "y": 48},
            "image_size": {"width": 320, "height": 200},
        }

    monkeypatch.setattr(vision_api, "_image_path_for_live_or_saved", lambda **_kwargs: (str(image_path), None))
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "stage2-calibration-trace.json")
    monkeypatch.setattr(
        vision_api.VisionProviderFactory,
        "load_config",
        lambda: {
            "vision": {
                "timeout_seconds": 60,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="calibrate numbered regions",
            app_name="demo",
            agent_mode="learn",
            learn_depth="deep",
            provider_mode="local_grounding",
            metadata={
                "learn_all_targets": True,
                "learn_locate_model_review": False,
                "two_stage_report_path": str(two_stage_report),
                "learn_vista_coordinate_validation": {"max_targets": 1, "stop_on_failure": False},
            },
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    learned = response.data["result"]["learn_all_targets"]
    assert len(calls) == 1
    assert learned["target_count"] == 0
    assert learned["calibration_target_count"] == 2
    assert learned["calibration_targets"][0]["candidate_id"].endswith("search_button")
    assert learned["calibration_targets"][0]["calibration_only"] is True
    assert learned["calibration_targets"][0]["execute_binding_enabled"] is False
    assert learned["calibration_targets"][0]["vista_coordinate_validation"]["status"] == "valid"
    assert learned["overlay"]["model_validated_calibration_count"] == 1
    assert learned["overlay"]["pending_calibration_count"] == 1
    assert response.data["result"]["execution_path"]["action_executed"] is False


def test_learn_vista_validation_can_cover_every_calibration_target(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": f"candidate_{index}",
            "label": f"Target {index}",
            "role": "review_only",
            "bbox": {"x": 20 + index * 60, "y": 40, "w": 40, "h": 40},
            "click_point": {"x": 40 + index * 60, "y": 60},
            "locator_prompt": f"Locate exact numbered target {index} inside the main region",
        }
        for index in range(3)
    ]
    long_prompt = "Locate exact numbered target 0 inside the main region. " + ("Keep all sibling context. " * 8)
    targets[0]["locator_prompt"] = long_prompt
    calls: list[str] = []

    def fake_vista(**kwargs):
        calls.append(kwargs["prompt"])
        index = len(calls) - 1
        point = {"x": 40 + index * 60, "y": 60}
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
                "raw_text": __import__("json").dumps([point["x"], point["y"]]),
            "raw_response": {},
            "parsed": {"contract_version": "vista_point_v1", "point": point},
            "point": point,
            "image_size": {"width": 320, "height": 200},
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "max_targets": 1,
            "validate_all_targets": True,
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert len(calls) == 3
    assert calls[0] == long_prompt.strip()
    assert summary["validated_count"] == 3
    assert summary["skipped_count"] == 0
    assert summary["validation_scope"] == "all_targets"


def test_learn_vista_validation_options_preserve_all_target_scope() -> None:
    request = VisionLocateTargetRequestModel(
        goal="calibrate every numbered region",
        agent_mode="learn",
        learn_depth="deep",
        metadata={
            "learn_vista_coordinate_validation": {
                "enabled": True,
                "max_targets": "all",
                "stop_on_failure": False,
            }
        },
    )

    options = vision_api._learn_vista_coordinate_validation_options(
        request,
        {"runtime": "transformers", "output_contract": "vista_point_v1"},
    )

    assert options["validate_all_targets"] is True
    assert options["stop_on_failure"] is False
    assert options["use_numbered_overlay"] is False


def test_learn_vista_validation_options_preserve_revision_bound_batch_resume() -> None:
    prior_result = {
        "contract_version": "learn_vista_target_coordinate_validation_v1",
        "candidate_id": "stage2:revision-1:item-1",
        "status": "valid",
    }
    request = VisionLocateTargetRequestModel(
        goal="calibrate reviewed controls",
        agent_mode="learn",
        learn_depth="deep",
        metadata={
            "final_numbering_revision": "revision-1",
            "learn_vista_coordinate_validation": {
                "enabled": True,
                "max_targets": "all",
                "batch_size": 2,
                "resume_results": [prior_result],
                "resume_revision": "revision-1",
                "stop_on_failure": False,
            },
        },
    )

    options = vision_api._learn_vista_coordinate_validation_options(
        request,
        {"runtime": "transformers", "output_contract": "vista_point_v1"},
    )

    assert options["batch_size"] == 2
    assert options["resume_results"] == [prior_result]
    assert options["resume_revision"] == "revision-1"
    assert options["expected_final_numbering_revision"] == "revision-1"


def test_learn_vista_validation_batches_and_resumes_without_repeating_candidates(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": f"stage2:revision-1:item-{index}",
            "final_numbering_revision": "revision-1",
            "label": f"Target {index}",
            "role": "button",
            "bbox": {"x": 20 + index * 70, "y": 40, "w": 50, "h": 40},
            "click_point": {"x": 45 + index * 70, "y": 60},
        }
        for index in range(3)
    ]
    calls: list[str] = []

    def fake_vista(**kwargs):
        calls.append(kwargs["goal"])
        index = len(calls) - 1
        point = {"x": 45 + index * 70, "y": 60}
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": __import__("json").dumps([point["x"], point["y"]]),
            "raw_response": {},
            "parsed": {"contract_version": "vista_point_v1", "point": point},
            "point": point,
            "image_size": {"width": 320, "height": 200},
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)
    first = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 2,
            "resume_results": [],
            "resume_revision": "revision-1",
            "expected_final_numbering_revision": "revision-1",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert len(calls) == 2
    assert first["status"] == "partial_resumable"
    assert first["batch"]["attempted_count"] == 2
    assert first["batch"]["remaining_candidate_ids"] == ["stage2:revision-1:item-2"]
    assert first["batch"]["resumable"] is True

    second = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 2,
            "resume_results": first["results"],
            "resume_revision": "revision-1",
            "expected_final_numbering_revision": "revision-1",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert len(calls) == 3
    assert calls[-1] == "Click Target 2"
    assert second["status"] == "ready"
    assert second["validated_count"] == 3
    assert second["batch"]["already_completed_count"] == 2
    assert second["batch"]["remaining_count"] == 0
    assert second["batch"]["resumable"] is False


def test_learn_vista_validation_rejects_unknown_resume_candidate_without_model_call(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": "stage2:revision-1:item-1",
            "final_numbering_revision": "revision-1",
            "label": "Target",
            "role": "button",
            "bbox": {"x": 20, "y": 40, "w": 50, "h": 40},
            "click_point": {"x": 45, "y": 60},
        }
    ]

    def unexpected_call(**_kwargs):
        raise AssertionError("model must not run for stale resume evidence")

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", unexpected_call)
    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 1,
            "resume_results": [
                {
                    "candidate_id": "stage2:old-revision:item-9",
                    "status": "valid",
                }
            ],
            "resume_revision": "revision-1",
            "expected_final_numbering_revision": "revision-1",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert summary["status"] == "blocked"
    assert summary["abort_reason"] == "resume_candidate_not_found"
    assert summary["validated_count"] == 0
    assert summary["batch"]["resumable"] is False


def test_learn_vista_timeout_is_partial_resumable_when_continue_requested(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": f"target-{index}",
            "label": f"Target {index}",
            "role": "button",
            "bbox": {"x": 20 + index * 70, "y": 40, "w": 50, "h": 40},
            "click_point": {"x": 45 + index * 70, "y": 60},
        }
        for index in range(3)
    ]
    calls = []

    def timeout_vista(**kwargs):
        calls.append(kwargs["goal"])
        raise TimeoutError("timed out")

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", timeout_vista)
    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 2,
            "resume_results": [],
            "expected_final_numbering_revision": "revision-timeout",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert calls == ["Click Target 0"]
    assert summary["status"] == "partial_resumable"
    assert summary["abort_reason"] == "request_timeout"
    assert summary["failed_count"] == 1
    assert summary["batch"]["attempted_candidate_ids"] == ["target-0"]
    assert summary["batch"]["completed_candidate_ids"] == []
    assert summary["batch"]["retryable_failure_candidate_ids"] == ["target-0"]
    assert summary["batch"]["remaining_candidate_ids"] == ["target-0", "target-1", "target-2"]
    assert summary["batch"]["resumable"] is True
    assert summary["results"][0]["final_numbering_revision"] == "revision-timeout"


def test_learn_vista_model_busy_is_recoverable_without_marking_candidate_completed(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": f"target-{index}",
            "label": f"Target {index}",
            "role": "button",
            "bbox": {"x": 20 + index * 70, "y": 40, "w": 50, "h": 40},
            "click_point": {"x": 45 + index * 70, "y": 60},
        }
        for index in range(3)
    ]
    calls = []

    def busy_vista(**kwargs):
        calls.append(kwargs)
        raise RuntimeError(
            'local vision endpoint returned HTTP 503: {"error":{"type":"model_busy"}}'
        )

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", busy_vista)

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={"enabled": True, "validate_all_targets": True, "stop_on_failure": False},
        timeout_seconds=12,
    )

    assert len(calls) == 1
    assert summary["status"] == "partial_resumable"
    assert summary["batch_aborted"] is True
    assert summary["abort_reason"] == "model_busy"
    assert summary["failed_count"] == 1
    assert summary["skipped_count"] == 3
    assert summary["batch"]["completed_candidate_ids"] == []
    assert summary["batch"]["retryable_failure_candidate_ids"] == ["target-0"]
    assert summary["batch"]["remaining_candidate_ids"] == ["target-0", "target-1", "target-2"]
    assert summary["batch"]["resumable"] is True
    assert targets[0]["vista_coordinate_validation"]["failure_category"] == "model_busy"


def test_learn_vista_resume_retries_transient_failure_instead_of_skipping_candidate(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    targets = [
        {
            "candidate_id": "target-0",
            "label": "Target 0",
            "role": "button",
            "bbox": {"x": 20, "y": 40, "w": 50, "h": 40},
            "click_point": {"x": 45, "y": 60},
        }
    ]
    calls = []

    def busy_then_ready(**kwargs):
        calls.append(kwargs["goal"])
        if len(calls) == 1:
            raise RuntimeError(
                'local vision endpoint returned HTTP 503: {"error":{"type":"model_busy"}}'
            )
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[45, 60]",
            "raw_response": {},
            "parsed": {"contract_version": "vista_point_v1", "point": {"x": 45, "y": 60}},
            "point": {"x": 45, "y": 60},
            "image_size": {"width": 320, "height": 200},
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", busy_then_ready)
    first = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 1,
            "resume_results": [],
            "resume_revision": "revision-retry",
            "expected_final_numbering_revision": "revision-retry",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )
    second = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        targets,
        image_path=str(image_path),
        image_size={"width": 320, "height": 200},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "validate_all_targets": True,
            "batch_size": 1,
            "resume_results": first["results"],
            "resume_revision": "revision-retry",
            "expected_final_numbering_revision": "revision-retry",
            "stop_on_failure": False,
        },
        timeout_seconds=12,
    )

    assert calls == ["Click Target 0", "Click Target 0"]
    assert second["status"] == "ready"
    assert second["batch"]["completed_candidate_ids"] == ["target-0"]
    assert second["batch"]["remaining_candidate_ids"] == []
    assert len(second["results"]) == 1
    assert second["results"][0]["status"] != "failed"


def test_learn_all_targets_location_status_reports_blocked_vista_calibration() -> None:
    result = {
        "target_count": 0,
        "invalid_count": 0,
        "review_box_count": 0,
        "calibration_target_count": 4,
        "vista_coordinate_validation": {
            "status": "blocked",
            "batch_aborted": True,
            "abort_reason": "request_timeout",
        },
    }

    assert vision_api._learn_all_targets_location_status(result) == "learn_calibration_blocked"


def test_learn_all_targets_location_status_reports_resumable_vista_calibration() -> None:
    result = {
        "target_count": 0,
        "invalid_count": 0,
        "review_box_count": 0,
        "calibration_target_count": 4,
        "vista_coordinate_validation": {
            "status": "partial_resumable",
            "batch_aborted": True,
            "abort_reason": "request_timeout",
            "batch": {"resumable": True, "remaining_count": 3},
        },
    }

    assert vision_api._learn_all_targets_location_status(result) == "learn_calibration_partial"


def test_learn_all_targets_builder_preserves_resumable_calibration_status(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "resumable_calibration.png"
    vision_api.Image.new("RGB", (320, 200), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {"image_size": {"width": 320, "height": 200}},
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "resumable_calibration",
            "candidates": [],
            "calibration_candidates": [
                {
                    "candidate_id": "target-0",
                    "label": "Search",
                    "role": "button",
                    "bbox": {"x": 20, "y": 30, "w": 80, "h": 30},
                    "click_point": {"x": 60, "y": 45},
                    "source": "two_stage_parent_group",
                }
            ],
            "two_stage_calibration_authoritative": True,
        },
    }

    def fake_apply(*args, **kwargs):
        return {
            "contract_version": "learn_vista_coordinate_validation_summary_v1",
            "status": "partial_resumable",
            "batch_aborted": True,
            "abort_reason": "request_timeout",
            "batch": {"resumable": True, "remaining_count": 1},
            "results": [],
        }

    monkeypatch.setattr(vision_api, "_apply_vista_coordinate_validation_to_learn_targets", fake_apply)

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={
            "local_config": {"profile_id": "vista-test"},
            "options": {"enabled": True},
            "timeout_seconds": 30,
        },
    )

    assert result["status"] == "partial"
    assert vision_api._learn_all_targets_location_status(result) == "learn_calibration_partial"


def test_two_stage_calibration_candidates_keep_region_and_child_locator_context(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    numbered_overlay_path = tmp_path / ("long-numbered-overlay-directory-" * 6) / "numbered.png"
    numbered_overlay_path.parent.mkdir(parents=True)
    Image.new("RGB", (320, 200), color="gray").save(numbered_overlay_path)
    assert len(str(numbered_overlay_path)) > 160
    report_path = tmp_path / "two_stage.json"
    report_path.write_text(
        __import__("json").dumps(
            {
                "source_image_path": str(image_path),
                "surface_adapter_decision": {
                    "contract_version": "learning_surface_adapter_decision_v1",
                    "adapter_id": "browser",
                    "status": "selected_from_visible_evidence",
                    "excluded_zones": ["browser_chrome"],
                    "excluded_item_ids": ["address_bar"],
                    "final_geometry_allowed": False,
                },
                "surface_adapter_application": {
                    "contract_version": "learning_surface_adapter_application_v1",
                    "adapter_id": "browser",
                    "excluded_item_ids": ["address_bar"],
                    "fixed_height_boundary_used": False,
                    "final_geometry_changed": False,
                },
                "fusion": {"compiled_overlay_path": str(numbered_overlay_path)},
                "stage2_numbering": {
                    "regions": [
                        {
                            "region_id": "structure_region_main",
                            "label": "Main content",
                            "bbox": {"x": 10, "y": 20, "w": 300, "h": 170},
                            "numbered_items": [
                                {
                                    "item_id": "card_1",
                                    "number": "3.4",
                                    "label": "Music",
                                    "role": "media_card",
                                    "bbox": {"x": 20, "y": 30, "w": 120, "h": 140},
                                    "children": [
                                        {"label": "专属心情好歌"},
                                        {"label": "乐享悠闲"},
                                    ],
                                },
                                {
                                    "item_id": "card_2",
                                    "number": "3.5",
                                    "label": "Music",
                                    "role": "media_card",
                                    "bbox": {"x": 160, "y": 30, "w": 120, "h": 140},
                                    "children": [{"label": "专属推荐"}],
                                },
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    attached = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
    )

    candidates = attached["screen_map"]["calibration_candidates"]
    first = next(item for item in candidates if item["candidate_id"].endswith("card_1"))
    second = next(item for item in candidates if item["candidate_id"].endswith("card_2"))
    assert first["locator_context"]["region_label"] == "Main content"
    assert first["locator_context"]["region_bbox"] == {"x": 10, "y": 20, "w": 300, "h": 170}
    assert first["numbered_overlay_path"] == str(numbered_overlay_path)
    assert first["locator_context"]["child_labels"] == ["专属心情好歌", "乐享悠闲"]
    assert "Main content" in first["locator_prompt"]
    assert "3.4" in first["locator_prompt"]
    assert "专属心情好歌" in first["locator_prompt"]
    assert "乐享悠闲" in first["locator_prompt"]
    assert first["locator_prompt"] != second["locator_prompt"]
    assert attached["screen_map"]["surface_adapter_decision"]["adapter_id"] == "browser"
    assert attached["screen_map"]["surface_adapter_application"]["fixed_height_boundary_used"] is False
    converted = vision_api._screen_map_calibration_candidate_to_target(first, 0)
    assert converted is not None
    assert converted["locator_prompt"] == first["locator_prompt"]
    assert converted["locator_context"] == first["locator_context"]
    assert converted["numbered_overlay_path"] == str(numbered_overlay_path)


def test_two_stage_calibration_candidates_exclude_child_evidence_items(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    report_path = tmp_path / "two_stage.json"
    report_path.write_text(
        __import__("json").dumps(
            {
                "source_image_path": str(image_path),
                "stage2_numbering": {
                    "regions": [
                        {
                            "region_id": "structure_region_main",
                            "label": "Main content",
                            "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
                            "subregion_groups": [
                                {
                                    "group_id": "tile_card_row_1",
                                    "role": "tile_card_parent",
                                    "bbox": {"x": 20, "y": 30, "w": 130, "h": 80},
                                    "member_item_ids": ["card_1", "card_1_title"],
                                },
                                {
                                    "group_id": "text_card_parent_1",
                                    "role": "tile_card_parent",
                                    "label": "Applications card",
                                    "bbox": {"x": 170, "y": 30, "w": 130, "h": 80},
                                    "member_item_ids": ["text_card_title", "text_card_subtitle"],
                                },
                            ],
                            "numbered_items": [
                                {
                                    "item_id": "card_1",
                                    "number": "2.1",
                                    "label": "Settings card",
                                    "role": "tile_card",
                                    "bbox": {"x": 20, "y": 30, "w": 130, "h": 80},
                                    "children": [{"label": "System"}, {"label": "Display and sound"}],
                                },
                                {
                                    "item_id": "card_1_title",
                                    "number": "2.2",
                                    "label": "System",
                                    "role": "text",
                                    "bbox": {"x": 55, "y": 42, "w": 48, "h": 18},
                                },
                                {
                                    "item_id": "text_card_title",
                                    "number": "2.3",
                                    "label": "Applications",
                                    "role": "text",
                                    "bbox": {"x": 185, "y": 42, "w": 80, "h": 18},
                                },
                                {
                                    "item_id": "text_card_subtitle",
                                    "number": "2.4",
                                    "label": "Uninstall and defaults",
                                    "role": "text",
                                    "bbox": {"x": 185, "y": 66, "w": 100, "h": 18},
                                },
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    attached = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
    )

    candidates = attached["screen_map"]["calibration_candidates"]
    assert {item["candidate_id"] for item in candidates} == {
        "stage2:structure_region_main:card_1",
        "stage2:structure_region_main:text_card_parent_1",
    }
    visual_card = next(item for item in candidates if item["candidate_id"].endswith(":card_1"))
    assert visual_card["locator_context"]["child_labels"] == ["System", "Display and sound"]
    source = attached["two_stage_calibration_source"]
    assert source["candidate_count"] == 2
    assert source["suppressed_child_evidence_count"] == 3


def test_two_stage_calibration_candidates_use_merged_parent_instead_of_card_fragments(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (420, 260), color="white").save(image_path)
    report_path = tmp_path / "two_stage.json"
    report_path.write_text(
        __import__("json").dumps(
            {
                "source_image_path": str(image_path),
                "stage2_numbering": {
                    "regions": [
                        {
                            "region_id": "structure_region_main",
                            "label": "Main content",
                            "bbox": {"x": 0, "y": 0, "w": 420, "h": 260},
                            "subregion_groups": [
                                {
                                    "group_id": "merged_info_card",
                                    "role": "tile_card_parent",
                                    "label": "Get Started",
                                    "bbox": {"x": 40, "y": 50, "w": 160, "h": 150},
                                    "member_item_ids": ["card_top", "text_top", "card_bottom", "text_bottom"],
                                    "adjacent_fragment_merged": True,
                                    "merged_adjacent_fragment_group_ids": ["card_bottom_parent"],
                                }
                            ],
                            "numbered_items": [
                                {
                                    "item_id": "card_top",
                                    "number": "2.1",
                                    "label": "Whether you are new",
                                    "role": "tile_card",
                                    "bbox": {"x": 40, "y": 50, "w": 150, "h": 80},
                                },
                                {
                                    "item_id": "text_top",
                                    "number": "2.2",
                                    "label": "Get Started",
                                    "role": "text",
                                    "bbox": {"x": 52, "y": 62, "w": 100, "h": 20},
                                },
                                {
                                    "item_id": "card_bottom",
                                    "number": "2.3",
                                    "label": "Beginner guide",
                                    "role": "tile_card",
                                    "bbox": {"x": 40, "y": 126, "w": 160, "h": 74},
                                },
                                {
                                    "item_id": "text_bottom",
                                    "number": "2.4",
                                    "label": "Start with our guide",
                                    "role": "text",
                                    "bbox": {"x": 52, "y": 158, "w": 120, "h": 20},
                                },
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    attached = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
    )

    candidates = attached["screen_map"]["calibration_candidates"]
    assert [item["candidate_id"] for item in candidates] == [
        "stage2:structure_region_main:merged_info_card"
    ]
    assert candidates[0]["bbox"] == {"x": 40, "y": 50, "w": 160, "h": 150}
    assert attached["two_stage_calibration_source"]["suppressed_child_evidence_count"] == 4


def test_finalized_stage2_calibration_uses_revision_bound_ids_and_rejects_stale_revision(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    report_path = tmp_path / "final_stage2.json"
    report_path.write_text(
        __import__("json").dumps(
            {
                "source_image_path": str(image_path),
                "model_review_repair": {
                    "calibration_permission": True,
                    "final_numbering_revision": "revision-123",
                    "integrity_gate": {"passed": True, "failure_categories": []},
                },
                "stage2_numbering": {
                    "graph_revision": "revision-123",
                    "final_numbering": {
                        "revision": "revision-123",
                        "source_ids_are_calibration_ids": False,
                    },
                    "regions": [
                        {
                            "region_id": "provisional_region",
                            "final_region_id": "final-region:revision:0001",
                            "label": "Main content",
                            "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
                            "subregion_groups": [],
                            "numbered_items": [
                                {
                                    "item_id": "provisional_item",
                                    "final_item_id": "final-item:revision:00001",
                                    "number": "1.1",
                                    "label": "Open",
                                    "role": "control",
                                    "bbox": {"x": 20, "y": 30, "w": 60, "h": 30},
                                }
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    attached = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
        expected_final_numbering_revision="revision-123",
    )

    candidate = attached["screen_map"]["calibration_candidates"][0]
    assert candidate["candidate_id"] == "stage2:final-region:revision:0001:final-item:revision:00001"
    assert candidate["source_region_id"] == "provisional_region"
    assert candidate["source_item_id"] == "provisional_item"
    assert candidate["final_numbering_revision"] == "revision-123"
    assert attached["two_stage_calibration_source"]["status"] == "ready"

    stale = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
        expected_final_numbering_revision="different-revision",
    )
    assert stale["two_stage_calibration_source"]["status"] == "stale_graph"
    assert stale["screen_map"].get("calibration_candidates", []) == []


def test_finalized_atomic_control_parent_is_one_revision_bound_calibration_target(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (420, 260), color="white").save(image_path)
    overlay_path = tmp_path / "reviewed-overlay.png"
    Image.new("RGB", (420, 260), color="gray").save(overlay_path)
    report_path = tmp_path / "final_stage2.json"
    report_path.write_text(
        __import__("json").dumps(
            {
                "source_image_path": str(image_path),
                "fusion": {"compiled_overlay_path": str(overlay_path)},
                "model_review_repair": {
                    "calibration_permission": True,
                    "final_numbering_revision": "revision-control-parent",
                    "integrity_gate": {"passed": True, "failure_categories": []},
                },
                "stage2_numbering": {
                    "graph_revision": "revision-control-parent",
                    "final_numbering": {
                        "revision": "revision-control-parent",
                        "source_ids_are_calibration_ids": False,
                    },
                    "regions": [
                        {
                            "region_id": "conversation_list",
                            "final_region_id": "final-region:conversation-list",
                            "label": "Conversation list",
                            "bbox": {"x": 20, "y": 20, "w": 300, "h": 220},
                            "subregion_groups": [],
                            "numbered_items": [
                                {
                                    "item_id": "avatar_1",
                                    "number": "2.1",
                                    "label": "Avatar",
                                    "role": "icon",
                                    "bbox": {"x": 35, "y": 48, "w": 42, "h": 42},
                                },
                                {
                                    "item_id": "title_1",
                                    "number": "2.2",
                                    "label": "Project discussion",
                                    "role": "text",
                                    "bbox": {"x": 88, "y": 48, "w": 140, "h": 20},
                                },
                                {
                                    "item_id": "preview_1",
                                    "number": "2.3",
                                    "label": "Latest message preview",
                                    "role": "text",
                                    "bbox": {"x": 88, "y": 70, "w": 180, "h": 18},
                                },
                            ],
                            "control_parents": [
                                {
                                    "object_id": "control_parent_row_1",
                                    "final_control_parent_id": "final-control-parent:row-1",
                                    "label": "Project discussion",
                                    "role": "atomic_control_parent",
                                    "bbox": {"x": 35, "y": 44, "w": 245, "h": 50},
                                    "member_object_ids": ["avatar_1", "title_1", "preview_1"],
                                    "source": "repeated_visual_anchor_with_row_evidence",
                                }
                            ],
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    attached = vision_api._attach_two_stage_calibration_candidates(
        {"screen_map": {"candidates": []}},
        report_path_value=str(report_path),
        image_path=str(image_path),
        expected_final_numbering_revision="revision-control-parent",
    )

    candidates = attached["screen_map"]["calibration_candidates"]
    assert [candidate["candidate_id"] for candidate in candidates] == [
        "stage2:final-region:conversation-list:final-control-parent:row-1"
    ]
    candidate = candidates[0]
    assert candidate["source_item_id"] == "control_parent_row_1"
    assert candidate["final_numbering_revision"] == "revision-control-parent"
    assert candidate["bbox"] == {"x": 35, "y": 44, "w": 245, "h": 50}
    assert candidate["calibration_target_kind"] == "atomic_control_parent"
    assert candidate["member_source_item_ids"] == ["avatar_1", "title_1", "preview_1"]
    assert candidate["locator_context"]["calibration_target_kind"] == "atomic_control_parent"
    assert candidate["locator_context"]["child_labels"] == ["Avatar", "Latest message preview"]
    assert "Project discussion" in candidate["locator_prompt"]
    assert "Latest message preview" in candidate["locator_prompt"]
    source = attached["two_stage_calibration_source"]
    assert source["status"] == "ready"
    assert source["candidate_count"] == 1
    assert source["suppressed_child_evidence_count"] == 3
    assert {
        item["reason"] for item in source["suppressed_child_evidence"]
    } == {"atomic_control_parent_replaces_member_fragment_calibration"}
    assert source["numbered_overlay_path"] == str(overlay_path)


def test_learn_vista_validation_defaults_to_raw_parent_region_roi_and_restores_full_screen_point(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 240), color="white").save(image_path)
    numbered_overlay_path = tmp_path / "numbered.png"
    Image.new("RGB", (400, 240), color="gray").save(numbered_overlay_path)
    target = {
        "candidate_id": "top_control_2",
        "label": "Play",
        "role": "control",
        "bbox": {"x": 140, "y": 30, "w": 40, "h": 30},
        "click_point": {"x": 160, "y": 45},
        "locator_prompt": "Locate the exact Play control in the top bar.",
        "numbered_overlay_path": str(numbered_overlay_path),
        "locator_context": {
            "region_label": "Top bar",
            "region_bbox": {"x": 80, "y": 10, "w": 260, "h": 70},
        },
    }
    calls: list[dict] = []

    def fake_vista(**kwargs):
        calls.append(kwargs)
        transform = kwargs["coordinate_transform"]
        assert kwargs["image_size"].to_dict() == {"width": 280, "height": 90}
        assert kwargs["original_image_size"].to_dict() == {"width": 400, "height": 240}
        assert transform["origin_original"] == {"x": 70, "y": 0}
        assert kwargs["image_preprocess"]["numbered_overlay_source_path"] == ""
        assert kwargs["image_preprocess"]["original_image_path"] == str(image_path)
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(kwargs["image_path"]),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[321, 500]",
            "raw_response": {},
            "parsed": {"contract_version": "vista_point_v1"},
            "processed_point": {"x": 90, "y": 45},
            "point": {"x": 160, "y": 45},
            "image_size": {"width": 400, "height": 240},
            "inference_image_size": {"width": 280, "height": 90},
            "coordinate_transform": transform,
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 400, "height": 240},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={"enabled": True, "max_targets": 1, "stop_on_failure": False, "region_roi_padding": 10},
        timeout_seconds=12,
    )

    assert len(calls) == 1
    assert calls[0]["image_path"] != image_path
    assert summary["inside_count"] == 1
    assert target["click_point"] == {"x": 160, "y": 45}
    validation = target["vista_coordinate_validation"]
    assert validation["inference_scope"] == "parent_region_roi"
    assert validation["inference_visual_source"] == "source_screenshot"
    assert validation["coordinate_transform"]["origin_original"] == {"x": 70, "y": 0}
    assert validation["precise_locator_evidence"]["contract_version"] == "precise_locator_evidence_v1"
    assert validation["precise_locator_evidence"]["click_performed"] is False


def test_learn_vista_validation_uses_numbered_overlay_only_when_debug_option_is_explicit(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (300, 180), color="white").save(image_path)
    numbered_overlay_path = tmp_path / "numbered.png"
    Image.new("RGB", (300, 180), color="gray").save(numbered_overlay_path)
    target = {
        "candidate_id": "search",
        "label": "Search",
        "role": "button",
        "bbox": {"x": 20, "y": 20, "w": 80, "h": 40},
        "click_point": {"x": 60, "y": 40},
        "numbered_overlay_path": str(numbered_overlay_path),
        "locator_context": {
            "region_label": "Header",
            "region_bbox": {"x": 0, "y": 0, "w": 300, "h": 90},
        },
    }

    def fake_vista(**kwargs):
        assert kwargs["image_preprocess"]["numbered_overlay_source_path"] == str(numbered_overlay_path)
        crop = kwargs["image_preprocess"]["crop_bounds_original"]
        assert crop["w"] < 300
        assert crop["x"] <= target["bbox"]["x"]
        assert crop["x"] + crop["w"] >= target["bbox"]["x"] + target["bbox"]["w"]
        return {
            "point": {"x": 60, "y": 40},
            "coordinate_transform": kwargs["coordinate_transform"],
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 300, "height": 180},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "max_targets": 1,
            "stop_on_failure": False,
            "use_numbered_overlay": True,
        },
        timeout_seconds=12,
    )

    validation = target["vista_coordinate_validation"]
    assert validation["inference_visual_source"] == "numbered_overlay"
    assert validation["precise_locator_evidence"]["numbered_overlay_used"] is True


def test_learn_vista_dense_list_row_validation_uses_compact_column_roi(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "documentation_portal.png"
    Image.new("RGB", (2521, 1300), color="white").save(image_path)
    numbered_overlay_path = tmp_path / "documentation_portal_numbered.png"
    Image.new("RGB", (2521, 1300), color="white").save(numbered_overlay_path)
    target = {
        "candidate_id": "list_row_1",
        "label": "2026-06-29 Python Packaging Council Inaugural Election Dates",
        "role": "list_row",
        "bbox": {"x": 698, "y": 962, "w": 428, "h": 22},
        "click_point": {"x": 912, "y": 973},
        "locator_prompt": "Locate the exact list row in the left column.",
        "numbered_overlay_path": str(numbered_overlay_path),
        "locator_context": {
            "region_label": "Primary Area",
            "region_bbox": {"x": 0, "y": 210, "w": 2521, "h": 1090},
        },
    }

    def fake_vista(**kwargs):
        crop = kwargs["image_preprocess"]["crop_bounds_original"]
        assert crop == {"x": 645, "y": 952, "w": 534, "h": 42}
        assert crop["x"] + crop["w"] < 1319
        assert kwargs["coordinate_transform"]["origin_original"] == {"x": 645, "y": 952}
        return {
            "point": {"x": 912, "y": 973},
            "coordinate_transform": kwargs["coordinate_transform"],
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 2521, "height": 1300},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "max_targets": 1,
            "stop_on_failure": False,
            "use_numbered_overlay": True,
            "region_roi_padding": 10,
        },
        timeout_seconds=12,
    )

    validation = target["vista_coordinate_validation"]
    assert summary["inside_count"] == 1
    assert validation["inference_scope"] == "target_context_roi"
    assert validation["image_preprocess"]["crop_bounds_original"] == {
        "x": 645,
        "y": 952,
        "w": 534,
        "h": 42,
    }


def test_learn_vista_menu_item_uses_raw_screenshot_when_number_overlay_would_cover_small_text(
    monkeypatch,
    tmp_path,
) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (300, 180), color="white").save(image_path)
    numbered_overlay_path = tmp_path / "numbered.png"
    Image.new("RGB", (300, 180), color="gray").save(numbered_overlay_path)
    target = {
        "candidate_id": "file_menu",
        "label": "File(F)",
        "role": "menu_item",
        "bbox": {"x": 20, "y": 30, "w": 60, "h": 38},
        "click_point": {"x": 50, "y": 49},
        "numbered_overlay_path": str(numbered_overlay_path),
        "locator_context": {
            "region_label": "Header",
            "region_bbox": {"x": 0, "y": 0, "w": 300, "h": 68},
        },
    }

    def fake_vista(**kwargs):
        assert kwargs["image_preprocess"]["numbered_overlay_source_path"] == ""
        assert kwargs["image_preprocess"]["original_image_path"] == str(image_path)
        return {
            "point": {"x": 50, "y": 49},
            "coordinate_transform": kwargs["coordinate_transform"],
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 300, "height": 180},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "max_targets": 1,
            "stop_on_failure": False,
            "use_numbered_overlay": True,
        },
        timeout_seconds=12,
    )

    validation = target["vista_coordinate_validation"]
    assert validation["inference_visual_source"] == "source_screenshot"
    assert validation["inference_scope"] == "target_context_roi"
    assert validation["precise_locator_evidence"]["numbered_overlay_used"] is False


def test_learn_vista_compact_direct_bar_control_uses_raw_candidate_centered_roi(
    monkeypatch,
    tmp_path,
) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 180), color="white").save(image_path)
    numbered_overlay_path = tmp_path / "numbered.png"
    Image.new("RGB", (400, 180), color="gray").save(numbered_overlay_path)
    target = {
        "candidate_id": "top_control_11",
        "label": "control 11",
        "role": "control",
        "bbox": {"x": 180, "y": 12, "w": 48, "h": 52},
        "click_point": {"x": 204, "y": 38},
        "locator_prompt": (
            "Locate the exact control numbered 1.11 in Top/header area. "
            "Return one point inside this exact item, not a nearby sibling."
        ),
        "numbered_overlay_path": str(numbered_overlay_path),
        "locator_context": {
            "region_label": "Top/header area",
            "region_bbox": {"x": 0, "y": 0, "w": 400, "h": 90},
        },
    }

    def fake_vista(**kwargs):
        assert kwargs["image_preprocess"]["numbered_overlay_source_path"] == ""
        assert kwargs["image_preprocess"]["original_image_path"] == str(image_path)
        crop = kwargs["image_preprocess"]["crop_bounds_original"]
        assert crop["w"] < 120
        assert crop["x"] <= target["bbox"]["x"]
        assert crop["x"] + crop["w"] >= target["bbox"]["x"] + target["bbox"]["w"]
        assert "closest to the center of this crop" in kwargs["prompt"]
        assert "numbered 1.11" not in kwargs["prompt"]
        return {
            "point": {"x": 204, "y": 38},
            "coordinate_transform": kwargs["coordinate_transform"],
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 400, "height": 180},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={
            "enabled": True,
            "max_targets": 1,
            "stop_on_failure": False,
            "use_numbered_overlay": True,
        },
        timeout_seconds=12,
    )

    validation = target["vista_coordinate_validation"]
    assert validation["inference_visual_source"] == "source_screenshot"
    assert validation["inference_scope"] == "target_context_roi"
    assert validation["precise_locator_evidence"]["numbered_overlay_used"] is False


def test_learn_vista_validation_reranks_current_ocr_candidate_instead_of_treating_source_bbox_as_answer(
    monkeypatch,
    tmp_path,
) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (360, 220), color="white").save(image_path)
    target = {
        "candidate_id": "search",
        "label": "Search",
        "role": "nav_item",
        "bbox": {"x": 10, "y": 20, "w": 72, "h": 36},
        "click_point": {"x": 46, "y": 38},
        "confidence": 0.6,
        "source": "stage2_visual",
        "locator_context": {
            "region_label": "Left navigation",
            "region_bbox": {"x": 0, "y": 0, "w": 190, "h": 220},
        },
    }

    def fake_vista(**kwargs):
        return {
            "point": {"x": 130, "y": 126},
            "coordinate_transform": kwargs["coordinate_transform"],
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 360, "height": 220},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={"enabled": True, "max_targets": 1, "stop_on_failure": False},
        timeout_seconds=12,
        evidence_context={
            "screen_map": {"candidates": []},
            "observe_result": {
                "texts": [
                    {
                        "id": "ocr-search",
                        "text": "Search",
                        "bbox": {"x": 104, "y": 112, "w": 52, "h": 28},
                        "confidence": 0.98,
                    }
                ]
            },
        },
    )

    validation = target["vista_coordinate_validation"]
    assert summary["precise_review_pass_count"] == 1
    assert validation["vista_point_inside_bbox"] is False
    assert validation["precise_locator_evidence"]["selected_candidate"]["candidate_id"] == "ocr-search"
    assert validation["precise_locator_evidence"]["source_bbox_quality"]["classification"] == "candidate_bbox_misaligned"
    assert target["bbox"] == {"x": 96, "y": 104, "w": 68, "h": 44}
    assert target["click_point"] == {"x": 130, "y": 126}
    assert target["coordinate_source"] == "precise_locator_v1"


def test_learn_vista_validation_separates_geometry_outside_from_gate_review(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (360, 220), color="white").save(image_path)
    target = {
        "candidate_id": "control-3",
        "label": "control 3",
        "role": "control",
        "bbox": {"x": 120, "y": 40, "w": 48, "h": 52},
        "click_point": {"x": 144, "y": 66},
        "confidence": 0.9,
        "source": "stage2_visual",
        "locator_context": {
            "region_label": "Top bar",
            "region_bbox": {"x": 0, "y": 0, "w": 360, "h": 100},
        },
    }

    monkeypatch.setattr(
        vision_api,
        "_call_vista_point_prompt",
        lambda **_kwargs: {
            "point": {"x": 144, "y": 66},
            "coordinate_transform": None,
            "image_preprocess": None,
        },
    )

    summary = vision_api._apply_vista_coordinate_validation_to_learn_targets(
        [target],
        image_path=str(image_path),
        image_size={"width": 360, "height": 220},
        local_config={"model_name": "inclusionAI/VISTA-4B", "output_contract": "vista_point_v1"},
        options={"enabled": True, "max_targets": 1, "stop_on_failure": False},
        timeout_seconds=12,
    )

    assert target["vista_coordinate_validation"]["status"] == "needs_review"
    assert summary["inside_count"] == 1
    assert summary["outside_count"] == 0
    assert summary["needs_review_count"] == 1


def test_learn_path_overlap_rule_removes_non_containment_overlap_but_keeps_children() -> None:
    candidates = [
        {
            "candidate_id": "parent_card",
            "label": "News card",
            "role": "news_card",
            "bbox": {"x": 20, "y": 40, "w": 260, "h": 140},
            "section_id": "main_content",
            "confidence": 0.7,
        },
        {
            "candidate_id": "child_button",
            "label": "Read more",
            "role": "button",
            "bbox": {"x": 210, "y": 145, "w": 60, "h": 24},
            "section_id": "main_content",
            "confidence": 0.8,
        },
        {
            "candidate_id": "overlap_card",
            "label": "Overlapping card",
            "role": "news_card",
            "bbox": {"x": 230, "y": 105, "w": 180, "h": 120},
            "section_id": "main_content",
            "confidence": 0.5,
        },
    ]

    kept, removals = vision_api._prune_non_containment_overlaps(candidates)

    assert {item["candidate_id"] for item in kept} == {"parent_card", "child_button"}
    assert removals == [
        {
            "candidate_id": "overlap_card",
            "label": "Overlapping card",
            "bbox": {"x": 230, "y": 105, "w": 180, "h": 120},
            "section_id": "main_content",
            "reason": "non_containment_overlap_removed",
            "source": "path_graph_overlap_rule",
            "kept_candidate_id": "parent_card",
            "kept_label": "News card",
        }
    ]


def test_learn_locate_hard_rules_run_when_model_review_skipped() -> None:
    screen_map = {
        "contract_version": "screen_map_v1",
        "summary": {"candidate_count": 2},
        "candidates": [
            {
                "candidate_id": "primary_card",
                "label": "Primary card",
                "role": "news_card",
                "bbox": {"x": 20, "y": 40, "w": 260, "h": 140},
                "section_id": "main_content",
                "confidence": 0.8,
            },
            {
                "candidate_id": "overlap_card",
                "label": "Overlapping card",
                "role": "news_card",
                "bbox": {"x": 230, "y": 105, "w": 180, "h": 120},
                "section_id": "main_content",
                "confidence": 0.5,
            },
        ],
    }

    refined, delta = vision_api._apply_learn_locate_model_review_to_screen_map(
        screen_map=screen_map,
        model_review={"contract_version": "learn_locate_model_review_v1", "status": "skipped"},
    )

    assert [item["candidate_id"] for item in refined["candidates"]] == ["primary_card"]
    assert refined["summary"]["non_containment_overlap_removal_count"] == 1
    assert delta["summary"]["removal_count"] == 1
    assert delta["removals"][0]["candidate_id"] == "overlap_card"
    assert delta["candidate_decisions"][0]["source"] == "path_graph_overlap_rule"


def test_learn_all_targets_visual_preview_removes_contained_parent_card(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    vision_api.Image.new("RGB", (420, 240), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "trace_path": "observe.json",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "demo_state",
            "candidates": [
                {
                    "candidate_id": "parent_card",
                    "label": "News card",
                    "role": "news_card",
                    "bbox": {"x": 20, "y": 40, "w": 260, "h": 140},
                    "click_point": {"x": 150, "y": 110},
                    "section_id": "main_content",
                    "source": "ocr_card_groups",
                    "confidence": 0.7,
                },
                {
                    "candidate_id": "child_button",
                    "label": "Read more",
                    "role": "button",
                    "bbox": {"x": 210, "y": 145, "w": 60, "h": 24},
                    "click_point": {"x": 240, "y": 157},
                    "section_id": "main_content",
                    "source": "ocr_text_actions",
                    "confidence": 0.8,
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert [item["candidate_id"] for item in result["targets"]] == ["child_button"]
    assert result["target_count"] == 1
    assert result["visual_overlap_removal_count"] == 1
    assert result["visual_overlap_removals"][0]["candidate_id"] == "parent_card"
    assert result["visual_overlap_removals"][0]["reason"] == "contained_visual_parent_removed"


def test_learn_target_overlay_uses_matching_two_stage_numbered_overlay_as_fusion_base(tmp_path, monkeypatch) -> None:
    from app.api import vision as vision_api

    source_path = tmp_path / "source.png"
    numbered_path = tmp_path / "numbered.png"
    Image.new("RGB", (160, 100), color="white").save(source_path)
    Image.new("RGB", (160, 100), color=(41, 52, 63)).save(numbered_path)
    monkeypatch.setattr(
        vision_api,
        "build_review_overlay_path",
        lambda **_: tmp_path / "fused.png",
    )

    overlay = vision_api._render_learn_all_targets_overlay(
        image_path=str(source_path),
        targets=[
            {
                "candidate_id": "stage2:header:search",
                "role": "button",
                "bbox": {"x": 20, "y": 20, "w": 40, "h": 24},
                "click_point": {"x": 40, "y": 32},
                "calibration_only": True,
                "numbered_overlay_path": str(numbered_path),
                "coordinate_validation": {"status": "valid"},
                "vista_coordinate_validation": {"status": "valid"},
            }
        ],
        name_hint="fusion",
    )

    assert overlay["status"] == "ready"
    assert overlay["base_visual_source"] == "two_stage_numbered_overlay"
    assert overlay["base_overlay_path"] == str(numbered_path.resolve())
    assert overlay["final_fusion_overlay"] is True
    with Image.open(overlay["output_path"]) as rendered:
        assert rendered.getpixel((120, 80)) == (41, 52, 63)


def test_learn_target_overlay_avoids_duplicate_success_labels_on_numbered_fusion_base(tmp_path, monkeypatch) -> None:
    from app.api import vision as vision_api

    source_path = tmp_path / "source.png"
    numbered_path = tmp_path / "numbered.png"
    Image.new("RGB", (160, 100), color="white").save(source_path)
    Image.new("RGB", (160, 100), color=(41, 52, 63)).save(numbered_path)
    monkeypatch.setattr(
        vision_api,
        "build_review_overlay_path",
        lambda **_: tmp_path / "fused.png",
    )
    labels: list[str] = []
    monkeypatch.setattr(
        vision_api,
        "_draw_learn_target_overlay_label",
        lambda _draw, _x, _y, label, **_kwargs: labels.append(label),
    )

    overlay = vision_api._render_learn_all_targets_overlay(
        image_path=str(source_path),
        targets=[
            {
                "candidate_id": "stage2:header:search",
                "role": "button",
                "bbox": {"x": 20, "y": 20, "w": 40, "h": 24},
                "click_point": {"x": 40, "y": 32},
                "calibration_only": True,
                "numbered_overlay_path": str(numbered_path),
                "coordinate_validation": {"status": "valid"},
                "vista_coordinate_validation": {"status": "valid"},
            },
            {
                "candidate_id": "stage2:header:review",
                "role": "button",
                "bbox": {"x": 80, "y": 20, "w": 40, "h": 24},
                "click_point": {"x": 100, "y": 32},
                "calibration_only": True,
                "numbered_overlay_path": str(numbered_path),
                "coordinate_validation": {"status": "valid"},
                "vista_coordinate_validation": {"status": "needs_review"},
            },
            {
                "candidate_id": "stage2:header:failed",
                "role": "button",
                "bbox": {"x": 125, "y": 20, "w": 30, "h": 24},
                "click_point": {"x": 140, "y": 32},
                "calibration_only": True,
                "numbered_overlay_path": str(numbered_path),
                "coordinate_validation": {"status": "valid"},
                "vista_coordinate_validation": {"status": "failed"},
            },
        ],
        name_hint="fusion",
    )

    assert overlay["status"] == "ready"
    assert overlay["calibration_label_mode"] == "failed_status_badges_only"
    assert labels == ["F"]


def test_learn_all_targets_filters_browser_chrome_and_tiny_noise(tmp_path) -> None:
    image_path = tmp_path / "browser.png"
    vision_api.Image.new("RGB", (640, 360), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "browser_page",
            "app_name": "python.org",
            "surface_adapter_decision": {
                "contract_version": "learning_surface_adapter_decision_v1",
                "adapter_id": "browser",
                "status": "selected_from_visible_evidence",
                "excluded_zones": ["browser_chrome"],
                "excluded_item_ids": ["browser_tab_title", "address_bar"],
                "final_geometry_allowed": False,
            },
            "candidates": [
                {
                    "candidate_id": "tab_noise",
                    "label": "Welcome tab",
                    "role": "button",
                    "bbox": {"x": 1, "y": 1, "w": 1, "h": 1},
                    "click_point": {"x": 1, "y": 1},
                    "section_id": "browser_chrome",
                    "source": "top_level.ui.elements",
                },
                {
                    "candidate_id": "browser_tab_title",
                    "label": "Welcome to Python.org tab",
                    "role": "button",
                    "bbox": {"x": 12, "y": 8, "w": 120, "h": 24},
                    "click_point": {"x": 72, "y": 20},
                    "section_id": "page_header",
                    "source": "top_level.ui.elements",
                },
                {
                    "candidate_id": "address_bar",
                    "label": "https://example.com",
                    "role": "text_input",
                    "bbox": {"x": 90, "y": 32, "w": 360, "h": 24},
                    "click_point": {"x": 270, "y": 44},
                    "section_id": "page_header",
                    "source": "top_level.ui.elements",
                },
                {
                    "candidate_id": "page_search",
                    "label": "Search documentation",
                    "role": "text_input",
                    "bbox": {"x": 120, "y": 120, "w": 240, "h": 36},
                    "click_point": {"x": 240, "y": 138},
                    "section_id": "primary_area",
                    "source": "ocr_text_actions",
                },
                {
                    "candidate_id": "site_top_nav",
                    "label": "Documentation",
                    "role": "link",
                    "bbox": {"x": 260, "y": 62, "w": 120, "h": 26},
                    "click_point": {"x": 320, "y": 75},
                    "section_id": "site_header",
                    "source": "ocr_text_actions",
                },
                {
                    "candidate_id": "windows_taskbar_edge",
                    "label": "Microsoft Edge",
                    "role": "button",
                    "bbox": {"x": 110, "y": 334, "w": 90, "h": 24},
                    "click_point": {"x": 155, "y": 346},
                    "section_id": "taskbar",
                    "source": "windows_uia.controls",
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert {item["candidate_id"] for item in result["targets"]} == {"site_top_nav", "page_search"}
    assert result["target_count"] == 2
    assert result["filtered_browser_chrome_count"] == 3
    assert result["filtered_noise_count"] == 1


def test_learn_all_targets_filters_browser_chrome_from_authoritative_calibration_candidates(tmp_path) -> None:
    image_path = tmp_path / "authoritative_browser.png"
    vision_api.Image.new("RGB", (1280, 720), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "python_homepage",
            "app_name": "Welcome to Python.org",
            "two_stage_calibration_authoritative": True,
            "candidates": [
                {
                    "candidate_id": "stale_observe_candidate",
                    "label": "Stale candidate",
                    "role": "button",
                    "bbox": {"x": 500, "y": 300, "w": 100, "h": 40},
                    "click_point": {"x": 550, "y": 320},
                    "section_id": "primary_area",
                }
            ],
            "calibration_candidates": [
                {
                    "candidate_id": "stage2_browser_tab",
                    "label": "Welcome to Python.org",
                    "role": "button",
                    "bbox": {"x": 70, "y": 8, "w": 180, "h": 28},
                    "click_point": {"x": 160, "y": 22},
                    "parent_region_id": "structure_region_browser_chrome",
                },
                {
                    "candidate_id": "stage2_automation_banner",
                    "label": "ChatGPT 已开始调试此浏览器",
                    "role": "text",
                    "bbox": {"x": 24, "y": 58, "w": 240, "h": 28},
                    "click_point": {"x": 144, "y": 72},
                    "parent_region_id": "structure_region_page_header",
                },
                {
                    "candidate_id": "stage2_page_search",
                    "label": "Search documentation",
                    "role": "text_input",
                    "bbox": {"x": 700, "y": 160, "w": 260, "h": 36},
                    "click_point": {"x": 830, "y": 178},
                    "parent_region_id": "structure_region_main_content",
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert {item["candidate_id"] for item in result["calibration_targets"]} == {"stage2_page_search"}
    assert result["raw_calibration_candidate_count"] == 3
    assert result["filtered_calibration_browser_chrome_count"] == 2
    assert result["filtered_browser_chrome_count"] == 2
    assert result["calibration_target_count"] == 1


def test_learn_all_targets_excludes_dry_run_only_content_cards(tmp_path) -> None:
    image_path = tmp_path / "content_cards.png"
    vision_api.Image.new("RGB", (900, 600), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "python_homepage",
            "app_name": "python.org",
            "candidates": [
                {
                    "candidate_id": "search_button",
                    "label": "Search button",
                    "role": "button",
                    "bbox": {"x": 700, "y": 80, "w": 80, "h": 36},
                    "click_point": {"x": 740, "y": 98},
                    "section_id": "site_header",
                    "source": "top_level.ui.elements",
                    "risk_class": "safe_click_allowed",
                    "evidence": {"interaction_policy": {"allowed": True}},
                },
                {
                    "candidate_id": "code_sample_text_card",
                    "label": "# Simple output (with Unicode)",
                    "role": "news_card",
                    "bbox": {"x": 120, "y": 150, "w": 360, "h": 220},
                    "click_point": {"x": 300, "y": 260},
                    "section_id": "primary_area",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "evidence": {
                        "interaction_policy": {
                            "allowed": None,
                            "reasons": ["card_group_candidate", "section:primary_area"],
                        }
                    },
                },
                {
                    "candidate_id": "jobs_body_text_card",
                    "label": "Looking for work or have a Python related position",
                    "role": "recommendation_item",
                    "bbox": {"x": 540, "y": 280, "w": 280, "h": 130},
                    "click_point": {"x": 680, "y": 345},
                    "section_id": "primary_area",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "evidence": {
                        "interaction_policy": {
                            "allowed": None,
                            "reasons": ["card_group_candidate", "section:primary_area"],
                        }
                    },
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert [item["candidate_id"] for item in result["targets"]] == ["search_button"]
    assert result["filtered_non_actionable_count"] == 2
    assert [item["candidate_id"] for item in result["review_boxes"]] == [
        "code_sample_text_card",
        "jobs_body_text_card",
    ]
    assert all(item["review_status"] == "non_actionable_review_only" for item in result["review_boxes"])
    assert result["overlay"]["review_box_count"] == 2
    assert result["overlay"]["target_count"] == 1
    assert result["overlay"]["total_box_count"] == 3


def test_learn_all_targets_renders_non_actionable_review_boxes_when_no_targets(tmp_path) -> None:
    image_path = tmp_path / "review_only.png"
    vision_api.Image.new("RGB", (900, 600), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {
            "texts": [
                {
                    "id": "ocr_home_title",
                    "text": "主页",
                    "bbox": {"x": 94, "y": 98, "w": 68, "h": 38},
                    "confidence": 0.99,
                },
                {
                    "id": "ocr_section_title",
                    "text": "专属精选推荐",
                    "bbox": {"x": 95, "y": 162, "w": 96, "h": 20},
                    "confidence": 0.99,
                },
                {
                    "id": "ocr_album_title",
                    "text": "能量充电",
                    "bbox": {"x": 135, "y": 329, "w": 162, "h": 45},
                    "confidence": 0.99,
                },
            ]
        },
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "apple_music_home",
            "app_name": "apple_music",
            "candidates": [
                {
                    "candidate_id": "album_card_1",
                    "label": "ATLUS Sound Team",
                    "role": "news_card",
                    "bbox": {"x": 76, "y": 417, "w": 232, "h": 201},
                    "click_point": {"x": 192, "y": 518},
                    "section_id": "main_content",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "evidence": {
                        "interaction_policy": {
                            "allowed": None,
                            "reasons": ["card_group_candidate", "section:main_content"],
                        }
                    },
                },
                {
                    "candidate_id": "album_card_2",
                    "label": "Death Stranding 2 Songs",
                    "role": "recommendation_item",
                    "bbox": {"x": 693, "y": 786, "w": 199, "h": 58},
                    "click_point": {"x": 792, "y": 815},
                    "section_id": "main_content",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "evidence": {
                        "interaction_policy": {
                            "allowed": None,
                            "reasons": ["card_group_candidate", "section:main_content"],
                        }
                    },
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert result["status"] == "empty"
    assert result["target_count"] == 0
    assert result["filtered_non_actionable_count"] == 2
    assert [item["candidate_id"] for item in result["review_boxes"][:2]] == ["album_card_1", "album_card_2"]
    assert {item["candidate_id"] for item in result["review_boxes"]} >= {
        "learn_ocr_text_ocr_home_title",
        "learn_ocr_text_ocr_section_title",
        "learn_ocr_text_ocr_album_title",
    }
    assert all(
        item["execute_binding_enabled"] is False and item["artifact_is_authorization"] is False
        for item in result["review_boxes"]
    )
    assert result["overlay"]["status"] == "ready"
    assert result["overlay"]["target_count"] == 0
    assert result["overlay"]["review_box_count"] == 5
    assert result["overlay"]["total_box_count"] == 5
    assert result["overlay_path"]
    assert vision_api._learn_all_targets_location_status(result) == "learn_review_boxes_ready"


def test_learn_all_targets_locate_reports_review_boxes_ready_when_no_executable_targets(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "review_only_locate.png"
    vision_api.Image.new("RGB", (900, 600), (255, 255, 255)).save(image_path)
    observe_trace = tmp_path / "observe_review_only.json"
    observe_trace.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 900, "height": 600},
                    "texts": [
                        {
                            "id": "ocr_home_title",
                            "text": "主页",
                            "bbox": {"x": 94, "y": 98, "w": 68, "h": 38},
                            "confidence": 0.99,
                        }
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "apple_music_home",
                        "app_name": "apple_music",
                        "candidates": [
                            {
                                "candidate_id": "album_card_1",
                                "label": "ATLUS Sound Team",
                                "role": "news_card",
                                "bbox": {"x": 76, "y": 417, "w": 232, "h": 201},
                                "click_point": {"x": 192, "y": 518},
                                "section_id": "main_content",
                                "source": "ocr_card_groups",
                                "risk_class": "safe_dry_run_only",
                                "screen_map_rule": "card_texts_grouped_as_single_candidate",
                                "evidence": {
                                    "interaction_policy": {
                                        "allowed": None,
                                        "reasons": ["card_group_candidate", "section:main_content"],
                                    }
                                },
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: (str(image_path), None),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "learn-review-boxes-trace.json")
    monkeypatch.setattr(
        vision_api,
        "recognition_plan",
        lambda _request: (_ for _ in ()).throw(AssertionError("Learn all-target locate should not run single-goal recognition")),
    )

    response = vision_api.locate_target(
        VisionLocateTargetRequestModel(
            goal="learn all visible controls",
            app_name="apple_music",
            agent_mode="learn",
            learn_depth="deep",
            metadata={"learn_all_targets": True, "learn_vista_coordinate_validation": False},
            observe_trace_path=str(observe_trace),
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert result["location_status"] == "learn_review_boxes_ready"
    assert result["learn_all_targets"]["target_count"] == 0
    assert result["learn_all_targets"]["review_box_count"] >= 1
    assert Path(result["learn_all_targets"]["overlay_path"]).exists()
    assert result["path_map_review"]["summary"]["addition_count"] == 0
    assert result["path_map_review"]["summary"]["review_box_count"] >= 1
    assert result["path_map_review"]["summary"]["review_only_overlay_ready"] is True
    assert result["execution_path"]["target_count"] == 0
    assert result["execution_path"]["review_box_count"] >= 1
    assert result["execution_path"]["review_only_overlay_ready"] is True


def test_learn_review_boxes_keep_card_text_as_children_not_sibling_numbers(tmp_path) -> None:
    image_path = tmp_path / "card_children.png"
    vision_api.Image.new("RGB", (800, 500), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {
            "texts": [
                {"id": "ocr_section", "text": "专属精选推荐", "bbox": {"x": 80, "y": 120, "w": 110, "h": 20}, "confidence": 0.99},
                {"id": "ocr_album", "text": "能量充电", "bbox": {"x": 120, "y": 260, "w": 130, "h": 36}, "confidence": 0.99},
                {"id": "ocr_artist", "text": "ATLUS Sound Team", "bbox": {"x": 120, "y": 318, "w": 150, "h": 18}, "confidence": 0.99},
            ]
        },
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "apple_music_home",
            "app_name": "apple_music",
            "candidates": [
                {
                    "candidate_id": "music_card_energy",
                    "label": "能量充电",
                    "role": "news_card",
                    "bbox": {"x": 88, "y": 190, "w": 245, "h": 180},
                    "click_point": {"x": 210, "y": 280},
                    "section_id": "main_content",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "children": [
                        {"child_id": "ocr_album", "label": "能量充电", "bbox": {"x": 120, "y": 260, "w": 130, "h": 36}},
                        {"child_id": "ocr_artist", "label": "ATLUS Sound Team", "bbox": {"x": 120, "y": 318, "w": 150, "h": 18}},
                    ],
                    "evidence": {"interaction_policy": {"allowed": None, "reasons": ["card_group_candidate"]}},
                }
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    by_id = {item["candidate_id"]: item for item in result["review_boxes"]}
    assert "music_card_energy" in by_id
    assert [item["label"] for item in by_id["music_card_energy"]["children"]] == ["能量充电", "ATLUS Sound Team"]
    assert "learn_ocr_text_ocr_album" not in by_id
    assert "learn_ocr_text_ocr_artist" not in by_id
    assert "learn_ocr_text_ocr_section" in by_id


def test_learn_review_boxes_include_left_nav_rail_icons_without_ocr(tmp_path) -> None:
    image_path = tmp_path / "left_nav_rail.png"
    image = vision_api.Image.new("RGB", (640, 480), (255, 255, 255))
    draw = vision_api.ImageDraw.Draw(image)
    draw.rectangle((0, 0, 56, 479), fill=(245, 245, 245))
    draw.rectangle((22, 96, 36, 110), fill=(30, 30, 30))
    draw.rectangle((22, 146, 36, 160), fill=(30, 30, 30))
    draw.rectangle((22, 196, 36, 210), fill=(30, 30, 30))
    image.save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {"image_size": {"width": 640, "height": 480}, "texts": []},
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "desktop_app_home",
            "app_name": "desktop_app",
            "candidates": [],
            "two_stage_structure_regions": [
                {
                    "region_id": "structure_region_left_navigation",
                    "label": "Left navigation",
                    "role": "left_navigation",
                    "bbox": {"x": 0, "y": 0, "w": 56, "h": 480},
                }
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    nav_boxes = [item for item in result["review_boxes"] if item["role"] == "nav_rail_icon_review_only"]
    assert len(nav_boxes) >= 3
    assert all(item["execute_binding_enabled"] is False for item in nav_boxes)
    assert all(item["artifact_is_authorization"] is False for item in nav_boxes)


def test_learn_review_boxes_do_not_invent_left_nav_without_structure_region(tmp_path) -> None:
    image_path = tmp_path / "no_left_nav_region.png"
    image = vision_api.Image.new("RGB", (640, 480), (255, 255, 255))
    draw = vision_api.ImageDraw.Draw(image)
    draw.rectangle((0, 0, 56, 479), fill=(245, 245, 245))
    draw.rectangle((22, 96, 36, 110), fill=(30, 30, 30))
    draw.rectangle((22, 146, 36, 160), fill=(30, 30, 30))
    draw.rectangle((22, 196, 36, 210), fill=(30, 30, 30))
    image.save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {"image_size": {"width": 640, "height": 480}, "texts": []},
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "settings_home",
            "app_name": "settings",
            "candidates": [],
            "two_stage_structure_regions": [
                {
                    "region_id": "structure_region_top_bar",
                    "label": "Top/header area",
                    "role": "top_bar",
                    "bbox": {"x": 0, "y": 0, "w": 640, "h": 80},
                },
                {
                    "region_id": "structure_region_primary_area",
                    "label": "Primary Area",
                    "role": "primary_area",
                    "bbox": {"x": 0, "y": 80, "w": 640, "h": 400},
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert not any(item["role"] == "nav_rail_icon_review_only" for item in result["review_boxes"])


def test_learn_final_overlay_uses_authoritative_two_stage_candidates_without_raw_review_mix(tmp_path) -> None:
    image_path = tmp_path / "authoritative_two_stage.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {
            "image_size": {"width": 320, "height": 200},
            "texts": [
                {"id": "raw_title", "text": "Applications", "bbox": {"x": 50, "y": 60, "w": 80, "h": 18}},
            ],
        },
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "settings_home",
            "candidates": [
                {
                    "candidate_id": "raw_text_candidate",
                    "label": "Applications",
                    "role": "text",
                    "bbox": {"x": 50, "y": 60, "w": 80, "h": 18},
                    "click_point": {"x": 90, "y": 69},
                    "source": "ocr_text",
                }
            ],
            "calibration_candidates": [
                {
                    "candidate_id": "stage2:main:applications_parent",
                    "label": "Applications card",
                    "role": "tile_card_parent",
                    "bbox": {"x": 30, "y": 40, "w": 150, "h": 90},
                    "click_point": {"x": 105, "y": 85},
                    "source": "two_stage_parent_group",
                    "calibration_only": True,
                    "review_only": True,
                }
            ],
            "two_stage_calibration_authoritative": True,
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert result["calibration_target_count"] == 1
    assert result["target_count"] == 0
    assert result["review_boxes"] == []
    assert result["raw_candidates_suppressed_by_authoritative_two_stage_count"] == 1


def test_learn_vista_dense_row_context_excludes_adjacent_rows() -> None:
    context = vision_api._learn_vista_target_context_bbox(
        {"x": 12, "y": 326, "w": 368, "h": 33},
        parent_bbox={"x": 0, "y": 120, "w": 800, "h": 740},
        target_role="conversation_row",
    )

    assert context == {"x": 0, "y": 326, "w": 736, "h": 33}


def test_learn_vista_dense_list_row_context_excludes_parallel_column() -> None:
    context = vision_api._learn_vista_target_context_bbox(
        {"x": 698, "y": 962, "w": 428, "h": 22},
        parent_bbox={"x": 0, "y": 210, "w": 2521, "h": 1090},
        target_role="list_row",
    )

    assert context == {"x": 655, "y": 962, "w": 514, "h": 22}
    assert context["x"] <= 698
    assert context["x"] + context["w"] >= 1126
    assert context["x"] + context["w"] < 1319


def test_learn_vista_menu_item_context_is_local_to_adjacent_menu_strip() -> None:
    context = vision_api._learn_vista_target_context_bbox(
        {"x": 20, "y": 30, "w": 60, "h": 38},
        parent_bbox={"x": 0, "y": 0, "w": 2576, "h": 68},
        target_role="menu_item",
    )

    assert context == {"x": 2, "y": 16, "w": 96, "h": 52}


def test_learn_vista_compact_direct_bar_control_context_excludes_adjacent_controls() -> None:
    context = vision_api._learn_vista_target_context_bbox(
        {"x": 877, "y": 9, "w": 48, "h": 52},
        parent_bbox={"x": 0, "y": 0, "w": 1154, "h": 90},
        target_role="control",
    )

    assert context == {"x": 865, "y": 2, "w": 72, "h": 65}


def test_learn_vista_does_not_ground_status_bar_evidence() -> None:
    assert vision_api._learn_vista_target_ineligibility_reason(
        {
            "candidate_id": "stage2:main:status_bar",
            "label": "第 1 行，第 1 列 100% Windows (CRLF)",
            "role": "status_bar_evidence",
            "bbox": {"x": 1200, "y": 742, "w": 400, "h": 58},
        },
        image_size={"width": 1600, "height": 800},
    ) == "structural_status_bar_review_only"


def test_learn_vista_does_not_ground_combined_menu_bar_evidence() -> None:
    assert vision_api._learn_vista_target_ineligibility_reason(
        {
            "candidate_id": "stage2:topbar:combined_menu",
            "label": "文件(F) 编辑(E) 格式(O) 查看(V) 帮助(H)",
            "role": "menu_bar_evidence",
            "bbox": {"x": 12, "y": 33, "w": 263, "h": 22},
        },
        image_size={"width": 2576, "height": 1416},
    ) == "structural_menu_bar_review_only"


def test_learn_vista_only_receives_locatable_targets_while_review_evidence_stays_visible(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "locatable_targets.png"
    Image.new("RGB", (320, 200), color="white").save(image_path)
    calibration_candidates = [
        {
            "candidate_id": "button_target",
            "label": "Open chat",
            "role": "button",
            "bbox": {"x": 20, "y": 20, "w": 80, "h": 36},
            "click_point": {"x": 60, "y": 38},
            "source": "two_stage_stage2_numbering",
        },
        {
            "candidate_id": "conversation_row_target",
            "label": "Project group",
            "role": "conversation_row",
            "bbox": {"x": 20, "y": 70, "w": 180, "h": 58},
            "click_point": {"x": 110, "y": 99},
            "source": "two_stage_parent_group",
        },
        {
            "candidate_id": "plain_text_evidence",
            "label": "Latest message",
            "role": "text",
            "bbox": {"x": 50, "y": 90, "w": 90, "h": 18},
            "click_point": {"x": 95, "y": 99},
            "source": "two_stage_stage2_numbering",
        },
        {
            "candidate_id": "layout_separator",
            "label": "separator",
            "role": "separator",
            "bbox": {"x": 10, "y": 140, "w": 200, "h": 2},
            "click_point": {"x": 110, "y": 141},
            "source": "two_stage_stage2_numbering",
        },
        {
            "candidate_id": "window_shell",
            "label": "title bar",
            "role": "pane",
            "bbox": {"x": 220, "y": 0, "w": 90, "h": 42},
            "click_point": {"x": 265, "y": 21},
            "source": "two_stage_stage2_numbering",
        },
        {
            "candidate_id": "partial_visible_card_1",
            "label": "partially visible conversation",
            "role": "message_card",
            "bbox": {"x": 20, "y": 178, "w": 180, "h": 22},
            "click_point": {"x": 110, "y": 189},
            "source": "bottom_edge_partial_card_reconciliation",
        },
        {
            "candidate_id": "chat_list_filters_container",
            "label": "chat-list-filters",
            "role": "message_bubble",
            "bbox": {"x": 10, "y": 145, "w": 200, "h": 32},
            "click_point": {"x": 110, "y": 161},
            "source": "two_stage_stage2_numbering",
        },
    ]
    observe_reuse = {
        "status": "ready",
        "observe_result": {"image_size": {"width": 320, "height": 200}},
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "conversation_workspace",
            "candidates": [],
            "calibration_candidates": calibration_candidates,
            "two_stage_calibration_authoritative": True,
        },
    }
    calls: list[str] = []

    def fake_vista(**kwargs):
        calls.append(kwargs["prompt"])
        point = {"x": 60, "y": 38} if len(calls) == 1 else {"x": 110, "y": 99}
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": f"[{point['x']}, {point['y']}]",
            "raw_response": {"choices": [{"message": {"content": f"[{point['x']}, {point['y']}]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": float(point["x"]), "y": float(point["y"]), "coordinate_space": "pixel"},
            },
            "point": point,
            "image_size": {"width": 320, "height": 200},
        }

    monkeypatch.setattr(vision_api, "_call_vista_point_prompt", fake_vista)

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={
            "local_config": {"profile_id": "vista-test", "model_name": "inclusionAI/VISTA-4B"},
            "options": {"enabled": True, "validate_all_targets": True, "stop_on_failure": False},
            "timeout_seconds": 30,
        },
    )

    summary = result["vista_coordinate_validation"]
    assert result["calibration_target_count"] == 7
    assert len(calls) == 2
    assert summary["eligible_target_count"] == 2
    assert summary["review_only_not_sent_to_vista_count"] == 5
    assert {item["candidate_id"] for item in summary["review_only_not_sent_to_vista"]} == {
        "plain_text_evidence",
        "layout_separator",
        "window_shell",
        "partial_visible_card_1",
        "chat_list_filters_container",
    }
    by_id = {item["candidate_id"]: item for item in result["calibration_targets"]}
    assert by_id["plain_text_evidence"]["vista_coordinate_validation"]["status"] == "skipped"
    assert by_id["partial_visible_card_1"]["vista_coordinate_validation"]["reason"] == "partial_visible_review_only"
    assert result["overlay_path"]


def test_learn_all_targets_excludes_blocked_visual_icons_but_keeps_cards_as_review_boxes(tmp_path) -> None:
    image_path = tmp_path / "blocked_icons_with_cards.png"
    image = vision_api.Image.new("RGB", (900, 650), (255, 255, 255))
    draw = vision_api.ImageDraw.Draw(image)
    draw.rectangle((0, 0, 58, 649), fill=(246, 246, 246))
    draw.rectangle((18, 140, 38, 160), fill=(24, 24, 24))
    image.save(image_path)
    observe_reuse = {
        "status": "ready",
        "observe_result": {
            "texts": [
                {"id": "card_title", "text": "能量充电", "bbox": {"x": 180, "y": 300, "w": 110, "h": 32}, "confidence": 0.98},
                {"id": "section_title", "text": "专属精选推荐", "bbox": {"x": 160, "y": 240, "w": 110, "h": 20}, "confidence": 0.98},
            ]
        },
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "apple_music_home",
            "app_name": "apple_music",
            "two_stage_structure_regions": [
                {
                    "region_id": "structure_region_left_navigation",
                    "label": "Left navigation",
                    "role": "left_navigation",
                    "bbox": {"x": 0, "y": 0, "w": 58, "h": 650},
                }
            ],
            "candidates": [
                {
                    "candidate_id": "visual_left_icon_home",
                    "label": "Home",
                    "role": "icon_button",
                    "bbox": {"x": 16, "y": 136, "w": 24, "h": 24},
                    "click_point": {"x": 28, "y": 148},
                    "section_id": "left_nav_rail",
                    "source": "top_level.ui.elements",
                    "risk_class": "blocked",
                    "evidence": {
                        "interaction_policy": {
                            "allowed": False,
                            "reasons": ["semantic_icon_without_text_or_uia"],
                        }
                    },
                },
                {
                    "candidate_id": "music_card_energy",
                    "label": "能量充电",
                    "role": "news_card",
                    "bbox": {"x": 148, "y": 270, "w": 240, "h": 180},
                    "click_point": {"x": 268, "y": 360},
                    "section_id": "primary_area",
                    "source": "ocr_card_groups",
                    "risk_class": "safe_dry_run_only",
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "children": [
                        {"child_id": "card_title", "label": "能量充电", "bbox": {"x": 180, "y": 300, "w": 110, "h": 32}},
                    ],
                    "evidence": {"interaction_policy": {"allowed": None, "reasons": ["card_group_candidate"]}},
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert result["target_count"] == 0
    assert result["filtered_blocked_review_only_count"] == 1
    assert {item["candidate_id"] for item in result["review_boxes"]} >= {"music_card_energy"}
    assert not any(item["candidate_id"] == "visual_left_icon_home" for item in result["targets"])
    assert not any(item["candidate_id"] == "visual_left_icon_home" for item in result["review_boxes"])
    assert any(item["role"] == "nav_rail_icon_review_only" for item in result["review_boxes"])
    assert result["overlay"]["review_box_count"] >= 2
    assert result["overlay_path"]


def test_card_bbox_uses_contiguous_text_cluster_without_swallowing_next_heading() -> None:
    section_bbox = {"x": 80, "y": 180, "w": 280, "h": 460}
    texts = [
        {"id": "title", "text": "专属推荐", "bbox": {"x": 112, "y": 435, "w": 53, "h": 17}},
        {"id": "seed", "text": "ATLUS Sound Team", "bbox": {"x": 110, "y": 451, "w": 180, "h": 20}},
        {"id": "artist", "text": "CthulhuSeeker", "bbox": {"x": 112, "y": 468, "w": 160, "h": 17}},
        {"id": "more", "text": "San-Z", "bbox": {"x": 111, "y": 483, "w": 190, "h": 17}},
        {"id": "next_heading", "text": "最近播放", "bbox": {"x": 94, "y": 579, "w": 67, "h": 21}},
    ]

    bbox = vision_api._card_bbox_for_seed(
        texts,
        seed_bbox={"x": 110, "y": 451, "w": 180, "h": 20},
        seed_boxes=[{"x": 110, "y": 451, "w": 180, "h": 20}],
        section_bbox=section_bbox,
    )

    assert bbox is not None
    assert bbox["y"] + bbox["h"] < 560


def test_learn_all_targets_excludes_ocr_only_text_headers_but_keeps_clear_small_buttons(tmp_path) -> None:
    image_path = tmp_path / "ocr_text_actions.png"
    vision_api.Image.new("RGB", (1000, 700), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "python_homepage",
            "app_name": "python.org",
            "candidates": [
                {
                    "candidate_id": "ocr_latest_news_header",
                    "label": "Latest News",
                    "role": "text_action",
                    "bbox": {"x": 180, "y": 420, "w": 145, "h": 30},
                    "click_point": {"x": 252, "y": 435},
                    "section_id": "primary_area",
                    "source": "ocr_text_actions",
                    "risk_class": "safe_click_allowed",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["ocr_text_candidate"]},
                        "evidence_level": "ocr_text_only",
                    },
                },
                {
                    "candidate_id": "ocr_latest_version_text",
                    "label": "Latest: Python 3.14.6",
                    "role": "text_action",
                    "bbox": {"x": 360, "y": 320, "w": 150, "h": 24},
                    "click_point": {"x": 435, "y": 332},
                    "section_id": "primary_area",
                    "source": "ocr_text_actions",
                    "risk_class": "safe_click_allowed",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["ocr_text_candidate"]},
                        "evidence_level": "ocr_text_only",
                    },
                },
                {
                    "candidate_id": "ocr_more_button",
                    "label": ">> More",
                    "role": "button",
                    "bbox": {"x": 850, "y": 420, "w": 62, "h": 24},
                    "click_point": {"x": 881, "y": 432},
                    "section_id": "primary_area",
                    "source": "ocr_text_actions",
                    "risk_class": "safe_click_allowed",
                    "screen_map_rule": "more_text_is_button",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["ocr_text_candidate"]},
                        "evidence_level": "ocr_text_only",
                    },
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert [item["candidate_id"] for item in result["targets"]] == ["ocr_more_button"]
    assert result["filtered_non_actionable_count"] == 2


def test_learn_all_targets_excludes_ungrounded_semantic_regions(tmp_path) -> None:
    image_path = tmp_path / "semantic_regions.png"
    vision_api.Image.new("RGB", (1000, 700), (255, 255, 255)).save(image_path)
    observe_reuse = {
        "status": "ready",
        "screen_map": {
            "contract_version": "screen_map_v1",
            "state_id": "python_homepage",
            "app_name": "python.org",
            "candidates": [
                {
                    "candidate_id": "semantic_search_button",
                    "label": "Search button",
                    "role": "button",
                    "bbox": {"x": 620, "y": 240, "w": 70, "h": 44},
                    "click_point": {"x": 655, "y": 262},
                    "source": "top_level.ui.elements",
                    "risk_class": "safe_click_allowed",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["generic_action"]},
                        "coordinate_confidence": "medium",
                        "evidence_level": "semantic_region_only",
                        "source_text_id": None,
                    },
                },
                {
                    "candidate_id": "grounded_download_button",
                    "label": "Download button",
                    "role": "button",
                    "bbox": {"x": 140, "y": 120, "w": 120, "h": 42},
                    "click_point": {"x": 200, "y": 141},
                    "source": "top_level.ui.elements",
                    "risk_class": "safe_click_allowed",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["generic_action"]},
                        "coordinate_confidence": "medium",
                        "evidence_level": "semantic_region_only",
                        "source_text_id": "text_download",
                    },
                },
                {
                    "candidate_id": "high_confidence_semantic_button",
                    "label": "Docs button",
                    "role": "button",
                    "bbox": {"x": 320, "y": 120, "w": 95, "h": 42},
                    "click_point": {"x": 367, "y": 141},
                    "source": "top_level.ui.elements",
                    "risk_class": "safe_click_allowed",
                    "evidence": {
                        "interaction_policy": {"allowed": True, "reasons": ["generic_action"]},
                        "coordinate_confidence": "high",
                        "evidence_level": "semantic_region_only",
                        "source_text_id": None,
                    },
                },
            ],
        },
    }

    result = vision_api._build_learn_all_targets_from_screen_map(
        observe_reuse,
        image_path=str(image_path),
        vista_validation={"options": {"enabled": False}},
    )

    assert [item["candidate_id"] for item in result["targets"]] == [
        "grounded_download_button",
        "high_confidence_semantic_button",
    ]
    assert result["filtered_ungrounded_count"] == 1


def test_recognition_plan_reuses_observe_ocr_anchors_without_rescanning(monkeypatch, tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")

    def fail_scan(_path):
        raise AssertionError("OCR should be reused from observe trace")

    monkeypatch.setattr(vision_api.ocr_service, "scan_image", fail_scan)

    reused_anchors = {
        "contract_version": "ocr_anchors_v1",
        "image_path": str(image_path),
        "coordinate_space": "original_image",
        "image_size": {"width": 100, "height": 80},
        "anchor_count": 1,
        "anchors": [
            {
                "anchor_id": "ocr_anchor_1",
                "text": "Start",
                "bbox": {"x": 10, "y": 12, "w": 40, "h": 16},
                "center": {"x": 30, "y": 20},
                "confidence": 0.99,
            }
        ],
    }

    vision_request, ocr_result, anchor_payload, status = vision_api._recognition_vision_request_with_ocr_anchors(
        VisionRecognitionPlanRequestModel(
            image_path=str(image_path),
            goal="Start",
            metadata={
                "reused_ocr_anchors": reused_anchors,
                "reused_ocr_source_trace_path": "observe-trace.json",
                "ocr_anchors": {"enabled": True, "max_anchors": "all"},
            },
        ),
        image_path=image_path,
        image_size=ImageSize(width=100, height=80),
    )

    assert ocr_result is not None
    assert ocr_result.metadata["engine"] == "observe_trace_reuse"
    assert ocr_result.matches[0].text == "Start"
    assert anchor_payload is not None
    assert anchor_payload["anchor_count"] == 1
    assert status["reused"] is True
    assert status["source_trace_path"] == "observe-trace.json"
    assert vision_request.metadata["ocr_anchors"]["anchors"][0]["text"] == "Start"
    assert "reused_ocr_anchors" not in vision_request.metadata


def test_locate_reuse_builds_ocr_anchors_from_observe_trace_texts(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 200, "height": 120},
                    "texts": [
                        {
                            "id": "text_start",
                            "text": "Start",
                            "bbox": {"x": 20, "y": 30, "w": 50, "h": 20},
                            "confidence": 0.97,
                        }
                    ],
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [{"label": "Start"}],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reuse = vision_api._load_observe_trace_reuse(str(trace_path), image_path=str(image_path), goal="Start")

    assert reuse["status"] == "ready"
    assert reuse["anchor_source"] == "observe_trace_texts"
    assert reuse["anchor_count"] == 1
    assert reuse["ocr_anchors"]["anchors"][0]["text"] == "Start"
    assert reuse["ocr_anchors"]["anchors"][0]["goal_similarity"] == 1.0
    assert reuse["state_id"] == "state_demo"


def test_observe_trace_reuse_builds_screen_inventory_from_screen_reading(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fake")
    trace_path = tmp_path / "observe_with_screen_reading.json"
    trace_path.write_text(
        __import__("json").dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "image_size": {"width": 300, "height": 180},
                    "texts": [
                        {
                            "id": "text_pay",
                            "text": "Pay",
                            "bbox": {"x": 20, "y": 40, "w": 40, "h": 20},
                            "confidence": 0.97,
                        }
                    ],
                    "parse_result": {
                        "screen_reading": {
                            "contract_version": "screen_reading_v1",
                            "texts": [
                                {
                                    "id": "text_pay",
                                    "text": "Pay",
                                    "bbox": {"x": 20, "y": 40, "w": 40, "h": 20},
                                    "confidence": 0.97,
                                }
                            ],
                            "ui_elements": [
                                {
                                    "id": "filter_pay",
                                    "type": "button",
                                    "role_guess": "button",
                                    "label": "Pay",
                                    "bbox": {"x": 12, "y": 30, "w": 80, "h": 42},
                                    "click_point": {"x": 52, "y": 51},
                                    "confidence": 0.8,
                                    "coordinate_confidence": "medium",
                                    "interaction_type": "click",
                                    "evidence": {"interaction_policy": {"allowed": True}},
                                }
                            ],
                        }
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [{"label": "Pay"}],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reuse = vision_api._load_observe_trace_reuse(str(trace_path), image_path=str(image_path), goal="Pay")

    assert reuse["status"] == "ready"
    assert reuse["screen_inventory"]["contract_version"] == "screen_inventory_v1"
    assert reuse["screen_inventory"]["available_actions"][0]["label"] == "Pay"
