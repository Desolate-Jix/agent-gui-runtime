import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.runtime_lifecycle import (InstallationLease, InstallationMaintenance,
                                   RuntimeBusyError, update_pending_path)


def test_shared_readers_exclude_update_and_update_excludes_new_host(tmp_path):
    root = tmp_path / "installed"
    with InstallationLease(root), InstallationLease(root):
        with pytest.raises(RuntimeBusyError):
            with InstallationMaintenance(root):
                pytest.fail("maintenance acquired while runtime alive")
    with InstallationMaintenance(root):
        with pytest.raises(RuntimeBusyError):
            with InstallationLease(root):
                pytest.fail("runtime started during maintenance")
    with InstallationLease(root):
        pass


def test_crashed_update_requires_recovery_even_with_damaged_marker(tmp_path):
    root = tmp_path / "installed"
    update_pending_path(root).write_bytes(b"interrupted JSON")
    with pytest.raises(RuntimeBusyError, match="recovery_required"):
        with InstallationLease(root):
            pass
    with InstallationMaintenance(root):
        update_pending_path(root).unlink()
    with InstallationLease(root):
        pass


def test_process_exit_releases_lease_without_pid_expiry(tmp_path):
    root = tmp_path / "installed"
    code = ("from app.runtime_lifecycle import InstallationLease; import sys; "
            "lease=InstallationLease(sys.argv[1]).acquire(); print('held',flush=True); "
            "sys.stdin.readline()")
    process = subprocess.Popen([sys.executable, "-u", "-c", code, str(root)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                               cwd=Path(__file__).resolve().parents[1])
    try:
        assert process.stdout.readline().strip() == "held"
        with pytest.raises(RuntimeBusyError):
            with InstallationMaintenance(root):
                pass
        process.stdin.write("exit\n")
        process.stdin.flush()
        assert process.wait(timeout=10) == 0
        with InstallationMaintenance(root):
            pass
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()


def test_lock_is_stable_outside_replaced_installation(tmp_path):
    root = tmp_path / "installed"
    root.mkdir()
    with InstallationLease(root):
        root.rmdir()
        root.mkdir()
        with pytest.raises(RuntimeBusyError):
            with InstallationMaintenance(root):
                pass


@pytest.mark.skipif(os.name == "nt", reason="unprivileged Windows symlink unavailable")
def test_symlink_installation_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="reparse"):
        InstallationLease(alias)
