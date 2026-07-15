from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.experiments.hierarchical_region_partition import (
    RegionFrame,
    SCHEMA_VERSION,
    build_anonymous_candidates,
    compile_hierarchical_regions,
)
from app.vision.local_provider import LocalVisionProvider


PROMPT = """Organize anonymous visual candidates from one screenshot into a two-level region tree. Return JSON only.

Evidence protocol:
- candidate_columns defines the compact fields in candidate_rows.
- The only valid candidate IDs are exactly the first values present in candidate_rows. Never synthesize, continue, or enumerate IDs that are absent.
- Geometry and the numbered overlay are evidence. Do not output bbox or pixel coordinates.

Organization procedure:
1. Inspect the screenshot for visible columns, panels, whitespace separators, and large content blocks.
2. Select only candidate IDs that support each region. Do not merge all candidates into one region merely because a broad container exists.
3. Use one to six Level 1 regions for major visible areas. One Level 1 region is valid only when the surface genuinely has no clearly independent panel or column.
4. Use Level 2 children for clearly independent panels inside a broad parent. Every child candidate must also appear in its parent's source_candidate_ids.
5. Do not split buttons, icons, or text into regions. Do not infer top, left, right, or bottom bars from position alone.
6. A local input or status area may be a child; it must not become a whole-window bottom region.
7. When candidates cannot express a visible region, add a structured candidate_gaps object instead of inventing geometry.

Output contract:
- schema_version: exactly hierarchical_region_partition_mvp_v1
- page_type: short generic free-text summary
- regions: array of objects with region_id, level, parent_id, source_candidate_ids, content_summary, optional_role, confidence, children
- region_id: unique R1/R2 style value; child IDs may use R1.1 style
- level: integer 1 or 2
- parent_id: root for Level 1, an existing Level 1 region ID for Level 2
- source_candidate_ids: non-empty array containing only IDs present in candidate_rows
- optional_role: navigation, list, content, toolbar, composer, status, media, or unknown
- confidence: number from 0 to 1
- children: array of child region IDs
- unassigned_candidate_ids: array of valid candidate IDs not used by any region
- candidate_gaps: array of objects with description and approximate_location
"""


def run_case(
    *,
    case: dict[str, Any],
    out_dir: Path,
    recorded_model_payload: dict[str, Any] | None = None,
    endpoint: str | None = None,
    model_name: str | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "case").strip()
    case_dir = out_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    trial_path = _resolve_path(str(case.get("trial_result_path") or ""))
    trial = _read_json(trial_path)
    image_path = _trial_image_path(trial, trial_path.parent)
    with Image.open(image_path) as image:
        image_size = {"width": image.width, "height": image.height}

    inventory = trial.get("screen_inventory") if isinstance(trial.get("screen_inventory"), list) else []
    candidates = build_anonymous_candidates(inventory, image_size)
    screenshot_copy = case_dir / "screenshot.png"
    shutil.copyfile(image_path, screenshot_copy)
    candidate_overlay = _render_candidate_overlay(image_path, candidates, case_dir / "candidate_overlay.png")
    prompt_payload = _build_prompt_payload(candidates, image_size)
    prompt_text = f"{PROMPT}\n\nCandidate evidence:\n{json.dumps(prompt_payload, ensure_ascii=False, separators=(',', ':'))}"
    (case_dir / "model_prompt.json").write_text(
        json.dumps({"prompt": prompt_text, "prompt_input": prompt_payload}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if recorded_model_payload is not None:
        parsed = recorded_model_payload
        raw_text = json.dumps(recorded_model_payload, ensure_ascii=False, indent=2)
        source_type = "recorded_model_output"
    else:
        if not endpoint or not model_name:
            raise ValueError("endpoint and model_name are required without recorded_model_payload")
        provider = LocalVisionProvider(endpoint=endpoint, model_name=model_name, timeout_seconds=timeout_seconds)
        raw_response = provider._call_openai_compatible_endpoint(  # noqa: SLF001
            candidate_overlay,
            prompt_text,
            max_tokens=3072,
            temperature=0.0,
        )
        raw_text = provider._extract_message_text(raw_response)  # noqa: SLF001
        parsed = provider._parse_json_object(raw_text)  # noqa: SLF001
        source_type = "actual_model_call"

    (case_dir / "model_raw_response.txt").write_text(raw_text + "\n", encoding="utf-8")
    (case_dir / "model_parsed_response.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    compiled = compile_hierarchical_regions(parsed, candidates, image_size)
    validator_path = case_dir / "validator_report.json"
    validator_path.write_text(json.dumps(compiled["validator"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    region_overlay = _render_region_overlay(image_path, compiled.get("regions", []), case_dir / "hierarchical_region_overlay.png")

    frame = RegionFrame(image_path=image_path, compiled=compiled)
    crop_paths: list[str] = []
    crop_failures: list[dict[str, str]] = []
    for region in compiled.get("regions", []):
        region_id = str(region.get("region_id") or "")
        try:
            crop_paths.append(str(frame.crop_region(region_id, case_dir / "crops")))
        except (KeyError, ValueError, OSError) as exc:
            crop_failures.append({"region_id": region_id, "error": str(exc)})

    old_summary = _old_v1_summary(trial)
    old_summary_path = case_dir / "old_v1_summary.json"
    old_summary_path.write_text(json.dumps(old_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old_v1_overlay = _render_old_v1_overlay(image_path, old_summary["regions"], case_dir / "old_v1_overlay.png")
    attempted_crops = len(compiled.get("regions", []))
    crop_rate: float | str = round(len(crop_paths) / attempted_crops, 4) if attempted_crops else "not_covered"
    validator = compiled["validator"]
    comparison_path = case_dir / "comparison_report.json"
    report = {
        "contract_version": "hierarchical_region_partition_case_report_v1",
        "case_id": case_id,
        "source_type": source_type,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks": 0,
        "trial_result_path": str(trial_path),
        "screenshot_path": str(screenshot_copy),
        "candidate_overlay_path": str(candidate_overlay),
        "old_v1_overlay_path": str(old_v1_overlay),
        "region_overlay_path": str(region_overlay),
        "validator_report_path": str(validator_path),
        "old_v1_summary_path": str(old_summary_path),
        "comparison_report_path": str(comparison_path),
        "crop_paths": crop_paths,
        "crop_failures": crop_failures,
        "old_v1_summary": old_summary,
        "validator": validator,
        "regions": compiled.get("regions", []),
        "candidate_gaps": compiled.get("candidate_gaps", []),
        "metrics": {
            "candidate_count": len(candidates),
            "root_region_count": validator["root_region_count"],
            "child_region_count": validator["child_region_count"],
            "validator_pass": validator["valid"],
            "major_content_coverage": validator["major_content_coverage"],
            "severe_overlap_count": validator["severe_overlap_count"],
            "unassigned_candidate_ratio": validator["unassigned_candidate_ratio"],
            "candidate_gap_count": validator["candidate_gap_count"],
            "disconnected_union_count": validator["disconnected_union_count"],
            "crop_success_rate": crop_rate,
        },
        "known_old_issue": str(case.get("known_old_issue") or ""),
        "reviewer_notes": str(case.get("reviewer_notes") or "pending visual review"),
        "interpretation": "shadow evaluation only; no Execute, PathGraph promotion, click, fill, or submit",
    }
    comparison_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def run_manifest(
    manifest_path: Path,
    out_dir: Path,
    *,
    offline_outputs_path: Path | None = None,
    endpoint: str | None = None,
    model_name: str | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    cases = manifest.get("cases") if isinstance(manifest.get("cases"), list) else []
    offline_outputs = _read_json(offline_outputs_path) if offline_outputs_path else {}
    reports = []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("case_id") or "")
        recorded = offline_outputs.get(case_id) if isinstance(offline_outputs.get(case_id), dict) else None
        reports.append(
            run_case(
                case=case,
                out_dir=out_dir,
                recorded_model_payload=recorded,
                endpoint=endpoint,
                model_name=model_name,
                timeout_seconds=timeout_seconds,
            )
        )
    summary = {
        "contract_version": "hierarchical_region_partition_mvp_report_v1",
        "display_only": True,
        "actual_model_call": offline_outputs_path is None,
        "case_count": len(reports),
        "cases": reports,
        "interpretation": "per-case evidence only; no aggregate accuracy or production reliability claim",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "hierarchical_region_partition_mvp_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def _build_prompt_payload(candidates: list[dict[str, Any]], image_size: dict[str, int]) -> dict[str, Any]:
    edge_codes = {"left": "L", "top": "T", "right": "R", "bottom": "B"}
    return {
        "schema_version": SCHEMA_VERSION,
        "image_size": [image_size["width"], image_size["height"]],
        "candidate_count": len(candidates),
        "candidate_columns": ["id", "x", "y", "w", "h", "edges", "count", "sources"],
        "candidate_rows": [
            [
                candidate["candidate_id"],
                candidate["bbox"]["x"],
                candidate["bbox"]["y"],
                candidate["bbox"]["w"],
                candidate["bbox"]["h"],
                "".join(edge_codes[value] for value in candidate.get("touches_edges", []) if value in edge_codes),
                candidate["element_count"],
                candidate["source_types"],
            ]
            for candidate in candidates
        ],
    }


def _render_candidate_overlay(image_path: Path, candidates: list[dict[str, Any]], out_path: Path) -> Path:
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for item in candidates:
            box = item["bbox"]
            xy = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
            draw.rectangle(xy, outline=(230, 126, 0), width=2)
            draw.text((box["x"] + 2, box["y"] + 2), item["candidate_id"], fill=(255, 255, 255), stroke_width=2, stroke_fill=(160, 70, 0), font=font)
        image.save(out_path)
    return out_path


def _render_region_overlay(image_path: Path, regions: list[dict[str, Any]], out_path: Path) -> Path:
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for region in regions:
            box = region.get("bbox") if isinstance(region.get("bbox"), dict) else None
            if not box:
                continue
            level = int(region.get("level") or 0)
            color = (0, 104, 220) if level == 1 else (0, 158, 96)
            xy = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
            draw.rectangle(xy, outline=color, width=4 if level == 1 else 2)
            label = f'{region.get("region_id")} L{level} {region.get("optional_role")}'
            draw.text((box["x"] + 3, box["y"] + 3), label, fill=(255, 255, 255), stroke_width=2, stroke_fill=color, font=font)
        image.save(out_path)
    return out_path


def _render_old_v1_overlay(image_path: Path, regions: list[dict[str, Any]], out_path: Path) -> Path:
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        for index, region in enumerate(regions, start=1):
            box = region.get("bbox") if isinstance(region.get("bbox"), dict) else None
            if not box:
                continue
            left = max(0, min(image.width, int(box.get("x") or 0)))
            top = max(0, min(image.height, int(box.get("y") or 0)))
            right = max(left, min(image.width, left + int(box.get("w") or 0)))
            bottom = max(top, min(image.height, top + int(box.get("h") or 0)))
            if right <= left or bottom <= top:
                continue
            draw.rectangle((left, top, right, bottom), outline=(180, 40, 180), width=3)
            label = f'old-{index} {region.get("zone_id") or region.get("region_id")}'
            draw.text((left + 3, top + 3), label, fill=(255, 255, 255), stroke_width=2, stroke_fill=(120, 0, 120), font=font)
        image.save(out_path)
    return out_path


def _old_v1_summary(trial: dict[str, Any]) -> dict[str, Any]:
    understanding = trial.get("two_stage_understanding") if isinstance(trial.get("two_stage_understanding"), dict) else {}
    stage1 = understanding.get("stage1_structure") if isinstance(understanding.get("stage1_structure"), dict) else {}
    regions = stage1.get("structure_regions") if isinstance(stage1.get("structure_regions"), list) else []
    return {
        "contract_version": str(stage1.get("contract_version") or "unknown"),
        "region_count": len(regions),
        "regions": [
            {
                "region_id": str(item.get("region_id") or ""),
                "zone_id": str(item.get("zone_id") or ""),
                "bbox": item.get("bbox") if isinstance(item.get("bbox"), dict) else {},
            }
            for item in regions
            if isinstance(item, dict)
        ],
    }


def _trial_image_path(trial: dict[str, Any], base_dir: Path) -> Path:
    observe = trial.get("observe_bundle") if isinstance(trial.get("observe_bundle"), dict) else {}
    value = str(observe.get("source_image_path") or observe.get("image_path") or "").strip()
    if not value:
        understanding = trial.get("two_stage_understanding") if isinstance(trial.get("two_stage_understanding"), dict) else {}
        value = str(understanding.get("source_image_path") or "").strip()
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate read-only hierarchical region partitioning on saved screenshots.")
    parser.add_argument("--case-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--offline-model-output", type=Path)
    parser.add_argument("--model-profile", type=Path)
    parser.add_argument("--endpoint")
    parser.add_argument("--model-name")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    endpoint = args.endpoint
    model_name = args.model_name
    if args.model_profile:
        profile = _read_json(args.model_profile)
        endpoint = endpoint or str(profile.get("endpoint") or "")
        model_name = model_name or str(profile.get("model_name") or "")
    report = run_manifest(
        args.case_manifest,
        args.out,
        offline_outputs_path=args.offline_model_output,
        endpoint=endpoint,
        model_name=model_name,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps({"report_path": report["report_path"], "case_count": report["case_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
