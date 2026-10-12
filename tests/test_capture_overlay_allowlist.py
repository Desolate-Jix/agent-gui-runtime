"""录屏白名单仅免除截图矩形遮挡，不能隐去像素或放行动作。"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core import screenshot
from tests.test_capture_window_ownership import _setup


RECT = {"left": 10, "top": 20, "width": 200, "height": 100}


def scene(monkeypatch, *, name="NVIDIA Overlay.exe", window_class="CEF-OSC-WIDGET",
          style=0x800A8):
    manager, bound, gui = _setup(monkeypatch, overlay=(10, 20, 210, 120))
    gui.GetClassName = lambda hwnd: window_class
    gui.GetWindowLong = lambda hwnd, field: style
    gui.GetLayeredWindowAttributes = lambda hwnd: (0, 255, 2)
    gui.GetAncestor = lambda hwnd, flag: hwnd
    gui.GetWindowText = lambda hwnd: "NVIDIA GeForce Overlay"
    gui.IsChild = lambda parent, child: False
    gui.WindowFromPoint = lambda point: 200
    monkeypatch.setattr(manager, "_get_process_id", lambda hwnd: 10 if hwnd == 100 else 20)
    monkeypatch.setattr(manager, "_get_process_name", lambda pid: name if pid == 20 else "target.exe")
    monkeypatch.setattr(manager, "get_bound_window", lambda: bound)
    return manager, bound, gui


def test_known_recording_overlay_no_longer_blocks_capture(monkeypatch):
    manager, bound, _ = scene(monkeypatch)
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is True
    assert not result.get("occluded_regions")
    exemption = result["capture_overlay_exemptions"][0]
    assert exemption["handle"] == 200
    assert exemption["process_id"] == 20
    assert exemption["process_name"] == "NVIDIA Overlay.exe"
    assert exemption["window_class"] == "CEF-OSC-WIDGET"


@pytest.mark.parametrize("change", [
    {"name": "NVIDIA.exe"},
    {"name": "NVIDIA Container.exe"},
    {"name": "NVIDIA Overlay.exe.bak"},
    {"name": None},
    {"window_class": "Chrome_WidgetWin_1"},
    {"style": 0xA8},
    {"style": 0x80088},
    {"style": 0x800A0},
])
def test_similar_or_interactive_windows_are_not_allowlisted(monkeypatch, change):
    manager, bound, _ = scene(monkeypatch, **change)
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is False
    assert result["reason"] == "capture_window_occluded"
    assert not result.get("capture_overlay_exemptions")


def test_executable_name_case_does_not_change_windows_identity(monkeypatch):
    manager, bound, _ = scene(monkeypatch, name="nvidia OVERLAY.EXE")
    assert manager.validate_bound_capture_visibility(
        bound=bound, rect=RECT, allow_partial=True)["allowed"] is True


@pytest.mark.parametrize("field", ["GetClassName", "GetWindowLong"])
def test_unavailable_overlay_identity_does_not_grant_exemption(monkeypatch, field):
    manager, bound, gui = scene(monkeypatch)
    def unavailable(*args):
        raise OSError("identity unavailable")
    setattr(gui, field, unavailable)
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is False
    assert not result.get("capture_overlay_exemptions")


def test_allowlist_does_not_skip_strict_native_region_or_point_gate(monkeypatch):
    manager, bound, _ = scene(monkeypatch)
    assert manager.validate_bound_capture_visibility(
        bound=bound, rect=RECT, allow_partial=True)["allowed"] is True
    region = manager.validate_bound_region_visibility(bound=bound, bbox=(0, 0, 200, 100))
    assert region["allowed"] is False
    assert region["reason"] == "target_region_occluded"
    point = manager.validate_bound_point_visibility(bound=bound, x=20, y=20)
    assert point["allowed"] is False
    assert point["reason"] == "target_point_occluded"


def test_other_window_behind_allowlisted_overlay_still_blocks(monkeypatch):
    manager, bound, gui = scene(monkeypatch)
    gui.GetWindow = lambda hwnd, flag: {200: 300, 300: 100}.get(hwnd, 0)
    gui.GetClassName = lambda hwnd: "CEF-OSC-WIDGET" if hwnd == 200 else "OtherWindow"
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is False
    assert result["reason"] == "capture_window_occluded"


@pytest.mark.parametrize("opaque_other", [False, True])
def test_capture_preserves_hud_pixels_and_only_masks_unrelated_windows(monkeypatch, tmp_path, opaque_other):
    manager, bound, gui = scene(monkeypatch)
    if opaque_other:
        gui.GetWindow = lambda hwnd, flag: {200: 300, 300: 100}.get(hwnd, 0)
        gui.GetClassName = lambda hwnd: "CEF-OSC-WIDGET" if hwnd == 200 else "OtherWindow"
        gui.GetWindowRect = lambda hwnd: (160, 70, 210, 120) if hwnd == 300 else (10, 20, 210, 120)

    pixels = Image.new("RGB", (200, 100), (10, 30, 50))
    pixels.paste((255, 20, 30), (5, 5, 15, 15))
    class Screen:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def grab(self, monitor):
            return SimpleNamespace(size=pixels.size, rgb=pixels.tobytes())

    monkeypatch.setattr(screenshot, "mss", Screen)
    service = screenshot.ScreenshotService(window_manager=manager, capture_dir=tmp_path)
    result = service.capture_window(focus_window=False)
    with Image.open(Path(result["image_path"])) as actual:
        assert actual.getpixel((8, 8)) == (255, 20, 30)
        assert actual.getpixel((20, 20)) == (10, 30, 50)
        assert actual.getpixel((180, 80)) == ((32, 32, 32) if opaque_other else (10, 30, 50))
    assert result["capture_visibility"]["masked"] is opaque_other
    assert len(result["capture_visibility"]["capture_overlay_exemptions"]) == 1


@pytest.mark.parametrize("overlay_pids", [(None,), (20, 21)])
def test_missing_or_changed_process_identity_cannot_obtain_exemption(monkeypatch, overlay_pids):
    manager, bound, _ = scene(monkeypatch)
    reads = iter(overlay_pids)
    monkeypatch.setattr(manager, "_get_process_id",
        lambda hwnd: 10 if hwnd == bound.handle else next(reads))
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is False
    assert result["reason"] == "capture_window_occluded"
    assert not result.get("capture_overlay_exemptions")


@pytest.mark.parametrize("name,allowed", [("NVIDIA Overlay.exe", True), ("Other.exe", False)])
def test_reviewed_single_pixel_scope_uses_same_overlay_exemption(monkeypatch, name, allowed):
    manager, bound, _ = scene(monkeypatch, name=name)
    result = manager.validate_bound_region_visibility(bound=bound, bbox=(20, 20, 1, 1))
    assert result["allowed"] is allowed
    assert result["reason"] == ("target_region_visible" if allowed else "target_region_occluded")


from tests.test_nonmodal_popup_parent_click import scene as input_scene


@pytest.mark.parametrize("hit", [100, 200])
def test_recording_overlay_dispatch_depends_on_real_point_hit(input_scene, monkeypatch, hit):
    from app.core import input_controller as inputs
    from app.core import window_manager as windows
    controller, manager, bound, state = input_scene
    state.foreground, state.hit, state.owner = 100, hit, 200
    monkeypatch.delattr(manager, "validate_bound_region_visibility")
    monkeypatch.setattr(manager, "_capture_surface_rect", lambda handle: (0, 0, 2560, 1400))
    monkeypatch.setattr(manager, "_is_dwm_cloaked", lambda handle: False)
    monkeypatch.setattr(manager, "_get_process_id", lambda handle: 20 if handle == 200 else 10)
    monkeypatch.setattr(manager, "_get_process_name",
        lambda pid: "NVIDIA Overlay.exe" if pid == 20 else "browser.exe")
    for key, value in {"GW_HWNDNEXT": 2, "GWL_EXSTYLE": -20,
                       "WS_EX_LAYERED": 0x80000, "WS_EX_TRANSPARENT": 0x20,
                       "WS_EX_TOPMOST": 0x8, "LWA_ALPHA": 2}.items():
        monkeypatch.setattr(windows.win32con, key, value, raising=False)
    gui = windows.win32gui
    monkeypatch.setattr(gui, "GetTopWindow", lambda handle: 200, raising=False)
    monkeypatch.setattr(gui, "GetWindow", lambda handle, flag: 100 if handle == 200 else 0, raising=False)
    monkeypatch.setattr(gui, "GetWindowRect", lambda handle: (0, 0, 2560, 1400))
    monkeypatch.setattr(gui, "GetClassName", lambda handle: "CEF-OSC-WIDGET" if handle == 200 else "Window")
    monkeypatch.setattr(gui, "GetWindowLong", lambda *args: 0x800A8, raising=False)
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", lambda handle: (0, 255, 2), raising=False)
    if hit == 200:
        with pytest.raises(inputs.TargetPointOccludedError):
            controller.click_point(1008, 49, hold_ms=0, target_bbox=(1008, 49, 1, 1))
        assert "down" not in state.events
    else:
        result = controller.click_point(1008, 49, hold_ms=0, target_bbox=(1008, 49, 1, 1))
        assert result["clicked"] is True
        assert state.events.count("down") == 1 and state.events.count("up") == 1
