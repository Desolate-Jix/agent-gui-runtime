"""有限主动审核策略；先确定结果，再计算交接，不创建观察或输入。"""
import json
import math
import re


def normalize_review_context(value):
    required = {"goal", "step_goal", "remaining_plan", "allowed_states"}
    optional = {"source_sha256", "source_id", "review_policy", "wait_policy"}
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        raise ValueError("decision_review_context_fields_invalid")
    for key, maximum in (("goal", 4000), ("step_goal", 4000), ("source_id", 200)):
        if key in value and (not isinstance(value[key], str) or not value[key].strip() or len(value[key]) > maximum):
            raise ValueError("decision_review_context_text_invalid")
    for key, count, maximum in (("remaining_plan", 256, 2000), ("allowed_states", 32, 1000)):
        items = value[key]
        if (not isinstance(items, list) or len(items) > count
                or any(not isinstance(item, str) or not item.strip() or len(item) > maximum for item in items)):
            raise ValueError("decision_review_context_list_invalid")
    if "source_sha256" in value and (not isinstance(value["source_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"])):
        raise ValueError("decision_review_context_source_invalid")
    if "review_policy" in value and value["review_policy"] not in ("adaptive", "always_main"):
        raise ValueError("decision_review_context_policy_invalid")
    if "wait_policy" in value:
        wait = value["wait_policy"]
        if (type(wait) is not dict or set(wait) != {"loading_condition", "completion_excludes_loading"}
                or type(wait["loading_condition"]) is not str or not wait["loading_condition"].strip()
                or len(wait["loading_condition"]) > 4000 or type(wait["completion_excludes_loading"]) is not bool):
            raise ValueError("decision_wait_policy_invalid")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ValueError("decision_review_context_too_large")
    # 冻结对象，调用者后续修改不能改变请求或已认证结果。
    return json.loads(encoded)


def normalize_assessment_context(value):
    fields = {"assessment_round", "original_receipt_sha256", "evidence_set_sha256", "elapsed_ms", "timeout_seconds"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("decision_assessment_context_fields_invalid")
    if type(value["assessment_round"]) is not int or value["assessment_round"] not in (0, 1, 2):
        raise ValueError("decision_assessment_round_invalid")
    for key in ("original_receipt_sha256", "evidence_set_sha256"):
        if type(value[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
            raise ValueError("decision_assessment_hash_invalid")
    elapsed, timeout = value["elapsed_ms"], value["timeout_seconds"]
    if (type(elapsed) not in (int, float) or not 0 <= elapsed < 12000 or not math.isfinite(elapsed)
            or type(timeout) not in (int, float) or not 0 < timeout <= (12000 - elapsed) / 1000
            or not math.isfinite(timeout)):
        raise ValueError("decision_assessment_budget_invalid")
    return json.loads(json.dumps(value, allow_nan=False))


def enabled_predicates(profile, phase, context=None):
    if profile.decision_format == "choice":
        return []
    danger = "unsafe_effect" if phase == "before_action" else "visible_error"
    return (["condition_met", danger] + (["needs_agent_review"] if profile.proactive_review else [])
            + (["still_progressing"] if phase == "after_action" and (context or {}).get("wait_policy") else []))


def effective_review_policy(profile, context):
    return "always_main" if (profile.review_policy == "always_main"
        or (context or {}).get("review_policy") == "always_main") else "adaptive"


def metadata(profile, phase, context=None):
    if profile.decision_format == "choice":
        return {"schema_version": "decision_assessment.v2", "decision_format": "choice", "choice_result": None,
            "disposition": "review_required", "suggested_disposition": None, "review_scope": "runtime_diagnostic",
            "reason_codes": [], "enabled_predicates": [], "predicates": {}, "probabilities": {}}
    names = enabled_predicates(profile, phase, context)
    danger = "unsafe_effect" if phase == "before_action" else "visible_error"
    states = {name: {"type": "unavailable" if name in names else "not_requested", "probability": None}
              for name in ("condition_met", danger, "needs_agent_review", "still_progressing")}
    return {"schema_version": "decision_assessment.v2", "disposition": "review_required",
            "suggested_disposition": None, "review_scope": "runtime_diagnostic", "reason_codes": [],
            "enabled_predicates": names, "predicates": states, "probabilities": {name: None for name in states}}


def require_review(result, reason, *, scope="runtime_diagnostic"):
    result.update(disposition="review_required", review_scope=scope, adopted=False, reason=reason)
    result["reason_codes"] = list(dict.fromkeys([*result.get("reason_codes", []), reason]))
    return result


def assessment(profile, phase, probabilities, context=None):
    danger = "unsafe_effect" if phase == "before_action" else "visible_error"
    met, error = probabilities["condition_met"], probabilities[danger]
    high, low = profile.pass_threshold, profile.fail_threshold
    result_threshold = (profile.before_action_pass_threshold if phase == "before_action"
                        else profile.after_action_pass_threshold)
    result_high = result_threshold if result_threshold is not None else high
    review_threshold = profile.after_action_review_threshold if phase == "after_action" else None
    wait = (context or {}).get("wait_policy") if phase == "after_action" else None
    progressing = probabilities.get("still_progressing") if wait else None
    loading_conflict = bool(wait and wait["completion_excludes_loading"] and met >= result_high and progressing >= high)
    conflict = met >= result_high and error >= high or loading_conflict
    verdict = "uncertain" if conflict else (
        "failure" if error >= high or met <= low else
        "success" if met >= result_high and error <= low else "uncertain")
    reasons = []
    if conflict:
        reasons.append("decision_predicate_conflict")
    if loading_conflict:
        reasons.append("decision_completion_loading_conflict")
    if error >= high:
        reasons.append(danger + "_high")
    elif error > low:
        reasons.append(danger + "_gray")
    if met <= low:
        reasons.append("condition_not_met")
    elif met < result_high:
        reasons.append("condition_gray")
    review = probabilities["needs_agent_review"] if profile.proactive_review else None
    needs_review = review is not None and (review >= review_threshold if review_threshold is not None else review > low)
    if needs_review:
        reasons.append("off_plan_intervention_high" if review_threshold is not None or review >= high else "off_plan_intervention_gray")
    disposition = "continue" if verdict == "success" and not needs_review else "review_required"
    if (wait and not conflict and met <= low and progressing >= high and error <= low and not needs_review):
        # 已声明的可见加载只允许继续观察，不把尚未完成记为成功或终态失败。
        verdict, disposition = "uncertain", "observe"
        reasons.append("declared_loading_high")
    scope = "remaining_plan" if needs_review and verdict == "success" else "effect_and_plan" if needs_review else "effect"
    actual = disposition
    if profile.mode == "shadow":
        actual = "review_required"
        reasons.append("decision_shadow_advice_only")
    return {"verdict": verdict, "disposition": actual, "suggested_disposition": disposition,
            "review_scope": scope, "reason_codes": reasons,
            "adopted": profile.mode == "auto" and actual == "continue"}
