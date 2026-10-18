"""局部遮挡只排除被遮区域，不让无关浮窗阻断整个界面。"""

from types import SimpleNamespace

import pytest
from PIL import Image

import app.core.screenshot as capture_module
import app.core.window_manager as module
from app.api.models.response import CaptureData
from app.core.screenshot import ScreenshotService
from test_capture_window_ownership import _setup


RECT = {"left": 10, "top": 20, "width": 200, "height": 100}


def test_small_overlay_is_reported_in_window_coordinates(monkeypatch):
    manager, bound, _ = _setup(monkeypatch, overlay=(195, 110, 230, 140))
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is True
    assert result["reason"] == "capture_window_partially_visible"
    assert result["occluded_regions"] == [{"x": 185, "y": 90, "width": 15, "height": 10}]
    assert result["visible_fraction"] == pytest.approx(0.9925)
    assert manager.validate_bound_capture_visibility(bound=bound, rect=RECT)["allowed"] is False


def test_owned_native_popup_is_not_counted_as_capture_occlusion(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(75, 65, 180, 120))
    root_owner = getattr(module.win32con, "GA_ROOTOWNER", 3)
    gui.GetAncestor = lambda hwnd, mode: bound.handle if hwnd == 200 and mode == root_owner else hwnd

    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)

    assert result["allowed"] is True
    assert result["reason"] == "capture_window_visible"
    assert result.get("occluded_regions", []) == []


def test_same_process_unowned_top_level_popup_remains_capture_occlusion(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(75, 65, 180, 120))
    root_owner = getattr(module.win32con, "GA_ROOTOWNER", 3)
    gui.GetAncestor = lambda hwnd, mode: hwnd

    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)

    assert result["allowed"] is True
    assert result["reason"] == "capture_window_partially_visible"
    assert result["occluded_regions"] == [{"x": 65, "y": 45, "width": 105, "height": 55}]


def test_full_occlusion_remains_blocked(monkeypatch):
    manager, bound, _ = _setup(monkeypatch, overlay=(0, 0, 500, 500))
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is False
    assert result["reason"] == "capture_window_occluded"


def test_overlapping_overlays_do_not_double_count_visible_area(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(10, 20, 150, 120))
    gui.GetWindow = lambda hwnd, _: 201 if hwnd == 200 else 100
    gui.GetWindowRect = lambda hwnd: ((10, 20, 210, 120) if hwnd == 100 else (10, 20, 150, 120))
    result = manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)
    assert result["allowed"] is True
    assert result["visible_fraction"] == pytest.approx(0.3)


def test_multiple_overlays_covering_entire_target_are_blocked(monkeypatch):
    manager, bound, gui = _setup(monkeypatch, overlay=(10, 20, 110, 120))
    gui.GetWindow = lambda hwnd, _: 201 if hwnd == 200 else 100
    gui.GetWindowRect = lambda hwnd: {100: (10, 20, 210, 120),
        200: (10, 20, 110, 120), 201: (110, 20, 210, 120)}[hwnd]
    assert manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)["allowed"] is False


@pytest.mark.parametrize("mode", ["missing", "cycle", "minimized"])
def test_partial_capture_does_not_skip_identity_or_z_order_failure(monkeypatch, mode):
    manager, bound, _ = _setup(monkeypatch, **{mode: True})
    assert manager.validate_bound_capture_visibility(bound=bound, rect=RECT, allow_partial=True)["allowed"] is False


def test_target_region_is_independent_of_unrelated_overlay(monkeypatch):
    manager, bound, _ = _setup(monkeypatch, overlay=(195, 110, 230, 140))
    assert manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 20, "top": 30, "width": 40, "height": 20})["allowed"] is True
    assert manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 190, "top": 100, "width": 20, "height": 20})["allowed"] is False


def test_target_bbox_uses_outward_rounding_and_window_origin(monkeypatch):
    manager, bound, _ = _setup(monkeypatch, overlay=(75, 65, 76, 66))
    assert manager.validate_bound_region_visibility(bound=bound, bbox=(0, 0, 30, 30))["allowed"] is True
    assert manager.validate_bound_region_visibility(bound=bound, bbox=(64.8, 44.8, 0.3, 0.3))["allowed"] is False
    assert manager.validate_bound_region_visibility(bound=bound, bbox=(0, 0, float("nan"), 20))["allowed"] is False


def test_owned_popup_does_not_own_parent_target(monkeypatch):
    manager, bound, gui = _setup(monkeypatch)
    gui.WindowFromPoint = lambda _: 200
    gui.GetAncestor = lambda _, mode: 100 if mode == 3 else 200
    gui.IsChild = lambda *_: False
    gui.GetWindowText = lambda _: "Owned popup"
    monkeypatch.setattr(manager, "_get_process_name", lambda _: "target.exe")
    assert manager.validate_bound_point_visibility(bound=bound, x=30, y=30)["allowed"] is False


def test_text_without_reclick_still_checks_observed_point(monkeypatch):
    from test_text_input_guard import prepared
    from app.core.input_controller import TargetPointOccludedError, VK_CONTROL, VK_V
    import app.core.input_controller as input_module
    controller, _, events, _ = prepared(monkeypatch)
    monkeypatch.setattr(input_module.window_manager, "validate_bound_point_visibility",
        lambda **_: {"allowed": False, "reason": "target_point_occluded"})
    with pytest.raises(TargetPointOccludedError):
        controller.type_text("search", x=70, y=80, click_before_typing=False)
    assert (VK_CONTROL, VK_V) not in events
    assert events[-1] == "clipboard-restored"


def test_guarded_insertion_rejects_field_edge_occlusion_without_paste(monkeypatch):
    from test_text_guarded_backend import compose, reviewed, resolve_text_parameters
    import app.core.input_controller as inputs
    parameters = resolve_text_parameters(reviewed(variable="query", clear_existing=False), {"query": "map"})
    adapter, command, authority, _, _, events, pasted = compose(monkeypatch, resolved=parameters, selection=(3, 3))
    monkeypatch.setattr(inputs.window_manager, "validate_bound_region_visibility",
        lambda **_: {"allowed": False, "reason": "target_region_occluded"})
    assert adapter.dispatch(command, authority=authority).status != "dispatched"
    assert pasted == [] and "click" not in events
    assert events[-1] == "clipboard-restored"


def test_bbox_occlusion_after_pointer_settle_stops_mouse_down(monkeypatch):
    import app.core.input_controller as inputs
    controller = inputs.InputController()
    bound = SimpleNamespace(handle=7, title="Target")
    events = []
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point",
        lambda **_: {"window_x": 50, "window_y": 50, "screen_x": 50, "screen_y": 50})
    monkeypatch.setattr(inputs.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(inputs.win32api, "GetCursorPos", lambda: (50, 50))
    monkeypatch.setattr(controller, "_focus_window", lambda _: True)
    monkeypatch.setattr(controller, "_send_move", lambda *_: events.append("move"))
    monkeypatch.setattr(inputs.time, "sleep", lambda _: events.append("settle"))
    monkeypatch.setattr(inputs.window_manager, "validate_bound_point_visibility", lambda **_: {"allowed": True})
    def region_check(**kwargs):
        assert events == ["move", "settle"]
        assert kwargs["bbox"] == (40, 40, 30, 30)
        return {"allowed": False, "reason": "target_region_occluded"}
    monkeypatch.setattr(inputs.window_manager, "validate_bound_region_visibility", region_check)
    monkeypatch.setattr(controller, "mouse_down", lambda _: events.append("down"))
    with pytest.raises(inputs.TargetPointOccludedError) as rejected:
        controller.click_point(50, 50, target_bbox=(40, 40, 30, 30))
    assert "down" not in events
    assert rejected.value.evidence['point_visibility']['allowed'] is True
    assert rejected.value.evidence['region_visibility']['reason'] == 'target_region_occluded'


def _capture_setup(monkeypatch, tmp_path, *, move_during_capture=False):
    manager, bound, gui = _setup(monkeypatch, overlay=(75, 65, 85, 75))
    manager.get_bound_window = lambda: bound
    class Context:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def grab(self, monitor):
            if move_during_capture:
                gui.GetWindowRect = lambda h: (10, 20, 210, 120) if h == 100 else (80, 65, 90, 75)
            size = (monitor["width"], monitor["height"])
            return SimpleNamespace(size=size, rgb=bytes([255, 0, 0]) * (size[0] * size[1]))
    monkeypatch.setattr(capture_module, "MSS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(capture_module, "mss", Context)
    monkeypatch.setattr(capture_module, "Image", Image)
    return ScreenshotService(window_manager=manager, capture_dir=tmp_path)


def test_full_capture_masks_overlay_and_preserves_visible_pixels(monkeypatch, tmp_path):
    service = _capture_setup(monkeypatch, tmp_path)
    result = service.capture_window(focus_window=False)
    assert result["image_width"] == 200 and result["image_height"] == 100
    image = Image.open(result["image_path"])
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((65, 45)) == (32, 32, 32)
    assert image.getpixel((75, 55)) == (255, 0, 0)
    assert result["capture_visibility"]["masked"] is True
    assert CaptureData(**result).model_dump()["capture_visibility"] == result["capture_visibility"]


def test_roi_mask_uses_image_relative_pixels_once(monkeypatch, tmp_path):
    from app.api.models.request import ROIModel
    service = _capture_setup(monkeypatch, tmp_path)
    result = service.capture_window(focus_window=False, roi=ROIModel(x=50, y=30, width=100, height=60))
    image = Image.open(result["image_path"])
    assert image.getpixel((15, 15)) == (32, 32, 32)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert result["capture_visibility"]["occluded_regions"] == [{"x": 65, "y": 45, "width": 10, "height": 10}]


def test_overlay_moving_during_capture_discards_pixels(monkeypatch, tmp_path):
    service = _capture_setup(monkeypatch, tmp_path, move_during_capture=True)
    with pytest.raises(ValueError, match="capture_visibility_changed"):
        service.capture_window(focus_window=False)
    assert not list(tmp_path.glob("*.png"))

