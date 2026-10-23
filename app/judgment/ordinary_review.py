"""普通模型复核保留独立原始结论，不伪造概率或平均两层判断。"""
import math
import re

from .choice_contract import CHOICES, CHOICE_NAME, choice_assessment
from .timeout_contract import validate_timeout_diagnostic
from .profile import DEFAULT_MODEL, DEFAULT_REVIEW_ENDPOINT


def effective_choice(result):
    """调用方先认证完整回执，再读取最终一层的选择；本函数不授予输入权限。"""
    record = result.get("ordinary_review")
    if record is not None:
        return record.get("review_result", {}).get("choice") if record.get("status") == "completed" else None
    return (result.get("choice_result") or {}).get("choice")


def validate_review_answer(answer, digest, *, identity_spec=None):
    from .openai_decisions import _usage_counts
    fields = {"request_sha256", "review_result", "usage", "http_elapsed_ms", "server_processing_ms", "provider_request_id"}
    if identity_spec is not None:
        fields.add("identity_result")
    if type(answer) is not dict or set(answer) != fields or answer["request_sha256"] != digest:
        raise ValueError("ordinary_review_binding_invalid")
    value = answer["review_result"]
    if type(value) is not dict or set(value) != {"type", "name", "choice"} or value["name"] != CHOICE_NAME:
        raise ValueError("ordinary_review_choice_invalid")
    if not ((value["type"] == "choice" and value["choice"] in CHOICES)
            or (value["type"] == "refusal" and value["choice"] is None)):
        raise ValueError("ordinary_review_choice_invalid")
    if identity_spec is not None:
        from .target_identity import validate_identity_record
        validate_identity_record(answer["identity_result"], value, ordinary=True, spec=identity_spec)
    usage = _usage_counts(answer["usage"])
    for name in ("http_elapsed_ms", "server_processing_ms"):
        number = answer[name]
        if number is None and name == "server_processing_ms":
            continue
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ValueError("ordinary_review_timing_invalid")
    request_id = answer["provider_request_id"]
    if request_id is not None and (type(request_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) is None):
        raise ValueError("ordinary_review_request_id_invalid")
    return {**answer, "usage": usage, "review_result": dict(value)}


def combined_usage(primary, secondary):
    from .openai_decisions import _usage_counts
    first, second = _usage_counts(primary), _usage_counts(secondary)
    result = {key: first[key] + second[key] for key in ("input_tokens", "output_tokens", "total_tokens")}
    for key in ("input_tokens_details", "output_tokens_details"):
        if key in first and key in second:
            result[key] = {}
            for name in first[key].keys() & second[key].keys():
                if key == "input_tokens_details" and name == "cache_write_tokens_details":
                    result[key][name] = {ttl: first[key][name][ttl] + second[key][name][ttl]
                                         for ttl in ("ttl_30m_tokens", "ttl_12h_tokens")}
                else:
                    result[key][name] = first[key][name] + second[key][name]
    return result


def review_record_usage(record):
    if "usage" in record:
        return record["usage"]
    return (record.get("diagnostic") or {}).get("usage")


def review_metadata(profile):
    # 默认路线保留旧标记，自定义普通复核则明确标识真实配置模型。
    if profile.ordinary_review_endpoint == DEFAULT_REVIEW_ENDPOINT and profile.ordinary_review_model == DEFAULT_MODEL:
        return {"judged_by": "ordinary_luna"}
    return {"judged_by": "ordinary_review", "ordinary_review_model": profile.ordinary_review_model}


def review_assessment(profile, record):
    status = record["status"]
    if status == "completed":
        choice = record["review_result"]["choice"]
        return {"status": "completed", **choice_assessment(profile, choice),
                "reason_codes": ["ordinary_review_" + choice], **review_metadata(profile)}
    reason = record["reason"]
    return {"status": status, "verdict": "uncertain", "adopted": False,
            "disposition": "review_required", "suggested_disposition": "review_required",
            "review_scope": "runtime_diagnostic" if status != "refused" else "effect",
            "reason": reason, "reason_codes": [reason], **review_metadata(profile)}


def validate_review_record(record, digest, *, identity_spec=None):
    if type(record) is not dict or record.get("request_sha256") != digest:
        raise ValueError("ordinary_review_record_invalid")
    status = record.get("status")
    if status in ("completed", "refused"):
        fields = {"status"} | ({"reason"} if status == "refused" else set())
        answer = validate_review_answer({key: value for key, value in record.items() if key not in fields}, digest,
            identity_spec=identity_spec)
        if (answer["review_result"]["type"] == "refusal") != (status == "refused"):
            raise ValueError("ordinary_review_record_invalid")
        if status == "refused" and record["reason"] != "ordinary_review_refused":
            raise ValueError("ordinary_review_record_invalid")
    elif (status not in {"limited", "timeout", "error"}
            or set(record) not in ({"status", "reason", "request_sha256"},
                {"status", "reason", "request_sha256", "diagnostic"})
            or record["reason"] not in {"ordinary_review_request_cap", "ordinary_review_timeout",
                "ordinary_review_failed", "ordinary_review_unavailable", "ordinary_review_service_closed",
                "ordinary_review_field_content_unsupported", "ordinary_review_persistence_failed"}):
        raise ValueError("ordinary_review_record_invalid")
    if "diagnostic" in record:
        if status != "timeout":
            raise ValueError("ordinary_review_record_invalid")
        diagnostic = validate_timeout_diagnostic(record["diagnostic"])
        if not diagnostic["code"].startswith("ordinary_review_"):
            raise ValueError("ordinary_review_record_invalid")
    return record
