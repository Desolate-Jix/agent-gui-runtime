"""短时读占用不能丢失最终回执；重试范围仅为文件发布。"""
from concurrent.futures import ThreadPoolExecutor
import time
import pytest
from app.core.json_snapshot import read_json_snapshot, write_json_snapshot


def test_reader_does_not_block_atomic_publication(tmp_path):
    path = tmp_path / "report.json"
    write_json_snapshot(path, {"version": 1})
    with ThreadPoolExecutor() as pool:
        with path.open("rb") as reader:
            future = pool.submit(write_json_snapshot, path, {"version": 2})
            time.sleep(.06)
            assert b'"version": 1' in reader.read()
        future.result(timeout=2)
    assert read_json_snapshot(path) == {"version": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_unrelated_write_failure_is_not_retried(tmp_path, monkeypatch):
    from pathlib import Path
    calls = []
    def fail(self, target):
        calls.append(1)
        raise OSError("disk failure")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        write_json_snapshot(tmp_path / "report.json", {"version": 1})
    assert len(calls) == 1
