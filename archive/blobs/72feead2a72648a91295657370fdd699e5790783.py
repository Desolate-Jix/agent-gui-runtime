"""关闭本地安全策略时复用原动作路由，不建立学习段或另一个输入后端。"""
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
from hashlib import sha256
import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
from app.core.local_input_policy import _local_operator_input_scope, _local_operator_step_scope, _window_rect
from app.core.runtime_artifacts import RuntimeTimer
from app.core.screenshot import ScreenshotService, CaptureVisibilityError
from app.core.observation_policy import local_action_observation_kind, resolve_render_grace_ms
from .conditional_observation import UIATextConditionProbe, observe_until_condition, validate_condition
from .local_action_contract import LocalActionFieldsError, _validated_request
from .post_action_recovery import observe_recovery_windows


class LocalDirectStepMixin:
    def prepare_local_step_models(self, *, prepare_ocr: bool = True) -> dict:
        """显式只读准备并复用既有驻留池，不附加运行时或赋予输入权限。"""
        if type(prepare_ocr) is not bool:
            raise TypeError("prepare_ocr must be bool")
        self._begin("idle")
        timer = RuntimeTimer(contract_version="local_model_preparation_timing_v1")
        owned = False
        result = {"status": "preparing", "input_dispatched": False, "learning_enabled": False}
        try:
            with self._guard:
                if not self._keep_models_loaded:
                    raise ValueError("enable model residency before explicit preparation")
                if self._runtime is not None or self._attached or self._learning_binding is not None or self._model_service is not None:
                    raise ValueError("cancel the current runtime before model preparation")
            self._require_host_ready(require_unattached=True)
            from app.vision.configuration import load_formal_vision_configuration
            from app.vision.model_service import freeze_model_service
            with timer.step("configuration_load"):
                configuration = freeze_model_service(load_formal_vision_configuration(self._vision_config_path))
            if configuration is not None:
                owned = True

                def prepare(stage):
                    stage["mode"] = "reuse" if configuration in self._resident_model_services else "prepare"
                    self._prepare_model_service_on_owner(configuration)

                _timed_owner_call(self._owner, timer, "model_prepare_or_reuse", prepare)
            if prepare_ocr:
                def prepare_local_ocr(stage):
                    from app.api.vision import ocr_service
                    return ocr_service.prepare()

                result["ocr"] = _timed_owner_call(self._owner, timer, "ocr_prepare", prepare_local_ocr)
            result["status"] = "ready"
            return result
        finally:
            try:
                if owned:
                    with timer.step("model_release_to_residency"):
                        self._release_model_service()
            finally:
                self._end()
                result["timings"] = {**timer.to_dict(), "inclusive": True, "nested_timings_additive": False}

    def execute_local_step(self, *, target_window_handle: int, target_process_id: int,
                           operation: str, request: dict, include_observation: bool = False,
                           observation_wait_ms: int | None = None, observation_condition: dict | None = None,
                           control_target=None) -> dict:
        """仅本地协调器入口；不经 Agent JSON 关闭策略，也不要求一次性执行凭据。"""
        timer = RuntimeTimer(contract_version="local_step_invocation_timing_v1")
        timing_context = {"invocation_id": "local-invocation-" + uuid4().hex,
                          "include_observation": include_observation, "observation_wait_ms": observation_wait_ms}
        failure = None
        try:
            with timer.step("request_validation"):
                from app.core.local_control_target import LocalControlTarget
                if control_target is not None and (operation != "execute_recognition_plan"
                        or not isinstance(control_target, LocalControlTarget)):
                    raise ValueError("internal control target requires a recognition click")
                if type(include_observation) is not bool:
                    raise TypeError("include_observation must be bool")
                if observation_wait_ms is not None:
                    resolve_render_grace_ms("", observation_wait_ms)
                if observation_wait_ms and not include_observation:
                    raise ValueError("observation wait requires include_observation")
                if type(target_window_handle) is not int or target_window_handle <= 0 or type(target_process_id) is not int or target_process_id <= 0:
                    raise ValueError("local step requires a valid HWND and PID")
                request = _validated_request(operation, request)
                timing_context["observation_wait_ms"] = (resolve_render_grace_ms(
                    local_action_observation_kind(operation, request), observation_wait_ms)
                    if include_observation else 0)
                timing_context["observation_condition"] = validate_condition(
                    observation_condition, timing_context["observation_wait_ms"])
            with timer.step("coordinator_begin"):
                self._begin("idle")
            configuration = None
            prepare_model = operation == "execute_recognition_plan" and self._uses_production_factory
            model_preparation_owned = False
            try:
                with timer.step("host_preparation"):
                    with self._guard:
                        if self._automatic_safety_interception:
                            raise self._error("one_time_authority_required",
                                "automatic safety interception is enabled; use the confirmed LiveController path")
                        if self._runtime is not None or self._attached or self._learning_binding is not None:
                            raise self._error("local_step_unavailable", "cancel the current runtime before a local non-learning step")
                        if self._model_service is not None:
                            raise self._error("model_service_cleanup_pending", "release the previous model owner before a local step")
                    self._require_host_ready(require_unattached=True)
                if prepare_model:
                    with timer.step("configuration_load"):
                        from app.vision.configuration import load_formal_vision_configuration
                        from app.vision.model_service import freeze_model_service
                        configuration = load_formal_vision_configuration(self._vision_config_path)
                        frozen = freeze_model_service(configuration)
                    if frozen is not None:
                        model_preparation_owned = True

                        def prepare(stage):
                            with self._guard:
                                stage["mode"] = "reuse" if (self._keep_models_loaded
                                    and frozen in self._resident_model_services) else "prepare"
                            return self._prepare_model_service_on_owner(frozen)

                        _timed_owner_call(self._owner, timer, "model_prepare_or_reuse", prepare)
                return _timed_owner_call(self._owner, timer, "owner_dispatch",
                    lambda stage: self._execute_local_step_on_owner(target_window_handle,
                        target_process_id, operation, request, configuration, timing_context=timing_context,
                        control_target=control_target),
                    includes="local_step_timings")
            finally:
                try:
                    if model_preparation_owned:
                        with timer.step("model_release"):
                            self._release_model_service()
                finally:
                    with timer.step("coordinator_end"):
                        self._end()
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                _persist_invocation(self._runtime_output_root, timing_context, timer, operation, failure)
            except Exception as timing_error:
                # 计时落盘失败不得替换原动作或清理异常；不输出可能含私密内容的异常消息。
                if failure is None:
                    raise
                failure.add_note("local step timing persistence failed: " + type(timing_error).__name__)

    def _execute_local_step_on_owner(self, handle, pid, operation, request, configuration=None,
                                     *, timing_context, control_target=None):
        timer = RuntimeTimer(contract_version="local_step_owner_timing_v1")
        try:
            from app.vision.configuration import pinned_vision_configuration
            from app.core.local_control_target import local_control_target_scope
            with _local_operator_step_scope(), local_control_target_scope(control_target), (pinned_vision_configuration(configuration) if configuration else nullcontext()):
                return self._perform_local_step_on_owner(handle, pid, operation, request, timer, timing_context)
        finally:
            timing_context["local_step_timings"] = {**timer.to_dict(), "scope": "owner_execution",
                "inclusive": True, "nested_timings_additive": False}

    def _perform_local_step_on_owner(self, handle, pid, operation, request, timer, timing_context):
        with timer.step("binding_identity"):
            manager = self._windows()
            bound = manager.bind_window_by_handle(handle)
            reader = WindowsNativeIdentityReader(window_manager=manager)
            identity = validate_native_identity_fact(reader.read_identity(handle),
                target_window_handle=handle, expected_process_id=pid)
            if identity is None or bound is None or bound.handle != handle or bound.process_id != pid:
                raise ValueError("local step target identity mismatch")
            window_rect = _window_rect(bound)
        step_id = "local-step-" + uuid4().hex
        output = self._runtime_output_root / "local-direct-steps" / step_id
        output.mkdir(parents=True, exist_ok=False)
        report = {"contract_version": "local_direct_step_v1", "step_id": step_id,
                  "started_at": _now(), "operation": operation, "target_identity": identity,
                  "automatic_safety_interception": False, "one_time_authority_required": False,
                  "learning_enabled": False, "phase": "preparing", "request": _audit_request(request),
                  "effect_verified": False, "automatic_retry_allowed": False}
        timing_context.update(report=report, output=output)
        failure = None
        try:
            with timer.step("capture_hash"):
                from app.api.models.request import ROIModel
                roi = ROIModel.model_validate(request["capture_roi"]) if request.get("capture_roi") else None
                capture = ScreenshotService(window_manager=manager, capture_dir=output / "captures").capture_window(
                    roi=roi, focus_window=False, purpose="local-direct-no-learning")
                _validate_coordinates(request, capture)
                image_path = Path(capture["image_path"])
                report["capture"] = {**capture, "sha256": sha256(image_path.read_bytes()).hexdigest(),
                    "frame_id": "before_input", "observation_stage": "before_input"}
            condition = timing_context.get("observation_condition")
            if condition is not None:
                with timer.step("observation_condition_baseline"):
                    probe = UIATextConditionProbe(condition, manager, reader, identity)
                    baseline = probe()
            # 范围内只有此会话的原路由可执行；无一次性凭据、无默认/跨会话放行。
            with _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
                    window_rect=window_rect,
                    enabled=lambda: not self._automatic_safety_interception and not self._shutdown
                                    and not self._cancel_wait.is_set()):
                report["phase"] = "dispatching"
                with timer.step("report_persist", phase="dispatching"):
                    _write_report(output, report)
                with timer.step("route_call", inclusive=True):
                    report["response"] = _post_action(operation, request, manager)
            # 进入原路由后可能已产生部分输入，失败返回不能证明没有副作用。
            report["phase"] = "returned" if report["response"].get("success") is True else "result_unknown"
            response_data = report["response"].get("data") or {}
            if (operation == "press_key" and report["response"].get("success") is False
                    and response_data.get("dispatch_status") == "not_dispatched"
                    and response_data.get("pressed") is False):
                report["phase"] = "not_dispatched"
            if timing_context.get("include_observation"):
                # 结果和后图同次回传；观察失败不能重放已经可能派发的动作。
                with timer.step("post_action_observation"):
                    try:
                        wait_ms = timing_context.get("observation_wait_ms", 0)
                        condition_result = None
                        if condition is not None:
                            after, condition_result = observe_until_condition(probe,
                                lambda: _capture_observation(manager, reader, identity, handle, pid, output, roi),
                                baseline, timeout_ms=wait_ms, cancel=self._cancel_wait, clock=perf_counter)
                            condition_result["expected"] = condition
                        else:
                            if wait_ms and self._cancel_wait.wait(wait_ms / 1000):
                                raise ValueError("post-action observation cancelled")
                            after = _capture_observation(manager, reader, identity, handle, pid, output, roi)
                        after = {**after, "frame_id": "after_settled",
                            "observation_stage": "after_condition_wait" if condition else "after_render_wait", "render_grace_ms": wait_ms,
                            "render_completion_verified": False}
                        report["observation"] = {"status": "captured", "capture": after,
                            "source": "post_action", "authorizes_action": False,
                            "readiness": "unassessed", "render_grace_ms": wait_ms,
                            "automatic_retry_allowed": False}
                        if condition_result is not None:
                            report["observation"].update(condition=condition_result, readiness=condition_result["status"])
                    except Exception as error:
                        if report["phase"] == "returned":
                            report["phase"] = "returned_observation_unavailable"
                        elif report["phase"] != "not_dispatched":
                            report["phase"] = "result_unknown"
                        report["observation"] = {"status": "unavailable", "error_type": type(error).__name__,
                            "error_code": error.reason if isinstance(error, CaptureVisibilityError) else
                                getattr(error, "reason_code", "post_action_observation_failed"),
                            "next_action": "capture_current_state_without_replaying_input",
                            "authorizes_action": False, "readiness": "unknown", "automatic_retry_allowed": False}
                        recovery = observe_recovery_windows(manager, identity)
                        report["observation"]["recovery"] = recovery
                        if recovery["status"] == "candidates_available":
                            report["observation"]["next_action"] = "inspect_recovery_windows_then_select_and_capture"
                        elif recovery["status"] == "process_not_running":
                            # 进程消失可解释缺图，但不证明正常退出或任务成功，也不能重放输入。
                            report["observation"]["error_code"] = "target_process_not_running"
                            report["observation"]["next_action"] = "review_task_effect_without_replaying_input"
            return report
        except Exception as error:
            failure = error
            phase = "result_unknown" if report["phase"] == "dispatching" else "failed"
            report.update(phase=phase, error_type=type(error).__name__, error="local_step_failed")
            raise
        finally:
            report.update(finished_at=_now(), local_input_scope_closed=True)
            try:
                with timer.step("report_persist", phase="finished"):
                    _write_report(output, report)
            except Exception as persistence_error:
                if failure is None:
                    raise
                failure.add_note("local step report persistence failed: " + type(persistence_error).__name__)


def _capture_observation(manager, reader, identity, handle, pid, output, roi):
    def check_identity():
        current = validate_native_identity_fact(reader.read_identity(handle),
            target_window_handle=handle, expected_process_id=pid)
        keys = ("process_create_time", "executable_path", "process_id", "target_window_handle")
        if current is None or any(current.get(key) != identity.get(key) for key in keys):
            raise ValueError("post-action observation target identity changed")

    check_identity()
    capture = ScreenshotService(window_manager=manager, capture_dir=output / "observations").capture_window(
        roi=roi, focus_window=False, purpose="local-direct-post-action")
    check_identity()
    return {**capture, "sha256": sha256(Path(capture["image_path"]).read_bytes()).hexdigest(),
            "observed_at": _now()}


def _timed_owner_call(owner, timer, name, callback, **metadata):
    with timer.step(name, inclusive=True, **metadata):
        stage = timer.steps[-1]
        queued_at = perf_counter()

        def run():
            stage["queue_wait_ms"] = round((perf_counter() - queued_at) * 1000, 3)
            return callback(stage)

        return owner.call(run)


def _persist_invocation(root, context, timer, operation, failure):
    # 外层包含 owner 和原路由的内层耗时，不能把两层 total 再相加。
    timings = {**timer.to_dict(), "scope": "execute_local_step", "inclusive": True,
        "nested_timings_additive": False, "final_timing_sync_excluded": True}
    fields = {"invocation_id": context["invocation_id"], "invocation_timings": timings,
        "invocation_status": "returned" if failure is None else "raised"}
    if failure is not None:
        fields["invocation_error_type"] = type(failure).__name__
    if "local_step_timings" in context:
        fields["local_step_timings"] = context["local_step_timings"]
    if "report" in context:
        context["report"].update(fields)
        # 最后一笔只同步已结束的计时，不递归测量自身的序列化与写入。
        _write_report(context["output"], context["report"])
    else:
        allowed = {"execute_recognition_plan", "type_text", "scroll", "press_key"}
        report = {"contract_version": "local_step_invocation_v1", **fields,
            "operation": operation if type(operation) is str and operation in allowed else "unsupported"}
        output = root / "local-direct-invocations" / context["invocation_id"]
        output.mkdir(parents=True, exist_ok=False)
        (output / "invocation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_coordinates(request, capture):
    size = capture.get("window_size") or {"width": capture["image_width"], "height": capture["image_height"]}
    roi = capture.get("roi") or {"x": 0, "y": 0, **size}
    for key, extent in (("x", "width"), ("y", "height")):
        point = request.get(key)
        if point is not None and (type(point) is not int or not 0 <= point < size[extent]
                or not roi[key] <= point < roi[key] + roi[extent]):
            raise ValueError("local action point is outside the current screenshot")


def _post_action(operation, request, manager):
    from fastapi import FastAPI
    import httpx
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest, ScrollRequest, TypeTextRequest
    from .local_keyboard_action import LocalKeyRequest, press_local_key
    if action.window_manager is not manager:
        raise ValueError("local route and coordinator must share the bound window manager")
    model, handler = {"type_text": (TypeTextRequest, action.type_text),
                      "press_key": (LocalKeyRequest, press_local_key),
                      "scroll": (ScrollRequest, action.scroll),
                      "execute_recognition_plan": (ExecuteRecognitionPlanRequest, action.execute_recognition_plan)}[operation]
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/action/" + operation)
    async def endpoint(payload: dict):
        # 保持 Windows COM/窗口访问在当前串行 owner，不让 FastAPI 切换到工作线程。
        return handler(model.model_validate(payload)).model_dump()

    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local-operator") as client:
            response = await client.post("/action/" + operation, json=request)
            response.raise_for_status()
            return response.json()

    return asyncio.run(send())


def _audit_request(request):
    value = deepcopy(request)
    text = value.pop("text", None)
    if text is not None:
        value["text_length"] = len(text)
        value["text_sha256"] = sha256(text.encode("utf-8")).hexdigest()
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_report(output, report):
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
