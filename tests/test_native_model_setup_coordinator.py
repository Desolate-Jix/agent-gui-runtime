from __future__ import annotations

import json
from pathlib import Path

import pytest


def _weights(root: Path) -> Path:
    root.mkdir()
    for name, value in (("config.json", {"model_type": "qwen3_5"}), ("tokenizer_config.json", {}), ("tokenizer.json", {}),
                        ("processor_config.json", {}), ("model.safetensors.index.json", {"weight_map": {"x": "a.safetensors"}})):
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    (root / "a.safetensors").write_bytes(b"x")
    return root


class _Facade:
    def list_reviewed_assets(self): return []


class _Host:
    def status(self): return {"phase": "ready"}
    def close(self): return None


def _coordinator(tmp_path: Path):
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    factory = lambda **_kwargs: pytest.fail("model runtime must not be created by setup")
    return NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), runtime_factory=factory,
                                       thread_initializer=lambda: None, thread_finalizer=lambda: None,
                                       vision_config_path=tmp_path / "vision.json")


def test_coordinator_configures_only_while_idle_without_runtime_creation(tmp_path: Path):
    coordinator = _coordinator(tmp_path)
    try:
        assert coordinator.model_setup_status()["service_started"] is False
        configured = coordinator.configure_vista_model(model_directory=str(_weights(tmp_path / "weights")))
        assert configured["status"] == "configured_unverified"
        assert Path(configured["config_path"]).is_file()
    finally:
        coordinator.shutdown()


def test_coordinator_rejects_setup_when_busy(tmp_path: Path):
    coordinator = _coordinator(tmp_path)
    try:
        coordinator._busy = True
        with pytest.raises(Exception) as error:
            coordinator.model_setup_status()
        assert error.value.code == "lifecycle_busy"
    finally:
        coordinator._busy = False
        coordinator.shutdown()
