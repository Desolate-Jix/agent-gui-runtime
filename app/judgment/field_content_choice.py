"""首次纯视觉焦点检查的独立字段内容分类，不增加请求或输入权限。"""
import math

from .choice_contract import CHOICES as MAIN_CHOICES, choice_assessment


FIELD_CONTENT_NAME = "field_content"
FIELD_CONTENT_CHOICES = ("empty", "nonempty", "uncertain")


def field_content_requested(payload):
    action = payload.get("action") if type(payload) is dict else None
    if type(action) is not dict or "field_content_check" not in action:
        return False
    flag = action["field_content_check"]
    if (type(flag) is not dict or set(flag) != {"schema", "clear_existing"}
            or flag["schema"] != "visual_field_content.v1" or type(flag["clear_existing"]) is not bool
            or payload.get("phase") != "after_action" or action.get("operation") != "visual_field_check"
            or action.get("field_phase") != "focus" or action.get("focus_stage") != "after_click"
            or "focus_value_snapshot" in action or "field_freshness_context" in action):
        raise ValueError("decision_field_content_scope_invalid")
    return True


def field_content_question(*, input_readiness=False):
    if input_readiness:
        return {"type": "choice", "name": FIELD_CONTENT_NAME,
            "instructions": "Is the marked target input empty or nonempty? Ignore placeholder and hint text. "
                "Choose uncertain if its actual text content cannot be determined.",
            "choices": [
                {"value": "empty", "description": "The input contains no entered text."},
                {"value": "nonempty", "description": "The input contains entered text."},
                {"value": "uncertain", "description": "The input content cannot be determined."}]}
    return {"type": "choice", "name": FIELD_CONTENT_NAME,
        "instructions": "Classify the current actual content of the target field identified by action.field.field_goal. "
            "Use the supplied current screenshot evidence only. Placeholder or hint text is not a field value. "
            "empty requires visible evidence that the actual field value contains no characters; nonempty means it contains one or more characters. "
            "Choose uncertain if the field or its actual content cannot be established, including clipping, occlusion or ambiguity. "
            "Do not infer an empty value from focus, a caret, the intended future text or a past click marker. "
            "This content classification does not establish focus or authorize typing, clearing or any other action.",
        "choices": [
            {"value": "empty", "description": "The current actual field value is visibly empty; placeholder text is excluded."},
            {"value": "nonempty", "description": "The current actual field value contains one or more characters."},
            {"value": "uncertain", "description": "The supplied evidence cannot establish the current actual field content."}]}


def validate_field_content_result(value):
    fields = {"type", "name", "choice", "confidence", "probabilities"}
    if type(value) is not dict or set(value) != fields or value.get("name") != FIELD_CONTENT_NAME:
        raise ValueError("decision_field_content_result_invalid")
    if value["type"] == "refusal":
        if any(value[key] is not None for key in ("choice", "confidence", "probabilities")):
            raise ValueError("decision_field_content_refusal_invalid")
        return dict(value)
    if value["type"] != "choice" or value["choice"] not in FIELD_CONTENT_CHOICES:
        raise ValueError("decision_field_content_choice_invalid")

    def probability(item):
        if type(item) not in (int, float) or not math.isfinite(item) or not 0 <= item <= 1:
            raise ValueError("decision_field_content_probability_invalid")
        return item

    probability(value["confidence"])
    probabilities = value["probabilities"]
    if type(probabilities) is not list or len(probabilities) != len(FIELD_CONTENT_CHOICES):
        raise ValueError("decision_field_content_probabilities_invalid")
    names, total = set(), 0.0
    for item in probabilities:
        if (type(item) is not dict or set(item) != {"value", "probability"}
                or item["value"] not in FIELD_CONTENT_CHOICES or item["value"] in names):
            raise ValueError("decision_field_content_probabilities_invalid")
        names.add(item["value"])
        total += probability(item["probability"])
    if names != set(FIELD_CONTENT_CHOICES) or not math.isclose(total, 1.0, abs_tol=1e-6, rel_tol=0):
        raise ValueError("decision_field_content_probability_sum_invalid")
    return {**value, "probabilities": [dict(item) for item in probabilities]}


def field_content_assessment(profile, main_choice, content_result, *, clear_existing):
    if main_choice not in MAIN_CHOICES or type(clear_existing) is not bool:
        raise ValueError("decision_field_content_assessment_invalid")
    content = validate_field_content_result(content_result)
    result = choice_assessment(profile, main_choice)
    # 焦点不成立时，内容分类不能改变主判断或获得输入许可。
    if main_choice != "condition_met":
        return result
    choice = content["choice"] if content["type"] == "choice" else "refused"
    result["reason_codes"].append("decision_field_content_" + choice)
    if choice in ("uncertain", "refused") or choice == "nonempty" and not clear_existing:
        result.update(verdict="failure" if choice == "nonempty" else "uncertain",
            disposition="review_required", suggested_disposition="review_required", adopted=False)
    return result
