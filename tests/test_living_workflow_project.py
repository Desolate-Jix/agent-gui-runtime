from __future__ import annotations

from copy import deepcopy

import pytest

from app.desktop_review.workspace import DesktopReviewError
from test_formal_graph_exact_review import BATCH, TASK, _runtime


def _editorial_edge(node_id: str, region_id: str | None) -> dict:
    return {
        "edge_id": "project-edge-1",
        "source_node_id": node_id,
        "target_node_id": node_id,
        "action_type": "open_detail",
        "target_region_id": region_id,
        "expected_result": "Synthetic visible result",
        "condition": "Synthetic editorial condition",
    }


def test_living_project_overlay_keeps_source_graph_unchanged_and_snapshot_is_fixed(tmp_path):
    from app.desktop_review.workflow_project import WorkflowProjectService, validate_project_view

    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        source = facade.create_workflow_graph("Synthetic project source", TASK)
        source = facade.attach_interface_to_workflow(
            source["logical_workflow_id"], content["interface_id"], content["version_id"],
            source["revision"], source["content_sha256"], "project-source-attach",
        )
        service = WorkflowProjectService(facade)
        initial = service.load(source["logical_workflow_id"])
        node = initial["graph"]["nodes"][0]
        saved = service.save(
            source["logical_workflow_id"], initial["content_sha256"],
            {"title": "Living project title", "edges": [_editorial_edge(node["node_id"], node["regions"][0]["region_id"])]},
            "project-overlay-v1",
        )
        assert saved["contract_version"] == "workflow_project_view_v1"
        assert saved["revision"] == 1 and saved["graph"]["workflow"]["goal"] == "Living project title"
        assert saved["graph"]["edges"][0]["editorial"] is True
        assert service.list_projects()[0]["title"] == "Living project title"
        assert facade.load_graph_revision(source["logical_workflow_id"])["graph"]["edges"] == []
        fixed = service.load_snapshot(saved["snapshot_id"])
        assert fixed["content_sha256"] == saved["content_sha256"]
        assert validate_project_view(fixed) == fixed
        latest_interface = facade.save_interface_content(
            content["interface_id"], content["revision"], content["content_sha256"], {"regions": []}, "project-remove-region",
        )
        latest = service.load(source["logical_workflow_id"])
        assert latest["snapshot_id"] is None
        assert latest["graph"]["edges"][0]["edge_id"] == "project-edge-1"
        assert "target_region_missing" in latest["warnings"]
        assert service.load_snapshot(saved["snapshot_id"])["graph"]["nodes"][0]["regions"]
        memory = service.memory(TASK, source["logical_workflow_id"])
        assert memory["snapshot_id"] is not None
        assert service.load_snapshot(memory["snapshot_id"])["content_sha256"] == memory["content_sha256"]
        assert "image_path" not in str(memory)
        assert latest_interface["revision"] == 2
    finally:
        facade.close()
        store.close()


def test_living_project_rejects_stale_or_invalid_editorial_endpoints_and_retries(tmp_path):
    from app.desktop_review.workflow_project import WorkflowProjectService

    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        source = facade.create_workflow_graph("Synthetic project validation", TASK)
        source = facade.attach_interface_to_workflow(
            source["logical_workflow_id"], content["interface_id"], content["version_id"],
            source["revision"], source["content_sha256"], "project-validation-attach",
        )
        service = WorkflowProjectService(facade)
        initial = service.load(source["logical_workflow_id"])
        node = initial["graph"]["nodes"][0]
        valid = {"title": "Validation title", "edges": [_editorial_edge(node["node_id"], node["regions"][0]["region_id"])]}
        saved = service.save(source["logical_workflow_id"], initial["content_sha256"], valid, "project-idempotent")
        assert service.save(source["logical_workflow_id"], initial["content_sha256"], valid, "project-idempotent") == saved
        second = service.save(
            source["logical_workflow_id"], saved["content_sha256"],
            {"title": "Second save", "edges": valid["edges"]}, "project-second-save",
        )
        assert second["revision"] == 2 and second["graph"]["workflow"]["goal"] == "Second save"
        with pytest.raises(DesktopReviewError, match="idempotency_conflict"):
            service.save(source["logical_workflow_id"], initial["content_sha256"], {"title": "other"}, "project-idempotent")
        with pytest.raises(DesktopReviewError, match="stale"):
            service.save(source["logical_workflow_id"], initial["content_sha256"], valid, "project-stale")
        bad = deepcopy(valid)
        bad["edges"][0]["target_region_id"] = "missing-region"
        current = service.load(source["logical_workflow_id"])
        with pytest.raises(DesktopReviewError, match="target_region"):
            service.save(source["logical_workflow_id"], current["content_sha256"], bad, "project-bad-target")
        no_target = deepcopy(valid)
        no_target["edges"][0]["action_type"] = "observe"
        no_target["edges"][0]["target_region_id"] = None
        saved_without_target = service.save(
            source["logical_workflow_id"], current["content_sha256"], no_target, "project-no-target",
        )
        assert "target_region_missing" not in saved_without_target["warnings"]
    finally:
        facade.close()
        store.close()


def test_living_project_memory_captures_a_fixed_initial_view_without_an_overlay_head(tmp_path):
    from app.desktop_review.workflow_project import WorkflowProjectService

    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        source = facade.create_workflow_graph("Synthetic project memory", TASK)
        source = facade.attach_interface_to_workflow(
            source["logical_workflow_id"], content["interface_id"], content["version_id"],
            source["revision"], source["content_sha256"], "project-memory-attach",
        )
        service = WorkflowProjectService(facade)
        memory = service.memory(TASK, source["logical_workflow_id"])
        assert memory["revision"] == 0 and memory["snapshot_id"]
        original = service.load_snapshot(memory["snapshot_id"])
        facade.save_interface_content(
            content["interface_id"], content["revision"], content["content_sha256"],
            {"meaning": "Changed synthetic interface"}, "project-memory-interface-change",
        )
        assert service.load(source["logical_workflow_id"])["graph"]["nodes"][0]["display_name"] == "Changed synthetic interface"
        assert service.load_snapshot(memory["snapshot_id"])["graph"]["nodes"][0]["display_name"] == original["graph"]["nodes"][0]["display_name"]
        other = facade.create_workflow_graph("Synthetic project memory other", TASK)
        other = facade.attach_interface_to_workflow(
            other["logical_workflow_id"], content["interface_id"], content["version_id"],
            other["revision"], other["content_sha256"], "project-memory-other-attach",
        )
        before = service._index()
        with pytest.raises(DesktopReviewError, match="memory_not_found"):
            service.memory("wrong-task", other["logical_workflow_id"])
        assert service._index() == before
        with pytest.raises(DesktopReviewError, match="memory_not_found"):
            service.memory(TASK, other["logical_workflow_id"], memory["snapshot_id"])
    finally:
        facade.close()
        store.close()


def test_living_project_keeps_legacy_graphs_read_only(tmp_path):
    from app.desktop_review.workflow_project import WorkflowProjectService

    store, _, facade, _ = _runtime(tmp_path)
    try:
        source = facade.create_workflow_graph("Synthetic legacy project", TASK)
        service = WorkflowProjectService(facade)
        loaded = service.load(source["logical_workflow_id"])
        with pytest.raises(DesktopReviewError, match="legacy_read_only"):
            service.save(source["logical_workflow_id"], loaded["content_sha256"], {"title": "No content reference"}, "project-legacy-save")
    finally:
        facade.close()
        store.close()


def test_living_project_title_only_keeps_editorial_edges_and_removed_source_edges_removed(tmp_path):
    from app.desktop_review.workflow_project import WorkflowProjectService

    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        source = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        source = facade.attach_interface_to_workflow(
            source["logical_workflow_id"], content["interface_id"], content["version_id"],
            source["revision"], source["content_sha256"], "project-source-edge-attach",
        )
        service = WorkflowProjectService(facade)
        initial = service.load(source["logical_workflow_id"])
        original = initial["graph"]["edges"][0]
        preserved_source = {
            "edge_id": original["edge_id"],
            "source_node_id": original["source_node_id"],
            "target_node_id": original["target_node_id"],
            "action_type": original["action_type"],
            "target_region_id": original["target_region_id"],
            "expected_result": original.get("expected_result", ""),
            "condition": original.get("condition", original.get("stop_condition", "")),
        }
        interface_node = next(node for node in initial["graph"]["nodes"] if "interface_reference" in node)
        editorial = _editorial_edge(interface_node["node_id"], interface_node["regions"][0]["region_id"])
        first = service.save(
            source["logical_workflow_id"], initial["content_sha256"],
            {"title": "Source and editorial", "edges": [preserved_source, editorial]}, "project-source-edge-first",
        )
        title_only = service.save(
            source["logical_workflow_id"], first["content_sha256"], {"title": "Title only"}, "project-source-edge-title",
        )
        assert {edge["edge_id"] for edge in title_only["graph"]["edges"]} == {original["edge_id"], editorial["edge_id"]}
        removed = service.save(
            source["logical_workflow_id"], title_only["content_sha256"],
            {"title": "Remove source", "edges": [editorial]}, "project-source-edge-remove",
        )
        assert [edge["edge_id"] for edge in removed["graph"]["edges"]] == [editorial["edge_id"]]
        after_title_only = service.save(
            source["logical_workflow_id"], removed["content_sha256"], {"title": "Still removed"}, "project-source-edge-still-removed",
        )
        assert [edge["edge_id"] for edge in after_title_only["graph"]["edges"]] == [editorial["edge_id"]]
        assert facade.load_graph_revision(source["logical_workflow_id"])["graph"]["edges"][0]["edge_id"] == original["edge_id"]
    finally:
        facade.close()
        store.close()
