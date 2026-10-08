"""真实判断结算的恢复仍须核验原会话认证账本，不重派输入或模型。"""
from copy import deepcopy
from hashlib import sha256
import json
import os
import shutil
import sqlite3
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.core.decision_configuration import PROFILE_SNAPSHOT, freeze_decision_profile
from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.execution.session_input_terminal import _catalog
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.learning_memory.workflow_program import WorkflowProgramService
from app.learning_memory.workflow_recovery_history import verify_recovery_history
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workspace import MemoryWorkspace
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_decision_verification import CONDITION
from tests.test_workflow_recovery_import import prepare, commit
from tests.test_workflow_rule_definition import definition
from tests.test_workflow_terminal_recovery import terminal
from tests.test_workflow_trial import services, response, WORKFLOW


@pytest.fixture
def decision_recovery_scene(epoch_scene, services, monkeypatch, request):
    epoch = epoch_scene
    programs, _, saved, _ = services
    library_root = epoch.old.parent / "memory-library"
    shutil.copytree(programs.library._workspace_root, library_root / "desktop-review")
    identity = {"handle": 71, "process_id": 72, "process_create_time": 73.5}
    image = epoch.old / "decision-current.png"
    Image.new("RGB", (160, 100), "white").save(image)
    frame = {"capture_id": "decision-after", "image_path": str(image),
        "sha256": sha256(image.read_bytes()).hexdigest(), "image_size": {"width": 160, "height": 100},
        "window_rect": [0, 0, 160, 100], "window_identity": identity}
    image_check, capture_count = None, 1
    if getattr(request, "param", None) == "image_miss":
        from tests.test_image_verification import sample
        from tests.test_image_wait_early_exit import Clock
        image_check, _, _, _ = sample(library_root)
        Image.new("RGB", (80, 60), "black").save(image)
        frame.update(sha256=sha256(image.read_bytes()).hexdigest(), image_size={"width": 80, "height": 60},
                     window_rect=[0, 0, 80, 60])
        clock = Clock()
        monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
        monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
        capture_count = 20
    captures, calls = [], []

    def capture(*args, **kwargs):
        captures.append(True)
        return deepcopy(frame), {}

    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "condition_met", "probability": 0.98},
            {"type": "predicate", "name": "visible_error", "probability": 0.01}],
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}})

    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    monkeypatch.setenv("RECOVERY_DECISION_SYNTHETIC_KEY", "synthetic-recovery-key")
    client = httpx.Client(transport=httpx.MockTransport(reply))
    profile = DecisionProfile(mode="auto", api_key_env="RECOVERY_DECISION_SYNTHETIC_KEY", auto_conditions=[CONDITION])
    decision = DecisionService(epoch.old, profile=profile, provider=OpenAIDecisionsProvider(
        api_key_env="RECOVERY_DECISION_SYNTHETIC_KEY", client=client))
    freeze_decision_profile(decision)
    try:
        with MemoryWorkspace(library_root) as library:
            programs = WorkflowProgramService(library)
            value = definition(saved)
            prefix = deepcopy(value["steps"][0])
            prefix.update(step_id="prefix", title="原判断上游", outputs=[], success_conditions=[],
                verification={"kind": "agent_judgment", "decision_condition": CONDITION},
                branches={"success": "search", "failure": None, "uncertain": None})
            if image_check is not None:
                prefix["verification"]["image_check"] = image_check
            value["steps"].insert(0, prefix)
            saved = programs.save(WORKFLOW, saved["content_sha256"], value, "recovery-decision-save")
            reviewed = deepcopy(saved["definition"])
            for step in reviewed["steps"]:
                step["review_status"] = "reviewed"
            saved = programs.save(WORKFLOW, saved["content_sha256"], reviewed, "recovery-decision-review")
            trials = TrialService(library, epoch.old)
            run = trials.start(WORKFLOW, saved["program_id"], "prefix", {"query": "当前中文值"}, "source-start")
            first = trials.prepare(run["run_id"], "prefix-prepare")
            path = response(epoch.old, first)
            receipt = read_json_snapshot(path)
            receipt["result"].update(capture={"capture_id": "decision-before"}, target_identity={
                "target_window_handle": identity["handle"], "process_id": identity["process_id"],
                "process_create_time": identity["process_create_time"]}, steps=[{
                    "operation": "execute_recognition_plan", "status": "returned", "action_executed": True,
                    "receipt": {"phase": "returned", "response": {"success": True,
                        "data": {"execution_path": {"action_executed": True}}}}}])
            write_json_snapshot(path, receipt)
        from app.learning_memory.runtime_verification import verify_trial_step
        co = SimpleNamespace(_memory_library_root=library_root, _decision_service=decision,
            _owner=SimpleNamespace(call=lambda f: f()))
        settled = verify_trial_step(co, session_dir=epoch.old, request_id="decision-verify", request={
            "action": "verify", "run_id": run["run_id"], "execution_request_id": first["execution_request_id"]})
        assert settled["history"][0]["judged_by"] == "decision" and settled["status"] == "ready"
        assert len(calls) == 1 and len(captures) == capture_count
        decision.close()
        monkeypatch.delenv("RECOVERY_DECISION_SYNTHETIC_KEY")
        with MemoryWorkspace(library_root) as library:
            trials = TrialService(library, epoch.old)
            pending = trials.prepare(run["run_id"], "search-prepare")
        runtime = WorkflowRuntime(epoch.old, SimpleNamespace(_memory_library_root=library_root))
        runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "source-run")
        response(epoch.old, pending)
        with MemoryWorkspace(library_root) as library:
            trials = TrialService(library, epoch.old)
            pointer = read_json_snapshot(epoch.old.parent / "latest-session.json")
            worker = terminal((runtime, trials, run, epoch.old, pending, pointer["host_identity"], 900002))
            worker["result"]["target_identity"] = {"target_window_handle": identity["handle"],
                "process_id": identity["process_id"], "process_create_time": identity["process_create_time"]}
            worker.update(dispatch_in_progress=False, dispatch_attempts=[])
            write_json_snapshot(epoch.old / "agent-commands" / (pending["execution_request_id"] + ".json"), worker)
            recovery = WorkflowTerminalRecovery(trials, host_identity=pointer["host_identity"], runner_pid=900002)
            recovery.settle(recovery.preview(run["run_id"]), "source-settlement")
            original = trials.status(run["run_id"])
        before = old_bytes(epoch)
        preview = epoch.manager.preview_recovery()
        epoch.manager.recover_session("epoch-admission", preview["preview_sha256"])
        new = epoch.manager.session
        effect_image = new / "workflow-effects/current.png"
        effect_image.parent.mkdir()
        Image.new("RGB", (160, 100), "white").save(effect_image)
        image_hash = sha256(effect_image.read_bytes()).hexdigest()
        reference = "workflow-effects/effect-current.json"
        effect = {"contract_version": "workflow_current_effect.v1", "source_run_id": run["run_id"],
            "source_step_id": "search", "source_execution_request_id": pending["execution_request_id"],
            "source_receipt_sha256": sha256((epoch.old / "responses" / (pending["execution_request_id"] + ".json")).read_bytes()).hexdigest(),
            "source_settlement_sha256": sha256(canonical_json_bytes(original["recovery_settlement"])).hexdigest(),
            "source_program_sha256": saved["content_sha256"], "source_action_executed": True,
            "session_name": new.name, "request_id": "effect-current", "capture_id": "capture-current",
            "capture_sha256": image_hash, "window_identity": identity, "scope_id": "search-field", "evidence_ref": reference}
        observation = {key: deepcopy(effect[key]) for key in ("session_name", "request_id", "capture_id",
            "capture_sha256", "window_identity", "scope_id", "evidence_ref")}
        observation.update(step_id="search", complete=True, source="uia_value", values={"field_value": "当前中文值"})
        envelope = {"contract_version": "workflow_takeover_observation.v1", "effect": effect, "observation": observation,
            "frame": {"image_path": str(effect_image), "sha256": image_hash, "capture_id": effect["capture_id"],
                "image_size": {"width": 160, "height": 100}, "window_identity": identity},
            "native_evidence": {}, "measurement": {"started_ns": 1, "ended_ns": 2}}
        write_json_snapshot(new / reference, envelope)
        yield SimpleNamespace(epoch=epoch, library_root=library_root, new=new, source_run_id=run["run_id"],
            old_eid=pending["execution_request_id"], decision_eid=first["execution_request_id"],
            effect_ref=reference, original=original, program=saved, old_before=before, calls=calls, captures=captures)
    finally:
        decision.close()
        client.close()


def verify_history(scene, hashes=None):
    hashes = hashes or {name: sha256(raw).hexdigest() for name, raw in _catalog(scene.epoch.old).items()}
    with MemoryWorkspace(scene.library_root) as library:
        return verify_recovery_history(library, scene.epoch.old, scene.original, scene.program, file_hashes=hashes)


def test_maintained_catalog_includes_authenticated_decision_dependencies(decision_recovery_scene):
    s = decision_recovery_scene
    required = {PROFILE_SNAPSHOT, "judgments/decisions.sqlite3", "workflow-decisions/decision-verify.result.json",
                "workflow-decisions/" + s.decision_eid + ".request.json"}
    assert required <= set(_catalog(s.epoch.old))


def test_original_decision_history_recovery_is_authenticated_readonly(decision_recovery_scene):
    s = decision_recovery_scene
    result = verify_history(s)
    assert result["history"][0]["judged_by"] == "decision"
    assert result["consumed_step_ids"] == ["prefix"] and result["outputs"] == {}
    assert {PROFILE_SNAPSHOT, "judgments/decisions.sqlite3"} <= set(result["files"])
    assert verify_history(s) == result
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1


def test_decision_history_survives_real_admission_prepare_commit_without_replay(decision_recovery_scene):
    s = decision_recovery_scene
    prepared = prepare(s)
    imported = prepared["trial_state"]["history"][0]
    assert imported["source_entry"]["judged_by"] == "decision" and imported["source_entry"] == s.original["history"][0]
    _, first = commit(s, prepared)
    _, second = commit(s, prepare(s))
    assert first == second and first["run_id"] != s.source_run_id
    assert not list((s.new / "commands").glob("*.json"))
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1


def test_recovery_never_reads_key_opens_writable_ledger_or_evaluates(decision_recovery_scene, monkeypatch):
    s = decision_recovery_scene
    original_get = os.environ.get

    def guarded_get(name, *args):
        if name in {"RECOVERY_DECISION_SYNTHETIC_KEY", "OPENAI_API_KEY", "AGENT_GUI_DECISION_PROFILE"}:
            pytest.fail("recovery must use source policy and durable authentication without credentials")
        return original_get(name, *args)

    def forbidden(*args, **kwargs):
        pytest.fail("recovery cannot dispatch decisions or open the writable ledger")

    monkeypatch.setattr(os.environ, "get", guarded_get)
    monkeypatch.setattr(DecisionService, "evaluate", forbidden)
    monkeypatch.setattr(DecisionService, "_get_provider", forbidden)
    monkeypatch.setattr(DecisionService, "_connect", forbidden)
    assert verify_history(s)["history"][0]["judged_by"] == "decision"
    assert prepare(s)["trial_state"]["history"][0]["source_entry"]["judged_by"] == "decision"
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1


@pytest.mark.parametrize("change", ["result", "binding", "index", "policy", "threshold", "ledger", "pre_capture", "window", "input_fact", "review_request"])
def test_rehashed_tampering_cannot_forge_authenticated_decision_history(decision_recovery_scene, change):
    s = decision_recovery_scene
    root = s.epoch.old
    path = root / "workflow-decisions/decision-verify.result.json"
    if change == "ledger":
        with sqlite3.connect(root / "judgments/decisions.sqlite3") as db:
            db.execute("UPDATE dispatches SET result_blob=?", (b"forged-result",))
    elif change in {"policy", "threshold"}:
        path = root / PROFILE_SNAPSHOT
        value = read_json_snapshot(path)
        value["mode" if change == "policy" else "pass_threshold"] = "shadow" if change == "policy" else 0.95
        write_json_snapshot(path, value)
    elif change == "index":
        path = root / ("workflow-decisions/" + s.decision_eid + ".request.json")
        value = read_json_snapshot(path)
        value["request_id"] = "other-verify"
        write_json_snapshot(path, value)
    elif change in {"pre_capture", "window"}:
        path = root / "workflow-observations/decision-verify.json"
        value = read_json_snapshot(path)
        if change == "pre_capture":
            value["receipt"]["pre_capture_id"] = "forged-before"
        else:
            value["frame"]["window_identity"]["process_create_time"] = 99.0
        write_json_snapshot(path, value)
    elif change in {"input_fact", "review_request"}:
        value = deepcopy(s.original)
        if change == "input_fact":
            value["history"][0]["action_executed"] = True
        else:
            value["history"][0]["review_request"] = None
        s.original = value
        write_json_snapshot(root / ("workflow-trials/" + s.source_run_id + ".json"), value)
    else:
        value = read_json_snapshot(path)
        if change == "result":
            value["result"]["verdict"] = "failure"
        else:
            value["binding"]["run_id"] = "trial-other"
        write_json_snapshot(path, value)
    before = old_bytes(s.epoch)
    with pytest.raises(ValueError):
        verify_history(s)
    assert old_bytes(s.epoch) == before and len(s.calls) == len(s.captures) == 1


@pytest.mark.parametrize("missing", [PROFILE_SNAPSHOT, "judgments/decisions.sqlite3",
    "workflow-decisions/decision-verify.result.json", "workflow-observations/decision-verify.json", "decision-current.png"])
def test_missing_admitted_decision_dependency_rejects(decision_recovery_scene, missing):
    s = decision_recovery_scene
    hashes = {name: sha256(raw).hexdigest() for name, raw in _catalog(s.epoch.old).items()}
    hashes.pop(missing)
    with pytest.raises(ValueError, match="workflow_recovery_history_source_"):
        verify_history(s, hashes)
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == len(s.captures) == 1


def test_tampering_after_admission_cannot_prepare_import(decision_recovery_scene):
    s = decision_recovery_scene
    path = s.epoch.old / "judgments/decisions.sqlite3"
    path.write_bytes(path.read_bytes() + b"changed")
    before = old_bytes(s.epoch)
    with pytest.raises(ValueError, match="source_catalog_changed"):
        prepare(s)
    assert old_bytes(s.epoch) == before and not list((s.new / "commands").glob("*.json"))
    assert len(s.calls) == len(s.captures) == 1


@pytest.mark.parametrize("decision_recovery_scene", ["image_miss"], indirect=True)
def test_recovery_recomputes_original_semantic_image_miss(decision_recovery_scene):
    s = decision_recovery_scene
    assert verify_history(s)["history"][0]["judged_by"] == "decision"
    assert prepare(s)["trial_state"]["history"][0]["source_entry"]["judged_by"] == "decision"
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == 1 and len(s.captures) == 20
    check = s.program["definition"]["steps"][0]["verification"]["image_check"]
    reference = s.library_root / "desktop-review/evidence-objects" / (check["reference_sha256"] + ".png")
    reference.write_bytes(b"corrupt-reference")
    with pytest.raises(ValueError, match="reference_sha256_changed"):
        verify_history(s)
    assert old_bytes(s.epoch) == s.old_before and len(s.calls) == 1 and len(s.captures) == 20


def test_oversized_sqlite_catalog_is_rejected_before_reading_bytes(tmp_path, monkeypatch):
    from pathlib import Path
    root = tmp_path / "session"
    path = root / "judgments/decisions.sqlite3"
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.seek(64 * 1024 * 1024)
        stream.write(b"x")
    original = Path.read_bytes

    def guarded_read(candidate):
        if candidate == path:
            pytest.fail("oversized ledger must be rejected before allocating its bytes")
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(ValueError, match="session_input_catalog_limit"):
        _catalog(root)
