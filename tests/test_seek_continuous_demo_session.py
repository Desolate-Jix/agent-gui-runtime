from __future__ import annotations

import hashlib
from pathlib import Path

from app.agent.continuous_task_session import create_continuous_task_session
from app.agent.seek_continuous_demo import (
    build_step_evidence,
    load_seek_checkpoint,
    load_seek_session,
    quick_apply_interface_id,
    resolve_active_memory_sha256,
    save_seek_checkpoint,
    save_seek_session,
)


class _MemoryStore:
    def __init__(self, active: dict[str, str]) -> None:
        self.active = active
        self.loaded: list[str] = []

    def registry(self) -> dict:
        return {"active_by_interface": dict(self.active)}

    def load_active(self, interface_id: str) -> dict:
        self.loaded.append(interface_id)
        return {"interface_id": interface_id}


def test_step_evidence_uses_current_image_checksum_and_trace(tmp_path: Path) -> None:
    image = tmp_path / "current.png"
    image.write_bytes(b"current screenshot")
    trace = tmp_path / "trace.json"
    trace.write_text("{}", encoding="utf-8")

    evidence = build_step_evidence(
        {
            "after_image": str(image),
            "trace_paths": [str(trace)],
            "report_path": str(tmp_path / "step_report.json"),
        },
        run_dir=tmp_path,
    )

    assert evidence == {
        "capture_id": str(image.resolve()),
        "screenshot_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "trace_path": str(trace.resolve()),
    }


def test_step_evidence_rejects_payload_without_current_screenshot(tmp_path: Path) -> None:
    try:
        build_step_evidence({"status": "ok"}, run_dir=tmp_path)
    except ValueError as exc:
        assert "current screenshot evidence" in str(exc)
    else:
        raise AssertionError("missing current screenshot must be rejected")


def test_active_memory_resolution_validates_registry_object() -> None:
    store = _MemoryStore({"seek_quick_apply_answer_questions": "memory-sha"})

    assert resolve_active_memory_sha256(store, "seek_quick_apply_answer_questions") == "memory-sha"
    assert store.loaded == ["seek_quick_apply_answer_questions"]
    assert resolve_active_memory_sha256(store, "seek_quick_apply_review") is None


def test_quick_apply_interface_identity_is_stable() -> None:
    assert (
        quick_apply_interface_id(
            {
                "current_step": "Answer Employer Questions",
                "state_type": "risky_application_questions",
            }
        )
        == "seek_quick_apply_answer_employer_questions"
    )
    assert quick_apply_interface_id({"state_type": "final_submit_visible"}) == "seek_quick_apply_final_submit_visible"


def test_session_and_checkpoint_round_trip(tmp_path: Path) -> None:
    session = create_continuous_task_session(
        session_id="seek-run-1",
        workflow_id="seek-quick-apply-demo",
    )
    session_path = save_seek_session(tmp_path, session)
    checkpoint_path = save_seek_checkpoint(
        tmp_path,
        {
            "phase": "quick_apply",
            "application_started": True,
            "last_flow_state": {"current_step": "answer_employer_questions"},
        },
    )

    assert session_path == tmp_path / "continuous_task_session.json"
    assert checkpoint_path == tmp_path / "seek_continuous_checkpoint.json"
    assert load_seek_session(tmp_path)["session_id"] == "seek-run-1"
    assert load_seek_checkpoint(tmp_path)["phase"] == "quick_apply"
