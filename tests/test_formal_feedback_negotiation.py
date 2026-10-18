from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
import sys
from types import ModuleType

from PIL import Image
import pytest

from app.agent_link import mcp_bridge
from app.agent_link.contracts import canonical_hash, validate_batch
from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.mcp_bridge import _call
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


_TOKEN = "feedback-negotiation-reviewer"
_LIMIT = 2_500_000


def _batch() -> dict:
    image = Image.new("L", (1024, 1024), 0)
    output = BytesIO()
    image.save(output, format="PNG", compress_level=0)
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "feedback-negotiation-batch",
        "batch_id": "feedback-negotiation-batch",
        "title": "反馈协商",
        "learning_outcome": "completed",
        "screenshots": [{
            "screenshot_id": "feedback-capture",
            "png_base64": base64.b64encode(output.getvalue()).decode("ascii"),
        }],
        "interfaces": [{
            "interface_id": "feedback-interface",
            "screenshot_id": "feedback-capture",
            "meaning": "反馈读取", "regions": [],
        }],
        "relationships": [], "steps": [], "issues": [],
    }


def _wire(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _host_with_feedback(tmp_path, issue_count: int):
    store = AgentLinkStore(tmp_path / "feedback-negotiation-inbox.json")
    service = AgentLinkService(store, _TOKEN)
    host = OwnedAgentLinkHttpHost(service)
    grant = service.reviewer_call(_TOKEN, "create_connection", {
        "task_id": "feedback-negotiation-task", "agent_name": "feedback-negotiation-agent",
    })
    batch = _batch()
    service.agent_call(grant["token"], "submit_batch", batch)
    normalized = validate_batch(batch)
    baseline = {
        "contract_version": "desktop_review_baseline_v1",
        "task_id": "feedback-negotiation-task",
        "workspace_revision": 1,
        "source_ref": canonical_hash(normalized),
        "batch_sha256": canonical_hash(normalized),
        "batch": batch,
    }
    service.reviewer_call(_TOKEN, "record_feedback", {
        "task_id": "feedback-negotiation-task", "batch_id": batch["batch_id"],
        "idempotency_key": "feedback-negotiation-record", "expected_revision": 0,
        "notes": [], "issues": [{
            "issue_id": f"feedback-issue-{index}",
            "scope": {"interface_ids": ["feedback-interface"], "relationship_ids": []},
            "message": "请审核", "review_baseline": deepcopy(baseline),
        } for index in range(issue_count)],
    })
    return store, service, host, grant["token"], batch


def test_legacy_http_feedback_remains_canonical_and_view_is_explicit(tmp_path) -> None:
    store, service, host, token, batch = _host_with_feedback(tmp_path, 1)
    try:
        base_url = host.start()
        status = _call(base_url, token, "status", {})
        assert status["feedback_view"] == {
            "operation": "read_feedback_view",
            "contract_version": "agent_link_feedback_view_v1",
        }
        canonical = _call(base_url, token, "read_feedback", {"batch_id": batch["batch_id"]})
        assert "review_baseline" in canonical["issues"][0]
        assert "png_base64" in canonical["issues"][0]["review_baseline"]["batch"]["screenshots"][0]
        view = _call(base_url, token, "read_feedback_view", {"batch_id": batch["batch_id"]})
        assert view["feedback_view_contract"] == "agent_link_feedback_view_v1"
        assert "review_baseline" not in view["issues"][0]
        assert view["issues"][0]["review_baseline_view"]["contract_version"] == "desktop_review_baseline_view_v1"
        assert service.agent_call(token, "read_feedback", {"batch_id": batch["batch_id"]}) == canonical
    finally:
        host.close()
        store.close()


def test_new_mcp_negotiation_uses_compact_view_before_loopback_response_limit(tmp_path) -> None:
    store, _, host, token, batch = _host_with_feedback(tmp_path, 2)
    try:
        base_url = host.start()
        with pytest.raises(RuntimeError, match="response exceeds limit"):
            _call(base_url, token, "read_feedback", {"batch_id": batch["batch_id"]})
        view = mcp_bridge._read_learning_feedback(base_url, token, batch["batch_id"])
        assert len(_wire(view)) < _LIMIT
        assert all("review_baseline" not in issue for issue in view["issues"])
    finally:
        host.close()
        store.close()


def test_mcp_falls_back_to_legacy_only_when_capability_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def old_host(_: str, __: str, operation: str, arguments: dict) -> dict:
        calls.append(operation)
        if operation == "status":
            return {"contract_version": "agent_link_v1", "capabilities": ["read_feedback"]}
        assert operation == "read_feedback" and arguments == {"batch_id": "old-batch"}
        return {"contract_version": "agent_link_v1", "batch_id": "old-batch", "revision": 0, "notes": [], "issues": [], "staging_only": True}

    monkeypatch.setattr(mcp_bridge, "_call", old_host)
    assert mcp_bridge._read_learning_feedback("http://127.0.0.1:1234", "a" * 32, "old-batch")["batch_id"] == "old-batch"
    assert calls == ["status", "read_feedback"]


def test_mcp_does_not_silently_fallback_after_advertised_view_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def advertised_but_broken(_: str, __: str, operation: str, ___: dict) -> dict:
        calls.append(operation)
        if operation == "status":
            return {"feedback_view": {"operation": "read_feedback_view", "contract_version": "agent_link_feedback_view_v1"}}
        if operation == "read_feedback_view":
            raise RuntimeError("Agent Link request rejected")
        raise AssertionError("legacy fallback must not be called")

    monkeypatch.setattr(mcp_bridge, "_call", advertised_but_broken)
    with pytest.raises(RuntimeError, match="rejected"):
        mcp_bridge._read_learning_feedback("http://127.0.0.1:1234", "a" * 32, "new-batch")
    assert calls == ["status", "read_feedback_view"]


@pytest.mark.parametrize("capability", [None, {}, {"operation": "read_feedback_view", "contract_version": "future_version"}])
def test_mcp_rejects_invalid_advertised_capability_without_legacy_fallback(monkeypatch, capability):
    calls = []

    def backend(_url, _token, operation, _arguments):
        calls.append(operation)
        return {"feedback_view": capability}

    monkeypatch.setattr(mcp_bridge, "_call", backend)
    with pytest.raises(RuntimeError, match="capability is invalid"):
        mcp_bridge._read_learning_feedback("http://127.0.0.1:1234", "a" * 32, "batch")
    assert calls == ["status"]


def test_mcp_rejects_unversioned_advertised_view_response(monkeypatch):
    calls = []

    def backend(_url, _token, operation, _arguments):
        calls.append(operation)
        if operation == "status":
            return {"feedback_view": {"operation": "read_feedback_view", "contract_version": "agent_link_feedback_view_v1"}}
        return {"issues": []}

    monkeypatch.setattr(mcp_bridge, "_call", backend)
    with pytest.raises(RuntimeError, match="feedback-view response contract is invalid"):
        mcp_bridge._read_learning_feedback("http://127.0.0.1:1234", "a" * 32, "batch")
    assert calls == ["status", "read_feedback_view"]


def test_mcp_registration_stays_at_four_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[str] = []

    class FakeServer:
        def __init__(self, **_: object) -> None:
            pass

        def add_tool(self, function, *, name: str, description: str) -> None:
            assert callable(function) and description
            registered.append(name)

        def run(self, *, transport: str) -> None:
            assert transport == "stdio"

    fake_mcp = ModuleType("mcp")
    fake_server = ModuleType("mcp.server")
    fake_server.MCPServer = FakeServer
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
    monkeypatch.delenv("AGENT_LINK_ARTIFACT_BUNDLE", raising=False)
    monkeypatch.setattr(mcp_bridge, "_configuration", lambda: ("http://127.0.0.1:1234", "a" * 32))
    monkeypatch.setattr(mcp_bridge, "_call", lambda _url, _token, operation, arguments: (
        {"contract_version": "agent_link_v1", "capabilities": ["read_feedback"]}
        if operation == "status" and arguments == {} else pytest.fail("unexpected Agent Link call")
    ))
    mcp_bridge.run_stdio()
    assert sorted(registered) == [
        "agent_link_status", "read_learning_feedback", "submit_learning_batch", "submit_relearning_candidate",
    ]
