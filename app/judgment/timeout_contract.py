"""超时只保存固定阶段、固定码及已经验证的计量，不保存异常原文。"""
import math
import re


PHASES = {"admission", "preparation", "queue", "http", "parse", "service_deadline"}
SUFFIXES = {"timeout", "provider_timeout", "provider_queue_timeout", "provider_budget_expired",
    "connect_timeout", "read_timeout", "write_timeout", "pool_timeout", "parse_deadline",
    "stage_budget_expired", "outer_budget_expired"}
FIELDS = {"phase", "code", "usage", "http_elapsed_ms", "server_processing_ms", "provider_request_id"}


def validate_timeout_diagnostic(value):
    if (type(value) is not dict or set(value) != FIELDS or type(value.get("phase")) is not str
            or value["phase"] not in PHASES):
        raise ValueError("decision_timeout_diagnostic_invalid")
    code = value["code"]
    if type(code) is not str or not any(code == prefix + suffix
            for prefix in ("decision_", "ordinary_review_") for suffix in SUFFIXES):
        raise ValueError("decision_timeout_diagnostic_invalid")
    result = dict(value)
    if value["usage"] is not None:
        from .openai_decisions import _usage_counts
        result["usage"] = _usage_counts(value["usage"])
    for key in ("http_elapsed_ms", "server_processing_ms"):
        number = value[key]
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            raise ValueError("decision_timeout_diagnostic_invalid")
    request_id = value["provider_request_id"]
    if request_id is not None and (type(request_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) is None):
        raise ValueError("decision_timeout_diagnostic_invalid")
    return result


def timeout_diagnostic(phase, code, measurements=None):
    measurements = measurements or {}
    return validate_timeout_diagnostic({"phase": phase, "code": code,
        **{key: measurements.get(key) for key in FIELDS - {"phase", "code"}}})


class ProviderTimeout(TimeoutError):
    def __init__(self, code, *, phase, measurements=None, diagnostic_code=None):
        super().__init__(code)
        self.diagnostic = timeout_diagnostic(phase, diagnostic_code or code, measurements)


def review_timeout_diagnostic(error):
    diagnostic = getattr(error, "diagnostic", None)
    if diagnostic is not None:
        diagnostic = validate_timeout_diagnostic(diagnostic)
        code = diagnostic["code"]
        if code.startswith("decision_"):
            diagnostic["code"] = "ordinary_review_" + code[len("decision_"):]
        return diagnostic
    code = str(error)
    if code.startswith("decision_"):
        code = "ordinary_review_" + code[len("decision_"):]
    if code not in {"ordinary_review_" + suffix for suffix in SUFFIXES}:
        code = "ordinary_review_timeout"
    phase = "queue" if "queue" in code else "preparation" if "budget_expired" in code else "http"
    return timeout_diagnostic(phase, code)
