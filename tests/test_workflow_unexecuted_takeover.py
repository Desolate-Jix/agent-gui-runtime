"""显式零输入接管只沿全新隔离原票据；离线夹具不代表实机验收。"""
from copy import deepcopy
from hashlib import sha256
import json
import shutil
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.instant_command_queue import enqueue_command
from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
from app.learning_memory.workflow_verification import verify_current_effect
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, response, WORKFLOW
from tests.test_workflow_rule_definition import definition
from tests.test_workflow_terminal_recovery import terminal


@pytest.fixture
def build_unexecuted(epoch_scene, runtime_scene, monkeypatch):
    built = []
    def build(prefix_count=0, fact="valid", effect="failure"):
        assert not built, "one_fresh_source_per_test"
        built.append(True)
        epoch = epoch_scene
        source_runtime, source_trials, _, source, _ = runtime_scene
        programs = source_trials.programs
        saved = programs.load(WORKFLOW)
        value = definition(saved)
        if prefix_count:
            prefix = deepcopy(value["steps"][0])
            prefix.update(step_id="prefix", title="已核验上游",
                          branches={"success": "search", "failure": None, "uncertain": None})
            prefix.pop("verification")
            prefix["success_conditions"] = []
            value["steps"].insert(0, prefix)
        value["steps"][-1]["review_status"] = "reviewed"
        saved = programs.save(WORKFLOW, saved["content_sha256"], value, "fresh-resume-program")
        run = source_trials.start(WORKFLOW, saved["program_id"], "prefix" if prefix_count else "search",
                                  {"query": "fresh-query"}, "fresh-source-start")
        if prefix_count:
            prefix_ticket = source_trials.prepare(run["run_id"], "fresh-prefix-prepare")
            path = response(source, prefix_ticket)
            receipt = read_json_snapshot(path)
            receipt["result"]["steps"] = [{"operation": "execute_recognition_plan", "status": "returned",
                "action_executed": True, "receipt": {"phase": "returned", "response": {"success": True,
                    "data": {"execution_path": {"action_executed": True}}}}}]
            write_json_snapshot(path, receipt)
            source_trials.review(run["run_id"], "fresh-prefix-review", prefix_ticket["execution_request_id"],
                                 "success", {}, {"result_title": "verified-prefix"})
        pending = source_trials.prepare(run["run_id"], "fresh-search-prepare")
        source_runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "fresh-source-run")
        response(source, pending)
        # 所有来源事实在首次结算和准入之前完成；准入后不补写账本或 SHA。
        for folder in ("commands", "responses", "workflow-trials", "workflow-runners"):
            shutil.copytree(source / folder, epoch.old / folder, dirs_exist_ok=True)
        library_root = epoch.old.parent / "memory-library"
        shutil.copytree(programs.library._workspace_root, library_root / "desktop-review")
        identity = {"handle": 71, "process_id": 72, "process_create_time": 73.5}
        pointer = read_json_snapshot(epoch.old.parent / "latest-session.json")
        with MemoryWorkspace(library_root) as library:
            trials = TrialService(library, epoch.old)
            status = fact if fact in {"completed", "failed"} else "cancelled"
            action = True if fact == "action_true" else None if fact == "action_unknown" else False
            worker = terminal((source_runtime, trials, run, epoch.old, pending, pointer["host_identity"], 900002),
                              status=status, action=action)
            worker.update(completed=False, dispatch_in_progress=False, dispatch_attempts=[],
                          last_execution=None, pending_grounding=None)
            worker["result"]["target_identity"] = {"target_window_handle": identity["handle"],
                "process_id": identity["process_id"], "process_create_time": identity["process_create_time"]}
            if fact == "last_execution":
                worker["last_execution"] = {"operation": "execute_recognition_plan", "action_executed": False}
            if fact == "pending_grounding":
                worker["pending_grounding"] = {"request_id": "original-pending"}
            if fact == "dispatch_in_progress":
                worker["dispatch_in_progress"] = True
            if fact == "dispatch_attempt":
                worker["dispatch_attempts"] = [{"index": 1, "operation": "execute_recognition_plan",
                    "status": "returned", "action_executed": False}]
                worker["last_execution"] = {"attempt_index": 1, "operation": "execute_recognition_plan",
                    "receipt": {"phase": "returned", "response": {"success": False,
                        "data": {"execution_path": {"action_executed": False}}}}}
            acceptance_path = epoch.old / "responses" / (pending["execution_request_id"] + ".json")
            acceptance = read_json_snapshot(acceptance_path)
            acceptance["result"]["target_identity"] = deepcopy(worker["result"]["target_identity"])
            if fact == "acceptance_unknown":
                acceptance["result"]["action_executed"] = None
            elif fact == "acceptance_nested_true":
                acceptance["result"]["nested"] = {"previous_action_executed": True}
            write_json_snapshot(acceptance_path, acceptance)
            write_json_snapshot(epoch.old / "agent-commands" / (pending["execution_request_id"] + ".json"), worker)
            recovery = WorkflowTerminalRecovery(trials, host_identity=pointer["host_identity"], runner_pid=900002)
            recovery.settle(recovery.preview(run["run_id"]), "fresh-terminal-settle")
            original = trials.status(run["run_id"])
        before = old_bytes(epoch)
        preview = epoch.manager.preview_recovery()
        epoch.manager.recover_session("fresh-epoch-admission", preview["preview_sha256"])
        new = epoch.manager.session
        folder = new / "workflow-effects"
        folder.mkdir()
        image = folder / "current.png"
        Image.new("RGB", (160, 100), "white").save(image)
        image_hash = sha256(image.read_bytes()).hexdigest()
        reference = "workflow-effects/fresh-current.json"
        current = {"contract_version": "workflow_current_effect.v1", "source_run_id": run["run_id"],
            "source_step_id": "search", "source_execution_request_id": pending["execution_request_id"],
            "source_receipt_sha256": sha256(acceptance_path.read_bytes()).hexdigest(),
            "source_settlement_sha256": sha256(canonical_json_bytes(original["recovery_settlement"])).hexdigest(),
            "source_program_sha256": saved["content_sha256"],
            "source_action_executed": original["recovery_settlement"]["action_executed"],
            "session_name": new.name, "request_id": "fresh-current", "capture_id": "fresh-capture",
            "capture_sha256": image_hash, "window_identity": identity, "scope_id": "search-field",
            "evidence_ref": reference}
        observation = {key: deepcopy(current[key]) for key in ("session_name", "request_id", "capture_id",
            "capture_sha256", "window_identity", "scope_id", "evidence_ref")}
        observation.update(step_id="search", complete=effect != "uncertain", source="uia_value",
                           values={"field_value": "fresh-query" if effect == "success" else "not-yet-executed"})
        frame = {"image_path": str(image), "sha256": image_hash, "capture_id": current["capture_id"],
                 "image_size": {"width": 160, "height": 100}, "window_identity": identity}
        step = next(s for s in saved["definition"]["steps"] if s["step_id"] == "search")
        verified = verify_current_effect(step, inputs=original["inputs"], outputs={}, effect=current, observation=observation)
        if effect == "failure":
            assert verified["verdict"] == "failure" and verified["reason"] == "observed_value_conflict"
        envelope = {"contract_version": "workflow_takeover_observation.v1", "effect": current,
            "observation": observation, "frame": frame, "native_evidence": {},
            "measurement": {"started_ns": 1, "ended_ns": 2}, "verification": verified}
        write_json_snapshot(new / reference, envelope)
        monkeypatch.setattr("app.learning_memory.workflow_runner.MemoryWorkspace", MemoryWorkspace)
        return SimpleNamespace(epoch=epoch, library_root=library_root, new=new, old_before=before,
            source_run_id=run["run_id"], old_eid=pending["execution_request_id"], envelope=envelope,
            effect_ref=reference, original=original, prefix_count=prefix_count)
    return build


def prepare(scene, request_id="resume-preview", resolution="resume_unexecuted"):
    from app.learning_memory.workflow_recovery_import import prepare_recovery_import
    kwargs = {} if resolution is None else {"resolution": resolution}
    return prepare_recovery_import(scene.library_root, scene.new, admission_request_id="fresh-epoch-admission",
        source_run_id=scene.source_run_id, effect_evidence_ref=scene.effect_ref, request_id=request_id, **kwargs)


def offline_runtime(scene):
    return WorkflowRuntime(scene.new, SimpleNamespace(_memory_library_root=scene.library_root))


def commit(scene, prepared, runtime=None):
    from app.learning_memory.workflow_recovery_import import commit_recovery_import
    runtime = runtime or offline_runtime(scene)
    with MemoryWorkspace(scene.library_root) as library:
        result = commit_recovery_import(TrialService(library, scene.new), runtime.runner, prepared, mode="single")
    return runtime, result


@pytest.mark.parametrize("prefix_count", [0, 1])
def test_resume_import_keeps_unexecuted_step_and_real_prefix(build_unexecuted, prefix_count):
    scene = build_unexecuted(prefix_count)
    prepared = prepare(scene)
    state = prepared["trial_state"]
    marker = state["recovery_import"]
    assert marker["contract_version"] == "workflow_recovery_import.v2"
    assert marker["resolution"] == "resume_unexecuted"
    assert state["current_step_id"] == "search" and state["status"] == "ready" and state["pending"] is None
    assert marker["consumed_step_ids"] == (["prefix"] if prefix_count else [])
    assert [row["step_id"] for row in state["history"]] == marker["consumed_step_ids"]
    assert state["outputs"] == ({"prefix.result_title": "verified-prefix"} if prefix_count else {})
    assert all(row["step_id"] != "search" for row in state["history"])
    assert scene.original["recovery_settlement"]["terminal_status"] == "cancelled"
    runtime, snapshot = commit(scene, prepared)
    assert snapshot["wait_reason"] == "takeover_ready"
    assert runtime.runner._load(snapshot["run_id"])["seen_steps"] == marker["consumed_step_ids"]
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before
    before = {p: p.read_bytes() for p in scene.new.rglob("*") if p.is_file()}
    assert commit(scene, prepared, runtime)[1] == snapshot
    assert {p: p.read_bytes() for p in scene.new.rglob("*") if p.is_file()} == before
    request = {"action": "continue", "run_id": snapshot["run_id"], "wait_id": snapshot["wait"]["wait_id"]}
    runtime.control(request, "fresh-resume-continue")
    runtime.tick(force=True)
    commands = list((scene.new / "commands").glob("*.json"))
    assert len(commands) == 1 and commands[0].stem != scene.old_eid
    pending = runtime.runner._trial("status", snapshot["run_id"])["pending"]
    assert pending["step_id"] == "search" and pending["execution_request_id"] == commands[0].stem
    runtime.control(request, "fresh-resume-continue")
    runtime.tick(force=True)
    assert list((scene.new / "commands").glob("*.json")) == commands
    assert old_bytes(scene.epoch) == scene.old_before


def test_default_adopt_success_still_refuses_false_effect(build_unexecuted):
    scene = build_unexecuted()
    with pytest.raises(ValueError, match="current_effect_not_success"):
        prepare(scene, resolution=None)


@pytest.mark.parametrize("effect", ["success", "uncertain"])
def test_resume_never_uses_success_or_uncertain_effect(build_unexecuted, effect):
    scene = build_unexecuted(effect=effect)
    with pytest.raises(ValueError):
        prepare(scene)
    assert old_bytes(scene.epoch) == scene.old_before


@pytest.mark.parametrize("fact", ["completed", "failed", "action_true", "action_unknown", "last_execution",
    "pending_grounding", "dispatch_attempt", "dispatch_in_progress", "acceptance_unknown", "acceptance_nested_true"])
def test_incompatible_original_input_facts_are_refused(build_unexecuted, fact):
    # 原结算或准入若先拒绝未知事实，也是必须保留的拒绝；不补 SHA 绕过。
    with pytest.raises(ValueError):
        scene = build_unexecuted(fact=fact)
        prepare(scene)


def public_scene(scene, monkeypatch):
    from app.learning_memory import workflow_takeover_observation as observer
    calls = []
    changes = {}
    def read(coordinator, **kwargs):
        calls.append(kwargs)
        frame = deepcopy(scene.envelope["frame"])
        control = {"control_id": "query", "runtime_id": [1, 71, 8], "control_type": "Edit",
            "automation_id": "query", "name": "Search", "bbox": {"x": 10, "y": 10, "w": 80, "h": 20}}
        if changes.get("control"):
            control["runtime_id"][-1] += 1
        value = "different-conflicting-value" if changes.get("value") else "not-yet-executed"
        return {"frame": frame, "window_identity": frame["window_identity"], "capture_id": frame["capture_id"],
            "capture_sha256": frame["sha256"], "scope_id": "search-field", "source": "uia_value",
            "complete": True, "values": {"field_value": value}, "evidence": {"selected_control": control}}
    monkeypatch.setattr(observer, "read_step_observation", read)
    co = SimpleNamespace(_memory_library_root=scene.library_root, _owner=SimpleNamespace(call=lambda fn: fn()))
    return SimpleNamespace(scene=scene, runtime=WorkflowRuntime(scene.new, co), calls=calls, changes=changes)


def control(public, request_id, request):
    command = {"kind": "learning_workflow", "request": deepcopy(request)}
    enqueue_command(public.scene.new, request_id, command)
    result = public.runtime.control(request, request_id)
    write_json_snapshot(public.scene.new / "responses" / (request_id + ".json"),
                        {"command": command, "status": "returned", "result": result})
    return result


def public_preview(public):
    return control(public, "public-resume-preview", {"action": "takeover_preview",
        "admission_request_id": "fresh-epoch-admission", "source_run_id": public.scene.source_run_id,
        "resolution": "resume_unexecuted"})


def public_commit(public, view, request_id="public-resume-commit"):
    return control(public, request_id, {"action": "takeover_commit", "preview_request_id": "public-resume-preview",
        "preview_sha256": view["preview_sha256"], "mode": "single"})


@pytest.mark.parametrize("prefix_count", [0, 1])
def test_public_preview_commit_reobserve_and_inherit_exact_resolution(build_unexecuted, monkeypatch, prefix_count):
    scene = build_unexecuted(prefix_count)
    public = public_scene(scene, monkeypatch)
    view = public_preview(public)
    assert len(public.calls) == 1 and view["next_step_id"] == "search"
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    snapshot = public_commit(public, view)
    assert len(public.calls) == 2 and snapshot["wait_reason"] == "takeover_ready"
    assert snapshot["recovery_import"]["resolution"] == "resume_unexecuted"
    assert public.runtime._enabled_run is None
    assert all(read_json_snapshot(p)["kind"] == "learning_workflow" for p in (scene.new / "commands").glob("*.json"))
    assert public_commit(public, view, "public-resume-readback") == snapshot
    assert len(public.calls) == 2
    request = {"action": "continue", "run_id": snapshot["run_id"], "wait_id": snapshot["wait"]["wait_id"]}
    control(public, "public-fresh-continue", request)
    public.runtime.tick(force=True)
    inputs = [p for p in (scene.new / "commands").glob("*.json") if read_json_snapshot(p)["kind"] != "learning_workflow"]
    assert len(inputs) == 1 and inputs[0].stem != scene.old_eid
    control(public, "public-fresh-continue", request)
    public.runtime.tick(force=True)
    assert [p for p in (scene.new / "commands").glob("*.json") if read_json_snapshot(p)["kind"] != "learning_workflow"] == inputs
    assert old_bytes(scene.epoch) == scene.old_before


@pytest.mark.parametrize("change", ["control", "value"])
def test_public_commit_rejects_reobserved_scope_drift(build_unexecuted, monkeypatch, change):
    public = public_scene(build_unexecuted(), monkeypatch)
    view = public_preview(public)
    public.changes[change] = True
    with pytest.raises(ValueError):
        public_commit(public, view)
    assert not list((public.scene.new.parent / "workflow-takeovers").glob("*.json"))


def test_commit_cannot_accept_request_resolution_override(build_unexecuted):
    from app.learning_memory.workflow_control import validate_request
    with pytest.raises(ValueError):
        validate_request({"action": "takeover_commit", "preview_request_id": "preview",
                          "preview_sha256": "a" * 64, "mode": "single", "resolution": "resume_unexecuted"})


@pytest.mark.parametrize("change", ["resolution", "current_step", "outputs", "source"])
def test_prepared_or_source_tampering_never_publishes(build_unexecuted, change):
    scene = build_unexecuted()
    prepared = prepare(scene)
    if change == "resolution":
        prepared["trial_state"]["recovery_import"]["resolution"] = "adopt_success"
    elif change == "current_step":
        prepared["trial_state"]["current_step_id"] = "open"
    elif change == "outputs":
        prepared["trial_state"]["outputs"]["search.result_title"] = "fabricated"
    else:
        path = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        commit(scene, prepared)
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    assert not list((scene.new / "commands").glob("*.json"))


def test_same_source_claim_cannot_be_consumed_by_second_resume_request(build_unexecuted):
    scene = build_unexecuted()
    first = prepare(scene, "first-explicit-resume")
    commit(scene, first)
    with pytest.raises(ValueError):
        second = prepare(scene, "second-explicit-resume")
        commit(scene, second)


@pytest.mark.parametrize("change", ["inputs", "outputs", "current_step", "worker", "effect_png", "admission"])
def test_first_continue_revalidates_initial_trial_and_original_ancestry(build_unexecuted, change):
    scene = build_unexecuted()
    prepared = prepare(scene)
    runtime, snapshot = commit(scene, prepared)
    run_id = snapshot["run_id"]
    trial_path = runtime.runner._trial("status", run_id)
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        path = trials._path(run_id)
    if change in {"inputs", "outputs", "current_step"}:
        value = read_json_snapshot(path)
        if change == "inputs":
            value["inputs"]["query"] = "changed-input"
        elif change == "outputs":
            value["outputs"]["search.result_title"] = "fabricated-output"
        else:
            value["current_step_id"] = "open"
        write_json_snapshot(path, value)
    elif change == "worker":
        path = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "effect_png":
        path = scene.new / "workflow-effects/current.png"
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        path = scene.new.parent / "recovery-admissions/fresh-epoch-admission.json"
        path.write_bytes(path.read_bytes() + b" ")
    before_runner = {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")}
    before_commands = {p: p.read_bytes() for p in (scene.new / "commands").glob("*.json")}
    with pytest.raises(ValueError):
        runtime.control({"action": "continue", "run_id": run_id, "wait_id": snapshot["wait"]["wait_id"]},
                        "first-continue-must-refuse")
    assert {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")} == before_runner
    assert {p: p.read_bytes() for p in (scene.new / "commands").glob("*.json")} == before_commands


def test_disposition_does_not_create_a_second_source_claim_identity(build_unexecuted):
    scene = build_unexecuted()
    resumed = prepare(scene, "resume-choice")
    # 同一来源的新独立观察可证明效果成功；不修改任何已准入原账本。
    envelope = deepcopy(scene.envelope)
    folder = scene.new / "workflow-effects"
    image = folder / "later-current.png"
    Image.new("RGB", (160, 100), "blue").save(image)
    image_hash = sha256(image.read_bytes()).hexdigest()
    reference = "workflow-effects/later-current.json"
    envelope["effect"].update(request_id="later-current", capture_id="later-capture",
                             capture_sha256=image_hash, evidence_ref=reference)
    envelope["observation"].update(request_id="later-current", capture_id="later-capture",
        capture_sha256=image_hash, evidence_ref=reference, values={"field_value": "fresh-query"})
    envelope["frame"].update(image_path=str(image), sha256=image_hash, capture_id="later-capture")
    write_json_snapshot(scene.new / reference, envelope)
    scene.effect_ref = reference
    adopted = prepare(scene, "adopt-choice", resolution=None)
    assert adopted["trial_state"]["recovery_import"]["contract_version"] == "workflow_recovery_import.v1"
    assert adopted["trial_state"]["recovery_import"]["claim_id"] == resumed["trial_state"]["recovery_import"]["claim_id"]
    commit(scene, resumed)
    with pytest.raises(ValueError):
        commit(scene, adopted)


def finish_fresh_search(public):
    from app.learning_memory.workflow_control import workflow_control
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    snapshot = public_commit(public, public_preview(public))
    scene = public.scene
    control(public, "continue-new-real-history", {"action": "continue", "run_id": snapshot["run_id"],
                                                "wait_id": snapshot["wait"]["wait_id"]})
    public.runtime.tick(force=True)
    pending = public.runtime.runner._trial("status", snapshot["run_id"])["pending"]
    assert pending["execution_request_id"] != scene.old_eid and pending["step_id"] == "search"
    # 模拟本次新输入的原终态；不是复用原 cancelled 回执。
    response(scene.new, pending, status="completed", action_executed=True)
    request = {"action": "review", "run_id": snapshot["run_id"],
        "execution_request_id": pending["execution_request_id"], "verdict": "success",
        "observations": {"field_value": "fresh-query"}, "outputs": {"result_title": "fresh-query"}}
    command = {"kind": "learning_workflow", "request": deepcopy(request)}
    enqueue_command(scene.new, "review-new-input", command)
    with MemoryWorkspace(scene.library_root) as library:
        reviewed = workflow_control(library, scene.new, request, "review-new-input")
    write_json_snapshot(scene.new / "responses/review-new-input.json",
                        {"command": command, "status": "returned", "result": reviewed})
    public.runtime.tick(force=True)
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        state = trials.status(snapshot["run_id"])
        program = trials.programs.load(state["workflow_id"], state["program_id"])
        hashes = {p.relative_to(scene.new).as_posix(): sha256(p.read_bytes()).hexdigest()
                  for p in scene.new.rglob("*") if p.is_file()}
        proof = verify_recovery_history(library, scene.new, state, program, file_hashes=hashes)
    return snapshot, pending, state, proof


@pytest.mark.parametrize("prefix_count", [0, 1])
def test_fresh_success_after_resume_creates_verifiable_new_history(build_unexecuted, monkeypatch, prefix_count):
    public = public_scene(build_unexecuted(prefix_count), monkeypatch)
    snapshot, pending, state, proof = finish_fresh_search(public)
    assert state["current_step_id"] == "open" and state["pending"] is None
    assert proof["consumed_step_ids"] == (["prefix", "search"] if prefix_count else ["search"])
    fresh = state["history"][-1]
    assert fresh["step_id"] == "search" and fresh["execution_request_id"] == pending["execution_request_id"]
    assert fresh["execution_request_id"] != public.scene.old_eid and fresh["verdict"] == "success"
    assert fresh["outputs"] == {"result_title": "fresh-query"}
    assert fresh["judged_by"] == "agent"
    assert state["recovery_import"]["consumed_step_ids"] == (["prefix"] if prefix_count else [])
    assert proof["history"] == state["history"]
    assert public.scene.original["recovery_settlement"]["terminal_status"] == "cancelled"
    assert public.scene.original["recovery_settlement"]["action_executed"] is False
    assert old_bytes(public.scene.epoch) == public.scene.old_before
    # 已建立合法新 ticket/history 后，初始状态 hash 不再阻止正常 advance。
    public.runtime.tick(force=True)
    assert old_bytes(public.scene.epoch) == public.scene.old_before


@pytest.mark.parametrize("change", ["inputs", "history", "source"])
def test_after_fresh_history_drift_still_refuses_replay(build_unexecuted, monkeypatch, change):
    from app.learning_memory.workflow_recovery_history import verify_recovery_history
    public = public_scene(build_unexecuted(), monkeypatch)
    _, _, state, _ = finish_fresh_search(public)
    scene = public.scene
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        if change == "inputs":
            state["inputs"]["query"] = "altered-input"
        elif change == "history":
            state["history"][-1]["outputs"]["result_title"] = "fabricated-history"
        else:
            source = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
            source.write_bytes(source.read_bytes() + b" ")
        if change != "source":
            write_json_snapshot(trials._path(state["run_id"]), state)
        program = trials.programs.load(state["workflow_id"], state["program_id"])
        hashes = {p.relative_to(scene.new).as_posix(): sha256(p.read_bytes()).hexdigest()
                  for p in scene.new.rglob("*") if p.is_file()}
        before = {p: p.read_bytes() for p in (scene.new / "commands").glob("*.json")}
        with pytest.raises(ValueError):
            verify_recovery_history(library, scene.new, trials.status(state["run_id"]), program, file_hashes=hashes)
        assert {p: p.read_bytes() for p in (scene.new / "commands").glob("*.json")} == before

@pytest.mark.parametrize("change", ["inputs", "worker"])
def test_changed_runner_seen_prefix_cannot_bypass_first_continue_proof(build_unexecuted, change):
    scene = build_unexecuted()
    runtime, snapshot = commit(scene, prepare(scene))
    run_id = snapshot["run_id"]
    runner_path = runtime.runner._path(run_id)
    runner_state = read_json_snapshot(runner_path)
    runner_state["seen_steps"] = ["unproven-step"]
    write_json_snapshot(runner_path, runner_state)
    if change == "inputs":
        with MemoryWorkspace(scene.library_root) as library:
            path = TrialService(library, scene.new)._path(run_id)
        trial = read_json_snapshot(path)
        trial["inputs"]["query"] = "changed-before-first-input"
        write_json_snapshot(path, trial)
    else:
        path = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    before = {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")}
    with pytest.raises(ValueError):
        runtime.control({"action": "continue", "run_id": run_id,
            "wait_id": snapshot["wait"]["wait_id"]}, "must-not-skip-initial-proof")
    assert {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")} == before
    assert not list((scene.new / "commands").glob("*.json"))

@pytest.mark.parametrize("change", ["inputs", "worker"])
def test_unproven_extra_history_cannot_skip_first_continue_proof(build_unexecuted, change):
    scene = build_unexecuted()
    runtime, snapshot = commit(scene, prepare(scene))
    run_id = snapshot["run_id"]
    with MemoryWorkspace(scene.library_root) as library:
        path = TrialService(library, scene.new)._path(run_id)
    trial = read_json_snapshot(path)
    trial["history"].append({"step_id": "search", "verdict": "success", "outputs": {}})
    if change == "inputs":
        trial["inputs"]["query"] = "unproven-new-input"
    else:
        worker = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
        worker.write_bytes(worker.read_bytes() + b" ")
    write_json_snapshot(path, trial)
    before = {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")}
    with pytest.raises(ValueError):
        runtime.control({"action": "continue", "run_id": run_id,
            "wait_id": snapshot["wait"]["wait_id"]}, "must-prove-grown-history")
    assert {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")} == before
    assert not list((scene.new / "commands").glob("*.json"))

@pytest.mark.parametrize("change", ["inputs", "worker"])
def test_terminal_runner_with_retained_wait_cannot_reactivate_input(build_unexecuted, change):
    scene = build_unexecuted()
    runtime, snapshot = commit(scene, prepare(scene))
    run_id = snapshot["run_id"]
    runner_path = runtime.runner._path(run_id)
    runner_state = read_json_snapshot(runner_path)
    runner_state["runner_state"] = "completed"
    write_json_snapshot(runner_path, runner_state)
    if change == "inputs":
        with MemoryWorkspace(scene.library_root) as library:
            path = TrialService(library, scene.new)._path(run_id)
        trial = read_json_snapshot(path)
        trial["inputs"]["query"] = "must-not-reactivate"
        write_json_snapshot(path, trial)
    else:
        path = scene.epoch.old / "agent-commands" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    before = {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")}
    with pytest.raises(ValueError):
        runtime.control({"action": "continue", "run_id": run_id,
            "wait_id": snapshot["wait"]["wait_id"]}, "cannot-resume-inconsistent-terminal")
    assert {p: p.read_bytes() for p in runtime.runner.root.glob("*.json")} == before
    assert not list((scene.new / "commands").glob("*.json"))
