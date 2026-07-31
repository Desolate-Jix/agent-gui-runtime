from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

from app.learn.recognition.review_adjudication import score_review_adjudication
from scripts.run_learning_model_review_validation import run_validation


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_human_adjudication_can_match_missing_repair_by_role_and_expected_geometry() -> None:
    score = score_review_adjudication(
        adjudication={
            "contract_version": "learning_model_review_human_adjudication_v1",
            "scope": "review_layer_only",
            "expected_group_decisions": [],
            "expected_missing_targets": [
                {
                    "expected_role": "content_region",
                    "expected_roi": {"x": 250, "y": 110, "w": 700, "h": 540},
                    "min_expected_coverage": 0.8,
                }
            ],
        },
        validated_patch={
            "missing": [
                {
                    "expected_role": "content_region",
                    "rough_roi": {"x": 258, "y": 113, "w": 692, "h": 537},
                }
            ]
        },
        final_stage2={
            "regions": [
                {
                    "subregion_groups": [
                        {
                            "group_id": "model_review_missing_1_deterministic_region",
                            "role": "content_region",
                            "bbox": {"x": 258, "y": 113, "w": 692, "h": 537},
                        }
                    ]
                }
            ]
        },
        integrity_gate={
            "source_atomic_count": 10,
            "final_atomic_count": 10,
            "failure_categories": [],
        },
    )

    assert score["quality_gate_passed"] is True
    assert score["metrics"]["missing_region_detection"]["passed"] == 1
    assert score["metrics"]["missing_region_recovery"]["passed"] == 1


def test_human_adjudication_reads_wrapped_final_stage2_numbering() -> None:
    score = score_review_adjudication(
        adjudication={
            "contract_version": "learning_model_review_human_adjudication_v1",
            "scope": "review_layer_only",
            "expected_group_decisions": [],
            "expected_missing_targets": [
                {
                    "expected_role": "content_region",
                    "expected_roi": {"x": 250, "y": 110, "w": 700, "h": 540},
                    "min_expected_coverage": 0.8,
                }
            ],
        },
        validated_patch={
            "missing": [
                {
                    "expected_role": "content_region",
                    "rough_roi": {"x": 258, "y": 113, "w": 718, "h": 550},
                }
            ]
        },
        final_stage2={
            "contract_version": "learning_draft_v1",
            "stage2_numbering": {
                "contract_version": "learn_stage2_numbering_v1",
                "regions": [
                    {
                        "subregion_groups": [
                            {
                                "group_id": "model_review_missing_1_deterministic_region",
                                "role": "content_region",
                                "bbox": {"x": 258, "y": 113, "w": 718, "h": 550},
                            }
                        ]
                    }
                ],
            },
        },
        integrity_gate={
            "source_atomic_count": 10,
            "final_atomic_count": 10,
            "failure_categories": [],
        },
    )

    assert score["quality_gate_passed"] is True
    assert score["metrics"]["missing_region_recovery"]["passed"] == 1


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    screenshot = tmp_path / "original.png"
    root_partition = tmp_path / "root_partition.png"
    overlay = tmp_path / "before.png"
    stage2 = tmp_path / "stage2.json"
    Image.new("RGB", (160, 120), "white").save(screenshot)
    Image.new("RGB", (160, 120), "black").save(root_partition)
    Image.new("RGB", (160, 120), "gray").save(overlay)
    stage2.write_text(
        json.dumps(
            {
                "two_stage_understanding": {
                    "stage2_numbering": {
                        "regions": [
                            {
                                "region_id": "root",
                                "bbox": {"x": 0, "y": 0, "w": 160, "h": 120},
                                "numbered_items": [],
                                "subregion_groups": [],
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return screenshot, root_partition, overlay, stage2


def _manifest(
    tmp_path: Path,
    *,
    screenshot_sha256: str | None = None,
    human_adjudication: dict[str, Any] | None = None,
) -> Path:
    screenshot, root_partition, overlay, stage2 = _fixture(tmp_path)
    adjudication_path = tmp_path / "human_adjudication.json"
    if human_adjudication is not None:
        adjudication_path.write_text(json.dumps(human_adjudication), encoding="utf-8")
    manifest = {
        "contract_version": "learning_model_review_validation_manifest_v1",
        "suite_id": "three_case_development_validation",
        "suite_type": "development_validation",
        "used_for_tuning": True,
        "cases": [
            {
                "case_id": "notepad_sparse_negative",
                "surface_family": "sparse_editor",
                "stage2_json_path": str(stage2),
                "stage2_sha256": _sha256(stage2),
                "screenshot_path": str(screenshot),
                "screenshot_sha256": screenshot_sha256 or _sha256(screenshot),
                "root_partition_overlay_path": str(root_partition),
                "root_partition_overlay_sha256": _sha256(root_partition),
                "composite_overlay_path": str(overlay),
                "composite_overlay_sha256": _sha256(overlay),
                **(
                    {
                        "human_adjudication_path": str(adjudication_path),
                        "human_adjudication_sha256": _sha256(adjudication_path),
                    }
                    if human_adjudication is not None
                    else {}
                ),
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_validation_runner_requires_actual_model_evidence_and_three_images(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)

    def probe_runner(**kwargs: Any) -> dict[str, Any]:
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        validated_patch = out_dir / "validated_review_patch.json"
        validated_patch.write_text(
            json.dumps({"group_reviews": [], "missing": [], "needs_human_review": []}),
            encoding="utf-8",
        )
        before = out_dir / "before_review_fusion.png"
        Image.new("RGB", (160, 120), "gray").save(before)
        raw = out_dir / "raw_model_output.txt"
        raw.write_text('{"group_reviews":[],"missing":[]}', encoding="utf-8")
        prompt = out_dir / "prompt.txt"
        prompt.write_text("review", encoding="utf-8")
        return {
            "actual_model_call": True,
            "source_type": "actual_model_call",
            "validated_review_patch_path": str(validated_patch),
            "before_review_overlay_path": str(before),
            "raw_model_output_path": str(raw),
            "prompt_path": str(prompt),
            "prompt_version": "learning_overlay_model_review_prompt_v2",
            "schema_version": "learning_model_review_patch_v1",
            "parser_version": "learning_model_review_parser_v1",
            "model_name": "test-model",
            "inference_parameters": {"temperature": 0.0},
            "workflow_state": "completed_review_only",
            "completed_review_only": True,
        }

    def closure_runner(**kwargs: Any) -> dict[str, Any]:
        final = Path(kwargs["out_path"]).parent / "final_repaired_fusion.png"
        final.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (160, 120), "white").save(final)
        source = json.loads(Path(kwargs["stage2_source_path"]).read_text(encoding="utf-8"))
        recomposed = source["two_stage_understanding"]["stage2_numbering"]
        return {
            "workflow_state": "completed_review_only",
            "completed_review_only": True,
            "final_repaired_overlay_path": str(final),
            "source_graph_revision": "source-revision",
            "final_graph_revision": "final-revision",
            "deterministic_repair_failed": 0,
            "final_workflow": {
                "workflow_state": "completed_review_only",
                "recomposed_stage2": recomposed,
                "replacement_integrity_gate": {
                    "passed": True,
                    "failure_categories": [],
                    "needs_human_review": 0,
                },
                "repair_pending_count": 0,
            },
            "safety": {"real_clicks": 0, "live_fills": 0, "live_submits": 0},
        }

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
        closure_runner=closure_runner,
    )

    assert report["summary"] == {"attempted": 1, "passed": 1, "failed": 0, "invalid": 0, "safe_stop": 0}
    case = report["cases"][0]
    assert case["actual_model_call"] is True
    assert case["three_image_evidence"]["complete"] is True
    assert case["three_image_evidence"]["root_partition"] == str((tmp_path / "root_partition.png").resolve())
    assert case["three_image_evidence"]["before_review_fusion"]
    assert Path(case["three_image_evidence"]["audit_contact_sheet_path"]).exists()
    assert case["provenance"]["prompt_version"] == "learning_overlay_model_review_prompt_v2"
    assert case["provenance"]["source_graph_revision"] == "source-revision"
    assert case["provenance"]["final_graph_revision"] == "final-revision"
    assert case["finalization"]["calibration_permission"] is True
    assert case["finalization"]["integrity_gate"]["passed"] is True
    assert Path(case["finalization"]["final_stage2_report_path"]).exists()
    assert report["safety"] == {"real_clicks": 0, "live_fills": 0, "live_submits": 0}


def test_validation_runner_excludes_stale_fixture_from_attempted(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path, screenshot_sha256="0" * 64)
    calls = 0

    def probe_runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
    )

    assert calls == 0
    assert report["summary"] == {"attempted": 0, "passed": 0, "failed": 0, "invalid": 1, "safe_stop": 0}
    assert report["invalid_cases"][0]["failure_category"] == "stale_fixture"
    assert report["invalid_cases"][0]["expected_checksum"] == "0" * 64
    assert report["invalid_cases"][0]["actual_checksum"]


def test_validation_runner_does_not_treat_recorded_output_as_actual_call(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)

    def probe_runner(**_: Any) -> dict[str, Any]:
        return {"actual_model_call": False, "source_type": "recorded_model_output"}

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
    )

    assert report["summary"]["attempted"] == 1
    assert report["summary"]["failed"] == 1
    assert report["cases"][0]["failure_category"] == "actual_model_call_missing"
    assert report["model_review_coverage"] == {"passed": 0, "attempted": 1, "rate": 0.0}


def test_validation_runner_scores_human_review_adjudication_without_inflating_model_coverage(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        human_adjudication={
            "contract_version": "learning_model_review_human_adjudication_v1",
            "scope": "review_layer_only",
            "expected_group_decisions": [
                {"region_id": "keep_group", "decision": "keep", "critical": True},
                {"region_id": "remove_group", "decision": "remove"},
                {
                    "region_id": "relabel_group",
                    "decision": "relabel",
                    "expected_role": "message_item",
                },
            ],
            "expected_missing_targets": [
                {
                    "target_id": "missing_form",
                    "expected_role": "form_region",
                    "expected_final_group_id": "recovered_group",
                }
            ],
        },
    )

    def probe_runner(**kwargs: Any) -> dict[str, Any]:
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        validated_patch = out_dir / "validated_review_patch.json"
        validated_patch.write_text(
            json.dumps(
                {
                    "keep": [{"region_id": "keep_group"}],
                    "remove": [{"region_id": "remove_group"}],
                    "relabel": [{"region_id": "relabel_group", "new_role": "message_item"}],
                    "missing": [{"target_id": "missing_form", "expected_role": "form_region"}],
                    "needs_human_review": [],
                }
            ),
            encoding="utf-8",
        )
        before = out_dir / "before_review_fusion.png"
        Image.new("RGB", (160, 120), "gray").save(before)
        raw = out_dir / "raw_model_output.txt"
        raw.write_text("{}", encoding="utf-8")
        prompt = out_dir / "prompt.txt"
        prompt.write_text("review", encoding="utf-8")
        return {
            "actual_model_call": True,
            "source_type": "actual_model_call",
            "validated_review_patch_path": str(validated_patch),
            "before_review_overlay_path": str(before),
            "raw_model_output_path": str(raw),
            "prompt_path": str(prompt),
        }

    def closure_runner(**kwargs: Any) -> dict[str, Any]:
        final = Path(kwargs["out_path"]).parent / "final_repaired_fusion.png"
        final.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (160, 120), "white").save(final)
        recomposed = {
            "regions": [
                {
                    "region_id": "root",
                    "bbox": {"x": 0, "y": 0, "w": 160, "h": 120},
                    "numbered_items": [],
                    "subregion_groups": [
                        {
                            "group_id": "keep_group",
                            "role": "card",
                            "bbox": {"x": 0, "y": 0, "w": 40, "h": 40},
                            "member_item_ids": [],
                        },
                        {
                            "group_id": "relabel_group",
                            "role": "message_item",
                            "bbox": {"x": 40, "y": 0, "w": 40, "h": 40},
                            "member_item_ids": [],
                        },
                        {
                            "group_id": "recovered_group",
                            "role": "form_region",
                            "bbox": {"x": 0, "y": 40, "w": 80, "h": 40},
                            "member_item_ids": [],
                        },
                    ],
                }
            ]
        }
        return {
            "workflow_state": "completed_review_only",
            "completed_review_only": True,
            "final_repaired_overlay_path": str(final),
            "source_graph_revision": "source-revision",
            "final_graph_revision": "final-revision",
            "deterministic_repair_failed": 0,
            "final_workflow": {
                "workflow_state": "completed_review_only",
                "recomposed_stage2": recomposed,
                "replacement_integrity_gate": {
                    "passed": True,
                    "failure_categories": [],
                    "needs_human_review": 0,
                },
                "repair_pending_count": 0,
            },
        }

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
        closure_runner=closure_runner,
    )

    case = report["cases"][0]
    assert case["human_adjudication"]["quality_gate_passed"] is True
    assert case["human_adjudication"]["false_deletions"] == []
    assert report["review_quality_metrics"]["review_keep_precision"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "interpretation": "expected keep groups were not removed",
    }
    assert report["review_quality_metrics"]["false_group_cleanup"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "interpretation": "human-marked false groups were removed",
    }
    assert report["review_quality_metrics"]["missing_region_detection"]["passed"] == 1
    assert report["review_quality_metrics"]["missing_region_recovery"]["passed"] == 1
    assert report["review_quality_metrics"]["atomic_evidence_preservation"]["passed"] == 1
    assert report["review_quality_metrics"]["interpretation"] == (
        "human-adjudicated review assertions only; not recognition accuracy or general reliability"
    )


def test_validation_runner_marks_critical_false_deletion_as_safe_stop(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        human_adjudication={
            "contract_version": "learning_model_review_human_adjudication_v1",
            "scope": "review_layer_only",
            "expected_group_decisions": [
                {"region_id": "critical_apply_entry", "decision": "keep", "critical": True}
            ],
            "expected_missing_targets": [],
        },
    )

    def probe_runner(**kwargs: Any) -> dict[str, Any]:
        out_dir = Path(kwargs["out_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        patch = out_dir / "validated_review_patch.json"
        patch.write_text(
            json.dumps(
                {
                    "keep": [],
                    "remove": [{"region_id": "critical_apply_entry"}],
                    "relabel": [],
                    "missing": [],
                    "needs_human_review": [],
                }
            ),
            encoding="utf-8",
        )
        before = out_dir / "before.png"
        Image.new("RGB", (160, 120), "gray").save(before)
        raw = out_dir / "raw.txt"
        raw.write_text("{}", encoding="utf-8")
        prompt = out_dir / "prompt.txt"
        prompt.write_text("review", encoding="utf-8")
        return {
            "actual_model_call": True,
            "source_type": "actual_model_call",
            "validated_review_patch_path": str(patch),
            "before_review_overlay_path": str(before),
            "raw_model_output_path": str(raw),
            "prompt_path": str(prompt),
        }

    def closure_runner(**kwargs: Any) -> dict[str, Any]:
        final = Path(kwargs["out_path"]).parent / "final.png"
        final.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (160, 120), "white").save(final)
        source = json.loads(Path(kwargs["stage2_source_path"]).read_text(encoding="utf-8"))
        return {
            "workflow_state": "completed_review_only",
            "completed_review_only": True,
            "final_repaired_overlay_path": str(final),
            "deterministic_repair_failed": 0,
            "final_workflow": {
                "workflow_state": "completed_review_only",
                "recomposed_stage2": source["two_stage_understanding"]["stage2_numbering"],
                "replacement_integrity_gate": {
                    "passed": True,
                    "failure_categories": [],
                    "needs_human_review": 0,
                },
                "repair_pending_count": 0,
            },
        }

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
        closure_runner=closure_runner,
    )

    assert report["summary"]["passed"] == 0
    assert report["summary"]["safe_stop"] == 1
    assert report["cases"][0]["case_outcome"] == "safe_stop"
    assert report["cases"][0]["human_adjudication"]["quality_gate_passed"] is False
    assert report["cases"][0]["human_adjudication"]["critical_false_deletions"] == [
        "critical_apply_entry"
    ]


def test_validation_runner_excludes_stale_human_adjudication_fixture(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        human_adjudication={
            "contract_version": "learning_model_review_human_adjudication_v1",
            "scope": "review_layer_only",
            "expected_group_decisions": [],
            "expected_missing_targets": [],
        },
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cases"][0]["human_adjudication_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = 0

    def probe_runner(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    report = run_validation(
        manifest_path=manifest_path,
        out_dir=tmp_path / "out",
        probe_runner=probe_runner,
    )

    assert calls == 0
    assert report["summary"] == {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "invalid": 1,
        "safe_stop": 0,
    }
    assert report["invalid_cases"][0]["failure_category"] == "stale_fixture"
    assert report["invalid_cases"][0]["fixture_type"] == "human_adjudication"
