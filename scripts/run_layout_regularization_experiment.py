from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.layout_regularization import regularize_repeated_card_layout


MANIFEST_CONTRACT = "learn_layout_regularization_experiment_manifest_v1"
REPORT_CONTRACT = "learn_layout_regularization_experiment_report_v1"


def run_layout_regularization_experiment(
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
        raise ValueError("unsupported layout regularization experiment manifest")

    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    for index, raw_case in enumerate(manifest.get("cases") or [], start=1):
        if not isinstance(raw_case, dict):
            continue
        case_id = str(raw_case.get("case_id") or f"case_{index}").strip()
        replay_report_path = _resolve(raw_case.get("replay_report_path"), root=root)
        source_image_path = _resolve(raw_case.get("source_image_path"), root=root)
        if not replay_report_path.exists() or not source_image_path.exists():
            invalid_cases.append(
                {
                    "case_id": case_id,
                    "failure_category": "missing_fixture",
                    "replay_report_path": str(replay_report_path),
                    "source_image_path": str(source_image_path),
                }
            )
            continue
        replay_report = _read_json(replay_report_path)
        candidates = _card_candidates(replay_report)
        result = regularize_repeated_card_layout(
            image_path=source_image_path,
            candidates=candidates,
            minimum_group_size=int(raw_case.get("minimum_group_size") or 3),
        )
        case_dir = output_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        result_path = case_dir / "layout_regularization_result.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        regularized_overlay_path = case_dir / "layout_regularized_overlay.png"
        _draw_regularized_overlay(
            source_image_path=source_image_path,
            result=result,
            output_path=regularized_overlay_path,
        )
        current_overlay_path = _resolve(
            (replay_report.get("overlay_status") or {}).get("path"),
            root=root,
        )
        comparison_path = case_dir / "original_current_regularized.png"
        _draw_comparison(
            source_image_path=source_image_path,
            current_overlay_path=current_overlay_path,
            regularized_overlay_path=regularized_overlay_path,
            output_path=comparison_path,
        )
        cases.append(
            {
                "case_id": case_id,
                "status": result["status"],
                "eligible_candidate_count": result["eligible_candidate_count"],
                "visual_rectangle_count": result["visual_rectangle_count"],
                "repeated_size_cluster_count": result["repeated_size_cluster_count"],
                "inferred_grid_slot_count": result["inferred_grid_slot_count"],
                "alignment_group_count": result["alignment_group_count"],
                "normalized_card_count": result["normalized_card_count"],
                "unregularized_candidate_count": len(result["unregularized_candidates"]),
                "source_image_path": str(source_image_path),
                "current_fusion_overlay_path": (
                    str(current_overlay_path) if current_overlay_path.exists() else ""
                ),
                "regularized_overlay_path": str(regularized_overlay_path),
                "comparison_path": str(comparison_path),
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
            "offline selective layout-regularization experiment; repeated visual rows and inferred "
            "grid slots can produce review-only normalized bboxes while unsupported layouts remain "
            "unchanged; this is not recognition accuracy or Execute evidence"
        ),
        "safety": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
    }
    report_path = output_dir / "layout_regularization_experiment_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    demo_index_path = output_dir / "DEMO.md"
    demo_index_path.write_text(_demo_markdown(report), encoding="utf-8")
    report["report_path"] = str(report_path)
    report["demo_index_path"] = str(demo_index_path)
    return report


def _card_candidates(replay_report: dict[str, Any]) -> list[dict[str, Any]]:
    fusion = replay_report.get("fusion") if isinstance(replay_report.get("fusion"), dict) else {}
    boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    return [
        item
        for item in boxes
        if isinstance(item, dict)
        and str(item.get("box_type") or "").casefold() == "subregion_group"
        and str(item.get("role") or "").casefold() == "tile_card_parent"
        and item.get("render_in_main_overlay") is not False
    ]


def _draw_regularized_overlay(
    *,
    source_image_path: Path,
    result: dict[str, Any],
    output_path: Path,
) -> None:
    with Image.open(source_image_path) as source:
        base = source.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()
    for group in result.get("alignment_groups") or []:
        group_id = str(group.get("group_id") or "")
        for item in group.get("items") or []:
            raw_bbox = item.get("raw_bbox") or {}
            normalized_bbox = item.get("layout_normalized_bbox") or {}
            _draw_dashed_bbox(draw, raw_bbox, color=(238, 139, 39, 220), width=2)
            _draw_bbox(draw, normalized_bbox, color=(16, 151, 101, 245), width=4)
            x = int(normalized_bbox.get("x") or 0)
            y = int(normalized_bbox.get("y") or 0)
            label = f"{group_id} · {item.get('source_candidate_id') or ''}"
            _draw_label(draw, x, y, label, font=font)
    Image.alpha_composite(base, overlay).convert("RGB").save(output_path)


def _draw_comparison(
    *,
    source_image_path: Path,
    current_overlay_path: Path,
    regularized_overlay_path: Path,
    output_path: Path,
) -> None:
    paths = [
        ("ORIGINAL", source_image_path),
        ("CURRENT FUSION", current_overlay_path if current_overlay_path.exists() else source_image_path),
        ("LAYOUT REGULARIZED", regularized_overlay_path),
    ]
    panel_width = 720
    panel_height = 500
    header_height = 34
    canvas = Image.new("RGB", (panel_width * len(paths), panel_height + header_height), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (label, path) in enumerate(paths):
        with Image.open(path) as image:
            panel = ImageOps.contain(image.convert("RGB"), (panel_width, panel_height))
        x = index * panel_width + (panel_width - panel.width) // 2
        y = header_height + (panel_height - panel.height) // 2
        canvas.paste(panel, (x, y))
        draw.text((index * panel_width + 10, 10), label, fill=(22, 35, 48), font=font)
    canvas.save(output_path)


def _draw_bbox(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    x = int(bbox.get("x") or 0)
    y = int(bbox.get("y") or 0)
    w = int(bbox.get("w") or 0)
    h = int(bbox.get("h") or 0)
    if w <= 0 or h <= 0:
        return
    draw.rectangle((x, y, x + w, y + h), outline=color, width=width)


def _draw_dashed_bbox(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    x = int(bbox.get("x") or 0)
    y = int(bbox.get("y") or 0)
    w = int(bbox.get("w") or 0)
    h = int(bbox.get("h") or 0)
    if w <= 0 or h <= 0:
        return
    dash = 10
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


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    font: ImageFont.ImageFont,
) -> None:
    left, top, right, bottom = draw.textbbox((x, y), label, font=font)
    draw.rectangle(
        (left, top, right + 6, bottom + 4),
        fill=(16, 151, 101, 230),
    )
    draw.text((x + 3, y + 2), label, fill="white", font=font)


def _demo_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Layout Regularization Experiment",
        "",
        "- Scope: offline, read-only; no model call, click, fill, or submit.",
        "- Orange dashed boxes: raw detected or inferred geometry before row normalization.",
        "- Green solid boxes: layout-normalized review proposals.",
        "- No repeated-layout evidence means no change; a no-op is not a failed recognition result.",
        "",
        "| Case | Groups | Normalized cards | Result |",
        "|---|---:|---:|---|",
    ]
    for case in report.get("cases") or []:
        lines.append(
            f"| {case['case_id']} | {case['alignment_group_count']} | "
            f"{case['normalized_card_count']} | {case['status']} |"
        )
    lines.extend(["", "## Evidence", ""])
    for case in report.get("cases") or []:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- [Three-way comparison]({case['comparison_path']})",
                f"- [Regularized overlay]({case['regularized_overlay_path']})",
                f"- [Structured result]({case['result_path']})",
                "",
            ]
        )
    return "\n".join(lines)


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
    result = run_layout_regularization_experiment(
        manifest_path=args.manifest,
        out_dir=args.out,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={result['report_path']}")
        print(f"demo_index_path={result['demo_index_path']}")


if __name__ == "__main__":
    main()
