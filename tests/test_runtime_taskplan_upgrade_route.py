"""Opt-in real 0.1.8 -> frozen release migration, with original sessions read-only.

Set AGENT_GUI_RUNTIME_UPGRADE_BASELINE_DIR and AGENT_GUI_RUNTIME_UPGRADE_RELEASE_DIR
to directories containing runtime-update.json, the installer, and update ZIP;
set AGENT_GUI_RUNTIME_UPGRADE_TARGET_DIGEST to the independently frozen new target
digest and AGENT_GUI_RUNTIME_UPGRADE_SESSIONS to a JSON list of original session
paths. No network, daily installation, desktop, or model service is used.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from uuid import uuid4

import psutil
import pytest

from app import runtime_task_ledger as ledger
from app.runtime_lifecycle import InstallationLease, update_pending_path
from app.runtime_update import RuntimeUpdater, target_digest, validate_target


_ENV = "AGENT_GUI_RUNTIME_UPGRADE_"
# Bytes retained from anonymous GitHub asset verification on 2026-10-24.
_PUBLISHED_018 = {
    "runtime-update.json": "be3d25675e9070e5e680f04b65692cbea1919aa598800f9ec4a89c325b7324a7",
    "AgentGUIRuntimeExecution-Setup.exe": "03394583530aadd5b500db621bb34139d2723d6c3176850680b26f721631f93d",
    "AgentGUIRuntimeExecution-update.zip": "120ef33d380f02fdddd21e297090f4205d204d4dab7e16b4f0a30a63d3cda972",
}


def _json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _snapshot(path):
    return {p.relative_to(path).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in path.rglob("*") if p.is_file()}


def _run(*args, cwd, log=None):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=150)
    if log is not None:
        _json_write(log, {"command": [str(arg) for arg in args], "cwd": str(cwd),
                          "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    return result


def _cli(script_root, installed, action, *, cwd, log=None, digest=None):
    args = [sys.executable, "-I", "-B", "-X", "utf8", script_root / "scripts/update_runtime.py",
            "--root", installed, action]
    if digest is not None:
        args.extend(["--confirm-target", digest])
    return _run(*args, cwd=cwd, log=log)


def _assets(directory, expected_digest, validator):
    target = validate_target(json.loads((directory / "runtime-update.json").read_text(encoding="utf-8")))
    assert target_digest(target) == expected_digest, "release differs from independently frozen target"
    installer = directory / "AgentGUIRuntimeExecution-Setup.exe"
    archive = directory / "AgentGUIRuntimeExecution-update.zip"
    for path, key in ((installer, "installer"), (archive, "payload")):
        raw = path.read_bytes()
        assert len(raw) == target[key]["size"] and sha256(raw).hexdigest() == target[key]["sha256"]
    validator._validate_payload(target, installer.read_bytes(), archive.read_bytes())
    return SimpleNamespace(directory=directory, target=target, installer=installer, archive=archive)


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    required = ("BASELINE_DIR", "RELEASE_DIR", "TARGET_DIGEST", "SESSIONS")
    if os.name != "nt" or any(not os.environ.get(_ENV + name) for name in required):
        pytest.skip("explicit frozen Windows release assets and original session paths required")
    folder = tmp_path_factory.mktemp("verified-taskplan-upgrade")
    validator = RuntimeUpdater(folder)
    baseline_dir = Path(os.environ[_ENV + "BASELINE_DIR"]).resolve()
    for name, digest in _PUBLISHED_018.items():
        assert sha256((baseline_dir / name).read_bytes()).hexdigest() == digest, "published 0.1.8 asset changed"
    old_target = validate_target(json.loads((baseline_dir / "runtime-update.json").read_text(encoding="utf-8")))
    old = _assets(baseline_dir, target_digest(old_target), validator)
    new = _assets(Path(os.environ[_ENV + "RELEASE_DIR"]).resolve(),
                  os.environ[_ENV + "TARGET_DIGEST"], validator)
    assert old.target["version"] == "0.1.8" and new.target["version"] != "0.1.8"
    payload = folder / "verified-new-payload"
    payload.mkdir()
    validator._validate_payload(new.target, new.installer.read_bytes(), new.archive.read_bytes(), payload)
    expected = {row["path"]: row["sha256"] for row in new.target["files"]}
    assert _snapshot(payload) == expected
    sessions = [Path(value).resolve() for value in json.loads(os.environ[_ENV + "SESSIONS"])]
    assert sessions and all(session.is_dir() for session in sessions)
    originals = {session: _snapshot(session) for session in sessions}
    value = SimpleNamespace(old=old, new=new, payload=payload, sessions=sessions, logs=folder,
                            payload_hashes=expected)
    _json_write(folder / "frozen-inputs.json", {
        "old_target_digest": target_digest(old.target), "new_target_digest": target_digest(new.target),
        "old_published_assets": _PUBLISHED_018, "new_payload_file_count": len(expected),
        "sessions": {str(session): original for session, original in originals.items()},
        "python": sys.executable, "network_used": False, "model_used": False, "desktop_used": False})
    yield value
    assert _snapshot(payload) == expected, "new frozen payload changed during test"
    for session, original in originals.items():
        assert _snapshot(session) == original, "original session evidence changed during migration test"


@pytest.fixture
def installed(releases, request):
    # The real installer accepts --check-install only below the system temp.
    # Keep paths short for the .NET Framework installer's MAX_PATH contract.
    with tempfile.TemporaryDirectory(prefix="artp-") as directory:
        check_root = Path(directory).resolve() / "check"
        name = request.node.name
        result = _run(releases.old.installer, "--check-install", check_root,
                      cwd=releases.logs, log=releases.logs / (name + "-install.json"))
        assert result.returncode == 0, result.stdout + result.stderr
        root = check_root / "AgentGUIRuntimeExecutionPreview"
        record = json.loads((root / ".component-install.json").read_text(encoding="utf-8"))
        assert record["version"] == "0.1.8"
        for row in releases.old.target["files"]:
            assert sha256((root / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        private = root / "personal-data.txt"
        private.write_bytes(b"preserve-user-data\x00\xff")
        environment = root / ".venv-agent/preserve.txt"
        environment.parent.mkdir()
        environment.write_bytes(b"preserve-environment")
        yield SimpleNamespace(root=root, private=private, environment=environment, name=name,
                              check_root=check_root, before=_snapshot(root))
        assert private.read_bytes() == b"preserve-user-data\x00\xff"
        assert environment.read_bytes() == b"preserve-environment"


def _register(installed, session):
    with InstallationLease(installed.root):
        ledger.register(installed.root, session)
    return _snapshot(ledger.registry_directory(installed.root))


def _stage_with_old_code(releases, installed):
    helper = releases.logs / "stage-with-installed-018.py"
    if not helper.exists():
        helper.write_text(
            'import json,sys\nfrom pathlib import Path\n'
            'root,assets=map(Path,sys.argv[1:3])\nsys.path.insert(0,str(root))\n'
            'import app.runtime_update as module\n'
            'target=json.loads((assets/"runtime-update.json").read_text(encoding="utf-8"))\n'
            'class LocalVerifiedAssets:\n'
            ' def fetch(self,url,max_bytes):\n'
            '  name=next(name for key,name in (("payload","AgentGUIRuntimeExecution-update.zip"),("installer","AgentGUIRuntimeExecution-Setup.exe")) if target[key]["url"]==url)\n'
            '  raw=(assets/name).read_bytes()\n  assert len(raw)<=max_bytes\n  return raw\n'
            'result=module.RuntimeUpdater(root,transport=LocalVerifiedAssets()).stage(target)\n'
            'print(json.dumps({"loaded_updater":module.__file__,"result":result}))\n', encoding="utf-8")
    result = _run(sys.executable, "-I", "-B", helper, installed.root, releases.new.directory,
                  cwd=releases.logs, log=releases.logs / (installed.name + "-old-stage.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert Path(value["loaded_updater"]).resolve() == installed.root / "app/runtime_update.py"
    assert value["result"]["target_digest"] == target_digest(releases.new.target)


def test_published_018_gate_then_external_settlement_then_original_updater_apply(releases, installed):
    for session in releases.sessions:
        _register(installed, session)
    registered = _snapshot(ledger.registry_directory(installed.root))
    _stage_with_old_code(releases, installed)
    digest = target_digest(releases.new.target)
    for action in ("settle", "apply"):
        result = _cli(installed.root, installed.root, action, cwd=releases.logs,
                      log=releases.logs / (installed.name + "-old-" + action + "-RED.json"),
                      digest=digest if action == "apply" else None)
        assert result.returncode != 0 and "runtime_task_ledger" in result.stdout
        assert _snapshot(ledger.registry_directory(installed.root)) == registered
        assert _snapshot(installed.root) == installed.before
        assert not update_pending_path(installed.root).exists()
    # The manual new installer has the same unresolved-session gate.
    result = _run(releases.new.installer, "--check-install", installed.check_root, cwd=releases.logs,
                  log=releases.logs / (installed.name + "-manual-installer-RED.json"))
    assert result.returncode != 0 and "cleanup is unresolved" in result.stderr
    assert _snapshot(installed.root) == installed.before
    # Absolute NEW script path; --root names the OLD installation. No installed
    # module/PYTHONPATH/current-working-directory fallback can supply the verifier.
    assert _snapshot(releases.payload) == releases.payload_hashes
    result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
                  log=releases.logs / (installed.name + "-external-settle-GREEN.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value["settled"] is True and value["cleared_sessions"] == len(releases.sessions)
    assert _snapshot(ledger.registry_directory(installed.root)) == {}
    assert _snapshot(installed.root) == installed.before
    assert not update_pending_path(installed.root).exists()
    result = _cli(installed.root, installed.root, "apply", cwd=releases.logs, digest=digest,
                  log=releases.logs / (installed.name + "-original-updater-apply-GREEN.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "applied"
    assert not update_pending_path(installed.root).exists()
    marker = json.loads((installed.root / ".component-install.json").read_text(encoding="utf-8"))
    assert marker["version"] == releases.new.target["version"]
    for row in releases.new.target["files"]:
        assert sha256((installed.root / row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_external_settlement_keeps_registration_while_installation_is_active(releases, installed):
    before = _register(installed, releases.sessions[0])
    with InstallationLease(installed.root):
        result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
                      log=releases.logs / (installed.name + "-refused.json"))
    assert result.returncode != 0 and "runtime_running_or_under_maintenance" in result.stdout
    assert _snapshot(ledger.registry_directory(installed.root)) == before
    assert _snapshot(installed.root) == installed.before


@pytest.mark.parametrize("damage", ("unknown_input", "changed_receipt", "active_original_process"))
def test_external_settlement_keeps_unproven_originals(releases, installed, damage):
    session = installed.root.parent / "data" / ("session-" + uuid4().hex)
    journal = json.loads((releases.sessions[0] / "session-resources.json").read_text(encoding="utf-8"))
    journal.update(session_name=session.name, resources={})
    report = {"finished_at": "2026-10-27T00:00:00Z", "phase": "stopped", "host_phase": "stopped",
              "cleanup_errors": [], "sampler_stopped": True, "runner_pid": journal["runner_identity"]["pid"]}
    command = {"kind": "step", "operation": "type_text", "request": {"text": "synthetic-only-never-dispatched"}}
    response = {"command": command, "status": "returned", "result": {
        "phase": "returned", "response": {"data": {"action_executed": True}}}}
    _json_write(session / "session-resources.json", journal)
    _json_write(session / "report.json", report)
    _json_write(session / "commands/input.json", command)
    _json_write(session / "responses/input.json", response)
    # Establish that the unchanged synthetic receipt is valid before making the
    # negative case, so a fixture error cannot masquerade as a safe refusal.
    _register(installed, session)
    valid = _cli(releases.payload, installed.root, "settle", cwd=releases.logs)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    _register(installed, session)
    if damage == "unknown_input":
        (session / "responses/input.json").unlink()
    elif damage == "changed_receipt":
        response["command"] = {**command, "operation": "click"}
        _json_write(session / "responses/input.json", response)
    else:
        journal["host_identity"] = {"pid": os.getpid(), "created": psutil.Process().create_time()}
        _json_write(session / "session-resources.json", journal)
    before, registry = _snapshot(session), _snapshot(ledger.registry_directory(installed.root))
    result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
                  log=releases.logs / (installed.name + "-refused.json"))
    assert result.returncode != 0 and "runtime_task_ledger" in result.stdout
    assert _snapshot(session) == before
    assert _snapshot(ledger.registry_directory(installed.root)) == registry
    assert _snapshot(installed.root) == installed.before
