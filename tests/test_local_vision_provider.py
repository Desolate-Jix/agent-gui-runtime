from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from PIL import Image

from app.vision.local_provider import LocalVisionProvider
from app.vision.schemas import VisionAnalyzeRequest


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_local_provider_calls_openai_compatible_vision_endpoint(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    model_json = {
        "provider": "local",
        "contract_version": "vision_regions_v1",
        "image_size": {"width": 200, "height": 120},
        "screen_summary": "demo screen",
        "state_guess": "demo_home",
        "regions": [
            {
                "region_id": "region_start",
                "label": "Start",
                "role": "button",
                "diagonal": {"x1": 20, "y1": 30, "x2": 90, "y2": 60},
                "description": "Start button that opens the next page.",
                "ocr_text": "Start",
                "text_lines": ["Start"],
                "possible_destinations": ["next_page"],
                "confidence": 0.91,
            }
        ],
        "targets": [],
        "observers": [],
        "notes": [],
    }

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:1234/v1/chat/completions"
        assert timeout == 12.0
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "Qwen3-VL-8B-Instruct-GGUF"
        assert body["max_tokens"] == 2048
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model_name="Qwen3-VL-8B-Instruct-GGUF",
        timeout_seconds=12,
    )
    result = provider.analyze(VisionAnalyzeRequest(image_path=str(image_path), app_name="demo"))

    assert result.provider == "Qwen3-VL-8B-Instruct-GGUF"
    assert result.screen_summary == "demo screen"
    assert result.state_guess == "demo_home"
    assert len(result.regions) == 1
    assert result.regions[0].bbox.to_dict() == {"x": 20, "y": 30, "w": 70, "h": 30}
    assert result.raw_text is not None
    assert result.raw_response is not None
    assert result.raw_response["attempts"][0]["status"] == "success"
    assert result.raw_response["contract_version"] == "provider_model_trace_v1"
    assert result.raw_response["raw_text"] == result.raw_text
    attempt_io = result.raw_response["attempts"][0]["model_io"]
    assert attempt_io["contract_version"] == "model_io_attempt_v1"
    assert attempt_io["input"]["prompt"]
    assert attempt_io["input"]["image_path"] == str(image_path)
    assert attempt_io["output"]["raw_text"] == result.raw_text
    assert attempt_io["output"]["parsed_model_json"]["screen_summary"] == "demo screen"


def test_local_provider_caps_fast_screen_understanding_output(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "observe.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["max_tokens"] == 2048
        prompt = body["messages"][1]["content"][0]["text"]
        assert "fast screen-understanding stage" in prompt
        assert "do not emit ocr_text" in prompt
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "screen_summary": "actionable screen",
                                    "regions": [],
                                    "targets": [],
                                    "observers": [],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)
    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions").analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert result.screen_summary == "actionable screen"
    assert result.raw_response["attempts"][0]["max_regions"] == 12


def test_local_provider_waits_for_loading_model_then_runs_same_attempt(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "loading-observe.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)
    calls: list[str] = []
    sleeps: list[float] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise HTTPError(
                request.full_url,
                503,
                "Service Unavailable",
                {},
                BytesIO(b'{"error":{"message":"Loading model"}}'),
            )
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "screen_summary": "loaded screen",
                                    "regions": [],
                                    "targets": [],
                                    "observers": [],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)
    monkeypatch.setattr("app.vision.local_provider.time.sleep", lambda seconds: sleeps.append(seconds))

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1240/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert len(calls) == 2
    assert sleeps == [1.0]
    assert result.screen_summary == "loaded screen"
    assert "model_loading_wait_retries=1" in result.notes
    assert len(result.raw_response["attempts"]) == 1


def test_local_provider_remaps_coordinates_from_scaled_inference_image(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "large-screen.png"
    Image.new("RGB", (2000, 1000), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][1]["content"][0]["text"]
        assert "image width = 1280" in prompt
        assert "image height = 640" in prompt
        model_json = {
            "provider": "local",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 1280, "height": 640},
            "screen_summary": "scaled demo screen",
            "state_guess": "demo_home",
            "regions": [
                {
                    "region_id": "region_scaled",
                    "label": "Scaled Button",
                    "role": "button",
                    "diagonal": {"x1": 128, "y1": 64, "x2": 512, "y2": 256},
                    "description": "Button from scaled inference.",
                    "ocr_text": "Scaled",
                    "text_lines": ["Scaled"],
                    "possible_destinations": [],
                    "confidence": 0.9,
                }
            ],
            "targets": [],
            "observers": [],
            "notes": [],
        }
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model_name="Qwen3-VL-8B-Instruct-GGUF",
        timeout_seconds=12,
    )
    result = provider.analyze(VisionAnalyzeRequest(image_path=str(image_path), app_name="demo"))

    assert result.image_size is not None
    assert result.image_size.to_dict() == {"width": 2000, "height": 1000}
    assert result.regions[0].bbox.to_dict() == {"x": 200, "y": 100, "w": 600, "h": 300}
    assert "coordinate_remap" in result.raw_response["attempts"][0]


def test_local_provider_recovers_normalized_1000_coordinates_before_scaled_image_remap(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "qq-window.png"
    Image.new("RGB", (820, 1303), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        model_json = {
            "provider": "local",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 806, "height": 1280},
            "screen_summary": "QQ window",
            "state_guess": "open",
            "regions": [
                {
                    "region_id": "close",
                    "label": "close window button",
                    "role": "button",
                    "diagonal": {"x1": 965, "y1": 10, "x2": 985, "y2": 30},
                    "confidence": 1.0,
                }
            ],
            "targets": [],
            "observers": [],
            "notes": [],
        }
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="click_target")
    )

    assert result.regions[0].bbox.to_dict() == {"x": 792, "y": 13, "w": 16, "h": 26}
    assert "coordinate_space_recovered=normalized_1000;items=1" in result.notes


def test_local_provider_scales_ocr_anchors_for_resized_inference_image(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "large-screen-with-anchors.png"
    Image.new("RGB", (2000, 1000), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][1]["content"][0]["text"]
        assert '"coordinate_space":"inference_image"' in prompt
        assert '[1,"Start",640,320,128,32,1]' in prompt
        model_json = {
            "provider": "local",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 1280, "height": 640},
            "screen_summary": "anchor demo",
            "state_guess": "demo_home",
            "regions": [],
            "targets": [],
            "observers": [],
            "notes": [],
        }
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model_name="Qwen3-VL-8B-Instruct-GGUF",
        timeout_seconds=12,
    )
    result = provider.analyze(
        VisionAnalyzeRequest(
            image_path=str(image_path),
            task="click_target",
            app_name="demo",
            metadata={
                "ocr_anchors": {
                    "contract_version": "ocr_anchors_v1",
                    "coordinate_space": "original_image",
                    "image_size": {"width": 2000, "height": 1000},
                    "anchor_count": 1,
                    "anchors": [
                        {
                            "anchor_id": "ocr_anchor_1",
                            "text": "Start",
                            "bbox": {"x": 1000, "y": 500, "w": 200, "h": 50},
                            "center": {"x": 1100, "y": 525},
                            "confidence": 0.98,
                            "goal_similarity": 0.9,
                        }
                    ],
                }
            },
        )
    )

    attempt = result.raw_response["attempts"][0]
    assert attempt["ocr_anchors"]["enabled"] is True
    assert attempt["ocr_anchors"]["coordinate_space"] == "inference_image"
    assert attempt["ocr_anchors"]["anchor_count"] == 1
    assert attempt["ocr_anchors"]["prompt_profile"] == "relation_matrix_compact"
    assert attempt["ocr_anchors"]["prompt_anchor_count"] == 1
    assert attempt["ocr_anchors"]["prompt_text_anchor_count"] == 1
    assert attempt["ocr_anchors"]["prompt_goal_match_count"] == 1
    assert attempt["ocr_anchors"]["prompt_focus_relation_count"] == 0


def test_local_provider_retries_with_compact_prompt_after_truncated_json(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "retry-screen.png"
    Image.new("RGB", (1800, 1200), color=(255, 255, 255)).save(image_path)
    call_prompts: list[str] = []

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][1]["content"][0]["text"]
        call_prompts.append(prompt)
        if len(call_prompts) == 1:
            return _FakeHTTPResponse({"choices": [{"message": {"content": "{\"regions\": ["}}]})
        model_json = {
            "provider": "local",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 1024, "height": 683},
            "screen_summary": "retry demo",
            "state_guess": "retry_state",
            "regions": [
                {
                    "region_id": "region_retry",
                    "label": "Retry Button",
                    "role": "button",
                    "diagonal": {"x1": 128, "y1": 128, "x2": 384, "y2": 256},
                    "description": "Recovered after retry.",
                    "ocr_text": "Retry",
                    "text_lines": ["Retry"],
                    "possible_destinations": [],
                    "confidence": 0.8,
                }
            ],
            "targets": [],
            "observers": [],
            "notes": [],
        }
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model_name="Qwen3-VL-8B-Instruct-GGUF",
        timeout_seconds=12,
    )
    result = provider.analyze(VisionAnalyzeRequest(image_path=str(image_path), app_name="demo"))

    assert len(call_prompts) == 2
    assert "compact mode is active" in call_prompts[1]
    assert result.screen_summary == "retry demo"
    assert len(result.raw_response["attempts"]) == 2
    assert result.raw_response["attempts"][0]["status"] == "failed"
    assert result.raw_response["attempts"][0]["model_io"]["output"]["raw_text"] == "{\"regions\": ["
    assert result.raw_response["attempts"][1]["status"] == "success"
    assert result.raw_response["attempts"][1]["model_io"]["status"] == "success"
    assert "provider_retry_count=1" in result.notes


def test_local_provider_failure_keeps_model_io_diagnostics(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "bad-json.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse({"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12)
    try:
        provider.analyze(VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen"))
    except RuntimeError as exc:
        diagnostics = getattr(exc, "diagnostics", {})
    else:
        raise AssertionError("expected invalid model JSON to fail")

    assert diagnostics["contract_version"] == "model_io_trace_v1"
    assert diagnostics["status"] == "failed"
    assert diagnostics["attempt_count"] == 2
    first_attempt = diagnostics["attempts"][0]
    assert first_attempt["status"] == "failed"
    assert first_attempt["model_io"]["input"]["prompt"]
    assert first_attempt["model_io"]["output"]["raw_text"] == "not json at all"


def test_local_provider_repairs_inner_quotes_in_json_strings(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "quote-screen.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"screen_summary":"news card with "quoted" title",'
                                '"state_guess":"news_home",'
                                '"regions":[],'
                                '"targets":[],'
                                '"observers":[]}'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert result.screen_summary == 'news card with "quoted" title'
    assert "json_repair=escaped_inner_string_quotes" in result.notes
    assert result.raw_response["attempts"][0]["status"] == "success"


def test_local_provider_repairs_missing_commas_between_json_fields(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "missing-comma-screen.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{\n'
                                '  "screen_summary": "google news page"\n'
                                '  "state_guess": "news_home",\n'
                                '  "regions": [],\n'
                                '  "targets": [],\n'
                                '  "observers": []\n'
                                '}'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert result.screen_summary == "google news page"
    assert result.state_guess == "news_home"
    assert "json_repair=inserted_missing_commas_before_keys" in result.notes


def test_local_provider_repairs_trailing_commas_and_raw_string_newlines(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "trailing-comma-screen.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{\n'
                                '  "screen_summary": "line one\nline two",\n'
                                '  "state_guess": "news_home",\n'
                                '  "regions": [],\n'
                                '  "targets": [],\n'
                                '  "observers": [],\n'
                                '}'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert result.screen_summary == "line one\nline two"
    assert "json_repair=removed_trailing_commas" in result.notes
    assert "json_repair=escaped_raw_string_newlines" in result.notes


def test_local_provider_repairs_truncated_regions_payload(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "truncated-screen.png"
    Image.new("RGB", (200, 120), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{\n'
                                '  "contract_version": "vision_regions_v1",\n'
                                '  "image_size": {"width": 200, "height": 120},\n'
                                '  "screen_summary": "google news page",\n'
                                '  "state_guess": "news_home",\n'
                                '  "regions": [\n'
                                '    {"region_id": "c1", "label": "Search", "role": "input", "diagonal": {"x1": 10, "y1": 10, "x2": 100, "y2": 30}, "description": "search", "confidence": 0.9},\n'
                                '    {"region_id": "c2", "label": "Menu", "role": "button", "diagonal": {"x1": 120, "y1": 10, "x2": 150, "y2": 30}, "description": "open menu", "confidence": 0.'
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    result = LocalVisionProvider(endpoint="http://127.0.0.1:1234/v1/chat/completions", timeout_seconds=12).analyze(
        VisionAnalyzeRequest(image_path=str(image_path), task="observe_screen")
    )

    assert result.screen_summary == "google news page"
    assert len(result.regions) == 1
    assert result.regions[0].label == "Search"
    assert "json_repair=closed_truncated_regions_payload" in result.notes


def test_local_provider_can_use_grid_overlay_reference(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "grid-screen.png"
    Image.new("RGB", (600, 400), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][1]["content"][0]["text"]
        assert "light coordinate grid" in prompt
        assert "major grid spacing is 120 pixels" in prompt
        assert "first estimate each bbox edge against the nearest visible grid lines" in prompt
        model_json = {
            "provider": "local",
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 600, "height": 400},
            "screen_summary": "grid demo",
            "state_guess": "grid_state",
            "regions": [],
            "targets": [],
            "observers": [],
            "notes": [],
        }
        return _FakeHTTPResponse({"choices": [{"message": {"content": json.dumps(model_json)}}]})

    monkeypatch.setattr("app.vision.local_provider.urlopen", fake_urlopen)

    provider = LocalVisionProvider(
        endpoint="http://127.0.0.1:1234/v1/chat/completions",
        model_name="Qwen3-VL-8B-Instruct-GGUF",
        timeout_seconds=12,
    )
    result = provider.analyze(
        VisionAnalyzeRequest(
            image_path=str(image_path),
            app_name="demo",
            metadata={"grid_overlay": {"enabled": True, "spacing": 120}},
        )
    )

    attempt = result.raw_response["attempts"][0]
    assert attempt["grid_overlay"]["enabled"] is True
    assert attempt["grid_overlay"]["spacing"] == 120
    assert Path(attempt["grid_overlay"]["artifact_path"]).exists()
    assert "grid_overlay_spacing=120px" in result.notes


def test_normalizer_keeps_string_notes_as_single_items() -> None:
    from app.vision.normalizer import normalizer

    result = normalizer.normalize(
        {
            "provider": "local",
            "screen_summary": "demo",
            "state_guess": "idle",
            "image_size": {"width": 10, "height": 10},
            "notes": "single note",
        },
        "local",
    )

    assert result.notes == ["single note"]
