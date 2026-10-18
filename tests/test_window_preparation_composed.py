"""真实发布、宿主、串行拥有者与窗口原语；只替换系统边界。"""
from copy import deepcopy
from threading import get_ident, Event, Thread
from types import SimpleNamespace

import pytest

from app.agent.reviewed_workflow_asset import content_sha256
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_desktop_exact_review import _new_runtime, _complete, _record_dir, _load, _TOKEN
from tests.test_window_preparation_authority import scene


@pytest.fixture
def prepared_host(tmp_path, monkeypatch, scene):
    manager, state, identity, _reader = scene
    executable = tmp_path / "fixture.exe"
    executable.write_bytes(b"synthetic fixture; never execute")
    store, _service, facade, saved = _new_runtime(tmp_path)
    binding = {"kind": "native", "display_name": "Synthetic editor", "executable_identity": str(executable), "product_name": "Notepad"}
    compiled = _complete(facade, facade.prepare_exact_review("task", "exact-review-batch", saved["revision"], binding))
    asset = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")["asset"]
    facade.publish_exact_review(compiled["compile_receipt_id"])
    facade.close(); store.close()
    identity["executable_path"] = asset["application"]["executable_path"]
    calls = []
    def process(pid):
        assert pid == 12
        calls.append(get_ident())
        return SimpleNamespace(exe=lambda: identity["executable_path"], create_time=lambda: identity["process_create_time"])
    monkeypatch.setattr("psutil.Process", process)
    monkeypatch.setattr(manager, "list_visible_windows", lambda: [dict(handle=321, process_id=12, title="Synthetic editor", process_name="fixture.exe")])
    def no_launch(*_args, **_kwargs): raise AssertionError("unexpected process creation")
    monkeypatch.setattr("app.core.application_launch.subprocess", SimpleNamespace(Popen=no_launch))
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "root", _TOKEN)
    host.start()
    co = NativeSingleStepCoordinator(tmp_path / "root", host.facade, host,
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co._window_manager = manager
    selection = dict(asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset), target_window_handle=321, target_process_id=12)
    try:
        yield co, host, selection, manager, state, identity, calls
    finally:
        co.shutdown()


def test_actual_published_asset_prepares_on_same_owner_and_pins_process(prepared_host):
    co, host, selection, manager, state, identity, calls = prepared_host
    preview = co.preview_window_preparation(mode="focus", **selection)
    assert state.mutations == [] and co._runtime is None
    assert preview["executable_path"] == identity["executable_path"]
    outcome = co.confirm_window_preparation(preview["preparation_id"])
    assert outcome["status"] == "focused" and outcome["window"]["handle"] == 321
    assert state.active == 321 and state.blocked == []
    assert len(set(calls)) == 1 and calls[0] != get_ident()
    assert co._runtime is None and host.status().get("reviewed_single_step_enabled") is not True
    with pytest.raises(NativeSingleStepCoordinatorError, match="absent or consumed"):
        co.confirm_window_preparation(preview["preparation_id"])
    identity["process_create_time"] += 1
    from app.agent.runtime_session_selection import RuntimeSessionSelection
    with pytest.raises(NativeSingleStepCoordinatorError) as changed:
        co._owner.call(lambda: co._wait_foreground_on_owner(RuntimeSessionSelection(**selection), bind=True))
    assert changed.value.code == "window_preparation_identity_changed"


@pytest.mark.parametrize("intervening", ["preview", "inventory", "clear"])
def test_old_preparation_cannot_survive_replacement_or_refresh(prepared_host, intervening):
    co, _host, selection, _manager, state, _identity, _calls = prepared_host
    preview = co.preview_window_preparation(mode="focus", **selection)
    if intervening == "preview": co.preview_window_preparation(mode="focus", **selection)
    elif intervening == "inventory": co.inventory()
    else: co.clear_window_preparation()
    with pytest.raises(NativeSingleStepCoordinatorError):
        co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == []


def test_late_confirmation_cannot_interrupt_started_session_or_revive_after_cancel(prepared_host):
    from tests.test_native_single_step_coordinator import _Runtime
    co, host, selection, _manager, state, _identity, _calls = prepared_host
    preview = co.preview_window_preparation(mode="focus", **selection)
    runtime = _Runtime()
    co._runtime_factory = lambda **_kwargs: runtime
    co._uses_production_factory = False
    state.active = 321
    assert co.prepare(**selection)["phase"] == "observed"
    with pytest.raises(NativeSingleStepCoordinatorError): co.confirm_window_preparation(preview["preparation_id"])
    assert co._runtime is runtime and state.mutations == []
    assert co.cancel() == {"phase": "idle", "cleanup_verified": True}
    with pytest.raises(NativeSingleStepCoordinatorError): co.confirm_window_preparation(preview["preparation_id"])
    assert state.mutations == []


def test_actual_launch_path_tracks_exact_process_and_does_not_start_runtime(prepared_host, monkeypatch):
    co, _host, selection, manager, state, identity, _calls = prepared_host
    launched = []
    monkeypatch.setattr(manager, "list_visible_windows", lambda: ([dict(handle=321, process_id=12)] if launched else []))
    def popen(command):
        launched.append((command, get_ident()))
        return SimpleNamespace(pid=12)
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", popen)
    preview = co.preview_window_preparation(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    assert launched == []
    outcome = co.confirm_window_preparation(preview["preparation_id"])
    assert outcome["status"] == "launched_window_ready" and outcome["window"]["handle"] == 321
    assert launched == [([identity["executable_path"]], co._owner.call(get_ident))]
    assert co._runtime is None and state.mutations == []


def test_launcher_handoff_accepts_new_exact_executable_not_launcher_pid(prepared_host, monkeypatch):
    co, _host, selection, manager, state, _identity, _calls = prepared_host
    launched = []
    monkeypatch.setattr(manager, "list_visible_windows", lambda: ([dict(handle=321, process_id=12)] if launched else []))
    def popen(command):
        launched.append(command)
        return SimpleNamespace(pid=987)
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", popen)
    preview = co.preview_window_preparation(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_ready" and result["window"]["process_id"] == 12
    assert result["process_id"] == 987 and len(launched) == 1 and state.mutations == []


def test_failure_after_launch_keeps_effect_and_requires_fresh_inventory(prepared_host, monkeypatch):
    co, _host, selection, manager, state, _identity, _calls = prepared_host
    launched = []
    def windows():
        if launched: raise OSError("synthetic enumeration failure after launch")
        return []
    def popen(command):
        launched.append(command)
        return SimpleNamespace(pid=12)
    monkeypatch.setattr(manager, "list_visible_windows", windows)
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", popen)
    args = dict(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    preview = co.preview_window_preparation(**args)
    result = co.confirm_window_preparation(preview["preparation_id"])
    assert result["status"] == "launched_window_unavailable" and result["process_id"] == 12
    assert result["launch_effect_undone"] is False and result["result_unknown"] is True
    with pytest.raises(NativeSingleStepCoordinatorError) as failed: co.preview_window_preparation(**args)
    assert failed.value.code == "window_launch_requires_inventory"
    monkeypatch.setattr(manager, "list_visible_windows", lambda: [])
    co.inventory()
    co.preview_window_preparation(**args)
    assert len(launched) == 1 and state.mutations == []


def test_cancellation_during_launch_wait_retains_actual_launch_outcome(prepared_host, monkeypatch):
    co, _host, selection, manager, state, _identity, _calls = prepared_host
    entered, release = Event(), Event()
    def popen(command):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(pid=12)
    monkeypatch.setattr("app.core.application_launch.subprocess.Popen", popen)
    monkeypatch.setattr(manager, "list_visible_windows", lambda: [])
    preview = co.preview_window_preparation(mode="launch", asset_id=selection["asset_id"], asset_content_sha256=selection["asset_content_sha256"])
    result = []
    thread = Thread(target=lambda: result.append(co.confirm_window_preparation(preview["preparation_id"])))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(NativeSingleStepCoordinatorError) as busy: co.inventory()
        assert busy.value.code == "lifecycle_busy"
        co.cancel_waiting()
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive()
    assert result[0]["status"] == "launched_window_unavailable"
    assert result[0]["reason"] == "launch_effect_not_undone_after_cancel"
    assert state.mutations == [] and co._runtime is None
