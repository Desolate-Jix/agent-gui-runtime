from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal, Mapping

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.agent.live_controller import (
    LiveController,
    LiveControllerDecision,
    ServerWorkflowBinding,
)
from app.agent.live_runtime_composition import build_existing_windows_live_controller
from app.agent.reviewed_workflow_asset import (
    ReviewedWorkflowAssetStore,
    content_sha256,
    validate_reviewed_workflow_asset,
)
from app.agent.runtime_contracts import (
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
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


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


class LocalAgentRuntimeCallsite:
    """本地单实例入口；客户端只选择服务器已暴露的动作。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        asset_store: Any,
        window_manager: Any,
        claim_store: Any,
        controller_factory: Callable[[ServerWorkflowBinding], LiveController] | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._asset_store = asset_store
        self._window_manager = window_manager
        self._claim_store = claim_store
        self._controller_factory = controller_factory or (
            lambda binding: build_existing_windows_live_controller(
                self._project_root,
                binding,
            )
        )
        self._lock = RLock()
        self._controller: LiveController | Any | None = None
        self._observation: AgentObservationV1 | None = None
        self._target_window_handle: int | None = None
        self._target_process_id: int | None = None
        self._confirmation_id: str | None = None

    def start_session(self) -> AgentObservationV1:
        with self._lock:
            if self._observation is not None:
                raise self._error(
                    409,
                    "agent_runtime_session_active",
                    "An agent runtime session is already active.",
                )
            try:
                unresolved = self._claim_store.list_unresolved_claims()
            except RuntimeIntentClaimStoreError as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "Durable runtime state could not be verified.",
                ) from exc
            if unresolved:
                raise self._error(
                    412,
                    "agent_runtime_unresolved_claim_exists",
                    "An unresolved durable runtime operation must be recovered first.",
                )
            resolved = self._resolve_server_binding()
            try:
                controller = self._controller_factory(resolved.binding)
                session = controller.start_session()
            except Exception as exc:
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The server could not create a verified agent observation.",
                ) from exc
            try:
                post_start = self._resolve_server_binding()
            except AgentRuntimeCallsiteError:
                self._release_started_session(controller, session.session_id)
                raise
            observation = session.current_observation
            binding = resolved.binding
            if (
                post_start != resolved
                or not isinstance(observation, AgentObservationV1)
                or session.session_id != observation.session_id
                or session.workflow != resolved.workflow
                or session.target_window_handle != binding.target_window_handle
                or observation.workflow != resolved.workflow
                or observation.application.identity_ref
                != f"application:{binding.application_identity_key}"
            ):
                self._release_started_session(controller, session.session_id)
                raise self._error(
                    503,
                    "agent_runtime_recovery_required",
                    "The server observation binding could not be verified.",
                )
            self._controller = controller
            self._observation = observation
            self._target_window_handle = binding.target_window_handle
            self._target_process_id = resolved.process_id
            self._confirmation_id = None
            return observation

    def submit_intent(
        self,
        request: AgentRuntimeIntentRequest,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        with self._lock:
            if self._observation is not None:
                observation = self._observation
                selected_action = next(
                    (
                        action
                        for action in observation.available_actions
                        if action.action_id == request.action_id
                    ),
                    None,
                )
                if (
                    request.session_id != observation.session_id
                    or request.observation_id != observation.observation_id
                    or request.action_id != "open_apply_flow"
                    or selected_action is None
                    or selected_action.semantic_action != "open_apply_flow"
                ):
                    raise self._error(
                        409,
                        "agent_runtime_invalid_intent",
                        "The intent does not match the active server observation.",
                    )
                self._verify_active_window()
                try:
                    intent = validate_agent_intent_v1(
                        {
                            "contract_version": "agent_intent_v1",
                            "intent_id": request.intent_id,
                            "session_id": request.session_id,
                            "observation_id": request.observation_id,
                            "workflow": observation.workflow.model_dump(mode="json"),
                            "action_id": request.action_id,
                        },
                        observation=observation,
                    )
                except (TypeError, ValueError) as exc:
                    raise self._error(
                        409,
                        "agent_runtime_invalid_intent",
                        "The intent does not match the active server observation.",
                    ) from exc
                controller = self._controller
            else:
                claim = self._find_exact_claim(request)
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

    def decide_confirmation(
        self,
        request: AgentRuntimeConfirmationDecisionRequest,
    ) -> RuntimeResultReceiptV1 | _DecisionProjection:
        with self._lock:
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
            or request.action_id != "open_apply_flow"
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
            or intent.action_id != "open_apply_flow"
            or action is None
            or action.action_id != intent.action_id
            or action.semantic_action != "open_apply_flow"
        ):
            raise self._error(
                412,
                "agent_runtime_binding_mismatch",
                "The durable operation action no longer matches the reviewed Portfolio transition.",
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

    def _resolve_server_binding(self) -> _ResolvedServerState:
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
        if len(active) != 1:
            raise self._error(
                412,
                "agent_runtime_active_asset_ambiguous",
                "Exactly one active reviewed workflow asset is required.",
            )
        asset_id, object_sha = next(iter(active.items()))
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
            ):
                raise ValueError("asset identity mismatch")
            application_identity_key = _asset_application_identity_key(asset)
            workflow = WorkflowRefV1.model_validate(
                {
                    "workflow_id": asset_id,
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
        bound, process_id = self._current_bound_window()
        return _ResolvedServerState(
            binding=ServerWorkflowBinding(
                workflow_id=asset_id,
                asset_id=asset_id,
                application_identity_key=application_identity_key,
                target_window_handle=bound.handle,
            ),
            process_id=process_id,
            workflow=workflow,
        )

    def _current_bound_window(self) -> tuple[Any, int]:
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
        if bound.is_active is not True:
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
        self._controller = None
        self._observation = None
        self._target_window_handle = None
        self._target_process_id = None
        self._confirmation_id = None

    @staticmethod
    def _release_started_session(controller: Any, session_id: str) -> None:
        for name in ("abandon_session", "close_session"):
            release = getattr(controller, name, None)
            if callable(release):
                try:
                    release(session_id=session_id)
                except Exception:
                    pass
                return

    @staticmethod
    def _error(status_code: int, code: str, message: str) -> AgentRuntimeCallsiteError:
        return AgentRuntimeCallsiteError(
            status_code=status_code,
            code=code,
            message=message,
        )


def _asset_application_identity_key(asset: Mapping[str, Any]) -> str:
    application = asset.get("application")
    if not isinstance(application, Mapping):
        raise ValueError("reviewed asset application identity is missing")
    kind = application.get("kind")
    if kind == "web":
        identity = application.get("canonical_domain")
    elif kind == "native":
        identity = application.get("product_identity") or application.get("executable")
    else:
        identity = None
    if not isinstance(kind, str) or not isinstance(identity, str) or not identity:
        raise ValueError("reviewed asset application identity is unsupported")
    return f"{kind}:{identity}"


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
