"""公开命令只携带声明；服务对象和共享截止时间由原宿主注入。"""
from copy import deepcopy
from time import perf_counter_ns

from .action_review import normalize_action_review_context, review_preflight, _digest


def build_input_review_options(coordinator, command, execution_request_id, *, deadline_ns=None, cancelled=None):
    context = normalize_action_review_context(command.get("action_review"))
    request = command.get("request") or {}
    mode = command.get("field_evidence_mode", "visual" if context is not None
        and "target" not in request and "target_memory" not in request else "legacy")
    if mode not in {"legacy", "visual"} or mode == "visual" and context is None:
        raise ValueError("visual_field_requires_action_review_context")
    if context is None:
        return {}
    deadline_ns = (perf_counter_ns() + context["budget_ms"] * 1_000_000 if deadline_ns is None else deadline_ns)
    if type(deadline_ns) is not int or deadline_ns <= 0:
        raise ValueError("action_review_deadline_invalid")
    result = {"action_review": context, "action_review_deadline_ns": deadline_ns}
    if mode == "legacy":
        return result
    # 在进入输入组合前拒绝不可用审核，保留明确的零输入事实。
    preflight = review_preflight(getattr(coordinator, "_decision_service", None))
    if not preflight["ready"]:
        raise ValueError(preflight["reason"])
    if type(execution_request_id) is not str or not execution_request_id:
        raise ValueError("visual_field_execution_id_required")
    if cancelled is not None and not callable(cancelled):
        raise ValueError("visual_field_cancel_predicate_invalid")
    if cancelled is None:
        def cancelled():
            event = getattr(coordinator, "_cancel_wait", None)
            return bool(getattr(coordinator, "_shutdown", False) or event is not None and event.is_set())
    steps = context["plan"]["steps"]
    index = next(i for i, row in enumerate(steps) if row["step_id"] == context["step_id"])
    step = steps[index]
    review_context = {"goal": context["plan"].get("goal", context["plan"]["title"]),
        "step_goal": step["action"]["field_goal"], "source_id": context["run_id"],
        "source_sha256": _digest(context["plan"]),
        "remaining_plan": [row["action"].get("field_goal", row["action"].get("goal")) for row in steps[index+1:]],
        "allowed_states": deepcopy(step["verification"].get("allowed_states", []))}
    if "review_policy" in step["verification"]:
        review_context["review_policy"] = step["verification"]["review_policy"]
    return {**result, "field_evidence_mode": "visual", "visual_field_context": {
        "service": getattr(coordinator, "_decision_service", None),
        "execution_request_id": execution_request_id, "deadline_ns": deadline_ns,
        "review_context": review_context,
        "field_kind": "search" if command["request"]["submit_search"] else "text",
        "native_field_evidence": False, "ocr_enabled": False,
        "cancelled": cancelled}}
