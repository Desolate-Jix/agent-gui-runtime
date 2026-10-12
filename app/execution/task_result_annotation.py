"""仅投影已验证普通单次点击的原回执，历史后验绑定不重新解释。"""
from copy import deepcopy
from pathlib import Path

from app.judgment.executed_click_annotation import executed_click_reference, executed_click_metadata
from .decision_check import decision_frame


def task_result_click_action(step, effective, frame):
    """调用方已验证原命令终态；缺少真实点击坐标的旧路线保持原义。"""
    action = step.get("action") or {}
    command = effective.get("command") or {}
    if (action.get("kind") != "click" or action.get("click_kind", "single") != "single"
            or command.get("kind") != "step" or command.get("operation") != "execute_recognition_plan"):
        return None
    receipt = effective.get("result") or {}
    if receipt.get("contract_version") != "local_direct_step_v1":
        return None
    invalid = "task_result_click_binding_invalid"
    if effective.get("status") != "returned" or (command.get("request") or {}).get("click_kind", "single") != "single":
        raise ValueError(invalid)
    api = receipt.get("response")
    if not isinstance(api, dict) or not isinstance(api.get("data"), dict):
        raise ValueError(invalid)
    data = api["data"]
    data = data.get("result", data)
    if not isinstance(data, dict):
        raise ValueError(invalid)
    click = data.get("click_result")
    if not isinstance(click, dict):
        raise ValueError(invalid)
    if not any(key in click for key in ("window_point", "screen_point", "down", "up", "click_events")):
        return None
    observation = receipt.get("observation")
    if (not isinstance(observation, dict) or observation.get("status") != "captured"
            or observation.get("source") != "post_action"
            or (receipt.get("request") or {}).get("click_kind", "single") != "single"):
        raise ValueError(invalid)
    after = observation.get("capture")
    observed = effective.get("observation")
    if (not isinstance(after, dict) or not isinstance(observed, dict) or frame.get("role") != "after"
            or any(after.get(key) != observed.get(key) for key in ("capture_id", "sha256", "image_path", "window_rect"))):
        raise ValueError(invalid)
    if decision_frame(after, frame.get("window_identity"), role="after") != frame:
        raise ValueError(invalid)
    rect = after.get("window_rect")
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(value) is not int for value in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]):
        raise ValueError(invalid)
    before = receipt.get("capture") or {}
    if (before.get("image_path") and Path(before["image_path"]).resolve() == Path(after["image_path"]).resolve()):
        raise ValueError(invalid)
    reference = executed_click_reference(receipt, {
        "click_point": deepcopy(click.get("window_point")),
        "window_identity": deepcopy(frame.get("window_identity")),
        "window_rect": [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]})
    if reference is None:
        return None
    if "click_events" in click:
        events = click["click_events"]
        if (not isinstance(events, list) or len(events) != 1 or not isinstance(events[0], dict)
                or type(events[0].get("index")) is not int or events[0]["index"] != 1
                or any(events[0].get(key) != click.get(key) for key in ("down", "up"))):
            raise ValueError(invalid)
    projected = {"operation": "step_result_check", "kind": "click",
        "input_receipt_sha256": reference["receipt_sha256"], "executed_click": reference}
    executed_click_metadata(frame, (rect[2] - rect[0], rect[3] - rect[1]), projected)
    return projected


def task_result_decision_binding(binding, action, *, saved_binding=None):
    """旧结果严格按原摘要认证；新请求必须保留真实点击，不能混用结果。"""
    current = {**deepcopy(binding), **({"action": deepcopy(action)} if action is not None else {})}
    if saved_binding is None:
        return current
    if saved_binding == current:
        return current
    if action is not None and saved_binding in (binding, {**binding, "action": None}):
        return deepcopy(saved_binding)
    raise ValueError("task_plan_decision_binding_changed")
