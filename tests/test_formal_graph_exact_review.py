from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.exact_review import ExactReviewError
from app.desktop_review.workspace import NativeReviewFacade


TOKEN = "fresh-graph-exact-token"
TASK = "fresh-graph-exact-task"
BATCH = "fresh-graph-exact-batch"
BINDING = {
    "kind": "native", "display_name": "Fresh Editor",
    "executable_identity": "fresh-editor.exe", "product_name": "Fresh Editor",
}


def _batch() -> dict:
    image = Image.new("RGB", (101, 67), (241, 247, 252))
    stream = BytesIO()
    image.save(stream, format="PNG")
    interfaces = []
    for index, identity in enumerate(("state-a", "state-b", "state-c")):
        interfaces.append({
            "interface_id": identity, "screenshot_id": "fresh-capture",
            "meaning": f"Meaning {identity}",
            "regions": [{
                "region_id": f"region-{identity}", "bbox": [3 + index, 4, 25, 14],
                "name": f"Region {identity}", "meaning": f"Control {identity}",
            }],
        })
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "fresh-graph-exact-submit",
        "batch_id": BATCH, "title": "Fresh A B C exact graph", "learning_outcome": "completed",
        "screenshots": [{
            "screenshot_id": "fresh-capture",
            "png_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        }],
        "interfaces": interfaces,
        "relationships": [{
            "relationship_id": "rel-open", "from_interface_id": "state-a",
            "to_interface_id": "state-b", "kind": "opens old B",
        }],
        "steps": [{
            "step_id": "open-result", "action_type": "open_detail",
            "target_region_id": "region-state-a", "start_state": "state-a",
            "arrival_state": "state-b", "prerequisites": ["A visible"],
            "expected_result": "B visible", "stop_condition": "B absent",
        }],
        "issues": [],
    }


def _runtime(tmp_path: Path) -> tuple[AgentLinkStore, AgentLinkService, NativeReviewFacade, dict]:
    store = AgentLinkStore(tmp_path / "fresh-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": TASK, "agent_name": "fresh-exact-agent"})
    original = _batch()
    service.agent_call(grant["token"], "submit_batch", original)
    return store, service, NativeReviewFacade(service, TOKEN, tmp_path / "fresh-artifacts"), original


def _node(snapshot: dict, external_id: str) -> dict:
    return next(item for item in snapshot["graph"]["nodes"] if item["external_interface_id"] == external_id)


def _receipt(root: Path, receipt_id: str) -> dict:
    paths = list((root / "desktop-review" / "exact-reviews").glob(f"*/receipt-{receipt_id}.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8-sig"))


def _correct_graph(facade: NativeReviewFacade, prefix: str) -> dict:
    created = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
    edge, target = created["graph"]["edges"][0], _node(created, "state-c")
    stale = facade.apply_graph_edit(
        created["logical_workflow_id"], 1, created["content_sha256"],
        {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target["node_id"]},
        f"{prefix}-retarget",
    )
    return facade.apply_graph_edit(
        stale["logical_workflow_id"], 2, stale["content_sha256"],
        {"type": "update_edge_semantics", "edge_id": edge["edge_id"],
         "expected_result": "C result visible", "stop_condition": "C result absent",
         "prerequisites": ["A visible"], "relationship_kinds": {"rel-open": "opens corrected C"}},
        f"{prefix}-semantics",
    )


def test_graph_backed_review_compiles_corrected_c_after_restart_without_mutating_sources(tmp_path: Path) -> None:
    store, service, facade, original = _runtime(tmp_path)
    original_batch = deepcopy(service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"])
    created = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
    original_path = tmp_path / "fresh-artifacts" / created["source_refs"]["original_batch_path"]
    screenshot_path = tmp_path / "fresh-artifacts" / created["source_refs"]["screenshots"][0]["path"]
    original_file_bytes, screenshot_bytes = original_path.read_bytes(), screenshot_path.read_bytes()
    r1_path = tmp_path / "fresh-artifacts" / "desktop-review" / "graph-revisions" / created["logical_workflow_id"] / "revisions" / f"{created['content_sha256']}.json"
    r1_bytes = r1_path.read_bytes()
    edge, target = created["graph"]["edges"][0], _node(created, "state-c")
    stale = facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target["node_id"]}, "fresh-restart-retarget")
    corrected = facade.apply_graph_edit(stale["logical_workflow_id"], 2, stale["content_sha256"], {"type": "update_edge_semantics", "edge_id": edge["edge_id"], "expected_result": "C result visible", "stop_condition": "C result absent", "prerequisites": ["A visible"], "relationship_kinds": {"rel-open": "opens corrected C"}}, "fresh-restart-correction")
    graph_id, graph_sha = corrected["logical_workflow_id"], corrected["content_sha256"]
    facade.close(); store.close()

    reopened_store = AgentLinkStore(tmp_path / "fresh-inbox.json")
    reopened_service = AgentLinkService(reopened_store, TOKEN)
    reopened = NativeReviewFacade(reopened_service, TOKEN, tmp_path / "fresh-artifacts")
    try:
        prepared = reopened.prepare_graph_exact_review(graph_id, 3, graph_sha, deepcopy(BINDING), [])
        assert prepared["contract_version"] == "desktop_graph_exact_review_v1"
        assert "workspace_revision" not in prepared
        relationship_subject = next(item for item in prepared["subjects"] if item["kind"] == "relationship")
        assert relationship_subject["content"]["kind"] == "opens corrected C"
        assert reopened.prepare_graph_exact_review(graph_id, 3, graph_sha, deepcopy(BINDING), []) == prepared
        assert reopened.compile_exact_review(prepared["review_ref"], 0)["status"] == "blocked"
        confirmed = [item["subject_id"] for item in prepared["subjects"]]
        approved = reopened.record_review_decisions(prepared["review_ref"], 0, confirmed)
        reopened.close(); reopened_store.close()
        reopened_store = AgentLinkStore(tmp_path / "fresh-inbox.json")
        reopened_service = AgentLinkService(reopened_store, TOKEN)
        reopened = NativeReviewFacade(reopened_service, TOKEN, tmp_path / "fresh-artifacts")
        retained = reopened.prepare_graph_exact_review(graph_id, 3, graph_sha, deepcopy(BINDING), [])
        assert all(item["confirmed"] for item in retained["subjects"])
        assert retained["approval_revision"] == approved["approval_revision"]
        compiled = reopened.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        assert compiled["status"] == "compiled", compiled
        assert reopened.compile_exact_review(prepared["review_ref"], approved["approval_revision"]) == compiled
        receipt = _receipt(tmp_path / "fresh-artifacts", compiled["compile_receipt_id"])
        transition = receipt["asset"]["transitions"][0]
        target_state = next(item for item in receipt["asset"]["states"] if item["source_node_id"] == target["node_id"])
        assert transition["target_state_id"] == target_state["state_id"]
        assert [item["condition"] for item in transition["expected_effect"]["semantic_success_rules"]] == ["C result visible"]
        assert receipt["logical_workflow_id"] == graph_id and receipt["graph_sha256"] == graph_sha
        published = reopened.publish_exact_review(compiled["compile_receipt_id"])
        assert published["logical_workflow_id"] == graph_id
        assert published["graph_sha256"] == graph_sha
        assert published["artifact_is_authorization"] is False
        assert published["execute_binding_enabled"] is False
        assert reopened_service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"] == original_batch
        assert r1_path.read_bytes() == r1_bytes
        assert original_path.read_bytes() == original_file_bytes
        assert screenshot_path.read_bytes() == screenshot_bytes
        assert _batch() == original
    finally:
        reopened.close(); reopened_store.close()


def test_graph_prepare_rejects_unresolved_retarget_and_stale_identity(tmp_path: Path) -> None:
    store, _, facade, _ = _runtime(tmp_path)
    try:
        created = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        edge, target = created["graph"]["edges"][0], _node(created, "state-c")
        stale = facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target["node_id"]}, "fresh-unresolved-retarget")
        with pytest.raises(ExactReviewError, match="unresolved_target_semantics"):
            facade.prepare_graph_exact_review(stale["logical_workflow_id"], 2, stale["content_sha256"], deepcopy(BINDING), [])
        with pytest.raises(ExactReviewError, match="source or revision changed"):
            facade.prepare_graph_exact_review(stale["logical_workflow_id"], 1, created["content_sha256"], deepcopy(BINDING), [])
        with pytest.raises(ExactReviewError, match="source or revision changed"):
            facade.prepare_graph_exact_review(stale["logical_workflow_id"], 2, "0" * 64, deepcopy(BINDING), [])
    finally:
        facade.close(); store.close()


def test_graph_head_advance_invalidates_approval_compile_and_receipt_without_rewrite(tmp_path: Path) -> None:
    store, _, facade, _ = _runtime(tmp_path)
    try:
        corrected = _correct_graph(facade, "fresh-stale-head")
        prepared = facade.prepare_graph_exact_review(
            corrected["logical_workflow_id"], 3, corrected["content_sha256"], deepcopy(BINDING), [],
        )
        ids = [item["subject_id"] for item in prepared["subjects"]]
        approved = facade.record_review_decisions(prepared["review_ref"], 0, ids)
        compiled = facade.compile_exact_review(prepared["review_ref"], 1)
        receipt_path = next((tmp_path / "fresh-artifacts" / "desktop-review" / "exact-reviews").glob(f"*/receipt-{compiled['compile_receipt_id']}.json"))
        receipt_bytes = receipt_path.read_bytes()
        advanced = facade.apply_graph_edit(
            corrected["logical_workflow_id"], 3, corrected["content_sha256"],
            {"type": "update_node_meaning", "node_id": _node(corrected, "state-a")["node_id"], "meaning": "Advanced A"},
            "fresh-advance-after-compile",
        )
        assert advanced["revision"] == 4
        for operation in (
            lambda: facade.record_review_decisions(prepared["review_ref"], approved["approval_revision"], ids),
            lambda: facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"]),
            lambda: facade.publish_exact_review(compiled["compile_receipt_id"]),
        ):
            with pytest.raises(ExactReviewError, match="source or revision changed"):
                operation()
        assert receipt_path.read_bytes() == receipt_bytes
    finally:
        facade.close(); store.close()


def test_unedited_graph_control_and_staging_tamper_refusal(tmp_path: Path) -> None:
    store, service, facade, _ = _runtime(tmp_path)
    try:
        original_batch = deepcopy(service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"])
        created = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        prepared = facade.prepare_graph_exact_review(
            created["logical_workflow_id"], 1, created["content_sha256"], deepcopy(BINDING), [],
        )
        assert prepared["status"] == "prepared" and prepared["graph_revision"] == 1
        approved = facade.record_review_decisions(
            prepared["review_ref"], 0, [item["subject_id"] for item in prepared["subjects"]],
        )
        compiled = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        receipt = _receipt(tmp_path / "fresh-artifacts", compiled["compile_receipt_id"])
        target_state = next(
            item for item in receipt["asset"]["states"]
            if item["source_node_id"] == _node(created, "state-b")["node_id"]
        )
        assert receipt["asset"]["transitions"][0]["target_state_id"] == target_state["state_id"]

        tamper_binding = {**deepcopy(BINDING), "display_name": "Fresh Tamper Editor"}
        tamper_prepared = facade.prepare_graph_exact_review(
            created["logical_workflow_id"], 1, created["content_sha256"], tamper_binding, [],
        )
        current_path = next(
            path for path in (tmp_path / "fresh-artifacts" / "desktop-review" / "exact-reviews").glob("*/current.json")
            if json.loads(path.read_text(encoding="utf-8-sig"))["review_ref"] == tamper_prepared["review_ref"]
        )
        current = json.loads(current_path.read_text(encoding="utf-8-sig"))
        staged_path = tmp_path / "fresh-artifacts" / current["staging_path"]
        staged = json.loads(staged_path.read_text(encoding="utf-8-sig"))
        staged["workflow"]["display_name"] = "tampered sealed graph staging"
        staged_path.write_text(json.dumps(staged, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        with pytest.raises(ExactReviewError, match="staging dependencies changed"):
            facade.record_review_decisions(tamper_prepared["review_ref"], 0, [])
        assert service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"] == original_batch
        with pytest.raises(ExactReviewError, match="could not be loaded"):
            facade.prepare_graph_exact_review("workflow-" + "f" * 64, 1, "0" * 64, deepcopy(BINDING), [])
    finally:
        facade.close(); store.close()


def test_graph_receipt_source_identity_tamper_is_rejected(tmp_path: Path) -> None:
    store, _, facade, _ = _runtime(tmp_path)
    try:
        corrected = _correct_graph(facade, "fresh-receipt-tamper")
        prepared = facade.prepare_graph_exact_review(
            corrected["logical_workflow_id"], 3, corrected["content_sha256"], deepcopy(BINDING), [],
        )
        approved = facade.record_review_decisions(
            prepared["review_ref"], 0, [item["subject_id"] for item in prepared["subjects"]],
        )
        compiled = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        receipt_path = next((tmp_path / "fresh-artifacts" / "desktop-review" / "exact-reviews").glob(f"*/receipt-{compiled['compile_receipt_id']}.json"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
        receipt["graph_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        with pytest.raises(ExactReviewError, match="graph source changed"):
            facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
    finally:
        facade.close(); store.close()
