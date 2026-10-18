from __future__ import annotations
from pathlib import Path
import subprocess
import json
import os
import pytest
from scripts import build_native_windows as build
def _metadata() -> bytes: return b'{"packages":[],"python":"formal"}'
def _successful_run(command, **kwargs):
    if "-c" in command: return subprocess.CompletedProcess(command, 0, _metadata() if "importlib.metadata" in command[-1] else b'{"pyinstaller":"6.22.2"}', b"")
    dist = Path(command[command.index("--distpath") + 1]) / "AgentReview"; dist.mkdir(parents=True)
    (dist / "AgentReview.exe").write_bytes(b"gui"); (dist / "AgentReviewBridge.exe").write_bytes(b"bridge")
    kwargs["stdout"].write(b"out"); kwargs["stderr"].write(b"err")
    return subprocess.CompletedProcess(command, 0, b"out", b"err")
def _paths(tmp_path: Path):
    release = tmp_path / "release"; release.mkdir(); tools = tmp_path / "tools"; tools.mkdir(); runtime = tmp_path / "python.exe"; runtime.write_bytes(b"python")
    return release, tools, runtime
def test_new_output_creates_evidence_and_records_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release, tools, runtime = _paths(tmp_path); output = release / "attempt"
    monkeypatch.setattr(build, "RELEASE_ROOT", release); monkeypatch.setattr(build, "REPO_ROOT", tmp_path); monkeypatch.setattr(build.subprocess, "run", _successful_run)
    assert build.build(output, tools, runtime) == 0
    assert (output / "logs" / "command.json").is_file()
    assert (output / "logs" / "stdout.bin").read_bytes() == b"out"
    assert '"succeeded": true' in (output / "build-result.json").read_text(encoding="utf-8")
def test_existing_or_unsafe_output_is_rejected(tmp_path: Path) -> None:
    release, _, _ = _paths(tmp_path); existing = release / "existing"; existing.mkdir()
    with pytest.raises(FileExistsError): build._require_new_output(existing, release)
    with pytest.raises(ValueError): build._require_new_output(tmp_path / "outside", release)


def test_explicit_output_parent_keeps_build_outside_project_without_overwrite(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    external = tmp_path / "external-volume"; external.mkdir()
    output = external / "fresh-attempt"
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    monkeypatch.setattr(build.subprocess, "run", _successful_run)
    assert build.build(output, tools, runtime, output_parent=external) == 0
    assert (output / "dist/AgentReview/AgentReview.exe").read_bytes() == b"gui"
    assert list(release.iterdir()) == []
    with pytest.raises(FileExistsError):
        build.build(output, tools, runtime, output_parent=external)
    assert (output / "dist/AgentReview/AgentReview.exe").read_bytes() == b"gui"


@pytest.mark.parametrize("case", ["relative", "missing", "file", "outside", "parent"])
def test_explicit_output_parent_rejects_ambiguous_or_out_of_scope_paths(monkeypatch, tmp_path, case):
    release, tools, runtime = _paths(tmp_path)
    external = tmp_path / "external-volume"; external.mkdir()
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: pytest.fail("invalid output must not start build"))
    parent = {"relative": Path("relative-parent"), "missing": tmp_path / "absent", "file": runtime}.get(case, external)
    output = tmp_path / "outside" if case == "outside" else external if case == "parent" else external / "fresh"
    with pytest.raises(ValueError):
        build.build(output, tools, runtime, output_parent=parent)
    assert not (external / "fresh").exists()


def test_build_cli_forwards_explicit_parent_without_changing_default(monkeypatch, tmp_path):
    parent = tmp_path / "external"; parent.mkdir()
    calls = []
    monkeypatch.setattr(build, "build", lambda *a, **k: calls.append((a, k)) or 0)
    assert build.main(["--output-root", str(parent / "fresh"), "--output-parent", str(parent)]) == 0
    assert calls[0][1]["output_parent"] == parent
    assert build.main(["--output-root", str(parent / "other")]) == 0
    assert calls[1][1]["output_parent"] is None
def test_nonzero_result_is_persisted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release, tools, runtime = _paths(tmp_path); output = release / "attempt"
    monkeypatch.setattr(build, "RELEASE_ROOT", release); monkeypatch.setattr(build, "REPO_ROOT", tmp_path)
    def run(command, **kwargs):
        if "-c" in command: return _successful_run(command, **kwargs)
        kwargs["stdout"].write(b"out"); kwargs["stderr"].write(b"bad")
        return subprocess.CompletedProcess(command, 7, b"out", b"bad")
    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.build(output, tools, runtime) == 1
    result = (output / "build-result.json").read_text(encoding="utf-8")
    assert '"returncode": 7' in result and '"succeeded": false' in result
def test_zero_exit_without_exact_companions_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    release, tools, runtime = _paths(tmp_path); output = release / "attempt"
    monkeypatch.setattr(build, "RELEASE_ROOT", release); monkeypatch.setattr(build, "REPO_ROOT", tmp_path)
    def run(command, **kwargs):
        if "-c" in command: return _successful_run(command, **kwargs)
        return subprocess.CompletedProcess(command, 0, b"out", b"")
    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.build(output, tools, runtime) == 1
    assert "AgentReviewBridge.exe" in (output / "build-result.json").read_text(encoding="utf-8")


def test_runtime_inventory_does_not_include_build_tool_path(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    monkeypatch.setenv("PYTHONPATH", "unrelated-inherited-path")
    monkeypatch.setenv("PYTHONHOME", "unrelated-inherited-home")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return _successful_run(command, **kwargs)
    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.build(release / "attempt", tools, runtime) == 0
    assert "PYTHONPATH" not in calls[0][1]["env"]
    assert "PYTHONHOME" not in calls[0][1]["env"]
    assert calls[1][1]["env"]["PYTHONPATH"] == str(tools)
    assert calls[2][1]["env"]["HF_HUB_OFFLINE"] == "1"


def test_metadata_failure_preserves_raw_stdout_and_stderr(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 7, b"partial metadata", b"probe failure")
    monkeypatch.setattr(build.subprocess, "run", run)
    output = release / "attempt"
    assert build.build(output, tools, runtime) == 1
    assert (output / "logs/runtime-metadata.stdout.bin").read_bytes() == b"partial metadata"
    assert (output / "logs/runtime-metadata.stderr.bin").read_bytes() == b"probe failure"
    assert json.loads((output / "build-result.json").read_text(encoding="utf-8"))["succeeded"] is False


def test_hash_failure_never_reports_success(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    monkeypatch.setattr(build.subprocess, "run", _successful_run)
    def unavailable(*args):
        raise OSError("artifact could not be read")
    monkeypatch.setattr(build, "_write_output_hashes", unavailable)
    output = release / "attempt"
    assert build.build(output, tools, runtime) == 1
    report = json.loads((output / "build-result.json").read_text(encoding="utf-8"))
    assert report["succeeded"] is False
    assert report["failure"]["type"] == "OSError"


def test_partial_output_setup_failure_is_recorded(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    original = Path.mkdir
    def mkdir(path, *args, **kwargs):
        if path == release / "attempt/work":
            raise OSError("work directory denied")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    output = release / "attempt"
    assert build.build(output, tools, runtime) == 1
    assert json.loads((output / "build-result.json").read_text(encoding="utf-8"))["succeeded"] is False


@pytest.mark.parametrize("path_key", ["PATH", "Path"])
def test_build_subprocess_cannot_resolve_dlls_from_inherited_path(monkeypatch, tmp_path, path_key):
    release, tools, runtime = _paths(tmp_path)
    system_root = tmp_path / "Windows"
    (system_root / "System32").mkdir(parents=True)
    inherited = {path_key: str(tmp_path / "unrelated-poppler-bin"), "SystemRoot": str(system_root), "PYTHONPATH": "ambient-python"}
    monkeypatch.setattr(build.os, "environ", inherited)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    calls = []
    def run(command, **kwargs):
        calls.append(kwargs["env"].copy())
        return _successful_run(command, **kwargs)
    monkeypatch.setattr(build.subprocess, "run", run)
    assert build.build(release / "attempt", tools, runtime) == 0
    expected = [str(runtime.parent.resolve()), str(system_root / "System32"), str(system_root)]
    assert len(calls) == 3
    for environment in calls:
        search_paths = [value for key, value in environment.items() if key.upper() == "PATH"]
        assert len(search_paths) == 1
        assert search_paths[0].split(os.pathsep) == expected
    assert inherited[path_key] == str(tmp_path / "unrelated-poppler-bin")


def test_invalid_system_root_fails_before_any_build_subprocess(monkeypatch, tmp_path):
    release, tools, runtime = _paths(tmp_path)
    monkeypatch.setattr(build, "RELEASE_ROOT", release)
    monkeypatch.setattr(build.os, "environ", {"SystemRoot": "relative-windows", "PATH": "ambient-dlls"})
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return _successful_run(command, **kwargs)
    monkeypatch.setattr(build.subprocess, "run", run)
    output = release / "attempt"
    assert build.build(output, tools, runtime) == 1
    assert calls == []
    report = json.loads((output / "build-result.json").read_text(encoding="utf-8"))
    assert report["failure"]["type"] == "ValueError"
    assert "SystemRoot" in report["failure"]["message"]
