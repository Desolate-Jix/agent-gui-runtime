from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_fusion_pathgraph_candidate_status_report.json"


def build_fusion_pathgraph_candidate_status(
    *,
    candidate_path: str | Path,
    detail_attach_report_path: str | Path,
    promotion_replay_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    candidate_file = _resolve_path(candidate_path, root)
    attach_file = _resolve_path(detail_attach_report_path, root)
    replay_file = _resolve_path(promotion_replay_report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    candidate = _read_json(candidate_file)
    attach = _read_json(attach_file)
    replay = _read_json(replay_file)
    replay_case = _first_replay_case(replay, candidate_file, root)
    failed_checks = _list_of_text(replay_case.get("failed_check_ids"))
    report = {
        "contract_version": "learn_fusion_pathgraph_candidate_status_report_v1",
        "candidate_path": _relative_path(candidate_file, root),
        "detail_attach_report_path": _relative_path(attach_file, root),
        "promotion_replay_report_path": _relative_path(replay_file, root),
        "summary": {
            "candidate_validation_status": _text(candidate.get("validation_status") or candidate.get("candidate_status")),
            "state_count": _summary_number(candidate, "state_count"),
            "region_count": _summary_number(candidate, "region_count"),
            "action_template_count": _summary_number(candidate, "action_template_count"),
            "pending_detail_observe_request_count": len(_list_of_dicts(candidate.get("pending_detail_observe_requests"))),
            "detail_attachment_status": _text(attach.get("attachment_status")),
            "attached_request_count": int(attach.get("attached_request_count") or 0),
            "detail_surface_attachment_count": int(attach.get("detail_surface_attachment_count") or 0),
            "attached_detail_region_count": int(attach.get("attached_detail_region_count") or 0),
            "attached_detail_action_count": int(attach.get("attached_detail_action_count") or 0),
            "readiness_status": _text(replay_case.get("readiness_status")),
            "promotion_gate_status": _text(replay_case.get("gate_status")),
            "remaining_failed_checks": failed_checks,
            "ready_for_runtime_pathgraph_promotion": False,
            "real_clicks": 0,
        },
        "next_required_steps": _next_required_steps(failed_checks),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "candidate_only": True,
        "no_dispatch": True,
        "interpretation": (
            "Status report for the fused-understanding PathGraph candidate review chain. "
            "It summarizes offline evidence only and does not authorize Execute or Runtime promotion."
        ),
    }
    report_path = out / REPORT_NAME
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_pathgraph_candidate_status_build_result_v1",
        "status_report_path": str(report_path.resolve()),
        "summary": report["summary"],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _first_replay_case(replay: dict[str, Any], candidate_file: Path, root: Path) -> dict[str, Any]:
    cases = _list_of_dicts(replay.get("cases"))
    relative = _relative_path(candidate_file, root)
    for case in cases:
        if _text(case.get("candidate_path")) == relative:
            return case
    return cases[0] if cases else {}


def _summary_number(candidate: dict[str, Any], key: str) -> int:
    summary = candidate.get("validation_summary") if isinstance(candidate.get("validation_summary"), dict) else {}
    return int(summary.get(key) or 0)


def _next_required_steps(failed_checks: list[str]) -> list[str]:
    steps: list[str] = []
    if "current_screen_freshness" in failed_checks:
        steps.append("bind_current_screen_freshness_or_capture_same_screenshot_support")
    if not failed_checks:
        steps.append("human_promotion_review_required_before_runtime_pathgraph_promotion")
    return steps


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


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize fused-understanding PathGraph candidate review status.")
    parser.add_argument("--candidate", required=True, help="Path to pathgraph_candidate.json")
    parser.add_argument("--detail-attach-report", required=True, help="Path to detail_observe_attach_result.json")
    parser.add_argument("--promotion-replay-report", required=True, help="Path to pathgraph_promotion_gate_replay_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    build_fusion_pathgraph_candidate_status(
        candidate_path=args.candidate,
        detail_attach_report_path=args.detail_attach_report,
        promotion_replay_report_path=args.promotion_replay_report,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
