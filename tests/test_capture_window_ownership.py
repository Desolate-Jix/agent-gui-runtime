"""屏幕矩形必须仍由目标窗口覆盖，不能只检查中心点。"""

from types import SimpleNamespace
import pytest
import app.core.window_manager as module
from app.core.window_manager import BoundWindow, WindowManager, WindowRect


def _setup(monkeypatch, *, overlay=None, minimized=False, missing=False, cycle=False):
    target = 100
    rect = (10, 20, 210, 120)
    top = 200 if overlay is not None or missing or cycle else target
    gui = SimpleNamespace(
        IsWindow=lambda hwnd: True,
        IsWindowVisible=lambda hwnd: True,
        IsIconic=lambda hwnd: minimized if hwnd == target else False,
        GetWindowRect=lambda hwnd: rect if hwnd == target else (overlay or (300, 300, 400, 400)),
        GetTopWindow=lambda _: top,
        GetWindow=lambda hwnd, _: (top if cycle else (0 if missing else target)),
    )
    monkeypatch.setattr(module, 'WINDOWS_BACKEND_AVAILABLE', True)
    monkeypatch.setattr(module, 'win32gui', gui)
    manager = WindowManager()
    monkeypatch.setattr(manager, '_is_dwm_cloaked', lambda h: False, raising=False)
    monkeypatch.setattr(manager, '_capture_surface_rect', lambda h: gui.GetWindowRect(h))
    monkeypatch.setattr(manager, '_get_process_id', lambda _: 10)
    bound = BoundWindow(target, 'Target', 10, 'target.exe', WindowRect(*rect), False)
    return manager, bound, gui


@pytest.mark.parametrize('overlay,reason', [
    (None, 'capture_window_visible'),
    ((75, 65, 76, 66), 'capture_window_occluded'),
    ((210, 20, 250, 120), 'capture_window_visible'),
])
def test_z_order_checks_the_full_capture_rectangle(monkeypatch, overlay, reason):
    manager, bound, _ = _setup(monkeypatch, overlay=overlay)
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={'left': 10, 'top': 20, 'width': 200, 'height': 100})
    assert result['reason'] == reason
    assert result['allowed'] is (reason == 'capture_window_visible')


@pytest.mark.parametrize('mode,reason', [
    ('minimized', 'capture_window_minimized'),
    ('missing', 'capture_visibility_unavailable'),
    ('cycle', 'capture_visibility_unavailable'),
])
def test_invalid_target_or_z_order_never_allows_capture(monkeypatch, mode, reason):
    manager, bound, _ = _setup(monkeypatch, **{mode: True})
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={'left': 10, 'top': 20, 'width': 200, 'height': 100})
    assert result['allowed'] is False and result['reason'] == reason


def test_binding_drift_and_hidden_overlay_are_distinguished(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(75, 65, 76, 66))
    gui.IsWindowVisible = lambda hwnd: hwnd == bound.handle
    rect = {'left': 10, 'top': 20, 'width': 200, 'height': 100}
    assert manager.validate_bound_capture_visibility(bound=bound, rect=rect)['allowed'] is True
    gui.GetWindowRect = lambda _: (11, 20, 211, 120)
    result = manager.validate_bound_capture_visibility(bound=bound, rect=rect)
    assert result['allowed'] is False and result['reason'] == 'capture_binding_changed'


@pytest.mark.parametrize('cloaked,style,alpha,flags,allowed', [
    (True, 0, 255, 2, True),
    (False, 0x80000, 0, 2, True),
    (False, 0x80000, 1, 2, False),
    (False, 0x80000, 0, 1, False),
    (False, 0x20, 0, 2, False),
])
def test_only_proven_invisible_overlays_are_excluded(monkeypatch, cloaked, style, alpha, flags, allowed):
    manager, bound, gui = _setup(monkeypatch, overlay=(10, 20, 210, 120))
    monkeypatch.setattr(manager, '_is_dwm_cloaked', lambda h: cloaked)
    gui.GetWindowLong = lambda h, field: style
    gui.GetLayeredWindowAttributes = lambda h: (0, alpha, flags)
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={'left': 10, 'top': 20, 'width': 200, 'height': 100}, allow_partial=True)
    assert result['allowed'] is allowed


def test_unknown_layered_opacity_still_occludes(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(10, 20, 210, 120))
    gui.GetWindowLong = lambda h, field: 0x80000
    def unavailable(h):
        raise OSError('per-pixel alpha unavailable')
    gui.GetLayeredWindowAttributes = unavailable
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={'left': 10, 'top': 20, 'width': 200, 'height': 100}, allow_partial=True)
    assert result['allowed'] is False
