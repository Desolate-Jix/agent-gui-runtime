from __future__ import annotations

from copy import deepcopy
import json
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api import memory as memory_api
from app.learn.agent_evidence import (
    PersistedReviewRevision,
    build_agent_evidence_context,
    build_workflow_agent_evidence,
    load_application_agent_evidence_context,
    migrate_agent_evidence_assets,
)
from app.learn.application_interface_graph import (
    build_application_interface_graph,
    save_application_interface_graph,
)
from app.learn.interface_assets import (
    build_single_interface_asset,
    save_single_interface_asset,
)
from app.learn.interface_workflow_review import (
    INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
    build_interface_node_review_revision,
    load_interface_workflow_agent_context,
    save_interface_workflow_review_candidate,
)
from app.main import app


APPLICATION = {
    "kind": "web",
    "name": "Example",
    "url": "https://example.test/items",
    "process": "msedge.exe",
}


def _asset() -> dict:
    revision_hash = "a" * 64
    return build_single_interface_asset(
        {
            "node_id": "items",
            "display_name": "Items",
            "surface_type": "list",
            "state_signature": "items-v1",
            "evidence": {
                "source_screenshot_path": "artifacts/screenshots/items.png",
                "fused_overlay_path": "artifacts/review-overlays/items.png",
            },
            "states": [{"state_id": "items", "label": "Items visible"}],
            "regions": [
                {
                    "region_id": "results",
                    "label": "Current results",
                    "bbox": {"x": 20, "y": 80, "width": 500, "height": 400},
                }
            ],
            "controls": [
                {
                    "control_id": "open_item",
                    "label": "Open current item",
                    "visible_text_anchors": ["Open"],
                    "role": "button",
                    "bbox": {"x": 40, "y": 120, "width": 200, "height": 60},
                    "agent_description": "打开 Agent 选中的当前条目",
                }
            ],
            "content_descriptors": [
                {
                    "content_id": "items_title",
                    "label": "Items",
                    "source_kind": "control",
                    "source_id": "open_item",
                    "content_behavior": "fixed_label",
                    "agent_usage": "identity_anchor",
                    "read_policy": "on_interface_match",
                    "agent_description": "用于确认当前是条目列表界面",
                },
                {
                    "content_id": "current_results",
                    "label": "Current results",
                    "source_kind": "region",
                    "source_id": "results",
                    "content_behavior": "dynamic_collection",
                    "agent_usage": "decision_signal",
                    "read_policy": "on_demand",
                    "agent_description": "需要选择条目时读取当前结果，不沿用历史值",
                },
            ],
            "action_candidates": [
                {
                    "action_template_id": "open_item",
                    "semantic_action": "open_detail",
                    "target_control_id": "open_item",
                    "agent_description": "打开当前选中的条目并检查详情界面",
                    "verification_rule_ids": ["detail_visible"],
                    "review_status": "human_approved",
                },
                {
                    "action_template_id": "submit_item",
                    "semantic_action": "final_submit",
                    "target_control_id": "open_item",
                    "agent_description": "提交最终结果",
                },
            ],
            "verification_rules": [
                {"rule_id": "detail_visible", "description": "详情标题可见"}
            ],
            "review_status": "human_approved",
            "reviewed_by_human": True,
            "reviewed_revision_hash": revision_hash,
            "current_revision_hash": revision_hash,
            "manual_revision": {
                "semantic_description": "读取最新条目并选择一个进入详情"
            },
        },
        application_identity=APPLICATION,
    )


def _persist_reviewed_workflow(tmp_path: Path) -> dict:
    asset = _asset()
    for path_text, content in (
        (asset["evidence"]["source_screenshot_path"], b"source-image-v1"),
        (asset["evidence"]["fused_overlay_path"], b"overlay-image-v1"),
    ):
        evidence_path = tmp_path / path_text
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_bytes(content)
    node_id = str(asset["interface_id"])
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": "workflow_agent_evidence",
            "goal": "Read the current items safely",
            "application_identity": deepcopy(asset["application_identity"]),
            "entry_node_id": node_id,
            "node_ids": [node_id],
            "edge_ids": [],
            "review_status": "human_approved",
        },
        "nodes": [
            {
                "node_id": node_id,
                "display_name": asset["display_name"],
                "surface_type": asset["surface_type"],
                "state_signature": asset["state_signature"],
                "agent_description": asset["review"]["manual_revision"][
                    "semantic_description"
                ],
                "evidence": deepcopy(asset["evidence"]),
                "content_descriptors": [
                    *deepcopy(asset["fixed_anchors"]),
                    *deepcopy(asset["dynamic_slots"]),
                ],
                "states": deepcopy(asset["states"]),
                "regions": deepcopy(asset["regions"]),
                "controls": deepcopy(asset["controls"]),
                "action_candidates": deepcopy(asset["action_candidates"]),
                "verification_rules": deepcopy(asset["verification_rules"]),
                "blockers": deepcopy(asset["blockers"]),
                "review_status": "human_approved",
                "reviewed_by_human": True,
                "manual_revision": deepcopy(asset["review"]["manual_revision"]),
            }
        ],
        "edges": [],
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
        },
    }
    review["nodes"][0]["human_review_confirmation"] = {
        "contract_version": INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT,
        "revision": build_interface_node_review_revision(review, node_id=node_id),
    }
    return save_interface_workflow_review_candidate(review, project_root=tmp_path)


def test_agent_evidence_is_semantic_actionable_and_geometry_free() -> None:
    context = build_agent_evidence_context(
        _asset(),
        outgoing_transitions=[
            {
                "transition_id": "items_to_detail",
                "source_interface_id": "items",
                "target_interface_id": "detail",
                "source_control_id": "open_item",
                "action_type": "open_detail",
                "display_name": "打开详情",
                "agent_description": "打开当前条目并进入详情",
                "risk_level": "low",
                "review_status": "human_approved",
                "success_conditions": ["detail interface matched"],
                "operation_goal": "Open the current item titled Atlas report",
                "requires_completed_read": "current_results",
            }
        ],
    )

    assert context["contract_version"] == "agent_evidence_context_v1"
    assert context["interface"]["responsibility"] == "读取最新条目并选择一个进入详情"
    assert context["identity_anchors"][0]["content_id"] == "items_title"
    assert context["deferred_reads"][0]["content_id"] == "current_results"
    assert context["deferred_reads"][0]["read_strategy"] == "infinite_collection"
    assert (
        context["deferred_reads"][0]["completion_policy"]
        == "budget_or_no_new_content"
    )
    assert context["available_actions"][0]["action_type"] == "open_detail"
    assert context["available_actions"][0]["target_interface_id"] == "detail"
    assert context["available_actions"][0]["source_control_id"] == "open_item"
    assert (
        context["available_actions"][0]["operation_goal"]
        == "Open the current item titled Atlas report"
    )
    assert (
        context["available_actions"][0]["requires_completed_read"]
        == "current_results"
    )
    assert context["forbidden_actions"][0]["action_type"] == "final_submit"
    semantic_control = context["semantic_controls"][0]
    assert semantic_control == {
        "control_id": "open_item",
        "semantic_name": "Open current item",
        "visible_text_anchors": ["Open"],
        "purpose": "打开 Agent 选中的当前条目",
        "role": "button",
        "allowed_actions": ["open_detail"],
        "verification_rule": {
            "rule_ids": ["detail_visible"],
            "success_conditions": ["detail interface matched"],
        },
        "risk_class": "low",
        "review_status": "needs_human_review",
        "requires_fresh_grounding": True,
    }
    assert context["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in context["readiness"]["missing_fields"]
    serialized = json.dumps(context, ensure_ascii=False)
    assert "bbox" not in serialized
    assert "click_point" not in serialized
    assert context["artifact_is_authorization"] is False
    assert context["execution_contract"]["gate_required"] is True
    assert context["projection_contract"] == {
        "projection_is_read_only": True,
        "authoritative_source": "server_persisted_canonical_workflow_revision",
        "reverse_write_forbidden": True,
        "evidence_reference_expansion_for_agent_forbidden": True,
    }


def test_agent_evidence_requires_explicit_human_approval_status() -> None:
    asset = _asset()
    asset["review"]["status"] = "human_reviewed"

    context = build_agent_evidence_context(asset)

    assert context["readiness"]["status"] == "needs_human_review"
    assert "human_approval" in context["readiness"]["missing_fields"]


def test_agent_evidence_rejects_forged_matching_revision_hashes() -> None:
    asset = _asset()
    asset["review"].update(
        {
            "status": "human_approved",
            "reviewed_by_human": True,
            "reviewed_revision_hash": "f" * 64,
            "current_revision_hash": "f" * 64,
        }
    )

    context = build_agent_evidence_context(asset)

    assert context["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in context["readiness"]["missing_fields"]
    assert context["artifact_is_authorization"] is False
    assert context["execute_binding_enabled"] is False
    assert context["execution_contract"]["final_submit_forbidden"] is True


def test_agent_evidence_rejects_label_only_and_stale_revision_projection() -> None:
    label_only = _asset()
    label_only["review"].update(
        {
            "status": "human_approved",
            "reviewed_by_human": False,
            "reviewed_revision_hash": "",
            "current_revision_hash": "",
        }
    )
    stale_revision = _asset()
    stale_revision["review"]["current_revision_hash"] = "b" * 64

    label_context = build_agent_evidence_context(label_only)
    stale_context = build_agent_evidence_context(stale_revision)

    assert label_context["readiness"]["status"] == "needs_human_review"
    assert "human_approval" in label_context["readiness"]["missing_fields"]
    assert stale_context["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in stale_context["readiness"]["missing_fields"]
    assert label_context["artifact_is_authorization"] is False
    assert stale_context["execution_contract"]["final_submit_forbidden"] is True


def test_agent_evidence_explicit_approval_still_requires_complete_semantics() -> None:
    asset = _asset()
    asset["review"]["status"] = "human_approved"
    asset["review"]["manual_revision"] = {}

    context = build_agent_evidence_context(asset)

    assert context["readiness"]["status"] == "needs_human_review"
    assert "interface_responsibility" in context["readiness"]["missing_fields"]
    assert "human_approval" not in context["readiness"]["missing_fields"]


def test_agent_evidence_accepts_reviewed_terminal_safe_stop_without_fake_action() -> None:
    asset = _asset()
    asset["controls"] = []
    asset["action_candidates"] = []
    asset["dynamic_slots"] = []
    asset["blockers"] = [
        {
            "blocker_id": "login_required",
            "reason": "login_required",
            "safe_stop_required": True,
        }
    ]
    asset["verification_rules"] = [
        {
            "rule_id": "stop_after_login_required",
            "expected_decision": "safe_stop",
        }
    ]

    context = build_agent_evidence_context(asset)

    assert context["available_actions"] == []
    assert context["readiness"]["status"] == "needs_human_review"
    assert "action_semantics" not in context["readiness"]["missing_fields"]
    assert "human_review_revision" in context["readiness"]["missing_fields"]


def test_agent_evidence_rejects_transition_needing_human_review() -> None:
    asset = _asset()
    asset["action_candidates"] = [asset["action_candidates"][1]]

    context = build_agent_evidence_context(
        asset,
        outgoing_transitions=[
            {
                "transition_id": "items_to_detail",
                "source_interface_id": "items",
                "target_interface_id": "detail",
                "source_control_id": "open_item",
                "action_type": "open_detail",
                "agent_description": "打开当前条目并进入详情",
                "review_status": "needs_human_review",
            }
        ],
    )

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["action_id"] == "items_to_detail"
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "human_approval"
    ]
    assert context["readiness"]["status"] == "needs_human_review"
    assert "action_linkage" in context["readiness"]["missing_fields"]


def test_agent_evidence_rejects_legacy_transition_approval_status() -> None:
    asset = _asset()
    asset["action_candidates"] = [asset["action_candidates"][1]]

    context = build_agent_evidence_context(
        asset,
        outgoing_transitions=[
            {
                "transition_id": "items_to_detail",
                "source_interface_id": "items",
                "target_interface_id": "detail",
                "source_control_id": "open_item",
                "action_type": "open_detail",
                "agent_description": "打开当前条目并进入详情",
                "review_status": "human_confirmed",
            }
        ],
    )

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "human_approval"
    ]


def test_agent_evidence_accepts_explicitly_approved_transition() -> None:
    asset = _asset()
    asset["action_candidates"] = [asset["action_candidates"][1]]

    context = build_agent_evidence_context(
        asset,
        outgoing_transitions=[
            {
                "transition_id": "items_to_detail",
                "source_interface_id": "items",
                "target_interface_id": "detail",
                "source_control_id": "open_item",
                "action_type": "open_detail",
                "agent_description": "打开当前条目并进入详情",
                "review_status": "human_approved",
            }
        ],
    )

    assert context["available_actions"][0]["action_id"] == "items_to_detail"
    assert context["actions_needing_review"] == []
    assert context["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in context["readiness"]["missing_fields"]


def test_agent_evidence_accepts_reviewed_open_modal_transition() -> None:
    context = build_agent_evidence_context(
        _asset(),
        outgoing_transitions=[
            {
                "transition_id": "items_to_policy_modal",
                "source_interface_id": "items",
                "target_interface_id": "policy_modal",
                "source_control_id": "open_item",
                "action_type": "open_modal",
                "display_name": "打开规则弹窗",
                "agent_description": "打开规则弹窗并读取当前规则。",
                "risk_level": "low",
                "review_status": "human_approved",
            }
        ],
    )

    assert any(
        action["action_type"] == "open_modal"
        for action in context["available_actions"]
    )
    assert not any(
        action["action_type"] == "open_modal"
        for action in context["actions_needing_review"]
    )
    assert context["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in context["readiness"]["missing_fields"]


def test_workflow_agent_evidence_preserves_groundable_operation_goal() -> None:
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {
            "application_identity": {
                "identity_key": "web:example",
                "kind": "web",
                "name": "Example",
            }
        },
        "nodes": [
            {
                "node_id": "items",
                "display_name": "Items",
                "surface_type": "list",
                "agent_description": "Select a visible item and open its details.",
                "content_descriptors": [
                    {
                        "content_id": "items_title",
                        "label": "Items",
                        "content_behavior": "fixed_label",
                        "agent_usage": "identity_anchor",
                        "read_policy": "on_interface_match",
                    }
                ],
                "controls": [
                    {
                        "control_id": "open_item",
                        "label": "Open item",
                        "purpose": "Open the selected item detail.",
                        "role": "button",
                        "bbox": {"x": 10, "y": 20, "width": 100, "height": 40},
                    }
                ],
                "action_candidates": [
                    {
                        "action_template_id": "open_item_action",
                        "semantic_action": "open_detail",
                        "target_control_id": "open_item",
                        "target_interface_id": "detail",
                        "operation_goal": "Click the button labeled Open item",
                        "click_point": {"x": 50, "y": 40},
                    }
                ],
                "review_status": "human_reviewed",
            },
            {
                "node_id": "detail",
                "display_name": "Detail",
                "surface_type": "detail",
                "agent_description": "Read the selected item details.",
                "content_descriptors": [
                    {
                        "content_id": "detail_title",
                        "label": "Detail",
                        "content_behavior": "fixed_label",
                        "agent_usage": "identity_anchor",
                        "read_policy": "on_interface_match",
                    }
                ],
                "review_status": "human_reviewed",
            },
        ],
        "edges": [
            {
                "edge_id": "items_to_detail",
                "source_node_id": "items",
                "target_node_id": "detail",
                "source_control_id": "open_item",
                "action_type": "open_detail",
                "agent_description": "Use open_detail to move from items to detail.",
                "risk_level": "low",
                "review_status": "human_approved",
            }
        ],
    }

    evidence = build_workflow_agent_evidence(review)
    items = next(
        item for item in evidence["interfaces"] if item["interface"]["interface_id"] == "items"
    )

    assert items["available_actions"][0]["operation_goal"] == (
        "Click the button labeled Open item"
    )
    assert items["available_actions"][0]["action_id"] == "items_to_detail"
    serialized = json.dumps(items, ensure_ascii=False)
    assert "click_point" not in serialized
    assert "bbox" not in serialized


def test_workflow_projects_human_reviewed_region_action() -> None:
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {"application_identity": {"identity_key": "web:seek"}},
        "nodes": [{
            "node_id": "home",
            "display_name": "Seek home",
            "agent_description": "Job cards",
            "review_status": "human_approved",
            "reviewed_by_human": True,
            "content_descriptors": [{
                "content_id": "jobs", "label": "Jobs",
                "content_behavior": "fixed_label", "agent_usage": "identity_anchor",
            }],
            "regions": [{
                "region_id": "review_region_review_box_37",
                "label": "Job card",
                "agent_description": "Open this job card detail",
                "semantic_action": "open_detail",
                "human_review": {"status": "approved"},
            }],
        }],
        "edges": [],
    }
    evidence = build_workflow_agent_evidence(review)
    actions = evidence["interfaces"][0]["available_actions"]
    assert actions[0]["action_id"] == "region_action_review_region_review_box_37"
    assert actions[0]["action_type"] == "open_detail"


def test_legacy_regions_are_visible_but_never_promoted_to_actions() -> None:
    asset = _asset()
    asset["fixed_anchors"] = []
    asset["dynamic_slots"] = []
    asset["controls"] = []
    asset["action_candidates"] = []
    asset["regions"] = [
        {
            "region_id": "uih:group:main:card_1",
            "label": "Possible card",
            "hierarchy_level": "component",
            "role": "card",
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 80},
            "review_status": "review_only",
        }
    ]
    asset["review"]["status"] = "needs_human_review"

    context = build_agent_evidence_context(
        asset,
        outgoing_transitions=[
            {
                "transition_id": "legacy_to_detail",
                "source_interface_id": "items",
                "target_interface_id": "detail",
                "source_control_id": "missing_control",
                "action_type": "open_detail",
                "agent_description": "打开详情",
                "review_status": "human_approved",
            }
        ],
    )

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "known_source_control"
    ]
    assert context["legacy_recognition_candidates"][0]["label"] == "Possible card"
    assert context["legacy_recognition_candidates"][0]["actionable"] is False
    assert context["readiness"]["status"] == "needs_human_review"
    assert "identity_anchor" in context["readiness"]["missing_fields"]
    assert "action_semantics" in context["readiness"]["missing_fields"]
    assert context["readiness"]["legacy_inferred"] is True
    assert "bbox" not in json.dumps(context, ensure_ascii=False)


def test_unknown_action_type_fails_closed_even_with_a_known_control() -> None:
    asset = _asset()
    asset["action_candidates"] = [
        {
            "action_template_id": "invented_action",
            "semantic_action": "open_something_new",
            "target_control_id": "open_item",
            "agent_description": "未知动作不能自动进入 Agent 可用动作",
            "review_status": "human_approved",
        }
    ]

    context = build_agent_evidence_context(asset)

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "supported_action_type"
    ]
    assert context["readiness"]["status"] == "needs_human_review"


def test_bbox_only_control_cannot_be_promoted_to_agent_usable_action() -> None:
    asset = _asset()
    asset["controls"] = [
        {
            "control_id": "open_item",
            "bbox": {"x": 40, "y": 120, "width": 200, "height": 60},
        }
    ]

    context = build_agent_evidence_context(asset)

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "source_control_semantic_name",
        "source_control_purpose",
    ]
    assert context["readiness"]["status"] == "needs_human_review"
    assert "control_semantics" in context["readiness"]["missing_fields"]


@pytest.mark.parametrize(
    "action_type",
    [
        "submit_application",
        "complete_application",
        "send_application",
        "confirm_purchase",
        "place_order",
    ],
)
def test_dangerous_action_aliases_remain_forbidden(action_type: str) -> None:
    asset = _asset()
    asset["action_candidates"] = [
        {
            "action_template_id": action_type,
            "semantic_action": action_type,
            "target_control_id": "open_item",
            "agent_description": "危险动作别名",
        }
    ]

    context = build_agent_evidence_context(asset)

    assert context["available_actions"] == []
    assert context["forbidden_actions"][0]["action_type"] == action_type
    assert context["forbidden_actions"][0]["blocked_reason"] == (
        "unsafe_or_final_action"
    )


def test_unknown_asset_schema_is_rejected_before_projection() -> None:
    asset = _asset()
    asset["contract_version"] = "single_interface_asset_v999"

    with pytest.raises(
        ValueError,
        match="requires a single_interface_asset_v1 asset",
    ):
        build_agent_evidence_context(asset)


def test_migration_writes_sidecar_without_mutating_source_asset(tmp_path: Path) -> None:
    result = save_single_interface_asset(_asset(), project_root=tmp_path)
    asset_path = tmp_path / result["asset_path"]
    original_bytes = asset_path.read_bytes()

    report = migrate_agent_evidence_assets(project_root=tmp_path)

    assert report["contract_version"] == "agent_evidence_migration_report_v1"
    assert report["asset_count"] == 1
    assert report["agent_usable_count"] == 0
    assert report["needs_human_review_count"] == 1
    assert asset_path.read_bytes() == original_bytes
    evidence_path = asset_path.with_name("agent_evidence.json")
    assert evidence_path.is_file()
    migrated = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert migrated["contract_version"] == "agent_evidence_context_v1"
    assert migrated["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in migrated["readiness"]["missing_fields"]
    assert migrated["artifact_is_authorization"] is False


def test_migration_requires_a_matching_server_persisted_review_revision(
    tmp_path: Path,
) -> None:
    revision = {"server_revision": "items-v1"}
    revision_hash = hashlib.sha256(
        json.dumps(
            revision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    asset = _asset()
    asset["review"]["reviewed_revision_hash"] = revision_hash
    asset["review"]["current_revision_hash"] = revision_hash
    save_single_interface_asset(asset, project_root=tmp_path)
    trusted_revision = PersistedReviewRevision(
        revision=revision,
        revision_hash=revision_hash,
        source_asset_sha256="b" * 64,
    )

    missing = migrate_agent_evidence_assets(project_root=tmp_path)
    trusted = migrate_agent_evidence_assets(
        project_root=tmp_path,
        persisted_review_revisions={"items": trusted_revision},
    )
    stale_revision = {"server_revision": "items-v0"}
    stale_revision_hash = hashlib.sha256(
        json.dumps(
            stale_revision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    stale = migrate_agent_evidence_assets(
        project_root=tmp_path,
        persisted_review_revisions={
            "items": PersistedReviewRevision(
                revision=stale_revision,
                revision_hash=stale_revision_hash,
                source_asset_sha256="b" * 64,
            )
        },
    )

    assert missing["agent_usable_count"] == 0
    assert trusted["agent_usable_count"] == 1
    assert stale["agent_usable_count"] == 0


def test_standalone_parallel_asset_cannot_become_agent_usable(
    tmp_path: Path,
) -> None:
    asset = _asset()
    save_single_interface_asset(asset, project_root=tmp_path)
    graph = build_application_interface_graph(
        application_identity=APPLICATION,
        interfaces=[asset],
        entry_interface_id="items",
        transitions=[],
    )
    save_application_interface_graph(graph, project_root=tmp_path)

    context = load_application_agent_evidence_context(
        "web:example.test",
        interface_id="items",
        project_root=tmp_path,
    )

    assert context["contract_version"] == "application_agent_evidence_context_v1"
    assert context["interface_count"] == 1
    assert context["interfaces"][0]["interface"]["interface_id"] == "items"
    assert context["interfaces"][0]["readiness"]["status"] == "needs_human_review"
    assert "human_review_revision" in context["interfaces"][0]["readiness"]["missing_fields"]
    assert context["execution_contract"]["operation_required"] is True


def test_persisted_server_canonical_revision_is_agent_usable(tmp_path: Path) -> None:
    _persist_reviewed_workflow(tmp_path)

    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
    )

    interface = context["agent_evidence_workflows"][0]["interfaces"][0]
    assert interface["readiness"]["status"] == "agent_usable"
    assert interface["readiness"]["missing_fields"] == []
    assert context["agent_ready"] is True
    assert context["artifact_is_authorization"] is False
    assert context["execute_binding_enabled"] is False
    assert interface["execution_contract"]["final_submit_forbidden"] is True


def test_same_path_changed_evidence_rejects_recomputed_matching_hashes(
    tmp_path: Path,
) -> None:
    saved = _persist_reviewed_workflow(tmp_path)
    workflow_path = Path(saved["path"])
    payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    node = payload["nodes"][0]
    evidence_path = tmp_path / node["evidence"]["source_screenshot_path"]
    evidence_path.write_bytes(b"source-image-replaced-at-the-same-path")

    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
    )

    assert context["agent_evidence_workflows"] == []
    assert context["blocked_interfaces"][0]["agent_usable"] is False
    assert context["blocked_interfaces"][0]["reason"] == (
        "human_review_revision_mismatch"
    )
    assert context["agent_ready"] is False


def test_agent_can_load_application_evidence_through_memory_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    asset = _asset()
    save_single_interface_asset(asset, project_root=tmp_path)
    save_application_interface_graph(
        build_application_interface_graph(
            application_identity=APPLICATION,
            interfaces=[asset],
            entry_interface_id="items",
            transitions=[],
        ),
        project_root=tmp_path,
    )
    monkeypatch.setattr(memory_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).get(
        "/memory/interface_assets/agent_context",
        params={
            "application_identity_key": "web:example.test",
            "interface_id": "items",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert (
        payload["data"]["interfaces"][0]["readiness"]["status"]
        == "needs_human_review"
    )
