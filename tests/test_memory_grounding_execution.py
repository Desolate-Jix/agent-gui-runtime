"""记忆目标只适配公共计划；当前上下文、几何和单次派发必须有效。"""
from contextvars import copy_context
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.core.local_recognition_policy import local_recognition_selection
from tests.test_local_step_timings import timed_scene as original_timed_scene


@pytest.fixture
def timed_scene(original_timed_scene, monkeypatch):
    from app.core.window_manager import WindowManager
    from app.execution import local_direct_step as direct
    co, state, clock, root = original_timed_scene
    manager = co._windows()
    bound = manager.bind_window_by_handle(321)
    bound.is_active = False
    manager.get_bound_window = lambda: bound
    manager.prepare_bound_window = lambda permit: WindowManager.prepare_bound_window(manager, permit)
    def focus():
        state.events.append("target_focus")
        if getattr(state, "focus_failure", False):
            raise PermissionError("window_focus_unverified")
        bound.is_active = not getattr(state, "focus_unconfirmed", False)
        if getattr(state, "geometry_drift", False):
            bound.rect.right += 1
        return bound
    manager.focus_bound_window = focus
    original_reader = direct.WindowsNativeIdentityReader
    def reader(**kwargs):
        native = original_reader(**kwargs)
        read = native.read_identity
        def current(handle):
            identity = read(handle)
            field = getattr(state, "identity_drift", None)
            if field and "target_focus" in state.events:
                identity[field] = {"process_id": 99, "process_create_time": 999.0,
                    "executable_path": "c:\\foreign\\other.exe"}[field]
            return identity
        native.read_identity = current
        return native
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader", reader)
    state.events.clear()
    return co, state, clock, root


@pytest.mark.parametrize("failure", [None, "focus_failure", "focus_unconfirmed", "geometry_drift",
    "process_id", "process_create_time", "executable_path", "occluded"])
def test_memory_capture_requires_verified_target_preparation(timed_scene, memory_scene, monkeypatch, failure):
    co, state, _, _ = timed_scene
    if failure in {"process_id", "process_create_time", "executable_path"}:
        state.identity_drift = failure
    elif failure:
        setattr(state, failure, True)
    def resolve(**kwargs):
        assert co._windows().get_bound_window().is_active is True
        state.events.append("memory_read")
        if failure == "occluded":
            from app.core.screenshot import CaptureVisibilityError
            raise CaptureVisibilityError("capture_window_occluded")
        return None, {"status": "miss", "reason": "target_absent"}
    monkeypatch.setattr("app.learning_memory.runtime_target.prepare_memory_grounding", lambda *args, **kwargs: resolve(**kwargs))
    def execute():
        return co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation="execute_recognition_plan", request={"goal": "Search", "target_memory": memory_scene[0]})
    if failure:
        with pytest.raises((PermissionError, ValueError)):
            execute()
        if failure == "occluded":
            assert state.events.count("memory_read") == 1
        else:
            assert "memory_read" not in state.events
        assert "route" not in state.events
    else:
        assert execute()["phase"] == "returned"
        assert state.events.count("target_focus") == 1
        assert state.events.index("target_focus") < state.events.index("memory_read")


def test_agent_proxy_prepares_target_through_real_common_entry(timed_scene, memory_scene, monkeypatch):
    from threading import Condition
    from types import SimpleNamespace
    from app.vision.agent_command_jobs import _CoordinatorProxy
    from app.core.local_input_policy import _local_operator_step_scope
    from app.execution import local_direct_step as direct
    co, state, _, _ = timed_scene
    monkeypatch.setattr(direct, "_local_operator_step_scope", _local_operator_step_scope)
    manager = SimpleNamespace(coordinator=co, _condition=Condition(), _update=lambda *args, **kwargs: None)
    job = SimpleNamespace(manager=manager, learning_context=None, cancelled=False, workflow_bindings=None)
    # 真实解析器拒绝缺失库；在此之前仍须完成单次身份绑定准备，且不能死锁。
    with pytest.raises(ValueError, match="memory_library_unavailable"):
        _CoordinatorProxy(job).execute_local_step(target_window_handle=321, target_process_id=12,
            operation="execute_recognition_plan", request={"goal": "Search", "target_memory": memory_scene[0]})
    assert state.events.count("target_focus") == 1
    assert "route" not in state.events


@pytest.fixture
def memory_scene(tmp_path):
    path = tmp_path / "current.png"
    Image.new("RGB", (180, 100), "white").save(path)
    reference = {"recipe_id": "target-recipe-" + "a" * 64,
                 "interface_key": "form", "state_key": "ready"}
    identity = {"target_window_handle": 10, "process_id": 20, "process_create_time": 30.0}
    frame = {"capture_id": "current-1", "image_path": str(path),
             "sha256": sha256(path.read_bytes()).hexdigest(),
             "image_size": {"width": 180, "height": 100},
             "window_identity": {"handle": 10, "process_id": 20, "process_create_time": 30.0}}
    resolution = {"status": "matched", "reason": "unique_current_target", "goal": "Search",
                  "strategy": "template", "frame": frame, "reference": reference,
                  "context_verified": True, "evidence": {"anchors": ["form-title"]},
                  "candidate": {"capture_id": "current-1", "viewport_size": frame["image_size"],
                                "source": "memory_template", "bbox": {"x": 20, "y": 30, "w": 60, "h": 20},
                                "click_point": {"x": 50, "y": 40}, "score": .99,
                                "freshness": "current_capture", "label": "Search", "role": "button"}}
    return reference, resolution, identity


def _target(scene, read_current=None):
    from app.core.memory_grounding_target import MemoryGroundingTarget
    reference, resolution, _ = scene
    return MemoryGroundingTarget(reference, resolution,
        read_current=read_current or (lambda image_path: deepcopy(resolution)))


def test_memory_plan_is_consumed_by_existing_geometry_selector(memory_scene):
    target = _target(memory_scene)
    _, resolution, identity = memory_scene
    plan = target.plan(image_path=resolution["frame"]["image_path"], goal="Search", identity=identity)
    selected = local_recognition_selection(plan, image_path=plan["image_path"],
                                          viewport_size={"width": 180, "height": 100})
    assert selected["selected_click_point"] == {"x": 50, "y": 40}
    assert selected["candidate_decisions"][0]["coordinate_source"] == "memory_template"
    assert plan["execution_path"]["vision_model_used"] is False
    assert plan["memory_evidence"]["context_verified"] is True
    assert plan["memory_evidence"]["task_effect_verified"] is None


@pytest.mark.parametrize("change", ["pid", "goal", "context", "point", "ambiguous", "frame", "reference"])
def test_memory_revalidation_rejects_stale_or_wrong_context(memory_scene, change):
    _, resolution, identity = memory_scene
    current = deepcopy(resolution)
    target = _target(memory_scene, lambda path: current)
    kwargs = {"image_path": resolution["frame"]["image_path"], "goal": "Search", "identity": identity}
    if change == "pid":
        identity["process_id"] += 1
    elif change == "goal":
        kwargs["goal"] = "Cancel"
    elif change == "context":
        current["context_verified"] = False
    elif change == "point":
        current["candidate"]["click_point"]["x"] += 1
    elif change == "ambiguous":
        current["status"] = "ambiguous"
    elif change == "frame":
        current["frame"]["sha256"] = "0" * 64
    else:
        current["reference"]["state_key"] = "other"
    with pytest.raises(ValueError, match="memory_grounding"):
        target.plan(**kwargs)
    assert target.input_claimed is False


def test_memory_dispatch_requires_plan_once_and_revokes_copied_scope(memory_scene):
    from app.core.memory_grounding_target import memory_grounding_scope, current_memory_grounding
    target = _target(memory_scene)
    point = {"x": 50, "y": 40}
    _, resolution, identity = memory_scene
    with pytest.raises(ValueError, match="plan_required"):
        target.before_dispatch(point, identity=identity)
    target.plan(image_path=resolution["frame"]["image_path"], goal="Search", identity=identity)
    with memory_grounding_scope(target):
        assert current_memory_grounding() is target
        copied = copy_context()
        target.before_dispatch(point, identity=identity)
        with pytest.raises(ValueError, match="already_claimed"):
            target.before_dispatch(point, identity=identity)
    assert current_memory_grounding() is None
    with pytest.raises(ValueError, match="scope_revoked"):
        copied.run(current_memory_grounding)


def test_memory_target_freezes_initial_resolution(memory_scene):
    _, resolution, identity = memory_scene
    fresh = deepcopy(resolution)
    target = _target(memory_scene, lambda path: fresh)
    resolution["candidate"]["click_point"]["x"] = 100
    result = target.plan(image_path=fresh["frame"]["image_path"], goal="Search", identity=identity)
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 50, "y": 40}


def test_memory_hit_never_prepares_local_visual_model(timed_scene, memory_scene):
    co, state, _, _ = timed_scene
    memory_scene[1]["frame"]["window_identity"].update(handle=321, process_id=12, process_create_time=123.5)
    receipt = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Search"}, memory_target=_target(memory_scene))
    assert receipt["phase"] == "returned"
    assert "configuration_load" not in state.events
    assert "model_prepare" not in state.events
    assert state.events.count("route") == 1


def test_memory_reference_is_resolved_before_model_preparation(timed_scene, memory_scene, monkeypatch):
    co, state, _, _ = timed_scene
    reference, resolution, _ = memory_scene
    resolution["frame"]["window_identity"].update(handle=321, process_id=12, process_create_time=123.5)
    target = _target(memory_scene)
    monkeypatch.setattr(co, "prepare_memory_grounding", lambda **kw: (target, deepcopy(resolution)), raising=False)
    receipt = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Search", "target_memory": reference})
    assert "configuration_load" not in state.events
    assert receipt["memory_resolution"]["status"] == "matched"
    assert state.events.count("route") == 1


def test_expected_memory_miss_uses_selected_local_route_and_reports_reason(timed_scene, memory_scene, monkeypatch):
    co, state, _, _ = timed_scene
    monkeypatch.setattr(co, "prepare_memory_grounding", lambda **kw:
                        (None, {"status": "miss", "reason": "target_absent", "candidate": None}), raising=False)
    receipt = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Search", "target_memory": memory_scene[0]})
    assert "model_prepare" in state.events
    assert receipt["memory_resolution"]["reason"] == "target_absent"
    assert state.events.count("route") == 1


def test_corrupt_memory_does_not_prepare_model_or_dispatch(timed_scene, memory_scene, monkeypatch):
    co, state, _, _ = timed_scene
    def invalid(**kwargs):
        raise ValueError("target_recipe_digest_mismatch")
    monkeypatch.setattr(co, "prepare_memory_grounding", invalid, raising=False)
    with pytest.raises(ValueError, match="digest_mismatch"):
        co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation="execute_recognition_plan", request={"goal": "Search", "target_memory": memory_scene[0]})
    assert "model_prepare" not in state.events
    assert "route" not in state.events


@pytest.mark.parametrize("changed", [False, True])
def test_memory_uses_common_action_route_and_rechecks_before_input(memory_scene, monkeypatch, changed):
    from types import SimpleNamespace
    from app.api import action, vision
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.desktop_review.local_action_contract import _validated_request
    from app.core.local_input_policy import _local_operator_input_scope
    from app.core.memory_grounding_target import memory_grounding_scope
    from app.core import local_text_focus

    _, resolution, identity = memory_scene
    current = deepcopy(resolution)
    frame = resolution["frame"]
    bound = SimpleNamespace(handle=10, process_id=20, title="Fixture", process_name="fixture.exe",
        rect=SimpleNamespace(left=0, top=0, right=180, bottom=100))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    native = {**identity, "contract_version": "windows_native_identity_observation_v1",
              "provider": "windows_native_identity", "status": "observed",
              "executable_path": "c:\\fixture\\fixture.exe"}
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw:
                        {"image_path": frame["image_path"], "window_size": frame["image_size"], "roi": None})
    monkeypatch.setattr(action, "prepare_browser_content", lambda *args: None)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(__import__("pathlib").Path(frame["image_path"]).parent / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    monkeypatch.setattr(vision, "recognition_plan", lambda *args: pytest.fail("memory hit invoked a visual model"))
    if changed:
        def invalidate(*args):
            current["context_verified"] = False
        monkeypatch.setattr(local_text_focus, "check_local_text_focus", invalidate)
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kw:
                        clicks.append((x, y)) or {"clicked": True, "point": {"x": x, "y": y}})
    target = _target(memory_scene, lambda path: current)
    request = ExecuteRecognitionPlanRequest.model_validate(_validated_request("execute_recognition_plan",
        {"goal": "Search", "enable_post_click_verification": False}))
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(native))
    with memory_grounding_scope(target), _local_operator_input_scope(manager=manager,
            identity_reader=reader, identity=native, window_rect=(0, 0, 180, 100), enabled=lambda: True):
        result = action.execute_recognition_plan(request)
    if changed:
        assert not result.success
        assert clicks == []
        assert not target.input_claimed
    else:
        assert result.success, result
        assert clicks == [(50, 40)]
        assert target.input_claimed
        assert result.data["result"]["recognition_plan"]["memory_evidence"]["context_verified"]


@pytest.mark.parametrize("source", ["agent_current", "external_api"])
def test_memory_hit_never_requests_agent_or_api_grounding(memory_scene, tmp_path, source):
    from app.vision.agent_command_jobs import AgentCommandJobs
    from app.vision.grounding_handoff import GroundingHandoffStore
    from app.vision.recognition_source import RecognitionSourceConfig
    from tests.test_agent_command_jobs import _Coordinator, _wait
    target = _target(memory_scene)
    co = _Coordinator()
    co.prepare_memory_grounding = lambda **kwargs: (target, deepcopy(memory_scene[1]))
    def no_vision(*args, **kwargs):
        raise AssertionError("memory hit requested vision handoff")
    store = GroundingHandoffStore(tmp_path, owner_id="memory-test")
    store.prepare = no_vision
    configuration = RecognitionSourceConfig(source=source, **({"api_profile": "fixture"} if source == "external_api" else {}))
    jobs = AgentCommandJobs(co, store, no_vision, configuration,
                            **({"api_grounder": no_vision} if source == "external_api" else {}))
    try:
        jobs.start("memory-job", {"kind": "step", "operation": "execute_recognition_plan",
            "request": {"goal": "Search", "target_memory": memory_scene[0]}},
            {"handle": 10, "process_id": 20},
            {"image_transport": "supported", "current_vision": "supported"})
        done = _wait(jobs, "memory-job", "completed")
        assert done["action_executed"] is True
        assert len(co.calls) == 1
        assert co.calls[0]["memory_target"] is target
        assert done.get("recognition_calls", []) == []
    finally:
        jobs.close()


def test_direct_api_never_silently_ignores_host_owned_memory_reference(memory_scene, monkeypatch):
    from types import SimpleNamespace
    from app.api import action, vision
    from app.api.models.request import ExecuteRecognitionPlanRequest
    monkeypatch.setattr(action, "window_manager", SimpleNamespace(get_bound_window=lambda: None))
    monkeypatch.setattr(vision, "recognition_plan", lambda *args: pytest.fail("unresolved recipe reached model"))
    result = action.execute_recognition_plan(ExecuteRecognitionPlanRequest.model_validate({
        "goal": "Search", "target_memory": memory_scene[0]}))
    assert result.success is False
    assert result.error.code == "target_memory_host_required"


def test_memory_preparation_cannot_rebind_during_another_local_step(timed_scene, memory_scene, monkeypatch):
    from app.core.local_input_policy import _local_operator_step_scope
    monkeypatch.setattr("app.desktop_review.local_direct_step._local_operator_step_scope",
                        _local_operator_step_scope)
    co = timed_scene[0]
    invoked = []
    monkeypatch.setattr("app.learning_memory.runtime_target.prepare_memory_grounding",
                        lambda *args, **kwargs: invoked.append(True))
    with _local_operator_step_scope(), pytest.raises(PermissionError, match="another local step"):
        co.prepare_memory_grounding(target_window_handle=10, target_process_id=20,
                                    request={"goal": "Search", "target_memory": memory_scene[0]})
    assert invoked == []


def test_dynamic_recipe_uses_frozen_trial_bindings_and_rejects_missing_bindings(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.learning_memory import runtime_target
    from app.learning_memory.target_recipe import action_semantics_sha256
    from tests.test_workflow_target_bindings import RULE
    reference = {"recipe_id": "target-recipe-" + "a" * 64,
                 "interface_key": "search", "state_key": "results"}
    scope = {"task_id": "memory-local", "interface_key": "search", "state_key": "results",
             "application": {"executable_name": "fixture.exe"},
             "anchors": [{"kind": "uia", "name": "结果页", "control_type": "Pane"}]}
    action = {"kind": "click", "goal": "打开结果", "target_memory": reference}
    recipe = {"scope": scope, "strategies": [RULE], "action_semantics_sha256":
              action_semantics_sha256(action, scope=scope, strategies=[RULE])}
    class Library:
        def __init__(self, root):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(runtime_target, "MemoryWorkspace", Library)
    monkeypatch.setattr(runtime_target, "load_target_recipe", lambda *args: recipe)
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation",
                        lambda *args, **kwargs: ({"capture_id": "current"}, {"uia": {}}))
    captured = []
    def resolve(*args, **kwargs):
        captured.append(deepcopy(kwargs["bindings"]))
        return {"status": "miss", "reason": "visible_row_missing", "goal": "打开结果",
                "reference": reference, "candidate": None, "frame": kwargs["frame"]}
    monkeypatch.setattr(runtime_target, "resolve_target_recipe", resolve)
    bound = SimpleNamespace(handle=10, process_id=20)
    coordinator = SimpleNamespace(_memory_library_root=tmp_path,
        _windows=lambda: SimpleNamespace(bind_window_by_handle=lambda handle: bound))
    request = {"goal": "打开结果", "target_memory": reference}
    with pytest.raises(ValueError, match="workflow_target_bindings_required"):
        runtime_target.prepare_memory_grounding(coordinator, request=request, handle=10, pid=20)
    bindings = {"run_id": "trial-now", "step_id": "open", "execution_request_id": "ticket-now",
        "command_sha256": "a" * 64, "action": action, "inputs": {"query": "本次编号42"}, "outputs": {}}
    target, resolution = runtime_target.prepare_memory_grounding(coordinator, request=request,
        handle=10, pid=20, memory_bindings=bindings)
    assert target is None and "本次编号42" in resolution["grounding_goal"]
    assert captured == [{key: bindings[key] for key in ("action", "run_id", "inputs", "outputs")}]
    rereads = []
    monkeypatch.setattr(runtime_target, "MemoryGroundingTarget",
        lambda ref, result, *, read_current: rereads.append(read_current) or object())
    monkeypatch.setattr(runtime_target, "resolve_target_recipe", lambda *args, **kwargs:
        captured.append(deepcopy(kwargs["bindings"])) or {
            "status": "matched", "reason": "unique_current_target", "goal": "打开结果",
            "reference": reference, "frame": kwargs["frame"], "candidate": {}})
    runtime_target.prepare_memory_grounding(coordinator, request=request,
        handle=10, pid=20, memory_bindings=bindings)
    bindings["inputs"]["query"] = "后改的编号"
    rereads[0]()
    assert captured[-1]["inputs"]["query"] == "本次编号42"


def test_local_memory_miss_uses_context_goal_without_changing_original_request(timed_scene, memory_scene, monkeypatch):
    from app.desktop_review import local_direct_step as direct
    co, state, _, _ = timed_scene
    original = {"goal": "Search", "target_memory": memory_scene[0]}
    observed = []
    route = direct._post_action
    monkeypatch.setattr(direct, "_post_action", lambda operation, request, manager:
                        observed.append(deepcopy(request)) or route(operation, request, manager))
    monkeypatch.setattr(co, "prepare_memory_grounding", lambda **kwargs: (None,
        {"status": "miss", "reason": "visible_row_missing", "candidate": None,
         "grounding_goal": "Search；本次编号42"}), raising=False)
    co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request=original)
    assert original["goal"] == "Search" and original["target_memory"] == memory_scene[0]
    assert observed[0]["goal"] == "Search；本次编号42"
    assert "target_memory" not in observed[0]
    assert "model_prepare" in state.events
