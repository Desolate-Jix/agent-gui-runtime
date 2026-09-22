"""自动解析当前桌面宿主，复用现有窗口准备及单步执行链。"""


def prepare_desktop_target(coordinator):
    windows = coordinator.discover_applications().get("running_windows", [])
    desktops = [window for window in windows if window.get("window_kind") == "desktop"]
    if len(desktops) != 1:
        raise ValueError("desktop_host_unavailable_or_ambiguous: inspect discover; desktop icons must be available")
    desktop = desktops[0]
    preview = coordinator.preview_selected_window_preparation(
        target_window_handle=desktop["handle"], target_process_id=desktop["process_id"])
    prepared = coordinator.confirm_window_preparation(preview["preparation_id"])
    window = prepared.get("window") or {}
    if (prepared.get("status") != "focused" or window.get("handle") != desktop["handle"]
            or window.get("process_id") != desktop["process_id"]):
        raise ValueError("desktop_host_preparation_unverified: no desktop input dispatched")
    return {"window": window, "preparation_preview": preview, "preparation_result": prepared,
            "binding_mode": "automatic_desktop_host", "caller_window_binding_required": False}
