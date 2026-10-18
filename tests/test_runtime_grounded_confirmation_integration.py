import json
import subprocess
import sys
import time

import pytest

from app.agent.runtime_contracts import validate_agent_intent_v1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from tests.test_agent_runtime_api_v1 import _client
from tests.test_agent_runtime_grounded_preview import live, _request


def _claim_from_actual_preflight(live):
    observation = live.service.start_session()
    request = _request(observation)
    preview = live.service.prepare_grounded_review(request)
    intent = validate_agent_intent_v1({
        "contract_version": "agent_intent_v1",
        **request.model_dump(mode="json"),
        "workflow": observation.workflow.model_dump(mode="json"),
    }, observation=observation)
    binding = live.controllers[0]._binding
    # 本阶段只验证存储接缝，先释放预检会话，不冒充已接通正式发布入口。
    live.service.cancel_prepared_session(session_id=observation.session_id)
    live.claims.claim(observation=observation, intent=intent, server_binding={
        "workflow_id": binding.workflow_id,
        "asset_id": binding.asset_id,
        "application_identity_key": binding.application_identity_key,
        "target_window_handle": binding.target_window_handle,
    })
    claim = live.claims.mark_grounded_confirmation_pending(
        session_id=observation.session_id,
        observation_id=observation.observation_id,
        preview=preview,
    )
    return request, preview, claim


@pytest.mark.parametrize("decision", [None, "approved"])
def test_grounded_unresolved_store_state_blocks_legacy_session_start(live, decision):
    request, _, claim = _claim_from_actual_preflight(live)
    if decision:
        claim = live.claims.record_grounded_confirmation_decision(
            confirmation_id=claim.grounded_confirmation.confirmation_id, decision=decision,
        )
    factory_count = len(live.controllers)
    with _client(live.service) as client:
        response = client.post("/runtime/agent/session/start", json={})
    assert response.status_code == 412
    assert len(live.controllers) == factory_count
    assert live.claims.get_for_observation(
        session_id=request.session_id, observation_id=request.observation_id,
    ).phase == claim.phase
    assert all(backend.attempt_count == 0 for backend in live.backends)


@pytest.mark.parametrize("state", ["pending", "approved", "denied", "closed"])
def test_legacy_http_cannot_consume_or_approve_grounded_confirmation(live, state):
    request, _, claim = _claim_from_actual_preflight(live)
    confirmation_id = claim.grounded_confirmation.confirmation_id
    if state in {"approved", "denied"}:
        claim = live.claims.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision=state,
        )
    elif state == "closed":
        claim = live.claims.close_grounded_confirmation(
            confirmation_id=confirmation_id, reason_code="grounded_confirmation_cancelled",
        )
    capture_count = sum(source.projected_calls for source in live.sources)
    with _client(live.service) as client:
        approval = client.post("/runtime/agent/confirmation/decide", json={
            "confirmation_id": confirmation_id, "decision": "approved",
        })
        intent = client.post("/runtime/agent/intent/submit", json=request.model_dump(mode="json"))
    assert approval.status_code == 412
    assert intent.status_code == 200
    assert intent.json()["data"]["status"] == "RECOVERY_REQUIRED"
    assert sum(source.projected_calls for source in live.sources) == capture_count
    assert all(backend.attempt_count == 0 for backend in live.backends)
    assert live.claims.get_for_observation(
        session_id=request.session_id, observation_id=request.observation_id,
    ).phase == claim.phase


def test_reopened_store_keeps_actual_preview_but_cannot_restore_old_approval(live, tmp_path):
    _, preview, claim = _claim_from_actual_preflight(live)
    confirmation_id = claim.grounded_confirmation.confirmation_id
    approved = live.claims.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id, decision="approved",
    )
    reopened = RuntimeIntentClaimStore(
        project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    read = reopened.get_for_grounded_confirmation(confirmation_id=confirmation_id)
    assert read.phase == "grounded_confirmation_approved"
    assert read.grounded_confirmation.owner_is_current is False
    assert read.grounded_confirmation.preview == preview
    closed = reopened.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id, decision="approved",
    )
    assert closed.phase == "grounded_confirmation_closed"
    assert closed.grounded_confirmation.closed_reason_code == "grounded_confirmation_restarted"
    assert closed.grounded_confirmation.decision_content_sha256 == approved.grounded_confirmation.decision_content_sha256
    assert all(backend.attempt_count == 0 for backend in live.backends)


@pytest.mark.parametrize("state", ["denied", "closed"])
def test_grounded_resolution_permits_new_preparation_without_changing_old_preview(live, state):
    _, preview, claim = _claim_from_actual_preflight(live)
    confirmation_id = claim.grounded_confirmation.confirmation_id
    if state == "denied":
        live.claims.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="denied")
    else:
        live.claims.close_grounded_confirmation(confirmation_id=confirmation_id, reason_code="grounded_confirmation_cancelled")
    new_observation = live.service.start_session()
    assert new_observation.session_id != claim.observation.session_id
    assert live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).grounded_confirmation.preview == preview
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_grounded_parent_approval_and_subprocess_denial_commit_one_decision(live, tmp_path):
    _, preview, claim = _claim_from_actual_preflight(live)
    confirmation_id = claim.grounded_confirmation.confirmation_id
    ready = tmp_path / "grounded-child-ready"
    proceed = tmp_path / "grounded-child-proceed"
    child_code = """
import json
from pathlib import Path
import sys
import time
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore

root, confirmation_id, ready, proceed = sys.argv[1:]
store = RuntimeIntentClaimStore(project_root=root, receipt_store=RuntimeReceiptStore(project_root=root))
Path(ready).touch()
deadline = time.monotonic() + 10
while not Path(proceed).exists():
    if time.monotonic() >= deadline:
        raise RuntimeError("parent did not release grounded race")
    time.sleep(0.01)
try:
    result = store.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="denied")
    outcome = result.grounded_confirmation.decision
except RuntimeIntentClaimStoreError as exc:
    if "conflict" not in str(exc):
        raise
    outcome = "conflict"
print(json.dumps({"outcome": outcome}, ensure_ascii=False))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", child_code, str(tmp_path), confirmation_id, str(ready), str(proceed)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=2)
                pytest.fail(f"Grounded child exited before readiness: {stdout} {stderr}")
            assert time.monotonic() < deadline, "Grounded child readiness timed out"
            time.sleep(0.01)
        proceed.touch()
        try:
            approved = live.claims.record_grounded_confirmation_decision(
                confirmation_id=confirmation_id, decision="approved",
            )
            parent_outcome = approved.grounded_confirmation.decision
        except RuntimeIntentClaimStoreError as exc:
            assert "conflict" in str(exc)
            parent_outcome = "conflict"
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
    finally:
        # 只回收本测试创建的有界子进程，不触及其他进程。
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    child_outcome = json.loads(stdout)["outcome"]
    outcomes = [parent_outcome, child_outcome]
    assert outcomes.count("conflict") == 1
    winner = next(value for value in outcomes if value != "conflict")
    assert winner in {"approved", "denied"}
    current = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
    assert current.grounded_confirmation.decision == winner
    assert current.grounded_confirmation.preview == preview
    assert len(list(live.claims.grounded_decisions_root.iterdir())) == 1
    assert not list(live.claims.grounded_closed_root.iterdir())
    assert not list(live.claims.dispatch_started_root.iterdir())
    assert not list(live.claims.terminal_root.iterdir())
    assert all(backend.attempt_count == 0 for backend in live.backends)
