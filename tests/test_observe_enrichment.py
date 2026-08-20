from __future__ import annotations

import inspect

from app.operation.observe.contracts import ObserveScreenTaskInput


def test_screen_map_builder_creates_read_only_candidate_map() -> None:
    from app.learn.observe_enrichment.screen_map_builder import (
        build_observation_screen_map,
    )

    screen_map = build_observation_screen_map(
        {
            "image_size": {"width": 800, "height": 600},
            "state_guess": "settings",
            "screen_summary": "Settings screen with a Save button.",
            "screen_reading": {
                "ui": {
                    "elements": [
                        {
                            "id": "save",
                            "label": "Save",
                            "type": "button",
                            "bbox": {"x": 620, "y": 520, "w": 100, "h": 40},
                            "click_point": {"x": 670, "y": 540},
                            "confidence": 0.92,
                        }
                    ]
                }
            },
        },
        task=ObserveScreenTaskInput(
            app_name="sample_app",
            capture_live=False,
            image_path="sample.png",
        ),
        image_path="sample.png",
    )

    assert screen_map["contract_version"] == "screen_map_v1"
    assert screen_map["state_id"].startswith("state_")
    candidate = next(item for item in screen_map["candidates"] if item["candidate_id"] == "save")
    assert candidate["label"] == "Save"
    assert candidate["risk_class"] == "safe_dry_run_only"
    assert "execution_authorized" not in candidate
    assert "locate" in screen_map["agent_usage"]["locate_role"].casefold()


def test_observe_enrichment_modules_do_not_import_api() -> None:
    from app.learn.observe_enrichment import path_graph, screen_map_builder

    source = inspect.getsource(screen_map_builder) + inspect.getsource(path_graph)

    assert "app.api" not in source
    assert "fastapi" not in source
