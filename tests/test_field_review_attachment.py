"""字段审核等待仍占用原 job；附件只交付原绑定证据，不结算或重放输入。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.instant_mcp import InstantSession, write_json
from app.instant_receipt import compact_receipt


def _waiting_session(tmp_path, monkeypatch, *, alive=True):
    session = InstantSession(tmp_path, tmp_path, recognition_source="external_api")
    session.session = tmp_path
    monkeypatch.setattr(session, "_host_alive", lambda: alive)
    for name in ("commands", "responses", "agent-commands"):
        (tmp_path / name).mkdir()
    original = {"kind": "input_sequence", "request": {"field_goal": "Search", "text": "private original input"}}
    poll = {"kind": "agent_command_status", "request": {"command_id": "original-input"}}
    image = b"\x89PNG\r\n\x1a\n" + b"frozen-field-review-pixels"
    image_path = tmp_path / "field-review.png"
    image_path.write_bytes(image)
    after = {"image_path": str(image_path), "sha256": sha256(image).hexdigest(),
        "window_size": [80, 60], "capture_id": "field-capture", "window_identity": {"handle": 10, "process_id": 20}}
    packet = {"schema": "field_review_packet.v1", "run_id": "trial-original", "step_id": "search",
        "plan_id": "plan-original", "plan_sha256": "d" * 64,
        "execution_request_id": "original-input", "after": after,
        "request": {"condition": "The intended field remains focused"},
        "assessment": {"verdict": "failure", "reason": "model requested Main review"},
        "progress_snapshot": {"path": "sequence-progress/original-input.json", "sha256": "a" * 64},
        "packet_sha256": "b" * 64, "evidence_set_sha256": "c" * 64, "assessment_round": 0,
        "authorizes_action": False}
    worker = {"contract_version": "agent_command.v1", "command_id": "original-input",
        "status": "awaiting_field_review", "action_executed": True, "dispatch_in_progress": False,
        "pending_field_review": packet, "result": None}
    write_json(tmp_path / "commands/original-input.json", original)
    write_json(tmp_path / "responses/original-input.json", {"command": original, "status": "returned",
        "result": {**worker, "status": "running", "pending_field_review": None, "action_executed": False}})
    write_json(tmp_path / "commands/poll-original.json", poll)
    write_json(tmp_path / "responses/poll-original.json", {"command": poll, "status": "returned", "result": worker})
    write_json(tmp_path / "agent-commands/original-input.json", worker)
    return session, worker, image


def test_live_field_review_is_pending_and_keeps_original_packet(tmp_path, monkeypatch):
    session, worker, _ = _waiting_session(tmp_path, monkeypatch)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    receipt = session.result("poll-original")
    assert receipt["operation_succeeded"] is None
    assert receipt["task_effect_verified"] is None and receipt["action_executed"] is True
    assert receipt["operation_success_scope"] == "agent_command_progress"
    assert receipt["result"]["pending_field_review"] == worker["pending_field_review"]
    assert receipt["next_action"] == "review_original_field_packet_then_continue_original_task_plan"
    assert receipt["next"]["arguments"]["command"]["request"] == {"command_id": "original-input"}
    assert receipt["next"]["arguments"]["request_id"] != "original-input"
    assert "command" not in receipt and receipt["automatic_retry_allowed"] is False
    assert {path: path.read_bytes() for path in tmp_path.rglob("*.json")} == before


def test_status_request_delivers_packet_image_without_reading_terminal_worker(tmp_path, monkeypatch):
    session, worker, image = _waiting_session(tmp_path, monkeypatch)
    assert session.image("poll-original", "after") == image
    assert session.result("poll-original")["observation"]["capture"] == worker["pending_field_review"]["after"]


def test_field_review_image_keeps_existing_digest_guard(tmp_path, monkeypatch):
    session, _, _ = _waiting_session(tmp_path, monkeypatch)
    (tmp_path / "field-review.png").write_bytes(b"\x89PNG\r\n\x1a\nchanged-pixels")
    with pytest.raises(ValueError, match="digest"):
        session.image("poll-original", "after")


@pytest.mark.parametrize("packet", [[], {"schema": "field_review_packet.v1", "execution_request_id": "other-input"}])
def test_unbound_field_packet_cannot_supply_another_commands_image(tmp_path, monkeypatch, packet):
    session, _, _ = _waiting_session(tmp_path, monkeypatch)
    path = tmp_path / "responses/poll-original.json"
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["result"]["pending_field_review"] = packet
    write_json(path, receipt)
    assert "observation" not in session.result("poll-original")
    with pytest.raises(ValueError, match="no recorded image"):
        session.image("poll-original", "after")


def test_dead_field_review_is_unknown_and_never_an_action_permit(tmp_path, monkeypatch):
    session, worker, _ = _waiting_session(tmp_path, monkeypatch, alive=False)
    receipt = session.result("poll-original")
    assert receipt["operation_succeeded"] is None
    assert receipt["action_executed"] is True and receipt["worker_status"] == "result_unknown"
    assert receipt["persisted_worker_evidence"]["status"] == "awaiting_field_review"
    assert receipt["result"]["pending_field_review"] == worker["pending_field_review"]
    assert receipt["next_action"] == "inspect_original_worker_evidence_no_replay"
    assert "next" not in receipt and receipt["automatic_retry_allowed"] is False


def test_compact_field_review_preserves_public_packet_only(tmp_path, monkeypatch):
    session, worker, _ = _waiting_session(tmp_path, monkeypatch)
    packet = deepcopy(worker["pending_field_review"])
    packet["private_runtime_state"] = {"credential": "must-not-be-projected"}
    worker["pending_field_review"] = packet
    worker["private_runtime_state"] = "must-not-be-projected"
    receipt = compact_receipt({"request_id": "poll-original", "result": worker})
    projected = receipt["agent_command"]["pending_field_review"]
    assert projected["schema"] == "field_review_packet.v1"
    assert projected["after"] == packet["after"]
    for key in ("run_id", "step_id", "execution_request_id", "plan_id", "plan_sha256", "packet_sha256", "evidence_set_sha256",
                "assessment_round", "request", "assessment", "progress_snapshot"):
        assert projected[key] == packet[key]
    assert "must-not-be-projected" not in json.dumps(receipt)
