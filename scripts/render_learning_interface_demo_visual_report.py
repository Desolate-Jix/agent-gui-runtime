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

from scripts.render_learn_page_detail_candidate_preview import render_page_detail_candidate_preview


def render_learning_interface_demo_visual_report(
    *,
    chain_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else ROOT
    chain_report = _read_json(_resolve_path(chain_report_path, root))
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    cases = [item for item in chain_report.get("cases", []) if isinstance(item, dict)]
    case_reports = [_render_case(case, out, root) for case in cases]
    contact_sheet_path = _create_contact_sheet(case_reports, out / "learning_interface_demo_visual_contact_sheet.png", root=root)
    summary = {
        "case_count": len(case_reports),
        "display_review_ready_count": sum(
            1 for item in case_reports if item.get("quality_status") == "display_review_ready"
        ),
        "stress_sample_display_review_count": sum(
            1 for item in case_reports if item.get("quality_status") == "stress_sample_display_review"
        ),
        "runtime_pathgraph_ready_count": 0,
        "interpretation": (
            "Display/review visual evidence only; not recognition accuracy, Execute authorization, "
            "or Runtime PathGraph readiness."
        ),
    }
    report = {
        "contract_version": "learning_interface_demo_visual_report_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_chain_report_path": _relative_path(_resolve_path(chain_report_path, root), root),
        "summary": summary,
        "case_count": summary["case_count"],
        "display_review_ready_count": summary["display_review_ready_count"],
        "stress_sample_display_review_count": summary["stress_sample_display_review_count"],
        "runtime_pathgraph_ready_count": summary["runtime_pathgraph_ready_count"],
        "contact_sheet_path": _relative_path(contact_sheet_path, root),
        "cases": case_reports,
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "interpretation": (
            "Display-only visual audit for Learning Interface demo readiness. "
            "It is not recognition accuracy, Execute authorization, or Runtime PathGraph promotion evidence."
        ),
    }
    report_path = out / "learning_interface_demo_visual_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = _relative_path(report_path, root)
    return report


def _render_case(case: dict[str, Any], out_dir: Path, root: Path) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "case").strip() or "case"
    case_dir = out_dir / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    page_detail_path = _resolve_path(((case.get("page_detail") or {}).get("report_path") or ""), root)
    scaffold_path = _resolve_path(((case.get("scaffold") or {}).get("report_path") or ""), root)
    page_preview_path = case_dir / "page_detail_preview.png"
    page_layout_summary = render_page_detail_candidate_preview(
        source_path=page_detail_path,
        out_path=case_dir / "page_detail_layout_preview.png",
        project_root=root,
        max_width=1400,
    )
    page_visual_summary = _render_page_detail_on_screenshot(
        source_path=page_detail_path,
        out_path=page_preview_path,
        root=root,
    )
    page_preview = {
        **page_layout_summary,
        "output_path": _relative_path(page_preview_path, root),
        "layout_preview_path": page_layout_summary.get("output_path"),
        "screenshot_backed": page_visual_summary.get("screenshot_backed"),
        "screenshot_source_path": page_visual_summary.get("screenshot_source_path"),
    }
    pathgraph_preview_path = case_dir / "readonly_pathgraph_preview.png"
    pathgraph_preview = _render_readonly_pathgraph_preview(
        scaffold_path=scaffold_path,
        out_path=pathgraph_preview_path,
        root=root,
    )
    pathgraph_diagram_path = case_dir / "readonly_pathgraph_diagram.png"
    pathgraph_diagram = _render_readonly_pathgraph_diagram(
        scaffold_path=scaffold_path,
        out_path=pathgraph_diagram_path,
        root=root,
    )
    quality = _visual_quality(case, page_preview, pathgraph_preview)
    return {
        "case_id": case_id,
        "quality_status": quality["status"],
        "issues": quality["issues"],
        "visual_artifacts_present": quality["status"] in {"display_review_ready", "stress_sample_display_review"},
        "display_review_ready": quality["status"] == "display_review_ready",
        "page_detail_report_path": _relative_path(page_detail_path, root),
        "scaffold_report_path": _relative_path(scaffold_path, root),
        "page_detail_preview_path": _relative_path(page_preview_path, root),
        "readonly_pathgraph_preview_path": _relative_path(pathgraph_preview_path, root),
        "readonly_pathgraph_diagram_path": _relative_path(pathgraph_diagram_path, root),
        "page_detail_summary": page_preview,
        "readonly_pathgraph_summary": pathgraph_preview,
        "readonly_pathgraph_diagram_summary": pathgraph_diagram,
        "runtime_pathgraph_ready": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _visual_quality(case: dict[str, Any], page_preview: dict[str, Any], pathgraph_preview: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if int(page_preview.get("spatial_region_count") or 0) <= 0:
        issues.append("missing_page_detail_spatial_regions")
    if int(pathgraph_preview.get("state_count") or 0) <= 0:
        issues.append("missing_pathgraph_states")
    if int(pathgraph_preview.get("region_count") or 0) <= 0:
        issues.append("missing_pathgraph_regions")
    if int(pathgraph_preview.get("action_template_count") or 0) <= 0:
        issues.append("missing_pathgraph_actions")
    case_id = str(case.get("case_id") or "").casefold()
    if case_id in {"python_org", "python"}:
        issues.append("python_org_stress_sample")
        return {"status": "stress_sample_display_review", "issues": issues}
    return {"status": "needs_review" if issues else "display_review_ready", "issues": issues}


def _render_readonly_pathgraph_preview(*, scaffold_path: Path, out_path: Path, root: Path) -> dict[str, Any]:
    scaffold = _read_json(scaffold_path)
    preview = scaffold.get("page_detail_readonly_pathgraph_preview")
    if not isinstance(preview, dict):
        raise ValueError(f"missing page_detail_readonly_pathgraph_preview: {scaffold_path}")
    page_detail = preview.get("page_detail_preview") if isinstance(preview.get("page_detail_preview"), dict) else {}
    path_graph = preview.get("readonly_path_graph_preview")
    if not isinstance(path_graph, dict):
        raise ValueError(f"missing readonly_path_graph_preview: {scaffold_path}")
    layout = page_detail.get("layout") if isinstance(page_detail.get("layout"), dict) else {}
    bounds = _bbox(layout.get("bounds")) or {"x": 0, "y": 0, "w": 1, "h": 1}
    regions = [_normalize_region(item) for item in _list_of_dicts(layout.get("regions"))]
    regions = [item for item in regions if item.get("bbox")]
    states = [_normalize_region(item) for item in _list_of_dicts(path_graph.get("states"))]
    states = [item for item in states if item.get("bbox")]
    actions = _list_of_dicts(path_graph.get("action_templates"))
    image, draw_bounds, scale, screenshot_path = _base_preview_image(page_detail, bounds, root=root)
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    _draw_grid(draw, image.width, image.height)
    for index, state in enumerate(_sort_by_area(states), start=1):
        _draw_box(
            draw,
            state,
            bounds=draw_bounds,
            scale=scale,
            outline=(37, 99, 235, 190),
            fill=(219, 234, 254, 45),
            label=f"S{index} {state.get('label') or state.get('state_id') or 'state'}",
            font=font,
            line_width=3,
        )
    for index, region in enumerate(_sort_by_area(regions), start=1):
        _draw_box(
            draw,
            region,
            bounds=draw_bounds,
            scale=scale,
            outline=(245, 158, 11, 200),
            fill=(255, 251, 235, 38),
            label=f"#{region.get('region_no') or index} {region.get('label') or region.get('region_id') or 'region'}",
            font=font,
            line_width=2,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return {
        "contract_version": "readonly_pathgraph_preview_visual_summary_v1",
        "source_path": _relative_path(scaffold_path, root),
        "output_path": _relative_path(out_path, root),
        "state_count": len(states),
        "region_count": len(regions),
        "action_template_count": len(actions),
        "screenshot_backed": bool(screenshot_path),
        "screenshot_source_path": _relative_path(screenshot_path, root) if screenshot_path else "",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
    }


def _render_readonly_pathgraph_diagram(*, scaffold_path: Path, out_path: Path, root: Path) -> dict[str, Any]:
    scaffold = _read_json(scaffold_path)
    preview = scaffold.get("page_detail_readonly_pathgraph_preview")
    if not isinstance(preview, dict):
        raise ValueError(f"missing page_detail_readonly_pathgraph_preview: {scaffold_path}")
    path_graph = preview.get("readonly_path_graph_preview")
    if not isinstance(path_graph, dict):
        raise ValueError(f"missing readonly_path_graph_preview: {scaffold_path}")
    states = _list_of_dicts(path_graph.get("states"))
    actions = _list_of_dicts(path_graph.get("action_templates"))
    actions_by_region: dict[str, int] = {}
    for action in actions:
        target = str(action.get("target_region_id") or action.get("target_entity") or "").strip()
        if target:
            actions_by_region[target] = actions_by_region.get(target, 0) + 1
    width = 1200
    state_height = 150
    height = max(360, 110 + max(1, len(states)) * state_height + 110)
    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    title = "Read-only PathGraph structure preview"
    subtitle = "display_only=true · execute_binding_enabled=false · runtime_pathgraph_promotion=false"
    draw.text((28, 24), title, fill=(15, 23, 42), font=font)
    draw.text((28, 46), subtitle, fill=(71, 85, 105), font=font)
    if not states:
        draw.text((28, 100), "No states available", fill=(127, 29, 29), font=font)
    y = 86
    for index, state in enumerate(states, start=1):
        state_id = str(state.get("state_id") or f"state_{index}")
        label = str(state.get("label") or state_id)
        region_refs = [str(item) for item in state.get("region_refs", [])] if isinstance(state.get("region_refs"), list) else []
        action_count = sum(actions_by_region.get(region_id, 0) for region_id in region_refs)
        x = 40
        box_w = width - 80
        box_h = state_height - 24
        draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=10, outline=(37, 99, 235, 180), fill=(239, 246, 255, 230), width=3)
        draw.text((x + 18, y + 14), f"S{index}: {label}", fill=(30, 64, 175), font=font)
        draw.text((x + 18, y + 36), f"state_id={state_id}", fill=(51, 65, 85), font=font)
        draw.text((x + 18, y + 58), f"regions={len(region_refs)} · read_only_actions={action_count}", fill=(51, 65, 85), font=font)
        preview_refs = ", ".join(region_refs[:8])
        if len(region_refs) > 8:
            preview_refs += f", +{len(region_refs) - 8} more"
        draw.text((x + 18, y + 82), f"region refs: {preview_refs or 'none'}", fill=(71, 85, 105), font=font)
        chip_y = y + 104
        for chip_index, text in enumerate(["no dispatch", "requires review", "final submit forbidden"]):
            chip_x = x + 18 + chip_index * 190
            draw.rounded_rectangle([chip_x, chip_y, chip_x + 168, chip_y + 24], radius=8, outline=(148, 163, 184, 180), fill=(255, 255, 255, 230), width=1)
            draw.text((chip_x + 9, chip_y + 7), text, fill=(71, 85, 105), font=font)
        if index < len(states):
            mid_x = width // 2
            draw.line([(mid_x, y + box_h + 8), (mid_x, y + state_height - 2)], fill=(37, 99, 235, 170), width=3)
            draw.polygon([(mid_x - 6, y + state_height - 8), (mid_x + 6, y + state_height - 8), (mid_x, y + state_height)], fill=(37, 99, 235, 190))
        y += state_height
    footer_y = height - 56
    draw.text((28, footer_y), f"states={len(states)} · actions={len(actions)} · generated from page_detail_readonly_pathgraph_preview", fill=(51, 65, 85), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return {
        "contract_version": "readonly_pathgraph_diagram_visual_summary_v1",
        "source_path": _relative_path(scaffold_path, root),
        "output_path": _relative_path(out_path, root),
        "state_count": len(states),
        "action_template_count": len(actions),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
    }


def _render_page_detail_on_screenshot(*, source_path: Path, out_path: Path, root: Path) -> dict[str, Any]:
    candidate = _read_json(source_path)
    layout = candidate.get("layout") if isinstance(candidate.get("layout"), dict) else {}
    bounds = _bbox(layout.get("bounds")) or {"x": 0, "y": 0, "w": 1, "h": 1}
    sections = [_normalize_region(item) for item in _list_of_dicts(layout.get("sections"))]
    sections = [item for item in sections if item.get("bbox")]
    regions = [_normalize_region(item) for item in _list_of_dicts(layout.get("regions"))]
    regions = [item for item in regions if item.get("bbox") and item.get("render_in_spatial_preview") is not False]
    image, draw_bounds, scale, screenshot_path = _base_preview_image(candidate, bounds, root=root)
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    _draw_grid(draw, image.width, image.height)
    for index, section in enumerate(_sort_by_area(sections), start=1):
        _draw_box(
            draw,
            section,
            bounds=draw_bounds,
            scale=scale,
            outline=(30, 41, 59, 170),
            fill=(148, 163, 184, 30),
            label=f"S{index} {section.get('label') or section.get('section_id') or 'section'}",
            font=font,
            line_width=3,
        )
    for index, region in enumerate(_sort_by_area(regions), start=1):
        _draw_box(
            draw,
            region,
            bounds=draw_bounds,
            scale=scale,
            outline=(249, 115, 22, 215),
            fill=(255, 247, 237, 35),
            label=f"#{region.get('region_no') or index} {region.get('label') or region.get('region_id') or 'region'}",
            font=font,
            line_width=2,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return {
        "contract_version": "page_detail_screenshot_visual_summary_v1",
        "source_path": _relative_path(source_path, root),
        "output_path": _relative_path(out_path, root),
        "section_count": len(sections),
        "region_count": len(regions),
        "screenshot_backed": bool(screenshot_path),
        "screenshot_source_path": _relative_path(screenshot_path, root) if screenshot_path else "",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _base_preview_image(page_detail: dict[str, Any], bounds: dict[str, int], *, root: Path) -> tuple[Image.Image, dict[str, int], float, Path | None]:
    screenshot_path = _first_existing_path(
        [
            page_detail.get("screenshot_path"),
            page_detail.get("source_image_path"),
        ],
        root=root,
    )
    if screenshot_path:
        with Image.open(screenshot_path) as source:
            image = source.convert("RGB")
        scale = min(1.0, 1400 / max(1, image.width))
        if scale < 1.0:
            image = image.resize((int(image.width * scale), int(image.height * scale)))
        return image, {"x": 0, "y": 0, "w": int(round(image.width / scale)), "h": int(round(image.height / scale))}, scale, screenshot_path
    scale = min(1.0, 1400 / max(1, int(bounds["w"])))
    width = max(420, int(int(bounds["w"]) * scale))
    height = max(260, int(int(bounds["h"]) * scale))
    return Image.new("RGB", (width, height), (248, 250, 252)), bounds, scale, None


def _first_existing_path(values: list[Any], *, root: Path) -> Path | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.exists():
            return candidate.resolve()
    return None


def _create_contact_sheet(case_reports: list[dict[str, Any]], out_path: Path, *, root: Path) -> Path:
    tiles: list[tuple[str, Image.Image]] = []
    for report in case_reports:
        for label, key in [
            ("page detail", "page_detail_preview_path"),
            ("readonly pathgraph", "readonly_pathgraph_preview_path"),
            ("pathgraph structure", "readonly_pathgraph_diagram_path"),
        ]:
            image_path = _resolve_path(report.get(key) or "", root)
            with Image.open(image_path) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((640, 400))
                canvas = Image.new("RGB", (660, 445), "white")
                canvas.paste(thumb, ((660 - thumb.width) // 2, 36))
                draw = ImageDraw.Draw(canvas)
                draw.text((10, 10), f"{report.get('case_id')} · {label}", fill=(0, 0, 0), font=ImageFont.load_default())
                tiles.append((str(report.get("case_id")), canvas))
    if not tiles:
        raise ValueError("no visual tiles generated")
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 660, rows * 445), (245, 247, 250))
    for index, (_label, tile) in enumerate(tiles):
        sheet.paste(tile, ((index % cols) * 660, (index // cols) * 445))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def _draw_box(
    draw: ImageDraw.ImageDraw,
    item: dict[str, Any],
    *,
    bounds: dict[str, int],
    scale: float,
    outline: tuple[int, int, int, int],
    fill: tuple[int, int, int, int],
    label: str,
    font: ImageFont.ImageFont,
    line_width: int,
) -> None:
    box = _bbox(item.get("bbox"))
    if not box:
        return
    x1 = int((box["x"] - bounds["x"]) * scale)
    y1 = int((box["y"] - bounds["y"]) * scale)
    x2 = int((box["x"] + box["w"] - bounds["x"]) * scale)
    y2 = int((box["y"] + box["h"] - bounds["y"]) * scale)
    if x2 <= x1 or y2 <= y1:
        return
    draw.rectangle([x1, y1, x2, y2], outline=outline, fill=fill, width=line_width)
    safe_label = str(label)[:54]
    label_box = draw.textbbox((x1 + 4, y1 + 4), safe_label, font=font)
    draw.rectangle([label_box[0] - 3, label_box[1] - 3, label_box[2] + 3, label_box[3] + 3], fill=(255, 255, 255, 220))
    draw.text((x1 + 4, y1 + 4), safe_label, fill=(15, 23, 42, 235), font=font)


def _draw_grid(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(226, 232, 240, 120), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(226, 232, 240, 120), width=1)


def _sort_by_area(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: int((item.get("bbox") or {}).get("w") or 1) * int((item.get("bbox") or {}).get("h") or 1), reverse=True)


def _normalize_region(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    box = _bbox(out.get("bbox"))
    if box:
        out["bbox"] = box
    return out


def _bbox(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    try:
        width = value.get("w", value.get("width"))
        height = value.get("h", value.get("height"))
        return {
            "x": int(value.get("x") or 0),
            "y": int(value.get("y") or 0),
            "w": max(1, int(width if width is not None else 1)),
            "h": max(1, int(height if height is not None else 1)),
        }
    except (TypeError, ValueError):
        return {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Learning Interface demo visual audit sheets.")
    parser.add_argument("--chain-report", required=True, help="learning_interface_chain_smoke_report.json")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = render_learning_interface_demo_visual_report(chain_report_path=args.chain_report, out_dir=args.out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report['report_path']}")
        print(f"contact_sheet_path={report['contact_sheet_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
