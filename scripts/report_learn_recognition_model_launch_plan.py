from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = PROJECT_ROOT / "configs" / "model_profiles"
DEFAULT_SELECTION_PATH = (
    PROJECT_ROOT
    / "logs"
    / "benchmarks"
    / "learn_recognition_next_model_selection_v1"
    / "next_model_selection_report.json"
)
DEFAULT_TARGET_PROFILE_ID = "learn_mode_uground_7b"

PLANNED_LOCAL_DIRS = {
    "learn_mode_uground_7b": "models/uground-v1-7b",
    "learn_mode_uground_2b": "models/uground-v1-2b",
}

PLANNED_ENDPOINTS = {
    "learn_mode_uground_7b": "http://127.0.0.1:1246/v1/chat/completions",
    "learn_mode_uground_2b": "http://127.0.0.1:1245/v1/chat/completions",
}

PLANNED_PID_FILES = {
    "learn_mode_uground_7b": "logs/learn-mode-uground-7b-server.pid",
    "learn_mode_uground_2b": "logs/learn-mode-uground-2b-server.pid",
}


def build_learn_recognition_model_launch_plan(
    *,
    profile_id: str | None = None,
    profile_dir: str | Path = PROFILE_DIR,
    selection_path: str | Path | None = DEFAULT_SELECTION_PATH,
    project_root: str | Path = PROJECT_ROOT,
    out: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root)
    selection = _read_json_if_exists(selection_path) if selection_path else {}
    target_profile_id = profile_id or _selection_target_profile_id(selection) or DEFAULT_TARGET_PROFILE_ID
    profile_path = Path(profile_dir) / f"{target_profile_id}.json"
    profile = _read_json(profile_path)
    planned_local_dir = PLANNED_LOCAL_DIRS.get(target_profile_id) or f"models/{target_profile_id}"
    planned_endpoint = PLANNED_ENDPOINTS.get(target_profile_id) or str(profile.get("endpoint") or "")
    planned_pid_file = PLANNED_PID_FILES.get(target_profile_id) or f"logs/{target_profile_id}-server.pid"
    model_files_exist = _path_has_files(root / planned_local_dir)
    adapter_path = root / "scripts" / "model_servers" / "uground_openai_server.py"
    start_script_path = root / "scripts" / "model_servers" / "start_uground_vision_server.ps1"
    dependency_probe = _dependency_probe()

    blockers = _launch_blockers(
        profile=profile,
        planned_local_dir=planned_local_dir,
        model_files_exist=model_files_exist,
        adapter_path=adapter_path,
        start_script_path=start_script_path,
        planned_endpoint=planned_endpoint,
    )
    report = {
        "contract_version": "learn_recognition_model_launch_plan_v1",
        "target_profile_id": target_profile_id,
        "profile_path": str(profile_path),
        "selected_from_report": str(selection_path) if selection_path else "",
        "selection_report_found": bool(selection),
        "model_id": profile.get("model_id") or "",
        "model_family": profile.get("model_family") or "",
        "max_parameters_b": profile.get("max_parameters_b"),
        "candidate_source_url": profile.get("candidate_source_url") or "",
        "mode_scope": profile.get("mode_scope") or "",
        "intended_pipeline_stage": profile.get("intended_pipeline_stage") or "",
        "input_contract": profile.get("input_contract") or "",
        "output_contract": profile.get("output_contract") or "",
        "coordinate_output": profile.get("coordinate_output") or "",
        "current_profile_state": {
            "download_status": profile.get("download_status") or "",
            "launchable": bool(profile.get("launchable")),
            "model_path": profile.get("model_path") or "",
            "endpoint": profile.get("endpoint") or "",
            "provider_mode": profile.get("provider_mode") or "",
        },
        "planned_runtime_materialization": {
            "planned_local_model_dir": planned_local_dir,
            "planned_endpoint": planned_endpoint,
            "planned_start_script": "scripts/model_servers/start_uground_vision_server.ps1",
            "planned_server_adapter": "scripts/model_servers/uground_openai_server.py",
            "planned_pid_file": planned_pid_file,
            "model_files_exist": model_files_exist,
            "server_adapter_exists": adapter_path.exists(),
            "start_script_exists": start_script_path.exists(),
            "dependency_probe": dependency_probe,
        },
        "official_source_summary": {
            "model_card": _huggingface_model_card(profile.get("model_id") or ""),
            "official_repository": "https://github.com/OSU-NLP-Group/UGround",
            "official_vllm_command": f"vllm serve {profile.get('model_id') or target_profile_id} --api-key token-abc123 --dtype float16",
            "coordinate_contract": "UGround V1 Qwen2-VL output is in [0,1000); restore with x/1000*width and y/1000*height.",
            "prompt_contract": "Return one point (x, y) for the described GUI element; temperature should be zero.",
            "local_adapter_decision": _local_adapter_decision(dependency_probe),
        },
        "readiness_to_launch": {
            "status": "launchable" if not blockers else "not_launchable_yet",
            "blockers": blockers,
        },
        "execute_mode_impact": {
            "changes_execute_defaults": False,
            "execute_binding_enabled": bool(profile.get("execute_binding_enabled")),
            "artifact_is_authorization": bool(profile.get("artifact_is_authorization")),
            "real_action_requires_gate": bool(profile.get("real_action_requires_gate")),
            "final_submit_forbidden": bool(profile.get("final_submit_forbidden")),
            "interpretation": "learn-only launch planning; it must not replace Execute Mode profiles or authorize clicks",
        },
        "recommended_sequence": _recommended_sequence(
            target_profile_id,
            adapter_exists=adapter_path.exists(),
            start_script_exists=start_script_path.exists(),
        ),
        "verification_after_materialization": _verification_after_materialization(target_profile_id),
        "anti_inflation": {
            "not_accuracy": True,
            "not_model_ability_proof": True,
            "not_execute_authorization": True,
            "not_live_click_or_submit": True,
            "report_did_not_mutate_profile": True,
            "profile_currently_launchable": bool(profile.get("launchable")),
            "interpretation": (
                "launch plan report only; it does not download a model, mutate a profile, start a server, "
                "run actual grounding, or prove Learn Recognition reliability"
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


def _read_json_if_exists(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.exists():
        return {}
    return _read_json(candidate)


def _huggingface_model_card(model_id: str) -> str:
    model = str(model_id or "").strip()
    return f"https://huggingface.co/{model}" if model else ""


def _selection_target_profile_id(selection: dict[str, Any]) -> str:
    recommendation = selection.get("primary_recommendation")
    if isinstance(recommendation, dict):
        return str(recommendation.get("profile_id") or "")
    return ""


def _path_has_files(path: Path) -> bool:
    return path.exists() and any(item.is_file() for item in path.rglob("*"))


def _dependency_probe() -> dict[str, bool]:
    return {
        name: importlib.util.find_spec(name) is not None
        for name in ["torch", "transformers", "qwen_vl_utils", "vllm", "sglang"]
    }


def _local_adapter_decision(dependency_probe: dict[str, bool]) -> str:
    if dependency_probe.get("vllm"):
        return "official_vllm_openai_server_available"
    if dependency_probe.get("torch") and dependency_probe.get("transformers"):
        return "use_local_transformers_adapter_until_vllm_is_installed"
    return "runtime_dependencies_missing"


def _launch_blockers(
    *,
    profile: dict[str, Any],
    planned_local_dir: str,
    model_files_exist: bool,
    adapter_path: Path,
    start_script_path: Path,
    planned_endpoint: str,
) -> list[str]:
    blockers: list[str] = []
    if not model_files_exist:
        blockers.append("model_files_missing")
        blockers.append("planned_model_dir_empty")
    if model_files_exist and str(profile.get("download_status") or "").casefold() in {"", "not_downloaded", "metadata_only", "planned"}:
        blockers.append("profile_download_status_not_updated")
    if not adapter_path.exists():
        blockers.append("server_adapter_missing")
    if not start_script_path.exists():
        blockers.append("start_script_missing")
    if not planned_endpoint:
        blockers.append("planned_endpoint_missing")
    if not profile.get("launchable"):
        blockers.append("profile_launchable_false")
    if str(profile.get("model_path") or "").strip() not in {"", planned_local_dir}:
        blockers.append("profile_model_path_differs_from_plan")
    if profile.get("endpoint") and str(profile.get("endpoint")) != planned_endpoint:
        blockers.append("profile_endpoint_differs_from_plan")
    return blockers


def _recommended_sequence(profile_id: str, *, adapter_exists: bool, start_script_exists: bool) -> list[str]:
    steps = [
        f"verify official model files for {profile_id} and place them under the planned local model dir",
    ]
    if adapter_exists:
        steps.append("use the checked-in UGround Transformers adapter; do not reuse the VISTA-specific adapter")
    else:
        steps.append("add a UGround-compatible OpenAI-style server adapter instead of reusing the VISTA-specific adapter")
    if start_script_exists:
        steps.append("use the checked-in start_uground_vision_server.ps1 wrapper after model files exist")
    else:
        steps.append("add a start_uground_vision_server.ps1 wrapper only after the adapter has a working health/check endpoint")
    steps.extend(
        [
            "update the profile to available_local only after local files, endpoint, start script, and pid file are verified",
            "rerun the readiness report and then the fixed 8-case grounding matrix with VISTA baseline plus this profile",
        ]
    )
    return steps


def _verification_after_materialization(profile_id: str) -> dict[str, str]:
    return {
        "readiness": (
            "uv run python scripts\\report_learn_recognition_model_readiness.py "
            "--out logs\\benchmarks\\learn_recognition_model_readiness_after_launch\\model_readiness_report.json --json"
        ),
        "matrix": (
            "uv run python scripts\\run_learn_recognition_grounding_model_matrix.py "
            "--manifest artifacts\\benchmarks\\learn_recognition_golden_manifest_v1.json "
            "--cases-json artifacts\\benchmarks\\learn_recognition_alternative_grounding_candidates_v1.json "
            "--out logs\\benchmarks\\learn_recognition_grounding_model_matrix_after_launch "
            "--model-profile learn_grounding_vista_4b_baseline "
            f"--model-profile {profile_id} --timeout-seconds 60 --json"
        ),
        "no_execute_change_audit": "rg \"DEFAULT_STAGE_PROFILE_IDS|vista_4b_transformers|execute_binding_enabled\" app configs tests",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-id", default=None)
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR))
    parser.add_argument("--selection", default=str(DEFAULT_SELECTION_PATH))
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_learn_recognition_model_launch_plan(
        profile_id=args.profile_id,
        profile_dir=args.profile_dir,
        selection_path=args.selection,
        out=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
