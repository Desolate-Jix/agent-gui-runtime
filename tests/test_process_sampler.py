"""ProcessSampler 的隔离单元测试；不启动 GUI、不读取命令行。"""

from types import SimpleNamespace

import pytest

from app.core import process_sampler as subject


class FakeProcess:
    def __init__(self, pid, ppid, created):
        self.pid = pid
        self._ppid = ppid
        self.created = created
        self.name_calls = 0
        self.exe_calls = 0

    @property
    def info(self):
        return {"pid": self.pid, "ppid": self._ppid}

    def create_time(self):
        return self.created

    def name(self):
        self.name_calls += 1
        return f"proc-{self.pid}"

    def exe(self):
        self.exe_calls += 1
        return f"C:/proc-{self.pid}.exe"

    def ppid(self):
        return self._ppid

    def num_threads(self):
        return 3

    def memory_info(self):
        return SimpleNamespace(rss=4096 + self.pid)

    def cpu_times(self):
        return SimpleNamespace(user=1.25, system=0.5)

    def status(self):
        return "running"

    def oneshot(self):
        class _OneShot:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        return _OneShot()


def test_discovery_enumerates_once_and_reuses_static_fields(monkeypatch):
    processes = {
        10: FakeProcess(10, 1, 100.0),
        11: FakeProcess(11, 10, 101.0),
        12: FakeProcess(12, 11, 102.0),
        13: FakeProcess(13, 99, 103.0),
    }
    calls = []

    def process_iter(attrs):
        calls.append(tuple(attrs))
        return list(processes.values())

    monkeypatch.setattr(subject.psutil, "process_iter", process_iter)
    monkeypatch.setattr(subject.psutil, "Process", lambda pid: processes[pid])
    sampler = subject.ProcessSampler(10, extra_root_getter=lambda: [11], discovery_interval=10)

    first = sampler.snapshot(lightweight=False)
    second = sampler.snapshot(lightweight=True, discover=False)

    assert [row["pid"] for row in first["processes"]] == [10, 11, 12]
    assert [row["pid"] for row in second["processes"]] == [10, 11, 12]
    assert len(calls) == 1
    assert first["collection"]["discovery"] is True
    assert second["collection"]["discovery"] is False
    assert processes[10].name_calls == processes[10].exe_calls == 1
    assert "collection_ms" in second and "collection_errors" in second


def test_pid_reuse_is_rejected_without_old_identity_row(monkeypatch):
    process = FakeProcess(20, 1, 200.0)
    monkeypatch.setattr(subject.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(subject.psutil, "Process", lambda _pid: process)
    sampler = subject.ProcessSampler(20)

    sampler.snapshot(lightweight=False)
    process.created = 201.0
    result = sampler.snapshot(lightweight=True, discover=False)

    assert result["processes"] == [{"pid": 20, "observation_error": "pid_reused_rejected"}]
    assert result["collection_errors"][0]["error"] == "pid_reused_rejected"

    # 即使下一次低频发现看到相同 PID，也不能重新收养已拒绝的新身份。
    result = sampler.snapshot(lightweight=True, discover=True)
    assert result["processes"] == []
    assert result["collection_errors"][0]["error"] == "pid_reused_rejected"


def test_pid_reuse_after_process_disappears_is_rejected(monkeypatch):
    current = {40: FakeProcess(40, 1, 400.0)}

    def factory(pid):
        if pid not in current:
            raise subject.psutil.NoSuchProcess(pid)
        return current[pid]

    monkeypatch.setattr(subject.psutil, "Process", factory)
    monkeypatch.setattr(subject.psutil, "process_iter", lambda _attrs: list(current.values()))
    sampler = subject.ProcessSampler(40)
    sampler.snapshot(lightweight=False)
    del current[40]
    missing = sampler.snapshot(lightweight=True, discover=False)
    assert missing["processes"] == [{"pid": 40, "observation_error": "NoSuchProcess"}]

    current[40] = FakeProcess(40, 1, 401.0)
    reused = sampler.snapshot(lightweight=True, discover=True)
    assert reused["processes"] == []
    assert any(error["error"] == "pid_reused_rejected" for error in reused["collection_errors"])


def test_extra_root_error_is_reported_and_cmdline_is_never_requested(monkeypatch):
    process = FakeProcess(30, 1, 300.0)
    requested = []

    def process_iter(attrs):
        requested.append(tuple(attrs))
        return [process]

    monkeypatch.setattr(subject.psutil, "process_iter", process_iter)
    monkeypatch.setattr(subject.psutil, "Process", lambda _pid: process)
    sampler = subject.ProcessSampler(30, extra_root_getter=lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    result = sampler.snapshot(lightweight=False)

    assert requested == [("pid", "ppid")]
    assert result["processes"][0]["pid"] == 30
    assert any(error["operation"] == "extra_root_getter" for error in result["collection_errors"])


def test_static_field_errors_are_visible(monkeypatch):
    process = FakeProcess(31, 1, 310.0)
    process.name = lambda: (_ for _ in ()).throw(subject.psutil.AccessDenied(31))
    process.exe = lambda: (_ for _ in ()).throw(subject.psutil.AccessDenied(31))
    monkeypatch.setattr(subject.psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(subject.psutil, "Process", lambda _pid: process)

    result = subject.ProcessSampler(31).snapshot(lightweight=False)

    row = result["processes"][0]
    assert row["name"] is None and row["exe"] is None
    assert {error["field"] for error in result["collection_errors"]} == {"name", "exe"}


def test_interval_validation():
    with pytest.raises(ValueError):
        subject.ProcessSampler(1, sample_interval=1)
    with pytest.raises(ValueError):
        subject.ProcessSampler(1, sample_interval=2, discovery_interval=1)
    with pytest.raises(ValueError):
        subject.ProcessSampler(1.2)
