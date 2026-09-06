"""选择审核候选件的串行化原语。"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
from threading import RLock
import time
from typing import Iterator
from uuid import uuid4


_PROCESS_LOCKS: dict[str, RLock] = {}
_PROCESS_LOCKS_GUARD = RLock()
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_RETRY_DELAY_SECONDS = 0.01
_WINDOWS_LOCK_VIOLATION = 33


def _process_lock(directory: Path) -> RLock:
    """返回目录对应的进程内可重入锁。"""
    key = str(directory.resolve()).casefold()
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, RLock())


@contextmanager
def selection_save_lock(directory: Path) -> Iterator[None]:
    """在一次保存期间持有候选件的进程内和跨进程锁。"""
    directory.mkdir(parents=True, exist_ok=True)
    process_lock = _process_lock(directory)
    with process_lock:
        lock_path = directory / ".selection-review-save.lock"
        if not lock_path.exists() or lock_path.stat().st_size == 0:
            with lock_path.open("ab") as initializer:
                initializer.write(b"0")
        with lock_path.open("a+b") as handle:
            _lock_file(handle)
            try:
                yield
            finally:
                _unlock_file(handle)


def atomic_write_text(path: Path, text: str) -> None:
    """原子发布完整候选件，避免读到部分写入的 head。"""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _lock_file(handle: object) -> None:
    """在有限时间内获取文件锁，只重试已知的锁竞争错误。"""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                handle.seek(0)  # type: ignore[attr-defined]
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                return
            except OSError as error:
                _retry_or_raise_lock_error(error, deadline)
    else:
        import fcntl

        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
                return
            except OSError as error:
                _retry_or_raise_lock_error(error, deadline)


def _unlock_file(handle: object) -> None:
    """释放已获取的文件锁。"""
    if os.name == "nt":
        import msvcrt

        handle.seek(0)  # type: ignore[attr-defined]
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _retry_or_raise_lock_error(error: OSError, deadline: float) -> None:
    """仅把操作系统报告的锁竞争作为可重试条件。"""
    if not _is_lock_contention(error):
        raise OSError("selection save lock acquisition failed") from error
    if time.monotonic() >= deadline:
        raise TimeoutError("selection save lock timed out after 10 seconds") from error
    time.sleep(min(_LOCK_RETRY_DELAY_SECONDS, max(0.0, deadline - time.monotonic())))


def _is_lock_contention(error: OSError) -> bool:
    """判断错误是否为已知的跨进程锁竞争。"""
    if os.name == "nt":
        return (
            getattr(error, "winerror", None) == _WINDOWS_LOCK_VIOLATION
            or error.errno in {errno.EACCES, errno.EAGAIN}
        )
    return error.errno in {errno.EACCES, errno.EAGAIN}
