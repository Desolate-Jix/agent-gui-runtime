"""将已提交的首次观察安全装载为仅运行时来源。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.fresh_learning_observation import FreshLearningObservationPacket
from app.agent_link.contracts import AgentLinkError
from app.agent_link.fresh_source_contract import validate_fresh_source_metadata


CONTRACT_VERSION = "fresh_learning_runtime_source_v1"
_SOURCE_KIND = "fresh_learning"
_REFERENCE_KEYS = {
    "contract_version",
    "source_kind",
    "connection_id",
    "task_id",
    "segment_id",
    "batch_id",
    "source_metadata",
    "application_identity",
    "target_window_handle",
    "target_process_id",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "action_executed",
    "source_sha256",
}


class FreshLearningRuntimeSourceError(ValueError):
    """首次运行时来源不是当前已提交的不可变观察。"""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise FreshLearningRuntimeSourceError("fresh runtime source is not canonical JSON") from error


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise FreshLearningRuntimeSourceError(f"fresh runtime {label} is invalid")
    return value


def _scope_value(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise FreshLearningRuntimeSourceError(f"fresh runtime {label} is invalid")
    return value


def _normalized_application_identity(value: Mapping[str, Any]) -> dict[str, str]:
    from app.agent.fresh_learning_observation import _application_identity

    try:
        return _application_identity(value)
    except (TypeError, ValueError) as error:
        raise FreshLearningRuntimeSourceError("fresh runtime application identity is invalid") from error


def _application_identity_from_evidence(evidence: Mapping[str, Any]) -> dict[str, str]:
    application = evidence.get("application")
    if not isinstance(application, Mapping):
        raise FreshLearningRuntimeSourceError("fresh runtime application evidence is invalid")
    value = dict(application)
    if value.get("kind") == "web":
        if set(value) == {"kind", "canonical_origin"}:
            # 原始网页记忆仍可读取；字段执行另需本次采集的完整进程身份。
            candidate = value
        elif set(value) == {"kind", "canonical_origin", "executable_path", "process_create_time"}:
            from app.agent.native_identity import normalize_windows_executable_path
            created = value["process_create_time"]
            # 浏览器仍是 web 应用；只验证 OS 身份字段，不能把它递归伪装成 native 应用。
            if (isinstance(created, bool) or not isinstance(created, (int, float))
                    or not math.isfinite(float(created)) or float(created) <= 0
                    or normalize_windows_executable_path(value["executable_path"]) is None):
                raise FreshLearningRuntimeSourceError("fresh runtime web process evidence is invalid")
            candidate = {"kind": "web", "canonical_origin": value["canonical_origin"]}
        else:
            raise FreshLearningRuntimeSourceError("fresh runtime web application evidence is invalid")
    elif value.get("kind") == "native":
        if set(value) != {"kind", "executable_path", "process_create_time"}:
            raise FreshLearningRuntimeSourceError("fresh runtime native application evidence is invalid")
        created = value.get("process_create_time")
        if (
            isinstance(created, bool)
            or not isinstance(created, (int, float))
            or not math.isfinite(float(created))
            or float(created) <= 0
        ):
            raise FreshLearningRuntimeSourceError("fresh runtime native application evidence is invalid")
        candidate = {"kind": "native", "executable_path": value.get("executable_path")}
    else:
        raise FreshLearningRuntimeSourceError("fresh runtime application evidence is invalid")
    try:
        return _normalized_application_identity(candidate)
    except FreshLearningRuntimeSourceError as error:
        raise FreshLearningRuntimeSourceError("fresh runtime application evidence is invalid") from error


def _packet_target(evidence: Mapping[str, Any]) -> tuple[int, int]:
    target = evidence.get("target")
    if not isinstance(target, Mapping) or set(target) != {"window_handle", "process_id", "rect"}:
        raise FreshLearningRuntimeSourceError("fresh runtime target evidence is invalid")
    return (
        _positive_int(target.get("window_handle"), "target window handle"),
        _positive_int(target.get("process_id"), "target process ID"),
    )


def _snapshot(
    source_owner: Any,
    *,
    connection_id: str,
    task_id: str,
    segment_id: str,
    batch_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    segments = source_owner.segments

    def read(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        segment = segments._stored_segment(state, connection_id, task_id, segment_id)
        batch = state["batches"].get(batch_id)
        if batch is None:
            raise FreshLearningRuntimeSourceError("fresh runtime batch is not committed")
        return deepcopy(segment), deepcopy(batch)

    try:
        return segments.store.read(read)
    except AgentLinkError as error:
        raise FreshLearningRuntimeSourceError("fresh runtime source scope or ownership is unavailable") from error


def _committed_source(
    segment: Mapping[str, Any],
    batch: Mapping[str, Any],
    *,
    connection_id: str,
    task_id: str,
    segment_id: str,
    batch_id: str,
) -> dict[str, Any]:
    if segment.get("status") != "active":
        raise FreshLearningRuntimeSourceError("fresh runtime segment is not active")
    if batch.get("connection_id") != connection_id or batch.get("task_id") != task_id:
        raise FreshLearningRuntimeSourceError("fresh runtime batch scope does not match")
    source = batch.get("fresh_learning_source")
    try:
        checked = validate_fresh_source_metadata(source)
    except ValueError as error:
        raise FreshLearningRuntimeSourceError("fresh runtime batch source is invalid") from error
    if (
        checked["connection_id"] != connection_id
        or checked["task_id"] != task_id
        or checked["segment_id"] != segment_id
    ):
        raise FreshLearningRuntimeSourceError("fresh runtime source scope does not match")
    observations = segment.get("observations")
    if not isinstance(observations, list):
        raise FreshLearningRuntimeSourceError("fresh runtime batch membership is unavailable")
    memberships = [
        item for item in observations
        if isinstance(item, Mapping) and item.get("batch_id") == batch_id
    ]
    if len(memberships) != 1 or memberships[0].get("source") != checked:
        raise FreshLearningRuntimeSourceError("fresh runtime batch membership does not match")
    screenshots = batch.get("screenshots")
    if not isinstance(screenshots, list) or len(screenshots) != 1:
        raise FreshLearningRuntimeSourceError("fresh runtime batch screenshot is invalid")
    return checked


def _validate_batch_capture(batch: Mapping[str, Any], packet: FreshLearningObservationPacket) -> None:
    evidence = packet.evidence()
    capture = evidence.get("capture")
    if not isinstance(capture, Mapping):
        raise FreshLearningRuntimeSourceError("fresh runtime capture evidence is invalid")
    viewport = capture.get("viewport_size")
    screenshots = batch.get("screenshots")
    if not isinstance(viewport, Mapping) or not isinstance(screenshots, list) or len(screenshots) != 1:
        raise FreshLearningRuntimeSourceError("fresh runtime batch screenshot is invalid")
    shot = screenshots[0]
    if (
        not isinstance(shot, Mapping)
        or shot.get("screenshot_id") != "capture"
        or shot.get("sha256") != capture.get("screenshot_sha256")
        or shot.get("width") != viewport.get("width")
        or shot.get("height") != viewport.get("height")
    ):
        raise FreshLearningRuntimeSourceError("fresh runtime batch capture does not match source")


def _build_reference(
    *,
    connection_id: str,
    task_id: str,
    segment_id: str,
    batch_id: str,
    source_metadata: Mapping[str, Any],
    packet: FreshLearningObservationPacket,
) -> dict[str, Any]:
    evidence = packet.evidence()
    application_identity = _application_identity_from_evidence(evidence)
    target_window_handle, target_process_id = _packet_target(evidence)
    reference: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "source_kind": _SOURCE_KIND,
        "connection_id": connection_id,
        "task_id": task_id,
        "segment_id": segment_id,
        "batch_id": batch_id,
        "source_metadata": deepcopy(dict(source_metadata)),
        "application_identity": application_identity,
        "target_window_handle": target_window_handle,
        "target_process_id": target_process_id,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_executed": False,
    }
    return {**reference, "source_sha256": _digest(reference)}


def _validated_reference(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REFERENCE_KEYS:
        raise FreshLearningRuntimeSourceError("fresh runtime source reference is invalid")
    reference = deepcopy(dict(value))
    if (
        reference.get("contract_version") != CONTRACT_VERSION
        or reference.get("source_kind") != _SOURCE_KIND
        or any(reference.get(key) is not False for key in (
            "artifact_is_authorization", "execute_binding_enabled", "action_executed",
        ))
    ):
        raise FreshLearningRuntimeSourceError("fresh runtime source boundary is invalid")
    for key in ("connection_id", "task_id", "segment_id", "batch_id"):
        _scope_value(reference.get(key), key)
    try:
        source = validate_fresh_source_metadata(reference.get("source_metadata"))
    except ValueError as error:
        raise FreshLearningRuntimeSourceError("fresh runtime source metadata is invalid") from error
    if any(source[key] != reference[key] for key in ("connection_id", "task_id", "segment_id")):
        raise FreshLearningRuntimeSourceError("fresh runtime source metadata scope is invalid")
    application_identity = _normalized_application_identity(reference.get("application_identity"))
    if application_identity != reference["application_identity"]:
        raise FreshLearningRuntimeSourceError("fresh runtime application identity is invalid")
    _positive_int(reference.get("target_window_handle"), "target window handle")
    _positive_int(reference.get("target_process_id"), "target process ID")
    digest = reference.get("source_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest != _digest({
        key: item for key, item in reference.items() if key != "source_sha256"
    }):
        raise FreshLearningRuntimeSourceError("fresh runtime source digest is invalid")
    return reference


@dataclass(frozen=True, slots=True)
class FreshLearningRuntimeSource:
    project_root: Path
    reference_json: bytes
    packet: FreshLearningObservationPacket

    def __post_init__(self) -> None:
        if not isinstance(self.project_root, Path) or self.project_root != self.project_root.resolve():
            raise FreshLearningRuntimeSourceError("fresh runtime project root is invalid")
        from app.agent.fresh_learning_observation import FreshLearningObservationPacket

        if not isinstance(self.reference_json, bytes) or not isinstance(self.packet, FreshLearningObservationPacket):
            raise FreshLearningRuntimeSourceError("fresh runtime source payload is invalid")
        try:
            decoded = json.loads(self.reference_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FreshLearningRuntimeSourceError("fresh runtime source payload is invalid") from error
        reference = _validated_reference(decoded)
        if self.reference_json != _canonical_bytes(reference):
            raise FreshLearningRuntimeSourceError("fresh runtime source bytes are not canonical")

    def reference(self) -> dict[str, Any]:
        try:
            value = json.loads(self.reference_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:  # pragma: no cover
            raise FreshLearningRuntimeSourceError("fresh runtime source payload is invalid") from error
        return _validated_reference(value)


def _require_owner(source_owner: Any) -> None:
    from app.agent.fresh_learning_archive import FreshLearningObservationArchive
    from app.agent_link.fresh_graph_source import FreshGraphSourceOwner
    from app.agent_link.learning_segments import LearningSegmentOwner
    from app.desktop_review.workspace import NativeReviewFacade

    if not isinstance(source_owner, FreshGraphSourceOwner):
        raise TypeError("fresh runtime source requires a real FreshGraphSourceOwner")
    try:
        segments = source_owner.segments
        facade = source_owner.facade
        archive = source_owner.archive
        root = segments.recorder.project_root
        if (
            not isinstance(segments, LearningSegmentOwner)
            or not isinstance(facade, NativeReviewFacade)
            or not isinstance(archive, FreshLearningObservationArchive)
            or archive.project_root != root
            or Path(facade._artifact_root).resolve() != root
            or facade._service._store is not segments.store
        ):
            raise FreshLearningRuntimeSourceError(
                "fresh runtime source owner invariants do not match"
            )
    except FreshLearningRuntimeSourceError:
        raise
    except (AttributeError, TypeError, ValueError) as error:
        raise FreshLearningRuntimeSourceError(
            "fresh runtime source owner invariants are unavailable"
        ) from error


def _copy_packet(packet: "FreshLearningObservationPacket") -> "FreshLearningObservationPacket":
    from app.agent.fresh_learning_observation import FreshLearningObservationPacket

    if not isinstance(packet, FreshLearningObservationPacket):
        raise FreshLearningRuntimeSourceError("fresh runtime packet is invalid")
    return FreshLearningObservationPacket(
        png_bytes=bytes(packet.png_bytes), evidence_json=bytes(packet.evidence_json),
    )


def load_fresh_learning_runtime_source(
    source_owner: Any,
    *,
    connection_id: str,
    task_id: str,
    segment_id: str,
    batch_id: str,
) -> FreshLearningRuntimeSource:
    """读取同一活动段内已提交的首次观察，并在返回前重复检查范围。"""

    _require_owner(source_owner)
    connection_id = _scope_value(connection_id, "connection_id")
    task_id = _scope_value(task_id, "task_id")
    segment_id = _scope_value(segment_id, "segment_id")
    batch_id = _scope_value(batch_id, "batch_id")
    scope = {
        "connection_id": connection_id,
        "task_id": task_id,
        "segment_id": segment_id,
        "batch_id": batch_id,
    }
    initial_segment, initial_batch = _snapshot(source_owner, **scope)
    source_metadata = _committed_source(initial_segment, initial_batch, **scope)
    try:
        packet = source_owner.archive.read(source_metadata["reference"], **{
            key: scope[key] for key in ("connection_id", "task_id", "segment_id")
        })
    except (OSError, ValueError) as error:
        raise FreshLearningRuntimeSourceError("fresh runtime archive source is unavailable") from error
    _validate_batch_capture(initial_batch, packet)
    reference = _build_reference(packet=packet, source_metadata=source_metadata, **scope)
    final_segment, final_batch = _snapshot(source_owner, **scope)
    final_source = _committed_source(final_segment, final_batch, **scope)
    if final_segment != initial_segment or final_batch != initial_batch or final_source != source_metadata:
        raise FreshLearningRuntimeSourceError("fresh runtime source changed during load")
    return FreshLearningRuntimeSource(
        project_root=source_owner.archive.project_root,
        reference_json=_canonical_bytes(reference),
        packet=_copy_packet(packet),
    )


def reload_fresh_learning_runtime_source(
    source_owner: Any,
    source: FreshLearningRuntimeSource,
) -> FreshLearningRuntimeSource:
    """每次重启均重读归档与已提交范围，拒绝缓存或篡改的来源。"""

    if not isinstance(source, FreshLearningRuntimeSource):
        raise TypeError("fresh runtime source must be FreshLearningRuntimeSource")
    reference = source.reference()
    reloaded = load_fresh_learning_runtime_source(
        source_owner,
        connection_id=reference["connection_id"],
        task_id=reference["task_id"],
        segment_id=reference["segment_id"],
        batch_id=reference["batch_id"],
    )
    if (
        reloaded.project_root != source.project_root
        or reloaded.reference_json != source.reference_json
        or reloaded.packet != source.packet
    ):
        raise FreshLearningRuntimeSourceError("fresh runtime source differs from committed source")
    return reloaded


__all__ = [
    "FreshLearningRuntimeSource",
    "FreshLearningRuntimeSourceError",
    "load_fresh_learning_runtime_source",
    "reload_fresh_learning_runtime_source",
]
