"""原生单步复核的串行 Runtime 协调器。"""

from __future__ import annotations

from app.agent.action_semantics import READ_ONLY_REVIEW_ACTIONS, REVIEWED_SINGLE_STEP_ACTIONS
from app.agent.text_parameters import ReviewedTextParameters, ResolvedTextParameters, resolve_text_parameters, text_parameter_reference
from app.agent.text_execution import validate_local_text_preview
from app.agent.text_field_evidence import TextFieldExpectation

from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from threading import Event, RLock
import math
import time
from typing import Any, Callable
from uuid import uuid4

from app.runtime_environment import inspect_environment
from app.vision.configuration import (
    VisionConfigurationError, load_formal_vision_configuration, resolve_vision_config_path,
)
from app.vision.model_service import FormalModelService, ModelServiceError, freeze_model_service

from .single_step_runtime_owner import RuntimeOwnerProxy, SerialRuntimeOwner
from .grounded_history import GroundedHistoryMixin
from .window_preparation import WindowPreparationMixin
from .local_direct_step import LocalDirectStepMixin
from .model_setup import initialize_vista_configuration


class NativeSingleStepCoordinatorError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        result_unknown: bool = False,
        retry_preparation: bool = False,
        computation_stopped: bool = False,
    ) -> None:
        self.code = code
        self.message = message
        self.result_unknown = result_unknown
        self.retry_preparation = retry_preparation
        self.computation_stopped = computation_stopped is True
        super().__init__(message)


class NativeSingleStepCoordinator(LocalDirectStepMixin, WindowPreparationMixin, GroundedHistoryMixin):
    def __init__(
        self,
        project_root: str | Path,
        facade: Any,
        host: Any,
        *,
        runtime_factory: Callable[..., Any] | None = None,
        thread_initializer: Callable[[], None] | None = None,
        thread_finalizer: Callable[[], None] | None = None,
        foreground_timeout: float = 30.0,
        vision_config_path: str | Path | None = None,
        runtime_output_root: str | Path | None = None,
        enable_agent_learning: bool | None = None,
    ) -> None:
        timeout = _positive_timeout(foreground_timeout)
        if not callable(getattr(facade, "list_reviewed_assets", None)):
            raise TypeError("facade must expose list_reviewed_assets")
        if not callable(getattr(host, "status", None)):
            raise TypeError("host must expose status")
        self._project_root = Path(project_root).resolve()
        self._runtime_output_root = (self._project_root / "runtime-output" if runtime_output_root is None
                                     else Path(runtime_output_root).expanduser().resolve())
        self._vision_config_path = resolve_vision_config_path(vision_config_path, project_root=self._project_root)
        # 首次写入保留最终路径分量，避免已存在的悬空链接被提前解析为新文件。
        self._model_setup_config_path = (Path(vision_config_path).expanduser().absolute() if vision_config_path is not None
                                        else self._project_root / "configs/vision.json")
        self._facade = facade
        self._host = host
        self._runtime_factory = _production_runtime_factory if runtime_factory is None else runtime_factory
        self._uses_production_factory = runtime_factory is None or runtime_factory is _production_runtime_factory
        self._window_manager = getattr(self._runtime_factory, "window_manager", None)
        self._owner = SerialRuntimeOwner(
            initializer=thread_initializer,
            finalizer=thread_finalizer,
            output_root=self._runtime_output_root,
            call_scope=self._model_request_scope,
        )
        self._foreground_timeout = timeout
        self._guard = RLock()
        self._automatic_safety_interception = True
        self._cancel_wait = Event()
        self._busy = False
        self._shutdown = False
        self._phase = "idle"
        self._runtime: Any | None = None
        self._proxy: RuntimeOwnerProxy | None = None
        self._observation: Any | None = None
        self._selection: Any | None = None
        self._learning_binding: Any | None = None
        # 清理后仅保留同一绑定的只读事实快照，不能重新附加或执行。
        self._fresh_runtime_snapshots: dict[int, tuple[Any, dict[str, Any]]] = {}
        self._factory_outcome_unknown = False
        self._confirmation_id: str | None = None
        self._preview_sha256: str | None = None
        self._intent_id: str | None = None
        self._action_id: str | None = None
        self._attached = False
        self._history_store = None
        self._history_confirmation_id: str | None = None
        self._model_service: FormalModelService | None = None
        self._model_release_pending = False
        self._keep_models_loaded = False
        self._resident_model_services: dict[Any, FormalModelService] = {}
        self._resident_model_cleanup_pending = False
        self._model_service_configuration = None
        self._model_reuse_failed = False
        self._window_preparations: dict[str, dict[str, Any]] = {}
        self._prepared_window_identities: dict[tuple[Any, ...], dict[str, Any]] = {}
        self._unverified_window_launch: dict[str, Any] | None = None
        if enable_agent_learning is not None and type(enable_agent_learning) is not bool:
            raise TypeError("enable_agent_learning must be bool or None")
        enable_learning = self._uses_production_factory if enable_agent_learning is None else enable_agent_learning
        installer = getattr(host, "enable_learning_runtime", None)
        if enable_learning and callable(installer):
            installer(self)
        elif enable_agent_learning is True:
            raise TypeError("host must expose the requested learning runtime capability")

    def safety_settings(self) -> dict[str, Any]:
        """仅展示本地会话选项，不为 Agent 签发批准。"""
        with self._guard:
            return {"automatic_safety_interception": self._automatic_safety_interception,
                    "scope": "automatic_risk_policy", "session_only": True}

    def set_automatic_safety_interception(self, enabled: bool) -> dict[str, Any]:
        """只在无待执行步骤时修改，已冻结的预览不得中途切换模式。"""
        if type(enabled) is not bool:
            raise TypeError("automatic_safety_interception must be a bool")
        with self._guard:
            if (self._busy or self._shutdown or self._phase != "idle"
                    or self._runtime is not None or self._confirmation_id is not None
                    or self._factory_outcome_unknown or self._model_release_pending
                    or self._model_service is not None or self._window_preparations):
                raise self._error("safety_mode_change_unavailable",
                    "safety_mode_change_unavailable: cancel the current step before changing safety mode")
            self._automatic_safety_interception = enabled
            return self.safety_settings()

    def environment(self) -> dict[str, Any]:
        self._begin("idle")
        try:
            report = inspect_environment()
            config_report = {"config_path": str(self._vision_config_path), "runtime_verified": False,
                "model_assets_checked": False, "service_contacted": False}
            try:
                snapshot = load_formal_vision_configuration(self._vision_config_path)
                config_report.update(status="configured_unverified", mode=snapshot.mode)
            except VisionConfigurationError as error:
                config_report.update(status="blocked", reason_code=error.code)
            report["vision_configuration"] = config_report
            return report
        finally:
            self._end()

    def model_setup_status(self) -> dict[str, Any]:
        """返回首次 VISTA 配置入口的被动状态，不创建运行时。"""
        self._begin("idle")
        try:
            return {"config_path": str(self._model_setup_config_path),
                    "config_exists": self._model_setup_config_path.exists() or self._model_setup_config_path.is_symlink(),
                    "supported_model": "VISTA-4B", "default_port": 13244,
                    "service_started": False}
        finally:
            self._end()

    def configure_vista_model(self, *, model_directory: str, port: int = 13244) -> dict[str, Any]:
        """仅发布首次配置；模型加载仍由后续显式准备路径负责。"""
        self._begin("idle")
        try:
            result = initialize_vista_configuration(self._model_setup_config_path, model_directory, port)
            self._vision_config_path = Path(result["config_path"]).resolve()
            return result
        finally:
            self._end()

    def inventory(self) -> dict[str, Any]:
        self._begin("idle")
        try:
            self._require_host_ready()
            self._check_runtime_environment()
            assets = self._facade.list_reviewed_assets()
            windows = self._owner.call(lambda: self._windows().list_visible_windows())
            inventory = {
                "assets": _assets(assets),
                "windows": _windows(windows),
            }
            self._unverified_window_launch = None
            return inventory
        except NativeSingleStepCoordinatorError:
            raise
        except Exception:
            raise self._error("inventory_failed", "native inventory could not be loaded") from None
        finally:
            self._end()

    def prepare(
        self,
        *,
        asset_id: str,
        asset_content_sha256: str,
        target_window_handle: int,
        target_process_id: int,
        learning_binding: Any | None = None,
    ) -> dict[str, Any]:
        if learning_binding is not None:
            from app.agent_link.learning_runtime_binding import LearningRuntimeBinding

            if not isinstance(learning_binding, LearningRuntimeBinding):
                raise TypeError("learning_binding must be LearningRuntimeBinding")
            if learning_binding.project_root != self._project_root:
                raise ValueError("learning runtime must share the coordinator root")
        self._begin_any({"idle", "prepare_recovery_required"})
        try:
            self._require_host_ready(require_unattached=True)
            selection = _selection(
                asset_id, asset_content_sha256, target_window_handle, target_process_id
            )
            with self._guard:
                retry_runtime = self._runtime
                previous_selection = self._selection
                factory_outcome_unknown = self._factory_outcome_unknown
                if self._phase != "idle" and self._learning_binding is not learning_binding:
                    raise self._error("runtime_cleanup_pending", "retained learning ownership differs")
                self._learning_binding = learning_binding
            if factory_outcome_unknown:
                raise self._error(
                    "runtime_cleanup_pending",
                    "runtime factory ownership cannot be verified",
                    result_unknown=True,
                )
            if retry_runtime is not None:
                if previous_selection != selection:
                    raise self._error(
                        "runtime_cleanup_pending",
                        "the retained runtime owner requires the same selection",
                    )
                has_local_cleanup = callable(
                    getattr(retry_runtime, "cancel_local_preparation", None)
                )
                try:
                    self._cleanup_unattached_local(retry_runtime, selection)
                except Exception as error:
                    raise self._mapped(
                        error,
                        "runtime_cleanup_pending",
                        "the prior runtime preparation cleanup remains pending",
                        retry_preparation=has_local_cleanup,
                    ) from None
                self._owner.call(lambda: self._wait_foreground_on_owner(selection, bind=False))
                runtime = retry_runtime
            else:
                self._check_runtime_environment()
                runtime = self._owner.call(lambda: self._create_runtime_on_owner(selection))
                with self._guard:
                    self._runtime = runtime
                    self._proxy = RuntimeOwnerProxy(self._owner, runtime)
                    self._selection = selection
                    self._factory_outcome_unknown = False
                    self._phase = "prepare_recovery_required"
            try:
                observation = self._owner.call(runtime.start_session)
            except Exception:
                with self._guard:
                    self._phase = "prepare_recovery_required"
                raise
            session_id = getattr(observation, "session_id", None)
            if not isinstance(session_id, str) or not session_id:
                raise self._error(
                    "runtime_observation_invalid",
                    "runtime observation is invalid",
                    retry_preparation=callable(
                        getattr(runtime, "cancel_local_preparation", None)
                    ),
                )
            try:
                actions = _actions(getattr(observation, "available_actions", None))
            except Exception:
                raise self._error(
                    "runtime_observation_invalid",
                    "runtime observation actions are invalid",
                    retry_preparation=callable(
                        getattr(runtime, "cancel_local_preparation", None)
                    ),
                ) from None
            with self._guard:
                self._observation = observation
                self._phase = "observed"
            result = {"phase": "observed", "session_id": session_id, "actions": actions}
            if not actions:
                result["diagnostic"] = _preflight_diagnostic(observation)
            return result
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(
                error,
                "runtime_prepare_failed",
                "runtime preparation failed",
                force_unknown=self._phase == "prepare_recovery_required",
                retry_preparation=(
                    getattr(error, "retry_preparation", False) is True
                    and self._runtime is not None
                    and self._observation is None
                ),
            ) from None
        finally:
            self._end()

    def text_input_requirements(self, *, action_id: str) -> ReviewedTextParameters:
        self._begin("observed")
        try:
            runtime, observation, _proxy = self._active()
            result = self._owner.call(lambda: self._text_requirements_on_owner(runtime, observation, action_id))
            if result is None:
                raise self._error("text_action_required", "action does not require text")
            return result
        finally:
            self._end()

    def prepare_fresh(self, *, source, learning_binding) -> dict[str, Any]:
        """从已提交首次来源使用同一 owner 准备，不构造审核资产。"""
        from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
        from .fresh_runtime_callsite import FreshRuntimeSelection

        if not isinstance(learning_binding, LearningRuntimeBinding):
            raise TypeError("learning_binding must be LearningRuntimeBinding")
        selection = FreshRuntimeSelection(source)
        if learning_binding.project_root != self._project_root:
            raise ValueError("fresh learning runtime must share the coordinator root")
        # 首次来源不复用失败 owner；必须先完成该 owner 的精确清理。
        self._begin("idle")
        try:
            self._require_host_ready(require_unattached=True)
            with self._guard:
                self._learning_binding = learning_binding
                self._selection = selection
            runtime = self._owner.call(lambda: self._create_runtime_on_owner(selection))
            with self._guard:
                self._runtime = runtime
                self._proxy = RuntimeOwnerProxy(self._owner, runtime)
                self._selection = selection
                self._factory_outcome_unknown = False
                self._phase = "prepare_recovery_required"
            observation = self._owner.call(runtime.start_session)
            if not isinstance(getattr(observation, "session_id", None), str):
                raise self._error("runtime_observation_invalid", "fresh runtime observation is invalid",
                                  retry_preparation=callable(getattr(runtime, "cancel_local_preparation", None)))
            payload = observation.to_dict()
            with self._guard:
                self._observation, self._phase = observation, "observed"
            return {"phase": "observed", "session_id": observation.session_id, "actions": [],
                    "observation": payload}
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "runtime_prepare_failed", "fresh runtime preparation failed",
                               force_unknown=self._runtime is not None,
                               retry_preparation=self._runtime is not None and self._observation is None) from None
        finally:
            self._end()

    def fresh_runtime_status(self, *, expected_learning_binding) -> dict[str, Any]:
        with self._guard:
            if expected_learning_binding is self._learning_binding and self._runtime is not None:
                runtime = self._runtime
            else:
                snapshot = self._fresh_runtime_snapshots.get(id(expected_learning_binding))
                if snapshot is not None and snapshot[0] is expected_learning_binding:
                    return deepcopy(snapshot[1])
                raise self._error("runtime_owner_mismatch", "fresh runtime ownership differs")
        return self._owner.call(runtime.get_fresh_runtime_state)

    def request_fresh_review(self, *, intent: dict, expected_learning_binding,
                             text_input: ResolvedTextParameters | None = None) -> dict[str, Any]:
        self._begin("observed")
        invoked = False
        try:
            if expected_learning_binding is not self._learning_binding:
                raise self._error("runtime_owner_mismatch", "fresh runtime ownership differs")
            runtime, _observation, proxy = self._active()
            invoked = True
            result = self._owner.call(lambda: runtime.request_grounded_confirmation(
                intent, **({"text_input": text_input} if text_input is not None else {})))
            status = getattr(result, "status", None)
            if status in {"REJECTED", "RECOVERY_REQUIRED"}:
                raise self._error("grounded_review_rejected" if status == "REJECTED" else "runtime_cleanup_pending",
                                  "fresh review was not published", result_unknown=status == "RECOVERY_REQUIRED")
            grounded = getattr(result, "grounded_confirmation", None)
            preliminary = getattr(grounded, "confirmation_id", None)
            if isinstance(preliminary, str) and preliminary:
                with self._guard:
                    self._confirmation_id = preliminary
                    self._phase = "pending_review"
            preview = getattr(grounded, "preview", None)
            if (getattr(result, "phase", None) != "grounded_confirmation_pending" or grounded is None
                    or grounded.owner_is_current is not True or preview is None):
                raise self._error("grounded_review_rejected", "fresh review was not published")
            payload = preview.to_dict()
            view = {"phase": "pending_review", "confirmation_id": grounded.confirmation_id,
                    "preview": payload, "requested_at": grounded.requested_at.isoformat().replace("+00:00", "Z"),
                    "expires_at": grounded.expires_at.isoformat().replace("+00:00", "Z"),
                    "owner_is_current": True, "source_kind": "fresh_learning",
                    "png_bytes": _image(self._owner.call(lambda: runtime.get_local_grounded_image(confirmation_id=grounded.confirmation_id)))}
            self._attach_local_text(runtime, view)
            with self._guard:
                self._confirmation_id = grounded.confirmation_id
                self._preview_sha256 = payload["preview_sha256"]
                self._intent_id, self._action_id = intent["intent_id"], intent["action_id"]
                self._phase = "pending_review"
            self._host.attach_grounded_runtime(proxy, confirmation_id=grounded.confirmation_id)
            with self._guard:
                self._attached = True
            return view
        except NativeSingleStepCoordinatorError as error:
            if invoked and error.code != "grounded_review_rejected":
                with self._guard:
                    self._phase = "review_recovery_required"
            raise
        except Exception as error:
            if invoked:
                with self._guard:
                    self._phase = "review_recovery_required"
            raise self._mapped(error, "review_request_failed", "fresh review publication remains recoverable",
                               force_unknown=invoked) from None
        finally:
            self._end()

    def current_agent_review(self) -> dict[str, Any]:
        """只读接管当前本地 Agent 待审 owner；不批准、不执行。"""
        with self._guard:
            fresh = _is_fresh_selection(self._selection)
        if fresh:
            return self.current_fresh_review()
        with self._guard:
            if (self._phase not in {"pending_review", "approved"} or self._runtime is None
                    or self._confirmation_id is None or self._intent_id is None or self._action_id is None):
                raise self._error("review_unavailable", "review is not owned")
            runtime, confirmation_id, intent_id, action_id = (
                self._runtime, self._confirmation_id, self._intent_id, self._action_id)
        claim = self._owner.call(lambda: runtime.get_local_grounded_confirmation(confirmation_id=confirmation_id))
        phase = "grounded_confirmation_approved" if self._phase == "approved" else "grounded_confirmation_pending"
        _claim, view = self._review_view(claim, expected_phase=phase, intent_id=intent_id, action_id=action_id)
        view["png_bytes"] = _image(self._owner.call(
            lambda: runtime.get_local_grounded_image(confirmation_id=confirmation_id)))
        self._attach_local_text(runtime, view)
        view["source_kind"] = "reviewed_learning"
        return view

    def current_fresh_review(self) -> dict[str, Any]:
        with self._guard:
            if (not _is_fresh_selection(self._selection) or self._phase not in {"pending_review", "approved"}
                    or self._runtime is None or self._confirmation_id is None):
                raise self._error("fresh_review_unavailable", "fresh review is not owned")
            runtime, confirmation_id = self._runtime, self._confirmation_id
        claim = self._owner.call(lambda: runtime.get_local_grounded_confirmation(confirmation_id=confirmation_id))
        grounded = claim.grounded_confirmation
        if grounded is None or grounded.owner_is_current is not True:
            raise self._error("fresh_review_unavailable", "fresh review is no longer owned")
        payload = grounded.preview.to_dict()
        view = {"phase": "approved" if claim.phase == "grounded_confirmation_approved" else "pending_review",
                "confirmation_id": confirmation_id, "preview": payload,
                "requested_at": grounded.requested_at.isoformat().replace("+00:00", "Z"),
                "expires_at": grounded.expires_at.isoformat().replace("+00:00", "Z"),
                "owner_is_current": True, "source_kind": "fresh_learning",
                "png_bytes": _image(self._owner.call(lambda: runtime.get_local_grounded_image(confirmation_id=confirmation_id)))}
        self._attach_local_text(runtime, view)
        return view

    def deny(self, *, confirmation_id: str, preview_content_sha256: str | None = None,
             preview_sha256: str | None = None) -> dict[str, Any]:
        self._begin("pending_review")
        try:
            runtime, observation, _proxy = self._active()
            fresh = _is_fresh_selection(self._selection)
            if fresh:
                actual_hash = preview_sha256 if preview_sha256 is not None else preview_content_sha256
            else:
                if preview_sha256 is not None or preview_content_sha256 is None:
                    raise self._error("preview_identity_mismatch", "reviewed preview identity differs")
                actual_hash = preview_content_sha256
            with self._guard:
                if confirmation_id != self._confirmation_id or actual_hash != self._preview_sha256:
                    raise self._error("preview_identity_mismatch", "review preview identity differs")
            if not fresh:
                # 已审核路径由 canonical host 关闭待审 owner；不调用首次学习决策路径。
                self._host.release_grounded_runtime(confirmation_id=confirmation_id)
                binding = self._learning_binding
                if binding is not None:
                    try:
                        binding.close_unconsumed(runtime_session_id=observation.session_id)
                    except Exception as error:
                        with self._guard:
                            self._attached = False
                            self._phase = "cleanup_required"
                        raise self._mapped(
                            error, "runtime_cleanup_pending",
                            "reviewed denial cleanup remains pending",
                        ) from None
                with self._guard:
                    self._attached = False
                self._clear()
                return {"phase": "denied", "confirmation_id": confirmation_id,
                        "artifact_is_authorization": False}
            result = self._owner.call(lambda: runtime.decide_grounded_confirmation(
                confirmation_id=confirmation_id, decision="denied"))
            if getattr(result, "phase", None) not in {"grounded_confirmation_denied", "grounded_confirmation_closed"}:
                raise self._error("review_denial_failed", "review denial was not recorded")
            self._host.release_grounded_runtime(
                confirmation_id=confirmation_id,
                timeout=max(30.0, self._foreground_timeout),
            )
            with self._guard:
                self._attached = False
                self._phase = "observed"
            return {"phase": "denied", "confirmation_id": confirmation_id,
                    "artifact_is_authorization": False}
        finally:
            self._end()

    def _text_requirements_on_owner(self, runtime, observation, action_id):
        actions = [action for action in observation.available_actions if action.action_id == action_id]
        if len(actions) != 1 or actions[0].semantic_action not in READ_ONLY_REVIEW_ACTIONS:
            raise self._error("action_not_available", "action is not available")
        if actions[0].semantic_action != "fill_field":
            return None
        reviewed = runtime.get_local_reviewed_text_parameters(action_id=action_id)
        if type(reviewed) is not ReviewedTextParameters or text_parameter_reference(reviewed) != actions[0].text_parameters_ref:
            raise self._error("text_declaration_mismatch", "owned text declaration differs")
        return reviewed

    def _resolve_text_on_owner(self, runtime, observation, action_id, variables):
        reviewed = self._text_requirements_on_owner(runtime, observation, action_id)
        try:
            if variables is not None and type(variables) is not dict:
                raise ValueError("invalid text values")
            if reviewed is None:
                if variables:
                    raise ValueError("non-text action received text values")
                return None
            values = {} if variables is None else variables
            expected = {reviewed.content.value} if reviewed.content.kind == "variable" else set()
            if set(values) != expected:
                raise ValueError("text values do not match the reviewed source")
            return resolve_text_parameters(reviewed, values)
        except (TypeError, ValueError):
            raise self._error("text_input_invalid", "required text values are missing or invalid") from None

    def request_review(self, *, action_id: str, text_values: dict[str, str] | None = None,
                       expected_learning_binding: Any | None = None, intent_id: str | None = None) -> dict[str, Any]:
        self._begin("observed")
        invoked = False
        try:
            if not isinstance(action_id, str) or not action_id:
                raise self._error("invalid_action_id", "action identity is invalid")
            runtime, observation, proxy = self._active()
            with self._guard:
                if expected_learning_binding is not None and self._learning_binding is not expected_learning_binding:
                    raise self._error("runtime_owner_mismatch", "learning preparation owner differs")
            if action_id not in {item["action_id"] for item in _actions(observation.available_actions)}:
                raise self._error("action_not_available", "action is not available")
            variables = deepcopy(text_values)
            text_input = self._owner.call(lambda: self._resolve_text_on_owner(runtime, observation, action_id, variables))
            request = self._intent_request(observation, action_id, intent_id=intent_id)
            with self._guard:
                self._intent_id = request.intent_id
                self._action_id = action_id
            self._owner.call(lambda: self._wait_foreground_on_owner(self._selection, bind=False))
            invoked = True
            result = self._owner.call(
                lambda: runtime.request_grounded_confirmation(request, **({"text_input": text_input} if text_input is not None else {}))
            )
            status = getattr(result, "status", None)
            if status in {"REJECTED", "RECOVERY_REQUIRED"}:
                if status == "RECOVERY_REQUIRED":
                    with self._guard:
                        self._phase = "review_recovery_required"
                raise self._error(
                    "grounded_review_rejected" if status == "REJECTED" else "runtime_cleanup_pending",
                    "grounded review was not published",
                    result_unknown=status == "RECOVERY_REQUIRED",
                )
            preliminary = getattr(getattr(result, "grounded_confirmation", None), "confirmation_id", None)
            if isinstance(preliminary, str) and preliminary:
                with self._guard:
                    self._confirmation_id = preliminary
                    self._phase = "pending_review"
            claim, view = self._review_view(
                result,
                expected_phase="grounded_confirmation_pending",
                intent_id=request.intent_id,
                action_id=action_id,
            )
            confirmation_id = view["confirmation_id"]
            with self._guard:
                self._confirmation_id = confirmation_id
                self._preview_sha256 = view["preview"]["content_sha256"]
                self._phase = "pending_review"
            view["png_bytes"] = _image(self._owner.call(
                lambda: runtime.get_local_grounded_image(confirmation_id=confirmation_id)
            ))
            self._attach_local_text(runtime, view)
            self._host.attach_grounded_runtime(proxy, confirmation_id=confirmation_id)
            with self._guard:
                self._attached = True
            return view
        except NativeSingleStepCoordinatorError as error:
            if invoked and error.code != "grounded_review_rejected":
                with self._guard:
                    if self._phase == "observed":
                        self._phase = "review_recovery_required"
            raise
        except Exception as error:
            if invoked:
                with self._guard:
                    self._phase = "review_recovery_required"
            raise self._mapped(
                error,
                "review_request_failed",
                "grounded review could not be requested",
                force_unknown=invoked,
            ) from None
        finally:
            self._end()

    def approve(
        self, *, confirmation_id: str, preview_content_sha256: str | None = None,
        preview_sha256: str | None = None,
    ) -> dict[str, Any]:
        self._begin("pending_review")
        try:
            if _is_fresh_selection(self._selection):
                actual_hash = preview_sha256 if preview_sha256 is not None else preview_content_sha256
                return self._approve_fresh(confirmation_id=confirmation_id, preview_sha256=actual_hash)
            if preview_sha256 is not None or preview_content_sha256 is None:
                raise self._error("preview_identity_mismatch", "reviewed preview identity differs")
            runtime, _observation, _proxy = self._active()
            with self._guard:
                expected_id = self._confirmation_id
                expected_hash = self._preview_sha256
            if confirmation_id != expected_id:
                raise self._error("confirmation_identity_mismatch", "confirmation identity differs")
            if preview_content_sha256 != expected_hash:
                raise self._error("preview_identity_mismatch", "preview identity differs")
            self._owner.call(lambda: self._wait_foreground_on_owner(self._selection, bind=False))
            result = self._owner.call(lambda: runtime.decide_grounded_confirmation(
                confirmation_id=confirmation_id, decision="approved"
            ))
            _claim, view = self._review_view(
                result, expected_phase="grounded_confirmation_approved",
                intent_id=self._intent_id, action_id=self._action_id,
            )
            if view["preview"]["content_sha256"] != expected_hash:
                raise self._error("preview_identity_mismatch", "approved preview identity differs")
            view["png_bytes"] = _image(self._owner.call(
                lambda: runtime.get_local_grounded_image(confirmation_id=confirmation_id)
            ))
            self._attach_local_text(runtime, view)
            with self._guard:
                self._phase = "approved"
            return view
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "review_approval_failed", "grounded review approval failed") from None
        finally:
            self._end()

    def _approve_fresh(self, *, confirmation_id: str, preview_sha256: str | None) -> dict[str, Any]:
        runtime, _observation, _proxy = self._active()
        with self._guard:
            expected_id, expected_hash = self._confirmation_id, self._preview_sha256
        if confirmation_id != expected_id:
            raise self._error("confirmation_identity_mismatch", "fresh confirmation identity differs")
        if preview_sha256 != expected_hash:
            raise self._error("preview_identity_mismatch", "fresh preview identity differs")
        self._owner.call(lambda: self._wait_foreground_on_owner(self._selection, bind=False))
        result = self._owner.call(lambda: runtime.decide_grounded_confirmation(
            confirmation_id=confirmation_id, decision="approved"))
        if getattr(result, "phase", None) != "grounded_confirmation_approved":
            raise self._error("review_approval_failed", "fresh review approval was not recorded")
        view = self.current_fresh_review()
        if view["preview"]["preview_sha256"] != expected_hash or view["phase"] != "approved":
            raise self._error("preview_identity_mismatch", "approved fresh preview identity differs")
        with self._guard:
            self._phase = "approved"
        return view

    def execute(self, *, confirmation_id: str) -> dict[str, Any]:
        self._begin("approved")
        try:
            runtime, observation, _proxy = self._active()
            with self._guard:
                expected = self._confirmation_id
            if confirmation_id != expected:
                raise self._error("confirmation_identity_mismatch", "confirmation identity differs")
            if not _is_fresh_selection(self._selection):
                if not any(action.action_id == self._action_id and action.semantic_action in REVIEWED_SINGLE_STEP_ACTIONS for action in observation.available_actions):
                    raise self._error("text_execution_not_ready", "this action is currently read-only")
                action = next(item for item in observation.available_actions if item.action_id == self._action_id)
                if action.semantic_action == "fill_field":
                    try:
                        field_expectation = self._owner.call(
                            lambda: runtime.get_local_grounded_text_field_expectation(confirmation_id=confirmation_id)
                        )
                        if type(field_expectation) is not TextFieldExpectation:
                            raise ValueError("owned text field expectation is unavailable")
                    except Exception:
                        raise self._error("text_execution_not_ready", "this text preview has no owned field expectation") from None
            client = getattr(self._host, "single_step", None)
            if client is None:
                raise self._error("execution_role_unavailable", "owned execution role is unavailable")
            self._owner.call(lambda: self._wait_foreground_on_owner(self._selection, bind=False))
            try:
                response = client.execute(confirmation_id=confirmation_id)
            except Exception as error:
                if getattr(error, "result_unknown", False) is True:
                    with self._guard:
                        self._phase = "recovery_required"
                raise
            if (
                not isinstance(response, dict)
                or response.get("contract_version") != "native_single_step_response_v1"
                or response.get("confirmation_id") != confirmation_id
                or response.get("kind") not in {"receipt", "decision"}
                or response.get("artifact_is_authorization") is not False
            ):
                with self._guard:
                    self._phase = "recovery_required"
                raise self._error("execution_result_invalid", "single-step response is invalid", result_unknown=True)
            with self._guard:
                self._phase = "executed"
            return deepcopy(response)
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "execution_failed", "single-step execution failed") from None
        finally:
            self._end()

    def model_residency_settings(self) -> dict[str, Any]:
        """驻留仅保存模型进程，不保存截图、窗口绑定或执行批准。"""
        with self._guard:
            return {"keep_models_loaded": self._keep_models_loaded,
                    "allow_multiple_models": self._keep_models_loaded,
                    "resident_model_count": len(self._resident_model_services),
                    "session_only": True}

    def _begin_model_settings(self) -> None:
        with self._guard:
            if (self._busy or self._shutdown or self._phase != "idle"
                    or self._runtime is not None or self._confirmation_id is not None
                    or self._model_service is not None or self._factory_outcome_unknown
                    or self._model_release_pending or self._window_preparations):
                raise self._error("model_residency_change_unavailable",
                    "Cancel the current step before changing or releasing resident models.")
            self._busy = True

    def set_keep_models_loaded(self, enabled: bool) -> dict[str, Any]:
        """关闭选项先验证释放；失败保留原设置和清理拥有权。"""
        if type(enabled) is not bool:
            raise TypeError("keep_models_loaded must be a bool")
        self._begin_model_settings()
        try:
            if not enabled or self._resident_model_cleanup_pending:
                self._release_resident_models()
            with self._guard:
                self._keep_models_loaded = enabled
            return self.model_residency_settings()
        finally:
            self._end()

    def release_resident_models(self) -> dict[str, Any]:
        """释放闲置模型，不修改偏好，不终止外部服务。"""
        self._begin_model_settings()
        try:
            self._release_resident_models()
            return self.model_residency_settings()
        finally:
            self._end()

    def _release_resident_models(self) -> None:
        with self._guard:
            self._resident_model_cleanup_pending = bool(self._resident_model_services)
            entries = list(self._resident_model_services.items())
        for key, service in entries:
            try:
                proof = self._owner.call(service.close)
                if not isinstance(proof, dict) or proof.get("cleanup_verified") is not True:
                    raise self._error("model_service_cleanup_pending", "Resident model cleanup is unverified.", result_unknown=True)
            except Exception as error:
                raise self._mapped(error, "model_service_cleanup_pending",
                    "Resident model cleanup remains pending; retry release.", force_unknown=True) from error
            with self._guard:
                del self._resident_model_services[key]
        with self._guard:
            self._resident_model_cleanup_pending = False

    def _cancel_cleanup_result(self) -> dict[str, Any]:
        result = {"phase": "idle", "cleanup_verified": True}
        if self._keep_models_loaded or self._resident_model_services:
            # 步骤清理不等于模型进程退出，显式报告仍驻留的数量。
            result["model_residency"] = self.model_residency_settings()
        return result

    def observe_learning_target_passively(
        self,
        *,
        application_identity: dict[str, Any],
        target_window_handle: int,
        target_process_id: int,
        goal: str,
    ) -> Any:
        """在既有受管模型 owner 上执行只读目标观察，不绑定窗口或创建选择。"""
        self._begin("idle", preserve_window_preparation=True)
        cleanup_attempted = False
        configuration = None
        try:
            self._require_host_ready(require_unattached=True)
            if self._model_service is not None:
                raise self._error(
                    "model_service_cleanup_pending",
                    "Release the retained model owner before observing again.",
                )

            def prepare_service() -> None:
                nonlocal configuration
                self._check_runtime_environment()
                try:
                    configuration = load_formal_vision_configuration(self._vision_config_path)
                    model_configuration = freeze_model_service(configuration)
                except (VisionConfigurationError, ModelServiceError) as error:
                    raise self._error(
                        error.code,
                        "Vision configuration must be corrected before observing a target.",
                    ) from None
                with self._guard:
                    self._phase = "passive_observing"
                    if model_configuration is not None:
                        self._model_service_configuration = model_configuration
                if model_configuration is not None:
                    self._prepare_model_service_on_owner(model_configuration)

            self._owner.call(prepare_service)
            if self._cancel_wait.is_set():
                raise self._error("observation_cancelled", "targeted observation was cancelled")

            def observe_on_owner() -> Any:
                from app.agent.fresh_learning_factory import create_fresh_learning_observation_owner

                if self._cancel_wait.is_set():
                    raise self._error("observation_cancelled", "targeted observation was cancelled")
                owner = create_fresh_learning_observation_owner(
                    project_root=self._project_root,
                    application_identity=application_identity,
                    target_window_handle=target_window_handle,
                    target_process_id=target_process_id,
                    vision_configuration=configuration,
                )
                return owner.observe(
                    target_window_handle=target_window_handle,
                    target_process_id=target_process_id,
                    goal=goal,
                )

            packet = self._owner.call(observe_on_owner)
            if self._cancel_wait.is_set():
                raise self._error("observation_cancelled", "targeted observation was cancelled")
            cleanup_attempted = True
            self._release_model_service()
            if self._cancel_wait.is_set():
                raise self._error("observation_cancelled", "targeted observation was cancelled")
            self._clear()
            return packet
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "observation_failed", "targeted observation failed") from None
        finally:
            try:
                if self._model_service is not None and not cleanup_attempted:
                    cleanup_attempted = True
                    self._release_model_service(force=True)
            except Exception:
                with self._guard:
                    if self._model_service is not None:
                        self._phase = "passive_observation_cleanup_required"
                raise
            else:
                if self._model_service is None:
                    with self._guard:
                        passive = self._phase == "passive_observing"
                    if passive:
                        self._clear()
                else:
                    with self._guard:
                        self._phase = "passive_observation_cleanup_required"
            finally:
                self._end()

    def cancel(self, *, expected_learning_binding: Any | None = None) -> dict[str, Any]:
        with self._guard:
            if expected_learning_binding is not None and self._learning_binding is not expected_learning_binding:
                raise self._error("runtime_owner_mismatch", "learning preparation owner differs")
            if self._history_confirmation_id is not None:
                raise self._error("grounded_recovery_owner_busy", "Finish the retained post-verification recovery before releasing its owner.", result_unknown=True)
            if self._busy:
                raise self._error("lifecycle_busy", "coordinator operation is active")
            if self._phase == "idle":
                return self._cancel_cleanup_result()
            self._busy = True
            attached = self._attached
            confirmation_id = self._confirmation_id
            runtime = self._runtime
            observation = self._observation
            phase = self._phase
            factory_outcome_unknown = self._factory_outcome_unknown
        try:
            if self._model_release_pending:
                self._release_model_service()
                self._clear()
                return self._cancel_cleanup_result()
            if factory_outcome_unknown:
                raise self._error(
                    "runtime_cleanup_pending",
                    "runtime factory ownership cannot be verified",
                    result_unknown=True,
                )
            if attached:
                if confirmation_id is None:
                    raise self._error("cleanup_identity_missing", "cleanup identity is missing")
                # 在 host 清理精确 owner 前冻结同一绑定的事实状态；释放后绝不重连或再执行。
                if (_is_fresh_selection(self._selection) and self._learning_binding is not None
                        and runtime is not None and observation is not None):
                    self._freeze_fresh_runtime_snapshot(runtime)
                release_options = {"timeout": 30.0} if _is_fresh_selection(self._selection) else {}
                self._host.release_grounded_runtime(confirmation_id=confirmation_id, **release_options)
                released = self._host.status()
                if (
                    not isinstance(released, dict)
                    or released.get("contract_version") != "native_review_host_v1"
                    or released.get("phase") != "ready"
                    or released.get("staging_only") is not True
                    or getattr(self._host, "single_step", None) is not None
                ):
                    raise self._error(
                        "runtime_cleanup_pending", "host release was not verified"
                    )
                if (_is_fresh_selection(self._selection) and self._learning_binding is not None
                        and runtime is not None and observation is not None):
                    self._freeze_fresh_runtime_snapshot(runtime)
            elif runtime is not None and observation is None:
                self._cleanup_unattached_local(runtime, self._selection)
            elif runtime is not None and observation is not None:
                session_id = observation.session_id
                if confirmation_id is None and phase != "review_recovery_required":
                    if callable(getattr(runtime, "cancel_local_preparation", None)):
                        self._cleanup_unattached_local(runtime, self._selection)
                    else:
                        result = self._owner.call(
                            lambda: runtime.cancel_prepared_session(session_id=session_id)
                        )
                        if result is not None:
                            raise self._error("runtime_cleanup_pending", "prepared cleanup was not verified")
                else:
                    result = self._owner.call(
                        lambda: runtime.cancel_grounded_review(session_id=session_id)
                    )
                    if confirmation_id is None:
                        _validate_grounded_cancel_unknown(result, session_id)
                    else:
                        if _is_fresh_selection(self._selection):
                            _validate_fresh_cancel(result, session_id, confirmation_id)
                        else:
                            _validate_grounded_cancel(result, session_id, confirmation_id)
            if (not attached and _is_fresh_selection(self._selection) and self._learning_binding is not None
                    and runtime is not None and observation is not None):
                self._freeze_fresh_runtime_snapshot(runtime)
            self._release_model_service()
            self._clear()
            return self._cancel_cleanup_result()
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "runtime_cleanup_pending", "runtime cleanup remains pending") from None
        finally:
            self._end()

    def cancel_waiting(self, *, expected_learning_binding: Any | None = None) -> bool:
        with self._guard:
            if expected_learning_binding is not None and self._learning_binding is not expected_learning_binding:
                return False
            self._cancel_wait.set()
            return True

    def learning_runtime_state(self) -> dict[str, Any]:
        """仅返回本地拥有权快照；绑定含锁，不能复制或发给 Agent。"""
        with self._guard:
            return {"binding": self._learning_binding, "phase": self._phase,
                    "busy": self._busy, "shutdown": self._shutdown,
                    "session_id": getattr(self._observation, "session_id", None)}

    def shutdown(self) -> None:
        self.cancel_waiting()
        with self._guard:
            if self._history_confirmation_id is not None:
                raise self._error("grounded_recovery_owner_busy", "The post-verification recovery owner must be retained.", result_unknown=True)
            if self._shutdown:
                return
            if self._busy:
                raise self._error("lifecycle_busy", "coordinator operation is active")
            self._busy = True
            attached = self._attached
            runtime, observation = self._runtime, self._observation
            factory_outcome_unknown = self._factory_outcome_unknown
        try:
            if factory_outcome_unknown:
                raise self._error(
                    "shutdown_cleanup_pending",
                    "runtime factory ownership cannot be verified",
                    result_unknown=True,
                )
            if not self._model_release_pending and not attached and runtime is not None:
                if self._confirmation_id is None:
                    self._cleanup_unattached_local(runtime, self._selection)
                elif observation is not None:
                    result = self._owner.call(lambda: runtime.cancel_grounded_review(session_id=observation.session_id))
                    _validate_grounded_cancel(result, observation.session_id, self._confirmation_id)
                else:
                    raise self._error(
                        "runtime_cleanup_pending",
                        "grounded cleanup identity is incomplete",
                    )
            self._host.close()
            self._release_model_service(force=True)
            self._release_resident_models()
            self._owner.close()
            self._clear()
            with self._guard:
                self._shutdown = True
        except NativeSingleStepCoordinatorError:
            raise
        except Exception as error:
            raise self._mapped(error, "shutdown_cleanup_pending", "coordinator shutdown cleanup is pending") from error
        finally:
            self._end()

    def _check_runtime_environment(self) -> None:
        if not self._uses_production_factory:
            return
        report = inspect_environment(profile="windows_runtime")
        if report["status"] != "metadata_present_unverified":
            raise self._error(
                "runtime_dependencies_missing",
                "Runtime dependency metadata is unavailable or unsupported; run "
                "scripts/check_desktop_environment.py --profile windows_runtime "
                "with this interpreter before preparing a target.",
            )

    def _create_runtime_on_owner(self, selection: Any) -> Any:
        if not self._automatic_safety_interception and not _is_fresh_selection(selection):
            raise self._error("safety_observation_mode_unsupported",
                "This debug entry does not support disabled automatic interception; no model or action was started.")
        self._check_runtime_environment()
        # 在窗口绑定和拥有权变更前固定配置，失败可直接修正后重试。
        configuration = None
        model_configuration = None
        if self._uses_production_factory:
            try:
                configuration = load_formal_vision_configuration(self._vision_config_path)
                model_configuration = freeze_model_service(configuration)
            except (VisionConfigurationError, ModelServiceError) as error:
                raise self._error(error.code, "Vision configuration must be corrected before preparing a target.") from None
        if self._model_service is not None:
            raise self._error("model_service_cleanup_pending", "Release the retained model owner before preparing again.")
        self._wait_foreground_on_owner(selection, bind=True)
        if model_configuration is not None:
            with self._guard:
                self._selection = selection
                self._phase = "prepare_recovery_required"
            self._prepare_model_service_on_owner(model_configuration)
            # 权重加载期间窗口可能已经切换，不能沿用加载前的前台判断。
            self._wait_foreground_on_owner(selection, bind=False)
        with self._guard:
            self._selection = selection
            self._phase = "prepare_recovery_required"
            self._factory_outcome_unknown = True
        runtime = self._runtime_factory(
            project_root=self._project_root,
            selection=selection,
            window_manager=self._windows(),
            **({"vision_configuration": configuration} if configuration is not None else {}),
            **({"learning_binding": self._learning_binding} if self._learning_binding is not None else {}),
            **({"fresh_source_owner": self._host.fresh_learning} if self._uses_production_factory and _is_fresh_selection(selection) else {}),
            **({"automatic_safety_interception": self._automatic_safety_interception} if self._uses_production_factory else {}),
        )
        if runtime is None or not callable(getattr(runtime, "start_session", None)):
            raise self._error(
                "runtime_factory_invalid",
                "runtime factory returned an invalid start protocol",
                result_unknown=True,
            )
        return runtime

    def _prepare_model_service_on_owner(self, configuration) -> None:
        with self._guard:
            if self._keep_models_loaded and configuration not in self._resident_model_services:
                port = configuration.profile()["port"]
                if any(saved.profile()["port"] == port for saved in self._resident_model_services):
                    # 同端口旧权重不能因 API 模型名相同被误收养为新配置的外部服务。
                    raise self._error("model_service_resident_configuration_conflict",
                        "Release the resident model on this port before changing its configuration.")
            resident = self._resident_model_services.pop(configuration, None) if self._keep_models_loaded else None
            self._model_service_configuration = configuration
            self._model_reuse_failed = False
            self._model_service = resident or FormalModelService(
                configuration, output_root=self._runtime_output_root,
                **({"allow_resource_coexistence": True} if self._keep_models_loaded else {}))
        if resident is None:
            self._model_service.prepare(self._cancel_wait)
        else:
            try:
                resident.reuse_ready(self._cancel_wait)
            except BaseException:
                # 实例或健康变化不能靠静默重启掩盖；保留该 owner 供显式清理。
                self._model_reuse_failed = True
                raise

    def _release_model_service(self, *, force: bool = False) -> None:
        if self._model_service is None:
            return
        if (self._keep_models_loaded and not force and not self._model_release_pending
                and not self._model_reuse_failed and not self._cancel_wait.is_set()
                and self._model_service_configuration is not None
                and self._owner.call(self._model_service.can_retain)):
            with self._guard:
                self._resident_model_services[self._model_service_configuration] = self._model_service
                self._model_service = None
                self._model_service_configuration = None
            return
        self._model_release_pending = True
        proof = self._owner.call(self._model_service.close)
        if not isinstance(proof, dict) or proof.get("cleanup_verified") is not True:
            raise self._error("model_service_cleanup_pending", "Model cleanup could not be verified.", result_unknown=True)
        self._model_service = None
        self._model_service_configuration = None
        self._model_reuse_failed = False
        self._model_release_pending = False

    def _model_request_scope(self):
        from app.vision.request_control import ModelRequestContext, ModelRequestError, pinned_model_request

        service = self._model_service
        if service is None:
            return nullcontext()

        def verify(endpoint: str, model_name: str) -> None:
            try:
                service.verify_request_instance(endpoint, model_name)
            except ModelServiceError as error:
                raise ModelRequestError(error.code) from error

        def begin(request_id: str) -> None:
            try:
                service.begin_request(request_id)
            except ModelServiceError as error:
                raise ModelRequestError(error.code) from error

        # 只绑定已显式配置的本地受管链；旧外部服务接口保持原有行为。
        return pinned_model_request(ModelRequestContext(self._cancel_wait, verify_instance=verify,
            on_started=begin, on_completed=service.complete_request, on_cancelled=service.cancel_request))

    def _wait_foreground_on_owner(self, selection: Any, *, bind: bool) -> None:
        windows = self._windows()
        if bind:
            bound = windows.bind_window_by_handle(selection.target_window_handle)
            _exact_window(bound, selection)
        deadline = time.monotonic() + self._foreground_timeout
        while True:
            if self._cancel_wait.is_set():
                raise self._error("foreground_wait_cancelled", "foreground wait was cancelled")
            current = windows.get_bound_window()
            _exact_window(current, selection)
            key = _selection_identity(selection)
            prepared_identity = self._prepared_window_identities.get(key)
            if prepared_identity is not None:
                from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
                observed_identity = WindowsNativeIdentityReader(window_manager=windows).read_identity(selection.target_window_handle)
                checked_identity = validate_native_identity_fact(
                    observed_identity, target_window_handle=selection.target_window_handle,
                    expected_process_id=selection.target_process_id,
                    expected_executable_path=prepared_identity["executable_path"],
                )
                if checked_identity != prepared_identity:
                    raise self._error("window_preparation_identity_changed", "prepared window identity changed")
            if getattr(current, "is_active", None) is True:
                break
            if time.monotonic() >= deadline:
                raise self._error("foreground_wait_timeout", "target window did not become foreground")
            self._cancel_wait.wait(min(0.05, max(0.0, deadline - time.monotonic())))

    def _windows(self) -> Any:
        if self._window_manager is not None:
            return self._window_manager
        from app.core.window_manager import window_manager

        return window_manager

    def _intent_request(self, observation: Any, action_id: str, *, intent_id: str | None = None) -> Any:
        try:
            from app.api.agent_runtime import AgentRuntimeIntentRequest

            return AgentRuntimeIntentRequest(
                intent_id=intent_id if intent_id is not None else "intent-" + uuid4().hex,
                session_id=observation.session_id,
                observation_id=observation.observation_id,
                action_id=action_id,
            )
        except Exception:
            raise self._error("intent_construction_failed", "runtime intent could not be constructed") from None

    def _review_view(
        self,
        claim: Any,
        *,
        expected_phase: str,
        intent_id: str,
        action_id: str,
    ) -> tuple[Any, dict[str, Any]]:
        grounded = getattr(claim, "grounded_confirmation", None)
        preview = getattr(grounded, "preview", None)
        try:
            payload = preview.to_dict()
        except Exception:
            raise self._error("review_snapshot_invalid", "grounded review snapshot is invalid") from None
        phase = getattr(claim, "phase", None)
        owner = getattr(grounded, "owner_is_current", None)
        confirmation_id = getattr(grounded, "confirmation_id", None)
        observation = self._observation
        selection = self._selection
        workflow = getattr(observation, "workflow", None)
        workflow_json = workflow.model_dump(mode="json") if callable(getattr(workflow, "model_dump", None)) else {
            "workflow_id": getattr(workflow, "workflow_id", None),
            "asset_id": getattr(workflow, "asset_id", None),
        }
        if (
            phase != expected_phase
            or owner is not True
            or not isinstance(confirmation_id, str)
            or not isinstance(getattr(grounded, "requested_at", None), str)
            or not isinstance(getattr(grounded, "expires_at", None), str)
            or not isinstance(payload, dict)
            or not isinstance(payload.get("content_sha256"), str)
            or getattr(getattr(claim, "observation", None), "session_id", None)
            != getattr(observation, "session_id", None)
            or getattr(getattr(claim, "observation", None), "observation_id", None)
            != getattr(observation, "observation_id", None)
            or getattr(getattr(claim, "intent", None), "intent_id", None) != intent_id
            or payload.get("session_id") != getattr(observation, "session_id", None)
            or payload.get("observation_id") != getattr(observation, "observation_id", None)
            or payload.get("intent_id") != intent_id
            or payload.get("workflow") != workflow_json
            or payload.get("target_window_handle") != selection.target_window_handle
            or payload.get("target_process_id") != selection.target_process_id
            or not isinstance(payload.get("review_selection"), dict)
            or payload["review_selection"].get("transition_id") != action_id
        ):
            raise self._error("review_snapshot_invalid", "grounded review snapshot is invalid")
        return claim, {
            "phase": "pending_review" if expected_phase.endswith("pending") else "approved",
            "confirmation_id": confirmation_id,
            "preview": deepcopy(payload),
            "requested_at": getattr(grounded, "requested_at", None),
            "expires_at": getattr(grounded, "expires_at", None),
            "owner_is_current": True,
        }

    def _attach_local_text(self, runtime, view):
        from app.agent.automatic_safety_policy import FRESH_PREVIEW_VERSIONS
        preview = view["preview"]
        semantic = (preview.get("intent", {}).get("semantic_action")
            if preview.get("contract_version") in FRESH_PREVIEW_VERSIONS
            else preview.get("grounding_preview", {}).get("semantic_action"))
        if semantic == "fill_field":
            resolved = self._owner.call(lambda: runtime.get_local_grounded_text_input(confirmation_id=view["confirmation_id"]))
            validate_local_text_preview(view["preview"], resolved)
            view["text_input_local"] = resolved
            if "text_field_expectation_ref" in view["preview"]:
                expected = self._owner.call(
                    lambda: runtime.get_local_grounded_text_field_expectation(
                        confirmation_id=view["confirmation_id"]
                    )
                )
                if (type(expected) is not TextFieldExpectation
                        or expected.parameters != resolved
                        or expected.to_reference() != view["preview"]["text_field_expectation_ref"]):
                    raise self._error("text_field_expectation_mismatch", "local text field expectation differs")
                view["text_field_local"] = expected

    def _freeze_fresh_runtime_snapshot(self, runtime: Any) -> None:
        """清理前尽力保存事实；来源重载失败不得阻断精确 owner 清理。"""
        try:
            snapshot = self._owner.call(runtime.get_fresh_runtime_state)
        except Exception:
            snapshot = {"source_kind": "fresh_learning", "status": "snapshot_unavailable",
                        "artifact_is_authorization": False}
        with self._guard:
            if self._learning_binding is not None:
                self._fresh_runtime_snapshots[id(self._learning_binding)] = (
                    self._learning_binding, deepcopy(snapshot),
                )

    def _active(self) -> tuple[Any, Any, RuntimeOwnerProxy]:
        with self._guard:
            if self._runtime is None or self._observation is None or self._proxy is None:
                raise self._error("runtime_owner_unavailable", "runtime owner is unavailable")
            return self._runtime, self._observation, self._proxy

    def _require_host_ready(self, *, require_unattached: bool = False) -> None:
        status = self._host.status()
        if not isinstance(status, dict) or status.get("phase") != "ready" or not status.get("base_url"):
            raise self._error("host_not_ready", "desktop host is not ready")
        if require_unattached and status.get("reviewed_single_step_enabled") is True:
            raise self._error("runtime_already_attached", "a grounded runtime is already attached")

    def _begin(self, required_phase: str, *, preserve_window_preparation: bool = False) -> None:
        self._begin_any({required_phase}, preserve_window_preparation=preserve_window_preparation)

    def _end(self) -> None:
        with self._guard:
            self._busy = False

    def _clear(self) -> None:
        with self._guard:
            self._history_confirmation_id = None
            self._phase = "idle"
            self._runtime = self._proxy = self._observation = self._selection = None
            self._learning_binding = None
            self._factory_outcome_unknown = False
            self._confirmation_id = self._preview_sha256 = None
            self._intent_id = self._action_id = None
            self._attached = False
            self._model_release_pending = False

    def _cleanup_unattached_local(self, runtime: Any, selection: Any) -> None:
        cleanup = getattr(runtime, "cancel_local_preparation", None)
        if callable(cleanup):
            proof = self._owner.call(cleanup)
            _validate_local_preparation_cleanup(proof, selection)
            with self._guard:
                self._observation = None
            return
        observation = self._observation
        if observation is None:
            raise self._error(
                "runtime_cleanup_pending",
                "runtime preparation ownership cannot be verified",
                retry_preparation=False,
            )
        result = self._owner.call(
            lambda: runtime.cancel_prepared_session(
                session_id=observation.session_id
            )
        )
        if result is not None:
            raise self._error(
                "runtime_cleanup_pending",
                "prepared cleanup was not verified",
            )
        with self._guard:
            self._observation = None

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        result_unknown: bool = False,
        retry_preparation: bool = False,
    ) -> NativeSingleStepCoordinatorError:
        return NativeSingleStepCoordinatorError(
            code,
            message,
            result_unknown=result_unknown,
            retry_preparation=retry_preparation,
        )

    @staticmethod
    def _mapped(
        error: Exception,
        code: str,
        message: str,
        *,
        force_unknown: bool = False,
        retry_preparation: bool = False,
    ) -> NativeSingleStepCoordinatorError:
        from app.vision.request_control import ModelRequestError
        from app.core.failure_diagnostics import log_failure_structure

        log_failure_structure(error, "native_coordinator")

        underlying = getattr(error, "code", None)
        computation_stopped = False
        cause: BaseException | None = error
        seen: set[int] = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, ModelRequestError):
                underlying = cause.code
                computation_stopped = cause.computation_stopped is True
                break
            cause = cause.__cause__
        if underlying == "model_request_cancelled":
            message = ("识别请求已取消；已确认本次请求不再活动。" if computation_stopped
                       else "识别请求已取消；服务端计算尚未确认停止。")
        return NativeSingleStepCoordinatorError(
            underlying if isinstance(underlying, str) and underlying else code,
            message,
            result_unknown=(
                force_unknown or getattr(error, "result_unknown", False) is True
            ),
            retry_preparation=retry_preparation,
            computation_stopped=computation_stopped,
        )

    def _begin_any(self, phases: set[str], *, preserve_window_preparation: bool = False) -> None:
        with self._guard:
            if self._model_release_pending or self._resident_model_cleanup_pending:
                raise self._error("model_service_cleanup_pending", "Model cleanup must finish before another operation.", result_unknown=True)
            if self._shutdown:
                raise self._error("coordinator_closed", "coordinator is closed")
            if self._busy:
                raise self._error("lifecycle_busy", "coordinator operation is active")
            if self._phase not in phases:
                raise self._error("invalid_phase", "operation is not valid in the current phase")
            if not preserve_window_preparation:
                self._window_preparations.clear()
            # 在公布新操作前清除上轮事件，不能抹掉本轮已接收的取消请求。
            self._cancel_wait.clear()
            self._busy = True


def _production_runtime_factory(*, project_root: Path, selection: Any, window_manager: Any, vision_configuration=None, learning_binding=None, fresh_source_owner=None, automatic_safety_interception=True) -> Any:
    from .fresh_runtime_callsite import FreshRuntimeSelection, build_fresh_runtime_callsite

    if type(automatic_safety_interception) is not bool:
        raise TypeError("automatic_safety_interception must be a bool")
    if isinstance(selection, FreshRuntimeSelection):
        if learning_binding is None:
            raise ValueError("fresh runtime requires a learning binding")
        return build_fresh_runtime_callsite(
            project_root=project_root, selection=selection, window_manager=window_manager,
            fresh_source_owner=fresh_source_owner,
            learning_binding=learning_binding, vision_configuration=vision_configuration,
            automatic_safety_interception=automatic_safety_interception,
        )
    if not automatic_safety_interception:
        raise NativeSingleStepCoordinatorError("safety_observation_mode_unsupported",
            "safety_observation_mode_unsupported: the published-workflow debug entry still requires automatic interception")
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore
    from app.api.agent_runtime import LocalAgentRuntimeCallsite

    receipts = RuntimeReceiptStore(project_root=project_root)
    claims = RuntimeIntentClaimStore(project_root=project_root, receipt_store=receipts)
    return LocalAgentRuntimeCallsite(
        project_root=project_root,
        asset_store=ReviewedWorkflowAssetStore(project_root=project_root),
        window_manager=window_manager,
        claim_store=claims,
        selection=selection,
        vision_configuration=vision_configuration,
        learning_binding=learning_binding,
    )


def _selection(asset_id: Any, asset_hash: Any, handle: Any, process_id: Any) -> Any:
    try:
        from app.agent.runtime_session_selection import RuntimeSessionSelection

        return RuntimeSessionSelection(
            asset_id=asset_id,
            asset_content_sha256=asset_hash,
            target_window_handle=handle,
            target_process_id=process_id,
        )
    except (TypeError, ValueError):
        raise NativeSingleStepCoordinatorError("invalid_selection", "runtime selection is invalid") from None


def _exact_window(window: Any, selection: Any) -> None:
    if (
        window is None
        or getattr(window, "handle", None) != selection.target_window_handle
        or getattr(window, "process_id", None) != selection.target_process_id
    ):
        raise NativeSingleStepCoordinatorError("target_window_changed", "target window identity changed")


def _assets(value: Any) -> list[dict[str, Any]]:
    required = {"asset_id", "content_sha256", "application", "display_name"}
    if not isinstance(value, list):
        raise ValueError
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError
        result.append(deepcopy(item))
    return result


def _windows(value: Any) -> list[dict[str, Any]]:
    required = {"handle", "title", "process_id", "process_name"}
    if not isinstance(value, list):
        raise ValueError
    result = []
    for item in value:
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError
        handle, process_id = item["handle"], item["process_id"]
        if (
            type(handle) is not int
            or handle <= 0
            or type(process_id) is not int
            or process_id <= 0
        ):
            continue
        title = item["title"]
        process_name = item["process_name"]
        if title is not None and not isinstance(title, str):
            raise ValueError
        if process_name is not None and not isinstance(process_name, str):
            raise ValueError
        result.append({
            "handle": handle,
            "title": title or "",
            "process_id": process_id,
            "process_name": process_name or "",
        })
    return result


def _actions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, (list, tuple)):
        raise NativeSingleStepCoordinatorError("runtime_observation_invalid", "available actions are invalid")
    result = []
    seen = set()
    for action in value:
        action_id = getattr(action, "action_id", None)
        semantic = getattr(action, "semantic_action", None)
        if semantic == "safe_stop":
            continue
        if semantic not in READ_ONLY_REVIEW_ACTIONS:
            continue
        target = getattr(action, "target_state_id", None)
        if not all(isinstance(item, str) and item for item in (action_id, semantic, target)) or action_id in seen:
            raise NativeSingleStepCoordinatorError("runtime_observation_invalid", "available actions are invalid")
        seen.add(action_id)
        result.append({"action_id": action_id, "semantic_action": semantic, "target": target})
    return result


def _preflight_diagnostic(observation: Any) -> dict[str, Any]:
    safe_stop = getattr(observation, "safe_stop", None)
    state = getattr(observation, "state", None)
    current_capture = getattr(observation, "current_capture", None)
    blockers = getattr(observation, "blockers", None)
    reason_code = getattr(safe_stop, "reason_code", None)
    state_status = getattr(state, "status", None)
    state_id = getattr(state, "state_id", None)
    capture_id = getattr(current_capture, "capture_id", None)
    if (
        not isinstance(reason_code, str)
        or not reason_code
        or not isinstance(state_status, str)
        or not state_status
        or not (isinstance(state_id, str) or state_id is None)
        or not isinstance(capture_id, str)
        or not capture_id
        or not isinstance(blockers, (list, tuple))
    ):
        return {
            "contract_version": "native_preflight_diagnostic_v1",
            "status": "unavailable",
            "unavailable_reason_code": "observation_diagnostic_fields_unavailable",
            "artifact_is_authorization": False,
        }
    normalized_blockers = []
    for blocker in blockers:
        blocker_id = getattr(blocker, "blocker_id", None)
        description = getattr(blocker, "description", None)
        if not isinstance(blocker_id, str) or not blocker_id or not isinstance(description, str) or not description:
            return {
                "contract_version": "native_preflight_diagnostic_v1",
                "status": "unavailable",
                "unavailable_reason_code": "observation_diagnostic_fields_unavailable",
                "artifact_is_authorization": False,
            }
        normalized_blockers.append({"reason_code": blocker_id, "description": description})
    return {
        "contract_version": "native_preflight_diagnostic_v1",
        "status": "available",
        "safe_stop_reason_code": reason_code,
        "state_status": state_status,
        "state_id": state_id,
        "capture_id": capture_id,
        "blockers": normalized_blockers,
        "artifact_is_authorization": False,
    }



def _positive_timeout(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("foreground_timeout must be positive")
    return float(value)


def _validate_local_preparation_cleanup(value: Any, selection: Any) -> None:
    expected_selection = _selection_payload(selection)
    if (
        not isinstance(value, dict)
        or set(value) != {"contract_version", "selection", "cleanup_verified", "artifact_is_authorization"}
        or value.get("contract_version") != "local_preparation_cleanup_v1"
        or value.get("selection") != expected_selection
        or value.get("cleanup_verified") is not True
        or value.get("artifact_is_authorization") is not False
    ):
        raise NativeSingleStepCoordinatorError(
            "runtime_cleanup_pending", "local preparation cleanup was not verified", retry_preparation=True,
        )


def _is_fresh_selection(selection: Any) -> bool:
    return getattr(selection, "to_dict", None) is not None and selection.to_dict().get("source_kind") == "fresh_learning"


def _selection_payload(selection: Any) -> dict[str, Any]:
    if _is_fresh_selection(selection):
        return selection.to_dict()
    return {"asset_id": selection.asset_id, "asset_content_sha256": selection.asset_content_sha256,
            "target_window_handle": selection.target_window_handle, "target_process_id": selection.target_process_id}


def _selection_identity(selection: Any) -> tuple[Any, ...]:
    payload = _selection_payload(selection)
    return tuple((key, payload[key]) for key in sorted(payload))

def _validate_fresh_cancel(value: Any, session_id: str, confirmation_id: str) -> None:
    phase = getattr(value, "phase", None)
    observation = getattr(value, "observation", None)
    grounded = getattr(value, "grounded_confirmation", None)
    if (phase not in {"grounded_confirmation_closed", "grounded_confirmation_denied"}
            or getattr(observation, "session_id", None) != session_id
            or getattr(grounded, "confirmation_id", None) != confirmation_id):
        raise NativeSingleStepCoordinatorError("runtime_cleanup_pending", "fresh grounded cleanup was not verified")


def _validate_grounded_cancel(value: Any, session_id: str, confirmation_id: str) -> None:
    grounded = getattr(value, "grounded_confirmation", None)
    observation = getattr(value, "observation", None)
    if (
        getattr(value, "phase", None) != "grounded_confirmation_closed"
        or getattr(observation, "session_id", None) != session_id
        or getattr(grounded, "confirmation_id", None) != confirmation_id
        or getattr(grounded, "closed_reason_code", None)
        != "grounded_confirmation_cancelled"
    ):
        raise NativeSingleStepCoordinatorError(
            "runtime_cleanup_pending", "grounded cleanup was not verified"
        )


def _validate_grounded_cancel_unknown(value: Any, session_id: str) -> None:
    grounded = getattr(value, "grounded_confirmation", None)
    observation = getattr(value, "observation", None)
    confirmation_id = getattr(grounded, "confirmation_id", None)
    if (
        getattr(value, "phase", None) != "grounded_confirmation_closed"
        or getattr(observation, "session_id", None) != session_id
        or not isinstance(confirmation_id, str)
        or not confirmation_id.startswith("grounded-confirmation.")
        or getattr(grounded, "closed_reason_code", None)
        != "grounded_confirmation_cancelled"
    ):
        raise NativeSingleStepCoordinatorError(
            "runtime_cleanup_pending", "grounded cleanup was not verified"
        )


def _image(value: Any) -> bytes:
    if not isinstance(value, bytes) or not value.startswith(b"\x89PNG\r\n\x1a\n"):
        raise NativeSingleStepCoordinatorError(
            "review_image_invalid", "grounded review image is invalid"
        )
    return bytes(value)


__all__ = ["NativeSingleStepCoordinator", "NativeSingleStepCoordinatorError"]
