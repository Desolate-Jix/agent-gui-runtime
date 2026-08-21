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
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import uuid4

from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import RuntimeResultReceiptV1


STORE_CONTRACT_VERSION = "runtime_receipt_record_v1"
POINTER_CONTRACT_VERSION = "runtime_receipt_pointer_v1"
STORE_ROOT = Path("runtime_state/runtime-receipts-v1")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_IS_WINDOWS = os.name == "nt"


class RuntimeReceiptStoreError(ValueError):
    """Receipt 持久化、完整性或身份校验失败。"""


class _PublishedBytesConflict(RuntimeReceiptStoreError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeReceiptRecord:
    runtime_receipt: RuntimeResultReceiptV1
    backend_receipt: BackendDispatchReceipt | None
    content_sha256: str


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
        self._ensure_layout()

    def put(
        self,
        receipt: RuntimeResultReceiptV1 | Mapping[str, object],
        *,
        backend_receipt: BackendDispatchReceipt | None = None,
    ) -> dict[str, str]:
        """验证并不可变发布一个 Receipt record。"""

        validated = self._validate_runtime_receipt(receipt)
        if backend_receipt is not None and not isinstance(
            backend_receipt, BackendDispatchReceipt
        ):
            raise RuntimeReceiptStoreError("invalid backend receipt object")
        self._validate_backend_pairing(validated, backend_receipt)
        envelope = {
            "store_contract_version": STORE_CONTRACT_VERSION,
            "runtime_receipt": validated.model_dump(mode="json"),
            "backend_receipt": (
                asdict(backend_receipt) if backend_receipt is not None else None
            ),
        }
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
        return self._get_object(receipt_id=receipt_id, digest=digest)

    def _get_object(self, *, receipt_id: str, digest: str) -> RuntimeReceiptRecord:
        """读取 CAS object；调用方必须先证明 receipt identity 已提交。"""

        object_path = self._object_path(digest)
        raw, envelope = self._read_canonical_json(object_path, label="receipt object")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeReceiptStoreError("runtime receipt object checksum mismatch")
        if set(envelope) != {
            "store_contract_version",
            "runtime_receipt",
            "backend_receipt",
        } or envelope.get("store_contract_version") != STORE_CONTRACT_VERSION:
            raise RuntimeReceiptStoreError("invalid runtime receipt record contract")
        runtime_payload = envelope.get("runtime_receipt")
        if not isinstance(runtime_payload, Mapping):
            raise RuntimeReceiptStoreError("runtime receipt record payload is invalid")
        runtime_receipt = self._validate_runtime_receipt(runtime_payload)
        if runtime_receipt.receipt_id != receipt_id:
            raise RuntimeReceiptStoreError("runtime receipt record identity mismatch")
        backend_receipt = self._validate_backend_payload(envelope.get("backend_receipt"))
        self._validate_backend_pairing(runtime_receipt, backend_receipt)
        return RuntimeReceiptRecord(
            runtime_receipt=runtime_receipt,
            backend_receipt=backend_receipt,
            content_sha256=digest,
        )

    def load_by_receipt_id(self, receipt_id: str) -> RuntimeReceiptRecord:
        """通过 Windows-safe hashed identity index 读取 Receipt。"""

        if not isinstance(receipt_id, str) or not receipt_id:
            raise RuntimeReceiptStoreError("receipt_id is required")
        digest = self._load_pointer_digest(receipt_id)
        return self._get_object(receipt_id=receipt_id, digest=digest)

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
        ):
            if path.exists() and self._is_reparse(path):
                raise RuntimeReceiptStoreError(
                    "runtime receipt store reparse redirection is forbidden"
                )
        try:
            self.objects_root.mkdir(parents=True, exist_ok=True)
            self.receipt_ids_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeReceiptStoreError(
                f"runtime receipt store layout is unavailable: {exc}"
            ) from exc
        for path in (self.root, self.objects_root, self.receipt_ids_root):
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
