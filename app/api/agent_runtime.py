from __future__ import annotations

from app.agent.action_semantics import READ_ONLY_REVIEW_ACTIONS, REVIEWED_SINGLE_STEP_ACTIONS
from app.agent.text_parameters import ResolvedTextParameters

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.agent.live_controller import (
    LiveController,
    LiveControllerDecision,
    ServerWorkflowBinding,
)
from app.agent.live_runtime_composition import build_existing_windows_live_controller
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from app.agent_link.contracts import AgentLinkError
from app.agent.native_identity import asset_application_identity_key
from app.agent.reviewed_workflow_asset import (
    ReviewedWorkflowAssetStore,
    content_sha256,
    validate_reviewed_workflow_asset,
)
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    WorkflowRefV1,
    validate_agent_intent_v1,
)
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimSnapshot,
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.models.response import APIResponse, ErrorModel
from app.core.window_manager import window_manager


router = APIRouter(prefix="/runtime/agent", tags=["agent-runtime"])


class AgentRuntimeStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AgentRuntimeIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent_id: str
    session_id: str
    observation_id: str
    action_id: str


class AgentRuntimeConfirmationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirmation_id: str
    decision: Literal["approved", "denied"]


class AgentRuntimeCallsiteError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retry_preparation: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_preparation = retry_preparation


@dataclass(frozen=True, slots=True)
class _DecisionProjection:
    status: str
    reason_code: str
    confirmation_id: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "confirmation_id": self.confirmation_id,
        }


@dataclass(frozen=True, slots=True)
class _ResolvedServerState:
    binding: ServerWorkflowBinding
    process_id: int
    workflow: WorkflowRefV1


from .grounded_recovery import GroundedRecoveryMixin


class LocalAgentRuntimeCallsite(GroundedRecoveryMixin):
    """本地单实例入口；客户端只选择服务器已暴露的动作。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        asset_store: Any,
        window_manager: Any,
        claim_store: Any,
        controller_factory: Callable[[ServerWorkflowBinding], LiveController] | None = None,
        selection: RuntimeSessionSelection | None = None,
        vision_configuration=None,
        learning_binding: LearningRuntimeBinding | None = None,
    ) -> None:
        if learning_binding is not None:
            if not isinstance(learning_binding, LearningRuntimeBinding):
                raise TypeError("learning_binding must be LearningRuntimeBinding or None")
            if learning_binding.project_root != Path(project_root).resolve():
                raise ValueError("learning_binding must use the callsite project root")
        if selection is not None and not isinstance(selection, RuntimeSessionSelection):
            raise TypeError("selection must be RuntimeSessionSelection or None")
        if vision_configuration is not None:
            from app.vision.configuration import VisionConfigurationSnapshot
            if not isinstance(vision_configuration, VisionConfigurationSnapshot):
                raise TypeError("vision_configuration must be VisionConfigurationSnapshot or None")
        self._project_root = Path(project_root).resolve()
        self._asset_store = asset_store
        self._window_manager = window_manager
        self._claim_store = claim_store
        self._selection = selection
        self._learning_binding = learning_binding
        if controller_factory is None:
            self._controller_factory = lambda binding: build_existing_windows_live_controller(
                self._project_root,
                binding,
                intent_claim_store=self._claim_store,
                **({"action_learning_recorder": learning_binding.recorder} if learning_binding is not None else {}),
                **({"vision_configuration": vision_configuration} if vision_configuration is not None else {}),
            )
        else:
            self._controller_factory = controller_factory
        self._lock = RLock()
        self._controller: LiveController | Any | None = None
        self._observation: AgentObservationV1 | None = None
        self._target_window_handle: int | None = None
        self._target_process_id: int | None = None
        self._confirmation_id: str | None = None
        self._pending_cleanup: tuple[Any, str] | None = None
        self._learning_cleanup: tuple[str, bool] | None = None
        self._cancelled_sessions: set[str] = set()
        self._preparation_owner: tuple[Any, str] | None = None
        self._preparation_cleanup_verified = False
        self._preparation_unknown = False
        self._grounded_intent: AgentIntentV1 | None = None
        self._grounded_confirmation_id: str | None = None
        self._grounded_cleanup: tuple[Any, str, str] | None = None
        self._grounded_cancelled_sessions: set[str] = set()
        self._grounded_recovery_id: str | None = None
        self._grounded_recovery_factory_unknown = False

    def start_session(self) -> AgentObservationV1:
        with self._lock:
            if self._grounded_recovery_id is not None:
                raise self._error(409, "grounded_recovery_owner_busy", "Complete recovery with the retained owner before starting a session.")
            self._retry_grounded_cleanup()
            self._retry_pending_cleanup()
            if self._observation is not None:
                raise self._error(
                    409,
                    "agent_runtime_session_active",
                    "An agent runtime session is already active.",
                )
            if self._preparation_owner is not None:
                self._cancel_managed_preparation()
            self._retry_learning_cleanup()
            if self._preparation_unknown:
                raise self._error(
                    503,
                    "agent_runtime_cleanup_required",
                    "The prior runtime preparation owner cannot be verified.",
                )
            self._preparation_cleanup_verified = False
            try:
                unresolved = self._claim_store.list_unresolved_claims()
            except RuntimeIntentClaimStoreError as exc:
                error = self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "Durable runtime state could not be verified.",
                    retry_preparation=True,
                )
                self._preparation_cleanup_verified = True
                raise error from exc
            if unresolved:
                error = self._error(
                    412,
                    "agent_runtime_unresolved_claim_exists",
                    "An unresolved durable runtime operation must be recovered first.",
                    retry_preparation=True,
                )
                self._preparation_cleanup_verified = True
                raise error
            try:
                resolved = self._resolve_server_binding()
            except AgentRuntimeCallsiteError as error:
                self._preparation_cleanup_verified = True
                error.retry_preparation = True
                raise
            controller: Any | None = None
            try:
                controller = self._controller_factory(resolved.binding)
                if self._learning_binding is not None:
                    inject = getattr(controller, "set_action_learning_recorder", None)
                    if not callable(inject):
                        raise TypeError("learning controller must retain action learning recorder")
                    inject(self._learning_binding.recorder)
                    if getattr(controller, "_action_learning_recorder", None) is not self._learning_binding.recorder:
                        raise TypeError("learning controller did not retain exact action learning recorder")
            except Exception as exc:
                self._preparation_unknown = True
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The runtime controller factory failed before ownership could be verified.",
                ) from exc
            managed_start = getattr(controller, "start_session_preparation", None)
            managed_cancel = getattr(controller, "cancel_session_preparation", None)
            managed = callable(managed_start) and callable(managed_cancel)
            if managed:
                preparation_id = "preparation." + uuid4().hex
                self._preparation_owner = (controller, preparation_id)
                try:
                    session = managed_start(preparation_id=preparation_id)
                except Exception as exc:
                    raise self._prepared_cleanup_error() from exc
            else:
                try:
                    session = controller.start_session()
                except Exception as exc:
                    self._preparation_unknown = True
                    raise self._error(
                        503,
                        "agent_runtime_recovery_required",
                        "The legacy runtime start outcome could not be verified.",
                    ) from exc
            try:
                post_start = self._resolve_server_binding()
            except AgentRuntimeCallsiteError:
                self._release_preparation_after_start(controller, session, managed=managed)
                raise
            try:
                observation = session.current_observation
                binding = resolved.binding
                valid = (
                    post_start == resolved
                    and isinstance(observation, AgentObservationV1)
                    and session.session_id == observation.session_id
                    and session.workflow == resolved.workflow
                    and session.target_window_handle == binding.target_window_handle
                    and observation.workflow == resolved.workflow
                    and observation.application.identity_ref
                    == f"application:{binding.application_identity_key}"
                )
            except Exception as exc:
                self._release_preparation_after_start(controller, session, managed=managed)
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The server observation shape could not be verified.",
                    retry_preparation=True,
                ) from exc
            if not valid:
                self._release_preparation_after_start(controller, session, managed=managed)
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The server observation binding could not be verified.",
                    retry_preparation=True,
                )
            if observation.safe_stop.required:
                try:
                    if managed:
                        self._cancel_managed_preparation()
                    else:
                        controller.close_initial_safe_stop(session_id=session.session_id)
                        self._preparation_cleanup_verified = True
                except Exception as exc:
                    if not managed:
                        self._pending_cleanup = (controller, session.session_id)
                    raise self._prepared_cleanup_error() from exc
                return observation
            if self._learning_binding is not None:
                try:
                    self._learning_binding.attach_validated_runtime(
                        runtime_session_id=session.session_id,
                    )
                except Exception as exc:
                    self._learning_cleanup = (session.session_id, True)
                    try:
                        self._release_preparation_after_start(controller, session, managed=managed)
                        self._retry_learning_cleanup()
                    except Exception as cleanup_exc:
                        raise self._prepared_cleanup_error() from cleanup_exc
                    raise self._error(
                        503, "agent_runtime_recovery_required",
                        "The learning runtime binding could not be verified.",
                        retry_preparation=True,
                    ) from exc
            self._controller = controller
            self._observation = observation
            self._target_window_handle = binding.target_window_handle
            self._target_process_id = resolved.process_id
            self._confirmation_id = None
            return observation

    def cancel_prepared_session(self, *, session_id: str) -> None:
        """仅取消本地入口拥有的无意图准备，不关闭持久确认。"""
        with self._lock:
            self._require_no_grounded_recovery()
            if not isinstance(session_id, str) or not session_id:
                raise self._error(409, "agent_runtime_invalid_session", "A prepared session identity is required.")
            pending = self._pending_cleanup
            if pending is not None:
                if pending[1] != session_id:
                    raise self._error(409, "agent_runtime_invalid_session", "The session is not owned by this callsite.")
                self._retry_pending_cleanup()
                self._cancelled_sessions.add(session_id)
                return
            if session_id in self._cancelled_sessions:
                return
            if self._learning_cleanup is not None and self._learning_cleanup[0] == session_id:
                self._retry_learning_cleanup()
                return
            if self._grounded_intent is not None:
                raise self._error(
                    409,
                    "agent_runtime_session_consumed",
                    "A grounded confirmation cannot be cancelled as preparation.",
                )
            observation = self._observation
            if observation is None or observation.session_id != session_id or self._controller is None:
                raise self._error(409, "agent_runtime_invalid_session", "The session is not owned by this callsite.")
            if self._confirmation_id is not None:
                raise self._error(409, "agent_runtime_session_consumed", "A durable operation cannot be cancelled as preparation.")
            try:
                claim = self._claim_store.find_for_observation(
                    session_id=session_id, observation_id=observation.observation_id,
                )
            except RuntimeIntentClaimStoreError as exc:
                self._pending_cleanup = (self._controller, session_id)
                raise self._prepared_cleanup_error() from exc
            if claim is not None:
                raise self._error(409, "agent_runtime_session_consumed", "A durable operation cannot be cancelled as preparation.")
            owner = self._preparation_owner
            if owner is not None and owner[0] is self._controller:
                self._cancel_managed_preparation()
            else:
                self._release_started_session(self._controller, session_id)
                self._preparation_cleanup_verified = True
            if self._learning_binding is not None:
                self._learning_cleanup = (session_id, False)
                self._retry_learning_cleanup()
            self._clear_active()
            self._cancelled_sessions.add(session_id)

    def cancel_local_preparation(self) -> dict[str, Any]:
        """核验并关闭本 callsite 的本地准备，不接收客户端自报身份。"""
        with self._lock:
            self._require_no_grounded_recovery()
            selection = self._selection
            if selection is None:
                raise self._error(
                    409,
                    "agent_runtime_selection_required",
                    "An exact local session selection is required for preparation cleanup.",
                )
            if (
                self._grounded_intent is not None
                or self._grounded_confirmation_id is not None
                or self._confirmation_id is not None
            ):
                raise self._error(
                    409,
                    "agent_runtime_session_consumed",
                    "A durable operation cannot be cancelled as local preparation.",
                )
            if self._pending_cleanup is not None:
                self._retry_pending_cleanup()
                self._preparation_cleanup_verified = True
            if self._observation is not None:
                # 已发布观察必须先核验无意图并关闭学习记录，不能走托管准备捷径。
                self.cancel_prepared_session(session_id=self._observation.session_id)
            elif self._preparation_owner is not None:
                self._cancel_managed_preparation()
                self._clear_active()
            elif self._preparation_unknown:
                raise self._error(
                    503,
                    "agent_runtime_cleanup_required",
                    "The local preparation owner cannot be verified.",
                )
            elif not self._preparation_cleanup_verified:
                raise self._error(
                    409,
                    "agent_runtime_no_local_preparation",
                    "No verifiable local preparation is available for cleanup.",
                )
            self._retry_learning_cleanup()
            return {
                "contract_version": "local_preparation_cleanup_v1",
                "selection": {
                    "asset_id": selection.asset_id,
                    "asset_content_sha256": selection.asset_content_sha256,
                    "target_window_handle": selection.target_window_handle,
                    "target_process_id": selection.target_process_id,
                },
                "cleanup_verified": True,
                "artifact_is_authorization": False,
            }

    def submit_intent(
        self,
        request: AgentRuntimeIntentRequest,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        with self._lock:
            self._require_no_grounded_recovery()
            if self._grounded_intent is not None:
                return _DecisionProjection(
                    "RECOVERY_REQUIRED",
                    "grounded_confirmation_active",
                    self._grounded_confirmation_id,
                )
            if self._observation is not None:
                intent = self._active_intent(request)
                self._verify_active_window()
                controller = self._controller
            else:
                claim = self._find_exact_claim(request)
                grounded = getattr(claim, "grounded_confirmation", None)
                if grounded is not None:
                    return _DecisionProjection(
                        "RECOVERY_REQUIRED",
                        "grounded_confirmation_owner_unavailable",
                        grounded.confirmation_id,
                    )
                if claim.phase == "terminal":
                    return self._load_terminal_receipt(claim)
                intent = claim.intent
                controller = self._controller_for_claim(claim)
            try:
                result = controller.submit_intent(intent.model_dump(mode="json"))
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The controller could not process the persisted intent safely.",
                ) from exc
            return self._project_controller_result(result)

    def prepare_grounded_review(self, request: AgentRuntimeIntentRequest) -> "GroundedActionPreview | _DecisionProjection":
        """本地只读预览入口；不接受坐标、批准或新HTTP权限。"""
        from app.agent.grounded_action_preview import GroundedActionPreview

        with self._lock:
            self._require_no_grounded_recovery()
            if self._selection is None:
                raise self._error(412, "agent_runtime_selection_required", "An exact local session selection is required.")
            if self._pending_cleanup is not None:
                raise self._prepared_cleanup_error()
            if self._grounded_intent is not None:
                raise self._error(
                    409,
                    "agent_runtime_grounded_confirmation_active",
                    "A grounded confirmation is already active.",
                )
            intent = self._active_intent(request, review_only=True)
            observation = self._observation
            if self._controller is None or self._confirmation_id is not None:
                raise self._error(409, "agent_runtime_session_consumed", "Only an unconsumed prepared session can be previewed.")
            self._verify_grounded_preview_binding(observation)
            try:
                result = self._controller.prepare_grounded_review(
                    intent.model_dump(mode="json"), target_process_id=self._target_process_id,
                )
            except Exception as exc:
                raise self._error(503, "agent_runtime_preview_failed", "The grounded preview could not be prepared safely.") from exc
            self._verify_grounded_preview_binding(observation)
            if isinstance(result, LiveControllerDecision):
                if result.status not in {"REJECTED", "RECOVERY_REQUIRED"} or result.confirmation_id is not None:
                    raise self._error(503, "agent_runtime_preview_invalid", "The preview returned an invalid decision.")
                return _DecisionProjection(result.status, result.reason_code, None)
            if not isinstance(result, GroundedActionPreview):
                raise self._error(503, "agent_runtime_preview_invalid", "The preview result could not be verified.")
            payload = result.to_dict()
            if any(payload.get(key) != value for key, value in {
                "session_id": observation.session_id, "observation_id": observation.observation_id,
                "intent_id": intent.intent_id, "workflow": observation.workflow.model_dump(mode="json"),
                "target_window_handle": self._target_window_handle, "target_process_id": self._target_process_id,
            }.items()):
                raise self._error(503, "agent_runtime_preview_invalid", "The grounded preview identity does not match the session.")
            if payload["review_selection"].get("transition_id") != intent.action_id:
                raise self._error(503, "agent_runtime_preview_invalid", "The grounded preview action does not match the intent.")
            return result

    def request_grounded_confirmation(
        self,
        request: AgentRuntimeIntentRequest,
        *,
        text_input: ResolvedTextParameters | None = None,
    ) -> RuntimeIntentClaimSnapshot | _DecisionProjection:
        """发布服务器定位预览到同一持久 store，仍不产生执行权限。"""
        with self._lock:
            self._require_no_grounded_recovery()
            self._require_exact_selection()
            if self._pending_cleanup is not None:
                raise self._prepared_cleanup_error()
            if self._grounded_cleanup is not None:
                raise self._grounded_cleanup_error()
            intent = self._active_intent(request, review_only=True)
            observation = self._observation
            controller = self._controller
            if observation is None or controller is None or self._confirmation_id is not None:
                raise self._error(
                    409,
                    "agent_runtime_session_consumed",
                    "Only an unconsumed prepared session can request grounded confirmation.",
                )
            retrying_grounded_publication = self._grounded_intent is not None
            if retrying_grounded_publication and self._grounded_intent != intent:
                raise self._error(
                    409,
                    "agent_runtime_grounded_request_conflict",
                    "The active grounded request has a different intent.",
                )
            self._grounded_intent = intent
            try:
                self._assert_grounded_live_binding(observation)
            except AgentRuntimeCallsiteError:
                if retrying_grounded_publication:
                    self._close_local_grounded_stale(controller, observation)
                else:
                    # 首次调用 controller 前，不存在发布上下文或持久事实。
                    self._grounded_intent = None
                raise
            try:
                result = controller.request_grounded_confirmation(
                    intent.model_dump(mode="json"),
                    target_process_id=self._target_process_id,
                    **({"text_input": text_input} if text_input is not None else {}),
                )
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_grounded_publication_failed",
                    "The grounded confirmation could not be published safely.",
                ) from exc
            if isinstance(result, LiveControllerDecision):
                if (
                    result.status not in {"REJECTED", "RECOVERY_REQUIRED"}
                    or result.confirmation_id is not None
                ):
                    raise self._error(
                        503,
                        "agent_runtime_grounded_publication_invalid",
                        "The grounded publication returned an invalid decision.",
                    )
                if (
                    (not retrying_grounded_publication or result.status != "REJECTED")
                    and (result.status == "REJECTED" or result.reason_code
                    not in {
                        "grounded_confirmation_persistence_failed",
                        "grounded_confirmation_integrity_failed",
                        "grounded_confirmation_cleanup_required",
                    })
                ):
                    self._grounded_intent = None
                if result.reason_code == "grounded_confirmation_cleanup_required":
                    self._grounded_cleanup = (
                        controller,
                        observation.session_id,
                        "grounded_confirmation_cancelled",
                    )
                return _DecisionProjection(result.status, result.reason_code, None)
            claim = self._reload_grounded_snapshot(
                result,
                intent=intent,
                require_current_owner=True,
            )
            grounded = claim.grounded_confirmation
            self._grounded_confirmation_id = grounded.confirmation_id
            if claim.phase in {
                "grounded_confirmation_denied",
                "grounded_confirmation_closed",
            }:
                self._grounded_cancelled_sessions.add(observation.session_id)
                self._clear_active()
                return claim
            try:
                self._assert_grounded_live_binding(observation)
            except AgentRuntimeCallsiteError:
                self._close_local_grounded_stale(controller, observation)
                raise
            return claim

    def decide_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
        decision: Literal["approved", "denied"],
    ) -> RuntimeIntentClaimSnapshot | _DecisionProjection:
        """独立记录 grounded 决定；本阶段批准也不执行。"""
        with self._lock:
            self._require_no_grounded_recovery()
            self._require_exact_selection()
            claim = self._load_grounded_by_confirmation(confirmation_id)
            grounded = claim.grounded_confirmation
            if decision not in {"approved", "denied"}:
                raise self._error(
                    409,
                    "agent_runtime_grounded_decision_invalid",
                    "The grounded confirmation decision is invalid.",
                )
            if grounded.decision is not None and grounded.decision != decision:
                raise self._error(
                    409,
                    "agent_runtime_decision_conflict",
                    "The grounded confirmation already has a different decision.",
                )
            local = self._local_grounded_owner(claim)
            if decision == "approved" and grounded.owner_is_current and local is None:
                raise self._error(
                    503,
                    "agent_runtime_grounded_owner_unavailable",
                    "The live grounded confirmation owner is unavailable.",
                )
            if local is None:
                try:
                    result = self._claim_store.record_grounded_confirmation_decision(
                        confirmation_id=confirmation_id,
                        decision=decision,
                    )
                except RuntimeIntentClaimStoreError as exc:
                    raise self._grounded_store_error(exc)
                return self._reload_grounded_snapshot(result)
            controller, observation = local
            if decision == "approved":
                try:
                    self._assert_grounded_live_binding(observation)
                except AgentRuntimeCallsiteError:
                    self._close_local_grounded_stale(controller, observation)
                    raise
            try:
                result = controller.record_grounded_confirmation_decision(
                    confirmation_id=confirmation_id,
                    decision=decision,
                )
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The grounded decision could not be recorded safely.",
                ) from exc
            if isinstance(result, LiveControllerDecision):
                if result.reason_code == "grounded_confirmation_decision_conflict":
                    raise self._error(
                        409,
                        "agent_runtime_decision_conflict",
                        "The grounded confirmation already has a different decision.",
                    )
                if result.reason_code == "grounded_confirmation_cleanup_required":
                    self._grounded_cleanup = (
                        controller,
                        observation.session_id,
                        "grounded_confirmation_cancelled",
                    )
                return _DecisionProjection(
                    result.status, result.reason_code, result.confirmation_id
                )
            verified = self._reload_grounded_snapshot(result)
            if decision == "approved" and verified.phase == "grounded_confirmation_approved":
                try:
                    self._assert_grounded_live_binding(observation)
                except AgentRuntimeCallsiteError:
                    self._close_local_grounded_stale(controller, observation)
                    raise
            if verified.phase in {
                "grounded_confirmation_denied",
                "grounded_confirmation_closed",
            }:
                self._grounded_cancelled_sessions.add(observation.session_id)
                self._clear_active()
            return verified

    def consume_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        """仅由当前显式选择的本地 owner 消费 grounded 批准。"""
        with self._lock:
            self._require_no_grounded_recovery()
            pending_cleanup = self._grounded_cleanup
            if (
                pending_cleanup is not None
                and pending_cleanup[2] == f"consume:{confirmation_id}"
            ):
                self._retry_grounded_cleanup()
            self._require_exact_selection()
            claim = self._load_grounded_by_confirmation(confirmation_id)
            if claim.phase == "terminal":
                try:
                    receipt = self._claim_store.load_terminal_receipt(
                        session_id=claim.observation.session_id,
                        observation_id=claim.observation.observation_id,
                    )
                except RuntimeIntentClaimStoreError as exc:
                    raise self._grounded_store_error(exc)
                local = self._local_grounded_owner(claim)
                if local is not None:
                    self._grounded_cancelled_sessions.add(
                        claim.observation.session_id
                    )
                    self._clear_active()
                return receipt
            local = self._local_grounded_owner(claim)
            if local is None:
                return _DecisionProjection(
                    "RECOVERY_REQUIRED",
                    "grounded_confirmation_owner_unavailable",
                    confirmation_id,
                )
            controller, observation = local
            try:
                self._assert_grounded_live_binding(observation)
                result = controller.consume_grounded_confirmation(
                    confirmation_id=confirmation_id
                )
            except AgentRuntimeCallsiteError:
                self._close_local_grounded_stale(controller, observation)
                raise
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The grounded confirmation could not be consumed safely.",
                ) from exc
            if isinstance(result, LiveControllerDecision):
                if result.reason_code == "grounded_confirmation_cleanup_required":
                    self._grounded_cleanup = (
                        controller,
                        observation.session_id,
                        f"consume:{confirmation_id}",
                    )
                if result.reason_code == "grounded_confirmation_stale":
                    self._grounded_cancelled_sessions.add(observation.session_id)
                    self._clear_active()
                return _DecisionProjection(
                    result.status, result.reason_code, result.confirmation_id
                )
            if not isinstance(result, RuntimeResultReceiptV1):
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The grounded consume result is invalid.",
                )
            try:
                verified = self._claim_store.load_terminal_receipt(
                    session_id=claim.observation.session_id,
                    observation_id=claim.observation.observation_id,
                )
            except RuntimeIntentClaimStoreError as exc:
                raise self._grounded_store_error(exc)
            if verified != result:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The grounded consume receipt could not be verified.",
                )
            self._grounded_cancelled_sessions.add(observation.session_id)
            self._clear_active()
            return verified

    def get_local_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        """只读返回当前 callsite 确切持有的 grounded confirmation。"""
        with self._lock:
            self._require_exact_selection()
            if self._pending_cleanup is not None or self._grounded_cleanup is not None:
                raise self._error(
                    409,
                    "agent_runtime_cleanup_pending",
                    "The current runtime owner still has pending cleanup.",
                )
            claim = self._load_grounded_by_confirmation(confirmation_id)
            if claim.phase not in {
                "grounded_confirmation_pending",
                "grounded_confirmation_approved",
            }:
                raise self._error(
                    409,
                    "agent_runtime_grounded_confirmation_unavailable",
                    "The grounded confirmation is not attachable.",
                )
            local = self._local_grounded_owner(claim)
            if local is None:
                raise self._error(
                    409,
                    "agent_runtime_grounded_confirmation_owner_unavailable",
                    "The grounded confirmation is not owned by this callsite.",
                )
            _controller, observation = local
            # 读取已固定的预览时审核窗口可以在前台；身份与资产仍须一致。
            self._assert_grounded_live_binding(observation, require_active=False)
            return claim

    def get_local_reviewed_text_parameters(self, *, action_id: str):
        """本地界面专用原值入口，不增加 HTTP/Agent 工具字段。"""
        from app.agent.text_parameters import ReviewedTextParameters, text_parameter_reference
        with self._lock:
            self._require_exact_selection()
            observation, controller = self._observation, self._controller
            if observation is None or controller is None or self._grounded_intent is not None:
                raise self._error(409, "agent_runtime_text_input_unavailable", "No unconsumed local text action is available.")
            self._assert_grounded_live_binding(observation)
            action = next((item for item in observation.available_actions if item.action_id == action_id), None)
            if action is None or action.semantic_action != "fill_field":
                raise self._error(409, "agent_runtime_text_input_unavailable", "No local text action matches.")
            reviewed = controller.get_local_reviewed_text_parameters(session_id=observation.session_id, action_id=action_id)
            if type(reviewed) is not ReviewedTextParameters or text_parameter_reference(reviewed) != action.text_parameters_ref:
                raise self._error(409, "agent_runtime_text_input_invalid", "The text declaration no longer matches.")
            return reviewed

    def get_local_grounded_text_input(self, *, confirmation_id: str):
        from app.agent.text_execution import validate_local_text_preview
        with self._lock:
            claim = self.get_local_grounded_confirmation(confirmation_id=confirmation_id)
            local = self._local_grounded_owner(claim)
            if local is None:
                raise self._error(409, "agent_runtime_text_input_unavailable", "The text preview owner is unavailable.")
            resolved = local[0].get_local_grounded_text_input(confirmation_id=confirmation_id)
            validate_local_text_preview(claim.grounded_confirmation.preview.to_dict(), resolved)
            return resolved

    def get_local_grounded_text_field_expectation(self, *, confirmation_id: str):
        from app.agent.text_field_evidence import TextFieldExpectation
        with self._lock:
            claim = self.get_local_grounded_confirmation(confirmation_id=confirmation_id)
            local = self._local_grounded_owner(claim)
            if local is None:
                raise self._error(409, "agent_runtime_text_input_unavailable", "The text preview owner is unavailable.")
            expected = local[0].get_local_grounded_text_field_expectation(confirmation_id=confirmation_id)
            if (type(expected) is not TextFieldExpectation
                    or expected.to_reference() != claim.grounded_confirmation.preview.to_dict().get("text_field_expectation_ref")):
                raise self._error(409, "agent_runtime_text_input_invalid", "The field expectation no longer matches.")
            return expected

    def get_local_grounded_image(self, *, confirmation_id: str) -> bytes:
        """只读返回当前本地 owner 的 grounded 预览 PNG。"""
        with self._lock:
            claim = self.get_local_grounded_confirmation(
                confirmation_id=confirmation_id,
            )
            grounded = claim.grounded_confirmation
            local = self._local_grounded_owner(claim)
            if grounded is None or grounded.owner_is_current is not True or local is None:
                raise self._error(
                    409,
                    "agent_runtime_grounded_confirmation_owner_unavailable",
                    "The grounded confirmation is not owned by this callsite.",
                )
            controller, _observation = local
            reader = getattr(controller, "get_local_grounded_image", None)
            if not callable(reader):
                raise self._error(
                    503,
                    "agent_runtime_grounded_image_unavailable",
                    "The grounded preview image is unavailable.",
                )
            try:
                image_bytes = reader(confirmation_id=confirmation_id)
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_grounded_image_unavailable",
                    "The grounded preview image could not be verified.",
                ) from exc
            if type(image_bytes) is not bytes or not image_bytes:
                raise self._error(
                    503,
                    "agent_runtime_grounded_image_unavailable",
                    "The grounded preview image is invalid.",
                )
            verified = self.get_local_grounded_confirmation(
                confirmation_id=confirmation_id,
            )
            if verified != claim:
                raise self._error(
                    503,
                    "agent_runtime_grounded_image_unavailable",
                    "The grounded preview image binding changed while it was read.",
                )
            return bytes(image_bytes)

    def cancel_grounded_review(
        self,
        *,
        session_id: str,
    ) -> RuntimeIntentClaimSnapshot | _DecisionProjection | None:
        with self._lock:
            self._require_no_grounded_recovery()
            self._require_exact_selection()
            if session_id in self._grounded_cancelled_sessions:
                return None
            observation = self._observation
            controller = self._controller
            if (
                not isinstance(session_id, str)
                or not session_id
                or observation is None
                or observation.session_id != session_id
                or controller is None
                or self._grounded_intent is None
            ):
                raise self._error(
                    409,
                    "agent_runtime_invalid_session",
                    "The grounded session is not owned by this callsite.",
                )
            try:
                result = controller.cancel_grounded_review(session_id=session_id)
            except Exception as exc:
                self._grounded_cleanup = (
                    controller,
                    session_id,
                    "grounded_confirmation_cancelled",
                )
                raise self._grounded_cleanup_error() from exc
            if isinstance(result, LiveControllerDecision):
                self._grounded_cleanup = (
                    controller,
                    session_id,
                    "grounded_confirmation_cancelled",
                )
                return _DecisionProjection(
                    result.status, result.reason_code, result.confirmation_id
                )
            verified = self._reload_grounded_snapshot(result) if result is not None else None
            self._grounded_cancelled_sessions.add(session_id)
            self._clear_active()
            return verified

    def close_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeIntentClaimSnapshot | _DecisionProjection:
        with self._lock:
            self._require_no_grounded_recovery()
            self._require_exact_selection()
            claim = self._load_grounded_by_confirmation(confirmation_id)
            local = self._local_grounded_owner(claim)
            if local is None:
                try:
                    closed = self._claim_store.close_grounded_confirmation(
                        confirmation_id=confirmation_id,
                        reason_code="grounded_confirmation_cancelled",
                    )
                except RuntimeIntentClaimStoreError as exc:
                    raise self._grounded_store_error(exc)
                return self._reload_grounded_snapshot(closed)
            _controller, observation = local
            result = self.cancel_grounded_review(session_id=observation.session_id)
            if result is None:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The grounded close record could not be verified.",
                )
            return result

    def _active_intent(self, request: AgentRuntimeIntentRequest, *, review_only: bool = False):
        observation = self._observation
        if not isinstance(request, AgentRuntimeIntentRequest) or observation is None:
            raise self._error(409, "agent_runtime_invalid_intent", "The intent requires an active server observation.")
        selected_action = next((action for action in observation.available_actions if action.action_id == request.action_id), None)
        if (
            request.session_id != observation.session_id or request.observation_id != observation.observation_id
            or selected_action is None or selected_action.semantic_action not in (READ_ONLY_REVIEW_ACTIONS if review_only else REVIEWED_SINGLE_STEP_ACTIONS)
        ):
            raise self._error(409, "agent_runtime_invalid_intent", "The intent does not match the active server observation.")
        try:
            return validate_agent_intent_v1({
                "contract_version": "agent_intent_v1", "intent_id": request.intent_id,
                "session_id": request.session_id, "observation_id": request.observation_id,
                "workflow": observation.workflow.model_dump(mode="json"), "action_id": request.action_id,
            }, observation=observation)
        except (TypeError, ValueError) as exc:
            raise self._error(409, "agent_runtime_invalid_intent", "The intent does not match the active server observation.") from exc

    def _verify_grounded_preview_binding(self, observation: AgentObservationV1) -> None:
        try:
            resolved = self._resolve_server_binding()
            if (
                resolved.workflow != observation.workflow
                or resolved.binding.target_window_handle != self._target_window_handle
                or resolved.process_id != self._target_process_id
            ):
                raise self._error(412, "agent_runtime_binding_mismatch", "The grounded preview binding has changed.")
        except AgentRuntimeCallsiteError:
            self.cancel_prepared_session(session_id=observation.session_id)
            raise

    def _require_exact_selection(self) -> RuntimeSessionSelection:
        if self._selection is None:
            raise self._error(
                412,
                "agent_runtime_selection_required",
                "An exact local session selection is required.",
            )
        return self._selection

    def _assert_grounded_live_binding(self, observation: AgentObservationV1, *, require_active: bool = True) -> None:
        resolved = self._resolve_server_binding(require_active=require_active)
        if (
            resolved.workflow != observation.workflow
            or resolved.binding.target_window_handle != self._target_window_handle
            or resolved.process_id != self._target_process_id
        ):
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The grounded confirmation binding has changed.",
            )

    def _reload_grounded_snapshot(
        self,
        claim: RuntimeIntentClaimSnapshot,
        *,
        intent: AgentIntentV1 | None = None,
        require_current_owner: bool = False,
    ) -> RuntimeIntentClaimSnapshot:
        if not isinstance(claim, RuntimeIntentClaimSnapshot):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The grounded confirmation snapshot is invalid.",
            )
        grounded = claim.grounded_confirmation
        if grounded is None:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The grounded confirmation snapshot is missing.",
            )
        try:
            reloaded = self._claim_store.get_for_grounded_confirmation(
                confirmation_id=grounded.confirmation_id,
            )
        except RuntimeIntentClaimStoreError as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The grounded confirmation could not be reloaded safely.",
            ) from exc
        current = reloaded.grounded_confirmation
        selection = self._require_exact_selection()
        preview = current.preview.to_dict() if current is not None else None
        if (
            reloaded != claim
            or current is None
            or (intent is not None and reloaded.intent != intent)
            or (require_current_owner and current.owner_is_current is not True)
            or reloaded.observation.workflow.asset_id != selection.asset_id
            or reloaded.observation.workflow.asset_content_sha256
            != selection.asset_content_sha256
            or reloaded.server_binding.target_window_handle
            != selection.target_window_handle
            or preview["target_window_handle"] != selection.target_window_handle
            or preview["target_process_id"] != selection.target_process_id
            or preview["session_id"] != reloaded.observation.session_id
            or preview["observation_id"] != reloaded.observation.observation_id
            or preview["intent_id"] != reloaded.intent.intent_id
            or preview["review_selection"].get("transition_id")
            != reloaded.intent.action_id
        ):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The grounded confirmation identity could not be verified.",
            )
        return reloaded

    def _load_grounded_by_confirmation(
        self,
        confirmation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        try:
            claim = self._claim_store.get_for_grounded_confirmation(
                confirmation_id=confirmation_id,
            )
        except RuntimeIntentClaimStoreError as exc:
            raise self._error(
                412,
                "agent_runtime_grounded_confirmation_invalid",
                "The grounded confirmation record could not be verified.",
            ) from exc
        return self._reload_grounded_snapshot(claim)

    def _local_grounded_owner(
        self,
        claim: RuntimeIntentClaimSnapshot,
    ) -> tuple[Any, AgentObservationV1] | None:
        observation = self._observation
        grounded = claim.grounded_confirmation
        if (
            self._controller is None
            or observation is None
            or self._grounded_intent != claim.intent
            or grounded is None
            or self._grounded_confirmation_id != grounded.confirmation_id
            or observation.session_id != claim.observation.session_id
            or observation.observation_id != claim.observation.observation_id
        ):
            return None
        return self._controller, observation

    def _close_local_grounded_stale(
        self,
        controller: Any,
        observation: AgentObservationV1,
    ) -> RuntimeIntentClaimSnapshot:
        pending = (
            controller,
            observation.session_id,
            "grounded_confirmation_stale",
        )
        try:
            result = controller.cancel_grounded_review(
                session_id=observation.session_id,
                reason_code="grounded_confirmation_stale",
            )
        except Exception as exc:
            self._grounded_cleanup = pending
            raise self._grounded_cleanup_error() from exc
        if isinstance(result, LiveControllerDecision) or result is None:
            self._grounded_cleanup = pending
            raise self._grounded_cleanup_error()
        verified = self._reload_grounded_snapshot(result)
        grounded = verified.grounded_confirmation
        if (
            verified.phase != "grounded_confirmation_closed"
            or grounded is None
            or grounded.closed_reason_code != "grounded_confirmation_stale"
        ):
            self._grounded_cleanup = pending
            raise self._grounded_cleanup_error()
        self._grounded_cancelled_sessions.add(observation.session_id)
        self._clear_active()
        return verified

    def _grounded_store_error(
        self,
        exc: RuntimeIntentClaimStoreError,
    ) -> AgentRuntimeCallsiteError:
        if "conflict" in str(exc):
            return self._error(
                409,
                "agent_runtime_decision_conflict",
                "The grounded confirmation has a conflicting durable fact.",
            )
        return self._error(
            503,
            "agent_runtime_recovery_required",
            "The grounded confirmation could not be updated safely.",
        )

    def decide_confirmation(
        self,
        request: AgentRuntimeConfirmationDecisionRequest,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        with self._lock:
            self._require_no_grounded_recovery()
            if self._grounded_intent is not None:
                raise self._error(
                    409,
                    "agent_runtime_grounded_confirmation_active",
                    "A grounded confirmation cannot use the legacy decision path.",
                )
            try:
                claim = self._claim_store.get_for_confirmation(
                    confirmation_id=request.confirmation_id
                )
            except RuntimeIntentClaimStoreError as exc:
                raise self._error(
                    412,
                    "agent_runtime_confirmation_invalid",
                    "The confirmation record could not be verified.",
                ) from exc
            confirmation = claim.confirmation
            if confirmation is None:
                raise self._error(
                    412,
                    "agent_runtime_confirmation_invalid",
                    "The confirmation record could not be verified.",
                )
            if (
                confirmation.decision is not None
                and confirmation.decision != request.decision
            ):
                raise self._error(
                    409,
                    "agent_runtime_decision_conflict",
                    "The confirmation already has a different decision.",
                )
            if request.decision == "approved":
                self._require_portfolio_claim_action(claim)
            if claim.phase == "terminal":
                if confirmation.decision != "approved":
                    raise self._error(
                        503,
                        "agent_runtime_recovery_required",
                        "The terminal confirmation lineage could not be verified.",
                    )
                return self._load_terminal_receipt(claim)
            if confirmation.decision == "denied":
                self._clear_active()
                return _DecisionProjection(
                    "REJECTED",
                    "confirmation_denied",
                    request.confirmation_id,
                )
            if claim.phase == "confirmation_closed":
                self._clear_active()
                return _DecisionProjection(
                    "REJECTED",
                    confirmation.closed_reason_code or "confirmation_stale",
                    request.confirmation_id,
                )
            if claim.phase in {"confirmation_resume_started", "dispatch_started"}:
                return _DecisionProjection(
                    "RECOVERY_REQUIRED",
                    (
                        "confirmation_resume_indeterminate"
                        if claim.phase == "confirmation_resume_started"
                        else "dispatch_indeterminate"
                    ),
                    request.confirmation_id,
                )
            if request.decision == "denied" and claim.phase == "confirmation_pending":
                return self._record_denial_without_dispatch(request)
            controller = self._controller_for_claim(claim)
            try:
                decision = controller.record_confirmation_decision(
                    confirmation_id=request.confirmation_id,
                    decision=request.decision,
                )
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The confirmation decision could not be recorded safely.",
                ) from exc
            if decision.reason_code == "confirmation_decision_conflict":
                raise self._error(
                    409,
                    "agent_runtime_decision_conflict",
                    "The confirmation already has a different decision.",
                )
            if decision.status != "APPROVED":
                projected = self._project_controller_result(decision)
                if decision.reason_code in {
                    "confirmation_denied",
                    "confirmation_expired",
                    "confirmation_stale",
                }:
                    self._clear_active()
                return projected
            try:
                approved = self._claim_store.get_for_confirmation(
                    confirmation_id=request.confirmation_id
                )
            except RuntimeIntentClaimStoreError as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The approved confirmation could not be reloaded safely.",
                ) from exc
            confirmation = approved.confirmation
            if confirmation is None or confirmation.decision != "approved":
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The approved confirmation could not be verified.",
                )
            try:
                result = controller.submit_intent(
                    approved.intent.model_dump(mode="json")
                )
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The approved intent could not be resumed safely.",
                ) from exc
            return self._project_controller_result(result)

    def _find_exact_claim(
        self,
        request: AgentRuntimeIntentRequest,
    ) -> RuntimeIntentClaimSnapshot | Any:
        try:
            claim = self._claim_store.find_for_observation(
                session_id=request.session_id,
                observation_id=request.observation_id,
            )
        except RuntimeIntentClaimStoreError as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "Durable runtime state could not be verified.",
            ) from exc
        if (
            claim is None
            or request.intent_id != claim.intent.intent_id
            or request.action_id != claim.intent.action_id
        ):
            raise self._error(
                409,
                "agent_runtime_invalid_intent",
                "The intent does not match server-owned durable state.",
            )
        self._require_portfolio_claim_action(claim)
        return claim

    def _require_portfolio_claim_action(
        self,
        claim: RuntimeIntentClaimSnapshot | Any,
    ) -> None:
        observation = claim.observation
        intent = claim.intent
        action = next(
            (
                candidate
                for candidate in observation.available_actions
                if candidate.action_id == intent.action_id
            ),
            None,
        )
        if (
            intent.session_id != observation.session_id
            or intent.observation_id != observation.observation_id
            or intent.workflow != observation.workflow
            or action is None
            or action.action_id != intent.action_id
            or action.semantic_action not in REVIEWED_SINGLE_STEP_ACTIONS
        ):
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The durable operation action no longer matches the reviewed transition.",
            )

    def _load_terminal_receipt(
        self,
        claim: RuntimeIntentClaimSnapshot | Any,
    ) -> RuntimeResultReceiptV1:
        try:
            receipt = self._claim_store.load_terminal_receipt(
                session_id=claim.observation.session_id,
                observation_id=claim.observation.observation_id,
            )
        except RuntimeIntentClaimStoreError as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The terminal receipt could not be verified.",
            ) from exc
        if not isinstance(receipt, RuntimeResultReceiptV1):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The terminal receipt could not be verified.",
            )
        self._clear_active()
        return receipt

    def _record_denial_without_dispatch(
        self,
        request: AgentRuntimeConfirmationDecisionRequest,
    ) -> _DecisionProjection:
        try:
            denied = self._claim_store.record_confirmation_decision(
                confirmation_id=request.confirmation_id,
                decision="denied",
            )
        except RuntimeIntentClaimStoreError as exc:
            message = str(exc)
            if "decision conflict" in message:
                raise self._error(
                    409,
                    "agent_runtime_decision_conflict",
                    "The confirmation already has a different decision.",
                ) from exc
            if "confirmation expired" in message:
                try:
                    closed = self._claim_store.get_for_confirmation(
                        confirmation_id=request.confirmation_id
                    )
                except RuntimeIntentClaimStoreError as reload_exc:
                    raise self._error(
                        503,
                        "agent_runtime_recovery_required",
                        "The expired confirmation could not be verified.",
                    ) from reload_exc
                closed_confirmation = closed.confirmation
                if (
                    closed.phase != "confirmation_closed"
                    or closed_confirmation is None
                    or closed_confirmation.closed_reason_code != "confirmation_expired"
                ):
                    raise self._error(
                        503,
                        "agent_runtime_recovery_required",
                        "The expired confirmation could not be verified.",
                    ) from exc
                self._clear_active()
                return _DecisionProjection(
                    "REJECTED",
                    "confirmation_expired",
                    request.confirmation_id,
                )
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The confirmation denial could not be persisted safely.",
            ) from exc
        denied_confirmation = denied.confirmation
        if (
            denied.phase == "confirmation_closed"
            and denied_confirmation is not None
            and denied_confirmation.confirmation_id == request.confirmation_id
            and denied_confirmation.closed_reason_code == "confirmation_expired"
        ):
            self._clear_active()
            return _DecisionProjection(
                "REJECTED",
                "confirmation_expired",
                request.confirmation_id,
            )
        if (
            denied.phase != "confirmation_denied"
            or denied_confirmation is None
            or denied_confirmation.confirmation_id != request.confirmation_id
            or denied_confirmation.decision != "denied"
        ):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The confirmation denial could not be verified.",
            )
        self._clear_active()
        return _DecisionProjection(
            "REJECTED",
            "confirmation_denied",
            request.confirmation_id,
        )

    def _controller_for_claim(self, claim: RuntimeIntentClaimSnapshot | Any):
        resolved = self._resolve_server_binding()
        binding = resolved.binding
        process_id = resolved.process_id
        if claim.server_binding.to_dict() != {
            "workflow_id": binding.workflow_id,
            "asset_id": binding.asset_id,
            "application_identity_key": binding.application_identity_key,
            "target_window_handle": binding.target_window_handle,
        }:
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The durable operation no longer matches the server binding.",
            )
        if claim.observation.workflow != resolved.workflow:
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The durable operation no longer matches the active reviewed asset.",
            )
        confirmation = claim.confirmation
        if (
            confirmation is not None
            and confirmation.target_process_id != process_id
        ):
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The durable operation no longer matches the bound process.",
            )
        if (
            self._controller is not None
            and self._observation is not None
            and self._observation.session_id == claim.observation.session_id
        ):
            self._target_process_id = process_id
            return self._controller
        try:
            controller = self._controller_factory(binding)
        except Exception as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The durable operation controller could not be restored.",
            ) from exc
        self._controller = controller
        self._observation = claim.observation
        self._target_window_handle = binding.target_window_handle
        self._target_process_id = process_id
        self._confirmation_id = (
            confirmation.confirmation_id if confirmation is not None else None
        )
        return controller

    def _resolve_server_binding(self, *, require_active: bool = True) -> _ResolvedServerState:
        try:
            registry = self._asset_store.registry()
            active = registry.get("active_by_asset")
        except Exception as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The reviewed asset registry could not be verified.",
            ) from exc
        if not isinstance(active, Mapping):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The reviewed asset registry could not be verified.",
            )
        if len(active) == 0:
            raise self._error(
                412,
                "agent_runtime_no_active_asset",
                "No active reviewed workflow asset is available.",
            )
        selection = self._selection
        if selection is None:
            if len(active) != 1:
                raise self._error(
                    412,
                    "agent_runtime_active_asset_ambiguous",
                    "Exactly one active reviewed workflow asset is required.",
                )
            asset_id, object_sha = next(iter(active.items()))
        else:
            asset_id = selection.asset_id
            object_sha = active.get(asset_id)
            if object_sha is None:
                raise self._error(
                    412,
                    "agent_runtime_selected_asset_inactive",
                    "The selected reviewed workflow asset is not active.",
                )
            if object_sha != selection.asset_content_sha256:
                raise self._error(
                    412,
                    "agent_runtime_selected_asset_mismatch",
                    "The selected reviewed workflow asset version no longer matches.",
                )
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or not isinstance(object_sha, str)
            or len(object_sha) != 64
        ):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The active reviewed workflow asset could not be verified.",
            )
        try:
            asset = validate_reviewed_workflow_asset(
                self._asset_store.load_active(asset_id)
            )
            asset_content_sha256 = content_sha256(asset)
            if (
                asset.get("asset_id") != asset_id
                or object_sha != asset_content_sha256
                or (
                    selection is not None
                    and asset_content_sha256 != selection.asset_content_sha256
                )
            ):
                raise ValueError("asset identity mismatch")
            application_identity_key = _asset_application_identity_key(asset)
            source_workflow_id = asset["source_review_lineage"][
                "source_workflow_id"
            ]
            workflow = WorkflowRefV1.model_validate(
                {
                    "workflow_id": source_workflow_id,
                    "asset_id": asset_id,
                    "asset_content_sha256": asset_content_sha256,
                    "source_workflow_sha256": asset["source_review_lineage"][
                        "source_workflow_sha256"
                    ],
                    "reviewed_revision_hash": asset["source_review_lineage"][
                        "reviewed_revision_hash"
                    ],
                }
            )
        except Exception as exc:
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The active reviewed workflow asset could not be verified.",
            ) from exc
        bound, process_id = self._current_bound_window(require_active=require_active)
        if selection is not None and (
            bound.handle != selection.target_window_handle
            or process_id != selection.target_process_id
        ):
            raise self._error(
                412,
                "agent_runtime_selection_binding_mismatch",
                "The selected runtime window binding no longer matches.",
            )
        return _ResolvedServerState(
            binding=ServerWorkflowBinding(
                workflow_id=source_workflow_id,
                asset_id=asset_id,
                application_identity_key=application_identity_key,
                target_window_handle=bound.handle,
            ),
            process_id=process_id,
            workflow=workflow,
        )

    def _current_bound_window(self, *, require_active: bool = True) -> tuple[Any, int]:
        try:
            bound = self._window_manager.get_bound_window()
        except Exception as exc:
            raise self._error(
                412,
                "agent_runtime_bound_window_required",
                "A current server-bound window is required.",
            ) from exc
        if bound is None:
            raise self._error(
                412,
                "agent_runtime_bound_window_required",
                "A current server-bound window is required.",
            )
        if require_active and bound.is_active is not True:
            raise self._error(
                412,
                "agent_runtime_bound_window_inactive",
                "The server-bound window must be active.",
            )
        if (
            type(bound.handle) is not int
            or bound.handle <= 0
            or type(bound.process_id) is not int
            or bound.process_id <= 0
        ):
            raise self._error(
                412,
                "agent_runtime_bound_window_invalid",
                "The server-bound window identity is invalid.",
            )
        return bound, bound.process_id

    def _verify_active_window(self) -> None:
        bound, process_id = self._current_bound_window()
        if (
            self._observation is None
            or self._target_window_handle is None
            or self._target_process_id is None
            or bound.handle != self._target_window_handle
            or process_id != self._target_process_id
        ):
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The active session no longer matches the bound window.",
            )

    def _project_controller_result(
        self,
        result: RuntimeResultReceiptV1 | LiveControllerDecision,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        if isinstance(result, RuntimeResultReceiptV1):
            self._clear_active()
            return result
        if not isinstance(result, LiveControllerDecision):
            raise self._error(
                503,
                "agent_runtime_recovery_required",
                "The controller returned an invalid runtime result.",
            )
        status = "NEEDS_REVIEW" if result.status == "CONFIRMATION_REQUIRED" else result.status
        confirmation_id = result.confirmation_id
        if status == "NEEDS_REVIEW":
            if not confirmation_id:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The confirmation request could not be verified.",
                )
            self._confirmation_id = confirmation_id
        if result.status == "RECOVERY_REQUIRED":
            return _DecisionProjection(status, result.reason_code, confirmation_id)
        if result.reason_code in {
            "confirmation_denied",
            "confirmation_expired",
            "confirmation_stale",
        }:
            self._clear_active()
        return _DecisionProjection(status, result.reason_code, confirmation_id)

    def _clear_active(self) -> None:
        self._grounded_recovery_id = None
        self._grounded_recovery_factory_unknown = False
        self._controller = None
        self._observation = None
        self._target_window_handle = None
        self._target_process_id = None
        self._confirmation_id = None
        self._grounded_intent = None
        self._grounded_confirmation_id = None
        self._grounded_cleanup = None
        self._preparation_owner = None
        self._preparation_cleanup_verified = True
        self._preparation_unknown = False

    def _retry_grounded_cleanup(self) -> None:
        pending = self._grounded_cleanup
        if pending is None:
            return
        controller, session_id, reason_code = pending
        try:
            if reason_code.startswith("consume:"):
                result = controller.consume_grounded_confirmation(
                    confirmation_id=reason_code.removeprefix("consume:")
                )
                if not isinstance(result, RuntimeResultReceiptV1):
                    raise RuntimeError("grounded terminal cleanup is incomplete")
            else:
                result = controller.cancel_grounded_review(
                    session_id=session_id,
                    reason_code=reason_code,
                )
        except Exception as exc:
            raise self._grounded_cleanup_error() from exc
        if isinstance(result, LiveControllerDecision):
            raise self._grounded_cleanup_error()
        self._grounded_cancelled_sessions.add(session_id)
        if (
            self._controller is controller
            and self._observation is not None
            and self._observation.session_id == session_id
        ):
            self._clear_active()
        else:
            self._grounded_cleanup = None

    def _retry_pending_cleanup(self) -> None:
        pending = self._pending_cleanup
        if pending is not None:
            self._release_started_session(*pending)
            self._preparation_cleanup_verified = True
            if (
                self._controller is pending[0]
                and self._observation is not None
                and self._observation.session_id == pending[1]
            ):
                if self._learning_binding is not None:
                    self._learning_cleanup = (pending[1], False)
                    self._retry_learning_cleanup()
                self._clear_active()
                self._cancelled_sessions.add(pending[1])

    def _retry_learning_cleanup(self) -> None:
        pending = self._learning_cleanup
        if pending is None:
            return
        if not self._preparation_cleanup_verified or self._learning_binding is None:
            raise self._prepared_cleanup_error()
        session_id, allow_absent = pending
        try:
            self._learning_binding.close_unconsumed(runtime_session_id=session_id)
        except AgentLinkError as error:
            # 只有关联失败前确实未产生 child 才允许缺失；不能吞掉来源故障。
            if not allow_absent or error.code != "not_found":
                raise self._prepared_cleanup_error() from error
        except Exception as error:
            raise self._prepared_cleanup_error() from error
        self._learning_cleanup = None
        self._cancelled_sessions.add(session_id)
        if self._observation is not None and self._observation.session_id == session_id:
            self._clear_active()

    def _release_preparation_after_start(
        self,
        controller: Any,
        session: Any,
        *,
        managed: bool,
    ) -> None:
        if managed:
            self._cancel_managed_preparation()
            return
        session_id = getattr(session, "session_id", None)
        if not isinstance(session_id, str) or not session_id:
            self._preparation_unknown = True
            raise self._error(
                503,
                "agent_runtime_cleanup_required",
                "The legacy preparation session identity cannot be verified.",
            )
        self._release_started_session(controller, session_id)
        self._preparation_cleanup_verified = True

    def _cancel_managed_preparation(self) -> None:
        owner = self._preparation_owner
        if owner is None:
            if self._preparation_cleanup_verified:
                return
            raise self._prepared_cleanup_error()
        controller, preparation_id = owner
        cancel = getattr(controller, "cancel_session_preparation", None)
        if not callable(cancel):
            raise self._prepared_cleanup_error()
        try:
            cancel(preparation_id=preparation_id)
        except Exception as exc:
            raise self._prepared_cleanup_error() from exc
        self._preparation_owner = None
        self._preparation_cleanup_verified = True
        self._preparation_unknown = False

    def _release_started_session(self, controller: Any, session_id: str) -> None:
        release = getattr(controller, "abandon_session", None)
        if not callable(release):
            self._pending_cleanup = (controller, session_id)
            raise self._prepared_cleanup_error()
        try:
            release(session_id=session_id)
        except Exception as exc:
            self._pending_cleanup = (controller, session_id)
            raise self._prepared_cleanup_error() from exc
        self._pending_cleanup = None

    def _prepared_cleanup_error(self) -> AgentRuntimeCallsiteError:
        # 旧无选择入口保留既有错误码；精确准备入口公开专用清理状态。
        code = (
            "agent_runtime_cleanup_required"
            if self._selection is not None
            else "agent_runtime_recovery_required"
        )
        return self._error(
            503,
            code,
            "The prepared runtime session could not be released safely.",
            retry_preparation=(
                self._selection is not None
                and not self._preparation_unknown
                and (
                    self._preparation_owner is not None
                    or self._pending_cleanup is not None
                    or self._preparation_cleanup_verified
                )
            ),
        )

    def _grounded_cleanup_error(self) -> AgentRuntimeCallsiteError:
        return self._error(
            503,
            "agent_runtime_cleanup_required",
            "The grounded runtime session could not be released safely.",
        )

    @staticmethod
    def _error(
        status_code: int,
        code: str,
        message: str,
        *,
        retry_preparation: bool = False,
    ) -> AgentRuntimeCallsiteError:
        return AgentRuntimeCallsiteError(
            status_code=status_code,
            code=code,
            message=message,
            retry_preparation=retry_preparation,
        )


def _asset_application_identity_key(asset: Mapping[str, Any]) -> str:
    application = asset.get("application")
    if not isinstance(application, Mapping):
        raise ValueError("reviewed asset application identity is missing")
    return asset_application_identity_key(application)


_DEFAULT_CALLSITE: LocalAgentRuntimeCallsite | None = None
_DEFAULT_CALLSITE_LOCK = RLock()


def get_agent_runtime_callsite() -> LocalAgentRuntimeCallsite:
    global _DEFAULT_CALLSITE
    with _DEFAULT_CALLSITE_LOCK:
        if _DEFAULT_CALLSITE is None:
            project_root = Path(__file__).resolve().parents[2]
            receipt_store = RuntimeReceiptStore(project_root=project_root)
            claim_store = RuntimeIntentClaimStore(
                project_root=project_root,
                receipt_store=receipt_store,
            )
            _DEFAULT_CALLSITE = LocalAgentRuntimeCallsite(
                project_root=project_root,
                asset_store=ReviewedWorkflowAssetStore(project_root=project_root),
                window_manager=window_manager,
                claim_store=claim_store,
            )
        return _DEFAULT_CALLSITE


def _require_loopback(request: Request) -> None:
    host = request.client.host if request.client is not None else ""
    try:
        allowed = ip_address(host).is_loopback
    except ValueError:
        allowed = False
    if not allowed:
        raise AgentRuntimeCallsiteError(
            status_code=403,
            code="agent_runtime_loopback_required",
            message="Agent runtime endpoints are available only from loopback clients.",
        )


def _success(message: str, data: Any) -> APIResponse:
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    if isinstance(data, _DecisionProjection):
        payload = data.to_dict()
    return APIResponse(success=True, message=message, data=payload, error=None)


def _failure(exc: AgentRuntimeCallsiteError) -> JSONResponse:
    envelope = APIResponse(
        success=False,
        message=exc.message,
        data=None,
        error=ErrorModel(code=exc.code, details=exc.message),
    )
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(mode="json"))


@router.post("/session/start", response_model=APIResponse)
def start_agent_runtime_session(
    payload: AgentRuntimeStartRequest,
    request: Request,
    callsite: LocalAgentRuntimeCallsite = Depends(get_agent_runtime_callsite),
):
    try:
        _require_loopback(request)
        return _success("Agent runtime session started.", callsite.start_session())
    except AgentRuntimeCallsiteError as exc:
        return _failure(exc)


@router.post("/intent/submit", response_model=APIResponse)
def submit_agent_runtime_intent(
    payload: AgentRuntimeIntentRequest,
    request: Request,
    callsite: LocalAgentRuntimeCallsite = Depends(get_agent_runtime_callsite),
):
    try:
        _require_loopback(request)
        return _success("Agent runtime intent processed.", callsite.submit_intent(payload))
    except AgentRuntimeCallsiteError as exc:
        return _failure(exc)


@router.post("/confirmation/decide", response_model=APIResponse)
def decide_agent_runtime_confirmation(
    payload: AgentRuntimeConfirmationDecisionRequest,
    request: Request,
    callsite: LocalAgentRuntimeCallsite = Depends(get_agent_runtime_callsite),
):
    try:
        _require_loopback(request)
        return _success(
            "Agent runtime confirmation processed.",
            callsite.decide_confirmation(payload),
        )
    except AgentRuntimeCallsiteError as exc:
        return _failure(exc)


__all__ = [
    "LocalAgentRuntimeCallsite",
    "get_agent_runtime_callsite",
    "router",
]
