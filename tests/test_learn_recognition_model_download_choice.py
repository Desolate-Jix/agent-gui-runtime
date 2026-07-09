from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_model_download_choice import (
    build_learn_recognition_model_download_choice_report,
)


def test_repository_download_choice_splits_risk_and_quality_recommendations() -> None:
    report = build_learn_recognition_model_download_choice_report()

    assert report["contract_version"] == "learn_recognition_model_download_choice_v1"
    assert report["candidate_count"] == 2
    assert report["risk_first_recommendation"]["profile_id"] == "learn_mode_uground_2b"
    assert report["risk_first_recommendation"]["preferred_download_total_gb"] < 5
    assert report["quality_first_recommendation"]["profile_id"] == "learn_mode_uground_7b"
    assert report["quality_first_recommendation"]["preferred_download_total_gb"] > 10
    assert report["anti_inflation"]["not_accuracy"] is True
    assert report["anti_inflation"]["not_model_ability_proof"] is True
    assert report["anti_inflation"]["not_execute_authorization"] is True
    assert "download choice report only" in report["anti_inflation"]["interpretation"]


def test_download_choice_writes_json_and_does_not_claim_profile_promotion(tmp_path: Path) -> None:
    out_path = tmp_path / "download_choice_report.json"

    report = build_learn_recognition_model_download_choice_report(out=out_path)

    assert report["report_path"] == str(out_path)
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learn_recognition_model_download_choice_v1"
    assert saved["anti_inflation"]["not_profile_promotion"] is True
    assert saved["risk_first_recommendation"]["intended_use"] == "launchability_smoke_before_larger_quality_probe"
    assert saved["quality_first_recommendation"]["intended_use"] == "fixed_grounding_matrix_quality_probe_after_materialization"


def test_download_choice_uses_selection_report_for_quality_first(tmp_path: Path) -> None:
    materialization_2b = tmp_path / "m2.json"
    materialization_7b = tmp_path / "m7.json"
    selection = tmp_path / "selection.json"
    materialization_2b.write_text(
        json.dumps(_materialization("learn_mode_uground_2b", "osunlp/UGround-V1-2B", 2.0, 4.1), ensure_ascii=False),
        encoding="utf-8",
    )
    materialization_7b.write_text(
        json.dumps(_materialization("learn_mode_uground_7b", "osunlp/UGround-V1-7B", 7.0, 15.4), ensure_ascii=False),
        encoding="utf-8",
    )
    selection.write_text(
        json.dumps(
            {
                "primary_recommendation": {
                    "profile_id": "learn_mode_uground_2b",
                    "reason": "test selection override",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_learn_recognition_model_download_choice_report(
        uground2b_materialization_path=materialization_2b,
        uground7b_materialization_path=materialization_7b,
        selection_report_path=selection,
    )

    assert report["risk_first_recommendation"]["profile_id"] == "learn_mode_uground_2b"
    assert report["quality_first_recommendation"]["profile_id"] == "learn_mode_uground_2b"
    assert report["quality_first_recommendation"]["reason"] == "test selection override"


def _materialization(profile_id: str, model_id: str, max_parameters_b: float, preferred_gb: float) -> dict:
    return {
        "contract_version": "learn_recognition_model_materialization_report_v1",
        "profile_id": profile_id,
        "model_id": model_id,
        "max_parameters_b": max_parameters_b,
        "download_requested": False,
        "remote_inspection_requested": True,
        "materialization_status": "not_materialized",
        "blockers": ["model_dir_empty"],
        "planned_model_dir": f"D:/agent-gui-runtime/models/{profile_id}",
        "planned_endpoint": f"http://127.0.0.1:{1240 + int(max_parameters_b)}/v1/chat/completions",
        "dependency_probe": {"torch": True, "transformers": True},
        "disk_space": {
            "preferred_download_total_gb": preferred_gb,
            "free_gb": 31.5,
            "free_after_preferred_gb": round(31.5 - preferred_gb, 3),
        },
        "remote_model_summary": {
            "known_total_gb": preferred_gb * 2,
            "preferred_download_total_gb": preferred_gb,
        },
        "anti_inflation": {"not_accuracy": True},
    }
