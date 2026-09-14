"""首次学习观察的不可变本地来源归档。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, UnidentifiedImageError

from app.agent.fresh_learning_observation import FreshLearningObservationPacket
from app.agent.reviewed_workflow_asset import _atomic_write, _exclusive_file_lock


REFERENCE_CONTRACT_VERSION = "fresh_learning_source_ref_v1"
OBSERVATION_CONTRACT_VERSION = "fresh_learning_observation_v1"
DEFAULT_MAX_PNG_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024


class FreshLearningObservationArchiveError(ValueError):
    """首次学习来源不可持久化或不可验证。"""


class FreshLearningObservationArchive:
    """仅保存绑定范围的原始截图与首次观察证据。"""

    def __init__(
        self,
        project_root: str | Path,
        max_png_bytes: int = DEFAULT_MAX_PNG_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.max_png_bytes = _positive_limit(max_png_bytes, "max_png_bytes")
        self.max_total_bytes = _positive_limit(max_total_bytes, "max_total_bytes")
        if self.max_total_bytes < self.max_png_bytes:
            # 总额可以比单张小；record 时仍明确报告总额限制。
            pass
        self.root = self.project_root / "runtime_state" / "fresh-learning-v1"
        self.png_root = self.root / "png"
        self.records_root = self.root / "records"
        self.lock_path = self.root / ".archive.lock"

    def record(
        self,
        packet: FreshLearningObservationPacket,
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
    ) -> dict[str, str]:
        """保存一次不可变观察；同一内容和范围的重试复用来源。"""

        scope = _scope(connection_id, task_id, segment_id)
        evidence, png_size = _validate_packet(packet, max_png_bytes=self.max_png_bytes)
        screenshot_sha256 = evidence["capture"]["screenshot_sha256"]
        capture_id = evidence["capture"]["capture_id"]
        content_sha256 = sha256(
            _canonical_bytes({
                "evidence_json": packet.evidence_json.decode("utf-8"),
                "screenshot_sha256": screenshot_sha256,
            })
        ).hexdigest()
        source_id = sha256(_canonical_bytes({
            "scope": scope,
            "content_sha256": content_sha256,
            "capture_id": capture_id,
        })).hexdigest()
        reference = {
            "contract_version": REFERENCE_CONTRACT_VERSION,
            "source_id": source_id,
            "content_sha256": content_sha256,
            "capture_id": capture_id,
            "screenshot_sha256": screenshot_sha256,
        }
        envelope = {
            "contract_version": REFERENCE_CONTRACT_VERSION,
            "source_id": source_id,
            "content_sha256": content_sha256,
            "scope": scope,
            "capture_id": capture_id,
            "screenshot_sha256": screenshot_sha256,
            "png_size": png_size,
            "viewport_size": evidence["capture"]["viewport_size"],
            "evidence_json": packet.evidence_json.decode("utf-8"),
        }
        raw_envelope = _canonical_bytes(envelope)
        with self._gate(create=True):
            png_path = self.png_root / f"{screenshot_sha256}.png"
            record_path = self.records_root / f"{source_id}.json"
            if record_path.exists():
                if record_path.read_bytes() != raw_envelope:
                    raise FreshLearningObservationArchiveError("immutable source identity conflict")
                self._verified_png(png_path, envelope)
                return deepcopy(reference)
            png_is_new = not png_path.exists()
            if not png_is_new:
                self._verified_png(png_path, envelope)
            additional_bytes = len(raw_envelope) + (png_size if png_is_new else 0)
            if self._committed_payload_bytes() + additional_bytes > self.max_total_bytes:
                raise FreshLearningObservationArchiveError("total budget exceeded")
            if png_is_new:
                _atomic_write(png_path, packet.png_bytes)
            _atomic_write(record_path, raw_envelope)
        return deepcopy(reference)

    def read(
        self,
        reference: Mapping[str, Any],
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
    ) -> FreshLearningObservationPacket:
        """按同一连接、任务和段读取并重验原始来源。"""

        scope = _scope(connection_id, task_id, segment_id)
        checked_reference = _reference(reference)
        with self._gate(create=False):
            record_path = self.records_root / f"{checked_reference['source_id']}.json"
            envelope = self._load_envelope(record_path)
            if envelope["scope"] != scope:
                raise FreshLearningObservationArchiveError("source scope does not match")
            expected_reference = {
                key: envelope[key]
                for key in ("contract_version", "source_id", "content_sha256", "capture_id", "screenshot_sha256")
            }
            if checked_reference != expected_reference:
                raise FreshLearningObservationArchiveError("source reference does not match")
            png = self._verified_png(
                self.png_root / f"{envelope['screenshot_sha256']}.png", envelope,
            )
            packet = FreshLearningObservationPacket(
                png_bytes=png,
                evidence_json=envelope["evidence_json"].encode("utf-8"),
            )
            _validate_packet(packet, max_png_bytes=self.max_png_bytes)
            if sha256(_canonical_bytes({
                "evidence_json": envelope["evidence_json"],
                "screenshot_sha256": envelope["screenshot_sha256"],
            })).hexdigest() != envelope["content_sha256"]:
                raise FreshLearningObservationArchiveError("source record content is corrupt")
            return packet

    def _gate(self, *, create: bool):
        self._ensure_layout(create=create)
        return _exclusive_file_lock(self.lock_path)

    def _ensure_layout(self, *, create: bool) -> None:
        if create:
            self.png_root.mkdir(parents=True, exist_ok=True)
            self.records_root.mkdir(parents=True, exist_ok=True)
        for path in (self.root, self.png_root, self.records_root):
            if not path.is_dir():
                raise FreshLearningObservationArchiveError("archive layout is unavailable")
            try:
                path.resolve().relative_to(self.project_root)
            except ValueError as error:
                raise FreshLearningObservationArchiveError("archive path escapes project root") from error

    def _load_envelope(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise FreshLearningObservationArchiveError("source record is missing or corrupt")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FreshLearningObservationArchiveError("source record is corrupt") from error
        if not isinstance(value, dict) or _canonical_bytes(value) != raw:
            raise FreshLearningObservationArchiveError("source record is corrupt")
        required = {
            "contract_version", "source_id", "content_sha256", "scope", "capture_id",
            "screenshot_sha256", "png_size", "viewport_size", "evidence_json",
        }
        if set(value) != required or value["contract_version"] != REFERENCE_CONTRACT_VERSION:
            raise FreshLearningObservationArchiveError("source record is corrupt")
        _reference({key: value[key] for key in required - {"scope", "png_size", "viewport_size", "evidence_json"}})
        if (
            not isinstance(value["scope"], dict)
            or set(value["scope"]) != {"connection_id", "task_id", "segment_id"}
            or _scope(**value["scope"]) != value["scope"]
            or not isinstance(value["evidence_json"], str)
        ):
            raise FreshLearningObservationArchiveError("source record is corrupt")
        if not isinstance(value["png_size"], int) or value["png_size"] <= 0:
            raise FreshLearningObservationArchiveError("source record is corrupt")
        return value

    def _verified_png(self, path: Path, envelope: Mapping[str, Any]) -> bytes:
        if not path.is_file():
            raise FreshLearningObservationArchiveError("source PNG is missing or corrupt")
        try:
            payload = path.read_bytes()
        except OSError as error:
            raise FreshLearningObservationArchiveError("source PNG is corrupt") from error
        if len(payload) != envelope["png_size"] or sha256(payload).hexdigest() != envelope["screenshot_sha256"]:
            raise FreshLearningObservationArchiveError("source PNG is corrupt")
        dimensions = _png_dimensions(payload)
        viewport = envelope["viewport_size"]
        if dimensions != (viewport.get("width"), viewport.get("height")):
            raise FreshLearningObservationArchiveError("source PNG dimensions are corrupt")
        return payload

    def _committed_payload_bytes(self) -> int:
        """额度只统计可读取的 PNG 与来源记录，不统计固定锁文件。"""

        try:
            return sum(
                path.stat().st_size
                for directory in (self.png_root, self.records_root)
                for path in directory.iterdir()
                if path.is_file()
            )
        except OSError as error:
            raise FreshLearningObservationArchiveError("total budget is unavailable") from error


def _validate_packet(packet: FreshLearningObservationPacket, *, max_png_bytes: int) -> tuple[dict[str, Any], int]:
    if not isinstance(packet, FreshLearningObservationPacket):
        raise TypeError("packet must be FreshLearningObservationPacket")
    png = packet.png_bytes
    if len(png) > max_png_bytes:
        raise FreshLearningObservationArchiveError("PNG budget exceeded")
    dimensions = _png_dimensions(png)
    try:
        evidence = packet.evidence()
    except ValueError as error:
        raise FreshLearningObservationArchiveError("evidence is corrupt") from error
    if evidence.get("contract_version") != OBSERVATION_CONTRACT_VERSION:
        raise FreshLearningObservationArchiveError("evidence contract is invalid")
    capture = evidence.get("capture")
    if not isinstance(capture, dict):
        raise FreshLearningObservationArchiveError("evidence capture is invalid")
    digest = sha256(png).hexdigest()
    if capture.get("screenshot_sha256") != digest:
        raise FreshLearningObservationArchiveError("evidence screenshot does not match PNG")
    if not isinstance(capture.get("capture_id"), str) or not capture["capture_id"]:
        raise FreshLearningObservationArchiveError("evidence capture is invalid")
    viewport = capture.get("viewport_size")
    if not isinstance(viewport, dict) or dimensions != (viewport.get("width"), viewport.get("height")):
        raise FreshLearningObservationArchiveError("evidence PNG dimensions do not match")
    if any(evidence.get(key) is not False for key in ("artifact_is_authorization", "execute_binding_enabled", "action_executed")):
        raise FreshLearningObservationArchiveError("evidence cannot claim an asset or action")
    return evidence, len(png)


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise FreshLearningObservationArchiveError("source PNG is invalid")
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != "PNG":
                raise FreshLearningObservationArchiveError("source PNG is invalid")
            image.load()
            return image.size
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise FreshLearningObservationArchiveError("source PNG is invalid") from error


def _scope(connection_id: Any, task_id: Any, segment_id: Any) -> dict[str, str]:
    values = {"connection_id": connection_id, "task_id": task_id, "segment_id": segment_id}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise FreshLearningObservationArchiveError("source scope is invalid")
    return values


def _reference(reference: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(reference, Mapping) or set(reference) != {"contract_version", "source_id", "content_sha256", "capture_id", "screenshot_sha256"}:
        raise FreshLearningObservationArchiveError("source reference is invalid")
    value = dict(reference)
    if value["contract_version"] != REFERENCE_CONTRACT_VERSION:
        raise FreshLearningObservationArchiveError("source reference is invalid")
    for key in ("source_id", "content_sha256", "capture_id", "screenshot_sha256"):
        if not isinstance(value[key], str) or not value[key]:
            raise FreshLearningObservationArchiveError("source reference is invalid")
    for key in ("source_id", "content_sha256", "screenshot_sha256"):
        if len(value[key]) != 64 or any(char not in "0123456789abcdef" for char in value[key]):
            raise FreshLearningObservationArchiveError("source reference is invalid")
    return value


def _positive_limit(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise FreshLearningObservationArchiveError("source value is not canonical JSON") from error


__all__ = [
    "FreshLearningObservationArchive",
    "FreshLearningObservationArchiveError",
]
