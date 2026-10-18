"""公共 MCP 双动作图的人工审核、发布和重开复用隔离回归。"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import re

from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.desktop_review.host import DesktopReviewHost
from tests.test_formal_fresh_graph_source import REVIEWER
from tests.test_fresh_agent_public_sequence import (
    _install_public_observation_owner,
    _public_rig,
    _run_public_two_action_sequence,
)


BINDING = {
    "kind": "web",
    "display_name": "Synthetic public graph review fixture",
    "canonical_origin": "https://fresh.example",
}
_SHARED_BOUNDARY = "Synthetic fixture shared visible boundary"


def _edit(facade, snapshot, operation, idempotency_key):
    return facade.apply_graph_edit(
        snapshot["logical_workflow_id"],
        snapshot["revision"],
        snapshot["content_sha256"],
        operation,
        idempotency_key,
    )


def _identity(node, label):
    evidence = node["evidence"]
    return {
        "type": "update_node_recognition_text",
        "node_id": node["node_id"],
        "recognition_text": label,
        "bbox": [3, 4, 25, 14],
        "source_screenshot_path": evidence["source_screenshot_path"],
        "source_screenshot_sha256": evidence["source_screenshot_sha256"],
    }


def _current_with_partial_shared_anchor_evidence(asset, shared_states):
    supplied = [
        anchor
        for state in shared_states
        for anchor in state["identity_anchors"]
        if anchor["label"] == _SHARED_BOUNDARY
    ]
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": content_sha256(asset),
        "capture_id": "synthetic-fixture-shared-boundary-capture",
        "screenshot_sha256": "e" * 64,
        "viewport_size": {"width": 160, "height": 100},
        "origin": "https://fresh.example",
        # 夹具仅提交两个同文本文字锚点，不冒充完整真实场景或额外区域/控件锚点。
        "observed_anchor_evidence": [
            {
                "anchor_id": anchor["anchor_id"],
                "matched": True,
                "confidence": 0.95,
                "evidence_ref": f"synthetic-fixture:{anchor['anchor_id']}",
            }
            for anchor in supplied
        ],
    }


def test_public_two_action_graph_human_retarget_publish_reopen_and_partial_boundary_ambiguity(
    tmp_path, monkeypatch,
):
    public_owners = _install_public_observation_owner(tmp_path, monkeypatch)
    with _public_rig(tmp_path) as (host, coordinator, connection, segment, instances):
        first, second = asyncio.run(asyncio.wait_for(
            _run_public_two_action_sequence(
                host=host,
                coordinator=coordinator,
                connection=connection,
                segment=segment,
                instances=instances,
                public_owners=public_owners,
            ),
            timeout=120,
        ))
        facade = host.facade
        original = facade.load_graph_revision(first[0]["logical_workflow_id"])
        original_snapshot = deepcopy(original)
        original_source_refs = deepcopy(original["source_refs"])
        first_edge, second_edge = original["graph"]["edges"]
        original_first_after = first_edge["target_node_id"]
        second_before = second_edge["source_node_id"]
        assert original_first_after != second_before
        assert [len(instance[2].commands) for instance in instances] == [1, 1]

        # 显式模拟人工改正目标；绝不把相同标签自动视为状态合并。
        corrected = _edit(
            facade,
            original,
            {
                "type": "update_edge_target",
                "edge_id": first_edge["edge_id"],
                "target_node_id": second_before,
            },
            "simulated-human-retarget-first-edge",
        )
        retargeted = next(edge for edge in corrected["graph"]["edges"] if edge["edge_id"] == first_edge["edge_id"])
        assert retargeted["target_node_id"] == second_before
        assert retargeted["target_semantics_status"] == "stale_after_retarget"

        reviewed = corrected
        for index, edge in enumerate(reviewed["graph"]["edges"]):
            reviewed = _edit(
                facade,
                reviewed,
                {
                    "type": "update_edge_semantics",
                    "edge_id": edge["edge_id"],
                    "prerequisites": [f"Synthetic fixture action {index} is ready"],
                    "expected_result": f"Synthetic fixture action {index} completed",
                    "stop_condition": f"Synthetic fixture action {index} is unavailable",
                    "relationship_kinds": {},
                },
                f"simulated-human-semantics-{index}",
            )

        for index, node in enumerate(reviewed["graph"]["nodes"]):
            label = _SHARED_BOUNDARY if node["node_id"] in {original_first_after, second_before} else f"Synthetic fixture visible screen {index}"
            operation = _identity(node, label)
            reviewed = _edit(facade, reviewed, operation, f"simulated-human-identity-{index}")
            changed = next(item for item in reviewed["graph"]["nodes"] if item["node_id"] == node["node_id"])
            assert changed["recognition_anchor"]["source_screenshot_path"] == operation["source_screenshot_path"]
            assert changed["recognition_anchor"]["source_screenshot_sha256"] == operation["source_screenshot_sha256"]
            assert changed["recognition_anchor"]["bbox"] == [3, 4, 25, 14]

        assert facade.load_graph_revision(original["logical_workflow_id"], original["revision"]) == original_snapshot
        assert reviewed["source_refs"] == original_source_refs
        assert [len(instance[2].commands) for instance in instances] == [1, 1]
        invalid_node_ids = [
            node["node_id"] for node in reviewed["graph"]["nodes"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", node["node_id"])
            or node["node_id"].endswith(".")
        ]
        assert not invalid_node_ids, invalid_node_ids

        prepared = facade.prepare_graph_exact_review(
            reviewed["logical_workflow_id"],
            reviewed["revision"],
            reviewed["content_sha256"],
            BINDING,
            [],
        )
        confirmed = facade.record_review_decisions(
            prepared["review_ref"],
            0,
            [subject["subject_id"] for subject in prepared["subjects"]],
        )
        compiled = facade.compile_exact_review(prepared["review_ref"], confirmed["approval_revision"])
        assert compiled["status"] == "compiled", compiled
        publication = facade.publish_exact_review(compiled["compile_receipt_id"])
        assert publication["version_id"]
        assert [len(instance[2].commands) for instance in instances] == [1, 1]

        assets = ReviewedWorkflowAssetStore(project_root=facade._artifact_root)
        explicit = assets.load_workflow_version(reviewed["logical_workflow_id"], publication["version_id"])
        asset = explicit["asset"]
        assert asset == publication["asset"]
        memory = facade.get_workflow_memory(
            [reviewed["logical_workflow_id"]],
            reviewed["logical_workflow_id"],
            publication["version_id"],
        )
        assert memory["version_id"] == publication["version_id"]
        assert memory["asset_sha256"] == content_sha256(asset)

        states_by_source = {state["source_node_id"]: state for state in asset["states"]}
        first_transition = next(
            transition for transition in asset["transitions"]
            if transition["source_state_id"] == states_by_source[first_edge["source_node_id"]]["state_id"]
        )
        second_transition = next(
            transition for transition in asset["transitions"]
            if transition["source_state_id"] == states_by_source[second_before]["state_id"]
        )
        assert first_transition["target_state_id"] == second_transition["source_state_id"]
        assert original_first_after in states_by_source
        entry = next(state for state in asset["states"] if state["state_id"] == asset["entry_state_id"])
        entry_outgoing = entry["allowed_transition_ids"]
        assert isinstance(entry_outgoing, list)
        assert set(entry_outgoing) <= {transition["transition_id"] for transition in asset["transitions"]}

    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        reopened_memory = reopened.facade.get_workflow_memory(
            [reviewed["logical_workflow_id"]],
            reviewed["logical_workflow_id"],
            publication["version_id"],
        )
        assert reopened_memory == memory
        reopened_asset = ReviewedWorkflowAssetStore(project_root=tmp_path / "review").load_workflow_version(
            reviewed["logical_workflow_id"], publication["version_id"]
        )["asset"]
        assert reopened_asset == asset

        shared_states = [states_by_source[original_first_after], states_by_source[second_before]]
        current = _current_with_partial_shared_anchor_evidence(reopened_asset, shared_states)
        supplied_anchor_ids = {item["anchor_id"] for item in current["observed_anchor_evidence"]}
        expected_anchor_ids = {
            anchor["anchor_id"]
            for state in shared_states
            for anchor in state["identity_anchors"]
            if anchor["label"] == _SHARED_BOUNDARY
        }
        extra_anchor_ids = {
            anchor["anchor_id"]
            for state in shared_states
            for anchor in state["identity_anchors"]
            if anchor["label"] != _SHARED_BOUNDARY
        }
        assert len(expected_anchor_ids) == 2
        assert extra_anchor_ids
        assert supplied_anchor_ids == expected_anchor_ids
        assert supplied_anchor_ids.isdisjoint(extra_anchor_ids)
        resolution = resolve_current_state(reopened_asset, current)
        assert resolution["status"] == "blocked", resolution
        assert resolution["failure_code"] == "current_state_ambiguous"
        assert set(resolution["candidate_state_ids"]) == {state["state_id"] for state in shared_states}
    finally:
        reopened.close()
