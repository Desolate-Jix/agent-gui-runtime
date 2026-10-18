"""关闭未完成时必须返回真实归属窗口，不把保存弹窗当成宿主清理。"""
from types import SimpleNamespace

import pytest

from app.core import window_close


class Gui:
    def IsWindow(self, handle):
        return handle in {10, 11, 12, 13, 14}

    def IsWindowEnabled(self, handle):
        return handle != 10

    def IsWindowVisible(self, handle):
        return handle != 14

    def EnumWindows(self, callback, extra):
        for handle in (10, 11, 12, 13, 14):
            callback(handle, extra)

    def GetWindow(self, handle, kind):
        assert kind == 4
        return {11: 10, 12: 0, 13: 10, 14: 10}.get(handle, 0)

    def GetWindowText(self, handle):
        return "保存提示" if handle == 11 else "其他窗口"

    def GetClassName(self, handle):
        return "#32770"


def threads():
    return SimpleNamespace(GetWindowThreadProcessId=lambda handle: (1, 99 if handle == 13 else 20))


def test_close_observation_only_returns_visible_same_process_owned_windows():
    result = window_close.observe_close_wait(10, 20, gui=Gui(), threads=threads())
    assert result["status"] == "owned_modal_visible"
    assert result["parent_enabled"] is False
    assert result["owned_windows"] == [{"handle": 11, "process_id": 20,
        "title": "保存提示", "class_name": "#32770", "enabled": True}]
    assert result["authorizes_input"] is False


def test_close_observation_rejects_changed_parent_process():
    with pytest.raises(ValueError, match="identity"):
        window_close.observe_close_wait(10, 99, gui=Gui(), threads=threads())


def test_close_observation_reports_no_modal_without_assuming_closed():
    gui = Gui()
    gui.EnumWindows = lambda callback, extra: callback(12, extra)
    result = window_close.observe_close_wait(10, 20, gui=gui, threads=threads())
    assert result["status"] == "window_still_present"
    assert result["owned_windows"] == []


def test_close_observation_does_not_loop_on_cyclic_owner_chain():
    gui = Gui()
    gui.GetWindow = lambda handle, kind: {11: 12, 12: 11}.get(handle, 0)
    result = window_close.observe_close_wait(10, 20, gui=gui, threads=threads())
    assert result["owned_windows"] == []
