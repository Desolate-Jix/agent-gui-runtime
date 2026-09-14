"""正式运行时动作的非执行型、显式会话记录账本。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.agent.reviewed_workflow_asset import _atomic_write, _exclusive_file_lock
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
    RuntimeVerifiedTerminalReceipt,
)
from app.agent.runtime_receipt_store import RuntimeReceiptRecord, RuntimeReceiptStore, RuntimeReceiptStoreError


LEDGER_CONTRACT_VERSION = "action_learning_ledger_v1"
SESSION_CONTRACT_VERSION = "action_learning_session_v1"
BEFORE_CONTRACT_VERSION = "action_learning_before_v1"
FRESH_BEFORE_CONTRACT_VERSION = "action_learning_before_v2"
EVENT_CONTRACT_VERSION = "action_learning_event_v1"
STORE_ROOT = Path("runtime_state/action-learning-v1")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BEFORE_KEYS = {
    "contract_version",
    "runtime_session_id",
    "observation_id",
    "intent_id",
    "intent_sha256",
    "workflow",
    "action",
    "capture",
    "current_observation_sha256",
    "projected_observation_sha256",
    "selection_ref",
    "selection_sha256",
    "grounding_sha256",
    "candidate_ref",
    "geometry",
    "gate_decision_ref",
    "scroll_capture_ref",
    "text_field_expectation_sha256",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_EVENT_KEYS = {
    "contract_version",
    "event_id",
    "learning_session_id",
    "runtime",
    "before",
    "terminal",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}


class ActionLearningRecorderError(ValueError):
    """记录生命周期、范围、完整性或持久化失败。"""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ActionLearningRecorderError(
            f"action learning serialization failed: {exc}"
        ) from exc


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or _STABLE_ID.fullmatch(value) is None:
        raise ActionLearningRecorderError(f"{label} is invalid")
    return value


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ActionLearningRecorderError(f"{label} is invalid")
    return value


class ActionLearningRecorder:
    """仅记录已绑定 runtime session 的 before/terminal 证据引用。"""

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / STORE_ROOT
        self.ledger_path = self.root / "ledger.json"
        self.lock_path = self.root / ".ledger.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        self._read_ledger()

    def start_learning_session(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
    ) -> dict[str, Any]:
        learning_id = _require_id(learning_session_id, "learning_session_id")
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        with self._locked_ledger() as ledger:
            sessions = ledger["sessions"]
            bindings = ledger["runtime_bindings"]
            existing_binding = bindings.get(runtime_id)
            if existing_binding is not None and existing_binding != learning_id:
                raise ActionLearningRecorderError(
                    "runtime session is already bound to another learning session"
                )
            existing = sessions.get(learning_id)
            if existing is not None:
                if existing["runtime_session_id"] != runtime_id:
                    raise ActionLearningRecorderError(
                        "learning session is bound to another runtime session"
                    )
                if existing["status"] != "active":
                    raise ActionLearningRecorderError("learning session is already finished")
                bindings[runtime_id] = learning_id
                return self._session_view(existing)
            sessions[learning_id] = {
                "contract_version": SESSION_CONTRACT_VERSION,
                "learning_session_id": learning_id,
                "runtime_session_id": runtime_id,
                "status": "active",
                "revision": 1,
                "pending_befores": {},
                "events": {},
                "receipt_bindings": {},
            }
            bindings[runtime_id] = learning_id
            ledger["revision"] += 1
            self._write_ledger(ledger)
            return self._session_view(sessions[learning_id])

    def get_learning_session(self, *, learning_session_id: str) -> dict[str, Any]:
        learning_id = _require_id(learning_session_id, "learning_session_id")
        session, _ = self._read_session_with_sources(learning_id)
        return self._session_view(session)

    def list_learning_sessions(self) -> list[dict[str, Any]]:
        ledger = self._read_ledger()
        return [
            self._session_view(ledger["sessions"][session_id])
            for session_id in sorted(ledger["sessions"])
        ]

    def read_learning_session_sources(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """返回同一修订的记录视图及派发前截图来源状态，不把未知结果补为成功。"""

        learning_id = _require_id(learning_session_id, "learning_session_id")
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ActionLearningRecorderError("expected revision must be a positive integer")
        session, sources = self._read_session_with_sources(learning_id)
        if session["runtime_session_id"] != runtime_id:
            raise ActionLearningRecorderError("learning session scope does not match")
        if session["revision"] != expected_revision:
            raise ActionLearningRecorderError("learning session revision is stale")
        return {
            "contract_version": "action_learning_session_sources_v1",
            "session": self._session_view(session),
            "before_sources": {event_id: deepcopy(sources[event_id]) for event_id in session["events"]},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "action_executed": False,
        }

    def get_active_learning_binding(self, *, runtime_session_id: str) -> str | None:
        """只读返回同一账本中的当前显式学习绑定。"""

        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        ledger = self._read_ledger_snapshot()
        learning_id = ledger["runtime_bindings"].get(runtime_id)
        if learning_id is None:
            return None
        session = ledger["sessions"].get(learning_id)
        if (
            session is None
            or session["runtime_session_id"] != runtime_id
            or session["status"] != "active"
        ):
            raise ActionLearningRecorderError("learning session binding is invalid")
        self._validate_session_authority(session)
        return learning_id

    def finish_learning_session(
        self,
        *,
        learning_session_id: str,
        runtime_session_id: str,
        require_empty: bool = False,
    ) -> dict[str, Any]:
        if type(require_empty) is not bool:
            raise ActionLearningRecorderError("require_empty must be bool")
        learning_id = _require_id(learning_session_id, "learning_session_id")
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        with self._locked_ledger() as ledger:
            session = ledger["sessions"].get(learning_id)
            if session is None or session["runtime_session_id"] != runtime_id:
                raise ActionLearningRecorderError("learning session scope does not match")
            # 空准备的关闭必须在同一账本锁内核验，不能覆盖并发落盘的动作。
            if require_empty and (session["events"] or session["pending_befores"]):
                raise ActionLearningRecorderError("learning session is not empty")
            if session["status"] == "finished":
                return self._session_view(session)
            if session["pending_befores"]:
                raise ActionLearningRecorderError(
                    "learning session has unresolved recording gaps"
                )
            if ledger["runtime_bindings"].get(runtime_id) != learning_id:
                raise ActionLearningRecorderError("learning session binding is unavailable")
            session["status"] = "finished"
            session["revision"] += 1
            del ledger["runtime_bindings"][runtime_id]
            ledger["revision"] += 1
            self._write_ledger(ledger)
            return self._session_view(session)

    def record_before(
        self,
        *,
        runtime_session_id: str,
        observation_id: str,
        payload: Mapping[str, object],
    ) -> dict[str, Any] | None:
        runtime_id = _require_id(runtime_session_id, "runtime_session_id")
        observation = _require_id(observation_id, "observation_id")
        if not isinstance(payload, Mapping):
            raise ActionLearningRecorderError("before payload is invalid")
        canonical = deepcopy(dict(payload))
        if canonical.get("contract_version") not in {BEFORE_CONTRACT_VERSION, FRESH_BEFORE_CONTRACT_VERSION}:
            raise ActionLearningRecorderError("before payload contract is invalid")
        if canonical.get("runtime_session_id") != runtime_id:
            raise ActionLearningRecorderError("before runtime scope does not match")
        if canonical.get("observation_id") != observation:
            raise ActionLearningRecorderError("before observation scope does not match")
        digest = _sha256(canonical)
        record = {**canonical, "content_sha256": digest}
        self._validate_before_shape(record)
        with self._locked_ledger() as ledger:
            learning_id = ledger["runtime_bindings"].get(runtime_id)
            if learning_id is None:
                return None
            session = ledger["sessions"].get(learning_id)
            if session is None or session["status"] != "active":
                raise ActionLearningRecorderError("learning session binding is invalid")
            existing = session["pending_befores"].get(observation)
            if existing is not None:
                if existing != record:
                    raise ActionLearningRecorderError(
                        "before observation identity conflict"
                    )
                return deepcopy(existing)
            session["pending_befores"][observation] = record
            session["revision"] += 1
            ledger["revision"] += 1
            self._write_ledger(ledger)
            return deepcopy(record)

    def observe_terminal_receipt(
        self,
        verified: RuntimeVerifiedTerminalReceipt,
    ) -> None:
        """只接受 claim store 在 terminal 重读后构造的内部证明。"""

        if not isinstance(verified, RuntimeVerifiedTerminalReceipt):
            raise ActionLearningRecorderError(
                "terminal receipt must be verified by the claim store"
            )
        verified.require_valid()
        record = verified.record
        receipt = record.runtime_receipt
        if (
            receipt.session_id != verified.session_id
            or receipt.observation_id != verified.observation_id
        ):
            raise ActionLearningRecorderError("terminal receipt scope does not match")
        with self._locked_ledger() as ledger:
            learning_id = ledger["runtime_bindings"].get(verified.session_id)
            if learning_id is None:
                return
            session = ledger["sessions"].get(learning_id)
            if session is None or session["status"] != "active":
                raise ActionLearningRecorderError("learning session binding is invalid")
            before = session["pending_befores"].get(verified.observation_id)
            if before is None:
                # 未在共同派发边界成功持久化 before 时，不能凭 terminal 反推。
                return
            existing_digest = session["receipt_bindings"].get(receipt.receipt_id)
            if (
                existing_digest is not None
                and existing_digest != record.content_sha256
            ):
                raise ActionLearningRecorderError(
                    "terminal receipt identity has different content"
                )
            event = self._build_event(
                learning_session_id=learning_id,
                before=before,
                verified=verified,
            )
            event_id = event["event_id"]
            existing = session["events"].get(event_id)
            if existing is not None:
                if existing != event:
                    raise ActionLearningRecorderError("learning event identity conflict")
                session["pending_befores"].pop(verified.observation_id, None)
                return
            session["receipt_bindings"][receipt.receipt_id] = record.content_sha256
            session["events"][event_id] = event
            del session["pending_befores"][verified.observation_id]
            session["revision"] += 1
            ledger["revision"] += 1
            self._write_ledger(ledger)

    def recover_pending(
        self,
        *,
        learning_session_id: str,
        claim_store: RuntimeIntentClaimStore,
    ) -> dict[str, Any]:
        learning_id = _require_id(learning_session_id, "learning_session_id")
        if not isinstance(claim_store, RuntimeIntentClaimStore):
            raise ActionLearningRecorderError("claim_store is required")
        if claim_store.project_root != self.project_root:
            raise ActionLearningRecorderError(
                "claim_store must use the learning recorder project root"
            )
        claim_store.add_terminal_receipt_observer(self.observe_terminal_receipt)
        session = self.get_learning_session(learning_session_id=learning_id)
        pending = [
            (session["runtime_session_id"], observation_id)
            for observation_id in session["recording_gaps"]
        ]
        # 不持有 recorder 锁调用 claim store，避免 terminal observer 反向重入死锁。
        for runtime_session_id, observation_id in pending:
            claim_store.load_terminal_receipt(
                session_id=runtime_session_id,
                observation_id=observation_id,
            )
        return self.get_learning_session(learning_session_id=learning_id)

    def _build_event(
        self,
        *,
        learning_session_id: str,
        before: Mapping[str, Any],
        verified: RuntimeVerifiedTerminalReceipt,
    ) -> dict[str, Any]:
        record = verified.record
        receipt = record.runtime_receipt
        identity_material = (
            f"{learning_session_id}\0{receipt.receipt_id}\0{record.content_sha256}"
        ).encode("utf-8")
        event_id = "learning-event." + hashlib.sha256(identity_material).hexdigest()
        payload = {
            "contract_version": EVENT_CONTRACT_VERSION,
            "event_id": event_id,
            "learning_session_id": learning_session_id,
            "runtime": {
                "session_id": verified.session_id,
                "observation_id": verified.observation_id,
            },
            "before": deepcopy(dict(before)),
            "terminal": self._terminal_projection(record),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        return {**payload, "content_sha256": _sha256(payload)}

    def _terminal_projection(self, record: RuntimeReceiptRecord) -> dict[str, Any]:
        receipt = record.runtime_receipt
        receipt_payload = receipt.model_dump(mode="json")
        return {
            "receipt_id": receipt.receipt_id,
            "receipt_content_sha256": record.content_sha256,
            "intent_id": receipt.intent_id,
            "action": deepcopy(receipt_payload["action"]),
            "outcome": receipt.outcome,
            "reason_code": receipt.reason_code,
            "attempt_count": receipt.attempt_count,
            "gate_status": receipt.gate_status,
            "dispatch_status": receipt.dispatch_status,
            "effect_status": receipt.effect_status,
            "destination_status": receipt.destination_status,
            "evidence": deepcopy(receipt_payload["evidence"]),
            "next_observation_id": receipt.next_observation_id,
            "backend_receipt": (
                asdict(record.backend_receipt)
                if record.backend_receipt is not None
                else None
            ),
            "verification_evidence_sha256": (
                _sha256(record.verification_evidence)
                if record.verification_evidence is not None
                else None
            ),
            "next_observation_ref": self._next_observation_ref(record.next_observation),
        }

    @staticmethod
    def _next_observation_ref(observation: Any) -> dict[str, Any] | None:
        if observation is None:
            return None
        from app.agent.fresh_learning_action_contracts import FreshLearningClaimObservation
        if isinstance(observation, FreshLearningClaimObservation):
            current = observation.to_dict()
            return {
                "observation_id": current["observation_id"], "state": "unreviewed",
                "capture_id": current["capture"]["capture_id"],
                "screenshot_sha256": current["capture"]["screenshot_sha256"],
                "evidence_ref": "fresh-capture:" + current["capture_source"]["source_id"],
            }
        current_capture = observation.current_capture
        return {
            "observation_id": observation.observation_id,
            "state_resolution_ref": observation.state_resolution_ref,
            "capture_id": current_capture.capture_id,
            "screenshot_sha256": current_capture.screenshot_sha256,
            "evidence_ref": current_capture.evidence_ref,
        }

    def _session_view(self, session: Mapping[str, Any]) -> dict[str, Any]:
        view = deepcopy(dict(session))
        pending = view.pop("pending_befores")
        view.pop("receipt_bindings")
        view["recording_gaps"] = sorted(pending)
        view["pending_before_refs"] = [
            {
                "observation_id": observation_id,
                "intent_id": pending[observation_id]["intent_id"],
                "capture_id": pending[observation_id]["capture"]["capture_id"],
                "content_sha256": pending[observation_id]["content_sha256"],
            }
            for observation_id in sorted(pending)
        ]
        return view

    def _empty_ledger(self) -> dict[str, Any]:
        return {
            "contract_version": LEDGER_CONTRACT_VERSION,
            "revision": 0,
            "sessions": {},
            "runtime_bindings": {},
        }

    def _read_ledger(self) -> dict[str, Any]:
        return self._read_ledger_with_sources()[0]

    def _read_ledger_with_sources(self) -> tuple[dict[str, Any], dict[str, Any]]:
        ledger = self._read_ledger_snapshot()
        sources = self._validate_authoritative_events(ledger)
        return ledger, sources

    def _read_ledger_snapshot(self) -> dict[str, Any]:
        with _exclusive_file_lock(self.lock_path):
            return self._read_ledger_unlocked()

    def _read_session_with_sources(self, learning_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        # 全账本结构仍逐次校验；单段读取只证明本段，不宣称其他历史证据健康。
        ledger = self._read_ledger_snapshot()
        session = ledger["sessions"].get(learning_id)
        if session is None:
            raise ActionLearningRecorderError("learning session was not found")
        return session, self._validate_session_authority(session)

    def _validate_session_authority(self, session: Mapping[str, Any]) -> dict[str, Any]:
        return self._validate_events(list(session["events"].values()))

    def _validate_authoritative_events(self, ledger: Mapping[str, Any]) -> dict[str, Any]:
        events = [event for session in ledger["sessions"].values() for event in session["events"].values()]
        return self._validate_events(events)

    def _validate_events(self, events: list[Mapping[str, Any]]) -> dict[str, Any]:
        if not events:
            return {}
        sources = {}
        try:
            receipts = RuntimeReceiptStore(project_root=self.project_root, create_layout=False)
            claims = RuntimeIntentClaimStore(project_root=self.project_root, receipt_store=receipts, create_layout=False)
            for event in events:
                runtime = event["runtime"]
                snapshot, record = claims.read_committed_terminal_evidence(
                    session_id=runtime["session_id"], observation_id=runtime["observation_id"],
                )
                receipt = record.runtime_receipt
                before = event["before"]
                if before.get("contract_version") == FRESH_BEFORE_CONTRACT_VERSION:
                    from app.agent.fresh_learning_recording import validate_fresh_before_source
                    if event["terminal"] != self._terminal_projection(record):
                        raise ActionLearningRecorderError("fresh event differs from authoritative receipt")
                    try:
                        sources[event["event_id"]] = validate_fresh_before_source(before, snapshot, record)
                    except (ValueError, TypeError, KeyError) as error:
                        raise ActionLearningRecorderError("fresh learning source is unavailable or corrupt") from error
                    continue
                if (
                    event["terminal"] != self._terminal_projection(record)
                    or before["intent_id"] != receipt.intent_id
                    or before["workflow"] != receipt.workflow.model_dump(mode="json")
                    or before["action"] != receipt.action.model_dump(mode="json", exclude_none=True)
                ):
                    raise ActionLearningRecorderError("learning event differs from authoritative receipt")
                for field in ("selection_ref", "candidate_ref", "gate_decision_ref"):
                    reference = getattr(receipt.evidence, field)
                    if reference is not None and before[field] != reference:
                        raise ActionLearningRecorderError("learning before differs from authoritative receipt")
                sources[event["event_id"]] = self._validate_before_capture_source(before, snapshot)
        except (RuntimeIntentClaimStoreError, RuntimeReceiptStoreError, OSError) as error:
            raise ActionLearningRecorderError("authoritative learning receipt is unavailable or corrupt") from error
        return sources

    @staticmethod
    def _validate_before_capture_source(before: Mapping[str, Any], snapshot: Any) -> dict[str, Any]:
        checkpoint = snapshot.verification_checkpoint
        if checkpoint is None:
            # 派发结果未知时可能没有检查点；保留回执，但不把自封截图引用当成已验证来源。
            return {
                "status": "unavailable", "reason": "verification_checkpoint_unavailable",
                "checkpoint_sha256": None,
            }
        current = checkpoint.current_observation
        grounding = checkpoint.grounding
        selection = checkpoint.selection
        point = grounding.get("click_point")
        if not isinstance(point, Mapping) or set(point) != {"x", "y"}:
            raise ActionLearningRecorderError("authoritative learning grounding point is invalid")
        expected_geometry = {
            "bbox": grounding.get("bbox"),
            "viewport_size": current.get("viewport_size"),
            "click_point": [point["x"], point["y"]],
            "target_window_handle": snapshot.server_binding.target_window_handle,
            "target_process_id": checkpoint.target_process_id,
        }
        if (
            any(before["capture"].get(key) != current.get(key) for key in ("capture_id", "screenshot_sha256"))
            or before["geometry"] != expected_geometry
            or before["selection_sha256"] != selection.get("selection_sha256")
            or before["grounding_sha256"] != _sha256(grounding)
            or before["current_observation_sha256"] != _sha256(current)
            or before["intent_sha256"] != _sha256(snapshot.intent.model_dump(mode="json"))
            or before["gate_decision_ref"] != checkpoint.gate_decision_ref
        ):
            raise ActionLearningRecorderError("learning before capture differs from authoritative dispatch checkpoint")
        return {"status": "verified", "reason": None, "checkpoint_sha256": checkpoint.checkpoint_sha256}

    def _read_ledger_unlocked(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return self._empty_ledger()
        try:
            raw = self.ledger_path.read_bytes()
            decoded = raw.decode("utf-8")
            ledger = json.loads(decoded)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ActionLearningRecorderError(
                "action learning ledger is unavailable or corrupt"
            ) from exc
        if _canonical_bytes(ledger) != raw:
            raise ActionLearningRecorderError("action learning ledger is not canonical")
        self._validate_ledger(ledger)
        return ledger

    @contextmanager
    def _locked_ledger(self):
        # 不持账本锁复核 claim；重新入锁后拒绝被并发替换的快照。
        verified = self._read_ledger()
        with _exclusive_file_lock(self.lock_path):
            current = self._read_ledger_unlocked()
            if current != verified:
                raise ActionLearningRecorderError("learning ledger changed during verification; retry required")
            yield current

    def _write_ledger(self, ledger: Mapping[str, Any]) -> None:
        try:
            self._validate_ledger(ledger)
            _atomic_write(self.ledger_path, _canonical_bytes(ledger))
        except ActionLearningRecorderError:
            raise
        except (OSError, TimeoutError) as exc:
            raise ActionLearningRecorderError(
                "action learning ledger persistence failed"
            ) from exc

    def _validate_ledger(self, value: object) -> None:
        if not isinstance(value, dict) or set(value) != {
            "contract_version",
            "revision",
            "sessions",
            "runtime_bindings",
        }:
            raise ActionLearningRecorderError("action learning ledger contract is invalid")
        if value["contract_version"] != LEDGER_CONTRACT_VERSION:
            raise ActionLearningRecorderError("action learning ledger version is invalid")
        if type(value["revision"]) is not int or value["revision"] < 0:
            raise ActionLearningRecorderError("action learning ledger revision is invalid")
        sessions = value["sessions"]
        bindings = value["runtime_bindings"]
        if not isinstance(sessions, dict) or not isinstance(bindings, dict):
            raise ActionLearningRecorderError("action learning ledger collections are invalid")
        for learning_id, session in sessions.items():
            self._validate_session(learning_id, session)
        for runtime_id, learning_id in bindings.items():
            _require_id(runtime_id, "runtime binding")
            _require_id(learning_id, "learning binding")
            session = sessions.get(learning_id)
            if (
                session is None
                or session["runtime_session_id"] != runtime_id
                or session["status"] != "active"
            ):
                raise ActionLearningRecorderError("runtime binding is inconsistent")
        active = {
            session["runtime_session_id"]: learning_id
            for learning_id, session in sessions.items()
            if session["status"] == "active"
        }
        if active != bindings:
            raise ActionLearningRecorderError("active learning bindings are incomplete")

    def _validate_session(self, learning_id: object, session: object) -> None:
        _require_id(learning_id, "learning session key")
        if not isinstance(session, dict) or set(session) != {
            "contract_version",
            "learning_session_id",
            "runtime_session_id",
            "status",
            "revision",
            "pending_befores",
            "events",
            "receipt_bindings",
        }:
            raise ActionLearningRecorderError("learning session contract is invalid")
        if (
            session["contract_version"] != SESSION_CONTRACT_VERSION
            or session["learning_session_id"] != learning_id
            or session["status"] not in {"active", "finished"}
            or type(session["revision"]) is not int
            or session["revision"] < 1
        ):
            raise ActionLearningRecorderError("learning session identity is invalid")
        _require_id(session["runtime_session_id"], "runtime_session_id")
        pending = session["pending_befores"]
        events = session["events"]
        receipt_bindings = session["receipt_bindings"]
        if not all(isinstance(item, dict) for item in (pending, events, receipt_bindings)):
            raise ActionLearningRecorderError("learning session records are invalid")
        if session["status"] == "finished" and pending:
            raise ActionLearningRecorderError("finished learning session has pending gaps")
        for observation_id, before in pending.items():
            _require_id(observation_id, "pending observation key")
            self._validate_hashed_record(
                before,
                contract=(FRESH_BEFORE_CONTRACT_VERSION if before.get("contract_version") == FRESH_BEFORE_CONTRACT_VERSION else BEFORE_CONTRACT_VERSION),
                identity=("observation_id", observation_id),
            )
            if before["runtime_session_id"] != session["runtime_session_id"]:
                raise ActionLearningRecorderError("pending before scope is invalid")
            self._validate_before_shape(before)
        observed_receipts: dict[str, str] = {}
        for event_id, event in events.items():
            _require_id(event_id, "learning event key")
            self._validate_hashed_record(
                event,
                contract=EVENT_CONTRACT_VERSION,
                identity=("event_id", event_id),
            )
            if event["learning_session_id"] != learning_id:
                raise ActionLearningRecorderError("learning event scope is invalid")
            if set(event) != _EVENT_KEYS:
                raise ActionLearningRecorderError("learning event fields are invalid")
            if event["artifact_is_authorization"] is not False or event[
                "execute_binding_enabled"
            ] is not False:
                raise ActionLearningRecorderError("learning event cannot grant authority")
            runtime = event.get("runtime")
            before = event.get("before")
            if (
                not isinstance(runtime, dict)
                or set(runtime) != {"session_id", "observation_id"}
                or runtime["session_id"] != session["runtime_session_id"]
                or not isinstance(before, dict)
                or before.get("runtime_session_id") != runtime["session_id"]
                or before.get("observation_id") != runtime["observation_id"]
            ):
                raise ActionLearningRecorderError("learning event runtime scope is invalid")
            self._validate_before_shape(before)
            terminal = event.get("terminal")
            if not isinstance(terminal, dict) or set(terminal) != {
                "receipt_id",
                "receipt_content_sha256",
                "intent_id",
                "action",
                "outcome",
                "reason_code",
                "attempt_count",
                "gate_status",
                "dispatch_status",
                "effect_status",
                "destination_status",
                "evidence",
                "next_observation_id",
                "backend_receipt",
                "verification_evidence_sha256",
                "next_observation_ref",
            }:
                raise ActionLearningRecorderError("learning terminal event is invalid")
            receipt_id = _require_id(terminal.get("receipt_id"), "receipt_id")
            digest = _require_sha256(
                terminal.get("receipt_content_sha256"),
                "receipt_content_sha256",
            )
            prior = observed_receipts.setdefault(receipt_id, digest)
            if prior != digest:
                raise ActionLearningRecorderError(
                    "learning receipt identity has conflicting content"
                )
            expected_event_id = "learning-event." + hashlib.sha256(
                f"{learning_id}\0{receipt_id}\0{digest}".encode("utf-8")
            ).hexdigest()
            if event_id != expected_event_id:
                raise ActionLearningRecorderError("learning event identity is not deterministic")
        for receipt_id, digest in receipt_bindings.items():
            _require_id(receipt_id, "receipt binding")
            _require_sha256(digest, "receipt binding digest")
        if observed_receipts != receipt_bindings:
            raise ActionLearningRecorderError("learning receipt bindings are inconsistent")

    def _validate_before_shape(self, before: Mapping[str, Any]) -> None:
        if before.get("contract_version") == FRESH_BEFORE_CONTRACT_VERSION:
            from app.agent.fresh_learning_recording import validate_fresh_before_shape
            try:
                validate_fresh_before_shape(before)
            except (ValueError, TypeError, KeyError) as error:
                raise ActionLearningRecorderError("fresh before contract is invalid") from error
            return
        if set(before) != _BEFORE_KEYS:
            raise ActionLearningRecorderError("before observation fields are invalid")
        for field in (
            "intent_sha256",
            "current_observation_sha256",
            "projected_observation_sha256",
            "selection_sha256",
            "grounding_sha256",
        ):
            _require_sha256(before.get(field), field)
        if before.get("artifact_is_authorization") is not False or before.get(
            "execute_binding_enabled"
        ) is not False:
            raise ActionLearningRecorderError("before observation cannot grant authority")
        action = before.get("action")
        if (
            not isinstance(action, dict)
            or not {"action_id", "semantic_action"}.issubset(action)
            or not set(action).issubset(
                {
                    "action_id",
                    "semantic_action",
                    "scroll_parameters",
                    "text_parameters_ref",
                }
            )
            or ("scroll_parameters" in action and "text_parameters_ref" in action)
        ):
            raise ActionLearningRecorderError("before action reference is invalid")
        _require_id(action.get("action_id"), "before action_id")
        _require_id(action.get("semantic_action"), "before semantic_action")
        capture = before.get("capture")
        if not isinstance(capture, dict) or set(capture) != {
            "capture_id",
            "screenshot_sha256",
            "evidence_ref",
        }:
            raise ActionLearningRecorderError("before capture reference is invalid")
        _require_id(capture.get("capture_id"), "before capture_id")
        _require_sha256(capture.get("screenshot_sha256"), "before screenshot_sha256")
        if not isinstance(capture.get("evidence_ref"), str) or not capture["evidence_ref"]:
            raise ActionLearningRecorderError("before capture evidence_ref is invalid")
        for field in ("selection_ref", "candidate_ref", "gate_decision_ref"):
            if not isinstance(before.get(field), str) or not before[field]:
                raise ActionLearningRecorderError(f"before {field} is invalid")
        geometry = before.get("geometry")
        if not isinstance(geometry, dict) or set(geometry) != {
            "bbox",
            "viewport_size",
            "click_point",
            "target_window_handle",
            "target_process_id",
        }:
            raise ActionLearningRecorderError("before geometry is invalid")
        text_digest = before.get("text_field_expectation_sha256")
        if text_digest is not None:
            _require_sha256(text_digest, "text_field_expectation_sha256")

    def _validate_hashed_record(
        self,
        record: object,
        *,
        contract: str,
        identity: tuple[str, str],
    ) -> None:
        if not isinstance(record, dict) or record.get("contract_version") != contract:
            raise ActionLearningRecorderError("action learning record contract is invalid")
        if record.get(identity[0]) != identity[1]:
            raise ActionLearningRecorderError("action learning record identity is invalid")
        digest = _require_sha256(record.get("content_sha256"), "content_sha256")
        payload = dict(record)
        del payload["content_sha256"]
        if _sha256(payload) != digest:
            raise ActionLearningRecorderError("action learning record checksum mismatch")


__all__ = [
    "ActionLearningRecorder",
    "ActionLearningRecorderError",
]
