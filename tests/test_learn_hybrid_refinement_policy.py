from __future__ import annotations

import pytest


def _selection(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": "hybrid_target_selection_v1",
        "selection_status": "selected",
        "candidate_id": "candidate/one",
        "capture": {"capture_id": "capture/one", "image_sha256": "a" * 64},
        "model_proposal": {"canonical_capture_pixel_point": [10.0, 20.0]},
    }
    value.update(changes)
    return value


def test_conditional_refinement_skips_a_valid_unique_point_without_trigger() -> None:
    from app.learn.hybrid.refinement_policy import decide_refinement

    result = decide_refinement(selection=_selection(), policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False})

    assert result["status"] == "skipped"
    assert result["reason"] == "valid_unique_point_no_geometric_trigger"
    assert result["provider_result"] is None


def test_ambiguous_selection_never_requests_refinement() -> None:
    from app.learn.hybrid.refinement_policy import decide_refinement

    result = decide_refinement(selection=_selection(selection_status="ambiguous", candidate_id=None), policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": True})

    assert result["status"] == "not_requested"
    assert result["reason"] == "ambiguous_selection"


def test_requested_refinement_without_a_provider_is_not_completed() -> None:
    from app.learn.hybrid.refinement_policy import decide_refinement

    result = decide_refinement(selection=_selection(), policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": True})

    assert result["status"] == "requested"
    assert result["provider_result"] is None


@pytest.mark.parametrize("mode,trigger,status,reason", [
    ("never", True, "skipped", "policy_never"),
    ("always", False, "requested", "policy_always"),
    ("conditional", False, "skipped", "valid_unique_point_no_geometric_trigger"),
    ("conditional", True, "requested", "explicit_geometric_trigger"),
])
def test_three_modes_keep_call_decision_explicit(mode, trigger, status, reason):
    from app.learn.hybrid.refinement_policy import decide_refinement
    value = decide_refinement(selection=_selection(), policy={"policy_version": "selection_refinement_modes_v1", "mode": mode, "geometric_trigger": trigger})
    assert value["status"] == status
    assert value["reason"] == reason
    assert value["provider_result"] is None


@pytest.mark.parametrize("status", ["ambiguous", "unbound", "provider_failure", "unknown"])
def test_always_does_not_bypass_missing_unique_selection(status):
    from app.learn.hybrid.refinement_policy import decide_refinement
    value = decide_refinement(selection=_selection(selection_status=status, candidate_id=None), policy={"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": True})
    assert value["status"] == "not_requested"


def test_historical_policy_remains_conditional_only():
    from app.learn.hybrid.refinement_policy import decide_refinement
    with pytest.raises(ValueError, match="invalid"):
        decide_refinement(selection=_selection(), policy={"policy_version": "selection_refinement_conditional_v1", "mode": "always", "geometric_trigger": False})
