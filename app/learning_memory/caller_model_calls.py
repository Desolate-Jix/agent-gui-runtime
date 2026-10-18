"""接收调用方实际提供的逐调用计量，独立标注来源和覆盖范围。"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.model_usage import ModelUsage
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from .workflow_program import _id


Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
SCHEMA = "caller_model_call.v1"


class ModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Text
    model: Text
    call_id: Text
    source: Literal["agent_current", "agent_delegate", "external_api", "local"]
    phase: Literal["planning", "grounding", "verification"]
    status: Literal["success", "failure", "timeout", "cancelled"]
    usage: ModelUsage | None
    elapsed_ms: float | None = Field(default=None, strict=True, ge=0, allow_inf_nan=False)


def _identity(call):
    return sha256(canonical_json_bytes([call["provider"], call["call_id"]])).hexdigest()


def _path(session, identity):
    session = Path(session).resolve()
    path = session / "caller-model-calls" / (identity + ".json")
    if path.parent.resolve() != path.parent or path.resolve() != path:
        raise ValueError("caller_model_call_path_outside_session")
    return path


def _binding(library, session, scope):
    if not isinstance(scope, dict):
        raise ValueError("caller_model_call_binding_invalid")
    if scope.get("kind") == "workflow" and set(scope) == {"kind", "run_id", "step_id", "execution_request_id"}:
        from .workflow_trial import TrialService, _read, _receipt_state, _selection_context
        from .workflow_execution_strategy import command_step
        for key in ("run_id", "step_id", "execution_request_id"):
            _id(scope[key], key)
        trials = TrialService(library, session)
        state = trials.status(scope["run_id"])
        entries = list(state["history"]) + ([state["pending"]] if state["pending"] else [])
        matches = [item for item in entries if item["step_id"] == scope["step_id"]
                   and item["execution_request_id"] == scope["execution_request_id"]]
        if len(matches) != 1:
            raise ValueError("caller_model_call_binding_mismatch")
        command_path = Path(session) / "commands" / (scope["execution_request_id"] + ".json")
        command = _read(command_path)
        if "suggested_command" in matches[0] and command != matches[0]["suggested_command"]:
            raise ValueError("caller_model_call_command_binding_mismatch")
        receipt_path = Path(session) / "responses" / command_path.name
        receipt = _read(receipt_path)
        context = None
        if (command.get("request") or {}).get("selection_intent") == "ensure_selected":
            # 历史上下文只用该步之前已确认的输出，不绑定后来产生的值。
            earlier = {}
            for entry in state["history"]:
                if entry is matches[0]:
                    break
                if entry.get("verdict") == "success":
                    earlier.update({entry["step_id"] + "." + key: value for key, value in entry["outputs"].items()})
            prior = {**state, "outputs": earlier}
            program = trials.programs.load(state["workflow_id"], state["program_id"])
            steps = [step for step in program["definition"]["steps"] if step["step_id"] == scope["step_id"]]
            if len(steps) != 1:
                raise ValueError("caller_model_call_binding_mismatch")
            context = _selection_context(prior, command_step(library, steps[0], prior), command, scope["execution_request_id"])
        _receipt_state(receipt, receipt_path, scope["execution_request_id"], command, expected_context=context)
        digest = sha256(receipt_path.read_bytes()).hexdigest()
        if "receipt_sha256" in matches[0] and matches[0]["receipt_sha256"] != digest:
            raise ValueError("caller_model_call_receipt_binding_mismatch")
        return {"evidence_ref": str(receipt_path.relative_to(Path(session))).replace("\\", "/"),
                "sha256": digest}
    if scope.get("kind") == "synthesis" and set(scope) == {"kind", "synthesis_id", "source_sha256", "reply_request_id"}:
        from .learning_synthesis import LearningSynthesisService, _read_reply
        _id(scope["reply_request_id"], "reply_request_id")
        service = LearningSynthesisService(library, session)
        original = service._request(scope["synthesis_id"])["request"]
        if scope["source_sha256"] != original["source_sha256"]:
            raise ValueError("caller_model_call_source_binding_mismatch")
        directory = service._directory(scope["synthesis_id"])
        path = directory / "attempts" / (scope["reply_request_id"] + ".json")
        attempt = path.exists()
        if not attempt:
            path = directory / "completion.json"
        reply = _read_reply(path, original, attempt=attempt)
        if reply["reply_request_id"] != scope["reply_request_id"]:
            raise ValueError("caller_model_call_reply_binding_mismatch")
        return {"evidence_ref": str(path.relative_to(library._artifact_root)).replace("\\", "/"),
                "sha256": sha256(path.read_bytes()).hexdigest()}
    raise ValueError("caller_model_call_binding_invalid")


def record_model_call(library, session, *, scope, model_call):
    call = ModelCall.model_validate(model_call).model_dump(mode="json", exclude_none=False)
    binding = _binding(library, session, scope)
    if scope["kind"] == "synthesis" and call["phase"] != "planning":
        raise ValueError("caller_model_call_synthesis_phase_invalid")
    value = {"schema": SCHEMA, "scope": scope, "model_call": call, "binding": binding,
             "provenance": "caller_reported", "independently_verified": False}
    _verify_saved_binding(session, value, getattr(library, "_artifact_root", None))
    value["content_sha256"] = sha256(canonical_json_bytes(value)).hexdigest()
    path = _path(session, _identity(call))
    if path.exists() and json.loads(path.read_text(encoding="utf-8")) != value:
        raise ValueError("caller_model_call_conflict")
    _write_immutable(path, canonical_json_bytes(value) + b"\n")
    return {"status": "recorded", "provenance": "caller_reported", "input_executed": False,
            "evidence_ref": str(path.relative_to(Path(session).resolve())).replace("\\", "/")}


def _verify_saved_binding(session, value, artifact_root):
    scope, binding = value["scope"], value.get("binding")
    if not isinstance(binding, dict) or set(binding) != {"evidence_ref", "sha256"}:
        raise ValueError("caller_model_call_evidence_invalid")
    if scope.get("kind") == "workflow" and set(scope) == {"kind", "run_id", "step_id", "execution_request_id"}:
        for key in ("run_id", "step_id", "execution_request_id"):
            _id(scope[key], key)
        root = Path(session).resolve()
        allowed = {"responses/" + scope["execution_request_id"] + ".json"}
    elif scope.get("kind") == "synthesis" and set(scope) == {"kind", "synthesis_id", "source_sha256", "reply_request_id"}:
        if artifact_root is None:
            raise ValueError("caller_model_call_artifact_root_required")
        for key in ("synthesis_id", "reply_request_id"):
            _id(scope[key], key)
        root = Path(artifact_root).resolve()
        prefix = "desktop-review/learning-synthesis/" + scope["synthesis_id"] + "/"
        allowed = {prefix + "completion.json", prefix + "attempts/" + scope["reply_request_id"] + ".json"}
    else:
        raise ValueError("caller_model_call_binding_invalid")
    if not isinstance(binding["evidence_ref"], str) or binding["evidence_ref"] not in allowed:
        raise ValueError("caller_model_call_evidence_mismatch")
    path = root / binding["evidence_ref"]
    if path.resolve() != path or sha256(path.read_bytes()).hexdigest() != binding["sha256"]:
        raise ValueError("caller_model_call_evidence_changed")


def load_call_summary(session, selector, *, artifact_root=None):
    rows = []
    try:
        directory = _path(session, "probe").parent
        if not directory.exists():
            return None
        for path in sorted(directory.glob("*.json")):
            _path(session, path.stem)
            value = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or value.get("schema") != SCHEMA
                    or value.get("provenance") != "caller_reported" or value.get("independently_verified") is not False
                    or not isinstance(value.get("scope"), dict)):
                raise ValueError("caller_model_call_record_invalid")
            expected_hash = value.pop("content_sha256", None)
            if expected_hash != sha256(canonical_json_bytes(value)).hexdigest():
                raise ValueError("caller_model_call_record_changed")
            call = ModelCall.model_validate(value["model_call"])
            if path.stem != _identity(call.model_dump(mode="json")):
                raise ValueError("caller_model_call_record_identity_mismatch")
            if all(value["scope"].get(key) == item for key, item in selector.items()):
                _verify_saved_binding(session, value, artifact_root)
                rows.append(call)
        if not rows:
            return None
        counts = {phase: sum(row.phase == phase for row in rows) for phase in ("planning", "grounding", "verification")}
        usage = None
        if all(row.usage is not None for row in rows):
            usage = {key: sum(row.usage.counts()[key] for row in rows)
                     for key in ("input_tokens", "output_tokens", "total_tokens")}
        return {"status": "available", "coverage": "caller_reported_partial", "independently_verified": False,
                "model_calls": {**counts, "total": len(rows)}, "usage": usage,
                "usage_observed_calls": sum(row.usage is not None for row in rows),
                "status_counts": dict(Counter(row.status for row in rows)),
                "elapsed_ms_sum": sum(row.elapsed_ms for row in rows) if all(row.elapsed_ms is not None for row in rows) else None}
    except (OSError, ValueError, KeyError) as error:
        return {"status": "unavailable", "coverage": "caller_reported_partial", "independently_verified": False,
                "reason": "caller_model_call_records_or_source_evidence_invalid",
                "error_type": type(error).__name__}
