from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.classifier import classify_inventory_items
from app.learn.recognition.grounding import build_grounding_request, normalize_grounding_result_to_screen
from app.learn.recognition.parsers import parse_existing_evidence_to_inventory
from app.learn.recognition.pipeline import build_learning_recognition_trial
from app.learn.recognition.roi import bounded_roi_crop_size_for_bbox, build_roi_crop_metadata
from app.learn.recognition.validator import validate_grounding_candidate
from app.vision.local_provider import LocalVisionProvider


ModelCaller = Callable[[Path, str, dict[str, Any]], dict[str, Any]]


def run_actual_grounding_smoke(
    *,
    manifest_path: str | Path,
    case_id: str,
    label: str,
    screenshot_path: str | Path,
    out_dir: str | Path,
    endpoint: str | None,
    model_name: str | None,
    model_profile_id: str | None = None,
    timeout_seconds: float = 60.0,
    roi_bbox_override: dict[str, Any] | None = None,
    model_caller: ModelCaller | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    screenshot_path = Path(screenshot_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_profile = _load_model_profile(model_profile_id)
    model_profile_summary = _model_profile_summary(model_profile, model_profile_id)
    resolved_endpoint = endpoint or str(model_profile.get("endpoint") or "") or None
    resolved_model_name = (
        model_name
        or str(model_profile.get("model_name") or "")
        or str(model_profile.get("model_id") or "")
        or "inclusionAI/VISTA-4B"
    )
    base_model_config = {
        "endpoint": resolved_endpoint,
        "model_name": resolved_model_name,
        "model_profile_id": model_profile_summary.get("profile_id"),
        "model_profile": model_profile_summary,
        "timeout_seconds": timeout_seconds,
    }
    manifest = _read_json(manifest_path)
    case = _find_case(manifest, case_id)
    observe_bundle = _observe_bundle_for_case(case, manifest_path.parent)
    if not isinstance(observe_bundle, dict):
        report = _write_blocked_report(
            out_dir=out_dir,
            case_id=case_id,
            label=label,
            screenshot_path=screenshot_path,
            blocker_category="fixture_precondition_failed",
            message=f"case {case_id} does not contain an observe bundle",
            model_config=base_model_config,
        )
        if json_stdout:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    if not screenshot_path.exists():
        report = _write_blocked_report(
            out_dir=out_dir,
            case_id=case_id,
            label=label,
            screenshot_path=screenshot_path,
            blocker_category="stale_fixture",
            message=f"screenshot fixture does not exist: {screenshot_path}",
            model_config=base_model_config,
            status="invalid",
            source_type="fixture_only",
            extra={
                "fixture_validity": {
                    "status": "invalid",
                    "failure_category": "stale_fixture",
                    "reason": "missing_screenshot",
                    "screenshot_path": str(screenshot_path),
                },
                "interpretation": "invalid stale fixture; excluded from pass/fail and actual_model_call denominators",
            },
        )
        if json_stdout:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    inventory = parse_existing_evidence_to_inventory(observe_bundle)
    classification = classify_inventory_items(inventory)
    item = _find_accepted_item(classification, label)
    if item is None:
        report = _write_blocked_report(
            out_dir=out_dir,
            case_id=case_id,
            label=label,
            screenshot_path=screenshot_path,
            blocker_category="fixture_precondition_failed",
            message=f"no accepted grounding item with label {label!r} in case {case_id}",
            model_config=base_model_config,
            extra={
                "classification_summary": classification.get("summary") if isinstance(classification, dict) else {},
                "accepted_labels": [
                    str(entry.get("label") or "")
                    for entry in classification.get("accepted_for_grounding", [])
                    if isinstance(entry, dict)
                ],
            },
        )
        if json_stdout:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return report

    source_image_size = _image_size(screenshot_path)
    roi_crop = build_roi_crop_metadata(
        source_image_size=source_image_size,
        candidate_bbox=item.get("bbox") if isinstance(item, dict) else {},
        crop_size=_crop_size_for_item(item),
    )
    roi_crop = _apply_roi_bbox_override(roi_crop, source_image_size=source_image_size, override=roi_bbox_override)
    grounding_request = build_grounding_request(item=item, roi_crop=roi_crop, goal=f"locate {label}")
    roi_crop["grounding_request"] = grounding_request

    roi_image_path = out_dir / f"{_safe_path_part(case_id)}__{_safe_path_part(label)}__roi.png"
    _write_roi_image(screenshot_path, roi_crop, roi_image_path)

    prompt = _grounding_prompt(grounding_request)
    model_config = {
        "endpoint": resolved_endpoint,
        "model_name": resolved_model_name,
        "model_profile_id": model_profile_summary.get("profile_id"),
        "model_profile": model_profile_summary,
        "timeout_seconds": timeout_seconds,
        "image_path": str(roi_image_path),
    }
    readiness_blocker = _model_profile_readiness_blocker(
        profile=model_profile,
        profile_summary=model_profile_summary,
        endpoint=resolved_endpoint,
    )
    if readiness_blocker:
        report = _write_blocked_report(
            out_dir=out_dir,
            case_id=case_id,
            label=label,
            screenshot_path=screenshot_path,
            blocker_category=str(readiness_blocker["failure_category"]),
            message=str(readiness_blocker["message"]),
            model_config=model_config,
            extra={
                "roi_image_path": str(roi_image_path),
                "grounding_request": grounding_request,
                "model_profile_readiness": readiness_blocker,
            },
        )
        if json_stdout:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return report
    model_call = model_caller or _default_model_caller(endpoint=resolved_endpoint, model_name=resolved_model_name, timeout_seconds=timeout_seconds)

    try:
        model_result = model_call(roi_image_path, prompt, model_config)
        raw_text = str(model_result.get("raw_text") or "")
        grounding = parse_grounding_model_output(raw_text)
        grounding["evidence"] = {
            "screenshot_freshness": True,
            "uia_or_dom_or_parser_overlap": True,
        }
        grounding["model_io"] = {
            "contract_version": "learn_actual_grounding_model_io_v1",
            "endpoint": resolved_endpoint,
            "model_name": resolved_model_name,
            "model_profile": model_profile_summary,
            "prompt": prompt,
            "raw_text": raw_text,
            "raw_response": model_result.get("raw_response"),
        }
        normalized_grounding = normalize_grounding_result_to_screen(grounding, roi_crop=roi_crop)
        validation = validate_grounding_candidate(
            item=item,
            grounding=normalized_grounding,
            evidence=_validation_evidence(item=item, grounding=normalized_grounding),
        )
        point_quality = _point_quality_diagnosis(
            grounding_request=grounding_request,
            normalized_grounding=normalized_grounding,
            validation=validation,
        )
        pipeline_result = build_learning_recognition_trial(
            observe_bundle=observe_bundle,
            state_guess=str(case.get("surface") or case_id),
            summary=str(case.get("goal") or f"Actual grounding smoke for {label}"),
            grounding_adapter=lambda *, item, roi_crop: normalized_grounding,
        )
        actual_grounding_output_path = out_dir / "actual_grounding_output_v1.json"
        actual_grounding_output_path.write_text(
            json.dumps(
                {
                    "contract_version": "actual_grounding_output_v1",
                    "source_type": "actual_grounding_call",
                    "actual_model_call_in_this_run": True,
                    "case_id": case_id,
                    "label": label,
                    "screenshot_path": str(screenshot_path),
                    "roi_image_path": str(roi_image_path),
                    "model_config": model_config,
                    "model_profile": model_profile_summary,
                    "grounding_by_label": {label: normalized_grounding},
                    "validation": validation,
                    "point_quality": point_quality,
                    "interpretation": "saved output from one actual grounding smoke; replaying this artifact later is recorded-output evidence, not a fresh actual model call",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        status = "passed" if validation.get("status") == "valid_candidate" else "failed"
        report = {
            "contract_version": "learn_actual_grounding_smoke_report_v1",
            "status": status,
            "source_type": "actual_grounding_call",
            "actual_model_call_in_this_run": True,
            "case_id": case_id,
            "label": label,
            "screenshot_path": str(screenshot_path),
            "roi_image_path": str(roi_image_path),
            "actual_grounding_output_path": str(actual_grounding_output_path),
            "model_config": model_config,
            "model_profile": model_profile_summary,
            "grounding_request": grounding_request,
            "raw_model_output": raw_text,
            "normalized_grounding": normalized_grounding,
            "validation": validation,
            "point_quality": point_quality,
            "learning_draft": pipeline_result.get("learning_draft"),
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "real_clicks_performed": 0,
                "final_submit_forbidden": True,
            },
            "interpretation": "single-image actual grounding smoke only; no execute authorization and no reliability claim",
        }
    except Exception as exc:
        report = {
            "contract_version": "learn_actual_grounding_smoke_report_v1",
            "status": "blocked",
            "source_type": "actual_grounding_call",
            "actual_model_call_in_this_run": False,
            "blocker": {
                "failure_category": "model_endpoint_unavailable_or_invalid_output",
                "message": str(exc),
            },
            "case_id": case_id,
            "label": label,
            "screenshot_path": str(screenshot_path),
            "roi_image_path": str(roi_image_path),
            "model_config": model_config,
            "model_profile": model_profile_summary,
            "grounding_request": grounding_request,
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "real_clicks_performed": 0,
                "final_submit_forbidden": True,
            },
            "interpretation": "blocked smoke; do not count in actual_grounding_call denominator",
        }

    report_path = out_dir / "learn_actual_grounding_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def run_actual_grounding_smoke_batch(
    *,
    manifest_path: str | Path,
    cases: list[dict[str, Any]],
    out_dir: str | Path,
    endpoint: str | None,
    model_name: str | None,
    model_profile_id: str | None = None,
    timeout_seconds: float = 60.0,
    model_caller: ModelCaller | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_reports: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "").strip()
        label = str(case.get("label") or "").strip()
        screenshot_path = str(case.get("screenshot_path") or case.get("screenshot") or "").strip()
        batch_case_metadata = _batch_case_metadata(case)
        if not case_id or not label or not screenshot_path:
            case_report = {
                "contract_version": "learn_actual_grounding_smoke_report_v1",
                "status": "blocked",
                "source_type": "actual_grounding_call",
                "actual_model_call_in_this_run": False,
                "case_id": case_id or f"case_{index}",
                "label": label,
                "batch_case": batch_case_metadata,
                "blocker": {
                    "failure_category": "invalid_batch_case",
                    "message": "case_id, label, and screenshot_path are required",
                },
                "interpretation": "invalid batch case; do not count in actual_grounding_call denominator",
            }
            case_reports.append(case_report)
            continue
        case_out_dir = out_dir / f"{index:02d}_{_safe_path_part(case_id)}"
        case_report = run_actual_grounding_smoke(
            manifest_path=manifest_path,
            case_id=case_id,
            label=label,
            screenshot_path=screenshot_path,
            out_dir=case_out_dir,
            endpoint=str(case.get("endpoint") or endpoint or ""),
            model_name=case.get("model_name") or model_name,
            model_profile_id=str(case.get("model_profile_id") or model_profile_id or ""),
            timeout_seconds=float(case.get("timeout_seconds") or timeout_seconds),
            roi_bbox_override=case.get("roi_bbox_override") if isinstance(case.get("roi_bbox_override"), dict) else None,
            model_caller=model_caller,
            json_stdout=False,
        )
        case_report["batch_case"] = batch_case_metadata
        case_reports.append(case_report)

    summary = _batch_summary(case_reports)
    report = {
        "contract_version": "learn_actual_grounding_smoke_batch_report_v1",
        "manifest_path": str(manifest_path),
        "case_count": len(cases),
        "summary": summary,
        "actual_model_profile_breakdown": _actual_model_profile_breakdown(case_reports),
        "actual_grounding_failure_categories": _actual_grounding_failure_categories(case_reports),
        "case_reports": case_reports,
        "interpretation": (
            "batch smoke report only; actual_model_call denominator includes only cases where a model endpoint was called; "
            "precondition-blocked cases verify safety/routing and are not model accuracy evidence"
        ),
    }
    report_path = out_dir / "learn_actual_grounding_smoke_batch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _batch_case_metadata(case: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "surface",
        "expected_case_outcome",
        "expected_blocker",
        "reason",
        "model_profile_id",
        "timeout_seconds",
        "roi_bbox_override",
    ]
    metadata = {key: case[key] for key in keys if case.get(key) not in (None, "")}
    metadata["interpretation"] = "batch case review metadata only; not used to score model point quality"
    return metadata


def _batch_summary(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    actual_attempted = [report for report in case_reports if report.get("actual_model_call_in_this_run") is True]
    actual_passed = [report for report in actual_attempted if report.get("status") == "passed"]
    return {
        "total_cases": len(case_reports),
        "passed": sum(1 for report in case_reports if report.get("status") == "passed"),
        "failed": sum(1 for report in case_reports if report.get("status") == "failed"),
        "blocked": sum(1 for report in case_reports if report.get("status") == "blocked"),
        "invalid": sum(1 for report in case_reports if report.get("status") == "invalid"),
        "actual_model_call": {
            "passed": len(actual_passed),
            "attempted": len(actual_attempted),
            "rate": "not_covered" if not actual_attempted else round(len(actual_passed) / len(actual_attempted), 4),
            "interpretation": "fresh actual grounding calls only; not a reliability or 90% accuracy claim",
        },
        "point_center_bias_diagnostic": _point_center_bias_diagnostic(actual_attempted),
        "blocked_categories": _blocked_categories(case_reports),
    }


def _point_center_bias_diagnostic(actual_reports: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(actual_reports)
    near_center = 0
    exact_center = 0
    samples: list[dict[str, Any]] = []
    for report in actual_reports:
        point = _raw_model_point(report)
        if not point:
            continue
        x = _float_or_zero(point.get("x"))
        y = _float_or_zero(point.get("y"))
        is_near = abs(x - 500.0) <= 10.0 and abs(y - 500.0) <= 10.0
        is_exact = x == 500.0 and y == 500.0
        if is_near:
            near_center += 1
        if is_exact:
            exact_center += 1
        if len(samples) < 5:
            samples.append(
                {
                    "case_id": report.get("case_id") or "",
                    "label": report.get("label") or "",
                    "raw_point": {"x": x, "y": y},
                    "near_normalized_center": is_near,
                }
            )
    rate: float | str = "not_covered" if attempted == 0 else round(near_center / attempted, 4)
    if attempted < 3:
        status = "insufficient_sample_size"
    elif near_center / max(1, attempted) >= 0.6:
        status = "center_bias_risk"
    else:
        status = "no_center_bias_signal"
    return {
        "contract_version": "learn_actual_grounding_center_bias_diagnostic_v1",
        "status": status,
        "attempted": attempted,
        "near_center_outputs": near_center,
        "exact_center_outputs": exact_center,
        "near_center_rate": rate,
        "sample_raw_points": samples,
        "interpretation": (
            "diagnostic only; repeated normalized center outputs can pass centered ROI crops and are not model reliability evidence"
        ),
    }


def _raw_model_point(report: dict[str, Any]) -> dict[str, float] | None:
    grounding = report.get("normalized_grounding") if isinstance(report.get("normalized_grounding"), dict) else {}
    raw = grounding.get("raw_output") if isinstance(grounding, dict) else None
    point = _point_from_raw_output(raw)
    if point:
        return point
    raw_text = report.get("raw_model_output")
    if isinstance(raw_text, str) and raw_text.strip():
        try:
            parsed = parse_grounding_model_output(raw_text)
            return _point_from_raw_output(parsed.get("raw_output"))
        except Exception:
            return None
    return None


def _actual_grounding_failure_categories(case_reports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in case_reports:
        if report.get("status") != "failed" or report.get("actual_model_call_in_this_run") is not True:
            continue
        point_quality = report.get("point_quality") if isinstance(report.get("point_quality"), dict) else {}
        validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
        category = str(
            point_quality.get("failure_category")
            or validation.get("failure_category")
            or "actual_grounding_failed"
        )
        counts[category] = counts.get(category, 0) + 1
    return counts


def _actual_model_profile_breakdown(case_reports: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    breakdown: dict[str, dict[str, int]] = {
        "actual_model_call": {},
        "blocked_or_precondition": {},
    }
    for report in case_reports:
        profile = report.get("model_profile") if isinstance(report.get("model_profile"), dict) else {}
        profile_id = str(profile.get("profile_id") or report.get("model_profile_id") or "").strip()
        if not profile_id:
            continue
        if report.get("actual_model_call_in_this_run") is True:
            bucket = "actual_model_call"
        elif report.get("status") == "invalid":
            bucket = "invalid_fixture"
        else:
            bucket = "blocked_or_precondition"
        breakdown.setdefault(bucket, {})
        breakdown[bucket][profile_id] = breakdown[bucket].get(profile_id, 0) + 1
    return breakdown


def _blocked_categories(case_reports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in case_reports:
        if report.get("status") != "blocked":
            continue
        blocker = report.get("blocker") if isinstance(report.get("blocker"), dict) else {}
        category = str(blocker.get("failure_category") or "unknown")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _write_blocked_report(
    *,
    out_dir: Path,
    case_id: str,
    label: str,
    screenshot_path: Path,
    blocker_category: str,
    message: str,
    model_config: dict[str, Any],
    status: str = "blocked",
    source_type: str = "actual_grounding_call",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "contract_version": "learn_actual_grounding_smoke_report_v1",
        "status": status,
        "source_type": source_type,
        "actual_model_call_in_this_run": False,
        "blocker": {
            "failure_category": blocker_category,
            "message": message,
        },
        "case_id": case_id,
        "label": label,
        "screenshot_path": str(screenshot_path),
        "model_config": model_config,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
        "interpretation": "blocked smoke; do not count in actual_grounding_call denominator",
    }
    if extra:
        report.update(extra)
    profile = model_config.get("model_profile") if isinstance(model_config.get("model_profile"), dict) else {}
    if profile:
        report["model_profile"] = profile
        report["model_profile_id"] = profile.get("profile_id")
    report_path = out_dir / "learn_actual_grounding_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _point_quality_diagnosis(
    *,
    grounding_request: dict[str, Any],
    normalized_grounding: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    target = grounding_request.get("target") if isinstance(grounding_request.get("target"), dict) else {}
    roi_bbox = target.get("candidate_bbox_in_roi") if isinstance(target.get("candidate_bbox_in_roi"), dict) else {}
    raw = normalized_grounding.get("raw_output") if isinstance(normalized_grounding, dict) else None
    roi_point = _restored_roi_point(normalized_grounding) or _point_from_raw_output(raw)
    status = "passed_inside_expected_bbox"
    failure_category = None
    error = {"outside_by_x": 0.0, "outside_by_y": 0.0, "distance_to_bbox": 0.0}
    inside = False
    if roi_point and roi_bbox:
        inside = _point_inside_xywh(roi_point, roi_bbox)
        if not inside:
            status = "failed_outside_expected_bbox"
            failure_category = "model_point_outside_roi_candidate_bbox"
            error = _bbox_distance(roi_point, roi_bbox)
    elif validation.get("status") != "valid_candidate":
        status = "failed_missing_roi_point_or_bbox"
        failure_category = str(validation.get("failure_category") or "point_quality_evidence_missing")
    return {
        "contract_version": "learn_actual_grounding_point_quality_v1",
        "status": status,
        "failure_category": failure_category,
        "roi_point": roi_point,
        "roi_point_source": "restored_local_point" if _restored_roi_point(normalized_grounding) else "raw_output",
        "roi_candidate_bbox": dict(roi_bbox) if roi_bbox else {},
        "roi_point_inside_candidate_bbox": inside,
        "screen_point": validation.get("screen_point") if isinstance(validation.get("screen_point"), dict) else {},
        "screen_bbox": validation.get("screen_bbox") if isinstance(validation.get("screen_bbox"), dict) else {},
        "error": error,
        "interpretation": "point-quality diagnosis only; failed points are still blocked by validation and do not authorize Execute",
    }


def _point_from_raw_output(raw: Any) -> dict[str, float] | None:
    if isinstance(raw, list) and len(raw) >= 2:
        return {"x": _float_or_zero(raw[0]), "y": _float_or_zero(raw[1])}
    if isinstance(raw, dict) and raw.get("x") is not None and raw.get("y") is not None:
        return {"x": _float_or_zero(raw.get("x")), "y": _float_or_zero(raw.get("y"))}
    return None


def _restored_roi_point(grounding: dict[str, Any]) -> dict[str, float] | None:
    debug = grounding.get("debug") if isinstance(grounding, dict) and isinstance(grounding.get("debug"), dict) else {}
    point = debug.get("restored_local_point") if isinstance(debug.get("restored_local_point"), dict) else None
    if not point:
        return None
    return {"x": _float_or_zero(point.get("x")), "y": _float_or_zero(point.get("y"))}


def _point_inside_xywh(point: dict[str, float], bbox: dict[str, Any]) -> bool:
    x = _float_or_zero(point.get("x"))
    y = _float_or_zero(point.get("y"))
    bx = _float_or_zero(bbox.get("x"))
    by = _float_or_zero(bbox.get("y"))
    bw = _float_or_zero(bbox.get("w") if bbox.get("w") is not None else bbox.get("width"))
    bh = _float_or_zero(bbox.get("h") if bbox.get("h") is not None else bbox.get("height"))
    return bx <= x <= bx + bw and by <= y <= by + bh


def _bbox_distance(point: dict[str, float], bbox: dict[str, Any]) -> dict[str, float]:
    x = _float_or_zero(point.get("x"))
    y = _float_or_zero(point.get("y"))
    bx = _float_or_zero(bbox.get("x"))
    by = _float_or_zero(bbox.get("y"))
    bw = _float_or_zero(bbox.get("w") if bbox.get("w") is not None else bbox.get("width"))
    bh = _float_or_zero(bbox.get("h") if bbox.get("h") is not None else bbox.get("height"))
    nearest_x = min(max(x, bx), bx + bw)
    nearest_y = min(max(y, by), by + bh)
    outside_by_x = 0.0 if bx <= x <= bx + bw else min(abs(x - bx), abs(x - (bx + bw)))
    outside_by_y = 0.0 if by <= y <= by + bh else min(abs(y - by), abs(y - (by + bh)))
    return {
        "outside_by_x": round(outside_by_x, 4),
        "outside_by_y": round(outside_by_y, 4),
        "distance_to_bbox": round(math.hypot(x - nearest_x, y - nearest_y), 4),
    }


def parse_grounding_model_output(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("grounding model returned empty output")
    parsed: Any
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = _parse_first_numeric_pair(text)
    if isinstance(parsed, list) and len(parsed) >= 2:
        return {
            "coordinate_space": "normalized_0_1000",
            "raw_output": [parsed[0], parsed[1]],
        }
    if isinstance(parsed, dict):
        point = parsed.get("point") if isinstance(parsed.get("point"), dict) else parsed
        bbox = point.get("bbox") if isinstance(point.get("bbox"), dict) else parsed.get("bbox") if isinstance(parsed.get("bbox"), dict) else None
        if isinstance(bbox, dict):
            x = _float_or_zero(bbox.get("x")) + (_float_or_zero(bbox.get("w")) / 2.0)
            y = _float_or_zero(bbox.get("y")) + (_float_or_zero(bbox.get("h")) / 2.0)
            return {
                "coordinate_space": str(point.get("coordinate_space") or parsed.get("coordinate_space") or "normalized_0_1000"),
                "raw_output": [x, y],
            }
        if point.get("x") is not None and point.get("y") is not None:
            return {
                "coordinate_space": str(point.get("coordinate_space") or parsed.get("coordinate_space") or "normalized_0_1000"),
                "raw_output": [point.get("x"), point.get("y")],
            }
    raise ValueError(f"unsupported grounding model output: {text[:200]}")


def _default_model_caller(*, endpoint: str | None, model_name: str, timeout_seconds: float) -> ModelCaller:
    if not endpoint:
        raise ValueError("endpoint is required for actual grounding smoke")
    provider = LocalVisionProvider(endpoint=endpoint, model_name=model_name, timeout_seconds=timeout_seconds)

    def caller(image_path: Path, prompt: str, model_config: dict[str, Any]) -> dict[str, Any]:
        raw_response = provider._call_openai_compatible_endpoint(
            image_path,
            prompt,
            max_tokens=64,
            temperature=0.0,
        )
        return {
            "raw_text": provider._extract_message_text(raw_response),
            "raw_response": raw_response,
        }

    return caller


def _grounding_prompt(request: dict[str, Any]) -> str:
    target = request.get("target") if isinstance(request.get("target"), dict) else {}
    candidate_bbox_in_roi = target.get("candidate_bbox_in_roi") if isinstance(target.get("candidate_bbox_in_roi"), dict) else {}
    return (
        "Locate the requested GUI target inside this cropped ROI image.\n"
        f"Target label: {target.get('label')}\n"
        f"Target role: {target.get('role')}\n"
        f"ROI-image candidate bbox in pixels: {candidate_bbox_in_roi}\n"
        "Choose a point inside the ROI-image candidate bbox, preferably near its visible center.\n"
        "Do not return original screenshot coordinates or copy bbox numbers.\n"
        "Return ROI pixel coordinates only, not normalized coordinates. Use coordinate_space=roi_local_point.\n"
        "Return only one coordinate pair as [x,y].\n"
        "Coordinates must refer to the cropped ROI image in pixels, and the pair must be inside the ROI-image candidate bbox."
    )


def _validation_evidence(*, item: dict[str, Any], grounding: dict[str, Any]) -> dict[str, Any]:
    evidence = grounding.get("evidence") if isinstance(grounding.get("evidence"), dict) else {}
    return {
        "coordinate_transform_replay": bool(evidence.get("coordinate_transform_replay")),
        "screenshot_freshness": bool(evidence.get("screenshot_freshness")),
        "ocr_anchor_overlap": evidence.get("ocr_anchor_overlap", True),
        "uia_or_dom_or_parser_overlap": evidence.get("uia_or_dom_or_parser_overlap", _has_non_ocr_source(item)),
    }


def _has_non_ocr_source(item: dict[str, Any]) -> bool:
    sources = item.get("source_evidence") if isinstance(item, dict) else []
    if not isinstance(sources, list):
        return False
    return any(str(source).casefold() in {"uia", "dom", "omniparser", "calibrated_target"} for source in sources)


def _find_case(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    cases = manifest.get("cases") if isinstance(manifest, dict) else []
    for case in cases if isinstance(cases, list) else []:
        if isinstance(case, dict) and str(case.get("case_id") or "") == case_id:
            return case
    raise ValueError(f"case_id not found: {case_id}")


def _observe_bundle_for_case(case: dict[str, Any], manifest_dir: Path) -> dict[str, Any] | None:
    inline = case.get("observe_bundle")
    if isinstance(inline, dict):
        return inline
    path_value = case.get("recorded_parser_output_path")
    if not path_value:
        return None
    payload_path = Path(path_value)
    if not payload_path.is_absolute():
        manifest_relative = manifest_dir / payload_path
        payload_path = manifest_relative if manifest_relative.exists() else PROJECT_ROOT / payload_path
    payload = _read_json(payload_path)
    observe_bundle = payload.get("observe_bundle") if isinstance(payload, dict) else None
    if isinstance(observe_bundle, dict):
        return observe_bundle
    if isinstance(payload.get("sources"), dict):
        return payload
    return None


def _find_accepted_item(classification: dict[str, Any], label: str) -> dict[str, Any] | None:
    target = label.casefold()
    items = classification.get("accepted_for_grounding")
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and str(item.get("label") or "").casefold() == target:
            return item
    return None


def _write_roi_image(screenshot_path: Path, roi_crop: dict[str, Any], target_path: Path) -> None:
    transform = roi_crop.get("coordinate_transform") if isinstance(roi_crop.get("coordinate_transform"), dict) else {}
    roi_bbox = transform.get("roi_bbox") if isinstance(transform.get("roi_bbox"), dict) else {}
    crop_size = roi_crop.get("crop_size") if isinstance(roi_crop.get("crop_size"), dict) else {}
    x = _int_or_zero(roi_bbox.get("x"))
    y = _int_or_zero(roi_bbox.get("y"))
    w = max(1, _int_or_zero(roi_bbox.get("w")))
    h = max(1, _int_or_zero(roi_bbox.get("h")))
    target_w = max(1, _int_or_zero(crop_size.get("width")))
    target_h = max(1, _int_or_zero(crop_size.get("height")))
    with Image.open(screenshot_path) as image:
        crop = image.crop((x, y, x + w, y + h))
        if crop.width != target_w or crop.height != target_h:
            crop = crop.resize((target_w, target_h), Image.Resampling.LANCZOS)
        crop.save(target_path)


def _image_size(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height}


def _crop_size_for_item(item: dict[str, Any]) -> dict[str, int]:
    bbox = item.get("bbox") if isinstance(item, dict) else {}
    bbox = bbox if isinstance(bbox, dict) else {}
    return bounded_roi_crop_size_for_bbox(bbox)


def _apply_roi_bbox_override(
    roi_crop: dict[str, Any],
    *,
    source_image_size: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(override, dict):
        return roi_crop
    source_w = max(1, _int_or_zero(source_image_size.get("width")))
    source_h = max(1, _int_or_zero(source_image_size.get("height")))
    x = max(0, min(_int_or_zero(override.get("x")), source_w - 1))
    y = max(0, min(_int_or_zero(override.get("y")), source_h - 1))
    w = max(1, min(_int_or_zero(override.get("w")), source_w - x))
    h = max(1, min(_int_or_zero(override.get("h")), source_h - y))
    crop_w = max(1, _int_or_zero(override.get("crop_width") or w))
    crop_h = max(1, _int_or_zero(override.get("crop_height") or h))
    updated = dict(roi_crop)
    updated["crop_size"] = {"width": crop_w, "height": crop_h}
    transform = dict(updated.get("coordinate_transform") if isinstance(updated.get("coordinate_transform"), dict) else {})
    transform["roi_bbox"] = {"x": x, "y": y, "w": w, "h": h}
    transform["crop_size"] = {"width": crop_w, "height": crop_h}
    transform["scale_x"] = round(crop_w / w, 6)
    transform["scale_y"] = round(crop_h / h, 6)
    transform["override_source"] = "benchmark_case_roi_bbox_override"
    updated["coordinate_transform"] = transform
    updated["roi_bbox_override"] = {"x": x, "y": y, "w": w, "h": h, "crop_width": crop_w, "crop_height": crop_h}
    return updated


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_model_profile(profile_id: str | None) -> dict[str, Any]:
    profile_key = str(profile_id or "").strip()
    if not profile_key:
        return {}
    profile_path = Path(profile_key)
    if not profile_path.is_absolute():
        if profile_path.suffix.lower() != ".json":
            profile_path = PROJECT_ROOT / "configs" / "model_profiles" / f"{profile_key}.json"
        else:
            profile_path = PROJECT_ROOT / profile_path
    if not profile_path.exists():
        raise FileNotFoundError(f"model profile not found: {profile_key}")
    profile = _read_json(profile_path)
    if str(profile.get("mode_scope") or "") != "learn_only":
        raise ValueError(f"model profile must be learn_only: {profile_key}")
    if profile.get("execute_binding_enabled") is not False:
        raise ValueError(f"model profile must keep execute_binding_enabled=false: {profile_key}")
    return profile


def _model_profile_summary(profile: dict[str, Any], requested_profile_id: str | None) -> dict[str, Any]:
    if not profile and not str(requested_profile_id or "").strip():
        return {}
    profile_id = str(profile.get("profile_id") or requested_profile_id or "").strip()
    return {
        "profile_id": profile_id,
        "model_id": str(profile.get("model_id") or "").strip(),
        "model_family": str(profile.get("model_family") or "").strip(),
        "mode_scope": str(profile.get("mode_scope") or "").strip(),
        "max_parameters_b": profile.get("max_parameters_b"),
        "download_status": str(profile.get("download_status") or "").strip(),
        "launchable": bool(profile.get("launchable")),
        "endpoint": str(profile.get("endpoint") or "").strip(),
        "model_path": str(profile.get("model_path") or "").strip(),
        "artifact_is_authorization": bool(profile.get("artifact_is_authorization")),
        "execute_binding_enabled": bool(profile.get("execute_binding_enabled")),
    }


def _model_profile_readiness_blocker(
    *,
    profile: dict[str, Any],
    profile_summary: dict[str, Any],
    endpoint: str | None,
) -> dict[str, Any] | None:
    if not profile:
        return None
    readiness = {
        "contract_version": "learn_actual_grounding_model_profile_readiness_v1",
        "profile_id": profile_summary.get("profile_id"),
        "model_id": profile_summary.get("model_id"),
        "model_family": profile_summary.get("model_family"),
        "download_status": profile_summary.get("download_status"),
        "launchable": profile_summary.get("launchable") is True,
        "endpoint_present": bool(str(endpoint or "").strip()),
        "model_path": profile_summary.get("model_path") or "",
        "interpretation": "profile readiness preflight only; blocked profiles do not enter actual_model_call denominator",
    }
    download_status = str(readiness["download_status"] or "").casefold()
    not_downloaded_statuses = {"", "not_downloaded", "metadata_only", "planned", "todo"}
    if download_status in not_downloaded_statuses:
        return {
            **readiness,
            "failure_category": "model_profile_not_downloaded",
            "message": f"model profile {readiness['profile_id']} is not downloaded or only metadata is available",
        }
    if readiness["launchable"] is not True:
        return {
            **readiness,
            "failure_category": "model_profile_not_launchable",
            "message": f"model profile {readiness['profile_id']} is not marked launchable",
        }
    if readiness["endpoint_present"] is not True:
        return {
            **readiness,
            "failure_category": "model_profile_endpoint_missing",
            "message": f"model profile {readiness['profile_id']} has no endpoint for actual grounding",
        }
    return None


def _parse_first_numeric_pair(text: str) -> list[float]:
    import re

    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(matches) < 2:
        raise ValueError(f"no numeric point in model output: {text[:200]}")
    return [float(matches[0]), float(matches[1])]


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value)).strip("_") or "item"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--label")
    parser.add_argument("--screenshot")
    parser.add_argument("--cases-json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-profile", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.cases_json:
        payload = _read_json(Path(args.cases_json))
        cases = payload.get("cases") if isinstance(payload, dict) else payload
        if not isinstance(cases, list):
            raise ValueError("--cases-json must contain a list or an object with cases")
        run_actual_grounding_smoke_batch(
            manifest_path=args.manifest,
            cases=cases,
            out_dir=args.out,
            endpoint=args.endpoint,
            model_name=args.model,
            model_profile_id=args.model_profile,
            timeout_seconds=args.timeout_seconds,
            json_stdout=args.json,
        )
    else:
        if not args.case_id or not args.label or not args.screenshot:
            raise ValueError("--case-id, --label, and --screenshot are required unless --cases-json is provided")
        run_actual_grounding_smoke(
            manifest_path=args.manifest,
            case_id=args.case_id,
            label=args.label,
            screenshot_path=args.screenshot,
            out_dir=args.out,
            endpoint=args.endpoint,
            model_name=args.model,
            model_profile_id=args.model_profile,
            timeout_seconds=args.timeout_seconds,
            json_stdout=args.json,
        )


if __name__ == "__main__":
    main()
