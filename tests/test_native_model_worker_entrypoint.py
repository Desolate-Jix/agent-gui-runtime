"""冻结 VISTA worker 入口的无模型解析回归。"""
from __future__ import annotations

import builtins
import json

import pytest

from app.desktop_review import entrypoint
from app.vision.model_workers import vista_openai_server


def test_vista_main_accepts_explicit_argv_for_help_without_loading_model() -> None:
    with pytest.raises(SystemExit) as raised:
        vista_openai_server.main(["--help"])
    assert raised.value.code == 0


def test_frozen_worker_first_argument_forwards_only_vista_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded: list[list[str]] = []
    monkeypatch.setattr(vista_openai_server, "main", lambda argv: forwarded.append(argv) or 17)

    assert entrypoint.main(["--model-worker", "vista", "--help"]) == 17
    assert forwarded == [["--help"]]


def test_frozen_worker_rejects_missing_or_unknown_worker_before_gui() -> None:
    with pytest.raises(SystemExit) as missing:
        entrypoint.main(["--model-worker"])
    with pytest.raises(SystemExit) as unknown:
        entrypoint.main(["--model-worker", "other"])

    assert missing.value.code == 2
    assert unknown.value.code == 2


def test_model_worker_is_only_recognized_as_the_exact_first_argument() -> None:
    with pytest.raises(SystemExit) as raised:
        entrypoint.main(["--diagnostics", "--model-worker", "vista"])
    assert raised.value.code == 2


def test_frozen_vista_runtime_check_dispatches_without_model_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert entrypoint.main(["--model-worker", "vista", "--check-runtime"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model_loaded"] is False
    assert payload["inference_verified"] is False
    assert payload["status"] == "runtime_imports_verified"
    assert payload["imports"]["Qwen3_5ForConditionalGeneration"].endswith("Qwen3_5ForConditionalGeneration")
    assert payload["imports"]["Qwen3VLProcessor"].endswith("Qwen3VLProcessor")
    assert payload["imports"]["Qwen3VLVideoProcessor"].endswith("Qwen3VLVideoProcessor")
    assert payload["imports"]["Qwen2VLImageProcessorFast"].endswith("Qwen2VLImageProcessor")


def test_vista_serving_requires_model_path_before_runtime_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    inspected = []
    monkeypatch.setattr(vista_openai_server, "_inspect_runtime", lambda: inspected.append(True) or {})

    with pytest.raises(SystemExit) as raised:
        vista_openai_server.main([])

    assert raised.value.code == 2
    assert inspected == []


def test_vista_runtime_check_names_the_failed_required_dependency(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "transformers.models.qwen3_vl.video_processing_qwen3_vl":
            raise ImportError("synthetic missing VISTA video processor")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    assert vista_openai_server.main(["--check-runtime"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "runtime_imports_failed"
    assert payload["failed_dependency"] == "transformers.models.qwen3_vl.video_processing_qwen3_vl.Qwen3VLVideoProcessor"
