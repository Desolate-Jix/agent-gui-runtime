from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review
from app.learn.pathgraph_candidate import attach_detail_observe_result_to_candidate


REPORT_NAME = "detail_observe_attach_result.json"


def attach_detail_observe_to_candidate(
    *,
    candidate_path: str | Path,
    detail_source_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    request_ids: list[str] | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    candidate = _resolve_path(candidate_path, root)
    detail_source = _resolve_path(detail_source_path, root)
    out = _resolve_output_dir(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    wrapper_before = _read_json(candidate)
    pending_requests = _list_of_dicts(wrapper_before.get("pending_detail_observe_requests"))
    selected_request_ids = _selected_request_ids(pending_requests, request_ids)

    last_attach_result: dict[str, Any] | None = None
    for request_id in selected_request_ids:
        last_attach_result = attach_detail_observe_result_to_candidate(
            candidate,
            request_id=request_id,
            detail_source_path=detail_source,
            project_root=root,
        )

    review = load_learning_draft_review(candidate, project_root=root)
    candidate_review = review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
    readiness = (
        candidate_review.get("pathgraph_readiness_summary")
        if isinstance(candidate_review.get("pathgraph_readiness_summary"), dict)
        else {}
    )
    gate = readiness.get("promotion_review_gate") if isinstance(readiness.get("promotion_review_gate"), dict) else {}
    wrapper_after = _read_json(candidate)
    attachments = _list_of_dicts(wrapper_after.get("detail_surface_attachments"))
    attached_regions = _list_of_dicts(candidate_review.get("attached_detail_regions"))
    attached_actions = _list_of_dicts(candidate_review.get("attached_detail_actions"))

    result = {
        "contract_version": "pathgraph_candidate_detail_observe_attach_result_v1",
        "attachment_status": "attached" if selected_request_ids else "no_pending_requests",
        "pending_request_count": len(pending_requests),
        "attached_request_count": len(selected_request_ids),
        "attached_request_ids": selected_request_ids,
        "detail_surface_attachment_count": len(attachments),
        "attached_detail_region_count": len(attached_regions),
        "attached_detail_action_count": len(attached_actions),
        "readiness_status": readiness.get("readiness_status"),
        "promotion_review_blockers": readiness.get("promotion_review_blockers") or [],
        "promotion_gate_status": gate.get("gate_status"),
        "promotion_gate_failed_check_ids": gate.get("failed_check_ids") or [],
        "pathgraph_candidate_path": _relative_path(candidate, root),
        "runtime_path_graph_candidate_path": wrapper_after.get("runtime_path_graph_candidate_path"),
        "interface_map_candidate_path": wrapper_after.get("interface_map_candidate_path"),
        "validation_report_path": wrapper_after.get("validation_report_path"),
        "detail_source_path": _relative_path(detail_source, root),
        "last_attach_result_contract": last_attach_result.get("contract_version") if last_attach_result else None,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "no_dispatch": True,
        "candidate_only": True,
        "interpretation": (
            "detail observe attachment is offline candidate enrichment only; "
            "it does not authorize Execute, clicks, live form fill, or submit"
        ),
    }
    report_path = out / REPORT_NAME
    result["report_path"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def _selected_request_ids(pending_requests: list[dict[str, Any]], requested: list[str] | None) -> list[str]:
    pending_by_id = {str(item.get("request_id") or ""): item for item in pending_requests}
    if requested:
        missing = [item for item in requested if item not in pending_by_id]
        if missing:
            raise ValueError(f"pending detail observe request not found: {', '.join(missing)}")
        return requested
    return [
        request_id
        for request_id, item in pending_by_id.items()
        if request_id and str(item.get("status") or "pending") != "attached"
    ]


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _resolve_output_dir(path: str | Path, root: Path) -> Path:
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach an offline detail observe draft to a PathGraph candidate.")
    parser.add_argument("--candidate", required=True, help="Path to pathgraph_candidate.json")
    parser.add_argument("--detail-source", required=True, help="Path to detail observe trial/draft JSON")
    parser.add_argument("--out", required=True, help="Directory for detail observe attach report")
    parser.add_argument("--request-id", action="append", dest="request_ids", help="Specific pending request id to attach")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    attach_detail_observe_to_candidate(
        candidate_path=args.candidate,
        detail_source_path=args.detail_source,
        out_dir=args.out,
        request_ids=args.request_ids,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
