from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_model_launch_plan import build_learn_recognition_model_launch_plan


def test_repository_launch_plan_keeps_uground7b_non_launchable_until_materialized() -> None:
    report = build_learn_recognition_model_launch_plan(profile_id="learn_mode_uground_7b")

    assert report["contract_version"] == "learn_recognition_model_launch_plan_v1"
    assert report["target_profile_id"] == "learn_mode_uground_7b"
    assert report["model_id"] == "osunlp/UGround-V1-7B"
    assert report["readiness_to_launch"]["status"] == "not_launchable_yet"
    assert "model_files_missing" in report["readiness_to_launch"]["blockers"]
    assert "server_adapter_missing" not in report["readiness_to_launch"]["blockers"]
    assert "start_script_missing" not in report["readiness_to_launch"]["blockers"]
    assert "profile_launchable_false" in report["readiness_to_launch"]["blockers"]
    assert report["planned_runtime_materialization"]["planned_local_model_dir"] == "models/uground-v1-7b"
    assert report["planned_runtime_materialization"]["planned_endpoint"] == "http://127.0.0.1:1246/v1/chat/completions"
    assert report["planned_runtime_materialization"]["server_adapter_exists"] is True
    assert report["planned_runtime_materialization"]["start_script_exists"] is True
    assert report["planned_runtime_materialization"]["dependency_probe"]["transformers"] is True
    assert report["official_source_summary"]["coordinate_contract"].startswith("UGround V1 Qwen2-VL output")
    assert any("checked-in UGround Transformers adapter" in step for step in report["recommended_sequence"])
    assert any("checked-in start_uground_vision_server.ps1" in step for step in report["recommended_sequence"])
    assert report["execute_mode_impact"]["changes_execute_defaults"] is False
    assert report["execute_mode_impact"]["execute_binding_enabled"] is False
    assert report["execute_mode_impact"]["artifact_is_authorization"] is False
    assert report["anti_inflation"]["not_accuracy"] is True
    assert report["anti_inflation"]["not_model_ability_proof"] is True
    assert report["anti_inflation"]["not_execute_authorization"] is True
    assert report["anti_inflation"]["report_did_not_mutate_profile"] is True
    assert report["anti_inflation"]["profile_currently_launchable"] is False


def test_launch_plan_uses_selection_primary_when_profile_id_omitted() -> None:
    report = build_learn_recognition_model_launch_plan()

    assert report["selection_report_found"] is True
    assert report["target_profile_id"] == "learn_mode_uground_7b"
    assert report["selected_from_report"].endswith("next_model_selection_report.json")


def test_launch_plan_uses_target_model_id_in_official_source_summary() -> None:
    report = build_learn_recognition_model_launch_plan(profile_id="learn_mode_uground_2b")

    assert report["target_profile_id"] == "learn_mode_uground_2b"
    assert report["readiness_to_launch"]["status"] == "launchable"
    assert report["readiness_to_launch"]["blockers"] == []
    assert report["anti_inflation"]["profile_currently_launchable"] is True
    assert report["official_source_summary"]["model_card"] == "https://huggingface.co/osunlp/UGround-V1-2B"
    assert "osunlp/UGround-V1-2B" in report["official_source_summary"]["official_vllm_command"]
    assert "osunlp/UGround-V1-7B" not in report["official_source_summary"]["official_vllm_command"]


def test_launch_plan_distinguishes_local_files_from_unpromoted_profile(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    model_dir = tmp_path / "models" / "uground-v1-2b"
    profile_dir.mkdir()
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (profile_dir / "learn_mode_uground_2b.json").write_text(
        json.dumps(
            {
                "profile_id": "learn_mode_uground_2b",
                "model_id": "osunlp/UGround-V1-2B",
                "model_family": "UGround",
                "max_parameters_b": 2.0,
                "candidate_source_url": "https://github.com/OSU-NLP-Group/UGround",
                "mode_scope": "learn_only",
                "intended_pipeline_stage": "roi_grounding",
                "download_status": "not_downloaded",
                "launchable": False,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "real_action_requires_gate": True,
                "final_submit_forbidden": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_learn_recognition_model_launch_plan(
        profile_id="learn_mode_uground_2b",
        profile_dir=profile_dir,
        project_root=tmp_path,
    )

    blockers = report["readiness_to_launch"]["blockers"]
    assert report["planned_runtime_materialization"]["model_files_exist"] is True
    assert "model_files_missing" not in blockers
    assert "planned_model_dir_empty" not in blockers
    assert "profile_download_status_not_updated" in blockers
    assert "profile_launchable_false" in blockers


def test_launch_plan_writes_json_without_mutating_profile(tmp_path: Path) -> None:
    out_path = tmp_path / "launch_plan.json"
    profile_path = Path("configs/model_profiles/learn_mode_uground_7b.json")
    before = profile_path.read_text(encoding="utf-8")

    report = build_learn_recognition_model_launch_plan(profile_id="learn_mode_uground_7b", out=out_path)

    assert report["report_path"] == str(out_path)
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learn_recognition_model_launch_plan_v1"
    assert saved["readiness_to_launch"]["status"] == "not_launchable_yet"
    assert profile_path.read_text(encoding="utf-8") == before
