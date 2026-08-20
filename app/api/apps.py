from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.core.window_manager import window_manager
from app.api.models.request import OpenAppRequest
from app.api.models.response import APIResponse, ErrorModel
from app.operation.runtime_context import build_operation_runtime_context, operation_trace_link

router = APIRouter(prefix="/apps", tags=["apps"])

APP_CATALOG_PATH = Path("configs/app_catalog.json")

DEFAULT_APP_CATALOG = {
    "contract_version": "app_catalog_v1",
    "apps": [
        {
            "app_id": "edge",
            "name": "Microsoft Edge",
            "description": "Web browser for website and web-app tasks.",
            "launch_command": ["msedge.exe"],
            "executable_candidates": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "process_name": "msedge.exe",
            "title_hint": "Microsoft Edge",
            "capabilities": ["open_url", "web_navigation", "web_forms", "browser_ui"],
        },
        {
            "app_id": "chrome",
            "name": "Google Chrome",
            "description": "Chrome browser for website and web-app tasks.",
            "launch_command": ["chrome.exe"],
            "executable_candidates": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            ],
            "process_name": "chrome.exe",
            "title_hint": "Google Chrome",
            "capabilities": ["open_url", "web_navigation", "web_forms", "browser_ui"],
        },
        {
            "app_id": "notepad",
            "name": "Notepad",
            "description": "Plain text editor for simple local text editing tasks.",
            "launch_command": ["notepad.exe"],
            "process_name": "notepad.exe",
            "title_hint": "Notepad",
            "capabilities": ["text_editing", "file_text_review"],
        },
        {
            "app_id": "calculator",
            "name": "Calculator",
            "description": "Windows Calculator for desktop GUI recognition and learning tasks.",
            "launch_command": ["calc.exe"],
            "process_name": "ApplicationFrameHost.exe",
            "title_hints": ["Calculator", "计算器"],
            "require_title_match": True,
            "capabilities": ["calculation", "desktop_ui"],
        },
    ],
}


@router.get("", response_model=APIResponse)
def list_apps() -> APIResponse:
    """Return launchable catalog apps and currently visible windows for agent startup."""
    catalog = _load_app_catalog()
    try:
        windows = window_manager.list_visible_windows()
        window_status = "ok"
    except Exception as exc:
        windows = []
        window_status = "unavailable"
        window_error = str(exc)
    else:
        window_error = None
    bound = window_manager.get_bound_window()
    payload: dict[str, Any] = {
        "contract_version": "app_discovery_v1",
        "catalog": catalog,
        "running_windows": windows,
        "bound_window": _bound_window_payload(bound),
        "window_status": window_status,
        "agent_next_steps": [
            "Choose an app from catalog.apps or a visible running window.",
            "Open a catalog app with POST /apps/open when needed.",
            "Bind an existing window with POST /session/bind_window when already running.",
            "Call POST /vision/observe_screen to understand the current screen before precise localization.",
        ],
    }
    if window_error:
        payload["window_error"] = window_error
    return APIResponse(success=True, message="Apps listed", data=payload, error=None)


@router.post("/open", response_model=APIResponse)
def open_app(request: OpenAppRequest) -> APIResponse:
    """Open an app from the catalog or from an explicit command, then optionally bind a matching window."""
    timer = RuntimeTimer()
    try:
        with timer.step("load_app_catalog"):
            catalog = _load_app_catalog()
        with timer.step("resolve_app", app_id=request.app_id):
            app = _resolve_app(catalog, request)
        with timer.step("resolve_launch_command", app_id=app.get("app_id")):
            command = _resolve_launch_command(app, request)
        if not command:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No launch command available",
                data={"app": app, "timings": timings},
                error=ErrorModel(code="missing_launch_command", details="Provide app_id with launch_command or request.command"),
            )
        before_windows: list[dict[str, Any]] = []
        if request.bind_after_open and request.prefer_new_window:
            with timer.step("list_visible_windows_before_open"):
                before_windows = window_manager.list_visible_windows()
        with timer.step("launch_process", executable=command[0] if command else None):
            process = subprocess.Popen(command)
        wait_seconds = float(request.wait_seconds)
        with timer.step("wait_after_open", wait_seconds=wait_seconds, requested_wait_seconds=request.wait_seconds):
            time.sleep(wait_seconds)
        with timer.step("list_visible_windows"):
            windows = window_manager.list_visible_windows()
        bound_payload = None
        bind_error = None
        maximize_error = None
        process_name = request.process_name or app.get("process_name")
        title_hints = _app_title_hints(app, request)
        title = title_hints[0] if title_hints else None
        title_required = bool(request.title) or bool(app.get("require_title_match"))
        if request.bind_after_open:
            try:
                with timer.step(
                    "bind_window",
                    process_name=process_name,
                    title=title,
                    prefer_new_window=request.prefer_new_window,
                ):
                    bound = _bind_opened_window(
                        process_name=process_name,
                        title=title,
                        title_hints=title_hints,
                        title_required=title_required,
                        before_windows=before_windows,
                        after_windows=windows,
                        prefer_new_window=request.prefer_new_window,
                    )
                bound_payload = _bound_window_payload(bound)
            except Exception as exc:
                bind_error = str(exc)
            if bound_payload is not None and request.maximize_after_open:
                try:
                    with timer.step("maximize_bound_window", handle=bound.handle):
                        bound = window_manager.maximize_bound_window()
                    bound_payload = _bound_window_payload(bound)
                except Exception as exc:
                    maximize_error = str(exc)
        result = {
            "contract_version": "app_open_result_v1",
            "app": app,
            "command": command,
            "process_id": process.pid,
            "bind_after_open": request.bind_after_open,
            "prefer_new_window": request.prefer_new_window,
            "maximize_after_open": request.maximize_after_open,
            "bound_window": bound_payload,
            "bind_error": bind_error,
            "maximize_error": maximize_error,
            "windows_before_open": before_windows,
            "running_windows": windows,
        }
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="bind_window",
            semantic_action="bind_window" if bound_payload is not None else "open_app",
            side_effect_class="navigation",
            requires_gate=False,
            window_binding_id=f"window:{int(bound.handle)}" if bound_payload is not None and bound is not None else None,
            viewport_size=_bound_window_size(bound_payload),
        )
        result["operation_context"] = operation_context
        result["operation_trace_link"] = operation_trace_link(operation_context, result_status="success")
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="apps",
            operation="open_app",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=str(app.get("app_id") or "custom_app"),
        )
        return APIResponse(success=True, message="App open requested", data=result, error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="apps",
            operation="open_app",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_id or "custom_app",
        )
        return APIResponse(
            success=False,
            message="App open failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="app_open_failed", details=str(exc)),
        )


def _load_app_catalog() -> dict[str, Any]:
    if not APP_CATALOG_PATH.exists():
        return DEFAULT_APP_CATALOG
    payload = json.loads(APP_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return DEFAULT_APP_CATALOG
    payload.setdefault("contract_version", "app_catalog_v1")
    payload.setdefault("apps", [])
    return payload


def _resolve_app(catalog: dict[str, Any], request: OpenAppRequest) -> dict[str, Any]:
    apps = catalog.get("apps") if isinstance(catalog.get("apps"), list) else []
    if request.app_id:
        for app in apps:
            if isinstance(app, dict) and app.get("app_id") == request.app_id:
                return app
        raise ValueError(f"app_id not found in app catalog: {request.app_id}")
    if request.command:
        return {
            "app_id": "custom",
            "name": "Custom command",
            "launch_command": request.command,
            "process_name": request.process_name,
            "title_hint": request.title,
            "capabilities": ["custom_launch"],
        }
    raise ValueError("Provide app_id or command")


def _app_title_hints(app: dict[str, Any], request: OpenAppRequest) -> list[str]:
    if request.title:
        return [request.title]
    raw_hints = app.get("title_hints")
    if isinstance(raw_hints, list):
        hints = [str(item).strip() for item in raw_hints if str(item).strip()]
        if hints:
            return hints
    title_hint = str(app.get("title_hint") or "").strip()
    return [title_hint] if title_hint else []


def _resolve_launch_command(app: dict[str, Any], request: OpenAppRequest) -> list[str] | None:
    command = list(request.command or app.get("launch_command") or [])
    if not command:
        return None
    command[0] = _resolve_executable(command[0], app.get("executable_candidates") or [])
    if request.url:
        command.append(request.url)
    return command


def _is_browser_app(app: dict[str, Any]) -> bool:
    app_id = str(app.get("app_id") or "").lower()
    capabilities = {str(item).lower() for item in (app.get("capabilities") or [])}
    process_name = str(app.get("process_name") or "").lower()
    return (
        app_id in {"edge", "chrome", "browser", "firefox"}
        or "browser_ui" in capabilities
        or process_name in {"msedge.exe", "chrome.exe", "firefox.exe"}
    )


def _bind_opened_window(
    process_name: str | None,
    title: str | None,
    *,
    title_hints: list[str] | None = None,
    title_required: bool,
    before_windows: list[dict[str, Any]] | None = None,
    after_windows: list[dict[str, Any]] | None = None,
    prefer_new_window: bool = True,
) -> Any:
    if prefer_new_window:
        new_window = _new_matching_window(before_windows or [], after_windows or [], process_name=process_name)
        if new_window and new_window.get("handle") is not None:
            return window_manager.bind_window_by_handle(int(new_window["handle"]))
    candidates = title_hints or ([title] if title else [])
    last_error: Exception | None = None
    for candidate_title in candidates:
        try:
            return window_manager.bind_window(process_name=process_name, title=candidate_title)
        except Exception as exc:
            last_error = exc
    if title_required:
        if last_error is not None:
            raise last_error
        raise ValueError("A required window title hint was not configured")
    if not process_name:
        if last_error is not None:
            raise last_error
        raise ValueError("A process name or window title hint is required to bind the opened app")
    return window_manager.bind_window(process_name=process_name, title=None)


def _new_matching_window(
    before_windows: list[dict[str, Any]],
    after_windows: list[dict[str, Any]],
    *,
    process_name: str | None,
) -> dict[str, Any] | None:
    before_handles = {int(item["handle"]) for item in before_windows if isinstance(item, dict) and item.get("handle") is not None}
    process_query = process_name.strip().lower() if process_name else None
    new_matches: list[dict[str, Any]] = []
    for item in after_windows:
        if not isinstance(item, dict) or item.get("handle") is None:
            continue
        if int(item["handle"]) in before_handles:
            continue
        if process_query and str(item.get("process_name") or "").strip().lower() != process_query:
            continue
        new_matches.append(item)
    return new_matches[-1] if new_matches else None


def _resolve_executable(executable: str, candidates: list[Any]) -> str:
    expanded = os.path.expandvars(str(executable))
    path = Path(expanded)
    if path.is_absolute() and path.exists():
        return str(path)
    if "\\" in expanded or "/" in expanded:
        return expanded
    found = shutil.which(expanded)
    if found:
        return found
    for candidate in candidates:
        candidate_path = Path(os.path.expandvars(str(candidate)))
        if candidate_path.exists():
            return str(candidate_path)
    return expanded


def _bound_window_payload(bound: Any) -> dict[str, Any] | None:
    if bound is None:
        return None
    return {
        "bound": True,
        "handle": bound.handle,
        "window_title": bound.title,
        "process_id": bound.process_id,
        "process_name": bound.process_name,
        "rect": {
            "left": bound.rect.left,
            "top": bound.rect.top,
            "right": bound.rect.right,
            "bottom": bound.rect.bottom,
        },
        "is_active": bound.is_active,
    }


def _bound_window_size(bound_payload: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(bound_payload, dict):
        return None
    rect = bound_payload.get("rect")
    if not isinstance(rect, dict):
        return None
    try:
        width = int(rect["right"]) - int(rect["left"])
        height = int(rect["bottom"]) - int(rect["top"])
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}
