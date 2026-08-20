from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.model_server import ensure_model_server, stop_model_server
from app.learn.recognition.support_eligibility import (
    finalize_support_eligibility_summary,
    merge_support_eligibility_summary,
    new_support_eligibility_summary,
)
from scripts.run_learn_recognition_actual_parser_smoke import ParserModelCaller, run_actual_parser_smoke


def run_actual_parser_batch(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
    endpoint: str | None,
    model_name: str | None = None,
    model_profile_id: str | None = None,
    timeout_seconds: float = 60.0,
    start_profile: bool = False,
    stop_started_profile: bool = True,
    start_wait_seconds: float = 180.0,
    model_caller: ParserModelCaller | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _read_json(manifest_path)
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("actual parser manifest must contain a cases list")

    case_results: list[dict[str, Any]] = []
    totals = {"cases": 0, "passed": 0, "failed": 0, "blocked": 0, "invalid": 0}
    metrics = {
        "actual_parser_call": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "parse_inventory": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "parser_case_has_grounding_candidate": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "grounding_eligible_item_yield": {"passed": 0, "attempted": 0, "rate": "not_covered"},
    }
    actionability_summary = {
        "total_screen_inventory_count": 0,
        "total_grounding_eligible_count": 0,
        "total_review_only_count": 0,
        "cases_without_grounding_candidates": [],
        "grounding_candidate_backlog": [],
        "interpretation": (
            "parser inventory success is not enough for PathGraph connection; a case needs "
            "grounding-eligible candidates before ROI grounding or PathGraph draft wiring can proceed"
        ),
    }
    supplemental_source_validity_summary = {
        "by_status": {},
        "stale_or_invalid_cases": [],
        "interpretation": "supplemental evidence must match the case screenshot before it can support grounding candidates",
    }
    parser_actual_call_usefulness = _empty_parser_actual_call_usefulness()
    grounding_eligibility_gate_summary = _empty_grounding_eligibility_gate_summary()
    layout_graph_summary = _empty_layout_graph_summary()
    layout_cleanup_summary = _empty_layout_cleanup_summary()
    support_eligibility_summary = new_support_eligibility_summary()
    lifecycle = _start_profile(model_profile_id, wait_seconds=start_wait_seconds) if start_profile else {
        "start_profile_requested": False,
        "started_profile": None,
        "start_error": None,
    }

    try:
        for index, case in enumerate(cases):
            totals["cases"] += 1
            if not isinstance(case, dict):
                totals["invalid"] += 1
                case_results.append({"case_id": f"invalid_{index + 1}", "status": "invalid", "failure_category": "invalid_case"})
                continue
            case_id = str(case.get("case_id") or f"case_{index + 1}")
            screenshot_path = _resolve_path(case.get("screenshot_path"), base=manifest_path.parent)
            if not screenshot_path.exists():
                totals["invalid"] += 1
                case_results.append(
                    {
                        "case_id": case_id,
                        "status": "invalid",
                        "failure_category": "screenshot_missing",
                        "screenshot_path": str(screenshot_path),
                    }
                )
                continue

            case_screenshot_sha256 = _sha256_file(screenshot_path)
            case_out_dir = out_dir / _safe_case_id(case_id)
            supplemental_sources, supplemental_sources_path, supplemental_source_validity = _case_supplemental_sources(
                case,
                base=manifest_path.parent,
                screenshot_path=screenshot_path,
            )
            if supplemental_source_validity.get("status") == "stale_fixture":
                _record_supplemental_source_validity(
                    supplemental_source_validity_summary,
                    case_id=case_id,
                    supplemental_sources_path=supplemental_sources_path,
                    validity=supplemental_source_validity,
                )
                totals["invalid"] += 1
                case_results.append(
                    {
                        "case_id": case_id,
                        "status": "invalid",
                        "failure_category": "stale_supplemental_sources",
                        "screenshot_path": str(screenshot_path),
                        "screenshot_sha256": case_screenshot_sha256,
                        "supplemental_sources_path": str(supplemental_sources_path) if supplemental_sources_path else "",
                        "supplemental_source_validity": supplemental_source_validity,
                    }
                )
                continue
            _record_supplemental_source_validity(
                supplemental_source_validity_summary,
                case_id=case_id,
                supplemental_sources_path=supplemental_sources_path,
                validity=supplemental_source_validity,
            )
            report = run_actual_parser_smoke(
                screenshot_path=screenshot_path,
                out_dir=case_out_dir,
                endpoint=endpoint,
                model_name=model_name,
                model_profile_id=model_profile_id,
                app_name=str(case.get("app_name") or manifest.get("app_name") or "learn_recognition"),
                goal=str(case.get("goal") or manifest.get("goal") or "produce semantic UI parser evidence"),
                state_hint=str(case.get("state_hint") or manifest.get("state_hint") or "unknown"),
                timeout_seconds=timeout_seconds,
                model_caller=model_caller,
                supplemental_sources=supplemental_sources,
                json_stdout=False,
            )
            status = str(report.get("status") or "failed")
            if status == "passed":
                totals["passed"] += 1
            elif status == "blocked":
                totals["blocked"] += 1
            else:
                totals["failed"] += 1

            _accumulate_metric(metrics["actual_parser_call"], (report.get("metrics") or {}).get("actual_parser_call"))
            _accumulate_metric(metrics["parse_inventory"], (report.get("metrics") or {}).get("parse_inventory"))
            _accumulate_actionability_metrics(
                metrics=metrics,
                summary=actionability_summary,
                usefulness=parser_actual_call_usefulness,
                case_id=case_id,
                report=report,
                supplemental_source_validity=supplemental_source_validity,
            )
            _accumulate_grounding_eligibility_gate_summary(
                grounding_eligibility_gate_summary,
                report.get("grounding_eligibility_gate"),
            )
            _accumulate_layout_cleanup_summary(layout_cleanup_summary, case_id=case_id, report=report)
            _accumulate_layout_graph_summary(layout_graph_summary, report.get("layout_graph"))
            case_support_eligibility = report.get("support_eligibility_summary") if isinstance(report.get("support_eligibility_summary"), dict) else None
            if case_support_eligibility:
                merge_support_eligibility_summary(support_eligibility_summary, case_support_eligibility)
            case_results.append(
                {
                    "case_id": case_id,
                    "status": status,
                    "actual_model_call_in_this_run": bool(report.get("actual_model_call_in_this_run")),
                    "screenshot_path": str(screenshot_path),
                    "screenshot_sha256": str(report.get("screenshot_sha256") or case_screenshot_sha256),
                    "report_path": str(report.get("report_path") or case_out_dir / "learn_actual_parser_smoke_report.json"),
                    "actual_parser_output_path": report.get("actual_parser_output_path"),
                    "supplemental_source_keys": sorted(supplemental_sources.keys()) if isinstance(supplemental_sources, dict) else [],
                    "supplemental_sources_path": str(supplemental_sources_path) if supplemental_sources_path else "",
                    "supplemental_source_validity": supplemental_source_validity,
                    "metrics": report.get("metrics") or {},
                    "blocker": report.get("blocker"),
                    "counts": report.get("counts"),
                    "layout_cleanup": _case_layout_cleanup_summary(report),
                    "grounding_eligibility_gate": report.get("grounding_eligibility_gate"),
                    "support_eligibility_summary": case_support_eligibility,
                    "parser_actual_call_usefulness": report.get("parser_actual_call_usefulness"),
                }
            )
    finally:
        if start_profile and stop_started_profile and lifecycle.get("started_profile"):
            lifecycle["stop_started_profile_requested"] = True
            lifecycle["stop_result"] = _stop_started_profile(lifecycle["started_profile"])
        elif start_profile:
            lifecycle["stop_started_profile_requested"] = False
            lifecycle["stop_result"] = None

    _finalize_metric(metrics["actual_parser_call"])
    _finalize_metric(metrics["parse_inventory"])
    _finalize_metric(metrics["parser_case_has_grounding_candidate"])
    _finalize_metric(metrics["grounding_eligible_item_yield"])
    report = {
        "contract_version": "learn_actual_parser_batch_report_v1",
        "manifest_path": str(manifest_path),
        "model_config": {
            "endpoint": endpoint,
            "model_name": model_name,
            "model_profile_id": model_profile_id,
            "timeout_seconds": timeout_seconds,
        },
        "service_lifecycle": lifecycle,
        "source_breakdown": {
            "actual_parser_call": metrics["actual_parser_call"]["attempted"],
            "fixture_only": 0,
            "recorded_parser_output": 0,
            "blocked_or_invalid": totals["blocked"] + totals["invalid"],
        },
        "metrics": metrics,
        "actionability_summary": actionability_summary,
        "supplemental_source_validity_summary": supplemental_source_validity_summary,
        "parser_actual_call_usefulness": parser_actual_call_usefulness,
        "support_eligibility_summary": finalize_support_eligibility_summary(support_eligibility_summary),
        "layout_cleanup_summary": _finalize_layout_cleanup_summary(layout_cleanup_summary),
        "layout_graph_summary": _finalize_layout_graph_summary(layout_graph_summary),
        "grounding_eligibility_gate_summary": _finalize_grounding_eligibility_gate_summary(grounding_eligibility_gate_summary),
        "totals": totals,
        "case_results": case_results,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
        "interpretation": (
            "actual parser batch smoke; fresh attempted cases count actual model calls only. "
            "This is not a 90% recognition claim, not Execute authorization, and not a live-click test."
        ),
    }
    report_path = out_dir / "learn_actual_parser_batch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _start_profile(profile_id: str | None, *, wait_seconds: float) -> dict[str, Any]:
    if not str(profile_id or "").strip():
        return {
            "start_profile_requested": True,
            "started_profile": None,
            "start_error": "model_profile_id_required_for_lifecycle",
        }
    try:
        result = ensure_model_server(
            stage="observe",
            profile_id=str(profile_id),
            wait_until_ready=True,
            wait_seconds=wait_seconds,
        )
    except Exception as exc:
        return {
            "start_profile_requested": True,
            "started_profile": None,
            "start_error": str(exc),
        }
    started_profile = None
    skipped_profile = None
    entry = {
        "profile_id": str(profile_id),
        "started": bool(result.get("started")),
        "before_status": _status_value(result.get("before")),
        "after_status": _status_value(result.get("after")),
        "profile": result.get("profile") or {},
        "start": result.get("start") or {},
    }
    if entry["started"]:
        started_profile = entry
    else:
        skipped_profile = {**entry, "reason": "already_running_or_not_started"}
    return {
        "start_profile_requested": True,
        "started_profile": started_profile,
        "skipped_profile": skipped_profile,
        "start_error": None,
    }


def _stop_started_profile(started_profile: dict[str, Any]) -> dict[str, Any]:
    profile = started_profile.get("profile") if isinstance(started_profile.get("profile"), dict) else {}
    if not profile:
        return {"stopped": False, "error": "started profile missing public profile payload"}
    try:
        result = stop_model_server(profile)
    except Exception as exc:
        return {"stopped": False, "error": str(exc)}
    return {
        "stopped": bool(result.get("stopped")),
        "returncode": result.get("returncode"),
        "stdout": result.get("stdout") or "",
        "stderr": result.get("stderr") or "",
        "after_status": _status_value(result.get("after")),
    }


def _accumulate_metric(total: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    attempted = _int(value.get("attempted"))
    passed = _int(value.get("passed"))
    total["attempted"] = _int(total.get("attempted")) + attempted
    total["passed"] = _int(total.get("passed")) + passed


def _finalize_metric(metric: dict[str, Any]) -> None:
    attempted = _int(metric.get("attempted"))
    passed = _int(metric.get("passed"))
    metric["attempted"] = attempted
    metric["passed"] = passed
    metric["rate"] = "not_covered" if attempted == 0 else round(passed / attempted, 4)


def _metric_attempted(value: Any) -> int:
    return _int(value.get("attempted")) if isinstance(value, dict) else 0


def _accumulate_actionability_metrics(
    *,
    metrics: dict[str, dict[str, Any]],
    summary: dict[str, Any],
    usefulness: dict[str, Any],
    case_id: str,
    report: dict[str, Any],
    supplemental_source_validity: dict[str, Any] | None = None,
) -> None:
    parser_attempted = _metric_attempted((report.get("metrics") or {}).get("actual_parser_call"))
    if parser_attempted <= 0:
        return
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    screen_inventory_count = _int(counts.get("screen_inventory_count"))
    grounding_eligible_count = _int(counts.get("grounding_eligible_count"))
    accepted_for_grounding_count = _int(counts.get("accepted_for_grounding_count"))
    review_only_count = _int(counts.get("review_only_count"))
    candidate_count = max(grounding_eligible_count, accepted_for_grounding_count)

    case_metric = metrics["parser_case_has_grounding_candidate"]
    case_metric["attempted"] = _int(case_metric.get("attempted")) + 1
    if candidate_count > 0:
        case_metric["passed"] = _int(case_metric.get("passed")) + 1
    elif screen_inventory_count > 0:
        summary["cases_without_grounding_candidates"].append(case_id)
        summary["grounding_candidate_backlog"].append(
            {
                "case_id": case_id,
                "failure_category": "no_grounding_candidate",
                "screen_inventory_count": screen_inventory_count,
                "review_only_count": review_only_count,
                "supplemental_validity_status": str((supplemental_source_validity or {}).get("status") or "unknown"),
                "recommended_intervention": (
                    "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox "
                    "alignment before PathGraph wiring"
                ),
            }
        )

    item_metric = metrics["grounding_eligible_item_yield"]
    item_metric["attempted"] = _int(item_metric.get("attempted")) + screen_inventory_count
    item_metric["passed"] = _int(item_metric.get("passed")) + candidate_count

    summary["total_screen_inventory_count"] = _int(summary.get("total_screen_inventory_count")) + screen_inventory_count
    summary["total_grounding_eligible_count"] = _int(summary.get("total_grounding_eligible_count")) + candidate_count
    summary["total_review_only_count"] = _int(summary.get("total_review_only_count")) + review_only_count
    _accumulate_parser_actual_call_usefulness(
        usefulness=usefulness,
        case_id=case_id,
        screen_inventory_count=screen_inventory_count,
        candidate_count=candidate_count,
        report=report,
    )


def _empty_parser_actual_call_usefulness() -> dict[str, Any]:
    return {
        "parser_inventory_generated": False,
        "parser_useful_for_review": False,
        "parser_useful_for_grounding": False,
        "semantic_only_regions": 0,
        "grounding_eligible_regions": 0,
        "accepted_for_grounding": 0,
        "cases_useful_for_grounding": [],
        "cases_review_only_without_grounding": [],
        "blocked_from_grounding_reasons": {},
        "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
    }


def _empty_grounding_eligibility_gate_summary() -> dict[str, Any]:
    return {
        "contract_version": "learn_grounding_eligibility_gate_batch_summary_v1",
        "evaluation_scope": "learn_mode_grounding_eligibility_gate",
        "execution_scope": "no_action_no_execute_no_live_click",
        "not_accuracy": True,
        "not_e2e_success": True,
        "not_execute_mode_default": True,
        "grounding_eligibility": {"attempted": 0, "eligible": 0, "blocked": 0},
        "semantic_only_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "ocr_only_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "browser_chrome_rejection": {"passed": 0, "attempted": 0, "rate": "not_covered"},
        "split_roi_required": {
            "attempted": 0,
            "count": 0,
            "item_ids": [],
            "interpretation": (
                "split ROI is a diagnostic for overlapping distinct eligible targets; it is not click permission "
                "or a grounding success metric"
            ),
        },
        "non_actionable_leaked_to_grounding": {
            "passed": 1,
            "attempted": 0,
            "rate": "not_covered",
            "leaked_count": 0,
            "leaked_item_ids": [],
            "interpretation": "non-actionable items must not enter ROI grounding",
        },
        "grounding_eligible_breakdown": {
            "semantic_only": 0,
            "ocr_only": 0,
            "uia_interactable": 0,
            "dom_interactable": 0,
            "omniparser_interactable": 0,
            "human_calibrated": 0,
            "no_dispatch_execute_candidate": 0,
        },
        "interpretation": (
            "grounding_eligible only means the item may enter ROI grounding; it is not click permission, "
            "Execute authorization, PathGraph promotion, or a recognition accuracy metric"
        ),
    }


def _empty_layout_graph_summary() -> dict[str, Any]:
    return {
        "contract_version": "learn_layout_graph_batch_summary_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "node_count": 0,
        "zone_counts": {},
        "overlap_cluster_count": 0,
        "split_roi_required_item_ids": [],
        "interpretation": "layout graph summary is review/ROI-planning evidence only; it is not click permission or accuracy",
    }


def _empty_layout_cleanup_summary() -> dict[str, Any]:
    return {
        "contract_version": "learn_layout_cleanup_batch_summary_v1",
        "input_count": 0,
        "output_count": 0,
        "suppressed_count": 0,
        "duplicates_merged": 0,
        "suppression_reason_counts": {},
        "cases_with_suppression": [],
        "interpretation": (
            "layout cleanup summary explains why parser candidates were removed or merged; "
            "it is not model accuracy, click success, or Execute authorization"
        ),
    }


def _case_layout_cleanup_summary(report: dict[str, Any]) -> dict[str, Any]:
    layout_cleanup = report.get("layout_cleanup") if isinstance(report.get("layout_cleanup"), dict) else {}
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    reason_counts = layout_cleanup.get("suppression_reason_counts")
    if not isinstance(reason_counts, dict):
        reason_counts = counts.get("layout_cleanup_suppression_reason_counts")
    if not isinstance(reason_counts, dict):
        reason_counts = {}
    return {
        "input_count": _int(layout_cleanup.get("input_count")),
        "output_count": _int(layout_cleanup.get("output_count")),
        "suppressed_count": _int(layout_cleanup.get("suppressed_count") or counts.get("layout_cleanup_suppressed_count")),
        "duplicates_merged": _int(layout_cleanup.get("duplicates_merged")),
        "suppression_reason_counts": {str(key): _int(value) for key, value in reason_counts.items()},
    }


def _accumulate_layout_cleanup_summary(summary: dict[str, Any], *, case_id: str, report: dict[str, Any]) -> None:
    case_summary = _case_layout_cleanup_summary(report)
    summary["input_count"] = _int(summary.get("input_count")) + _int(case_summary.get("input_count"))
    summary["output_count"] = _int(summary.get("output_count")) + _int(case_summary.get("output_count"))
    summary["suppressed_count"] = _int(summary.get("suppressed_count")) + _int(case_summary.get("suppressed_count"))
    summary["duplicates_merged"] = _int(summary.get("duplicates_merged")) + _int(case_summary.get("duplicates_merged"))
    reason_counts = summary["suppression_reason_counts"]
    for reason, count in (case_summary.get("suppression_reason_counts") or {}).items():
        reason_counts[str(reason)] = _int(reason_counts.get(str(reason))) + _int(count)
    if _int(case_summary.get("suppressed_count")) > 0:
        summary["cases_with_suppression"].append(
            {
                "case_id": case_id,
                "suppressed_count": _int(case_summary.get("suppressed_count")),
                "suppression_reason_counts": case_summary.get("suppression_reason_counts") or {},
            }
        )


def _finalize_layout_cleanup_summary(summary: dict[str, Any]) -> dict[str, Any]:
    summary["input_count"] = _int(summary.get("input_count"))
    summary["output_count"] = _int(summary.get("output_count"))
    summary["suppressed_count"] = _int(summary.get("suppressed_count"))
    summary["duplicates_merged"] = _int(summary.get("duplicates_merged"))
    summary["suppression_reason_counts"] = dict(sorted((summary.get("suppression_reason_counts") or {}).items()))
    summary["cases_with_suppression"] = sorted(
        summary.get("cases_with_suppression") if isinstance(summary.get("cases_with_suppression"), list) else [],
        key=lambda item: str(item.get("case_id") if isinstance(item, dict) else ""),
    )
    return summary


def _accumulate_layout_graph_summary(summary: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    summary["node_count"] = _int(summary.get("node_count")) + _int(value.get("node_count"))
    zones = value.get("zones") if isinstance(value.get("zones"), dict) else {}
    zone_counts = summary["zone_counts"]
    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        item_ids = zone.get("item_ids") if isinstance(zone.get("item_ids"), list) else []
        count = len([item for item in item_ids if str(item or "").strip()])
        if count:
            zone_counts[str(zone_id)] = _int(zone_counts.get(str(zone_id))) + count
    clusters = value.get("overlap_clusters") if isinstance(value.get("overlap_clusters"), list) else []
    summary["overlap_cluster_count"] = _int(summary.get("overlap_cluster_count")) + len(clusters)
    for cluster in clusters:
        if not isinstance(cluster, dict) or cluster.get("split_roi_required") is not True:
            continue
        item_ids = cluster.get("item_ids") if isinstance(cluster.get("item_ids"), list) else []
        summary["split_roi_required_item_ids"].extend(str(item) for item in item_ids if str(item or "").strip())


def _finalize_layout_graph_summary(summary: dict[str, Any]) -> dict[str, Any]:
    summary["node_count"] = _int(summary.get("node_count"))
    summary["overlap_cluster_count"] = _int(summary.get("overlap_cluster_count"))
    summary["zone_counts"] = dict(sorted((summary.get("zone_counts") or {}).items()))
    summary["split_roi_required_item_ids"] = sorted(set(summary.get("split_roi_required_item_ids") if isinstance(summary.get("split_roi_required_item_ids"), list) else []))
    return summary


def _accumulate_grounding_eligibility_gate_summary(summary: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    gate_counts = value.get("grounding_eligibility") if isinstance(value.get("grounding_eligibility"), dict) else {}
    target_counts = summary["grounding_eligibility"]
    target_counts["attempted"] += _int(gate_counts.get("attempted"))
    target_counts["eligible"] += _int(gate_counts.get("eligible"))
    target_counts["blocked"] += _int(gate_counts.get("blocked"))
    _accumulate_pass_attempt(summary["semantic_only_rejection"], value.get("semantic_only_rejection"))
    _accumulate_pass_attempt(summary["ocr_only_rejection"], value.get("ocr_only_rejection"))
    _accumulate_pass_attempt(summary["browser_chrome_rejection"], value.get("browser_chrome_rejection"))
    split = value.get("split_roi_required") if isinstance(value.get("split_roi_required"), dict) else {}
    split_target = summary["split_roi_required"]
    split_target["attempted"] += _int(split.get("attempted"))
    split_target["count"] += _int(split.get("count"))
    if isinstance(split.get("item_ids"), list):
        split_target["item_ids"].extend(str(item) for item in split["item_ids"] if str(item or "").strip())
    leak = value.get("non_actionable_leaked_to_grounding") if isinstance(value.get("non_actionable_leaked_to_grounding"), dict) else {}
    leak_target = summary["non_actionable_leaked_to_grounding"]
    leak_target["attempted"] += _int(leak.get("attempted"))
    leak_target["leaked_count"] += _int(leak.get("leaked_count"))
    if isinstance(leak.get("leaked_item_ids"), list):
        leak_target["leaked_item_ids"].extend(str(item) for item in leak["leaked_item_ids"] if str(item or "").strip())
    breakdown = value.get("grounding_eligible_breakdown") if isinstance(value.get("grounding_eligible_breakdown"), dict) else {}
    for key in summary["grounding_eligible_breakdown"]:
        summary["grounding_eligible_breakdown"][key] += _int(breakdown.get(key))


def _finalize_grounding_eligibility_gate_summary(summary: dict[str, Any]) -> dict[str, Any]:
    _finalize_metric(summary["semantic_only_rejection"])
    _finalize_metric(summary["ocr_only_rejection"])
    _finalize_metric(summary["browser_chrome_rejection"])
    split = summary["split_roi_required"]
    split["attempted"] = _int(split.get("attempted"))
    split["count"] = _int(split.get("count"))
    split["item_ids"] = sorted(set(split.get("item_ids") if isinstance(split.get("item_ids"), list) else []))
    leak = summary["non_actionable_leaked_to_grounding"]
    leak["passed"] = 1 if _int(leak.get("leaked_count")) == 0 else 0
    leak["rate"] = "not_covered" if _int(leak.get("attempted")) == 0 else float(leak["passed"])
    leak["leaked_item_ids"] = sorted(set(leak.get("leaked_item_ids") if isinstance(leak.get("leaked_item_ids"), list) else []))
    return summary


def _accumulate_pass_attempt(total: dict[str, Any], value: Any) -> None:
    if not isinstance(value, dict):
        return
    total["attempted"] = _int(total.get("attempted")) + _int(value.get("attempted"))
    total["passed"] = _int(total.get("passed")) + _int(value.get("passed"))


def _accumulate_parser_actual_call_usefulness(
    *,
    usefulness: dict[str, Any],
    case_id: str,
    screen_inventory_count: int,
    candidate_count: int,
    report: dict[str, Any],
) -> None:
    case_usefulness = report.get("parser_actual_call_usefulness") if isinstance(report.get("parser_actual_call_usefulness"), dict) else {}
    semantic_only_regions = _int(case_usefulness.get("semantic_only_regions"))
    grounding_eligible_regions = _int(case_usefulness.get("grounding_eligible_regions")) or candidate_count
    accepted_for_grounding = _int(case_usefulness.get("accepted_for_grounding"))
    if screen_inventory_count > 0:
        usefulness["parser_inventory_generated"] = True
        usefulness["parser_useful_for_review"] = True
    if grounding_eligible_regions > 0 and accepted_for_grounding > 0:
        usefulness["parser_useful_for_grounding"] = True
        usefulness["cases_useful_for_grounding"].append(case_id)
    elif screen_inventory_count > 0:
        usefulness["cases_review_only_without_grounding"].append(case_id)
    usefulness["semantic_only_regions"] = _int(usefulness.get("semantic_only_regions")) + semantic_only_regions
    usefulness["grounding_eligible_regions"] = _int(usefulness.get("grounding_eligible_regions")) + grounding_eligible_regions
    usefulness["accepted_for_grounding"] = _int(usefulness.get("accepted_for_grounding")) + accepted_for_grounding
    reason = str(case_usefulness.get("blocked_from_grounding_reason") or "").strip()
    if reason:
        reasons = usefulness["blocked_from_grounding_reasons"]
        reasons[reason] = _int(reasons.get(reason)) + 1


def _resolve_path(value: Any, *, base: Path) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return (base / path).resolve()


def _case_supplemental_sources(
    case: dict[str, Any],
    *,
    base: Path,
    screenshot_path: Path,
) -> tuple[dict[str, Any] | None, Path | None, dict[str, Any]]:
    inline_sources = case.get("supplemental_sources")
    if isinstance(inline_sources, dict):
        return inline_sources, None, {"status": "inline_not_checksum_checked"}
    source_path_value = str(case.get("supplemental_sources_path") or "").strip()
    if not source_path_value:
        return None, None, {"status": "not_provided"}
    source_path = _resolve_path(source_path_value, base=base)
    payload = _read_json(source_path)
    validity = _supplemental_source_validity(payload=payload, screenshot_path=screenshot_path, source_path=source_path)
    if validity.get("status") == "stale_fixture":
        return None, source_path, validity
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else None
    if sources is None:
        observe_bundle = payload.get("observe_bundle") if isinstance(payload.get("observe_bundle"), dict) else {}
        sources = observe_bundle.get("sources") if isinstance(observe_bundle.get("sources"), dict) else None
    if sources is None:
        raise ValueError(f"supplemental_sources_path does not contain sources: {source_path}")
    return {str(key): value for key, value in sources.items() if key != "vision" and isinstance(value, dict)}, source_path, validity


def _supplemental_source_validity(*, payload: dict[str, Any], screenshot_path: Path, source_path: Path) -> dict[str, Any]:
    expected_checksum = str(payload.get("screenshot_sha256") or "").strip().lower()
    if not expected_checksum:
        screenshot = payload.get("screenshot") if isinstance(payload.get("screenshot"), dict) else {}
        expected_checksum = str(screenshot.get("sha256") or "").strip().lower()
    if not expected_checksum:
        return {
            "status": "checksum_not_declared",
            "screenshot_path": str(screenshot_path),
            "supplemental_sources_path": str(source_path),
        }
    actual_checksum = _sha256_file(screenshot_path)
    if actual_checksum != expected_checksum:
        return {
            "status": "stale_fixture",
            "failure_category": "stale_supplemental_sources",
            "expected_screenshot_sha256": expected_checksum,
            "actual_screenshot_sha256": actual_checksum,
            "screenshot_path": str(screenshot_path),
            "supplemental_sources_path": str(source_path),
        }
    return {
        "status": "checksum_match",
        "screenshot_sha256": actual_checksum,
        "screenshot_path": str(screenshot_path),
        "supplemental_sources_path": str(source_path),
    }


def _record_supplemental_source_validity(
    summary: dict[str, Any],
    *,
    case_id: str,
    supplemental_sources_path: Path | None,
    validity: dict[str, Any],
) -> None:
    status = str(validity.get("status") or "unknown")
    by_status = summary.setdefault("by_status", {})
    by_status[status] = _int(by_status.get(status)) + 1
    if status == "stale_fixture":
        summary.setdefault("stale_or_invalid_cases", []).append(
            {
                "case_id": case_id,
                "status": status,
                "failure_category": str(validity.get("failure_category") or "stale_supplemental_sources"),
                "supplemental_sources_path": str(supplemental_sources_path) if supplemental_sources_path else "",
            }
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_case_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe[:80] or "case"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _status_value(payload: Any) -> str:
    return str(payload.get("status") or "") if isinstance(payload, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-profile", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--start-profile", action="store_true")
    parser.add_argument("--no-stop-started-profile", action="store_true")
    parser.add_argument("--start-wait-seconds", type=float, default=180.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_actual_parser_batch(
        manifest_path=args.manifest,
        out_dir=args.out,
        endpoint=args.endpoint,
        model_name=args.model,
        model_profile_id=args.model_profile,
        timeout_seconds=args.timeout_seconds,
        start_profile=args.start_profile,
        stop_started_profile=not args.no_stop_started_profile,
        start_wait_seconds=args.start_wait_seconds,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
