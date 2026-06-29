from __future__ import annotations

from pathlib import Path

from app.runtime_architecture.contracts import AppProfile, load_app_profile


APP_PROFILE_DIR = Path("artifacts/app_profiles")


def list_app_profiles(profile_dir: str | Path = APP_PROFILE_DIR) -> list[dict[str, object]]:
    root = Path(profile_dir)
    if not root.exists():
        return []
    profiles: list[dict[str, object]] = []
    for path in sorted(root.glob("*_app_profile_v1.json")):
        try:
            profile = load_app_profile(path)
        except Exception as exc:
            profiles.append(
                {
                    "path": str(path),
                    "valid": False,
                    "error": str(exc),
                }
            )
            continue
        profiles.append(_profile_summary(profile, path))
    return profiles


def get_app_profile(app_id: str, profile_dir: str | Path = APP_PROFILE_DIR) -> tuple[AppProfile, Path]:
    normalized = _normalize_app_id(app_id)
    if not normalized:
        raise ValueError("app_id is required")
    root = Path(profile_dir)
    candidates = [
        root / f"{normalized}_app_profile_v1.json",
        root / f"{normalized}.json",
    ]
    for path in candidates:
        if path.exists():
            return load_app_profile(path), path
    for path in sorted(root.glob("*_app_profile_v1.json")):
        profile = load_app_profile(path)
        if _normalize_app_id(profile.app_id) == normalized:
            return profile, path
    raise FileNotFoundError(f"App profile not found: {app_id}")


def _profile_summary(profile: AppProfile, path: Path) -> dict[str, object]:
    return {
        "contract_version": profile.contract_version,
        "app_id": profile.app_id,
        "display_name": profile.display_name,
        "execution_model": profile.execution_model,
        "profile_role": profile.profile_role,
        "path": str(path),
        "valid": True,
        "operation_skill_count": len(profile.operation_skills),
        "gate_contract_count": len(profile.gate_contracts),
        "workflow_asset_count": len(profile.workflow_assets),
        "learning_asset_count": len(profile.learning_assets),
        "final_submit_default": profile.policy.get("final_submit_default"),
    }


def _normalize_app_id(value: str) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in {"_", "-"})
