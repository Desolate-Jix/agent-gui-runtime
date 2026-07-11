from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = [
    {
        "case_id": "python_org_v92_visual_audit",
        "path": "artifacts/chatgpt_reports/stage2_v92_parent_child_display_gpt_audit_result.json",
        "evidence_kind": "chatgpt_visual_audit",
        "surface": "python_org",
    },
    {
        "case_id": "python_org_v97_visual_audit",
        "path": "artifacts/chatgpt_reports/stage2_v97_text_card_group_cleanup_gpt_audit_result.json",
        "evidence_kind": "chatgpt_visual_audit",
        "surface": "python_org",
    },
    {
        "case_id": "python_org_honest_fullscreen_summary",
        "path": "artifacts/review-overlays/honest_fullscreen_recognition_check_20260705/honest_fullscreen_recognition_summary.json",
        "evidence_kind": "honest_fullscreen_summary",
        "surface": "python_org",
    },
    {
        "case_id": "python_org_current_replay",
        "path": "artifacts/learning-runs/regression_20260711_replay_python_org/learn_two_stage_replay_report_20260711-055127.json",
        "evidence_kind": "two_stage_replay_report",
        "surface": "python_org",
    },
    {
        "case_id": "python_org_actual_parser_inventory",
        "path": "logs/learn-recognition-parser-exp1/python_homepage_full_observe_20260703/actual_parser_output_v1.json",
        "evidence_kind": "actual_parser_output",
        "surface": "python_org",
    },
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve(path: str | Path, root: Path = ROOT) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _relative(path: str | Path, root: Path = ROOT) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return str(candidate.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(candidate)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _int_field(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _matching_honest_items(
    payload: dict[str, Any],
    *,
    case_id: str = "",
    surface: str = "",
) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return []
    needles = {
        value.replace("_org", "").replace("-", "_").lower()
        for value in (case_id, surface)
        if value
    }
    if not needles:
        return [item for item in items if isinstance(item, dict)]
    matched: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        haystack = " ".join(
            str(item.get(key) or "").replace("-", "_").lower()
            for key in ("case", "parser_path", "overlay")
        )
        if any(needle and needle in haystack for needle in needles):
            matched.append(item)
    return matched


def _has_any_true_model_grounding(payload: dict[str, Any]) -> bool:
    for node in _walk_dicts(payload):
        if node.get("model_grounding_attempted") is True:
            return True
        if _int_field(node.get("model_grounding_attempted_count")) > 0:
            return True
    return False


def _model_grounding_attempt_count(payload: dict[str, Any]) -> int:
    total = 0
    for node in _walk_dicts(payload):
        total += _int_field(node.get("model_grounding_attempted_count"))
        if node.get("model_grounding_attempted") is True:
            total += 1
    return total


def _evidence_kind_classification(
    payload: dict[str, Any],
    evidence_kind: str,
    *,
    case_id: str = "",
    surface: str = "",
) -> str:
    if evidence_kind == "chatgpt_visual_audit":
        return "display_review_only"
    if evidence_kind == "honest_fullscreen_summary":
        precise = _int_field(payload.get("precise_supported_count"))
        for item in _matching_honest_items(payload, case_id=case_id, surface=surface):
            precise += _int_field(item.get("precise_supported_count"))
        return "precise_model_grounding_summary" if precise > 0 else "rough_semantic_or_display_only"
    if evidence_kind == "actual_parser_output":
        if payload.get("actual_model_call_in_this_run") is True and not _has_any_true_model_grounding(payload):
            return "model_semantic_inventory_only"
    if _has_any_true_model_grounding(payload):
        return "has_recorded_model_grounding_attempts"
    return "display_review_only"


def audit_historical_evidence_case(case: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "").strip() or "unnamed_case"
    evidence_kind = str(case.get("evidence_kind") or "unknown").strip() or "unknown"
    surface = str(case.get("surface") or "")
    source_path = _resolve(case.get("path") or "", root)
    result: dict[str, Any] = {
        "case_id": case_id,
        "surface": surface,
        "source_path": _relative(source_path, root),
        "evidence_kind": evidence_kind,
        "attempted": True,
        "valid_evidence_file": False,
        "model_accuracy_claim_allowed": False,
        "model_grounding_claim_allowed": False,
        "errors": [],
    }
    if not source_path.exists():
        result["errors"].append("source_missing")
        result["classification"] = "missing_evidence"
        return result
    try:
        payload = _read_json(source_path)
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"json_read_failed:{type(exc).__name__}:{exc}")
        result["classification"] = "invalid_json"
        return result

    grounding_attempts = _model_grounding_attempt_count(payload)
    classification = _evidence_kind_classification(
        payload,
        evidence_kind,
        case_id=case_id,
        surface=surface,
    )
    has_grounding = classification == "has_recorded_model_grounding_attempts"
    result.update(
        {
            "valid_evidence_file": True,
            "classification": classification,
            "actual_model_call_recorded": bool(payload.get("actual_model_call_in_this_run") is True),
            "model_grounding_attempted_count": grounding_attempts,
            "model_accuracy_claim_allowed": False,
            "model_grounding_claim_allowed": has_grounding,
            "display_review_only": not has_grounding,
            "claim_boundary": (
                "recorded grounding attempts exist; still requires separate coordinate/gate review"
                if has_grounding
                else "not valid evidence for model accuracy, point grounding, Execute, or Runtime PathGraph promotion"
            ),
        }
    )
    if evidence_kind == "honest_fullscreen_summary":
        result["honest_fullscreen_counts"] = _honest_fullscreen_counts(
            payload,
            case_id=case_id,
            surface=surface,
        )
    if evidence_kind == "chatgpt_visual_audit":
        result["visual_audit_verdict"] = _visual_audit_verdict(payload, case_id)
    return result


def _honest_fullscreen_counts(
    payload: dict[str, Any],
    *,
    case_id: str = "",
    surface: str = "",
) -> dict[str, Any]:
    precise = _int_field(payload.get("precise_supported_count"))
    rough = _int_field(payload.get("rough_semantic_count"))
    matched_items = _matching_honest_items(payload, case_id=case_id, surface=surface)
    for item in matched_items:
        precise += _int_field(item.get("precise_supported_count"))
        rough += _int_field(item.get("rough_semantic_count"))
    return {
        "precise_supported_count": precise,
        "rough_semantic_count": rough,
        "matched_item_count": len(matched_items),
    }


def _visual_audit_verdict(payload: dict[str, Any], case_id: str) -> str:
    conclusions = payload.get("conclusions") if isinstance(payload.get("conclusions"), dict) else {}
    for key in ("python_org", "python", case_id):
        value = conclusions.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("overall_verdict", "verdict"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    reply = str(payload.get("reply") or payload.get("latest_assistant_text") or "")
    if "Python.org" in reply and "CONDITIONAL PASS" in reply:
        return "CONDITIONAL PASS"
    return "not_recorded"


def run_historical_model_evidence_audit(
    cases: list[dict[str, Any]] | None = None,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    selected_cases = cases or DEFAULT_CASES
    results = [audit_historical_evidence_case(case, root=root) for case in selected_cases]
    attempted = len(results)
    valid_files = sum(1 for item in results if item.get("valid_evidence_file") is True)
    model_grounding_cases = sum(1 for item in results if item.get("model_grounding_claim_allowed") is True)
    display_only_cases = sum(1 for item in results if item.get("display_review_only") is True)
    invalid_cases = [item for item in results if item.get("valid_evidence_file") is not True]
    return {
        "contract_version": "learning_historical_model_evidence_audit_v1",
        "generated_at": _now(),
        "summary": {
            "attempted": attempted,
            "valid_files": valid_files,
            "invalid_files": len(invalid_cases),
            "display_review_only_cases": display_only_cases,
            "model_grounding_evidence_cases": model_grounding_cases,
            "model_accuracy_claim_allowed": False,
            "interpretation": (
                "Historical clean overlays may be protected display references, but they are not model accuracy "
                "or point-grounding evidence unless recorded model grounding attempts and coordinate/gate evidence exist."
            ),
        },
        "cases": results,
        "invalid_cases": invalid_cases,
        "safety_boundary": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit historical Learning Mode artifacts for model-grounding claim boundaries."
    )
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_historical_model_evidence_audit()
    if args.out:
        out_path = _resolve(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["invalid_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
