from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.main import app


@dataclass(frozen=True)
class ChainSmokeCase:
    case_id: str
    trace_path: str
    source_image_path: str


def build_protected_cases(regression_root: Path) -> list[ChainSmokeCase]:
    cases: list[ChainSmokeCase] = []
    for case_id in ["applemusic", "qq", "python_org"]:
        case_dir = regression_root / case_id
        reports = sorted(case_dir.glob("learn_two_stage_replay_report_*.json"))
        if not reports:
            raise FileNotFoundError(f"missing replay report for {case_id}: {case_dir}")
        report = _read_json(reports[-1])
        observe_bundle = report.get("observe_bundle") if isinstance(report.get("observe_bundle"), dict) else {}
        source_override = report.get("source_image_override") if isinstance(report.get("source_image_override"), dict) else {}
        trace_path = str(report.get("source_trace_path") or "").strip()
        source_image_path = str(
            source_override.get("path")
            or observe_bundle.get("source_image_path")
            or observe_bundle.get("image_path")
            or ""
        ).strip()
        if not trace_path:
            raise ValueError(f"missing source trace for {case_id}")
        if not source_image_path:
            raise ValueError(f"missing source image for {case_id}")
        cases.append(ChainSmokeCase(case_id=case_id, trace_path=trace_path, source_image_path=source_image_path))
    return cases


def classify_case_quality(summary: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    case_id = str(summary.get("case_id") or "").strip().lower()
    deep = summary.get("deep_calibration") if isinstance(summary.get("deep_calibration"), dict) else {}
    trial = summary.get("trial") if isinstance(summary.get("trial"), dict) else {}
    two_stage = summary.get("two_stage") if isinstance(summary.get("two_stage"), dict) else {}
    page_detail = summary.get("page_detail") if isinstance(summary.get("page_detail"), dict) else {}
    scaffold = summary.get("scaffold") if isinstance(summary.get("scaffold"), dict) else {}
    draft_counts = trial.get("draft_section_counts") if isinstance(trial.get("draft_section_counts"), dict) else {}

    stage2_was_expected = two_stage.get("stage2_numbering_skipped") is False
    if int(deep.get("review_box_count") or 0) <= 0:
        issues.append("missing_deep_review_boxes")
    if stage2_was_expected and int(trial.get("two_stage_review_region_count") or 0) <= 0:
        issues.append("missing_two_stage_review_regions")
    if int(draft_counts.get("regions") or 0) <= 0:
        issues.append("missing_draft_regions")
    if int(page_detail.get("region_count") or 0) <= 0:
        issues.append("missing_page_detail_regions")
    if scaffold.get("page_detail_readonly_pathgraph_preview_status") != "page_detail_readonly_preview_ready":
        issues.append("missing_readonly_pathgraph_preview")

    stress_sample = case_id in {"python_org", "python"}
    if stress_sample:
        issues.append("python_org_stress_sample")
    status = "needs_review" if issues else "review_only_chain_ready"
    if stress_sample:
        status = "stress_only_needs_review"

    return {
        "status": status,
        "issues": issues,
        "runtime_pathgraph_ready": False,
        "execute_binding_enabled": False,
        "interpretation": (
            "display/review-only chain quality; not recognition accuracy or Runtime PathGraph readiness. "
            "Python.org is kept as a protected stress sample, not a success baseline."
        ),
    }


def run_case(client: TestClient, case: ChainSmokeCase, out_dir: Path) -> dict[str, Any]:
    trace_path = Path(case.trace_path)
    trace = _read_json(trace_path)
    observe_result = _trace_result(trace)
    source_image_path = str(case.source_image_path)
    source_image = Path(source_image_path)
    if not source_image.exists():
        source_image = ROOT / source_image_path
    if not source_image.exists():
        raise FileNotFoundError(f"{case.case_id} source image missing: {case.source_image_path}")

    state_hint = str(observe_result.get("state_guess") or observe_result.get("state_hint") or "home")
    summary: dict[str, Any] = {
        "case_id": case.case_id,
        "source_trace_path": str(trace_path),
        "source_image_path": str(source_image),
        "state_hint": state_hint,
        "safety": _safety_boundary(),
    }

    two_stage_payload = {
        "app_name": case.case_id,
        "state_hint": state_hint,
        "trace_path": str(trace_path),
        "source_image_path": str(source_image),
        "observe_result": observe_result,
        "require_stage1_gate": True,
        "stage2_region_strategy": "partitioned",
    }
    two_stage = _post_json(client, "/panel/run_learning_two_stage_understanding", two_stage_payload)
    two_stage_data = two_stage.get("data") if isinstance(two_stage.get("data"), dict) else {}
    fusion = two_stage_data.get("fusion") if isinstance(two_stage_data.get("fusion"), dict) else {}
    fused_boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    summary["two_stage"] = {
        "success": bool(two_stage.get("success")),
        "report_path": two_stage_data.get("report_path"),
        "stage1_gate_status": (two_stage_data.get("stage1_gate") or {}).get("status")
        if isinstance(two_stage_data.get("stage1_gate"), dict)
        else "",
        "stage2_numbering_skipped": two_stage_data.get("stage2_numbering_skipped"),
        "overlay_path": two_stage_data.get("coordinate_overlay_path")
        or two_stage_data.get("full_screen_understanding_overlay_path"),
        "review_box_count": len(fused_boxes) or _two_stage_review_box_count(two_stage_data),
    }

    locate_payload = {
        "goal": "learn all visible controls",
        "task": "click_target",
        "app_name": case.case_id,
        "state_hint": state_hint,
        "provider_mode": "local_grounding",
        "agent_mode": "learn",
        "learn_depth": "deep",
        "metadata": {
            "learn_all_targets": True,
            "learn_all_targets_reason": "protected three-interface Learning Interface chain smoke",
        },
        "capture_live": False,
        "image_path": str(source_image),
        "observe_trace_path": str(trace_path),
        "dry_run": True,
        "trace": True,
        "write_policy": {"path_graph": False, "element_memory": False, "trace": True},
    }
    locate = _post_json(client, "/vision/locate_target", locate_payload)
    locate_result = ((locate.get("data") or {}).get("result")) if isinstance(locate.get("data"), dict) else {}
    locate_result = locate_result if isinstance(locate_result, dict) else {}
    learn_targets = locate_result.get("learn_all_targets") if isinstance(locate_result.get("learn_all_targets"), dict) else {}
    summary["deep_calibration"] = {
        "success": bool(locate.get("success")),
        "location_status": locate_result.get("location_status"),
        "target_count": learn_targets.get("target_count"),
        "review_box_count": learn_targets.get("review_box_count"),
        "raw_candidate_count": learn_targets.get("raw_candidate_count"),
        "validated_count": learn_targets.get("validated_count"),
        "invalid_count": learn_targets.get("invalid_count"),
        "overlay_path": learn_targets.get("overlay_path") or locate_result.get("coordinate_overlay_path"),
        "model_review_status": (locate_result.get("learn_locate_model_review") or {}).get("status")
        if isinstance(locate_result.get("learn_locate_model_review"), dict)
        else "",
        "model_review_reason": (locate_result.get("learn_locate_model_review") or {}).get("reason")
        if isinstance(locate_result.get("learn_locate_model_review"), dict)
        else "",
        "vista_validation_status": (learn_targets.get("vista_coordinate_validation") or {}).get("status")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else "",
        "trace_path": locate_result.get("trace_path"),
    }

    observation_evidence = _observation_evidence(
        observe_result=observe_result,
        image_path=str(source_image),
        locate_result=locate_result,
        learn_targets=learn_targets,
    )
    trial = _post_json(
        client,
        "/panel/run_learning_recognition_trial",
        {
            "app_name": case.case_id,
            "state_hint": state_hint,
            "summary": f"protected chain smoke: learn {case.case_id} interface",
            "observation_evidence": observation_evidence,
            "two_stage_report_path": summary["two_stage"].get("report_path"),
        },
    )
    trial_data = trial.get("data") if isinstance(trial.get("data"), dict) else {}
    trial_summary = trial_data.get("summary") if isinstance(trial_data.get("summary"), dict) else {}
    summary["trial"] = {
        "success": bool(trial.get("success")),
        "trial_path": trial_data.get("trial_path"),
        "status": trial_data.get("status"),
        "screen_inventory_count": trial_summary.get("screen_inventory_count"),
        "two_stage_review_region_count": trial_summary.get("two_stage_review_region_count"),
        "two_stage_report_attached": trial_summary.get("two_stage_report_attached"),
        "two_stage_stage1_gate_status": trial_summary.get("two_stage_stage1_gate_status"),
        "two_stage_stage2_numbering_skipped": trial_summary.get("two_stage_stage2_numbering_skipped"),
        "two_stage_review_box_count": trial_summary.get("two_stage_review_box_count"),
        "accepted_for_grounding_count": trial_summary.get("accepted_for_grounding_count"),
        "grounding_validation_count": trial_summary.get("grounding_validation_count"),
        "draft_section_counts": trial_summary.get("draft_section_counts"),
        "precise_understanding_status": trial_summary.get("precise_understanding_status"),
    }

    trial_path = summary["trial"].get("trial_path")
    if trial_path:
        page = _post_json(client, "/panel/create_page_detail_candidate", {"source_path": trial_path})
    else:
        page = {"success": False, "data": {}}
    page_data = page.get("data") if isinstance(page.get("data"), dict) else {}
    page_summary = page_data.get("summary") if isinstance(page_data.get("summary"), dict) else {}
    summary["page_detail"] = {
        "success": bool(page.get("success")),
        "report_path": page_data.get("report_path"),
        "preview_path": page_data.get("preview_path"),
        "region_count": page_summary.get("region_count"),
        "section_count": page_summary.get("section_count"),
    }

    scaffold_source = summary["page_detail"].get("report_path") or trial_path
    if scaffold_source:
        scaffold = _post_json(client, "/panel/create_learning_demo_scaffold", {"source_path": scaffold_source})
    else:
        scaffold = {"success": False, "data": {}}
    scaffold_data = scaffold.get("data") if isinstance(scaffold.get("data"), dict) else {}
    scaffold_summary = scaffold_data.get("summary") if isinstance(scaffold_data.get("summary"), dict) else {}
    summary["scaffold"] = {
        "success": bool(scaffold.get("success")),
        "report_path": scaffold_data.get("report_path"),
        "readiness_status": scaffold_summary.get("readiness_status"),
        "page_detail_readonly_pathgraph_preview_status": scaffold_summary.get(
            "page_detail_readonly_pathgraph_preview_status"
        ),
    }
    summary["quality"] = classify_case_quality(summary)
    summary["chain_success"] = all(
        bool((summary.get(key) or {}).get("success"))
        for key in ["two_stage", "deep_calibration", "trial", "page_detail", "scaffold"]
    )
    case_out = out_dir / case.case_id / "learning_interface_chain_smoke.json"
    case_out.parent.mkdir(parents=True, exist_ok=True)
    case_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary["case_report_path"] = str(case_out)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run protected Learning Interface chain smoke for three surfaces.")
    parser.add_argument(
        "--regression-root",
        default="logs/benchmarks/learn_three_surface_regression_20260710_v5",
        help="Regression root containing applemusic/qq/python_org two-stage replay reports.",
    )
    parser.add_argument("--out", required=True, help="Output directory for reports and contact sheet.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary.")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    cases = build_protected_cases(Path(args.regression_root))
    case_results = [run_case(client, case, out_dir) for case in cases]
    contact_sheet = create_contact_sheet(case_results, out_dir / "learning_interface_chain_contact_sheet.png")
    report = {
        "contract_version": "learning_interface_chain_smoke_report_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(case_results),
        "chain_success_count": sum(1 for item in case_results if item.get("chain_success")),
        "review_only_chain_ready_count": sum(
            1 for item in case_results if (item.get("quality") or {}).get("status") == "review_only_chain_ready"
        ),
        "stress_only_needs_review_count": sum(
            1 for item in case_results if (item.get("quality") or {}).get("status") == "stress_only_needs_review"
        ),
        "runtime_pathgraph_ready_count": 0,
        "safety": _safety_boundary(),
        "contact_sheet_path": str(contact_sheet),
        "cases": case_results,
        "interpretation": "Protected three-interface display/review chain smoke; not recognition accuracy or Execute readiness.",
    }
    report_path = out_dir / "learning_interface_chain_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"report_path={report_path}")
        print(f"contact_sheet_path={contact_sheet}")
    return 0


def create_contact_sheet(case_results: list[dict[str, Any]], out_path: Path) -> Path:
    thumbs: list[tuple[str, Image.Image]] = []
    for result in case_results:
        for label, path in [
            ("two-stage", (result.get("two_stage") or {}).get("overlay_path")),
            ("deep", (result.get("deep_calibration") or {}).get("overlay_path")),
        ]:
            image_path = _resolve_path(path)
            if image_path and image_path.exists():
                with Image.open(image_path) as image:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((520, 360))
                    canvas = Image.new("RGB", (540, 405), "white")
                    canvas.paste(thumb, ((540 - thumb.width) // 2, 34))
                    draw = ImageDraw.Draw(canvas)
                    draw.text((10, 10), f"{result.get('case_id')} · {label}", fill=(0, 0, 0), font=_font())
                    thumbs.append((f"{result.get('case_id')} {label}", canvas))
    if not thumbs:
        raise ValueError("no overlay images available for contact sheet")
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 540, rows * 405), (245, 247, 250))
    for index, (_label, thumb) in enumerate(thumbs):
        x = (index % cols) * 540
        y = (index // cols) * 405
        sheet.paste(thumb, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 16)
    except Exception:
        return ImageFont.load_default()


def _trace_result(trace: dict[str, Any]) -> dict[str, Any]:
    if isinstance(trace.get("result"), dict):
        return trace["result"]
    data = trace.get("data") if isinstance(trace.get("data"), dict) else {}
    if isinstance(data.get("result"), dict):
        return data["result"]
    return trace


def _observation_evidence(
    *,
    observe_result: dict[str, Any],
    image_path: str,
    locate_result: dict[str, Any],
    learn_targets: dict[str, Any],
) -> dict[str, Any]:
    screen_reading = observe_result.get("screen_reading") if isinstance(observe_result.get("screen_reading"), dict) else {}
    return {
        "contract_version": "panel_learning_draft_observation_evidence_v1",
        "evidence_source": "protected_three_interface_chain_smoke",
        "current_image_path": image_path,
        "screen_size": observe_result.get("screen_size")
        or observe_result.get("viewport_size")
        or observe_result.get("image_size")
        or {},
        "screen_summary": observe_result.get("screen_summary")
        or screen_reading.get("screen_summary")
        or "protected learning interface chain smoke",
        "screen_map": observe_result.get("screen_map") if isinstance(observe_result.get("screen_map"), dict) else {},
        "coordinate_overlay_path": learn_targets.get("overlay_path") or locate_result.get("coordinate_overlay_path") or "",
        "learn_all_targets_summary": {
            "status": learn_targets.get("status"),
            "target_count": learn_targets.get("target_count") or 0,
            "validated_count": learn_targets.get("validated_count") or 0,
            "invalid_count": learn_targets.get("invalid_count") or 0,
            "review_box_count": learn_targets.get("review_box_count") or 0,
            "coordinate_calibration_status": "validated_targets_available"
            if int(learn_targets.get("target_count") or 0)
            else "review_overlay_only_model_validation_not_run",
        },
        "calibrated_targets": (learn_targets.get("targets") if isinstance(learn_targets.get("targets"), list) else [])[:120],
        "review_boxes": (learn_targets.get("review_boxes") if isinstance(learn_targets.get("review_boxes"), list) else [])[:160],
        "path_map_review_summary": (locate_result.get("path_map_review") or {}).get("summary")
        if isinstance(locate_result.get("path_map_review"), dict)
        else {},
        "no_click_authorization": True,
        "execute_binding_enabled": False,
    }


def _post_json(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    try:
        body = response.json()
    except Exception:
        body = {"success": False, "message": response.text}
    body["http_status_code"] = response.status_code
    return body


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_path(path: Any) -> Path | None:
    path_text = str(path or "").strip()
    if not path_text:
        return None
    candidate = Path(path_text)
    if candidate.exists():
        return candidate
    candidate = ROOT / path_text
    if candidate.exists():
        return candidate
    return None


def _two_stage_review_box_count(two_stage_data: dict[str, Any]) -> int:
    fusion = two_stage_data.get("fusion") if isinstance(two_stage_data.get("fusion"), dict) else {}
    boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    if boxes:
        return len(boxes)
    fusion_status = two_stage_data.get("fusion_status") if isinstance(two_stage_data.get("fusion_status"), dict) else {}
    fusion_summary = fusion_status.get("summary") if isinstance(fusion_status.get("summary"), dict) else {}
    status_count = int(fusion_status.get("review_box_count") or fusion_summary.get("fused_review_box_count") or 0)
    if status_count:
        return status_count
    report_path = _resolve_path(two_stage_data.get("report_path"))
    if report_path and report_path.exists():
        try:
            report = _read_json(report_path)
        except Exception:
            return 0
        report_fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
        report_boxes = (
            report_fusion.get("fused_review_boxes")
            if isinstance(report_fusion.get("fused_review_boxes"), list)
            else []
        )
        if report_boxes:
            return len(report_boxes)
        report_status = report.get("fusion_status") if isinstance(report.get("fusion_status"), dict) else {}
        report_summary = report_status.get("summary") if isinstance(report_status.get("summary"), dict) else {}
        return int(report_status.get("review_box_count") or report_summary.get("fused_review_box_count") or 0)
    return 0


def _safety_boundary() -> dict[str, Any]:
    return {
        "live_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "execute_binding_enabled": False,
        "runtime_pathgraph_promotion": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
