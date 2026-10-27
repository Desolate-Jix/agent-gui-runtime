"""Durable control ordering; a failed request never implies that input was absent."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _write(path, value):
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        move.restype = wintypes.BOOL
        if not move(str(temporary), str(path), 0x1 | 0x8):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class ControlRejectionProof:
    def __init__(self, value):
        self.value = deepcopy(value)


class TaskPlanControlReceipt:
    def __init__(self, session, owner_id, request_id, request):
        from app.core.json_snapshot import read_json_snapshot
        self.session = Path(session).resolve()
        self.path = self.session / "task-plan-controls" / (request_id + ".json")
        self.path.parent.mkdir(exist_ok=True)
        if self.path.parent.resolve().parent != self.session:
            raise ValueError("task_plan_control_receipt_path_invalid")
        binding = {"schema": "task_plan_control_receipt.v1", "session_directory": str(self.session),
            "owner_id": owner_id, "request_id": request_id,
            "command_sha256": digest({"kind": "task_plan", "request": request})}
        prior = read_json_snapshot(self.path) if self.path.exists() else None
        prior_fields = set(binding) | {"phase", "input_dispatch_started"}
        if isinstance(prior, dict) and prior.get("phase") in {"failed", "rejected_before_dispatch"}:
            prior_fields |= {"error_type", "error_sha256"}
        if prior is not None and (not isinstance(prior, dict)
                or set(prior) != prior_fields
                or any(prior.get(key) != value for key, value in binding.items())
                or type(prior.get("input_dispatch_started")) is not bool
                or prior.get("phase") == "rejected_before_dispatch" and prior["input_dispatch_started"] is not False
                or prior.get("phase") in {"input_possible", "failed"} and prior["input_dispatch_started"] is not True
                or prior.get("phase") not in {"processing", "input_possible", "returned", "failed", "rejected_before_dispatch"}):
            if (isinstance(prior, dict) and isinstance(request, dict) and request.get("action") == "start"
                    and prior.get("command_sha256") != binding["command_sha256"]):
                raise ValueError("task_plan_start_idempotency_conflict")
            raise ValueError("task_plan_control_receipt_conflict")
        # Unknown/interrupted attempts are never downgraded on a same-ID retry.
        self.input_possible = bool(prior and (prior["input_dispatch_started"]
            or prior["phase"] in {"processing", "input_possible", "failed"}))
        self.value = {**binding, "phase": "processing", "input_dispatch_started": self.input_possible}
        _write(self.path, self.value)

    def before_input_capability(self):
        if self.input_possible:
            return
        # Set memory first: even a writer that raises after replace cannot permit
        # the exception handler to overwrite an uncertain dispatch with rejection.
        self.input_possible = True
        self.value.update(phase="input_possible", input_dispatch_started=True)
        _write(self.path, self.value)

    def returned(self):
        self.value.update(phase="returned", input_dispatch_started=self.input_possible)
        _write(self.path, self.value)

    def failed(self, error):
        self.value.update(phase="failed" if self.input_possible else "rejected_before_dispatch",
            input_dispatch_started=self.input_possible,
            error_type=type(error).__name__, error_sha256=digest(str(error)))
        _write(self.path, self.value)
        if not self.input_possible:
            error.task_plan_control_rejection = ControlRejectionProof({
                "contract_version": "task_plan_control_rejection.v1", "request_id": self.value["request_id"],
                "status": "rejected_before_dispatch", "input_attempted": False, "action_executed": False,
                "record": {"path": self.path.relative_to(self.session).as_posix(),
                    "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest()}})


def preserve_control_rejection(response, error, request_id):
    proof = getattr(error, "task_plan_control_rejection", None)
    if isinstance(proof, ControlRejectionProof) and proof.value["request_id"] == request_id:
        response["result"] = deepcopy(proof.value)
