import json
from pathlib import Path
import subprocess

import pytest

from scripts.check_learning_integration import build_commands, run_checks


def test_fast_has_only_named_offline_tests():
    commands = build_commands("fast", python="python-for-test")
    assert len(commands) == 1
    assert commands[0][:6] == ["python-for-test", "-m", "pytest", "-q", "-p", "no:xdist"]
    assert commands[0][6:] == [
        "tests/test_learn_hybrid_target_selection.py",
        "tests/test_learn_hybrid_refinement_policy.py",
        "tests/test_learn_hybrid_selection_review.py",
        "tests/test_learn_hybrid_selection_comparison.py",
    ]


def test_integration_adds_explicit_js_without_glob_or_model_command():
    commands = build_commands("integration", python="python-for-test")
    assert commands[-1] == [
        "node", "--test", "--test-concurrency=1", "tests/js/panel_learning_selection_review.test.cjs",
        "tests/js/panel_learning_hybrid_review.test.cjs",
        "tests/js/panel_learning_selection_flow.test.cjs",
        "tests/js/interface_workflow_v2_panel.test.cjs",
        "tests/js/agent_runtime_panel.test.cjs",
        "tests/js/panel_primary_navigation.test.cjs",
    ]
    assert "tests/test_learning_workflow_selection_mode.py" in commands[0]
    assert "tests/test_panel_selection_rollout_boundary.py" in commands[0]
    assert "tests/test_learning_selection_public_flow.py" in commands[0]
    assert "tests/test_learning_selection_roundtrip.py" in commands[0]
    assert "tests/test_learning_selection_save_integrity.py" in commands[0]
    assert "tests/test_learning_selection_actual_flow.py" in commands[0]
    assert "tests/test_learning_static_capture.py" in commands[0]
    assert "tests/test_learning_selection_actual_origin.py" in commands[0]
    assert "tests/test_learning_selection_refinement.py" in commands[0]
    assert "tests/test_learning_vista_current_source.py" in commands[0]
    assert "tests/test_learning_selection_acceptance_catalog.py" in commands[0]
    assert "tests/test_learning_selection_acceptance_runner.py" in commands[0]
    assert "tests/test_learning_selection_acceptance_export.py" in commands[0]
    assert "tests/test_start_test_panel_launcher.py" in commands[0]
    assert "tests/test_development_state_paths.py" in commands[0]
    assert "tests/test_learning_asset_readonly_compatibility.py" in commands[0]
    assert "tests/test_learning_new_asset_offline.py" in commands[0]
    assert "tests/test_learning_new_asset_agent_roundtrip.py" in commands[0]
    assert "tests/test_agent_observation_compiled_projection.py" in commands[0]
    assert "tests/test_runtime_contracts.py::test_dataflow_requires_latest_detail_snapshot_for_downstream_steps" in commands[0]
    assert all("*" not in arg for command in commands for arg in command)


def test_npm_test_matches_the_serial_offline_js_runner_selection():
    package = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8"))
    expected = " ".join(build_commands("integration", python="python-for-test")[-1])

    assert package["scripts"]["test"] == expected


def test_fixed_runner_does_not_inherit_external_test_selection_or_plugins(monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "tests/not_in_the_offline_set.py")
    monkeypatch.setenv("PYTEST_PLUGINS", "unreviewed_plugin")
    environments = []

    def capture(command, **kwargs):
        environments.append(kwargs.get("env", {}))

    assert run_checks("integration", runner=capture) == 0
    assert len(environments) == 2
    for environment in environments:
        assert environment.get("PYTEST_ADDOPTS") == ""
        assert environment.get("PYTEST_PLUGINS") == ""
        assert environment.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1"
        assert environment.get("CUDA_VISIBLE_DEVICES") == ""
        assert environment.get("AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH") == ":memory:"


def test_windows_offline_workflow_uses_the_existing_no_model_entrypoint():
    workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/offline-learning.yml").read_text(encoding="utf-8")

    for required in (
        "runs-on: windows-latest",
        "timeout-minutes: 20",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD: \"1\"",
        "CUDA_VISIBLE_DEVICES: \"\"",
        "HF_HUB_OFFLINE: \"1\"",
        "TRANSFORMERS_OFFLINE: \"1\"",
        "OMP_NUM_THREADS: \"1\"",
        "actions/setup-python@v7",
        "python-version: \"3.11\"",
        "actions/setup-node@v6",
        "node-version: \"22\"",
        "astral-sh/setup-uv@v9",
        "uv sync --locked --group dev",
        "uv run python scripts/check_learning_integration.py --suite integration",
    ):
        assert required in workflow
    assert "model_servers" not in workflow
    assert "run_learning_selection_actual" not in workflow


def test_failures_return_nonzero_and_stop_without_false_success():
    calls = []

    def fail(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(5, command)

    assert run_checks("integration", runner=fail) == 5
    assert len(calls) == 1


def test_missing_command_is_reported_as_failure():
    def absent(command, **kwargs):
        raise FileNotFoundError("node is unavailable")

    assert run_checks("integration", runner=absent) != 0


def test_unknown_suite_is_rejected():
    with pytest.raises(ValueError):
        build_commands("all-models", python="python-for-test")
