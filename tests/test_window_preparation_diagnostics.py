"""窗口准备保留系统拒绝事实，不推测完整性或触发输入回退。"""
import pytest

from app.core import window_manager as wm
from app.core.window_preparation import window_preparation_failure_details
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from tests.test_fresh_window_preparation import fresh_host
from tests.test_window_preparation_authority import scene


class Win32Denied(Exception):
    pass


@pytest.mark.parametrize("code,api", [(5, "BringWindowToTop"), (1400, "SetForegroundWindow")])
def test_focus_error_preserves_win32_facts_through_public_coordinator(fresh_host, monkeypatch, code, api):
    co, manager, state, _identity = fresh_host
    original = Win32Denied(code, api, "\u62d2\u7edd\u8bbf\u95ee\u3002" if code == 5 else "Invalid window handle")
    def fail(_handle):
        raise original
    monkeypatch.setattr(wm.win32gui, api, fail)
    preview = co.preview_selected_window_preparation(target_window_handle=321, target_process_id=12)
    with pytest.raises(NativeSingleStepCoordinatorError) as caught:
        co.confirm_window_preparation(preview["preparation_id"])
    error = caught.value
    assert error.code == "window_focus_unverified" and error.result_unknown
    assert error.diagnostics["winerror"] == code and error.diagnostics["win32_function"] == api
    assert error.diagnostics["target_integrity"] == "not_measured"
    assert error.diagnostics["privilege_mismatch_possible"] is (code == 5)
    assert api in str(error) and f"Win32 error {code}" in str(error)
    if code == 5:
        assert "\u62d2\u7edd\u8bbf\u95ee\u3002" in str(error)
        assert "elevation is not established" in str(error)
    else:
        assert "privilege mismatch" not in str(error)
    assert state.active == 0 and state.blocked == [] and co._runtime is None
    with pytest.raises(PermissionError):
        manager.focus_bound_window()


def test_verified_foreground_does_not_fail_on_intermediate_warning(fresh_host, monkeypatch):
    co, _manager, state, _identity = fresh_host
    def warn(_handle):
        state.active = 321
        raise Win32Denied(5, "BringWindowToTop", "Access denied")
    monkeypatch.setattr(wm.win32gui, "BringWindowToTop", warn)
    preview = co.preview_selected_window_preparation(target_window_handle=321, target_process_id=12)
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "focused" and state.blocked == []


def test_maximize_error_preserves_nested_win32_cause(fresh_host, monkeypatch):
    co, _manager, state, _identity = fresh_host
    def fail(*_args):
        raise Win32Denied(5, "ShowWindow", "Access denied")
    monkeypatch.setattr(wm.win32gui, "ShowWindow", fail)
    preview = co.preview_selected_window_maximize(target_window_handle=321, target_process_id=12)
    with pytest.raises(NativeSingleStepCoordinatorError) as caught:
        co.confirm_window_preparation(preview["preparation_id"])
    assert caught.value.code == "window_maximize_unverified"
    assert caught.value.diagnostics["win32_function"] == "ShowWindow"
    assert state.blocked == [] and state.active == 0


def test_non_win32_error_does_not_fabricate_privilege_diagnosis():
    assert window_preparation_failure_details(PermissionError("identity changed")) == {}
    assert window_preparation_failure_details(ValueError("private arbitrary payload")) == {}


def test_cyclic_error_chain_is_bounded():
    error = RuntimeError("no native code")
    error.__cause__ = error
    assert window_preparation_failure_details(error) == {}
