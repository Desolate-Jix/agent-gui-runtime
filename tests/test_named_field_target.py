"""命名字段不能借任意输入框的角色或模型落点丢失完整标签。"""
import pytest

from app.operation.recognition.control_target import generic_field_target, uia_action_identity_matches


def field(name, *, kind="Edit", patterns=None):
    return {"name": name, "control_type": kind, "patterns": patterns or ["Value", "Text"],
            "visible": True, "enabled": True}


@pytest.mark.parametrize("goal,label", [
    ("Click the Quick search input box", "Quick search"),
    ("Right click inside the Google search input box", "Google search"),
    ("Locate the Email input field", "Email"),
    ("Focus in the Message text area", "Message"),
    ("Click the Quick search box", "Quick search"),
])
def test_named_field_requires_complete_label_and_field_role(goal, label):
    assert generic_field_target(goal) is False
    assert uia_action_identity_matches(field(label), goal=goal) is True
    for wrong in ["Address bar", "地址和搜索栏", "Search", "Quick", "current query", ""]:
        assert uia_action_identity_matches(field(wrong), goal=goal) is False
    assert uia_action_identity_matches(field(label, kind="Button", patterns=["Invoke"]), goal=goal) is False


@pytest.mark.parametrize("goal", [
    "Click the input box", "Right click inside the text area of the document",
    "Click the search input box", "Click within the search field", "Focus in the text area",
    "Locate an input field", "Click a textbox", "Click the textarea", "Click the combobox",
])
def test_genuine_generic_field_keeps_dynamic_value_identity(goal):
    assert generic_field_target(goal) is True
    assert uia_action_identity_matches(field("dynamic value"), goal=goal) is True


@pytest.mark.parametrize("goal", [
    "Click the word Quick inside the search input box",
    "Click Save inside the input box", "Click the button inside the text area",
    "Do not click the Quick search input box",
])
def test_contained_target_and_negation_do_not_become_named_field(goal):
    assert generic_field_target(goal) is False
    assert uia_action_identity_matches(field("dynamic value"), goal=goal) is False


def test_named_field_label_normalization_preserves_unicode_and_full_words():
    goal = "Click the Customer Email input box"
    assert uia_action_identity_matches(field("customer   email"), goal=goal)
    assert not uia_action_identity_matches(field("Email"), goal=goal)
    assert not uia_action_identity_matches(field("Customer Email backup"), goal=goal)
    assert uia_action_identity_matches(field("邮件地址"), goal="Click the 邮件地址 input box")


def test_structured_and_quoted_targets_keep_existing_exact_label_contract():
    target = {"contract_version": "recognition_control_target_v1", "label": "Quick search",
              "role": "input", "source_binding_sha256": "a" * 64}
    goal = "Click the Quick search input box"
    assert uia_action_identity_matches(field("Quick search"), goal=goal, control_target=target)
    assert not uia_action_identity_matches(field("Address bar"), goal=goal, control_target=target)
    assert not generic_field_target('Click the input labelled "Quick search"')
    assert uia_action_identity_matches(field("Quick search"), goal='Click the input labelled "Quick search"')


@pytest.mark.parametrize("goal", [
    "Right click the Google search input box at the top of the page",
    "Locate the Google search input box at the top of the page",
    "Right click inside the Google search input box containing Wikipedia Nelson",
])
def test_previously_generic_qualified_field_does_not_bind_arbitrary_dynamic_value(goal):
    assert generic_field_target(goal) is False
    assert not uia_action_identity_matches(field("TimaruDunedin", kind="ComboBox"), goal=goal)
    assert uia_action_identity_matches(field("Google search", kind="ComboBox"), goal=goal)
