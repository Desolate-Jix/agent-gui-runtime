from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_fusion_gate_rejection_diagnosis_report.json"


def report_gate_rejection_diagnosis(
    *,
    fusion_status_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    status_path = _resolve_path(fusion_status_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    status = _read_json(status_path)
    cases = [_diagnose_item(item, root=root) for item in _gate_rejected_items(status)]
    classification_counts = _count_by(cases, "classification")
    proposed_fix_counts = _count_by(cases, "proposed_fix")
    result = {
        "contract_version": "learn_fusion_gate_rejection_diagnosis_report_v1",
        "source_fusion_status_path": _relative_path(status_path, root),
        "summary": {
            "attempted": len(cases),
            "classification_counts": classification_counts,
            "proposed_fix_counts": proposed_fix_counts,
            "safe_intercepts": len([case for case in cases if case.get("safety_interpretation") == "safe_intercept_not_unsafe_failure"]),
            "real_clicks": sum(int(case.get("real_clicks") or 0) for case in cases),
        },
        "cases": cases,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "display_only": True,
        "not_accuracy": True,
        "interpretation": (
            "Offline diagnosis for fused understanding gate rejections. "
            "A rejected dry-run candidate is a safe intercept, not an unsafe failure or click success."
        ),
    }
    report_path = out / REPORT_NAME
    result["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _gate_rejected_items(status: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in _list_of_dicts(status.get("items"))
        if _text(item.get("calibration_status")) == "gate_rejected" or _text(item.get("gate_safety")) == "passed_rejected"
    ]


def _diagnose_item(item: dict[str, Any], *, root: Path) -> dict[str, Any]:
    trace_path = _resolve_optional_path(item.get("trace_path"), root)
    trace = _read_json(trace_path) if trace_path and trace_path.exists() else {}
    request = trace.get("request") if isinstance(trace.get("request"), dict) else {}
    pre_click = _pre_click_decision(trace)
    candidate_decision = _first_candidate_decision(pre_click)
    pre_click_reasons = _list_of_strings(pre_click.get("reasons"))
    candidate_reasons = _list_of_strings(candidate_decision.get("reasons"))
    classification = _classify_rejection(item=item, request=request, candidate_reasons=candidate_reasons)
    proposed_fix = _proposed_fix(classification)
    return {
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "role": item.get("role"),
        "classification": classification,
        "proposed_fix": proposed_fix,
        "requested_task": _text(request.get("task")),
        "requested_semantic_action": _text(
            (request.get("operation_context") if isinstance(request.get("operation_context"), dict) else {}).get(
                "semantic_action"
            )
        ),
        "pre_click_allowed": pre_click.get("allowed"),
        "pre_click_reasons": pre_click_reasons,
        "candidate_decision_reasons": candidate_reasons,
        "point_quality": item.get("point_quality"),
        "gate_safety": item.get("gate_safety"),
        "trace_path": item.get("trace_path"),
        "recognition_plan_trace_path": item.get("recognition_plan_trace_path"),
        "overlay_path": item.get("overlay_path"),
        "real_clicks": int(item.get("real_clicks") or 0),
        "safety_interpretation": "safe_intercept_not_unsafe_failure",
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _pre_click_decision(trace: dict[str, Any]) -> dict[str, Any]:
    result = trace.get("result") if isinstance(trace.get("result"), dict) else {}
    direct = result.get("pre_click_decision") if isinstance(result.get("pre_click_decision"), dict) else {}
    if direct:
        return direct
    plan = result.get("recognition_plan") if isinstance(result.get("recognition_plan"), dict) else {}
    return plan.get("pre_click_decision") if isinstance(plan.get("pre_click_decision"), dict) else {}


def _first_candidate_decision(pre_click: dict[str, Any]) -> dict[str, Any]:
    decisions = _list_of_dicts(pre_click.get("candidate_decisions"))
    return decisions[0] if decisions else {}


def _classify_rejection(*, item: dict[str, Any], request: dict[str, Any], candidate_reasons: list[str]) -> str:
    label = _text(item.get("label")).casefold()
    role = _text(item.get("role")).casefold()
    requested_task = _text(request.get("task")).casefold()
    operation_context = request.get("operation_context") if isinstance(request.get("operation_context"), dict) else {}
    semantic_action = _text(operation_context.get("semantic_action")).casefold()
    if "candidate_goal_action_mismatch" in candidate_reasons and role == "card" and requested_task != "open_detail":
        return "missing_open_detail_semantic_action"
    if role in {"other", "region"} or "placeholder" in label or "indicator" in label:
        return "non_actionable_region_correctly_rejected"
    if "candidate_goal_action_mismatch" in candidate_reasons and not semantic_action:
        return "missing_or_ambiguous_semantic_action"
    if "candidate_goal_action_mismatch" in candidate_reasons:
        return "semantic_action_mismatch"
    return "pre_click_gate_rejected_other"


def _proposed_fix(classification: str) -> str:
    fixes = {
        "missing_open_detail_semantic_action": "rerun_locator_probe_with_operation_context_semantic_action_open_detail",
        "non_actionable_region_correctly_rejected": "keep_blocked_or_mark_as_page_structure_not_action",
        "missing_or_ambiguous_semantic_action": "add_explicit_semantic_action_before_pathgraph_wiring",
        "semantic_action_mismatch": "align_goal_task_and_candidate_semantic_action",
        "pre_click_gate_rejected_other": "inspect_trace_before_changing_gate_or_prompt",
    }
    return fixes.get(classification, "inspect_trace_before_changing_gate_or_prompt")


def _count_by(cases: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        value = _text(case.get(key)) or "missing"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _resolve_optional_path(value: Any, root: Path) -> Path | None:
    text = _text(value)
    if not text:
        return None
    return _resolve_path(text, root)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose gate-rejected items in a Learn fusion status report.")
    parser.add_argument("--fusion-status", required=True, help="Path to learn_precise_understanding_fusion_status_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_gate_rejection_diagnosis(
        fusion_status_path=args.fusion_status,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
