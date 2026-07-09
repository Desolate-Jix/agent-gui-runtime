from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.report_learn_recognition_pathgraph_readiness_diagnosis import (
    build_pathgraph_readiness_diagnosis,
)


def test_pathgraph_readiness_diagnosis_reports_blocked_case_root_cause(tmp_path: Path) -> None:
    status_report = tmp_path / "status.json"
    status_report.write_text(
        json.dumps(
            {
                "pathgraph_connection_readiness": {
                    "status": "not_ready_for_pathgraph_candidate_promotion",
                    "ready_cases": ["ready_case"],
                    "blocked_cases": ["blocked_case"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser_batch = tmp_path / "parser_batch.json"
    parser_batch.write_text(
        json.dumps(
            {
                "case_results": [
                    {
                        "case_id": "ready_case",
                        "screenshot_path": "screenshots/ready.png",
                        "report_path": "logs/ready/learn_actual_parser_smoke_report.json",
                        "supplemental_sources_path": "support/ready.json",
                        "supplemental_source_validity": {"status": "checksum_match"},
                        "parser_actual_call_usefulness": {
                            "parser_inventory_generated": True,
                            "parser_useful_for_review": True,
                            "parser_useful_for_grounding": True,
                            "semantic_only_regions": 1,
                            "grounding_eligible_regions": 3,
                            "accepted_for_grounding": 3,
                            "blocked_from_grounding_reason": "",
                        },
                    },
                    {
                        "case_id": "blocked_case",
                        "screenshot_path": "screenshots/blocked.png",
                        "report_path": "logs/blocked/learn_actual_parser_smoke_report.json",
                        "supplemental_sources_path": "",
                        "supplemental_source_validity": {"status": "not_provided"},
                        "parser_actual_call_usefulness": {
                            "parser_inventory_generated": True,
                            "parser_useful_for_review": True,
                            "parser_useful_for_grounding": False,
                            "semantic_only_regions": 12,
                            "grounding_eligible_regions": 0,
                            "accepted_for_grounding": 0,
                            "blocked_from_grounding_reason": "semantic_region_only_without_interactable_evidence",
                        },
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "ready_case",
                        "surface": "python_homepage",
                        "goal": "ready goal",
                        "screenshot_path": "screenshots/ready.png",
                    },
                    {
                        "case_id": "blocked_case",
                        "surface": "seek_results",
                        "goal": "blocked goal",
                        "screenshot_path": "screenshots/blocked.png",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_pathgraph_readiness_diagnosis(
        status_report_path=status_report,
        parser_batch_report_path=parser_batch,
        manifest_path=manifest,
        out_dir=tmp_path / "out",
    )

    assert report["contract_version"] == "learn_pathgraph_readiness_blocker_diagnosis_v1"
    assert report["summary"] == {
        "readiness_status": "not_ready_for_pathgraph_candidate_promotion",
        "ready_case_count": 1,
        "blocked_case_count": 1,
        "ready_for_pathgraph_candidate_review": False,
    }
    assert report["ready_cases"][0]["case_id"] == "ready_case"
    assert report["ready_cases"][0]["pathgraph_action"] == "candidate_review_allowed"
    blocked = report["blocked_cases"][0]
    assert blocked["case_id"] == "blocked_case"
    assert blocked["surface"] == "seek_results"
    assert blocked["screenshot_path"] == "screenshots/blocked.png"
    assert blocked["screenshot_sha256"] == ""
    assert blocked["actual_parser_smoke_report_path"] == "logs/blocked/learn_actual_parser_smoke_report.json"
    assert blocked["supplemental_source_validity_status"] == "not_provided"
    assert blocked["root_cause"] == "no_same_screenshot_interactable_support"
    assert blocked["failure_category"] == "no_grounding_candidate"
    assert blocked["pathgraph_action"] == "do_not_wire_to_pathgraph_candidate"
    assert blocked["proposed_fix"] == (
        "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox alignment before PathGraph wiring"
    )
    assert blocked["safety_impact"] == (
        "keeping this case blocked preserves no-click/no-Execute safety because semantic-only regions cannot become actions"
    )
    repair_target = report["support_repair_targets"][0]
    assert repair_target["case_id"] == "blocked_case"
    assert repair_target["case_locked_by_sha256"] is False
    assert repair_target["current_status"] == "semantic_only_without_same_screenshot_interactable_support"
    assert repair_target["acceptance_criteria"]["support_artifact_screenshot_sha256_must_match"] is True
    assert repair_target["acceptance_criteria"]["near_miss_support_counts_as_interactable_support"] is False
    assert repair_target["acceptance_criteria"]["pathgraph_promotion_allowed"] is False
    assert repair_target["acceptance_criteria"]["execute_binding_enabled"] is False
    assert Path(report["report_path"]).exists()


def test_pathgraph_readiness_diagnosis_reports_same_screenshot_support_discovery(tmp_path: Path) -> None:
    screenshot = tmp_path / "blocked.png"
    Image.new("RGB", (12, 8), "white").save(screenshot)
    status_report = tmp_path / "status.json"
    status_report.write_text(
        json.dumps(
            {
                "pathgraph_connection_readiness": {
                    "status": "not_ready_for_pathgraph_candidate_promotion",
                    "ready_cases": [],
                    "blocked_cases": ["blocked_case"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser_batch = tmp_path / "parser_batch.json"
    parser_batch.write_text(
        json.dumps(
            {
                "case_results": [
                    {
                        "case_id": "blocked_case",
                        "screenshot_path": str(screenshot),
                        "supplemental_source_validity": {"status": "not_provided"},
                        "parser_actual_call_usefulness": {
                            "parser_inventory_generated": True,
                            "parser_useful_for_grounding": False,
                            "grounding_eligible_regions": 0,
                            "accepted_for_grounding": 0,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "blocked_case",
                        "surface": "python_homepage",
                        "screenshot_path": str(screenshot),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    checksum = _sha256_file(screenshot)
    (support_root / "same_image_no_support.json").write_text(
        json.dumps({"screenshot_sha256": checksum, "sources": {"vision": {"regions": []}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (support_root / "same_image_with_support.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {"calibrated_targets": {"targets": [{"label": "Search", "bbox": {"x": 1, "y": 1, "w": 4, "h": 3}}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_pathgraph_readiness_diagnosis(
        status_report_path=status_report,
        parser_batch_report_path=parser_batch,
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        support_search_roots=[support_root],
    )

    audit = report["support_discovery"]
    assert audit["search_complete"] is True
    assert audit["searched_roots"] == [str(support_root)]
    assert audit["json_files_scanned"] == 2
    assert audit["support_candidate_file_count"] == 1
    assert audit["indexed_checksum_count"] == 1
    discovery = report["blocked_cases"][0]["same_screenshot_support_discovery"]
    assert discovery["status"] == "matching_interactable_support_found"
    assert discovery["screenshot_sha256"] == checksum
    assert report["blocked_cases"][0]["screenshot_sha256"] == checksum
    assert discovery["matching_source_count"] == 2
    assert discovery["interactable_support_count"] == 1
    assert discovery["interactable_support_paths"] == [str(support_root / "same_image_with_support.json")]
    assert discovery["support_details"][0]["support_type"] == "calibrated_targets"
    assert discovery["support_details"][0]["artifact_is_authorization"] is False
    assert report["blocked_cases"][0]["not_prompt_tuning_issue"] is True
    assert report["blocked_cases"][0]["block_reason"] == "semantic_only_without_same_screenshot_interactable_support"
    assert report["blocked_cases"][0]["bbox_alignment_audit"]["status"] == "not_evaluated_no_parser_inventory"
    assert "capture_same_screenshot_uia" in report["blocked_cases"][0]["recommended_next_evidence"]
    target = report["support_repair_targets"][0]
    assert target["case_id"] == "blocked_case"
    assert target["screenshot_sha256"] == checksum
    assert target["case_locked_by_sha256"] is True
    assert target["same_screenshot_support_status"] == "matching_interactable_support_found"
    assert target["interactable_support_count"] == 1
    assert target["bbox_alignment_status"] == "not_evaluated_no_parser_inventory"
    assert target["acceptance_criteria"]["bbox_alignment_required_before_grounding_eligible"] is True
    assert target["acceptance_criteria"]["semantic_or_ocr_leaked_to_grounding_must_remain"] == 0
    assert target["next_checkpoint"] == "same_screenshot_support_repair_v1"


def test_pathgraph_readiness_diagnosis_evaluates_support_bbox_alignment(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), "white").save(screenshot)
    checksum = _sha256_file(screenshot)
    actual_output = tmp_path / "actual_parser_output_v1.json"
    actual_output.write_text(
        json.dumps(
            {
                "screen_inventory": [
                    {
                        "item_id": "vision_search",
                        "label": "Search",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 40, "y": 20, "w": 80, "h": 30},
                        "review_only": True,
                        "grounding_eligible": False,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    (support_root / "aligned_uia.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {
                    "uia": {
                        "controls": [
                            {
                                "name": "Search",
                                "control_type": "Button",
                                "bbox": {"x": 42, "y": 22, "w": 78, "h": 28},
                                "patterns": ["Invoke"],
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = _build_single_blocked_report(
        tmp_path,
        screenshot=screenshot,
        actual_output=actual_output,
        support_root=support_root,
    )

    audit = report["blocked_cases"][0]["bbox_alignment_audit"]
    assert audit["status"] == "bbox_alignment_passed"
    assert audit["attempted"] == 1
    assert audit["passed"] == 1
    assert audit["best_matches"][0]["support"]["support_type"] == "uia"
    assert audit["best_matches"][0]["bbox_alignment"]["passed"] is True
    assert audit["pathgraph_promotion_allowed"] is False
    assert audit["execute_binding_enabled"] is False
    assert report["support_repair_targets"][0]["bbox_alignment_status"] == "bbox_alignment_passed"


def test_pathgraph_readiness_diagnosis_keeps_misaligned_support_blocked(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), "white").save(screenshot)
    checksum = _sha256_file(screenshot)
    actual_output = tmp_path / "actual_parser_output_v1.json"
    actual_output.write_text(
        json.dumps(
            {
                "screen_inventory": [
                    {
                        "item_id": "vision_search",
                        "label": "Search",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 40, "y": 20, "w": 80, "h": 30},
                        "review_only": True,
                        "grounding_eligible": False,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    (support_root / "misaligned_uia.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {
                    "uia": {
                        "controls": [
                            {
                                "name": "Search",
                                "control_type": "Button",
                                "bbox": {"x": 150, "y": 80, "w": 30, "h": 20},
                                "patterns": ["Invoke"],
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = _build_single_blocked_report(
        tmp_path,
        screenshot=screenshot,
        actual_output=actual_output,
        support_root=support_root,
    )

    audit = report["blocked_cases"][0]["bbox_alignment_audit"]
    assert audit["status"] == "support_found_but_bbox_alignment_failed"
    assert audit["attempted"] == 1
    assert audit["passed"] == 0
    assert audit["best_matches"][0]["bbox_alignment"]["passed"] is False
    assert report["support_repair_targets"][0]["bbox_alignment_status"] == "support_found_but_bbox_alignment_failed"
    assert report["support_repair_targets"][0]["acceptance_criteria"]["pathgraph_promotion_allowed"] is False


def test_pathgraph_readiness_diagnosis_classifies_raw_model_bbox_miss_before_remap(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), "white").save(screenshot)
    checksum = _sha256_file(screenshot)
    actual_output = tmp_path / "actual_parser_output_v1.json"
    raw_text = json.dumps(
        {
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 100, "height": 60},
            "regions": [
                {
                    "region_id": "vision_search",
                    "label": "Search",
                    "role": "input",
                    "diagonal": {"x1": 20, "y1": 10, "x2": 60, "y2": 25},
                }
            ],
        },
        ensure_ascii=False,
    )
    actual_output.write_text(
        json.dumps(
            {
                "observe_bundle": {
                    "sources": {
                        "vision": {
                            "raw_response": {
                                "attempts": [
                                    {
                                        "tag": "fast_observation",
                                        "model_io": {
                                            "attempt": {"tag": "fast_observation"},
                                            "input": {
                                                "original_image_size": {"width": 200, "height": 120},
                                                "inference_image_size": {"width": 100, "height": 60},
                                            },
                                            "output": {"raw_text": raw_text},
                                        },
                                    }
                                ]
                            }
                        }
                    }
                },
                "screen_inventory": [
                    {
                        "item_id": "vision_search",
                        "label": "Search",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 40, "y": 20, "w": 80, "h": 30},
                        "review_only": True,
                        "grounding_eligible": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    (support_root / "misaligned_calibrated.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {
                    "calibrated_targets": {
                        "targets": [
                            {
                                "label": "Search",
                                "role": "text_input",
                                "bbox": {"x": 150, "y": 80, "w": 30, "h": 20},
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = _build_single_blocked_report(
        tmp_path,
        screenshot=screenshot,
        actual_output=actual_output,
        support_root=support_root,
    )

    audit = report["blocked_cases"][0]["bbox_alignment_audit"]
    blocked = report["blocked_cases"][0]
    match = audit["best_matches"][0]
    diagnosis = match["coordinate_diagnosis"]
    assert blocked["root_cause"] == "parser_bbox_alignment_failed"
    assert blocked["block_reason"] == "same_screenshot_support_found_but_parser_bbox_alignment_failed"
    assert blocked["not_prompt_tuning_issue"] is False
    assert blocked["not_pathgraph_wiring_issue"] is True
    assert blocked["proposed_fix"] == "fix actual parser bbox/coordinate output or use an alternative ROI/parser locator before PathGraph wiring"
    assert audit["status"] == "support_found_but_bbox_alignment_failed"
    assert audit["coordinate_failure_categories"] == {"raw_model_bbox_misaligned_before_remap": 1}
    assert diagnosis["failure_category"] == "raw_model_bbox_misaligned_before_remap"
    assert diagnosis["raw_model_bbox_in_inference_space"] == {"x": 20, "y": 10, "w": 40, "h": 15}
    assert diagnosis["support_bbox_projected_to_inference_space"] == {"x": 75, "y": 40, "w": 15, "h": 10}
    assert diagnosis["raw_model_vs_projected_support_alignment"]["passed"] is False
    assert diagnosis["remapped_parser_vs_support_alignment"]["passed"] is False


def test_pathgraph_readiness_diagnosis_reports_implicit_normalized_1000_recovery_candidate(tmp_path: Path) -> None:
    screenshot = tmp_path / "python_home.png"
    Image.new("RGB", (2521, 1300), "white").save(screenshot)
    checksum = _sha256_file(screenshot)
    actual_output = tmp_path / "actual_parser_output_v1.json"
    raw_text = json.dumps(
        {
            "contract_version": "vision_regions_v1",
            "image_size": {"width": 1280, "height": 660},
            "regions": [
                {
                    "region_id": "vision_search",
                    "label": "Search input",
                    "role": "input",
                    "diagonal": {"x1": 568, "y1": 68, "x2": 666, "y2": 88},
                }
            ],
        },
        ensure_ascii=False,
    )
    actual_output.write_text(
        json.dumps(
            {
                "observe_bundle": {
                    "sources": {
                        "vision": {
                            "raw_response": {
                                "attempts": [
                                    {
                                        "tag": "fast_observation",
                                        "model_io": {
                                            "attempt": {"tag": "fast_observation"},
                                            "input": {
                                                "original_image_size": {"width": 2521, "height": 1300},
                                                "inference_image_size": {"width": 1280, "height": 660},
                                            },
                                            "output": {"raw_text": raw_text},
                                        },
                                    }
                                ]
                            }
                        }
                    }
                },
                "screen_inventory": [
                    {
                        "item_id": "vision_search",
                        "label": "Search input",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 1119, "y": 134, "w": 193, "h": 39},
                        "review_only": True,
                        "grounding_eligible": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    (support_root / "calibrated_search.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {
                    "calibrated_targets": {
                        "targets": [
                            {
                                "label": "Search input",
                                "role": "text_input",
                                "bbox": {"x": 1454, "y": 90, "w": 222, "h": 36},
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = _build_single_blocked_report(
        tmp_path,
        screenshot=screenshot,
        actual_output=actual_output,
        support_root=support_root,
    )

    audit = report["blocked_cases"][0]["bbox_alignment_audit"]
    blocked = report["blocked_cases"][0]
    diagnosis = audit["best_matches"][0]["coordinate_diagnosis"]
    recovery = diagnosis["coordinate_recovery_candidate"]
    assert blocked["root_cause"] == "coordinate_space_recovery_needed"
    assert blocked["block_reason"] == "same_screenshot_support_found_but_coordinate_recovery_not_applied"
    assert blocked["not_prompt_tuning_issue"] is True
    assert blocked["not_pathgraph_wiring_issue"] is True
    assert blocked["proposed_fix"] == (
        "rerun Learn Recognition actual parser with opt-in implicit normalized_1000 coordinate recovery, "
        "then recheck same-screenshot support alignment before PathGraph wiring"
    )
    assert audit["status"] == "support_found_but_bbox_alignment_failed"
    assert audit["coordinate_failure_categories"] == {"implicit_normalized_1000_recovery_needed": 1}
    assert diagnosis["failure_category"] == "implicit_normalized_1000_recovery_needed"
    assert diagnosis["raw_model_vs_projected_support_alignment"]["passed"] is False
    assert diagnosis["remapped_parser_vs_support_alignment"]["passed"] is False
    assert recovery["recovered_bbox_in_inference_space"] == {"x": 727, "y": 45, "w": 125, "h": 13}
    assert recovery["recovered_vs_projected_support_alignment"]["passed"] is True
    assert recovery["alignment_improved"] is True
    assert recovery["artifact_is_authorization"] is False
    assert recovery["execute_binding_enabled"] is False


def test_pathgraph_readiness_diagnosis_uses_label_tiebreaker_when_overlap_is_zero(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (200, 120), "white").save(screenshot)
    checksum = _sha256_file(screenshot)
    actual_output = tmp_path / "actual_parser_output_v1.json"
    actual_output.write_text(
        json.dumps(
            {
                "screen_inventory": [
                    {
                        "item_id": "c1",
                        "label": "Search input",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 10, "y": 10, "w": 20, "h": 20},
                    },
                    {
                        "item_id": "c2",
                        "label": "Search button",
                        "source_evidence": ["vision"],
                        "bbox": {"x": 40, "y": 10, "w": 20, "h": 20},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    support_root = tmp_path / "support"
    support_root.mkdir()
    (support_root / "button_support.json").write_text(
        json.dumps(
            {
                "screenshot_sha256": checksum,
                "sources": {
                    "calibrated_targets": {
                        "targets": [
                            {
                                "label": "GO search button",
                                "role": "button",
                                "bbox": {"x": 160, "y": 90, "w": 20, "h": 20},
                            }
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = _build_single_blocked_report(
        tmp_path,
        screenshot=screenshot,
        actual_output=actual_output,
        support_root=support_root,
    )

    match = report["blocked_cases"][0]["bbox_alignment_audit"]["best_matches"][0]
    assert match["parser_candidate"]["item_id"] == "c2"
    assert match["parser_candidate"]["label"] == "Search button"
    assert match["bbox_alignment"]["passed"] is False


def _build_single_blocked_report(
    tmp_path: Path,
    *,
    screenshot: Path,
    actual_output: Path,
    support_root: Path,
) -> dict:
    status_report = tmp_path / "status.json"
    status_report.write_text(
        json.dumps(
            {
                "pathgraph_connection_readiness": {
                    "status": "not_ready_for_pathgraph_candidate_promotion",
                    "ready_cases": [],
                    "blocked_cases": ["blocked_case"],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser_batch = tmp_path / "parser_batch.json"
    parser_batch.write_text(
        json.dumps(
            {
                "case_results": [
                    {
                        "case_id": "blocked_case",
                        "screenshot_path": str(screenshot),
                        "screenshot_sha256": _sha256_file(screenshot),
                        "actual_parser_output_path": str(actual_output),
                        "supplemental_source_validity": {"status": "not_provided"},
                        "parser_actual_call_usefulness": {
                            "parser_inventory_generated": True,
                            "parser_useful_for_review": True,
                            "parser_useful_for_grounding": False,
                            "semantic_only_regions": 1,
                            "grounding_eligible_regions": 0,
                            "accepted_for_grounding": 0,
                            "blocked_from_grounding_reason": "semantic_region_only_without_interactable_evidence",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "blocked_case",
                        "surface": "test_surface",
                        "screenshot_path": str(screenshot),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return build_pathgraph_readiness_diagnosis(
        status_report_path=status_report,
        parser_batch_report_path=parser_batch,
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        support_search_roots=[support_root],
    )


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
