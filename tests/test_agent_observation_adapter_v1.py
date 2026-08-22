from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path

import pytest

from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.learn.interface_workflow_review import build_interface_node_review_revision, save_interface_workflow_review_candidate
from tests.test_agent_evidence import _persist_reviewed_workflow
from tests.test_reviewed_workflow_replay_v2 import _observation


def _server_asset(tmp_path: Path, *, blocker: bool = False) -> tuple[dict, Path]:
    saved = _persist_reviewed_workflow(tmp_path)
    source = Path(saved["path"])
    review = json.loads(source.read_text(encoding="utf-8"))
    first = review["nodes"][0]
    second = deepcopy(first)
    second.update({"node_id": "detail", "display_name": "Detail", "surface_type": "detail", "state_signature": "detail-v1", "agent_description": "Read the selected item detail.", "action_candidates": [], "controls": []})
    if blocker:
        first["blockers"] = [{"blocker_id": "reviewed_policy", "description": "A reviewed policy requires safe stop.", "safe_stop_required": True}]
    review["nodes"] = [first, second]
    review["edges"] = [{"edge_id": "items_to_detail", "source_node_id": "items", "target_node_id": "detail", "source_control_id": "open_item", "target_control_id": "open_item", "action_type": "open_detail", "agent_description": "Open the reviewed item detail.", "risk_level": "low", "review_status": "human_approved", "requires_user_confirmation": False, "preconditions": [], "success_conditions": ["Detail is visible"], "failure_conditions": ["Detail did not open"]}]
    review["workflow"].update({"node_ids": ["items", "detail"], "edge_ids": ["items_to_detail"]})
    for node in review["nodes"]:
        node.pop("human_review_confirmation", None)
    draft = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    review = json.loads(Path(draft["path"]).read_text(encoding="utf-8"))
    for node in review["nodes"]:
        node["review_status"] = "human_approved"
        node["reviewed_by_human"] = True
        node["human_review_confirmation"] = {"contract_version": "interface_node_human_review_confirmation_v1", "revision": build_interface_node_review_revision(review, node_id=node["node_id"])}
    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    source = Path(saved["path"])
    digest = sha256(source.read_bytes()).hexdigest()
    compiled = compile_reviewed_workflow_asset_v2(project_root=tmp_path, source_workflow_path=source.relative_to(tmp_path), expected_source_workflow_sha256=digest)
    assert compiled["status"] == "compiled", compiled
    asset = compiled["asset"]
    return asset, source


def _adapt(tmp_path: Path, asset: dict, *, anchors: tuple[str, ...] | None = None, state_id: str | None = None):
    requested_state = state_id or asset["entry_state_id"]
    state = next(item for item in asset["states"] if item["state_id"] == requested_state)
    anchor_ids = tuple(item["anchor_id"] for item in state["identity_anchors"])
    current = _observation(asset, "capture-current", "e" * 64, *(anchor_ids if anchors is None else anchors), origin="https://example.test")
    resolution = resolve_current_state(asset, current)
    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
    return adapt_reviewed_context_to_agent_observation_v1(
        observation_id="observation-current", session_id="session-current", workflow_id="workflow_agent_evidence",
        reviewed_asset=asset, current_observation=current, state_resolution=resolution,
        project_root=tmp_path, application_identity_key="web:example.test",
    )


def test_actual_server_loaded_workflow_projects_real_semantic_action(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    observation = _adapt(tmp_path, asset)
    assert observation.state.source_interface_id == "items"
    entry = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    transition_id = entry["allowed_transition_ids"][0]
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == transition_id
    )
    identity_rule = transition["post_action_verification"]["semantic_success_rules"][0]
    rule_digest = sha256(
        f"transition:{transition_id}:rule:{identity_rule['rule_id']}".encode("utf-8")
    ).hexdigest()
    assert identity_rule["type"] == "target_state_identity"
    assert [item.action_id for item in observation.available_actions] == [transition_id, "runtime.safe_stop"]
    assert observation.available_actions[0].semantic_action == "open_detail"
    assert observation.available_actions[0].verification_rule_refs == [
        f"content-sha256:{observation.workflow.asset_content_sha256}:{rule_digest}"
    ]
    assert observation.semantic_facts[0].capture_id is None


def test_adapter_api_cannot_accept_caller_context() -> None:
    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
    assert "interface_workflow_agent_context" not in inspect.signature(adapt_reviewed_context_to_agent_observation_v1).parameters
    assert "state_resolution_ref" not in inspect.signature(adapt_reviewed_context_to_agent_observation_v1).parameters
    assert "current_capture_evidence_ref" not in inspect.signature(adapt_reviewed_context_to_agent_observation_v1).parameters


def test_valid_current_interface_ignores_global_agent_ready_false(tmp_path: Path, monkeypatch) -> None:
    asset, _ = _server_asset(tmp_path)
    import app.agent.agent_observation_adapter as adapter_module
    original = adapter_module.load_interface_workflow_agent_context

    def load_with_unrelated_block(*, project_root, application_identity_key):
        context = original(project_root=project_root, application_identity_key=application_identity_key)
        context["agent_ready"] = False
        context["blocked_interfaces"].append({"interface_id": "unrelated", "reason": "human_review_required"})
        return context

    monkeypatch.setattr(adapter_module, "load_interface_workflow_agent_context", load_with_unrelated_block)
    observation = _adapt(tmp_path, asset)
    assert observation.state.status == "matched"
    assert observation.safe_stop.required is False


def test_application_identity_mismatch_and_not_found_reject(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    state = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    anchors = tuple(item["anchor_id"] for item in state["identity_anchors"])
    current = _observation(asset, "capture-current", "e" * 64, *anchors, origin="https://example.test")
    resolution = resolve_current_state(asset, current)
    from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
    with pytest.raises(ValueError):
        adapt_reviewed_context_to_agent_observation_v1(observation_id="o", session_id="s", workflow_id="workflow_agent_evidence", reviewed_asset=asset, current_observation=current, state_resolution=resolution, project_root=tmp_path, application_identity_key="web:missing.test")


def test_source_tampering_after_persistence_rejects(tmp_path: Path) -> None:
    asset, source = _server_asset(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["nodes"][0]["display_name"] = "Tampered"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        _adapt(tmp_path, asset)


def test_unresolved_state_has_zero_semantic_actions_and_safe_stops(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    observation = _adapt(tmp_path, asset, anchors=())
    assert observation.state.status == "unknown"
    assert observation.state.source_interface_id is None
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]


def test_ambiguous_state_has_zero_semantic_actions_and_safe_stops(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    anchors = tuple(state["identity_anchors"][0]["anchor_id"] for state in asset["states"])
    observation = _adapt(tmp_path, asset, anchors=anchors)
    assert observation.state.status == "ambiguous"
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]


def test_reviewed_blocker_is_preserved_and_forces_safe_stop(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path, blocker=True)
    observation = _adapt(tmp_path, asset)
    assert any("reviewed policy" in item.description.casefold() for item in observation.blockers)
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]


def test_stale_current_redacted_fact_cannot_rebind_to_new_capture(tmp_path: Path, monkeypatch) -> None:
    asset, _ = _server_asset(tmp_path)
    import app.agent.agent_observation_adapter as adapter_module
    original = adapter_module.load_interface_workflow_agent_context

    def load_stale(*, project_root, application_identity_key):
        context = original(project_root=project_root, application_identity_key=application_identity_key)
        interface = context["agent_evidence_workflows"][0]["interfaces"][0]
        interface["dynamic_content"][0].update({"observation_status": "current_redacted", "capture_id": "capture-old", "value": None, "value_sha256": "d" * 64})
        return context

    monkeypatch.setattr(adapter_module, "load_interface_workflow_agent_context", load_stale)
    observation = _adapt(tmp_path, asset)
    fact = next(item for item in observation.semantic_facts if item.fact_type == "current_content")
    assert fact.observation_status == "requires_observation"
    assert fact.capture_id is None
    assert fact.value_sha256 is None


def test_real_stop_boundary_preserves_stop_reason(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    boundary = next(item for item in asset["states"] if item["state_id"] != asset["entry_state_id"])
    boundary["availability"] = "stop_boundary"
    boundary["allowed_transition_ids"] = []
    boundary.pop("grounding_profile", None)
    observation = _adapt(tmp_path, asset, state_id=boundary["state_id"])
    assert observation.state.status == "stop_boundary"
    assert observation.safe_stop.reason_code == "stop_boundary"


@pytest.mark.parametrize("bad_blocker", ["not-an-object", {"blocker_id": "bad", "description": "Bad", "safe_stop_required": "yes"}])
def test_malformed_reviewed_blocker_fails_closed(tmp_path: Path, monkeypatch, bad_blocker) -> None:
    asset, _ = _server_asset(tmp_path)
    import app.agent.agent_observation_adapter as adapter_module
    original = adapter_module.load_interface_workflow_agent_context

    def load_malformed(*, project_root, application_identity_key):
        context = original(project_root=project_root, application_identity_key=application_identity_key)
        context["workflows"][0]["nodes"][0]["blockers"] = [bad_blocker]
        return context

    monkeypatch.setattr(adapter_module, "load_interface_workflow_agent_context", load_malformed)
    with pytest.raises(ValueError, match="blocker"):
        _adapt(tmp_path, asset)


def test_projection_has_no_geometry_path_or_authority_payload(tmp_path: Path) -> None:
    asset, _ = _server_asset(tmp_path)
    payload = _adapt(tmp_path, asset).model_dump()
    assert payload.pop("artifact_is_authorization") is False
    encoded = json.dumps(payload, ensure_ascii=False).casefold()
    for token in ("bbox", "click_point", "coordinates", "viewport", "_path", "provider_native", "approved_to_click", "direct_dispatch"):
        assert token not in encoded
    assert "evidence:capture-current" not in encoded
    assert all(ref.startswith("content-sha256:") for ref in payload["evidence_refs"])
