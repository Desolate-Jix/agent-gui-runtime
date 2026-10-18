"""即时桥接的无输入协议、幂等和证据回归。"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app.instant_mcp import InstantCommand, InstantSession, build_server, write_json


class Alive:
    def poll(self):
        return None


@pytest.fixture
def session(tmp_path):
    s = InstantSession(Path(__file__).resolve().parents[1], tmp_path, tmp_path, allow_local_input=True)
    s.session = tmp_path / "session-test"
    for folder in ("commands", "responses"):
        (s.session / folder).mkdir(parents=True)
    write_json(s.session / "report.json", {"phase": "ready"})
    s.process = Alive()
    return s


def test_server_schema_builds(session):
    assert build_server(session).name == "agent-review-instant"


@pytest.mark.parametrize("allow_input,missing_model,code", [
    (True, True, "model_directory_unavailable"),
    (False, False, "local_input_not_enabled"),
])
def test_start_preflight_error_is_actionable_without_launch(tmp_path, allow_input, missing_model, code):
    import asyncio
    model = tmp_path / "private-model-path" if missing_model else tmp_path
    data = tmp_path / "data"
    s = InstantSession(Path(__file__).resolve().parents[1], data, model, allow_local_input=allow_input)
    result = asyncio.run(build_server(s).call_tool("instant_start", {"new_session": True}))
    assert result.is_error
    value = json.loads(result.content[0].text)
    assert value["status"] == "start_rejected"
    assert value["error"]["code"] == code
    assert value["host_launch_attempted"] is False
    assert value["automatic_retry_allowed"] is False and value["next"]
    assert s.process is None and s.session is None and s.lock_file is None
    log = (data / "startup-errors.jsonl").read_text(encoding="utf-8")
    assert json.loads(log)["error"]["code"] == code
    assert "private-model-path" not in log and "private-model-path" not in result.content[0].text
    assert not list(data.glob("session-*"))


def test_start_preflight_reports_log_failure_without_hiding_root_error(tmp_path):
    import asyncio
    data = tmp_path / "not-a-directory"
    data.write_text("preserve", encoding="utf-8")
    s = InstantSession(tmp_path, data, tmp_path / "missing", allow_local_input=True)
    result = asyncio.run(build_server(s).call_tool("instant_start", {}))
    value = json.loads(result.content[0].text)
    assert result.is_error and value["error"]["code"] == "model_directory_unavailable"
    assert value["diagnostic_log_error"] == "FileExistsError"
    assert data.read_text(encoding="utf-8") == "preserve"


def test_start_success_keeps_status_shape(session):
    import asyncio
    try:
        result = asyncio.run(build_server(session).call_tool("instant_start", {}))
        assert not result.is_error
        value = json.loads(result.content[0].text)
        assert value["phase"] == "ready" and value["host_alive"] is True
        assert "host_launch_attempted" not in value
    finally:
        if session.lock_file:
            session.lock_file.close()


def test_unexpected_start_failure_is_not_misreported_as_preflight(session, monkeypatch):
    import asyncio
    from mcp.server.mcpserver.exceptions import UnexpectedToolError

    def failed_launch(**kwargs):
        raise OSError("launch state unknown")

    monkeypatch.setattr(session, "start", failed_launch)
    with pytest.raises(UnexpectedToolError):
        asyncio.run(build_server(session).call_tool("instant_start", {}))
    assert not (session.data_root / "startup-errors.jsonl").exists()


def test_close_launched_window_requires_explicit_identity_and_queues_once(session):
    import asyncio
    server = build_server(session)
    command = {'kind': 'close_launched_window', 'handle': 123, 'process_id': 456}
    result = asyncio.run(server.call_tool('instant_submit', {'request_id': 'close-app', 'command': command}))
    assert not result.is_error
    assert json.loads(result.content[0].text)['status'] == 'pending'
    assert json.loads(session._path('close-app', 'commands').read_text(encoding='utf-8')) == command
    assert not (session.session / 'closing.json').exists()


@pytest.mark.parametrize('command', [
    {'kind': 'close_launched_window'},
    {'kind': 'close_launched_window', 'handle': 123},
    {'kind': 'close_launched_window', 'handle': 123, 'process_id': 456, 'url': 'https://example.org'},
])
def test_close_launched_window_invalid_shape_never_queues(session, command):
    import asyncio
    result = asyncio.run(build_server(session).call_tool('instant_submit', {
        'request_id': 'close-invalid', 'command': command}))
    assert result.is_error
    assert json.loads(result.content[0].text)['status'] == 'validation_rejected'
    assert not list((session.session / 'commands').glob('*.json'))


def test_close_pending_is_not_reported_as_completed(session):
    write_json(session._path('close-app', 'responses'), {'status': 'returned', 'result': {
        'status': 'window_close_pending', 'success': False, 'close_requested': True}})
    assert session.result('close-app')['operation_succeeded'] is False


def test_protocol_validation_does_not_initialize_windows_com_in_worker():
    import os
    import subprocess
    import sys
    probe = """
import json, sys
from concurrent.futures import ThreadPoolExecutor
from app.instant_mcp import InstantCommand
commands = [
    {"kind": "step", "operation": "type_text", "request": {
        "text": "probe", "x": 10, "y": 20, "click_before_typing": True}},
    {"kind": "step", "operation": "press_key", "request": {"key": "Enter", "x": 10, "y": 20}},
    {"kind": "step", "operation": "scroll", "request": {"direction": "down", "x": 10, "y": 20}},
    {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Click Search"}},
]
with ThreadPoolExecutor(max_workers=1) as pool:
    results = list(pool.map(lambda command: InstantCommand.model_validate(command).command(), commands))
print(json.dumps({"count": len(results), "windows_modules": sorted(
    name for name in sys.modules if name.split('.')[0] in {"pywinauto", "comtypes"})}))
"""
    result = subprocess.run([sys.executable, "-c", probe], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, capture_output=True, text=True,
        encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["count"] == 4
    assert value["windows_modules"] == []


def test_invalid_step_is_readable_logged_and_host_reusable(session):
    import asyncio
    server = build_server(session)
    command = {"kind": "step", "operation": "type_text", "request": {
        "text": "private-value", "x": 1, "y": 1, "click_before_typing": True,
        "submit": True}}
    result = asyncio.run(server.call_tool("instant_submit", {"request_id": "bad", "command": command}))
    assert result.is_error
    value = json.loads(result.content[0].text)
    assert value["error"]["invalid_fields"] == ["submit"]
    assert "text" in value["error"]["allowed_fields"]
    assert value["accepted"] is False and value["action_executed"] is False
    log = (session.session / "validation-errors.jsonl").read_text(encoding="utf-8")
    assert "private-value" not in log and "private-value" not in result.content[0].text
    assert not list((session.session / "commands").glob("*.json"))
    assert session.status()["host_alive"]
    del command["request"]["submit"]
    fixed = asyncio.run(server.call_tool("instant_submit", {"request_id": "bad", "command": command}))
    assert not fixed.is_error
    assert json.loads(fixed.content[0].text)["status"] == "pending"
    assert len(list((session.session / "commands").glob("*.json"))) == 1


def test_invalid_step_value_does_not_echo_private_input(session):
    import asyncio
    result = asyncio.run(build_server(session).call_tool("instant_submit", {"request_id": "bad",
        "command": {"kind": "step", "operation": "press_key", "request": {
            "key": "private-value", "x": 1, "y": 1}}}))
    assert result.is_error
    assert "private-value" not in result.content[0].text
    assert not list((session.session / "commands").glob("*.json"))


def test_unknown_fields_are_named(session):
    import asyncio
    result = asyncio.run(build_server(session).call_tool("instant_submit", {"request_id": "bad",
        "command": {"kind": "step", "operation": "press_key", "request": {
            "key": "Enter", "x": 1, "y": 1, "invented_field": "private-value"}}}))
    assert result.is_error
    value = json.loads(result.content[0].text)
    assert value["error"]["unknown_fields"] == ["invented_field"]
    assert "key" in value["error"]["allowed_fields"]
    assert "private-value" not in result.content[0].text


def test_local_enable_is_not_agent_argument(tmp_path):
    s = InstantSession(tmp_path, tmp_path, tmp_path)
    with pytest.raises(ValueError, match="explicitly"):
        s.start()


def test_single_pending_and_no_replay(session):
    first = session.submit("a", {"kind": "capture"})
    assert first["status"] == "pending"
    assert session.submit("a", {"kind": "capture"})["status"] == "pending"
    with pytest.raises(ValueError, match="different"):
        session.submit("a", {"kind": "maximize"})
    with pytest.raises(ValueError, match="pending"):
        session.submit("b", {"kind": "capture"})
    write_json(session._path("a", "responses"), {"status": "returned", "result": {"status": "ok"}})
    assert session.submit("a", {"kind": "capture"})["operation_succeeded"] is True
    assert len(list((session.session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("state,code,next_tool", [
    ("starting", "host_not_ready", "instant_status"),
    ("pending", "command_pending", "instant_result"),
    ("closing", "session_closing", "instant_status"),
])
def test_admission_state_error_is_structured_and_does_not_queue(session, state, code, next_tool):
    import asyncio
    if state == "starting":
        write_json(session.session / "report.json", {"phase": "starting"})
    elif state == "pending":
        session.submit("prior", {"kind": "discover"})
    else:
        write_json(session.session / "closing.json", {"request_id": "close-test"})
    before = sorted(p.name for p in (session.session / "commands").glob("*.json"))
    server = build_server(session)
    result = asyncio.run(server.call_tool("instant_submit", {
        "request_id": "new", "command": {"kind": "discover"}}))
    assert result.is_error
    response = json.loads(result.content[0].text)
    assert response["status"] == "state_rejected" and response["accepted"] is False
    assert response["action_executed"] is False and response["automatic_retry_allowed"] is False
    assert response["error"]["code"] == code
    assert response["next"]["tool"] == next_tool
    if state == "pending":
        assert response["next"]["arguments"] == {"request_id": "prior"}
    assert sorted(p.name for p in (session.session / "commands").glob("*.json")) == before
    if state == "starting":
        write_json(session.session / "report.json", {"phase": "ready"})
        fixed = asyncio.run(server.call_tool("instant_submit", {
            "request_id": "new", "command": {"kind": "discover"}}))
        assert not fixed.is_error
        assert json.loads(fixed.content[0].text)["status"] == "pending"


def test_queue_write_error_is_not_misreported_as_safe_rejection(session, monkeypatch):
    import asyncio
    def failed_write(path, value):
        raise OSError("uncertain write outcome")
    monkeypatch.setattr("app.instant_mcp.write_json", failed_write)
    with pytest.raises(Exception, match="instant_submit|uncertain write"):
        asyncio.run(build_server(session).call_tool("instant_submit", {
            "request_id": "new", "command": {"kind": "discover"}}))


def test_concurrent_same_id(session):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: session.submit("a", {"kind": "capture"}), range(16)))
    assert all(x["status"] == "pending" for x in results)
    assert len(list((session.session / "commands").glob("*.json"))) == 1


@pytest.mark.parametrize("request_id", ["../bad", "", "Upper", "a/b", "a" * 81])
def test_invalid_ids(session, request_id):
    with pytest.raises(ValueError):
        session.result(request_id)


@pytest.mark.parametrize("command", [
    {"kind": "capture", "url": "https://example.com"},
    {"kind": "launch"}, {"kind": "select", "handle": 1},
    {"kind": "step", "operation": "press_key", "request": {"key": "UnsupportedKey", "x": 1, "y": 1}},
    {"kind": "step", "operation": "type_text", "request": {"text": "x", "x": 1, "y": 1, "click_before_typing": True, "submit": True}},
    {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "click", "image_path": "old.png"}},
    {"kind": "capture", "automatic_safety_interception": False},
])
def test_invalid_commands(command):
    with pytest.raises(ValueError):
        InstantCommand.model_validate(command).command()


@pytest.mark.parametrize("replace", [False, True])
def test_text_replace_option_reaches_queue_without_implicit_submit(session, replace):
    import asyncio
    result = asyncio.run(build_server(session).call_tool("instant_submit", {
        "request_id": "fill", "command": {"kind": "step", "operation": "type_text", "request": {
            "text": "new value", "x": 40, "y": 60, "click_before_typing": True,
            "clear_existing": replace}}}))
    assert not result.is_error
    command = json.loads(session._path("fill", "commands").read_text(encoding="utf-8"))
    assert command["request"]["clear_existing"] is replace
    assert command["request"].get("submit", False) is False
    assert command["request"]["text"] == "new value"


@pytest.mark.parametrize("key", ["Enter", "Tab", "Shift+Tab", "Escape", "Backspace", "Delete",
    "Left", "Right", "Up", "Down", "Home", "End", "Ctrl+A", "Ctrl+Z", "Ctrl+Y",
    "Shift+Left", "Shift+Right", "Shift+Up", "Shift+Down", "Shift+Home", "Shift+End", "Ctrl+Home", "Ctrl+End"])
def test_editing_key_tool_admission_persists_one_command(session, key):
    import asyncio
    server = build_server(session)
    result = asyncio.run(server.call_tool("instant_submit", {
        "request_id": "edit-key", "command": {"kind": "step", "operation": "press_key",
            "request": {"key": key, "x": 40, "y": 60}}}))
    assert not result.is_error
    command = json.loads(session._path("edit-key", "commands").read_text(encoding="utf-8"))
    assert command["request"] == {"key": key, "x": 40, "y": 60}
    assert len(list((session.session / "commands").glob("*.json"))) == 1
    tools = asyncio.run(server.list_tools())
    description = next(tool.description for tool in tools if tool.name == "instant_submit")
    assert key in description
    assert "CURRENT FOCUS" in description


def test_backend_failure_not_success(session):
    write_json(session._path("a", "responses"), {"status": "returned", "command": {"text": "secret"},
        "result": {"phase": "result_unknown", "request": {"text": "secret"}, "response": {"success": False}}})
    value = session.result("a")
    assert not value["operation_succeeded"] and not value["automatic_retry_allowed"]
    assert "secret" not in json.dumps(value)


@pytest.mark.parametrize("result", [
    {"status": "launched_window_unavailable", "window": None, "reason": "launched_window_ambiguous", "result_unknown": True},
    {"status": "launched_window_ready", "window": None},
    {"status": "focused", "window": {"handle": 5, "process_id": False}},
    {"status": "maximized", "window": {"handle": 0, "process_id": 10}},
    {"phase": "failed"},
    {"result_unknown": True},
])
def test_returned_is_not_semantic_success(session, result):
    write_json(session._path("failed-launch", "responses"), {"status": "returned", "result": result})
    received = session.result("failed-launch")
    assert received["status"] == "returned"
    assert received["operation_succeeded"] is False
    assert received["automatic_retry_allowed"] is False


@pytest.mark.parametrize("status", ["launched_window_ready", "focused", "maximized"])
def test_window_success_requires_bound_window(session, status):
    write_json(session._path("window", "responses"), {"status": "returned", "result": {
        "status": status, "window": {"handle": 5, "process_id": 10}}})
    assert session.result("window")["operation_succeeded"] is True


def test_image_original_and_digest(session):
    path = session.session / "image.png"
    data = b"\x89PNG\r\n\x1a\nexample"
    path.write_bytes(data)
    write_json(session._path("a", "responses"), {"status": "returned", "observation": {
        "image_path": str(path), "sha256": hashlib.sha256(data).hexdigest()}})
    assert session.image("a") == data
    path.write_bytes(data + b"changed")
    with pytest.raises(ValueError, match="digest"):
        session.image("a")


def test_image_cannot_read_outside_session(session):
    path = session.data_root / "private.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    write_json(session._path("a", "responses"), {"status": "returned", "observation": {"image_path": str(path)}})
    with pytest.raises(ValueError):
        session.image("a")


def test_close_ack_is_not_cleanup(session):
    assert session.stop()["cleanup_verified"] is False
    with pytest.raises(ValueError):
        session.submit("b", {"kind": "capture"})


def test_data_directory_exclusive_lock(tmp_path):
    a = InstantSession(tmp_path, tmp_path, tmp_path)
    b = InstantSession(tmp_path, tmp_path, tmp_path)
    try:
        a._lock()
        with pytest.raises(ValueError, match="another MCP"):
            b._lock()
    finally:
        a.close()
        b.close()


def test_reconnect_reads_original_receipt(tmp_path):
    name = "session-" + "a" * 32
    directory = tmp_path / name
    (directory / "responses").mkdir(parents=True)
    (directory / "commands").mkdir()
    write_json(tmp_path / "latest-session.json", {"name": name, "host_identity": None})
    write_json(directory / "commands/old.json", {"kind": "capture"})
    write_json(directory / "responses/old.json", {"status": "returned", "result": {"status": "old"}})
    write_json(directory / "report.json", {"phase": "stopped", "host_phase": "stopped",
        "finished_at": "then", "cleanup_errors": [], "sampler_stopped": True})
    s = InstantSession(tmp_path, tmp_path, tmp_path, allow_local_input=True)
    try:
        assert s.start()["cleanup_verified"]
        assert s.submit("old", {"kind": "capture"})["result"]["status"] == "old"
        with pytest.raises(ValueError, match="not ready"):
            s.submit("new", {"kind": "capture"})
        assert len(list((directory / "commands").glob("*.json"))) == 1
    finally:
        s.close()


def test_mcp_image_content_uses_original_bytes(session):
    import asyncio
    import base64
    from io import BytesIO
    from PIL import Image
    out = BytesIO()
    Image.new("RGB", (12, 9), "blue").save(out, format="PNG")
    raw = out.getvalue()
    path = session.session / "original.png"
    path.write_bytes(raw)
    write_json(session._path("a", "responses"), {"status": "returned", "observation": {
        "image_path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}})
    result = asyncio.run(build_server(session).call_tool("instant_image", {"request_id": "a"}))
    assert not result.is_error
    assert result.content[0].mime_type == "image/png"
    assert base64.b64decode(result.content[0].data) == raw


def test_agent_review_returns_both_original_frames_without_input(session):
    import asyncio
    import base64
    from io import BytesIO
    from PIL import Image
    frames = {}
    expected = {}
    for view, color in [('before', 'blue'), ('after', 'green')]:
        out = BytesIO()
        Image.new('RGB', (12, 9), color).save(out, format='PNG')
        expected[view] = out.getvalue()
        path = session.session / (view + '.png')
        path.write_bytes(expected[view])
        frames[view] = {'image_path': str(path), 'sha256': hashlib.sha256(expected[view]).hexdigest()}
    write_json(session._path('review', 'responses'), {'status': 'returned', 'result': {
        'contract_version': 'local_direct_step_v1', 'phase': 'returned',
        'capture': frames['before'], 'observation': {'capture': frames['after']},
        'response': {'success': True}}})
    review = session.result('review')['agent_review']
    assert review['verified'] is None and review['status'] == 'awaiting_agent_review'
    assert review['automatic_retry_allowed'] is False
    assert review['before']['frame_id'] == 'before_input'
    assert review['after']['frame_id'] == 'after_settled'
    assert review['after']['image_path'] == frames['after']['image_path']
    assert review['comparison']['diff_available'] is False
    assert review['comparison']['frame_pair'] == ['before_input', 'after_settled']
    server = build_server(session)
    for view in frames:
        result = asyncio.run(server.call_tool('instant_image', review[view]['arguments']))
        assert not result.is_error
        assert base64.b64decode(result.content[0].data) == expected[view]
    assert session.image('review') == expected['after']
    assert not list((session.session / 'commands').glob('*.json'))
    (session.session / 'after.png').write_bytes(expected['before'])
    with pytest.raises(ValueError, match='digest mismatch'):
        session.image('review')


def test_agent_review_missing_after_never_substitutes_immediate_frame(session):
    api = {'success': True, 'data': {'result': {
        'post_click_verification': {'after': {'image_path': 'immediate.png'}}}}}
    write_json(session._path('missing-after', 'responses'), {'status': 'returned', 'result': {
        'contract_version': 'local_direct_step_v1', 'phase': 'result_unknown',
        'capture': {'image_path': str(session.session / 'before.png'), 'sha256': 'before'},
        'observation': {'status': 'unavailable'}, 'response': api}})
    result = session.result('missing-after')
    assert result['agent_review']['status'] == 'evidence_incomplete'
    assert result['agent_review']['after']['available'] is False
    assert result['agent_review']['after']['sha256'] is None
    assert result['agent_review']['verified'] is None
    assert result['operation_succeeded'] is False
    with pytest.raises(ValueError, match='no recorded image'):
        session.image('missing-after', 'after')


def test_known_dispatch_missing_after_is_separate_from_effect_and_guides_recovery(session):
    recovery = {'status': 'candidates_available', 'candidates': [{'handle': 22, 'process_id': 44}],
                'authorizes_input': False, 'successor_identity_verified': False}
    write_json(session._path('transition', 'responses'), {'status': 'returned', 'result': {
        'contract_version': 'local_direct_step_v1', 'phase': 'returned_observation_unavailable',
        'capture': {'image_path': 'before.png', 'sha256': 'before'},
        'observation': {'status': 'unavailable', 'recovery': recovery},
        'response': {'success': True, 'data': {'pressed': True}}}})
    result = session.result('transition')
    assert result['operation_succeeded'] is True
    assert result['operation_success_scope'] == 'input_route_only'
    assert result['input_route_succeeded'] is True
    assert result['observation_status'] == 'unavailable'
    assert result['agent_review']['status'] == 'evidence_incomplete'
    assert result['agent_review']['verified'] is None
    assert result['agent_review']['recovery'] == recovery
    assert 'select' in result['agent_review']['next']
    assert result['task_effect_verified'] is False and result['automatic_retry_allowed'] is False
    with pytest.raises(ValueError, match='no recorded image'):
        session.image('transition', 'after')
    assert not list((session.session / 'commands').glob('*.json'))


@pytest.mark.parametrize('route_success', [None, False, 'true'])
def test_transition_phase_alone_cannot_prove_route_success(session, route_success):
    write_json(session._path('incomplete-route', 'responses'), {'status': 'returned', 'result': {
        'contract_version': 'local_direct_step_v1', 'phase': 'returned_observation_unavailable',
        'response': {'success': route_success}, 'observation': {'status': 'unavailable'}}})
    result = session.result('incomplete-route')
    assert result['operation_succeeded'] is False
    assert result['input_route_succeeded'] is (False if route_success is False else None)


@pytest.mark.parametrize('case,code', [
    ('unknown', 'image_request_unknown'),
    ('pending', 'image_request_pending'),
    ('host_gone', 'image_result_unknown'),
    ('missing', 'image_frame_unavailable'),
    ('digest', 'image_digest_mismatch'),
    ('invalid_png', 'image_format_invalid'),
])
def test_image_failure_is_actionable_without_replaying_input(session, case, code):
    import asyncio
    if case in {'pending', 'host_gone'}:
        write_json(session._path('image-error', 'commands'), {'kind': 'capture'})
        if case == 'host_gone':
            session.process = None
    elif case != 'unknown':
        frame = session.session / 'recorded.png'
        raw = b'\x89PNG\r\n\x1a\nrecorded' if case != 'invalid_png' else b'not a PNG'
        frame.write_bytes(raw)
        capture = {} if case == 'missing' else {
            'image_path': str(frame),
            'sha256': 'bad' if case == 'digest' else hashlib.sha256(raw).hexdigest()}
        write_json(session._path('image-error', 'responses'), {
            'status': 'returned', 'observation': capture})
    before = {p.name: p.read_bytes() for p in (session.session / 'commands').glob('*.json')}
    server = build_server(session)
    result = asyncio.run(server.call_tool('instant_image', {'request_id': 'image-error'}))
    assert result.is_error
    value = json.loads(result.content[0].text)
    assert value['error']['code'] == code
    assert value['request_id'] == 'image-error' and value['view'] == 'after'
    assert value['automatic_retry_allowed'] is False
    assert value['read_only'] is True and value['next']
    assert 'action_executed' not in value
    assert str(session.session) not in result.content[0].text
    assert before == {p.name: p.read_bytes() for p in (session.session / 'commands').glob('*.json')}
    assert not asyncio.run(server.call_tool('instant_status', {})).is_error


@pytest.mark.parametrize('request_id,started,code', [
    ('../private', True, 'invalid_request_id'),
    ('valid', False, 'image_session_unavailable'),
])
def test_image_request_errors_are_readable_before_loading_evidence(session, request_id, started, code):
    import asyncio
    if not started:
        session.session = None
    result = asyncio.run(build_server(session).call_tool('instant_image', {'request_id': request_id}))
    assert result.is_error
    assert json.loads(result.content[0].text)['error']['code'] == code


def test_python_print_does_not_pollute_stdio(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    code = '''import sys, runpy
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
import app.instant_mcp as module
original = module.build_server
def noisy(session):
    print("INSTANT_TEST_PYTHON_NOISE")
    return original(session)
module.build_server = noisy
sys.argv = [str(root / "scripts/start_instant_mcp.py"), "--data-dir", sys.argv[2], "--model-directory", sys.argv[2]]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
    result = subprocess.run([sys.executable, "-c", code, str(root), str(tmp_path)], input=b"",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert b"INSTANT_TEST_PYTHON_NOISE" in result.stderr
    assert b"INSTANT_TEST_PYTHON_NOISE" not in result.stdout
    for line in result.stdout.splitlines():
        json.loads(line)
