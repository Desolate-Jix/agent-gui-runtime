from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.learn.application_interface_graph import (
    build_application_graph_agent_context,
    build_application_interface_graph,
    load_application_interface_graph,
    save_application_interface_graph,
    save_workflow_review_as_application_assets,
)
from app.learn.interface_assets import build_single_interface_asset


APPLICATION = {
    "kind": "web",
    "name": "Example",
    "url": "https://example.test/home",
    "process": "msedge.exe",
}


def _asset(interface_id: str, control_id: str) -> dict:
    return build_single_interface_asset(
        {
            "node_id": interface_id,
            "display_name": interface_id.replace("_", " ").title(),
            "surface_type": "content_feed",
            "state_signature": f"{interface_id}-v1",
            "evidence": {
                "source_screenshot_path": f"artifacts/screenshots/{interface_id}.png",
                "fused_overlay_path": f"artifacts/review-overlays/{interface_id}.png",
            },
            "controls": [
                {
                    "control_id": control_id,
                    "label": control_id.replace("_", " "),
                    "role": "button",
                    "bbox": {"x": 10, "y": 20, "width": 80, "height": 30},
                }
            ],
            "content_descriptors": [
                {
                    "content_id": f"{interface_id}_title",
                    "label": "Interface title",
                    "source_kind": "control",
                    "source_id": control_id,
                    "content_behavior": "fixed_label",
                    "agent_usage": "identity_anchor",
                    "read_policy": "on_interface_match",
                    "agent_description": "用于识别当前界面",
                }
            ],
            "review_status": "human_reviewed",
        },
        application_identity=APPLICATION,
    )


def test_application_graph_supports_branching_human_links() -> None:
    home = _asset("home", "open_detail")
    detail = _asset("detail", "open_apply")
    saved = _asset("saved", "open_saved_item")

    graph = build_application_interface_graph(
        application_identity=APPLICATION,
        interfaces=[home, detail, saved],
        entry_interface_id="home",
        transitions=[
            {
                "transition_id": "home_to_detail",
                "source_interface_id": "home",
                "target_interface_id": "detail",
                "source_control_id": "open_detail",
                "action_type": "open_detail",
                "display_name": "打开详情",
                "agent_description": "点击岗位卡片进入对应详情页",
                "risk_level": "low",
                "review_status": "human_confirmed",
                "success_conditions": ["detail interface matched"],
            },
            {
                "transition_id": "home_to_saved",
                "source_interface_id": "home",
                "target_interface_id": "saved",
                "source_control_id": "open_detail",
                "action_type": "click",
                "display_name": "查看收藏",
                "agent_description": "进入已收藏内容列表",
                "risk_level": "low",
                "review_status": "human_confirmed",
            },
        ],
    )

    assert graph["contract_version"] == "application_interface_graph_v1"
    assert graph["entry_interface_id"] == "home"
    assert graph["interface_ids"] == ["detail", "home", "saved"]
    assert [item["target_interface_id"] for item in graph["transitions"]] == [
        "detail",
        "saved",
    ]
    assert all(item["artifact_is_authorization"] is False for item in graph["transitions"])
    assert all(item["automatic_execution_allowed"] is False for item in graph["transitions"])


def test_application_graph_accepts_reviewed_open_modal_transition() -> None:
    home = _asset("home", "open_policy")
    policy_modal = _asset("policy_modal", "close_policy")

    graph = build_application_interface_graph(
        application_identity=APPLICATION,
        interfaces=[home, policy_modal],
        entry_interface_id="home",
        transitions=[
            {
                "transition_id": "home_to_policy_modal",
                "source_interface_id": "home",
                "target_interface_id": "policy_modal",
                "source_control_id": "open_policy",
                "action_type": "open_modal",
                "display_name": "打开规则弹窗",
                "agent_description": "打开规则弹窗并读取当前规则。",
                "risk_level": "low",
                "review_status": "human_confirmed",
            }
        ],
    )

    assert graph["transitions"][0]["action_type"] == "open_modal"


def test_application_graph_rejects_unknown_control_or_interface() -> None:
    home = _asset("home", "open_detail")
    detail = _asset("detail", "open_apply")

    with pytest.raises(ValueError, match="source control"):
        build_application_interface_graph(
            application_identity=APPLICATION,
            interfaces=[home, detail],
            entry_interface_id="home",
            transitions=[
                {
                    "transition_id": "bad",
                    "source_interface_id": "home",
                    "target_interface_id": "detail",
                    "source_control_id": "missing",
                    "action_type": "open_detail",
                    "review_status": "human_confirmed",
                }
            ],
        )


def test_graph_agent_context_includes_descriptions_but_never_authorizes_actions() -> None:
    graph = build_application_interface_graph(
        application_identity=APPLICATION,
        interfaces=[_asset("home", "open_detail"), _asset("detail", "open_apply")],
        entry_interface_id="home",
        transitions=[
            {
                "transition_id": "home_to_detail",
                "source_interface_id": "home",
                "target_interface_id": "detail",
                "source_control_id": "open_detail",
                "action_type": "open_detail",
                "display_name": "打开详情",
                "agent_description": "点击当前内容卡片并验证详情标题出现",
                "risk_level": "low",
                "review_status": "human_confirmed",
            }
        ],
    )

    context = build_application_graph_agent_context(
        graph,
        interface_id="home",
    )

    assert context["current_interface"]["interface_id"] == "home"
    assert context["outgoing_transitions"][0]["agent_description"].startswith("点击当前")
    assert context["outgoing_transitions"][0]["requires_fresh_grounding"] is True
    assert context["outgoing_transitions"][0]["automatic_execution_allowed"] is False
    assert context["execution_contract"]["gate_required"] is True
    assert "bbox" not in json.dumps(context, ensure_ascii=False)
    assert context["artifact_is_authorization"] is False


def test_save_and_load_application_graph_validates_checksum(tmp_path: Path) -> None:
    graph = build_application_interface_graph(
        application_identity=APPLICATION,
        interfaces=[_asset("home", "open_detail")],
        entry_interface_id="home",
        transitions=[],
    )

    result = save_application_interface_graph(graph, project_root=tmp_path)
    loaded = load_application_interface_graph(
        "web:example.test",
        project_root=tmp_path,
    )

    assert result["status"] == "saved"
    assert loaded["entry_interface_id"] == "home"
    assert loaded["interface_ids"] == ["home"]
    assert Path(tmp_path, result["graph_path"]).is_file()


def test_workflow_review_is_frozen_as_independent_assets_and_graph(tmp_path: Path) -> None:
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {
            "workflow_id": "example_flow",
            "application_identity": APPLICATION,
            "entry_node_id": "home",
        },
        "nodes": [
            {
                "node_id": "home",
                "display_name": "Home",
                "surface_type": "content_feed",
                "state_signature": "home-v1",
                "evidence": {
                    "source_screenshot_path": "artifacts/screenshots/home.png",
                    "fused_overlay_path": "artifacts/review-overlays/home.png",
                },
                "controls": [
                    {
                        "control_id": "open_detail",
                        "label": "Open detail",
                        "role": "button",
                    }
                ],
                "content_descriptors": [
                    {
                        "content_id": "result_list",
                        "label": "Current results",
                        "source_kind": "region",
                        "source_id": "result_list",
                        "content_behavior": "dynamic_collection",
                        "agent_usage": "decision_signal",
                        "read_policy": "on_interface_match",
                        "agent_description": "读取本次截图中的最新结果",
                    }
                ],
                "review_status": "human_reviewed",
            },
            {
                "node_id": "detail",
                "display_name": "Detail",
                "surface_type": "detail",
                "state_signature": "detail-v1",
                "evidence": {
                    "source_screenshot_path": "artifacts/screenshots/detail.png",
                    "fused_overlay_path": "artifacts/review-overlays/detail.png",
                },
                "controls": [{"control_id": "open_apply", "label": "Apply", "role": "button"}],
                "review_status": "human_reviewed",
            },
        ],
        "edges": [
            {
                "edge_id": "home_to_detail",
                "source_node_id": "home",
                "target_node_id": "detail",
                "target_control_id": "open_detail",
                "action_type": "open_detail",
                "display_name": "打开详情",
                "agent_description": "点击当前条目进入详情",
                "risk_level": "low",
                "review_status": "human_confirmed",
            }
        ],
        "artifact_is_authorization": False,
    }

    result = save_workflow_review_as_application_assets(
        review,
        project_root=tmp_path,
    )
    graph = load_application_interface_graph(
        "web:example.test",
        project_root=tmp_path,
    )

    assert result["status"] == "saved"
    assert result["saved_interface_count"] == 2
    assert result["saved_transition_count"] == 1
    assert result["invalid_transitions"] == []
    assert graph["interface_ids"] == ["detail", "home"]
    assert graph["transitions"][0]["source_control_id"] == "open_detail"
    assert result["agent_evidence_projection"]["asset_count"] == 2
    home_evidence_path = (
        tmp_path
        / "artifacts"
        / "interface-assets"
        / "web_example.test"
        / "interfaces"
        / "home"
        / "agent_evidence.json"
    )
    home_evidence = json.loads(home_evidence_path.read_text(encoding="utf-8"))
    assert home_evidence["available_actions"][0]["target_interface_id"] == "detail"
    assert home_evidence["available_actions"][0]["source_control_id"] == "open_detail"
    assert home_evidence["artifact_is_authorization"] is False
