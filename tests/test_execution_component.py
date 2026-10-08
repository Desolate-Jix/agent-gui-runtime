"""执行独立源码包闭合真实输入入口，拒绝学习界面依赖。"""
from pathlib import Path
import json

import pytest


def test_actual_mcp_initialization_reports_release_version():
    from app.instant_mcp import build_server
    server = build_server(None)
    assert server._lowlevel_server.create_initialization_options().server_version == "0.1.2-preview.2"


def test_checker_rejects_descriptor_version_different_from_actual_mcp(monkeypatch):
    from types import SimpleNamespace
    from app.learning_memory import execution_installation
    from scripts.check_execution_component import check
    monkeypatch.setattr(execution_installation, "load_execution_installation",
                        lambda root: SimpleNamespace(version="0.0.0-wrong"))
    with pytest.raises(ValueError, match="MCP version mismatch"):
        check(Path(__file__).resolve().parents[1])


def test_qt_dependency_is_rejected_instead_of_silently_excluded(tmp_path):
    from scripts.build_execution_component import reject_gui_dependencies
    path = tmp_path / "backend.py"
    path.write_text("from PySide6.QtWidgets import QWidget\n", encoding="utf-8")
    with pytest.raises(ValueError, match="GUI dependency"):
        reject_gui_dependencies(tmp_path, [path])


def test_real_payload_has_execution_identity_installer_manifest_and_isolated_input_evidence(tmp_path):
    from scripts.build_execution_component import build
    from scripts.build_component_installer import validate
    from app.learning_memory.execution_installation import load_execution_installation
    root = Path(__file__).resolve().parents[1]
    result = build(root, tmp_path / "execution", version="0.1.2-preview.2")
    payload = Path(result["directory"])
    installer_rows = validate(payload, result["installer_manifest"])
    assert all(set(row) == {"path", "size", "sha256"} for row in installer_rows)
    paths = {row["path"] for row in installer_rows}
    assert {"scripts/start_instant_mcp.py", "scripts/run_local_step_session.py",
        "scripts/start_instant_mcp_admin.py", "scripts/instant_admin_worker.py",
        "scripts/setup_instant.ps1", "scripts/configure_instant.ps1",
        "requirements/agent-runtime-win311.txt", "execution-installation.json"} <= paths
    assert "app/application_profiles/seek/application.py" in paths
    assert not any("workbench" in name or name.endswith(".qm") for name in paths)
    assert load_execution_installation(payload).version == "0.1.2-preview.2"
    evidence = json.loads(Path(result["verification_report"]).read_text(encoding="utf-8"))
    assert evidence["passed"] is True
    assert evidence["mcp_server_version"] == evidence["version"] == "0.1.2-preview.2"
    assert evidence["input_executed"] is False
    assert evidence["qt_imported"] is False
    assert evidence["image_feature_closure"]["passed"] is True
    assert evidence["image_feature_closure"]["png_match"]["matched"] is True
    assert evidence["image_feature_closure"]["strategies"] == ["learned", "steps_only"]
    assert evidence["isolated_real_input_entrypoints"]["passed"] is True
    assert all(row["handler_executed"] is False for row in
        evidence["isolated_real_input_entrypoints"]["operations"])
    with pytest.raises(FileExistsError):
        build(root, payload, version="other")
