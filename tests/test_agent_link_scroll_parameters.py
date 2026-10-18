from __future__ import annotations

import copy

import pytest

from app.agent_link.contracts import AgentLinkError, validate_batch
from test_agent_link_flow_candidates import _candidate, _setup, flow_changes


PARAMETERS = {
    "contract_version": "reviewed_scroll_parameters_v1",
    "target_container_id": "r2",
    "axis": "vertical",
    "direction": "down",
    "wheel_clicks": 3,
    "unit": "wheel_detent",
}


def test_agent_link_relearning_candidate_preserves_reviewed_scroll_parameters(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        change = copy.deepcopy(flow_changes()[0])
        change.update(action_type="scroll_region", target_region_id="r2", scroll_parameters=PARAMETERS)
        receipt = service.agent_call(
            grant["token"], "submit_candidate", _candidate(baseline, changes=[change])
        )
        persisted = store.snapshot()["candidates"][receipt["candidate_id"]]
        assert persisted["changes"] == [change]
    finally:
        store.close()


def test_agent_link_relearning_steps_add_and_step_change_preserve_scroll_parameters(tmp_path):
    _, store, service, grant, baseline = _setup(tmp_path)
    try:
        added = {
            "step_id": "scroll-added",
            "action_type": "scroll_region",
            "target_region_id": "r2",
            "start_state": "i2",
            "arrival_state": "i1",
            "prerequisites": ["ready"],
            "expected_result": "more content visible",
            "stop_condition": "stop",
            "scroll_parameters": PARAMETERS,
        }
        add_receipt = service.agent_call(
            grant["token"],
            "submit_candidate",
            _candidate(
                baseline,
                key="scroll-add",
                changes=[{"change_type": "steps_add", "after_step_id": "s1", "steps": [added]}],
            ),
        )
        assert store.snapshot()["candidates"][add_receipt["candidate_id"]]["changes"][0]["steps"][0]["scroll_parameters"] == PARAMETERS

        changed_parameters = {**PARAMETERS, "target_container_id": "r1", "direction": "up"}
        change_receipt = service.agent_call(
            grant["token"],
            "submit_candidate",
            _candidate(
                baseline,
                key="scroll-change",
                changes=[{
                    "change_type": "step",
                    "step_id": "s1",
                    "action_type": "scroll_region",
                    "target_region_id": "r1",
                    "expected_result": "more content visible",
                    "scroll_parameters": changed_parameters,
                }],
            ),
        )
        assert store.snapshot()["candidates"][change_receipt["candidate_id"]]["changes"][0]["scroll_parameters"] == changed_parameters
    finally:
        store.close()


@pytest.mark.parametrize("parameters", [None, {**PARAMETERS, "wheel_clicks": 0}, {**PARAMETERS, "target_container_id": "r1"}])
def test_agent_link_rejects_missing_invalid_or_unbound_scroll_parameters(parameters):
    from test_agent_link_flow_candidates import flow_batch

    batch = flow_batch()
    step = batch["steps"][0]
    step.update(action_type="scroll_region", target_region_id="r2")
    if parameters is not None:
        step["scroll_parameters"] = parameters
    with pytest.raises(AgentLinkError):
        validate_batch(batch)
