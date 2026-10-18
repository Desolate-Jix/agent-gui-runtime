"""测试启动器只枚举自己拥有的进程树，不按标题猜测目标。"""
from __future__ import annotations
import time


def owned_window_candidates(manager, process, process_factory):
    """Windows venv 启动器可能把实际 Qt 窗口放在子进程中。"""
    owner = process_factory(process.pid)
    process_ids = {owner.pid, *(child.pid for child in owner.children(recursive=True))}
    return [window for window in manager.list_visible_windows()
            if window["process_id"] in process_ids]


def wait_for_owned_capture_visibility(manager, handle, process_id, *, timeout=120.0,
                                      clock=time.monotonic, pause=time.sleep, on_check=None):
    """测试准备只等待确切窗口可截图，不激活、不批准，也不放宽截图保护。"""
    deadline = clock() + timeout
    while True:
        bound = manager.bind_window_by_handle(handle)
        if bound.handle != handle or bound.process_id != process_id:
            raise RuntimeError("fixture_identity_changed")
        rect = {"left": bound.rect.left, "top": bound.rect.top,
                "width": bound.rect.right - bound.rect.left,
                "height": bound.rect.bottom - bound.rect.top}
        check = manager.validate_bound_capture_visibility(bound=bound, rect=rect)
        if on_check is not None:
            on_check(check)
        if isinstance(check, dict) and check.get("allowed") is True:
            return check
        if clock() >= deadline:
            reason = check.get("reason", "capture_visibility_unavailable") if isinstance(check, dict) else "capture_visibility_unavailable"
            raise TimeoutError("fixture_not_ready: " + str(reason))
        pause(0.5)
