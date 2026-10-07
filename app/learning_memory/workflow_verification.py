"""使用当次终态回执和完整新观察判断有限的步骤结果。"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
import re


KINDS = frozenset({"field_equals", "text_equals", "text_contains", "target_present", "target_absent", "agent_judgment"})
READ_METHODS = frozenset({"uia_value", "visible_text", "agent_read"})


def validate_observation_target(value):
    if (not isinstance(value, dict) or "control_type" not in value
            or not {"name", "automation_id"}.intersection(value)
            or set(value) - {"control_type", "name", "automation_id"}
            or any(not _text(item) or len(item) > 2000 for item in value.values())):
        raise ValueError("verification_target_invalid")
    return deepcopy(value)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _identity(value):
    return (isinstance(value, dict) and set(value) == {"handle", "process_id", "process_create_time"}
            and type(value["handle"]) is int and value["handle"] > 0
            and type(value["process_id"]) is int and value["process_id"] > 0
            and type(value["process_create_time"]) in (int, float)
            and isfinite(value["process_create_time"]) and value["process_create_time"] > 0)


def _result(verdict, reason, receipt, observation=None, values=None):
    refs = [receipt["evidence_ref"]] if _text(receipt.get("evidence_ref")) else []
    if observation is not None and _text(observation.get("evidence_ref")):
        refs.append(observation["evidence_ref"])
    return {"verdict": verdict, "source": "rule", "observations": deepcopy(observation) if observation is not None else {},
            "outputs": deepcopy(values) if verdict == "success" and values is not None else {},
            "evidence_refs": refs, "reason": reason}


def _expected(reference, inputs, outputs, run_id):
    if not isinstance(reference, dict):
        raise ValueError("verification_expected_invalid")
    source = reference.get("source")
    if source == "constant" and set(reference) == {"source", "value"}:
        value = reference["value"]
    elif source == "input" and set(reference) == {"source", "name"} and _text(reference["name"]):
        if reference["name"] not in inputs:
            return False, None, "missing_input"
        value = inputs[reference["name"]]
    elif source == "output" and set(reference) == {"source", "step_id", "name"} and _text(reference["step_id"]) and _text(reference["name"]):
        entry = outputs.get(reference["step_id"] + "." + reference["name"])
        if entry is None:
            return False, None, "missing_output"
        if not isinstance(entry, dict) or set(entry) != {"run_id", "value"} or entry["run_id"] != run_id:
            return False, None, "stale_output"
        value = entry["value"]
    else:
        raise ValueError("verification_expected_invalid")
    if type(value) not in (str, int, float, bool):
        raise ValueError("verification_expected_value_invalid")
    return True, value, None


def _evidence_current(receipt, observation):
    if not isinstance(observation, dict):
        return False
    for key in ("run_id", "step_id", "request_id", "execution_request_id"):
        if observation.get(key) != receipt[key]:
            return False
    if (observation.get("complete") is not True or not _text(observation.get("capture_id"))
            or observation["capture_id"] == receipt["pre_capture_id"]
            or observation["capture_id"] != receipt["post_capture_id"]
            or not _hash(observation.get("capture_sha256"))
            or observation["capture_sha256"] != receipt["post_capture_sha256"]
            or observation.get("window_identity") != receipt["window_identity"]
            or observation.get("scope_id") != receipt["scope_id"]
            or not _text(observation.get("source")) or not _text(observation.get("evidence_ref"))
            or not isinstance(observation.get("values"), dict)):
        return False
    return True


def _observation_value(verification, observation):
    kind = verification["kind"]
    key = "field_value" if kind == "field_equals" else "text" if kind in {"text_equals", "text_contains"} else "target_present"
    values = observation["values"]
    if key not in values:
        return False, None
    actual = values[key]
    if kind in {"text_equals", "text_contains"} and not isinstance(actual, str):
        return False, None
    if kind in {"target_present", "target_absent"} and type(actual) is not bool:
        return False, None
    if kind == "field_equals" and type(actual) not in (str, int, float, bool):
        return False, None
    return True, actual


def _read_value(read_spec, observation):
    method = read_spec["method"]
    if observation["source"] != method:
        return False, None
    key = "field_value" if method == "uia_value" else "text"
    if key not in observation["values"]:
        return False, None
    value = observation["values"][key]
    return type(value) in (str, int, float, bool), value


def _output_type(value, kind):
    return ((kind == "text" and isinstance(value, str))
            or (kind == "number" and type(value) in (int, float) and isfinite(value))
            or (kind == "boolean" and type(value) is bool))


def _selection_effect_current(step, inputs, outputs, receipt):
    # 此处只判定归一化证据；来源文件和图片由消费入口重读核验。
    from hashlib import sha256
    from app.desktop_review.external_mapping import canonical_json_bytes
    from .selection_satisfaction import request_digest, validate_selection_intent, validate_selection_state
    try:
        action = step["action"]
        validate_selection_intent(action)
        proof = receipt["row_selection_proof"]
        actual = receipt["action_executed"]
        binding = proof["binding"]
        expected = {"run_id": receipt["run_id"], "step_id": step["step_id"],
                    "execution_request_id": receipt["execution_request_id"], "action": action,
                    "inputs": inputs, "outputs": outputs}
        if (proof.get("contract_version") != "row_selection_effect.v1"
                or proof.get("state_satisfied") is not True
                or proof.get("action_executed") is not actual or proof.get("action_required") is not actual
                or proof.get("status") != ("selected_after_dispatch" if actual else "already_satisfied")
                or proof.get("request_sha256") != request_digest(action)
                or proof.get("reference") != action.get("target_memory")
                or not _hash(binding.get("command_sha256"))
                or not _text(binding.get("session_directory"))
                or any(binding.get(key) != value for key, value in expected.items())
                or proof.get("sha256") != sha256(canonical_json_bytes(
                    {key: value for key, value in proof.items() if key != "sha256"})).hexdigest()):
            return False
        before, after = proof["before"], proof["after"]
        original = validate_selection_state(before)
        final = validate_selection_state(after, original)
        return (final["selected"] is True and original["selected"] is not actual
                and before.get("reference") == proof["reference"] == after.get("reference")
                and before["frame"]["capture_id"] != after["frame"]["capture_id"]
                and before["frame"]["window_identity"] == after["frame"]["window_identity"] == receipt["window_identity"]
                and before["frame"]["window_rect"] == after["frame"]["window_rect"]
                and all(before["candidate"].get(key) == after["candidate"].get(key)
                        for key in ("bbox", "click_point", "label", "source", "viewport_size")))
    except (KeyError, TypeError, ValueError):
        return False


def verify_step(step: dict, *, inputs: dict, outputs: dict, receipt: dict, observation: dict) -> dict:
    """只依据归属和来源可核对的当次证据输出结果。"""
    if (not isinstance(step, dict) or not _text(step.get("step_id"))
            or not isinstance(inputs, dict) or not isinstance(outputs, dict)
            or not isinstance(receipt, dict)):
        raise ValueError("verification_input_invalid")
    for key in ("run_id", "step_id", "request_id", "execution_request_id", "pre_capture_id", "post_capture_id", "scope_id"):
        if not _text(receipt.get(key)):
            raise ValueError("verification_receipt_identity_invalid")
    if receipt["step_id"] != step["step_id"] or not _identity(receipt.get("window_identity")):
        raise ValueError("verification_receipt_identity_invalid")
    if receipt.get("status") not in {"completed", "failed", "pending"} or type(receipt.get("action_executed")) is not bool:
        raise ValueError("verification_receipt_status_invalid")
    if not _hash(receipt.get("post_capture_sha256")) or not _text(receipt.get("evidence_ref")):
        return _result("uncertain", "receipt_evidence_missing", receipt)
    if receipt["status"] == "failed":
        return _result("failure", "execution_failed", receipt)
    if receipt["status"] == "pending":
        return _result("uncertain", "execution_pending", receipt)
    from .selection_satisfaction import selection_requested
    if selection_requested(step.get("action")):
        if not _selection_effect_current(step, inputs, outputs, receipt):
            return _result("failure", "selection_effect_unproven", receipt)
    elif step.get("action", {}).get("kind") != "read_text" and receipt["action_executed"] is not True:
        return _result("failure", "input_not_executed", receipt)
    if not _evidence_current(receipt, observation):
        return _result("uncertain", "current_observation_missing_or_mismatched", receipt,
                       observation if isinstance(observation, dict) else None)
    return _verify_rules(step, inputs=inputs, outputs=outputs, evidence=receipt,
                         observation=observation, expected_run_id=receipt["run_id"])


def verify_current_effect(step: dict, *, inputs: dict, outputs: dict, effect: dict, observation: dict) -> dict:
    """核验新现场的当前效果，保留原动作事实且不制造执行回执。"""
    fields = {"contract_version", "source_run_id", "source_step_id", "source_execution_request_id",
              "source_receipt_sha256", "source_settlement_sha256", "source_program_sha256",
              "source_action_executed", "session_name", "request_id", "capture_id", "capture_sha256",
              "window_identity", "scope_id", "evidence_ref"}
    if (not isinstance(step, dict) or not _text(step.get("step_id"))
            or not isinstance(inputs, dict) or not isinstance(outputs, dict)
            or not isinstance(effect, dict) or set(effect) != fields
            or effect.get("contract_version") != "workflow_current_effect.v1"):
        raise ValueError("verification_current_effect_invalid")
    if (any(not _text(effect[key]) for key in ("source_run_id", "source_step_id", "source_execution_request_id",
                                              "request_id", "capture_id", "scope_id", "evidence_ref"))
            or effect["source_step_id"] != step["step_id"]
            or any(not _hash(effect[key]) for key in ("source_receipt_sha256", "source_settlement_sha256",
                                                     "source_program_sha256", "capture_sha256"))
            or not isinstance(effect["session_name"], str)
            or re.fullmatch(r"session-[0-9a-f]{32}", effect["session_name"]) is None
            or not _identity(effect["window_identity"])
            or effect["source_action_executed"] is not None and type(effect["source_action_executed"]) is not bool):
        raise ValueError("verification_current_effect_binding_invalid")
    observed_fields = {"session_name", "step_id", "request_id", "capture_id", "capture_sha256",
                       "window_identity", "scope_id", "complete", "source", "values", "evidence_ref"}
    if (not isinstance(observation, dict) or set(observation) != observed_fields
            or observation.get("step_id") != effect["source_step_id"]
            or any(observation.get(key) != effect[key] for key in (
                "session_name", "request_id", "capture_id", "capture_sha256", "window_identity", "scope_id", "evidence_ref"))
            or observation.get("complete") is not True or not _text(observation.get("source"))
            or not isinstance(observation.get("values"), dict)):
        return _result("uncertain", "current_observation_missing_or_mismatched", effect,
                       observation if isinstance(observation, dict) else None)
    return _verify_rules(step, inputs=inputs, outputs=outputs, evidence=effect, observation=observation,
                         expected_run_id=effect["source_run_id"], current_effect=True)


def _verify_rules(step, *, inputs, outputs, evidence, observation, expected_run_id, current_effect=False):
    # 两种证据仅共用有限规则判定；执行终态与当前效果身份分别由各自入口验证。
    receipt = evidence
    verification = step.get("verification")
    read_spec = step.get("read_spec")
    if verification is None and read_spec is None:
        return _result("uncertain", "verification_rule_missing", receipt, observation)
    if verification is not None and (not isinstance(verification, dict) or verification.get("kind") not in KINDS):
        raise ValueError("verification_rule_invalid")
    if read_spec is not None and (not isinstance(read_spec, dict) or set(read_spec) - {"method", "output_name", "target"} or read_spec.get("method") not in READ_METHODS or not _text(read_spec.get("output_name"))):
        raise ValueError("read_spec_invalid")
    if verification is not None and verification["kind"] == "agent_judgment":
        if verification.get("image_check") is not None:
            from .image_verification import image_proof_current
            if (not step.get("outputs") and "read_spec" not in step
                    and step.get("action", {}).get("kind") != "read_text"
                    and image_proof_current(verification["image_check"], observation)):
                from .workflow_trial import _conditions
                current_outputs = {key: item["value"] for key, item in outputs.items()
                                   if isinstance(item, dict) and item.get("run_id") == expected_run_id and "value" in item}
                if _conditions(step.get("success_conditions", []), inputs, current_outputs, observation["values"]) != "true":
                    return _result("uncertain", "image_success_conditions_require_agent", receipt, observation)
                return _result("success", "image_rule_verified", receipt, observation, {})
        return _result("uncertain", "agent_judgment_required", receipt, observation)
    if current_effect and read_spec is not None and read_spec["method"] == "agent_read":
        return _result("uncertain", "agent_read_required", receipt, observation)
    captured = {}
    if verification is not None:
        kind = verification["kind"]
        if kind in {"field_equals", "text_equals", "text_contains"}:
            if "expected" not in verification:
                raise ValueError("verification_expected_missing")
            ready, expected, reason = _expected(verification["expected"], inputs, outputs, expected_run_id)
            if not ready:
                return _result("uncertain", reason, receipt, observation)
        present, actual = _observation_value(verification, observation)
        if not present:
            return _result("uncertain", "observed_value_missing", receipt, observation)
        if kind == "text_contains":
            if not isinstance(expected, str):
                raise ValueError("verification_contains_expected_invalid")
            passed = expected in actual
        elif kind in {"field_equals", "text_equals"}:
            passed = type(actual) is type(expected) and actual == expected
        else:
            passed = actual is (kind == "target_present")
        if not passed:
            return _result("failure", "observed_value_conflict", receipt, observation)
        output_name = verification.get("output_name")
        if output_name is not None:
            if not _text(output_name):
                raise ValueError("verification_output_name_invalid")
            captured[output_name] = actual
    if read_spec is not None:
        ready, actual = _read_value(read_spec, observation)
        if not ready:
            return _result("uncertain", "read_observation_missing", receipt, observation)
        name = read_spec["output_name"]
        if name in captured and (type(captured[name]) is not type(actual) or captured[name] != actual):
            return _result("failure", "read_output_conflict", receipt, observation)
        captured[name] = actual
    declarations = step.get("outputs", [])
    if not isinstance(declarations, list) or any(not isinstance(item, dict) or set(item) != {"name", "type"} or not _text(item["name"]) or item["type"] not in {"text", "number", "boolean"} for item in declarations):
        raise ValueError("verification_output_declarations_invalid")
    declared = {item["name"]: item["type"] for item in declarations}
    if len(declared) != len(declarations):
        raise ValueError("verification_output_declarations_invalid")
    if set(captured) != set(declared) or any(not _output_type(captured[name], kind) for name, kind in declared.items()):
        return _result("uncertain", "required_output_missing_or_wrong_type", receipt, observation)
    return _result("success", "current_effect_rule_verified" if current_effect else "rule_verified", receipt, observation, captured)


__all__ = ["verify_step", "verify_current_effect"]
