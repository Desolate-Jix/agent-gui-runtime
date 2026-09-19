"""原生窗口准备意图：预览不产生外部效果，确认后才允许一次聚焦或启动。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from pathlib import PureWindowsPath
import time
from typing import Any
from uuid import uuid4

from app.agent.native_identity import (
    WindowsNativeIdentityReader,
    require_reviewed_native_executable_path,
    validate_native_identity_fact,
)
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.core.window_close import post_window_close, window_handle_exists


class WindowPreparationMixin:
    _WINDOW_PREPARATION_TTL_SECONDS = 60.0

    def discover_applications(self) -> dict[str, Any]:
        from .application_catalog import application_catalog_view

        self._begin("idle", preserve_window_preparation=True)
        try:
            self._require_host_ready(require_unattached=True)
            return self._owner.call(lambda: {
                "contract_version": "native_application_discovery_v1",
                "apps": application_catalog_view(),
                "running_windows": self._windows().list_visible_windows(),
            })
        finally:
            self._end()

    def preview_application_launch(self, *, app_id: str, url: str | None = None) -> dict[str, Any]:
        self._begin("idle")
        try:
            self._require_host_ready(require_unattached=True)
            if getattr(self, "_unverified_window_launch", None) is not None:
                raise self._error("window_launch_requires_inventory", "Inspect existing windows before another launch.")
            intent = self._owner.call(lambda: self._build_application_launch(app_id=app_id, url=url))
            self._window_preparations[intent["preparation_id"]] = deepcopy(intent)
            return deepcopy(_public_intent(intent))
        finally:
            self._end()

    def _build_application_launch(self, *, app_id: str, url: str | None) -> dict[str, Any]:
        from .application_catalog import application_launch_selection

        try:
            selection = application_launch_selection(app_id, url)
        except (ValueError, TypeError, OSError) as error:
            raise self._error("window_preparation_launch_invalid", "Catalog application or URL is unavailable or invalid.") from error
        return {**selection, "contract_version": "native_window_preparation_v1",
                "preparation_id": str(uuid4()), "mode": "launch", "identity": None,
                "expires_at": time.monotonic() + self._WINDOW_PREPARATION_TTL_SECONDS}

    def preview_window_preparation(
        self,
        *,
        mode: str,
        asset_id: str,
        asset_content_sha256: str,
        target_window_handle: int | None = None,
        target_process_id: int | None = None,
    ) -> dict[str, Any]:
        self._begin("idle")
        try:
            self._require_host_ready(require_unattached=True)
            if mode == "launch" and getattr(self, "_unverified_window_launch", None) is not None:
                raise self._error("window_launch_requires_inventory", "Inspect existing windows before another launch.")
            intent = self._owner.call(lambda: self._build_window_preparation(
                mode=mode,
                asset_id=asset_id,
                asset_content_sha256=asset_content_sha256,
                target_window_handle=target_window_handle,
                target_process_id=target_process_id,
            ))
            self._window_preparations[intent["preparation_id"]] = deepcopy(intent)
            return deepcopy(_public_intent(intent))
        finally:
            self._end()

    def confirm_window_preparation(self, preparation_id: str) -> dict[str, Any]:
        self._begin("idle", preserve_window_preparation=True)
        try:
            self._require_host_ready(require_unattached=True)
            return self._owner.call(lambda: self._confirm_window_preparation_on_owner(preparation_id))
        finally:
            self._end()

    def preview_selected_window_preparation(
        self, *, target_window_handle: int, target_process_id: int,
    ) -> dict[str, Any]:
        """首次学习只预览已选窗口；仍由本地单独确认恢复/聚焦。"""
        self._begin("idle")
        try:
            self._require_host_ready(require_unattached=True)
            intent = self._owner.call(lambda: self._build_selected_window_preparation(
                target_window_handle=target_window_handle, target_process_id=target_process_id))
            self._window_preparations[intent["preparation_id"]] = deepcopy(intent)
            return deepcopy(_public_intent(intent))
        finally:
            self._end()

    def preview_selected_window_maximize(
        self, *, target_window_handle: int, target_process_id: int,
    ) -> dict[str, Any]:
        """首次学习只预览最大化选定窗口；确认后仍不授予键鼠权限。"""
        self._begin("idle")
        try:
            self._require_host_ready(require_unattached=True)
            intent = self._owner.call(lambda: self._build_selected_window_preparation(
                target_window_handle=target_window_handle,
                target_process_id=target_process_id,
                mode="maximize",
            ))
            self._window_preparations[intent["preparation_id"]] = deepcopy(intent)
            return deepcopy(_public_intent(intent))
        finally:
            self._end()

    def _build_selected_window_preparation(
        self, *, target_window_handle: int, target_process_id: int, mode: str = "focus",
    ) -> dict[str, Any]:
        handle, pid = target_window_handle, target_process_id
        if mode not in {"focus", "maximize"}:
            raise self._error("window_preparation_mode_invalid", "Selected window preparation mode is invalid.")
        if type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0:
            raise self._error("window_preparation_identity_invalid", "Focus requires a selected HWND and PID.")
        try:
            bound = self._windows().bind_window_by_handle(handle)
            identity = WindowsNativeIdentityReader(window_manager=self._windows()).read_identity(handle)
            checked = validate_native_identity_fact(identity, target_window_handle=handle, expected_process_id=pid)
        except Exception as error:
            raise self._error("window_preparation_identity_invalid", "Selected window identity is unavailable.") from error
        if checked is None:
            raise self._error("window_preparation_identity_invalid", "Selected window identity does not match the selected process.")
        return {
            "contract_version": "native_window_preparation_v1", "source": "selected_window",
            "preparation_id": str(uuid4()), "mode": mode, "title": bound.title,
            "executable_path": checked["executable_path"], "identity": checked,
            "expires_at": time.monotonic() + self._WINDOW_PREPARATION_TTL_SECONDS,
        }

    def _confirm_window_preparation_on_owner(self, preparation_id: str) -> dict[str, Any]:
        self._require_host_ready(require_unattached=True)
        if self._attached or self._history_confirmation_id is not None:
            raise self._error("window_preparation_unavailable", "runtime owner is already attached")
        intent = self._window_preparations.pop(str(preparation_id), None)
        if not isinstance(intent, dict):
            raise self._error("window_preparation_not_found", "window preparation is absent or consumed")
        if time.monotonic() >= intent["expires_at"]:
            raise self._error("window_preparation_expired", "window preparation has expired")
        checked = self._revalidate_window_preparation(intent)
        if self._cancel_wait.is_set():
            raise self._error("window_preparation_cancelled", "Window preparation was cancelled before dispatch.")
        if checked["mode"] in {"focus", "maximize"}:
            from app.core.window_preparation import _mint_window_preparation_permit

            permit = _mint_window_preparation_permit(
                self._windows(), checked["identity"], WindowsNativeIdentityReader(window_manager=self._windows()),
                operation=checked["mode"],
            )
            try:
                bound = (
                    self._windows().prepare_bound_window(permit)
                    if checked["mode"] == "focus"
                    else self._windows().prepare_maximized_bound_window(permit)
                )
            except Exception as error:
                from app.core.window_preparation import window_preparation_failure_details, window_preparation_failure_message

                code = "window_focus_unverified" if checked["mode"] == "focus" else "window_maximize_unverified"
                details = window_preparation_failure_details(error)
                failure = self._error(code, "Window preparation may have started but was not verified."
                    + window_preparation_failure_message(details), result_unknown=True)
                failure.diagnostics = details
                raise failure from error
            self._cache_prepared_identity(checked, checked["identity"])
            return {"status": "focused" if checked["mode"] == "focus" else "maximized", "window": _bound(bound)}
        if getattr(self, "_unverified_window_launch", None) is not None:
            raise self._error("window_launch_requires_inventory", "Inspect existing windows before another launch.")
        from app.core.application_launch import launch_process

        # 启动器 PID 不等于 GUI PID；只接受启动后新增且程序身份唯一的窗口。
        before = self._visible_window_handles()
        if self._cancel_wait.is_set():
            raise self._error("window_preparation_cancelled", "Window preparation was cancelled before launch.")
        process_id = None
        try:
            process = launch_process(checked.get("command", [checked["executable_path"]]))
            if type(process.pid) is int and process.pid > 0:
                process_id = process.pid
            result = self._await_launched_window(checked, process, before)
        except Exception:
            result = _launch_unavailable(process_id, "launch_effect_not_undone_after_observation_error")
        self._unverified_window_launch = deepcopy(result) if result["status"] != "launched_window_ready" else None
        return result

    def close_launched_window(self, *, target_window_handle: int, target_process_id: int) -> dict[str, Any]:
        """仅关闭本协调器通过 launch 新增且身份仍一致的窗口。"""
        self._begin("idle", preserve_window_preparation=True)
        try:
            self._require_host_ready()
            return self._owner.call(lambda: self._close_launched_window_on_owner(
                target_window_handle=target_window_handle, target_process_id=target_process_id))
        finally:
            self._end()

    def _close_launched_window_on_owner(self, *, target_window_handle: int, target_process_id: int) -> dict[str, Any]:
        if type(target_window_handle) is not int or target_window_handle <= 0 or type(target_process_id) is not int or target_process_id <= 0:
            raise self._error("window_close_identity_invalid", "window close requires a valid handle and process id")
        identity = getattr(self, "_launched_window_identities", {}).get((target_window_handle, target_process_id))
        if identity is None:
            raise self._error("window_close_not_launched", "window was not launched by this coordinator")
        close_state = getattr(self, "_launched_window_close_state", {})
        # 已发关闭请求后只补确认，窗口消失时不能再绑定它。
        if close_state.get((target_window_handle, target_process_id)) and not window_handle_exists(target_window_handle):
            self._launched_window_identities.pop((target_window_handle, target_process_id), None)
            close_state.pop((target_window_handle, target_process_id), None)
            return {"status": "window_closed", "success": True, "close_requested": True,
                    "automatic_retry_allowed": False}
        try:
            self._windows().bind_window_by_handle(target_window_handle)
            current = validate_native_identity_fact(
                WindowsNativeIdentityReader(window_manager=self._windows()).read_identity(target_window_handle),
                target_window_handle=target_window_handle, expected_process_id=target_process_id,
            )
        except Exception as error:
            raise self._error("window_close_identity_unavailable", "launched window identity is unavailable") from error
        if current != identity:
            raise self._error("window_close_identity_changed", "launched window identity changed")
        if not close_state.get((target_window_handle, target_process_id), False):
            post_window_close(target_window_handle)
            close_state[(target_window_handle, target_process_id)] = True
            self._launched_window_close_state = close_state
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not window_handle_exists(target_window_handle):
                getattr(self, "_launched_window_identities", {}).pop((target_window_handle, target_process_id), None)
                close_state.pop((target_window_handle, target_process_id), None)
                return {"status": "window_closed", "success": True, "close_requested": True,
                        "automatic_retry_allowed": False}
            self._cancel_wait.wait(min(0.05, max(0.0, deadline - time.monotonic())))
        return {"status": "window_close_pending", "success": False, "close_requested": True,
                "automatic_retry_allowed": False}

    def _cache_prepared_identity(self, intent, identity):
        if intent.get("source") in {"app_catalog", "selected_window"}:
            # 首次启动/聚焦没有旧资产，不凭窗口回执授予资产或操作权限。
            return
        from app.agent.runtime_session_selection import RuntimeSessionSelection
        from .single_step_coordinator import _selection_identity

        # 写入和后续前台等待必须使用同一种键，不能丢失已准备的进程创建时间。
        key = _selection_identity(RuntimeSessionSelection(
            asset_id=intent["asset_id"], asset_content_sha256=intent["asset_content_sha256"],
            target_window_handle=identity["target_window_handle"], target_process_id=identity["process_id"]))
        self._prepared_window_identities.clear()
        self._prepared_window_identities[key] = deepcopy(identity)

    def _visible_window_handles(self):
        items = self._windows().list_visible_windows()
        if not isinstance(items, list) or any(not isinstance(item, dict) or type(item.get("handle")) is not int or item["handle"] <= 0 for item in items):
            raise self._error("window_inventory_invalid", "Visible window inventory is invalid.")
        return {item["handle"] for item in items}

    def clear_window_preparation(self) -> None:
        with self._guard:
            self._window_preparations.clear()

    def _build_window_preparation(self, **selection: Any) -> dict[str, Any]:
        mode = selection["mode"]
        if mode not in {"launch", "focus"}:
            raise self._error("window_preparation_mode_invalid", "window preparation mode is invalid")
        asset = ReviewedWorkflowAssetStore(project_root=self._project_root).load_active(selection["asset_id"])
        if content_sha256(asset) != selection["asset_content_sha256"]:
            raise self._error("window_preparation_asset_changed", "reviewed asset hash changed")
        executable_path = require_reviewed_native_executable_path(asset["application"])
        result: dict[str, Any] = {
            "contract_version": "native_window_preparation_v1",
            "preparation_id": str(uuid4()), "mode": mode,
            "asset_id": selection["asset_id"], "asset_content_sha256": selection["asset_content_sha256"],
            "executable_path": executable_path, "identity": None,
            "expires_at": time.monotonic() + self._WINDOW_PREPARATION_TTL_SECONDS,
        }
        if mode == "launch":
            native_path = PureWindowsPath(executable_path)
            path = Path(executable_path)
            if (not native_path.is_absolute() or not native_path.drive or native_path.suffix.lower() != ".exe"
                    or str(native_path).startswith("\\") or str(native_path).startswith("\\?\\")
                    or any(":" in part for part in native_path.parts[1:]) or not path.is_file()):
                raise self._error("window_preparation_launch_invalid", "reviewed executable is not a local existing file")
        else:
            handle, pid = selection["target_window_handle"], selection["target_process_id"]
            if type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0:
                raise self._error("window_preparation_identity_invalid", "focus requires a selected HWND and PID")
            self._windows().bind_window_by_handle(handle)
            identity = WindowsNativeIdentityReader(window_manager=self._windows()).read_identity(handle)
            checked = validate_native_identity_fact(identity, target_window_handle=handle,
                expected_process_id=pid, expected_executable_path=executable_path)
            if checked is None:
                raise self._error("window_preparation_identity_invalid", "selected window identity does not match reviewed application")
            result["identity"] = checked
        return result

    def _revalidate_window_preparation(self, intent: dict[str, Any]) -> dict[str, Any]:
        if intent.get("source") == "selected_window":
            rebuilt = self._build_selected_window_preparation(
                target_window_handle=intent["identity"]["target_window_handle"],
                target_process_id=intent["identity"]["process_id"], mode=intent["mode"])
            if (intent["mode"] not in {"focus", "maximize"} or rebuilt["identity"] != intent["identity"]
                    or rebuilt["executable_path"] != intent["executable_path"]):
                raise self._error("window_preparation_identity_changed", "Selected window identity changed after preview.")
            return intent
        if intent.get("source") == "app_catalog":
            rebuilt = self._build_application_launch(app_id=intent["app_id"], url=intent["url"])
            compared = {"app_id", "name", "url", "command", "executable_path", "catalog_entry_sha256", "executable_sha256"}
            if any(rebuilt[key] != intent[key] for key in compared):
                raise self._error("window_preparation_application_changed", "Catalog command or executable changed after preview.")
            return intent
        rebuilt = self._build_window_preparation(
            mode=intent["mode"], asset_id=intent["asset_id"], asset_content_sha256=intent["asset_content_sha256"],
            target_window_handle=(intent["identity"] or {}).get("target_window_handle"),
            target_process_id=(intent["identity"] or {}).get("process_id"),
        )
        if intent["mode"] == "focus" and rebuilt["identity"] != intent["identity"]:
            raise self._error("window_preparation_identity_changed", "selected window identity changed")
        return intent

    def _await_launched_window(self, intent: dict[str, Any], process: Any, before: set[int]) -> dict[str, Any]:
        process_id = process.pid if type(process.pid) is int and process.pid > 0 else None
        expected_path = intent["executable_path"]
        deadline = time.monotonic() + self._WINDOW_PREPARATION_TTL_SECONDS
        while time.monotonic() < deadline:
            if self._cancel_wait.is_set():
                return _launch_unavailable(process_id, "launch_effect_not_undone_after_cancel")
            handles = self._visible_window_handles() - before
            matches = []
            for handle in sorted(handles):
                self._windows().bind_window_by_handle(handle)
                identity = WindowsNativeIdentityReader(window_manager=self._windows()).read_identity(handle)
                observed = validate_native_identity_fact(identity, target_window_handle=handle)
                if observed is None:
                    return _launch_unavailable(process_id, "launched_window_identity_unavailable")
                if observed["executable_path"] == expected_path:
                    matches.append(observed)
            if len(matches) > 1:
                return _launch_unavailable(process_id, "launched_window_ambiguous")
            if len(matches) == 1:
                matched = matches[0]
                handle = matched["target_window_handle"]
                bound = self._windows().bind_window_by_handle(handle)
                current = WindowsNativeIdentityReader(window_manager=self._windows()).read_identity(handle)
                if validate_native_identity_fact(current, target_window_handle=handle) != matched:
                    return _launch_unavailable(process_id, "launched_window_identity_changed")
                if self._cancel_wait.is_set():
                    return _launch_unavailable(process_id, "launch_effect_not_undone_after_cancel")
                self._cache_prepared_identity(intent, matched)
                if not hasattr(self, "_launched_window_identities"):
                    self._launched_window_identities = {}
                self._launched_window_identities[(matched["target_window_handle"], matched["process_id"])] = deepcopy(matched)
                return {"status": "launched_window_ready", "process_id": process_id, "window": _bound(bound)}
            self._cancel_wait.wait(min(0.05, max(0, deadline - time.monotonic())))
        return _launch_unavailable(process_id, "launched_window_timeout")


def _launch_unavailable(process_id, reason):
    return {"status": "launched_window_unavailable", "process_id": process_id, "window": None,
            "reason": reason, "result_unknown": True, "launch_effect_undone": False}


def _public_intent(intent: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in intent.items() if key != "expires_at"}
    result["expires_in_seconds"] = 60
    return result


def _bound(value: Any) -> dict[str, Any]:
    return {"handle": int(value.handle), "process_id": int(value.process_id), "title": value.title}
