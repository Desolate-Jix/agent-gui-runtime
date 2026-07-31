from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.run_interface_class_rule_demo import run_interface_class_rule_demo


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replay_report(
    *,
    category: str,
    strategy: str,
    root_roles: list[str],
    overlay_path: str,
) -> dict:
    return {
        "contract_version": "learn_two_stage_replay_report_v1",
        "interface_classification": {
            "category": category,
            "status": "accepted",
            "source": "model_output",
            "class_rule_profile": {
                "primary_content_strategy": strategy,
                "allow_media_card_synthesis": False,
                "allow_chat_semantics": False,
            },
        },
        "class_rule_profile": {
            "primary_content_strategy": strategy,
            "allow_media_card_synthesis": False,
            "allow_chat_semantics": False,
        },
        "stage1_region_localization": {
            "regions": [
                {
                    "region_id": f"region_{role}",
                    "label": role.replace("_", " ").title(),
                    "role": role,
                    "bbox": {"x": 1, "y": 2, "w": 30, "h": 40},
                }
                for role in root_roles
            ]
        },
        "stage1_gate": {"status": "passed"},
        "stage2_numbering": {
            "agent_peer_card_inventory": {
                "contract_version": "agent_peer_card_inventory_v1",
                "status": "current_peer_items_projected",
                "peer_item_family": "independent_content_module",
                "current_visual_evidence_required": True,
                "item_count": 1,
                "readable_item_count": 1,
                "review_candidate_count": 0,
                "items": [
                    {
                        "candidate_id": "module_1",
                        "semantic_name": "Top story",
                        "content_summary": ["Top story", "Publisher - 2h"],
                        "source_kind": "current_screen_inventory",
                        "candidate_kind": "visual_card_parent",
                        "agent_decision_status": "readable_candidate",
                        "review_status": "needs_human_review",
                        "inferred_neighbor": False,
                        "capabilities": {
                            "read_current_content": True,
                            "open_detail_candidate": False,
                            "requires_fresh_localization": True,
                            "requires_gate": True,
                        },
                    }
                ],
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            "layout_review_enhancement": {
                "report": {
                    "normalized_existing_card_count": 3,
                    "neighbor_proposal_count": 1,
                    "class_rule_context": {
                        "class_prior": "expected",
                        "peer_item_family": "independent_content_module",
                        "activation": "current_visual_repetition_required",
                        "can_create_without_visual_support": False,
                        "triggered_by_current_visual_evidence": True,
                    },
                },
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        },
        "stage1_structure": {
            "diagnostics": {
                "root_selection": {
                    "class_rule_edge_partition_suppressed_without_navigation_evidence": (
                        category == "feed_workspace"
                    )
                }
            }
        },
        "overlay_status": {"status": "available", "path": overlay_path},
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def test_interface_class_rule_demo_emits_agent_readable_evidence(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    screenshot = tmp_path / "screen.png"
    trace.write_text("{}", encoding="utf-8")
    screenshot.write_bytes(b"png")
    manifest = {
        "contract_version": "interface_class_rule_demo_manifest_v1",
        "class_rule_id": "aggregate_portal",
        "cases": [
            {
                "case_id": "aggregate_positive",
                "case_role": "positive",
                "source_type": "recorded_model_output",
                "trace_path": str(trace),
                "trace_sha256": _sha256(trace),
                "screenshot_path": str(screenshot),
                "screenshot_sha256": _sha256(screenshot),
                "expected": {
                    "interface_category": "aggregate_portal",
                    "primary_content_strategy": "independent_content_modules",
                    "root_roles": ["top_bar", "main_content"],
                    "stage1_gate_status": "passed",
                },
            },
            {
                "case_id": "feed_near_negative",
                "case_role": "near_negative",
                "source_type": "recorded_model_output",
                "trace_path": str(trace),
                "trace_sha256": _sha256(trace),
                "screenshot_path": str(screenshot),
                "screenshot_sha256": _sha256(screenshot),
                "expected": {
                    "interface_category": "feed_workspace",
                    "primary_content_strategy": "feed_items",
                    "root_roles": ["top_bar", "main_content"],
                    "stage1_gate_status": "passed",
                },
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    def replay_runner(case: dict, case_out_dir: Path) -> dict:
        expected = case["expected"]
        return _replay_report(
            category=expected["interface_category"],
            strategy=expected["primary_content_strategy"],
            root_roles=expected["root_roles"],
            overlay_path=str(case_out_dir / "overlay.png"),
        )

    report = run_interface_class_rule_demo(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
        replay_runner=replay_runner,
    )

    assert report["demo_readiness"] == "ready_for_offline_read_only_demo"
    assert report["class_rule_routing"] == {
        "passed": 2,
        "attempted": 2,
        "rate": 1.0,
        "interpretation": "recorded-output class-rule routing checks; not model accuracy",
    }
    assert report["agent_evidence_contract"]["passed"] == 2
    assert report["peer_card_inventory_summary"] == {
        "cases_with_current_inventory": 2,
        "attempted_cases": 2,
        "readable_item_total": 2,
        "review_candidate_total": 0,
        "interpretation": (
            "current-screen Agent inventory counts only; not recognition accuracy "
            "or execution reliability"
        ),
    }
    assert report["cases"][0]["peer_card_inventory"] == {
        "status": "current_peer_items_projected",
        "peer_item_family": "independent_content_module",
        "item_count": 1,
        "readable_item_count": 1,
        "review_candidate_count": 0,
    }
    evidence_path = tmp_path / report["cases"][0]["agent_evidence_path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["decision_support"]["primary_content_strategy"] == "independent_content_modules"
    assert evidence["decision_support"]["layout_review_strategy"] == {
        "class_prior": "expected",
        "peer_item_family": "independent_content_module",
        "activation": "current_visual_repetition_required",
        "triggered_by_current_visual_evidence": True,
        "normalized_existing_candidate_count": 3,
        "review_candidate_count": 1,
        "interpretation": (
            "class prior is advisory; only current visual repetition may produce review candidates"
        ),
    }
    assert evidence["decision_support"]["peer_card_inventory"] == {
        "contract_version": "agent_peer_card_inventory_v1",
        "status": "current_peer_items_projected",
        "peer_item_family": "independent_content_module",
        "current_visual_evidence_required": True,
        "item_count": 1,
        "readable_item_count": 1,
        "review_candidate_count": 0,
        "items": [
            {
                "candidate_id": "module_1",
                "semantic_name": "Top story",
                "content_summary": ["Top story", "Publisher - 2h"],
                "source_kind": "current_screen_inventory",
                "candidate_kind": "visual_card_parent",
                "agent_decision_status": "readable_candidate",
                "review_status": "needs_human_review",
                "inferred_neighbor": False,
                "capabilities": {
                    "read_current_content": True,
                    "open_detail_candidate": False,
                    "requires_fresh_localization": True,
                    "requires_gate": True,
                },
            }
        ],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert evidence["execution_contract"]["historical_coordinates_forbidden"] is True
    assert evidence["artifact_is_authorization"] is False
    assert "bbox" not in json.dumps(evidence)
    assert report["safety"]["live_clicks"] == 0


def test_interface_class_rule_demo_excludes_stale_fixture(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    screenshot = tmp_path / "screen.png"
    trace.write_text("{}", encoding="utf-8")
    screenshot.write_bytes(b"png")
    manifest = {
        "contract_version": "interface_class_rule_demo_manifest_v1",
        "class_rule_id": "aggregate_portal",
        "cases": [
            {
                "case_id": "stale_case",
                "case_role": "positive",
                "trace_path": str(trace),
                "trace_sha256": _sha256(trace),
                "screenshot_path": str(screenshot),
                "screenshot_sha256": "0" * 64,
                "expected": {},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_interface_class_rule_demo(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
        replay_runner=lambda case, out: {},
    )

    assert report["class_rule_routing"]["attempted"] == 0
    assert report["class_rule_routing"]["rate"] == "not_covered"
    assert report["invalid_cases"][0]["failure_category"] == "stale_fixture"
    assert report["demo_readiness"] == "not_ready"
