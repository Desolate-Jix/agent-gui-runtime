"""离线基准费用账本；只有新预留返回 True 才允许调用方发送一次 HTTP。"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re


MAX_TOKENS = 5_000_000
SCHEMA = "decision_benchmark_budget.v1"
HEAD_SCHEMA = "decision_benchmark_budget_head.v1"


class BudgetError(ValueError):
    pass


class BudgetExceeded(BudgetError):
    pass


class BudgetOverrun(BudgetExceeded):
    pass


class BudgetConflict(BudgetError):
    pass


class BudgetJournalError(BudgetError):
    pass


def _count(value):
    if type(value) is not int or value < 0:
        raise BudgetError("benchmark_budget_count_invalid")
    return value


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BudgetError("benchmark_budget_sha256_invalid")
    return value


def _request_id(value):
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise BudgetError("benchmark_budget_request_id_invalid")
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise BudgetJournalError("benchmark_budget_duplicate_json_key")
        value[key] = item
    return value


def _invalid_constant(value):
    raise BudgetJournalError("benchmark_budget_nonfinite_json")


def _json_line(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")


def _write_all(fd, value):
    while value:
        written = os.write(fd, value)
        if written <= 0:
            raise OSError("benchmark_budget_write_failed")
        value = value[written:]


class TokenBudget:
    """跨进程重读账本；未知预留不释放，重复操作不重新获得发送权。"""

    def __init__(self, path, limit=MAX_TOKENS):
        self._limit = _count(limit)
        if limit > MAX_TOKENS:
            raise BudgetError("benchmark_budget_limit_invalid")
        self.path = Path(path).resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_existed = self.lock_path.exists()
        with self._locked() as lock_fd:
            if not self.path.exists():
                if lock_existed:
                    raise BudgetJournalError("benchmark_budget_journal_missing")
                self._append({"schema": SCHEMA, "event": "init", "limit": limit}, lock_fd, create=True)
            self._read_state(lock_fd)

    @property
    def limit(self):
        return self._limit

    @contextmanager
    def _locked(self):
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
        fd = os.open(self.lock_path, flags, 0o600)
        acquired = False
        try:
            if os.fstat(fd).st_size == 0:
                _write_all(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            acquired = True
            yield fd
        finally:
            if acquired:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append(self, event, lock_fd, *, create=False):
        flags = os.O_WRONLY | getattr(os, "O_BINARY", 0) | (os.O_CREAT | os.O_EXCL if create else os.O_APPEND)
        fd = os.open(self.path, flags, 0o600)
        try:
            _write_all(fd, _json_line(event))
            os.fsync(fd)
        finally:
            os.close(fd)
        data = self.path.read_bytes()
        # 锁文件兼作持久头，完整行截断也不能被误认成合法旧前缀。
        head = _json_line({"schema": HEAD_SCHEMA, "bytes": len(data), "sha256": sha256(data).hexdigest()})
        os.lseek(lock_fd, 1, os.SEEK_SET)
        _write_all(lock_fd, head)
        os.ftruncate(lock_fd, 1 + len(head))
        os.fsync(lock_fd)

    def _read_state(self, lock_fd):
        try:
            data = self.path.read_bytes()
            os.lseek(lock_fd, 0, os.SEEK_SET)
            head_bytes = os.read(lock_fd, os.fstat(lock_fd).st_size)
            if not data or not data.endswith(b"\n") or head_bytes[:1] != b"\0" or not head_bytes.endswith(b"\n"):
                raise BudgetJournalError("benchmark_budget_journal_truncated")
            head = json.loads(head_bytes[1:].decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
            if (type(head) is not dict or set(head) != {"schema", "bytes", "sha256"} or head["schema"] != HEAD_SCHEMA
                    or type(head["bytes"]) is not int or head["bytes"] != len(data) or head["sha256"] != sha256(data).hexdigest()):
                raise BudgetJournalError("benchmark_budget_head_mismatch")
            events = [json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
                for line in data[:-1].split(b"\n")]
            initial = events[0]
            if (type(initial) is not dict or set(initial) != {"schema", "event", "limit"}
                    or initial["schema"] != SCHEMA or initial["event"] != "init"
                    or _count(initial["limit"]) > MAX_TOKENS):
                raise BudgetJournalError("benchmark_budget_init_invalid")
            state = {"limit": initial["limit"], "spent": 0, "reserved": 0, "halted": False, "requests": {}}
            for event in events[1:]:
                self._replay(state, event)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, BudgetJournalError):
                raise
            raise BudgetJournalError("benchmark_budget_journal_invalid") from None
        if state["limit"] != self.limit:
            raise BudgetConflict("benchmark_budget_limit_conflict")
        state["committed"] = state["spent"] + state["reserved"]
        state["remaining"] = max(0, state["limit"] - state["committed"])
        return state

    @staticmethod
    def _replay(state, event):
        if type(event) is not dict:
            raise BudgetJournalError("benchmark_budget_event_invalid")
        request_id = _request_id(event.get("request_id"))
        existing = state["requests"].get(request_id)
        if event.get("event") == "reserve" and set(event) == {"event", "request_id", "amount", "request_sha256"}:
            amount, request_hash = _count(event["amount"]), _hash(event["request_sha256"])
            if (existing is not None or state["halted"] or state["spent"] + state["reserved"] + amount > state["limit"]):
                raise BudgetJournalError("benchmark_budget_reservation_invalid")
            state["requests"][request_id] = {"amount": amount, "request_sha256": request_hash, "settlement": None}
            state["reserved"] += amount
        elif event.get("event") == "settle" and set(event) == {"event", "request_id", "input_tokens", "output_tokens", "response_sha256"}:
            total = _count(event["input_tokens"]) + _count(event["output_tokens"])
            _hash(event["response_sha256"])
            if existing is None or existing["settlement"] is not None:
                raise BudgetJournalError("benchmark_budget_settlement_invalid")
            existing["settlement"] = {key: event[key] for key in ("input_tokens", "output_tokens", "response_sha256")}
            state["spent"] += total
            state["reserved"] -= existing["amount"]
            state["halted"] = state["halted"] or total > existing["amount"]
        else:
            raise BudgetJournalError("benchmark_budget_event_invalid")

    def snapshot(self):
        with self._locked() as lock_fd:
            return deepcopy(self._read_state(lock_fd))

    def reserve(self, request_id, amount, request_sha256):
        request_id, amount, request_sha256 = _request_id(request_id), _count(amount), _hash(request_sha256)
        with self._locked() as lock_fd:
            state = self._read_state(lock_fd)
            existing = state["requests"].get(request_id)
            if existing is not None:
                if existing["amount"] != amount or existing["request_sha256"] != request_sha256:
                    raise BudgetConflict("benchmark_budget_request_conflict")
                return False
            if state["halted"] or state["committed"] + amount > self.limit:
                raise BudgetExceeded("benchmark_budget_exceeded")
            self._append({"event": "reserve", "request_id": request_id, "amount": amount,
                "request_sha256": request_sha256}, lock_fd)
            return True

    def settle(self, request_id, input_tokens, output_tokens, response_sha256):
        request_id = _request_id(request_id)
        input_tokens, output_tokens, response_sha256 = _count(input_tokens), _count(output_tokens), _hash(response_sha256)
        settlement = {"input_tokens": input_tokens, "output_tokens": output_tokens, "response_sha256": response_sha256}
        with self._locked() as lock_fd:
            state = self._read_state(lock_fd)
            existing = state["requests"].get(request_id)
            if existing is None:
                raise BudgetConflict("benchmark_budget_unreserved_request")
            fresh = existing["settlement"] is None
            if not fresh and existing["settlement"] != settlement:
                raise BudgetConflict("benchmark_budget_settlement_conflict")
            if fresh:
                self._append({"event": "settle", "request_id": request_id, **settlement}, lock_fd)
            if input_tokens + output_tokens > existing["amount"]:
                raise BudgetOverrun("benchmark_budget_actual_usage_exceeded_reservation")
            return fresh
