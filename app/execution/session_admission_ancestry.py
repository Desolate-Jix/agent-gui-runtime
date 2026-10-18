"""归档准入链仅证明只读来源，不授予清理、接管或输入能力。"""
from hashlib import sha256
import json
import math
from pathlib import Path
import re

import psutil

from app.desktop_review.external_mapping import canonical_json_bytes
from .session_resources import decode_session_resources
from .session_input_terminal import _catalog


def _require(value, reason):
    if not value:
        raise ValueError("workflow_recovery_ancestry_" + reason)


def _identity(value):
    return (isinstance(value, dict) and set(value) == {"pid", "created"}
        and type(value["pid"]) is int and value["pid"] > 0
        and type(value["created"]) in (int, float) and math.isfinite(value["created"]) and value["created"] > 0)


def _alive(pid, created):
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE and process.create_time() == created
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied as error:
        raise ValueError("workflow_recovery_ancestry_process_unverifiable") from error


def inspect_admission_ancestry(session_dir, admission_record_path, successor_admission_paths):
    """固定全部原字节并验证已死亡来源到当前活宿主的明确 ready 链。"""
    session = Path(session_dir).resolve()
    root = session.parent
    _require(isinstance(successor_admission_paths, (list, tuple)) and 1 <= len(successor_admission_paths) <= 16,
             "successors_invalid")
    snapshots = {}

    def raw(path):
        value = path.read_bytes()
        _require(path not in snapshots or snapshots[path] == value, "changed")
        snapshots[path] = value
        return value

    def read(path):
        value = json.loads(raw(path).decode("utf-8-sig"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
        _require(isinstance(value, dict), "json_invalid")
        return value

    paths = []
    for value in [admission_record_path, *successor_admission_paths]:
        path = Path(value)
        _require(path.is_absolute() and path == path.resolve() and path.parent == root / "recovery-admissions"
                 and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}\.json", path.name) and path not in paths, "path_invalid")
        paths.append(path)
    previous = None
    sources = set()
    first_pointer = None
    for path in paths:
        record = read(path)
        _require(set(record) == {"contract_version", "request_id", "preview_sha256", "preview", "new_session_name", "phase", "new_host_identity"}
                 and record["contract_version"] == "session_epoch_admission.v1" and record["request_id"] == path.stem
                 and record["phase"] == "ready", "record_invalid")
        preview = record["preview"]
        _require(isinstance(preview, dict) and set(preview) == {"contract_version", "source_session", "original_pointer_raw_utf8", "resource_proof", "input_proof", "preview_sha256"}
                 and preview["contract_version"] == "session_epoch_admission_preview.v1"
                 and isinstance(record["preview_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", record["preview_sha256"])
                 and preview["preview_sha256"] == record["preview_sha256"]
                 and sha256(canonical_json_bytes({key: value for key, value in preview.items() if key != "preview_sha256"})).hexdigest() == record["preview_sha256"], "preview_invalid")
        source = Path(preview["source_session"])
        _require(source.is_absolute() and source == source.resolve() and source.parent == root
                 and re.fullmatch(r"session-[0-9a-f]{32}", source.name) and source not in sources, "source_invalid")
        sources.add(source)
        pointer = json.loads(preview["original_pointer_raw_utf8"])
        _require(isinstance(pointer, dict) and set(pointer) == {"name", "host_identity", "recognition_source", "delegate_profile", "api_profile"}
                 and pointer["name"] == source.name and _identity(pointer["host_identity"]), "pointer_invalid")
        if previous is None:
            _require(source == session, "source_invalid")
            first_pointer = pointer
        else:
            _require(pointer == previous and source.name == previous["name"], "chain_binding_invalid")
        proof, inputs = preview["resource_proof"], preview["input_proof"]
        _require(isinstance(proof, dict) and proof.get("contract_version") == "session_resource_cleanup.v1"
                 and proof.get("resources_cleanup_verified") is True and isinstance(inputs, dict)
                 and inputs.get("contract_version") == "session_input_terminal.v1"
                 and inputs.get("input_terminal_settlement_verified") is True, "proof_invalid")
        catalog = _catalog(source)
        _require(isinstance(inputs.get("files"), dict)
                 and inputs["files"] == {name: sha256(value).hexdigest() for name, value in catalog.items()}, "input_snapshot_invalid")
        for name, value in catalog.items():
            evidence = source / name
            _require(evidence not in snapshots or snapshots[evidence] == value, "changed")
            snapshots[evidence] = value
        report_raw, resource_raw = raw(source / "report.json"), raw(source / "session-resources.json")
        hashes = proof["original_snapshots"]
        _require(hashes.get("pointer") == sha256(preview["original_pointer_raw_utf8"].encode("utf-8")).hexdigest()
                 and hashes.get("report") == sha256(report_raw).hexdigest()
                 and hashes.get("resources") == sha256(resource_raw).hexdigest(), "snapshot_invalid")
        journal = decode_session_resources(source, resource_raw)
        host, runner = journal["host_identity"], journal["runner_identity"]
        _require(host == pointer["host_identity"] == proof.get("host_identity")
                 and runner == proof.get("runner_identity") and json.loads(report_raw).get("runner_pid") == runner["pid"]
                 and proof.get("session_name") == source.name
                 and journal["recognition_source"] == pointer["recognition_source"] == proof.get("recognition_source"), "resource_binding_invalid")
        _require(not _alive(host["pid"], host["created"])
                 and not _alive(runner["pid"], runner["create_time_ns"] / 1_000_000_000), "source_alive")
        new_name, new_host = record["new_session_name"], record["new_host_identity"]
        _require(isinstance(new_name, str) and re.fullmatch(r"session-[0-9a-f]{32}", new_name)
                 and root / new_name not in sources and _identity(new_host), "new_identity_invalid")
        previous = {**pointer, "name": new_name, "host_identity": new_host}
    _require(read(root / "latest-session.json") == previous, "live_pointer_invalid")
    _require(_alive(previous["host_identity"]["pid"], previous["host_identity"]["created"]), "live_host_inactive")
    _require(all(path.read_bytes() == value for path, value in snapshots.items()), "changed")
    return {"original_pointer": first_pointer, "file_hashes": {str(path): sha256(value).hexdigest() for path, value in snapshots.items()}}
