import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from urllib.parse import urlsplit

import httpx
import pytest

from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.desktop_review.host import DesktopHostError, DesktopReviewHost
from app.desktop_review.single_step import NativeSingleStepError, OwnedSingleStepClient
from tests.test_agent_link_shared_host import _post
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_grounded_single_dispatch_integration import approved


@pytest.fixture
def execution_host(tmp_path, approved):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "reviews", "integration-reviewer-secret", port=0,
    )
    try:
        host.start()
        yield host
    finally:
        host.close()


def test_owned_http_executes_actual_approved_runtime_once(execution_host, approved):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    first_client = execution_host.single_step
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    assert execution_host.single_step is first_client
    status = execution_host.status()
    assert status["contract_version"] == "native_review_host_v2"
    assert status["staging_only"] is False
    assert status["agent_link_staging_only"] is True
    assert status["reviewed_single_step_enabled"] is True
    assert status["automatic_execution_enabled"] is False
    response = execution_host.single_step.execute(confirmation_id=approved.confirmation_id)
    assert set(response) == {
        "contract_version", "confirmation_id", "kind", "payload", "artifact_is_authorization",
    }
    assert response["contract_version"] == "native_single_step_response_v1"
    assert response["confirmation_id"] == approved.confirmation_id
    assert response["kind"] == "receipt"
    assert response["artifact_is_authorization"] is False
    receipt = RuntimeResultReceiptV1.model_validate(response["payload"])
    assert receipt.outcome == "SAFE_STOP"
    assert receipt.reason_code == "stop_boundary"
    assert receipt.attempt_count == 1
    assert any(ref.startswith("grounded-consume:") for ref in receipt.evidence.trace_refs)
    assert sum(backend.attempt_count for backend in approved.live.backends) == 1
    assert sum(source.projected_calls for source in approved.live.sources) == 3
    claim = approved.live.claims.get_for_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert claim.phase == "terminal"
    repeated = execution_host.single_step.execute(confirmation_id=approved.confirmation_id)
    assert repeated == response
    assert sum(backend.attempt_count for backend in approved.live.backends) == 1
    assert sum(source.projected_calls for source in approved.live.sources) == 3


def test_learning_reviewer_cannot_execute_actual_runtime(execution_host, approved):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    url = execution_host.status()["base_url"]
    captures = sum(source.projected_calls for source in approved.live.sources)
    status, response = _post(
        url + "/action/execute_recognition_plan", "integration-reviewer-secret",
        {"confirmation_id": approved.confirmation_id},
    )
    assert status == 401
    assert set(response) == {"error"}
    assert set(response["error"]) == {"code", "message", "result_unknown"}
    assert response["error"]["result_unknown"] is False
    assert _post(url + "/reviewer/list_connections", "integration-reviewer-secret", {})[0] == 404
    assert sum(source.projected_calls for source in approved.live.sources) == captures
    assert sum(backend.attempt_count for backend in approved.live.backends) == 0
    assert not list(approved.live.claims.grounded_consume_root.iterdir())


def test_agent_learning_token_cannot_execute_or_obtain_execution_credentials(execution_host, approved):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    created = execution_host.connections.create_connection("task-http-integration", "synthetic-test-agent")
    assert created["staging_only"] is True
    url = execution_host.status()["base_url"]
    status, response = _post(
        url + "/action/execute_recognition_plan", created["token"],
        {"confirmation_id": approved.confirmation_id},
    )
    assert status == 401
    assert response["error"]["result_unknown"] is False
    assert "execution_token" not in created
    assert sum(source.projected_calls for source in approved.live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in approved.live.backends)
    assert not list(approved.live.claims.grounded_consume_root.iterdir())


def test_actual_post_dispatch_receipt_read_failure_is_unknown_without_auto_retry(execution_host, approved, monkeypatch):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    original = approved.live.claims.load_terminal_receipt
    reads = []

    def fail_second_read(**kwargs):
        reads.append(kwargs)
        if len(reads) == 2:
            raise RuntimeIntentClaimStoreError("synthetic private receipt-read failure")
        return original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(approved.live.claims, "load_terminal_receipt", fail_second_read)
        with pytest.raises(NativeSingleStepError) as raised:
            execution_host.single_step.execute(confirmation_id=approved.confirmation_id)
        assert raised.value.result_unknown is True
        assert "synthetic private" not in str(raised.value)
        assert len(reads) == 2
        assert approved.live.claims.get_for_grounded_confirmation(
            confirmation_id=approved.confirmation_id,
        ).phase == "terminal"
        assert sum(backend.attempt_count for backend in approved.live.backends) == 1
        assert sum(source.projected_calls for source in approved.live.sources) == 3
    replay = execution_host.single_step.execute(confirmation_id=approved.confirmation_id)
    assert replay["kind"] == "receipt"
    assert RuntimeResultReceiptV1.model_validate(replay["payload"]).attempt_count == 1
    assert sum(backend.attempt_count for backend in approved.live.backends) == 1
    assert sum(source.projected_calls for source in approved.live.sources) == 3


def test_foreign_confirmation_never_reaches_actual_store(execution_host, approved, monkeypatch):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    original = approved.live.claims.get_for_grounded_confirmation
    lookups = []

    def lookup(**kwargs):
        lookups.append(kwargs)
        return original(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(approved.live.claims, "get_for_grounded_confirmation", lookup)
        with pytest.raises(NativeSingleStepError) as raised:
            execution_host.single_step.execute(confirmation_id="grounded-confirmation." + "0" * 64)
        assert raised.value.result_unknown is False
        assert lookups == []
    assert sum(source.projected_calls for source in approved.live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in approved.live.backends)


def test_actual_fresh_visual_drift_returns_bound_decision_without_dispatch(execution_host, approved):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    approved.live.sources[0].post_current_sequence[0]["screenshot_sha256"] = "a" * 64
    response = execution_host.single_step.execute(confirmation_id=approved.confirmation_id)
    assert response == {
        "contract_version": "native_single_step_response_v1",
        "confirmation_id": approved.confirmation_id,
        "kind": "decision",
        "payload": {
            "status": "REJECTED", "reason_code": "grounded_confirmation_stale",
            "confirmation_id": approved.confirmation_id,
        },
        "artifact_is_authorization": False,
    }
    assert all(backend.attempt_count == 0 for backend in approved.live.backends)
    claim = approved.live.claims.get_for_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert claim.phase == "grounded_confirmation_closed"
    assert not list(approved.live.claims.grounded_consume_root.iterdir())


def test_actual_cancel_recovery_decision_keeps_host_owner_until_exact_retry(execution_host, approved, monkeypatch):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)

    def unavailable(**_kwargs):
        raise RuntimeIntentClaimStoreError("synthetic close persistence unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(approved.live.claims, "close_grounded_confirmation", unavailable)
        with pytest.raises(DesktopHostError) as raised:
            execution_host.close()
        assert raised.value.code == "runtime_cleanup_pending"
        assert execution_host.status()["phase"] == "stopping"
        assert execution_host._resources_closed is False
        assert execution_host._single_step_controller.attached is True
        assert approved.live.service._grounded_cleanup is not None
        assert approved.observation.session_id in approved.live.controllers[0]._sessions
    execution_host.close()
    assert execution_host.status()["phase"] == "stopped"
    assert approved.observation.session_id not in approved.live.controllers[0]._sessions
    assert all(backend.attempt_count == 0 for backend in approved.live.backends)


@pytest.mark.parametrize("malformation", ["kind_list", "status_object", "deep_json"])
def test_malformed_host_response_always_surfaces_unknown_without_second_post(malformation, monkeypatch):
    identity = "grounded-confirmation." + "a" * 64
    payload = {
        "contract_version": "native_single_step_response_v1", "confirmation_id": identity,
        "kind": "decision", "payload": {
            "status": "REJECTED", "reason_code": "grounded_confirmation_stale", "confirmation_id": identity,
        }, "artifact_is_authorization": False,
    }
    if malformation == "kind_list":
        payload["kind"] = []
    elif malformation == "status_object":
        payload["payload"]["status"] = {}
    content = b"[" * 2000 + b"]" * 2000 if malformation == "deep_json" else json.dumps(payload).encode("utf-8")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=content)

    original = httpx.Client

    def client(**kwargs):
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    owned = OwnedSingleStepClient(
        base_url="http://127.0.0.1:49123", token="synthetic-execution-credential", confirmation_id=identity,
    )
    with pytest.raises(NativeSingleStepError) as raised:
        owned.execute(confirmation_id=identity)
    assert raised.value.result_unknown is True
    assert len(requests) == 1


def test_pending_rejection_close_durably_cancels_actual_owner(tmp_path, live):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    identity = pending.grounded_confirmation.confirmation_id
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "reviews", "pending-reviewer-secret")
    try:
        host.start()
        host.attach_grounded_runtime(live.service, confirmation_id=identity)
        response = host.single_step.execute(confirmation_id=identity)
        assert response["payload"]["reason_code"] == "grounded_confirmation_not_approved"
        host.close()
        assert live.claims.get_for_grounded_confirmation(confirmation_id=identity).phase == "grounded_confirmation_closed"
        assert observation.session_id not in live.controllers[0]._sessions
        assert all(backend.attempt_count == 0 for backend in live.backends)
        assert host.status()["phase"] == "stopped"
    finally:
        host.close()
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_retained_client_is_revoked_before_closed_port_can_be_reused(execution_host, approved):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    retained = execution_host.single_step
    port = urlsplit(execution_host.status()["base_url"]).port
    execution_host.close()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            self.rfile.read(int(self.headers["content-length"]))
            requests.append(self.path)
            body = json.dumps({
                "contract_version": "native_single_step_response_v1", "confirmation_id": approved.confirmation_id,
                "kind": "decision", "payload": {
                    "status": "REJECTED", "reason_code": "grounded_confirmation_stale",
                    "confirmation_id": approved.confirmation_id,
                }, "artifact_is_authorization": False,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with pytest.raises(NativeSingleStepError) as raised:
            retained.execute(confirmation_id=approved.confirmation_id)
        assert raised.value.result_unknown is False
        assert requests == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive()


def test_pre_post_claim_drains_actual_runtime_before_listener_release(execution_host, approved, monkeypatch):
    execution_host.attach_grounded_runtime(approved.live.service, confirmation_id=approved.confirmation_id)
    retained = execution_host.single_step
    entered, release = threading.Event(), threading.Event()
    responses, failures = [], []
    post = httpx.Client.post

    def paused_post(self, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return post(self, *args, **kwargs)

    def execute():
        try:
            responses.append(retained.execute(confirmation_id=approved.confirmation_id))
        except BaseException as error:
            failures.append(error)

    with monkeypatch.context() as patch:
        patch.setattr(httpx.Client, "post", paused_post)
        thread = threading.Thread(target=execute)
        thread.start()
        try:
            assert entered.wait(3)
            with pytest.raises(DesktopHostError) as closing:
                execution_host.close(timeout=0.05)
            assert closing.value.code == "shutdown_timeout"
            assert execution_host.status()["phase"] == "stopping"
            assert execution_host._http.phase == "ready"
            with pytest.raises(NativeSingleStepError) as revoked:
                retained.execute(confirmation_id=approved.confirmation_id)
            assert revoked.value.result_unknown is False
            release.set()
            thread.join(10)
            assert not thread.is_alive() and failures == []
            assert len(responses) == 1 and responses[0]["kind"] == "receipt"
            assert sum(backend.attempt_count for backend in approved.live.backends) == 1
        finally:
            release.set()
            thread.join(10)
            assert not thread.is_alive()
    execution_host.close()
    assert execution_host.status()["phase"] == "stopped"
