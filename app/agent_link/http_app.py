from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .contracts import AgentLinkError
from .service import AgentLinkService
from .feedback_view import compact_feedback_view
from .interface_capability import INTERFACE_RELEARNING_CAPABILITY

_AGENT_OPERATIONS = {"status", "submit_batch", "read_feedback", "read_feedback_view", "submit_candidate", "search_workflow_memory", "get_workflow_memory", "start_learning_segment", "get_learning_segment", "finish_learning_segment", "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime", "observe_learning_screen"}
_AGENT_OPERATIONS.add("submit_observed_interface_learning")
_AGENT_OPERATIONS.update({"inspect_learning_content", "read_learning_content"})
_AGENT_OPERATIONS.update({"prepare_fresh_learning_runtime", "request_fresh_learning_action",
                          "get_fresh_learning_runtime", "cancel_fresh_learning_runtime", "request_learning_action", "get_learning_action_result"})
_AGENT_OPERATIONS.update({"search_interface_memory", "get_interface_memory", "request_interface_membership"})
_AGENT_OPERATIONS.update({"search_workflow_projects", "get_workflow_project_memory"})
_AGENT_OPERATIONS.update(INTERFACE_RELEARNING_CAPABILITY["operations"])
_AGENT_OPERATIONS.update({"discover_applications", "request_application_launch", "get_application_launch"})
_REVIEWER_OPERATIONS = {"create_connection", "revoke_connection", "list_batches", "list_connections", "get_batch", "record_feedback", "withdraw_issue"}
_FEEDBACK_VIEW_CAPABILITY = {
    "operation": "read_feedback_view",
    "contract_version": "agent_link_feedback_view_v1",
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _token(request: Request) -> str | None:
    value = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not value.startswith(prefix) or not value[len(prefix):]:
        return None
    return value[len(prefix):]


def create_agent_link_app(
    service: AgentLinkService, *, max_request_bytes: int = 2_500_000,
    reviewer_http: bool = True,
    execution_controller: Any | None = None,
    execution_token_digest: str | None = None,
) -> FastAPI:
    if type(reviewer_http) is not bool:
        raise TypeError("reviewer_http must be a bool")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(AgentLinkError)
    async def agent_link_error(_: Request, error: AgentLinkError) -> JSONResponse:
        status = 401 if error.code == "authentication_failed" else 409 if error.code in {"idempotency_conflict", "batch_conflict", "issue_conflict", "stale_revision"} else 400
        return _error(status, error.code, error.message)

    async def arguments(request: Request) -> dict[str, Any] | JSONResponse:
        if request.client is None or request.client.host != "127.0.0.1":
            return _error(403, "loopback_required", "only 127.0.0.1 is permitted")
        if request.headers.get("origin"):
            return _error(403, "origin_forbidden", "browser origins are not accepted")
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > max_request_bytes:
                    return _error(413, "request_too_large", "request body exceeds limit")
            except ValueError:
                return _error(400, "invalid_request", "invalid content length")
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > max_request_bytes:
                return _error(413, "request_too_large", "request body exceeds limit")
            chunks.append(chunk)
        body = b"".join(chunks)
        try:
            result = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error(400, "invalid_json", "request body must be JSON")
        if not isinstance(result, dict):
            return _error(400, "invalid_arguments", "request body must be an object")
        return result

    async def call(request: Request, role: str, operation: str) -> JSONResponse:
        permitted = _AGENT_OPERATIONS if role == "agent" else _REVIEWER_OPERATIONS
        if operation not in permitted:
            return _error(404, "operation_not_found", "operation is not available for this endpoint")
        parsed = await arguments(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        token = _token(request)
        if token is None:
            return _error(401, "authentication_required", "Bearer authentication is required")
        try:
            operation_call = service.agent_call if role == "agent" else service.reviewer_call
            service_operation = "read_feedback" if operation == "read_feedback_view" else operation
            result = await run_in_threadpool(operation_call, token, service_operation, parsed)
        except AgentLinkError as error:
            status = 401 if error.code == "authentication_failed" else 409 if error.code in {"idempotency_conflict", "batch_conflict", "issue_conflict", "stale_revision", "learning_busy"} else 400
            return _error(status, error.code, error.message)
        if role == "agent" and operation == "read_feedback_view":
            # 展示副本必须由显式协商端点请求，旧读取端点保持规范载荷。
            try:
                result = await run_in_threadpool(compact_feedback_view, result)
                result = {**result, "feedback_view_contract": _FEEDBACK_VIEW_CAPABILITY["contract_version"]}
            except ValueError:
                return _error(500, "invalid_feedback", "stored feedback cannot be presented")
        if role == "agent" and operation == "status":
            result = {**result, "feedback_view": dict(_FEEDBACK_VIEW_CAPABILITY)}
        return JSONResponse(status_code=200, content=result)

    @app.post("/agent/{operation}")
    async def agent(request: Request, operation: str) -> JSONResponse:
        return await call(request, "agent", operation)

    if reviewer_http:
        @app.post("/reviewer/{operation}")
        async def reviewer(request: Request, operation: str) -> JSONResponse:
            return await call(request, "reviewer", operation)

    if (execution_controller is None) != (execution_token_digest is None):
        raise ValueError("execution controller and token digest must be provided together")
    if execution_controller is not None:
        from .execution_http import install_execution_route

        install_execution_route(
            app,
            controller=execution_controller,
            token_digest=execution_token_digest,
        )

    return app
