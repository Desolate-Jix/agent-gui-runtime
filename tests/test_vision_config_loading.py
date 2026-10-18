"""配置读取不得创建占位文件或掩盖部署缺失。"""
import json
from pathlib import Path

import pytest

from app.vision.factory import VisionProviderFactory
from app.vision.configuration import VisionConfigurationError


@pytest.mark.parametrize("explicit", [False, True])
def test_missing_vision_config_fails_without_creating_directories(tmp_path, monkeypatch, explicit):
    import app.vision.configuration as configuration
    monkeypatch.setattr(configuration, "_source_project_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "chosen" / "vision.json" if explicit else tmp_path / "configs" / "vision.json"
    with pytest.raises(FileNotFoundError) as caught:
        VisionProviderFactory.load_config(missing) if explicit else VisionProviderFactory.load_config()
    assert Path(caught.value.filename) == missing
    assert not missing.exists()
    assert not missing.parent.exists()


def test_explicit_vision_config_preserves_utf8_and_source_bytes(tmp_path, monkeypatch):
    selected = tmp_path / "selected.json"
    config = {"vision": {"mode": "local", "local": {"model_name": "\u4e2d\u6587\u6a21\u578b", "endpoint": "http://127.0.0.1:1"}}}
    raw = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    selected.write_bytes(raw)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert VisionProviderFactory.load_config(selected) == config
    assert selected.read_bytes() == raw
    assert not list(elsewhere.iterdir())


def test_malformed_vision_config_is_not_replaced_with_default(tmp_path):
    selected = tmp_path / "broken.json"
    selected.write_bytes(b"{invalid json}")
    with pytest.raises(VisionConfigurationError) as caught:
        VisionProviderFactory.load_config(selected)
    assert caught.value.code == "vision_config_invalid"
    assert selected.read_bytes() == b"{invalid json}"
