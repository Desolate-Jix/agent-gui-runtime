from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from .contracts import AgentLinkError, canonical_hash, validate_batch, validate_candidate, validate_scope
from .review_baseline import (
    candidate_content_sha256,
    hashes_equal,
    validate_candidate_changes,
    validate_review_baseline,
    validate_graph_review_baseline,
    validate_graph_candidate,
)
from .graph_contract import GraphContractError, validate_graph_scope
from .memory_scope import validate_stored_memory_scope

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _empty_state() -> dict[str, Any]:
    return {"store_version": "agent_link_store_v2", "connections": {}, "batches": {}, "feedback": {}, "candidates": {}, "idempotency": {}, "application_launches": {"requests": {}, "idempotency": {}}}


def _exact(value: Any, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys: raise ValueError
    return value


def _validate_state(value: Any) -> dict[str, Any]:
    # 旧收件箱没有启动请求容器；仅补齐该空容器，仍拒绝其他未知字段。
    if isinstance(value, dict) and set(value) == set(_empty_state()) - {"application_launches"}:
        value = {**value, "application_launches": {"requests": {}, "idempotency": {}}}
    state = _exact(value, set(_empty_state()))
    if state["store_version"] != "agent_link_store_v2" or any(not isinstance(state[key], dict) for key in _empty_state() if key != "store_version"): raise ValueError
    for connection_id, connection in state["connections"].items():
        connection_keys = {"connection_id", "task_id", "agent_name", "token_digest", "revoked", "created_at"}
        if isinstance(connection, dict) and "memory_scope" in connection:
            connection_keys.add("memory_scope")
        if isinstance(connection, dict) and "learning_segments" in connection:
            connection_keys.add("learning_segments")
        record = _exact(connection, connection_keys)
        if not all(isinstance(record[key], str) and record[key] for key in ("connection_id", "task_id", "agent_name", "token_digest")) or record["connection_id"] != connection_id or not _DIGEST.fullmatch(record["token_digest"]) or type(record["revoked"]) is not bool or type(record["created_at"]) is not int or record["created_at"] < 0: raise ValueError
        if "memory_scope" in record:
            validate_stored_memory_scope(record["memory_scope"])
        if "learning_segments" in record:
            from .learning_segments import validate_stored_learning_segments
            validate_stored_learning_segments(record["learning_segments"])
            for segment in record["learning_segments"].values():
                for observation in segment.get("observations", []):
                    source = observation["source"]
                    if source["connection_id"] != connection_id or source["task_id"] != record["task_id"]:
                        raise ValueError
    for batch_id, stored in state["batches"].items():
        if not isinstance(stored, dict): raise ValueError
        extra = {"fresh_learning_source"} if "fresh_learning_source" in stored else set()
        base = {key: copy.deepcopy(value) for key, value in stored.items() if key not in {"connection_id", "task_id", "status", "source"} | extra}
        if set(stored) != set(base) | {"connection_id", "task_id", "status", "source"} | extra: raise ValueError
        existing_png_sha256 = frozenset()
        if extra:
            from .fresh_source_contract import validate_fresh_source_metadata
            source = validate_fresh_source_metadata(stored["fresh_learning_source"])
            if source["connection_id"] != stored["connection_id"] or source["task_id"] != stored["task_id"]:
                raise ValueError
            segment = state["connections"].get(source["connection_id"], {}).get("learning_segments", {}).get(source["segment_id"], {})
            if {"batch_id": batch_id, "source": source} not in segment.get("observations", []):
                raise ValueError
            existing_png_sha256 = frozenset({source["reference"]["screenshot_sha256"]})
        for screenshot in base.get("screenshots", []):
            if not isinstance(screenshot, dict) or set(screenshot) != {"screenshot_id", "png_base64", "sha256", "width", "height"}: raise ValueError
            digest, width, height = screenshot.pop("sha256"), screenshot.pop("width"), screenshot.pop("height")
            if not _DIGEST.fullmatch(digest) or type(width) is not int or type(height) is not int: raise ValueError
            screenshot["_stored"] = (digest, width, height)
            screenshot.pop("_stored")
        batch = validate_batch(base, existing_png_sha256=existing_png_sha256)
        for original, checked in zip(stored["screenshots"], batch["screenshots"]):
            if original["sha256"] != checked["sha256"] or original["width"] != checked["width"] or original["height"] != checked["height"]: raise ValueError
        if batch["batch_id"] != batch_id or stored["connection_id"] not in state["connections"] or not isinstance(stored["task_id"], str) or stored["task_id"] != state["connections"][stored["connection_id"]]["task_id"] or stored["status"] != "pending_review_proposal" or stored["source"] != "untrusted_external": raise ValueError
    if set(state["feedback"]) != set(state["batches"]): raise ValueError
    for batch_id, feedback in state["feedback"].items():
        record = _exact(feedback, {"revision", "history", "issues"})
        if type(record["revision"]) is not int or record["revision"] < 0 or not isinstance(record["history"], list) or not isinstance(record["issues"], dict): raise ValueError
        if [entry.get("revision") if isinstance(entry, dict) else None for entry in record["history"]] != list(range(1, record["revision"] + 1)): raise ValueError
        historical_issue_ids: set[str] = set()
        for entry in record["history"]:
            _exact(entry, {"revision", "notes", "issue_ids"})
            if type(entry["revision"]) is not int or not isinstance(entry["notes"], list) or not isinstance(entry["issue_ids"], list) or len(set(entry["issue_ids"])) != len(entry["issue_ids"]): raise ValueError
            from .contracts import NoteInput, parse
            for note in entry["notes"]: parse(NoteInput, note, "stored note")
            if any(not isinstance(issue_id, str) or not issue_id for issue_id in entry["issue_ids"]): raise ValueError
            historical_issue_ids.update(entry["issue_ids"])
        for issue_id, issue in record["issues"].items():
            issue_keys = {"issue_id", "scope", "message", "status", "baseline_revision"}
            has_baseline = "review_baseline" in issue or "review_baseline_sha256" in issue
            if has_baseline:
                issue_keys |= {"review_baseline", "review_baseline_sha256"}
            _exact(issue, issue_keys)
            if issue["issue_id"] != issue_id or issue_id not in historical_issue_ids or issue["status"] not in {"open", "withdrawn"} or type(issue["baseline_revision"]) is not int or not 1 <= issue["baseline_revision"] <= record["revision"] or not isinstance(issue["message"], str) or not issue["message"]: raise ValueError
            effective_batch = state["batches"][batch_id]
            if has_baseline:
                if not isinstance(issue["review_baseline"], dict): raise ValueError
                if issue["review_baseline"].get("contract_version") == "desktop_graph_review_baseline_v1":
                    baseline, snapshot = validate_graph_review_baseline(
                        issue["review_baseline"], task_id=effective_batch["task_id"],
                        batch_id=batch_id, original_batch=effective_batch,
                    )
                    try: validate_graph_scope(issue["scope"], snapshot["graph"])
                    except GraphContractError as error: raise ValueError from error
                    effective_batch = None
                else:
                    baseline, effective_batch = validate_review_baseline(
                        issue["review_baseline"], task_id=effective_batch["task_id"],
                        original_batch=effective_batch,
                    )
                if not hashes_equal(issue["review_baseline_sha256"], canonical_hash(baseline)):
                    raise ValueError
            if effective_batch is not None: validate_scope(issue["scope"], effective_batch)
    launches = _exact(state["application_launches"], {"requests", "idempotency"})
    if not isinstance(launches["requests"], dict) or not isinstance(launches["idempotency"], dict): raise ValueError
    launch_ids: set[str] = set()
    for request_id, request in launches["requests"].items():
        if not isinstance(request, dict): raise ValueError
        base = {"request_id", "connection_id", "task_id", "app_id", "url", "created_at", "status"}
        optional = set()
        status = request.get("status")
        if status == "previewed": optional = {"preview", "preview_sha256", "previewed_at"}
        elif status == "dispatch_started": optional = {"preview", "preview_sha256", "previewed_at", "dispatch_started_at"}
        elif status in {"launched_window_ready", "launched_window_unavailable"}: optional = {"preview", "preview_sha256", "previewed_at", "dispatch_started_at", "outcome", "completed_at"}
        if set(request) != base | optional or request_id != request.get("request_id") or not all(isinstance(request.get(key), str) and request[key] for key in ("request_id", "connection_id", "task_id", "app_id")) or request["connection_id"] not in state["connections"] or state["connections"][request["connection_id"]]["task_id"] != request["task_id"] or request["url"] is not None and (not isinstance(request["url"], str) or not request["url"] or len(request["url"]) > 4096 or any(ord(char) < 32 for char in request["url"])) or type(request["created_at"]) is not int or request["created_at"] < 0 or status not in {"pending_human_confirmation", "previewed", "dispatch_started", "launched_window_ready", "launched_window_unavailable"}: raise ValueError
        if request_id in launch_ids: raise ValueError
        launch_ids.add(request_id)
        if optional:
            preview = request["preview"]
            if not isinstance(preview, dict) or set(preview) != {"contract_version", "preparation_id", "mode", "identity", "source", "app_id", "name", "url", "command", "executable_path", "catalog_entry_sha256", "executable_sha256", "expires_in_seconds"} or preview.get("contract_version") != "native_window_preparation_v1" or preview.get("mode") != "launch" or preview.get("identity") is not None or preview.get("source") != "app_catalog" or preview.get("app_id") != request["app_id"] or preview.get("url") != request["url"] or not all(isinstance(preview.get(key), str) and preview[key] for key in ("preparation_id", "name", "executable_path")) or not isinstance(preview.get("command"), list) or not 1 <= len(preview["command"]) <= 32 or any(not isinstance(item, str) or not item or len(item) > 4096 for item in preview["command"]) or preview["command"][0] != preview["executable_path"] or not isinstance(preview.get("catalog_entry_sha256"), str) or not _DIGEST.fullmatch(preview["catalog_entry_sha256"]) or not isinstance(preview.get("executable_sha256"), str) or not _DIGEST.fullmatch(preview["executable_sha256"]) or type(preview.get("expires_in_seconds")) is not int or not 1 <= preview["expires_in_seconds"] <= 3600 or not _DIGEST.fullmatch(request["preview_sha256"]) or request["preview_sha256"] != canonical_hash(preview) or type(request["previewed_at"]) is not int or request["previewed_at"] < 0: raise ValueError
        if status in {"dispatch_started", "launched_window_ready", "launched_window_unavailable"} and (type(request["dispatch_started_at"]) is not int or request["dispatch_started_at"] < request["previewed_at"]): raise ValueError
        if status in {"launched_window_ready", "launched_window_unavailable"}:
            outcome = request["outcome"]
            if type(request["completed_at"]) is not int or request["completed_at"] < request["dispatch_started_at"] or not isinstance(outcome, dict) or outcome.get("status") != status: raise ValueError
            if status == "launched_window_ready":
                if set(outcome) != {"status", "process_id", "window"} or type(outcome.get("process_id")) is not int or outcome["process_id"] <= 0 or not isinstance(outcome.get("window"), dict) or set(outcome["window"]) != {"handle", "process_id", "title"} or type(outcome["window"].get("handle")) is not int or outcome["window"]["handle"] <= 0 or type(outcome["window"].get("process_id")) is not int or outcome["window"]["process_id"] <= 0 or not isinstance(outcome["window"].get("title"), str): raise ValueError
            elif set(outcome) != {"status", "process_id", "window", "reason", "result_unknown", "launch_effect_undone"} or outcome["window"] is not None or outcome["process_id"] is not None and (type(outcome["process_id"]) is not int or outcome["process_id"] <= 0) or not isinstance(outcome["reason"], str) or not outcome["reason"] or outcome["result_unknown"] is not True or outcome["launch_effect_undone"] is not False: raise ValueError
    for ledger_key, item in launches["idempotency"].items():
        if not isinstance(ledger_key, str) or not ledger_key or not isinstance(item, dict) or set(item) != {"request_hash", "request_id"} or not _DIGEST.fullmatch(item["request_hash"]) or item["request_id"] not in launches["requests"]: raise ValueError
        request = launches["requests"][item["request_id"]]
        if not ledger_key.startswith(request["connection_id"] + ":"): raise ValueError

    for candidate_id, stored in state["candidates"].items():
        if not isinstance(stored, dict): raise ValueError
        base = {key: value for key, value in stored.items() if key not in {"candidate_id", "connection_id", "status", "candidate_sha256"}}
        expected_stored_keys = set(base) | {"candidate_id", "connection_id", "status"}
        if "candidate_sha256" in stored: expected_stored_keys.add("candidate_sha256")
        if set(stored) != expected_stored_keys: raise ValueError
        candidate = validate_candidate(base)
        if candidate_id != stored["candidate_id"] or stored["connection_id"] not in state["connections"] or candidate["batch_id"] not in state["batches"] or stored["status"] not in {"pending_review_proposal", "stale", "withdrawn"}: raise ValueError
        batch = state["batches"][candidate["batch_id"]]
        feedback = state["feedback"][candidate["batch_id"]]
        issue = feedback["issues"].get(candidate["issue_id"])
        if batch["connection_id"] != stored["connection_id"] or issue is None or candidate["baseline_revision"] != issue["baseline_revision"] or candidate["baseline_revision"] < 1 or candidate["baseline_revision"] > feedback["revision"]: raise ValueError
        effective_batch = batch
        if "review_baseline" in issue:
            if "review_baseline_sha256" not in candidate or "candidate_sha256" not in stored:
                raise ValueError
            if not hashes_equal(candidate["review_baseline_sha256"], issue["review_baseline_sha256"]):
                raise ValueError
            if issue["review_baseline"].get("contract_version") == "desktop_graph_review_baseline_v1":
                if candidate.get("contract_version") != "agent_link_graph_candidate_v1": raise ValueError
                _, snapshot = validate_graph_review_baseline(
                    issue["review_baseline"], task_id=batch["task_id"], batch_id=candidate["batch_id"], original_batch=batch
                )
                if candidate.get("logical_workflow_id") != snapshot["logical_workflow_id"] or not hashes_equal(candidate.get("baseline_graph_sha256"), snapshot["content_sha256"]): raise ValueError
                validate_graph_candidate(candidate, snapshot, issue)
                effective_batch = None
            else:
                if candidate.get("contract_version") != "agent_link_v1": raise ValueError
                _, effective_batch = validate_review_baseline(
                    issue["review_baseline"], task_id=batch["task_id"], original_batch=batch
                )
            if not hashes_equal(stored["candidate_sha256"], candidate_content_sha256(stored)):
                raise ValueError
        elif "review_baseline_sha256" in candidate or "candidate_sha256" in stored:
            raise ValueError
        if effective_batch is not None:
            scope = validate_scope(candidate["scope"], effective_batch)
            if scope != issue["scope"]: raise ValueError
        if stored["status"] == "pending_review_proposal" and (issue["status"] != "open" or candidate["baseline_revision"] != feedback["revision"]): raise ValueError
        if stored["status"] == "stale" and (issue["status"] != "open" or candidate["baseline_revision"] == feedback["revision"]): raise ValueError
        if stored["status"] == "withdrawn" and issue["status"] != "withdrawn": raise ValueError
        if effective_batch is not None:
            validate_candidate_changes(candidate, effective_batch, scope, reject_duplicate_fields="review_baseline" in issue)
    receipt_shapes = {
        "submit_batch": ({"contract_version", "batch_id", "status", "learning_outcome", "incomplete", "staging_only"}, "pending_review_proposal"),
        "submit_candidate": ({"contract_version", "candidate_id", "batch_id", "issue_id", "status", "staging_only"}, "pending_review_proposal"),
        "record_feedback": ({"contract_version", "batch_id", "revision", "status", "staging_only"}, "feedback_recorded"),
        "withdraw_issue": ({"contract_version", "batch_id", "issue_id", "revision", "status", "staging_only"}, "issue_withdrawn"),
        "revoke_connection": ({"contract_version", "connection_id", "status", "staging_only"}, "revoked"),
        "set_workflow_memory_scope": ({"contract_version", "connection_id", "revision", "status", "staging_only"}, "memory_scope_updated"),
    }
    for ledger_key, item in state["idempotency"].items():
        record = _exact(item, {"request_hash", "receipt"})
        parts = ledger_key.split(":", 2)
        if len(parts) != 3 or not _DIGEST.fullmatch(record["request_hash"]) or parts[1] not in receipt_shapes: raise ValueError
        keys, status = receipt_shapes[parts[1]]; receipt = _exact(record["receipt"], keys)
        if receipt["contract_version"] != "agent_link_v1" or receipt["status"] != status or receipt["staging_only"] is not True: raise ValueError
        if parts[1] == "submit_batch" and (receipt["learning_outcome"] not in {"completed", "partial", "failed", "safety_stop"} or type(receipt["incomplete"]) is not bool or receipt["incomplete"] != (receipt["learning_outcome"] != "completed")): raise ValueError
        if parts[0] != "reviewer" and (parts[0] not in state["connections"] or parts[1] not in {"submit_batch", "submit_candidate"}): raise ValueError
        if parts[1] == "submit_batch" and receipt["batch_id"] not in state["batches"]: raise ValueError
        if parts[1] == "submit_candidate" and (receipt["candidate_id"] not in state["candidates"] or state["candidates"][receipt["candidate_id"]]["batch_id"] != receipt["batch_id"] or state["candidates"][receipt["candidate_id"]]["issue_id"] != receipt["issue_id"]): raise ValueError
        if parts[1] in {"record_feedback", "withdraw_issue"} and (receipt["batch_id"] not in state["batches"] or type(receipt["revision"]) is not int or receipt["revision"] < 1 or receipt["revision"] > state["feedback"][receipt["batch_id"]]["revision"]): raise ValueError
        if parts[1] == "withdraw_issue" and receipt["issue_id"] not in state["feedback"][receipt["batch_id"]]["issues"]: raise ValueError
        if parts[1] == "revoke_connection" and (receipt["connection_id"] not in state["connections"] or state["connections"][receipt["connection_id"]]["revoked"] is not True): raise ValueError
        if parts[1] == "set_workflow_memory_scope":
            connection = state["connections"].get(receipt["connection_id"])
            if connection is None or "memory_scope" not in connection or type(receipt["revision"]) is not int or not 1 <= receipt["revision"] <= connection["memory_scope"]["revision"]:
                raise ValueError
    return state


class AgentLinkStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if str(path) == ":memory:": raise AgentLinkError("invalid_store", "an explicit persistent inbox path is required")
        self._guard = threading.RLock()
        self._closed = False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._lock_handle = self._lock_path.open("a+b")
        self._acquire_owner_lock()
        try: self._state = self._read_state()
        except Exception:
            self.close(); raise

    def _acquire_owner_lock(self) -> None:
        try:
            self._lock_handle.seek(0, os.SEEK_END)
            if self._lock_handle.tell() == 0: self._lock_handle.write(b"0"); self._lock_handle.flush()
            self._lock_handle.seek(0)
            try:
                import msvcrt; msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            except ImportError:
                import fcntl; fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error: raise AgentLinkError("store_in_use", "another owner already holds this inbox") from error

    def _read_state(self) -> dict[str, Any]:
        if not self._path.exists(): return _empty_state()
        try: data = json.loads(self._path.read_text(encoding="utf-8")); return _validate_state(data)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, AgentLinkError) as error: raise AgentLinkError("corrupt_store", "inbox state is corrupt and was not reset") from error

    def read(self, action: Callable[[dict[str, Any]], Any]) -> Any:
        with self._guard:
            if self._closed: raise AgentLinkError("store_closed", "inbox store is closed")
            return copy.deepcopy(action(self._state))

    def snapshot(self) -> dict[str, Any]: return self.read(lambda state: state)

    def mutate(self, change: Callable[[dict[str, Any]], Any]) -> Any:
        with self._guard:
            if self._closed: raise AgentLinkError("store_closed", "inbox store is closed")
            next_state = copy.deepcopy(self._state)
            result = change(next_state)
            self._write_state(next_state)
            self._state = next_state
            return copy.deepcopy(result)

    def _write_state(self, state: dict[str, Any]) -> None:
        descriptor, name = tempfile.mkstemp(prefix=self._path.name + ".", suffix=".tmp", dir=self._path.parent); temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        except OSError as error: raise AgentLinkError("persistence_failed", "inbox update was not persisted") from error
        finally:
            if temporary.exists(): temporary.unlink(missing_ok=True)

    def close(self) -> None:
        with self._guard:
            if self._closed: return
            self._closed = True
            try:
                self._lock_handle.seek(0)
                try:
                    import msvcrt; msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
                except ImportError:
                    import fcntl; fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            except OSError: pass
            finally: self._lock_handle.close()
