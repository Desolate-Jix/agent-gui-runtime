"""真实首次学习 owner 通过原生认证单步边界；仅 OS/识别使用隔离夹具。"""

from copy import deepcopy
from dataclasses import replace

import httpx
import pytest

from app.desktop_review.single_step import (
    NativeSingleStepController, NativeSingleStepError, validate_single_step_response,
)
from tests.test_fresh_dispatch_graph import _ready, _close
from tests.test_fresh_learning_action_preview import _setup


def test_actual_pending_fresh_owner_attaches_without_a_reviewed_asset(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        identity = claim.grounded_confirmation.confirmation_id
        controller = NativeSingleStepController()
        attachment = controller.attach(runtime, confirmation_id=identity)
        assert attachment.source_kind == "fresh_learning"
        assert attachment.source_sha256 == source.reference()["source_sha256"]
        assert attachment.workflow_id is None and attachment.asset_id is None
        assert (attachment.target_window_handle, attachment.target_process_id) == (4242, 9001)
        assert attachment.session_id == session.session_id
        assert backend.commands == []
        controller.cleanup_attachment(confirmation_id=identity)
        assert controller.attached is False
        assert claims.get_for_grounded_confirmation(confirmation_id=identity).phase == "grounded_confirmation_closed"
        assert session.session_id not in runtime._sessions
    finally:
        _close(host, runtime)


def test_fresh_native_canonical_http_requires_owned_role_and_dispatches_once(tmp_path):
    host, owner, runtime, backend, claims, session, scope, identity = _ready(tmp_path)
    try:
        host.start()
        host.attach_grounded_runtime(runtime, confirmation_id=identity)
        url = host.status()["base_url"] + "/action/execute_recognition_plan"
        with httpx.Client(trust_env=False) as client:
            denied = client.post(url, headers={"authorization": "Bearer unrelated-agent-token"},
                                 json={"confirmation_id": identity})
        assert denied.status_code == 401 and backend.commands == []
        response = host.single_step.execute(confirmation_id=identity)
        assert response["kind"] == "receipt"
        receipt = response["payload"]
        assert receipt["contract_version"] == "runtime_fresh_result_receipt_v1"
        assert receipt["outcome"] == "ACTION_RECORDED"
        assert receipt["effect_status"] == "not_verified"
        assert receipt["evidence"]["confirmation_id"] == identity
        assert "workflow" not in receipt
        assert len(backend.commands) == 1
        assert host.single_step.execute(confirmation_id=identity) == response
        assert len(backend.commands) == 1
        graph_id = host.fresh_learning.sync_actions(**scope)["logical_workflow_id"]
        graph = host.facade.load_graph_revision(graph_id)["graph"]
        assert len(graph["edges"]) == 1
        host.release_grounded_runtime(confirmation_id=identity, timeout=30.0)
        assert host.single_step is None and session.session_id not in runtime._sessions
    finally:
        _close(host, runtime)


def test_native_fresh_pending_execute_is_rejected_and_cleanup_preserves_no_input(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        identity = claim.grounded_confirmation.confirmation_id
        host.start()
        host.attach_grounded_runtime(runtime, confirmation_id=identity)
        result = host.single_step.execute(confirmation_id=identity)
        assert result["kind"] == "decision"
        assert result["payload"]["reason_code"] == "grounded_confirmation_not_approved"
        assert backend.commands == []
        host.release_grounded_runtime(confirmation_id=identity, timeout=30.0)
        assert claims.get_for_grounded_confirmation(confirmation_id=identity).phase == "grounded_confirmation_closed"
        assert session.session_id not in runtime._sessions
    finally:
        _close(host, runtime)


def test_fresh_denial_after_attachment_releases_exact_native_owner(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        identity = claim.grounded_confirmation.confirmation_id
        controller = NativeSingleStepController()
        controller.attach(runtime, confirmation_id=identity)
        denied = runtime.record_grounded_confirmation_decision(confirmation_id=identity, decision="denied")
        assert denied.phase == "grounded_confirmation_denied"
        controller.cleanup_attachment(confirmation_id=identity)
        assert controller.attached is False
        assert claims.get_for_grounded_confirmation(confirmation_id=identity).phase == "grounded_confirmation_denied"
        assert backend.commands == [] and session.session_id not in runtime._sessions
        with pytest.raises(ValueError):
            runtime.cancel_grounded_review(session_id="foreign-session")
    finally:
        _close(host, runtime)


@pytest.mark.parametrize("field", ["confirmation", "effect", "workflow"])
def test_fresh_receipt_envelope_rejects_cross_confirmation_or_promoted_success(tmp_path, field):
    host, owner, runtime, backend, claims, session, scope, identity = _ready(tmp_path)
    try:
        receipt = runtime.consume_grounded_confirmation(confirmation_id=identity)
        envelope = {"contract_version": "native_single_step_response_v1", "confirmation_id": identity,
                    "kind": "receipt", "payload": receipt.model_dump(mode="json"),
                    "artifact_is_authorization": False}
        assert validate_single_step_response(envelope, confirmation_id=identity) == envelope
        bad = deepcopy(envelope)
        if field == "confirmation":
            bad["payload"]["evidence"]["confirmation_id"] = "grounded-confirmation." + "f" * 64
        elif field == "effect":
            bad["payload"]["effect_status"] = "verified"
        else:
            bad["payload"]["workflow"] = {"asset_id": "fake"}
        with pytest.raises(NativeSingleStepError):
            validate_single_step_response(bad, confirmation_id=identity)
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_fresh_native_attach_rejects_source_binding_change_and_closed_owner(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        identity = claim.grounded_confirmation.confirmation_id
        bad_claim = replace(claim, server_binding=replace(claim.server_binding, source_sha256="a" * 64))
        class ChangedOwner:
            def get_local_grounded_confirmation(self, *, confirmation_id):
                return bad_claim
        controller = NativeSingleStepController()
        with pytest.raises(NativeSingleStepError):
            controller.attach(ChangedOwner(), confirmation_id=identity)
        assert controller.attached is False
        runtime.cancel_grounded_review(session_id=session.session_id)
        with pytest.raises(NativeSingleStepError):
            controller.attach(runtime, confirmation_id=identity)
        assert backend.commands == []
    finally:
        _close(host, runtime)
