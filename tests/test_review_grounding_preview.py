from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from app.agent.reviewed_workflow_replay import (
    _validate_server_confirmed_grounding,
    resolve_current_state,
    select_transition_for_review,
    select_verified_transition,
    validate_current_grounding,
    validate_review_grounding_preview,
)
from tests.test_live_controller_w4 import _Gate, _TargetResolver, _current_observation
from tests.test_reviewed_workflow_asset_v2 import _asset


def _canonical_sha(payload: dict, field: str, *aliases: str) -> str:
    excluded = {field, *aliases}
    body = {key: value for key, value in payload.items() if key not in excluded}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review_fixture(*, requires_confirmation: bool = False):
    asset = _asset()
    asset["transitions"][0]["risk_policy"]["requires_user_confirmation"] = (
        requires_confirmation
    )
    if requires_confirmation:
        asset["transitions"][0]["risk_policy"]["automatic_execution_allowed"] = False
    current = _current_observation(asset)
    resolution = resolve_current_state(asset, current)
    selection = select_transition_for_review(
        asset,
        resolution,
        transition_id="open_detail",
        current_observation=current,
    )
    resolved = _TargetResolver().resolve(
        session_id="session.review",
        selection=selection,
        current_observation=current,
    )
    grounding = resolved["grounding"]
    gate = _Gate().evaluate(selection=selection, grounding=grounding)
    return asset, current, resolution, selection, grounding, gate


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_review_selector_and_preview_bind_full_current_geometry_without_authority(
    requires_confirmation: bool,
) -> None:
    asset, _, _, selection, grounding, gate = _review_fixture(
        requires_confirmation=requires_confirmation
    )

    preview = validate_review_grounding_preview(
        asset,
        selection,
        grounding,
        gate,
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )

    assert selection["contract_version"] == "review_transition_selection_v1"
    assert selection["review_only"] is True
    assert selection["artifact_is_authorization"] is False
    assert selection["execute_binding_enabled"] is False
    assert selection["grants_action_authority"] is False
    assert selection["selection_sha256"] == selection["review_selection_sha256"]
    assert selection["review_selection_sha256"] == _canonical_sha(
        selection, "review_selection_sha256", "selection_sha256"
    )
    assert preview["contract_version"] == "review_grounding_preview_v1"
    assert preview["status"] == "validated"
    assert preview["review_only"] is True
    assert preview["artifact_is_authorization"] is False
    assert preview["execute_binding_enabled"] is False
    assert preview["grants_action_authority"] is False
    assert preview["bbox"] == grounding["bbox"]
    assert preview["click_point"] == grounding["click_point"]
    assert preview["confidence"] == grounding["confidence"]
    assert preview["score_margin"] == grounding["score_margin"]
    assert preview["review_selection_sha256"] == selection["review_selection_sha256"]
    assert preview["gate_selection_sha256"] == gate["selection_sha256"]
    assert preview["preview_sha256"] == _canonical_sha(preview, "preview_sha256")


def test_review_contracts_are_rejected_by_both_execution_validators() -> None:
    asset, _, _, selection, grounding, gate = _review_fixture()

    public = validate_current_grounding(asset, selection, grounding, gate)
    internal = _validate_server_confirmed_grounding(
        asset,
        selection,
        grounding,
        gate,
        confirmation_evidence=object(),
    )

    assert public["status"] == "blocked"
    assert internal["status"] == "blocked"


def test_public_execution_selector_still_rejects_forged_confirmation() -> None:
    asset, current, resolution, _, _, _ = _review_fixture(requires_confirmation=True)

    selection = select_verified_transition(
        asset,
        resolution,
        transition_id="open_detail",
        human_confirmation={"decision": "approved"},
        current_observation=current,
    )

    assert selection["status"] == "blocked"
    assert selection["failure_code"] == "human_review_required"


@pytest.mark.parametrize(
    "target,mutation",
    [
        ("selection", lambda value: value.update(review_only=False)),
        ("selection", lambda value: value.update(extra=True)),
        ("selection", lambda value: value.update(review_selection_sha256="0" * 64)),
        ("selection", lambda value: value["capture_lineage"].update(capture_id="other")),
        ("grounding", lambda value: value.update(candidate_id="other")),
        ("grounding", lambda value: value.update(screenshot_sha256="0" * 64)),
        ("grounding", lambda value: value.update(confidence=True)),
        ("grounding", lambda value: value.update(score_margin=float("nan"))),
        ("grounding", lambda value: value["bbox"].update(w=2000)),
        ("grounding", lambda value: value["click_point"].update(x=10)),
        ("grounding", lambda value: value["viewport_size"].update(width=100)),
        ("grounding", lambda value: value.update(evidence_refs=[])),
        ("gate", lambda value: value.update(allowed=False)),
        ("gate", lambda value: value.update(selection_sha256="0" * 64)),
        ("gate", lambda value: value.update(evidence_refs=[])),
        ("gate", lambda value: value.update(extra=True)),
    ],
)
def test_review_preview_fails_closed_on_shape_geometry_and_binding_drift(
    target: str,
    mutation,
) -> None:
    asset, _, _, selection, grounding, gate = _review_fixture()
    values = {
        "selection": deepcopy(selection),
        "grounding": deepcopy(grounding),
        "gate": deepcopy(gate),
    }
    mutation(values[target])

    result = validate_review_grounding_preview(
        asset,
        values["selection"],
        values["grounding"],
        values["gate"],
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )

    assert result["status"] == "blocked"
    assert result["review_only"] is True
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["grants_action_authority"] is False
