from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from tests.test_agent_link_inbox import _batch


def test_loopback_http_separates_agent_and_reviewer_identities(tmp_path):
    from app.agent_link.http_app import create_agent_link_app
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    app = create_agent_link_app(AgentLinkService(store, reviewer_token="reviewer-secret-value-123"))
    loopback = TestClient(app, client=("127.0.0.1", 50001))
    denied = TestClient(app, client=("10.1.2.3", 50001))
    assert denied.post("/reviewer/create_connection", headers={"Authorization": "Bearer reviewer-secret-value-123"}, json={"task_id": "task-a", "agent_name": "sample"}).status_code == 403
    assert loopback.post("/reviewer/create_connection", json={"task_id": "task-a", "agent_name": "sample"}).status_code == 401
    assert loopback.post("/reviewer/create_connection", headers={"Authorization": "Bearer reviewer-secret-value-123", "Origin": "https://elsewhere.invalid"}, json={"task_id": "task-a", "agent_name": "sample"}).status_code == 403
    grant = loopback.post("/reviewer/create_connection", headers={"Authorization": "Bearer reviewer-secret-value-123"}, json={"task_id": "task-a", "agent_name": "sample"})
    assert grant.status_code == 200
    agent_headers = {"Authorization": "Bearer " + grant.json()["token"]}
    assert loopback.post("/agent/create_connection", headers=agent_headers, json={}).status_code == 404
    assert loopback.post("/agent/submit_batch", headers=agent_headers, json=_batch()).json()["status"] == "pending_review_proposal"
    listed = loopback.post("/reviewer/list_batches", headers={"Authorization": "Bearer reviewer-secret-value-123"}, json={"task_id": "task-a"})
    assert listed.status_code == 200 and listed.json()["batches"][0]["batch_id"] == "batch-a"
    assert loopback.post("/agent/nope", headers=agent_headers, json={}).status_code == 404
    store.close()


def test_http_rejections_are_stable_and_do_not_echo_secrets(tmp_path):
    from app.agent_link.http_app import create_agent_link_app
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    app = create_agent_link_app(AgentLinkService(store, reviewer_token="reviewer-secret-value-123"), max_request_bytes=100)
    client = TestClient(app, client=("127.0.0.1", 50002))
    response = client.post("/reviewer/create_connection", headers={"Authorization": "Bearer wrong-secret"}, json={"task_id": "task-a", "agent_name": "sample"})
    assert response.status_code == 401
    assert "wrong-secret-value-123" not in response.text and "reviewer-secret-value-123" not in response.text
    too_large = client.post("/reviewer/create_connection", headers={"Authorization": "Bearer reviewer-secret"}, content=b"{" + b"x" * 200, headers_update=None) if False else client.post("/reviewer/create_connection", headers={"Authorization": "Bearer reviewer-secret", "content-type": "application/json"}, content=b"{" + b"x" * 200)
    assert too_large.status_code == 413
    assert store.snapshot()["connections"] == {}
    store.close()



def test_chunked_request_stops_reading_at_limit(tmp_path):
    import asyncio
    from app.agent_link.http_app import create_agent_link_app
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore

    store = AgentLinkStore(tmp_path / "inbox.json")
    app = create_agent_link_app(AgentLinkService(store, reviewer_token="reviewer-secret-value-123"), max_request_bytes=10)
    received, sent = [], []
    async def receive():
        index = len(received); received.append(index)
        return {"type": "http.request", "body": b"abcdefgh", "more_body": index < 3}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/reviewer/create_connection", "raw_path": b"/reviewer/create_connection", "query_string": b"", "headers": [(b"authorization", b"Bearer reviewer-secret-value-123"), (b"content-type", b"application/json")], "client": ("127.0.0.1", 50003), "server": ("127.0.0.1", 50003)}
    asyncio.run(app(scope, receive, send))
    assert sent[0]["status"] == 413
    assert len(received) == 2
    store.close()


def test_bridge_rejects_unsafe_token_before_network_without_echo():
    from app.agent_link.mcp_bridge import _call
    secret = "synthetic-private-token\ninvalid"
    with pytest.raises(RuntimeError) as failure:
        _call("http://127.0.0.1:1", secret, "status", {})
    assert secret not in str(failure.value)
