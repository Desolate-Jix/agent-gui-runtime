"""复用现有应用目录解析，不创建第二个启动器。"""
from copy import deepcopy
import hashlib
import ntpath
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


def _available_catalog():
    from .installed_applications import discover_installed_applications

    catalog = _catalog()
    existing = {app['app_id'] for app in catalog['apps']}
    discovered = discover_installed_applications()
    for app in catalog['apps']:
        try:
            command = _resolve(app)
        except (ValueError, TypeError, OSError):
            continue
        duplicates = [item for item in discovered if item['launch_command'] == command
                      and ntpath.normcase(item.get('working_directory') or '')
                      == ntpath.normcase(app.get('working_directory') or '')]
        # 仅合并唯一的同命令发现项；不同参数或工作目录仍保留为候选。
        if len(duplicates) == 1:
            duplicate = duplicates[0]
            app['aliases'] = sorted(set([duplicate['name'], *duplicate.get('aliases', [])]))
            discovered.remove(duplicate)
    catalog['apps'].extend(app for app in discovered if app['app_id'] not in existing)
    return catalog


class ApplicationSelectionError(ValueError):
    def __init__(self, code, message, candidates=()):
        super().__init__(message)
        self.diagnostics = {'error_code': code, 'candidates': [
            {key: item.get(key) for key in ('app_id', 'name', 'launch_command', 'working_directory')} for item in candidates],
            'next': 'Choose one candidate app_id, or supply an absolute local .exe/.lnk path.'}


def _resolve(app, url=None):
    from app.api.apps import _resolve_launch_command
    from app.api.models.request import OpenAppRequest

    raw = app.get("launch_command")
    if (not isinstance(raw, list) or not raw or len(raw) > 64
            or not raw[0] or any(not isinstance(arg, str) or len(arg) > 8192
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
    for app in _available_catalog()["apps"]:
        item = {"app_id": app["app_id"], "name": str(app.get("name") or app["app_id"]),
                "capabilities": deepcopy(app.get("capabilities", [])), "executable_path": None, "launchable": False}
        try:
            item["executable_path"] = _resolve(app)[0]
            item["launchable"] = True
        except (ValueError, TypeError, OSError):
            item["unavailable_reason"] = "catalog_executable_unavailable"
        apps.append(item)
    return apps


def application_launch_selection(app_id=None, url=None, *, name=None, path=None):
    selector = {key: value for key, value in {'app_id': app_id, 'name': name, 'path': path}.items() if value is not None}
    if len(selector) != 1 or any(not isinstance(value, str) or not value.strip() or len(value) > 4096
                                or has_launch_display_controls(value) for value in selector.values()):
        raise ValueError('launch requires exactly one non-empty app_id, name or path')
    if path is not None:
        from .installed_applications import explicit_application
        matches = [explicit_application(path)]
    else:
        apps = _available_catalog()['apps']
        if app_id is not None:
            matches = [app for app in apps if app['app_id'] == app_id]
        else:
            query = name.strip().casefold()
            labels = lambda app: [str(app.get('name', '')).casefold(),
                                  *(str(alias).casefold() for alias in app.get('aliases', []))]
            matches = [app for app in apps if query in labels(app)]
            if not matches:
                matches = [app for app in apps if any(query in label for label in labels(app))]
    if len(matches) != 1:
        raise ApplicationSelectionError('application_name_ambiguous' if matches else 'application_not_found',
            'Multiple applications match; choose a candidate.' if matches else
            'Application was not discovered. Supply its .exe or .lnk path; MCP registration is not required.', matches)
    app = matches[0]
    app_id = app['app_id']
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
            "selector": selector, "working_directory": app.get('working_directory'),
            "url": url, "command": command, "executable_path": command[0],
            "catalog_entry_sha256": canonical_hash(app), "executable_sha256": executable_sha256}
