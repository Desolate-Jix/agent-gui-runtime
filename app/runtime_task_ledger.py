"""Durable installation-wide registrations; process death never settles input.

Callers register under an installation lease before starting a host. Maintenance
holds the exclusive installation lock while asserting/clearing settled entries.
The index covers registrations made by this version, not untracked legacy hosts.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
from uuid import uuid4


SCHEMA = "runtime_task_ledger.v1"
_FIELDS = {"schema", "installation_root", "session_path", "registrant"}


class RuntimeTaskLedgerError(ValueError):
    """Evidence is missing, changed, corrupt, or not settled."""


def _require(value, code):
    if not value:
        raise RuntimeTaskLedgerError("runtime_task_ledger_" + code)


def _no_reparse(path):
    for item in (path, *path.parents):
        try:
            facts = item.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(facts.st_mode)
                 and not getattr(facts, "st_file_attributes", 0) & 0x400, "reparse_rejected")


def _canonical(path):
    _require(isinstance(path, (str, os.PathLike)), "path_invalid")
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts, "absolute_path_required")
    _no_reparse(path)
    result = path.resolve()
    _require(result != result.parent, "root_path_rejected")
    return result


def registry_directory(root):
    root = _canonical(root)
    result = root.parent / ("." + root.name + ".runtime-sessions")
    _no_reparse(result)
    return result


def _session(path):
    result = _canonical(path)
    _require(not result.exists() or result.is_dir(), "session_path_invalid")
    return result


def _entry(root, session):
    key = hashlib.sha256(os.path.normcase(str(session)).encode("utf-8")).hexdigest()
    return registry_directory(root) / (key + ".json")


def _read(path):
    _no_reparse(path)
    _require(path.is_file() and path.stat().st_size <= 1024 * 1024, "snapshot_invalid")
    raw = path.read_bytes()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(RuntimeTaskLedgerError("runtime_task_ledger_json_invalid")))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeTaskLedgerError("runtime_task_ledger_snapshot_invalid") from error
    _require(isinstance(value, dict), "snapshot_invalid")
    return value, raw


def _current_identity():
    import psutil
    created = psutil.Process(os.getpid()).create_time()
    _require(type(created) in (int, float) and math.isfinite(created) and created > 0,
             "registrant_identity_invalid")
    return {"pid": os.getpid(), "created": created}


def _registration(root, session, registrant):
    return {"schema": SCHEMA, "installation_root": str(root), "session_path": str(session),
            "registrant": registrant}


def _registered(root, path):
    value, raw = _read(path)
    _require(set(value) == _FIELDS and value.get("schema") == SCHEMA
             and isinstance(value["session_path"], str), "registration_invalid")
    identity = value["registrant"]
    _require(isinstance(identity, dict) and set(identity) == {"pid", "created"}
             and type(identity["pid"]) is int and identity["pid"] > 0
             and type(identity["created"]) in (int, float) and math.isfinite(identity["created"])
             and identity["created"] > 0, "registrant_identity_invalid")
    session = _session(value["session_path"])
    _require(value == _registration(root, session, identity) and path == _entry(root, session), "registration_binding_invalid")
    return session, raw


def _publish_new(temporary, target):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        move = kernel.MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        # Write-through rename, without REPLACE_EXISTING: never overwrite a
        # registration which appeared while this writer was preparing its file.
        if not move(str(temporary), str(target), 0x8):
            code = ctypes.get_last_error()
            if code in {80, 183}:
                raise FileExistsError(str(target))
            raise ctypes.WinError(code)
    else:
        os.link(temporary, target)
        fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def register(root, session_path):
    """Durably register one exact, possibly not-yet-created session; idempotent."""
    root, session = _canonical(root), _session(session_path)
    folder = registry_directory(root)
    folder.mkdir(parents=False, exist_ok=True)
    _no_reparse(folder)
    _require(folder.is_dir(), "registry_invalid")
    path = _entry(root, session)
    if path.exists():
        existing, raw = _registered(root, path)
        _require(existing == session, "registration_conflict")
        return json.loads(raw.decode("utf-8"))
    value = _registration(root, session, _current_identity())
    temporary = folder / (".register-" + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write((json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        _no_reparse(folder)
        try:
            _publish_new(temporary, path)
        except FileExistsError:
            _require(_registered(root, path)[0] == session, "registration_conflict")
        existing, raw = _registered(root, path)
        _require(existing == session, "registration_conflict")
        return json.loads(raw.decode("utf-8"))
    finally:
        if temporary.exists():
            _no_reparse(temporary)
            temporary.unlink()


def abandon_unlaunched(root, session_path):
    """Parent-only cleanup after synchronously proving Popen created no child.

    The caller must use this only in that known-not-created launch failure
    branch. Absence/death of a PID, timeout or an exception after Popen returned
    is not that proof. Once the session directory exists this path is closed.
    """
    root, session = _canonical(root), _session(session_path)
    path = _entry(root, session)
    registered, raw = _registered(root, path)
    value = json.loads(raw.decode("utf-8"))
    _require(registered == session and value["registrant"] == _current_identity(), "unlaunched_parent_mismatch")
    _require(not session.exists(), "session_already_created")
    _require(_registered(root, path)[1] == raw, "registration_changed")
    path.unlink()
    return {"abandoned": True, "session_path": str(session), "evidence": "synchronous_launch_not_created"}


def _safe_evidence_tree(session):
    _require(session.is_dir(), "session_missing")
    count = 0
    pending = [session]
    while pending:
        directory = pending.pop()
        _no_reparse(directory)
        for path in directory.iterdir():
            count += 1
            _require(count <= 16384, "evidence_limit")
            _no_reparse(path)
            if path.is_dir():
                pending.append(path)
            else:
                _require(path.is_file(), "evidence_path_invalid")


def _inactive(identity, clock, allow_current_process):
    from app.execution.session_resource_recovery import _inactive as inspect_inactive
    if allow_current_process and identity["pid"] == os.getpid():
        import psutil
        created = psutil.Process(os.getpid()).create_time()
        actual = int(round(created * 1_000_000_000)) if clock == "create_time_ns" else created
        _require(actual == identity[clock], "current_runner_identity_changed")
        return
    inspect_inactive(identity, clock)


def _resources(session, journal, allow_current_process):
    from app.execution.session_resource_recovery import _scope_verified
    from app.learn.hybrid import windows_process_scope as scopes
    _inactive(journal["host_identity"], "created", allow_current_process)
    _inactive(journal["runner_identity"], "create_time_ns", allow_current_process)
    for model in journal["resources"].values():
        phase = model["closed_from_phase"] if model["phase"] == "closed" else model["phase"]
        _require(not (model["ownership"] == "external" and model["pending_request_id"] is not None), "resource_pending")
        if phase == "registered" or model["ownership"] == "external":
            continue
        _require(phase not in {"scope_starting", "launch_starting"}, "resource_identity_unknown")
        identities = {(row["pid"], row["create_time_ns"]): row for row in
                      model["member_identities"] + model["cleanup_member_identities"]}
        proof = scopes.observe_process_scope_cleanup(model["scope_name"], terminate=False,
            remove_owned_pid_file=False, listener_ports=[], stable_zero_observations=3,
            pid_file=session / model["pid_file"], retained_process_identities=tuple(identities.values()),
            timeout_seconds=1.0, interval_seconds=.025, include_diagnostics=True)
        _require(_scope_verified(proof, model["scope_name"]), "resource_cleanup_unverified")


def _admissions(session):
    folder = session.parent / "recovery-admissions"
    _no_reparse(folder)
    if not folder.exists():
        return []
    _require(folder.is_dir(), "admissions_invalid")
    result = []
    for path in sorted(folder.iterdir()):
        _require(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}\.json", path.name), "admission_path_invalid")
        value, raw = _read(path)
        preview = value.get("preview")
        _require(isinstance(preview, dict), "admission_invalid")
        if preview.get("source_session") == str(session) or value.get("new_session_name") == session.name:
            _require(value.get("phase") == "ready", "admission_unsettled")
            result.append((path, value, raw))
    return result


def _recovered(session, records):
    from app.execution.session_epoch_admission import SessionEpochAdmission
    source_records = [(path, value, raw) for path, value, raw in records
                      if value["preview"].get("source_session") == str(session)]
    _require(len(source_records) == 1, "cleanup_unverified")
    path, value, raw = source_records[0]
    pointer = json.loads(value["preview"]["original_pointer_raw_utf8"])
    instant = SimpleNamespace(data_root=session.parent, recognition_source=pointer.get("recognition_source"),
        delegate_profile=pointer.get("delegate_profile"), api_profile=pointer.get("api_profile"),
        decision_profile=pointer.get("decision_profile"), decision_profile_sha256=pointer.get("decision_profile_sha256"))
    contract = SessionEpochAdmission(instant)
    old, _, _ = contract._validate(value, path.stem, value.get("preview_sha256"))
    _require(old == session, "admission_source_invalid")
    # This revalidates original report/resource hashes, original PID creation
    # identities, native model ownership and original input settlement. It does
    # not launch/continue a host or trust a historical "verified" flag alone.
    contract._original_unchanged(value, published=True)
    _require(path.read_bytes() == raw, "admission_changed")
    return {"settled": True, "evidence": "explicit_epoch_recovery", "session_path": str(session),
            "recovery_request_id": path.stem}


def read_session_status(root, session_path, *, allow_current_process=False):
    """Read original cleanup/input/resource evidence without starting any host."""
    _canonical(root)
    session = _session(session_path)
    try:
        _safe_evidence_tree(session)
        report, report_raw = _read(session / "report.json")
        records = _admissions(session)
        normal = (isinstance(report.get("finished_at"), str) and bool(report["finished_at"])
            and report.get("phase") == "stopped" and report.get("host_phase") == "stopped"
            and report.get("cleanup_errors") == [] and report.get("sampler_stopped") is True)
        if not normal:
            return _recovered(session, records)
        from app.execution.session_resources import decode_session_resources
        from app.core.session_input_terminal import inspect_session_input_terminal
        _, resource_raw = _read(session / "session-resources.json")
        journal = decode_session_resources(session, resource_raw)
        _require(report.get("runner_pid") == journal["runner_identity"]["pid"]
                 and type(report.get("runner_pid")) is int, "runner_binding_invalid")
        _resources(session, journal, allow_current_process)
        proof = inspect_session_input_terminal(session, session.parent / "memory-library")
        _require(proof.get("input_terminal_settlement_verified") is True, "input_unsettled")
        _require((session / "report.json").read_bytes() == report_raw
                 and (session / "session-resources.json").read_bytes() == resource_raw, "evidence_changed")
        _resources(session, journal, allow_current_process)
        _safe_evidence_tree(session)
        return {"settled": True, "evidence": "normal_cleanup", "session_path": str(session),
                "input_catalog_sha256": proof["catalog_sha256"]}
    except RuntimeTaskLedgerError:
        raise
    except Exception as error:
        raise RuntimeTaskLedgerError("runtime_task_ledger_session_unsettled") from error


def clear(root, session_path):
    """Clear only verified cleanup; a finalizing runner may verify its own PID."""
    root, session = _canonical(root), _session(session_path)
    path = _entry(root, session)
    original = _registered(root, path)[1] if path.exists() else None
    proof = read_session_status(root, session, allow_current_process=True)
    if original is not None:
        _require(_registered(root, path)[1] == original, "registration_changed")
        path.unlink()
    return {**proof, "cleared": original is not None}


def assert_settled(root, *, clear_settled=False):
    """Verify all registered sessions; optional clearing requires maintenance ownership.

    An absent registry proves no registered activity only, never that a legacy
    version had no live/unknown session. Migration policy remains with callers.
    """
    root = _canonical(root)
    folder = registry_directory(root)
    if not folder.exists():
        return {"settled": True, "registered_sessions": 0, "cleared_sessions": 0,
                "coverage": "registered_sessions_only", "legacy_sessions_proven": False}
    _require(folder.is_dir(), "registry_invalid")
    paths = sorted(folder.iterdir())
    _require(len(paths) <= 4096, "registry_limit")
    verified = []
    for path in paths:
        _require(re.fullmatch(r"[0-9a-f]{64}\.json", path.name), "registry_entry_invalid")
        session, raw = _registered(root, path)
        proof = read_session_status(root, session)
        _require(_registered(root, path)[1] == raw, "registration_changed")
        verified.append((path, raw, proof))
    _require(sorted(folder.iterdir()) == paths, "registry_changed")
    if clear_settled:
        for path, raw, _ in verified:
            _require(_registered(root, path)[1] == raw, "registration_changed")
            path.unlink()
    return {"settled": True, "registered_sessions": len(verified),
            "cleared_sessions": len(verified) if clear_settled else 0,
            "coverage": "registered_sessions_only", "legacy_sessions_proven": False}
