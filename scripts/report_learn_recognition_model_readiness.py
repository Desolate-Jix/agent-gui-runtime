from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = PROJECT_ROOT / "configs" / "model_profiles"


def build_learn_recognition_model_readiness(
    *,
    profile_dir: str | Path = PROFILE_DIR,
    out: str | Path | None = None,
    include_vista_baseline: bool = True,
    json_stdout: bool = False,
) -> dict[str, Any]:
    profile_dir = Path(profile_dir)
    profile_paths = sorted(profile_dir.glob("learn_mode_*.json"))
    if include_vista_baseline:
        vista_path = profile_dir / "learn_grounding_vista_4b_baseline.json"
        if vista_path.exists():
            profile_paths.append(vista_path)
    profiles = [_profile_readiness(path) for path in profile_paths]
    report = {
        "contract_version": "learn_recognition_model_readiness_report_v1",
        "profile_dir": str(profile_dir),
        "profile_count": len(profiles),
        "readiness_summary": _summary(profiles),
        "profiles": profiles,
        "recommended_next_actions": _recommended_next_actions(profiles),
        "interpretation": (
            "readiness report only; it does not download models, start services, run actual grounding, "
            "or prove recognition accuracy"
        ),
    }
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _profile_readiness(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8-sig"))
    profile_id = str(profile.get("profile_id") or path.stem)
    model_path = str(profile.get("model_path") or "").strip()
    mmproj_path = str(profile.get("mmproj_path") or "").strip()
    endpoint = str(profile.get("endpoint") or "").strip()
    download_status = str(profile.get("download_status") or "").strip()
    launchable = bool(profile.get("launchable"))
    model_path_exists = _path_exists(model_path)
    mmproj_required = bool(mmproj_path)
    mmproj_path_exists = _path_exists(mmproj_path) if mmproj_required else None
    readiness_status, blockers = _readiness_status(
        download_status=download_status,
        launchable=launchable,
        endpoint=endpoint,
        model_path=model_path,
        model_path_exists=model_path_exists,
        mmproj_required=mmproj_required,
        mmproj_path_exists=mmproj_path_exists,
    )
    return {
        "profile_id": profile_id,
        "label": profile.get("label") or profile_id,
        "model_id": profile.get("model_id") or "",
        "model_family": profile.get("model_family") or "",
        "max_parameters_b": profile.get("max_parameters_b"),
        "experiment_priority": profile.get("experiment_priority"),
        "mode_scope": profile.get("mode_scope") or "",
        "intended_pipeline_stage": profile.get("intended_pipeline_stage") or "",
        "parser_role": profile.get("parser_role"),
        "grounding_role": profile.get("grounding_role"),
        "input_contract": profile.get("input_contract") or "",
        "output_contract": profile.get("output_contract") or "",
        "coordinate_output": profile.get("coordinate_output") or "",
        "download_status": download_status,
        "launchable": launchable,
        "endpoint": endpoint,
        "endpoint_present": bool(endpoint),
        "model_path": model_path,
        "model_path_exists": model_path_exists,
        "mmproj_path": mmproj_path,
        "mmproj_path_exists": mmproj_path_exists,
        "candidate_source_url": profile.get("candidate_source_url") or "",
        "artifact_is_authorization": bool(profile.get("artifact_is_authorization")),
        "execute_binding_enabled": bool(profile.get("execute_binding_enabled")),
        "final_submit_forbidden": bool(profile.get("final_submit_forbidden")),
        "readiness_status": readiness_status,
        "blockers": blockers,
        "next_action": _next_action(readiness_status, blockers, profile),
    }


def _readiness_status(
    *,
    download_status: str,
    launchable: bool,
    endpoint: str,
    model_path: str,
    model_path_exists: bool | None,
    mmproj_required: bool,
    mmproj_path_exists: bool | None,
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    normalized_status = download_status.casefold()
    if normalized_status in {"", "not_downloaded", "metadata_only", "planned", "todo"}:
        blockers.append("model_not_downloaded")
    if not launchable:
        blockers.append("profile_not_launchable")
    if not endpoint:
        blockers.append("endpoint_missing")
    if model_path and model_path_exists is False:
        blockers.append("model_path_missing")
    if mmproj_required and mmproj_path_exists is False:
        blockers.append("mmproj_path_missing")
    if blockers:
        if "model_not_downloaded" in blockers:
            return "download_or_setup_required", blockers
        return "blocked_until_profile_fixed", blockers
    return "actual_call_ready", blockers


def _next_action(readiness_status: str, blockers: list[str], profile: dict[str, Any]) -> str:
    if readiness_status == "actual_call_ready":
        return "can be added to actual parser/grounding matrix; still requires benchmark evidence before promotion"
    if "model_not_downloaded" in blockers:
        source = str(profile.get("candidate_source_url") or "").strip()
        return f"download and wire this profile before actual calls; source={source or 'not specified'}"
    if "endpoint_missing" in blockers:
        return "add/start an OpenAI-compatible endpoint before actual calls"
    if "profile_not_launchable" in blockers:
        return "set launchable only after model path and endpoint are verified"
    return "repair profile metadata before using it in model experiments"


def _summary(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    for profile in profiles:
        status = str(profile.get("readiness_status") or "unknown")
        stage = str(profile.get("intended_pipeline_stage") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_stage[stage] = by_stage.get(stage, 0) + 1
    return {
        "by_status": by_status,
        "by_stage": by_stage,
        "actual_call_ready_profiles": [
            profile["profile_id"] for profile in profiles if profile.get("readiness_status") == "actual_call_ready"
        ],
        "download_or_setup_required_profiles": [
            profile["profile_id"] for profile in profiles if profile.get("readiness_status") != "actual_call_ready"
        ],
    }


def _recommended_next_actions(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "profile_id": profile["profile_id"],
            "readiness_status": profile["readiness_status"],
            "next_action": profile["next_action"],
        }
        for profile in sorted(profiles, key=lambda item: (item.get("readiness_status") != "actual_call_ready", item.get("experiment_priority") or 999))
    ]


def _path_exists(path_value: str) -> bool | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.exists()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR))
    parser.add_argument("--out")
    parser.add_argument("--exclude-vista-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_learn_recognition_model_readiness(
        profile_dir=args.profile_dir,
        out=args.out,
        include_vista_baseline=not args.exclude_vista_baseline,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
