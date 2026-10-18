"""公共内容读取走真实来源、宿主、HTTP 和 MCP，不注入历史学习内容。"""

import asyncio
from contextlib import contextmanager
import json

import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from app.agent_link.contracts import AgentLinkError, canonical_hash
from app.desktop_review.host import DesktopReviewHost
from tests.test_formal_learning_observation import _rig, _request, REVIEWER
from tests.test_formal_learning_runtime_controls import _mcp_server


class Reader:
    def __init__(self):
        self.text = "岗位正文\n" * 3000 + "结束标记"
        self.calls = []
        self.partial = False
        self.change_during_read = False

    def inspect_regions(self, bound):
        self.calls.append(("inspect", bound.handle))
        return {"regions": [{"region_id": "body", "name": "正文", "control_type": "Document",
            "bbox": {"x": 1, "y": 2, "w": 100, "h": 50}, "reader": "uia_text_pattern",
            "reference": {"private_fingerprint": "server-owned"}}], "truncated": False}

    def read_region(self, bound, reference, max_chars):
        assert reference == {"private_fingerprint": "server-owned"}
        self.calls.append(("read", bound.handle))
        result = {"text": self.text[:max_chars], "provider": "windows_uia",
            "method": "descendant_text" if self.partial else "text_pattern_document_range",
            "truncated": len(self.text) > max_chars, "read_complete": not self.partial and len(self.text) <= max_chars,
            "completion_basis": "descendant_inventory_not_proof_of_complete_content" if self.partial else "uia_document_range",
            "region_reference": reference}
        if self.change_during_read:
            self.text += "变化"
        return result


@contextmanager
def rig(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        reader = Reader()
        provider = host._service._learning_observation_provider.content
        provider.reader = reader
        observed = host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        def call(operation, **args):
            return host._service.agent_call(connection["token"], operation, {"segment_id": segment["segment_id"], **args})
        inspected = call("inspect_learning_content", batch_id=observed["batch_id"])
        request = {"inspection_id": inspected["inspection_id"], "region_id": "body", "idempotency_key": "first-read"}
        yield host, connection, segment, provider, reader, call, request, captures


def test_public_content_read_persists_full_unicode_and_reopens_without_stale_pointer(tmp_path, monkeypatch):
    with rig(tmp_path, monkeypatch) as (host, connection, segment, provider, reader, call, request, captures):
        result = call("read_learning_content", **request)
        assert result["text"] == reader.text and result["text"].endswith("结束标记")
        assert result["read_complete"] and not result["truncated"]
        assert result["scope"] == "selected_region_only"
        assert result["action_executed"] is False and result["scroll_performed"] is False
        assert "reference" not in result and "server-owned" not in json.dumps(result)
        assert call("read_learning_content", **request) == result
        later = call("read_learning_content", **{**request, "idempotency_key": "second-read"})
        latest = next(provider.root.rglob("latest.json"))
        assert json.loads(latest.read_text(encoding="utf-8"))["snapshot_id"] == later["snapshot_id"]
        assert call("read_learning_content", **request) == result
        assert json.loads(latest.read_text(encoding="utf-8"))["snapshot_id"] == later["snapshot_id"]
        assert all(c == {"save_image": True, "focus_window": False, "purpose": "learning-observation"}
                   for capture in captures for c in capture.calls)
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        reopened._service._learning_observation_provider.content.reader = reader
        assert reopened._service.agent_call(connection["token"], "read_learning_content", {
            "segment_id": segment["segment_id"], **request}) == result
    finally:
        reopened.close()


@pytest.mark.parametrize("kind", ["truncated", "partial"])
def test_content_completeness_never_uses_no_new_content_as_proof(tmp_path, monkeypatch, kind):
    with rig(tmp_path, monkeypatch) as (_host, _connection, _segment, _provider, reader, call, request, _captures):
        reader.partial = kind == "partial"
        value = call("read_learning_content", **request, max_chars=5 if kind == "truncated" else 200000)
        assert not value["read_complete"]
        assert value["truncated"] == (kind == "truncated")


@pytest.mark.parametrize("kind", ["foreign", "mutated", "unknown_region", "changed_text", "closed_segment", "stale_surface", "in_read_change", "idempotency"])
def test_content_negative_cases_do_not_write_success(tmp_path, monkeypatch, kind):
    with rig(tmp_path, monkeypatch) as (host, connection, segment, provider, reader, call, request, _captures):
        if kind == "foreign":
            other = host._service.reviewer_call(REVIEWER, "create_connection", {"task_id": connection["task_id"], "agent_name": "foreign"})
            call = lambda op, **args: host._service.agent_call(other["token"], op, {"segment_id": segment["segment_id"], **args})
        elif kind == "mutated":
            path = next(provider.root.rglob("inspections/*.json"))
            value = json.loads(path.read_text(encoding="utf-8")); value["regions"]["regions"][0]["name"] = "改"
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        elif kind == "unknown_region":
            request["region_id"] = "unknown"
        elif kind in {"changed_text", "idempotency"}:
            call("read_learning_content", **request)
            if kind == "changed_text": reader.text += "已变更"
            else: request["max_chars"] = 100
        elif kind == "closed_segment":
            call("finish_learning_segment", expected_revision=call("get_learning_segment")["revision"])
        elif kind == "stale_surface":
            from tests.test_formal_fresh_learning_observation import _owner, _ScreenshotService
            import app.agent.fresh_learning_factory as factory
            monkeypatch.setattr(factory, "create_fresh_learning_observation_owner", lambda **kwargs: _owner(
                kwargs["project_root"], screenshot=_ScreenshotService(tmp_path / "changed", width=159)))
        elif kind == "in_read_change":
            reader.change_during_read = True
        before = sorted((str(p), p.read_bytes()) for p in provider.root.rglob("*.json"))
        with pytest.raises(AgentLinkError):
            call("read_learning_content", **request)
        assert sorted((str(p), p.read_bytes()) for p in provider.root.rglob("*.json")) == before


def test_content_tools_real_http_and_mcp_stdio(tmp_path, monkeypatch):
    with rig(tmp_path, monkeypatch) as (host, _connection, segment, _provider, reader, _call, request, _captures):
        host.start()
        async def run():
            async with stdio_client(_mcp_server(host.status()["base_url"], _connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    names = {t.name for t in (await client.list_tools()).tools}
                    assert {"inspect_learning_content", "read_learning_content"} <= names
                    response = await client.call_tool("read_learning_content", {"segment_id": segment["segment_id"], **request})
                    assert not response.is_error
                    assert response.structured_content["text"] == reader.text
                    invalid = await client.call_tool("read_learning_content", {"segment_id": segment["segment_id"], **request, "region_id": "unknown"})
                    assert invalid.is_error and "server-owned" not in str(invalid)
        asyncio.run(run())


def test_content_latest_pointer_recovers_after_partial_commit_without_rewinding(tmp_path, monkeypatch):
    import app.desktop_review.learning_content as module
    with rig(tmp_path, monkeypatch) as (_host, _connection, _segment, provider, _reader, call, request, _captures):
        writer = module._atomic_write_bytes
        def interrupted(path, payload):
            if path.name == "latest.json": raise OSError("simulated write failure")
            writer(path, payload)
        monkeypatch.setattr(module, "_atomic_write_bytes", interrupted)
        with pytest.raises(AgentLinkError, match="content reading failed"):
            call("read_learning_content", **request)
        assert not list(provider.root.rglob("latest.json"))
        monkeypatch.setattr(module, "_atomic_write_bytes", writer)
        recovered = call("read_learning_content", **request)
        latest = next(provider.root.rglob("latest.json"))
        assert json.loads(latest.read_text(encoding="utf-8"))["snapshot_id"] == recovered["snapshot_id"]
        later = call("read_learning_content", **{**request, "idempotency_key": "later"})
        call("read_learning_content", **request)
        assert json.loads(latest.read_text(encoding="utf-8"))["snapshot_id"] == later["snapshot_id"]
