from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.draft_review import load_learning_draft_review
from scripts.check_learning_structure_quality import check_learning_structure_quality_case

DEFAULT_CASES = [
    {
        "case_id": "applemusic",
        "source_path": "artifacts/learning-runs/panel_20260710-211655-075_applemusic/learn_mode_demo_scaffold.json",
        "expect_source_image_override": False,
    },
    {
        "case_id": "qq",
        "source_path": "artifacts/learning-runs/panel_20260710-211658-310_qq/learn_mode_demo_scaffold.json",
        "expect_source_image_override": False,
    },
    {
        "case_id": "python_org",
        "source_path": "artifacts/learning-runs/panel_20260710-211701-968_python_org/learn_mode_demo_scaffold.json",
        "expect_source_image_override": True,
    },
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _resolve_project_path(path: str | Path, root: Path = ROOT) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _relative(path: str | Path | None, root: Path = ROOT) -> str:
    if not path:
        return ""
    candidate = Path(str(path))
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(candidate)


def _exists(path: str | Path | None, root: Path = ROOT) -> bool:
    if not path:
        return False
    return _resolve_project_path(path, root).exists()


def _companion_trial_path(source_path: Path) -> Path:
    return source_path.with_name("trial_result.json")


def _source_override_from_companion(source_path: Path) -> dict[str, Any]:
    trial_path = _companion_trial_path(source_path)
    if not trial_path.exists():
        return {
            "status": "not_available",
            "trial_path": _relative(trial_path),
            "applied": False,
        }
    trial = _read_json(trial_path)
    override = trial.get("source_image_override") if isinstance(trial.get("source_image_override"), dict) else {}
    return {
        "status": str(override.get("status") or "not_recorded"),
        "trial_path": _relative(trial_path),
        "applied": bool(override.get("applied") is True),
        "reason": str(override.get("reason") or ""),
        "original_path": _relative(override.get("original_path")),
        "path": _relative(override.get("path")),
    }


def _model_grounding_from_companion(source_path: Path) -> dict[str, Any]:
    trial_path = _companion_trial_path(source_path)
    if not trial_path.exists():
        return {
            "status": "not_available",
            "model_accuracy_claim_allowed": False,
        }
    trial = _read_json(trial_path)
    evidence = (
        trial.get("model_grounding_evidence")
        if isinstance(trial.get("model_grounding_evidence"), dict)
        else {}
    )
    attempted = int(evidence.get("model_grounding_attempted_count") or 0)
    return {
        "status": str(evidence.get("status") or "not_recorded"),
        "model_grounding_attempted_count": attempted,
        "model_call_plan_is_recommendation_only": bool(
            evidence.get("model_call_plan_is_recommendation_only") is True
        ),
        "model_accuracy_claim_allowed": False,
        "interpretation": (
            "review/display regression only; not model accuracy evidence"
            if attempted <= 0
            else "recorded grounding attempts still require separate reviewer acceptance"
        ),
    }


def _structure_quality_from_companion(source_path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    trial_path = _companion_trial_path(source_path)
    if not trial_path.exists():
        return {
            "status": "not_available",
            "trial_path": _relative(trial_path, root),
            "runtime_pathgraph_ready": False,
            "interpretation": "no companion trial_result.json; structure quality not archived",
        }
    result = check_learning_structure_quality_case(
        {
            "case_id": source_path.parent.name or source_path.stem,
            "trial_result_path": trial_path,
        },
        root=root,
    )
    metrics = result.get("structure_metrics") if isinstance(result.get("structure_metrics"), dict) else {}
    return {
        "status": str(result.get("quality_status") or "unknown"),
        "trial_path": _relative(trial_path, root),
        "runtime_pathgraph_ready": bool(result.get("runtime_pathgraph_ready") is True),
        "stage1_screen_coverage_ratio": metrics.get("stage1_screen_coverage_ratio"),
        "stage1_near_full_partition_required_ratio": metrics.get("stage1_near_full_partition_required_ratio"),
        "stage2_numbered_item_count": metrics.get("stage2_numbered_item_count"),
        "fused_review_box_count": metrics.get("fused_review_box_count"),
        "sibling_non_parent_overlap_count": metrics.get("sibling_non_parent_overlap_count"),
        "failed_checks": result.get("failed_checks") if isinstance(result.get("failed_checks"), list) else [],
        "interpretation": "structure-quality archive signal only; not model accuracy or Execute readiness",
    }


def check_learning_protected_case(case: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "").strip() or "unnamed_case"
    source_path = _resolve_project_path(case.get("source_path") or "", root)
    expect_override = bool(case.get("expect_source_image_override") is True)
    result: dict[str, Any] = {
        "case_id": case_id,
        "source_path": _relative(source_path, root),
        "attempted": True,
        "passed": False,
        "errors": [],
    }
    if not source_path.exists():
        result["errors"].append("source_missing")
        return result
    try:
        review = load_learning_draft_review(source_path, project_root=root)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"load_failed:{type(exc).__name__}:{exc}")
        return result

    draft = review.get("draft") if isinstance(review.get("draft"), dict) else {}
    preview = (
        review.get("screen_understanding_preview")
        if isinstance(review.get("screen_understanding_preview"), dict)
        else {}
    )
    candidate_review = (
        review.get("pathgraph_candidate_review")
        if isinstance(review.get("pathgraph_candidate_review"), dict)
        else {}
    )
    page_detail = (
        candidate_review.get("page_detail_candidate")
        if isinstance(candidate_review.get("page_detail_candidate"), dict)
        else {}
    )
    layout = page_detail.get("layout") if isinstance(page_detail.get("layout"), dict) else {}
    compiled_overlay = str(preview.get("compiled_overlay_path") or "").strip()
    full_overlay = str(preview.get("full_screen_understanding_overlay_path") or "").strip()
    state_count = len(draft.get("states") if isinstance(draft.get("states"), list) else [])
    region_count = len(draft.get("regions") if isinstance(draft.get("regions"), list) else [])
    action_count = len(
        draft.get("action_templates") if isinstance(draft.get("action_templates"), list) else []
    )
    states_with_refs = [
        state.get("state_id")
        for state in draft.get("states", [])
        if isinstance(state, dict) and (state.get("region_refs") or state.get("action_template_refs"))
    ]
    source_override = _source_override_from_companion(source_path)
    model_grounding = _model_grounding_from_companion(source_path)
    structure_quality = _structure_quality_from_companion(source_path, root=root)

    checks = {
        "source_loads": True,
        "compiled_overlay_exists": _exists(compiled_overlay, root),
        "full_overlay_exists": _exists(full_overlay, root),
        "uses_review_overlay": "review-overlays" in compiled_overlay.replace("\\", "/"),
        "page_detail_present": page_detail.get("contract_version") == "learn_page_detail_candidate_v1",
        "draft_regions_present": region_count > 0,
        "draft_actions_present": action_count > 0,
        "state_refs_present": bool(states_with_refs),
        "source_override_expectation_met": (
            source_override["applied"] if expect_override else source_override["status"] in {"not_recorded", "not_available", ""}
        ),
        "model_grounding_not_promoted": model_grounding["model_accuracy_claim_allowed"] is False,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    result.update(
        {
            "passed": not failed_checks,
            "failed_checks": failed_checks,
            "checks": checks,
            "display_summary": {
                "state_count": state_count,
                "region_count": region_count,
                "action_template_count": action_count,
                "states_with_refs_count": len(states_with_refs),
                "states_with_refs_sample": states_with_refs[:6],
                "page_detail_section_count": len(layout.get("sections") if isinstance(layout.get("sections"), list) else []),
                "page_detail_region_count": len(layout.get("regions") if isinstance(layout.get("regions"), list) else []),
            },
            "overlay": {
                "compiled_overlay_path": _relative(compiled_overlay, root),
                "full_screen_understanding_overlay_path": _relative(full_overlay, root),
            },
            "source_image_override": source_override,
            "model_grounding_evidence": model_grounding,
            "structure_quality": structure_quality,
            "interpretation": "protected-set display/review check only; no live click, no live fill, no submit",
        }
    )
    return result


def run_learning_protected_set_review(
    cases: list[dict[str, Any]] | None = None,
    *,
    root: Path = ROOT,
    checkpoint_id: str = "",
) -> dict[str, Any]:
    selected_cases = cases or DEFAULT_CASES
    case_results = [check_learning_protected_case(case, root=root) for case in selected_cases]
    attempted = len(case_results)
    passed = sum(1 for item in case_results if item.get("passed") is True)
    failed = attempted - passed
    report = {
        "contract_version": "learning_protected_set_review_check_v1",
        "generated_at": _now(),
        "summary": {
            "attempted": attempted,
            "passed": passed,
            "failed": failed,
            "rate": round(passed / attempted, 4) if attempted else "not_covered",
            "interpretation": "display/review protected-set check; not recognition accuracy or model grounding evidence",
        },
        "cases": case_results,
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
    }
    if checkpoint_id:
        report["archive_node"] = build_learning_protected_archive_node(
            report,
            checkpoint_id=checkpoint_id,
            root=root,
        )
    return report


def build_learning_protected_archive_node(
    report: dict[str, Any],
    *,
    checkpoint_id: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    case_nodes = []
    for item in cases:
        if not isinstance(item, dict):
            continue
        overlay = item.get("overlay") if isinstance(item.get("overlay"), dict) else {}
        display = item.get("display_summary") if isinstance(item.get("display_summary"), dict) else {}
        case_nodes.append(
            {
                "case_id": item.get("case_id"),
                "source_path": item.get("source_path"),
                "compiled_overlay_path": overlay.get("compiled_overlay_path"),
                "state_count": display.get("state_count"),
                "region_count": display.get("region_count"),
                "action_template_count": display.get("action_template_count"),
                "page_detail_section_count": display.get("page_detail_section_count"),
                "passed": item.get("passed") is True,
                "model_grounding_status": (
                    item.get("model_grounding_evidence", {}).get("status")
                    if isinstance(item.get("model_grounding_evidence"), dict)
                    else "unknown"
                ),
                **_archive_structure_quality_fields(item),
            }
        )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return {
        "contract_version": "learning_protected_archive_node_v1",
        "checkpoint_id": checkpoint_id,
        "created_at": report.get("generated_at") or _now(),
        "status": "pass" if int(summary.get("failed") or 0) == 0 else "fail",
        "scope": "AppleMusic / QQ / Python.org protected display-review baseline",
        "case_count": len(case_nodes),
        "cases": case_nodes,
        "anti_pollution_policy": {
            "before_new_interface": (
                "uv run python scripts\\check_learning_protected_set_review.py "
                "--out logs\\benchmarks\\learning_protected_set_review_latest.json "
                "--checkpoint-id latest --json"
            ),
            "after_strategy_change": (
                "rerun the same protected-set command and compare all case nodes before testing a new interface"
            ),
            "failure_policy": "fix the shared invariant or revert the strategy before continuing new-interface exploration",
        },
        "safety_boundary": {
            "display_review_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "interpretation": (
            "Archive node for protected Learning Mode display-review regression. "
            "It is not model accuracy, point grounding, Execute authorization, or Runtime PathGraph readiness."
        ),
    }


def compare_learning_protected_archive_node(
    current_report: dict[str, Any],
    baseline_report: dict[str, Any],
) -> dict[str, Any]:
    current_archive = _archive_node_from_report(current_report)
    baseline_archive = _archive_node_from_report(baseline_report)
    current_cases = _archive_case_map(current_archive)
    baseline_cases = _archive_case_map(baseline_archive)
    mismatches: list[dict[str, Any]] = []
    legacy_skipped_optional_fields: set[str] = set()
    for case_id in sorted(set(current_cases) | set(baseline_cases)):
        current_case = current_cases.get(case_id)
        baseline_case = baseline_cases.get(case_id)
        if current_case is None:
            mismatches.append({"case_id": case_id, "field": "case_presence", "baseline": "present", "current": "missing"})
            continue
        if baseline_case is None:
            mismatches.append({"case_id": case_id, "field": "case_presence", "baseline": "missing", "current": "present"})
            continue
        for field in _archive_comparison_fields():
            if field in _archive_optional_comparison_fields() and field not in baseline_case:
                legacy_skipped_optional_fields.add(field)
                continue
            if current_case.get(field) != baseline_case.get(field):
                mismatches.append(
                    {
                        "case_id": case_id,
                        "field": field,
                        "baseline": baseline_case.get(field),
                        "current": current_case.get(field),
                    }
                )
    status = "pass" if not mismatches else "fail"
    return {
        "contract_version": "learning_protected_archive_node_comparison_v1",
        "status": status,
        "baseline_checkpoint_id": baseline_archive.get("checkpoint_id"),
        "current_checkpoint_id": current_archive.get("checkpoint_id"),
        "compared_case_count": len(current_cases),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "comparison_fields": _archive_comparison_fields(),
        "optional_comparison_fields": _archive_optional_comparison_fields(),
        "legacy_skipped_optional_fields": sorted(legacy_skipped_optional_fields),
        "interpretation": (
            "Protected-set anti-pollution comparison. A mismatch means the AppleMusic / QQ / Python.org "
            "display-review baseline changed and must be reviewed before exploring another interface."
        ),
    }


def _archive_node_from_report(report: dict[str, Any]) -> dict[str, Any]:
    archive = report.get("archive_node") if isinstance(report.get("archive_node"), dict) else {}
    if archive.get("contract_version") == "learning_protected_archive_node_v1":
        return archive
    if report.get("contract_version") == "learning_protected_archive_node_v1":
        return report
    if report.get("contract_version") == "learning_protected_set_review_check_v1":
        clone = copy.deepcopy(report)
        if "archive_node" not in clone:
            clone["archive_node"] = build_learning_protected_archive_node(
                clone,
                checkpoint_id=str((clone.get("summary") or {}).get("checkpoint_id") or "baseline"),
            )
        return clone["archive_node"]
    raise ValueError("baseline/current report must contain a learning protected archive node")


def _archive_case_map(archive: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = archive.get("cases") if isinstance(archive.get("cases"), list) else []
    return {
        str(item.get("case_id") or ""): item
        for item in cases
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    }


def _archive_structure_quality_fields(item: dict[str, Any]) -> dict[str, Any]:
    structure = item.get("structure_quality") if isinstance(item.get("structure_quality"), dict) else {}
    if not structure or structure.get("status") in {None, "", "not_available"}:
        return {}
    return {
        "structure_quality_status": structure.get("status"),
        "structure_stage1_screen_coverage_ratio": structure.get("stage1_screen_coverage_ratio"),
        "structure_stage1_near_full_partition_required_ratio": structure.get(
            "stage1_near_full_partition_required_ratio"
        ),
        "structure_stage2_numbered_item_count": structure.get("stage2_numbered_item_count"),
        "structure_fused_review_box_count": structure.get("fused_review_box_count"),
        "structure_sibling_non_parent_overlap_count": structure.get("sibling_non_parent_overlap_count"),
        "structure_runtime_pathgraph_ready": bool(structure.get("runtime_pathgraph_ready") is True),
    }


def _archive_comparison_fields() -> list[str]:
    return [
        "source_path",
        "compiled_overlay_path",
        "state_count",
        "region_count",
        "action_template_count",
        "page_detail_section_count",
        "passed",
        "model_grounding_status",
        *_archive_optional_comparison_fields(),
    ]


def _archive_optional_comparison_fields() -> list[str]:
    return [
        "structure_quality_status",
        "structure_stage1_screen_coverage_ratio",
        "structure_stage1_near_full_partition_required_ratio",
        "structure_stage2_numbered_item_count",
        "structure_fused_review_box_count",
        "structure_sibling_non_parent_overlap_count",
        "structure_runtime_pathgraph_ready",
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check protected Learning Mode review scaffolds.")
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    parser.add_argument("--checkpoint-id", default="", help="Optional archive-node id for this protected baseline.")
    parser.add_argument("--baseline", default="", help="Optional previous archive/report JSON to compare against.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_learning_protected_set_review(checkpoint_id=args.checkpoint_id)
    if args.baseline:
        baseline = _read_json(_resolve_project_path(args.baseline))
        report["baseline_comparison"] = compare_learning_protected_archive_node(report, baseline)
    if args.out:
        out_path = _resolve_project_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    baseline_status = (
        report.get("baseline_comparison", {}).get("status")
        if isinstance(report.get("baseline_comparison"), dict)
        else "pass"
    )
    return 0 if report["summary"]["failed"] == 0 and baseline_status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
