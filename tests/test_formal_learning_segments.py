from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
from app.agent.action_learning_recorder import ActionLearningRecorder
from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_segments import (
    LEARNING_SEGMENT_CAPABILITY,
    LearningSegmentOwner,
)
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from tests.test_formal_action_learning_recorder import _UnknownBackend, _controller, _event
from tests.test_formal_learning_capture_archive import _png
from tests.test_live_controller_w4 import _current_observation, _intent


REVIEWER = "formal-segment-reviewer-token"
TASK = "formal-segment-task"


def _connection(service: AgentLinkService, name: str = "segment-agent") -> dict:
    return service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": TASK, "agent_name": name,
    })


def _owners(root: Path):
    store = AgentLinkStore(root / "agent-link.json")
    service = AgentLinkService(store, REVIEWER)
    recorder = ActionLearningRecorder(project_root=root)
    archive = ActionLearningCaptureArchive(recorder=recorder)
    owner = LearningSegmentOwner(store, recorder=recorder, capture_archive=archive)
    return store, service, recorder, archive, owner


def _start(owner: LearningSegmentOwner, connection: dict, *, key="segment-start"):
    return owner.start(
        connection_id=connection["connection_id"],
        task_id=TASK,
        idempotency_key=key,
        title="Fresh two-action segment",
    )


def _perform_action(
    root: Path,
    owner: LearningSegmentOwner,
    recorder: ActionLearningRecorder,
    archive: ActionLearningCaptureArchive,
    connection: dict,
    segment_id: str,
    *,
    sequence: int,
    unknown: bool = False,
    pin: bool = True,
):
    task_id = connection["task_id"]
    backend = _UnknownBackend() if unknown else None
    controller, source, actual_backend, _, _ = _controller(
        root, recorder, backend=backend,
    )
    before_png = _png(1440, 900, color=(10 + sequence, 20, 30))
    after_png = _png(800, 600, color=(40 + sequence, 50, 60))
    before = _current_observation(
        source.asset, capture_id=f"capture-before-{sequence}",
    )
    before["screenshot_sha256"] = sha256(before_png).hexdigest()
    before["viewport_size"] = {"width": 1440, "height": 900}
    after = _current_observation(
        source.asset,
        capture_id=f"capture-after-{sequence}",
        anchors=("anchor_detail", "quick_apply"),
    )
    after["screenshot_sha256"] = sha256(after_png).hexdigest()
    after["viewport_size"] = {"width": 800, "height": 600}
    source.current = before
    source.post_current = after
    source.post_current_sequence = [after]
    runtime = controller.start_session()
    owner.attach_runtime(
        connection_id=connection["connection_id"],
        task_id=task_id,
        segment_id=segment_id,
        runtime_session_id=runtime.session_id,
    )
    receipt = controller.submit_intent(_intent(runtime))
    child = next(
        item
        for item in owner.get(
                        connection_id=connection["connection_id"],
            task_id=task_id,
            segment_id=segment_id,
        )["children"]
        if item["runtime_session_id"] == runtime.session_id
    )
    session = recorder.get_learning_session(
        learning_session_id=child["learning_session_id"],
    )
    event = _event(session)
    if pin:
        geometry = event["before"]["geometry"]
        capture = event["before"]["capture"]
        archive.pin_current_capture(
            runtime_session_id=runtime.session_id,
            capture_id=capture["capture_id"],
            screenshot_sha256=capture["screenshot_sha256"],
            viewport_size=geometry["viewport_size"],
            asset_content_sha256=event["before"]["workflow"]["asset_content_sha256"],
            target_window_handle=geometry["target_window_handle"],
            target_process_id=geometry["target_process_id"],
            png_bytes=before_png,
        )
        after_ref = event["terminal"]["next_observation_ref"]
        if after_ref is not None:
            archive.pin_current_capture(
                runtime_session_id=runtime.session_id,
                capture_id=after_ref["capture_id"],
                screenshot_sha256=after_ref["screenshot_sha256"],
                viewport_size={"width": 800, "height": 600},
                asset_content_sha256=event["before"]["workflow"]["asset_content_sha256"],
                target_window_handle=geometry["target_window_handle"],
                target_process_id=geometry["target_process_id"],
                png_bytes=after_png,
            )
    return runtime, receipt, actual_backend, child


def test_capability_shape_is_metadata_only() -> None:
    assert LEARNING_SEGMENT_CAPABILITY == {
        "contract_version": "agent_learning_segment_v1",
        "operations": [
            "start_learning_segment",
            "get_learning_segment",
            "finish_learning_segment",
        ],
    }


def test_empty_start_retry_restart_and_finish_are_persistent_and_truthful(
    tmp_path: Path,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    started = _start(owner, connection)
    assert started == {
        "contract_version": "agent_learning_segment_v1",
        "segment_id": started["segment_id"],
        "status": "active",
        "revision": 1,
        "title": "Fresh two-action segment",
        "children": [],
        "source_status": "empty",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_executed": False,
    }
    assert _start(owner, connection) == started
    with pytest.raises(AgentLinkError) as conflict:
        owner.start(
            connection_id=connection["connection_id"], task_id=TASK,
            idempotency_key="segment-start", title="Changed",
        )
    assert conflict.value.code == "idempotency_conflict"
    store.close()

    reopened = AgentLinkStore(tmp_path / "agent-link.json")
    restarted = LearningSegmentOwner(
        reopened, recorder=recorder, capture_archive=archive,
    )
    assert restarted.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=started["segment_id"],
    ) == started
    closed = restarted.finish(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=started["segment_id"], expected_revision=1,
    )
    assert closed["status"] == "closed"
    assert closed["source_status"] == "empty"
    assert closed["revision"] > 1
    assert restarted.finish(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=started["segment_id"], expected_revision=1,
    ) == closed
    assert restarted.finish(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=started["segment_id"], expected_revision=closed["revision"],
    ) == closed
    reopened.close()


def test_restart_rejects_resealed_segment_title(tmp_path: Path) -> None:
    store, service, _, _, owner = _owners(tmp_path)
    connection = _connection(service)
    started = _start(owner, connection, key="strict-restart")
    store.close()
    path = tmp_path / "agent-link.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["connections"][connection["connection_id"]]["learning_segments"][
        started["segment_id"]
    ]["title"] = "Resealed title"
    path.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    with pytest.raises(AgentLinkError) as corrupt:
        AgentLinkStore(path)
    assert corrupt.value.code == "corrupt_store"


def test_connection_isolation_single_active_and_revocation(tmp_path: Path) -> None:
    store, service, _, _, owner = _owners(tmp_path)
    first = _connection(service)
    other = _connection(service, "other-segment-agent")
    started = _start(owner, first)
    with pytest.raises(AgentLinkError) as busy:
        owner.start(
            connection_id=first["connection_id"], task_id=TASK,
            idempotency_key="second", title="Second",
        )
    assert busy.value.code == "learning_busy"
    assert _start(owner, other)["segment_id"] != started["segment_id"]
    service.reviewer_call(REVIEWER, "revoke_connection", {
        "connection_id": first["connection_id"], "idempotency_key": "revoke-first",
    })
    with pytest.raises(AgentLinkError) as revoked:
        owner.get(
            connection_id=first["connection_id"], task_id=TASK,
            segment_id=started["segment_id"],
        )
    assert revoked.value.code == "connection_revoked"
    store.close()


def test_two_actual_actions_join_exact_sources_and_finish_children(
    tmp_path: Path,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection)
    first = _perform_action(
        tmp_path, owner, recorder, archive, connection, segment["segment_id"],
        sequence=1,
    )
    second = _perform_action(
        tmp_path, owner, recorder, archive, connection, segment["segment_id"],
        sequence=2,
    )

    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    assert current["source_status"] == "complete"
    assert [item["runtime_session_id"] for item in current["children"]] == [
        first[0].session_id, second[0].session_id,
    ]
    assert [item["revision"] for item in current["children"]] == [3, 3]
    assert [item["outcomes"][0]["outcome"] for item in current["children"]] == [
        "VERIFIED", "VERIFIED",
    ]
    serialized = json.dumps(current, ensure_ascii=False)
    assert "png_bytes" not in serialized and "events" not in serialized
    assert str(tmp_path) not in serialized
    assert first[2].attempt_count == second[2].attempt_count == 1

    closed = owner.finish(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"], expected_revision=current["revision"],
    )
    assert closed["status"] == "closed"
    assert closed["source_status"] == "complete"
    assert [item["recording_status"] for item in closed["children"]] == [
        "finished", "finished",
    ]
    store.close()


def test_unresolved_child_blocks_second_attach_and_finish(tmp_path: Path) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection)
    first_controller, _, first_backend, _, _ = _controller(tmp_path, recorder)
    first_runtime = first_controller.start_session()
    owner.attach_runtime(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"], runtime_session_id=first_runtime.session_id,
    )
    first_controller.abandon_session(session_id=first_runtime.session_id)
    second_controller, _, second_backend, _, _ = _controller(tmp_path, recorder)
    second_runtime = second_controller.start_session()

    with pytest.raises(AgentLinkError) as attach_busy:
        owner.attach_runtime(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], runtime_session_id=second_runtime.session_id,
        )
    assert attach_busy.value.code == "learning_busy"
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    with pytest.raises(AgentLinkError) as finish_busy:
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], expected_revision=current["revision"],
        )
    assert finish_busy.value.code == "learning_busy"
    assert first_backend.attempt_count == second_backend.attempt_count == 0
    assert len(current["children"]) == 1
    second_controller.abandon_session(session_id=second_runtime.session_id)
    store.close()


def test_missing_png_remains_incomplete_and_blocks_finish(
    tmp_path: Path,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    missing = _start(owner, connection, key="missing-start")
    _perform_action(
        tmp_path, owner, recorder, archive, connection, missing["segment_id"],
        sequence=3, pin=False,
    )
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=missing["segment_id"],
    )
    assert current["source_status"] == "incomplete"
    with pytest.raises(AgentLinkError) as unavailable:
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=missing["segment_id"], expected_revision=current["revision"],
        )
    assert unavailable.value.code == "learning_source_unavailable"

    store.close()


def test_qualified_unknown_outcome_is_not_relabelled_success(tmp_path: Path) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection, key="unknown-start")
    _perform_action(
        tmp_path, owner, recorder, archive, connection, segment["segment_id"],
        sequence=4, unknown=True,
    )
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    assert current["source_status"] == "incomplete"
    assert current["children"][0]["outcomes"][0]["outcome"] == "INDETERMINATE"
    with pytest.raises(AgentLinkError) as unavailable:
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], expected_revision=current["revision"],
        )
    assert unavailable.value.code == "learning_source_unavailable"
    store.close()


def test_finish_rechecks_complete_sources_before_closing_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection, key="source-race-start")
    _perform_action(
        tmp_path, owner, recorder, archive, connection, segment["segment_id"],
        sequence=5,
    )
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    child = current["children"][0]
    session = recorder.get_learning_session(
        learning_session_id=child["learning_session_id"],
    )
    event = _event(session)
    digest = event["before"]["capture"]["screenshot_sha256"]
    blob = archive.blobs_root / f"{digest}.png"
    original = archive.read_session_evidence
    reads = 0

    def remove_after_first_finish_read(**kwargs):
        nonlocal reads
        evidence = original(**kwargs)
        reads += 1
        if reads == 1:
            blob.unlink()
        return evidence

    monkeypatch.setattr(archive, "read_session_evidence", remove_after_first_finish_read)
    with pytest.raises(AgentLinkError) as unavailable:
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], expected_revision=current["revision"],
        )
    assert unavailable.value.code == "learning_source_unavailable"
    assert recorder.get_learning_session(
        learning_session_id=child["learning_session_id"],
    )["status"] == "active"
    store.close()


def test_resumed_closing_rechecks_sources_after_child_was_finished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection, key="closing-retry-start")
    _perform_action(
        tmp_path, owner, recorder, archive, connection, segment["segment_id"],
        sequence=6,
    )
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    child = current["children"][0]
    original_mutate = store.mutate
    mutations = 0

    def interrupt_commit(change):
        nonlocal mutations
        mutations += 1
        if mutations == 2:
            raise AgentLinkError(
                "learning_source_unavailable", "synthetic close commit interruption",
            )
        return original_mutate(change)

    monkeypatch.setattr(store, "mutate", interrupt_commit)
    with pytest.raises(AgentLinkError):
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], expected_revision=current["revision"],
        )
    assert recorder.get_learning_session(
        learning_session_id=child["learning_session_id"],
    )["status"] == "finished"
    monkeypatch.setattr(store, "mutate", original_mutate)
    closing = owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )
    assert closing["status"] == "closing"
    session = recorder.get_learning_session(
        learning_session_id=child["learning_session_id"],
    )
    digest = _event(session)["before"]["capture"]["screenshot_sha256"]
    (archive.blobs_root / f"{digest}.png").unlink()

    with pytest.raises(AgentLinkError) as unavailable:
        owner.finish(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], expected_revision=closing["revision"],
        )
    assert unavailable.value.code == "learning_source_unavailable"
    assert owner.get(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"],
    )["status"] == "closing"
    store.close()


def test_pending_bind_retry_uses_same_child_without_backend_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service, recorder, archive, owner = _owners(tmp_path)
    connection = _connection(service)
    segment = _start(owner, connection)
    controller, _, backend, _, _ = _controller(tmp_path, recorder)
    runtime = controller.start_session()
    original = recorder.start_learning_session
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("synthetic recorder bind interruption")
        return original(**kwargs)

    monkeypatch.setattr(recorder, "start_learning_session", fail_once)
    with pytest.raises(AgentLinkError) as interrupted:
        owner.attach_runtime(
            connection_id=connection["connection_id"], task_id=TASK,
            segment_id=segment["segment_id"], runtime_session_id=runtime.session_id,
        )
    assert interrupted.value.code == "learning_source_unavailable"
    resumed = owner.attach_runtime(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"], runtime_session_id=runtime.session_id,
    )
    assert len(resumed["children"]) == 1
    assert resumed["children"][0]["runtime_session_id"] == runtime.session_id
    assert backend.attempt_count == 0
    controller.abandon_session(session_id=runtime.session_id)
    store.close()
