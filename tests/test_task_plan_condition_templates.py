"""执行模板绑定到原计划和本次输入；仅使用离线收据与服务。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_backend import TaskPlanBackend
from app.execution.task_plan_contract import validate_task_plan
from app.execution.task_plan_review import digest
from app.judgment.condition_templates import make_record_id_template, resolve_condition_binding
from tests.test_task_plan_adaptive_review import OfflineAssessment
from tests.test_task_plan_contract import plan
from tests.test_task_plan_native_semantic import timeout_original
from tests.test_task_plan_runner import complete_original, scene


def template_plan(*, source="literal", native=False, wait=False, policy="adaptive"):
    value = plan(count=1)
    value["schema_version"] = "task_plan.v2"
    value["inputs"] = {"record": "REC-007"}
    binding = {"schema": "condition_binding.v1", "template": make_record_id_template(
        allowed_states=["Matching detail without a modal"], review_policy=policy),
        "typed_parameters": {"record_id": {"source": source,
            **({"value": "REC-007"} if source == "literal" else {"name": "record"})}}}
    rule = value["steps"][0]["verification"] if native else {"kind": "agent_judgment"}
    rule["condition_binding"] = binding
    if wait:
        rule["wait_policy"] = {"loading_condition": "Loading indicator is visible",
            "completion_excludes_loading": True}
    value["steps"][0]["verification"] = rule
    return value


def expected_snapshot(value):
    return resolve_condition_binding(value["steps"][0]["verification"]["condition_binding"], value["inputs"])


@pytest.mark.parametrize("source", ["literal", "input"])
def test_start_freezes_complete_snapshot_and_reopen_authenticates_it(tmp_path, monkeypatch, source):
    value = template_plan(source=source)
    assert validate_task_plan(value) == value
    s = scene(tmp_path, monkeypatch, source=value)
    state = s.runtime.backend.status(s.run_id)
    frozen = s.runtime.backend._source(state)
    snapshots = {"step-0": expected_snapshot(value)}
    assert frozen["condition_snapshots"] == snapshots
    assert state["condition_snapshots_sha256"] == digest(snapshots)
    value["inputs"]["record"] = "CHANGED"
    assert TaskPlanBackend(tmp_path, owner_id="owner-1").status(s.run_id) == state
    assert s.runtime.backend._source(state)["condition_snapshots"] == snapshots


@pytest.mark.parametrize("version", ["task_plan.v1", "task_plan.v2"])
def test_legacy_plans_do_not_gain_empty_snapshot_fields(tmp_path, monkeypatch, version):
    value = plan(count=1)
    value["schema_version"] = version
    s = scene(tmp_path, monkeypatch, source=value)
    state = s.runtime.backend.status(s.run_id)
    assert "condition_snapshots_sha256" not in state
    assert "condition_snapshots" not in s.runtime.backend._source(state)


@pytest.mark.parametrize("bad", [None, 7, True, "", "X" * 161])
def test_invalid_referenced_input_fails_before_any_dispatch(tmp_path, monkeypatch, bad):
    value = template_plan(source="input")
    if bad is None:
        value["inputs"].clear()
    else:
        value["inputs"]["record"] = bad
    with pytest.raises(ValueError):
        scene(tmp_path, monkeypatch, source=value)
    assert list(tmp_path.glob("commands/*.json")) == []
    assert list(tmp_path.glob("task-plans/trial-*.json")) == []


@pytest.mark.parametrize("native", [False, True])
def test_binding_and_freeform_are_mutually_exclusive_and_v1_rejects(native):
    value = template_plan(native=native)
    value["steps"][0]["verification"]["decision_condition"] = "Other condition"
    with pytest.raises(ValueError):
        validate_task_plan(value)
    value["steps"][0]["verification"].pop("decision_condition")
    value["schema_version"] = "task_plan.v1"
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("source", ["literal", "input"])
def test_semantic_dispatch_and_backend_adoption_use_exact_frozen_snapshot(tmp_path, monkeypatch, source):
    value, service = template_plan(source=source), OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    original = complete_original(s, native=False)
    raw = (tmp_path / "responses" / (original.command_id + ".json")).read_bytes()
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed"
    assert terminal["history"][0]["judged_by"] == "decision"
    assert len(service.calls) == 1
    assert service.calls[0]["condition_snapshot"] == expected_snapshot(value)
    assert service.calls[0]["condition"] == expected_snapshot(value)["condition"]
    assert service.calls[0]["review_context"]["allowed_states"] == expected_snapshot(value)["allowed_states"]
    assert (tmp_path / "responses" / (original.command_id + ".json")).read_bytes() == raw


@pytest.mark.parametrize("timeout", [False, True])
def test_native_proof_stays_local_and_trusted_timeout_shares_template_dispatch(tmp_path, monkeypatch, timeout):
    value, service = template_plan(native=True, source="input"), OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    original = timeout_original(s) if timeout else complete_original(s)
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed"
    assert terminal["history"][0]["execution_request_id"] == original.command_id
    assert terminal["history"][0]["judged_by"] == ("decision" if timeout else "native_condition")
    assert len(service.calls) == int(timeout)
    if timeout:
        assert service.calls[0]["condition_snapshot"] == expected_snapshot(value)


def test_template_always_main_holds_complete_native_proof_without_api(tmp_path, monkeypatch):
    value, service = template_plan(native=True, policy="always_main"), OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    complete_original(s)
    waiting = s.runtime.tick(force=True)
    assert waiting["wait_reason"] == "verification_required" and waiting["history"] == []
    assert waiting["review_packet"]["reason"] == "decision_always_main"
    assert waiting["review_packet"]["condition_snapshot"] == expected_snapshot(value)
    assert service.calls == []


@pytest.mark.parametrize("where", ["source", "state", "inputs"])
def test_reopen_rejects_snapshot_digest_or_input_drift(tmp_path, monkeypatch, where):
    s = scene(tmp_path, monkeypatch, source=template_plan(source="input"))
    state = s.runtime.backend.status(s.run_id)
    if where == "source":
        path = s.runtime.backend._source_path(state["plan_id"])
        value = read_json_snapshot(path)
        value["condition_snapshots"]["step-0"]["typed_parameters"]["record_id"] = "OTHER"
    else:
        path = s.runtime.backend._path(s.run_id)
        value = read_json_snapshot(path)
        if where == "state":
            value["condition_snapshots_sha256"] = "a" * 64
        else:
            value["inputs"]["record"] = "OTHER"
    write_json_snapshot(path, value)
    with pytest.raises(ValueError):
        TaskPlanBackend(tmp_path, owner_id="owner-1").status(s.run_id)
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def test_backend_independently_rebuilds_after_forged_sender_snapshot(tmp_path, monkeypatch):
    from app.execution import task_plan_verification as module
    value, service = template_plan(), OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    complete_original(s, native=False)
    original_assess = module.assess
    def forge(service, binding, *, v2):
        other = deepcopy(value)
        other["steps"][0]["verification"]["condition_binding"]["typed_parameters"]["record_id"]["value"] = "OTHER"
        binding["condition_snapshot"] = expected_snapshot(other)
        binding["condition"] = binding["condition_snapshot"]["condition"]
        return original_assess(service, binding, v2=v2)
    monkeypatch.setattr(module, "assess", forge)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert waiting["wait"]["error"]["message"] == "task_plan_decision_binding_changed"
    assert len(service.calls) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1


def test_last_authentication_cannot_mutate_snapshot_before_adoption(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=template_plan(), decision=service)
    complete_original(s, native=False)
    validate, calls = service.validate_result, []
    def late(value, **binding):
        calls.append(True)
        valid = validate(value, **binding)
        if len(calls) == 2:
            binding["condition_snapshot"]["typed_parameters"]["record_id"] = "LATE"
        return valid
    monkeypatch.setattr(service, "validate_result", late)
    waiting = s.runtime.tick(force=True)
    assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
    assert "condition" in waiting["wait"]["error"]["message"]


def test_auto_observation_reuses_frozen_template_for_both_assessments(tmp_path, monkeypatch):
    from tests.test_task_plan_observation import observation_scene
    value = template_plan(source="input", wait=True)
    s, original, clock, captures = observation_scene(tmp_path, monkeypatch, source=value)
    assert s.runtime.tick(force=True)["observation_pending"] is True
    clock.seconds = 1.6
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed" and len(captures) == 1
    assert len(s.co._decision_service.calls) == 2
    assert all(call["condition_snapshot"] == expected_snapshot(value) for call in s.co._decision_service.calls)
    assert terminal["history"][0]["execution_request_id"] == original.command_id


def test_manual_v3_inherits_template_and_settles_original_wait(tmp_path, monkeypatch):
    from tests.test_task_plan_manual_observation import manual_scene, module, observe_request, snapshot
    from tests.test_task_plan_adaptive_review import review_request
    value = template_plan(source="input")
    s, original, waiting, captures, _ = manual_scene(tmp_path, monkeypatch, source=value)
    module().observe_task_plan(s.runtime, observe_request(s, waiting))
    current = snapshot(s)
    assert current["review_packet"]["schema"] == "review_packet.v3"
    assert current["review_packet"]["condition_snapshot"] == expected_snapshot(value)
    assert current["wait"] == waiting["wait"] and len(captures) == 1
    reviewed = s.runtime.control(review_request(s, current, original), "template-manual-review")
    assert reviewed["status"] == "completed" and len(s.co._decision_service.calls) == 1


def test_source_drift_while_reading_original_frame_is_rejected_before_dispatch(tmp_path, monkeypatch):
    from app.execution import task_plan_verification as module
    service = OfflineAssessment(disposition="continue")
    s = scene(tmp_path, monkeypatch, source=template_plan(), decision=service)
    complete_original(s, native=False)
    state = s.runtime.backend.status(s.run_id)
    frame_reader = module.decision_frame
    def drift(*args, **kwargs):
        frame = frame_reader(*args, **kwargs)
        path = s.runtime.backend._source_path(state["plan_id"])
        source = read_json_snapshot(path)
        source["condition_snapshots"]["step-0"]["typed_parameters"]["record_id"] = "LATE"
        write_json_snapshot(path, source)
        return frame
    monkeypatch.setattr(module, "decision_frame", drift)
    with pytest.raises(ValueError, match="condition_source_binding"):
        s.runtime.tick(force=True)
    assert service.calls == []
    assert read_json_snapshot(s.runtime.backend._path(s.run_id))["history"] == []


def test_backend_cannot_bypass_template_always_main_with_native_settlement(tmp_path, monkeypatch):
    value = template_plan(native=True, policy="always_main")
    s = scene(tmp_path, monkeypatch, source=value, decision=OfflineAssessment())
    original = complete_original(s)
    s.runtime.tick(force=True)
    state = s.runtime.backend.status(s.run_id)
    candidate = deepcopy(next(iter(state["verification_results"].values())))
    candidate.pop("review_packet")
    candidate.update(verdict="success", judged_by="native_condition", reason="declared_native_condition_met")
    with pytest.raises(ValueError, match="condition_always_main"):
        s.runtime.backend.record_verified_result(s.run_id, "forged-native", original.command_id, candidate)
    assert s.runtime.backend.status(s.run_id)["history"] == []


def test_packet_cannot_rebind_template_even_with_recomputed_packet_hash(tmp_path, monkeypatch):
    from app.execution.task_plan_review import validate_packet
    s = scene(tmp_path, monkeypatch, source=template_plan(source="input"), decision=OfflineAssessment())
    complete_original(s, native=False)
    waiting = s.runtime.tick(force=True)
    packet = deepcopy(waiting["review_packet"])
    other = template_plan()
    other["steps"][0]["verification"]["condition_binding"]["typed_parameters"]["record_id"]["value"] = "OTHER"
    packet["condition_snapshot"] = expected_snapshot(other)
    packet["expected_condition"] = packet["condition_snapshot"]["condition"]
    packet["packet_sha256"] = digest({key: value for key, value in packet.items() if key != "packet_sha256"})
    with pytest.raises(ValueError, match="condition_packet_binding"):
        validate_packet(packet, s.runtime.backend.status(s.run_id), tmp_path)


@pytest.mark.parametrize("hazard", ["output", "read_text", "states", "length"])
def test_template_contract_rejects_ambiguous_or_dynamic_meaning_before_dispatch(tmp_path, monkeypatch, hazard):
    value = template_plan()
    rule = value["steps"][0]["verification"]
    if hazard == "output":
        rule["condition_binding"]["typed_parameters"]["record_id"] = {"source": "output", "name": "record"}
    elif hazard == "read_text":
        value["steps"][0]["action"] = {"kind": "read_text", "goal": "Read dynamic content"}
    elif hazard == "states":
        rule["allowed_states"] = ["Other state"]
    else:
        rule["condition_binding"]["template"] = make_record_id_template(
            text_template="X" * 3988 + "{record_id}", max_length=160)
        rule["condition_binding"]["typed_parameters"]["record_id"]["value"] = "Y" * 160
    with pytest.raises(ValueError):
        scene(tmp_path, monkeypatch, source=value)
    assert list(tmp_path.glob("commands/*.json")) == []


def test_parameter_braces_quotes_and_chinese_remain_opaque_string_data(tmp_path, monkeypatch):
    import json
    value, service = template_plan(source="input"), OfflineAssessment(disposition="continue")
    record = '\u8bb0\u5f55-{record_id}-"\\input'
    value["inputs"]["record"] = record
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    complete_original(s, native=False)
    assert s.runtime.tick(force=True)["runner_state"] == "completed"
    assert service.calls[0]["condition_snapshot"]["typed_parameters"]["record_id"] == record
    assert service.calls[0]["condition"] == "The detail page record ID equals " + json.dumps(record, ensure_ascii=False) + "."


class LocalProvider:
    ready = True

    def __init__(self):
        self.calls = []

    def judge(self, payload):
        self.calls.append(deepcopy(payload))
        return {"request_sha256": payload["request_sha256"], "predicates": {
            name: {"type": "predicate", "probability": .98 if name == "condition_met" else .01}
            for name in payload["enabled_predicates"]},
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            "http_elapsed_ms": 0, "server_processing_ms": None, "provider_request_id": "offline-execution-1"}


@pytest.mark.parametrize("mode", ["auto", "shadow"])
def test_backend_cannot_bypass_host_always_main_with_template_native_settlement(tmp_path, monkeypatch, mode):
    from app.judgment.profile import DecisionProfile
    from app.judgment.service import DecisionService
    value, provider = template_plan(native=True), LocalProvider()
    service = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
        "contract_version": "decision_profile.v2", "mode": mode, "review_policy": "always_main"}),
        provider=provider)
    try:
        s = scene(tmp_path, monkeypatch, source=value, decision=service)
        original = complete_original(s)
        waiting = s.runtime.tick(force=True)
        assert waiting["wait_reason"] == "verification_required" and waiting["history"] == []
        assert waiting["review_packet"]["reason"] == "decision_always_main"
        state = s.runtime.backend.status(s.run_id)
        candidate = deepcopy(next(iter(state["verification_results"].values())))
        candidate.pop("review_packet")
        candidate.update(verdict="success", judged_by="native_condition", reason="declared_native_condition_met")
        with pytest.raises(ValueError, match="condition_always_main"):
            s.runtime.backend.record_verified_result(s.run_id, "forged-host-native", original.command_id,
                candidate, decision_service=service)
        assert s.runtime.backend.status(s.run_id)["history"] == []
        assert provider.calls == []
    finally:
        service.close()


@pytest.mark.parametrize("disabled", ["off", "enabled_false"])
def test_disabled_host_always_main_keeps_template_native_proof_local(tmp_path, monkeypatch, disabled):
    from app.judgment.profile import DecisionProfile
    from app.judgment.service import DecisionService
    provider = LocalProvider()
    service = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
        "contract_version": "decision_profile.v2", "mode": "off" if disabled == "off" else "auto",
        "review_policy": "always_main"}), provider=provider)
    if disabled == "enabled_false":
        service.enabled = False
    try:
        s = scene(tmp_path, monkeypatch, source=template_plan(native=True), decision=service)
        complete_original(s)
        terminal = s.runtime.tick(force=True)
        assert terminal["runner_state"] == "completed"
        assert terminal["history"][0]["judged_by"] == "native_condition"
        assert provider.calls == []
    finally:
        service.close()


@pytest.mark.parametrize("record", ["REC-A", "REC-B"])
def test_actual_service_authenticates_plan_input_and_reopen_reuses_ledger_without_dispatch(tmp_path, monkeypatch, record):
    from app.judgment.profile import DecisionProfile
    from app.judgment.service import DecisionService
    value = template_plan(source="input")
    value["inputs"]["record"] = record
    frozen = expected_snapshot(value)
    profile = DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "mode": "auto",
        "auto_condition_templates": [{key: frozen[key] for key in
            ("condition_template_id", "revision", "template_sha256")}]})
    provider = LocalProvider()
    service = DecisionService(tmp_path, profile=profile, provider=provider)
    validate, authenticated = service.validate_result, []
    def authenticate(result, **binding):
        authenticated.append(deepcopy(binding))
        return validate(result, **binding)
    monkeypatch.setattr(service, "validate_result", authenticate)
    s = scene(tmp_path, monkeypatch, source=value, decision=service)
    original = complete_original(s, native=False)
    terminal = s.runtime.tick(force=True)
    assert terminal["runner_state"] == "completed" and terminal["history"][0]["judged_by"] == "decision"
    assert len(authenticated) >= 2 and all(item["condition_snapshot"] == frozen for item in authenticated)
    assert len(provider.calls) == 1 and provider.calls[0]["condition"] == frozen["condition"]
    assert "condition_snapshot" not in provider.calls[0]
    saved = read_json_snapshot(tmp_path / "task-plan-decisions" / (original.command_id + ".json"))
    assert saved["binding"]["condition_snapshot"] == frozen
    assert saved["result"]["condition_snapshot"]["typed_parameters"] == {"record_id": record}
    service.close()
    reopened_provider = LocalProvider()
    reopened = DecisionService(tmp_path, profile=profile, provider=reopened_provider)
    try:
        assert reopened.validate_result(saved["result"], **saved["binding"]) is True
        assert reopened.validate_result(saved["result"]) is False
        assert reopened.evaluate(**saved["binding"]) == saved["result"]
        other = template_plan(source="input")
        other["inputs"]["record"] = "REC-B" if record == "REC-A" else "REC-A"
        changed = {**saved["binding"], **{"condition_snapshot": expected_snapshot(other),
            "condition": expected_snapshot(other)["condition"]}}
        assert reopened.validate_result(saved["result"], **changed) is False
        assert reopened.evaluate(**changed)["status"] == "conflict"
        assert reopened_provider.calls == []
        assert TaskPlanBackend(tmp_path, owner_id="owner-1").status(s.run_id)["status"] == "completed"
    finally:
        reopened.close()


def test_actual_service_unknown_template_never_falls_back_to_string_allowlist(tmp_path, monkeypatch):
    from app.judgment.profile import DecisionProfile
    from app.judgment.service import DecisionService
    value = template_plan(source="input")
    frozen, provider = expected_snapshot(value), LocalProvider()
    profile = DecisionProfile.model_validate({"contract_version": "decision_profile.v2", "mode": "auto",
        "auto_conditions": [frozen["condition"]], "auto_condition_templates": []})
    service = DecisionService(tmp_path, profile=profile, provider=provider)
    try:
        s = scene(tmp_path, monkeypatch, source=value, decision=service)
        original = complete_original(s, native=False)
        waiting = s.runtime.tick(force=True)
        assert waiting["history"] == [] and waiting["wait_reason"] == "verification_required"
        assert waiting["review_packet"]["reason"] == "decision_condition_template_not_allowlisted"
        assert waiting["review_packet"]["condition_snapshot"] == frozen
        saved = read_json_snapshot(tmp_path / "task-plan-decisions" / (original.command_id + ".json"))
        assert saved["validated"] is True and saved["result"]["status"] == "skipped"
        assert service.validate_result(saved["result"], **saved["binding"]) is True
        assert service.evaluate(**saved["binding"]) == saved["result"] and provider.calls == []
        assert len(list(tmp_path.glob("commands/*.json"))) == 1
    finally:
        service.close()
