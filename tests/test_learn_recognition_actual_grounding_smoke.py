from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.run_learn_recognition_actual_grounding_smoke import (
    parse_grounding_model_output,
    run_actual_grounding_smoke_batch,
    run_actual_grounding_smoke,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_parse_grounding_model_output_accepts_json_point_and_pair():
    assert parse_grounding_model_output('{"point":{"x":500,"y":500,"coordinate_space":"normalized_0_1000"}}') == {
        "coordinate_space": "normalized_0_1000",
        "raw_output": [500, 500],
    }
    assert parse_grounding_model_output("[500, 500]") == {
        "coordinate_space": "normalized_0_1000",
        "raw_output": [500, 500],
    }


def test_actual_grounding_smoke_with_fake_model_writes_reviewable_draft(tmp_path: Path):
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
                            "contract_version": "learn_observe_bundle_v1",
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "omniparser": {
                                    "parsed_content_list": [
                                        {
                                            "type": "icon",
                                            "content": "Search",
                                            "bbox": [500, 300, 600, 340],
                                            "interactivity": True,
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile_path = tmp_path / "learn_grounding_fake_launchable.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "learn_grounding_fake_launchable",
                "mode_scope": "learn_only",
                "model_id": "osunlp/UGround-V1-2B",
                "model_name": "osunlp/UGround-V1-2B",
                "model_family": "UGround",
                "max_parameters_b": 2.0,
                "endpoint": "http://127.0.0.1:1/v1/chat/completions",
                "download_status": "available_test",
                "launchable": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        assert image_path.exists()
        assert model_config["model_name"] == "osunlp/UGround-V1-2B"
        assert model_config["model_profile"]["profile_id"] == "learn_grounding_fake_launchable"
        assert "coordinate_space=roi_local_point" in prompt
        assert "Original screenshot candidate bbox" not in prompt
        assert "[57,46]" not in prompt
        return {
            "raw_text": '{"point":{"x":100,"y":40,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="actual_grounding_fake",
        label="Search",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint=None,
        model_name="",
        model_profile_id=str(profile_path),
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["source_type"] == "actual_grounding_call"
    assert report["actual_model_call_in_this_run"] is True
    assert report["model_profile"]["profile_id"] == "learn_grounding_fake_launchable"
    assert report["normalized_grounding"]["screen_point"] == {"x": 550, "y": 320}
    assert report["validation"]["status"] == "valid_candidate"
    assert report["point_quality"]["status"] == "passed_inside_expected_bbox"
    assert report["point_quality"]["roi_point_inside_candidate_bbox"] is True
    assert report["learning_draft"]["contract_version"] == "learning_template_draft_v1"
    assert Path(report["report_path"]).exists()
    assert Path(report["roi_image_path"]).exists()
    output_path = Path(report["actual_grounding_output_path"])
    assert output_path.exists()
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert output["model_profile"]["profile_id"] == "learn_grounding_fake_launchable"
    assert output["grounding_by_label"]["Search"]["screen_point"] == {"x": 550, "y": 320}
    assert output["point_quality"]["status"] == "passed_inside_expected_bbox"
    assert "not a fresh actual model call" in output["interpretation"]


def test_actual_grounding_point_quality_uses_restored_roi_point_for_normalized_output(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (1200, 800), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "actual_grounding_normalized",
                        "surface": "python_homepage",
                        "observe_bundle": {
                            "contract_version": "learn_observe_bundle_v1",
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "omniparser": {
                                    "parsed_content_list": [
                                        {
                                            "type": "icon",
                                            "content": "Search",
                                            "bbox": [500, 300, 600, 340],
                                            "interactivity": True,
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        assert image_path.exists()
        return {
            "raw_text": '{"point":{"x":500,"y":500,"coordinate_space":"normalized_0_1000"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="actual_grounding_normalized",
        label="Search",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-normalized",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["normalized_grounding"]["debug"]["restored_local_point"] == {"x": 100, "y": 40}
    assert report["point_quality"]["roi_point"] == {"x": 100.0, "y": 40.0}
    assert report["point_quality"]["roi_point_source"] == "restored_local_point"
    assert report["point_quality"]["roi_point_inside_candidate_bbox"] is True
    assert report["point_quality"]["status"] == "passed_inside_expected_bbox"


def test_actual_grounding_smoke_reports_model_point_outside_roi_candidate_bbox(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (500, 400), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "actual_grounding_miss",
                        "surface": "test_page",
                        "goal": "locate button",
                        "observe_bundle": {
                            "screen_size": {"width": 500, "height": 400},
                            "sources": {
                                "uia": {
                                    "controls": [
                                        {
                                            "name": "Search",
                                            "control_type": "Button",
                                            "bbox": {"x": 100, "y": 100, "w": 80, "h": 30},
                                            "patterns": ["Invoke"],
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        assert image_path.exists()
        assert "ROI-image candidate bbox" in prompt
        return {
            "raw_text": '{"point":{"x":10,"y":15,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="actual_grounding_miss",
        label="Search",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-model",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "failed"
    assert report["validation"]["failure_category"] == "point_outside_bbox"
    assert report["point_quality"]["status"] == "failed_outside_expected_bbox"
    assert report["point_quality"]["failure_category"] == "model_point_outside_roi_candidate_bbox"
    assert report["point_quality"]["roi_point"] == {"x": 10.0, "y": 15.0}
    assert report["point_quality"]["roi_candidate_bbox"] == {"x": 40, "y": 15, "w": 80, "h": 30}
    assert report["point_quality"]["error"]["outside_by_x"] == 30.0
    assert report["point_quality"]["error"]["distance_to_bbox"] == 30.0
    output = json.loads(Path(report["actual_grounding_output_path"]).read_text(encoding="utf-8"))
    assert output["point_quality"]["failure_category"] == "model_point_outside_roi_candidate_bbox"


def test_actual_grounding_batch_counts_only_fresh_model_calls(tmp_path: Path):
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
    profile_path = tmp_path / "learn_grounding_batch_launchable.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "learn_grounding_batch_launchable",
                "mode_scope": "learn_only",
                "model_id": "batch/model",
                "model_name": "batch-model",
                "model_family": "BatchGrounder",
                "max_parameters_b": 1.0,
                "endpoint": "http://127.0.0.1:1/v1/chat/completions",
                "download_status": "available_test",
                "launchable": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    call_count = 0

    def fake_model_caller(image_path, prompt, model_config):
        nonlocal call_count
        call_count += 1
        return {
            "raw_text": '{"point":{"x":100,"y":40,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke_batch(
        manifest_path=manifest_path,
        cases=[
            {"case_id": "actual_grounding_fake", "label": "Search", "screenshot_path": str(screenshot_path)},
            {
                "case_id": "semantic_rejected",
                "label": "Search",
                "screenshot_path": str(screenshot_path),
                "model_profile_id": "learn_mode_uground_7b",
            },
        ],
        out_dir=tmp_path / "batch",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="",
        model_profile_id=str(profile_path),
        model_caller=fake_model_caller,
    )

    assert call_count == 1
    assert report["summary"]["actual_model_call"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
        "interpretation": "fresh actual grounding calls only; not a reliability or 90% accuracy claim",
    }
    assert report["summary"]["point_center_bias_diagnostic"]["status"] == "insufficient_sample_size"
    assert report["summary"]["blocked_categories"] == {"fixture_precondition_failed": 1}
    assert report["actual_model_profile_breakdown"] == {
        "actual_model_call": {"learn_grounding_batch_launchable": 1},
        "blocked_or_precondition": {"learn_mode_uground_7b": 1},
    }
    assert report["case_reports"][0]["batch_case"]["interpretation"].startswith("batch case review metadata")


def test_actual_grounding_batch_reports_center_point_bias_risk(tmp_path: Path):
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
                        "observe_bundle": {
                            "contract_version": "learn_observe_bundle_v1",
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "omniparser": {
                                    "parsed_content_list": [
                                        {
                                            "type": "icon",
                                            "content": "Search",
                                            "bbox": [500, 300, 600, 340],
                                            "interactivity": True,
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile_path = tmp_path / "learn_grounding_center_bias.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "learn_grounding_center_bias",
                "mode_scope": "learn_only",
                "model_id": "center/model",
                "model_name": "center-model",
                "model_family": "CenterBias",
                "max_parameters_b": 1.0,
                "endpoint": "http://127.0.0.1:1/v1/chat/completions",
                "download_status": "available_test",
                "launchable": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def center_model_caller(image_path, prompt, model_config):
        return {
            "raw_text": '{"point":{"x":500,"y":500,"coordinate_space":"normalized_0_1000"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke_batch(
        manifest_path=manifest_path,
        cases=[
            {"case_id": "actual_grounding_fake", "label": "Search", "screenshot_path": str(screenshot_path)}
            for _ in range(3)
        ],
        out_dir=tmp_path / "center-bias-batch",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="",
        model_profile_id=str(profile_path),
        model_caller=center_model_caller,
    )

    diagnostic = report["summary"]["point_center_bias_diagnostic"]
    assert diagnostic["status"] == "center_bias_risk"
    assert diagnostic["near_center_outputs"] == 3
    assert diagnostic["near_center_rate"] == 1.0
    assert "not model reliability evidence" in diagnostic["interpretation"]


def test_actual_grounding_roi_override_makes_center_point_fail(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (1200, 800), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "actual_grounding_offcenter",
                        "surface": "offcenter_fixture",
                        "observe_bundle": {
                            "contract_version": "learn_observe_bundle_v1",
                            "screen_size": {"width": 1200, "height": 800},
                            "sources": {
                                "omniparser": {
                                    "parsed_content_list": [
                                        {
                                            "type": "icon",
                                            "content": "Off-center target",
                                            "bbox": [500, 300, 600, 340],
                                            "interactivity": True,
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    profile_path = tmp_path / "learn_grounding_center_bias.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "learn_grounding_center_bias",
                "mode_scope": "learn_only",
                "model_id": "center/model",
                "model_name": "center-model",
                "model_family": "CenterBias",
                "max_parameters_b": 1.0,
                "endpoint": "http://127.0.0.1:1/v1/chat/completions",
                "download_status": "available_test",
                "launchable": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def center_model_caller(image_path, prompt, model_config):
        return {
            "raw_text": '{"point":{"x":500,"y":500,"coordinate_space":"normalized_0_1000"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke_batch(
        manifest_path=manifest_path,
        cases=[
            {
                "case_id": "actual_grounding_offcenter",
                "label": "Off-center target",
                "screenshot_path": str(screenshot_path),
                "roi_bbox_override": {"x": 450, "y": 260, "w": 400, "h": 160},
            }
        ],
        out_dir=tmp_path / "offcenter-batch",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="",
        model_profile_id=str(profile_path),
        model_caller=center_model_caller,
    )

    assert report["summary"]["actual_model_call"]["attempted"] == 1
    assert report["summary"]["actual_model_call"]["passed"] == 0
    case = report["case_reports"][0]
    assert case["status"] == "failed"
    assert case["grounding_request"]["target"]["candidate_bbox_in_roi"] == {"x": 50, "y": 40, "w": 100, "h": 40}
    assert case["point_quality"]["status"] == "failed_outside_expected_bbox"
    assert case["point_quality"]["failure_category"] == "model_point_outside_roi_candidate_bbox"
    assert case["point_quality"]["roi_point"] == {"x": 200.0, "y": 80.0}


def test_actual_grounding_smoke_resolves_endpoint_and_model_from_profile(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (500, 400), color=(255, 255, 255)).save(screenshot_path)
    profile_path = tmp_path / "learn_grounding_test_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "profile_id": "learn_grounding_test_profile",
                "mode_scope": "learn_only",
                "model_id": "test/model",
                "model_name": "test-model-name",
                "model_family": "TestGrounder",
                "max_parameters_b": 1.0,
                "endpoint": "http://127.0.0.1:65530/v1/chat/completions",
                "download_status": "available_test",
                "launchable": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "profile_resolved_grounding",
                        "surface": "test_page",
                        "goal": "locate search",
                        "observe_bundle": {
                            "screen_size": {"width": 500, "height": 400},
                            "sources": {
                                "uia": {
                                    "controls": [
                                        {
                                            "name": "Search",
                                            "control_type": "Button",
                                            "bbox": {"x": 100, "y": 100, "w": 80, "h": 30},
                                            "patterns": ["Invoke"],
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        assert model_config["endpoint"] == "http://127.0.0.1:65530/v1/chat/completions"
        assert model_config["model_name"] == "test-model-name"
        assert model_config["model_profile"]["profile_id"] == "learn_grounding_test_profile"
        return {
            "raw_text": '{"point":{"x":80,"y":30,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="profile_resolved_grounding",
        label="Search",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint=None,
        model_name=None,
        model_profile_id=str(profile_path),
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["model_config"]["endpoint"] == "http://127.0.0.1:65530/v1/chat/completions"
    assert report["model_config"]["model_name"] == "test-model-name"
    assert report["model_profile"]["profile_id"] == "learn_grounding_test_profile"


def test_actual_grounding_smoke_blocks_metadata_only_profile_before_model_call(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (500, 400), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "metadata_only_profile",
                        "surface": "test_page",
                        "goal": "locate search",
                        "observe_bundle": {
                            "screen_size": {"width": 500, "height": 400},
                            "sources": {
                                "uia": {
                                    "controls": [
                                        {
                                            "name": "Search",
                                            "control_type": "Button",
                                            "bbox": {"x": 100, "y": 100, "w": 80, "h": 30},
                                            "patterns": ["Invoke"],
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        raise AssertionError("metadata-only profile must be blocked before model call")

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="metadata_only_profile",
        label="Search",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:65530/v1/chat/completions",
        model_name=None,
        model_profile_id="learn_mode_uground_7b",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "blocked"
    assert report["actual_model_call_in_this_run"] is False
    assert report["blocker"]["failure_category"] == "model_profile_not_downloaded"
    assert report["model_profile"]["profile_id"] == "learn_mode_uground_7b"
    assert report["model_profile_readiness"]["download_status"] == "not_downloaded"
    assert report["model_profile_readiness"]["launchable"] is False
    assert report["model_profile_readiness"]["endpoint_present"] is True
    assert "actual_model_call denominator" in report["model_profile_readiness"]["interpretation"]
    assert Path(report["roi_image_path"]).exists()


def test_actual_grounding_smoke_accepts_calibrated_target_source(tmp_path: Path):
    screenshot_path = tmp_path / "screen.png"
    Image.new("RGB", (1400, 900), color=(255, 255, 255)).save(screenshot_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "calibrated_search_button",
                        "surface": "python_homepage",
                        "goal": "locate search button from calibrated target evidence",
                        "observe_bundle": {
                            "screen_size": {"width": 1400, "height": 900},
                            "sources": {
                                "calibrated_targets": {
                                    "targets": [
                                        {
                                            "candidate_id": "search_button",
                                            "label": "Search button",
                                            "role": "button",
                                            "bbox": {"x": 1200, "y": 200, "w": 80, "h": 40},
                                            "click_point": {"x": 1240, "y": 220},
                                            "coordinate_validation": {
                                                "status": "valid",
                                                "bbox_present": True,
                                                "click_point_present": True,
                                                "bbox_inside_image": True,
                                                "click_point_inside_image": True,
                                                "click_point_inside_bbox": True,
                                            },
                                        }
                                    ]
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path, prompt, model_config):
        assert "ROI-image candidate bbox" in prompt
        assert "original screenshot coordinates" in prompt
        assert "[57,46]" not in prompt
        return {
            "raw_text": '{"point":{"x":80,"y":40,"coordinate_space":"roi_local_point"}}',
            "raw_response": {"choices": []},
        }

    report = run_actual_grounding_smoke(
        manifest_path=manifest_path,
        case_id="calibrated_search_button",
        label="Search button",
        screenshot_path=screenshot_path,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-model",
        model_caller=fake_model_caller,
    )

    assert report["status"] == "passed"
    assert report["validation"]["checks"]["uia_or_dom_or_parser_overlap"] is True
    assert report["learning_draft"]["action_templates"][0]["label"] == "Search button"


def test_repository_vista_baseline_cases_mix_actual_and_blocked_paths():
    cases_path = PROJECT_ROOT / "artifacts" / "benchmarks" / "learn_recognition_actual_grounding_vista_baseline_cases_v1.json"
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    outcomes = {case.get("expected_case_outcome") for case in cases}

    assert payload["profile_id"] == "learn_grounding_vista_4b_baseline"
    assert "actual_grounding_call" in outcomes
    assert "blocked_precondition" in outcomes
    assert sum(1 for case in cases if case.get("expected_case_outcome") == "actual_grounding_call") >= 2
    assert sum(1 for case in cases if case.get("expected_case_outcome") == "blocked_precondition") >= 2
    for case in cases:
        assert (PROJECT_ROOT / case["screenshot_path"].replace("D:/agent-gui-runtime/", "")).exists()


def test_repository_vista_seek_cases_use_saved_screenshot_and_actual_outcomes():
    cases_path = PROJECT_ROOT / "artifacts" / "benchmarks" / "learn_recognition_actual_grounding_vista_seek_cases_v1.json"
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["profile_id"] == "learn_grounding_vista_4b_baseline"
    assert len(cases) == 3
    assert {case["expected_case_outcome"] for case in cases} == {"actual_grounding_call"}
    assert {case["label"] for case in cases} == {
        "Search keyword field",
        "SEEK search button",
        "Pay filter",
    }
    for case in cases:
        screenshot_path = Path(case["screenshot_path"])
        if not screenshot_path.is_absolute():
            screenshot_path = PROJECT_ROOT / screenshot_path
        assert screenshot_path.exists()
        assert "pytest-" not in str(screenshot_path)


def test_repository_alternative_grounding_candidate_set_keeps_hard_cases():
    cases_path = PROJECT_ROOT / "artifacts" / "benchmarks" / "learn_recognition_alternative_grounding_candidates_v1.json"
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"]

    assert payload["contract_version"] == "learn_recognition_alternative_grounding_candidates_v1"
    assert payload["required_report_policy"] == {
        "separate_model_point_quality": True,
        "separate_validator_safety": True,
        "separate_precondition_stops": True,
        "no_total_accuracy": True,
        "no_execute_authorization": True,
    }
    assert len(cases) == 19
    assert sum(1 for case in cases if case.get("expected_case_outcome") == "actual_grounding_call") == 16
    assert sum(1 for case in cases if case.get("expected_case_outcome") == "blocked_precondition") == 3
    offcenter_cases = [case for case in cases if case.get("roi_bbox_override")]
    assert len(offcenter_cases) == 7
    assert {case["surface"] for case in offcenter_cases} >= {
        "seek_results_header_offcenter_roi",
        "python_homepage_offcenter_roi",
        "seek_results_header_input_offcenter_roi",
        "python_homepage_nav_multicandidate_roi",
        "python_homepage_buttons_multicandidate_roi",
    }
    assert {
        (case["case_id"], case["label"])
        for case in cases
        if case.get("expected_case_outcome") == "actual_grounding_call"
    } >= {
        ("recorded_parser_seek_search_header_controls", "Search keyword field"),
        ("recorded_parser_seek_search_header_controls", "SEEK search button"),
        ("recorded_parser_seek_search_header_controls", "Pay filter"),
        ("recorded_parser_calibrated_targets_python_homepage", "Search input field"),
        ("recorded_parser_calibrated_targets_python_homepage", "Search button"),
        ("recorded_parser_calibrated_targets_python_homepage", "Downloads link"),
        ("recorded_parser_calibrated_targets_python_homepage", "Documentation link"),
        ("recorded_parser_calibrated_targets_python_homepage", "Get Started button"),
        ("recorded_parser_calibrated_targets_python_homepage", "Download button"),
    }
    assert {
        case["expected_blocker"]
        for case in cases
        if case.get("expected_case_outcome") == "blocked_precondition"
    } == {"fixture_precondition_failed"}
    for case in cases:
        screenshot_path = Path(case["screenshot_path"])
        if not screenshot_path.is_absolute():
            screenshot_path = PROJECT_ROOT / screenshot_path
        assert screenshot_path.exists()
        assert case.get("reason")
