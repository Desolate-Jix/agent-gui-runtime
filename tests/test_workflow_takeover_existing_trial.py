"""拒绝其他活动工作流须发生在接管声明落盘前。"""
import pytest

from app.core.json_snapshot import read_json_snapshot
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_trial import TrialService
from tests.test_workflow_recovery_import import import_scene, prepare, commit
from tests.test_instant_epoch_recovery import epoch_scene
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


def test_competing_ready_trial_does_not_leave_blocking_takeover_claim(import_scene):
    scene = import_scene
    prepared = prepare(scene)
    source = read_json_snapshot(scene.epoch.old / 'workflow-trials' / (scene.source_run_id + '.json'))
    with MemoryWorkspace(scene.library_root) as library:
        other = TrialService(library, scene.new).start(source['workflow_id'], source['program_id'],
            source['start_step_id'], source['inputs'], 'another-workflow')
    with pytest.raises(ValueError):
        commit(scene, prepared)
    assert not list((scene.new.parent / 'workflow-takeovers').glob('*.json'))
    with MemoryWorkspace(scene.library_root) as library:
        assert TrialService(library, scene.new).status(other['run_id']) == other
