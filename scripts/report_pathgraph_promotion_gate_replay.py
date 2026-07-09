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


def build_promotion_gate_replay_report(
    *,
    candidate_paths: list[str | Path],
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.mkdir(parents=True, exist_ok=True)

    cases = [_candidate_gate_case(path, root=root) for path in candidate_paths]
    report_path = out_path / "pathgraph_promotion_gate_replay_report.json"
    report = {
        "contract_version": "pathgraph_promotion_gate_replay_report_v1",
        "summary": _summary(cases),
        "cases": cases,
        "interpretation": (
            "offline promotion-review gate replay only; this report checks candidate evidence and blockers, "
            "but does not authorize Execute, clicks, filling, final submit, or Runtime PathGraph promotion"
        ),
        "safety": {
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [item for item in cases if item.get("gate_status") == "passed_for_human_promotion_review"]
    blocked = [item for item in cases if item.get("gate_status") == "blocked_from_promotion_review"]
    non_demo = [item for item in cases if item.get("fixture_kind") == "non_demo_candidate"]
    demo = [item for item in cases if item.get("fixture_kind") == "demo_candidate"]
    return {
        "candidate_count": len(cases),
        "non_demo_candidate_count": len(non_demo),
        "demo_candidate_count": len(demo),
        "passed_for_human_promotion_review_count": len(passed),
        "non_demo_passed_for_human_promotion_review_count": sum(
            1 for item in passed if item.get("fixture_kind") == "non_demo_candidate"
        ),
        "demo_passed_for_human_promotion_review_count": sum(
            1 for item in passed if item.get("fixture_kind") == "demo_candidate"
        ),
        "blocked_from_promotion_review_count": len(blocked),
        "non_demo_blocked_from_promotion_review_count": sum(
            1 for item in blocked if item.get("fixture_kind") == "non_demo_candidate"
        ),
        "demo_blocked_from_promotion_review_count": sum(
            1 for item in blocked if item.get("fixture_kind") == "demo_candidate"
        ),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _candidate_gate_case(path_value: str | Path, *, root: Path) -> dict[str, Any]:
    candidate_path = Path(path_value)
    if not candidate_path.is_absolute():
        candidate_path = root / candidate_path
    review = load_learning_draft_review(candidate_path, project_root=root)
    candidate_review = review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
    readiness = (
        candidate_review.get("pathgraph_readiness_summary")
        if isinstance(candidate_review.get("pathgraph_readiness_summary"), dict)
        else {}
    )
    gate = readiness.get("promotion_review_gate") if isinstance(readiness.get("promotion_review_gate"), dict) else {}
    wrapper = _read_json(candidate_path)
    reviewed_path = str(wrapper.get("reviewed_template_candidate_path") or "")
    reviewed = _read_json(_resolve_under_root(reviewed_path, root)) if reviewed_path else {}
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    source_trial_path = str(audit.get("source_trial_path") or "")
    freshness = (
        wrapper.get("source_freshness_summary")
        if isinstance(wrapper.get("source_freshness_summary"), dict)
        else {}
    )
    return {
        "case_id": _case_id(source_trial_path=source_trial_path, candidate_path=candidate_path),
        "candidate_path": _relative_path(candidate_path, root),
        "reviewed_template_candidate_path": reviewed_path,
        "source_trial_path": source_trial_path,
        "fixture_kind": _fixture_kind(source_trial_path),
        "readiness_status": str(readiness.get("readiness_status") or "not_evaluated"),
        "promotion_review_blockers": readiness.get("promotion_review_blockers") if isinstance(readiness.get("promotion_review_blockers"), list) else [],
        "gate_status": str(gate.get("gate_status") or "not_evaluated"),
        "failed_check_ids": gate.get("failed_check_ids") if isinstance(gate.get("failed_check_ids"), list) else [],
        "checks": gate.get("checks") if isinstance(gate.get("checks"), list) else [],
        "source_freshness_summary": freshness,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "candidate_only": True,
        "no_dispatch": True,
    }


def _case_id(*, source_trial_path: str, candidate_path: Path) -> str:
    if source_trial_path:
        parent = Path(source_trial_path).parent.name
        if parent:
            return parent
    parent = candidate_path.parent.parent.name
    return parent or candidate_path.stem


def _fixture_kind(source_trial_path: str) -> str:
    return "demo_candidate" if "learning-draft-freshness-demo" in source_trial_path.replace("\\", "/") else "non_demo_candidate"


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


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_paths_from_args(args: argparse.Namespace, root: Path) -> list[Path]:
    paths = [Path(item) for item in args.candidate]
    for pattern in args.candidate_glob:
        paths.extend(root.glob(pattern))
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay PathGraph candidate promotion-review gates without dispatch.")
    parser.add_argument("--candidate", action="append", default=[], help="Path to a pathgraph_candidate.json file.")
    parser.add_argument("--candidate-glob", action="append", default=[], help="Project-root relative glob for candidates.")
    parser.add_argument("--out", required=True, help="Output directory for the replay report.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    candidates = _candidate_paths_from_args(args, root)
    build_promotion_gate_replay_report(
        candidate_paths=candidates,
        out_dir=args.out,
        project_root=root,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
