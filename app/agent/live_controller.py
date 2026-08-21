"""W4 server-owned Live Controller 的最小可执行纵切。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from app.agent.desktop_backend import (
    DesktopBackend,
    DesktopDispatchCommand,
    _mint_execution_authority,
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

    def __post_init__(self) -> None:
        if not self.workflow_id or not self.asset_id:
            raise ValueError("server workflow binding requires workflow_id and asset_id")


@dataclass(frozen=True, slots=True)
class LiveSessionSnapshot:
    session_id: str
    workflow: WorkflowRefV1
    current_observation: AgentObservationV1


@dataclass(frozen=True, slots=True)
class LiveControllerDecision:
    status: str
    reason_code: str


class AssetLoader(Protocol):
    def load_active(self, asset_id: str) -> dict[str, Any]: ...


class ObservationSource(Protocol):
    def create_initial(
        self,
        *,
        session_id: str,
        workflow: dict[str, Any],
    ) -> AgentObservationV1 | Mapping[str, object]: ...

    def capture_current(
        self,
        *,
        session_id: str,
        asset: dict[str, Any],
    ) -> Mapping[str, Any]: ...


class TargetResolver(Protocol):
    def resolve(
        self,
        *,
        selection: dict[str, Any],
        current_observation: dict[str, Any],
    ) -> Mapping[str, Any]: ...


class Gate(Protocol):
    def evaluate(
        self,
        *,
        selection: dict[str, Any],
        grounding: dict[str, Any],
    ) -> Mapping[str, Any]: ...


@dataclass(slots=True)
class _LiveSession:
    snapshot: LiveSessionSnapshot
    asset: dict[str, Any]
    consumed: bool = False


class LiveController:
    def __init__(
        self,
        *,
        binding: ServerWorkflowBinding,
        observation_source: ObservationSource,
        target_resolver: TargetResolver,
        gate: Gate,
        backend: DesktopBackend,
        grounding_policy: Mapping[str, Any],
        asset_loader: AssetLoader | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        if asset_loader is None:
            if project_root is None:
                raise ValueError("project_root is required when no trusted asset loader is provided")
            asset_loader = ReviewedWorkflowAssetStore(project_root=project_root)
        self._binding = binding
        self._asset_loader = asset_loader
        self._observation_source = observation_source
        self._target_resolver = target_resolver
        self._gate = gate
        self._backend = backend
        self._grounding_policy = dict(grounding_policy)
        self._sessions: dict[str, _LiveSession] = {}
        self._lock = RLock()

    def start_session(self) -> LiveSessionSnapshot:
        asset = validate_reviewed_workflow_asset(
            self._asset_loader.load_active(self._binding.asset_id)
        )
        if asset["asset_id"] != self._binding.asset_id:
            raise ValueError("active reviewed asset identity does not match server binding")
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
        projected = self._observation_source.create_initial(
            session_id=session_id,
            workflow=workflow.model_dump(mode="json"),
        )
        observation = (
            projected
            if isinstance(projected, AgentObservationV1)
            else validate_agent_observation_v1(projected)
        )
        if observation.session_id != session_id or observation.workflow != workflow:
            raise ValueError("server observation does not match pinned session workflow")
        if observation.application.kind != asset["application"]["kind"]:
            raise ValueError("server observation application does not match reviewed asset")
        snapshot = LiveSessionSnapshot(
            session_id=session_id,
            workflow=workflow,
            current_observation=observation,
        )
        with self._lock:
            self._sessions[session_id] = _LiveSession(snapshot=snapshot, asset=asset)
        return snapshot

    def submit_intent(
        self,
        payload: Mapping[str, object],
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        session_id = payload.get("session_id") if isinstance(payload, Mapping) else None
        with self._lock:
            session = self._sessions.get(session_id) if isinstance(session_id, str) else None
            if session is None:
                return LiveControllerDecision("REJECTED", "unknown_session")
            if session.consumed:
                return LiveControllerDecision("REJECTED", "observation_consumed")
            try:
                intent = validate_agent_intent_v1(
                    payload,
                    observation=session.snapshot.current_observation,
                )
            except (TypeError, ValueError):
                return LiveControllerDecision("REJECTED", "invalid_intent")
            session.consumed = True

        return self._execute_accepted_intent(session, intent)

    def _execute_accepted_intent(
        self,
        session: _LiveSession,
        intent: AgentIntentV1,
    ) -> RuntimeResultReceiptV1 | LiveControllerDecision:
        observation = session.snapshot.current_observation
        if intent.action_id == "runtime.safe_stop":
            return LiveControllerDecision("SAFE_STOP", "safe_stop_boundary")

        current = dict(
            self._observation_source.capture_current(
                session_id=session.snapshot.session_id,
                asset=session.asset,
            )
        )
        if current.get("capture_id") == observation.current_capture.capture_id:
            return LiveControllerDecision("BLOCKED", "stale_candidate")

        state_resolution = resolve_current_state(session.asset, current)
        if state_resolution.get("status") != "resolved":
            return LiveControllerDecision(
                "BLOCKED",
                str(state_resolution.get("failure_code") or "current_state_unresolved"),
            )
        selection = select_verified_transition(
            session.asset,
            state_resolution,
            transition_id=intent.action_id,
            current_observation=current,
        )
        if selection.get("status") != "selected":
            failure = str(selection.get("failure_code") or "target_unresolved")
            status = "NEEDS_REVIEW" if failure == "human_review_required" else "BLOCKED"
            return LiveControllerDecision(status, failure)

        resolution = dict(
            self._target_resolver.resolve(
                selection=selection,
                current_observation=current,
            )
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
        gate = dict(self._gate.evaluate(selection=selection, grounding=grounding))
        validation = validate_current_grounding(
            session.asset,
            selection,
            grounding,
            gate,
            policy=self._grounding_policy,
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
        command = DesktopDispatchCommand(
            semantic_action=selection["semantic_action"],
            capture_id=grounding["capture_id"],
            candidate_id=grounding["candidate_id"],
            click_point=(float(point["x"]), float(point["y"])),
        )
        gate_ref = self._first_ref(gate.get("evidence_refs"), "gate")
        authority = _mint_execution_authority(
            session_id=session.snapshot.session_id,
            observation_id=observation.observation_id,
            intent_id=intent.intent_id,
            selection_sha256=selection["selection_sha256"],
            capture_id=command.capture_id,
            candidate_id=command.candidate_id,
            click_point=command.click_point,
            gate_decision_ref=gate_ref,
        )
        try:
            backend_receipt = self._backend.dispatch(command, authority=authority)
        except Exception:
            return self._indeterminate_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt_ref=f"backend-receipt:exception:{uuid4().hex}",
            )
        if backend_receipt.status == "indeterminate":
            return self._indeterminate_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt_ref=backend_receipt.receipt_ref,
            )
        if backend_receipt.status != "dispatched":
            return self._execution_failed_receipt(
                session=session,
                intent=intent,
                selection=selection,
                grounding=grounding,
                gate_ref=gate_ref,
                backend_receipt_ref=backend_receipt.receipt_ref,
            )
        return self._receipt(
            session=session,
            intent=intent,
            outcome="DISPATCHED",
            reason_code="verification_pending",
            attempt_count=1,
            gate_status="allowed",
            dispatch_status="dispatched",
            selection_ref=f"selection:{selection['selection_sha256']}",
            candidate_ref=f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}",
            gate_ref=gate_ref,
            backend_ref=backend_receipt.receipt_ref,
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
    ) -> RuntimeResultReceiptV1:
        selection_ref = f"selection:{selection['selection_sha256']}"
        candidate_ref = None
        if grounding is not None and grounding.get("candidate_id"):
            candidate_ref = f"candidate:{grounding.get('capture_id')}:{grounding['candidate_id']}"
        gate_ref = self._first_ref(gate.get("evidence_refs") if gate else None, "gate") if gate_blocked else None
        return self._receipt(
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

    def _execution_failed_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate_ref: str,
        backend_receipt_ref: str,
    ) -> RuntimeResultReceiptV1:
        return self._receipt(
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
            backend_ref=backend_receipt_ref,
        )

    def _indeterminate_receipt(
        self,
        *,
        session: _LiveSession,
        intent: AgentIntentV1,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate_ref: str,
        backend_receipt_ref: str,
    ) -> RuntimeResultReceiptV1:
        return self._receipt(
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
            backend_ref=backend_receipt_ref,
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
    ) -> RuntimeResultReceiptV1:
        observation = session.snapshot.current_observation
        selected = next(item for item in observation.available_actions if item.action_id == intent.action_id)
        receipt_id = f"receipt.{uuid4().hex}"
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
                    "verification_ref": None,
                    "trace_refs": [f"trace:live-controller:{receipt_id}"],
                },
                "next_observation_id": None,
                "safe_stop": {"required": True, "reason_code": reason_code},
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


__all__ = [
    "LiveController",
    "LiveControllerDecision",
    "LiveSessionSnapshot",
    "ServerWorkflowBinding",
]
