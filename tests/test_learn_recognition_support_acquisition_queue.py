from __future__ import annotations

import json
import hashlib
from pathlib import Path


def test_support_acquisition_queue_turns_repair_targets_into_operator_tasks(tmp_path: Path) -> None:
    from scripts.build_learn_recognition_support_acquisition_queue import build_support_acquisition_queue

    screenshot_dir = tmp_path / "artifacts" / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    missing_support_screenshot = screenshot_dir / "seek.png"
    missing_support_screenshot.write_bytes(b"seek-screenshot")
    missing_support_sha = hashlib.sha256(missing_support_screenshot.read_bytes()).hexdigest()
    misaligned_screenshot = screenshot_dir / "python.png"
    misaligned_screenshot.write_bytes(b"python-screenshot")
    misaligned_sha = hashlib.sha256(misaligned_screenshot.read_bytes()).hexdigest()

    manifest = tmp_path / "artifacts" / "benchmarks" / "learn_recognition_actual_parser_cases_v1.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for script_name in (
        "capture_learn_recognition_same_screenshot_support.py",
        "create_learn_recognition_calibrated_support.py",
        "bind_learn_recognition_support_to_manifest.py",
    ):
        (scripts_dir / script_name).write_text("# placeholder\n", encoding="utf-8")

    diagnosis_path = tmp_path / "diagnosis.json"
    diagnosis_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_pathgraph_readiness_blocker_diagnosis_v1",
                "support_repair_targets": [
                    {
                        "case_id": "case_missing_support",
                        "surface": "seek_results",
                        "goal": "find job cards",
                        "screenshot_path": "artifacts/screenshots/seek.png",
                        "screenshot_sha256": missing_support_sha,
                        "current_status": "semantic_only_without_same_screenshot_interactable_support",
                        "root_cause": "no_same_screenshot_interactable_support",
                        "same_screenshot_support_status": "no_matching_support_json_found",
                        "interactable_support_count": 0,
                        "bbox_alignment_status": "not_evaluated",
                        "required_next_evidence": [
                            "capture_same_screenshot_uia",
                            "capture_same_screenshot_omniparser",
                            "add_same_screenshot_calibrated_target",
                        ],
                    },
                    {
                        "case_id": "case_misaligned",
                        "surface": "python_homepage",
                        "goal": "search docs",
                        "screenshot_path": "artifacts/screenshots/python.png",
                        "screenshot_sha256": misaligned_sha,
                        "current_status": "same_screenshot_support_found_but_parser_bbox_alignment_failed",
                        "root_cause": "parser_bbox_alignment_failed",
                        "same_screenshot_support_status": "matching_interactable_support_found",
                        "interactable_support_count": 2,
                        "bbox_alignment_status": "failed",
                        "required_next_evidence": ["add_same_screenshot_calibrated_target"],
                    },
                ],
                "safety": {
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "real_clicks_performed": 0,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_support_acquisition_queue(
        diagnosis_report_path=diagnosis_path,
        out=tmp_path / "queue.json",
        project_root=tmp_path,
    )

    assert report["contract_version"] == "learn_recognition_support_acquisition_queue_v1"
    assert report["summary"] == {
        "task_count": 2,
        "missing_support_count": 1,
        "alignment_repair_count": 1,
        "preflight_ready_count": 2,
        "preflight_blocked_count": 0,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    first = report["tasks"][0]
    assert first["case_id"] == "case_missing_support"
    assert first["priority"] == 1
    assert first["task_type"] == "capture_same_screenshot_support"
    assert "capture_learn_recognition_same_screenshot_support.py" in first["recommended_commands"][0]
    assert "--out " in first["recommended_commands"][0]
    assert "--screenshot" not in first["recommended_commands"][0]
    assert "--out-dir" not in first["recommended_commands"][0]
    assert first["support_validation_commands"] == [
        "uv run python scripts\\bind_learn_recognition_support_to_manifest.py --manifest artifacts\\benchmarks\\learn_recognition_actual_parser_cases_v1.json --case-id case_missing_support --support artifacts/benchmarks/learn_recognition_support_repair/case_missing_support\\same_screenshot_uia_support.json --validate-only --json"
    ]
    assert "--out " not in first["support_validation_commands"][0]
    assert "bind_learn_recognition_support_to_manifest.py" in first["recommended_commands"][-1]
    assert "--out artifacts/benchmarks/learn_recognition_support_repair/case_missing_support/learn_recognition_actual_parser_cases_with_support.json" in first["recommended_commands"][-1]
    assert first["acceptance_criteria"]["screenshot_sha256_must_match"] is True
    assert first["preflight"]["manual_window_reproduction_required"] is True
    assert first["preflight"]["target_screenshot_sha256"] == missing_support_sha
    assert first["preflight"]["capture_script_accepts_saved_screenshot"] is False
    assert first["preflight"]["status"] == "ready"
    assert first["preflight"]["screenshot_exists"] is True
    assert first["preflight"]["screenshot_sha256_status"] == "match"
    assert first["preflight"]["required_scripts_present"] is True
    assert first["preflight"]["manifest_exists"] is True
    assert first["safety"]["execute_binding_enabled"] is False

    second = report["tasks"][1]
    assert second["case_id"] == "case_misaligned"
    assert second["priority"] == 2
    assert second["task_type"] == "repair_bbox_alignment"
    assert "create_learn_recognition_calibrated_support.py" in second["recommended_commands"][0]
    assert "--screenshot artifacts/screenshots/python.png" in second["recommended_commands"][0]
    assert second["support_validation_commands"] == [
        "uv run python scripts\\bind_learn_recognition_support_to_manifest.py --manifest artifacts\\benchmarks\\learn_recognition_actual_parser_cases_v1.json --case-id case_misaligned --support artifacts/benchmarks/learn_recognition_support_repair/case_misaligned\\same_screenshot_calibrated_support.json --validate-only --json"
    ]
    assert "--out artifacts/benchmarks/learn_recognition_support_repair/case_misaligned/learn_recognition_actual_parser_cases_with_support.json" in second["recommended_commands"][-1]
    assert second["preflight"]["manual_window_reproduction_required"] is False
    assert second["preflight"]["status"] == "ready"

    written = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    assert written["tasks"][0]["case_id"] == "case_missing_support"


def test_support_acquisition_queue_preflight_blocks_stale_or_missing_screenshot(tmp_path: Path) -> None:
    from scripts.build_learn_recognition_support_acquisition_queue import build_support_acquisition_queue

    manifest = tmp_path / "artifacts" / "benchmarks" / "learn_recognition_actual_parser_cases_v1.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for script_name in (
        "capture_learn_recognition_same_screenshot_support.py",
        "bind_learn_recognition_support_to_manifest.py",
    ):
        (scripts_dir / script_name).write_text("# placeholder\n", encoding="utf-8")

    screenshot_dir = tmp_path / "artifacts" / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    stale_screenshot = screenshot_dir / "stale.png"
    stale_screenshot.write_bytes(b"actual")

    diagnosis_path = tmp_path / "diagnosis.json"
    diagnosis_path.write_text(
        json.dumps(
            {
                "support_repair_targets": [
                    {
                        "case_id": "case_stale",
                        "screenshot_path": "artifacts/screenshots/stale.png",
                        "screenshot_sha256": "0" * 64,
                        "same_screenshot_support_status": "no_matching_support_json_found",
                        "bbox_alignment_status": "not_evaluated",
                    },
                    {
                        "case_id": "case_missing",
                        "screenshot_path": "artifacts/screenshots/missing.png",
                        "screenshot_sha256": "1" * 64,
                        "same_screenshot_support_status": "no_matching_support_json_found",
                        "bbox_alignment_status": "not_evaluated",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_support_acquisition_queue(
        diagnosis_report_path=diagnosis_path,
        project_root=tmp_path,
    )

    assert report["summary"]["preflight_ready_count"] == 0
    assert report["summary"]["preflight_blocked_count"] == 2
    statuses = {task["case_id"]: task["preflight"] for task in report["tasks"]}
    assert statuses["case_stale"]["status"] == "blocked"
    assert statuses["case_stale"]["screenshot_sha256_status"] == "mismatch"
    assert "screenshot_sha256_mismatch" in statuses["case_stale"]["blockers"]
    assert statuses["case_missing"]["status"] == "blocked"
    assert statuses["case_missing"]["screenshot_exists"] is False
    assert "screenshot_missing" in statuses["case_missing"]["blockers"]
