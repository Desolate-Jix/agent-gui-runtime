"""Opt-out daily release checks, isolated from task execution and API secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from app.runtime_lifecycle import InstallationMaintenance, RuntimeBusyError, update_state_path, _no_reparse

CHECK_INTERVAL_SECONDS = 86400


def minimal_environment():
    """System/runtime discovery only; no inherited model, MCP or profile keys."""
    names = {"systemroot", "windir", "temp", "tmp", "userprofile", "localappdata",
             "appdata", "path", "pathext", "comspec", "processor_architecture"}
    environment = {key: value for key, value in os.environ.items() if key.casefold() in names}
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return environment


def _read(root, name, default):
    path = update_state_path(root) / name
    _no_reparse(path)
    if not path.exists():
        return default
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("update_settings_too_large")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("update_settings_invalid")
    return value


def _write(root, name, value):
    state = update_state_path(root)
    _no_reparse(state)
    state.mkdir(parents=True, exist_ok=True)
    path = state / name
    _no_reparse(path)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    _no_reparse(temporary)
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def settings(root):
    value = _read(root, "check-settings.json", {"automatic_checks": True})
    if set(value) != {"automatic_checks"} or type(value["automatic_checks"]) is not bool:
        raise ValueError("update_settings_invalid")
    return value


def set_automatic_checks(root, enabled):
    if type(enabled) is not bool:
        raise ValueError("automatic_checks_boolean_required")
    _write(root, "check-settings.json", {"automatic_checks": enabled})
    return settings(root)


def cached_check(root):
    try:
        value = _read(root, "last-check.json", {"status": "not_checked"})
        concise = {key: value[key] for key in ("status", "checked_at", "error_type") if key in value}
        if "available_version" in value:
            concise["available_version"] = value["available_version"]
        elif isinstance(value.get("target"), dict):
            concise["available_version"] = value["target"].get("version")
        return {**concise, "automatic_checks": settings(root)["automatic_checks"],
                "automatic_install": False, "read_only": True}
    except (ValueError, OSError):
        return {"status": "check_state_unavailable", "automatic_install": False, "read_only": True}


def check_and_cache(root, *, scheduled=False, updater_factory=None, now=None):
    """Only check metadata. No staging, application, task cancellation or API use."""
    now = time.time() if now is None else now
    state = update_state_path(root)
    state.mkdir(parents=True, exist_ok=True)
    try:
        with InstallationMaintenance(state / "check-worker"):
            if scheduled:
                if not settings(root)["automatic_checks"]:
                    return {"status": "disabled"}
                previous = _read(root, "last-check.json", {})
                checked_at = previous.get("checked_at", 0)
                if type(checked_at) in (int, float) and 0 <= now - checked_at < CHECK_INTERVAL_SECONDS:
                    return {**previous, "cached": True}
            if updater_factory is None:
                from app.runtime_update import RuntimeUpdater
                updater_factory = RuntimeUpdater
            try:
                target = updater_factory(root).check()
                value = {"status": "available" if target else "up_to_date", "checked_at": now,
                         "available_version": target.get("version") if target else None,
                         "automatic_install": False}
            except Exception as error:
                # Do not persist response bodies, credentials, URLs with query secrets,
                # or disturb the running task on an offline check.
                value = {"status": "check_failed", "checked_at": now,
                         "error_type": type(error).__name__, "automatic_install": False}
            _write(root, "last-check.json", value)
            return value
    except RuntimeBusyError:
        return {"status": "check_in_progress", "automatic_install": False}


def schedule_check(root):
    """Called once by a launcher, never between action batches. No stdout."""
    root = Path(root).resolve()
    if not (root / ".component-install.json").is_file():
        return
    try:
        if not settings(root)["automatic_checks"]:
            return
        previous = _read(root, "last-check.json", {})
        checked_at = previous.get("checked_at", 0)
        if type(checked_at) in (int, float) and 0 <= time.time() - checked_at < CHECK_INTERVAL_SECONDS:
            return
        # The update origin never receives Runtime provider/MCP credentials.
        subprocess.Popen([sys.executable, "-I", "-B", str(root / "scripts/update_runtime.py"),
                          "--root", str(root), "check", "--scheduled"], cwd=root.parent,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=minimal_environment(), close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, ValueError):
        # Check availability cannot become a prerequisite for task execution.
        return
