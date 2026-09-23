"""只模拟 Win32 边界，验证公共下拉遮挡规则，不访问真实桌面。"""
from types import SimpleNamespace as NS

import pytest

from app.core import window_manager as module


@pytest.mark.parametrize("pid,owner,rect,expected,allowed", [
    (29388,132626,(1049,400,1498,600),None,True),
    (29388,132626,(1049,400,1498,600),657610,True),
    (29388,132626,(1049,400,1498,600),657611,False),
    (29388,132626,(1049,400,1498,600),657610.0,False),
    (29388,132626,(1049,400,1498,600),True,False),
    (30000,132626,(1049,400,1498,600),None,False),
    (29388,123,(1049,400,1498,600),None,False),
    (29388,132626,(0,0,100,100),None,False),
    (29388,132626,None,None,False),
])
def test_native_owned_popup_is_not_a_foreign_occluder(monkeypatch,pid,owner,rect,expected,allowed):
    def rectangle(handle):
        if rect is None: raise OSError("unavailable")
        return rect
    monkeypatch.setattr(module,"win32con",NS(GA_ROOT=2,GA_ROOTOWNER=3))
    monkeypatch.setattr(module,"win32gui",NS(WindowFromPoint=lambda point:657696,
        GetAncestor=lambda handle,kind:657610 if kind==2 else owner,
        IsChild=lambda parent,child:False,GetWindowText=lambda handle:"popup",
        GetWindowRect=rectangle,GetClassName=lambda handle:"Chrome_WidgetWin_1"))
    manager=module.WindowManager()
    monkeypatch.setattr(manager,"_ensure_windows_backend",lambda:None)
    monkeypatch.setattr(manager,"_get_process_id",lambda handle:pid)
    monkeypatch.setattr(manager,"_get_process_name",lambda pid:"msedge.exe")
    bound=module.BoundWindow(132626,"test",29388,"msedge.exe",module.WindowRect(0,0,2560,1400),True)
    value=manager.validate_bound_point_visibility(bound=bound,x=1134,y=546,
        expected_owned_popup_handle=expected)
    assert value["allowed"] is allowed
    if allowed:
        assert value["reason"]=="target_point_owned_by_bound_popup"
        assert value["hit_window"]["root_handle"]==657610
