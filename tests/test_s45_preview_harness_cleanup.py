"""S45 现场 runner 清理顺序的隔离测试。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).parents[1] / ".superpowers/sdd/2026-09-10-graph-centered-formal-revision/s45_codex_fresh_preview.py"
    spec = importlib.util.spec_from_file_location("s45_preview_harness", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Connections:
    def __init__(self, events, fail=False): self.events, self.fail = events, fail
    def revoke_connection(self, connection_id, key):
        self.events.append("revoke")
        if self.fail: raise RuntimeError("revoke failed")
        return {"contract_version": "agent_link_v1", "connection_id": connection_id, "status": "revoked", "staging_only": True}


class _Host:
    def __init__(self, events, fail=False): self.connections = _Connections(events, fail); self.events = events
    def close(self): self.events.append("close")
    def status(self): return {"phase": "stopped"}


class _Coordinator:
    def __init__(self, events, fail=False): self.events, self.fail = events, fail
    def cancel(self):
        self.events.append("cancel")
        return {"phase": "idle", "cleanup_verified": True}
    def shutdown(self):
        self.events.append("shutdown")
        if self.fail: raise RuntimeError("shutdown failed")


def test_cleanup_preserves_primary_failure_and_revoke_precedes_shutdown():
    module = _module(); events = []; written = {}
    result = {"error_type": "RuntimeError", "error": "primary failure"}
    def write(name, value): written[name] = json.loads(json.dumps(value))
    module._cleanup_runtime(coordinator=_Coordinator(events), host=_Host(events), connection={"connection_id": "c1"}, result=result, write=write)
    assert result["error"] == "primary failure"
    assert events == ["cancel", "revoke", "shutdown", "close"]
    assert "result.json" in written and result["cleanup_verified"] is True


def test_cleanup_continues_after_failure_and_marks_unverified():
    module = _module(); events = []; written = {}
    result = {"error_type": "ValueError", "error": "primary failure"}
    def write(name, value): written[name] = json.loads(json.dumps(value))
    module._cleanup_runtime(coordinator=_Coordinator(events, fail=True), host=_Host(events, fail=True), connection={"connection_id": "c1"}, result=result, write=write)
    assert result["error"] == "primary failure"
    assert events == ["cancel", "revoke", "shutdown", "close"]
    assert result["cleanup_verified"] is False and len(result["cleanup_errors"]) == 2
    assert "result.json" in written


def test_cleanup_does_not_claim_cancelled_when_cancel_is_unverified():
    module = _module(); events = []; written = {}
    result = {}
    def write(name, value): written[name] = json.loads(json.dumps(value))
    class BadCancel(_Coordinator):
        def cancel(self):
            self.events.append("cancel")
            raise RuntimeError("cancel failed")
    module._cleanup_runtime(coordinator=BadCancel(events), host=_Host(events), connection={"connection_id": "c1"}, result=result, write=write)
    assert result["coordinator_cancelled"] is False
    assert result["cleanup_verified"] is False and "result.json" in written


def test_result_write_failure_cannot_leave_cleanup_verified():
    module = _module(); events = []
    result = {}
    def write(name, value): raise OSError("disk unavailable")
    module._cleanup_runtime(coordinator=_Coordinator(events), host=_Host(events), connection={"connection_id": "c1"}, result=result, write=write)
    assert result["cleanup_verified"] is False
    assert result["cleanup_errors"][-1]["step"] == "result_write"
