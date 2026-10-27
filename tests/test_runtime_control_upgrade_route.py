"""Opt-in published 0.1.9 -> frozen 0.1.10 upgrade, with old sessions unchanged.

Set AGENT_GUI_RUNTIME_CONTROL_UPGRADE_PREPARED_INPUTS to the immutable output of
the external old-payload producer, RELEASE_DIR to real new release assets, and
TARGET_DIGEST to the independently frozen exact target. No network, desktop,
daily installation, or model service is used.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

import psutil
import pytest

from app import runtime_task_ledger as ledger
from app.runtime_lifecycle import InstallationLease, update_pending_path
from app.runtime_update import RuntimeUpdater, target_digest, validate_target
from tests.test_runtime_taskplan_upgrade_route import _assets, _cli, _json_write, _run, _snapshot


_ENV = "AGENT_GUI_RUNTIME_CONTROL_UPGRADE_"
_PUBLISHED_019 = {
    "runtime-update.json": "1b3e23c9da0921ccb44e7c77dc15585f798a5d702e4961ad622c4c18b6c9c123",
    "AgentGUIRuntimeExecution-Setup.exe": "bde46f7a8c47b42388c8ac39916c5152cb0931528d171170c0d9b91e2bf5e972",
    "AgentGUIRuntimeExecution-update.zip": "0e54ee8037bc2104d5a1b0729ca3f4f14add54f53c7d5a0c0e186b60f67d52ff",
}


@pytest.fixture(scope="module")
def releases(tmp_path_factory):
    names = ("PREPARED_INPUTS", "RELEASE_DIR", "TARGET_DIGEST")
    if os.name != "nt" or any(not os.environ.get(_ENV + name) for name in names):
        pytest.skip("explicit published 0.1.9 originals and frozen 0.1.10 release assets required")
    prepared = json.loads(Path(os.environ[_ENV + "PREPARED_INPUTS"]).read_text(encoding="utf-8"))
    baseline = Path(prepared["baseline_assets"]).resolve()
    assert prepared["published_asset_sha256"] == _PUBLISHED_019
    for name, expected in _PUBLISHED_019.items():
        assert sha256((baseline / name).read_bytes()).hexdigest() == expected
    folder = tmp_path_factory.mktemp("verified-control-upgrade")
    validator = RuntimeUpdater(folder)
    old_target = validate_target(json.loads((baseline / "runtime-update.json").read_text(encoding="utf-8")))
    old = _assets(baseline, target_digest(old_target), validator)
    new = _assets(Path(os.environ[_ENV + "RELEASE_DIR"]).resolve(),
        os.environ[_ENV + "TARGET_DIGEST"], validator)
    assert old.target["version"] == "0.1.9" and new.target["version"] == "0.1.10"
    payload = folder / "verified-new-payload"
    payload.mkdir()
    validator._validate_payload(new.target, new.installer.read_bytes(), new.archive.read_bytes(), payload)
    expected = {row["path"]: row["sha256"] for row in new.target["files"]}
    assert _snapshot(payload) == expected
    sessions = {key: Path(value["session"]).resolve() for key, value in prepared["scenarios"].items()}
    assert set(sessions) == {"observe", "rejected-no-proof"}
    for key, session in sessions.items():
        scenario = prepared["scenarios"][key]
        assert _snapshot(session) == scenario["session_files"]
        assert scenario["original_dispatch_count"] == 1 and scenario["terminal_runner_state"] == "completed"
        assert scenario["new_control_receipt_exists"] is False
        old_payload = Path(prepared["payload"]).resolve()
        assert scenario["namespace_app_path"] == [str(old_payload / "app")]
        assert all(Path(value["path"]).resolve().is_relative_to(old_payload)
            for value in scenario["app_modules"].values())
    originals = {session: _snapshot(session) for session in sessions.values()}
    _json_write(folder / "frozen-inputs.json", {
        "prepared_inputs": os.environ[_ENV + "PREPARED_INPUTS"], "old_published_assets": _PUBLISHED_019,
        "old_target_digest": target_digest(old.target), "new_target_digest": target_digest(new.target),
        "new_payload_file_count": len(expected), "sessions": {str(key): value for key, value in originals.items()},
        "python": sys.executable, "network_used": False, "desktop_used": False, "model_used": False})
    yield SimpleNamespace(old=old, new=new, payload=payload, sessions=sessions, logs=folder,
        prepared=prepared, payload_hashes=expected)
    assert _snapshot(payload) == expected
    for session, before in originals.items():
        assert _snapshot(session) == before, "immutable old session changed during upgrade acceptance"


@pytest.fixture
def installed(releases, request):
    with tempfile.TemporaryDirectory(prefix="arcu-") as directory:
        check_root = Path(directory).resolve() / "check"
        name = request.node.name
        result = _run(releases.old.installer, "--check-install", check_root,
            cwd=releases.logs, log=releases.logs / (name + "-install.json"))
        assert result.returncode == 0, result.stdout + result.stderr
        root = check_root / "AgentGUIRuntimeExecutionPreview"
        assert json.loads((root / ".component-install.json").read_text(encoding="utf-8"))["version"] == "0.1.9"
        for row in releases.old.target["files"]:
            assert sha256((root / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        private = root / "personal-data.txt"
        private.write_bytes(b"preserve-control-upgrade-user-data\x00\xff")
        environment = root / ".venv-agent/preserve.txt"
        environment.parent.mkdir()
        environment.write_bytes(b"preserve-control-upgrade-environment")
        yield SimpleNamespace(root=root, private=private, environment=environment,
            name=name, check_root=check_root, before=_snapshot(root))
        assert private.read_bytes() == b"preserve-control-upgrade-user-data\x00\xff"
        assert environment.read_bytes() == b"preserve-control-upgrade-environment"


def _register(installed, session):
    with InstallationLease(installed.root):
        ledger.register(installed.root, session)
    return _snapshot(ledger.registry_directory(installed.root))


def _stage_old(releases, installed):
    helper = releases.logs / "stage-with-published-019.py"
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


def test_published_019_observe_gate_external_settlement_and_original_updater_apply(releases, installed):
    registry = _register(installed, releases.sessions["observe"])
    _stage_old(releases, installed)
    digest = target_digest(releases.new.target)
    for action in ("settle", "apply"):
        result = _cli(installed.root, installed.root, action, cwd=releases.logs,
            log=releases.logs / (installed.name + "-old-" + action + "-RED.json"),
            digest=digest if action == "apply" else None)
        assert result.returncode != 0 and "runtime_task_ledger" in result.stdout
        assert _snapshot(ledger.registry_directory(installed.root)) == registry
        assert _snapshot(installed.root) == installed.before
        assert not update_pending_path(installed.root).exists()
    result = _run(releases.new.installer, "--check-install", installed.check_root,
        cwd=releases.logs, log=releases.logs / (installed.name + "-manual-installer-RED.json"))
    assert result.returncode != 0 and "cleanup is unresolved" in result.stderr
    assert _snapshot(installed.root) == installed.before
    result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
        log=releases.logs / (installed.name + "-external-settle-GREEN.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value["settled"] is True and value["cleared_sessions"] == 1
    assert _snapshot(ledger.registry_directory(installed.root)) == {}
    assert _snapshot(installed.root) == installed.before and not update_pending_path(installed.root).exists()
    result = _cli(installed.root, installed.root, "apply", cwd=releases.logs, digest=digest,
        log=releases.logs / (installed.name + "-original-updater-apply-GREEN.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["status"] == "applied"
    assert not update_pending_path(installed.root).exists()
    marker = json.loads((installed.root / ".component-install.json").read_text(encoding="utf-8"))
    assert marker["version"] == "0.1.10"
    for row in releases.new.target["files"]:
        assert sha256((installed.root / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    health_report = releases.logs / (installed.name + "-health.json")
    result = _run(sys.executable, "-I", "-B", installed.root / "scripts/check_execution_component.py",
        "--root", installed.root, "--report", health_report, cwd=releases.logs,
        log=releases.logs / (installed.name + "-health-command.json"))
    health = json.loads(health_report.read_text(encoding="utf-8"))
    assert result.returncode == 0 and health["passed"] is True
    assert health["input_executed"] is False and health["host_started"] is False


def test_external_verifier_retains_old_rejected_control_without_original_proof(releases, installed):
    before = _register(installed, releases.sessions["rejected-no-proof"])
    result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
        log=releases.logs / (installed.name + "-refused.json"))
    assert result.returncode != 0 and "runtime_task_ledger" in result.stdout
    assert _snapshot(ledger.registry_directory(installed.root)) == before
    assert _snapshot(installed.root) == installed.before


def test_external_verifier_retains_registration_while_installation_is_active(releases, installed):
    before = _register(installed, releases.sessions["observe"])
    with InstallationLease(installed.root):
        result = _cli(releases.payload, installed.root, "settle", cwd=releases.logs,
            log=releases.logs / (installed.name + "-refused.json"))
    assert result.returncode != 0 and "runtime_running_or_under_maintenance" in result.stdout
    assert _snapshot(ledger.registry_directory(installed.root)) == before
    assert _snapshot(installed.root) == installed.before


@pytest.mark.parametrize("damage", ("missing_receipt", "changed_receipt", "active_original_process"))
def test_external_verifier_retains_missing_changed_or_active_evidence(releases, installed, damage):
    # These independent negative-only fixtures do not clone or alter the old
    # regression originals. Prove the intact fixture through the new CLI first.
    session = installed.root.parent / "data" / ("session-negative-" + damage)
    old = releases.sessions["observe"]
    journal = json.loads((old / "session-resources.json").read_text(encoding="utf-8"))
    journal.update(session_name=session.name, resources={})
    report = json.loads((old / "report.json").read_text(encoding="utf-8"))
    command = {"kind": "step", "operation": "type_text", "request": {"text": "offline-only-never-dispatched"}}
    response = {"command": command, "status": "returned", "result": {
        "phase": "returned", "response": {"data": {"action_executed": True}}}}
    _json_write(session / "session-resources.json", journal)
    _json_write(session / "report.json", report)
    _json_write(session / "commands/input.json", command)
    _json_write(session / "responses/input.json", response)
    _register(installed, session)
    valid = _cli(releases.payload, installed.root, "settle", cwd=releases.logs)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    _register(installed, session)
    if damage == "missing_receipt":
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
