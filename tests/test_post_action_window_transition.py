"""目标弹窗消失后，观察不得抢焦点或抹掉已下发输入。"""
import pytest

from app.core import verifier as module
from app.core import input_controller as inputs


@pytest.mark.parametrize("disappeared", [False, True])
def test_agent_observation_is_passive_and_reports_capture_loss(monkeypatch, disappeared):
    calls = []
    def capture(**kwargs):
        calls.append(kwargs)
        if disappeared:
            raise ValueError("No window is currently bound")
        return {"image_path": None}
    monkeypatch.setattr(module.screenshot_service, "capture_window", capture)
    monkeypatch.setattr(module.window_manager, "get_bound_window", lambda: None)
    result = module.Verifier().verify_action("execute_recognition_plan", wait_ms=0,
        judged_by_agent=True, before_state={"window_handle": 17}, click_result={"clicked": True})
    assert calls[0]["focus_window"] is False
    assert result["verified"] is None
    assert result["automatic_retry_allowed"] is False
    if disappeared:
        assert result["after"]["capture_status"] == "unavailable"
        assert result["after"]["error_type"] == "ValueError"
        assert result["after"]["image_path"] is None
        assert result["diff"]["available"] is False


def test_key_release_survives_window_destroyed_by_key_down(monkeypatch):
    controller = inputs.InputController()
    events = []
    def authorize():
        if events:
            raise PermissionError("target disappeared after key down")
    def send(count, pointer, size):
        value = pointer._obj.union.ki
        events.append((value.wVk, value.dwFlags))
        return 1
    monkeypatch.setattr(controller, "_ensure_windows_input", authorize)
    monkeypatch.setattr(inputs.ctypes.windll.user32, "SendInput", send)
    controller._press_chord([0x0D])
    assert events == [(0x0D, 0), (0x0D, 2)]
    with pytest.raises(PermissionError):
        controller._send_key(0x0D, key_up=True)
    with pytest.raises(PermissionError):
        controller._press_chord([0x0D])
    assert len(events) == 2


def test_interrupted_chord_releases_only_its_pressed_modifier(monkeypatch):
    controller = inputs.InputController()
    events = []
    def authorize():
        if events:
            raise PermissionError("cancelled before second key")
    def send(count, pointer, size):
        value = pointer._obj.union.ki
        events.append((value.wVk, value.dwFlags))
        return 1
    monkeypatch.setattr(controller, "_ensure_windows_input", authorize)
    monkeypatch.setattr(inputs.ctypes.windll.user32, "SendInput", send)
    with pytest.raises(PermissionError, match="cancelled"):
        controller._press_chord([0x11, 0x41])
    assert events == [(0x11, 0), (0x11, 2)]
