"""保存学习工作流对照试验的证据事件。"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from pathlib import Path


SCHEMA = "workflow_measurement.v1"
PHASES = frozenset({"planning", "grounding", "verification", "ocr", "matching", "input", "wait", "learning", "cold_start"})
STATUSES = frozenset({"success", "failure", "timeout", "cancelled", "pending", "waiting"})
MODEL_SOURCES = frozenset({"local", "agent_current", "agent_delegate", "external_api"})
MODEL_PHASES = frozenset({"planning", "grounding", "verification"})
_LOCK = threading.RLock()
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,159}\Z")
_WINDOWS_RESERVED = frozenset({"con", "prn", "aux", "nul"} |
                              {f"com{index}" for index in range(1, 10)} |
                              {f"lpt{index}" for index in range(1, 10)})


def _run_id(value):
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None or value in _WINDOWS_RESERVED:
        raise ValueError("measurement_run_id_invalid")
    return value


def _run_path(session_dir, run_id):
    session = Path(session_dir).resolve()
    directory = session / "measurements" / _run_id(run_id)
    path = directory / "events.jsonl"
    # 名称校验之外，还拒绝既有目录或日志链接跳出本会话。
    if (directory.parent.resolve() != directory.parent or directory.resolve() != directory
            or path.resolve() != path):
        raise ValueError("measurement_path_outside_session")
    return path


def _read_log(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _validate(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("measurement event must be an object")
    required = {"schema", "event_id", "run_id", "step_id", "request_id", "phase", "source", "started_ns", "ended_ns", "status", "usage", "evidence_refs"}
    if set(event) - (required | {"parent_event_id"}):
        raise ValueError("measurement event contains unknown fields")
    if required - set(event):
        raise ValueError("measurement event is missing required fields")
    if event["schema"] != SCHEMA:
        raise ValueError("unsupported measurement schema")
    for key in ("event_id", "run_id", "step_id", "request_id", "source"):
        if not isinstance(event[key], str) or not event[key].strip():
            raise ValueError(f"{key} must be a non-empty string")
    if "parent_event_id" in event and (not isinstance(event["parent_event_id"], str) or not event["parent_event_id"].strip()):
        raise ValueError("parent_event_id must be a non-empty string")
    if event["phase"] not in PHASES or event["status"] not in STATUSES:
        raise ValueError("invalid measurement phase or status")
    start, end = event["started_ns"], event["ended_ns"]
    if type(start) is not int or type(end) is not int or start < 0 or end < start:
        raise ValueError("invalid measurement interval")
    refs = event["evidence_refs"]
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise ValueError("evidence_refs must be a list of non-empty strings")
    usage = event["usage"]
    if usage is not None:
        if not isinstance(usage, dict) or not {"input_tokens", "output_tokens"} <= usage.keys() or set(usage) - {"input_tokens", "output_tokens", "total_tokens"}:
            raise ValueError("usage requires actual input_tokens and output_tokens")
        if any(type(value) is not int or value < 0 for value in usage.values()):
            raise ValueError("usage token counts must be non-negative integers")
        if "total_tokens" in usage and usage["total_tokens"] < usage["input_tokens"] + usage["output_tokens"]:
            raise ValueError("total_tokens cannot be less than component counts")
    return event


def _deduplicate(events: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    run_id = None
    for candidate in events:
        event = _validate(candidate)
        if run_id is None:
            run_id = event["run_id"]
        elif run_id != event["run_id"]:
            raise ValueError("events from different run_id values cannot be summarized together")
        prior = unique.get(event["event_id"])
        if prior is not None and prior != event:
            raise ValueError("event_id was reused with a changed payload")
        unique[event["event_id"]] = event
    return list(unique.values())


def load_events(session_dir: Path, run_id: str) -> list[dict]:
    """读取单个 run；旧单文件只读参与去重，绝不迁写。"""
    _run_id(run_id)
    with _LOCK:
        session = Path(session_dir).resolve()
        legacy_path = session / "measurement.jsonl"
        if legacy_path.resolve() != legacy_path:
            raise ValueError("measurement_path_outside_session")
        legacy = _deduplicate(_read_log(legacy_path))
        if legacy and legacy[0]["run_id"] != run_id:
            legacy = []
        current = _read_log(_run_path(session, run_id))
        if any(_validate(row)["run_id"] != run_id for row in current):
            raise ValueError("measurement_run_id_mismatch")
        return _deduplicate(legacy + current)


def record_event(session_dir: Path, event: dict) -> None:
    """只追加一次不可变事件；相同事件重放保持幂等。"""
    _validate(event)
    _run_id(event["run_id"])
    path = _run_path(session_dir, event["run_id"])
    with _LOCK:
        seen = {row["event_id"]: row for row in load_events(session_dir, event["run_id"])}
        prior = seen.get(event["event_id"])
        if prior is not None:
            if prior != event:
                raise ValueError("event_id was reused with a changed payload")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _run_path(session_dir, event["run_id"])
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()


def _union_duration(events: list[dict]) -> int:
    intervals = sorted((event["started_ns"], event["ended_ns"]) for event in events)
    if not intervals:
        return 0
    total = 0
    left, right = intervals[0]
    for start, end in intervals[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right - left
            left, right = start, end
    return total + right - left


def summarize_run(events: list[dict]) -> dict:
    """汇总已观测时段；未知模型用量保持空值。"""
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    rows = _deduplicate(events)
    calls = {phase: 0 for phase in ("planning", "grounding", "verification")}
    model_rows = []
    for row in rows:
        if row["phase"] in MODEL_PHASES and row["source"] in MODEL_SOURCES:
            calls[row["phase"]] += 1
            model_rows.append(row)
    calls["total"] = sum(calls.values())
    usage = None
    if model_rows and all(row["usage"] is not None for row in model_rows):
        usage = {
            "input_tokens": sum(row["usage"]["input_tokens"] for row in model_rows),
            "output_tokens": sum(row["usage"]["output_tokens"] for row in model_rows),
            "total_tokens": sum(row["usage"].get("total_tokens", row["usage"]["input_tokens"] + row["usage"]["output_tokens"]) for row in model_rows),
        }
    return {
        "run_id": rows[0]["run_id"] if rows else None,
        "event_count": len(rows),
        "model_calls": calls,
        "usage": usage,
        "usage_observed_calls": sum(row["usage"] is not None for row in model_rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "elapsed_ns": _union_duration(rows),
        "wall_elapsed_ns": max(row["ended_ns"] for row in rows) - min(row["started_ns"] for row in rows) if rows else 0,
        "unclassified_ns": (max(row["ended_ns"] for row in rows) - min(row["started_ns"] for row in rows) - _union_duration(rows)) if rows else 0,
        "phase_elapsed_ns": {phase: _union_duration([row for row in rows if row["phase"] == phase]) for phase in PHASES},
    }
