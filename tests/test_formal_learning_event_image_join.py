from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from app.agent.action_learning_capture_archive import (
    ActionLearningCaptureArchive,
    ActionLearningCaptureArchiveError,
    ActionLearningSessionEvidence,
)
from app.agent.action_learning_recorder import ActionLearningRecorder
from tests.test_formal_action_learning_recorder import (
    _UnknownBackend,
    _controller,
    _event,
)
from tests.test_formal_learning_capture_archive import _png
from tests.test_live_controller_w4 import _current_observation, _intent


def _actual_recorded_event(
    root: Path,
    *,
    same_png: bool = False,
    unknown: bool = False,
):
    recorder = ActionLearningRecorder(project_root=root)
    backend = _UnknownBackend() if unknown else None
    controller, source, actual_backend, claims, receipts = _controller(
        root, recorder, backend=backend,
    )
    before_png = _png(1440, 900, color=(11, 22, 33))
    after_png = before_png if same_png else _png(800, 600, color=(44, 55, 66))
    before = _current_observation(source.asset)
    before["screenshot_sha256"] = sha256(before_png).hexdigest()
    before["viewport_size"] = {"width": 1440, "height": 900}
    after = _current_observation(
        source.asset,
        capture_id="capture-post",
        anchors=("anchor_detail", "quick_apply"),
    )
    after["screenshot_sha256"] = sha256(after_png).hexdigest()
    after["viewport_size"] = {
        "width": 1440 if same_png else 800,
        "height": 900 if same_png else 600,
    }
    source.current = before
    source.post_current = after
    source.post_current_sequence = [after]
    runtime = controller.start_session()
    started = recorder.start_learning_session(
        learning_session_id="learning.join",
        runtime_session_id=runtime.session_id,
    )
    receipt = controller.submit_intent(_intent(runtime))
    session = recorder.get_learning_session(learning_session_id="learning.join")
    event = _event(session)
    return {
        "recorder": recorder,
        "archive": ActionLearningCaptureArchive(recorder=recorder),
        "runtime": runtime,
        "session": session,
        "event": event,
        "receipt": receipt,
        "before_png": before_png,
        "after_png": after_png,
        "backend": actual_backend,
        "claims": claims,
        "receipts": receipts,
        "started": started,
    }


def _pin_before(
    state: dict,
    *,
    asset_sha: str | None = None,
    window_handle: int | None = None,
    process_id: int | None = None,
) -> dict:
    event = state["event"]
    capture = event["before"]["capture"]
    geometry = event["before"]["geometry"]
    return state["archive"].pin_current_capture(
        runtime_session_id=event["runtime"]["session_id"],
        capture_id=capture["capture_id"],
        screenshot_sha256=capture["screenshot_sha256"],
        viewport_size=geometry["viewport_size"],
        asset_content_sha256=(
            asset_sha or event["before"]["workflow"]["asset_content_sha256"]
        ),
        target_window_handle=(
            window_handle or geometry["target_window_handle"]
        ),
        target_process_id=process_id or geometry["target_process_id"],
        png_bytes=state["before_png"],
    )


def _pin_after(state: dict) -> dict | None:
    event = state["event"]
    after = event["terminal"]["next_observation_ref"]
    if after is None:
        return None
    geometry = event["before"]["geometry"]
    width, height = (
        (1440, 900)
        if state["after_png"] == state["before_png"]
        else (800, 600)
    )
    return state["archive"].pin_current_capture(
        runtime_session_id=event["runtime"]["session_id"],
        capture_id=after["capture_id"],
        screenshot_sha256=after["screenshot_sha256"],
        viewport_size={"width": width, "height": height},
        asset_content_sha256=event["before"]["workflow"]["asset_content_sha256"],
        target_window_handle=geometry["target_window_handle"],
        target_process_id=geometry["target_process_id"],
        png_bytes=state["after_png"],
    )


def _read(state: dict) -> ActionLearningSessionEvidence:
    return state["archive"].read_session_evidence(
        learning_session_id="learning.join",
        runtime_session_id=state["runtime"].session_id,
        expected_revision=state["session"]["revision"],
    )


def test_actual_authoritative_event_joins_distinct_exact_before_and_after_png(
    tmp_path: Path,
) -> None:
    state = _actual_recorded_event(tmp_path)
    before_metadata = _pin_before(state)
    after_metadata = _pin_after(state)
    assert after_metadata is not None

    restarted = ActionLearningCaptureArchive(
        recorder=ActionLearningRecorder(project_root=tmp_path),
    )
    state["archive"] = restarted
    packet = _read(state)

    evidence = packet.evidence()
    assert evidence["contract_version"] == "action_learning_session_evidence_v1"
    assert evidence["learning_session_id"] == "learning.join"
    assert evidence["runtime_session_id"] == state["runtime"].session_id
    assert evidence["revision"] == state["session"]["revision"]
    assert evidence["recording_status"] == "active"
    assert evidence["events"] == state["session"]["events"]
    assert evidence["recording_gaps"] == []
    assert evidence["source_status"] == "complete"
    assert evidence["artifact_is_authorization"] is False
    assert evidence["execute_binding_enabled"] is False
    assert evidence["action_executed"] is False
    source = evidence["event_sources"][0]
    assert source["event_id"] == state["event"]["event_id"]
    assert source["before"] == {
        "status": "available",
        "capture_id": before_metadata["capture_id"],
        "screenshot_sha256": before_metadata["screenshot_sha256"],
        "metadata": before_metadata,
    }
    assert source["after_observation_present"] is True
    assert source["after"] == {
        "status": "available",
        "capture_id": after_metadata["capture_id"],
        "screenshot_sha256": after_metadata["screenshot_sha256"],
        "metadata": after_metadata,
    }
    assert dict(packet.png_by_sha256) == {
        sha256(state["before_png"]).hexdigest(): state["before_png"],
        sha256(state["after_png"]).hexdigest(): state["after_png"],
    }
    with pytest.raises(FrozenInstanceError):
        packet.evidence_json = b"changed"
    evidence["events"].clear()
    assert packet.evidence()["events"] == state["session"]["events"]


def test_same_png_digest_is_deduplicated_without_collapsing_before_after_refs(
    tmp_path: Path,
) -> None:
    state = _actual_recorded_event(tmp_path, same_png=True)
    _pin_before(state)
    _pin_after(state)

    packet = _read(state)
    source = packet.evidence()["event_sources"][0]

    assert len(packet.png_by_sha256) == 1
    assert source["before"]["capture_id"] != source["after"]["capture_id"]
    assert (
        source["before"]["screenshot_sha256"]
        == source["after"]["screenshot_sha256"]
        == packet.png_by_sha256[0][0]
    )


@pytest.mark.parametrize("mismatch", ["asset", "window", "process"])
def test_before_metadata_scope_mismatch_is_explicitly_incomplete(
    tmp_path: Path,
    mismatch: str,
) -> None:
    state = _actual_recorded_event(tmp_path)
    _pin_before(
        state,
        asset_sha="b" * 64 if mismatch == "asset" else None,
        window_handle=9999 if mismatch == "window" else None,
        process_id=9999 if mismatch == "process" else None,
    )
    _pin_after(state)

    packet = _read(state)
    evidence = packet.evidence()

    assert evidence["source_status"] == "incomplete"
    assert evidence["event_sources"][0]["before"] == {
        "status": "unavailable",
        "reason": "archive_source_unavailable",
        "capture_id": state["event"]["before"]["capture"]["capture_id"],
        "screenshot_sha256": state["event"]["before"]["capture"]["screenshot_sha256"],
    }
    assert state["event"]["before"]["capture"]["screenshot_sha256"] not in dict(
        packet.png_by_sha256
    )


def test_missing_archive_returns_incomplete_without_creating_layout_or_lock(
    tmp_path: Path,
) -> None:
    state = _actual_recorded_event(tmp_path)
    assert not state["archive"].root.exists()

    packet = _read(state)

    assert packet.evidence()["source_status"] == "incomplete"
    assert all(
        item["status"] == "unavailable"
        for source in packet.evidence()["event_sources"]
        for item in (source["before"], source["after"])
        if item is not None
    )
    assert packet.png_by_sha256 == ()
    assert not state["archive"].root.exists()
    assert not state["archive"].lock_path.exists()


def test_unknown_terminal_without_checkpoint_keeps_event_but_not_before_png(
    tmp_path: Path,
) -> None:
    state = _actual_recorded_event(tmp_path, unknown=True)
    _pin_before(state)
    assert state["event"]["terminal"]["next_observation_ref"] is None

    packet = _read(state)
    evidence = packet.evidence()
    source = evidence["event_sources"][0]

    assert evidence["source_status"] == "incomplete"
    assert source["before"] == {
        "status": "unavailable",
        "reason": "before_source_unverified",
        "capture_id": state["event"]["before"]["capture"]["capture_id"],
        "screenshot_sha256": state["event"]["before"]["capture"][
            "screenshot_sha256"
        ],
    }
    assert source["after_observation_present"] is False
    assert source["after"] is None
    assert packet.png_by_sha256 == ()
    assert evidence["events"][state["event"]["event_id"]]["terminal"] == (
        state["event"]["terminal"]
    )
    assert evidence["events"][state["event"]["event_id"]]["terminal"][
        "effect_status"
    ] == "indeterminate"


def test_empty_session_is_empty_and_nonallocating(tmp_path: Path) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    session = recorder.start_learning_session(
        learning_session_id="learning.empty", runtime_session_id="runtime.empty",
    )
    archive = ActionLearningCaptureArchive(recorder=recorder)

    packet = archive.read_session_evidence(
        learning_session_id="learning.empty",
        runtime_session_id="runtime.empty",
        expected_revision=session["revision"],
    )

    assert packet.evidence()["source_status"] == "empty"
    assert packet.evidence()["events"] == {}
    assert packet.png_by_sha256 == ()
    assert not archive.root.exists()


@pytest.mark.parametrize("failure", ["learning", "runtime", "revision", "bool_revision"])
def test_wrong_scope_or_revision_fails_without_archive_writes(
    tmp_path: Path,
    failure: str,
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    session = recorder.start_learning_session(
        learning_session_id="learning.scope", runtime_session_id="runtime.scope",
    )
    archive = ActionLearningCaptureArchive(recorder=recorder)
    kwargs = {
        "learning_session_id": (
            "learning.other" if failure == "learning" else "learning.scope"
        ),
        "runtime_session_id": (
            "runtime.other" if failure == "runtime" else "runtime.scope"
        ),
        "expected_revision": (
            True
            if failure == "bool_revision"
            else session["revision"] + 1
            if failure == "revision"
            else session["revision"]
        ),
    }

    with pytest.raises(ActionLearningCaptureArchiveError):
        archive.read_session_evidence(**kwargs)
    assert not archive.root.exists()


def test_pending_recording_gap_is_incomplete_without_fabricated_image_gap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, backend, _, _ = _controller(tmp_path, recorder)
    runtime = controller.start_session()
    recorder.start_learning_session(
        learning_session_id="learning.gap", runtime_session_id=runtime.session_id,
    )
    original_write = recorder._write_ledger
    writes = 0

    def fail_terminal(ledger):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("synthetic terminal recording failure")
        return original_write(ledger)

    monkeypatch.setattr(recorder, "_write_ledger", fail_terminal)
    controller.submit_intent(_intent(runtime))
    session = recorder.get_learning_session(learning_session_id="learning.gap")
    archive = ActionLearningCaptureArchive(recorder=recorder)

    packet = archive.read_session_evidence(
        learning_session_id="learning.gap",
        runtime_session_id=runtime.session_id,
        expected_revision=session["revision"],
    )

    assert backend.attempt_count == 1
    assert packet.evidence()["source_status"] == "incomplete"
    assert packet.evidence()["recording_gaps"] == session["recording_gaps"]
    assert packet.evidence()["event_sources"] == []
    assert packet.png_by_sha256 == ()
    assert not archive.root.exists()


def test_final_recorder_snapshot_change_requires_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _actual_recorded_event(tmp_path)
    _pin_before(state)
    _pin_after(state)
    original_read = state["archive"]._read_join_capture
    changed = False

    def read_then_finish(**kwargs):
        nonlocal changed
        value = original_read(**kwargs)
        if not changed:
            changed = True
            state["recorder"].finish_learning_session(
                learning_session_id="learning.join",
                runtime_session_id=state["runtime"].session_id,
            )
        return value

    monkeypatch.setattr(state["archive"], "_read_join_capture", read_then_finish)

    with pytest.raises(ActionLearningCaptureArchiveError, match="retry"):
        _read(state)


def test_existing_archive_layout_without_lock_is_not_completed_by_read(
    tmp_path: Path,
) -> None:
    state = _actual_recorded_event(tmp_path)
    state["archive"].blobs_root.mkdir(parents=True)
    state["archive"].records_root.mkdir(parents=True)
    assert not state["archive"].lock_path.exists()

    packet = _read(state)

    assert packet.evidence()["source_status"] == "incomplete"
    assert not state["archive"].lock_path.exists()
