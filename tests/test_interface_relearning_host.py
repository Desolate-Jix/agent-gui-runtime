"""独立界面重学的公开通信只提交候选，不授予人工采用或动作执行权。"""
import asyncio
import base64
import hashlib
import json

import mcp
import pytest

from app.desktop_review.host import DesktopReviewHost
from tests.test_agent_link_inbox import _batch
from tests.test_agent_link_shared_host import _post
from tests.test_formal_learning_observation import _mcp_server


def _prepare(host, ready):
    connection = host.connections.create_connection("fresh-relearning-task", "isolated-agent")
    batch = _batch("fresh-relearning-batch", "fresh-relearning-import")
    batch["screenshots"] = batch["screenshots"][:1]
    batch["interfaces"] = batch["interfaces"][:1]
    batch.update(steps=[], relationships=[], issues=[])
    code, _ = _post(ready["base_url"] + "/agent/submit_batch", connection["token"], batch)
    assert code == 200
    snap = host.facade.import_interface_content(connection["task_id"], batch["batch_id"], "interface-list")
    issue = host.facade.request_interface_relearning(snap["interface_id"], snap["revision"],
        snap["content_sha256"], [], "整页含义和搜索框需要修正", "fresh-issue")
    return connection, snap, issue


def test_native_relearning_same_task_protocol_and_no_adoption_http(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", "fresh-relearning-reviewer")
    try:
        ready = host.start()
        connection, snap, issue = _prepare(host, ready)
        def post(operation, args, token=None):
            return _post(ready["base_url"] + "/agent/" + operation, token or connection["token"], args)
        code, status = post("status", {})
        assert code == 200
        assert set(status["interface_relearning"]["operations"]) == {
            "list_interface_relearning_feedback", "get_interface_relearning_feedback", "submit_interface_relearning_candidate"}
        code, found = post("list_interface_relearning_feedback", {})
        assert code == 200 and found["issues"][0]["issue_id"] == issue["issue_id"]
        code, feedback = post("get_interface_relearning_feedback", {"issue_id": issue["issue_id"]})
        assert code == 200
        assert feedback["baseline"]["content_sha256"] == snap["content_sha256"]
        raw = base64.b64decode(feedback["screenshot"]["png_base64"], validate=True)
        assert hashlib.sha256(raw).hexdigest() == snap["source"]["screenshot_sha256"]
        assert not any(term in json.dumps(feedback) for term in ("image_path", "reviewer_token", str(tmp_path)))
        request = {"issue_id": issue["issue_id"], "expected_baseline_sha256": snap["content_sha256"],
            "changes": {"meaning": "重学候选：可输入关键词后查看详情"}, "idempotency_key": "fresh-candidate"}
        code, candidate = post("submit_interface_relearning_candidate", request)
        assert code == 200, candidate
        assert host.facade.load_interface_content(snap["interface_id"])["version_id"] == snap["version_id"]
        assert post("submit_interface_relearning_candidate", request) == (code, candidate)
        foreign = host.connections.create_connection("foreign-task", "foreign-agent")
        for operation, args in (("get_interface_relearning_feedback", {"issue_id": issue["issue_id"]}),
                                ("submit_interface_relearning_candidate", request)):
            code, denied = post(operation, args, foreign["token"])
            assert code == 400 and denied["error"]["code"] == "not_found"
        assert post("list_interface_relearning_feedback", {}, foreign["token"])[1]["issues"] == []
        assert post("adopt_interface_relearning", {"issue_id": issue["issue_id"]})[0] == 404
        adopted = host.facade.adopt_interface_relearning(issue["issue_id"], candidate["candidate"]["candidate_id"],
            snap["revision"], snap["content_sha256"], "fresh-adopt")
        assert adopted["status"] == "adopted"
        latest = post("get_interface_memory", {"interface_id": snap["interface_id"]})[1]
        assert latest["content"]["meaning"] == request["changes"]["meaning"]
        assert latest["content_sha256"] != snap["content_sha256"]
        assert latest["execute_binding_enabled"] is False
        code, pinned = post("get_interface_relearning_feedback", {"issue_id": issue["issue_id"]})
        assert code == 200 and pinned["baseline"]["content_sha256"] == snap["content_sha256"]
    finally:
        host.close()


def test_real_mcp_feedback_image_candidate_schema_and_safe_errors(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", "fresh-relearning-reviewer")
    try:
        ready = host.start()
        connection, snap, issue = _prepare(host, ready)
        async def exercise():
            async with mcp.Client(_mcp_server(ready["base_url"], connection["token"])) as client:
                tools = (await client.list_tools()).tools
                names = {item.name for item in tools}
                assert "adopt_interface_relearning" not in names
                result = await client.call_tool("get_interface_relearning_feedback", {"issue_id": issue["issue_id"]})
                assert not result.is_error, result
                assert any(item.type == "image" for item in result.content)
                assert "png_base64" not in result.structured_content["screenshot"]
                assert result.structured_content["baseline"]["content_sha256"] == snap["content_sha256"]
                definition = next(item for item in tools if item.name == "submit_interface_relearning_candidate").input_schema
                assert "InterfaceRelearningChanges" in definition["$defs"]
                request = {"issue_id": issue["issue_id"], "expected_baseline_sha256": snap["content_sha256"],
                    "changes": {"meaning": "MCP 候选"}, "idempotency_key": "mcp-candidate"}
                proposal = await client.call_tool("submit_interface_relearning_candidate", request)
                assert not proposal.is_error, proposal
                assert proposal.structured_content["candidate"]["content"]["meaning"] == "MCP 候选"
                failed = await client.call_tool("submit_interface_relearning_candidate", {
                    **request, "changes": {"meaning": "相同 key 不同候选"}})
                assert failed.is_error and "idempotency_conflict" in str(failed)
                assert host.facade.load_interface_content(snap["interface_id"])["revision"] == snap["revision"]
        asyncio.run(exercise())
    finally:
        host.close()
