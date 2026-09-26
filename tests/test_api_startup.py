"""外部 API 启动检查必须在创建宿主前完成，密钥不得写入启动参数。"""
from argparse import Namespace
import json
from types import SimpleNamespace

import pytest

from app.instant_mcp import InstantSession, InstantStartError
from scripts.run_local_step_session import configure_recognition_startup


def profile(tmp_path):
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps({'endpoint': 'http://127.0.0.1:34567/completions',
        'model': 'fixture', 'api_key_env': 'STARTUP_TEST_KEY'}), encoding='utf-8')
    return path


def test_external_session_passes_profile_but_not_key_and_skips_model(tmp_path, monkeypatch):
    import app.instant_mcp as instant
    path = profile(tmp_path)
    monkeypatch.setenv('STARTUP_TEST_KEY', 'startup-test-key')
    launched = []
    monkeypatch.setattr(instant.subprocess, 'Popen', lambda args, **kwargs:
        launched.append(args) or SimpleNamespace(pid=12345, poll=lambda: None))
    monkeypatch.setattr('psutil.Process', lambda _: SimpleNamespace(create_time=lambda: 1.0))
    session = InstantSession(tmp_path, tmp_path / 'data', allow_local_input=True,
        recognition_source='external_api', api_profile=path)
    try:
        assert session.start()['recognition_source'] == 'external_api'
        assert launched[0][launched[0].index('--api-profile') + 1] == str(path)
        assert '--model-directory' not in launched[0]
        saved = (tmp_path / 'data/latest-session.json').read_text(encoding='utf-8')
        assert 'startup-test-key' not in saved + repr(launched)
        report = {}
        value = configure_recognition_startup(object(), Namespace(recognition_source='external_api',
            delegate_profile=None, api_profile=str(path), model_directory=None), report)
        assert value.model == 'fixture' and report['model_configuration'] is None
    finally:
        if session.lock_file:
            session.lock_file.close()
        if session.log_file:
            session.log_file.close()


def test_missing_api_key_rejected_before_any_host_or_lock(tmp_path, monkeypatch):
    monkeypatch.delenv('STARTUP_TEST_KEY', raising=False)
    session = InstantSession(tmp_path, tmp_path / 'data', allow_local_input=True,
        recognition_source='external_api', api_profile=profile(tmp_path))
    with pytest.raises(InstantStartError) as failure:
        session.start()
    assert failure.value.code == 'api_key_missing'
    assert session.lock_file is None and session.process is None
