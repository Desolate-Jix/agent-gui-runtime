"""在原执行 owner 线程读取当前窗口、截图与所需 UIA 控件。"""
from __future__ import annotations

from hashlib import sha256
from math import isfinite
import ntpath
from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.agent.native_identity import WindowsNativeIdentityReader
from app.core.screenshot import ScreenshotService
from app.operation.screen_reading.uia_provider import WindowsUIAProvider


def _window_class(handle):
    try:
        import win32gui
        value = win32gui.GetClassName(handle)
        return value if isinstance(value, str) and value else None
    except (ImportError, OSError, ValueError):
        return None


def _bound(manager, handle, pid):
    bound = manager.get_bound_window()
    if (bound is None or getattr(bound, "handle", None) != handle
            or getattr(bound, "process_id", None) != pid):
        raise ValueError("memory_observation_window_binding_changed")
    rect = bound.rect
    geometry = (rect.left, rect.top, rect.right, rect.bottom)
    if any(type(value) is not int for value in geometry) or rect.right <= rect.left or rect.bottom <= rect.top:
        raise ValueError("memory_observation_window_rect_invalid")
    return bound, geometry


def _identity(reader, handle, pid):
    value = reader.read_identity(handle)
    if (not isinstance(value, dict) or value.get("status") != "observed"
            or value.get("target_window_handle") != handle or value.get("process_id") != pid
            or type(value.get("process_create_time")) not in (int, float)
            or not isfinite(value["process_create_time"]) or value["process_create_time"] <= 0
            or not isinstance(value.get("executable_path"), str)):
        raise ValueError("memory_observation_native_identity_unavailable")
    executable = ntpath.basename(value["executable_path"])
    if not executable or executable == value["executable_path"]:
        raise ValueError("memory_observation_executable_invalid")
    return {"handle": handle, "process_id": pid,
            "process_create_time": value["process_create_time"]}, executable


def _image(path, geometry):
    file = Path(path).resolve()
    raw = file.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("memory_observation_png_required")
    with Image.open(file) as image:
        size = {"width": image.width, "height": image.height}
    if size != {"width": geometry[2] - geometry[0], "height": geometry[3] - geometry[1]}:
        raise ValueError("memory_observation_viewport_changed")
    return str(file), sha256(raw).hexdigest(), size


def _needs_uia(recipe):
    if recipe is None:
        return False
    if not isinstance(recipe, dict) or not isinstance(recipe.get("scope"), dict) or not isinstance(recipe.get("strategies"), list):
        raise ValueError("memory_observation_recipe_invalid")
    rows = [*recipe["scope"].get("anchors", []), *recipe["strategies"]]
    return any(isinstance(item, dict) and item.get("kind") in {"uia", "visible_row"} for item in rows)


def capture_memory_observation(coordinator, handle, pid, *, image_path=None, recipe=None):
    if type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0:
        raise ValueError("memory_observation_target_invalid")
    manager = coordinator._windows()
    before, geometry = _bound(manager, handle, pid)
    reader = WindowsNativeIdentityReader(window_manager=manager)
    identity, executable = _identity(reader, handle, pid)
    window_class = _window_class(handle)
    if image_path is None:
        directory = Path(coordinator._runtime_output_root) / "memory-observations" / uuid4().hex
        capture = ScreenshotService(window_manager=manager, capture_dir=directory).capture_window(
            focus_window=False, purpose="memory-current-observation")
        image_path = capture.get("image_path")
        if not image_path or capture.get("roi") is not None and capture["roi"] != {}:
            raise ValueError("memory_observation_full_capture_required")
    path, digest, size = _image(image_path, geometry)
    capture_id = "memory-capture-" + uuid4().hex
    frame = {"capture_id": capture_id, "image_path": path, "sha256": digest, "image_size": size,
             "window_identity": identity, "window_rect": list(geometry),
             "application": {"executable_name": executable}}
    if window_class:
        frame["application"]["window_class"] = window_class
    if _needs_uia(recipe):
        snapshot = WindowsUIAProvider().snapshot_window(before)
        if (isinstance(snapshot, dict) and snapshot.get("status") == "ok"
                and snapshot.get("scan_complete") is True and snapshot.get("truncated") is False):
            snapshot = {**snapshot, "capture_id": capture_id, "window_identity": identity}
            uia = {"status": "ok", "capture_id": capture_id,
                   "window_identity": identity, "snapshot": snapshot}
        else:
            uia = {"status": "unavailable", "capture_id": capture_id,
                   "window_identity": identity, "reason": (snapshot or {}).get("reason", "uia_incomplete")
                   if isinstance(snapshot, dict) else "uia_invalid"}
    else:
        uia = {"status": "not_required"}
    _, after_geometry = _bound(manager, handle, pid)
    after_identity, after_executable = _identity(reader, handle, pid)
    if (after_geometry != geometry or after_identity != identity or after_executable != executable
            or _window_class(handle) != window_class):
        raise ValueError("memory_observation_identity_changed")
    if sha256(Path(path).read_bytes()).hexdigest() != digest:
        raise ValueError("memory_observation_capture_changed")
    return frame, {"uia": uia}


__all__ = ["capture_memory_observation"]
