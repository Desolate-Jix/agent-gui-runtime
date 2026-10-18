from types import SimpleNamespace
import json
import threading

import httpx
import pytest

from app.desktop_review.host import DesktopHostError, DesktopReviewHost
from app.desktop_review.single_step import (
    NativeSingleStepController,
    NativeSingleStepError,
)


REVIEWER = "native-host-reviewer-secret"
CONFIRMATION = "grounded-confirmation." + "c" * 64


def _claim():
    workflow = SimpleNamespace(workflow_id="workflow-a", asset_id="asset-a")
    observation = SimpleNamespace(
        session_id="session-a", observation_id="observation-a", workflow=workflow
    )
    intent = SimpleNamespace(intent_id="intent-a")
    binding = SimpleNamespace(target_window_handle=4401)
    preview = SimpleNamespace(to_dict=lambda: {"target_process_id": 5501})
    grounded = SimpleNamespace(confirmation_id=CONFIRMATION, preview=preview)
    return SimpleNamespace(
        phase="grounded_confirmation_pending",
        observation=observation,
        intent=intent,
        server_binding=binding,
        grounded_confirmation=grounded,
    )


class _Callsite:
    def __init__(self):
        self.claim = _claim()
        self.consume_calls = 0
        self.cancel_calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.cancel_failure = False
        self.cancel_recovery = False

    def get_local_grounded_confirmation(self, *, confirmation_id):
        assert confirmation_id == CONFIRMATION
        return self.claim

    def consume_grounded_confirmation(self, *, confirmation_id):
        assert confirmation_id == CONFIRMATION
        self.consume_calls += 1
        self.entered.set()
        if self.block:
            assert self.release.wait(5)
        return SimpleNamespace(
            status="REJECTED",
            reason_code="grounded_confirmation_stale",
            confirmation_id=confirmation_id,
        )

    def cancel_grounded_review(self, *, session_id):
        assert session_id == "session-a"
        self.cancel_calls += 1
        if self.cancel_failure:
            self.cancel_failure = False
            raise RuntimeError("synthetic cleanup failure")
        if self.cancel_recovery:
            self.cancel_recovery = False
            return SimpleNamespace(
                status="RECOVERY_REQUIRED",
                reason_code="grounded_confirmation_cleanup_required",
                confirmation_id=CONFIRMATION,
            )
        grounded = SimpleNamespace(
            confirmation_id=CONFIRMATION,
            closed_reason_code="grounded_confirmation_cancelled",
        )
        return SimpleNamespace(
            phase="grounded_confirmation_closed",
            observation=self.claim.observation,
            grounded_confirmation=grounded,
        )


def test_host_attach_sets_strict_v2_and_close_cancels_unconsumed_owner(tmp_path):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    try:
        host.start()
        attached = host.attach_grounded_runtime(
            callsite, confirmation_id=CONFIRMATION
        )
        assert attached == host.status()
        assert attached == {
            "contract_version": "native_review_host_v2",
            "host_id": attached["host_id"],
            "phase": "ready",
            "base_url": attached["base_url"],
            "staging_only": False,
            "agent_link_staging_only": True,
            "reviewed_single_step_enabled": True,
            "automatic_execution_enabled": False,
        }
        assert REVIEWER not in repr(host.single_step)
    finally:
        host.close()
    assert callsite.cancel_calls == 1
    assert callsite.consume_calls == 0


def test_close_does_not_hold_admission_lock_while_inflight_drains(tmp_path):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    callsite.block = True
    host.start()
    host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
    failures = []

    def execute():
        try:
            host.single_step.execute(confirmation_id=CONFIRMATION)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=execute, name="single-step-owned-test")
    thread.start()
    try:
        assert callsite.entered.wait(3)
        with pytest.raises(DesktopHostError) as timeout:
            host.close(timeout=0.05)
        assert timeout.value.code == "shutdown_timeout"
        assert host.status()["phase"] == "stopping"
        callsite.release.set()
        thread.join(5)
        assert not thread.is_alive() and failures == []
        host.close(timeout=5)
        assert host.status()["phase"] == "stopped"
    finally:
        callsite.release.set()
        thread.join(5)
        if host.status()["phase"] != "stopped":
            host.close(timeout=5)


def test_cleanup_failure_keeps_attachment_for_close_retry(tmp_path):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    callsite.cancel_failure = True
    host.start()
    host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
    with pytest.raises(DesktopHostError) as failure:
        host.close(timeout=5)
    assert failure.value.code == "runtime_cleanup_pending"
    assert host.status()["phase"] == "stopping"
    host.close(timeout=5)
    assert host.status()["phase"] == "stopped"
    assert callsite.cancel_calls == 2


def test_cleanup_recovery_decision_keeps_attachment_for_close_retry(tmp_path):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    callsite.cancel_recovery = True
    host.start()
    host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
    with pytest.raises(DesktopHostError) as failure:
        host.close(timeout=5)
    assert failure.value.code == "runtime_cleanup_pending"
    assert host.status()["phase"] == "stopping"
    host.close(timeout=5)
    assert host.status()["phase"] == "stopped"
    assert callsite.cancel_calls == 2


def test_controller_rejects_second_concurrent_admission_before_runtime(tmp_path):
    callsite = _Callsite()
    callsite.block = True
    controller = NativeSingleStepController()
    controller.attach(callsite, confirmation_id=CONFIRMATION)
    controller.set_accepting(True)
    failures = []

    def execute():
        try:
            controller.execute_server(confirmation_id=CONFIRMATION)
        except BaseException as error:
            failures.append(error)

    first = threading.Thread(target=execute, name="single-step-admission-first")
    second = threading.Thread(target=execute, name="single-step-admission-second")
    first.start()
    try:
        assert callsite.entered.wait(3)
        second.start()
        second.join(0.25)
        assert not second.is_alive()
        assert len(failures) == 1
        assert isinstance(failures[0], NativeSingleStepError)
        assert failures[0].result_unknown is False
        assert callsite.consume_calls == 1
    finally:
        callsite.release.set()
        first.join(5)
        second.join(5)
    assert not first.is_alive() and not second.is_alive()


def test_failed_http_reconcile_revokes_retained_client_before_network(tmp_path, monkeypatch):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    try:
        host.start()
        host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
        retained = host.single_step
        with host._http._guard:
            host._http._phase = "failed"
            host._http._base_url = None
        assert host.status()["phase"] == "failed"

        def network_forbidden(**_kwargs):
            raise AssertionError("revoked client attempted network")

        monkeypatch.setattr(httpx, "Client", network_forbidden)
        with pytest.raises(NativeSingleStepError) as raised:
            retained.execute(confirmation_id=CONFIRMATION)
        assert raised.value.result_unknown is False
    finally:
        host.close(timeout=5)


def test_close_waits_for_client_claim_before_stopping_listener(tmp_path, monkeypatch):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", REVIEWER
    )
    callsite = _Callsite()
    entered = threading.Event()
    release = threading.Event()
    failures = []

    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            entered.set()
            assert release.wait(5)
            body = {
                "contract_version": "native_single_step_response_v1",
                "confirmation_id": CONFIRMATION,
                "kind": "decision",
                "payload": {
                    "status": "REJECTED",
                    "reason_code": "grounded_confirmation_stale",
                    "confirmation_id": CONFIRMATION,
                },
                "artifact_is_authorization": False,
            }
            return httpx.Response(200, content=json.dumps(body).encode("utf-8"))

    host.start()
    host.attach_grounded_runtime(callsite, confirmation_id=CONFIRMATION)
    monkeypatch.setattr(httpx, "Client", _Client)

    def execute():
        try:
            host.single_step.execute(confirmation_id=CONFIRMATION)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=execute, name="single-step-client-claim-test")
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(DesktopHostError) as timeout:
            host.close(timeout=0.05)
        assert timeout.value.code == "shutdown_timeout"
        assert host.status()["phase"] == "stopping"
        assert host._http.phase == "ready"
        release.set()
        thread.join(5)
        assert not thread.is_alive() and failures == []
        host.close(timeout=5)
        assert host.status()["phase"] == "stopped"
    finally:
        release.set()
        thread.join(5)
        if host.status()["phase"] != "stopped":
            host.close(timeout=5)
