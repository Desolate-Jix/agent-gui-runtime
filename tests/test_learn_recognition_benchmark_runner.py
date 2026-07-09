from __future__ import annotations

import json

from scripts.run_learn_recognition_benchmark import run_benchmark

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_learn_recognition_benchmark_reports_layered_metrics_without_total_success(tmp_path):
    manifest = {
        "contract_version": "learn_recognition_golden_manifest_v1",
        "cases": [
            {
                "case_id": "search_button_grounded",
                "observe_bundle": {
                    "screen_size": {"width": 1280, "height": 720},
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "name": "Search",
                                    "control_type": "Button",
                                    "bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                                    "patterns": ["Invoke"],
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "inventory_min_count": 1,
                    "actionable_labels": ["Search"],
                    "roi_coverage_labels": ["Search"],
                    "grounding_valid_labels": ["Search"],
                    "draft_region_labels": ["Search"],
                },
                "grounding": {
                    "Search": {
                        "screen_point": {"x": 1024, "y": 158},
                        "screen_bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                        "evidence": {
                            "coordinate_transform_replay": True,
                            "screenshot_freshness": True,
                            "uia_or_dom_or_parser_overlap": True,
                        },
                    }
                },
            },
            {
                "case_id": "readable_text_rejected",
                "observe_bundle": {
                    "screen_size": {"width": 800, "height": 600},
                    "sources": {
                        "ocr": {
                            "texts": [
                                {
                                    "text": "Latest News",
                                    "bbox": {"x": 20, "y": 300, "w": 180, "h": 32},
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "inventory_min_count": 1,
                    "rejected_labels": ["Latest News"],
                },
            },
            {
                "case_id": "browser_chrome_wrong_surface_rejected",
                "observe_bundle": {
                    "screen_size": {"width": 1280, "height": 720},
                    "sources": {
                        "ocr": {
                            "texts": [
                                {
                                    "text": "Address and search bar",
                                    "bbox": {"x": 72, "y": 42, "w": 420, "h": 28},
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "inventory_min_count": 1,
                    "wrong_surface_labels": ["Address and search bar"],
                },
            },
            {
                "case_id": "stale_fixture_missing_observe",
                "expected": {"inventory_min_count": 1},
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["contract_version"] == "learn_recognition_benchmark_report_v1"
    assert "success_rate" not in json.dumps(report)
    assert report["source_breakdown"] == {
        "fixture_only": 3,
        "recorded_parser_output": 0,
        "recorded_grounding_output": 0,
        "actual_parser_call": 0,
        "actual_grounding_call": 0,
    }
    assert report["parser_reliability_status"] == "fixture_only_not_model_validated"
    assert report["grounding_reliability_status"] == "fixture_only_not_model_validated"
    assert report["metrics"]["parse_inventory"] == {"passed": 3, "attempted": 3, "rate": 1.0}
    assert report["metrics"]["actionable_classification"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["form_field_classification"]["rate"] == "not_covered"
    assert report["metrics"]["semantic_only_rejection"]["rate"] == "not_covered"
    assert report["metrics"]["non_actionable_rejection"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["wrong_surface_rejection"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["roi_target_coverage"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["grounding_point"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["coordinate_transform"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["metrics"]["pathgraph_candidate_validation"]["rate"] == "not_covered"
    assert report["invalid_cases"][0]["case_id"] == "stale_fixture_missing_observe"
    assert report["invalid_cases"][0]["failure_category"] == "invalid_fixture"
    assert report["grounding_eligibility_breakdown"]["grounding_eligible"] == 1
    assert report["grounding_eligibility_breakdown"]["review_only"] >= 2
    assert "review usefulness is not grounding success" in report["parser_output_quality"]["interpretation"]
    support = report["support_eligibility_summary"]
    assert support["parser_candidate_contract"] == "parser_candidate_v1"
    assert support["total_candidates"] == 3
    assert support["grounding_eligible_candidates"] == 1
    assert support["review_only_candidates"] == 2
    assert support["interactable_evidence_candidates"] == 1
    assert support["semantic_or_ocr_candidates"] == 2
    assert support["semantic_or_ocr_leaked_to_grounding"] == 0
    assert support["semantic_or_ocr_leakage_safe"] is True
    assert support["by_source_type"] == {"ocr": 2, "uia": 1}
    assert support["by_evidence_kind"] == {"ocr_text_anchor": 2, "uia_interactable": 1}
    assert "not click permission" in support["interpretation"]


def test_learn_recognition_benchmark_records_grounding_failures(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "point_outside_bbox",
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
                "expected": {
                    "grounding_valid_labels": ["Search"],
                },
                "grounding": {
                    "Search": {
                        "screen_point": {"x": 300, "y": 115},
                        "screen_bbox": {"x": 100, "y": 100, "w": 80, "h": 30},
                        "evidence": {
                            "coordinate_transform_replay": True,
                            "screenshot_freshness": True,
                        },
                    }
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["metrics"]["grounding_point"] == {"passed": 0, "attempted": 1, "rate": 0.0}
    assert report["metrics"]["coordinate_transform"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["failures"][0]["case_id"] == "point_outside_bbox"
    assert report["failures"][0]["metric"] == "grounding_point"
    assert report["failures"][0]["failure_category"] == "point_outside_bbox"


def test_learn_recognition_benchmark_scores_form_fields(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "email_field",
                "observe_bundle": {
                    "screen_size": {"width": 900, "height": 600},
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "name": "Email",
                                    "control_type": "Edit",
                                    "bbox": {"x": 120, "y": 220, "w": 320, "h": 36},
                                    "patterns": ["Value"],
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "form_field_labels": ["Email"],
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["metrics"]["form_field_classification"] == {"passed": 1, "attempted": 1, "rate": 1.0}


def test_learn_recognition_benchmark_scores_leakage_taxonomy(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "semantic_region_without_evidence",
                "observe_bundle": {
                    "screen_size": {"width": 900, "height": 600},
                    "sources": {
                        "vision": {
                            "regions": [
                                {
                                    "label": "Hero code sample",
                                    "role": "card",
                                    "bbox": {"x": 120, "y": 160, "w": 420, "h": 220},
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "semantic_without_interactable_labels": ["Hero code sample"],
                    "not_grounded_labels": ["Hero code sample"],
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["metrics"]["semantic_bbox_without_interactable_evidence"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["semantic_only_rejection"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["non_actionable_leaked_to_grounding"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    case_summary = report["case_results"][0]["grounding_eligibility"]
    assert case_summary["grounding_eligible"] == 0
    assert case_summary["review_only"] == 1
    assert case_summary["blocked_reasons"]["semantic_region_only_without_interactable_evidence"] == 1
    support = report["case_results"][0]["support_eligibility"]
    assert support["total_candidates"] == 1
    assert support["by_evidence_kind"] == {"semantic_region": 1}
    assert support["semantic_or_ocr_leaked_to_grounding"] == 0
    assert support["blocked_reasons"]["semantic_region_only_without_interactable_evidence"] == 1


def test_learn_recognition_benchmark_reports_same_screenshot_support_eligibility(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "same_screenshot_support",
                "observe_bundle": {
                    "screenshot_sha256": "b" * 64,
                    "coordinate_space": "image",
                    "screen_size": {"width": 900, "height": 600},
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "name": "Search",
                                    "control_type": "Button",
                                    "bbox": {"x": 120, "y": 80, "w": 90, "h": 32},
                                    "patterns": ["Invoke"],
                                }
                            ]
                        },
                        "vision": {
                            "regions": [
                                {
                                    "region_id": "hero",
                                    "label": "Hero content",
                                    "role": "section",
                                    "bbox": {"x": 20, "y": 180, "w": 520, "h": 260},
                                }
                            ]
                        },
                    },
                },
                "expected": {
                    "inventory_min_count": 2,
                    "actionable_labels": ["Search"],
                    "semantic_without_interactable_labels": ["Hero content"],
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    support = report["support_eligibility_summary"]
    assert support["total_candidates"] == 2
    assert support["grounding_eligible_candidates"] == 1
    assert support["same_screenshot_interactable_support"] == 1
    assert support["same_screenshot_support_rate"] == 0.5
    assert support["by_source_type"] == {"qwen_vlm": 1, "uia": 1}
    assert support["by_evidence_kind"] == {"semantic_region": 1, "uia_interactable": 1}
    case_support = report["case_results"][0]["support_eligibility"]
    assert case_support["coverage_status"] == "covered"
    assert case_support["semantic_or_ocr_leakage_safe"] is True


def test_recorded_parser_top_level_checksum_feeds_support_eligibility(tmp_path):
    recorded_parser = {
        "contract_version": "recorded_parser_output_v1",
        "screenshot_sha256": "c" * 64,
        "observe_bundle": {
            "contract_version": "learn_observe_bundle_v1",
            "screen_size": {"width": 900, "height": 600},
            "sources": {
                "uia": {
                    "controls": [
                        {
                            "name": "Search",
                            "control_type": "Button",
                            "bbox": {"x": 120, "y": 80, "w": 90, "h": 32},
                            "patterns": ["Invoke"],
                        }
                    ]
                }
            },
        },
    }
    parser_path = tmp_path / "recorded_parser.json"
    parser_path.write_text(json.dumps(recorded_parser, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "cases": [
            {
                "case_id": "recorded_same_screenshot_support",
                "source_type": "recorded_parser_output",
                "recorded_parser_output_path": str(parser_path),
                "expected": {"actionable_labels": ["Search"]},
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    support = report["support_eligibility_summary"]
    assert support["same_screenshot_interactable_support"] == 1
    assert support["same_screenshot_support_rate"] == 1.0
    assert report["case_results"][0]["support_eligibility"]["same_screenshot_interactable_support"] == 1


def test_learn_recognition_benchmark_loads_recorded_parser_and_grounding_outputs(tmp_path):
    recorded_parser = {
        "contract_version": "recorded_parser_output_v1",
        "provider": "sample_recorded_parser",
        "observe_bundle": {
            "contract_version": "learn_observe_bundle_v1",
            "screen_size": {"width": 900, "height": 600},
            "sources": {
                "vision": {
                    "regions": [
                        {
                            "label": "Hero code sample",
                            "role": "card",
                            "bbox": {"x": 100, "y": 120, "w": 300, "h": 180},
                        }
                    ]
                }
            },
        },
    }
    recorded_grounding = {
        "contract_version": "recorded_grounding_output_v1",
        "provider": "sample_recorded_grounding",
        "grounding_by_label": {
            "Search": {
                "screen_point": {"x": 214, "y": 76},
                "screen_bbox": {"x": 180, "y": 60, "w": 90, "h": 32},
                "evidence": {
                    "coordinate_transform_replay": True,
                    "screenshot_freshness": True,
                    "uia_or_dom_or_parser_overlap": True,
                },
            }
        },
    }
    parser_path = tmp_path / "recorded_parser.json"
    grounding_path = tmp_path / "recorded_grounding.json"
    parser_path.write_text(json.dumps(recorded_parser, ensure_ascii=False), encoding="utf-8")
    grounding_path.write_text(json.dumps(recorded_grounding, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "cases": [
            {
                "case_id": "recorded_parser_semantic_rejection",
                "source_type": "recorded_parser_output",
                "recorded_parser_output_path": str(parser_path),
                "expected": {
                    "inventory_min_count": 1,
                    "semantic_without_interactable_labels": ["Hero code sample"],
                    "not_grounded_labels": ["Hero code sample"],
                },
            },
            {
                "case_id": "recorded_grounding_search_point",
                "source_type": "recorded_grounding_output",
                "recorded_grounding_output_path": str(grounding_path),
                "observe_bundle": {
                    "screen_size": {"width": 900, "height": 600},
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "name": "Search",
                                    "control_type": "Button",
                                    "bbox": {"x": 180, "y": 60, "w": 90, "h": 32},
                                    "patterns": ["Invoke"],
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "inventory_min_count": 1,
                    "actionable_labels": ["Search"],
                    "grounding_valid_labels": ["Search"],
                },
            },
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["source_breakdown"]["fixture_only"] == 0
    assert report["source_breakdown"]["recorded_parser_output"] == 1
    assert report["source_breakdown"]["recorded_grounding_output"] == 1
    assert report["parser_reliability_status"] == "recorded_parser_output_minimal_coverage"
    assert report["grounding_reliability_status"] == "recorded_grounding_output_minimal_coverage"
    assert "not a new actual model call" in report["recorded_output_interpretation"]
    assert report["metrics"]["semantic_bbox_without_interactable_evidence"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["semantic_only_rejection"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["grounding_point"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert report["case_results"][0]["source_artifacts"]["recorded_parser_output_path"] == str(parser_path)
    assert report["case_results"][1]["source_artifacts"]["recorded_grounding_output_path"] == str(grounding_path)


def test_learn_recognition_benchmark_restores_uground_normalized_roi_point(tmp_path):
    recorded_grounding = {
        "contract_version": "recorded_grounding_output_v1",
        "provider": "uground_style_recorded_output",
        "grounding_by_label": {
            "Search": {
                "coordinate_space": "uground_0_999",
                "raw_output": "(500, 500)",
                "evidence": {
                    "screenshot_freshness": True,
                    "uia_or_dom_or_parser_overlap": True,
                },
            }
        },
    }
    grounding_path = tmp_path / "uground_recorded_grounding.json"
    grounding_path.write_text(json.dumps(recorded_grounding, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "cases": [
            {
                "case_id": "uground_style_roi_point",
                "source_type": "recorded_grounding_output",
                "recorded_grounding_output_path": str(grounding_path),
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
                "expected": {
                    "actionable_labels": ["Search"],
                    "grounding_valid_labels": ["Search"],
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert report["metrics"]["grounding_point"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    validation = report["case_results"][0]["status"]
    assert validation == "draft_ready"


def test_learn_recognition_benchmark_covers_pathgraph_candidate_validation(tmp_path):
    manifest = {
        "cases": [
            {
                "case_id": "pathgraph_candidate_ok",
                "surface": "python_homepage",
                "goal": "Validate draft to pathgraph candidate safety path.",
                "observe_bundle": {
                    "screen_size": {"width": 1280, "height": 720},
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "name": "Search",
                                    "control_type": "Button",
                                    "bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                                    "patterns": ["Invoke"],
                                }
                            ]
                        }
                    },
                },
                "expected": {
                    "actionable_labels": ["Search"],
                    "grounding_valid_labels": ["Search"],
                    "pathgraph_candidate_validation_status": "passed_candidate",
                },
                "review_patch": {
                    "blockers": [{"blocker_id": "final_submit", "label": "Final submit remains blocked"}],
                    "verification_rules": [{"rule_id": "search_visible", "label": "Search button remains visible"}],
                    "review_status": "approved_as_assisted_template",
                },
                "grounding": {
                    "Search": {
                        "screen_point": {"x": 1024, "y": 158},
                        "screen_bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                        "evidence": {
                            "coordinate_transform_replay": True,
                            "screenshot_freshness": True,
                            "uia_or_dom_or_parser_overlap": True,
                        },
                    }
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out", project_root=tmp_path)

    assert report["metrics"]["pathgraph_candidate_validation"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    case = report["case_results"][0]
    assert case["metrics"]["pathgraph_candidate_validation"] == "passed"
    assert case["pathgraph_candidate"]["validation_status"] == "passed_candidate"
    assert case["pathgraph_candidate"]["execute_binding_enabled"] is False


def test_learn_recognition_benchmark_reports_recorded_model_profile_breakdown(tmp_path):
    recorded_parser = {
        "contract_version": "recorded_parser_output_v1",
        "model_profile": {
            "profile_id": "learn_mode_qwen3_vl_8b",
            "model_id": "Qwen/Qwen3-VL-8B-Instruct",
            "provider_mode": "local_understanding",
        },
        "actual_model_call_in_this_run": True,
        "observe_bundle": {
            "contract_version": "learn_observe_bundle_v1",
            "screen_size": {"width": 500, "height": 400},
            "sources": {
                "vision": {
                    "regions": [
                        {
                            "label": "Hero code sample",
                            "role": "card",
                            "bbox": {"x": 60, "y": 80, "w": 220, "h": 140},
                        }
                    ]
                }
            },
        },
    }
    recorded_grounding = {
        "contract_version": "recorded_grounding_output_v1",
        "provider": "uground_v1_recorded_contract_sample",
        "model_profile_id": "learn_mode_uground_2b",
        "model_id": "osunlp/UGround-V1-2B",
        "actual_model_call_in_this_run": False,
        "grounding_by_label": {
            "Search": {
                "coordinate_space": "uground_0_999",
                "raw_output": "(500, 500)",
                "evidence": {
                    "screenshot_freshness": True,
                    "uia_or_dom_or_parser_overlap": True,
                },
            }
        },
    }
    parser_path = tmp_path / "qwen8b_recorded_parser.json"
    grounding_path = tmp_path / "uground_2b_recorded_grounding.json"
    parser_path.write_text(json.dumps(recorded_parser, ensure_ascii=False), encoding="utf-8")
    grounding_path.write_text(json.dumps(recorded_grounding, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "cases": [
            {
                "case_id": "qwen8b_profile_breakdown",
                "source_type": "recorded_parser_output",
                "recorded_parser_output_path": str(parser_path),
                "expected": {
                    "inventory_min_count": 1,
                    "semantic_without_interactable_labels": ["Hero code sample"],
                    "not_grounded_labels": ["Hero code sample"],
                },
            },
            {
                "case_id": "uground_2b_profile_breakdown",
                "source_type": "recorded_grounding_output",
                "recorded_grounding_output_path": str(grounding_path),
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
                "expected": {
                    "actionable_labels": ["Search"],
                    "grounding_valid_labels": ["Search"],
                },
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out", project_root=tmp_path)

    assert report["recorded_model_profile_breakdown"]["recorded_parser_output"] == {
        "learn_mode_qwen3_vl_8b": 1
    }
    assert report["recorded_model_profile_breakdown"]["recorded_grounding_output"] == {
        "learn_mode_uground_2b": 1
    }
    parser_case = report["case_results"][0]
    assert parser_case["recorded_model_profile"] == {
        "profile_id": "learn_mode_qwen3_vl_8b",
        "model_id": "Qwen/Qwen3-VL-8B-Instruct",
        "provider": "local_understanding",
        "source_type": "recorded_parser_output",
        "actual_model_call_in_this_run": True,
    }
    grounding_case = report["case_results"][1]
    assert grounding_case["recorded_model_profile"] == {
        "profile_id": "learn_mode_uground_2b",
        "model_id": "osunlp/UGround-V1-2B",
        "provider": "uground_v1_recorded_contract_sample",
        "source_type": "recorded_grounding_output",
        "actual_model_call_in_this_run": False,
    }


def test_repository_learn_recognition_manifest_has_expanded_case_set():
    manifest_path = PROJECT_ROOT / "artifacts" / "benchmarks" / "learn_recognition_golden_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_ids = [case["case_id"] for case in manifest["cases"]]

    assert len(case_ids) >= 20
    assert len(case_ids) == len(set(case_ids))
    assert "form_email_field_classified" in case_ids
    assert "grounding_point_outside_bbox_failure" in case_ids
    assert "recorded_grounding_uground_7b_seek_search_button_point_valid" in case_ids
    assert "recorded_grounding_gui_actor_7b_seek_pay_filter_point_valid" in case_ids
    assert "grounding_missing_transform_failure" in case_ids
    assert "wrong_surface_browser_chrome_rejected" in case_ids
    assert "semantic_bbox_without_interactable_evidence" in case_ids
    assert "semantic_region_uia_cross_evidence_grounded" in case_ids
    assert "pathgraph_candidate_validation_ok" in case_ids
    assert "recorded_parser_semantic_region_rejected" in case_ids
    assert "recorded_grounding_search_point_valid" in case_ids
    assert "recorded_parser_omniparser_style_search_action" in case_ids
    assert "recorded_parser_omniparser_style_form_fields" in case_ids
    assert "recorded_parser_omniparser_style_final_submit_danger" in case_ids
    assert "recorded_parser_execute_candidate_docs_search" in case_ids
    assert "recorded_parser_execute_candidate_google_news_home" in case_ids
    assert "recorded_parser_seek_search_header_controls" in case_ids
    assert "recorded_parser_qwen8b_python_homepage_semantic_only" in case_ids
    assert "recorded_parser_qwen8b_learn_profile_python_homepage_semantic_only" in case_ids
    assert "recorded_grounding_uground_style_roi_point_valid" in case_ids
    assert "recorded_grounding_uground_2b_search_point_valid" in case_ids
    assert "recorded_grounding_uground_7b_apply_now_point_valid" in case_ids
    assert "roi_edge_top_left_button_grounded" in case_ids
    assert "roi_edge_bottom_right_button_grounded" in case_ids
    assert "form_search_input_roi_covered" in case_ids
    assert "wrong_surface_login_overlay_rejected" in case_ids
    assert "wrong_surface_cookie_overlay_rejected" in case_ids
