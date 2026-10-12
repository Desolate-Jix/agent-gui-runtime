"""普通执行的新请求默认视觉；离线验证历史票据与学习边界。"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.instant_mcp import InstantCommand, InstantSession, build_server, write_json
from tests.test_execution_client import client
from tests.test_learning_benchmark_client import FakeSDK


COMMAND = {"kind": "input_sequence", "request": {
    "field_goal": "Search field", "text": "java", "submit_search": True}}


@pytest.fixture
def session(tmp_path):
    value = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path,
        allow_local_input=True)
    value.session = tmp_path / "session-test"
    for folder in ("commands", "responses"):
        (value.session / folder).mkdir(parents=True)
    write_json(value.session / "report.json", {"phase": "ready"})
    value.process = type("Alive", (), {"poll": lambda self: None})()
    return value


def test_new_public_input_is_deterministic_context_only_and_does_not_change_normalizer():
    from app.execution.public_input_defaults import adopt_public_input_command
    assert InstantCommand.model_validate(COMMAND).command() == COMMAND
    original = deepcopy(COMMAND)
    first = adopt_public_input_command("input-one", COMMAND)
    assert first == adopt_public_input_command("input-one", COMMAND)
    assert COMMAND == original and first["kind"] == "input_sequence"
    assert first["field_evidence_mode"] == "visual"
    assert first["request"] == {**COMMAND["request"], "clear_existing": True}
    context = first["action_review"]
    plan = context["plan"]
    assert plan["steps"][0]["action"] == {"kind": "input_sequence", **first["request"]}
    assert plan["steps"][0]["verification"] == {"kind": "agent_judgment"}
    assert "completion" not in plan
    assert InstantCommand.model_validate(first).command() == first
    assert adopt_public_input_command("input-one", COMMAND, existing_command=first) == first
    changed = deepcopy(COMMAND)
    changed["request"]["text"] = "python"
    with pytest.raises(ValueError, match="request_id.*different command"):
        adopt_public_input_command("input-one", changed, existing_command=first)


@pytest.mark.parametrize("change", [
    {"field_evidence_mode": "legacy"},
    {"request": {**COMMAND["request"], "target": {"control_type": "Edit", "name": "Search"}}},
    {"request": {**COMMAND["request"], "target_memory": {
        "recipe_id": "target-recipe-" + "a" * 64, "interface_key": "i", "state_key": "s"}}},
])
def test_explicit_native_or_memory_is_preserved(change):
    from app.execution.public_input_defaults import adopt_public_input_command
    command = {**deepcopy(COMMAND), **change}
    assert InstantCommand.model_validate(command).command() == command
    assert adopt_public_input_command("input-one", command) == command


def test_learning_and_old_ticket_keep_original_semantics():
    from app.execution.public_input_defaults import adopt_public_input_command
    assert adopt_public_input_command("input-one", COMMAND, learning_recording=True) == COMMAND
    assert adopt_public_input_command("input-one", COMMAND, existing_command=COMMAND) == COMMAND


def test_new_direct_request_is_deferred_to_empty_check_and_old_routes_remain():
    from app.execution.public_input_defaults import adopt_public_input_command
    command = deepcopy(COMMAND)
    command["request"]["clear_existing"] = False
    adopted = adopt_public_input_command("input-one", command)
    assert adopted["field_evidence_mode"] == "visual"
    assert adopted["request"]["clear_existing"] is False
    assert adopt_public_input_command("input-one", command, existing_command=command) == command
    native = {**command, "field_evidence_mode": "legacy"}
    assert adopt_public_input_command("input-one", native) == native


def test_session_adopts_only_new_ticket_and_same_id_never_replays(session):
    assert session.submit("input-one", COMMAND)["status"] == "pending"
    path = session._path("input-one", "commands")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["field_evidence_mode"] == "visual"
    before = path.stat().st_mtime_ns
    assert session.submit("input-one", COMMAND)["status"] == "pending"
    assert path.stat().st_mtime_ns == before
    changed = deepcopy(COMMAND)
    changed["request"]["text"] = "python"
    with pytest.raises(ValueError, match="different command"):
        session.submit("input-one", changed)
    assert json.loads(path.read_text(encoding="utf-8")) == stored


def test_session_old_ticket_and_active_learning_do_not_gain_context(session):
    write_json(session._path("old-input", "commands"), COMMAND)
    write_json(session._path("old-input", "responses"), {"status": "returned", "command": COMMAND})
    assert session.submit("old-input", COMMAND)["status"] == "returned"
    from app.learning_memory.event_store import LearningEventStore
    LearningEventStore(session.session).control("learning_start", {"scope": "interface", "title": "Learning"}, "learn-one")
    assert session.submit("learning-input", COMMAND)["status"] == "pending"
    assert json.loads(session._path("learning-input", "commands").read_text(encoding="utf-8")) == COMMAND


def test_direct_input_enters_visual_queue_without_changing_clear_mode(session):
    command = deepcopy(COMMAND)
    command["request"]["clear_existing"] = False
    result = asyncio.run(build_server(session).call_tool("instant_submit", {
        "request_id": "append-one", "command": command}))
    value = json.loads(result.content[0].text)
    assert not result.is_error and value["status"] == "pending"
    queued = json.loads(session._path("append-one", "commands").read_text(encoding="utf-8"))
    assert queued["field_evidence_mode"] == "visual"
    assert queued["request"]["clear_existing"] is False


def test_execution_client_adopts_new_request_and_repeated_id_only_reads(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            first = await opened.execute({"request_id": "input-one", "command": COMMAND})
            second = await opened.execute({"request_id": "input-one", "command": COMMAND})
            assert first["original_request_id"] == second["original_request_id"] == "input-one"
            changed = deepcopy(COMMAND)
            changed["request"]["text"] = "python"
            with pytest.raises(ValueError, match="request_id_conflict"):
                await opened.execute({"request_id": "input-one", "command": changed})

    asyncio.run(scenario())
    submits = [args for name, args in sdk.calls if name == "instant_run"]
    assert len(submits) == 1 and submits[0]["request_id"] == "input-one"
    assert submits[0]["command"]["field_evidence_mode"] == "visual"


def test_reconnected_execution_client_reads_existing_old_ticket(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            directory = opened.data_root / "session-old"
            (directory / "commands").mkdir(parents=True)
            write_json(directory / "commands" / "input-old.json", COMMAND)
            opened._status["session_directory"] = str(directory)
            result = await opened.execute({"request_id": "input-old", "command": COMMAND})
            assert result["request_id"] == "input-old"

    asyncio.run(scenario())
    assert not any(name == "instant_run" for name, _ in sdk.calls)
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["input-old"]


def test_execution_client_preserves_native_learning_and_queues_direct_input_for_empty_check(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            native = {**deepcopy(COMMAND), "field_evidence_mode": "legacy"}
            await opened.execute({"request_id": "native-one", "command": native})
            append = deepcopy(COMMAND)
            append["request"]["clear_existing"] = False
            await opened.execute({"request_id": "append-one", "command": append})
            directory = opened.data_root / "session-learning"
            directory.mkdir(parents=True)
            from app.learning_memory.event_store import LearningEventStore
            LearningEventStore(directory).control("learning_start", {"scope": "interface", "title": "Learning"}, "learn-one")
            opened._status["session_directory"] = str(directory)
            await opened.execute({"request_id": "learning-one", "command": COMMAND})

    asyncio.run(scenario())
    submits = {args["request_id"]: args["command"] for name, args in sdk.calls if name == "instant_run"}
    direct = submits.pop("append-one")
    assert direct["request"]["clear_existing"] is False and direct["field_evidence_mode"] == "visual"
    assert submits == {"native-one": {**COMMAND, "field_evidence_mode": "legacy"}, "learning-one": COMMAND}


UNAFFECTED_COMMANDS = [
    {"kind": "discover"},
    {"kind": "select", "handle": 7, "process_id": 9},
    {**COMMAND, "field_evidence_mode": "legacy"},
    {"kind": "input_sequence", "request": {**COMMAND["request"],
        "target": {"control_type": "Edit", "name": "Search"}}},
    {"kind": "input_sequence", "request": {**COMMAND["request"], "target_memory": {
        "recipe_id": "target-recipe-" + "a" * 64, "interface_key": "i", "state_key": "s"}}},
]


def corrupt_learning_state(directory):
    path = directory / "learning-memory" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")


@pytest.mark.parametrize("command", UNAFFECTED_COMMANDS + [COMMAND])
def test_corrupt_learning_state_does_not_change_native_unrelated_or_historical_session_request(session, command):
    corrupt_learning_state(session.session)
    if command == COMMAND:
        write_json(session._path("same-id", "commands"), command)
    assert session.submit("same-id", command)["status"] == "pending"
    assert json.loads(session._path("same-id", "commands").read_text(encoding="utf-8")) == command


@pytest.mark.parametrize("command", UNAFFECTED_COMMANDS + [COMMAND])
def test_corrupt_learning_state_does_not_change_native_unrelated_or_historical_client_request(tmp_path, command):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            directory = opened.data_root / "session-corrupt"
            corrupt_learning_state(directory)
            opened._status["session_directory"] = str(directory)
            if command == COMMAND:
                (directory / "commands").mkdir()
                write_json(directory / "commands" / "same-id.json", command)
            return await opened.execute({"request_id": "same-id", "command": command})

    assert asyncio.run(scenario())["request_id"] == "same-id"
    submits = [args for name, args in sdk.calls if name == "instant_run"]
    assert [(args["request_id"], args["command"]) for args in submits] == (
        [] if command == COMMAND else [("same-id", command)])


def test_new_ordinary_session_input_surfaces_corrupt_learning_json_without_queue(session):
    corrupt_learning_state(session.session)
    with pytest.raises(json.JSONDecodeError):
        session.submit("new-input", COMMAND)
    assert not session._path("new-input", "commands").exists()


def test_new_ordinary_client_input_surfaces_corrupt_learning_json_without_transport(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            directory = opened.data_root / "session-corrupt"
            corrupt_learning_state(directory)
            opened._status["session_directory"] = str(directory)
            with pytest.raises(json.JSONDecodeError):
                await opened.execute({"request_id": "new-input", "command": COMMAND})

    asyncio.run(scenario())
    assert not any(name == "instant_run" for name, _ in sdk.calls)
