from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from mcp.types import CallToolResult

from .feedback_view import compact_feedback_view
from .contracts import (
    ObservedRegionInput, InterfaceRelearningChanges, LearnedControlSelectionInput,
    MAX_LOCAL_IMAGE_RESPONSE_BYTES,
)
from .interface_capability import INTERFACE_CONTENT_CAPABILITY, WORKFLOW_PROJECT_MEMORY_CAPABILITY, INTERFACE_RELEARNING_CAPABILITY
from .artifacts import (
    ArtifactCatalog,
    BridgeBatchInput,
    BridgeCandidateInput,
    BridgeGraphCandidateInput,
    expand_batch,
    expand_candidate,
    load_artifact_catalog,
)
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


_FEEDBACK_VIEW_CAPABILITY = {
    "operation": "read_feedback_view",
    "contract_version": "agent_link_feedback_view_v1",
}
_WORKFLOW_MEMORY_CAPABILITY = {
    "contract_version": "agent_workflow_memory_v1",
    "operations": ["search_workflow_memory", "get_workflow_memory"],
}
_WORKFLOW_MEMORY_ERROR_CODES = {
    "invalid_arguments", "not_found", "memory_source_unavailable",
    "stale_revision", "memory_too_large",
}
_LEARNING_SEGMENT_CAPABILITY = {
    "contract_version": "agent_learning_segment_v1",
    "operations": ["start_learning_segment", "get_learning_segment", "finish_learning_segment"],
}
_LEARNING_ERROR_CODES = {
    "invalid_arguments", "not_found", "connection_revoked", "stale_revision",
    "idempotency_conflict", "learning_busy", "learning_source_unavailable",
    "operation_forbidden", "persistence_failed",
}
_LEARNING_RUNTIME_CAPABILITY = {
    "contract_version": "agent_learning_runtime_v1",
    "operations": ["prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime"],
}
_INTERFACE_CONTENT_CAPABILITY = INTERFACE_CONTENT_CAPABILITY
_WORKFLOW_PROJECT_MEMORY_CAPABILITY = WORKFLOW_PROJECT_MEMORY_CAPABILITY
_INTERFACE_ERROR_CODES = {
    "invalid_arguments", "not_found", "interface_source_unavailable", "operation_forbidden",
    "connection_revoked", "stale_revision", "idempotency_conflict",
    "persistence_failed",
}
_PROJECT_ERROR_CODES = _INTERFACE_ERROR_CODES
_REVIEWED_ACTION_CAPABILITY = {"contract_version": "agent_reviewed_learning_action_v1", "operations": ["request_learning_action", "get_learning_action_result"]}
_FRESH_RUNTIME_CAPABILITY = {"contract_version": "agent_fresh_learning_runtime_v1", "operations": [
    "prepare_fresh_learning_runtime", "request_fresh_learning_action",
    "get_fresh_learning_runtime", "cancel_fresh_learning_runtime"]}
_LEARNING_RUNTIME_ERROR_CODES = {
    "runtime_prepare_failed", "runtime_cleanup_pending", "learning_busy",
    "invalid_arguments", "not_found", "connection_revoked", "operation_forbidden",
    "idempotency_conflict", "learning_source_unavailable",
}
_LEARNING_OBSERVATION_CAPABILITY = {
    "contract_version": "agent_learning_observation_v1",
    "operations": ["observe_learning_screen", "submit_observed_interface_learning"],
}
_LEARNING_CONTENT_CAPABILITY = {
    "contract_version": "agent_learning_content_v1",
    "operations": ["inspect_learning_content", "read_learning_content"],
}
_APPLICATION_STARTUP_CAPABILITY = {
    "contract_version": "agent_application_startup_v1",
    "operations": ["discover_applications", "request_application_launch", "get_application_launch"],
}
_LEARNING_CONTENT_ERROR_CODES = {
    "content_source_stale", "content_region_unavailable", "content_read_failed",
    "content_inspection_unavailable", "content_invalid_arguments", "learning_busy",
    "learning_source_unavailable", "capture_window_minimized", "capture_window_occluded",
    "idempotency_conflict",
}
_LEARNING_OBSERVATION_ERROR_CODES = {
    "invalid_arguments", "not_found", "connection_revoked", "operation_forbidden",
    "idempotency_conflict", "learning_busy", "learning_capacity_exceeded",
    "learning_source_unavailable", "observation_failed", "observation_too_large",
    "persistence_failed", "learning_runtime_unavailable", "stale_revision",
    "invalid_evidence",
    "capture_window_minimized", "capture_window_occluded",
}


class ReviewedScrollParametersInput(BaseModel):
    """MCP 只声明既有审核滚动参数；服务端仍由共享领域类型复核。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    contract_version: Literal["reviewed_scroll_parameters_v1"]
    target_container_id: str = Field(min_length=1, max_length=256)
    axis: Literal["vertical"]
    direction: Literal["up", "down"]
    wheel_clicks: int = Field(ge=1, le=20)
    unit: Literal["wheel_detent"]


class AgentLinkLearningError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link learning segment request failed: {code}")


class AgentLinkMemoryError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link workflow memory request failed: {code}")


class AgentLinkInterfaceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link interface memory request failed: {code}")

class AgentLinkProjectError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link workflow project request failed: {code}")


class AgentLinkLearningRuntimeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link learning runtime request failed: {code}")


class AgentLinkLearningObservationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link learning observation request failed: {code}")


class AgentLinkLearningContentError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Agent Link learning content request failed: {code}")


class AgentLinkTransportTimeout(RuntimeError):
    def __init__(self) -> None:
        self.code = "transport_timeout_outcome_unknown"
        super().__init__(
            "Agent Link request timed out; outcome is unknown. "
            "Read the same operation status before retrying. The bridge did not resend the request."
        )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def _base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("AGENT_LINK_BASE_URL must be http://127.0.0.1:PORT") from error
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or port is None or not 1 <= port <= 65535 or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise RuntimeError("AGENT_LINK_BASE_URL must be http://127.0.0.1:PORT")
    return f"http://127.0.0.1:{port}"


def _agent_token(value: Any) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 512 or not value.isascii() or any(ord(character) < 33 or ord(character) > 126 for character in value):
        raise RuntimeError("AGENT_LINK_TOKEN is invalid")
    return value


def _configuration() -> tuple[str, str]:
    base = os.environ.get("AGENT_LINK_BASE_URL", "")
    token = os.environ.get("AGENT_LINK_TOKEN", "")
    return _base_url(base), _agent_token(token)


def _response_limit(operation: str) -> int:
    image_operations = {
        "observe_learning_screen",
        "get_learning_action_result",
        "get_interface_relearning_feedback",
        *_FRESH_RUNTIME_CAPABILITY["operations"],
    }
    return MAX_LOCAL_IMAGE_RESPONSE_BYTES if operation in image_operations else 2_500_000


def _timeout_seconds(operation: str) -> int:
    long_operations = {
        "prepare_learning_runtime",
        "request_learning_action",
        "observe_learning_screen",
        # 正文只读含前后截图与双读，沿用长操作等待且超时绝不自动重发。
        "inspect_learning_content",
        "read_learning_content",
        # 项目记忆核验固定图来源并可能封存快照；等待预算不能短于实际磁盘核验。
        "get_workflow_project_memory",
        "prepare_fresh_learning_runtime",
        "request_fresh_learning_action",
        # 取消需等待已拥有资源的清理；结束学习段还会校验来源并同步动作图。
        "cancel_learning_runtime",
        "cancel_fresh_learning_runtime",
        "finish_learning_segment",
    }
    return 180 if operation in long_operations else 10


def _call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> Any:
    base_url, token = _base_url(base_url), _agent_token(token)
    try:
        data = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("Agent Link request is invalid") from error
    if len(data) > 2_500_000:
        raise RuntimeError("Agent Link request exceeds limit")
    request = Request(base_url + "/agent/" + operation, data=data, method="POST", headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        timeout = _timeout_seconds(operation)
        response_limit = _response_limit(operation)
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(response_limit + 1)
            if len(raw) > response_limit: raise RuntimeError("Agent Link service response exceeds limit")
            payload = json.loads(raw.decode("utf-8"))
    except HTTPError as error:
        try:
            response_limit = _response_limit(operation)
            raw = error.read(response_limit + 1)
            if len(raw) > response_limit: raise RuntimeError("Agent Link service error exceeds limit")
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("Agent Link service returned an invalid error response") from error
        except TimeoutError as timeout_error:
            raise AgentLinkTransportTimeout() from timeout_error
    except (URLError, OSError) as error:
        if isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError):
            raise AgentLinkTransportTimeout() from error
        raise RuntimeError("Agent Link loopback service is unavailable") from error
    if operation in {"search_interface_memory", "search_workflow_projects"} and isinstance(payload, list):
        if any(not isinstance(item, dict) for item in payload):
            raise RuntimeError("Agent Link service returned an invalid interface list")
        return payload
    if not isinstance(payload, dict):
        raise RuntimeError("Agent Link service returned an invalid response")
    if "error" in payload:
        error = payload["error"]
        if (
            operation in _LEARNING_SEGMENT_CAPABILITY["operations"]
            and isinstance(error, dict) and error.get("code") in _LEARNING_ERROR_CODES
        ):
            raise AgentLinkLearningError(error["code"])
        if (
            operation in _LEARNING_RUNTIME_CAPABILITY["operations"] + _FRESH_RUNTIME_CAPABILITY["operations"] + _REVIEWED_ACTION_CAPABILITY["operations"]
            and isinstance(error, dict) and error.get("code") in _LEARNING_RUNTIME_ERROR_CODES
        ):
            raise AgentLinkLearningRuntimeError(error["code"])
        if (
            operation in _LEARNING_OBSERVATION_CAPABILITY["operations"]
            and isinstance(error, dict) and error.get("code") in _LEARNING_OBSERVATION_ERROR_CODES
        ):
            raise AgentLinkLearningObservationError(error["code"])
        if (
            operation in _LEARNING_CONTENT_CAPABILITY["operations"]
            and isinstance(error, dict) and error.get("code") in _LEARNING_CONTENT_ERROR_CODES
        ):
            raise AgentLinkLearningContentError(error["code"])
        if (
            operation in {"search_workflow_memory", "get_workflow_memory"}
            and isinstance(error, dict)
            and error.get("code") in _WORKFLOW_MEMORY_ERROR_CODES
        ):
            raise AgentLinkMemoryError(error["code"])
        if (
            operation in _INTERFACE_CONTENT_CAPABILITY["operations"] + INTERFACE_RELEARNING_CAPABILITY["operations"]
            and isinstance(error, dict) and error.get("code") in _INTERFACE_ERROR_CODES
        ):
            raise AgentLinkInterfaceError(error["code"])
        if operation in _WORKFLOW_PROJECT_MEMORY_CAPABILITY["operations"] and isinstance(error, dict) and error.get("code") in _PROJECT_ERROR_CODES:
            raise AgentLinkProjectError(error["code"])
        if isinstance(error, dict) and error.get("code") in {"authentication_failed", "authentication_required", "connection_revoked", "idempotency_conflict", "batch_conflict", "issue_conflict", "stale_revision", "invalid_arguments", "invalid_reference", "invalid_scope", "invalid_bbox", "invalid_png", "not_found", "operation_forbidden", "operation_not_found", "request_too_large", "unsupported_version"}:
            raise RuntimeError("Agent Link request rejected")
        raise RuntimeError("Agent Link service rejected the request")
    return payload


def _read_learning_feedback(base_url: str, token: str, batch_id: str) -> dict[str, Any]:
    status = _call(base_url, token, "status", {})
    capability = status.get("feedback_view")
    if "feedback_view" not in status:
        # 仅兼容未声明新能力的旧宿主；其规范响应仍由本地展示转换处理。
        return compact_feedback_view(
            _call(base_url, token, "read_feedback", {"batch_id": batch_id})
        )
    if capability != _FEEDBACK_VIEW_CAPABILITY:
        raise RuntimeError("Agent Link feedback-view capability is invalid")
    result = _call(base_url, token, "read_feedback_view", {"batch_id": batch_id})
    if result.get("feedback_view_contract") != _FEEDBACK_VIEW_CAPABILITY["contract_version"]:
        raise RuntimeError("Agent Link feedback-view response contract is invalid")
    return compact_feedback_view(result)


def _memory_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkMemoryError as error:
        from mcp.server.mcpserver.exceptions import ToolError

        # SDK 会隐藏普通异常；只公开受控错误码，不开启全局调试或转发服务正文。
        code = error.code if error.code in _WORKFLOW_MEMORY_ERROR_CODES else "memory_source_unavailable"
        raise ToolError(f"Workflow memory request failed: {code}") from None


def _interface_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> Any:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkInterfaceError as error:
        from mcp.server.mcpserver.exceptions import ToolError

        # 仅公开稳定错误码，不转发本地异常或路径。
        code = error.code if error.code in _INTERFACE_ERROR_CODES else "interface_source_unavailable"
        raise ToolError(f"Interface memory request failed: {code}") from None

def _project_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> Any:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkProjectError as error:
        from mcp.server.mcpserver.exceptions import ToolError
        code = error.code if error.code in _PROJECT_ERROR_CODES else "interface_source_unavailable"
        raise ToolError(f"Workflow project request failed: {code}") from None


def _learning_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkTransportTimeout as error:
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError(f"{error.code}: {error}") from None
    except AgentLinkLearningError as error:
        from mcp.server.mcpserver.exceptions import ToolError

        # 仅公开稳定错误码，不转发本地路径或来源异常正文。
        raise ToolError(f"Learning segment request failed: {error.code}") from None


def _learning_runtime_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkTransportTimeout as error:
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError(f"{error.code}: {error}") from None
    except AgentLinkLearningRuntimeError as error:
        from mcp.server.mcpserver.exceptions import ToolError

        code = error.code if error.code in _LEARNING_RUNTIME_ERROR_CODES else "learning_source_unavailable"
        raise ToolError(f"Learning runtime request failed: {code}") from None


def _learning_observation_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkLearningObservationError as error:
        from mcp.server.mcpserver.exceptions import ToolError

        code = error.code if error.code in _LEARNING_OBSERVATION_ERROR_CODES else "observation_failed"
        if code in {"capture_window_minimized", "capture_window_occluded"}:
            raise ToolError(f"Learning observation request failed: {code}. "
                "请恢复并露出目标窗口后重试；未产生学习结果或输入。 / "
                "Please restore and uncover the target window before retrying; no learning result or input was produced.") from None
        raise ToolError(f"Learning observation request failed: {code}") from None


def _learning_content_tool_call(base_url: str, token: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _call(base_url, token, operation, arguments)
    except AgentLinkLearningContentError as error:
        code = error.code if error.code in _LEARNING_CONTENT_ERROR_CODES else "learning_source_unavailable"
        raise ToolError(f"Learning content request failed: {code}") from None


def _observation_mcp_result(result: dict[str, Any]) -> "CallToolResult":
    import base64
    import hashlib
    from io import BytesIO
    from PIL import Image
    from mcp.types import CallToolResult, ImageContent, TextContent
    from .contracts import MAX_LOCAL_PNG_BYTES, MAX_SCREENSHOT_DIMENSION

    reviewed = result.get("contract_version") == _REVIEWED_ACTION_CAPABILITY["contract_version"]
    relearning = result.get("contract_version") == INTERFACE_RELEARNING_CAPABILITY["contract_version"]
    if relearning and set(result) != {"contract_version", "issue", "baseline", "candidates", "screenshot",
                                     "artifact_is_authorization", "execute_binding_enabled", "action_executed"}:
        raise RuntimeError("Agent Link interface feedback response is invalid")
    after = result.get("after_observation") if reviewed else None
    screenshot = after.get("screenshot") if isinstance(after, dict) else result.get("screenshot")
    fresh = result.get("contract_version") == _FRESH_RUNTIME_CAPABILITY["contract_version"]
    flags = (("artifact_is_authorization", "operation_dispatches_input", "execution_ready")
             if fresh or reviewed else
             ("artifact_is_authorization", "execute_binding_enabled", "action_executed"))
    receipt = result.get("receipt") if reviewed else None
    reviewed_keys = {
        "contract_version", "segment_id", "preparation_id", "intent_id", "action_id",
        "phase", "claim_phase", "confirmation_id", "receipt", "after_observation", *flags,
    }
    available_receipt_keys = {
        "status", "receipt_id", "content_sha256", "outcome", "reason_code",
        "attempt_count", "dispatch_status", "effect_status", "destination_status",
        "artifact_is_authorization",
    }
    receipt_available = isinstance(receipt, dict) and receipt.get("status") == "available"
    receipt_unavailable = (
        isinstance(receipt, dict)
        and set(receipt) == {"status", "reason_code"}
        and receipt.get("status") == "unavailable"
        and isinstance(receipt.get("reason_code"), str)
    )
    receipt_safe = receipt_unavailable or (
        receipt_available
        and set(receipt) == available_receipt_keys
        and isinstance(receipt.get("receipt_id"), str)
        and isinstance(receipt.get("content_sha256"), str)
        and len(receipt["content_sha256"]) == 64
        and all(character in "0123456789abcdef" for character in receipt["content_sha256"])
        and type(receipt.get("attempt_count")) is int
        and receipt.get("artifact_is_authorization") is False
        and all(isinstance(receipt.get(key), str) for key in (
            "outcome", "reason_code", "dispatch_status", "effect_status", "destination_status"))
    )
    after_safe = (
        isinstance(after, dict)
        and (
            (after.get("status") in {"unavailable", "unknown"}
             and set(after) == {"status", "reason_code"}
             and isinstance(after.get("reason_code"), str))
            or (after.get("status") == "available"
                and set(after) == {"status", "observation_id", "capture_id", "screenshot"}
                and isinstance(after.get("observation_id"), str)
                and isinstance(after.get("capture_id"), str))
        )
    )
    if reviewed and (
        any(result.get(key) is not False for key in flags)
        or not isinstance(result.get("claim_phase"), str)
        or not set(result).issubset(reviewed_keys)
        or not receipt_safe
        or not after_safe
        or (after.get("status") == "available" and (
            not isinstance(screenshot, dict)
            or set(screenshot) != {"mime_type", "sha256", "width", "height", "png_base64"}))
    ):
        raise RuntimeError("Agent Link observation response is invalid")
    if reviewed and after.get("status") != "available":
        metadata = deepcopy(result)
        try:
            text = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            raise RuntimeError("Agent Link observation response is invalid") from None
        return CallToolResult(
            content=[TextContent(text=text)],
            structuredContent=metadata,
        )
    if (
        (not fresh and not reviewed and not relearning
         and result.get("contract_version") != _LEARNING_OBSERVATION_CAPABILITY["contract_version"])
        or not isinstance(screenshot, dict)
        or screenshot.get("mime_type") != "image/png"
        or not isinstance(screenshot.get("sha256"), str)
        or len(screenshot["sha256"]) != 64
        or type(screenshot.get("width")) is not int
        or type(screenshot.get("height")) is not int
        or screenshot["width"] <= 0
        or screenshot["height"] <= 0
        or max(screenshot["width"], screenshot["height"]) > MAX_SCREENSHOT_DIMENSION
        or any(result.get(key) is not False for key in flags)
    ):
        raise RuntimeError("Agent Link observation response is invalid")
    png_base64 = screenshot.get("png_base64")
    if (not isinstance(png_base64, str) or not png_base64
            or len(png_base64) > 4 * ((MAX_LOCAL_PNG_BYTES + 2) // 3)):
        raise RuntimeError("Agent Link observation response is invalid")
    try:
        png = base64.b64decode(png_base64, validate=True)
        if len(png) > MAX_LOCAL_PNG_BYTES or hashlib.sha256(png).hexdigest() != screenshot["sha256"]:
            raise ValueError("image digest or size differs")
        with Image.open(BytesIO(png)) as image:
            if image.format != "PNG" or image.size != (screenshot["width"], screenshot["height"]):
                raise ValueError("image dimensions or format differ")
            image.load()
    except (ValueError, OSError, Image.DecompressionBombError):
        raise RuntimeError("Agent Link observation response is invalid") from None
    metadata = deepcopy(result)
    metadata_screenshot = dict(screenshot)
    metadata_screenshot.pop("png_base64", None)
    if reviewed:
        metadata["after_observation"]["screenshot"] = metadata_screenshot
    else:
        metadata["screenshot"] = metadata_screenshot
    try:
        text = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise RuntimeError("Agent Link observation response is invalid") from None
    return CallToolResult(
        content=[
            ImageContent(data=png_base64, mimeType="image/png"),
            TextContent(text=text),
        ],
        structuredContent=metadata,
    )


def run_stdio() -> None:
    base_url, token = _configuration()
    status = _call(base_url, token, "status", {})
    memory_capability = status.get("workflow_memory")
    if "workflow_memory" in status and memory_capability != _WORKFLOW_MEMORY_CAPABILITY:
        raise RuntimeError("Agent Link workflow-memory capability is invalid")
    interface_capability = status.get("interface_content")
    if "interface_content" in status and interface_capability != _INTERFACE_CONTENT_CAPABILITY:
        raise RuntimeError("Agent Link interface-content capability is invalid")
    relearning_capability = status.get("interface_relearning")
    if "interface_relearning" in status and relearning_capability != INTERFACE_RELEARNING_CAPABILITY:
        raise RuntimeError("Agent Link interface-relearning capability is invalid")
    project_capability = status.get("workflow_project_memory")
    if "workflow_project_memory" in status and project_capability != _WORKFLOW_PROJECT_MEMORY_CAPABILITY:
        raise RuntimeError("Agent Link workflow-project capability is invalid")
    learning_capability = status.get("learning_segments")
    if "learning_segments" in status and learning_capability != _LEARNING_SEGMENT_CAPABILITY:
        raise RuntimeError("Agent Link learning-segment capability is invalid")
    runtime_capability = status.get("learning_runtime")
    if "learning_runtime" in status and runtime_capability != _LEARNING_RUNTIME_CAPABILITY:
        raise RuntimeError("Agent Link learning-runtime capability is invalid")
    reviewed_action_capability = status.get("reviewed_learning_actions")
    if "reviewed_learning_actions" in status and reviewed_action_capability != _REVIEWED_ACTION_CAPABILITY:
        raise RuntimeError("Agent Link reviewed-learning-action capability is invalid")
    fresh_capability = status.get("fresh_learning_runtime")
    if "fresh_learning_runtime" in status and fresh_capability != _FRESH_RUNTIME_CAPABILITY:
        raise RuntimeError("Agent Link fresh-learning-runtime capability is invalid")
    observation_capability = status.get("learning_observation")
    if "learning_observation" in status and observation_capability != _LEARNING_OBSERVATION_CAPABILITY:
        raise RuntimeError("Agent Link learning-observation capability is invalid")
    content_capability = status.get("learning_content")
    if "learning_content" in status and content_capability != _LEARNING_CONTENT_CAPABILITY:
        raise RuntimeError("Agent Link learning-content capability is invalid")
    application_startup_capability = status.get("application_startup")
    if "application_startup" in status and application_startup_capability != _APPLICATION_STARTUP_CAPABILITY:
        raise RuntimeError("Agent Link application-startup capability is invalid")
    catalog: ArtifactCatalog | None = None
    bundle_path = os.environ.get("AGENT_LINK_ARTIFACT_BUNDLE")
    if bundle_path:
        connection_id, task_id = status.get("connection_id"), status.get("task_id")
        if not isinstance(connection_id, str) or not isinstance(task_id, str):
            raise RuntimeError("Agent Link service returned an invalid status response")
        catalog = load_artifact_catalog(Path(bundle_path), connection_id=connection_id, task_id=task_id)
    try:
        from mcp.server import MCPServer
    except ImportError as error:
        raise RuntimeError("MCP SDK is not installed; install requirements/agent-link-dev.txt in an isolated environment") from error
    server = MCPServer(name="agent-link-inbox", description="No-action staging inbox for external learning proposals.")

    def agent_link_status() -> dict[str, Any]:
        return _call(base_url, token, "status", {})

    def submit_learning_batch(batch: BridgeBatchInput) -> dict[str, Any]:
        return _call(base_url, token, "submit_batch", expand_batch(batch, catalog))

    def read_learning_feedback(batch_id: str) -> dict[str, Any]:
        return _read_learning_feedback(base_url, token, batch_id)

    def submit_relearning_candidate(candidate: BridgeCandidateInput | BridgeGraphCandidateInput) -> dict[str, Any]:
        return _call(base_url, token, "submit_candidate", expand_candidate(candidate, catalog))

    def discover_applications() -> dict[str, Any]:
        return _call(base_url, token, "discover_applications", {})

    def request_application_launch(app_id: str, idempotency_key: str, url: str | None = None) -> dict[str, Any]:
        return _call(base_url, token, "request_application_launch", {
            "app_id": app_id, "idempotency_key": idempotency_key, "url": url,
        })

    def get_application_launch(request_id: str) -> dict[str, Any]:
        return _call(base_url, token, "get_application_launch", {"request_id": request_id})

    def search_workflow_memory(
        application_scope: dict[str, Any], query: str = "", cursor: str | None = None,
    ) -> dict[str, Any]:
        return _memory_tool_call(base_url, token, "search_workflow_memory", {
            "application_scope": application_scope, "query": query, "cursor": cursor,
        })

    def get_workflow_memory(workflow_id: str, version: str | None = None) -> dict[str, Any]:
        return _memory_tool_call(base_url, token, "get_workflow_memory", {
            "workflow_id": workflow_id, "version": version,
        })

    def search_interface_memory(query: str = "") -> list[dict[str, Any]]:
        result = _interface_tool_call(base_url, token, "search_interface_memory", {"query": query})
        if not isinstance(result, list):
            raise AgentLinkInterfaceError("interface_source_unavailable")
        return result

    def get_interface_memory(interface_id: str, version_id: str | None = None) -> dict[str, Any]:
        return _interface_tool_call(base_url, token, "get_interface_memory", {
            "interface_id": interface_id, "version_id": version_id,
        })

    def search_workflow_projects(query: str = "") -> list[dict[str, Any]]:
        result = _project_tool_call(base_url, token, "search_workflow_projects", {"query": query})
        if not isinstance(result, list):
            raise RuntimeError("Agent Link service returned an invalid workflow project list")
        return result

    def list_interface_relearning_feedback() -> dict[str, Any]:
        return _interface_tool_call(base_url, token, "list_interface_relearning_feedback", {})

    def get_interface_relearning_feedback(issue_id: str) -> Any:
        result = _interface_tool_call(base_url, token, "get_interface_relearning_feedback", {"issue_id": issue_id})
        return _observation_mcp_result(result)

    def submit_interface_relearning_candidate(issue_id: str, expected_baseline_sha256: str,
                                              changes: InterfaceRelearningChanges,
                                              idempotency_key: str) -> dict[str, Any]:
        return _interface_tool_call(base_url, token, "submit_interface_relearning_candidate", {
            "issue_id": issue_id, "expected_baseline_sha256": expected_baseline_sha256,
            "changes": changes.model_dump(exclude_unset=True), "idempotency_key": idempotency_key})

    def get_workflow_project_memory(workflow_id: str, snapshot_id: str | None = None) -> dict[str, Any]:
        return _project_tool_call(base_url, token, "get_workflow_project_memory", {
            "workflow_id": workflow_id, "snapshot_id": snapshot_id,
        })

    def request_interface_membership(
        workflow_id: str, interface_id: str, version_id: str,
        expected_revision: int, expected_sha256: str, idempotency_key: str,
    ) -> dict[str, Any]:
        return _interface_tool_call(base_url, token, "request_interface_membership", {
            "workflow_id": workflow_id, "interface_id": interface_id,
            "version_id": version_id, "expected_revision": expected_revision,
            "expected_sha256": expected_sha256, "idempotency_key": idempotency_key,
        })

    def start_learning_segment(idempotency_key: str, title: str) -> dict[str, Any]:
        return _learning_tool_call(base_url, token, "start_learning_segment", {
            "idempotency_key": idempotency_key, "title": title,
        })

    def get_learning_segment(segment_id: str) -> dict[str, Any]:
        return _learning_tool_call(base_url, token, "get_learning_segment", {"segment_id": segment_id})

    def finish_learning_segment(segment_id: str, expected_revision: int) -> dict[str, Any]:
        return _learning_tool_call(base_url, token, "finish_learning_segment", {
            "segment_id": segment_id, "expected_revision": expected_revision,
        })

    def prepare_learning_runtime(
        segment_id: str, idempotency_key: str, asset_id: str, asset_content_sha256: str,
        target_window_handle: int, target_process_id: int,
    ) -> dict[str, Any]:
        return _learning_runtime_tool_call(base_url, token, "prepare_learning_runtime", {
            "segment_id": segment_id, "idempotency_key": idempotency_key,
            "asset_id": asset_id, "asset_content_sha256": asset_content_sha256,
            "target_window_handle": target_window_handle,
            "target_process_id": target_process_id,
        })

    def get_learning_runtime(segment_id: str, preparation_id: str) -> dict[str, Any]:
        return _learning_runtime_tool_call(base_url, token, "get_learning_runtime", {
            "segment_id": segment_id, "preparation_id": preparation_id,
        })

    def cancel_learning_runtime(segment_id: str, preparation_id: str) -> dict[str, Any]:
        return _learning_runtime_tool_call(base_url, token, "cancel_learning_runtime", {
            "segment_id": segment_id, "preparation_id": preparation_id,
        })

    def request_learning_action(segment_id: str, preparation_id: str, intent_id: str,
                                action_id: str, text_values: dict[str, str] | None = None) -> dict[str, Any]:
        arguments = {"segment_id": segment_id, "preparation_id": preparation_id,
                     "intent_id": intent_id, "action_id": action_id}
        if text_values is not None:
            arguments["text_values"] = text_values
        return _learning_runtime_tool_call(base_url, token, "request_learning_action", arguments)

    def get_learning_action_result(segment_id: str, preparation_id: str) -> dict[str, Any]:
        result = _learning_runtime_tool_call(base_url, token, "get_learning_action_result", {
            "segment_id": segment_id, "preparation_id": preparation_id})
        return _observation_mcp_result(result)


    def fresh_call(operation, arguments):
        result = _learning_runtime_tool_call(base_url, token, operation, arguments)
        return _observation_mcp_result(result) if "screenshot" in result else result

    def prepare_fresh_learning_runtime(segment_id: str, batch_id: str, idempotency_key: str) -> Any:
        return fresh_call("prepare_fresh_learning_runtime", {
            "segment_id": segment_id, "batch_id": batch_id, "idempotency_key": idempotency_key})

    def request_fresh_learning_action(segment_id: str, preparation_id: str, intent_id: str,
                                      action_id: str, semantic_action: str, goal: str,
                                      text_parameters: dict[str, Any] | None = None,
                                      text_values: dict[str, str] | None = None,
                                      learned_control: LearnedControlSelectionInput | None = None,
                                      scroll_parameters: ReviewedScrollParametersInput | None = None) -> Any:
        arguments = {"segment_id": segment_id,
            "preparation_id": preparation_id, "intent_id": intent_id, "action_id": action_id,
            "semantic_action": semantic_action, "goal": goal}
        if text_parameters is not None:
            arguments["text_parameters"] = text_parameters
        if text_values is not None:
            arguments["text_values"] = text_values
        if learned_control is not None:
            arguments['learned_control'] = learned_control.model_dump()
        if scroll_parameters is not None:
            arguments["scroll_parameters"] = scroll_parameters.model_dump()
        return fresh_call("request_fresh_learning_action", arguments)

    def get_fresh_learning_runtime(segment_id: str, preparation_id: str) -> Any:
        return fresh_call("get_fresh_learning_runtime", {"segment_id": segment_id, "preparation_id": preparation_id})

    def cancel_fresh_learning_runtime(segment_id: str, preparation_id: str) -> Any:
        return fresh_call("cancel_fresh_learning_runtime", {"segment_id": segment_id, "preparation_id": preparation_id})

    def observe_learning_screen(
        segment_id: str, idempotency_key: str, application_identity: dict[str, Any],
        target_window_handle: int, target_process_id: int, title: str, meaning: str,
        goal: str | None = None,
    ) -> Any:
        result = _learning_observation_tool_call(base_url, token, "observe_learning_screen", {
            "segment_id": segment_id, "idempotency_key": idempotency_key,
            "application_identity": application_identity,
            "target_window_handle": target_window_handle,
            "target_process_id": target_process_id, "title": title, "meaning": meaning,
            "goal": goal,
        })
        return _observation_mcp_result(result)

    def submit_observed_interface_learning(segment_id: str, batch_id: str, expected_revision: int,
                                           expected_sha256: str, meaning: str,
                                           regions: list[ObservedRegionInput], idempotency_key: str,
                                           recognition_text: str | None = None) -> dict[str, Any]:
        return _learning_observation_tool_call(base_url, token, "submit_observed_interface_learning", {
            "segment_id": segment_id, "batch_id": batch_id, "expected_revision": expected_revision,
            "expected_sha256": expected_sha256, "meaning": meaning,
            "regions": [region.model_dump() for region in regions],
            "idempotency_key": idempotency_key, "recognition_text": recognition_text,
        })

    def inspect_learning_content(segment_id: str, batch_id: str) -> dict[str, Any]:
        return _learning_content_tool_call(base_url, token, "inspect_learning_content", {
            "segment_id": segment_id, "batch_id": batch_id})

    def read_learning_content(segment_id: str, inspection_id: str, region_id: str,
                              idempotency_key: str, max_chars: int = 200000) -> dict[str, Any]:
        return _learning_content_tool_call(base_url, token, "read_learning_content", {
            "segment_id": segment_id, "inspection_id": inspection_id, "region_id": region_id,
            "idempotency_key": idempotency_key, "max_chars": max_chars})

    server.add_tool(agent_link_status, name="agent_link_status", description="Read the no-action staging inbox connection status.")
    server.add_tool(submit_learning_batch, name="submit_learning_batch", description="Submit Agent-learned content to the living workspace. Valid independent interfaces are saved and readable without content approval; legacy proposal status does not grant or require execution authority. Screenshot references contain only an artifact ID and SHA-256, not copied base64.")
    server.add_tool(read_learning_feedback, name="read_learning_feedback", description="Read persisted reviewer notes and scoped issues; exact baselines are compact noncanonical review_baseline_view records, and review_baseline_sha256 remains the source digest.")
    server.add_tool(submit_relearning_candidate, name="submit_relearning_candidate", description="Submit a candidate tied to an open reviewer issue and exact baseline; added screenshot references contain IDs and SHA-256 only.")
    if application_startup_capability is not None:
        server.add_tool(discover_applications, name="discover_applications", description="List local catalog applications available for a separately reviewed startup request. This only reads the catalog and never launches a program.")
        server.add_tool(request_application_launch, name="request_application_launch", description="Stage one catalog application launch for a local human to preview and independently confirm. No executable path or command arguments are accepted, and this tool never launches a program.")
        server.add_tool(get_application_launch, name="get_application_launch", description="Read the current receipt for this connection's staged application launch. A window identifier appears only after separate local human confirmation; this never launches or executes input.")
    if memory_capability is not None:
        server.add_tool(search_workflow_memory, name="search_workflow_memory", description="Search only the workflow memory IDs explicitly granted to this connection; this read never authorizes or executes an action.")
        server.add_tool(get_workflow_memory, name="get_workflow_memory", description="Read one explicitly granted workflow memory version selected by the Agent; current grounding and separate action confirmation remain required.")
    if interface_capability is not None:
        server.add_tool(search_interface_memory, name="search_interface_memory", description="Search saved interface summaries for this connection's task without a content-review gate; this read never approves or executes external actions.")
        server.add_tool(get_interface_memory, name="get_interface_memory", description="Read the latest saved interface version by default, or an explicitly selected version_id; this is read-only and never grants execution authority.")
        server.add_tool(request_interface_membership, name="request_interface_membership", description="Attach a saved interface reference to a workflow project. Saving does not require review; this never dispatches external actions.")
    if project_capability is not None:
        server.add_tool(search_workflow_projects, name="search_workflow_projects", description="Search saved workflow project summaries for this connection's task; read-only and never executes.")
        server.add_tool(get_workflow_project_memory, name="get_workflow_project_memory", description="Read the latest saved workflow project view by default, or an exact snapshot_id; read-only and never executes.")
    if relearning_capability is not None:
        server.add_tool(list_interface_relearning_feedback, name="list_interface_relearning_feedback", description="List native human feedback for saved independent interfaces in this connection's task. This does not capture or execute input.")
        server.add_tool(get_interface_relearning_feedback, name="get_interface_relearning_feedback", description="Read an interface issue with its exact saved baseline, original screenshot and current proposals. Preserve baseline_content_sha256 and region_id. This read does not adopt or execute.")
        server.add_tool(submit_interface_relearning_candidate, name="submit_interface_relearning_candidate", description="Propose corrections to the pinned independent-interface baseline. Changes may contain meaning, recognition_text and regions: regions is the COMPLETE ordered replacement list, not a partial patch. Preserve unchanged regions with at least their region_id; omitted IDs are removed in the proposal. Existing regions support optional bbox [x,y,width,height], name, kind, meaning and recognition_text. The proposal never changes current saved memory: a person compares and adopts it in the native panel. Retry with the same key and payload.")
    if learning_capability is not None:
        server.add_tool(start_learning_segment, name="start_learning_segment", description="Start one connection-owned learning segment. This metadata control does not capture, plan or execute an action; runtime attachment requires the trusted local callsite.")
        server.add_tool(get_learning_segment, name="get_learning_segment", description="Read ordered learning references and current source coverage for this connection. Unknown or missing evidence is not a successful workflow.")
        server.add_tool(finish_learning_segment, name="finish_learning_segment", description="Close a segment at its exact current revision after recorded sources settle. Empty is not learned, and closing never approves, publishes or executes a workflow.")
    if runtime_capability is not None:
        server.add_tool(prepare_learning_runtime, name="prepare_learning_runtime", description="Capture and prepare only the exact reviewed asset and target window for local learning. This never approves or executes an action; local human review remains independent.")
        server.add_tool(get_learning_runtime, name="get_learning_runtime", description="Read one connection-owned prepared learning runtime. This read never authorizes, approves or executes an action.")
        server.add_tool(cancel_learning_runtime, name="cancel_learning_runtime", description="Request cleanup for one exact prepared learning runtime. Cleanup status is reported separately and cancellation never executes an action.")
    if reviewed_action_capability is not None:
        server.add_tool(request_learning_action, name="request_learning_action", description="Request one frozen reviewed action for independent local human review. This never approves or executes input.")
        server.add_tool(get_learning_action_result, name="get_learning_action_result", description="Read only verified factual state for one requested reviewed action. This read never authorizes or executes input.")
    if observation_capability is not None:
        server.add_tool(observe_learning_screen, name="observe_learning_screen", description="Passively capture the exact Agent-selected learning screen as an unreviewed graph source. This never approves or executes an action.")
        server.add_tool(submit_observed_interface_learning, name="submit_observed_interface_learning", description="Complete the first unfilled observed interface with Agent-provided meaning and screenshot-pixel regions. Each region requires bbox [x, y, width, height], name, kind and meaning; recognition_text defaults to empty and region_id is server-generated. This saves content only and never executes actions.")
    if content_capability is not None:
        server.add_tool(inspect_learning_content, name="inspect_learning_content", description="Inspect the selected learning capture for readable content regions only. Read-only: this tool never scrolls, clicks, or executes input.")
        server.add_tool(read_learning_content, name="read_learning_content", description="Read text from one inspected region, bounded by max_chars. Check read_complete, truncated and completion_basis: completeness applies only to the selected provider range, not the entire page or job. Never scrolls, clicks, or executes input.")
    if fresh_capability is not None:
        server.add_tool(prepare_fresh_learning_runtime, name="prepare_fresh_learning_runtime", description="Prepare a fresh runtime from this connection's committed learning batch. Returns the original observation image; does not approve or execute. Capability support is not current readiness.")
        server.add_tool(request_fresh_learning_action, name="request_fresh_learning_action", description="Propose one geometry-free action for independent native human review. Optional learned_control contains exact interface_id, version_id and region_id from saved native interface memory; the server pins the content and rechecks its unique visible text anchor against current recognition/UIA. No old coordinates, latest-version fallback or content-finalization requirement. Image-only learned controls are not yet supported. This option does not expand supported action semantics or allow Apply/final submission. fill_field requires text_parameters (reviewed_text_parameters_v1); variable content also requires text_values matching exactly its declared variable name. scroll_region requires scroll_parameters (reviewed_scroll_parameters_v1) with an exact target container and vertical up/down wheel_detent count from 1 through 20. Values are frozen for the exact local preview. Never approves, executes or submits; retries must preserve the same intent, declaration, learned reference and resolved values. Other actions must omit text and scroll fields.")
        server.add_tool(get_fresh_learning_runtime, name="get_fresh_learning_runtime", description="Read the owned runtime's factual outcome and original latest available image without recapture or input. Recorded input is not verified task success.")
        server.add_tool(cancel_fresh_learning_runtime, name="cancel_fresh_learning_runtime", description="Request cleanup of the exact fresh preparation. A timeout remains pending; it does not release ownership or allow another action.")
    server.run(transport="stdio")
