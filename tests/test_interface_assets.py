from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.learn.interface_assets import (
    build_interface_agent_context,
    build_single_interface_asset,
    load_application_interface_library,
    save_single_interface_asset,
)


def _workflow_node(
    *,
    node_id: str = "interface_home",
    overlay_path: str = "artifacts/review-overlays/home.png",
) -> dict:
    return {
        "node_id": node_id,
        "display_name": "Home",
        "surface_type": "content_feed",
        "state_signature": "home-v1",
        "evidence_status": "ready" if overlay_path else "overlay_missing",
        "evidence": {
            "source_screenshot_path": "artifacts/screenshots/home.png",
            "fused_overlay_path": overlay_path,
            "viewport_size": {"width": 1280, "height": 720},
        },
        "states": [{"state_id": "home", "label": "Home"}],
        "regions": [
            {
                "region_id": "job_card",
                "label": "Current item",
                "bbox": {"x": 40, "y": 120, "width": 360, "height": 180},
                "click_point": {"x": 220, "y": 210},
            }
        ],
        "controls": [
            {
                "control_id": "open_detail",
                "label": "Open detail",
                "role": "button",
                "bbox": {"x": 60, "y": 250, "width": 120, "height": 36},
                "actual_point": {"x": 120, "y": 268},
            }
        ],
        "action_candidates": [
            {
                "action_template_id": "open_detail",
                "semantic_action": "open_detail",
                "target_region_id": "job_card",
                "clickPoint": {"x": 220, "y": 210},
            }
        ],
        "verification_rules": [{"rule_id": "detail_visible"}],
        "blockers": [],
        "review_status": "human_reviewed",
    }


def test_build_single_interface_asset_owns_evidence_and_removes_runtime_points() -> None:
    node = _workflow_node()

    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "web",
            "name": "Example",
            "url": "https://example.test/home",
            "process": "msedge.exe",
        },
    )
    node["evidence"]["fused_overlay_path"] = "artifacts/review-overlays/changed.png"

    assert asset["contract_version"] == "single_interface_asset_v1"
    assert asset["interface_id"] == "interface_home"
    assert asset["application_identity"]["identity_key"] == "web:example.test"
    assert asset["evidence"]["fused_overlay_path"].endswith("home.png")
    serialized = json.dumps(asset, ensure_ascii=False)
    assert "click_point" not in serialized
    assert "actual_point" not in serialized
    assert "clickPoint" not in serialized
    assert asset["safety"]["historical_coordinates_forbidden"] is True
    assert asset["artifact_is_authorization"] is False


def test_build_single_interface_asset_preserves_explicit_missing_overlay_state() -> None:
    asset = build_single_interface_asset(
        _workflow_node(overlay_path=""),
        application_identity={
            "kind": "native",
            "name": "Example App",
            "process": "example.exe",
        },
    )

    assert asset["evidence_status"] == "overlay_missing"
    assert asset["evidence"]["fused_overlay_path"] == ""


def test_human_described_region_is_projected_as_agent_semantic_control() -> None:
    node = _workflow_node()
    node["controls"] = []
    node["action_candidates"] = []
    node["verification_rules"] = []
    node["regions"] = [
        {
            "region_id": "refresh_feed",
            "label": "刷新新闻信息流",
            "role": "button",
            "description": "刷新当前新闻信息流，操作后重新读取新闻区域。",
            "action_type": "click",
            "verification_rule": "新闻卡片内容或更新时间发生变化",
            "risk_level": "normal",
            "human_review": {"bbox_edited": True},
            "bbox": {"x": 40, "y": 120, "w": 120, "h": 36},
        },
        {
            "region_id": "unreviewed_visual_box",
            "label": "visual box",
            "role": "control",
            "bbox": {"x": 200, "y": 120, "w": 120, "h": 36},
        },
    ]

    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "web",
            "url": "https://example.test/news",
        },
    )
    context = build_interface_agent_context(asset)

    assert asset["controls"] == [
        {
            "control_id": "refresh_feed",
            "label": "刷新新闻信息流",
            "role": "button",
            "agent_description": "刷新当前新闻信息流，操作后重新读取新闻区域。",
            "review_status": "human_reviewed",
            "source_region_id": "refresh_feed",
        }
    ]
    assert asset["action_candidates"] == [
        {
            "action_template_id": "region_action_refresh_feed",
            "action_type": "click",
            "semantic_action": "click",
            "display_name": "刷新新闻信息流",
            "agent_description": "刷新当前新闻信息流，操作后重新读取新闻区域。",
            "target_control_id": "refresh_feed",
            "target_region_id": "refresh_feed",
            "risk_level": "normal",
            "review_status": "human_reviewed",
            "verification_rule_ids": ["region_rule_refresh_feed"],
        }
    ]
    assert asset["verification_rules"] == [
        {
            "rule_id": "region_rule_refresh_feed",
            "label": "新闻卡片内容或更新时间发生变化",
            "source_region_id": "refresh_feed",
            "review_status": "human_reviewed",
        }
    ]
    assert context["controls"][0]["control_id"] == "refresh_feed"
    assert context["available_action_candidates"][0]["target_control_id"] == "refresh_feed"
    assert "bbox" not in json.dumps(context, ensure_ascii=False)


def test_human_described_open_modal_region_is_preserved_as_semantic_action() -> None:
    node = _workflow_node()
    node["controls"] = []
    node["action_candidates"] = []
    node["verification_rules"] = []
    node["regions"] = [
        {
            "region_id": "open_policy",
            "label": "打开规则弹窗",
            "role": "button",
            "description": "打开规则弹窗并读取当前规则。",
            "action_type": "open_modal",
            "verification_rule": "规则弹窗可见",
            "risk_level": "normal",
            "human_review": {"bbox_edited": True},
            "bbox": {"x": 40, "y": 120, "w": 120, "h": 36},
        }
    ]

    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "web",
            "url": "https://example.test/policy",
        },
    )

    assert asset["action_candidates"][0]["action_type"] == "open_modal"
    assert asset["action_candidates"][0]["semantic_action"] == "open_modal"


def test_save_and_load_interface_assets_are_grouped_by_application(tmp_path: Path) -> None:
    application = {
        "kind": "native",
        "name": "Example App",
        "process": "example.exe",
    }
    first = build_single_interface_asset(
        _workflow_node(node_id="interface_home"),
        application_identity=application,
    )
    second = build_single_interface_asset(
        _workflow_node(node_id="interface_detail"),
        application_identity=application,
    )

    first_result = save_single_interface_asset(first, project_root=tmp_path)
    second_result = save_single_interface_asset(second, project_root=tmp_path)
    library = load_application_interface_library(
        "native:example.exe:example-app",
        project_root=tmp_path,
    )

    assert first_result["status"] == "saved"
    assert second_result["status"] == "saved"
    assert library["contract_version"] == "application_interface_library_v1"
    assert library["interface_ids"] == ["interface_detail", "interface_home"]
    assert [item["interface_id"] for item in library["interfaces"]] == [
        "interface_detail",
        "interface_home",
    ]
    assert all(item["application_identity"]["identity_key"] == "native:example.exe:example-app" for item in library["interfaces"])
    assert all(Path(tmp_path, item["asset_path"]).is_file() for item in library["records"])


def test_build_single_interface_asset_rejects_unresolved_application_identity() -> None:
    with pytest.raises(ValueError, match="resolved application identity"):
        build_single_interface_asset(_workflow_node(), application_identity={})


def test_interface_asset_separates_fixed_anchors_and_dynamic_slots() -> None:
    node = _workflow_node()
    node["content_descriptors"] = [
        {
            "content_id": "search_label",
            "label": "Search jobs",
            "source_kind": "control",
            "source_id": "open_detail",
            "content_behavior": "fixed_label",
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
            "agent_description": "用于确认当前界面的固定标题",
        },
        {
            "content_id": "job_results",
            "label": "Current job results",
            "source_kind": "region",
            "source_id": "job_card",
            "content_behavior": "dynamic_collection",
            "agent_usage": "decision_signal",
            "read_policy": "on_demand",
            "agent_description": "读取当前岗位标题和公司，不沿用历史内容",
            "current_value": "不得进入持久资产的旧岗位",
        },
    ]

    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "web",
            "name": "Example",
            "url": "https://example.test/home",
            "process": "msedge.exe",
        },
    )

    assert [item["content_id"] for item in asset["fixed_anchors"]] == ["search_label"]
    assert [item["content_id"] for item in asset["dynamic_slots"]] == ["job_results"]
    assert "current_value" not in asset["dynamic_slots"][0]
    assert asset["dynamic_slots"][0]["agent_description"].startswith("读取当前岗位")


def test_agent_context_reads_dynamic_values_only_from_current_observation() -> None:
    node = _workflow_node()
    node["content_descriptors"] = [
        {
            "content_id": "job_results",
            "label": "Current job results",
            "source_kind": "region",
            "source_id": "job_card",
            "content_behavior": "dynamic_collection",
            "agent_usage": "decision_signal",
            "read_policy": "on_interface_match",
            "agent_description": "用于判断当前岗位是否值得打开",
        }
    ]
    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "web",
            "name": "Example",
            "url": "https://example.test/home",
            "process": "msedge.exe",
        },
    )

    context = build_interface_agent_context(
        asset,
        live_observation={
            "contract_version": "live_interface_observation_v1",
            "interface_id": "interface_home",
            "capture_id": "capture-current",
            "observed_at": "2026-07-28T05:00:00+00:00",
            "values_by_content_id": {
                "job_results": ["Current role A", "Current role B"],
            },
        },
    )

    assert context["dynamic_content"][0]["observation_status"] == "current"
    assert context["dynamic_content"][0]["value"] == [
        "Current role A",
        "Current role B",
    ]
    assert context["dynamic_content"][0]["capture_id"] == "capture-current"
    assert context["execution_contract"]["historical_coordinates_forbidden"] is True
    assert context["artifact_is_authorization"] is False


def test_agent_context_marks_unobserved_dynamic_content_and_redacts_sensitive_value() -> None:
    node = _workflow_node()
    node["content_descriptors"] = [
        {
            "content_id": "latest_message",
            "label": "Latest message",
            "source_kind": "region",
            "source_id": "job_card",
            "content_behavior": "dynamic_value",
            "agent_usage": "decision_signal",
            "read_policy": "on_demand",
            "agent_description": "需要时读取当前消息",
        },
        {
            "content_id": "health_answer",
            "label": "Health answer",
            "source_kind": "region",
            "source_id": "job_card",
            "content_behavior": "sensitive_dynamic",
            "agent_usage": "display_only",
            "read_policy": "on_demand",
            "agent_description": "敏感信息不得写入上下文原文",
        },
    ]
    asset = build_single_interface_asset(
        node,
        application_identity={
            "kind": "native",
            "name": "Example App",
            "process": "example.exe",
        },
    )

    context = build_interface_agent_context(
        asset,
        live_observation={
            "contract_version": "live_interface_observation_v1",
            "interface_id": "interface_home",
            "capture_id": "capture-current",
            "observed_at": "2026-07-28T05:00:00+00:00",
            "values_by_content_id": {"health_answer": "private answer"},
        },
    )

    values = {item["content_id"]: item for item in context["dynamic_content"]}
    assert values["latest_message"]["observation_status"] == "requires_observation"
    assert values["health_answer"]["observation_status"] == "current_redacted"
    assert "value" not in values["health_answer"]
    assert values["health_answer"]["value_length"] == len("private answer")
    assert len(values["health_answer"]["value_sha256"]) == 64
    assert "private answer" not in json.dumps(context, ensure_ascii=False)


def test_interface_asset_rejects_unknown_content_semantics() -> None:
    node = _workflow_node()
    node["content_descriptors"] = [
        {
            "content_id": "bad",
            "content_behavior": "sometimes_fixed",
            "agent_usage": "decision_signal",
            "read_policy": "on_demand",
        }
    ]

    with pytest.raises(ValueError, match="content_behavior"):
        build_single_interface_asset(
            node,
            application_identity={
                "kind": "native",
                "name": "Example App",
                "process": "example.exe",
            },
        )
