from __future__ import annotations

import json
import hashlib
from pathlib import Path

from PIL import Image

import scripts.run_learn_recognition_actual_parser_batch as parser_batch
from scripts.run_learn_recognition_actual_parser_batch import run_actual_parser_batch


def test_actual_parser_batch_aggregates_passed_and_failed_actual_calls(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (320, 240), "white").save(first)
    Image.new("RGB", (320, 240), "white").save(second)
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps(
            {
                "contract_version": "learn_actual_parser_case_manifest_v1",
                "cases": [
                    {
                        "case_id": "homepage_search",
                        "screenshot_path": str(first),
                        "app_name": "python",
                        "state_hint": "homepage",
                        "goal": "parse visible search controls",
                    },
                    {
                        "case_id": "empty_output",
                        "screenshot_path": str(second),
                        "app_name": "empty",
                        "state_hint": "empty",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        if image_path == second:
            return {
                "provider": "fake-qwen",
                "contract_version": "vision_regions_v1",
                "screen_summary": "empty",
                "state_guess": "empty",
                "regions": [],
            }
        return {
            "provider": "fake-qwen",
            "contract_version": "vision_regions_v1",
            "screen_summary": "Search page",
            "state_guess": "homepage",
            "regions": [
                {
                    "region_id": "search",
                    "label": "Search",
                    "role": "input",
                    "diagonal": {"x1": 20, "y1": 30, "x2": 220, "y2": 70},
                    "confidence": 0.9,
                }
            ],
        }

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
        model_caller=fake_model_caller,
    )

    assert report["contract_version"] == "learn_actual_parser_batch_report_v1"
    assert report["metrics"]["actual_parser_call"] == {"passed": 1, "attempted": 2, "rate": 0.5}
    assert report["totals"]["passed"] == 1
    assert report["totals"]["failed"] == 1
    assert report["source_breakdown"]["actual_parser_call"] == 2
    assert report["source_breakdown"]["fixture_only"] == 0
    assert report["case_results"][0]["status"] == "passed"
    assert report["case_results"][1]["status"] == "failed"
    assert report["case_results"][0]["screenshot_sha256"] == _sha256_file(first)
    assert report["case_results"][1]["screenshot_sha256"] == _sha256_file(second)
    assert report["support_eligibility_summary"]["total_candidates"] == 1
    assert report["support_eligibility_summary"]["by_source_type"] == {"qwen_vlm": 1}
    assert report["support_eligibility_summary"]["semantic_or_ocr_leaked_to_grounding"] == 0
    assert report["case_results"][0]["support_eligibility_summary"]["total_candidates"] == 1
    assert report["layout_cleanup_summary"]["suppressed_count"] == 0
    assert report["layout_cleanup_summary"]["suppression_reason_counts"] == {}
    assert report["case_results"][0]["layout_cleanup"]["suppression_reason_counts"] == {}
    assert Path(report["case_results"][0]["report_path"]).exists()
    assert report["safety"]["real_clicks_performed"] == 0
    assert "not a 90% recognition claim" in report["interpretation"]


def test_actual_parser_batch_blocked_cases_do_not_enter_actual_denominator(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (100, 80), "white").save(screenshot)
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "missing_endpoint",
                        "screenshot_path": str(screenshot),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint=None,
        model_name="missing-endpoint",
    )

    assert report["totals"]["blocked"] == 1
    assert report["metrics"]["actual_parser_call"] == {"passed": 0, "attempted": 0, "rate": "not_covered"}
    assert report["source_breakdown"]["actual_parser_call"] == 0
    assert report["case_results"][0]["actual_model_call_in_this_run"] is False


def test_actual_parser_batch_can_start_and_stop_requested_profile(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(screenshot)
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "started_profile_case", "screenshot_path": str(screenshot)}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    starts: list[dict] = []
    stops: list[dict] = []

    def fake_ensure_model_server(**kwargs):
        starts.append(kwargs)
        return {
            "started": True,
            "before": {"status": "unreachable"},
            "after": {"status": "running"},
            "profile": {"profile_id": "learn_mode_qwen3_vl_8b", "port": 1240},
            "start": {"pid": 1234},
        }

    def fake_stop_model_server(profile):
        stops.append(profile)
        return {"stopped": True, "returncode": 0, "after": {"status": "unreachable"}}

    monkeypatch.setattr(parser_batch, "ensure_model_server", fake_ensure_model_server)
    monkeypatch.setattr(parser_batch, "stop_model_server", fake_stop_model_server)

    def fake_model_caller(image_path: Path, model_config: dict) -> dict:
        return {
            "provider": "fake-qwen",
            "contract_version": "vision_regions_v1",
            "regions": [
                {
                    "region_id": "button",
                    "label": "Search",
                    "role": "button",
                    "diagonal": {"x1": 10, "y1": 10, "x2": 80, "y2": 40},
                }
            ],
        }

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1240/v1/chat/completions",
        model_profile_id="learn_mode_qwen3_vl_8b",
        start_profile=True,
        start_wait_seconds=12,
        model_caller=fake_model_caller,
    )

    assert starts[0]["stage"] == "observe"
    assert starts[0]["profile_id"] == "learn_mode_qwen3_vl_8b"
    assert starts[0]["wait_until_ready"] is True
    assert starts[0]["wait_seconds"] == 12
    assert stops == [{"profile_id": "learn_mode_qwen3_vl_8b", "port": 1240}]
    assert report["service_lifecycle"]["started_profile"]["started"] is True
    assert report["service_lifecycle"]["stop_started_profile_requested"] is True
    assert report["service_lifecycle"]["stop_result"]["stopped"] is True
    assert report["metrics"]["actual_parser_call"]["attempted"] == 1


def test_actual_parser_batch_reports_grounding_candidate_yield(monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (120, 80), "white").save(first)
    Image.new("RGB", (120, 80), "white").save(second)
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {"case_id": "has_grounding_candidate", "screenshot_path": str(first)},
                    {"case_id": "review_only_inventory", "screenshot_path": str(second)},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_smoke(**kwargs):
        case_id = Path(kwargs["out_dir"]).name
        if case_id == "has_grounding_candidate":
            counts = {
                "screen_inventory_count": 3,
                "accepted_for_grounding_count": 2,
                "grounding_eligible_count": 2,
                "review_only_count": 1,
                "layout_cleanup_suppressed_count": 2,
                "layout_cleanup_suppression_reason_counts": {"cross_evidence_support_duplicate": 2},
            }
            layout_cleanup = {
                "input_count": 5,
                "output_count": 3,
                "suppressed_count": 2,
                "duplicates_merged": 2,
                "suppression_reason_counts": {"cross_evidence_support_duplicate": 2},
            }
        else:
            counts = {
                "screen_inventory_count": 4,
                "accepted_for_grounding_count": 0,
                "grounding_eligible_count": 0,
                "review_only_count": 4,
                "layout_cleanup_suppressed_count": 1,
                "layout_cleanup_suppression_reason_counts": {"semantic_container_overlaps_interactable_children": 1},
            }
            layout_cleanup = {
                "input_count": 5,
                "output_count": 4,
                "suppressed_count": 1,
                "duplicates_merged": 0,
                "suppression_reason_counts": {"semantic_container_overlaps_interactable_children": 1},
            }
        support_eligibility_summary = {
            "contract_version": "learn_support_eligibility_summary_v1",
            "parser_candidate_contract": "parser_candidate_v1",
            "total_candidates": counts["screen_inventory_count"],
            "grounding_eligible_candidates": counts["grounding_eligible_count"],
            "review_only_candidates": counts["review_only_count"],
            "interactable_evidence_candidates": counts["grounding_eligible_count"],
            "same_screenshot_interactable_support": counts["grounding_eligible_count"],
            "semantic_or_ocr_candidates": counts["review_only_count"],
            "semantic_or_ocr_leaked_to_grounding": 0,
            "stale_candidates": 0,
            "missing_parser_candidate_contract": 0,
            "by_source_type": {"qwen_vlm": counts["review_only_count"], "uia": counts["grounding_eligible_count"]},
            "by_evidence_kind": {
                "semantic_region": counts["review_only_count"],
                "uia_interactable": counts["grounding_eligible_count"],
            },
            "blocked_reasons": (
                {"semantic_region_only_without_interactable_evidence": counts["review_only_count"]}
                if counts["review_only_count"]
                else {}
            ),
            "interpretation": "parser_candidate_v1 support eligibility is evidence routing only",
        }
        return {
            "status": "passed",
            "actual_model_call_in_this_run": True,
            "metrics": {
                "actual_parser_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                "parse_inventory": {"passed": 1, "attempted": 1, "rate": 1.0},
            },
            "counts": counts,
            "layout_cleanup": layout_cleanup,
            "support_eligibility_summary": support_eligibility_summary,
                "grounding_eligibility_gate": {
                "contract_version": "learn_grounding_eligibility_gate_report_v1",
                "evaluation_scope": "learn_mode_grounding_eligibility_gate",
                "execution_scope": "no_action_no_execute_no_live_click",
                "not_accuracy": True,
                "not_e2e_success": True,
                "not_execute_mode_default": True,
                "grounding_eligibility": {
                    "attempted": counts["screen_inventory_count"],
                    "eligible": counts["grounding_eligible_count"],
                    "blocked": counts["review_only_count"],
                },
                "semantic_only_rejection": {
                    "passed": counts["review_only_count"],
                    "attempted": counts["review_only_count"],
                    "rate": 1.0 if counts["review_only_count"] else "not_covered",
                },
                "ocr_only_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
                "non_actionable_leaked_to_grounding": {
                    "passed": 1,
                    "attempted": 1,
                    "rate": 1.0,
                    "leaked_count": 0,
                    "leaked_item_ids": [],
                },
                "browser_chrome_rejection": {
                    "passed": 1 if case_id == "review_only_inventory" else 0,
                    "attempted": 1 if case_id == "review_only_inventory" else 0,
                    "rate": 1.0 if case_id == "review_only_inventory" else "not_covered",
                },
                "split_roi_required": {
                    "attempted": 2 if case_id == "has_grounding_candidate" else 0,
                    "count": 2 if case_id == "has_grounding_candidate" else 0,
                    "item_ids": ["get_started", "download"] if case_id == "has_grounding_candidate" else [],
                },
                "grounding_eligible_breakdown": {
                    "semantic_only": 0,
                    "ocr_only": 0,
                    "uia_interactable": counts["grounding_eligible_count"],
                    "dom_interactable": 0,
                    "omniparser_interactable": 0,
                    "human_calibrated": 0,
                    "no_dispatch_execute_candidate": 0,
                    },
                },
                "layout_graph": {
                    "contract_version": "learn_layout_graph_v1",
                    "node_count": counts["screen_inventory_count"],
                    "zone_count": 2 if case_id == "has_grounding_candidate" else 1,
                    "zones": {
                        "browser_chrome": {"zone_id": "browser_chrome", "item_ids": []},
                        "page_header": {
                            "zone_id": "page_header",
                            "item_ids": ["get_started", "download"] if case_id == "has_grounding_candidate" else [],
                        },
                        "main_content": {
                            "zone_id": "main_content",
                            "item_ids": ["body_text"] if case_id == "review_only_inventory" else ["news"],
                        },
                    },
                    "overlap_clusters": [
                        {
                            "cluster_id": "overlap_cluster_1",
                            "item_ids": ["get_started", "download"],
                            "split_roi_required": True,
                        }
                    ] if case_id == "has_grounding_candidate" else [],
                },
                "supplemental_source_validity": {"status": "not_provided"},
            "parser_actual_call_usefulness": {
                "parser_inventory_generated": True,
                "parser_useful_for_review": True,
                "parser_useful_for_grounding": case_id == "has_grounding_candidate",
                "semantic_only_regions": counts["screen_inventory_count"] - counts["grounding_eligible_count"],
                "grounding_eligible_regions": counts["grounding_eligible_count"],
                "accepted_for_grounding": 1 if case_id == "has_grounding_candidate" else 0,
                "blocked_from_grounding_reason": "" if case_id == "has_grounding_candidate" else "semantic_region_only_without_interactable_evidence",
                "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
            },
            "report_path": str(Path(kwargs["out_dir"]) / "learn_actual_parser_smoke_report.json"),
        }

    monkeypatch.setattr(parser_batch, "run_actual_parser_smoke", fake_smoke)

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
    )

    assert report["metrics"]["parser_case_has_grounding_candidate"] == {"passed": 1, "attempted": 2, "rate": 0.5}
    assert report["metrics"]["grounding_eligible_item_yield"] == {"passed": 2, "attempted": 7, "rate": 0.2857}
    assert report["actionability_summary"]["cases_without_grounding_candidates"] == ["review_only_inventory"]
    assert report["actionability_summary"]["grounding_candidate_backlog"] == [
        {
            "case_id": "review_only_inventory",
            "failure_category": "no_grounding_candidate",
            "screen_inventory_count": 4,
            "review_only_count": 4,
            "supplemental_validity_status": "not_provided",
            "recommended_intervention": "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox alignment before PathGraph wiring",
        }
    ]
    assert report["actionability_summary"]["total_screen_inventory_count"] == 7
    assert report["actionability_summary"]["total_grounding_eligible_count"] == 2
    assert report["parser_actual_call_usefulness"] == {
        "parser_inventory_generated": True,
        "parser_useful_for_review": True,
        "parser_useful_for_grounding": True,
        "semantic_only_regions": 5,
        "grounding_eligible_regions": 2,
        "accepted_for_grounding": 1,
        "cases_useful_for_grounding": ["has_grounding_candidate"],
        "cases_review_only_without_grounding": ["review_only_inventory"],
        "blocked_from_grounding_reasons": {"semantic_region_only_without_interactable_evidence": 1},
        "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
    }
    assert report["grounding_eligibility_gate_summary"]["grounding_eligibility"] == {
        "attempted": 7,
        "eligible": 2,
        "blocked": 5,
    }
    assert report["grounding_eligibility_gate_summary"]["non_actionable_leaked_to_grounding"]["leaked_count"] == 0
    assert report["grounding_eligibility_gate_summary"]["grounding_eligible_breakdown"]["uia_interactable"] == 2
    assert report["grounding_eligibility_gate_summary"]["browser_chrome_rejection"] == {
        "passed": 1,
        "attempted": 1,
        "rate": 1.0,
    }
    assert report["grounding_eligibility_gate_summary"]["split_roi_required"]["count"] == 2
    assert report["grounding_eligibility_gate_summary"]["split_roi_required"]["item_ids"] == ["download", "get_started"]
    assert report["layout_graph_summary"]["node_count"] == 7
    assert report["layout_graph_summary"]["zone_counts"] == {
        "main_content": 2,
        "page_header": 2,
    }
    assert report["layout_graph_summary"]["overlap_cluster_count"] == 1
    assert report["layout_graph_summary"]["split_roi_required_item_ids"] == ["download", "get_started"]
    assert report["layout_cleanup_summary"]["contract_version"] == "learn_layout_cleanup_batch_summary_v1"
    assert report["layout_cleanup_summary"]["input_count"] == 10
    assert report["layout_cleanup_summary"]["output_count"] == 7
    assert report["layout_cleanup_summary"]["suppressed_count"] == 3
    assert report["layout_cleanup_summary"]["duplicates_merged"] == 2
    assert report["layout_cleanup_summary"]["suppression_reason_counts"] == {
        "cross_evidence_support_duplicate": 2,
        "semantic_container_overlaps_interactable_children": 1,
    }
    assert report["layout_cleanup_summary"]["cases_with_suppression"] == [
        {
            "case_id": "has_grounding_candidate",
            "suppressed_count": 2,
            "suppression_reason_counts": {"cross_evidence_support_duplicate": 2},
        },
        {
            "case_id": "review_only_inventory",
            "suppressed_count": 1,
            "suppression_reason_counts": {"semantic_container_overlaps_interactable_children": 1},
        },
    ]
    assert report["case_results"][0]["layout_cleanup"]["suppression_reason_counts"] == {
        "cross_evidence_support_duplicate": 2
    }
    assert report["grounding_eligibility_gate_summary"]["not_accuracy"] is True
    assert report["support_eligibility_summary"]["total_candidates"] == 7
    assert report["support_eligibility_summary"]["grounding_eligible_candidates"] == 2
    assert report["support_eligibility_summary"]["same_screenshot_interactable_support"] == 2
    assert report["support_eligibility_summary"]["semantic_or_ocr_leaked_to_grounding"] == 0
    assert report["support_eligibility_summary"]["by_source_type"] == {"qwen_vlm": 5, "uia": 2}
    assert report["case_results"][0]["support_eligibility_summary"]["grounding_eligible_candidates"] == 2
    assert "parser inventory success is not enough" in report["actionability_summary"]["interpretation"]


def test_actual_parser_batch_passes_case_supplemental_sources(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(screenshot)
    manifest = tmp_path / "parser_cases.json"
    supplemental_sources = {
        "calibrated_targets": {
            "targets": [
                {
                    "candidate_id": "calibrated_search",
                    "label": "Search",
                    "role": "button",
                    "bbox": {"x": 10, "y": 10, "w": 50, "h": 20},
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
    }
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "with_supplemental_sources",
                        "screenshot_path": str(screenshot),
                        "supplemental_sources": supplemental_sources,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    received: list[dict] = []

    def fake_smoke(**kwargs):
        received.append(kwargs)
        return {
            "status": "passed",
            "actual_model_call_in_this_run": True,
            "metrics": {
                "actual_parser_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                "parse_inventory": {"passed": 1, "attempted": 1, "rate": 1.0},
            },
            "counts": {
                "screen_inventory_count": 2,
                "accepted_for_grounding_count": 1,
                "grounding_eligible_count": 1,
                "review_only_count": 1,
            },
        }

    monkeypatch.setattr(parser_batch, "run_actual_parser_smoke", fake_smoke)

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
    )

    assert received[0]["supplemental_sources"] == supplemental_sources
    assert report["case_results"][0]["supplemental_source_keys"] == ["calibrated_targets"]
    assert report["metrics"]["parser_case_has_grounding_candidate"]["passed"] == 1


def test_actual_parser_batch_loads_case_supplemental_sources_path(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (120, 80), "white").save(screenshot)
    supplemental_path = tmp_path / "supplemental.json"
    supplemental_path.write_text(
        json.dumps(
            {
                "contract_version": "recorded_parser_output_v1",
                "screenshot_sha256": _sha256_file(screenshot),
                "observe_bundle": {
                    "sources": {
                        "calibrated_targets": {
                            "targets": [
                                {
                                    "candidate_id": "calibrated_download",
                                    "label": "Download",
                                    "role": "button",
                                    "bbox": {"x": 40, "y": 20, "w": 50, "h": 20},
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
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "with_supplemental_sources_path",
                        "screenshot_path": str(screenshot),
                        "supplemental_sources_path": str(supplemental_path),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    received: list[dict] = []

    def fake_smoke(**kwargs):
        received.append(kwargs)
        return {
            "status": "passed",
            "actual_model_call_in_this_run": True,
            "metrics": {
                "actual_parser_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                "parse_inventory": {"passed": 1, "attempted": 1, "rate": 1.0},
            },
            "counts": {
                "screen_inventory_count": 2,
                "accepted_for_grounding_count": 1,
                "grounding_eligible_count": 1,
                "review_only_count": 1,
            },
        }

    monkeypatch.setattr(parser_batch, "run_actual_parser_smoke", fake_smoke)

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
    )

    assert received[0]["supplemental_sources"] == {
        "calibrated_targets": {
            "targets": [
                {
                    "candidate_id": "calibrated_download",
                    "label": "Download",
                    "role": "button",
                    "bbox": {"x": 40, "y": 20, "w": 50, "h": 20},
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
    }
    assert report["case_results"][0]["supplemental_source_keys"] == ["calibrated_targets"]
    assert report["case_results"][0]["supplemental_sources_path"] == str(supplemental_path)
    assert report["case_results"][0]["supplemental_source_validity"]["status"] == "checksum_match"
    assert report["supplemental_source_validity_summary"] == {
        "by_status": {"checksum_match": 1},
        "stale_or_invalid_cases": [],
        "interpretation": "supplemental evidence must match the case screenshot before it can support grounding candidates",
    }


def test_actual_parser_batch_rejects_stale_supplemental_sources_path(monkeypatch, tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    other_screenshot = tmp_path / "other.png"
    Image.new("RGB", (120, 80), "white").save(screenshot)
    Image.new("RGB", (120, 80), "black").save(other_screenshot)
    supplemental_path = tmp_path / "stale_supplemental.json"
    supplemental_path.write_text(
        json.dumps(
            {
                "contract_version": "recorded_parser_output_v1",
                "screenshot_sha256": _sha256_file(other_screenshot),
                "observe_bundle": {
                    "sources": {
                        "uia": {
                            "controls": [
                                {
                                    "candidate_id": "stale_search",
                                    "label": "Search",
                                    "role": "button",
                                    "bbox": {"x": 10, "y": 10, "w": 50, "h": 20},
                                }
                            ]
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "parser_cases.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "stale_support",
                        "screenshot_path": str(screenshot),
                        "supplemental_sources_path": str(supplemental_path),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_smoke(**kwargs):
        calls.append(kwargs)
        raise AssertionError("stale supplemental sources must not run the model")

    monkeypatch.setattr(parser_batch, "run_actual_parser_smoke", fake_smoke)

    report = run_actual_parser_batch(
        manifest_path=manifest,
        out_dir=tmp_path / "out",
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="fake-qwen",
    )

    assert calls == []
    assert report["totals"]["invalid"] == 1
    assert report["totals"]["passed"] == 0
    assert report["totals"]["failed"] == 0
    assert report["metrics"]["actual_parser_call"] == {"passed": 0, "attempted": 0, "rate": "not_covered"}
    case_result = report["case_results"][0]
    assert case_result["status"] == "invalid"
    assert case_result["failure_category"] == "stale_supplemental_sources"
    assert case_result["screenshot_sha256"] == _sha256_file(screenshot)
    assert case_result["supplemental_source_validity"]["status"] == "stale_fixture"
    assert case_result["supplemental_source_validity"]["expected_screenshot_sha256"] == _sha256_file(other_screenshot)
    assert case_result["supplemental_source_validity"]["actual_screenshot_sha256"] == _sha256_file(screenshot)
    assert report["supplemental_source_validity_summary"]["by_status"] == {"stale_fixture": 1}
    assert report["supplemental_source_validity_summary"]["stale_or_invalid_cases"] == [
        {
            "case_id": "stale_support",
            "status": "stale_fixture",
            "failure_category": "stale_supplemental_sources",
            "supplemental_sources_path": str(supplemental_path),
        }
    ]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
