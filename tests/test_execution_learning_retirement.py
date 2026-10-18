import pytest
from pydantic import ValidationError

from app.instant_mcp import InstantCommand, InstantSession


@pytest.mark.parametrize("kind", [
    "learning_start", "learning_status", "learning_stop", "learning_recover",
    "learning_event", "learning_review", "learning_projection", "learning_import",
    "learning_library", "learning_memory", "learning_save_interface", "learning_commit",
    "learning_project", "learning_reuse", "learning_adopt_source", "learning_template",
    "learning_feedback", "learning_workflow",
])
def test_learning_command_refused_before_session_side_effects(kind, tmp_path):
    with pytest.raises(ValidationError):
        InstantCommand.model_validate({"kind": kind, "request": {}})
    session = InstantSession(tmp_path, tmp_path / "data")
    with pytest.raises(ValidationError):
        session.submit("retired-learning", {"kind": kind, "request": {}})
    assert not (tmp_path / "commands").exists()


def test_execution_command_schema_retains_task_plan_and_actions():
    kinds = InstantCommand.model_json_schema()["properties"]["kind"]["enum"]
    assert {"step", "input_sequence", "form_fill", "task_plan", "capture"} <= set(kinds)
    assert not any(kind.startswith("learning_") for kind in kinds)
