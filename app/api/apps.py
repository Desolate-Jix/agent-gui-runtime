from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.core.runtime_artifacts import write_trace
from app.core.window_manager import window_manager
from app.models.request import OpenAppRequest
from app.models.response import APIResponse, ErrorModel

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
            "process_name": "msedge.exe",
            "title_hint": "Microsoft Edge",
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
    try:
        catalog = _load_app_catalog()
        app = _resolve_app(catalog, request)
        command = request.command or app.get("launch_command")
        if not command:
            return APIResponse(
                success=False,
                message="No launch command available",
                data={"app": app},
                error=ErrorModel(code="missing_launch_command", details="Provide app_id with launch_command or request.command"),
            )
        process = subprocess.Popen(command)
        time.sleep(float(request.wait_seconds))
        windows = window_manager.list_visible_windows()
        bound_payload = None
        bind_error = None
        process_name = request.process_name or app.get("process_name")
        title = request.title or app.get("title_hint")
        if request.bind_after_open:
            try:
                bound = window_manager.bind_window(process_name=process_name, title=title)
                bound_payload = _bound_window_payload(bound)
            except Exception as exc:
                bind_error = str(exc)
        result = {
            "contract_version": "app_open_result_v1",
            "app": app,
            "command": command,
            "process_id": process.pid,
            "bind_after_open": request.bind_after_open,
            "bound_window": bound_payload,
            "bind_error": bind_error,
            "running_windows": windows,
        }
        result["trace_path"] = write_trace(
            category="apps",
            operation="open_app",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=str(app.get("app_id") or "custom_app"),
        )
        return APIResponse(success=True, message="App open requested", data=result, error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="apps",
            operation="open_app",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_id or "custom_app",
        )
        return APIResponse(
            success=False,
            message="App open failed",
            data={"trace_path": trace_path},
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
