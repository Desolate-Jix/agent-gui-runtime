"""正式模型解释器冻结及创建失败拥有权；不加载任何权重。"""
import json
from pathlib import Path
import sys
from threading import Event

import pytest

from app.learn.hybrid.windows_process_scope import WindowsProcessScope
from tests.test_formal_model_service import _configuration, backend
from tests.test_native_model_scope_initialization import _install_fake_job


def _transformers(tmp_path, python_path=None):
    from app.vision.model_service import freeze_model_service

    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["runtime"] = "transformers"
    if python_path is not None:
        profile["python_path"] = python_path
    path.write_text(json.dumps(profile), encoding="utf-8")
    return freeze_model_service(snapshot)


def test_source_runtime_freezes_current_interpreter_without_using_path_fallback(tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    frozen = _transformers(tmp_path)
    assert frozen.profile()["python_path"] == str(Path(sys.executable).resolve())


def test_explicit_interpreter_is_resolved_from_profile_directory_and_pinned(tmp_path, monkeypatch):
    executable = tmp_path / "chosen.exe"
    executable.write_bytes(b"synthetic-not-executable")
    frozen = _transformers(tmp_path, "chosen.exe")
    monkeypatch.chdir(tmp_path.parent)
    assert frozen.profile()["python_path"] == str(executable)


def test_packaged_gui_executable_cannot_be_guessed_as_python(tmp_path, monkeypatch):
    from app.vision.model_service import ModelServiceError

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(ModelServiceError, match="model_service_interpreter_required"):
        _transformers(tmp_path)


@pytest.mark.parametrize("field,value", [("runtime", "Transformers"), ("output_contract", "VISTA_POINT_V1")])
def test_packaged_interpreter_requirement_matches_runtime_case_rules(tmp_path, monkeypatch, field, value):
    from app.vision.model_service import ModelServiceError, freeze_model_service

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile[field] = value
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ModelServiceError, match="model_service_interpreter_required"):
        freeze_model_service(snapshot)


def test_missing_explicit_interpreter_fails_before_model_start(tmp_path):
    from app.vision.model_service import ModelServiceError

    with pytest.raises(ModelServiceError, match="model_service_interpreter_invalid"):
        _transformers(tmp_path, "missing.exe")


@pytest.mark.parametrize("existing", [False, True])
def test_model_owner_retains_failed_constructor_handle_without_terminating_foreign_job(tmp_path, monkeypatch, backend, existing):
    from app.vision.model_service import FormalModelService, ModelServiceError, freeze_model_service

    module, closed, calls = _install_fake_job(monkeypatch, get_last_error=183 if existing else 0,
                                            query_error=None if existing else RuntimeError("policy"))
    monkeypatch.setattr(module, "WindowsProcessScope", WindowsProcessScope)
    attempts = []

    def fail_close(handle):
        attempts.append(handle)
        raise RuntimeError("close")

    monkeypatch.setattr(module.win32api, "CloseHandle", fail_close)
    snapshot, _ = _configuration(tmp_path)
    owner = FormalModelService(freeze_model_service(snapshot), output_root=tmp_path / "output")
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending") as error:
        owner.prepare(Event())
    assert error.value.result_unknown is True
    assert owner._initialization_cleanup is not None
    assert backend.starts == backend.cleanups == []
    assert len(attempts) == 2
    retained = owner._initialization_cleanup
    with pytest.raises(ModelServiceError, match="model_service_invalid_phase"):
        owner.prepare(Event())
    assert owner._initialization_cleanup is retained and len(attempts) == 2
    monkeypatch.setattr(module.win32api, "CloseHandle", lambda handle: closed.append(handle))
    assert owner.close()["cleanup_verified"] is True
    assert closed == ["job-handle"]
    assert backend.cleanups == []
