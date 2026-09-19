"""Agent 连接拥有的连续学习段元数据与证据汇总。"""

from __future__ import annotations

import copy
import re
from typing import Any, Mapping
from uuid import uuid4

from app.agent.action_learning_capture_archive import (
    ActionLearningCaptureArchive,
    ActionLearningCaptureArchiveError,
)
from app.agent.action_learning_recorder import (
    ActionLearningRecorder,
    ActionLearningRecorderError,
)

from .contracts import AgentLinkError, canonical_hash
from .store import AgentLinkStore


CONTRACT_VERSION = "agent_learning_segment_v1"
MAX_SEGMENT_OBSERVATIONS = 256
LEARNING_SEGMENT_CAPABILITY = {
    "contract_version": CONTRACT_VERSION,
    "operations": [
        "start_learning_segment",
        "get_learning_segment",
        "finish_learning_segment",
    ],
}

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KEY = re.compile(r"^[\x21-\x7e]{1,128}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEGMENT_KEYS = {
    "contract_version",
    "segment_id",
    "title",
    "status",
    "revision",
    "start_idempotency_key",
    "start_request_sha256",
    "children",
    "closing",
}
_CHILD_KEYS = {
    "child_id",
    "learning_session_id",
    "runtime_session_id",
    "phase",
}
_CLOSING_KEYS = {"expected_revision", "children"}
_CLOSING_CHILD_KEYS = {
    "child_id",
    "learning_session_id",
    "runtime_session_id",
    "expected_revision",
}


def _fail(code: str, message: str) -> None:
    raise AgentLinkError(code, message)


def _stable_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail("invalid_arguments", f"{label} is invalid")
    return value


def _connection_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        _fail("invalid_arguments", "connection_id is invalid")
    return value


def _task_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 4000:
        _fail("invalid_arguments", "task_id is invalid")
    return value


def _title(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        _fail("invalid_arguments", "title is invalid")
    return value


def _idempotency_key(value: object) -> str:
    if not isinstance(value, str) or _KEY.fullmatch(value) is None:
        _fail("invalid_arguments", "idempotency_key is invalid")
    return value


def _positive_revision(value: object) -> int:
    if type(value) is not int or value < 1:
        _fail("invalid_arguments", "expected_revision must be a positive integer")
    return value


def _stored_id(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError
    return value


def validate_stored_learning_segments(value: Any) -> dict[str, Any]:
    """严格验证单个连接的持久化学习段，不迁移旧连接。"""

    if not isinstance(value, dict):
        raise ValueError
    active = 0
    start_keys: set[str] = set()
    for segment_id, segment in value.items():
        optional = {"observations"} if isinstance(segment, dict) and "observations" in segment else set()
        if not isinstance(segment, dict) or set(segment) != _SEGMENT_KEYS | optional:
            raise ValueError
        if optional:
            from .fresh_source_contract import validate_fresh_source_metadata
            observations = segment["observations"]
            if not isinstance(observations, list) or len(observations) > MAX_SEGMENT_OBSERVATIONS:
                raise ValueError
            batch_ids = set()
            for observation in observations:
                if not isinstance(observation, dict) or set(observation) != {"batch_id", "source"}:
                    raise ValueError
                batch_id = _stored_id(observation["batch_id"])
                source = validate_fresh_source_metadata(observation["source"])
                if batch_id in batch_ids or source["segment_id"] != segment_id:
                    raise ValueError
                batch_ids.add(batch_id)
        if segment.get("contract_version") != CONTRACT_VERSION:
            raise ValueError
        if _stored_id(segment_id) != segment.get("segment_id"):
            raise ValueError
        title = segment.get("title")
        key = segment.get("start_idempotency_key")
        digest = segment.get("start_request_sha256")
        if (
            not isinstance(title, str)
            or not title
            or len(title) > 512
            or not isinstance(key, str)
            or _KEY.fullmatch(key) is None
            or key in start_keys
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or canonical_hash({"title": title}) != digest
            or segment.get("status") not in {"active", "closing", "closed"}
            or type(segment.get("revision")) is not int
            or segment["revision"] < 1
            or not isinstance(segment.get("children"), list)
        ):
            raise ValueError
        start_keys.add(key)
        if segment["status"] in {"active", "closing"}:
            active += 1
        child_ids: set[str] = set()
        learning_ids: set[str] = set()
        runtime_ids: set[str] = set()
        pending = 0
        for child in segment["children"]:
            if not isinstance(child, dict) or set(child) != _CHILD_KEYS:
                raise ValueError
            child_id = _stored_id(child.get("child_id"))
            learning_id = _stored_id(child.get("learning_session_id"))
            runtime_id = _stored_id(child.get("runtime_session_id"))
            identity_digest = canonical_hash({
                "segment_id": segment_id,
                "runtime_session_id": runtime_id,
            })
            if (
                child_id in child_ids
                or learning_id in learning_ids
                or runtime_id in runtime_ids
                or child_id != "child." + identity_digest
                or learning_id != "learning." + identity_digest
                or child.get("phase") not in {"pending_bind", "bound", "cancelled"}
            ):
                raise ValueError
            child_ids.add(child_id)
            learning_ids.add(learning_id)
            runtime_ids.add(runtime_id)
            pending += child["phase"] == "pending_bind"
        if pending > 1:
            raise ValueError
        closing = segment["closing"]
        if segment["status"] == "active":
            if closing is not None:
                raise ValueError
        else:
            if not isinstance(closing, dict) or set(closing) != _CLOSING_KEYS:
                raise ValueError
            if type(closing.get("expected_revision")) is not int or closing["expected_revision"] < 1:
                raise ValueError
            expected_segment_revision = closing["expected_revision"] + (
                1 if segment["status"] == "closing" else 2
            )
            if segment["revision"] != expected_segment_revision:
                raise ValueError
            entries = closing.get("children")
            recorded_children = [child for child in segment["children"] if child["phase"] != "cancelled"]
            if not isinstance(entries, list) or len(entries) != len(recorded_children):
                raise ValueError
            for entry, child in zip(entries, recorded_children):
                if not isinstance(entry, dict) or set(entry) != _CLOSING_CHILD_KEYS:
                    raise ValueError
                if any(entry.get(field) != child.get(field) for field in (
                    "child_id", "learning_session_id", "runtime_session_id",
                )):
                    raise ValueError
                if type(entry.get("expected_revision")) is not int or entry["expected_revision"] < 1:
                    raise ValueError
        if segment["status"] != "active" and pending:
            raise ValueError
    if active > 1:
        raise ValueError
    return copy.deepcopy(value)


class LearningSegmentOwner:
    """协调同一收件箱、记录账本与 PNG 档案的只读学习段视图。"""

    def __init__(
        self,
        store: AgentLinkStore,
        *,
        recorder: ActionLearningRecorder,
        capture_archive: ActionLearningCaptureArchive,
    ) -> None:
        if not isinstance(store, AgentLinkStore):
            raise TypeError("store must be AgentLinkStore")
        if not isinstance(recorder, ActionLearningRecorder):
            raise TypeError("recorder must be ActionLearningRecorder")
        if (
            not isinstance(capture_archive, ActionLearningCaptureArchive)
            or capture_archive.recorder is not recorder
            or capture_archive.project_root != recorder.project_root
        ):
            raise TypeError("capture_archive must share the recorder")
        self.store = store
        self.recorder = recorder
        self.capture_archive = capture_archive

    def start(
        self,
        *,
        connection_id: str,
        task_id: str,
        idempotency_key: str,
        title: str,
    ) -> dict[str, Any]:
        connection_id = _connection_id(connection_id)
        task_id = _task_id(task_id)
        key = _idempotency_key(idempotency_key)
        title = _title(title)
        request_digest = canonical_hash({"title": title})

        def change(state: dict[str, Any]) -> str:
            connection = self._connection(state, connection_id, task_id)
            segments = connection.setdefault("learning_segments", {})
            for stored in segments.values():
                if stored["start_idempotency_key"] == key:
                    if stored["start_request_sha256"] != request_digest:
                        _fail("idempotency_conflict", "idempotency key was reused with different content")
                    return stored["segment_id"]
            if any(item["status"] in {"active", "closing"} for item in segments.values()):
                _fail("learning_busy", "another learning segment is active")
            segment_id = "segment." + uuid4().hex
            segments[segment_id] = {
                "contract_version": CONTRACT_VERSION,
                "segment_id": segment_id,
                "title": title,
                "status": "active",
                "revision": 1,
                "start_idempotency_key": key,
                "start_request_sha256": request_digest,
                "children": [],
                "closing": None,
            }
            return segment_id

        segment_id = self.store.mutate(change)
        return self.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)

    def get(
        self,
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
    ) -> dict[str, Any]:
        connection_id = _connection_id(connection_id)
        task_id = _task_id(task_id)
        segment_id = _stable_id(segment_id, "segment_id")
        initial = self._segment_snapshot(connection_id, task_id, segment_id)
        view = self._qualified_view(initial)
        final = self._segment_snapshot(connection_id, task_id, segment_id)
        if final != initial:
            _fail("stale_revision", "learning segment changed during source read")
        return view

    def attach_runtime(
        self,
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
        runtime_session_id: str,
    ) -> dict[str, Any]:
        connection_id = _connection_id(connection_id)
        task_id = _task_id(task_id)
        segment_id = _stable_id(segment_id, "segment_id")
        runtime_id = _stable_id(runtime_session_id, "runtime_session_id")
        initial = self._segment_snapshot(connection_id, task_id, segment_id)
        if initial["status"] != "active":
            _fail("learning_busy", "learning segment is not active")
        same = next((child for child in initial["children"] if child["runtime_session_id"] == runtime_id), None)
        if same is not None and same["phase"] == "bound":
            return self.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        pending = next((child for child in initial["children"] if child["phase"] == "pending_bind"), None)
        if pending is not None and pending["runtime_session_id"] != runtime_id:
            _fail("learning_busy", "a learning child bind is unresolved")
        if pending is None and initial["children"]:
            previous = self._qualified_child(initial["children"][-1])
            self._require_settled_child(previous)
            self._assert_segment_unchanged(connection_id, task_id, segment_id, initial)

        child_id, learning_id = self._child_ids(segment_id, runtime_id)
        if pending is None:
            def add_pending(state: dict[str, Any]) -> None:
                stored = self._stored_segment(state, connection_id, task_id, segment_id)
                if stored != initial:
                    _fail("stale_revision", "learning segment changed before runtime bind")
                stored["children"].append({
                    "child_id": child_id,
                    "learning_session_id": learning_id,
                    "runtime_session_id": runtime_id,
                    "phase": "pending_bind",
                })
                stored["revision"] += 1

            self.store.mutate(add_pending)
        try:
            self.recorder.start_learning_session(
                learning_session_id=learning_id,
                runtime_session_id=runtime_id,
            )
        except (ActionLearningRecorderError, OSError) as error:
            raise AgentLinkError(
                "learning_source_unavailable", "learning recorder bind is unavailable",
            ) from error

        def commit_bound(state: dict[str, Any]) -> None:
            stored = self._stored_segment(state, connection_id, task_id, segment_id)
            match = next((child for child in stored["children"] if child["runtime_session_id"] == runtime_id), None)
            if match is None or match["child_id"] != child_id or match["learning_session_id"] != learning_id:
                _fail("stale_revision", "learning child bind metadata changed")
            if match["phase"] == "pending_bind":
                match["phase"] = "bound"
                stored["revision"] += 1

        self.store.mutate(commit_bound)
        return self.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)

    def close_unconsumed_runtime(
        self,
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
        runtime_session_id: str,
    ) -> dict[str, Any]:
        """运行时确已释放后关闭空记录；撤销连接只允许完成既有清理。"""
        connection_id = _connection_id(connection_id)
        task_id = _task_id(task_id)
        segment_id = _stable_id(segment_id, "segment_id")
        runtime_id = _stable_id(runtime_session_id, "runtime_session_id")
        initial = self.store.read(
            lambda state: self._stored_cleanup_segment(state, connection_id, task_id, segment_id)
        )
        child = next((item for item in initial["children"] if item["runtime_session_id"] == runtime_id), None)
        if child is None:
            _fail("not_found", "learning runtime child was not found")
        if child["phase"] == "cancelled":
            return self._qualified_cleanup_view(initial)
        if child["phase"] not in {"bound", "pending_bind"}:
            _fail("learning_busy", "learning child is not eligible for empty cleanup")
        if child["phase"] in {"bound", "pending_bind"}:
            try:
                # 绑定提交可能晚于记录器写入；从已校验账本区分真正缺失与损坏。
                session = next((item for item in self.recorder.list_learning_sessions()
                                if item["learning_session_id"] == child["learning_session_id"]), None)
                if session is None and child["phase"] == "bound":
                    _fail("learning_source_unavailable", "bound learning recorder is missing")
                if session is not None and (
                    session["runtime_session_id"] != runtime_id
                    or session["status"] not in {"active", "finished"}
                    or session["events"]
                    or session["recording_gaps"]
                    or session["pending_before_refs"]
                ):
                    _fail("learning_busy", "learning child has durable action or unresolved gaps")
                if session is not None and session["status"] == "active":
                    self.recorder.finish_learning_session(
                        learning_session_id=child["learning_session_id"],
                        runtime_session_id=runtime_id,
                        require_empty=True,
                    )
            except AgentLinkError:
                raise
            except (ActionLearningRecorderError, OSError) as error:
                raise AgentLinkError(
                    "learning_source_unavailable", "learning recorder cleanup is unavailable",
                ) from error

        def commit_cancelled(state: dict[str, Any]) -> None:
            stored = self._stored_cleanup_segment(state, connection_id, task_id, segment_id)
            match = next((item for item in stored["children"] if item["runtime_session_id"] == runtime_id), None)
            if match is None or match["child_id"] != child["child_id"]:
                _fail("stale_revision", "learning child cleanup metadata changed")
            if match["phase"] != "cancelled":
                if match["phase"] != child["phase"]:
                    _fail("stale_revision", "learning child cleanup phase changed")
                match["phase"] = "cancelled"
                stored["revision"] += 1

        self.store.mutate(commit_cancelled)
        final = self.store.read(
            lambda state: self._stored_cleanup_segment(state, connection_id, task_id, segment_id)
        )
        return self._qualified_cleanup_view(final)

    def finish(
        self,
        *,
        connection_id: str,
        task_id: str,
        segment_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        connection_id = _connection_id(connection_id)
        task_id = _task_id(task_id)
        segment_id = _stable_id(segment_id, "segment_id")
        expected = _positive_revision(expected_revision)
        initial = self._segment_snapshot(connection_id, task_id, segment_id)
        if initial["status"] == "closed":
            original_expected = initial["closing"]["expected_revision"]
            if expected not in {original_expected, initial["revision"]}:
                _fail("stale_revision", "learning segment revision is stale")
            return self.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        if initial["status"] == "closing":
            original_expected = initial["closing"]["expected_revision"]
            if expected not in {original_expected, initial["revision"]}:
                _fail("stale_revision", "learning segment revision is stale")
            expected = original_expected
            closing = initial
        else:
            if initial["revision"] != expected:
                _fail("stale_revision", "learning segment revision is stale")
            qualified = self._qualified_view(initial)
            for child in qualified["children"]:
                self._require_finishable_child(child)
            self._assert_segment_unchanged(connection_id, task_id, segment_id, initial)
            pinned = [{
                "child_id": child["child_id"],
                "learning_session_id": child["learning_session_id"],
                "runtime_session_id": child["runtime_session_id"],
                "expected_revision": child["revision"],
            } for child in qualified["children"] if child["phase"] != "cancelled"]

            def begin_closing(state: dict[str, Any]) -> None:
                stored = self._stored_segment(state, connection_id, task_id, segment_id)
                if stored != initial:
                    _fail("stale_revision", "learning segment changed before close")
                stored["status"] = "closing"
                stored["closing"] = {"expected_revision": expected, "children": pinned}
                stored["revision"] += 1

            self.store.mutate(begin_closing)
            closing = self._segment_snapshot(connection_id, task_id, segment_id)

        for pinned in closing["closing"]["children"]:
            try:
                current = self.recorder.get_learning_session(
                    learning_session_id=pinned["learning_session_id"],
                )
                if (
                    current["runtime_session_id"] != pinned["runtime_session_id"]
                    or current["revision"] not in {
                        pinned["expected_revision"], pinned["expected_revision"] + 1,
                    }
                ):
                    _fail("stale_revision", "learning child changed during close")
                if current["revision"] == pinned["expected_revision"]:
                    if current["status"] != "active":
                        _fail("stale_revision", "learning child close state is invalid")
                elif current["status"] != "finished":
                    _fail("stale_revision", "learning child close state is invalid")
                evidence = self.capture_archive.read_session_evidence(
                    learning_session_id=pinned["learning_session_id"],
                    runtime_session_id=pinned["runtime_session_id"],
                    expected_revision=current["revision"],
                ).evidence()
                if evidence.get("source_status") != "complete":
                    _fail(
                        "learning_source_unavailable",
                        "learning child source became incomplete during close",
                    )
                if current["status"] == "active":
                    self.recorder.finish_learning_session(
                        learning_session_id=pinned["learning_session_id"],
                        runtime_session_id=pinned["runtime_session_id"],
                    )
            except AgentLinkError:
                raise
            except (ActionLearningRecorderError, ActionLearningCaptureArchiveError, OSError) as error:
                raise AgentLinkError(
                    "learning_source_unavailable", "learning child close source is unavailable",
                ) from error

        def commit_closed(state: dict[str, Any]) -> None:
            stored = self._stored_segment(state, connection_id, task_id, segment_id)
            if stored["status"] == "closed":
                if stored["closing"]["expected_revision"] != expected:
                    _fail("stale_revision", "learning segment revision is stale")
                return
            if stored != closing:
                _fail("stale_revision", "learning segment changed during close")
            stored["status"] = "closed"
            stored["revision"] += 1

        self.store.mutate(commit_closed)
        return self.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)

    @staticmethod
    def _connection(state: Mapping[str, Any], connection_id: str, task_id: str) -> dict[str, Any]:
        connection = state["connections"].get(connection_id)
        if connection is None or connection.get("task_id") != task_id:
            _fail("not_found", "learning connection was not found")
        if connection.get("revoked") is True:
            _fail("connection_revoked", "agent connection is revoked")
        return connection

    @staticmethod
    def _cleanup_connection(state: Mapping[str, Any], connection_id: str, task_id: str) -> dict[str, Any]:
        connection = state["connections"].get(connection_id)
        if connection is None or connection.get("task_id") != task_id:
            _fail("not_found", "learning connection was not found")
        return connection

    def _stored_cleanup_segment(
        self, state: Mapping[str, Any], connection_id: str, task_id: str, segment_id: str,
    ) -> dict[str, Any]:
        connection = self._cleanup_connection(state, connection_id, task_id)
        segment = connection.get("learning_segments", {}).get(segment_id)
        if segment is None:
            _fail("not_found", "learning segment was not found")
        return segment

    def _qualified_cleanup_view(self, segment: Mapping[str, Any]) -> dict[str, Any]:
        return self._qualified_view(segment)

    def _stored_segment(
        self, state: Mapping[str, Any], connection_id: str, task_id: str, segment_id: str,
    ) -> dict[str, Any]:
        connection = self._connection(state, connection_id, task_id)
        segment = connection.get("learning_segments", {}).get(segment_id)
        if segment is None:
            _fail("not_found", "learning segment was not found")
        return segment

    def _segment_snapshot(self, connection_id: str, task_id: str, segment_id: str) -> dict[str, Any]:
        return self.store.read(
            lambda state: self._stored_segment(state, connection_id, task_id, segment_id)
        )

    def _assert_segment_unchanged(
        self, connection_id: str, task_id: str, segment_id: str, expected: Mapping[str, Any],
    ) -> None:
        current = self._segment_snapshot(connection_id, task_id, segment_id)
        if current != expected:
            _fail("stale_revision", "learning segment changed during source read")

    @staticmethod
    def _child_ids(segment_id: str, runtime_id: str) -> tuple[str, str]:
        digest = canonical_hash({"segment_id": segment_id, "runtime_session_id": runtime_id})
        return "child." + digest, "learning." + digest

    def _qualified_view(self, segment: Mapping[str, Any]) -> dict[str, Any]:
        observations = copy.deepcopy(segment.get("observations", []))
        if observations:
            from app.agent.fresh_learning_archive import FreshLearningObservationArchive
            try:
                archive = FreshLearningObservationArchive(self.recorder.project_root)
                for observation in observations:
                    source = observation["source"]
                    archive.read(source["reference"], **{key: source[key] for key in ("connection_id", "task_id", "segment_id")})
            except (OSError, ValueError) as error:
                raise AgentLinkError("learning_source_unavailable", "fresh observation source is unavailable") from error
        children = [self._qualified_child(child) for child in segment["children"]]
        action_children = [child for child in children if child["phase"] != "cancelled"]
        if not action_children:
            status = "complete" if observations else "empty"
        elif all(child["source_status"] == "complete" for child in action_children):
            status = "complete"
        else:
            status = "incomplete"
        return {
            "contract_version": CONTRACT_VERSION,
            "segment_id": segment["segment_id"],
            "status": segment["status"],
            "revision": segment["revision"],
            "title": segment["title"],
            "children": children,
            **({"observations": observations} if "observations" in segment else {}),
            "source_status": status,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }

    def _qualified_child(self, child: Mapping[str, Any]) -> dict[str, Any]:
        base = {
            "child_id": child["child_id"],
            "learning_session_id": child["learning_session_id"],
            "runtime_session_id": child["runtime_session_id"],
            "phase": child["phase"],
        }
        if child["phase"] == "pending_bind":
            return {
                **base,
                "revision": None,
                "recording_status": "pending_bind",
                "source_status": "incomplete",
                "recording_gap_count": 0,
                "event_count": 0,
                "outcomes": [],
            }
        if child["phase"] == "cancelled":
            return {
                **base,
                "revision": None,
                "recording_status": "cancelled",
                "source_status": "empty",
                "recording_gap_count": 0,
                "event_count": 0,
                "outcomes": [],
            }
        try:
            session = self.recorder.get_learning_session(
                learning_session_id=child["learning_session_id"],
            )
            if session["runtime_session_id"] != child["runtime_session_id"]:
                raise ActionLearningRecorderError("learning session scope does not match")
            evidence = self.capture_archive.read_session_evidence(
                learning_session_id=child["learning_session_id"],
                runtime_session_id=child["runtime_session_id"],
                expected_revision=session["revision"],
            ).evidence()
        except (ActionLearningRecorderError, ActionLearningCaptureArchiveError, OSError) as error:
            raise AgentLinkError(
                "learning_source_unavailable", "learning segment source is unavailable",
            ) from error
        source_by_event = {item["event_id"]: item for item in evidence["event_sources"]}
        outcomes = []
        for event_id in sorted(session["events"]):
            event = session["events"][event_id]
            terminal = event["terminal"]
            source = source_by_event[event_id]
            outcomes.append({
                "event_id": event_id,
                "outcome": terminal["outcome"],
                "reason_code": terminal["reason_code"],
                "effect_status": terminal["effect_status"],
                "destination_status": terminal["destination_status"],
                "before_source_status": source["before"]["status"],
                "after_observation_present": source["after_observation_present"],
                "after_source_status": None if source["after"] is None else source["after"]["status"],
            })
        return {
            **base,
            "revision": session["revision"],
            "recording_status": session["status"],
            "source_status": evidence["source_status"],
            "recording_gap_count": len(session["recording_gaps"]),
            "event_count": len(session["events"]),
            "outcomes": outcomes,
        }

    @staticmethod
    def _require_settled_child(child: Mapping[str, Any]) -> None:
        if child["phase"] == "cancelled":
            return
        if child["recording_status"] != "active" or child["event_count"] == 0:
            _fail("learning_busy", "prior learning child has no terminal event")
        if child["recording_gap_count"]:
            _fail("learning_busy", "prior learning child has a recording gap")
        if child["source_status"] != "complete":
            _fail("learning_source_unavailable", "prior learning child source is incomplete")

    @staticmethod
    def _require_finishable_child(child: Mapping[str, Any]) -> None:
        if child["phase"] == "cancelled":
            return
        if child["phase"] != "bound" or child["event_count"] == 0:
            _fail("learning_busy", "learning child has no terminal event")
        if child["recording_gap_count"]:
            _fail("learning_busy", "learning child has a recording gap")
        if child["source_status"] != "complete":
            _fail("learning_source_unavailable", "learning child source is incomplete")
