import pytest

from app.learning_memory import workflow_metrics
from app.learning_memory.workflow_metrics import (
    load_run_metrics, record_api_attempt, record_rule_observation,
)


def envelope(request_id="verify-1", *, start=10, end=20):
    return {
        "measurement": {"started_ns": start, "ended_ns": end},
        "receipt": {"run_id": "run-1", "step_id": "step-1", "request_id": request_id,
                    "execution_request_id": "execute-1", "evidence_ref": "responses/execute-1.json"},
        "observation": {"evidence_ref": f"workflow-observations/{request_id}.json"},
    }


def test_three_native_rules_are_observed_but_total_model_calls_unknown(tmp_path):
    for number, verdict in enumerate(("success", "failure", "uncertain"), 1):
        record_rule_observation(tmp_path, envelope(f"verify-{number}", start=number * 10,
                                                  end=number * 10 + 5), verdict)
    result = load_run_metrics(tmp_path, "run-1")
    assert result["observed"]["event_count"] == 3
    assert result["observed"]["model_calls"]["total"] == 0
    assert result["observed"]["status_counts"] == {"success": 1, "failure": 1, "waiting": 1}
    assert result["observed"]["phase_elapsed_ns"]["verification"] == 15
    assert result["total_model_calls"] is None
    assert result["total_usage"] is None
    assert result["coverage"] == {"planning": "unobserved", "grounding": "partial",
                                  "verification": "partial", "overall": "partial"}
    assert (tmp_path / "measurements" / "run-1" / "events.jsonl").is_file()


def test_api_and_rule_events_are_idempotent_with_unknown_usage(tmp_path):
    attempt = {"started_ns": 1, "ended_ns": 10, "status": "timeout", "usage": None}
    arguments = {"run_id": "run-1", "step_id": "step-1", "execution_request_id": "execute-1",
                 "grounding_request_id": "ground-1", "attempt": attempt}
    record_api_attempt(tmp_path, **arguments)
    record_api_attempt(tmp_path, **arguments)
    record_rule_observation(tmp_path, envelope(), "success")
    record_rule_observation(tmp_path, envelope(), "success")
    result = load_run_metrics(tmp_path, "run-1")
    assert result["observed"]["event_count"] == 2
    assert result["observed"]["model_calls"]["grounding"] == 1
    assert result["observed"]["usage"] is None
    assert result["observed"]["status_counts"] == {"timeout": 1, "success": 1}
    with pytest.raises(ValueError, match="event_id"):
        record_api_attempt(tmp_path, **{**arguments, "attempt": {**attempt, "ended_ns": 11}})


def test_old_envelope_without_measurement_is_skipped(tmp_path):
    old = envelope()
    old.pop("measurement")
    record_rule_observation(tmp_path, old, "success")
    assert load_run_metrics(tmp_path, "run-1")["observed"]["event_count"] == 0
    assert not (tmp_path / "measurements").exists()


@pytest.mark.parametrize("change", [
    {"measurement": {"started_ns": True, "ended_ns": 2}},
    {"measurement": {"started_ns": 3, "ended_ns": 2}},
    {"receipt": {"run_id": "../escape", "step_id": "step-1", "request_id": "verify-1",
                 "execution_request_id": "execute-1", "evidence_ref": "responses/execute-1.json"}},
    {"receipt": {"run_id": "run-1", "step_id": "step-1", "request_id": "verify-1",
                 "execution_request_id": "execute-1", "evidence_ref": "../escape.json"}},
    {"observation": {"evidence_ref": "C:/escape.json"}},
])
def test_rule_rejects_invalid_measurement_or_reference(tmp_path, change):
    value = envelope()
    value.update(change)
    with pytest.raises(ValueError):
        record_rule_observation(tmp_path, value, "success")


def test_rule_rejects_unknown_verdict(tmp_path):
    with pytest.raises(ValueError):
        record_rule_observation(tmp_path, envelope(), "completed")
    with pytest.raises(ValueError):
        record_rule_observation(tmp_path, envelope(), {})


def test_rule_rejects_changed_duplicate_payload(tmp_path):
    record_rule_observation(tmp_path, envelope(), "success")
    with pytest.raises(ValueError, match="event_id"):
        record_rule_observation(tmp_path, envelope(end=21), "success")


@pytest.mark.parametrize("change", [
    {"grounding_request_id": "../escape"},
    {"execution_request_id": "../escape"},
    {"attempt": {"started_ns": 1, "ended_ns": 2, "status": "pending", "usage": None}},
    {"attempt": {"started_ns": 1, "ended_ns": 2, "status": "success", "usage": {"input_tokens": 1}}},
    {"attempt": {"started_ns": 1, "ended_ns": 2, "status": [], "usage": None}},
    {"attempt": {"started_ns": 1, "ended_ns": 2, "status": "success", "usage": None, "extra": 1}},
])
def test_api_rejects_invalid_fields_and_paths(tmp_path, change):
    fields = {"run_id": "run-1", "step_id": "step-1", "execution_request_id": "execute-1",
              "grounding_request_id": "ground-1", "attempt": {"started_ns": 1, "ended_ns": 2,
                                                         "status": "success", "usage": None}}
    fields.update(change)
    with pytest.raises(ValueError):
        record_api_attempt(tmp_path, **fields)


def test_api_records_actual_usage_without_claiming_full_coverage(tmp_path):
    record_api_attempt(tmp_path, run_id="run-1", step_id="step-1", execution_request_id="execute-1",
                       grounding_request_id="ground-1", attempt={"started_ns": 0, "ended_ns": 8,
                       "status": "success", "usage": {"input_tokens": 3, "output_tokens": 2}})
    value = load_run_metrics(tmp_path, "run-1")
    assert value["observed"]["usage"]["total_tokens"] == 5
    assert value["total_usage"] is None
    assert value["total_model_calls"] is None


def test_corrupt_log_is_unavailable_without_rewriting_and_can_recover(tmp_path):
    record_rule_observation(tmp_path, envelope(), "success")
    path = tmp_path / "measurements" / "run-1" / "events.jsonl"
    original = path.read_bytes()
    corrupt = original + b"{broken-json\n"
    path.write_bytes(corrupt)
    unavailable = load_run_metrics(tmp_path, "run-1")
    assert unavailable == {
        "status": "unavailable", "observed": None,
        "coverage": {"planning": "unobserved", "grounding": "partial",
                     "verification": "partial", "overall": "partial"},
        "total_model_calls": None, "total_usage": None,
        "error": {"code": "measurement_log_invalid", "type": "JSONDecodeError"},
    }
    assert path.read_bytes() == corrupt
    path.write_bytes(original)
    assert load_run_metrics(tmp_path, "run-1")["observed"]["event_count"] == 1


def test_invalid_run_id_is_rejected_before_log_read(tmp_path):
    with pytest.raises(ValueError, match="measurement_run_id_invalid"):
        load_run_metrics(tmp_path, "../escape")


def test_io_failure_is_unavailable_but_programming_failure_propagates(tmp_path, monkeypatch):
    def fail_io(*_):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(workflow_metrics, "load_events", fail_io)
    value = load_run_metrics(tmp_path, "run-1")
    assert value["observed"] is None
    assert value["error"] == {"code": "measurement_log_io_error", "type": "OSError"}

    def fail_bug(*_):
        raise RuntimeError("synthetic programming failure")
    monkeypatch.setattr(workflow_metrics, "load_events", fail_bug)
    with pytest.raises(RuntimeError, match="synthetic programming failure"):
        load_run_metrics(tmp_path, "run-1")
