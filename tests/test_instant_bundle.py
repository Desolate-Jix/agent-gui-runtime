"""交付白名单与清单边界，不启动输入宿主。"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts import build_instant_bundle as bundle


def seed(root):
    for name in bundle.ROOT_FILES + bundle.SCRIPTS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    for name in ("app/application_profiles/seek/scroll_containers.py", "app/seek/old.py",
                 "app/web_panel/old.py", "app/main.py", "app/api/panel.py",
                 "app/desktop_review/input_sequence.py", "app/__pycache__/x.pyc",
                 "tests/test_current.py", "docs/verification/current.md",
                 "models/weights.bin", "logs/private.json", "mcp-config.local.json",
                 "scripts/model_servers/runtime.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")


def test_source_selection_retains_dependencies_not_old_ui_or_private_data(tmp_path):
    root = tmp_path / "seek" / "source"
    seed(root)
    found = {p.relative_to(root).as_posix() for p in bundle.collect_sources(root)}
    assert "app/application_profiles/seek/scroll_containers.py" in found
    assert "app/desktop_review/input_sequence.py" in found
    assert "docs/verification/current.md" in found
    assert "tests/test_current.py" in found
    assert not any(x in found for x in ("app/seek/old.py", "app/web_panel/old.py",
        "app/main.py", "app/api/panel.py", "logs/private.json", "models/weights.bin", "mcp-config.local.json"))


def test_missing_required_source_fails_before_output(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle.build(tmp_path / "missing", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("entrypoint", (
    "app/desktop_review/entrypoint.py", "app/desktop_review/application.py",
    "app/agent_link/mcp_bridge.py",
))
def test_execution_bundle_excludes_learning_entrypoints_not_shared_runtime(tmp_path, entrypoint):
    seed(tmp_path)
    shared = ("app/desktop_review/host.py", "app/desktop_review/workspace.py",
              "app/agent_link/host.py", "app/agent_link/http_app.py", "app/agent_link/service.py",
              "app/learn/hybrid/windows_process_scope.py")
    for name in (entrypoint, *shared):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    found = {p.relative_to(tmp_path).as_posix() for p in bundle.collect_sources(tmp_path)}
    assert entrypoint not in found
    assert set(shared) <= found


def test_build_and_archive_only_ship_manifest_not_generated_junk(tmp_path, monkeypatch):
    source, out = tmp_path / "source", tmp_path / "delivery"
    seed(source)
    monkeypatch.setattr(bundle, "verify_entrypoints", lambda root: (root / "entrypoint-verification.json").write_text('{"passed":true}', encoding="utf-8"))
    bundle.build(source, out)
    (out / "private-session.json").write_text("secret", encoding="utf-8")
    result = bundle.archive(out)
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        assert not any("private-session" in name for name in archive.namelist())
        assert "delivery/docs/verification/current.md" in archive.namelist()
    assert result["sha256"] == hashlib.sha256(Path(result["zip"]).read_bytes()).hexdigest()


def test_archive_rejects_mutated_payload(tmp_path, monkeypatch):
    source, out = tmp_path / "source", tmp_path / "delivery"
    seed(source)
    monkeypatch.setattr(bundle, "verify_entrypoints", lambda root: (root / "entrypoint-verification.json").write_text('{"passed":true}', encoding="utf-8"))
    bundle.build(source, out)
    (out / "README.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        bundle.archive(out)


def test_build_never_overwrites_existing_delivery(tmp_path):
    with pytest.raises(FileExistsError):
        bundle.build(tmp_path, tmp_path)
