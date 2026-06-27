from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.seek.learn_artifacts import build_seek_learn_artifacts
from app.learn.path_graph_artifacts import build_seek_runtime_path_graph_export
from app.learn.interface_map import build_learned_interface_map
from app.learn.visual_asset_crops import build_visual_asset_crop_export


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def resolve_trace_path(report_path: Path, report: dict[str, Any]) -> Path | None:
    raw = report.get("traversal_trace_path")
    if not raw:
        return None
    trace_path = Path(str(raw))
    if trace_path.is_absolute():
        return trace_path
    if trace_path.exists():
        return trace_path
    return report_path.parent / trace_path


def build_export(
    *,
    report_path: str | Path,
    trace_path: str | Path | None = None,
) -> dict[str, Any]:
    report_file = Path(report_path)
    report = read_json(report_file)
    resolved_trace_path = Path(trace_path) if trace_path else resolve_trace_path(report_file, report)
    trace = read_json(resolved_trace_path) if resolved_trace_path and resolved_trace_path.exists() else None
    return build_seek_learn_artifacts(
        report,
        trace=trace,
        report_path=report_file,
        trace_path=resolved_trace_path,
    )


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export SEEK Learn Mode artifacts from a stable MVP run.")
    parser.add_argument("--report", type=Path, required=True, help="seek_mvp_run_report_v1 JSON path.")
    parser.add_argument("--trace", type=Path, default=None, help="Optional seek_mvp_traversal_trace_v1 JSON path.")
    parser.add_argument("--out", type=Path, required=True, help="Output bundle path.")
    parser.add_argument("--profile-out", type=Path, default=None, help="Optional learned_app_profile_v1 output path.")
    parser.add_argument("--path-graph-out", type=Path, default=None, help="Optional path_graph_seed_v1 output path.")
    parser.add_argument("--runtime-graph-out", type=Path, default=None, help="Optional runtime_path_graph_v1 output path.")
    parser.add_argument("--learned-skills-out", type=Path, default=None, help="Optional learned_skill_v1 output path.")
    parser.add_argument("--visual-assets-out", type=Path, default=None, help="Optional visual_asset_v1 output path.")
    parser.add_argument("--interface-map-out", type=Path, default=None, help="Optional learned_interface_map_v1 output path.")
    parser.add_argument("--visual-source-image", type=Path, default=None, help="Optional screenshot used to crop visual assets.")
    parser.add_argument("--visual-crops-dir", type=Path, default=None, help="Optional visual asset crop output directory.")
    parser.add_argument("--visual-crop-export-out", type=Path, default=None, help="Optional visual_asset_crop_export_v1 output path.")
    args = parser.parse_args(argv)

    artifact = build_export(report_path=args.report, trace_path=args.trace)
    runtime_export = build_seek_runtime_path_graph_export(artifact)
    visual_crop_export = None
    if args.visual_source_image and args.visual_crops_dir:
        visual_crop_export = build_visual_asset_crop_export(
            runtime_export["runtime_path_graph"],
            runtime_export["visual_assets"],
            source_image_path=args.visual_source_image,
            output_dir=args.visual_crops_dir,
        )
        runtime_export["visual_assets"] = visual_crop_export["visual_assets"]
    interface_map = build_learned_interface_map(runtime_export["runtime_path_graph"], runtime_export["visual_assets"])
    write_json(args.out, artifact)
    if args.profile_out:
        write_json(args.profile_out, artifact["learned_app_profile"])
    if args.path_graph_out:
        write_json(args.path_graph_out, artifact["path_graph_seed"])
    if args.runtime_graph_out:
        write_json(args.runtime_graph_out, runtime_export["runtime_path_graph"])
    if args.learned_skills_out:
        write_json(args.learned_skills_out, runtime_export["learned_skills"])
    if args.visual_assets_out:
        write_json(args.visual_assets_out, runtime_export["visual_assets"])
    if args.interface_map_out:
        write_json(args.interface_map_out, interface_map)
    if args.visual_crop_export_out:
        if visual_crop_export is None:
            raise ValueError("--visual-crop-export-out requires --visual-source-image and --visual-crops-dir")
        write_json(args.visual_crop_export_out, visual_crop_export)
    summary = {
        "success": True,
        "contract_version": artifact.get("contract_version"),
        "out": str(args.out),
        "profile_out": str(args.profile_out) if args.profile_out else None,
        "path_graph_out": str(args.path_graph_out) if args.path_graph_out else None,
        "runtime_graph_out": str(args.runtime_graph_out) if args.runtime_graph_out else None,
        "learned_skills_out": str(args.learned_skills_out) if args.learned_skills_out else None,
        "visual_assets_out": str(args.visual_assets_out) if args.visual_assets_out else None,
        "interface_map_out": str(args.interface_map_out) if args.interface_map_out else None,
        "visual_crop_export_out": str(args.visual_crop_export_out) if args.visual_crop_export_out else None,
        "page_type": artifact["learned_app_profile"].get("page_type"),
        "baseline": artifact.get("baseline"),
        "runtime_path_graph_contract": runtime_export["runtime_path_graph"].get("contract_version"),
        "interface_map_contract": interface_map.get("contract_version"),
        "visual_asset_crop_contract": visual_crop_export.get("contract_version") if visual_crop_export else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
