from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from app.agent.seek_continuous_demo import (
    CHECKPOINT_FILENAME,
    LATEST_HANDOFF_POINTER_FILENAME,
    SESSION_FILENAME,
    load_seek_checkpoint,
    load_seek_session,
)


HANDOFF_CONTRACT = "continuous_task_learning_handoff_v1"
LAUNCH_FILENAME = "continuous_resume_launch.json"


class ReviewedMemoryStore(Protocol):
    def registry(self) -> dict[str, Any]: ...

    def load_active(self, interface_id: str) -> dict[str, Any]: ...


def load_continuous_task_handoff(
    *,
    project_root: str | Path,
    run_dir: str | Path | None,
    memory_store: ReviewedMemoryStore,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    resolved_run_dir = _resolve_run_dir(root, run_dir)
    session = load_seek_session(resolved_run_dir)
    checkpoint = load_seek_checkpoint(resolved_run_dir)
    pending = session.get("pending_learning") if isinstance(session.get("pending_learning"), dict) else {}
    interface_id = str(pending.get("interface_id") or session.get("current_interface_id") or "").strip()
    evidence = _latest_interface_evidence(session, interface_id)
    screenshot_path = _resolve_project_file(root, evidence.get("capture_id"))
    expected_sha256 = str(evidence.get("screenshot_sha256") or "").strip().lower()
    actual_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    screenshot_valid = bool(expected_sha256 and expected_sha256 == actual_sha256)

    active_memory_sha256 = None
    if interface_id:
        registry = memory_store.registry()
        active = registry.get("active_by_interface") if isinstance(registry.get("active_by_interface"), dict) else {}
        active_memory_sha256 = str(active.get(interface_id) or "").strip() or None
        if active_memory_sha256:
            memory_store.load_active(interface_id)

    resume_blocker = _resume_blocker(
        session=session,
        checkpoint=checkpoint,
        interface_id=interface_id,
        screenshot_valid=screenshot_valid,
        active_memory_sha256=active_memory_sha256,
    )
    resume_action = _resume_action(session=session, checkpoint=checkpoint)
    return {
        "contract_version": HANDOFF_CONTRACT,
        "run_dir": _relative_path(root, resolved_run_dir),
        "run_dir_absolute": str(resolved_run_dir),
        "status": str(session.get("status") or "unknown"),
        "workflow_id": str(session.get("workflow_id") or ""),
        "checkpoint_phase": str(checkpoint.get("phase") or ""),
        "pending_interface_id": interface_id,
        "pending_surface_type": str(pending.get("surface_type") or session.get("current_surface_type") or ""),
        "required_result": str(pending.get("required_result") or ""),
        "screenshot_path": _relative_path(root, screenshot_path),
        "screenshot_sha256": actual_sha256,
        "screenshot_valid": screenshot_valid,
        "trace_path": str(evidence.get("trace_path") or ""),
        "active_memory_object_sha256": active_memory_sha256,
        "resume_ready": resume_blocker is None,
        "resume_action": resume_action,
        "resume_blocker": resume_blocker,
        "no_submit": True,
        "live_submit_authorized": False,
        "live_safe_fill_authorized": False,
    }


def start_continuous_task_resume(
    *,
    project_root: str | Path,
    run_dir: str | Path,
    memory_store: ReviewedMemoryStore,
    base_url: str,
    popen: Callable[..., Any] = subprocess.Popen,
    python_executable: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    handoff = load_continuous_task_handoff(
        project_root=root,
        run_dir=run_dir,
        memory_store=memory_store,
    )
    if handoff["resume_ready"] is not True:
        raise ValueError(f"continuous task resume is blocked: {handoff['resume_blocker']}")
    resolved_run_dir = Path(str(handoff["run_dir_absolute"])).resolve()
    runtime_base_url = _validated_runtime_base_url(base_url)
    checkpoint = load_seek_checkpoint(resolved_run_dir)
    command = [
        str(python_executable or sys.executable),
        str(root / "scripts" / "seek_speed_demo_runner.py"),
        "--run-dir",
        str(resolved_run_dir),
        "--base-url",
        runtime_base_url,
        "--continuous-session",
        "--resume-continuous-session",
        "--approve-quick-apply-entry",
        "--max-safe-fields-to-fill",
        "0",
        "--max-application-steps",
        "1",
    ]
    job_attempt = checkpoint.get("job_attempt") if isinstance(checkpoint.get("job_attempt"), dict) else {}
    if str(job_attempt.get("match_decision") or "").strip() == "maybe_apply":
        command.append("--allow-maybe-apply")
    log_path = resolved_run_dir / "continuous_resume.log"
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        process = popen(
            command,
            cwd=str(root),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    launch = {
        "contract_version": "continuous_task_resume_launch_v1",
        "status": "resume_started",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "pid": int(process.pid),
        "run_dir": handoff["run_dir"],
        "pending_interface_id": handoff["pending_interface_id"],
        "active_memory_object_sha256": handoff["active_memory_object_sha256"],
        "resume_action": handoff["resume_action"],
        "command": command,
        "log_path": _relative_path(root, log_path),
        "no_submit": True,
        "live_submit_authorized": False,
        "live_safe_fill_authorized": False,
    }
    (resolved_run_dir / LAUNCH_FILENAME).write_text(
        json.dumps(launch, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return launch


def _resolve_run_dir(project_root: Path, run_dir: str | Path | None) -> Path:
    if run_dir is None or not str(run_dir).strip():
        pointer_path = project_root / "logs" / LATEST_HANDOFF_POINTER_FILENAME
        run_path = _run_dir_from_pointer(project_root, pointer_path)
        if run_path is None:
            candidates = [
                path.parent
                for path in (project_root / "logs").rglob(SESSION_FILENAME)
                if path.is_file()
            ]
            if not candidates:
                raise ValueError("no continuous task session found")
            run_path = max(candidates, key=lambda path: (path / SESSION_FILENAME).stat().st_mtime)
    else:
        candidate = Path(run_dir)
        run_path = candidate if candidate.is_absolute() else project_root / candidate
    resolved = run_path.resolve()
    if resolved != project_root and project_root not in resolved.parents:
        raise ValueError("continuous task run directory must stay inside project root")
    if not (resolved / SESSION_FILENAME).is_file():
        raise ValueError(f"continuous task session not found: {resolved / SESSION_FILENAME}")
    if not (resolved / CHECKPOINT_FILENAME).is_file():
        raise ValueError(f"continuous task checkpoint not found: {resolved / CHECKPOINT_FILENAME}")
    return resolved


def _run_dir_from_pointer(project_root: Path, pointer_path: Path) -> Path | None:
    if not pointer_path.is_file():
        return None
    try:
        payload = json.loads(pointer_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    candidate = Path(str(payload.get("run_dir") or "").strip())
    if not candidate:
        return None
    resolved = candidate.resolve()
    if project_root not in resolved.parents:
        return None
    if not (resolved / SESSION_FILENAME).is_file() or not (resolved / CHECKPOINT_FILENAME).is_file():
        return None
    return resolved


def _latest_interface_evidence(session: dict[str, Any], interface_id: str) -> dict[str, Any]:
    events = session.get("events") if isinstance(session.get("events"), list) else []
    for event in reversed(events):
        if not isinstance(event, dict) or event.get("event_type") != "interface_observed":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if interface_id and details.get("interface_id") != interface_id:
            continue
        evidence = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
        if evidence:
            return evidence
    raise ValueError("continuous task session is missing pending interface evidence")


def _resolve_project_file(project_root: Path, value: Any) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError("continuous task screenshot evidence is missing")
    candidate = Path(text)
    path = (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    if project_root not in path.parents:
        raise ValueError("continuous task screenshot must stay inside project root")
    if not path.is_file():
        raise ValueError(f"continuous task screenshot not found: {path}")
    return path


def _resume_blocker(
    *,
    session: dict[str, Any],
    checkpoint: dict[str, Any],
    interface_id: str,
    screenshot_valid: bool,
    active_memory_sha256: str | None,
) -> str | None:
    if (
        session.get("status") == "awaiting_apply_entry_confirmation"
        and checkpoint.get("phase") == "awaiting_apply_confirmation"
    ):
        if not interface_id:
            return "current_interface_id_missing"
        if not screenshot_valid:
            return "current_screenshot_evidence_invalid"
        pending_confirmation = session.get("pending_apply_confirmation")
        if not isinstance(pending_confirmation, dict) or not pending_confirmation.get("job_id"):
            return "pending_apply_confirmation_missing"
        return None
    if session.get("status") != "paused_for_learning":
        return "session_not_paused_for_learning"
    if checkpoint.get("phase") != "quick_apply":
        return "checkpoint_not_quick_apply"
    if not interface_id:
        return "pending_interface_id_missing"
    if not screenshot_valid:
        return "pending_screenshot_evidence_invalid"
    if not active_memory_sha256:
        return "matching_reviewed_memory_not_published"
    return None


def _resume_action(*, session: dict[str, Any], checkpoint: dict[str, Any]) -> str:
    if (
        session.get("status") == "awaiting_apply_entry_confirmation"
        and checkpoint.get("phase") == "awaiting_apply_confirmation"
    ):
        return "confirm_apply_entry"
    if session.get("status") == "paused_for_learning" and checkpoint.get("phase") == "quick_apply":
        return "resume_after_learning"
    return "resume_continuous_task"


def _validated_runtime_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("continuous task runtime base_url must be a local HTTP endpoint")
    if not parsed.port:
        raise ValueError("continuous task runtime base_url must include an explicit port")
    return value


def _relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root).as_posix()
