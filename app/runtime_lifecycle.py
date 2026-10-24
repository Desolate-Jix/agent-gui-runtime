"""Installation-wide reader/writer lease shared by launchers and maintenance.

The lock is a stable sibling of the installation, so neither replacing payload
files nor uninstalling the payload changes the lock's identity.  Kernel locks
are released by process exit, never by deleting a PID file or guessing a timeout.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


class RuntimeBusyError(RuntimeError):
    """An installation is running, under maintenance, or requires recovery."""


def _canonical(root):
    supplied = Path(root).absolute()
    _no_reparse(supplied)
    result = supplied.resolve()
    if result == result.parent:
        raise ValueError("installation_root_required")
    return result


def _no_reparse(path):
    for item in (Path(path), *Path(path).parents):
        try:
            facts = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(facts.st_mode) or getattr(facts, "st_file_attributes", 0) & 0x400:
            raise ValueError("installation_reparse_point_rejected")


def maintenance_lock_path(root):
    root = _canonical(root)
    return root.parent / ("." + root.name + ".runtime-maintenance.lock")


def update_pending_path(root):
    root = _canonical(root)
    return root.parent / ("." + root.name + ".runtime-update-pending.json")


def update_state_path(root):
    root = _canonical(root)
    return root.parent / ("." + root.name + ".runtime-updates")


class _InstallationLock:
    exclusive = False

    def __init__(self, root):
        self._stream = None
        self._overlapped = None
        self.root = _canonical(root)

    def acquire(self):
        if self._stream is not None:
            return self
        path = maintenance_lock_path(self.root)
        _no_reparse(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+b")
        try:
            # LockFileEx can lock beyond EOF; no write is required after locking.
            if os.name == "nt":
                import ctypes
                from ctypes import wintypes
                import msvcrt

                class OVERLAPPED(ctypes.Structure):
                    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                                ("hEvent", wintypes.HANDLE)]

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                lock = kernel.LockFileEx
                lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
                lock.restype = wintypes.BOOL
                overlap = OVERLAPPED()
                if not lock(msvcrt.get_osfhandle(stream.fileno()), 1 | (2 if self.exclusive else 0),
                            0, 1, 0, ctypes.byref(overlap)):
                    raise OSError(ctypes.get_last_error(), "installation lock unavailable")
                self._overlapped = overlap
            else:
                import fcntl
                fcntl.flock(stream, (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            self._stream = stream
            if not self.exclusive:
                pending = update_pending_path(self.root)
                _no_reparse(pending)
                if pending.exists():
                    raise RuntimeBusyError("runtime_update_recovery_required")
            return self
        except BaseException as error:
            self._stream = None
            stream.close()
            if isinstance(error, OSError):
                raise RuntimeBusyError("runtime_running_or_under_maintenance") from error
            raise

    def close(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            # Closing the exact kernel handle releases its range lock.
            stream.close()
        self._overlapped = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        self.close()


class InstallationLease(_InstallationLock):
    """Held for the lifetime of a runtime parent or host process."""


class InstallationMaintenance(_InstallationLock):
    """Exclusive, nonblocking maintenance. Does not cancel or kill a task."""
    exclusive = True
