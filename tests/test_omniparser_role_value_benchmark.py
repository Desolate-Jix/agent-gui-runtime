from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import benchmark_omniparser_role_value as benchmark


ROOT = Path(__file__).resolve().parents[1]
FROZEN_BENCHMARK = ROOT / "artifacts" / "benchmarks" / "five-interface-omniparser-postprocess-v2-20260824"
FROZEN_REPORT = FROZEN_BENCHMARK / "report.json"
FROZEN_FUSION = FROZEN_BENCHMARK / "omniparser_goal_selection_fusion_report_v3.json"
FROZEN_AVAILABLE = FROZEN_REPORT.is_file() and FROZEN_FUSION.is_file()

APP_IDS = ("calculator", "notepad", "paint", "character_map", "control_panel")
SHA_BY_APP = {app_id: f"{index + 1:064x}" for index, app_id in enumerate(APP_IDS)}


def _screen(app_id: str, *, provider: str) -> dict[str, object]:
    actions = (["accept", "resize_box"] + ["add_box"] * 6) if provider == "qwen" else (["accept"] * 6 + ["relabel", "add_box"])
    counts = {action: actions.count(action) for action in ("accept", "relabel", "resize_box", "rebox_and_relabel", "add_box")}
    return {
        "app_id": app_id,
        "image_sha256": SHA_BY_APP[app_id],
        "candidate_count": 3 if provider == "omniparser" else 1,
        "geometry": {"strict_iou_0_5": {"matched": 2 if provider == "omniparser" else 1, "gold_count": 4}},
        "critical_review": {
            "target_count": 8,
            "box_found_count": 7 if provider == "omniparser" else 2,
            **{f"{action}_count": count for action, count in counts.items()},
            "details": [
                *[
                    {
                        "target_id": f"{app_id}-{index}",
                        "box_found": action != "add_box",
                        "geometry_acceptable": action in {"accept", "relabel"},
                        "semantic_correct": action in {"accept", "resize_box"},
                        "review_action": action,
                    }
                    for index, action in enumerate(actions)
                ],
            ],
        },
    }


def _provider_report() -> dict[str, object]:
    return {
        "contract_version": "five_screen_omniparser_scorer_report_v1",
        "screen_count": 5,
        "app_ids": list(APP_IDS),
        "providers": {provider: {"screen_count": 5, "screens": [_screen(app_id, provider=provider) for app_id in APP_IDS]} for provider in ("qwen", "omniparser")},
        "interpretation": {"artifact_is_authorization": False, "execute_binding_enabled": False},
    }


def _fusion_report() -> dict[str, object]:
    case_ids = [f"{app_id}__case_{index}" for app_id in APP_IDS for index in range(8)]
    details = [
        {
            "case_id": case_id,
            "selected": index < 7,
            "inside_expected_bbox": index < 5,
        }
        for index, case_id in enumerate(case_ids)
    ]
    return {
        "contract_version": "omniparser_vista_goal_selection_benchmark_v3",
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "lineage_validation": {"status": "valid", "screen_count": 5, "case_count": 40, "case_to_image_binding_count": 40},
        "modes": {
            "omni_uia_qwen_exact_unique_fail_closed": {
                "case_count": 40,
            "selected_count": 7,
            "inside_count": 5,
            "per_screen": {
                app_id: {"case_count": 8, "selected_count": 7 if app_id == "calculator" else 0, "inside_count": 5 if app_id == "calculator" else 0}
                for app_id in APP_IDS
            },
            "details": details,
            }
        },
    }


def test_role_value_report_uses_measured_review_and_fail_closed_detail_data() -> None:
    report = benchmark.build_role_value_report(_provider_report(), _fusion_report())

    assert report["candidate_discovery"]["qwen"] == {
        "candidate_count": 5,
        "critical_target_count": 40,
        "critical_box_found_count": 10,
        "critical_box_missing_count": 30,
        "critical_strict_geometry_count": 5,
        "all_control_strict_geometry_count": 5,
        "all_control_target_count": 20,
    }
    assert report["human_review_actions"]["omniparser"]["raw"] == {
        "accept": 30,
        "relabel": 5,
        "resize_box": 0,
        "rebox_and_relabel": 0,
        "add_box": 5,
    }
    assert report["human_review_actions"]["qwen"]["geometry_correction_raw_count"] == 35
    assert report["vista_avoidance"] == {
        "mode": "omni_uia_qwen_exact_unique_fail_closed",
        "nominal_selected_count": 7,
        "correct_selected_count": 5,
        "wrong_selected_count": 2,
        "wrong_case_ids_post_selection_evidence": ["calculator__case_5", "calculator__case_6"],
        "safety_credited_avoided_calls": 0,
    }
    assert report["disposition"]["decision"] == "KEEP_SHADOW"
    assert report["disposition"]["reasons"][:4] == [
        "candidate discovery adds 25 critical boxes and reduces geometry correction events by 30",
        "clutter remains 15 Omni candidates versus 5 Qwen candidates",
        "10 Omni critical targets still require semantic review",
        "fused bypass has 2 wrong targets",
    ]
    assert report["measurement_limits"]["candidate_availability_and_review"].startswith(
        "35/40 Omni critical box availability"
    )


def test_role_value_rejects_fusion_app_set_drift() -> None:
    fusion = _fusion_report()
    fusion["modes"]["omni_uia_qwen_exact_unique_fail_closed"]["per_screen"].pop("paint")

    with pytest.raises(benchmark.BenchmarkInputError, match="application set"):
        benchmark.build_role_value_report(_provider_report(), fusion)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda provider, fusion: provider["interpretation"].pop("artifact_is_authorization"), "non-authorizing"),
        (lambda provider, fusion: provider["providers"]["omniparser"]["screens"][0].__setitem__("image_sha256", "f" * 64), "SHA binding"),
        (lambda provider, fusion: fusion["lineage_validation"].__setitem__("status", "other"), "lineage"),
        (lambda provider, fusion: fusion["lineage_validation"].__setitem__("case_to_image_binding_count", 39), "lineage"),
        (lambda provider, fusion: fusion["modes"]["omni_uia_qwen_exact_unique_fail_closed"]["details"][1].__setitem__("case_id", "calculator__case_0"), "case IDs"),
        (lambda provider, fusion: fusion["modes"]["omni_uia_qwen_exact_unique_fail_closed"]["details"][0].__setitem__("case_id", "unknown__case_0"), "case app binding"),
        (lambda provider, fusion: provider["providers"]["qwen"]["screens"][0]["critical_review"]["details"][1].__setitem__("target_id", "calculator-0"), "target IDs"),
        (lambda provider, fusion: provider["providers"]["qwen"]["screens"][0]["critical_review"]["details"][0].__setitem__("box_found", False), "box/action"),
        (lambda provider, fusion: provider["providers"]["qwen"]["screens"][0]["critical_review"]["details"][0].__setitem__("review_action", "unknown"), "review action"),
        (lambda provider, fusion: provider["providers"]["qwen"]["screens"][0]["critical_review"]["details"][1].__setitem__("geometry_acceptable", True), "semantic/geometry/action"),
        (lambda provider, fusion: provider["providers"]["qwen"]["screens"][0]["critical_review"]["details"][2].__setitem__("geometry_acceptable", True), "semantic/geometry/action"),
    ],
)
def test_role_value_rejects_invalid_attribution_and_detail_contracts(mutate: object, reason: str) -> None:
    provider = _provider_report()
    fusion = _fusion_report()
    provider["interpretation"].update({"artifact_is_authorization": False, "execute_binding_enabled": False})
    fusion["lineage_validation"].update({"status": "valid", "case_to_image_binding_count": 40})
    mutate(provider, fusion)

    with pytest.raises(benchmark.BenchmarkInputError, match=reason):
        benchmark.build_role_value_report(provider, fusion)


@pytest.mark.skipif(not FROZEN_AVAILABLE, reason="requires ignored frozen provider and fusion reports")
def test_frozen_role_value_report_pins_measured_decision_data() -> None:
    report = benchmark.run_benchmark(FROZEN_BENCHMARK)

    assert report["candidate_discovery"] == {
        "qwen": {
            "candidate_count": 45,
            "critical_target_count": 40,
            "critical_box_found_count": 14,
            "critical_box_missing_count": 26,
            "critical_strict_geometry_count": 6,
            "all_control_strict_geometry_count": 7,
            "all_control_target_count": 204,
        },
        "omniparser": {
            "candidate_count": 368,
            "critical_target_count": 40,
            "critical_box_found_count": 34,
            "critical_box_missing_count": 6,
            "critical_strict_geometry_count": 25,
            "all_control_strict_geometry_count": 78,
            "all_control_target_count": 204,
        },
    }
    assert report["human_review_actions"]["qwen"]["raw"] == {
        "accept": 5, "relabel": 1, "resize_box": 3, "rebox_and_relabel": 5, "add_box": 26,
    }
    assert report["human_review_actions"]["omniparser"]["raw"] == {
        "accept": 0, "relabel": 25, "resize_box": 0, "rebox_and_relabel": 9, "add_box": 6,
    }
    assert report["human_review_actions"]["qwen"]["geometry_correction_raw_count"] == 34
    assert report["human_review_actions"]["omniparser"]["geometry_correction_raw_count"] == 15
    assert report["vista_avoidance"] == {
        "mode": "omni_uia_qwen_exact_unique_fail_closed",
        "nominal_selected_count": 7,
        "correct_selected_count": 5,
        "wrong_selected_count": 2,
        "wrong_case_ids_post_selection_evidence": ["paint__resize", "character_map__help"],
        "safety_credited_avoided_calls": 0,
    }


@pytest.mark.skipif(not FROZEN_AVAILABLE, reason="requires ignored frozen provider and fusion reports")
def test_cli_writes_role_value_report(tmp_path: Path) -> None:
    output_path = tmp_path / "role_value.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmark_omniparser_role_value.py"),
            "--benchmark-dir", str(FROZEN_BENCHMARK), "--out", str(output_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output_path.read_text(encoding="utf-8"))["disposition"]["decision"] == "KEEP_SHADOW"
