from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import scripts.run_learn_recognition_grounding_model_matrix as matrix_runner
from scripts.run_learn_recognition_grounding_model_matrix import run_grounding_model_matrix


def test_grounding_model_matrix_separates_actual_calls_from_readiness_blockers(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (1200, 800), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "actual_grounding_fake",
                        "surface": "python_homepage",
                        "goal": "locate search",
                        "observe_bundle": {
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "omniparser": {
                                    "parsed_content_list": [
                                        {"type": "icon", "content": "Search", "bbox": [500, 300, 600, 340], "interactivity": True}
                                    ]
                                }
                            },
                        },
                    },
                    {
                        "case_id": "semantic_rejected",
                        "surface": "python_homepage",
                        "goal": "reject semantic-only",
                        "observe_bundle": {
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "vision": {
                                    "regions": [
                                        {
                                            "region_id": "c1",
                                            "label": "Search",
                                            "role": "button",
                                            "diagonal": {"x1": 500, "y1": 300, "x2": 600, "y2": 340},
                                            "confidence": 0.9,
                                        }
                                    ]
                                }
                            },
                        },
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "contract_version": "test_alt_grounding_cases_v1",
                "required_report_policy": {
                    "separate_model_point_quality": True,
                    "separate_precondition_stops": True,
                    "no_total_accuracy": True,
                },
                "cases": [
                    {
                        "case_id": "actual_grounding_fake",
                        "label": "Search",
                        "surface": "python_homepage",
                        "screenshot_path": str(screenshot_path),
                        "expected_case_outcome": "actual_grounding_call",
                        "reason": "positive actual grounding candidate",
                    },
                    {
                        "case_id": "semantic_rejected",
                        "label": "Search",
                        "surface": "python_homepage_semantic_only",
                        "screenshot_path": str(screenshot_path),
                        "expected_case_outcome": "blocked_precondition",
                        "expected_blocker": "fixture_precondition_failed",
                        "reason": "semantic only must stop before grounding",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    launchable_profile_path = _write_profile(tmp_path / "launchable.json", "launchable_profile", "available_test", True)
    blocked_profile_path = _write_profile(tmp_path / "blocked.json", "blocked_profile", "not_downloaded", False)

    call_count = 0

    def fake_model_caller(image_path, prompt, model_config):
        nonlocal call_count
        call_count += 1
        return {
            "raw_text": '{"point":{"x":100,"y":40,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_grounding_model_matrix(
        manifest_path=manifest_path,
        cases_json_path=cases_path,
        out_dir=tmp_path / "matrix",
        model_profiles=[str(launchable_profile_path), str(blocked_profile_path)],
        model_caller=fake_model_caller,
    )

    assert call_count == 1
    assert report["evaluation_scope"] == "learn_mode_saved_screenshot_roi_grounding_matrix"
    assert report["execution_scope"] == "no_action_no_execute_no_live_click"
    assert report["reliability_status"] == "exploratory_insufficient_sample_size"
    assert report["dataset_status"] == "targeted_hardcase_matrix"
    assert report["selection_bias"] == "contains targeted hard cases derived from known failure modes"
    assert report["not_accuracy"] is True
    assert report["not_e2e_success"] is True
    assert report["not_execute_mode_default"] is True
    assert report["source_breakdown"] == {
        "saved_screenshot_actual_call": 1,
        "precondition_stop": 1,
        "live_click": 0,
        "execute_mode": 0,
    }
    assert report["fresh_actual_calls"] == {"attempted": 1}
    assert report["precondition_stops"] == {"count": 1, "excluded_from_grounding_denominator": True}
    assert "accuracy" not in report["grounding_point_inside_expected_bbox_checks"]
    assert report["grounding_point_inside_expected_bbox_checks"]["launchable_profile"]["attempted"] == 1
    assert report["grounding_point_inside_expected_bbox_checks"]["launchable_profile"]["interpretation"] == (
        "ROI saved-screenshot bbox check only; not live GUI reliability"
    )
    assert report["candidate_set"]["contract_version"] == "test_alt_grounding_cases_v1"
    assert report["matrix_summary"]["profile_count"] == 2
    rows = {Path(row["model_profile_id"]).stem: row for row in report["matrix_summary"]["rows"]}
    assert rows["launchable"]["actual_model_call"]["attempted"] == 1
    assert rows["launchable"]["actual_model_call"]["passed"] == 1
    assert rows["launchable"]["point_center_bias_diagnostic"]["status"] == "insufficient_sample_size"
    assert rows["launchable"]["blocked_categories"] == {"fixture_precondition_failed": 1}
    assert rows["blocked"]["actual_model_call"]["attempted"] == 0
    assert rows["blocked"]["actual_model_call"]["rate"] == "not_covered"
    assert rows["blocked"]["blocked_categories"] == {"model_profile_not_downloaded": 1, "fixture_precondition_failed": 1}
    assert Path(report["report_path"]).exists()

    launchable_batch_path = Path(rows["launchable"]["batch_report_path"])
    launchable_batch = json.loads(launchable_batch_path.read_text(encoding="utf-8"))
    assert launchable_batch["case_reports"][0]["batch_case"]["expected_case_outcome"] == "actual_grounding_call"
    assert launchable_batch["case_reports"][1]["batch_case"]["expected_blocker"] == "fixture_precondition_failed"


def test_grounding_model_matrix_can_start_and_stop_only_profiles_it_started(tmp_path: Path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps({"cases": []}, ensure_ascii=False), encoding="utf-8")
    started: list[str] = []
    stopped: list[str] = []

    def fake_ensure(**kwargs):
        profile_id = kwargs["profile_id"]
        started.append(profile_id)
        was_started = profile_id == "learn_mode_uground_2b"
        return {
            "started": was_started,
            "before": {"status": "unreachable" if was_started else "running"},
            "after": {"status": "running"},
            "profile": {
                "profile_id": profile_id,
                "stop_script": "scripts/model_servers/stop_local_vision_server.ps1",
                "port": 13245 if was_started else 13244,
            },
            "start": {"pid": 123} if was_started else {},
        }

    def fake_stop(profile):
        stopped.append(profile["profile_id"])
        return {
            "stopped": True,
            "returncode": 0,
            "stdout": f"stopped {profile['profile_id']}",
            "stderr": "",
            "after": {"status": "unreachable"},
        }

    monkeypatch.setattr(matrix_runner, "ensure_model_server", fake_ensure)
    monkeypatch.setattr(matrix_runner, "stop_model_server", fake_stop)

    report = run_grounding_model_matrix(
        manifest_path=manifest_path,
        cases_json_path=cases_path,
        out_dir=tmp_path / "matrix",
        model_profiles=["learn_mode_uground_2b", "learn_grounding_vista_4b_baseline"],
        start_profiles=True,
        stop_started_profiles=True,
        start_wait_seconds=5,
    )

    lifecycle = report["service_lifecycle"]
    assert started == ["learn_mode_uground_2b", "learn_grounding_vista_4b_baseline"]
    assert stopped == ["learn_mode_uground_2b"]
    assert lifecycle["started_profiles"][0]["profile_id"] == "learn_mode_uground_2b"
    assert lifecycle["skipped_profiles"][0]["profile_id"] == "learn_grounding_vista_4b_baseline"
    assert lifecycle["stop_results"][0]["profile_id"] == "learn_mode_uground_2b"
    assert lifecycle["stop_results"][0]["stopped"] is True


def _write_profile(path: Path, profile_id: str, download_status: str, launchable: bool) -> Path:
    path.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "mode_scope": "learn_only",
                "model_id": f"test/{profile_id}",
                "model_name": f"{profile_id}-model",
                "model_family": "TestGrounder",
                "max_parameters_b": 1.0,
                "endpoint": "http://127.0.0.1:1/v1/chat/completions" if launchable else "",
                "download_status": download_status,
                "launchable": launchable,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path
