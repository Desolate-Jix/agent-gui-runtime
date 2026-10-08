"""执行计时不能把交接、查询或嵌套区间误报为纯推理耗时。"""
from copy import deepcopy

import pytest

from app.execution.timeline import summarize_execution_timeline


def span(start, end, layer, kind="span", **extra):
    return {"started_ns": start, "ended_ns": end, "layer": layer, "kind": kind, **extra}


def test_handoff_is_not_pure_inference():
    events = [span(0, 48_164_387_000, "unknown", "action"),
              span(0, 40_701_318_500, "vision", "handoff"),
              span(40_701_318_500, 43_400_318_500, "decision")]
    original = deepcopy(events)
    result = summarize_execution_timeline(events)
    assert result["action_total_ms"] == 48164.387
    assert result["layers_ms"]["handoff"] == 40701.3185
    assert result["handoff_is_pure_inference"] is False
    assert "vision" not in result["layers_ms"]
    assert result["unknown_ms"] == pytest.approx(4764.0685)
    assert events == original


def test_query_receipt_is_not_action_duration():
    result = summarize_execution_timeline([span(100, 200, "input", "query")])
    assert result["action_total_ms"] is None
    assert result["measured_span_union_ms"] is None
    assert result["query_included_in_action_duration"] is False


def test_nested_decision_times_are_not_added():
    result = summarize_execution_timeline([
        span(0, 2_699_000_000, "unknown", "action"),
        span(0, 2_699_000_000, "decision"),
        span(200_000_000, 1_836_000_000, "decision"),
        span(500_000_000, 1_184_000_000, "decision")])
    assert result["action_total_ms"] == 2699
    assert result["layers_ms"] == {"decision": 2699}
    assert result["measured_span_union_ms"] == 2699
    assert result["overlap_ms"] == 0


def test_missing_timestamps_stay_unknown():
    result = summarize_execution_timeline([{"layer": "vision", "duration_ms": 200}])
    assert result["status"] == "partial"
    assert result["action_total_ms"] is None
    assert result["unknown_events"] == [{"event_index": 0, "reason": "missing_timestamps"}]


def test_overlapping_layers_are_reported_without_double_count():
    result = summarize_execution_timeline([
        span(0, 100_000_000, "unknown", "action"),
        span(0, 70_000_000, "uia"), span(30_000_000, 100_000_000, "capture")])
    assert result["layers_ms"] == {"capture": 30, "uia": 30}
    assert result["overlap_ms"] == 40
    assert result["measured_span_union_ms"] == 100
    assert result["status"] == "partial"


def test_incomparable_clock_does_not_fill_unknown_time():
    result = summarize_execution_timeline([
        span(0, 100_000_000, "unknown", "action", clock_id="host"),
        span(0, 100_000_000, "vision", clock_id="remote")])
    assert result["unknown_ms"] == 100
    assert result["layers_ms"] == {}
    assert result["unknown_events"] == [{"event_index": 1, "reason": "incomparable_clock"}]
