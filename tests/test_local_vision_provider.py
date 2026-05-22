from __future__ import annotations

import json
from pathlib import Path

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


def test_local_provider_scales_ocr_anchors_for_resized_inference_image(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "large-screen-with-anchors.png"
    Image.new("RGB", (2000, 1000), color=(255, 255, 255)).save(image_path)

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        prompt = body["messages"][1]["content"][0]["text"]
        assert '"coordinate_space":"inference_image"' in prompt
        assert '"b":[640,320,128,32]' in prompt
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
    assert result.raw_response["attempts"][1]["status"] == "success"
    assert "provider_retry_count=1" in result.notes


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
