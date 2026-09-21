"""通用输入组合：复用单步执行与字段读取，检查失败即返回已完成部分。"""
from hashlib import sha256
from time import perf_counter, sleep
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class InputSequenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_goal: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=20000)
    clear_existing: bool = True
    submit_search: bool


class InputSequenceInterrupted(ValueError):
    pass


def _action_data(step):
    data = (step.get("response") or {}).get("data") or {}
    return data.get("result", data)


def _wait_for_focused_field(read):
    from app.agent.windows_text_field_reader import TextFieldReadError
    deadline = perf_counter() + .5
    while True:
        try:
            return read()
        except TextFieldReadError as error:
            remaining = deadline - perf_counter()
            # 点击后的 UIA 焦点发布可滞后；仅重读，不重放点击，不忽略身份或内容错误。
            if error.reason_code != "text_field_keyboard_focus_unavailable" or remaining <= 0:
                raise
            sleep(min(.025, remaining))


def _read_field(coordinator, target, point, capture, field_id, expected_identity):
    from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
    from app.agent.windows_text_field_reader import WindowsTextFieldReader

    def read():
        manager = coordinator._windows()
        bound = manager.bind_window_by_handle(target["handle"])
        identity_reader = WindowsNativeIdentityReader(window_manager=manager)
        identity = validate_native_identity_fact(identity_reader.read_identity(target["handle"]),
            target_window_handle=target["handle"], expected_process_id=target["process_id"])
        if bound is None or identity is None or identity != expected_identity:
            raise InputSequenceInterrupted("input_sequence_target_changed")
        rect = bound.rect
        size = capture.get("window_size") or {}
        if size != {"width": rect.right - rect.left, "height": rect.bottom - rect.top}:
            raise InputSequenceInterrupted("input_sequence_viewport_changed")
        # 单像素仅指定读取命中点；快照中的字段框来自真实 UIA，不能用此框证明定位。
        return WindowsTextFieldReader(window_manager=manager, native_identity_reader=identity_reader).read_field(
            target_field_id=field_id, capture_id=capture["sha256"],
            target_window_handle=target["handle"], target_process_id=target["process_id"],
            process_create_time=identity["process_create_time"],
            window_rect=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            target_bbox=(point["x"], point["y"], 1, 1),
            click_point=(point["x"], point["y"]), require_keyboard_focus=True)

    return _wait_for_focused_field(lambda: coordinator._owner.call(read))


def run_input_sequence(coordinator, target, request, *, observation_wait_ms=None, observation_condition=None, persist=None):
    """同一宿主串行命令内完成组合；不循环点击、不自动改写目标或重试输入。"""
    spec = InputSequenceRequest.model_validate(request)
    if target is None:
        raise ValueError("select a target window before input_sequence")
    from app.core.observation_policy import resolve_render_grace_ms
    if observation_wait_ms is not None:
        resolve_render_grace_ms("", observation_wait_ms)
    if observation_condition is not None:
        from .conditional_observation import validate_condition
        if not spec.submit_search:
            raise ValueError("input_sequence condition requires submit_search")
        observation_condition = validate_condition(observation_condition,
            resolve_render_grace_ms("press_enter", observation_wait_ms))
    group_id = "input-sequence-" + uuid4().hex
    started = perf_counter()
    result = {"contract_version": "input_sequence_v1", "sequence_id": group_id,
        "status": "running", "phase": "focus", "target": dict(target), "steps": [],
        "completed_steps": [], "interrupted_at": None, "input_check": {"status": "not_checked"},
        "capture": None, "observation": {"status": "not_requested"},
        "action_executed": False, "task_effect_verified": None, "automatic_retry_allowed": False,
        "text_length": len(spec.text), "text_sha256": sha256(spec.text.encode("utf-8")).hexdigest(),
        "submit_search": spec.submit_search}

    def checkpoint():
        result["total_ms"] = round((perf_counter() - started) * 1000, 3)
        if persist is not None:
            persist(result)

    def action(name, operation, payload, wait_ms):
        result["phase"] = name
        # 后图必须属于最后一次尝试，不能把上一步的图冒充本次输入后的图。
        result["observation"] = {"status": "unavailable", "reason": "action_in_progress"}
        row = {"name": name, "operation": operation, "status": "dispatching", "action_executed": None}
        result["steps"].append(row)
        checkpoint()
        at = perf_counter()
        try:
            step = coordinator.execute_local_step(target_window_handle=target["handle"],
                target_process_id=target["process_id"], operation=operation, request=payload,
                include_observation=True, observation_wait_ms=wait_ms,
                **({"observation_condition": observation_condition}
                   if name == "search" and observation_condition is not None else {}))
        except Exception:
            row["status"] = "result_unknown"
            result["action_executed"] = True if result["action_executed"] is True else None
            raise
        finally:
            row["elapsed_ms"] = round((perf_counter() - at) * 1000, 3)
        row.update(status=step.get("phase"), receipt=step)
        if result["capture"] is None:
            result["capture"] = step.get("capture")
        result["observation"] = step.get("observation") or {"status": "unavailable"}
        data = _action_data(step)
        dispatched = ((data.get("execution_path") or {}).get("action_executed", data.get("action_executed"))
                      if operation != "press_key" else data.get("pressed"))
        row["action_executed"] = dispatched if type(dispatched) is bool else None
        if dispatched is True:
            result["action_executed"] = True
        elif result["action_executed"] is not True and dispatched is None:
            result["action_executed"] = None
        checkpoint()
        if (step.get("response") or {}).get("success") is not True or dispatched is not True:
            raise InputSequenceInterrupted(name + "_input_not_confirmed")
        result["completed_steps"].append(name)
        if not (result["observation"].get("capture") or {}).get("sha256"):
            raise InputSequenceInterrupted(name + "_observation_unavailable")
        checkpoint()
        return data

    def read(name, point):
        result["phase"] = name
        checkpoint()
        at = perf_counter()
        try:
            capture = result["observation"]["capture"]
            expected_identity = result["steps"][-1]["receipt"].get("target_identity")
            snapshot = _read_field(coordinator, target, point, capture, group_id, expected_identity)
            result.setdefault("field_reads", []).append({"name": name, **snapshot.to_reference()})
            return snapshot
        except Exception as error:
            result["input_check"] = {"status": "unavailable", "phase": name,
                "reason": getattr(error, "reason_code", "field_read_failed")}
            raise
        finally:
            result.setdefault("check_timings", []).append({"name": name,
                "elapsed_ms": round((perf_counter() - at) * 1000, 3)})

    try:
        located = action("focus", "execute_recognition_plan", {
            "goal": spec.field_goal, "click_kind": "single"}, 0)
        point = located.get("selected_click_point")
        if (located.get("selected_click_point_coordinate_space") != "capture_image_pixels"
                or not isinstance(point, dict)
                or any(type(point.get(key)) is not int or point[key] < 0 for key in ("x", "y"))):
            raise InputSequenceInterrupted("focus_coordinate_unavailable")
        result["selected_click_point"] = dict(point)
        result["selected_click_point_coordinate_space"] = "capture_image_pixels"
        before = read("check_focus", point)
        if spec.clear_existing:
            expected = spec.text
        else:
            if before.selection is None:
                raise InputSequenceInterrupted("input_selection_unavailable")
            start, end = before.selection
            expected = before.value[:start] + spec.text + before.value[end:]
        action("type", "type_text", {"text": spec.text, **point,
            "click_before_typing": False, "clear_existing": spec.clear_existing}, 0)
        after = read("check_input", point)
        from app.agent.text_field_evidence import same_text_field_instance
        if not same_text_field_instance(after.identity, before.identity) or after.source != before.source:
            raise InputSequenceInterrupted("input_field_changed")
        if after.value != expected:
            result["input_check"] = {"status": "mismatch", "source": after.source,
                "expected_sha256": sha256(expected.encode("utf-8")).hexdigest(),
                "actual_sha256": sha256(after.value.encode("utf-8")).hexdigest()}
            raise InputSequenceInterrupted("input_value_mismatch")
        result["input_check"] = {"status": "matched", "source": after.source,
            "value_sha256": sha256(after.value.encode("utf-8")).hexdigest(), "read_id": after.read_id}
        result["completed_steps"].append("check_input")
        if spec.submit_search:
            action("search", "press_key", {"key": "Enter", **point}, observation_wait_ms)
        result.update(status="completed", phase="returned",
            next_action="inspect_returned_image_and_judge_task_effect")
    except Exception as error:
        # 组合可能已有输入，必须保留子步回执，不把整个命令伪装成零副作用。
        reason = (str(error) if isinstance(error, InputSequenceInterrupted)
                  else getattr(error, "reason_code", "input_sequence_failed"))
        result.update(status="interrupted", interrupted_at=result["phase"],
            error={"code": reason, "type": type(error).__name__},
            next_action="inspect_partial_steps_and_current_state_before_a_new_command")
    finally:
        checkpoint()
    return result
