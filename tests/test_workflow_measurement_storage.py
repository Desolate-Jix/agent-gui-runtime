"""同一会话多个计量 run 的隔离与旧日志只读兼容。"""

import json

import pytest

from app.learning_memory.measurement import load_events, record_event, summarize_run
from tests.test_workflow_measurement import event


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_multiple_runs_have_independent_logs_and_summaries(tmp_path):
    first = dict(event("a", "grounding", 0, 10), run_id="r1")
    second = dict(event("a", "verification", 5, 20), run_id="trial-" + "a" * 64)
    record_event(tmp_path, first)
    record_event(tmp_path, second)
    record_event(tmp_path, first)
    assert load_events(tmp_path, "r1") == [first]
    assert load_events(tmp_path, second["run_id"]) == [second]
    assert summarize_run(load_events(tmp_path, "r1"))["model_calls"]["grounding"] == 1
    assert summarize_run(load_events(tmp_path, second["run_id"]))["model_calls"]["verification"] == 1
    assert _rows(tmp_path / "measurements" / "r1" / "events.jsonl") == [first]
    assert _rows(tmp_path / "measurements" / second["run_id"] / "events.jsonl") == [second]
    assert not (tmp_path / "measurement.jsonl").exists()
    with pytest.raises(ValueError, match="event_id"):
        record_event(tmp_path, dict(first, ended_ns=11))


def test_legacy_log_is_read_only_and_deduplicates_new_events(tmp_path):
    legacy = dict(event("legacy", "grounding", 0, 10), run_id="r1")
    path = tmp_path / "measurement.jsonl"
    original = json.dumps(legacy, ensure_ascii=False) + "\n"
    path.write_text(original, encoding="utf-8")
    assert load_events(tmp_path, "r1") == [legacy]
    assert load_events(tmp_path, "r2") == []
    record_event(tmp_path, legacy)
    assert not (tmp_path / "measurements").exists()
    with pytest.raises(ValueError, match="event_id"):
        record_event(tmp_path, dict(legacy, ended_ns=12))
    fresh = dict(event("new", "verification", 10, 20), run_id="r1")
    other = dict(event("other", "planning", 0, 1), run_id="r2")
    record_event(tmp_path, fresh)
    record_event(tmp_path, other)
    assert load_events(tmp_path, "r1") == [legacy, fresh]
    assert load_events(tmp_path, "r2") == [other]
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("run_id", ["", ".", "..", "../outside", "a/b", "a\\b", "C:foo",
                                    "CON", "con", "prn", "aux", "nul", "com1", "lpt9", "r1.",
                                    "r 1", "a" * 161])
def test_invalid_run_id_never_writes(tmp_path, run_id):
    with pytest.raises(ValueError, match="run_id"):
        record_event(tmp_path, dict(event("bad", "planning", 0, 1), run_id=run_id))
    with pytest.raises(ValueError, match="run_id"):
        load_events(tmp_path, run_id)
    assert not (tmp_path / "measurements").exists()


def test_mismatched_run_in_new_file_is_rejected(tmp_path):
    folder = tmp_path / "measurements" / "r1"
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_text(json.dumps(dict(event("bad", "planning", 0, 1), run_id="r2")) + "\n",
                                       encoding="utf-8")
    with pytest.raises(ValueError, match="run_id"):
        load_events(tmp_path, "r1")
    with pytest.raises(ValueError, match="run_id"):
        record_event(tmp_path, dict(event("new", "planning", 2, 3), run_id="r1"))


def test_existing_run_directory_symlink_cannot_escape_session(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "session"
    (root / "measurements").mkdir(parents=True)
    try:
        (root / "measurements" / "r1").symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("directory symlink is unavailable")
    with pytest.raises(ValueError, match="measurement_path_outside_session"):
        record_event(root, dict(event("new", "planning", 0, 1), run_id="r1"))
    assert not (outside / "events.jsonl").exists()
