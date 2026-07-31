from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from app.agent.continuous_task_handoff import (
    load_continuous_task_handoff,
    start_continuous_task_resume,
)
from app.agent.continuous_task_session import (
    create_continuous_task_session,
    observe_interface,
    request_apply_entry_confirmation,
)
from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
from app.agent.seek_continuous_demo import save_seek_checkpoint, save_seek_session
from tests.test_reviewed_interface_memory import _write_reviewed_candidate


class _MemoryStore:
    def __init__(self, active: dict[str, str] | None = None) -> None:
        self.active = dict(active or {})

    def registry(self) -> dict[str, object]:
        return {
            "registry_revision": len(self.active),
            "active_by_interface": dict(self.active),
        }

    def load_active(self, interface_id: str) -> dict[str, str]:
        object_sha256 = self.active.get(interface_id)
        if not object_sha256:
            raise ValueError(f"active reviewed interface memory not found: {interface_id}")
        return {
            "contract_version": "reviewed_interface_memory_v1",
            "interface_id": interface_id,
            "object_sha256": object_sha256,
        }


def _write_paused_run(project_root: Path, *, interface_id: str = "seek_quick_apply_contact_details") -> Path:
    run_dir = project_root / "logs" / "seek-demo" / "run-1"
    screenshot = project_root / "artifacts" / "screenshots" / "quick-apply.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), "white").save(screenshot)
    session = create_continuous_task_session(
        session_id="run-1",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id=interface_id,
        surface_type="seek_quick_apply",
        memory_object_sha256=None,
        evidence={
            "capture_id": str(screenshot),
            "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            "trace_path": str(run_dir / "quick-apply-observe.json"),
        },
    )
    save_seek_session(run_dir, session)
    save_seek_checkpoint(
        run_dir,
        {
            "phase": "quick_apply",
            "application_started": True,
            "last_flow_state": {"current_step": "Contact details"},
        },
    )
    return run_dir


def _write_confirmation_run(project_root: Path) -> Path:
    run_dir = project_root / "logs" / "seek-demo" / "confirmation-run"
    screenshot = project_root / "artifacts" / "screenshots" / "job-detail.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), "white").save(screenshot)
    session = create_continuous_task_session(
        session_id="confirmation-run",
        workflow_id="seek-quick-apply-demo",
    )
    session = observe_interface(
        session,
        interface_id="seek_job_detail_runtime_profile",
        surface_type="seek_job_detail",
        memory_object_sha256=None,
        learning_required=False,
        knowledge_source="seek_runtime_profile",
        evidence={
            "capture_id": str(screenshot),
            "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            "trace_path": str(run_dir / "job-detail-observe.json"),
        },
    )
    session = request_apply_entry_confirmation(
        session,
        job_id="seek-job-1",
        job_title="Data Analyst",
    )
    save_seek_session(run_dir, session)
    save_seek_checkpoint(
        run_dir,
        {
            "phase": "awaiting_apply_confirmation",
            "application_started": False,
            "job_attempt": {
                "match_decision": "maybe_apply",
                "job_title": "Data Analyst",
            },
        },
    )
    return run_dir


def test_handoff_exposes_pending_interface_and_current_screenshot(tmp_path: Path) -> None:
    run_dir = _write_paused_run(tmp_path)

    result = load_continuous_task_handoff(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=_MemoryStore(),
    )

    assert result["status"] == "paused_for_learning"
    assert result["pending_interface_id"] == "seek_quick_apply_contact_details"
    assert result["screenshot_path"].endswith("artifacts/screenshots/quick-apply.png")
    assert result["screenshot_valid"] is True
    assert result["resume_ready"] is False
    assert result["resume_blocker"] == "matching_reviewed_memory_not_published"
    assert result["no_submit"] is True


def test_handoff_discovers_latest_task_from_runtime_pointer(tmp_path: Path) -> None:
    run_dir = _write_paused_run(tmp_path)

    result = load_continuous_task_handoff(
        project_root=tmp_path,
        run_dir=None,
        memory_store=_MemoryStore(),
    )

    assert result["run_dir_absolute"] == str(run_dir.resolve())
    pointer = json.loads(
        (tmp_path / "logs" / "continuous_task_latest.json").read_text(encoding="utf-8")
    )
    assert Path(pointer["run_dir"]) == run_dir.resolve()


def test_apply_entry_confirmation_is_a_ready_explicit_handoff_action(tmp_path: Path) -> None:
    run_dir = _write_confirmation_run(tmp_path)

    result = load_continuous_task_handoff(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=_MemoryStore(),
    )

    assert result["status"] == "awaiting_apply_entry_confirmation"
    assert result["checkpoint_phase"] == "awaiting_apply_confirmation"
    assert result["resume_ready"] is True
    assert result["resume_action"] == "confirm_apply_entry"
    assert result["resume_blocker"] is None
    assert result["live_safe_fill_authorized"] is False


def test_matching_reviewed_memory_unlocks_same_run_resume(tmp_path: Path) -> None:
    run_dir = _write_paused_run(tmp_path)
    store = _MemoryStore({"seek_quick_apply_contact_details": "memory-sha-1"})

    result = load_continuous_task_handoff(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=store,
    )

    assert result["resume_ready"] is True
    assert result["active_memory_object_sha256"] == "memory-sha-1"
    assert result["resume_blocker"] is None


def test_pause_publish_and_resume_uses_the_same_continuous_task(tmp_path: Path) -> None:
    interface_id = "seek_quick_apply_contact_details"
    run_dir = _write_paused_run(tmp_path, interface_id=interface_id)
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    before = load_continuous_task_handoff(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=store,
    )
    assert before["resume_ready"] is False

    candidate_path = _write_reviewed_candidate(tmp_path)
    published = store.publish(
        source_path=candidate_path,
        interface_id=interface_id,
        expected_registry_revision=0,
    )
    calls: list[list[str]] = []

    class _Process:
        pid = 9876

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        return _Process()

    resumed = start_continuous_task_resume(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=store,
        base_url="http://127.0.0.1:8765",
        popen=fake_popen,
        python_executable="python-test",
    )

    assert published["interface_id"] == interface_id
    assert resumed["run_dir"] == "logs/seek-demo/run-1"
    assert resumed["active_memory_object_sha256"] == published["object_sha256"]
    assert calls[0][calls[0].index("--run-dir") + 1] == str(run_dir)
    assert "--resume-continuous-session" in calls[0]
    assert calls[0][calls[0].index("--base-url") + 1] == "http://127.0.0.1:8765"
    assert calls[0][calls[0].index("--max-safe-fields-to-fill") + 1] == "0"
    assert all("submit" not in part.casefold() for part in calls[0])


def test_handoff_rejects_run_directory_outside_project(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-seek-run"
    outside.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="inside project root"):
        load_continuous_task_handoff(
            project_root=tmp_path,
            run_dir=outside,
            memory_store=_MemoryStore(),
        )


def test_resume_launcher_uses_same_run_dir_and_never_adds_submit_flags(tmp_path: Path) -> None:
    run_dir = _write_paused_run(tmp_path)
    calls: list[dict[str, object]] = []

    class _Process:
        pid = 4321

    def fake_popen(command, **kwargs):
        calls.append({"command": list(command), **kwargs})
        return _Process()

    result = start_continuous_task_resume(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=_MemoryStore({"seek_quick_apply_contact_details": "memory-sha-1"}),
        base_url="http://127.0.0.1:8765",
        popen=fake_popen,
        python_executable="python-test",
    )

    command = calls[0]["command"]
    assert result["status"] == "resume_started"
    assert result["pid"] == 4321
    assert command[:2] == [
        "python-test",
        str(tmp_path / "scripts" / "seek_speed_demo_runner.py"),
    ]
    assert command[command.index("--run-dir") + 1] == str(run_dir)
    assert "--continuous-session" in command
    assert "--resume-continuous-session" in command
    assert "--approve-quick-apply-entry" in command
    assert command[command.index("--base-url") + 1] == "http://127.0.0.1:8765"
    assert command[command.index("--max-safe-fields-to-fill") + 1] == "0"
    assert command[command.index("--max-application-steps") + 1] == "1"
    assert all("submit" not in str(item).casefold() for item in command)
    launch = json.loads((run_dir / "continuous_resume_launch.json").read_text(encoding="utf-8"))
    assert launch["no_submit"] is True
    assert launch["live_submit_authorized"] is False


def test_confirmation_launcher_preserves_maybe_apply_and_disables_live_fill(tmp_path: Path) -> None:
    run_dir = _write_confirmation_run(tmp_path)
    calls: list[list[str]] = []

    class _Process:
        pid = 2468

    def fake_popen(command, **kwargs):
        calls.append(list(command))
        return _Process()

    result = start_continuous_task_resume(
        project_root=tmp_path,
        run_dir=run_dir,
        memory_store=_MemoryStore(),
        base_url="http://127.0.0.1:8765",
        popen=fake_popen,
        python_executable="python-test",
    )

    command = calls[0]
    assert result["resume_action"] == "confirm_apply_entry"
    assert "--approve-quick-apply-entry" in command
    assert "--allow-maybe-apply" in command
    assert command[command.index("--max-safe-fields-to-fill") + 1] == "0"
    assert command[command.index("--max-application-steps") + 1] == "1"


def test_panel_handoff_routes_load_and_start_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    import app.api.panel as panel_api

    calls: list[tuple[str, str]] = []

    def fake_load(**kwargs):
        calls.append(("load", str(kwargs.get("run_dir") or "")))
        return {
            "contract_version": "continuous_task_learning_handoff_v1",
            "run_dir": "logs/seek-demo/run-1",
            "status": "paused_for_learning",
            "resume_ready": True,
            "no_submit": True,
        }

    def fake_start(**kwargs):
        calls.append(("start", str(kwargs.get("run_dir") or "")))
        return {
            "contract_version": "continuous_task_resume_launch_v1",
            "status": "resume_started",
            "run_dir": "logs/seek-demo/run-1",
            "no_submit": True,
        }

    monkeypatch.setattr(panel_api, "load_continuous_task_handoff", fake_load, raising=False)
    monkeypatch.setattr(panel_api, "start_continuous_task_resume", fake_start, raising=False)
    client = TestClient(app)

    loaded = client.get(
        "/panel/continuous_task_handoff",
        params={"run_dir": "logs/seek-demo/run-1"},
    ).json()
    started = client.post(
        "/panel/resume_continuous_task",
        json={
            "run_dir": "logs/seek-demo/run-1",
            "base_url": "http://127.0.0.1:8765",
        },
    ).json()

    assert loaded["success"] is True
    assert loaded["data"]["resume_ready"] is True
    assert started["success"] is True
    assert started["data"]["status"] == "resume_started"
    assert calls == [
        ("load", "logs/seek-demo/run-1"),
        ("start", "logs/seek-demo/run-1"),
    ]
