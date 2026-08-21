from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from app.agent.reviewed_workflow_asset import content_sha256, validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.learn.interface_workflow_review import load_interface_workflow_agent_context
from tests.test_agent_evidence import _persist_reviewed_workflow
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _observation


def _interface_context(asset: dict, *, stale_dynamic: bool = False) -> dict:
    source_hash = asset["source_review_lineage"]["source_workflow_sha256"]
    interface = {
        "contract_version": "agent_evidence_context_v1",
        "interface": {
            "interface_id": "node_homepage",
            "application_identity_key": "web:nz.seek.com",
            "display_name": "SEEK homepage",
            "surface_type": "web_page",
            "state_signature": "homepage",
            "responsibility": "Choose a reviewed job card.",
            "review_status": "human_approved",
        },
        "identity_anchors": [
            {
                "source_id": "anchor_homepage",
                "label": "Homepage",
                "value": "Homepage",
                "observation_status": "reviewed",
                "evidence_refs": ["evidence:homepage"],
            }
        ],
        "dynamic_content": [
            {
                "source_id": "job_title",
                "label": "Current job title",
                "value": "Software Engineer",
                "observation_status": "current",
                "capture_id": "capture-old" if stale_dynamic else "capture-1",
                "evidence_refs": ["evidence:job-title"],
            }
        ],
        "available_actions": [
            {
                "action_id": "legacy_edge_open_detail",
                "semantic_action": "open_detail",
                "review_status": "human_approved",
            }
        ],
        "actions_needing_review": [],
        "blockers": [],
        "readiness": {"status": "agent_usable", "missing_fields": []},
        "projection_contract": {
            "projection_is_read_only": True,
            "authoritative_source": "server_persisted_canonical_workflow_revision",
            "reverse_write_forbidden": True,
            "evidence_reference_expansion_for_agent_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "source_asset_sha256": source_hash,
    }
    return {
        "contract_version": "interface_workflow_agent_context_v1",
        "application_identity_key": "web:nz.seek.com",
        "application_identity": {"identity_key": "web:nz.seek.com", "kind": "web"},
        "workflow_count": 1,
        "workflows": [],
        "agent_evidence_workflows": [
            {"contract_version": "workflow_agent_evidence_v1", "workflow_id": "workflow-1", "interfaces": [interface]}
        ],
        "agent_ready": True,
        "blocked_interfaces": [],
        "agent_usable_interfaces": [{"workflow_id": "workflow-1", "interface_id": "node_homepage", "agent_usable": True}],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _inputs(*, anchors: tuple[str, ...] = ("anchor_homepage", "job_card"), stale_dynamic: bool = False):
    asset = validate_reviewed_workflow_asset(_asset())
    current = _observation(asset, "capture-1", "a" * 64, *anchors)
    resolution = resolve_current_state(asset, current)
    return asset, current, resolution, _interface_context(asset, stale_dynamic=stale_dynamic)


def _adapt(**overrides):
    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1

    asset, current, resolution, context = _inputs()
    payload = {
        "observation_id": "observation-1",
        "session_id": "session-1",
        "workflow_id": "workflow-1",
        "reviewed_asset": asset,
        "current_observation": current,
        "state_resolution": resolution,
        "interface_workflow_agent_context": context,
        "state_resolution_ref": "state-resolution:1",
        "current_capture_evidence_ref": "capture:1",
    }
    payload.update(overrides)
    return adapt_reviewed_context_to_agent_observation_v1(**payload)


def test_projects_current_reviewed_state_to_canonical_transition_only() -> None:
    observation = _adapt()

    assert observation.state.status == "matched"
    assert observation.state.state_id == "homepage"
    assert observation.application.identity_ref == "application:web:nz.seek.com"
    assert [item.action_id for item in observation.available_actions] == ["open_detail", "runtime.safe_stop"]
    action = observation.available_actions[0]
    assert action.semantic_action == "open_detail"
    assert action.expected_effect == "Reach reviewed state: detail."
    assert action.verification_rule_refs == ["workflow-rule:detail_identity"]
    assert observation.safe_stop.required is False
    assert observation.workflow.asset_content_sha256 == content_sha256(validate_reviewed_workflow_asset(_asset()))


def test_unresolved_state_projects_safe_stop_only() -> None:
    asset, current, resolution, context = _inputs(anchors=())
    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1

    observation = adapt_reviewed_context_to_agent_observation_v1(
        observation_id="observation-1", session_id="session-1", workflow_id="workflow-1",
        reviewed_asset=asset, current_observation=current, state_resolution=resolution,
        interface_workflow_agent_context=context, state_resolution_ref="state-resolution:1",
        current_capture_evidence_ref="capture:1",
    )
    assert observation.state.status == "unknown"
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]
    assert observation.safe_stop.required is True
    assert observation.blockers[0].safe_stop_required is True


def test_stale_dynamic_content_is_not_presented_as_current_value() -> None:
    asset, current, resolution, context = _inputs(stale_dynamic=True)
    observation = _adapt(
        reviewed_asset=asset, current_observation=current, state_resolution=resolution,
        interface_workflow_agent_context=context,
    )
    fact = next(item for item in observation.semantic_facts if item.fact_id == "fact.job_title")
    assert fact.value is None
    assert fact.observation_status == "requires_observation"


@pytest.mark.parametrize("mutation,match", [
    (lambda value: value["application_identity"].update(identity_key="web:wrong.test"), "application identity"),
    (lambda value: value["agent_evidence_workflows"][0]["interfaces"][0].update(source_asset_sha256="d" * 64), "source asset"),
    (lambda value: value.update(agent_ready=False), "agent-ready"),
])
def test_rejects_context_identity_and_source_mismatches(mutation, match: str) -> None:
    asset, current, resolution, context = _inputs()
    mutation(context)
    with pytest.raises(ValueError, match=match):
        _adapt(reviewed_asset=asset, current_observation=current, state_resolution=resolution, interface_workflow_agent_context=context)


def test_rejects_forged_state_resolution() -> None:
    asset, current, resolution, context = _inputs()
    resolution = deepcopy(resolution)
    resolution["state_id"] = "detail"
    with pytest.raises(ValueError, match="state resolution"):
        _adapt(reviewed_asset=asset, current_observation=current, state_resolution=resolution, interface_workflow_agent_context=context)


def test_projection_omits_geometry_paths_and_authority() -> None:
    observation = _adapt()
    payload = observation.model_dump()
    assert payload["artifact_is_authorization"] is False
    payload.pop("artifact_is_authorization")
    encoded = str(payload).casefold()
    for token in ("bbox", "click_point", "viewport", "_path", "execute_binding", "authorization", "provider"):
        assert token not in encoded


def test_accepts_actual_server_loaded_review_context(tmp_path: Path) -> None:
    saved = _persist_reviewed_workflow(tmp_path)
    source = Path(saved["path"])
    source = source if source.is_absolute() else tmp_path / source
    digest = sha256(source.read_bytes()).hexdigest()
    compiled = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=digest,
    )
    asset = compiled["asset"]
    context = load_interface_workflow_agent_context(
        project_root=tmp_path,
        application_identity_key="web:example.test",
    )
    anchor_ids = [item["anchor_id"] for item in asset["states"][0]["identity_anchors"]]
    current = _observation(
        asset,
        "capture-server",
        "e" * 64,
        *anchor_ids,
        origin="https://example.test",
    )
    resolution = resolve_current_state(asset, current)

    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1

    observation = adapt_reviewed_context_to_agent_observation_v1(
        observation_id="observation-server",
        session_id="session-server",
        workflow_id="workflow_agent_evidence",
        reviewed_asset=asset,
        current_observation=current,
        state_resolution=resolution,
        interface_workflow_agent_context=context,
        state_resolution_ref="state-resolution:server",
        current_capture_evidence_ref="capture:server",
    )

    assert observation.state.status == "matched"
    assert observation.application.identity_ref == "application:web:example.test"
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]
    assert observation.safe_stop.reason_code == "no_available_action"
    assert any(item.fact_type == "identity_anchor" for item in observation.semantic_facts)
    assert "_path" not in str(observation.model_dump()).casefold()
