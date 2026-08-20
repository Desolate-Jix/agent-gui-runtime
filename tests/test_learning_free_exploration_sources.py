import json
from pathlib import Path

from PIL import Image

from scripts.report_learning_free_exploration_sources import (
    classify_learning_trace_source,
    run_free_exploration_source_inventory,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 12), "white").save(path)
    return path


def test_classifies_non_protected_observe_trace_with_inventory_as_candidate(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "calculator.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__calculator.json",
        {
            "success": True,
            "result": {
                "image_path": str(image),
                "texts": [{"text": "Calculator"}],
                "ui_elements": [{"role": "button"}],
                "screen_map": {"image_path": str(image)},
            },
        },
    )

    result = classify_learning_trace_source(trace, root=tmp_path)

    assert result["candidate_for_free_exploration"] is True
    assert result["classification"] == "usable_non_protected_observe_trace"
    assert result["inventory_total"] >= 3


def test_classifies_protected_surface_as_not_candidate(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "apple-music.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__applemusic.json",
        {"result": {"image_path": str(image), "texts": [{"text": "Music"}]}},
    )

    result = classify_learning_trace_source(trace, root=tmp_path)

    assert result["candidate_for_free_exploration"] is False
    assert result["classification"] == "protected_baseline_trace"


def test_classifies_panel_self_observation_as_not_candidate(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "openclaw-console.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__openclaw.json",
        {
            "request": {"app_name": "openclaw_console_free_exploration"},
            "result": {
                "image_path": str(image),
                "texts": [
                    {
                        "text": (
                            "127.0.0.1:8000/panel?stage=learn_replay&learn_view=draft"
                        )
                    },
                    {"text": "学习草稿"},
                    {"text": "PathGraph"},
                ],
                "screen_map": {
                    "image_path": str(image),
                    "state_hint": "OpenClaw console screen",
                    "state_signature": {
                        "candidate_label_sample": [
                            "从学习草稿生成的只读预览",
                            "Welcome to Python.org",
                        ]
                    },
                },
            },
        },
    )

    result = classify_learning_trace_source(trace, root=tmp_path)

    assert result["candidate_for_free_exploration"] is False
    assert result["classification"] == "panel_self_observation_trace"
    assert "panel_self_observation_or_loaded_learning_artifact" in result["reasons"]


def test_classifies_model_test_and_missing_image_as_not_candidate(tmp_path: Path) -> None:
    model_trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__panel-model-test__demo-observe.json",
        {"success": True, "request": {"image_path": None}, "model_io": {"attempts": []}},
    )
    stale_trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__newapp.json",
        {"result": {"image_path": str(tmp_path / "missing.png"), "texts": [{"text": "New"}]}},
    )

    model_result = classify_learning_trace_source(model_trace, root=tmp_path)
    stale_result = classify_learning_trace_source(stale_trace, root=tmp_path)

    assert model_result["classification"] == "model_test_trace"
    assert model_result["candidate_for_free_exploration"] is False
    assert stale_result["classification"] == "missing_or_stale_image"
    assert stale_result["candidate_for_free_exploration"] is False


def test_inventory_counts_candidates_and_classes(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "notes.png")
    trace_dir = tmp_path / "logs" / "traces" / "vision"
    _write_json(
        trace_dir / "20260711__learn-mode-fast-observe__notes.json",
        {"result": {"image_path": str(image), "texts": [{"text": "Notes"}]}},
    )
    _write_json(
        trace_dir / "20260711__panel-model-test__demo-observe.json",
        {"request": {"image_path": None}, "model_io": {"attempts": []}},
    )

    report = run_free_exploration_source_inventory(trace_dir=trace_dir, root=tmp_path)

    assert report["scanned_trace_count"] == 2
    assert report["candidate_count"] == 1
    assert report["classification_counts"]["usable_non_protected_observe_trace"] == 1
    assert report["classification_counts"]["model_test_trace"] == 1
    assert report["next_action"] == "Use a candidate trace with scripts/run_learning_free_exploration_from_trace.py"
    assert report["intake_gate"]["allowed"] is True
    assert report["intake_gate"]["status"] == "ready_for_safe_free_exploration"


def test_inventory_gate_allows_candidate_while_reporting_rejected_stale_sources(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "notes.png")
    trace_dir = tmp_path / "logs" / "traces" / "vision"
    _write_json(
        trace_dir / "20260711__learn-mode-fast-observe__notes.json",
        {"result": {"image_path": str(image), "texts": [{"text": "Notes"}]}},
    )
    _write_json(
        trace_dir / "20260711__learn-mode-fast-observe__stale.json",
        {"result": {"image_path": str(tmp_path / "missing.png"), "texts": [{"text": "Stale"}]}},
    )

    report = run_free_exploration_source_inventory(trace_dir=trace_dir, root=tmp_path)

    assert report["candidate_count"] == 1
    assert report["classification_counts"]["missing_or_stale_image"] == 1
    assert report["intake_gate"]["allowed"] is True
    assert report["intake_gate"]["blockers"] == []
    assert "missing_or_stale_image_not_allowed" in report["intake_gate"]["rejected_source_warnings"]


def test_inventory_gate_blocks_screenshot_only_or_inventory_missing_source(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "plain.png")
    trace_dir = tmp_path / "logs" / "traces" / "vision"
    _write_json(
        trace_dir / "20260711__learn-mode-fast-observe__plain.json",
        {"result": {"image_path": str(image)}},
    )

    report = run_free_exploration_source_inventory(trace_dir=trace_dir, root=tmp_path)

    assert report["candidate_count"] == 0
    assert report["classification_counts"]["image_without_observe_inventory"] == 1
    assert report["intake_gate"]["allowed"] is False
    assert report["intake_gate"]["status"] == "blocked_until_real_observe_capture"
    assert "no_usable_non_protected_observe_trace" in report["intake_gate"]["blockers"]
    assert "screenshot_only_or_inventory_missing_not_allowed" in report["intake_gate"]["blockers"]
