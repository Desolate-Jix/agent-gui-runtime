"""同次审核点击后的单次替换能力；不提供公开点击或键盘授权。"""
from copy import deepcopy
from hashlib import sha256
import json
from threading import get_ident
from time import perf_counter_ns


_ISSUER = object()


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def bind_visual_compound_input(target, *, text, context, field_goal):
    from .local_text_focus import VisualTextFocusTarget
    if (type(target) is not VisualTextFocusTarget or hasattr(target, "_compound_spec")
            or type(text) is not str or not text or len(text) > 20000
            or type(context.get("deadline_ns")) is not int
            or not isinstance(context.get("execution_request_id"), str)
            or not context["execution_request_id"] or not field_goal):
        raise ValueError("visual_compound_binding_invalid")
    target._compound_spec = {"text": text, "deadline_ns": context["deadline_ns"],
        "cancelled": context.get("cancelled"), "issuer": _ISSUER,
        "execution_request_id": context["execution_request_id"], "field_goal": deepcopy(field_goal)}
    target._compound_prepared = None
    target._compound_consumed = False


def _scope():
    from .local_text_focus import _SCOPE, VisualTextFocusTarget
    scope = _SCOPE.get()
    if scope is None or type(scope["target"]) is not VisualTextFocusTarget:
        return None
    target = scope["target"]
    if not hasattr(target, "_compound_spec"):
        return None
    if (not scope["active"] or scope["owner"] != get_ident() or not scope["claimed"]
            or target._compound_spec.get("issuer") is not _ISSUER):
        raise ValueError("visual_compound_scope_unavailable")
    return scope


def _check_stop(spec):
    cancelled = spec["cancelled"]
    stopped = cancelled() if callable(cancelled) else False
    if type(stopped) is not bool:
        raise ValueError("visual_compound_cancel_state_unknown")
    if stopped:
        raise ValueError("visual_field_cancelled")
    if perf_counter_ns() >= spec["deadline_ns"]:
        raise ValueError("visual_field_deadline_expired")


def resume_pre_action_compound(target, approval, *, execution_request_id):
    """Renew only the original unperformed compound under the live Main capability."""
    from .local_text_focus import VisualTextFocusTarget
    from app.execution.main_pre_action_approval import MainPreActionApproval
    if type(target) is not VisualTextFocusTarget or not hasattr(target, '_compound_spec'):
        return
    if type(approval) is not MainPreActionApproval:
        raise ValueError('visual_compound_main_approval_invalid')
    approval.validate()
    spec = target._compound_spec
    context = approval.source.context
    step = next(row for row in context['plan']['steps'] if row['step_id'] == context['step_id'])
    from app.execution.task_plan_contract import resolve_action_text
    if (spec.get('issuer') is not _ISSUER or target._compound_prepared is not None or target._compound_consumed
            or spec['execution_request_id'] != execution_request_id
            or step['action']['kind'] != 'input_sequence' or step['action']['field_goal'] != spec['field_goal']
            or resolve_action_text(step['action']['text'], context['plan']['inputs']) != spec['text']):
        raise ValueError('visual_compound_main_binding_invalid')
    spec['deadline_ns'] = approval.deadline_ns


def prepare_visual_compound_input(manager, point, review):
    scope = _scope()
    if scope is None:
        return
    from app.execution.action_review import current_action_review, validate_assessment
    from app.execution.decision_check import DecisionCheckRejected, _identity
    from app.execution.task_plan_contract import resolve_action_text
    from .local_input_policy import current_local_operator_identity
    target, spec = scope["target"], scope["target"]._compound_spec
    def reject(reason):
        raise DecisionCheckRejected(reason, {"status": "invalidated", "verdict": "uncertain",
            "reason": reason, "adopted": False, "authorizes_action": False, "automatic_retry_allowed": False})
    if target._compound_consumed or target._compound_prepared is not None:
        raise ValueError("visual_compound_already_consumed")
    active = current_action_review()
    from app.execution.main_pre_action_approval import MainPreActionApproval
    main_approval = review.get('main_pre_action_approval') if isinstance(review, dict) else None
    main_adopted = (type(main_approval) is MainPreActionApproval and main_approval.validate() is True
        and active is not None and active.get('main_pre_action_review') == main_approval.to_reference())
    if (not isinstance(review, dict) or active is None or review.get("scope") is not active
            or not (main_adopted or validate_assessment(active["service"], active["assessment"],
                envelope=active["envelope"], cancelled=active["cancelled"]))):
        reject("visual_compound_candidate_review_required")
    review["validate"]()
    context = active["context"]
    action = next(row["action"] for row in context["plan"]["steps"] if row["step_id"] == context["step_id"])
    if (action.get("kind") != "input_sequence" or action.get("clear_existing", True) is not True
            or action.get("field_goal") != spec["field_goal"]
            or resolve_action_text(action.get("text"), context["plan"]["inputs"]) != spec["text"]
            or review["candidate"]["click_point"] != point):
        reject("visual_compound_review_binding_invalid")
    identity = _identity(current_local_operator_identity(manager))
    bound = manager.get_bound_window()
    if bound is None or (bound.handle, bound.process_id) != (target.handle, target.pid):
        raise ValueError("visual_compound_window_binding_changed")
    _check_stop(spec)
    target._compound_prepared = {"point": deepcopy(point), "window_identity": identity,
        "window_rect": [bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom],
        "review": review, "owner": get_ident(), "scope": scope}


class VisualCompoundKeyboardTarget:
    def __init__(self, target, *, _issuer=None):
        if _issuer is not _ISSUER or target._compound_prepared is None:
            raise ValueError("visual_compound_keyboard_issuer_unavailable")
        self._target, self._consumed = target, False
        self._binding = target._compound_prepared
        self._text_sha256 = sha256(target._compound_spec["text"].encode("utf-8")).hexdigest()

    def validate_command(self, operation, request):
        if (operation != "type_text" or type(request.get("text")) is not str
                or sha256(request["text"].encode("utf-8")).hexdigest() != self._text_sha256
                or {key: request.get(key) for key in ("x", "y")} != self._binding["point"]
                or any(type(request.get(key)) is not int for key in ("x", "y"))
                or request.get("clear_existing") is not True
                or request.get("click_before_typing", False) is not False
                or request.get("submit", False) is not False):
            raise ValueError("visual_compound_keyboard_command_changed")

    def verify(self, manager):
        from app.execution.decision_check import _identity
        from .local_input_policy import current_local_operator_identity
        binding = self._binding
        if (_scope() is not binding["scope"] or binding["owner"] != get_ident()
                or not self._target._compound_consumed):
            raise ValueError("visual_compound_keyboard_scope_unavailable")
        _check_stop(self._target._compound_spec)
        bound = manager.get_bound_window()
        if (bound is None or _identity(current_local_operator_identity(manager)) != binding["window_identity"]
                or [bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom] != binding["window_rect"]):
            raise ValueError("visual_compound_window_binding_changed")


def perform_visual_compound_input(controller, manager, point, click_result, *, output=None):
    scope = _scope()
    if scope is None:
        return None
    from .local_keyboard_target import local_keyboard_target_scope
    from .typing_dispatch import create_typing_dispatch, typing_dispatch_from_error
    target = scope["target"]
    binding = target._compound_prepared
    if binding is None or target._compound_consumed:
        raise ValueError("visual_compound_already_consumed_or_unreviewed")
    target._compound_consumed = True
    compound = {"schema": "visual_compound_input.v1", "text_length": len(target._compound_spec["text"]),
        "text_sha256": sha256(target._compound_spec["text"].encode("utf-8")).hexdigest(),
        "clear_existing": True, "submit": False, "window_identity": deepcopy(binding["window_identity"]),
        "execution_request_id": target._compound_spec["execution_request_id"],
        "window_rect": list(binding["window_rect"]), "point": deepcopy(binding["point"]),
        "click_result_sha256": _digest(click_result), "typing_dispatch": create_typing_dispatch().reference()}
    if output is not None:
        output["visual_compound_input"] = compound
    entered = False
    try:
        if (point != binding["point"] or not isinstance(click_result, dict) or click_result.get("clicked") is not True
                or click_result.get("window_point") != point or click_result.get("window_handle") != target.handle):
            raise ValueError("visual_compound_click_binding_changed")
        keyboard = VisualCompoundKeyboardTarget(target, _issuer=_ISSUER)
        keyboard.verify(manager)
        with local_keyboard_target_scope(keyboard):
            entered = True
            typed = controller.type_text(target._compound_spec["text"], **point,
                click_before_typing=False, clear_existing=True, submit=False)
        compound.update(type_result=typed, typing_dispatch=deepcopy(typed["typing_dispatch"]))
        if output is not None:
            output.update(type_result=deepcopy(typed), typing_dispatch=deepcopy(compound["typing_dispatch"]))
        return compound
    except Exception as error:
        dispatch = typing_dispatch_from_error(error)
        if dispatch is not None or entered:
            compound["typing_dispatch"] = dispatch
        compound["error"] = {"type": type(error).__name__, "code": str(error)}
        if output is not None:
            output["typing_dispatch"] = deepcopy(compound["typing_dispatch"])
        error._visual_compound_input = deepcopy(compound)
        raise


def validate_visual_compound_receipt(receipt, expected, *, execution_request_id):
    """值证明只接受同一真实已关闭动作，不把完成点击当成完成键入。"""
    from app.execution.decision_check import _identity
    from app.judgment.executed_click_annotation import executed_click_reference
    data = (receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    compound = data.get("visual_compound_input")
    typed = compound.get("type_result") if isinstance(compound, dict) else None
    dispatch = compound.get("typing_dispatch") if isinstance(compound, dict) else None
    rect = expected["window_rect"]
    if (receipt.get("contract_version") != "local_direct_step_v1"
            or receipt.get("operation") != "execute_recognition_plan" or receipt.get("phase") != "returned"
            or "action_executed" in receipt and receipt["action_executed"] is not True
            or (data.get("execution_path") or {}).get("action_executed") is not True
            or receipt.get("local_input_scope_closed") is not True or not receipt.get("finished_at")
            or (receipt.get("response") or {}).get("success") is not True
            or not isinstance(compound, dict) or compound.get("schema") != "visual_compound_input.v1"
            or compound.get("execution_request_id") != execution_request_id
            or compound.get("text_sha256") != sha256(expected["expected_text"].encode("utf-8")).hexdigest()
            or type(compound.get("text_length")) is not int or compound.get("text_length") != len(expected["expected_text"])
            or compound.get("clear_existing") is not True or compound.get("submit") is not False
            or compound.get("window_identity") != _identity(receipt.get("target_identity"))
            or compound.get("window_identity") != expected["window_identity"]
            or compound.get("window_rect") != [rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]]
            or compound.get("point") != expected["click_point"]
            or compound.get("click_result_sha256") != _digest(data.get("click_result"))
            or not isinstance(typed, dict) or typed.get("typed") is not True
            or typed.get("window_handle") != expected["window_identity"]["handle"]
            or type(typed.get("text_length")) is not int or typed.get("text_length") != len(expected["expected_text"])
            or typed.get("clear_existing") is not True or typed.get("submit") is not False
            or typed.get("click_before_typing") is not False
            or not isinstance(dispatch, dict) or dispatch != typed.get("typing_dispatch")
            or dispatch.get("schema") != "typing_dispatch.v1"
            or dispatch.get("focus_dispatch") != "not_started"
            or dispatch.get("selection_dispatch") != "completed" or dispatch.get("text_dispatch") != "completed"
            or dispatch.get("submit_dispatch") != "not_started" or dispatch.get("action_executed") is not True
            or dispatch.get("input_started") is not True or dispatch.get("artifact_is_authorization") is not False
            or not isinstance(dispatch.get("events"), list)
            or [(row.get("phase"), row.get("status")) for row in dispatch["events"] if isinstance(row, dict)] != [
                ("selection", "started"), ("selection", "completed"), ("text", "started"), ("text", "completed")]):
        raise ValueError("visual_compound_receipt_binding_invalid")
    if executed_click_reference(receipt, expected) is None:
        raise ValueError("visual_compound_completed_click_required")
    return deepcopy(compound)
