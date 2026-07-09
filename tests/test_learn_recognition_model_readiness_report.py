from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_model_readiness import build_learn_recognition_model_readiness


def test_repository_learn_recognition_model_readiness_report():
    report = build_learn_recognition_model_readiness()
    profiles = {profile["profile_id"]: profile for profile in report["profiles"]}

    assert report["contract_version"] == "learn_recognition_model_readiness_report_v1"
    assert "learn_mode_qwen3_vl_8b" in profiles
    assert "learn_grounding_vista_4b_baseline" in profiles
    assert profiles["learn_mode_qwen3_vl_8b"]["readiness_status"] == "actual_call_ready"
    assert profiles["learn_grounding_vista_4b_baseline"]["readiness_status"] == "actual_call_ready"
    assert profiles["learn_mode_qwen3_vl_8b"]["model_path_exists"] is True
    assert profiles["learn_mode_qwen3_vl_8b"]["mmproj_path_exists"] is True
    assert profiles["learn_grounding_vista_4b_baseline"]["endpoint_present"] is True

    optional_profiles = [
        "learn_mode_uground_2b",
        "learn_mode_uground_7b",
        "learn_mode_gui_actor_3b",
        "learn_mode_gui_actor_7b",
        "learn_mode_showui_2b",
        "learn_mode_omniparser_v2",
    ]
    for profile_id in optional_profiles:
        profile = profiles[profile_id]
        assert profile["readiness_status"] in {"actual_call_ready", "download_or_setup_required", "blocked_until_profile_fixed"}
        if profile["readiness_status"] != "actual_call_ready":
            assert profile["blockers"]
        assert profile["artifact_is_authorization"] is False
        assert profile["execute_binding_enabled"] is False
        assert profile["final_submit_forbidden"] is True

    ready_profiles = set(report["readiness_summary"]["actual_call_ready_profiles"])
    assert {
        "learn_mode_qwen3_vl_8b",
        "learn_grounding_vista_4b_baseline",
    }.issubset(ready_profiles)
    assert report["readiness_summary"]["by_status"]["actual_call_ready"] == len(ready_profiles)
    assert sum(report["readiness_summary"]["by_status"].values()) == len(profiles)


def test_model_readiness_report_writes_json(tmp_path: Path):
    out_path = tmp_path / "readiness.json"

    report = build_learn_recognition_model_readiness(out=out_path)

    assert report["report_path"] == str(out_path)
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learn_recognition_model_readiness_report_v1"
    assert saved["profile_count"] == report["profile_count"]
