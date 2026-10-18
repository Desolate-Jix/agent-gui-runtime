from __future__ import annotations

from types import SimpleNamespace
from threading import Event, Thread

import pytest

from app.desktop_review.host import DesktopHostError, DesktopReviewHost


CONFIRMATION = "grounded-confirmation." + "e" * 64


class _Callsite:
    def __init__(self):
        self.fail = False; self.cancel_count = 0
        self.block = False; self.entered = Event(); self.release = Event()
        self.cancel_block = False; self.cancel_entered = Event(); self.cancel_release = Event()
    def get_local_grounded_confirmation(self, **_kwargs):
        observation = SimpleNamespace(session_id="s", observation_id="o", workflow=SimpleNamespace(workflow_id="w", asset_id="a"))
        grounded = SimpleNamespace(confirmation_id=CONFIRMATION, preview=SimpleNamespace(to_dict=lambda: {"target_process_id":7}))
        return SimpleNamespace(observation=observation, intent=SimpleNamespace(intent_id="i"),
                               server_binding=SimpleNamespace(target_window_handle=41), grounded_confirmation=grounded)
    def cancel_grounded_review(self, **_kwargs):
        self.cancel_count += 1
        self.cancel_entered.set()
        if self.cancel_block:
            assert self.cancel_release.wait(5)
        if self.fail: raise RuntimeError("injected")
        return SimpleNamespace(phase="grounded_confirmation_closed",
            observation=SimpleNamespace(session_id="s"),
            grounded_confirmation=SimpleNamespace(confirmation_id=CONFIRMATION, closed_reason_code="grounded_confirmation_cancelled"))
    def consume_grounded_confirmation(self, **_kwargs):
        self.entered.set()
        if self.block:
            assert self.release.wait(5)
        return SimpleNamespace(status="REJECTED", reason_code="grounded_confirmation_stale", confirmation_id=CONFIRMATION)


def test_release_revokes_client_but_keeps_agent_inbox_ready(tmp_path):
    host = DesktopReviewHost(tmp_path/"inbox.db", tmp_path/"review", "reviewer-token-123")
    try:
        ready = host.start()
        callsite = _Callsite()
        host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        old_client = host.single_step
        released = host.release_grounded_runtime(confirmation_id=CONFIRMATION)
        assert released["contract_version"] == "native_review_host_v1"
        assert released["phase"] == "ready"
        assert released["base_url"] == ready["base_url"]
        assert host.single_step is None
        with pytest.raises(Exception) as caught:
            old_client.execute(confirmation_id=CONFIRMATION)
        assert caught.value.code == "single_step_client_revoked"
        assert host.connections.list_connections() == []
    finally:
        host.close()


def test_release_failure_retains_exact_owner_for_retry(tmp_path):
    host = DesktopReviewHost(tmp_path/"inbox.db", tmp_path/"review", "reviewer-token-123")
    try:
        host.start()
        callsite = _Callsite()
        host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        with pytest.raises(DesktopHostError) as wrong:
            host.release_grounded_runtime(
                confirmation_id="grounded-confirmation." + "f" * 64
            )
        assert wrong.value.code == "confirmation_not_attached"
        assert host.single_step is not None
        callsite.fail = True
        with pytest.raises(DesktopHostError) as caught:
            host.release_grounded_runtime(confirmation_id=CONFIRMATION)
        assert caught.value.code == "runtime_cleanup_pending"
        assert host.single_step is not None
        assert host.status()["contract_version"] == "native_review_host_v2"
        callsite.fail = False
        host.release_grounded_runtime(confirmation_id=CONFIRMATION)
        assert callsite.cancel_count == 2
    finally:
        host.close()


def test_release_timeout_retains_owner_and_stops_new_admission(tmp_path):
    host = DesktopReviewHost(tmp_path/"inbox.db", tmp_path/"review", "reviewer-token-123")
    callsite = _Callsite(); callsite.block = True
    failures = []
    thread = None
    try:
        host.start()
        host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        client = host.single_step
        thread = Thread(target=lambda: _capture(failures, lambda: client.execute(confirmation_id=CONFIRMATION)))
        thread.start()
        assert callsite.entered.wait(3)
        with pytest.raises(DesktopHostError) as caught:
            host.release_grounded_runtime(confirmation_id=CONFIRMATION, timeout=0.05)
        assert caught.value.code == "shutdown_timeout"
        assert host.single_step is client
        with pytest.raises(Exception) as revoked:
            client.execute(confirmation_id=CONFIRMATION)
        assert revoked.value.code == "single_step_client_revoked"
        callsite.release.set(); thread.join(5)
        assert not thread.is_alive() and failures == []
        host.release_grounded_runtime(confirmation_id=CONFIRMATION)
    finally:
        callsite.release.set()
        if thread is not None: thread.join(5)
        host.close()


def test_blocked_cleanup_timeout_is_bounded_and_exact_retry_adopts_same_work(tmp_path):
    host = DesktopReviewHost(tmp_path/"inbox.db", tmp_path/"review", "reviewer-token-123")
    callsite = _Callsite(); callsite.cancel_block = True
    outcome = []
    thread = None
    try:
        host.start(); host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        thread = Thread(target=lambda: _capture(outcome, lambda: host.release_grounded_runtime(
            confirmation_id=CONFIRMATION, timeout=0.05)))
        thread.start(); assert callsite.cancel_entered.wait(2)
        with pytest.raises(DesktopHostError) as concurrent_close:
            host.close(timeout=0.05)
        assert concurrent_close.value.code == "lifecycle_busy"
        thread.join(0.3)
        assert not thread.is_alive(), "release ignored its cleanup timeout"
        assert len(outcome) == 1 and isinstance(outcome[0], DesktopHostError)
        assert outcome[0].code == "shutdown_timeout"
        assert callsite.cancel_count == 1 and host.single_step is not None
        with pytest.raises(DesktopHostError) as attach:
            host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        assert attach.value.code in {"lifecycle_busy", "runtime_already_attached"}
        with pytest.raises(DesktopHostError) as foreign:
            host.release_grounded_runtime(
                confirmation_id="grounded-confirmation." + "f" * 64,
                timeout=0.05,
            )
        assert foreign.value.code == "confirmation_not_attached"
        with pytest.raises(DesktopHostError) as retry_timeout:
            host.release_grounded_runtime(confirmation_id=CONFIRMATION, timeout=0.05)
        assert retry_timeout.value.code == "shutdown_timeout"
        assert callsite.cancel_count == 1
        callsite.cancel_release.set()
        released = host.release_grounded_runtime(confirmation_id=CONFIRMATION)
        assert released["contract_version"] == "native_review_host_v1"
        assert callsite.cancel_count == 1
    finally:
        callsite.cancel_release.set()
        if thread is not None: thread.join(5)
        host.close()


def test_close_waits_for_retained_cleanup_without_duplicate_cancel(tmp_path):
    host = DesktopReviewHost(tmp_path/"inbox.db", tmp_path/"review", "reviewer-token-123")
    callsite = _Callsite(); callsite.cancel_block = True
    try:
        host.start(); host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        with pytest.raises(DesktopHostError) as release_timeout:
            host.release_grounded_runtime(confirmation_id=CONFIRMATION, timeout=0.05)
        assert release_timeout.value.code == "shutdown_timeout"
        with pytest.raises(DesktopHostError) as close_timeout:
            host.close(timeout=0.05)
        assert close_timeout.value.code == "shutdown_timeout"
        assert host.status()["phase"] == "stopping"
        assert callsite.cancel_count == 1
        callsite.cancel_release.set()
        host.close(timeout=5)
        assert host.status()["phase"] == "stopped"
        assert callsite.cancel_count == 1
    finally:
        callsite.cancel_release.set()
        if host.status()["phase"] != "stopped": host.close(timeout=5)


def _capture(failures, operation):
    try: operation()
    except BaseException as error: failures.append(error)
