"""重复读取仍核验完整目录边界，但不放大文件系统元数据访问。"""
import os
import stat
from types import SimpleNamespace

import pytest

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore


def _store(root):
    receipts = RuntimeReceiptStore(project_root=root)
    return RuntimeIntentClaimStore(project_root=root, receipt_store=receipts)


def test_one_claim_path_has_bounded_real_metadata_probes(tmp_path, monkeypatch):
    store = _store(tmp_path)
    calls = []
    actual_stat, actual_lstat = os.stat, os.lstat
    def tracked_stat(*args, **kwargs):
        calls.append(("stat", args[0]))
        return actual_stat(*args, **kwargs)
    def tracked_lstat(*args, **kwargs):
        calls.append(("lstat", args[0]))
        return actual_lstat(*args, **kwargs)
    monkeypatch.setattr(os, "stat", tracked_stat)
    monkeypatch.setattr(os, "lstat", tracked_lstat)
    path = store._claim_path("a" * 64)
    assert path == store.claims_root / ("a" * 64 + ".json")
    assert len(calls) <= 48, f"one filename caused {len(calls)} metadata probes"


def test_readonly_missing_phase_is_not_recreated(tmp_path):
    store = _store(tmp_path)
    store.terminal_root.rmdir()
    with pytest.raises(RuntimeIntentClaimStoreError):
        RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=store._receipt_store, create_layout=False)
    assert not store.terminal_root.exists()


def test_unrelated_phase_replacement_is_checked_on_every_path_read(tmp_path):
    store = _store(tmp_path)
    store._claim_path("a" * 64)
    store.terminal_root.rmdir()
    store.terminal_root.write_bytes(b"not a directory")
    with pytest.raises(RuntimeIntentClaimStoreError):
        store._claim_path("b" * 64)
    assert store.terminal_root.read_bytes() == b"not a directory"


def test_windows_reparse_flag_on_other_phase_is_not_cached(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store._claim_path("a" * 64)
    actual_lstat = os.lstat
    def reparse_lstat(path, *args, **kwargs):
        result = actual_lstat(path, *args, **kwargs)
        if os.fspath(path) == os.fspath(store.terminal_root):
            return SimpleNamespace(st_mode=result.st_mode,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return result
    monkeypatch.setattr(os, "lstat", reparse_lstat)
    with pytest.raises(RuntimeIntentClaimStoreError):
        store._claim_path("b" * 64)


def test_layout_rejects_phase_outside_fixed_store_tree(tmp_path):
    store = _store(tmp_path)
    outside_store = tmp_path / "not-a-store-phase"
    outside_store.mkdir()
    store.terminal_root = outside_store
    with pytest.raises(RuntimeIntentClaimStoreError):
        store._claim_path("a" * 64)
    assert list(outside_store.iterdir()) == []


def test_missing_writable_phase_is_created_without_changing_existing_evidence(tmp_path):
    store = _store(tmp_path)
    retained = store.claims_root / ("c" * 64 + ".json")
    retained.write_bytes(b"retained evidence")
    before = retained.stat().st_mtime_ns
    store.terminal_root.rmdir()
    store._claim_path("a" * 64)
    assert store.terminal_root.is_dir()
    assert retained.read_bytes() == b"retained evidence"
    assert retained.stat().st_mtime_ns == before
