"""原生桌面连接凭据的本地控制面。"""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from app.agent_link.contracts import AgentLinkError, CONTRACT_VERSION
from app.agent_link.artifact_packaging import prepare_bundle


class NativeConnectionError(RuntimeError):
    def __init__(self, code: str, message: str, *, result_unknown: bool = False) -> None:
        self.code = code
        self.message = message
        self.result_unknown = result_unknown
        super().__init__(message)


class NativeConnectionController:
    def __init__(
        self,
        service: Any,
        reviewer_token: str,
        host_status: Callable[[], dict[str, Any]],
        *,
        lifecycle_guard: Any | None = None,
    ) -> None:
        if not hasattr(service, "reviewer_call"):
            raise TypeError("service must provide reviewer_call")
        if not isinstance(reviewer_token, str) or not reviewer_token:
            raise ValueError("reviewer_token is required")
        if not callable(host_status):
            raise TypeError("host_status must be callable")
        self._service = service
        self._reviewer_token = reviewer_token
        self._host_status = host_status
        self._lifecycle_guard = lifecycle_guard or RLock()

    def host_status(self) -> dict[str, Any]:
        return deepcopy(self._host_status())

    def list_connections(self) -> list[dict[str, Any]]:
        with self._lifecycle_guard:
            self._require_ready()
            result = self._reviewer_call("list_connections", {})
            if not _valid_envelope(result, {"contract_version", "connections", "staging_only"}):
                raise _invalid_response()
            records = result.get("connections")
            if not isinstance(records, list):
                raise _invalid_response()
            checked: list[dict[str, Any]] = []
            identities: set[str] = set()
            for value in records:
                if not isinstance(value, dict) or set(value) != {
                    "connection_id", "task_id", "agent_name", "revoked", "created_at"
                }:
                    raise _invalid_response()
                if not all(_valid_text(value.get(key)) for key in (
                    "connection_id", "task_id", "agent_name"
                )):
                    raise _invalid_response()
                if type(value.get("revoked")) is not bool:
                    raise _invalid_response()
                if type(value.get("created_at")) is not int or value["created_at"] < 0:
                    raise _invalid_response()
                if value["connection_id"] in identities:
                    raise _invalid_response()
                identities.add(value["connection_id"])
                checked.append(deepcopy(value))
            return checked

    def create_connection(self, task_id: str, agent_name: str) -> dict[str, Any]:
        task = _input_text(task_id, "task_id")
        name = _input_text(agent_name, "agent_name")
        with self._lifecycle_guard:
            self._require_ready()
            try:
                result = self._service.reviewer_call(
                    self._reviewer_token,
                    "create_connection",
                    {"task_id": task, "agent_name": name},
                )
            except AgentLinkError as error:
                raise NativeConnectionError(
                    error.code,
                    "connection creation failed; refresh before deciding whether to retry",
                    result_unknown=True,
                ) from None
            except Exception:
                raise NativeConnectionError(
                    "connection_create_failed",
                    "connection creation failed; refresh before deciding whether to retry",
                    result_unknown=True,
                ) from None
            if not _valid_envelope(result, {
                "contract_version", "connection_id", "task_id", "agent_name", "token",
                "staging_only",
            }):
                raise _invalid_response(result_unknown=True)
            token = result.get("token")
            if (
                result.get("task_id") != task
                or result.get("agent_name") != name
                or not _valid_text(result.get("connection_id"))
                or not isinstance(token, str)
                or not token.isascii()
                or not 16 <= len(token) <= 512
                or any(ord(character) < 33 or ord(character) > 126 for character in token)
            ):
                raise _invalid_response(result_unknown=True)
            return deepcopy(result)

    def revoke_connection(
        self, connection_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        identity = _input_text(connection_id, "connection_id")
        key = _input_text(idempotency_key, "idempotency_key")
        with self._lifecycle_guard:
            self._require_ready()
            result = self._reviewer_call(
                "revoke_connection",
                {"connection_id": identity, "idempotency_key": key},
            )
            if not _valid_envelope(result, {
                "contract_version", "connection_id", "status", "staging_only"
            }):
                raise _invalid_response()
            if result.get("connection_id") != identity or result.get("status") != "revoked":
                raise _invalid_response()
            return deepcopy(result)

    def prepare_artifact_bundle(self, binding: dict, images: Mapping[str, Path], output: Path) -> dict:
        if not isinstance(binding, dict) or set(binding) != {"connection_id", "task_id", "host_id", "base_url"}:
            raise NativeConnectionError("invalid_arguments", "artifact binding is invalid")
        if not all(_valid_text(value) for value in binding.values()) or not isinstance(images, Mapping):
            raise NativeConnectionError("invalid_arguments", "artifact selection is invalid")
        binding, images = deepcopy(binding), dict(images)
        with self._lifecycle_guard:
            self._require_artifact_connection(binding)
            try:
                result = prepare_bundle(images, connection_id=binding["connection_id"], task_id=binding["task_id"], output=output)
            except FileExistsError:
                raise NativeConnectionError("artifact_output_exists", "choose a new output file; the existing file was not overwritten") from None
            except (ValueError, TypeError):
                raise NativeConnectionError("artifact_invalid_input", "selected images or bundle exceed the validated format or limits") from None
            except (OSError, RuntimeError):
                raise NativeConnectionError("artifact_preparation_failed", "image packaging failed; check the selected output before retrying", result_unknown=True) from None
            try:
                self._require_artifact_connection(binding)
            except NativeConnectionError:
                raise NativeConnectionError("artifact_binding_changed", "connection changed; a file may exist but must not be attached", result_unknown=True) from None
            return deepcopy(result)

    def _require_artifact_connection(self, binding: dict) -> None:
        self._require_ready()
        status = self.host_status()
        if status.get("phase") != "ready" or any(status.get(key) != binding[key] for key in ("host_id", "base_url")):
            raise NativeConnectionError("artifact_binding_changed", "image registration host does not match the selected connection")
        records = self.list_connections()
        if not any(record["connection_id"] == binding["connection_id"] and record["task_id"] == binding["task_id"] and not record["revoked"] for record in records):
            raise NativeConnectionError("artifact_connection_unavailable", "selected image registration connection is missing, changed or revoked")

    def _require_ready(self) -> None:
        status = self._host_status()
        if not isinstance(status, dict) or status.get("phase") != "ready":
            raise NativeConnectionError("host_not_ready", "connection host is not ready")

    def _reviewer_call(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._service.reviewer_call(
                self._reviewer_token, operation, arguments
            )
        except AgentLinkError as error:
            raise NativeConnectionError(error.code, "connection operation failed") from None
        except Exception:
            raise NativeConnectionError(
                "connection_operation_failed", "connection operation failed"
            ) from None


def _input_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise NativeConnectionError("invalid_arguments", f"{field} is invalid")
    return value


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 256


def _valid_envelope(value: Any, keys: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == keys
        and value.get("contract_version") == CONTRACT_VERSION
        and value.get("staging_only") is True
    )


def _invalid_response(*, result_unknown: bool = False) -> NativeConnectionError:
    return NativeConnectionError(
        "invalid_response", "connection service returned an invalid response",
        result_unknown=result_unknown,
    )
