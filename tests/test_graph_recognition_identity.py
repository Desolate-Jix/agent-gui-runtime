"""可见身份必须显式绑定原节点原图；文字说明不会自动变成身份。"""

from copy import deepcopy

import pytest

from app.agent_link.graph_contract import GraphContractError, validate_graph_operations
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_graph_exact_review import TASK, BATCH, _runtime


def _identity(node, text="Visible fixture title", bbox=None):
    return {"type": "update_node_recognition_text", "node_id": node["node_id"],
            "recognition_text": text, "bbox": bbox if bbox is not None else [3, 4, 25, 14],
            "source_screenshot_path": node["evidence"]["source_screenshot_path"],
            "source_screenshot_sha256": node["evidence"]["source_screenshot_sha256"]}


def test_identity_edit_creates_new_replayable_revision_without_approval_or_source_rewrite(tmp_path):
    store, service, facade, original = _runtime(tmp_path)
    try:
        first = facade.create_graph_revision(TASK, BATCH, 0)
        node = first["graph"]["nodes"][0]
        old = deepcopy(first)
        original_path = facade._artifact_root / first["source_refs"]["original_batch_path"]
        source_bytes = original_path.read_bytes()
        operation = _identity(node)
        changed = facade.apply_graph_edit(first["logical_workflow_id"], first["revision"],
            first["content_sha256"], operation, "visible-identity")
        result = changed["graph"]["nodes"][0]
        assert result["recognition_text"] == "Visible fixture title"
        assert result["recognition_anchor"] == {
            "contract_version": "graph_node_recognition_anchor_v1", "node_id": node["node_id"],
            "text": "Visible fixture title", "source_screenshot_path": operation["source_screenshot_path"],
            "source_screenshot_sha256": operation["source_screenshot_sha256"], "bbox": [3, 4, 25, 14]}
        assert result["display_name"] == node["display_name"]
        assert result["reviewed_by_human"] is False
        assert result["artifact_is_authorization"] is False
        assert changed["parent_sha256"] == first["content_sha256"]
        assert facade.apply_graph_edit(first["logical_workflow_id"], first["revision"],
            first["content_sha256"], operation, "visible-identity") == changed
        assert facade.load_graph_revision(first["logical_workflow_id"], first["revision"]) == old
        assert original_path.read_bytes() == source_bytes
        assert facade.load_graph_revision(first["logical_workflow_id"]) == changed
        from app.desktop_review.workspace import NativeReviewFacade
        from tests.test_formal_graph_exact_review import TOKEN
        root = facade._artifact_root
        facade.close()
        facade = NativeReviewFacade(service, TOKEN, root)
        assert facade.load_graph_revision(first["logical_workflow_id"]) == changed
    finally:
        facade.close(); store.close()


@pytest.mark.parametrize("mutate", [
    lambda op: op.update(source_screenshot_sha256="0" * 64),
    lambda op: op.update(source_screenshot_path="other.png"),
    lambda op: op.update(node_id="other-node"),
    lambda op: op.update(recognition_text=" "),
    lambda op: op.update(bbox=[-1, 0, 2, 2]),
    lambda op: op.update(bbox=[0, 0, 0, 4]),
    lambda op: op.update(bbox=[0, 0, 10000, 10000]),
    lambda op: op.update(bbox=[True, 0, 2, 2]),
])
def test_wrong_identity_evidence_cannot_advance_graph(tmp_path, mutate):
    store, service, facade, original = _runtime(tmp_path)
    try:
        first = facade.create_graph_revision(TASK, BATCH, 0)
        operation = _identity(first["graph"]["nodes"][0])
        mutate(operation)
        with pytest.raises(DesktopReviewError):
            facade.apply_graph_edit(first["logical_workflow_id"], first["revision"],
                first["content_sha256"], operation, "bad-identity")
        assert facade.load_graph_revision(first["logical_workflow_id"]) == first
    finally:
        facade.close(); store.close()


def test_identity_proposal_is_restricted_to_issue_scope(tmp_path):
    store, service, facade, original = _runtime(tmp_path)
    try:
        first = facade.create_graph_revision(TASK, BATCH, 0)
        operation = _identity(first["graph"]["nodes"][0])
        with pytest.raises(GraphContractError, match="outside scope"):
            validate_graph_operations([operation], first["graph"],
                {"node_ids": [first["graph"]["nodes"][1]["node_id"]], "edge_ids": []})
    finally:
        facade.close(); store.close()


def test_agent_can_propose_visible_identity_but_only_reviewer_adopts_it(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.agent_link.host import OwnedAgentLinkHttpHost
    from app.agent_link.mcp_bridge import _call
    from app.desktop_review.workspace import NativeReviewFacade
    from tests.test_formal_graph_exact_review import TOKEN, _batch

    store = AgentLinkStore(tmp_path / "identity-agent-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": TASK, "agent_name": "identity-agent"})
    service.agent_call(grant["token"], "submit_batch", _batch())
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "identity-agent-artifacts")
    host = OwnedAgentLinkHttpHost(service)
    try:
        base_url = host.start()
        assert "update_node_recognition_text" in _call(base_url, grant["token"], "status", {})["graph_contracts"]["operations"]
        first = facade.create_graph_revision(TASK, BATCH, 0)
        node = first["graph"]["nodes"][0]
        requested = facade.request_graph_relearn(first["logical_workflow_id"], first["revision"],
            first["content_sha256"], 0, {"node_ids": [node["node_id"]], "edge_ids": []},
            "Identify the visible screen title", "identity-request")
        feedback = _call(base_url, grant["token"], "read_feedback_view", {"batch_id": BATCH})
        issue = feedback["issues"][0]
        visible = issue["review_baseline_view"]["snapshot"]["graph"]["nodes"][0]
        candidate = {"contract_version": "agent_link_graph_candidate_v1", "idempotency_key": "identity-proposal",
            "batch_id": BATCH, "issue_id": issue["issue_id"], "baseline_revision": requested["revision"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "logical_workflow_id": first["logical_workflow_id"], "baseline_graph_sha256": first["content_sha256"],
            "scope": issue["scope"], "changes": [_identity(visible)]}
        receipt = _call(base_url, grant["token"], "submit_candidate", candidate)
        assert facade.load_graph_revision(first["logical_workflow_id"]) == first
        comparison = facade.compare_graph_relearn_candidate(first["logical_workflow_id"], first["revision"],
            first["content_sha256"], receipt["candidate_id"])
        preview = comparison["operation_previews"][0]
        assert preview["before"] is None
        assert preview["after"]["text"] == "Visible fixture title"
        adopted = facade.adopt_graph_relearn_candidate(first["logical_workflow_id"], first["revision"],
            first["content_sha256"], receipt["candidate_id"], comparison["candidate_sha256"],
            comparison["review_baseline_sha256"], "identity-adopt")
        assert adopted["graph"]["nodes"][0]["recognition_text"] == "Visible fixture title"
        assert adopted["graph"]["nodes"][0]["reviewed_by_human"] is False
        assert facade.load_graph_revision(first["logical_workflow_id"], first["revision"]) == first
    finally:
        facade.close(); host.close(); store.close()
