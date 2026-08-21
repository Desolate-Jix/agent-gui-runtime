"""W3b 的最小 durable Intent claim state machine。

该模块只记录 server-bound Observation/Intent 消费与结果关联。Claim 和 phase
marker 永远不授予桌面执行权，也不保存 bbox、click point 或 Gate authority。
Portfolio v1 仍是单一 live controller；敌对并发文件系统交换与分布式锁不在范围内。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

import app.agent.runtime_receipt_store as durable_store
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
    validate_runtime_result_receipt_v1,
)
from app.agent.runtime_receipt_store import (
    RuntimeReceiptRecord,
    RuntimeReceiptStore,
    RuntimeReceiptStoreError,
)


CLAIM_CONTRACT_VERSION = "runtime_intent_claim_v1"
DISPATCH_MARKER_CONTRACT_VERSION = "runtime_intent_dispatch_started_v1"
TERMINAL_MARKER_CONTRACT_VERSION = "runtime_intent_terminal_v1"
STORE_ROOT = Path("runtime_state/runtime-intent-claims-v1")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_PHASE_LOCK = RLock()


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
class RuntimeIntentClaimSnapshot:
    claim_id: str
    claim_content_sha256: str
    phase: Literal["claimed", "dispatch_started", "terminal"]
    observation: AgentObservationV1
    intent: AgentIntentV1
    server_binding: RuntimeIntentServerBinding
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
        self.terminal_root = self.root / "terminal"
        self._receipt_store = receipt_store
        self._ensure_layout()

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
        with _PHASE_LOCK:
            base = self._load_claim(session_id, observation_id)
            identity_hash = self._identity_hash(session_id, observation_id)
            if self._terminal_path(identity_hash).exists():
                raise RuntimeIntentClaimStoreError(
                    "terminal claim cannot return to dispatch_started"
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
        with _PHASE_LOCK:
            base = self._load_claim(session_id, observation_id)
            receipt = self._resolve_receipt(base, receipt_ref)
            self._commit_terminal(base, receipt)
            return self.get_for_observation(
                session_id=session_id,
                observation_id=observation_id,
            )

    def get_for_observation(
        self,
        *,
        session_id: str,
        observation_id: str,
    ) -> RuntimeIntentClaimSnapshot:
        with _PHASE_LOCK:
            base = self._load_claim(session_id, observation_id)
            identity_hash = self._identity_hash(session_id, observation_id)
            dispatch_marker = self._load_optional_marker(
                self._dispatch_path(identity_hash),
                expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
                expected_phase="dispatch_started",
                base=base,
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
                    )
                    self._publish_terminal_marker(base, receipt_record)
                    terminal_marker = self._load_optional_marker(
                        self._terminal_path(identity_hash),
                        expected_contract=TERMINAL_MARKER_CONTRACT_VERSION,
                        expected_phase="terminal",
                        base=base,
                    )
            if receipt_record is not None:
                self._validate_attempt_phase(
                    receipt_record.runtime_receipt,
                    dispatch_started=dispatch_marker is not None,
                )
                phase: Literal["claimed", "dispatch_started", "terminal"] = "terminal"
                terminal_ref = {
                    "receipt_id": receipt_record.runtime_receipt.receipt_id,
                    "content_sha256": receipt_record.content_sha256,
                }
            elif dispatch_marker is not None:
                phase = "dispatch_started"
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
                terminal_receipt_ref=terminal_ref,
                recovery_required=phase != "terminal",
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

    def _commit_terminal(
        self,
        base: Mapping[str, Any],
        receipt: RuntimeReceiptRecord,
    ) -> None:
        identity_hash = self._identity_hash(
            base["observation"].session_id,
            base["observation"].observation_id,
        )
        dispatch_marker = self._load_optional_marker(
            self._dispatch_path(identity_hash),
            expected_contract=DISPATCH_MARKER_CONTRACT_VERSION,
            expected_phase="dispatch_started",
            base=base,
        )
        self._validate_attempt_phase(
            receipt.runtime_receipt,
            dispatch_started=dispatch_marker is not None,
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

    @staticmethod
    def _validate_attempt_phase(
        receipt: RuntimeResultReceiptV1,
        *,
        dispatch_started: bool,
    ) -> None:
        if receipt.attempt_count == 1 and not dispatch_started:
            raise RuntimeIntentClaimStoreError(
                "attempt_count 1 terminal receipt requires dispatch_started"
            )
        if receipt.attempt_count == 0 and dispatch_started:
            raise RuntimeIntentClaimStoreError(
                "attempt_count 0 receipt must terminalize from claimed"
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
            self.terminal_root,
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
    "RuntimeIntentClaimSnapshot",
    "RuntimeIntentClaimStore",
    "RuntimeIntentClaimStoreError",
    "RuntimeIntentServerBinding",
]
