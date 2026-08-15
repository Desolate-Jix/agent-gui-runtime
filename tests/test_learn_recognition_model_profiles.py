from __future__ import annotations

import json
from pathlib import Path

from app.core.model_server import STAGE_PROFILE_IDS


PROFILE_DIR = Path("configs/model_profiles")
LEARN_PROFILE_IDS = {
    "learn_mode_qwen3_vl_8b",
    "learn_mode_uground_2b",
    "learn_mode_uground_7b",
    "learn_mode_gui_actor_3b",
    "learn_mode_gui_actor_7b",
    "learn_mode_showui_2b",
    "learn_mode_omniparser_v2",
}

LOCAL_LEARN_PROFILE_IDS = {"learn_mode_qwen3_vl_8b", "learn_mode_uground_2b"}
METADATA_ONLY_LEARN_PROFILE_IDS = LEARN_PROFILE_IDS - LOCAL_LEARN_PROFILE_IDS


def test_learn_mode_model_profiles_are_learn_only_and_under_12b() -> None:
    profiles = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in PROFILE_DIR.glob("learn_mode_*.json")}

    assert LEARN_PROFILE_IDS.issubset(profiles)
    execute_defaults = set(STAGE_PROFILE_IDS.values())

    for profile_id in LEARN_PROFILE_IDS:
        profile = profiles[profile_id]
        assert profile["profile_id"] == profile_id
        assert profile["mode_scope"] == "learn_only"
        assert float(profile["max_parameters_b"]) <= 12.0
        assert profile_id not in execute_defaults
        assert profile["artifact_is_authorization"] is False
        assert profile["execute_binding_enabled"] is False
        assert profile["real_action_requires_gate"] is True
        assert isinstance(profile.get("experiment_priority"), int)
        assert str(profile.get("input_contract") or "").strip()
        assert str(profile.get("output_contract") or "").strip()
        assert str(profile.get("coordinate_output") or "").strip()
        assert profile.get("parser_role") is not None
        assert profile.get("grounding_role") is not None

    for profile_id in METADATA_ONLY_LEARN_PROFILE_IDS:
        profile = profiles[profile_id]
        assert profile["download_status"] == "not_downloaded"
        assert profile["launchable"] is False
        assert profile.get("model_path") in (None, "")

    qwen_profile = profiles["learn_mode_qwen3_vl_8b"]
    assert qwen_profile["download_status"] == "available_local_baseline"
    assert qwen_profile["launchable"] is True
    assert qwen_profile["provider_mode"] == "local_understanding"
    assert qwen_profile["endpoint"] == "http://127.0.0.1:13240/v1/chat/completions"
    assert qwen_profile["port"] == 13240
    assert Path(qwen_profile["model_path"]).exists()
    assert Path(qwen_profile["mmproj_path"]).exists()
    assert qwen_profile["profile_id"] not in execute_defaults

    uground_2b_profile = profiles["learn_mode_uground_2b"]
    assert uground_2b_profile["download_status"] == "available_local_smoke_verified"
    assert uground_2b_profile["launchable"] is True
    assert uground_2b_profile["provider_mode"] == "local_grounding"
    assert uground_2b_profile["runtime"] == "transformers"
    assert uground_2b_profile["endpoint"] == "http://127.0.0.1:13245/v1/chat/completions"
    assert uground_2b_profile["start_script"] == "scripts/model_servers/start_uground_vision_server.ps1"
    assert uground_2b_profile["stop_script"] == "scripts/model_servers/stop_local_vision_server.ps1"
    assert uground_2b_profile["pid_file"] == "logs/learn-mode-uground-2b-server.pid"
    assert Path(uground_2b_profile["model_path"]).exists()
    assert uground_2b_profile["profile_id"] not in execute_defaults


def test_learn_mode_model_profiles_do_not_claim_execute_stage_roles() -> None:
    forbidden_roles = {"observe", "understanding", "locate", "grounding"}
    for path in PROFILE_DIR.glob("learn_mode_*.json"):
        profile = json.loads(path.read_text(encoding="utf-8"))
        roles = {str(item).casefold() for item in profile.get("role", [])}
        assert roles.isdisjoint(forbidden_roles), profile["profile_id"]
        assert profile["intended_pipeline_stage"] in {
            "parser_provider",
            "whole_screen_understanding",
            "roi_grounding",
            "grounding_verifier",
        }


def test_learn_mode_model_profiles_separate_parser_and_grounding_roles() -> None:
    profiles = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in PROFILE_DIR.glob("learn_mode_*.json")}

    assert profiles["learn_mode_qwen3_vl_8b"]["grounding_role"] == "not_used_for_final_point"
    assert profiles["learn_mode_omniparser_v2"]["parser_role"] == "ui_element_parser"
    assert profiles["learn_mode_uground_2b"]["grounding_role"] == "roi_point_grounding"
    assert profiles["learn_mode_uground_7b"]["grounding_role"] == "roi_point_grounding"
    assert profiles["learn_mode_showui_2b"]["coordinate_output"] == "normalized_0_1_point_requires_coordinate_transform"
    assert profiles["learn_mode_gui_actor_3b"]["output_contract"] == "action_region_verification_v1"
    assert profiles["learn_mode_gui_actor_7b"]["output_contract"] == "action_region_verification_v1"

    priorities = [profiles[profile_id]["experiment_priority"] for profile_id in LEARN_PROFILE_IDS]
    assert len(priorities) == len(set(priorities))


def test_qwen_8b_profiles_declare_gpu_memory_budget_for_resource_preflight() -> None:
    for profile_name in ("learn_mode_qwen3_vl_8b.json", "qwen3_vl_8b_q4_k_m.json"):
        profile = json.loads((PROFILE_DIR / profile_name).read_text(encoding="utf-8"))
        assert profile["gpu_memory_gib"] == 7


def test_qwen_8b_profiles_share_the_reserved_range_safe_port() -> None:
    profiles = [
        json.loads((PROFILE_DIR / profile_name).read_text(encoding="utf-8"))
        for profile_name in ("learn_mode_qwen3_vl_8b.json", "qwen3_vl_8b_q4_k_m.json")
    ]

    assert {profile["port"] for profile in profiles} == {13240}
    assert {
        profile["endpoint"]
        for profile in profiles
    } == {"http://127.0.0.1:13240/v1/chat/completions"}


def test_learn_grounding_vista_baseline_profile_is_learn_only_wrapper() -> None:
    profile = json.loads((PROFILE_DIR / "learn_grounding_vista_4b_baseline.json").read_text(encoding="utf-8"))
    execute_defaults = set(STAGE_PROFILE_IDS.values())

    assert profile["profile_id"] == "learn_grounding_vista_4b_baseline"
    assert profile["mode_scope"] == "learn_only"
    assert profile["model_id"] == "inclusionAI/VISTA-4B"
    assert float(profile["max_parameters_b"]) <= 12.0
    assert profile["launchable"] is True
    assert profile["download_status"] == "available_local_baseline"
    assert profile["runtime"] == "transformers"
    assert profile["provider_mode"] == "local_grounding"
    assert profile["endpoint"] == "http://127.0.0.1:13244/v1/chat/completions"
    assert profile["start_script"] == "scripts/model_servers/start_transformers_vision_server.ps1"
    assert profile["stop_script"] == "scripts/model_servers/stop_local_vision_server.ps1"
    assert profile["pid_file"] == "logs/learn-grounding-vista-4b-baseline-server.pid"
    assert profile["port"] == 13244
    assert profile["profile_id"] not in execute_defaults
    assert profile["artifact_is_authorization"] is False
    assert profile["execute_binding_enabled"] is False
    assert profile["real_action_requires_gate"] is True
    assert profile["final_submit_forbidden"] is True
