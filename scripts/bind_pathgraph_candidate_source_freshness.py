from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review


def bind_candidate_source_freshness(
    *,
    candidate_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    resolved_candidate = _resolve_under_root(candidate_path, root)
    out_path = _resolve_under_root(out_dir, root)
    out_path.mkdir(parents=True, exist_ok=True)

    wrapper = _read_json(resolved_candidate)
    reviewed_path_value = str(wrapper.get("reviewed_template_candidate_path") or "")
    reviewed_path = _resolve_under_root(reviewed_path_value, root)
    reviewed = _read_json(reviewed_path)
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    source_trial_path_value = str(audit.get("source_trial_path") or reviewed.get("source", {}).get("source_trial_path") or "")
    source_trial_path = _resolve_under_root(source_trial_path_value, root)
    source_trial = _read_json(source_trial_path)
    evidence = _source_screenshot_evidence(source_trial, root)

    if evidence.get("status") != "found":
        result = _blocked_result(
            candidate_path=resolved_candidate,
            root=root,
            evidence=evidence,
        )
        _write_result(out_path, result, json_stdout=json_stdout)
        return result

    patched_reviewed = deepcopy(reviewed)
    draft = patched_reviewed.setdefault("draft", {})
    page_details = draft.setdefault("page_details", {})
    screen = page_details.setdefault("screen", {})
    screen["source_image_path"] = evidence["source_image_path"]
    screen["source_image_sha256"] = evidence["source_image_sha256"]
    screen["source_freshness_binding"] = {
        "contract_version": "source_freshness_binding_v1",
        "source_type": "source_trial_screenshot",
        "source_trial_path": _relative_path(source_trial_path, root),
        "bound_at_stage": "pathgraph_candidate_review",
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    patched_reviewed["execute_binding_enabled"] = False
    patched_reviewed["artifact_is_authorization"] = False
    patched_reviewed["counts_as_pure_model_generated"] = False
    patched_audit = patched_reviewed.setdefault("audit", {})
    patched_audit["source_freshness_binding"] = screen["source_freshness_binding"]

    patched_reviewed_path = out_path / "reviewed_template_candidate_with_source_freshness.json"
    patched_reviewed_path.write_text(json.dumps(patched_reviewed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build = build_pathgraph_candidate_from_review(
        patched_reviewed_path,
        {"review_status": "approved_as_assisted_template", "source_after_review": "assisted_generation"},
        project_root=root,
    )
    result = {
        "contract_version": "pathgraph_candidate_source_freshness_bind_result_v1",
        "binding_status": "bound",
        "source_type": "source_trial_screenshot",
        "source_image_path": evidence["source_image_path"],
        "source_image_sha256": evidence["source_image_sha256"],
        "original_candidate_path": _relative_path(resolved_candidate, root),
        "patched_reviewed_template_candidate_path": _relative_path(patched_reviewed_path, root),
        "pathgraph_candidate_path": build["pathgraph_candidate_path"],
        "reviewed_template_candidate_path": build["reviewed_template_candidate_path"],
        "validation_report_path": build["validation_report_path"],
        "source_freshness_summary": build.get("source_freshness_summary") or {},
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "candidate_only": True,
        "no_dispatch": True,
        "interpretation": (
            "binds existing source-trial screenshot evidence into a reviewed candidate copy; "
            "does not capture a new screenshot, execute GUI actions, or authorize Execute"
        ),
    }
    _write_result(out_path, result, json_stdout=json_stdout)
    return result


def _source_screenshot_evidence(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    candidates = [
        _candidate_from_pair(payload.get("screenshot_path"), payload.get("screenshot_sha256")),
        _candidate_from_pair(payload.get("image_path"), payload.get("image_sha256")),
    ]
    observe_bundle = payload.get("observe_bundle") if isinstance(payload.get("observe_bundle"), dict) else {}
    candidates.extend(
        [
            _candidate_from_pair(observe_bundle.get("screenshot_path"), observe_bundle.get("screenshot_sha256")),
            _candidate_from_pair(observe_bundle.get("image_path"), observe_bundle.get("image_sha256")),
            _candidate_from_pair(observe_bundle.get("source_image_path"), observe_bundle.get("source_image_sha256")),
        ]
    )
    draft = payload.get("learning_draft") if isinstance(payload.get("learning_draft"), dict) else {}
    if not draft and isinstance(payload.get("best_learning_draft"), dict):
        draft = payload.get("best_learning_draft") or {}
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    candidates.extend(
        [
            _candidate_from_pair(screen.get("source_image_path"), screen.get("source_image_sha256")),
            _candidate_from_pair(screen.get("screenshot_path"), screen.get("screenshot_sha256")),
            _candidate_from_pair(screen.get("image_path"), screen.get("image_sha256")),
        ]
    )
    for candidate in candidates:
        path_text = str(candidate.get("path") or "").strip()
        if not path_text:
            continue
        path = _resolve_under_root(path_text, root)
        if not path.exists() or not path.is_file():
            return {
                "status": "blocked",
                "block_reason": "source_screenshot_file_missing",
                "source_image_path": _relative_path(path, root),
                "expected_sha256": str(candidate.get("sha256") or "").lower(),
            }
        actual_sha256 = _sha256_file(path)
        expected_sha256 = str(candidate.get("sha256") or "").strip().lower()
        if expected_sha256 and expected_sha256 != actual_sha256:
            return {
                "status": "blocked",
                "block_reason": "source_screenshot_sha256_mismatch",
                "source_image_path": _relative_path(path, root),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            }
        return {
            "status": "found",
            "source_image_path": _relative_path(path, root),
            "source_image_sha256": actual_sha256,
        }
    return {"status": "blocked", "block_reason": "source_screenshot_not_found"}


def _candidate_from_pair(path_value: Any, sha_value: Any) -> dict[str, str]:
    return {"path": str(path_value or "").strip(), "sha256": str(sha_value or "").strip().lower()}


def _blocked_result(*, candidate_path: Path, root: Path, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "pathgraph_candidate_source_freshness_bind_result_v1",
        "binding_status": "blocked",
        "block_reason": str(evidence.get("block_reason") or "source_screenshot_not_found"),
        "source_image_path": str(evidence.get("source_image_path") or ""),
        "expected_sha256": str(evidence.get("expected_sha256") or ""),
        "actual_sha256": str(evidence.get("actual_sha256") or ""),
        "pathgraph_candidate_path": _relative_path(candidate_path, root),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "candidate_only": True,
        "no_dispatch": True,
    }


def _write_result(out_dir: Path, result: dict[str, Any], *, json_stdout: bool) -> None:
    report_path = out_dir / "source_freshness_bind_result.json"
    result["report_path"] = str(report_path)
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def _resolve_under_root(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind existing source-trial screenshot freshness into a candidate copy.")
    parser.add_argument("--candidate", required=True, help="Path to pathgraph_candidate.json.")
    parser.add_argument("--out", required=True, help="Output directory for patched reviewed candidate and report.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    bind_candidate_source_freshness(
        candidate_path=args.candidate,
        out_dir=args.out,
        project_root=args.project_root,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
