from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Protocol

from app.agent.continuous_task_session import SESSION_CONTRACT


SESSION_FILENAME = "continuous_task_session.json"
CHECKPOINT_FILENAME = "seek_continuous_checkpoint.json"
CHECKPOINT_CONTRACT = "seek_continuous_demo_checkpoint_v1"
LATEST_HANDOFF_POINTER_FILENAME = "continuous_task_latest.json"


class ReviewedMemoryStore(Protocol):
    def registry(self) -> dict[str, Any]: ...

    def load_active(self, interface_id: str) -> dict[str, Any]: ...


def build_step_evidence(payload: dict[str, Any], *, run_dir: str | Path) -> dict[str, str]:
    run_path = Path(run_dir).resolve()
    image_path = _first_existing_path(
        payload.get("after_image"),
        payload.get("observe_image"),
        payload.get("before_image"),
    )
    if image_path is None:
        raise ValueError("continuous SEEK step is missing current screenshot evidence")

    trace_candidates = payload.get("trace_paths") if isinstance(payload.get("trace_paths"), list) else []
    trace_path = _first_existing_path(
        *trace_candidates,
        payload.get("observe_trace"),
        payload.get("report_path"),
    )
    if trace_path is None:
        fallback = run_path / "continuous_task_session.json"
        trace_path = fallback.resolve()

    return {
        "capture_id": str(image_path),
        "screenshot_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "trace_path": str(trace_path),
    }


def resolve_active_memory_sha256(store: ReviewedMemoryStore, interface_id: str) -> str | None:
    registry = store.registry()
    active = registry.get("active_by_interface") if isinstance(registry.get("active_by_interface"), dict) else {}
    object_sha256 = str(active.get(interface_id) or "").strip()
    if not object_sha256:
        return None
    store.load_active(interface_id)
    return object_sha256


def quick_apply_interface_id(flow_state: dict[str, Any] | None) -> str:
    payload = flow_state if isinstance(flow_state, dict) else {}
    identity = str(payload.get("current_step") or payload.get("state_type") or "unknown").strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", identity).strip("_")
    return f"seek_quick_apply_{slug or 'unknown'}"


def save_seek_session(run_dir: str | Path, session: dict[str, Any]) -> Path:
    if session.get("contract_version") != SESSION_CONTRACT:
        raise ValueError("invalid continuous task session")
    path = Path(run_dir) / SESSION_FILENAME
    _write_json(path, session)
    _write_latest_handoff_pointer(path.parent)
    return path


def _write_latest_handoff_pointer(run_dir: Path) -> None:
    resolved_run_dir = run_dir.resolve()
    logs_root = next(
        (candidate for candidate in (resolved_run_dir, *resolved_run_dir.parents) if candidate.name.casefold() == "logs"),
        None,
    )
    if logs_root is None:
        return
    _write_json(
        logs_root / LATEST_HANDOFF_POINTER_FILENAME,
        {
            "contract_version": "continuous_task_latest_pointer_v1",
            "run_dir": str(resolved_run_dir),
        },
    )


def load_seek_session(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir) / SESSION_FILENAME
    payload = _read_json(path)
    if payload.get("contract_version") != SESSION_CONTRACT:
        raise ValueError("invalid continuous task session contract")
    return payload


def save_seek_checkpoint(run_dir: str | Path, checkpoint: dict[str, Any]) -> Path:
    payload = {
        "contract_version": CHECKPOINT_CONTRACT,
        **checkpoint,
    }
    path = Path(run_dir) / CHECKPOINT_FILENAME
    _write_json(path, payload)
    return path


def load_seek_checkpoint(run_dir: str | Path) -> dict[str, Any]:
    path = Path(run_dir) / CHECKPOINT_FILENAME
    payload = _read_json(path)
    if payload.get("contract_version") != CHECKPOINT_CONTRACT:
        raise ValueError("invalid continuous SEEK checkpoint contract")
    return payload


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        path = Path(text).resolve()
        if path.is_file():
            return path
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload
