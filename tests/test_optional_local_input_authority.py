"""同一安全开关控制本地无学习输入；替换系统边界，不替换授权判断。"""
from copy import deepcopy
from contextvars import copy_context
from types import SimpleNamespace

import pytest

from app.core import input_controller as inputs
from app.core import window_manager as windows
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator


def test_direct_entry_is_available_without_a_learning_session(tmp_path):
    co = NativeSingleStepCoordinator(tmp_path, SimpleNamespace(list_reviewed_assets=lambda: []),
        SimpleNamespace(status=lambda: {"phase": "running"}), enable_agent_learning=False,
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    assert callable(getattr(co, "execute_local_step", None))
    assert co._learning_binding is None


@pytest.fixture
def local_scene(tmp_path, monkeypatch):
    from app.desktop_review import local_direct_step as direct
    from app.api import action

    identity = {"contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed", "target_window_handle": 321,
        "process_id": 12, "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=321, process_id=12, title="Synthetic editor", process_name="editor.exe",
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600))
    manager = SimpleNamespace(get_bound_window=lambda: bound,
        bind_window_by_handle=lambda handle: bound if handle == bound.handle else None)
    state = SimpleNamespace(calls=[], captures=0, identity=identity, callback=None, saved_context=None)
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader", lambda **kw:
        SimpleNamespace(read_identity=lambda handle: deepcopy(identity)))
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(inputs, "window_manager", manager)
    monkeypatch.setattr(inputs, "WINDOWS_INPUT_AVAILABLE", True)

    class Capture:
        def __init__(self, **kwargs):
            self.root = kwargs["capture_dir"]

        def capture_window(self, **kwargs):
            from PIL import Image
            state.captures += 1
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / "fresh.png"
            Image.new("RGB", (800, 600), "white").save(path)
            return {"image_path": str(path), "image_width": 800, "image_height": 600}

    monkeypatch.setattr(direct, "ScreenshotService", Capture)

    def type_text(text, **kwargs):
        if state.callback:
            state.callback()
        inputs.InputController()._ensure_windows_input()
        assert not inputs.runtime_backend_input_is_active()
        windows.WindowManager._ensure_window_mutation_authority(manager, preparation_handle=321)
        state.saved_context = copy_context()
        state.calls.append({"text": text, **kwargs})
        return {"typed": True}

    monkeypatch.setattr(action.input_controller, "type_text", type_text)
    factory = lambda **kwargs: None
    factory.window_manager = manager
    host = SimpleNamespace(status=lambda: {"phase": "ready", "base_url": "http://127.0.0.1:1"}, close=lambda: None)
    co = NativeSingleStepCoordinator(tmp_path, SimpleNamespace(list_reviewed_assets=lambda: []), host,
        runtime_factory=factory, enable_agent_learning=False,
        runtime_output_root=tmp_path / "runtime", thread_initializer=lambda: None, thread_finalizer=lambda: None)
    yield co, state, manager, direct
    co.shutdown()


def run_fill(co, **changes):
    request = {"text": "Google Maps", "x": 300, "y": 200, "click_before_typing": True,
               "submit": False, "clear_existing": False}
    request.update(changes)
    return co.execute_local_step(target_window_handle=321, target_process_id=12,
                                 operation="type_text", request=request)


def test_same_switch_off_executes_without_one_time_token_and_on_rejects(local_scene):
    co, state, _manager, _direct = local_scene
    with pytest.raises(Exception, match="automatic safety interception"):
        run_fill(co)
    assert state.captures == 0 and state.calls == []
    co.set_automatic_safety_interception(False)
    result = run_fill(co)
    assert result["response"]["success"] is True
    assert result["one_time_authority_required"] is False
    assert result["learning_enabled"] is False and len(state.calls) == 1
    assert co._learning_binding is None and co._runtime is None
    with pytest.raises(PermissionError, match="one-time"):
        inputs.InputController()._ensure_windows_input()
    with pytest.raises(PermissionError, match="one-time"):
        state.saved_context.run(inputs.InputController()._ensure_windows_input)
    co.set_automatic_safety_interception(True)
    with pytest.raises(Exception, match="automatic safety interception"):
        run_fill(co)
    assert len(state.calls) == 1


def test_local_replace_dispatches_existing_backend_and_keeps_submit_separate(local_scene):
    co, state, _manager, _direct = local_scene
    co.set_automatic_safety_interception(False)
    result = run_fill(co, text="\u5317\u4eac", clear_existing=True)
    assert result["response"]["success"] is True
    assert len(state.calls) == 1
    assert state.calls[0]["text"] == "\u5317\u4eac"
    assert state.calls[0]["clear_existing"] is True
    assert state.calls[0]["submit"] is False
    assert state.calls[0]["x"] == 300 and state.calls[0]["y"] == 200
    assert result["learning_enabled"] is False


def test_scope_closes_after_failure_and_does_not_leak_to_other_threads(local_scene):
    from concurrent.futures import ThreadPoolExecutor
    co, state, _manager, _direct = local_scene
    co.set_automatic_safety_interception(False)

    def callback():
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(inputs.InputController()._ensure_windows_input)
            with pytest.raises(PermissionError):
                future.result()
            current_context = copy_context()
            transferred = pool.submit(current_context.run, inputs.InputController()._ensure_windows_input)
            with pytest.raises(PermissionError):
                transferred.result()
        raise RuntimeError("synthetic backend failure")

    state.callback = callback
    result = run_fill(co)
    assert result["response"]["success"] is False and state.calls == []
    assert result["phase"] == "result_unknown" and result["automatic_retry_allowed"] is False
    with pytest.raises(PermissionError):
        inputs.InputController()._ensure_windows_input()
    state.callback = None
    assert run_fill(co)["response"]["success"] is True


def test_local_focus_permission_is_for_the_current_handle_only(local_scene):
    co, state, manager, _direct = local_scene
    co.set_automatic_safety_interception(False)

    def callback():
        with pytest.raises(PermissionError):
            windows.WindowManager._ensure_window_mutation_authority(manager, preparation_handle=888)
        with pytest.raises(PermissionError):
            windows.WindowManager._ensure_window_mutation_authority(manager,
                preparation_handle=321, preparation_operation="maximize")

    state.callback = callback
    assert run_fill(co)["response"]["success"] is True


def test_raw_route_cannot_use_the_coordinators_disabled_policy(local_scene):
    from app.api import action
    from app.api.models.request import TypeTextRequest
    co, state, _manager, _direct = local_scene
    co.set_automatic_safety_interception(False)
    response = action.type_text(TypeTextRequest(text="Google Maps", x=300, y=200,
        click_before_typing=True, metadata={"automatic_safety_interception": False}))
    assert response.success is False and state.calls == []


def test_click_request_forces_current_capture_and_trace_only(local_scene):
    _co, _state, _manager, direct = local_scene
    request = direct._validated_request("execute_recognition_plan", {"goal": "Google Maps"})
    assert request["capture_live"] is True and request["max_execution_attempts"] == 1
    assert request["learning_mode"] is None and request["agent_mode"] == "execute"
    assert request["write_policy"] == {"path_graph": False, "element_memory": False, "trace": True}
    for field in ("approved_plan_id", "interface_memory_id", "image_path"):
        with pytest.raises(ValueError, match="saved action sources"):
            direct._validated_request("execute_recognition_plan", {"goal": "Google Maps", field: "old"})


@pytest.mark.parametrize("metadata", [
    {"auto_observe_learning_artifacts": True},
    {"learning_artifacts": {"auto_observe": True}},
])
def test_metadata_cannot_start_learning_from_the_local_entry(local_scene, metadata):
    co, state, _manager, direct = local_scene
    co.set_automatic_safety_interception(False)
    with pytest.raises(ValueError, match="learning artifacts"):
        direct._validated_request("execute_recognition_plan", {"goal": "Google Maps", "metadata": metadata})
    assert state.captures == 0 and state.calls == []


@pytest.mark.parametrize("change", ["pid", "creation", "window", "geometry", "cancel"])
def test_current_window_and_cancellation_are_still_checked(local_scene, change):
    co, state, manager, _direct = local_scene
    co.set_automatic_safety_interception(False)

    def callback():
        if change == "pid": state.identity["process_id"] = 90
        elif change == "creation": state.identity["process_create_time"] += 1
        elif change == "window": manager.get_bound_window = lambda: SimpleNamespace(handle=999, process_id=12)
        elif change == "geometry": manager.get_bound_window().rect.right += 10
        else: co.cancel_waiting()

    state.callback = callback
    result = run_fill(co)
    assert result["response"]["success"] is False and state.calls == []
    assert "local safety-off input is unavailable" in result["response"]["error"]["details"]


@pytest.mark.parametrize("changes", [{"submit": True}, {"x": 900}, {"click_before_typing": False},
                                       {"automatic_safety_interception": False}])
def test_invalid_or_remote_policy_payload_cannot_open_input(local_scene, changes):
    co, state, _manager, _direct = local_scene
    co.set_automatic_safety_interception(False)
    with pytest.raises((ValueError, RuntimeError)):
        run_fill(co, **changes)
    assert state.calls == []


def test_two_coordinators_cannot_dispatch_on_the_desktop_concurrently(local_scene, tmp_path):
    co, state, manager, _direct = local_scene
    factory = lambda **kwargs: None
    factory.window_manager = manager
    other = NativeSingleStepCoordinator(tmp_path / "other", co._facade, co._host,
        runtime_factory=factory, enable_agent_learning=False, runtime_output_root=tmp_path / "other-output",
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    co.set_automatic_safety_interception(False)
    other.set_automatic_safety_interception(False)
    nested = []

    def callback():
        state.callback = None
        try:
            nested.append(run_fill(other))
        except PermissionError as error:
            nested.append(str(error))

    state.callback = callback
    try:
        result = run_fill(co)
        assert result["response"]["success"] is True
        assert len(nested) == 1 and isinstance(nested[0], str) and "another local step" in nested[0]
        assert len(state.calls) == 1
        assert run_fill(other)["response"]["success"] is True
    finally:
        other.shutdown()


def test_occluded_capture_still_prevents_dispatch(local_scene, monkeypatch):
    from app.core.screenshot import CaptureVisibilityError
    co, state, _manager, direct = local_scene
    co.set_automatic_safety_interception(False)

    def fail(**kwargs):
        raise CaptureVisibilityError("capture_window_occluded")

    monkeypatch.setattr(direct, "ScreenshotService", lambda **kw: SimpleNamespace(capture_window=fail))
    with pytest.raises(Exception, match="capture_window_occluded"):
        run_fill(co)
    assert state.calls == []


def test_local_enter_uses_existing_key_sender_without_typing_or_learning(local_scene, monkeypatch):
    co, state, manager, _direct = local_scene
    monkeypatch.setattr(inputs, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: 321))
    manager.validate_bound_point_visibility = lambda **kw: {"allowed": True}
    sent = []
    def send_key(self, key, *, key_up):
        self._ensure_windows_input()
        sent.append((key, key_up))
    monkeypatch.setattr(inputs.InputController, "_send_key", send_key)
    request = {"key": "Enter", "x": 300, "y": 200,
               "capture_roi": {"x": 0, "y": 0, "width": 700, "height": 500}}
    with pytest.raises(Exception):
        co.execute_local_step(target_window_handle=321, target_process_id=12, operation="press_key", request=request)
    assert sent == []
    co.set_automatic_safety_interception(False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12, operation="press_key", request=request)
    assert result["response"]["success"] is True
    assert sent == [(13, False), (13, True)] and state.calls == []
    assert co._runtime is None and co._learning_binding is None


def test_roi_coordinates_remain_window_relative_and_need_visible_evidence(local_scene):
    _co, _state, _manager, direct = local_scene
    capture = {"image_width": 400, "image_height": 300, "window_size": {"width": 800, "height": 600},
               "roi": {"x": 300, "y": 200, "width": 400, "height": 300}}
    direct._validate_coordinates({"x": 500, "y": 300}, capture)
    with pytest.raises(ValueError):
        direct._validate_coordinates({"x": 100, "y": 300}, capture)


def test_enter_does_not_retarget_a_background_window(local_scene, monkeypatch):
    co, state, manager, _direct = local_scene
    monkeypatch.setattr(inputs, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: 999))
    manager.validate_bound_point_visibility = lambda **kw: {"allowed": True}
    sent = []
    monkeypatch.setattr(inputs.InputController, "_send_key", lambda *a, **k: sent.append(True))
    co.set_automatic_safety_interception(False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12, operation="press_key",
        request={"key": "Enter", "x": 300, "y": 200})
    assert result["response"]["success"] is False and sent == [] and state.calls == []


@pytest.mark.parametrize("key", ["Win", "Ctrl+L", "Enter\n"])
def test_local_keyboard_entry_does_not_expand_to_arbitrary_hotkeys(local_scene, key):
    _co, _state, _manager, direct = local_scene
    with pytest.raises(ValueError):
        direct._validated_request("press_key", {"key": key, "x": 300, "y": 200})


def test_local_text_accepts_explicit_capture_region_without_changing_input_coordinates(local_scene):
    co, state, _manager, _direct = local_scene
    co.set_automatic_safety_interception(False)
    result = run_fill(co, capture_roi={"x": 200, "y": 100, "width": 500, "height": 400})
    assert result["response"]["success"] is True
    assert result["request"]["capture_roi"] == {"x": 200, "y": 100, "width": 500, "height": 400}
    assert state.calls[0]["x"] == 300 and state.calls[0]["y"] == 200


def test_recognition_prepares_configured_model_before_dispatch_and_releases(local_scene, monkeypatch):
    from app.vision import configuration, model_service
    co, state, _manager, direct = local_scene
    co._uses_production_factory = True
    events = []
    snapshot = object()
    frozen = object()
    monkeypatch.setattr(configuration, "load_formal_vision_configuration", lambda path: snapshot)
    monkeypatch.setattr(model_service, "freeze_model_service", lambda value: frozen if value is snapshot else None)
    from contextlib import contextmanager
    @contextmanager
    def pinned(value):
        assert value is snapshot
        events.append("config-pinned")
        yield
    monkeypatch.setattr(configuration, "pinned_vision_configuration", pinned)
    co._prepare_model_service_on_owner = lambda value: events.append("prepare") if value is frozen else None
    co._release_model_service = lambda **kwargs: events.append("release")
    monkeypatch.setattr(direct, "_post_action", lambda *args: events.append("dispatch") or {"success": True})
    co.set_automatic_safety_interception(False)
    co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "open link"})
    assert events == ["prepare", "config-pinned", "dispatch", "release"]


def test_model_preparation_failure_never_falls_through_to_weak_inventory(local_scene, monkeypatch):
    from app.vision import configuration, model_service
    co, state, _manager, _direct = local_scene
    co._uses_production_factory = True
    monkeypatch.setattr(configuration, "load_formal_vision_configuration", lambda path: object())
    monkeypatch.setattr(model_service, "freeze_model_service", lambda value: object())
    def prepare(value):
        raise RuntimeError("configured model unavailable")
    co._prepare_model_service_on_owner = prepare
    co.set_automatic_safety_interception(False)
    with pytest.raises(RuntimeError, match="configured model unavailable"):
        co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation="execute_recognition_plan", request={"goal": "open link"})
    assert state.captures == 0 and state.calls == []
