from __future__ import annotations

from types import SimpleNamespace

import pytest


def _install_fake_job(monkeypatch: pytest.MonkeyPatch, *, get_last_error=0, query_error: BaseException | None = None, set_error: BaseException | None = None):
    from app.learn.hybrid import windows_process_scope as module

    closed: list[object] = []
    calls: list[str] = []
    job = SimpleNamespace(
        JOB_OBJECT_LIMIT_BREAKAWAY_OK=1,
        JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK=2,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=4,
        JobObjectExtendedLimitInformation=9,
        CreateJobObject=lambda _security, _name: "job-handle",
    )

    def query(_handle, _kind):
        calls.append("query")
        if query_error is not None:
            raise query_error
        return {"BasicLimitInformation": {"LimitFlags": 0}}

    def set_information(_handle, _kind, _information):
        calls.append("set")
        if set_error is not None:
            raise set_error

    job.QueryInformationJobObject = query
    job.SetInformationJobObject = set_information
    api = SimpleNamespace(
        GetLastError=(
            (lambda: (_ for _ in ()).throw(get_last_error))
            if isinstance(get_last_error, BaseException)
            else (lambda: get_last_error)
        ),
        CloseHandle=lambda handle: closed.append(handle),
    )
    monkeypatch.setattr(module, "windows_process_scope_available", lambda: True)
    monkeypatch.setattr(module, "win32job", job)
    monkeypatch.setattr(module, "win32api", api)
    return module, closed, calls


@pytest.mark.parametrize("failure", ["get_last_error", "query", "set"])
def test_new_scope_policy_initialization_failure_closes_created_handle(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    kwargs = {
        "get_last_error": RuntimeError("last-error") if failure == "get_last_error" else 0,
        "query_error": RuntimeError("query") if failure == "query" else None,
        "set_error": RuntimeError("set") if failure == "set" else None,
    }
    module, closed, _calls = _install_fake_job(monkeypatch, **kwargs)

    with pytest.raises(RuntimeError):
        module.WindowsProcessScope("Local\\AgentGuiHybrid-vista-" + "a" * 64, create=True)

    assert closed == ["job-handle"]


def test_existing_scope_error_closes_once_without_policy_initialization(monkeypatch: pytest.MonkeyPatch) -> None:
    module, closed, calls = _install_fake_job(monkeypatch, get_last_error=183)

    with pytest.raises(module.HybridProcessScopeError, match="already exists"):
        module.WindowsProcessScope("Local\\AgentGuiHybrid-vista-" + "b" * 64, create=True)

    assert closed == ["job-handle"]
    assert calls == []


def test_successful_scope_retains_handle_until_owner_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    module, closed, calls = _install_fake_job(monkeypatch)

    scope = module.WindowsProcessScope("Local\\AgentGuiHybrid-vista-" + "c" * 64, create=True)
    assert calls == ["query", "set"]
    assert closed == []
    scope.close()
    assert closed == ["job-handle"]


def test_new_scope_close_failure_preserves_policy_failure_as_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    module, _closed, _calls = _install_fake_job(monkeypatch, query_error=RuntimeError("query"))
    monkeypatch.setattr(module.win32api, "CloseHandle", lambda _handle: (_ for _ in ()).throw(RuntimeError("close")))

    with pytest.raises(RuntimeError, match="close") as raised:
        module.WindowsProcessScope("Local\\AgentGuiHybrid-vista-" + "d" * 64, create=True)

    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "query"
