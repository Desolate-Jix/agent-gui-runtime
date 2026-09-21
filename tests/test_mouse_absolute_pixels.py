from types import SimpleNamespace

import pytest

from app.core import input_controller as module


@pytest.mark.parametrize('width,height', [(2412, 1080), (1920, 1080), (2560, 1440), (3840, 2160)])
def test_absolute_move_targets_each_pixel_interval_not_its_lower_edge(monkeypatch, width, height):
    user32 = SimpleNamespace(GetSystemMetrics=lambda metric: width if metric == module.SM_CXSCREEN else height)
    monkeypatch.setattr(module.ctypes, 'windll', SimpleNamespace(user32=user32))
    controller = module.InputController()
    sent = []
    monkeypatch.setattr(controller, '_send_mouse_input', lambda **kw: sent.append(kw))
    # 覆盖本轮 (10,56) 与所有左右边缘，不能通过放宽漂移校验掩盖变换错误。
    for x in range(width):
        y = x % height
        controller._send_move(x, y)
        packet = sent[-1]
        assert packet['dx'] * width // 65536 == x
        assert packet['dy'] * height // 65536 == y
        assert packet['flags'] == module.MOUSEEVENTF_MOVE | module.MOUSEEVENTF_ABSOLUTE


def test_actual_back_button_failure_pixel_round_trip(monkeypatch):
    monkeypatch.setattr(module.ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
        GetSystemMetrics=lambda metric: 2412 if metric == module.SM_CXSCREEN else 1080)))
    controller = module.InputController()
    sent = []
    monkeypatch.setattr(controller, '_send_mouse_input', lambda **kw: sent.append(kw))
    controller._send_move(10, 56)
    assert (sent[0]['dx'] * 2412 // 65536, sent[0]['dy'] * 1080 // 65536) == (10, 56)
