import json
from pathlib import Path

from PIL import Image

from scripts.prepare_learning_free_exploration_preflight import prepare_learning_free_exploration_preflight


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 12), "white").save(path)
    return path


def _baseline(path: Path) -> Path:
    return _write_json(
        path,
        {
            "archive_node": {
                "contract_version": "learning_protected_archive_node_v1",
                "checkpoint_id": "baseline",
                "cases": [],
            }
        },
    )


def test_preflight_blocks_until_trace_is_provided(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.prepare_learning_free_exploration_preflight.run_learning_exploration_readiness_check",
        lambda **kwargs: {
            "ready_for_new_interface_exploration": True,
            "summary": {"protected_set_passed": True},
        },
    )

    report = prepare_learning_free_exploration_preflight(
        baseline_path=_baseline(tmp_path / "baseline.json"),
        root=tmp_path,
    )

    assert report["status"] == "blocked_before_replay"
    assert "usable_non_protected_observe_trace_required" in report["blockers"]
    assert report["trace_classification"]["classification"] == "not_provided"
    assert report["required_capture"]["capture_route"] == "/vision/observe_screen"


def test_preflight_accepts_non_protected_observe_trace_with_inventory(tmp_path: Path, monkeypatch) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "calculator.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__calculator.json",
        {
            "result": {
                "image_path": str(image),
                "texts": [{"text": "Calculator"}],
                "ui_elements": [{"role": "button"}],
            }
        },
    )
    monkeypatch.setattr(
        "scripts.prepare_learning_free_exploration_preflight.run_learning_exploration_readiness_check",
        lambda **kwargs: {
            "ready_for_new_interface_exploration": True,
            "summary": {"protected_set_passed": True},
        },
    )

    report = prepare_learning_free_exploration_preflight(
        trace_path=trace,
        baseline_path=_baseline(tmp_path / "baseline.json"),
        root=tmp_path,
    )

    assert report["status"] == "ready_for_no_click_free_exploration_replay"
    assert report["trace_classification"]["classification"] == "usable_non_protected_observe_trace"
    assert "run_learning_free_exploration_from_trace.py" in report["next_command"]
    assert report["safety_boundary"]["live_clicks"] == 0


def test_preflight_rejects_protected_trace(tmp_path: Path, monkeypatch) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "applemusic.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__applemusic.json",
        {"result": {"image_path": str(image), "texts": [{"text": "Music"}]}},
    )
    monkeypatch.setattr(
        "scripts.prepare_learning_free_exploration_preflight.run_learning_exploration_readiness_check",
        lambda **kwargs: {
            "ready_for_new_interface_exploration": True,
            "summary": {"protected_set_passed": True},
        },
    )

    report = prepare_learning_free_exploration_preflight(
        trace_path=trace,
        baseline_path=_baseline(tmp_path / "baseline.json"),
        root=tmp_path,
    )

    assert report["status"] == "blocked_before_replay"
    assert report["trace_classification"]["classification"] == "protected_baseline_trace"
    assert "usable_non_protected_observe_trace_required" in report["blockers"]


def test_preflight_rejects_panel_self_observation_trace(tmp_path: Path, monkeypatch) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "panel.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__openclaw.json",
        {
            "result": {
                "image_path": str(image),
                "texts": [
                    {"text": "127.0.0.1:8000/panel?stage=learn_replay&learn_view=draft"},
                    {"text": "学习草稿"},
                ],
                "screen_map": {"image_path": str(image)},
            }
        },
    )
    monkeypatch.setattr(
        "scripts.prepare_learning_free_exploration_preflight.run_learning_exploration_readiness_check",
        lambda **kwargs: {
            "ready_for_new_interface_exploration": True,
            "summary": {"protected_set_passed": True},
        },
    )

    report = prepare_learning_free_exploration_preflight(
        trace_path=trace,
        baseline_path=_baseline(tmp_path / "baseline.json"),
        root=tmp_path,
    )

    assert report["status"] == "blocked_before_replay"
    assert report["trace_classification"]["classification"] == "panel_self_observation_trace"
    assert "usable_non_protected_observe_trace_required" in report["blockers"]
