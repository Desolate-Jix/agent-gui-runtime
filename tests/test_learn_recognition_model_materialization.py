from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.materialize_learn_recognition_model_profile import build_model_materialization_report


def _write_profile(path: Path, *, profile_id: str = "learn_mode_uground_7b", max_parameters_b: float = 7.0) -> None:
    path.write_text(
        json.dumps(
            {
                "profile_id": profile_id,
                "mode_scope": "learn_only",
                "model_id": "osunlp/UGround-V1-7B",
                "candidate_source_url": "https://huggingface.co/osunlp/UGround-V1-7B",
                "max_parameters_b": max_parameters_b,
                "intended_pipeline_stage": "roi_grounding",
                "download_status": "not_downloaded",
                "model_path": "",
                "launchable": False,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_required_model_files(model_dir: Path) -> None:
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "preprocessor_config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"fake")


def test_materialization_dry_run_reports_empty_model_dir_blockers(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    _write_profile(profile_dir / "learn_mode_uground_7b.json")

    report = build_model_materialization_report(
        profile_id="learn_mode_uground_7b",
        profile_dir=profile_dir,
        model_dir=tmp_path / "models" / "uground-v1-7b",
    )

    assert report["contract_version"] == "learn_recognition_model_materialization_report_v1"
    assert report["download_requested"] is False
    assert report["download_result"]["status"] == "skipped"
    assert report["materialization_status"] == "not_materialized"
    assert "model_dir_empty" in report["blockers"]
    assert "config_json_missing" in report["blockers"]
    assert "processor_config_missing" in report["blockers"]
    assert "weight_file_missing" in report["blockers"]
    assert report["profile_patch_proposal"]["apply_now"] is False
    assert report["profile_patch_proposal"]["patch"]["launchable"] is False


def test_materialization_candidate_when_required_local_files_exist(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    _write_profile(profile_dir / "learn_mode_uground_7b.json")
    model_dir = tmp_path / "models" / "uground-v1-7b"
    _write_required_model_files(model_dir)

    report = build_model_materialization_report(
        profile_id="learn_mode_uground_7b",
        profile_dir=profile_dir,
        model_dir=model_dir,
    )

    assert report["materialization_status"] == "materialized_candidate"
    assert report["blockers"] == []
    assert report["after_local_model_summary"]["has_weight_file"] is True
    assert report["profile_patch_proposal"]["safe_to_patch_after_health_check"] is True
    assert report["profile_patch_proposal"]["patch"]["download_status"] == "available_local_pending_health"
    assert report["profile_patch_proposal"]["patch"]["launchable"] is False


def test_materialization_accepts_smoke_verified_launchable_profile(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile_path = profile_dir / "learn_mode_uground_2b.json"
    _write_profile(profile_path, profile_id="learn_mode_uground_2b", max_parameters_b=2.0)
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.update(
        {
            "download_status": "available_local_smoke_verified",
            "launchable": True,
            "endpoint": "http://127.0.0.1:1245/v1/chat/completions",
        }
    )
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    model_dir = tmp_path / "models" / "uground-v1-2b"
    _write_required_model_files(model_dir)

    report = build_model_materialization_report(
        profile_id="learn_mode_uground_2b",
        profile_dir=profile_dir,
        model_dir=model_dir,
    )

    assert report["materialization_status"] == "materialized_candidate"
    assert report["blockers"] == []
    assert report["profile_patch_proposal"]["safe_to_patch_after_health_check"] is False
    assert report["profile_patch_proposal"]["reason"] == "profile already marked smoke-verified; no patch proposal required"


def test_materialization_can_use_injected_remote_info_without_network(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    _write_profile(profile_dir / "learn_mode_uground_7b.json")

    report = build_model_materialization_report(
        profile_id="learn_mode_uground_7b",
        profile_dir=profile_dir,
        model_dir=tmp_path / "models" / "uground-v1-7b",
        inspect_remote=True,
        remote_info_provider=lambda model_id: {
            "files": [
                {"path": "config.json", "size": 10},
                {"path": "model-00001-of-00002.safetensors", "size": 100},
                {"path": "pytorch_model.bin", "size": 1000},
            ]
        },
    )

    assert report["remote_model_summary"]["status"] == "ok"
    assert report["remote_model_summary"]["file_count"] == 3
    assert report["remote_model_summary"]["known_total_bytes"] == 1110
    assert report["remote_model_summary"]["preferred_download_total_bytes"] == 110
    assert "*.bin" not in report["download_allow_patterns"]


def test_materialization_refuses_non_learn_only_profile(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    path = profile_dir / "execute_profile.json"
    path.write_text(
        json.dumps(
            {
                "profile_id": "execute_profile",
                "mode_scope": "execute",
                "max_parameters_b": 7,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-learn-only"):
        build_model_materialization_report(profile_id="execute_profile", profile_dir=profile_dir)


def test_materialization_refuses_over_12b_profile(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    _write_profile(profile_dir / "learn_mode_uground_72b.json", profile_id="learn_mode_uground_72b", max_parameters_b=72)

    with pytest.raises(ValueError, match="over 12B"):
        build_model_materialization_report(profile_id="learn_mode_uground_72b", profile_dir=profile_dir)
