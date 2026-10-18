from __future__ import annotations

import pytest

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from tests.test_window_preparation_composed import prepared_host
from tests.test_window_preparation_authority import scene  # 注册 prepared_host 的场景依赖


def test_expired_or_wrong_asset_preparation_rejects_before_os_effect(prepared_host):
    co, _host, selection, _manager, state, _identity, _calls = prepared_host
    with pytest.raises(NativeSingleStepCoordinatorError) as wrong:
        co.preview_window_preparation(mode="focus", asset_id=selection["asset_id"],
            asset_content_sha256="0" * 64, target_window_handle=321, target_process_id=12)
    assert wrong.value.code == "window_preparation_asset_changed"
    preview = co.preview_window_preparation(mode="focus", **selection)
    co._window_preparations[preview["preparation_id"]]["expires_at"] = 0
    with pytest.raises(NativeSingleStepCoordinatorError) as expired:
        co.confirm_window_preparation(preview["preparation_id"])
    assert expired.value.code == "window_preparation_expired"
    assert state.mutations == [] and co._runtime is None


def test_native_identity_drift_between_preview_and_confirm_has_no_focus_effect(prepared_host):
    co, _host, selection, _manager, state, identity, _calls = prepared_host
    preview = co.preview_window_preparation(mode="focus", **selection)
    identity["process_create_time"] += 1
    with pytest.raises(NativeSingleStepCoordinatorError) as changed:
        co.confirm_window_preparation(preview["preparation_id"])
    assert changed.value.code == "window_preparation_identity_changed"
    assert state.mutations == [] and co._runtime is None


def test_popen_failure_is_unknown_single_effect_and_requires_inventory(prepared_host, monkeypatch):
    co, _host, selection, manager, state, _identity, _calls = prepared_host
    launches = []
    def popen(command):
        launches.append(command)
        raise OSError("synthetic Popen failure")
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", popen)
    args = {"mode": "launch", "asset_id": selection["asset_id"], "asset_content_sha256": selection["asset_content_sha256"]}
    preview = co.preview_window_preparation(**args)
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_unavailable"
    assert result["result_unknown"] is True and result["launch_effect_undone"] is False
    assert len(launches) == 1
    with pytest.raises(NativeSingleStepCoordinatorError) as blocked:
        co.preview_window_preparation(**args)
    assert blocked.value.code == "window_launch_requires_inventory"
    co.inventory()
    assert state.mutations == [] and co._runtime is None


def test_multiple_new_exact_executable_windows_are_ambiguous_without_focus(prepared_host, monkeypatch):
    from app.core import window_manager as wm
    co, _host, selection, manager, state, identity, _calls = prepared_host
    monkeypatch.setattr(wm.win32gui, "IsWindow", lambda handle: handle in {321, 501, 502})
    launched = []
    monkeypatch.setattr(manager, "list_visible_windows", lambda: ([
        {"handle": 501, "process_id": 12, "title": "Synthetic editor", "process_name": "fixture.exe"},
        {"handle": 502, "process_id": 12, "title": "Synthetic editor", "process_name": "fixture.exe"},
    ] if launched else []))
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", lambda command: launched.append(command) or type("P", (), {"pid": 987})())
    preview = co.preview_window_preparation(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_unavailable" and result["reason"] == "launched_window_ambiguous"
    assert state.mutations == [] and co._runtime is None


def test_existing_window_is_not_claimed_as_new_launch_success(prepared_host, monkeypatch):
    co, _host, selection, _manager, state, _identity, _calls = prepared_host
    launches = []
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", lambda command: launches.append(command) or type("P", (), {"pid": 987})())
    preview = co.preview_window_preparation(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    co._WINDOW_PREPARATION_TTL_SECONDS = 0.02
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_unavailable" and result["reason"] == "launched_window_timeout"
    assert len(launches) == 1 and state.mutations == []

