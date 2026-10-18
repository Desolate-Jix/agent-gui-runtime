"""本地确认只放行选定窗口的一次最大化，不增加 Agent 键鼠权限。"""
import pytest

from app.core import window_manager as wm
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from tests.test_fresh_window_preparation import fresh_host
from tests.test_window_preparation_authority import scene  # 注册 fresh_host 的场景依赖


def _preview(co):
    return co.preview_selected_window_maximize(
        target_window_handle=321,
        target_process_id=12,
    )


def test_selected_window_maximize_requires_preview_and_runs_once(fresh_host):
    co, manager, state, identity = fresh_host
    preview = _preview(co)
    assert preview["source"] == "selected_window"
    assert preview["mode"] == "maximize"
    assert preview["identity"] == identity
    assert state.mutations == []

    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "maximized"
    assert result["window"]["handle"] == 321
    assert ("restore", 321, wm.win32con.SW_MAXIMIZE) in state.mutations
    assert state.active == 321 and state.blocked == []
    assert co._runtime is None and co._prepared_window_identities == {}

    mutations = list(state.mutations)
    with pytest.raises(NativeSingleStepCoordinatorError, match="absent or consumed"):
        co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == mutations
    with pytest.raises(PermissionError):
        manager.maximize_bound_window()


@pytest.mark.parametrize("change", ["expiry", "replace", "pid", "creation", "executable"])
def test_invalidated_maximize_preview_has_no_window_effect(fresh_host, change):
    co, _manager, state, identity = fresh_host
    preview = _preview(co)
    if change == "expiry":
        co._window_preparations[preview["preparation_id"]]["expires_at"] = 0
    elif change == "replace":
        _preview(co)
    elif change == "pid":
        co._window_preparations[preview["preparation_id"]]["identity"]["process_id"] = 99
    elif change == "creation":
        identity["process_create_time"] += 1
    else:
        identity["executable_path"] = "c:\\other\\app.exe"
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == [] and co._runtime is None


def test_maximize_preview_does_not_mutate_returned_identity(fresh_host):
    co, _manager, state, identity = fresh_host
    preview = _preview(co)
    preview["identity"]["process_id"] = 99
    stored = co._window_preparations[preview["preparation_id"]]
    assert stored["identity"] == identity
    assert state.mutations == []
