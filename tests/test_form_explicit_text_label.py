"""结构化字段标签不能被自然语言中的 input/field 等词截断。"""
import json

import pytest

from app.desktop_review import form_fill
from app.operation.recognition.control_target import uia_action_identity_matches
from app.operation.recognition.text_match import explicit_target_label, explicit_target_role


@pytest.mark.parametrize("label", ["Text input", "Search field", "Email", 'Say "yes"',
    'Folder \\ name', 'Line\nTwo', '制表\t字段', '中文 "姓名"', 'Ending \\', 'Slash \\"quote"'])
def test_declared_label_reaches_recognition_as_exact_identity(monkeypatch, label):
    seen = []
    def run(coordinator, target, request, **kwargs):
        seen.append(request)
        return {"status": "completed", "phase": "returned", "steps": [], "action_executed": True,
                "input_check": {"status": "matched"}}
    monkeypatch.setattr(form_fill, "run_input_sequence", run)
    result = form_fill.run_form_fill(object(), {"handle": 1, "process_id": 2},
        {"fields": [{"kind": "text", "field_goal": "Click the Text input field",
                     "label": label, "text": "test"}]})
    assert result["status"] == "completed"
    assert explicit_target_label(seen[0]["field_goal"]) == label
    control = {"control_type": "Edit", "name": label, "patterns": ["Value"],
               "visible": True, "enabled": True}
    assert uia_action_identity_matches(control, goal=seen[0]["field_goal"])
    assert not uia_action_identity_matches({**control, "name": "Unrelated"}, goal=seen[0]["field_goal"])
    if label == 'Say "yes"':
        assert not uia_action_identity_matches({**control, "name": "Say \\"}, goal=seen[0]["field_goal"])


def test_escaped_label_preserves_suffix_role_and_alternative_detection():
    literal = json.dumps('Say "yes"')
    assert explicit_target_role(f"Click {literal} input field") == "input"
    assert explicit_target_label(f"Click {literal} or another input") is None


@pytest.mark.parametrize("goal,expected", [
    ("Click 'Don't save' button", "Don't save"),
    ('Click “姓名” input', "姓名"),
    ('Click "C:\\Users\\name" input', 'C:\\Users\\name'),
])
def test_natural_quoted_labels_keep_existing_interpretation(goal, expected):
    assert explicit_target_label(goal) == expected
