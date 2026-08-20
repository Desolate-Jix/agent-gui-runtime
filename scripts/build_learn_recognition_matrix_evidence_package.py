from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

CONTRACT_VERSION = "learn_recognition_matrix_evidence_package_v1"


def build_matrix_evidence_package(
    *,
    matrix_report_path: str | Path,
    model_profile_id: str,
    out_dir: str | Path | None = None,
    generate_pathgraph_candidate: bool = False,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    matrix_path = _resolve_under_root(matrix_report_path, root)
    matrix = _read_json(matrix_path)
    profile_row = _profile_row(matrix, model_profile_id)
    batch_path = _resolve_under_root(profile_row.get("batch_report_path") or "", root)
    batch = _read_json(batch_path)
    case_evidence = _case_evidence(batch)
    draft = _draft_from_case_evidence(
        model_profile_id=model_profile_id,
        matrix=matrix,
        profile_row=profile_row,
        case_evidence=case_evidence,
    )

    output_dir = _resolve_output_dir(out_dir, root, model_profile_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    package_path = output_dir / "matrix_learning_draft_package.json"
    package = {
        "contract_version": CONTRACT_VERSION,
        "source_type": "actual_call_matrix_evidence",
        "source_after_review": "model_generated",
        "counts_as_pure_model_generated": False,
        "draft_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "final_submit_forbidden": True,
        "authorization_scope": "display_and_review_only",
        "app_name": "learn_recognition_matrix",
        "best_attempt_index": None,
        "best_learning_draft": draft,
        "matrix_evidence": {
            "matrix_report_path": _relative_path(matrix_path, root),
            "batch_report_path": _relative_path(batch_path, root),
            "model_profile_id": model_profile_id,
            "actual_model_call": profile_row.get("actual_model_call") or {},
            "total_status": profile_row.get("total_status") or {},
            "blocked_categories": profile_row.get("blocked_categories") or {},
            "actual_grounding_failure_categories": profile_row.get("actual_grounding_failure_categories") or {},
            "case_evidence": case_evidence,
            "interpretation": "display-only matrix evidence for learning draft review; not model reliability and not Execute authorization",
        },
        "safety": _safety(),
        "created_at": datetime.now().isoformat(),
        "interpretation": "matrix-derived learning draft candidate; review/display only, no click authorization",
    }
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = {
        "contract_version": "learn_recognition_matrix_evidence_package_build_v1",
        "package_path": _relative_path(package_path, root),
        "model_profile_id": model_profile_id,
        "case_count": len(case_evidence),
        "actual_model_call": profile_row.get("actual_model_call") or {},
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "generated_pathgraph_candidate": None,
    }
    if generate_pathgraph_candidate:
        candidate = build_pathgraph_candidate_from_review(package_path, {}, project_root=root)
        result["generated_pathgraph_candidate"] = candidate
    result_path = output_dir / "matrix_evidence_package_build_report.json"
    result["report_path"] = _relative_path(result_path, root)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _profile_row(matrix: dict[str, Any], model_profile_id: str) -> dict[str, Any]:
    summary = matrix.get("matrix_summary") if isinstance(matrix.get("matrix_summary"), dict) else {}
    rows = summary.get("rows") if isinstance(summary.get("rows"), list) else []
    for row in rows:
        if isinstance(row, dict) and str(row.get("model_profile_id") or "") == model_profile_id:
            return row
    raise ValueError(f"matrix report does not contain profile row: {model_profile_id}")


def _case_evidence(batch: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for report in batch.get("case_reports") or []:
        if not isinstance(report, dict):
            continue
        if report.get("actual_model_call_in_this_run") is not True or report.get("status") != "passed":
            continue
        validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
        point_quality = report.get("point_quality") if isinstance(report.get("point_quality"), dict) else {}
        grounding = report.get("normalized_grounding") if isinstance(report.get("normalized_grounding"), dict) else {}
        screen_bbox = validation.get("screen_bbox") if isinstance(validation.get("screen_bbox"), dict) else {}
        screen_point = validation.get("screen_point") if isinstance(validation.get("screen_point"), dict) else {}
        label = str(report.get("label") or report.get("case_id") or "target").strip()
        case_id = str(report.get("case_id") or _slug(label)).strip()
        evidence.append(
            {
                "case_id": case_id,
                "label": label,
                "surface": _surface(report),
                "status": report.get("status"),
                "screenshot_path": report.get("screenshot_path") or "",
                "roi_image_path": report.get("roi_image_path") or "",
                "actual_grounding_output_path": report.get("actual_grounding_output_path") or "",
                "bbox": _bbox(screen_bbox),
                "click_point": _point(screen_point),
                "point_quality_status": point_quality.get("status") or "",
                "roi_point_source": point_quality.get("roi_point_source") or "",
                "raw_model_output": report.get("raw_model_output") or "",
                "normalized_grounding": grounding,
                "validation": validation,
                "point_quality": point_quality,
            }
        )
    return evidence


def _draft_from_case_evidence(
    *,
    model_profile_id: str,
    matrix: dict[str, Any],
    profile_row: dict[str, Any],
    case_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    state_ids = sorted({_slug(item.get("surface") or "matrix_state") for item in case_evidence}) or ["matrix_state"]
    states = [
        {
            "state_id": state_id,
            "label": state_id.replace("_", " ").strip().title(),
            "state_type": "learn_recognition_surface",
            "description": "Surface reconstructed from actual grounding matrix evidence.",
        }
        for state_id in state_ids
    ]
    regions = []
    actions = []
    transitions = []
    for index, item in enumerate(case_evidence, start=1):
        state_id = _slug(item.get("surface") or "matrix_state")
        region_id = f"region_{index}_{_slug(item.get('label') or 'target')}"
        action_id = f"action_{index}_{_slug(item.get('label') or 'target')}"
        regions.append(
            {
                "region_id": region_id,
                "label": item.get("label") or region_id,
                "region_type": "validated_grounding_target",
                "state_id": state_id,
                "bbox": item.get("bbox") or {},
                "click_point": item.get("click_point") or {},
                "source_case_id": item.get("case_id") or "",
                "source_profile_id": model_profile_id,
                "display_only": True,
            }
        )
        actions.append(
            {
                "action_template_id": action_id,
                "label": item.get("label") or action_id,
                "semantic_action": _semantic_action(item.get("label") or ""),
                "low_level_action_type": "point_grounding_candidate",
                "target_entity": region_id,
                "state_id": state_id,
                "expected_effect": "needs_human_review_before_use",
                "evidence_ref": item.get("actual_grounding_output_path") or item.get("roi_image_path") or "",
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        transitions.append(
            {
                "transition_id": f"transition_{index}_{_slug(item.get('label') or 'target')}",
                "source_state_id": state_id,
                "target_state_id": state_id,
                "trigger_action_template_id": action_id,
                "transition_type": "self_review_candidate",
                "guard_policy": "display_only_needs_human_review",
            }
        )
    return {
        "contract_version": "learning_template_draft_v1",
        "learning_source": "actual_call_matrix_evidence",
        "screen_summary": (
            f"{model_profile_id} grounding matrix evidence: "
            f"{len(case_evidence)} passed actual-call point candidates from fixed candidate set."
        ),
        "state_guess": state_ids[0],
        "workflow_draft": {
            "states": states,
            "action_templates": actions,
            "verification_rules": [
                {
                    "rule_id": "validator_valid_candidate_required",
                    "description": "Each candidate must have Validator status valid_candidate and point_quality passed_inside_expected_bbox.",
                    "source": "matrix_evidence",
                },
                {
                    "rule_id": "human_review_before_execute",
                    "description": "Matrix-derived candidates are display/review evidence only and cannot authorize Execute.",
                    "source": "safety_policy",
                },
            ],
            "transitions": transitions,
        },
        "interface_draft": {
            "regions": regions,
            "visual_assets": [],
            "dynamic_areas": [],
            "danger_zones": [
                {
                    "danger_zone_id": "final_submit_forbidden",
                    "label": "Final submit / send / confirm remains forbidden",
                    "policy": "hard_block",
                }
            ],
        },
        "blockers": [
            {
                "blocker_id": "display_only_no_execute_binding",
                "description": "Matrix evidence cannot be used as Execute authorization.",
            },
            {
                "blocker_id": "insufficient_sample_size_for_reliability",
                "description": "This fixed matrix is too small to prove recognition reliability or 90% accuracy.",
            },
        ],
        "agent_decision_points": [
            {
                "decision_id": "review_matrix_candidate_before_promotion",
                "description": "Human review is required before converting any matrix-derived region/action into a reusable template.",
            }
        ],
        "operation_skills": ["roi_point_grounding", "coordinate_transform_replay", "validator_check"],
        "gate_contracts": ["no_execute_binding", "final_submit_forbidden", "human_review_required"],
        "notes": [
            {
                "note_id": "matrix_summary",
                "text": json.dumps(profile_row.get("actual_model_call") or {}, ensure_ascii=False),
            },
            {
                "note_id": "matrix_interpretation",
                "text": str((matrix.get("matrix_summary") or {}).get("interpretation") or ""),
            },
        ],
        "safety": _safety(),
    }


def _surface(report: dict[str, Any]) -> str:
    batch_case = report.get("batch_case") if isinstance(report.get("batch_case"), dict) else {}
    return str(batch_case.get("surface") or report.get("case_id") or "matrix_state")


def _semantic_action(label: str) -> str:
    text = str(label or "").casefold()
    if "search" in text:
        return "search_or_filter"
    if "download" in text:
        return "open_download_or_navigation"
    if "pay" in text or "filter" in text:
        return "open_filter"
    return "review_grounded_target"


def _bbox(value: dict[str, Any]) -> dict[str, int]:
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": _int_or_zero(value.get("w")),
        "h": _int_or_zero(value.get("h")),
    }


def _point(value: dict[str, Any]) -> dict[str, int]:
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
    }


def _safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "final_submit_forbidden": True,
        "authorization_scope": "display_and_review_only",
    }


def _resolve_under_root(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("matrix evidence source must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _resolve_output_dir(path_value: str | Path | None, root: Path, model_profile_id: str) -> Path:
    if path_value is None:
        path = root / "artifacts" / "learn-recognition-matrix-evidence" / _slug(model_profile_id)
    else:
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("matrix evidence output must be under artifacts or logs")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _slug(value: Any) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._-").lower()
    return slug or "item"


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--model-profile", default="learn_mode_uground_2b")
    parser.add_argument("--out-dir")
    parser.add_argument("--generate-pathgraph-candidate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_matrix_evidence_package(
        matrix_report_path=args.matrix_report,
        model_profile_id=args.model_profile,
        out_dir=args.out_dir,
        generate_pathgraph_candidate=args.generate_pathgraph_candidate,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
