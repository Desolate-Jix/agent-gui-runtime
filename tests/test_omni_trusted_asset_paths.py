from __future__ import annotations

from pathlib import Path

import pytest


def test_adapter_passes_only_its_trusted_asset_paths_to_worker_environment(tmp_path: Path) -> None:
    from app.learn.recognition.uei.omniparser_shadow_adapter import _offline_environment

    environment = _offline_environment(
        tmp_path / "cache",
        code_path=tmp_path / "trusted-code",
        weights_path=tmp_path / "trusted-weights",
    )

    assert environment["AGENT_GUI_UEI_OMNIPARSER_CODE_PATH"] == str((tmp_path / "trusted-code").resolve())
    assert environment["AGENT_GUI_UEI_OMNIPARSER_WEIGHTS_PATH"] == str((tmp_path / "trusted-weights").resolve())
    assert "AGENT_GUI_UEI_OMNIPARSER_CODE_PATH" not in _offline_environment(tmp_path / "cache")


def test_worker_consumes_trusted_asset_path_overrides_and_preserves_default_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_uei_omniparser_shadow_worker as worker
    from scripts import run_omniparser_learn_smoke as runner

    default_code = tmp_path / "default-code"
    default_weights = tmp_path / "default-weights"
    trusted_code = tmp_path / "trusted-code"
    trusted_weights = tmp_path / "trusted-weights"
    for path in (default_code, default_weights, trusted_code, trusted_weights):
        path.mkdir()
    image = tmp_path / "capture.png"
    image.write_bytes(b"capture")
    observed: list[tuple[Path, Path]] = []

    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "_load_profile",
        lambda: {"expected_paths": {"code_path": "default-code", "weights_path": "default-weights", "huggingface_cache_path": str(tmp_path / "cache")}},
    )
    monkeypatch.setattr(runner, "_preflight", lambda **kwargs: None)
    monkeypatch.setattr(
        runner,
        "_load_official_models",
        lambda code_path, weights_path, cache_path: observed.append((code_path, weights_path)) or (object(), object(), object(), object()),
    )
    monkeypatch.setattr(
        runner,
        "_run_once",
        lambda **kwargs: ([{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "element", "content": "x", "interactivity": True}], 1.0),
    )
    monkeypatch.setattr(
        "app.learn.recognition.omniparser_quality.filter_omniparser_candidates",
        lambda items, *, image_size: (items, {}),
    )

    monkeypatch.delenv("AGENT_GUI_UEI_OMNIPARSER_CODE_PATH", raising=False)
    monkeypatch.delenv("AGENT_GUI_UEI_OMNIPARSER_WEIGHTS_PATH", raising=False)
    worker._run(image, {"width": 10, "height": 10}, native_output=True)
    assert observed.pop() == (default_code, default_weights)

    monkeypatch.setenv("AGENT_GUI_UEI_OMNIPARSER_CODE_PATH", str(trusted_code))
    monkeypatch.setenv("AGENT_GUI_UEI_OMNIPARSER_WEIGHTS_PATH", str(trusted_weights))
    worker._run(image, {"width": 10, "height": 10}, native_output=True)
    assert observed.pop() == (trusted_code.resolve(), trusted_weights.resolve())


def test_worker_rejects_partial_or_relative_trusted_asset_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_uei_omniparser_shadow_worker as worker

    profile = {"expected_paths": {"code_path": "code", "weights_path": "weights"}}
    monkeypatch.setenv("AGENT_GUI_UEI_OMNIPARSER_CODE_PATH", str(tmp_path / "code"))
    monkeypatch.delenv("AGENT_GUI_UEI_OMNIPARSER_WEIGHTS_PATH", raising=False)
    with pytest.raises(ValueError, match="asset_path"):
        worker._asset_paths(profile)
    monkeypatch.setenv("AGENT_GUI_UEI_OMNIPARSER_WEIGHTS_PATH", "relative")
    with pytest.raises(ValueError, match="asset_path"):
        worker._asset_paths(profile)
