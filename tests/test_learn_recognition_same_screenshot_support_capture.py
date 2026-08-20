from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import scripts.run_learn_recognition_actual_parser_batch as parser_batch
from scripts.run_learn_recognition_actual_parser_batch import run_actual_parser_batch
from scripts.capture_learn_recognition_same_screenshot_support import capture_same_screenshot_uia_support


class FakeScreenshotService:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path

    def capture_window(self, **kwargs):
        return {
            "image_path": str(self.image_path),
            "image_width": 120,
            "image_height": 80,
            "window_size": {"width": 120, "height": 80},
            "capture_purpose": kwargs.get("purpose"),
        }


class FakeUIAProvider:
    def snapshot_bound_window(self, *, max_controls: int = 250):
        return {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "window": {
                "handle": 1001,
                "title": "Fake window",
                "process_name": "fake.exe",
                "bbox": {"x": 0, "y": 0, "w": 120, "h": 80},
            },
            "control_count": 1,
            "controls": [
                {
                    "control_id": "uia_1_search",
                    "name": "Search",
                    "control_type": "Button",
                    "bbox": {"x": 10, "y": 12, "w": 40, "h": 20},
                    "screen_bbox": {"x": 110, "y": 212, "w": 40, "h": 20},
                    "enabled": True,
                    "visible": True,
                    "patterns": ["Invoke"],
                }
            ],
        }


def test_capture_same_screenshot_uia_support_writes_checksum_bound_evidence(tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(image_path)
    out_dir = tmp_path / "out"

    result = capture_same_screenshot_uia_support(
        out_dir=out_dir,
        app_name="fake_app",
        state_hint="fake_state",
        screenshot_service=FakeScreenshotService(image_path),
        uia_provider=FakeUIAProvider(),
        max_controls=25,
    )

    support_path = Path(result["support_path"])
    payload = json.loads(support_path.read_text(encoding="utf-8"))

    assert payload["contract_version"] == "learn_recognition_same_screenshot_support_v1"
    assert payload["support_type"] == "uia"
    assert payload["screenshot_path"] == str(image_path)
    assert payload["screenshot_sha256"] == result["screenshot_sha256"]
    assert payload["sources"]["uia"]["controls"][0]["name"] == "Search"
    assert payload["sources"]["uia"]["controls"][0]["patterns"] == ["Invoke"]
    assert payload["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }
    assert result["support_source_keys"] == ["uia"]
    assert result["uia_status"] == "ok"


def test_captured_uia_support_can_feed_actual_parser_batch(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(image_path)
    capture_result = capture_same_screenshot_uia_support(
        out_dir=tmp_path / "support",
        app_name="fake_app",
        screenshot_service=FakeScreenshotService(image_path),
        uia_provider=FakeUIAProvider(),
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "with_captured_uia_support",
                        "screenshot_path": str(image_path),
                        "supplemental_sources_path": capture_result["support_path"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    received: list[dict] = []

    def fake_smoke(**kwargs):
        received.append(kwargs)
        return {
            "status": "passed",
            "actual_model_call_in_this_run": True,
            "metrics": {
                "actual_parser_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                "parse_inventory": {"passed": 1, "attempted": 1, "rate": 1.0},
            },
            "counts": {
                "screen_inventory_count": 1,
                "accepted_for_grounding_count": 1,
                "grounding_eligible_count": 1,
                "review_only_count": 0,
            },
        }

    monkeypatch.setattr(parser_batch, "run_actual_parser_smoke", fake_smoke)

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "batch",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
    )

    assert received[0]["supplemental_sources"]["uia"]["controls"][0]["name"] == "Search"
    assert report["case_results"][0]["supplemental_source_validity"]["status"] == "checksum_match"
    assert report["case_results"][0]["supplemental_source_keys"] == ["uia"]
