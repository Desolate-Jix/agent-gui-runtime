"""只读核验原成功历史的来源，不授予输入或跨会话接管。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.desktop_review.external_mapping import canonical_json_bytes
from .receipt_adapter import resolve_execution_receipt
from .workflow_execution_strategy import command_step, execution_strategy
from .workflow_program import WorkflowProgramService, _id, _type
from .workflow_target_bindings import _outputs
from .workflow_trial import _actual_action_executed, _command, _conditions, _execution_identity, _receipt_state, _selection_context, _verified_observation
from .workflow_verification import verify_step


def _require(value, code):
    if not value:
        raise ValueError("workflow_recovery_history_" + code)


def _digest(value):
    return sha256(canonical_json_bytes(value)).hexdigest()


def verify_recovery_history(library, session_dir, state, program, *, file_hashes, admission_chain=None):
    """所有来源须绑定准入原字节；Agent 审核来源不等于独立准确率证明。"""
    return _verify_history(library, session_dir, state, program, file_hashes=file_hashes,
                           visited=set(), depth=0, external_snapshots={}, admission_chain=admission_chain)


def _verify_history(library, session_dir, state, program, *, file_hashes, visited, depth, external_snapshots,
                    admission_chain=None):
    session = Path(session_dir).resolve()
    _require(isinstance(state, dict) and isinstance(program, dict) and isinstance(file_hashes, dict), "input_invalid")
    identity = (str(session), state.get("run_id"))
    _require(depth < 16 and identity not in visited, "ancestry_cycle_or_depth")
    visited = visited | {identity}
    snapshots = {}

    def snapshot(path):
        path = Path(path)
        path = (path if path.is_absolute() else session / path).resolve()
        _require(path.is_relative_to(session), "evidence_outside_session")
        relative = path.relative_to(session).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ValueError("workflow_recovery_history_source_unavailable") from error
        _require(file_hashes.get(relative) == sha256(raw).hexdigest(), "source_hash_mismatch")
        _require(path not in snapshots or snapshots[path] == raw, "source_changed")
        snapshots[path] = raw
        return raw

    def read(path):
        try:
            value = json.loads(snapshot(path).decode("utf-8"),
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
        except (UnicodeError, ValueError) as error:
            raise ValueError("workflow_recovery_history_source_invalid") from error
        _require(isinstance(value, dict), "source_invalid")
        return value

    run_id = _id(state.get("run_id"), "run_id")
    original = read("workflow-trials/" + run_id + ".json")
    _require(original == state, "trial_mismatch")
    loaded = WorkflowProgramService(library).load(state["workflow_id"], state["program_id"])
    _require(loaded == program and program["program_id"] == state["program_id"]
             and program["project_snapshot_id"] == state["project_snapshot_id"], "program_mismatch")
    history = state.get("history")
    _require(isinstance(history, list) and len(history) <= 256, "history_invalid")
    steps = {step["step_id"]: step for step in program["definition"]["steps"]}
    wrapped = _outputs(state, program)
    consumed, earlier, expected_step = [], {}, state["start_step_id"]
    ancestry, prefix_length = None, 0
    if state.get("recovery_import") is not None:
        imported, ancestry = _verify_import(library, session, state, program, visited=visited,
                                           depth=depth, external_snapshots=external_snapshots,
                                           admission_chain=admission_chain)
        prefix_length = len(imported["history"])
        consumed = list(imported["recovery_import"]["consumed_step_ids"])
        earlier = deepcopy(imported["outputs"])
        expected_step = imported["current_step_id"]
    execution_ids = set()
    requests = state.get("requests")
    _require(isinstance(requests, dict), "requests_invalid")

    def request_match(entry, values):
        digest = _digest(values)
        review = entry.get("review_request")
        if review is not None:
            _require(isinstance(review, dict) and set(review) == {"request_id", "submitted_outputs"}, "review_request_invalid")
            request_id = _id(review.get("request_id"), "request_id")
            _require(requests.get(request_id) == digest, "request_hash_mismatch")
            return request_id
        matches = [key for key, value in requests.items() if value == digest]
        _require(len(matches) == 1, "request_hash_mismatch")
        return _id(matches[0], "request_id")

    for entry in history[prefix_length:]:
        _require(isinstance(entry, dict), "entry_invalid")
        origin = entry.get("judged_by")
        _require(origin in {"agent", "rule", "runtime"}, "origin_not_supported")
        if origin == "runtime":
            _require(entry.get("runtime_reason") == "original_execution_failed", "origin_not_supported")
        step_id = entry.get("step_id")
        _require(step_id in steps and step_id not in consumed and step_id == expected_step, "step_invalid")
        _require(execution_strategy(entry) == execution_strategy(state), "strategy_mismatch")
        consumed.append(step_id)
        step = steps[step_id]
        eid = _id(entry.get("execution_request_id"), "execution_request_id")
        _require(eid not in execution_ids, "execution_id_duplicate")
        execution_ids.add(eid)
        command = read("commands/" + eid + ".json")
        base = deepcopy(command)
        capabilities = base.pop("vision_capabilities", None)
        if capabilities is not None:
            from app.vision.recognition_source import ClientVisionCapabilities
            ClientVisionCapabilities.model_validate(capabilities)
        prior_state = {**state, "outputs": deepcopy(earlier)}
        compiled = _command(command_step(library, step, prior_state), state["inputs"], earlier)
        _require(base == compiled, "command_mismatch")
        receipt_path = session / "responses" / (eid + ".json")
        receipt = read(receipt_path)
        receipt_hash = sha256(snapshots[receipt_path]).hexdigest()
        _require(entry.get("receipt_sha256") == receipt_hash, "receipt_hash_mismatch")
        terminal_snapshot = None
        if (receipt.get("result") or {}).get("contract_version") == "agent_command.v1":
            terminal_snapshot = read("agent-commands/" + eid + ".json")
        effective, _ = resolve_execution_receipt(receipt, receipt_path, eid, terminal_snapshot=terminal_snapshot)
        if command["kind"] == "read_text":
            capture = effective.get("observation") or (effective.get("result") or {}).get("capture") or {}
            snapshot(capture.get("image_path", ""))
        context = _selection_context(prior_state, command_step(library, step, prior_state), command, eid)
        dispatched, terminal, read_observation = _receipt_state(receipt, receipt_path, eid, command,
                                                               terminal_snapshot=terminal_snapshot, expected_context=context)
        _require(entry.get("terminal_receipt") == terminal, "terminal_mismatch")
        actual = _actual_action_executed(effective.get("result"), terminal) if context is not None else None
        route = dispatched and actual is True if context is not None else dispatched
        _require(entry.get("input_route_succeeded") is (route if read_observation is None else None), "route_mismatch")
        if context is not None:
            _require(entry.get("command_succeeded") is dispatched and entry.get("action_executed") is actual, "selection_input_fact_mismatch")
            if dispatched:
                proof = effective["result"]["row_selection_proof"]
                _require(entry.get("selection_proof_sha256") == proof["sha256"], "selection_proof_mismatch")
                for stage in ("before", "after"):
                    snapshot(proof[stage]["frame"]["image_path"])
            else:
                _require("selection_proof_sha256" not in entry, "selection_proof_mismatch")
        if read_observation is not None:
            _require(entry.get("read_observation") == read_observation, "read_observation_mismatch")
        if origin == "agent":
            verdict = entry.get("agent_verdict")
            observations = entry.get("observations")
            review = entry.get("review_request")
            if review is not None:
                _require(isinstance(review, dict) and set(review) == {"request_id", "submitted_outputs"}, "review_request_invalid")
                submitted = review["submitted_outputs"]
                request_match(entry, [eid, verdict, observations, submitted])
            elif entry.get("verdict") == "success":
                submitted = entry.get("outputs")
                request_match(entry, [eid, verdict, observations, submitted])
            else:
                candidates = []
                for name in file_hashes:
                    if not name.startswith("commands/") or not name.endswith(".json"):
                        continue
                    control = read(name)
                    request = control.get("request") or {}
                    if (control.get("kind") == "learning_workflow" and request.get("action") == "review"
                            and request.get("run_id") == run_id and request.get("execution_request_id") == eid
                            and request.get("verdict") == verdict and request.get("observations") == observations):
                        request_id = Path(name).stem
                        values = request.get("outputs")
                        if requests.get(request_id) == _digest([eid, verdict, observations, values]):
                            candidates.append(values)
                _require(len(candidates) == 1, "submitted_outputs_unavailable")
                submitted = candidates[0]
        elif origin == "runtime":
            _require(receipt.get("status") == "failed" or (terminal is not None and terminal["status"] == "failed"),
                     "runtime_failure_unproven")
            original_error = receipt if receipt.get("status") == "failed" else terminal_snapshot
            _require(isinstance(original_error, dict), "runtime_failure_unproven")
            action = _actual_action_executed(effective.get("result"), terminal)
            _require(type(action) is bool, "runtime_action_unknown")
            request_id = _id(entry.get("runtime_settlement_request_id"), "request_id")
            result = {"source": "runtime", "verdict": "failure", "reason": "original_execution_failed",
                      "terminal_status": "failed", "action_executed": action,
                      "runtime_settlement_request_id": request_id,
                      "error_type": original_error.get("error_type"), "error": original_error.get("error")}
            _require(entry.get("review_request") == {"request_id": request_id, "submitted_outputs": {}},
                     "review_request_invalid")
            _require(requests.get(request_id) == _digest([eid, "failure", {}, {}, result]), "request_hash_mismatch")
            expected = {"step_id": step_id, "execution_request_id": eid,
                "review_request": {"request_id": request_id, "submitted_outputs": {}},
                "execution_strategy": execution_strategy(state), "receipt_sha256": receipt_hash,
                "terminal_receipt": terminal, "input_route_succeeded": dispatched if read_observation is None else None,
                "verdict": "failure", "condition_result": _conditions(step["success_conditions"], state["inputs"], earlier, {}),
                "judged_by": "runtime", "observations": {}, "outputs": {}, "runtime_verdict": "failure",
                "action_executed": action, "runtime_reason": "original_execution_failed",
                "runtime_settlement_request_id": request_id, "terminal_status": "failed"}
            if context is not None:
                expected.update(command_succeeded=dispatched, input_route_succeeded=route)
            if read_observation is not None:
                expected["read_observation"] = read_observation
            for key in ("error_type", "error"):
                if result[key] is not None:
                    expected[key] = result[key]
            _require(entry == expected, "runtime_entry_mismatch")
            verdict, observations, submitted = "failure", {}, {}
        else:
            result = entry.get("verification")
            _require(isinstance(result, dict) and result.get("source") == "rule", "verification_invalid")
            observation = result.get("observations")
            _require(isinstance(observation, dict), "verification_invalid")
            reference = observation.get("evidence_ref")
            _require(isinstance(reference, str) and (session / reference).resolve().is_relative_to(session / "workflow-observations"), "evidence_outside_session")
            envelope = read(reference)
            _require(envelope.get("contract_version") == "workflow_observation.v1"
                     and envelope.get("observation") == observation and envelope.get("source_receipt_sha256") == receipt_hash
                     and envelope.get("terminal_receipt") == terminal, "envelope_mismatch")
            normalized, frame = envelope.get("receipt"), envelope.get("frame")
            _require(isinstance(normalized, dict) and isinstance(frame, dict), "envelope_invalid")
            snapshot(frame.get("image_path", ""))
            _verified_observation({"observation": frame}, session)
            request_id = _id(observation.get("request_id"), "request_id")
            ids = {"run_id": run_id, "step_id": step_id, "request_id": request_id, "execution_request_id": eid}
            _require(all(normalized.get(key) == value for key, value in ids.items())
                     and normalized.get("window_identity") == _execution_identity(effective)
                     and frame.get("window_identity") == normalized.get("window_identity")
                     and normalized.get("post_capture_id") == frame.get("capture_id")
                     and normalized.get("post_capture_sha256") == frame.get("sha256")
                     and normalized.get("status") == ("completed" if dispatched else "failed")
                     and normalized.get("action_executed") is (actual if context is not None else dispatched and command["kind"] != "read_text")
                     and (session / str(normalized.get("evidence_ref", ""))).resolve() == receipt_path, "normalized_binding_mismatch")
            if context is not None and dispatched:
                _require(normalized.get("row_selection_proof") == effective["result"].get("row_selection_proof"), "normalized_selection_proof_mismatch")
            else:
                _require("row_selection_proof" not in normalized, "normalized_selection_proof_mismatch")
            result_outputs = {key: {"run_id": run_id, "value": value} for key, value in earlier.items()}
            computed = verify_step(step, inputs=state["inputs"], outputs=result_outputs,
                                   receipt=normalized, observation=observation)
            _require(computed == result, "verification_mismatch")
            verdict, observations, submitted = result["verdict"], observation.get("values", {}), result["outputs"]
            _require(entry.get("rule_verdict") == verdict and entry.get("observations") == observations, "verification_mismatch")
            _require(requests.get(request_id) == _digest([eid, verdict, observations, submitted, result]), "request_hash_mismatch")
            if entry.get("review_request") is not None:
                _require(entry["review_request"] == {"request_id": request_id, "submitted_outputs": submitted}, "review_request_invalid")
        _require(verdict in {"success", "failure", "uncertain"} and isinstance(observations, dict)
                 and isinstance(submitted, dict), "review_invalid")
        declarations = {row["name"]: row["type"] for row in step["outputs"]}
        _require(not set(submitted) - set(declarations) and all(_type(value, declarations[name]) for name, value in submitted.items()), "outputs_invalid")
        if verdict == "success":
            _require(dispatched and set(submitted) == set(declarations), "success_unproven")
        condition = _conditions(step["success_conditions"], state["inputs"],
                                {**earlier, **{step_id + "." + key: value for key, value in submitted.items()}}, observations)
        effective_verdict = verdict if verdict != "success" else "success" if condition == "true" else "failure" if condition == "false" else "uncertain"
        _require(entry.get("condition_result") == condition and entry.get("verdict") == effective_verdict
                 and entry.get("outputs") == (submitted if effective_verdict == "success" else {}), "verdict_mismatch")
        if effective_verdict == "success":
            earlier.update({step_id + "." + key: value for key, value in submitted.items()})
        expected_step = step_id if effective_verdict == "uncertain" else step["branches"][effective_verdict]
    _require(state.get("current_step_id") == expected_step, "current_step_mismatch")
    _require(earlier == {key: value["value"] for key, value in wrapped.items()}, "outputs_mismatch")
    _require(WorkflowProgramService(library).load(state["workflow_id"], state["program_id"]) == program, "program_changed")
    _require(all(path.read_bytes() == raw for path, raw in snapshots.items()), "source_changed")
    _require(all(path.read_bytes() == raw for path, raw in external_snapshots.items()), "ancestor_changed")
    result = {"contract_version": "workflow_recovery_history.v1", "source_session_name": session.name,
              "source_run_id": run_id, "source_program_sha256": program["content_sha256"],
              "history": deepcopy(history), "outputs": deepcopy(earlier), "consumed_step_ids": consumed,
              "files": {path.relative_to(session).as_posix(): sha256(raw).hexdigest() for path, raw in snapshots.items()}}
    if ancestry is not None:
        result["ancestry"] = ancestry
    return {**result, "content_sha256": _digest(result)}


def _verify_import(library, session, state, program, *, visited, depth, external_snapshots, admission_chain):
    # 导入前缀只核对原来源事件，不把祖先执行 ID 改成当前执行。
    from .workflow_recovery_import import (_source, _effect, _build, _prepared_marker,
                                           _claim_path, validate_import_claim, _ADMISSION)
    from app.execution.session_input_terminal import _catalog

    def fixed(path):
        path = Path(path).resolve()
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ValueError("workflow_recovery_history_ancestor_unavailable") from error
        _require(path not in external_snapshots or external_snapshots[path] == raw, "ancestor_changed")
        external_snapshots[path] = raw
        return raw

    marker = state["recovery_import"]
    _require(isinstance(marker, dict), "import_marker_invalid")
    claim_path = _claim_path(session, marker.get("claim_id"))
    claim_raw = fixed(claim_path)
    claim = json.loads(claim_raw.decode("utf-8"))
    _require(validate_import_claim(state, session) == claim, "claim_changed")
    prepared = claim.get("prepared")
    _require(_prepared_marker(prepared) == marker, "import_marker_mismatch")
    _require(isinstance(prepared["admission_request_id"], str)
             and _ADMISSION.fullmatch(prepared["admission_request_id"]), "admission_id_invalid")
    admission_path = session.parent / "recovery-admissions" / (prepared["admission_request_id"] + ".json")
    _require(admission_path.resolve().parent == (session.parent / "recovery-admissions").resolve(), "admission_path_invalid")
    admission_raw = fixed(admission_path)
    chain = [] if admission_chain is None else admission_chain
    _require(isinstance(chain, (list, tuple)) and len(chain) <= 16, "admission_chain_invalid")
    normalized_chain = []
    for value in chain:
        path = Path(value).resolve()
        _require(path.parent == (session.parent / "recovery-admissions").resolve()
                 and path.suffix == ".json" and _ADMISSION.fullmatch(path.stem), "admission_chain_invalid")
        fixed(path)
        normalized_chain.append(path)
    options = {"archived_admission_chain": normalized_chain} if normalized_chain else {}
    old, source, source_program, admission, admission_sha = _source(
        library, session, prepared["admission_request_id"], marker["source_run_id"], **options)
    _require(admission_raw == fixed(admission_path) and sha256(admission_raw).hexdigest() == admission_sha
             and admission_sha == prepared["admission_record_sha256"], "admission_changed")
    _require(old.name == marker["source_session_name"] and source_program == program,
             "import_program_or_parent_mismatch")
    files = prepared["source_files"]
    _require(files == admission["preview"]["input_proof"]["files"], "ancestor_catalog_mismatch")
    catalog = _catalog(old)
    _require({path: sha256(raw).hexdigest() for path, raw in catalog.items()} == files, "ancestor_catalog_mismatch")
    for relative, raw in catalog.items():
        _require(fixed(old / relative) == raw, "ancestor_changed")
    history = _verify_history(library, old, source, source_program, file_hashes=files,
                              visited=visited, depth=depth + 1, external_snapshots=external_snapshots,
                              admission_chain=[admission_path, *normalized_chain])
    reference = marker["effect_evidence_ref"]
    _require(isinstance(reference, str) and (session / reference).resolve().parent == session / "workflow-effects"
             and (session / reference).suffix == ".json", "effect_path_invalid")
    effect_raw = fixed(session / reference)
    envelope, effect_sha, _ = _effect(session, reference, source, source_program, source_session=old)
    _require(sha256(effect_raw).hexdigest() == effect_sha == marker["effect_evidence_sha256"], "effect_changed")
    image = Path(_verified_observation({"observation": envelope["frame"]}, session)["image_path"])
    image_raw = fixed(image)
    _require(prepared["effect_files"] == {reference: effect_sha,
        image.relative_to(session).as_posix(): sha256(image_raw).hexdigest()}, "effect_files_mismatch")
    from .workflow_recovery_resolution import marker_resolution
    imported = _build(session, marker["request_id"], old, source, source_program,
                      history, envelope, effect_sha, resolution=marker_resolution(marker))
    _require(imported == prepared["trial_state"] and marker == imported["recovery_import"]
             and _digest(imported) == claim.get("trial_state_sha256"), "imported_trial_mismatch")
    prefix = imported["history"]
    _require(state["history"][:len(prefix)] == prefix
             and _digest(prefix) == claim.get("imported_history_sha256"), "imported_prefix_mismatch")
    for key in ("run_id", "workflow_id", "program_id", "execution_strategy", "project_snapshot_id", "start_step_id", "inputs"):
        _require(state.get(key) == imported.get(key), "import_binding_changed")
    _require(_catalog(old) == catalog, "ancestor_changed")
    _require(all(path.read_bytes() == raw for path, raw in external_snapshots.items()), "ancestor_changed")
    return imported, {"contract_version": "workflow_recovery_ancestry.v1",
        "source_session_name": old.name, "source_run_id": source["run_id"],
        "source_history_sha256": history["content_sha256"], "history": history,
        "claim_sha256": sha256(claim_raw).hexdigest(), "admission_sha256": admission_sha,
        "effect_sha256": effect_sha, "effect_frame_sha256": sha256(image_raw).hexdigest()}
