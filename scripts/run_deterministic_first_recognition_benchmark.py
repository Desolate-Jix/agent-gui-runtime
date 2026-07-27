from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.two_stage import build_two_stage_screen_understanding
from scripts.run_learn_stage1_region_localization import (
    _observe_bundle_from_trace_result,
    _stage1_inventory_from_trace_result,
)


def resolve_fixture_path(value: str, *, source_root: Path, project_root: Path = ROOT) -> Path:
    path = Path(value)
    if path.is_absolute() and path.exists():
        return path
    project_candidate = project_root / path
    if project_candidate.exists():
        return project_candidate
    source_candidate = source_root / path
    if source_candidate.exists():
        return source_candidate
    raise FileNotFoundError(f"fixture evidence missing: {value}")


def summarize_first_recognition(
    report: dict[str, Any],
    *,
    original_path: str,
    root_overlay_path: str,
    final_overlay_path: str,
) -> dict[str, Any]:
    stage1 = report.get("stage1_structure") if isinstance(report.get("stage1_structure"), dict) else {}
    gate = report.get("stage1_gate") if isinstance(report.get("stage1_gate"), dict) else {}
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    page_details = report.get("page_details") if isinstance(report.get("page_details"), dict) else {}
    learning_draft = report.get("learning_draft") if isinstance(report.get("learning_draft"), dict) else {}
    return {
        "stage1_source": str(report.get("stage1_source") or stage1.get("source") or ""),
        "root_region_count": int(stage1.get("region_count") or 0),
        "root_validator_valid": bool((stage1.get("root_validator") or {}).get("valid")),
        "stage1_gate_status": str(gate.get("status") or "unknown"),
        "stage1_failure_categories": list(gate.get("failure_categories") or []),
        "stage2_numbering_skipped": bool(stage2.get("skipped") or report.get("stage2_numbering_skipped")),
        "stage2_region_count": int(stage2.get("region_count") or len(stage2.get("regions") or [])),
        "stage2_numbered_item_count": int(stage2.get("numbered_item_count") or 0),
        "stage2_calibration_candidate_count": int(stage2.get("calibration_candidate_count") or 0),
        "fused_review_box_count": len(fusion.get("fused_review_boxes") or []),
        "page_detail_section_count": len(page_details.get("sections") or []),
        "learning_draft_region_count": len(learning_draft.get("regions") or []),
        "three_image_artifacts": {
            "original": original_path,
            "root_partition": root_overlay_path,
            "final_fusion": final_overlay_path,
        },
    }


def evaluate_root_zone_expectation(
    report: dict[str, Any],
    expected: list[str],
) -> dict[str, Any]:
    stage1 = report.get("stage1_structure") if isinstance(report.get("stage1_structure"), dict) else {}
    actual = [
        str(region.get("zone_id") or "")
        for region in stage1.get("structure_regions") or []
        if isinstance(region, dict)
    ]
    normalized_expected = [str(value) for value in expected]
    return {
        "passed": actual == normalized_expected,
        "expected": normalized_expected,
        "actual": actual,
    }


def run_manifest(manifest_path: Path, out_dir: Path) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    source_root = Path(str(manifest.get("source_root") or ROOT))
    require_gate = bool(manifest.get("require_stage1_gate", True))
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    excluded_cases = list(manifest.get("excluded_cases") or [])
    for case in manifest.get("cases") or []:
        case_id = str(case.get("case_id") or "case")
        try:
            cases.append(
                _run_case(
                    case,
                    out_dir=out_dir,
                    source_root=source_root,
                    require_gate=require_gate,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            invalid_cases.append({"case_id": case_id, "failure_category": "invalid_fixture", "error": str(exc)})

    aggregate = {
        "attempted": len(cases),
        "invalid": len(invalid_cases),
        "canonical_root_confirmed": sum(
            case["summary"]["stage1_source"] == "deterministic_root_partition_v1" for case in cases
        ),
        "root_validator_valid": sum(case["summary"]["root_validator_valid"] for case in cases),
        "stage1_gate_passed": sum(case["summary"]["stage1_gate_status"] == "passed" for case in cases),
        "stage2_completed": sum(not case["summary"]["stage2_numbering_skipped"] for case in cases),
        "three_image_complete": sum(
            all(Path(path).exists() for path in case["summary"]["three_image_artifacts"].values())
            for case in cases
        ),
        "root_zone_expectation_passed": sum(
            case["root_zone_expectation"]["passed"] for case in cases
        ),
        "interpretation": "first-recognition fixed-trace coverage; requires manual three-image review",
    }
    report = {
        "contract_version": "deterministic_first_recognition_benchmark_v2",
        "manifest_path": str(manifest_path),
        "stage1_source": "deterministic_root_partition_v1",
        "require_stage1_gate": require_gate,
        "source_type": "fixed_actual_observe_trace",
        "model_calls_in_benchmark": 0,
        "real_clicks": 0,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "aggregate": aggregate,
        "cases": cases,
        "invalid_cases": invalid_cases,
        "excluded_cases": excluded_cases,
    }
    report_path = out_dir / "deterministic_first_recognition_report.json"
    _write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def _run_case(
    case: dict[str, Any],
    *,
    out_dir: Path,
    source_root: Path,
    require_gate: bool,
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "case")
    case_dir = out_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    trace_path = resolve_fixture_path(str(case.get("trace_path") or ""), source_root=source_root)
    screenshot_path = resolve_fixture_path(str(case.get("screenshot_path") or ""), source_root=source_root)
    _verify_sha256(trace_path, str(case.get("trace_sha256") or ""), case_id=case_id, evidence="trace")
    _verify_sha256(
        screenshot_path,
        str(case.get("screenshot_sha256") or ""),
        case_id=case_id,
        evidence="screenshot",
    )
    original_path = case_dir / "01_original.png"
    shutil.copyfile(screenshot_path, original_path)
    trace = _read_json(trace_path)
    result = _trace_result(trace)
    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)
    with Image.open(original_path) as image:
        bundle["screen_size"] = {"width": image.width, "height": image.height}
    bundle["image_path"] = str(original_path)
    bundle["source_image_path"] = str(original_path)
    bundle["app_name"] = str(case.get("app_family") or bundle.get("app_name") or "unknown")
    inventory = _stage1_inventory_from_trace_result(result)
    if not inventory:
        raise ValueError(f"{case_id}: observe trace produced no first-recognition inventory")
    layout_graph = build_inventory_layout_graph(inventory, screen_size=bundle["screen_size"])
    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=require_gate,
        stage2_region_strategy="partitioned",
        enable_ocr_content_recovery=True,
    )
    full_report_path = case_dir / "first_recognition_full_report.json"
    _write_json(full_report_path, report)
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    root_overlay_path = _copy_artifact(
        fusion.get("stage1_structure_overlay_path"),
        case_dir / "02_root_partition.png",
    )
    final_overlay_path = _copy_artifact(
        fusion.get("full_screen_understanding_overlay_path") or fusion.get("compiled_overlay_path"),
        case_dir / "03_final_fusion.png",
    )
    summary = summarize_first_recognition(
        report,
        original_path=str(original_path),
        root_overlay_path=str(root_overlay_path),
        final_overlay_path=str(final_overlay_path),
    )
    root_zone_expectation = evaluate_root_zone_expectation(
        report,
        list(case.get("expected_root_zones") or []),
    )
    case_report = {
        "case_id": case_id,
        "app_family": str(case.get("app_family") or ""),
        "trace_path": str(trace_path),
        "screenshot_path": str(screenshot_path),
        "screen_inventory_count": len(inventory),
        "expected_root_zones": list(case.get("expected_root_zones") or []),
        "root_zone_expectation": root_zone_expectation,
        "summary": summary,
        "full_report_path": str(full_report_path),
        "manual_review_status": "pending_three_image_review",
        "real_clicks": 0,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    _write_json(case_dir / "case_report.json", case_report)
    return case_report


def _trace_result(trace: dict[str, Any]) -> dict[str, Any]:
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    if isinstance(result.get("data"), dict):
        result = result["data"]
    if isinstance(result.get("result"), dict) and not result.get("image_path"):
        result = result["result"]
    if not isinstance(result, dict):
        raise ValueError("trace does not contain a dict result")
    return result


def _verify_sha256(path: Path, expected: str, *, case_id: str, evidence: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not expected or actual != expected:
        raise ValueError(f"{case_id}: stale {evidence}; expected {expected}, got {actual}")


def _copy_artifact(value: Any, destination: Path) -> Path:
    source = Path(str(value or ""))
    if not source.is_absolute():
        source = ROOT / source
    if not source.exists():
        raise ValueError(f"render artifact missing: {value}")
    shutil.copyfile(source, destination)
    return destination


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Stage1 on fixed first-observe traces.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_manifest(args.manifest, args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(report["report_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
