"""W3b 的最小 durable Intent claim state machine。

该模块只记录 server-bound Observation/Intent 消费与结果关联。Claim 和 phase
marker 永远不授予桌面执行权，也不保存 bbox、click point 或 Gate authority。
Portfolio v1 仍是单一 live controller；敌对并发文件系统交换与分布式锁不在范围内。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import local, RLock
from typing import Any, Literal
from uuid import uuid4

import app.agent.runtime_receipt_store as durable_store
from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    WorkflowRefV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
    validate_runtime_result_receipt_v1,
)
from app.agent.runtime_receipt_store import (
    RuntimeReceiptRecord,
    RuntimeReceiptStore,
    RuntimeReceiptStoreError,
)
from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt, RuntimeFreshReceiptError
from app.agent.fresh_learning_action_contracts import (
    CLAIM_CONTRACT_VERSION as FRESH_CLAIM_CONTRACT_VERSION,
    FreshLearningActionContractError,
    FreshLearningClaimObservation,
    FreshLearningIntent,
    FreshLearningServerBinding,
    RuntimeFreshLearningClaimSnapshot,
    canonical_json_bytes as _fresh_canonical_json_bytes,
    payload_sha256 as _fresh_payload_sha256,
    validate_source_reference,
)
from app.agent.runtime_fresh_confirmation import (
    REQUEST_CONTRACT_VERSION as FRESH_GROUNDED_REQUEST_CONTRACT_VERSION,
    RuntimeFreshConfirmationError,
    RuntimeFreshLearningGroundedConfirmationSnapshot,
    build_closed_record as build_fresh_grounded_closed_record,
    build_decision_record as build_fresh_grounded_decision_record,
    build_request_record as build_fresh_grounded_request_record,
    validate_closed_record as validate_fresh_grounded_closed_record,
    validate_decision_record as validate_fresh_grounded_decision_record,
    validate_request_record as validate_fresh_grounded_request_record,
)
from app.agent.runtime_fresh_consume import (
    RuntimeFreshConsumeError,
    RuntimeFreshConsumeSnapshot,
    build_record as build_fresh_consume_record,
    content_sha256 as fresh_consume_content_sha256,
)
from app.agent.reviewed_workflow_asset import _exclusive_file_lock
from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
from app.agent.action_parameters import reviewed_action_parameter_fields
from app.agent.native_identity import validate_native_identity_fact
from app.agent.reviewed_workflow_replay import current_observation_contract_matches
from app.agent.text_field_evidence import validate_text_field_expectation_reference
from app.agent.text_parameters import validate_text_dispatch_geometry
from app.agent.runtime_grounded_confirmation import (
    RuntimeGroundedConfirmationError,
    RuntimeGroundedConfirmationSnapshot,
    build_closed_record,
    build_decision_record,
    build_request_record,
    canonical_json_bytes as _grounded_canonical_json_bytes,
    parse_utc as _parse_grounded_utc,
    snapshot_from_records as _grounded_snapshot_from_records,
    validate_closed_record,
    validate_decision_record,
    validate_preview_binding,
    validate_request_record,
)
from app.agent.runtime_grounded_consume import (
    RuntimeGroundedConsumeError,
    RuntimeGroundedConsumeSnapshot,
    build_consume_record,
    canonical_json_bytes as _consume_canonical_json_bytes,
    validate_consume_record,
    validate_fresh_preview,
)


CLAIM_CONTRACT_VERSION = "runtime_intent_claim_v1"
DISPATCH_MARKER_CONTRACT_VERSION = "runtime_intent_dispatch_started_v1"
VERIFICATION_PENDING_CONTRACT_VERSION = "runtime_intent_verification_pending_v2"
TERMINAL_MARKER_CONTRACT_VERSION = "runtime_intent_terminal_v1"
GROUNDED_DISPATCH_MARKER_CONTRACT_VERSION = "runtime_intent_grounded_dispatch_started_v1"
GROUNDED_VERIFICATION_PENDING_CONTRACT_VERSION = "runtime_intent_grounded_verification_pending_v1"
GROUNDED_TERMINAL_MARKER_CONTRACT_VERSION = "runtime_intent_grounded_terminal_v1"
CONFIRMATION_REQUEST_CONTRACT_VERSION = "runtime_intent_confirmation_request_v1"
CONFIRMATION_DECISION_CONTRACT_VERSION = "runtime_intent_confirmation_decision_v1"
CONFIRMATION_RESUME_CONTRACT_VERSION = "runtime_intent_confirmation_resume_started_v1"
CONFIRMATION_CLOSED_CONTRACT_VERSION = "runtime_intent_confirmation_closed_v1"
CONFIRMATION_TTL_SECONDS = 300
STORE_ROOT = Path("runtime_state/runtime-intent-claims-v1")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PHASE_LOCK = RLock()
_PHASE_FENCE_STATE = local()
_SERVER_CONFIRMATION_EVIDENCE_SEAL = object()
_GROUNDED_EXECUTION_EVIDENCE_SEAL = object()
_TERMINAL_RECEIPT_EVIDENCE_SEAL = object()


class RuntimeIntentClaimStoreError(ValueError):
    """Claim identity、phase 或持久化完整性失败。"""


class _PublishedBytesConflict(RuntimeIntentClaimStoreError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeVerifiedTerminalReceipt:
    """由 claim terminal marker 与 immutable receipt 共同证明的内部观察。"""

    session_id: str
    observation_id: str
    record: RuntimeReceiptRecord
    _seal: object = field(repr=False)

    def require_valid(self) -> None:
        if self._seal is not _TERMINAL_RECEIPT_EVIDENCE_SEAL:
            raise RuntimeIntentClaimStoreError(
                "terminal receipt observation is not claim-store verified"
            )
        if (
            self.record.runtime_receipt.session_id != self.session_id
            or self.record.runtime_receipt.observation_id != self.observation_id
        ):
            raise RuntimeIntentClaimStoreError(
                "terminal receipt observation scope mismatch"
            )


@dataclass(frozen=True, slots=True)
class RuntimeIntentServerBinding:
    workflow_id: str
    asset_id: str
    application_identity_key: str
    target_window_handle: int

    @classmethod
    def validate(
        cls,
        value: "RuntimeIntentServerBinding | Mapping[str, object]",
    ) -> "RuntimeIntentServerBinding":
        if isinstance(value, cls):
            candidate = value
        elif isinstance(value, Mapping):
            required = {
                "workflow_id",
                "asset_id",
                "application_identity_key",
                "target_window_handle",
            }
            if set(value) != required:
                raise RuntimeIntentClaimStoreError(
                    "server binding must be a strict four-field mapping"
                )
            candidate = cls(
                workflow_id=value["workflow_id"],  # type: ignore[arg-type]
                asset_id=value["asset_id"],  # type: ignore[arg-type]
                application_identity_key=value["application_identity_key"],  # type: ignore[arg-type]
                target_window_handle=value["target_window_handle"],  # type: ignore[arg-type]
            )
        else:
            raise RuntimeIntentClaimStoreError("server binding must be a strict mapping")
        for label, identity in (
            ("workflow", candidate.workflow_id),
            ("asset", candidate.asset_id),
        ):
            if not isinstance(identity, str) or _STABLE_ID_PATTERN.fullmatch(identity) is None:
                raise RuntimeIntentClaimStoreError(
                    f"server binding {label} identity is invalid"
                )
        if (
            not isinstance(candidate.application_identity_key, str)
            or not candidate.application_identity_key.strip()
            or candidate.application_identity_key != candidate.application_identity_key.strip()
            or len(candidate.application_identity_key) > 256
        ):
            raise RuntimeIntentClaimStoreError(
                "server binding application identity is invalid"
            )
        if (
            type(candidate.target_window_handle) is not int
            or candidate.target_window_handle <= 0
        ):
            raise RuntimeIntentClaimStoreError("server binding window handle is invalid")
        return candidate

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "asset_id": self.asset_id,
            "application_identity_key": self.application_identity_key,
            "target_window_handle": self.target_window_handle,
        }


@dataclass(frozen=True, slots=True)
class RuntimeVerificationPendingCheckpoint:
    """只读 verification resume 快照；属性每次返回独立 JSON 副本。"""

    claim_id: str
    claim_content_sha256: str
    checkpoint_sha256: str
    gate_decision_ref: str
    target_process_id: int
    backend_receipt: BackendDispatchReceipt
    _current_observation_json: bytes = field(repr=False)
    _selection_json: bytes = field(repr=False)
    _grounding_json: bytes = field(repr=False)
    _gate_json: bytes = field(repr=False)
    _scroll_capture_json: bytes | None = field(default=None, repr=False)
    _text_field_expectation_json: bytes | None = field(default=None, repr=False)
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False

    @staticmethod
    def _mapping(raw: bytes) -> dict[str, Any]:
        value = json.loads(raw.decode("utf-8"))
        assert isinstance(value, dict)
        return value

    @property
    def current_observation(self) -> dict[str, Any]:
        return self._mapping(self._current_observation_json)

    @property
    def scroll_capture(self) -> dict[str, Any] | None:
        return self._mapping(self._scroll_capture_json) if self._scroll_capture_json is not None else None

    @property
    def selection(self) -> dict[str, Any]:
        return self._mapping(self._selection_json)

    @property
    def grounding(self) -> dict[str, Any]:
        return self._mapping(self._grounding_json)

    @property
    def gate(self) -> dict[str, Any]:
        return self._mapping(self._gate_json)

    @property
    def text_field_expectation(self) -> dict[str, Any] | None:
        return (
            self._mapping(self._text_field_expectation_json)
            if self._text_field_expectation_json is not None
            else None
        )


@dataclass(frozen=True, slots=True)
class RuntimeIntentConfirmationSnapshot:
    confirmation_id: str
    request_content_sha256: str
    session_id: str
    observation_id: str
    intent_id: str
    workflow: WorkflowRefV1
    transition_id: str
    semantic_action: str
    request_capture_id: str
    request_screenshot_sha256: str
    request_state_resolution_sha256: str
    target_window_handle: int
    target_process_id: int
    requested_at: str
    expires_at: str
    decision: Literal["approved", "denied"] | None = None
    decision_content_sha256: str | None = None
    decided_at: str | None = None
    resume_attempt_id: str | None = None
    closed_reason_code: Literal["confirmation_expired", "confirmation_stale"] | None = None
    evidence_ref: str = ""
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False


@dataclass(frozen=True, slots=True)
class _ServerConfirmedTransitionEvidence:
    confirmation: RuntimeIntentConfirmationSnapshot
    _seal: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class _GroundedExecutionEvidence:
    confirmation_id: str
    request_content_sha256: str
    decision_content_sha256: str
    fresh_preview_content_sha256: str
    transition_id: str
    fresh_capture_id: str
    evidence_ref: str
    _seal: object = field(repr=False, compare=False)


def _unwrap_server_confirmed_transition_evidence(
    value: object,
) -> RuntimeIntentConfirmationSnapshot | None:
    if (
        not isinstance(value, _ServerConfirmedTransitionEvidence)
        or value._seal is not _SERVER_CONFIRMATION_EVIDENCE_SEAL
    ):
        return None
    return value.confirmation


def _unwrap_grounded_execution_evidence(
    value: object,
) -> _GroundedExecutionEvidence | None:
    if (
        not isinstance(value, _GroundedExecutionEvidence)
        or value._seal is not _GROUNDED_EXECUTION_EVIDENCE_SEAL
    ):
        return None
    return value


@dataclass(frozen=True, slots=True)
class RuntimeIntentClaimSnapshot:
    claim_id: str
    claim_content_sha256: str
    phase: Literal[
        "claimed",
        "confirmation_pending",
        "confirmation_approved",
        "confirmation_denied",
        "confirmation_resume_started",
        "confirmation_closed",
        "grounded_confirmation_pending",
        "grounded_confirmation_approved",
        "grounded_confirmation_denied",
        "grounded_confirmation_closed",
        "grounded_confirmation_consume_started",
        "dispatch_started",
        "verification_pending",
        "terminal",
    ]
    observation: AgentObservationV1
    intent: AgentIntentV1
    server_binding: RuntimeIntentServerBinding
    confirmation: RuntimeIntentConfirmationSnapshot | None
    verification_checkpoint: RuntimeVerificationPendingCheckpoint | None
    terminal_receipt_ref: dict[str, str] | None
    recovery_required: bool
    grants_action_authority: Literal[False] = False
    artifact_is_authorization: Literal[False] = False
    grounded_confirmation: RuntimeGroundedConfirmationSnapshot | None = None
    grounded_consume: RuntimeGroundedConsumeSnapshot | None = None


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeIntentClaimStoreError(
            f"runtime intent claim serialization failed: {exc}"
        ) from exc


def _payload_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


class RuntimeIntentClaimStore:
    """一个 Observation 只允许一个 immutable Intent claim。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        receipt_store: RuntimeReceiptStore,
        clock: Callable[[], datetime] | None = None,
        create_layout: bool = True,
    ) -> None:
        if type(create_layout) is not bool:
            raise TypeError("create_layout must be bool")
        self._create_layout = create_layout
        if not isinstance(receipt_store, RuntimeReceiptStore):
            raise RuntimeIntentClaimStoreError("receipt_store is required")
        self.project_root = Path(project_root).resolve()
        if receipt_store.project_root != self.project_root:
            raise RuntimeIntentClaimStoreError(
                "receipt_store must use the same project root"
            )
        self.root = self.project_root / STORE_ROOT
        self.claims_root = self.root / "claims"
        self.dispatch_started_root = self.root / "dispatch-started"
        self.verification_pending_root = self.root / "verification-pending"
        self.terminal_root = self.root / "terminal"
        self.confirmation_requests_root = self.root / "confirmation-requests"
        self.confirmation_decisions_root = self.root / "confirmation-decisions"
        self.confirmation_resume_root = self.root / "confirmation-resume-started"
        self.confirmation_closed_root = self.root / "confirmation-closed"
        self.grounded_requests_root = self.root / "grounded-requests"
        self.grounded_decisions_root = self.root / "grounded-decisions"
        self.grounded_closed_root = self.root / "grounded-closed"
        self.grounded_consume_root = self.root / "grounded-consume-started"
        self.phase_locks_root = self.root / "phase-locks"
        self._receipt_store = receipt_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._owner_instance_id = f"owner.{uuid4().hex}"
        self._terminal_receipt_observers: list[
            Callable[[RuntimeVerifiedTerminalReceipt], None]
        ] = []
        self._terminal_observer_lock = RLock()
        self._ensure_layout()

    def add_terminal_receipt_observer(
        self,
        observer: Callable[[RuntimeVerifiedTerminalReceipt], None],
    ) -> None:
        """增加只读 terminal 观察器；回调永远在 claim 文件锁之外运行。"""

        if not callable(observer):
            raise TypeError("terminal receipt observer must be callable")
        with self._terminal_observer_lock:
            if observer not in self._terminal_receipt_observers:
                self._terminal_receipt_observers.append(observer)

    def mark_grounded_confirmation_pending(
        self,
        *,
        session_id: str,
        observation_id: str,
        preview: GroundedActionPreview | object,
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            if self._claim_is_fresh(identity_hash):
                return self._mark_fresh_grounded_confirmation_pending(
                    identity_hash=identity_hash, session_id=session_id,
                    observation_id=observation_id, preview=preview,
                )
            base = self._load_claim(session_id, observation_id)
            try:
                requested_preview = validate_preview_binding(preview, base=base)
            except RuntimeGroundedConfirmationError as exc:
                raise RuntimeIntentClaimStoreError(str(exc)) from exc
            state = self._load_grounded_state(identity_hash, base=base)
            if state is not None and self._grounded_consume_path(identity_hash).exists():
                self._load_grounded_consume(identity_hash, base=base, grounded_state=state)
                raise RuntimeIntentClaimStoreError(
                    "grounded consume cannot return to confirmation pending"
                )
            self._reject_mixed_grounded_phases(
                identity_hash,
                grounded_present=state is not None,
            )
            if state is not None:
                self._reject_grounded_receipt_conflict(base)
                request_raw, request, persisted_preview, *_rest = state
                if persisted_preview.to_dict() != requested_preview:
                    raise RuntimeIntentClaimStoreError(
                        "grounded confirmation request conflict"
                    )
                return self.get_for_observation(
                    session_id=session_id,
                    observation_id=observation_id,
                )
            if self._has_any_legacy_phase_marker(identity_hash):
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation request conflicts with an existing phase"
                )
            if self._find_receipt(base) is not None:
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation request requires an unattempted claim"
                )
            confirmation_id = f"grounded-confirmation.{identity_hash}"
            try:
                marker = build_request_record(
                    base=base,
                    confirmation_id=confirmation_id,
                    preview=preview,
                    owner_instance_id=self._owner_instance_id,
                    requested_at=self._utc_now(),
                )
                self._publish_bytes(
                    self._grounded_request_path(identity_hash),
                    _grounded_canonical_json_bytes(marker),
                )
            except (RuntimeGroundedConfirmationError, _PublishedBytesConflict) as exc:
                if isinstance(exc, _PublishedBytesConflict):
                    message = "grounded confirmation request conflict"
                else:
                    message = str(exc)
                raise RuntimeIntentClaimStoreError(message) from exc
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def get_for_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            _, marker = self._read_canonical_json(
                self._grounded_request_path(identity_hash),
                label="grounded confirmation request",
            )
            session_id = marker.get("session_id")
            observation_id = marker.get("observation_id")
            if (
                not isinstance(session_id, str)
                or not isinstance(observation_id, str)
                or self._identity_hash(session_id, observation_id) != identity_hash
            ):
                raise RuntimeIntentClaimStoreError(
                    "invalid or tampered grounded confirmation request"
                )
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def _get_grounded_execution_evidence(
        self,
        *,
        confirmation_id: str,
        fresh_preview: GroundedActionPreview,
    ) -> _GroundedExecutionEvidence:
        """重读批准父链并封装仅限本进程 execution selector 的证明。"""
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._grounded_request_is_fresh(identity_hash):
                raise RuntimeIntentClaimStoreError(
                    "fresh learning grounded confirmation has no execution evidence"
                )
            base, state = self._load_grounded_by_identity(identity_hash)
            request_raw, request, approved_preview, _requested, expires, decision_raw, decision, closed = state
            if (
                closed is not None
                or decision_raw is None
                or decision is None
                or decision.get("decision") != "approved"
                or request.get("owner_instance_id") != self._owner_instance_id
                or self._utc_now() >= expires
                or self._grounded_consume_path(identity_hash).exists()
                or self._dispatch_path(identity_hash).exists()
                or self._verification_pending_path(identity_hash).exists()
                or self._terminal_path(identity_hash).exists()
                or self._find_receipt(base) is not None
            ):
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation is not eligible for fresh execution"
                )
            try:
                fresh = validate_fresh_preview(approved_preview, fresh_preview)
            except RuntimeGroundedConsumeError as exc:
                raise RuntimeIntentClaimStoreError(str(exc)) from exc
            proof_payload = {
                "confirmation_id": confirmation_id,
                "request_content_sha256": hashlib.sha256(request_raw).hexdigest(),
                "decision_content_sha256": hashlib.sha256(decision_raw).hexdigest(),
                "fresh_preview_content_sha256": fresh_preview.to_dict()["content_sha256"],
            }
            proof_sha = _payload_sha256(proof_payload)
            return _GroundedExecutionEvidence(
                **proof_payload,
                transition_id=base["intent"].action_id,
                fresh_capture_id=fresh["current_observation"]["current_capture"]["capture_id"],
                evidence_ref=f"grounded-confirmation-proof:{proof_sha}",
                _seal=_GROUNDED_EXECUTION_EVIDENCE_SEAL,
            )

    def begin_grounded_confirmation_consume(
        self,
        *,
        confirmation_id: str,
        fresh_preview: GroundedActionPreview,
        current_observation: Mapping[str, object],
        selection: Mapping[str, object],
        grounding: Mapping[str, object],
        execution_gate: Mapping[str, object],
        gate_decision_ref: str,
        target_process_id: int,
    ) -> RuntimeIntentClaimSnapshot:
        """原子封存批准后的 fresh execution bundle；本方法不派发。"""
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._grounded_request_is_fresh(identity_hash):
                raise RuntimeIntentClaimStoreError(
                    "fresh learning grounded confirmation cannot be consumed"
                )
            base, state = self._load_grounded_by_identity(identity_hash)
            request_raw, request, approved_preview, _requested, expires, decision_raw, decision, closed = state
            self._reject_grounded_receipt_conflict(base)
            if self._grounded_consume_path(identity_hash).exists():
                raise RuntimeIntentClaimStoreError("grounded consume has already started")
            if (
                closed is not None
                or decision_raw is None
                or decision is None
                or decision.get("decision") != "approved"
                or request.get("owner_instance_id") != self._owner_instance_id
                or self._utc_now() >= expires
                or self._dispatch_path(identity_hash).exists()
                or self._verification_pending_path(identity_hash).exists()
                or self._terminal_path(identity_hash).exists()
            ):
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation is not eligible for consume"
                )
            proof = self._get_grounded_execution_evidence(
                confirmation_id=confirmation_id,
                fresh_preview=fresh_preview,
            )
            if selection.get("human_confirmation_evidence_ref") != proof.evidence_ref:
                raise RuntimeIntentClaimStoreError("grounded execution proof mismatch")
            marker = build_consume_record(
                base=base,
                request=request,
                request_raw=request_raw,
                decision_raw=decision_raw,
                fresh_preview=fresh_preview,
                current_observation=current_observation,
                selection=selection,
                grounding=grounding,
                execution_gate=execution_gate,
                gate_decision_ref=gate_decision_ref,
                target_process_id=target_process_id,
                owner_instance_id=self._owner_instance_id,
                consume_attempt_id=f"grounded-consume-attempt.{uuid4().hex}",
                started_at=self._utc_now(),
            )
            try:
                validate_consume_record(
                    marker,
                    base=base,
                    request=request,
                    request_raw=request_raw,
                    decision=decision,
                    decision_raw=decision_raw,
                    approved_preview=approved_preview,
                )
                self._publish_bytes(
                    self._grounded_consume_path(identity_hash),
                    _consume_canonical_json_bytes(marker),
                )
            except RuntimeGroundedConsumeError as exc:
                raise RuntimeIntentClaimStoreError(str(exc)) from exc
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("grounded consume conflict") from exc
            return self.get_for_observation(
                session_id=request["session_id"],
                observation_id=request["observation_id"],
            )

    def record_grounded_confirmation_decision(
        self,
        *,
        confirmation_id: str,
        decision: Literal["approved", "denied"],
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot:
        if not isinstance(decision, str) or decision not in {"approved", "denied"}:
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation decision is invalid"
            )
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._grounded_request_is_fresh(identity_hash):
                return self._record_fresh_grounded_confirmation_decision(
                    identity_hash=identity_hash, decision=decision,
                )
            base, state = self._load_grounded_by_identity(identity_hash)
            self._reject_mixed_grounded_phases(identity_hash, grounded_present=True)
            if self._grounded_consume_path(identity_hash).exists():
                self._load_grounded_consume(identity_hash, base=base, grounded_state=state)
                raise RuntimeIntentClaimStoreError(
                    "grounded consume cannot return to confirmation decision"
                )
            self._reject_grounded_receipt_conflict(base)
            request_raw, request, _preview, _requested, expires, decision_raw, existing, closed = state
            if closed is not None:
                if existing is not None and existing.get("decision") == decision:
                    return self.get_for_observation(
                        session_id=request["session_id"],
                        observation_id=request["observation_id"],
                    )
                raise RuntimeIntentClaimStoreError(
                    "closed grounded confirmation cannot be approved or denied"
                )
            owner_changed = request["owner_instance_id"] != self._owner_instance_id
            now = self._utc_now()
            if existing is not None:
                if existing["decision"] != decision:
                    raise RuntimeIntentClaimStoreError(
                        "grounded confirmation decision conflict"
                    )
                if decision == "denied":
                    return self.get_for_observation(
                        session_id=request["session_id"],
                        observation_id=request["observation_id"],
                    )
                if owner_changed:
                    self._publish_grounded_closed(
                        identity_hash,
                        base=base,
                        request_raw=request_raw,
                        request=request,
                        decision_raw=decision_raw,
                        reason_code="grounded_confirmation_restarted",
                    )
                elif now >= expires:
                    self._publish_grounded_closed(
                        identity_hash,
                        base=base,
                        request_raw=request_raw,
                        request=request,
                        decision_raw=decision_raw,
                        reason_code="grounded_confirmation_expired",
                    )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if owner_changed and decision == "approved":
                self._publish_grounded_closed(
                    identity_hash,
                    base=base,
                    request_raw=request_raw,
                    request=request,
                    decision_raw=None,
                    reason_code="grounded_confirmation_restarted",
                )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if now >= expires:
                self._publish_grounded_closed(
                    identity_hash,
                    base=base,
                    request_raw=request_raw,
                    request=request,
                    decision_raw=None,
                    reason_code="grounded_confirmation_expired",
                )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            try:
                marker = build_decision_record(
                    base=base,
                    confirmation_id=confirmation_id,
                    request_content_sha256=hashlib.sha256(request_raw).hexdigest(),
                    decision=decision,
                    decided_at=now,
                )
                validate_decision_record(
                    marker,
                    base=base,
                    request=request,
                    request_raw=request_raw,
                )
                self._publish_bytes(
                    self._grounded_decision_path(identity_hash),
                    _grounded_canonical_json_bytes(marker),
                )
            except RuntimeGroundedConfirmationError as exc:
                raise RuntimeIntentClaimStoreError(str(exc)) from exc
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation decision conflict"
                ) from exc
            return self.get_for_observation(
                session_id=request["session_id"],
                observation_id=request["observation_id"],
            )

    def close_grounded_confirmation(
        self,
        *,
        confirmation_id: str,
        reason_code: str,
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot:
        allowed = {
            "grounded_confirmation_cancelled",
            "grounded_confirmation_expired",
            "grounded_confirmation_stale",
            "grounded_confirmation_restarted",
        }
        if not isinstance(reason_code, str) or reason_code not in allowed:
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation close reason is invalid"
            )
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._grounded_request_is_fresh(identity_hash):
                return self._close_fresh_grounded_confirmation(
                    identity_hash=identity_hash, reason_code=reason_code,
                )
            base, state = self._load_grounded_by_identity(identity_hash)
            self._reject_mixed_grounded_phases(identity_hash, grounded_present=True)
            if self._grounded_consume_path(identity_hash).exists():
                self._load_grounded_consume(identity_hash, base=base, grounded_state=state)
                raise RuntimeIntentClaimStoreError(
                    "grounded consume cannot be closed"
                )
            self._reject_grounded_receipt_conflict(base)
            request_raw, request, _preview, _requested, expires, decision_raw, decision_marker, closed = state
            if closed is not None:
                if closed["reason_code"] != reason_code:
                    raise RuntimeIntentClaimStoreError(
                        "grounded confirmation close conflict"
                    )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if decision_marker is not None and decision_marker["decision"] == "denied":
                raise RuntimeIntentClaimStoreError(
                    "denied grounded confirmation cannot be closed"
                )
            if (
                reason_code == "grounded_confirmation_expired"
                and self._utc_now() < expires
            ):
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation is not expired"
                )
            if (
                reason_code == "grounded_confirmation_restarted"
                and request["owner_instance_id"] == self._owner_instance_id
            ):
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation owner has not restarted"
                )
            self._publish_grounded_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request,
                decision_raw=decision_raw,
                reason_code=reason_code,
            )
            return self.get_for_observation(
                session_id=request["session_id"],
                observation_id=request["observation_id"],
            )

    def mark_confirmation_pending(
        self,
        *,
        session_id: str,
        observation_id: str,
        current_observation: Mapping[str, object],
        state_resolution: Mapping[str, object],
        transition_id: str,
        semantic_action: str,
        target_process_id: int,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_state(identity_hash, base=base)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot enter legacy confirmation"
                )
            request_path = self._confirmation_request_path(identity_hash)
            if (
                self._dispatch_path(identity_hash).exists()
                or self._terminal_path(identity_hash).exists()
                or self._find_receipt(base) is not None
            ):
                raise RuntimeIntentClaimStoreError(
                    "confirmation request requires an unattempted claim"
                )
            observation: AgentObservationV1 = base["observation"]
            intent: AgentIntentV1 = base["intent"]
            action = next(
                (item for item in observation.available_actions if item.action_id == intent.action_id),
                None,
            )
            capture_id = current_observation.get("capture_id")
            screenshot_sha256 = current_observation.get("screenshot_sha256")
            resolution_sha256 = state_resolution.get("resolution_sha256")
            if (
                transition_id != intent.action_id
                or action is None
                or semantic_action != action.semantic_action
                or action.requires_user_confirmation is not True
                or not isinstance(capture_id, str)
                or _STABLE_ID_PATTERN.fullmatch(capture_id) is None
                or not isinstance(screenshot_sha256, str)
                or _SHA256_PATTERN.fullmatch(screenshot_sha256) is None
                or not isinstance(resolution_sha256, str)
                or _SHA256_PATTERN.fullmatch(resolution_sha256) is None
            ):
                if action is not None and action.requires_user_confirmation is not True:
                    raise RuntimeIntentClaimStoreError(
                        "confirmation request action requires_user_confirmation must be true"
                    )
                raise RuntimeIntentClaimStoreError("confirmation request lineage is invalid")
            self._validate_target_process_id(target_process_id)
            if request_path.exists():
                existing = self.get_for_observation(
                    session_id=session_id,
                    observation_id=observation_id,
                )
                confirmation = existing.confirmation
                if confirmation is None or (
                    confirmation.transition_id != transition_id
                    or confirmation.semantic_action != semantic_action
                    or confirmation.request_capture_id != capture_id
                    or confirmation.request_screenshot_sha256 != screenshot_sha256
                    or confirmation.request_state_resolution_sha256 != resolution_sha256
                    or confirmation.target_process_id != target_process_id
                ):
                    raise RuntimeIntentClaimStoreError("confirmation request conflict")
                return existing
            now = self._utc_now()
            marker = {
                "store_contract_version": CONFIRMATION_REQUEST_CONTRACT_VERSION,
                "claim_id": base["claim_id"],
                "claim_content_sha256": base["claim_content_sha256"],
                "phase": "confirmation_pending",
                "confirmation_id": f"confirmation.{identity_hash}",
                "session_id": observation.session_id,
                "observation_id": observation.observation_id,
                "intent_id": intent.intent_id,
                "workflow": observation.workflow.model_dump(mode="json"),
                "transition_id": transition_id,
                "semantic_action": semantic_action,
                "request_capture_id": capture_id,
                "request_screenshot_sha256": screenshot_sha256,
                "request_state_resolution_sha256": resolution_sha256,
                "target_window_handle": base["server_binding"].target_window_handle,
                "target_process_id": target_process_id,
                "requested_at": self._format_time(now),
                "expires_at": self._format_time(
                    now + timedelta(seconds=CONFIRMATION_TTL_SECONDS)
                ),
                "artifact_is_authorization": False,
                "grants_action_authority": False,
            }
            marker["request_binding_sha256"] = _payload_sha256(marker)
            try:
                self._publish_bytes(request_path, _canonical_json_bytes(marker))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "confirmation request conflict"
                ) from exc
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def record_confirmation_decision(
        self,
        *,
        confirmation_id: str,
        decision: Literal["approved", "denied"],
    ) -> RuntimeIntentClaimSnapshot:
        if decision not in {"approved", "denied"}:
            raise RuntimeIntentClaimStoreError("confirmation decision is invalid")
        identity_hash = self._confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_by_identity(identity_hash)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot enter legacy confirmation"
                )
            request_raw, request = self._load_confirmation_request_by_identity(identity_hash)
            base = self._load_claim(request["session_id"], request["observation_id"])
            decision_path = self._confirmation_decision_path(identity_hash)
            decision_raw, existing = self._load_optional_confirmation_decision(
                identity_hash, base=base, request_raw=request_raw, request=request
            )
            if existing is not None and existing["decision"] != decision:
                raise RuntimeIntentClaimStoreError("confirmation decision conflict")
            closed = self._load_optional_confirmation_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request,
                decision_raw=decision_raw,
            )
            if closed is not None:
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if (
                existing is not None
                and self._confirmation_resume_path(identity_hash).exists()
            ):
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if self._utc_now() >= self._parse_time(request["expires_at"]):
                self._publish_confirmation_closed(
                    identity_hash,
                    base=base,
                    request_raw=request_raw,
                    request=request,
                    decision_raw=decision_raw,
                    reason_code="confirmation_expired",
                )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if decision_path.exists():
                assert existing is not None
                if existing["decision"] != decision:
                    raise RuntimeIntentClaimStoreError("confirmation decision conflict")
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            marker = {
                "store_contract_version": CONFIRMATION_DECISION_CONTRACT_VERSION,
                "claim_id": base["claim_id"],
                "claim_content_sha256": base["claim_content_sha256"],
                "phase": "confirmation_decided",
                "confirmation_id": confirmation_id,
                "request_content_sha256": hashlib.sha256(request_raw).hexdigest(),
                "decision": decision,
                "decided_at": self._format_time(self._utc_now()),
                "artifact_is_authorization": False,
                "grants_action_authority": False,
            }
            marker["decision_binding_sha256"] = _payload_sha256(marker)
            try:
                self._publish_bytes(decision_path, _canonical_json_bytes(marker))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("confirmation decision conflict") from exc
            return self.get_for_observation(
                session_id=request["session_id"], observation_id=request["observation_id"]
            )

    def get_for_confirmation(self, *, confirmation_id: str) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            _, request = self._load_confirmation_request_by_identity(identity_hash)
            return self.get_for_observation(
                session_id=request["session_id"],
                observation_id=request["observation_id"],
            )

    def _get_server_confirmed_transition_evidence(
        self,
        *,
        confirmation_id: str,
    ) -> _ServerConfirmedTransitionEvidence:
        claim = self.get_for_confirmation(confirmation_id=confirmation_id)
        confirmation = claim.confirmation
        if (
            claim.phase != "confirmation_resume_started"
            or confirmation is None
            or confirmation.decision != "approved"
            or confirmation.resume_attempt_id is None
            or not confirmation.evidence_ref
        ):
            raise RuntimeIntentClaimStoreError(
                "server confirmation evidence requires authoritative resume marker"
            )
        return _ServerConfirmedTransitionEvidence(
            confirmation=confirmation,
            _seal=_SERVER_CONFIRMATION_EVIDENCE_SEAL,
        )

    def begin_confirmation_resume(
        self,
        *,
        confirmation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_by_identity(identity_hash)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot enter legacy confirmation resume"
                )
            request_raw, request = self._load_confirmation_request_by_identity(identity_hash)
            base = self._load_claim(request["session_id"], request["observation_id"])
            decision_raw, decision = self._load_confirmation_decision(
                identity_hash, base=base, request_raw=request_raw, request=request
            )
            closed = self._load_optional_confirmation_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request,
                decision_raw=decision_raw,
            )
            if closed is not None:
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            if decision["decision"] != "approved":
                raise RuntimeIntentClaimStoreError("confirmation was not approved")
            if self._confirmation_resume_path(identity_hash).exists():
                raise RuntimeIntentClaimStoreError("confirmation resume already started")
            if self._utc_now() >= self._parse_time(request["expires_at"]):
                self._publish_confirmation_closed(
                    identity_hash,
                    base=base,
                    request_raw=request_raw,
                    request=request,
                    decision_raw=decision_raw,
                    reason_code="confirmation_expired",
                )
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            marker = {
                "store_contract_version": CONFIRMATION_RESUME_CONTRACT_VERSION,
                "claim_id": base["claim_id"],
                "claim_content_sha256": base["claim_content_sha256"],
                "phase": "confirmation_resume_started",
                "confirmation_id": confirmation_id,
                "request_content_sha256": hashlib.sha256(request_raw).hexdigest(),
                "decision_content_sha256": hashlib.sha256(decision_raw).hexdigest(),
                "resume_attempt_id": f"resume.{uuid4().hex}",
                "started_at": self._format_time(self._utc_now()),
                "artifact_is_authorization": False,
                "grants_action_authority": False,
            }
            marker["resume_binding_sha256"] = _payload_sha256(marker)
            try:
                published = self._publish_bytes(
                    self._confirmation_resume_path(identity_hash),
                    _canonical_json_bytes(marker),
                )
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "confirmation resume already started"
                ) from exc
            if not published:
                raise RuntimeIntentClaimStoreError("confirmation resume already started")
            return self.get_for_observation(
                session_id=request["session_id"], observation_id=request["observation_id"]
            )

    def close_confirmation(
        self,
        *,
        confirmation_id: str,
        reason_code: Literal["confirmation_expired", "confirmation_stale"],
    ) -> RuntimeIntentClaimSnapshot:
        if reason_code not in {"confirmation_expired", "confirmation_stale"}:
            raise RuntimeIntentClaimStoreError("confirmation close reason is invalid")
        identity_hash = self._confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_by_identity(identity_hash)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot enter legacy confirmation close"
                )
            request_raw, request = self._load_confirmation_request_by_identity(identity_hash)
            base = self._load_claim(request["session_id"], request["observation_id"])
            if (
                self._dispatch_path(identity_hash).exists()
                or self._verification_pending_path(identity_hash).exists()
                or self._terminal_path(identity_hash).exists()
                or self._find_receipt(base) is not None
            ):
                raise RuntimeIntentClaimStoreError(
                    "confirmation cannot close after dispatch_started"
                )
            decision_raw, _ = self._load_optional_confirmation_decision(
                identity_hash, base=base, request_raw=request_raw, request=request
            )
            closed = self._load_optional_confirmation_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request,
                decision_raw=decision_raw,
            )
            if closed is not None:
                if closed["reason_code"] != reason_code:
                    raise RuntimeIntentClaimStoreError("confirmation close conflict")
                return self.get_for_observation(
                    session_id=request["session_id"],
                    observation_id=request["observation_id"],
                )
            self._publish_confirmation_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request,
                decision_raw=decision_raw,
                reason_code=reason_code,
            )
            return self.get_for_observation(
                session_id=request["session_id"], observation_id=request["observation_id"]
            )

    def claim(
        self,
        *,
        observation: AgentObservationV1 | Mapping[str, object],
        intent: AgentIntentV1 | Mapping[str, object],
        server_binding: RuntimeIntentServerBinding | Mapping[str, object],
    ) -> RuntimeIntentClaimSnapshot:
        validated_observation = self._validate_observation(observation)
        validated_intent = self._validate_intent(
            intent,
            observation=validated_observation,
        )
        binding = RuntimeIntentServerBinding.validate(server_binding)
        self._validate_binding(
            observation=validated_observation,
            binding=binding,
        )
        identity_hash = self._identity_hash(
            validated_observation.session_id,
            validated_observation.observation_id,
        )
        claim_id = f"claim.{identity_hash}"
        observation_payload = validated_observation.model_dump(mode="json")
        intent_payload = validated_intent.model_dump(mode="json")
        binding_payload = binding.to_dict()
        record = {
            "store_contract_version": CLAIM_CONTRACT_VERSION,
            "claim_id": claim_id,
            "observation": observation_payload,
            "intent": intent_payload,
            "server_binding": binding_payload,
            "observation_sha256": _payload_sha256(observation_payload),
            "intent_sha256": _payload_sha256(intent_payload),
            "binding_sha256": _payload_sha256(binding_payload),
            "artifact_is_authorization": False,
        }
        with self._claim_phase_fence(identity_hash):
            path = self._claim_path(identity_hash)
            try:
                self._publish_bytes(path, _canonical_json_bytes(record))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim identity conflict"
                ) from exc
            return self.get_for_observation(
                session_id=validated_observation.session_id,
                observation_id=validated_observation.observation_id,
            )
    def claim_fresh_learning(
        self,
        *,
        observation: Mapping[str, object],
        intent: FreshLearningIntent | Mapping[str, object],
        source_reference: Mapping[str, object],
    ) -> RuntimeFreshLearningClaimSnapshot:
        try:
            checked_observation = FreshLearningClaimObservation.from_dict(observation)
            checked_intent = FreshLearningIntent.from_dict(
                intent.to_dict() if isinstance(intent, FreshLearningIntent) else intent)
            checked_source = validate_source_reference(source_reference)
            binding = FreshLearningServerBinding.from_source(checked_source)
        except FreshLearningActionContractError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        observed = checked_observation.to_dict()
        if (checked_intent.session_id != checked_observation.session_id
                or checked_intent.observation_id != checked_observation.observation_id
                or checked_intent.source_sha256 != checked_source["source_sha256"]
                or observed["source"] != checked_source):
            raise RuntimeIntentClaimStoreError("fresh learning intent or source binding mismatch")
        identity_hash = self._identity_hash(checked_observation.session_id,
                                            checked_observation.observation_id)
        record = {
            "store_contract_version": FRESH_CLAIM_CONTRACT_VERSION,
            "claim_id": f"claim.{identity_hash}",
            "observation": observed,
            "intent": checked_intent.to_dict(),
            "source_reference": checked_source,
            "server_binding": binding.to_dict(),
            "observation_sha256": _fresh_payload_sha256(observed),
            "intent_sha256": _fresh_payload_sha256(checked_intent.to_dict()),
            "source_reference_sha256": _fresh_payload_sha256(checked_source),
            "binding_sha256": _fresh_payload_sha256(binding.to_dict()),
            "artifact_is_authorization": False,
        }
        with self._claim_phase_fence(identity_hash):
            try:
                self._publish_bytes(self._claim_path(identity_hash),
                                    _fresh_canonical_json_bytes(record))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("fresh learning intent claim identity conflict") from exc
            return self._load_fresh_claim(checked_observation.session_id,
                                          checked_observation.observation_id)

    def mark_dispatch_started(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_state(identity_hash, base=base)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot dispatch"
                )
            if self._confirmation_request_path(identity_hash).exists():
                confirmation_claim = self.get_for_observation(
                    session_id=session_id,
                    observation_id=observation_id,
                )
                if confirmation_claim.phase != "confirmation_resume_started":
                    raise RuntimeIntentClaimStoreError(
                        "confirmation dispatch requires confirmation_resume_started"
                    )
            if self._terminal_path(identity_hash).exists():
                raise RuntimeIntentClaimStoreError(
                    "terminal claim cannot return to dispatch_started"
                )
            if self._verification_pending_path(identity_hash).exists():
                raise RuntimeIntentClaimStoreError(
                    "verification_pending claim cannot return to dispatch_started"
                )
            existing_receipt = self._find_receipt(base)
            if existing_receipt is not None:
                self._commit_terminal(base, existing_receipt)
                raise RuntimeIntentClaimStoreError(
                    "terminal claim cannot return to dispatch_started"
                )
            marker = self._dispatch_marker(base)
            try:
                self._publish_bytes(
                    self._dispatch_path(identity_hash),
                    _canonical_json_bytes(marker),
                )
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "dispatch_started phase conflict"
                ) from exc
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def terminalize(
        self,
        *,
        session_id: str,
        observation_id: str,
        receipt_ref: Mapping[str, object],
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_state(identity_hash, base=base)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot terminalize"
                )
            receipt = self._resolve_receipt(base, receipt_ref)
            self._commit_terminal(base, receipt)
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def mark_verification_pending(
        self,
        *,
        session_id: str,
        observation_id: str,
        current_observation: Mapping[str, object],
        selection: Mapping[str, object],
        grounding: Mapping[str, object],
        gate: Mapping[str, object],
        gate_decision_ref: str,
        backend_receipt: BackendDispatchReceipt,
        target_process_id: int,
        scroll_capture: Mapping[str, object] | None = None,
        text_field_expectation: Mapping[str, object] | None = None,
    ) -> RuntimeIntentClaimSnapshot:
        """封存 definitive dispatch 后只读 verification 所需的 server evidence。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_state(identity_hash, base=base)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot enter verification_pending"
                )
            if self._terminal_path(identity_hash).exists() or self._find_receipt(base) is not None:
                raise RuntimeIntentClaimStoreError(
                    "terminal claim cannot return to verification_pending"
                )
            dispatch_marker = self._load_optional_marker(
                self._dispatch_path(identity_hash),
                expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
                expected_phase="dispatch_started",
                base=base,
            )
            if dispatch_marker is None:
                raise RuntimeIntentClaimStoreError(
                    "verification_pending requires dispatch_started"
                )
            marker = self._verification_pending_marker(
                base,
                scroll_capture=scroll_capture,
                current_observation=current_observation,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_decision_ref=gate_decision_ref,
                backend_receipt=backend_receipt,
                target_process_id=target_process_id,
                text_field_expectation=text_field_expectation,
            )
            try:
                self._publish_bytes(
                    self._verification_pending_path(identity_hash),
                    _canonical_json_bytes(marker),
                )
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError(
                    "verification_pending phase conflict"
                ) from exc
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def mark_grounded_dispatch_started(
        self, *, confirmation_id: str, consume_content_sha256: str
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            base, state = self._load_grounded_by_identity(identity_hash)
            consume = self._load_grounded_consume(
                identity_hash, base=base, grounded_state=state
            )
            if consume is None or consume.content_sha256 != consume_content_sha256:
                raise RuntimeIntentClaimStoreError("grounded consume lineage mismatch")
            if (
                self._verification_pending_path(identity_hash).exists()
                or self._terminal_path(identity_hash).exists()
                or self._find_receipt(base) is not None
            ):
                raise RuntimeIntentClaimStoreError("grounded dispatch phase conflict")
            marker = {
                "store_contract_version": GROUNDED_DISPATCH_MARKER_CONTRACT_VERSION,
                "claim_id": base["claim_id"],
                "claim_content_sha256": base["claim_content_sha256"],
                "phase": "dispatch_started",
                "grounded_consume_ref": consume.evidence_ref,
                "artifact_is_authorization": False,
            }
            try:
                self._publish_bytes(
                    self._dispatch_path(identity_hash), _canonical_json_bytes(marker)
                )
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("grounded dispatch phase conflict") from exc
            return self.get_for_observation(
                session_id=state[1]["session_id"],
                observation_id=state[1]["observation_id"],
            )

    def mark_grounded_verification_pending(
        self,
        *,
        confirmation_id: str,
        consume_content_sha256: str,
        current_observation: Mapping[str, object],
        selection: Mapping[str, object],
        grounding: Mapping[str, object],
        gate: Mapping[str, object],
        gate_decision_ref: str,
        backend_receipt: BackendDispatchReceipt,
        target_process_id: int,
        scroll_capture: Mapping[str, object] | None = None,
        text_field_expectation: Mapping[str, object] | None = None,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            base, state = self._load_grounded_by_identity(identity_hash)
            consume = self._load_grounded_consume(
                identity_hash, base=base, grounded_state=state
            )
            if consume is None or consume.content_sha256 != consume_content_sha256:
                raise RuntimeIntentClaimStoreError("grounded consume lineage mismatch")
            dispatch = self._load_grounded_dispatch_marker(
                identity_hash, base=base, consume=consume
            )
            if dispatch is None:
                raise RuntimeIntentClaimStoreError(
                    "grounded verification_pending requires dispatch_started"
                )
            if self._terminal_path(identity_hash).exists() or self._find_receipt(base) is not None:
                raise RuntimeIntentClaimStoreError("grounded verification phase conflict")
            marker = self._verification_pending_marker(
                base,
                current_observation=current_observation,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_decision_ref=gate_decision_ref,
                backend_receipt=backend_receipt,
                target_process_id=target_process_id,
                grounded_consume_ref=consume.evidence_ref,
                scroll_capture=scroll_capture,
                text_field_expectation=text_field_expectation,
            )
            self._validate_grounded_checkpoint_bundle(marker, consume=consume)
            try:
                self._publish_bytes(
                    self._verification_pending_path(identity_hash),
                    _canonical_json_bytes(marker),
                )
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("grounded verification phase conflict") from exc
            return self.get_for_observation(
                session_id=state[1]["session_id"],
                observation_id=state[1]["observation_id"],
            )

    def find_for_observation(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot | None:
        """只在 canonical claim 确实不存在时返回 None。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        if not self._claim_path(identity_hash).exists():
            return None
        return self.get_for_observation(
            session_id=session_id,
            observation_id=observation_id,
        )

    def list_grounded_claims(self) -> tuple[RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot, ...]:
        """严格枚举并重读所有 grounded claim；不返回 legacy phase。"""
        try:
            paths = tuple(sorted(self.claims_root.iterdir(), key=lambda item: item.name))
        except OSError as exc:
            raise RuntimeIntentClaimStoreError("runtime intent claim inventory is unavailable") from exc
        grounded: list[RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot] = []
        for path in paths:
            if (path.parent != self.claims_root or path.suffix != ".json"
                    or _SHA256_PATTERN.fullmatch(path.stem) is None
                    or not path.is_file() or self._is_reparse(path)):
                raise RuntimeIntentClaimStoreError("runtime intent claim inventory contains an invalid entry")
            identity_hash = path.stem
            with self._claim_phase_fence(identity_hash):
                _, payload = self._read_canonical_json(path, label="intent claim")
                observation = payload.get("observation")
                if not isinstance(observation, Mapping):
                    raise RuntimeIntentClaimStoreError("runtime intent claim inventory identity is invalid")
                session_id, observation_id = observation.get("session_id"), observation.get("observation_id")
                if (not isinstance(session_id, str) or not isinstance(observation_id, str)
                        or self._identity_hash(session_id, observation_id) != identity_hash):
                    raise RuntimeIntentClaimStoreError("runtime intent claim inventory identity is invalid")
                snapshot = self.get_for_observation(session_id=session_id, observation_id=observation_id)
            if snapshot.grounded_confirmation is not None:
                grounded.append(snapshot)
        return tuple(sorted(grounded, key=lambda item: item.claim_id))

    def list_unresolved_claims(self) -> tuple[RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot, ...]:
        """严格校验并返回阻止新本地会话的 durable claims。"""

        try:
            paths = tuple(sorted(self.claims_root.iterdir(), key=lambda item: item.name))
        except OSError as exc:
            raise RuntimeIntentClaimStoreError(
                "runtime intent claim inventory is unavailable"
            ) from exc
        unresolved: list[RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot] = []
        unresolved_phases = {
            "claimed",
            "confirmation_pending",
            "confirmation_approved",
            "confirmation_resume_started",
            "dispatch_started",
            "verification_pending",
            "grounded_confirmation_pending",
            "grounded_confirmation_approved",
            "grounded_confirmation_consume_started",
        }
        for path in paths:
            if (
                path.parent != self.claims_root
                or path.suffix != ".json"
                or _SHA256_PATTERN.fullmatch(path.stem) is None
                or not path.is_file()
                or self._is_reparse(path)
            ):
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim inventory contains an invalid entry"
                )
            identity_hash = path.stem
            with self._claim_phase_fence(identity_hash):
                _, payload = self._read_canonical_json(path, label="intent claim")
                observation = payload.get("observation")
                if not isinstance(observation, Mapping):
                    raise RuntimeIntentClaimStoreError(
                        "runtime intent claim inventory identity is invalid"
                    )
                session_id = observation.get("session_id")
                observation_id = observation.get("observation_id")
                if (
                    not isinstance(session_id, str)
                    or not isinstance(observation_id, str)
                    or self._identity_hash(session_id, observation_id) != identity_hash
                ):
                    raise RuntimeIntentClaimStoreError(
                        "runtime intent claim inventory identity is invalid"
                    )
                snapshot = self.get_for_observation(
                    session_id=session_id,
                    observation_id=observation_id,
                )
            if snapshot.phase in unresolved_phases:
                unresolved.append(snapshot)
        return tuple(unresolved)

    def persist_terminal(
        self,
        *,
        session_id: str,
        observation_id: str,
        receipt: RuntimeResultReceiptV1,
        backend_receipt: BackendDispatchReceipt | None = None,
        verification_evidence: Mapping[str, object] | None = None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None = None,
    ) -> RuntimeResultReceiptV1:
        """先封存 Receipt record，再提交 terminal marker 并重读精确结果。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
            if self._has_any_grounded_marker(identity_hash):
                self._load_grounded_state(identity_hash, base=base)
                raise RuntimeIntentClaimStoreError(
                    "grounded confirmation cannot persist a terminal receipt"
                )
            self._validate_receipt_lineage(base, receipt)
            self._validate_terminal_phase(
                base,
                receipt,
                backend_receipt=backend_receipt,
                verification_evidence=verification_evidence,
                next_observation=next_observation,
            )
            try:
                receipt_ref = self._receipt_store.put(
                    receipt,
                    backend_receipt=backend_receipt,
                    verification_evidence=verification_evidence,
                    next_observation=next_observation,
                )
            except RuntimeReceiptStoreError as exc:
                raise RuntimeIntentClaimStoreError(
                    f"runtime receipt persistence failed: {exc}"
                ) from exc
            record = self._resolve_receipt(base, receipt_ref)
            self._commit_terminal(base, record)
        return self.load_terminal_receipt(
            session_id=session_id,
            observation_id=observation_id,
        )

    def persist_grounded_terminal(
        self,
        *,
        confirmation_id: str,
        consume_content_sha256: str,
        receipt: RuntimeResultReceiptV1,
        backend_receipt: BackendDispatchReceipt | None = None,
        verification_evidence: Mapping[str, object] | None = None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None = None,
    ) -> RuntimeResultReceiptV1:
        identity_hash = self._grounded_confirmation_identity_hash(confirmation_id)
        with self._claim_phase_fence(identity_hash):
            base, state = self._load_grounded_by_identity(identity_hash)
            consume = self._load_grounded_consume(
                identity_hash, base=base, grounded_state=state
            )
            if consume is None or consume.content_sha256 != consume_content_sha256:
                raise RuntimeIntentClaimStoreError("grounded consume lineage mismatch")
            self._validate_receipt_lineage(base, receipt)
            if consume.evidence_ref not in receipt.evidence.trace_refs:
                raise RuntimeIntentClaimStoreError(
                    "terminal receipt grounded consume evidence ref mismatch"
                )
            dispatch = self._load_grounded_dispatch_marker(
                identity_hash, base=base, consume=consume
            )
            checkpoint = self._load_verification_pending_marker(
                self._verification_pending_path(identity_hash),
                base=base,
                grounded_consume=consume,
            )
            self._validate_attempt_phase(
                receipt,
                dispatch_started=dispatch is not None,
                verification_pending=checkpoint is not None,
            )
            self._validate_checkpoint_receipt_pairing(
                base,
                checkpoint,
                receipt=receipt,
                backend_receipt=backend_receipt,
                verification_evidence=verification_evidence,
                next_observation=next_observation,
            )
            try:
                receipt_ref = self._receipt_store.put(
                    receipt,
                    backend_receipt=backend_receipt,
                    verification_evidence=verification_evidence,
                    next_observation=next_observation,
                )
            except RuntimeReceiptStoreError as exc:
                raise RuntimeIntentClaimStoreError(
                    f"runtime receipt persistence failed: {exc}"
                ) from exc
            record = self._resolve_receipt(base, receipt_ref)
            self._publish_grounded_terminal_marker(base, record, consume=consume)
            terminal_session_id = state[1]["session_id"]
            terminal_observation_id = state[1]["observation_id"]
        return self.load_terminal_receipt(
            session_id=terminal_session_id,
            observation_id=terminal_observation_id,
        )

    def load_terminal_receipt(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeResultReceiptV1 | RuntimeFreshResultReceipt:
        """解析 terminal marker 指向的权威 Receipt。"""

        record = self.load_terminal_receipt_record(
            session_id=session_id,
            observation_id=observation_id,
        )
        with self._terminal_observer_lock:
            observers = tuple(self._terminal_receipt_observers)
        for observer in observers:
            try:
                observer(
                    RuntimeVerifiedTerminalReceipt(
                        session_id=session_id,
                        observation_id=observation_id,
                        record=deepcopy(record),
                        _seal=_TERMINAL_RECEIPT_EVIDENCE_SEAL,
                    )
                )
            except Exception:
                # terminal 已提交；观察缺口由 recorder 的 durable pending-before 暴露。
                continue
        return record.runtime_receipt

    def persist_fresh_terminal(
        self, receipt: RuntimeFreshResultReceipt | Mapping[str, object],
        backend_receipt: BackendDispatchReceipt | None, *, next_observation: Mapping[str, object] | None = None,
    ) -> RuntimeFreshResultReceipt:
        try:
            checked = RuntimeFreshResultReceipt.from_dict(
                receipt.model_dump(mode="json") if isinstance(receipt, RuntimeFreshResultReceipt) else receipt)
        except RuntimeFreshReceiptError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        identity_hash = self._identity_hash(checked.session_id, checked.observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_fresh_claim(checked.session_id, checked.observation_id)
            consume = self._load_fresh_consume(identity_hash, base=base)
            if consume is None:
                raise RuntimeIntentClaimStoreError("fresh terminal requires consume")
            raw_dispatch, dispatch = self._read_canonical_json(self._dispatch_path(identity_hash), label="fresh dispatch")
            if (dispatch.get("store_contract_version") != "runtime_fresh_learning_dispatch_started_v1"
                    or dispatch.get("claim_id") != base.claim_id
                    or dispatch.get("grounded_consume_ref") != "fresh-grounded-consume:" + consume.content_sha256):
                raise RuntimeIntentClaimStoreError("fresh terminal requires fresh dispatch")
            if (checked.intent_id != base.intent.intent_id or checked.source_sha256 != base.server_binding.source_sha256
                    or checked.action.action_id != base.intent.action_id or checked.action.semantic_action != base.intent.semantic_action
                    or checked.evidence.consume_content_sha256 != consume.content_sha256
                    or checked.evidence.approved_preview_sha256 != consume.approved_preview_sha256
                    or checked.evidence.fresh_preview_sha256 != consume.fresh_preview_sha256
                    or checked.evidence.confirmation_id != consume.confirmation_id
                    or checked.evidence.capture_id != consume.capture_id):
                raise RuntimeIntentClaimStoreError("fresh terminal receipt lineage mismatch")
            self._validate_fresh_terminal_record(base, consume, checked, next_observation)
            ref = self._receipt_store.put(checked, backend_receipt=backend_receipt, next_observation=next_observation)
            record = self._receipt_store.get(ref)
            self._validate_fresh_terminal_record(base, consume, record.runtime_receipt, record.next_observation)
            marker = {"store_contract_version": "runtime_fresh_learning_terminal_v1", "claim_id": base.claim_id,
                "claim_content_sha256": base.claim_content_sha256, "phase": "terminal", "receipt_ref": ref,
                "grounded_consume_ref": "fresh-grounded-consume:" + consume.content_sha256,
                "artifact_is_authorization": False}
            try:
                self._publish_bytes(self._terminal_path(identity_hash), _fresh_canonical_json_bytes(marker))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("fresh terminal phase conflict") from exc
        loaded = self.load_terminal_receipt(session_id=checked.session_id, observation_id=checked.observation_id)
        if not isinstance(loaded, RuntimeFreshResultReceipt):
            raise RuntimeIntentClaimStoreError("fresh terminal reload returned reviewed receipt")
        return loaded

    def _fresh_terminal_ref(self, identity_hash: str, *, base: RuntimeFreshLearningClaimSnapshot) -> dict[str, str] | None:
        path = self._terminal_path(identity_hash)
        if not path.exists():
            return None
        _raw, marker = self._read_canonical_json(path, label="fresh terminal")
        ref = marker.get("receipt_ref")
        if (set(marker) != {"store_contract_version", "claim_id", "claim_content_sha256", "phase", "receipt_ref", "grounded_consume_ref", "artifact_is_authorization"}
                or marker.get("store_contract_version") != "runtime_fresh_learning_terminal_v1"
                or marker.get("claim_id") != base.claim_id or marker.get("claim_content_sha256") != base.claim_content_sha256
                or marker.get("phase") != "terminal" or marker.get("artifact_is_authorization") is not False
                or not isinstance(ref, Mapping) or set(ref) != {"receipt_id", "content_sha256"}):
            raise RuntimeIntentClaimStoreError("fresh terminal marker is invalid")
        return dict(ref)

    def _fresh_terminal_snapshot(self, base: RuntimeFreshLearningClaimSnapshot, identity_hash: str,
                                 record: RuntimeReceiptRecord) -> RuntimeFreshLearningClaimSnapshot:
        receipt = record.runtime_receipt
        if not isinstance(receipt, RuntimeFreshResultReceipt) or (receipt.session_id != base.observation.session_id
                or receipt.observation_id != base.observation.observation_id or receipt.intent_id != base.intent.intent_id):
            raise RuntimeIntentClaimStoreError("fresh terminal receipt is invalid")
        consume = self._load_fresh_consume(identity_hash, base=base)
        if consume is None:
            raise RuntimeIntentClaimStoreError("fresh terminal consume is unavailable")
        _raw, dispatch = self._read_canonical_json(self._dispatch_path(identity_hash), label="fresh dispatch")
        expected_dispatch = {
            "store_contract_version": "runtime_fresh_learning_dispatch_started_v1",
            "claim_id": base.claim_id, "claim_content_sha256": base.claim_content_sha256,
            "phase": "dispatch_started", "grounded_consume_ref": "fresh-grounded-consume:" + consume.content_sha256,
            "artifact_is_authorization": False,
        }
        if dispatch != expected_dispatch:
            raise RuntimeIntentClaimStoreError("fresh terminal dispatch binding mismatch")
        _raw, terminal = self._read_canonical_json(self._terminal_path(identity_hash), label="fresh terminal")
        expected_terminal = {
            **expected_dispatch, "store_contract_version": "runtime_fresh_learning_terminal_v1",
            "phase": "terminal", "receipt_ref": {
                "receipt_id": receipt.receipt_id, "content_sha256": record.content_sha256},
        }
        if terminal != expected_terminal:
            raise RuntimeIntentClaimStoreError("fresh terminal consume or receipt binding mismatch")
        self._validate_fresh_terminal_record(base, consume, receipt, record.next_observation)
        state = self._load_fresh_grounded_state(identity_hash, base=base, allow_receipt=True)
        # 本次读取已完整校验 consume；构造确认视图无需再读取和复验一次。
        confirmation = self._fresh_confirmation(state)
        return RuntimeFreshLearningClaimSnapshot(claim_id=base.claim_id, claim_content_sha256=base.claim_content_sha256,
            phase="terminal", observation=base.observation, intent=base.intent, server_binding=base.server_binding,
            grounded_confirmation=confirmation, grounded_consume=consume,
            terminal_receipt_id=receipt.receipt_id, recovery_required=False)

    def _validate_fresh_terminal_record(self, base: RuntimeFreshLearningClaimSnapshot,
                                        consume: RuntimeFreshConsumeSnapshot,
                                        receipt: RuntimeFreshResultReceipt,
                                        next_observation: object) -> None:
        preview = consume.fresh_preview.to_dict()
        decision = preview["pre_click_decision"]
        from app.agent.automatic_safety_policy import preview_action_selection, preview_automatic_safety_interception
        capture = preview["observation_evidence"]["capture"]
        candidate = "candidate:" + consume.capture_id + ":" + preview_action_selection(preview)["selected_candidate_id"]
        gate = "gate:" + _payload_sha256(decision)
        if (receipt.gate_status != ('allowed' if preview_automatic_safety_interception(preview) else 'manual_confirmed')
                or receipt.session_id != base.observation.session_id or receipt.observation_id != base.observation.observation_id
                or receipt.intent_id != base.intent.intent_id or receipt.source_sha256 != base.server_binding.source_sha256
                or receipt.action.action_id != base.intent.action_id or receipt.action.semantic_action != base.intent.semantic_action
                or receipt.evidence.source_sha256 != base.server_binding.source_sha256
                or receipt.evidence.approved_preview_sha256 != consume.approved_preview_sha256
                or receipt.evidence.fresh_preview_sha256 != consume.fresh_preview_sha256
                or receipt.evidence.consume_content_sha256 != consume.content_sha256
                or receipt.evidence.confirmation_id != consume.confirmation_id
                or receipt.evidence.capture_id != consume.capture_id
                or receipt.evidence.candidate_ref != candidate or receipt.evidence.gate_decision_ref != gate):
            raise RuntimeIntentClaimStoreError("fresh terminal factual evidence mismatch")
        if receipt.outcome == "ACTION_RECORDED":
            if not isinstance(next_observation, FreshLearningClaimObservation):
                raise RuntimeIntentClaimStoreError("fresh recorded terminal requires after observation")
            after = next_observation.to_dict()
            after_capture = after["capture"]
            if (after["source"] != base.observation.to_dict()["source"]
                    or after["application"] != preview["observation_evidence"]["application"]
                    or after_capture["capture_clock_id"] != capture["capture_clock_id"]
                    or after_capture["capture_id"] == consume.capture_id
                    or after_capture["capture_started_ns"] <= capture["observed_at_ns"]
                    or after_capture["viewport_size"] != capture["viewport_size"]
                    or receipt.next_observation_id != next_observation.observation_id):
                raise RuntimeIntentClaimStoreError("fresh terminal after observation binding mismatch")
        elif next_observation is not None or receipt.next_observation_id is not None:
            raise RuntimeIntentClaimStoreError("fresh non-recorded terminal cannot carry after observation")
        if base.intent.semantic_action == "scroll_region":
            from app.agent.fresh_learning_recording import fresh_preview_geometry
            proof = receipt.evidence.scroll_verification
            geometry = fresh_preview_geometry(consume.fresh_preview)
            if (not isinstance(proof, Mapping) or proof["scroll_parameters"] != base.intent.scroll_parameters
                    or proof["target_bbox"] != dict(zip(("x", "y", "width", "height"),
                        (geometry["bbox"][k] for k in ("x", "y", "w", "h"))))
                    or proof["before"]["image_sha256"] != capture["screenshot_sha256"]):
                raise RuntimeIntentClaimStoreError("fresh scroll proof differs from authoritative consume")
            if proof["after"] is not None:
                if (next_observation is None
                        or proof["after"]["capture_id"] != next_observation.to_dict()["capture"]["capture_id"]
                        or proof["after"]["image_sha256"] != next_observation.to_dict()["capture"]["screenshot_sha256"]):
                    raise RuntimeIntentClaimStoreError("fresh scroll proof differs from after observation")
        if base.intent.semantic_action == "fill_field":
            proof = receipt.evidence.text_field_verification
            if (receipt.evidence.text_parameters_ref != base.intent.text_parameters_ref
                    or receipt.evidence.text_parameters_ref != preview["intent"].get("text_parameters_ref")
                    or not isinstance(proof, Mapping)
                    or proof.get("expected") != preview.get("text_field_expectation_ref")):
                raise RuntimeIntentClaimStoreError("fresh terminal text evidence differs from authoritative consume")
            actual = proof["actual"]
            if actual is not None:
                if (not isinstance(next_observation, FreshLearningClaimObservation)
                        or actual["capture_id"] != next_observation.to_dict()["capture"]["capture_id"]
                        or actual["observed_at_ns"] < next_observation.to_dict()["capture"]["observed_at_ns"]):
                    raise RuntimeIntentClaimStoreError("fresh terminal text read differs from after capture")

    def load_terminal_receipt_record(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeReceiptRecord:
        """在同一 phase fence 内验证 terminal marker 与 immutable receipt。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            if self._claim_is_fresh(identity_hash):
                base = self._load_fresh_claim(session_id, observation_id)
                ref = self._fresh_terminal_ref(identity_hash, base=base)
                if ref is None:
                    raise RuntimeIntentClaimStoreError("fresh claim has no terminal receipt")
                record = self._receipt_store.get(ref)
                self._fresh_terminal_snapshot(base, identity_hash, record)
                return record
            snapshot = self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )
            if snapshot.phase != "terminal" or snapshot.terminal_receipt_ref is None:
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim has no terminal receipt"
                )
            base = self._load_claim(session_id, observation_id)
            return self._resolve_receipt(
                base,
                snapshot.terminal_receipt_ref,
            )

    def read_committed_terminal_evidence(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> tuple[RuntimeIntentClaimSnapshot, RuntimeReceiptRecord]:
        """同一阶段锁内只读已提交证据，不补建丢失的 terminal 标记。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            if not self._terminal_path(identity_hash).is_file():
                raise RuntimeIntentClaimStoreError("committed terminal marker is unavailable")
            if self._claim_is_fresh(identity_hash):
                base = self._load_fresh_claim(session_id, observation_id)
                ref = self._fresh_terminal_ref(identity_hash, base=base)
                if ref is None:
                    raise RuntimeIntentClaimStoreError("fresh terminal marker is unavailable")
                record = self._receipt_store.get(ref)
                return self._fresh_terminal_snapshot(base, identity_hash, record), record
            snapshot = self.get_for_observation(
                session_id=session_id, observation_id=observation_id,
            )
            if snapshot.phase != "terminal" or snapshot.terminal_receipt_ref is None:
                raise RuntimeIntentClaimStoreError("runtime intent claim has no committed terminal receipt")
            base = self._load_claim(session_id, observation_id)
            record = self._resolve_receipt(base, snapshot.terminal_receipt_ref)
            return snapshot, record

    def get_for_observation(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot | RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            if self._claim_is_fresh(identity_hash):
                fresh_base = self._load_fresh_claim(session_id, observation_id)
                terminal_ref = self._fresh_terminal_ref(identity_hash, base=fresh_base)
                if terminal_ref is not None:
                    return self._fresh_terminal_snapshot(fresh_base, identity_hash, self._receipt_store.get(terminal_ref))
                return self._fresh_snapshot(fresh_base, self._load_fresh_grounded_state(identity_hash, base=fresh_base))
            base = self._load_claim(session_id, observation_id)
            grounded_state = self._load_grounded_state(identity_hash, base=base)
            if grounded_state is not None:
                (
                    grounded_request_raw,
                    grounded_request,
                    grounded_preview,
                    _grounded_requested,
                    _grounded_expires,
                    grounded_decision_raw,
                    grounded_decision,
                    grounded_closed,
                ) = grounded_state
                grounded_snapshot = _grounded_snapshot_from_records(
                    request_raw=grounded_request_raw,
                    request=grounded_request,
                    preview=grounded_preview,
                    current_owner_instance_id=self._owner_instance_id,
                    decision_raw=grounded_decision_raw,
                    decision=grounded_decision,
                    closed=grounded_closed,
                )
                grounded_consume = self._load_grounded_consume(
                    identity_hash, base=base, grounded_state=grounded_state
                )
                if grounded_consume is not None:
                    if any(
                        path.exists()
                        for path in (
                            self._confirmation_request_path(identity_hash),
                            self._confirmation_decision_path(identity_hash),
                            self._confirmation_resume_path(identity_hash),
                            self._confirmation_closed_path(identity_hash),
                        )
                    ):
                        raise RuntimeIntentClaimStoreError(
                            "grounded consume conflicts with legacy confirmation"
                        )
                    dispatch_marker = self._load_grounded_dispatch_marker(
                        identity_hash, base=base, consume=grounded_consume
                    )
                    verification_marker = self._load_verification_pending_marker(
                        self._verification_pending_path(identity_hash),
                        base=base,
                        grounded_consume=grounded_consume,
                    )
                    if verification_marker is not None and dispatch_marker is None:
                        raise RuntimeIntentClaimStoreError(
                            "grounded verification_pending requires dispatch_started"
                        )
                    terminal_marker = self._load_grounded_terminal_marker(
                        identity_hash, base=base, consume=grounded_consume
                    )
                    receipt_record: RuntimeReceiptRecord | None
                    if terminal_marker is not None:
                        receipt_record = self._resolve_receipt(
                            base, terminal_marker["receipt_ref"]
                        )
                        self._validate_attempt_phase(
                            receipt_record.runtime_receipt,
                            dispatch_started=dispatch_marker is not None,
                            verification_pending=verification_marker is not None,
                        )
                    elif verification_marker is not None:
                        receipt_record = self._find_receipt(base)
                        if receipt_record is not None:
                            self._publish_grounded_terminal_marker(
                                base, receipt_record, consume=grounded_consume
                            )
                    else:
                        receipt_record = None
                    if receipt_record is not None:
                        if grounded_consume.evidence_ref not in receipt_record.runtime_receipt.evidence.trace_refs:
                            raise RuntimeIntentClaimStoreError(
                                "terminal receipt grounded consume evidence ref mismatch"
                            )
                        phase = "terminal"
                        terminal_ref = {
                            "receipt_id": receipt_record.runtime_receipt.receipt_id,
                            "content_sha256": receipt_record.content_sha256,
                        }
                    elif verification_marker is not None:
                        phase = "verification_pending"
                        terminal_ref = None
                    elif dispatch_marker is not None:
                        phase = "dispatch_started"
                        terminal_ref = None
                    else:
                        phase = "grounded_confirmation_consume_started"
                        terminal_ref = None
                    return RuntimeIntentClaimSnapshot(
                        claim_id=base["claim_id"],
                        claim_content_sha256=base["claim_content_sha256"],
                        phase=phase,
                        observation=base["observation"],
                        intent=base["intent"],
                        server_binding=base["server_binding"],
                        confirmation=None,
                        verification_checkpoint=(
                            self._checkpoint_snapshot(verification_marker)
                            if verification_marker is not None else None
                        ),
                        terminal_receipt_ref=terminal_ref,
                        recovery_required=phase != "terminal",
                        grounded_confirmation=grounded_snapshot,
                        grounded_consume=grounded_consume,
                    )
                self._reject_mixed_grounded_phases(
                    identity_hash,
                    grounded_present=True,
                )
                self._reject_grounded_receipt_conflict(base)
                if grounded_closed is not None:
                    grounded_phase = "grounded_confirmation_closed"
                elif grounded_decision is not None:
                    grounded_phase = (
                        "grounded_confirmation_approved"
                        if grounded_decision["decision"] == "approved"
                        else "grounded_confirmation_denied"
                    )
                else:
                    grounded_phase = "grounded_confirmation_pending"
                return RuntimeIntentClaimSnapshot(
                    claim_id=base["claim_id"],
                    claim_content_sha256=base["claim_content_sha256"],
                    phase=grounded_phase,
                    observation=base["observation"],
                    intent=base["intent"],
                    server_binding=base["server_binding"],
                    confirmation=None,
                    verification_checkpoint=None,
                    terminal_receipt_ref=None,
                    recovery_required=grounded_phase in {
                        "grounded_confirmation_pending",
                        "grounded_confirmation_approved",
                    },
                    grounded_confirmation=grounded_snapshot,
                )
            request_raw, request_marker = self._load_optional_confirmation_request(
                identity_hash, base=base
            )
            decision_raw: bytes | None = None
            decision_marker: dict[str, Any] | None = None
            if request_marker is not None:
                decision_raw, decision_marker = self._load_optional_confirmation_decision(
                    identity_hash,
                    base=base,
                    request_raw=request_raw,
                    request=request_marker,
                )
            resume_marker = self._load_optional_confirmation_resume(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request_marker,
                decision_raw=decision_raw,
                decision=decision_marker,
            )
            closed_marker = self._load_optional_confirmation_closed(
                identity_hash,
                base=base,
                request_raw=request_raw,
                request=request_marker,
                decision_raw=decision_raw,
            )
            dispatch_marker = self._load_optional_marker(
                self._dispatch_path(identity_hash),
                expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
                expected_phase="dispatch_started",
                base=base,
            )
            verification_marker = self._load_verification_pending_marker(
                self._verification_pending_path(identity_hash),
                base=base,
            )
            if verification_marker is not None and dispatch_marker is None:
                raise RuntimeIntentClaimStoreError(
                    "verification_pending requires dispatch_started"
                )
            terminal_marker = self._load_optional_marker(
                self._terminal_path(identity_hash),
                expected_contract=TERMINAL_MARKER_CONTRACT_VERSION,
                expected_phase="terminal",
                base=base,
            )
            receipt_record: RuntimeReceiptRecord | None = None
            if terminal_marker is not None:
                receipt_ref = terminal_marker.get("receipt_ref")
                if not isinstance(receipt_ref, Mapping):
                    raise RuntimeIntentClaimStoreError(
                        "terminal marker receipt ref is invalid"
                    )
                receipt_record = self._resolve_receipt(base, receipt_ref)
            else:
                receipt_record = self._find_receipt(base)
                if receipt_record is not None:
                    self._validate_attempt_phase(
                        receipt_record.runtime_receipt,
                        dispatch_started=dispatch_marker is not None,
                        verification_pending=verification_marker is not None,
                    )
                    self._publish_terminal_marker(base, receipt_record)
                    terminal_marker = self._load_optional_marker(
                        self._terminal_path(identity_hash),
                        expected_contract=TERMINAL_MARKER_CONTRACT_VERSION,
                        expected_phase="terminal",
                        base=base,
                    )
            if receipt_record is not None:
                confirmation_evidence_ref = self._confirmation_resume_evidence_ref(
                    base,
                    identity_hash,
                    pending_error=(
                        "terminal confirmation resume evidence is unavailable"
                    ),
                )
                self._validate_confirmation_receipt_evidence(
                    receipt_record.runtime_receipt,
                    confirmation_evidence_ref=confirmation_evidence_ref,
                )
                self._validate_attempt_phase(
                    receipt_record.runtime_receipt,
                    dispatch_started=dispatch_marker is not None,
                    verification_pending=verification_marker is not None,
                )
                phase = "terminal"
                terminal_ref = {
                    "receipt_id": receipt_record.runtime_receipt.receipt_id,
                    "content_sha256": receipt_record.content_sha256,
                }
            elif verification_marker is not None:
                phase = "verification_pending"
                terminal_ref = None
            elif dispatch_marker is not None:
                phase = "dispatch_started"
                terminal_ref = None
            elif closed_marker is not None:
                phase = "confirmation_closed"
                terminal_ref = None
            elif resume_marker is not None:
                phase = "confirmation_resume_started"
                terminal_ref = None
            elif decision_marker is not None:
                phase = (
                    "confirmation_approved"
                    if decision_marker["decision"] == "approved"
                    else "confirmation_denied"
                )
                terminal_ref = None
            elif request_marker is not None:
                phase = "confirmation_pending"
                terminal_ref = None
            else:
                phase = "claimed"
                terminal_ref = None
            return RuntimeIntentClaimSnapshot(
                claim_id=base["claim_id"],
                claim_content_sha256=base["claim_content_sha256"],
                phase=phase,
                observation=base["observation"],
                intent=base["intent"],
                server_binding=base["server_binding"],
                confirmation=(
                    self._confirmation_snapshot(
                        request_raw=request_raw,
                        request=request_marker,
                        decision_raw=decision_raw,
                        decision=decision_marker,
                        resume=resume_marker,
                        closed=closed_marker,
                        workflow=base["observation"].workflow,
                    )
                    if request_marker is not None and request_raw is not None
                    else None
                ),
                verification_checkpoint=(
                    self._checkpoint_snapshot(verification_marker)
                    if verification_marker is not None
                    else None
                ),
                terminal_receipt_ref=terminal_ref,
                recovery_required=phase in {
                    "claimed",
                    "confirmation_resume_started",
                    "dispatch_started",
                    "verification_pending",
                },
            )

    def _load_claim(self, session_id: str, observation_id: str) -> dict[str, Any]:
        identity_hash = self._identity_hash(session_id, observation_id)
        path = self._claim_path(identity_hash)
        raw, payload = self._read_canonical_json(path, label="intent claim")
        expected_keys = {
            "store_contract_version",
            "claim_id",
            "observation",
            "intent",
            "server_binding",
            "observation_sha256",
            "intent_sha256",
            "binding_sha256",
            "artifact_is_authorization",
        }
        if (
            set(payload) != expected_keys
            or payload.get("store_contract_version") != CLAIM_CONTRACT_VERSION
            or payload.get("artifact_is_authorization") is not False
        ):
            raise RuntimeIntentClaimStoreError("invalid runtime intent claim contract")
        expected_claim_id = f"claim.{identity_hash}"
        if payload.get("claim_id") != expected_claim_id:
            raise RuntimeIntentClaimStoreError("runtime intent claim identity mismatch")
        observation_payload = payload.get("observation")
        intent_payload = payload.get("intent")
        binding_payload = payload.get("server_binding")
        if not all(
            isinstance(value, Mapping)
            for value in (observation_payload, intent_payload, binding_payload)
        ):
            raise RuntimeIntentClaimStoreError("runtime intent claim payload is invalid")
        if payload.get("observation_sha256") != _payload_sha256(observation_payload):
            raise RuntimeIntentClaimStoreError("runtime intent claim observation hash tamper")
        if payload.get("intent_sha256") != _payload_sha256(intent_payload):
            raise RuntimeIntentClaimStoreError("runtime intent claim intent hash tamper")
        if payload.get("binding_sha256") != _payload_sha256(binding_payload):
            raise RuntimeIntentClaimStoreError("runtime intent claim binding hash tamper")
        observation = self._validate_observation(observation_payload)
        intent = self._validate_intent(intent_payload, observation=observation)
        binding = RuntimeIntentServerBinding.validate(binding_payload)
        self._validate_binding(observation=observation, binding=binding)
        if (
            observation.session_id != session_id
            or observation.observation_id != observation_id
        ):
            raise RuntimeIntentClaimStoreError("runtime intent claim lookup identity mismatch")
        return {
            "claim_id": expected_claim_id,
            "claim_content_sha256": hashlib.sha256(raw).hexdigest(),
            "observation": observation,
            "intent": intent,
            "server_binding": binding,
        }

    def _claim_is_fresh(self, identity_hash: str) -> bool:
        path = self._claim_path(identity_hash)
        if not path.exists():
            return False
        _raw, payload = self._read_canonical_json(path, label="intent claim")
        return payload.get("store_contract_version") == FRESH_CLAIM_CONTRACT_VERSION

    def _grounded_request_is_fresh(self, identity_hash: str) -> bool:
        path = self._grounded_request_path(identity_hash)
        if not path.exists():
            return False
        _raw, payload = self._read_canonical_json(path, label="grounded confirmation request")
        return payload.get("contract_version") == FRESH_GROUNDED_REQUEST_CONTRACT_VERSION

    def _load_fresh_claim(
        self, session_id: str, observation_id: str,
    ) -> RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        raw, payload = self._read_canonical_json(self._claim_path(identity_hash),
                                                  label="fresh learning intent claim")
        required = {"store_contract_version", "claim_id", "observation", "intent",
                    "source_reference", "server_binding", "observation_sha256",
                    "intent_sha256", "source_reference_sha256", "binding_sha256",
                    "artifact_is_authorization"}
        if (set(payload) != required
                or payload.get("store_contract_version") != FRESH_CLAIM_CONTRACT_VERSION
                or payload.get("claim_id") != f"claim.{identity_hash}"
                or payload.get("artifact_is_authorization") is not False):
            raise RuntimeIntentClaimStoreError("invalid fresh learning intent claim contract")
        values = (payload.get("observation"), payload.get("intent"),
                  payload.get("source_reference"), payload.get("server_binding"))
        if not all(isinstance(item, Mapping) for item in values):
            raise RuntimeIntentClaimStoreError("fresh learning intent claim payload is invalid")
        observation_payload, intent_payload, source_payload, binding_payload = values
        hashes = (("observation_sha256", observation_payload), ("intent_sha256", intent_payload),
                  ("source_reference_sha256", source_payload), ("binding_sha256", binding_payload))
        if any(payload.get(label) != _fresh_payload_sha256(item) for label, item in hashes):
            raise RuntimeIntentClaimStoreError("fresh learning intent claim hash tamper")
        try:
            observation = FreshLearningClaimObservation.from_dict(observation_payload)
            intent = FreshLearningIntent.from_dict(intent_payload)
            source = validate_source_reference(source_payload)
            binding = FreshLearningServerBinding.from_source(source)
        except FreshLearningActionContractError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        if (binding.to_dict() != binding_payload or observation.session_id != session_id
                or observation.observation_id != observation_id
                or observation.to_dict()["source"] != source
                or intent.session_id != session_id or intent.observation_id != observation_id
                or intent.source_sha256 != source["source_sha256"]):
            raise RuntimeIntentClaimStoreError("fresh learning intent claim binding mismatch")
        return RuntimeFreshLearningClaimSnapshot(
            claim_id=f"claim.{identity_hash}", claim_content_sha256=hashlib.sha256(raw).hexdigest(),
            phase="claimed", observation=observation, intent=intent, server_binding=binding,
        )

    def _validate_fresh_preview(self, preview: object, base: RuntimeFreshLearningClaimSnapshot) -> dict[str, Any]:
        try:
            from app.agent.fresh_learning_action_preview import validate_fresh_preview_binding
            checked = validate_fresh_preview_binding(
                preview, base.observation.to_dict(), base.intent.to_dict(),
                base.observation.to_dict()["source"],
            )
        except ImportError as exc:
            raise RuntimeIntentClaimStoreError("fresh learning preview contract is unavailable") from exc
        except ValueError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        if not isinstance(checked, Mapping):
            raise RuntimeIntentClaimStoreError("fresh learning preview validation is invalid")
        return dict(checked)

    def _fresh_receipt_conflict(self, base: RuntimeFreshLearningClaimSnapshot) -> None:
        try:
            record = self._receipt_store.find_for_intent(
                session_id=base.observation.session_id,
                observation_id=base.observation.observation_id,
                intent_id=base.intent.intent_id,
            )
        except RuntimeReceiptStoreError as exc:
            raise RuntimeIntentClaimStoreError("authoritative runtime receipt lookup failed") from exc
        if record is not None:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation has an authoritative receipt conflict")

    def _load_fresh_grounded_state(
        self, identity_hash: str, *, base: RuntimeFreshLearningClaimSnapshot, allow_receipt: bool = False,
    ) -> tuple[bytes, dict[str, Any], dict[str, Any], datetime, datetime, bytes | None,
               dict[str, Any] | None, dict[str, Any] | None] | None:
        if self._fresh_has_legacy_phase_marker(identity_hash):
            raise RuntimeIntentClaimStoreError("fresh claim has mixed legacy phase markers")
        if not allow_receipt:
            self._fresh_receipt_conflict(base)
        request_path, decision_path, closed_path = (self._grounded_request_path(identity_hash),
            self._grounded_decision_path(identity_hash), self._grounded_closed_path(identity_hash))
        if not request_path.exists():
            if decision_path.exists() or closed_path.exists():
                raise RuntimeIntentClaimStoreError("orphan fresh grounded confirmation marker is invalid")
            return None
        try:
            request_raw, request_value = self._read_canonical_json(request_path, label="fresh grounded confirmation request")
            request, preview, requested, expires = validate_fresh_grounded_request_record(
                request_value, base=base, identity_hash=identity_hash)
            if self._validate_fresh_preview(preview, base) != preview:
                raise RuntimeIntentClaimStoreError("fresh grounded preview binding mismatch")
            decision_raw = None
            decision = None
            if decision_path.exists():
                decision_raw, value = self._read_canonical_json(decision_path, label="fresh grounded confirmation decision")
                decision = validate_fresh_grounded_decision_record(value, request=request, request_raw=request_raw)
            closed = None
            if closed_path.exists():
                _closed_raw, value = self._read_canonical_json(closed_path, label="fresh grounded confirmation close")
                closed = validate_fresh_grounded_closed_record(value, request=request,
                    request_raw=request_raw, decision_raw=decision_raw)
        except RuntimeFreshConfirmationError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        return request_raw, request, preview, requested, expires, decision_raw, decision, closed

    def _fresh_confirmation(self, state) -> RuntimeFreshLearningGroundedConfirmationSnapshot:
        if state is None:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation is unavailable")
        request_raw, request, preview, requested, expires, _decision_raw, decision, closed = state
        phase = "pending" if decision is None else decision["decision"]
        if closed is not None:
            phase = "closed"
        return RuntimeFreshLearningGroundedConfirmationSnapshot(
            confirmation_id=request["confirmation_id"], phase=phase,
            preview=FreshLearningActionPreview.from_dict(preview),
            owner_instance_id=request["owner_instance_id"],
            owner_is_current=request["owner_instance_id"] == self._owner_instance_id,
            request_content_sha256=hashlib.sha256(request_raw).hexdigest(), requested_at=requested,
            expires_at=expires,
            decision=None if decision is None else decision["decision"],
            closed_reason_code=None if closed is None else closed["reason_code"],
        )

    def _fresh_snapshot(
        self, base: RuntimeFreshLearningClaimSnapshot,
        state: tuple[bytes, dict[str, Any], dict[str, Any], datetime, datetime, bytes | None,
                     dict[str, Any] | None, dict[str, Any] | None] | None,
    ) -> RuntimeFreshLearningClaimSnapshot:
        if state is None:
            return base
        confirmation = self._fresh_confirmation(state)
        phase = confirmation.phase
        identity_hash = self._identity_hash(base.observation.session_id, base.observation.observation_id)
        consume = self._load_fresh_consume(identity_hash, base=base)
        if consume is not None:
            dispatch_path = self._dispatch_path(identity_hash)
            if dispatch_path.exists():
                _raw, dispatch = self._read_canonical_json(dispatch_path, label="fresh dispatch")
                if (dispatch.get("store_contract_version") != "runtime_fresh_learning_dispatch_started_v1"
                        or dispatch.get("claim_id") != base.claim_id
                        or dispatch.get("grounded_consume_ref") != "fresh-grounded-consume:" + consume.content_sha256):
                    raise RuntimeIntentClaimStoreError("fresh dispatch marker is invalid")
                phase = "dispatch_started"
            else:
                phase = "grounded_confirmation_consume_started"
            return RuntimeFreshLearningClaimSnapshot(
                claim_id=base.claim_id, claim_content_sha256=base.claim_content_sha256, phase=phase,
                observation=base.observation, intent=base.intent, server_binding=base.server_binding,
                grounded_confirmation=confirmation, grounded_consume=consume, recovery_required=True,
            )
        return RuntimeFreshLearningClaimSnapshot(
            claim_id=base.claim_id, claim_content_sha256=base.claim_content_sha256,
            phase=f"grounded_confirmation_{phase}", observation=base.observation,
            intent=base.intent, server_binding=base.server_binding,
            grounded_confirmation=confirmation,
            recovery_required=phase == "pending",
        )

    def _mark_fresh_grounded_confirmation_pending(
        self, *, identity_hash: str, session_id: str, observation_id: str, preview: object,
    ) -> RuntimeFreshLearningClaimSnapshot:
        base = self._load_fresh_claim(session_id, observation_id)
        checked = self._validate_fresh_preview(preview, base)
        state = self._load_fresh_grounded_state(identity_hash, base=base)
        if state is not None:
            self._fresh_receipt_conflict(base)
            if state[2] != checked:
                raise RuntimeIntentClaimStoreError("fresh grounded confirmation request conflict")
            return self._fresh_snapshot(base, state)
        if self._has_any_legacy_phase_marker(identity_hash):
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation conflicts with an existing phase")
        self._fresh_receipt_conflict(base)
        try:
            marker = build_fresh_grounded_request_record(
                base=base, confirmation_id=f"grounded-confirmation.{identity_hash}", preview=checked,
                owner_instance_id=self._owner_instance_id, requested_at=self._utc_now(), ttl_seconds=300,
            )
            self._publish_bytes(self._grounded_request_path(identity_hash), _fresh_canonical_json_bytes(marker))
        except (RuntimeFreshConfirmationError, _PublishedBytesConflict) as exc:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation request conflict") from exc
        return self._fresh_snapshot(base, self._load_fresh_grounded_state(identity_hash, base=base))

    def begin_fresh_confirmation_consume(
        self, session_id: str, observation_id: str, *, fresh_preview: FreshLearningActionPreview,
        text_visual_proof=None, navigation_visual_proof=None, navigation_visibility=None,
    ) -> RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_fresh_claim(session_id, observation_id)
            state = self._load_fresh_grounded_state(identity_hash, base=base)
            if state is None:
                raise RuntimeIntentClaimStoreError("fresh grounded confirmation is unavailable")
            request_raw, request, approved, _requested, expires, decision_raw, decision, closed = state
            if (closed is not None or decision_raw is None or decision is None
                    or decision.get("decision") != "approved" or self._utc_now() >= expires
                    or request["owner_instance_id"] != self._owner_instance_id):
                raise RuntimeIntentClaimStoreError("fresh grounded confirmation is not eligible for consume")
            try:
                from app.agent.fresh_learning_action_preview import validate_fresh_execution_preview
                validate_fresh_execution_preview(approved, fresh_preview, text_visual_proof=text_visual_proof,
                    navigation_visual_proof=navigation_visual_proof)
                current = FreshLearningActionPreview.from_dict(fresh_preview).to_dict()
            except ImportError as exc:
                raise RuntimeIntentClaimStoreError("fresh execution preview comparator is unavailable") from exc
            except ValueError as exc:
                raise RuntimeIntentClaimStoreError(str(exc)) from exc
            try:
                marker = build_fresh_consume_record(base=base, request=request, request_raw=request_raw,
                    decision_raw=decision_raw, fresh_preview=dict(current))
                navigation_record = None
                if navigation_visual_proof is not None or navigation_visibility is not None:
                    from app.agent.navigation_visual_stability import (
                        NavigationVisualStabilityAttestation, navigation_visual_expectation,
                    )
                    from app.agent.fresh_learning_archive import FreshLearningObservationArchive
                    if (not isinstance(navigation_visibility, dict)
                            or set(navigation_visibility) != {'capture_source', 'proof'}
                            or type(navigation_visibility['proof']) is not NavigationVisualStabilityAttestation
                            or text_visual_proof is not None):
                        raise RuntimeIntentClaimStoreError('navigation consume requires a verified final visibility capture')
                    source = base.observation.to_dict()['source']
                    scope = {key: source[key] for key in ('connection_id', 'task_id', 'segment_id')}
                    final_packet = FreshLearningObservationArchive(self.project_root).read(navigation_visibility['capture_source'], **scope)
                    approved_data = FreshLearningActionPreview.from_dict(approved).to_dict()
                    final_evidence = final_packet.evidence()
                    if (final_evidence['recognition']['status'] != 'not_requested'
                            or final_evidence['capture']['capture_id'] == current['observation_evidence']['capture']['capture_id']
                            or final_evidence['capture']['capture_started_ns'] <= current['observation_evidence']['capture']['observed_at_ns']):
                        raise RuntimeIntentClaimStoreError('navigation final visibility must follow recognition')
                    navigation_visibility['proof'].validate_binding(approved_data['observation_evidence'], final_evidence,
                        navigation_visual_expectation(FreshLearningActionPreview.from_dict(approved)))
                    navigation_record = {'contract_version': 'fresh_navigation_visual_stability_record_v2',
                        'confirmation_id': request['confirmation_id'],
                        'approved_preview_sha256': request['preview_sha256'],
                        'fresh_preview_sha256': current['preview_sha256'],
                        'proof': navigation_visual_proof.to_reference() if navigation_visual_proof is not None else None,
                        'visibility': {'capture_source': navigation_visibility['capture_source'],
                            'proof': navigation_visibility['proof'].to_reference()}, 'artifact_is_authorization': False}
                    marker['contract_version'] = 'runtime_fresh_learning_grounded_consume_v2'
                    marker['navigation_proof_sha256'] = hashlib.sha256(_fresh_canonical_json_bytes(navigation_record)).hexdigest()
                raw = _fresh_canonical_json_bytes(marker)
                if text_visual_proof is not None:
                    # 先封存本地验证证明；该旁证不能恢复权限或代替消费标记。
                    proof_record = {'contract_version': 'fresh_text_visual_stability_record_v1',
                        'confirmation_id': request['confirmation_id'],
                        'approved_preview_sha256': request['preview_sha256'],
                        'fresh_preview_sha256': current['preview_sha256'],
                        'consume_content_sha256': hashlib.sha256(raw).hexdigest(),
                        'proof': text_visual_proof.to_reference(), 'artifact_is_authorization': False}
                    self._publish_bytes(self.root / f'text-visual-stability-{identity_hash}.json',
                        _fresh_canonical_json_bytes(proof_record))
                if navigation_record is not None:
                    navigation_record['consume_content_sha256'] = hashlib.sha256(raw).hexdigest()
                    self._publish_bytes(self.root / f'navigation-visual-stability-{identity_hash}.json',
                        _fresh_canonical_json_bytes(navigation_record))
                self._publish_bytes(self._grounded_consume_path(identity_hash), raw)
            except (_PublishedBytesConflict, RuntimeFreshConsumeError) as exc:
                raise RuntimeIntentClaimStoreError("fresh consume conflict") from exc
            digest = fresh_consume_content_sha256(marker)
            consume = RuntimeFreshConsumeSnapshot(request["confirmation_id"], digest,
                FreshLearningActionPreview.from_dict(marker["fresh_preview"]), marker["approved_preview_sha256"], marker["fresh_preview_sha256"],
                marker["source_sha256"], marker["capture_id"])
            return RuntimeFreshLearningClaimSnapshot(
                claim_id=base.claim_id, claim_content_sha256=base.claim_content_sha256,
                phase="grounded_confirmation_consume_started", observation=base.observation,
                intent=base.intent, server_binding=base.server_binding,
                grounded_confirmation=self._fresh_snapshot(base, state).grounded_confirmation,
                grounded_consume=consume, recovery_required=True,
            )

    def _validate_fresh_text_visual_record(self, identity_hash, *, base, marker, consume_raw, approved, current):
        from app.agent.fresh_learning_archive import FreshLearningObservationArchive
        from app.agent.text_visual_stability import verify_text_visual_stability_reference
        from app.agent.automatic_safety_policy import preview_automatic_safety_interception

        before = FreshLearningActionPreview.from_dict(approved).to_dict()
        after = current.to_dict()
        from app.agent.fresh_learning_action_preview import validate_text_execution_equivalence, validate_fresh_execution_preview
        path = self.root / f'text-visual-stability-{identity_hash}.json'
        if (not path.exists() and before['capture_source']['screenshot_sha256']
                == after['capture_source']['screenshot_sha256']):
            # 旧精确路径可无旁证，但 UIA 或目标差异仍不能借相同 PNG 绕过。
            try:
                validate_fresh_execution_preview(approved, current)
            except ValueError as exc:
                raise RuntimeIntentClaimStoreError('fresh text consume differs from the approved preview') from exc
            return
        try:
            _, record = self._read_canonical_json(path, label='fresh text visual proof')
            keys = {'contract_version', 'confirmation_id', 'approved_preview_sha256',
                'fresh_preview_sha256', 'consume_content_sha256', 'proof', 'artifact_is_authorization'}
            if (set(record) != keys or record['contract_version'] != 'fresh_text_visual_stability_record_v1'
                    or record['artifact_is_authorization'] is not False
                    or before['intent']['semantic_action'] != 'fill_field'
                    or after['intent']['semantic_action'] != 'fill_field'
                    or record['confirmation_id'] != marker['confirmation_id']
                    or record['approved_preview_sha256'] != marker['approved_preview_sha256']
                    or record['fresh_preview_sha256'] != after['preview_sha256']
                    or record['consume_content_sha256'] != hashlib.sha256(consume_raw).hexdigest()):
                raise ValueError('fresh text visual proof does not bind the consume record')
            source = base.observation.to_dict()['source']
            scope = {key: source[key] for key in ('connection_id', 'task_id', 'segment_id')}
            archive = FreshLearningObservationArchive(self.project_root)
            original_packet = archive.read(before['capture_source'], **scope)
            current_packet = archive.read(after['capture_source'], **scope)
            if (original_packet.evidence() != before['observation_evidence']
                    or current_packet.evidence() != after['observation_evidence']):
                raise ValueError('fresh text visual proof archived evidence differs')
            # 重开只回验事实和原图，不从旁证恢复可执行的本地证明对象。
            verify_text_visual_stability_reference(record['proof'], original_evidence=original_packet.evidence(),
                current_evidence=current_packet.evidence(), field_expectation_reference=before['text_field_expectation_ref'],
                original_png_bytes=original_packet.png_bytes, current_png_bytes=current_packet.png_bytes,
                original_uia_snapshot=before['uia_snapshot'], current_uia_snapshot=after['uia_snapshot'],
                automatic_safety_interception=preview_automatic_safety_interception(before))
            validate_text_execution_equivalence(approved, current, uia_stability=record['proof'].get('uia_stability'))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RuntimeIntentClaimStoreError('fresh text visual proof is missing, corrupt or mismatched') from exc

    def _validate_fresh_navigation_visual_record(self, identity_hash, *, base, marker, consume_raw, approved, current):
        from app.agent.fresh_learning_archive import FreshLearningObservationArchive
        from app.agent.fresh_learning_action_preview import (
            validate_fresh_execution_preview, validate_navigation_execution_equivalence,
        )
        from app.agent.navigation_visual_stability import (
            navigation_visual_expectation, verify_navigation_visual_stability_reference,
        )

        before = FreshLearningActionPreview.from_dict(approved).to_dict()
        after = current.to_dict()
        path = self.root / f'navigation-visual-stability-{identity_hash}.json'
        try:
            if not path.exists() and marker['contract_version'] == 'runtime_fresh_learning_grounded_consume_v1':
                # 即使图片摘要相同，点或来源变化也必须有可重算的封存证明。
                validate_fresh_execution_preview(approved, current)
                return
            _, record = self._read_canonical_json(path, label='fresh navigation visual proof')
            keys = {'contract_version', 'confirmation_id', 'approved_preview_sha256',
                'fresh_preview_sha256', 'consume_content_sha256', 'proof', 'visibility', 'artifact_is_authorization'}
            proof_hash = hashlib.sha256(_fresh_canonical_json_bytes({k: v for k, v in record.items()
                if k != 'consume_content_sha256'})).hexdigest()
            if (set(record) != keys or record['contract_version'] != 'fresh_navigation_visual_stability_record_v2'
                    or marker['contract_version'] != 'runtime_fresh_learning_grounded_consume_v2'
                    or marker.get('navigation_proof_sha256') != proof_hash
                    or record['artifact_is_authorization'] is not False
                    or record['confirmation_id'] != marker['confirmation_id']
                    or record['approved_preview_sha256'] != marker['approved_preview_sha256']
                    or record['fresh_preview_sha256'] != after['preview_sha256']
                    or record['consume_content_sha256'] != hashlib.sha256(consume_raw).hexdigest()):
                raise ValueError('fresh navigation proof does not bind the consume record')
            source = base.observation.to_dict()['source']
            scope = {key: source[key] for key in ('connection_id', 'task_id', 'segment_id')}
            archive = FreshLearningObservationArchive(self.project_root)
            original_packet = archive.read(before['capture_source'], **scope)
            current_packet = archive.read(after['capture_source'], **scope)
            if (original_packet.evidence() != before['observation_evidence']
                    or current_packet.evidence() != after['observation_evidence']):
                raise ValueError('fresh navigation archived evidence differs')
            expectation = navigation_visual_expectation(FreshLearningActionPreview.from_dict(approved))
            if record['proof'] is not None:
                verify_navigation_visual_stability_reference(record['proof'],
                    original_evidence=original_packet.evidence(), current_evidence=current_packet.evidence(),
                    expectation_reference=expectation,
                    original_png_bytes=original_packet.png_bytes, current_png_bytes=current_packet.png_bytes)
                validate_navigation_execution_equivalence(approved, current)
            else:
                validate_fresh_execution_preview(approved, current)
            visibility = record['visibility']
            if not isinstance(visibility, dict) or set(visibility) != {'capture_source', 'proof'}:
                raise ValueError('navigation final visibility reference is missing')
            final_packet = archive.read(visibility['capture_source'], **scope)
            final_evidence = final_packet.evidence()
            if (final_evidence['recognition']['status'] != 'not_requested'
                    or final_evidence['capture']['capture_id'] == after['observation_evidence']['capture']['capture_id']
                    or final_evidence['capture']['capture_started_ns'] <= after['observation_evidence']['capture']['observed_at_ns']):
                raise ValueError('navigation final visibility did not follow recognition')
            verify_navigation_visual_stability_reference(visibility['proof'],
                original_evidence=original_packet.evidence(), current_evidence=final_evidence,
                expectation_reference=expectation,
                original_png_bytes=original_packet.png_bytes, current_png_bytes=final_packet.png_bytes)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise RuntimeIntentClaimStoreError('fresh navigation visual proof is missing, corrupt or mismatched') from exc

    def _load_fresh_consume(self, identity_hash: str, *, base: RuntimeFreshLearningClaimSnapshot) -> RuntimeFreshConsumeSnapshot | None:
        path = self._grounded_consume_path(identity_hash)
        if not path.exists():
            return None
        _raw, marker = self._read_canonical_json(path, label="fresh grounded consume")
        required = {"contract_version", "confirmation_id", "claim_id", "claim_content_sha256",
            "request_content_sha256", "decision_content_sha256", "approved_preview_sha256",
            "fresh_preview_sha256", "fresh_preview", "source_sha256", "capture_id",
            "artifact_is_authorization", "execute_binding_enabled", "action_executed"}
        if marker.get('contract_version') == 'runtime_fresh_learning_grounded_consume_v2':
            required.add('navigation_proof_sha256')
        if (set(marker) != required or marker.get("contract_version") not in {
                "runtime_fresh_learning_grounded_consume_v1", "runtime_fresh_learning_grounded_consume_v2"}
                or marker.get("claim_id") != base.claim_id or marker.get("claim_content_sha256") != base.claim_content_sha256
                or marker.get("source_sha256") != base.server_binding.source_sha256
                or any(marker.get(k) is not False for k in ("artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
            raise RuntimeIntentClaimStoreError("fresh grounded consume contract is invalid or mixed")
        try:
            preview = FreshLearningActionPreview.from_dict(marker.get("fresh_preview"))
        except ValueError as exc:
            raise RuntimeIntentClaimStoreError("fresh grounded consume preview is invalid") from exc
        if preview.content_sha256 != marker.get("fresh_preview_sha256"):
            raise RuntimeIntentClaimStoreError("fresh grounded consume preview binding mismatch")
        state = self._load_fresh_grounded_state(identity_hash, base=base, allow_receipt=True)
        if state is None:
            raise RuntimeIntentClaimStoreError("fresh grounded consume request is unavailable")
        request_raw, request, approved, _requested, _expires, decision_raw, decision, closed = state
        if (closed is not None or decision_raw is None or decision is None or decision.get("decision") != "approved"
                or marker.get("confirmation_id") != request.get("confirmation_id")
                or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
                or marker.get("decision_content_sha256") != hashlib.sha256(decision_raw).hexdigest()
                or marker.get("approved_preview_sha256") != request.get("preview_sha256")):
            raise RuntimeIntentClaimStoreError("fresh grounded consume request or decision linkage mismatch")
        before = FreshLearningActionPreview.from_dict(approved).to_dict()
        navigation_record = self.root / f'navigation-visual-stability-{identity_hash}.json'
        if (navigation_record.exists() or marker['contract_version'] == 'runtime_fresh_learning_grounded_consume_v2'
                or before['contract_version'] in {'fresh_learning_action_preview_v2', 'fresh_learning_action_preview_v3'}
                and before['intent']['semantic_action'] == 'open_detail'):
            self._validate_fresh_navigation_visual_record(identity_hash, base=base, marker=marker,
                consume_raw=_raw, approved=approved, current=preview)
        else:
            self._validate_fresh_text_visual_record(identity_hash, base=base, marker=marker,
                consume_raw=_raw, approved=approved, current=preview)
        return RuntimeFreshConsumeSnapshot(marker["confirmation_id"], hashlib.sha256(_raw).hexdigest(), preview,
            marker["approved_preview_sha256"], marker["fresh_preview_sha256"], marker["source_sha256"], marker["capture_id"])

    def mark_fresh_dispatch_started(self, session_id: str, observation_id: str) -> RuntimeFreshLearningClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_fresh_claim(session_id, observation_id)
            consume = self._load_fresh_consume(identity_hash, base=base)
            if consume is None:
                raise RuntimeIntentClaimStoreError("fresh dispatch requires consume")
            marker = {"store_contract_version": "runtime_fresh_learning_dispatch_started_v1", "claim_id": base.claim_id,
                "claim_content_sha256": base.claim_content_sha256, "phase": "dispatch_started",
                "grounded_consume_ref": "fresh-grounded-consume:" + consume.content_sha256,
                "artifact_is_authorization": False}
            try:
                self._publish_bytes(self._dispatch_path(identity_hash), _fresh_canonical_json_bytes(marker))
            except _PublishedBytesConflict as exc:
                raise RuntimeIntentClaimStoreError("fresh dispatch phase conflict") from exc
            return RuntimeFreshLearningClaimSnapshot(claim_id=base.claim_id, claim_content_sha256=base.claim_content_sha256,
                phase="dispatch_started", observation=base.observation, intent=base.intent, server_binding=base.server_binding,
                grounded_consume=consume, recovery_required=True)

    def _load_fresh_grounded_by_identity(
        self, identity_hash: str,
    ) -> tuple[RuntimeFreshLearningClaimSnapshot, tuple[bytes, dict[str, Any], dict[str, Any], datetime,
                                                        datetime, bytes | None, dict[str, Any] | None, dict[str, Any] | None]]:
        _raw, marker = self._read_canonical_json(self._grounded_request_path(identity_hash),
            label="fresh grounded confirmation request")
        session_id, observation_id = marker.get("session_id"), marker.get("observation_id")
        if (not isinstance(session_id, str) or not isinstance(observation_id, str)
                or self._identity_hash(session_id, observation_id) != identity_hash):
            raise RuntimeIntentClaimStoreError("invalid fresh grounded confirmation request")
        base = self._load_fresh_claim(session_id, observation_id)
        state = self._load_fresh_grounded_state(identity_hash, base=base)
        if state is None:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation request is unavailable")
        return base, state

    def _publish_fresh_grounded_closed(self, identity_hash: str, *, request: Mapping[str, Any],
                                       request_raw: bytes, decision_raw: bytes | None, reason_code: str) -> None:
        try:
            marker = build_fresh_grounded_closed_record(request=request, request_raw=request_raw,
                decision_raw=decision_raw, reason_code=reason_code, closed_at=self._utc_now())
            validate_fresh_grounded_closed_record(marker, request=request, request_raw=request_raw,
                                                   decision_raw=decision_raw)
            self._publish_bytes(self._grounded_closed_path(identity_hash), _fresh_canonical_json_bytes(marker))
        except (RuntimeFreshConfirmationError, _PublishedBytesConflict) as exc:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation close conflict") from exc

    def _record_fresh_grounded_confirmation_decision(
        self, *, identity_hash: str, decision: Literal["approved", "denied"],
    ) -> RuntimeFreshLearningClaimSnapshot:
        base, state = self._load_fresh_grounded_by_identity(identity_hash)
        self._fresh_receipt_conflict(base)
        request_raw, request, _preview, _requested, expires, decision_raw, existing, closed = state
        if closed is not None:
            if existing is not None and existing["decision"] == decision:
                return self._fresh_snapshot(base, state)
            raise RuntimeIntentClaimStoreError("closed fresh grounded confirmation cannot be decided")
        owner_changed, expired = request["owner_instance_id"] != self._owner_instance_id, self._utc_now() >= expires
        if existing is not None:
            if existing["decision"] != decision:
                raise RuntimeIntentClaimStoreError("fresh grounded confirmation decision conflict")
            if decision == "approved" and (owner_changed or expired):
                self._publish_fresh_grounded_closed(identity_hash, request=request, request_raw=request_raw,
                    decision_raw=decision_raw, reason_code=("grounded_confirmation_restarted" if owner_changed else "grounded_confirmation_expired"))
            return self.get_for_observation(session_id=base.observation.session_id, observation_id=base.observation.observation_id)
        if decision == "approved" and owner_changed:
            self._publish_fresh_grounded_closed(identity_hash, request=request, request_raw=request_raw,
                decision_raw=None, reason_code="grounded_confirmation_restarted")
            return self.get_for_observation(session_id=base.observation.session_id, observation_id=base.observation.observation_id)
        if expired:
            self._publish_fresh_grounded_closed(identity_hash, request=request, request_raw=request_raw,
                decision_raw=None, reason_code="grounded_confirmation_expired")
            return self.get_for_observation(session_id=base.observation.session_id, observation_id=base.observation.observation_id)
        try:
            marker = build_fresh_grounded_decision_record(confirmation_id=request["confirmation_id"],
                request_raw=request_raw, decision=decision, decided_at=self._utc_now())
            validate_fresh_grounded_decision_record(marker, request=request, request_raw=request_raw)
            self._publish_bytes(self._grounded_decision_path(identity_hash), _fresh_canonical_json_bytes(marker))
        except (RuntimeFreshConfirmationError, _PublishedBytesConflict) as exc:
            raise RuntimeIntentClaimStoreError("fresh grounded confirmation decision conflict") from exc
        return self.get_for_observation(session_id=base.observation.session_id, observation_id=base.observation.observation_id)

    def _close_fresh_grounded_confirmation(self, *, identity_hash: str, reason_code: str) -> RuntimeFreshLearningClaimSnapshot:
        base, state = self._load_fresh_grounded_by_identity(identity_hash)
        self._fresh_receipt_conflict(base)
        request_raw, request, _preview, _requested, _expires, decision_raw, _decision, closed = state
        if closed is not None:
            if closed["reason_code"] != reason_code:
                raise RuntimeIntentClaimStoreError("fresh grounded confirmation close conflict")
            return self._fresh_snapshot(base, state)
        self._publish_fresh_grounded_closed(identity_hash, request=request, request_raw=request_raw,
            decision_raw=decision_raw, reason_code=reason_code)
        return self.get_for_observation(session_id=base.observation.session_id, observation_id=base.observation.observation_id)

    def _find_receipt(self, base: Mapping[str, Any]) -> RuntimeReceiptRecord | None:
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        try:
            record = self._receipt_store.find_for_intent(
                session_id=observation.session_id,
                observation_id=observation.observation_id,
                intent_id=intent.intent_id,
            )
        except RuntimeReceiptStoreError as exc:
            raise RuntimeIntentClaimStoreError(
                f"authoritative runtime receipt lookup failed: {exc}"
            ) from exc
        if record is not None:
            self._validate_receipt_lineage(base, record.runtime_receipt)
            self._validate_record_checkpoint_pairing(base, record)
        return record

    def _resolve_receipt(
        self,
        base: Mapping[str, Any],
        receipt_ref: Mapping[str, object],
    ) -> RuntimeReceiptRecord:
        try:
            record = self._receipt_store.get(receipt_ref)
        except RuntimeReceiptStoreError as exc:
            raise RuntimeIntentClaimStoreError(
                f"authoritative runtime receipt is unavailable: {exc}"
            ) from exc
        self._validate_receipt_lineage(base, record.runtime_receipt)
        self._validate_record_checkpoint_pairing(base, record)
        return record

    @staticmethod
    def _validate_receipt_lineage(
        base: Mapping[str, Any],
        receipt: RuntimeResultReceiptV1,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        try:
            validate_runtime_result_receipt_v1(
                receipt.model_dump(mode="json"),
                observation=observation,
                intent=intent,
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime receipt lineage does not match claim context: {exc}"
            ) from exc

    def _validate_record_checkpoint_pairing(
        self,
        base: Mapping[str, Any],
        record: RuntimeReceiptRecord,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
        grounded_consume_ref: str | None = None
        if self._grounded_consume_path(identity_hash).exists():
            grounded_state = self._load_grounded_state(identity_hash, base=base)
            if grounded_state is None:
                raise RuntimeIntentClaimStoreError("orphan grounded consume marker")
            consume = self._load_grounded_consume(
                identity_hash, base=base, grounded_state=grounded_state
            )
            if consume is None:
                raise RuntimeIntentClaimStoreError("orphan grounded consume marker")
            grounded_consume_ref = consume.evidence_ref
            if grounded_consume_ref not in record.runtime_receipt.evidence.trace_refs:
                raise RuntimeIntentClaimStoreError(
                    "runtime receipt grounded consume evidence ref mismatch"
                )
        verification_marker = self._load_verification_pending_marker(
            self._verification_pending_path(identity_hash),
            base=base,
            grounded_consume=(consume if grounded_consume_ref is not None else None),
        )
        self._validate_checkpoint_receipt_pairing(
            base,
            verification_marker,
            receipt=record.runtime_receipt,
            backend_receipt=record.backend_receipt,
            verification_evidence=record.verification_evidence,
            next_observation=record.next_observation,
        )

    def _validate_checkpoint_receipt_pairing(
        self,
        base: Mapping[str, Any],
        verification_marker: Mapping[str, Any] | None,
        *,
        receipt: RuntimeResultReceiptV1,
        backend_receipt: BackendDispatchReceipt | None,
        verification_evidence: Mapping[str, object] | None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None,
    ) -> None:
        if verification_marker is None:
            return
        semantic_success = receipt.outcome == "VERIFIED" or (
            receipt.outcome == "SAFE_STOP"
            and receipt.dispatch_status == "dispatched"
        )
        if not semantic_success and receipt.outcome != "VERIFICATION_FAILED":
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing requires semantic terminal"
            )
        selection = verification_marker["selection"]
        grounding = verification_marker["grounding"]
        checkpoint_backend = verification_marker["backend_receipt"]
        expected_backend = BackendDispatchReceipt(
            receipt_ref=checkpoint_backend["receipt_ref"],
            status=checkpoint_backend["status"],
            reason_code=checkpoint_backend["reason_code"],
        )
        expected_selection_ref = f"selection:{selection['selection_sha256']}"
        expected_candidate_ref = (
            f"candidate:{grounding['capture_id']}:{grounding['candidate_id']}"
        )
        expected_gate_ref = verification_marker["gate_decision_ref"]
        evidence = receipt.evidence
        if (
            evidence.selection_ref != expected_selection_ref
            or evidence.candidate_ref != expected_candidate_ref
            or evidence.gate_decision_ref != expected_gate_ref
            or evidence.backend_receipt_ref != expected_backend.receipt_ref
            or backend_receipt != expected_backend
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing reference mismatch"
            )
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        claimed_action = next(
            (
                action
                for action in observation.available_actions
                if action.action_id == intent.action_id
            ),
            None,
        )
        if (
            claimed_action is None
            or selection.get("transition_id") != intent.action_id
            or selection.get("semantic_action") != claimed_action.semantic_action
            or selection.get("source_state_id") != observation.state.state_id
            or selection.get("target_state_id") != claimed_action.target_state_id
            or receipt.action.action_id != selection.get("transition_id")
            or receipt.action.semantic_action != selection.get("semantic_action")
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing action mismatch"
            )
        if not isinstance(verification_evidence, Mapping):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing requires verification evidence"
            )
        checkpoint_text_expectation = verification_marker.get(
            "text_field_expectation"
        )
        if checkpoint_text_expectation is not None:
            try:
                from app.agent.text_field_evidence import (
                    validate_text_field_verification_reference,
                )

                proof = validate_text_field_verification_reference(
                    verification_evidence.get("text_field_verification"),
                    selection.get("text_parameters_ref"),
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint receipt text field proof is invalid"
                ) from exc
            if _canonical_json_bytes(proof.get("expected")) != _canonical_json_bytes(
                checkpoint_text_expectation
            ):
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint receipt text field expectation mismatch"
                )
            if semantic_success:
                if proof.get("status") != "verified" or proof.get("reason_code") != "none":
                    raise RuntimeIntentClaimStoreError(
                        "verification checkpoint receipt text field result mismatch"
                    )
            elif (
                receipt.outcome == "VERIFICATION_FAILED"
                and proof.get("status") == "not_verified"
                and proof.get("reason_code") != receipt.reason_code
            ):
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint receipt text field reason mismatch"
                )
        if not semantic_success:
            return
        if (
            verification_evidence.get("selection_sha256")
            != selection.get("selection_sha256")
            or verification_evidence.get("transition_id")
            != selection.get("transition_id")
            or verification_evidence.get("source_state_id")
            != selection.get("source_state_id")
            or verification_evidence.get("target_state_id")
            != selection.get("target_state_id")
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing verification mismatch"
            )
        try:
            projected_observation = (
                next_observation
                if isinstance(next_observation, AgentObservationV1)
                else self._validate_observation(next_observation)  # type: ignore[arg-type]
            )
        except RuntimeIntentClaimStoreError as exc:
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing next observation is invalid"
            ) from exc
        if (
            projected_observation.session_id != observation.session_id
            or projected_observation.workflow != observation.workflow
            or projected_observation.application != observation.application
            or projected_observation.state.state_id != selection.get("target_state_id")
            or receipt.next_observation_id != projected_observation.observation_id
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint receipt pairing next observation mismatch"
            )

    def _commit_terminal(
        self,
        base: Mapping[str, Any],
        receipt: RuntimeReceiptRecord,
    ) -> None:
        identity_hash = self._identity_hash(
            base["observation"].session_id,
            base["observation"].observation_id,
        )
        confirmation_evidence_ref = self._validate_confirmation_terminalization(
            base, identity_hash
        )
        self._validate_confirmation_receipt_evidence(
            receipt.runtime_receipt,
            confirmation_evidence_ref=confirmation_evidence_ref,
        )
        dispatch_marker = self._load_optional_marker(
            self._dispatch_path(identity_hash),
            expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
            expected_phase="dispatch_started",
            base=base,
        )
        verification_marker = self._load_verification_pending_marker(
            self._verification_pending_path(identity_hash),
            base=base,
        )
        self._validate_attempt_phase(
            receipt.runtime_receipt,
            dispatch_started=dispatch_marker is not None,
            verification_pending=verification_marker is not None,
        )
        self._validate_checkpoint_receipt_pairing(
            base,
            verification_marker,
            receipt=receipt.runtime_receipt,
            backend_receipt=receipt.backend_receipt,
            verification_evidence=receipt.verification_evidence,
            next_observation=receipt.next_observation,
        )
        self._publish_terminal_marker(base, receipt)

    def _publish_terminal_marker(
        self,
        base: Mapping[str, Any],
        receipt: RuntimeReceiptRecord,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
        marker = {
            "store_contract_version": TERMINAL_MARKER_CONTRACT_VERSION,
            "claim_id": base["claim_id"],
            "claim_content_sha256": base["claim_content_sha256"],
            "phase": "terminal",
            "receipt_ref": {
                "receipt_id": receipt.runtime_receipt.receipt_id,
                "content_sha256": receipt.content_sha256,
            },
            "artifact_is_authorization": False,
        }
        try:
            self._publish_bytes(
                self._terminal_path(identity_hash),
                _canonical_json_bytes(marker),
            )
        except _PublishedBytesConflict as exc:
            raise RuntimeIntentClaimStoreError("terminal phase conflict") from exc

    def _publish_grounded_terminal_marker(
        self,
        base: Mapping[str, Any],
        receipt: RuntimeReceiptRecord,
        *,
        consume: RuntimeGroundedConsumeSnapshot,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id, observation.observation_id
        )
        marker = {
            "store_contract_version": GROUNDED_TERMINAL_MARKER_CONTRACT_VERSION,
            "claim_id": base["claim_id"],
            "claim_content_sha256": base["claim_content_sha256"],
            "phase": "terminal",
            "grounded_consume_ref": consume.evidence_ref,
            "receipt_ref": {
                "receipt_id": receipt.runtime_receipt.receipt_id,
                "content_sha256": receipt.content_sha256,
            },
            "artifact_is_authorization": False,
        }
        try:
            self._publish_bytes(
                self._terminal_path(identity_hash), _canonical_json_bytes(marker)
            )
        except _PublishedBytesConflict as exc:
            raise RuntimeIntentClaimStoreError("grounded terminal phase conflict") from exc

    def _load_grounded_terminal_marker(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        consume: RuntimeGroundedConsumeSnapshot,
    ) -> dict[str, Any] | None:
        path = self._terminal_path(identity_hash)
        if not path.exists():
            return None
        _raw, marker = self._read_canonical_json(path, label="grounded terminal marker")
        if (
            set(marker) != {
                "store_contract_version", "claim_id", "claim_content_sha256",
                "phase", "grounded_consume_ref", "receipt_ref",
                "artifact_is_authorization",
            }
            or marker.get("store_contract_version")
            != GROUNDED_TERMINAL_MARKER_CONTRACT_VERSION
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("phase") != "terminal"
            or marker.get("grounded_consume_ref") != consume.evidence_ref
            or marker.get("artifact_is_authorization") is not False
            or not isinstance(marker.get("receipt_ref"), Mapping)
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered grounded terminal marker")
        return marker

    def _validate_terminal_phase(
        self,
        base: Mapping[str, Any],
        receipt: RuntimeResultReceiptV1,
        *,
        backend_receipt: BackendDispatchReceipt | None,
        verification_evidence: Mapping[str, object] | None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
        confirmation_evidence_ref = self._validate_confirmation_terminalization(
            base, identity_hash
        )
        self._validate_confirmation_receipt_evidence(
            receipt,
            confirmation_evidence_ref=confirmation_evidence_ref,
        )
        dispatch_marker = self._load_optional_marker(
            self._dispatch_path(identity_hash),
            expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
            expected_phase="dispatch_started",
            base=base,
        )
        verification_marker = self._load_verification_pending_marker(
            self._verification_pending_path(identity_hash),
            base=base,
        )
        if verification_marker is not None and dispatch_marker is None:
            raise RuntimeIntentClaimStoreError(
                "verification_pending requires dispatch_started"
            )
        self._validate_attempt_phase(
            receipt,
            dispatch_started=dispatch_marker is not None,
            verification_pending=verification_marker is not None,
        )
        self._validate_checkpoint_receipt_pairing(
            base,
            verification_marker,
            receipt=receipt,
            backend_receipt=backend_receipt,
            verification_evidence=verification_evidence,
            next_observation=next_observation,
        )

    def _validate_confirmation_terminalization(
        self,
        base: Mapping[str, Any],
        identity_hash: str,
    ) -> str | None:
        return self._confirmation_resume_evidence_ref(
            base,
            identity_hash,
            pending_error="confirmation_pending cannot terminalize before confirmation resume",
        )

    @staticmethod
    def _validate_confirmation_receipt_evidence(
        receipt: RuntimeResultReceiptV1,
        *,
        confirmation_evidence_ref: str | None,
    ) -> None:
        if (
            confirmation_evidence_ref is not None
            and confirmation_evidence_ref not in receipt.evidence.trace_refs
        ):
            raise RuntimeIntentClaimStoreError(
                "terminal receipt confirmation evidence ref mismatch"
            )

    @staticmethod
    def _validate_attempt_phase(
        receipt: RuntimeResultReceiptV1,
        *,
        dispatch_started: bool,
        verification_pending: bool,
    ) -> None:
        if receipt.attempt_count == 1 and not dispatch_started:
            raise RuntimeIntentClaimStoreError(
                "attempt_count 1 terminal receipt requires dispatch_started"
            )
        if receipt.attempt_count == 0 and dispatch_started:
            raise RuntimeIntentClaimStoreError(
                "attempt_count 0 receipt must terminalize from claimed"
            )
        semantic_w5 = receipt.outcome in {"VERIFIED", "VERIFICATION_FAILED"} or (
            receipt.outcome == "SAFE_STOP" and receipt.dispatch_status == "dispatched"
        )
        if semantic_w5 and not verification_pending:
            raise RuntimeIntentClaimStoreError(
                "semantic terminal receipt requires verification_pending"
            )
        if verification_pending and not semantic_w5:
            raise RuntimeIntentClaimStoreError(
                "verification_pending only accepts a semantic terminal receipt"
            )

    @staticmethod
    def _dispatch_marker(base: Mapping[str, Any]) -> dict[str, object]:
        return {
            "store_contract_version": DISPATCH_MARKER_CONTRACT_VERSION,
            "claim_id": base["claim_id"],
            "claim_content_sha256": base["claim_content_sha256"],
            "phase": "dispatch_started",
            "artifact_is_authorization": False,
        }

    def _load_grounded_dispatch_marker(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        consume: RuntimeGroundedConsumeSnapshot,
    ) -> dict[str, Any] | None:
        path = self._dispatch_path(identity_hash)
        if not path.exists():
            return None
        _raw, marker = self._read_canonical_json(path, label="grounded dispatch marker")
        if (
            set(marker) != {
                "store_contract_version", "claim_id", "claim_content_sha256",
                "phase", "grounded_consume_ref", "artifact_is_authorization",
            }
            or marker.get("store_contract_version")
            != GROUNDED_DISPATCH_MARKER_CONTRACT_VERSION
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("phase") != "dispatch_started"
            or marker.get("grounded_consume_ref") != consume.evidence_ref
            or marker.get("artifact_is_authorization") is not False
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered grounded dispatch marker")
        return marker

    def _verification_pending_marker(
        self,
        base: Mapping[str, Any],
        *,
        current_observation: Mapping[str, object],
        selection: Mapping[str, object],
        grounding: Mapping[str, object],
        gate: Mapping[str, object],
        gate_decision_ref: str,
        backend_receipt: BackendDispatchReceipt,
        target_process_id: int,
        grounded_consume_ref: str | None = None,
        scroll_capture: Mapping[str, object] | None = None,
        text_field_expectation: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        mappings = {
            "current_observation": self._checkpoint_mapping(
                current_observation, label="current observation"
            ),
            "selection": self._checkpoint_mapping(selection, label="selection"),
            "grounding": self._checkpoint_mapping(grounding, label="grounding"),
            "gate": self._checkpoint_mapping(gate, label="gate"),
        }
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
        if grounded_consume_ref is None:
            confirmation_evidence_ref = self._confirmation_resume_evidence_ref(
                base,
                identity_hash,
                pending_error="verification checkpoint confirmation resume is unavailable",
            )
            if (
                confirmation_evidence_ref is not None
                and mappings["selection"].get("human_confirmation_evidence_ref")
                != confirmation_evidence_ref
            ):
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint confirmation evidence ref mismatch"
                )
        self._validate_definitive_backend_receipt(backend_receipt)
        self._validate_target_process_id(target_process_id)
        if (
            not isinstance(gate_decision_ref, str)
            or _OPAQUE_REF_PATTERN.fullmatch(gate_decision_ref) is None
        ):
            raise RuntimeIntentClaimStoreError("gate decision ref is invalid")
        self._validate_checkpoint_lineage(
            base,
            current_observation=mappings["current_observation"],
            selection=mappings["selection"],
            grounding=mappings["grounding"],
            gate=mappings["gate"],
            gate_decision_ref=gate_decision_ref,
            target_process_id=target_process_id,
            native_consume_bound=grounded_consume_ref is not None,
        )
        validated_text_expectation = self._validate_text_field_checkpoint_reference(
            text_field_expectation,
            base=base,
            current_observation=mappings["current_observation"],
            selection=mappings["selection"],
            grounding=mappings["grounding"],
            gate=mappings["gate"],
            target_process_id=target_process_id,
        )
        marker: dict[str, object] = {
            "store_contract_version": (
                GROUNDED_VERIFICATION_PENDING_CONTRACT_VERSION
                if grounded_consume_ref is not None
                else VERIFICATION_PENDING_CONTRACT_VERSION
            ),
            "claim_id": base["claim_id"],
            "claim_content_sha256": base["claim_content_sha256"],
            "phase": "verification_pending",
            **mappings,
            "gate_decision_ref": gate_decision_ref,
            "backend_receipt": asdict(backend_receipt),
            "target_process_id": target_process_id,
            "artifact_is_authorization": False,
            "grants_action_authority": False,
        }
        if grounded_consume_ref is not None:
            marker["grounded_consume_ref"] = grounded_consume_ref
        if scroll_capture is not None:
            marker["scroll_capture"] = self._checkpoint_mapping(scroll_capture, label="scroll capture")
        if validated_text_expectation is not None:
            marker["text_field_expectation"] = validated_text_expectation
        self._validate_scroll_checkpoint_capture(marker)
        marker["checkpoint_sha256"] = _payload_sha256(marker)
        return marker

    def _load_verification_pending_marker(
        self,
        path: Path,
        *,
        base: Mapping[str, Any],
        grounded_consume_ref: str | None = None,
        grounded_consume: RuntimeGroundedConsumeSnapshot | None = None,
    ) -> dict[str, Any] | None:
        if grounded_consume is not None:
            if grounded_consume_ref not in {None, grounded_consume.evidence_ref}:
                raise RuntimeIntentClaimStoreError(
                    "grounded verification consume reference mismatch"
                )
            grounded_consume_ref = grounded_consume.evidence_ref
        if not path.exists():
            return None
        _, marker = self._read_canonical_json(
            path,
            label="verification_pending marker",
        )
        expected_keys = {
            "store_contract_version",
            "claim_id",
            "claim_content_sha256",
            "phase",
            "current_observation",
            "selection",
            "grounding",
            "gate",
            "gate_decision_ref",
            "backend_receipt",
            "target_process_id",
            "artifact_is_authorization",
            "grants_action_authority",
            "checkpoint_sha256",
        }
        if grounded_consume_ref is not None:
            expected_keys.add("grounded_consume_ref")
        if isinstance(marker.get("selection"), Mapping) and marker["selection"].get("semantic_action") == "scroll_region":
            expected_keys.add("scroll_capture")
        if isinstance(marker.get("selection"), Mapping) and marker["selection"].get("semantic_action") == "fill_field":
            expected_keys.add("text_field_expectation")
        digest_payload = dict(marker)
        checkpoint_sha256 = digest_payload.pop("checkpoint_sha256", None)
        if (
            set(marker) != expected_keys
            or marker.get("store_contract_version")
            != (
                GROUNDED_VERIFICATION_PENDING_CONTRACT_VERSION
                if grounded_consume_ref is not None
                else VERIFICATION_PENDING_CONTRACT_VERSION
            )
            or marker.get("phase") != "verification_pending"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or checkpoint_sha256 != _payload_sha256(digest_payload)
            or (
                grounded_consume_ref is not None
                and marker.get("grounded_consume_ref") != grounded_consume_ref
            )
        ):
            raise RuntimeIntentClaimStoreError(
                "invalid or tampered verification_pending marker"
            )
        backend_payload = marker.get("backend_receipt")
        self._validate_scroll_checkpoint_capture(marker)
        if not isinstance(backend_payload, Mapping) or set(backend_payload) != {
            "receipt_ref",
            "status",
            "reason_code",
        }:
            raise RuntimeIntentClaimStoreError(
                "invalid or tampered verification_pending backend receipt"
            )
        backend_receipt = BackendDispatchReceipt(
            receipt_ref=backend_payload.get("receipt_ref"),  # type: ignore[arg-type]
            status=backend_payload.get("status"),  # type: ignore[arg-type]
            reason_code=backend_payload.get("reason_code"),  # type: ignore[arg-type]
        )
        self._validate_definitive_backend_receipt(backend_receipt)
        target_process_id = marker.get("target_process_id")
        self._validate_target_process_id(target_process_id)
        mappings = {}
        for field_name in ("current_observation", "selection", "grounding", "gate"):
            mappings[field_name] = self._checkpoint_mapping(
                marker.get(field_name),  # type: ignore[arg-type]
                label=field_name.replace("_", " "),
            )
        gate_decision_ref = marker.get("gate_decision_ref")
        if (
            not isinstance(gate_decision_ref, str)
            or _OPAQUE_REF_PATTERN.fullmatch(gate_decision_ref) is None
        ):
            raise RuntimeIntentClaimStoreError(
                "invalid or tampered verification_pending gate ref"
            )
        self._validate_checkpoint_lineage(
            base,
            current_observation=mappings["current_observation"],
            selection=mappings["selection"],
            grounding=mappings["grounding"],
            gate=mappings["gate"],
            gate_decision_ref=gate_decision_ref,
            target_process_id=target_process_id,
            native_consume_bound=grounded_consume_ref is not None,
        )
        text_expectation = self._validate_text_field_checkpoint_reference(
            marker.get("text_field_expectation"),
            base=base,
            current_observation=mappings["current_observation"],
            selection=mappings["selection"],
            grounding=mappings["grounding"],
            gate=mappings["gate"],
            target_process_id=target_process_id,
        )
        if text_expectation is not None:
            marker["text_field_expectation"] = text_expectation
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
        if grounded_consume_ref is None:
            confirmation_evidence_ref = self._confirmation_resume_evidence_ref(
                base,
                identity_hash,
                pending_error="verification checkpoint confirmation resume is unavailable",
            )
            if (
                confirmation_evidence_ref is not None
                and mappings["selection"].get("human_confirmation_evidence_ref")
                != confirmation_evidence_ref
            ):
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint confirmation evidence ref mismatch"
                )
        elif grounded_consume is not None:
            self._validate_grounded_checkpoint_bundle(
                marker,
                consume=grounded_consume,
            )
        return marker

    @staticmethod
    def _validate_text_field_checkpoint_reference(
        value: Mapping[str, object] | None,
        *,
        base: Mapping[str, Any],
        current_observation: Mapping[str, Any],
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate: Mapping[str, Any],
        target_process_id: int,
    ) -> dict[str, Any] | None:
        semantic = selection.get("semantic_action")
        if semantic != "fill_field":
            if value is not None:
                raise RuntimeIntentClaimStoreError(
                    "non-fill verification checkpoint cannot carry text field expectation"
                )
            return None
        try:
            parameters = reviewed_action_parameter_fields(selection)
            if (
                any(
                    reviewed_action_parameter_fields(
                        candidate, semantic_action=semantic
                    )
                    != parameters
                    for candidate in (grounding, gate)
                )
                or "text_parameters_ref" not in parameters
            ):
                raise ValueError("text action parameters mismatch")
            reference = validate_text_field_expectation_reference(
                value, parameters["text_parameters_ref"]
            )
            before = reference["before"]
            identity = before["identity"]
            viewport = grounding["viewport_size"]
            bbox = grounding["bbox"]
            point = grounding["click_point"]
            control_bbox = tuple(identity["control_bbox"])
            declared_bbox = tuple(bbox[key] for key in ("x", "y", "w", "h"))
            grounding_viewport = (viewport["width"], viewport["height"])
            grounding_point = (point["x"], point["y"])
            validate_text_dispatch_geometry(
                declared_bbox, grounding_viewport, grounding_point
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint text field expectation is invalid"
            ) from exc
        if (
            before.get("capture_id") != current_observation.get("capture_id")
            or identity.get("target_field_id")
            != parameters["text_parameters_ref"].get("target_field_id")
            or identity.get("window_handle")
            != base["server_binding"].target_window_handle
            or identity.get("process_id") != target_process_id
            or identity.get("window_rect", [None, None, None, None])[2:]
            != list(grounding_viewport)
            or not (
                control_bbox[0] <= declared_bbox[0]
                and control_bbox[1] <= declared_bbox[1]
                and declared_bbox[0] + declared_bbox[2]
                <= control_bbox[0] + control_bbox[2]
                and declared_bbox[1] + declared_bbox[3]
                <= control_bbox[1] + control_bbox[3]
            )
            or gate.get("selected_click_point") != point
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint text field expectation lineage mismatch"
            )
        return reference

    @staticmethod
    def _validate_grounded_checkpoint_bundle(
        marker: Mapping[str, Any],
        *,
        consume: RuntimeGroundedConsumeSnapshot,
    ) -> None:
        expected = {
            "current_observation": consume.current_observation,
            "selection": consume.selection,
            "grounding": consume.grounding,
            "gate": consume.gate,
        }
        if (
            any(
                _canonical_json_bytes(marker.get(key))
                != _canonical_json_bytes(value)
                for key, value in expected.items()
            )
            or marker.get("gate_decision_ref") != consume.gate_decision_ref
            or marker.get("target_process_id") != consume.target_process_id
            or marker.get("grounded_consume_ref") != consume.evidence_ref
            or (
                consume.selection.get("semantic_action") == "fill_field"
                and _canonical_json_bytes(marker.get("text_field_expectation"))
                != _canonical_json_bytes(
                    consume.fresh_preview.to_dict().get("text_field_expectation_ref")
                )
            )
        ):
            raise RuntimeIntentClaimStoreError(
                "grounded verification checkpoint bundle differs from consume"
            )

    @staticmethod
    def _checkpoint_mapping(
        value: Mapping[str, object],
        *,
        label: str,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise RuntimeIntentClaimStoreError(f"{label} checkpoint input must be a mapping")
        try:
            cloned = json.loads(_canonical_json_bytes(value).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeIntentClaimStoreError(
                f"{label} checkpoint input is invalid"
            ) from exc
        if not isinstance(cloned, dict):
            raise RuntimeIntentClaimStoreError(f"{label} checkpoint input must be a mapping")
        RuntimeIntentClaimStore._reject_action_authority(cloned, path=label)
        return cloned

    @staticmethod
    def _reject_action_authority(value: object, *, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).lower()
                if normalized in {
                    "artifact_is_authorization",
                    "grants_action_authority",
                    "execute_binding_enabled",
                }:
                    if nested is not False:
                        raise RuntimeIntentClaimStoreError(
                            f"{path} cannot grant action authority or authorization"
                        )
                elif (
                    "authority" in normalized
                    or "authorization" in normalized
                    or normalized in {
                        "token",
                        "approved_plan",
                        "approved_to_click",
                        "approved_to_dispatch",
                    }
                ):
                    raise RuntimeIntentClaimStoreError(
                        f"{path} cannot carry authority or authorization tokens"
                    )
                RuntimeIntentClaimStore._reject_action_authority(
                    nested,
                    path=f"{path}.{key}",
                )
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                RuntimeIntentClaimStore._reject_action_authority(
                    nested,
                    path=f"{path}[{index}]",
                )

    @staticmethod
    def _validate_definitive_backend_receipt(value: object) -> None:
        if (
            not isinstance(value, BackendDispatchReceipt)
            or not isinstance(value.receipt_ref, str)
            or _OPAQUE_REF_PATTERN.fullmatch(value.receipt_ref) is None
            or value.status != "dispatched"
            or value.reason_code != "none"
        ):
            raise RuntimeIntentClaimStoreError(
                "verification_pending requires a definitive dispatched backend receipt"
            )

    @staticmethod
    def _validate_target_process_id(value: object) -> None:
        if type(value) is not int or value <= 0:
            raise RuntimeIntentClaimStoreError(
                "verification_pending target_process_id must be a positive integer"
            )

    @staticmethod
    def _validate_checkpoint_lineage(
        base: Mapping[str, Any],
        *,
        current_observation: Mapping[str, Any],
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        gate: Mapping[str, Any],
        gate_decision_ref: str,
        target_process_id: int,
        native_consume_bound: bool,
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        workflow = observation.workflow
        if observation.application.kind == "native":
            # 原生检查点必须关联已校验的 consume；旧路径没有前置实例事实，继续拒绝。
            if (
                not native_consume_bound
                or current_observation.get("origin") != ""
                or validate_native_identity_fact(
                    current_observation.get("native_identity"),
                    target_window_handle=base["server_binding"].target_window_handle,
                    expected_process_id=target_process_id,
                ) is None
            ):
                raise RuntimeIntentClaimStoreError("verification checkpoint native identity is invalid or unsupported")
        if (
            not current_observation_contract_matches(current_observation, observation.application.kind)
            or current_observation.get("asset_id") != workflow.asset_id
            or current_observation.get("expected_asset_content_sha256")
            != workflow.asset_content_sha256
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint current observation lineage mismatch"
            )
        if (
            current_observation.get("capture_id")
            == observation.current_capture.capture_id
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint C1 capture must be newer than claim C0"
            )
        capture_lineage = {
            key: current_observation.get(key)
            for key in ("capture_id", "screenshot_sha256", "viewport_size")
        }
        selection_capture = selection.get("capture_lineage")
        expected_selection = {
            "asset_id": workflow.asset_id,
            "asset_content_sha256": workflow.asset_content_sha256,
            "source_workflow_sha256": workflow.source_workflow_sha256,
            "reviewed_revision_hash": workflow.reviewed_revision_hash,
        }
        claimed_action = next(
            (
                action
                for action in observation.available_actions
                if action.action_id == intent.action_id
            ),
            None,
        )
        selection_sha256 = selection.get("selection_sha256")
        if (
            any(selection.get(key) != expected for key, expected in expected_selection.items())
            or not isinstance(selection_capture, Mapping)
            or dict(selection_capture) != capture_lineage
            or claimed_action is None
            or selection.get("transition_id") != intent.action_id
            or selection.get("semantic_action") != claimed_action.semantic_action
            or not isinstance(selection_sha256, str)
            or _SHA256_PATTERN.fullmatch(selection_sha256) is None
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint selection lineage mismatch"
            )
        for field_name, expected in (
            ("asset_content_sha256", workflow.asset_content_sha256),
            ("transition_id", selection.get("transition_id")),
            ("source_state_id", selection.get("source_state_id")),
            ("capture_id", capture_lineage["capture_id"]),
            ("screenshot_sha256", capture_lineage["screenshot_sha256"]),
            ("viewport_size", capture_lineage["viewport_size"]),
        ):
            if grounding.get(field_name) != expected:
                raise RuntimeIntentClaimStoreError(
                    "verification checkpoint grounding lineage mismatch"
                )
        expected_gate = {
            "allowed": True,
            "asset_content_sha256": workflow.asset_content_sha256,
            "transition_id": selection.get("transition_id"),
            "selection_sha256": selection.get("selection_sha256"),
            "selected_candidate_id": grounding.get("candidate_id"),
            "selected_click_point": grounding.get("click_point"),
            "capture_id": capture_lineage["capture_id"],
            "screenshot_sha256": capture_lineage["screenshot_sha256"],
            "viewport_size": capture_lineage["viewport_size"],
        }
        refs = gate.get("evidence_refs")
        if (
            any(gate.get(key) != expected for key, expected in expected_gate.items())
            or not isinstance(refs, list)
            or gate_decision_ref not in refs
        ):
            raise RuntimeIntentClaimStoreError(
                "verification checkpoint Gate lineage mismatch"
            )

    @staticmethod
    def _checkpoint_snapshot(
        marker: Mapping[str, Any],
    ) -> RuntimeVerificationPendingCheckpoint:
        backend = marker["backend_receipt"]
        return RuntimeVerificationPendingCheckpoint(
            claim_id=marker["claim_id"],
            claim_content_sha256=marker["claim_content_sha256"],
            checkpoint_sha256=marker["checkpoint_sha256"],
            gate_decision_ref=marker["gate_decision_ref"],
            target_process_id=marker["target_process_id"],
            backend_receipt=BackendDispatchReceipt(
                receipt_ref=backend["receipt_ref"],
                status=backend["status"],
                reason_code=backend["reason_code"],
            ),
            _current_observation_json=_canonical_json_bytes(marker["current_observation"]),
            _selection_json=_canonical_json_bytes(marker["selection"]),
            _grounding_json=_canonical_json_bytes(marker["grounding"]),
            _gate_json=_canonical_json_bytes(marker["gate"]),
            _scroll_capture_json=_canonical_json_bytes(marker["scroll_capture"]) if "scroll_capture" in marker else None,
            _text_field_expectation_json=(
                _canonical_json_bytes(marker["text_field_expectation"])
                if "text_field_expectation" in marker
                else None
            ),
        )

    @staticmethod
    def _validate_scroll_checkpoint_capture(marker: Mapping[str, Any]) -> None:
        if not isinstance(marker.get("selection"), Mapping):
            raise RuntimeIntentClaimStoreError("checkpoint selection is invalid")
        if marker["selection"].get("semantic_action") != "scroll_region":
            if "scroll_capture" in marker:
                raise RuntimeIntentClaimStoreError("non-scroll checkpoint cannot carry scroll capture")
            return
        capture = marker.get("scroll_capture")
        current = marker.get("current_observation")
        if (
            not isinstance(capture, Mapping) or not isinstance(current, Mapping)
            or capture.get("contract_version") != "scroll_capture_snapshot_v1"
            or capture.get("captured") is not True
            or capture.get("capture_id") != current.get("capture_id")
            or capture.get("image_sha256") != current.get("screenshot_sha256")
            or capture.get("viewport_size") != current.get("viewport_size")
            or validate_native_identity_fact(capture.get("native_identity"),
                target_window_handle=capture.get("window_handle"), expected_process_id=marker["target_process_id"]) is None
            or ("native_identity" in current and capture.get("native_identity") != current["native_identity"])
        ):
            raise RuntimeIntentClaimStoreError("scroll checkpoint capture lineage mismatch")

    def _load_optional_marker(
        self,
        path: Path,
        *,
        expected_contract: str,
        expected_phase: str,
        base: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if not path.exists():
            return None
        _, marker = self._read_canonical_json(path, label=f"{expected_phase} marker")
        common = {
            "store_contract_version",
            "claim_id",
            "claim_content_sha256",
            "phase",
            "artifact_is_authorization",
        }
        allowed = common | ({"receipt_ref"} if expected_phase == "terminal" else set())
        if (
            set(marker) != allowed
            or marker.get("store_contract_version") != expected_contract
            or marker.get("phase") != expected_phase
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("artifact_is_authorization") is not False
        ):
            raise RuntimeIntentClaimStoreError(
                f"invalid or tampered {expected_phase} marker"
            )
        return marker

    def _has_any_grounded_marker(self, identity_hash: str) -> bool:
        return any(
            path.exists()
            for path in (
                self._grounded_request_path(identity_hash),
                self._grounded_decision_path(identity_hash),
                self._grounded_closed_path(identity_hash),
                self._grounded_consume_path(identity_hash),
            )
        )

    def _has_any_legacy_phase_marker(self, identity_hash: str) -> bool:
        return any(
            path.exists()
            for path in (
                self._confirmation_request_path(identity_hash),
                self._confirmation_decision_path(identity_hash),
                self._confirmation_resume_path(identity_hash),
                self._confirmation_closed_path(identity_hash),
                self._dispatch_path(identity_hash),
                self._verification_pending_path(identity_hash),
                self._terminal_path(identity_hash),
            )
        )

    def _fresh_has_legacy_phase_marker(self, identity_hash: str) -> bool:
        for path, fresh_contract in (
            (self._dispatch_path(identity_hash), "runtime_fresh_learning_dispatch_started_v1"),
            (self._terminal_path(identity_hash), "runtime_fresh_learning_terminal_v1"),
        ):
            if path.exists():
                _raw, marker = self._read_canonical_json(path, label="fresh phase marker")
                if marker.get("store_contract_version") != fresh_contract:
                    return True
        return any(path.exists() for path in (
            self._confirmation_request_path(identity_hash), self._confirmation_decision_path(identity_hash),
            self._confirmation_resume_path(identity_hash), self._confirmation_closed_path(identity_hash),
            self._verification_pending_path(identity_hash),
        ))

    def _reject_mixed_grounded_phases(
        self,
        identity_hash: str,
        *,
        grounded_present: bool,
    ) -> None:
        if grounded_present and self._has_any_legacy_phase_marker(identity_hash):
            raise RuntimeIntentClaimStoreError(
                "mixed grounded and legacy runtime intent phases are invalid"
            )

    def _reject_grounded_receipt_conflict(self, base: Mapping[str, Any]) -> None:
        if self._find_receipt(base) is not None:
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation has an authoritative receipt conflict"
            )

    def _load_grounded_by_identity(
        self,
        identity_hash: str,
    ) -> tuple[dict[str, Any], tuple[Any, ...]]:
        path = self._grounded_request_path(identity_hash)
        if not path.exists():
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation request is unavailable"
            )
        _, marker = self._read_canonical_json(
            path,
            label="grounded confirmation request",
        )
        session_id = marker.get("session_id")
        observation_id = marker.get("observation_id")
        if (
            not isinstance(session_id, str)
            or not isinstance(observation_id, str)
            or self._identity_hash(session_id, observation_id) != identity_hash
        ):
            raise RuntimeIntentClaimStoreError(
                "invalid or tampered grounded confirmation request"
            )
        base = self._load_claim(session_id, observation_id)
        state = self._load_grounded_state(identity_hash, base=base)
        if state is None:
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation request is unavailable"
            )
        return base, state

    def _load_grounded_state(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
    ) -> tuple[
        bytes,
        dict[str, Any],
        GroundedActionPreview,
        datetime,
        datetime,
        bytes | None,
        dict[str, Any] | None,
        dict[str, Any] | None,
    ] | None:
        request_path = self._grounded_request_path(identity_hash)
        decision_path = self._grounded_decision_path(identity_hash)
        closed_path = self._grounded_closed_path(identity_hash)
        if not request_path.exists():
            if decision_path.exists() or closed_path.exists():
                raise RuntimeIntentClaimStoreError(
                    "orphan grounded confirmation marker is invalid"
                )
            return None
        try:
            request_raw, request_value = self._read_canonical_json(
                request_path,
                label="grounded confirmation request",
            )
            request, preview, requested, expires = validate_request_record(
                request_value,
                base=base,
                identity_hash=identity_hash,
            )
            decision_raw: bytes | None = None
            decision: dict[str, Any] | None = None
            if decision_path.exists():
                decision_raw, decision_value = self._read_canonical_json(
                    decision_path,
                    label="grounded confirmation decision",
                )
                decision, _decided = validate_decision_record(
                    decision_value,
                    base=base,
                    request=request,
                    request_raw=request_raw,
                )
            closed: dict[str, Any] | None = None
            if closed_path.exists():
                _closed_raw, closed_value = self._read_canonical_json(
                    closed_path,
                    label="grounded confirmation close",
                )
                closed, _closed_at = validate_closed_record(
                    closed_value,
                    base=base,
                    request=request,
                    request_raw=request_raw,
                    decision_raw=decision_raw,
                )
        except RuntimeGroundedConfirmationError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        return (
            request_raw,
            request,
            preview,
            requested,
            expires,
            decision_raw,
            decision,
            closed,
        )

    def _load_grounded_consume(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        grounded_state: tuple[Any, ...],
    ) -> RuntimeGroundedConsumeSnapshot | None:
        path = self._grounded_consume_path(identity_hash)
        if not path.exists():
            return None
        request_raw, request, preview, _requested, _expires, decision_raw, decision, closed = grounded_state
        if closed is not None:
            raise RuntimeIntentClaimStoreError("closed grounded confirmation has consume marker")
        try:
            _raw, value = self._read_canonical_json(path, label="grounded consume")
            _marker, snapshot = validate_consume_record(
                value,
                base=base,
                request=request,
                request_raw=request_raw,
                decision=decision,
                decision_raw=decision_raw,
                approved_preview=preview,
            )
        except RuntimeGroundedConsumeError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        return snapshot

    def _publish_grounded_closed(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes,
        request: Mapping[str, Any],
        decision_raw: bytes | None,
        reason_code: str,
    ) -> None:
        try:
            marker = build_closed_record(
                base=base,
                confirmation_id=request["confirmation_id"],
                request_content_sha256=hashlib.sha256(request_raw).hexdigest(),
                decision_content_sha256=(
                    hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
                ),
                reason_code=reason_code,
                closed_at=self._utc_now(),
            )
            validate_closed_record(
                marker,
                base=base,
                request=request,
                request_raw=request_raw,
                decision_raw=decision_raw,
            )
            self._publish_bytes(
                self._grounded_closed_path(identity_hash),
                _grounded_canonical_json_bytes(marker),
            )
        except RuntimeGroundedConfirmationError as exc:
            raise RuntimeIntentClaimStoreError(str(exc)) from exc
        except _PublishedBytesConflict as exc:
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation close conflict"
            ) from exc

    def _load_confirmation_request_by_identity(
        self,
        identity_hash: str,
    ) -> tuple[bytes, dict[str, Any]]:
        path = self._confirmation_request_path(identity_hash)
        if not path.exists():
            raise RuntimeIntentClaimStoreError("confirmation request is unavailable")
        raw, marker = self._read_canonical_json(path, label="confirmation request")
        session_id = marker.get("session_id")
        observation_id = marker.get("observation_id")
        if not isinstance(session_id, str) or not isinstance(observation_id, str):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation request")
        base = self._load_claim(session_id, observation_id)
        loaded_raw, loaded = self._load_optional_confirmation_request(
            identity_hash, base=base
        )
        if loaded is None or loaded_raw is None:
            raise RuntimeIntentClaimStoreError("confirmation request is unavailable")
        return loaded_raw, loaded

    def _load_optional_confirmation_request(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
    ) -> tuple[bytes | None, dict[str, Any] | None]:
        path = self._confirmation_request_path(identity_hash)
        if not path.exists():
            return None, None
        raw, marker = self._read_canonical_json(path, label="confirmation request")
        expected = {
            "store_contract_version", "claim_id", "claim_content_sha256", "phase",
            "confirmation_id", "session_id", "observation_id", "intent_id", "workflow",
            "transition_id", "semantic_action", "request_capture_id",
            "request_screenshot_sha256", "request_state_resolution_sha256",
            "target_window_handle", "target_process_id", "requested_at", "expires_at",
            "artifact_is_authorization", "grants_action_authority", "request_binding_sha256",
        }
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        binding: RuntimeIntentServerBinding = base["server_binding"]
        action = next(
            (item for item in observation.available_actions if item.action_id == intent.action_id),
            None,
        )
        if (
            set(marker) != expected
            or marker.get("store_contract_version") != CONFIRMATION_REQUEST_CONTRACT_VERSION
            or marker.get("phase") != "confirmation_pending"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("confirmation_id") != f"confirmation.{identity_hash}"
            or marker.get("session_id") != observation.session_id
            or marker.get("observation_id") != observation.observation_id
            or marker.get("intent_id") != intent.intent_id
            or marker.get("workflow") != observation.workflow.model_dump(mode="json")
            or marker.get("transition_id") != intent.action_id
            or action is None
            or marker.get("semantic_action") != action.semantic_action
            or action.requires_user_confirmation is not True
            or marker.get("target_window_handle") != binding.target_window_handle
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or marker.get("request_binding_sha256")
            != _payload_sha256(
                {key: value for key, value in marker.items() if key != "request_binding_sha256"}
            )
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation request")
        for key in ("request_screenshot_sha256", "request_state_resolution_sha256"):
            value = marker.get(key)
            if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
                raise RuntimeIntentClaimStoreError("invalid or tampered confirmation request")
        capture_id = marker.get("request_capture_id")
        if not isinstance(capture_id, str) or _STABLE_ID_PATTERN.fullmatch(capture_id) is None:
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation request")
        self._validate_target_process_id(marker.get("target_process_id"))
        requested = self._parse_time(marker.get("requested_at"))
        expires = self._parse_time(marker.get("expires_at"))
        if expires - requested != timedelta(seconds=CONFIRMATION_TTL_SECONDS):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation request")
        return raw, marker

    def _confirmation_resume_evidence_ref(
        self,
        base: Mapping[str, Any],
        identity_hash: str,
        *,
        pending_error: str,
    ) -> str | None:
        request_raw, request = self._load_optional_confirmation_request(
            identity_hash,
            base=base,
        )
        if request_raw is None or request is None:
            return None
        decision_raw, decision = self._load_optional_confirmation_decision(
            identity_hash,
            base=base,
            request_raw=request_raw,
            request=request,
        )
        resume = self._load_optional_confirmation_resume(
            identity_hash,
            base=base,
            request_raw=request_raw,
            request=request,
            decision_raw=decision_raw,
            decision=decision,
        )
        closed = self._load_optional_confirmation_closed(
            identity_hash,
            base=base,
            request_raw=request_raw,
            request=request,
            decision_raw=decision_raw,
        )
        if closed is not None:
            raise RuntimeIntentClaimStoreError(
                "closed confirmation cannot dispatch, verify, or terminalize"
            )
        if (
            decision_raw is None
            or decision is None
            or decision.get("decision") != "approved"
            or resume is None
        ):
            raise RuntimeIntentClaimStoreError(pending_error)
        snapshot = self._confirmation_snapshot(
            request_raw=request_raw,
            request=request,
            decision_raw=decision_raw,
            decision=decision,
            resume=resume,
            closed=None,
            workflow=base["observation"].workflow,
        )
        if not snapshot.evidence_ref:
            raise RuntimeIntentClaimStoreError(
                "confirmation evidence ref is unavailable"
            )
        return snapshot.evidence_ref

    def _load_confirmation_decision(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes,
        request: Mapping[str, Any],
    ) -> tuple[bytes, dict[str, Any]]:
        raw, marker = self._load_optional_confirmation_decision(
            identity_hash,
            base=base,
            request_raw=request_raw,
            request=request,
        )
        if raw is None or marker is None:
            raise RuntimeIntentClaimStoreError("confirmation decision is unavailable")
        return raw, marker

    def _load_optional_confirmation_decision(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes | None,
        request: Mapping[str, Any],
    ) -> tuple[bytes | None, dict[str, Any] | None]:
        path = self._confirmation_decision_path(identity_hash)
        if not path.exists():
            return None, None
        if request_raw is None:
            raise RuntimeIntentClaimStoreError("confirmation decision requires request")
        raw, marker = self._read_canonical_json(path, label="confirmation decision")
        expected = {
            "store_contract_version", "claim_id", "claim_content_sha256", "phase",
            "confirmation_id", "request_content_sha256", "decision", "decided_at",
            "artifact_is_authorization", "grants_action_authority", "decision_binding_sha256",
        }
        if (
            set(marker) != expected
            or marker.get("store_contract_version") != CONFIRMATION_DECISION_CONTRACT_VERSION
            or marker.get("phase") != "confirmation_decided"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("confirmation_id") != request.get("confirmation_id")
            or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
            or marker.get("decision") not in {"approved", "denied"}
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or marker.get("decision_binding_sha256")
            != _payload_sha256(
                {key: value for key, value in marker.items() if key != "decision_binding_sha256"}
            )
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation decision")
        self._parse_time(marker.get("decided_at"))
        return raw, marker

    def _load_optional_confirmation_resume(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes | None,
        request: Mapping[str, Any] | None,
        decision_raw: bytes | None,
        decision: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        path = self._confirmation_resume_path(identity_hash)
        if not path.exists():
            return None
        if request_raw is None or request is None or decision_raw is None or decision is None:
            raise RuntimeIntentClaimStoreError("confirmation resume requires approved decision")
        _, marker = self._read_canonical_json(path, label="confirmation resume")
        expected = {
            "store_contract_version", "claim_id", "claim_content_sha256", "phase",
            "confirmation_id", "request_content_sha256", "decision_content_sha256",
            "resume_attempt_id", "started_at", "artifact_is_authorization",
            "grants_action_authority", "resume_binding_sha256",
        }
        if (
            set(marker) != expected
            or marker.get("store_contract_version") != CONFIRMATION_RESUME_CONTRACT_VERSION
            or marker.get("phase") != "confirmation_resume_started"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("confirmation_id") != request.get("confirmation_id")
            or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
            or marker.get("decision_content_sha256") != hashlib.sha256(decision_raw).hexdigest()
            or decision.get("decision") != "approved"
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or marker.get("resume_binding_sha256")
            != _payload_sha256(
                {key: value for key, value in marker.items() if key != "resume_binding_sha256"}
            )
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation resume")
        resume_attempt_id = marker.get("resume_attempt_id")
        if not isinstance(resume_attempt_id, str) or _STABLE_ID_PATTERN.fullmatch(resume_attempt_id) is None:
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation resume")
        self._parse_time(marker.get("started_at"))
        return marker

    def _publish_confirmation_closed(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes,
        request: Mapping[str, Any],
        decision_raw: bytes | None,
        reason_code: Literal["confirmation_expired", "confirmation_stale"],
    ) -> None:
        marker = {
            "store_contract_version": CONFIRMATION_CLOSED_CONTRACT_VERSION,
            "claim_id": base["claim_id"],
            "claim_content_sha256": base["claim_content_sha256"],
            "phase": "confirmation_closed",
            "confirmation_id": request["confirmation_id"],
            "request_content_sha256": hashlib.sha256(request_raw).hexdigest(),
            "decision_content_sha256": (
                hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
            ),
            "reason_code": reason_code,
            "closed_at": self._format_time(self._utc_now()),
            "artifact_is_authorization": False,
            "grants_action_authority": False,
        }
        marker["closed_binding_sha256"] = _payload_sha256(marker)
        try:
            self._publish_bytes(
                self._confirmation_closed_path(identity_hash),
                _canonical_json_bytes(marker),
            )
        except _PublishedBytesConflict as exc:
            raise RuntimeIntentClaimStoreError("confirmation close conflict") from exc

    def _load_optional_confirmation_closed(
        self,
        identity_hash: str,
        *,
        base: Mapping[str, Any],
        request_raw: bytes | None,
        request: Mapping[str, Any] | None,
        decision_raw: bytes | None,
    ) -> dict[str, Any] | None:
        path = self._confirmation_closed_path(identity_hash)
        if not path.exists():
            return None
        if request_raw is None or request is None:
            raise RuntimeIntentClaimStoreError("confirmation close requires request")
        _, marker = self._read_canonical_json(path, label="confirmation close")
        expected = {
            "store_contract_version", "claim_id", "claim_content_sha256", "phase",
            "confirmation_id", "request_content_sha256", "decision_content_sha256",
            "reason_code", "closed_at", "artifact_is_authorization",
            "grants_action_authority", "closed_binding_sha256",
        }
        expected_decision = hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
        if (
            set(marker) != expected
            or marker.get("store_contract_version") != CONFIRMATION_CLOSED_CONTRACT_VERSION
            or marker.get("phase") != "confirmation_closed"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("confirmation_id") != request.get("confirmation_id")
            or marker.get("request_content_sha256") != hashlib.sha256(request_raw).hexdigest()
            or marker.get("decision_content_sha256") != expected_decision
            or marker.get("reason_code") not in {"confirmation_expired", "confirmation_stale"}
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or marker.get("closed_binding_sha256")
            != _payload_sha256(
                {key: value for key, value in marker.items() if key != "closed_binding_sha256"}
            )
        ):
            raise RuntimeIntentClaimStoreError("invalid or tampered confirmation close")
        self._parse_time(marker.get("closed_at"))
        return marker

    @staticmethod
    def _confirmation_snapshot(
        *,
        request_raw: bytes,
        request: Mapping[str, Any],
        decision_raw: bytes | None,
        decision: Mapping[str, Any] | None,
        resume: Mapping[str, Any] | None,
        closed: Mapping[str, Any] | None,
        workflow: Any,
    ) -> RuntimeIntentConfirmationSnapshot:
        decision_digest = hashlib.sha256(decision_raw).hexdigest() if decision_raw else None
        evidence_ref = (
            f"confirmation:{request['confirmation_id']}:{decision_digest}"
            if decision_digest and decision and decision.get("decision") == "approved"
            else ""
        )
        return RuntimeIntentConfirmationSnapshot(
            confirmation_id=request["confirmation_id"],
            request_content_sha256=hashlib.sha256(request_raw).hexdigest(),
            session_id=request["session_id"],
            observation_id=request["observation_id"],
            intent_id=request["intent_id"],
            workflow=workflow,
            transition_id=request["transition_id"],
            semantic_action=request["semantic_action"],
            request_capture_id=request["request_capture_id"],
            request_screenshot_sha256=request["request_screenshot_sha256"],
            request_state_resolution_sha256=request["request_state_resolution_sha256"],
            target_window_handle=request["target_window_handle"],
            target_process_id=request["target_process_id"],
            requested_at=request["requested_at"],
            expires_at=request["expires_at"],
            decision=decision.get("decision") if decision else None,
            decision_content_sha256=decision_digest,
            decided_at=decision.get("decided_at") if decision else None,
            resume_attempt_id=resume.get("resume_attempt_id") if resume else None,
            closed_reason_code=closed.get("reason_code") if closed else None,
            evidence_ref=evidence_ref,
        )

    def _utc_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeIntentClaimStoreError("confirmation clock must return aware datetime")
        return value.astimezone(timezone.utc).replace(microsecond=0)

    @staticmethod
    def _format_time(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _parse_time(value: object) -> datetime:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise RuntimeIntentClaimStoreError("confirmation timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
        except ValueError as exc:
            raise RuntimeIntentClaimStoreError("confirmation timestamp is invalid") from exc
        if parsed.tzinfo != timezone.utc:
            raise RuntimeIntentClaimStoreError("confirmation timestamp is invalid")
        return parsed

    @staticmethod
    def _confirmation_identity_hash(confirmation_id: str) -> str:
        if (
            not isinstance(confirmation_id, str)
            or not confirmation_id.startswith("confirmation.")
            or _SHA256_PATTERN.fullmatch(confirmation_id.removeprefix("confirmation.")) is None
        ):
            raise RuntimeIntentClaimStoreError("confirmation identity is invalid")
        return confirmation_id.removeprefix("confirmation.")

    @staticmethod
    def _grounded_confirmation_identity_hash(confirmation_id: str) -> str:
        prefix = "grounded-confirmation."
        if (
            not isinstance(confirmation_id, str)
            or not confirmation_id.startswith(prefix)
            or _SHA256_PATTERN.fullmatch(confirmation_id.removeprefix(prefix)) is None
        ):
            raise RuntimeIntentClaimStoreError(
                "grounded confirmation identity is invalid"
            )
        return confirmation_id.removeprefix(prefix)

    @staticmethod
    def _validate_observation(
        value: AgentObservationV1 | Mapping[str, object],
    ) -> AgentObservationV1:
        try:
            payload = (
                value.model_dump(mode="json")
                if isinstance(value, AgentObservationV1)
                else value
            )
            return validate_agent_observation_v1(payload)
        except (TypeError, ValueError) as exc:
            raise RuntimeIntentClaimStoreError(f"invalid Agent Observation: {exc}") from exc

    @staticmethod
    def _validate_intent(
        value: AgentIntentV1 | Mapping[str, object],
        *,
        observation: AgentObservationV1,
    ) -> AgentIntentV1:
        try:
            payload = (
                value.model_dump(mode="json") if isinstance(value, AgentIntentV1) else value
            )
            return validate_agent_intent_v1(payload, observation=observation)
        except (TypeError, ValueError) as exc:
            raise RuntimeIntentClaimStoreError(f"invalid Agent Intent: {exc}") from exc

    @staticmethod
    def _validate_binding(
        *,
        observation: AgentObservationV1,
        binding: RuntimeIntentServerBinding,
    ) -> None:
        if binding.workflow_id != observation.workflow.workflow_id:
            raise RuntimeIntentClaimStoreError("server binding workflow mismatch")
        if binding.asset_id != observation.workflow.asset_id:
            raise RuntimeIntentClaimStoreError("server binding asset mismatch")
        if observation.application.identity_ref != (
            f"application:{binding.application_identity_key}"
        ):
            raise RuntimeIntentClaimStoreError("server binding application mismatch")

    @staticmethod
    def _identity_hash(session_id: str, observation_id: str) -> str:
        identity = {"session_id": session_id, "observation_id": observation_id}
        for label, value in identity.items():
            if not isinstance(value, str) or _STABLE_ID_PATTERN.fullmatch(value) is None:
                raise RuntimeIntentClaimStoreError(
                    f"runtime intent claim {label} is invalid"
                )
        return hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()

    def _ensure_layout(self) -> None:
        paths = (
            self.root,
            self.claims_root,
            self.dispatch_started_root,
            self.verification_pending_root,
            self.terminal_root,
            self.confirmation_requests_root,
            self.confirmation_decisions_root,
            self.confirmation_resume_root,
            self.confirmation_closed_root,
            self.grounded_requests_root,
            self.grounded_decisions_root,
            self.grounded_closed_root,
            self.grounded_consume_root,
            self.phase_locks_root,
        )
        if self.root != self.project_root / STORE_ROOT or any(
            path.parent != self.root for path in paths[1:]
        ):
            raise RuntimeIntentClaimStoreError("runtime intent claim store layout is invalid")
        try:
            if self.project_root.resolve() != self.project_root:
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store redirection resolves outside project root"
                )
        except (OSError, RuntimeError) as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime intent claim store layout is unavailable: {exc}"
            ) from exc
        # 固定父子拓扑已覆盖全部祖先；每次仍读取完整目录树，但不重复 mkdir/resolve。
        for path in (self.project_root / "runtime_state", *paths):
            try:
                try:
                    status = os.lstat(path)
                except FileNotFoundError:
                    if not self._create_layout:
                        raise RuntimeIntentClaimStoreError(
                            "runtime intent claim store layout is invalid"
                        ) from None
                    path.mkdir(parents=True, exist_ok=True)
                    status = os.lstat(path)
            except OSError as exc:
                raise RuntimeIntentClaimStoreError(
                    f"runtime intent claim store layout is unavailable: {exc}"
                ) from exc
            if stat.S_ISLNK(status.st_mode) or bool(
                getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
            ):
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store reparse redirection is forbidden"
                )
            if not stat.S_ISDIR(status.st_mode):
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store layout is invalid"
                )

    def _claim_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.claims_root, f"{identity_hash}.json")

    def _dispatch_path(self, identity_hash: str) -> Path:
        return self._bounded_path(
            self.dispatch_started_root,
            f"{identity_hash}.json",
        )

    def _terminal_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.terminal_root, f"{identity_hash}.json")

    def _verification_pending_path(self, identity_hash: str) -> Path:
        return self._bounded_path(
            self.verification_pending_root,
            f"{identity_hash}.json",
        )

    def _confirmation_request_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.confirmation_requests_root, f"{identity_hash}.json")

    def _confirmation_decision_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.confirmation_decisions_root, f"{identity_hash}.json")

    def _confirmation_resume_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.confirmation_resume_root, f"{identity_hash}.json")

    def _confirmation_closed_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.confirmation_closed_root, f"{identity_hash}.json")

    def _grounded_request_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.grounded_requests_root, f"{identity_hash}.json")

    def _grounded_decision_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.grounded_decisions_root, f"{identity_hash}.json")

    def _grounded_closed_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.grounded_closed_root, f"{identity_hash}.json")

    def _grounded_consume_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.grounded_consume_root, f"{identity_hash}.json")

    def _phase_lock_path(self, identity_hash: str) -> Path:
        return self._bounded_path(self.phase_locks_root, f"{identity_hash}.json")

    @contextmanager
    def _claim_phase_fence(self, identity_hash: str) -> Iterator[None]:
        held = getattr(_PHASE_FENCE_STATE, "held", None)
        if held is None:
            held = set()
            _PHASE_FENCE_STATE.held = held
        if identity_hash in held:
            yield
            return
        lock_path = self._phase_lock_path(identity_hash)
        if not self._create_layout and not lock_path.is_file():
            raise RuntimeIntentClaimStoreError("existing claim phase lock is unavailable")
        if self._is_reparse(lock_path):
            raise RuntimeIntentClaimStoreError("claim phase lock reparse is forbidden")
        with _PHASE_LOCK:
            try:
                with _exclusive_file_lock(lock_path, timeout_seconds=10.0):
                    if self._is_reparse(lock_path):
                        raise RuntimeIntentClaimStoreError(
                            "claim phase lock reparse is forbidden"
                        )
                    held.add(identity_hash)
                    try:
                        yield
                    finally:
                        held.remove(identity_hash)
            except TimeoutError as exc:
                raise RuntimeIntentClaimStoreError(
                    "claim phase transition lock timed out"
                ) from exc

    def _bounded_path(self, parent: Path, filename: str) -> Path:
        if _SHA256_PATTERN.fullmatch(filename.removesuffix(".json")) is None:
            raise RuntimeIntentClaimStoreError("runtime intent claim path identity is invalid")
        self._ensure_layout()
        path = parent / filename
        if path.parent != parent or self._is_reparse(path):
            raise RuntimeIntentClaimStoreError("runtime intent claim path escape")
        return path

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime intent claim path is unavailable: {exc}"
            ) from exc
        return stat.S_ISLNK(status.st_mode) or bool(
            getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
        )

    def _publish_bytes(self, target: Path, contents: bytes) -> bool:
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            descriptor = os.open(
                str(temporary),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                if durable_store._IS_WINDOWS:
                    durable_store._publish_windows_no_replace_write_through(
                        temporary,
                        target,
                    )
                else:
                    durable_store._publish_posix_no_replace_durable(
                        temporary,
                        target,
                    )
            except FileExistsError:
                if self._read_bytes(target) != contents:
                    raise _PublishedBytesConflict("published bytes conflict")
                return False
            return True
        except _PublishedBytesConflict:
            raise
        except (OSError, RuntimeIntentClaimStoreError) as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime intent claim durable write failed: {target}: {exc}"
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_bytes(self, path: Path) -> bytes:
        if self._is_reparse(path):
            raise RuntimeIntentClaimStoreError("runtime intent claim reparse is forbidden")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime intent claim object is unreadable: {path}: {exc}"
            ) from exc

    def _read_canonical_json(
        self,
        path: Path,
        *,
        label: str,
    ) -> tuple[bytes, dict[str, Any]]:
        raw = self._read_bytes(path)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeIntentClaimStoreError(f"invalid {label} JSON") from exc
        if not isinstance(value, dict) or _canonical_json_bytes(value) != raw:
            raise RuntimeIntentClaimStoreError(f"invalid or noncanonical {label}")
        return raw, value


__all__ = [
    "RuntimeGroundedConfirmationSnapshot",
    "RuntimeIntentConfirmationSnapshot",
    "RuntimeIntentClaimSnapshot",
    "RuntimeIntentClaimStore",
    "RuntimeIntentClaimStoreError",
    "RuntimeIntentServerBinding",
    "RuntimeVerifiedTerminalReceipt",
    "RuntimeVerificationPendingCheckpoint",
]
