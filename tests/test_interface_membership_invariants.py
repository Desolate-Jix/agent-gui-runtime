"""独立引用必须沿用真实内容、证据和提交身份，不以列表标签代替验证。"""
from copy import deepcopy

import pytest

from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.workspace import DesktopReviewError
from test_formal_graph_exact_review import _runtime, TASK, BATCH


@pytest.fixture
def rig(tmp_path):
    store, service, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        graph = facade.create_workflow_graph("Independent references", TASK)
        yield facade, content, graph
    finally:
        facade.close()
        store.close()


def _attach(facade, content, graph, key="attach"):
    return facade.attach_interface_to_workflow(graph["logical_workflow_id"], content["interface_id"],
        content["version_id"], graph["revision"], graph["content_sha256"], key)


def test_exact_retry_survives_new_head(rig):
    facade, content, graph = rig
    first = _attach(facade, content, graph)
    assert _attach(facade, content, graph) == first


def test_reference_node_projects_real_content_and_evidence(rig):
    facade, content, graph = rig
    first = _attach(facade, content, graph)
    node = first["graph"]["nodes"][0]
    assert node["display_name"] == content["content"]["meaning"]
    assert node["regions"] == content["content"]["regions"]
    evidence = facade.load_graph_node_evidence(first["logical_workflow_id"], first["revision"],
        first["content_sha256"], node["node_id"])
    assert evidence["screenshot"]["png_bytes"].startswith(b"\x89PNG")
    assert evidence["screenshot"]["sha256"] == content["source"]["screenshot_sha256"]


def test_recomputed_outer_hash_cannot_relabel_exact_reference(rig):
    facade, content, graph = rig
    first = _attach(facade, content, graph)
    altered = deepcopy(first)
    altered["graph"]["nodes"][0]["display_name"] = "Not the referenced content"
    service = GraphRevisionService(facade)
    altered["content_sha256"] = service._content_sha(altered)
    with pytest.raises(DesktopReviewError):
        service._validate_snapshot(altered)


def test_composition_cannot_smuggle_unobserved_edges(rig):
    facade, content, graph = rig
    first = _attach(facade, content, graph)
    altered = deepcopy(first)
    node_id = first["graph"]["nodes"][0]["node_id"]
    altered["graph"]["edges"] = [{"edge_id": "invented", "source_node_id": node_id, "target_node_id": node_id}]
    service = GraphRevisionService(facade)
    altered["content_sha256"] = service._content_sha(altered)
    with pytest.raises(DesktopReviewError):
        service._validate_snapshot(altered)


def test_broken_graph_is_reported_not_hidden_from_library(rig):
    facade, content, graph = rig
    head = GraphRevisionService(facade)._head_path(graph["logical_workflow_id"])
    head.write_bytes(b"broken")
    with pytest.raises(DesktopReviewError):
        facade.list_workflow_graphs()
