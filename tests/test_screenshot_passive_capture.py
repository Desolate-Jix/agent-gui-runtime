from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.core.screenshot as screenshot_module
from app.core.screenshot import ScreenshotService


def _bound() -> SimpleNamespace:
    return SimpleNamespace(
        handle=4242,
        title="Bound browser",
        process_id=9001,
        process_name="browser.exe",
        rect=SimpleNamespace(left=100, top=200, right=900, bottom=700),
    )


class _WindowManager:
    def __init__(self, *, passive_bound: object | None, focused_bound: object | None = None) -> None:
        self.passive_bound = passive_bound
        self.focused_bound = focused_bound if focused_bound is not None else passive_bound
        self.get_calls = 0
        self.focus_calls = 0

    def get_bound_window(self) -> object | None:
        self.get_calls += 1
        return self.passive_bound

    def focus_bound_window(self) -> object:
        self.focus_calls += 1
        return self.focused_bound


class _RawCapture:
    def __init__(self, *, width: int, height: int) -> None:
        self.size = (width, height)
        self.rgb = b""


class _MSSContext:
    def __init__(self, monitors: list[dict[str, int]]) -> None:
        self.monitors = monitors

    def __enter__(self) -> _MSSContext:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def grab(self, monitor: dict[str, int]) -> _RawCapture:
        self.monitors.append(dict(monitor))
        return _RawCapture(width=monitor["width"], height=monitor["height"])


class _Image:
    def __init__(self, *, width: int, height: int) -> None:
        self.width = width
        self.height = height


class _ImageModule:
    @staticmethod
    def frombytes(_mode: str, size: tuple[int, int], _rgb: bytes) -> _Image:
        return _Image(width=size[0], height=size[1])


def _install_capture_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    manager: _WindowManager,
) -> list[dict[str, int]]:
    monitors: list[dict[str, int]] = []
    monkeypatch.setattr(screenshot_module, "MSS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(screenshot_module, "window_manager", manager)
    monkeypatch.setattr(screenshot_module, "mss", lambda: _MSSContext(monitors))
    monkeypatch.setattr(screenshot_module, "Image", _ImageModule)
    return monitors


def test_passive_capture_reads_binding_without_focus_or_settle_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _WindowManager(passive_bound=_bound())
    monitors = _install_capture_fakes(monkeypatch, manager=manager)
    service = ScreenshotService()
    wait_calls: list[bool] = []
    monkeypatch.setattr(service, "_wait_after_focus", lambda: wait_calls.append(True))

    result = service.capture_window(
        save_image=False,
        purpose="runtime-observation",
        focus_window=False,
    )

    assert manager.get_calls == 1
    assert manager.focus_calls == 0
    assert wait_calls == []
    assert monitors == [{"left": 100, "top": 200, "width": 800, "height": 500}]
    assert result == {
        "image_path": None,
        "image_width": 800,
        "image_height": 500,
        "roi": None,
        "roi_adjusted": False,
        "capture_purpose": "runtime-observation",
        "window_size": {"width": 800, "height": 500},
    }


def test_passive_capture_missing_binding_fails_before_mss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _WindowManager(passive_bound=None)
    monitors = _install_capture_fakes(monkeypatch, manager=manager)
    service = ScreenshotService()
    wait_calls: list[bool] = []
    monkeypatch.setattr(service, "_wait_after_focus", lambda: wait_calls.append(True))

    with pytest.raises(ValueError, match="No bound window available to capture"):
        service.capture_window(save_image=False, focus_window=False)

    assert manager.get_calls == 1
    assert manager.focus_calls == 0
    assert wait_calls == []
    assert monitors == []


def test_default_capture_still_focuses_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _WindowManager(passive_bound=_bound(), focused_bound=_bound())
    monitors = _install_capture_fakes(monkeypatch, manager=manager)
    service = ScreenshotService()
    wait_calls: list[bool] = []
    monkeypatch.setattr(service, "_wait_after_focus", lambda: wait_calls.append(True))

    result = service.capture_window(save_image=False)

    assert manager.get_calls == 0
    assert manager.focus_calls == 1
    assert wait_calls == [True]
    assert monitors == [{"left": 100, "top": 200, "width": 800, "height": 500}]
    assert result["window_size"] == {"width": 800, "height": 500}
