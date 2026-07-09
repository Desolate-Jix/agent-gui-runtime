from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
from app.learn.draft_review import load_learning_draft_review
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def build_learning_draft_freshness_demo_fixtures(*, project_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    out_dir = root / "artifacts" / "learning-draft-freshness-demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    image_path = out_dir / "source.png"
    image_path.write_bytes(PNG_1X1)
    image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()

    cases = [
        {
            "case_id": "freshness_matched",
            "source_image_path": _relative_path(image_path, root),
            "source_image_sha256": image_sha256,
        },
        {
            "case_id": "freshness_missing_file",
            "source_image_path": "artifacts/learning-draft-freshness-demo/missing_source.png",
            "source_image_sha256": image_sha256,
        },
        {
            "case_id": "freshness_checksum_mismatch",
            "source_image_path": _relative_path(image_path, root),
            "source_image_sha256": "0" * 64,
        },
    ]

    built_cases: list[dict[str, Any]] = []
    for case in cases:
        trial_path = out_dir / case["case_id"] / "trial_result.json"
        trial_path.parent.mkdir(parents=True, exist_ok=True)
        trial_path.write_text(
            json.dumps(_trial_payload(case), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result = build_pathgraph_candidate_from_review(
            _relative_path(trial_path, root),
            _review_patch(),
            project_root=root,
        )
        freshness = result["source_freshness_summary"]
        review = load_learning_draft_review(result["pathgraph_candidate_path"], project_root=root)
        candidate_review = review.get("pathgraph_candidate_review") if isinstance(review, dict) else {}
        readiness = (
            candidate_review.get("pathgraph_readiness_summary")
            if isinstance(candidate_review, dict) and isinstance(candidate_review.get("pathgraph_readiness_summary"), dict)
            else {}
        )
        promotion_gate = (
            readiness.get("promotion_review_gate")
            if isinstance(readiness.get("promotion_review_gate"), dict)
            else {}
        )
        built_cases.append(
            {
                "case_id": case["case_id"],
                "source_image_path": case["source_image_path"],
                "expected_source_image_sha256": case["source_image_sha256"],
                "freshness_status": freshness.get("freshness_status"),
                "source_image_status": freshness.get("source_image_status"),
                "checksum_status": freshness.get("checksum_status"),
                "warnings": freshness.get("warnings") or [],
                "promotion_gate_status": promotion_gate.get("gate_status") or "not_evaluated",
                "promotion_gate_failed_check_ids": promotion_gate.get("failed_check_ids") or [],
                "reviewed_template_candidate_path": result["reviewed_template_candidate_path"],
                "pathgraph_candidate_path": result["pathgraph_candidate_path"],
                "validation_report_path": result["validation_report_path"],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )

    summary_path = out_dir / "freshness_demo_summary.json"
    summary = {
        "contract_version": "learning_draft_freshness_demo_fixtures_v1",
        "summary_path": _relative_path(summary_path, root),
        "interpretation": "offline display/review fixtures only; no model call, no live click, no Execute authorization",
        "cases": built_cases,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _trial_payload(case: dict[str, str]) -> dict[str, Any]:
    return {
        "contract_version": "learning_model_trial_v1",
        "app_name": "demo",
        "best_attempt_index": 0,
        "best_learning_draft": {
            "contract_version": "learning_template_draft_v1",
            "screen_summary": f"Freshness demo case: {case['case_id']}",
            "state_guess": "demo_search_surface",
            "workflow_draft": {
                "states": [{"state_id": "s1", "label": "Demo page", "page_type": "search_page"}],
                "action_templates": [
                    {
                        "action_template_id": "a1",
                        "label": "Type query",
                        "semantic_action": "fill_field",
                        "target_entity": "r1",
                        "bbox": {"x": 10, "y": 20, "w": 80, "h": 24},
                        "click_point": {"x": 50, "y": 32},
                    }
                ],
                "verification_rules": [{"rule_id": "v1", "label": "Confirm edited target remains visible"}],
            },
            "interface_draft": {
                "regions": [
                    {
                        "region_id": "r1",
                        "label": "Demo input",
                        "role": "text_input",
                        "bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                        "click_point": {"x": 58, "y": 33},
                    }
                ]
            },
            "page_details": {
                "screen": {
                    "source_image_path": case["source_image_path"],
                    "source_image_sha256": case["source_image_sha256"],
                }
            },
            "safety": {
                "observation_only": True,
                "final_submit_blocked": True,
            },
            "blockers": [{"blocker_id": "b1", "label": "Stop on final submit"}],
            "learning_source": "offline_freshness_demo_fixture",
        },
    }


def _review_patch() -> dict[str, Any]:
    return {
        "review_status": "approved_as_assisted_template",
        "region_bbox_updates": {
            "r1": {
                "bbox": {"x": 12, "y": 22, "width": 96, "height": 28},
                "click_point": {"x": 60, "y": 36},
            }
        },
        "action_bbox_updates": {
            "a1": {
                "bbox": {"x": 14, "y": 24, "w": 82, "h": 22},
                "click_point": {"x": 55, "y": 35},
            }
        },
        "blockers": [{"blocker_id": "b1", "label": "Stop on final submit"}],
        "verification_rules": [{"rule_id": "v1", "label": "Confirm edited target remains visible"}],
    }


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create offline Learning Draft source-freshness demo fixtures.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()
    summary = build_learning_draft_freshness_demo_fixtures(project_root=args.project_root)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(summary["summary_path"])


if __name__ == "__main__":
    main()
