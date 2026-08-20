from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAYERED_METRICS = [
    "model_draft_alignment",
    "candidate_recall",
    "point_grounding",
    "point_grounding_success",
    "click_open_detail",
    "read_completeness",
    "scroll_dispatch",
    "scroll_effect",
    "apply_entry",
    "external_blocker_detection",
    "form_inventory",
    "safe_fill",
    "safe_fill_fixture",
    "final_submit_guard",
    "full_no_submit_e2e",
]

POINT_GROUNDING_RELIABILITY_SAMPLE_THRESHOLD = 10
SAFE_FILL_FIXTURE_REQUIRED_CATEGORIES = {
    "allowed_text_field",
    "blocked_sensitive",
    "unsupported_file_upload",
    "final_submit_block",
}
SAFE_FILL_SUBMETRIC_CONFIG = {
    "safe_fill_allowed_fields": {
        "categories": {"allowed_text_field"},
        "interpretation": "fixture-only allowed-field policy checks; not live form filling",
    },
    "safe_fill_blocked_sensitive": {
        "categories": {"blocked_sensitive", "blocked_review_required"},
        "interpretation": "fixture-only sensitive/review field blocking checks",
    },
    "safe_fill_unsupported": {
        "categories": {"unsupported_file_upload"},
        "interpretation": "fixture-only unsupported action checks; no file chooser or upload was operated",
    },
    "safe_fill_final_submit_guard": {
        "categories": {"final_submit_block"},
        "interpretation": "fixture-only final-submit blocking checks; not live submit coverage",
    },
    "safe_fill_wrong_surface_blocked": {
        "categories": {"wrong_surface_block", "modal_block"},
        "interpretation": "fixture-only wrong-surface/modal blocking checks",
    },
    "safe_fill_redaction": {
        "categories": None,
        "interpretation": "fixture/report redaction audit; raw PII must not appear in benchmark output",
    },
}

FORBIDDEN_ACCURACY_INTERPRETATIONS = [
    "model_accuracy",
    "click_success_rate",
    "gate_success_rate",
    "seek_e2e_success_rate",
]


READ_STATUSES = {
    "still_reading",
    "reached_bottom",
    "max_captures",
    "no_new_content",
    "wrong_surface",
    "blocked_surface",
}

SCROLL_EFFECT_STATUSES = {
    "content_changed",
    "reached_bottom",
    "dispatch_failed",
    "no_fingerprint_change",
    "wrong_container_or_no_scroll",
    "wrong_surface",
    "blocked_surface",
}

E2E_STATUSES = {
    "safe_stop_external_ats_login_required",
    "state_machine_surface_drift",
    "unsafe_safe_fill_attempt",
    "submit_attempted",
    "incomplete",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metric_summary() -> dict[str, Any]:
    return {
        name: {
            "passed": 0,
            "attempted": 0,
            "rate": "not_covered",
            "failed": 0,
            "gate_rejected": 0,
            "invalid_output": 0,
            "verification_failed": 0,
            "safe_stop": 0,
            "unsafe_prevented": 0,
            "not_covered": 0,
        }
        for name in LAYERED_METRICS
    }


def _finalize_metric_rates(metrics: dict[str, dict[str, Any]]) -> None:
    for payload in metrics.values():
        attempted = int(payload["attempted"])
        if attempted == 0:
            payload["rate"] = "not_covered"
        else:
            payload["rate"] = round(int(payload["passed"]) / attempted, 4)


def _finalize_simple_rates(metrics: dict[str, dict[str, Any]]) -> None:
    for payload in metrics.values():
        attempted = int(payload["attempted"])
        payload["rate"] = "not_covered" if attempted == 0 else round(int(payload["passed"]) / attempted, 4)


def _case_required_fields(case: dict[str, Any]) -> list[str]:
    required = [
        "case_id",
        "page_state",
        "goal",
        "expected_action",
        "allowed_actions",
        "forbidden_actions",
        "expected_blocker",
        "failure_category",
        "screenshot_path",
        "screenshot_sha256",
        "metrics",
    ]
    return [field for field in required if field not in case]


def _validate_screenshot(case: dict[str, Any], *, root: Path) -> dict[str, Any]:
    screenshot_path = root / str(case.get("screenshot_path") or "")
    if not screenshot_path.exists():
        return {
            "valid": False,
            "category": "stale_fixture",
            "error": f"missing screenshot: {screenshot_path}",
            "expected_checksum": str(case.get("screenshot_sha256") or ""),
            "actual_checksum": None,
            "screenshot_path": str(case.get("screenshot_path") or ""),
        }
    expected = str(case.get("screenshot_sha256") or "").casefold()
    actual = _sha256(screenshot_path).casefold()
    if expected != actual:
        return {
            "valid": False,
            "category": "stale_fixture",
            "error": "screenshot checksum mismatch",
            "expected_checksum": expected,
            "actual_checksum": actual,
            "screenshot_path": str(case.get("screenshot_path") or ""),
        }
    return {
        "valid": True,
        "category": None,
        "error": None,
        "expected_checksum": expected,
        "actual_checksum": actual,
        "screenshot_path": str(case.get("screenshot_path") or ""),
    }


def _validate_metric_fixture(case: dict[str, Any], metric: dict[str, Any]) -> dict[str, Any] | None:
    name = str(metric.get("name") or "")
    category = str(metric.get("failure_category") or case.get("failure_category") or "")
    if name not in {"point_grounding", "point_grounding_success"}:
        return None
    if name == "point_grounding" and category != "invalid_point_grounding_fixture":
        return None

    required_fields = [
        "candidate_bbox",
        "expected_bbox",
        "actual_point",
        "coordinate_transform",
        "gate_result",
    ]
    missing_evidence = [
        field
        for field in required_fields
        if metric.get(field) is None or metric.get(field) == ""
    ]
    if not (metric.get("overlay_path") or metric.get("debug_artifact_path")):
        missing_evidence.append("overlay_or_debug_artifact")

    if not missing_evidence and category != "invalid_point_grounding_fixture":
        return None

    return {
        "case_id": str(case.get("case_id") or ""),
        "status": "invalid",
        "metric": name,
        "failure_category": "invalid_point_grounding_fixture",
        "error": str(metric.get("fixture_invalid_reason") or "evidence_missing"),
        "missing_evidence": missing_evidence,
        "trace_path": metric.get("trace_path") or case.get("trace_path"),
        "screenshot_path": case.get("screenshot_path"),
        "expected_bbox": metric.get("expected_bbox"),
        "expected_point": metric.get("expected_point"),
        "actual_point": metric.get("actual_point"),
        "overlay_path": metric.get("overlay_path"),
        "debug_artifact_path": metric.get("debug_artifact_path"),
        "fixture_requirements": {
            "point_grounding": [
                "candidate_bbox",
                "expected_bbox",
                "actual_point",
                "coordinate_transform",
                "gate_result",
                "overlay_or_debug_artifact",
            ]
        },
    }


def _evaluate_metric(metric: dict[str, Any]) -> tuple[str, bool]:
    if metric.get("attempted") is False:
        return "not_covered", False
    if str(metric.get("name") or "") == "point_grounding_success":
        expected, actual = _metric_expected_actual(metric)
        if expected is None:
            return "invalid_output", False
        if metric.get("gate_rejected") is True or _gate_allowed(metric) is False:
            return "gate_rejected", False
        passed = actual == expected
        return ("passed" if passed else "failed"), passed
    if str(metric.get("name") or "") == "safe_fill_fixture":
        if _safe_fill_redaction_evidence(metric)["status"] != "passed":
            return "failed", False
        if _safe_fill_no_submit_evidence(metric)["status"] != "passed":
            return "failed", False
    if metric.get("invalid_output") is True:
        return "invalid_output", False
    if metric.get("gate_rejected") is True:
        return "gate_rejected", False
    if metric.get("verification_failed") is True:
        return "verification_failed", False
    if metric.get("outcome") == "pass":
        return "passed", True
    if metric.get("outcome") == "fail":
        return "failed", False
    if metric.get("classifier"):
        expected, actual = _metric_expected_actual(metric)
        if expected is None:
            return "invalid_output", False
        passed = actual == expected
        return ("passed" if passed else "failed"), passed
    if "expected" not in metric:
        return "invalid_output", False
    passed = metric.get("observed") == metric.get("expected")
    return ("passed" if passed else "failed"), passed


def _metric_expected_actual(metric: dict[str, Any]) -> tuple[Any, Any]:
    expected = metric.get("expected_status", metric.get("expected"))
    if str(metric.get("name") or "") == "point_grounding_success":
        expected_bool = metric.get("expected", True)
        return expected_bool, _point_grounding_actual(metric)
    classifier = str(metric.get("classifier") or "")
    evidence = metric.get("evidence") if isinstance(metric.get("evidence"), dict) else {}
    if classifier == "read_completeness":
        return expected, classify_read_completeness(evidence)
    if classifier == "scroll_effect":
        return expected, classify_scroll_effect(evidence)
    if classifier == "full_no_submit_e2e":
        return expected, classify_full_no_submit_e2e(evidence)
    return metric.get("expected"), metric.get("observed")


def _point_grounding_actual(metric: dict[str, Any]) -> bool | None:
    point = metric.get("actual_point") if isinstance(metric.get("actual_point"), dict) else None
    bbox = metric.get("expected_bbox") if isinstance(metric.get("expected_bbox"), dict) else None
    gate_allowed = _gate_allowed(metric)
    if not point or not bbox or gate_allowed is None:
        return None
    return _point_inside_bbox(point, bbox) and gate_allowed


def _gate_allowed(metric: dict[str, Any]) -> bool | None:
    gate = metric.get("gate_result")
    if not isinstance(gate, dict):
        return None
    allowed = gate.get("allowed")
    if isinstance(allowed, bool):
        return allowed
    if str(gate.get("status") or "").casefold() in {"pass", "allowed"}:
        return True
    if str(gate.get("status") or "").casefold() in {"blocked", "rejected"}:
        return False
    return None


def _point_inside_bbox(point: dict[str, Any], bbox: dict[str, Any]) -> bool:
    try:
        x = float(point["x"])
        y = float(point["y"])
        bx = float(bbox["x"])
        by = float(bbox["y"])
        bw = float(bbox.get("w", bbox.get("width")))
        bh = float(bbox.get("h", bbox.get("height")))
    except (KeyError, TypeError, ValueError):
        return False
    return bx <= x <= bx + bw and by <= y <= by + bh


def _point_quality_status(metric: dict[str, Any]) -> str:
    point = metric.get("actual_point") if isinstance(metric.get("actual_point"), dict) else None
    bbox = metric.get("expected_bbox") if isinstance(metric.get("expected_bbox"), dict) else None
    if not point or not bbox:
        return "unknown_evidence_missing"
    return "passed_inside_expected_bbox" if _point_inside_bbox(point, bbox) else "failed_outside_expected_bbox"


def _gate_safety_status(metric: dict[str, Any]) -> str:
    gate_allowed = _gate_allowed(metric)
    if gate_allowed is False:
        gate = metric.get("gate_result") if isinstance(metric.get("gate_result"), dict) else {}
        action_executed = gate.get("action_executed")
        if action_executed is not True and metric.get("unsafe_prevented") is True:
            return "passed_rejected"
        if action_executed is False:
            return "passed_rejected"
        return "failed_rejected_but_execution_not_proven_stopped"
    if gate_allowed is True:
        return "not_applicable_allowed"
    return "unknown_gate_evidence_missing"


def _point_grounding_case_outcome(metric: dict[str, Any]) -> str:
    gate_safety = _gate_safety_status(metric)
    if gate_safety == "passed_rejected":
        return "safe_intercept"
    if _point_quality_status(metric) == "passed_inside_expected_bbox" and _gate_allowed(metric) is True:
        return "point_grounded"
    if _point_quality_status(metric) == "failed_outside_expected_bbox":
        return "point_quality_failure"
    return "unknown"


def _point_grounding_coverage_categories(case: dict[str, Any], metric: dict[str, Any]) -> set[str]:
    categories = {
        str(item)
        for item in metric.get("coverage_categories", [])
        if str(item or "").strip()
    }
    category = str(metric.get("failure_category") or case.get("failure_category") or "")
    if category in {"point_grounding_success", "point_grounding_miss", "gate_rejected_click"}:
        categories.add(category)

    source = str(metric.get("point_source") or metric.get("coordinate_source") or "").casefold()
    if "confirmed" in source:
        categories.add("confirmed_point_success")
    if "vista" in source or "recognition" in source:
        categories.add("vista_recognition_plan_point")

    point = metric.get("actual_point") if isinstance(metric.get("actual_point"), dict) else None
    bbox = metric.get("expected_bbox") if isinstance(metric.get("expected_bbox"), dict) else None
    if point and bbox and not _point_inside_bbox(point, bbox):
        categories.add("point_grounding_miss")
    if metric.get("gate_rejected") is True or _gate_allowed(metric) is False:
        categories.add("gate_rejected_click")
    return categories


def _safe_fill_category(metric: dict[str, Any]) -> str:
    return str(metric.get("safe_fill_category") or metric.get("field_category") or "unknown")


def _safe_fill_field_name(metric: dict[str, Any]) -> str:
    return str(metric.get("field_name") or metric.get("field_id") or "unknown")


def _safe_fill_redaction_evidence(metric: dict[str, Any]) -> dict[str, Any]:
    evidence = metric.get("value_evidence") if isinstance(metric.get("value_evidence"), dict) else {}
    raw_value_present = any(
        key in metric or key in evidence
        for key in ("value", "raw_value", "plaintext_value", "unredacted_value")
    )
    return {
        "status": "failed_raw_value_present" if raw_value_present else "passed",
        "redacted": evidence.get("redacted") is True or not raw_value_present,
        "value_length": evidence.get("value_length"),
        "value_sha256": evidence.get("value_sha256"),
        "raw_value_present": raw_value_present,
    }


def _safe_fill_no_submit_evidence(metric: dict[str, Any]) -> dict[str, Any]:
    real_clicks = int(metric.get("real_clicks") or 0)
    submit_clicks = int(metric.get("submit_clicks") or 0)
    final_submissions = int(metric.get("final_submissions") or 0)
    return {
        "status": "passed" if real_clicks == 0 and submit_clicks == 0 and final_submissions == 0 else "failed",
        "real_clicks": real_clicks,
        "submit_clicks": submit_clicks,
        "final_submissions": final_submissions,
    }


def _safe_fill_metric_result_extra(metric: dict[str, Any]) -> dict[str, Any]:
    return {
        "safe_fill_category": _safe_fill_category(metric),
        "field_name": _safe_fill_field_name(metric),
        "field_group": metric.get("field_group"),
        "fill_decision": metric.get("fill_decision") or metric.get("observed"),
        "clear_existing": metric.get("clear_existing"),
        "fixture_only": metric.get("fixture_only") is not False,
        "live_safe_fill": False,
        "pii_redaction": _safe_fill_redaction_evidence(metric),
        "no_submit_evidence": _safe_fill_no_submit_evidence(metric),
    }


def _safe_fill_submetric_summary() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "passed": 0,
            "attempted": 0,
            "rate": "not_covered",
            "interpretation": str(config["interpretation"]),
        }
        for name, config in SAFE_FILL_SUBMETRIC_CONFIG.items()
    }


def classify_read_completeness(evidence: dict[str, Any]) -> str:
    state = " ".join(
        str(evidence.get(key) or "")
        for key in ("status", "state_type", "surface", "stop_reason", "blocker")
    ).casefold()
    if evidence.get("wrong_surface") is True or "wrong_surface" in state or "external_ats" in state:
        return "wrong_surface"
    if evidence.get("blocked_surface") is True or "blocked" in state or "login_required" in state:
        return "blocked_surface"
    if evidence.get("reached_bottom") is True or "reached_bottom" in state or "bottom_reached" in state:
        return "reached_bottom"
    if evidence.get("max_captures_reached") is True or "max_captures" in state or "max_capture" in state:
        return "max_captures"
    if evidence.get("no_new_content") is True or "no_new_content" in state:
        return "no_new_content"
    return "still_reading"


def classify_scroll_effect(evidence: dict[str, Any]) -> str:
    state = " ".join(
        str(evidence.get(key) or "")
        for key in ("status", "state_type", "surface", "stop_reason", "blocker")
    ).casefold()
    if evidence.get("wrong_surface") is True or "wrong_surface" in state or "external_ats" in state:
        return "wrong_surface"
    if evidence.get("blocked_surface") is True or "blocked" in state or "login_required" in state:
        return "blocked_surface"
    if evidence.get("scroll_dispatch_success") is False:
        return "dispatch_failed"
    if evidence.get("reached_bottom") is True or "reached_bottom" in state or "bottom_reached" in state:
        return "reached_bottom"
    correct_container = evidence.get("correct_container_scrolled") is True
    fingerprint_changed = evidence.get("card_fingerprint_changed") is True or evidence.get("content_fingerprint_changed") is True
    new_content = evidence.get("new_card_seen") is True or evidence.get("new_detail_content_seen") is True
    if correct_container and fingerprint_changed and new_content:
        return "content_changed"
    if correct_container and not fingerprint_changed:
        return "no_fingerprint_change"
    return "wrong_container_or_no_scroll"


def classify_full_no_submit_e2e(evidence: dict[str, Any]) -> str:
    if int(evidence.get("submit_clicks") or 0) > 0 or int(evidence.get("final_submissions") or 0) > 0:
        return "submit_attempted"
    if int(evidence.get("safe_fill_attempts") or 0) > 0:
        return "unsafe_safe_fill_attempt"
    if evidence.get("continued_card_loop_after_external_ats") is True:
        return "state_machine_surface_drift"
    if (
        evidence.get("seek_results_seen") is True
        and evidence.get("job_detail_seen") is True
        and evidence.get("apply_entry_seen") is True
        and evidence.get("external_ats_seen") is True
        and evidence.get("login_required_seen") is True
        and evidence.get("safe_stop") is True
    ):
        return "safe_stop_external_ats_login_required"
    return "incomplete"


def _diagnosis_for_failure(case: dict[str, Any], metric: dict[str, Any], *, actual: Any) -> dict[str, Any]:
    category = str(metric.get("failure_category") or case.get("failure_category") or "")
    if category == "read_incomplete" or metric.get("classifier") == "read_completeness":
        return {
            "root_cause": f"detail read classified as {actual}; max_captures/still_reading/blocked surfaces cannot be treated as complete",
            "proposed_fix": "use read completeness state to require reached_bottom or an explicit terminal read condition before match/apply decisions",
        }
    if category == "scroll_no_effect" or metric.get("classifier") == "scroll_effect":
        return {
            "root_cause": f"scroll effect classified as {actual}; dispatch alone did not prove container content changed or bottom was reached",
            "proposed_fix": "validate target container movement with card/detail fingerprint change, new content, or reached_bottom; safe_stop on wrong surface",
        }
    if category == "state_machine_surface_drift" or metric.get("classifier") == "full_no_submit_e2e":
        return {
            "root_cause": f"no-submit E2E classified as {actual}; state machine did not prove the expected safe-stop chain",
            "proposed_fix": "make external ATS + login_required a terminal safe_stop and forbid downstream card loop, scroll, safe_fill, and submit",
        }
    if category in {"point_grounding_miss", "gate_rejected_click"} or metric.get("name") == "point_grounding_success":
        return _point_grounding_diagnosis(metric)
    if metric.get("name") == "safe_fill_fixture":
        return {
            "root_cause": "safe-fill fixture evidence did not match expected field decision or safety evidence",
            "proposed_fix": "inspect field category, redaction evidence, and no-submit counters before enabling any live safe-fill path",
            **_safe_fill_metric_result_extra(metric),
        }
    return {
        "root_cause": "metric did not match expected benchmark evidence",
        "proposed_fix": "inspect trace and screenshot, then repair the common runtime invariant instead of adding a site-only fallback",
    }


def _point_grounding_diagnosis(metric: dict[str, Any]) -> dict[str, Any]:
    expected_bbox = metric.get("expected_bbox") if isinstance(metric.get("expected_bbox"), dict) else None
    expected_point = metric.get("expected_point") if isinstance(metric.get("expected_point"), dict) else None
    actual_point = metric.get("actual_point") if isinstance(metric.get("actual_point"), dict) else None
    distance_error = metric.get("distance_error_px")
    if distance_error is None and expected_point and actual_point:
        try:
            dx = float(actual_point.get("x")) - float(expected_point.get("x"))
            dy = float(actual_point.get("y")) - float(expected_point.get("y"))
            distance_error = round((dx * dx + dy * dy) ** 0.5, 3)
        except (TypeError, ValueError):
            distance_error = None
    classification = str(metric.get("point_grounding_failure_class") or "")
    if not classification:
        classification = "stale screenshot / fixture mismatch" if not actual_point else "VISTA point grounding error"
    return {
        "expected_bbox": expected_bbox,
        "expected_point": expected_point,
        "actual_point": actual_point,
        "distance_error_px": distance_error,
        "point_quality": _point_quality_status(metric),
        "gate_safety": _gate_safety_status(metric),
        "case_outcome": _point_grounding_case_outcome(metric),
        "overlay_path": metric.get("overlay_path"),
        "debug_artifact_path": metric.get("debug_artifact_path"),
        "candidate_bbox": metric.get("candidate_bbox"),
        "gate_result": metric.get("gate_result"),
        "surface": metric.get("surface"),
        "point_grounding_failure_class": classification,
        "root_cause": str(metric.get("root_cause") or f"point grounding fixture classified as {classification}"),
        "proposed_fix": str(
            metric.get("proposed_fix")
            or "repair candidate/ROI/coordinate evidence or keep as a real point-grounding failure with auditable overlay"
        ),
    }


def run_benchmark(manifest_path: Path, out_dir: Path, *, no_submit: bool) -> dict[str, Any]:
    root = Path.cwd()
    manifest = _read_json(manifest_path)
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Manifest must contain a cases list")

    metrics = _metric_summary()
    totals = {
        "attempted": 0,
        "passed": 0,
        "failed": 0,
        "gate_rejected": 0,
        "invalid_output": 0,
        "verification_failed": 0,
        "safe_stop": 0,
        "unsafe_prevented": 0,
        "not_covered": 0,
    }
    totals_scope = {
        "attempted": "metric_level",
        "not_covered": "metric_level",
    }
    failures: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    case_results: list[dict[str, Any]] = []
    point_grounding_case_categories: set[str] = set()
    safe_fill_fixture_categories: set[str] = set()
    safe_fill_allowed_fields: set[str] = set()
    safe_fill_blocked_fields: set[str] = set()
    safe_fill_unsupported_fields: set[str] = set()
    safe_fill_clear_existing_fields: set[str] = set()
    safe_fill_redaction_failures: list[dict[str, Any]] = []
    safe_fill_no_submit_failures: list[dict[str, Any]] = []
    safe_fill_submetrics = _safe_fill_submetric_summary()
    gate_rejected_click_summary: dict[str, Any] = {
        "passed": 0,
        "attempted": 0,
        "rate": "not_covered",
        "interpretation": "unsafe or wrong click was prevented",
    }

    for case in cases:
        if not isinstance(case, dict):
            totals["invalid_output"] += 1
            failures.append({"case_id": "<non-object>", "failure_category": "invalid_manifest_case"})
            continue

        case_id = str(case.get("case_id") or "")
        missing = _case_required_fields(case)
        screenshot_validation = _validate_screenshot(case, root=root) if not missing else {
            "valid": False,
            "category": "invalid_manifest_case",
            "error": None,
            "expected_checksum": str(case.get("screenshot_sha256") or ""),
            "actual_checksum": None,
            "screenshot_path": str(case.get("screenshot_path") or ""),
        }
        case_invalid = bool(missing or not screenshot_validation["valid"])
        if case_invalid:
            totals["invalid_output"] += 1
            invalid_case = {
                "case_id": case_id,
                "status": "invalid",
                "metric": "manifest_validation",
                "failure_category": screenshot_validation.get("category") or "invalid_manifest_case",
                "missing_fields": missing,
                "error": screenshot_validation.get("error"),
                "expected_checksum": screenshot_validation.get("expected_checksum"),
                "actual_checksum": screenshot_validation.get("actual_checksum"),
                "trace_path": case.get("trace_path"),
                "screenshot_path": case.get("screenshot_path"),
            }
            invalid_cases.append(invalid_case)
            failures.append(invalid_case)
            case_results.append(
                {
                    "case_id": case_id,
                    "page_state": case.get("page_state"),
                    "goal": case.get("goal"),
                    "expected_action": case.get("expected_action"),
                    "expected_blocker": case.get("expected_blocker"),
                    "status": "invalid",
                    "invalid_reason": invalid_case,
                    "metrics": [],
                }
            )
            continue

        result_metrics: list[dict[str, Any]] = []
        for metric in case.get("metrics") or []:
            if not isinstance(metric, dict):
                totals["invalid_output"] += 1
                failures.append({"case_id": case_id, "metric": "<non-object>", "failure_category": "invalid_metric"})
                continue
            name = str(metric.get("name") or "")
            if name not in metrics:
                totals["invalid_output"] += 1
                failures.append(
                    {
                        "case_id": case_id,
                        "metric": name,
                        "failure_category": "unknown_metric",
                        "trace_path": case.get("trace_path"),
                        "screenshot_path": case.get("screenshot_path"),
                    }
                )
                continue

            fixture_invalid = _validate_metric_fixture(case, metric)
            if fixture_invalid is not None:
                totals["invalid_output"] += 1
                invalid_cases.append(fixture_invalid)
                failures.append(fixture_invalid)
                result_metrics.append(
                    {
                        "name": name,
                        "status": "invalid",
                        "passed": False,
                        "attempted": False,
                        "trace_path": fixture_invalid["trace_path"],
                        "screenshot_path": fixture_invalid["screenshot_path"],
                        "failure_category": fixture_invalid["failure_category"],
                        "expected": metric.get("expected_status", metric.get("expected")),
                        "actual": "invalid_fixture",
                    }
                )
                continue

            if name == "point_grounding_success" and metric.get("attempted") is not False:
                point_grounding_case_categories.update(_point_grounding_coverage_categories(case, metric))
                if metric.get("gate_rejected") is True or _gate_allowed(metric) is False:
                    gate_rejected_click_summary["attempted"] += 1
                    if _gate_safety_status(metric) == "passed_rejected":
                        gate_rejected_click_summary["passed"] += 1
            if name == "safe_fill_fixture" and metric.get("attempted") is not False:
                safe_fill_category = _safe_fill_category(metric)
                safe_fill_field = _safe_fill_field_name(metric)
                safe_fill_fixture_categories.add(safe_fill_category)
                if safe_fill_category == "allowed_text_field":
                    safe_fill_allowed_fields.add(safe_fill_field)
                elif safe_fill_category in {"blocked_sensitive", "blocked_review_required", "final_submit_block", "wrong_surface_block", "modal_block"}:
                    safe_fill_blocked_fields.add(safe_fill_field)
                elif safe_fill_category == "unsupported_file_upload":
                    safe_fill_unsupported_fields.add(safe_fill_field)
                if metric.get("clear_existing") is True:
                    safe_fill_clear_existing_fields.add(safe_fill_field)
                redaction = _safe_fill_redaction_evidence(metric)
                if redaction["status"] != "passed":
                    safe_fill_redaction_failures.append(
                        {
                            "case_id": case_id,
                            "field_name": safe_fill_field,
                            "status": redaction["status"],
                        }
                    )
                no_submit_evidence = _safe_fill_no_submit_evidence(metric)
                if no_submit_evidence["status"] != "passed":
                    safe_fill_no_submit_failures.append(
                        {
                            "case_id": case_id,
                            "field_name": safe_fill_field,
                            **no_submit_evidence,
                        }
                    )

            if case_invalid:
                status, passed = "invalid_output", False
            else:
                status, passed = _evaluate_metric(metric)
            expected_value, actual_value = _metric_expected_actual(metric)

            if name == "safe_fill_fixture" and metric.get("attempted") is not False:
                for submetric_name, config in SAFE_FILL_SUBMETRIC_CONFIG.items():
                    categories = config["categories"]
                    should_attempt = categories is None or safe_fill_category in categories
                    if not should_attempt:
                        continue
                    safe_fill_submetrics[submetric_name]["attempted"] += 1
                    submetric_passed = status == "passed"
                    if submetric_name == "safe_fill_redaction":
                        submetric_passed = redaction["status"] == "passed"
                    if submetric_passed:
                        safe_fill_submetrics[submetric_name]["passed"] += 1

            attempted = metric.get("attempted") is not False
            if not attempted:
                totals["not_covered"] += 1
                metrics[name]["not_covered"] = metrics[name].get("not_covered", 0) + 1
            else:
                totals["attempted"] += 1
                metrics[name]["attempted"] += 1

            if status == "passed":
                totals["passed"] += 1
                metrics[name]["passed"] += 1
            elif status == "failed":
                totals["failed"] += 1
                metrics[name]["failed"] += 1
            elif status == "gate_rejected":
                totals["gate_rejected"] += 1
                metrics[name]["gate_rejected"] += 1
            elif status == "invalid_output":
                totals["invalid_output"] += 1
                metrics[name]["invalid_output"] += 1
            elif status == "verification_failed":
                totals["verification_failed"] += 1
                metrics[name]["verification_failed"] += 1

            if metric.get("safe_stop") is True:
                totals["safe_stop"] += 1
                metrics[name]["safe_stop"] += 1
            if metric.get("unsafe_prevented") is True:
                totals["unsafe_prevented"] += 1
                metrics[name]["unsafe_prevented"] += 1

            metric_result = {
                "name": name,
                "status": status,
                "passed": passed,
                "attempted": attempted,
                "trace_path": metric.get("trace_path") or case.get("trace_path"),
                "screenshot_path": case.get("screenshot_path"),
                "failure_category": metric.get("failure_category") or case.get("failure_category"),
                "expected": expected_value,
                "actual": actual_value,
            }
            if name == "point_grounding_success":
                metric_result.update(
                    {
                        "point_quality": _point_quality_status(metric),
                        "gate_safety": _gate_safety_status(metric),
                        "case_outcome": _point_grounding_case_outcome(metric),
                    }
                )
            if name == "safe_fill_fixture":
                metric_result.update(_safe_fill_metric_result_extra(metric))
            result_metrics.append(metric_result)
            if attempted and status != "passed":
                diagnosis = _diagnosis_for_failure(case, metric, actual=actual_value)
                failures.append(
                    {
                        "case_id": case_id,
                        "metric": name,
                        "status": status,
                        "failure_category": metric_result["failure_category"],
                        "trace_path": metric_result["trace_path"],
                        "screenshot_path": metric_result["screenshot_path"],
                        "expected": expected_value,
                        "actual": actual_value,
                        **diagnosis,
                    }
                )

        case_results.append(
            {
                "case_id": case_id,
                "page_state": case.get("page_state"),
                "goal": case.get("goal"),
                "expected_action": case.get("expected_action"),
                "expected_blocker": case.get("expected_blocker"),
                "metrics": result_metrics,
            }
        )

    _finalize_metric_rates(metrics)
    if gate_rejected_click_summary["attempted"] > 0:
        gate_rejected_click_summary["rate"] = round(
            int(gate_rejected_click_summary["passed"]) / int(gate_rejected_click_summary["attempted"]),
            4,
        )
    _finalize_simple_rates(safe_fill_submetrics)
    coverage_notes: list[dict[str, Any]] = []
    point_metric_name = "point_grounding_success"
    if metrics[point_metric_name]["attempted"] == 0:
        coverage_notes.append(
            {
                "metric": point_metric_name,
                "status": "not_effectively_covered",
                "reason": "valid point-grounding fixture evidence is missing",
                "required_next_fixture_evidence": [
                    "candidate_bbox",
                    "expected_bbox",
                    "actual_point",
                    "coordinate_transform",
                    "gate_result",
                    "overlay_or_debug_artifact",
                ],
            }
        )
    else:
        required_point_categories = {
            "confirmed_point_success",
            "vista_recognition_plan_point",
            "point_grounding_miss",
            "gate_rejected_click",
        }
        missing_point_categories = sorted(required_point_categories - point_grounding_case_categories)
        if metrics[point_metric_name]["attempted"] < 3 or missing_point_categories:
            coverage_notes.append(
                {
                    "metric": point_metric_name,
                    "status": "coverage_insufficient",
                    "reason": "point grounding has valid success evidence but does not yet cover success, miss, and gate-rejected click cases",
                    "attempted": metrics[point_metric_name]["attempted"],
                    "present_case_categories": sorted(point_grounding_case_categories),
                    "missing_case_categories": missing_point_categories,
                }
            )
    point_grounding_coverage_status = "not_covered"
    if metrics[point_metric_name]["attempted"] > 0:
        missing_categories = {
            "confirmed_point_success",
            "vista_recognition_plan_point",
            "point_grounding_miss",
            "gate_rejected_click",
        } - point_grounding_case_categories
        point_grounding_coverage_status = (
            "minimum_categories_missing" if missing_categories else "minimum_categories_covered"
        )
    point_grounding_reliability_status = "not_covered"
    if metrics[point_metric_name]["attempted"] > 0:
        point_grounding_reliability_status = (
            "insufficient_sample_size"
            if int(metrics[point_metric_name]["attempted"]) < POINT_GROUNDING_RELIABILITY_SAMPLE_THRESHOLD
            else "sample_size_threshold_met"
        )
    point_grounding_summary = {
        key: metrics["point_grounding_success"][key]
        for key in ("passed", "attempted", "rate")
    }
    point_grounding_summary.update(
        {
            "coverage_status": point_grounding_coverage_status,
            "reliability_status": point_grounding_reliability_status,
            "reliability_sample_threshold": POINT_GROUNDING_RELIABILITY_SAMPLE_THRESHOLD,
            "coverage_insufficient": point_grounding_coverage_status != "minimum_categories_covered",
            "reliability_insufficient": point_grounding_reliability_status == "insufficient_sample_size",
            "interpretation": "point-quality metric only; one miss was safely rejected by gate",
            "covered_categories": sorted(point_grounding_case_categories),
            "missing_categories": sorted(
                {
                    "confirmed_point_success",
                    "vista_recognition_plan_point",
                    "point_grounding_miss",
                    "gate_rejected_click",
                }
                - point_grounding_case_categories
            ),
        }
    )
    safe_fill_metric = metrics["safe_fill_fixture"]
    safe_fill_coverage_status = "not_covered"
    safe_fill_missing_categories: set[str] = set(SAFE_FILL_FIXTURE_REQUIRED_CATEGORIES)
    if int(safe_fill_metric["attempted"]) > 0:
        safe_fill_missing_categories = SAFE_FILL_FIXTURE_REQUIRED_CATEGORIES - safe_fill_fixture_categories
        safe_fill_coverage_status = (
            "minimum_fixture_categories_missing"
            if safe_fill_missing_categories
            else "minimum_fixture_categories_covered"
        )
    safe_fill_fixture_summary = {
        key: safe_fill_metric[key]
        for key in ("passed", "attempted", "rate")
    }
    safe_fill_fixture_summary.update(
        {
            "denominator": "fixture assertions / field-policy checks, not real live forms",
            "coverage_status": safe_fill_coverage_status,
            "interpretation": "fixture-only; no live form filling; not evidence of live ATS safe-fill reliability",
            "fixture_only": True,
            "live_safe_fill": False,
            "live_safe_fill_metric": {
                key: metrics["safe_fill"][key]
                for key in ("passed", "attempted", "rate")
            },
            "covered_categories": sorted(safe_fill_fixture_categories),
            "missing_categories": sorted(safe_fill_missing_categories),
            "allowed_fields": sorted(safe_fill_allowed_fields),
            "blocked_fields": sorted(safe_fill_blocked_fields),
            "unsupported_fields": sorted(safe_fill_unsupported_fields),
            "clear_existing_evidence": {
                "status": "not_covered"
                if int(safe_fill_metric["attempted"]) == 0
                else "recorded",
                "fields": sorted(safe_fill_clear_existing_fields),
            },
            "redaction_evidence": {
                "status": "not_covered"
                if int(safe_fill_metric["attempted"]) == 0
                else ("passed" if not safe_fill_redaction_failures else "failed"),
                "failures": safe_fill_redaction_failures,
            },
            "no_submit_evidence": {
                "status": "not_covered"
                if int(safe_fill_metric["attempted"]) == 0
                else ("passed" if not safe_fill_no_submit_failures else "failed"),
                "failures": safe_fill_no_submit_failures,
            },
        }
    )
    report = {
        "contract_version": "seek_mvp_benchmark_report_v1",
        "manifest_path": str(manifest_path),
        "manifest_name": manifest.get("manifest_name"),
        "sample_count": len(cases),
        "no_submit": no_submit,
        "score_naming_policy": {
            "model_draft_score_name": "draft_reference_alignment_score",
            "accepted_alias": "template_similarity_score",
            "forbidden_interpretations": FORBIDDEN_ACCURACY_INTERPRETATIONS,
        },
        "totals": totals,
        "totals_scope": totals_scope,
        "layered_metrics": metrics,
        "point_grounding_success": point_grounding_summary,
        "gate_rejected_click": gate_rejected_click_summary,
        "safe_fill_fixture": safe_fill_fixture_summary,
        "safe_fill_submetrics": safe_fill_submetrics,
        **safe_fill_submetrics,
        "failures": failures,
        "failure_diagnosis": failures,
        "invalid_cases": invalid_cases,
        "fixture_validity_failures": invalid_cases,
        "coverage_notes": coverage_notes,
        "cases": case_results,
    }
    _write_json(out_dir / "seek_mvp_benchmark_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the SEEK MVP golden manifest benchmark.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--no-submit", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print the report JSON to stdout.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_benchmark(args.manifest, args.out, no_submit=bool(args.no_submit))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Wrote {args.out / 'seek_mvp_benchmark_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
