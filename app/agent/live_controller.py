"""W4 server-owned Live Controller 的最小可执行纵切。"""

from __future__ import annotations

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, RuntimeFreshLearningClaimSnapshot
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, build_fresh_learning_action_preview, validate_fresh_preview_binding,
)

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from threading import RLock
import time
from typing import Any, Literal, Protocol
from uuid import uuid4
from weakref import WeakValueDictionary

from app.agent.desktop_backend import (
    BackendDispatchReceipt,
    DesktopBackend,
    DesktopDispatchCommand,
    _mint_execution_authority,
)
from app.agent.native_identity import asset_application_identity_key
from app.agent.action_parameters import reviewed_action_parameter_fields
from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters, scroll_parameter_fields
from app.agent.text_parameters import ReviewedTextParameters, ResolvedTextParameters, TextDispatchParameters, resolve_text_parameters, text_parameter_reference
from app.agent.text_execution import text_execution_reference, validate_local_text_preview
from app.agent.text_field_evidence import TextFieldExpectation, prepare_text_field_expectation, validate_text_field_precondition, verify_text_field_result_reference
from app.agent.text_input_guard import TextInputGuard
from app.gate.scroll_evidence import measure_scroll_spatial_evidence
from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentConfirmationSnapshot,
    RuntimeIntentClaimSnapshot,
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
    RuntimeVerificationPendingCheckpoint,
)
from app.agent.action_learning_recorder import (
    ActionLearningRecorder,
    ActionLearningRecorderError,
    BEFORE_CONTRACT_VERSION,
)
from app.agent.runtime_grounded_consume import (
    RuntimeGroundedConsumeSnapshot,
    RuntimeGroundedConsumeError,
    validate_fresh_preview,
)
from app.agent.reviewed_workflow_asset import (
    ReviewedWorkflowAssetStore,
    content_sha256,
    validate_reviewed_workflow_asset,
)
from app.agent.reviewed_workflow_replay import (
    _select_grounded_confirmed_transition,
    _select_server_confirmed_transition,
    _verify_grounded_server_dispatched_transition_result,
    _validate_server_confirmed_grounding,
    _validate_grounded_current_grounding,
    resolve_current_state,
    select_transition_for_review,
    select_verified_transition,
    validate_current_grounding,
    validate_review_grounding_preview,
    verify_server_dispatched_transition_result,
)
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    WorkflowRefV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
)
from app.agent.fresh_learning_runtime_session import (
    ServerFreshLearningBinding, FreshLearningSessionSnapshot,
    validate_fresh_runtime_owners, observe_fresh_runtime_session,
)


@dataclass(frozen=True, slots=True)
class ServerWorkflowBinding:
    workflow_id: str
    asset_id: str
    application_identity_key: str
    target_window_handle: int

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.asset_id or not self.application_identity_key:
            raise ValueError("server workflow binding requires workflow, asset, and application identity")
        if type(self.target_window_handle) is not int or self.target_window_handle <= 0:
            raise ValueError("server workflow binding requires a positive target window handle")


@dataclass(frozen=True, slots=True)
class LiveSessionSnapshot:
    session_id: str
    workflow: WorkflowRefV1
    current_observation: AgentObservationV1
    target_window_handle: int


@dataclass(frozen=True, slots=True)
class LiveControllerDecision:
    status: str
    reason_code: str
    confirmation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectedObservationCapture:
    """同一 passive capture 派生出的 C1 与严格 AgentObservation。"""

    session_id: str
    workflow: WorkflowRefV1
    application_identity_key: str
    asset_id: str
    asset_content_sha256: str
    target_window_handle: int
    target_process_id: int
    current_observation: dict[str, Any]
    agent_observation: AgentObservationV1
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False


class AssetLoader(Protocol):
    def load_active(self, asset_id: str) -> dict[str, Any]: ...


class ObservationSource(Protocol):
    def create_initial(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> AgentObservationV1 | Mapping[str, object]: ...

    def capture_current(
        self,
        *,
        session_id: str,
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> Mapping[str, Any]: ...

    def capture_projected(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
        asset: dict[str, Any],
        target_window_handle: int,
    ) -> ProjectedObservationCapture: ...


class TargetResolver(Protocol):
    def resolve(
        self,
        *,
        session_id: str,
        selection: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> Mapping[str, Any]: ...


class Gate(Protocol):
    def evaluate(
        self,
        *,
        selection: dict[str, Any],
        grounding: dict[str, Any],
        **context: Any,
    ) -> Mapping[str, Any]: ...


class WindowVisibilityChecker(Protocol):
    def check(
        self,
        *,
        session_id: str,
        capture_lineage: Mapping[str, Any],
        target_window_handle: int,
        click_point: tuple[float, float],
        target_bbox: tuple[float, float, float, float],
    ) -> Mapping[str, Any]: ...


class ExistingWindowManagerVisibilityChecker:
    """把 WindowManager 事实投影给 Runtime；不拥有允许执行的判断权。"""

    def __init__(self, *, window_manager: Any | None = None) -> None:
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        self._window_manager = window_manager

    def check(
        self,
        *,
        session_id: str,
        capture_lineage: Mapping[str, Any],
        target_window_handle: int,
        click_point: tuple[float, float],
        target_bbox: tuple[float, float, float, float],
    ) -> Mapping[str, Any]:
        try:
            bound = self._window_manager.get_bound_window()
        except Exception as exc:
            return {
                "bound_window_handle": None,
                "point_visibility": None,
                "error": str(exc),
            }
        if bound is None or int(bound.handle) != target_window_handle:
            return {
                "bound_window_handle": int(bound.handle) if bound is not None else None,
                "point_visibility": None,
            }
        try:
            fact = self._window_manager.validate_bound_point_visibility(
                bound=bound,
                x=int(click_point[0]),
                y=int(click_point[1]),
            )
            region_check = getattr(self._window_manager, "validate_bound_region_visibility", None)
            region = region_check(bound=bound, bbox=target_bbox) if callable(region_check) else None
            if not isinstance(region, Mapping) or type(region.get("allowed")) is not bool:
                region = {"allowed": False, "reason": "target_region_visibility_unavailable"}
            fact = dict(fact)
            if region.get("allowed") is not True:
                fact.update(allowed=False, reason=region.get("reason") or "target_region_visibility_unavailable")
        except Exception as exc:
            return {
                "bound_window_handle": target_window_handle,
                "point_visibility": None,
                "error": str(exc),
            }
        return {
            "bound_window_handle": target_window_handle,
            "point_visibility": dict(fact),
            "region_visibility": dict(region),
        }


@dataclass(slots=True, weakref_slot=True)
class _WindowLease:
    target_window_handle: int
    session_id: str


_WINDOW_LEASES: WeakValueDictionary[int, _WindowLease] = WeakValueDictionary()
_WINDOW_LEASE_LOCK = RLock()
_OPAQUE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


@dataclass(slots=True)
class _LiveSession:
    snapshot: LiveSessionSnapshot
    asset: dict[str, Any]
    window_lease: _WindowLease
    consumed: bool = False
    confirmation: RuntimeIntentConfirmationSnapshot | None = None
    grounded_consume: RuntimeGroundedConsumeSnapshot | None = None


@dataclass(frozen=True, slots=True)
class _ReviewedSessionSource:
    asset: dict[str, Any]
    workflow: WorkflowRefV1


@dataclass(slots=True)
class _FreshLiveSession:
    snapshot: FreshLearningSessionSnapshot
    window_lease: _WindowLease
    consumed: bool = False
    confirmation: None = None


@dataclass(slots=True)
class _PreparationAttempt:
    preparation_id: str
    state: str
    session_id: str | None = None
    window_lease: _WindowLease | None = None


@dataclass(frozen=True, slots=True)
class _GroundedPublicationContext:
    intent: AgentIntentV1 | FreshLearningIntent
    preview: GroundedActionPreview | FreshLearningActionPreview
    target_process_id: int
    text_input: ResolvedTextParameters | None = field(default=None, repr=False)
    text_field_expectation: TextFieldExpectation | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _PreparedGroundedReview:
    preview: GroundedActionPreview | FreshLearningActionPreview
    text_field_expectation: TextFieldExpectation | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    receipt: RuntimeResultReceiptV1
    backend_receipt: BackendDispatchReceipt | None = None
    verification_evidence: Mapping[str, object] | None = None
    next_observation: AgentObservationV1 | None = None


@dataclass(frozen=True, slots=True)
class _GroundedSelection:
    selection: dict[str, Any]
    grounding: dict[str, Any]
    gate: dict[str, Any]
    validation: dict[str, Any]
    click_point: tuple[float, float]
    target_bbox: tuple[float, float, float, float]
    gate_context: dict[str, Any]
    visibility: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _CurrentProjection:
    projected: ProjectedObservationCapture
    current: dict[str, Any]
    state_resolution: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _CurrentProjectionFailure:
    reason_code: str
    recovery_required: bool = False


@dataclass(frozen=True, slots=True)
class _GroundingFailure:
    reason_code: str
    recovery_required: bool = False
    selection: dict[str, Any] | None = None
    grounding: dict[str, Any] | None = None
    gate: dict[str, Any] | None = None
    gate_blocked: bool = False


class LiveController:
    def __init__(
        self,
        *,
        binding: ServerWorkflowBinding | ServerFreshLearningBinding,
        observation_source: ObservationSource,
        target_resolver: TargetResolver,
        gate: Gate,
        window_visibility_checker: WindowVisibilityChecker | None = None,
        backend: DesktopBackend,
        intent_claim_store: RuntimeIntentClaimStore,
        grounding_policy: Mapping[str, Any],
        asset_loader: AssetLoader | None = None,
        project_root: str | Path | None = None,
        verification_max_capture_attempts: int = 4,
        verification_poll_interval_seconds: float = 0.25,
        verification_total_budget_seconds: float = 30.0,
        verification_sleeper: Callable[[float], None] | None = None,
        verification_monotonic_clock: Callable[[], float] | None = None,
        action_learning_recorder: ActionLearningRecorder | None = None,
        fresh_source_owner: Any | None = None,
        automatic_safety_interception: bool = True,
    ) -> None:
        from app.agent.automatic_safety_policy import validate_automatic_safety_interception
        self._automatic_safety_interception = validate_automatic_safety_interception(automatic_safety_interception)
        if not self._automatic_safety_interception and not isinstance(binding, ServerFreshLearningBinding):
            raise ValueError('automatic safety observation mode is supported only by fresh single-step learning')
        if not isinstance(intent_claim_store, RuntimeIntentClaimStore):
            raise ValueError("intent_claim_store is required")
        if isinstance(binding, ServerFreshLearningBinding):
            validate_fresh_runtime_owners(binding.source, fresh_source_owner,
                observation_source, intent_claim_store.project_root)
        elif fresh_source_owner is not None:
            raise ValueError("fresh source owner requires a fresh learning binding")
        elif asset_loader is None:
            if project_root is None:
                raise ValueError("project_root is required when no trusted asset loader is provided")
            asset_loader = ReviewedWorkflowAssetStore(project_root=project_root)
        if (
            isinstance(verification_max_capture_attempts, bool)
            or not isinstance(verification_max_capture_attempts, int)
            or verification_max_capture_attempts < 1
        ):
            raise ValueError("verification_max_capture_attempts must be a positive integer")
        for name, value, allow_zero in (
            (
                "verification_poll_interval_seconds",
                verification_poll_interval_seconds,
                True,
            ),
            (
                "verification_total_budget_seconds",
                verification_total_budget_seconds,
                False,
            ),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or (float(value) < 0 if allow_zero else float(value) <= 0)
            ):
                qualifier = "finite and nonnegative" if allow_zero else "finite and positive"
                raise ValueError(f"{name} must be {qualifier}")
        if verification_sleeper is not None and not callable(verification_sleeper):
            raise TypeError("verification_sleeper must be callable")
        if verification_monotonic_clock is not None and not callable(
            verification_monotonic_clock
        ):
            raise TypeError("verification_monotonic_clock must be callable")
        self._binding = binding
        self._fresh_source_owner = fresh_source_owner
        self._asset_loader = asset_loader
        self._observation_source = observation_source
        self._target_resolver = target_resolver
        self._gate = gate
        self._window_visibility_checker = (
            window_visibility_checker or ExistingWindowManagerVisibilityChecker()
        )
        self._backend = backend
        self._intent_claim_store = intent_claim_store
        self._grounding_policy = dict(grounding_policy)
        self._verification_max_capture_attempts = verification_max_capture_attempts
        self._verification_poll_interval_seconds = float(
            verification_poll_interval_seconds
        )
        self._verification_total_budget_seconds = float(
            verification_total_budget_seconds
        )
        self._verification_sleeper = (
            verification_sleeper
            if verification_sleeper is not None
            else time.sleep
        )
        self._verification_monotonic_clock = (
            verification_monotonic_clock
            if verification_monotonic_clock is not None
            else time.monotonic
        )
        self._sessions: dict[str, _LiveSession | _FreshLiveSession] = {}
        self._abandoned_sessions: set[str] = set()
        self._preparation_attempts: dict[str, _PreparationAttempt] = {}
        self._grounded_publications: dict[str, _GroundedPublicationContext] = {}
        self._grounded_cancelled_sessions: set[str] = set()
        self._released_fresh_confirmations: dict[str, tuple[str, str, str, str]] = {}
        self._grounded_recovery_sessions: dict[str, _LiveSession] = {}
        self._lock = RLock()
        self._action_learning_recorder: ActionLearningRecorder | None = None
        if action_learning_recorder is not None:
            self.set_action_learning_recorder(action_learning_recorder)

    def set_action_learning_recorder(
        self,
        recorder: ActionLearningRecorder,
    ) -> None:
        """在会话开始前显式注入非执行型记录器。"""

        if not isinstance(recorder, ActionLearningRecorder):
            raise TypeError("action_learning_recorder must be ActionLearningRecorder")
        if recorder.project_root != self._intent_claim_store.project_root:
            raise ValueError("action learning recorder must use the claim store project root")
        with self._lock:
            if self._sessions:
                raise ValueError("action learning recorder must be set before a runtime session starts")
            if self._action_learning_recorder is not None:
                if self._action_learning_recorder is recorder:
                    return
                raise ValueError("action learning recorder is already set")
            self._action_learning_recorder = recorder
            self._intent_claim_store.add_terminal_receipt_observer(
                recorder.observe_terminal_receipt
            )

    def start_session(self) -> LiveSessionSnapshot | FreshLearningSessionSnapshot:
        return self._start_session_core(preparation=None)

    def start_session_preparation(self, *, preparation_id: str) -> LiveSessionSnapshot | FreshLearningSessionSnapshot:
        """记录本地准备所有权，并复用唯一的会话启动核心。"""
        if (
            not isinstance(preparation_id, str)
            or not preparation_id
            or preparation_id != preparation_id.strip()
            or len(preparation_id) > 256
        ):
            raise ValueError("preparation identity is invalid")
        with self._lock:
            if preparation_id in self._preparation_attempts:
                raise ValueError("preparation identity is already recorded")
            if any(
                attempt.state in {"starting", "active", "cleanup_required"}
                for attempt in self._preparation_attempts.values()
            ):
                raise ValueError("another preparation attempt is active")
            preparation = _PreparationAttempt(preparation_id, "starting")
            self._preparation_attempts[preparation_id] = preparation
        try:
            return self._start_session_core(preparation=preparation)
        except Exception:
            with self._lock:
                if preparation.state == "starting":
                    preparation.state = "closed"
            raise

    def cancel_session_preparation(self, *, preparation_id: str) -> None:
        """只关闭本控制器记录的 exact preparation attempt。"""
        if not isinstance(preparation_id, str) or not preparation_id:
            raise ValueError("preparation identity is invalid")
        with self._lock:
            attempt = self._preparation_attempts.get(preparation_id)
            if attempt is None:
                raise ValueError("preparation attempt is not owned by this controller")
            if attempt.state == "closed":
                return
            if attempt.state == "starting":
                raise ValueError("preparation attempt is still starting")
            session_id = attempt.session_id
            lease = attempt.window_lease
            session = self._sessions.get(session_id) if session_id is not None else None
            if session is not None:
                self.abandon_session(session_id=session_id)
                attempt.state = "closed"
                return
            if attempt.state != "cleanup_required" or lease is None:
                raise ValueError("preparation attempt ownership cannot be verified")
            try:
                self._release_window_lease(lease)
            except Exception:
                raise
            attempt.state = "closed"

    def _load_reviewed_session_source(self) -> _ReviewedSessionSource:
        asset = validate_reviewed_workflow_asset(
            self._asset_loader.load_active(self._binding.asset_id)
        )
        if asset["asset_id"] != self._binding.asset_id:
            raise ValueError("active reviewed asset identity does not match server binding")
        if (
            asset["source_review_lineage"]["source_workflow_id"]
            != self._binding.workflow_id
        ):
            raise ValueError("reviewed source workflow identity does not match server binding")
        expected_application_key = self._asset_application_identity_key(asset)
        if expected_application_key != self._binding.application_identity_key:
            raise ValueError("reviewed asset application identity does not match server binding")
        workflow = WorkflowRefV1.model_validate(
            {
                "workflow_id": self._binding.workflow_id,
                "asset_id": asset["asset_id"],
                "asset_content_sha256": content_sha256(asset),
                "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
                "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
            }
        )
        return _ReviewedSessionSource(asset, workflow)

    def _start_session_core(
        self,
        *,
        preparation: _PreparationAttempt | None,
    ) -> LiveSessionSnapshot | FreshLearningSessionSnapshot:
        if isinstance(self._binding, ServerFreshLearningBinding):
            from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source

            validate_fresh_runtime_owners(self._binding.source, self._fresh_source_owner,
                self._observation_source, self._intent_claim_store.project_root)
            source = reload_fresh_learning_runtime_source(self._fresh_source_owner, self._binding.source)
        else:
            source = self._load_reviewed_session_source()
        session_id = f"session.{uuid4().hex}"
        lease = self._acquire_window_lease(session_id)
        if preparation is not None:
            with self._lock:
                preparation.session_id = session_id
                preparation.window_lease = lease
        try:
            if not isinstance(source, _ReviewedSessionSource):
                snapshot = observe_fresh_runtime_session(source=source,
                    source_owner=self._fresh_source_owner,
                    observation_owner=self._observation_source, session_id=session_id)
                session = _FreshLiveSession(snapshot=snapshot, window_lease=lease)
            else:
                asset, workflow = source.asset, source.workflow
                projected = self._observation_source.create_initial(
                    session_id=session_id,
                    workflow=workflow.model_dump(mode="json"),
                    asset=asset,
                    target_window_handle=self._binding.target_window_handle,
                )
                observation = (
                    projected
                    if isinstance(projected, AgentObservationV1)
                    else validate_agent_observation_v1(projected)
                )
                if observation.session_id != session_id or observation.workflow != workflow:
                    raise ValueError("server observation does not match pinned session workflow")
                if (
                    observation.application.kind != asset["application"]["kind"]
                    or observation.application.identity_ref
                    != f"application:{self._binding.application_identity_key}"
                ):
                    raise ValueError("server observation application identity does not match reviewed asset")
                snapshot = LiveSessionSnapshot(
                    session_id=session_id,
                    workflow=workflow,
                    current_observation=observation,
                    target_window_handle=self._binding.target_window_handle,
                )
                session = _LiveSession(snapshot=snapshot, asset=asset, window_lease=lease)
            with self._lock:
                self._sessions[session_id] = session
                if preparation is not None:
                    preparation.state = "active"
        except Exception:
            try:
                self._release_window_lease(lease)
            except Exception as cleanup_error:
                if preparation is not None:
                    with self._lock:
                        preparation.state = "cleanup_required"
                raise RuntimeError("preparation cleanup is required") from cleanup_error
            if preparation is not None:
                with self._lock:
                    preparation.state = "closed"
            raise
        return snapshot

    def abandon_session(self, *, session_id: str) -> None:
        """仅释放本控制器未消费且没有持久意图的准备会话。"""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("prepared session identity is invalid")
        with self._lock:
            if session_id in self._abandoned_sessions:
                return
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("prepared session is not owned by this controller")
            if session.consumed or session.confirmation is not None:
                raise ValueError("prepared session has already been consumed")
            claim = self._intent_claim_store.find_for_observation(
                session_id=session.snapshot.session_id,
                observation_id=session.snapshot.current_observation.observation_id,
            )
            if claim is not None:
                raise ValueError("prepared session has a durable intent claim")
            self._release_window_lease(session.window_lease)
            self._sessions.pop(session_id)
            self._abandoned_sessions.add(session_id)
            self._close_preparation_for_session(session_id)

    def get_local_reviewed_text_parameters(self, *, session_id: str, action_id: str) -> ReviewedTextParameters:
        """只在本地拥有者内读取审核原文，不投影到 Agent 观察。"""
        if isinstance(self._binding, ServerFreshLearningBinding):
            raise ValueError("fresh learning has no reviewed text parameters")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("text session is not owned")
            actions = [item for item in session.snapshot.current_observation.available_actions if item.action_id == action_id]
            transitions = [item for item in session.asset["transitions"] if item["transition_id"] == action_id]
            if len(actions) != 1 or actions[0].semantic_action != "fill_field" or len(transitions) != 1:
                raise ValueError("text action is not available")
            reviewed = ReviewedTextParameters.from_payload(transitions[0].get("text_parameters"))
            if actions[0].text_parameters_ref != text_parameter_reference(reviewed):
                raise ValueError("text declaration binding changed")
            return reviewed

    def _resolve_local_text_input(self, session, action_id, supplied):
        action = next((item for item in session.snapshot.current_observation.available_actions if item.action_id == action_id), None)
        if action is None or action.semantic_action != "fill_field":
            return None if supplied is None else LiveControllerDecision("REJECTED", "text_input_invalid")
        try:
            reviewed = self.get_local_reviewed_text_parameters(session_id=session.snapshot.session_id, action_id=action_id)
            if supplied is None:
                if reviewed.content.kind == "variable":
                    return LiveControllerDecision("REJECTED", "text_input_required")
                return resolve_text_parameters(reviewed, {})
            if type(supplied) is not ResolvedTextParameters or supplied.reviewed != reviewed:
                raise ValueError("text input declaration changed")
            return supplied
        except (TypeError, ValueError):
            return LiveControllerDecision("REJECTED", "text_input_invalid")

    def prepare_grounded_review(
        self,
        payload: Mapping[str, object],
        *,
        target_process_id: int,
        text_input: ResolvedTextParameters | None = None,
    ) -> GroundedActionPreview | LiveControllerDecision:
        prepared = self._prepare_grounded_review(
            payload, target_process_id=target_process_id, text_input=text_input,
        )
        return prepared.preview if isinstance(prepared, _PreparedGroundedReview) else prepared

    def _prepare_grounded_review(
        self, payload: Mapping[str, object], *, target_process_id: int,
        text_input: ResolvedTextParameters | None = None,
    ) -> _PreparedGroundedReview | LiveControllerDecision:
        """在同一会话锁内生成无权限、零派发的当前定位预览。"""
        if isinstance(self._binding, ServerFreshLearningBinding):
            return self._prepare_fresh_grounded_review(payload, target_process_id=target_process_id,
                text_input=text_input)
        if type(target_process_id) is not int or target_process_id <= 0:
            return LiveControllerDecision("REJECTED", "invalid_target_process_id")
        session_id = payload.get("session_id") if isinstance(payload, Mapping) else None
        with self._lock:
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if session is None:
                return LiveControllerDecision("REJECTED", "unknown_session")
            if session.snapshot.session_id in self._grounded_publications:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_active"
                )
            try:
                claim = self._intent_claim_store.find_for_observation(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision("RECOVERY_REQUIRED", "claim_integrity_failed")
            if claim is not None or session.consumed or session.confirmation is not None:
                return LiveControllerDecision("REJECTED", "observation_consumed")
            try:
                intent = validate_agent_intent_v1(
                    payload,
                    observation=session.snapshot.current_observation,
                )
            except (TypeError, ValueError):
                return LiveControllerDecision("REJECTED", "invalid_intent")
            if intent.action_id == "runtime.safe_stop":
                return LiveControllerDecision("REJECTED", "safe_stop_boundary")
            text_input = self._resolve_local_text_input(session, intent.action_id, text_input)
            if isinstance(text_input, LiveControllerDecision):
                return text_input
            projection = self._capture_current_resolution(
                session=session,
                expected_process_id=target_process_id,
            )
            if isinstance(projection, _CurrentProjectionFailure):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED" if projection.recovery_required else "REJECTED",
                    projection.reason_code,
                )
            projected = projection.projected
            current = projection.current
            state_resolution = projection.state_resolution
            try:
                selection = select_transition_for_review(
                    session.asset,
                    state_resolution,
                    transition_id=intent.action_id,
                    current_observation=current,
                )
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "transition_selection_failed"
                )
            if selection.get("status") != "selected":
                reason = self._normalize_block_reason(
                    str(selection.get("failure_code") or "target_unresolved")
                )
                return LiveControllerDecision("REJECTED", reason)
            review_gate = getattr(self._gate, "evaluate_review", None)
            if not callable(review_gate):
                return LiveControllerDecision("RECOVERY_REQUIRED", "review_gate_unavailable")
            grounded = self._ground_selected_current(
                session=session,
                current=current,
                selection=selection,
                validator=lambda selected, evidence, gate: validate_review_grounding_preview(
                    session.asset,
                    selected,
                    evidence,
                    gate,
                    policy=self._grounding_policy,
                ),
                gate_evaluator=review_gate,
            )
            if isinstance(grounded, _GroundingFailure):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED" if grounded.recovery_required else "REJECTED",
                    grounded.reason_code,
                )
            text_field_expectation = None
            if text_input is not None:
                try:
                    before_field = self._observation_source.read_text_field(
                        session_id=session.snapshot.session_id, current_observation=current,
                        selection=grounded.selection, grounding=grounded.grounding,
                    )
                    text_field_expectation = prepare_text_field_expectation(before_field, text_input)
                except (AttributeError, TypeError, ValueError, OSError):
                    return LiveControllerDecision("REJECTED", "text_field_unavailable")
            preview_payload: dict[str, Any] = {
                "contract_version": "grounded_action_preview_v1",
                "status": "prepared",
                "review_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "grants_action_authority": False,
                "session_id": session.snapshot.session_id,
                "observation_id": session.snapshot.current_observation.observation_id,
                "intent_id": intent.intent_id,
                "workflow": session.snapshot.workflow.model_dump(mode="json"),
                "target_window_handle": session.snapshot.target_window_handle,
                "target_process_id": projected.target_process_id,
                "current_observation": projected.agent_observation.model_dump(mode="json"),
                "review_selection": deepcopy(grounded.selection),
                "grounding_preview": deepcopy(grounded.validation),
            }
            if text_input is not None:
                preview_payload["text_execution_ref"] = text_execution_reference(text_input)
                preview_payload["text_field_expectation_ref"] = text_field_expectation.to_reference()
            encoded = json.dumps(
                preview_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            preview_payload["content_sha256"] = hashlib.sha256(encoded).hexdigest()
            try:
                return _PreparedGroundedReview(GroundedActionPreview.from_dict(preview_payload), text_field_expectation)
            except (TypeError, ValueError):
                return LiveControllerDecision("RECOVERY_REQUIRED", "preview_integrity_failed")

    def _validated_session_intent(self, payload, session):
        if isinstance(session, _FreshLiveSession):
            intent = FreshLearningIntent.from_dict(payload)
            reference = session.snapshot.source.reference()
            if (intent.session_id != session.snapshot.session_id
                    or intent.observation_id != session.snapshot.current_observation.observation_id
                    or intent.source_sha256 != reference["source_sha256"]):
                raise ValueError("fresh intent does not match the current session")
            from app.agent.learned_control_reference import revalidate_learned_control
            revalidate_learned_control(self._fresh_source_owner, session.snapshot.source, intent)
            return intent
        return validate_agent_intent_v1(payload, observation=session.snapshot.current_observation)

    def _validate_fresh_text_input(self, intent, supplied):
        from app.agent.text_parameters import text_parameter_reference

        if intent.semantic_action != "fill_field":
            return None if supplied is None else LiveControllerDecision("REJECTED", "unexpected_text_input")
        if (type(supplied) is not ResolvedTextParameters
                or text_parameter_reference(supplied.reviewed) != intent.text_parameters_ref):
            return LiveControllerDecision("REJECTED", "fresh_text_input_invalid")
        return supplied

    def _prepare_fresh_grounded_review(self, payload, *, target_process_id, text_input=None):
        if type(target_process_id) is not int or target_process_id <= 0:
            return LiveControllerDecision("REJECTED", "invalid_target_process_id")
        session_id = payload.get("session_id") if isinstance(payload, Mapping) else None
        with self._lock:
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if not isinstance(session, _FreshLiveSession):
                return LiveControllerDecision("REJECTED", "unknown_session")
            try:
                intent = self._validated_session_intent(payload, session)
            except (TypeError, ValueError):
                return LiveControllerDecision("REJECTED", "invalid_intent")
            text_input = self._validate_fresh_text_input(intent, text_input)
            if isinstance(text_input, LiveControllerDecision):
                return text_input
            if target_process_id != session.snapshot.target_process_id:
                return LiveControllerDecision("REJECTED", "invalid_target_process_id")
            try:
                existing = self._intent_claim_store.find_for_observation(
                    session_id=session_id, observation_id=intent.observation_id)
                if existing is not None or session.consumed or session_id in self._grounded_publications:
                    return LiveControllerDecision("REJECTED", "observation_consumed")
                from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source

                source = session.snapshot.source
                validate_fresh_runtime_owners(source, self._fresh_source_owner, self._observation_source,
                                             self._intent_claim_store.project_root)
                reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
                from app.agent.learned_control_reference import revalidate_learned_control, recognition_target_from_learned_control
                revalidate_learned_control(self._fresh_source_owner, source, intent)
                control_target = recognition_target_from_learned_control(intent.learned_control,
                    semantic_action=intent.semantic_action)
                bundle = self._observation_source.observe_for_action(
                    target_window_handle=session.snapshot.target_window_handle,
                    target_process_id=target_process_id, goal=intent.goal,
                    **({"control_target": control_target} if control_target is not None else {}),
                    **({"semantic_action": intent.semantic_action}
                       if intent.semantic_action in {'fill_field', 'open_detail', 'scroll_region'} else {}),
                    **({"scroll_parameters": intent.scroll_parameters} if intent.semantic_action == 'scroll_region' else {}))
                reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
                reference = source.reference()
                scope = {k: reference[k] for k in ("connection_id", "task_id", "segment_id")}
                capture_source = self._fresh_source_owner.archive.record(bundle.packet, **scope)
                expectation = None
                if text_input is not None:
                    from app.agent.fresh_learning_action_preview import _decision_and_risk

                    decision, _risk = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(),
                        intent, original=bundle.recognition_result(),
                        automatic_safety_interception=self._automatic_safety_interception)
                    field = self._observation_source.read_text_field(bundle=bundle,
                        target_field_id=text_input.reviewed.target_field_id, decision=decision,
                        **({} if self._automatic_safety_interception else {'automatic_safety_interception': False}))
                    expectation = prepare_text_field_expectation(field, text_input)
                preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
                    observation=session.snapshot.current_observation.to_dict(), intent=intent,
                    source_reference=reference, text_field_expectation=expectation,
                    automatic_safety_interception=self._automatic_safety_interception)
                self._read_fresh_preview_packet(session, preview)
                return _PreparedGroundedReview(preview, expectation)
            except (TypeError, ValueError, OSError) as error:
                from app.core.failure_diagnostics import log_failure_structure

                log_failure_structure(error, "fresh_preview")
                return LiveControllerDecision("REJECTED", "fresh_preview_evidence_rejected")

    def _read_fresh_preview_packet(self, session, preview):
        from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source

        source = session.snapshot.source
        validate_fresh_runtime_owners(source, self._fresh_source_owner, self._observation_source,
                                     self._intent_claim_store.project_root)
        reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
        data = preview.to_dict()
        from app.agent.learned_control_reference import revalidate_learned_control
        revalidate_learned_control(self._fresh_source_owner, source, FreshLearningIntent.from_dict(data['intent']))
        reference = source.reference()
        packet = self._fresh_source_owner.archive.read(data["capture_source"],
            **{k: reference[k] for k in ("connection_id", "task_id", "segment_id")})
        if packet.evidence() != data["observation_evidence"]:
            raise ValueError("fresh preview archived evidence changed")
        reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
        return packet

    def request_grounded_confirmation(
        self,
        payload: Mapping[str, object],
        *,
        target_process_id: int,
        text_input: ResolvedTextParameters | None = None,
    ) -> RuntimeIntentClaimSnapshot | LiveControllerDecision:
        """以同一控制器 owner 发布实际预检，不赋予执行权限。"""
        if type(target_process_id) is not int or target_process_id <= 0:
            return LiveControllerDecision("REJECTED", "invalid_target_process_id")
        session_id = payload.get("session_id") if isinstance(payload, Mapping) else None
        with self._lock:
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if session is None:
                return LiveControllerDecision("REJECTED", "unknown_session")
            try:
                intent = self._validated_session_intent(payload, session)
            except (TypeError, ValueError):
                return LiveControllerDecision("REJECTED", "invalid_intent")
            context = self._grounded_publications.get(session.snapshot.session_id)
            supplied = context.text_input if context is not None and text_input is None else text_input
            if isinstance(session, _FreshLiveSession):
                text_input = self._validate_fresh_text_input(intent, supplied)
            else:
                text_input = self._resolve_local_text_input(session, intent.action_id, supplied)
            if isinstance(text_input, LiveControllerDecision):
                return text_input
            if context is not None:
                if context.intent != intent or context.target_process_id != target_process_id or context.text_input != text_input:
                    return LiveControllerDecision(
                        "REJECTED", "grounded_confirmation_request_conflict"
                    )
            else:
                try:
                    existing = self._intent_claim_store.find_for_observation(
                        session_id=session.snapshot.session_id,
                        observation_id=session.snapshot.current_observation.observation_id,
                    )
                except RuntimeIntentClaimStoreError:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "claim_integrity_failed"
                    )
                if existing is not None:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED",
                        "grounded_confirmation_owner_unavailable",
                    )
                if session.consumed or session.confirmation is not None:
                    return LiveControllerDecision("REJECTED", "observation_consumed")
                prepared = self._prepare_grounded_review(
                    intent.model_dump(mode="json"),
                    target_process_id=target_process_id,
                    **({"text_input": text_input} if text_input is not None else {}),
                )
                if isinstance(prepared, LiveControllerDecision):
                    return prepared
                preview = prepared.preview
                context = _GroundedPublicationContext(
                    intent=intent,
                    preview=preview,
                    target_process_id=target_process_id,
                    text_input=text_input,
                    text_field_expectation=prepared.text_field_expectation,
                )
                # 先冻结不确定性上下文，再开始任何持久写。
                self._grounded_publications[session.snapshot.session_id] = context
                session.consumed = True
            try:
                if isinstance(session, _FreshLiveSession):
                    self._read_fresh_preview_packet(session, context.preview)
                claim = self._intent_claim_store.find_for_observation(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                )
                if claim is None:
                    if isinstance(session, _FreshLiveSession):
                        claim = self._intent_claim_store.claim_fresh_learning(
                            observation=session.snapshot.current_observation.to_dict(), intent=context.intent,
                            source_reference=session.snapshot.source.reference())
                    else:
                        claim = self._intent_claim_store.claim(
                            observation=session.snapshot.current_observation,
                            intent=context.intent, server_binding=self._server_binding_payload())
                if not self._grounded_claim_matches(
                    claim,
                    session=session,
                    context=context,
                    require_preview=False,
                ):
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "grounded_confirmation_integrity_failed"
                    )
                claim = self._intent_claim_store.mark_grounded_confirmation_pending(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                    preview=context.preview,
                )
                grounded = claim.grounded_confirmation
                if grounded is None:
                    raise RuntimeIntentClaimStoreError(
                        "grounded confirmation snapshot is missing"
                    )
                reloaded = self._intent_claim_store.get_for_grounded_confirmation(
                    confirmation_id=grounded.confirmation_id,
                )
                if reloaded != claim or not self._grounded_claim_matches(
                    reloaded,
                    session=session,
                    context=context,
                    require_preview=True,
                ):
                    raise RuntimeIntentClaimStoreError(
                        "grounded confirmation snapshot does not match publication"
                    )
                if reloaded.phase in {
                    "grounded_confirmation_denied",
                    "grounded_confirmation_closed",
                }:
                    try:
                        self._release_grounded_session(
                            session=session,
                            context=context,
                        )
                    except Exception:
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "grounded_confirmation_cleanup_required",
                        )
                return reloaded
            except (RuntimeIntentClaimStoreError, ValueError, OSError):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_persistence_failed"
                )

    def record_grounded_confirmation_decision(
        self,
        *,
        confirmation_id: str,
        decision: Literal["approved", "denied"],
    ) -> RuntimeIntentClaimSnapshot | LiveControllerDecision:
        """只记录 grounded 决定；批准在本阶段绝不派发。"""
        with self._lock:
            try:
                before = self._intent_claim_store.get_for_grounded_confirmation(
                    confirmation_id=confirmation_id,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "grounded_confirmation_integrity_failed",
                    confirmation_id,
                )
            context_pair = self._grounded_context_for_claim(before)
            if context_pair is None:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "grounded_confirmation_owner_unavailable",
                    confirmation_id,
                )
            session, context = context_pair
            if not self._grounded_claim_matches(
                before,
                session=session,
                context=context,
                require_preview=True,
            ):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "grounded_confirmation_integrity_failed",
                    confirmation_id,
                )
            try:
                if isinstance(session, _FreshLiveSession) and decision == "approved":
                    self._read_fresh_preview_packet(session, context.preview)
                decided = self._intent_claim_store.record_grounded_confirmation_decision(
                    confirmation_id=confirmation_id,
                    decision=decision,
                )
            except (RuntimeIntentClaimStoreError, ValueError, OSError) as exc:
                conflict = isinstance(exc, RuntimeIntentClaimStoreError) and "conflict" in str(exc)
                reason = (
                    "grounded_confirmation_decision_conflict"
                    if conflict
                    else "grounded_confirmation_integrity_failed"
                )
                return LiveControllerDecision(
                    "REJECTED" if conflict else "RECOVERY_REQUIRED",
                    reason,
                    confirmation_id,
                )
            if decided.phase in {
                "grounded_confirmation_denied",
                "grounded_confirmation_closed",
            }:
                try:
                    self._release_grounded_session(
                        session=session,
                        context=context,
                    )
                    if isinstance(decided, RuntimeFreshLearningClaimSnapshot):
                        grounded = decided.grounded_confirmation
                        self._released_fresh_confirmations[decided.observation.session_id] = (
                            grounded.confirmation_id, decided.claim_content_sha256,
                            grounded.request_content_sha256, decided.phase,
                        )
                except Exception:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED",
                        "grounded_confirmation_cleanup_required",
                        confirmation_id,
                    )
            return decided

    def get_local_grounded_text_input(self, *, confirmation_id: str) -> ResolvedTextParameters:
        with self._lock:
            claim = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
            context_pair = self._grounded_context_for_claim(claim)
            if (claim.grounded_confirmation is None or not claim.grounded_confirmation.owner_is_current
                    or claim.phase not in {"grounded_confirmation_pending", "grounded_confirmation_approved"}
                    or context_pair is None):
                raise ValueError("text preview is not owned by this controller")
            session, context = context_pair
            if not self._grounded_claim_matches(claim, session=session, context=context, require_preview=True):
                raise ValueError("text preview binding changed")
            validate_local_text_preview(claim.grounded_confirmation.preview.to_dict(), context.text_input)
            return context.text_input

    def get_local_grounded_text_field_expectation(self, *, confirmation_id: str) -> TextFieldExpectation:
        with self._lock:
            parameters = self.get_local_grounded_text_input(confirmation_id=confirmation_id)
            claim = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
            pair = self._grounded_context_for_claim(claim)
            expected = pair[1].text_field_expectation if pair is not None else None
            if (type(expected) is not TextFieldExpectation or expected.parameters != parameters
                    or expected.to_reference() != claim.grounded_confirmation.preview.to_dict().get("text_field_expectation_ref")):
                raise ValueError("text field expectation is not owned by this controller")
            return expected

    def get_local_grounded_confirmation(self, *, confirmation_id: str):
        """原生附加只读取本控制器持有且原图仍可核验的待确认动作。"""
        with self._lock:
            self.get_local_grounded_image(confirmation_id=confirmation_id)
            return self._intent_claim_store.get_for_grounded_confirmation(
                confirmation_id=confirmation_id,
            )

    def get_local_grounded_image(self, *, confirmation_id: str) -> bytes:
        """只读返回当前 controller 确切持有的 grounded 预览 PNG。"""
        with self._lock:
            try:
                claim = self._intent_claim_store.get_for_grounded_confirmation(
                    confirmation_id=confirmation_id,
                )
            except RuntimeIntentClaimStoreError as exc:
                raise ValueError("grounded image confirmation is unavailable") from exc
            grounded = claim.grounded_confirmation
            context_pair = self._grounded_context_for_claim(claim)
            if (
                grounded is None
                or grounded.owner_is_current is not True
                or claim.phase not in {
                    "grounded_confirmation_pending",
                    "grounded_confirmation_approved",
                }
                or context_pair is None
            ):
                raise ValueError("grounded image is not owned by this controller")
            session, context = context_pair
            if not self._grounded_claim_matches(
                claim,
                session=session,
                context=context,
                require_preview=True,
            ):
                raise ValueError("grounded image confirmation binding changed")
            preview = grounded.preview.to_dict()
            if isinstance(session, _FreshLiveSession):
                return self._read_fresh_preview_packet(session, grounded.preview).png_bytes
            grounding = preview.get("grounding_preview")
            if not isinstance(grounding, Mapping):
                raise ValueError("grounded image preview binding is invalid")
            reader = getattr(self._observation_source, "read_cached_grounded_image", None)
            if not callable(reader):
                raise ValueError("grounded image cache is unavailable")
            try:
                image_bytes = reader(
                    session_id=preview["session_id"],
                    asset_id=grounding["asset_id"],
                    asset_content_sha256=grounding["asset_content_sha256"],
                    target_window_handle=preview["target_window_handle"],
                    target_process_id=preview["target_process_id"],
                    capture_lineage=grounding["capture_lineage"],
                )
            except Exception as exc:
                raise ValueError("grounded image material is unavailable") from exc
            if type(image_bytes) is not bytes or not image_bytes:
                raise ValueError("grounded image material is invalid")
            return bytes(image_bytes)

    def consume_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        """批准后以一次 fresh bundle 进入既有唯一派发尾部。"""
        if isinstance(self._binding, ServerFreshLearningBinding):
            return self._consume_fresh_grounded_confirmation(confirmation_id=confirmation_id)
        with self._lock:
            try:
                claim = self._intent_claim_store.get_for_grounded_confirmation(
                    confirmation_id=confirmation_id
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_integrity_failed", confirmation_id
                )
            if claim.phase == "terminal":
                try:
                    receipt = self._intent_claim_store.load_terminal_receipt(
                        session_id=claim.observation.session_id,
                        observation_id=claim.observation.observation_id,
                    )
                except RuntimeIntentClaimStoreError:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "receipt_integrity_failed", confirmation_id
                    )
                recovery = self._grounded_recovery_sessions.get(confirmation_id)
                local = self._grounded_context_for_claim(claim)
                if recovery is not None:
                    if (
                        recovery.snapshot.current_observation != claim.observation
                        or recovery.snapshot.workflow != claim.observation.workflow
                        or recovery.snapshot.target_window_handle
                        != claim.server_binding.target_window_handle
                        or recovery.grounded_consume != claim.grounded_consume
                    ):
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "grounded_confirmation_integrity_failed",
                            confirmation_id,
                        )
                    try:
                        self._release_window_lease(recovery.window_lease)
                    except Exception:
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "grounded_confirmation_cleanup_required",
                            confirmation_id,
                        )
                    self._grounded_recovery_sessions.pop(confirmation_id, None)
                elif local is not None:
                    session, _context = local
                    try:
                        self._release_window_lease(session.window_lease)
                    except Exception:
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "grounded_confirmation_cleanup_required",
                            confirmation_id,
                        )
                    self._sessions.pop(session.snapshot.session_id, None)
                    self._grounded_publications.pop(session.snapshot.session_id, None)
                return receipt
            if claim.phase == "verification_pending":
                return self._recover_verification_pending(claim)
            if claim.phase == "dispatch_started":
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "dispatch_indeterminate", confirmation_id
                )
            if claim.phase == "grounded_confirmation_consume_started":
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_consume_indeterminate", confirmation_id
                )
            if claim.phase == "grounded_confirmation_approved":
                checked = self.record_grounded_confirmation_decision(
                    confirmation_id=confirmation_id,
                    decision="approved",
                )
                if isinstance(checked, LiveControllerDecision):
                    return checked
                claim = checked
                if claim.phase == "grounded_confirmation_closed":
                    return LiveControllerDecision(
                        "REJECTED", "grounded_confirmation_stale", confirmation_id
                    )
            grounded = claim.grounded_confirmation
            if grounded is None or claim.phase != "grounded_confirmation_approved":
                return LiveControllerDecision(
                    "REJECTED", "grounded_confirmation_not_approved", confirmation_id
                )
            context_pair = self._grounded_context_for_claim(claim)
            if context_pair is None or grounded.owner_is_current is not True:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_owner_unavailable", confirmation_id
                )
            session, context = context_pair
            if not self._grounded_claim_matches(
                claim, session=session, context=context, require_preview=True
            ):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_integrity_failed", confirmation_id
                )
            text_expectation = context.text_field_expectation
            if context.preview.to_dict()["review_selection"]["semantic_action"] == "fill_field":
                # 旧只读预览或丢失本地原值时，不能用持久摘要恢复输入权限。
                if (
                    type(text_expectation) is not TextFieldExpectation
                    or text_expectation.parameters != context.text_input
                    or text_expectation.to_reference() != context.preview.to_dict().get("text_field_expectation_ref")
                ):
                    return LiveControllerDecision("REJECTED", "text_execution_not_ready", confirmation_id)
            projection = self._capture_current_resolution(
                session=session, expected_process_id=context.target_process_id
            )
            if isinstance(projection, _CurrentProjectionFailure):
                if not projection.recovery_required:
                    return self._close_grounded_stale_for_consume(
                        session=session, confirmation_id=confirmation_id
                    )
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", projection.reason_code, confirmation_id
                )
            try:
                review_selection = select_transition_for_review(
                    session.asset,
                    projection.state_resolution,
                    transition_id=context.intent.action_id,
                    current_observation=projection.current,
                )
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "transition_selection_failed", confirmation_id
                )
            if review_selection.get("status") != "selected":
                return self._close_grounded_stale_for_consume(
                    session=session, confirmation_id=confirmation_id
                )
            review_gate = getattr(self._gate, "evaluate_review", None)
            if not callable(review_gate):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "review_gate_unavailable", confirmation_id
                )
            reviewed = self._ground_selected_current(
                session=session,
                current=projection.current,
                selection=review_selection,
                validator=lambda selected, evidence, gate: validate_review_grounding_preview(
                    session.asset,
                    selected,
                    evidence,
                    gate,
                    policy=self._grounding_policy,
                ),
                gate_evaluator=review_gate,
            )
            if isinstance(reviewed, _GroundingFailure):
                if reviewed.recovery_required:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", reviewed.reason_code, confirmation_id
                    )
                return self._close_grounded_stale_for_consume(
                    session=session, confirmation_id=confirmation_id
                )
            freshness = reviewed.visibility.get("freshness")
            if isinstance(freshness, Mapping) and freshness.get("full_frame_status") == "changed":
                return self._close_grounded_stale_for_consume(
                    session=session, confirmation_id=confirmation_id
                )
            fresh_text_expectation = None
            if text_expectation is not None:
                try:
                    fresh_field = self._observation_source.read_text_field(
                        session_id=session.snapshot.session_id, current_observation=projection.current,
                        selection=reviewed.selection, grounding=reviewed.grounding,
                    )
                    validate_text_field_precondition(text_expectation, fresh_field)
                    fresh_text_expectation = prepare_text_field_expectation(fresh_field, text_expectation.parameters)
                except (AttributeError, TypeError, ValueError, OSError):
                    return self._close_grounded_stale_for_consume(session=session, confirmation_id=confirmation_id)
            fresh_preview = self._make_grounded_preview(
                session=session,
                intent=context.intent,
                projection=projection,
                reviewed=reviewed,
                text_field_expectation=fresh_text_expectation,
            )
            try:
                validate_fresh_preview(context.preview, fresh_preview)
                sealed = self._intent_claim_store._get_grounded_execution_evidence(
                    confirmation_id=confirmation_id,
                    fresh_preview=fresh_preview,
                )
            except (RuntimeGroundedConsumeError, RuntimeIntentClaimStoreError):
                return self._close_grounded_stale_for_consume(
                    session=session, confirmation_id=confirmation_id
                )
            try:
                execution_selection = _select_grounded_confirmed_transition(
                    session.asset,
                    projection.state_resolution,
                    transition_id=context.intent.action_id,
                    grounded_evidence=sealed,
                    current_observation=projection.current,
                )
                execution_gate = dict(
                    self._gate.evaluate(
                        selection=execution_selection,
                        grounding=reviewed.grounding,
                        **reviewed.gate_context,
                    )
                )
                execution_validation = _validate_grounded_current_grounding(
                    session.asset,
                    execution_selection,
                    reviewed.grounding,
                    execution_gate,
                    grounded_evidence=sealed,
                    policy=self._grounding_policy,
                )
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_execution_validation_failed", confirmation_id
                )
            if (
                execution_selection.get("status") != "selected"
                or execution_validation.get("status") != "validated"
            ):
                return self._close_grounded_stale_for_consume(
                    session=session, confirmation_id=confirmation_id
                )
            gate_ref = self._first_ref(execution_gate.get("evidence_refs"), "gate")
            try:
                consumed = self._intent_claim_store.begin_grounded_confirmation_consume(
                    confirmation_id=confirmation_id,
                    fresh_preview=fresh_preview,
                    current_observation=projection.current,
                    selection=execution_selection,
                    grounding=reviewed.grounding,
                    execution_gate=execution_gate,
                    gate_decision_ref=gate_ref,
                    target_process_id=projection.projected.target_process_id,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_consume_persistence_failed", confirmation_id
                )
            consume = consumed.grounded_consume
            if consume is None or consumed.phase != "grounded_confirmation_consume_started":
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_consume_integrity_failed", confirmation_id
                )
            session.grounded_consume = consume
            result = self._dispatch_validated_grounding(
                session=session,
                intent=context.intent,
                text_field_expectation=fresh_text_expectation,
                observation=session.snapshot.current_observation,
                current=projection.current,
                projected=projection.projected,
                grounded=_GroundedSelection(
                    selection=execution_selection,
                    grounding=reviewed.grounding,
                    gate=execution_gate,
                    validation=execution_validation,
                    click_point=reviewed.click_point,
                    target_bbox=reviewed.target_bbox,
                    gate_context=reviewed.gate_context,
                    visibility=reviewed.visibility,
                ),
            )
            if isinstance(result, LiveControllerDecision):
                return result
            try:
                receipt = self._intent_claim_store.persist_grounded_terminal(
                    confirmation_id=confirmation_id,
                    consume_content_sha256=consume.content_sha256,
                    receipt=result.receipt,
                    backend_receipt=result.backend_receipt,
                    verification_evidence=result.verification_evidence,
                    next_observation=result.next_observation,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "receipt_persistence_failed", confirmation_id
                )
            try:
                self._release_window_lease(session.window_lease)
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_cleanup_required", confirmation_id
                )
            self._sessions.pop(session.snapshot.session_id, None)
            self._grounded_publications.pop(session.snapshot.session_id, None)
            return receipt

    def _make_grounded_preview(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        projection: _CurrentProjection,
        reviewed: _GroundedSelection,
        text_field_expectation: TextFieldExpectation | None = None,
    ) -> GroundedActionPreview:
        payload: dict[str, Any] = {
            "contract_version": "grounded_action_preview_v1",
            "status": "prepared",
            "review_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "grants_action_authority": False,
            "session_id": session.snapshot.session_id,
            "observation_id": session.snapshot.current_observation.observation_id,
            "intent_id": intent.intent_id,
            "workflow": session.snapshot.workflow.model_dump(mode="json"),
            "target_window_handle": session.snapshot.target_window_handle,
            "target_process_id": projection.projected.target_process_id,
            "current_observation": projection.projected.agent_observation.model_dump(mode="json"),
            "review_selection": deepcopy(reviewed.selection),
            "grounding_preview": deepcopy(reviewed.validation),
        }
        if text_field_expectation is not None:
            payload["text_execution_ref"] = text_execution_reference(text_field_expectation.parameters)
            payload["text_field_expectation_ref"] = text_field_expectation.to_reference()
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        payload["content_sha256"] = hashlib.sha256(encoded).hexdigest()
        return GroundedActionPreview.from_dict(payload)

    def _dispatch_command_once(self, command, *, authority):
        """两种来源共享唯一输入调用；未知结果不可触发再次输入。"""
        try:
            receipt = self._backend.dispatch(command, authority=authority)
        except Exception:
            return BackendDispatchReceipt(
                receipt_ref=f"backend-receipt:exception:{uuid4().hex}",
                status="indeterminate", reason_code="backend_result_lost")
        if not self._is_valid_backend_receipt(receipt):
            return BackendDispatchReceipt(
                receipt_ref=f"backend-receipt:invalid:{uuid4().hex}",
                status="indeterminate", reason_code="backend_result_lost")
        return receipt

    def _pin_fresh_learning_capture(self, session, packet):
        archive = self._fresh_source_owner.segments.capture_archive
        evidence = packet.evidence()
        capture = evidence["capture"]
        result = archive.pin_current_capture(
            runtime_session_id=session.snapshot.session_id,
            capture_id=capture["capture_id"], screenshot_sha256=capture["screenshot_sha256"],
            viewport_size=capture["viewport_size"],
            fresh_source_sha256=session.snapshot.source.reference()["source_sha256"],
            target_window_handle=evidence["target"]["window_handle"],
            target_process_id=evidence["target"]["process_id"], png_bytes=packet.png_bytes)
        if result is None:
            raise ValueError("fresh learning capture has no active recorder binding")

    def _finish_fresh_terminal(self, claim, confirmation_id):
        from app.agent_link.contracts import AgentLinkError

        try:
            receipt = self._intent_claim_store.load_terminal_receipt(
                session_id=claim.observation.session_id, observation_id=claim.observation.observation_id)
        except (ValueError, OSError):
            return LiveControllerDecision("RECOVERY_REQUIRED", "receipt_integrity_failed", confirmation_id)
        pair = self._grounded_context_for_claim(claim)
        if pair is not None:
            self._release_grounded_session(session=pair[0], context=pair[1])
        try:
            reference = self._binding.source.reference()
            synced = self._fresh_source_owner.sync_actions(
                **{key: reference[key] for key in ("connection_id", "task_id", "segment_id")})
            if synced.get("status") != "synchronized":
                return LiveControllerDecision("RECOVERY_REQUIRED", "learning_graph_pending", confirmation_id)
        except (AgentLinkError, ValueError, OSError):
            return LiveControllerDecision("RECOVERY_REQUIRED", "learning_graph_sync_failed", confirmation_id)
        return receipt

    def _check_fresh_visibility_capture(self, session, preview, *, navigation_scope=None, navigation_approval=None):
        """被动重拍核对当前像素；不把同 HWND 的命中测试当作画面新鲜度。"""
        from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source
        from app.agent.fresh_capture_stability import check_fresh_capture_pixels

        data = preview.to_dict()
        def validate_source():
            from app.agent.learned_control_reference import revalidate_learned_control
            reload_fresh_learning_runtime_source(self._fresh_source_owner, session.snapshot.source)
            revalidate_learned_control(self._fresh_source_owner, session.snapshot.source,
                                      FreshLearningIntent.from_dict(data['intent']))
        if navigation_scope is not None or navigation_approval is not None:
            # 始终对照最初批准帧，不能把前一次容许的小变化累积成新的基准。
            validate_source()
            passive = self._observation_source.observe_with_uia(
                target_window_handle=session.snapshot.target_window_handle,
                target_process_id=session.snapshot.target_process_id)
            packet = passive.packet
            current = packet.evidence()['capture']
            before = data['observation_evidence']['capture']
            if (current['capture_id'] == before['capture_id']
                    or current['capture_started_ns'] <= before['observed_at_ns']):
                raise ValueError('navigation visibility requires a newer passive capture')
            validate_source()
            if navigation_scope is None:
                from app.agent.fresh_capture_stability import require_exact_fresh_capture, TransientCapturePixelsChanged
                try:
                    require_exact_fresh_capture(original=data['observation_evidence'],
                        current=packet.evidence(), png_bytes=packet.png_bytes)
                except ValueError:
                    # 类型化证明重新检查所有绑定，仅接纳已证明的远端工具栏/像素变化。
                    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
                    navigation_scope = NavigationVisualStabilityScope(*navigation_approval)
                else:
                    return {'capture_id': current['capture_id'], 'screenshot_sha256': current['screenshot_sha256'],
                        'policy': 'exact_pixels'}
            proof = navigation_scope.validate(current_evidence=packet.evidence(), current_png_bytes=packet.png_bytes,
                                              current_uia_snapshot=passive.uia_snapshot())
            reference = self._binding.source.reference()
            capture_source = self._fresh_source_owner.archive.record(packet,
                **{key: reference[key] for key in ('connection_id', 'task_id', 'segment_id')})
            return {'capture_source': capture_source, 'proof': proof}
        return check_fresh_capture_pixels(original=data["observation_evidence"],
            observe=lambda: self._observation_source.observe(
                target_window_handle=session.snapshot.target_window_handle,
                target_process_id=session.snapshot.target_process_id, goal=None),
            validate_source=validate_source,
            allow_transient_retry=data["intent"]["semantic_action"] == "fill_field")

    def _consume_fresh_grounded_confirmation(self, *, confirmation_id):
        from app.agent.desktop_backend import FreshExecutionSourceLineage
        from app.agent.fresh_learning_action_contracts import FreshLearningClaimObservation, payload_sha256
        from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview
        from app.agent.fresh_learning_recording import build_fresh_learning_before, fresh_preview_geometry
        from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source
        from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
        from app.agent_link.contracts import AgentLinkError

        with self._lock:
            try:
                claim = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
            except (ValueError, OSError):
                return LiveControllerDecision("RECOVERY_REQUIRED", "grounded_confirmation_integrity_failed", confirmation_id)
            if (not isinstance(claim, RuntimeFreshLearningClaimSnapshot)
                    or claim.observation.to_dict()["source"] != self._binding.source.reference()):
                return LiveControllerDecision("REJECTED", "fresh_learning_source_mismatch", confirmation_id)
            if claim.phase == "terminal":
                return self._finish_fresh_terminal(claim, confirmation_id)
            if claim.phase in {"dispatch_started", "grounded_confirmation_consume_started"}:
                return LiveControllerDecision("RECOVERY_REQUIRED", "fresh_dispatch_indeterminate", confirmation_id)
            if claim.phase != "grounded_confirmation_approved":
                return LiveControllerDecision("REJECTED", "grounded_confirmation_not_approved", confirmation_id)
            checked = self.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="approved")
            if isinstance(checked, LiveControllerDecision):
                return checked
            claim = checked
            if claim.phase != "grounded_confirmation_approved":
                return LiveControllerDecision("REJECTED", "grounded_confirmation_stale", confirmation_id)
            pair = self._grounded_context_for_claim(claim)
            if pair is None or claim.grounded_confirmation.owner_is_current is not True:
                return LiveControllerDecision("RECOVERY_REQUIRED", "grounded_confirmation_owner_unavailable", confirmation_id)
            session, context = pair
            if (not isinstance(session, _FreshLiveSession)
                    or not self._grounded_claim_matches(claim, session=session, context=context, require_preview=True)):
                return LiveControllerDecision("RECOVERY_REQUIRED", "grounded_confirmation_integrity_failed", confirmation_id)
            recorder = self._action_learning_recorder
            segments = self._fresh_source_owner.segments
            source = session.snapshot.source
            reference = source.reference()
            scope = {key: reference[key] for key in ("connection_id", "task_id", "segment_id")}
            try:
                if recorder is None or recorder is not segments.recorder:
                    return LiveControllerDecision("REJECTED", "fresh_learning_recording_required", confirmation_id)
                segment = segments.get(**scope)
                if not any(child["runtime_session_id"] == session.snapshot.session_id and child["phase"] == "bound"
                           for child in segment["children"]):
                    return LiveControllerDecision("REJECTED", "fresh_learning_binding_required", confirmation_id)
                approved_packet = self._read_fresh_preview_packet(session, context.preview)
                from app.agent.automatic_safety_policy import preview_automatic_safety_interception, preview_action_selection
                strict = preview_automatic_safety_interception(context.preview)
                text_visual_scope, text_visual_proof = None, None
                navigation_scope, navigation_proof, navigation_visibility = None, None, None
                if context.intent.semantic_action == "fill_field":
                    from app.agent.text_visual_stability import TextVisualStabilityScope
                    approved_field = self.get_local_grounded_text_field_expectation(confirmation_id=confirmation_id)
                    text_visual_scope = TextVisualStabilityScope(expectation=approved_field,
                        original_evidence=approved_packet.evidence(), original_png_bytes=approved_packet.png_bytes,
                        original_uia_snapshot=context.preview.to_dict()['uia_snapshot'],
                        automatic_safety_interception=strict)
                previous_capture = approved_packet.evidence()['capture']
                # 填写的最终可见性门再次识别、分类并读取字段，始终对照最初批准帧，避免累计漂移。
                for _ in range(2 if text_visual_scope is not None else 1):
                    from app.agent.learned_control_reference import revalidate_learned_control, recognition_target_from_learned_control
                    revalidate_learned_control(self._fresh_source_owner, source, context.intent)
                    control_target = recognition_target_from_learned_control(context.intent.learned_control,
                        semantic_action=context.intent.semantic_action)
                    bundle = self._observation_source.observe_for_action(
                        target_window_handle=session.snapshot.target_window_handle,
                        target_process_id=session.snapshot.target_process_id, goal=context.intent.goal,
                        **({"control_target": control_target} if control_target is not None else {}),
                        **({"semantic_action": "fill_field", "expected_visual": approved_packet.evidence(),
                            "text_visual_scope": text_visual_scope} if text_visual_scope is not None else
                           {"semantic_action": "open_detail"} if context.intent.semantic_action == 'open_detail' else
                           {"semantic_action": "scroll_region", "scroll_parameters": context.intent.scroll_parameters}
                           if context.intent.semantic_action == 'scroll_region' else {}))
                    current_capture = bundle.packet.evidence()['capture']
                    if (current_capture['capture_id'] == previous_capture['capture_id']
                            or current_capture['capture_started_ns'] <= previous_capture['observed_at_ns']):
                        raise ValueError('fresh text visibility requires a newer capture')
                    previous_capture = current_capture
                    reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
                    capture_source = self._fresh_source_owner.archive.record(bundle.packet, **scope)
                    text_expectation = None
                    if text_visual_scope is not None:
                        from app.agent.fresh_learning_action_preview import _decision_and_risk
                        text_visual_proof = text_visual_scope.validate(current_evidence=bundle.packet.evidence(),
                            current_png_bytes=bundle.packet.png_bytes, current_uia_snapshot=bundle.uia_snapshot())
                        decision, _risk = _decision_and_risk(bundle.packet.evidence(), bundle.uia_snapshot(),
                            context.intent, original=bundle.recognition_result(), automatic_safety_interception=strict)
                        current_field = self._observation_source.read_text_field(bundle=bundle,
                            target_field_id=context.text_input.reviewed.target_field_id, decision=decision,
                            **({} if strict else {'automatic_safety_interception': False}))
                        validate_text_field_precondition(approved_field, current_field)
                        text_expectation = prepare_text_field_expectation(current_field, context.text_input)
                    fresh = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
                        observation=session.snapshot.current_observation.to_dict(), intent=context.intent,
                        source_reference=reference, text_field_expectation=text_expectation,
                        automatic_safety_interception=strict)
                    try:
                        validate_fresh_execution_preview(context.preview, fresh, text_visual_proof=text_visual_proof)
                    except ValueError:
                        if text_visual_scope is not None or strict and context.intent.semantic_action != 'open_detail':
                            raise
                        from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
                        navigation_scope = NavigationVisualStabilityScope(approved_preview=context.preview,
                            original_png_bytes=approved_packet.png_bytes)
                        navigation_proof = navigation_scope.validate(current_evidence=bundle.packet.evidence(),
                            current_png_bytes=bundle.packet.png_bytes, current_uia_snapshot=bundle.uia_snapshot())
                        validate_fresh_execution_preview(context.preview, fresh,
                            navigation_visual_proof=navigation_proof)
                self._read_fresh_preview_packet(session, fresh)
                geometry = fresh_preview_geometry(fresh)
                data = fresh.to_dict()
                capture = data["observation_evidence"]["capture"]
                box = geometry["bbox"]
                if text_visual_scope is None:
                    visibility_result = self._check_fresh_visibility_capture(session, fresh, navigation_scope=navigation_scope,
                        navigation_approval=(context.preview, approved_packet.png_bytes)
                        if not strict or context.intent.semantic_action == 'open_detail' else None)
                    if isinstance(visibility_result, dict) and 'proof' in visibility_result:
                        navigation_visibility = visibility_result
                visibility = self._window_visibility_checker.check(
                    session_id=session.snapshot.session_id, capture_lineage=capture,
                    target_window_handle=geometry["target_window_handle"],
                    click_point=tuple(geometry["click_point"]),
                    target_bbox=(box["x"], box["y"], box["w"], box["h"]))
                if (not isinstance(visibility, Mapping)
                        or visibility.get("bound_window_handle") != session.snapshot.target_window_handle
                        or not isinstance(visibility.get("point_visibility"), Mapping)
                        or visibility["point_visibility"].get("allowed") is not True):
                    raise ValueError("fresh target is not currently visible")
                self._pin_fresh_learning_capture(session, bundle.packet)
                reload_fresh_learning_runtime_source(self._fresh_source_owner, source)
                from app.agent.learned_control_reference import revalidate_learned_control
                revalidate_learned_control(self._fresh_source_owner, source, context.intent)
                scroll_dispatch, scroll_before = None, None
                if context.intent.semantic_action == "scroll_region":
                    from app.agent.fresh_scroll_region import fresh_scroll_dispatch, read_fresh_scroll_capture
                    scroll_dispatch = fresh_scroll_dispatch(context.intent, data["risk"], data["observation_evidence"])
                    scroll_before = read_fresh_scroll_capture(self._observation_source,
                        self._fresh_source_owner.archive, bundle.packet, scope)
            except (ValueError, TypeError, OSError, AgentLinkError):
                return self._close_grounded_stale_for_consume(session=session, confirmation_id=confirmation_id)
            try:
                claim = self._intent_claim_store.begin_fresh_confirmation_consume(
                    session_id=session.snapshot.session_id, observation_id=context.intent.observation_id,
                    fresh_preview=fresh, text_visual_proof=text_visual_proof, navigation_visual_proof=navigation_proof,
                    navigation_visibility=navigation_visibility)
                before = build_fresh_learning_before(claim)
                if recorder.record_before(runtime_session_id=session.snapshot.session_id,
                    observation_id=context.intent.observation_id, payload=before) is None:
                    raise ValueError("fresh learning binding disappeared before dispatch")
                lineage = {key: value for key, value in before["source_lineage"].items() if key != "source_kind"}
                candidate_id = preview_action_selection(data)["selected_candidate_id"]
                text_dispatch, text_guard = None, None
                if text_expectation is not None:
                    text_dispatch = TextDispatchParameters(parameters=text_expectation.parameters,
                        target_bbox=tuple(box[key] for key in ("x", "y", "w", "h")),
                        viewport_size=tuple(capture["viewport_size"][key] for key in ("width", "height")))
                    text_guard = TextInputGuard(expectation=text_expectation,
                        read_current=lambda: self._observation_source.read_text_field(bundle=bundle,
                            target_field_id=text_expectation.before.identity.target_field_id,
                            decision=data["pre_click_decision"], require_keyboard_focus=True,
                            **({} if strict else {'automatic_safety_interception': False})))
                command = DesktopDispatchCommand(
                    semantic_action=context.intent.semantic_action, capture_id=capture["capture_id"],
                    candidate_id=candidate_id, click_point=tuple(geometry["click_point"]),
                    target_window_handle=geometry["target_window_handle"],
                    scroll=scroll_dispatch, text_input=text_dispatch, text_guard=text_guard,
                    target_bbox=tuple(box[key] for key in ("x", "y", "w", "h")))
                authority = _mint_execution_authority(
                    session_id=session.snapshot.session_id, observation_id=context.intent.observation_id,
                    intent_id=context.intent.intent_id, source_lineage=FreshExecutionSourceLineage(**lineage),
                    action_evidence_sha256=fresh.content_sha256, semantic_action=context.intent.semantic_action,
                    capture_id=capture["capture_id"], candidate_id=candidate_id,
                    click_point=tuple(geometry["click_point"]), target_window_handle=geometry["target_window_handle"],
                    gate_decision_ref=before["gate_decision_ref"], scroll=scroll_dispatch, text_input=text_dispatch, text_guard=text_guard,
                    target_bbox=command.target_bbox)
                from app.agent.learned_control_reference import revalidate_learned_control
                revalidate_learned_control(self._fresh_source_owner, source, context.intent)
                self._intent_claim_store.mark_fresh_dispatch_started(
                    session_id=session.snapshot.session_id, observation_id=context.intent.observation_id)
            except (ValueError, TypeError, OSError):
                return LiveControllerDecision("RECOVERY_REQUIRED", "fresh_dispatch_preparation_failed", confirmation_id)
            backend_receipt = self._dispatch_command_once(command, authority=authority)
            next_observation = None
            actual_field = None
            scroll_after = None
            if backend_receipt.status == "dispatched":
                outcome, reason = "ACTION_RECORDED", "backend_dispatched"
                try:
                    after = observe_fresh_runtime_session(source=source, source_owner=self._fresh_source_owner,
                        observation_owner=self._observation_source, session_id=session.snapshot.session_id)
                    after_data = after.current_observation.to_dict()
                    after_capture = after_data["capture"]
                    if (after_capture["capture_clock_id"] != capture["capture_clock_id"]
                            or after_capture["capture_id"] == capture["capture_id"]
                            or after_capture["capture_started_ns"] <= capture["observed_at_ns"]):
                        raise ValueError("fresh after observation is not newer than dispatch capture")
                    self._pin_fresh_learning_capture(session, after.current_observation.packet)
                    next_observation = FreshLearningClaimObservation.from_dict(after_data)
                    if scroll_dispatch is not None:
                        try:
                            scroll_after = read_fresh_scroll_capture(self._observation_source,
                                self._fresh_source_owner.archive, after.current_observation.packet, scope)
                        except (ValueError, TypeError, OSError):
                            # 动作已派发；空间核验失败保持未知，不重复滚动。
                            scroll_after = None
                    if text_expectation is not None:
                        try:
                            actual_field = self._observation_source.read_text_field_after(
                                packet=after.current_observation.packet, expectation=text_expectation)
                        except (ValueError, TypeError, OSError):
                            # 新截图仍有效；字段读取失败不能伪装成填写成功，也不能重试输入。
                            actual_field = None
                except (ValueError, TypeError, OSError):
                    outcome, reason = "OBSERVATION_FAILED", "after_observation_unavailable"
            elif backend_receipt.status == "not_started":
                outcome, reason = "EXECUTION_FAILED", "backend_not_started"
            else:
                outcome, reason = "EXECUTION_UNKNOWN", "backend_result_lost"
            text_evidence = {}
            effect_status = "not_verified"
            if scroll_dispatch is not None:
                from app.agent.fresh_scroll_region import fresh_scroll_proof
                text_evidence = {"scroll_verification": fresh_scroll_proof(scroll_dispatch.parameters,
                    scroll_dispatch.target_bbox, scroll_before, scroll_after)}
            if text_expectation is not None:
                from app.agent.text_field_evidence import verify_text_field_result

                proof = verify_text_field_result(text_expectation, actual_field)
                text_evidence = {"text_parameters_ref": context.intent.text_parameters_ref,
                    "text_field_verification": proof}
                effect_status = proof["status"]
            receipt = RuntimeFreshResultReceipt.from_dict({
                "contract_version": "runtime_fresh_result_receipt_v1" if strict else "runtime_fresh_result_receipt_v2",
                "receipt_id": "fresh-receipt." + uuid4().hex,
                "issued_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "session_id": session.snapshot.session_id, "observation_id": context.intent.observation_id,
                "intent_id": context.intent.intent_id, "source_sha256": reference["source_sha256"],
                "action": before["action"], "outcome": outcome, "reason_code": reason,
                "attempt_count": 1, "gate_status": "allowed" if strict else "manual_confirmed", "dispatch_status": backend_receipt.status,
                "effect_status": effect_status, "destination_status": "not_evaluated",
                "evidence": {**lineage, "capture_id": capture["capture_id"],
                    "candidate_ref": before["candidate_ref"], "gate_decision_ref": before["gate_decision_ref"],
                    **text_evidence},
                "next_observation_id": next_observation.observation_id if next_observation is not None else None,
                "artifact_is_authorization": False})
            try:
                self._intent_claim_store.persist_fresh_terminal(receipt, backend_receipt,
                    next_observation=next_observation)
                terminal = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
            except (ValueError, TypeError, OSError):
                return LiveControllerDecision("RECOVERY_REQUIRED", "fresh_receipt_persistence_failed", confirmation_id)
            return self._finish_fresh_terminal(terminal, confirmation_id)

    def release_local_fresh_recovery(self, *, confirmation_id: str) -> RuntimeFreshLearningClaimSnapshot:
        """仅释放停止后的本地所有者；保留未知持久结果，不补回执或重试输入。"""
        with self._lock:
            claim = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id)
            if (not isinstance(self._binding, ServerFreshLearningBinding)
                    or type(claim) is not RuntimeFreshLearningClaimSnapshot
                    or claim.phase not in {"grounded_confirmation_consume_started", "dispatch_started"}
                    or claim.recovery_required is not True or claim.grounded_consume is None
                    or claim.grounded_confirmation is None
                    or claim.grounded_confirmation.owner_is_current is not True
                    or claim.observation.to_dict()["source"] != self._binding.source.reference()):
                raise ValueError("fresh recovery owner or durable phase cannot be verified")
            session_id = claim.observation.session_id
            if session_id in self._sessions:
                result = self.cancel_grounded_review(session_id=session_id)
                if (not isinstance(result, LiveControllerDecision)
                        or result.status != "RECOVERY_REQUIRED"
                        or result.reason_code != "fresh_dispatch_indeterminate"
                        or result.confirmation_id != confirmation_id):
                    raise ValueError("fresh local recovery release did not complete")
            if (session_id not in self._grounded_cancelled_sessions
                    or session_id in self._sessions or session_id in self._grounded_publications):
                raise ValueError("fresh recovery local owner is still retained")
            with _WINDOW_LEASE_LOCK:
                lease = _WINDOW_LEASES.get(self._binding.target_window_handle)
                if lease is not None and lease.session_id == session_id:
                    raise ValueError("fresh recovery window lease is still retained")
            if self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=confirmation_id) != claim:
                raise ValueError("fresh recovery durable state changed during release")
            self._close_preparation_for_session(session_id)
            return claim

    def _close_grounded_stale_for_consume(
        self, *, session: _LiveSession, confirmation_id: str
    ) -> LiveControllerDecision:
        result = self.cancel_grounded_review(
            session_id=session.snapshot.session_id,
            reason_code="grounded_confirmation_stale",
        )
        if isinstance(result, LiveControllerDecision):
            return result
        return LiveControllerDecision(
            "REJECTED", "grounded_confirmation_stale", confirmation_id
        )

    def cancel_grounded_review(
        self,
        *,
        session_id: str,
        reason_code: str = "grounded_confirmation_cancelled",
    ) -> RuntimeIntentClaimSnapshot | LiveControllerDecision | None:
        """先关闭持久事实，再释放确切窗口 lease。"""
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("grounded session identity is invalid")
        with self._lock:
            released = self._released_fresh_confirmations.get(session_id)
            if released is not None:
                # 只读回本实例已释放的确切拒绝/关闭记录，不复活执行上下文。
                identity, claim_sha, request_sha, phase = released
                claim = self._intent_claim_store.get_for_grounded_confirmation(confirmation_id=identity)
                if (not isinstance(claim, RuntimeFreshLearningClaimSnapshot)
                        or claim.observation.session_id != session_id
                        or claim.claim_content_sha256 != claim_sha
                        or claim.phase != phase
                        or phase not in {"grounded_confirmation_denied", "grounded_confirmation_closed"}
                        or claim.grounded_confirmation.request_content_sha256 != request_sha
                        or session_id in self._sessions):
                    raise ValueError("released fresh confirmation changed")
                return claim
            if session_id in self._grounded_cancelled_sessions:
                return None
            session = self._sessions.get(session_id)
            context = self._grounded_publications.get(session_id)
            if session is None or context is None:
                raise ValueError("grounded session is not owned by this controller")
            try:
                claim = self._intent_claim_store.find_for_observation(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                )
                if claim is None:
                    result = None
                else:
                    if not self._grounded_claim_matches(
                        claim,
                        session=session,
                        context=context,
                        require_preview=claim.grounded_confirmation is not None,
                    ):
                        raise RuntimeIntentClaimStoreError(
                            "grounded confirmation claim does not match owner context"
                        )
                    if (isinstance(claim, RuntimeFreshLearningClaimSnapshot)
                            and claim.phase in {"grounded_confirmation_consume_started", "dispatch_started"}):
                        # 只清理本地租约，不把未知派发改写为未执行或重新批准。
                        self._release_grounded_session(session=session, context=context)
                        self._grounded_cancelled_sessions.add(session_id)
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED", "fresh_dispatch_indeterminate",
                            claim.grounded_confirmation.confirmation_id)
                    if claim.grounded_confirmation is None:
                        claim = self._intent_claim_store.mark_grounded_confirmation_pending(
                            session_id=session.snapshot.session_id,
                            observation_id=session.snapshot.current_observation.observation_id,
                            preview=context.preview,
                        )
                    grounded = claim.grounded_confirmation
                    if grounded is None:
                        raise RuntimeIntentClaimStoreError(
                            "grounded confirmation snapshot is missing"
                        )
                    if claim.phase in {
                        "grounded_confirmation_denied",
                        "grounded_confirmation_closed",
                    }:
                        result = claim
                    else:
                        result = self._intent_claim_store.close_grounded_confirmation(
                            confirmation_id=grounded.confirmation_id,
                            reason_code=reason_code,
                        )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_cleanup_required"
                )
            try:
                self._release_grounded_session(session=session, context=context)
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_cleanup_required"
                )
            self._grounded_cancelled_sessions.add(session_id)
            return result

    def close_initial_safe_stop(self, *, session_id: str) -> None:
        """释放尚未形成意图的初始停止边界会话。"""
        if isinstance(self._binding, ServerFreshLearningBinding):
            raise ValueError("fresh learning uses explicit preparation cancellation")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("initial safe-stop session is not owned by this controller")
            if (
                session.snapshot.current_observation.safe_stop.required is not True
                or session.consumed
            ):
                raise ValueError("initial safe-stop close requires an unconsumed safe-stop observation")
            claim = self._intent_claim_store.find_for_observation(
                session_id=session.snapshot.session_id,
                observation_id=session.snapshot.current_observation.observation_id,
            )
            if claim is not None:
                raise ValueError("initial safe-stop close refuses a durable intent claim")
            self._sessions.pop(session_id)
            self._release_window_lease(session.window_lease)
            self._close_preparation_for_session(session_id)

    def record_confirmation_decision(
        self,
        *,
        confirmation_id: str,
        decision: Literal["approved", "denied"],
    ) -> LiveControllerDecision:
        if isinstance(self._binding, ServerFreshLearningBinding):
            return LiveControllerDecision("REJECTED", "fresh_learning_confirmation_not_available")
        try:
            pending = self._intent_claim_store.get_for_confirmation(
                confirmation_id=confirmation_id
            )
            if pending.server_binding.to_dict() != {
                "workflow_id": self._binding.workflow_id,
                "asset_id": self._binding.asset_id,
                "application_identity_key": self._binding.application_identity_key,
                "target_window_handle": self._binding.target_window_handle,
            }:
                return LiveControllerDecision(
                    "REJECTED", "confirmation_binding_mismatch", confirmation_id
                )
            claim = self._intent_claim_store.record_confirmation_decision(
                confirmation_id=confirmation_id,
                decision=decision,
            )
        except RuntimeIntentClaimStoreError as exc:
            if "confirmation expired" in str(exc):
                reason = "confirmation_expired"
            elif "decision conflict" in str(exc):
                reason = "confirmation_decision_conflict"
            else:
                reason = "confirmation_integrity_failed"
            status = (
                "REJECTED"
                if reason in {"confirmation_expired", "confirmation_decision_conflict"}
                else "RECOVERY_REQUIRED"
            )
            return LiveControllerDecision(status, reason, confirmation_id)
        confirmation = claim.confirmation
        if confirmation is None or confirmation.confirmation_id != confirmation_id:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "confirmation_integrity_failed", confirmation_id
            )
        if claim.phase == "confirmation_closed":
            return LiveControllerDecision(
                "REJECTED",
                confirmation.closed_reason_code or "confirmation_stale",
                confirmation_id,
            )
        if confirmation.decision == "denied":
            return LiveControllerDecision("REJECTED", "confirmation_denied", confirmation_id)
        if confirmation.decision == "approved":
            return LiveControllerDecision("APPROVED", "confirmation_approved", confirmation_id)
        return LiveControllerDecision(
            "RECOVERY_REQUIRED", "confirmation_integrity_failed", confirmation_id
        )

    def submit_intent(
        self,
        payload: Mapping[str, object],
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        if isinstance(self._binding, ServerFreshLearningBinding):
            return LiveControllerDecision("REJECTED", "fresh_learning_confirmation_not_available")
        session_id = payload.get("session_id") if isinstance(payload, Mapping) else None
        observation_id = (
            payload.get("observation_id") if isinstance(payload, Mapping) else None
        )
        with self._lock:
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if session is None:
                if isinstance(session_id, str) and isinstance(observation_id, str):
                    try:
                        existing = self._intent_claim_store.find_for_observation(
                            session_id=session_id,
                            observation_id=observation_id,
                        )
                    except RuntimeIntentClaimStoreError:
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "claim_integrity_failed",
                        )
                    if existing is not None:
                        return self._recover_existing_claim(payload, existing)
                return LiveControllerDecision("REJECTED", "unknown_session")
            if session.snapshot.session_id in self._grounded_publications:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "grounded_confirmation_active"
                )
            try:
                existing = self._intent_claim_store.find_for_observation(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                )
            except RuntimeIntentClaimStoreError:
                was_consumed = session.consumed
                session.consumed = True
                if not was_consumed:
                    self._release_window_lease(session.window_lease)
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "claim_integrity_failed",
                )
            if existing is not None:
                was_consumed = session.consumed
                session.consumed = True
                result = self._recover_existing_claim(payload, existing)
                if not was_consumed or existing.phase == "terminal":
                    self._release_window_lease(session.window_lease)
                return result
            try:
                intent = validate_agent_intent_v1(
                    payload,
                    observation=session.snapshot.current_observation,
                )
            except (TypeError, ValueError):
                return LiveControllerDecision("REJECTED", "invalid_intent")
            if session.consumed:
                self._release_window_lease(session.window_lease)
                return LiveControllerDecision("REJECTED", "observation_consumed")
            if any(item.action_id == intent.action_id and item.semantic_action == "fill_field"
                   for item in session.snapshot.current_observation.available_actions):
                # 普通 Agent intent 没有本地字段预览，不得先占用 claim 再等待无法执行的确认。
                return LiveControllerDecision("REJECTED", "text_grounded_confirmation_required")
            try:
                self._intent_claim_store.claim(
                    observation=session.snapshot.current_observation,
                    intent=intent,
                    server_binding={
                        "workflow_id": self._binding.workflow_id,
                        "asset_id": self._binding.asset_id,
                        "application_identity_key": self._binding.application_identity_key,
                        "target_window_handle": self._binding.target_window_handle,
                    },
                )
            except RuntimeIntentClaimStoreError:
                try:
                    committed = self._intent_claim_store.find_for_observation(
                        session_id=session.snapshot.session_id,
                        observation_id=session.snapshot.current_observation.observation_id,
                    )
                except RuntimeIntentClaimStoreError:
                    session.consumed = True
                    self._release_window_lease(session.window_lease)
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED",
                        "claim_integrity_failed",
                    )
                if committed is not None:
                    session.consumed = True
                    result = self._recover_existing_claim(payload, committed)
                    self._release_window_lease(session.window_lease)
                    return result
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "claim_persistence_failed",
                )
            session.consumed = True

        try:
            result = self._execute_accepted_intent(session, intent)
            if isinstance(result, LiveControllerDecision):
                return result
            try:
                return self._intent_claim_store.persist_terminal(
                    session_id=session.snapshot.session_id,
                    observation_id=session.snapshot.current_observation.observation_id,
                    receipt=result.receipt,
                    backend_receipt=result.backend_receipt,
                    verification_evidence=result.verification_evidence,
                    next_observation=result.next_observation,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "receipt_persistence_failed",
                )
        finally:
            with self._lock:
                self._sessions.pop(session.snapshot.session_id, None)
            self._release_window_lease(session.window_lease)

    def _recover_existing_claim(
        self,
        payload: Mapping[str, object],
        claim: RuntimeIntentClaimSnapshot,
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        try:
            intent = validate_agent_intent_v1(payload, observation=claim.observation)
        except (TypeError, ValueError):
            return LiveControllerDecision("REJECTED", "observation_consumed")
        if intent != claim.intent:
            return LiveControllerDecision("REJECTED", "observation_consumed")
        if claim.grounded_consume is not None:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "grounded_confirmation_active"
            )
        if claim.phase == "terminal":
            try:
                return self._intent_claim_store.load_terminal_receipt(
                    session_id=claim.observation.session_id,
                    observation_id=claim.observation.observation_id,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "receipt_integrity_failed",
                )
        if claim.phase == "dispatch_started":
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "dispatch_indeterminate",
            )
        if claim.phase == "verification_pending":
            return self._recover_verification_pending(claim)
        if claim.phase == "confirmation_pending":
            confirmation_id = claim.confirmation.confirmation_id if claim.confirmation else None
            return LiveControllerDecision(
                "CONFIRMATION_REQUIRED",
                "human_confirmation_required",
                confirmation_id,
            )
        if claim.phase == "confirmation_denied":
            confirmation_id = claim.confirmation.confirmation_id if claim.confirmation else None
            return LiveControllerDecision("REJECTED", "confirmation_denied", confirmation_id)
        if claim.phase == "confirmation_approved":
            return self._resume_confirmed_claim(claim)
        if claim.phase == "confirmation_resume_started":
            confirmation_id = claim.confirmation.confirmation_id if claim.confirmation else None
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "confirmation_resume_indeterminate",
                confirmation_id,
            )
        if claim.phase == "confirmation_closed":
            confirmation = claim.confirmation
            return LiveControllerDecision(
                "REJECTED",
                confirmation.closed_reason_code if confirmation else "confirmation_stale",
                confirmation.confirmation_id if confirmation else None,
            )
        return LiveControllerDecision("RECOVERY_REQUIRED", "observation_consumed")

    def _resume_confirmed_claim(
        self,
        claim: RuntimeIntentClaimSnapshot,
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        confirmation = claim.confirmation
        if confirmation is None or confirmation.decision != "approved":
            return LiveControllerDecision("RECOVERY_REQUIRED", "confirmation_integrity_failed")
        if confirmation.semantic_action == "fill_field":
            # 旧审批没有可恢复的本地字段原值，关闭未尝试记录，避免长期占用恢复队列。
            return self._close_stale_confirmation(confirmation.confirmation_id)
        try:
            if claim.server_binding.to_dict() != {
                "workflow_id": self._binding.workflow_id,
                "asset_id": self._binding.asset_id,
                "application_identity_key": self._binding.application_identity_key,
                "target_window_handle": self._binding.target_window_handle,
            }:
                return self._close_stale_confirmation(confirmation.confirmation_id)
            asset = validate_reviewed_workflow_asset(
                self._asset_loader.load_active(claim.observation.workflow.asset_id)
            )
            if (
                asset["asset_id"] != claim.observation.workflow.asset_id
                or asset["source_review_lineage"]["source_workflow_id"]
                != claim.observation.workflow.workflow_id
                or claim.observation.workflow.workflow_id != self._binding.workflow_id
                or content_sha256(asset) != claim.observation.workflow.asset_content_sha256
                or asset["source_review_lineage"]["source_workflow_sha256"]
                != claim.observation.workflow.source_workflow_sha256
                or asset["source_review_lineage"]["reviewed_revision_hash"]
                != claim.observation.workflow.reviewed_revision_hash
                or self._asset_application_identity_key(asset)
                != claim.server_binding.application_identity_key
            ):
                return self._close_stale_confirmation(confirmation.confirmation_id)
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "confirmation_integrity_failed", confirmation.confirmation_id
            )
        try:
            lease = self._acquire_window_lease(claim.observation.session_id)
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "window_lease_unavailable", confirmation.confirmation_id
            )
        try:
            try:
                started = self._intent_claim_store.begin_confirmation_resume(
                    confirmation_id=confirmation.confirmation_id
                )
            except RuntimeIntentClaimStoreError as exc:
                if "confirmation expired" in str(exc):
                    return LiveControllerDecision(
                        "REJECTED", "confirmation_expired", confirmation.confirmation_id
                    )
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "confirmation_resume_indeterminate",
                    confirmation.confirmation_id,
                )
            started_confirmation = started.confirmation
            if started.phase == "confirmation_closed":
                return LiveControllerDecision(
                    "REJECTED",
                    (
                        started_confirmation.closed_reason_code
                        if started_confirmation is not None
                        else "confirmation_expired"
                    ),
                    confirmation.confirmation_id,
                )
            if started_confirmation is None:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "confirmation_integrity_failed",
                    confirmation.confirmation_id,
                )
            session = _LiveSession(
                snapshot=LiveSessionSnapshot(
                    session_id=claim.observation.session_id,
                    workflow=claim.observation.workflow,
                    current_observation=claim.observation,
                    target_window_handle=claim.server_binding.target_window_handle,
                ),
                asset=asset,
                window_lease=lease,
                consumed=True,
                confirmation=started_confirmation,
            )
            result = self._execute_accepted_intent(session, claim.intent)
            if isinstance(result, LiveControllerDecision):
                return result
            try:
                return self._intent_claim_store.persist_terminal(
                    session_id=claim.observation.session_id,
                    observation_id=claim.observation.observation_id,
                    receipt=result.receipt,
                    backend_receipt=result.backend_receipt,
                    verification_evidence=result.verification_evidence,
                    next_observation=result.next_observation,
                )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "receipt_persistence_failed",
                    confirmation.confirmation_id,
                )
        finally:
            self._release_window_lease(lease)

    def _close_stale_confirmation(self, confirmation_id: str) -> LiveControllerDecision:
        try:
            closed = self._intent_claim_store.close_confirmation(
                confirmation_id=confirmation_id,
                reason_code="confirmation_stale",
            )
        except RuntimeIntentClaimStoreError:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "confirmation_integrity_failed", confirmation_id
            )
        confirmation = closed.confirmation
        if (
            closed.phase != "confirmation_closed"
            or confirmation is None
            or confirmation.closed_reason_code != "confirmation_stale"
        ):
            return LiveControllerDecision(
                "RECOVERY_REQUIRED", "confirmation_integrity_failed", confirmation_id
            )
        return LiveControllerDecision("REJECTED", "confirmation_stale", confirmation_id)

    def _recover_verification_pending(
        self,
        claim: RuntimeIntentClaimSnapshot,
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        checkpoint = claim.verification_checkpoint
        if checkpoint is None:
            return LiveControllerDecision("RECOVERY_REQUIRED", "claim_integrity_failed")
        try:
            if claim.server_binding.to_dict() != {
                "workflow_id": self._binding.workflow_id,
                "asset_id": self._binding.asset_id,
                "application_identity_key": self._binding.application_identity_key,
                "target_window_handle": self._binding.target_window_handle,
            }:
                return LiveControllerDecision("RECOVERY_REQUIRED", "claim_binding_mismatch")
            asset = validate_reviewed_workflow_asset(
                self._asset_loader.load_active(claim.observation.workflow.asset_id)
            )
            if (
                asset["asset_id"] != claim.observation.workflow.asset_id
                or asset["source_review_lineage"]["source_workflow_id"]
                != claim.observation.workflow.workflow_id
                or claim.observation.workflow.workflow_id != self._binding.workflow_id
                or content_sha256(asset) != claim.observation.workflow.asset_content_sha256
                or asset["source_review_lineage"]["source_workflow_sha256"]
                != claim.observation.workflow.source_workflow_sha256
                or asset["source_review_lineage"]["reviewed_revision_hash"]
                != claim.observation.workflow.reviewed_revision_hash
                or self._asset_application_identity_key(asset)
                != claim.server_binding.application_identity_key
            ):
                return LiveControllerDecision("RECOVERY_REQUIRED", "claim_binding_mismatch")
        except Exception:
            return LiveControllerDecision("RECOVERY_REQUIRED", "claim_integrity_failed")

        local_grounded = (
            self._grounded_context_for_claim(claim)
            if claim.grounded_consume is not None else None
        )
        owns_existing_grounded = local_grounded is not None
        if local_grounded is not None:
            session = local_grounded[0]
            session.grounded_consume = claim.grounded_consume
            lease = session.window_lease
        elif claim.grounded_consume is not None:
            confirmation_id = claim.grounded_consume.confirmation_id
            session = self._grounded_recovery_sessions.get(confirmation_id)
            if session is None:
                try:
                    lease = self._acquire_window_lease(claim.observation.session_id)
                except Exception:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "window_lease_unavailable", confirmation_id
                    )
                session = _LiveSession(
                    snapshot=LiveSessionSnapshot(
                        session_id=claim.observation.session_id,
                        workflow=claim.observation.workflow,
                        current_observation=claim.observation,
                        target_window_handle=claim.server_binding.target_window_handle,
                    ),
                    asset=asset,
                    window_lease=lease,
                    consumed=True,
                    grounded_consume=claim.grounded_consume,
                )
                self._grounded_recovery_sessions[confirmation_id] = session
            elif (
                session.snapshot.current_observation != claim.observation
                or session.snapshot.workflow != claim.observation.workflow
                or session.snapshot.target_window_handle
                != claim.server_binding.target_window_handle
                or session.grounded_consume != claim.grounded_consume
            ):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", "claim_integrity_failed", confirmation_id
                )
            lease = session.window_lease
        else:
            try:
                lease = self._acquire_window_lease(claim.observation.session_id)
            except Exception:
                return LiveControllerDecision("RECOVERY_REQUIRED", "window_lease_unavailable")
            session = _LiveSession(
                snapshot=LiveSessionSnapshot(
                    session_id=claim.observation.session_id,
                    workflow=claim.observation.workflow,
                    current_observation=claim.observation,
                    target_window_handle=claim.server_binding.target_window_handle,
                ),
                asset=asset,
                window_lease=lease,
                consumed=True,
                confirmation=claim.confirmation,
                grounded_consume=claim.grounded_consume,
            )
        try:
            result = self._verify_pending_checkpoint(session, claim.intent, checkpoint)
            if isinstance(result, LiveControllerDecision):
                return result
            try:
                if claim.grounded_consume is not None:
                    receipt = self._intent_claim_store.persist_grounded_terminal(
                        confirmation_id=claim.grounded_consume.confirmation_id,
                        consume_content_sha256=claim.grounded_consume.content_sha256,
                        receipt=result.receipt,
                        backend_receipt=result.backend_receipt,
                        verification_evidence=result.verification_evidence,
                        next_observation=result.next_observation,
                    )
                else:
                    receipt = self._intent_claim_store.persist_terminal(
                        session_id=claim.observation.session_id,
                        observation_id=claim.observation.observation_id,
                        receipt=result.receipt,
                        backend_receipt=result.backend_receipt,
                        verification_evidence=result.verification_evidence,
                        next_observation=result.next_observation,
                    )
            except RuntimeIntentClaimStoreError:
                return LiveControllerDecision("RECOVERY_REQUIRED", "receipt_persistence_failed")
            if owns_existing_grounded:
                try:
                    self._release_window_lease(lease)
                except Exception:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "grounded_confirmation_cleanup_required"
                    )
                self._sessions.pop(session.snapshot.session_id, None)
                self._grounded_publications.pop(session.snapshot.session_id, None)
            elif claim.grounded_consume is not None:
                confirmation_id = claim.grounded_consume.confirmation_id
                try:
                    self._release_window_lease(lease)
                except Exception:
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED",
                        "grounded_confirmation_cleanup_required",
                        confirmation_id,
                    )
                self._grounded_recovery_sessions.pop(confirmation_id, None)
            return receipt
        finally:
            if not owns_existing_grounded and claim.grounded_consume is None:
                self._release_window_lease(lease)

    def _capture_current_resolution(
        self,
        *,
        session: _LiveSession,
        expected_process_id: int | None = None,
    ) -> _CurrentProjection | _CurrentProjectionFailure:
        try:
            projected = self._observation_source.capture_projected(
                session_id=session.snapshot.session_id,
                workflow=session.snapshot.workflow.model_dump(mode="json"),
                asset=session.asset,
                target_window_handle=session.snapshot.target_window_handle,
            )
        except Exception:
            return _CurrentProjectionFailure("current_capture_failed", True)
        projection_failure = self._projected_capture_failure(
            projected,
            session=session,
            expected_process_id=expected_process_id,
        )
        if projection_failure is not None:
            if (
                expected_process_id is not None
                and isinstance(projected, ProjectedObservationCapture)
                and projected.target_process_id != expected_process_id
            ):
                return _CurrentProjectionFailure("target_process_changed")
            return _CurrentProjectionFailure(projection_failure, True)
        current = dict(projected.current_observation)
        if (
            current.get("capture_id")
            == session.snapshot.current_observation.current_capture.capture_id
        ):
            return _CurrentProjectionFailure("stale_candidate")
        try:
            state_resolution = resolve_current_state(session.asset, current)
        except Exception:
            return _CurrentProjectionFailure("state_resolution_failed", True)
        if state_resolution.get("status") != "resolved":
            return _CurrentProjectionFailure("target_unresolved")
        return _CurrentProjection(
            projected=projected,
            current=current,
            state_resolution=dict(state_resolution),
        )

    def _ground_selected_current(
        self,
        *,
        session: _LiveSession,
        current: dict[str, Any],
        selection: dict[str, Any],
        validator: Callable[
            [dict[str, Any], dict[str, Any], dict[str, Any]],
            dict[str, Any],
        ],
        gate_evaluator: Callable[..., Mapping[str, Any]] | None = None,
    ) -> _GroundedSelection | _GroundingFailure:
        """共享无权限定位、Gate、几何及可见性流水线。"""
        if not self._supports_exact_target_state_verification(session.asset, selection):
            return _GroundingFailure("policy_blocked", selection=selection)
        try:
            resolution = dict(
                self._target_resolver.resolve(
                    session_id=session.snapshot.session_id,
                    selection=selection,
                    current_observation=current,
                )
            )
        except Exception:
            return _GroundingFailure("target_resolution_failed", recovery_required=True)
        resolution_status = resolution.get("status")
        if resolution_status != "resolved":
            reason = {
                "ambiguous": "grounding_ambiguous",
                "stale": "stale_candidate",
                "wrong_context": "capture_lineage_mismatch",
            }.get(str(resolution_status), "target_unresolved")
            return _GroundingFailure(reason, selection=selection)
        grounding_value = resolution.get("grounding")
        if not isinstance(grounding_value, Mapping):
            return _GroundingFailure("target_unresolved", selection=selection)
        grounding = dict(grounding_value)
        gate_context_value = resolution.get("gate_context", {})
        if not isinstance(gate_context_value, Mapping):
            return _GroundingFailure(
                "pre_click_rejected", selection=selection, grounding=grounding
            )
        try:
            evaluate_gate = gate_evaluator or self._gate.evaluate
            gate_value = evaluate_gate(
                selection=selection,
                grounding=grounding,
                **dict(gate_context_value),
            )
        except (TypeError, ValueError):
            return _GroundingFailure(
                "pre_click_rejected", selection=selection, grounding=grounding
            )
        except Exception:
            return _GroundingFailure("gate_evaluation_failed", recovery_required=True)
        if not isinstance(gate_value, Mapping):
            return _GroundingFailure(
                "pre_click_rejected", selection=selection, grounding=grounding
            )
        try:
            gate = dict(gate_value)
        except Exception:
            return _GroundingFailure("gate_evaluation_failed", recovery_required=True)
        try:
            validation = validator(selection, grounding, gate)
        except Exception:
            return _GroundingFailure("grounding_validation_failed", recovery_required=True)
        if validation.get("status") != "validated":
            failure_code = self._normalize_block_reason(
                str(validation.get("failure_code") or "pre_click_rejected")
            )
            return _GroundingFailure(
                failure_code,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_blocked=gate.get("allowed") is not True,
            )
        point = grounding["click_point"]
        click_point = (float(point["x"]), float(point["y"]))
        bbox = grounding["bbox"]
        target_bbox = (
            float(bbox["x"]),
            float(bbox["y"]),
            float(bbox["w"]),
            float(bbox["h"]),
        )
        try:
            visibility = dict(
                self._window_visibility_checker.check(
                    session_id=session.snapshot.session_id,
                    capture_lineage=selection["capture_lineage"],
                    target_window_handle=session.snapshot.target_window_handle,
                    click_point=click_point,
                    target_bbox=target_bbox,
                )
            )
        except Exception:
            return _GroundingFailure("visibility_check_failed", recovery_required=True)
        bound_handle = visibility.get("bound_window_handle")
        point_visibility = visibility.get("point_visibility")
        reason = None
        if bound_handle != session.snapshot.target_window_handle:
            reason = "foreground_window_changed"
        elif (
            not isinstance(point_visibility, Mapping)
            or point_visibility.get("allowed") is not True
        ):
            reason = "target_occluded"
        if reason is not None:
            return _GroundingFailure(
                reason,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_blocked=True,
            )
        return _GroundedSelection(
            selection=selection,
            grounding=grounding,
            gate=gate,
            validation=dict(validation),
            click_point=click_point,
            target_bbox=target_bbox,
            gate_context=dict(gate_context_value),
            visibility=visibility,
        )

    def _execute_accepted_intent(
        self,
        session: _LiveSession,
        intent: AgentIntentV1,
    ) -> _ExecutionResult | LiveControllerDecision:
        observation = session.snapshot.current_observation
        if intent.action_id == "runtime.safe_stop":
            return _ExecutionResult(
                self._receipt(
                    session=session,
                    intent=intent,
                    outcome="SAFE_STOP",
                    reason_code="safe_stop_boundary",
                    attempt_count=0,
                    gate_status="not_evaluated",
                    dispatch_status="not_started",
                    selection_ref=None,
                    candidate_ref=None,
                    gate_ref=None,
                    backend_ref=None,
                )
            )

        projection = self._capture_current_resolution(
            session=session,
            expected_process_id=(
                session.confirmation.target_process_id
                if session.confirmation is not None
                else None
            ),
        )
        if isinstance(projection, _CurrentProjectionFailure):
            if (
                projection.reason_code == "target_process_changed"
                and session.confirmation is not None
            ):
                return self._close_stale_confirmation(
                    session.confirmation.confirmation_id
                )
            if projection.recovery_required:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED", projection.reason_code
                )
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code=projection.reason_code,
                )
            )
        projected = projection.projected
        current = projection.current
        state_resolution = projection.state_resolution
        confirmation_evidence: object | None = None
        try:
            if session.confirmation is not None:
                confirmation_evidence = (
                    self._intent_claim_store._get_server_confirmed_transition_evidence(
                        confirmation_id=session.confirmation.confirmation_id
                    )
                )
                selection = _select_server_confirmed_transition(
                    session.asset,
                    state_resolution,
                    transition_id=intent.action_id,
                    confirmation_evidence=confirmation_evidence,
                    current_observation=current,
                )
            else:
                selection = select_verified_transition(
                    session.asset,
                    state_resolution,
                    transition_id=intent.action_id,
                    current_observation=current,
                )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "transition_selection_failed",
            )
        if selection.get("status") != "selected":
            failure = str(selection.get("failure_code") or "target_unresolved")
            if failure == "human_review_required":
                try:
                    pending = self._intent_claim_store.mark_confirmation_pending(
                        session_id=session.snapshot.session_id,
                        observation_id=observation.observation_id,
                        current_observation=current,
                        state_resolution=state_resolution,
                        transition_id=intent.action_id,
                        semantic_action=next(
                            item.semantic_action
                            for item in observation.available_actions
                            if item.action_id == intent.action_id
                        ),
                        target_process_id=projected.target_process_id,
                    )
                except (RuntimeIntentClaimStoreError, StopIteration):
                    return LiveControllerDecision(
                        "RECOVERY_REQUIRED", "confirmation_persistence_failed"
                    )
                confirmation_id = (
                    pending.confirmation.confirmation_id if pending.confirmation else None
                )
                return LiveControllerDecision(
                    "CONFIRMATION_REQUIRED",
                    "human_confirmation_required",
                    confirmation_id,
                )
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code="target_unresolved",
                )
            )

        if session.confirmation is not None:
            validator = lambda selected, evidence, gate: _validate_server_confirmed_grounding(
                session.asset,
                selected,
                evidence,
                gate,
                policy=self._grounding_policy,
                confirmation_evidence=confirmation_evidence,
            )
        else:
            validator = lambda selected, evidence, gate: validate_current_grounding(
                session.asset,
                selected,
                evidence,
                gate,
                policy=self._grounding_policy,
            )
        grounded = self._ground_selected_current(
            session=session,
            current=current,
            selection=selection,
            validator=validator,
        )
        if isinstance(grounded, _GroundingFailure):
            if grounded.recovery_required:
                return LiveControllerDecision("RECOVERY_REQUIRED", grounded.reason_code)
            if grounded.reason_code == "policy_blocked":
                return _ExecutionResult(
                    self._early_receipt(
                        session=session,
                        intent=intent,
                        outcome="BLOCKED",
                        reason_code="policy_blocked",
                    )
                )
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code=grounded.reason_code,
                selection=grounded.selection,
                grounding=grounded.grounding,
                gate=grounded.gate,
                gate_blocked=grounded.gate_blocked,
            )
        return self._dispatch_validated_grounding(
            session=session,
            intent=intent,
            observation=observation,
            current=current,
            projected=projected,
            grounded=grounded,
        )

    def _dispatch_validated_grounding(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        observation: AgentObservationV1,
        current: dict[str, Any],
        projected: ProjectedObservationCapture,
        grounded: _GroundedSelection,
        text_field_expectation: TextFieldExpectation | None = None,
    ) -> _ExecutionResult | LiveControllerDecision:
        """旧执行与 grounded consume 共用的唯一 authority/dispatch 尾部。"""
        selection = grounded.selection
        grounding = grounded.grounding
        gate = grounded.gate
        click_point = grounded.click_point
        parameters = scroll_parameter_fields(selection)
        scroll = None
        scroll_capture = None
        if parameters:
            try:
                scroll_capture = self._observation_source.read_scroll_capture(
                    session_id=session.snapshot.session_id, current_observation=current,
                )
            except (AttributeError, ValueError, OSError):
                return LiveControllerDecision("RECOVERY_REQUIRED", "scroll_capture_unavailable")
            scroll = ScrollDispatchParameters(
                parameters=ReviewedScrollParameters.from_payload(parameters["scroll_parameters"]),
                target_bbox=tuple(grounding["bbox"][key] for key in ("x", "y", "w", "h")),
                viewport_size=tuple(grounding["viewport_size"][key] for key in ("width", "height")),
            )
        text_input = None
        text_guard = None
        if selection["semantic_action"] == "fill_field":
            consume = session.grounded_consume
            if (
                type(text_field_expectation) is not TextFieldExpectation
                or consume is None
                or text_field_expectation.to_reference() != consume.fresh_preview.to_dict().get("text_field_expectation_ref")
                or text_parameter_reference(text_field_expectation.parameters.reviewed) != selection.get("text_parameters_ref")
            ):
                return LiveControllerDecision("REJECTED", "text_execution_not_ready")
            text_input = TextDispatchParameters(
                parameters=text_field_expectation.parameters,
                target_bbox=tuple(grounding["bbox"][key] for key in ("x", "y", "w", "h")),
                viewport_size=tuple(grounding["viewport_size"][key] for key in ("width", "height")),
            )
            text_guard = TextInputGuard(
                expectation=text_field_expectation,
                read_current=lambda: self._observation_source.read_text_field(
                    session_id=session.snapshot.session_id, current_observation=current,
                    selection=selection, grounding=grounding, require_keyboard_focus=True,
                ),
            )
        command = DesktopDispatchCommand(
            semantic_action=selection["semantic_action"],
            capture_id=grounding["capture_id"],
            candidate_id=grounding["candidate_id"],
            click_point=click_point,
            target_window_handle=session.snapshot.target_window_handle,
            scroll=scroll,
            text_input=text_input,
            text_guard=text_guard,
            target_bbox=tuple(grounding["bbox"][key] for key in ("x", "y", "w", "h")),
        )
        gate_ref = self._first_ref(gate.get("evidence_refs"), "gate")
        if self._action_learning_recorder is not None:
            try:
                self._action_learning_recorder.record_before(
                    runtime_session_id=session.snapshot.session_id,
                    observation_id=observation.observation_id,
                    payload=self._learning_before_payload(
                        session=session,
                        intent=intent,
                        observation=observation,
                        current=current,
                        projected=projected,
                        selection=selection,
                        grounding=grounding,
                        click_point=click_point,
                        gate_ref=gate_ref,
                        scroll_capture=scroll_capture,
                        text_field_expectation=text_field_expectation,
                    ),
                )
            except (ActionLearningRecorderError, TypeError, ValueError, OSError):
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "learning_recording_failed",
                )
        authority = _mint_execution_authority(
            session_id=session.snapshot.session_id,
            observation_id=observation.observation_id,
            intent_id=intent.intent_id,
            workflow_revision_hash=session.snapshot.workflow.reviewed_revision_hash,
            semantic_action=command.semantic_action,
            selection_sha256=selection["selection_sha256"],
            capture_id=command.capture_id,
            candidate_id=command.candidate_id,
            click_point=command.click_point,
            target_window_handle=command.target_window_handle,
            gate_decision_ref=gate_ref,
            scroll=scroll,
            text_input=text_input,
            text_guard=text_guard,
            target_bbox=command.target_bbox,
        )
        try:
            if session.grounded_consume is not None:
                self._intent_claim_store.mark_grounded_dispatch_started(
                    confirmation_id=session.grounded_consume.confirmation_id,
                    consume_content_sha256=session.grounded_consume.content_sha256,
                )
            else:
                self._intent_claim_store.mark_dispatch_started(
                    session_id=session.snapshot.session_id,
                    observation_id=observation.observation_id,
                )
        except RuntimeIntentClaimStoreError:
            return LiveControllerDecision("RECOVERY_REQUIRED", "dispatch_marker_failed")
        backend_receipt = self._dispatch_command_once(command, authority=authority)
        if backend_receipt.status == "indeterminate":
            return self._indeterminate_receipt(
                session=session, intent=intent, selection=selection,
                grounding=grounding, gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        if backend_receipt.status != "dispatched":
            return self._execution_failed_receipt(
                session=session, intent=intent, selection=selection,
                grounding=grounding, gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        try:
            if session.grounded_consume is not None:
                checkpoint_claim = self._intent_claim_store.mark_grounded_verification_pending(
                    **({"scroll_capture": scroll_capture} if scroll_capture is not None else {}),
                    **({"text_field_expectation": text_field_expectation.to_reference()} if text_field_expectation is not None else {}),
                    confirmation_id=session.grounded_consume.confirmation_id,
                    consume_content_sha256=session.grounded_consume.content_sha256,
                    current_observation=current,
                    selection=selection,
                    grounding=grounding,
                    gate=gate,
                    gate_decision_ref=gate_ref,
                    backend_receipt=backend_receipt,
                    target_process_id=projected.target_process_id,
                )
            else:
                checkpoint_claim = self._intent_claim_store.mark_verification_pending(
                    **({"scroll_capture": scroll_capture} if scroll_capture is not None else {}),
                    session_id=session.snapshot.session_id,
                    observation_id=observation.observation_id,
                    current_observation=current,
                    selection=selection,
                    grounding=grounding,
                    gate=gate,
                    gate_decision_ref=gate_ref,
                    backend_receipt=backend_receipt,
                    target_process_id=projected.target_process_id,
                )
            checkpoint_claim = self._intent_claim_store.get_for_observation(
                session_id=session.snapshot.session_id,
                observation_id=observation.observation_id,
            )
        except RuntimeIntentClaimStoreError:
            return LiveControllerDecision("RECOVERY_REQUIRED", "verification_checkpoint_failed")
        checkpoint = checkpoint_claim.verification_checkpoint
        if checkpoint_claim.phase != "verification_pending" or checkpoint is None:
            return LiveControllerDecision("RECOVERY_REQUIRED", "verification_checkpoint_failed")
        return self._verify_pending_checkpoint(session, intent, checkpoint)

    @staticmethod
    def _learning_digest(value: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _learning_before_payload(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        observation: AgentObservationV1,
        current: Mapping[str, Any],
        projected: ProjectedObservationCapture,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        click_point: tuple[float, float],
        gate_ref: str,
        scroll_capture: Mapping[str, Any] | None,
        text_field_expectation: TextFieldExpectation | None,
    ) -> dict[str, Any]:
        """冻结共同派发前的引用、摘要和几何，不复制文本或剪贴板内容。"""

        current_capture = projected.agent_observation.current_capture.model_dump(mode="json")
        scroll_ref = None
        if scroll_capture is not None:
            scroll_ref = {
                key: deepcopy(scroll_capture[key])
                for key in (
                    "capture_id",
                    "image_sha256",
                    "screenshot_sha256",
                    "evidence_ref",
                    "viewport_size",
                    "target_window_handle",
                    "target_process_id",
                )
                if key in scroll_capture
            }
            scroll_ref["content_sha256"] = self._learning_digest(scroll_capture)
        text_expectation_sha256 = None
        if text_field_expectation is not None:
            text_expectation_sha256 = self._learning_digest(
                text_field_expectation.to_reference()
            )
        return {
            "contract_version": BEFORE_CONTRACT_VERSION,
            "runtime_session_id": session.snapshot.session_id,
            "observation_id": observation.observation_id,
            "intent_id": intent.intent_id,
            "intent_sha256": self._learning_digest(intent.model_dump(mode="json")),
            "workflow": session.snapshot.workflow.model_dump(mode="json"),
            "action": {
                "action_id": intent.action_id,
                "semantic_action": selection["semantic_action"],
                **deepcopy(reviewed_action_parameter_fields(selection)),
            },
            "capture": current_capture,
            "current_observation_sha256": self._learning_digest(current),
            "projected_observation_sha256": self._learning_digest(
                projected.agent_observation.model_dump(mode="json")
            ),
            "selection_ref": f"selection:{selection['selection_sha256']}",
            "selection_sha256": selection["selection_sha256"],
            "grounding_sha256": self._learning_digest(grounding),
            "candidate_ref": (
                f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}"
            ),
            "geometry": {
                "bbox": deepcopy(grounding["bbox"]),
                "viewport_size": deepcopy(grounding["viewport_size"]),
                "click_point": [float(value) for value in click_point],
                "target_window_handle": session.snapshot.target_window_handle,
                "target_process_id": projected.target_process_id,
            },
            "gate_decision_ref": gate_ref,
            "scroll_capture_ref": scroll_ref,
            "text_field_expectation_sha256": text_expectation_sha256,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def _verify_pending_checkpoint(
        self,
        session: _LiveSession,
        intent: AgentIntentV1,
        checkpoint: RuntimeVerificationPendingCheckpoint,
    ) -> _ExecutionResult | LiveControllerDecision:
        selection = checkpoint.selection
        grounding = checkpoint.grounding
        selection_ref = f"selection:{selection['selection_sha256']}"
        candidate_ref = f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}"
        deadline = (
            self._verification_monotonic_clock()
            + self._verification_total_budget_seconds
        )
        seen_post_capture_ids: set[str] = set()

        for capture_attempt in range(self._verification_max_capture_attempts):
            receipt_id = f"receipt.{uuid4().hex}"
            trace_ref = f"trace:live-controller:{receipt_id}"
            server_refs = [
                selection_ref,
                candidate_ref,
                checkpoint.gate_decision_ref,
                checkpoint.backend_receipt.receipt_ref,
                trace_ref,
                *(
                    [session.confirmation.evidence_ref]
                    if session.confirmation is not None
                    and session.confirmation.evidence_ref
                    else []
                ),
                *(
                    [session.grounded_consume.evidence_ref]
                    if session.grounded_consume is not None
                    else []
                ),
            ]
            try:
                projected = self._observation_source.capture_projected(
                    session_id=session.snapshot.session_id,
                    workflow=session.snapshot.workflow.model_dump(mode="json"),
                    asset=session.asset,
                    target_window_handle=session.snapshot.target_window_handle,
                )
            except Exception:
                return LiveControllerDecision("RECOVERY_REQUIRED", "post_capture_failed")
            projection_failure = self._projected_capture_failure(
                projected,
                session=session,
                expected_process_id=checkpoint.target_process_id,
            )
            if projection_failure is not None:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "post_capture_lineage_mismatch",
                )

            try:
                if session.grounded_consume is not None:
                    verification = _verify_grounded_server_dispatched_transition_result(
                        session.asset,
                        selection,
                        checkpoint.current_observation,
                        projected.current_observation,
                        server_evidence_refs=server_refs,
                        grounded_confirmation_evidence_ref=str(
                            session.grounded_consume.selection.get(
                                "human_confirmation_evidence_ref"
                            )
                            or ""
                        ),
                    )
                else:
                    verification = verify_server_dispatched_transition_result(
                        session.asset,
                        selection,
                        checkpoint.current_observation,
                        projected.current_observation,
                        server_evidence_refs=server_refs,
                    )
            except Exception:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "post_verification_integrity_failed",
                )

            post_capture_id = str(
                projected.current_observation.get("capture_id") or ""
            )
            if selection.get("semantic_action") == "scroll_region":
                try:
                    after_scroll = self._observation_source.read_scroll_capture(
                        session_id=session.snapshot.session_id, current_observation=projected.current_observation,
                    )
                except (AttributeError, ValueError, OSError):
                    after_scroll = None
                bbox = grounding["bbox"]
                spatial = measure_scroll_spatial_evidence(
                    before=checkpoint.scroll_capture, after=after_scroll,
                    target_bbox={"x": bbox["x"], "y": bbox["y"], "width": bbox["w"], "height": bbox["h"]},
                    target_container_id=selection["scroll_parameters"]["target_container_id"],
                )
                if spatial["status"] != "target_visual_change":
                    verification = {
                        "contract_version": "transition_verification_v1", "status": "blocked",
                        "artifact_is_authorization": False, "execute_binding_enabled": False,
                        "state_advanced": False, "failure_code": f"scroll_{spatial['status']}",
                        "semantic_verification": verification, "scroll_spatial_evidence": spatial,
                    }
                else:
                    verification = {**verification, "scroll_spatial_evidence": spatial}
            if selection.get("semantic_action") == "fill_field":
                try:
                    actual_field = self._observation_source.read_text_field_after(
                        session_id=session.snapshot.session_id, current_observation=projected.current_observation,
                        previous_selection=selection,
                    )
                except (AttributeError, TypeError, ValueError, OSError):
                    actual_field = None
                field_proof = verify_text_field_result_reference(
                    checkpoint.text_field_expectation, actual_field,
                    declaration_reference=selection["text_parameters_ref"],
                )
                if field_proof["status"] != "verified":
                    verification = {
                        "contract_version": "transition_verification_v1", "status": "blocked",
                        "artifact_is_authorization": False, "execute_binding_enabled": False,
                        "state_advanced": False, "failure_code": field_proof["reason_code"],
                        "semantic_verification": verification, "text_field_verification": field_proof,
                    }
                else:
                    verification = {**verification, "text_field_verification": field_proof}
            if post_capture_id and post_capture_id in seen_post_capture_ids:
                verification = {
                    **verification,
                    "status": "blocked",
                    "failure_code": "post_capture_not_new",
                    "state_advanced": False,
                }
            if post_capture_id:
                seen_post_capture_ids.add(post_capture_id)

            status = verification.get("status")
            failure = str(verification.get("failure_code") or "")
            if status == "blocked" and failure not in {
                "post_capture_not_new",
                "destination_mismatch",
                "post_action_failure",
                "scroll_no_visual_change", "scroll_non_target_visual_change", "scroll_unknown",
                "text_field_unavailable", "text_field_identity_changed", "text_field_read_not_new", "text_value_mismatch",
            }:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    failure or "post_verification_integrity_failed",
                )
            if status not in {"verified", "blocked"}:
                return LiveControllerDecision(
                    "RECOVERY_REQUIRED",
                    "post_verification_integrity_failed",
                )

            if (
                status == "blocked"
                and self._should_poll_verification_failure(
                    verification,
                    source_state_id=str(selection["source_state_id"]),
                )
                and capture_attempt + 1 < self._verification_max_capture_attempts
            ):
                remaining = deadline - self._verification_monotonic_clock()
                if remaining > 0:
                    delay = min(self._verification_poll_interval_seconds, remaining)
                    try:
                        self._verification_sleeper(delay)
                    except Exception:
                        return LiveControllerDecision(
                            "RECOVERY_REQUIRED",
                            "post_verification_wait_failed",
                        )
                    if self._verification_monotonic_clock() < deadline:
                        continue

            verification_ref = self._verification_ref(verification)
            common = {
                "session": session,
                "intent": intent,
                "receipt_id": receipt_id,
                "attempt_count": 1,
                "gate_status": "allowed",
                "dispatch_status": "dispatched",
                "selection_ref": selection_ref,
                "candidate_ref": candidate_ref,
                "gate_ref": checkpoint.gate_decision_ref,
                "backend_ref": checkpoint.backend_receipt.receipt_ref,
                "verification_ref": verification_ref,
            }
            if status == "blocked":
                receipt = self._receipt(
                    **common,
                    outcome="VERIFICATION_FAILED",
                    reason_code=failure,
                    effect_status="not_verified",
                    destination_status=(
                        "not_evaluated"
                        if failure == "post_capture_not_new"
                        else "not_verified"
                    ),
                )
                return _ExecutionResult(
                    receipt,
                    checkpoint.backend_receipt,
                    verification,
                    None,
                )

            availability = verification["post_state_resolution"]["state_availability"]
            outcome = "SAFE_STOP" if availability == "stop_boundary" else "VERIFIED"
            reason_code = "stop_boundary" if availability == "stop_boundary" else "none"
            receipt = self._receipt(
                **common,
                outcome=outcome,
                reason_code=reason_code,
                effect_status="verified",
                destination_status="verified",
                next_observation_id=projected.agent_observation.observation_id,
            )
            return _ExecutionResult(
                receipt,
                checkpoint.backend_receipt,
                verification,
                projected.agent_observation,
            )

        return LiveControllerDecision(
            "RECOVERY_REQUIRED",
            "post_verification_integrity_failed",
        )

    def _projected_capture_failure(
        self,
        projected: object,
        *,
        session: _LiveSession,
        expected_process_id: int | None = None,
    ) -> str | None:
        if not isinstance(projected, ProjectedObservationCapture):
            return "current_capture_lineage_mismatch"
        if (
            not isinstance(projected.agent_observation, AgentObservationV1)
            or not isinstance(projected.current_observation, dict)
        ):
            return "current_capture_lineage_mismatch"
        workflow = session.snapshot.workflow
        if (
            projected.grants_action_authority is not False
            or projected.artifact_is_authorization is not False
            or projected.session_id != session.snapshot.session_id
            or projected.workflow != workflow
            or projected.application_identity_key != self._binding.application_identity_key
            or projected.asset_id != workflow.asset_id
            or projected.asset_content_sha256 != workflow.asset_content_sha256
            or projected.target_window_handle != session.snapshot.target_window_handle
            or type(projected.target_process_id) is not int
            or projected.target_process_id <= 0
            or (
                expected_process_id is not None
                and projected.target_process_id != expected_process_id
            )
        ):
            return "current_capture_lineage_mismatch"
        agent = projected.agent_observation
        current = projected.current_observation
        if (
            agent.observation_id == session.snapshot.current_observation.observation_id
            or agent.session_id != projected.session_id
            or agent.workflow != workflow
            or agent.application.kind != session.asset["application"]["kind"]
            or agent.application.identity_ref
            != f"application:{projected.application_identity_key}"
            or agent.current_capture.capture_id != current.get("capture_id")
            or agent.current_capture.screenshot_sha256
            != str(current.get("screenshot_sha256") or "").lower()
        ):
            return "current_capture_lineage_mismatch"
        try:
            resolution = resolve_current_state(session.asset, current)
        except Exception:
            return "current_capture_lineage_mismatch"
        if resolution.get("status") == "resolved":
            expected_status = (
                "stop_boundary"
                if resolution.get("state_availability") == "stop_boundary"
                else "matched"
            )
            if (
                agent.state.status != expected_status
                or agent.state.state_id != resolution.get("state_id")
                or agent.state.state_availability
                != resolution.get("state_availability")
                or agent.state.resolution_sha256
                != resolution.get("resolution_sha256")
            ):
                return "current_capture_lineage_mismatch"
        else:
            expected_status = (
                "ambiguous"
                if resolution.get("failure_code") == "current_state_ambiguous"
                else "unknown"
            )
            if agent.state.status != expected_status or agent.state.state_id is not None:
                return "current_capture_lineage_mismatch"
        return None

    @staticmethod
    def _supports_exact_target_state_verification(
        asset: Mapping[str, Any],
        selection: Mapping[str, Any],
    ) -> bool:
        transition = next(
            (
                item
                for item in asset.get("transitions", [])
                if isinstance(item, Mapping)
                and item.get("transition_id") == selection.get("transition_id")
            ),
            None,
        )
        policy = transition.get("post_action_verification") if transition else None
        rules = policy.get("semantic_success_rules") if isinstance(policy, Mapping) else None
        if (
            not isinstance(policy, Mapping)
            or set(policy) != {"requires_new_capture", "semantic_success_rules"}
            or policy.get("requires_new_capture") is not True
            or not isinstance(rules, list)
            or not rules
        ):
            return False
        ids: set[str] = set()
        for rule in rules:
            if (
                not isinstance(rule, Mapping)
                or set(rule) != {"rule_id", "type"}
                or not isinstance(rule.get("rule_id"), str)
                or not rule["rule_id"].strip()
                or rule.get("type") != "target_state_identity"
                or rule["rule_id"].strip() in ids
            ):
                return False
            ids.add(rule["rule_id"].strip())
        return True

    @staticmethod
    def _should_poll_verification_failure(
        verification: Mapping[str, object],
        *,
        source_state_id: str,
    ) -> bool:
        failure = verification.get("failure_code")
        # 滚轮派发不代表界面已重绘；这里只补观察，不重复输入。
        if failure == "scroll_no_visual_change":
            return True
        post_resolution = verification.get("post_state_resolution")
        if not isinstance(post_resolution, Mapping):
            return False
        if failure == "destination_mismatch":
            return (
                post_resolution.get("status") == "resolved"
                and post_resolution.get("state_id") == source_state_id
            )
        if failure == "post_action_failure":
            return post_resolution.get("failure_code") in {
                "current_state_unresolved",
                "current_state_ambiguous",
            }
        return False

    @staticmethod
    def _verification_ref(verification: Mapping[str, object]) -> str:
        encoded = json.dumps(
            dict(verification),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return f"verification:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _is_valid_backend_receipt(value: object) -> bool:
        if (
            not isinstance(value, BackendDispatchReceipt)
            or not isinstance(value.receipt_ref, str)
            or not (1 <= len(value.receipt_ref) <= 256)
            or _OPAQUE_REF_PATTERN.fullmatch(value.receipt_ref) is None
        ):
            return False
        expected = {
            "dispatched": "none",
            "not_started": "backend_failed",
            "indeterminate": "backend_result_lost",
        }
        return expected.get(value.status) == value.reason_code

    def _early_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        outcome: str,
        reason_code: str,
    ) -> RuntimeResultReceiptV1:
        return self._receipt(
            session=session,
            intent=intent,
            outcome=outcome,
            reason_code=reason_code,
            attempt_count=0,
            gate_status="not_evaluated",
            dispatch_status="not_started",
            selection_ref=None,
            candidate_ref=None,
            gate_ref=None,
            backend_ref=None,
        )

    def _blocked_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        reason_code: str,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any] | None = None,
        gate: Mapping[str, Any] | None = None,
        gate_blocked: bool = False,
    ) -> _ExecutionResult:
        selection_ref = f"selection:{selection['selection_sha256']}"
        candidate_ref = None
        if grounding is not None and grounding.get("candidate_id"):
            candidate_ref = f"candidate:{grounding.get('capture_id')}:{grounding['candidate_id']}"
        gate_ref = self._first_ref(gate.get("evidence_refs") if gate else None, "gate") if gate_blocked else None
        return _ExecutionResult(
            self._receipt(
                session=session,
                intent=intent,
                outcome="BLOCKED",
                reason_code=reason_code,
                attempt_count=0,
                gate_status="blocked" if gate_blocked else "not_evaluated",
                dispatch_status="not_started",
                selection_ref=selection_ref,
                candidate_ref=candidate_ref,
                gate_ref=gate_ref,
                backend_ref=None,
            )
        )

    def _execution_failed_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate_ref: str,
        backend_receipt: BackendDispatchReceipt,
    ) -> _ExecutionResult:
        return _ExecutionResult(
            self._receipt(
                session=session,
                intent=intent,
                outcome="EXECUTION_FAILED",
                reason_code="backend_failed",
                attempt_count=1,
                gate_status="allowed",
                dispatch_status="not_started",
                selection_ref=f"selection:{selection['selection_sha256']}",
                candidate_ref=f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}",
                gate_ref=gate_ref,
                backend_ref=backend_receipt.receipt_ref,
            ),
            backend_receipt,
        )

    def _indeterminate_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate_ref: str,
        backend_receipt: BackendDispatchReceipt,
    ) -> _ExecutionResult:
        return _ExecutionResult(
            self._receipt(
                session=session,
                intent=intent,
                outcome="INDETERMINATE",
                reason_code="backend_result_lost",
                attempt_count=1,
                gate_status="allowed",
                dispatch_status="indeterminate",
                effect_status="indeterminate",
                destination_status="indeterminate",
                selection_ref=f"selection:{selection['selection_sha256']}",
                candidate_ref=f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}",
                gate_ref=gate_ref,
                backend_ref=backend_receipt.receipt_ref,
            ),
            backend_receipt,
        )

    def _receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        outcome: str,
        reason_code: str,
        attempt_count: int,
        gate_status: str,
        dispatch_status: str,
        selection_ref: str | None,
        candidate_ref: str | None,
        gate_ref: str | None,
        backend_ref: str | None,
        effect_status: str = "not_evaluated",
        destination_status: str = "not_evaluated",
        receipt_id: str | None = None,
        verification_ref: str | None = None,
        next_observation_id: str | None = None,
    ) -> RuntimeResultReceiptV1:
        observation = session.snapshot.current_observation
        selected = next(item for item in observation.available_actions if item.action_id == intent.action_id)
        receipt_id = receipt_id or f"receipt.{uuid4().hex}"
        return RuntimeResultReceiptV1.model_validate(
            {
                "contract_version": "runtime_result_receipt_v1",
                "receipt_id": receipt_id,
                "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "session_id": session.snapshot.session_id,
                "observation_id": observation.observation_id,
                "intent_id": intent.intent_id,
                "workflow": session.snapshot.workflow.model_dump(mode="json"),
                "action": {
                    "action_id": intent.action_id,
                    "semantic_action": selected.semantic_action,
                    **reviewed_action_parameter_fields(selected.model_dump(mode="json")),
                },
                "outcome": outcome,
                "reason_code": reason_code,
                "attempt_count": attempt_count,
                "gate_status": gate_status,
                "dispatch_status": dispatch_status,
                "effect_status": effect_status,
                "destination_status": destination_status,
                "evidence": {
                    "state_resolution_ref": observation.state_resolution_ref,
                    "selection_ref": selection_ref,
                    "candidate_ref": candidate_ref,
                    "gate_decision_ref": gate_ref,
                    "backend_receipt_ref": backend_ref,
                    "verification_ref": verification_ref,
                    "trace_refs": [
                        f"trace:live-controller:{receipt_id}",
                        *(
                            [session.confirmation.evidence_ref]
                            if session.confirmation is not None
                            and session.confirmation.evidence_ref
                            else []
                        ),
                        *(
                            [session.grounded_consume.evidence_ref]
                            if session.grounded_consume is not None
                            else []
                        ),
                    ],
                },
                "next_observation_id": next_observation_id,
                "safe_stop": {"required": reason_code != "none", "reason_code": reason_code},
                "artifact_is_authorization": False,
            }
        )

    @staticmethod
    def _first_ref(value: object, fallback: str) -> str:
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item:
                    return item
        return f"{fallback}:{uuid4().hex}"

    @staticmethod
    def _normalize_block_reason(reason_code: str) -> str:
        if reason_code in {
            "policy_blocked",
            "capture_lineage_mismatch",
            "stale_candidate",
            "grounding_ambiguous",
            "target_unresolved",
            "pre_click_rejected",
            "foreground_window_changed",
            "target_occluded",
        }:
            return reason_code
        if reason_code in {"capture_missing", "asset_lineage_mismatch"}:
            return "capture_lineage_mismatch"
        return "target_unresolved"

    @staticmethod
    def _asset_application_identity_key(asset: Mapping[str, Any]) -> str:
        application = asset.get("application")
        if not isinstance(application, Mapping):
            raise ValueError("reviewed asset application identity is missing")
        return asset_application_identity_key(application)

    def _acquire_window_lease(self, session_id: str) -> _WindowLease:
        handle = self._binding.target_window_handle
        lease = _WindowLease(target_window_handle=handle, session_id=session_id)
        with _WINDOW_LEASE_LOCK:
            current = _WINDOW_LEASES.get(handle)
            if current is not None:
                raise RuntimeError(
                    f"target window lease is already held by session {current.session_id}"
                )
            _WINDOW_LEASES[handle] = lease
        return lease

    def _server_binding_payload(self) -> dict[str, object]:
        return {
            "workflow_id": self._binding.workflow_id,
            "asset_id": self._binding.asset_id,
            "application_identity_key": self._binding.application_identity_key,
            "target_window_handle": self._binding.target_window_handle,
        }

    def _grounded_claim_matches(
        self,
        claim: RuntimeIntentClaimSnapshot,
        *,
        session: _LiveSession,
        context: _GroundedPublicationContext,
        require_preview: bool,
    ) -> bool:
        if isinstance(session, _FreshLiveSession):
            if (not isinstance(claim, RuntimeFreshLearningClaimSnapshot)
                    or claim.observation.to_dict() != session.snapshot.current_observation.to_dict()
                    or claim.intent != context.intent
                    or context.target_process_id != session.snapshot.target_process_id):
                return False
            try:
                validate_fresh_preview_binding(context.preview, claim.observation, claim.intent,
                                              session.snapshot.source.reference())
            except (TypeError, ValueError):
                return False
            grounded = claim.grounded_confirmation
            return (grounded is None and not require_preview) or (
                grounded is not None and grounded.preview == context.preview)
        if (
            not isinstance(claim, RuntimeIntentClaimSnapshot)
            or claim.observation != session.snapshot.current_observation
            or claim.intent != context.intent
            or claim.server_binding.to_dict() != self._server_binding_payload()
            or claim.confirmation is not None
        ):
            return False
        grounded = claim.grounded_confirmation
        if not require_preview:
            return grounded is None or grounded.preview == context.preview
        if grounded is None or grounded.preview != context.preview:
            return False
        preview = grounded.preview.to_dict()
        return (
            preview["target_process_id"] == context.target_process_id
            and preview["target_window_handle"]
            == session.snapshot.target_window_handle
            and preview["session_id"] == session.snapshot.session_id
            and preview["observation_id"]
            == session.snapshot.current_observation.observation_id
            and preview["intent_id"] == context.intent.intent_id
        )

    def _grounded_context_for_claim(
        self,
        claim: RuntimeIntentClaimSnapshot,
    ) -> tuple[_LiveSession, _GroundedPublicationContext] | None:
        session_id = claim.observation.session_id
        session = self._sessions.get(session_id)
        context = self._grounded_publications.get(session_id)
        if session is None or context is None:
            return None
        return session, context

    def _release_grounded_session(
        self,
        *,
        session: _LiveSession,
        context: _GroundedPublicationContext,
    ) -> None:
        session_id = session.snapshot.session_id
        if self._grounded_publications.get(session_id) is not context:
            raise RuntimeError("grounded publication context changed")
        self._release_window_lease(session.window_lease)
        self._sessions.pop(session_id, None)
        self._grounded_publications.pop(session_id, None)

    @staticmethod
    def _release_window_lease(lease: _WindowLease) -> None:
        with _WINDOW_LEASE_LOCK:
            current = _WINDOW_LEASES.get(lease.target_window_handle)
            if current is lease:
                _WINDOW_LEASES.pop(lease.target_window_handle, None)

    def _close_preparation_for_session(self, session_id: str) -> None:
        for attempt in self._preparation_attempts.values():
            if attempt.session_id == session_id:
                attempt.state = "closed"


__all__ = [
    "LiveController",
    "LiveControllerDecision",
    "LiveSessionSnapshot",
    "ExistingWindowManagerVisibilityChecker",
    "ServerWorkflowBinding",
    "ServerFreshLearningBinding",
    "FreshLearningSessionSnapshot",
    "WindowVisibilityChecker",
]
