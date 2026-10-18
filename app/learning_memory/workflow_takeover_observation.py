"""新宿主采集原步骤当前效果，不产生执行回执或推进账本。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.core.local_input_policy import _local_operator_step_scope
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from app.execution.session_input_terminal import inspect_session_input_terminal
from .receipt_adapter import resolve_execution_receipt
from .verification_observation import read_step_observation
from .workflow_execution_strategy import execution_strategy
from .workflow_program import _id
from .workflow_recovery_import import _source, _effect, _digest, _require, _SESSION
from .workflow_runner import _exclusive
from .workflow_trial import _read, _execution_identity, _verified_observation
from .workflow_verification import verify_current_effect
from .workspace import MemoryWorkspace


def collect_takeover_effect(coordinator, *, session_dir, admission_request_id, source_run_id, request_id):
    """返回 {envelope, evidence_ref, evidence_sha256}；不支持时返回 verification_required。"""
    _id(request_id, "request_id")
    session = Path(session_dir).resolve()
    root = Path(coordinator._memory_library_root).resolve()
    _require(_SESSION.fullmatch(session.name) and root == session.parent / "memory-library", "session_binding_invalid")
    directory = session / "workflow-effects"
    _require(directory.resolve().parent == session, "effect_path_invalid")
    reference = "workflow-effects/" + request_id + ".json"
    artifact = session / reference
    with _exclusive(directory / "observations.lock"):
        with MemoryWorkspace(root) as library:
            old, state, program, admission, admission_sha = _source(library, session, admission_request_id, source_run_id)
        proof_path = session.parent / "recovery-admissions" / (admission_request_id + ".json")
        proof = inspect_session_input_terminal(old, root, admission_record_path=proof_path)
        _require(proof == admission["preview"]["input_proof"], "source_catalog_changed")
        settlement = state["recovery_settlement"]
        step = next(item for item in program["definition"]["steps"] if item["step_id"] == settlement["step_id"])
        rule, read_spec = step.get("verification"), step.get("read_spec")
        reason = ("steps_only_agent_review_required" if execution_strategy(state) == "steps_only" else
                  "agent_judgment_required" if (rule and rule["kind"] == "agent_judgment") or not (rule or read_spec) else None)
        method = None if reason else (read_spec["method"] if read_spec else "uia_value" if rule["kind"] == "field_equals"
                  else "presence" if rule["kind"] in {"target_present", "target_absent"} else "visible_text")
        if reason or method == "agent_read":
            return {"status": "verification_required", "reason": reason or "agent_read_required",
                    "automatic_retry_allowed": False}
        if artifact.exists():
            envelope, digest, _ = _effect(session, reference, state, program, source_session=old)
            _require(envelope["effect"]["request_id"] == request_id
                     and envelope.get("admission_request_id") == admission_request_id
                     and envelope.get("admission_record_sha256") == admission_sha, "effect_request_conflict")
            outputs = {key: {"run_id": source_run_id, "value": value} for key, value in state["outputs"].items()}
            verified = verify_current_effect(step, inputs=state["inputs"], outputs=outputs,
                effect=envelope["effect"], observation=envelope["observation"])
            _require(verified == envelope.get("verification") and envelope["observation"].get("complete") is True,
                     "effect_verification_changed")
            return {"envelope": envelope, "evidence_ref": reference, "evidence_sha256": digest}
        receipt_path = old / "responses" / (settlement["execution_request_id"] + ".json")
        effective, _ = resolve_execution_receipt(_read(receipt_path), receipt_path, settlement["execution_request_id"])
        identity = _execution_identity(effective)
        _require(isinstance(identity, dict), "window_binding_not_verified")

        def observe():
            with _local_operator_step_scope():
                return read_step_observation(coordinator,
                    target={"handle": identity["handle"], "process_id": identity["process_id"]},
                    selector=(read_spec or rule)["target"], method=method)

        started = perf_counter_ns()
        live = coordinator._owner.call(observe)
        ended = perf_counter_ns()
        frame = live.get("frame")
        _require(isinstance(frame, dict) and frame.get("window_identity") == identity
                 and live.get("window_identity") == identity, "window_binding_not_verified")
        _verified_observation({"observation": frame}, session)
        _require(live.get("complete") is True and isinstance(live.get("scope_id"), str) and live["scope_id"]
                 and isinstance(live.get("source"), str) and live["source"]
                 and isinstance(live.get("values"), dict)
                 and live.get("capture_id") == frame.get("capture_id")
                 and live.get("capture_sha256") == frame.get("sha256"), "observation_incomplete")
        effect = {"contract_version": "workflow_current_effect.v1", "source_run_id": source_run_id,
            "source_step_id": step["step_id"], "source_execution_request_id": settlement["execution_request_id"],
            "source_receipt_sha256": settlement["acceptance_receipt_sha256"],
            "source_settlement_sha256": _digest(settlement), "source_program_sha256": program["content_sha256"],
            "source_action_executed": settlement["action_executed"], "session_name": session.name,
            "request_id": request_id, "capture_id": frame["capture_id"], "capture_sha256": frame["sha256"],
            "window_identity": deepcopy(identity), "scope_id": live["scope_id"], "evidence_ref": reference}
        observation = {key: deepcopy(effect[key]) for key in ("session_name", "request_id", "capture_id",
            "capture_sha256", "window_identity", "scope_id", "evidence_ref")}
        observation.update(step_id=step["step_id"], complete=True, source=live["source"], values=deepcopy(live["values"]))
        outputs = {key: {"run_id": source_run_id, "value": value} for key, value in state["outputs"].items()}
        verification = verify_current_effect(step, inputs=state["inputs"], outputs=outputs,
                                             effect=effect, observation=observation)
        envelope = {"contract_version": "workflow_takeover_observation.v1", "effect": effect,
            "observation": observation, "frame": deepcopy(frame), "native_evidence": deepcopy(live["evidence"]),
            "measurement": {"started_ns": started, "ended_ns": ended}, "verification": verification,
            "admission_request_id": admission_request_id, "admission_record_sha256": admission_sha}
        with MemoryWorkspace(root) as library:
            current = _source(library, session, admission_request_id, source_run_id)
            _require(current == (old, state, program, admission, admission_sha), "source_changed")
        _require(inspect_session_input_terminal(old, root, admission_record_path=proof_path) == proof, "source_catalog_changed")
        _verified_observation({"observation": frame}, session)
        raw = canonical_json_bytes(envelope)
        _write_immutable(artifact, raw)
        return {"envelope": deepcopy(envelope), "evidence_ref": reference, "evidence_sha256": sha256(raw).hexdigest()}
