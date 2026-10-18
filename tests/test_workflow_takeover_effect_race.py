"""接管提交固定新效果原件，ready 回读不再次消费观察。"""
import inspect
from copy import deepcopy
from hashlib import sha256

import pytest

from tests.test_workflow_recovery_import import import_scene, prepare, commit
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services
from app.core.json_snapshot import read_json_snapshot


@pytest.mark.parametrize("asset", ["png", "envelope"])
def test_last_effect_validation_drift_prevents_ready(import_scene, monkeypatch, asset):
    import app.learning_memory.workflow_recovery_import as module
    scene = import_scene
    prepared = prepare(scene)
    original = module._build
    changed = []

    def build(*args, **kwargs):
        state = original(*args, **kwargs)
        # 直接识别 Trial 导入核验，避免提交前检查次数变化削弱反例。
        in_trial_import = any(frame.function == "import_recovery_trial" for frame in inspect.stack())
        if in_trial_import and not changed:
            path = scene.new / ("workflow-effects/current.png" if asset == "png" else scene.effect_ref)
            path.write_bytes(path.read_bytes() + b" ")
            changed.append(True)
        return state

    monkeypatch.setattr(module, "_build", build)
    with pytest.raises(ValueError):
        commit(scene, prepared)
    assert changed
    claims = list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert all(read_json_snapshot(path)["phase"] != "ready" for path in claims)
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before


@pytest.mark.parametrize("asset", ["png", "envelope"])
def test_ready_same_id_returns_original_state_after_effect_asset_changes(import_scene, asset):
    scene = import_scene
    prepared = prepare(scene)
    _, first = commit(scene, prepared)
    path = scene.new / ("workflow-effects/current.png" if asset == "png" else scene.effect_ref)
    path.write_bytes(path.read_bytes() + b" ")
    protected = {path: path.read_bytes() for folder in ("workflow-trials", "workflow-runners")
                 for path in (scene.new / folder).glob("*.json")}
    _, second = commit(scene, prepared)
    assert second == first
    assert {path: path.read_bytes() for path in protected} == protected
    assert not list((scene.new / "commands").glob("*.json"))
    assert old_bytes(scene.epoch) == scene.old_before


def test_effect_files_cannot_replace_real_png_with_unrelated_file(import_scene):
    scene = import_scene
    prepared = deepcopy(prepare(scene))
    unrelated = scene.new / "workflow-effects/unrelated.bin"
    unrelated.write_bytes(b"unrelated")
    prepared["effect_files"] = {scene.effect_ref: prepared["effect_files"][scene.effect_ref],
        unrelated.relative_to(scene.new).as_posix(): sha256(unrelated.read_bytes()).hexdigest()}
    with pytest.raises(ValueError, match="effect_files_invalid"):
        commit(scene, prepared)
    assert not list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert not list((scene.new / "workflow-trials").glob("trial-*.json"))
    assert old_bytes(scene.epoch) == scene.old_before


def test_source_response_drift_after_import_blocks_final_ready(import_scene, monkeypatch):
    from app.learning_memory.workflow_runner import WorkflowRunner
    scene = import_scene
    prepared = prepare(scene)
    original = WorkflowRunner.import_recovery
    response = scene.epoch.old / "responses" / (scene.old_eid + ".json")
    original_bytes = response.read_bytes()
    changed = []

    def import_runner(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        response.write_bytes(original_bytes + b" ")
        changed.append(True)
        return result

    monkeypatch.setattr(WorkflowRunner, "import_recovery", import_runner)
    with pytest.raises(ValueError, match="prepared_source_changed"):
        commit(scene, prepared)
    assert changed
    claims = list((scene.new.parent / "workflow-takeovers").glob("*.json"))
    assert len(claims) == 1 and read_json_snapshot(claims[0])["phase"] == "importing"
    assert not list((scene.new / "commands").glob("*.json"))
    actual = old_bytes(scene.epoch)
    assert actual.pop(str(response.relative_to(scene.epoch.old))) == original_bytes + b" "
    expected = dict(scene.old_before)
    expected.pop(str(response.relative_to(scene.epoch.old)))
    assert actual == expected
