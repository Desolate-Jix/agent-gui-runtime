from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_precise_understanding_fusion_status_report.json"


def report_fusion_status(
    *,
    report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_path = _resolve_path(report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    source = _read_json(source_path)
    fusion = source.get("fused_precise_understanding") if isinstance(source.get("fused_precise_understanding"), dict) else {}
    items = _list_of_dicts(fusion.get("items"))
    summary = fusion.get("summary") if isinstance(fusion.get("summary"), dict) else {}
    full_overlay_path = _text(source.get("full_screen_understanding_overlay_path"))
    overlay_path = _text(source.get("compiled_overlay_path"))
    screenshot_path = _text(source.get("screenshot_path"), fusion.get("screenshot_path"))
    calibration_backlog = _calibration_backlog(source, fusion)
    block_reason_counts = _block_reason_counts(items)
    promotable_items = [
        item
        for item in items
        if isinstance(item.get("promotion_policy"), dict)
        and item["promotion_policy"].get("promotable_to_pathgraph_candidate_review") is True
    ]
    blocked_items = [item for item in items if item not in promotable_items]

    payload = {
        "contract_version": "learn_precise_understanding_fusion_status_report_v1",
        "source_report_path": _relative_path(source_path, root),
        "source_contract": source.get("contract_version"),
        "fusion_contract": fusion.get("contract_version"),
        "screenshot_path": screenshot_path,
        "full_screen_understanding_overlay_path": full_overlay_path,
        "compiled_overlay_path": overlay_path,
        "display_readiness": {
            "status": "display_ready" if items and (_path_exists(full_overlay_path, root) or _path_exists(overlay_path, root)) else "display_evidence_missing",
            "item_count": len(items),
            "full_screen_overlay_available": _path_exists(full_overlay_path, root),
            "overlay_available": _path_exists(overlay_path, root),
            "screenshot_available": _path_exists(screenshot_path, root),
            "interpretation": "display readiness only; it does not authorize Execute or PathGraph promotion",
        },
        "pathgraph_preparation": {
            "status": _pathgraph_status(promotable_items=promotable_items, blocked_items=blocked_items, items=items),
            "promotable_item_count": len(promotable_items),
            "blocked_item_count": len(blocked_items),
            "required_next_evidence": _required_next_evidence(block_reason_counts, items=items),
            "interpretation": "human PathGraph candidate review readiness only; not Runtime PathGraph promotion",
        },
        "calibration_backlog": calibration_backlog,
        "summary": {
            "attempted": int(summary.get("attempted") or len(items)),
            "promotable_to_pathgraph_candidate_review": len(promotable_items),
            "needs_human_review": int(summary.get("needs_human_review") or 0),
            "safe_intercepts": int(summary.get("safe_intercepts") or 0),
            "failed": int(summary.get("failed") or 0),
            "real_clicks": _sum_int(items, "real_clicks"),
        },
        "block_reason_counts": block_reason_counts,
        "calibration_status_counts": _field_counts(items, "calibration_status"),
        "gate_safety_counts": _field_counts(items, "gate_safety"),
        "point_quality_counts": _field_counts(items, "point_quality"),
        "items": [_item_diagnosis(item) for item in items],
        "safety": {
            "real_clicks": _sum_int(items, "real_clicks"),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
            "no_dispatch": True,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "not_accuracy": True,
        "not_e2e_success": True,
        "interpretation": (
            "Offline status report for fused whole-screen understanding plus Execute dry-run locator evidence. "
            "It is for review and PathGraph preparation only; it is not recognition accuracy, Execute authorization, "
            "live fill, submit, or Runtime PathGraph promotion."
        ),
    }
    output_path = out / REPORT_NAME
    payload["report_path"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _calibration_backlog(source: dict[str, Any], fusion: dict[str, Any]) -> dict[str, Any]:
    backlog = source.get("calibration_backlog") if isinstance(source.get("calibration_backlog"), dict) else {}
    if not backlog:
        backlog = fusion.get("calibration_backlog") if isinstance(fusion.get("calibration_backlog"), dict) else {}
    if not backlog:
        return {
            "contract_version": "numbered_region_calibration_backlog_v1",
            "summary": {
                "uncalibrated_locator_cards": 0,
                "display_only": True,
                "execute_binding_enabled": False,
            },
            "items": [],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    copied = dict(backlog)
    copied["summary"] = dict(copied.get("summary") if isinstance(copied.get("summary"), dict) else {})
    copied["summary"]["display_only"] = True
    copied["summary"]["execute_binding_enabled"] = False
    copied["items"] = _list_of_dicts(copied.get("items"))
    copied["display_only"] = True
    copied["execute_binding_enabled"] = False
    copied["artifact_is_authorization"] = False
    return copied


def _pathgraph_status(*, promotable_items: list[dict[str, Any]], blocked_items: list[dict[str, Any]], items: list[dict[str, Any]]) -> str:
    if not items:
        return "not_covered"
    if promotable_items and blocked_items:
        return "partially_ready_for_human_review"
    if promotable_items:
        return "ready_for_human_review"
    return "blocked_from_pathgraph_candidate_review"


def _required_next_evidence(block_reason_counts: dict[str, int], *, items: list[dict[str, Any]]) -> list[str]:
    required: list[str] = []
    if block_reason_counts.get("semantic_only_requires_cross_evidence_or_human_review"):
        required.append("same_screenshot_ocr_uia_or_calibrated_support")
    if block_reason_counts.get("pre_click_gate_rejected") or any(
        _text(item.get("calibration_status")) == "gate_rejected" or _text(item.get("gate_safety")) == "passed_rejected"
        for item in items
    ):
        required.append("review_gate_rejection_reason_before_pathgraph_wiring")
    if block_reason_counts.get("locator_model_or_seed_requires_human_review"):
        required.append("manual_bbox_or_locator_prompt_review")
    if not required:
        required.append("human_promotion_review")
    return required


def _item_diagnosis(item: dict[str, Any]) -> dict[str, Any]:
    policy = item.get("promotion_policy") if isinstance(item.get("promotion_policy"), dict) else {}
    return {
        "region_no": item.get("region_no"),
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label"),
        "role": item.get("role"),
        "evidence_level": item.get("evidence_level"),
        "calibration_status": item.get("calibration_status"),
        "point_quality": item.get("point_quality"),
        "gate_safety": item.get("gate_safety"),
        "promotable_to_pathgraph_candidate_review": policy.get("promotable_to_pathgraph_candidate_review") is True,
        "block_reason": _text(policy.get("block_reason")),
        "trace_path": item.get("trace_path"),
        "recognition_plan_trace_path": item.get("recognition_plan_trace_path"),
        "overlay_path": item.get("overlay_path"),
        "real_clicks": int(item.get("real_clicks") or 0),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _block_reason_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        policy = item.get("promotion_policy") if isinstance(item.get("promotion_policy"), dict) else {}
        if policy.get("promotable_to_pathgraph_candidate_review") is True:
            continue
        reason = _text(policy.get("block_reason")) or "missing_promotion_policy"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _field_counts(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = _text(item.get(key)) or "missing"
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _path_exists(path_text: str, root: Path) -> bool:
    if not path_text:
        return False
    path = Path(path_text)
    if not path.is_absolute():
        path = root / path
    return path.exists()


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _sum_int(items: list[dict[str, Any]], key: str) -> int:
    return sum(int(item.get(key) or 0) for item in items)


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize fused learning precise-understanding readiness.")
    parser.add_argument("--report", required=True, help="Path to numbered_region_calibration_report.json")
    parser.add_argument("--out", required=True, help="Output directory for fusion status report")
    parser.add_argument("--json", action="store_true", help="Print report JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_fusion_status(report_path=args.report, out_dir=args.out, json_stdout=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
