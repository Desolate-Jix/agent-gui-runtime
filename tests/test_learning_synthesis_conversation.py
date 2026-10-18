"""同一整理请求的自动纠错预算和人工续接跨重开保持。"""
from copy import deepcopy
import json

import pytest

from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.receipt_adapter import content_hash
from test_learning_synthesis import _reply, _stop, repeated_state, observation_scene


def _status(store, request):
    return store.control("learning_workflow", {"action": "synthesis_status",
        "synthesis_id": request["synthesis_id"]}, "conversation-status")


def _fail_twice(store, request):
    bad = _reply(request, annotations={"click-1": {"unrecognized": True}})
    return [store.control("learning_workflow", bad, name) for name in ("initial-bad", "correction-bad")]


def _resume(request, **changes):
    value = {"action": "synthesis_resume", "synthesis_id": request["synthesis_id"],
             "source_sha256": request["source_sha256"], "after_reply_request_id": "correction-bad",
             "user_instruction": "请保留原操作，仅修正成功条件。"}
    value.update(changes)
    return value


def test_initial_reply_and_one_correction_then_user_wait_survive_reopen(repeated_state):
    store, root, started, _, _ = repeated_state
    first = _stop(store)
    request = first["synthesis_request"]
    assert first["conversation"]["state"] == "initial_reply"
    assert first["conversation"]["replies_remaining"] == 2
    errors = _fail_twice(store, request)
    assert errors[0]["conversation"]["state"] == "correct_once"
    assert errors[0]["conversation"]["replies_remaining"] == 1
    assert errors[1]["conversation"]["state"] == "awaiting_user"
    reopened = LearningEventStore(store.session)
    for _ in range(2):
        pending = _status(reopened, request)
        assert pending["status"] == "awaiting_user"
        assert pending["conversation"]["replies_remaining"] == 0
        assert pending["synthesis_request"] == request
        assert pending["metrics"]["reply_attempts"] == 2
    prepared = reopened.control("learning_workflow", {"action": "synthesis_prepare",
        "learning_session_id": started["learning_id"]}, "repeat-prepare")
    assert prepared["conversation"] == pending["conversation"]
    with pytest.raises(ValueError, match="synthesis_user_input_required"):
        reopened.control("learning_workflow", _reply(request), "third-automatic-reply")
    attempts = root / "desktop-review/learning-synthesis" / request["synthesis_id"] / "attempts"
    assert len(list(attempts.glob("*.json"))) == 2


def test_explicit_user_resume_keeps_original_identity_and_is_idempotent(repeated_state):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    resumed = store.control("learning_workflow", _resume(request), "user-resume")
    assert resumed["status"] == "awaiting_agent"
    assert resumed["synthesis_request"] == request
    assert resumed["conversation"]["resume_request_id"] == "user-resume"
    assert resumed["conversation"]["user_instruction"] == _resume(request)["user_instruction"]
    assert resumed["conversation"]["replies_remaining"] == 2
    reopened = LearningEventStore(store.session)
    assert _status(reopened, request)["conversation"] == resumed["conversation"]
    bad = _reply(request, annotations={"click-1": {"unrecognized": True}})
    bad["resume_request_id"] = "user-resume"
    reopened.control("learning_workflow", bad, "resumed-bad")
    replay = reopened.control("learning_workflow", _resume(request), "user-resume")
    assert replay["conversation"]["replies_remaining"] == 1
    done = reopened.control("learning_workflow", _reply(request, resume_request_id="user-resume"), "resumed-correction")
    assert done["status"] == "draft_ready"
    assert done["conversation"]["state"] == "review_draft"
    assert done["metrics"]["reply_attempts"] == 4
    assert done["metrics"]["total_model_calls"] is None
    assert _status(reopened, request) == done


@pytest.mark.parametrize("changes,error", [
    ({"source_sha256": "0" * 64}, "synthesis_source_mismatch"),
    ({"after_reply_request_id": "initial-bad"}, "synthesis_resume_stale"),
    ({"user_instruction": " "}, "user_instruction"),
])
def test_resume_rejects_unbound_or_empty_user_request(repeated_state, changes, error):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    with pytest.raises(ValueError, match=error):
        store.control("learning_workflow", _resume(request, **changes), "invalid-resume")
    assert _status(store, request)["conversation"]["replies_remaining"] == 0


def test_resume_does_not_erase_history_or_accept_changed_idempotent_payload(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    directory = root / "desktop-review/learning-synthesis" / request["synthesis_id"]
    originals = {p: p.read_bytes() for p in (directory / "attempts").glob("*.json")}
    store.control("learning_workflow", _resume(request), "user-resume")
    with pytest.raises(ValueError, match="synthesis_resume_conflict"):
        store.control("learning_workflow", _resume(request, user_instruction="改成别的规则"), "user-resume")
    assert all(path.read_bytes() == raw for path, raw in originals.items())


def test_legacy_attempts_still_exhaust_budget_without_inventing_order(repeated_state):
    store, root, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    directory = root / "desktop-review/learning-synthesis" / request["synthesis_id"]
    for path in (directory / "attempts").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        value.pop("attempt_index")
        value.pop("attempt_created_at")
        value.pop("record_sha256")
        value["record_sha256"] = content_hash(value)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    state = _status(store, request)
    assert state["last_correction"]["ordering"] == "unknown"
    assert state["conversation"]["state"] == "awaiting_user"
    assert state["conversation"]["replies_remaining"] == 0
    with pytest.raises(ValueError, match="synthesis_attempt_order_unknown"):
        store.control("learning_workflow", _resume(request,
            after_reply_request_id=state["last_correction"]["reply_request_id"]), "legacy-resume")


def test_status_checks_original_source_before_requesting_another_reply(repeated_state, monkeypatch):
    from app.learning_memory import learning_synthesis
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    def corrupt(*args, **kwargs):
        raise ValueError("memory_graph_source_changed")
    monkeypatch.setattr(learning_synthesis, "_source", corrupt)
    with pytest.raises(ValueError, match="memory_graph_source_changed"):
        _status(store, request)


def test_late_reply_cannot_consume_new_user_round(repeated_state):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    store.control("learning_workflow", _resume(request), "user-resume")
    with pytest.raises(ValueError, match="synthesis_reply_round_mismatch"):
        store.control("learning_workflow", _reply(request), "late-original-reply")
    assert _status(store, request)["conversation"]["replies_remaining"] == 2


def test_resume_cannot_grant_extra_budget_until_current_round_is_exhausted(repeated_state):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    store.control("learning_workflow", _resume(request), "user-resume")
    with pytest.raises(ValueError, match="synthesis_user_resume_not_required"):
        store.control("learning_workflow", _resume(request), "extra-resume")
    done = store.control("learning_workflow", _reply(request, resume_request_id="user-resume"), "done")
    with pytest.raises(ValueError, match="synthesis_already_completed"):
        store.control("learning_workflow", _resume(request), "after-complete")
    assert _status(store, request) == done


@pytest.mark.parametrize("completed", [False, True])
def test_duplicate_reply_requires_original_resume_round(repeated_state, completed):
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    _fail_twice(store, request)
    store.control("learning_workflow", _resume(request), "user-resume")
    reply = _reply(request, resume_request_id="user-resume")
    if not completed:
        reply["annotations"] = {"click-1": {"unrecognized": True}}
    store.control("learning_workflow", reply, "bound-reply")
    reply.pop("resume_request_id")
    with pytest.raises(ValueError, match="synthesis_reply_round_mismatch"):
        store.control("learning_workflow", reply, "bound-reply")


@pytest.mark.parametrize("operation", ["status", "duplicate"])
def test_completed_draft_does_not_hide_source_corruption(repeated_state, monkeypatch, operation):
    from app.learning_memory import learning_synthesis
    store, _, _, _, _ = repeated_state
    request = _stop(store)["synthesis_request"]
    reply = _reply(request)
    store.control("learning_workflow", reply, "completed")
    def corrupt(*args, **kwargs):
        raise ValueError("memory_graph_source_changed")
    monkeypatch.setattr(learning_synthesis, "_source", corrupt)
    with pytest.raises(ValueError, match="memory_graph_source_changed"):
        if operation == "status":
            _status(store, request)
        else:
            store.control("learning_workflow", reply, "completed")
