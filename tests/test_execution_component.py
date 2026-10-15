"""执行独立源码包闭合真实输入入口，拒绝学习界面依赖。"""
from pathlib import Path


def test_execution_payload_includes_maintained_startup_helper():
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    _, _, sources = collect_execution_sources(root)
    assert root / "scripts/execution_startup.py" in sources
import json
import re
from urllib.parse import unquote, urlsplit

import pytest


def test_actual_mcp_initialization_reports_release_version():
    from app.instant_mcp import build_server
    server = build_server(None)
    assert server._lowlevel_server.create_initialization_options().server_version == "0.1.5"


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
    assert {"scripts/learning_benchmark_client.py", "scripts/execution_client.py"} <= set(entries)
    assert {"scripts/learning_benchmark_client.py", "scripts/execution_client.py", "scripts/smoke_instant_mcp.py",
            "app/instant_receipt.py",
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


def test_provider_configuration_and_bilingual_homepage_resources_are_delivered():
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    _, resources, _ = collect_execution_sources(root)
    assert {"configs/decision-profile.providers.example.json",
        "docs/development/DECISION_PROVIDERS.md", "docs/development/DECISION_PROVIDERS.zh-CN.md",
        "README.zh-CN.md", "docs/EXECUTION_GUIDE.md", "docs/EXECUTION_GUIDE.zh-CN.md",
        "docs/assets/readme-hero.svg", "docs/assets/readme-hero.mobile.svg",
        "docs/assets/readme-hero.zh-CN.svg", "docs/assets/readme-hero.zh-CN.mobile.svg"} <= set(resources)


def test_copied_execution_sources_close_adaptive_protocol_and_linked_profile(tmp_path):
    from scripts.build_component_sources import copy_component_sources
    from scripts.build_execution_component import collect_execution_sources
    root = Path(__file__).resolve().parents[1]
    entries, resources, _ = collect_execution_sources(root)
    payload = tmp_path / "copied-execution"
    manifest = copy_component_sources(root, payload, entries, resources=resources)
    paths = {row["path"] for row in manifest["files"]}
    execution_documents = {"docs/development/TARGET_CHECK.md", "docs/development/SETTLED_OBSERVATION.md",
        "docs/verification/DECISION_PROMPT_BENCHMARK_20261015.md",
        "docs/development/DECISION_LUNA_REVIEW.md", "docs/development/TARGET_IDENTITY_REVIEW.md",
        "docs/verification/EXECUTION_SPEED_20261015.md", "docs/verification/GOOGLE_JAVA_FIXED_20261015.md",
        "docs/verification/TARGET_CHECK_PROMPT_20261014.md",
        "docs/verification/ORDINARY_REVIEW_TIMEOUT_20261014.md",
        "docs/verification/TARGET_CHECK_LIVE_20261014.md", "docs/verification/TARGET_CHECK_OFFLINE_20261014.md",
        "docs/verification/TARGET_IDENTITY_LIVE_20261014.md",
        "docs/verification/SYMBOL_CASCADE_CONTROLLED_20261014.md",
        "docs/verification/DECISION_CASCADE_AUDIT_20261014.md",
        "docs/verification/DECISION_CASCADE_REPLAY_20261014.md"}
    required = {"configs/decision-profile.adaptive.example.json",
        "configs/decision-profile.visual-execution.example.json", "configs/decision-profile.legacy.example.json",
        "docs/development/VISUAL_EXECUTION_INPUT.md", "docs/development/DECISION_CHOICE.md",
        "docs/development/EXTERNAL_VISION_API.md",
        "docs/verification/EXECUTION_STABLE_012_20261012.md",
        "docs/verification/RECORDING_OVERLAY_ALLOWLIST_20261012.md",
        "docs/verification/DEFAULT_REPLACE_20261012.md", "docs/LEARNING_PREVIEW_QUICKSTART.md",
        "app/judgment/adaptive_policy.py", "app/judgment/http_deadline.py", "app/execution/task_plan_review.py",
        "app/execution/task_plan_cancellation.py", "app/execution/task_plan_observation.py",
        "app/execution/task_plan_observation_capture.py",
        "app/execution/task_plan_manual_observation.py",
        "app/execution/task_plan_observation_delivery.py",
        "app/execution/task_plan_native_condition.py",
        "app/execution/task_plan_conditions.py", "app/judgment/condition_templates.py",
        "app/learning_memory/workflow_condition_templates.py",
        "app/learning_memory/runtime_verification.py", "app/learning_memory/decision_verification.py"} | execution_documents
    assert required <= paths
    assert all((payload / name).read_bytes() == (root / name).read_bytes() for name in required)
    assert not any(name.startswith("tests/") for name in paths)
    for reference in re.findall(r'\]\(([^)]+)\)', (payload / "README.md").read_text(encoding="utf-8")):
        target = urlsplit(reference)
        if not target.scheme and target.path:
            assert unquote(target.path) in paths, "packaged README link missing: " + reference
    for name in execution_documents:
        for reference in re.findall(r'\]\(([^)]+)\)', (payload / name).read_text(encoding="utf-8")):
            target = urlsplit(reference)
            if not target.scheme and target.path:
                linked = ((payload / name).parent / unquote(target.path)).resolve().relative_to(payload.resolve())
                assert linked.as_posix() in paths, "packaged execution document link missing: " + reference
    profile = json.loads((payload / "configs/decision-profile.adaptive.example.json").read_text(encoding="utf-8"))
    assert profile["contract_version"] == "decision_profile.v2" and profile["mode"] == "auto"
    assert profile["proactive_review"] is True and profile["review_policy"] == "adaptive"
    assert profile["decision_format"] == "choice"
    visual = json.loads((payload / "configs/decision-profile.visual-execution.example.json").read_text(encoding="utf-8"))
    assert visual["contract_version"] == "decision_profile.v2" and visual["mode"] == "auto"
    assert visual["decision_format"] == "choice"
    assert "The recorded click is inside the intended visible text input." in visual["auto_conditions"]
    legacy = json.loads((payload / "configs/decision-profile.legacy.example.json").read_text(encoding="utf-8"))
    assert legacy["contract_version"] == "decision_profile.v1" and legacy["mode"] == "shadow"


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
    result = build(root, tmp_path / "execution", version="0.1.5")
    payload = Path(result["directory"])
    installer_rows = validate(payload, result["installer_manifest"])
    assert all(set(row) == {"path", "size", "sha256"} for row in installer_rows)
    paths = {row["path"] for row in installer_rows}
    assert {"scripts/start_instant_mcp.py", "scripts/run_local_step_session.py",
        "scripts/execution_client.py",
        "scripts/start_instant_mcp_admin.py", "scripts/instant_admin_worker.py",
        "scripts/setup_instant.ps1", "scripts/configure_instant.ps1",
        "requirements/agent-runtime-win311.txt", "execution-installation.json"} <= paths
    assert "app/application_profiles/seek/application.py" in paths
    assert not any("workbench" in name or name.endswith(".qm") for name in paths)
    assert load_execution_installation(payload).version == "0.1.5"
    evidence = json.loads(Path(result["verification_report"]).read_text(encoding="utf-8"))
    assert evidence["passed"] is True
    assert evidence["mcp_server_version"] == evidence["version"] == "0.1.5"
    assert evidence["input_executed"] is False
    assert evidence["qt_imported"] is False
    assert evidence["entrypoints"]["execution_client"] == {"imported": True, "main_executed": False}
    assert evidence["image_feature_closure"]["passed"] is True
    assert evidence["image_feature_closure"]["png_match"]["matched"] is True
    assert evidence["image_feature_closure"]["strategies"] == ["learned", "steps_only"]
    assert evidence["isolated_real_input_entrypoints"]["passed"] is True
    assert all(row["handler_executed"] is False for row in
        evidence["isolated_real_input_entrypoints"]["operations"])
    with pytest.raises(FileExistsError):
        build(root, payload, version="other")
