"""原始截图须带本次稳定窗口几何，不能用输入前的位置补作后图证据。"""
from types import SimpleNamespace

import pytest

from app.core import screenshot


@pytest.fixture
def captured_scene(monkeypatch):
    bound = SimpleNamespace(handle=101, process_id=12, is_active=True,
        rect=SimpleNamespace(left=-30, top=40, right=50, bottom=100))
    state = SimpleNamespace(bound=bound, drift=False, grabs=[])
    manager = SimpleNamespace(get_bound_window=lambda: state.bound,
        validate_bound_capture_visibility=lambda **kwargs: {"allowed": True})
    service = screenshot.ScreenshotService(window_manager=manager)
    monkeypatch.setattr(service, "_ensure_capture_backend", lambda: None)

    class Screen:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def grab(self, monitor):
            state.grabs.append(dict(monitor))
            if state.drift:
                state.bound.rect.left += 1
                state.bound.rect.right += 1
            size = (monitor["width"], monitor["height"])
            return SimpleNamespace(size=size, rgb=b"\x10\x20\x30" * (size[0] * size[1]))

    monkeypatch.setattr(screenshot, "mss", Screen)
    return service, state


@pytest.mark.parametrize("cropped", [False, True])
def test_capture_records_stable_screen_rect_and_actual_pixel_size(captured_scene, cropped):
    service, state = captured_scene
    roi = SimpleNamespace(x=5, y=7, width=20, height=10,
        model_dump=lambda: {"x": 5, "y": 7, "width": 20, "height": 10}) if cropped else None
    result = service.capture_window(roi=roi, save_image=False, focus_window=False)
    assert result["window_rect"] == [-30, 40, 50, 100]
    assert result["image_size"] == ({"width": 20, "height": 10} if cropped else {"width": 80, "height": 60})
    assert result["window_size"] == {"width": 80, "height": 60}
    assert result["image_size"] == {"width": result["image_width"], "height": result["image_height"]}
    assert len(state.grabs) == 1


def test_drifting_capture_cannot_publish_current_or_previous_geometry(captured_scene):
    service, state = captured_scene
    state.drift = True
    with pytest.raises(ValueError, match="capture_binding_changed"):
        service.capture_window(save_image=False, focus_window=False)
    assert len(state.grabs) == 1


@pytest.mark.parametrize("before,after,accepted", [
    ([{"x": 40, "y": 44, "width": 40, "height": 16}],
     [{"x": 40, "y": 52, "width": 40, "height": 8}], True),
    ([{"x": 40, "y": 44, "width": 40, "height": 16}], [], True),
    ([{"x": 10, "y": 10, "width": 10, "height": 10},
      {"x": 20, "y": 10, "width": 10, "height": 10}],
     [{"x": 15, "y": 10, "width": 10, "height": 10}], True),
    ([{"x": 40, "y": 44, "width": 40, "height": 8}],
     [{"x": 40, "y": 44, "width": 40, "height": 16}], False),
    ([{"x": 40, "y": 44, "width": 20, "height": 8}],
     [{"x": 41, "y": 44, "width": 20, "height": 8}], False),
])
def test_capture_accepts_only_shrinking_occlusion_and_keeps_original_mask(
        captured_scene, tmp_path, before, after, accepted):
    from PIL import Image
    from app.core.screenshot import CaptureVisibilityError

    service, state = captured_scene
    state.bound.title, state.bound.process_name = "Test capture", "test.exe"
    service._capture_dir = tmp_path
    observations = iter((before, after))
    service._window_manager.validate_bound_capture_visibility = lambda **kwargs: {
        "contract_version": "bound_capture_visibility_v2", "allowed": True,
        "reason": "capture_window_partially_visible", "bound_window_handle": state.bound.handle,
        "occluded_regions": next(observations)}
    if not accepted:
        with pytest.raises(CaptureVisibilityError, match="capture_visibility_changed"):
            service.capture_window(save_image=False, focus_window=False)
    else:
        capture = service.capture_window(save_image=True, focus_window=False)
        assert capture["capture_visibility"]["occluded_regions"] == before
        assert capture["capture_visibility"]["masked"] is True
        with Image.open(capture["image_path"]) as image:
            assert image.getpixel((10, 30)) == (16, 32, 48)
            x, y = before[0]["x"], before[0]["y"]
            assert image.getpixel((x, y)) == (32, 32, 32)
    assert len(state.grabs) == 1


@pytest.mark.parametrize("partial", [False, True])
def test_real_capture_visibility_survives_into_startup(captured_scene, tmp_path, partial):
    from hashlib import sha256
    from pathlib import Path
    from scripts.execution_startup import selection_ready
    from tests.test_execution_startup import scenario
    service, state = captured_scene
    state.bound.handle, state.bound.process_id = 10, 20
    state.bound.title, state.bound.process_name = "Test capture", "test.exe"
    visibility = {"contract_version": "bound_capture_visibility_v2", "allowed": True,
        "reason": "capture_window_partially_visible" if partial else "capture_window_visible",
        "bound_window_handle": 10}
    if partial:
        visibility["occluded_regions"] = [{"x": 0, "y": 0, "width": 1, "height": 1}]
    service._window_manager.validate_bound_capture_visibility = lambda **kwargs: dict(visibility)
    service._capture_dir = tmp_path
    capture = service.capture_window(focus_window=False)
    # 直接消费真实截图返回值，不能由测试补造可见性证明。
    assert capture["capture_visibility"]["allowed"] is True
    assert capture["capture_visibility"]["masked"] is partial
    client, select, plan, response, calls, image = scenario(tmp_path)
    capture["window_identity"] = response["observation"]["window_identity"]
    capture["sha256"] = sha256(Path(capture["image_path"]).read_bytes()).hexdigest()
    response["observation"] = capture
    assert selection_ready(response, select) is True
