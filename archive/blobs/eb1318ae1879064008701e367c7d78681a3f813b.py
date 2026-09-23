"""观察中断后的只读窗口线索；不绑定、聚焦、截图或重放动作。"""
from app.agent.native_identity import normalize_windows_executable_path


def observe_recovery_windows(manager, identity, *, process_factory=None) -> dict:
    result = {"status": "unavailable", "source": "same_process_visible_windows",
              "candidates": [], "target_in_candidates": None,
              "successor_identity_verified": False, "authorizes_input": False,
              "automatic_retry_allowed": False}
    try:
        if process_factory is None:
            from psutil import Process
            process_factory = Process
        pid = identity["process_id"]

        def same_process():
            process = process_factory(pid)
            return (process.create_time() == identity["process_create_time"]
                    and normalize_windows_executable_path(process.exe()) == identity["executable_path"])

        if not same_process():
            return {**result, "error_code": "recovery_process_identity_changed"}
        candidates = [{"handle": row["handle"], "process_id": pid, "title": row.get("title")}
                      for row in manager.list_visible_windows()
                      if row.get("process_id") == pid and type(row.get("handle")) is int and row["handle"] > 0]
        if not same_process():
            return {**result, "error_code": "recovery_process_identity_changed"}
        return {**result, "status": "candidates_available" if candidates else "no_visible_candidates",
                "candidates": candidates,
                "target_in_candidates": any(row["handle"] == identity["target_window_handle"] for row in candidates)}
    except Exception as error:
        # 诊断失败不能覆盖已返回的动作回执，也不回显私密异常正文。
        return {**result, "error_code": "recovery_observation_failed", "error_type": type(error).__name__}
