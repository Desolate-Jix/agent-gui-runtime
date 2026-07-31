from __future__ import annotations

from typing import Any


def model_io_trace(
    provider_response: Any | None = None,
    *,
    error: Exception | None = None,
) -> dict[str, Any] | None:
    if provider_response is not None:
        raw_response = getattr(provider_response, "raw_response", None)
        raw = raw_response if isinstance(raw_response, dict) else {}
        attempts = raw.get("attempts") if isinstance(raw.get("attempts"), list) else []
        model_json = raw.get("model_json") if isinstance(raw.get("model_json"), dict) else {}
        model_name = raw.get("model_name") or model_json.get("model_name") or model_json.get("provider")
        return {
            "contract_version": "model_io_trace_v1",
            "status": "success",
            "provider": getattr(provider_response, "provider", None),
            "model_name": model_name,
            "raw_text": getattr(provider_response, "raw_text", None) or raw.get("raw_text"),
            "raw_response": raw,
            "attempt_count": len(attempts),
            "attempts": attempts,
        }
    if error is not None:
        diagnostics = getattr(error, "diagnostics", None)
        if isinstance(diagnostics, dict):
            return {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                **diagnostics,
            }
    return None


def attach_model_io(
    result_payload: dict[str, Any],
    provider_response: Any | None,
) -> None:
    model_io = model_io_trace(provider_response)
    if model_io is not None:
        result_payload["model_io"] = model_io


def model_io_failure_payload(exc: Exception) -> dict[str, Any] | None:
    return model_io_trace(error=exc)
