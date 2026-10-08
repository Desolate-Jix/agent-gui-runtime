"""显式判断只补充执行证据，不能产生坐标或授予输入权限。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re
from threading import get_ident


_SCOPE = ContextVar("execution_decision_check", default=None)


class DecisionCheckRejected(ValueError):
    def __init__(self, reason_code, result):
        self.reason_code = reason_code
        self.result = deepcopy(result)
        super().__init__(reason_code)


def validate_decision_check(value):
    if value is None:
        return None
    if (type(value) is not dict or set(value) != {"condition", "phase"}
            or type(value.get("condition")) is not str or not value["condition"].strip()
            or len(value["condition"]) > 4000
            or value.get("phase") not in {"before_action", "after_action"}):
        raise ValueError("decision_check requires explicit condition and before_action/after_action phase")
    return deepcopy(value)


def validate_execution_request_id(value):
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
        raise ValueError("decision_check requires a stable execution_request_id")
    return value


def service_enabled(service):
    return service is not None and getattr(service, "enabled", False) is True


@contextmanager
def execution_decision_scope(service, *, decision_check, request_id, execution_request_id, step_id=None, evidence_root=None):
    check = validate_decision_check(decision_check)
    if check is None:
        yield
        return
    validate_execution_request_id(execution_request_id)
    if _SCOPE.get() is not None:
        raise ValueError("decision_check scopes cannot overlap")
    scope = {"service": service, "check": check, "request_id": request_id,
        "execution_request_id": execution_request_id, "step_id": step_id,
        "owner": get_ident(), "active": True, "result": None, "evidence_root": evidence_root}
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        scope["active"] = False
        _SCOPE.reset(token)


def current_execution_decision():
    scope = _SCOPE.get()
    if scope is None:
        return None
    if not scope["active"] or scope["owner"] != get_ident():
        raise ValueError("decision_check scope revoked")
    return scope


def _identity(value):
    value = value if isinstance(value, dict) else {}
    result = {"handle": value.get("handle", value.get("target_window_handle")),
        "process_id": value.get("process_id"), "process_create_time": value.get("process_create_time")}
    if (type(result["handle"]) is not int or result["handle"] <= 0
            or type(result["process_id"]) is not int or result["process_id"] <= 0
            or type(result["process_create_time"]) not in {int, float}
            or result["process_create_time"] <= 0):
        raise ValueError("decision_check window identity unavailable")
    return result


def decision_frame(capture, identity, *, role):
    if not isinstance(capture, dict) or type(capture.get("image_path")) is not str:
        raise ValueError("decision_check original capture unavailable")
    bound = _identity(identity)
    declared = capture.get("window_identity")
    if declared is not None and _identity(declared) != bound:
        raise ValueError("decision_check capture window identity mismatch")
    digest = sha256(Path(capture["image_path"]).read_bytes()).hexdigest()
    if capture.get("sha256") is not None and capture["sha256"] != digest:
        raise ValueError("decision_check capture hash mismatch")
    return {"capture_id": capture.get("capture_id") or "capture-" + digest[:32],
        "sha256": digest, "image_path": capture["image_path"], "window_identity": bound, "role": role}


def _candidate(candidate, point):
    if not isinstance(candidate, dict) or not isinstance(point, dict):
        raise ValueError("decision_check current candidate unavailable")
    element = candidate.get("element")
    element = element if isinstance(element, dict) else {}
    box = candidate.get("bbox") or candidate.get("refined_bbox") or element.get("bbox")
    if not isinstance(box, dict):
        raise ValueError("decision_check candidate bbox unavailable")
    box = {"x": box.get("x"), "y": box.get("y"),
        "w": box.get("w", box.get("width")), "h": box.get("h", box.get("height"))}
    if (any(type(box[key]) is not int for key in box) or min(box["w"], box["h"]) <= 0
            or any(type(point.get(key)) is not int for key in ("x", "y"))
            or not (box["x"] <= point["x"] < box["x"] + box["w"]
                and box["y"] <= point["y"] < box["y"] + box["h"])):
        raise ValueError("decision_check point outside current candidate")
    return {"candidate_id": candidate.get("candidate_id"), "bbox": box,
        "click_point": deepcopy(point), "capture_id": candidate.get("capture_id"),
        "source": candidate.get("source"), "label": candidate.get("text", candidate.get("label"))}


def _advice(reason, *, phase, input_status=None):
    return {"status": "not_applied", "reason": reason, "phase": phase, "verdict": "uncertain",
        "adopted": False, "effect_verified": None, "input_status": input_status,
        "authorizes_action": False, "automatic_retry_allowed": False, "gate_applied": False}


def _evaluate(service, *, request_id, execution_request_id, condition, frames, phase, step_id=None, action=None):
    request = dict(request_id=request_id, execution_request_id=execution_request_id,
        condition=condition, frames=frames, mode="execution", phase=phase, step_id=step_id, action=action)
    try:
        result = service.evaluate(**request)
    except Exception as error:
        return {**_advice("decision_service_failed", phase=phase), "status": "error",
            "error_type": type(error).__name__}
    if (not isinstance(result, dict) or result.get("request_id") != request_id
            or result.get("execution_request_id") != execution_request_id or result.get("phase") != phase
            or result.get("verdict") not in {"success", "failure", "uncertain"}
            or result.get("authorizes_action") is not False):
        return {**_advice("decision_result_binding_invalid", phase=phase), "status": "invalid"}
    if result.get("adopted") is True:
        try:
            authenticated = service.validate_result(result, **request)
        except Exception:
            authenticated = False
        if authenticated is not True:
            return {**_advice("decision_result_authentication_invalid", phase=phase), "status": "invalid"}
    return {**deepcopy(result), "judgment_result": deepcopy(result),
        "authorizes_action": False, "automatic_retry_allowed": False}


def _automatic_gate(scope):
    service = scope["service"]
    return (service_enabled(service) and getattr(service, "adoption_mode", None) == "auto"
        and service.auto_condition_allowed(scope["check"]["condition"]))


def before_action_unavailable(scope):
    service = scope["service"]
    if not service_enabled(service):
        result = _advice("decision_service_disabled", phase="before_action")
    else:
        readiness = service.readiness()
        if readiness.get("ready") is True:
            return None
        result = {**_advice("decision_service_unavailable", phase="before_action"),
            "status": readiness.get("status", "not_connected"), "gate_applied": _automatic_gate(scope)}
    scope["result"] = deepcopy(result)
    if result["gate_applied"]:
        raise DecisionCheckRejected("decision_check_rejected", result)
    return result


def _before_evidence(scope, capture, identity, candidate, point):
    frame = decision_frame(capture, identity, role="before")
    selected = _candidate(candidate, point)
    if scope["evidence_root"] is not None:
        root = Path(scope["evidence_root"])
        service_root = getattr(scope["service"], "session_dir", None)
        if (root.is_symlink() or (service_root is not None
                and not root.resolve().is_relative_to(Path(service_root).resolve()))):
            raise ValueError("decision_check owned evidence root invalid")
        root.mkdir(parents=True, exist_ok=True)
        owned = root / (frame["sha256"] + Path(frame["image_path"]).suffix)
        if owned.is_symlink():
            raise ValueError("decision_check owned evidence path invalid")
        payload = Path(frame["image_path"]).read_bytes()
        if sha256(payload).hexdigest() != frame["sha256"]:
            raise ValueError("decision_check original capture changed before transfer")
        if owned.exists() and owned.read_bytes() != payload:
            raise ValueError("decision_check owned evidence conflicts")
        if not owned.exists():
            owned.write_bytes(payload)
        frame["image_path"] = str(owned)
    return frame, selected


def evaluate_before_action(scope, *, capture, identity, candidate, point, goal, click_kind, revalidate):
    check, service = scope["check"], scope["service"]
    if check["phase"] != "before_action" or not service_enabled(service):
        result = _advice("decision_service_disabled", phase=check["phase"])
        scope["result"] = result
        return result
    try:
        frame, selected = _before_evidence(scope, capture, identity, candidate, point)
    except (ValueError, OSError, TypeError) as error:
        result = {**_advice("original_before_evidence_invalid", phase="before_action"),
            "status": "rejected", "error_type": type(error).__name__}
        scope["result"] = deepcopy(result)
        raise DecisionCheckRejected("decision_check_invalid_evidence", result) from error
    action = {"operation": "execute_recognition_plan", "goal": goal, "click_kind": click_kind,
        "target_window_identity": frame["window_identity"], "candidate": selected}
    result = _evaluate(service, request_id=scope["request_id"], execution_request_id=scope["execution_request_id"],
        condition=check["condition"], frames=[frame], phase="before_action", step_id=scope["step_id"], action=action)
    gate = _automatic_gate(scope)
    result.update(gate_applied=gate, authorizes_action=False, automatic_retry_allowed=False)
    # 网络等待期间的变化必须在原输入 claim 之前发现，影子模式也不能沿用过时坐标。
    try:
        current_capture, current_identity, current_candidate = revalidate()
        current_frame = decision_frame(current_capture, current_identity, role="before")
        current_selected = _candidate(current_candidate, point)
        if (current_frame["sha256"] != frame["sha256"]
                or current_frame["window_identity"] != frame["window_identity"] or current_selected != selected):
            raise ValueError("decision_check evidence changed while waiting")
    except Exception as error:
        result.update(status="invalidated", adopted=False, reason="evidence_changed_after_wait",
            revalidation_error_type=type(error).__name__)
        scope["result"] = deepcopy(result)
        raise DecisionCheckRejected("decision_check_stale_after_wait", result) from error
    result["freshness_revalidated"] = True
    scope["result"] = deepcopy(result)
    if gate and (result.get("adopted") is not True or result.get("verdict") != "success"):
        raise DecisionCheckRejected("decision_check_rejected", result)
    return result


def evaluate_post_action(service, *, request_id, execution_request_id, decision_check, receipt, before_frame=None):
    check = validate_decision_check(decision_check)
    if check is None:
        return _advice("decision_check_absent", phase="after_action")
    validate_execution_request_id(execution_request_id)
    if check["phase"] != "after_action":
        return _advice("decision_check_phase_not_after_action", phase=check["phase"])
    if not isinstance(receipt, dict):
        return _advice("original_receipt_unavailable", phase="after_action")
    outer = receipt if "result" in receipt and "response" not in receipt else None
    original = receipt.get("result") if outer is not None else receipt
    status = receipt.get("status", original.get("phase") if isinstance(original, dict) else None)
    advice = _advice("original_receipt_unavailable", phase="after_action", input_status=status)
    if not service_enabled(service):
        return {**advice, "reason": "decision_service_disabled"}
    response = original.get("response") if isinstance(original, dict) else None
    if (not isinstance(original, dict) or (outer is not None and outer.get("status") != "returned")
            or (outer is not None and outer.get("request_id", execution_request_id) != execution_request_id)
            or original.get("phase") != "returned" or not isinstance(response, dict) or response.get("success") is not True):
        return {**advice, "reason": "original_input_not_completed"}
    observation = original.get("observation")
    if not isinstance(observation, dict) or observation.get("status") != "captured":
        return {**advice, "reason": "original_after_capture_unavailable"}
    try:
        after = decision_frame(observation.get("capture"), original.get("target_identity"), role="after")
        frames = [after]
        if before_frame is not None:
            frames.insert(0, decision_frame(before_frame, original.get("target_identity"), role="before"))
    except (ValueError, OSError) as error:
        return {**advice, "reason": "original_evidence_invalid", "error_type": type(error).__name__}
    result = _evaluate(service, request_id=request_id, execution_request_id=execution_request_id,
        condition=check["condition"], frames=frames, phase="after_action", step_id=original.get("step_id"))
    adopted = result.get("adopted") is True
    verdict = result.get("verdict")
    return {**result, "input_status": status, "effect_verified": verdict == "success" if adopted else None,
        "task_effect": ("success" if verdict == "success" else "failure") if adopted else "awaiting_agent_review",
        "authorizes_action": False, "automatic_retry_allowed": False}
