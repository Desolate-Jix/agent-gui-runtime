from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_support_acquisition_brief(
    *,
    queue_path: str | Path,
    status_path: str | Path,
    out: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    queue_path = Path(queue_path)
    status_path = Path(status_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8-sig"))
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    tasks = queue.get("tasks") if isinstance(queue.get("tasks"), list) else []
    statuses = status.get("case_statuses") if isinstance(status.get("case_statuses"), list) else []
    status_by_case = {
        str(item.get("case_id") or ""): item
        for item in statuses
        if isinstance(item, dict)
    }
    pending = [
        task
        for task in tasks
        if isinstance(task, dict)
        and task.get("task_type") == "capture_same_screenshot_support"
        and (status_by_case.get(str(task.get("case_id") or "")) or {}).get("status") == "pending_support_capture"
    ]
    pending = sorted(pending, key=lambda item: (int(item.get("priority") or 99), str(item.get("case_id") or "")))
    if not pending:
        report = {
            "contract_version": "learn_recognition_support_acquisition_brief_v1",
            "status": "no_pending_support_capture",
            "queue_path": str(queue_path),
            "status_path": str(status_path),
            "safety": _safety(),
        }
        return _emit(report, out=out, json_stdout=json_stdout)
    task = pending[0]
    case_id = str(task.get("case_id") or "")
    report = {
        "contract_version": "learn_recognition_support_acquisition_brief_v1",
        "status": "target_selected",
        "queue_path": str(queue_path),
        "status_path": str(status_path),
        "selected_case": {
            "case_id": case_id,
            "priority": task.get("priority"),
            "task_type": task.get("task_type"),
            "surface": task.get("surface", ""),
            "goal": task.get("goal", ""),
            "current_status": task.get("current_status", ""),
        },
        "target_screenshot": _target_screenshot_metadata(task, queue_path=queue_path),
        "operator_steps": _operator_steps(task),
        "acceptance_criteria": {
            "support_validation_must_return": "status=validated and bindable=true",
            "support_screenshot_sha256_must_match_target": True,
            "bind_writes_per_case_manifest_only": True,
            "rerun_parser_batch_and_readiness_before_pathgraph_claim": True,
        },
        "interpretation": (
            "operator brief only; it does not reproduce the window, capture support, write manifests, "
            "start models, run grounding, or authorize Execute"
        ),
        "safety": _safety(),
    }
    return _emit(report, out=out, json_stdout=json_stdout)


def _operator_steps(task: dict[str, Any]) -> list[dict[str, Any]]:
    commands = task.get("recommended_commands") if isinstance(task.get("recommended_commands"), list) else []
    validation_commands = (
        task.get("support_validation_commands") if isinstance(task.get("support_validation_commands"), list) else []
    )
    preflight = task.get("preflight") if isinstance(task.get("preflight"), dict) else {}
    return [
        {
            "step": "reproduce_target_window",
            "manual_window_reproduction_required": bool(preflight.get("manual_window_reproduction_required")),
            "target_screenshot_path": str(task.get("screenshot_path") or ""),
            "target_screenshot_sha256": str(task.get("screenshot_sha256") or ""),
        },
        {
            "step": "capture_same_screenshot_support",
            "command": str(commands[0] if commands else ""),
        },
        {
            "step": "validate_support_only",
            "command": str(validation_commands[0] if validation_commands else ""),
            "writes_manifest": False,
        },
        {
            "step": "bind_per_case_manifest",
            "command": str(commands[-1] if commands else ""),
            "requires_bindable_true": True,
        },
    ]


def _target_screenshot_metadata(task: dict[str, Any], *, queue_path: Path) -> dict[str, Any]:
    path_value = str(task.get("screenshot_path") or "")
    resolved = _resolve_screenshot_path(path_value, queue_path=queue_path)
    expected_sha = str(task.get("screenshot_sha256") or "")
    metadata = {
        "path": path_value,
        "sha256": expected_sha,
        "actual_sha256": "",
        "sha256_match": False,
        "exists": bool(resolved and resolved.exists()),
        "width": None,
        "height": None,
        "ready_for_reproduction": False,
        "blockers": [],
    }
    if resolved and resolved.exists():
        metadata["actual_sha256"] = _sha256_file(resolved)
        metadata["sha256_match"] = bool(expected_sha) and metadata["actual_sha256"] == expected_sha
        with Image.open(resolved) as image:
            metadata["width"] = image.width
            metadata["height"] = image.height
    blockers: list[str] = []
    if not metadata["exists"]:
        blockers.append("target_screenshot_missing")
    elif not metadata["sha256_match"]:
        blockers.append("target_screenshot_sha256_mismatch")
    metadata["blockers"] = blockers
    metadata["ready_for_reproduction"] = not blockers
    return metadata


def _resolve_screenshot_path(path_value: str, *, queue_path: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    queue_parent_candidate = (queue_path.parent / path).resolve()
    if queue_parent_candidate.exists():
        return queue_parent_candidate
    return cwd_candidate


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }


def _emit(report: dict[str, Any], *, out: str | Path | None, json_stdout: bool) -> dict[str, Any]:
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the next operator brief for same-screenshot support capture.")
    parser.add_argument("--queue", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--out")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_support_acquisition_brief(
        queue_path=args.queue,
        status_path=args.status,
        out=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
