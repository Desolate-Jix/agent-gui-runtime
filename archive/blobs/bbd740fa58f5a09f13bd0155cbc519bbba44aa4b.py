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


def _focus_field_binding(located, receipt, target):
    """将刚派发的 UIA 推荐绑定到原识别截图；纯像素目标不伪造字段身份。"""
    from pathlib import Path
    from app.agent.native_identity import validate_native_identity_fact
    from app.operation.recognition.control_target import uia_control_has_text_entry_patterns

    def invalid():
        raise InputSequenceInterrupted("input_field_binding_invalid")
    def mapping(value):
        if not isinstance(value, dict): invalid()
        return value
    plan = located.get("recognition_plan")
    if plan is None:
        return None
    plan = mapping(plan)
    chosen = mapping(plan.get("recommended_target"))
    element = mapping(chosen.get("element"))
    evidence = mapping(element.get("evidence") or {})
    action = evidence.get("screen_inventory_action")
    declared = (isinstance(action, dict) and action.get("source") == "windows_uia.controls"
                or "windows_uia.controls" in (element.get("sources") or []))
    if not declared:
        return None
    action = mapping(action)
    if action.get("source") != "windows_uia.controls" or not action.get("source_id"):
        invalid()
    selected_id = chosen.get("candidate_id")
    ranked = mapping(plan.get("candidate_result"))
    narrow = mapping(plan.get("narrow_search_result"))
    point = mapping(located.get("selected_click_point"))
    if (not selected_id or ranked.get("recommended_candidate_id") != selected_id
            or narrow.get("recommended_candidate_id") != selected_id
            or located.get("selected_click_point_coordinate_space") != "capture_image_pixels"
            or any(type(point.get(k)) is not int for k in ("x", "y"))):
        invalid()
    selected = [c for c in ranked.get("candidates", []) if isinstance(c, dict) and c.get("candidate_id") == selected_id]
    local = [c for c in narrow.get("results", []) if isinstance(c, dict) and c.get("candidate_id") == selected_id]
    if len(selected) != 1 or len(local) != 1 or local[0].get("refined_click_point") != point:
        invalid()
    selected_element = mapping(selected[0].get("element"))
    selected_action = mapping(mapping(selected_element.get("evidence")).get("screen_inventory_action"))
    if (selected_action.get("source") != "windows_uia.controls" or selected_action.get("source_id") != action["source_id"]
            or selected_element.get("bbox") != element.get("bbox")):
        invalid()
    parsed = mapping(plan.get("parse_result"))
    raw = mapping(mapping(parsed.get("execute_fast_inventory")).get("raw_uia_snapshot"))
    if raw.get("status") != "ok" or raw.get("scan_complete") is not True or raw.get("truncated") is not False:
        invalid()
    controls = [c for c in raw.get("controls", []) if isinstance(c, dict) and c.get("control_id") == action["source_id"]]
    if len(controls) != 1:
        invalid()
    control = controls[0]
    runtime_id, kind = control.get("runtime_id"), control.get("control_type")
    bbox = mapping(control.get("bbox"))
    if (type(runtime_id) not in (tuple, list) or not 1 <= len(runtime_id) <= 64
            or any(type(item) is not int for item in runtime_id) or kind not in {"Edit", "ComboBox"}
            or not uia_control_has_text_entry_patterns(control)
            or control.get("visible") is not True or control.get("enabled") is not True
            or bbox != element.get("bbox") or any(type(bbox.get(k)) is not int for k in ("x", "y", "w", "h"))
            or bbox["w"] <= 0 or bbox["h"] <= 0
            or not (bbox["x"] <= point["x"] < bbox["x"]+bbox["w"] and bbox["y"] <= point["y"] < bbox["y"]+bbox["h"])):
        invalid()
    identity = validate_native_identity_fact(receipt.get("target_identity"),
        target_window_handle=target["handle"], expected_process_id=target["process_id"])
    window = mapping(raw.get("window"))
    window_box = mapping(window.get("bbox"))
    reading = mapping(parsed.get("screen_reading"))
    capture = mapping(located.get("live_capture"))
    size = mapping(reading.get("image_size"))
    if (identity is None or window.get("handle") != target["handle"] or window.get("process_id") != target["process_id"]
            or any(type(window_box.get(k)) is not int for k in ("x", "y", "w", "h"))
            or size != {"width": window_box["w"], "height": window_box["h"]} or capture.get("window_size") != size
            or bbox["x"] < 0 or bbox["y"] < 0 or bbox["x"]+bbox["w"] > size["width"] or bbox["y"]+bbox["h"] > size["height"]):
        invalid()
    paths = [plan.get("image_path"), reading.get("image_path"), capture.get("image_path")]
    if any(not isinstance(p, str) or not p for p in paths):
        invalid()
    try:
        paths = [Path(p).resolve(strict=True) for p in paths]
        if len(set(paths)) != 1: invalid()
        digest = sha256(paths[0].read_bytes()).hexdigest()
    except (OSError, ValueError):
        raise InputSequenceInterrupted("input_field_binding_capture_unavailable") from None
    if capture.get("sha256") is not None and capture["sha256"] != digest:
        invalid()
    return {"contract_version": "input_sequence_field_binding_v1", "runtime_id": list(runtime_id),
        "control_type": kind, "bbox": dict(bbox), "source_control_id": action["source_id"],
        "source_capture_sha256": digest, "window_handle": target["handle"], "process_id": target["process_id"],
        "process_create_time": identity["process_create_time"],
        "window_rect": [window_box[k] for k in ("x", "y", "w", "h")]}


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


def _read_field(coordinator, target, point, capture, field_id, expected_identity, *, field_binding=None, post_input=False):
    from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    if type(post_input) is not bool or post_input and field_binding is None:
        raise InputSequenceInterrupted("input_field_post_input_binding_invalid")

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
        bound_rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        binding_args = {}
        bbox = (point["x"], point["y"], 1, 1)
        if field_binding is not None:
            if (field_binding["window_handle"] != target["handle"] or field_binding["process_id"] != target["process_id"]
                    or field_binding["process_create_time"] != identity["process_create_time"]
                    or tuple(field_binding["window_rect"]) != bound_rect):
                raise InputSequenceInterrupted("input_field_binding_changed")
            bbox = tuple(field_binding["bbox"][k] for k in ("x", "y", "w", "h"))
            binding_args = {"expected_runtime_id": tuple(field_binding["runtime_id"]),
                            "expected_control_type": field_binding["control_type"]}
            if post_input:
                binding_args["allow_post_input_geometry_rebind"] = True
        # 有本帧身份时使用原字段框；纯像素路径的单点不能充当字段定位证明。
        return WindowsTextFieldReader(window_manager=manager, native_identity_reader=identity_reader).read_field(
            target_field_id=field_id, capture_id=capture["sha256"],
            target_window_handle=target["handle"], target_process_id=target["process_id"],
            process_create_time=identity["process_create_time"],
            window_rect=bound_rect, target_bbox=bbox,
            click_point=(point["x"], point["y"]), require_keyboard_focus=True, **binding_args)

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
    field_binding = None
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
            snapshot = _read_field(coordinator, target, point, capture, group_id, expected_identity,
                **({"field_binding": field_binding, "post_input": name == "check_input"} if field_binding is not None else {}))
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
        result["phase"] = "check_focus"
        field_binding = _focus_field_binding(located, result["steps"][0]["receipt"], target)
        if field_binding is not None:
            result["field_binding"] = field_binding
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
        if after.identity.control_bbox != before.identity.control_bbox:
            # 布局演化仅是执行后读取证据，不修改原定位绑定或任何后续点击坐标。
            result["input_check"]["geometry_change"] = {"before_bbox": list(before.identity.control_bbox),
                "after_bbox": list(after.identity.control_bbox), "coordinate_space": "capture_image_pixels", "read_only": True}
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
        from app.agent.windows_text_field_reader import TextFieldReadError
        if isinstance(error, TextFieldReadError):
            # 仅透传读取器重新白名单投影后的阶段状态，不复制任意异常属性。
            diagnostic = TextFieldReadError.to_reference(error).get("diagnostic")
            if diagnostic:
                result["error"]["diagnostic"] = diagnostic
    finally:
        checkpoint()
    return result
