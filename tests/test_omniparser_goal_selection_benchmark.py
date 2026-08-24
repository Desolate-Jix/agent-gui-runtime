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

    assert report["contract_version"] == "omniparser_vista_goal_selection_benchmark_v2"
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
