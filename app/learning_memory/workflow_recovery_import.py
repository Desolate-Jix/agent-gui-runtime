"""在新账本中明确导入已核验来源；共享声明先落盘，不重放旧输入。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from app.desktop_review.external_mapping import canonical_json_bytes
from app.core.instant_command_queue import command_queue_lock
from app.execution.session_input_terminal import _catalog, inspect_session_input_terminal
from .receipt_adapter import resolve_execution_receipt
from .workflow_execution_strategy import execution_strategy
from .workflow_program import _id
from .workflow_runner import _exclusive, _run_id
from .workflow_trial import TrialService, _conditions, _execution_identity, _read, _write, _verified_observation
from .workflow_terminal_recovery import WorkflowTerminalRecovery, _action_claims
from .workflow_recovery_history import verify_recovery_history
from .workflow_recovery_resolution import marker_resolution, validate_resolution
from .workflow_verification import verify_current_effect
from .workspace import MemoryWorkspace


_SESSION = re.compile(r"session-[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ADMISSION = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}\Z")


def _require(value, reason):
    if not value:
        raise ValueError("workflow_takeover_" + reason)


def _digest(value):
    return sha256(canonical_json_bytes(value)).hexdigest()


def _confined(root, value):
    path = (root / value).resolve()
    _require(path.is_relative_to(root) and path != root, "path_outside_session")
    return path


def _source(library, session, admission_request_id, source_run_id, *, archived_admission_chain=None):
    _require(isinstance(admission_request_id, str) and _ADMISSION.fullmatch(admission_request_id), "admission_id_invalid")
    path = session.parent / "recovery-admissions" / (admission_request_id + ".json")
    _require(path.resolve().parent == (session.parent / "recovery-admissions").resolve(), "admission_path_invalid")
    raw = path.read_bytes()
    admission = json.loads(raw.decode("utf-8"))
    _require(admission.get("phase") == "ready" and admission.get("new_session_name") == session.name,
             "admission_not_ready_or_foreign")
    preview = admission.get("preview")
    _require(isinstance(preview, dict) and isinstance(preview.get("source_session"), str), "admission_invalid")
    old = Path(preview["source_session"]).resolve()
    _require(old.parent == session.parent and _SESSION.fullmatch(old.name) and old != session, "source_session_invalid")
    pointer = json.loads(preview["original_pointer_raw_utf8"])
    report = _read(old / "report.json")
    service = WorkflowTerminalRecovery(TrialService(library, old), host_identity=pointer["host_identity"],
                                       runner_pid=report["runner_pid"])
    state = (service.status_archived(_run_id(source_run_id), path, archived_admission_chain)
             if archived_admission_chain else service.status_admitted(_run_id(source_run_id), path))
    _require(isinstance(state, dict) and isinstance(state.get("recovery_settlement"), dict), "source_not_settled")
    program = service.trials.programs.load(state["workflow_id"], state["program_id"])
    _require(path.read_bytes() == raw, "admission_changed")
    return old, state, program, admission, sha256(raw).hexdigest()


def _effect(session, reference, state, program, *, source_session):
    _require(isinstance(reference, str), "effect_path_invalid")
    path = _confined(session, reference)
    _require(path.parent == session / "workflow-effects" and path.suffix == ".json", "effect_path_invalid")
    raw = path.read_bytes()
    envelope = json.loads(raw.decode("utf-8"))
    _require(isinstance(envelope, dict) and envelope.get("contract_version") == "workflow_takeover_observation.v1",
             "effect_contract_invalid")
    effect, observation, frame = (envelope.get(key) for key in ("effect", "observation", "frame"))
    _require(isinstance(effect, dict) and isinstance(observation, dict) and isinstance(frame, dict), "effect_invalid")
    settlement = state["recovery_settlement"]
    expected = {"source_run_id": state["run_id"], "source_step_id": settlement["step_id"],
        "source_execution_request_id": settlement["execution_request_id"],
        "source_receipt_sha256": settlement["acceptance_receipt_sha256"],
        "source_settlement_sha256": _digest(settlement), "source_program_sha256": program["content_sha256"],
        "session_name": session.name, "evidence_ref": path.relative_to(session).as_posix()}
    _require(all(effect.get(key) == value for key, value in expected.items())
             and effect.get("source_action_executed") is settlement["action_executed"], "effect_source_mismatch")
    _require(frame.get("capture_id") == effect.get("capture_id") and frame.get("sha256") == effect.get("capture_sha256")
             and frame.get("window_identity") == effect.get("window_identity"), "effect_capture_mismatch")
    _verified_observation({"observation": frame}, session)
    source_receipt = source_session / "responses" / (state["pending"]["execution_request_id"] + ".json")
    effective, _ = resolve_execution_receipt(_read(source_receipt), source_receipt, state["pending"]["execution_request_id"])
    _require(_execution_identity(effective) == frame["window_identity"], "window_binding_not_verified")
    steps = [step for step in program["definition"]["steps"] if step["step_id"] == settlement["step_id"]]
    _require(len(steps) == 1 and execution_strategy(state) != "steps_only", "effect_requires_explicit_review")
    _require(path.read_bytes() == raw, "effect_changed")
    return deepcopy(envelope), sha256(raw).hexdigest(), steps[0]


def _verify_unexecuted(old, state):
    settlement = state["recovery_settlement"]
    eid = settlement["execution_request_id"]
    worker_path = old / "agent-commands" / (eid + ".json")
    acceptance_path = old / "responses" / (eid + ".json")
    worker_raw, acceptance_raw = worker_path.read_bytes(), acceptance_path.read_bytes()
    _require(sha256(worker_raw).hexdigest() == settlement["worker_terminal_sha256"]
             and sha256(acceptance_raw).hexdigest() == settlement["acceptance_receipt_sha256"],
             "unexecuted_source_changed")
    worker = json.loads(worker_raw.decode("utf-8"))
    acceptance = json.loads(acceptance_raw.decode("utf-8"))
    accepted = acceptance.get("result")
    _require(settlement["terminal_status"] == "cancelled" and settlement["action_executed"] is False
             and settlement["input_route_succeeded"] is False
             and isinstance(accepted, dict) and accepted.get("action_executed") is False
             and worker.get("status") == "cancelled" and worker.get("action_executed") is False
             and worker.get("dispatch_in_progress") is False and worker.get("dispatch_attempts") == []
             and worker.get("last_execution") is None and worker.get("pending_grounding") is None
             and all(value is False for value in _action_claims(accepted) + _action_claims(worker)),
             "unexecuted_input_not_proven")
    _require(worker_path.read_bytes() == worker_raw and acceptance_path.read_bytes() == acceptance_raw,
             "unexecuted_source_changed")


def _build(session, request_id, old, state, program, history, envelope, effect_sha256,
           *, resolution="adopt_success"):
    resolution = validate_resolution(resolution)
    _id(request_id, "request_id")
    effect, observation = envelope["effect"], envelope["observation"]
    step = next(item for item in program["definition"]["steps"] if item["step_id"] == effect["source_step_id"])
    outputs = {key: {"run_id": state["run_id"], "value": value} for key, value in history["outputs"].items()}
    result = verify_current_effect(step, inputs=state["inputs"], outputs=outputs, effect=effect, observation=observation)
    if resolution == "resume_unexecuted":
        _verify_unexecuted(old, state)
        _require(result["verdict"] == "failure" and result["reason"] == "observed_value_conflict",
                 "unexecuted_effect_not_proven")
        values, consumed = deepcopy(history["outputs"]), list(history["consumed_step_ids"])
        target, condition = step["step_id"], None
    else:
        values = {**history["outputs"], **{step["step_id"] + "." + key: value for key, value in result["outputs"].items()}}
        condition = _conditions(step["success_conditions"], state["inputs"], values, observation.get("values", {}))
        _require(result["verdict"] == "success" and condition == "true", "current_effect_not_success")
        consumed = history["consumed_step_ids"] + [step["step_id"]]
        target = step["branches"]["success"]
    _require(len(consumed) <= 256 and len(set(consumed)) == len(consumed), "consumed_step_conflict")
    _require(target not in consumed, "cyclic_success_branch")
    source = {"session_name": old.name, "run_id": state["run_id"], "step_id": step["step_id"],
              "execution_request_id": effect["source_execution_request_id"], "program_sha256": program["content_sha256"]}
    claim_id = _digest(list(source.values()))
    run_id = "trial-" + _digest([str(session), request_id, claim_id])
    imported = [{"step_id": row["step_id"], "verdict": row["verdict"], "outputs": deepcopy(row["outputs"]),
                 "judged_by": "recovery_history", "event_kind": "recovery_history_import",
                 "source": {"session_name": old.name, "run_id": state["run_id"], "history_index": index,
                            "verified_history_sha256": history["content_sha256"]},
                 "source_entry": deepcopy(row)} for index, row in enumerate(history["history"])]
    if resolution == "adopt_success":
        imported.append({"step_id": step["step_id"], "verdict": "success", "outputs": deepcopy(result["outputs"]),
                         "judged_by": "current_effect", "event_kind": "recovery_current_effect",
                         "source": source, "source_action_executed": effect["source_action_executed"],
                         "input_route_succeeded": None, "condition_result": condition, "verification": result})
    marker = {"contract_version": "workflow_recovery_import.v1", "claim_id": claim_id, "request_id": request_id,
        "source_session_name": old.name, "source_run_id": state["run_id"], "source_step_id": step["step_id"],
        "source_execution_request_id": effect["source_execution_request_id"],
        "source_program_sha256": program["content_sha256"], "source_settlement_sha256": effect["source_settlement_sha256"],
        "effect_evidence_ref": effect["evidence_ref"], "effect_evidence_sha256": effect_sha256,
        "verified_history_sha256": history["content_sha256"], "consumed_step_ids": consumed, "status": "prepared"}
    if resolution == "resume_unexecuted":
        marker.update(contract_version="workflow_recovery_import.v2", resolution=resolution)
    return {"run_id": run_id, "workflow_id": state["workflow_id"], "program_id": state["program_id"],
        "execution_strategy": execution_strategy(state), "project_snapshot_id": program["project_snapshot_id"],
        "start_step_id": state["start_step_id"], "current_step_id": target, "inputs": deepcopy(state["inputs"]),
        "outputs": values, "status": "ready" if target else "completed", "pending": None, "history": imported,
        "requests": {}, "prepare_requests": {}, "recovery_import": marker}


def prepare_recovery_import(library_root, session_dir, *, admission_request_id, source_run_id,
                            effect_evidence_ref, request_id, control_scope=None, control_request_id=None,
                            resolution="adopt_success"):
    resolution = validate_resolution(resolution)
    session, root = Path(session_dir).resolve(), Path(library_root).resolve()
    _require(_SESSION.fullmatch(session.name) and root == session.parent / "memory-library", "session_binding_invalid")
    with MemoryWorkspace(root) as library:
        old, state, program, admission, admission_sha = _source(library, session, admission_request_id, source_run_id)
    proof = inspect_session_input_terminal(old, root, admission_record_path=
        session.parent / "recovery-admissions" / (admission_request_id + ".json"))
    _require(proof == admission["preview"]["input_proof"], "source_catalog_changed")
    new_input_files = _new_input_files(session, root, control_scope=control_scope, control_request_id=control_request_id)
    with MemoryWorkspace(root) as library:
        history = verify_recovery_history(library, old, state, program, file_hashes=proof["files"],
            admission_chain=[session.parent / 'recovery-admissions' / (admission_request_id + '.json')])
        envelope, effect_sha, _ = _effect(session, effect_evidence_ref, state, program, source_session=old)
        prepared = {"trial_state": _build(session, request_id, old, state, program, history, envelope, effect_sha,
                                         resolution=resolution),
            "admission_request_id": admission_request_id, "admission_record_sha256": admission_sha,
            "source_files": deepcopy(proof["files"]), "new_input_files": new_input_files,
            "effect_files": {effect_evidence_ref: effect_sha,
                Path(_verified_observation({"observation": envelope["frame"]}, session)["image_path"])
                .relative_to(session).as_posix(): envelope["frame"]["sha256"]}}
        if control_scope is not None:
            prepared['control_scope'] = deepcopy(control_scope)
        _validate_prepared(TrialService(library, session), prepared, control_request_id=control_request_id)
    return deepcopy(prepared)


def _prepared_marker(prepared):
    _require(isinstance(prepared, dict) and set(prepared) - {'control_scope'} == {"trial_state", "admission_request_id",
             "admission_record_sha256", "source_files", "new_input_files", "effect_files"}, "prepared_invalid")
    state = prepared["trial_state"]
    _require(isinstance(state, dict) and isinstance(state.get("recovery_import"), dict), "prepared_trial_invalid")
    marker = state["recovery_import"]
    marker_resolution(marker)
    if 'control_scope' in prepared:
        from .workflow_takeover_controls import validate_scope
        scope = validate_scope(prepared['control_scope'])
        _require(scope == {'preview_request_id': marker['request_id'],
            'admission_request_id': prepared['admission_request_id'], 'source_run_id': marker['source_run_id']},
            'control_scope_mismatch')
    return marker


def _new_input_files(session, library_root, *, control_scope=None, control_request_id=None):
    if control_scope is not None:
        from .workflow_takeover_controls import scoped_input_files
        return scoped_input_files(session, library_root, control_scope, current_request_id=control_request_id)
    _require(control_request_id is None, 'control_scope_missing')
    # 导入账本会改变，但原命令及其回执必须保持准备时的原字节。
    proof = inspect_session_input_terminal(session, library_root)
    return {path: value for path, value in proof["files"].items()
            if not path.startswith(("workflow-trials/", "workflow-runners/"))}


def _validate_new_files(trials, prepared, *, control_request_id=None):
    _require(_new_input_files(trials.session, trials.session.parent / "memory-library",
             control_scope=prepared.get('control_scope'), control_request_id=control_request_id)
             == prepared["new_input_files"], "new_input_changed")
    files = prepared["effect_files"]
    marker = prepared["trial_state"]["recovery_import"]
    _require(isinstance(files, dict) and len(files) == 2
             and files.get(marker["effect_evidence_ref"]) == marker["effect_evidence_sha256"], "effect_files_invalid")
    for relative, digest in files.items():
        _require(isinstance(relative, str) and isinstance(digest, str) and _HASH.fullmatch(digest), "effect_files_invalid")
        _require(sha256(_confined(trials.session, relative).read_bytes()).hexdigest() == digest, "effect_changed")


def _validate_prepared(trials, prepared, *, control_request_id=None):
    marker = _prepared_marker(prepared)
    state = prepared["trial_state"]
    old, source, program, admission, admission_sha = _source(trials.programs.library, trials.session,
        prepared["admission_request_id"], marker["source_run_id"])
    _require(admission_sha == prepared["admission_record_sha256"]
             and prepared["source_files"] == admission["preview"]["input_proof"]["files"], "prepared_source_changed")
    raw = _catalog(old)
    _require({relative: sha256(value).hexdigest() for relative, value in raw.items()} == prepared["source_files"],
             "prepared_source_changed")
    history = verify_recovery_history(trials.programs.library, old, source, program, file_hashes=prepared["source_files"],
        admission_chain=[trials.session.parent / 'recovery-admissions' / (prepared['admission_request_id'] + '.json')])
    envelope, effect_sha, _ = _effect(trials.session, marker["effect_evidence_ref"], source, program, source_session=old)
    expected_files = {marker["effect_evidence_ref"]: effect_sha,
        _confined(trials.session, envelope["frame"]["image_path"]).relative_to(trials.session).as_posix():
        envelope["frame"]["sha256"]}
    _require(prepared["effect_files"] == expected_files, "effect_files_invalid")
    expected = _build(trials.session, marker["request_id"], old, source, program, history, envelope, effect_sha,
                      resolution=marker_resolution(marker))
    _require(expected == state, "prepared_trial_mismatch")
    _require(_catalog(old) == raw, "prepared_source_changed")
    _validate_session_trials(trials, state['run_id'])
    _validate_new_files(trials, prepared, control_request_id=control_request_id)
    return marker


def _validate_session_trials(trials, imported_run_id):
    for existing in trials.root.glob('trial-*.json'):
        if existing.stem != imported_run_id:
            current = trials.status(existing.stem)
            _require(current.get('pending') is None and current.get('status') in {'completed', 'failed', 'cancelled'},
                     'session_has_other_trial')


def _claim_path(session, claim_id):
    _require(isinstance(claim_id, str) and _HASH.fullmatch(claim_id), "claim_id_invalid")
    directory = session.parent / "workflow-takeovers"
    path = directory / (claim_id + ".json")
    _require(directory.resolve().parent == session.parent and path.resolve().parent == directory.resolve(), "claim_path_invalid")
    return path


def ensure_session_takeover_ready(session_dir):
    session = Path(session_dir).resolve()
    directory = session.parent / "workflow-takeovers"
    if not directory.exists():
        return
    _require(directory.resolve().parent == session.parent, "claim_path_invalid")
    paths = list(directory.glob("*.json"))
    _require(len(paths) <= 4096, "claim_catalog_unbounded")
    for path in paths:
        _require(_HASH.fullmatch(path.stem) and path.resolve().parent == directory.resolve(), "claim_path_invalid")
        claim = _read(path)
        _require(claim.get("contract_version") == "workflow_takeover_claim.v1"
                 and claim.get("claim_id") == path.stem and claim.get("phase") in {"prepared", "importing", "ready"},
                 "claim_catalog_invalid")
        if claim.get("new_session_name") == session.name and claim["phase"] != "ready":
            raise ValueError("workflow_takeover_import_in_progress")


def validate_import_claim(state, session_dir, *, ready=True):
    marker = state.get("recovery_import")
    if marker is None:
        return None
    session = Path(session_dir).resolve()
    resolution = marker_resolution(marker)
    claim = _read(_claim_path(session, marker["claim_id"]))
    _require(claim.get("contract_version") == "workflow_takeover_claim.v1" and claim.get("claim_id") == marker["claim_id"]
             and claim.get("request_id") == marker["request_id"] and claim.get("new_run_id") == state["run_id"]
             and claim.get("new_session_name") == session.name and claim.get("recovery_import") == marker,
             "claim_binding_invalid")
    _require(claim.get("phase") == ("ready" if ready else "importing"), "claim_not_ready" if ready else "claim_not_importing")
    ids = marker["consumed_step_ids"]
    minimum = 0 if resolution == "resume_unexecuted" else 1
    _require(isinstance(ids, list) and minimum <= len(ids) <= 256
             and all(isinstance(value, str) and bool(value.strip()) for value in ids)
             and len(set(ids)) == len(ids), "consumed_step_conflict")
    _require(resolution != "resume_unexecuted" or marker["source_step_id"] not in ids, "consumed_step_conflict")
    prefix = state.get("history", [])[:len(ids)]
    _require([row.get("step_id") for row in prefix] == ids and _digest(prefix) == claim.get("imported_history_sha256"),
             "imported_history_changed")
    if not ready:
        _require(_digest(state) == claim.get("trial_state_sha256"), "imported_trial_changed")
    return claim


def validate_recovery_progress(library, session_dir, state):
    session = Path(session_dir).resolve()
    claim = validate_import_claim(state, session)
    prepared = claim["prepared"]
    marker = _prepared_marker(prepared)
    _require(marker == state["recovery_import"], "initial_trial_changed")
    if len(state["history"]) == len(marker["consumed_step_ids"]):
        _require(state == prepared["trial_state"] and _digest(state) == claim["trial_state_sha256"],
                 "initial_trial_changed")
    program = TrialService(library, session).programs.load(state["workflow_id"], state["program_id"])
    raw = _catalog(session)
    verified = verify_recovery_history(library, session, state, program,
        file_hashes={relative: sha256(value).hexdigest() for relative, value in raw.items()})
    _require(_catalog(session) == raw, "recovery_source_changed")
    return verified


def import_recovery_trial(trials, claim_id, request_id, *, control_request_id=None):
    path = _claim_path(trials.session, claim_id)
    claim = _read(path)
    _require(claim.get("request_id") == request_id, "request_conflict")
    prepared = claim.get("prepared")
    _validate_prepared(trials, prepared, control_request_id=control_request_id)
    state = deepcopy(prepared["trial_state"])
    validate_import_claim(state, trials.session, ready=False)
    _validate_session_trials(trials, state['run_id'])
    target = trials._path(state["run_id"])
    if target.exists():
        _require(trials.status(state["run_id"]) == state, "imported_trial_changed")
    else:
        _write(target, state)
    index_path = trials.root / "requests.json"
    index = _read(index_path) if index_path.exists() else {}
    entry = {"request_sha256": _digest([claim_id, state["run_id"]]), "run_id": state["run_id"]}
    _require(request_id not in index or index[request_id] == entry, "request_conflict")
    index[request_id] = entry
    _write(index_path, index)
    return state


def commit_recovery_import(trials, runner, prepared, *, mode="until_wait", vision_capabilities=None, control_request_id=None):
    _require(runner.session == trials.session and runner.library_root == trials.session.parent / "memory-library",
             "runner_binding_invalid")
    _require(mode in {"single", "until_wait"}, "runner_mode_invalid")
    if vision_capabilities is not None:
        from app.vision.recognition_source import ClientVisionCapabilities
        vision_capabilities = ClientVisionCapabilities.model_validate(vision_capabilities).model_dump(exclude_none=True)
    marker = _prepared_marker(prepared)
    path = _claim_path(trials.session, marker["claim_id"])
    state = prepared["trial_state"]
    expected = {"contract_version": "workflow_takeover_claim.v1", "claim_id": marker["claim_id"],
        "request_id": marker["request_id"], "new_session_name": trials.session.name, "new_run_id": state["run_id"],
        "recovery_import": deepcopy(marker), "trial_state_sha256": _digest(state),
        "imported_history_sha256": _digest(state["history"]), "prepared": deepcopy(prepared),
        "mode": mode, "vision_capabilities": deepcopy(vision_capabilities)}
    with command_queue_lock(trials.session), _exclusive(path.parent / "claims.lock"):
        if path.exists():
            claim = _read(path)
            _require({key: value for key, value in claim.items() if key != "phase"} == expected
                     and claim.get("phase") in {"prepared", "importing", "ready"}, "claim_conflict")
        else:
            _validate_prepared(trials, prepared, control_request_id=control_request_id)
            claim = {**expected, "phase": "prepared"}
            _write(path, claim)
        if claim["phase"] == "ready":
            current = trials.status(state["run_id"])
            validate_import_claim(current, trials.session)
            runner_state = runner._load(state["run_id"])
            _require(runner_state is not None, "runner_missing")
            runner._recovery_guard(current, runner_state)
            return runner._snapshot(runner_state, trial=current)
        _validate_prepared(trials, prepared, control_request_id=control_request_id)
        if claim["phase"] == "prepared":
            claim["phase"] = "importing"
            _write(path, claim)
        trials.import_recovery(marker["claim_id"], marker["request_id"], control_request_id=control_request_id)
        snapshot = runner.import_recovery(state["run_id"], marker["request_id"], mode=mode,
            claim_id=marker["claim_id"], seen_steps=marker["consumed_step_ids"], vision_capabilities=vision_capabilities,
            trial_service=trials)
        old = trials.session.parent / marker["source_session_name"]
        _require(_SESSION.fullmatch(old.name)
                 and {relative: sha256(value).hexdigest() for relative, value in _catalog(old).items()}
                 == prepared["source_files"], "prepared_source_changed")
        _validate_new_files(trials, prepared, control_request_id=control_request_id)
        claim["phase"] = "ready"
        _write(path, claim)
        validate_import_claim(trials.status(state["run_id"]), trials.session)
        return snapshot


__all__ = ["prepare_recovery_import", "commit_recovery_import"]
