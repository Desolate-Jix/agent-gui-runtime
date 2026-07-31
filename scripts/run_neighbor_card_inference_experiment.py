from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.layout_regularization import (
    infer_neighbor_card_candidates,
)


MANIFEST_CONTRACT = "learn_neighbor_card_inference_experiment_manifest_v1"
REPORT_CONTRACT = "learn_neighbor_card_inference_experiment_report_v1"


def run_neighbor_card_inference_experiment(
    *,
    manifest_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    manifest_file = _resolve(manifest_path, root=root)
    output_dir = _resolve(out_dir, root=root)
    manifest = _read_json(manifest_file)
    if manifest.get("contract_version") != MANIFEST_CONTRACT:
        raise ValueError("unsupported neighbor card inference experiment manifest")

    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    for index, raw_case in enumerate(manifest.get("cases") or [], start=1):
        if not isinstance(raw_case, dict):
            continue
        case_id = str(raw_case.get("case_id") or f"case_{index}").strip()
        source_image_path = _resolve(raw_case.get("source_image_path"), root=root)
        replay_report_path = _resolve(raw_case.get("replay_report_path"), root=root)
        fixture_error = _fixture_error(
            case_id=case_id,
            source_image_path=source_image_path,
            expected_sha256=str(raw_case.get("source_image_sha256") or ""),
            replay_report_path=replay_report_path,
        )
        if fixture_error is not None:
            invalid_cases.append(fixture_error)
            continue

        expected_boxes = _valid_bboxes(raw_case.get("expected_card_bboxes"))
        if not expected_boxes:
            invalid_cases.append(
                {
                    "case_id": case_id,
                    "failure_category": "missing_expected_card_annotations",
                    "source_image_path": str(source_image_path),
                }
            )
            continue

        replay_report = _read_json(replay_report_path)
        candidates = _card_candidates(replay_report)
        inference = infer_neighbor_card_candidates(
            image_path=source_image_path,
            candidates=candidates,
            minimum_group_size=int(raw_case.get("minimum_group_size") or 3),
            minimum_visual_support=float(
                raw_case.get("minimum_visual_support")
                if raw_case.get("minimum_visual_support") is not None
                else 0.45
            ),
        )
        baseline_matches = _baseline_expected_matches(expected_boxes, candidates)
        proposal_matches = _proposal_expected_matches(
            expected_boxes,
            inference["proposals"],
        )
        after_matches = baseline_matches | proposal_matches["expected_indexes"]
        before_metric = _metric(
            passed=len(baseline_matches),
            attempted=len(expected_boxes),
            interpretation=(
                "human-annotated structural cards containing an existing semantic card seed"
            ),
        )
        after_metric = _metric(
            passed=len(after_matches),
            attempted=len(expected_boxes),
            interpretation=(
                "same fixture after adding review-only one-hop neighbor proposals"
            ),
        )
        precision_metric = _metric(
            passed=proposal_matches["matched_proposal_count"],
            attempted=len(inference["proposals"]),
            interpretation=(
                "neighbor proposals overlapping a human-annotated structural card; "
                "single fixture only"
            ),
        )
        case_dir = output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        result_path = case_dir / "neighbor_card_inference_result.json"
        result_path.write_text(
            json.dumps(inference, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        overlay_path = case_dir / "neighbor_card_inference_overlay.png"
        _draw_overlay(
            source_image_path=source_image_path,
            expected_boxes=expected_boxes,
            candidates=candidates,
            proposals=inference["proposals"],
            output_path=overlay_path,
        )
        before_rate = float(before_metric["rate"])
        after_rate = float(after_metric["rate"])
        cases.append(
            {
                "case_id": case_id,
                "status": inference["status"],
                "seed_candidate_count": inference["seed_candidate_count"],
                "proposal_count": inference["proposal_count"],
                "structural_card_recall_before": before_metric,
                "structural_card_recall_after": after_metric,
                "neighbor_proposal_precision": precision_metric,
                "recall_rate_delta": round(after_rate - before_rate, 4),
                "false_positive_proposal_count": (
                    len(inference["proposals"])
                    - proposal_matches["matched_proposal_count"]
                ),
                "source_image_path": str(source_image_path),
                "replay_report_path": str(replay_report_path),
                "overlay_path": str(overlay_path),
                "result_path": str(result_path),
            }
        )

    report = {
        "contract_version": REPORT_CONTRACT,
        "manifest_path": str(manifest_file),
        "case_count": len(cases),
        "invalid_case_count": len(invalid_cases),
        "cases": cases,
        "invalid_cases": invalid_cases,
        "interpretation": (
            "single-fixture offline comparison of a one-hop same-class neighbor prior; "
            "rates describe human-annotated fixture coverage, not model accuracy, "
            "general card-recognition reliability, or Execute success"
        ),
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
    }
    report_path = output_dir / "neighbor_card_inference_experiment_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    demo_path = output_dir / "DEMO.md"
    demo_path.write_text(_demo_markdown(report), encoding="utf-8")
    report["report_path"] = str(report_path)
    report["demo_index_path"] = str(demo_path)
    return report


def _fixture_error(
    *,
    case_id: str,
    source_image_path: Path,
    expected_sha256: str,
    replay_report_path: Path,
) -> dict[str, Any] | None:
    if not source_image_path.is_file() or not replay_report_path.is_file():
        return {
            "case_id": case_id,
            "failure_category": "missing_fixture",
            "source_image_path": str(source_image_path),
            "replay_report_path": str(replay_report_path),
        }
    actual_sha256 = hashlib.sha256(source_image_path.read_bytes()).hexdigest()
    if not expected_sha256 or actual_sha256 != expected_sha256.casefold():
        return {
            "case_id": case_id,
            "failure_category": "stale_fixture",
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
            "source_image_path": str(source_image_path),
        }
    return None


def _card_candidates(replay_report: dict[str, Any]) -> list[dict[str, Any]]:
    fusion = (
        replay_report.get("fusion")
        if isinstance(replay_report.get("fusion"), dict)
        else {}
    )
    boxes = (
        fusion.get("fused_review_boxes")
        if isinstance(fusion.get("fused_review_boxes"), list)
        else []
    )
    return [
        item
        for item in boxes
        if isinstance(item, dict)
        and str(item.get("box_type") or "").casefold() == "subregion_group"
        and str(item.get("role") or "").casefold() == "tile_card_parent"
        and item.get("render_in_main_overlay") is not False
    ]


def _valid_bboxes(value: Any) -> list[dict[str, int]]:
    if not isinstance(value, list):
        return []
    boxes: list[dict[str, int]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            bbox = {
                key: int(round(float(item.get(key) or 0)))
                for key in ("x", "y", "w", "h")
            }
        except (TypeError, ValueError):
            continue
        if bbox["w"] > 0 and bbox["h"] > 0:
            boxes.append(bbox)
    return boxes


def _baseline_expected_matches(
    expected_boxes: list[dict[str, int]],
    candidates: list[dict[str, Any]],
) -> set[int]:
    matches: set[int] = set()
    for expected_index, expected in enumerate(expected_boxes):
        for candidate in candidates:
            bbox = candidate.get("bbox")
            if isinstance(bbox, dict) and _contains_center(expected, bbox):
                matches.add(expected_index)
                break
    return matches


def _proposal_expected_matches(
    expected_boxes: list[dict[str, int]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_indexes: set[int] = set()
    matched_proposals = 0
    for proposal in proposals:
        bbox = proposal.get("bbox")
        if not isinstance(bbox, dict):
            continue
        best_index = max(
            range(len(expected_boxes)),
            key=lambda index: _bbox_iou(expected_boxes[index], bbox),
            default=-1,
        )
        if best_index >= 0 and _bbox_iou(expected_boxes[best_index], bbox) >= 0.5:
            expected_indexes.add(best_index)
            matched_proposals += 1
    return {
        "expected_indexes": expected_indexes,
        "matched_proposal_count": matched_proposals,
    }


def _metric(*, passed: int, attempted: int, interpretation: str) -> dict[str, Any]:
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "interpretation": interpretation,
    }


def _contains_center(container: dict[str, Any], child: dict[str, Any]) -> bool:
    center_x = float(child.get("x") or 0) + float(child.get("w") or 0) / 2.0
    center_y = float(child.get("y") or 0) + float(child.get("h") or 0) / 2.0
    return (
        float(container["x"]) <= center_x <= float(container["x"] + container["w"])
        and float(container["y"])
        <= center_y
        <= float(container["y"] + container["h"])
    )


def _bbox_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    x1 = max(float(left["x"]), float(right["x"]))
    y1 = max(float(left["y"]), float(right["y"]))
    x2 = min(
        float(left["x"] + left["w"]),
        float(right["x"] + right["w"]),
    )
    y2 = min(
        float(left["y"] + left["h"]),
        float(right["y"] + right["h"]),
    )
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (
        float(left["w"] * left["h"])
        + float(right["w"] * right["h"])
        - intersection
    )
    return intersection / union if union > 0 else 0.0


def _draw_overlay(
    *,
    source_image_path: Path,
    expected_boxes: list[dict[str, int]],
    candidates: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    output_path: Path,
) -> None:
    with Image.open(source_image_path) as source:
        image = source.convert("RGBA")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for bbox in expected_boxes:
        _draw_dashed_bbox(draw, bbox, color=(122, 76, 190, 230), width=3)
    for candidate in candidates:
        bbox = candidate.get("bbox")
        if isinstance(bbox, dict):
            _draw_bbox(draw, bbox, color=(230, 135, 30, 230), width=3)
    for proposal in proposals:
        bbox = proposal.get("bbox")
        if not isinstance(bbox, dict):
            continue
        _draw_bbox(draw, bbox, color=(16, 151, 101, 245), width=5)
        label = f"neighbor · {proposal.get('score')}"
        draw.text(
            (int(bbox["x"]) + 4, int(bbox["y"]) + 4),
            label,
            fill=(16, 80, 62, 255),
            font=font,
        )
    image.convert("RGB").save(output_path)


def _draw_bbox(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    x = int(bbox["x"])
    y = int(bbox["y"])
    w = int(bbox["w"])
    h = int(bbox["h"])
    draw.rectangle((x, y, x + w, y + h), outline=color, width=width)


def _draw_dashed_bbox(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    x = int(bbox["x"])
    y = int(bbox["y"])
    w = int(bbox["w"])
    h = int(bbox["h"])
    dash = 12
    for start in range(0, w, dash * 2):
        draw.line((x + start, y, x + min(w, start + dash), y), fill=color, width=width)
        draw.line(
            (x + start, y + h, x + min(w, start + dash), y + h),
            fill=color,
            width=width,
        )
    for start in range(0, h, dash * 2):
        draw.line((x, y + start, x, y + min(h, start + dash)), fill=color, width=width)
        draw.line(
            (x + w, y + start, x + w, y + min(h, start + dash)),
            fill=color,
            width=width,
        )


def _demo_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Neighbor Card Inference Experiment",
        "",
        "- Scope: checksum-pinned, offline, read-only fixture comparison.",
        "- Purple dashed: human-annotated structural cards.",
        "- Orange: existing semantic card seeds.",
        "- Green: one-hop same-class neighbor proposals.",
        "- No model call, click, fill, or submit.",
        "",
        "| Case | Before | After | Proposal precision | Delta |",
        "|---|---:|---:|---:|---:|",
    ]
    for case in report.get("cases") or []:
        before = case["structural_card_recall_before"]
        after = case["structural_card_recall_after"]
        precision = case["neighbor_proposal_precision"]
        lines.append(
            f"| {case['case_id']} | {before['passed']}/{before['attempted']} | "
            f"{after['passed']}/{after['attempted']} | "
            f"{precision['passed']}/{precision['attempted']} | "
            f"{case['recall_rate_delta']:+.4f} |"
        )
        lines.extend(
            [
                "",
                f"- [Overlay]({case['overlay_path']})",
                f"- [Structured result]({case['result_path']})",
            ]
        )
    return "\n".join(lines) + "\n"


def _resolve(value: Any, *, root: Path) -> Path:
    path = Path(str(value or ""))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_neighbor_card_inference_experiment(
        manifest_path=args.manifest,
        out_dir=args.out,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report['report_path']}")
        print(f"demo_index_path={report['demo_index_path']}")


if __name__ == "__main__":
    main()
