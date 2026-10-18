"""执行后控件布局变化不是更换字段；执行前仍要求原几何一致。"""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.agent.text_field_evidence import (
    prepare_text_field_expectation, validate_text_field_precondition,
    verify_text_field_result, verify_text_field_result_reference,
    validate_text_field_verification_reference,
)
from app.agent.text_parameters import text_parameter_reference
from tests.test_text_field_evidence import snapshot, resolved


def _grown_result():
    expected = prepare_text_field_expectation(snapshot(), resolved())
    actual = replace(expected.before, value=expected.expected_value, capture_id='after-layout',
        read_id='after-layout-read', observed_at_ns=200,
        identity=replace(expected.before.identity, control_bbox=(20, 30, 240, 40)))
    return expected, actual


def test_current_same_instance_result_retains_new_geometry_with_versioned_policy():
    expected, actual = _grown_result()
    declaration = text_parameter_reference(expected.parameters.reviewed)
    proof = verify_text_field_result(expected, actual)
    assert proof['status'] == 'verified'
    assert proof['contract_version'] == 'text_field_verification_v2'
    assert proof['actual']['identity']['control_bbox'] == [20, 30, 240, 40]
    assert proof['expected']['before']['identity']['control_bbox'] == [20, 30, 180, 40]
    assert verify_text_field_result_reference(expected.to_reference(), actual,
        declaration_reference=declaration) == proof
    assert validate_text_field_verification_reference(proof, declaration) == proof
    with pytest.raises(ValueError, match='precondition'):
        validate_text_field_precondition(expected, replace(actual, value=expected.before.value))


def test_legacy_geometry_mismatch_receipt_is_not_reinterpreted():
    expected, actual = _grown_result()
    proof = {'contract_version':'text_field_verification_v1', 'status':'not_verified',
        'reason_code':'text_field_identity_changed', 'expected':expected.to_reference(),
        'actual':actual.to_reference(), 'artifact_is_authorization':False}
    declaration = text_parameter_reference(expected.parameters.reviewed)
    assert validate_text_field_verification_reference(proof, declaration) == proof
    forged = deepcopy(proof)
    forged.update(status='verified', reason_code='none')
    with pytest.raises(ValueError):
        validate_text_field_verification_reference(forged, declaration)


@pytest.mark.parametrize('change', [
    {'runtime_id':(42, 999)}, {'process_id':9002}, {'process_create_time':1001.5},
    {'target_field_id':'another-field'}, {'window_handle':4343}, {'window_rect':(11, 20, 320, 200)},
])
def test_post_layout_cannot_relax_field_instance_or_window_binding(change):
    expected, actual = _grown_result()
    changed = replace(actual, identity=replace(actual.identity, **change))
    assert verify_text_field_result(expected, changed)['reason_code'] == 'text_field_identity_changed'


@pytest.mark.parametrize('change,reason', [
    ({'value':'wrong'}, 'text_value_mismatch'),
    ({'capture_id':'capture-1'}, 'text_field_read_not_new'),
    ({'read_id':'read-1'}, 'text_field_read_not_new'),
    ({'observed_at_ns':100}, 'text_field_read_not_new'),
    ({'source':'uia_text'}, 'text_field_identity_changed'),
])
def test_post_layout_still_checks_value_epoch_and_provider(change, reason):
    expected, actual = _grown_result()
    actual = replace(actual, **change)
    result = verify_text_field_result(expected, actual)
    assert result['reason_code'] == reason and result['status'] == 'not_verified'


def test_fresh_post_read_and_durable_receipt_accept_current_field_expansion(tmp_path):
    from tests.test_fresh_text_dispatch import _ready_text
    from app.agent.live_controller import LiveControllerDecision
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
    from app.agent.runtime_receipt_store import RuntimeReceiptStore
    with _ready_text(tmp_path) as (_host, owner, runtime, native_input, claims, session, _scope, cid, parameters):
        reader = owner._text_field_reader
        snapshot = owner._uia_provider.snapshot_window
        def expanded(bound):
            current = snapshot(bound)
            # 只在合成输入结束后改变当前 UIA，读取器继续返回请求中的真实当前几何。
            if native_input.calls and reader.value == parameters.text:
                current['controls'][0]['bbox'] = {'x': 10, 'y': 10, 'w': 140, 'h': 40}
            return current
        owner._uia_provider.snapshot_window = expanded
        result = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.effect_status == 'verified'
        proof = result.evidence.text_field_verification
        assert proof['contract_version'] == 'text_field_verification_v2'
        assert proof['actual']['identity']['control_bbox'] == [10, 10, 140, 40]
        assert proof['expected']['before']['identity']['control_bbox'] == [10, 10, 120, 40]
        assert reader.calls[-1]['target_bbox'] == (10, 10, 140, 40)
        assert reader.calls[-1]['click_point'] == (80, 30)
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=claims._receipt_store, create_layout=False)
        assert reopened.get_for_grounded_confirmation(confirmation_id=cid).phase == 'terminal'
        record = claims.load_terminal_receipt_record(session_id=session.session_id,
            observation_id=result.observation_id)
        reference = {'receipt_id': result.receipt_id, 'content_sha256': record.content_sha256}
        reloaded = RuntimeReceiptStore(project_root=claims.project_root, create_layout=False).get(reference)
        assert reloaded.runtime_receipt == RuntimeFreshResultReceipt.from_dict(result.model_dump(mode='json'))
        legacy = result.model_dump(mode='json')
        legacy['effect_status'] = 'not_verified'
        legacy['evidence']['text_field_verification'].update(contract_version='text_field_verification_v1',
            status='not_verified', reason_code='text_field_identity_changed')
        legacy_root = tmp_path / 'legacy-receipt-only'
        old_ref = RuntimeReceiptStore(project_root=legacy_root).put(legacy,
            backend_receipt=record.backend_receipt, next_observation=record.next_observation)
        old = RuntimeReceiptStore(project_root=legacy_root, create_layout=False).get(old_ref)
        assert old.runtime_receipt.effect_status == 'not_verified'
        assert old.runtime_receipt.evidence.text_field_verification['contract_version'] == 'text_field_verification_v1'
        assert RuntimeReceiptStore(project_root=claims.project_root, create_layout=False).get(reference) == reloaded
        assert runtime.consume_grounded_confirmation(confirmation_id=cid) == result
        assert len(native_input.calls) == 1


@pytest.mark.parametrize('mutation', [
    'runtime_id', 'window_handle', 'process_id', 'process_create_time', 'window_rect',
    'target_field_id', 'value_sha256', 'status', 'effect_status', 'version', 'downgrade',
])
def test_layout_receipt_parser_rejects_tampered_identity_value_and_policy(mutation):
    from tests.test_runtime_fresh_text_receipt import _receipt
    from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt, RuntimeFreshReceiptError
    expected, actual = _grown_result()
    value = _receipt(verification=verify_text_field_result(expected, actual))
    value['evidence']['text_parameters_ref'] = text_parameter_reference(expected.parameters.reviewed)
    value['evidence']['capture_id'] = expected.before.capture_id
    assert RuntimeFreshResultReceipt.from_dict(value).effect_status == 'verified'
    proof = value['evidence']['text_field_verification']
    changes = {'runtime_id': [42, 999], 'window_handle': 4343, 'process_id': 9002,
        'process_create_time': 1001.5, 'window_rect': [11, 20, 320, 200], 'target_field_id': 'other'}
    if mutation in changes:
        proof['actual']['identity'][mutation] = changes[mutation]
    elif mutation == 'value_sha256':
        proof['actual']['value_sha256'] = 'f' * 64
    elif mutation == 'status':
        proof['status'] = 'not_verified'
    elif mutation == 'effect_status':
        value['effect_status'] = 'not_verified'
    else:
        proof['contract_version'] = ('text_field_verification_v1' if mutation == 'downgrade'
            else 'text_field_verification_v999')
    with pytest.raises(RuntimeFreshReceiptError):
        RuntimeFreshResultReceipt.from_dict(value)
