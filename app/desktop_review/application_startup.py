"""Agent 应用启动请求只在人工确认后交给既有窗口准备协调器。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import ntpath
import re
import time
from threading import RLock
from typing import Any
from uuid import uuid4

from app.agent_link.contracts import AgentLinkError
from app.agent_link.store import AgentLinkStore
from app.core.launch_text import has_launch_display_controls

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT = "agent_application_startup_v1"


def _stable(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise AgentLinkError("invalid_arguments", f"{name} is invalid")
    return value


def _task(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 4000:
        raise AgentLinkError("invalid_arguments", "task_id is invalid")
    return value


def _url(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4096 or has_launch_display_controls(value):
        raise AgentLinkError("invalid_arguments", "url is invalid")
    return value


def _canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise AgentLinkError("invalid_arguments", "application launch request is invalid") from None
    return hashlib.sha256(encoded).hexdigest()


class ApplicationStartupProvider:
    """同一 inbox 所有者的人工应用启动请求入口；Agent 永远不持有确认方法。"""

    def __init__(self, store: AgentLinkStore, coordinator: Any) -> None:
        if not isinstance(store, AgentLinkStore):
            raise TypeError("application startup requires AgentLinkStore")
        required = ("discover_applications", "preview_application_launch", "confirm_window_preparation")
        if any(not callable(getattr(coordinator, name, None)) for name in required):
            raise TypeError("application startup requires the native preparation coordinator")
        self.store = store
        self._coordinator = coordinator
        self._guard = RLock()

    def discover(self, *, connection_id: str, task_id: str) -> dict[str, Any]:
        self._require_connection(connection_id, task_id)
        try:
            result = self._coordinator.discover_applications()
        except Exception as error:
            raise AgentLinkError("application_catalog_unavailable", "application catalog is unavailable") from error
        return _discovery(result)

    def request(self, *, connection_id: str, task_id: str, app_id: Any, idempotency_key: Any, url: Any = None) -> dict[str, Any]:
        connection_id, task_id = _stable(connection_id, "connection_id"), _task(task_id)
        app_id, idempotency_key, url = _stable(app_id, "app_id"), _stable(idempotency_key, "idempotency_key"), _url(url)
        payload = {"connection_id": connection_id, "task_id": task_id, "app_id": app_id, "url": url}
        request_hash = _canonical_hash(payload)

        def change(state):
            self._checked_connection(state, connection_id, task_id)
            launches = state["application_launches"]
            ledger_key = connection_id + ":" + idempotency_key
            prior = launches["idempotency"].get(ledger_key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise AgentLinkError("idempotency_conflict", "launch key has another request")
                return self._request_receipt(launches["requests"][prior["request_id"]])
            request_id = "application-launch-" + uuid4().hex
            record = {"request_id": request_id, **payload, "created_at": time.time_ns(), "status": "pending_human_confirmation"}
            launches["requests"][request_id] = record
            launches["idempotency"][ledger_key] = {"request_hash": request_hash, "request_id": request_id}
            return self._request_receipt(record)

        return self.store.mutate(change)

    def get(self, *, connection_id: str, task_id: str, request_id: Any) -> dict[str, Any]:
        request_id = _stable(request_id, "request_id")
        return self.store.read(lambda state: self._agent_view(state, connection_id, task_id, request_id))

    def list_requests(self) -> list[dict[str, Any]]:
        def capture(state):
            result = []
            for record in state["application_launches"]["requests"].values():
                result.append(self._human_view(record))
            return sorted(result, key=lambda item: (item["created_at"], item["request_id"]), reverse=True)
        return self.store.read(capture)

    def preview(self, request_id: Any) -> dict[str, Any]:
        request_id = _stable(request_id, "request_id")
        with self._guard:
            record = self.store.read(lambda state: self._human_record(state, request_id, allow_dispatch=False))
            try:
                result = self._coordinator.preview_application_launch(app_id=record["app_id"], url=record["url"])
            except Exception as error:
                raise AgentLinkError("application_preview_unavailable", "application preview is unavailable") from error
            preview = _preview(result, record)
            digest = _canonical_hash(preview)

            def change(state):
                current = self._human_record(state, request_id, allow_dispatch=False)
                if current["app_id"] != record["app_id"] or current["url"] != record["url"]:
                    raise AgentLinkError("idempotency_conflict", "launch request changed")
                current.update({"status": "previewed", "preview": preview, "preview_sha256": digest,
                                "previewed_at": time.time_ns()})
                return {**deepcopy(preview), "preview_sha256": digest}
            return self.store.mutate(change)

    def confirm(self, request_id: Any, expected_preview_sha256: Any) -> dict[str, Any]:
        request_id = _stable(request_id, "request_id")
        if not isinstance(expected_preview_sha256, str) or _HASH.fullmatch(expected_preview_sha256) is None:
            raise AgentLinkError("invalid_arguments", "preview binding is invalid")
        with self._guard:
            # 启动之前先落盘不可重试状态；重开后的 dispatch_started 绝不能再次调用启动器。
            def begin(state):
                record = self._human_record(state, request_id, allow_dispatch=False)
                if record["status"] != "previewed":
                    raise AgentLinkError("launch_not_previewed", "launch requires an exact current preview")
                preview = record["preview"]
                if record["preview_sha256"] != expected_preview_sha256 or record["preview_sha256"] != _canonical_hash(preview):
                    raise AgentLinkError("stale_preview", "launch preview is no longer current")
                record["status"] = "dispatch_started"
                record["dispatch_started_at"] = time.time_ns()
                return deepcopy(preview)
            preview = self.store.mutate(begin)
            try:
                outcome = self._coordinator.confirm_window_preparation(preview["preparation_id"])
            except Exception as error:
                # 已经不知道系统启动调用是否产生效果；不得自动重试。
                raise AgentLinkError("launch_result_unknown", "launch result is unknown and cannot be retried") from error
            checked = _outcome(outcome)
            def finish(state):
                record = self._human_record(state, request_id, allow_dispatch=True)
                if record["status"] != "dispatch_started":
                    raise AgentLinkError("launch_result_unknown", "launch record changed during dispatch")
                record["status"] = checked["status"]
                record["outcome"] = checked
                record["completed_at"] = time.time_ns()
                return deepcopy(checked)
            return self.store.mutate(finish)

    def _require_connection(self, connection_id: str, task_id: str) -> None:
        self.store.read(lambda state: self._checked_connection(state, connection_id, task_id))

    @staticmethod
    def _checked_connection(state: dict[str, Any], connection_id: str, task_id: str) -> dict[str, Any]:
        connection = state["connections"].get(connection_id)
        if connection is None or connection["task_id"] != task_id:
            raise AgentLinkError("not_found", "application launch request was not found")
        if connection["revoked"]:
            raise AgentLinkError("connection_revoked", "agent connection is revoked")
        return connection

    def _agent_view(self, state, connection_id, task_id, request_id):
        self._checked_connection(state, connection_id, task_id)
        record = state["application_launches"]["requests"].get(request_id)
        if record is None or record["connection_id"] != connection_id or record["task_id"] != task_id:
            raise AgentLinkError("not_found", "application launch request was not found")
        return self._request_view(record)

    def _human_record(self, state, request_id, *, allow_dispatch: bool) -> dict[str, Any]:
        record = state["application_launches"]["requests"].get(request_id)
        if record is None:
            raise AgentLinkError("not_found", "application launch request was not found")
        self._checked_connection(state, record["connection_id"], record["task_id"])
        if not allow_dispatch and record["status"] in {"dispatch_started", "launched_window_ready", "launched_window_unavailable"}:
            raise AgentLinkError("launch_not_available", "application launch is no longer available for confirmation")
        return record

    @staticmethod
    def _request_receipt(record: dict[str, Any]) -> dict[str, Any]:
        status = record["status"]
        return {"contract_version": _CONTRACT, "request_id": record["request_id"], "app_id": record["app_id"],
                "status": status, "staging_only": status not in {"launched_window_ready", "launched_window_unavailable"},
                "action_executed": False}

    @staticmethod
    def _request_view(record: dict[str, Any]) -> dict[str, Any]:
        result = {"contract_version": _CONTRACT, "request_id": record["request_id"], "app_id": record["app_id"],
                  "url": record["url"], "status": record["status"], "staging_only": True,
                  "action_executed": False}
        if record["status"] in {"launched_window_ready", "launched_window_unavailable"}:
            result.update(deepcopy(record["outcome"]))
            result["staging_only"] = False
            result["action_executed"] = False
        elif record["status"] == "dispatch_started":
            result["result_unknown"] = True
        return result

    @staticmethod
    def _human_view(record: dict[str, Any]) -> dict[str, Any]:
        return {key: deepcopy(record[key]) for key in ("request_id", "task_id", "app_id", "url", "created_at", "status")}


def _discovery(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"contract_version", "apps", "running_windows"} or value.get("contract_version") != "native_application_discovery_v1":
        raise AgentLinkError("application_catalog_unavailable", "application catalog is invalid")
    apps, windows = value["apps"], value["running_windows"]
    if not isinstance(apps, list) or not isinstance(windows, list):
        raise AgentLinkError("application_catalog_unavailable", "application catalog is invalid")
    ids = set()
    for app in apps:
        base = {"app_id", "name", "capabilities", "executable_path", "launchable"}
        allowed = base | ({"unavailable_reason"} if isinstance(app, dict) and not app.get("launchable") else set())
        if not isinstance(app, dict) or set(app) != allowed or _ID.fullmatch(app.get("app_id", "")) is None or app["app_id"] in ids or not isinstance(app["name"], str) or not app["name"] or not isinstance(app["capabilities"], list) or not all(isinstance(item, str) and item for item in app["capabilities"]) or type(app["launchable"]) is not bool:
            raise AgentLinkError("application_catalog_unavailable", "application catalog is invalid")
        if app["launchable"]:
            if not isinstance(app["executable_path"], str) or not app["executable_path"]:
                raise AgentLinkError("application_catalog_unavailable", "application catalog is invalid")
        elif app["executable_path"] is not None or not isinstance(app.get("unavailable_reason"), str) or not app["unavailable_reason"]:
            raise AgentLinkError("application_catalog_unavailable", "application catalog is invalid")
        ids.add(app["app_id"])
    return deepcopy(value)


def _preview(value: Any, record: dict[str, Any]) -> dict[str, Any]:
    keys = {"contract_version", "preparation_id", "mode", "identity", "source", "app_id", "name", "url", "command", "executable_path", "catalog_entry_sha256", "executable_sha256", "expires_in_seconds"}
    if isinstance(value, dict) and 'working_directory' in value:
        cwd = value['working_directory']
        if not isinstance(cwd, str) or not cwd or not ntpath.isabs(cwd):
            raise AgentLinkError('application_preview_unavailable', 'application working directory is invalid')
        keys.add('working_directory')
    if not isinstance(value, dict) or set(value) != keys or value.get("contract_version") != "native_window_preparation_v1" or value.get("mode") != "launch" or value.get("identity") is not None or value.get("source") != "app_catalog" or value.get("app_id") != record["app_id"] or value.get("url") != record["url"] or _ID.fullmatch(value.get("preparation_id", "")) is None or not isinstance(value.get("name"), str) or not value["name"] or not isinstance(value.get("executable_path"), str) or not value["executable_path"] or not isinstance(value.get("catalog_entry_sha256"), str) or _HASH.fullmatch(value["catalog_entry_sha256"]) is None or not isinstance(value.get("executable_sha256"), str) or _HASH.fullmatch(value["executable_sha256"]) is None or type(value.get("expires_in_seconds")) is not int or not 1 <= value["expires_in_seconds"] <= 3600 or not isinstance(value.get("command"), list) or not 1 <= len(value["command"]) <= 32 or any(not isinstance(item, str) or not item or len(item) > 4096 for item in value["command"]) or value["command"][0] != value["executable_path"]:
        raise AgentLinkError("application_preview_unavailable", "application preview is invalid")
    return deepcopy(value)


def _outcome(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") not in {"launched_window_ready", "launched_window_unavailable"}:
        raise AgentLinkError("launch_result_unknown", "launch result is invalid")
    status = value["status"]
    if status == "launched_window_ready":
        if set(value) != {"status", "process_id", "window"} or type(value["process_id"]) is not int or value["process_id"] <= 0 or not isinstance(value["window"], dict) or set(value["window"]) != {"handle", "process_id", "title"} or type(value["window"]["handle"]) is not int or value["window"]["handle"] <= 0 or type(value["window"].get("process_id")) is not int or value["window"]["process_id"] <= 0 or not isinstance(value["window"]["title"], str):
            raise AgentLinkError("launch_result_unknown", "launch result is invalid")
    else:
        required = {"status", "process_id", "window", "reason", "result_unknown", "launch_effect_undone"}
        if set(value) != required or value["window"] is not None or (value["process_id"] is not None and (type(value["process_id"]) is not int or value["process_id"] <= 0)) or not isinstance(value["reason"], str) or not value["reason"] or value["result_unknown"] is not True or value["launch_effect_undone"] is not False:
            raise AgentLinkError("launch_result_unknown", "launch result is invalid")
    return deepcopy(value)
