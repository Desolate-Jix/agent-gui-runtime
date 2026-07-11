from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def archive_learning_demo_visual_checkpoint(
    *,
    visual_report_path: str | Path,
    protected_report_path: str | Path,
    out_path: str | Path,
    checkpoint_id: str,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else ROOT
    visual_path = _resolve_path(visual_report_path, root)
    protected_path = _resolve_path(protected_report_path, root)
    out = _resolve_path(out_path, root)
    visual_report = _read_json(visual_path)
    protected_report = _read_json(protected_path)
    visual_summary = visual_report.get("summary") if isinstance(visual_report.get("summary"), dict) else {}
    protected_summary = protected_report.get("summary") if isinstance(protected_report.get("summary"), dict) else {}
    baseline = protected_report.get("baseline_comparison") if isinstance(protected_report.get("baseline_comparison"), dict) else {}
    safety = visual_report.get("safety") if isinstance(visual_report.get("safety"), dict) else {}
    contact_sheet = _resolve_path(str(visual_report.get("contact_sheet_path") or ""), root)
    cases = [_archive_case(item, protected_report) for item in _list_of_dicts(visual_report.get("cases"))]
    blockers: list[str] = []
    if not contact_sheet.exists():
        blockers.append("contact_sheet_missing")
    if int(protected_summary.get("failed") or 0) > 0:
        blockers.append("protected_set_failed")
    if baseline.get("status") not in {"pass", None}:
        blockers.append("protected_baseline_drift")
    if int(visual_summary.get("runtime_pathgraph_ready_count") or 0) != 0:
        blockers.append("runtime_pathgraph_promotion_present")
    if safety.get("execute_binding_enabled") is not False:
        blockers.append("execute_binding_not_disabled")
    if int(safety.get("live_clicks") or 0) != 0 or int(safety.get("live_fills") or 0) != 0 or int(safety.get("live_submits") or 0) != 0:
        blockers.append("live_action_present")
    report = {
        "contract_version": "learning_demo_visual_archive_node_v1",
        "checkpoint_id": checkpoint_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "pass" if not blockers else "needs_review",
        "blockers": blockers,
        "visual_report_path": _relative_path(visual_path, root),
        "protected_report_path": _relative_path(protected_path, root),
        "contact_sheet_path": _relative_path(contact_sheet, root),
        "summary": {
            "case_count": int(visual_summary.get("case_count") or len(cases)),
            "display_review_ready_count": int(visual_summary.get("display_review_ready_count") or 0),
            "stress_sample_display_review_count": int(visual_summary.get("stress_sample_display_review_count") or 0),
            "runtime_pathgraph_ready_count": int(visual_summary.get("runtime_pathgraph_ready_count") or 0),
            "protected_attempted": int(protected_summary.get("attempted") or 0),
            "protected_passed": int(protected_summary.get("passed") or 0),
            "protected_failed": int(protected_summary.get("failed") or 0),
            "protected_baseline_status": baseline.get("status") or "not_provided",
            "protected_baseline_mismatch_count": int(baseline.get("mismatch_count") or 0),
            "interpretation": (
                "Interview/display archive node only. It proves the visual demo artifacts and protected "
                "display-review baseline are present; it is not recognition accuracy, model grounding, "
                "Execute authorization, or Runtime PathGraph readiness."
            ),
        },
        "cases": cases,
        "safety_boundary": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "next_step_policy": {
            "before_new_interface": (
                "Run the protected-set checker with this archive's protected baseline before and after "
                "any new recognition strategy or free-exploration replay."
            ),
            "python_org_boundary": (
                "Python.org remains a stress sample and must not be promoted to demo-ready or model-accuracy "
                "evidence without future per-region grounding artifacts."
            ),
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = _relative_path(out, root)
    return report


def _archive_case(case: dict[str, Any], protected_report: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    protected_case = _protected_case_by_id(protected_report, case_id)
    structure_quality = protected_case.get("structure_quality") if isinstance(protected_case.get("structure_quality"), dict) else {}
    return {
        "case_id": case_id,
        "quality_status": case.get("quality_status") or "unknown",
        "display_review_ready": bool(case.get("display_review_ready") is True),
        "visual_artifacts_present": bool(case.get("visual_artifacts_present") is True),
        "page_detail_preview_path": case.get("page_detail_preview_path") or "",
        "readonly_pathgraph_preview_path": case.get("readonly_pathgraph_preview_path") or "",
        "readonly_pathgraph_diagram_path": case.get("readonly_pathgraph_diagram_path") or "",
        "protected_case_passed": protected_case.get("passed") is True,
        "structure_quality_status": structure_quality.get("status") or "unknown",
        "runtime_pathgraph_ready": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _protected_case_by_id(protected_report: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in _list_of_dicts(protected_report.get("cases")):
        if str(case.get("case_id") or "") == case_id:
            return case
    return {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(path: str | Path, root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive the current Learning Interface visual demo checkpoint.")
    parser.add_argument("--visual-report", required=True)
    parser.add_argument("--protected-report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--checkpoint-id", default="learning_demo_visual_checkpoint")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = archive_learning_demo_visual_checkpoint(
        visual_report_path=args.visual_report,
        protected_report_path=args.protected_report,
        out_path=args.out,
        checkpoint_id=args.checkpoint_id,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
