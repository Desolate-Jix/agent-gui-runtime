"""冻结每个宿主的非秘密判断策略，回读结果不受外部配置改动影响。"""
from pathlib import Path

from app.judgment import DecisionService, load_decision_profile


PROFILE_SNAPSHOT = "decision-profile.snapshot.json"


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
