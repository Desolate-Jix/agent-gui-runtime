"""离线费用账本：先落盘、未知保留、重开不重派及跨进程互斥。"""
from contextlib import contextmanager
from hashlib import sha256
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def module():
    return importlib.import_module("scripts.decision_benchmark_budget")


def digest(value):
    return sha256(value.encode("utf-8")).hexdigest()


def test_reserve_settle_and_resume_are_durable_and_idempotent(tmp_path, monkeypatch):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    fsyncs = []
    original = api.os.fsync
    def synced(fd):
        fsyncs.append(fd)
        return original(fd)
    monkeypatch.setattr(api.os, "fsync", synced)
    assert budget.reserve("\u8bf7\u6c42-1", 80, digest("request")) is True
    assert fsyncs and "\u8bf7\u6c42-1" in path.read_text(encoding="utf-8")
    reserved = path.read_bytes()
    fsyncs.clear()
    assert api.TokenBudget(path, limit=100).reserve("\u8bf7\u6c42-1", 80, digest("request")) is False
    assert path.read_bytes() == reserved and not fsyncs
    assert budget.settle("\u8bf7\u6c42-1", 20, 5, digest("response")) is True
    assert fsyncs
    settled = path.read_bytes()
    fsyncs.clear()
    assert budget.settle("\u8bf7\u6c42-1", 20, 5, digest("response")) is False
    assert path.read_bytes() == settled and not fsyncs
    state = api.TokenBudget(path, limit=100).snapshot()
    assert (state["spent"], state["reserved"], state["committed"], state["remaining"], state["halted"]) == (25, 0, 25, 75, False)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 3


def test_unknown_call_keeps_full_reservation_and_cannot_be_retried(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    assert budget.reserve("unknown", 80, digest("request"))
    reopened = api.TokenBudget(path, limit=100)
    assert reopened.reserve("unknown", 80, digest("request")) is False
    assert reopened.snapshot()["reserved"] == 80
    before = path.read_bytes()
    with pytest.raises(api.BudgetExceeded):
        reopened.reserve("new", 21, digest("new"))
    assert path.read_bytes() == before


def test_existing_instances_reload_other_instances_spending(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    first, second = api.TokenBudget(path, limit=100), api.TokenBudget(path, limit=100)
    assert first.reserve("one", 80, digest("one"))
    with pytest.raises(api.BudgetExceeded):
        second.reserve("two", 30, digest("two"))
    first.settle("one", 10, 5, digest("response"))
    assert second.reserve("two", 30, digest("two"))
    assert first.snapshot()["committed"] == 45


def test_limit_is_fixed_on_resume_and_never_above_five_million(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path)
    assert budget.limit == 5_000_000
    before = path.read_bytes()
    with pytest.raises(api.BudgetConflict):
        api.TokenBudget(path, limit=4_000_000)
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        api.TokenBudget(tmp_path / "too-large.jsonl", limit=5_000_001)


@pytest.mark.parametrize("bad", [True, False, -1, 1.5, "1", None])
def test_counts_are_nonnegative_integers_and_reject_bool(tmp_path, bad):
    api = module()
    with pytest.raises(ValueError):
        api.TokenBudget(tmp_path / "invalid-limit.jsonl", limit=bad)
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    with pytest.raises(ValueError):
        budget.reserve("invalid", bad, digest("request"))
    budget.reserve("valid", 50, digest("request"))
    before = path.read_bytes()
    for input_tokens, output_tokens in ((bad, 1), (1, bad)):
        with pytest.raises(ValueError):
            budget.settle("valid", input_tokens, output_tokens, digest("response"))
    assert path.read_bytes() == before


@pytest.mark.parametrize("request_id,request_hash", [("", "a" * 64), (True, "a" * 64),
    ("request", "a" * 63), ("request", "z" * 64), ("request", True)])
def test_invalid_request_binding_never_appends(tmp_path, request_id, request_hash):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        budget.reserve(request_id, 1, request_hash)
    assert path.read_bytes() == before


def test_same_id_changed_amount_request_hash_or_settlement_is_conflict(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    budget.reserve("one", 50, digest("request"))
    for amount, request_hash in ((51, digest("request")), (50, digest("different"))):
        with pytest.raises(api.BudgetConflict):
            budget.reserve("one", amount, request_hash)
    with pytest.raises(api.BudgetConflict):
        budget.settle("unreserved", 1, 2, digest("response"))
    budget.settle("one", 10, 5, digest("response"))
    before = path.read_bytes()
    for first, second, response_hash in ((11, 5, digest("response")), (10, 6, digest("response")), (10, 5, digest("different"))):
        with pytest.raises(api.BudgetConflict):
            budget.settle("one", first, second, response_hash)
    assert path.read_bytes() == before


@pytest.mark.parametrize("actual", [40, 101])
def test_overrun_is_fsynced_as_fact_and_halts_new_calls(tmp_path, actual):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    budget.reserve("overrun", 30, digest("request"))
    budget.reserve("already-in-flight", 10, digest("other"))
    with pytest.raises(api.BudgetOverrun):
        budget.settle("overrun", actual, 0, digest("response"))
    state = api.TokenBudget(path, limit=100).snapshot()
    assert state["spent"] == actual and state["halted"] is True and state["reserved"] == 10
    before = path.read_bytes()
    with pytest.raises(api.BudgetOverrun):
        budget.settle("overrun", actual, 0, digest("response"))
    assert path.read_bytes() == before
    with pytest.raises(api.BudgetExceeded):
        budget.reserve("new", 0, digest("new"))
    assert budget.settle("already-in-flight", 5, 0, digest("other-response"))


@pytest.mark.parametrize("corruption", [b"", b'{"event":', b'\xff\n', b'{}\n',
    b'{"event":"init","event":"init"}\n', b'\n'])
def test_truncated_or_illegal_journal_fails_closed_without_repair(tmp_path, corruption):
    api = module()
    path = tmp_path / "budget.jsonl"
    path.write_bytes(corruption)
    with pytest.raises(api.BudgetJournalError):
        api.TokenBudget(path)
    assert path.read_bytes() == corruption


def test_partial_tail_or_illegal_event_after_valid_data_fails_closed(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    budget.reserve("one", 10, digest("one"))
    original = path.read_bytes()
    for tail in (b'{"event":"settle"}', b'{"event":"settle"}\n', b'{"event":"other"}\n'):
        path.write_bytes(original + tail)
        before = path.read_bytes()
        with pytest.raises(api.BudgetJournalError):
            budget.reserve("two", 10, digest("two"))
        assert path.read_bytes() == before


def test_complete_line_tail_truncation_is_detected_by_persistent_head(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    budget.reserve("sent", 80, digest("sent"))
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
    with pytest.raises(api.BudgetJournalError):
        api.TokenBudget(path, limit=100)


def test_missing_journal_with_retained_head_cannot_reset_the_budget(tmp_path):
    api = module()
    budget = api.TokenBudget(tmp_path / "original.jsonl", limit=100)
    budget.reserve("sent", 80, digest("sent"))
    missing = tmp_path / "missing.jsonl"
    missing.with_name(missing.name + ".lock").write_bytes(budget.lock_path.read_bytes())
    with pytest.raises(api.BudgetJournalError):
        api.TokenBudget(missing, limit=100)
    assert not missing.exists()


def test_valid_head_does_not_make_illegal_events_acceptable(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    original = path.read_bytes()
    events = [{"event": "reserve", "request_id": "bad", "amount": True, "request_sha256": digest("bad")},
        {"event": "reserve", "request_id": "bad", "amount": 101, "request_sha256": digest("bad")},
        {"event": "settle", "request_id": "unreserved", "input_tokens": 1, "output_tokens": 2, "response_sha256": digest("bad")},
        {"event": "init", "schema": api.SCHEMA, "limit": 100}]
    for event in events:
        data = original + (json.dumps(event) + "\n").encode("utf-8")
        path.write_bytes(data)
        budget.lock_path.write_bytes(b"\0" + (json.dumps({"schema": api.HEAD_SCHEMA,
            "bytes": len(data), "sha256": sha256(data).hexdigest()}) + "\n").encode("utf-8"))
        with pytest.raises(api.BudgetJournalError):
            budget.snapshot()


def test_failed_event_fsync_does_not_return_permission_to_send(tmp_path, monkeypatch):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    def failed_sync(fd):
        raise OSError("offline fsync failure")
    monkeypatch.setattr(api.os, "fsync", failed_sync)
    with pytest.raises(OSError, match="fsync failure"):
        budget.reserve("not-authorized", 80, digest("request"))
    with pytest.raises(api.BudgetJournalError):
        budget.snapshot()


WORKER = """
import json,sys
from scripts.decision_benchmark_budget import TokenBudget, BudgetExceeded
print('ready',flush=True)
sys.stdin.readline()
try:
    result=TokenBudget(sys.argv[1],limit=100).reserve(sys.argv[2],60,'a'*64)
    print(json.dumps({'reserved':result}),flush=True)
except BudgetExceeded:
    print(json.dumps({'exceeded':True}),flush=True)
"""


def test_two_processes_cannot_reserve_more_than_cap(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    api.TokenBudget(path, limit=100)
    workers = [subprocess.Popen([sys.executable, "-c", WORKER, str(path), f"p{i}"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8") for i in range(2)]
    for worker in workers:
        assert worker.stdout.readline().strip() == "ready"
    for worker in workers:
        worker.stdin.write("go\n")
        worker.stdin.flush()
    outcomes = []
    for worker in workers:
        output, error = worker.communicate(timeout=15)
        assert worker.returncode == 0, error
        outcomes.append(json.loads(output))
    assert sorted(outcomes, key=str) == sorted([{"reserved": True}, {"exceeded": True}], key=str)
    assert api.TokenBudget(path, limit=100).snapshot()["committed"] == 60


@contextmanager
def native_lock(path):
    with path.open("r+b") as stream:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def test_external_process_must_wait_for_existing_native_file_lock(tmp_path):
    api = module()
    path = tmp_path / "budget.jsonl"
    budget = api.TokenBudget(path, limit=100)
    worker = None
    with native_lock(budget.lock_path):
        worker = subprocess.Popen([sys.executable, "-c", WORKER, str(path), "locked"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        assert worker.stdout.readline().strip() == "ready"
        worker.stdin.write("go\n")
        worker.stdin.flush()
        with pytest.raises(subprocess.TimeoutExpired):
            worker.communicate(timeout=.2)
    output, error = worker.communicate(timeout=15)
    assert worker.returncode == 0, error
    assert json.loads(output) == {"reserved": True}
