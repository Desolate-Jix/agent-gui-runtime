"""只移除重复聚焦等待，不复用旧帧或减少可见性核验。"""
from pathlib import Path

import pytest

from app.core.screenshot import ScreenshotService
from test_screenshot_passive_capture import _bound, _WindowManager, _install_capture_fakes, _Image


def test_fresh_foreground_capture_never_refocuses_or_waits(monkeypatch):
    bound = _bound()
    bound.is_active = True
    manager = _WindowManager(passive_bound=bound)
    checks = []
    def visibility(**kwargs):
        checks.append(kwargs)
        return {"allowed": True}
    manager.validate_bound_capture_visibility = visibility
    monitors = _install_capture_fakes(monkeypatch, manager=manager)
    service = ScreenshotService(window_manager=manager)
    monkeypatch.setattr(service, "_wait_after_focus", lambda: pytest.fail("already foreground must not wait"))
    for _ in range(2):
        service.capture_window(save_image=False)
    assert manager.focus_calls == 0
    assert len(monitors) == 2 and len(checks) == 4


@pytest.mark.parametrize("active", [False, None, 1])
def test_nonforeground_or_unknown_state_keeps_focus_settle(monkeypatch, active):
    bound = _bound()
    bound.is_active = active
    manager = _WindowManager(passive_bound=bound)
    _install_capture_fakes(monkeypatch, manager=manager)
    waits = []
    service = ScreenshotService(window_manager=manager)
    monkeypatch.setattr(service, "_wait_after_focus", lambda: waits.append(True))
    service.capture_window(save_image=False)
    assert manager.focus_calls == 1 and waits == [True]


def test_saving_uses_balanced_lossless_png_compression(monkeypatch, tmp_path):
    manager = _WindowManager(passive_bound=_bound())
    _install_capture_fakes(monkeypatch, manager=manager)
    saved = []
    def save(image, path, **kwargs):
        saved.append(kwargs)
        Path(path).write_bytes(b"synthetic image")
    monkeypatch.setattr(_Image, "save", save, raising=False)
    ScreenshotService(window_manager=manager, capture_dir=tmp_path).capture_window(focus_window=False)
    assert saved == [{"compress_level": 3}]
