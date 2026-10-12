"""主动审核保留原票据；使用真实运行器与队列，服务边界保持离线。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_contract import validate_task_plan
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import complete_original, scene


CONDITION = "The requested detail is visible."


def adaptive_plan(count=2):
    value = plan(count=count, verification={"kind": "agent_judgment", "decision_condition": CONDITION,
        "allowed_states": ["Requested detail with no modal choice"]})
    value["schema_version"] = "task_plan.v2"
    return value


class OfflineAssessment:
    enabled = True

    def status(self):
        return {"contract_version": "decision_profile.v2", "profile_sha256": "e" * 64,
            "adoption_mode": "auto", "review_policy": "adaptive"}

    def __init__(self, *, disposition="review_required", error=None, authenticate=True, during=None):
        self.disposition = disposition
        self.error = error
        self.authenticate = authenticate
        self.during = during
        self.calls = []

    def evaluate(self, **binding):
        self.calls.append(deepcopy(binding))
        if self.during:
            self.during()
        if self.error == "provider":
            raise RuntimeError("private provider detail")
        if self.error == "shape":
            return ["invalid provider structure"]
        return {"schema_version": "decision_assessment.v2", "request_id": binding["request_id"],
            "execution_request_id": binding["execution_request_id"], "phase": binding["phase"],
            "verdict": "success", "disposition": self.disposition, "review_scope": "remaining_plan",
            "reason_codes": ["off_plan_intervention_high"],
            "enabled_predicates": ["condition_met", "visible_error", "needs_agent_review"],
            "adopted": self.disposition == "continue", "authorizes_action": False,
            "profile_sha256": "e" * 64}

    def validate_result(self, value, **binding):
        if self.error == "authentication":
            raise RuntimeError("private authentication detail")
        return self.authenticate and binding in self.calls


def review_request(s, waiting, original):
    packet = waiting["review_packet"]
    return {"action": "review", "run_id": s.run_id, "execution_request_id": original.command_id,
        "step_id": "step-0", "verdict": "success", "reason": "Original evidence and suffix inspected",
        "evidence_sha256": original.capture["sha256"], "review_packet_sha256": packet["packet_sha256"],
        "evidence_set_sha256": packet["evidence_set_sha256"], "assessment_round": packet["assessment_round"]}


def test_v2_contract_preserves_v1_and_freezes_review_context():
    value = adaptive_plan()
    assert validate_task_plan(value) == value
    value["steps"][0]["verification"]["allowed_states"].append("Changed")
    assert validate_task_plan(plan()) == plan()


@pytest.mark.parametrize("patch", [{"review_policy": "adaptive"}, {"allowed_states": [""]},
    {"allowed_states": "normal"}, {"assessment_round": 1}, {"before_action": True}])
def test_v2_verification_cannot_expand_authority(patch):
    value = adaptive_plan()
    value["steps"][0]["verification"].update(patch)
    with pytest.raises(ValueError):
        validate_task_plan(value)


def test_proactive_success_keeps_original_wait_until_bound_review_and_continue(tmp_path, monkeypatch):
    service = OfflineAssessment()
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required" and waiting["history"] == []
    packet = waiting["review_packet"]
    assert packet["schema"] == "review_packet.v1" and packet["suggested_verdict"] == "success"
    assert packet["wait_id"] == waiting["wait"]["wait_id"]
    assert packet["original_input_status"] == "completed" and packet["action_executed"] is True
    assert packet["evidence_set_sha256"] and packet["source_ref"]["sha256"]
    assert service.calls[0]["review_context"]["source_sha256"] == waiting["plan_sha256"]
    for index in range(3):
        observed = s.runtime.control({"action": "status", "run_id": s.run_id}, "status-" + str(index))
        assert observed["review_packet"] == packet
        assert s.runtime.tick(force=True) is None
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1
    reviewed = s.runtime.control(review_request(s, waiting, original), "main-review")
    assert reviewed["status"] == "ready" and reviewed["wait"] == waiting["wait"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    s.runtime.control({"action": "continue", "run_id": s.run_id,
        "wait_id": waiting["wait"]["wait_id"]}, "continue-original")
    s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert read_json_snapshot(tmp_path / "responses" / (original.command_id + ".json")) == original.receipt


@pytest.mark.parametrize("field", ["review_packet_sha256", "evidence_set_sha256", "assessment_round"])
def test_stale_v2_review_cannot_settle_original_ticket(tmp_path, monkeypatch, field):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    original = complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    request = review_request(s, waiting, original)
    request[field] = 1 if field == "assessment_round" else "a" * 64
    with pytest.raises(ValueError, match="review_packet_binding"):
        s.runtime.control(request, "stale-review")
    assert s.runtime.backend.status(s.run_id)["history"] == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("error", ["provider", "shape", "authentication"])
def test_provider_failures_are_structured_waits_without_private_detail(tmp_path, monkeypatch, error):
    service = OfflineAssessment(error=error)
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "verification_required" and "error" not in result["wait"]
    assert "decision_" in result["review_packet"]["reason"]
    assert "private" not in str(result["review_packet"])
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("field", ["verdict", "disposition", "review_scope"])
@pytest.mark.parametrize("bad_value", [[], {}])
def test_unhashable_assessment_fields_become_structured_review(tmp_path, monkeypatch, field, bad_value):
    service = OfflineAssessment()
    evaluate = service.evaluate
    def malformed(**binding):
        value = evaluate(**binding)
        value[field] = deepcopy(bad_value)
        return value
    monkeypatch.setattr(service, "evaluate", malformed)
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    expected = "decision_result_binding_invalid" if field == "verdict" else "decision_result_contract_invalid"
    assert result["review_packet"]["reason"] == expected
    assert result["wait_reason"] == "verification_required" and "error" not in result["wait"]
    assert result["history"] == [] and len(service.calls) == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_v2_plan_rejects_v1_profile_before_paid_dispatch(tmp_path, monkeypatch):
    service = OfflineAssessment()
    service.status = lambda: {"contract_version": "decision_profile.v1", "profile_sha256": "d" * 64}
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    complete_original(s, native=False)
    result = s.runtime.tick(force=True)
    assert result["review_packet"]["reason"] == "decision_profile_v2_required"
    assert service.calls == [] and len(list(tmp_path.glob("commands/*.json"))) == 1


def test_explicit_always_main_holds_complete_native_proof_without_api(tmp_path, monkeypatch):
    service = OfflineAssessment()
    service.status = lambda: {"contract_version": "decision_profile.v2", "profile_sha256": "e" * 64,
        "adoption_mode": "auto", "review_policy": "always_main"}
    source = plan()
    source["schema_version"] = "task_plan.v2"
    s = scene(tmp_path, monkeypatch, source=source, decision=service)
    original = complete_original(s)
    result = s.runtime.tick(force=True)
    assert result["wait_reason"] == "verification_required" and result["history"] == []
    assert result["review_packet"]["suggested_verdict"] == "success"
    assert result["review_packet"]["reason"] == "decision_always_main"
    assert result["review_packet"]["profile_sha256"] == "e" * 64
    assert service.calls == []
    reviewed = s.runtime.control(review_request(s, result, original), "always-main-review")
    assert reviewed["status"] == "ready" and len(list(tmp_path.glob("commands/*.json"))) == 1


def successor_request(s, *, logical_id="successor-one"):
    parent = s.runtime.backend.status(s.run_id)
    value = plan(count=1)
    value["schema_version"] = "task_plan.v2"
    value["steps"][0]["step_id"] = "remaining-step"
    value["steps"][0]["action"]["goal"] = "Open the remaining independent record"
    return {"action": "start", "plan": value, "successor": {
        "successor_request_id": logical_id, "successor_of": s.run_id,
        "parent_plan_sha256": parent["plan_sha256"],
        "prefix_sha256": s.runtime.backend.prefix_sha256(s.run_id),
        "lineage_generation": parent.get("lineage_generation", 0), "reason": "Main changed remaining plan"}}


def cancelled_parent(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    original = complete_original(s, native=False)
    s.runtime.tick(force=True)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-parent")
    assert s.runtime.tick(force=True)["runner_state"] == "cancelled"
    return s, original


def test_successor_logical_id_reuses_original_run_across_transport_ids(tmp_path, monkeypatch):
    s, original = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    child = s.runtime.control(request, "transport-one")
    repeated = s.runtime.control(request, "transport-two")
    assert repeated["run_id"] == child["run_id"] != s.run_id
    assert repeated["active_command_id"] == child["active_command_id"]
    assert child["successor_of"] == s.run_id and child["lineage_generation"] == 1
    assert child["history"] == []
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert s.runtime.backend.status(s.run_id)["history"][0]["execution_request_id"] == original.command_id


def test_successor_conflict_and_consumed_generation_cannot_replay(tmp_path, monkeypatch):
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    child = s.runtime.control(request, "transport-one")
    other = deepcopy(request)
    other["plan"]["title"] += " changed"
    with pytest.raises(ValueError, match="successor_idempotency_conflict"):
        s.runtime.control(other, "conflicting-transport")
    other = deepcopy(request)
    other["successor"]["successor_request_id"] = "successor-two"
    with pytest.raises(ValueError, match="successor_generation_consumed"):
        s.runtime.control(other, "another-transport")
    assert len(list(tmp_path.glob("commands/*.json"))) == 2
    assert child["run_id"] == s.runtime.runner._active_run()


def test_successor_ordinary_start_id_collision_does_not_consume_generation(tmp_path, monkeypatch):
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    parent = s.runtime.backend.status(s.run_id)
    request = successor_request(s, logical_id=parent["start_request_id"])
    before = s.runtime.backend._lineage()
    with pytest.raises(ValueError, match="successor_run_id_conflict"):
        s.runtime.control(request, "colliding-successor-transport")
    assert s.runtime.backend._lineage() == before
    assert s.runtime.runner._active_run() == s.run_id
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    child = s.runtime.control(successor_request(s), "noncolliding-successor-transport")
    assert child["successor_of"] == s.run_id and child["lineage_generation"] == 1
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_reserved_successor_with_terminal_active_parent_blocks_competing_input(tmp_path, monkeypatch):
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    start = s.runtime.backend._start_locked
    def interrupted(*args, **kwargs):
        raise OSError("synthetic child creation interruption")
    monkeypatch.setattr(s.runtime.backend, "_start_locked", interrupted)
    with pytest.raises(OSError, match="synthetic child creation interruption"):
        s.runtime.control(request, "interrupted-successor-transport")
    ledger = s.runtime.backend._lineage()
    assert ledger["requests"]["successor-one"]["status"] == "reserved"
    assert s.runtime.runner._active_run() == s.run_id
    assert s.runtime.runner.status(s.run_id)["runner_state"] == "cancelled"
    before = list(tmp_path.glob("commands/*.json"))
    with pytest.raises(ValueError, match="task_plan_run_active"):
        s.runtime.admit("competing-step", {"kind": "step", "goal": "Open another record"})
    assert list(tmp_path.glob("commands/*.json")) == before
    monkeypatch.setattr(s.runtime.backend, "_start_locked", start)
    child = s.runtime.control(request, "reconciled-successor-transport")
    assert child["successor_of"] == s.run_id
    assert child["start_transport_request_id"] == "interrupted-successor-transport"
    assert s.runtime.backend._lineage()["requests"]["successor-one"]["status"] == "committed"
    assert len(list(tmp_path.glob("commands/*.json"))) == 2


def test_old_successor_readback_cannot_disable_another_active_run(tmp_path, monkeypatch):
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    child = s.runtime.control(request, "first-transport")
    parent_id = s.run_id
    s.run_id = child["run_id"]
    complete_original(s)
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    s.run_id = parent_id
    current = s.runtime.control({"action": "start", "plan": plan()}, "next-independent-plan")
    enabled = s.runtime._enabled_run
    old = s.runtime.control(request, "repeat-old-transport")
    assert old["run_id"] == child["run_id"] and old["runner_state"] == "completed"
    assert s.runtime._enabled_run == enabled == current["run_id"]
    assert s.runtime.runner._active_run() == current["run_id"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 3


def test_existing_client_returns_one_original_review_event_without_spawning_main(tmp_path, monkeypatch):
    import asyncio
    from tests.test_task_plan_client import Session, client
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
    complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    session = Session([waiting, waiting])
    opened = client(tmp_path, session)
    events = []
    result = asyncio.run(opened.run_plan("plan-start", {"kind": "task_plan",
        "request": {"action": "start", "plan": adaptive_plan()}}, event_callback=events.append))
    assert result["client_state"] == "review_required"
    assert result["result"]["review_packet"] == waiting["review_packet"]
    repeated = asyncio.run(opened.run_plan("same-wait-status", {"kind": "task_plan",
        "request": {"action": "status", "run_id": s.run_id}}, event_callback=events.append))
    assert repeated["wait_id"] == result["wait_id"] and len(events) == 1
    assert [name for name, _ in session.calls] == ["instant_run", "instant_run"]
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_client_pending_successor_uses_first_transport_receipt_after_logical_replay(tmp_path, monkeypatch):
    import asyncio
    from tests.test_task_plan_client import Session, client
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    child = s.runtime.control(request, "first-successor-transport")
    session = Session([child], pending_status=1)
    opened = client(tmp_path, session)
    async def scenario():
        started = await opened.run_plan("replayed-successor-transport", {
            "kind": "task_plan", "request": request}, event_callback=None, total_timeout=0)
        pending = await opened.run_plan("successor-pending-status", {"kind": "task_plan", "request": {
            "action": "status", "run_id": child["run_id"]}}, event_callback=None, total_timeout=0)
        return started, pending
    started, pending = asyncio.run(scenario())
    assert started["client_state"] == pending["client_state"] == "pending"
    assert started["start_request_id"] == pending["start_request_id"] == "successor-one"
    for result in (started, pending):
        assert result["start_receipt"]["arguments"]["request_id"] == "first-successor-transport"
    assert len(session.calls) == 2 and len(list(tmp_path.glob("commands/*.json"))) == 2


@pytest.mark.parametrize("review_probability", [.96, .01])
def test_real_v2_service_authentication_and_runtime_queue_share_review_context(tmp_path, monkeypatch, review_probability):
    import httpx
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    from tests.test_openai_decisions import reply
    monkeypatch.setenv("DECISION_ADAPTIVE_TEST_KEY", "synthetic-offline-only")
    requests = []
    response = reply()
    response["answers"][1]["name"] = "visible_error"
    response["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": review_probability})
    def offline(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    with httpx.Client(transport=httpx.MockTransport(offline)) as connection:
        profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
            api_key_env="DECISION_ADAPTIVE_TEST_KEY", auto_conditions=[CONDITION])
        service = DecisionService(tmp_path, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env="DECISION_ADAPTIVE_TEST_KEY", client=connection))
        s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
        original = complete_original(s, native=False)
        result = s.runtime.tick(force=True)
        if review_probability > .1:
            assert result["review_required"] is True and result["history"] == []
            assert result["review_packet"]["profile_sha256"] == service.status()["profile_sha256"]
            assert len(list(tmp_path.glob("commands/*.json"))) == 1
            reviewed = s.runtime.control(review_request(s, result, original), "authenticated-main-review")
            assert reviewed["status"] == "ready"
        else:
            assert result["history"][0]["judged_by"] == "decision" and result["pending"]["step_id"] == "step-1"
            assert len(list(tmp_path.glob("commands/*.json"))) == 2
        assert len(requests) == 1


def test_successor_conservatively_refuses_completed_command_even_with_new_verification(tmp_path, monkeypatch):
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    request = successor_request(s)
    old = s.runtime.backend.pinned_step(s.run_id, "step-0")
    request["plan"]["steps"][0] = {**deepcopy(old), "step_id": "intentional-navigation-repeat"}
    request["plan"]["steps"][0]["verification"] = {"kind": "agent_judgment", "decision_condition": "Changed condition"}
    with pytest.raises(ValueError, match="completed_input_replay_forbidden"):
        s.runtime.control(request, "repeat-navigation")
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_cancelled_label_alone_cannot_admit_unknown_prefix(tmp_path, monkeypatch):
    from app.execution.task_plan_review import digest
    s, _ = cancelled_parent(tmp_path, monkeypatch)
    path = s.runtime.backend._path(s.run_id)
    state = read_json_snapshot(path)
    row = state["history"][0]
    request_id = row["verification_request_id"]
    result = state["verification_results"][request_id]
    result["original_input_status"] = row["original_input_status"] = "unknown"
    state["verification_requests"][request_id] = row["verification_result_sha256"] = digest(result)
    write_json_snapshot(path, state)
    with pytest.raises(ValueError, match="parent_input_unknown"):
        s.runtime.control(successor_request(s), "unknown-labelled-cancelled")
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


@pytest.mark.parametrize("hazard", ["parent_pending", "queue", "agent_job", "unknown"])
def test_successor_rejects_inflight_or_unknown_original_work(tmp_path, monkeypatch, hazard):
    if hazard in {"parent_pending", "unknown"}:
        s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=OfflineAssessment())
        if hazard == "unknown":
            complete_original(s, status="unknown")
            s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-parent")
            s.runtime.tick(force=True)
    else:
        s, _ = cancelled_parent(tmp_path, monkeypatch)
        if hazard == "queue":
            write_json_snapshot(tmp_path / "commands" / "unsettled-input.json", {"kind": "step"})
        else:
            write_json_snapshot(tmp_path / "agent-commands" / "unsettled-input.json", {"status": "running"})
    request = successor_request(s)
    before = list(tmp_path.glob("commands/*.json"))
    with pytest.raises(ValueError, match="successor_.*(quiescent|terminal)"):
        s.runtime.control(request, "unsafe-successor")
    assert list(tmp_path.glob("commands/*.json")) == before


def test_late_successful_decision_after_cancel_cannot_dispatch_suffix(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=adaptive_plan(), decision=service)
    service.during = lambda: s.runtime.backend.cancel(s.run_id, "cancel-during-decision")
    complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    assert waiting["status"] == "cancel_requested"
    s.runtime.tick(force=True)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
