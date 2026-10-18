"""原生捕获坐标统一为客户区，不能把透明边框后面的别的窗口学进去。"""
from types import SimpleNamespace

from PIL import Image, ImageChops
import pytest

import app.core.window_manager as module
from app.core.window_manager import WindowManager, WindowRect


def _manager(monkeypatch):
    gui = SimpleNamespace(GetWindowRect=lambda h: (822, 389, 1738, 988),
        GetClientRect=lambda h: (0, 0, 900, 560),
        ClientToScreen=lambda h, p: (830 + p[0], 420 + p[1]),
        GetForegroundWindow=lambda: 123)
    monkeypatch.setattr(module, "win32gui", gui)
    monkeypatch.setattr(module, "WINDOWS_BACKEND_AVAILABLE", True)
    manager = WindowManager()
    monkeypatch.setattr(manager, "_get_process_id", lambda h: 456)
    monkeypatch.setattr(manager, "_get_process_name", lambda p: "fixture.exe")
    return manager, gui


def test_bound_capture_and_click_share_exact_client_origin(monkeypatch):
    manager, gui = _manager(monkeypatch)
    bound = manager._build_bound_window(SimpleNamespace(handle=123, window_text=lambda: "fixture"))
    assert bound.rect == WindowRect(830, 420, 1730, 980)
    assert (bound.rect.left + 20, bound.rect.top + 82) == (850, 502)
    assert bound.title == "fixture" and bound.is_active


def test_background_edge_drift_does_not_enter_capture_surface(monkeypatch):
    manager, gui = _manager(monkeypatch)
    bound = manager._build_bound_window(SimpleNamespace(handle=123, window_text=lambda: "fixture"))
    first = Image.new("RGB", (916, 599), "white")
    second = first.copy()
    second.putpixel((90, 598), (0, 0, 0))
    box = (bound.rect.left - 822, bound.rect.top - 389, bound.rect.right - 822, bound.rect.bottom - 389)
    assert ImageChops.difference(first.crop(box), second.crop(box)).getbbox() is None
    second.putpixel((40, 140), (0, 0, 0))
    assert ImageChops.difference(first.crop(box), second.crop(box)).getbbox() is not None


def test_missing_or_empty_client_geometry_never_falls_back_to_foreign_pixels(monkeypatch):
    manager, gui = _manager(monkeypatch)
    gui.GetClientRect = lambda h: (0, 0, 0, 0)
    with pytest.raises(ValueError):
        manager._build_bound_window(SimpleNamespace(handle=123, window_text=lambda: "fixture"))
