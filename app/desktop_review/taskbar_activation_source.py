from __future__ import annotations

import hashlib
import json
import time
import re
from pathlib import Path
from typing import Any, Mapping


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def build_taskbar_activation_evidence(*, captured_at_monotonic: float, capture_id: str, image_path: str, image_sha256: str,
    desktop_rect: dict, taskbar: dict, destination: dict, source_foreground: dict, selected_button: dict) -> dict:
    if taskbar.get("class_name") not in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"} or not str(taskbar.get("exe", "")).replace("/", "\\").casefold().endswith("\\explorer.exe"):
        raise ValueError("taskbar source rejected non-Explorer taskbar")
    if not selected_button.get("ancestor_control_ids") or selected_button.get("toolbar_control_id") not in selected_button["ancestor_control_ids"]:
        raise ValueError("taskbar source rejected missing toolbar ancestry")
    if selected_button.get("enabled") is not True or selected_button.get("visible") is not True or "Invoke" not in selected_button.get("patterns", []):
        raise ValueError("taskbar source rejected unavailable button")
    box, bar = selected_button["bbox"], taskbar["screen_rect"]
    point = [box["x"] + box["w"] // 2, box["y"] + box["h"] // 2]
    screen = [bar["left"] + point[0], bar["top"] + point[1]]
    if not (0 <= point[0] < bar["width"] and 0 <= point[1] < bar["height"]):
        raise ValueError("taskbar source rejected point outside taskbar")
    selected_button = {**selected_button, "control_type": selected_button.get("control_type", "Button")}
    if not isinstance(selected_button.get('point_visibility'), dict):
        raise ValueError('taskbar source requires observed point ownership')
    result = {"schema": "taskbar_activation_evidence_v1", "captured_at_monotonic": captured_at_monotonic, "capture_id": capture_id, "image_path": image_path, "image_sha256": image_sha256, "desktop_rect": desktop_rect, "taskbar": taskbar, "destination": destination, "source_foreground": source_foreground, "selected_button": selected_button, "running_window_count": 1, "matched_button_count": 1, "window_point": point, "screen_point": screen}
    stable = {k: result[k] for k in ("taskbar", "destination", "selected_button", "window_point", "screen_point")}
    result["candidate_id"] = _hash(stable)
    result["source_sha256"] = _hash(result)
    return result


class WindowsTaskbarActivationSource:
    def __init__(self, *, output_dir: Path, destination_window_handle: int, destination_process_id: int) -> None:
        self.output_dir, self.destination_window_handle, self.destination_process_id = Path(output_dir), destination_window_handle, destination_process_id
        self._destination_identity: dict | None = None

    def observe(self) -> dict:
        try:
            import psutil
            import win32gui
            import win32process
            from app.core.screenshot import Image, mss
            from app.core.window_manager import BoundWindow, WindowRect
            from app.operation.screen_reading.uia_provider import WindowsUIAProvider
        except Exception as error:
            raise RuntimeError("taskbar activation Windows dependencies are unavailable") from error
        if not win32gui.IsWindow(self.destination_window_handle):
            raise ValueError("taskbar activation destination window is unavailable")
        if win32process.GetWindowThreadProcessId(self.destination_window_handle)[1] != self.destination_process_id:
            raise ValueError("taskbar activation destination process changed")
        destinations: list[int] = []
        def _window(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == self.destination_process_id:
                destinations.append(hwnd)
        win32gui.EnumWindows(_window, None)
        if destinations != [self.destination_window_handle]:
            raise ValueError("taskbar activation destination has multiple windows")
        bars: list[int] = []
        def _bar(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) in {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
                bars.append(hwnd)
        win32gui.EnumWindows(_bar, None)
        if len(bars) != 1:
            raise ValueError("taskbar activation taskbar is ambiguous")
        bar = bars[0]; rect = win32gui.GetWindowRect(bar); bar_pid = win32process.GetWindowThreadProcessId(bar)[1]
        bar_process, dest_process = psutil.Process(bar_pid), psutil.Process(self.destination_process_id)
        import win32api
        if Path(bar_process.exe()).resolve() != (Path(win32api.GetWindowsDirectory()) / 'explorer.exe').resolve():
            raise ValueError('taskbar activation Explorer executable identity differs')
        captured_at = time.monotonic()
        bound = BoundWindow(bar, win32gui.GetWindowText(bar), bar_pid, bar_process.name(), WindowRect(*rect), False)
        snapshot = WindowsUIAProvider().snapshot_window(bound)
        if snapshot.get("status") != "ok":
            raise ValueError("taskbar activation UIA snapshot is unavailable")
        title = win32gui.GetWindowText(self.destination_window_handle)
        controls = snapshot.get("controls", [])
        toolbars = [c for c in controls if c.get("class_name") == "MSTaskListWClass"]
        if len(toolbars) != 1:
            raise ValueError("taskbar activation task list is ambiguous")
        toolbar = toolbars[0]
        runtime = toolbar.get('runtime_id')
        if not isinstance(runtime, list) or len(runtime) != 2 or runtime[0] != 42 or type(runtime[1]) is not int:
            raise ValueError('taskbar activation toolbar HWND is unavailable')
        toolbar_handle = runtime[1]
        if (win32gui.GetClassName(toolbar_handle) != 'MSTaskListWClass'
                or win32gui.GetAncestor(toolbar_handle, 2) != bar
                or win32process.GetWindowThreadProcessId(toolbar_handle)[1] != bar_pid):
            raise ValueError('taskbar activation toolbar native identity differs')
        pattern = re.compile(re.escape(title) + r' - 1 (?:个运行窗口|running window)', re.IGNORECASE)
        matches = [c for c in controls if c.get("control_type") == "Button" and toolbar["control_id"] in c.get("ancestor_control_ids", []) and title and pattern.fullmatch(str(c.get("name") or ""))]
        if len(matches) != 1:
            raise ValueError("taskbar activation button is ambiguous")
        box = matches[0]['bbox']
        point = (rect[0] + box['x'] + box['w'] // 2, rect[1] + box['y'] + box['h'] // 2)
        hit = int(win32gui.WindowFromPoint(point) or 0)
        root = int(win32gui.GetAncestor(hit, 2) or hit) if hit else 0
        if root != bar or hit not in {bar, toolbar_handle}:
            raise ValueError('taskbar activation point is obstructed')
        visibility = {'kind': 'taskbar_button', 'hit_handle': hit, 'hit_root_handle': root, 'owner_handle': bar}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with mss() as capture:
            monitor = dict(capture.monitors[0]); raw = capture.grab(monitor)
            image = self.output_dir / ("taskbar-" + str(time.time_ns()) + ".png")
            Image.frombytes("RGB", raw.size, raw.rgb).save(image)
        foreground = win32gui.GetForegroundWindow()
        def _identity(hwnd: int) -> dict:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]; proc = psutil.Process(pid)
            return {"handle": hwnd, "pid": pid, "exe": proc.exe(), "create_time": proc.create_time(), "title": win32gui.GetWindowText(hwnd)}
        evidence = build_taskbar_activation_evidence(captured_at_monotonic=captured_at, capture_id=hashlib.sha256(image.read_bytes()).hexdigest()[:32],
            image_path=str(image), image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(), desktop_rect=monitor,
            taskbar={"handle": bar, "class_name": win32gui.GetClassName(bar), "pid": bar_pid, "exe": bar_process.exe(), "create_time": bar_process.create_time(), "screen_rect": {"left": rect[0], "top": rect[1], "width": rect[2]-rect[0], "height": rect[3]-rect[1]}},
            destination=_identity(self.destination_window_handle), source_foreground=_identity(foreground),
            selected_button={**matches[0], 'point_visibility': visibility, 'toolbar_handle': toolbar_handle,
                'toolbar_class_name': 'MSTaskListWClass', "toolbar_control_id": toolbar["control_id"], "toolbar_runtime_id": toolbar.get("runtime_id")})
        hit = int(win32gui.WindowFromPoint(tuple(evidence["screen_point"])) or 0)
        root = int(win32gui.GetAncestor(hit, 2) or hit) if hit else 0
        if root != bar or hit not in {bar, toolbar_handle}:
            raise ValueError("taskbar activation point is obstructed")
        evidence["selected_button"]["point_visibility"] = {
            "kind": "taskbar_button", "hit_handle": hit, "hit_root_handle": root, "owner_handle": bar,
        }
        stable = {k: evidence[k] for k in ("taskbar", "destination", "selected_button", "window_point", "screen_point")}
        evidence["candidate_id"] = _hash(stable)
        unhashed = dict(evidence); unhashed.pop("source_sha256", None)
        evidence["source_sha256"] = _hash(unhashed)
        identity = {k: evidence['destination'][k] for k in ('handle', 'pid', 'exe', 'create_time')}
        if self._destination_identity is not None and identity != self._destination_identity:
            raise ValueError('taskbar activation destination identity changed')
        self._destination_identity = identity
        return evidence

    __call__ = observe

    def read_destination_foreground(self) -> dict:
        try:
            import psutil, win32gui, win32process
            hwnd = self.destination_window_handle; pid = win32process.GetWindowThreadProcessId(hwnd)[1]; proc = psutil.Process(pid)
            fact = {"handle": hwnd, "pid": pid, "exe": proc.exe(), "create_time": proc.create_time()}
            if self._destination_identity is None or fact != self._destination_identity:
                raise RuntimeError("taskbar activation destination identity changed")
            return {**fact, "is_foreground": win32gui.GetForegroundWindow() == hwnd}
        except Exception as error:
            raise RuntimeError("taskbar activation destination foreground read failed") from error
