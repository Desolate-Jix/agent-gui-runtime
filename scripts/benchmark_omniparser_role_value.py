from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


APP_IDS = ("calculator", "notepad", "paint", "character_map", "control_panel")
_PROVIDER_CONTRACT_VERSION = "five_screen_omniparser_scorer_report_v1"
_FUSION_CONTRACT_VERSION = "omniparser_vista_goal_selection_benchmark_v3"
_VISTA_MODE = "omni_uia_qwen_exact_unique_fail_closed"
_ACTION_FIELDS = ("accept", "relabel", "resize_box", "rebox_and_relabel", "add_box")


class BenchmarkInputError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError(f"invalid benchmark JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkInputError(f"benchmark JSON must be an object: {path}")
    return value


def _require_non_authorizing(payload: dict[str, Any], label: str) -> None:
    for field, expected in (("artifact_is_authorization", False), ("execute_binding_enabled", False)):
        if payload.get(field) is not expected:
            raise BenchmarkInputError(f"{label} must be non-authorizing: {field}")


def _provider_screens(provider_report: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    providers = provider_report.get("providers")
    entry = providers.get(provider) if isinstance(providers, dict) else None
    screens = entry.get("screens") if isinstance(entry, dict) else None
    if not isinstance(screens, list) or len(screens) != 5 or not all(isinstance(screen, dict) for screen in screens):
        raise BenchmarkInputError(f"provider screens invalid: {provider}")
    if {str(screen.get("app_id") or "") for screen in screens} != set(APP_IDS):
        raise BenchmarkInputError(f"provider application set invalid: {provider}")
    return screens


def _validate_provider_report(payload: dict[str, Any]) -> None:
    if payload.get("contract_version") != _PROVIDER_CONTRACT_VERSION:
        raise BenchmarkInputError("provider report contract version invalid")
    if payload.get("screen_count") != 5 or set(payload.get("app_ids") or []) != set(APP_IDS):
        raise BenchmarkInputError("provider report frozen five-screen binding invalid")
    interpretation = payload.get("interpretation")
    if not isinstance(interpretation, dict):
        raise BenchmarkInputError("provider report interpretation invalid")
    _require_non_authorizing(interpretation, "provider report")
    sha_by_provider: dict[str, dict[str, str]] = {}
    for provider in ("qwen", "omniparser"):
        sha_by_provider[provider] = {}
        for screen in _provider_screens(payload, provider):
            app_id = str(screen["app_id"])
            image_sha = screen.get("image_sha256")
            if not isinstance(image_sha, str) or re.fullmatch(r"[0-9a-f]{64}", image_sha) is None:
                raise BenchmarkInputError(f"provider image SHA invalid: {provider}:{app_id}")
            sha_by_provider[provider][app_id] = image_sha
    if sha_by_provider["qwen"] != sha_by_provider["omniparser"]:
        raise BenchmarkInputError("provider screenshot SHA binding mismatch")


def _validate_fusion_report(payload: dict[str, Any]) -> None:
    if payload.get("contract_version") != _FUSION_CONTRACT_VERSION:
        raise BenchmarkInputError("fusion report contract version invalid")
    if payload.get("review_only") is not True:
        raise BenchmarkInputError("fusion report must be review-only")
    _require_non_authorizing(payload, "fusion report")
    lineage = payload.get("lineage_validation")
    if (
        not isinstance(lineage, dict)
        or lineage.get("status") != "valid"
        or lineage.get("screen_count") != 5
        or lineage.get("case_count") != 40
        or lineage.get("case_to_image_binding_count") != 40
    ):
        raise BenchmarkInputError("fusion report lineage/frozen five-screen binding invalid")
    modes = payload.get("modes")
    mode = modes.get(_VISTA_MODE) if isinstance(modes, dict) else None
    if not isinstance(mode, dict) or mode.get("case_count") != 40:
        raise BenchmarkInputError("fusion report fail-closed mode invalid")
    per_screen = mode.get("per_screen")
    if not isinstance(per_screen, dict) or set(per_screen) != set(APP_IDS):
        raise BenchmarkInputError("fusion report application set invalid")
    if any(not isinstance(summary, dict) or summary.get("case_count") != 8 for summary in per_screen.values()):
        raise BenchmarkInputError("fusion report per-screen case count invalid")
    details = mode.get("details")
    if not isinstance(details, list) or len(details) != 40 or not all(isinstance(detail, dict) for detail in details):
        raise BenchmarkInputError("fusion report details invalid")
    case_ids = [detail.get("case_id") for detail in details]
    if not all(isinstance(case_id, str) and case_id.strip() for case_id in case_ids) or len(set(case_ids)) != 40:
        raise BenchmarkInputError("fusion report case IDs invalid")
    by_app: dict[str, list[dict[str, Any]]] = {app_id: [] for app_id in APP_IDS}
    for detail, case_id in zip(details, case_ids, strict=True):
        app_id, separator, target_id = case_id.partition("__")
        if separator != "__" or not target_id or app_id not in by_app:
            raise BenchmarkInputError("fusion report case app binding invalid")
        if not isinstance(detail.get("selected"), bool) or not isinstance(detail.get("inside_expected_bbox"), bool):
            raise BenchmarkInputError("fusion report detail selection flags invalid")
        by_app[app_id].append(detail)
    if any(len(app_details) != 8 for app_details in by_app.values()):
        raise BenchmarkInputError("fusion report case app distribution invalid")
    selected_count = sum(detail["selected"] for detail in details)
    inside_count = sum(detail["selected"] and detail["inside_expected_bbox"] for detail in details)
    if mode.get("selected_count") != selected_count or mode.get("inside_count") != inside_count:
        raise BenchmarkInputError("fusion report mode/detail totals invalid")
    for app_id, app_details in by_app.items():
        summary = per_screen[app_id]
        if (
            summary.get("selected_count") != sum(detail["selected"] for detail in app_details)
            or summary.get("inside_count") != sum(detail["selected"] and detail["inside_expected_bbox"] for detail in app_details)
        ):
            raise BenchmarkInputError("fusion report per-screen/detail totals invalid")


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BenchmarkInputError(f"invalid measured count: {label}")
    return value


def _provider_measurements(provider_report: dict[str, Any], provider: str) -> tuple[dict[str, int], dict[str, Any]]:
    candidate_count = 0
    critical_target_count = 0
    critical_box_found_count = 0
    critical_strict_geometry_count = 0
    all_control_strict_geometry_count = 0
    all_control_target_count = 0
    action_counts = {field: 0 for field in _ACTION_FIELDS}
    for screen in _provider_screens(provider_report, provider):
        critical = screen.get("critical_review")
        geometry = screen.get("geometry")
        strict = geometry.get("strict_iou_0_5") if isinstance(geometry, dict) else None
        details = critical.get("details") if isinstance(critical, dict) else None
        if not isinstance(details, list) or not isinstance(strict, dict):
            raise BenchmarkInputError(f"provider review details invalid: {provider}")
        target_count = _integer(critical.get("target_count"), f"{provider}.critical.target_count")
        if target_count != len(details):
            raise BenchmarkInputError(f"provider critical target/detail mismatch: {provider}")
        target_ids = [detail.get("target_id") for detail in details if isinstance(detail, dict)]
        if len(target_ids) != len(details) or not all(isinstance(target_id, str) and target_id.strip() for target_id in target_ids) or len(set(target_ids)) != len(target_ids):
            raise BenchmarkInputError(f"provider critical target IDs invalid: {provider}")
        for detail in details:
            if (
                not isinstance(detail.get("box_found"), bool)
                or not isinstance(detail.get("geometry_acceptable"), bool)
                or not isinstance(detail.get("semantic_correct"), bool)
            ):
                raise BenchmarkInputError(f"provider critical detail booleans invalid: {provider}")
            action = detail.get("review_action")
            if action not in _ACTION_FIELDS:
                raise BenchmarkInputError(f"provider critical review action invalid: {provider}")
            expected_action = (
                "add_box"
                if detail["box_found"] is False
                else "accept"
                if detail["semantic_correct"] and detail["geometry_acceptable"]
                else "resize_box"
                if detail["semantic_correct"]
                else "relabel"
                if detail["geometry_acceptable"]
                else "rebox_and_relabel"
            )
            if (
                (detail["box_found"] is False and (detail["semantic_correct"] or detail["geometry_acceptable"]))
                or action != expected_action
            ):
                raise BenchmarkInputError(f"provider critical box/action semantic/geometry/action mismatch: {provider}")
        critical_target_count += target_count
        found = _integer(critical.get("box_found_count"), f"{provider}.critical.box_found_count")
        added = _integer(critical.get("add_box_count"), f"{provider}.critical.add_box_count")
        if found != target_count - added or found != sum(detail["box_found"] for detail in details):
            raise BenchmarkInputError(f"provider critical box/add mismatch: {provider}")
        critical_box_found_count += found
        candidate_count += _integer(screen.get("candidate_count"), f"{provider}.candidate_count")
        all_control_strict_geometry_count += _integer(strict.get("matched"), f"{provider}.strict.matched")
        all_control_target_count += _integer(strict.get("gold_count"), f"{provider}.strict.gold_count")
        critical_strict_geometry_count += sum(detail["geometry_acceptable"] for detail in details)
        measured_actions = {field: _integer(critical.get(f"{field}_count"), f"{provider}.{field}_count") for field in _ACTION_FIELDS}
        detail_actions = {field: sum(detail.get("review_action") == field for detail in details) for field in _ACTION_FIELDS}
        if sum(measured_actions.values()) != target_count or measured_actions != detail_actions:
            raise BenchmarkInputError(f"provider review action/detail mismatch: {provider}")
        for field in _ACTION_FIELDS:
            action_counts[field] += measured_actions[field]
    if critical_target_count != 40:
        raise BenchmarkInputError(f"provider critical target count invalid: {provider}")
    discovery = {
        "candidate_count": candidate_count,
        "critical_target_count": critical_target_count,
        "critical_box_found_count": critical_box_found_count,
        "critical_box_missing_count": critical_target_count - critical_box_found_count,
        "critical_strict_geometry_count": critical_strict_geometry_count,
        "all_control_strict_geometry_count": all_control_strict_geometry_count,
        "all_control_target_count": all_control_target_count,
    }
    workload = {
        "raw": action_counts,
        "geometry_correction_raw_count": action_counts["resize_box"] + action_counts["rebox_and_relabel"] + action_counts["add_box"],
    }
    return discovery, workload


def _vista_avoidance(fusion_report: dict[str, Any]) -> dict[str, Any]:
    mode = fusion_report["modes"][_VISTA_MODE]
    details = mode.get("details")
    if not isinstance(details, list):
        raise BenchmarkInputError("fusion fail-closed details invalid")
    selected = [detail for detail in details if detail.get("selected") is True]
    correct = [detail for detail in selected if detail.get("inside_expected_bbox") is True]
    wrong = [detail for detail in selected if detail.get("inside_expected_bbox") is not True]
    wrong_case_ids = [str(detail.get("case_id") or "") for detail in wrong]
    if any(not case_id for case_id in wrong_case_ids):
        raise BenchmarkInputError("fusion wrong-case evidence missing case_id")
    return {
        "mode": _VISTA_MODE,
        "nominal_selected_count": len(selected),
        "correct_selected_count": len(correct),
        "wrong_selected_count": len(wrong),
        "wrong_case_ids_post_selection_evidence": wrong_case_ids,
        "safety_credited_avoided_calls": 0 if wrong else len(correct),
    }


def build_role_value_report(provider_report: dict[str, Any], fusion_report: dict[str, Any]) -> dict[str, Any]:
    _validate_provider_report(provider_report)
    _validate_fusion_report(fusion_report)
    discovery = {}
    workload = {}
    for provider in ("qwen", "omniparser"):
        discovery[provider], workload[provider] = _provider_measurements(provider_report, provider)
    avoidance = _vista_avoidance(fusion_report)
    candidate_delta = discovery["omniparser"]["critical_box_found_count"] - discovery["qwen"]["critical_box_found_count"]
    correction_delta = workload["qwen"]["geometry_correction_raw_count"] - workload["omniparser"]["geometry_correction_raw_count"]
    omni_accept_count = workload["omniparser"]["raw"]["accept"]
    omni_target_count = discovery["omniparser"]["critical_target_count"]
    semantic_review_reason = (
        "all Omni critical boxes still require semantic review"
        if omni_accept_count == 0
        else f"{omni_target_count - omni_accept_count} Omni critical targets still require semantic review"
    )
    candidate_delta_reason = (
        f"adds {candidate_delta} critical boxes"
        if candidate_delta > 0
        else f"loses {abs(candidate_delta)} critical boxes"
        if candidate_delta < 0
        else "has no critical-box change"
    )
    correction_delta_reason = (
        f"reduces geometry correction events by {correction_delta}"
        if correction_delta > 0
        else f"increases geometry correction events by {abs(correction_delta)}"
        if correction_delta < 0
        else "does not change geometry correction events"
    )
    return {
        "contract_version": "omniparser_role_value_benchmark_v1",
        "scope": "frozen artifact decision report; review-only candidate geometry; no model, GUI, click, or authorization",
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "candidate_discovery": discovery,
        "human_review_actions": workload,
        "vista_avoidance": avoidance,
        "disposition": {
            "decision": "KEEP_SHADOW",
            "reasons": [
                f"candidate discovery {candidate_delta_reason} and {correction_delta_reason}",
                f"clutter remains {discovery['omniparser']['candidate_count']} Omni candidates versus {discovery['qwen']['candidate_count']} Qwen candidates",
                semantic_review_reason,
                f"fused bypass has {avoidance['wrong_selected_count']} wrong targets",
                "bounded-ROI VISTA benefit is not measured",
                "active review time is not measured",
            ],
        },
        "measurement_limits": {
            "candidate_availability_and_review": (
                f"{discovery['omniparser']['critical_box_found_count']}/{discovery['omniparser']['critical_target_count']} Omni critical box availability and critical-review associations are posthoc candidate-availability/review measurements, not online selection accuracy."
            ),
            "vista_reference": "The current VISTA reference is direct/full-screen; bounded ROI benefit remains unmeasured.",
            "cross_report_screenshot_sha_binding": (
                "The fusion report has no per-app screenshot SHA map, so cross-report SHA binding is not validated; "
                "contract/version and app/case bindings are validated instead."
            ),
        },
    }


def run_benchmark(benchmark_dir: Path) -> dict[str, Any]:
    benchmark_dir = Path(benchmark_dir).resolve()
    return build_role_value_report(
        _load_json(benchmark_dir / "report.json"),
        _load_json(benchmark_dir / "omniparser_goal_selection_fusion_report_v3.json"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Omni candidate-geometry role value from frozen reports.")
    parser.add_argument("--benchmark-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(args.benchmark_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for provider, summary in report["candidate_discovery"].items():
            print(
                f"{provider}: candidates={summary['candidate_count']} critical_boxes={summary['critical_box_found_count']}/"
                f"{summary['critical_target_count']} strict_geometry={summary['critical_strict_geometry_count']}"
            )
        print(f"disposition={report['disposition']['decision']}")
        print(f"report_path={args.out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
