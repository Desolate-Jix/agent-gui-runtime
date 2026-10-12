"""只读观察的公共契约与审核版本推进，不调用桌面或远端模型。"""
import asyncio
from copy import deepcopy

import pytest

from app.execution.task_plan_admission import validate_task_plan_request
from app.execution.task_plan_review import digest
from app.instant_mcp import InstantCommand
from tests.test_task_plan_client import Session, client, snapshot


def observe_request():
    return {"action": "observe", "run_id": "trial-" + "a" * 64,
        "step_id": "first", "execution_request_id": "input-first", "wait_id": "wait-first",
        "observation_request_id": "main-look-one", "review_packet_sha256": "b" * 64,
        "evidence_set_sha256": "c" * 64, "assessment_round": 0}


def test_public_observe_contract_accepts_bound_read_only_request():
    request = observe_request()
    assert validate_task_plan_request(request) == request
    assert InstantCommand.model_validate({"kind": "task_plan", "request": request}).command()["request"] == request


@pytest.mark.parametrize("field", list(observe_request()))
def test_public_observe_contract_requires_every_binding(field):
    request = observe_request()
    del request[field]
    with pytest.raises(ValueError):
        validate_task_plan_request(request)


@pytest.mark.parametrize(("field", "value"), [
    ("observation_request_id", "../retry"), ("observation_request_id", ""),
    ("assessment_round", True), ("assessment_round", -1),
    ("review_packet_sha256", "wrong"), ("evidence_set_sha256", "wrong"), ("click", True),
])
def test_public_observe_contract_rejects_malformed_or_input_fields(field, value):
    request = observe_request()
    request[field] = value
    with pytest.raises(ValueError):
        validate_task_plan_request(request)


def waiting_snapshot():
    value = snapshot(reason="verification_required")
    refs = [{"path": "captures/original.png", "sha256": "e" * 64}]
    packet = {key: deepcopy(value[key]) for key in
        ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity")}
    packet.update(schema="review_packet.v1", wait_id=value["wait"]["wait_id"], step_id="first",
        execution_request_id="input-first", evidence_refs=refs, evidence_set_sha256=digest(refs),
        assessment_round=0, after={"sha256": "e" * 64}, original_input_status="completed",
        action_executed=True, authorizes_action=False, automatic_retry_allowed=False)
    packet["packet_sha256"] = digest(packet)
    value.update(review_packet=packet, review_required=True)
    return value


def revised_snapshot(previous):
    value = deepcopy(previous)
    old = previous["review_packet"]
    packet = value["review_packet"]
    refs = deepcopy(old.get("input_evidence_refs", old["evidence_refs"]))
    refs.append({"path": "task-plan-observations/manual-one.png", "sha256": "f" * 64})
    packet.update(schema="review_packet.v3", packet_revision=old.get("packet_revision", 0) + 1,
        previous_packet_sha256=old["packet_sha256"],
        packet_ancestors=[*old.get("packet_ancestors", []), old["packet_sha256"]],
        latest_observation={"role": "observation", "capture_id": "manual-one", "sha256": "f" * 64},
        assessment_basis=old.get("assessment_basis", {"packet_sha256": old["packet_sha256"],
            "evidence_set_sha256": old["evidence_set_sha256"], "assessment_round": old["assessment_round"]}),
        input_evidence_refs=refs, evidence_set_sha256=digest(refs), evidence_refs=deepcopy(refs),
        artifact_refs=deepcopy(refs), artifact_set_sha256=digest(refs))
    packet["packet_sha256"] = digest({key: item for key, item in packet.items() if key != "packet_sha256"})
    return value


def test_client_accepts_new_evidence_once_without_repeating_main_callback(tmp_path):
    old = waiting_snapshot()
    new = revised_snapshot(old)
    session = Session([old, new, new])
    opened = client(tmp_path, session, allow_actions=False)
    events = []
    request = {"action": "status", "run_id": old["run_id"]}
    async def scenario():
        for name in ("first-status", "new-evidence-status", "same-evidence-status"):
            await opened.run_plan(name, {"kind": "task_plan", "request": request}, event_callback=events.append)
    asyncio.run(scenario())
    assert len(events) == 2
    assert events[0]["result"]["review_packet"]["after"] == events[1]["result"]["review_packet"]["after"]
    assert [name for name, _ in session.calls] == ["instant_run"] * 3


@pytest.mark.parametrize("damage", ["ancestor", "revision", "after", "round", "missing_old_evidence", "downgrade"])
def test_client_rejects_packet_replacement_without_valid_evidence_lineage(tmp_path, damage):
    old = waiting_snapshot()
    new = revised_snapshot(old)
    p = new["review_packet"]
    if damage == "ancestor":
        p["packet_ancestors"] = ["0" * 64]
        p["previous_packet_sha256"] = "0" * 64
    elif damage == "revision":
        p["packet_revision"] = 2
    elif damage == "after":
        p["after"]["sha256"] = "0" * 64
    elif damage == "round":
        p["assessment_round"] = 1
    elif damage == "missing_old_evidence":
        p["input_evidence_refs"] = p["input_evidence_refs"][1:]
        p["evidence_set_sha256"] = digest(p["input_evidence_refs"])
    p["packet_sha256"] = digest({key: item for key, item in p.items() if key != "packet_sha256"})
    first, second = (revised_snapshot(old), old) if damage == "downgrade" else (old, new)
    opened = client(tmp_path, Session([]))
    opened._plan_snapshot(first, run_id=None, start_request_id=None, previous=None)
    with pytest.raises(ValueError, match="review_packet"):
        opened._plan_snapshot(second, run_id=None, start_request_id=None, previous=first)


def test_client_submits_observe_without_requiring_input_permission(tmp_path):
    old = waiting_snapshot()
    new = revised_snapshot(old)
    session = Session([new])
    opened = client(tmp_path, session, allow_actions=False)
    request = {**observe_request(), "run_id": old["run_id"], "wait_id": old["wait"]["wait_id"],
        "review_packet_sha256": old["review_packet"]["packet_sha256"],
        "evidence_set_sha256": old["review_packet"]["evidence_set_sha256"]}
    result = asyncio.run(opened.run_plan("look-transport", {"kind": "task_plan", "request": request}))
    assert result["client_state"] == "review_required"
    assert session.calls[0][1]["command"]["request"] == request
    assert len(session.calls) == 1


def test_manual_result_exposes_current_observation_image_separately(tmp_path):
    state = revised_snapshot(waiting_snapshot())
    state["manual_observation"] = {"status": "captured", "observation_request_id": "logical-one",
        "packet_sha256": state["review_packet"]["packet_sha256"]}
    opened = client(tmp_path, Session([state]), allow_actions=False)
    result = asyncio.run(opened.run_plan("manual-control", {"kind": "task_plan",
        "request": {"action": "status", "run_id": state["run_id"]}}))
    assert result["observation_image"]["tool"] == "instant_result"
    assert result["observation_image"]["arguments"] == {
        "request_id": "manual-control", "detail": "full", "images": "after"}
    assert result["observation_image"]["role"] == "observation"
    assert result["images"][0]["arguments"]["request_id"] == "input-first"


def video_snapshot(schema="video_playback_binding.v1"):
    value = waiting_snapshot()
    packet = value["review_packet"]
    inputs = deepcopy(packet["evidence_refs"])
    ledger = [{"path": "task-plan-video/input-first/0000.json", "sha256": "a" * 64}]
    artifacts = [*inputs, *ledger]
    video = {"schema": schema, "execution_request_id": "input-first",
        "ledger_refs": ledger, "ledger_sha256": digest(ledger), "input_evidence_refs": inputs,
        "evidence_set_sha256": digest(inputs), "samples": [], "region": None, "analysis": None,
        "assessment_round": 0, "assessment_ref": None, "original_receipt_sha256": "b" * 64, "elapsed_ms": 0}
    packet.update(schema="review_packet.v4", video_playback=video, input_evidence_refs=inputs,
        evidence_refs=artifacts, artifact_refs=deepcopy(artifacts), artifact_set_sha256=digest(artifacts),
        original_receipt_sha256="b" * 64, assessment_ref=None)
    packet["packet_sha256"] = digest({key: item for key, item in packet.items() if key != "packet_sha256"})
    return value


@pytest.mark.parametrize("schema", ["video_playback_binding.v1", "video_playback_binding.v2", "dynamic_content_binding.v1"])
def test_video_v4_client_projects_once_and_continues_original_wait(tmp_path, schema):
    from tests.test_task_plan_client import reviewed_original_snapshot, snapshot
    waiting = video_snapshot(schema)
    reviewed = reviewed_original_snapshot()
    reviewed["history"][0]["reason"] = "reviewed playback evidence"
    final = snapshot(completed=2)
    final["history"][0] = deepcopy(reviewed["history"][0])
    session = Session([waiting, waiting, reviewed, final])
    opened = client(tmp_path, session)
    events = []
    async def exercise():
        status = {"kind": "task_plan", "request": {"action": "status", "run_id": waiting["run_id"]}}
        first = await opened.run_plan("video-status", status, event_callback=events.append)
        assert first["client_state"] == "review_required"
        assert first["result"]["review_packet"] == waiting["review_packet"]
        assert first["video_playback_images"]["arguments"] == {
            "request_id": "video-status", "detail": "full", "images": "after"}
        assert first["images"][0]["arguments"] == {"request_id": "input-first", "view": "after"}
        await opened.run_plan("video-status-again", status, event_callback=events.append)
        assert len(events) == 1
        review = {"action": "review", "run_id": waiting["run_id"], "execution_request_id": "input-first",
            "step_id": "first", "verdict": "success", "reason": "reviewed playback evidence"}
        settled = await opened.run_plan("original-review", {"kind": "task_plan", "request": review})
        assert settled["client_state"] == "continue_required" and settled["wait_id"] == first["wait_id"]
        return await opened.run_plan("original-continue", {"kind": "task_plan", "request": {
            "action": "continue", "run_id": waiting["run_id"], "wait_id": first["wait_id"]}})
    result = asyncio.run(exercise())
    assert result["client_state"] == "terminal"
    assert [args["command"]["request"]["action"] for name, args in session.calls] == ["status", "status", "review", "continue"]


@pytest.mark.parametrize("damage", ["execution", "inputs", "evidence_hash", "round", "assessment", "receipt", "ledger", "artifact"])
@pytest.mark.parametrize("schema", ["video_playback_binding.v1", "video_playback_binding.v2", "dynamic_content_binding.v1"])
def test_video_v4_client_rejects_rehashed_cross_binding_packet(tmp_path, damage, schema):
    state = video_snapshot(schema)
    packet, video = state["review_packet"], state["review_packet"]["video_playback"]
    if damage == "execution":
        video["execution_request_id"] = "another-input"
    elif damage == "inputs":
        video["input_evidence_refs"] = []
    elif damage == "evidence_hash":
        video["evidence_set_sha256"] = "0" * 64
    elif damage == "round":
        video["assessment_round"] = 1
    elif damage == "assessment":
        video["assessment_ref"] = {"path": "other.json", "sha256": "0" * 64}
    elif damage == "receipt":
        video["original_receipt_sha256"] = "0" * 64
    elif damage == "ledger":
        video["ledger_sha256"] = "0" * 64
    else:
        packet["artifact_refs"] = packet["evidence_refs"] = packet["input_evidence_refs"]
        packet["artifact_set_sha256"] = digest(packet["artifact_refs"])
    packet["packet_sha256"] = digest({key: item for key, item in packet.items() if key != "packet_sha256"})
    with pytest.raises(ValueError, match="review_packet"):
        client(tmp_path, Session([]))._plan_snapshot(state, run_id=None, start_request_id=None, previous=None)
