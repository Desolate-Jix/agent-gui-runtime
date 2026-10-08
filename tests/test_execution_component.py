"""执行独立源码包闭合真实输入入口，拒绝学习界面依赖。"""
from pathlib import Path
import json

import pytest


def test_actual_mcp_initialization_reports_release_version():
    from app.instant_mcp import build_server
    server = build_server(None)
    assert server._lowlevel_server.create_initialization_options().server_version == "0.1.2-preview.3"


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


def test_public_task_plan_helper_and_runtime_are_collected_without_gui():
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    entries, _, sources = collect_execution_sources(root)
    paths = {path.relative_to(root).as_posix() for path in sources}
    assert "scripts/learning_benchmark_client.py" in entries
    assert {"scripts/learning_benchmark_client.py", "scripts/smoke_instant_mcp.py",
            "app/execution/task_plan_admission.py", "app/execution/task_plan_backend.py",
            "app/execution/task_plan_contract.py", "app/execution/task_plan_target.py",
            "app/execution/task_plan_verification.py"} <= paths


def test_public_plan_resources_include_current_usage_configuration_and_acceptance():
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    _, resources, _ = collect_execution_sources(root)
    assert {"docs/development/TASK_PLAN.md", "docs/development/EXTERNAL_VISION_BENCHMARK.md",
            "configs/vision-api-openai-luna.example.json",
            "docs/verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md"} <= set(resources)


def test_powershell_vista_worker_is_closed_with_local_launch_resources():
    import re
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    start = "scripts/model_servers/start_transformers_vision_server.ps1"
    script = (root / start).read_text(encoding="utf-8")
    worker = re.search(r'\$serverScript\s*=\s*Resolve-Path\s*\(Join-Path\s+\$root\s+"([^\"]+\.py)"\)', script)
    assert worker is not None
    relative = worker.group(1).replace("\\", "/")
    entries, resources, sources = collect_execution_sources(root)
    assert relative in entries
    assert {relative, "app/vision/model_workers/__init__.py"} <= {
        path.relative_to(root).as_posix() for path in sources}
    assert {start, "scripts/model_servers/stop_local_vision_server.ps1",
            "configs/model_profiles/vista_4b_transformers.json"} <= set(resources)


def test_real_payload_has_execution_identity_installer_manifest_and_isolated_input_evidence(tmp_path):
    from scripts.build_execution_component import build
    from scripts.build_component_installer import validate
    from app.learning_memory.execution_installation import load_execution_installation
    root = Path(__file__).resolve().parents[1]
    result = build(root, tmp_path / "execution", version="0.1.2-preview.3")
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
    assert load_execution_installation(payload).version == "0.1.2-preview.3"
    evidence = json.loads(Path(result["verification_report"]).read_text(encoding="utf-8"))
    assert evidence["passed"] is True
    assert evidence["mcp_server_version"] == evidence["version"] == "0.1.2-preview.3"
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
