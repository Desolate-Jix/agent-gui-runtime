from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import uuid
import time
from threading import RLock
from typing import Any

from .candidate_projection import CHANGE_TYPES
from .contracts import AgentLinkError, CONTRACT_VERSION, canonical_hash, fail, parse, validate_batch, validate_candidate, validate_scope, NoteInput, IssueInput
from .review_baseline import (
    candidate_content_sha256,
    hashes_equal,
    validate_candidate_changes,
    validate_review_baseline,
    validate_graph_review_baseline,
    validate_graph_candidate,
)
from .graph_contract import GraphContractError, validate_graph_scope
from .store import AgentLinkStore
from .interface_capability import INTERFACE_CONTENT_CAPABILITY, WORKFLOW_PROJECT_MEMORY_CAPABILITY, INTERFACE_RELEARNING_CAPABILITY
from .memory_scope import (
    MEMORY_CAPABILITY,
    MEMORY_SCOPE_CONTRACT,
    validate_workflow_id,
    validate_workflow_ids,
)

_AGENT = {"status", "submit_batch", "read_feedback", "submit_candidate"}
_APPLICATION_STARTUP_OPERATIONS = {"discover_applications", "request_application_launch", "get_application_launch"}
_APPLICATION_STARTUP_CAPABILITY = {"contract_version": "agent_application_startup_v1", "operations": ["discover_applications", "request_application_launch", "get_application_launch"]}
_REVIEWER = {"create_connection", "revoke_connection", "list_batches", "list_connections", "get_batch", "record_feedback", "withdraw_issue", "set_workflow_memory_scope"}
_MEMORY_OPERATIONS = {"search_workflow_memory", "get_workflow_memory"}
_INTERFACE_OPERATIONS = {"search_interface_memory", "get_interface_memory", "request_interface_membership"}
_PROJECT_OPERATIONS = {"search_workflow_projects", "get_workflow_project_memory"}
_OBSERVED_INTERFACE_OPERATION = "submit_observed_interface_learning"
_LEARNING_CONTENT_OPERATIONS = {"inspect_learning_content", "read_learning_content"}
_LEARNING_CONTENT_CAPABILITY = {
    "contract_version": "agent_learning_content_v1",
    "operations": ["inspect_learning_content", "read_learning_content"],
}
_INTERFACE_CAPABILITY = INTERFACE_CONTENT_CAPABILITY
_PROJECT_CAPABILITY = WORKFLOW_PROJECT_MEMORY_CAPABILITY
_LEARNING_OPERATIONS = {"start_learning_segment", "get_learning_segment", "finish_learning_segment"}
_LEARNING_RUNTIME_OPERATIONS = {
    "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime",
}
_LEARNING_RUNTIME_CAPABILITY = {
    "contract_version": "agent_learning_runtime_v1",
    "operations": [
        "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime",
    ],
}
_LEARNING_CONTENT_ERROR_CODES = {
    "content_source_stale", "content_region_unavailable", "content_read_failed",
    "content_inspection_unavailable", "content_invalid_arguments", "learning_busy",
    "learning_source_unavailable", "capture_window_minimized", "capture_window_occluded",
    "idempotency_conflict",
}
_REVIEWED_ACTION_CAPABILITY = {"contract_version": "agent_reviewed_learning_action_v1", "operations": [
    "request_learning_action", "get_learning_action_result"]}
_FRESH_RUNTIME_CAPABILITY = {"contract_version": "agent_fresh_learning_runtime_v1", "operations": [
    "prepare_fresh_learning_runtime", "request_fresh_learning_action",
    "get_fresh_learning_runtime", "cancel_fresh_learning_runtime"]}
_MEMORY_ERROR_MESSAGES = {
    "invalid_arguments": "workflow memory request is invalid",
    "not_found": "workflow memory was not found",
    "memory_source_unavailable": "workflow memory source is unavailable",
    "stale_revision": "workflow memory revision is stale",
    "memory_too_large": "workflow memory response exceeds limit",
}


def _digest(value: str) -> str: return hashlib.sha256(value.encode("utf-8")).hexdigest()
def _secret(value: Any, name: str) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 512 or not value.isascii() or "\r" in value or "\n" in value: raise AgentLinkError("invalid_configuration", f"{name} must be bounded ASCII without line breaks")
    return value

def _args(value: Any, keys: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - keys or required - set(value): fail("invalid_arguments", "arguments do not satisfy the agent_link_v1 contract")
    return value

def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4000: fail("invalid_arguments", f"{name} is invalid")
    return value


class AgentLinkService:
    def __init__(self, store: AgentLinkStore, reviewer_token: str) -> None:
        self._store, self._reviewer_digest = store, _digest(_secret(reviewer_token, "reviewer token"))
        self._memory_reader_guard = RLock()
        self._memory_reader: Any | None = None
        self._interface_gateway_guard = RLock()
        self._interface_gateway: Any | None = None
        self._learning_owner_guard = RLock()
        self._learning_owner: Any | None = None
        self._learning_runtime_guard = RLock()
        self._learning_runtime_provider: Any | None = None
        self._learning_observation_guard = RLock()
        self._learning_observation_provider: Any | None = None
        self._application_startup_guard = RLock()
        self._application_startup_provider: Any | None = None

    def bind_application_startup_provider(self, reviewer_token: str, provider: Any) -> None:
        """安装同一 inbox 和本地协调器的人工启动入口。"""
        self._reviewer(reviewer_token)
        from app.desktop_review.application_startup import ApplicationStartupProvider

        if not isinstance(provider, ApplicationStartupProvider) or provider.store is not self._store:
            fail("invalid_arguments", "application startup provider must share this inbox")
        with self._application_startup_guard:
            if self._application_startup_provider is not None:
                fail("learning_busy", "application startup provider is already installed")
            self._application_startup_provider = provider

    def _application_startup_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._application_startup_guard:
            provider = self._application_startup_provider
        if provider is None:
            fail("operation_forbidden", "application startup is not enabled")
        keys = {
            "discover_applications": set(),
            "request_application_launch": {"app_id", "idempotency_key", "url"},
            "get_application_launch": {"request_id"},
        }[operation]
        required = keys - ({"url"} if operation == "request_application_launch" else set())
        args = _args(arguments, keys, required)
        identity = self._store.read(lambda state: {key: self._connection(state, token)[key]
                                                    for key in ("connection_id", "task_id")})
        method = {
            "discover_applications": provider.discover,
            "request_application_launch": provider.request,
            "get_application_launch": provider.get,
        }[operation]
        try:
            result = method(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("application_startup_unavailable", "application startup provider is unavailable") from error
        # 外部调用期间可能撤销；禁止把撤销后的结果作为 Agent 成功回执。
        self._store.read(lambda state: self._connection(state, token))
        if not isinstance(result, dict):
            fail("application_startup_unavailable", "application startup provider returned an invalid response")
        return copy.deepcopy(result)

    def _learning_content_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._learning_observation_guard:
            provider = self._learning_observation_provider
        content = getattr(provider, "content", None) if provider is not None else None
        if content is None or not callable(getattr(content, operation.replace("_learning_content", ""), None)):
            fail("operation_forbidden", "learning content access is not enabled")
        if operation == "inspect_learning_content":
            args = _args(arguments, {"segment_id", "batch_id"}, {"segment_id", "batch_id"})
            method = content.inspect
        else:
            args = _args(arguments, {"segment_id", "inspection_id", "region_id", "idempotency_key", "max_chars"},
                         {"segment_id", "inspection_id", "region_id", "idempotency_key"})
            if "max_chars" in args and (type(args["max_chars"]) is not int or not 1 <= args["max_chars"] <= 200000):
                fail("content_invalid_arguments", "max_chars is invalid")
            args.setdefault("max_chars", 200000)
            method = content.read
        identity = self._store.read(lambda state: {
            key: value for key, value in self._connection(state, token).items()
            if key in {"connection_id", "task_id"}
        })
        try:
            result = method(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            code = "content_inspection_unavailable" if operation == "inspect_learning_content" else "content_read_failed"
            raise AgentLinkError(code, "learning content provider is unavailable") from error
        self._store.read(lambda state: self._connection(state, token))
        if (not isinstance(result, dict)
                or result.get("contract_version") != "agent_learning_content_v1"
                or any(result.get(key) is not False for key in (
                    "artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
            fail("learning_source_unavailable", "learning content provider returned an invalid response")
        return copy.deepcopy(result)

    def bind_learning_observation_provider(self, reviewer_token: str, provider: Any) -> None:
        """只安装与当前宿主同根、同收件箱的可信观察入口。"""
        self._reviewer(reviewer_token)
        from app.desktop_review.learning_observation import LearningObservationProvider

        with self._learning_owner_guard:
            owner = self._learning_owner
        if (not isinstance(provider, LearningObservationProvider)
                or provider.source_owner.segments is not owner
                or owner is None or owner.store is not self._store):
            fail("invalid_arguments", "observation provider must share this inbox and owner")
        with self._learning_observation_guard:
            if self._learning_observation_provider is not None:
                fail("learning_busy", "observation provider is already installed")
            self._learning_observation_provider = provider

    def _learning_observation_call(self, token: str, arguments: Any) -> dict[str, Any]:
        with self._learning_observation_guard:
            provider = self._learning_observation_provider
        if provider is None:
            fail("operation_forbidden", "learning observation is not enabled")
        required = {"segment_id", "idempotency_key", "application_identity", "target_window_handle",
                    "target_process_id", "title", "meaning"}
        args = _args(arguments, required | {"goal"}, required)
        identity = self._store.read(lambda state: {
            key: value for key, value in self._connection(state, token).items()
            if key in {"connection_id", "task_id"}
        })
        try:
            result = provider.observe(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("observation_failed", "learning observation provider is unavailable") from error
        self._store.read(lambda state: self._connection(state, token))
        if (not isinstance(result, dict) or result.get("contract_version") != "agent_learning_observation_v1"
                or any(result.get(key) is not False for key in (
                    "artifact_is_authorization", "execute_binding_enabled", "action_executed"))):
            fail("learning_source_unavailable", "observation provider returned an invalid response")
        return copy.deepcopy(result)

    def _submit_observed_interface_learning(self, token: str, arguments: Any) -> dict[str, Any]:
        with self._learning_observation_guard:
            provider = self._learning_observation_provider
        if provider is None or not callable(getattr(provider, _OBSERVED_INTERFACE_OPERATION, None)):
            fail("operation_forbidden", "observed interface learning is not enabled")
        required = {"segment_id", "batch_id", "expected_revision", "expected_sha256", "meaning", "regions", "idempotency_key"}
        args = _args(arguments, required | {"recognition_text"}, required)
        identity = self._store.read(lambda state: {
            key: self._connection(state, token)[key] for key in ("connection_id", "task_id")
        })
        return provider.submit_observed_interface_learning(**identity, **copy.deepcopy(args))

    def bind_learning_segment_owner(self, reviewer_token: str, owner: Any) -> None:
        """只接收同一收件箱的真实本地学习所有者，不允许 Agent 自行绑定。"""
        self._reviewer(reviewer_token)
        from .learning_segments import LearningSegmentOwner

        if not isinstance(owner, LearningSegmentOwner) or owner.store is not self._store:
            fail("invalid_arguments", "learning segment owner must share this inbox")
        with self._learning_owner_guard:
            if self._learning_owner is not None and self._learning_owner is not owner:
                fail("learning_busy", "learning segment owner is already installed")
            self._learning_owner = owner

    def _learning_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._learning_owner_guard:
            owner = self._learning_owner
        if owner is None:
            fail("operation_forbidden", "learning segment controls are not enabled")
        keys = {
            "start_learning_segment": {"idempotency_key", "title"},
            "get_learning_segment": {"segment_id"},
            "finish_learning_segment": {"segment_id", "expected_revision"},
        }[operation]
        args = _args(arguments, keys, keys)
        identity = self._store.read(lambda state: {
            key: value for key, value in self._connection(state, token).items()
            if key in {"connection_id", "task_id"}
        })
        method = {
            "start_learning_segment": owner.start,
            "get_learning_segment": owner.get,
            "finish_learning_segment": owner.finish,
        }[operation]
        # 文件来源检查不能持收件箱锁；所有者写入时再次检查连接身份。
        result = method(**identity, **copy.deepcopy(args))
        self._store.read(lambda state: self._connection(state, token))
        if (
            not isinstance(result, dict)
            or result.get("contract_version") != "agent_learning_segment_v1"
            or any(result.get(key) is not False for key in (
                "artifact_is_authorization", "execute_binding_enabled", "action_executed",
            ))
        ):
            fail("learning_source_unavailable", "learning segment source returned an invalid response")
        if operation == "finish_learning_segment":
            with self._learning_observation_guard:
                provider = self._learning_observation_provider
            if provider is not None:
                result["graph"] = provider.source_owner.sync_actions(
                    **identity, segment_id=args["segment_id"])
                self._store.read(lambda state: self._connection(state, token))
        return copy.deepcopy(result)

    def bind_learning_runtime_provider(self, reviewer_token: str, provider: Any) -> None:
        """安装与当前收件箱和学习所有者一致的本地运行时提供者。"""
        self._reviewer(reviewer_token)
        from app.desktop_review.learning_runtime import LearningRuntimeProvider

        with self._learning_owner_guard:
            owner = self._learning_owner
        if (
            owner is None
            or not isinstance(provider, LearningRuntimeProvider)
            or provider.owner is not owner
            or owner.store is not self._store
        ):
            fail("invalid_arguments", "learning runtime provider must share this inbox and owner")
        with self._learning_runtime_guard:
            if self._learning_runtime_provider is not None:
                fail("learning_busy", "learning runtime provider is already installed")
            self._learning_runtime_provider = provider

    @staticmethod
    def _runtime_result(result: Any) -> dict[str, Any]:
        if (
            not isinstance(result, dict)
            or result.get("contract_version") != "agent_learning_runtime_v1"
            or not isinstance(result.get("preparation_id"), str)
            or not result["preparation_id"]
            or not isinstance(result.get("phase"), str)
            or not result["phase"]
            or type(result.get("cleanup_verified")) is not bool
            or any(result.get(key) is not False for key in (
                "artifact_is_authorization", "execute_binding_enabled", "action_executed",
            ))
        ):
            fail("learning_source_unavailable", "learning runtime provider returned an invalid response")
        return copy.deepcopy(result)

    def _reviewed_action_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._learning_runtime_guard:
            provider = self._learning_runtime_provider
        if provider is None:
            fail("operation_forbidden", "reviewed learning actions are not enabled")
        keys = {"request_learning_action": {"segment_id", "preparation_id", "intent_id", "action_id", "text_values"},
                "get_learning_action_result": {"segment_id", "preparation_id"}}[operation]
        required = keys - ({"text_values"} if operation == "request_learning_action" else set())
        args = _args(arguments, keys, required)
        identity = self._store.read(lambda state: {key: value for key, value in self._connection(state, token).items()
                                                 if key in {"connection_id", "task_id"}})
        method = {"request_learning_action": provider.request_reviewed_action,
                  "get_learning_action_result": provider.get_reviewed_action_result}[operation]
        try:
            result = method(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("learning_source_unavailable", "reviewed learning action state is unavailable") from error
        self._store.read(lambda state: self._connection(state, token))
        if (not isinstance(result, dict) or result.get("contract_version") != "agent_reviewed_learning_action_v1"
                or not isinstance(result.get("preparation_id"), str) or not result["preparation_id"]
                or any(result.get(key) is not False for key in (
                    "artifact_is_authorization", "operation_dispatches_input", "execution_ready"))):
            fail("learning_source_unavailable", "reviewed learning action provider returned an invalid response")
        return copy.deepcopy(result)

    def _learning_runtime_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._learning_runtime_guard:
            provider = self._learning_runtime_provider
        if provider is None:
            fail("operation_forbidden", "learning runtime controls are not enabled")
        keys = {
            "prepare_learning_runtime": {
                "segment_id", "idempotency_key", "asset_id", "asset_content_sha256",
                "target_window_handle", "target_process_id",
            },
            "get_learning_runtime": {"segment_id", "preparation_id"},
            "cancel_learning_runtime": {"segment_id", "preparation_id"},
        }[operation]
        args = _args(arguments, keys, keys)
        identity = self._store.read(lambda state: {
            key: value for key, value in self._connection(state, token).items()
            if key in {"connection_id", "task_id"}
        })
        method = {
            "prepare_learning_runtime": provider.prepare,
            "get_learning_runtime": provider.get,
            "cancel_learning_runtime": provider.cancel_reviewed,
        }[operation]
        try:
            # 提供者可能读取资产或等待本地协调器，调用期间不得持有收件箱锁。
            result = method(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            code = "runtime_prepare_failed" if operation == "prepare_learning_runtime" else (
                "runtime_cleanup_pending" if operation == "cancel_learning_runtime" else "learning_source_unavailable"
            )
            raise AgentLinkError(code, "learning runtime provider is unavailable") from error
        self._store.read(lambda state: self._connection(state, token))
        return self._runtime_result(result)

    def bind_workflow_memory_reader(self, reviewer_token: str, reader: Any) -> None:
        self._reviewer(reviewer_token)
        if not callable(getattr(reader, "search_workflow_memory", None)) or not callable(getattr(reader, "get_workflow_memory", None)):
            fail("invalid_arguments", "workflow memory reader is invalid")
        with self._memory_reader_guard:
            self._memory_reader = reader

    def bind_interface_content_gateway(self, reviewer_token: str, gateway: Any) -> None:
        """仅由可信 reviewer 安装同一连接宿主的界面内容只读网关。"""
        self._reviewer(reviewer_token)
        required = ("search_interface_memory", "get_interface_memory", "request_interface_membership")
        if any(not callable(getattr(gateway, name, None)) for name in required):
            fail("invalid_arguments", "interface content gateway is invalid")
        with self._interface_gateway_guard:
            if self._interface_gateway is not None:
                fail("learning_busy", "interface content gateway is already installed")
            self._interface_gateway = gateway

    @staticmethod
    def _safe_interface_result(result: Any, *, list_result: bool = False) -> Any:
        if list_result:
            if not isinstance(result, list):
                fail("interface_source_unavailable", "interface memory source is unavailable")
            value = copy.deepcopy(result)
        else:
            if not isinstance(result, dict):
                fail("interface_source_unavailable", "interface memory source is unavailable")
            value = copy.deepcopy(result)
        def inspect(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key == "executable_path_provided" and type(child) is bool:
                        continue
                    if not isinstance(key, str) or any(token in key.casefold() for token in ("path", "token", "password", "secret", "credential")):
                        fail("interface_source_unavailable", "interface memory source is unavailable")
                    inspect(child)
            elif isinstance(item, list):
                for child in item: inspect(child)
            elif isinstance(item, (str, int, float, bool)) or item is None:
                return
            else:
                fail("interface_source_unavailable", "interface memory source is unavailable")
        inspect(value)
        try:
            canonical_hash(value)
        except Exception as error:
            raise AgentLinkError("interface_source_unavailable", "interface memory source is unavailable") from error
        return value

    def _interface_call(self, token: str, operation: str, arguments: Any) -> Any:
        with self._interface_gateway_guard:
            gateway = self._interface_gateway
        if gateway is None:
            fail("operation_forbidden", "interface content access is not enabled")
        keys = {
            "search_interface_memory": ({"query"}, set()),
            "get_interface_memory": ({"interface_id", "version_id"}, {"interface_id"}),
            "request_interface_membership": ({"workflow_id", "interface_id", "version_id", "expected_revision", "expected_sha256", "idempotency_key"}, {"workflow_id", "interface_id", "version_id", "expected_revision", "expected_sha256", "idempotency_key"}),
        }[operation]
        args = _args(arguments, *keys)
        for field in ("interface_id", "version_id"):
            if field in args and args[field] is not None:
                _text(args[field], field)
        if operation == "search_interface_memory" and (not isinstance(args.get("query", ""), str) or len(args.get("query", "")) > 4000):
            fail("invalid_arguments", "query is invalid")
        for name in keys[1] - {"expected_revision"}:
            _text(args[name], name)
        if operation == "request_interface_membership":
            if type(args["expected_revision"]) is not int or args["expected_revision"] < 1:
                fail("invalid_arguments", "expected_revision must be positive")
            digest = args["expected_sha256"]
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                fail("invalid_arguments", "expected_sha256 is invalid")
        identity = self._store.read(lambda state: {
            key: value for key, value in self._connection(state, token).items() if key in {"connection_id", "task_id"}
        })
        try:
            if operation == "search_interface_memory":
                result = gateway.search_interface_memory(identity["task_id"], args.get("query", ""))
                safe = self._safe_interface_result(result, list_result=True)
            elif operation == "get_interface_memory":
                result = gateway.get_interface_memory(identity["task_id"], args["interface_id"], args.get("version_id"))
                safe = self._safe_interface_result(result)
            else:
                result = gateway.request_interface_membership(identity["task_id"], **copy.deepcopy(args))
                safe = self._safe_interface_result(result)
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("interface_source_unavailable", "interface memory source is unavailable") from error
        def recheck(state):
            connection = self._connection(state, token)
            if any(connection[key] != identity[key] for key in identity):
                fail("stale_revision", "interface connection identity changed")
        self._store.read(recheck)
        return safe

    def _project_call(self, token: str, operation: str, arguments: Any) -> Any:
        with self._interface_gateway_guard:
            gateway = self._interface_gateway
        if gateway is None or any(not callable(getattr(gateway, name, None)) for name in _PROJECT_OPERATIONS):
            fail("operation_forbidden", "workflow project memory access is not enabled")
        if operation == "search_workflow_projects":
            args = _args(arguments, {"query"}, set())
            if not isinstance(args.get("query", ""), str) or len(args.get("query", "")) > 4000:
                fail("invalid_arguments", "query is invalid")
        else:
            args = _args(arguments, {"workflow_id", "snapshot_id"}, {"workflow_id"})
            _text(args["workflow_id"], "workflow_id")
            if "snapshot_id" in args and args["snapshot_id"] is not None:
                _text(args["snapshot_id"], "snapshot_id")
        identity = self._store.read(lambda state: {key: value for key, value in self._connection(state, token).items() if key in {"connection_id", "task_id"}})
        try:
            result = (gateway.search_workflow_projects(identity["task_id"], args.get("query", ""))
                      if operation == "search_workflow_projects" else
                      gateway.get_workflow_project_memory(identity["task_id"], args["workflow_id"], args.get("snapshot_id")))
            return_value = self._safe_interface_result(result, list_result=operation == "search_workflow_projects")
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("interface_source_unavailable", "workflow project memory source is unavailable") from error
        self._store.read(lambda state: self._recheck_identity(state, token, identity))
        return return_value

    def _recheck_identity(self, state, token, identity):
        connection = self._connection(state, token)
        if any(connection[key] != identity[key] for key in identity):
            fail("stale_revision", "memory connection identity changed")

    def _fresh_runtime_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._learning_runtime_guard:
            provider = self._learning_runtime_provider
        if provider is None:
            fail("operation_forbidden", "fresh learning runtime is not enabled")
        keys = {
            "prepare_fresh_learning_runtime": {"segment_id", "batch_id", "idempotency_key"},
            "request_fresh_learning_action": {"segment_id", "preparation_id", "intent_id", "action_id", "semantic_action", "goal"},
            "get_fresh_learning_runtime": {"segment_id", "preparation_id"},
            "cancel_fresh_learning_runtime": {"segment_id", "preparation_id"},
        }[operation]
        optional = {"text_parameters", "text_values", "learned_control", "scroll_parameters"} if operation == "request_fresh_learning_action" else set()
        args = _args(arguments, keys | optional, keys)
        identity = self._store.read(lambda state: {key: value for key, value in self._connection(state, token).items()
                                                 if key in {"connection_id", "task_id"}})
        method = {"prepare_fresh_learning_runtime": provider.prepare_fresh,
                  "request_fresh_learning_action": provider.request_fresh,
                  "get_fresh_learning_runtime": provider.get_fresh,
                  "cancel_fresh_learning_runtime": provider.cancel_fresh}[operation]
        try:
            result = method(**identity, **copy.deepcopy(args))
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("learning_source_unavailable", "fresh runtime state is unavailable") from error
        self._store.read(lambda state: self._connection(state, token))
        if (not isinstance(result, dict) or result.get("contract_version") != "agent_fresh_learning_runtime_v1"
                or not isinstance(result.get("preparation_id"), str) or not result["preparation_id"]
                or not isinstance(result.get("phase"), str) or not result["phase"]
                or type(result.get("cleanup_verified")) is not bool
                or any(result.get(key) is not False for key in (
                    "artifact_is_authorization", "operation_dispatches_input", "execution_ready"))):
            fail("learning_source_unavailable", "fresh runtime provider returned an invalid response")
        return copy.deepcopy(result)

    def _connection(self, state: dict[str, Any], token: str) -> dict[str, Any]:
        candidate = _digest(_secret(token, "agent token"))
        for connection in state["connections"].values():
            if hmac.compare_digest(connection["token_digest"], candidate):
                if connection["revoked"]: fail("connection_revoked", "agent connection is revoked")
                return connection
        fail("authentication_failed", "agent authentication failed")

    def _reviewer(self, token: str) -> None:
        if not isinstance(token, str) or not hmac.compare_digest(_digest(token), self._reviewer_digest): fail("authentication_failed", "reviewer authentication failed")

    def reviewer_transaction(self, token: str, callback):
        """只为同进程 reviewer 提供既有 store guard 下的原子回调。"""
        self._reviewer(token)
        if not callable(callback):
            fail("invalid_arguments", "reviewer transaction callback is invalid")
        return self._store.read(lambda _state: callback())

    def agent_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        if operation in _APPLICATION_STARTUP_OPERATIONS:
            return self._application_startup_call(token, operation, arguments)
        if operation in INTERFACE_RELEARNING_CAPABILITY["operations"]:
            from .interface_relearning_call import interface_relearning_call
            return interface_relearning_call(self, token, operation, arguments)
        if operation in _PROJECT_OPERATIONS:
            return self._project_call(token, operation, arguments)
        if operation in _INTERFACE_OPERATIONS:
            return self._interface_call(token, operation, arguments)
        if operation in _FRESH_RUNTIME_CAPABILITY["operations"]:
            return self._fresh_runtime_call(token, operation, arguments)
        if operation in _REVIEWED_ACTION_CAPABILITY["operations"]:
            return self._reviewed_action_call(token, operation, arguments)
        if operation == "observe_learning_screen":
            return self._learning_observation_call(token, arguments)
        if operation in _LEARNING_CONTENT_OPERATIONS:
            return self._learning_content_call(token, operation, arguments)
        if operation == _OBSERVED_INTERFACE_OPERATION:
            return self._submit_observed_interface_learning(token, arguments)
        if operation in _LEARNING_RUNTIME_OPERATIONS:
            return self._learning_runtime_call(token, operation, arguments)
        if operation in _LEARNING_OPERATIONS:
            return self._learning_call(token, operation, arguments)
        if operation in _MEMORY_OPERATIONS:
            return self._memory_call(token, operation, arguments)
        if operation not in _AGENT: raise AgentLinkError("operation_forbidden", "reviewer operation is not available to an Agent connection")
        if operation == "status":
            if arguments != {}: fail("invalid_arguments", "status takes no arguments")
            return self._store.read(lambda state: self._status(state, token))
        if operation == "read_feedback":
            args = _args(arguments, {"batch_id"}, {"batch_id"}); return self._store.read(lambda state: self._feedback(state, self._connection(state, token), _text(args["batch_id"], "batch_id")))
        if operation == "submit_batch": return self._batch(token, validate_batch(arguments))
        return self._candidate(token, validate_candidate(arguments))

    def reviewer_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        self._reviewer(token)
        if operation not in _REVIEWER: raise AgentLinkError("operation_forbidden", "operation is not available to reviewer")
        if operation == "create_connection": return self._create(arguments)
        if operation == "list_batches": return self._list(arguments)
        if operation == "list_connections": return self._connections(arguments)
        if operation == "get_batch": return self._get(arguments)
        if operation == "revoke_connection": return self._revoke(arguments)
        if operation == "set_workflow_memory_scope": return self._set_memory_scope(arguments)
        if operation == "record_feedback": return self._record(arguments)
        return self._withdraw(arguments)

    def _status(self, state, token):
        connection = self._connection(state, token)
        result = {"contract_version": CONTRACT_VERSION, "connection_id": connection["connection_id"], "task_id": connection["task_id"], "capabilities": sorted(_AGENT), "candidate_change_types": list(CHANGE_TYPES), "graph_contracts": {"baseline": "desktop_graph_review_baseline_v1", "baseline_view": "desktop_graph_review_baseline_view_v1", "candidate": "agent_link_graph_candidate_v1", "operations": ["update_edge_target", "update_region_bbox", "update_node_meaning", "update_node_recognition_text", "update_edge_semantics"]}, "staging_only": True}
        scope = connection.get("memory_scope")
        with self._memory_reader_guard:
            reader_installed = self._memory_reader is not None
        if reader_installed and isinstance(scope, dict) and scope.get("workflow_ids"):
            result["workflow_memory"] = copy.deepcopy(MEMORY_CAPABILITY)
        with self._interface_gateway_guard:
            if self._interface_gateway is not None:
                result["interface_content"] = copy.deepcopy(_INTERFACE_CAPABILITY)
                if all(callable(getattr(self._interface_gateway, name, None)) for name in INTERFACE_RELEARNING_CAPABILITY["operations"]):
                    result["interface_relearning"] = copy.deepcopy(INTERFACE_RELEARNING_CAPABILITY)
                if all(callable(getattr(self._interface_gateway, name, None)) for name in _PROJECT_OPERATIONS):
                    result["workflow_project_memory"] = copy.deepcopy(_PROJECT_CAPABILITY)
        with self._learning_owner_guard:
            if self._learning_owner is not None:
                from .learning_segments import LEARNING_SEGMENT_CAPABILITY

                result["learning_segments"] = copy.deepcopy(LEARNING_SEGMENT_CAPABILITY)
        with self._learning_runtime_guard:
            if self._learning_runtime_provider is not None:
                result["learning_runtime"] = copy.deepcopy(_LEARNING_RUNTIME_CAPABILITY)
                result["fresh_learning_runtime"] = copy.deepcopy(_FRESH_RUNTIME_CAPABILITY)
                result["reviewed_learning_actions"] = copy.deepcopy(_REVIEWED_ACTION_CAPABILITY)
        with self._application_startup_guard:
            if self._application_startup_provider is not None:
                result["application_startup"] = copy.deepcopy(_APPLICATION_STARTUP_CAPABILITY)
        with self._learning_observation_guard:
            if self._learning_observation_provider is not None:
                from app.desktop_review.learning_observation import OBSERVATION_CAPABILITY

                result["learning_observation"] = copy.deepcopy(OBSERVATION_CAPABILITY)
                if getattr(self._learning_observation_provider, "content", None) is not None:
                    result["learning_content"] = copy.deepcopy(_LEARNING_CONTENT_CAPABILITY)
        return result

    def _create(self, arguments):
        args = _args(arguments, {"task_id", "agent_name"}, {"task_id", "agent_name"}); task, name = _text(args["task_id"], "task_id"), _text(args["agent_name"], "agent_name")
        token, connection_id = secrets.token_urlsafe(32), "connection-" + uuid.uuid4().hex
        def change(state):
            state["connections"][connection_id] = {"connection_id": connection_id, "task_id": task, "agent_name": name, "token_digest": _digest(token), "revoked": False, "created_at": time.time_ns()}
            return {"contract_version": CONTRACT_VERSION, "connection_id": connection_id, "task_id": task, "agent_name": name, "token": token, "staging_only": True}
        return self._store.mutate(change)

    def _set_memory_scope(self, arguments):
        args = _args(
            arguments,
            {"connection_id", "expected_revision", "workflow_ids", "idempotency_key"},
            {"connection_id", "expected_revision", "workflow_ids", "idempotency_key"},
        )
        connection_id = _text(args["connection_id"], "connection_id")
        key = _text(args["idempotency_key"], "idempotency_key")
        if type(args["expected_revision"]) is not int or args["expected_revision"] < 0:
            fail("invalid_arguments", "expected_revision must be non-negative")
        workflow_ids = validate_workflow_ids(args["workflow_ids"])
        request = {
            "connection_id": connection_id,
            "expected_revision": args["expected_revision"],
            "workflow_ids": workflow_ids,
            "idempotency_key": key,
        }

        def change(state):
            def action():
                connection = state["connections"].get(connection_id)
                if connection is None:
                    fail("not_found", "connection was not found")
                if connection["revoked"]:
                    fail("connection_revoked", "agent connection is revoked")
                current = connection.get("memory_scope")
                revision = current["revision"] if current is not None else 0
                if revision != args["expected_revision"]:
                    fail("stale_revision", "workflow memory scope revision is stale")
                next_revision = revision + 1
                connection["memory_scope"] = {
                    "contract_version": MEMORY_SCOPE_CONTRACT,
                    "revision": next_revision,
                    "workflow_ids": list(workflow_ids),
                }
                return {
                    "contract_version": CONTRACT_VERSION,
                    "connection_id": connection_id,
                    "revision": next_revision,
                    "status": "memory_scope_updated",
                    "staging_only": True,
                }

            return self._idem(
                state, "reviewer", "set_workflow_memory_scope", key, request, action,
            )

        return self._store.mutate(change)

    def _memory_call(self, token: str, operation: str, arguments: Any) -> dict[str, Any]:
        with self._memory_reader_guard:
            reader = self._memory_reader
        if reader is None:
            fail("operation_forbidden", "workflow memory access is not enabled")
        if operation == "search_workflow_memory":
            args = _args(arguments, {"application_scope", "query", "cursor"}, {"application_scope"})
            if not isinstance(args["application_scope"], dict):
                fail("invalid_arguments", "application_scope must be an object")
            query = args.get("query", "")
            cursor = args.get("cursor")
            if not isinstance(query, str) or len(query) > 4000:
                fail("invalid_arguments", "query is invalid")
            if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4000):
                fail("invalid_arguments", "cursor is invalid")
            reader_arguments = (copy.deepcopy(args["application_scope"]), query, cursor)
        else:
            args = _args(arguments, {"workflow_id", "version"}, {"workflow_id"})
            workflow_id = validate_workflow_id(args["workflow_id"])
            version = args.get("version")
            if version is not None and (not isinstance(version, str) or not version or len(version) > 4000):
                fail("invalid_arguments", "version is invalid")
            reader_arguments = (workflow_id, version)

        def capture(state):
            connection = self._connection(state, token)
            scope = connection.get("memory_scope")
            if not isinstance(scope, dict) or not scope["workflow_ids"]:
                fail("operation_forbidden", "workflow memory access is not enabled")
            if operation == "get_workflow_memory" and reader_arguments[0] not in scope["workflow_ids"]:
                fail("not_found", "workflow memory was not found")
            return {
                "connection_id": connection["connection_id"],
                "revision": scope["revision"],
                "workflow_ids": list(scope["workflow_ids"]),
            }

        authorization = self._store.read(capture)
        try:
            if operation == "search_workflow_memory":
                result = reader.search_workflow_memory(
                    authorization["workflow_ids"], *reader_arguments,
                )
            else:
                result = reader.get_workflow_memory(
                    authorization["workflow_ids"], *reader_arguments,
                )
        except Exception as error:
            self._raise_memory_reader_error(error)

        def recheck(state):
            connection = self._connection(state, token)
            scope = connection.get("memory_scope")
            if (
                connection["connection_id"] != authorization["connection_id"]
                or not isinstance(scope, dict)
                or scope["revision"] != authorization["revision"]
                or scope["workflow_ids"] != authorization["workflow_ids"]
            ):
                fail("stale_revision", "workflow memory scope changed during the read")

        self._store.read(recheck)
        try:
            if (
                not isinstance(result, dict)
                or result.get("contract_version") != "agent_workflow_memory_v1"
                or result.get("artifact_is_authorization") is not False
                or result.get("execute_binding_enabled") is not False
                or result.get("requires_current_grounding") is not True
            ):
                raise ValueError("invalid workflow memory response")
            canonical_hash(result)
            safe_result = copy.deepcopy(result)
        except Exception as error:
            raise AgentLinkError(
                "memory_source_unavailable", "workflow memory source returned an invalid response",
            ) from error
        return safe_result

    @staticmethod
    def _raise_memory_reader_error(error: Exception) -> None:
        try:
            from app.desktop_review.workflow_memory import WorkflowMemoryError
        except ImportError:
            WorkflowMemoryError = None
        code = getattr(error, "code", None) if WorkflowMemoryError is not None and isinstance(error, WorkflowMemoryError) else None
        if code not in _MEMORY_ERROR_MESSAGES:
            code = "memory_source_unavailable"
        raise AgentLinkError(code, _MEMORY_ERROR_MESSAGES[code]) from error

    def _idem(self, state, actor, operation, key, request, action):
        request_hash, ledger = canonical_hash(request), f"{actor}:{operation}:{key}"
        previous = state["idempotency"].get(ledger)
        if previous:
            if not hmac.compare_digest(previous["request_hash"], request_hash): fail("idempotency_conflict", "idempotency key was already used with different content")
            return previous["receipt"]
        receipt = action(); state["idempotency"][ledger] = {"request_hash": request_hash, "receipt": copy.deepcopy(receipt)}; return receipt

    def _batch(self, token, batch):
        def change(state):
            connection = self._connection(state, token)
            def action():
                if batch["batch_id"] in state["batches"]: fail("batch_conflict", "batch_id already exists")
                stored = copy.deepcopy(batch); stored.update(connection_id=connection["connection_id"], task_id=connection["task_id"], status="pending_review_proposal", source="untrusted_external")
                state["batches"][batch["batch_id"]] = stored; state["feedback"][batch["batch_id"]] = {"revision": 0, "history": [], "issues": {}}
                return {"contract_version": CONTRACT_VERSION, "batch_id": batch["batch_id"], "status": "pending_review_proposal", "learning_outcome": batch["learning_outcome"], "incomplete": batch["learning_outcome"] != "completed", "staging_only": True}
            return self._idem(state, connection["connection_id"], "submit_batch", batch["idempotency_key"], batch, action)
        receipt = self._store.mutate(change)
        with self._interface_gateway_guard:
            importer = getattr(self._interface_gateway, "get_submitted_interface_refs", None)
        if not callable(importer):
            return receipt
        identity = self._store.read(lambda state: {
            key: self._connection(state, token)[key] for key in ("connection_id", "task_id")
        })
        try:
            # 收件箱提交后释放锁，再物化内容；失败时同批次幂等重试可继续导入。
            references = importer(identity["task_id"], batch["batch_id"])
            references = self._safe_interface_result(references, list_result=True)
        except AgentLinkError:
            raise
        except Exception as error:
            raise AgentLinkError("interface_source_unavailable", "batch is stored but interface import is pending; retry the same submission") from error
        current = self._store.read(lambda state: self._connection(state, token))
        if any(current[key] != identity[key] for key in identity):
            fail("stale_revision", "interface connection identity changed")
        return {**receipt, "interface_contents": references}

    def _owned(self, state, connection, batch_id):
        batch = state["batches"].get(batch_id)
        if batch is None or batch["connection_id"] != connection["connection_id"]: fail("not_found", "batch was not found for this connection")
        return batch

    def _feedback(self, state, connection, batch_id):
        self._owned(state, connection, batch_id); feedback = state["feedback"][batch_id]
        return {"contract_version": CONTRACT_VERSION, "batch_id": batch_id, "revision": feedback["revision"], "notes": [note for entry in feedback["history"] for note in entry["notes"]], "issues": list(feedback["issues"].values()), "staging_only": True}

    def _list(self, arguments):
        args = _args(arguments, {"task_id"}, set()); task = args.get("task_id");
        if task is not None: task = _text(task, "task_id")
        return self._store.read(lambda state: {"contract_version": CONTRACT_VERSION, "batches": [{"batch_id": batch["batch_id"], "task_id": batch["task_id"], "title": batch["title"], "status": batch["status"], "feedback_revision": state["feedback"][batch["batch_id"]]["revision"]} for batch in state["batches"].values() if task is None or batch["task_id"] == task], "staging_only": True})

    def _connections(self, arguments):
        args = _args(arguments, {"task_id"}, set()); task = args.get("task_id")
        if task is not None: task = _text(task, "task_id")
        return self._store.read(lambda state: {"contract_version": CONTRACT_VERSION, "connections": [{key: connection[key] for key in ("connection_id", "task_id", "agent_name", "revoked", "created_at")} for connection in state["connections"].values() if task is None or connection["task_id"] == task], "staging_only": True})

    def _get(self, arguments):
        args = _args(arguments, {"task_id", "batch_id"}, {"task_id", "batch_id"}); task, batch_id = _text(args["task_id"], "task_id"), _text(args["batch_id"], "batch_id")
        def read(state):
            batch = state["batches"].get(batch_id)
            if batch is None or batch["task_id"] != task: fail("not_found", "batch was not found for this task")
            public = {key: value for key, value in batch.items() if key not in {"connection_id", "task_id", "status", "source", "fresh_learning_source"}}
            return {"contract_version": CONTRACT_VERSION, "batch": public, "source": "untrusted_external", "feedback_history": state["feedback"][batch_id]["history"], "issues": list(state["feedback"][batch_id]["issues"].values()), "candidates": [item for item in state["candidates"].values() if item["batch_id"] == batch_id], "staging_only": True,
                    **({"fresh_learning_source": copy.deepcopy(batch["fresh_learning_source"])} if "fresh_learning_source" in batch else {})}
        return self._store.read(read)

    def _record(self, arguments):
        args = _args(arguments, {"task_id", "batch_id", "idempotency_key", "expected_revision", "notes", "issues"}, {"task_id", "batch_id", "idempotency_key", "expected_revision", "notes", "issues"})
        task, batch_id, key = _text(args["task_id"], "task_id"), _text(args["batch_id"], "batch_id"), _text(args["idempotency_key"], "idempotency_key")
        if type(args["expected_revision"]) is not int or args["expected_revision"] < 0: fail("invalid_arguments", "expected_revision must be non-negative")
        notes = [parse(NoteInput, note, "note") for note in args["notes"]] if isinstance(args["notes"], list) else fail("invalid_arguments", "notes must be a list")
        issues = [parse(IssueInput, issue, "issue") for issue in args["issues"]] if isinstance(args["issues"], list) else fail("invalid_arguments", "issues must be a list")
        request = {"task_id": task, "batch_id": batch_id, "idempotency_key": key, "expected_revision": args["expected_revision"], "notes": notes, "issues": issues}
        def change(state):
            def action():
                batch = state["batches"].get(batch_id)
                if batch is None or batch["task_id"] != task: fail("not_found", "batch was not found for this task")
                feedback = state["feedback"][batch_id]
                if feedback["revision"] != args["expected_revision"]: fail("stale_revision", "feedback revision is stale")
                if len({note["note_id"] for note in notes}) != len(notes): fail("invalid_arguments", "note ids must be unique")
                validated_issues = []
                for issue in issues:
                    stored_issue = copy.deepcopy(issue)
                    effective_batch = batch
                    if "review_baseline" in issue:
                        if issue["review_baseline"].get("contract_version") == "desktop_graph_review_baseline_v1":
                            baseline, snapshot = validate_graph_review_baseline(
                                issue["review_baseline"], task_id=task, batch_id=batch_id,
                                original_batch=batch,
                            )
                            try: stored_issue["scope"] = validate_graph_scope(issue["scope"], snapshot["graph"])
                            except GraphContractError as error: fail("invalid_scope", str(error))
                            effective_batch = None
                        else:
                            baseline, effective_batch = validate_review_baseline(
                                issue["review_baseline"], task_id=task, original_batch=batch
                            )
                        stored_issue["review_baseline"] = baseline
                        stored_issue["review_baseline_sha256"] = canonical_hash(baseline)
                    if effective_batch is not None:
                        stored_issue["scope"] = validate_scope(issue["scope"], effective_batch)
                    validated_issues.append(stored_issue)
                revision = feedback["revision"] + 1; issue_ids=[]
                for candidate in state["candidates"].values():
                    if candidate["batch_id"] == batch_id and candidate["status"] == "pending_review_proposal": candidate["status"] = "stale"
                for issue in validated_issues:
                    if issue["issue_id"] in feedback["issues"]: fail("issue_conflict", "issue_id already exists")
                    feedback["issues"][issue["issue_id"]]={**issue, "status":"open", "baseline_revision":revision}; issue_ids.append(issue["issue_id"])
                feedback["revision"] = revision; feedback["history"].append({"revision": revision, "notes": notes, "issue_ids": issue_ids})
                return {"contract_version": CONTRACT_VERSION,"batch_id":batch_id,"revision":revision,"status":"feedback_recorded","staging_only":True}
            return self._idem(state, "reviewer", "record_feedback", key, request, action)
        return self._store.mutate(change)

    def _candidate(self, token, candidate):
        def change(state):
            connection=self._connection(state, token)
            def action():
                batch=self._owned(state, connection, candidate["batch_id"]); feedback=state["feedback"][candidate["batch_id"]]; issue=feedback["issues"].get(candidate["issue_id"])
                if issue is None: fail("not_found", "issue was not found")
                if issue["status"] == "withdrawn": fail("issue_withdrawn", "issue is withdrawn")
                if candidate["baseline_revision"] != feedback["revision"] or candidate["baseline_revision"] != issue["baseline_revision"]: fail("stale_revision", "candidate baseline is stale")
                if "review_baseline" in issue:
                    expected_hash = issue["review_baseline_sha256"]
                    supplied_hash = candidate.get("review_baseline_sha256")
                    if not hashes_equal(supplied_hash, expected_hash):
                        fail("invalid_baseline", "candidate must echo the exact review baseline digest")
                    if issue["review_baseline"].get("contract_version") == "desktop_graph_review_baseline_v1":
                        if candidate.get("contract_version") != "agent_link_graph_candidate_v1":
                            fail("invalid_baseline", "legacy candidate cannot attach to graph issue")
                        _, snapshot = validate_graph_review_baseline(
                            issue["review_baseline"], task_id=batch["task_id"],
                            batch_id=candidate["batch_id"], original_batch=batch,
                        )
                        if candidate["logical_workflow_id"] != snapshot["logical_workflow_id"] or not hashes_equal(candidate["baseline_graph_sha256"], snapshot["content_sha256"]):
                            fail("invalid_baseline", "candidate graph baseline binding is invalid")
                        validate_graph_candidate(candidate, snapshot, issue)
                        effective_batch = None
                    else:
                        if candidate.get("contract_version") != "agent_link_v1":
                            fail("invalid_baseline", "graph candidate cannot attach to legacy issue")
                        _, effective_batch = validate_review_baseline(
                            issue["review_baseline"], task_id=batch["task_id"], original_batch=batch
                        )
                else:
                    if candidate.get("contract_version") != "agent_link_v1": fail("invalid_baseline", "graph candidate requires graph issue")
                    if "review_baseline_sha256" in candidate:
                        fail("invalid_baseline", "legacy issue has no human review baseline")
                    effective_batch = batch
                if effective_batch is not None:
                    scope=validate_scope(candidate["scope"], effective_batch)
                    if scope != issue["scope"]: fail("invalid_scope", "candidate scope must match issue scope")
                    validate_candidate_changes(candidate, effective_batch, scope)
                candidate_id="candidate-"+uuid.uuid4().hex
                stored_candidate={**copy.deepcopy(candidate), "candidate_id":candidate_id,"connection_id":connection["connection_id"],"status":"pending_review_proposal"}
                if "review_baseline_sha256" in candidate:
                    stored_candidate["candidate_sha256"] = candidate_content_sha256(stored_candidate)
                state["candidates"][candidate_id]=stored_candidate
                return {"contract_version":CONTRACT_VERSION,"candidate_id":candidate_id,"batch_id":candidate["batch_id"],"issue_id":candidate["issue_id"],"status":"pending_review_proposal","staging_only":True}
            return self._idem(state, connection["connection_id"], "submit_candidate", candidate["idempotency_key"], candidate, action)
        return self._store.mutate(change)

    def _revoke(self, arguments):
        args=_args(arguments,{"connection_id","idempotency_key"},{"connection_id","idempotency_key"}); connection_id,key=_text(args["connection_id"],"connection_id"),_text(args["idempotency_key"],"idempotency_key")
        def change(state):
            def action():
                connection=state["connections"].get(connection_id)
                if connection is None: fail("not_found","connection was not found")
                connection["revoked"]=True
                return {"contract_version":CONTRACT_VERSION,"connection_id":connection_id,"status":"revoked","staging_only":True}
            return self._idem(state,"reviewer","revoke_connection",key,args,action)
        return self._store.mutate(change)

    def _withdraw(self, arguments):
        args=_args(arguments,{"task_id","batch_id","issue_id","expected_revision","idempotency_key"},{"task_id","batch_id","issue_id","expected_revision","idempotency_key"}); task,batch_id,issue_id,key=(_text(args[x],x) for x in ("task_id","batch_id","issue_id","idempotency_key"))
        if type(args["expected_revision"]) is not int or args["expected_revision"]<1: fail("invalid_arguments","expected_revision must be positive")
        def change(state):
            def action():
                batch=state["batches"].get(batch_id); feedback=state["feedback"].get(batch_id)
                if batch is None or batch["task_id"] != task: fail("not_found","batch was not found for this task")
                issue=feedback["issues"].get(issue_id)
                if issue is None: fail("not_found","issue was not found")
                if feedback["revision"] != args["expected_revision"]: fail("stale_revision","feedback revision is stale")
                if issue["status"]=="withdrawn": fail("issue_withdrawn","issue is already withdrawn")
                issue["status"]="withdrawn"; feedback["revision"]+=1; feedback["history"].append({"revision":feedback["revision"],"notes":[],"issue_ids":[]})
                for candidate in state["candidates"].values():
                    if candidate["batch_id"] != batch_id: continue
                    if candidate["issue_id"] == issue_id: candidate["status"] = "withdrawn"
                    elif candidate["status"] == "pending_review_proposal": candidate["status"] = "stale"
                return {"contract_version":CONTRACT_VERSION,"batch_id":batch_id,"issue_id":issue_id,"revision":feedback["revision"],"status":"issue_withdrawn","staging_only":True}
            return self._idem(state,"reviewer","withdraw_issue",key,args,action)
        return self._store.mutate(change)
