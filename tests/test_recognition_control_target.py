import pytest

from app.api.vision import _vista_direct_prompt
from app.operation.recognition.control_target import control_target_matches, uia_control_matches, validate_control_target


def target():
    return {"contract_version": "recognition_control_target_v1", "label": "搜索", "role": "button", "source_binding_sha256": "a" * 64}


def test_control_target_is_strict_and_normalized():
    assert validate_control_target({**target(), "label": "  搜索  "})["label"] == "搜索"
    with pytest.raises(ValueError):
        validate_control_target({**target(), "role": "meaning"})
    with pytest.raises(ValueError):
        validate_control_target({**target(), "source_binding_sha256": "x"})


def test_target_matches_exact_label_and_closed_uia_role():
    value = validate_control_target(target())
    assert control_target_matches("搜索", "button", value)
    assert not control_target_matches("搜索", "input", value)
    assert uia_control_matches({"name": "搜索", "control_type": "Button"}, value)
    assert not uia_control_matches({"name": "搜索", "control_type": "RadioButton"}, value)


def test_target_prompt_keeps_operation_description_and_has_no_bbox():
    prompt = _vista_direct_prompt("Click 搜索 after entering a query.", target())
    assert 'exact visible button "搜索"' in prompt
    assert "Click 搜索 after entering a query." in prompt
    assert "bbox" not in prompt


def test_target_rejects_non_string_and_static_unknown_uia():
    with pytest.raises(ValueError):
        validate_control_target({**target(), "label": ["搜索"]})
    value = validate_control_target({**target(), "role": "control"})
    assert not uia_control_matches({"name": "搜索", "control_type": "Pane", "enabled": True, "visible": True, "patterns": ["Invoke"]}, value)
