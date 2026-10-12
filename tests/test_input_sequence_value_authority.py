"""全文替换和 append 只读拒绝的原 producer/runner/close 贯通。"""
from copy import deepcopy
from hashlib import sha256

import pytest

from app.agent import text_field_evidence as evidence
from app.execution import input_sequence
from tests.test_input_sequence import Coordinator
from tests.test_input_sequence_focus_partial import REQUEST, TARGET, queued, persist_original
from tests.test_local_step_timings import timed_scene
from tests.test_recognition_dispatch_boundary import route


def snapshot(value, capture_id="fresh", read_id="read", field_id="field", *, target=TARGET):
    pattern = evidence.TextFieldPatternEvidence(authority="uia_value", pattern_consistency="disagrees",
        value_sha256=sha256(value.encode("utf-8")).hexdigest(), value_length=len(value),
        text_sha256=sha256(b"Q").hexdigest(), text_length=1, selection_basis="disabled_disagreement")
    identity = evidence.TextFieldIdentity(field_id, target["handle"], target["process_id"],
        target["process_create_time"], (42, 1), (0, 0, 800, 600), (1, 1, 300, 40))
    return evidence.TextFieldSnapshot(identity, capture_id, read_id, 100 if read_id == "1" else 200,
        "uia_value", value, None, pattern)


@pytest.mark.parametrize("readback,expected", [("maps", "completed"), ("wrong value", "interrupted")])
def test_local_full_replace_records_sidecar_and_enter_requires_exact_readback(monkeypatch, readback, expected):
    co = Coordinator()
    values = iter(["old", readback])
    count = []

    def read(coordinator, target, point, capture, field_id, expected_identity, **kwargs):
        count.append(point)
        return snapshot(next(values), capture["sha256"], str(len(count)), field_id,
            target={"handle": 1, "process_id": 2, "process_create_time": 123.0})

    monkeypatch.setattr(input_sequence, "_read_field", read)
    monkeypatch.setattr(input_sequence, "_focus_field_binding", lambda *args: {
        "runtime_id": [42, 1], "control_type": "Edit", "bbox": {"x": 1, "y": 1, "w": 300, "h": 40}})
    result = input_sequence.run_input_sequence(co, {"handle": 1, "process_id": 2},
        {"field_goal": "fresh field", "text": "maps", "clear_existing": True, "submit_search": True})
    assert result["status"] == expected
    assert [row["operation"] for row in co.calls] == ["execute_recognition_plan", "type_text"] + (
        ["press_key"] if expected == "completed" else [])
    assert result["action_executed"] is True
    assert len(result["field_reads"]) == 2
    assert all(row["pattern_evidence"]["pattern_consistency"] == "disagrees" for row in result["field_reads"])
    assert all(row["contract_version"] == "text_field_snapshot_reference_v1" for row in result["field_reads"])


@pytest.mark.parametrize("cancel", [False, True])
def test_append_without_selection_keeps_real_focus_proof_and_unlocks_owned_close(
        route, timed_scene, tmp_path, monkeypatch, cancel):
    from app.execution import local_direct_step
    response = route.run("success")
    monkeypatch.setattr(local_direct_step, "_post_action", lambda *args: deepcopy(response))
    monkeypatch.setattr(input_sequence, "_focus_field_binding", lambda *args: {
        "runtime_id": [42, 1], "control_type": "Edit", "bbox": {"x": 1, "y": 1, "w": 300, "h": 40}})
    monkeypatch.setattr(input_sequence, "_read_field", lambda coordinator, target, point, capture,
        field_id, *args, **kwargs: snapshot("old", capture["sha256"], "1", field_id))
    request = {**REQUEST, "clear_existing": False}
    result = input_sequence.run_input_sequence(timed_scene[0], {"handle": 321, "process_id": 12}, request)
    assert result["status"] == "interrupted" and result["completed_steps"] == ["focus"]
    assert result["error"] == {"code": "text_field_selection_unavailable", "type": "TextFieldReadError"}
    assert result["input_check"]["phase"] == "check_focus"
    assert result["field_reads"][0]["pattern_evidence"]["selection_basis"] == "disabled_disagreement"
    assert result["partial_input_terminal"]["started_actions"] == ["focus"]
    assert result["action_executed"] is True
    assert route.events.count("click_point") == 1
    monkeypatch.setattr("tests.test_input_sequence_focus_partial.REQUEST", request)
    s, pending, path, calls = queued(tmp_path, monkeypatch, result)
    original = persist_original(s, pending, path, result)
    if cancel:
        s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-original")
    final = s.runtime.tick(force=True)
    assert final["status"] == ("cancelled" if cancel else "failed")
    assert final["pending"] is None and len(final["history"]) == 1
    assert final["history"][0]["action_executed"] is True
    assert final["history"][0]["original_input_status"] == "failed"
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    for i in range(2):
        assert s.runtime.control({"action": "status", "run_id": s.run_id}, "status-" + str(i))["history"] == final["history"]
    assert len(list(s.session.glob("commands/trial-exec-*.json"))) == 1
    assert path.read_bytes() == original and calls == []
