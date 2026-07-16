from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.experiments.coarse_region_proposal_mvp import build_coarse_region_proposals
from app.learn.experiments.hierarchical_region_partition import (
    RegionFrame,
    SCHEMA_VERSION,
    build_anonymous_candidates,
    compile_hierarchical_regions,
)
from app.vision.local_provider import LocalVisionProvider
from scripts.eval_hierarchical_region_partition_mvp import (
    _build_prompt_payload,
    _read_json,
    _render_candidate_overlay,
    _render_region_overlay,
    _resolve_path,
    _trial_image_path,
)


PROMPT = """Organize supplied anonymous geometry evidence from one screenshot into a two-level region tree. Return JSON only.

Controlled adjudication rules:
- Use only IDs present in candidate_rows. Never invent an ID or bbox.
- Select supplied candidates, merge adjacent supplied candidates, and organize them into Level 1 and Level 2 regions.
- A child must be geometrically contained by its parent. Its candidate IDs must also appear in the parent's source_candidate_ids.
- Do not promote individual buttons, icons, text fragments, or element IDs into major regions.
- Do not infer regions from an application name. Judge only screenshot geometry and supplied evidence.
- If visible geometry is missing from the supplied evidence, report it in candidate_gaps.
- Do not output bbox or pixel coordinates. The program computes final bbox unions.

Output contract:
- schema_version: exactly hierarchical_region_partition_mvp_v1
- page_type: short generic free-text summary
- regions: array of objects with region_id, level, parent_id, source_candidate_ids, content_summary, optional_role, confidence, children
- region_id: unique R1/R2 or R1.1 style value
- level: integer 1 or 2
- parent_id: root for Level 1, or an existing Level 1 region ID for Level 2
- source_candidate_ids: non-empty array containing only supplied IDs
- optional_role: navigation, list, content, toolbar, composer, status, media, or unknown
- confidence: number from 0 to 1
- children: array of child region IDs
- unassigned_candidate_ids: array of supplied IDs not used by any region
- candidate_gaps: array of objects with description and approximate_location
"""

ModelCaller = Callable[..., str]


def run_ab_case(
    *,
    case: dict[str, Any],
    out_dir: Path,
    model_caller: ModelCaller | None = None,
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
    screenshot_copy = case_dir / "screenshot.png"
    shutil.copyfile(image_path, screenshot_copy)

    element_candidates = build_anonymous_candidates(inventory, image_size)
    proposal_report = build_coarse_region_proposals(inventory, image_size)
    coarse_candidates = proposal_report["proposals"]
    proposal_report_path = case_dir / "coarse_proposal_generation_report.json"
    proposal_report_path.write_text(json.dumps(proposal_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    caller = model_caller or _provider_caller(
        endpoint=endpoint,
        model_name=model_name,
        timeout_seconds=timeout_seconds,
    )
    experiment_a = _run_experiment(
        experiment_id="A_element_only",
        candidates=element_candidates,
        prompt_payload=_build_prompt_payload(element_candidates, image_size),
        image_path=image_path,
        case_dir=case_dir,
        image_size=image_size,
        model_caller=caller,
    )
    experiment_b = _run_experiment(
        experiment_id="B_coarse_proposals",
        candidates=coarse_candidates,
        prompt_payload=_build_coarse_prompt_payload(coarse_candidates, image_size),
        image_path=image_path,
        case_dir=case_dir,
        image_size=image_size,
        model_caller=caller,
    )
    report = {
        "contract_version": "hierarchical_region_partition_mvp2_ab_case_report_v1",
        "case_id": case_id,
        "trial_result_path": str(trial_path),
        "screenshot_path": str(screenshot_copy),
        "coarse_proposal_report_path": str(proposal_report_path),
        "experiment_a": experiment_a,
        "experiment_b": experiment_b,
        "model_call_count": 2,
        "repair_call_count": 0,
        "same_model_configuration": True,
        "display_only": True,
        "production_integration": False,
        "execute_binding_enabled": False,
        "pathgraph_promotion": False,
        "real_clicks": 0,
        "interpretation": "A/B shadow experiment only; no aggregate accuracy or production reliability claim",
    }
    report_path = case_dir / "ab_comparison_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def run_manifest(
    manifest_path: Path,
    out_dir: Path,
    *,
    endpoint: str,
    model_name: str,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    cases = manifest.get("cases") if isinstance(manifest.get("cases"), list) else []
    reports = [
        run_ab_case(
            case=case,
            out_dir=out_dir,
            endpoint=endpoint,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )
        for case in cases
        if isinstance(case, dict)
    ]
    validator_a = sum(bool(item["experiment_a"]["validator"]["valid"]) for item in reports)
    validator_b = sum(bool(item["experiment_b"]["validator"]["valid"]) for item in reports)
    summary = {
        "contract_version": "hierarchical_region_partition_mvp2_ab_report_v1",
        "case_count": len(reports),
        "actual_model_call": True,
        "model_name": model_name,
        "temperature": 0.0,
        "max_tokens": 3072,
        "calls_per_case": 2,
        "repair_calls": 0,
        "validator_pass_counts": {"element_only": validator_a, "coarse_proposals": validator_b},
        "cases": reports,
        "display_only": True,
        "production_integration": False,
        "interpretation": "per-sample A/B evidence; not accuracy and not a production capability claim",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "hierarchical_region_partition_mvp2_ab_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def _run_experiment(
    *,
    experiment_id: str,
    candidates: list[dict[str, Any]],
    prompt_payload: dict[str, Any],
    image_path: Path,
    case_dir: Path,
    image_size: dict[str, int],
    model_caller: ModelCaller,
) -> dict[str, Any]:
    experiment_dir = case_dir / experiment_id
    experiment_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = _render_candidate_overlay(image_path, candidates, experiment_dir / "input_overlay.png")
    prompt_text = f"{PROMPT}\n\nCandidate evidence:\n{json.dumps(prompt_payload, ensure_ascii=False, separators=(',', ':'))}"
    prompt_path = experiment_dir / "model_prompt.json"
    prompt_path.write_text(
        json.dumps({"prompt": prompt_text, "prompt_input": prompt_payload}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_text = model_caller(
        image_path=overlay_path,
        prompt_text=prompt_text,
        max_tokens=3072,
        temperature=0.0,
    )
    raw_path = experiment_dir / "model_raw_response.txt"
    raw_path.write_text(raw_text + "\n", encoding="utf-8")
    parsed = _parse_json_object(raw_text)
    parsed_path = experiment_dir / "model_parsed_response.json"
    parsed_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compiled = compile_hierarchical_regions(parsed, candidates, image_size)
    validator_path = experiment_dir / "validator_report.json"
    validator_path.write_text(json.dumps(compiled["validator"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    region_overlay = _render_region_overlay(image_path, compiled.get("regions", []), experiment_dir / "region_overlay.png")
    frame = RegionFrame(image_path=image_path, compiled=compiled)
    crop_paths = []
    crop_failures = []
    for region in compiled.get("regions", []):
        region_id = str(region.get("region_id") or "")
        try:
            crop_paths.append(str(frame.crop_region(region_id, experiment_dir / "crops")))
        except (KeyError, ValueError, OSError) as exc:
            crop_failures.append({"region_id": region_id, "error": str(exc)})
    return {
        "experiment_id": experiment_id,
        "source_type": "actual_model_call",
        "candidate_count": len(candidates),
        "input_overlay_path": str(overlay_path),
        "prompt_path": str(prompt_path),
        "raw_response_path": str(raw_path),
        "parsed_response_path": str(parsed_path),
        "validator_report_path": str(validator_path),
        "region_overlay_path": str(region_overlay),
        "crop_paths": crop_paths,
        "crop_failures": crop_failures,
        "validator": compiled["validator"],
        "regions": compiled.get("regions", []),
    }


def _build_coarse_prompt_payload(candidates: list[dict[str, Any]], image_size: dict[str, int]) -> dict[str, Any]:
    edge_codes = {"left": "L", "top": "T", "right": "R", "bottom": "B"}
    source_codes = {
        "x_whitespace_partition": "XW",
        "y_whitespace_partition": "YW",
        "element_cluster": "EC",
        "remainder_region": "RR",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": "coarse_region_proposal",
        "image_size": [image_size["width"], image_size["height"]],
        "candidate_count": len(candidates),
        "candidate_columns": ["id", "x", "y", "w", "h", "level_hint", "edges", "sources", "density"],
        "candidate_rows": [
            [
                candidate["candidate_id"],
                candidate["bbox"]["x"],
                candidate["bbox"]["y"],
                candidate["bbox"]["w"],
                candidate["bbox"]["h"],
                candidate["proposal_level"],
                "".join(edge_codes[value] for value in candidate.get("touches_edges", []) if value in edge_codes),
                [source_codes.get(value, "G") for value in candidate.get("generation_sources", [])],
                candidate.get("evidence", {}).get("element_density", 0.0),
            ]
            for candidate in candidates
        ],
    }


def _provider_caller(*, endpoint: str | None, model_name: str | None, timeout_seconds: float) -> ModelCaller:
    if not endpoint or not model_name:
        raise ValueError("endpoint and model_name are required")
    provider = LocalVisionProvider(endpoint=endpoint, model_name=model_name, timeout_seconds=timeout_seconds)

    def call(*, image_path: Path, prompt_text: str, max_tokens: int, temperature: float) -> str:
        response = provider._call_openai_compatible_endpoint(  # noqa: SLF001
            image_path,
            prompt_text,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return provider._extract_message_text(response)  # noqa: SLF001

    return call


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated coarse-proposal hierarchical-region MVP-2 A/B evaluation.")
    parser.add_argument("--case-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-profile", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    profile = _read_json(args.model_profile)
    report = run_manifest(
        args.case_manifest,
        args.out,
        endpoint=str(profile.get("endpoint") or ""),
        model_name=str(profile.get("model_name") or ""),
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps({"report_path": report["report_path"], "case_count": report["case_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
