"""本次原文只在拥有者内存中，持久预览使用精确摘要绑定。"""
from hashlib import sha256
import pytest
from app.agent.text_parameters import resolve_text_parameters
from test_native_text_input_dialog import parameters


def test_execution_reference_changes_with_value_but_never_contains_value():
    from app.agent.text_execution import text_execution_reference, validate_text_execution_reference
    from app.agent.text_parameters import text_parameter_reference

    reviewed = parameters()
    value = "本次私有值\r\n"
    resolved = resolve_text_parameters(reviewed, {"query": value})
    reference = text_execution_reference(resolved)
    assert reference["text_sha256"] == sha256(value.encode("utf-8")).hexdigest()
    assert reference["text_length"] == len(value)
    assert value not in repr(reference)
    assert reference != text_execution_reference(resolve_text_parameters(reviewed, {"query": "different"}))
    assert validate_text_execution_reference(reference, text_parameter_reference(reviewed)) == reference
    with pytest.raises(ValueError):
        validate_text_execution_reference(reference, text_parameter_reference(parameters("literal", "changed")))


def test_reference_rejects_missing_or_extra_original_text_and_invalid_length():
    from app.agent.text_execution import text_execution_reference, validate_text_execution_reference
    from app.agent.text_parameters import text_parameter_reference

    reviewed = parameters("literal", "")
    reference = text_execution_reference(resolve_text_parameters(reviewed, {}))
    assert reference["text_length"] == 0
    for damaged in ({**reference, "text": ""}, {**reference, "text_length": True}, {**reference, "text_length": 32769}, {}):
        with pytest.raises(ValueError):
            validate_text_execution_reference(damaged, text_parameter_reference(reviewed))
