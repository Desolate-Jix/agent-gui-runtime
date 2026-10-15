"""合并候选审核；场景预检不具备候选权限，采用仍由原执行线程完成。"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
import json
from threading import get_ident
from time import perf_counter_ns

from .decision_check import _candidate, _evaluate, decision_frame
from app.judgment.adaptive_policy import normalize_review_context
from app.judgment.service import decision_profile_sha256


from app.judgment.visual_action_conditions import CANDIDATE_CONDITION, SCENE_CONDITION, FRESHNESS_CONDITION


_SCOPE = ContextVar("visual_action_review", default=None)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _deadline(value):
    if type(value) is not int or value <= 0:
        raise ValueError("action_review_deadline_invalid")
    return value


def normalize_action_review_context(value):
    if value is None:
        return None
    fields = {"schema", "plan", "step_id", "run_id", "attempt_id", "budget_ms"}
    if type(value) is not dict or set(value) != fields or value.get("schema") != "action_review_context.v1":
        raise ValueError("action_review_context_invalid")
    from .task_plan_contract import validate_task_plan
    checked = deepcopy(value)
    checked["plan"] = validate_task_plan(value["plan"])
    if sum(row["step_id"] == value["step_id"] for row in checked["plan"]["steps"]) != 1:
        raise ValueError("action_review_step_not_in_plan")
    if type(value["budget_ms"]) is not int or not 1 <= value["budget_ms"] <= 120000:
        raise ValueError("action_review_budget_invalid")
    for key in ("run_id", "attempt_id"):
        if type(value[key]) is not str or not value[key].strip() or len(value[key]) > 128:
            raise ValueError("action_review_identity_invalid")
    return checked


def build_action_review(*, scope, plan, step, run_id, attempt_id, capture, identity,
                        candidate, action, profile_sha256, deadline_ns):
    if scope not in {"scene", "candidate"}:
        raise ValueError("action_review_scope_invalid")
    if not isinstance(plan, dict) or not isinstance(step, dict) or not isinstance(action, dict):
        raise ValueError("action_review_plan_invalid")
    steps = plan.get("steps")
    if not isinstance(steps, list) or sum(item == step for item in steps) != 1:
        raise ValueError("action_review_step_not_in_plan")
    for value in (run_id, attempt_id):
        if type(value) is not str or not value.strip() or len(value) > 128:
            raise ValueError("action_review_identity_invalid")
    if type(profile_sha256) is not str or len(profile_sha256) != 64 or any(c not in "0123456789abcdef" for c in profile_sha256):
        raise ValueError("action_review_profile_invalid")
    frame = decision_frame(capture, identity, role="before")
    selected = None
    if scope == "candidate":
        if not isinstance(candidate, dict) or candidate.get("capture_id") != frame["capture_id"]:
            raise ValueError("action_review_candidate_capture_mismatch")
        selected = _candidate(candidate, candidate.get("click_point"))
    elif candidate is not None:
        raise ValueError("action_review_scene_candidate_forbidden")
    reviewed_action = deepcopy(action)
    declared = step.get("action", {})
    identity_spec = None
    target_check = None
    if "target_identity" in declared:
        if plan.get("schema_version") != "task_plan.v3" or declared.get("kind") not in {"click", "input_sequence"}:
            raise ValueError("action_review_target_identity_unsupported")
        from app.judgment.target_identity import normalize_target_identity
        identity_spec = normalize_target_identity(declared["target_identity"])
    elif scope == "candidate" and plan.get("schema_version") == "task_plan.v3":
        from app.core.agent_grounding_target import AgentGroundingTarget, current_agent_grounding
        from app.core.visual_submit_target import VisualSubmitTarget
        target = current_agent_grounding()
        if type(target) in {AgentGroundingTarget, VisualSubmitTarget}:
            identity_spec = target.review_target_identity(declared)
            if identity_spec is None:
                target_check = target.review_target_check(declared)
    if identity_spec is not None:
        if "target_identity" in action and action["target_identity"] != identity_spec:
            raise ValueError("action_review_target_identity_conflict")
        if scope == "candidate":
            # 身份选项只来自冻结计划或当前内部定位原件，不采用任意候选字典。
            reviewed_action["target_identity"] = deepcopy(identity_spec)
        else:
            reviewed_action.pop("target_identity", None)
    elif "target_identity" in action:
        raise ValueError("action_review_target_identity_conflict")
    if scope == "scene":
        reviewed_action.pop("target_check", None)
    elif target_check is not None:
        if "target_check" in action and action["target_check"] != target_check:
            raise ValueError("action_review_target_check_conflict")
        reviewed_action["target_check"] = deepcopy(target_check)
    elif "target_check" in action:
        raise ValueError("action_review_target_check_conflict")
    def describe(item):
        action_value = item.get("action", {})
        return str(action_value.get("field_goal", action_value.get("goal", action_value.get("kind", ""))))[:2000]
    index = steps.index(step)
    verification = step.get("verification", {})
    context = normalize_review_context({"goal": plan.get("goal", plan.get("title")),
        "step_goal": describe(step), "remaining_plan": [describe(row) for row in steps[index+1:]],
        "allowed_states": deepcopy(verification.get("allowed_states", [])),
        "source_id": run_id, "source_sha256": _digest(plan),
        **({"review_policy": verification["review_policy"]} if "review_policy" in verification else {})})
    envelope = {"schema": "action_review.v1", "scope": scope, "run_id": run_id,
        "step_id": step["step_id"], "attempt_id": attempt_id, "frame": frame,
        "action": reviewed_action, "candidate": selected, "review_context": context,
        "profile_sha256": profile_sha256, "deadline_ns": _deadline(deadline_ns)}
    envelope["envelope_sha256"] = _digest(envelope)
    return envelope


def build_freshness_review(envelope, *, current_frame, changed_region):
    _validate_envelope(envelope, "candidate")
    if "prior_frame" in envelope:
        raise ValueError("action_review_freshness_retry_exhausted")
    checked = deepcopy(envelope)
    checked["prior_frame"] = deepcopy(envelope["frame"])
    checked["frame"] = {**deepcopy(current_frame), "role": "observation"}
    checked["candidate"]["capture_id"] = current_frame["capture_id"]
    # 新鲜度只审核本次变化，旧身份声明不能作为当前帧的分类结果。
    checked["action"].pop("target_identity", None)
    checked["action"].pop("target_check", None)
    checked["action"]["freshness_context"] = {"schema": "action_freshness.v1",
        "changed_region": deepcopy(changed_region)}
    checked["envelope_sha256"] = _digest({k: v for k, v in checked.items() if k != "envelope_sha256"})
    return checked


def _validate_envelope(envelope, scope):
    required = {"schema", "scope", "run_id", "step_id", "attempt_id", "frame", "action",
        "candidate", "review_context", "profile_sha256", "deadline_ns", "envelope_sha256"}
    if (type(envelope) is not dict or set(envelope) not in (required, required | {"prior_frame"}) or envelope["schema"] != "action_review.v1"
            or envelope["scope"] != scope or _digest({k: v for k, v in envelope.items()
                if k != "envelope_sha256"}) != envelope["envelope_sha256"]):
        raise ValueError("action_review_scope_or_binding_invalid")
    _deadline(envelope["deadline_ns"])
    normalize_review_context(envelope["review_context"])
    if scope == "candidate" and not isinstance(envelope["candidate"], dict):
        raise ValueError("action_review_candidate_required")
    if scope == "scene" and envelope["candidate"] is not None:
        raise ValueError("action_review_scene_candidate_forbidden")
    if "prior_frame" in envelope and (scope != "candidate"
            or envelope["prior_frame"].get("role") != "before" or envelope["frame"].get("role") != "observation"
            or envelope["prior_frame"].get("window_identity") != envelope["frame"].get("window_identity")
            or envelope["action"].get("freshness_context", {}).get("schema") != "action_freshness.v1"):
        raise ValueError("action_review_freshness_binding_invalid")


def _condition(envelope):
    return (FRESHNESS_CONDITION if "prior_frame" in envelope else
        CANDIDATE_CONDITION if envelope["scope"] == "candidate" else SCENE_CONDITION)


def _frames(envelope):
    return ([deepcopy(envelope["prior_frame"])] if "prior_frame" in envelope else []) + [deepcopy(envelope["frame"])]


def review_preflight(service, *, condition=CANDIDATE_CONDITION):
    result = {"ready": False, "authorizes_action": False, "condition": condition}
    if service is None or getattr(service, "enabled", False) is not True:
        return {**result, "reason": "decision_service_disabled"}
    profile = service.profile
    if getattr(profile, "contract_version", None) != "decision_profile.v2":
        return {**result, "reason": "decision_profile_v2_required"}
    if profile.review_policy == "always_main":
        return {**result, "reason": "decision_always_main"}
    if service.adoption_mode != "auto":
        return {**result, "reason": "decision_auto_required"}
    if not service.auto_condition_allowed(condition):
        return {**result, "reason": "decision_condition_not_allowlisted"}
    status = service.status()
    result.update(profile_sha256=decision_profile_sha256(profile), service_status=status)
    budget = status.get("budget", {})
    remaining = budget.get("remaining") if isinstance(budget, dict) else None
    if remaining is None:
        remaining = status.get("remaining")
    if remaining == 0:
        return {**result, "reason": "decision_scope_request_cap"}
    readiness = service.readiness()
    if readiness.get("ready") is not True:
        return {**result, "reason": "decision_service_unavailable", "readiness": readiness}
    return {**result, "ready": True, "reason": None}


def _assessment(envelope, disposition, *, reason=None, **extra):
    return {"schema": "action_assessment.v1", "scope": envelope["scope"],
        "envelope_sha256": envelope["envelope_sha256"], "disposition": disposition,
        "reason": reason, "authorizes_action": False, **extra}


def _assess(service, envelope, scope):
    _validate_envelope(envelope, scope)
    if service is not None and decision_profile_sha256(service.profile) != envelope["profile_sha256"]:
        raise ValueError("action_review_profile_changed")
    if perf_counter_ns() >= envelope["deadline_ns"]:
        return _assessment(envelope, "unavailable", reason="action_review_deadline_expired")
    condition = _condition(envelope)
    preflight = review_preflight(service, condition=condition)
    if not preflight["ready"]:
        return _assessment(envelope, "unavailable", reason=preflight["reason"], preflight=preflight)
    digest = envelope["envelope_sha256"]
    request = {"request_id": "action-review-" + digest[:40],
        "execution_request_id": "attempt-" + _digest([envelope["run_id"], envelope["step_id"], envelope["attempt_id"]])[:40],
        "condition": condition, "frames": _frames(envelope), "phase": "before_action",
        "step_id": envelope["step_id"], "review_context": deepcopy(envelope["review_context"]),
        "action": {**deepcopy(envelope["action"]), "candidate": deepcopy(envelope["candidate"]),
            "review_scope": scope, "envelope_sha256": digest,
            "target_window_identity": deepcopy(envelope["frame"]["window_identity"])}}
    answer = _evaluate(service, **request, deadline_ns=envelope["deadline_ns"])
    if perf_counter_ns() >= envelope["deadline_ns"]:
        return _assessment(envelope, "unavailable", reason="action_review_deadline_expired", judgment=answer)
    binding = answer.get("evaluation_request")
    passed = answer.get("adopted") is True and answer.get("verdict") == "success"
    return _assessment(envelope, "pass" if passed else "review", reason=answer.get("reason"),
        judgment=answer, evaluation_request=binding)


def assess_candidate(service, *, envelope):
    return _assess(service, envelope, "candidate")


def assess_scene(service, *, envelope):
    return _assess(service, envelope, "scene")


def _validate_result_binding(service, result, *, envelope, cancelled=None, require_pass=True):
    try:
        _validate_envelope(envelope, envelope["scope"])
        if (cancelled is not None and cancelled() or perf_counter_ns() >= envelope["deadline_ns"]
                or result.get("scope") != envelope["scope"]
                or require_pass and result.get("disposition") != "pass"
                or result.get("envelope_sha256") != envelope["envelope_sha256"]
                or result.get("authorizes_action") is not False
                or decision_profile_sha256(service.profile) != envelope["profile_sha256"]):
            return False
        request = result["evaluation_request"]
        expected_action = {**deepcopy(envelope["action"]), "candidate": deepcopy(envelope["candidate"]),
            "review_scope": envelope["scope"], "envelope_sha256": envelope["envelope_sha256"],
            "target_window_identity": deepcopy(envelope["frame"]["window_identity"])}
        if (request["action"] != expected_action
                or request["request_id"] != "action-review-" + envelope["envelope_sha256"][:40]
                or request["execution_request_id"] != "attempt-" + _digest([
                    envelope["run_id"], envelope["step_id"], envelope["attempt_id"]])[:40]
                or request["step_id"] != envelope["step_id"]
                or request["frames"] != _frames(envelope)
                or request["review_context"] != envelope["review_context"]
                or request["phase"] != "before_action"
                or request["condition"] != _condition(envelope)):
            return False
        raw = result["judgment"]["judgment_result"]
        return (not require_pass or raw.get("adopted") is True and raw.get("verdict") == "success") and service.validate_result(raw, **request) is True
    except (KeyError, TypeError, ValueError, OSError):
        return False


def validate_assessment(service, result, *, envelope, cancelled=None):
    return _validate_result_binding(service, result, envelope=envelope, cancelled=cancelled)


def validate_scene_assessment(service, result, *, envelope, cancelled=None):
    if not isinstance(envelope, dict) or envelope.get("scope") != "scene":
        return False
    return _validate_result_binding(service, result, envelope=envelope,
        cancelled=cancelled, require_pass=False)


@contextmanager
def action_review_scope(service, *, context=None, cancelled=None, deadline_ns=None):
    if context is None:
        yield None
        return
    if _SCOPE.get() is not None:
        raise ValueError("action_review_scope_overlap")
    context = normalize_action_review_context(context)
    deadline_ns = (_deadline(deadline_ns) if deadline_ns is not None else
        perf_counter_ns() + context["budget_ms"] * 1_000_000)
    scope = {"service": service, "context": context, "cancelled": cancelled, "deadline_ns": deadline_ns,
        "owner": get_ident(), "active": True, "assessment": None, "envelope": None}
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        scope["active"] = False
        _SCOPE.reset(token)


def current_action_review():
    scope = _SCOPE.get()
    if scope is not None and (scope["active"] is not True or scope["owner"] != get_ident()):
        raise ValueError("action_review_scope_revoked")
    return scope
