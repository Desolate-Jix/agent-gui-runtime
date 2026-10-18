"""宿主必须独立绑定预览模式，不能接受错误 callsite 换成另一模式回执。"""
import pytest

from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
from app.desktop_review.single_step import NativeSingleStepController, NativeSingleStepError
from tests.test_fresh_learning_action_preview import _setup
from tests.test_fresh_dispatch_graph import _close


@pytest.mark.parametrize('enabled', [True, False])
def test_host_rejects_opposite_mode_receipt_and_retains_owner(tmp_path, monkeypatch, enabled):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    monkeypatch.setattr(runtime, '_automatic_safety_interception', enabled)
    controller = NativeSingleStepController()
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        grounded = claim.grounded_confirmation
        identity = grounded.confirmation_id
        receipt = RuntimeFreshResultReceipt.from_dict({
            'contract_version': 'runtime_fresh_result_receipt_v2' if enabled else 'runtime_fresh_result_receipt_v1',
            'receipt_id': 'receipt.wrong-mode', 'issued_at': '2026-09-13T00:00:00Z',
            'session_id': claim.observation.session_id, 'observation_id': claim.observation.observation_id,
            'intent_id': claim.intent.intent_id, 'source_sha256': claim.server_binding.source_sha256,
            'action': {'action_id': intent.action_id, 'semantic_action': 'open_detail'},
            'outcome': 'EXECUTION_FAILED', 'reason_code': 'backend_not_started', 'attempt_count': 1,
            'gate_status': 'manual_confirmed' if enabled else 'allowed', 'dispatch_status': 'not_started',
            'effect_status': 'not_verified', 'destination_status': 'not_evaluated',
            'evidence': {'source_sha256': claim.server_binding.source_sha256,
                'approved_preview_sha256': grounded.preview.content_sha256, 'fresh_preview_sha256': 'b' * 64,
                'consume_content_sha256': 'c' * 64, 'confirmation_id': identity, 'capture_id': 'capture.test',
                'candidate_ref': 'candidate:test', 'gate_decision_ref': 'gate:test'},
            'next_observation_id': None, 'artifact_is_authorization': False,
        })
        class WrongModeCallsite:
            def get_local_grounded_confirmation(self, **kwargs):
                return claim
            def consume_grounded_confirmation(self, **kwargs):
                return receipt
        attachment = controller.attach(WrongModeCallsite(), confirmation_id=identity)
        assert attachment.automatic_safety_interception is enabled
        monkeypatch.setattr(runtime, '_automatic_safety_interception', not enabled)
        controller.set_accepting(True)
        with pytest.raises(NativeSingleStepError) as error:
            controller.execute_server(confirmation_id=identity)
        assert error.value.code == 'runtime_result_invalid'
        assert error.value.result_unknown is True
        assert controller.attachment_snapshot() is attachment
        assert controller._last_envelope is None and controller._execution_started is True
        assert backend.commands == []
    finally:
        controller.set_accepting(False)
        _close(host, runtime)


def test_disabled_interception_does_not_approve_a_pending_action(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    monkeypatch.setattr(runtime, '_automatic_safety_interception', False)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        result = runtime.consume_grounded_confirmation(confirmation_id=claim.grounded_confirmation.confirmation_id)
        assert result.reason_code == 'grounded_confirmation_not_approved'
        assert backend.commands == []
    finally:
        _close(host, runtime)
