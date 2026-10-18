"""当前 Agent 的一次整理交接可恢复，生成草稿不冒充审核或执行。"""
from copy import deepcopy
from hashlib import sha256
import json

from PIL import Image
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene


def _stop(store):
    return store.control("learning_stop", {}, "stop-again")["synthesis"]


def _reply(request, **changes):
    value = {"action": "synthesis_complete", "synthesis_id": request["synthesis_id"],
             "source_sha256": request["source_sha256"], "parameter_bindings": {},
             "annotations": {"click-0": {"title": "查询", "verification": {"kind": "agent_judgment"}},
                             "click-1": {"title": "刷新", "verification": {"kind": "agent_judgment"}}}}
    value.update(changes)
    return value


def test_stop_hands_off_once_and_reply_persists_pending_draft(repeated_state):
    store, root, started, _, _ = repeated_state
    pending = _stop(store)
    assert pending["status"] == "awaiting_agent"
    request = pending["synthesis_request"]
    assert request["learning_session_id"] == started["learning_id"]
    assert {row["event_id"] for row in request["events"]} == {"click-0", "click-1"}
    assert _stop(store)["synthesis_request"] == request
    assert pending["input_executed"] is False and pending["automatic_retry_allowed"] is False
    reply = _reply(request)
    completed = store.control("learning_workflow", reply, "synthesis-reply")
    assert completed["status"] == "draft_ready"
    draft = completed["draft"]
    assert [step["title"] for step in draft["definition"]["steps"]] == ["查询", "刷新"]
    assert all(step["review_status"] == "pending" for step in draft["definition"]["steps"])
    assert len(draft["proposed_target_recipes"]) == 2
    assert completed["metrics"]["reply_attempts"] == 1
    assert completed["metrics"]["total_model_calls"] is None
    assert completed["metrics"]["total_usage"] is None
    assert completed["metrics"]["compile_ms"] >= 0
    assert store.control("learning_workflow", reply, "same-reply-new-id") == completed
    reopened = LearningEventStore(store.session)
    status = reopened.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "read-synthesis")
    assert status == completed
    with MemoryWorkspace(root) as library:
        assert library.load_workflow_program(draft["workflow_id"])["program_id"] is None
    assert not list((root / "desktop-review/target-recipes").glob("*.json"))
    changed = deepcopy(reply)
    changed["annotations"]["click-0"]["title"] = "不同回复"
    with pytest.raises(ValueError, match="synthesis_reply_conflict"):
        store.control("learning_workflow", changed, "conflicting-reply")


def test_invalid_reply_has_event_field_and_legacy_order_is_explicit(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    bad = _reply(request, annotations={"click-1": {"unrecognized": True}})
    rejected = store.control("learning_workflow", bad, "bad-reply")
    assert rejected["status"] == "needs_correction"
    assert rejected["errors"][0]["event_id"] == "click-1"
    assert rejected["errors"][0]["field"] == "annotations.click-1"
    assert store.control("learning_workflow", bad, "bad-reply") == rejected
    pending = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "status-after-error")
    assert pending["status"] == "awaiting_agent"
    assert pending["synthesis_request"] == request
    assert pending["last_correction"] == {"reply_request_id": "bad-reply", "result": rejected,
        "ordering": "recorded_sequence"}
    newer_bad = _reply(request, annotations={"click-0": {"unrecognized": True}})
    newer = store.control("learning_workflow", newer_bad, "aaa-newer-error")
    latest = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "status-after-newer-error")
    assert latest["last_correction"] == {"reply_request_id": "aaa-newer-error", "result": newer,
        "ordering": "recorded_sequence"}
    # 旧 attempt 没有时间字段时，顺序未知；status 用稳定的 ID 顺序选取。
    attempts = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts"
    for path in attempts.glob("*.json"):
        legacy = json.loads(path.read_text(encoding="utf-8"))
        legacy.pop("attempt_created_at", None)
        legacy.pop("attempt_index", None)
        legacy.pop("record_sha256")
        legacy["record_sha256"] = content_hash(legacy)
        path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    legacy_status = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "legacy-status")
    assert legacy_status["last_correction"]["reply_request_id"] == "bad-reply"
    assert legacy_status["last_correction"]["ordering"] == "unknown"
    with pytest.raises(ValueError, match="synthesis_attempt_order_unknown"):
        store.control("learning_workflow", {"action": "synthesis_resume",
            "synthesis_id": request["synthesis_id"], "source_sha256": request["source_sha256"],
            "after_reply_request_id": "bad-reply", "user_instruction": "请根据原始记录继续修正。"}, "user-resume")



def test_attempt_sequence_wins_when_clock_moves_backwards(repeated_state, monkeypatch):
    from app.learning_memory import learning_synthesis
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    timestamps = iter(("2026-10-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"))
    monkeypatch.setattr(learning_synthesis, "_now", lambda: next(timestamps))
    first = _reply(request, annotations={"click-0": {"unrecognized": True}})
    second = _reply(request, annotations={"click-1": {"unrecognized": True}})
    store.control("learning_workflow", first, "first-attempt")
    store.control("learning_workflow", second, "second-attempt")
    attempts = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts"
    first_record = json.loads((attempts / "first-attempt.json").read_text(encoding="utf-8"))
    second_record = json.loads((attempts / "second-attempt.json").read_text(encoding="utf-8"))
    assert (first_record["attempt_index"], second_record["attempt_index"]) == (1, 2)
    assert second_record["attempt_created_at"] < first_record["attempt_created_at"]
    state = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "after-clock-rollback")
    assert state["last_correction"]["reply_request_id"] == "second-attempt"
    assert state["last_correction"]["ordering"] == "recorded_sequence"


@pytest.mark.parametrize(("field", "value"), [
    ("attempt_index", 0), ("attempt_created_at", "not-a-timestamp")])
def test_invalid_attempt_order_metadata_is_rejected(repeated_state, field, value):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    bad = _reply(request, annotations={"click-1": {"unrecognized": True}})
    store.control("learning_workflow", bad, "malformed-order")
    path = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts/malformed-order.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record[field] = value
    record.pop("record_sha256")
    record["record_sha256"] = content_hash(record)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="synthesis_attempt_order_invalid"):
        store.control("learning_workflow", {"action": "synthesis_status",
            "synthesis_id": request["synthesis_id"]}, "read-malformed-order")


def test_legacy_timestamp_order_is_reported_as_legacy_time(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    for request_id, event_id, timestamp in (("legacy-a", "click-0", "2026-08-01T00:00:00+00:00"),
                                             ("legacy-b", "click-1", "2026-08-02T00:00:00+00:00")):
        store.control("learning_workflow", _reply(request,
            annotations={event_id: {"unrecognized": True}}), request_id)
    attempts = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts"
    for request_id, timestamp in (("legacy-a", "2026-08-01T00:00:00+00:00"),
                                  ("legacy-b", "2026-08-02T00:00:00+00:00")):
        path = attempts / f"{request_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("attempt_index")
        record["attempt_created_at"] = timestamp
        record.pop("record_sha256")
        record["record_sha256"] = content_hash(record)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    state = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "legacy-time-order")
    assert state["last_correction"]["reply_request_id"] == "legacy-b"
    assert state["last_correction"]["ordering"] == "legacy_time"

def test_invalid_nested_rule_identifies_recorded_event(repeated_state):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    bad = _reply(request, annotations={"click-1": {"verification": {
        "kind": "target_present", "target": {"name": "Refresh"}}}})
    result = store.control("learning_workflow", bad, "bad-target")
    assert result["status"] == "needs_correction"
    assert result["errors"][0]["event_id"] == "click-1"
    assert result["errors"][0]["code"] == "verification_target_invalid"


def test_wrong_or_changed_source_is_rejected(repeated_state):
    store, _, started, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    with pytest.raises(ValueError, match="synthesis_source_mismatch"):
        store.control("learning_workflow", _reply(request, source_sha256="0" * 64), "wrong-source")
    store.control("learning_start", {"scope": "workflow", "title": "新学习段",
        "project_id": "same-state"}, "another-start")
    store.control("learning_stop", {}, "another-stop")
    with pytest.raises(ValueError, match="synthesis_source_changed"):
        store.control("learning_workflow", _reply(request), "stale-source")
    replacement = store.control("learning_workflow", {"action": "synthesis_prepare",
        "learning_session_id": started["learning_id"]}, "new-snapshot")
    assert replacement["synthesis_request"]["synthesis_id"] != request["synthesis_id"]


def test_human_program_is_preserved_between_request_and_reply(repeated_state):
    store, _, started, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    draft = store.control("learning_workflow", {"action": "compile",
        "learning_session_id": started["learning_id"]}, "manual-compile")
    baseline = store.control("learning_workflow", {"action": "read",
        "workflow_id": draft["workflow_id"]}, "manual-read")
    draft["definition"]["title"] = "人工修订的工作流"
    saved = store.control("learning_workflow", {"action": "save", "workflow_id": draft["workflow_id"],
        "expected_sha256": baseline["content_sha256"], "definition": draft["definition"],
        "target_recipes": [row["recipe"] for row in draft["proposed_target_recipes"]]}, "manual-save")
    completed = store.control("learning_workflow", _reply(request), "late-agent-reply")
    assert completed["status"] == "existing_program_preserved"
    assert completed["draft"]["existing_program_id"] == saved["program_id"]
    assert completed["draft"]["definition"]["title"] == "人工修订的工作流"
    preserved = store.control("learning_workflow", {"action": "synthesis_prepare",
        "learning_session_id": started["learning_id"]}, "prepare-after-save")
    assert preserved["status"] == "existing_program_preserved"


def test_changed_persisted_request_is_not_accepted(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    path = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "request.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["request"]["events"] = []
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="synthesis_record_changed"):
        store.control("learning_workflow", {"action": "synthesis_status",
            "synthesis_id": request["synthesis_id"]}, "read-corrupt")


def _input_workflow(tmp_path, command=None):
    session = tmp_path / "input-session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    started = store.control("learning_start", {"scope": "workflow", "title": "查询编号",
        "project_id": "parameter-example"}, "start")
    before, after = session / "before.png", session / "after.png"
    Image.new("RGB", (100, 80), "white").save(before)
    Image.new("RGB", (100, 80), "blue").save(after)
    frame = lambda path: {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                          "window_size": {"width": 100, "height": 80}}
    command = command or {"kind": "input_sequence", "request": {"field_goal": "编号", "text": "样本甲",
        "submit_search": True, "clear_existing": True}}
    ticket = store.prepare("query", command, None)
    response = {"command": command, "learning_binding": ticket, "status": "returned",
        "result": {"status": "completed", "action_executed": True, "capture": frame(before),
                   "observation": {"capture": frame(after)}, "steps": []}}
    if command["kind"] == "step":
        response["result"]["response"] = {"success": True, "data": {"result": {"action_executed": True}}}
    write_json_snapshot(session / "responses/query.json", response)
    store.record("query", ticket)
    event = store.control("learning_event", {"event_id": "query"}, "read")["event"]
    identity = {"interface_key": "search", "state_key": "home", "meaning": "查询页"}
    store.control("learning_review", {"review": {"event_id": "query", "event_sha256": content_hash(event),
        "verdict": "success", "reviewer": "synthetic", "reason": "仅测试参数合同",
        "before": {**identity, "frame_sha256": frame(before)["sha256"]},
        "after": {**identity, "frame_sha256": frame(after)["sha256"]}}}, "review")
    result = store.control("learning_stop", {}, "stop")
    return store, started, result


def test_original_input_example_is_ephemeral_and_reply_parameterizes_it(tmp_path):
    store, _, stopped = _input_workflow(tmp_path)
    pending = stopped["synthesis"]
    assert pending["input_examples"]["query"] == {"status": "available", "value": "样本甲"}
    request = pending["synthesis_request"]
    path = tmp_path / "memory-library/desktop-review/learning-synthesis" / request["synthesis_id"] / "request.json"
    assert "样本甲" not in path.read_text(encoding="utf-8")
    reply = _reply(request, parameter_bindings={"query": {"name": "record_id", "example_value": "样本甲"}},
                   annotations={"query": {"verification": {"kind": "field_equals",
                       "target": {"control_type": "Edit", "name": "编号"},
                       "expected": {"source": "input", "name": "record_id"}}}})
    completed = store.control("learning_workflow", reply, "reply")
    assert completed["status"] == "draft_ready"
    assert completed["draft"]["definition"]["steps"][0]["action"]["text"] == {"source": "input", "name": "record_id"}
    assert "样本甲" not in (path.parent / "completion.json").read_text(encoding="utf-8")


def test_missing_or_changed_original_input_is_never_guessed(tmp_path):
    store, _, stopped = _input_workflow(tmp_path)
    request = stopped["synthesis"]["synthesis_request"]
    original = store.session / "responses/query.json"
    original.unlink()
    state = store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "missing-source")
    assert state["input_examples"]["query"]["status"] == "unavailable"
    assert "value" not in state["input_examples"]["query"]


def test_synthesis_source_failure_is_not_annotation_error(repeated_state, monkeypatch):
    from app.learning_memory import workflow_compiler
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    def broken_source(*args, **kwargs):
        raise ValueError("memory_graph_source_changed")
    monkeypatch.setattr(workflow_compiler, "read_project", broken_source)
    with pytest.raises(ValueError, match="memory_graph_source_changed"):
        store.control("learning_workflow", _reply(request), "source-failure")
    directory = root / "desktop-review/learning-synthesis" / request["synthesis_id"]
    assert not (directory / "completion.json").exists()
    assert not list((directory / "attempts").glob("*.json"))


@pytest.mark.parametrize("operation", ["status", "same_reply", "corrected_reply"])
def test_synthesis_attempt_is_bound_to_request(repeated_state, operation):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    bad = _reply(request, annotations={"click-1": {"unrecognized": True}})
    store.control("learning_workflow", bad, "bad-reply")
    path = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts/bad-reply.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["result"]["synthesis_id"] = "learning-synthesis-" + "a" * 64
    record.pop("record_sha256")
    record["record_sha256"] = content_hash(record)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    query, request_id = ({"action": "synthesis_status", "synthesis_id": request["synthesis_id"]}, "status")
    if operation == "same_reply":
        query, request_id = bad, "bad-reply"
    elif operation == "corrected_reply":
        query, request_id = _reply(request), "corrected-reply"
    with pytest.raises(ValueError, match="synthesis_attempt_binding_invalid"):
        store.control("learning_workflow", query, request_id)
    assert not (path.parent.parent / "completion.json").exists()


def test_synthesis_completion_payload_is_bound_to_source(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    store.control("learning_workflow", _reply(request), "valid-reply")
    path = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "completion.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["result"]["source_sha256"] = "0" * 64
    record.pop("record_sha256")
    record["record_sha256"] = content_hash(record)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="synthesis_completion_binding_invalid"):
        store.control("learning_workflow", {"action": "synthesis_status",
            "synthesis_id": request["synthesis_id"]}, "read-corrupt-completion")


@pytest.mark.parametrize("scope,pending", [("interface", False), ("workflow", True)])
def test_standalone_and_incomplete_stop_do_not_synthesize(tmp_path, scope, pending):
    store = LearningEventStore(tmp_path / "session")
    start = {"scope": scope, "title": "不强制生成工作流"}
    if scope == "workflow":
        start["project_id"] = "incomplete"
    store.control("learning_start", start, "start")
    if pending:
        store.reserve(store.prepare("pending-read", {"kind": "read_text"}, None))
    result = store.control("learning_stop", {}, "stop")
    assert "synthesis" not in result
    assert result["recording_complete"] is (not pending)
    assert not list((tmp_path / "memory-library/desktop-review/learning-synthesis").glob("*"))


def test_unsupported_recorded_action_does_not_request_empty_synthesis(tmp_path):
    _, _, stopped = _input_workflow(tmp_path, {"kind": "step", "operation": "execute_recognition_plan",
        "request": {"goal": "打开详情", "click_kind": "right"}})
    synthesis = stopped["synthesis"]
    assert synthesis["status"] == "needs_review"
    assert synthesis["reason"] == "no_compilable_actions"
    assert "action_definition_required" in {row["reason"] for row in synthesis["unresolved_items"]}
    assert not list((tmp_path / "memory-library/desktop-review/learning-synthesis").glob("*"))

