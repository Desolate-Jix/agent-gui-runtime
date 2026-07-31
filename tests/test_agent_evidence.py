from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api import memory as memory_api
from app.learn.agent_evidence import (
    build_agent_evidence_context,
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
from app.main import app


APPLICATION = {
    "kind": "web",
    "name": "Example",
    "url": "https://example.test/items",
    "process": "msedge.exe",
}


def _asset() -> dict:
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
            "review_status": "human_reviewed",
            "manual_revision": {
                "semantic_description": "读取最新条目并选择一个进入详情"
            },
        },
        application_identity=APPLICATION,
    )


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
                "review_status": "human_confirmed",
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
    assert context["readiness"]["status"] == "agent_usable"
    serialized = json.dumps(context, ensure_ascii=False)
    assert "bbox" not in serialized
    assert "click_point" not in serialized
    assert context["artifact_is_authorization"] is False
    assert context["execution_contract"]["gate_required"] is True
    assert context["projection_contract"] == {
        "projection_is_read_only": True,
        "authoritative_source": "versioned_interface_asset_and_human_review",
        "reverse_write_forbidden": True,
        "evidence_reference_expansion_for_agent_forbidden": True,
    }


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
                "review_status": "human_confirmed",
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
    assert context["readiness"]["status"] == "agent_usable"


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
        }
    ]

    context = build_agent_evidence_context(asset)

    assert context["available_actions"] == []
    assert context["actions_needing_review"][0]["missing_fields"] == [
        "supported_action_type"
    ]
    assert context["readiness"]["status"] == "needs_human_review"


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
    assert report["agent_usable_count"] == 1
    assert asset_path.read_bytes() == original_bytes
    evidence_path = asset_path.with_name("agent_evidence.json")
    assert evidence_path.is_file()
    migrated = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert migrated["contract_version"] == "agent_evidence_context_v1"
    assert migrated["readiness"]["status"] == "agent_usable"
    assert migrated["artifact_is_authorization"] is False


def test_application_agent_context_loads_interfaces_and_reviewed_transitions(
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
    assert context["interfaces"][0]["readiness"]["status"] == "agent_usable"
    assert context["execution_contract"]["operation_required"] is True


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
    assert payload["data"]["interfaces"][0]["readiness"]["status"] == "agent_usable"
