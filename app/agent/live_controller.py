"""W4 server-owned Live Controller 的最小可执行纵切。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import uuid4
from weakref import WeakValueDictionary

from app.agent.desktop_backend import (
    BackendDispatchReceipt,
    DesktopBackend,
    DesktopDispatchCommand,
    _mint_execution_authority,
)
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimSnapshot,
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
    RuntimeVerificationPendingCheckpoint,
)
from app.agent.reviewed_workflow_asset import (
    ReviewedWorkflowAssetStore,
    content_sha256,
    validate_reviewed_workflow_asset,
)
from app.agent.reviewed_workflow_replay import (
    resolve_current_state,
    select_verified_transition,
    validate_current_grounding,
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
        except Exception as exc:
            return {
                "bound_window_handle": target_window_handle,
                "point_visibility": None,
                "error": str(exc),
            }
        return {
            "bound_window_handle": target_window_handle,
            "point_visibility": dict(fact),
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


@dataclass(frozen=True, slots=True)
class _ExecutionResult:
    receipt: RuntimeResultReceiptV1
    backend_receipt: BackendDispatchReceipt | None = None
    verification_evidence: Mapping[str, object] | None = None
    next_observation: AgentObservationV1 | None = None


class LiveController:
    def __init__(
        self,
        *,
        binding: ServerWorkflowBinding,
        observation_source: ObservationSource,
        target_resolver: TargetResolver,
        gate: Gate,
        window_visibility_checker: WindowVisibilityChecker | None = None,
        backend: DesktopBackend,
        intent_claim_store: RuntimeIntentClaimStore,
        grounding_policy: Mapping[str, Any],
        asset_loader: AssetLoader | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        if asset_loader is None:
            if project_root is None:
                raise ValueError("project_root is required when no trusted asset loader is provided")
            asset_loader = ReviewedWorkflowAssetStore(project_root=project_root)
        if not isinstance(intent_claim_store, RuntimeIntentClaimStore):
            raise ValueError("intent_claim_store is required")
        self._binding = binding
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
        self._sessions: dict[str, _LiveSession] = {}
        self._lock = RLock()

    def start_session(self) -> LiveSessionSnapshot:
        asset = validate_reviewed_workflow_asset(
            self._asset_loader.load_active(self._binding.asset_id)
        )
        if asset["asset_id"] != self._binding.asset_id:
            raise ValueError("active reviewed asset identity does not match server binding")
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
        session_id = f"session.{uuid4().hex}"
        lease = self._acquire_window_lease(session_id)
        try:
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
        except Exception:
            self._release_window_lease(lease)
            raise
        snapshot = LiveSessionSnapshot(
            session_id=session_id,
            workflow=workflow,
            current_observation=observation,
            target_window_handle=self._binding.target_window_handle,
        )
        with self._lock:
            self._sessions[session_id] = _LiveSession(
                snapshot=snapshot,
                asset=asset,
                window_lease=lease,
            )
        return snapshot

    def submit_intent(
        self,
        payload: Mapping[str, object],
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
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
        return LiveControllerDecision("RECOVERY_REQUIRED", "observation_consumed")

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
        )
        try:
            result = self._verify_pending_checkpoint(session, claim.intent, checkpoint)
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
                return LiveControllerDecision("RECOVERY_REQUIRED", "receipt_persistence_failed")
        finally:
            self._release_window_lease(lease)

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

        try:
            projected = self._observation_source.capture_projected(
                session_id=session.snapshot.session_id,
                workflow=session.snapshot.workflow.model_dump(mode="json"),
                asset=session.asset,
                target_window_handle=session.snapshot.target_window_handle,
            )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "current_capture_failed",
            )
        projection_failure = self._projected_capture_failure(
            projected,
            session=session,
        )
        if projection_failure is not None:
            return LiveControllerDecision("RECOVERY_REQUIRED", projection_failure)
        current = dict(projected.current_observation)
        if current.get("capture_id") == observation.current_capture.capture_id:
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code="stale_candidate",
                )
            )

        try:
            state_resolution = resolve_current_state(session.asset, current)
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "state_resolution_failed",
            )
        if state_resolution.get("status") != "resolved":
            # 冻结 Contract 不允许把非 safe_stop intent 投影成 non-dispatch SAFE_STOP。
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code="target_unresolved",
                )
            )
        try:
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
                return _ExecutionResult(
                    self._early_receipt(
                        session=session,
                        intent=intent,
                        outcome="NEEDS_REVIEW",
                        reason_code="needs_human_review",
                    )
                )
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code="target_unresolved",
                )
            )

        if not self._supports_exact_target_state_verification(session.asset, selection):
            return _ExecutionResult(
                self._early_receipt(
                    session=session,
                    intent=intent,
                    outcome="BLOCKED",
                    reason_code="policy_blocked",
                )
            )

        try:
            resolution = dict(
                self._target_resolver.resolve(
                    session_id=session.snapshot.session_id,
                    selection=selection,
                    current_observation=current,
                )
            )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "target_resolution_failed",
            )
        resolution_status = resolution.get("status")
        if resolution_status != "resolved":
            reason = {
                "ambiguous": "grounding_ambiguous",
                "stale": "stale_candidate",
                "wrong_context": "capture_lineage_mismatch",
            }.get(str(resolution_status), "target_unresolved")
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code=reason,
                selection=selection,
            )
        grounding_value = resolution.get("grounding")
        if not isinstance(grounding_value, Mapping):
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code="target_unresolved",
                selection=selection,
            )
        grounding = dict(grounding_value)
        gate_context_value = resolution.get("gate_context", {})
        if not isinstance(gate_context_value, Mapping):
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code="pre_click_rejected",
                selection=selection,
                grounding=grounding,
            )
        try:
            gate_value = self._gate.evaluate(
                selection=selection,
                grounding=grounding,
                **dict(gate_context_value),
            )
        except (TypeError, ValueError):
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code="pre_click_rejected",
                selection=selection,
                grounding=grounding,
            )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "gate_evaluation_failed",
            )
        if not isinstance(gate_value, Mapping):
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code="pre_click_rejected",
                selection=selection,
                grounding=grounding,
            )
        try:
            gate = dict(gate_value)
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "gate_evaluation_failed",
            )
        try:
            validation = validate_current_grounding(
                session.asset,
                selection,
                grounding,
                gate,
                policy=self._grounding_policy,
            )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "grounding_validation_failed",
            )
        if validation.get("status") != "validated":
            failure_code = self._normalize_block_reason(
                str(validation.get("failure_code") or "pre_click_rejected")
            )
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code=failure_code,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_blocked=gate.get("allowed") is not True,
            )

        point = grounding["click_point"]
        click_point = (float(point["x"]), float(point["y"]))
        try:
            visibility = dict(
                self._window_visibility_checker.check(
                    session_id=session.snapshot.session_id,
                    capture_lineage=selection["capture_lineage"],
                    target_window_handle=session.snapshot.target_window_handle,
                    click_point=click_point,
                )
            )
        except Exception:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "visibility_check_failed",
            )
        bound_handle = visibility.get("bound_window_handle")
        point_visibility = visibility.get("point_visibility")
        reason = None
        if bound_handle != session.snapshot.target_window_handle:
            reason = "foreground_window_changed"
        elif not isinstance(point_visibility, Mapping) or point_visibility.get("allowed") is not True:
            reason = "target_occluded"
        if reason is not None:
            return self._blocked_receipt(
                session=session,
                intent=intent,
                reason_code=reason,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_blocked=True,
            )
        command = DesktopDispatchCommand(
            semantic_action=selection["semantic_action"],
            capture_id=grounding["capture_id"],
            candidate_id=grounding["candidate_id"],
            click_point=click_point,
            target_window_handle=session.snapshot.target_window_handle,
        )
        gate_ref = self._first_ref(gate.get("evidence_refs"), "gate")
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
        )
        try:
            self._intent_claim_store.mark_dispatch_started(
                session_id=session.snapshot.session_id,
                observation_id=observation.observation_id,
            )
        except RuntimeIntentClaimStoreError:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                "dispatch_marker_failed",
            )
        try:
            backend_receipt = self._backend.dispatch(command, authority=authority)
        except Exception:
            backend_receipt = BackendDispatchReceipt(
                receipt_ref=f"backend-receipt:exception:{uuid4().hex}",
                status="indeterminate",
                reason_code="backend_result_lost",
            )
            return self._indeterminate_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        if not self._is_valid_backend_receipt(backend_receipt):
            backend_receipt = BackendDispatchReceipt(
                receipt_ref=f"backend-receipt:invalid:{uuid4().hex}",
                status="indeterminate",
                reason_code="backend_result_lost",
            )
            return self._indeterminate_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        if backend_receipt.status == "indeterminate":
            return self._indeterminate_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        if backend_receipt.status != "dispatched":
            return self._execution_failed_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt=backend_receipt,
            )
        try:
            checkpoint_claim = self._intent_claim_store.mark_verification_pending(
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

    def _verify_pending_checkpoint(
        self,
        session: _LiveSession,
        intent: AgentIntentV1,
        checkpoint: RuntimeVerificationPendingCheckpoint,
    ) -> _ExecutionResult | LiveControllerDecision:
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

        selection = checkpoint.selection
        grounding = checkpoint.grounding
        gate = checkpoint.gate
        selection_ref = f"selection:{selection['selection_sha256']}"
        candidate_ref = f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}"
        receipt_id = f"receipt.{uuid4().hex}"
        trace_ref = f"trace:live-controller:{receipt_id}"
        server_refs = [
            selection_ref,
            candidate_ref,
            checkpoint.gate_decision_ref,
            checkpoint.backend_receipt.receipt_ref,
            trace_ref,
        ]
        try:
            verification = verify_server_dispatched_transition_result(
                session.asset,
                selection,
                checkpoint.current_observation,
                projected.current_observation,
                server_evidence_refs=server_refs,
            )
        except Exception:
            return LiveControllerDecision("RECOVERY_REQUIRED", "post_verification_integrity_failed")

        status = verification.get("status")
        failure = str(verification.get("failure_code") or "")
        if status == "blocked" and failure not in {
            "post_capture_not_new",
            "destination_mismatch",
            "post_action_failure",
        }:
            return LiveControllerDecision(
                "RECOVERY_REQUIRED",
                failure or "post_verification_integrity_failed",
            )
        if status not in {"verified", "blocked"}:
            return LiveControllerDecision("RECOVERY_REQUIRED", "post_verification_integrity_failed")

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
                    "trace_refs": [f"trace:live-controller:{receipt_id}"],
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

    @staticmethod
    def _release_window_lease(lease: _WindowLease) -> None:
        with _WINDOW_LEASE_LOCK:
            current = _WINDOW_LEASES.get(lease.target_window_handle)
            if current is lease:
                _WINDOW_LEASES.pop(lease.target_window_handle, None)


__all__ = [
    "LiveController",
    "LiveControllerDecision",
    "LiveSessionSnapshot",
    "ExistingWindowManagerVisibilityChecker",
    "ServerWorkflowBinding",
    "WindowVisibilityChecker",
]
