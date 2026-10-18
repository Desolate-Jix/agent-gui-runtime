"""原命令队列的跨进程入队契约。"""

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from threading import Event

import pytest

from app.core.json_snapshot import read_json_snapshot
from app.core.instant_command_queue import CommandQueueBusy, command_queue_lock, enqueue_command


def _child_enqueue(session, entered, release, output):
    from app.core import instant_command_queue as queue

    original = queue.write_json_snapshot

    def paused_write(path, value):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test_writer_release_timeout")
        return original(path, value)

    queue.write_json_snapshot = paused_write
    try:
        output.put(("ok", queue.enqueue_command(session, "first", {"kind": "read_text"})))
    except Exception as error:
        output.put(("error", type(error).__name__, str(error)))


def test_same_id_is_idempotent_and_conflict_is_rejected(tmp_path):
    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    command = {"kind": "read_text", "request": {"goal": "本轮测试"}}
    assert enqueue_command(session, "original-1", command) is True
    assert enqueue_command(session, "original-1", command) is False
    with pytest.raises(ValueError, match="command_queue_request_conflict"):
        enqueue_command(session, "original-1", {"kind": "read_text", "request": {"goal": "different"}})
    assert read_json_snapshot(session / "commands" / "original-1.json") == command


@pytest.mark.parametrize("bad_id", ["", "Upper", "a/b", "a\\b", "../escape", "a" * 81])
def test_rejects_unsafe_request_ids_before_writing(tmp_path, bad_id):
    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    with pytest.raises(ValueError, match="request_id"):
        enqueue_command(session, bad_id, {"kind": "read_text"})
    assert list((session / "commands").glob("*.json")) == []


def test_pending_and_closing_never_write_new_command(tmp_path):
    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    assert enqueue_command(session, "pending-1", {"kind": "read_text"})
    with pytest.raises(CommandQueueBusy) as error:
        enqueue_command(session, "second", {"kind": "read_text"})
    assert error.value.pending_ids == ["pending-1"]
    assert not (session / "commands" / "second.json").exists()
    assert enqueue_command(session, "second", {"kind": "read_text"}, ignore_request_ids=("pending-1",))
    (session / "closing.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="command_queue_closing"):
        enqueue_command(session, "third", {"kind": "read_text"}, ignore_request_ids=("pending-1", "second"))
    assert not (session / "commands" / "third.json").exists()


def test_thread_contender_cannot_pass_check_while_writer_holds_lock(tmp_path, monkeypatch):
    from app.core import instant_command_queue as queue

    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    entered, release = Event(), Event()
    original = queue.write_json_snapshot

    def paused_write(path, value):
        entered.set()
        assert release.wait(5)
        return original(path, value)

    monkeypatch.setattr(queue, "write_json_snapshot", paused_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(enqueue_command, session, "first", {"kind": "read_text"})
        assert entered.wait(5)
        with pytest.raises(CommandQueueBusy):
            enqueue_command(session, "second", {"kind": "read_text"})
        release.set()
        assert first.result(timeout=5) is True
    assert [path.stem for path in (session / "commands").glob("*.json")] == ["first"]


def test_public_queue_lock_excludes_enqueue(tmp_path):
    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    with command_queue_lock(session):
        with pytest.raises(CommandQueueBusy) as error:
            enqueue_command(session, "first", {"kind": "read_text"})
        assert error.value.pending_ids == []
    assert enqueue_command(session, "first", {"kind": "read_text"}) is True


def test_process_contender_cannot_pass_check_while_writer_holds_lock(tmp_path):
    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)
    ctx = get_context("spawn")
    entered, release, output = ctx.Event(), ctx.Event(), ctx.Queue()
    child = ctx.Process(target=_child_enqueue, args=(session, entered, release, output))
    child.start()
    try:
        assert entered.wait(10)
        with pytest.raises(CommandQueueBusy):
            enqueue_command(session, "second", {"kind": "read_text"})
        release.set()
        assert output.get(timeout=10) == ("ok", True)
        child.join(timeout=10)
        assert child.exitcode == 0
    finally:
        release.set()
        child.join(timeout=10)
    assert [path.stem for path in (session / "commands").glob("*.json")] == ["first"]


def test_writer_exception_is_not_relabelled_as_queue_busy(tmp_path, monkeypatch):
    from app.core import instant_command_queue as queue

    session = tmp_path / "session"
    (session / "commands").mkdir(parents=True)

    def fail_write(path, value):
        raise OSError("disk-write-failed")

    monkeypatch.setattr(queue, "write_json_snapshot", fail_write)
    with pytest.raises(OSError, match="disk-write-failed"):
        enqueue_command(session, "first", {"kind": "read_text"})
    assert not (session / "commands" / "first.json").exists()
