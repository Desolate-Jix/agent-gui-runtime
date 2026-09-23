"""原生 owned 弹窗可出现在 UIA 子数组中，但不能被当作无关窗口。"""
from types import SimpleNamespace as NS
import pytest
from app.agent import windows_form_control_reader as r
from tests.test_windows_form_control_reader import Node, TARGET, setup

def popup(owner=10,pid=20):
    return {'handle':30,'process_id':pid,'owner_handle':owner,'root_owner_handle':owner,'class_name':'popup','rect':[120,260,220,360]}

def scene(setup):
    menu=Node('', 'Pane', (3,1), handle=30)
    choice=Node('Choice','CheckBox',(2,1))
    choice.iface_toggle=NS(CurrentToggleState=1)
    return setup(menu,choice)

def test_verified_owned_popup_does_not_break_full_window_scan(setup,monkeypatch):
    coordinator=scene(setup)
    monkeypatch.setattr(r,'_native_owned_popups',lambda *a:[popup()])
    value=r.read_form_control(coordinator,TARGET,'Choice','checkbox')
    assert value['checked'] is True

@pytest.mark.parametrize('bad', [[],[popup(owner=99)],[popup(pid=99)]])
def test_foreign_popup_never_normalizes_scope(setup,monkeypatch,bad):
    coordinator=scene(setup)
    monkeypatch.setattr(r,'_native_owned_popups',lambda *a:bad)
    with pytest.raises(r.FormControlReadError,match='tree_scope_changed'):
        r.read_form_control(coordinator,TARGET,'Choice','checkbox')

def test_popup_owner_change_during_scan_interrupts(setup,monkeypatch):
    coordinator=scene(setup)
    observations=iter([[popup()],[popup(owner=99)]])
    monkeypatch.setattr(r,'_native_owned_popups',lambda *a:next(observations))
    with pytest.raises(r.FormControlReadError,match='popup_changed'):
        r.read_form_control(coordinator,TARGET,'Choice','checkbox')
