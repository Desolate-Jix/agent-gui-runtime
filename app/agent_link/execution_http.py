"""共享宿主 canonical 单步路由的独立认证与严格传输。"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool


_SHA = re.compile(r"^[0-9a-f]{64}$")
_CONFIRMATION = re.compile(r"^grounded-confirmation\.[0-9a-f]{64}$")


def install_execution_route(
    app: FastAPI,
    *,
    controller: Any,
    token_digest: str,
    max_request_bytes: int = 4096,
) -> None:
    if not callable(getattr(controller, "execute_server", None)):
        raise TypeError("execution controller must provide execute_server")
    if not isinstance(token_digest, str) or _SHA.fullmatch(token_digest) is None:
        raise ValueError("execution token digest is invalid")
    if type(max_request_bytes) is not int or not 1 <= max_request_bytes <= 4096:
        raise ValueError("execution request limit is invalid")

    @app.post("/action/execute_recognition_plan")
    async def execute_recognition_plan(request: Request) -> JSONResponse:
        if request.client is None or request.client.host != "127.0.0.1":
            return _failure(403, "loopback_required", "only 127.0.0.1 is permitted")
        raw_headers = list(request.scope.get("headers", ()))
        if any(name.lower() == b"origin" for name, _ in raw_headers):
            return _failure(403, "origin_forbidden", "browser origins are not accepted")
        authorizations = [
            value.decode("latin-1")
            for name, value in raw_headers
            if name.lower() == b"authorization"
        ]
        if len(authorizations) != 1:
            return _failure(
                401, "authentication_required", "exact Bearer authentication is required"
            )
        prefix = "Bearer "
        supplied = authorizations[0]
        if not supplied.startswith(prefix) or not supplied[len(prefix):]:
            return _failure(
                401, "authentication_required", "exact Bearer authentication is required"
            )
        supplied_digest = hashlib.sha256(
            supplied[len(prefix):].encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(supplied_digest, token_digest):
            return _failure(401, "authentication_failed", "execution authentication failed")
        content_types = [
            value.decode("latin-1").strip().lower()
            for name, value in raw_headers
            if name.lower() == b"content-type"
        ]
        if content_types != ["application/json"]:
            return _failure(
                415, "content_type_required", "content-type must be application/json"
            )
        lengths = [
            value.decode("latin-1")
            for name, value in raw_headers
            if name.lower() == b"content-length"
        ]
        if len(lengths) > 1:
            return _failure(400, "invalid_request", "content length is invalid")
        if lengths:
            try:
                if not lengths[0].isascii() or not lengths[0].isdigit():
                    raise ValueError
                if int(lengths[0]) > max_request_bytes:
                    return _failure(413, "request_too_large", "request body exceeds limit")
            except ValueError:
                return _failure(400, "invalid_request", "content length is invalid")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_request_bytes:
                return _failure(413, "request_too_large", "request body exceeds limit")
            chunks.append(chunk)
        try:
            payload = json.loads(
                b"".join(chunks),
                object_pairs_hook=_unique_object,
                parse_constant=_invalid_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            return _failure(400, "invalid_json", "request body must be strict JSON")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"confirmation_id"}
            or not isinstance(payload.get("confirmation_id"), str)
            or _CONFIRMATION.fullmatch(payload["confirmation_id"]) is None
        ):
            return _failure(400, "invalid_request", "request body is invalid")
        try:
            result = await run_in_threadpool(
                controller.execute_server,
                confirmation_id=payload["confirmation_id"],
            )
            from app.desktop_review.single_step import validate_single_step_response

            result = validate_single_step_response(
                result,
                confirmation_id=payload["confirmation_id"],
            )
        except Exception as error:
            from app.desktop_review.single_step import NativeSingleStepError

            if isinstance(error, NativeSingleStepError):
                code = error.code
                message = error.message
                unknown = error.result_unknown
            else:
                code, message, unknown = (
                    "runtime_consume_failed",
                    "grounded single-step result is unknown",
                    True,
                )
            status = 409 if unknown is False else 503
            return _failure(status, code, message, result_unknown=unknown)
        return JSONResponse(status_code=200, content=result)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _failure(
    status: int,
    code: str,
    message: str,
    *,
    result_unknown: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "result_unknown": result_unknown,
            }
        },
    )


__all__ = ["install_execution_route"]
