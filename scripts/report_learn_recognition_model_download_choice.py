from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UGROUND_2B_MATERIALIZATION = (
    PROJECT_ROOT
    / "logs"
    / "benchmarks"
    / "learn_recognition_model_materialization_uground2b_remote"
    / "materialization_report.json"
)
DEFAULT_UGROUND_7B_MATERIALIZATION = (
    PROJECT_ROOT
    / "logs"
    / "benchmarks"
    / "learn_recognition_model_materialization_uground7b_remote"
    / "materialization_report.json"
)
DEFAULT_SELECTION_REPORT = (
    PROJECT_ROOT
    / "logs"
    / "benchmarks"
    / "learn_recognition_next_model_selection_v1"
    / "next_model_selection_report.json"
)


def build_learn_recognition_model_download_choice_report(
    *,
    uground2b_materialization_path: str | Path = DEFAULT_UGROUND_2B_MATERIALIZATION,
    uground7b_materialization_path: str | Path = DEFAULT_UGROUND_7B_MATERIALIZATION,
    selection_report_path: str | Path = DEFAULT_SELECTION_REPORT,
    out: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    materialization_reports = [
        _summarize_materialization(_read_json(Path(uground2b_materialization_path))),
        _summarize_materialization(_read_json(Path(uground7b_materialization_path))),
    ]
    selection_report = _read_json_if_exists(Path(selection_report_path))
    risk_first = _risk_first_recommendation(materialization_reports)
    quality_first = _quality_first_recommendation(materialization_reports, selection_report)
    report = {
        "contract_version": "learn_recognition_model_download_choice_v1",
        "source_reports": {
            "uground_2b_materialization": str(Path(uground2b_materialization_path)),
            "uground_7b_materialization": str(Path(uground7b_materialization_path)),
            "next_model_selection": str(Path(selection_report_path)),
            "next_model_selection_found": bool(selection_report),
        },
        "candidate_count": len(materialization_reports),
        "candidates": materialization_reports,
        "risk_first_recommendation": risk_first,
        "quality_first_recommendation": quality_first,
        "recommended_sequence": _recommended_sequence(risk_first, quality_first),
        "decision_boundary": {
            "choose_risk_first_when": [
                "disk space or startup risk is the immediate constraint",
                "the next objective is adapter launchability and health-check smoke",
                "a smaller model is enough to prove the UGround integration path before spending larger disk",
            ],
            "choose_quality_first_when": [
                "the next objective is to challenge the current VISTA small-control grounding miss",
                "download time and disk risk are acceptable",
                "the run will use the fixed grounding matrix and keep Validator thresholds unchanged",
            ],
        },
        "anti_inflation": {
            "not_accuracy": True,
            "not_model_ability_proof": True,
            "not_execute_authorization": True,
            "not_live_click_or_submit": True,
            "not_profile_promotion": True,
            "interpretation": (
                "download choice report only; it compares setup risk and planned evaluation order, "
                "not model accuracy, live click success, or Learn Recognition reliability"
            ),
        },
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


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path)


def _summarize_materialization(report: dict[str, Any]) -> dict[str, Any]:
    remote = report.get("remote_model_summary") if isinstance(report.get("remote_model_summary"), dict) else {}
    disk = report.get("disk_space") if isinstance(report.get("disk_space"), dict) else {}
    return {
        "profile_id": report.get("profile_id") or "",
        "model_id": report.get("model_id") or "",
        "max_parameters_b": report.get("max_parameters_b"),
        "materialization_status": report.get("materialization_status") or "",
        "blockers": list(report.get("blockers") or []),
        "planned_model_dir": report.get("planned_model_dir") or "",
        "planned_endpoint": report.get("planned_endpoint") or "",
        "preferred_download_total_gb": disk.get("preferred_download_total_gb")
        if disk.get("preferred_download_total_gb") is not None
        else remote.get("preferred_download_total_gb"),
        "known_total_gb": remote.get("known_total_gb"),
        "free_gb": disk.get("free_gb"),
        "free_after_preferred_gb": disk.get("free_after_preferred_gb"),
        "download_requested": bool(report.get("download_requested")),
        "remote_inspection_requested": bool(report.get("remote_inspection_requested")),
        "dependency_probe": report.get("dependency_probe") or {},
        "anti_inflation": report.get("anti_inflation") or {},
    }


def _risk_first_recommendation(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            _none_last_float(item.get("preferred_download_total_gb")),
            _none_last_float(item.get("max_parameters_b")),
            str(item.get("profile_id") or ""),
        ),
    )
    chosen = ranked[0] if ranked else {}
    return {
        "profile_id": chosen.get("profile_id") or "",
        "model_id": chosen.get("model_id") or "",
        "reason": "smallest preferred safetensors-first download and lower local startup risk",
        "preferred_download_total_gb": chosen.get("preferred_download_total_gb"),
        "free_after_preferred_gb": chosen.get("free_after_preferred_gb"),
        "intended_use": "launchability_smoke_before_larger_quality_probe",
    }


def _quality_first_recommendation(
    candidates: list[dict[str, Any]], selection_report: dict[str, Any]
) -> dict[str, Any]:
    primary = selection_report.get("primary_recommendation")
    primary_profile_id = ""
    reason = "next-model selection primary recommendation"
    if isinstance(primary, dict):
        primary_profile_id = str(primary.get("profile_id") or "")
        reason = str(primary.get("reason") or reason)
    chosen = next((item for item in candidates if item.get("profile_id") == primary_profile_id), None)
    if not chosen:
        chosen = max(candidates, key=lambda item: _zero_float(item.get("max_parameters_b")), default={})
        reason = "fallback largest UGround candidate when selection report is unavailable"
    return {
        "profile_id": chosen.get("profile_id") or "",
        "model_id": chosen.get("model_id") or "",
        "reason": reason,
        "preferred_download_total_gb": chosen.get("preferred_download_total_gb"),
        "free_after_preferred_gb": chosen.get("free_after_preferred_gb"),
        "intended_use": "fixed_grounding_matrix_quality_probe_after_materialization",
    }


def _recommended_sequence(risk_first: dict[str, Any], quality_first: dict[str, Any]) -> list[str]:
    risk_profile = risk_first.get("profile_id") or "risk-first profile"
    quality_profile = quality_first.get("profile_id") or "quality-first profile"
    return [
        f"materialize {risk_profile} first if the next checkpoint is low-risk adapter launchability",
        "run materialization dry-run again after files exist; do not patch profile before server health",
        f"materialize {quality_profile} next if the goal is to test whether UGround improves the current VISTA misses",
        "rerun readiness and the fixed 8-case grounding matrix with VISTA baseline plus the materialized profile",
        "keep reports layered; no 90% or reliability claim until actual model calls on independent cases support it",
    ]


def _none_last_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float("inf")


def _zero_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uground2b-materialization", default=str(DEFAULT_UGROUND_2B_MATERIALIZATION))
    parser.add_argument("--uground7b-materialization", default=str(DEFAULT_UGROUND_7B_MATERIALIZATION))
    parser.add_argument("--selection-report", default=str(DEFAULT_SELECTION_REPORT))
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_learn_recognition_model_download_choice_report(
        uground2b_materialization_path=args.uground2b_materialization,
        uground7b_materialization_path=args.uground7b_materialization,
        selection_report_path=args.selection_report,
        out=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
