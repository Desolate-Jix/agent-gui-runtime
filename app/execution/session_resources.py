"""持久资源身份清单，不观察或终止进程。"""
from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath
import re
from threading import RLock

from app.core.json_snapshot import write_json_snapshot
import json


_POLICY = {"kill_on_job_close": True, "breakaway_ok": False, "silent_breakaway_ok": False, "owner_handle_authority": "registry_parent"}
_PHASES = {"registered", "scope_starting", "scope_acquired", "launch_starting", "launch_registered", "ready", "closed"}


def _require(condition):
    if not condition:
        raise ValueError("session_resources_invalid_contract")


def _identity(value, clock):
    _require(isinstance(value, dict) and set(value) == {"pid", clock})
    _require(type(value["pid"]) is int and value["pid"] > 0)
    if clock == "created":
        _require(type(value[clock]) in {int, float} and 0 < value[clock] < float("inf"))
    else:
        _require(type(value[clock]) is int and value[clock] > 0)


def _validate(state, root):
    _require(isinstance(state, dict) and set(state) == {"contract_version", "session_name", "recognition_source", "host_identity", "runner_identity", "phase", "resources"})
    _require(state["contract_version"] == "session_resources.v1" and state["session_name"] == root.name)
    _require(isinstance(state["recognition_source"], str) and bool(state["recognition_source"].strip()))
    _identity(state["host_identity"], "created")
    _identity(state["runner_identity"], "create_time_ns")
    _require(isinstance(state["phase"], str) and state["phase"] in {"initializing", "ready"} and isinstance(state["resources"], dict))
    for rid, model in state["resources"].items():
        _require(isinstance(rid, str) and re.fullmatch("[0-9a-f]{32}", rid) is not None)
        _require(isinstance(model, dict) and set(model) == {"scope_name", "pid_file", "phase", "ownership", "policy", "member_identities", "cleanup_member_identities", "closed_from_phase", "pending_request_id"})
        _require(model["scope_name"] == "Local\\AgentGuiNativeModel-" + hashlib.sha256(rid.encode("ascii")).hexdigest())
        path = model["pid_file"]
        _require(isinstance(path, str) and "\\" not in path)
        parts = PurePosixPath(path).parts
        _require(len(parts) == 5 and parts[:4] == ("runtime-output", "model-services", rid, "model-server-pids") and parts[4].endswith(".pid") and parts[4] != ".pid" and PurePosixPath(path).as_posix() == path)
        _require((root / path).resolve().is_relative_to(root.resolve()))
        phase, ownership = model["phase"], model["ownership"]
        _require(isinstance(phase, str) and phase in _PHASES and (ownership is None or isinstance(ownership, str) and ownership in {"owned", "external"}))
        _require(model["policy"] is None or model["policy"] == _POLICY and all(type(model["policy"][key]) is bool for key in ("kill_on_job_close", "breakaway_ok", "silent_breakaway_ok")))
        closed_from = model["closed_from_phase"]
        if phase == "closed":
            _require(isinstance(closed_from, str) and closed_from in _PHASES - {"closed"})
            phase = closed_from
        else:
            _require(closed_from is None)
        members = model["member_identities"]
        _require(isinstance(members, list))
        seen = set()
        for member in members:
            _identity(member, "create_time_ns")
            key = (member["pid"], member["create_time_ns"])
            _require(key not in seen)
            seen.add(key)
        cleanup_members = model["cleanup_member_identities"]
        _require(isinstance(cleanup_members, list))
        seen = set()
        for member in cleanup_members:
            _identity(member, "create_time_ns")
            key = (member["pid"], member["create_time_ns"])
            _require(key not in seen)
            seen.add(key)
        _require(not cleanup_members or ownership == "owned" and phase in {"scope_acquired", "launch_starting", "launch_registered", "ready"})
        pending = model["pending_request_id"]
        _require(pending is None or isinstance(pending, str) and bool(pending.strip()))
        _require(pending is None or model["phase"] == "ready")
        if phase in {"registered", "scope_starting"}:
            _require(ownership is None and model["policy"] is None and not members)
        elif phase in {"scope_acquired", "launch_starting", "launch_registered"}:
            _require(ownership == "owned" and model["policy"] == _POLICY)
            _require(bool(members) == (phase == "launch_registered"))
        else:
            _require(ownership in {"owned", "external"})
            _require(ownership != "owned" or model["policy"] == _POLICY and bool(members))
            _require(ownership != "external" or model["policy"] is None and bool(members))
    return state


def read_session_resources(session_dir):
    root = Path(session_dir).resolve()
    return decode_session_resources(root, (root / "session-resources.json").read_bytes())


def decode_session_resources(session_dir, raw):
    """解析同一份原字节，使验证内容与证据哈希一致。"""
    _require(isinstance(raw, bytes))
    return _validate(json.loads(raw.decode("utf-8")), Path(session_dir).resolve())


class SessionResourceJournal:
    def __init__(self, session_dir, *, recognition_source, host_identity, runner_identity):
        self.session_dir = Path(session_dir).resolve()
        self.path = self.session_dir / "session-resources.json"
        self._lock = RLock()
        _require(not self.path.exists())
        state = {"contract_version": "session_resources.v1", "session_name": self.session_dir.name, "recognition_source": recognition_source, "host_identity": deepcopy(host_identity), "runner_identity": deepcopy(runner_identity), "phase": "initializing", "resources": {}}
        _validate(state, self.session_dir)
        write_json_snapshot(self.path, state)
        self._state = state

    def _change(self, operation):
        with self._lock:
            # 发布成功后才推进内存，失败保留上一版本。
            state = deepcopy(self._state)
            operation(state)
            _validate(state, self.session_dir)
            if state != self._state:
                write_json_snapshot(self.path, state)
                self._state = state

    def register_model(self, resource_id, *, scope_name, pid_file):
        _require(isinstance(resource_id, str) and re.fullmatch("[0-9a-f]{32}", resource_id) is not None)
        candidate = Path(pid_file)
        if not candidate.is_absolute():
            candidate = self.session_dir / candidate
        relative = candidate.resolve().relative_to(self.session_dir).as_posix()
        def update(state):
            _require(resource_id not in state["resources"])
            state["resources"][resource_id] = {"scope_name": scope_name, "pid_file": relative, "phase": "registered", "ownership": None, "policy": None, "member_identities": [], "cleanup_member_identities": [], "closed_from_phase": None, "pending_request_id": None}
        self._change(update)

    def _model_change(self, rid, operation):
        def update(state):
            _require(rid in state["resources"])
            operation(state["resources"][rid])
        self._change(update)

    def _advance(self, rid, original, target, **fields):
        def update(model):
            _require(model["phase"] == original)
            model.update(fields, phase=target)
        self._model_change(rid, update)

    def begin_model_scope(self, resource_id):
        self._advance(resource_id, "registered", "scope_starting")

    def model_scope_acquired(self, resource_id, policy):
        _require(policy == _POLICY)
        self._advance(resource_id, "scope_starting", "scope_acquired", ownership="owned", policy=deepcopy(policy))

    def begin_model_launch(self, resource_id):
        self._advance(resource_id, "scope_acquired", "launch_starting")

    def model_process_created(self, resource_id, identity):
        _identity(identity, "create_time_ns")
        self._advance(resource_id, "launch_starting", "launch_registered", member_identities=[deepcopy(identity)])

    def model_ready(self, resource_id, *, ownership, member_identities):
        def update(model):
            _require((model["phase"] == "registered" and ownership == "external") or (model["phase"] in {"launch_registered", "ready"} and model["ownership"] == ownership))
            for identity in member_identities:
                _identity(identity, "create_time_ns")
                if identity not in model["member_identities"]:
                    model["member_identities"].append(deepcopy(identity))
            model.update(phase="ready", ownership=ownership)
        self._model_change(resource_id, update)

    def model_request_started(self, resource_id, request_id):
        _require(isinstance(request_id, str) and bool(request_id.strip()))
        def update(model):
            _require(model["phase"] == "ready" and model["pending_request_id"] is None)
            model["pending_request_id"] = request_id
        self._model_change(resource_id, update)

    def model_request_finished(self, resource_id, request_id):
        def update(model):
            _require(model["phase"] == "ready" and isinstance(request_id, str) and model["pending_request_id"] == request_id)
            model["pending_request_id"] = None
        self._model_change(resource_id, update)

    def model_closed(self, resource_id):
        def update(model):
            _require(model["pending_request_id"] is None)
            if model["phase"] != "closed":
                # 关闭事实不补齐此前启动身份，也不证明资源清理完整。
                model["closed_from_phase"] = model["phase"]
                model["phase"] = "closed"
        self._model_change(resource_id, update)

    def model_cleanup_members_observed(self, resource_id, identities):
        _require(isinstance(identities, list))
        def update(model):
            _require(model["ownership"] == "owned" and model["phase"] in {"scope_acquired", "launch_starting", "launch_registered", "ready"})
            for identity in identities:
                _identity(identity, "create_time_ns")
                if identity not in model["cleanup_member_identities"]:
                    model["cleanup_member_identities"].append(deepcopy(identity))
        self._model_change(resource_id, update)

    def mark_ready(self):
        self._change(lambda state: state.update(phase="ready"))
