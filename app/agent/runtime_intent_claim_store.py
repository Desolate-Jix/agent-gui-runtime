"""W3b 的最小 durable Intent claim state machine。

该模块只记录 server-bound Observation/Intent 消费与结果关联。Claim 和 phase
marker 永远不授予桌面执行权，也不保存 bbox、click point 或 Gate authority。
Portfolio v1 仍是单一 live controller；敌对并发文件系统交换与分布式锁不在范围内。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
from app.agent.reviewed_workflow_asset import _exclusive_file_lock


CLAIM_CONTRACT_VERSION = "runtime_intent_claim_v1"
DISPATCH_MARKER_CONTRACT_VERSION = "runtime_intent_dispatch_started_v1"
VERIFICATION_PENDING_CONTRACT_VERSION = "runtime_intent_verification_pending_v2"
TERMINAL_MARKER_CONTRACT_VERSION = "runtime_intent_terminal_v1"
CONFIRMATION_REQUEST_CONTRACT_VERSION = "runtime_intent_confirmation_request_v1"
CONFIRMATION_DECISION_CONTRACT_VERSION = "runtime_intent_confirmation_decision_v1"
CONFIRMATION_RESUME_CONTRACT_VERSION = "runtime_intent_confirmation_resume_started_v1"
CONFIRMATION_CLOSED_CONTRACT_VERSION = "runtime_intent_confirmation_closed_v1"
CONFIRMATION_TTL_SECONDS = 300
STORE_ROOT = Path("runtime_state/runtime-intent-claims-v1")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_CURRENT_OBSERVATION_KEYS = {
    "contract_version",
    "asset_id",
    "expected_asset_content_sha256",
    "capture_id",
    "screenshot_sha256",
    "viewport_size",
    "origin",
    "observed_anchor_evidence",
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PHASE_LOCK = RLock()
_PHASE_FENCE_STATE = local()
_SERVER_CONFIRMATION_EVIDENCE_SEAL = object()


class RuntimeIntentClaimStoreError(ValueError):
    """Claim identity、phase 或持久化完整性失败。"""


class _PublishedBytesConflict(RuntimeIntentClaimStoreError):
    pass


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
    def selection(self) -> dict[str, Any]:
        return self._mapping(self._selection_json)

    @property
    def grounding(self) -> dict[str, Any]:
        return self._mapping(self._grounding_json)

    @property
    def gate(self) -> dict[str, Any]:
        return self._mapping(self._gate_json)


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


def _unwrap_server_confirmed_transition_evidence(
    value: object,
) -> RuntimeIntentConfirmationSnapshot | None:
    if (
        not isinstance(value, _ServerConfirmedTransitionEvidence)
        or value._seal is not _SERVER_CONFIRMATION_EVIDENCE_SEAL
    ):
        return None
    return value.confirmation


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
    ) -> None:
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
        self.phase_locks_root = self.root / "phase-locks"
        self._receipt_store = receipt_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._ensure_layout()

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

    def mark_dispatch_started(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
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
    ) -> RuntimeIntentClaimSnapshot:
        """封存 definitive dispatch 后只读 verification 所需的 server evidence。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
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
                current_observation=current_observation,
                selection=selection,
                grounding=grounding,
                gate=gate,
                gate_decision_ref=gate_decision_ref,
                backend_receipt=backend_receipt,
                target_process_id=target_process_id,
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

    def find_for_observation(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot | None:
        """只在 canonical claim 确实不存在时返回 None。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        if not self._claim_path(identity_hash).exists():
            return None
        return self.get_for_observation(
            session_id=session_id,
            observation_id=observation_id,
        )

    def list_unresolved_claims(self) -> tuple[RuntimeIntentClaimSnapshot, ...]:
        """严格校验并返回阻止新本地会话的 durable claims。"""

        try:
            paths = tuple(sorted(self.claims_root.iterdir(), key=lambda item: item.name))
        except OSError as exc:
            raise RuntimeIntentClaimStoreError(
                "runtime intent claim inventory is unavailable"
            ) from exc
        unresolved: list[RuntimeIntentClaimSnapshot] = []
        unresolved_phases = {
            "claimed",
            "confirmation_pending",
            "confirmation_approved",
            "confirmation_resume_started",
            "dispatch_started",
            "verification_pending",
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

    def load_terminal_receipt(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeResultReceiptV1:
        """解析 terminal marker 指向的权威 Receipt。"""

        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
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
            ).runtime_receipt

    def get_for_observation(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        identity_hash = self._identity_hash(session_id, observation_id)
        with self._claim_phase_fence(identity_hash):
            base = self._load_claim(session_id, observation_id)
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
        verification_marker = self._load_verification_pending_marker(
            self._verification_pending_path(identity_hash),
            base=base,
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
        )
        marker: dict[str, object] = {
            "store_contract_version": VERIFICATION_PENDING_CONTRACT_VERSION,
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
        marker["checkpoint_sha256"] = _payload_sha256(marker)
        return marker

    def _load_verification_pending_marker(
        self,
        path: Path,
        *,
        base: Mapping[str, Any],
    ) -> dict[str, Any] | None:
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
        digest_payload = dict(marker)
        checkpoint_sha256 = digest_payload.pop("checkpoint_sha256", None)
        if (
            set(marker) != expected_keys
            or marker.get("store_contract_version")
            != VERIFICATION_PENDING_CONTRACT_VERSION
            or marker.get("phase") != "verification_pending"
            or marker.get("claim_id") != base["claim_id"]
            or marker.get("claim_content_sha256") != base["claim_content_sha256"]
            or marker.get("artifact_is_authorization") is not False
            or marker.get("grants_action_authority") is not False
            or checkpoint_sha256 != _payload_sha256(digest_payload)
        ):
            raise RuntimeIntentClaimStoreError(
                "invalid or tampered verification_pending marker"
            )
        backend_payload = marker.get("backend_receipt")
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
        )
        observation: AgentObservationV1 = base["observation"]
        identity_hash = self._identity_hash(
            observation.session_id,
            observation.observation_id,
        )
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
        return marker

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
    ) -> None:
        observation: AgentObservationV1 = base["observation"]
        intent: AgentIntentV1 = base["intent"]
        workflow = observation.workflow
        if (
            set(current_observation) != _CURRENT_OBSERVATION_KEYS
            or current_observation.get("contract_version")
            != "reviewed_workflow_current_observation_v1"
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
        )

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
            self.phase_locks_root,
        )
        for path in (self.project_root / "runtime_state", *paths):
            if path.exists() and self._is_reparse(path):
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store reparse redirection is forbidden"
                )
        try:
            for path in paths[1:]:
                path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeIntentClaimStoreError(
                f"runtime intent claim store layout is unavailable: {exc}"
            ) from exc
        for path in paths:
            if not path.is_dir() or self._is_reparse(path):
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store layout is invalid"
                )
            try:
                path.resolve().relative_to(self.project_root)
            except ValueError as exc:
                raise RuntimeIntentClaimStoreError(
                    "runtime intent claim store redirection resolves outside project root"
                ) from exc

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
    "RuntimeIntentConfirmationSnapshot",
    "RuntimeIntentClaimSnapshot",
    "RuntimeIntentClaimStore",
    "RuntimeIntentClaimStoreError",
    "RuntimeIntentServerBinding",
    "RuntimeVerificationPendingCheckpoint",
]
