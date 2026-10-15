"""通用输入组合：复用单步执行与字段读取，检查失败即返回已完成部分。"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter, perf_counter_ns, sleep
from uuid import uuid4

from app.core.input_sequence_contract import InputSequenceRequest
from app.core.vision_admission_contract import AgentCommandCancelled


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
    geometry = mapping(receipt.get("target_window_geometry"))
    screen_rect = geometry.get("rect")
    if (geometry.get("coordinate_space") != "screen_pixels" or geometry.get("rect_format") != "ltrb"
            or type(screen_rect) not in (list, tuple) or len(screen_rect) != 4
            or any(type(value) is not int for value in screen_rect)):
        invalid()
    left, top, right, bottom = screen_rect
    reading = mapping(parsed.get("screen_reading"))
    capture = mapping(located.get("live_capture"))
    size = mapping(reading.get("image_size"))
    if (identity is None or window.get("handle") != target["handle"] or window.get("process_id") != target["process_id"]
            or any(type(window_box.get(k)) is not int for k in ("x", "y", "w", "h"))
            or window_box != {"x": 0, "y": 0, "w": right - left, "h": bottom - top}
            or right <= left or bottom <= top
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
    except AgentCommandCancelled:
        raise
    except (OSError, ValueError):
        raise InputSequenceInterrupted("input_field_binding_capture_unavailable") from None
    if capture.get("sha256") is not None and capture["sha256"] != digest:
        invalid()
    return {"contract_version": "input_sequence_field_binding_v1", "runtime_id": list(runtime_id),
        "control_type": kind, "bbox": dict(bbox), "source_control_id": action["source_id"],
        "source_capture_sha256": digest, "window_handle": target["handle"], "process_id": target["process_id"],
        "process_create_time": identity["process_create_time"],
        # UIA 框是截图坐标；屏幕原点只取同一步原生身份范围固定的窗口几何。
        "window_rect": [left, top, right - left, bottom - top]}


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


def _read_local_focus(coordinator, target, capture, field_id, binding, expected_identity):
    from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
    from app.agent.windows_text_field_reader import WindowsTextFieldReader

    def read():
        manager = coordinator._windows()
        identity = validate_native_identity_fact(WindowsNativeIdentityReader(
            window_manager=manager).read_identity(target["handle"]),
            target_window_handle=target["handle"], expected_process_id=target["process_id"])
        if (identity is None or identity != expected_identity
                or identity["process_create_time"] != binding["process_create_time"]):
            raise InputSequenceInterrupted("input_sequence_target_changed")
        return WindowsTextFieldReader(window_manager=manager,
            native_identity_reader=WindowsNativeIdentityReader(window_manager=manager)).read_bound_focus(
                target_field_id=field_id, capture_id=capture["sha256"],
                target_window_handle=target["handle"], target_process_id=target["process_id"],
                process_create_time=binding["process_create_time"], window_rect=tuple(binding["window_rect"]),
                expected_runtime_id=tuple(binding["runtime_id"]), expected_control_type=binding["control_type"])
    return _wait_for_focused_field(lambda: coordinator._owner.call(read))


def run_input_sequence(coordinator, target, request, *, observation_wait_ms=None, observation_condition=None, persist=None,
                       _tab_from=None, _expected_label=None, _on_field_complete=None, _prefer_current_uia=False,
                       _declared_label=None, memory_bindings=None, learning_context=None,
                        field_evidence_mode="legacy", visual_field_context=None,
                        action_review=None, action_review_deadline_ns=None, field_review_handler=None):
    """同一宿主串行命令内完成组合；不循环点击、不自动改写目标或重试输入。"""
    learning_context = deepcopy(learning_context) if learning_context is not None else None
    spec = InputSequenceRequest.model_validate(request)
    if field_evidence_mode not in {"legacy", "visual"}:
        raise ValueError("visual_field_evidence_mode_invalid")
    visual = field_evidence_mode == "visual"
    if visual:
        if (not isinstance(visual_field_context, dict) or visual_field_context.get("field_kind") not in {
                "text", "search", "address_bar"}
                or spec.submit_search and visual_field_context["field_kind"] not in {"search", "address_bar"}
                or spec.target is not None or spec.target_memory is not None or _tab_from is not None
                or _prefer_current_uia or _on_field_complete is not None or learning_context is not None):
            raise ValueError("visual_field_route_unsupported")
        from .visual_field_proof import _deadline
        _deadline(visual_field_context)
        native_evidence = visual_field_context.get("native_field_evidence", False)
        if type(native_evidence) is not bool:
            raise ValueError("visual_field_native_evidence_mode_invalid")
        visual_field_context = {**visual_field_context,
            "native_field_evidence": native_evidence,
            "review_context": deepcopy(visual_field_context.get("review_context"))}
        if not spec.clear_existing:
            raise ValueError("visual_field_append_requires_explicit_native_route")
        visual_field_context.pop("field_content_check", None)
        visual_field_context.pop("field_content_ocr", None)
    elif visual_field_context is not None:
        raise ValueError("visual_field_context_requires_explicit_visual_mode")
    compound_visual = visual and not native_evidence
    if spec.target is not None:
        if (spec.target_memory is not None or _tab_from is not None
                or _declared_label is not None and _declared_label != spec.target["name"]):
            raise ValueError("task_plan_target_input_route_conflict")
        _declared_label = spec.target["name"]
    if memory_bindings is not None:
        if not isinstance(memory_bindings, dict) or spec.target_memory is None:
            raise ValueError("workflow_target_bindings_invalid")
        bound = memory_bindings.get("action")
        if (not isinstance(bound, dict) or bound.get("kind") != "input_sequence"
                or bound.get("target_memory") != spec.target_memory
                or bound.get("field_goal") != spec.field_goal
                or bound.get("submit_search") is not spec.submit_search
                or bound.get("clear_existing") is not spec.clear_existing):
            raise ValueError("workflow_target_action_mismatch")
        from app.learning_memory.target_selectors import _value
        expected_text = _value(bound.get("text"), {key: memory_bindings[key]
            for key in ("run_id", "inputs", "outputs")})
        if expected_text != spec.text:
            raise ValueError("workflow_target_input_mismatch")
    if _tab_from is not None and (spec.submit_search or not _expected_label):
        raise ValueError("internal tab continuation requires a named fill-only field")
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
    local_binding = None
    started_actions = []
    focus_read_error = None
    visual_focus_readonly_error = None
    visual_focus_readonly_stage = None
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

    def action(name, operation, payload, wait_ms, *, keyboard_target=None, focus_target=None, memory_action=None, grounding_target=None):
        result["phase"] = name
        # 后图必须属于最后一次尝试，不能把上一步的图冒充本次输入后的图。
        result["observation"] = {"status": "unavailable", "reason": "action_in_progress"}
        row = {"name": name, "operation": operation, "status": "dispatching", "action_executed": None}
        result["steps"].append(row)
        checkpoint()
        at = perf_counter()
        try:
            started_actions.append(name)
            step = coordinator.execute_local_step(target_window_handle=target["handle"],
                target_process_id=target["process_id"], operation=operation, request=payload,
                include_observation=True, observation_wait_ms=wait_ms,
                **({"keyboard_target": keyboard_target} if keyboard_target is not None else {}),
                **({"focus_target": focus_target} if focus_target is not None else {}),
                **({"grounding_target": grounding_target} if grounding_target is not None else {}),
                 **({key: value for key, value in {"action_review": action_review,
                     "action_review_deadline_ns": action_review_deadline_ns}.items() if value is not None}
                    if name in {"focus", "focus_type"} or grounding_target is not None else {}),
                **({"memory_action": memory_action, "memory_bindings": memory_bindings}
                   if memory_action is not None and memory_bindings is not None else
                   {"memory_action": memory_action} if memory_action is not None else {}),
                **({"observation_condition": observation_condition}
                   if name == "search" and observation_condition is not None else {}),
                **({"learning_context": learning_context} if learning_context is not None else {}))
        except AgentCommandCancelled:
            raise
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
        from app.core.local_step_no_dispatch import pre_capture_failure_verified
        if pre_capture_failure_verified(step, operation):
            dispatched = False
        if dispatched is False:
            from app.core.recognition_dispatch import local_receipt_zero_input_verified
            if not local_receipt_zero_input_verified(step, operation):
                dispatched = None
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
        nonlocal focus_read_error
        result["phase"] = name
        checkpoint()
        at = perf_counter()
        try:
            capture = result["observation"]["capture"]
            expected_identity = result["steps"][-1]["receipt"].get("target_identity")
            snapshot = (_read_local_focus(coordinator, target, capture, group_id, local_binding,
                expected_identity) if local_binding is not None else _read_field(
                    coordinator, target, point, capture, group_id, expected_identity,
                    **({"field_binding": field_binding, "post_input": name == "check_input"}
                       if field_binding is not None else {})))
            patterns = snapshot.pattern_evidence
            result.setdefault("field_reads", []).append({"name": name, **snapshot.to_reference(),
                **({"pattern_evidence": patterns.to_reference()} if patterns is not None else {})})
            if name == "check_focus" and spec.clear_existing is False and snapshot.selection is None:
                from app.agent.windows_text_field_reader import TextFieldReadError
                raise TextFieldReadError("text_field_selection_unavailable")
            return snapshot
        except AgentCommandCancelled:
            raise
        except Exception as error:
            from app.agent.windows_text_field_reader import TextFieldReadError
            if name == "check_focus" and isinstance(error, TextFieldReadError):
                focus_read_error = error
            result["input_check"] = {"status": "unavailable", "phase": name,
                "reason": getattr(error, "reason_code", "field_read_failed")}
            raise
        finally:
            result.setdefault("check_timings", []).append({"name": name,
                "elapsed_ms": round((perf_counter() - at) * 1000, 3)})

    try:
        from app.core.local_text_focus import LocalTextFocusTarget, VisualTextFocusTarget
        focus_type = VisualTextFocusTarget if visual else LocalTextFocusTarget
        focus_target = focus_type(target["handle"], target["process_id"],
            expected_label=_declared_label)
        if compound_visual:
            from app.core.visual_compound_input import bind_visual_compound_input
            bind_visual_compound_input(focus_target, text=spec.text, context=visual_field_context, field_goal=spec.field_goal)
        if _tab_from is None:
            focus_metadata = {}
            if _prefer_current_uia:
                focus_metadata["text_focus_route"] = "current_uia_primary"
            if spec.target is not None:
                focus_metadata["task_plan_target"] = deepcopy(spec.target)
            located = action("focus_type" if compound_visual else "focus", "execute_recognition_plan", {
                "goal": spec.field_goal, "click_kind": "single",
                **({"target_memory": spec.target_memory} if spec.target_memory is not None else {}),
                **({"metadata": focus_metadata} if focus_metadata else {})},
                0, focus_target=focus_target,
                memory_action=({"kind": "input_sequence", "field_goal": spec.field_goal,
                                "submit_search": spec.submit_search} if spec.target_memory is not None else None))
        else:
            from app.core.local_keyboard_target import LocalKeyboardTarget
            previous, previous_kind = _tab_from
            x, y, w, h = previous.identity.control_bbox
            anchor = (x + w // 2, y + h // 2)
            keyboard = LocalKeyboardTarget(previous, previous_kind, anchor, "press_key",
                focus_reflow=True, key="Tab")
            action("focus_next", "press_key", {"key": "Tab", "x": anchor[0], "y": anchor[1]}, 0,
                keyboard_target=keyboard)
            from app.agent.windows_text_field_reader import probe_tab_focus_target
            local_binding = coordinator._owner.call(lambda: probe_tab_focus_target(
                coordinator._windows(), target["handle"], target["process_id"],
                _expected_label, previous.identity))
            x, y, w, h = local_binding["bbox"]
            located = {"selected_click_point": {"x": x + w // 2, "y": y + h // 2},
                "selected_click_point_coordinate_space": "capture_image_pixels"}
            result["focus_route"] = "tab_then_exact_accessible_label"
        point = located.get("selected_click_point")
        if (located.get("selected_click_point_coordinate_space") != "capture_image_pixels"
                or not isinstance(point, dict)
                or any(type(point.get(key)) is not int or point[key] < 0 for key in ("x", "y"))):
            raise InputSequenceInterrupted("focus_coordinate_unavailable")
        if _tab_from is None:
            result["selected_click_point"] = dict(point)
            result["selected_click_point_coordinate_space"] = "capture_image_pixels"
        else:
            result["local_focus_binding"] = dict(local_binding)
        result["phase"] = "check_focus"
        if visual:
            from app.agent.windows_text_field_reader import TextFieldReadError
            from .visual_field_proof import (assess_visual_field, read_visual_value,
                read_visual_focus_snapshot, assess_visual_selection, assess_visual_field_freshness,
                VisualFieldReviewRequired)
            from .decision_check import _candidate, _identity
            from app.core.local_keyboard_target import issue_visual_keyboard_target
            focus_receipt = result["steps"][0]["receipt"]
            candidate = (located.get("recognition_plan") or {}).get("recommended_target")
            rect = focus_receipt["target_window_geometry"]["rect"]
            expected_field = {"field_goal": spec.field_goal, "bbox": _candidate(candidate, point)["bbox"],
                "click_point": deepcopy(point), "window_identity": _identity(focus_receipt["target_identity"]),
                "window_rect": [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]],
                "field_kind": visual_field_context["field_kind"], "expected_text": spec.text}
            result["field_evaluations"] = []
            def evaluate_field(stage, callback):
                row = {"stage": stage, "status": "started"}
                result["field_evaluations"].append(row)
                at = perf_counter()
                try:
                    proof = callback()
                    reference = proof.to_reference()
                    row.update(status="adopted", request_sha256=reference["request_sha256"])
                    return proof, reference
                except VisualFieldReviewRequired as error:
                    handoff = VisualFieldReviewRequired.to_reference(error)
                    row.update(status="not_adopted", request_sha256=handoff["assessment"]["request_sha256"])
                    result["main_handoff"] = {**handoff, "stage": stage}
                    raise
                except AgentCommandCancelled:
                    raise
                except ValueError:
                    row["status"] = "not_adopted"
                    raise
                finally:
                    row["elapsed_ms"] = round((perf_counter() - at) * 1000, 3)
                    checkpoint()
            def review_selection(proof, frame, dispatch):
                selected, reference = evaluate_field("after_selection", lambda: assess_visual_selection(
                    proof, frame=frame, dispatch=dispatch))
                result["field_proofs"].append(reference)
                return selected
            def review_field_freshness(proof, frame, native_snapshot):
                stage = "before_type_freshness" if proof.request()["action"]["field_phase"] == "focus" else "before_enter_freshness"
                reviewed, reference = evaluate_field(stage, lambda: assess_visual_field_freshness(
                    proof, frame=frame, native_snapshot=native_snapshot))
                result["field_proofs"].append(reference)
                return reviewed
            def readonly_focus(stage, callback):
                nonlocal visual_focus_readonly_error, visual_focus_readonly_stage
                try:
                    return callback()
                except AgentCommandCancelled:
                    raise
                except Exception as error:
                    if native_evidence:
                        raise
                    # 保留兼容阶段名；纯视觉只确认实际点击点属于目标输入框。
                    reason = str(error) if isinstance(error, ValueError) and 0 < len(str(error)) <= 256 else "visual_focus_readonly_failed"
                    visual_focus_readonly_error = InputSequenceInterrupted(reason)
                    visual_focus_readonly_stage = stage
                    raise visual_focus_readonly_error from error
            if compound_visual:
                result["field_proofs"] = []
            else:
                try:
                    focus_snapshot = None
                    focus_frame = result["observation"]["capture"]
                    try:
                        if native_evidence:
                            focus_snapshot = coordinator._owner.call(lambda: read_visual_focus_snapshot(
                                frame=result["observation"]["capture"], expected_field=expected_field, manager=coordinator._windows()))
                    except TextFieldReadError as error:
                        # 只登记真实只读快照失败，评估或键盘目标构造异常不能冒充原生读取证明。
                        focus_read_error = error
                        raise
                    focus_proof, focus_reference = readonly_focus("after_click_assessment", lambda: coordinator._owner.call(lambda: evaluate_field("after_click",
                        lambda: assess_visual_field(phase="focus",
                        focus_receipt=focus_receipt, input_receipt=None, frame=focus_frame,
                        expected_field=expected_field, context=visual_field_context, focus_snapshot=focus_snapshot))))
                    effective_clear = spec.clear_existing
                    if not native_evidence:
                        result["visual_click_evidence"] = coordinator._owner.call(lambda: {
                            "session_directory": str(focus_proof._service.session_dir),
                            "profile": focus_proof._service.profile.model_dump(mode="json", exclude_unset=True),
                            "request": focus_proof.request(), "assessment": focus_proof.assessment()})
                    visual_field_context["typing_focus_proof"] = focus_proof
                    keyboard_target = coordinator._owner.call(lambda: issue_visual_keyboard_target(
                        focus_proof, "type_text", text=spec.text, clear_existing=effective_clear, selection_reviewer=review_selection,
                        freshness_reviewer=review_field_freshness))
                except AgentCommandCancelled:
                    raise
                except ValueError as error:
                    result["input_check"] = {"status": "unavailable", "phase": "check_focus", "reason": str(error)}
                    if error is visual_focus_readonly_error:
                        result["input_check"].update(evidence_kind="visual", focus_stage="after_click",
                            read_only_stage=visual_focus_readonly_stage)
                        raise
                    if error is focus_read_error:
                        raise
                    raise InputSequenceInterrupted(str(error)) from error
                result["field_proofs"] = [focus_reference]
                action("type", "type_text", {"text": spec.text, **point,
                    "click_before_typing": False, "clear_existing": effective_clear}, 0, keyboard_target=keyboard_target)
            result["phase"] = "check_input"
            typed = result["steps"][-1]["receipt"]
            try:
                value_reading = None
                if native_evidence:
                    value_reading = coordinator._owner.call(lambda: read_visual_value(
                        frame=result["observation"]["capture"], expected_field=expected_field,
                        context=visual_field_context, manager=coordinator._windows()))
                value_proof, value_reference = coordinator._owner.call(lambda: evaluate_field("after_type",
                    lambda: assess_visual_field(phase="value",
                    focus_receipt=focus_receipt, input_receipt=typed, frame=result["observation"]["capture"],
                    expected_field=expected_field, context=visual_field_context, value_reading=value_reading)))
            except AgentCommandCancelled:
                raise
            except VisualFieldReviewRequired as error:
                result["input_check"] = {"status": "unavailable", "phase": "check_input", "reason": str(error)}
                if not compound_visual or not callable(field_review_handler):
                    raise InputSequenceInterrupted(str(error)) from error
                try:
                    from app.core.input_sequence_partial import _compound_input_fact
                    from .main_field_approval import MainFieldApproval
                    from .visual_field_proof import build_main_approved_visual_field_proof
                    fact = _compound_input_fact(result, spec.model_dump(mode="json"), expected_field["window_identity"])
                    if started_actions != ["focus_type"] or fact is None or not fact["completed"]:
                        raise ValueError("visual_field_main_original_input_not_settled")
                    handoff = result["main_handoff"]
                    handoff["original_input"] = {"completed_steps": deepcopy(result["completed_steps"]),
                        "interrupted_at": "check_input", "action_executed": result["action_executed"],
                        "input_check": deepcopy(result["input_check"]),
                        "typing_dispatch": deepcopy(fact["fact"]["typing_dispatch"])}
                    # owner.call 已退回工作线程；人工等待不得占住桌面 owner。
                    approval = field_review_handler(error, stage="after_type", progress=deepcopy(result),
                        context=visual_field_context)
                    if type(approval) is not MainFieldApproval:
                        raise ValueError("visual_field_main_approval_required")
                    visual_field_context["deadline_ns"] = approval.deadline_ns
                    action_review_deadline_ns = approval.deadline_ns
                    def accepted_value():
                        proof = build_main_approved_visual_field_proof(approval, error=error,
                            focus_receipt=focus_receipt, input_receipt=typed, frame=result["observation"]["capture"],
                            expected_field=expected_field, context=visual_field_context)
                        return proof, proof.to_reference()
                    value_proof, value_reference = coordinator._owner.call(accepted_value)
                    result.setdefault("field_review_resolutions", []).append({
                        "handoff": deepcopy(handoff), "main_review": approval.to_reference()})
                    result.pop("main_handoff")
                except AgentCommandCancelled as failure:
                    # 此处只读审核尚未派发后缀；保留进入等待前已认证的原输入回执。
                    result["input_check"] = {"status": "unavailable", "phase": "check_input",
                        "reason": "agent_command_cancelled"}
                    raise InputSequenceInterrupted("agent_command_cancelled") from failure
                except ValueError as failure:
                    result["input_check"] = {"status": "unavailable", "phase": "check_input", "reason": str(failure)}
                    raise InputSequenceInterrupted(str(failure)) from failure
            except ValueError as error:
                result["input_check"] = {"status": "unavailable", "phase": "check_input", "reason": str(error)}
                raise InputSequenceInterrupted(str(error)) from error
            result["field_proofs"].append(value_reference)
            result["input_check"] = ({"status": "matched", "source": value_reference["reading"]["source"],
                "value_sha256": value_reference["value_sha256"], "evidence_kind": "visual"}
                if native_evidence else {"status": "verified", "source": value_reference["source"], "evidence_kind": "visual"})
            result["completed_steps"].append("check_input")
            if spec.submit_search:
                result["phase"] = "prepare_search"
                def prepare_enter():
                    try:
                        keyboard = issue_visual_keyboard_target(value_proof, "press_key", submit_search=True,
                            freshness_reviewer=review_field_freshness)
                        if compound_visual:
                            from app.core.visual_submit_target import VisualSubmitTarget
                            return VisualSubmitTarget(keyboard, action_review=action_review)
                        return keyboard
                    except AgentCommandCancelled:
                        raise
                    except ValueError:
                        # 只认证签发前沿的真实取消或期限；异常文字不能证明 Enter 未派发。
                        cancelled = visual_field_context.get("cancelled")
                        stopped = cancelled() if callable(cancelled) else False
                        observed = perf_counter_ns()
                        deadline = visual_field_context["deadline_ns"]
                        if (native_evidence or started_actions != (["focus_type"] if compound_visual else ["focus", "type"])
                                or type(stopped) is not bool or not (stopped or observed >= deadline)):
                            raise
                        import json
                        from app.core.input_sequence_partial import _digest
                        value = json.loads(value_proof._json_value)
                        reason = "visual_field_cancelled" if stopped else "visual_field_deadline_expired"
                        result["enter_preparation_failure"] = {
                            "schema": "visual_enter_preparation_partial.v1", "stage": "before_enter_dispatch",
                            "sequence_id": group_id, "request_sha256": _digest(spec.model_dump(mode="json")),
                            "focus_receipt_sha256": _digest(focus_receipt), "input_receipt_sha256": _digest(typed),
                            "value_request_sha256": value_reference["request_sha256"], "stop_reason": reason,
                            "cancelled": stopped, "deadline_ns": deadline, "observed_at_ns": observed,
                            "started_actions": list(started_actions), "suffix_dispatch_started": False,
                            # 已过期证明只作失败结算，由消费者读原账本认证，绝不重新授权。
                            "evidence": {"session_directory": str(value_proof._service.session_dir),
                                "profile": value_proof._service.profile.model_dump(mode="json", exclude_unset=True),
                                "request": value["request"], "assessment": value["assessment"]}}
                        raise InputSequenceInterrupted(reason) from None
                keyboard_target = coordinator._owner.call(prepare_enter)
                if compound_visual:
                    action("search", "execute_recognition_plan", {"goal": spec.field_goal,
                        "click_kind": "single"}, observation_wait_ms, grounding_target=keyboard_target)
                else:
                    action("search", "press_key", {"key": "Enter", **point}, observation_wait_ms,
                        keyboard_target=keyboard_target)
            result.update(status="completed", phase="returned", evidence_kind="visual",
                next_action="inspect_returned_image_and_judge_task_effect")
            return result
        field_binding = (_focus_field_binding(located, result["steps"][0]["receipt"], target)
                         if _tab_from is None else None)
        if (field_binding is not None and focus_target.binding is not None
                and (field_binding["runtime_id"] != focus_target.binding["runtime_id"]
                     or field_binding["control_type"] != focus_target.binding["control_type"])):
            raise InputSequenceInterrupted("input_preclick_binding_conflict")
        if field_binding is not None:
            result["field_binding"] = field_binding
        elif focus_target.binding is not None:
            local_binding = focus_target.binding
            result["local_focus_binding"] = {"runtime_id": local_binding["runtime_id"],
                "control_type": local_binding["control_type"], "bbox": local_binding["bbox"],
                "window_handle": local_binding["window_handle"], "process_id": local_binding["process_id"]}
        elif local_binding is None:
            raise InputSequenceInterrupted("input_preclick_binding_unavailable")
        if _expected_label is not None and _tab_from is None:
            from app.agent.windows_text_field_reader import probe_tab_focus_target
            labelled = coordinator._owner.call(lambda: probe_tab_focus_target(coordinator._windows(),
                target["handle"], target["process_id"], _expected_label, None))
            chosen_binding = field_binding or local_binding
            if (labelled["runtime_id"] != chosen_binding["runtime_id"]
                    or labelled["control_type"] != chosen_binding["control_type"]):
                raise InputSequenceInterrupted("text_group_first_field_changed")
        before = read("check_focus", point)
        keyboard_point = point
        if local_binding is not None:
            x, y, width, height = before.identity.control_bbox
            keyboard_point = {"x": x + width // 2, "y": y + height // 2}
            result["keyboard_anchor_point"] = dict(keyboard_point)
            result["keyboard_anchor_coordinate_space"] = "capture_image_pixels"
        if spec.clear_existing:
            expected = spec.text
        else:
            if before.selection is None:
                raise InputSequenceInterrupted("input_selection_unavailable")
            start, end = before.selection
            expected = before.value[:start] + spec.text + before.value[end:]
        from app.core.local_keyboard_target import LocalKeyboardTarget
        keyboard_target = (LocalKeyboardTarget(before,
            field_binding["control_type"] if field_binding is not None else local_binding["control_type"],
            (keyboard_point["x"], keyboard_point["y"]), "type_text", text_sha256=result["text_sha256"],
            clear_existing=spec.clear_existing, focus_reflow=local_binding is not None)
            if field_binding is not None or local_binding is not None else None)
        action("type", "type_text", {"text": spec.text, **keyboard_point,
            "click_before_typing": False, "clear_existing": spec.clear_existing}, 0, keyboard_target=keyboard_target)
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
        if _on_field_complete is not None:
            _on_field_complete(after, (field_binding or local_binding)["control_type"])
        if spec.submit_search:
            if local_binding is not None:
                x, y, width, height = after.identity.control_bbox
                keyboard_point = {"x": x + width // 2, "y": y + height // 2}
            keyboard_target = (LocalKeyboardTarget(after,
                field_binding["control_type"] if field_binding is not None else local_binding["control_type"],
                (keyboard_point["x"], keyboard_point["y"]), "press_key",
                focus_reflow=local_binding is not None)
                if field_binding is not None or local_binding is not None else None)
            action("search", "press_key", {"key": "Enter", **keyboard_point}, observation_wait_ms,
                keyboard_target=keyboard_target)
        result.update(status="completed", phase="returned",
            next_action="inspect_returned_image_and_judge_task_effect")
    except AgentCommandCancelled:
        raise
    except Exception as error:
        # 组合可能已有输入，必须保留子步回执，不把整个命令伪装成零副作用。
        from app.core.screenshot import CaptureVisibilityError
        reason = (str(error) if isinstance(error, InputSequenceInterrupted)
                  else error.reason if isinstance(error, CaptureVisibilityError)
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
            if error is focus_read_error:
                from app.core.input_sequence_partial import make_focus_partial_proof
                proof = make_focus_partial_proof(result, spec.model_dump(mode="json"),
                    started_actions=started_actions)
                if proof is not None:
                    result["partial_input_terminal"] = proof
        if error is visual_focus_readonly_error:
            from app.core.input_sequence_partial import make_focus_partial_proof
            proof = make_focus_partial_proof(result, spec.model_dump(mode="json"),
                started_actions=started_actions, read_only_stage=visual_focus_readonly_stage)
            if proof is not None:
                result["partial_input_terminal"] = proof
        if "main_handoff" in result:
            # 派发事实仍取原子步回执；只读交接不推断未知输入，也不授予重放。
            data = _action_data(result["steps"][-1]["receipt"]) if result["steps"][-1].get("receipt") else {}
            result["main_handoff"]["original_input"] = {
                "completed_steps": deepcopy(result["completed_steps"]), "interrupted_at": result["interrupted_at"],
                "action_executed": result["action_executed"], "input_check": deepcopy(result["input_check"]),
                "typing_dispatch": deepcopy(data.get("typing_dispatch") or (data.get("type_result") or {}).get("typing_dispatch"))}
            result["next_action"] = "review_original_evidence_with_main_before_a_new_command"
    finally:
        checkpoint()
    return result
