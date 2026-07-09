from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.bind_learn_recognition_support_to_manifest import bind_support_to_manifest


def report_support_acquisition_status(
    *,
    queue_path: str | Path,
    out: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    queue_path = Path(queue_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8-sig"))
    tasks = queue.get("tasks") if isinstance(queue.get("tasks"), list) else []
    statuses = [_status_for_task(task, root) for task in tasks if isinstance(task, dict)]
    summary = {
        "task_count": len(statuses),
        "support_artifact_present_count": sum(1 for item in statuses if item.get("support_exists") is True),
        "validated_count": sum(1 for item in statuses if item.get("status") == "validated"),
        "pending_support_count": sum(1 for item in statuses if item.get("status") == "pending_support_capture"),
        "target_screenshot_ready_count": sum(
            1
            for item in statuses
            if (item.get("capture_readiness") or {}).get("ready_for_reproduction") is True
        ),
        "pending_capture_ready_count": sum(
            1
            for item in statuses
            if item.get("status") == "pending_support_capture"
            and (item.get("capture_readiness") or {}).get("ready_for_reproduction") is True
        ),
        "pending_capture_blocked_count": sum(
            1
            for item in statuses
            if item.get("status") == "pending_support_capture"
            and (item.get("capture_readiness") or {}).get("ready_for_reproduction") is not True
        ),
        "rejected_count": sum(1 for item in statuses if item.get("status") == "rejected"),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    report = {
        "contract_version": "learn_recognition_support_acquisition_status_v1",
        "queue_path": str(queue_path),
        "summary": summary,
        "case_statuses": statuses,
        "interpretation": (
            "offline queue status only; it validates existing support artifacts and does not capture windows, "
            "start models, run grounding, write manifests, or authorize Execute"
        ),
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _status_for_task(task: dict[str, Any], root: Path) -> dict[str, Any]:
    parsed = _parse_validation_command(task)
    case_id = str(task.get("case_id") or parsed.get("case_id") or "")
    support_path = _resolve_path(str(parsed.get("support") or ""), root)
    manifest_path = _resolve_path(str(parsed.get("manifest") or ""), root)
    capture_readiness = _capture_readiness(task, root)
    base = {
        "case_id": case_id,
        "task_type": str(task.get("task_type") or ""),
        "manifest_path": str(manifest_path) if manifest_path else "",
        "support_path": str(support_path) if support_path else "",
        "support_exists": bool(support_path and support_path.exists()),
        "capture_readiness": capture_readiness,
        "bindable": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    if not support_path or not support_path.exists():
        return {
            **base,
            "status": "pending_support_capture",
            "failure_category": "support_artifact_missing",
        }
    if not manifest_path or not manifest_path.exists():
        return {
            **base,
            "status": "rejected",
            "failure_category": "manifest_missing",
        }
    result = bind_support_to_manifest(
        manifest_path=manifest_path,
        case_id=case_id,
        support_path=support_path,
        out_path="__validate_only_no_output__.json",
        validate_only=True,
    )
    if result.get("status") == "validated":
        return {
            **base,
            "status": "validated",
            "bindable": True,
            "validation_result": result,
        }
    return {
        **base,
        "status": "rejected",
        "failure_category": str(result.get("failure_category") or "support_not_bindable"),
        "validation_result": result,
    }


def _capture_readiness(task: dict[str, Any], root: Path) -> dict[str, Any]:
    path = _resolve_path(str(task.get("screenshot_path") or ""), root)
    expected_sha = str(task.get("screenshot_sha256") or "")
    exists = bool(path and path.exists())
    actual_sha = _sha256_file(path) if path and path.exists() else ""
    sha_match = bool(expected_sha) and bool(actual_sha) and actual_sha == expected_sha
    blockers: list[str] = []
    if not exists:
        blockers.append("target_screenshot_missing")
    elif not expected_sha:
        blockers.append("target_screenshot_sha256_missing")
    elif not sha_match:
        blockers.append("target_screenshot_sha256_mismatch")
    return {
        "ready_for_reproduction": not blockers,
        "blockers": blockers,
        "target_screenshot_exists": exists,
        "target_screenshot_sha256_match": sha_match,
    }


def _parse_validation_command(task: dict[str, Any]) -> dict[str, str]:
    commands = task.get("support_validation_commands") if isinstance(task.get("support_validation_commands"), list) else []
    command = str(commands[0] if commands else "")
    return {
        "manifest": _extract_arg(command, "--manifest"),
        "case_id": _extract_arg(command, "--case-id"),
        "support": _extract_arg(command, "--support"),
    }


def _extract_arg(command: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}\s+(.+?)(?=\s+--|$)", command)
    return match.group(1).strip().strip('"') if match else ""


def _resolve_path(value: str, root: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Report status for Learn Recognition support acquisition queue.")
    parser.add_argument("--queue", required=True)
    parser.add_argument("--out")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report_support_acquisition_status(
        queue_path=args.queue,
        out=args.out,
        project_root=args.project_root,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
