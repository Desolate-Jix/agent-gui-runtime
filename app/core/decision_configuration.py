"""冻结每个宿主的非秘密判断策略，回读结果不受外部配置改动影响。"""
from pathlib import Path

from app.judgment import DecisionService, load_decision_profile
from app.judgment.service import decision_profile_sha256, read_decision_budget_status


PROFILE_SNAPSHOT = "decision-profile.snapshot.json"


def read_session_decision_status(session_dir, saved_status):
    status = dict(saved_status)
    if status.get("mode", "off") == "off":
        return status
    unavailable = {"used": None, "remaining": None, "unknown_dispatches": None,
                   "budget_status": "unavailable"}
    try:
        root = Path(session_dir).resolve(strict=True)
        path = root / PROFILE_SNAPSHOT
        if path.is_symlink() or path.resolve(strict=True) != path:
            raise OSError("decision_session_profile_path_invalid")
        profile = load_decision_profile(path)
        expected = {"enabled": profile.mode != "off", "mode": profile.mode,
                    "configured": profile.mode != "off", "contract_version": profile.contract_version,
                    "request_cap": profile.request_cap, "timeout_seconds": profile.timeout_seconds}
        if profile.contract_version == "decision_profile.v2":
            expected.update(profile_sha256=decision_profile_sha256(profile),
                            proactive_review=profile.proactive_review, review_policy=profile.review_policy)
        if any(status.get(key) != value for key, value in expected.items()):
            raise ValueError("decision_session_profile_mismatch")
        # 只更新当前用量；原评估回执的认证预算保持入场快照。
        return {**status, **read_decision_budget_status(root, profile)}
    except (OSError, ValueError, TypeError):
        return {**status, **unavailable}


def freeze_decision_profile(service):
    if not service.enabled:
        return
    path = Path(service.session_dir) / PROFILE_SNAPSHOT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = service.profile.model_dump_json(indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
    except FileExistsError:
        if load_decision_profile(path) != service.profile:
            raise ValueError("decision_session_profile_mismatch") from None


def create_session_decision_service(session_dir, *, profile_path=None):
    service = DecisionService.from_environment(session_dir, profile_path=profile_path)
    try:
        freeze_decision_profile(service)
    except (OSError, ValueError):
        service.close()
        raise
    return service


def close_session_decision_service(service, errors):
    if service is None:
        return
    try:
        service.close()
    except Exception as error:
        # 清理失败进入最终回执，但不能跳过窗口、协调器和采样线程的后续清理。
        errors.append({"operation": "decision_service_close", "error_type": type(error).__name__})
