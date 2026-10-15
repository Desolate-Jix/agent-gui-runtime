"""核验宿主原序列的已知中断，不推断效果成功或授予恢复输入。"""
from hashlib import sha256
import json
from math import isfinite

from .receipt_action import _receipt_action
from .visual_typing_strategy import validated_effective_typing_request


PROOF_FIELD = "partial_input_terminal"


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _request(value):
    from .input_sequence_contract import InputSequenceRequest
    return InputSequenceRequest.model_validate(value).model_dump(mode="json")


def _identity(value):
    if not isinstance(value, dict):
        return None
    handle, pid, born = (value.get(key) for key in
        ("target_window_handle", "process_id", "process_create_time"))
    if (type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0
            or type(born) not in (int, float) or born <= 0 or not isfinite(born)):
        return None
    return {"handle": handle, "process_id": pid, "process_create_time": born}


def _expected_proof(result, request):
    if (not isinstance(result, dict) or result.get("contract_version") != "input_sequence_v1"
            or result.get("status") != "interrupted" or result.get("phase") != "check_focus"
            or result.get("interrupted_at") != "check_focus" or result.get("action_executed") is not True
            or result.get("completed_steps") != ["focus"] or result.get("automatic_retry_allowed") is not False
            or result.get("task_effect_verified") is not None
            or not isinstance(result.get("sequence_id"), str) or not result["sequence_id"]):
        return None
    error, check, rows = result.get("error"), result.get("input_check"), result.get("steps")
    if (not isinstance(error, dict)
            or not isinstance(error.get("code"), str) or not error["code"].strip() or len(error["code"]) > 256
            or not isinstance(check, dict) or check.get("status") != "unavailable"
            or check.get("phase") != "check_focus" or check.get("reason") != error["code"]
            or not isinstance(rows, list) or len(rows) != 1):
        return None
    visual = (error.get("type") == "InputSequenceInterrupted" and set(error) == {"code", "type"}
        and set(check) == {"status", "phase", "reason", "evidence_kind", "focus_stage", "read_only_stage"}
        and check.get("evidence_kind") == "visual" and check.get("focus_stage") == "after_click"
        and check.get("read_only_stage") in {"after_click_observation", "after_click_assessment", "field_content_ocr"})
    if not visual and error.get("type") != "TextFieldReadError":
        return None
    row = rows[0]
    if (not isinstance(row, dict) or row.get("name") != "focus"
            or row.get("operation") != "execute_recognition_plan"
            or row.get("status") != "returned" or row.get("action_executed") is not True):
        return None
    local = row.get("receipt")
    if (not isinstance(local, dict) or local.get("contract_version") != "local_direct_step_v1"
            or local.get("operation") != "execute_recognition_plan" or local.get("phase") != "returned"
            or local.get("local_input_scope_closed") is not True
            or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
            or "action_executed" in local and local["action_executed"] is not True):
        return None
    api = local.get("response")
    data = api.get("data") if isinstance(api, dict) else None
    if not isinstance(api, dict) or api.get("success") is not True or not isinstance(data, dict):
        return None
    data = data.get("result", data)
    if not isinstance(data, dict):
        return None
    click, agent, path = data.get("click_result"), data.get("agent_step_result"), data.get("execution_path")
    if (not isinstance(click, dict) or click.get("clicked") is not True
            or not isinstance(path, dict) or path.get("action_executed") is not True
            or _receipt_action(local, "execute_recognition_plan") is not True
            or "action_executed" in data and data["action_executed"] is not True
            or agent is not None and (not isinstance(agent, dict) or agent.get("action_executed") is not True)):
        return None
    target, identity, local_request = result.get("target"), _identity(local.get("target_identity")), local.get("request")
    if (identity is None or not isinstance(target, dict) or type(target.get("handle")) is not int
            or type(target.get("process_id")) is not int or target.get("handle") != identity["handle"]
            or target.get("process_id") != identity["process_id"] or not isinstance(local_request, dict)
            or local_request.get("goal") != request["field_goal"]):
        return None
    if (result.get("text_sha256") != sha256(request["text"].encode("utf-8")).hexdigest()
            or result.get("text_length") != len(request["text"])
            or result.get("submit_search") is not request["submit_search"]):
        return None
    return {"contract_version": "input_sequence_focus_partial.v2" if visual else "input_sequence_focus_partial.v1",
        "sequence_id": result["sequence_id"],
        "request_sha256": _digest(request), "focus_receipt_sha256": _digest(local),
        "target_identity": identity, "read_phase": "check_focus", "reason_code": error["code"],
        **({"read_only_stage": check["read_only_stage"]} if visual else {}),
        "started_actions": ["focus"], "suffix_dispatch_started": False, "read_only_failure": True}


def make_focus_partial_proof(result, request, *, started_actions, read_only_stage=None):
    """生产端仅在真实只读异常分支调用；派发前沿来自闭包内部，不接受请求元数据。"""
    if started_actions != ["focus"]:
        return None
    try:
        proof = _expected_proof(result, _request(request))
        if proof is not None and proof.get("read_only_stage") == read_only_stage:
            return proof
        return None
    except (ValueError, TypeError, OverflowError):
        return None


def focus_only_partial_verified(receipt, command, *, target_identity=None):
    """只读取已绑定的原命令/回执；调用方仍须核对 source、owner、票据及文件摘要。"""
    # 异步宿主将已落盘的失败终态投影为 failed；输入事实仍须完整原证明。
    if (not isinstance(receipt, dict) or receipt.get("status") not in ("returned", "failed")
            or receipt.get("command") != command or not isinstance(command, dict)
            or command.get("kind") != "input_sequence"):
        return False
    result = receipt.get("result")
    if not isinstance(result, dict) or not isinstance(result.get(PROOF_FIELD), dict):
        return False
    try:
        expected = _expected_proof(result, _request(command.get("request")))
    except (ValueError, TypeError, OverflowError):
        return False
    try:
        return (expected is not None and _digest(result[PROOF_FIELD]) == _digest(expected)
            and (target_identity is None or expected["target_identity"] == target_identity))
    except (ValueError, TypeError, OverflowError):
        return False


def _completed_type(local, request, text_digest, identity):
    api = local.get("response")
    data = api.get("data") if isinstance(api, dict) else None
    if not isinstance(api, dict) or api.get("success") is not True or not isinstance(data, dict):
        return False
    data = data.get("result", data)
    typed = data.get("type_result") if isinstance(data, dict) else None
    audited = local.get("request")
    if (not isinstance(typed, dict) or typed.get("typed") is not True
            or typed.get("window_handle") != identity["handle"]
            or typed.get("text_length") != len(request["text"])
            or typed.get("clear_existing") is not request["clear_existing"]
            or typed.get("click_before_typing") is not False or typed.get("submit") is not False
            or not isinstance(audited, dict) or audited.get("text_sha256") != text_digest
            or audited.get("text_length") != len(request["text"])
            or audited.get("clear_existing") is not request["clear_existing"]
            or audited.get("click_before_typing") is not False or audited.get("submit") is not False):
        return False
    dispatch = typed.get("typing_dispatch")
    if (not isinstance(dispatch, dict) or dispatch.get("schema") != "typing_dispatch.v1"
            or dispatch.get("focus_dispatch") != "not_started"
            or dispatch.get("selection_dispatch") != ("completed" if request["clear_existing"] else "not_started")
            or dispatch.get("text_dispatch") != "completed" or dispatch.get("submit_dispatch") != "not_started"
            or dispatch.get("input_started") is not True or dispatch.get("action_executed") is not True
            or dispatch.get("artifact_is_authorization") is not False):
        return False
    events = dispatch.get("events")
    expected = [(phase, state) for phase in (["selection", "text"] if request["clear_existing"] else ["text"])
        for state in ("started", "completed")]
    if not isinstance(events, list) or len(events) != len(expected):
        return False
    previous = 0
    for event, (phase, state) in zip(events, expected):
        elapsed = event.get("elapsed_ms") if isinstance(event, dict) else None
        if (not isinstance(event, dict) or event.get("phase") != phase or event.get("status") != state
                or type(elapsed) not in (int, float) or not isfinite(elapsed) or elapsed < previous):
            return False
        previous = elapsed
    return True


def _compound_input_fact(result, request, target_identity=None, *, allow_unknown_row=False):
    """核对同一原回执中的点击与键入前沿，不创建独立键入回执。"""
    from app.agent.native_identity import validate_native_identity_fact
    rows = result.get("steps")
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    local = row.get("receipt") if isinstance(row, dict) else None
    if (not isinstance(row, dict) or row.get("name") != "focus_type" or row.get("operation") != "execute_recognition_plan"
            or row.get("action_executed") is not True or not isinstance(local, dict)
            or local.get("contract_version") != "local_direct_step_v1"
            or local.get("operation") != "execute_recognition_plan"
            or (row.get("status") != local.get("phase") and not (allow_unknown_row
                and row.get("status") == "result_unknown" and local.get("phase") == "returned"))
            or local.get("phase") not in {"returned", "result_unknown"}
            or local.get("local_input_scope_closed") is not True
            or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
            or not isinstance(local.get("step_id"), str) or not local["step_id"]
            or "action_executed" in local and local["action_executed"] is not True):
        return None
    identity = _identity(local.get("target_identity"))
    target = result.get("target")
    native = (validate_native_identity_fact(local.get("target_identity"),
        target_window_handle=identity["handle"], expected_process_id=identity["process_id"]) if identity else None)
    if (identity is None or native is None
            or target_identity is not None and identity != target_identity
            or not isinstance(target, dict) or target.get("handle") != identity["handle"]
            or target.get("process_id") != identity["process_id"]
            or not isinstance(local.get("request"), dict) or local["request"].get("goal") != request["field_goal"]):
        return None
    api = local.get("response")
    data = api.get("data") if isinstance(api, dict) else None
    data = data.get("result", data) if isinstance(data, dict) else None
    if not isinstance(data, dict) or _receipt_action(local, "execute_recognition_plan") is not True:
        return None
    fact, click, path = data.get("visual_compound_input"), data.get("click_result"), data.get("execution_path")
    digest = sha256(request["text"].encode("utf-8")).hexdigest()
    if (not isinstance(fact, dict) or fact.get("schema") != "visual_compound_input.v1"
            or fact.get("text_sha256") != digest or fact.get("text_length") != len(request["text"])
            or fact.get("clear_existing") is not True or request["clear_existing"] is not True
            or fact.get("submit") is not False
            or fact.get("window_identity") != identity
            or not isinstance(fact.get("execution_request_id"), str) or not fact["execution_request_id"]
            or not isinstance(path, dict) or path.get("action_executed") is not True
            or "action_executed" in data and data["action_executed"] is not True
            or not isinstance(click, dict) or click.get("clicked") is not True
            or click.get("window_handle") != identity["handle"] or click.get("window_point") != fact.get("point")
            or fact.get("click_result_sha256") != _digest(click)):
        return None
    rect, point = fact.get("window_rect"), fact.get("point")
    geometry = local.get("target_window_geometry") or {}
    if (not isinstance(rect, list) or len(rect) != 4 or any(type(value) is not int for value in rect)
            or geometry.get("coordinate_space") != "screen_pixels" or geometry.get("rect_format") != "ltrb"
            or geometry.get("rect") != rect
            or rect[0] >= rect[2] or rect[1] >= rect[3] or not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(point[key]) is not int for key in point)
            or not 0 <= point["x"] < rect[2] - rect[0] or not 0 <= point["y"] < rect[3] - rect[1]):
        return None
    dispatch = fact.get("typing_dispatch")
    if (not isinstance(dispatch, dict) or dispatch.get("schema") != "typing_dispatch.v1"
            or dispatch.get("focus_dispatch") != "not_started" or dispatch.get("submit_dispatch") != "not_started"
            or dispatch.get("artifact_is_authorization") is not False):
        return None
    selection, text = dispatch.get("selection_dispatch"), dispatch.get("text_dispatch")
    if (selection, text) not in {("not_started", "not_started"), ("completed", "not_started"), ("completed", "completed")}:
        return None
    phases = ([] if selection == "not_started" else ["selection"]) + ([] if text == "not_started" else ["text"])
    expected = [(phase, state) for phase in phases for state in ("started", "completed")]
    events = dispatch.get("events")
    if (dispatch.get("input_started") is not bool(phases) or dispatch.get("action_executed") is not bool(phases)
            or not isinstance(events, list) or len(events) != len(expected)):
        return None
    previous = 0
    for event, (phase, state) in zip(events, expected):
        elapsed = event.get("elapsed_ms") if isinstance(event, dict) else None
        if (not isinstance(event, dict) or set(event) != {"phase", "status", "elapsed_ms"}
                or event.get("phase") != phase or event.get("status") != state
                or type(elapsed) not in (int, float) or not isfinite(elapsed) or elapsed < previous):
            return None
        previous = elapsed
    typed = fact.get("type_result")
    completed = text == "completed"
    if completed:
        if (local["phase"] != "returned" or api.get("success") is not True or not isinstance(typed, dict)
                or typed.get("typed") is not True or typed.get("window_handle") != identity["handle"]
                or typed.get("text_length") != len(request["text"]) or typed.get("clear_existing") is not True
                or typed.get("click_before_typing") is not False or typed.get("submit") is not False
                or typed.get("typing_dispatch") != dispatch):
            return None
    elif (local["phase"] != "result_unknown" or api.get("success") is not False or typed is not None):
        return None
    return {"receipt": local, "fact": fact, "identity": identity, "native": native, "completed": completed}


def _visual_submit_status(row, fact, request, result):
    """新点击与按键各自结算；原回执之外的标志不能证明 Enter 已派发。"""
    from app.agent.native_identity import validate_native_identity_fact
    from .recognition_dispatch import local_receipt_zero_input_verified
    local = row.get("receipt") or {}
    identity = fact["identity"]
    if (row.get("name") != "search" or row.get("operation") != "execute_recognition_plan"
            or local.get("operation") != "execute_recognition_plan"
            or local.get("contract_version") != "local_direct_step_v1"
            or row.get("status") != local.get("phase") or local.get("local_input_scope_closed") is not True
            or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
            or not isinstance(local.get("step_id"), str) or not local["step_id"]
            or local["step_id"] == fact["receipt"]["step_id"]
            or (local.get("request") or {}).get("goal") != request["field_goal"]
            or (local.get("request") or {}).get("click_kind") != "single"
            or _identity(local.get("target_identity")) != identity
            or validate_native_identity_fact(local.get("target_identity"), target_window_handle=identity["handle"],
                expected_process_id=identity["process_id"]) != fact["native"]):
        return "unknown"
    if row.get("action_executed") is False:
        return "failed" if local_receipt_zero_input_verified(local, "execute_recognition_plan") else "unknown"
    api = local.get("response") or {}
    data = api.get("data") or {}
    data = data.get("result", data)
    submit, click = data.get("visual_submit"), data.get("click_result")
    proofs = result.get("field_proofs") or []
    proof = proofs[-1] if proofs else {}
    field = proof.get("field") or {}
    original = fact["fact"]
    if (row.get("action_executed") is not True or _receipt_action(local, "execute_recognition_plan") is not True
            or not isinstance(submit, dict) or submit.get("schema") != "visual_submit.v1"
            or submit.get("input_receipt_sha256") != _digest(fact["receipt"])
            or submit.get("window_identity") != identity or submit.get("point") != original["point"]
            or submit.get("window_rect") != original["window_rect"]
            or (local.get("target_window_geometry") or {}).get("rect") != original["window_rect"]
            or submit.get("execution_request_id") != original["execution_request_id"]
            or submit.get("field_goal") != request["field_goal"]
            or proof.get("schema") != "visual_field_proof.v1" or proof.get("phase") != "value"
            or proof.get("input_receipt_sha256") != submit["input_receipt_sha256"]
            or proof.get("focus_receipt_sha256") != submit["input_receipt_sha256"]
            or proof.get("request_sha256") != submit.get("value_request_sha256")
            or field.get("expected_text") != request["text"] or field.get("field_goal") != request["field_goal"]
            or field.get("window_identity") != identity or field.get("click_point") != original["point"]
            or not isinstance(click, dict) or click.get("clicked") is not True
            or click.get("window_handle") != identity["handle"] or click.get("window_point") != original["point"]
            or submit.get("click_result_sha256") != _digest(click)):
        return "unknown"
    dispatch = submit.get("key_dispatch")
    if (not isinstance(dispatch, dict) or dispatch.get("schema") != "key_dispatch.v1"
            or dispatch.get("key") != "Enter" or dispatch.get("point") != original["point"]
            or dispatch.get("artifact_is_authorization") is not False):
        return "unknown"
    state = dispatch.get("dispatch")
    events = dispatch.get("events")
    key = submit.get("key_result")
    if state == "not_started":
        return "failed" if (dispatch.get("input_started") is False and dispatch.get("action_executed") is False
            and events == [] and key is None and local.get("phase") == "result_unknown"
            and api.get("success") is False) else "unknown"
    if (state != "completed" or dispatch.get("input_started") is not True
            or dispatch.get("action_executed") is not True or not isinstance(events, list) or len(events) != 2
            or not isinstance(key, dict) or key.get("pressed") is not True or key.get("key") != "Enter"
            or key.get("window_handle") != identity["handle"] or key.get("text_retyped") is not False
            or key.get("key_dispatch") != dispatch or local.get("phase") != "returned" or api.get("success") is not True):
        return "unknown"
    previous = 0
    for event, expected in zip(events, ("started", "completed")):
        elapsed = event.get("elapsed_ms") if isinstance(event, dict) else None
        if (not isinstance(event, dict) or set(event) != {"status", "elapsed_ms"} or event.get("status") != expected
                or type(elapsed) not in (int, float) or not isfinite(elapsed) or elapsed < previous):
            return "unknown"
        previous = elapsed
    return "completed"


def _compound_search_receipt(row, fact, *, executed, request=None, result=None):
    if row.get("operation") == "execute_recognition_plan":
        return _visual_submit_status(row, fact, request, result) == ("completed" if executed else "failed")
    from app.agent.native_identity import validate_native_identity_fact
    from .recognition_dispatch import local_receipt_zero_input_verified
    local = row.get("receipt") or {}
    phase = "returned" if executed else "not_dispatched"
    identity = fact["identity"]
    return (row.get("name") == "search" and row.get("operation") == local.get("operation") == "press_key"
        and local.get("contract_version") == "local_direct_step_v1"
        and row.get("status") == local.get("phase") == phase and row.get("action_executed") is executed
        and local.get("local_input_scope_closed") is True and isinstance(local.get("finished_at"), str)
        and bool(local["finished_at"]) and isinstance(local.get("step_id"), str) and bool(local["step_id"])
        and local["step_id"] != fact["receipt"]["step_id"] and (local.get("request") or {}).get("key") == "Enter"
        and _identity(local.get("target_identity")) == identity
        and validate_native_identity_fact(local.get("target_identity"), target_window_handle=identity["handle"],
            expected_process_id=identity["process_id"]) == fact["native"]
        and (_receipt_action(local, "press_key") is True if executed else local_receipt_zero_input_verified(local, "press_key")))


def _compound_input_status(receipt, command, *, succeeded, action_executed, target_identity=None):
    """复合动作失败只在派发前沿明确关闭时结算；未知文字或按键仍持有票据。"""
    from .recognition_dispatch import local_receipt_zero_input_verified
    try:
        request, result = _request(command.get("request")), receipt["result"]
        rows = result["steps"]
        if (receipt.get("status") not in {"returned", "failed"} or receipt.get("command") != command
                or command.get("kind") != "input_sequence" or result.get("contract_version") != "input_sequence_v1"
                or result.get("automatic_retry_allowed") is not False or result.get("task_effect_verified") is not None
                or not isinstance(result.get("sequence_id"), str) or not result["sequence_id"]
                or result.get("text_sha256") != sha256(request["text"].encode("utf-8")).hexdigest()
                or result.get("text_length") != len(request["text"]) or result.get("submit_search") is not request["submit_search"]
                or {"typing_strategy", "typing_strategy_evidence", PROOF_FIELD} & result.keys()):
            return "unknown"
        if action_executed is False:
            local = rows[0]["receipt"]
            return "failed" if (not succeeded and len(rows) == 1 and result.get("status") == "interrupted"
                and result.get("phase") == result.get("interrupted_at") == "focus_type"
                and result.get("action_executed") is False and result.get("completed_steps") == []
                and rows[0].get("action_executed") is False
                and rows[0].get("name") == "focus_type" and rows[0].get("operation") == "execute_recognition_plan"
                and rows[0].get("status") == local.get("phase")
                and (local.get("request") or {}).get("goal") == request["field_goal"]
                and local_receipt_zero_input_verified(local, "execute_recognition_plan")
                and (target_identity is None or _identity(local.get("target_identity")) == target_identity)) else "unknown"
        fact = _compound_input_fact(result, request, target_identity)
        if action_executed is not True or result.get("action_executed") is not True or fact is None:
            return "unknown"
        phase, completed = result.get("phase"), result.get("completed_steps")
        check = result.get("input_check")
        verified = {"status": "verified", "source": "decision_visual", "evidence_kind": "visual"}
        if succeeded:
            expected_steps = ["focus_type", "check_input"] + (["search"] if request["submit_search"] else [])
            if (not fact["completed"] or result.get("status") != "completed" or completed != expected_steps
                    or check != verified or len(rows) != (2 if request["submit_search"] else 1)):
                return "unknown"
            if request["submit_search"]:
                if not _compound_search_receipt(rows[1], fact, executed=True, request=request, result=result):
                    return "unknown"
            return "completed"
        error = result.get("error")
        if (result.get("status") != "interrupted" or result.get("interrupted_at") != phase
                or not isinstance(error, dict) or error.get("type") != "InputSequenceInterrupted"):
            return "unknown"
        if phase == "focus_type":
            known = (len(rows) == 1 and check == {"status": "not_checked"} and (
                not fact["completed"] and completed == [] and error.get("code") == "focus_type_input_not_confirmed"
                or fact["completed"] and completed == ["focus_type"]
                and error.get("code") == "focus_type_observation_unavailable"
                and not ((fact["receipt"].get("observation") or {}).get("capture") or {}).get("sha256")
                and not ((result.get("observation") or {}).get("capture") or {}).get("sha256")))
        elif phase == "check_input":
            known = (fact["completed"] and len(rows) == 1 and completed == ["focus_type"]
                and isinstance(check, dict) and check.get("status") == "unavailable" and check.get("phase") == phase
                and isinstance(error.get("code"), str) and bool(error["code"]) and check.get("reason") == error["code"])
        elif phase == "prepare_search":
            known = (fact["completed"] and request["submit_search"] and len(rows) == 1
                and completed == ["focus_type", "check_input"] and check == verified
                and _enter_preparation_verified(result, request, fact["identity"]))
        elif phase == "search":
            search = rows[1] if len(rows) == 2 else {}
            local = search.get("receipt") or {}
            known = (fact["completed"] and request["submit_search"] and len(rows) == 2
                and completed == ["focus_type", "check_input"] and check == verified
                and error.get("code") == "search_input_not_confirmed"
                and _compound_search_receipt(search, fact, executed=False, request=request, result=result))
        else:
            known = False
        return "failed" if known else "unknown"
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return "unknown"


def search_not_dispatched_verified(receipt, command, *, target_identity=None):
    """只收敛完整已执行前缀加可信零按键后缀；原票据绑定仍由消费者核验。"""
    from app.agent.native_identity import validate_native_identity_fact
    from .recognition_dispatch import local_receipt_zero_input_verified
    if (not isinstance(receipt, dict) or receipt.get("status") not in ("returned", "failed")
            or receipt.get("command") != command or not isinstance(command, dict)
            or command.get("kind") != "input_sequence"):
        return False
    try:
        request = _request(command.get("request"))
    except (ValueError, TypeError, OverflowError):
        return False
    result = receipt.get("result")
    try:
        effective_request = validated_effective_typing_request(result, request)
    except ValueError:
        return False
    if (not isinstance(result, dict) or result.get("contract_version") != "input_sequence_v1"
            or result.get("status") != "interrupted" or result.get("phase") != "search"
            or result.get("interrupted_at") != "search" or result.get("action_executed") is not True
            or result.get("completed_steps") != ["focus", "type", "check_input"]
            or result.get("automatic_retry_allowed") is not False or result.get("task_effect_verified") is not None
            or not isinstance(result.get("sequence_id"), str) or not result["sequence_id"]
            or request["submit_search"] is not True or result.get("submit_search") is not True):
        return False
    text_digest = sha256(request["text"].encode("utf-8")).hexdigest()
    error, check, rows = result.get("error"), result.get("input_check"), result.get("steps")
    if (result.get("text_sha256") != text_digest or result.get("text_length") != len(request["text"])
            or not isinstance(error, dict) or error.get("type") != "InputSequenceInterrupted"
            or error.get("code") != "search_input_not_confirmed"
            or not isinstance(check, dict) or check.get("status") != "matched" or check.get("value_sha256") != text_digest
            or not isinstance(rows, list) or len(rows) != 3):
        return False
    identity, native_identity = None, None
    for row, (name, operation, phase, executed) in zip(rows, [
            ("focus", "execute_recognition_plan", "returned", True),
            ("type", "type_text", "returned", True), ("search", "press_key", "not_dispatched", False)]):
        if (not isinstance(row, dict) or row.get("name") != name or row.get("operation") != operation
                or row.get("status") != phase or row.get("action_executed") is not executed):
            return False
        local = row.get("receipt")
        if (not isinstance(local, dict) or local.get("contract_version") != "local_direct_step_v1"
                or local.get("operation") != operation or local.get("phase") != phase
                or local.get("local_input_scope_closed") is not True
                or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
                or "action_executed" in local and local["action_executed"] is not executed):
            return False
        current = _identity(local.get("target_identity"))
        if current is None or identity is not None and current != identity:
            return False
        native = validate_native_identity_fact(local.get("target_identity"),
            target_window_handle=current["handle"], expected_process_id=current["process_id"])
        if native is None or native_identity is not None and native != native_identity:
            return False
        native_identity = native
        identity = current
        if name == "search":
            if (not isinstance(local.get("request"), dict) or local["request"].get("key") != "Enter"
                    or not local_receipt_zero_input_verified(local, operation)):
                return False
        else:
            api = local.get("response")
            data = api.get("data") if isinstance(api, dict) else None
            data = data.get("result", data) if isinstance(data, dict) else None
            path = data.get("execution_path") if isinstance(data, dict) else None
            agent = data.get("agent_step_result") if isinstance(data, dict) else None
            if (not isinstance(api, dict) or api.get("success") is not True or not isinstance(data, dict)
                    or not isinstance(path, dict) or path.get("action_executed") is not True
                    or "action_executed" in data and data["action_executed"] is not True
                    or agent is not None and (not isinstance(agent, dict) or agent.get("action_executed") is not True)
                    or _receipt_action(local, operation) is not True):
                return False
            if name == "type":
                if not _completed_type(local, effective_request, text_digest, identity):
                    return False
            elif (not isinstance(data.get("click_result"), dict) or data["click_result"].get("clicked") is not True
                    or not isinstance(local.get("request"), dict) or local["request"].get("goal") != request["field_goal"]):
                return False
    target = result.get("target")
    return (isinstance(target, dict) and type(target.get("handle")) is int and type(target.get("process_id")) is int
        and target["handle"] == identity["handle"] and target["process_id"] == identity["process_id"]
        and (target_identity is None or target_identity == identity))


def type_not_dispatched_verified(receipt, command, *, target_identity=None):
    """已点击前缀加真实零键入证明只结算原失败，不授权任何后续输入。"""
    from app.agent.native_identity import validate_native_identity_fact
    from .recognition_dispatch import local_receipt_zero_input_verified
    if (not isinstance(receipt, dict) or receipt.get("status") not in ("returned", "failed")
            or receipt.get("command") != command or not isinstance(command, dict)
            or command.get("kind") != "input_sequence"):
        return False
    try:
        request = _request(command.get("request"))
    except (ValueError, TypeError, OverflowError):
        return False
    result = receipt.get("result")
    try:
        effective_request = validated_effective_typing_request(result, request)
    except ValueError:
        return False
    if (not isinstance(result, dict) or result.get("contract_version") != "input_sequence_v1"
            or result.get("status") != "interrupted" or result.get("phase") != "type"
            or result.get("interrupted_at") != "type" or result.get("action_executed") is not True
            or result.get("completed_steps") != ["focus"] or result.get("automatic_retry_allowed") is not False
            or result.get("task_effect_verified") is not None
            or not isinstance(result.get("sequence_id"), str) or not result["sequence_id"]):
        return False
    text_digest = sha256(request["text"].encode("utf-8")).hexdigest()
    error, check, rows = result.get("error"), result.get("input_check"), result.get("steps")
    if (result.get("text_sha256") != text_digest or result.get("text_length") != len(request["text"])
            or result.get("submit_search") is not request["submit_search"]
            or not isinstance(error, dict) or error.get("type") != "InputSequenceInterrupted"
            or error.get("code") != "type_input_not_confirmed"
            or not isinstance(check, dict) or check.get("status") != "not_checked"
            or not isinstance(rows, list) or len(rows) != 2):
        return False
    identity, native_identity = None, None
    for row, (name, operation, phase, executed) in zip(rows, [
            ("focus", "execute_recognition_plan", "returned", True),
            ("type", "type_text", "not_dispatched", False)]):
        if (not isinstance(row, dict) or row.get("name") != name or row.get("operation") != operation
                or row.get("status") != phase or row.get("action_executed") is not executed):
            return False
        local = row.get("receipt")
        if (not isinstance(local, dict) or local.get("contract_version") != "local_direct_step_v1"
                or local.get("operation") != operation or local.get("phase") != phase
                or local.get("local_input_scope_closed") is not True
                or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
                or "action_executed" in local and local["action_executed"] is not executed):
            return False
        current = _identity(local.get("target_identity"))
        if current is None or identity is not None and current != identity:
            return False
        native = validate_native_identity_fact(local.get("target_identity"),
            target_window_handle=current["handle"], expected_process_id=current["process_id"])
        if native is None or native_identity is not None and native != native_identity:
            return False
        identity, native_identity = current, native
        audited = local.get("request")
        if not isinstance(audited, dict):
            return False
        if name == "type":
            if (audited.get("text_sha256") != text_digest or audited.get("text_length") != len(request["text"])
                    or audited.get("clear_existing") is not effective_request["clear_existing"]
                    or audited.get("click_before_typing") is not False or audited.get("submit") is not False
                    or not local_receipt_zero_input_verified(local, operation)):
                return False
        else:
            api = local.get("response")
            data = api.get("data") if isinstance(api, dict) else None
            data = data.get("result", data) if isinstance(data, dict) else None
            path = data.get("execution_path") if isinstance(data, dict) else None
            agent = data.get("agent_step_result") if isinstance(data, dict) else None
            if (not isinstance(api, dict) or api.get("success") is not True or not isinstance(data, dict)
                    or not isinstance(path, dict) or path.get("action_executed") is not True
                    or "action_executed" in data and data["action_executed"] is not True
                    or agent is not None and (not isinstance(agent, dict) or agent.get("action_executed") is not True)
                    or _receipt_action(local, operation) is not True
                    or not isinstance(data.get("click_result"), dict) or data["click_result"].get("clicked") is not True
                    or audited.get("goal") != request["field_goal"]):
                return False
    target = result.get("target")
    return (isinstance(target, dict) and type(target.get("handle")) is int and type(target.get("process_id")) is int
        and target["handle"] == identity["handle"] and target["process_id"] == identity["process_id"]
        and (target_identity is None or target_identity == identity))


def _selection_only_dispatch(local):
    from pathlib import Path
    data = local["response"]["data"]
    data = data.get("result", data)
    dispatch = data.get("typing_dispatch")
    keys = {"schema", "focus_dispatch", "selection_dispatch", "text_dispatch", "submit_dispatch",
        "input_started", "action_executed", "events", "artifact_is_authorization", "selection_evidence"}
    if (not isinstance(dispatch, dict) or set(dispatch) != keys or dispatch["schema"] != "typing_dispatch.v1"
            or dispatch["focus_dispatch"] != "not_started" or dispatch["selection_dispatch"] != "completed"
            or dispatch["text_dispatch"] != "not_started" or dispatch["submit_dispatch"] != "not_started"
            or dispatch["input_started"] is not True or dispatch["action_executed"] is not True
            or dispatch["artifact_is_authorization"] is not False or "type_result" in data or data.get("typed") is True
            or data.get("input_started") is not True):
        return False
    events = dispatch["events"]
    if not isinstance(events, list) or len(events) != 2:
        return False
    previous = 0
    for event, state in zip(events, ("started", "completed")):
        elapsed = event.get("elapsed_ms") if isinstance(event, dict) else None
        if (not isinstance(event, dict) or set(event) != {"phase", "status", "elapsed_ms"}
                or event["phase"] != "selection" or event["status"] != state
                or type(elapsed) not in (int, float) or not isfinite(elapsed) or elapsed < previous):
            return False
        previous = elapsed
    evidence = dispatch["selection_evidence"]
    if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
            or not isinstance(evidence["path"], str) or not Path(evidence["path"]).is_absolute()):
        return False
    path = Path(evidence["path"])
    if not path.is_file() or path.stat().st_size > 65536:
        return False
    raw = path.read_bytes()
    return (sha256(raw).hexdigest() == evidence["sha256"]
        and _digest(json.loads(raw.decode("utf-8"))) == _digest({k: v for k, v in dispatch.items() if k != "selection_evidence"}))


def _enter_preparation_verified(result, request, identity):
    """只认证完整输入之后、尚未进入 Enter 动作的受控停止，不赋予动作权限。"""
    from pathlib import Path
    from app.judgment import DecisionProfile, DecisionService
    from app.judgment.ordinary_review import effective_choice
    service = None
    try:
        proof = result["enter_preparation_failure"]
        rows = result["steps"]
        compound = len(rows) == 1 and rows[0].get("name") == "focus_type"
        keys = {"schema", "stage", "sequence_id", "request_sha256", "focus_receipt_sha256",
            "input_receipt_sha256", "value_request_sha256", "stop_reason", "cancelled", "deadline_ns",
            "observed_at_ns", "started_actions", "suffix_dispatch_started", "evidence"}
        if (type(proof) is not dict or set(proof) != keys
                or proof["schema"] != "visual_enter_preparation_partial.v1"
                or proof["stage"] not in {"before_enter_keyboard_target", "before_enter_dispatch"}
                or proof["sequence_id"] != result["sequence_id"] or proof["request_sha256"] != _digest(request)
                or proof["started_actions"] != (["focus_type"] if compound else ["focus", "type"])
                or proof["suffix_dispatch_started"] is not False
                or type(proof["cancelled"]) is not bool or type(proof["deadline_ns"]) is not int
                or type(proof["observed_at_ns"]) is not int or proof["deadline_ns"] <= 0
                or proof["observed_at_ns"] <= 0 or not (proof["cancelled"] or proof["observed_at_ns"] >= proof["deadline_ns"])
                or proof["stop_reason"] != ("visual_field_cancelled" if proof["cancelled"] else "visual_field_deadline_expired")
                or result["error"] != {"type": "InputSequenceInterrupted", "code": proof["stop_reason"]}):
            return False
        new_click = "visual_click_evidence" in result
        evidence = proof["evidence"]
        evidence_keys = {"session_directory", "profile", "request", "assessment"}
        if (type(evidence) is not dict or set(evidence) != evidence_keys
                or not Path(evidence["session_directory"]).is_absolute() or not Path(evidence["session_directory"]).is_dir()):
            return False
        if compound:
            fact = _compound_input_fact(result, request, identity)
            if (fact is None or not fact["completed"]
                    or {"visual_click_evidence", "typing_strategy", "typing_strategy_evidence"} & result.keys()):
                return False
            focus = typed = fact["receipt"]
            execution_id = fact["fact"]["execution_request_id"]
        else:
            focus_evidence = result["visual_click_evidence" if new_click else "typing_strategy_evidence"]
            if (type(focus_evidence) is not dict or set(focus_evidence) != evidence_keys
                    or evidence["session_directory"] != focus_evidence["session_directory"]
                    or evidence["profile"] != focus_evidence["profile"]):
                return False
            focus, typed = [row["receipt"] for row in rows]
            execution_id = focus_evidence["request"]["execution_request_id"]
        value, assessment = evidence["request"], evidence["assessment"]
        action, field = value["action"], value["action"]["field"]
        if compound:
            from app.execution.decision_check import decision_frame
            from app.execution.visual_field_proof import _field
            from app.judgment.visual_action_conditions import VISUAL_TEXT_VALUE_CONDITION
            frame = decision_frame(focus["observation"]["capture"], identity, role="after")
            if (value["condition"] != VISUAL_TEXT_VALUE_CONDITION or value["frames"] != [frame]
                    or _field(field, focus) != field or len(result["field_proofs"]) != 1):
                return False
        reference = result["field_proofs"][-1]
        if (proof["focus_receipt_sha256"] != _digest(focus) or proof["input_receipt_sha256"] != _digest(typed)
                or value["mode"] != "execution" or value["phase"] != "after_action" or value["step_id"] != typed["step_id"]
                or value["execution_request_id"] != execution_id
                or action["operation"] != "visual_field_check" or action["field_phase"] != "value"
                or action.get("focus_stage") is not None or action.get("value_verification") != "visual"
                or action.get("actual_text") is not None or action.get("value_reading") is not None
                or action["focus_receipt_sha256"] != proof["focus_receipt_sha256"]
                or action["input_receipt_sha256"] != proof["input_receipt_sha256"]
                or action["expected_text"] != request["text"] or field != result["field_proofs"][0]["field"]
                or field["window_identity"] != identity or field["field_goal"] != request["field_goal"]
                or field["expected_text"] != request["text"] or field["field_kind"] not in {"search", "address_bar"}
                or reference["schema"] != "visual_field_proof.v1" or reference["phase"] != "value"
                or reference["value_verification"] != "visual" or reference["artifact_is_authorization"] is not False
                or reference["field"] != field or reference["frames"] != value["frames"]
                or reference["frame"] != value["frames"][-1]
                or reference["focus_receipt_sha256"] != proof["focus_receipt_sha256"]
                or reference["input_receipt_sha256"] != proof["input_receipt_sha256"]
                or reference["request_sha256"] != proof["value_request_sha256"]
                or assessment["request_sha256"] != proof["value_request_sha256"]
                or assessment["decision_format"] != "choice" or assessment["status"] != "completed"
                or assessment["adopted"] is not True or assessment["verdict"] != "success"
                or assessment["disposition"] != "continue"):
            return False
        profile = DecisionProfile.model_validate(evidence["profile"])
        service = DecisionService(evidence["session_directory"], profile=profile)
        if not compound and new_click and not _click_before_enter_verified(service, focus_evidence, result, request, identity):
            return False
        return (service.validate_result(assessment, **value) is True
            and effective_choice(assessment) == "condition_met")
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError):
        return False
    finally:
        if service is not None:
            service.close()


def _click_before_enter_verified(service, evidence, result, request, identity):
    """新点击凭据独立认证，并绑定本序列原点击、字段及字段回执。"""
    from app.execution.decision_check import decision_frame
    from app.execution.visual_field_proof import _field
    from app.judgment.executed_click_annotation import executed_click_reference
    from app.judgment.visual_action_conditions import VISUAL_INPUT_CLICKED_CONDITION
    from app.judgment.ordinary_review import effective_choice
    focus = result["steps"][0]["receipt"]
    value, assessment = evidence["request"], evidence["assessment"]
    action = value["action"]
    field = _field(action["field"], focus)
    frame = decision_frame(focus["observation"]["capture"], identity, role="after")
    reference = result["field_proofs"][0]
    expected_reference = {"schema": "visual_field_proof.v1", "evidence_kind": "visual", "phase": "focus",
        "source": "decision_visual", "focus_stage": "after_click", "field": field,
        "frame": frame, "frames": [frame], "focus_receipt_sha256": _digest(focus),
        "input_receipt_sha256": None, "selection_dispatch": None,
        "request_sha256": assessment["request_sha256"], "value_sha256": None,
        "reading": None, "artifact_is_authorization": False}
    if (request["clear_existing"] is not True or service.profile.contract_version != "decision_profile.v2"
            or service.profile.decision_format != "choice" or service.profile.mode != "auto"
            or value["condition"] != VISUAL_INPUT_CLICKED_CONDITION
            or value["mode"] != "execution" or value["phase"] != "after_action"
            or value["step_id"] != focus["step_id"] or value["frames"] != [frame]
            or action["operation"] != "visual_field_check" or action["field_phase"] != "focus"
            or action["focus_stage"] != "after_click" or action["field"] != field
            or field["field_goal"] != request["field_goal"] or field["expected_text"] != request["text"]
            or field["window_identity"] != identity
            or action["focus_receipt_sha256"] != _digest(focus)
            or action["input_receipt_sha256"] is not None or action["expected_text"] is not None
            or action["actual_text"] is not None or action["value_reading"] is not None
            or any(key in action for key in ("focus_value_snapshot", "field_freshness_context",
                "focus_observation", "field_content_check", "field_content_ocr"))
            or action["executed_click"] != executed_click_reference(focus, field)
            or action["field_image_scope"] != {"schema": "visual_field_roi.v1", "padding": 16}
            or reference != expected_reference
            or assessment["decision_format"] != "choice" or assessment["status"] != "completed"
            or assessment["adopted"] is not True or assessment["verdict"] != "success"
            or assessment["disposition"] != "continue"):
        return False
    return (service.validate_result(assessment, **value) is True
        and effective_choice(assessment) == "condition_met")


def visual_prefix_failure_verified(receipt, command, *, target_identity=None):
    """完整已知前缀只结算失败；文字或 Enter 的未知派发仍持有原票据。"""
    from app.agent.native_identity import validate_native_identity_fact
    from .recognition_dispatch import local_receipt_zero_input_verified
    try:
        if (not isinstance(receipt, dict) or receipt.get("status") not in {"returned", "failed"}
                or receipt.get("command") != command or not isinstance(command, dict)
                or command.get("kind") != "input_sequence"):
            return False
        request = _request(command.get("request"))
        result = receipt.get("result")
        effective_request = validated_effective_typing_request(result, request)
        if (not isinstance(result, dict) or result.get("contract_version") != "input_sequence_v1"
                or result.get("status") != "interrupted" or result.get("action_executed") is not True
                or result.get("automatic_retry_allowed") is not False or result.get("task_effect_verified") is not None
                or not isinstance(result.get("sequence_id"), str) or not result["sequence_id"]
                or request["clear_existing"] is not True and "typing_strategy" not in result):
            return False
        phase = result.get("phase")
        error, check, rows = result.get("error"), result.get("input_check"), result.get("steps")
        if (phase not in {"type", "check_input", "prepare_search", "search"} or result.get("interrupted_at") != phase
                or not isinstance(error, dict) or error.get("type") != "InputSequenceInterrupted"
                or not isinstance(check, dict) or not isinstance(rows, list)
                or len(rows) != (3 if phase == "search" else 2)):
            return False
        if phase == "type":
            if (error.get("code") != "type_input_not_confirmed" or check != {"status": "not_checked"}
                    or result.get("completed_steps") != ["focus"]):
                return False
        elif phase == "check_input":
            if (check.get("status") != "unavailable" or check.get("phase") != "check_input"
                    or not isinstance(error.get("code"), str) or not error["code"]
                    or check.get("reason") != error["code"] or result.get("completed_steps") != ["focus", "type"]):
                return False
        elif (request["submit_search"] is not True
                or phase == "search" and error.get("code") != "search_input_not_confirmed"
                or phase == "prepare_search" and "enter_preparation_failure" not in result
                or check != {"status": "verified", "source": "decision_visual", "evidence_kind": "visual"}
                or result.get("completed_steps") != ["focus", "type", "check_input"]):
            return False
        digest = sha256(request["text"].encode("utf-8")).hexdigest()
        if (result.get("text_sha256") != digest or result.get("text_length") != len(request["text"])
                or result.get("submit_search") is not request["submit_search"]):
            return False
        native_identity = identity = None
        seen_steps = set()
        for index, row in enumerate(rows):
            name, operation = [("focus", "execute_recognition_plan"), ("type", "type_text"), ("search", "press_key")][index]
            expected_phase = "result_unknown" if index == 1 and phase == "type" else "not_dispatched" if index == 2 else "returned"
            executed = index != 2
            local = row.get("receipt")
            if (row.get("name") != name or row.get("operation") != operation or row.get("status") != expected_phase
                    or row.get("action_executed") is not executed or not isinstance(local, dict)
                    or local.get("contract_version") != "local_direct_step_v1" or local.get("operation") != operation
                    or local.get("phase") != expected_phase or local.get("local_input_scope_closed") is not True
                    or not isinstance(local.get("finished_at"), str) or not local["finished_at"]
                    or "action_executed" in local and local["action_executed"] is not executed
                    or _receipt_action(local, operation) is not executed
                    or not isinstance(local.get("step_id"), str) or not local["step_id"] or local["step_id"] in seen_steps):
                return False
            seen_steps.add(local["step_id"])
            current = _identity(local.get("target_identity"))
            if current is None or identity is not None and current != identity:
                return False
            native = validate_native_identity_fact(local.get("target_identity"),
                target_window_handle=current["handle"], expected_process_id=current["process_id"])
            if native is None or native_identity is not None and native != native_identity:
                return False
            native_identity, identity = native, current
            api, audited = local.get("response"), local.get("request")
            if not isinstance(api, dict) or not isinstance(audited, dict):
                return False
            data = api.get("data")
            data = data.get("result", data) if isinstance(data, dict) else None
            if not isinstance(data, dict):
                return False
            if index == 0:
                if (api.get("success") is not True or audited.get("goal") != request["field_goal"]
                        or not isinstance(data.get("click_result"), dict) or data["click_result"].get("clicked") is not True):
                    return False
            elif index == 1:
                if (audited.get("text_sha256") != digest or audited.get("text_length") != len(request["text"])
                        or audited.get("clear_existing") is not effective_request["clear_existing"] or audited.get("click_before_typing") is not False
                        or audited.get("submit") is not False):
                    return False
                if phase == "type":
                    if (effective_request["clear_existing"] is not True or api.get("success") is not False or not isinstance(api.get("error"), dict)
                            or api["error"].get("code") != "type_text_failed" or not _selection_only_dispatch(local)):
                        return False
                elif not _completed_type(local, effective_request, digest, identity):
                    return False
            elif audited.get("key") != "Enter" or not local_receipt_zero_input_verified(local, operation):
                return False
        if phase == "prepare_search" and not _enter_preparation_verified(result, request, identity):
            return False
        target = result.get("target")
        return (isinstance(target, dict) and type(target.get("handle")) is int and type(target.get("process_id")) is int
            and target["handle"] == identity["handle"] and target["process_id"] == identity["process_id"]
            and (target_identity is None or target_identity == identity))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def _pre_capture_sequence_verified(receipt, command, target_identity):
    from .local_step_no_dispatch import pre_capture_failure_verified
    try:
        request, result = _request(command.get("request")), receipt["result"]
        rows = result.get("steps")
        if (command.get("kind") != "input_sequence" or receipt.get("command") != command
                or result.get("contract_version") != "input_sequence_v1" or result.get("status") != "interrupted"
                or result.get("phase") != "focus" or result.get("interrupted_at") != "focus"
                or result.get("action_executed") is not False or result.get("completed_steps") != []
                or result.get("input_check") != {"status": "not_checked"}
                or result.get("automatic_retry_allowed") is not False or result.get("task_effect_verified") is not None
                or result.get("error") != {"code": "focus_input_not_confirmed", "type": "InputSequenceInterrupted"}
                or result.get("text_sha256") != sha256(request["text"].encode("utf-8")).hexdigest()
                or result.get("text_length") != len(request["text"]) or result.get("submit_search") is not request["submit_search"]
                or not isinstance(rows, list) or len(rows) != 1):
            return False
        row = rows[0]
        local = row.get("receipt")
        if (row.get("name") != "focus" or row.get("operation") != "execute_recognition_plan"
                or row.get("status") != "not_dispatched" or row.get("action_executed") is not False
                or not pre_capture_failure_verified(local, "execute_recognition_plan")
                or local["request"].get("goal") != request["field_goal"]):
            return False
        identity, target = _identity(local["target_identity"]), result.get("target")
        return (identity is not None and isinstance(target, dict) and target.get("handle") == identity["handle"]
            and target.get("process_id") == identity["process_id"] and (target_identity is None or identity == target_identity))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def original_input_status(receipt, command, *, succeeded, action_executed, target_identity=None):
    rows = (receipt.get("result") or {}).get("steps") or []
    compound = any(isinstance(row, dict) and row.get("name") == "focus_type" for row in rows)
    result = receipt.get("result") or {}
    if compound or result.get("phase") == "focus_type" or "focus_type" in (result.get("completed_steps") or []):
        return _compound_input_status(receipt, command, succeeded=succeeded,
            action_executed=action_executed, target_identity=target_identity)
    if any(isinstance(row, dict) and isinstance(row.get("receipt"), dict)
            and ("pre_dispatch_failure" in row["receipt"]
                or row["receipt"].get("contract_version") == "pre_grounding_capture_failure.v1") for row in rows):
        if not _pre_capture_sequence_verified(receipt, command, target_identity) or succeeded or action_executed is not False:
            return "unknown"
        return "failed"
    if {"typing_strategy", "typing_strategy_evidence"} & (receipt.get("result") or {}).keys():
        try:
            validated_effective_typing_request(receipt["result"], _request(command.get("request")))
        except (ValueError, TypeError, OverflowError):
            return "unknown"
    if "enter_preparation_failure" in (receipt.get("result") or {}):
        verified = (action_executed is True and receipt["result"].get("phase") == "prepare_search"
            and visual_prefix_failure_verified(receipt, command, target_identity=target_identity))
        return "failed" if verified and not succeeded else "unknown"
    partial = focus_only_partial_verified(receipt, command, target_identity=target_identity)
    # 声明了新证明却不完整时不能退回汇总 false 或旧部分输入形状。
    if PROOF_FIELD in (receipt.get("result") or {}) and not partial:
        return "unknown"
    visual_prefix = action_executed is True and visual_prefix_failure_verified(receipt, command, target_identity=target_identity)
    if visual_prefix:
        return "unknown" if succeeded else "failed"
    if succeeded:
        return "completed"
    closed_search = action_executed is True and search_not_dispatched_verified(receipt, command,
        target_identity=target_identity)
    closed_type = action_executed is True and type_not_dispatched_verified(receipt, command,
        target_identity=target_identity)
    return "failed" if action_executed is False or action_executed is True and (partial or closed_search or closed_type) else "unknown"
