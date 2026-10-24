"""Transaction/transport fault tests; all installations are temporary fixtures."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from app import runtime_update as update
from app.runtime_lifecycle import InstallationLease, RuntimeBusyError, update_pending_path
from scripts.build_component_installer import CSC, build


pytestmark = pytest.mark.skipif(not CSC.is_file(), reason="Windows .NET compiler required for real installer fixtures")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class Transport:
    def __init__(self, blobs):
        self.blobs = dict(blobs)
        self.calls = []

    def fetch(self, url, max_bytes):
        self.calls.append((url, max_bytes))
        return self.blobs[url]


@pytest.fixture(scope="module")
def packages(tmp_path_factory):
    directory = tmp_path_factory.mktemp("runtime-update-packages")
    result = {}
    for version in ("0.1.0", "0.1.1", "0.1.2"):
        folder = directory / version
        payload = folder / "payload"
        payload.mkdir(parents=True)
        sources = {
            "LICENSE": b"fixture license\n",
            "pyproject.toml": b'requires-python = ">=3.11,<3.13"\n',
            "uv.lock": b"version = 1\n",
            "requirements/agent-runtime-api-win.lock.txt": b"fixture==1\n",
            "configs/provider.example.json": b"{}\n",
            "scripts/setup_instant.ps1": b"# fixture only\n",
            "scripts/run_local_step_session.py": b"# fixture only\n",
            "scripts/update_runtime.py": b"# maintained update CLI fixture\n",
            "app/runtime_update.py": b"# maintained updater fixture\n",
            "app/runtime_lifecycle.py": b"# maintained lifecycle fixture\n",
            "app/runtime_task_ledger.py": b"# maintained ledger fixture\n",
            "app/code.py": ("VERSION = " + repr(version) + "\n").encode(),
            "README.md": ("Version " + version + "\n").encode(),
        }
        sources["docs/removed.md" if version == "0.1.0" else "app/added.py"] = b"owned fixture\n"
        for name, raw in sources.items():
            path = payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        descriptor = {"schema": "execution_installation.v1", "component": "execution", "version": version,
                      "protocol": "workflow_queue.v1", "capabilities": ["learning_workflow.v1"],
                      "runner_entry": "scripts/run_local_step_session.py",
                      "files": [{"path": n, "sha256": digest(raw)} for n, raw in sorted(sources.items())]}
        (payload / "execution-installation.json").write_text(json.dumps(descriptor), encoding="utf-8")
        rows = [{"path": p.relative_to(payload).as_posix(), "size": p.stat().st_size,
                 "sha256": digest(p.read_bytes())} for p in sorted(payload.rglob("*")) if p.is_file()]
        manifest = folder / "files.json"
        manifest.write_text(json.dumps({"files": rows}), encoding="utf-8")
        output = folder / "installer"
        built = build(component="execution", version=version, payload_dir=payload, manifest=manifest, output_dir=output)
        exe = Path(built["setup_path"]).read_bytes()
        archive = (output / "payload.zip").read_bytes()
        metadata = json.loads((output / "payload-manifest.json").read_text(encoding="utf-8"))
        def asset(raw, name):
            return {"url": update._asset_url(version, name), "size": len(raw), "sha256": digest(raw)}
        target = update.validate_target({"schema": "runtime_update.v1", "component": "execution", "version": version,
                                        "python_contract": update.PYTHON_CONTRACT, "files": metadata["files"],
                                        "payload": asset(archive, "AgentGUIRuntimeExecution-update.zip"),
                                        "installer": asset(exe, "AgentGUIRuntimeExecution-Setup.exe")})
        result[version] = {"target": target, "payload": payload, "exe": exe, "archive": archive,
                           "manifest": (output / "payload-manifest.json").read_bytes()}
    return result


@pytest.fixture
def installation(tmp_path, packages):
    old = packages["0.1.0"]
    root = tmp_path / "installed"
    shutil.copytree(old["payload"], root)
    (root / "Uninstall.exe").write_bytes(old["exe"])
    record = {"format": "component-install-v1", "component": "execution", "product_id": update.PRODUCT_ID,
              "version": "0.1.0", "root": str(root.resolve()), "user_sid": update._current_sid(),
              "mode": "check", "state": "installed", "files": old["target"]["files"] + [
                  {"path": "Uninstall.exe", "size": len(old["exe"]), "sha256": digest(old["exe"])}]}
    (root / ".component-install.json").write_text(json.dumps(record), encoding="utf-8")
    blobs = {}
    for package in packages.values():
        blobs[package["target"]["payload"]["url"]] = package["archive"]
        blobs[package["target"]["installer"]["url"]] = package["exe"]
    transport = Transport(blobs)
    updater = update.RuntimeUpdater(root, transport=transport)
    return root, updater, transport


def owned_bytes(root):
    marker = json.loads((root / ".component-install.json").read_text(encoding="utf-8"))
    return {r["path"]: (root / r["path"]).read_bytes() for r in marker["files"]} | {
        ".component-install.json": (root / ".component-install.json").read_bytes()}


def stage(updater, packages, version="0.1.1"):
    return updater.stage(packages[version]["target"])["target_digest"]


def test_real_installer_resources_and_frozen_identity_constants(packages):
    package = packages["0.1.1"]
    assert update.installer_resources(package["exe"]) == {
        "payload.zip": package["archive"], "payload-manifest.json": package["manifest"]}
    old = digest(package["manifest"]).encode("utf-16-le")
    changed = package["exe"].replace(old, ("0" * 64).encode("utf-16-le"))
    assert changed != package["exe"]
    with pytest.raises(update.RuntimeUpdateError, match="identity_constants"):
        update.installer_resources(changed)


@pytest.mark.parametrize("mutation", [
    lambda t: t.update(command="powershell remote command"),
    lambda t: t.update(version="1.2.3-preview"),
    lambda t: t["payload"].update(url="http://127.0.0.1/update.zip"),
    lambda t: t["installer"].update(url="https://github.com/other/repo/releases/download/update.exe"),
    lambda t: t["files"][0].update(path="../outside.py"),
    lambda t: t["files"][0].update(path=".venv-agent/site.py"),
    lambda t: t["files"].append(dict(t["files"][0])),
])
def test_strict_metadata_rejects_remote_commands_paths_and_untrusted_sources(packages, mutation):
    target = deepcopy(packages["0.1.1"]["target"])
    mutation(target)
    with pytest.raises(update.RuntimeUpdateError):
        update.validate_target(target)


def test_release_check_selects_newest_stable_and_binds_metadata(installation, packages):
    root, updater, transport = installation
    releases = []
    for version in ("0.1.1", "0.1.2"):
        raw = json.dumps(packages[version]["target"]).encode()
        url = update._asset_url(version, "runtime-update.json")
        transport.blobs[url] = raw
        releases.append({"tag_name": "instant-v" + version, "draft": False, "prerelease": False,
                         "assets": [{"name": "runtime-update.json", "size": len(raw),
                                     "browser_download_url": url, "digest": "sha256:" + digest(raw)}]})
    releases.append({"tag_name": "instant-v9.0.0", "draft": False, "prerelease": True, "assets": []})
    transport.blobs[update.RELEASES_URL] = json.dumps(releases).encode()
    assert updater.check()["version"] == "0.1.2"
    assert updater._record()["version"] == "0.1.0"
    assert not update_pending_path(root).exists()


def test_duplicate_json_key_rejected():
    with pytest.raises(update.RuntimeUpdateError, match="duplicate"):
        update._json(b'{"version":"0.1.1","version":"0.1.2"}')


def test_stage_is_durable_and_never_mutates_installation_while_task_is_live(installation, packages):
    root, updater, _ = installation
    original = owned_bytes(root)
    with InstallationLease(root):
        target = stage(updater, packages)
        assert owned_bytes(root) == original
        with pytest.raises(RuntimeBusyError):
            updater.apply(target, health_check=lambda _: True)
    assert update.RuntimeUpdater(root).status()["target_digest"] == target
    assert not update_pending_path(root).exists()


@pytest.mark.parametrize("change", ["dependencies", "missing_contract", "python", "config", "bootstrap", "release_contract"])
def test_environment_configuration_and_legacy_bootstrap_require_manual_install(installation, packages, change):
    root, updater, transport = installation
    target = deepcopy(packages["0.1.1"]["target"])
    if change == "release_contract":
        target["version"] = "0.2.0"
        for key, filename in (("payload", "AgentGUIRuntimeExecution-update.zip"), ("installer", "AgentGUIRuntimeExecution-Setup.exe")):
            target[key]["url"] = update._asset_url(target["version"], filename)
    elif change == "python":
        target["python_contract"] = "cpython-3.13.v1"
    elif change == "missing_contract":
        target["files"] = [r for r in target["files"] if r["path"] != "uv.lock"]
    elif change == "bootstrap":
        old_record = updater._record
        updater._record = lambda: {**old_record(), "files": [r for r in old_record()["files"] if r["path"] != "scripts/update_runtime.py"]}
    else:
        prefix = "requirements/" if change == "dependencies" else "configs/"
        next(r for r in target["files"] if r["path"].startswith(prefix))["sha256"] = "0" * 64
    with pytest.raises(update.RuntimeUpdateError, match="manual_install_required"):
        updater.stage(target)
    assert transport.calls == []


def test_corrupted_download_and_installer_payload_disagreement_do_not_stage(installation, packages):
    root, updater, transport = installation
    target = deepcopy(packages["0.1.1"]["target"])
    transport.blobs[target["payload"]["url"]] = b"corrupt"
    with pytest.raises(update.RuntimeUpdateError, match="size_or_hash"):
        updater.stage(target)
    replacement = packages["0.1.0"]["archive"]
    transport.blobs[target["payload"]["url"]] = replacement
    target["payload"].update(size=len(replacement), sha256=digest(replacement))
    # Same version with differing bytes is independently blocked by highwater.
    updater.state.joinpath("highwater.json").unlink()
    with pytest.raises(update.RuntimeUpdateError, match="embedded_payload_mismatch"):
        updater.stage(target)
    assert not (updater.state / "stage.json").exists()


def test_modified_owned_file_is_refused_before_and_after_staging(installation, packages):
    root, updater, _ = installation
    path = root / "app/code.py"
    old = path.read_bytes()
    path.write_bytes(b"user edit")
    with pytest.raises(update.RuntimeUpdateError, match="owned_file_modified"):
        updater.stage(packages["0.1.1"]["target"])
    path.write_bytes(old)
    target = stage(updater, packages)
    path.write_bytes(b"another user edit")
    with pytest.raises(update.RuntimeUpdateError, match="owned_file_modified"):
        updater.apply(target, health_check=lambda _: True)
    assert path.read_bytes() == b"another user edit"
    assert not update_pending_path(root).exists()


def test_exact_confirmation_and_unknown_file_collision_are_refused(installation, packages):
    root, updater, _ = installation
    target = stage(updater, packages)
    with pytest.raises(update.RuntimeUpdateError, match="exact_target_confirmation"):
        updater.apply("0" * 64, health_check=lambda _: True)
    unknown = root / "app/added.py"
    unknown.write_bytes(b"user file")
    with pytest.raises(update.RuntimeUpdateError, match="refusing_unknown_file"):
        updater.apply(target, health_check=lambda _: True)
    assert unknown.read_bytes() == b"user file"


def test_success_updates_marker_and_uninstaller_together_preserves_user_data(installation, packages):
    root, updater, _ = installation
    for name in [".venv-agent/keep.txt", "data/private.json", "models/weights.bin", "mcp-config.local.json"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"private unchanged")
    target = stage(updater, packages)
    def health(selected):
        assert selected == root.resolve()
        assert update_pending_path(root).exists()
        assert updater._record()["version"] == "0.1.1"
        with pytest.raises(RuntimeBusyError):
            with InstallationLease(root):
                pass
        return True
    result = updater.apply(target, health_check=health)
    assert result["status"] == "applied"
    assert updater._record()["version"] == "0.1.1"
    assert (root / "Uninstall.exe").read_bytes() == packages["0.1.1"]["exe"]
    assert not (root / "docs/removed.md").exists()
    for name in [".venv-agent/keep.txt", "data/private.json", "models/weights.bin", "mcp-config.local.json"]:
        assert (root / name).read_bytes() == b"private unchanged"
    assert not update_pending_path(root).exists()


def test_health_failure_restores_exact_owned_bytes_and_keeps_backups(installation, packages):
    root, updater, _ = installation
    original = owned_bytes(root)
    target = stage(updater, packages)
    with pytest.raises(update.RuntimeUpdateError, match="health_check_failed"):
        updater.apply(target, health_check=lambda _: False)
    assert owned_bytes(root) == original
    assert not (root / "app/added.py").exists()
    assert updater.status()["status"] == "rolled_back"
    assert not update_pending_path(root).exists()
    assert list(updater.state.glob("transactions/*/backup/Uninstall.exe"))


class ProcessInterrupted(BaseException):
    pass


def test_process_interruption_blocks_start_and_recovers_with_new_updater(installation, packages, monkeypatch):
    root, updater, _ = installation
    original = owned_bytes(root)
    target = stage(updater, packages)
    replace = updater._replace
    def crash(source, destination):
        replace(source, destination)
        raise ProcessInterrupted()
    updater._replace = crash
    with pytest.raises(ProcessInterrupted):
        updater.apply(target, health_check=lambda _: True)
    assert update_pending_path(root).exists()
    with pytest.raises(RuntimeBusyError):
        with InstallationLease(root):
            pass
    recovery = update.RuntimeUpdater(root)
    command = recovery.status()["recovery_command"]
    assert str(recovery.state) in command[3]
    assert "/backup/" in command[3].replace("\\", "/")
    with monkeypatch.context() as patch:
        def unavailable():
            raise update.RuntimeUpdateError("partly_replaced_installation_identity")
        patch.setattr(recovery, "_record", unavailable)
        status = recovery.status()
        assert status["installed_version"] is None and status["install_identity_unavailable"] is True
        assert status["recovery_command"] == command
    with pytest.raises(update.RuntimeUpdateError, match="exact_recovery"):
        recovery.recover("0" * 64)
    assert recovery.recover(target)["status"] == "rolled_back"
    assert owned_bytes(root) == original
    assert not update_pending_path(root).exists()


def test_rollback_failure_preserves_pending_and_can_be_retried(installation, packages):
    root, updater, _ = installation
    original = owned_bytes(root)
    target = stage(updater, packages)
    replace = updater._replace
    failing = {"rollback": False}
    def maybe_fail(source, destination):
        if failing["rollback"]:
            raise OSError("simulated locked rollback destination")
        replace(source, destination)
    updater._replace = maybe_fail
    def health(_):
        failing["rollback"] = True
        return False
    with pytest.raises(update.RuntimeRollbackError, match="backups_preserved"):
        updater.apply(target, health_check=health)
    assert updater.status()["status"] == "rollback_failed"
    assert update_pending_path(root).exists()
    with pytest.raises(update.RuntimeUpdateError, match="recovery_required"):
        updater.stage(packages["0.1.2"]["target"])
    updater._replace = replace
    assert updater.recover(target)["status"] == "rolled_back"
    assert owned_bytes(root) == original


def test_explicit_rollback_binds_old_digest_and_does_not_lower_highwater(installation, packages):
    root, updater, _ = installation
    original = owned_bytes(root)
    target = stage(updater, packages, "0.1.2")
    result = updater.apply(target, health_check=lambda _: True)
    with pytest.raises(update.RuntimeUpdateError, match="exact_rollback"):
        updater.rollback(target)
    assert updater.rollback(result["rollback_target"]["target_digest"])["status"] == "rolled_back"
    assert owned_bytes(root) == original
    status = updater.status()
    assert status["installed_version"] == "0.1.0" and status["version"] == "0.1.2"
    with pytest.raises(update.RuntimeUpdateError, match="highwater"):
        updater.stage(packages["0.1.1"]["target"])


def test_rollback_does_not_overwrite_later_user_edit(installation, packages):
    root, updater, _ = installation
    result = updater.apply(stage(updater, packages), health_check=lambda _: True)
    (root / "app/code.py").write_bytes(b"later user edit")
    with pytest.raises(update.RuntimeUpdateError, match="owned_file_modified"):
        updater.rollback(result["rollback_target"]["target_digest"])
    assert (root / "app/code.py").read_bytes() == b"later user edit"


class Registry:
    def __init__(self):
        self.version = "0.1.0"
        self.fail_once = False
        self.calls = []
    def snapshot(self, root):
        self.calls.append("snapshot")
        return {"version": self.version, "type": 1}
    def set_version(self, root, version):
        self.calls.append("set")
        self.version = version
        if self.fail_once:
            self.fail_once = False
            raise OSError("simulated registry failure after write")
    def restore(self, root, snapshot):
        self.calls.append("restore")
        self.version = snapshot["version"]


def test_normal_registry_version_is_transactional_and_check_mode_never_touches_it(installation, packages):
    root, updater, _ = installation
    registry = Registry()
    updater.registry = registry
    target = stage(updater, packages)
    updater.apply(target, health_check=lambda _: True)
    assert registry.calls == []
    updater.rollback(updater.status()["rollback_target"]["target_digest"])
    marker = root / ".component-install.json"
    value = json.loads(marker.read_text(encoding="utf-8"));value["mode"] = "normal"
    marker.write_text(json.dumps(value), encoding="utf-8")
    original = owned_bytes(root)
    registry.fail_once = True
    with pytest.raises(update.RuntimeUpdateError, match="registry failure"):
        updater.apply(target, health_check=lambda _: True)
    assert owned_bytes(root) == original
    assert registry.version == "0.1.0"
    assert "restore" in registry.calls


@pytest.mark.parametrize("change", ["extra_operation", "changed_fact", "old_record", "rollback_digest", "backup_corrupt"])
def test_recovery_validates_complete_frozen_ownership_before_first_restore(installation, packages, change):
    root, updater, _ = installation
    target = stage(updater, packages)
    replace = updater._replace
    def crash(source, destination):
        replace(source, destination)
        raise ProcessInterrupted()
    updater._replace = crash
    with pytest.raises(ProcessInterrupted):
        updater.apply(target, health_check=lambda _: True)
    journal = updater._journal()
    tx = updater._tx(journal)
    unknown = root / "docs/user-note.md"
    unknown.write_bytes(b"user note must survive")
    if change == "extra_operation":
        payload = b"attacker overwrite"
        backup = tx / "backup/docs/user-note.md"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(payload)
        journal["operations"].append({"path": "docs/user-note.md", "old": {
            "path": "docs/user-note.md", "size": len(payload), "sha256": digest(payload)}, "new": None})
    elif change == "changed_fact":
        journal["operations"][0]["new"]["sha256"] = "0" * 64
    elif change == "old_record":
        journal["old_record"]["files"][0]["sha256"] = "0" * 64
    elif change == "rollback_digest":
        journal["rollback_target_digest"] = "0" * 64
    else:
        (tx / "backup/app/code.py").write_bytes(b"corrupt backup")
    updater._save(journal)
    current = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    recovery = update.RuntimeUpdater(root)
    restores = []
    recovery._replace = lambda *args: restores.append(args)
    with pytest.raises(update.RuntimeRollbackError):
        recovery.recover(target)
    assert restores == []
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()} == current
    assert unknown.read_bytes() == b"user note must survive"
    assert update_pending_path(root).exists()


def test_unsupported_running_python_requires_manual_environment_migration(installation, packages, monkeypatch):
    _, updater, transport = installation
    monkeypatch.setattr(update, "sys", SimpleNamespace(implementation=SimpleNamespace(name="cpython"), version_info=(3, 13)))
    with pytest.raises(update.RuntimeUpdateError, match="running_python_contract"):
        updater.stage(packages["0.1.1"]["target"])
    assert transport.calls == []


def test_user_edit_between_preflight_and_replace_is_preserved_and_blocks_resume(installation, packages):
    root, updater, _ = installation
    target = stage(updater, packages)
    replace = updater._replace
    edited = {"value": False}
    def race(source, destination):
        replace(source, destination)
        if not edited["value"]:
            (root / "app/code.py").write_bytes(b"concurrent user change")
            edited["value"] = True
    updater._replace = race
    with pytest.raises(update.RuntimeRollbackError):
        updater.apply(target, health_check=lambda _: True)
    assert (root / "app/code.py").read_bytes() == b"concurrent user change"
    assert update_pending_path(root).exists()


@pytest.mark.parametrize("journal_phase", ["committed", "rolled_back", "applying"])
def test_external_install_change_refuses_stale_rollback_before_pending_marker(installation, packages, journal_phase):
    root, updater, _ = installation
    result = updater.apply(stage(updater, packages), health_check=lambda _: True)
    # A later legitimate installer creates a new valid frozen ownership record.
    replacement = packages["0.1.2"]
    record = updater._record()
    for row in replacement["target"]["files"]:
        destination = root / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((replacement["payload"] / row["path"]).read_bytes())
    (root / "Uninstall.exe").write_bytes(replacement["exe"])
    record.update(version="0.1.2", files=replacement["target"]["files"] + [{"path":"Uninstall.exe", "size":len(replacement["exe"]), "sha256":digest(replacement["exe"])}])
    (root / ".component-install.json").write_text(json.dumps(record), encoding="utf-8")
    if journal_phase == "committed":
        with pytest.raises(update.RuntimeUpdateError, match="rollback_current_installation_changed"):
            updater.rollback(result["rollback_target"]["target_digest"])
    else:
        journal = updater._journal()
        journal["phase"] = journal_phase
        updater._save(journal)
    error = "committed_installation_record_changed" if journal_phase == "committed" else "recovery_current_installation_changed"
    with pytest.raises(update.RuntimeUpdateError, match=error):
        updater.recover(result["target_digest"])
    assert updater._record()["version"] == "0.1.2"
    assert not update_pending_path(root).exists()


def test_stale_registry_record_refuses_recovery_before_creating_pending(installation, packages):
    root, updater, _ = installation
    marker = root / ".component-install.json"
    record = json.loads(marker.read_text(encoding="utf-8"))
    record["mode"] = "normal"
    marker.write_text(json.dumps(record), encoding="utf-8")
    registry = Registry()
    updater.registry = registry
    result = updater.apply(stage(updater, packages), health_check=lambda _: True)
    registry.version = "9.9.9"
    with pytest.raises(update.RuntimeUpdateError, match="committed_registry_version_changed"):
        updater.recover(result["target_digest"])
    with pytest.raises(update.RuntimeUpdateError, match="rollback_current_registry_changed"):
        updater.rollback(result["rollback_target"]["target_digest"])
    assert registry.version == "9.9.9"
    assert not update_pending_path(root).exists()


@pytest.mark.parametrize("body,declared,limit,error", [
    (b"0123456789", None, 5, "download_too_large"),
    (b"abc", "5", 5, "truncated_download"),
    (b"abc", "100", 5, "download_too_large"),
    (b"abc", "invalid", 5, "download_too_large"),
])
def test_builtin_transport_bounds_reads_without_network(monkeypatch, body, declared, limit, error):
    class Response:
        headers = {} if declared is None else {"Content-Length": declared}
        stream = io.BytesIO(body)
        def __enter__(self):return self
        def __exit__(self, *args):return False
        def read(self, size):return self.stream.read(size)
    class Opener:
        def open(self, request, timeout):
            assert timeout == 20
            assert request.get_header("Accept") == "application/vnd.github+json"
            assert request.get_header("Authorization") is None
            return Response()
    monkeypatch.setattr(update.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(update.RuntimeUpdateError, match=error):
        update.GithubTransport().fetch(update.RELEASES_URL, limit)


@pytest.mark.parametrize("url", ["http://github.com/file", "https://127.0.0.1/file", "https://evil.example/file",
                                "https://user:password@release-assets.githubusercontent.com/file"])
def test_builtin_transport_rejects_unsafe_redirect_before_following(url):
    request = update.urllib.request.Request(update._asset_url("0.1.1", "payload.zip"))
    with pytest.raises(update.RuntimeUpdateError, match="unsafe_download_redirect"):
        update._Redirects().redirect_request(request, None, 302, "redirect", {}, url)
