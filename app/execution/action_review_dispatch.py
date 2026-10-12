"""在原动作线程采用合并审核；数据结果自身不能派发输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.judgment.service import decision_profile_sha256
from .action_review import (build_action_review, assess_candidate, validate_assessment,
    current_action_review)
from .decision_check import DecisionCheckRejected, _candidate, _identity, decision_frame


def _reject(scope, reason):
    result = {"status": "invalidated", "reason": reason, "verdict": "uncertain",
        "adopted": False, "authorizes_action": False, "automatic_retry_allowed": False,
        "action_assessment": deepcopy(scope.get("assessment"))}
    raise DecisionCheckRejected(reason, result)


def review_original_action(*, capture, identity, candidate, point, goal, click_kind,
                           manager, validate_binding):
    scope = current_action_review()
    if scope is None:
        return None
    if scope["assessment"] is not None:
        _reject(scope, "action_review_already_consumed")
    if scope["cancelled"] and scope["cancelled"]():
        _reject(scope, "action_review_cancelled")
    service, context = scope["service"], scope["context"]
    if service is None:
        _reject(scope, "action_review_service_unavailable")
    bound = manager.get_bound_window()
    bound_handle, bound_pid = bound.handle, bound.process_id
    rect = [bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom]
    frame = decision_frame(capture, identity, role="before")
    # 调用方已通过维护定位器核对当前目标区域；保存来源，不混用原截图编号。
    selected = _candidate(candidate, point)
    origin = deepcopy(selected)
    selected["capture_id"] = frame["capture_id"]
    step = next(row for row in context["plan"]["steps"] if row["step_id"] == context["step_id"])
    expected_goal = step["action"].get("field_goal", step["action"].get("goal"))
    if goal != expected_goal:
        _reject(scope, "action_review_original_goal_mismatch")
    action = {"operation": "execute_recognition_plan", "goal": goal, "click_kind": click_kind,
        "source_candidate": origin, "permitted_action": deepcopy(step["action"])}
    from app.core.agent_grounding_target import current_agent_grounding
    from app.core.visual_submit_target import VisualSubmitTarget
    if type(current_agent_grounding()) is VisualSubmitTarget:
        action["visual_submit_phase"] = "reanchor_enter"
    read_popup = getattr(manager, "read_owned_foreground_popup", None)
    popup_fact = deepcopy(read_popup(bound)) if callable(read_popup) else None
    action["native_popup_fact"] = popup_fact
    envelope = build_action_review(scope="candidate", plan=context["plan"], step=step,
        run_id=context["run_id"], attempt_id=context["attempt_id"], capture=capture,
        identity=identity, candidate=selected, action=action,
        profile_sha256=decision_profile_sha256(service.profile), deadline_ns=scope["deadline_ns"])
    scope["envelope"] = envelope
    scope["assessment"] = assess_candidate(service, envelope=envelope)
    def validate():
        if (current_action_review() is not scope or not validate_assessment(service, scope["assessment"],
                envelope=envelope, cancelled=scope["cancelled"])):
            _reject(scope, "action_review_not_adoptable")
        current_bound = manager.get_bound_window()
        if (current_bound is None or current_bound.handle != bound_handle
                or current_bound.process_id != bound_pid
                or [current_bound.rect.left, current_bound.rect.top,
                    current_bound.rect.right, current_bound.rect.bottom] != rect):
            _reject(scope, "action_review_window_changed")
        try:
            # 认证帧不得被改写；实时边界只核对身份和原候选，不再重拍做语义否决。
            if sha256(Path(frame["image_path"]).read_bytes()).hexdigest() != frame["sha256"]:
                _reject(scope, "action_review_source_changed")
            latest_identity, latest_candidate = validate_binding()
            if _identity(latest_identity) != frame["window_identity"]:
                _reject(scope, "action_review_window_changed")
            latest = _candidate(latest_candidate, point)
            if any(latest[key] != selected[key] for key in ("candidate_id", "bbox", "click_point", "source")):
                _reject(scope, "action_review_candidate_changed")
        except DecisionCheckRejected:
            raise
        except (ValueError, OSError, RuntimeError) as error:
            _reject(scope, "action_review_revalidation_failed:" + type(error).__name__)
        # 原生读取也消耗预算，不能在回调跨期后继续派发。
        if perf_counter_ns() >= scope["deadline_ns"] or scope["cancelled"] and scope["cancelled"]():
            _reject(scope, "action_review_not_adoptable")
    validate()
    box = selected["bbox"]
    # 目标可用性已由认证审核覆盖；原生遮挡检查只约束真实点击足迹，原候选绑定不变。
    click_visibility = {"target_bbox": {"x": point["x"], "y": point["y"], "width": 1, "height": 1},
        "candidate_bbox": {"x": box["x"], "y": box["y"], "width": box["w"], "height": box["h"]},
        "scope": "reviewed_click_point", "reason": "authenticated_decision_target_usable"}
    return {"assessment": deepcopy(scope["assessment"]), "validate": validate,
        "scope": scope, "frame": frame, "candidate": selected, "click_visibility": click_visibility}
