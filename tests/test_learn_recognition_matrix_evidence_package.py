from __future__ import annotations

import json
from pathlib import Path

from app.learn.draft_review import load_learning_draft_review
from scripts.build_learn_recognition_matrix_evidence_package import build_matrix_evidence_package


def test_matrix_evidence_package_loads_as_reviewable_learning_draft(tmp_path: Path) -> None:
    matrix_path, batch_path = _write_matrix_fixture(tmp_path)

    result = build_matrix_evidence_package(
        matrix_report_path=matrix_path,
        model_profile_id="learn_mode_uground_2b",
        out_dir=tmp_path / "artifacts" / "out",
        project_root=tmp_path,
    )

    package_path = tmp_path / result["package_path"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    review = load_learning_draft_review(package_path, project_root=tmp_path)

    assert result["case_count"] == 2
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert package["contract_version"] == "learn_recognition_matrix_evidence_package_v1"
    assert package["matrix_evidence"]["batch_report_path"] == batch_path.relative_to(tmp_path).as_posix()
    assert package["best_learning_draft"]["learning_source"] == "actual_call_matrix_evidence"
    assert review["draft_only"] is True
    assert review["execute_binding_enabled"] is False
    assert review["draft"]["states"]
    assert len(review["draft"]["regions"]) == 2
    assert len(review["draft"]["action_templates"]) == 2
    assert review["draft"]["blockers"]
    assert review["draft"]["verification_rules"]


def test_matrix_evidence_package_can_generate_display_only_pathgraph_candidate(tmp_path: Path) -> None:
    matrix_path, _batch_path = _write_matrix_fixture(tmp_path)

    result = build_matrix_evidence_package(
        matrix_report_path=matrix_path,
        model_profile_id="learn_mode_uground_2b",
        out_dir=tmp_path / "artifacts" / "out",
        generate_pathgraph_candidate=True,
        project_root=tmp_path,
    )

    candidate = result["generated_pathgraph_candidate"]
    assert candidate["artifact_is_authorization"] is False
    assert candidate["execute_binding_enabled"] is False
    assert candidate["final_submit_forbidden"] is True
    assert candidate["validation_status"] == "passed_candidate"
    assert (tmp_path / candidate["pathgraph_candidate_path"]).exists()
    assert (tmp_path / candidate["runtime_path_graph_candidate_path"]).exists()


def _write_matrix_fixture(root: Path) -> tuple[Path, Path]:
    batch_dir = root / "logs" / "batch"
    batch_dir.mkdir(parents=True)
    batch_path = batch_dir / "learn_actual_grounding_smoke_batch_report.json"
    batch_path.write_text(
        json.dumps(
            {
                "case_reports": [
                    _case("Search keyword field", "seek_results", 100, 20),
                    _case("Pay filter", "seek_results", 280, 20),
                    {
                        "case_id": "blocked",
                        "label": "Submit application",
                        "status": "blocked",
                        "actual_model_call_in_this_run": False,
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    matrix_path = root / "logs" / "matrix_report.json"
    matrix_path.write_text(
        json.dumps(
            {
                "matrix_summary": {
                    "rows": [
                        {
                            "model_profile_id": "learn_mode_uground_2b",
                            "batch_report_path": batch_path.relative_to(root).as_posix(),
                            "actual_model_call": {
                                "passed": 2,
                                "attempted": 2,
                                "rate": 1.0,
                            },
                            "total_status": {
                                "passed": 2,
                                "failed": 0,
                                "blocked": 1,
                            },
                            "blocked_categories": {"fixture_precondition_failed": 1},
                            "actual_grounding_failure_categories": {},
                        }
                    ],
                    "interpretation": "test matrix",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return matrix_path, batch_path


def _case(label: str, surface: str, x: int, y: int) -> dict:
    return {
        "case_id": f"case_{label}",
        "label": label,
        "status": "passed",
        "actual_model_call_in_this_run": True,
        "screenshot_path": "artifacts/screen.png",
        "roi_image_path": "artifacts/roi.png",
        "actual_grounding_output_path": "logs/out.json",
        "raw_model_output": "(500, 500)",
        "batch_case": {"surface": surface},
        "validation": {
            "status": "valid_candidate",
            "screen_bbox": {"x": x, "y": y, "w": 80, "h": 30},
            "screen_point": {"x": x + 40, "y": y + 15},
        },
        "point_quality": {
            "status": "passed_inside_expected_bbox",
            "roi_point_source": "restored_local_point",
        },
        "normalized_grounding": {
            "point": {"x": x + 40, "y": y + 15, "coordinate_space": "screen"},
        },
    }
