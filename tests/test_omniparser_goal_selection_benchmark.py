from __future__ import annotations

import inspect
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import benchmark_omniparser_goal_selection as benchmark
from scripts.benchmark_omniparser_goal_selection import (
    BenchmarkInputError,
    exact_unique_fail_closed,
    forced_similarity,
    run_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_BENCHMARK = ROOT / "artifacts" / "benchmarks" / "five-interface-omniparser-postprocess-v2-20260824"
FROZEN_REQUIRED_FILES = (
    "capture_manifest.json",
    "vista_cases.json",
    "vista.json",
    *(f"omni_{app_id}.json" for app_id in ("calculator", "notepad", "paint", "character_map", "control_panel")),
    *(f"{app_id}.png" for app_id in ("calculator", "notepad", "paint", "character_map", "control_panel")),
)
FROZEN_BENCHMARK_AVAILABLE = FROZEN_BENCHMARK.is_dir() and all(
    (FROZEN_BENCHMARK / name).is_file() for name in FROZEN_REQUIRED_FILES
)
FROZEN_SKIP_REASON = "requires ignored frozen Omni/VISTA benchmark artifacts that are absent from clean clones"


def _candidate(content: str, candidate_id: str) -> dict[str, object]:
    return {
        "element_id": candidate_id,
        "content": content,
        "type": "icon",
        "source": "box_yolo_content_yolo",
        "bbox": [0.1, 0.1, 0.2, 0.2],
        "interactivity": True,
    }


def _valid_omni_payload() -> dict[str, object]:
    return {
        "contract_version": "screen_parser_result_v1",
        "provider": "omniparser",
        "status": "success",
        "profile_id": "profile",
        "model_revision": "revision",
        "capture_id": "capture",
        "source_run_id": "run",
        "provenance": {"source": "recorded"},
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "review_only": True,
        "grounding_eligible": False,
    }


def test_selector_api_accepts_only_goal_and_current_candidates() -> None:
    assert tuple(inspect.signature(forced_similarity).parameters) == ("goal", "candidates")
    assert tuple(inspect.signature(exact_unique_fail_closed).parameters) == ("goal", "candidates")


def test_forced_similarity_avoids_short_token_substring_promotion() -> None:
    candidates = [_candidate("At", "short"), _candidate("Windows Defender", "semantic")]

    selected = forced_similarity("Locate the visible control: windows defender firewall", candidates)

    assert selected is not None
    assert selected["element_id"] == "semantic"


def test_forced_similarity_selects_deterministic_fallback_when_no_text_matches() -> None:
    candidates = [_candidate("alpha", "first"), _candidate("beta", "second")]

    selected = forced_similarity("Locate the visible control: unrelated", candidates)

    assert selected is not None
    assert selected["element_id"] == "first"


def test_exact_unique_fail_closed_requires_one_normalized_exact_match() -> None:
    goal = "Locate the visible control: close"

    assert exact_unique_fail_closed(goal, [_candidate("Close", "only")])["element_id"] == "only"
    assert exact_unique_fail_closed(goal, [_candidate("Close", "one"), _candidate("close!", "two")]) is None
    assert exact_unique_fail_closed(goal, [_candidate("Dismiss", "none")]) is None


def test_unique_uia_overlap_enriches_selection_text_without_changing_omni_geometry() -> None:
    candidates = [
        {
            **_candidate("unreadable", "omni-one"),
            "pixel_bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
        },
        {
            **_candidate("other", "omni-two"),
            "pixel_bbox": {"x": 80, "y": 10, "w": 40, "h": 20},
        },
    ]
    support = [
        {
            "support_id": "uia-close",
            "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
            "text": "Close Close button",
            "role": "button",
        }
    ]

    enriched, coverage = benchmark._enrich_candidates_with_support(candidates, support, "uia")

    assert enriched[0]["pixel_bbox"] == candidates[0]["pixel_bbox"]
    assert enriched[0]["support_texts"] == ["Close Close button"]
    assert enriched[1].get("support_texts") is None
    assert coverage == {"unique_count": 1, "ambiguous_count": 0, "unmatched_count": 1}
    assert forced_similarity("Locate the visible control: close", enriched)["element_id"] == "omni-one"


def test_ambiguous_support_overlap_does_not_enrich_candidate() -> None:
    candidates = [
        {
            **_candidate("unreadable", "omni-one"),
            "pixel_bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
        }
    ]
    support = [
        {"support_id": "uia-one", "bbox": {"x": 10, "y": 10, "w": 40, "h": 20}, "text": "Close", "role": "button"},
        {"support_id": "uia-two", "bbox": {"x": 10, "y": 10, "w": 40, "h": 20}, "text": "Open", "role": "button"},
    ]

    enriched, coverage = benchmark._enrich_candidates_with_support(candidates, support, "uia")

    assert enriched[0].get("support_texts") is None
    assert coverage == {"unique_count": 0, "ambiguous_count": 1, "unmatched_count": 0}


def test_noninteractive_support_role_does_not_enrich_candidate() -> None:
    candidates = [{**_candidate("unreadable", "omni-one"), "pixel_bbox": {"x": 10, "y": 10, "w": 40, "h": 20}}]
    support = [
        {
            "support_id": "uia-label",
            "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
            "text": "Close",
            "role": "text",
        }
    ]

    enriched, coverage = benchmark._enrich_candidates_with_support(candidates, support, "uia")

    assert enriched[0].get("support_texts") is None
    assert coverage == {"unique_count": 0, "ambiguous_count": 0, "unmatched_count": 1}


def test_support_extractors_keep_only_current_semantic_fields_and_canonical_roles() -> None:
    uia = {
        "uia_snapshot": {
            "controls": [
                {
                    "control_id": "uia-close",
                    "name": "Close window",
                    "automation_id": "Close",
                    "control_type": "Button",
                    "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
                    "enabled": True,
                    "visible": True,
                },
                {
                    "control_id": "uia-text",
                    "name": "not a selectable support role",
                    "control_type": "Text",
                    "bbox": {"x": 80, "y": 10, "w": 40, "h": 20},
                },
            ]
        }
    }
    qwen = {
        "observe_bundle": {
            "sources": {
                "vision": {
                    "regions": [
                        {
                            "region_id": "qwen-close",
                            "label": "close control",
                            "ocr_text": "X",
                            "description": "closes the window",
                            "role": "button",
                            "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
                        }
                    ]
                }
            }
        }
    }

    assert benchmark._uia_support_items(uia) == [
        {
            "support_id": "uia-close",
            "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
            "role": "button",
            "texts": ["Close window", "Close", "button"],
        }
    ]
    assert benchmark._qwen_support_items(qwen) == [
        {
            "support_id": "qwen-close",
            "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
            "role": "button",
            "texts": ["close control", "X", "closes the window", "button"],
        }
    ]


@pytest.mark.parametrize("state", [{"enabled": False, "visible": True}, {"enabled": True, "visible": False}])
def test_uia_support_extractor_rejects_disabled_or_invisible_controls(state: dict[str, bool]) -> None:
    payload = {
        "uia_snapshot": {
            "controls": [
                {
                    "control_id": "uia-close",
                    "name": "Close",
                    "automation_id": "Close",
                    "control_type": "Button",
                    "bbox": {"x": 10, "y": 10, "w": 40, "h": 20},
                    **state,
                }
            ]
        }
    }

    assert benchmark._uia_support_items(payload) == []


def _valid_uia_support_payload() -> dict[str, object]:
    return {
        "contract_version": "five_interface_uia_gold_source_v1",
        "app_id": "calculator",
        "uia_snapshot": {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
        },
    }


def _valid_qwen_support_payload() -> dict[str, object]:
    profile = {
        "profile_id": "learn_mode_qwen3_vl_8b",
        "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        "model_family": "Qwen3-VL",
        "provider_mode": "local_understanding",
        "mode_scope": "learn_only",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return {
        "contract_version": "actual_parser_output_v1",
        "source_type": "actual_parser_call",
        "actual_model_call_in_this_run": True,
        "model_profile": profile,
        "model_config": {
            "model_profile_id": "learn_mode_qwen3_vl_8b",
            "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
            "app_name": "calculator",
            "goal": "inventory the visible interface and identify interactive controls with labels and bounding boxes",
            "model_profile": dict(profile),
        },
        "observe_bundle": {
            "sources": {
                "vision": {
                    "contract_version": "vision_regions_v1",
                    "provider": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
                }
            }
        },
    }


def test_support_attribution_accepts_expected_recorded_profiles() -> None:
    benchmark._validate_support_attribution("calculator", "uia", _valid_uia_support_payload())
    benchmark._validate_support_attribution("calculator", "qwen", _valid_qwen_support_payload())


@pytest.mark.parametrize(
    ("source", "payload", "reason"),
    [
        ("uia", {**_valid_uia_support_payload(), "app_id": "paint"}, "UIA support attribution invalid"),
        (
            "uia",
            {**_valid_uia_support_payload(), "uia_snapshot": {"provider": "other", "provider_version": "windows_uia_provider_v1", "status": "ok"}},
            "UIA support attribution invalid",
        ),
        ("qwen", {**_valid_qwen_support_payload(), "source_type": "hand_authored"}, "Qwen support attribution invalid"),
        ("qwen", {**_valid_qwen_support_payload(), "actual_model_call_in_this_run": False}, "Qwen support attribution invalid"),
        (
            "qwen",
            {**_valid_qwen_support_payload(), "model_profile": {**_valid_qwen_support_payload()["model_profile"], "provider_mode": "other"}},
            "Qwen support attribution invalid",
        ),
        (
            "qwen",
            {
                **_valid_qwen_support_payload(),
                "observe_bundle": {"sources": {"vision": {"contract_version": "vision_regions_v1", "provider": "other"}}},
            },
            "Qwen support attribution invalid",
        ),
        (
            "qwen",
            {**_valid_qwen_support_payload(), "model_config": {**_valid_qwen_support_payload()["model_config"], "app_name": "paint"}},
            "Qwen support attribution invalid",
        ),
        (
            "qwen",
            {
                **_valid_qwen_support_payload(),
                "model_config": {**_valid_qwen_support_payload()["model_config"], "goal": "inventory controls"},
            },
            "Qwen support attribution invalid",
        ),
    ],
)
def test_support_attribution_rejects_mutated_or_hand_authored_payloads(
    source: str, payload: dict[str, object], reason: str
) -> None:
    with pytest.raises(BenchmarkInputError, match=reason):
        benchmark._validate_support_attribution("calculator", source, payload)


def test_support_lineage_rejects_qwen_observe_bundle_sha_mismatch() -> None:
    payload = {
        "screenshot_sha256": "expected",
        "observe_bundle": {
            "screenshot_sha256": "other",
            "image_size": {"width": 900, "height": 1000},
        },
    }

    with pytest.raises(BenchmarkInputError, match="Qwen screenshot SHA lineage mismatch"):
        benchmark._validate_support_lineage("calculator", "qwen", payload, "expected", (900, 1000))


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("contract_version", "other"),
        ("provider", "other"),
        ("status", "failed"),
        ("profile_id", ""),
        ("model_revision", " "),
        ("capture_id", None),
        ("source_run_id", 1),
        ("provenance", []),
        ("artifact_is_authorization", True),
        ("artifact_is_authorization", 0),
        ("execute_binding_enabled", True),
        ("review_only", False),
        ("review_only", 1),
        ("grounding_eligible", True),
    ],
)
def test_omni_artifact_attribution_rejects_invalid_contract_fields(field: str, invalid_value: object) -> None:
    payload = _valid_omni_payload()
    payload[field] = invalid_value

    with pytest.raises(BenchmarkInputError, match="Omni artifact attribution invalid"):
        benchmark._validate_omni_artifact_attribution("calculator", payload)


def test_omni_artifact_attribution_accepts_exact_non_authorizing_contract() -> None:
    benchmark._validate_omni_artifact_attribution("calculator", _valid_omni_payload())


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda results: results.__setitem__(1, deepcopy(results[0])), "duplicate"),
        (lambda results: results.reverse(), "ordered case IDs"),
        (lambda results: results[0].__setitem__("expected_bbox", {"x": 9, "y": 9, "w": 1, "h": 1}), "bbox"),
    ],
)
def test_vista_reference_rejects_duplicate_order_or_bbox_mismatch(mutate: object, reason: str) -> None:
    cases = [
        {"case_id": "a", "expected_bbox": {"x": 1, "y": 2, "w": 3, "h": 4}},
        {"case_id": "b", "expected_bbox": {"x": 5, "y": 6, "w": 7, "h": 8}},
    ]
    results = [
        {"case_id": "a", "expected_bbox": {"x": 1, "y": 2, "w": 3, "h": 4}},
        {"case_id": "b", "expected_bbox": {"x": 5, "y": 6, "w": 7, "h": 8}},
    ]
    mutate(results)

    with pytest.raises(BenchmarkInputError, match=reason):
        benchmark._validate_vista_reference_bindings(cases, results)


@pytest.mark.skipif(not FROZEN_BENCHMARK_AVAILABLE, reason=FROZEN_SKIP_REASON)
def test_frozen_benchmark_report_is_non_authorizing_and_reproducible() -> None:
    report = run_benchmark(FROZEN_BENCHMARK)

    assert report["contract_version"] == "omniparser_vista_goal_selection_benchmark_v3"
    assert report["review_only"] is True
    assert report["artifact_is_authorization"] is False
    assert report["execute_binding_enabled"] is False
    assert report["lineage_validation"] == {
        "status": "valid",
        "screen_count": 5,
        "case_count": 40,
        "case_to_image_binding_count": 40,
    }
    assert report["modes"]["forced_similarity"]["selected_count"] == 40
    assert report["modes"]["forced_similarity"]["inside_count"] == 6
    assert report["modes"]["forced_similarity"]["selection_precision"] == 0.15
    assert "allowed_precision" not in report["modes"]["forced_similarity"]
    assert report["modes"]["forced_similarity"]["interpretation"] == (
        "6/40 is end-to-end goal-selector safe-center accuracy; not detection recall, bbox IoU, execute safety, or authorization."
    )
    assert report["modes"]["exact_unique_fail_closed"]["selected_count"] == 5
    assert report["modes"]["exact_unique_fail_closed"]["inside_count"] == 4
    assert report["modes"]["omni_uia_forced_similarity"]["selection_input_contract"] == [
        "goal",
        "current_omni_candidates",
        "same_screenshot_uia_semantic_support",
    ]
    assert report["modes"]["omni_uia_qwen_forced_similarity"]["selection_input_contract"] == [
        "goal",
        "current_omni_candidates",
        "same_screenshot_uia_semantic_support",
        "same_screenshot_qwen_semantic_support",
    ]
    for name in ("omni_uia_forced_similarity", "omni_uia_exact_unique_fail_closed"):
        assert report["modes"][name]["case_count"] == 40
        assert set(report["modes"][name]["support_coverage"]) == {"uia"}
    for name in ("omni_uia_qwen_forced_similarity", "omni_uia_qwen_exact_unique_fail_closed"):
        assert report["modes"][name]["case_count"] == 40
        assert set(report["modes"][name]["support_coverage"]) == {"uia", "qwen"}
    metric_keys = ("selected_count", "inside_count", "selection_precision", "pass_count", "risky_count", "fail_count")
    assert {key: report["modes"]["omni_uia_forced_similarity"][key] for key in metric_keys} == {
        "selected_count": 40,
        "inside_count": 10,
        "selection_precision": 0.25,
        "pass_count": 10,
        "risky_count": 0,
        "fail_count": 30,
    }
    assert {key: report["modes"]["omni_uia_exact_unique_fail_closed"][key] for key in metric_keys} == {
        "selected_count": 5,
        "inside_count": 4,
        "selection_precision": 0.8,
        "pass_count": 4,
        "risky_count": 0,
        "fail_count": 36,
    }
    assert {key: report["modes"]["omni_uia_qwen_forced_similarity"][key] for key in metric_keys} == {
        "selected_count": 40,
        "inside_count": 15,
        "selection_precision": 0.375,
        "pass_count": 15,
        "risky_count": 0,
        "fail_count": 25,
    }
    assert {key: report["modes"]["omni_uia_qwen_exact_unique_fail_closed"][key] for key in metric_keys} == {
        "selected_count": 7,
        "inside_count": 5,
        "selection_precision": 0.714286,
        "pass_count": 5,
        "risky_count": 0,
        "fail_count": 35,
    }
    assert report["support_coverage"] == {
        "uia": {"unique_count": 98, "ambiguous_count": 0, "unmatched_count": 270},
        "qwen": {"unique_count": 21, "ambiguous_count": 0, "unmatched_count": 347},
    }
    assert report["posthoc_safe_center_point_ceiling"]["evaluation_only"] is True
    assert report["posthoc_safe_center_point_ceiling"]["used_for_selection"] is False
    assert report["posthoc_safe_center_point_ceiling"]["inside_count"] == 34
    assert "posthoc_geometry_ceiling" not in report
    assert report["metric_definitions"]["forced_similarity_safe_center_accuracy"].startswith(
        "End-to-end goal-selector"
    )
    assert "not detection" in report["metric_definitions"]["forced_similarity_safe_center_accuracy"]
    assert "not IoU" in report["metric_definitions"]["posthoc_safe_center_point_ceiling"]
    assert report["vista_frozen_reference"]["case_count"] == 40
    assert report["vista_frozen_reference"]["inside_count"] == 24


@pytest.mark.skipif(not FROZEN_BENCHMARK_AVAILABLE, reason=FROZEN_SKIP_REASON)
def test_script_runs_directly_as_cli(tmp_path: Path) -> None:
    output_path = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmark_omniparser_goal_selection.py"),
            "--benchmark-dir",
            str(FROZEN_BENCHMARK),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output_path.is_file()
