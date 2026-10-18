"""显式学习会话的当前 PNG 只读证据固化。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Iterator, Mapping
from uuid import uuid4

from PIL import Image

from app.agent.action_learning_recorder import (
    ActionLearningRecorder,
    ActionLearningRecorderError,
)
from app.agent.reviewed_workflow_asset import _atomic_write, _exclusive_file_lock


CONTRACT_VERSION = "action_learning_capture_v1"
FRESH_CONTRACT_VERSION = "action_learning_capture_v2"
STORE_ROOT = Path("runtime_state/action-learning-v1/captures")
DEFAULT_MAX_PNG_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_TOTAL_PNG_BYTES = 512 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_METADATA_KEYS = {
    "contract_version",
    "learning_session_id",
    "runtime_session_id",
    "capture_id",
    "screenshot_sha256",
    "png_size",
    "viewport_size",
    "asset_content_sha256",
    "target_window_handle",
    "target_process_id",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_REPARSE_POINT = 0x400


class ActionLearningCaptureArchiveError(ValueError):
    """截图身份、容量、完整性或持久化错误。"""


@dataclass(frozen=True, slots=True)
class ActionLearningSessionEvidence:
    evidence_json: bytes
    png_by_sha256: tuple[tuple[str, bytes], ...]

    def evidence(self) -> dict[str, Any]:
        """每次返回独立映射，不暴露内部可变引用。"""

        try:
            value = json.loads(self.evidence_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:  # pragma: no cover
            raise ActionLearningCaptureArchiveError(
                "session evidence bytes are corrupt"
            ) from error
        if not isinstance(value, dict):  # pragma: no cover
            raise ActionLearningCaptureArchiveError(
                "session evidence bytes are invalid"
            )
        return value


class ActionLearningCaptureArchive:
    """把已校验的当前截图原字节固化到 recorder 所属根目录。"""

    def __init__(
        self,
        *,
        recorder: ActionLearningRecorder,
        max_png_bytes: int = DEFAULT_MAX_PNG_BYTES,
        max_total_png_bytes: int = DEFAULT_MAX_TOTAL_PNG_BYTES,
    ) -> None:
        if not isinstance(recorder, ActionLearningRecorder):
            raise TypeError("recorder must be ActionLearningRecorder")
        if (
            isinstance(max_png_bytes, bool)
            or not isinstance(max_png_bytes, int)
            or max_png_bytes < 1
            or isinstance(max_total_png_bytes, bool)
            or not isinstance(max_total_png_bytes, int)
            or max_total_png_bytes < 1
        ):
            raise ValueError("capture archive limits must be positive integers")
        self.recorder = recorder
        self.project_root = recorder.project_root
        self.root = self.project_root / STORE_ROOT
        self.blobs_root = self.root / "blobs"
        self.records_root = self.root / "records"
        self.lock_path = self.root / ".archive.lock"
        self.max_png_bytes = max_png_bytes
        self.max_total_png_bytes = max_total_png_bytes

    def pin_current_capture(
        self,
        *,
        runtime_session_id: str,
        capture_id: str,
        screenshot_sha256: str,
        viewport_size: Mapping[str, Any],
        asset_content_sha256: str | None = None,
        fresh_source_sha256: str | None = None,
        target_window_handle: int,
        target_process_id: int,
        png_bytes: bytes,
    ) -> dict[str, Any] | None:
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        learning_id = self.recorder.get_active_learning_binding(
            runtime_session_id=runtime_id,
        )
        if learning_id is None:
            return None
        capture = _require_id(capture_id, "capture_id")
        screenshot_digest = _require_sha256(
            screenshot_sha256, "screenshot_sha256",
        )
        if (asset_content_sha256 is None) == (fresh_source_sha256 is None):
            raise ActionLearningCaptureArchiveError("capture requires exactly one source family")
        source_fields = (
            {"asset_content_sha256": _require_sha256(asset_content_sha256, "asset_content_sha256")}
            if fresh_source_sha256 is None else
            {"source_lineage": {"source_kind": "fresh_learning", "source_sha256":
                _require_sha256(fresh_source_sha256, "source_sha256")}}
        )
        viewport = _validate_viewport(viewport_size)
        window_handle = _positive_int(target_window_handle, "target_window_handle")
        process_id = _positive_int(target_process_id, "target_process_id")
        if not isinstance(png_bytes, bytes) or not png_bytes:
            raise ActionLearningCaptureArchiveError("png_bytes must be nonempty bytes")
        if len(png_bytes) > self.max_png_bytes:
            raise ActionLearningCaptureArchiveError("PNG exceeds per-capture quota")
        if sha256(png_bytes).hexdigest() != screenshot_digest:
            raise ActionLearningCaptureArchiveError("screenshot SHA-256 does not match PNG bytes")
        if _png_dimensions(png_bytes) != (viewport["width"], viewport["height"]):
            raise ActionLearningCaptureArchiveError("PNG dimensions do not match viewport_size")

        metadata = _metadata(
            learning_session_id=learning_id,
            runtime_session_id=runtime_id,
            capture_id=capture,
            screenshot_sha256=screenshot_digest,
            png_size=len(png_bytes),
            viewport_size=viewport,
            **source_fields,
            target_window_handle=window_handle,
            target_process_id=process_id,
        )
        with self._archive_gate(create=True):
            current_binding = self.recorder.get_active_learning_binding(
                runtime_session_id=runtime_id,
            )
            if current_binding != learning_id:
                raise ActionLearningCaptureArchiveError(
                    "learning binding changed before capture commit"
                )
            record_path = self._record_path(learning_id, runtime_id, capture)
            blob_path = self._blob_path(screenshot_digest)
            if record_path.exists():
                existing = self._load_metadata(record_path)
                if existing != metadata:
                    raise ActionLearningCaptureArchiveError(
                        "capture identity conflict"
                    )
                self._read_verified_blob(blob_path, existing)
                return deepcopy(existing)
            if blob_path.exists():
                self._read_verified_blob(blob_path, metadata)
            else:
                total = self._stored_png_bytes()
                if total + len(png_bytes) > self.max_total_png_bytes:
                    raise ActionLearningCaptureArchiveError(
                        "capture archive total quota exceeded"
                    )
                self._publish_new(blob_path, png_bytes, "capture blob")
            self._publish_new(
                record_path, _canonical_bytes(metadata), "capture metadata",
            )
            return deepcopy(metadata)

    def read_capture(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        capture_id: str,
        screenshot_sha256: str,
    ) -> bytes:
        learning_id = _require_id(learning_session_id, "learning_session_id")
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        capture = _require_id(capture_id, "capture_id")
        digest = _require_sha256(screenshot_sha256, "screenshot_sha256")
        try:
            session = self.recorder.get_learning_session(
                learning_session_id=learning_id,
            )
        except ActionLearningRecorderError as error:
            raise ActionLearningCaptureArchiveError(
                "learning capture session is unavailable or corrupt"
            ) from error
        if session.get("runtime_session_id") != runtime_id:
            raise ActionLearningCaptureArchiveError(
                "learning capture session scope does not match"
            )
        _, payload = self._read_join_capture(
            learning_session_id=learning_id,
            runtime_session_id=runtime_id,
            capture_id=capture,
            screenshot_sha256=digest,
            asset_content_sha256=None,
            target_window_handle=None,
            target_process_id=None,
            viewport_size=None,
        )
        return payload

    def read_session_evidence(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        expected_revision: int,
    ) -> ActionLearningSessionEvidence:
        learning_id = _require_id(learning_session_id, "learning_session_id")
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        revision = _positive_int(expected_revision, "expected_revision")
        initial_sources = self._read_authoritative_sources(
            learning_session_id=learning_id,
            runtime_session_id=runtime_id,
            expected_revision=revision,
        )
        initial = initial_sources["session"]
        before_sources = initial_sources["before_sources"]

        events = initial.get("events")
        gaps = initial.get("recording_gaps")
        if not isinstance(events, Mapping) or not isinstance(gaps, list):
            raise ActionLearningCaptureArchiveError(
                "authoritative learning session view is malformed"
            )
        sources: list[dict[str, Any]] = []
        pngs: dict[str, bytes] = {}
        incomplete = bool(gaps)
        for event_id in sorted(events):
            event = events[event_id]
            before = event["before"]
            before_capture = before["capture"]
            geometry = before["geometry"]
            is_fresh = before.get("contract_version") == "action_learning_before_v2"
            source_args = (
                {"asset_content_sha256": None, "fresh_source_sha256":
                 _require_sha256(before["source_lineage"]["source_sha256"], "event source_sha256")}
                if is_fresh else {"asset_content_sha256": _require_sha256(
                    before["workflow"]["asset_content_sha256"], "event asset_content_sha256")}
            )
            window_handle = _positive_int(
                geometry["target_window_handle"], "event target_window_handle",
            )
            process_id = _positive_int(
                geometry["target_process_id"], "event target_process_id",
            )
            viewport = _validate_viewport(geometry["viewport_size"])
            before_source = before_sources[event_id]
            if before_source["status"] != "verified":
                before_ref = self._unavailable_source_ref(
                    before_capture, reason="before_source_unverified",
                )
                before_payload = None
            else:
                before_ref, before_payload = self._join_source_ref(
                    learning_session_id=learning_id,
                    runtime_session_id=runtime_id,
                    capture=before_capture,
                    **source_args,
                    target_window_handle=window_handle,
                    target_process_id=process_id,
                    viewport_size=viewport,
                )
            if before_payload is None:
                incomplete = True
            else:
                pngs[before_ref["screenshot_sha256"]] = before_payload

            after_capture = event["terminal"]["next_observation_ref"]
            after_present = after_capture is not None
            after_ref = None
            if after_present:
                after_ref, after_payload = self._join_source_ref(
                    learning_session_id=learning_id,
                    runtime_session_id=runtime_id,
                    capture=after_capture,
                    **source_args,
                    target_window_handle=window_handle,
                    target_process_id=process_id,
                    viewport_size=None,
                )
                if after_payload is None:
                    incomplete = True
                else:
                    pngs[after_ref["screenshot_sha256"]] = after_payload
            sources.append({
                "event_id": event_id,
                "before": before_ref,
                "after_observation_present": after_present,
                "after": after_ref,
            })

        try:
            final_sources = self._read_authoritative_sources(
                learning_session_id=learning_id,
                runtime_session_id=runtime_id,
                expected_revision=revision,
            )
        except ActionLearningCaptureArchiveError as error:
            raise ActionLearningCaptureArchiveError(
                "learning session source snapshot changed; retry required"
            ) from error
        if final_sources != initial_sources:
            raise ActionLearningCaptureArchiveError(
                "learning session changed during evidence read; retry required"
            )
        source_status = (
            "empty" if not events and not gaps
            else "incomplete" if incomplete
            else "complete"
        )
        evidence = {
            "contract_version": "action_learning_session_evidence_v1",
            "learning_session_id": learning_id,
            "runtime_session_id": runtime_id,
            "revision": revision,
            "recording_status": initial["status"],
            "events": deepcopy(dict(events)),
            "event_sources": sources,
            "recording_gaps": deepcopy(gaps),
            "source_status": source_status,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }
        return ActionLearningSessionEvidence(
            evidence_json=_canonical_bytes(evidence),
            png_by_sha256=tuple(
                (digest, bytes(pngs[digest])) for digest in sorted(pngs)
            ),
        )

    def _read_authoritative_sources(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        try:
            snapshot = self.recorder.read_learning_session_sources(
                learning_session_id=learning_session_id,
                runtime_session_id=runtime_session_id,
                expected_revision=expected_revision,
            )
        except ActionLearningRecorderError as error:
            raise ActionLearningCaptureArchiveError(
                "authoritative learning session is unavailable or corrupt"
            ) from error
        if not isinstance(snapshot, Mapping) or set(snapshot) != {
            "contract_version",
            "session",
            "before_sources",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "action_executed",
        }:
            raise ActionLearningCaptureArchiveError(
                "authoritative learning source snapshot is malformed"
            )
        session = snapshot.get("session")
        sources = snapshot.get("before_sources")
        if (
            snapshot.get("contract_version")
            != "action_learning_session_sources_v1"
            or snapshot.get("artifact_is_authorization") is not False
            or snapshot.get("execute_binding_enabled") is not False
            or snapshot.get("action_executed") is not False
            or not isinstance(session, Mapping)
            or not isinstance(sources, Mapping)
            or session.get("learning_session_id") != learning_session_id
            or session.get("runtime_session_id") != runtime_session_id
            or session.get("revision") != expected_revision
            or not isinstance(session.get("events"), Mapping)
            or set(sources) != set(session["events"])
        ):
            raise ActionLearningCaptureArchiveError(
                "authoritative learning source snapshot is malformed"
            )
        for source in sources.values():
            if not isinstance(source, Mapping) or set(source) != {
                "status", "reason", "checkpoint_sha256",
            }:
                raise ActionLearningCaptureArchiveError(
                    "authoritative before source status is malformed"
                )
            if source.get("status") == "verified":
                if source.get("reason") is not None:
                    raise ActionLearningCaptureArchiveError(
                        "authoritative before source status is malformed"
                    )
                _require_sha256(
                    source.get("checkpoint_sha256"), "checkpoint_sha256",
                )
            elif (
                source.get("status") != "unavailable"
                or source.get("reason") != "verification_checkpoint_unavailable"
                or source.get("checkpoint_sha256") is not None
            ):
                raise ActionLearningCaptureArchiveError(
                    "authoritative before source status is malformed"
                )
        return deepcopy(dict(snapshot))

    @staticmethod
    def _unavailable_source_ref(
        capture: Mapping[str, Any], *, reason: str,
    ) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "reason": reason,
            "capture_id": _require_id(capture.get("capture_id"), "capture_id"),
            "screenshot_sha256": _require_sha256(
                capture.get("screenshot_sha256"), "screenshot_sha256",
            ),
        }

    def _join_source_ref(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        capture: Mapping[str, Any],
        asset_content_sha256: str | None,
        fresh_source_sha256: str | None = None,
        target_window_handle: int,
        target_process_id: int,
        viewport_size: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], bytes | None]:
        capture_id = _require_id(capture.get("capture_id"), "capture_id")
        digest = _require_sha256(
            capture.get("screenshot_sha256"), "screenshot_sha256",
        )
        unavailable = self._unavailable_source_ref(
            capture, reason="archive_source_unavailable",
        )
        try:
            metadata, payload = self._read_join_capture(
                learning_session_id=learning_session_id,
                runtime_session_id=runtime_session_id,
                capture_id=capture_id,
                screenshot_sha256=digest,
                asset_content_sha256=asset_content_sha256,
                fresh_source_sha256=fresh_source_sha256,
                target_window_handle=target_window_handle,
                target_process_id=target_process_id,
                viewport_size=viewport_size,
            )
        except ActionLearningCaptureArchiveError:
            return unavailable, None
        return {
            "status": "available",
            "capture_id": capture_id,
            "screenshot_sha256": digest,
            "metadata": metadata,
        }, payload

    def _read_join_capture(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        capture_id: str,
        screenshot_sha256: str,
        asset_content_sha256: str | None,
        fresh_source_sha256: str | None = None,
        target_window_handle: int | None,
        target_process_id: int | None,
        viewport_size: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], bytes]:
        with self._archive_gate(create=False):
            record_path = self._record_path(
                learning_session_id, runtime_session_id, capture_id,
            )
            metadata = self._load_metadata(record_path)
            if (
                metadata["learning_session_id"] != learning_session_id
                or metadata["runtime_session_id"] != runtime_session_id
                or metadata["capture_id"] != capture_id
                or metadata["screenshot_sha256"] != screenshot_sha256
                or (
                    asset_content_sha256 is not None
                    and metadata.get("asset_content_sha256") != asset_content_sha256
                )
                or (
                    fresh_source_sha256 is not None
                    and metadata.get("source_lineage") != {
                        "source_kind": "fresh_learning", "source_sha256": fresh_source_sha256}
                )
                or (
                    target_window_handle is not None
                    and metadata["target_window_handle"] != target_window_handle
                )
                or (
                    target_process_id is not None
                    and metadata["target_process_id"] != target_process_id
                )
                or (
                    viewport_size is not None
                    and metadata["viewport_size"] != dict(viewport_size)
                )
            ):
                raise ActionLearningCaptureArchiveError(
                    "learning capture identity does not match"
                )
            payload = self._read_verified_blob(
                self._blob_path(screenshot_sha256), metadata,
            )
            return deepcopy(metadata), bytes(payload)

    @contextmanager
    def _archive_gate(self, *, create: bool) -> Iterator[None]:
        self._ensure_layout(create=create)
        if self._is_reparse(self.lock_path):
            raise ActionLearningCaptureArchiveError("capture archive lock reparse is forbidden")
        if not create and not self.lock_path.is_file():
            raise ActionLearningCaptureArchiveError(
                "capture archive lock is unavailable"
            )
        try:
            with _exclusive_file_lock(self.lock_path):
                self._ensure_layout(create=False)
                if self._is_reparse(self.lock_path):
                    raise ActionLearningCaptureArchiveError(
                        "capture archive lock reparse is forbidden"
                    )
                yield
        except ActionLearningCaptureArchiveError:
            raise
        except (OSError, TimeoutError) as error:
            raise ActionLearningCaptureArchiveError(
                "capture archive lock is unavailable"
            ) from error

    def _ensure_layout(self, *, create: bool) -> None:
        paths = (
            self.project_root / "runtime_state",
            self.project_root / "runtime_state/action-learning-v1",
            self.root,
            self.blobs_root,
            self.records_root,
        )
        for path in paths:
            if path.exists() and self._is_reparse(path):
                raise ActionLearningCaptureArchiveError(
                    "capture archive reparse redirection is forbidden"
                )
        if create:
            try:
                self.blobs_root.mkdir(parents=True, exist_ok=True)
                self.records_root.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise ActionLearningCaptureArchiveError(
                    "capture archive layout is unavailable"
                ) from error
        for path in (self.root, self.blobs_root, self.records_root):
            if not path.is_dir() or self._is_reparse(path):
                raise ActionLearningCaptureArchiveError(
                    "capture archive layout is unavailable or corrupt"
                )
            try:
                path.resolve().relative_to(self.project_root)
            except ValueError as error:
                raise ActionLearningCaptureArchiveError(
                    "capture archive resolves outside project root"
                ) from error

    def _record_path(self, learning_id: str, runtime_id: str, capture_id: str) -> Path:
        identity = _canonical_bytes(
            {
                "learning_session_id": learning_id,
                "runtime_session_id": runtime_id,
                "capture_id": capture_id,
            }
        )
        path = self.records_root / f"{sha256(identity).hexdigest()}.json"
        self._assert_direct_child(path, self.records_root)
        return path

    def _blob_path(self, digest: str) -> Path:
        path = self.blobs_root / f"{_require_sha256(digest, 'screenshot_sha256')}.png"
        self._assert_direct_child(path, self.blobs_root)
        return path

    def _load_metadata(self, path: Path) -> dict[str, Any]:
        self._assert_direct_child(path, self.records_root)
        if not path.is_file() or self._is_reparse(path):
            raise ActionLearningCaptureArchiveError(
                "capture metadata is missing or corrupt"
            )
        try:
            raw = path.read_bytes()
            decoded = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ActionLearningCaptureArchiveError("capture metadata is corrupt") from error
        if not isinstance(decoded, dict) or _canonical_bytes(decoded) != raw:
            raise ActionLearningCaptureArchiveError("capture metadata is corrupt")
        _validate_metadata(decoded)
        return decoded

    def _read_verified_blob(self, path: Path, metadata: Mapping[str, Any]) -> bytes:
        self._assert_direct_child(path, self.blobs_root)
        if not path.is_file() or self._is_reparse(path):
            raise ActionLearningCaptureArchiveError("capture blob is missing or corrupt")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise ActionLearningCaptureArchiveError("capture blob is corrupt") from error
        if (
            len(payload) != metadata["png_size"]
            or sha256(payload).hexdigest() != metadata["screenshot_sha256"]
            or _png_dimensions(payload)
            != (
                metadata["viewport_size"]["width"],
                metadata["viewport_size"]["height"],
            )
        ):
            raise ActionLearningCaptureArchiveError("capture blob is corrupt")
        return payload

    def _stored_png_bytes(self) -> int:
        total = 0
        try:
            paths = list(self.blobs_root.iterdir())
        except OSError as error:
            raise ActionLearningCaptureArchiveError("capture quota is unavailable") from error
        for path in paths:
            if path.suffix != ".png" or not path.is_file() or self._is_reparse(path):
                raise ActionLearningCaptureArchiveError(
                    "capture blob collection is corrupt"
                )
            self._assert_direct_child(path, self.blobs_root)
            total += path.stat().st_size
        return total

    def _publish_new(self, path: Path, payload: bytes, label: str) -> None:
        self._assert_direct_child(path, path.parent)
        if path.exists():
            raise ActionLearningCaptureArchiveError(f"{label} identity conflict")
        temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        self._assert_direct_child(temporary, path.parent)
        try:
            _atomic_write(temporary, payload)
            if path.exists():
                raise ActionLearningCaptureArchiveError(f"{label} identity conflict")
            temporary.replace(path)
        except ActionLearningCaptureArchiveError:
            raise
        except OSError as error:
            raise ActionLearningCaptureArchiveError(f"{label} persistence failed") from error
        finally:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass

    def _assert_direct_child(self, path: Path, parent: Path) -> None:
        if path.parent != parent or self._is_reparse(path):
            raise ActionLearningCaptureArchiveError("capture archive path escape")

    @staticmethod
    def _is_reparse(path: Path) -> bool:
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ActionLearningCaptureArchiveError(
                "capture archive path is unavailable"
            ) from error
        return stat.S_ISLNK(status.st_mode) or bool(
            getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
        )


def _metadata(**values: Any) -> dict[str, Any]:
    payload = {
        "contract_version": FRESH_CONTRACT_VERSION if "source_lineage" in values else CONTRACT_VERSION,
        **deepcopy(values),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return {**payload, "content_sha256": sha256(_canonical_bytes(payload)).hexdigest()}


def _validate_metadata(value: Mapping[str, Any]) -> None:
    fresh = value.get("contract_version") == FRESH_CONTRACT_VERSION
    keys = (_METADATA_KEYS - {"asset_content_sha256"}) | {"source_lineage"} if fresh else _METADATA_KEYS
    if set(value) != keys or value.get("contract_version") not in {CONTRACT_VERSION, FRESH_CONTRACT_VERSION}:
        raise ActionLearningCaptureArchiveError("capture metadata is corrupt")
    if fresh:
        lineage = value.get("source_lineage")
        if (not isinstance(lineage, dict) or set(lineage) != {"source_kind", "source_sha256"}
                or lineage["source_kind"] != "fresh_learning"):
            raise ActionLearningCaptureArchiveError("capture fresh source lineage is invalid")
        _require_sha256(lineage.get("source_sha256"), "source_sha256")
    else:
        _require_sha256(value.get("asset_content_sha256"), "asset_content_sha256")
    for field in ("learning_session_id", "runtime_session_id", "capture_id"):
        _require_id(value.get(field), field)
    for field in ("screenshot_sha256", "content_sha256"):
        _require_sha256(value.get(field), field)
    _positive_int(value.get("png_size"), "png_size")
    _validate_viewport(value.get("viewport_size"))
    _positive_int(value.get("target_window_handle"), "target_window_handle")
    _positive_int(value.get("target_process_id"), "target_process_id")
    if (
        value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise ActionLearningCaptureArchiveError("capture metadata grants forbidden authority")
    payload = dict(value)
    digest = payload.pop("content_sha256")
    if sha256(_canonical_bytes(payload)).hexdigest() != digest:
        raise ActionLearningCaptureArchiveError("capture metadata is corrupt")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ActionLearningCaptureArchiveError(
            "capture metadata serialization failed"
        ) from error


def _require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ActionLearningCaptureArchiveError(f"{label} is invalid")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ActionLearningCaptureArchiveError(f"{label} is invalid")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ActionLearningCaptureArchiveError(f"{label} is invalid")
    return value


def _validate_viewport(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"width", "height"}:
        raise ActionLearningCaptureArchiveError("viewport_size is invalid")
    return {
        "width": _positive_int(value.get("width"), "viewport width"),
        "height": _positive_int(value.get("height"), "viewport height"),
    }


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.verify()
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG":
                raise ValueError("not PNG")
            return int(image.width), int(image.height)
    except Exception as error:
        raise ActionLearningCaptureArchiveError("PNG bytes are unreadable or corrupt") from error


__all__ = [
    "ActionLearningCaptureArchive",
    "ActionLearningCaptureArchiveError",
    "ActionLearningSessionEvidence",
    "DEFAULT_MAX_PNG_BYTES",
    "DEFAULT_MAX_TOTAL_PNG_BYTES",
    "STORE_ROOT",
]
