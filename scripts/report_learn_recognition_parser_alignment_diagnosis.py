from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.parsers import parse_existing_evidence_to_inventory


def run_parser_alignment_diagnosis(
    *,
    batch_report_path: str | Path,
    support_manifest_path: str | Path,
    support_case_id: str,
    out_dir: str | Path,
    case_id_contains: str = "",
    json_stdout: bool = False,
) -> dict[str, Any]:
    batch_report_path = Path(batch_report_path)
    support_manifest_path = Path(support_manifest_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    batch_report = _read_json(batch_report_path)
    support_manifest = _read_json(support_manifest_path)
    support_bundle = _support_bundle_from_manifest(support_manifest, support_case_id)
    support_items = _reference_support_items(support_bundle)

    metric = {"passed": 0, "attempted": 0, "rate": "not_covered"}
    failure_categories: dict[str, int] = {}
    case_results: list[dict[str, Any]] = []
    for case in batch_report.get("case_results") if isinstance(batch_report.get("case_results"), list) else []:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "")
        if case_id_contains and case_id_contains not in case_id:
            continue
        actual_path = _resolve_path(case.get("actual_parser_output_path"), base=batch_report_path.parent)
        if not actual_path.exists():
            continue
        actual_output = _read_json(actual_path)
        actual_items = _vision_items(actual_output)
        support_results = []
        for support in support_items:
            metric["attempted"] += 1
            match = _best_label_match(support, actual_items)
            result = _alignment_result(support=support, actual=match)
            if result["status"] == "passed":
                metric["passed"] += 1
            else:
                category = str(result["failure_category"])
                failure_categories[category] = int(failure_categories.get(category, 0)) + 1
            support_results.append(result)
        case_results.append(
            {
                "case_id": case.get("case_id"),
                "actual_parser_output_path": str(actual_path),
                "support_case_id": support_case_id,
                "support_results": support_results,
            }
        )

    _finalize_metric(metric)
    actionability_diagnosis = _actionability_diagnosis(metric=metric, failure_categories=failure_categories)
    report = {
        "contract_version": "learn_parser_alignment_diagnosis_v1",
        "batch_report_path": str(batch_report_path),
        "support_manifest_path": str(support_manifest_path),
        "support_case_id": support_case_id,
        "case_id_contains": case_id_contains,
        "metrics": {
            "parser_bbox_alignment": metric,
        },
        "failure_categories": failure_categories,
        "actionability_diagnosis": actionability_diagnosis,
        "case_results": case_results,
        "interpretation": (
            "diagnoses actual parser bbox alignment against existing reference controls; "
            "this is not model accuracy, not click success, and not Execute authorization"
        ),
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    report_path = out_dir / "learn_parser_alignment_diagnosis_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _support_bundle_from_manifest(manifest: dict[str, Any], case_id: str) -> dict[str, Any]:
    for case in manifest.get("cases") if isinstance(manifest.get("cases"), list) else []:
        if isinstance(case, dict) and str(case.get("case_id") or "") == str(case_id):
            bundle = case.get("observe_bundle")
            if isinstance(bundle, dict):
                return bundle
            path_value = case.get("recorded_parser_output_path")
            if path_value:
                path = _resolve_path(path_value, base=Path("artifacts/benchmarks"))
                payload = _read_json(path)
                bundle = payload.get("observe_bundle")
                if isinstance(bundle, dict):
                    return bundle
    raise ValueError(f"support case not found or has no observe bundle: {case_id}")


def _reference_support_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    items = parse_existing_evidence_to_inventory(bundle)
    return [
        item
        for item in items
        if str(item.get("evidence_level") or "").casefold() != "semantic_region_only"
        and str(item.get("item_type") or "").casefold() in {"actionable", "form_field"}
    ]


def _vision_items(actual_output: dict[str, Any]) -> list[dict[str, Any]]:
    items = actual_output.get("screen_inventory")
    if not isinstance(items, list):
        bundle = actual_output.get("observe_bundle")
        items = parse_existing_evidence_to_inventory(bundle) if isinstance(bundle, dict) else []
    return [
        item
        for item in items
        if isinstance(item, dict)
        and "vision" in {str(source).casefold() for source in item.get("source_evidence", []) if isinstance(item.get("source_evidence"), list)}
    ]


def _best_label_match(support: dict[str, Any], actual_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0.0
    for item in actual_items:
        score = _label_score(str(support.get("label") or ""), str(item.get("label") or ""))
        if _role_compatible(support, item):
            score += 0.25
        if score > best_score:
            best = item
            best_score = score
    if best_score < 0.35:
        return None
    return best


def _alignment_result(*, support: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, Any]:
    if actual is None:
        return {
            "status": "failed",
            "failure_category": "no_label_compatible_actual_parser_item",
            "support_label": support.get("label"),
            "support_bbox": support.get("bbox"),
            "actual_label": "",
            "actual_bbox": {},
            "overlap": _empty_overlap(),
        }
    overlap = _bbox_overlap(
        support.get("bbox") if isinstance(support.get("bbox"), dict) else {},
        actual.get("bbox") if isinstance(actual.get("bbox"), dict) else {},
    )
    passed = _overlap_is_acceptable(overlap)
    return {
        "status": "passed" if passed else "failed",
        "failure_category": "" if passed else "model_bbox_not_overlapping_reference",
        "support_label": support.get("label"),
        "support_role": support.get("role"),
        "support_bbox": support.get("bbox"),
        "actual_label": actual.get("label"),
        "actual_role": actual.get("role"),
        "actual_bbox": actual.get("bbox"),
        "center_delta_px": _center_delta(
            support.get("bbox") if isinstance(support.get("bbox"), dict) else {},
            actual.get("bbox") if isinstance(actual.get("bbox"), dict) else {},
        ),
        "overlap": overlap,
    }


def _label_score(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    return len(intersection) / max(len(left_tokens), len(right_tokens))


def _tokens(value: str) -> set[str]:
    aliases = {
        "keyword": "search",
        "field": "input",
        "button": "button",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", value.casefold()):
        tokens.add(aliases.get(token, token))
    return tokens


def _role_compatible(support: dict[str, Any], actual: dict[str, Any]) -> bool:
    left = str(support.get("role") or support.get("item_type") or "").casefold()
    right = str(actual.get("role") or actual.get("item_type") or "").casefold()
    if not left or not right:
        return False
    if "input" in left and "input" in right:
        return True
    if "button" in left and "button" in right:
        return True
    return left == right


def _overlap_is_acceptable(overlap: dict[str, float]) -> bool:
    if overlap["iou"] >= 0.35:
        return True
    return overlap["support_coverage"] >= 0.65 and overlap["actual_coverage"] >= 0.65


def _bbox_overlap(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    ax, ay, aw, ah = _bbox_numbers(a)
    bx, by, bw, bh = _bbox_numbers(b)
    area_a = aw * ah
    area_b = bw * bh
    if area_a <= 0 or area_b <= 0:
        return _empty_overlap()
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = area_a + area_b - intersection
    return {
        "iou": round(intersection / union, 4) if union else 0.0,
        "support_coverage": round(intersection / area_a, 4),
        "actual_coverage": round(intersection / area_b, 4),
        "area_ratio_actual_to_support": round(area_b / area_a, 4) if area_a else 0.0,
    }


def _center_delta(support_bbox: dict[str, Any], actual_bbox: dict[str, Any]) -> dict[str, float]:
    sx, sy, sw, sh = _bbox_numbers(support_bbox)
    ax, ay, aw, ah = _bbox_numbers(actual_bbox)
    return {
        "dx": round((ax + aw / 2.0) - (sx + sw / 2.0), 4),
        "dy": round((ay + ah / 2.0) - (sy + sh / 2.0), 4),
    }


def _actionability_diagnosis(*, metric: dict[str, Any], failure_categories: dict[str, int]) -> dict[str, Any]:
    attempted = int(metric.get("attempted") or 0)
    passed = int(metric.get("passed") or 0)
    failed = max(0, attempted - passed)
    if attempted == 0:
        status = "not_covered"
        root_cause = "no comparable reference controls were evaluated"
    elif failed == 0:
        status = "alignment_passed"
        root_cause = "actual parser bbox overlaps reference interactive controls"
    elif failure_categories.get("model_bbox_not_overlapping_reference"):
        status = "blocked_by_parser_bbox_alignment"
        root_cause = "actual parser bbox does not overlap reference interactive controls"
    else:
        status = "blocked_by_parser_alignment_unknown"
        root_cause = "actual parser output does not satisfy reference alignment checks"
    return {
        "status": status,
        "attempted_alignment_count": attempted,
        "passed_alignment_count": passed,
        "failed_alignment_count": failed,
        "root_cause": root_cause,
        "fix_location": "learn_recognition_parser_or_cross_evidence_adapter",
        "why_not_pathgraph_only": "PathGraph must not consume semantic-only or misaligned parser boxes as executable ROI candidates",
        "recommended_intervention": (
            "fix parser coordinate/bbox alignment or attach same-screenshot UIA/OmniParser/calibrated target support before ROI grounding"
        ),
        "safety_impact": "does not loosen safety; keeps misaligned semantic-only regions out of ROI grounding and Execute",
    }


def _empty_overlap() -> dict[str, float]:
    return {"iou": 0.0, "support_coverage": 0.0, "actual_coverage": 0.0, "area_ratio_actual_to_support": 0.0}


def _bbox_numbers(value: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _float(value.get("x")),
        _float(value.get("y")),
        max(0.0, _float(value.get("w"))),
        max(0.0, _float(value.get("h"))),
    )


def _finalize_metric(metric: dict[str, Any]) -> None:
    attempted = int(metric.get("attempted") or 0)
    passed = int(metric.get("passed") or 0)
    metric["attempted"] = attempted
    metric["passed"] = passed
    metric["rate"] = "not_covered" if attempted == 0 else round(passed / attempted, 4)


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _resolve_path(value: Any, *, base: Path) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return (base / path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-report", required=True)
    parser.add_argument("--support-manifest", required=True)
    parser.add_argument("--support-case-id", required=True)
    parser.add_argument("--case-id-contains", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_parser_alignment_diagnosis(
        batch_report_path=args.batch_report,
        support_manifest_path=args.support_manifest,
        support_case_id=args.support_case_id,
        out_dir=args.out,
        case_id_contains=args.case_id_contains,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
