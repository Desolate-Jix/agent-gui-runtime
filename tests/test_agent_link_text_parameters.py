from __future__ import annotations

import copy
import pytest

from test_agent_link_flow_candidates import _candidate, _setup, flow_batch, flow_changes


FIXED_PARAMETERS = {
    "contract_version": "reviewed_text_parameters_v1",
    "target_field_id": "r2",
    "content": {"kind": "literal", "text": "fixed text"},
    "clear_existing": False,
    "sensitive": False,
    "submit": False,
    "clipboard_policy": "restore_previous",
}
VARIABLE_PARAMETERS = {
    **FIXED_PARAMETERS,
    "content": {"kind": "variable", "name": "query_text"},
}


def test_agent_link_batch_preserves_fixed_and_variable_text_parameters():
    from app.agent_link.contracts import validate_batch

    for parameters in (FIXED_PARAMETERS, VARIABLE_PARAMETERS):
        batch = flow_batch()
        parameters = {**parameters, "target_field_id": batch["steps"][0]["target_region_id"]}
        batch["steps"][0].update(action_type="fill_field", text_parameters=copy.deepcopy(parameters))
        assert validate_batch(batch)["steps"][0]["text_parameters"] == parameters


def test_agent_link_candidate_step_step_flow_and_steps_add_preserve_text_parameters(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        flow = copy.deepcopy(flow_changes()[0])
        flow.update(action_type="fill_field", target_region_id="r2", text_parameters=copy.deepcopy(VARIABLE_PARAMETERS))
        flow_receipt = service.agent_call(
            grant["token"], "submit_candidate", _candidate(baseline, key="text-flow", changes=[flow])
        )
        assert store.snapshot()["candidates"][flow_receipt["candidate_id"]]["changes"] == [flow]

        step = {
            "change_type": "step", "step_id": "s1", "action_type": "fill_field",
            "target_region_id": "r1", "expected_result": "text entered",
            "text_parameters": {**FIXED_PARAMETERS, "target_field_id": "r1"},
        }
        step_receipt = service.agent_call(
            grant["token"], "submit_candidate", _candidate(baseline, key="text-step", changes=[step])
        )
        assert store.snapshot()["candidates"][step_receipt["candidate_id"]]["changes"] == [step]

        added = {
            "step_id": "text-added", "action_type": "fill_field", "target_region_id": "r2",
            "start_state": "i2", "arrival_state": "i1", "prerequisites": ["ready"],
            "expected_result": "text entered", "stop_condition": "stop",
            "text_parameters": copy.deepcopy(VARIABLE_PARAMETERS),
        }
        add_change = {"change_type": "steps_add", "after_step_id": "s1", "steps": [added]}
        add_receipt = service.agent_call(
            grant["token"], "submit_candidate", _candidate(baseline, key="text-add", changes=[add_change])
        )
        assert store.snapshot()["candidates"][add_receipt["candidate_id"]]["changes"] == [add_change]
    finally:
        store.close()


@pytest.mark.parametrize("model_name", ["StepInput", "StepChange", "StepFlowChange"])
def test_noncanonical_text_action_is_rejected_before_ingestion(model_name):
    from pydantic import ValidationError
    from app.agent_link import contracts

    step = copy.deepcopy(flow_batch()["steps"][0])
    step["action_type"] = " FILL_FIELD "
    if model_name == "StepChange":
        step = {key: step[key] for key in ("step_id", "action_type", "target_region_id", "expected_result")}
        step["change_type"] = "step"
    elif model_name == "StepFlowChange":
        step["change_type"] = "step_flow"
    with pytest.raises(ValidationError, match="canonical"):
        getattr(contracts, model_name).model_validate(step)
