"""真实配置文件必须从工作台指定位置贯穿首次学习，不借用学习根配置。"""

import json
from pathlib import Path

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_formal_fresh_learning_factory import (
    _WindowManager, _NativeReader, _OriginReader, _UIAProvider,
    _MSS, _patch_capture_backend,
)
from tests.test_formal_fresh_learning_observation import _RecognitionRunner


def _write_config(path, model_name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'vision': {'mode': 'local', 'local': {
        'model_name': model_name, 'endpoint': 'http://127.0.0.1:13244/v1/chat/completions',
        'model_path': 'weights/fixture-model',
    }}}, ensure_ascii=False), encoding='utf-8')


@pytest.mark.parametrize('learning_root_has_decoy', [False, True])
def test_real_config_loader_and_factory_keep_explicit_workbench_source(tmp_path, monkeypatch, learning_root_has_decoy):
    _exercise(tmp_path, monkeypatch, decoy=learning_root_has_decoy, missing=False)


def test_missing_explicit_config_does_not_fall_back_to_valid_learning_root_config(tmp_path, monkeypatch):
    _exercise(tmp_path, monkeypatch, decoy=True, missing=True)


def _exercise(tmp_path, monkeypatch, *, decoy, missing):
    import app.agent.fresh_learning_factory as factory
    import app.agent.fresh_learning_observation as observation
    import app.desktop_review.single_step_coordinator as coordinator_module

    data = tmp_path / 'fresh-learning'
    config_path = tmp_path / 'workbench-config' / 'vision.json'
    if not missing:
        _write_config(config_path, 'explicit-workbench-model')
    if decoy:
        _write_config(data / 'configs/vision.json', 'wrong-learning-root-model')
    _patch_capture_backend(monkeypatch)
    manager = _WindowManager()
    monkeypatch.setattr(factory, 'WindowManager', lambda: manager)
    monkeypatch.setattr(factory, 'WindowsNativeIdentityReader', _NativeReader)
    monkeypatch.setattr(factory, 'WindowsUIAOriginReader', _OriginReader)
    monkeypatch.setattr(factory, 'uia_provider', _UIAProvider())
    calls = []
    backend = _RecognitionRunner()

    def recognize(**kwargs):
        # 只替换模型推理；实际配置加载、冻结、工厂与新观察所有者全部保留。
        snapshot = kwargs['vision_configuration']
        assert snapshot.path == config_path.resolve()
        local = snapshot.to_dict()['vision']['local']
        assert local['model_name'] == 'explicit-workbench-model'
        assert Path(local['model_path']) == config_path.parent / 'weights/fixture-model'
        assert kwargs['provider_mode'] == 'local'
        calls.append(snapshot)
        return backend(**kwargs)

    monkeypatch.setattr(observation, '_run_existing_read_only_recognition', recognize)
    monkeypatch.setattr(coordinator_module, 'FormalModelService',
        lambda *args, **kwargs: pytest.fail('external configuration must not acquire a managed service'))
    host = DesktopReviewHost(tmp_path / 'inbox.json', data, 'configuration-origin-reviewer', port=0)
    coordinator = NativeSingleStepCoordinator(data, host.facade, host,
        vision_config_path=config_path, runtime_output_root=tmp_path / 'runtime-output',
        thread_initializer=lambda: None, thread_finalizer=lambda: None)
    monkeypatch.setattr(coordinator, '_check_runtime_environment', lambda: None)
    try:
        host.start()
        connection = host.connections.create_connection('config-origin-task', 'config-origin-agent')
        segment = host._service.agent_call(connection['token'], 'start_learning_segment',
            {'idempotency_key': 'segment-once', 'title': 'Fresh configuration origin'})
        request = {'segment_id': segment['segment_id'], 'idempotency_key': 'observe-once',
            'application_identity': {'kind': 'native', 'executable_path': r'C:\Fresh\fresh.exe'},
            'target_window_handle': 4242, 'target_process_id': 9001,
            'title': 'Fresh configuration screen', 'meaning': 'Configuration source test', 'goal': 'Fresh'}
        if missing:
            with pytest.raises(AgentLinkError) as failure:
                host._service.agent_call(connection['token'], 'observe_learning_screen', request)
            assert failure.value.code == 'observation_failed'
            assert calls == [] and manager.bound_handles == [] and _MSS.monitors == []
            assert host.facade.list_batches() == []
        else:
            response = host._service.agent_call(connection['token'], 'observe_learning_screen', request)
            replay = host._service.agent_call(connection['token'], 'observe_learning_screen', request)
            assert replay == response
            assert len(calls) == 1 and len(_MSS.monitors) == 1 and manager.bound_handles == [4242]
            assert response['observation']['recognition']['status'] == 'completed'
            assert response['action_executed'] is False and response['artifact_is_authorization'] is False
            assert len(host.facade.list_batches()) == 1 and host.facade.list_reviewed_assets() == []
        assert manager.focus_calls == 0
        assert coordinator.learning_runtime_state()['phase'] == 'idle'
        if decoy:
            retained = json.loads((data / 'configs/vision.json').read_text(encoding='utf-8'))
            assert retained['vision']['local']['model_name'] == 'wrong-learning-root-model'
        else:
            assert not (data / 'configs/vision.json').exists()
    finally:
        coordinator.shutdown()
        host.close()
