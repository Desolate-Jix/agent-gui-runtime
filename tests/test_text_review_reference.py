from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.action_parameters import reviewed_action_parameter_fields
from app.agent.text_parameters import (
    ReviewedTextParameters, text_parameter_fields, text_parameter_reference,
    validate_text_parameter_reference,
)

LITERAL = {
    "contract_version": "reviewed_text_parameters_v1", "target_field_id": "open",
    "content": {"kind": "literal", "text": "秘密\n文本"}, "clear_existing": True,
    "sensitive": True, "submit": False, "clipboard_policy": "restore_previous",
}
VARIABLE = {**LITERAL, "content": {"kind": "variable", "name": "query_text"}, "sensitive": False}

@pytest.mark.parametrize("payload", [LITERAL, VARIABLE])
def test_text_reference_is_canonical_and_never_projects_source_value(payload):
    reviewed = ReviewedTextParameters.from_payload(payload)
    reference = text_parameter_reference(reviewed)
    assert validate_text_parameter_reference(reference) == reference
    assert "秘密" not in str(reference)
    assert reference["variable_name"] == ("query_text" if payload is VARIABLE else None)
    assert text_parameter_fields({"semantic_action": "fill_field", "text_parameters": payload}) == {"text_parameters_ref": reference}
    assert reviewed_action_parameter_fields({"semantic_action": "fill_field", "text_parameters_ref": reference}) == {"text_parameters_ref": reference}

def test_text_reference_rejects_raw_reference_mixing_and_nonfill_leakage():
    reference = text_parameter_reference(ReviewedTextParameters.from_payload(LITERAL))
    with pytest.raises(ValueError):
        text_parameter_fields({"semantic_action": "fill_field", "text_parameters": LITERAL, "text_parameters_ref": reference})
    with pytest.raises(ValueError):
        text_parameter_fields({"semantic_action": "open_detail", "text_parameters_ref": reference})
    with pytest.raises(ValueError):
        validate_text_parameter_reference({**reference, "variable_name": "leak"})
