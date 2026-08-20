from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.repair_audit import (
    audit_stage2_repair_readiness,
    summarize_nine_interface_repair_audits,
)


def run_audit(benchmark_report_path: Path, out_path: Path) -> dict[str, Any]:
    benchmark_path = _resolve_path(benchmark_report_path, base=ROOT)
    benchmark = _read_json(benchmark_path)
    cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, str]] = []
    for source_case in benchmark.get("cases", []):
        if not isinstance(source_case, dict):
            continue
        case_id = str(source_case.get("case_id") or "unknown")
        try:
            full_report_path = _resolve_path(
                Path(str(source_case.get("full_report_path") or "")),
                base=benchmark_path.parent,
            )
            full_report = _read_json(full_report_path)
            stage2 = full_report.get("stage2_numbering")
            if not isinstance(stage2, dict):
                raise ValueError("saved report has no stage2_numbering object")
            case_audit = audit_stage2_repair_readiness(stage2)
            cases.append(
                {
                    "case_id": case_id,
                    "app_family": str(source_case.get("app_family") or ""),
                    "structure_signature": _structure_signature(full_report),
                    "full_report_path": str(full_report_path),
                    "three_image_artifacts": dict(
                        ((source_case.get("summary") or {}).get("three_image_artifacts") or {})
                    ),
                    **case_audit,
                }
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            invalid_cases.append(
                {
                    "case_id": case_id,
                    "failure_category": "invalid_saved_stage2_evidence",
                    "error": str(exc),
                }
            )

    summary = summarize_nine_interface_repair_audits(cases)
    summary["invalid"] = len(invalid_cases)
    report = {
        "contract_version": "nine_interface_general_review_repair_audit_v1",
        "source_benchmark_report_path": str(benchmark_path),
        "source_type": "fixed_actual_observe_trace_saved_stage2",
        "cases": cases,
        "invalid_cases": invalid_cases,
        "summary": summary,
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


def _structure_signature(report: dict[str, Any]) -> str:
    stage1 = report.get("stage1_structure")
    if not isinstance(stage1, dict):
        return "unknown"
    zones = [
        str(region.get("zone_id") or "unknown")
        for region in stage1.get("structure_regions", [])
        if isinstance(region, dict)
    ]
    return "+".join(zones) or "unknown"


def _resolve_path(path: Path, *, base: Path) -> Path:
    candidates = [path] if path.is_absolute() else [ROOT / path, base / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"evidence path is missing: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit generic review-repair readiness across saved interfaces.")
    parser.add_argument("--benchmark-report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_audit(Path(args.benchmark_report), Path(args.out))
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"report_path={report['report_path']}")
    return 0 if not report["invalid_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
