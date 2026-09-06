import subprocess

import pytest

from scripts.check_learning_integration import build_commands, run_checks


def test_fast_has_only_named_offline_tests():
    commands = build_commands("fast", python="python-for-test")
    assert len(commands) == 1
    assert commands[0][:4] == ["python-for-test", "-m", "pytest", "-q"]
    assert commands[0][4:] == [
        "tests/test_learn_hybrid_target_selection.py",
        "tests/test_learn_hybrid_refinement_policy.py",
        "tests/test_learn_hybrid_selection_review.py",
        "tests/test_learn_hybrid_selection_comparison.py",
    ]


def test_integration_adds_explicit_js_without_glob_or_model_command():
    commands = build_commands("integration", python="python-for-test")
    assert commands[-1] == [
        "node", "--test", "tests/js/panel_learning_selection_review.test.cjs",
        "tests/js/panel_learning_hybrid_review.test.cjs",
        "tests/js/panel_learning_selection_flow.test.cjs",
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
    assert all("*" not in arg for command in commands for arg in command)


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
