from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = PROJECT_ROOT / "configs" / "model_profiles"

PLANNED_LOCAL_DIRS = {
    "learn_mode_uground_7b": "models/uground-v1-7b",
    "learn_mode_uground_2b": "models/uground-v1-2b",
}

PLANNED_ENDPOINTS = {
    "learn_mode_uground_7b": "http://127.0.0.1:1246/v1/chat/completions",
    "learn_mode_uground_2b": "http://127.0.0.1:13245/v1/chat/completions",
}

PLANNED_PID_FILES = {
    "learn_mode_uground_7b": "logs/learn-mode-uground-7b-server.pid",
    "learn_mode_uground_2b": "logs/learn-mode-uground-2b-server.pid",
}

DEFAULT_ALLOW_PATTERNS = [
    "*.json",
    "*.safetensors",
    "*.model",
    "*.txt",
    "*.py",
    "*.md",
    "tokenizer*",
    "vocab.*",
    "merges.txt",
]


def build_model_materialization_report(
    *,
    profile_id: str,
    profile_dir: str | Path = PROFILE_DIR,
    model_dir: str | Path | None = None,
    inspect_remote: bool = False,
    download: bool = False,
    out: str | Path | None = None,
    json_stdout: bool = False,
    remote_info_provider: Callable[[str], dict[str, Any]] | None = None,
    downloader: Callable[[str, Path, list[str]], str] | None = None,
) -> dict[str, Any]:
    profile_path = Path(profile_dir) / f"{profile_id}.json"
    profile = _read_json(profile_path)
    _validate_profile_scope(profile)
    planned_model_dir = Path(model_dir) if model_dir else PROJECT_ROOT / PLANNED_LOCAL_DIRS.get(profile_id, f"models/{profile_id}")
    if not planned_model_dir.is_absolute():
        planned_model_dir = PROJECT_ROOT / planned_model_dir
    model_id = str(profile.get("model_id") or "")
    dependency_probe = _dependency_probe()
    before_local = _local_model_summary(planned_model_dir)
    remote_summary = _remote_summary(
        model_id,
        inspect_remote=inspect_remote,
        provider=remote_info_provider,
        dependency_probe=dependency_probe,
    )
    disk_space = _disk_space_summary(planned_model_dir, remote_summary)
    download_result = _download_model(
        model_id=model_id,
        model_dir=planned_model_dir,
        allow_patterns=DEFAULT_ALLOW_PATTERNS,
        download=download,
        downloader=downloader,
        dependency_probe=dependency_probe,
    )
    after_local = _local_model_summary(planned_model_dir)
    blockers = _materialization_blockers(profile, after_local, dependency_probe)
    patch_proposal = _profile_patch_proposal(profile, profile_id, planned_model_dir, blockers)
    report = {
        "contract_version": "learn_recognition_model_materialization_report_v1",
        "profile_id": profile_id,
        "profile_path": str(profile_path),
        "model_id": model_id,
        "candidate_source_url": profile.get("candidate_source_url") or "",
        "max_parameters_b": profile.get("max_parameters_b"),
        "mode_scope": profile.get("mode_scope") or "",
        "intended_pipeline_stage": profile.get("intended_pipeline_stage") or "",
        "download_requested": download,
        "remote_inspection_requested": inspect_remote,
        "dependency_probe": dependency_probe,
        "planned_model_dir": str(planned_model_dir),
        "planned_endpoint": PLANNED_ENDPOINTS.get(profile_id, ""),
        "planned_start_script": "scripts/model_servers/start_uground_vision_server.ps1",
        "planned_server_adapter": "scripts/model_servers/uground_openai_server.py",
        "planned_pid_file": PLANNED_PID_FILES.get(profile_id, f"logs/{profile_id}-server.pid"),
        "download_allow_patterns": DEFAULT_ALLOW_PATTERNS,
        "disk_space": disk_space,
        "before_local_model_summary": before_local,
        "remote_model_summary": remote_summary,
        "download_result": download_result,
        "after_local_model_summary": after_local,
        "materialization_status": "materialized_candidate" if not blockers else "not_materialized",
        "blockers": blockers,
        "profile_patch_proposal": patch_proposal,
        "next_steps": _next_steps(profile_id, blockers),
        "anti_inflation": {
            "not_accuracy": True,
            "not_model_ability_proof": True,
            "not_execute_authorization": True,
            "not_live_click_or_submit": True,
            "not_profile_promotion": True,
            "interpretation": (
                "materialization report only; model files and profile readiness still require server health and "
                "fixed benchmark evidence before any model ability claim"
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


def _validate_profile_scope(profile: dict[str, Any]) -> None:
    profile_id = str(profile.get("profile_id") or "")
    if profile.get("mode_scope") != "learn_only":
        raise ValueError(f"Refusing to materialize non-learn-only profile: {profile_id}")
    max_parameters_b = profile.get("max_parameters_b")
    if isinstance(max_parameters_b, (int, float)) and max_parameters_b > 12:
        raise ValueError(f"Refusing to materialize profile over 12B parameters: {profile_id}")
    if profile.get("execute_binding_enabled") is not False:
        raise ValueError(f"Refusing profile with execute binding enabled: {profile_id}")
    if profile.get("artifact_is_authorization") is not False:
        raise ValueError(f"Refusing profile that marks artifacts as authorization: {profile_id}")


def _dependency_probe() -> dict[str, bool]:
    return {
        name: importlib.util.find_spec(name) is not None
        for name in ["huggingface_hub", "torch", "transformers", "vllm", "sglang"]
    }


def _local_model_summary(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
    names = {item.name for item in files}
    suffixes = {item.suffix.casefold() for item in files}
    total_bytes = sum(item.stat().st_size for item in files)
    return {
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / 1024**3, 3),
        "has_config_json": "config.json" in names,
        "has_processor_or_preprocessor": bool({"preprocessor_config.json", "processor_config.json"} & names),
        "has_tokenizer_config": "tokenizer_config.json" in names,
        "has_weight_file": bool({".safetensors", ".bin"} & suffixes),
        "sample_files": sorted(str(item.relative_to(path)) for item in files[:12]) if path.exists() else [],
    }


def _disk_space_summary(model_dir: Path, remote_summary: dict[str, Any]) -> dict[str, Any]:
    probe_path = model_dir if model_dir.exists() else model_dir.parent
    while not probe_path.exists() and probe_path != probe_path.parent:
        probe_path = probe_path.parent
    usage = shutil.disk_usage(probe_path if probe_path.exists() else PROJECT_ROOT)
    preferred_bytes = int(remote_summary.get("preferred_download_total_bytes") or 0)
    free_after_preferred = usage.free - preferred_bytes if preferred_bytes else None
    return {
        "probe_path": str(probe_path if probe_path.exists() else PROJECT_ROOT),
        "free_bytes": usage.free,
        "free_gb": round(usage.free / 1024**3, 3),
        "preferred_download_total_bytes": preferred_bytes,
        "preferred_download_total_gb": round(preferred_bytes / 1024**3, 3) if preferred_bytes else None,
        "free_after_preferred_gb": round(free_after_preferred / 1024**3, 3) if free_after_preferred is not None else None,
        "warning": _disk_warning(usage.free, preferred_bytes),
    }


def _disk_warning(free_bytes: int, preferred_bytes: int) -> str:
    if not preferred_bytes:
        return ""
    if preferred_bytes > free_bytes:
        return "preferred download exceeds current free disk space"
    if preferred_bytes > free_bytes * 0.85:
        return "preferred download leaves very little free disk space"
    return ""


def _remote_summary(
    model_id: str,
    *,
    inspect_remote: bool,
    provider: Callable[[str], dict[str, Any]] | None,
    dependency_probe: dict[str, bool],
) -> dict[str, Any]:
    if not inspect_remote:
        return {"status": "skipped", "reason": "remote inspection not requested"}
    if not dependency_probe.get("huggingface_hub"):
        return {"status": "blocked", "reason": "huggingface_hub_missing"}
    try:
        if provider:
            info = provider(model_id)
        else:
            from huggingface_hub import HfApi

            model_info = HfApi().model_info(model_id, files_metadata=True)
            siblings = getattr(model_info, "siblings", []) or []
            info = {
                "files": [
                    {
                        "path": str(getattr(item, "rfilename", "")),
                        "size": getattr(item, "size", None),
                    }
                    for item in siblings
                ]
            }
        files = info.get("files") if isinstance(info.get("files"), list) else []
        known_sizes = [int(item.get("size") or 0) for item in files if isinstance(item, dict) and item.get("size")]
        preferred_files = [
            item
            for item in files
            if isinstance(item, dict) and _allowed_by_patterns(str(item.get("path") or ""), DEFAULT_ALLOW_PATTERNS)
        ]
        preferred_sizes = [int(item.get("size") or 0) for item in preferred_files if item.get("size")]
        return {
            "status": "ok",
            "file_count": len(files),
            "known_total_bytes": sum(known_sizes),
            "known_total_gb": round(sum(known_sizes) / 1024**3, 3),
            "preferred_download_file_count": len(preferred_files),
            "preferred_download_total_bytes": sum(preferred_sizes),
            "preferred_download_total_gb": round(sum(preferred_sizes) / 1024**3, 3),
            "sample_files": [str(item.get("path") or "") for item in files[:20] if isinstance(item, dict)],
            "preferred_sample_files": [str(item.get("path") or "") for item in preferred_files[:20]],
            "size_warning": "remote sizes can be incomplete; verify disk space before --download",
        }
    except Exception as exc:
        return {"status": "failed", "error_type": exc.__class__.__name__, "error": str(exc)}


def _allowed_by_patterns(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _download_model(
    *,
    model_id: str,
    model_dir: Path,
    allow_patterns: list[str],
    download: bool,
    downloader: Callable[[str, Path, list[str]], str] | None,
    dependency_probe: dict[str, bool],
) -> dict[str, Any]:
    if not download:
        return {"status": "skipped", "reason": "download flag not set", "writes": 0}
    if not dependency_probe.get("huggingface_hub"):
        return {"status": "blocked", "reason": "huggingface_hub_missing", "writes": 0}
    model_dir.mkdir(parents=True, exist_ok=True)
    try:
        if downloader:
            resolved = downloader(model_id, model_dir, allow_patterns)
        else:
            from huggingface_hub import snapshot_download

            resolved = snapshot_download(
                repo_id=model_id,
                local_dir=str(model_dir),
                allow_patterns=allow_patterns,
            )
        return {"status": "downloaded", "local_dir": str(resolved), "writes": 1, "allow_patterns": allow_patterns}
    except Exception as exc:
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "writes": 0,
            "allow_patterns": allow_patterns,
        }


def _materialization_blockers(profile: dict[str, Any], local_summary: dict[str, Any], dependency_probe: dict[str, bool]) -> list[str]:
    blockers: list[str] = []
    if not dependency_probe.get("torch") or not dependency_probe.get("transformers"):
        blockers.append("runtime_dependencies_missing")
    if not local_summary["exists"] or local_summary["file_count"] == 0:
        blockers.append("model_dir_empty")
    if not local_summary["has_config_json"]:
        blockers.append("config_json_missing")
    if not local_summary["has_processor_or_preprocessor"]:
        blockers.append("processor_config_missing")
    if not local_summary["has_weight_file"]:
        blockers.append("weight_file_missing")
    if profile.get("launchable") is not False and not _profile_is_smoke_verified(profile):
        blockers.append("profile_unexpectedly_launchable_before_health_check")
    return blockers


def _profile_patch_proposal(profile: dict[str, Any], profile_id: str, planned_model_dir: Path, blockers: list[str]) -> dict[str, Any]:
    if _profile_is_smoke_verified(profile):
        return {
            "profile_id": profile_id,
            "apply_now": False,
            "safe_to_patch_after_health_check": False,
            "patch": {},
            "reason": "profile already marked smoke-verified; no patch proposal required",
        }
    safe_to_patch_after_health = not blockers
    return {
        "profile_id": profile_id,
        "apply_now": False,
        "safe_to_patch_after_health_check": safe_to_patch_after_health,
        "patch": {
            "provider_mode": "local_grounding",
            "runtime": "transformers",
            "download_status": "available_local_pending_health",
            "model_path": str(planned_model_dir.relative_to(PROJECT_ROOT)) if planned_model_dir.is_relative_to(PROJECT_ROOT) else str(planned_model_dir),
            "endpoint": PLANNED_ENDPOINTS.get(profile_id, ""),
            "start_script": "scripts/model_servers/start_uground_vision_server.ps1",
            "stop_script": "scripts/model_servers/stop_local_vision_server.ps1",
            "pid_file": PLANNED_PID_FILES.get(profile_id, f"logs/{profile_id}-server.pid"),
            "launchable": False,
        },
        "reason": "profile stays non-launchable until model files, server health, and one no-action benchmark smoke are verified",
    }


def _profile_is_smoke_verified(profile: dict[str, Any]) -> bool:
    return (
        str(profile.get("download_status") or "").casefold() == "available_local_smoke_verified"
        and profile.get("launchable") is True
    )


def _next_steps(profile_id: str, blockers: list[str]) -> list[str]:
    if blockers:
        steps = ["resolve materialization blockers before changing the profile"]
        if "model_dir_empty" in blockers or "weight_file_missing" in blockers:
            steps.append(
                f"run this script with --download only when ready to fetch {profile_id} model files into the planned model dir"
            )
        steps.append("rerun materialization report and launch plan after files exist")
        return steps
    return [
        "start UGround server with scripts\\model_servers\\start_uground_vision_server.ps1",
        "check /health and /v1/chat/completions with one saved ROI image",
        "only then patch profile to available_local and rerun readiness + grounding matrix",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-id", default="learn_mode_uground_7b")
    parser.add_argument("--profile-dir", default=str(PROFILE_DIR))
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--inspect-remote", action="store_true")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_model_materialization_report(
        profile_id=args.profile_id,
        profile_dir=args.profile_dir,
        model_dir=args.model_dir,
        inspect_remote=args.inspect_remote,
        download=args.download,
        out=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
