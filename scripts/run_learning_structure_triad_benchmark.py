from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]


def _resolve(value: str | Path, *, root: Path = ROOT) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        result = {
            "x": int(round(float(value.get("x", 0)))),
            "y": int(round(float(value.get("y", 0)))),
            "w": int(round(float(value.get("w", value.get("width", 0))))),
            "h": int(round(float(value.get("h", value.get("height", 0))))),
        }
    except (TypeError, ValueError):
        return None
    return result if result["w"] > 0 and result["h"] > 0 else None


def _region_family(region: dict[str, Any]) -> str:
    value = " ".join(
        str(region.get(key) or "") for key in ("family", "region_id", "zone_id", "label")
    ).casefold()
    if "left" in value and any(token in value for token in ("nav", "side", "rail")):
        return "left_sidebar"
    if "right" in value and any(token in value for token in ("nav", "side", "rail")):
        return "right_sidebar"
    if "bottom" in value:
        return "bottom_bar"
    if "top" in value or "header" in value or "browser_chrome" in value:
        return "top_bar"
    if "main" in value or "primary" in value or "content" in value:
        return "main_content"
    return str(region.get("family") or "other")


def _boundary_error(
    expected: dict[str, int], actual: dict[str, int], *, width: int, height: int
) -> dict[str, float]:
    del width, height
    return {
        "x": round(abs(actual["x"] - expected["x"]) / max(1, expected["w"]), 4),
        "y": round(abs(actual["y"] - expected["y"]) / max(1, expected["h"]), 4),
        "w": round(abs(actual["w"] - expected["w"]) / max(1, expected["w"]), 4),
        "h": round(abs(actual["h"] - expected["h"]) / max(1, expected["h"]), 4),
    }


def _iou(first: dict[str, int], second: dict[str, int]) -> float:
    x1 = max(first["x"], second["x"])
    y1 = max(first["y"], second["y"])
    x2 = min(first["x"] + first["w"], second["x"] + second["w"])
    y2 = min(first["y"] + first["h"], second["y"] + second["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = first["w"] * first["h"] + second["w"] * second["h"] - intersection
    return intersection / max(1, union)


def _score_expected_elements(
    expected_elements: list[dict[str, Any]],
    actual_elements: list[dict[str, Any]],
) -> dict[str, Any]:
    unused_actual = set(range(len(actual_elements)))
    matches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for expected in expected_elements:
        expected_bbox = _bbox(expected.get("bbox"))
        accepted_roles = {str(role) for role in expected.get("accepted_roles", []) if str(role or "").strip()}
        candidates: list[tuple[float, float, int, dict[str, int]]] = []
        if expected_bbox:
            expected_cx = expected_bbox["x"] + expected_bbox["w"] / 2
            expected_cy = expected_bbox["y"] + expected_bbox["h"] / 2
            for index in unused_actual:
                actual = actual_elements[index]
                actual_bbox = _bbox(actual.get("bbox"))
                if not actual_bbox or (accepted_roles and str(actual.get("role") or "") not in accepted_roles):
                    continue
                actual_cx = actual_bbox["x"] + actual_bbox["w"] / 2
                actual_cy = actual_bbox["y"] + actual_bbox["h"] / 2
                center_x = abs(actual_cx - expected_cx) / max(1, expected_bbox["w"])
                center_y = abs(actual_cy - expected_cy) / max(1, expected_bbox["h"])
                overlap = _iou(expected_bbox, actual_bbox)
                candidates.append((overlap, max(center_x, center_y), index, actual_bbox))
        if not candidates:
            missing.append(expected)
            continue
        overlap, center_offset, index, actual_bbox = max(candidates, key=lambda item: (item[0], -item[1]))
        passed = overlap >= 0.65 and center_offset <= 0.10
        if passed:
            unused_actual.remove(index)
        else:
            missing.append(expected)
        matches.append(
            {
                "element_id": str(expected.get("element_id") or ""),
                "expected_bbox": expected_bbox,
                "actual_bbox": actual_bbox,
                "actual_role": str(actual_elements[index].get("role") or ""),
                "iou": round(overlap, 4),
                "center_offset_ratio": round(center_offset, 4),
                "passed": passed,
            }
        )
    passed_matches = [item for item in matches if item["passed"]]
    attempted = len(expected_elements)
    passed = len(passed_matches)
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "max_center_offset_ratio": (
            round(max((item["center_offset_ratio"] for item in passed_matches), default=0.0), 4)
            if attempted
            else "not_covered"
        ),
        "minimum_iou": (
            round(min((item["iou"] for item in passed_matches), default=0.0), 4)
            if attempted
            else "not_covered"
        ),
        "matches": matches,
        "missing_elements": missing,
        "interpretation": "human-annotated fixture element localization; not general model accuracy",
    }


def _contact_sheet(source: Path, stage1: Path, final: Path, out_path: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in (source, stage1, final)]
    target_height = 520
    resized: list[Image.Image] = []
    for image in images:
        ratio = target_height / max(1, image.height)
        resized.append(image.resize((max(1, int(image.width * ratio)), target_height)))
    label_height = 34
    gap = 12
    sheet = Image.new(
        "RGB",
        (sum(image.width for image in resized) + gap * 4, target_height + label_height + gap * 2),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    x = gap
    for label, image in zip(("ORIGINAL", "STAGE1 BARS", "FINAL FUSION"), resized, strict=True):
        draw.text((x, 8), label, fill="black")
        sheet.paste(image, (x, label_height))
        x += image.width + gap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def _invalid(case_id: str, category: str, **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "status": "invalid",
        "failure_category": category,
        "excluded_from_denominator": True,
        **extra,
    }


def _run_case(case: dict[str, Any], *, out_dir: Path) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "unnamed_case")
    source = _resolve(str(case.get("source_image_path") or ""))
    report_path = _resolve(str(case.get("report_path") or ""))
    if not source.is_file() or not report_path.is_file():
        return _invalid(
            case_id,
            "triad_evidence_missing",
            source_image_path=str(source),
            report_path=str(report_path),
        )
    actual_checksum = _sha256(source)
    expected_checksum = str(case.get("screenshot_sha256") or "")
    if not expected_checksum or actual_checksum != expected_checksum:
        return _invalid(
            case_id,
            "stale_fixture",
            expected_checksum=expected_checksum,
            actual_checksum=actual_checksum,
            source_image_path=str(source),
        )
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    report_source = _resolve(str(report.get("source_image_path") or ""))
    stage1_payload = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    stage1 = _resolve(str(stage1_payload.get("overlay_path") or ""))
    final = _resolve(str(fusion.get("compiled_overlay_path") or ""))
    if report_source != source or not stage1.is_file() or not final.is_file():
        return _invalid(
            case_id,
            "triad_evidence_missing",
            source_image_path=str(source),
            report_source_image_path=str(report_source),
            stage1_overlay_path=str(stage1),
            final_overlay_path=str(final),
        )

    with Image.open(source) as image:
        width, height = image.size
    expected_regions = [item for item in case.get("expected_regions", []) if isinstance(item, dict)]
    actual_regions = [item for item in stage1_payload.get("regions", []) if isinstance(item, dict)]
    unused_actual = set(range(len(actual_regions)))
    matches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    passed = 0
    max_error = 0.0
    for expected in expected_regions:
        expected_bbox = _bbox(expected.get("bbox"))
        family = _region_family(expected)
        candidates: list[tuple[float, int, dict[str, float]]] = []
        if expected_bbox:
            for index in unused_actual:
                actual = actual_regions[index]
                actual_bbox = _bbox(actual.get("bbox"))
                if _region_family(actual) != family or not actual_bbox:
                    continue
                errors = _boundary_error(expected_bbox, actual_bbox, width=width, height=height)
                candidates.append((max(errors.values()), index, errors))
        if not candidates:
            missing.append(expected)
            continue
        error, index, errors = min(candidates)
        unused_actual.remove(index)
        max_error = max(max_error, error)
        matched = error <= 0.10
        passed += int(matched)
        matches.append(
            {
                "family": family,
                "expected_bbox": expected_bbox,
                "actual_bbox": _bbox(actual_regions[index].get("bbox")),
                "normalized_boundary_error": errors,
                "passed": matched,
            }
        )
    unexpected = [actual_regions[index] for index in sorted(unused_actual)]
    attempted = len(expected_regions) + len(unexpected)
    rate: float | str = round(passed / attempted, 4) if attempted else "not_covered"
    stage1_boxes = {
        tuple(box.values())
        for item in actual_regions
        for box in [_bbox(item.get("bbox"))]
        if box
    }
    fused_review_boxes = [item for item in fusion.get("fused_review_boxes", []) if isinstance(item, dict)]
    content_boxes = []
    actual_elements: list[dict[str, Any]] = []
    for item in fused_review_boxes:
        item_bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if item_bbox and tuple(item_bbox.values()) not in stage1_boxes:
            content_boxes.append(item_bbox)
            actual_elements.append(item)
    final_content_vertical_coverage = round(
        max((box["y"] + box["h"] for box in content_boxes), default=0) / max(1, height),
        4,
    )
    min_final_coverage = float(case.get("min_final_content_vertical_coverage") or 0.0)
    failure_categories: list[str] = []
    if min_final_coverage and final_content_vertical_coverage < min_final_coverage:
        failure_categories.append("final_content_coverage_below_threshold")
    expected_elements = [item for item in case.get("expected_elements", []) if isinstance(item, dict)]
    golden_element_localization = _score_expected_elements(expected_elements, actual_elements)
    if expected_elements and golden_element_localization["rate"] < 0.95:
        failure_categories.append("golden_element_localization_below_threshold")
    contact_sheet = out_dir / "triads" / f"{case_id}.png"
    _contact_sheet(source, stage1, final, contact_sheet)
    case_passed = bool(
        attempted
        and rate >= 0.95
        and not missing
        and not unexpected
        and max_error <= 0.10
        and (not expected_elements or golden_element_localization["rate"] >= 0.95)
        and (
            not expected_elements
            or golden_element_localization["max_center_offset_ratio"] <= 0.10
        )
        and not failure_categories
    )
    return {
        "case_id": case_id,
        "status": "passed" if case_passed else "failed",
        "source_image_path": str(source),
        "stage1_overlay_path": str(stage1),
        "final_overlay_path": str(final),
        "triad_contact_sheet_path": str(contact_sheet),
        "structure_region_match_rate": {"passed": passed, "attempted": attempted, "rate": rate},
        "max_normalized_boundary_error": round(max_error, 4),
        "final_content_vertical_coverage": final_content_vertical_coverage,
        "minimum_final_content_vertical_coverage": min_final_coverage or "not_required",
        "golden_element_localization": golden_element_localization,
        "failure_categories": failure_categories,
        "matches": matches,
        "missing_regions": missing,
        "unexpected_regions": unexpected,
    }


def run_benchmark(manifest_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    manifest = json.loads(_resolve(manifest_path).read_text(encoding="utf-8-sig"))
    destination = _resolve(out_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results = [_run_case(case, out_dir=destination) for case in manifest.get("cases", []) if isinstance(case, dict)]
    valid = [item for item in results if item.get("status") != "invalid"]
    element_attempted = sum(
        int((item.get("golden_element_localization") or {}).get("attempted") or 0)
        for item in valid
    )
    element_passed = sum(
        int((item.get("golden_element_localization") or {}).get("passed") or 0)
        for item in valid
    )
    element_offsets = [
        float(metric.get("max_center_offset_ratio") or 0.0)
        for item in valid
        for metric in [item.get("golden_element_localization") or {}]
        if int(metric.get("attempted") or 0) > 0
    ]
    aggregate_element_metric = {
        "passed": element_passed,
        "attempted": element_attempted,
        "rate": round(element_passed / element_attempted, 4) if element_attempted else "not_covered",
        "max_center_offset_ratio": round(max(element_offsets), 4) if element_offsets else "not_covered",
    }
    automated_gate_passed = bool(valid) and all(item.get("status") == "passed" for item in valid)
    report = {
        "contract_version": "learning_structure_triad_report_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "metric_contract": {
            "structure_region_match_threshold": 0.95,
            "max_normalized_boundary_error": 0.10,
            "golden_element_localization_threshold": 0.95,
            "golden_element_minimum_iou": 0.65,
            "golden_element_max_center_offset_ratio": 0.10,
            "invalid_excluded_from_denominator": True,
            "interpretation": "review fixture metric only; not model accuracy or runtime reliability",
        },
        "summary": {
            "attempted": len(valid),
            "passed": sum(1 for item in valid if item.get("status") == "passed"),
            "failed": sum(1 for item in valid if item.get("status") == "failed"),
            "invalid": sum(1 for item in results if item.get("status") == "invalid"),
            "golden_element_localization": aggregate_element_metric,
        },
        "recognition_regression_workflow": {
            "stages": [
                "validate_same_source_triad",
                "score_structure_regions",
                "score_golden_elements",
                "require_manual_three_image_review",
            ],
            "automated_gate_status": "passed" if automated_gate_passed else "failed",
            "manual_visual_review_required": True,
            "manual_visual_review_input": "original screenshot + Stage1 bar overlay + final fusion overlay",
            "interpretation": "fixture regression workflow; not general model accuracy",
        },
        "cases": results,
        "safety": {"live_clicks": 0, "live_fills": 0, "live_submits": 0},
    }
    report_path = destination / "learning_structure_triad_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit original, Stage1 bars, and final fusion images together.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(args.manifest, args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["report_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
