"""Full, test-owned installer -> update -> external recovery -> uninstall.

No network, model API, desktop input, or daily installation is involved. The
next-patch payload is a synthetic future version used only inside this test.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from app.instant_mcp import INSTANT_VERSION
from app.runtime_lifecycle import InstallationLease, RuntimeBusyError, update_pending_path
from app.runtime_update import RuntimeUpdater
from scripts.build_component_installer import build as build_installer, CSC
from scripts.build_execution_component import build as build_component, verify_component
from scripts.build_runtime_update import build as build_update

ROOT = Path(__file__).resolve().parents[1]
BASELINE_VERSION = INSTANT_VERSION
_major, _minor, _patch = (int(part) for part in BASELINE_VERSION.split("."))
FUTURE_VERSION = f"{_major}.{_minor}.{_patch + 1}"
pytestmark = pytest.mark.skipif(os.name != "nt" or not Path(CSC).is_file(), reason="Windows .NET compiler required")


def _manifest(payload, path):
    rows = [{"path": p.relative_to(payload).as_posix(), "size": p.stat().st_size,
             "sha256": sha256(p.read_bytes()).hexdigest()}
            for p in sorted(payload.rglob("*")) if p.is_file()]
    path.write_text(json.dumps({"files": rows}), encoding="utf-8")


def _json_write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(*arguments):
    result = subprocess.run([str(a) for a in arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture
def short_installation_root():
    # .NET Framework installer APIs still have MAX_PATH limits. A test-owned
    # short root also represents the normal per-user product installation.
    with tempfile.TemporaryDirectory(prefix="aru-") as directory:
        path = Path(directory).resolve()
        assert path.parent == Path(tempfile.gettempdir()).resolve()
        yield path


def test_full_installed_payload_update_health_rollback_and_crash_recovery(tmp_path, short_installation_root):
    original_payload = tmp_path / "payload-baseline"
    original = build_component(ROOT, original_payload, version=BASELINE_VERSION, python=sys.executable)
    original_installer = build_installer(component="execution", version=BASELINE_VERSION,
        payload_dir=original_payload, manifest=original["installer_manifest"], output_dir=tmp_path / "installer-baseline")
    future_payload = tmp_path / "payload-future"
    shutil.copytree(original_payload, future_payload)
    entry = future_payload / "app/instant_mcp.py"
    entry_source = entry.read_text(encoding="utf-8")
    old_identity = f'INSTANT_VERSION = "{BASELINE_VERSION}"'
    assert entry_source.count(old_identity) == 1
    entry.write_text(entry_source.replace(old_identity, f'INSTANT_VERSION = "{FUTURE_VERSION}"', 1), encoding="utf-8")
    source_manifest = future_payload / "COMPONENT_SOURCE_MANIFEST.json"
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    for row in source["files"]:
        path = future_payload / row["path"]
        row.update(bytes=path.stat().st_size, sha256=sha256(path.read_bytes()).hexdigest())
    _json_write(source_manifest, source)
    descriptor_path = future_payload / "execution-installation.json"
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    descriptor["version"] = FUTURE_VERSION
    for row in descriptor["files"]:
        row["sha256"] = sha256((future_payload / row["path"]).read_bytes()).hexdigest()
    _json_write(descriptor_path, descriptor)
    verify_component(future_payload, tmp_path / "synthetic-future-preflight.json", python=sys.executable)
    future_manifest = tmp_path / "future-files.json"
    _manifest(future_payload, future_manifest)
    future_installer = build_installer(component="execution", version=FUTURE_VERSION, payload_dir=future_payload,
        manifest=future_manifest, output_dir=tmp_path / "installer-future")
    assets = build_update(tmp_path / "installer-future", tmp_path / "update-assets")
    target = json.loads(Path(assets["manifest"]).read_text(encoding="utf-8"))
    blobs = {target["payload"]["url"]: Path(assets["payload"]).read_bytes(),
             target["installer"]["url"]: Path(future_installer["setup_path"]).read_bytes()}
    class FixedTransport:
        def fetch(self, url, max_bytes):
            value = blobs[url]
            assert len(value) <= max_bytes
            return value
    check_root = short_installation_root / "check"
    _run(original_installer["setup_path"], "--check-install", check_root)
    installed = check_root / "AgentGUIRuntimeExecutionPreview"
    # These files are deliberately outside installer ownership and survive all
    # update, rollback and uninstall operations.
    private = installed / "personal-data.txt"
    private.write_bytes(b"keep-user-data")
    environment = installed / ".venv-agent"
    environment.mkdir()
    (environment / "preserve.txt").write_bytes(b"keep-environment")
    updater = RuntimeUpdater(installed, transport=FixedTransport())
    staged = updater.stage(target)
    digest = staged["target_digest"]
    with InstallationLease(installed):
        with pytest.raises(RuntimeBusyError):
            updater.apply(digest, health_check=lambda _: True)
    result = _run(sys.executable, "-I", "-B", installed / "scripts/update_runtime.py", "--root", installed,
                  "apply", "--confirm-target", digest)
    applied = json.loads(result.stdout)
    assert applied["status"] == "applied" and applied["version"] == FUTURE_VERSION
    assert not update_pending_path(installed).exists()
    assert updater._record()["version"] == FUTURE_VERSION
    # Call the actual ordinary C# ownership reader without changing the marker.
    # Reinstalling here would itself be another transaction, invalidating the
    # updater's exact marker backup intentionally.
    probe = tmp_path / "read-installed-record.ps1"
    probe.write_text('param([string]$Installer,[string]$Root)\n'
        '$ErrorActionPreference="Stop"\n'
        '$assembly=[Reflection.Assembly]::Load([IO.File]::ReadAllBytes($Installer))\n'
        '$method=$assembly.GetType("ComponentInstaller").GetMethod("ReadRecord",[Reflection.BindingFlags]"Static,NonPublic")\n'
        '$record=$method.Invoke($null,[object[]]@($Root,$true,$true))\n'
        '$record.version | ConvertTo-Json -Compress\n', encoding="utf-8")
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = _run(shell, "-NoProfile", "-NonInteractive", "-File", probe,
                  "-Installer", future_installer["setup_path"], "-Root", installed)
    assert json.loads(result.stdout) == FUTURE_VERSION
    rollback_digest = applied["rollback_target"]["target_digest"]
    result = _run(sys.executable, "-I", "-B", installed / "scripts/update_runtime.py", "--root", installed,
                  "rollback", "--confirm-target", rollback_digest)
    assert json.loads(result.stdout)["status"] == "rolled_back"
    assert updater._record()["version"] == BASELINE_VERSION
    assert private.read_bytes() == b"keep-user-data"
    assert (environment / "preserve.txt").read_bytes() == b"keep-environment"
    updater.stage(target)
    # Simulate process loss after a real file replacement. It is not a power-
    # failure simulation: durability is separately covered by write-through IO.
    crash = ("import sys,os; from app.runtime_update import RuntimeUpdater; "
             "u=RuntimeUpdater(sys.argv[1]); original=u._replace; "
             "u._replace=lambda source,target:(original(source,target),os._exit(23)); "
             "u.apply(sys.argv[2],health_check=lambda _:True)")
    process = subprocess.run([sys.executable, "-B", "-c", crash, str(installed), digest], cwd=ROOT,
                             capture_output=True, timeout=60)
    assert process.returncode == 23, process.stderr.decode("utf-8", errors="replace")
    assert update_pending_path(installed).is_file()
    with pytest.raises(RuntimeBusyError, match="recovery_required"):
        with InstallationLease(installed):
            pass
    recovery = updater.status()["recovery_command"]
    assert not Path(recovery[3]).is_relative_to(installed)
    result = _run(*recovery)
    assert json.loads(result.stdout)["status"] == "rolled_back"
    assert updater._record()["version"] == BASELINE_VERSION
    assert not update_pending_path(installed).exists()
    assert private.read_bytes() == b"keep-user-data"
    # Validate compatibility with the ordinary frozen-ownership uninstall path.
    # Check mode waits for its helper; its parent must therefore be the exact
    # original installer outside the installation, as in existing installer tests.
    _run(original_installer["setup_path"], "--check-uninstall", check_root)
    assert not (installed / "app/instant_mcp.py").exists()
    assert private.read_bytes() == b"keep-user-data"
    assert (environment / "preserve.txt").read_bytes() == b"keep-environment"
