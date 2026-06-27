from __future__ import annotations

from pathlib import Path

from app.api import vision as vision_api
from app.models.request import VisionLocateTargetRequestModel, VisionObserveScreenRequestModel
from app.models.request import VisionRecognitionPlanRequestModel
from app.models.response import APIResponse, ErrorModel
from app.vision.schemas import ImageSize, VisionAnalyzeResponse


def test_observe_screen_wraps_live_capture_and_screen_reading(monkeypatch) -> None:
    monkeypatch.setattr(
        vision_api,
        "_image_path_for_live_or_saved",
        lambda **_kwargs: ("screen.png", {"image_path": "screen.png"}),
    )
    monkeypatch.setattr(vision_api, "write_trace", lambda **_kwargs: "observe-trace.json")

    def fake_screen_reading(request):
        assert request.image_path == "screen.png"
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

    response = vision_api.observe_screen(VisionObserveScreenRequestModel(app_name="demo"))

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
    assert result["screen_map"]["summary"]["section_count"] >= 3
    assert result["screen_map"]["summary"]["candidate_count"] >= 6
    assert result["screen_map"]["sections"][0]["contract_version"] == "screen_map_section_v1"
    assert result["screen_map"]["candidates"][0]["label"] == "Filter"
    assert result["screen_map"]["candidates"][0]["section_id"]
    assert result["screen_map"]["candidates"][0]["risk_class"] == "safe_click_allowed"
    assert result["screen_map"]["candidates"][0]["expected_effect"] == "filter panel opens"
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
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
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
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
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
    assert start["coordinate_source"] == "vista_point_v1"
    assert start["vista_coordinate_validation"]["status"] == "valid"
    assert start["vista_coordinate_validation"]["model_io"]["raw_text"] == "[225, 328]"
    assert help_target["click_point"] == {"x": 200, "y": 58}
    assert help_target["vista_coordinate_validation"]["status"] == "needs_review"


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
