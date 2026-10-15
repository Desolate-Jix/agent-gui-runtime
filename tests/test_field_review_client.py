"""字段审核暂停只返回调用方，不替代审核或重发输入。"""
import asyncio
from copy import deepcopy

import pytest

from tests.test_learning_benchmark_client import ControlSDK, FakeSDK, client
from tests.test_task_plan_client import COMMAND, Session, client as plan_client, snapshot
from app.execution.task_plan_review import digest
from tests.test_agent_field_review_wait import field_wait_scene, wait_for


PACKET = {
    "schema": "field_review_packet.v1", "run_id": "original-plan",
    "step_id": "field-one", "execution_request_id": "original-input",
    "after": {"image_path": "evidence/after.png", "sha256": "a" * 64},
    "request": {"value": "\u4e2d\u6587"},
    "assessment": {"status": "verification_required"},
    "packet_sha256": "b" * 64, "evidence_set_sha256": "c" * 64,
    "assessment_round": 1,
}


class FieldReviewSDK(FakeSDK):
    @staticmethod
    def agent_receipt(request_id, command_id, state):
        value = FakeSDK.agent_receipt(request_id, command_id, state)
        if state == "awaiting_field_review":
            value["result"]["pending_field_review"] = deepcopy(PACKET)
        return value


class FieldReviewControlSDK(ControlSDK):
    agent_receipt = staticmethod(FieldReviewSDK.agent_receipt)


@pytest.mark.parametrize("initial", ["awaiting_field_review", "running"])
def test_field_review_returns_original_packet_and_stops_polling(tmp_path, initial):
    sdk = FieldReviewSDK()
    sdk.agent_initial = initial
    sdk.agent_statuses = ["awaiting_field_review"]

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-input", {"kind": "step",
                "operation": "execute_recognition_plan", "request": {"goal": "Fill field"}},
                total_timeout=1)

    result = asyncio.run(scenario())
    submits = [args for name, args in sdk.calls if name == "instant_run"]
    assert result["client_state"] == "review_required"
    assert result["original_request_id"] == result["command_id"] == "original-input"
    assert result["result"]["status"] == "awaiting_field_review"
    assert result["result"]["pending_field_review"] == PACKET
    assert result["automatic_retry_allowed"] is False
    if initial == "running":
        assert len(submits) == 2
        assert result["current_status_request_id"] == result["request_id"] == submits[-1]["request_id"]
        assert submits[-1]["command"] == {
            "kind": "agent_command_status", "request": {"command_id": "original-input"}}
    else:
        assert len(submits) == 1
        assert result["request_id"] == "original-input"
        assert result["current_status_request_id"] is None
    assert not any(name in {"instant_result", "instant_submit"} for name, _ in sdk.calls)


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
def test_explicit_control_field_review_preserves_outer_and_original_ids(tmp_path, kind):
    sdk = FieldReviewControlSDK(["awaiting_field_review"])
    command = {"kind": kind, "request": {"command_id": "original-input"}}
    if kind == "agent_command_continue":
        command["request"]["grounding_request_id"] = "original-grounding"

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("outer-control", command, total_timeout=1)

    result = asyncio.run(scenario())
    assert result["client_state"] == "review_required"
    assert result["request_id"] == result["original_request_id"] == "outer-control"
    assert result["current_status_request_id"] == "outer-control"
    assert result["command_id"] == "original-input"
    assert result["result"]["pending_field_review"] == PACKET
    assert result["automatic_retry_allowed"] is False
    assert [args for name, args in sdk.calls if name == "instant_run"] == [
        {"request_id": "outer-control", "command": command, "wait_ms": 1000,
         "detail": "full", "images": "none"}]


def field_plan(tmp_path):
    state = snapshot(reason="verification_required")
    state["session_directory"] = str(tmp_path)
    frame = {"image_path": str(tmp_path / "captures" / "typed.png"), "sha256": "a" * 64,
        "capture_id": "original-typed", "role": "after", "window_size": {"width": 80, "height": 60},
        "window_identity": deepcopy(state["target_identity"])}
    request = {"request_id": "original-field-check", "execution_request_id": "input-first",
        "step_id": "local-step-original", "condition": "The intended field contains the requested text",
        "phase": "after_action", "frames": [frame], "review_context": {
            "source_id": state["run_id"], "source_sha256": state["plan_sha256"]}}
    progress = {"path": "agent-commands/field-reviews/input-first-round0-progress.json", "sha256": "b" * 64}
    refs = [progress, {"path": "captures/typed.png", "sha256": frame["sha256"]}]
    packet = {"schema": "field_review_packet.v1", "command_id": "input-first", "stage": "after_type",
        "run_id": state["run_id"], "step_id": "first", "execution_request_id": "input-first",
        "plan_sha256": state["plan_sha256"], "session_directory": str(tmp_path), "assessment_round": 0,
        "request": request, "assessment": {**deepcopy(request), "status": "completed", "adopted": False,
            "disposition": "review_required"}, "condition": request["condition"],
        "after": frame, "frames": [frame], "progress_snapshot": progress, "progress_sha256": progress["sha256"],
        "evidence_refs": refs, "evidence_set_sha256": digest(refs),
        "authorizes_action": False, "automatic_retry_allowed": False}
    packet["packet_sha256"] = digest(packet)
    state.update(review_packet=packet, review_required=True, review_scope="input_value",
        allowed_controls=["review", "cancel"], caller_controls={"schema": "task_plan_caller_controls.v1",
            "authorizes_action": False, "review": {"caller_supplied_fields": ["verdict", "reason"], "request": {
                "action": "review", "run_id": packet["run_id"], "step_id": packet["step_id"],
                "execution_request_id": packet["execution_request_id"], "evidence_sha256": frame["sha256"],
                "review_packet_sha256": packet["packet_sha256"], "evidence_set_sha256": packet["evidence_set_sha256"],
                "assessment_round": 0}}})
    return state


def test_public_plan_returns_typed_prefix_review_packet_without_terminal_input(tmp_path, monkeypatch):
    state = field_plan(tmp_path)
    session = Session([state])
    events = []
    def no_local_read(*args, **kwargs):
        pytest.fail("public client must not read server image files")
    monkeypatch.setattr("pathlib.Path.read_bytes", no_local_read)
    result = asyncio.run(plan_client(tmp_path, session).run_plan("original-start", COMMAND,
        event_callback=events.append, total_timeout=1))
    assert result["client_state"] == "review_required"
    assert result["result"]["review_packet"] == state["review_packet"]
    assert result["result"]["caller_controls"] == state["caller_controls"]
    assert result["result"]["history"] == [] and result["active_command_id"] == "input-first"
    assert result["automatic_retry_allowed"] is False and result["no_replay"] is True
    assert len(events) == len(session.calls) == 1


@pytest.mark.parametrize("mutation", ["run_id", "step_id", "execution_request_id", "command_id",
    "plan_sha256", "session_directory", "assessment_round", "after", "evidence_set_sha256",
    "packet_sha256", "frame_reference", "progress_reference", "request_context", "assessment_frames",
    "request_context_shape", "progress_sha256", "authorizes_action"])
def test_public_plan_rejects_tampered_field_review_binding(tmp_path, mutation):
    state = field_plan(tmp_path)
    packet = state["review_packet"]
    if mutation in {"run_id", "step_id", "execution_request_id", "command_id", "plan_sha256", "session_directory"}:
        packet[mutation] = "other"
    elif mutation == "assessment_round":
        packet[mutation] = 1
    elif mutation == "after":
        packet["after"] = {**packet["after"], "sha256": "e" * 64}
    elif mutation == "frame_reference":
        packet["evidence_refs"][1]["sha256"] = "e" * 64
        packet["evidence_set_sha256"] = digest(packet["evidence_refs"])
    elif mutation == "progress_reference":
        packet["progress_snapshot"] = {"path": "other-progress.json", "sha256": "b" * 64}
    elif mutation == "request_context":
        packet["request"]["review_context"]["source_id"] = "other"
    elif mutation == "assessment_frames":
        packet["assessment"]["frames"] = []
    elif mutation == "request_context_shape":
        packet["request"]["review_context"] = []
    elif mutation == "authorizes_action":
        packet["authorizes_action"] = True
    else:
        packet[mutation] = "e" * 64
    if mutation != "packet_sha256":
        packet["packet_sha256"] = digest({key: value for key, value in packet.items() if key != "packet_sha256"})
    with pytest.raises(ValueError, match="benchmark_task_plan_field_review"):
        asyncio.run(plan_client(tmp_path, Session([state])).run_plan("original-start", COMMAND, total_timeout=1))


def test_actual_worker_packet_passes_public_plan_contract(tmp_path, field_wait_scene):
    scene = field_wait_scene
    scene.start()
    wait_for(scene.jobs, "awaiting_field_review")
    packet = scene.jobs.get_field_review("field-job")["packet"]
    state = snapshot(reason="verification_required", command_id="field-job")
    state.update(run_id=packet["run_id"], current_step_id=packet["step_id"],
        plan_sha256=packet["plan_sha256"], session_directory=packet["session_directory"],
        target_identity=packet["after"]["window_identity"], review_packet=packet)
    state["wait"].update(run_id=packet["run_id"], step_id=packet["step_id"])
    state["pending"]["step_id"] = packet["step_id"]
    result = asyncio.run(plan_client(tmp_path, Session([state])).run_plan("original-start", COMMAND, total_timeout=1))
    assert result["client_state"] == "review_required"
    assert result["result"]["review_packet"] == packet
    assert scene.inputs == ["compound_input"] and scene.approvals == []
    assert scene.jobs.get("field-job")["status"] == "awaiting_field_review"


@pytest.mark.parametrize("input_status", ["completed", "unknown", "failed"])
def test_field_continue_only_reaches_verified_full_step_review_without_intermediate_poll(tmp_path, input_status):
    prefix = field_plan(tmp_path)
    settled_input = deepcopy(prefix)
    packet = {key: deepcopy(prefix[key]) for key in (
        "run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity")}
    packet.update(schema="review_packet.v1", wait_id=prefix["wait"]["wait_id"], step_id="first",
        execution_request_id="input-first", evidence_refs=prefix["review_packet"]["evidence_refs"],
        evidence_set_sha256=prefix["review_packet"]["evidence_set_sha256"], assessment_round=0,
        after=prefix["review_packet"]["after"], original_input_status=input_status, action_executed=True,
        authorizes_action=False, automatic_retry_allowed=False)
    packet["packet_sha256"] = digest(packet)
    settled_input["review_packet"] = packet
    session = Session([prefix, settled_input])
    opened = plan_client(tmp_path, session)

    async def scenario():
        await opened.run_plan("original-start", COMMAND, total_timeout=1)
        return await opened.run_plan("explicit-field-continue", {"kind": "task_plan", "request": {
            "action": "continue", "run_id": prefix["run_id"], "wait_id": prefix["wait"]["wait_id"]}},
            total_timeout=1)

    if input_status != "completed":
        with pytest.raises(ValueError, match="stale_review_packet"):
            asyncio.run(scenario())
        return
    result = asyncio.run(scenario())
    assert result["client_state"] == "review_required"
    assert result["result"]["review_packet"] == packet
    assert result["active_command_id"] == "input-first" and result["result"]["history"] == []
    assert len(session.calls) == 2
