"""只投影已经落盘的执行事实，不重新观察、不推断任务成功。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from app.core.json_snapshot import read_json_snapshot


class ExecutionReceiptPending(ValueError):
    """异步执行尚未结束，不能固化为学习事件。"""


def resolve_execution_receipt(response, receipt_path, request_id, *, terminal_snapshot=None):
    result = response.get("result") or {}
    if result.get("contract_version") != "agent_command.v1":
        return response, None
    if result.get("command_id") != request_id:
        raise ValueError("learning async receipt identity mismatch")
    path = Path(receipt_path).parent.parent / "agent-commands" / (request_id + ".json")
    if terminal_snapshot is None and not path.is_file():
        raise ExecutionReceiptPending("awaiting_execution_result")
    terminal = read_json_snapshot(path) if terminal_snapshot is None else deepcopy(terminal_snapshot)
    if terminal.get("contract_version") != "agent_command.v1" or terminal.get("command_id") != request_id:
        raise ValueError("learning terminal receipt identity mismatch")
    if terminal.get("status") not in {"completed", "failed", "cancelled"}:
        raise ExecutionReceiptPending("awaiting_execution_result")
    effective = deepcopy(response)
    effective["result"] = deepcopy(terminal.get("result") or {})
    effective["observation"] = (terminal.get("observation") or {}).get("capture")
    effective["status"] = "returned" if terminal["status"] == "completed" else "failed"
    return effective, {"path": str(path), "sha256": content_hash(terminal),
                       "status": terminal["status"], "hash_scope": "canonical_json"}


RECORDED_KINDS = frozenset({"launch", "select", "maximize", "capture", "read_text",
                             "step", "input_sequence", "close_launched_window"})


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _frame(value):
    if not isinstance(value, dict) or not value.get("image_path"):
        return {"status": "missing"}
    # 这里只是原回执引用；未读取文件校验，不能宣称图像已验证。
    return {"status": "referenced", "bytes_verified": False,
            **{key: deepcopy(value[key]) for key in
               ("image_path", "sha256", "window_size", "capture_id", "frame_id", "observation_stage",
                "window_identity", "application", "window_rect")
               if key in value}}


def _step(value):
    api = value.get("response") or {}
    data = api.get("data") or {}
    action = data.get("result", data)
    dispatched = (action.get("execution_path") or {}).get("action_executed",
                  action.get("action_executed", action.get("pressed")))
    return {"phase": value.get("phase"),
            "action_executed": dispatched if type(dispatched) is bool else None,
            "before": _frame(value.get("capture")),
            "after": _frame((value.get("observation") or {}).get("capture"))}


def _target_observation(kind, result):
    if kind == "input_sequence":
        rows = result.get("steps", [])
        if not rows or rows[0].get("name") != "focus" or rows[0].get("operation") != "execute_recognition_plan":
            return None
        result = rows[0].get("receipt") or {}
    elif kind != "step":
        return None
    data = (result.get("response") or {}).get("data") or {}
    return data.get("result", data).get("learning_observation")


def target_observation_from_receipt(response, receipt_path, request_id):
    effective, _ = resolve_execution_receipt(response, receipt_path, request_id)
    return _target_observation((effective.get("command") or {}).get("kind"), effective.get("result") or {})


def project_receipt(request_id, response, receipt_path, ticket):
    original_hash = content_hash(response)
    response, terminal = resolve_execution_receipt(response, receipt_path, request_id)
    command = response.get("command") or {}
    if content_hash(command) != ticket["command_sha256"]:
        raise ValueError("learning command binding mismatch")
    kind = command.get("kind")
    result = response.get("result") or {}
    event = {"contract_version": "instant_learning_event_v1",
             "learning_id": ticket["learning_id"], "session_id": ticket["session_id"],
             "request_id": request_id, "kind": kind, "operation": command.get("operation"),
             "target_before": deepcopy(ticket.get("target_before")),
             "receipt": {"path": str(receipt_path), "sha256": original_hash,
                         "hash_scope": "canonical_json"},
             "command_sha256": ticket["command_sha256"],
             "status": response.get("status"), "started_at": response.get("started_at"),
             "finished_at": response.get("finished_at"), "command_wall_ms": response.get("command_wall_ms"),
             "agent_review": {"status": "awaiting_agent_review", "verdict": None},
             "task_effect_verified": None, "automatic_retry_allowed": False,
             "before": {"status": "missing"},
             "after": _frame(response.get("observation")), "action_executed": None,
             "action_hints": {key: deepcopy(value) for key, value in (command.get("request") or {}).items()
                              if key in {"goal", "field_goal", "click_kind", "template_memory", "target_memory", "key", "keys", "direction", "wheel_clicks",
                                         "clear_existing", "submit_search", "selection_intent"}
                              and (key != "selection_intent" or value is not None)},
             "steps": []}
    if terminal is not None:
        event["terminal_receipt"] = terminal
    if kind == "step":
        event.update(_step(result))
    elif kind == "input_sequence":
        event.update(sequence_status=result.get("status"), interrupted_at=result.get("interrupted_at"),
                     completed_steps=deepcopy(result.get("completed_steps", [])),
                     action_executed=result.get("action_executed"), before=_frame(result.get("capture")),
                     after=_frame((result.get("observation") or {}).get("capture")))
        for index, row in enumerate(result.get("steps", [])):
            event["steps"].append({"substep_id": f"{request_id}:{index}", "name": row.get("name"),
                "operation": row.get("operation"), "status": row.get("status"),
                **_step(row.get("receipt") or {}),
                "action_executed": row.get("action_executed"), "elapsed_ms": row.get("elapsed_ms")})
    # 保存文字的引用与摘要，而非把本次输入复制成永久界面知识。
    text = (command.get("request") or {}).get("text")
    if isinstance(text, str):
        event["input_text"] = {"length": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                               "value_stored_in": "original_local_receipt_only"}
    observation = _target_observation(kind, result)
    if observation is not None:
        if isinstance(observation, dict) and observation.get("status") == "unavailable":
            event["target_observation"] = deepcopy(observation)
        else:
            from .learning_observation_source import validate_learning_observation, learning_observation_reference
            frame = observation.get("frame") if isinstance(observation, dict) else None
            if not isinstance(frame, dict):
                raise ValueError("learning_observation_before_capture_invalid")
            # 原执行 API 的定位图才是候选来源；外层准备图仍保留在原回执中。
            event["before"] = _frame({**frame, "window_size": frame.get("image_size"),
                                      "frame_id": "before_input", "observation_stage": "before_input"})
            validated = validate_learning_observation(event, observation)
            event["target_observation"] = learning_observation_reference(validated)
    return event
