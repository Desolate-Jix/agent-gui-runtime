"""学习模板必须绑定已保存程序、原启动参数和原回执。"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.core.decision_configuration import freeze_decision_profile
from app.desktop_review.external_mapping import canonical_json_bytes
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.judgment.condition_templates import make_record_id_template, resolve_condition_binding
from app.learning_memory.workflow_program import _step_rules, WorkflowProgramService
from app.learning_memory.workflow_trial import TrialService
from tests.test_workflow_decision_adaptive import AdaptiveDecisionDouble
from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes


def binding(*, source="input", policy="adaptive", revision=1, states=None):
    template = make_record_id_template(revision=revision, review_policy=policy,
        allowed_states=states or ["The requested record detail is visible."])
    return {"schema": "condition_binding.v1", "template": template,
        "typed_parameters": {"record_id": {"source": "input", "name": "query"}
            if source == "input" else {"source": "literal", "value": "R-17"}}}


def template_program(services, *, rule=None, reviewed=True):
    programs, trials, saved, session = services
    value = deepcopy(saved["definition"])
    value["steps"] = value["steps"][:1]
    value["steps"][0].update(outputs=[], success_conditions=[],
        verification=rule or {"kind": "agent_judgment", "condition_binding": binding()},
        branches={"success": None, "failure": None, "uncertain": None})
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "template-save")
    if reviewed:
        value = deepcopy(saved["definition"])
        value["steps"][0]["review_status"] = "reviewed"
        saved = programs.save(WORKFLOW, saved["content_sha256"], value, "template-review")
    return programs, trials, saved, session


def template_scene(services, monkeypatch, *, service=None, rule=None, image_raw=None):
    programs, trials, saved, session = template_program(services, rule=rule)
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "R-17"}, "template-start")
    ticket = trials.prepare(run["run_id"], "template-prepare")
    path = response(session, ticket)
    original = read_json_snapshot(path)
    original["result"].update(target_identity={"target_window_handle": 1, "process_id": 2,
        "process_create_time": 3.0}, capture={"capture_id": "before"})
    write_json_snapshot(path, original)
    image = session / "template-after.png"
    if image_raw is None:
        Image.new("RGB", (80, 60), "white").save(image)
    else:
        image.write_bytes(image_raw)
    frame = {"capture_id": "after", "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
        "window_identity": {"handle": 1, "process_id": 2, "process_create_time": 3.0},
        "image_size": {"width": 80, "height": 60}, "window_rect": [0, 0, 80, 60]}
    captures = []
    def capture(*args, **kwargs):
        captures.append(True)
        return deepcopy(frame), {}
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    @contextmanager
    def workspace(root):
        yield programs.library
    monkeypatch.setattr("app.learning_memory.workspace.MemoryWorkspace", workspace)
    co = SimpleNamespace(_memory_library_root=programs.library._workspace_root,
        _owner=SimpleNamespace(call=lambda f: f()), _decision_service=service)
    from app.learning_memory.runtime_verification import verify_trial_step
    def verify(request_id="template-verify"):
        return verify_trial_step(co, session_dir=session, request_id=request_id,
            request={"action": "verify", "run_id": run["run_id"],
                "execution_request_id": ticket["execution_request_id"]})
    return SimpleNamespace(programs=programs, trials=trials, saved=saved, run=run, ticket=ticket,
        session=session, captures=captures, verify=verify)


def decision(template=None, *, approved=True, mode="auto"):
    service = AdaptiveDecisionDouble(disposition="continue", adopted=mode == "auto")
    template = template or binding()["template"]
    identity = SimpleNamespace(**{key: template[key] for key in
        ("condition_template_id", "revision", "template_sha256")})
    service.profile = SimpleNamespace(**{**vars(service.profile), "mode": mode,
        "auto_condition_templates": (identity,) if approved else ()})
    return service


def test_template_definition_saves_reopens_and_freezes_inputs(services):
    programs, trials, saved, session = template_program(services)
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "R-17"}, "typed-start")
    expected = resolve_condition_binding(binding(), {"query": "R-17"})
    assert run["condition_snapshots"] == {"search": expected}
    assert TrialService(programs.library, session).status(run["run_id"]) == run
    assert trials.start(WORKFLOW, saved["program_id"], "search", {"query": "R-17"}, "typed-start") == run
    assert programs.load(WORKFLOW, saved["program_id"]) == saved


@pytest.mark.parametrize("damage", ["both", "outputs", "read_spec", "read_text", "unknown_input", "number_input", "output_ref"])
def test_template_definition_rejects_conflicts_and_dynamic_reads(damage):
    step = {"action": {"kind": "click"}, "outputs": [],
        "verification": {"kind": "agent_judgment", "condition_binding": binding()}}
    inputs = {"query": "text"}
    if damage == "both":
        step["verification"]["decision_condition"] = "Text fallback must not win."
    elif damage == "outputs":
        step["outputs"] = [{"name": "read", "type": "text"}]
    elif damage == "read_spec":
        step["read_spec"] = {}
    elif damage == "read_text":
        step["action"]["kind"] = "read_text"
    elif damage == "unknown_input":
        inputs = {}
    elif damage == "number_input":
        inputs["query"] = "number"
    else:
        step["verification"]["condition_binding"]["typed_parameters"]["record_id"] = {
            "source": "output", "name": "query"}
    with pytest.raises(ValueError):
        _step_rules(step, inputs, {}, {})


def test_template_semantic_change_requires_new_template_revision_and_review(services):
    programs, _, saved, _ = template_program(services)
    value = deepcopy(saved["definition"])
    value["steps"][0]["verification"]["condition_binding"] = binding(states=["Different allowed state."])
    with pytest.raises(ValueError, match="template.*revision"):
        programs.save(WORKFLOW, saved["content_sha256"], value, "same-template-revision")
    value["steps"][0]["verification"]["condition_binding"] = binding(revision=2, states=["Different allowed state."])
    newer = programs.save(WORKFLOW, saved["content_sha256"], value, "new-template-revision")
    assert newer["definition"]["steps"][0]["review_status"] == "pending"
    assert programs.load(WORKFLOW, saved["program_id"]) == saved


def test_template_input_declaration_change_invalidates_review(services):
    programs, _, saved, _ = template_program(services)
    value = deepcopy(saved["definition"])
    value["steps"][0]["action"] = {"kind": "click", "goal": "Open record"}
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "template-click")
    value = deepcopy(saved["definition"])
    value["steps"][0]["review_status"] = "reviewed"
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "template-click-review")
    value = deepcopy(saved["definition"])
    value["inputs"][0]["required"] = False
    newer = programs.save(WORKFLOW, saved["content_sha256"], value, "template-input-declaration")
    assert newer["definition"]["steps"][0]["review_status"] == "pending"


@pytest.mark.parametrize("damage", ["input", "snapshot", "both", "drop"])
def test_original_start_binds_inputs_and_snapshots_before_prepare(services, damage):
    _, trials, saved, _ = template_program(services)
    run = trials.start(WORKFLOW, saved["program_id"], "search", {"query": "R-17"}, "typed-start")
    changed = deepcopy(run)
    if damage in {"input", "both"}:
        changed["inputs"]["query"] = "R-99"
    if damage in {"snapshot", "both"}:
        changed["condition_snapshots"] = {"search": resolve_condition_binding(binding(), {"query": "R-99"})}
    if damage == "drop":
        changed.pop("condition_snapshots")
    write_json_snapshot(trials._path(run["run_id"]), changed)
    with pytest.raises(ValueError, match="workflow_condition"):
        trials.prepare(run["run_id"], "tampered-prepare")
    assert not list(trials.session.glob("commands/*.json"))


def test_template_resolution_failure_precedes_any_trial_write(services):
    _, trials, saved, _ = template_program(services)
    with pytest.raises(ValueError, match="condition_parameter"):
        trials.start(WORKFLOW, saved["program_id"], "search", {"query": ""}, "empty-template-start")
    assert not list(trials.root.glob("trial-*.json"))


def test_template_real_trial_authenticates_snapshot_and_replays_once(services, monkeypatch):
    service = decision()
    s = template_scene(services, monkeypatch, service=service)
    result = s.verify()
    assert result["status"] == "completed"
    assert len(s.captures) == len(service.calls) == 1
    call = service.calls[0]
    assert call["condition_snapshot"] == s.run["condition_snapshots"]["search"]
    assert call["condition"] == call["condition_snapshot"]["condition"]
    assert call["review_context"]["allowed_states"] == binding()["template"]["allowed_states"]
    assert s.verify("another-template-verify") == result
    assert len(service.calls) == 1


@pytest.mark.parametrize("setting", ["unapproved", "v1", "always_main", "shadow"])
def test_template_route_never_weakens_policy_or_string_allowlist(services, monkeypatch, setting):
    bound = binding(policy="always_main" if setting == "always_main" else "adaptive")
    service = decision(bound["template"], approved=setting != "unapproved", mode="shadow" if setting == "shadow" else "auto")
    service.profile.auto_conditions = (resolve_condition_binding(bound, {"query": "R-17"})["condition"],)
    if setting == "v1":
        service.profile.contract_version = "decision_profile.v1"
    s = template_scene(services, monkeypatch, service=service,
        rule={"kind": "agent_judgment", "condition_binding": bound})
    result = s.verify()
    assert result["status"] == "verification_required" and s.trials.status(s.run["run_id"])["history"] == []
    if setting == "shadow":
        assert len(service.calls) == 1
    else:
        assert service.calls == s.captures == []


@pytest.mark.parametrize("damage", ["input", "both", "drop"])
def test_mid_decision_state_change_cannot_adopt(services, monkeypatch, damage):
    service = decision()
    s = template_scene(services, monkeypatch, service=service)
    def change():
        state = read_json_snapshot(s.trials._path(s.run["run_id"]))
        if damage != "drop":
            state["inputs"]["query"] = "R-99"
        if damage == "both":
            state["condition_snapshots"]["search"] = resolve_condition_binding(binding(), state["inputs"])
        if damage == "drop":
            state.pop("condition_snapshots")
        write_json_snapshot(s.trials._path(s.run["run_id"]), state)
    service.on_evaluate = change
    with pytest.raises(ValueError, match="workflow_condition"):
        s.verify()
    assert read_json_snapshot(s.trials._path(s.run["run_id"]))["history"] == []
    assert len(service.calls) == 1


@contextmanager
def offline_service(session, monkeypatch):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "condition_met", "probability": 0.98},
            {"type": "predicate", "name": "visible_error", "probability": 0.01},
            {"type": "predicate", "name": "needs_agent_review", "probability": 0.01}],
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}})
    monkeypatch.setenv("TEMPLATE_SYNTHETIC_KEY", "synthetic-only")
    template = binding()["template"]
    identity = {key: template[key] for key in ("condition_template_id", "revision", "template_sha256")}
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        api_key_env="TEMPLATE_SYNTHETIC_KEY", auto_condition_templates=[identity])
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        service = DecisionService(session, profile=profile, provider=OpenAIDecisionsProvider(
            api_key_env="TEMPLATE_SYNTHETIC_KEY", client=client))
        freeze_decision_profile(service)
        try:
            yield service, calls
        finally:
            service.close()


@pytest.mark.parametrize("source", ["input", "literal"])
def test_real_offline_provider_authenticates_template_binding(services, monkeypatch, source):
    with offline_service(services[3], monkeypatch) as (service, calls):
        s = template_scene(services, monkeypatch, service=service,
            rule={"kind": "agent_judgment", "condition_binding": binding(source=source)})
        result = s.verify()
        assert result["status"] == "completed" and result["history"][0]["judged_by"] == "decision"
        stored = read_json_snapshot(s.session / "workflow-decisions/template-verify.result.json")
        expected = resolve_condition_binding(binding(source=source), s.run["inputs"])
        assert stored["binding"]["condition_snapshot"] == stored["result"]["condition_snapshot"] == expected
        assert service.validate_result(stored["result"], **stored["binding"]) is True
        forged = deepcopy(stored["binding"])
        forged["condition_snapshot"] = resolve_condition_binding(binding(), {"query": "R-99"})
        forged["condition"] = forged["condition_snapshot"]["condition"]
        assert service.validate_result(stored["result"], **forged) is False
        assert s.verify("template-replay") == result and len(calls) == len(s.captures) == 1


@pytest.mark.parametrize("policy", ["adaptive", "always_main"])
def test_complete_image_proof_stays_local_with_template_policy(services, monkeypatch, policy, tmp_path):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    services[0].library._artifact_root = tmp_path
    check, raw, _, _ = sample(tmp_path)
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    rule = {"kind": "agent_judgment", "condition_binding": binding(policy=policy), "image_check": check}
    service = decision(rule["condition_binding"]["template"])
    s = template_scene(services, monkeypatch, service=service, rule=rule, image_raw=raw)
    result = s.verify()
    assert result["status"] == ("completed" if policy == "adaptive" else "verification_required")
    assert service.calls == [] and s.captures
    if policy == "always_main":
        assert result["local_verification"]["verdict"] == "success"
        assert s.trials.status(s.run["run_id"])["history"] == []


def test_same_definition_cannot_reuse_template_revision_with_different_semantics(services):
    programs, _, saved, _ = template_program(services)
    value = deepcopy(saved["definition"])
    second = deepcopy(value["steps"][0])
    second["step_id"] = "second"
    second["verification"]["condition_binding"] = binding(states=["Different state."])
    value["steps"].append(second)
    value["steps"][0]["branches"]["success"] = "second"
    with pytest.raises(ValueError, match="template.*revision"):
        programs.save(WORKFLOW, saved["content_sha256"], value, "definition-template-conflict")


@pytest.mark.parametrize("policy_source", ["template", "step", "global"])
def test_final_backend_cannot_adopt_local_image_while_main_review_is_required(
        services, monkeypatch, tmp_path, policy_source):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    services[0].library._artifact_root = tmp_path
    check, raw, _, _ = sample(tmp_path)
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    bound = binding(policy="always_main" if policy_source == "template" else "adaptive")
    rule = {"kind": "agent_judgment", "condition_binding": bound, "image_check": check}
    service = decision(bound["template"])
    if policy_source == "step":
        rule["review_policy"] = "always_main"
    if policy_source == "global":
        service.profile.review_policy = "always_main"
    s = template_scene(services, monkeypatch, service=service, rule=rule, image_raw=raw)
    paused = s.verify()
    assert paused["status"] == "verification_required" and paused["local_verification"]["verdict"] == "success"
    with pytest.raises(ValueError, match="workflow_decision_always_main"):
        s.trials.record_verified_result(s.run["run_id"], "template-verify", s.ticket["execution_request_id"],
            paused["local_verification"], decision_service=service)
    assert s.trials.status(s.run["run_id"])["history"] == [] and service.calls == []


def test_final_authentication_cannot_replace_original_inputs_and_snapshot(services, monkeypatch):
    service = decision()
    s = template_scene(services, monkeypatch, service=service)
    original_validate, validations = service.validate_result, []
    def validate(result, **call):
        validations.append(True)
        valid = original_validate(result, **call)
        if len(validations) == 3:
            state = read_json_snapshot(s.trials._path(s.run["run_id"]))
            state["inputs"]["query"] = "R-99"
            state["condition_snapshots"]["search"] = resolve_condition_binding(binding(), state["inputs"])
            write_json_snapshot(s.trials._path(s.run["run_id"]), state)
        return valid
    service.validate_result = validate
    with pytest.raises(ValueError, match="workflow_condition_original_inputs_changed"):
        s.verify()
    assert len(validations) == 3 and len(service.calls) == len(s.captures) == 1
    assert read_json_snapshot(s.trials._path(s.run["run_id"]))["history"] == []


def test_legacy_trial_keeps_original_hash_and_omits_template_fields(services):
    _, trials, saved, session = services
    inputs = {"query": "legacy"}
    run = trials.start(WORKFLOW, saved["program_id"], "search", inputs, "legacy-start")
    request_sha = sha256(canonical_json_bytes([WORKFLOW, saved["program_id"], "search", inputs])).hexdigest()
    assert "condition_snapshots" not in run
    assert run["run_id"] == "trial-" + sha256(canonical_json_bytes([str(session), "legacy-start", request_sha])).hexdigest()
    assert read_json_snapshot(session / "workflow-trials/requests.json") == {
        "legacy-start": {"run_id": run["run_id"], "request_sha256": request_sha}}


@pytest.mark.parametrize("policy_source", ["template", "step", "adaptive"])
def test_rehashed_rule_history_preserves_pinned_main_review_policy(
        services, monkeypatch, tmp_path, policy_source):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    from tests.test_workflow_recovery_history import catalog, verify
    services[0].library._artifact_root = tmp_path
    check, raw, _, _ = sample(tmp_path)
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    bound = binding(policy="always_main" if policy_source == "template" else "adaptive")
    rule = {"kind": "agent_judgment", "condition_binding": bound, "image_check": check}
    if policy_source == "step":
        rule["review_policy"] = "always_main"
    s = template_scene(services, monkeypatch, service=decision(bound["template"]), rule=rule, image_raw=raw)
    observed = s.verify()
    if policy_source == "adaptive":
        state = s.trials.status(s.run["run_id"])
    else:
        # 模拟旧结算缺口留下且重新计算请求摘要的规则历史，不能借恢复跳过人工审核。
        candidate = observed["local_verification"]
        state = s.trials._review(s.run["run_id"], "template-verify", s.ticket["execution_request_id"],
            candidate["verdict"], candidate["observations"]["values"], candidate["outputs"],
            verification_result=candidate)
    before = catalog(s.session)
    scene = s.trials, state, s.saved, s.session
    if policy_source == "adaptive":
        assert verify(scene)["history"] == state["history"]
    else:
        with pytest.raises(ValueError, match="workflow_recovery_history_main_review_required"):
            verify(scene)
    assert catalog(s.session) == before


@pytest.fixture
def template_recovery_scene(epoch_scene, services, monkeypatch):
    from tests import test_workflow_decision_recovery as recovery
    original_profile, original_save = recovery.DecisionProfile, WorkflowProgramService.save
    def profile(**kwargs):
        template = binding()["template"]
        kwargs["auto_condition_templates"] = [{key: template[key] for key in
            ("condition_template_id", "revision", "template_sha256")}]
        return original_profile(**kwargs)
    def save(self, workflow_id, expected_sha, definition, request_id, **kwargs):
        if request_id == "recovery-decision-save":
            definition = deepcopy(definition)
            definition["steps"][0]["verification"] = {"kind": "agent_judgment", "condition_binding": binding()}
        return original_save(self, workflow_id, expected_sha, definition, request_id, **kwargs)
    monkeypatch.setattr(recovery, "DecisionProfile", profile)
    monkeypatch.setattr(WorkflowProgramService, "save", save)
    scenario = recovery.decision_recovery_scene.__wrapped__(epoch_scene, services, monkeypatch,
        SimpleNamespace(param="v2"))
    try:
        yield next(scenario)
    finally:
        scenario.close()


def test_template_history_and_takeover_keep_original_source_without_replay(template_recovery_scene, monkeypatch):
    from app.execution.session_input_terminal import _catalog
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    from app.learning_memory.workspace import MemoryWorkspace
    from tests.test_workflow_decision_recovery import verify_history
    from tests.test_workflow_recovery_import import prepare, commit
    s = template_recovery_scene
    original = verify_history(s)
    assert "workflow-trials/requests.json" in original["files"]
    prepared = prepare(s)
    assert prepared["trial_state"]["condition_snapshots"] == s.original["condition_snapshots"]
    _, imported = commit(s, prepared)
    _, replay = commit(s, prepare(s))
    assert imported == replay
    with MemoryWorkspace(s.library_root) as library:
        trials = TrialService(library, s.new)
        state = trials.status(prepared["trial_state"]["run_id"])
        hashes = {name: sha256(raw).hexdigest() for name, raw in _catalog(s.new).items()}
        import app.learning_memory.workflow_condition_templates as conditions
        original_read = conditions.read_json_snapshot
        def no_unverified_claim(path):
            assert "workflow-takeovers" not in str(path)
            return original_read(path)
        monkeypatch.setattr(conditions, "read_json_snapshot", no_unverified_claim)
        verified = verify_recovery_history(library, s.new, state, s.program, file_hashes=hashes)
        assert verified["history"] == state["history"]
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1
    assert not list((s.new / "commands").glob("*.json"))


@pytest.mark.parametrize("damage", ["inputs_and_snapshot", "start_index", "envelope_snapshot"])
def test_rehashed_source_changes_cannot_forge_template_history(template_recovery_scene, damage):
    from tests.test_workflow_decision_recovery import verify_history
    s = template_recovery_scene
    if damage == "inputs_and_snapshot":
        s.original["inputs"]["query"] = "R-99"
        s.original["condition_snapshots"]["prefix"] = resolve_condition_binding(binding(), s.original["inputs"])
        write_json_snapshot(s.epoch.old / "workflow-trials" / (s.source_run_id + ".json"), s.original)
    elif damage == "start_index":
        path = s.epoch.old / "workflow-trials/requests.json"
        index = read_json_snapshot(path)
        index["source-start"]["request_sha256"] = "0" * 64
        write_json_snapshot(path, index)
    else:
        path = s.epoch.old / "workflow-observations/decision-verify.json"
        envelope = read_json_snapshot(path)
        envelope["condition_snapshot"] = resolve_condition_binding(binding(), {"query": "R-99"})
        write_json_snapshot(path, envelope)
    with pytest.raises(ValueError, match="workflow_condition"):
        verify_history(s)
    assert len(s.calls) == len(s.captures) == 1


@pytest.mark.parametrize("damage", ["both", "drop", "claim_changed_during_verification"])
def test_imported_template_inputs_are_bound_to_fixed_claim(template_recovery_scene, monkeypatch, damage):
    from app.execution.session_input_terminal import _catalog
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    from app.learning_memory.workflow_recovery_import import _claim_path
    from app.learning_memory.workspace import MemoryWorkspace
    from tests.test_workflow_recovery_import import prepare, commit
    s = template_recovery_scene
    prepared = prepare(s)
    commit(s, prepared)
    with MemoryWorkspace(s.library_root) as library:
        trials = TrialService(library, s.new)
        state = trials.status(prepared["trial_state"]["run_id"])
        if damage != "claim_changed_during_verification":
            if damage == "both":
                state["inputs"]["query"] = "R-99"
                state["condition_snapshots"]["prefix"] = resolve_condition_binding(binding(), state["inputs"])
            else:
                state.pop("condition_snapshots")
            write_json_snapshot(trials._path(state["run_id"]), state)
            with pytest.raises(ValueError, match="workflow_condition"):
                trials.status(state["run_id"])
        else:
            import app.learning_memory.workflow_recovery_import as recovery
            original_build = recovery._build
            def changed_claim(*args, **kwargs):
                result = original_build(*args, **kwargs)
                path = _claim_path(s.new, state["recovery_import"]["claim_id"])
                claim = read_json_snapshot(path)
                claim["unexpected"] = True
                write_json_snapshot(path, claim)
                return result
            monkeypatch.setattr(recovery, "_build", changed_claim)
            hashes = {name: sha256(raw).hexdigest() for name, raw in _catalog(s.new).items()}
            with pytest.raises(ValueError, match="ancestor_changed"):
                verify_recovery_history(library, s.new, state, s.program, file_hashes=hashes)
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1
