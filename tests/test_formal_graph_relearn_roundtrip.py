from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.mcp_bridge import _call
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.agent_link.contracts import AgentLinkError
from app.agent_link.review_baseline import candidate_content_sha256
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from app.desktop_review import graph_revision
from app.desktop_review.graph_revision import GraphRevisionService


TOKEN = "fresh-graph-relearn-reviewer-token"
TASK = "fresh-graph-relearn-task"
BATCH = "fresh-graph-relearn-batch"


def _batch() -> dict:
    image = Image.new("RGB", (96, 64), "white")
    stream = BytesIO(); image.save(stream, format="PNG")
    interfaces = []
    for index, identity in enumerate(("list", "detail", "result")):
        interfaces.append({"interface_id": identity, "screenshot_id": "capture", "meaning": identity,
                           "regions": [{"region_id": f"region-{identity}", "bbox": [2 + index, 3, 20, 12], "name": identity, "meaning": identity}]})
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "fresh-batch-key", "batch_id": BATCH,
        "title": "全新三状态图", "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "capture", "png_base64": base64.b64encode(stream.getvalue()).decode("ascii")}],
        "interfaces": interfaces,
        "relationships": [{"relationship_id": "rel-open", "from_interface_id": "list", "to_interface_id": "detail", "kind": "打开详情"}],
        "steps": [{"step_id": "open", "action_type": "open_detail", "target_region_id": "region-list", "start_state": "list", "arrival_state": "detail", "prerequisites": ["列表可见"], "expected_result": "详情可见", "stop_condition": "不符即停"}],
        "issues": [],
    }


def _node(snapshot: dict, external_id: str) -> dict:
    return next(item for item in snapshot["graph"]["nodes"] if item["external_interface_id"] == external_id)


def test_real_loopback_graph_feedback_candidate_adoption_and_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store_path, root = tmp_path / "inbox.json", tmp_path / "artifacts"
    store = AgentLinkStore(store_path); service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": TASK, "agent_name": "fresh-agent"})
    host = OwnedAgentLinkHttpHost(service); base_url = host.start()
    facade = NativeReviewFacade(service, TOKEN, root)
    original = _batch(); original_bytes = deepcopy(original)
    try:
        _call(base_url, grant["token"], "submit_batch", original)
        stored_original = deepcopy(service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"])
        created = facade.create_graph_revision(TASK, BATCH, 0, {"open": ["rel-open"]})
        r1_path = root / "desktop-review" / "graph-revisions" / created["logical_workflow_id"] / "revisions" / f"{created['content_sha256']}.json"
        r1_bytes = r1_path.read_bytes()
        source = _node(created, "list"); target = _node(created, "result"); edge = created["graph"]["edges"][0]
        requested = facade.request_graph_relearn(
            created["logical_workflow_id"], 1, created["content_sha256"], 0,
            {"node_ids": [source["node_id"]], "edge_ids": [edge["edge_id"]]},
            "修正节点含义、区域、目标及语义", "request-graph-relearn",
        )
        retried_request = facade.request_graph_relearn(
            created["logical_workflow_id"], 1, created["content_sha256"], 0,
            {"node_ids": [source["node_id"]], "edge_ids": [edge["edge_id"]]},
            "修正节点含义、区域、目标及语义", "request-graph-relearn",
        )
        assert retried_request["receipt"] == requested["receipt"]
        assert retried_request["issue"] == requested["issue"]
        with pytest.raises(DesktopReviewError):
            facade.request_graph_relearn(
                created["logical_workflow_id"], 1, created["content_sha256"], 0,
                {"node_ids": [source["node_id"]], "edge_ids": [edge["edge_id"]]},
                "不同请求内容", "request-graph-relearn",
            )
        visible = _call(base_url, grant["token"], "read_feedback_view", {"batch_id": BATCH})
        issue = visible["issues"][0]; baseline = issue["review_baseline_view"]
        assert baseline["contract_version"] == "desktop_graph_review_baseline_view_v1"
        assert baseline["graph_sha256"] == created["content_sha256"]
        candidate = {
            "contract_version": "agent_link_graph_candidate_v1", "idempotency_key": "candidate-graph-relearn",
            "batch_id": BATCH, "issue_id": issue["issue_id"], "baseline_revision": requested["revision"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "logical_workflow_id": created["logical_workflow_id"], "baseline_graph_sha256": created["content_sha256"],
            "scope": issue["scope"],
            "changes": [
                {"type": "update_node_meaning", "node_id": source["node_id"], "meaning": "新列表含义"},
                {"type": "update_region_bbox", "node_id": source["node_id"], "region_id": "region-list", "bbox": [8, 9, 22, 13]},
                {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target["node_id"]},
                {"type": "update_edge_semantics", "edge_id": edge["edge_id"], "expected_result": "结果页可见", "stop_condition": "结果页不符即停", "prerequisites": ["列表可见", "目标可用"], "relationship_kinds": {"rel-open": "打开结果"}},
            ],
        }
        foreign = service.reviewer_call(TOKEN, "create_connection", {"task_id": "foreign-task", "agent_name": "foreign-agent"})
        with pytest.raises(RuntimeError, match="rejected"):
            _call(base_url, foreign["token"], "submit_candidate", candidate)
        wrong_graph = deepcopy(candidate); wrong_graph["idempotency_key"] = "wrong-graph-hash"; wrong_graph["baseline_graph_sha256"] = "f" * 64
        with pytest.raises(RuntimeError, match="rejected"):
            _call(base_url, grant["token"], "submit_candidate", wrong_graph)
        legacy = {"contract_version": "agent_link_v1", "idempotency_key": "legacy-on-graph", "batch_id": BATCH,
                  "issue_id": issue["issue_id"], "baseline_revision": requested["revision"],
                  "review_baseline_sha256": issue["review_baseline_sha256"],
                  "scope": {"interface_ids": ["list"], "relationship_ids": []},
                  "changes": [{"change_type": "semantic", "target_type": "interface", "target_id": "list", "meaning": "错误混用"}]}
        with pytest.raises(AgentLinkError, match="legacy candidate"):
            service.agent_call(grant["token"], "submit_candidate", legacy)
        receipt = _call(base_url, grant["token"], "submit_candidate", candidate)
        compared = facade.compare_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"])
        assert compared["status"] == "current" and compared["changed"] is True
        changed_candidate = deepcopy(candidate); changed_candidate["idempotency_key"] = "candidate-graph-relearn-changed"; changed_candidate["changes"][0]["meaning"] = "另一候选含义"
        changed_receipt = _call(base_url, grant["token"], "submit_candidate", changed_candidate)
        changed_compared = facade.compare_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], changed_receipt["candidate_id"])
        with pytest.raises(DesktopReviewError):
            facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"], "0" * 64, compared["review_baseline_sha256"], "adopt-graph-relearn")
        with pytest.raises(DesktopReviewError):
            facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"], compared["candidate_sha256"], "0" * 64, "adopt-graph-relearn")
        real_head_write = graph_revision._atomic_write_bytes
        def interrupted(path: Path, payload: bytes) -> None:
            if path.name == "draft_head.json":
                raise OSError("simulated graph adoption head failure")
            real_head_write(path, payload)
        monkeypatch.setattr(graph_revision, "_atomic_write_bytes", interrupted)
        with pytest.raises(DesktopReviewError, match="原子图采用操作失败"):
            facade.adopt_graph_relearn_candidate(
                created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"],
                compared["candidate_sha256"], compared["review_baseline_sha256"], "adopt-graph-relearn",
            )
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 1
        monkeypatch.setattr(graph_revision, "_atomic_write_bytes", real_head_write)
        adopted = facade.adopt_graph_relearn_candidate(
            created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"],
            compared["candidate_sha256"], compared["review_baseline_sha256"], "adopt-graph-relearn",
        )
        assert adopted["revision"] == 2
        assert facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"], compared["candidate_sha256"], compared["review_baseline_sha256"], "adopt-graph-relearn") == adopted
        with pytest.raises(DesktopReviewError, match="idempotency_key"):
            facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], changed_receipt["candidate_id"], changed_compared["candidate_sha256"], changed_compared["review_baseline_sha256"], "adopt-graph-relearn")
        with pytest.raises(DesktopReviewError):
            facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"], "0" * 64, compared["review_baseline_sha256"], "adopt-graph-relearn")
        service.reviewer_call(TOKEN, "withdraw_issue", {"task_id": TASK, "batch_id": BATCH, "issue_id": issue["issue_id"], "expected_revision": 1, "idempotency_key": "withdraw-after-adopt"})
        assert facade.adopt_graph_relearn_candidate(created["logical_workflow_id"], 1, created["content_sha256"], receipt["candidate_id"], compared["candidate_sha256"], compared["review_baseline_sha256"], "adopt-graph-relearn") == adopted
        changed_node, changed_edge = _node(adopted, "list"), adopted["graph"]["edges"][0]
        assert changed_node["display_name"] == "新列表含义" and changed_node["regions"][0]["bbox"] == [8, 9, 22, 13]
        assert changed_edge["target_node_id"] == target["node_id"] and changed_edge["success_conditions"] == ["结果页可见"]
        assert changed_edge["external_relationships"][0]["kind"] == "打开结果"
        assert service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"] == stored_original
        assert r1_path.read_bytes() == r1_bytes
        graph_id, graph_hash = adopted["logical_workflow_id"], adopted["content_sha256"]
    finally:
        facade.close(); host.close(); store.close()
    reopened_store = AgentLinkStore(store_path); reopened_service = AgentLinkService(reopened_store, TOKEN)
    reopened = NativeReviewFacade(reopened_service, TOKEN, root)
    try:
        loaded = reopened.load_graph_revision(graph_id)
        assert loaded["content_sha256"] == graph_hash and _node(loaded, "list")["display_name"] == "新列表含义"
        assert hashlib.sha256(base64.b64decode(original_bytes["screenshots"][0]["png_base64"])).hexdigest() == loaded["source_refs"]["screenshots"][0]["sha256"]
        validator = GraphRevisionService(reopened)
        mutations = {
            "request digest": lambda item: item["change"]["adoption"].__setitem__("request_sha256", "0" * 64),
            "logical id": lambda item: item["change"]["adoption"]["candidate"].__setitem__("logical_workflow_id", "workflow-" + "e" * 64),
            "batch id": lambda item: item["change"]["adoption"]["candidate"].__setitem__("batch_id", "foreign"),
            "baseline digest": lambda item: (item["change"]["adoption"].__setitem__("review_baseline_sha256", "1" * 64), item["change"]["adoption"]["candidate"].__setitem__("review_baseline_sha256", "1" * 64)),
            "issue id": lambda item: (item["change"]["adoption"].__setitem__("issue_id", "foreign-issue"), item["change"]["adoption"]["candidate"].__setitem__("issue_id", "foreign-issue")),
            "scope": lambda item: item["change"]["adoption"]["candidate"]["scope"]["node_ids"].append("nonexistent"),
        }
        for mutation in mutations.values():
            tampered = deepcopy(loaded); mutation(tampered)
            # 同步内外候选摘要，不能仅因遗漏重新封装就让血缘负测通过。
            candidate_sha = candidate_content_sha256(tampered["change"]["adoption"]["candidate"])
            tampered["change"]["adoption"]["candidate"]["candidate_sha256"] = candidate_sha
            tampered["change"]["adoption"]["candidate_sha256"] = candidate_sha
            tampered["content_sha256"] = validator._content_sha(tampered)
            with pytest.raises(DesktopReviewError):
                validator._validate_snapshot(tampered)
    finally:
        reopened.close(); reopened_store.close()


def test_graph_candidate_stale_withdrawn_and_reverse_protocol_mixing_reject(tmp_path: Path) -> None:
    store = AgentLinkStore(tmp_path / "negative-inbox.json"); service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": TASK, "agent_name": "negative-agent"})
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "negative-artifacts")
    try:
        service.agent_call(grant["token"], "submit_batch", _batch())
        graph = facade.create_graph_revision(TASK, BATCH, 0, {"open": ["rel-open"]})
        node, edge = _node(graph, "list"), graph["graph"]["edges"][0]
        request = facade.request_graph_relearn(graph["logical_workflow_id"], 1, graph["content_sha256"], 0,
                                               {"node_ids": [node["node_id"]], "edge_ids": []}, "修正含义", "negative-request")
        issue = request["issue"]
        candidate = {"contract_version": "agent_link_graph_candidate_v1", "idempotency_key": "negative-candidate",
                     "batch_id": BATCH, "issue_id": issue["issue_id"], "baseline_revision": 1,
                     "review_baseline_sha256": issue["review_baseline_sha256"], "logical_workflow_id": graph["logical_workflow_id"],
                     "baseline_graph_sha256": graph["content_sha256"], "scope": issue["scope"],
                     "changes": [{"type": "update_node_meaning", "node_id": node["node_id"], "meaning": "候选含义"}]}
        receipt = service.agent_call(grant["token"], "submit_candidate", candidate)
        human = facade.apply_graph_edit(graph["logical_workflow_id"], 1, graph["content_sha256"],
                                        {"type": "update_node_meaning", "node_id": node["node_id"], "meaning": "人工含义"}, "human-after-request")
        assert facade.compare_graph_relearn_candidate(graph["logical_workflow_id"], 1, graph["content_sha256"], receipt["candidate_id"])["status"] == "stale"
        service.reviewer_call(TOKEN, "withdraw_issue", {"task_id": TASK, "batch_id": BATCH, "issue_id": issue["issue_id"],
                                                        "expected_revision": 1, "idempotency_key": "withdraw-graph-issue"})
        assert facade.compare_graph_relearn_candidate(graph["logical_workflow_id"], human["revision"], human["content_sha256"], receipt["candidate_id"])["status"] == "withdrawn"
        service.reviewer_call(TOKEN, "record_feedback", {"task_id": TASK, "batch_id": BATCH, "idempotency_key": "legacy-issue",
                                                         "expected_revision": 2, "notes": [], "issues": [{"issue_id": "legacy-only", "scope": {"interface_ids": ["list"], "relationship_ids": []}, "message": "旧协议问题"}]})
        mixed = deepcopy(candidate); mixed["idempotency_key"] = "graph-on-legacy"; mixed["issue_id"] = "legacy-only"; mixed["baseline_revision"] = 3
        with pytest.raises(AgentLinkError, match="graph candidate requires graph issue"):
            service.agent_call(grant["token"], "submit_candidate", mixed)
    finally:
        facade.close(); store.close()
