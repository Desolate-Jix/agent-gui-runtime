"""首次来源的 Agent 请求复用同一准备记录和占用状态。"""

from copy import deepcopy
import re
from uuid import uuid4

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_runtime_source import load_fresh_learning_runtime_source
from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters, text_parameter_reference
from app.agent.text_execution import text_execution_reference
from app.agent.scroll_parameters import ReviewedScrollParameters
from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from .fresh_runtime_callsite import FreshRuntimeSelection


FRESH_RUNTIME_CAPABILITY = {"contract_version": "agent_fresh_learning_runtime_v1", "operations": [
    "prepare_fresh_learning_runtime", "request_fresh_learning_action",
    "get_fresh_learning_runtime", "cancel_fresh_learning_runtime"]}


def _resolve_fresh_text_input(semantic_action, text_parameters, text_values):
    try:
        if semantic_action != "fill_field":
            if text_parameters is not None or text_values is not None:
                raise ValueError("non-text action cannot carry text inputs")
            return None
        declaration = ReviewedTextParameters.from_payload(text_parameters)
        if text_values is not None and type(text_values) is not dict:
            raise ValueError("text values must be an object")
        values = {} if text_values is None else text_values
        expected = {declaration.content.value} if declaration.content.kind == "variable" else set()
        if set(values) != expected or any(not isinstance(value, str) for value in values.values()):
            raise ValueError("text values must exactly match the declared source")
        return resolve_text_parameters(declaration, values)
    except (TypeError, ValueError):
        raise AgentLinkError("invalid_arguments", "fresh text declaration or required values are invalid") from None


def _resolve_fresh_scroll_parameters(semantic_action, scroll_parameters):
    try:
        if semantic_action != "scroll_region":
            if scroll_parameters is not None:
                raise ValueError("non-scroll action cannot carry scroll parameters")
            return None
        return ReviewedScrollParameters.from_payload(scroll_parameters).to_payload()
    except (TypeError, ValueError):
        raise AgentLinkError("invalid_arguments", "fresh reviewed scroll parameters are invalid") from None


class FreshLearningRuntimeMixin:
    def prepare_fresh(self, *, connection_id, task_id, segment_id, batch_id, idempotency_key):
        if not isinstance(idempotency_key, str) or re.fullmatch(r"[\x21-\x7e]{1,128}", idempotency_key) is None:
            raise AgentLinkError("invalid_arguments", "preparation idempotency key is invalid")
        binding = LearningRuntimeBinding(self.owner, connection_id, task_id, segment_id)
        try:
            source = load_fresh_learning_runtime_source(self._coordinator._host.fresh_learning,
                connection_id=connection_id, task_id=task_id, segment_id=segment_id, batch_id=batch_id)
        except (TypeError, ValueError, OSError) as error:
            raise AgentLinkError("learning_source_unavailable", "fresh committed source is unavailable") from error
        selection = FreshRuntimeSelection(source)
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
                "source_kind": "fresh_learning", "phase": "preparing", "cleanup_verified": False,
                "cancel_requested": False}
            self._records[preparation_id] = record
            self._requests[key] = preparation_id
            self._active = preparation_id
        try:
            result = self._coordinator.prepare_fresh(source=source, learning_binding=binding)
            with self._guard:
                record.update(phase=result["phase"], session_id=result["session_id"],
                              observation=deepcopy(result["observation"]))
        except Exception as error:
            from .single_step_coordinator import NativeSingleStepCoordinatorError

            # 仅公开已知前台等待原因，不泄露异常原文或未知内部错误码。
            code = (error.code if isinstance(error, NativeSingleStepCoordinatorError) and
                    error.code in {"foreground_wait_timeout", "foreground_wait_cancelled"}
                    else "runtime_prepare_failed")
            with self._guard:
                record.update(phase="failed", error_code=code)
        with self._guard:
            cancelled = record["cancel_requested"]
        scope = dict(connection_id=connection_id, task_id=task_id, segment_id=segment_id, preparation_id=preparation_id)
        return self.cancel_fresh(**scope) if cancelled else self.get_fresh(**scope)

    def _fresh_owned(self, connection_id, task_id, segment_id, preparation_id):
        record = self._owned(connection_id, task_id, segment_id, preparation_id)
        if record.get("source_kind") != "fresh_learning":
            raise AgentLinkError("not_found", "fresh learning preparation was not found")
        return record

    def get_fresh(self, *, connection_id, task_id, segment_id, preparation_id):
        self.owner.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        with self._guard:
            record = self._fresh_owned(connection_id, task_id, segment_id, preparation_id)
            self._refresh(record)
            binding = record["binding"]
            state = self._coordinator.learning_runtime_state()
            can_read = ("session_id" in record and not state["busy"] and
                        record["phase"] not in {"preparing", "cancelling"})
        if can_read:
            snapshot = self._coordinator.fresh_runtime_status(expected_learning_binding=binding)
            with self._guard:
                record["runtime_state"] = deepcopy(snapshot)
        with self._guard:
            return self._view(record)

    def request_fresh(self, *, connection_id, task_id, segment_id, preparation_id,
                      intent_id, action_id, semantic_action, goal, text_parameters=None, text_values=None,
                      learned_control=None, scroll_parameters=None):
        segment = self.owner.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        if segment["status"] != "active":
            raise AgentLinkError("learning_busy", "learning segment is not active")
        text_input = _resolve_fresh_text_input(semantic_action, text_parameters, text_values)
        text_reference = None if text_input is None else text_execution_reference(text_input)
        scroll_reference = _resolve_fresh_scroll_parameters(semantic_action, scroll_parameters)
        with self._guard:
            record = self._fresh_owned(connection_id, task_id, segment_id, preparation_id)
            self._refresh(record)
            observation = record.get("observation")
            if observation is None:
                raise AgentLinkError("learning_busy", "fresh preparation has no observation")
            try:
                intent_payload = {"contract_version": "fresh_learning_action_intent_v1",
                    "intent_id": intent_id, "action_id": action_id, "semantic_action": semantic_action, "goal": goal,
                    "session_id": record["session_id"], "observation_id": observation["observation_id"],
                    "source_sha256": record["selection"].source.reference()["source_sha256"]}
                if text_input is not None:
                    intent_payload["text_parameters_ref"] = text_parameter_reference(text_input.reviewed)
                if learned_control is not None:
                    from app.agent.learned_control_reference import resolve_learned_control
                    intent_payload['learned_control'] = resolve_learned_control(self._coordinator._host.fresh_learning,
                        record['selection'].source.reference(), learned_control)
                if scroll_reference is not None:
                    intent_payload["scroll_parameters"] = scroll_reference
                intent = FreshLearningIntent.from_dict(intent_payload).to_dict()
            except (TypeError, ValueError) as error:
                raise AgentLinkError("invalid_arguments", "fresh action intent is invalid") from error
            previous = record.get("intent")
            if previous is not None:
                if previous != intent or record.get("text_execution_ref") != text_reference:
                    raise AgentLinkError("idempotency_conflict", "fresh preparation already has another intent")
            else:
                if record["phase"] != "observed":
                    raise AgentLinkError("learning_busy", "fresh runtime is not ready for an intent")
                record["intent"] = intent
                if text_input is not None:
                    # 重试记录只保留摘要；准确原文仅传入同一所有者的本地预览。
                    record["text_execution_ref"] = text_reference
                record["phase"] = "requesting"
            binding = record["binding"]
        if previous is not None:
            # 离开记录锁后读取所有者事实；重试不重发预览或输入。
            return self.get_fresh(connection_id=connection_id, task_id=task_id, segment_id=segment_id,
                                  preparation_id=preparation_id)
        try:
            view = self._coordinator.request_fresh_review(intent=intent, expected_learning_binding=binding,
                **({"text_input": text_input} if text_input is not None else {}))
            with self._guard:
                record.update(phase="pending_review", confirmation_id=view["confirmation_id"])
        except Exception as error:
            with self._guard:
                record["error_code"] = "runtime_prepare_failed"
            raise AgentLinkError("runtime_prepare_failed", "fresh review preparation failed; inspect or cancel the same preparation") from error
        return self.get_fresh(connection_id=connection_id, task_id=task_id, segment_id=segment_id,
                              preparation_id=preparation_id)

    def cancel_fresh(self, *, connection_id, task_id, segment_id, preparation_id):
        self.owner.get(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        with self._guard:
            self._fresh_owned(connection_id, task_id, segment_id, preparation_id)
        self.cancel(connection_id=connection_id, task_id=task_id, segment_id=segment_id,
                    preparation_id=preparation_id)
        return self.get_fresh(connection_id=connection_id, task_id=task_id, segment_id=segment_id,
                              preparation_id=preparation_id)

    def _fresh_view(self, record):
        result = {"contract_version": "agent_fresh_learning_runtime_v1", "segment_id": record["binding"].segment_id,
            "preparation_id": record["preparation_id"], "phase": record["phase"],
            "cleanup_verified": record["cleanup_verified"], "cancellation_requested": record["cancel_requested"],
            "artifact_is_authorization": False, "operation_dispatches_input": False, "execution_ready": False}
        for key in ("session_id", "observation", "confirmation_id", "error_code"):
            if key in record:
                result[key] = deepcopy(record[key])
        if "runtime_state" in record:
            result.pop("observation", None)
            result.update(deepcopy(record["runtime_state"]))
        return result
