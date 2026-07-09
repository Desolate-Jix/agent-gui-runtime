from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.model_server import ensure_model_server, profile_for_stage, stop_model_server
from app.learn.recognition.two_stage import STAGE1_REGION_LOCALIZATION_PROMPT
from app.vision.local_provider import LocalVisionProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one actual model call for stage1 region localization.")
    parser.add_argument("--stage1-report", required=True, help="Stage1 heuristic report JSON.")
    parser.add_argument("--out", required=True, help="Output directory for model probe artifacts.")
    parser.add_argument("--profile-id", default="qwen3_vl_8b_q4_k_m", help="Launchable model profile id.")
    parser.add_argument("--wait-seconds", type=float, default=600.0, help="Model readiness wait budget.")
    parser.add_argument("--timeout-seconds", type=float, default=300.0, help="Single model request timeout.")
    parser.add_argument("--stop-after", action="store_true", help="Stop the model after the probe if this script started it.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args()

    stage1_report_path = Path(args.stage1_report)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    stage1_report = json.loads(stage1_report_path.read_text(encoding="utf-8-sig"))
    image_path = _image_path_from_stage1_report(stage1_report)
    profile = profile_for_stage("learning", args.profile_id)
    start_status = ensure_model_server(
        stage="learning",
        profile_id=args.profile_id,
        wait_until_ready=True,
        wait_seconds=args.wait_seconds,
    )
    started_by_probe = bool(start_status.get("started"))
    server_after = start_status.get("after") if isinstance(start_status.get("after"), dict) else start_status.get("before")
    if not isinstance(server_after, dict) or server_after.get("status") != "running":
        raise RuntimeError(f"Model server not ready: {server_after}")

    prompt_input = _build_prompt_input(stage1_report)
    prompt = (
        f"{STAGE1_REGION_LOCALIZATION_PROMPT}\n\n"
        "Use the following coarse hints only as replaceable evidence. Return JSON only.\n\n"
        f"{json.dumps(prompt_input, ensure_ascii=False, indent=2)}"
    )
    provider = LocalVisionProvider(
        endpoint=str(profile.get("endpoint") or ""),
        model_name=str(profile.get("model_name") or ""),
        timeout_seconds=float(args.timeout_seconds),
    )
    raw_response = provider._call_openai_compatible_endpoint(  # noqa: SLF001
        image_path,
        prompt,
        max_tokens=2048,
        temperature=0.0,
    )
    raw_text = provider._extract_message_text(raw_response)  # noqa: SLF001
    parse_error = ""
    parsed: dict[str, Any] = {}
    try:
        parsed = provider._parse_json_object(raw_text)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_output_path = out_dir / f"stage1_region_model_raw_{timestamp}.txt"
    raw_output_path.write_text(raw_text + "\n", encoding="utf-8")
    prompt_path = out_dir / f"stage1_region_model_prompt_{timestamp}.json"
    prompt_path.write_text(
        json.dumps({"prompt": prompt, "prompt_input": prompt_input}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    overlay_path = _render_model_overlay(image_path=image_path, parsed=parsed, out_dir=out_dir, timestamp=timestamp)
    report = {
        "contract_version": "learn_stage1_region_model_probe_report_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "actual_model_call": True,
        "source_stage1_report_path": str(stage1_report_path),
        "image_path": str(image_path),
        "profile_id": str(profile.get("profile_id") or args.profile_id),
        "model_name": str(profile.get("model_name") or ""),
        "model_start": start_status,
        "prompt_path": str(prompt_path),
        "raw_model_output_path": str(raw_output_path),
        "raw_response": raw_response,
        "parsed_output": parsed,
        "parse_error": parse_error,
        "model_region_count": len(parsed.get("regions") if isinstance(parsed.get("regions"), list) else []),
        "overlay_path": str(overlay_path) if overlay_path else "",
        "stage2_numbering_skipped": True,
        "pathgraph_generation_skipped": True,
        "interpretation": "Actual model call for Stage1 region localization only; no click/fill/submit/Execute authorization.",
    }
    stop_status = None
    if args.stop_after and started_by_probe:
        stop_status = stop_model_server(profile)
        report["model_stop"] = stop_status
    report_path = out_dir / f"stage1_region_model_probe_report_{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "report_path": str(report_path),
        "overlay_path": str(overlay_path) if overlay_path else "",
        "raw_model_output_path": str(raw_output_path),
        "actual_model_call": True,
        "model_region_count": report["model_region_count"],
        "parse_error": parse_error,
        "started_model": started_by_probe,
        "stopped_model": bool(stop_status and stop_status.get("stopped")),
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            print(f"{key}={value}")
    return 0


def _image_path_from_stage1_report(report: dict[str, Any]) -> Path:
    image_path = str(report.get("image_path") or "").strip()
    if not image_path:
        stage1 = report.get("stage1_structure") if isinstance(report.get("stage1_structure"), dict) else {}
        image_path = str(stage1.get("image_path") or "").strip()
    if not image_path:
        source = report.get("source_trace_path")
        if source:
            trace = json.loads(Path(str(source)).read_text(encoding="utf-8-sig"))
            result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
            image_path = str(result.get("image_path") or "").strip()
    if not image_path:
        raise ValueError("Stage1 report does not contain an image path")
    path = Path(image_path)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(str(path))
    return path


def _build_prompt_input(report: dict[str, Any]) -> dict[str, Any]:
    stage1 = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    diagnostics = report.get("calibration_diagnostics") if isinstance(report.get("calibration_diagnostics"), dict) else {}
    regions = stage1.get("regions") if isinstance(stage1.get("regions"), list) else []
    return {
        "contract_version": "learn_stage1_region_model_prompt_input_v1",
        "coarse_region_hints": [
            {
                "region_id": str(region.get("region_id") or ""),
                "label": str(region.get("label") or ""),
                "rough_bbox": region.get("rough_bbox") if isinstance(region.get("rough_bbox"), dict) else {},
                "calibration_status": (
                    region.get("coordinate_validation", {}).get("status")
                    if isinstance(region.get("coordinate_validation"), dict)
                    else ""
                ),
            }
            for region in regions
            if isinstance(region, dict)
        ],
        "calibration_diagnostics": diagnostics,
        "instruction": (
            "If a hint is visibly offset, replace it. "
            "Do not copy rough_bbox values when the screenshot evidence suggests a better boundary. "
            "If bottom visible content is continuous with the main scroll area, classify it as main_content, not bottom_bar."
        ),
    }


def _render_model_overlay(*, image_path: Path, parsed: dict[str, Any], out_dir: Path, timestamp: str) -> Path | None:
    regions = parsed.get("regions") if isinstance(parsed.get("regions"), list) else []
    if not regions:
        return None
    with Image.open(image_path) as image:
        canvas = image.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, region in enumerate(regions, start=1):
        bbox = _bbox(region.get("precise_bbox") or region.get("bbox") or region.get("rough_bbox"))
        if not bbox:
            continue
        label = str(region.get("label") or region.get("region_id") or f"region_{index}")
        _draw_box(draw, bbox, f"M{index}: {label}", color=(170, 40, 210), font=font, width=4)
    overlay_path = out_dir / f"{image_path.stem}__stage1-region-model-probe__{timestamp}.png"
    canvas.save(overlay_path)
    return overlay_path


def _draw_box(draw: ImageDraw.ImageDraw, bbox: dict[str, int], label: str, *, color: tuple[int, int, int], font: Any, width: int) -> None:
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
    text = str(label or "")[:48]
    text_bbox = draw.textbbox((x1, y1), text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    label_y = max(0, y1 - text_h - 4)
    draw.rectangle((x1, label_y, x1 + text_w + 6, label_y + text_h + 4), fill=color)
    draw.text((x1 + 3, label_y + 2), text, fill=(255, 255, 255), font=font)


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _int(value.get("x"))
    y = _int(value.get("y"))
    w = _int(value.get("w", value.get("width")))
    h = _int(value.get("h", value.get("height")))
    if w <= 0 or h <= 0:
        return None
    return {"x": max(0, x), "y": max(0, y), "w": w, "h": h}


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
