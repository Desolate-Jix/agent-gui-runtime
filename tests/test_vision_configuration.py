from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

import app.vision.configuration as configuration
from app.vision.configuration import (
    VisionConfigurationError,
    load_formal_vision_configuration,
    load_vision_config,
    pinned_vision_configuration,
    resolve_vision_config_path,
)
from app.vision.factory import VisionProviderFactory


def _write_config(path: Path, vision: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"vision": vision}), encoding="utf-8")
    return path


def _local(**overrides: object) -> dict:
    value: dict[str, object] = {
        "mode": "local",
        "timeout_seconds": 10,
        "local": {"endpoint": "http://localhost:8080/v1", "model_name": "vision-model"},
    }
    value.update(overrides)
    return value


def test_default_resolution_is_project_root_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    expected = (root / "configs" / "vision.json").resolve()
    monkeypatch.chdir(tmp_path)
    assert resolve_vision_config_path(project_root=root) == expected


def test_explicit_path_is_read_directly_and_factory_delegates(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "direct.json", _local())
    assert resolve_vision_config_path(config_path) == config_path.resolve()
    assert load_vision_config(config_path)["vision"]["local"]["model_name"] == "vision-model"
    assert VisionProviderFactory.load_config(config_path)["vision"]["mode"] == "local"


def test_missing_and_malformed_config_do_not_create_placeholder(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        load_vision_config(missing)
    assert not missing.exists()

    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad json", encoding="utf-8")
    with pytest.raises(VisionConfigurationError) as error:
        load_vision_config(malformed)
    assert error.value.code == "vision_config_invalid"
    assert "bad json" not in str(error.value)

    non_utf8 = tmp_path / "non-utf8.json"
    non_utf8.write_bytes(b"\xffSECRET_TOKEN")
    with pytest.raises(VisionConfigurationError) as decode_error:
        load_vision_config(non_utf8)
    assert decode_error.value.code == "vision_config_invalid"
    assert "SECRET_TOKEN" not in str(decode_error.value)


def test_noarg_default_uses_source_root_not_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "source-root"
    default_path = _write_config(root / "configs" / "vision.json", _local())
    monkeypatch.setattr(configuration, "_source_project_root", lambda: root)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    assert load_vision_config()["vision"]["local"]["model_name"] == "vision-model"
    assert resolve_vision_config_path() == default_path.resolve()


def test_snapshot_is_immutable_and_returns_fresh_copies(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "vision.json", _local())
    snapshot = load_formal_vision_configuration(config_path)
    first = snapshot.to_dict()
    first["vision"]["local"]["model_name"] = "changed"
    assert snapshot.to_dict()["vision"]["local"]["model_name"] == "vision-model"
    assert "vision-model" not in repr(snapshot)


def test_pinned_snapshot_nesting_thread_isolation_and_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first_path = _write_config(tmp_path / "first.json", _local())
    second_path = _write_config(tmp_path / "second.json", _local(local={"endpoint": "http://localhost:8081", "model_name": "second"}))
    first = load_formal_vision_configuration(first_path)
    second = load_formal_vision_configuration(second_path)
    seen: list[str] = []
    missing_default = tmp_path / "no-default.json"
    monkeypatch.setattr(configuration, "resolve_vision_config_path", lambda path=None, **kwargs: missing_default if path is None else Path(path).resolve())

    with pinned_vision_configuration(first):
        assert load_vision_config()["vision"]["local"]["model_name"] == "vision-model"
        with pinned_vision_configuration(second):
            assert load_vision_config()["vision"]["local"]["model_name"] == "second"
        assert load_vision_config()["vision"]["local"]["model_name"] == "vision-model"

        def read_worker() -> None:
            try:
                load_vision_config()
            except FileNotFoundError:
                seen.append("un-pinned")

        worker = threading.Thread(target=read_worker)
        worker.start()
        worker.join()
    assert seen == ["un-pinned"]
    with pytest.raises(FileNotFoundError):
        load_vision_config()


def test_pinned_snapshot_resets_after_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = _write_config(tmp_path / "vision.json", _local())
    snapshot = load_formal_vision_configuration(config_path)
    missing_default = tmp_path / "no-default.json"
    monkeypatch.setattr(configuration, "resolve_vision_config_path", lambda path=None, **kwargs: missing_default if path is None else Path(path).resolve())
    with pytest.raises(RuntimeError):
        with pinned_vision_configuration(snapshot):
            raise RuntimeError("test reset")
    with pytest.raises(FileNotFoundError):
        load_vision_config()


def test_formal_errors_are_sanitized_and_distinguished(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(VisionConfigurationError) as missing_error:
        load_formal_vision_configuration(missing)
    assert missing_error.value.code == "vision_config_missing"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json SECRET_TOKEN", encoding="utf-8")
    with pytest.raises(VisionConfigurationError) as invalid_error:
        load_formal_vision_configuration(invalid)
    assert invalid_error.value.code == "vision_config_invalid"
    assert "SECRET_TOKEN" not in str(invalid_error.value)

    unconfigured = _write_config(tmp_path / "unconfigured.json", _local(local={"endpoint": "not-a-url", "model_name": "vision-model"}))
    with pytest.raises(VisionConfigurationError) as endpoint_error:
        load_formal_vision_configuration(unconfigured)
    assert endpoint_error.value.code == "vision_provider_not_configured"

    stub = _write_config(tmp_path / "stub.json", _local(local={"endpoint": "https://example.test", "model_name": "local_stub"}))
    with pytest.raises(VisionConfigurationError) as stub_error:
        load_formal_vision_configuration(stub)
    assert stub_error.value.code == "vision_provider_not_configured"

    api = _write_config(tmp_path / "api.json", _local(mode="api"))
    with pytest.raises(VisionConfigurationError) as api_error:
        load_formal_vision_configuration(api)
    assert api_error.value.code == "vision_provider_unimplemented"

    unsupported = _write_config(tmp_path / "unsupported.json", _local(mode="remote"))
    with pytest.raises(VisionConfigurationError) as unsupported_error:
        load_formal_vision_configuration(unsupported)
    assert unsupported_error.value.code == "vision_provider_unsupported"

    invalid_mode = _write_config(tmp_path / "invalid-mode.json", _local(mode=""))
    with pytest.raises(VisionConfigurationError) as mode_error:
        load_formal_vision_configuration(invalid_mode)
    assert mode_error.value.code == "vision_config_invalid"

    padded_endpoint = _write_config(tmp_path / "padded-endpoint.json", _local(local={"endpoint": " http://localhost:8080", "model_name": "vision-model"}))
    with pytest.raises(VisionConfigurationError) as endpoint_whitespace_error:
        load_formal_vision_configuration(padded_endpoint)
    assert endpoint_whitespace_error.value.code == "vision_provider_not_configured"

    model_with_stub_word = _write_config(tmp_path / "stub-word.json", _local(local={"endpoint": "http://localhost:8080", "model_name": "my-stub-capable-model"}))
    assert load_formal_vision_configuration(model_with_stub_word).mode == "local"


def test_relative_model_path_is_config_directory_relative_without_probing(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "nested" / "vision.json",
        _local(local={"endpoint": "http://localhost:8080", "model_name": "vision-model", "model_path": "weights/model.gguf"}),
    )
    snapshot = load_formal_vision_configuration(config_path)
    assert snapshot.to_dict()["vision"]["local"]["model_path"] == str((config_path.parent / "weights/model.gguf").resolve())

    invalid_path = _write_config(tmp_path / "invalid-model-path.json", _local(local={"endpoint": "http://localhost:8080", "model_name": "vision-model", "model_path": 7}))
    with pytest.raises(VisionConfigurationError) as error:
        load_formal_vision_configuration(invalid_path)
    assert error.value.code == "vision_config_invalid"

    home_relative = _write_config(tmp_path / "home-relative.json", _local(local={"endpoint": "http://localhost:8080", "model_name": "vision-model", "model_path": "~/weights/model.gguf"}))
    assert load_formal_vision_configuration(home_relative).to_dict()["vision"]["local"]["model_path"] == str(Path("~/weights/model.gguf").expanduser().resolve())


def test_factory_does_not_load_when_explicit_empty_config() -> None:
    provider = VisionProviderFactory.create(config={})
    assert provider.endpoint is None


def test_canonical_existing_project_config_keeps_legacy_resource_root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    model = root / "models/owned.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"synthetic model metadata fixture")
    path = _write_config(root / "configs/vision.json", _local(local={
        "endpoint": "http://localhost:8080", "model_name": "owned", "model_path": "models/owned.gguf"}))
    monkeypatch.setattr(configuration, "_source_project_root", lambda: root)
    snapshot = load_formal_vision_configuration(path)
    assert snapshot.to_dict()["vision"]["local"]["model_path"] == str(model)
    assert model.is_file()
    assert not (root / "configs/models").exists()


def test_cold_formal_config_inspection_does_not_import_providers_or_create_artifacts(tmp_path):
    import os
    import subprocess
    import sys

    selected = _write_config(tmp_path / "config/vision.json", _local())
    empty = tmp_path / "empty"
    empty.mkdir()
    code = (
        "import sys; from app.vision.configuration import load_formal_vision_configuration; "
        "load_formal_vision_configuration(sys.argv[1]); "
        "assert 'app.vision.local_provider' not in sys.modules; "
        "assert 'app.core.runtime_artifacts' not in sys.modules"
    )
    completed = subprocess.run([sys.executable, "-c", code, str(selected)], cwd=empty,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONUTF8="1"),
        capture_output=True, text=True, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr
    assert not list(empty.iterdir())
