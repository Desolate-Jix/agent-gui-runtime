"""只观察原资源；资源证明不授予新会话或输入接管权限。"""
import hashlib
import json
import math
from pathlib import Path
import re

import psutil

from app.execution.session_resources import decode_session_resources
from app.learn.hybrid import windows_process_scope as scopes


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _inactive(identity, clock):
    try:
        process = psutil.Process(identity["pid"])
        created = process.create_time()
        _require(type(created) in (int, float) and math.isfinite(created) and created > 0,
                 "resource_process_identity_unobservable")
        original = identity[clock]
        actual = int(round(created * 1_000_000_000)) if clock == "create_time_ns" else created
        if actual != original:
            return
        _require(not process.is_running() or process.status() == psutil.STATUS_ZOMBIE,
                 "resource_original_process_active")
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return
    except psutil.AccessDenied as error:
        raise ValueError("resource_process_access_denied") from error
    except (OSError, RuntimeError) as error:
        raise ValueError("resource_process_identity_unobservable") from error


def _scope_verified(evidence, name):
    if not isinstance(evidence, dict):
        return False
    if (evidence.get("contract_version") != scopes.PROCESS_SCOPE_CONTRACT_VERSION
            or evidence.get("scope_name") != name
            or evidence.get("authority") != "windows_job_object"
            or evidence.get("cleanup_status") != "verified"
            or type(evidence.get("stable_zero_observations")) is not int
            or evidence["stable_zero_observations"] < 3):
        return False
    for field in ("member_pids_after", "member_identities_after", "remaining_owned_process_identities", "active_listeners_after"):
        if evidence.get(field) != []:
            return False
    if "pid_file_after" not in evidence or evidence["pid_file_after"] is not None:
        return False
    samples = evidence.get("samples")
    if not isinstance(samples, list) or len(samples) < 3:
        return False
    return all(isinstance(sample, dict) and all(sample.get(field) == [] for field in (
        "pids", "process_identities", "listeners", "remaining_owned_process_identities")) for sample in samples[-3:])


def observe_session_resource_cleanup(session_dir, *, timeout_seconds=1.0):
    _require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
             and 0 < timeout_seconds <= 10, "resource_timeout_invalid")
    root = Path(session_dir).resolve()
    _require(re.fullmatch(r"session-[0-9a-f]{32}", root.name) is not None, "resource_session_invalid")
    paths = {"pointer": root.parent / "latest-session.json", "report": root / "report.json",
             "resources": root / "session-resources.json"}
    try:
        original = {key: path.read_bytes() for key, path in paths.items()}
        pointer = json.loads(original["pointer"].decode("utf-8"))
        report = json.loads(original["report"].decode("utf-8"))
        journal = decode_session_resources(root, original["resources"])
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        raise ValueError("resource_snapshot_invalid") from error
    hashes = {key: hashlib.sha256(value).hexdigest() for key, value in original.items()}
    _require(isinstance(pointer, dict) and isinstance(report, dict), "resource_binding_invalid")
    host = pointer.get("host_identity")
    _require(isinstance(host, dict) and set(host) == {"pid", "created"}
             and type(host["pid"]) is int and type(host["created"]) in (int, float)
             and math.isfinite(host["created"]), "resource_pointer_binding_invalid")
    _require(pointer.get("name") == root.name and pointer.get("recognition_source") == journal["recognition_source"]
             and pointer.get("host_identity") == journal["host_identity"], "resource_pointer_binding_invalid")
    _require(type(report.get("runner_pid")) is int and report["runner_pid"] == journal["runner_identity"]["pid"],
             "resource_runner_binding_invalid")

    def unchanged():
        try:
            _require(all(path.read_bytes() == original[key] for key, path in paths.items()), "resource_snapshot_changed")
        except OSError as error:
            raise ValueError("resource_snapshot_changed") from error
        _inactive(journal["host_identity"], "created")
        _inactive(journal["runner_identity"], "create_time_ns")

    unchanged()
    models = {}
    for rid, model in journal["resources"].items():
        phase = model["closed_from_phase"] if model["phase"] == "closed" else model["phase"]
        result = {"status": "indeterminate", "phase": model["phase"], "closed_from_phase": model["closed_from_phase"],
                  "ownership": model["ownership"]}
        if model["pending_request_id"] is not None and model["ownership"] == "external":
            result["reason"] = "resource_request_pending"
        elif phase == "registered" or model["ownership"] == "external":
            result["status"] = "verified"
        elif phase in {"scope_starting", "launch_starting"}:
            result["reason"] = "resource_launch_identity_incomplete"
        else:
            identities = {(row["pid"], row["create_time_ns"]): row for row in (
                model["member_identities"] + model["cleanup_member_identities"])}
            try:
                evidence = scopes.observe_process_scope_cleanup(model["scope_name"], terminate=False,
                    remove_owned_pid_file=False, listener_ports=[], stable_zero_observations=3,
                    pid_file=root / model["pid_file"], retained_process_identities=tuple(identities.values()),
                    timeout_seconds=timeout_seconds, interval_seconds=min(.025, timeout_seconds / 4),
                    include_diagnostics=True)
                if _scope_verified(evidence, model["scope_name"]):
                    result["status"] = "verified"
                result["observation"] = {key: value for key, value in evidence.items() if key != "details"} if isinstance(evidence, dict) else None
            except Exception as error:
                result["error_type"] = type(error).__name__
        models[rid] = result
    unchanged()
    return {"contract_version": "session_resource_cleanup.v1", "session_name": root.name,
            "recognition_source": journal["recognition_source"], "host_identity": journal["host_identity"],
            "runner_identity": journal["runner_identity"], "original_snapshots": hashes,
            "model_resources": models, "resources_cleanup_verified": all(row["status"] == "verified" for row in models.values()),
            "input_terminal_settlement_verified": False, "new_epoch_ready": False}
