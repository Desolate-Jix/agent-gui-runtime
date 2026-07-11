import json
from pathlib import Path

from PIL import Image

import scripts.run_learning_free_exploration_from_trace as runner


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_image(path: Path, size: tuple[int, int] = (640, 360)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "white").save(path)
    return path


def _protected_ok(*_: object, **__: object) -> dict:
    return {
        "passed": True,
        "summary": {"failed": 0},
        "baseline_comparison": {"status": "pass", "mismatch_count": 0},
        "report": {"summary": {"failed": 0}},
    }


def test_free_exploration_blocks_protected_trace_before_replay(tmp_path: Path) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "applemusic.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__applemusic.json",
        {
            "result": {
                "image_path": str(image),
                "image_size": {"width": 640, "height": 360},
                "texts": [{"text": "Music", "bbox": {"x": 10, "y": 10, "w": 50, "h": 20}}],
            }
        },
    )

    report = runner.run_learning_free_exploration_from_trace(
        trace_path=trace,
        out_dir=tmp_path / "out",
        baseline_path="baseline.json",
        root=tmp_path,
    )

    assert report["status"] == "blocked_intake_gate"
    assert report["intake_classification"]["classification"] == "protected_baseline_trace"
    assert report["replay_report_path"] == ""
    assert report["safety_boundary"]["live_clicks"] == 0


def test_free_exploration_replays_usable_non_protected_trace_and_checks_protected_set(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image = _write_image(tmp_path / "artifacts" / "screenshots" / "notes.png")
    trace = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "20260711__learn-mode-fast-observe__notes.json",
        {
            "result": {
                "image_path": str(image),
                "image_size": {"width": 640, "height": 360},
                "texts": [
                    {"id": "title", "text": "Notes", "bbox": {"x": 20, "y": 20, "w": 90, "h": 24}},
                    {"id": "body", "text": "Today", "bbox": {"x": 120, "y": 120, "w": 120, "h": 28}},
                ],
                "screen_map": {
                    "image_path": str(image),
                    "sections": [
                        {
                            "section_id": "primary_area",
                            "role": "content",
                            "label": "Main",
                            "bbox": {"x": 0, "y": 0, "w": 640, "h": 360},
                        }
                    ],
                },
            }
        },
    )
    monkeypatch.setattr(runner, "_protected_comparison", _protected_ok)

    report = runner.run_learning_free_exploration_from_trace(
        trace_path=trace,
        out_dir=tmp_path / "out",
        baseline_path="baseline.json",
        root=tmp_path,
    )

    assert report["intake_classification"]["classification"] == "usable_non_protected_observe_trace"
    assert report["protected_before"]["passed"] is True
    assert report["protected_after"]["passed"] is True
    assert report["replay_report_path"]
    replay_path = tmp_path / report["replay_report_path"]
    assert replay_path.exists()
    assert report["status"] in {"replay_ready_for_visual_review", "replay_not_demo_ready"}
    assert report["safety_boundary"]["execute_binding_enabled"] is False
    assert report["safety_boundary"]["live_submits"] == 0
