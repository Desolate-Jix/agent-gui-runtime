from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from scripts.bind_pathgraph_candidate_source_freshness import bind_candidate_source_freshness


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg=="
)


def test_bind_candidate_source_freshness_rebuilds_non_demo_candidate_from_trial_screenshot(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    screenshot = tmp_path / "artifacts" / "screenshots" / "source.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(PNG_1X1)
    screenshot_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    trial_path = tmp_path / "logs" / "benchmarks" / "actual_parser_case" / "actual_parser_output_v1.json"
    _write_trial(trial_path, screenshot_path="artifacts/screenshots/source.png", screenshot_sha256=screenshot_sha256)

    initial = build_pathgraph_candidate_from_review(
        trial_path.relative_to(tmp_path),
        {"review_status": "approved_as_assisted_template"},
        project_root=tmp_path,
    )
    initial_review = load_learning_draft_review(initial["pathgraph_candidate_path"], project_root=tmp_path)
    initial_gate = initial_review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["promotion_review_gate"]
    assert "current_screen_freshness" in initial_gate["failed_check_ids"]

    result = bind_candidate_source_freshness(
        candidate_path=tmp_path / initial["pathgraph_candidate_path"],
        out_dir=tmp_path / "logs" / "freshness_bind",
        project_root=tmp_path,
    )

    assert result["contract_version"] == "pathgraph_candidate_source_freshness_bind_result_v1"
    assert result["binding_status"] == "bound"
    assert result["source_type"] == "source_trial_screenshot"
    assert result["source_image_path"] == "artifacts/screenshots/source.png"
    assert result["source_image_sha256"] == screenshot_sha256
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False

    rebuilt_wrapper = json.loads((tmp_path / result["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert rebuilt_wrapper["source_freshness_summary"]["freshness_status"] == "verified"
    assert rebuilt_wrapper["source_freshness_summary"]["checksum_status"] == "matched"
    review = load_learning_draft_review(result["pathgraph_candidate_path"], project_root=tmp_path)
    gate = review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["promotion_review_gate"]
    check_ids = {item["check_id"]: item for item in gate["checks"]}
    assert check_ids["current_screen_freshness"]["passed"] is True
    assert gate["gate_status"] == "passed_for_human_promotion_review"


def test_bind_candidate_source_freshness_rejects_missing_screenshot_file(tmp_path: Path) -> None:
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    trial_path = tmp_path / "logs" / "benchmarks" / "missing_file_case" / "actual_parser_output_v1.json"
    _write_trial(
        trial_path,
        screenshot_path="artifacts/screenshots/missing.png",
        screenshot_sha256="0" * 64,
    )
    initial = build_pathgraph_candidate_from_review(
        trial_path.relative_to(tmp_path),
        {"review_status": "approved_as_assisted_template"},
        project_root=tmp_path,
    )

    result = bind_candidate_source_freshness(
        candidate_path=tmp_path / initial["pathgraph_candidate_path"],
        out_dir=tmp_path / "logs" / "freshness_bind",
        project_root=tmp_path,
    )

    assert result["binding_status"] == "blocked"
    assert result["block_reason"] == "source_screenshot_file_missing"
    assert result["pathgraph_candidate_path"] == initial["pathgraph_candidate_path"]
    assert result["execute_binding_enabled"] is False


def _write_trial(path: Path, *, screenshot_path: str, screenshot_sha256: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_pipeline_result_v1",
                "screenshot_path": screenshot_path,
                "screenshot_sha256": screenshot_sha256,
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Source freshness bind case.",
                    "state_guess": "search",
                    "states": [{"state_id": "search", "label": "Search"}],
                    "regions": [
                        {
                            "region_id": "search_box",
                            "label": "Search input",
                            "role": "text_input",
                            "bbox": {"x": 10, "y": 10, "w": 120, "h": 30},
                            "click_point": {"x": 50, "y": 20},
                        }
                    ],
                    "action_templates": [
                        {
                            "action_template_id": "type_search",
                            "label": "Type search",
                            "semantic_action": "fill_field",
                            "target_entity": "search_box",
                            "bbox": {"x": 10, "y": 10, "w": 120, "h": 30},
                            "click_point": {"x": 50, "y": 20},
                        }
                    ],
                    "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                    "verification_rules": [{"rule_id": "search_visible", "label": "Search field visible"}],
                    "safety": {
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                        "final_submit_forbidden": True,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
