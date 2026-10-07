"""显式新会话准入；不消费旧输入或接管工作流。"""
import hashlib
import json
import math
from pathlib import Path
import re
from uuid import uuid4

import psutil

from app.core.session_epoch_read_contract import SessionEpochReadContract
from app.core.json_snapshot import write_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.execution.session_resource_recovery import observe_session_resource_cleanup, _inactive, _scope_verified
from app.execution.session_resources import decode_session_resources
from app.learn.hybrid import windows_process_scope as scopes


_PREVIEW = "session_epoch_admission_preview.v1"
_RECORD = "session_epoch_admission.v1"
_PHASES = {"prepared", "launch_started", "host_created", "pointer_published", "ready"}


def _require(condition, code):
    if not condition:
        raise ValueError("epoch_admission_" + code)


def _read(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        _require(isinstance(value, dict), "snapshot_invalid")
        return value, raw
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("epoch_admission_snapshot_invalid") from error


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _inspect_inputs(session, library, *, admission_record_path=None):
    from app.execution.session_input_terminal import inspect_session_input_terminal
    if admission_record_path is None:
        return inspect_session_input_terminal(session, library)
    return inspect_session_input_terminal(session, library, admission_record_path=admission_record_path)


class SessionEpochAdmission(SessionEpochReadContract):

    def preview(self):
        instant = self.instant
        root = Path(instant.data_root).resolve()
        pointer, raw = _read(root / "latest-session.json")
        old = self._session(pointer.get("name"))
        _require(instant.session is None or Path(instant.session).resolve() == old, "session_changed")
        self._config_matches(pointer)
        resource = observe_session_resource_cleanup(old)
        inputs = _inspect_inputs(old, root / "memory-library")
        _require(resource.get("resources_cleanup_verified") is True, "resources_unverified")
        _require(inputs.get("input_terminal_settlement_verified") is True, "input_unsettled")
        _require(resource.get("session_name") == old.name and resource.get("host_identity") == pointer.get("host_identity")
                 and resource.get("recognition_source") == instant.recognition_source, "resource_binding_invalid")
        _require(resource.get("original_snapshots", {}).get("pointer") == _sha(raw), "pointer_changed")
        _require((root / "latest-session.json").read_bytes() == raw, "pointer_changed")
        value = {"contract_version": _PREVIEW, "source_session": str(old),
                 "original_pointer_raw_utf8": raw.decode("utf-8"),
                 "resource_proof": resource, "input_proof": inputs}
        return {**value, "preview_sha256": _sha(canonical_json_bytes(value))}








    def _original_unchanged(self, record, published=False):
        old, _, _ = self._validate(record, record["request_id"], record["preview_sha256"])
        preview = record["preview"]
        if not published:
            # 创建后 Instant 已指向新目录，预览仍只验证保存的原目录。
            saved_session = self.instant.session
            try:
                self.instant.session = old
                _require(self.preview() == preview, "preview_changed")
            finally:
                self.instant.session = saved_session
            return
        hashes = preview["resource_proof"]["original_snapshots"]
        _, report_raw = _read(old / "report.json")
        journal_raw = (old / "session-resources.json").read_bytes()
        _require(_sha(report_raw) == hashes["report"] and _sha(journal_raw) == hashes["resources"], "preview_changed")
        journal = decode_session_resources(old, journal_raw)
        _require(journal["host_identity"] == preview["resource_proof"]["host_identity"]
                 and journal["runner_identity"] == preview["resource_proof"]["runner_identity"]
                 and journal["recognition_source"] == self.instant.recognition_source, "preview_changed")
        _inactive(journal["host_identity"], "created")
        _inactive(journal["runner_identity"], "create_time_ns")
        for model in journal["resources"].values():
            phase = model["closed_from_phase"] if model["phase"] == "closed" else model["phase"]
            _require(not (model["ownership"] == "external" and model["pending_request_id"] is not None), "resources_unverified")
            if phase == "registered" or model["ownership"] == "external":
                continue
            _require(phase not in {"scope_starting", "launch_starting"}, "resources_unverified")
            identities = {(row["pid"], row["create_time_ns"]): row for row in
                          model["member_identities"] + model["cleanup_member_identities"]}
            evidence = scopes.observe_process_scope_cleanup(model["scope_name"], terminate=False,
                remove_owned_pid_file=False, listener_ports=[], stable_zero_observations=3,
                pid_file=old / model["pid_file"], retained_process_identities=tuple(identities.values()),
                timeout_seconds=1.0, interval_seconds=.025, include_diagnostics=True)
            _require(_scope_verified(evidence, model["scope_name"]), "resources_unverified")
        admission_path = Path(self.instant.data_root) / "recovery-admissions" / (record["request_id"] + ".json")
        _require(_inspect_inputs(old, Path(self.instant.data_root) / "memory-library",
                 admission_record_path=admission_path) == preview["input_proof"], "preview_changed")
        _require((old / "report.json").read_bytes() == report_raw
                 and (old / "session-resources.json").read_bytes() == journal_raw, "preview_changed")

    def recover(self, request_id, preview_sha256):
        from app.instant_mcp import _validate_request_id
        _validate_request_id(request_id)
        _require(request_id.isascii(), "request_id_invalid")
        _require(isinstance(preview_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", preview_sha256), "preview_hash_invalid")
        instant = self.instant
        with instant.guard:
            config = instant._startup_configuration()
            _require(config.source == instant.recognition_source, "configuration_changed")
            instant._lock()
            folder = Path(instant.data_root) / "recovery-admissions"
            path = folder / (request_id + ".json")
            for other in folder.glob("*.json"):
                if other == path:
                    continue
                value, _ = _read(other)
                self._validate(value, other.stem, value.get("preview_sha256"))
                _require(value["phase"] == "ready", "unfinished_admission")
            if path.exists():
                record, _ = _read(path)
                old, new, pointer = self._validate(record, request_id, preview_sha256)
            else:
                preview = self.preview()
                _require(preview["preview_sha256"] == preview_sha256, "preview_changed")
                record = {"contract_version": _RECORD, "request_id": request_id,
                          "preview_sha256": preview_sha256, "preview": preview,
                          "new_session_name": "session-" + uuid4().hex,
                          "phase": "prepared", "new_host_identity": None}
                old, new, pointer = self._validate(record, request_id, preview_sha256)
                folder.mkdir(parents=True, exist_ok=True)
                write_json_snapshot(path, record)
            if record["phase"] == "launch_started":
                return self._result(record, "launch_unknown", False)
            current, raw = _read(Path(instant.data_root) / "latest-session.json")
            published = current == self._new_pointer(record) and record["new_host_identity"] is not None
            if published:
                _require(record["phase"] in {"host_created", "pointer_published", "ready"}, "pointer_invalid")
            else:
                _require(raw.decode("utf-8") == record["preview"]["original_pointer_raw_utf8"], "foreign_pointer")
                _require(record["phase"] in {"prepared", "host_created"}, "pointer_invalid")
            self._original_unchanged(record, published)
            if record["phase"] == "prepared":
                instant._check_peer_hosts(exclude_session=old)
                _require(not new.exists(), "new_session_exists")
                record["phase"] = "launch_started"
                write_json_snapshot(path, record)

                def created(identity):
                    self._identity(identity)
                    record["new_host_identity"] = dict(identity)
                    record["phase"] = "host_created"
                    write_json_snapshot(path, record)

                def before_publish():
                    self._verify_created(record)
                    self._original_unchanged(record)

                instant._launch_session(config, session_name=record["new_session_name"],
                                        on_created=created, before_publish=before_publish)
                current, _ = _read(Path(instant.data_root) / "latest-session.json")
                _require(current == self._new_pointer(record), "pointer_invalid")
                published = True
            elif record["phase"] == "host_created" and not published:
                self._verify_created(record)
                self._original_unchanged(record)
                write_json_snapshot(Path(instant.data_root) / "latest-session.json", self._new_pointer(record))
                published = True
            self._verify_created(record)
            instant.session = new
            instant.host_identity = dict(record["new_host_identity"])
            if getattr(getattr(instant, "process", None), "pid", None) != instant.host_identity["pid"]:
                instant.process = None
            if record["phase"] == "host_created":
                record["phase"] = "pointer_published"
                write_json_snapshot(path, record)
            ready = self._ready(record)
            latest, _ = _read(Path(instant.data_root) / "latest-session.json")
            _require(latest == self._new_pointer(record), "foreign_pointer")
            if record["phase"] == "ready":
                _require(ready, "ready_host_changed")
            elif ready:
                record["phase"] = "ready"
                write_json_snapshot(path, record)
            return self._result(record, record["phase"], ready)

    def _result(self, record, phase, ready):
        status = self.instant.status()
        # 未知启动只保留历史预览；本次没有重核旧 epoch，不宣称当前证明有效。
        current_verified = phase != "launch_unknown"
        return {**status, "recovery_admission": {"contract_version": _RECORD,
            "request_id": record["request_id"], "preview_sha256": record["preview_sha256"],
            "source_session": record["preview"]["source_session"], "new_session_name": record["new_session_name"],
            "phase": phase, "resources_cleanup_verified": current_verified,
            "input_terminal_settlement_verified": current_verified,
            "historical_resources_cleanup_verified": record["preview"]["resource_proof"]["resources_cleanup_verified"],
            "historical_input_terminal_settlement_verified": record["preview"]["input_proof"]["input_terminal_settlement_verified"],
            "new_epoch_ready": ready, "workflow_takeover_completed": False, "automatic_retry_allowed": False}}

    def _verify_created(self, record):
        process = self._process(record["new_host_identity"], self._session(record["new_session_name"]))
        command = process.cmdline()
        indexes = [i for i, part in enumerate(command) if part == "--parent-pid"]
        _require(len(indexes) == 1 and indexes[0] + 1 < len(command)
                 and command[indexes[0] + 1].isascii() and command[indexes[0] + 1].isdigit()
                 and int(command[indexes[0] + 1]) > 0
                 and process.ppid() == int(command[indexes[0] + 1]), "launcher_ancestry_invalid")

    def _process(self, identity, session):
        self._identity(identity)
        try:
            process = psutil.Process(identity["pid"])
            _require(process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                     and process.create_time() == identity["created"], "created_host_inactive")
            command = process.cmdline()
            entry = (Path(self.instant.root) / "scripts/run_local_step_session.py").resolve()
            _require(any(Path(part).resolve() == entry for part in command[1:]), "process_entry_invalid")
            expected = {"--output": str(session), "--recognition-source": self.instant.recognition_source}
            for key in ("delegate_profile", "api_profile"):
                if getattr(self.instant, key) is not None:
                    expected["--" + key.replace("_", "-")] = getattr(self.instant, key)
                else:
                    _require("--" + key.replace("_", "-") not in command, "process_configuration_invalid")
            for key, value in expected.items():
                indexes = [i for i, part in enumerate(command) if part == key]
                _require(len(indexes) == 1 and indexes[0] + 1 < len(command), "process_configuration_invalid")
                actual = command[indexes[0] + 1]
                _require(Path(actual).resolve() == session if key == "--output" else actual == value,
                         "process_configuration_invalid")
            _require("--local-no-learning" in command, "process_configuration_invalid")
            indexes = [i for i, part in enumerate(command) if part == "--model-directory"]
            if self.instant.recognition_source == "local":
                _require(len(indexes) == 1 and indexes[0] + 1 < len(command)
                         and self.instant.model_directory is not None
                         and Path(command[indexes[0] + 1]).resolve() == Path(self.instant.model_directory).resolve(),
                         "process_model_directory_invalid")
            else:
                _require(not indexes, "process_model_directory_unexpected")
            return process
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied) as error:
            raise ValueError("epoch_admission_created_host_unverifiable") from error

    def _ready(self, record):
        session = self._session(record["new_session_name"])
        report_path = session / "report.json"
        if not report_path.is_file():
            return False
        report, _ = _read(report_path)
        _require(not report.get("finished_at"), "new_host_finished")
        if report.get("phase") != "ready":
            return False
        journal = decode_session_resources(session, (session / "session-resources.json").read_bytes())
        _require(journal["phase"] == "ready" and journal["host_identity"] == record["new_host_identity"]
                 and journal["recognition_source"] == self.instant.recognition_source, "new_journal_invalid")
        runner = journal["runner_identity"]
        _require(report.get("runner_pid") == runner["pid"], "new_runner_invalid")
        process = psutil.Process(runner["pid"])
        created = process.create_time()
        _require(int(round(created * 1_000_000_000)) == runner["create_time_ns"], "new_runner_invalid")
        self._process({"pid": runner["pid"], "created": created}, session)
        _require(runner["pid"] == record["new_host_identity"]["pid"]
                 or process.ppid() == record["new_host_identity"]["pid"], "new_runner_ancestry_invalid")
        if record["phase"] != "ready":
            _require(report.get("target") is None and report.get("workflow_run") is None, "new_host_not_empty")
        for folder in ("commands", "agent-commands", "workflow-trials", "workflow-runners"):
            if record["phase"] != "ready":
                _require(not any(p.is_file() for p in (session / folder).rglob("*")), "new_host_not_empty")
        return True
