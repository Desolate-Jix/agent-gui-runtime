"""工作台只读发现原工作流来源，当前效果仍由宿主重新观察。"""
from hashlib import sha256
import json
from pathlib import Path
import re
from types import SimpleNamespace

from app.core.session_epoch_read_contract import SessionEpochReadContract
from app.core.session_input_terminal import inspect_session_input_terminal
from .workflow_recovery_import import _source, _verify_unexecuted
from .workflow_runner import _run_id
from .workflow_trial import TrialService
from .workspace import MemoryWorkspace


def _require(value, reason):
    if not value:
        raise ValueError("workflow_takeover_sources_" + reason)


def _read(path):
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (
        _ for _ in ()).throw(ValueError("workflow_takeover_sources_json_invalid")))
    _require(isinstance(value, dict), "json_invalid")
    return value, raw


def read_takeover_sources(session_dir, library_root):
    session, library_root = Path(session_dir).resolve(), Path(library_root).resolve()
    root = session.parent
    _require(re.fullmatch(r"session-[0-9a-f]{32}", session.name) and session.is_dir(), "session_invalid")
    _require(library_root == root / "memory-library" and library_root.is_dir(), "library_mismatch")
    directory = root / "recovery-admissions"
    if not directory.exists():
        return []
    _require(directory.resolve() == directory and directory.is_dir(), "admission_path_invalid")
    pointer, pointer_raw = _read(root / "latest-session.json")
    report, _ = _read(session / "report.json")
    _require(pointer.get("name") == session.name and report.get("phase") == "ready"
             and not report.get("finished_at"), "current_session_not_ready")
    # 仅复用准入的数据校验方法；此对象没有启动、输入或清理能力。
    admission = SessionEpochReadContract(SimpleNamespace(data_root=root,
        recognition_source=pointer.get("recognition_source"), delegate_profile=pointer.get("delegate_profile"),
        api_profile=pointer.get("api_profile")))
    rows = []
    for path in sorted(directory.glob("*.json")):
        _require(path.resolve() == path and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}\.json", path.name),
                 "admission_path_invalid")
        record, record_raw = _read(path)
        if record.get("new_session_name") != session.name:
            continue
        _require(record.get("phase") == "ready", "admission_not_ready")
        old, new, _ = admission._validate(record, path.stem, record.get("preview_sha256"))
        _require(new == session and pointer == admission._new_pointer(record), "current_binding_changed")
        proof = inspect_session_input_terminal(old, library_root, admission_record_path=path)
        _require(proof == record["preview"]["input_proof"], "source_changed")
        active_path = old / "workflow-runners" / "active.json"
        if active_path.exists():
            active, active_raw = _read(active_path)
            _require(set(active) == {"schema", "run_id"} and active["schema"] == "workflow_runner.v1",
                     "active_invalid")
            run_id = _run_id(active["run_id"])
            with MemoryWorkspace(library_root) as library:
                trials = TrialService(library, old)
                state = trials.status(run_id)
                if state.get("recovery_settlement") is None:
                    runner, _ = _read(old / "workflow-runners" / (run_id + ".json"))
                    _require(state.get("status") in {"completed", "failed", "cancelled"}
                             and state.get("pending") is None
                             and runner.get("runner_state") == state["status"]
                             and runner.get("ticket") is None, "source_unsettled")
                else:
                    _, state, program, _, _ = _source(library, session, path.stem, run_id)
                    settlement = state["recovery_settlement"]
                    steps = [step for step in program["definition"]["steps"]
                             if step["step_id"] == settlement["step_id"]]
                    _require(len(steps) == 1, "pinned_step_invalid")
                    try:
                        _verify_unexecuted(old, state)
                    except ValueError as error:
                        available, reason = False, str(error)
                    else:
                        available, reason = True, None
                    rows.append({"admission_request_id": path.stem, "source_run_id": run_id,
                        "source_session": str(old), "workflow_id": state["workflow_id"],
                        "program_id": state["program_id"], "program_sha256": program["content_sha256"],
                        "step_id": settlement["step_id"], "step_title": steps[0]["title"],
                        "terminal_status": settlement["terminal_status"],
                        "action_executed": settlement["action_executed"],
                        "resume_unexecuted_available": available, "resume_unexecuted_reason": reason,
                        "current_effect_verified": False})
            _require(active_path.read_bytes() == active_raw, "source_changed")
        _require(inspect_session_input_terminal(old, library_root, admission_record_path=path) == proof
                 and path.read_bytes() == record_raw, "source_changed")
    current_report, _ = _read(session / "report.json")
    _require((root / "latest-session.json").read_bytes() == pointer_raw
             and current_report.get("phase") == "ready" and not current_report.get("finished_at")
             and current_report.get("runner_pid") == report.get("runner_pid"), "current_binding_changed")
    return rows
