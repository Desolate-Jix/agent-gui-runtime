"""Append-only, content-addressed storage for sealed UEI v1 objects."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
from threading import RLock
from uuid import uuid4

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, seal_immutable
from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ID_FIELDS = {
    "trusted_provider_registration_v1": "registration_id",
    "artifact_ref_v1": "artifact_id",
    "capture_lineage_v1": "capture_id",
    "affine_coordinate_transform_v1": None,
    "provider_manifest_v1": "manifest_id",
    "screen_parse_request_v1": "request_id",
    "provider_safe_result_v1": "result_id",
    "provider_error_v1": "error_id",
    "provider_runtime_receipt_v1": "receipt_id",
    "hybrid_capture_context_v1": "context_id",
    "hybrid_capture_bundle_v1": "bundle_id",
    "hybrid_review_projection_v1": "projection_id",
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)


class UEIObjectStore:
    """Store verified UEI objects as immutable canonical JSON files."""

    def __init__(self, *, root: Path) -> None:
        if not isinstance(root, Path):
            raise UEIValidationError("store_root_must_be_path")
        self.root = root.absolute()
        self._lock = RLock()
        try:
            self._reject_reparse_ancestors(self.root)
            self.root.mkdir(parents=True, exist_ok=True)
            self._ensure_root()
        except OSError as error:
            raise UEIValidationError("store_root_unavailable") from error
        self._write_order: tuple[str, ...] = ()

    @property
    def write_order(self) -> tuple[str, ...]:
        """Return an immutable snapshot of this store instance's new writes."""
        with self._lock:
            return self._write_order

    def put(self, value: dict[str, object]) -> dict[str, str]:
        """Validate, seal, and atomically append one object without replacement."""
        if not isinstance(value, dict):
            raise UEIValidationError("store_value_not_object")
        candidate = deepcopy(value)
        contract_version = self._contract_version(candidate)
        validate_contract(candidate, contract_version=contract_version)
        declared_hash = candidate.get("content_sha256")
        if not isinstance(declared_hash, str) or declared_hash != content_sha256(candidate):
            raise UEIValidationError("store_content_sha256_mismatch")
        sealed = seal_immutable(candidate)
        canonical = canonical_json_bytes(sealed)
        digest = sealed["content_sha256"]
        assert isinstance(digest, str)

        with self._lock:
            self._ensure_root()
            target = self._object_path(digest)
            temporary = self.root / f".{digest}.{uuid4().hex}.tmp"
            try:
                self._write_temp(temporary, canonical)
                created = self._publish_temp(temporary, target, canonical)
            except UEIValidationError:
                raise
            except OSError as error:
                raise UEIValidationError("store_object_write_failed") from error
            finally:
                self._cleanup_temp(temporary)
            if created:
                self._write_order = (*self._write_order, contract_version)

        return {"id": self._stable_id(sealed, contract_version), "content_sha256": digest}

    def get(self, ref: dict[str, str], *, contract_version: str) -> dict[str, object]:
        """Read and reverify the exact immutable object selected by *ref*."""
        self._require_contract_version(contract_version)
        reference = self._validate_ref(ref)
        with self._lock:
            self._ensure_root()
            raw = self._read_existing(self._object_path(reference["content_sha256"]))
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise UEIValidationError("store_invalid_json") from error
        if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
            raise UEIValidationError("store_noncanonical_bytes")
        if value.get("content_sha256") != reference["content_sha256"]:
            raise UEIValidationError("store_content_sha256_mismatch")
        if content_sha256(value) != reference["content_sha256"]:
            raise UEIValidationError("store_content_sha256_mismatch")
        if value.get("contract_version") != contract_version:
            raise UEIValidationError("store_contract_version_mismatch")
        validate_contract(value, contract_version=contract_version)
        if self._stable_id(value, contract_version) != reference["id"]:
            raise UEIValidationError("store_stable_id_mismatch")
        return deepcopy(value)

    def object_count(self, *, contract_version: str) -> int:
        """Count verified objects for one contract without accepting corrupt files."""
        self._require_contract_version(contract_version)
        with self._lock:
            self._ensure_root()
            paths = tuple(self.root.glob("*.json"))
        count = 0
        for path in paths:
            if path.is_symlink():
                raise UEIValidationError("store_symlink_object")
            raw = self._read_existing(path)
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise UEIValidationError("store_invalid_json") from error
            if not isinstance(value, dict):
                raise UEIValidationError("store_value_not_object")
            stored_contract = self._contract_version(value)
            digest = value.get("content_sha256")
            if not isinstance(digest, str) or path.name != f"{digest}.json":
                raise UEIValidationError("store_content_sha256_mismatch")
            self.get({"id": self._stable_id(value, stored_contract), "content_sha256": digest}, contract_version=stored_contract)
            if stored_contract == contract_version:
                count += 1
        return count

    def _require_contract_version(self, contract_version: object) -> str:
        if not isinstance(contract_version, str) or contract_version not in _ID_FIELDS:
            raise UEIValidationError("store_unknown_contract_version")
        return contract_version

    def _contract_version(self, value: dict[str, object]) -> str:
        return self._require_contract_version(value.get("contract_version"))

    def _stable_id(self, value: dict[str, object], contract_version: str) -> str:
        id_field = _ID_FIELDS[contract_version]
        identifier = value.get("content_sha256") if id_field is None else value.get(id_field)
        if not isinstance(identifier, str) or not identifier:
            raise UEIValidationError("store_invalid_stable_id")
        return identifier

    def _validate_ref(self, ref: dict[str, str]) -> dict[str, str]:
        if not isinstance(ref, dict) or set(ref) != {"id", "content_sha256"}:
            raise UEIValidationError("store_invalid_immutable_ref")
        identifier = ref["id"]
        digest = ref["content_sha256"]
        if not isinstance(identifier, str) or not identifier:
            raise UEIValidationError("store_invalid_immutable_ref")
        if not isinstance(digest, str) or _HASH_PATTERN.fullmatch(digest) is None:
            raise UEIValidationError("store_invalid_immutable_ref")
        return {"id": identifier, "content_sha256": digest}

    def _ensure_root(self) -> None:
        self._reject_reparse_ancestors(self.root)
        if not self.root.is_dir():
            raise UEIValidationError("store_root_not_directory")

    def _reject_reparse_ancestors(self, path: Path) -> None:
        current = path
        while True:
            try:
                status = os.lstat(current)
            except FileNotFoundError:
                current = current.parent
                continue
            except OSError as error:
                raise UEIValidationError("store_path_unavailable") from error
            if stat.S_ISLNK(status.st_mode) or bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT):
                raise UEIValidationError("store_reparse_path")
            if current == current.parent:
                return
            current = current.parent

    def _object_path(self, digest: str) -> Path:
        if _HASH_PATTERN.fullmatch(digest) is None:
            raise UEIValidationError("store_invalid_content_sha256")
        self._ensure_root()
        path = self.root / f"{digest}.json"
        if path.parent != self.root:
            raise UEIValidationError("store_path_escape")
        if path.exists() and self._is_reparse(path):
            raise UEIValidationError("store_symlink_object")
        return path

    def _is_reparse(self, path: Path) -> bool:
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise UEIValidationError("store_path_unavailable") from error
        return stat.S_ISLNK(status.st_mode) or bool(getattr(status, "st_file_attributes", 0) & _REPARSE_POINT)

    def _read_existing(self, path: Path) -> bytes:
        self._ensure_root()
        if self._is_reparse(path):
            raise UEIValidationError("store_symlink_object")
        try:
            return path.read_bytes()
        except OSError as error:
            raise UEIValidationError("store_object_unreadable") from error

    def _write_temp(self, path: Path, contents: bytes) -> None:
        self._ensure_root()
        if path.parent != self.root or self._is_reparse(path):
            raise UEIValidationError("store_path_escape")
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())

    def _publish_temp(self, temporary: Path, target: Path, contents: bytes) -> bool:
        self._ensure_root()
        if temporary.parent != self.root or target.parent != self.root:
            raise UEIValidationError("store_path_escape")
        if self._is_reparse(target):
            raise UEIValidationError("store_symlink_object")
        try:
            os.link(str(temporary), str(target))
        except FileExistsError:
            if self._read_existing(target) != contents:
                raise UEIValidationError("store_digest_bytes_conflict")
            return False
        except OSError as error:
            raise UEIValidationError("store_object_publish_failed") from error
        return True

    def _cleanup_temp(self, path: Path) -> None:
        try:
            if path.exists() or self._is_reparse(path):
                path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            raise UEIValidationError("store_temp_cleanup_failed") from error
