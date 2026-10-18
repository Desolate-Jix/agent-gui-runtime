"""观察保存计时只记录静态阶段和耗时，不改变返回值或泄露学习内容。"""
import json
import logging

import pytest

from app.desktop_review import observation_timing as timing


def _records(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == timing.LOGGER_NAME]


def test_nested_span_records_elapsed_and_parent_without_payload(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger=timing.LOGGER_NAME)
    stamps = iter([10, 20, 50, 90])
    monkeypatch.setattr(timing, "perf_counter_ns", lambda: next(stamps))
    secret = object()
    with timing.observation_span("stage"):
        assert timing.timed_call("stage.archive", lambda: secret) is secret
    child, parent = _records(caplog)
    assert child["parent_started_ns"] == parent["started_ns"] == 10
    assert child["elapsed_ms"] == 30 / 1_000_000
    assert parent["elapsed_ms"] == 80 / 1_000_000
    assert all(r["outcome"] == "ok" for r in (child, parent))
    assert parent["parent_started_ns"] is None
    assert set(parent) == {"contract_version", "span", "started_ns", "finished_ns", "elapsed_ms",
                           "parent_started_ns", "thread_id", "outcome"}


def test_exception_identity_and_scope_restored_without_logging_error_text(caplog):
    caplog.set_level(logging.INFO, logger=timing.LOGGER_NAME)
    error = ValueError("private-window-title-and-token")
    @timing.timed_observation("stage")
    def fail(secret):
        raise error
    with pytest.raises(ValueError) as caught:
        fail("private-goal")
    assert caught.value is error
    with timing.observation_span("stage.archive"):
        pass
    failed, next_span = _records(caplog)
    assert failed["outcome"] == "error" and next_span["parent_started_ns"] is None
    assert "private" not in caplog.text


def test_real_stage_sync_and_import_emit_spans_without_changing_results(tmp_path, caplog):
    from tests.test_formal_fresh_graph_source import _stage
    caplog.set_level(logging.INFO, logger=timing.LOGGER_NAME)
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    try:
        again = host.fresh_learning.stage(**args)
        assert again == staged
        synced = host.fresh_learning.sync_actions(**{k: args[k] for k in ("connection_id", "task_id", "segment_id")})
        assert synced["action_executed"] is False
        imported = host.facade.import_interface_content(connection["task_id"], staged["batch_id"], "observed-screen")
        assert host.facade.import_interface_content(connection["task_id"], staged["batch_id"], "observed-screen") == imported
        spans = {r["span"] for r in _records(caplog)}
        assert {"stage", "stage.archive", "stage.validate_batch", "stage.store_commit",
                "stage.ensure_graph", "sync_actions", "sync_actions.collect", "sync_actions.ensure_graph",
                "interface_import", "interface_import.lock_held"} <= spans
        assert all(r["elapsed_ms"] >= 0 for r in _records(caplog))
        assert args["meaning"] not in caplog.text and connection["token"] not in caplog.text
    finally:
        host.close()
