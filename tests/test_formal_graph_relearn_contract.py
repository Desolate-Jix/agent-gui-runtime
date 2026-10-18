from __future__ import annotations

import pytest

from app.agent_link.contracts import AgentLinkError, validate_candidate
from app.agent_link.graph_contract import GraphContractError, apply_graph_operations, validate_graph_operations, validate_graph_scope
from app.desktop_review.workspace import NativeReviewFacade


def test_graph_relearn_facade_exposes_frozen_request_compare_and_adopt_apis() -> None:
    for name in (
        "request_graph_relearn",
        "compare_graph_relearn_candidate",
        "adopt_graph_relearn_candidate",
    ):
        assert callable(getattr(NativeReviewFacade, name, None)), name


def _graph() -> dict:
    return {
        "nodes": [{"node_id": "n1", "display_name": "旧", "agent_description": "旧", "page_details": {"screen": {"summary": "旧"}}, "regions": [{"region_id": "r1", "bbox": [1, 2, 3, 4]}], "controls": [{"region_id": "r1", "bbox": [1, 2, 3, 4]}], "action_candidates": [{"external_step_id": "s1", "expected_result": "旧结果", "stop_condition": "旧停止"}]}, {"node_id": "n2"}],
        "edges": [{"edge_id": "e1", "external_step_id": "s1", "target_node_id": "n1", "success_conditions": ["旧结果"], "failure_conditions": ["旧停止"], "preconditions": [], "external_relationships": [{"relationship_id": "rel1", "kind": "旧关系"}]}],
    }


def test_graph_operations_share_one_scoped_semantic_application_path() -> None:
    scope = {"node_ids": ["n1"], "edge_ids": ["e1"]}
    operations = [
        {"type": "update_node_meaning", "node_id": "n1", "meaning": "新含义"},
        {"type": "update_edge_semantics", "edge_id": "e1", "expected_result": "新结果", "stop_condition": "新停止", "prerequisites": ["可见"], "relationship_kinds": {"rel1": "新关系"}},
    ]
    checked = validate_graph_operations(operations, _graph(), scope)
    result = apply_graph_operations(_graph(), checked)
    assert result["nodes"][0]["page_details"]["screen"]["summary"] == "新含义"
    assert result["edges"][0]["success_conditions"] == ["新结果"]
    assert result["nodes"][0]["action_candidates"][0]["stop_condition"] == "新停止"
    assert result["edges"][0]["external_relationships"][0]["kind"] == "新关系"


def test_graph_candidate_is_discriminated_and_strict() -> None:
    candidate = {
        "contract_version": "agent_link_graph_candidate_v1", "idempotency_key": "k",
        "batch_id": "b", "issue_id": "i", "baseline_revision": 1,
        "review_baseline_sha256": "a" * 64, "logical_workflow_id": "workflow-" + "b" * 64,
        "baseline_graph_sha256": "c" * 64, "scope": {"node_ids": ["n1"], "edge_ids": []},
        "changes": [{"type": "update_node_meaning", "node_id": "n1", "meaning": "新"}],
    }
    assert validate_candidate(candidate) == candidate
    with pytest.raises(AgentLinkError):
        validate_candidate({**candidate, "authority": "approved"})


@pytest.mark.parametrize("scope", [
    {"node_ids": [], "edge_ids": []},
    {"node_ids": ["n1", "n1"], "edge_ids": []},
    {"node_ids": ["missing"], "edge_ids": []},
    {"node_ids": ["n1"], "edge_ids": [], "authority": "approved"},
])
def test_graph_scope_rejects_empty_duplicate_foreign_and_authority(scope: dict) -> None:
    with pytest.raises(GraphContractError):
        validate_graph_scope(scope, _graph())


def test_graph_operations_reject_scope_escape_duplicate_and_incomplete_semantics() -> None:
    graph = _graph()
    with pytest.raises(GraphContractError, match="outside scope"):
        validate_graph_operations([{"type": "update_node_meaning", "node_id": "n1", "meaning": "x"}], graph, {"node_ids": [], "edge_ids": ["e1"]})
    duplicate = {"type": "update_node_meaning", "node_id": "n1", "meaning": "x"}
    with pytest.raises(GraphContractError, match="conflict"):
        validate_graph_operations([duplicate, duplicate], graph, {"node_ids": ["n1"], "edge_ids": []})
    with pytest.raises(GraphContractError):
        validate_graph_operations([{"type": "update_edge_semantics", "edge_id": "e1", "expected_result": "x", "stop_condition": "y", "prerequisites": []}], graph, {"node_ids": [], "edge_ids": ["e1"]})
