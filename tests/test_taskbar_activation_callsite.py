import json
import time
from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step import NativeSingleStepError
from app.desktop_review.taskbar_activation import TaskbarActivationCallsite
from test_taskbar_activation_guard import evidence


class Reader:
    def __init__(self):
        self.counter = 0
        self.drift = False

    def __call__(self):
        self.counter += 1
        result = evidence(captured=time.monotonic())
        if self.drift:
            result['source_foreground']['handle'] += 1
            from app.desktop_review.taskbar_activation_source import _hash
            result['source_sha256'] = _hash({k: v for k, v in result.items() if k != 'source_sha256'})
        return result


def make_owner(tmp_path, backend=None):
    reader = Reader()
    backend = backend or DeterministicFakeBackend()
    owner = TaskbarActivationCallsite(source=reader, backend=backend, journal_dir=tmp_path / 'activation')
    return owner, reader, backend


def test_pending_cancel_and_bad_approval_cannot_dispatch(tmp_path):
    owner, _, backend = make_owner(tmp_path)
    preview = owner.prepare()
    with pytest.raises(ValueError, match='preview'):
        owner.record_decision(preview_sha256='0' * 64, approved=True)
    result = owner.consume_grounded_confirmation(confirmation_id=preview['confirmation_id'])
    assert result.reason_code == 'grounded_confirmation_not_approved'
    assert backend.dispatch_count == 0
    cancelled = owner.cancel_grounded_review(session_id=preview['session_id'])
    assert cancelled.phase == 'cancelled'


def test_actual_owned_http_dispatch_and_replay_use_one_backend_authority(tmp_path):
    owner, _, backend = make_owner(tmp_path)
    preview = owner.prepare()
    host = DesktopReviewHost(tmp_path / 'inbox.json', tmp_path / 'reviews', 'test-reviewer-secret')
    try:
        host.start()
        host.attach_grounded_runtime(owner, confirmation_id=preview['confirmation_id'])
        owner.record_decision(preview_sha256=preview['preview_sha256'], approved=True)
        result = host.single_step.execute(confirmation_id=preview['confirmation_id'])
        assert result['kind'] == 'receipt'
        assert result['payload']['source_kind'] == 'taskbar_activation'
        assert result['payload']['status'] == 'dispatched'
        assert host.single_step.execute(confirmation_id=preview['confirmation_id']) == result
        assert backend.dispatch_count == 1
        assert backend.commands[0].semantic_action == 'taskbar_activate'
        host.release_grounded_runtime(confirmation_id=preview['confirmation_id'])
    finally:
        host.close()
    state = json.loads((tmp_path / 'activation' / 'state.json').read_text(encoding='utf-8'))
    assert state['phase'] == 'terminal'
    assert state['receipt'] == result['payload']
    with pytest.raises(FileExistsError):
        TaskbarActivationCallsite(source=Reader(), backend=backend, journal_dir=tmp_path / 'activation')


def test_stale_geometry_never_reaches_backend(tmp_path):
    owner, reader, backend = make_owner(tmp_path)
    preview = owner.prepare()
    owner.record_decision(preview_sha256=preview['preview_sha256'], approved=True)
    reader.drift = True
    receipt = owner.consume_grounded_confirmation(confirmation_id=preview['confirmation_id'])
    assert receipt.status == 'not_started'
    assert backend.attempt_count == 0


def test_native_close_cancels_pending_taskbar_without_input(tmp_path):
    owner, _, backend = make_owner(tmp_path)
    preview = owner.prepare()
    host = DesktopReviewHost(tmp_path / 'inbox.json', tmp_path / 'reviews', 'test-reviewer-secret')
    host.start()
    host.attach_grounded_runtime(owner, confirmation_id=preview['confirmation_id'])
    host.close()
    assert owner.get_local_grounded_confirmation(confirmation_id=preview['confirmation_id']).phase == 'cancelled'
    assert backend.attempt_count == 0


def test_invalid_backend_receipt_is_indeterminate_and_never_retried(tmp_path):
    class BadBackend:
        calls = 0
        def dispatch(self, command, *, authority):
            self.calls += 1
            return SimpleNamespace(status='dispatched', reason_code='backend_failed', receipt_ref=None)
    backend = BadBackend()
    owner, _, _ = make_owner(tmp_path, backend)
    preview = owner.prepare()
    owner.record_decision(preview_sha256=preview['preview_sha256'], approved=True)
    receipt = owner.consume_grounded_confirmation(confirmation_id=preview['confirmation_id'])
    assert receipt.status == 'indeterminate'
    assert owner.consume_grounded_confirmation(confirmation_id=preview['confirmation_id']) == receipt
    assert backend.calls == 1


@pytest.mark.parametrize('key', ['destination_window_handle', 'destination_process_id'])
def test_attached_taskbar_rejects_wrong_destination_receipt(tmp_path, key):
    from app.desktop_review.single_step import NativeSingleStepController, _validate_attachment_result
    owner, _, _ = make_owner(tmp_path)
    preview = owner.prepare()
    controller = NativeSingleStepController()
    attachment = controller.attach(owner, confirmation_id=preview['confirmation_id'])
    owner.record_decision(preview_sha256=preview['preview_sha256'], approved=True)
    receipt = owner.consume_grounded_confirmation(confirmation_id=preview['confirmation_id'])
    payload = receipt.model_dump(mode='json')
    payload[key] += 99
    with pytest.raises(NativeSingleStepError):
        _validate_attachment_result({'kind': 'receipt', 'payload': payload}, attachment)
