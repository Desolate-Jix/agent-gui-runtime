"""现场效果采集只读原账本，原生观察在库锁之外。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_workflow_recovery_import import import_scene
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services
from app.learning_memory.workspace import MemoryWorkspace


def collect(scene, monkeypatch, *, complete=True, drift=False, after=None, conflicting_value=False):
    from app.learning_memory import workflow_takeover_observation as module
    calls = []

    def observe(coordinator, **kwargs):
        with MemoryWorkspace(scene.library_root):
            calls.append(kwargs)
        live = deepcopy(scene.envelope)
        frame = live["frame"]
        if drift:
            frame["window_identity"]["process_create_time"] += 1
        if after:
            after()
        if conflicting_value:
            live["observation"]["values"]["field_value"] = "不匹配"
        return dict(frame=frame, capture_id=frame["capture_id"], capture_sha256=frame["sha256"],
                    window_identity=frame["window_identity"], scope_id="search-field", source="uia_value",
                    complete=complete, values=live["observation"]["values"], evidence={"native": "中文证据"})

    monkeypatch.setattr(module, "read_step_observation", observe)
    co = SimpleNamespace(_memory_library_root=scene.library_root, _owner=SimpleNamespace(call=lambda fn: fn()))
    result = module.collect_takeover_effect(co, session_dir=scene.new, admission_request_id="epoch-admission",
        source_run_id=scene.source_run_id, request_id="collect-current")
    return result, calls


def test_collect_real_source_png_and_idempotent_readback(import_scene, monkeypatch):
    result, calls = collect(import_scene, monkeypatch)
    assert len(calls) == 1
    assert result["envelope"]["verification"]["verdict"] == "success"
    assert result["envelope"]["native_evidence"] == {"native": "中文证据"}
    assert result["envelope"]["effect"]["source_action_executed"] is True
    assert "execution_request_id" not in result["envelope"]["observation"]
    second, calls = collect(import_scene, monkeypatch)
    assert second == result and calls == []
    assert old_bytes(import_scene.epoch) == import_scene.old_before
    assert not list((import_scene.new / "commands").glob("*.json"))


@pytest.mark.parametrize("complete,drift", [(False, False), (True, True)])
def test_incomplete_or_window_drift_never_writes_effect(import_scene, monkeypatch, complete, drift):
    with pytest.raises(ValueError):
        collect(import_scene, monkeypatch, complete=complete, drift=drift)
    assert not (import_scene.new / "workflow-effects/collect-current.json").exists()
    assert old_bytes(import_scene.epoch) == import_scene.old_before


def test_unknown_source_refuses_before_observation(import_scene, monkeypatch):
    from app.learning_memory import workflow_takeover_observation as module
    monkeypatch.setattr(module, "read_step_observation", lambda *a, **k: pytest.fail("unexpected observation"))
    co = SimpleNamespace(_memory_library_root=import_scene.library_root)
    with pytest.raises(ValueError):
        module.collect_takeover_effect(co, session_dir=import_scene.new, admission_request_id="epoch-admission",
            source_run_id="trial-" + "f" * 64, request_id="unknown-source")


@pytest.mark.parametrize("kind", ["source", "png"])
def test_drift_during_native_read_never_publishes(import_scene, monkeypatch, kind):
    scene = import_scene
    path = (scene.epoch.old / "responses" / (scene.old_eid + ".json") if kind == "source"
            else scene.new / "workflow-effects/current.png")
    def change():
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        collect(scene, monkeypatch, after=change)
    assert not (scene.new / "workflow-effects/collect-current.json").exists()


def test_conflicting_current_value_is_failure_not_new_action(import_scene, monkeypatch):
    result, _ = collect(import_scene, monkeypatch, conflicting_value=True)
    assert result["envelope"]["verification"]["verdict"] == "failure"
    assert result["envelope"]["effect"]["source_action_executed"] is True
    assert old_bytes(import_scene.epoch) == import_scene.old_before


def test_existing_artifact_conflict_is_not_reobserved(import_scene, monkeypatch):
    from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
    collect(import_scene, monkeypatch)
    path = import_scene.new / "workflow-effects/collect-current.json"
    artifact = read_json_snapshot(path)
    artifact["admission_request_id"] = "other"
    write_json_snapshot(path, artifact)
    with pytest.raises(ValueError, match="effect_request_conflict"):
        collect(import_scene, monkeypatch)


def test_unsupported_real_program_requires_review(epoch_scene, runtime_scene, monkeypatch):
    import tests.test_workflow_recovery_import as fixture_module
    original = fixture_module.definition
    def definition(saved):
        value = original(saved)
        value["steps"][0]["verification"] = {"kind": "agent_judgment"}
        return value
    monkeypatch.setattr(fixture_module, "definition", definition)
    scene = fixture_module.import_scene.__wrapped__(epoch_scene, runtime_scene, monkeypatch)
    result, calls = collect(scene, monkeypatch)
    assert result == {"status": "verification_required", "reason": "agent_judgment_required",
                      "automatic_retry_allowed": False}
    assert calls == []
    assert not (scene.new / "workflow-effects/collect-current.json").exists()
    assert old_bytes(scene.epoch) == scene.old_before


def test_cached_verdict_tampering_refused(import_scene, monkeypatch):
    from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
    collect(import_scene, monkeypatch)
    path = import_scene.new / "workflow-effects/collect-current.json"
    artifact = read_json_snapshot(path)
    artifact["verification"]["verdict"] = "failure"
    write_json_snapshot(path, artifact)
    with pytest.raises(ValueError, match="effect_verification_changed"):
        collect(import_scene, monkeypatch)
