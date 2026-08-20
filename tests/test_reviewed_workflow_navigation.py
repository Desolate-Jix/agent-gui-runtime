from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

import app.agent.reviewed_workflow_navigation as reviewed_navigation
from app.agent.navigation_reading import validate_navigation_reading_decision
from app.agent.reviewed_workflow_navigation import (
    build_reviewed_workflow_navigation_context,
    load_reviewed_workflow_interface_evidence,
    run_reviewed_workflow_navigation_controller,
)
from app.learn.interface_workflow_review import (
    build_interface_node_review_revision,
    save_interface_workflow_review_candidate,
)
from scripts.run_reviewed_workflow_navigation_smoke import run_smoke


APPLICATION = {
    "kind": "web",
    "name": "Example",
    "url": "https://example.test/items",
    "process": "msedge.exe",
}


def _review(
    *,
    detail_review_status: str = "human_approved",
    edge_review_status: str = "human_approved",
) -> dict:
    return {
        "contract_version": "single_application_workflow_review_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": "reviewed_items_flow",
            "goal": "Open the selected item and read its current detail.",
            "application_identity": APPLICATION,
            "entry_node_id": "items",
            "node_ids": ["items", "detail"],
            "edge_ids": ["items_to_detail"],
            "review_status": "human_reviewed",
            "published_memory_version": None,
        },
        "nodes": [
            {
                "node_id": "items",
                "display_name": "Current items",
                "surface_type": "content_collection",
                "state_signature": "items-v1",
                "evidence": {
                    "source_screenshot_path": "artifacts/screenshots/items.png",
                    "fused_overlay_path": "artifacts/review-overlays/items.png",
                },
                "content_descriptors": [
                    {
                        "content_id": "items_heading",
                        "label": "Items",
                        "source_kind": "control",
                        "source_id": "open_selected_item",
                        "content_behavior": "fixed_label",
                        "agent_usage": "identity_anchor",
                        "read_policy": "on_interface_match",
                        "agent_description": "用于确认当前是条目列表界面。",
                    }
                ],
                "controls": [
                    {
                        "control_id": "open_selected_item",
                        "semantic_name": "Selected item control",
                        "visible_text_anchors": ["Open"],
                        "purpose": "Open the item currently selected by the Agent.",
                        "role": "button",
                        "allowed_actions": ["open_detail"],
                        "verification_rule": {
                            "rule_ids": ["detail_visible"],
                            "success_conditions": ["detail interface matched"],
                        },
                        "risk_class": "low",
                    }
                ],
                "states": [{"state_id": "items_ready", "display_name": "Items ready"}],
                "verification_rules": [
                    {"rule_id": "detail_visible", "description": "Detail is visible."}
                ],
                "review_status": edge_review_status,
                "reviewed_by_human": edge_review_status == "human_approved",
                "manual_revision": {
                    "semantic_description": "Read the current items and open the selected item."
                },
            },
            {
                "node_id": "detail",
                "display_name": "Current item detail",
                "surface_type": "detail",
                "state_signature": "detail-v1",
                "evidence": {
                    "source_screenshot_path": "artifacts/screenshots/detail.png",
                    "fused_overlay_path": "artifacts/review-overlays/detail.png",
                },
                "content_descriptors": [
                    {
                        "content_id": "detail_heading",
                        "label": "Detail",
                        "source_kind": "region",
                        "source_id": "detail_content",
                        "content_behavior": "fixed_label",
                        "agent_usage": "identity_anchor",
                        "read_policy": "on_interface_match",
                        "agent_description": "用于确认当前是条目详情界面。",
                    },
                    {
                        "content_id": "detail_content",
                        "label": "Current detail",
                        "source_kind": "region",
                        "source_id": "detail_content",
                        "content_behavior": "dynamic_value",
                        "agent_usage": "decision_signal",
                        "read_policy": "on_demand",
                        "agent_description": "需要时读取当前详情，不沿用历史内容。",
                    },
                ],
                "controls": [],
                "states": [{"state_id": "detail_ready", "display_name": "Detail ready"}],
                "review_status": detail_review_status,
                "reviewed_by_human": detail_review_status == "human_approved",
                "manual_revision": {
                    "semantic_description": "Read the latest detail and stop safely."
                },
            },
        ],
        "edges": [
            {
                "edge_id": "items_to_detail",
                "operation_id": "items_to_detail",
                "source_node_id": "items",
                "target_node_id": "detail",
                "source_control_id": "open_selected_item",
                "target_control_id": "open_selected_item",
                "target_region_id": "",
                "action_type": "open_detail",
                "display_name": "Open selected item",
                "agent_description": "Open the selected current item and verify its detail.",
                "risk_level": "low",
                "requires_user_confirmation": False,
                "preconditions": ["current interface matches items"],
                "success_conditions": ["detail interface matched"],
                "failure_conditions": ["detail interface verification failed"],
                "gate_policy": "fresh_grounding_and_gate_required",
                "review_status": "human_approved",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        ],
        "invalid_sources": [],
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
        },
    }


def _save_reviewed_workflow(tmp_path: Path, review: dict | None = None) -> dict:
    review = review or _review()
    workflow_id = str(review["workflow"]["workflow_id"])
    for index, node in enumerate(review["nodes"], start=1):
        node_id = str(node["node_id"])
        evidence = node["evidence"]
        for key in ("source_screenshot_path", "fused_overlay_path"):
            evidence_path = tmp_path / str(evidence[key])
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (64, 48), (index, index, index)).save(evidence_path)
            if key == "source_screenshot_path":
                evidence["source_screenshot_sha256"] = hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest()

        source_path = (
            tmp_path
            / "artifacts"
            / "learning"
            / "reviewed-workflow-navigation"
            / f"{node_id}.json"
        )
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            json.dumps(
                {
                    "contract_version": "interface_workflow_node_review_source_v1",
                    "workflow_id": workflow_id,
                    "node_id": node_id,
                    "draft": {
                        "screen_summary": str(node.get("display_name") or node_id),
                        "state_signature": str(node.get("state_signature") or node_id),
                    },
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        evidence["source_path"] = source_path.relative_to(tmp_path).as_posix()
        evidence["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()

    for edge in review["edges"]:
        edge.setdefault("operation_id", str(edge["edge_id"]))
        edge.setdefault("target_control_id", "")
        edge.setdefault("target_region_id", "")
        edge.setdefault("risk_level", "low")
        edge.setdefault("requires_user_confirmation", edge["risk_level"] == "high")

    for node in review["nodes"]:
        if node.get("reviewed_by_human") is not True:
            continue
        node["human_review_confirmation"] = {
            "contract_version": "interface_node_human_review_confirmation_v1",
            "revision": build_interface_node_review_revision(
                review,
                node_id=str(node["node_id"]),
            ),
        }
    return save_interface_workflow_review_candidate(review, project_root=tmp_path)


def test_reviewed_multi_interface_workflow_builds_agent_navigation_choice(
    tmp_path: Path,
) -> None:
    _save_reviewed_workflow(tmp_path)

    evidence = load_reviewed_workflow_interface_evidence(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        interface_id="items",
    )
    context = build_reviewed_workflow_navigation_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        interface_id="items",
        goal="Open the selected item and read the current detail.",
        observation={
            "contract_version": "current_interface_observation_v1",
            "interface_id": "items",
            "capture_id": "capture-current",
            "screenshot_sha256": "a" * 64,
            "trace_path": "logs/traces/current.json",
        },
    )

    assert evidence["readiness"]["status"] == "agent_usable"
    transition = next(
        choice
        for choice in context["choices"]
        if choice["choice_id"] == "transition:items_to_detail"
    )
    assert transition["source_control_id"] == "open_selected_item"
    assert transition["target_interface_id"] == "detail"
    plan = validate_navigation_reading_decision(
        context,
        {
            "choice_id": "transition:items_to_detail",
            "reason": "The reviewed workflow exposes the intended low-risk transition.",
        },
    )
    assert plan["semantic_action"] == "open_detail"
    assert plan["expected_target_interface_id"] == "detail"
    assert plan["requires_operation_resolution"] is True
    serialized = json.dumps(context, ensure_ascii=False)
    assert "bbox" not in serialized
    assert "click_point" not in serialized
    assert context["artifact_is_authorization"] is False


def test_reviewed_workflow_navigation_rejects_interface_needing_review(
    tmp_path: Path,
) -> None:
    _save_reviewed_workflow(
        tmp_path,
        _review(detail_review_status="needs_human_review"),
    )

    with pytest.raises(ValueError, match="agent_usable"):
        load_reviewed_workflow_interface_evidence(
            project_root=tmp_path,
            application_identity_key="web:example.test",
            workflow_id="reviewed_items_flow",
            interface_id="detail",
        )


def test_reviewed_workflow_navigation_rejects_unapproved_transition(
    tmp_path: Path,
) -> None:
    _save_reviewed_workflow(
        tmp_path,
        _review(edge_review_status="needs_human_review"),
    )

    with pytest.raises(ValueError, match="agent_usable"):
        load_reviewed_workflow_interface_evidence(
            project_root=tmp_path,
            application_identity_key="web:example.test",
            workflow_id="reviewed_items_flow",
            interface_id="items",
        )


def test_reviewed_workflow_navigation_rejects_unknown_workflow(tmp_path: Path) -> None:
    _save_reviewed_workflow(tmp_path)

    with pytest.raises(ValueError, match="workflow not found"):
        load_reviewed_workflow_interface_evidence(
            project_root=tmp_path,
            application_identity_key="web:example.test",
            workflow_id="missing_workflow",
            interface_id="items",
        )


def test_reviewed_workflow_navigation_smoke_writes_non_executing_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_reviewed_workflow(tmp_path)

    class FakeProvider:
        def __init__(self, **_: object) -> None:
            pass

        def decide(self, context: dict) -> dict:
            assert context["contract_version"] == "navigation_reading_agent_context_v1"
            return {
                "choice_id": "transition:items_to_detail",
                "reason": "Use the reviewed low-risk transition.",
                "decision_source": "actual_model_call",
            }

    monkeypatch.setattr(
        "scripts.run_reviewed_workflow_navigation_smoke."
        "OpenAICompatibleNavigationDecisionProvider",
        FakeProvider,
    )
    output_path = tmp_path / "logs" / "report.json"
    report = run_smoke(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        interface_id="items",
        goal="Open the selected item and read its current detail.",
        endpoint="http://127.0.0.1:13240",
        model_name="test-model",
        output_path=output_path,
    )

    assert report["execution"]["attempted"] is False
    assert report["validated_plan"]["semantic_action"] == "open_detail"
    assert report["artifact_is_authorization"] is False
    assert json.loads(output_path.read_text(encoding="utf-8")) == report


def test_saved_multi_interface_workflow_drives_continuous_agent_controller(
    tmp_path: Path,
) -> None:
    _save_reviewed_workflow(tmp_path)
    observations = iter(
        [
            {
                "contract_version": "current_interface_observation_v1",
                "interface_id": "items",
                "surface_type": "content_collection",
                "capture_id": "items-current",
                "screenshot_sha256": "a" * 64,
                "trace_path": "logs/traces/items-current.json",
            },
            {
                "contract_version": "current_interface_observation_v1",
                "interface_id": "detail",
                "surface_type": "detail",
                "capture_id": "detail-current",
                "screenshot_sha256": "b" * 64,
                "trace_path": "logs/traces/detail-current.json",
            },
        ]
    )
    decisions = iter(
        [
            {
                "choice_id": "transition:items_to_detail",
                "reason": "Use the reviewed low-risk transition.",
                "decision_source": "deterministic_fixture",
            },
            {
                "choice_id": "safe_stop:agent_requested_safe_stop",
                "reason": "The target detail interface is verified.",
                "decision_source": "deterministic_fixture",
            },
        ]
    )
    seen_contexts: list[dict] = []

    def decide(context: dict) -> dict:
        seen_contexts.append(context)
        return next(decisions)

    def execute(plan: dict, _context: dict) -> dict:
        return {
            "contract_version": "navigation_reading_operation_result_v1",
            "gate_result": {"allowed": True, "reason": "low_risk"},
            "action_type": "open_detail",
            "action_executed": True,
            "post_action_verified": True,
            "source_freshness": dict(plan["freshness"]),
        }

    report = run_reviewed_workflow_navigation_controller(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        goal="Open the selected item and read its current detail.",
        session_id="saved-workflow-session",
        observe_current=lambda: next(observations),
        decide=decide,
        execute_operation=execute,
        max_steps=4,
    )

    assert report["source_workflow"]["interface_count"] == 2
    assert report["source_workflow"]["transition_count"] == 1
    assert report["source_workflow"]["source"] == "reviewed_multi_interface_workflow"
    assert report["controller"]["visited_interfaces"] == ["items", "detail"]
    assert report["controller"]["final_status"] == "safe_stop"
    assert [step["semantic_action"] for step in report["controller"]["steps"]] == [
        "open_detail",
        "safe_stop",
    ]
    assert all("bbox" not in json.dumps(context) for context in seen_contexts)
    assert all("click_point" not in json.dumps(context) for context in seen_contexts)
    assert report["safety"]["artifact_is_authorization"] is False


def test_reviewed_node_agent_description_supplies_interface_responsibility(
    tmp_path: Path,
) -> None:
    review = _review()
    items = next(node for node in review["nodes"] if node["node_id"] == "items")
    items["agent_description"] = "Choose the next unfinished reviewed branch."
    items["manual_revision"] = {
        "source_path": "artifacts/reviews/items.json",
        "artifact_is_authorization": False,
    }
    _save_reviewed_workflow(tmp_path, review)

    evidence = load_reviewed_workflow_interface_evidence(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        interface_id="items",
    )

    assert evidence["interface"]["responsibility"] == (
        "Choose the next unfinished reviewed branch."
    )
    assert evidence["readiness"]["status"] == "agent_usable"


def test_reviewed_workflow_compiles_directly_to_live_multi_interface_suite(
    tmp_path: Path,
) -> None:
    review = _review()
    items = next(node for node in review["nodes"] if node["node_id"] == "items")
    items["action_candidates"] = [
        {
            "action_template_id": "open_selected_item_action",
            "semantic_action": "open_detail",
            "target_control_id": "open_selected_item",
            "target_interface_id": "detail",
            "operation_goal": "Click the button labeled Open selected item",
        }
    ]
    detail = next(node for node in review["nodes"] if node["node_id"] == "detail")
    detail["controls"] = [
        {
            "control_id": "return_to_items",
            "semantic_name": "Return to items",
            "visible_text_anchors": ["Return"],
            "purpose": "Return to the reviewed item list.",
            "role": "button",
            "allowed_actions": ["back"],
            "verification_rule": {
                "rule_ids": [],
                "success_conditions": ["items interface matched"],
            },
            "risk_class": "low",
            "review_status": "human_reviewed",
        }
    ]
    detail["action_candidates"] = [
        {
            "action_template_id": "return_to_items_action",
            "semantic_action": "back",
            "target_control_id": "return_to_items",
            "target_interface_id": "items",
            "operation_goal": "Click the button labeled Return to items",
        }
    ]
    review["workflow"]["edge_ids"].append("detail_to_items")
    review["edges"].append(
        {
            "edge_id": "detail_to_items",
            "source_node_id": "detail",
            "target_node_id": "items",
            "source_control_id": "return_to_items",
            "target_control_id": "return_to_items",
            "action_type": "back",
            "display_name": "Return to items",
            "agent_description": "Return to the reviewed item list.",
            "risk_level": "low",
            "requires_user_confirmation": False,
            "preconditions": ["current interface matches detail"],
            "success_conditions": ["items interface matched"],
            "failure_conditions": ["items interface verification failed"],
            "gate_policy": "fresh_grounding_and_gate_required",
            "review_status": "human_approved",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    detail["content_descriptors"][1]["max_scrolls"] = 3
    detail["content_descriptors"][1]["bottom_markers"] = ["DETAIL END"]
    _save_reviewed_workflow(tmp_path, review)

    suite = reviewed_navigation.build_reviewed_workflow_live_suite(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
    )

    assert suite["contract_version"] == "reviewed_workflow_live_suite_v1"
    assert suite["source"] == "reviewed_multi_interface_workflow"
    assert suite["initial_interface_id"] == "items"
    assert suite["app_name"] == "Example"
    assert [item["interface_id"] for item in suite["interface_specs"]] == [
        "items",
        "detail",
    ]
    assert suite["interface_specs"][0]["identity_marker_sets"] == [
        ["Items", "Open"],
    ]
    assert suite["interface_specs"][1]["identity_marker_sets"] == [
        ["Detail", "Return"],
    ]
    assert "Selected item control" not in json.dumps(
        suite["interface_specs"],
        ensure_ascii=False,
    )
    assert "Return to items" not in json.dumps(
        suite["interface_specs"],
        ensure_ascii=False,
    )
    assert suite["interface_specs"][1]["read_target"] == {
        "content_id": "detail_content",
        "scroll_scope": "page",
        "target_pane": "page",
        "wheel_clicks": 3,
        "bottom_markers": ["DETAIL END"],
    }
    assert suite["transitions"][0]["operation_goal"] == (
        "Click the button labeled Open selected item"
    )
    assert set(suite["evidence_by_interface"]) == {"items", "detail"}
    serialized = json.dumps(suite, ensure_ascii=False)
    assert "bbox" not in serialized
    assert "click_point" not in serialized
    assert suite["artifact_is_authorization"] is False


def test_reviewed_workflow_does_not_use_shared_controls_as_identity(
    tmp_path: Path,
) -> None:
    review = _review()
    for node in review["nodes"]:
        node.setdefault("controls", []).append(
            {
                "control_id": f"{node['node_id']}_back",
                "semantic_name": "Back",
                "purpose": "Return to the previous reviewed interface.",
                "role": "button",
                "allowed_actions": ["back"],
                "verification_rule": {
                    "rule_ids": [],
                    "success_conditions": ["previous interface matched"],
                },
                "risk_class": "low",
            }
        )
    _save_reviewed_workflow(tmp_path, review)

    suite = reviewed_navigation.build_reviewed_workflow_live_suite(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
    )

    assert all(
        ["Back"] not in spec["identity_marker_sets"]
        for spec in suite["interface_specs"]
    )


def test_reviewed_workflow_keeps_multiple_identity_anchors_conjunctive(
    tmp_path: Path,
) -> None:
    review = _review()
    items = next(node for node in review["nodes"] if node["node_id"] == "items")
    items["content_descriptors"].append(
        {
            "content_id": "items_subheading",
            "label": "Current collection",
            "source_kind": "region",
            "source_id": "items_collection",
            "content_behavior": "fixed_label",
            "agent_usage": "identity_anchor",
            "read_policy": "on_interface_match",
            "agent_description": "用于共同确认当前列表界面。",
        }
    )
    _save_reviewed_workflow(tmp_path, review)

    suite = reviewed_navigation.build_reviewed_workflow_live_suite(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
    )

    assert suite["interface_specs"][0]["identity_marker_sets"] == [
        ["Items", "Current collection", "Open"],
    ]


def test_reviewed_workflow_live_entry_generates_derived_multi_interface_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_reviewed_workflow(tmp_path)
    captured: dict = {}

    def run_suite(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {"contract_version": "navigation_reading_live_smoke_report_v1"}

    monkeypatch.setattr(
        "app.agent.navigation_reading_live_smoke.run_navigation_reading_live_suite",
        run_suite,
    )
    runner = getattr(
        reviewed_navigation,
        "run_reviewed_workflow_navigation_live_smoke",
        None,
    )
    assert callable(runner), "formal reviewed workflows need a direct live entry"

    report = runner(
        project_root=tmp_path,
        application_identity_key="web:example.test",
        workflow_id="reviewed_items_flow",
        out_dir=tmp_path / "live-report",
        runtime_endpoint="http://runtime.invalid",
        decision_endpoint="http://model.invalid",
        decision_model="controlled",
    )

    assert report["contract_version"] == "navigation_reading_live_smoke_report_v1"
    suite = captured["suite"]
    assert suite["source"] == "reviewed_multi_interface_workflow"
    assert set(suite["evidence_by_interface"]) == {"items", "detail"}
    assert captured["persist_session_workflow"] is True
    assert captured["workflow_project_root"] == tmp_path


def test_reviewed_workflow_live_cli_uses_formal_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import run_reviewed_workflow_navigation_live_smoke as cli

    captured: dict = {}

    def run_live(**kwargs: object) -> dict:
        captured.update(kwargs)
        return {
            "contract_version": "navigation_reading_live_smoke_report_v1",
            "report_path": str(tmp_path / "report.json"),
            "controller": {
                "final_status": "safe_stop",
                "stop_reason": "agent_requested_safe_stop",
                "visited_interfaces": ["items", "detail"],
            },
        }

    monkeypatch.setattr(cli, "run_reviewed_workflow_navigation_live_smoke", run_live)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_reviewed_workflow_navigation_live_smoke.py",
            "--application-identity-key",
            "web:example.test",
            "--workflow-id",
            "reviewed_items_flow",
            "--out",
            str(tmp_path / "live"),
            "--json",
        ],
    )

    assert cli.main() == 0
    assert captured["application_identity_key"] == "web:example.test"
    assert captured["workflow_id"] == "reviewed_items_flow"
    assert Path(captured["out_dir"]) == (tmp_path / "live").resolve()
    assert captured["project_root"] == Path.cwd().resolve()
    output = json.loads(capsys.readouterr().out)
    assert output["controller"]["visited_interfaces"] == ["items", "detail"]
