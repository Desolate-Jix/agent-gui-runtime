from __future__ import annotations

from pathlib import Path
import json

from app.runtime_architecture import build_default_architecture_spec, load_app_profile


EXPECTED_SEEK_PATTERNS = {
    "list_detail_page",
    "long_detail_reading",
    "agent_full_content_review",
    "entry_boundary",
    "multi_step_form",
    "danger_zone_final_submit",
}


def test_default_architecture_is_agentic_loop_first() -> None:
    spec = build_default_architecture_spec()

    assert spec.contract_version == "gui_agent_runtime_architecture_v1"
    assert spec.execution_model == "agentic_loop_first"
    assert [layer.name for layer in spec.layers] == [
        "agent",
        "operation",
        "gate",
        "trace",
        "workflow_asset",
    ]
    agent_layer = next(layer for layer in spec.layers if layer.name == "agent")
    assert "task decomposition" in agent_layer.owns
    workflow_layer = next(layer for layer in spec.layers if layer.name == "workflow_asset")
    assert "open-ended exploration on unknown screens" in workflow_layer.does_not_own


def test_seek_app_profile_loads_as_profile_asset() -> None:
    profile = load_app_profile(Path("artifacts/app_profiles/seek_app_profile_v1.json"))

    assert profile.contract_version == "app_profile_v1"
    assert profile.app_id == "seek"
    assert profile.execution_model == "agentic_loop_first"
    assert "read_full_job_detail" in profile.operation_skills
    assert "bound_window_match_v1" in profile.gate_contracts
    assert "final_submit_guard_v1" in profile.gate_contracts
    assert "latest_detail_snapshot_v1" in profile.gate_contracts
    assert "ocr_contextual_normalization_v1" in profile.gate_contracts
    assert any(asset["contract_version"] == "runtime_path_graph_v1" for asset in profile.workflow_assets)
    assert {item["pattern_id"] for item in profile.learned_patterns} == EXPECTED_SEEK_PATTERNS


def test_seek_learned_pattern_refs_point_to_valid_templates() -> None:
    profile = load_app_profile(Path("artifacts/app_profiles/seek_app_profile_v1.json"))

    for ref in profile.learned_patterns:
        path = Path(ref["path"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert ref["contract_version"] == "learning_pattern_ref_v1"
        assert payload["contract_version"] == "learning_pattern_template_v1"
        assert payload["pattern_id"] == ref["pattern_id"]
        assert payload["operation_skills"]
        assert payload["gate_contracts"]
        assert payload["trace_requirements"]
        assert payload["success_conditions"]
        assert payload["stop_conditions"]
        assert payload["seek_source"]["profile_id"] == "seek"
        assert payload["authorization"]
