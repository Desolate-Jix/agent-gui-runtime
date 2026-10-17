"""真实视觉提交能力与原序列回执离线绑定；所有桌面和网络边界均受控。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from app.core.input_sequence_partial import _digest, original_input_status
from app.execution.decision_check import decision_frame
from tests.test_local_step_timings import timed_scene
from tests.test_visual_field_proof import scene, FIELD, IDENTITY, NATIVE
from tests.test_visual_input_no_uia import visual_sequence


@pytest.fixture(autouse=True)
def forbid_real_input(monkeypatch):
    from app.core import input_controller
    def forbidden(*args, **kwargs):
        pytest.fail("离线提交观察测试禁止真实桌面输入")
    for name in ("_send_key", "_send_mouse_input", "_send_move", "_send_mouse_flags"):
        monkeypatch.setattr(input_controller.InputController, name, forbidden)
    if input_controller.win32api is not None:
        monkeypatch.setattr(input_controller.win32api, "SetCursorPos", forbidden)


def image_frame(root, name, *, changed=False):
    path = root / (name + ".png")
    image = Image.new("RGB", (180, 90), "white")
    if changed:
        ImageDraw.Draw(image).rectangle((30, 20, 140, 70), fill="navy")
    image.save(path)
    return {"capture_id": name, "image_path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(), "window_rect": [0, 0, 180, 90],
        "window_size": {"width": 180, "height": 90}, "window_identity": deepcopy(IDENTITY)}


@pytest.fixture
def submitted_sequence(visual_sequence, timed_scene, monkeypatch, tmp_path):
    from app.execution import input_sequence, local_direct_step as direct
    v = visual_sequence
    co, state, clock, _ = timed_scene
    from app.agent.native_identity import validate_native_identity_fact
    v.scene.focus["target_identity"] = validate_native_identity_fact(NATIVE, target_window_handle=10, expected_process_id=20)
    before, after = image_frame(tmp_path, "submit-before"), image_frame(tmp_path, "submit-after", changed=True)
    bound = co._windows().bind_window_by_handle(321)
    bound.handle, bound.process_id = 10, 20
    bound.rect = SimpleNamespace(left=0, top=0, right=180, bottom=90)
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader", lambda **kwargs:
        SimpleNamespace(read_identity=lambda handle: deepcopy(NATIVE)))
    class Capture:
        def __init__(self, **kwargs):
            pass
        def capture_window(self, **kwargs):
            return before
    monkeypatch.setattr(direct, "ScreenshotService", Capture)
    settings = {"wait": None, "context": None, "rule": None, "drop_target": False,
        "capture_error": False, "cancel_after_enter": False}
    capture_calls = []
    def capture_after(*args):
        capture_calls.append(1)
        if settings["capture_error"]:
            raise OSError("synthetic capture unavailable")
        return deepcopy(after)
    monkeypatch.setattr(direct, "_capture_observation", capture_after)
    # 替身路由独立提供前图，不承接真实 API 的发布前图回调。
    monkeypatch.setattr("app.core.settled_observation_scope.before_capture_sharing_eligible", lambda *args, **kwargs: False)
    waits = []
    def wait(seconds):
        waits.append(seconds)
        clock.advance(seconds * 1000)
        return False
    monkeypatch.setattr(co._cancel_wait, "wait", wait)
    original_run = input_sequence.run_input_sequence
    calls = []
    def run(coordinator, target, request, **kwargs):
        context = deepcopy(kwargs["action_review"])
        context["plan"].update(schema_version="task_plan.v3", goal="Search the fresh text")
        rule = {"kind": "agent_judgment", "decision_condition": "The requested search results are visible."}
        context["plan"]["steps"][0]["verification"] = rule
        context["plan"]["completion"] = {"step_id": context["step_id"], "verification": deepcopy(rule)}
        context = deepcopy(settings["context"] or context)
        if settings["rule"] is not None:
            context["plan"]["steps"][0]["verification"] = deepcopy(settings["rule"])
            context["plan"]["completion"]["verification"] = deepcopy(settings["rule"])
        kwargs["action_review"] = context
        kwargs["observation_wait_ms"] = settings["wait"]
        v.scene.context["execution_request_id"] = context["attempt_id"]
        original_execute = coordinator.execute_local_step
        def execute(**arguments):
            calls.append(arguments)
            if arguments.get("grounding_target") is None:
                return original_execute(**arguments)
            completed = original_execute(**arguments)
            def route(*unused):
                if settings["cancel_after_enter"]:
                    co._cancel_wait.set()
                return deepcopy(completed["response"])
            monkeypatch.setattr(direct, "_post_action", route)
            try:
                return co.execute_local_step(**{**arguments,
                    **({"grounding_target": None} if settings["drop_target"] else {})})
            except Exception:
                import traceback
                pytest.fail(traceback.format_exc())
        coordinator.execute_local_step = execute
        result = original_run(coordinator, target, request, **kwargs)
        command = {"kind": "input_sequence", "request": deepcopy(request), "field_evidence_mode": "visual",
            "action_review": context}
        if settings["wait"] is not None:
            command["observation_wait_ms"] = settings["wait"]
        return result, command
    monkeypatch.setattr(input_sequence, "run_input_sequence", run)
    return SimpleNamespace(run=v.run, v=v, co=co, clock=clock, waits=waits, calls=calls,
        settings=settings, before=before, after=after, capture_calls=capture_calls)


def effective_receipt(result, command):
    return {"status": "returned", "command": command, "result": result,
        "observation": deepcopy(result["observation"]["capture"])}


def early_receipt(result, command):
    from app.execution.task_plan_observation import CLOCK_ID
    local = result["steps"][-1]["receipt"]
    capture = local["observation"]["capture"]
    capture["observation_stage"] = "after_transition_observation"
    local["observation"].update(source="post_action", authorizes_action=False, render_grace_ms=2000,
        adaptive_wait={"schema": "adaptive_observation.v1", "budget_ms": 2000, "elapsed_ms": 400.0,
            "early": True, "reason": "changed_then_stable", "readiness": "unassessed",
            "effect_verified": False, "authorizes_action": False, "automatic_retry_allowed": False,
            "clock_id": CLOCK_ID, "started_ns": 1_000_000_000, "deadline_ns": 3_000_000_000,
            "samples": [{"image_path": capture["image_path"], "sha256": capture["sha256"]}]})
    result["observation"] = deepcopy(local["observation"])
    result["adaptive_submit"] = {"schema": "input_sequence_submit_observation.v1",
        "sequence_id": result["sequence_id"], "substep_index": 1,
        "execution_request_id": command["action_review"]["attempt_id"],
        "local_step_id": local["step_id"], "receipt_sha256": _digest(local)}
    return effective_receipt(result, command)


def test_real_visual_enter_uses_early_observation_and_focus_stays_zero(submitted_sequence):
    s = submitted_sequence
    result, command = s.run()
    assert result["status"] == "completed", result.get("error")
    assert original_input_status(effective_receipt(result, command), command, succeeded=True,
        action_executed=True, target_identity=IDENTITY) == "completed"
    assert s.calls[0]["observation_wait_ms"] == 0
    assert s.calls[-1]["observation_wait_ms"] is None
    assert result["observation"]["adaptive_wait"]["early"] is True
    assert 400 <= result["observation"]["adaptive_wait"]["elapsed_ms"] < 2000
    assert result["adaptive_submit"]["receipt_sha256"] == _digest(result["steps"][-1]["receipt"])
    from app.core.input_controller import VK_RETURN, VK_CONTROL, VK_V
    assert s.v.events.count((VK_RETURN,)) == s.v.events.count((VK_CONTROL, VK_V)) == 1


def test_grace_accepts_only_the_bound_final_visual_submit(submitted_sequence):
    from app.execution.task_plan_adaptive_grace import adaptive_grace
    result, command = submitted_sequence.run()
    receipt = early_receipt(result, command)
    frame = decision_frame(result["observation"]["capture"], IDENTITY, role="after")
    assert adaptive_grace(receipt, frame) == {"clock_id": result["observation"]["adaptive_wait"]["clock_id"],
        "started_ns": 1_000_000_000, "deadline_ns": 3_000_000_000, "budget_ms": 2000}


@pytest.mark.parametrize("scope", ["explicit_wait", "wait_policy", "native_condition", "video", "no_submit_capability"])
def test_other_wait_contracts_and_bare_sequence_kind_do_not_enable_early_observation(submitted_sequence, scope):
    s = submitted_sequence
    if scope == "explicit_wait":
        s.settings["wait"] = 2000
    elif scope == "wait_policy":
        s.settings["rule"] = {"kind": "agent_judgment", "decision_condition": "Search results are visible.",
            "wait_policy": {"loading_condition": "A loading panel is visible.", "completion_excludes_loading": True}}
    elif scope == "native_condition":
        s.settings["rule"] = {"kind": "native_condition", "condition": {"text": "Results", "control_type": "Text"}}
    elif scope == "video":
        s.settings["rule"] = {"kind": "video_playback", "decision_condition": "The selected video is playing."}
    else:
        s.settings["drop_target"] = True
    result, _ = s.run()
    assert result["status"] == "completed", result.get("error")
    assert s.waits == [2.0]
    assert "adaptive_wait" not in result["observation"] and "adaptive_submit" not in result
    assert s.calls[0]["observation_wait_ms"] == 0


@pytest.mark.parametrize("failure", ["capture_error", "cancel_after_enter"])
def test_observation_error_or_cancel_keeps_one_completed_enter_without_replay(submitted_sequence, failure):
    from app.core.input_controller import VK_RETURN, VK_CONTROL, VK_V
    s = submitted_sequence
    s.settings[failure] = True
    result, _ = s.run()
    assert result["status"] == "interrupted"
    assert result["interrupted_at"] == "search"
    assert "adaptive_submit" not in result
    assert s.v.events.count((VK_RETURN,)) == s.v.events.count((VK_CONTROL, VK_V)) == 1
    if failure == "cancel_after_enter":
        assert s.capture_calls == []


@pytest.mark.parametrize("damage", ["parent_id", "substep_hash", "substep_index", "substep_bool", "sequence_id", "local_id",
    "key_started", "key_tab", "key_events", "value_proof", "focus_instead", "extra_substep", "outer_frame", "source_frame", "plan_clear"])
def test_forged_or_wrong_stage_submit_cannot_open_grace(submitted_sequence, damage):
    from app.execution.task_plan_adaptive_grace import adaptive_grace
    result, command = submitted_sequence.run()
    receipt = early_receipt(result, command)
    frame = decision_frame(result["observation"]["capture"], IDENTITY, role="after")
    marker = result["adaptive_submit"]
    local = result["steps"][-1]["receipt"]
    submit = local["response"]["data"]["visual_submit"]
    if damage == "parent_id": marker["execution_request_id"] += "-other"
    elif damage == "substep_hash": marker["receipt_sha256"] = "f" * 64
    elif damage == "substep_index": marker["substep_index"] = 0
    elif damage == "substep_bool": marker["substep_index"] = True
    elif damage == "sequence_id": marker["sequence_id"] += "-other"
    elif damage == "local_id": marker["local_step_id"] += "-other"
    elif damage == "key_started": submit["key_dispatch"]["dispatch"] = "started"
    elif damage == "key_tab": submit["key_result"]["key"] = "Tab"
    elif damage == "key_events": submit["key_dispatch"]["events"] = []
    elif damage == "value_proof": submit["value_request_sha256"] = "f" * 64
    elif damage == "focus_instead": result["steps"][-1]["name"] = "focus_type"
    elif damage == "extra_substep": result["steps"].append(deepcopy(result["steps"][-1]))
    elif damage == "outer_frame": result["observation"]["capture"]["capture_id"] += "-other"
    elif damage == "plan_clear": command["action_review"]["plan"]["steps"][0]["action"]["clear_existing"] = False
    else: local["observation"]["capture"]["image_path"] = local["capture"]["image_path"]
    # 子步内容篡改即使重算公开摘要，也不能绕过真实 Enter 和父图绑定。
    if damage not in {"parent_id", "substep_hash", "substep_index", "substep_bool", "sequence_id", "local_id"}:
        marker["receipt_sha256"] = _digest(local)
    with pytest.raises(ValueError, match="task_plan_adaptive_grace_"):
        adaptive_grace(receipt, frame)


def test_submit_after_geometry_must_match_the_actual_substep(submitted_sequence):
    from app.execution.task_plan_adaptive_grace import adaptive_grace
    result, command = submitted_sequence.run()
    receipt = early_receipt(result, command)
    local = result["steps"][-1]["receipt"]
    local["observation"]["capture"]["window_rect"][0] += 1
    result["observation"] = deepcopy(local["observation"])
    result["adaptive_submit"]["receipt_sha256"] = _digest(local)
    receipt["observation"] = deepcopy(result["observation"]["capture"])
    frame = decision_frame(receipt["observation"], IDENTITY, role="after")
    with pytest.raises(ValueError, match="task_plan_adaptive_grace_binding_invalid"):
        adaptive_grace(receipt, frame)


def test_foreign_clock_cannot_resume_an_early_submit(submitted_sequence):
    from app.execution.task_plan_adaptive_grace import adaptive_grace
    result, command = submitted_sequence.run()
    receipt = early_receipt(result, command)
    local = result["steps"][-1]["receipt"]
    local["observation"]["adaptive_wait"]["clock_id"] = "old-process-clock"
    result["observation"] = deepcopy(local["observation"])
    result["adaptive_submit"]["receipt_sha256"] = _digest(local)
    frame = decision_frame(result["observation"]["capture"], IDENTITY, role="after")
    with pytest.raises(ValueError, match="clock_changed"):
        adaptive_grace(receipt, frame)


def queued_sequence(submitted_sequence, tmp_path, monkeypatch, *, final="success", unchanged=False):
    from app.core.json_snapshot import write_json_snapshot
    from app.execution import task_plan_observation as observation
    from tests import test_task_plan_runner as runner
    from tests.test_adaptive_grace_completion import GraceAssessment
    s = submitted_sequence
    action = {"kind": "input_sequence", "field_goal": FIELD["field_goal"], "text": FIELD["expected_text"],
        "clear_existing": True, "submit_search": True}
    rule = {"kind": "agent_judgment", "decision_condition": "The requested search results are visible."}
    plan = {"schema_version": "task_plan.v3", "title": "Search fresh text", "goal": "Search fresh text",
        "inputs": {}, "steps": [{"step_id": "search", "action": action, "verification": rule}],
        "completion": {"step_id": "search", "verification": deepcopy(rule)}}
    monkeypatch.setattr(runner, "TARGET", deepcopy(IDENTITY))
    service = GraceAssessment(final=final)
    task = runner.scene(tmp_path, monkeypatch, source=plan, decision=service)
    pending = task.runtime.backend.status(task.run_id)["pending"]
    s.settings["context"] = deepcopy(pending["suggested_command"]["action_review"])
    result, command = s.run()
    assert result["status"] == "completed", result.get("error")
    assert command == pending["suggested_command"]
    receipt = early_receipt(result, command)
    execution_id = pending["execution_request_id"]
    write_json_snapshot(tmp_path / "responses" / (execution_id + ".json"), receipt)
    clock = SimpleNamespace(seconds=1.4)
    monkeypatch.setattr(observation, "now_ns", lambda: int(clock.seconds * 1_000_000_000))
    captures = []
    def capture(coordinator, **kwargs):
        assert kwargs["wait_budget_exhausted"] is True
        assert kwargs["cancelled"]() is False
        captures.append(kwargs["observation_id"])
        current = image_frame(tmp_path, "final-readonly", changed=False)
        if unchanged:
            original = result["observation"]["capture"]
            from pathlib import Path
            path = tmp_path / "final-readonly.png"
            path.write_bytes(Path(original["image_path"]).read_bytes())
            current["sha256"] = sha256(path.read_bytes()).hexdigest()
        return {"frame": decision_frame(current, IDENTITY, role="observation"), "capture_elapsed_ms": 0.0}
    monkeypatch.setattr(observation, "capture_followup", capture)
    return SimpleNamespace(task=task, clock=clock, captures=captures, service=service,
        receipt=receipt, execution_id=execution_id, sequence=s)


@pytest.mark.parametrize("unchanged", [False, True])
def test_late_result_waits_original_deadline_once_and_reuses_identical_frame(
        submitted_sequence, tmp_path, monkeypatch, unchanged):
    from app.core.json_snapshot import read_json_snapshot
    from app.core.input_controller import VK_RETURN, VK_CONTROL, VK_V
    q = queued_sequence(submitted_sequence, tmp_path, monkeypatch, unchanged=unchanged,
        final="failure" if unchanged else "success")
    first = q.task.runtime.tick(force=True)
    assert first.get("observation_pending") is True and first["history"] == [], (first.get("wait") or {}).get("error")
    assert len(q.service.calls) == 1 and q.captures == []
    q.clock.seconds = 2.999
    assert q.task.runtime.tick(force=True).get("observation_pending") is True
    q.clock.seconds = 3.0
    final = q.task.runtime.tick(force=True)
    assert final["runner_state"] == ("failed" if unchanged else "completed")
    assert len(q.captures) == 1 and len(q.service.calls) == (1 if unchanged else 2)
    for _ in range(3):
        q.task.runtime.tick(force=True)
    assert len(q.captures) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    assert q.sequence.v.events.count((VK_RETURN,)) == q.sequence.v.events.count((VK_CONTROL, VK_V)) == 1
    assert read_json_snapshot(tmp_path / "responses" / (q.execution_id + ".json")) == q.receipt


def test_cancelled_grace_cannot_capture_or_repeat_enter(submitted_sequence, tmp_path, monkeypatch):
    from tests.test_task_plan_queued_cancel import queue_cancel
    q = queued_sequence(submitted_sequence, tmp_path, monkeypatch)
    assert q.task.runtime.tick(force=True).get("observation_pending") is True
    queue_cancel(q.task)
    q.clock.seconds = 3.0
    waiting = q.task.runtime.tick(force=True)
    assert waiting["history"] == [] and q.captures == [] and len(q.service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


@pytest.mark.parametrize("error", ["provider", "shape", "authentication"])
def test_result_model_errors_do_not_grant_submit_followup(submitted_sequence, tmp_path, monkeypatch, error):
    q = queued_sequence(submitted_sequence, tmp_path, monkeypatch)
    q.service.error = error
    result = q.task.runtime.tick(force=True)
    assert result["history"] == [] and result["runner_state"] != "completed"
    assert q.captures == [] and len(q.service.calls) == 1
