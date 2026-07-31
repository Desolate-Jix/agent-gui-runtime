from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.learn.draft_review import load_learning_draft_review
from app.main import app
from scripts import build_learn_demo_scaffold as scaffold_module
from scripts.build_learn_demo_scaffold import build_learn_demo_scaffold


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _candidate_fixture(tmp_path: Path) -> Path:
    actual_source = _write_json(
        tmp_path / "logs" / "benchmarks" / "fresh_model" / "actual_parser_output_with_fusion_status.json",
        {
            "contract_version": "actual_parser_output_v1",
            "source_type": "actual_parser_call",
            "actual_model_call_in_this_run": True,
            "screenshot_path": "artifacts/screen.png",
            "screenshot_sha256": "abc123",
            "learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results demo",
                "state_guess": "seek_results",
                "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                "regions": [
                    {
                        "region_id": "search_input",
                        "label": "Search input",
                        "role": "input",
                        "bbox": {"x": 20, "y": 20, "width": 220, "height": 40},
                    }
                ],
                "action_templates": [
                    {
                        "action_template_id": "fill_search_input",
                        "label": "Fill search input",
                        "action_type": "input",
                        "target_entity": "search_input",
                    }
                ],
            },
        },
    )
    reviewed = _write_json(
        tmp_path / "artifacts" / "candidate" / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "source": {
                "source_path": str(actual_source.relative_to(tmp_path)),
                "original_draft_path": str(actual_source.relative_to(tmp_path)),
            },
            "source_after_review": "assisted_generation",
            "counts_as_pure_model_generated": False,
            "reviewed_by_human": True,
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results demo",
                "state_guess": "seek_results",
                "page_details": {
                    "screen": {
                        "precise_understanding_fusion_status": {
                            "evidence_integrity": {
                                "source_calibration_report": {
                                    "path": "logs/benchmarks/calibration/fusion_status.json",
                                }
                            },
                            "precise_understanding_readiness_summary": {
                                "readiness_status": "needs_pending_calibration",
                                "calibration_coverage_rate": 0.25,
                            },
                            "calibration_backlog_items": [
                                {
                                    "region_no": 1,
                                    "source_item_id": "search",
                                    "label": "Search input",
                                    "role": "input",
                                    "rough_bbox_hint": {"x": 20, "y": 20, "w": 220, "h": 40},
                                }
                            ],
                            "calibration_batch_ready_region_numbers": [1],
                            "calibration_batch_review_blocked_region_numbers": [],
                        }
                    }
                },
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    validation = _write_json(
        tmp_path / "artifacts" / "candidate" / "promotion_validation_report.json",
        {
            "contract_version": "pathgraph_candidate_validation_report_v1",
            "validation_status": "blocked_pending_calibration",
            "summary": {},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    _write_json(
        tmp_path / "logs" / "benchmarks" / "calibration" / "fusion_status.json",
        {
            "contract_version": "learn_precise_understanding_fusion_status_v1",
            "screenshot_path": "artifacts/screen.png",
            "summary": {"attempted": 1},
            "fused_precise_understanding": {
                "items": [
                    {
                        "region_no": 1,
                        "source_item_id": "search",
                        "label": "Search input",
                        "role": "input",
                        "rough_bbox_hint": {"x": 20, "y": 20, "w": 220, "h": 40},
                    }
                ]
            },
        },
    )
    return _write_json(
        tmp_path / "artifacts" / "candidate" / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_report_path": str(validation.relative_to(tmp_path)),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )


def test_learning_demo_scaffold_refreshes_review_sidecars(tmp_path: Path) -> None:
    candidate = _candidate_fixture(tmp_path)

    result = build_learn_demo_scaffold(source_path=candidate, out_dir=candidate.parent, project_root=tmp_path)

    assert result["contract_version"] == "learn_mode_demo_scaffold_v1"
    assert result["summary"]["artifact_count"] == 5
    assert result["summary"]["failure_count"] == 0
    assert result["summary"]["actual_model_call_evidence_count"] == 1
    assert result["summary"]["assisted_or_human_review_evidence_count"] >= 1
    assert result["model_provenance_audit"]["status"] == "mixed_actual_model_and_assisted_review_evidence"
    assert result["model_provenance_audit"]["meets_fully_model_generated_demo_requirement"] is False
    assert "contains_assisted_or_human_review_evidence" in result["model_provenance_audit"]["blocking_reasons"]
    assert result["summary"]["model_generated_pathgraph_preview_status"] == "model_generated_preview_ready"
    assert result["summary"]["model_generated_pathgraph_preview_region_count"] >= 0
    assert result["summary"]["model_generated_page_detail_section_count"] >= 1
    assert result["summary"]["model_generated_page_detail_possible_operation_count"] >= 1
    assert result["page_detail_candidate"]["contract_version"] == "learn_page_detail_candidate_v1"
    assert result["page_detail_candidate"]["layout"]["sections"]
    correspondence = result["page_detail_pathgraph_correspondence"]
    assert correspondence["contract_version"] == "learn_page_detail_pathgraph_correspondence_v1"
    assert correspondence["display_only"] is True
    assert correspondence["execute_binding_enabled"] is False
    assert correspondence["artifact_is_authorization"] is False
    assert correspondence["page_detail_candidate_available"] is True
    assert correspondence["pathgraph_preview_available"] is True
    assert correspondence["shared_section_ids"]
    for section in correspondence["pathgraph_preview_sections"]:
        bbox = section["bbox"]
        assert set(bbox) >= {"x", "y", "w", "h"}
        assert bbox["w"] > 0
        assert bbox["h"] > 0
    assert result["display_readiness"]["page_detail_pathgraph_correspondence_ready"] is True
    model_preview = result["model_generated_pathgraph_preview"]
    assert model_preview["page_detail_preview"]["contract_version"] == "model_generated_page_detail_preview_v1"
    assert model_preview["page_detail_preview"]["summary"]["region_count"] >= 1
    assert model_preview["page_detail_preview"]["summary"]["possible_operation_count"] >= 1
    sections = [item["section_id"] for item in model_preview["page_detail_preview"]["layout"]["sections"]]
    assert "top_search_and_filters" in sections
    assert result["display_readiness"]["model_generated_pathgraph_preview_available"] is True
    assert result["display_readiness"]["model_only_demo_ready"] is True
    assert result["model_only_demo_readiness"]["status"] == "model_only_demo_ready"
    assert result["model_only_demo_readiness"]["ready"] is True
    assert result["model_only_demo_readiness"]["official_candidate_fully_model_generated"] is False
    assert result["display_readiness"]["pathgraph_detail_can_show_page_detail"] is True
    assert result["display_readiness"]["meets_fully_model_generated_demo_requirement"] is False
    assert result["safety"]["model_started"] is False
    assert result["safety"]["runtime_pathgraph_promotion"] is False
    assert (candidate.parent / "learn_precise_understanding_candidate.json").exists()
    assert (candidate.parent / "learn_page_detail_candidate.json").exists()
    assert (candidate.parent / "learn_fusion_current_evidence_packet.json").exists()
    assert (candidate.parent / "learn_fusion_pathgraph_integration_readiness_report.json").exists()
    assert (candidate.parent / "model_generated_pathgraph_preview" / "model_generated_pathgraph_preview.json").exists()
    assert Path(result["report_path"]).exists()

    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)
    scaffold = review["pathgraph_candidate_review"]["learn_mode_demo_scaffold"]
    assert scaffold["contract_version"] == "learn_mode_demo_scaffold_v1"
    summary_scaffold = review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["learn_mode_demo_scaffold"]
    assert summary_scaffold["summary"]["artifact_count"] == 5


def test_learning_demo_scaffold_can_be_loaded_from_external_output_dir(tmp_path: Path) -> None:
    candidate = _candidate_fixture(tmp_path)
    out_dir = tmp_path / "logs" / "benchmarks" / "fresh_demo_scaffold"

    result = build_learn_demo_scaffold(source_path=candidate, out_dir=out_dir, project_root=tmp_path)

    assert Path(result["report_path"]).parent == out_dir
    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)
    candidate_review = review["pathgraph_candidate_review"]
    assert candidate_review["learn_mode_demo_scaffold"]["contract_version"] == "learn_mode_demo_scaffold_v1"
    assert candidate_review["page_detail_candidate"]["contract_version"] == "learn_page_detail_candidate_v1"
    assert candidate_review["learn_mode_demo_scaffold"]["report_path"] == str(out_dir / "learn_mode_demo_scaffold.json")
    assert candidate_review["page_detail_candidate"]["report_path"] == str(out_dir / "learn_page_detail_candidate.json")


def test_learning_demo_scaffold_can_attach_to_direct_learning_draft_source(tmp_path: Path) -> None:
    candidate = _candidate_fixture(tmp_path)
    actual_source = tmp_path / "logs" / "benchmarks" / "fresh_model" / "actual_parser_output_with_fusion_status.json"
    out_dir = tmp_path / "logs" / "benchmarks" / "direct_demo_scaffold"

    result = build_learn_demo_scaffold(source_path=actual_source, out_dir=out_dir, project_root=tmp_path)

    assert result["source_path"] == str(actual_source.relative_to(tmp_path)).replace("\\", "/")
    review = load_learning_draft_review(actual_source.relative_to(tmp_path), project_root=tmp_path)
    candidate_review = review["pathgraph_candidate_review"]
    assert candidate_review["contract_version"] == "learning_demo_artifact_review_v1"
    assert candidate_review["learn_mode_demo_scaffold"]["contract_version"] == "learn_mode_demo_scaffold_v1"
    assert candidate_review["page_detail_candidate"]["contract_version"] == "learn_page_detail_candidate_v1"
    assert candidate_review["pathgraph_readiness_summary"]["learn_mode_demo_scaffold"]["summary"][
        "model_generated_pathgraph_preview_status"
    ] == "model_generated_preview_ready"


def test_learning_demo_scaffold_can_load_direct_page_detail_candidate(tmp_path: Path) -> None:
    candidate = _write_json(
        tmp_path / "logs" / "benchmarks" / "page_detail" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "source_identity": {
                "contract_version": "learning_repaired_source_identity_v1",
                "final_numbering_revision": "final-revision",
                "compiled_overlay_path": "artifacts/review-overlays/qq_reviewed.png",
                "dual_stream_contract": "learn_stage2_dual_streams_v1",
            },
            "source_path": "logs/benchmarks/two_stage/trial_result.json",
            "source_detail_shape": "learn_two_stage_screen_understanding_v1",
            "readiness_status": "needs_page_detail_review",
            "summary": {
                "region_count": 1,
                "section_count": 1,
                "possible_operation_count": 1,
                "display_group_count": 1,
                "display_only": True,
                "execute_binding_enabled": False,
                "runtime_pathgraph_promotion": False,
            },
            "layout": {
                "bounds": {"x": 10, "y": 20, "w": 300, "h": 200},
                "sections": [
                    {
                        "section_id": "main_content",
                        "label": "Main content",
                        "bbox": {"x": 10, "y": 20, "w": 300, "h": 200},
                        "region_count": 1,
                        "possible_operations": ["read_only"],
                    }
                ],
                "regions": [
                    {
                        "region_id": "main_card",
                        "label": "Main card",
                        "source_section_id": "main_content",
                        "bbox": {"x": 40, "y": 60, "w": 120, "h": 80},
                        "possible_operation": {"operation_type": "read_only"},
                    }
                ],
                "display_groups": [
                    {
                        "group_id": "main_group",
                        "role": "list_group",
                        "label": "Main group",
                        "bbox": {"x": 35, "y": 55, "w": 130, "h": 90},
                        "member_region_numbers": [1],
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                ],
            },
            "safety": {
                "display_only": True,
                "model_started": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
                "execute_binding_enabled": False,
                "runtime_pathgraph_promotion": False,
            },
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    out_dir = tmp_path / "logs" / "benchmarks" / "page_detail_scaffold"

    result = build_learn_demo_scaffold(source_path=candidate, out_dir=out_dir, project_root=tmp_path)

    assert result["summary"]["failure_count"] == 0
    assert result["summary"]["skipped_count"] >= 3
    assert result["summary"]["page_detail_region_count"] == 1
    assert result["summary"]["page_detail_section_count"] == 1
    assert result["summary"]["page_detail_display_group_count"] == 1
    assert result["summary"]["page_detail_readonly_pathgraph_preview_status"] == "page_detail_readonly_preview_ready"
    assert result["summary"]["page_detail_readonly_pathgraph_preview_region_count"] == 1
    assert result["summary"]["page_detail_readonly_pathgraph_preview_display_group_count"] == 1
    assert result["page_detail_candidate"]["contract_version"] == "learn_page_detail_candidate_v1"
    readonly_preview = result["page_detail_readonly_pathgraph_preview"]
    assert readonly_preview["contract_version"] == "page_detail_readonly_pathgraph_preview_v1"
    assert readonly_preview["preview_status"] == "page_detail_readonly_preview_ready"
    assert readonly_preview["page_detail_preview"]["layout"]["display_groups"][0]["group_id"] == "main_group"
    assert readonly_preview["runtime_pathgraph_promotion"] is False
    assert readonly_preview["execute_binding_enabled"] is False
    assert result["source_identity"]["final_numbering_revision"] == "final-revision"
    assert readonly_preview["source_identity"] == result["source_identity"]
    assert readonly_preview["readonly_path_graph_preview"]["source_identity"] == result["source_identity"]
    assert result["display_readiness"]["same_repaired_source_verified"] is True
    assert result["generated_artifacts"]["page_detail_candidate_path"] == str(candidate.relative_to(tmp_path)).replace(
        "\\", "/"
    )
    assert result["generated_artifacts"]["page_detail_readonly_pathgraph_preview_path"].endswith(
        "page_detail_readonly_pathgraph_preview/page_detail_readonly_pathgraph_preview.json"
    )
    skipped = {item["step_id"]: item for item in result["failures"] if item["status"] == "skipped"}
    assert skipped["precise_understanding_candidate"]["reason"] == "source_is_page_detail_candidate"
    assert skipped["current_evidence_packet"]["reason"] == "source_is_page_detail_candidate"
    flow_status = {item["step_id"]: item["status"] for item in result["flow"]}
    assert flow_status["full_screen_understanding_numbered_regions"] == "skipped_source_is_page_detail_candidate"
    assert flow_status["precise_understanding_candidate"] == "skipped_source_is_page_detail_candidate"
    assert flow_status["page_detail_readonly_pathgraph_preview"] == "page_detail_readonly_preview_ready"
    assert flow_status["template_like_page_detail"] == "needs_page_detail_review"
    assert result["display_readiness"]["pathgraph_detail_can_show_page_detail"] is True
    assert result["display_readiness"]["template_like_layout_available"] is True
    assert result["display_readiness"]["page_detail_readonly_pathgraph_preview_available"] is True
    assert result["page_detail_pathgraph_correspondence"]["correspondence_status"] == "layout_correspondence_available"
    assert result["page_detail_pathgraph_correspondence"]["pathgraph_preview_available"] is True
    assert result["page_detail_pathgraph_correspondence"]["shared_display_group_ids"] == ["main_group"]
    assert result["safety"]["model_started"] is False
    assert result["safety"]["live_clicks"] == 0
    assert result["safety"]["runtime_pathgraph_promotion"] is False
    assert Path(result["report_path"]).exists()


def test_model_provenance_follows_page_detail_source_path_to_actual_trial(tmp_path: Path) -> None:
    trial = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "panel_run" / "trial_result.json",
        {
            "contract_version": "learn_recognition_pipeline_result_v1",
            "source_type": "panel_observe_coordinate_evidence",
            "actual_model_call_in_this_run": True,
            "model_generated": True,
            "best_learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "states": [],
                "regions": [],
                "action_templates": [],
            },
        },
    )
    page_detail = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "panel_run" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "source_path": str(trial.relative_to(tmp_path)),
        },
    )

    audit = scaffold_module._model_provenance_audit(
        source_file=page_detail,
        review={},
        root=tmp_path,
    )

    assert audit["actual_model_call_evidence_count"] == 1
    assert audit["status"] == "fresh_model_generated_chain_evidence_present"
    assert audit["evidence"][1]["path"] == str(trial.relative_to(tmp_path)).replace("\\", "/")


def test_learning_demo_scaffold_endpoint_is_review_only(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    candidate = _candidate_fixture(tmp_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/create_learning_demo_scaffold",
        json={"source_path": str(candidate.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "learn_mode_demo_scaffold_v1"
    assert data["summary"]["artifact_count"] == 5
    assert data["summary"]["model_generated_pathgraph_preview_status"] == "model_generated_preview_ready"
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["safety"]["runtime_pathgraph_promotion"] is False
    assert data["trace_path"]


def test_learning_demo_scaffold_endpoint_accepts_page_detail_candidate(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    page_detail = _write_json(
        tmp_path / "logs" / "benchmarks" / "page_detail" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "readiness_status": "needs_page_detail_review",
            "summary": {"region_count": 1, "section_count": 1, "possible_operation_count": 1},
            "layout": {
                "bounds": {"x": 0, "y": 0, "w": 200, "h": 100},
                "sections": [
                    {
                        "section_id": "main_content",
                        "label": "Main content",
                        "bbox": {"x": 0, "y": 0, "w": 200, "h": 100},
                        "region_count": 1,
                    }
                ],
                "regions": [
                    {
                        "region_id": "main_card",
                        "label": "Main card",
                        "source_section_id": "main_content",
                        "bbox": {"x": 10, "y": 20, "w": 80, "h": 40},
                        "possible_operation": {"operation_type": "read_only"},
                    }
                ],
            },
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/create_learning_demo_scaffold",
        json={"source_path": str(page_detail.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["summary"]["failure_count"] == 0
    assert data["summary"]["page_detail_section_count"] == 1
    assert data["display_readiness"]["pathgraph_detail_can_show_page_detail"] is True
    skipped = {item["step_id"]: item for item in data["failures"] if item["status"] == "skipped"}
    assert skipped["precise_understanding_candidate"]["reason"] == "source_is_page_detail_candidate"
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["runtime_pathgraph_promotion"] is False
