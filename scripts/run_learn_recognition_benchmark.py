from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
from app.learn.recognition import build_learning_recognition_trial
from app.learn.recognition.grounding import normalize_grounding_result_to_screen
from app.learn.recognition.support_eligibility import (
    finalize_support_eligibility_summary,
    merge_support_eligibility_summary,
    new_support_eligibility_summary,
    summarize_support_eligibility_from_inventory,
)


METRIC_NAMES = (
    "parse_inventory",
    "actionable_classification",
    "form_field_classification",
    "non_actionable_leaked_to_grounding",
    "semantic_bbox_without_interactable_evidence",
    "semantic_only_rejection",
    "non_actionable_rejection",
    "danger_zone_rejection",
    "wrong_surface_rejection",
    "roi_target_coverage",
    "grounding_point",
    "coordinate_transform",
    "pathgraph_candidate_validation",
)

SOURCE_TYPES = (
    "fixture_only",
    "recorded_parser_output",
    "recorded_grounding_output",
    "actual_parser_call",
    "actual_grounding_call",
)


def run_benchmark(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
    json_stdout: bool = False,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    out_dir = Path(out_dir)
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    cases = manifest.get("cases") if isinstance(manifest, dict) else []
    cases = cases if isinstance(cases, list) else []

    counters = {name: {"passed": 0, "attempted": 0} for name in METRIC_NAMES}
    failures: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    source_breakdown = {name: 0 for name in SOURCE_TYPES}
    recorded_model_profile_breakdown: dict[str, dict[str, int]] = {
        "recorded_parser_output": {},
        "recorded_grounding_output": {},
    }
    grounding_eligibility_breakdown = _new_grounding_eligibility_breakdown()
    support_eligibility_summary = new_support_eligibility_summary()

    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or f"case_{len(case_results) + 1}")
        source_type = _case_source_type(case)
        observe_bundle = _observe_bundle_for_case(case, manifest_path.parent)
        if not isinstance(observe_bundle, dict):
            invalid_cases.append(
                {
                    "case_id": case_id,
                    "failure_category": "invalid_fixture",
                    "reason": "observe_bundle is required",
                    "source_type": source_type,
                }
            )
            continue
        source_breakdown[source_type] += 1
        recorded_profile = _recorded_model_profile_for_case(case, manifest_path.parent)
        if recorded_profile:
            _increment_recorded_profile_breakdown(recorded_model_profile_breakdown, source_type, recorded_profile)

        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        result = build_learning_recognition_trial(
            observe_bundle=observe_bundle,
            state_guess=str(case.get("surface") or case_id),
            summary=str(case.get("goal") or ""),
            grounding_adapter=_grounding_adapter_for_case(case),
        )
        case_result = {
            "case_id": case_id,
            "source_type": source_type,
            "source_artifacts": _source_artifacts_for_case(case),
            "status": result["status"],
            "metrics": {},
        }
        if recorded_profile:
            case_result["recorded_model_profile"] = recorded_profile
        case_result["grounding_eligibility"] = _grounding_eligibility_summary(result)
        case_result["support_eligibility"] = summarize_support_eligibility_from_inventory(result.get("screen_inventory"))
        _merge_grounding_eligibility_breakdown(grounding_eligibility_breakdown, case_result["grounding_eligibility"])
        merge_support_eligibility_summary(support_eligibility_summary, case_result["support_eligibility"])
        _score_parse_inventory(counters, failures, case_result, case_id, result, expected)
        _score_actionable_classification(counters, failures, case_result, case_id, result, expected)
        _score_form_field_classification(counters, failures, case_result, case_id, result, expected)
        _score_non_actionable_leakage(counters, failures, case_result, case_id, result, expected)
        _score_semantic_bbox_without_interactable_evidence(counters, failures, case_result, case_id, result, expected)
        _score_non_actionable_rejection(counters, failures, case_result, case_id, result, expected)
        _score_danger_zone_rejection(counters, failures, case_result, case_id, result, expected)
        _score_wrong_surface_rejection(counters, failures, case_result, case_id, result, expected)
        _score_roi_target_coverage(counters, failures, case_result, case_id, result, expected)
        _score_grounding(counters, failures, case_result, case_id, result, expected)
        _score_pathgraph_candidate_validation(counters, failures, case_result, case_id, result, expected, case, root)
        case_results.append(case_result)

    report = {
        "contract_version": "learn_recognition_benchmark_report_v1",
        "manifest_path": str(manifest_path),
        "case_count": len(cases),
        "valid_case_count": len(case_results),
        "invalid_case_count": len(invalid_cases),
        "metrics": {name: _metric_result(value) for name, value in counters.items()},
        "source_breakdown": source_breakdown,
        "recorded_model_profile_breakdown": recorded_model_profile_breakdown,
        "grounding_eligibility_breakdown": grounding_eligibility_breakdown,
        "support_eligibility_summary": finalize_support_eligibility_summary(support_eligibility_summary),
        "parser_output_quality": _parser_output_quality(grounding_eligibility_breakdown),
        "parser_reliability_status": _parser_reliability_status(source_breakdown),
        "grounding_reliability_status": _grounding_reliability_status(source_breakdown),
        "failures": failures,
        "invalid_cases": invalid_cases,
        "case_results": case_results,
        "recorded_output_interpretation": (
            "recorded parser/grounding outputs exercise ingestion and validation only; "
            "they are not a new actual model call in this run and are insufficient for reliability claims"
        ),
        "interpretation": "layered benchmark only; no total rate, no model accuracy claim, no execute authorization",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "learn_recognition_benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _grounding_adapter_for_case(case: dict[str, Any]):
    grounding_by_label = _grounding_for_case(case)
    if not grounding_by_label:
        return None

    def adapter(*, item: dict[str, Any], roi_crop: dict[str, Any]) -> dict[str, Any]:
        label = str(item.get("label") or "")
        result = grounding_by_label.get(label)
        result = result if isinstance(result, dict) else {}
        result = _normalize_recorded_grounding_result(dict(result), roi_crop=roi_crop)
        result.setdefault("debug", {})
        result["debug"]["roi_contract"] = roi_crop.get("contract_version")
        return result

    return adapter


def _normalize_recorded_grounding_result(result: dict[str, Any], *, roi_crop: dict[str, Any]) -> dict[str, Any]:
    return normalize_grounding_result_to_screen(result, roi_crop=roi_crop)


def _observe_bundle_for_case(case: dict[str, Any], manifest_dir: Path) -> dict[str, Any] | None:
    inline = case.get("observe_bundle")
    if isinstance(inline, dict):
        return inline
    path_value = case.get("recorded_parser_output_path")
    if not path_value:
        return None
    payload = _read_json_artifact(manifest_dir, path_value)
    if not isinstance(payload, dict):
        return None
    observe_bundle = payload.get("observe_bundle")
    if isinstance(observe_bundle, dict):
        return _observe_bundle_with_recorded_metadata(observe_bundle, payload=payload, path_value=path_value)
    if isinstance(payload.get("sources"), dict):
        return payload
    return None


def _observe_bundle_with_recorded_metadata(
    observe_bundle: dict[str, Any],
    *,
    payload: dict[str, Any],
    path_value: Any,
) -> dict[str, Any]:
    bundle = deepcopy(observe_bundle)
    for key in ("screenshot_sha256", "image_sha256", "coordinate_space", "source_run_id", "capture_time", "timestamp"):
        if key not in bundle and payload.get(key) is not None:
            bundle[key] = payload.get(key)
    if "raw_payload_path" not in bundle:
        bundle["raw_payload_path"] = str(path_value or "")
    return bundle


def _grounding_for_case(case: dict[str, Any]) -> dict[str, Any]:
    inline = case.get("grounding")
    if isinstance(inline, dict):
        return inline
    path_value = case.get("recorded_grounding_output_path")
    if not path_value:
        return {}
    payload = _read_json_artifact(Path("."), path_value)
    if not isinstance(payload, dict):
        return {}
    for key in ("grounding", "grounding_by_label"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _read_json_artifact(base_dir: Path, path_value: Any) -> dict[str, Any] | None:
    path_text = str(path_value or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        manifest_relative = base_dir / path
        path = manifest_relative if manifest_relative.exists() else PROJECT_ROOT / path
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _source_artifacts_for_case(case: dict[str, Any]) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for key in ("recorded_parser_output_path", "recorded_grounding_output_path"):
        value = str(case.get(key) or "").strip()
        if value:
            artifacts[key] = value
    return artifacts


def _recorded_model_profile_for_case(case: dict[str, Any], manifest_dir: Path) -> dict[str, Any]:
    source_type = _case_source_type(case)
    path_key = {
        "recorded_parser_output": "recorded_parser_output_path",
        "recorded_grounding_output": "recorded_grounding_output_path",
    }.get(source_type)
    if not path_key:
        return {}
    payload = _read_json_artifact(manifest_dir, case.get(path_key))
    if not isinstance(payload, dict):
        return {}
    profile = payload.get("model_profile") if isinstance(payload.get("model_profile"), dict) else {}
    profile_id = str(payload.get("model_profile_id") or profile.get("profile_id") or "").strip()
    model_id = str(payload.get("model_id") or profile.get("model_id") or "").strip()
    provider = str(payload.get("provider") or profile.get("provider_mode") or "").strip()
    if not profile_id and not model_id:
        return {}
    return {
        "profile_id": profile_id or "unknown_profile",
        "model_id": model_id,
        "provider": provider,
        "source_type": source_type,
        "actual_model_call_in_this_run": bool(payload.get("actual_model_call_in_this_run")),
    }


def _increment_recorded_profile_breakdown(
    breakdown: dict[str, dict[str, int]],
    source_type: str,
    profile: dict[str, str],
) -> None:
    if source_type not in breakdown:
        return
    profile_id = str(profile.get("profile_id") or "unknown_profile")
    breakdown[source_type][profile_id] = int(breakdown[source_type].get(profile_id, 0)) + 1


def _case_source_type(case: dict[str, Any]) -> str:
    value = str(case.get("source_type") or "fixture_only")
    return value if value in SOURCE_TYPES else "fixture_only"


def _parser_reliability_status(source_breakdown: dict[str, int]) -> str:
    if source_breakdown["actual_parser_call"] > 0:
        return "actual_parser_call_minimal_coverage"
    if source_breakdown["recorded_parser_output"] > 0:
        return "recorded_parser_output_minimal_coverage"
    return "fixture_only_not_model_validated"


def _grounding_reliability_status(source_breakdown: dict[str, int]) -> str:
    if source_breakdown["actual_grounding_call"] > 0:
        return "actual_grounding_call_minimal_coverage"
    if source_breakdown["recorded_grounding_output"] > 0:
        return "recorded_grounding_output_minimal_coverage"
    return "fixture_only_not_model_validated"


def _score_parse_inventory(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    minimum = expected.get("inventory_min_count")
    if minimum is None:
        return
    _attempt(counters, "parse_inventory")
    actual = len(result.get("screen_inventory") if isinstance(result.get("screen_inventory"), list) else [])
    passed = actual >= _int_or_zero(minimum)
    _record_metric(case_result, "parse_inventory", passed)
    if passed:
        _pass(counters, "parse_inventory")
    else:
        _failure(failures, case_id, "parse_inventory", "inventory_count_below_expected", minimum, actual)


def _score_actionable_classification(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("actionable_labels"))
    if not labels:
        return
    _attempt(counters, "actionable_classification")
    actual = _labels(result["classification"].get("accepted_for_grounding"))
    passed = set(labels).issubset(actual)
    _record_metric(case_result, "actionable_classification", passed)
    if passed:
        _pass(counters, "actionable_classification")
    else:
        _failure(failures, case_id, "actionable_classification", "missing_actionable_labels", labels, sorted(actual))


def _score_form_field_classification(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("form_field_labels"))
    if not labels:
        return
    _attempt(counters, "form_field_classification")
    accepted_items = result["classification"].get("accepted_for_grounding")
    actual = {
        str(item.get("label") or "")
        for item in accepted_items
        if isinstance(item, dict) and str(item.get("item_type") or "").casefold() == "form_field"
    }
    passed = set(labels).issubset(actual)
    _record_metric(case_result, "form_field_classification", passed)
    if passed:
        _pass(counters, "form_field_classification")
    else:
        _failure(failures, case_id, "form_field_classification", "missing_form_field_labels", labels, sorted(actual))


def _score_non_actionable_leakage(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("not_grounded_labels"))
    if not labels:
        return
    _attempt(counters, "non_actionable_leaked_to_grounding")
    actual = _labels(result["classification"].get("accepted_for_grounding"))
    leaked = sorted(set(labels).intersection(actual))
    passed = not leaked
    _record_metric(case_result, "non_actionable_leaked_to_grounding", passed)
    if passed:
        _pass(counters, "non_actionable_leaked_to_grounding")
    else:
        _failure(failures, case_id, "non_actionable_leaked_to_grounding", "non_actionable_leaked_to_grounding", labels, leaked)


def _score_semantic_bbox_without_interactable_evidence(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("semantic_without_interactable_labels"))
    if not labels:
        return
    _attempt(counters, "semantic_bbox_without_interactable_evidence")
    _attempt(counters, "semantic_only_rejection")
    rejected = _labels(result["classification"].get("rejected_non_actionable"))
    accepted = _labels(result["classification"].get("accepted_for_grounding"))
    passed = set(labels).issubset(rejected) and not set(labels).intersection(accepted)
    _record_metric(case_result, "semantic_bbox_without_interactable_evidence", passed)
    _record_metric(case_result, "semantic_only_rejection", passed)
    if passed:
        _pass(counters, "semantic_bbox_without_interactable_evidence")
        _pass(counters, "semantic_only_rejection")
    else:
        _failure(
            failures,
            case_id,
            "semantic_bbox_without_interactable_evidence",
            "semantic_bbox_without_interactable_evidence",
            labels,
            {"accepted": sorted(accepted), "rejected": sorted(rejected)},
        )
        _failure(
            failures,
            case_id,
            "semantic_only_rejection",
            "semantic_only_region_leaked_or_missing_rejection",
            labels,
            {"accepted": sorted(accepted), "rejected": sorted(rejected)},
        )


def _score_non_actionable_rejection(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("rejected_labels"))
    if not labels:
        return
    _attempt(counters, "non_actionable_rejection")
    actual = _labels(result["classification"].get("rejected_non_actionable"))
    passed = set(labels).issubset(actual)
    _record_metric(case_result, "non_actionable_rejection", passed)
    if passed:
        _pass(counters, "non_actionable_rejection")
    else:
        _failure(failures, case_id, "non_actionable_rejection", "missing_rejected_labels", labels, sorted(actual))


def _score_danger_zone_rejection(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("danger_zone_labels"))
    if not labels:
        return
    _attempt(counters, "danger_zone_rejection")
    actual = _labels(result["classification"].get("danger_zones"))
    passed = set(labels).issubset(actual)
    _record_metric(case_result, "danger_zone_rejection", passed)
    if passed:
        _pass(counters, "danger_zone_rejection")
    else:
        _failure(failures, case_id, "danger_zone_rejection", "missing_danger_zone_labels", labels, sorted(actual))


def _score_wrong_surface_rejection(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("wrong_surface_labels"))
    if not labels:
        return
    _attempt(counters, "wrong_surface_rejection")
    classification = result["classification"]
    accepted = _labels(classification.get("accepted_for_grounding"))
    rejected = _labels(classification.get("rejected_non_actionable"))
    danger = _labels(classification.get("danger_zones"))
    safe_rejected = rejected.union(danger)
    leaked = sorted(set(labels).intersection(accepted))
    missing_safe_rejection = sorted(set(labels).difference(safe_rejected))
    passed = not leaked and not missing_safe_rejection
    _record_metric(case_result, "wrong_surface_rejection", passed)
    if passed:
        _pass(counters, "wrong_surface_rejection")
    else:
        _failure(
            failures,
            case_id,
            "wrong_surface_rejection",
            "wrong_surface_not_safely_rejected",
            labels,
            {
                "accepted_for_grounding": sorted(accepted),
                "rejected_or_danger": sorted(safe_rejected),
                "leaked": leaked,
                "missing_safe_rejection": missing_safe_rejection,
            },
        )


def _score_roi_target_coverage(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("roi_coverage_labels"))
    if not labels:
        return
    _attempt(counters, "roi_target_coverage")
    roi_crops = result.get("roi_crops")
    roi_crops = roi_crops if isinstance(roi_crops, list) else []
    actual_by_label: dict[str, dict[str, Any]] = {}
    for roi_crop in roi_crops:
        if not isinstance(roi_crop, dict):
            continue
        request = roi_crop.get("grounding_request") if isinstance(roi_crop.get("grounding_request"), dict) else {}
        target = request.get("target") if isinstance(request.get("target"), dict) else {}
        label = str(target.get("label") or "")
        if not label:
            continue
        bbox = target.get("candidate_bbox_in_roi") if isinstance(target.get("candidate_bbox_in_roi"), dict) else {}
        crop_size = roi_crop.get("crop_size") if isinstance(roi_crop.get("crop_size"), dict) else {}
        transform = roi_crop.get("coordinate_transform") if isinstance(roi_crop.get("coordinate_transform"), dict) else {}
        actual_by_label[label] = {
            "candidate_bbox_in_roi": bbox,
            "crop_size": crop_size,
            "coordinate_transform_contract": transform.get("contract_version"),
            "covered": _bbox_inside_size(bbox, crop_size) and transform.get("contract_version") == "coordinate_transform_v1",
        }

    missing = [label for label in labels if label not in actual_by_label]
    uncovered = [label for label in labels if label in actual_by_label and not actual_by_label[label].get("covered")]
    passed = not missing and not uncovered
    _record_metric(case_result, "roi_target_coverage", passed)
    if passed:
        _pass(counters, "roi_target_coverage")
    else:
        _failure(
            failures,
            case_id,
            "roi_target_coverage",
            "roi_target_not_fully_covered",
            labels,
            {"missing": missing, "uncovered": uncovered, "roi_targets": actual_by_label},
        )


def _score_grounding(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    labels = _string_list(expected.get("grounding_valid_labels"))
    if not labels:
        return
    validations = result.get("grounding_validations")
    validations = validations if isinstance(validations, list) else []
    valid_by_label = {
        str(item.get("item_id") or ""): item
        for item in validations
        if isinstance(item, dict) and item.get("status") == "valid_candidate"
    }
    all_by_id = {str(item.get("item_id") or ""): item for item in validations if isinstance(item, dict)}
    accepted_items = result["classification"].get("accepted_for_grounding")
    label_to_id = {str(item.get("label") or ""): str(item.get("item_id") or "") for item in accepted_items if isinstance(item, dict)}

    _attempt(counters, "grounding_point")
    point_passed = all(label_to_id.get(label) in valid_by_label for label in labels)
    _record_metric(case_result, "grounding_point", point_passed)
    if point_passed:
        _pass(counters, "grounding_point")
    else:
        failing_label = next((label for label in labels if label_to_id.get(label) not in valid_by_label), labels[0])
        failed_validation = all_by_id.get(label_to_id.get(failing_label, ""))
        _failure(
            failures,
            case_id,
            "grounding_point",
            str((failed_validation or {}).get("failure_category") or "grounding_not_valid"),
            labels,
            _validation_actual(failed_validation),
        )

    _attempt(counters, "coordinate_transform")
    transform_passed = all(
        bool((all_by_id.get(label_to_id.get(label, "")) or {}).get("checks", {}).get("coordinate_transform_replay"))
        for label in labels
    )
    _record_metric(case_result, "coordinate_transform", transform_passed)
    if transform_passed:
        _pass(counters, "coordinate_transform")
    else:
        _failure(failures, case_id, "coordinate_transform", "coordinate_transform_not_replayable", labels, None)


def _score_pathgraph_candidate_validation(
    counters: dict[str, dict[str, int]],
    failures: list[dict[str, Any]],
    case_result: dict[str, Any],
    case_id: str,
    result: dict[str, Any],
    expected: dict[str, Any],
    case: dict[str, Any],
    project_root: Path,
) -> None:
    expected_status = expected.get("pathgraph_candidate_validation_status")
    if expected_status is None:
        return
    _attempt(counters, "pathgraph_candidate_validation")
    draft_dir = project_root / "artifacts" / "learn-recognition-benchmark" / _safe_path_part(case_id)
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / "learning_draft.json"
    draft_path.write_text(json.dumps(result["learning_draft"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        build_result = build_pathgraph_candidate_from_review(
            draft_path,
            case.get("review_patch") if isinstance(case.get("review_patch"), dict) else {},
            project_root=project_root,
        )
    except Exception as exc:
        _record_metric(case_result, "pathgraph_candidate_validation", False)
        _failure(
            failures,
            case_id,
            "pathgraph_candidate_validation",
            "pathgraph_candidate_build_failed",
            expected_status,
            str(exc),
        )
        return
    passed = build_result.get("validation_status") == expected_status and build_result.get("execute_binding_enabled") is False
    _record_metric(case_result, "pathgraph_candidate_validation", passed)
    case_result["pathgraph_candidate"] = {
        "validation_status": build_result.get("validation_status"),
        "pathgraph_candidate_path": build_result.get("pathgraph_candidate_path"),
        "validation_report_path": build_result.get("validation_report_path"),
        "artifact_is_authorization": build_result.get("artifact_is_authorization"),
        "execute_binding_enabled": build_result.get("execute_binding_enabled"),
    }
    if passed:
        _pass(counters, "pathgraph_candidate_validation")
    else:
        _failure(
            failures,
            case_id,
            "pathgraph_candidate_validation",
            "pathgraph_candidate_validation_status_mismatch",
            expected_status,
            case_result["pathgraph_candidate"],
        )


def _metric_result(counter: dict[str, int]) -> dict[str, Any]:
    attempted = counter["attempted"]
    passed = counter["passed"]
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": "not_covered" if attempted == 0 else round(passed / attempted, 4),
    }


def _new_grounding_eligibility_breakdown() -> dict[str, Any]:
    return {
        "total_classified_items": 0,
        "grounding_eligible": 0,
        "review_only": 0,
        "blocked_reasons": {},
        "interpretation": (
            "semantic-only parser output is review evidence only unless OCR/UIA/DOM/parser interactable evidence "
            "makes it eligible for grounding"
        ),
    }


def _grounding_eligibility_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = _new_grounding_eligibility_breakdown()
    classification = result.get("classification") if isinstance(result.get("classification"), dict) else {}
    for bucket in ("accepted_for_grounding", "rejected_non_actionable", "needs_human_review", "danger_zones"):
        items = classification.get(bucket)
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            summary["total_classified_items"] += 1
            if item.get("grounding_eligible") is True:
                summary["grounding_eligible"] += 1
            if item.get("review_only") is True:
                summary["review_only"] += 1
            reason = str(item.get("grounding_block_reason") or "").strip()
            if reason:
                blocked = summary["blocked_reasons"]
                blocked[reason] = int(blocked.get(reason, 0)) + 1
    return summary


def _merge_grounding_eligibility_breakdown(total: dict[str, Any], case_summary: dict[str, Any]) -> None:
    total["total_classified_items"] += int(case_summary.get("total_classified_items") or 0)
    total["grounding_eligible"] += int(case_summary.get("grounding_eligible") or 0)
    total["review_only"] += int(case_summary.get("review_only") or 0)
    total_reasons = total["blocked_reasons"]
    case_reasons = case_summary.get("blocked_reasons") if isinstance(case_summary.get("blocked_reasons"), dict) else {}
    for reason, count in case_reasons.items():
        total_reasons[str(reason)] = int(total_reasons.get(str(reason), 0)) + int(count or 0)


def _parser_output_quality(grounding_eligibility_breakdown: dict[str, Any]) -> dict[str, Any]:
    review_only_count = int(grounding_eligibility_breakdown.get("review_only") or 0)
    grounding_eligible_count = int(grounding_eligibility_breakdown.get("grounding_eligible") or 0)
    return {
        "review_only_items": review_only_count,
        "grounding_eligible_items": grounding_eligible_count,
        "parser_useful_for_review": review_only_count > 0,
        "parser_useful_for_grounding": grounding_eligible_count > 0,
        "interpretation": "review usefulness is not grounding success, click success, or PathGraph execute authorization",
    }


def _attempt(counters: dict[str, dict[str, int]], metric: str) -> None:
    counters[metric]["attempted"] += 1


def _pass(counters: dict[str, dict[str, int]], metric: str) -> None:
    counters[metric]["passed"] += 1


def _record_metric(case_result: dict[str, Any], metric: str, passed: bool) -> None:
    case_result["metrics"][metric] = "passed" if passed else "failed"


def _failure(
    failures: list[dict[str, Any]],
    case_id: str,
    metric: str,
    failure_category: str,
    expected: Any,
    actual: Any,
) -> None:
    failures.append(
        {
            "case_id": case_id,
            "metric": metric,
            "failure_category": failure_category,
            "expected": expected,
            "actual": actual,
        }
    )


def _labels(value: Any) -> set[str]:
    items = value if isinstance(value, list) else []
    return {str(item.get("label") or "") for item in items if isinstance(item, dict)}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value if str(item or "").strip()] if isinstance(value, list) else []


def _validation_actual(validation: dict[str, Any] | None) -> dict[str, Any]:
    validation = validation if isinstance(validation, dict) else {}
    return {
        "status": validation.get("status"),
        "failure_category": validation.get("failure_category"),
        "screen_point": validation.get("screen_point"),
        "screen_bbox": validation.get("screen_bbox"),
        "checks": validation.get("checks"),
    }


def _bbox_inside_size(bbox: dict[str, Any], size: dict[str, Any]) -> bool:
    try:
        x = float(bbox.get("x"))
        y = float(bbox.get("y"))
        w = float(bbox.get("w"))
        h = float(bbox.get("h"))
        width = float(size.get("width"))
        height = float(size.get("height"))
    except (TypeError, ValueError):
        return False
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_") or "case"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_benchmark(manifest_path=args.manifest, out_dir=args.out, json_stdout=args.json)


if __name__ == "__main__":
    main()
