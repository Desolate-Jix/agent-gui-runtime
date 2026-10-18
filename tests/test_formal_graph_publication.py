from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent import reviewed_workflow_asset as asset_module
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.desktop_review.exact_review import ExactReviewError
from test_formal_graph_exact_review import (
    BATCH, BINDING, TASK, TOKEN, _batch, _correct_graph, _node, _runtime,
)


def _review_compile(facade, graph: dict, binding: dict | None = None) -> tuple[dict, dict, dict]:
    prepared = facade.prepare_graph_exact_review(
        graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
        deepcopy(binding or BINDING), [],
    )
    approved = facade.record_review_decisions(
        prepared["review_ref"], prepared["approval_revision"],
        [item["subject_id"] for item in prepared["subjects"]],
    )
    compiled = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
    assert compiled["status"] == "compiled"
    return prepared, approved, compiled


def _submit_other(service, facade, suffix: str) -> dict:
    task_id, batch_id = f"fresh-publication-{suffix}-task", f"fresh-publication-{suffix}-batch"
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": task_id, "agent_name": f"agent-{suffix}"})
    batch = _batch()
    batch.update(batch_id=batch_id, idempotency_key=f"submit-{suffix}", title=f"Fresh {suffix} graph")
    service.agent_call(grant["token"], "submit_batch", batch)
    return facade.create_graph_revision(task_id, batch_id, 0, {"open-result": ["rel-open"]})


def _target_node_id(publication: dict) -> str:
    transition = publication["asset"]["transitions"][0]
    state = next(item for item in publication["asset"]["states"] if item["state_id"] == transition["target_state_id"])
    return state["source_node_id"]


def _registry_state(root: Path) -> tuple[bool, bytes | None, tuple[str, ...]]:
    store = ReviewedWorkflowAssetStore(project_root=root)
    path = store.registry_path
    return path.exists(), path.read_bytes() if path.exists() else None, tuple(sorted(item.name for item in store.objects_root.glob("*.json")))


def _receipt_paths(root: Path, receipt_id: str) -> tuple[Path, Path]:
    receipt_path = next((root / "desktop-review" / "exact-reviews").glob(f"*/receipt-{receipt_id}.json"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    return receipt_path, root / receipt["final_path"]


def test_graph_compile_receipt_publishes_logical_version(tmp_path: Path) -> None:
    store, _, facade, _ = _runtime(tmp_path)
    try:
        graph = _correct_graph(facade, "fresh-publication-red")
        prepared = facade.prepare_graph_exact_review(
            graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            deepcopy(BINDING), [],
        )
        approved = facade.record_review_decisions(
            prepared["review_ref"], 0,
            [item["subject_id"] for item in prepared["subjects"]],
        )
        compiled = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        published = facade.publish_exact_review(compiled["compile_receipt_id"])
        assert published["logical_workflow_id"] == graph["logical_workflow_id"]
        assert published["graph_revision"] == graph["revision"]
        assert published["graph_sha256"] == graph["content_sha256"]
        assert published["current"] is True
        assert published["artifact_is_authorization"] is False
        assert published["execute_binding_enabled"] is False
        loaded = ReviewedWorkflowAssetStore(project_root=tmp_path / "fresh-artifacts").load_workflow_version(
            graph["logical_workflow_id"], published["version_id"],
        )
        assert loaded["asset"] == published["asset"]
    finally:
        facade.close(); store.close()


def test_x_b_to_c_versions_and_independent_y_survive_restart(tmp_path: Path) -> None:
    inbox, service, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        x1_graph = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        _, _, x1_compiled = _review_compile(facade, x1_graph)
        x1 = facade.publish_exact_review(x1_compiled["compile_receipt_id"])
        assert _target_node_id(x1) == _node(x1_graph, "state-b")["node_id"]

        y_graph = _submit_other(service, facade, "y")
        _, _, y_compiled = _review_compile(
            facade, y_graph, {**BINDING, "display_name": "Fresh Y Editor"},
        )
        y1 = facade.publish_exact_review(y_compiled["compile_receipt_id"])

        edge, c_node = x1_graph["graph"]["edges"][0], _node(x1_graph, "state-c")
        retargeted = facade.apply_graph_edit(
            x1_graph["logical_workflow_id"], 1, x1_graph["content_sha256"],
            {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": c_node["node_id"]},
            "fresh-x-retarget-c",
        )
        corrected = facade.apply_graph_edit(
            retargeted["logical_workflow_id"], 2, retargeted["content_sha256"],
            {"type": "update_edge_semantics", "edge_id": edge["edge_id"],
             "expected_result": "Fresh C visible", "stop_condition": "Fresh C absent",
             "prerequisites": ["Fresh A visible"], "relationship_kinds": {"rel-open": "opens fresh C"}},
            "fresh-x-correct-semantics",
        )
        _, _, x2_compiled = _review_compile(facade, corrected)
        x2 = facade.publish_exact_review(x2_compiled["compile_receipt_id"])
        assert _target_node_id(x2) == c_node["node_id"]
        stable = _registry_state(root)
        with pytest.raises(ExactReviewError, match="source or revision changed"):
            facade.publish_exact_review(x1_compiled["compile_receipt_id"])
        assert _registry_state(root) == stable
        x_id, y_id = corrected["logical_workflow_id"], y_graph["logical_workflow_id"]
    finally:
        facade.close(); inbox.close()

    reopened = ReviewedWorkflowAssetStore(project_root=root)
    assert reopened.load_workflow_version(x_id)["version_id"] == x2["version_id"]
    assert reopened.load_workflow_version(y_id)["version_id"] == y1["version_id"]
    old = reopened.load_workflow_version(x_id, x1["version_id"])
    assert old["status"] == "superseded"
    assert _target_node_id(old) == _node(x1_graph, "state-b")["node_id"]
    assert _target_node_id(reopened.load_workflow_version(x_id)) == c_node["node_id"]
    assert old["artifact_is_authorization"] is False and old["execute_binding_enabled"] is False


def test_stale_registry_receipt_requires_explicit_recompile_and_duplicate_is_noop(tmp_path: Path) -> None:
    inbox, service, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        x_graph = _correct_graph(facade, "fresh-cas-x")
        x_prepared, x_approved, x_compiled = _review_compile(facade, x_graph)
        old_receipt_id = x_compiled["compile_receipt_id"]
        y_graph = _submit_other(service, facade, "cas-y")
        _, _, y_compiled = _review_compile(
            facade, y_graph, {**BINDING, "display_name": "Fresh CAS Y"},
        )
        y = facade.publish_exact_review(y_compiled["compile_receipt_id"])
        before = _registry_state(root)
        with pytest.raises(ExactReviewError, match="registry revision mismatch"):
            facade.publish_exact_review(old_receipt_id)
        assert _registry_state(root) == before

        refreshed = facade.compile_exact_review(x_prepared["review_ref"], x_approved["approval_revision"])
        assert refreshed["compile_receipt_id"] != old_receipt_id
        with pytest.raises(ExactReviewError, match="compile receipt is stale"):
            facade.publish_exact_review(old_receipt_id)
        x = facade.publish_exact_review(refreshed["compile_receipt_id"])
        assert ReviewedWorkflowAssetStore(project_root=root).load_workflow_version(y_graph["logical_workflow_id"])["version_id"] == y["version_id"]
        stable = _registry_state(root)
        retried = facade.publish_exact_review(refreshed["compile_receipt_id"])
        assert retried["version_id"] == x["version_id"] and retried["current"] is True
        assert _registry_state(root) == stable
    finally:
        facade.close(); inbox.close()


def test_exact_duplicate_older_version_does_not_roll_back_current_pointer(tmp_path: Path) -> None:
    inbox, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        graph = _correct_graph(facade, "fresh-duplicate-order")
        _, _, first_compiled = _review_compile(facade, graph)
        first = facade.publish_exact_review(first_compiled["compile_receipt_id"])
        _, _, second_compiled = _review_compile(
            facade, graph, {**BINDING, "display_name": "Fresh alternate reviewed binding"},
        )
        second = facade.publish_exact_review(second_compiled["compile_receipt_id"])
        assert second["version_id"] != first["version_id"]
        before = _registry_state(root)
        duplicate = facade.publish_exact_review(first_compiled["compile_receipt_id"])
        assert duplicate["version_id"] == first["version_id"]
        assert duplicate["status"] == "superseded" and duplicate["current"] is False
        assert _registry_state(root) == before
        assert ReviewedWorkflowAssetStore(project_root=root).load_workflow_version(graph["logical_workflow_id"])["version_id"] == second["version_id"]
    finally:
        facade.close(); inbox.close()


def test_legacy_asset_presence_cannot_prevent_graph_receipt_cas_refresh(tmp_path: Path) -> None:
    inbox, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        graph = _correct_graph(facade, "fresh-legacy-object-overlap")
        prepared, approved, compiled = _review_compile(facade, graph)
        receipt_path, _ = _receipt_paths(root, compiled["compile_receipt_id"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assets = ReviewedWorkflowAssetStore(project_root=root)
        assets.publish(receipt["asset"], expected_registry_revision=receipt["expected_registry_revision"])
        before = _registry_state(root)
        with pytest.raises(ExactReviewError, match="registry revision mismatch"):
            facade.publish_exact_review(compiled["compile_receipt_id"])
        assert _registry_state(root) == before
        refreshed = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        assert refreshed["compile_receipt_id"] != compiled["compile_receipt_id"]
        version = facade.publish_exact_review(refreshed["compile_receipt_id"])
        assert assets.load_workflow_version(graph["logical_workflow_id"])["version_id"] == version["version_id"]
    finally:
        facade.close(); inbox.close()


@pytest.mark.parametrize("mutation", ["source", "original", "prepared", "approval", "receipt", "final"])
def test_stale_or_corrupt_owner_evidence_never_mutates_registry(tmp_path: Path, mutation: str) -> None:
    inbox, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        graph = _correct_graph(facade, f"fresh-integrity-{mutation}")
        prepared, approved, compiled = _review_compile(facade, graph)
        receipt_path, final_path = _receipt_paths(root, compiled["compile_receipt_id"])
        before = _registry_state(root)
        if mutation == "source":
            facade.apply_graph_edit(
                graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
                {"type": "update_node_meaning", "node_id": _node(graph, "state-a")["node_id"], "meaning": "Changed after receipt"},
                "fresh-change-after-receipt",
            )
        elif mutation == "original":
            original_path = root / graph["source_refs"]["original_batch_path"]
            original_path.write_bytes(original_path.read_bytes() + b" ")
        elif mutation == "prepared":
            prepared_path = next((root / "desktop-review" / "exact-reviews").glob(f"*/prepared.json"))
            sealed = json.loads(prepared_path.read_text(encoding="utf-8-sig"))
            sealed["graph_sha256"] = "0" * 64
            prepared_path.write_text(json.dumps(sealed, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        elif mutation == "approval":
            facade.record_review_decisions(
                prepared["review_ref"], approved["approval_revision"],
                [item["subject_id"] for item in prepared["subjects"][:-1]],
            )
        elif mutation == "receipt":
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            receipt["graph_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        else:
            final_path.write_bytes(final_path.read_bytes() + b" ")
        with pytest.raises(ExactReviewError):
            facade.publish_exact_review(compiled["compile_receipt_id"])
        assert _registry_state(root) == before
    finally:
        facade.close(); inbox.close()


def test_unconfirmed_graph_cannot_create_or_publish_a_version(tmp_path: Path) -> None:
    inbox, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        graph = _correct_graph(facade, "fresh-unconfirmed-publication")
        prepared = facade.prepare_graph_exact_review(
            graph["logical_workflow_id"], graph["revision"], graph["content_sha256"], deepcopy(BINDING), [],
        )
        before = _registry_state(root)
        blocked = facade.compile_exact_review(prepared["review_ref"], 0)
        assert blocked["status"] == "blocked" and blocked["compile_receipt_id"] is None
        with pytest.raises(ExactReviewError, match="compile receipt id is invalid"):
            facade.publish_exact_review(blocked["compile_receipt_id"])
        assert _registry_state(root) == before
    finally:
        facade.close(); inbox.close()


def test_graph_version_registry_write_failure_is_atomic_and_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inbox, _, facade, _ = _runtime(tmp_path)
    root = tmp_path / "fresh-artifacts"
    try:
        graph = _correct_graph(facade, "fresh-write-failure")
        _, _, compiled = _review_compile(facade, graph)
        store = ReviewedWorkflowAssetStore(project_root=root)
        before = _registry_state(root)
        real_write = asset_module._atomic_write

        def fail_registry(path: Path, payload: bytes) -> None:
            if path == store.registry_path:
                raise OSError("simulated graph version registry write failure")
            real_write(path, payload)

        with monkeypatch.context() as patch:
            patch.setattr(asset_module, "_atomic_write", fail_registry)
            with pytest.raises(ExactReviewError, match="registry write failure"):
                facade.publish_exact_review(compiled["compile_receipt_id"])
        after_failure = _registry_state(root)
        assert after_failure[:2] == before[:2]
        published = facade.publish_exact_review(compiled["compile_receipt_id"])
        assert published["current"] is True
        assert ReviewedWorkflowAssetStore(project_root=root).load_workflow_version(graph["logical_workflow_id"])["version_id"] == published["version_id"]
    finally:
        facade.close(); inbox.close()
