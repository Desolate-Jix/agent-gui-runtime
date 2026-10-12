"""真实 producer/owner/持久队列贯通；只替换模型、桌面与字段读取边界。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.execution import input_sequence
from app.agent.windows_text_field_reader import TextFieldReadError
from tests.test_local_step_timings import timed_scene
from tests.test_recognition_dispatch_boundary import route


REQUEST = {"field_goal": "Focus the fresh field", "text": "fresh synthetic text",
           "clear_existing": True, "submit_search": True}
TARGET = {"handle": 321, "process_id": 12, "process_create_time": 123.5}


@pytest.fixture
def partial(route, timed_scene, monkeypatch):
    from app.execution import local_direct_step
    response = route.run("success")
    monkeypatch.setattr(local_direct_step, "_post_action", lambda *args: deepcopy(response))
    monkeypatch.setattr(input_sequence, "_focus_field_binding", lambda *args: {
        "runtime_id": [42, 1], "control_type": "Edit", "bbox": {"x": 1, "y": 1, "w": 300, "h": 40}})
    reads = []

    def read(*args, **kwargs):
        reads.append("check_focus")
        raise TextFieldReadError("text_field_value_patterns_disagree",
            diagnostic={"phase": "read_text", "read_index": 1})

    monkeypatch.setattr(input_sequence, "_read_field", read)
    result = input_sequence.run_input_sequence(timed_scene[0],
        {"handle": 321, "process_id": 12}, REQUEST)
    assert result["status"] == "interrupted" and result["action_executed"] is True
    assert result["completed_steps"] == ["focus"] and len(result["steps"]) == 1
    assert result["steps"][0]["receipt"]["local_input_scope_closed"] is True
    return SimpleNamespace(result=result, reads=reads, events=route.events)


def queued(tmp_path, monkeypatch, result):
    from tests import test_task_plan_runner as runner_tests
    from tests.test_task_plan_contract import plan
    monkeypatch.setattr(runner_tests, "TARGET", deepcopy(TARGET))
    source = plan(verification={"kind": "agent_judgment"})
    source["schema_version"] = "task_plan.v2"
    source["steps"][0]["action"] = {"kind": "input_sequence", **REQUEST}
    decision_calls = []

    def forbidden(**kwargs):
        decision_calls.append(kwargs)
        pytest.fail("interrupted input cannot call Decision")

    s = runner_tests.scene(tmp_path, monkeypatch, source=source,
        decision=SimpleNamespace(evaluate=forbidden))
    pending = s.runtime.backend.status(s.run_id)["pending"]
    path = s.session / "responses" / (pending["execution_request_id"] + ".json")
    return s, pending, path, decision_calls


def persist_original(s, pending, path, result, *, async_terminal=False):
    payload = {"status": "returned", "command": deepcopy(pending["suggested_command"]), "result": deepcopy(result)}
    if async_terminal:
        # 保留真实宿主原形：首次响应仍 running，独立 agent 回执已经失败终结。
        command_id = pending["execution_request_id"]
        payload["result"] = {"contract_version": "agent_command.v1", "command_id": command_id,
            "status": "running", "action_executed": False, "automatic_retry_allowed": False}
        write_json_snapshot(s.session / "agent-commands" / (command_id + ".json"), {
            "contract_version": "agent_command.v1", "command_id": command_id, "status": "failed",
            "result": deepcopy(result), "progress": deepcopy(result), "action_executed": True,
            "dispatch_in_progress": False, "cancel_requested": False, "automatic_retry_allowed": False})
    write_json_snapshot(path, payload)
    return path.read_bytes()


def test_only_typed_readonly_failure_produces_bound_known_partial(partial):
    proof = partial.result.get("partial_input_terminal")
    assert isinstance(proof, dict), "focus-only read failure needs explicit producer proof"
    assert proof["contract_version"] == "input_sequence_focus_partial.v1"
    assert proof["started_actions"] == ["focus"] and proof["read_phase"] == "check_focus"
    assert proof["target_identity"] == TARGET
    assert partial.reads == ["check_focus"]
    assert partial.events.count("click_point") == 1


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("async_terminal", [False, True])
def test_known_focus_partial_settles_original_ticket_and_unlocks_owned_close(
        partial, tmp_path, monkeypatch, cancel, async_terminal):
    s, pending, path, calls = queued(tmp_path, monkeypatch, partial.result)
    if cancel:
        waiting = s.runtime.tick(force=True)
        assert waiting["pending"] == pending and waiting["history"] == []
    original = persist_original(s, pending, path, partial.result, async_terminal=async_terminal)
    if cancel:
        request = {"action": "cancel", "run_id": s.run_id}
        command = {"kind": "task_plan", "request": request}
        write_json_snapshot(s.session / "commands/cancel-original.json", command)
        requested = s.runtime.control(request, "cancel-original")
        write_json_snapshot(s.session / "responses/cancel-original.json",
            {"status": "returned", "command": command, "result": requested})
        assert requested["status"] == "cancel_requested"
    final = s.runtime.tick(force=True)
    assert final["status"] == ("cancelled" if cancel else "failed")
    assert final["runner_state"] == final["status"] and final["pending"] is None
    assert len(final["history"]) == 1
    entry = final["history"][0]
    assert entry["execution_request_id"] == pending["execution_request_id"]
    assert entry["original_input_status"] == "failed" and entry["action_executed"] is True
    assert entry["verdict"] == final["status"].replace("failed", "failure")
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    if cancel:
        assert s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-original")["status"] == "cancelled"
    for i in range(2):
        snapshot = s.runtime.control({"action": "status", "run_id": s.run_id}, "status-" + str(i))
        assert snapshot["pending"] is None and snapshot["history"] == final["history"]
        assert s.runtime.tick(force=True) is None
    source = s.runtime.backend._source(s.runtime.backend.status(s.run_id))["plan"]
    successor = {"successor_request_id": "partial-successor", "successor_of": s.run_id,
        "parent_plan_sha256": final["plan_sha256"], "prefix_sha256": final["prefix_sha256"],
        "lineage_generation": 0, "reason": "cannot replay partial input"}
    with pytest.raises(ValueError, match="task_plan_successor_original_input_not_quiescent"):
        s.runtime.control({"action": "start", "plan": source, "successor": successor}, "successor-transport")
    with pytest.raises(ValueError, match="task_plan_successor_parent_input_unknown"):
        s.runtime.backend.start_successor(source, TARGET, successor, transport_request_id="successor-direct")
    assert len(list(s.session.glob("commands/trial-exec-*.json"))) == 1
    assert len(list(s.session.glob("commands/*.json"))) == (2 if cancel else 1)
    assert path.read_bytes() == original and calls == []
    assert partial.events.count("click_point") == 1


def test_terminal_reuses_the_same_known_partial_proof(partial, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    save(tmp_path, "commands", "original", command)
    save(tmp_path, "responses", "original", {"status": "returned", "command": command, "result": partial.result})
    known = inspect(tmp_path)["commands"]["original"]
    assert known == {"kind": "input_sequence", "terminal_status": "failed", "action_executed": True}


def damage(result, mode):
    if mode == "missing": result.pop("partial_input_terminal", None)
    elif mode == "bad_proof": result["partial_input_terminal"] = {"contract_version": "input_sequence_focus_partial.v1"}
    elif mode == "dispatching": result["steps"][0]["status"] = "dispatching"
    elif mode == "local_unknown": result["steps"][0]["receipt"]["phase"] = "result_unknown"
    elif mode == "unclosed": result["steps"][0]["receipt"]["local_input_scope_closed"] = False
    elif mode == "identity": result["steps"][0]["receipt"]["target_identity"]["process_create_time"] += 1
    elif mode == "extra_input": result["steps"].append({"name": "type", "operation": "type_text", "status": "dispatching", "action_executed": None})
    elif mode == "conflict":
        data = result["steps"][0]["receipt"]["response"]["data"]
        data.get("result", data)["execution_path"]["action_executed"] = False
    elif mode == "wrong_phase": result["interrupted_at"] = "check_input"
    elif mode == "other_error": result["error"]["type"] = "RuntimeError"
    elif mode == "request_hash": result.setdefault("partial_input_terminal", {})["request_sha256"] = "0" * 64
    elif mode == "focus_hash": result.setdefault("partial_input_terminal", {})["focus_receipt_sha256"] = "0" * 64
    elif mode == "proof_flag_as_int": result.setdefault("partial_input_terminal", {})["suffix_dispatch_started"] = 0
    elif mode == "no_click_fact":
        data = result["steps"][0]["receipt"]["response"]["data"]
        data.get("result", data).pop("click_result", None)


@pytest.mark.parametrize("mode", ["missing", "bad_proof", "dispatching", "local_unknown", "unclosed",
    "identity", "extra_input", "conflict", "wrong_phase", "other_error", "request_hash", "focus_hash",
    "proof_flag_as_int", "no_click_fact"])
def test_unproven_partial_still_owns_the_original_ticket(partial, tmp_path, monkeypatch, mode):
    result = deepcopy(partial.result)
    damage(result, mode)
    s, pending, path, calls = queued(tmp_path, monkeypatch, result)
    original = persist_original(s, pending, path, result)
    first = s.runtime.tick(force=True)
    assert first["status"] == "pending" and first["pending"] == pending and first["history"] == []
    assert first["wait_reason"] == "verification_required"
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unknown")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancel_requested" and final["pending"] == pending and final["history"] == []
    with pytest.raises(ValueError, match="task_plan_run_active"):
        s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    assert len(list(s.session.glob("commands/*.json"))) == 1 and path.read_bytes() == original and calls == []


def test_terminal_refuses_a_declared_but_invalid_partial_proof(partial, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    result = deepcopy(partial.result)
    damage(result, "bad_proof")
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    save(tmp_path, "commands", "original", command)
    save(tmp_path, "responses", "original", {"status": "returned", "command": command, "result": result})
    with pytest.raises(ValueError, match="session_input_batch_unknown"):
        inspect(tmp_path)


def test_completed_claim_cannot_bypass_a_conflicting_partial_proof(partial, tmp_path, monkeypatch):
    from app.core.input_sequence_partial import original_input_status
    result = deepcopy(partial.result)
    result["status"] = "completed"
    s, pending, path, calls = queued(tmp_path, monkeypatch, result)
    assert original_input_status({"status": "returned", "command": pending["suggested_command"],
        "result": result}, pending["suggested_command"], succeeded=True, action_executed=True,
        target_identity=TARGET) == "unknown"
    persist_original(s, pending, path, result)
    first = s.runtime.tick(force=True)
    assert first["pending"] == pending and first["history"] == []
    outcomes = first["verification_results"].values()
    assert outcomes and all(row["original_input_status"] == "unknown" for row in outcomes)
    assert calls == []


def test_arbitrary_exception_after_focus_does_not_mint_partial_proof(partial, timed_scene, monkeypatch):
    def read(*args, **kwargs):
        raise RuntimeError("unclassified failure")
    monkeypatch.setattr(input_sequence, "_read_field", read)
    result = input_sequence.run_input_sequence(timed_scene[0], {"handle": 321, "process_id": 12}, REQUEST)
    assert result["action_executed"] is True and "partial_input_terminal" not in result
