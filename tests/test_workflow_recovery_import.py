"""恢复导入只消费已核验来源，新调度不得重派旧执行 ID。"""
from copy import deepcopy
from hashlib import sha256
import json
import shutil
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, response, click_response, WORKFLOW
from tests.test_workflow_rule_definition import definition
from tests.test_workflow_terminal_recovery import terminal


@pytest.fixture
def import_scene(epoch_scene, runtime_scene, monkeypatch):
    scene = epoch_scene
    source_runtime, original_trials, _, source, _ = runtime_scene
    programs = original_trials.programs
    saved = programs.load(WORKFLOW)
    value = definition(saved)
    prefix = deepcopy(value["steps"][0])
    prefix.update(step_id="prefix", title="原上游", branches={"success": "search", "failure": None, "uncertain": None})
    value["steps"][0]["success_conditions"] = [{"left": {"source": "observation", "name": "eligible"},
                                                 "operator": "agent_assertion"}]
    value["steps"].insert(0, prefix)
    value["steps"][-1]["review_status"] = "reviewed"
    saved = programs.save(WORKFLOW, saved["content_sha256"], value, "import-rules")
    run = original_trials.start(WORKFLOW, saved["program_id"], "prefix", {"query": "当前中文值"}, "source-start")
    first = original_trials.prepare(run["run_id"], "prefix-prepare")
    prefix_path = response(source, first)
    prefix_receipt = read_json_snapshot(prefix_path)
    prefix_receipt["result"]["steps"] = [{"operation": "execute_recognition_plan", "status": "returned",
        "action_executed": True, "receipt": {"phase": "returned", "response": {"success": True,
            "data": {"execution_path": {"action_executed": True}}}}}]
    write_json_snapshot(prefix_path, prefix_receipt)
    original_trials.review(run["run_id"], "prefix-review", first["execution_request_id"], "success", {},
                           {"result_title": "已核验上游"})
    pending = original_trials.prepare(run["run_id"], "search-prepare")
    source_runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "source-run")
    response(source, pending)
    for folder in ("commands", "responses", "workflow-trials", "workflow-runners"):
        shutil.copytree(source / folder, scene.old / folder, dirs_exist_ok=True)
    library_root = scene.old.parent / "memory-library"
    shutil.copytree(programs.library._workspace_root, library_root / "desktop-review")
    identity = {"handle": 71, "process_id": 72, "process_create_time": 73.5}
    pointer = read_json_snapshot(scene.old.parent / "latest-session.json")
    with MemoryWorkspace(library_root) as library:
        trials = TrialService(library, scene.old)
        worker = terminal((source_runtime, trials, run, scene.old, pending, pointer["host_identity"], 900002))
        worker["result"]["target_identity"] = {"target_window_handle": identity["handle"],
            "process_id": identity["process_id"], "process_create_time": identity["process_create_time"]}
        worker.update(dispatch_in_progress=False, dispatch_attempts=[])
        write_json_snapshot(scene.old / "agent-commands" / (pending["execution_request_id"] + ".json"), worker)
        recovery = WorkflowTerminalRecovery(trials, host_identity=pointer["host_identity"], runner_pid=900002)
        recovery.settle(recovery.preview(run["run_id"]), "source-settlement")
        original = trials.status(run["run_id"])
    before = old_bytes(scene)
    preview = scene.manager.preview_recovery()
    scene.manager.recover_session("epoch-admission", preview["preview_sha256"])
    new = scene.manager.session
    folder = new / "workflow-effects"
    folder.mkdir()
    image = folder / "current.png"
    Image.new("RGB", (160, 100), "white").save(image)
    image_hash = sha256(image.read_bytes()).hexdigest()
    reference = "workflow-effects/effect-current.json"
    effect = {"contract_version": "workflow_current_effect.v1", "source_run_id": run["run_id"],
        "source_step_id": "search", "source_execution_request_id": pending["execution_request_id"],
        "source_receipt_sha256": sha256((scene.old / "responses" / (pending["execution_request_id"] + ".json")).read_bytes()).hexdigest(),
        "source_settlement_sha256": sha256(canonical_json_bytes(original["recovery_settlement"])).hexdigest(),
        "source_program_sha256": saved["content_sha256"], "source_action_executed": True,
        "session_name": new.name, "request_id": "effect-current", "capture_id": "capture-current",
        "capture_sha256": image_hash, "window_identity": identity, "scope_id": "search-field", "evidence_ref": reference}
    observation = {key: deepcopy(effect[key]) for key in ("session_name", "request_id", "capture_id",
        "capture_sha256", "window_identity", "scope_id", "evidence_ref")}
    observation.update(step_id="search", complete=True, source="uia_value", values={"field_value": "当前中文值", "eligible": True})
    frame = {"image_path": str(image), "sha256": image_hash, "capture_id": effect["capture_id"],
        "image_size": {"width": 160, "height": 100}, "window_identity": identity}
    envelope = {"contract_version": "workflow_takeover_observation.v1", "effect": effect,
        "observation": observation, "frame": frame, "native_evidence": {},
        "measurement": {"started_ns": 1, "ended_ns": 2}}
    write_json_snapshot(new / reference, envelope)
    # 源 runner fixture 的库 facade 只用于建原票据；新会话回读真实 MemoryWorkspace。
    monkeypatch.setattr("app.learning_memory.workflow_runner.MemoryWorkspace", MemoryWorkspace)
    return SimpleNamespace(epoch=scene, library_root=library_root, new=new, source_run_id=run["run_id"],
        old_eid=pending["execution_request_id"], effect_ref=reference, envelope=envelope, old_before=before)


def prepare(scene, request_id="import-current"):
    from app.learning_memory.workflow_recovery_import import prepare_recovery_import
    return prepare_recovery_import(scene.library_root, scene.new, admission_request_id="epoch-admission",
        source_run_id=scene.source_run_id, effect_evidence_ref=scene.effect_ref, request_id=request_id)


def commit(scene, prepared):
    from app.learning_memory.workflow_recovery_import import commit_recovery_import
    runtime = WorkflowRuntime(scene.new, SimpleNamespace(_memory_library_root=scene.library_root))
    with MemoryWorkspace(scene.library_root) as library:
        return runtime, commit_recovery_import(TrialService(library, scene.new), runtime.runner, prepared)


def test_import_is_explicit_idempotent_no_dispatch_and_old_bytes_immutable(import_scene):
    scene = import_scene
    prepared = prepare(scene)
    state = prepared["trial_state"]
    assert state["run_id"] != scene.source_run_id and state["pending"] is None
    assert state["current_step_id"] == "open"
    assert state["outputs"] == {"prefix.result_title": "已核验上游", "search.result_title": "当前中文值"}
    assert all("execution_request_id" not in entry for entry in state["history"])
    runtime, first = commit(scene, prepared)
    _, second = commit(scene, prepare(scene))
    assert first == second
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before
    resumed = runtime.control({"action": "continue", "run_id": state["run_id"],
        "wait_id": first["wait"]["wait_id"]}, "continue-downstream")
    assert resumed["runner_state"] == "ready"
    resumed = runtime.tick(force=True)
    commands = list((scene.new / "commands").glob("*.json"))
    assert len(commands) == 1 and commands[0].stem != scene.old_eid, (resumed.get("wait"), resumed.get("reason"))
    assert resumed["pending"]["step_id"] == "open"
    assert old_bytes(scene.epoch) == scene.old_before
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        pending = trials.status(state["run_id"])["pending"]
        click_response(scene.new, pending)
        completed = trials.review(state["run_id"], "new-downstream-review", pending["execution_request_id"],
                                  "success", {}, {})
        assert completed["history"][:len(state["history"])] == state["history"]
    assert runtime.tick(force=True)["runner_state"] == "completed"
    assert runtime.runner.status(state["run_id"])["runner_state"] == "completed"
    assert old_bytes(scene.epoch) == scene.old_before


@pytest.mark.parametrize("change", ["program", "receipt", "output", "envelope", "png", "condition", "rule_conflict", "window"])
def test_changed_source_or_current_effect_never_imports(import_scene, change):
    scene = import_scene
    envelope = deepcopy(scene.envelope)
    if change == "program":
        envelope["effect"]["source_program_sha256"] = "0" * 64
    elif change == "receipt":
        path = scene.epoch.old / "responses" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "output":
        path = scene.epoch.old / "workflow-trials" / (scene.source_run_id + ".json")
        state = read_json_snapshot(path)
        state["outputs"]["prefix.result_title"] = "篡改上游"
        write_json_snapshot(path, state)
    elif change == "envelope":
        envelope["contract_version"] = "workflow_receipt.v1"
    elif change == "png":
        (scene.new / "workflow-effects/current.png").write_bytes(b"bad")
    elif change == "condition":
        envelope["observation"]["values"]["eligible"] = False
    elif change == "rule_conflict":
        envelope["observation"]["values"]["field_value"] = "旧值"
    else:
        for field in ("effect", "observation", "frame"):
            envelope[field]["window_identity"]["process_create_time"] = 74.5
    write_json_snapshot(scene.new / scene.effect_ref, envelope)
    with pytest.raises(ValueError):
        prepare(scene)
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    assert not list((scene.new / "commands").glob("*.json"))


def test_different_request_cannot_consume_same_source_ticket(import_scene):
    scene = import_scene
    commit(scene, prepare(scene))
    with pytest.raises(ValueError):
        commit(scene, prepare(scene, "other-import"))
    assert old_bytes(scene.epoch) == scene.old_before
    assert not list((scene.new / "commands").glob("*.json"))


def test_source_drift_between_prepare_and_commit_cannot_publish_import(import_scene):
    scene = import_scene
    prepared = prepare(scene)
    path = scene.epoch.old / "responses" / (scene.old_eid + ".json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        commit(scene, prepared)
    assert not list((scene.new / "commands").glob("*.json"))


@pytest.mark.parametrize("stage", ["trial_write", "runner_active", "claim_ready"])
def test_partial_import_disk_failure_retries_same_run_without_dispatch(import_scene, monkeypatch, stage):
    from app.desktop_review import workspace as disk
    scene = import_scene
    prepared = prepare(scene)
    run_id = prepared["trial_state"]["run_id"]
    original_replace = disk.os.replace
    failures = []

    def replace(source, destination):
        from pathlib import Path
        destination = Path(destination)
        chosen = (stage == "trial_write" and destination.parent == scene.new / "workflow-trials"
                  and destination.name == run_id + ".json")
        chosen = chosen or (stage == "runner_active" and destination == scene.new / "workflow-runners/active.json")
        if stage == "claim_ready" and destination.parent == scene.new.parent / "workflow-takeovers":
            chosen = json.loads(Path(source).read_text(encoding="utf-8")).get("phase") == "ready"
        if chosen and not failures:
            failures.append(True)
            raise OSError("controlled import disk failure")
        return original_replace(source, destination)

    monkeypatch.setattr(disk.os, "replace", replace)
    with pytest.raises(OSError, match="controlled import disk failure"):
        commit(scene, prepared)
    assert failures
    claims = list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert len(claims) == 1 and read_json_snapshot(claims[0])["phase"] == "importing"
    assert old_bytes(scene.epoch) == scene.old_before
    assert not list((scene.new / "commands").glob("*.json"))
    if stage == "trial_write":
        with MemoryWorkspace(scene.library_root) as library, pytest.raises(ValueError):
            state = prepared["trial_state"]
            TrialService(library, scene.new).start(state["workflow_id"], state["program_id"],
                state["current_step_id"], state["inputs"], "competing-new-run")
        runtime = WorkflowRuntime(scene.new, SimpleNamespace(_memory_library_root=scene.library_root))
        with pytest.raises(ValueError):
            runtime.admit("competing-input", {"kind": "input_sequence", "request": {
                "field_goal": "当前字段", "text": "拒绝写入", "clear_existing": True, "submit_search": False}})
    if (scene.new / "workflow-trials" / (run_id + ".json")).exists():
        with MemoryWorkspace(scene.library_root) as library, pytest.raises(ValueError, match="claim_not_ready"):
            TrialService(library, scene.new).prepare(run_id, "blocked-before-ready")
    runner_path = scene.new / "workflow-runners" / (run_id + ".json")
    if runner_path.exists():
        runtime = WorkflowRuntime(scene.new, SimpleNamespace(_memory_library_root=scene.library_root))
        wait = read_json_snapshot(runner_path).get("wait") or {}
        with pytest.raises(ValueError, match="workflow_runner_recovery_import_invalid"):
            runtime.runner.resume(run_id, "blocked-before-ready", wait.get("wait_id", "unknown"))
    _, snapshot = commit(scene, prepare(scene))
    assert snapshot["run_id"] == run_id
    assert len(list((scene.new / "workflow-trials").glob("trial-*.json"))) == 1
    assert read_json_snapshot(claims[0])["phase"] == "ready"
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before
