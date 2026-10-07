"""当前效果证明与原动作事实分开，不伪造新执行回执。"""
from copy import deepcopy

import pytest

from app.learning_memory import workflow_verification as verification


def evidence(action=None):
    effect = {"contract_version": "workflow_current_effect.v1", "source_run_id": "trial-original",
              "source_step_id": "fill", "source_execution_request_id": "exec-original",
              "source_receipt_sha256": "a" * 64, "source_settlement_sha256": "b" * 64,
              "source_program_sha256": "c" * 64, "source_action_executed": action,
              "session_name": "session-" + "d" * 32, "request_id": "effect-new",
              "capture_id": "capture-new", "capture_sha256": "e" * 64,
              "window_identity": {"handle": 91, "process_id": 42, "process_create_time": 17.5},
              "scope_id": "field", "evidence_ref": "workflow-effects/effect-new.json"}
    observed = {key: deepcopy(effect[key]) for key in ("session_name", "request_id", "capture_id",
                "capture_sha256", "window_identity", "scope_id", "evidence_ref")}
    observed.update(step_id="fill", complete=True, source="uia_value", values={"field_value": "current"})
    return effect, observed


def step():
    return {"step_id": "fill", "action": {"kind": "input_sequence"},
            "verification": {"kind": "field_equals", "expected": {"source": "input", "name": "wanted"},
                             "output_name": "actual"}, "outputs": [{"name": "actual", "type": "text"}]}


def verify(target=None, action=None, *, effect=None, observation=None, inputs=None, outputs=None):
    original, observed = evidence(action)
    return verification.verify_current_effect(target or step(), inputs={"wanted": "current"} if inputs is None else inputs,
        outputs={} if outputs is None else outputs, effect=original if effect is None else effect,
        observation=observed if observation is None else observation)


@pytest.mark.parametrize("action", [True, False, None])
def test_success_preserves_source_action_fact_and_never_invents_execution(action):
    effect, observed = evidence(action)
    before = deepcopy((effect, observed))
    result = verify(effect=effect, observation=observed)
    assert result["verdict"] == "success" and result["reason"] == "current_effect_rule_verified"
    assert result["source"] == "rule" and result["outputs"] == {"actual": "current"}
    assert (effect, observed) == before
    assert effect["source_action_executed"] is action
    assert "action_executed" not in result and "status" not in result
    assert "run_id" not in result["observations"] and "execution_request_id" not in result["observations"]


@pytest.mark.parametrize("key,value", [
    ("session_name", "session-old"), ("source_step_id", "other"), ("source_run_id", ""),
    ("source_execution_request_id", ""), ("source_receipt_sha256", "A" * 64),
    ("source_settlement_sha256", "x"), ("source_program_sha256", ""),
    ("capture_sha256", "g" * 64), ("source_action_executed", 1),
    ("window_identity", {"handle": 1, "process_id": 2, "process_create_time": float("nan")}),
])
def test_effect_schema_rejects_invalid_source_or_new_binding(key, value):
    effect, observed = evidence()
    effect[key] = value
    with pytest.raises(ValueError, match="current_effect"):
        verify(effect=effect, observation=observed)


@pytest.mark.parametrize("change", ["missing_fact", "extra_receipt", "wrong_version"])
def test_effect_exact_keys_reject_receipt_disguise(change):
    effect, observed = evidence()
    if change == "missing_fact":
        del effect["source_action_executed"]
    elif change == "extra_receipt":
        effect.update(status="completed", action_executed=True)
    else:
        effect["contract_version"] = "workflow_receipt.v1"
    with pytest.raises(ValueError, match="current_effect"):
        verify(effect=effect, observation=observed)


@pytest.mark.parametrize("key,value", [
    ("session_name", "session-" + "f" * 32), ("step_id", "other"), ("request_id", "old-request"),
    ("capture_id", "old-capture"), ("capture_sha256", "f" * 64), ("scope_id", "other"),
    ("evidence_ref", "other.json"), ("complete", False), ("source", ""),
    ("window_identity", {"handle": 91, "process_id": 42, "process_create_time": 18.5}),
    ("run_id", "trial-original"), ("execution_request_id", "exec-original"),
])
def test_incomplete_drifted_or_receipt_disguised_observation_is_uncertain(key, value):
    effect, observed = evidence()
    observed[key] = value
    result = verify(effect=effect, observation=observed)
    assert result["verdict"] == "uncertain" and result["outputs"] == {}


def test_current_conflict_is_failure_and_expected_outputs_use_original_run():
    effect, observed = evidence()
    observed["values"]["field_value"] = "old"
    assert verify(effect=effect, observation=observed)["verdict"] == "failure"
    target = step()
    target["verification"]["expected"] = {"source": "output", "step_id": "read", "name": "value"}
    assert verify(target, outputs={"read.value": {"run_id": "trial-original", "value": "current"}})["verdict"] == "success"
    assert verify(target, outputs={"read.value": {"run_id": "trial-new", "value": "current"}})["reason"] == "stale_output"


@pytest.mark.parametrize("mode", ["no_rule", "agent_judgment", "agent_read", "missing_output", "wrong_type"])
def test_unsupported_or_incomplete_rule_outputs_remain_uncertain(mode):
    target = step()
    effect, observed = evidence()
    if mode == "no_rule":
        target.pop("verification")
    elif mode == "agent_judgment":
        target["verification"] = {"kind": "agent_judgment"}
    elif mode == "agent_read":
        target.pop("verification")
        target["read_spec"] = {"method": "agent_read", "output_name": "actual"}
        observed.update(source="agent_read", values={"text": "current"})
    elif mode == "missing_output":
        target["outputs"].append({"name": "required", "type": "text"})
    else:
        target["outputs"][0]["type"] = "number"
    result = verify(target, effect=effect, observation=observed)
    assert result["verdict"] == "uncertain" and result["outputs"] == {}


def test_current_read_spec_extracts_exact_outputs_without_action_claim():
    target = {"step_id": "fill", "action": {"kind": "read_text"},
              "read_spec": {"method": "uia_value", "output_name": "actual"},
              "outputs": [{"name": "actual", "type": "text"}]}
    assert verify(target)["outputs"] == {"actual": "current"}
