from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _write_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "status": "passed",
                "app_name": "seek",
                "image_size": {"width": 460, "height": 78},
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "image_size": {"width": 460, "height": 78},
                    "learning_source": "observe_model",
                    "screen_summary": "Search field for job query and location.",
                    "state_guess": "job_search_initial",
                    "workflow_draft": {
                        "states": [
                            {"state_id": "s1", "label": "job_search_initial", "page_type": "search_page"}
                        ],
                        "transitions": [],
                        "action_templates": [
                            {
                                "action_template_id": "a1",
                                "label": "type_job_query",
                                "semantic_action": "type_text",
                                "risk_level": "low",
                                "requires_gate": True,
                                "expected_effect": "populate search field with job query",
                            }
                        ],
                    },
                    "interface_draft": {
                        "regions": [
                            {"region_id": "r1", "label": "search_input_field", "role": "text_input"}
                        ],
                        "visual_assets": [],
                        "dynamic_areas": [],
                        "danger_zones": [],
                    },
                    "safety": {
                        "observation_only": True,
                        "promotion_allowed": False,
                        "final_submit_blocked": True,
                        "real_clicks_performed": 0,
                    },
                    "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_model_artifact_loader_creates_readonly_runtime_artifacts(tmp_path: Path) -> None:
    from app.learn.model_artifact_loader import load_model_learning_artifact

    trial_path = tmp_path / "artifacts" / "learning-runs" / "trial_result.json"
    _write_trial(trial_path)
    source_before = trial_path.read_bytes()
    source_hash = hashlib.sha256(source_before).hexdigest()

    result = load_model_learning_artifact(trial_path, project_root=tmp_path)

    assert trial_path.read_bytes() == source_before
    assert result["contract_version"] == "model_learning_artifact_load_v1"
    assert result["source"]["sha256"] == source_hash
    assert result["source"]["readonly"] is True
    assert result["source"]["posthoc_optimization_allowed"] is False

    graph_path = tmp_path / result["runtime_graph_path"]
    interface_map_path = tmp_path / result["interface_map_path"]
    assert graph_path.exists()
    assert interface_map_path.exists()

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["contract_version"] == "runtime_path_graph_v1"
    assert graph["loader"]["source_sha256"] == source_hash
    assert graph["artifact_is_authorization"] is False
    assert graph["safety"]["final_submit_forbidden"] is True
    assert graph["states"][0]["state_id"] == "s1"
    assert graph["transitions"][0]["action_template_id"] == "a1"
    assert graph["transitions"][0]["from_state_id"] == "s1"
    assert graph["transitions"][0]["to_state_id"] == "s1"
    assert graph["action_templates"][0]["action_type"] == "input"
    assert graph["action_templates"][0]["input_target"]["region_id"] == "r1"
    assert graph["action_templates"][0]["input_policy"]["submit_allowed"] is False

    interface_map = json.loads(interface_map_path.read_text(encoding="utf-8"))
    assert interface_map["contract_version"] == "learned_interface_map_v1"
    assert interface_map["source"]["readonly"] is True
    assert interface_map["editor_policy"]["source_artifact_editable"] is False
    assert interface_map["regions"][0]["region_id"] == "r1"
    assert interface_map["states"][0]["region_refs"] == ["r1"]


def test_panel_loads_model_artifact_into_replay_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.panel as panel_api

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/load_model_artifact",
        json={"trial_path": "artifacts/learning-runs/sample/trial_result.json"},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["data"]["contract_version"] == "model_learning_artifact_load_v1"
    assert payload["data"]["source"]["readonly"] is True
    assert payload["data"]["runtime_graph_path"].endswith("runtime_path_graph.json")
    assert payload["data"]["interface_map_path"].endswith("interface_map.json")


def test_model_artifact_can_drive_complete_dry_run_execute_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.execute as execute_api
    import app.api.panel as panel_api

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)
    source_hash_before = hashlib.sha256(trial_path.read_bytes()).hexdigest()
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(execute_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    load_payload = client.post(
        "/panel/load_model_artifact",
        json={"trial_path": "artifacts/learning-runs/sample/trial_result.json"},
    ).json()
    assert load_payload["success"] is True
    graph_path = load_payload["data"]["runtime_graph_path"]

    actions_payload = client.post(
        "/execute/available_actions",
        json={
            "runtime_graph_path": graph_path,
            "current_state_id": "s1",
            "screen_inventory": {"available_actions": [{"label": "Search"}]},
            "safety": {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False},
        },
    ).json()
    assert actions_payload["success"] is True
    actions = actions_payload["data"]["available_actions"]["actions"]
    assert [action["action_template_id"] for action in actions] == ["a1"]
    assert actions[0]["low_level_action_type"] == "input"
    assert actions[0]["action_taxonomy"]["kind"] == "fill_field"

    step_payload = client.post(
        "/execute/step",
        json={
            "runtime_graph_path": graph_path,
            "available_actions_trace_path": actions_payload["data"]["trace_path"],
            "path_graph_resolution": actions_payload["data"]["path_graph_resolution"],
            "selected_action": actions[0],
            "input_text": "software engineer",
            "dry_run": True,
            "dispatch_low_level": False,
            "safety": {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False},
        },
    ).json()
    assert step_payload["success"] is True
    assert step_payload["data"]["contract_version"] == "execute_step_response_v1"
    assert step_payload["data"]["path_graph_assisted"] is True
    assert step_payload["data"]["low_level_action_type"] == "input"
    assert step_payload["data"]["dispatch_low_level_executed"] is False
    assert step_payload["data"]["action_taxonomy"]["final_submit"] is False
    assert step_payload["data"]["execute_step_trace_path"]
    assert hashlib.sha256(trial_path.read_bytes()).hexdigest() == source_hash_before
