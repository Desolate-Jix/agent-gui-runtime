"""Agent 发起的原生准备入口；输入仍由既有协调器和独立审核控制。"""

from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import json
import re
from threading import RLock
from uuid import uuid4

from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from app.agent_link.learning_segments import LearningSegmentOwner
from .fresh_learning_runtime import FreshLearningRuntimeMixin


_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class LearningRuntimeProvider(FreshLearningRuntimeMixin):
    def __init__(self, owner: LearningSegmentOwner, coordinator) -> None:
        from .single_step_coordinator import NativeSingleStepCoordinator

        if not isinstance(owner, LearningSegmentOwner) or not isinstance(coordinator, NativeSingleStepCoordinator):
            raise TypeError("learning runtime requires the real owner and coordinator")
        if owner.recorder.project_root != coordinator._project_root:
            raise ValueError("learning owner and coordinator must share the project root")
        self.owner = owner
        self._coordinator = coordinator
        self._guard = RLock()
        self._records: dict[str, dict] = {}
        self._requests: dict[tuple, str] = {}
        self._active: str | None = None

    def prepare(self, *, connection_id, task_id, segment_id, idempotency_key,
                asset_id, asset_content_sha256, target_window_handle, target_process_id) -> dict:
        from .single_step_coordinator import _selection

        if not isinstance(idempotency_key, str) or re.fullmatch(r"[\x21-\x7e]{1,128}", idempotency_key) is None:
            raise AgentLinkError("invalid_arguments", "preparation idempotency key is invalid")
        try:
            selection = _selection(asset_id, asset_content_sha256, target_window_handle, target_process_id)
        except (TypeError, ValueError, RuntimeError):
            raise AgentLinkError("invalid_arguments", "runtime selection is invalid") from None
        binding = LearningRuntimeBinding(self.owner, connection_id, task_id, segment_id)
        key = (connection_id, task_id, segment_id, idempotency_key)
        with self._guard:
            previous = self._requests.get(key)
            if previous is not None:
                record = self._records[previous]
                if record["selection"] != selection:
                    raise AgentLinkError("idempotency_conflict", "preparation key has another selection")
                return self._view(record)
            if self._active is not None:
                self._refresh(self._records[self._active])
                if self._records[self._active]["phase"] not in {"cancelled", "released"}:
                    raise AgentLinkError("learning_busy", "finish the owned preparation before starting another")
            state = self._coordinator.learning_runtime_state()
            if state["busy"] or state["phase"] != "idle" or state["shutdown"]:
                raise AgentLinkError("learning_busy", "native runtime is not available for preparation")
            preparation_id = "preparation-" + uuid4().hex
            record = {"preparation_id": preparation_id, "binding": binding, "selection": selection,
                      "phase": "preparing", "cleanup_verified": False, "cancel_requested": False}
            self._records[preparation_id] = record
            self._requests[key] = preparation_id
            self._active = preparation_id
        # 模型准备可耗时；不持收件箱或入口锁，重复请求只读取同一记录。
        try:
            result = self._coordinator.prepare(
                asset_id=asset_id, asset_content_sha256=asset_content_sha256,
                target_window_handle=target_window_handle, target_process_id=target_process_id,
                learning_binding=binding,
            )
            with self._guard:
                record["phase"] = result["phase"]
                record["session_id"] = result["session_id"]
                record["actions"] = deepcopy(result["actions"])
        except Exception:
            with self._guard:
                record["phase"] = "failed"
                record["error_code"] = "runtime_prepare_failed"
        with self._guard:
            cancel_requested = record["cancel_requested"]
        if cancel_requested:
            return self.cancel(connection_id=connection_id, task_id=task_id,
                               segment_id=segment_id, preparation_id=preparation_id)
        with self._guard:
            return self._view(record)

    def request_reviewed_action(self, *, connection_id, task_id, segment_id, preparation_id,
                                intent_id, action_id, text_values=None) -> dict:
        self.owner.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        if (not isinstance(intent_id, str) or _STABLE_ID.fullmatch(intent_id) is None
                or not isinstance(action_id, str) or _STABLE_ID.fullmatch(action_id) is None):
            raise AgentLinkError("invalid_arguments", "reviewed action identity is invalid")
        if text_values is not None and (type(text_values) is not dict or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in text_values.items())):
            raise AgentLinkError("invalid_arguments", "reviewed text values are invalid")
        request = {"intent_id": intent_id, "action_id": action_id,
                   "text_values": deepcopy(text_values)}
        identity = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True,
                                              separators=(",", ":")).encode("utf-8")).hexdigest()
        with self._guard:
            record = self._owned(connection_id, task_id, segment_id, preparation_id)
            if record.get("source_kind") == "fresh_learning":
                raise AgentLinkError("not_found", "reviewed learning preparation was not found")
            if record.get("phase") != "observed":
                existing = record.get("reviewed_action")
                if existing is not None and existing["identity"] == identity:
                    return self._reviewed_action_view(record)
                raise AgentLinkError("idempotency_conflict", "reviewed action request conflicts with preparation")
            frozen = record.get("actions")
            matches = [item for item in frozen if isinstance(item, dict) and item.get("action_id") == action_id] \
                if isinstance(frozen, list) else []
            if len(matches) != 1:
                raise AgentLinkError("invalid_arguments", "reviewed action is not frozen in preparation")
            if matches[0].get("semantic_action") != "fill_field" and text_values:
                raise AgentLinkError("invalid_arguments", "reviewed action does not accept text values")
            existing = record.get("reviewed_action")
            if existing is not None:
                if existing["identity"] != identity:
                    raise AgentLinkError("idempotency_conflict", "reviewed action request conflicts with prior request")
                return self._reviewed_action_view(record)
            record["reviewed_action"] = {"identity": identity, **request, "phase": "requesting"}
        try:
            view = self._coordinator.request_review(action_id=action_id, text_values=deepcopy(text_values),
                                                    expected_learning_binding=record["binding"], intent_id=intent_id)
        except Exception as error:
            safe_invalid = (
                getattr(error, "code", None) == "text_input_invalid"
                and getattr(error, "result_unknown", False) is not True
            )
            with self._guard:
                current = record.get("reviewed_action")
                if isinstance(current, dict) and current.get("identity") == identity:
                    if record.get("phase") in {"cancelling", "cancelled", "released"}:
                        current["phase"] = "cancelled"
                    elif safe_invalid:
                        record.pop("reviewed_action", None)
                    else:
                        current["phase"] = "unknown"
            if safe_invalid:
                raise AgentLinkError("invalid_arguments", "reviewed text values are invalid") from None
            raise AgentLinkError("learning_source_unavailable", "native review request is unavailable") from error
        with self._guard:
            current = record.get("reviewed_action")
            if not isinstance(current, dict) or current.get("identity") != identity:
                raise AgentLinkError("idempotency_conflict", "reviewed action request identity changed")
            if record.get("phase") in {"cancelling", "cancelled", "released"}:
                current["phase"] = "cancelled"
                current.pop("confirmation_id", None)
                current.pop("observation_id", None)
                return self._reviewed_action_view(record)
            if record.get("phase") in {"cleanup_required", "failed"}:
                current["phase"] = "unknown"
                current.pop("confirmation_id", None)
                current.pop("observation_id", None)
                return self._reviewed_action_view(record)
            if record.get("phase") != "observed" or current.get("phase") != "requesting":
                raise AgentLinkError("learning_busy", "reviewed action request state changed")
            current.update({"phase": "pending_review", "confirmation_id": view["confirmation_id"],
                            "observation_id": view["preview"]["observation_id"]})
            record["phase"] = "pending_review"
            return self._reviewed_action_view(record)

    def get_reviewed_action_result(self, *, connection_id, task_id, segment_id, preparation_id) -> dict:
        with self._guard:
            record = self._owned(connection_id, task_id, segment_id, preparation_id)
            if record.get("source_kind") == "fresh_learning":
                raise AgentLinkError("not_found", "reviewed learning preparation was not found")
            request = record.get("reviewed_action")
            if request is None:
                raise AgentLinkError("not_found", "reviewed learning action was not requested")
            confirmation_id = request.get("confirmation_id")
        facts = self._durable_reviewed_result(
            connection_id=connection_id, task_id=task_id, segment_id=segment_id,
            record=record, confirmation_id=confirmation_id)
        with self._guard:
            # 每次都用当前持久证据投影，不缓存或复用旧终态。
            return self._reviewed_action_view(record, facts=facts)

    def get(self, *, connection_id, task_id, segment_id, preparation_id) -> dict:
        self.owner.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        with self._guard:
            record = self._owned(connection_id, task_id, segment_id, preparation_id)
            if record.get("source_kind") == "fresh_learning":
                raise AgentLinkError("not_found", "reviewed learning preparation was not found")
            return self._view(record)

    def cancel_reviewed(self, *, connection_id, task_id, segment_id, preparation_id):
        with self._guard:
            record = self._owned(connection_id, task_id, segment_id, preparation_id)
            if record.get("source_kind") == "fresh_learning":
                raise AgentLinkError("not_found", "reviewed learning preparation was not found")
        return self.cancel(connection_id=connection_id, task_id=task_id,
                           segment_id=segment_id, preparation_id=preparation_id)

    def cancel(self, *, connection_id, task_id, segment_id, preparation_id) -> dict:
        # Agent 入口仍检查撤销；可信宿主可按已保留的确切身份完成清理。
        with self._guard:
            record = self._owned(connection_id, task_id, segment_id, preparation_id)
            self._refresh(record)
            if record["phase"] in {"cancelled", "released"}:
                return self._view(record)
            if record["phase"] == "preparing":
                record["cancel_requested"] = True
                self._coordinator.cancel_waiting(expected_learning_binding=record["binding"])
                return self._view(record)
            if record["phase"] == "cancelling":
                return self._view(record)
            record["phase"] = "cancelling"
        try:
            proof = self._coordinator.cancel(expected_learning_binding=record["binding"])
            if proof.get("cleanup_verified") is not True:
                raise AgentLinkError("runtime_cleanup_pending", "runtime cleanup is not verified")
        except Exception:
            with self._guard:
                record["phase"] = "cleanup_required"
                record["error_code"] = "runtime_cleanup_pending"
            raise AgentLinkError("runtime_cleanup_pending", "runtime cleanup remains pending") from None
        with self._guard:
            record["phase"] = "cancelled"
            record["cleanup_verified"] = True
            record.pop("error_code", None)
            return self._view(record)

    def _durable_reviewed_result(self, *, connection_id, task_id, segment_id, record, confirmation_id):
        """只从已提交 claim/receipt 和所属学习归档生成事实投影。"""
        unavailable = {
            "claim_phase": "unknown",
            "receipt": {"status": "unavailable", "reason_code": "terminal_evidence_unavailable"},
            "after_observation": {"status": "unknown", "reason_code": "terminal_evidence_unavailable"},
        }
        if not isinstance(confirmation_id, str) or not confirmation_id:
            return unavailable
        try:
            from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
            from app.agent.runtime_receipt_store import RuntimeReceiptStore
            root = self.owner.recorder.project_root
            receipts = RuntimeReceiptStore(project_root=root, create_layout=False)
            claims = RuntimeIntentClaimStore(project_root=root, receipt_store=receipts, create_layout=False)
            snapshot, stored = claims.read_committed_terminal_evidence(
                session_id=record["session_id"], observation_id=record["reviewed_action"]["observation_id"])
            request = record["reviewed_action"]
            receipt = stored.runtime_receipt
            selection = record["selection"]
            grounded = snapshot.grounded_confirmation
            preview = None if grounded is None else grounded.preview.to_dict()
            frozen = [item for item in record.get("actions", [])
                      if isinstance(item, dict) and item.get("action_id") == request["action_id"]]
            available = [item for item in snapshot.observation.available_actions
                         if item.action_id == request["action_id"]]
            if (
                snapshot.phase != "terminal"
                or snapshot.observation.session_id != record["session_id"]
                or snapshot.observation.observation_id != request["observation_id"]
                or snapshot.intent.session_id != record["session_id"]
                or snapshot.intent.observation_id != request["observation_id"]
                or snapshot.intent.intent_id != request["intent_id"]
                or snapshot.intent.action_id != request["action_id"]
                or receipt.session_id != record["session_id"]
                or receipt.observation_id != request["observation_id"]
                or receipt.intent_id != request["intent_id"]
                or receipt.action.action_id != request["action_id"]
                or grounded is None
                or grounded.confirmation_id != confirmation_id
                or not isinstance(preview, dict)
                or preview.get("session_id") != record["session_id"]
                or preview.get("observation_id") != request["observation_id"]
                or preview.get("intent_id") != request["intent_id"]
                or preview.get("target_window_handle") != selection.target_window_handle
                or preview.get("target_process_id") != selection.target_process_id
                or snapshot.server_binding.asset_id != selection.asset_id
                or snapshot.server_binding.target_window_handle != selection.target_window_handle
                or snapshot.observation.workflow.asset_id != selection.asset_id
                or snapshot.observation.workflow.asset_content_sha256 != selection.asset_content_sha256
                or receipt.workflow != snapshot.observation.workflow
                or len(frozen) != 1
                or len(available) != 1
                or frozen[0].get("semantic_action") != available[0].semantic_action
                or frozen[0].get("target") != available[0].target_state_id
                or receipt.action.semantic_action != available[0].semantic_action
            ):
                return unavailable
            segment = self.owner._segment_snapshot(connection_id, task_id, segment_id)
            children = [item for item in segment["children"] if item["runtime_session_id"] == record["session_id"]]
            if len(children) != 1:
                return unavailable
            session = self.owner.recorder.get_learning_session(
                learning_session_id=children[0]["learning_session_id"])
            if (session.get("runtime_session_id") != record["session_id"]
                    or type(session.get("revision")) is not int):
                return unavailable
            evidence = self.owner.capture_archive.read_session_evidence(
                learning_session_id=children[0]["learning_session_id"], runtime_session_id=record["session_id"],
                expected_revision=session["revision"])
            archive = evidence.evidence()
            events = archive["events"]
            matched = [(event_id, event) for event_id, event in events.items()
                       if event.get("terminal", {}).get("receipt_id") == receipt.receipt_id]
            if len(matched) != 1:
                return unavailable
            event_id, event = matched[0]
            terminal = event.get("terminal")
            runtime = event.get("runtime")
            if (
                not isinstance(terminal, dict)
                or not isinstance(runtime, dict)
                or runtime.get("session_id") != record["session_id"]
                or runtime.get("observation_id") != request["observation_id"]
                or terminal.get("receipt_content_sha256") != stored.content_sha256
                or terminal.get("intent_id") != request["intent_id"]
                or terminal.get("action") != receipt.action.model_dump(mode="json", exclude_none=True)
            ):
                return unavailable
            receipt_view = {
                "status": "available", "receipt_id": receipt.receipt_id,
                "content_sha256": stored.content_sha256, "outcome": receipt.outcome,
                "reason_code": receipt.reason_code, "attempt_count": receipt.attempt_count,
                "dispatch_status": receipt.dispatch_status, "effect_status": receipt.effect_status,
                "destination_status": receipt.destination_status,
                "artifact_is_authorization": False,
            }
            source = next((item for item in archive["event_sources"] if item["event_id"] == event_id), None)
            after = None if source is None else source.get("after")
            next_observation = stored.next_observation
            current_capture = None if next_observation is None else next_observation.current_capture
            after_ref = terminal.get("next_observation_ref")
            if (
                not isinstance(after_ref, dict)
                or current_capture is None
                or receipt.next_observation_id != next_observation.observation_id
                or after_ref.get("observation_id") != next_observation.observation_id
                or after_ref.get("capture_id") != current_capture.capture_id
                or after_ref.get("screenshot_sha256") != current_capture.screenshot_sha256
            ):
                return {"claim_phase": "terminal", "receipt": receipt_view,
                        "after_observation": {"status": "unavailable", "reason_code": "after_identity_unavailable"}}
            pngs = dict(evidence.png_by_sha256)
            if not isinstance(after, dict) or after.get("status") != "available":
                return {"claim_phase": "terminal", "receipt": receipt_view,
                        "after_observation": {"status": "unavailable", "reason_code": "after_image_unavailable"}}
            digest = after.get("screenshot_sha256")
            metadata = after.get("metadata")
            png = pngs.get(digest)
            if (
                not isinstance(digest, str)
                or digest != current_capture.screenshot_sha256
                or not isinstance(metadata, dict)
                or metadata.get("learning_session_id") != children[0]["learning_session_id"]
                or metadata.get("runtime_session_id") != record["session_id"]
                or metadata.get("capture_id") != current_capture.capture_id
                or metadata.get("screenshot_sha256") != digest
                or metadata.get("asset_content_sha256") != selection.asset_content_sha256
                or metadata.get("target_window_handle") != selection.target_window_handle
                or metadata.get("target_process_id") != selection.target_process_id
                or not isinstance(png, bytes)
                or hashlib.sha256(png).hexdigest() != digest
            ):
                return {"claim_phase": "terminal", "receipt": receipt_view,
                        "after_observation": {"status": "unavailable", "reason_code": "after_image_unavailable"}}
            viewport = metadata.get("viewport_size")
            if not isinstance(viewport, dict):
                return {"claim_phase": "terminal", "receipt": receipt_view,
                        "after_observation": {"status": "unavailable", "reason_code": "after_image_unavailable"}}
            return {"claim_phase": "terminal", "receipt": receipt_view,
                    "after_observation": {"status": "available", "observation_id": next_observation.observation_id,
                    "capture_id": current_capture.capture_id, "screenshot": {
                        "mime_type": "image/png", "sha256": digest,
                        "width": viewport.get("width"), "height": viewport.get("height"),
                        "png_base64": base64.b64encode(png).decode("ascii")}}}
        except Exception:
            return unavailable

    def _reviewed_action_view(self, record, *, facts=None):
        request = record.get("reviewed_action")
        if not isinstance(request, dict):
            raise AgentLinkError("not_found", "reviewed learning action was not requested")
        result = {"contract_version": "agent_reviewed_learning_action_v1",
                  "segment_id": record["binding"].segment_id,
                  "preparation_id": record["preparation_id"],
                  "intent_id": request["intent_id"], "action_id": request["action_id"],
                  "phase": request["phase"] if facts is None else facts["claim_phase"],
                  "claim_phase": request["phase"] if facts is None else facts["claim_phase"],
                  "artifact_is_authorization": False,
                  "operation_dispatches_input": False, "execution_ready": False}
        if isinstance(request.get("confirmation_id"), str):
            result["confirmation_id"] = request["confirmation_id"]
        result["receipt"] = deepcopy(
            {"status": "unavailable", "reason_code": "not_read"}
            if facts is None else facts["receipt"])
        result["after_observation"] = deepcopy(
            {"status": "unavailable", "reason_code": "not_read"}
            if facts is None else facts["after_observation"])
        return result

    def _owned(self, connection_id, task_id, segment_id, preparation_id):
        if not isinstance(preparation_id, str):
            raise AgentLinkError("invalid_arguments", "preparation identity is invalid")
        record = self._records.get(preparation_id)
        binding = None if record is None else record["binding"]
        if binding is None or (binding.connection_id, binding.task_id, binding.segment_id) != (connection_id, task_id, segment_id):
            raise AgentLinkError("not_found", "learning preparation was not found")
        return record

    def _refresh(self, record):
        if record["phase"] in {"preparing", "cancelling", "cancelled", "released"}:
            return
        state = self._coordinator.learning_runtime_state()
        if state["binding"] is record["binding"]:
            if state["phase"] != "idle" and record["phase"] not in {"failed", "cleanup_required"}:
                record["phase"] = state["phase"]
        elif state["phase"] == "idle" and not state["busy"]:
            record["phase"] = "released"
            record["cleanup_verified"] = True

    def _view(self, record):
        self._refresh(record)
        if record.get("source_kind") == "fresh_learning":
            return self._fresh_view(record)
        result = {"contract_version": "agent_learning_runtime_v1",
                  "segment_id": record["binding"].segment_id,
                  "preparation_id": record["preparation_id"], "phase": record["phase"],
                  "cleanup_verified": record["cleanup_verified"],
                  "cancellation_requested": record["cancel_requested"],
                  "artifact_is_authorization": False, "execute_binding_enabled": False,
                  "action_executed": False}
        for key in ("session_id", "actions", "error_code"):
            if key in record:
                result[key] = deepcopy(record[key])
        return result
