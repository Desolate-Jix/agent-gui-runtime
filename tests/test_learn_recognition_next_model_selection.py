from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_next_model_selection import build_learn_recognition_next_model_selection


def test_repository_next_model_selection_prefers_evidence_backed_roi_candidate() -> None:
    report = build_learn_recognition_next_model_selection()

    assert report["contract_version"] == "learn_recognition_next_model_selection_v1"
    assert report["candidate_count"] == 6
    assert report["primary_recommendation"]["profile_id"] == "learn_mode_uground_7b"
    assert report["fast_probe_recommendation"]["profile_id"] == "learn_mode_uground_2b"
    assert "recorded_grounding_uground_7b_seek_search_button_point_valid" in report["primary_recommendation"]["current_vista_miss_related_cases"]
    assert report["recorded_profile_breakdown"]["learn_mode_uground_7b"] == 2
    assert report["recorded_profile_breakdown"]["learn_mode_uground_2b"] == 1
    assert report["anti_inflation"]["not_accuracy"] is True
    assert report["anti_inflation"]["not_model_ability_proof"] is True
    assert report["anti_inflation"]["not_execute_authorization"] is True
    assert "run_learn_recognition_grounding_model_matrix.py" in report["next_command_hint"]


def test_next_model_selection_writes_json(tmp_path: Path) -> None:
    out_path = tmp_path / "selection.json"

    report = build_learn_recognition_next_model_selection(out=out_path)

    assert report["report_path"] == str(out_path)
    saved = json.loads(out_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learn_recognition_next_model_selection_v1"
    assert saved["primary_recommendation"]["profile_id"] == report["primary_recommendation"]["profile_id"]

