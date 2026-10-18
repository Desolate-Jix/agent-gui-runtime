from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO

from PIL import Image
import pytest

from app.agent_link.contracts import validate_batch
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.external_mapping import ExternalMappingError, build_external_workflow_review
from app.desktop_review.workspace import NativeReviewFacade


def _raw_batch() -> dict:
    image = Image.new("RGB", (96, 64), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "fresh-graph-projection",
        "batch_id": "fresh-graph-projection",
        "title": "中文流程",
        "learning_outcome": "completed",
        "screenshots": [{
            "screenshot_id": "capture",
            "png_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        }],
        "interfaces": [
            {"interface_id": "source", "screenshot_id": "capture",
             "meaning": "起始界面", "recognition_text": "Source",
             "regions": [{"region_id": "open-control", "bbox": [2, 3, 20, 12],
                          "name": "打开", "meaning": "进入目标界面"}]},
            {"interface_id": "target", "screenshot_id": "capture",
             "meaning": "目标界面", "recognition_text": "Target", "regions": []},
        ],
        "relationships": [
            {"relationship_id": "second", "from_interface_id": "source",
             "to_interface_id": "target", "kind": "第二条中文关系"},
            {"relationship_id": "first", "from_interface_id": "source",
             "to_interface_id": "target", "kind": "第一条中文关系"},
        ],
        "steps": [{
            "step_id": "open-step", "action_type": "open_detail",
            "target_region_id": "open-control",
            "start_state": "source", "arrival_state": "target",
            "prerequisites": [], "expected_result": "目标界面可见", "stop_condition": "目标不符则停止",
        }],
        "issues": [],
    }


def _review(**kwargs) -> dict:
    return build_external_workflow_review(
        batch=validate_batch(_raw_batch()), task_id="fresh-task",
        source_ref="b" * 64, revision=1, **kwargs,
    )


def test_explicit_relationship_projection_preserves_chinese_kind():
    edge = _review(step_relationships={"open-step": ["first"]})["edges"][0]
    assert edge["external_relationships"] == [{
        "relationship_id": "first",
        "from_interface_id": "source",
        "to_interface_id": "target",
        "kind": "第一条中文关系",
    }]
    assert edge["execute_binding_enabled"] is False


def test_multiple_relationships_are_sorted_and_deep_copied():
    source = validate_batch(_raw_batch())
    result = build_external_workflow_review(
        batch=source, task_id="fresh-task", source_ref="b" * 64, revision=1,
        step_relationships={"open-step": ["second", "first"]},
    )
    relations = result["edges"][0]["external_relationships"]
    assert [item["relationship_id"] for item in relations] == ["first", "second"]
    relations[0]["kind"] = "changed"
    assert source["relationships"][1]["kind"] == "第一条中文关系"


def test_without_mapping_does_not_auto_bind_parallel_relations():
    assert "external_relationships" not in _review()["edges"][0]


@pytest.mark.parametrize("mapping", [
    {"unknown": ["first"]},
    {"open-step": "first"},
    {"open-step": ["first", "first"]},
    {"open-step": ["missing"]},
])
def test_malformed_bindings_reject(mapping):
    with pytest.raises(ExternalMappingError):
        _review(step_relationships=mapping)


def test_endpoint_mismatch_rejects():
    source = validate_batch(_raw_batch())
    source["relationships"][0]["to_interface_id"] = "source"
    with pytest.raises(ExternalMappingError, match="endpoints differ"):
        build_external_workflow_review(
            batch=source, task_id="fresh-task", source_ref="b" * 64, revision=1,
            step_relationships={"open-step": ["second"]},
        )


def test_real_saved_review_preparation_binds_edge_subject(tmp_path):
    reviewer_token = "fresh-graph-reviewer-token"
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, reviewer_token)
    facade = NativeReviewFacade(service, reviewer_token, tmp_path / "review")
    try:
        grant = service.reviewer_call(reviewer_token, "create_connection", {
            "task_id": "fresh-task", "agent_name": "fresh-contract-client",
        })
        service.agent_call(grant["token"], "submit_batch", _raw_batch())
        loaded = facade.load_batch("fresh-task", "fresh-graph-projection")
        saved = facade.save_revision(
            "fresh-task", "fresh-graph-projection", 0, loaded["batch"],
        )
        prepared = facade.prepare_exact_review(
            "fresh-task", "fresh-graph-projection", saved["revision"],
            {"kind": "native", "display_name": "Notepad",
             "executable_identity": "notepad.exe", "product_name": "Notepad"},
            step_relationships={"open-step": ["first"]},
        )
        edges = [item for item in prepared["subjects"] if item["kind"] == "edge"]
        assert len(edges) == 1
        assert edges[0]["content"]["external_relationships"][0]["relationship_id"] == "first"
        assert edges[0]["content"]["external_relationships"][0]["kind"] == "第一条中文关系"
        assert not any(item["confirmed"] for item in prepared["subjects"])
    finally:
        facade.close()
        store.close()


def test_fresh_three_state_graph_keeps_parallel_return_self_and_unknown_edges():
    raw = _raw_batch()
    raw["interfaces"][1]["regions"] = [{"region_id": "target-control", "bbox": [3, 4, 20, 12],
                                          "name": "目标控件", "meaning": "测试操作范围"}]
    raw["interfaces"].append({"interface_id": "third", "screenshot_id": "capture",
                              "meaning": "结果待确定的界面", "regions": []})
    second = deepcopy(raw["steps"][0])
    second.update(step_id="alternate-open", action_type="open_link")
    raw["steps"].append(second)
    for step_id, start, arrival, action, result in (
        ("return", "target", "source", "back", "返回起始界面"),
        ("same-surface", "target", "target", "wait", "仍在当前界面"),
        ("unknown-result", "target", "third", "unresolved_transition", "未验证结果，不能视为成功"),
    ):
        raw["steps"].append({
            "step_id": step_id, "start_state": start, "arrival_state": arrival,
            "action_type": action, "target_region_id": "target-control", "prerequisites": [],
            "expected_result": result, "stop_condition": "证据不符就停止",
        })
        raw["relationships"].append({
            "relationship_id": step_id, "from_interface_id": start,
            "to_interface_id": arrival, "kind": result,
        })
    batch = validate_batch(raw)
    before = deepcopy(batch)
    graph = build_external_workflow_review(
        batch=batch, task_id="fresh-three-state", source_ref="a" * 64, revision=1,
        step_relationships={"open-step": ["first"], "alternate-open": ["second"],
                            "return": ["return"], "same-surface": ["same-surface"],
                            "unknown-result": ["unknown-result"]},
    )
    edges = {edge["external_step_id"]: edge for edge in graph["edges"]}
    assert len(graph["nodes"]) == 3 and len(edges) == 5
    assert len({edge["edge_id"] for edge in edges.values()}) == 5
    assert edges["open-step"]["source_node_id"] == edges["alternate-open"]["source_node_id"]
    assert edges["open-step"]["target_node_id"] == edges["alternate-open"]["target_node_id"]
    assert edges["open-step"]["external_relationships"] != edges["alternate-open"]["external_relationships"]
    assert edges["return"]["target_node_id"] == edges["open-step"]["source_node_id"]
    assert edges["same-surface"]["source_node_id"] == edges["same-surface"]["target_node_id"]
    assert edges["unknown-result"]["action_type"] == "unknown_action"
    assert edges["unknown-result"]["success_conditions"] == ["未验证结果，不能视为成功"]
    assert all(edge["reviewed_by_human"] is False and edge["execute_binding_enabled"] is False
               for edge in edges.values())
    assert batch == before
