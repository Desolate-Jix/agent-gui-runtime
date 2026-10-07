"""重复 epoch 只复用经过原始来源核验的导入前缀。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_recovery_history import verify_recovery_history
from tests.test_workflow_recovery_import import import_scene, prepare, commit
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services, click_response
from tests.test_workflow_terminal_recovery import terminal


def hashes(session):
    return {path.relative_to(session).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in session.rglob("*") if path.is_file()}


@pytest.fixture
def ancestry_scene(import_scene):
    scene = import_scene
    prepared = prepare(scene)
    runtime, snapshot = commit(scene, prepared)
    runtime.control({"action": "continue", "run_id": snapshot["run_id"], "wait_id": snapshot["wait"]["wait_id"]}, "next")
    runtime.tick(force=True)
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        pending = trials.status(snapshot["run_id"])["pending"]
        click_response(scene.new, pending)
        state = trials.review(snapshot["run_id"], "new-review", pending["execution_request_id"], "success", {}, {})
        program = trials.programs.load(state["workflow_id"], state["program_id"])
    runtime.tick(force=True)
    return SimpleNamespace(scene=scene, state=state, program=program, prepared=prepared)


def verify(scene):
    with MemoryWorkspace(scene.scene.library_root) as library:
        return verify_recovery_history(library, scene.scene.new, scene.state, scene.program,
                                       file_hashes=hashes(scene.scene.new))


def test_real_import_prefix_and_later_execution_have_recursive_provenance(ancestry_scene):
    scene = ancestry_scene
    before = hashes(scene.scene.new)
    result = verify(scene)
    assert result["consumed_step_ids"] == ["prefix", "search", "open"]
    assert result["history"] == scene.state["history"]
    assert result["outputs"] == scene.state["outputs"]
    assert result["ancestry"]["source_session_name"] == scene.scene.epoch.old.name
    assert all("execution_request_id" not in row for row in result["history"][:2])
    assert hashes(scene.scene.new) == before
    assert old_bytes(scene.scene.epoch) == scene.scene.old_before


@pytest.mark.parametrize("change", ["prefix", "marker", "receipt", "effect", "png", "admission", "claim", "cycle"])
def test_changed_ancestor_or_import_prefix_refuses(ancestry_scene, change):
    item, scene = ancestry_scene, ancestry_scene.scene
    marker = item.state["recovery_import"]
    claim_path = scene.new.parent / "workflow-takeovers" / (marker["claim_id"] + ".json")
    if change in {"prefix", "marker"}:
        if change == "prefix": item.state["history"][0]["outputs"]["result_title"] = "篡改"
        else: item.state["recovery_import"]["source_program_sha256"] = "0" * 64
        write_json_snapshot(scene.new / "workflow-trials" / (item.state["run_id"] + ".json"), item.state)
    elif change == "receipt":
        path = scene.epoch.old / "responses" / (scene.old_eid + ".json")
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "png":
        (scene.new / "workflow-effects/current.png").write_bytes(b"bad")
    elif change == "effect":
        path = scene.new / scene.effect_ref
        envelope = read_json_snapshot(path)
        envelope["observation"]["values"]["field_value"] = "篡改"
        write_json_snapshot(path, envelope)
    elif change == "admission":
        path = scene.new.parent / "recovery-admissions/epoch-admission.json"
        path.write_bytes(path.read_bytes() + b" ")
    else:
        claim = read_json_snapshot(claim_path)
        if change == "claim": claim["prepared"]["trial_state"]["inputs"]["query"] = "篡改"
        else: claim["prepared"]["trial_state"]["recovery_import"]["source_session_name"] = scene.new.name
        write_json_snapshot(claim_path, claim)
    with pytest.raises(ValueError):
        verify(item)


def test_depth_and_visited_guard_before_recursive_source_reads(ancestry_scene):
    from app.learning_memory.workflow_recovery_history import _verify_history
    scene = ancestry_scene
    with MemoryWorkspace(scene.scene.library_root) as library:
        for depth, visited in [(16, set()), (0, {(str(scene.scene.new.resolve()), scene.state["run_id"])})]:
            with pytest.raises(ValueError, match="ancestry_cycle_or_depth"):
                _verify_history(library, scene.scene.new, scene.state, scene.program,
                    file_hashes=hashes(scene.scene.new), visited=visited, depth=depth, external_snapshots={})


def test_second_epoch_settled_source_can_prepare_verified_ancestry(epoch_scene, runtime_scene, monkeypatch):
    import tests.test_workflow_recovery_import as fixture_module
    from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
    from app.learning_memory.workflow_recovery_import import prepare_recovery_import
    from app.desktop_review.external_mapping import canonical_json_bytes
    from PIL import Image
    original = fixture_module.definition
    def definition(saved):
        value = original(saved)
        value["steps"][-1]["branches"]["success"] = "finish"
        final = deepcopy(value["steps"][0])
        final.update(step_id="finish", title="新 epoch 下游", branches={"success": None, "failure": None, "uncertain": None})
        value["steps"].append(final)
        return value
    monkeypatch.setattr(fixture_module, "definition", definition)
    scene = fixture_module.import_scene.__wrapped__(epoch_scene, runtime_scene, monkeypatch)
    runtime, snapshot = commit(scene, prepare(scene))
    runtime.control({"action": "continue", "run_id": snapshot["run_id"], "wait_id": snapshot["wait"]["wait_id"]}, "next")
    runtime.tick(force=True)
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        pending = trials.status(snapshot["run_id"])["pending"]
        click_response(scene.new, pending)
        trials.review(snapshot["run_id"], "open-review", pending["execution_request_id"], "success", {}, {})
    runtime.tick(force=True)
    pointer = read_json_snapshot(scene.new.parent / "latest-session.json")
    scene.epoch.active.pop(pointer["host_identity"]["pid"])
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, scene.new)
        state = trials.status(snapshot["run_id"])
        pending = state["pending"]
        assert pending["step_id"] == "finish" and pending["execution_request_id"] != scene.old_eid
        worker = terminal((runtime, trials, state, scene.new, pending, pointer["host_identity"], pointer["host_identity"]["pid"]))
        identity = scene.envelope["effect"]["window_identity"]
        worker["result"]["target_identity"] = {"target_window_handle": identity["handle"],
            "process_id": identity["process_id"], "process_create_time": identity["process_create_time"]}
        worker.update(dispatch_in_progress=False, dispatch_attempts=[])
        write_json_snapshot(scene.new / "agent-commands" / (pending["execution_request_id"] + ".json"), worker)
        recovery = WorkflowTerminalRecovery(trials, host_identity=pointer["host_identity"], runner_pid=pointer["host_identity"]["pid"])
        settled = recovery.settle(recovery.preview(state["run_id"]), "second-settlement")
    source_before = hashes(scene.new)
    preview = scene.epoch.manager.preview_recovery()
    scene.epoch.manager.recover_session("second-admission", preview["preview_sha256"])
    newer = scene.epoch.manager.session
    folder = newer / "workflow-effects"
    folder.mkdir()
    image = folder / "second.png"
    Image.new("RGB", (160, 100), "white").save(image)
    envelope = deepcopy(scene.envelope)
    digest = sha256(image.read_bytes()).hexdigest()
    reference = "workflow-effects/second-effect.json"
    envelope["effect"].update(source_run_id=settled["run_id"], source_step_id="finish",
        source_execution_request_id=pending["execution_request_id"],
        source_receipt_sha256=settled["recovery_settlement"]["acceptance_receipt_sha256"],
        source_settlement_sha256=sha256(canonical_json_bytes(settled["recovery_settlement"])).hexdigest(),
        session_name=newer.name, request_id="second-effect", capture_id="second-capture",
        capture_sha256=digest, evidence_ref=reference)
    envelope["observation"].update(session_name=newer.name, step_id="finish", request_id="second-effect",
        capture_id="second-capture", capture_sha256=digest, evidence_ref=reference)
    envelope["frame"].update(image_path=str(image), capture_id="second-capture", sha256=digest)
    write_json_snapshot(newer / reference, envelope)
    admission_path = scene.new.parent / "recovery-admissions/second-admission.json"
    with MemoryWorkspace(scene.library_root) as library:
        program = TrialService(library, scene.new).programs.load(settled["workflow_id"], settled["program_id"])
        with pytest.raises(ValueError, match="admission_pointer_invalid"):
            verify_recovery_history(library, scene.new, settled, program, file_hashes=hashes(scene.new))
        bundle = verify_recovery_history(library, scene.new, settled, program,
            file_hashes=hashes(scene.new), admission_chain=[admission_path])
        assert bundle["consumed_step_ids"] == ["prefix", "search", "open"]
        assert bundle["ancestry"]["source_session_name"] == scene.epoch.old.name
        for chain in ([admission_path, admission_path],
                      [admission_path, scene.new.parent / "recovery-admissions/epoch-admission.json"]):
            with pytest.raises(ValueError):
                verify_recovery_history(library, scene.new, settled, program,
                    file_hashes=hashes(scene.new), admission_chain=chain)
    prepared = prepare_recovery_import(scene.library_root, newer, admission_request_id="second-admission",
        source_run_id=settled["run_id"], effect_evidence_ref=reference, request_id="second-import")
    assert prepared["trial_state"]["recovery_import"]["consumed_step_ids"] == ["prefix", "search", "open", "finish"]
    assert prepared["trial_state"]["status"] == "completed" and prepared["trial_state"]["pending"] is None
    assert all("execution_request_id" not in row for row in prepared["trial_state"]["history"])
    assert hashes(scene.new) == source_before and old_bytes(scene.epoch) == scene.old_before
    assert not list((newer / "commands").glob("*.json"))
    from app.learning_memory.workflow_runtime import WorkflowRuntime
    from app.learning_memory.workflow_recovery_import import commit_recovery_import
    newer_runtime = WorkflowRuntime(newer, SimpleNamespace(_memory_library_root=scene.library_root))
    with MemoryWorkspace(scene.library_root) as library:
        trials = TrialService(library, newer)
        commit_recovery_import(trials, newer_runtime.runner, prepared)
        imported = trials.status(prepared["trial_state"]["run_id"])
        newest_bundle = verify_recovery_history(library, newer, imported, program, file_hashes=hashes(newer))
        assert newest_bundle["consumed_step_ids"] == ["prefix", "search", "open", "finish"]
        assert newest_bundle["ancestry"]["history"]["ancestry"]["source_session_name"] == scene.epoch.old.name
    assert hashes(scene.new) == source_before and old_bytes(scene.epoch) == scene.old_before
    assert not list((newer / "commands").glob("*.json"))
