"""只在新公开请求采纳时补视觉声明，不改历史命令合同或执行器。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def needs_visual_input_default(command):
    request = command.get("request") or {}
    return (command.get("kind") == "input_sequence" and "field_evidence_mode" not in command
        and "target" not in request and "target_memory" not in request)


def learning_recording_enabled(session_directory):
    if session_directory is None:
        return False
    directory = Path(session_directory)
    if not (directory / "learning-memory" / "current.json").is_file():
        return False
    from app.learning_memory.event_store import LearningEventStore
    return LearningEventStore(directory).snapshot().get("recording_enabled") is True


def _new_input_command(request_id, command, *, learning_recording):
    value = deepcopy(command)
    request = value.get("request") or {}
    if (value.get("kind") != "input_sequence" or learning_recording
            or value.get("field_evidence_mode") == "legacy"
            or "target" in request or "target_memory" in request):
        return value
    from app.core.input_sequence_contract import InputSequenceRequest
    request = InputSequenceRequest.model_validate(request).model_dump(exclude_none=True)
    value["request"] = request
    value["field_evidence_mode"] = "visual"
    if "action_review" not in value:
        # 上下文仅描述同一输入动作，不创建业务结果条件或另一执行计划。
        digest = sha256(json.dumps({"request_id": request_id, "command": value},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        step_id = "input-" + digest[:24]
        value["action_review"] = {"schema": "action_review_context.v1",
            "run_id": "input-" + digest, "attempt_id": "input-attempt-" + digest,
            "step_id": step_id, "budget_ms": 60000, "plan": {
                "schema_version": "task_plan.v2", "title": "Current input action", "inputs": {},
                "steps": [{"step_id": step_id, "action": {"kind": "input_sequence", **deepcopy(request)},
                    "verification": {"kind": "agent_judgment"}}]}}
    return value


def adopt_public_input_command(request_id, command, *, existing_command=None, learning_recording=False):
    if existing_command is not None:
        # 旧票据先精确匹配；不把今天的缺省反写进昨天的动作事实。
        if existing_command == command:
            return deepcopy(existing_command)
        if existing_command == _new_input_command(request_id, command, learning_recording=False):
            return deepcopy(existing_command)
        raise ValueError("request_id already belongs to a different command")
    return _new_input_command(request_id, command, learning_recording=learning_recording)


def adopt_session_input_command(session, request_id, command):
    path = session._path(request_id, "commands")
    from app.core.json_snapshot import read_json_snapshot
    existing = read_json_snapshot(path) if path.is_file() else None
    return adopt_public_input_command(request_id, command, existing_command=existing,
        learning_recording=existing is None and needs_visual_input_default(command)
            and learning_recording_enabled(session.session))
