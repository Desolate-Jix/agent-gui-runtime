"""工作台只读学习状态适配，不创建整理请求或执行命令。"""
import pytest

from app.learning_memory.editor_client import MemoryEditorClient
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene
from test_learning_synthesis import _input_workflow


def _reply(request):
    return {"action": "synthesis_complete", "synthesis_id": request["synthesis_id"],
            "source_sha256": request["source_sha256"], "parameter_bindings": {},
            "annotations": {"click-0": {"verification": {"kind": "agent_judgment"}},
                            "click-1": {"verification": {"kind": "agent_judgment"}}}}


def test_existing_synthesis_is_read_without_new_request_or_command(repeated_state):
    store, root, started, _, _ = repeated_state
    session = store.session
    requests = root / "desktop-review/learning-synthesis"
    with MemoryEditorClient(root) as client:
        first = client.read_workflow_learning(session)
        assert first["status"] == "awaiting_agent"
        assert first["learning_id"] == started["learning_id"]
        assert first["synthesis"]["status"] == "awaiting_agent"
        assert first["program"]["program_id"] is None
        before = {str(path.relative_to(root)): path.read_bytes() for path in requests.rglob("*") if path.is_file()}
        assert client.read_workflow_learning(session) == first
        assert {str(path.relative_to(root)): path.read_bytes() for path in requests.rglob("*") if path.is_file()} == before
        assert not list((session / "commands").glob("*.json"))
    request = first["synthesis"]["synthesis_request"]
    completed = store.control("learning_workflow", _reply(request), "reply")
    assert completed["status"] == "draft_ready"
    with MemoryEditorClient(root) as reopened:
        ready = reopened.read_workflow_learning(session)
        assert ready["status"] == "draft_ready"
        assert ready["synthesis"] == completed
        assert ready["program"]["program_id"] is None


def test_invalid_and_empty_session_rejected_or_reported(tmp_path):
    root = tmp_path / "memory-library"
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="session"):
            library.read_workflow_learning(tmp_path / "missing")
        session = tmp_path / "session-one"; session.mkdir()
        assert library.read_workflow_learning(session)["status"] == "no_learning"
        foreign = tmp_path / "foreign" / "session-two"; foreign.mkdir(parents=True)
        with pytest.raises(ValueError, match="library"):
            library.read_workflow_learning(foreign)
    assert not list(root.rglob("learning-synthesis/request.json"))


def test_recording_and_interface_learning_have_distinct_states(tmp_path):
    root = tmp_path / "memory-library"
    session = tmp_path / "session-one"; session.mkdir()
    store = LearningEventStore(session)
    store.control("learning_start", {"scope": "interface", "title": "页面"}, "start-interface")
    with MemoryWorkspace(root) as library:
        assert library.read_workflow_learning(session)["status"] == "interface_only"
    store.control("learning_stop", {}, "stop-interface")
    store.control("learning_start", {"scope": "workflow", "title": "流程",
                                     "project_id": "review"}, "start-workflow")
    with MemoryWorkspace(root) as library:
        assert library.read_workflow_learning(session)["status"] == "recording"


def test_missing_request_with_remaining_synthesis_state_is_corruption(repeated_state):
    store, root, _, _, _ = repeated_state
    with MemoryWorkspace(root) as library:
        state = library.read_workflow_learning(store.session)
        identity = state["synthesis"]["synthesis_request"]["synthesis_id"]
    request = root / "desktop-review/learning-synthesis" / identity / "request.json"
    request.rename(request.with_suffix(".missing"))
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match="synthesis.*request"):
            library.read_workflow_learning(store.session)


def test_stopped_unsupported_action_needs_review_without_creating_request(tmp_path):
    store, started, stopped = _input_workflow(tmp_path, {"kind": "step",
        "operation": "execute_recognition_plan", "request": {"goal": "打开详情", "click_kind": "double"}})
    root = tmp_path / "memory-library"
    assert stopped["synthesis"]["status"] == "needs_review"
    with MemoryEditorClient(root) as client:
        state = client.read_workflow_learning(store.session)
    assert state["status"] == "needs_review"
    assert state["learning_id"] == started["learning_id"]
    assert state["synthesis"]["reason"] == "no_compilable_actions"
    assert state["synthesis"]["unresolved_items"]
    assert not list((root / "desktop-review/learning-synthesis").glob("*/request.json"))
    assert not list((store.session / "commands").glob("*.json"))


def test_pending_ticket_and_valid_unrequested_source_are_distinct(tmp_path, repeated_state):
    session = tmp_path / "session-pending"; session.mkdir()
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "录制",
        "project_id": "review"}, "start")
    ticket = store.prepare("pending-click", {"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "打开"}}, None)
    store.reserve(ticket)
    store.control("learning_stop", {}, "stop")
    with MemoryWorkspace(tmp_path / "memory-library") as library:
        waiting = library.read_workflow_learning(session)
    assert waiting["status"] == "awaiting_recording" and waiting["learning_id"] == started["learning_id"]

    other_store, root, _, _, _ = repeated_state
    with MemoryWorkspace(root) as library:
        pending = library.read_workflow_learning(other_store.session)
    identity = pending["synthesis"]["synthesis_request"]["synthesis_id"]
    request = root / "desktop-review/learning-synthesis" / identity / "request.json"
    request.rename(tmp_path / "held-request.json")
    with MemoryWorkspace(root) as library:
        unrequested = library.read_workflow_learning(other_store.session)
    assert unrequested["status"] == "not_requested" and unrequested["synthesis"] is None
    assert not request.exists()


def test_saved_program_wins_over_old_synthesis_draft(repeated_state):
    store, root, _, _, _ = repeated_state
    with MemoryEditorClient(root) as client:
        pending = client.read_workflow_learning(store.session)
    request = pending["synthesis"]["synthesis_request"]
    completed = store.control("learning_workflow", _reply(request), "reply")
    draft = completed["draft"]
    with MemoryEditorClient(root) as client:
        saved = client.save_workflow_program(draft["workflow_id"],
            client.load_workflow_program(draft["workflow_id"])["content_sha256"],
            draft["definition"], "save", target_recipes=[row["recipe"] for row in draft["proposed_target_recipes"]])
        state = client.read_workflow_learning(store.session)
    assert state["status"] == "existing_program_preserved"
    assert state["program"]["program_id"] == saved["program_id"]
    assert state["synthesis"]["status"] == "existing_program_preserved"
    assert state["synthesis"].get("draft") is None
