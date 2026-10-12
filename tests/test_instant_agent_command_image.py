"""公开图片入口只读取同一代理命令的原始前后图，不触发输入或截图。"""
import asyncio
import base64
from copy import deepcopy
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app.instant_mcp import InstantImageError, InstantSession, build_server, write_json


class Alive:
    def poll(self):
        return None


@pytest.fixture
def session(tmp_path):
    value = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path, allow_local_input=True)
    value.session = tmp_path / "session-image"
    for folder in ("commands", "responses", "agent-commands"):
        (value.session / folder).mkdir(parents=True)
    write_json(value.session / "report.json", {"phase": "ready"})
    value.process = Alive()
    return value


def frame(session, name, color):
    output = BytesIO()
    Image.new("RGB", (12, 9), color).save(output, format="PNG")
    data = output.getvalue()
    path = session.session / (name + ".png")
    path.write_bytes(data)
    return {"image_path": str(path), "sha256": hashlib.sha256(data).hexdigest()}, data


def recorded_agent(session, kind="click"):
    before, before_bytes = frame(session, "before", "blue")
    after, after_bytes = frame(session, "after", "green")
    observation = {"status": "captured", "capture": after, "source": "post_action"}
    local = {"contract_version": "local_direct_step_v1", "phase": "returned", "capture": before,
             "observation": observation, "response": {"success": True}}
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Open detail"}}
    progress = None
    if kind == "sequence":
        intermediate, _ = frame(session, "focus-after", "red")
        progress = {"contract_version": "input_sequence.v1", "status": "completed", "capture": before,
                    "observation": observation, "completed_steps": ["focus", "type", "submit"],
                    "steps": [{"name": "focus", "operation": "execute_recognition_plan", "receipt": {
                        **deepcopy(local), "observation": {"status": "captured", "capture": intermediate}}},
                        {"name": "type", "operation": "type_text", "receipt": deepcopy(local)},
                        {"name": "submit", "operation": "press_key", "receipt": deepcopy(local)}]}
        local = progress
        command = {"kind": "input_sequence", "request": {"field_goal": "Search", "text": "example",
                    "clear_existing": True, "submit_search": True}}
    accepted = {"contract_version": "agent_command.v1", "command_id": "child", "status": "running",
                "pending_grounding": None, "progress": None, "result": None,
                "observation": {"status": "not_requested", "capture": None}, "action_executed": False}
    response = {"command": command, "status": "returned", "result": accepted,
                "observation": {"status": "not_requested", "capture": None}}
    terminal = {**deepcopy(accepted), "status": "completed", "result": local, "progress": progress,
                "observation": observation, "action_executed": True}
    write_json(session._path("child", "commands"), command)
    write_json(session._path("child", "responses"), response)
    write_json(session._path("child", "agent-commands"), terminal)
    return response, terminal, {"before": before_bytes, "after": after_bytes}


@pytest.mark.parametrize("kind", ["click", "sequence"])
@pytest.mark.parametrize("view", ["before", "after"])
def test_child_image_reads_terminal_original_frame_without_rewriting_acceptance(session, kind, view):
    recorded_agent(session, kind)
    response_path = session._path("child", "responses")
    original = response_path.read_bytes()
    expected = (session.session / (view + ".png")).read_bytes()
    assert session.image("child", view) == expected
    assert response_path.read_bytes() == original
    assert sorted(p.stem for p in (session.session / "commands").glob("*.json")) == ["child"]


def test_public_image_tool_returns_exact_child_after_png(session):
    _, _, expected = recorded_agent(session)
    result = asyncio.run(build_server(session).call_tool("instant_image", {"request_id": "child", "view": "after"}))
    assert not result.is_error
    assert base64.b64decode(result.content[0].data) == expected["after"]


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
@pytest.mark.parametrize("view", ["before", "after"])
def test_outer_agent_control_image_uses_its_bound_child_snapshot(session, kind, view):
    _, terminal, expected = recorded_agent(session)
    command = {"kind": kind, "request": {"command_id": "child"}}
    write_json(session._path("outer", "commands"), command)
    write_json(session._path("outer", "responses"), {"command": command, "status": "returned",
        "result": terminal, "observation": {"status": "not_requested", "capture": None}})
    assert session.image("outer", view) == expected[view]
    assert not session._path("outer", "agent-commands").exists()


@pytest.mark.parametrize("view", ["before", "after"])
def test_original_acceptance_cannot_redirect_to_another_readable_agent_frame(session, view):
    response, terminal, _ = recorded_agent(session)
    response["result"] = {**terminal, "command_id": "another-child"}
    write_json(session._path("child", "responses"), response)
    with pytest.raises(InstantImageError) as caught:
        session.image("child", view)
    assert caught.value.code == "image_frame_unavailable"


@pytest.mark.parametrize("kind", ["click", "sequence"])
@pytest.mark.parametrize("case,code", [("missing", "image_frame_unavailable"),
    ("tampered", "image_digest_mismatch"), ("format", "image_format_invalid"),
    ("outside", "image_frame_unavailable")])
def test_child_after_rejects_missing_or_untrusted_evidence(session, kind, case, code):
    _, terminal, _ = recorded_agent(session, kind)
    capture = terminal["observation"]["capture"]
    path = Path(capture["image_path"])
    if case == "missing":
        terminal["observation"] = {"status": "unavailable", "capture": None}
        terminal["result"]["observation"] = {"status": "unavailable", "capture": None}
    elif case == "tampered":
        path.write_bytes((session.session / "before.png").read_bytes())
    elif case == "format":
        path.write_bytes(b"not a PNG")
        capture["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        outside = session.session.parent / "outside.png"
        outside.write_bytes(path.read_bytes())
        capture["image_path"] = str(outside)
    write_json(session._path("child", "agent-commands"), terminal)
    with pytest.raises(InstantImageError) as caught:
        session.image("child", "after")
    assert caught.value.code == code


@pytest.mark.parametrize("state,code", [("running", "image_request_pending"),
    ("wrong_identity", "image_frame_unavailable")])
def test_child_after_requires_bound_terminal_worker(session, state, code):
    _, terminal, _ = recorded_agent(session)
    if state == "running":
        terminal["status"] = "running"
    else:
        terminal["command_id"] = "another-child"
    write_json(session._path("child", "agent-commands"), terminal)
    with pytest.raises(InstantImageError) as caught:
        session.image("child", "after")
    assert caught.value.code == code


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("view", ["before", "after"])
def test_plain_receipt_keeps_original_capture_roles(session, wrapped, view):
    before, before_bytes = frame(session, "plain-before", "blue")
    after, after_bytes = frame(session, "plain-after", "green")
    response = {"status": "returned", "result": {"capture": before, "observation": {"capture": after}},
                "observation": {"status": "not_requested", "capture": None} if wrapped else after}
    write_json(session._path("plain", "responses"), response)
    assert session.image("plain", view) == {"before": before_bytes, "after": after_bytes}[view]
