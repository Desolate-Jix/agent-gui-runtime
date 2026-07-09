from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.learn.draft_review import load_learning_draft_review
from app.main import app
from scripts.build_learn_demo_scaffold import build_learn_demo_scaffold
from scripts.report_learning_mode_demo_goal_readiness import report_learning_mode_demo_goal_readiness
from tests.test_learn_demo_scaffold import _candidate_fixture


def _force_pending_calibration(scaffold: dict) -> dict:
    path = Path(scaffold["report_path"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("summary", {})["precise_pending_calibration_count"] = 2
    payload["model_provenance_audit"] = {
        "status": "mixed_actual_model_and_assisted_review_evidence",
        "meets_fully_model_generated_demo_requirement": False,
        "actual_model_call_evidence_count": 1,
        "assisted_or_human_review_evidence_count": 2,
        "blocking_reasons": ["contains_assisted_or_human_review_evidence"],
    }
    trial_path = path.parent / "actual_parser_output_with_fusion_status.json"
    trial_path.write_text(json.dumps({"learning_draft": {}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    base_status_path = path.parent / "learn_fusion_refresh_base_status.json"
    base_status_path.write_text(
        json.dumps({"refresh_base_status": {"contract_version": "learn_fusion_refresh_base_status_v1"}}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    tasks_path = path.parent / "generated_numbered_region_tasks.json"
    tasks_path.write_text(json.dumps({"regions": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_report = path.parent / "numbered_region_calibration_report.json"
    source_report.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "generated_tasks_path": str(tasks_path),
                "screenshot_path": "fixtures/screenshot.png",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_dir = path.parent / "artifacts"
    artifact_dir.mkdir(exist_ok=True)
    full_overlay = artifact_dir / "full_overlay.png"
    selection_overlay = artifact_dir / "selection_overlay.png"
    pathgraph_preview = artifact_dir / "runtime_path_graph_model_preview.json"
    page_detail = path.parent / "learn_page_detail_candidate.json"
    full_overlay.write_bytes(b"full-overlay")
    selection_overlay.write_bytes(b"selection-overlay")
    pathgraph_preview.write_text(json.dumps({"graph": "preview"}, ensure_ascii=False), encoding="utf-8")
    page_detail.write_text(
        json.dumps(
            {
                "contract_version": "learn_page_detail_candidate_v1",
                "layout_mode": "spatial_bbox_order",
                "readiness_status": "needs_pending_calibration",
                "layout": {
                    "sections": [
                        {
                            "section_id": "top_search",
                            "bbox": {"x": 10, "y": 20, "w": 100, "h": 30},
                            "region_count": 1,
                            "possible_operations": ["fill_field", "submit_search"],
                            "operation_summary": {
                                "kind_counts": {"fill_field": 1, "submit_search": 1},
                                "readiness_counts": {"blocked_pending_calibration": 1},
                            },
                            "regions": [
                                {"region_no": 1, "bbox": {"x": 10, "y": 20, "w": 100, "h": 30}},
                            ],
                        },
                        {
                            "section_id": "results",
                            "bbox": {"x": 10, "y": 80, "w": 200, "h": 120},
                            "region_count": 1,
                            "possible_operations": ["open_detail"],
                            "operation_summary": {
                                "kind_counts": {"open_detail": 1},
                                "readiness_counts": {"review_required": 1},
                            },
                            "regions": [
                                {"region_no": 2, "bbox": {"x": 10, "y": 80, "w": 200, "h": 120}},
                            ],
                        },
                    ],
                    "regions": [
                        {"region_no": 1, "bbox": {"x": 10, "y": 20, "w": 100, "h": 30}},
                        {"region_no": 2, "bbox": {"x": 10, "y": 80, "w": 200, "h": 120}},
                    ],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sidecar = path.parent / "learn_precise_understanding_candidate.json"
    sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_candidate_v1",
                "source_calibration_report_path": str(source_report),
                "full_screen_understanding_overlay_path": str(full_overlay),
                "compiled_overlay_path": str(selection_overlay),
                "summary": {"total_regions": 2, "pending_calibration_count": 2},
                "items": [
                    {
                        "region_no": 1,
                        "calibration_state": "pending_execute_dry_run_calibration",
                        "required_next_step": "run_execute_dry_run_calibration_for_numbered_region",
                    },
                    {
                        "region_no": 2,
                        "calibration_state": "pending_execute_dry_run_calibration",
                        "required_next_step": "run_execute_dry_run_calibration_for_numbered_region",
                    },
                    {
                        "region_no": 3,
                        "calibration_state": "review_before_calibration",
                        "required_next_step": "resolve_blocker_before_pathgraph_review",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    payload.setdefault("generated_artifacts", {})["precise_understanding_candidate_path"] = str(sidecar)
    payload["generated_artifacts"]["page_detail_candidate_path"] = str(page_detail)
    payload["current_evidence_packet"] = {
        "calibration": {
            "readiness_summary": {},
        },
        "evidence_integrity": {
            "source_status_report": {
                "path": str(base_status_path),
                "exists": True,
            }
        },
    }
    payload["model_generated_pathgraph_preview"] = {
        "source_path": str(trial_path),
        "runtime_path_graph_model_preview_path": str(pathgraph_preview),
        "summary": {
            "region_count": 2,
            "action_template_count": 3,
        },
        "page_detail_preview": {
            "summary": {
                "section_count": 2,
                "possible_operation_count": 3,
            }
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def test_learning_mode_demo_goal_readiness_separates_display_demo_from_final_goal(tmp_path: Path) -> None:
    candidate = _candidate_fixture(tmp_path)
    scaffold = build_learn_demo_scaffold(source_path=candidate, out_dir=candidate.parent, project_root=tmp_path)
    _force_pending_calibration(scaffold)

    report = report_learning_mode_demo_goal_readiness(
        scaffold_path=scaffold["report_path"],
        out_dir=candidate.parent,
        project_root=tmp_path,
    )

    assert report["contract_version"] == "learning_mode_demo_goal_readiness_v1"
    assert report["demo_goal_status"] == "display_demo_ready_official_goal_blocked"
    assert report["display_demo_ready"] is True
    assert report["final_goal_complete"] is False
    assert "official_candidate_not_fully_system_model_generated" in report["blocking_reasons"]
    assert report["summary"]["passed_requirement_count"] >= 5
    assert report["summary"]["failed_requirement_count"] >= 1
    assert report["next_action_status"] == "awaiting_explicit_model_start_approval"
    assert report["may_start_model_after_user_approval"] is True
    assert report["may_run_without_user_approval"] is False
    acceptance = report["fresh_model_chain_acceptance"]
    assert acceptance["contract_version"] == "learning_mode_fresh_model_chain_acceptance_v1"
    assert acceptance["accepted"] is False
    assert acceptance["acceptance_status"] == "blocked_mixed_or_assisted_evidence"
    assert acceptance["actual_model_call_evidence_count"] == 1
    assert acceptance["assisted_or_human_review_evidence_count"] == 2
    assert acceptance["source_breakdown"]["actual_model_call"] == 1
    assert acceptance["source_breakdown"]["assisted_or_human_review"] == 2
    assert "contains_assisted_or_human_review_evidence" in acceptance["blocking_reasons"]
    assert "pending_calibration_remaining" in acceptance["blocking_reasons"]
    assert acceptance["counts_as_final_goal_completion"] is False
    replacement_plan = acceptance["replacement_plan"]
    assert replacement_plan["contract_version"] == "learning_mode_fresh_model_chain_replacement_plan_v1"
    assert replacement_plan["replacement_required"] is True
    assert replacement_plan["plan_status"] == "blocked_until_explicit_model_start_approval"
    assert replacement_plan["current_source_breakdown"]["actual_model_call"] == 1
    assert replacement_plan["current_source_breakdown"]["assisted_or_human_review"] == 2
    assert replacement_plan["sources_to_replace"] == ["assisted_or_human_review"]
    assert replacement_plan["required_source_type"] == "actual_model_call"
    assert replacement_plan["counts_as_model_ability_when_complete"] is True
    assert replacement_plan["execute_binding_enabled"] is False
    assert replacement_plan["artifact_is_authorization"] is False
    assert replacement_plan["replacement_steps"][0]["step_id"] == "obtain_explicit_model_start_approval"
    assert replacement_plan["replacement_steps"][1]["step_id"] == "run_fresh_numbered_region_calibration"
    assert replacement_plan["replacement_steps"][1]["command_executes_now"] is False
    assert replacement_plan["replacement_steps"][2]["step_id"] == "refresh_model_generated_scaffold"
    assert replacement_plan["replacement_steps"][3]["step_id"] == "rerun_goal_readiness_audit"
    evidence_map = {item["stage_id"]: item for item in report["demo_evidence_map"]}
    assert evidence_map["full_screen_understanding_numbered_regions"]["artifact_path"].endswith("full_overlay.png")
    assert evidence_map["full_screen_understanding_numbered_regions"]["artifact_exists"] is True
    assert len(evidence_map["full_screen_understanding_numbered_regions"]["artifact_sha256_prefix"]) == 12
    assert evidence_map["selection_map_precise_understanding"]["artifact_path"].endswith("selection_overlay.png")
    assert evidence_map["selection_map_precise_understanding"]["artifact_exists"] is True
    assert len(evidence_map["selection_map_precise_understanding"]["artifact_sha256_prefix"]) == 12
    assert evidence_map["pathgraph_model_preview"]["artifact_path"].endswith("runtime_path_graph_model_preview.json")
    assert evidence_map["pathgraph_model_preview"]["artifact_exists"] is True
    assert len(evidence_map["pathgraph_model_preview"]["artifact_sha256_prefix"]) == 12
    assert evidence_map["template_like_page_detail"]["status"] == "available"
    assert evidence_map["template_like_page_detail"]["artifact_exists"] is True
    assert len(evidence_map["template_like_page_detail"]["artifact_sha256_prefix"]) == 12
    assert evidence_map["template_like_page_detail"]["section_count"] == 2
    assert evidence_map["template_like_page_detail"]["possible_operation_count"] == 3
    assert evidence_map["template_like_page_detail"]["layout_mode"] == "spatial_bbox_order"
    assert evidence_map["template_like_page_detail"]["readiness_status"] == "needs_pending_calibration"
    assert evidence_map["template_like_page_detail"]["layout_section_count"] == 2
    assert evidence_map["template_like_page_detail"]["bbox_region_count"] == 2
    assert evidence_map["template_like_page_detail"]["operation_kinds"] == [
        "fill_field",
        "open_detail",
        "submit_search",
    ]
    assert evidence_map["template_like_page_detail"]["layout_section_summaries"] == [
        {
            "section_id": "top_search",
            "bbox": {"x": 10, "y": 20, "w": 100, "h": 30},
            "region_count": 1,
            "possible_operations": ["fill_field", "submit_search"],
            "operation_summary": {
                "kind_counts": {"fill_field": 1, "submit_search": 1},
                "readiness_counts": {"blocked_pending_calibration": 1},
            },
        },
        {
            "section_id": "results",
            "bbox": {"x": 10, "y": 80, "w": 200, "h": 120},
            "region_count": 1,
            "possible_operations": ["open_detail"],
            "operation_summary": {
                "kind_counts": {"open_detail": 1},
                "readiness_counts": {"review_required": 1},
            },
        },
    ]
    assert all(item["display_only"] is True for item in report["demo_evidence_map"])
    assert all(item["artifact_is_authorization"] is False for item in report["demo_evidence_map"])
    chain_manifest = report["demo_chain_manifest"]
    assert chain_manifest["contract_version"] == "learning_mode_demo_chain_manifest_v1"
    assert chain_manifest["chain_can_be_demoed"] is True
    assert chain_manifest["chain_is_final_goal_complete"] is False
    assert chain_manifest["demo_stage_order"] == [
        "full_screen_understanding_numbered_regions",
        "selection_map_precise_understanding",
        "pathgraph_model_preview",
        "template_like_page_detail",
    ]
    assert chain_manifest["final_goal_blockers"] == report["blocking_reasons"]
    chain_steps = {item["stage_id"]: item for item in chain_manifest["steps"]}
    assert chain_steps["selection_map_precise_understanding"]["proof_fields"] == [
        "artifact_sha256_prefix",
        "region_count",
    ]
    assert chain_steps["pathgraph_model_preview"]["proof_fields"] == [
        "action_count",
        "artifact_sha256_prefix",
        "region_count",
    ]
    assert chain_steps["template_like_page_detail"]["proof_fields"] == [
        "artifact_sha256_prefix",
        "bbox_region_count",
        "layout_mode",
        "layout_section_count",
        "operation_kinds",
        "readiness_status",
    ]
    assert all(item["stage_ready_for_display"] is True for item in chain_manifest["steps"])
    assert all(item["execute_binding_enabled"] is False for item in chain_manifest["steps"])
    next_actions = {item["action_id"]: item for item in report["next_actions"]}
    assert next_actions["request_explicit_model_start_approval"]["status"] == "required"
    assert next_actions["run_pending_numbered_region_calibration_batch"]["requires_user_approval"] is True
    assert next_actions["run_pending_numbered_region_calibration_batch"]["ready_region_numbers"] == [1, 2]
    assert next_actions["run_pending_numbered_region_calibration_batch"]["command_executes_now"] is False
    assert next_actions["run_pending_numbered_region_calibration_batch"]["start_model_flag_included"] is False
    assert next_actions["run_pending_numbered_region_calibration_batch"]["requires_user_or_runner_to_start_model"] is True
    assert "scripts\\run_numbered_region_calibration_probe.py" in next_actions[
        "run_pending_numbered_region_calibration_batch"
    ]["run_command_preview"]
    assert "--regions 1,2" in next_actions["run_pending_numbered_region_calibration_batch"]["run_command_preview"]
    assert next_actions["refresh_scaffold_after_calibration"]["status"] == "blocked_until_calibration_output"
    assert next_actions["refresh_scaffold_after_calibration"]["command_executes_now"] is False
    assert next_actions["refresh_scaffold_after_calibration"]["requires_completed_batch_output"] is True
    assert "scripts\\refresh_learn_fusion_after_calibration_batch.py" in next_actions[
        "refresh_scaffold_after_calibration"
    ]["run_command_preview"]
    assert "--trial" in next_actions["refresh_scaffold_after_calibration"]["run_command_preview"]
    assert "--base-status" in next_actions["refresh_scaffold_after_calibration"]["run_command_preview"]
    assert "--rerun-report" in next_actions["refresh_scaffold_after_calibration"]["run_command_preview"]
    assert next_actions["rerun_goal_readiness_audit"]["status"] == "blocked_until_scaffold_refresh"
    requirements = {item["requirement_id"]: item for item in report["requirements"]}
    assert requirements["full_screen_understanding_numbered_regions"]["status"] == "passed"
    assert requirements["selection_map_available"]["status"] == "passed"
    assert requirements["pathgraph_preview_available"]["status"] == "passed"
    assert requirements["pathgraph_opens_page_detail"]["status"] == "passed"
    assert requirements["template_like_page_detail_layout"]["status"] == "passed"
    assert requirements["model_only_demo_chain_ready"]["status"] == "passed"
    assert requirements["official_candidate_fully_system_model_generated"]["status"] == "failed"
    assert requirements["no_execute_no_submit_safety"]["status"] == "passed"
    assert report["safety"]["model_started"] is False
    assert report["safety"]["live_clicks"] == 0
    assert report["safety"]["live_submits"] == 0
    assert Path(report["report_path"]).exists()

    saved = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))
    assert saved["demo_goal_status"] == report["demo_goal_status"]

    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)
    loaded = review["pathgraph_candidate_review"]["learning_mode_demo_goal_readiness"]
    assert loaded["contract_version"] == "learning_mode_demo_goal_readiness_v1"
    assert loaded["demo_goal_status"] == "display_demo_ready_official_goal_blocked"
    summary = review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["learning_mode_demo_goal_readiness"]
    assert summary["display_demo_ready"] is True
    assert summary["final_goal_complete"] is False


def test_learning_mode_demo_goal_readiness_endpoint_is_review_only(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    candidate = _candidate_fixture(tmp_path)
    scaffold = build_learn_demo_scaffold(source_path=candidate, out_dir=candidate.parent, project_root=tmp_path)
    _force_pending_calibration(scaffold)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/create_learning_demo_goal_readiness",
        json={"scaffold_path": str(Path(scaffold["report_path"]).relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "learning_mode_demo_goal_readiness_v1"
    assert data["demo_goal_status"] == "display_demo_ready_official_goal_blocked"
    assert data["display_demo_ready"] is True
    assert data["final_goal_complete"] is False
    assert data["next_action_status"] == "awaiting_explicit_model_start_approval"
    assert data["may_run_without_user_approval"] is False
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["live_submits"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["trace_path"]
