"""W3b 的不可变 Runtime Receipt 持久化边界。

该 store 只封存已经生成的 Runtime Result Receipt 及其可选 backend
receipt。它不授予执行权，也不提供 exactly-once 或 Session ledger 语义。

Portfolio v1 会拒绝静态 junction/reparse 重定向，但不声称能够抵御具有并发
文件系统写权限的攻击者在校验后交换目录；该威胁需要独立的安全文件系统边界。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import AgentObservationV1, RuntimeResultReceiptV1


STORE_CONTRACT_VERSION = "runtime_receipt_record_v1"
STORE_CONTRACT_VERSION_V2 = "runtime_receipt_record_v2"
POINTER_CONTRACT_VERSION = "runtime_receipt_pointer_v1"
INTENT_POINTER_CONTRACT_VERSION = "runtime_receipt_intent_pointer_v1"
STORE_ROOT = Path("runtime_state/runtime-receipts-v1")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_IS_WINDOWS = os.name == "nt"
_VERIFIED_VERIFICATION_KEYS = {
    "contract_version",
    "status",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "state_advanced",
    "asset_content_sha256",
    "selection_sha256",
    "transition_id",
    "source_state_id",
    "target_state_id",
    "post_capture_lineage",
    "post_state_resolution",
    "evidence_refs",
}
_BLOCKED_VERIFICATION_BASE_KEYS = {
    "contract_version",
    "status",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "failure_code",
    "state_advanced",
}
_CAPTURE_LINEAGE_KEYS = {"capture_id", "screenshot_sha256", "viewport_size"}
_RESOLVED_STATE_KEYS = {
    "contract_version",
    "status",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "asset_id",
    "asset_content_sha256",
    "source_workflow_sha256",
    "reviewed_revision_hash",
    "canonical_origin",
    "state_id",
    "state_availability",
    "score",
    "capture_lineage",
    "observed_origin",
    "matched_anchor_ids",
    "evidence_refs",
    "resolution_sha256",
}
_BLOCKED_STATE_BASE_KEYS = {
    "contract_version",
    "status",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "failure_code",
    "asset_id",
    "asset_content_sha256",
    "source_workflow_sha256",
    "reviewed_revision_hash",
    "canonical_origin",
    "capture_lineage",
    "evidence_refs",
}


class RuntimeReceiptStoreError(ValueError):
    """Receipt 持久化、完整性或身份校验失败。"""


class _PublishedBytesConflict(RuntimeReceiptStoreError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeReceiptRecord:
    runtime_receipt: RuntimeResultReceiptV1
    backend_receipt: BackendDispatchReceipt | None
    content_sha256: str
    verification_evidence: dict[str, Any] | None = None
    next_observation: AgentObservationV1 | None = None


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
        raise RuntimeReceiptStoreError(
            f"runtime receipt serialization failed: {exc}"
        ) from exc


def _publish_windows_no_replace_write_through(
    temporary: Path,
    target: Path,
) -> None:
    """使用无覆盖、write-through 的 Windows rename 发布文件。"""

    import ctypes
    from ctypes import wintypes

    move_file_ex = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
    move_file_ex.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file_ex.restype = wintypes.BOOL
    movefile_write_through = 0x00000008
    if move_file_ex(str(temporary), str(target), movefile_write_through):
        return
    error_code = ctypes.get_last_error()
    if error_code in {80, 183}:  # ERROR_FILE_EXISTS / ERROR_ALREADY_EXISTS
        raise FileExistsError(error_code, "target already exists", str(target))
    raise OSError(error_code, "MoveFileExW durable publish failed", str(target))


def _fsync_file(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(str(path), flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _publish_posix_no_replace_durable(temporary: Path, target: Path) -> None:
    """通过 no-replace hard link 发布，并同步文件和父目录。"""

    os.link(str(temporary), str(target))
    try:
        _fsync_file(target)
        _fsync_directory(target.parent)
    except OSError:
        # durability 未确认时撤回可见名称；临时文件仍由调用方清理。
        try:
            target.unlink(missing_ok=True)
            _fsync_directory(target.parent)
        except OSError:
            pass
        raise


class RuntimeReceiptStore:
    """固定项目目录中的 append-only Runtime Receipt CAS。

    静态 reparse 重定向会 fail closed；敌对并发目录交换不属于 Portfolio v1。
    """

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / STORE_ROOT
        self.objects_root = self.root / "objects"
        self.receipt_ids_root = self.root / "receipt-ids"
        self.intent_ids_root = self.root / "intent-ids"
        self._ensure_layout()

    def put(
        self,
        receipt: RuntimeResultReceiptV1 | Mapping[str, object],
        *,
        backend_receipt: BackendDispatchReceipt | None = None,
        verification_evidence: Mapping[str, object] | None = None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None = None,
    ) -> dict[str, str]:
        """验证并不可变发布一个 Receipt record。"""

        validated = self._validate_runtime_receipt(receipt)
        if backend_receipt is not None and not isinstance(
            backend_receipt, BackendDispatchReceipt
        ):
            raise RuntimeReceiptStoreError("invalid backend receipt object")
        self._validate_backend_pairing(validated, backend_receipt)
        verified_evidence, validated_next = self._validate_semantic_evidence(
            validated,
            verification_evidence=verification_evidence,
            next_observation=next_observation,
        )
        envelope: dict[str, object] = {
            "store_contract_version": (
                STORE_CONTRACT_VERSION_V2
                if verified_evidence is not None
                else STORE_CONTRACT_VERSION
            ),
            "runtime_receipt": validated.model_dump(mode="json"),
            "backend_receipt": (
                asdict(backend_receipt) if backend_receipt is not None else None
            ),
        }
        if verified_evidence is not None:
            envelope.update(
                verification_evidence=verified_evidence,
                next_observation=(
                    validated_next.model_dump(mode="json")
                    if validated_next is not None
                    else None
                ),
                application=(
                    validated_next.application.model_dump(mode="json")
                    if validated_next is not None
                    else None
                ),
            )
        object_bytes = _canonical_json_bytes(envelope)
        content_sha256 = hashlib.sha256(object_bytes).hexdigest()
        object_path = self._object_path(content_sha256)
        self._publish_bytes(object_path, object_bytes)

        pointer = {
            "store_contract_version": POINTER_CONTRACT_VERSION,
            "receipt_id": validated.receipt_id,
            "content_sha256": content_sha256,
        }
        pointer_path = self._pointer_path(validated.receipt_id)
        try:
            self._publish_bytes(pointer_path, _canonical_json_bytes(pointer))
        except _PublishedBytesConflict as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt identity conflict: {validated.receipt_id}"
            ) from exc
        intent_pointer = {
            "store_contract_version": INTENT_POINTER_CONTRACT_VERSION,
            "session_id": validated.session_id,
            "observation_id": validated.observation_id,
            "intent_id": validated.intent_id,
            "receipt_id": validated.receipt_id,
            "content_sha256": content_sha256,
        }
        intent_pointer_path = self._intent_pointer_path(
            session_id=validated.session_id,
            observation_id=validated.observation_id,
            intent_id=validated.intent_id,
        )
        try:
            self._publish_bytes(
                intent_pointer_path,
                _canonical_json_bytes(intent_pointer),
            )
        except _PublishedBytesConflict as exc:
            raise RuntimeReceiptStoreError(
                "runtime receipt intent identity conflict"
            ) from exc
        return {
            "receipt_id": validated.receipt_id,
            "content_sha256": content_sha256,
        }

    def get(self, ref: Mapping[str, object]) -> RuntimeReceiptRecord:
        """读取并重新验证一个精确 immutable ref。"""

        if not isinstance(ref, Mapping) or set(ref) != {
            "receipt_id",
            "content_sha256",
        }:
            raise RuntimeReceiptStoreError("invalid runtime receipt immutable ref")
        receipt_id = ref.get("receipt_id")
        digest = ref.get("content_sha256")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise RuntimeReceiptStoreError("invalid runtime receipt immutable ref")
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise RuntimeReceiptStoreError("invalid runtime receipt immutable ref")

        committed_digest = self._load_pointer_digest(receipt_id)
        if committed_digest != digest:
            raise RuntimeReceiptStoreError(
                "runtime receipt identity pointer does not match immutable ref"
            )
        record = self._get_object(receipt_id=receipt_id, digest=digest)
        self._require_intent_pointer(record)
        return record

    def _get_object(self, *, receipt_id: str, digest: str) -> RuntimeReceiptRecord:
        """读取 CAS object；调用方必须先证明 receipt identity 已提交。"""

        object_path = self._object_path(digest)
        raw, envelope = self._read_canonical_json(object_path, label="receipt object")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeReceiptStoreError("runtime receipt object checksum mismatch")
        version = envelope.get("store_contract_version")
        v1_keys = {
            "store_contract_version",
            "runtime_receipt",
            "backend_receipt",
        }
        v2_keys = v1_keys | {
            "verification_evidence",
            "next_observation",
            "application",
        }
        if (
            version == STORE_CONTRACT_VERSION
            and set(envelope) != v1_keys
        ) or (
            version == STORE_CONTRACT_VERSION_V2
            and set(envelope) != v2_keys
        ) or version not in {STORE_CONTRACT_VERSION, STORE_CONTRACT_VERSION_V2}:
            raise RuntimeReceiptStoreError("invalid runtime receipt record contract")
        runtime_payload = envelope.get("runtime_receipt")
        if not isinstance(runtime_payload, Mapping):
            raise RuntimeReceiptStoreError("runtime receipt record payload is invalid")
        runtime_receipt = self._validate_runtime_receipt(runtime_payload)
        if runtime_receipt.receipt_id != receipt_id:
            raise RuntimeReceiptStoreError("runtime receipt record identity mismatch")
        backend_receipt = self._validate_backend_payload(envelope.get("backend_receipt"))
        self._validate_backend_pairing(runtime_receipt, backend_receipt)
        verification_evidence: dict[str, Any] | None = None
        next_observation: AgentObservationV1 | None = None
        if version == STORE_CONTRACT_VERSION_V2:
            verification_payload = envelope.get("verification_evidence")
            observation_payload = envelope.get("next_observation")
            if not isinstance(verification_payload, Mapping) or (
                observation_payload is not None
                and not isinstance(observation_payload, Mapping)
            ):
                raise RuntimeReceiptStoreError(
                    "invalid persisted receipt verification evidence"
                )
            verification_evidence, next_observation = self._validate_semantic_evidence(
                runtime_receipt,
                verification_evidence=verification_payload,
                next_observation=observation_payload,
            )
            application = envelope.get("application")
            if next_observation is None:
                if application is not None:
                    raise RuntimeReceiptStoreError(
                        "verification failure cannot bind an application"
                    )
            elif (
                not isinstance(application, Mapping)
                or dict(application)
                != next_observation.application.model_dump(mode="json")
            ):
                raise RuntimeReceiptStoreError("next observation application mismatch")
        return RuntimeReceiptRecord(
            runtime_receipt=runtime_receipt,
            backend_receipt=backend_receipt,
            content_sha256=digest,
            verification_evidence=verification_evidence,
            next_observation=next_observation,
        )

    def resolve_verification_evidence(
        self,
        ref_or_receipt_id: Mapping[str, object] | str,
    ) -> dict[str, Any]:
        """通过已有权威 Receipt 路径解析 verification，不维护第二套索引。"""

        record = self._resolve_record(ref_or_receipt_id)
        if record.verification_evidence is None:
            raise RuntimeReceiptStoreError(
                "runtime receipt has no persisted verification evidence"
            )
        return json.loads(_canonical_json_bytes(record.verification_evidence))

    def resolve_next_observation(
        self,
        ref_or_receipt_id: Mapping[str, object] | str,
    ) -> AgentObservationV1:
        """从权威 Receipt CAS object 解析其精确 next observation。"""

        record = self._resolve_record(ref_or_receipt_id)
        if record.next_observation is None:
            raise RuntimeReceiptStoreError(
                "runtime receipt has no persisted next observation"
            )
        return record.next_observation

    def _resolve_record(
        self,
        ref_or_receipt_id: Mapping[str, object] | str,
    ) -> RuntimeReceiptRecord:
        if isinstance(ref_or_receipt_id, str):
            return self.load_by_receipt_id(ref_or_receipt_id)
        if isinstance(ref_or_receipt_id, Mapping):
            return self.get(ref_or_receipt_id)
        raise RuntimeReceiptStoreError("invalid runtime receipt resolver reference")

    def load_by_receipt_id(self, receipt_id: str) -> RuntimeReceiptRecord:
        """通过 Windows-safe hashed identity index 读取 Receipt。"""

        if not isinstance(receipt_id, str) or not receipt_id:
            raise RuntimeReceiptStoreError("receipt_id is required")
        digest = self._load_pointer_digest(receipt_id)
        record = self._get_object(receipt_id=receipt_id, digest=digest)
        self._require_intent_pointer(record)
        return record

    def find_for_intent(
        self,
        *,
        session_id: str,
        observation_id: str,
        intent_id: str,
    ) -> RuntimeReceiptRecord | None:
        """查找已经同时提交 receipt 与 intent identity 的权威结果。"""

        pointer_path = self._intent_pointer_path(
            session_id=session_id,
            observation_id=observation_id,
            intent_id=intent_id,
        )
        if not pointer_path.exists():
            return None
        pointer = self._load_intent_pointer(
            session_id=session_id,
            observation_id=observation_id,
            intent_id=intent_id,
        )
        record = self.get(
            {
                "receipt_id": pointer["receipt_id"],
                "content_sha256": pointer["content_sha256"],
            }
        )
        receipt = record.runtime_receipt
        if (
            receipt.session_id != session_id
            or receipt.observation_id != observation_id
            or receipt.intent_id != intent_id
        ):
            raise RuntimeReceiptStoreError(
                "runtime receipt intent lookup identity mismatch"
            )
        return record

    def _load_pointer_digest(self, receipt_id: str) -> str:
        pointer_path = self._pointer_path(receipt_id)
        if not pointer_path.exists():
            raise RuntimeReceiptStoreError(
                "runtime receipt identity pointer is missing"
            )
        _, pointer = self._read_canonical_json(pointer_path, label="receipt pointer")
        if set(pointer) != {
            "store_contract_version",
            "receipt_id",
            "content_sha256",
        } or pointer.get("store_contract_version") != POINTER_CONTRACT_VERSION:
            raise RuntimeReceiptStoreError("invalid runtime receipt pointer contract")
        if pointer.get("receipt_id") != receipt_id:
            raise RuntimeReceiptStoreError("runtime receipt pointer identity mismatch")
        digest = pointer.get("content_sha256")
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise RuntimeReceiptStoreError("runtime receipt pointer checksum is invalid")
        return digest

    def _require_intent_pointer(self, record: RuntimeReceiptRecord) -> None:
        receipt = record.runtime_receipt
        pointer = self._load_intent_pointer(
            session_id=receipt.session_id,
            observation_id=receipt.observation_id,
            intent_id=receipt.intent_id,
        )
        if (
            pointer["receipt_id"] != receipt.receipt_id
            or pointer["content_sha256"] != record.content_sha256
        ):
            raise RuntimeReceiptStoreError(
                "runtime receipt intent authority pointer mismatch"
            )

    def _load_intent_pointer(
        self,
        *,
        session_id: str,
        observation_id: str,
        intent_id: str,
    ) -> dict[str, str]:
        path = self._intent_pointer_path(
            session_id=session_id,
            observation_id=observation_id,
            intent_id=intent_id,
        )
        if not path.exists():
            raise RuntimeReceiptStoreError(
                "runtime receipt intent authority pointer is missing"
            )
        _, pointer = self._read_canonical_json(path, label="intent pointer")
        expected_keys = {
            "store_contract_version",
            "session_id",
            "observation_id",
            "intent_id",
            "receipt_id",
            "content_sha256",
        }
        if (
            set(pointer) != expected_keys
            or pointer.get("store_contract_version")
            != INTENT_POINTER_CONTRACT_VERSION
        ):
            raise RuntimeReceiptStoreError(
                "invalid runtime receipt intent pointer contract"
            )
        expected_identity = (session_id, observation_id, intent_id)
        actual_identity = (
            pointer.get("session_id"),
            pointer.get("observation_id"),
            pointer.get("intent_id"),
        )
        if actual_identity != expected_identity:
            raise RuntimeReceiptStoreError(
                "runtime receipt intent pointer identity mismatch"
            )
        receipt_id = pointer.get("receipt_id")
        digest = pointer.get("content_sha256")
        if not isinstance(receipt_id, str) or not receipt_id:
            raise RuntimeReceiptStoreError(
                "runtime receipt intent pointer receipt identity is invalid"
            )
        if not isinstance(digest, str) or _SHA256_PATTERN.fullmatch(digest) is None:
            raise RuntimeReceiptStoreError(
                "runtime receipt intent pointer checksum is invalid"
            )
        return {
            "session_id": session_id,
            "observation_id": observation_id,
            "intent_id": intent_id,
            "receipt_id": receipt_id,
            "content_sha256": digest,
        }

    @staticmethod
    def _validate_runtime_receipt(
        receipt: RuntimeResultReceiptV1 | Mapping[str, object],
    ) -> RuntimeResultReceiptV1:
        try:
            payload = (
                receipt.model_dump(mode="json")
                if isinstance(receipt, RuntimeResultReceiptV1)
                else receipt
            )
            return RuntimeResultReceiptV1.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise RuntimeReceiptStoreError(f"invalid runtime receipt: {exc}") from exc

    @classmethod
    def _validate_semantic_evidence(
        cls,
        receipt: RuntimeResultReceiptV1,
        *,
        verification_evidence: Mapping[str, object] | None,
        next_observation: AgentObservationV1 | Mapping[str, object] | None,
    ) -> tuple[dict[str, Any] | None, AgentObservationV1 | None]:
        """只校验调用方已重算的结果及谱系；store 不执行或伪造 verification。"""

        semantic_success = receipt.outcome == "VERIFIED" or (
            receipt.outcome == "SAFE_STOP"
            and receipt.dispatch_status == "dispatched"
        )
        verification_failed = receipt.outcome == "VERIFICATION_FAILED"
        if not semantic_success and not verification_failed:
            if verification_evidence is not None or next_observation is not None:
                raise RuntimeReceiptStoreError(
                    "only semantic-success or verification-failed receipts "
                    "accept verification evidence"
                )
            return None, None
        if verification_evidence is None:
            raise RuntimeReceiptStoreError(
                "verified receipt requires verification evidence"
            )
        if verification_failed and next_observation is not None:
            raise RuntimeReceiptStoreError(
                "verification-failed receipt forbids a next observation"
            )
        if semantic_success and next_observation is None:
            raise RuntimeReceiptStoreError(
                "semantic-success receipt requires verification evidence "
                "and a next observation"
            )
        if not isinstance(verification_evidence, Mapping):
            raise RuntimeReceiptStoreError("verification evidence must be an object")
        try:
            verification = json.loads(
                _canonical_json_bytes(verification_evidence).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeReceiptStoreError(
                "verification evidence must be canonical JSON"
            ) from exc
        if not isinstance(verification, dict):
            raise RuntimeReceiptStoreError("verification evidence must be an object")
        verification_ref = (
            f"verification:{hashlib.sha256(_canonical_json_bytes(verification)).hexdigest()}"
        )
        if receipt.evidence.verification_ref != verification_ref:
            raise RuntimeReceiptStoreError("verification reference mismatch")
        if verification_failed:
            cls._validate_blocked_verification(receipt, verification)
            return verification, None

        try:
            observation_payload = (
                next_observation.model_dump(mode="json")
                if isinstance(next_observation, AgentObservationV1)
                else next_observation
            )
            observation = AgentObservationV1.model_validate(observation_payload)
        except (TypeError, ValueError) as exc:
            raise RuntimeReceiptStoreError(
                f"invalid next AgentObservationV1: {exc}"
            ) from exc
        if receipt.next_observation_id != observation.observation_id:
            raise RuntimeReceiptStoreError("next observation identity mismatch")
        if receipt.observation_id == observation.observation_id:
            raise RuntimeReceiptStoreError("next observation ID must be new")
        if receipt.session_id != observation.session_id:
            raise RuntimeReceiptStoreError("next observation session mismatch")
        if receipt.workflow != observation.workflow:
            raise RuntimeReceiptStoreError("next observation workflow mismatch")
        cls._validate_verification_lineage(receipt, verification, observation)
        return verification, observation

    @classmethod
    def _validate_blocked_verification(
        cls,
        receipt: RuntimeResultReceiptV1,
        verification: Mapping[str, Any],
    ) -> None:
        failure_code = verification.get("failure_code")
        expected_keys = set(_BLOCKED_VERIFICATION_BASE_KEYS)
        if failure_code in {"destination_mismatch", "post_action_failure"}:
            expected_keys.add("post_state_resolution")
        if (
            set(verification) != expected_keys
            or
            verification.get("contract_version") != "transition_verification_v1"
            or verification.get("status") != "blocked"
            or verification.get("artifact_is_authorization") is not False
            or verification.get("execute_binding_enabled") is not False
            or verification.get("state_advanced") is not False
        ):
            raise RuntimeReceiptStoreError(
                "verification failure evidence is not a blocked result"
            )
        if failure_code != receipt.reason_code:
            raise RuntimeReceiptStoreError(
                "verification failure reason mismatch"
            )
        if failure_code == "destination_mismatch":
            cls._validate_resolved_state(
                receipt,
                verification.get("post_state_resolution"),
                observation=None,
            )
        elif failure_code == "post_action_failure":
            cls._validate_blocked_state(
                receipt,
                verification.get("post_state_resolution"),
            )

    @classmethod
    def _validate_verification_lineage(
        cls,
        receipt: RuntimeResultReceiptV1,
        verification: Mapping[str, Any],
        observation: AgentObservationV1,
    ) -> None:
        if (
            set(verification) != _VERIFIED_VERIFICATION_KEYS
            or
            verification.get("contract_version") != "transition_verification_v1"
            or verification.get("status") != "verified"
            or verification.get("artifact_is_authorization") is not False
            or verification.get("execute_binding_enabled") is not False
            or verification.get("state_advanced") is not True
        ):
            raise RuntimeReceiptStoreError(
                "verification evidence is not a semantic-success result"
            )
        if (
            verification.get("asset_content_sha256")
            != receipt.workflow.asset_content_sha256
        ):
            raise RuntimeReceiptStoreError("verification workflow mismatch")
        if verification.get("transition_id") != receipt.action.action_id:
            raise RuntimeReceiptStoreError("verification transition mismatch")
        if (
            not isinstance(verification.get("selection_sha256"), str)
            or _SHA256_PATTERN.fullmatch(verification["selection_sha256"]) is None
            or not isinstance(verification.get("source_state_id"), str)
            or not verification["source_state_id"]
        ):
            raise RuntimeReceiptStoreError("verification lineage is invalid")
        if verification.get("target_state_id") != observation.state.state_id:
            raise RuntimeReceiptStoreError("verification destination mismatch")
        capture = verification.get("post_capture_lineage")
        cls._validate_capture_lineage(capture)
        assert isinstance(capture, Mapping)
        if (
            capture.get("capture_id") != observation.current_capture.capture_id
            or capture.get("screenshot_sha256")
            != observation.current_capture.screenshot_sha256
        ):
            raise RuntimeReceiptStoreError("verification capture mismatch")
        state = verification.get("post_state_resolution")
        cls._validate_resolved_state(receipt, state, observation=observation)
        assert isinstance(state, Mapping)
        if dict(state["capture_lineage"]) != dict(capture):
            raise RuntimeReceiptStoreError("verification capture mismatch")
        evidence_refs = cls._validate_ref_list(
            verification.get("evidence_refs"),
            label="verification evidence refs",
            allow_empty=False,
        )
        state_refs = cls._validate_ref_list(
            state.get("evidence_refs"),
            label="post-resolution evidence refs",
            allow_empty=False,
        )
        required_refs = {
            receipt.evidence.candidate_ref,
            receipt.evidence.gate_decision_ref,
            receipt.evidence.backend_receipt_ref,
            *receipt.evidence.trace_refs,
            *state_refs,
        }
        if None in required_refs or not required_refs.issubset(set(evidence_refs)):
            raise RuntimeReceiptStoreError(
                "verification evidence refs do not cover receipt lineage"
            )

    @classmethod
    def _validate_resolved_state(
        cls,
        receipt: RuntimeResultReceiptV1,
        value: object,
        *,
        observation: AgentObservationV1 | None,
    ) -> None:
        if not isinstance(value, Mapping) or set(value) != _RESOLVED_STATE_KEYS:
            raise RuntimeReceiptStoreError("invalid resolved post-state contract")
        if (
            value.get("contract_version") != "current_state_resolution_v1"
            or value.get("status") != "resolved"
            or value.get("artifact_is_authorization") is not False
            or value.get("execute_binding_enabled") is not False
            or value.get("asset_id") != receipt.workflow.asset_id
            or value.get("asset_content_sha256")
            != receipt.workflow.asset_content_sha256
            or value.get("source_workflow_sha256")
            != receipt.workflow.source_workflow_sha256
            or value.get("reviewed_revision_hash")
            != receipt.workflow.reviewed_revision_hash
        ):
            raise RuntimeReceiptStoreError("post-state workflow mismatch")
        cls._validate_capture_lineage(value.get("capture_lineage"))
        score = value.get("score")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(score)
            or score < 0
        ):
            raise RuntimeReceiptStoreError("post-state score is invalid")
        if (
            not isinstance(value.get("state_id"), str)
            or not value["state_id"]
            or value.get("state_availability") not in {"reviewed", "stop_boundary"}
            or not isinstance(value.get("resolution_sha256"), str)
            or _SHA256_PATTERN.fullmatch(value["resolution_sha256"]) is None
        ):
            raise RuntimeReceiptStoreError("post-state identity is invalid")
        cls._validate_ref_list(
            value.get("evidence_refs"),
            label="post-resolution evidence refs",
            allow_empty=False,
        )
        anchors = value.get("matched_anchor_ids")
        if (
            not isinstance(anchors, list)
            or not anchors
            or any(not isinstance(item, str) or not item for item in anchors)
            or anchors != sorted(set(anchors))
        ):
            raise RuntimeReceiptStoreError("post-state anchors are invalid")
        canonical_origin = cls._normalized_http_origin(value.get("canonical_origin"))
        observed_origin = cls._normalized_http_origin(value.get("observed_origin"))
        if canonical_origin is None or observed_origin is None:
            raise RuntimeReceiptStoreError("next observation application mismatch")
        if observation is None:
            return
        if observation.application.kind != "web":
            raise RuntimeReceiptStoreError(
                "native application verification is unsupported"
            )
        if (
            value.get("state_id") != observation.state.state_id
            or value.get("state_availability")
            != observation.state.state_availability
            or value.get("resolution_sha256")
            != observation.state.resolution_sha256
        ):
            raise RuntimeReceiptStoreError("verification state resolution mismatch")
        parsed = urlsplit(observed_origin)
        if observation.application.identity_ref != f"application:web:{parsed.hostname}":
            raise RuntimeReceiptStoreError("next observation application mismatch")

    @classmethod
    def _validate_blocked_state(
        cls,
        receipt: RuntimeResultReceiptV1,
        value: object,
    ) -> None:
        if not isinstance(value, Mapping):
            raise RuntimeReceiptStoreError("invalid blocked post-state contract")
        failure_code = value.get("failure_code")
        expected_keys = set(_BLOCKED_STATE_BASE_KEYS)
        if failure_code == "current_state_ambiguous":
            expected_keys.add("candidate_state_ids")
        if (
            set(value) != expected_keys
            or failure_code
            not in {"current_state_unresolved", "current_state_ambiguous"}
            or value.get("contract_version") != "current_state_resolution_v1"
            or value.get("status") != "blocked"
            or value.get("artifact_is_authorization") is not False
            or value.get("execute_binding_enabled") is not False
            or value.get("asset_id") != receipt.workflow.asset_id
            or value.get("asset_content_sha256")
            != receipt.workflow.asset_content_sha256
            or value.get("source_workflow_sha256")
            != receipt.workflow.source_workflow_sha256
            or value.get("reviewed_revision_hash")
            != receipt.workflow.reviewed_revision_hash
            or cls._normalized_http_origin(value.get("canonical_origin")) is None
        ):
            raise RuntimeReceiptStoreError("invalid blocked post-state contract")
        cls._validate_capture_lineage(value.get("capture_lineage"))
        cls._validate_ref_list(
            value.get("evidence_refs"),
            label="blocked post-resolution evidence refs",
            allow_empty=True,
        )
        if failure_code == "current_state_ambiguous":
            candidates = value.get("candidate_state_ids")
            if (
                not isinstance(candidates, list)
                or len(candidates) < 2
                or any(not isinstance(item, str) or not item for item in candidates)
                or candidates != sorted(set(candidates))
            ):
                raise RuntimeReceiptStoreError("invalid blocked post-state candidates")

    @staticmethod
    def _validate_capture_lineage(value: object) -> None:
        if not isinstance(value, Mapping) or set(value) != _CAPTURE_LINEAGE_KEYS:
            raise RuntimeReceiptStoreError("invalid verification capture lineage")
        viewport = value.get("viewport_size")
        if (
            not isinstance(value.get("capture_id"), str)
            or not value["capture_id"]
            or not isinstance(value.get("screenshot_sha256"), str)
            or _SHA256_PATTERN.fullmatch(value["screenshot_sha256"]) is None
            or not isinstance(viewport, Mapping)
            or set(viewport) != {"width", "height"}
            or any(
                not isinstance(viewport.get(key), int)
                or isinstance(viewport.get(key), bool)
                or viewport[key] <= 0
                for key in ("width", "height")
            )
        ):
            raise RuntimeReceiptStoreError("invalid verification capture lineage")

    @staticmethod
    def _validate_ref_list(
        value: object,
        *,
        label: str,
        allow_empty: bool,
    ) -> list[str]:
        if (
            not isinstance(value, list)
            or (not allow_empty and not value)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(set(value))
        ):
            raise RuntimeReceiptStoreError(f"invalid {label}")
        return value

    @staticmethod
    def _normalized_http_origin(value: object) -> str | None:
        if not isinstance(value, str) or not value or value != value.strip():
            return None
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            return None
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if (
            scheme not in {"http", "https"}
            or not hostname
            or any(character.isspace() for character in hostname)
            or "%" in hostname
            or "\\" in parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            return None
        default_port = 80 if scheme == "http" else 443
        port_suffix = "" if port in {None, default_port} else f":{port}"
        display_hostname = f"[{hostname}]" if ":" in hostname else hostname
        normalized = f"{scheme}://{display_hostname}{port_suffix}"
        return normalized if value == normalized else None

    @staticmethod
    def _validate_backend_payload(value: object) -> BackendDispatchReceipt | None:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {
            "receipt_ref",
            "status",
            "reason_code",
        }:
            raise RuntimeReceiptStoreError("invalid backend receipt record")
        receipt_ref = value.get("receipt_ref")
        status = value.get("status")
        reason_code = value.get("reason_code")
        if not isinstance(receipt_ref, str) or not receipt_ref:
            raise RuntimeReceiptStoreError("invalid backend receipt reference")
        if status not in {"dispatched", "not_started", "indeterminate"}:
            raise RuntimeReceiptStoreError("invalid backend receipt status")
        if reason_code not in {"none", "backend_failed", "backend_result_lost"}:
            raise RuntimeReceiptStoreError("invalid backend receipt reason")
        return BackendDispatchReceipt(
            receipt_ref=receipt_ref,
            status=status,
            reason_code=reason_code,
        )

    @staticmethod
    def _validate_backend_pairing(
        receipt: RuntimeResultReceiptV1,
        backend_receipt: BackendDispatchReceipt | None,
    ) -> None:
        backend_ref = receipt.evidence.backend_receipt_ref
        if backend_ref is None:
            if backend_receipt is not None:
                raise RuntimeReceiptStoreError(
                    "runtime receipt without backend reference cannot have a backend receipt"
                )
            return
        if backend_receipt is None:
            raise RuntimeReceiptStoreError("backend receipt is required")
        if backend_receipt.receipt_ref != backend_ref:
            raise RuntimeReceiptStoreError("backend receipt reference mismatch")

        expected = {
            "dispatched": ("dispatched", "none"),
            "not_started": ("not_started", "backend_failed"),
            "indeterminate": ("indeterminate", "backend_result_lost"),
        }[receipt.dispatch_status]
        if backend_receipt.status != expected[0]:
            raise RuntimeReceiptStoreError("backend receipt status mismatch")
        if backend_receipt.reason_code != expected[1]:
            raise RuntimeReceiptStoreError("backend receipt reason mismatch")
        if (
            receipt.dispatch_status == "not_started"
            and receipt.reason_code not in {"backend_failed", "backend_not_started"}
        ):
            raise RuntimeReceiptStoreError("backend receipt reason mismatch")
        if (
            receipt.dispatch_status == "indeterminate"
            and receipt.reason_code != "backend_result_lost"
        ):
            raise RuntimeReceiptStoreError("backend receipt reason mismatch")

    def _ensure_layout(self) -> None:
        expected = self.project_root / STORE_ROOT
        for path in (
            self.project_root / "runtime_state",
            expected,
            expected / "objects",
            expected / "receipt-ids",
            expected / "intent-ids",
        ):
            if path.exists() and self._is_reparse(path):
                raise RuntimeReceiptStoreError(
                    "runtime receipt store reparse redirection is forbidden"
                )
        try:
            self.objects_root.mkdir(parents=True, exist_ok=True)
            self.receipt_ids_root.mkdir(parents=True, exist_ok=True)
            self.intent_ids_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt store layout is unavailable: {exc}"
            ) from exc
        for path in (
            self.root,
            self.objects_root,
            self.receipt_ids_root,
            self.intent_ids_root,
        ):
            if not path.is_dir() or self._is_reparse(path):
                raise RuntimeReceiptStoreError("runtime receipt store layout is invalid")
            try:
                path.resolve().relative_to(self.project_root)
            except ValueError as exc:
                raise RuntimeReceiptStoreError(
                    "runtime receipt store redirection resolves outside project root"
                ) from exc

    def _object_path(self, digest: str) -> Path:
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise RuntimeReceiptStoreError("invalid runtime receipt object checksum")
        self._ensure_layout()
        path = self.objects_root / f"{digest}.json"
        self._assert_direct_child(path, self.objects_root)
        return path

    def _pointer_path(self, receipt_id: str) -> Path:
        if not isinstance(receipt_id, str) or not receipt_id:
            raise RuntimeReceiptStoreError("receipt_id is required")
        self._ensure_layout()
        identity_hash = hashlib.sha256(receipt_id.encode("utf-8")).hexdigest()
        path = self.receipt_ids_root / f"{identity_hash}.json"
        self._assert_direct_child(path, self.receipt_ids_root)
        return path

    def _intent_pointer_path(
        self,
        *,
        session_id: str,
        observation_id: str,
        intent_id: str,
    ) -> Path:
        identity = {
            "session_id": session_id,
            "observation_id": observation_id,
            "intent_id": intent_id,
        }
        if any(not isinstance(value, str) or not value for value in identity.values()):
            raise RuntimeReceiptStoreError(
                "runtime receipt intent identity is invalid"
            )
        self._ensure_layout()
        identity_hash = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
        path = self.intent_ids_root / f"{identity_hash}.json"
        self._assert_direct_child(path, self.intent_ids_root)
        return path

    def _assert_direct_child(self, path: Path, parent: Path) -> None:
        if path.parent != parent or self._is_reparse(path):
            raise RuntimeReceiptStoreError("runtime receipt store path escape")

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt store path is unavailable: {exc}"
            ) from exc
        return stat.S_ISLNK(status.st_mode) or bool(
            getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
        )

    def _publish_bytes(self, target: Path, contents: bytes) -> bool:
        self._ensure_layout()
        self._assert_direct_child(target, target.parent)
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            self._write_temp(temporary, contents)
            return self._publish_temp(temporary, target, contents)
        except _PublishedBytesConflict:
            raise
        except (OSError, RuntimeReceiptStoreError) as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt store write failed: {target}: {exc}"
            ) from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _write_temp(self, path: Path, contents: bytes) -> None:
        self._assert_direct_child(path, path.parent)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())

    def _publish_temp(self, temporary: Path, target: Path, contents: bytes) -> bool:
        self._assert_direct_child(temporary, target.parent)
        self._assert_direct_child(target, target.parent)
        try:
            self._durable_publish_no_replace(temporary, target)
        except FileExistsError:
            if self._read_bytes(target) != contents:
                raise _PublishedBytesConflict("published bytes conflict")
            return False
        return True

    @staticmethod
    def _durable_publish_no_replace(temporary: Path, target: Path) -> None:
        if _IS_WINDOWS:
            _publish_windows_no_replace_write_through(temporary, target)
        else:
            _publish_posix_no_replace_durable(temporary, target)

    def _read_bytes(self, path: Path) -> bytes:
        self._assert_direct_child(path, path.parent)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt store object is unreadable: {path}: {exc}"
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
            raise RuntimeReceiptStoreError(f"invalid {label} JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeReceiptStoreError(f"invalid {label} value")
        if _canonical_json_bytes(value) != raw:
            raise RuntimeReceiptStoreError(f"noncanonical {label} bytes")
        return raw, value


__all__ = [
    "RuntimeReceiptRecord",
    "RuntimeReceiptStore",
    "RuntimeReceiptStoreError",
]
