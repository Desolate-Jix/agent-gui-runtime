"""字段期望可持久复核，但不能通过引用夹带原文或改变填写语义。"""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent.text_field_evidence import prepare_text_field_expectation, validate_text_field_expectation_reference, verify_text_field_result_reference, validate_text_field_verification_reference
from app.agent.text_parameters import text_parameter_reference
from tests.test_text_field_evidence import snapshot, resolved


@pytest.mark.parametrize('clear', [True, False])
def test_reference_verifies_fresh_same_field_without_original_text(clear):
    local = prepare_text_field_expectation(snapshot('甲🙂乙', (1, 2)), resolved('新\r\n值', clear=clear))
    declaration = text_parameter_reference(local.parameters.reviewed)
    reference = local.to_reference()
    assert validate_text_field_expectation_reference(reference, declaration) == reference
    after = replace(local.before, value=local.expected_value, capture_id='fresh', read_id='fresh-read', observed_at_ns=200)
    assert verify_text_field_result_reference(reference, after, declaration_reference=declaration)['status'] == 'verified'
    wrong = replace(after, value='A' + after.value)
    assert verify_text_field_result_reference(reference, wrong, declaration_reference=declaration)['reason_code'] == 'text_value_mismatch'
    with pytest.raises(ValueError):
        bad = deepcopy(reference)
        bad['before']['value'] = 'secret'
        validate_text_field_expectation_reference(bad, declaration)
    with pytest.raises(ValueError):
        bad = deepcopy(reference)
        bad['expected_value_length'] += 1
        validate_text_field_expectation_reference(bad, declaration)


def test_reference_rejects_wrong_field_selection_and_replacement_hash():
    local = prepare_text_field_expectation(snapshot(), resolved())
    declaration = text_parameter_reference(local.parameters.reviewed)
    for mutate in [lambda r: r['before']['identity'].update(target_field_id='other'),
                   lambda r: r['before'].update(selection=[0, 99]),
                   lambda r: r.update(expected_value_sha256='a' * 64)]:
        reference = local.to_reference()
        mutate(reference)
        with pytest.raises(ValueError):
            validate_text_field_expectation_reference(reference, declaration)


def test_persisted_result_label_is_recomputed_and_cannot_hide_value_mismatch():
    local = prepare_text_field_expectation(snapshot(), resolved())
    declaration = text_parameter_reference(local.parameters.reviewed)
    after = replace(local.before, value='B', capture_id='fresh', read_id='fresh', observed_at_ns=200)
    proof = verify_text_field_result_reference(local.to_reference(), after, declaration_reference=declaration)
    assert validate_text_field_verification_reference(proof, declaration) == proof
    proof['actual']['value_sha256'] = 'a' * 64
    with pytest.raises(ValueError):
        validate_text_field_verification_reference(proof, declaration)
