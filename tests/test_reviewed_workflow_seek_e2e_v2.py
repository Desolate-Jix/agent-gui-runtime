from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_reviewed_workflow_compiler_v2 import _base_review, _persist_reviewed_workflow


@pytest.fixture(autouse=True)
def _panel_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)


def _observation(asset: dict, content_sha256: str, capture_id: str, *anchor_ids: str, origin: str = "https://nz.seek.com") -> dict:
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": content_sha256,
        "capture_id": capture_id,
        "screenshot_sha256": hashlib.sha256(capture_id.encode("utf-8")).hexdigest(),
        "viewport_size": {"width": 1440, "height": 900},
        "origin": origin,
        "observed_anchor_evidence": [
            {
                "anchor_id": anchor_id,
                "matched": True,
                "evidence_ref": f"synthetic:{capture_id}:{anchor_id}",
                "confidence": 0.95,
            }
            for anchor_id in anchor_ids
        ],
    }


def _anchors_for(asset: dict, source_node_id: str) -> list[str]:
    state = next(item for item in asset["states"] if item["source_node_id"] == source_node_id)
    return [item["anchor_id"] for item in state["identity_anchors"]]


def _grounding(selection: dict, *, candidate_id: str) -> tuple[dict, dict]:
    lineage = selection["capture_lineage"]
    grounding = {
        "contract_version": "reviewed_workflow_current_grounding_v1",
        "asset_content_sha256": selection["asset_content_sha256"],
        "transition_id": selection["transition_id"],
        "source_state_id": selection["source_state_id"],
        "capture_id": lineage["capture_id"],
        "screenshot_sha256": lineage["screenshot_sha256"],
        "viewport_size": lineage["viewport_size"],
        "element_ref": selection["element_ref"],
        "candidate_id": candidate_id,
        "candidate_current": True,
        "eligible": True,
        "confidence": 0.97,
        "score_margin": 0.40,
        "bbox": {"x": 100, "y": 180, "w": 420, "h": 72},
        "click_point": {"x": 250, "y": 216},
        "evidence_refs": [f"synthetic:grounding:{candidate_id}"],
    }
    gate = {
        "contract_version": "pre_click_decision_v1",
        "allowed": True,
        "asset_content_sha256": selection["asset_content_sha256"],
        "transition_id": selection["transition_id"],
        "selection_sha256": selection["selection_sha256"],
        "selected_candidate_id": candidate_id,
        "selected_element_id": selection["element_ref"],
        "selected_click_point": deepcopy(grounding["click_point"]),
        "capture_id": lineage["capture_id"],
        "screenshot_sha256": lineage["screenshot_sha256"],
        "viewport_size": deepcopy(lineage["viewport_size"]),
        "evidence_refs": [f"synthetic:gate:{candidate_id}"],
    }
    return grounding, gate


def _runtime_record(observation: dict, interface_id: str) -> dict:
    return {
        "contract_version": "navigation_runtime_observation_record_v1",
        "observation": {
            "contract_version": "current_interface_observation_v1",
            "interface_id": interface_id,
            "surface_type": "web",
            "capture_id": observation["capture_id"],
            "screenshot_sha256": observation["screenshot_sha256"],
            "trace_path": f"synthetic/traces/{observation['capture_id']}.json",
        },
        "image_path": f"synthetic/screenshots/{observation['capture_id']}.png",
        "window_size": deepcopy(observation["viewport_size"]),
        "ocr_result": {"items": [{"text": "Synthetic SEEK evidence"}]},
        "resolved_read_targets": {},
        "reached_bottom": False,
    }


def _assert_pre_click_matches_gate(pre_click: dict, gate: dict) -> None:
    assert pre_click["selected_candidate_id"] == gate["selected_candidate_id"]
    assert pre_click["selected_click_point"] == gate["selected_click_point"]
    assert pre_click["asset_content_sha256"] == gate["asset_content_sha256"]
    assert pre_click["transition_id"] == gate["transition_id"]
    assert pre_click["selection_sha256"] == gate["selection_sha256"]


class _BoundActionSimulator:
    """Synthetic action boundary that accepts only the already validated Gate binding."""

    def __init__(self, bindings: dict[str, tuple[dict, dict]]) -> None:
        self._bindings = bindings
        self.calls: list[tuple[str, dict]] = []
        self._dry_requests: dict[str, dict] = {}

    def __call__(self, path: str, payload: dict) -> dict:
        assert path == "/action/execute_recognition_plan"
        self.calls.append((path, deepcopy(payload)))
        replay = payload["metadata"]["replay_context"]
        transition_id = replay["transition_id"]
        selection, gate = self._bindings[transition_id]
        assert payload["metadata"]["semantic_action"] == selection["semantic_action"]
        assert payload["metadata"]["capture_lineage"] == {
            "capture_id": selection["capture_lineage"]["capture_id"],
            "screenshot_sha256": selection["capture_lineage"]["screenshot_sha256"],
            "viewport": selection["capture_lineage"]["viewport_size"],
        }
        assert replay == {
            "contract_version": "reviewed_workflow_replay_execution_context_v1",
            "asset_content_sha256": selection["asset_content_sha256"],
            "transition_id": selection["transition_id"],
            "selection_sha256": selection["selection_sha256"],
        }
        pre_click = {
            "allowed": True,
            "reason": "synthetic_unambiguous",
            "selected_candidate_id": gate["selected_candidate_id"],
            "selected_click_point": deepcopy(gate["selected_click_point"]),
            "asset_content_sha256": gate["asset_content_sha256"],
            "transition_id": gate["transition_id"],
            "selection_sha256": gate["selection_sha256"],
        }
        _assert_pre_click_matches_gate(pre_click, gate)
        if payload["dry_run"]:
            self._dry_requests[transition_id] = deepcopy(payload)
            return {
                "success": True,
                "data": {"result": {
                    "approved_plan_id": f"synthetic-approved-{transition_id}",
                    "pre_click_decision": pre_click,
                    "trace_path": f"synthetic/traces/{transition_id}-dry.json",
                }},
            }
        dry = self._dry_requests[transition_id]
        assert payload["approved_plan_id"] == f"synthetic-approved-{transition_id}"
        assert {key: value for key, value in payload.items() if key not in {"dry_run", "approved_plan_id"}} == {
            key: value for key, value in dry.items() if key != "dry_run"
        }
        return {
            "success": True,
            "data": {"result": {
                "execution_path": {"action_executed": True},
                "post_click_verification": {"verified": True},
                "trace_path": f"synthetic/traces/{transition_id}-click.json",
                "evidence_path": f"synthetic/evidence/{transition_id}.json",
            }},
        }


def _execute_via_real_adapter(
    adapter: object,
    selection: dict,
    source_observation: dict,
    *,
    expected_target_interface_id: str,
) -> dict:
    return adapter.execute(
        {
            "semantic_action": selection["semantic_action"],
            "operation_goal": "Open the reviewed synthetic SEEK state.",
            "expected_target_interface_id": expected_target_interface_id,
            "freshness": {
                "capture_id": source_observation["capture_id"],
                "screenshot_sha256": source_observation["screenshot_sha256"],
                "trace_path": f"synthetic/traces/{source_observation['capture_id']}.json",
                "viewport_size": deepcopy(source_observation["viewport_size"]),
            },
            "replay_context": {
                "contract_version": "reviewed_workflow_replay_execution_context_v1",
                "asset_content_sha256": selection["asset_content_sha256"],
                "transition_id": selection["transition_id"],
                "selection_sha256": selection["selection_sha256"],
            },
        },
        {"read_state": {}, "choices": []},
    )


def _assert_bound_operation(operation: dict, selection: dict, gate: dict) -> None:
    assert operation["replay_context"] == {
        "contract_version": "reviewed_workflow_replay_execution_context_v1",
        "asset_content_sha256": selection["asset_content_sha256"],
        "transition_id": selection["transition_id"],
        "selection_sha256": selection["selection_sha256"],
    }
    _assert_pre_click_matches_gate(operation["gate_result"]["details"], gate)


def test_synthetic_action_binding_rejects_mismatched_candidate_or_click_point() -> None:
    gate = {
        "selected_candidate_id": "candidate-a",
        "selected_click_point": {"x": 10, "y": 20},
        "asset_content_sha256": "a" * 64,
        "transition_id": "synthetic_transition",
        "selection_sha256": "b" * 64,
    }
    pre_click = {
        **gate,
        "selected_candidate_id": "candidate-b",
    }
    with pytest.raises(AssertionError):
        _assert_pre_click_matches_gate(pre_click, gate)
    pre_click = {
        **gate,
        "selected_click_point": {"x": 11, "y": 20},
    }
    with pytest.raises(AssertionError):
        _assert_pre_click_matches_gate(pre_click, gate)


def test_synthetic_seek_three_state_review_compile_publish_preview_and_verified_replay(tmp_path: Path) -> None:
    """Offline three-state path; apply-entry is a learning stop boundary."""
    from app.agent.reviewed_workflow_replay import (
        build_recovery_decision,
        resolve_current_state,
        select_verified_transition,
        validate_current_grounding,
        verify_transition_result,
    )
    from app.main import app

    review = _base_review()
    review["workflow"]["application_identity"] = {"url": "https://nz.seek.com"}
    source, source_sha = _persist_reviewed_workflow(tmp_path, review)
    assert source.exists()

    with TestClient(app) as client:
        compile_response = client.post("/panel/compile_reviewed_workflow_asset", json={
            "application_identity_key": "web:nz.seek.com",
            "workflow_id": "seek_home_to_apply",
            "expected_source_workflow_sha256": source_sha,
        })
        assert compile_response.status_code == 200
        compiled = compile_response.json()
        assert compiled["success"] is True
        assert compiled["data"]["artifact_is_authorization"] is False
        assert compiled["data"]["execute_binding_enabled"] is False

        publish_response = client.post("/panel/publish_reviewed_workflow_asset", json={
            "application_identity_key": "web:nz.seek.com",
            "workflow_id": "seek_home_to_apply",
            "expected_source_workflow_sha256": source_sha,
            "expected_registry_revision": compiled["data"]["registry_revision"],
        })
        assert publish_response.status_code == 200
        published = publish_response.json()
        assert published["success"] is True
        assert published["data"]["artifact_is_authorization"] is False
        assert published["data"]["execute_binding_enabled"] is False
        asset = published["data"]["compile_result"]["asset"]
        content_sha256 = published["data"]["publish_result"]["content_sha256"]
        assert asset["application"]["canonical_origin"] == "https://nz.seek.com"
        assert [state["availability"] for state in asset["states"]] == ["stop_boundary", "reviewed", "reviewed"]
        assert {item["semantic_action"] for item in asset["transitions"]} == {"open_detail", "open_apply_flow"}
        serialized_asset = json.dumps(asset, ensure_ascii=False)
        assert '"x"' not in serialized_asset and "hwnd" not in serialized_asset and "pid" not in serialized_asset

        home = _observation(asset, content_sha256, "capture-home", *_anchors_for(asset, "home"))
        preview = client.post("/panel/preview_reviewed_workflow_replay", json={
            "asset_id": asset["asset_id"],
            "expected_content_sha256": content_sha256,
            "current_observation": home,
        }).json()
        assert preview["success"] is True, preview["data"]["state_resolution"].get("failure_code")
        assert preview["data"]["mode"] == "read_only_preview"
        assert preview["data"]["would_call_action_api"] is False
        assert preview["data"]["execution_authorized"] is False
        assert preview["data"]["state_resolution"]["status"] == "resolved"

    home_resolution = resolve_current_state(asset, home)
    home_selection = select_verified_transition(asset, home_resolution, semantic_action="open_detail", current_observation=home)
    assert home_selection["status"] == "selected"
    assert home_selection["artifact_is_authorization"] is False
    assert home_selection["execute_binding_enabled"] is False
    assert "bbox" not in home_selection and "click_point" not in home_selection
    grounding, gate = _grounding(home_selection, candidate_id="candidate-home-job-card")
    grounded = validate_current_grounding(asset, home_selection, grounding, gate, policy={"minimum_confidence": 0.90, "minimum_score_margin": 0.20})
    assert grounded["status"] == "validated"
    assert gate["selected_candidate_id"] == "candidate-home-job-card"
    assert gate["selected_element_id"] == home_selection["element_ref"]
    assert gate["selected_click_point"] == grounding["click_point"]

    detail = _observation(asset, content_sha256, "capture-detail", *_anchors_for(asset, "detail"))
    detail_resolution = resolve_current_state(asset, detail)
    detail_selection = select_verified_transition(asset, detail_resolution, semantic_action="open_apply_flow", current_observation=detail)
    assert detail_selection["status"] == "selected"
    detail_grounding, detail_gate = _grounding(detail_selection, candidate_id="candidate-detail-quick-apply")
    assert validate_current_grounding(asset, detail_selection, detail_grounding, detail_gate, policy={"minimum_confidence": 0.90, "minimum_score_margin": 0.20})["status"] == "validated"

    apply_entry = _observation(asset, content_sha256, "capture-apply-entry", *_anchors_for(asset, "apply_entry"))
    from app.agent.navigation_reading_live_runtime import (
        BufferedNavigationRuntimeObserver,
        RuntimeNavigationOperationAdapter,
    )

    expected_interface_ids: list[str | None] = []
    records = iter([
        _runtime_record(home, "seek_home"),
        _runtime_record(detail, "seek_detail"),
        _runtime_record(apply_entry, "seek_apply_entry"),
    ])

    def capture_current(expected_interface_id=None):
        expected_interface_ids.append(expected_interface_id)
        return next(records)

    simulator = _BoundActionSimulator({
        home_selection["transition_id"]: (home_selection, gate),
        detail_selection["transition_id"]: (detail_selection, detail_gate),
    })
    observer = BufferedNavigationRuntimeObserver(capture_current=capture_current)
    adapter = RuntimeNavigationOperationAdapter(
        post_json=simulator,
        observer=observer,
        app_name="Synthetic SEEK",
    )
    assert observer.observe_current()["capture_id"] == home["capture_id"]
    operation = _execute_via_real_adapter(
        adapter,
        home_selection,
        home,
        expected_target_interface_id="seek_detail",
    )
    _assert_bound_operation(operation, home_selection, gate)
    advanced = verify_transition_result(asset, home_selection, operation, detail)
    assert advanced["status"] == "verified", {"advanced": advanced, "operation": operation, "selection": home_selection}
    assert advanced["state_advanced"] is True
    assert observer.latest_record()["observation"]["capture_id"] == detail["capture_id"]
    assert operation["source_freshness"]["capture_id"] == home["capture_id"]

    second_operation = _execute_via_real_adapter(
        adapter,
        detail_selection,
        detail,
        expected_target_interface_id="seek_apply_entry",
    )
    _assert_bound_operation(second_operation, detail_selection, detail_gate)
    assert second_operation["source_freshness"]["capture_id"] == advanced["post_capture_lineage"]["capture_id"] == detail["capture_id"]
    assert verify_transition_result(asset, detail_selection, second_operation, apply_entry)["status"] == "verified"
    assert expected_interface_ids == [None, "seek_detail", "seek_apply_entry"]
    assert len(simulator.calls) == 4
    boundary = resolve_current_state(asset, apply_entry)
    assert boundary["status"] == "resolved"
    assert boundary["state_availability"] == "stop_boundary"
    stopped = select_verified_transition(asset, boundary, current_observation=apply_entry)
    assert stopped["status"] == "blocked"
    assert stopped["failure_code"] == "stop_boundary"

    wrong_origin = _observation(asset, content_sha256, "capture-wrong-origin", *_anchors_for(asset, "home"), origin="https://evil.example")
    assert resolve_current_state(asset, wrong_origin)["failure_code"] == "unexpected_origin"
    stale_grounding, stale_gate = _grounding(home_selection, candidate_id="candidate-stale")
    stale_grounding["capture_id"] = "capture-stale"
    stale_grounding["screenshot_sha256"] = hashlib.sha256(b"capture-stale").hexdigest()
    stale_gate["capture_id"] = "capture-stale"
    stale_gate["screenshot_sha256"] = stale_grounding["screenshot_sha256"]
    assert validate_current_grounding(asset, home_selection, stale_grounding, stale_gate, policy={"minimum_confidence": 0.90, "minimum_score_margin": 0.20})["failure_code"] == "capture_lineage_mismatch"
    ambiguous_grounding, ambiguous_gate = _grounding(home_selection, candidate_id="candidate-ambiguous")
    ambiguous_grounding["score_margin"] = 0.01
    assert validate_current_grounding(asset, home_selection, ambiguous_grounding, ambiguous_gate, policy={"minimum_confidence": 0.90, "minimum_score_margin": 0.20})["failure_code"] == "grounding_ambiguous"
    recovery_once = build_recovery_decision(asset["transitions"][0], "capture_lineage_mismatch", attempts_used=0)
    assert recovery_once["decision"] == "reobserve_and_reground_once"
    assert recovery_once["repeat_action"] is False
    recovery_exhausted = build_recovery_decision(asset["transitions"][0], "capture_lineage_mismatch", attempts_used=1)
    assert recovery_exhausted["decision"] == "safe_stop_human_review"
    assert recovery_exhausted["repeat_action"] is False
