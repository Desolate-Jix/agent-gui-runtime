"""复用现有应用目录解析，不创建第二个启动器。"""
from copy import deepcopy
import hashlib
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

from app.agent.native_identity import normalize_windows_executable_path
from app.agent_link.contracts import canonical_hash
from app.core.launch_text import has_launch_display_controls


def _catalog():
    from app.api.apps import _load_app_catalog

    catalog = _load_app_catalog()
    apps = catalog.get("apps") if isinstance(catalog, dict) else None
    if not isinstance(apps, list) or any(not isinstance(app, dict) for app in apps):
        raise ValueError("application catalog is invalid")
    ids = [app.get("app_id") for app in apps]
    if any(not isinstance(item, str) or not item or len(item) > 128 for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("application catalog identifiers are missing or ambiguous")
    return deepcopy(catalog)


def _resolve(app, url=None):
    from app.api.apps import _resolve_launch_command
    from app.api.models.request import OpenAppRequest

    raw = app.get("launch_command")
    if (not isinstance(raw, list) or not raw or len(raw) > 64
            or any(not isinstance(arg, str) or not arg or len(arg) > 8192
                   or has_launch_display_controls(arg) for arg in raw)):
        raise ValueError("catalog launch command is invalid")
    command = _resolve_launch_command(app, OpenAppRequest(app_id=app["app_id"], url=url))
    normalized = normalize_windows_executable_path(command[0])
    path = PureWindowsPath(normalized or "")
    if (normalized is None or path.suffix != ".exe" or normalized.startswith("\\")
            or any(part == ".." or ":" in part for part in path.parts[1:])
            or not Path(normalized).is_file()):
        raise ValueError("catalog executable must be an existing local .exe file")
    command[0] = normalized
    return command


def application_catalog_view():
    apps = []
    for app in _catalog()["apps"]:
        item = {"app_id": app["app_id"], "name": str(app.get("name") or app["app_id"]),
                "capabilities": deepcopy(app.get("capabilities", [])), "executable_path": None, "launchable": False}
        try:
            item["executable_path"] = _resolve(app)[0]
            item["launchable"] = True
        except (ValueError, TypeError, OSError):
            item["unavailable_reason"] = "catalog_executable_unavailable"
        apps.append(item)
    return apps


def application_launch_selection(app_id, url=None):
    if not isinstance(app_id, str) or not app_id or len(app_id) > 128:
        raise ValueError("catalog application ID is invalid")
    matches = [app for app in _catalog()["apps"] if app["app_id"] == app_id]
    if len(matches) != 1:
        raise ValueError("catalog application was not found")
    app = matches[0]
    if url is not None:
        if (not isinstance(url, str) or not 1 <= len(url) <= 8192
                or has_launch_display_controls(url) or " " in url or "\\" in url):
            raise ValueError("application URL is invalid")
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("application URL must be HTTP(S) without credentials")
        _ = parsed.port
        if "open_url" not in app.get("capabilities", []):
            raise ValueError("catalog application does not accept URLs")
    command = _resolve(app, url)
    # 浏览器启动验收绑定新增窗口；显式新窗口避免已有进程只开标签后一直等不到新 HWND。
    if (url is not None and "browser_ui" in app.get("capabilities", [])
            and PureWindowsPath(command[0]).name.casefold() in {"msedge.exe", "chrome.exe"}
            and "--new-window" not in command[1:]):
        command.insert(1, "--new-window")
    # 固定实际文件摘要，避免预览后替换程序仍沿用原确认。
    with Path(command[0]).open("rb") as source:
        executable_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    return {"source": "app_catalog", "app_id": app_id, "name": str(app.get("name") or app_id),
            "url": url, "command": command, "executable_path": command[0],
            "catalog_entry_sha256": canonical_hash(app), "executable_sha256": executable_sha256}
