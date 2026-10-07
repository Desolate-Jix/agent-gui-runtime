"""同一 Instant 会话内的跨进程原命令入队门闩。"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
from threading import Lock

from .json_snapshot import read_json_snapshot, write_json_snapshot


_REQUEST_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")
_LOCKS_GUARD = Lock()
_THREAD_LOCKS = {}


class CommandQueueBusy(ValueError):
    """当前不能确定安全入队；本次调用没有写入新命令。"""

    def __init__(self, pending_ids=()):
        self.pending_ids = list(pending_ids)
        super().__init__("command_queue_busy")


def _request_id(value):
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        raise ValueError("request_id must be 1-80 lowercase ASCII letters/digits/dashes/underscores")
    return value


@contextmanager
def command_queue_lock(session_dir):
    """供同一会话的入队与取消票据处置共享的短锁。"""

    session = Path(session_dir).resolve()
    path = session / "command-queue.lock"
    with _LOCKS_GUARD:
        thread_lock = _THREAD_LOCKS.setdefault(path, Lock())
    if not thread_lock.acquire(blocking=False):
        raise CommandQueueBusy()
    try:
        with path.open("a+b") as stream:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise CommandQueueBusy() from error
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise CommandQueueBusy() from error
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        thread_lock.release()


def enqueue_command(session_dir, request_id, command, *, ignore_request_ids=()) -> bool:
    """锁内检查并持久化原命令；仅同 ID 同内容允许幂等返回。"""

    request_id = _request_id(request_id)
    ignored = {_request_id(value) for value in ignore_request_ids}
    session = Path(session_dir).resolve()
    commands = session / "commands"
    if not commands.is_dir():
        raise FileNotFoundError("command_queue_directory_missing")
    path = commands / (request_id + ".json")
    with command_queue_lock(session):
        if path.exists():
            if read_json_snapshot(path) != command:
                raise ValueError("command_queue_request_conflict")
            return False
        if (session / "closing.json").exists():
            raise ValueError("command_queue_closing")
        pending = sorted(p.stem for p in commands.glob("*.json")
                         if p.stem not in ignored and not (session / "responses" / p.name).is_file())
        if pending:
            raise CommandQueueBusy(pending)
        write_json_snapshot(path, command)
        return True


__all__ = ["CommandQueueBusy", "command_queue_lock", "enqueue_command"]
