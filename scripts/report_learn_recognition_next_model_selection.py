from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_READINESS_PATH = PROJECT_ROOT / "logs" / "benchmarks" / "learn_recognition_model_readiness_v1" / "model_readiness_report.json"
DEFAULT_COUNTERFACTUAL_PATH = PROJECT_ROOT / "logs" / "benchmarks" / "learn_recognition_seek_recorded_per_config_counterfactual" / "learn_recognition_benchmark_report.json"


def build_learn_recognition_next_model_selection(
    *,
    readiness_path: str | Path = DEFAULT_READINESS_PATH,
    evidence_paths: list[str | Path] | None = None,
    out: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    readiness_path = Path(readiness_path)
    readiness = _read_json(readiness_path)
    evidence_paths = [Path(path) for path in (evidence_paths or [DEFAULT_COUNTERFACTUAL_PATH])]
    evidence = [_read_json(path) for path in evidence_paths if Path(path).exists()]
    recorded_breakdown = _recorded_profile_breakdown(evidence)
    recorded_cases = _recorded_case_summary(evidence)

    profiles = readiness.get("profiles") if isinstance(readiness.get("profiles"), list) else []
    candidates = [
        _score_profile(profile, recorded_breakdown, recorded_cases)
        for profile in profiles
        if _is_download_candidate(profile)
    ]
    candidates.sort(key=lambda item: (-item["selection_score"], item["max_parameters_b"] or 999, item["profile_id"]))
    primary = candidates[0] if candidates else None
    fast_probe = _fast_probe_candidate(candidates)
    report = {
        "contract_version": "learn_recognition_next_model_selection_v1",
        "readiness_report_path": str(readiness_path),
        "evidence_report_paths": [str(path) for path in evidence_paths],
        "candidate_count": len(candidates),
        "primary_recommendation": primary,
        "fast_probe_recommendation": fast_probe,
        "candidate_ranking": candidates,
        "recorded_profile_breakdown": recorded_breakdown,
        "recorded_case_summary": recorded_cases,
        "selection_policy": {
            "primary": (
                "Prefer a learn-only ROI grounding profile with recorded evidence on current VISTA misses; "
                "do not lower validator thresholds or treat recorded output as actual model ability."
            ),
            "fast_probe": "Prefer the smallest ROI grounding profile for a cheap launchability smoke.",
        },
        "anti_inflation": {
            "not_accuracy": True,
            "not_model_ability_proof": True,
            "not_execute_authorization": True,
            "not_live_click_or_submit": True,
            "interpretation": (
                "selection report only; it chooses the next profile to download/start. "
                "It does not run the model, prove recognition accuracy, or authorize Execute."
            ),
        },
        "next_command_hint": _next_command_hint(primary),
    }
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _is_download_candidate(profile: dict[str, Any]) -> bool:
    if profile.get("readiness_status") == "actual_call_ready":
        return False
    if profile.get("download_status") != "not_downloaded":
        return False
    max_parameters_b = profile.get("max_parameters_b")
    if isinstance(max_parameters_b, (int, float)) and max_parameters_b > 12:
        return False
    return profile.get("mode_scope") in {"learn_only", "learn"}


def _recorded_profile_breakdown(reports: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for report in reports:
        breakdown = report.get("recorded_model_profile_breakdown") or {}
        grounding = breakdown.get("recorded_grounding_output") if isinstance(breakdown, dict) else {}
        if not isinstance(grounding, dict):
            continue
        for profile_id, count in grounding.items():
            totals[str(profile_id)] = totals.get(str(profile_id), 0) + int(count or 0)
    return totals


def _recorded_case_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile: dict[str, list[str]] = {}
    current_miss_related: dict[str, list[str]] = {}
    for report in reports:
        for case in report.get("case_results") or []:
            profile = case.get("recorded_model_profile") or {}
            profile_id = str(profile.get("profile_id") or "")
            if not profile_id:
                continue
            case_id = str(case.get("case_id") or "")
            by_profile.setdefault(profile_id, []).append(case_id)
            if any(token in case_id for token in ["seek_search_button", "seek_pay_filter"]):
                current_miss_related.setdefault(profile_id, []).append(case_id)
    return {
        "by_profile": by_profile,
        "current_vista_miss_related_by_profile": current_miss_related,
    }


def _score_profile(
    profile: dict[str, Any],
    recorded_breakdown: dict[str, int],
    recorded_cases: dict[str, Any],
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "")
    stage = str(profile.get("intended_pipeline_stage") or "")
    max_parameters_b = profile.get("max_parameters_b")
    priority = profile.get("experiment_priority")
    recorded_count = recorded_breakdown.get(profile_id, 0)
    current_miss_cases = (recorded_cases.get("current_vista_miss_related_by_profile") or {}).get(profile_id, [])
    stage_score = {
        "roi_grounding": 100,
        "grounding_verifier": 70,
        "parser_provider": 45,
        "whole_screen_understanding": 30,
    }.get(stage, 0)
    size_score = max(0.0, 12.0 - float(max_parameters_b or 12.0))
    priority_score = max(0, 10 - int(priority or 10))
    evidence_score = recorded_count * 20
    miss_score = len(current_miss_cases) * 25
    selection_score = round(stage_score + size_score + priority_score + evidence_score + miss_score, 3)
    return {
        "profile_id": profile_id,
        "model_id": profile.get("model_id") or "",
        "model_family": profile.get("model_family") or "",
        "max_parameters_b": max_parameters_b,
        "intended_pipeline_stage": stage,
        "grounding_role": profile.get("grounding_role") or "",
        "output_contract": profile.get("output_contract") or "",
        "coordinate_output": profile.get("coordinate_output") or "",
        "candidate_source_url": profile.get("candidate_source_url") or "",
        "readiness_status": profile.get("readiness_status") or "",
        "blockers": profile.get("blockers") or [],
        "recorded_evidence_count": recorded_count,
        "current_vista_miss_related_cases": current_miss_cases,
        "selection_score": selection_score,
        "score_factors": {
            "stage_score": stage_score,
            "size_score": size_score,
            "priority_score": priority_score,
            "recorded_evidence_score": evidence_score,
            "current_miss_score": miss_score,
        },
        "recommended_next_action": _profile_next_action(profile, recorded_count, current_miss_cases),
    }


def _profile_next_action(profile: dict[str, Any], recorded_count: int, current_miss_cases: list[str]) -> str:
    profile_id = str(profile.get("profile_id") or "")
    if profile.get("intended_pipeline_stage") == "roi_grounding":
        if current_miss_cases:
            return f"make {profile_id} launchable first for current VISTA miss reproduction"
        if recorded_count:
            return f"make {profile_id} launchable for low-cost ROI grounding actual-call smoke"
        return f"download/start {profile_id} only after higher-evidence ROI profiles are tested"
    return f"defer {profile_id}; useful later, but not the first ROI point-grounding replacement"


def _fast_probe_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    roi_candidates = [item for item in candidates if item.get("intended_pipeline_stage") == "roi_grounding"]
    if not roi_candidates:
        return None
    return sorted(
        roi_candidates,
        key=lambda item: (float(item.get("max_parameters_b") or 999), -int(item.get("recorded_evidence_count") or 0), item["profile_id"]),
    )[0]


def _next_command_hint(primary: dict[str, Any] | None) -> str:
    if not primary:
        return "No download candidate found; inspect readiness report first."
    return (
        "After the selected profile is downloaded and endpoint is wired, run: "
        "uv run python scripts\\run_learn_recognition_grounding_model_matrix.py "
        "--manifest artifacts\\benchmarks\\learn_recognition_golden_manifest_v1.json "
        "--cases-json artifacts\\benchmarks\\learn_recognition_alternative_grounding_candidates_v1.json "
        "--out logs\\benchmarks\\learn_recognition_grounding_model_matrix_next "
        "--model-profile learn_grounding_vista_4b_baseline "
        f"--model-profile {primary['profile_id']} --timeout-seconds 60 --json"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness", default=str(DEFAULT_READINESS_PATH))
    parser.add_argument("--evidence", action="append", default=None)
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_learn_recognition_next_model_selection(
        readiness_path=args.readiness,
        evidence_paths=args.evidence,
        out=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
