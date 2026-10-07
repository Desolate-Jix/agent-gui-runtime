import pytest

from app.learning_memory.measurement import load_events, record_event, summarize_run


def event(event_id, phase, start, end, *, status="success", usage=None, **extra):
    return {
        "schema": "workflow_measurement.v1", "event_id": event_id,
        "run_id": "run-1", "step_id": "step-1", "request_id": "request-1",
        "phase": phase, "source": "agent_current" if phase in {"planning", "grounding", "verification"} else "runtime",
        "started_ns": start, "ended_ns": end, "status": status,
        "usage": usage, "evidence_refs": [], **extra,
    }


def test_counts_all_model_roles_without_double_counting_nested_spans(tmp_path):
    rows = [
        event("plan", "planning", 0, 100, usage={"input_tokens": 8, "output_tokens": 2}),
        event("ground", "grounding", 20, 70, usage={"input_tokens": 5, "output_tokens": 1}),
        event("verify", "verification", 100, 140, usage={"input_tokens": 3, "output_tokens": 2}),
        event("ocr", "ocr", 30, 50),
    ]
    for row in rows:
        record_event(tmp_path, row)
    record_event(tmp_path, rows[0])
    saved = load_events(tmp_path, "run-1")
    assert len(saved) == 4
    assert (tmp_path / "measurements" / "run-1" / "events.jsonl").is_file()
    summary = summarize_run(saved)
    assert summary["model_calls"] == {"planning": 1, "grounding": 1, "verification": 1, "total": 3}
    assert summary["usage"] == {"input_tokens": 16, "output_tokens": 5, "total_tokens": 21}
    assert summary["elapsed_ns"] == 140
    assert summary["phase_elapsed_ns"]["ocr"] == 20


def test_missing_usage_stays_null_and_failed_attempts_remain(tmp_path):
    failed = event("attempt-1", "grounding", 0, 10, status="failure")
    retry = event("attempt-2", "grounding", 10, 30)
    record_event(tmp_path, failed)
    record_event(tmp_path, retry)
    summary = summarize_run([failed, retry])
    assert summary["model_calls"]["grounding"] == 2
    assert summary["status_counts"] == {"failure": 1, "success": 1}
    assert summary["usage"] is None
    with pytest.raises(ValueError, match="event_id"):
        record_event(tmp_path, dict(failed, ended_ns=11))


def test_rejects_invalid_identity_and_usage(tmp_path):
    with pytest.raises(ValueError):
        record_event(tmp_path, dict(event("bad", "planning", 0, 1), request_id=""))
    with pytest.raises(ValueError):
        summarize_run([event("bad", "planning", 2, 1)])
    with pytest.raises(ValueError):
        summarize_run([event("bad", "planning", 0, 1, usage={"input_tokens": 0})])


def test_learning_cold_start_wait_and_unclassified_time_are_separate():
    rows = [
        event("learn", "learning", 0, 10),
        event("cold", "cold_start", 10, 20),
        event("wait", "wait", 30, 50, status="waiting"),
        event("plan", "planning", 50, 60, usage=None),
    ]
    summary = summarize_run(rows)
    assert summary["phase_elapsed_ns"]["learning"] == 10
    assert summary["phase_elapsed_ns"]["cold_start"] == 10
    assert summary["phase_elapsed_ns"]["wait"] == 20
    assert summary["elapsed_ns"] == 50
    assert summary["wall_elapsed_ns"] == 60
    assert summary["unclassified_ns"] == 10
    assert summary["usage"] is None
