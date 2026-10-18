from __future__ import annotations

import json
from pathlib import Path

import pytest


def _weights(root: Path, *, broken_index: bool = False) -> Path:
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"model_type": "qwen3_5"}), encoding="utf-8")
    (root / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (root / "processor_config.json").write_text("{}", encoding="utf-8")
    name = "../outside.safetensors" if broken_index else "model-00001-of-00001.safetensors"
    (root / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"layer": name}}), encoding="utf-8")
    if not broken_index:
        (root / name).write_bytes(b"not-empty")
    return root


def test_initializes_source_vista_configuration_without_starting_service(tmp_path: Path):
    from app.desktop_review.model_setup import initialize_vista_configuration

    result = initialize_vista_configuration(tmp_path / "configs" / "vision.json", _weights(tmp_path / "weights"))

    assert result["status"] == "configured_unverified"
    assert result["model_loaded"] is False and result["service_started"] is False
    profile = json.loads(Path(result["profile_path"]).read_text(encoding="utf-8"))
    config = json.loads(Path(result["config_path"]).read_text(encoding="utf-8"))
    assert Path(profile["model_path"]) == (tmp_path / "weights").resolve()
    assert profile["endpoint"] == "http://127.0.0.1:13244/v1/chat/completions"
    assert Path(profile["start_script"]).is_absolute()
    assert config["vision"]["mode"] == "local_grounding"


def test_existing_config_is_preserved_and_invalid_metadata_is_rejected(tmp_path: Path):
    from app.desktop_review.model_setup import ModelSetupError, initialize_vista_configuration

    config = tmp_path / "vision.json"; config.write_bytes(b"not-json-existing")
    with pytest.raises(ModelSetupError, match="model_setup_config_exists"):
        initialize_vista_configuration(config, _weights(tmp_path / "weights"))
    assert config.read_bytes() == b"not-json-existing"
    with pytest.raises(ModelSetupError, match="model_setup_model_metadata_invalid"):
        initialize_vista_configuration(tmp_path / "other.json", _weights(tmp_path / "bad", broken_index=True))


def test_frozen_profile_omits_source_launch_fields(tmp_path: Path, monkeypatch):
    import app.desktop_review.model_setup as setup

    internal = tmp_path / "_internal" / "configs" / "model_profiles"; internal.mkdir(parents=True)
    canonical = Path("configs/model_profiles/vista_4b_transformers.json").read_text(encoding="utf-8")
    (internal / "vista_4b_transformers.json").write_text(canonical, encoding="utf-8")
    monkeypatch.setattr(setup.sys, "frozen", True, raising=False)
    monkeypatch.setattr(setup.sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    result = setup.initialize_vista_configuration(tmp_path / "vision.json", _weights(tmp_path / "weights"))
    profile = json.loads(Path(result["profile_path"]).read_text(encoding="utf-8"))
    assert not {"start_script", "stop_script", "pid_file", "python_path"} & set(profile)


def test_publish_race_leaves_existing_config_and_no_orphan_profile(tmp_path: Path, monkeypatch):
    import app.desktop_review.model_setup as setup

    config = tmp_path / "vision.json"
    original_link = setup.os.link
    calls = []
    def race(stage, destination):
        calls.append(Path(destination))
        if Path(destination) == config:
            config.write_bytes(b"raced-existing")
        return original_link(stage, destination)
    monkeypatch.setattr(setup.os, "link", race)
    with pytest.raises(setup.ModelSetupError, match="model_setup_config_exists"):
        setup.initialize_vista_configuration(config, _weights(tmp_path / "weights"))
    assert config.read_bytes() == b"raced-existing"
    assert list((tmp_path / "model_profiles").glob("*.json")) == []


def test_official_single_weight_layout_configures_without_inference(tmp_path):
    from app.desktop_review.model_setup import initialize_vista_configuration
    root = _weights(tmp_path / "weights")
    (root / "model.safetensors.index.json").unlink()
    (root / "model-00001-of-00001.safetensors").rename(root / "model.safetensors")
    result = initialize_vista_configuration(tmp_path / "vision.json", root)
    assert result["status"] == "configured_unverified"
    assert not result["model_loaded"] and not result["service_started"]


@pytest.mark.parametrize("defect", ["missing", "empty", "malformed_index", "missing_shard"])
def test_single_file_does_not_hide_incomplete_or_broken_weights(tmp_path, defect):
    from app.desktop_review.model_setup import _model_directory, ModelSetupError
    root = _weights(tmp_path / "weights")
    index = root / "model.safetensors.index.json"
    if defect in {"missing", "empty"}:
        index.unlink()
        if defect == "empty":
            (root / "model.safetensors").write_bytes(b"")
    else:
        (root / "model.safetensors").write_bytes(b"single-weight")
        if defect == "malformed_index":
            index.write_text("{broken", encoding="utf-8")
        else:
            (root / "model-00001-of-00001.safetensors").unlink()
    with pytest.raises(ModelSetupError, match="model_setup_model_metadata_invalid"):
        _model_directory(root)
