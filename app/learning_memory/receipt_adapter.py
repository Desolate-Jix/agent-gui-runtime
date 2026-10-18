"""只投影已经落盘的执行事实，不重新观察、不推断任务成功。"""
from copy import deepcopy
import hashlib
import json


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
               ("image_path", "sha256", "window_size", "capture_id", "frame_id", "observation_stage")
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


def project_receipt(request_id, response, receipt_path, ticket):
    command = response.get("command") or {}
    if content_hash(command) != ticket["command_sha256"]:
        raise ValueError("learning command binding mismatch")
    kind = command.get("kind")
    result = response.get("result") or {}
    event = {"contract_version": "instant_learning_event_v1",
             "learning_id": ticket["learning_id"], "session_id": ticket["session_id"],
             "request_id": request_id, "kind": kind, "operation": command.get("operation"),
             "target_before": deepcopy(ticket.get("target_before")),
             "receipt": {"path": str(receipt_path), "sha256": content_hash(response),
                         "hash_scope": "canonical_json"},
             "command_sha256": ticket["command_sha256"],
             "status": response.get("status"), "started_at": response.get("started_at"),
             "finished_at": response.get("finished_at"), "command_wall_ms": response.get("command_wall_ms"),
             "agent_review": {"status": "awaiting_agent_review", "verdict": None},
             "task_effect_verified": None, "automatic_retry_allowed": False,
             "before": {"status": "missing"},
             "after": _frame(response.get("observation")), "action_executed": None,
             "action_hints": {key: deepcopy(value) for key, value in (command.get("request") or {}).items()
                              if key in {"goal", "field_goal", "click_kind", "template_memory", "key", "keys", "direction", "wheel_clicks",
                                         "clear_existing", "submit_search"}},
             "steps": []}
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
    return event
