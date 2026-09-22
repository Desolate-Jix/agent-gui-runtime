"""模型启动诊断仅使用隔离替身，不启动模型或发送输入。"""
import json
from threading import Event
from unittest.mock import Mock

import pytest

from app.core import model_server
from app.learn.hybrid import windows_process_scope as scopes
from app.vision.model_service import FormalModelService, ModelServiceConfiguration, ModelServiceError


@pytest.fixture
def service(tmp_path, monkeypatch):
    profile = {"profile_id": "vista_4b_transformers", "port": 13244}
    value = FormalModelService(ModelServiceConfiguration(180, json.dumps(profile)),
        output_root=tmp_path, allow_resource_coexistence=True)
    monkeypatch.setattr(value, "_probe", lambda deadline: {"status": "unreachable"})
    monkeypatch.setattr(value, "close", Mock(return_value={"cleanup_verified": True}))
    monkeypatch.setattr(scopes, "_listeners", lambda ports: [])
    monkeypatch.setattr(scopes, "scoped_process_launch_ready", lambda: True)
    monkeypatch.setattr(scopes, "WindowsProcessScope", lambda *a, **k: Mock(pids=lambda: []))
    return value


def test_immediate_exit_keeps_actionable_diagnostics(service, monkeypatch):
    log = service._output_root / "logs/local-vision-server-vista_4b_transformers-20260922-120000.log"
    log.parent.mkdir(parents=True)
    log.write_text("SECRET_LOG_CONTENT", encoding="utf-8")
    failure = RuntimeError(f"Model start script exited immediately with code 2; see log: {log}")
    monkeypatch.setattr(model_server, "start_model_server", Mock(side_effect=failure))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    error = caught.value
    assert error.code == "model_service_prepare_failed"
    assert error.__cause__ is failure
    assert error.diagnostics["phase"] == "launch"
    assert error.diagnostics["error_code"] == error.code
    assert error.diagnostics["cause_type"] == "RuntimeError"
    assert error.diagnostics["process_exit_code"] == 2
    assert error.diagnostics["log_path"] == str(log)
    assert "SECRET_LOG_CONTENT" not in json.dumps(error.diagnostics)


def test_prepare_failure_keeps_cleanup_evidence_together_with_startup(service, monkeypatch):
    failure = ModelServiceError('model_service_cleanup_pending')
    failure.diagnostics = {'contract_version': 'model_service_cleanup_diagnostics_v1',
        'evidence_path': 'owned-cleanup.json', 'evidence': {'pid_file_cleanup': {'reason': 'unlink_failed'}}}
    service.close.side_effect = failure
    monkeypatch.setattr(model_server, 'start_model_server', Mock(side_effect=RuntimeError('launch failed')))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    assert caught.value.diagnostics['phase'] == 'launch'
    assert caught.value.diagnostics['cleanup_diagnostics']['evidence']['pid_file_cleanup']['reason'] == 'unlink_failed'


def test_later_exit_keeps_returned_log_location(service, monkeypatch):
    log = service._output_root / "logs/local-vision-server-vista_4b_transformers-20260922-120001.log"
    monkeypatch.setattr(model_server, "start_model_server", lambda *a, **k: {"log_path": str(log)})
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    assert caught.value.code == "model_service_exited"
    assert caught.value.diagnostics["phase"] == "readiness"
    assert caught.value.diagnostics["log_path"] == str(log)
    assert caught.value.diagnostics["process_exit_code"] is None


def test_arbitrary_exception_and_foreign_log_are_not_echoed(service, monkeypatch):
    failure = RuntimeError("Model start script exited immediately with code 2; see log: https://user:TOKEN@example.test/log")
    monkeypatch.setattr(model_server, "start_model_server", Mock(side_effect=failure))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    diagnostics = caught.value.diagnostics
    assert "TOKEN" not in json.dumps(diagnostics)
    assert diagnostics["log_path"] is None
    assert diagnostics["log_directory"] == str(service._output_root / "logs")


def test_native_error_retains_numeric_reason_without_secret_message(service, monkeypatch):
    failure = PermissionError(13, "token=SECRET_PERMISSION")
    failure.winerror = 5
    monkeypatch.setattr(model_server, "start_model_server", Mock(side_effect=failure))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    diagnostics = caught.value.diagnostics
    assert diagnostics["errno"] == 13
    assert diagnostics["winerror"] == 5
    assert "SECRET_PERMISSION" not in json.dumps(diagnostics)


def test_cleanup_failure_preserves_startup_diagnostics(service, monkeypatch):
    monkeypatch.setattr(model_server, "start_model_server", Mock(side_effect=PermissionError(13, "private")))
    service.close.side_effect = ModelServiceError("model_service_cleanup_pending", result_unknown=True)
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    assert caught.value.code == "model_service_cleanup_pending"
    assert caught.value.result_unknown
    assert caught.value.diagnostics["error_code"] == "model_service_prepare_failed"
    assert caught.value.diagnostics["cleanup_error_code"] == "model_service_cleanup_pending"
    assert caught.value.diagnostics["errno"] == 13


def test_preflight_timeout_does_not_claim_a_launch_log(service, monkeypatch):
    monkeypatch.setattr(service, "_probe", Mock(side_effect=ModelServiceError("model_service_readiness_timeout")))
    monkeypatch.setattr(model_server, "start_model_server", lambda *a, **k: pytest.fail("unexpected model launch"))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    assert caught.value.code == "model_service_readiness_timeout"
    assert caught.value.diagnostics["phase"] == "preflight"
    assert caught.value.diagnostics["log_directory"] is None
    assert caught.value.diagnostics["log_path"] is None


def test_post_launch_probe_timeout_is_readiness_not_launch(service, monkeypatch):
    log = service._output_root / "logs/local-vision-server-vista_4b_transformers-20260922-120001.log"
    monkeypatch.setattr(model_server, "start_model_server", lambda *a, **k: {"log_path": str(log)})
    monkeypatch.setattr(service, "_probe", Mock(side_effect=[{"status": "unreachable"},
        ModelServiceError("model_service_readiness_timeout")]))
    with pytest.raises(ModelServiceError) as caught:
        service.prepare(Event())
    assert caught.value.code == "model_service_readiness_timeout"
    assert caught.value.diagnostics["phase"] == "readiness"
    assert caught.value.diagnostics["log_path"] == str(log)
