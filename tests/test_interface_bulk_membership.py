from __future__ import annotations

from copy import deepcopy

import pytest

from app.desktop_review.workspace import DesktopReviewError
from test_formal_graph_exact_review import BATCH, TASK, TOKEN, _batch, _runtime


def _reference(value: dict) -> dict:
    return {key: value[key] for key in ("interface_id", "version_id", "content_sha256")}


def test_bulk_membership_attaches_all_selected_interfaces_in_one_revision_and_retries(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        second = facade.import_interface_content(TASK, BATCH, "state-b")
        graph = facade.create_workflow_graph("Synthetic bulk membership", TASK)
        attached = facade.attach_interfaces_to_workflow(
            graph["logical_workflow_id"], [_reference(first), _reference(second)],
            graph["revision"], graph["content_sha256"], "bulk-attach-two",
        )
        assert attached["revision"] == graph["revision"] + 1
        assert len(attached["graph"]["nodes"]) == 2
        assert attached["graph"]["edges"] == []
        assert facade.attach_interfaces_to_workflow(
            graph["logical_workflow_id"], [_reference(first), _reference(second)],
            graph["revision"], graph["content_sha256"], "bulk-attach-two",
        ) == attached
        with pytest.raises(DesktopReviewError, match="idempotency_key"):
            facade.attach_interfaces_to_workflow(
                graph["logical_workflow_id"], [_reference(first)],
                graph["revision"], graph["content_sha256"], "bulk-attach-two",
            )
        facade.save_interface_content(
            first["interface_id"], first["revision"], first["content_sha256"],
            {"meaning": "Later synthetic interface edit"}, "bulk-retry-after-interface-edit",
        )
        assert facade.attach_interfaces_to_workflow(
            graph["logical_workflow_id"], [_reference(first), _reference(second)],
            graph["revision"], graph["content_sha256"], "bulk-attach-two",
        ) == attached
        reopened = facade.load_graph_revision(graph["logical_workflow_id"])
        assert reopened["content_sha256"] == attached["content_sha256"]
    finally:
        facade.close()
        store.close()


def test_bulk_membership_refuses_non_latest_interface_before_any_graph_write(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        second = facade.import_interface_content(TASK, BATCH, "state-b")
        newer_first = facade.save_interface_content(
            first["interface_id"], first["revision"], first["content_sha256"],
            {"meaning": "Current latest synthetic interface"}, "bulk-stale-interface-newer",
        )
        graph = facade.create_workflow_graph("Synthetic stale interface", TASK)
        original = facade.load_graph_revision(graph["logical_workflow_id"])
        with pytest.raises(DesktopReviewError, match="stale_interface"):
            facade.attach_interfaces_to_workflow(
                graph["logical_workflow_id"], [_reference(first), _reference(second)],
                graph["revision"], graph["content_sha256"], "bulk-stale-interface",
            )
        assert facade.load_graph_revision(graph["logical_workflow_id"])["content_sha256"] == original["content_sha256"]
        attached = facade.attach_interfaces_to_workflow(
            graph["logical_workflow_id"], [_reference(newer_first), _reference(second)],
            graph["revision"], graph["content_sha256"], "bulk-current-interface",
        )
        assert attached["revision"] == graph["revision"] + 1
    finally:
        facade.close()
        store.close()


def test_bulk_membership_refuses_over_256_before_committing(tmp_path, monkeypatch):
    from app.desktop_review.workflow_membership import WorkflowMembershipService

    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        graph = facade.create_workflow_graph("Synthetic bulk limit", TASK)
        service = WorkflowMembershipService(facade)
        current = facade.load_graph_revision(graph["logical_workflow_id"])
        simulated = deepcopy(current)
        simulated["source_refs"]["interfaces"] = [
            {"interface_id": f"existing-{index}", "version_id": "version", "content_sha256": "0" * 64}
            for index in range(256)
        ]
        monkeypatch.setattr(service.graphs, "load", lambda *_args, **_kwargs: deepcopy(simulated))
        committed = []
        monkeypatch.setattr(service.graphs, "_write_committed", lambda snapshot: committed.append(snapshot))
        with pytest.raises(DesktopReviewError, match="limit_exceeded"):
            service.attach_interfaces_to_workflow(
                workflow_id=graph["logical_workflow_id"], interfaces=[_reference(content)],
                expected_revision=current["revision"], expected_sha256=current["content_sha256"], idempotency_key="bulk-limit",
            )
        assert committed == []
    finally:
        facade.close()
        store.close()


def test_bulk_membership_rejects_one_bad_duplicate_foreign_or_stale_item_without_partial_commit(tmp_path):
    store, service, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        second = facade.import_interface_content(TASK, BATCH, "state-b")
        foreign_grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": "other-task", "agent_name": "other-agent"})
        foreign_batch = deepcopy(_batch())
        foreign_batch["batch_id"] = "other-task-batch"
        foreign_batch["idempotency_key"] = "other-task-submit"
        service.agent_call(foreign_grant["token"], "submit_batch", foreign_batch)
        foreign = facade.import_interface_content("other-task", foreign_batch["batch_id"], "state-a")
        graph = facade.create_workflow_graph("Synthetic rejected bulk", TASK)
        original = facade.load_graph_revision(graph["logical_workflow_id"])
        bad_hash = _reference(first); bad_hash["content_sha256"] = "0" * 64
        for refs, key, message in (
            ([bad_hash, _reference(second)], "bulk-bad-hash", "identity"),
            ([_reference(first), _reference(first)], "bulk-duplicate", "duplicate"),
            ([_reference(first), _reference(foreign)], "bulk-foreign", "task"),
        ):
            with pytest.raises(DesktopReviewError, match=message):
                facade.attach_interfaces_to_workflow(
                    graph["logical_workflow_id"], refs, graph["revision"], graph["content_sha256"], key,
                )
            assert facade.load_graph_revision(graph["logical_workflow_id"])["content_sha256"] == original["content_sha256"]
        attached = facade.attach_interfaces_to_workflow(
            graph["logical_workflow_id"], [_reference(first)], graph["revision"], graph["content_sha256"], "bulk-one",
        )
        newer_first = facade.save_interface_content(
            first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "Newer first"}, "bulk-newer-first",
        )
        with pytest.raises(DesktopReviewError, match="already"):
            facade.attach_interfaces_to_workflow(
                graph["logical_workflow_id"], [_reference(newer_first)], attached["revision"], attached["content_sha256"], "bulk-other-version",
            )
        with pytest.raises(DesktopReviewError, match="stale"):
            facade.attach_interfaces_to_workflow(
                graph["logical_workflow_id"], [_reference(second)], graph["revision"], graph["content_sha256"], "bulk-stale",
            )
        assert facade.load_graph_revision(graph["logical_workflow_id"])["content_sha256"] == attached["content_sha256"]
    finally:
        facade.close()
        store.close()
