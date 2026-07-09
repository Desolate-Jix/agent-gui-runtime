from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def render_page_detail_candidate_preview(
    *,
    source_path: str | Path,
    out_path: str | Path | None = None,
    project_root: str | Path | None = None,
    max_width: int = 1400,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source = _resolve_path(source_path, root)
    candidate = _read_json(source)
    layout = _dict(candidate.get("layout"))
    bounds = _normalize_bbox(_dict(layout.get("bounds"))) or {"x": 0, "y": 0, "w": 1, "h": 1}
    sections = [_normalize_record(item) for item in _list_of_dicts(layout.get("sections"))]
    display_groups = [_normalize_record(item) for item in _list_of_dicts(layout.get("display_groups"))]
    regions = [_normalize_record(item) for item in _list_of_dicts(layout.get("regions"))]
    sections = [item for item in sections if item.get("bbox")]
    display_groups = [item for item in display_groups if item.get("bbox")]
    regions = [item for item in regions if item.get("bbox")]
    spatial_regions = [item for item in regions if item.get("render_in_spatial_preview") is not False]

    scale = min(1.0, max_width / max(1, int(bounds["w"])))
    width = max(420, int(int(bounds["w"]) * scale))
    height = max(260, int(int(bounds["h"]) * scale))
    image = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    _draw_grid(draw, width, height)

    for index, section in enumerate(_sort_by_area(sections), start=1):
        _draw_box(
            draw,
            section,
            bounds=bounds,
            scale=scale,
            outline=(30, 41, 59, 170),
            fill=(148, 163, 184, 42),
            label=f"S{index} {section.get('label') or section.get('section_id') or 'section'}",
            font=font,
            label_fill=(15, 23, 42, 235),
            line_width=3,
        )

    for index, group in enumerate(_sort_by_area(display_groups), start=1):
        style = _display_group_draw_style(group)
        _draw_box(
            draw,
            group,
            bounds=bounds,
            scale=scale,
            outline=style["outline"],
            fill=style["fill"],
            label=f"G{index} {group.get('label') or group.get('group_id') or 'group'}",
            font=font,
            label_fill=style["label_fill"],
            line_width=style["line_width"],
        )
    footer_connector_count = _draw_footer_connectors(
        draw,
        display_groups,
        bounds=bounds,
        scale=scale,
        font=font,
    )

    for index, region in enumerate(_sort_by_area(spatial_regions), start=1):
        style = _region_draw_style(region)
        _draw_box(
            draw,
            region,
            bounds=bounds,
            scale=scale,
            outline=style["outline"],
            fill=style["fill"],
            label=f"#{region.get('region_no') or index} {region.get('label') or region.get('region_id') or 'region'}",
            font=font,
            label_fill=style["label_fill"],
            line_width=style["line_width"],
        )

    low_emphasis_region_count = sum(1 for item in regions if _region_visual_emphasis(item) == "low_review")
    review_candidate_region_count = sum(1 for item in regions if _region_visual_emphasis(item) == "review_candidate")
    spatial_preview_suppressed_region_count = len(regions) - len(spatial_regions)
    output = _resolve_path(out_path, root) if out_path else source.with_name("learn_page_detail_candidate_preview.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    result = {
        "contract_version": "learn_page_detail_candidate_preview_v1",
        "source_path": _relative_path(source, root),
        "output_path": _relative_path(output, root),
        "section_count": len(sections),
        "display_group_count": len(display_groups),
        "list_group_count": sum(1 for item in display_groups if str(item.get("role") or "") == "list_group"),
        "footer_connector_count": footer_connector_count,
        "region_count": len(regions),
        "spatial_region_count": len(spatial_regions),
        "spatial_preview_suppressed_region_count": spatial_preview_suppressed_region_count,
        "primary_region_count": len(regions) - low_emphasis_region_count - review_candidate_region_count,
        "review_candidate_region_count": review_candidate_region_count,
        "low_emphasis_region_count": low_emphasis_region_count,
        "layout_mode": candidate.get("layout_mode"),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    return result


def _draw_footer_connectors(
    draw: ImageDraw.ImageDraw,
    display_groups: list[dict[str, Any]],
    *,
    bounds: dict[str, int],
    scale: float,
    font: ImageFont.ImageFont,
) -> int:
    count = 0
    for group in display_groups:
        connectors = _list_of_dicts(group.get("footer_connectors"))
        for connector in connectors:
            from_point = _normalize_point(_dict(connector.get("from_point")))
            to_point = _normalize_point(_dict(connector.get("to_point")))
            if not from_point or not to_point:
                continue
            x1 = int((from_point["x"] - bounds["x"]) * scale)
            y1 = int((from_point["y"] - bounds["y"]) * scale)
            x2 = int((to_point["x"] - bounds["x"]) * scale)
            y2 = int((to_point["y"] - bounds["y"]) * scale)
            draw.line([(x1, y1), (x2, y2)], fill=(14, 165, 233, 145), width=2)
            radius = 3
            draw.ellipse([x2 - radius, y2 - radius, x2 + radius, y2 + radius], fill=(14, 165, 233, 190))
            label = f"footer -> G"
            label_x = min(max(x1, x2) + 4, max(x1, x2) + 120)
            label_y = max(0, min(y1, y2) - 12)
            label_box = draw.textbbox((label_x, label_y), label, font=font)
            draw.rectangle(
                [label_box[0] - 3, label_box[1] - 2, label_box[2] + 3, label_box[3] + 2],
                fill=(240, 249, 255, 210),
            )
            draw.text((label_x, label_y), label, fill=(12, 74, 110, 230), font=font)
            count += 1
    return count


def _draw_grid(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=(226, 232, 240, 120), width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=(226, 232, 240, 120), width=1)


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
    label_fill: tuple[int, int, int, int],
    line_width: int,
) -> None:
    box = _normalize_bbox(_dict(item.get("bbox")))
    if not box:
        return
    x1 = int((box["x"] - bounds["x"]) * scale)
    y1 = int((box["y"] - bounds["y"]) * scale)
    x2 = int((box["x"] + box["w"] - bounds["x"]) * scale)
    y2 = int((box["y"] + box["h"] - bounds["y"]) * scale)
    if x2 <= x1 or y2 <= y1:
        return
    draw.rectangle([x1, y1, x2, y2], outline=outline, fill=fill, width=line_width)
    safe_label = str(label)[:58]
    label_box = draw.textbbox((x1 + 4, y1 + 4), safe_label, font=font)
    pad = 3
    draw.rectangle(
        [label_box[0] - pad, label_box[1] - pad, label_box[2] + pad, label_box[3] + pad],
        fill=(255, 255, 255, 214),
    )
    draw.text((x1 + 4, y1 + 4), safe_label, fill=label_fill, font=font)


def _region_draw_style(region: dict[str, Any]) -> dict[str, Any]:
    emphasis = _region_visual_emphasis(region)
    if emphasis == "low_review":
        return {
            "outline": (100, 116, 139, 125),
            "fill": (241, 245, 249, 26),
            "label_fill": (71, 85, 105, 215),
            "line_width": 1,
        }
    if emphasis == "review_candidate":
        return {
            "outline": (234, 179, 8, 178),
            "fill": (254, 252, 232, 40),
            "label_fill": (113, 63, 18, 230),
            "line_width": 2,
        }
    return {
        "outline": (249, 115, 22, 210),
        "fill": (255, 247, 237, 46),
        "label_fill": (124, 45, 18, 240),
        "line_width": 2,
    }


def _display_group_draw_style(group: dict[str, Any]) -> dict[str, Any]:
    role = str(group.get("role") or "")
    if role == "list_group":
        return {
            "outline": (14, 165, 233, 150),
            "fill": (224, 242, 254, 35),
            "label_fill": (12, 74, 110, 230),
            "line_width": 2,
        }
    return {
        "outline": (99, 102, 241, 135),
        "fill": (238, 242, 255, 32),
        "label_fill": (49, 46, 129, 220),
        "line_width": 2,
    }


def _region_visual_emphasis(region: dict[str, Any]) -> str:
    value = str(region.get("visual_emphasis") or "").strip()
    if value in {"low_review", "review_candidate", "primary_content"}:
        return value
    label = str(region.get("label") or "").casefold()
    role = str(region.get("role") or "").casefold()
    if "background" in label or "empty review" in label or "background" in role or "boundary_review" in role:
        return "low_review"
    return "primary_content"


def _sort_by_area(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: int(_dict(item.get("bbox")).get("w") or 1) * int(_dict(item.get("bbox")).get("h") or 1),
        reverse=True,
    )


def _normalize_record(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    bbox = _normalize_bbox(_dict(normalized.get("bbox")))
    if bbox:
        normalized["bbox"] = bbox
    return normalized


def _normalize_bbox(bbox: dict[str, Any]) -> dict[str, int]:
    if not bbox:
        return {}
    try:
        width = bbox.get("w", bbox.get("width"))
        height = bbox.get("h", bbox.get("height"))
        return {
            "x": int(bbox.get("x") or 0),
            "y": int(bbox.get("y") or 0),
            "w": max(1, int(width if width is not None else 1)),
            "h": max(1, int(height if height is not None else 1)),
        }
    except (TypeError, ValueError):
        return {}


def _normalize_point(point: dict[str, Any]) -> dict[str, int]:
    if not point:
        return {}
    try:
        return {"x": int(point.get("x") or 0), "y": int(point.get("y") or 0)}
    except (TypeError, ValueError):
        return {}


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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a display-only page-detail candidate preview PNG.")
    parser.add_argument("--source", required=True, help="learn_page_detail_candidate.json")
    parser.add_argument("--out", help="Output PNG path. Defaults beside the source candidate.")
    parser.add_argument("--max-width", type=int, default=1400)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = render_page_detail_candidate_preview(
        source_path=args.source,
        out_path=args.out,
        max_width=args.max_width,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
