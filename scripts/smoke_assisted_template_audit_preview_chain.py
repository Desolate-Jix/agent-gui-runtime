from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.assisted_template_review import (
    create_assisted_template_asset_candidate,
    create_assisted_template_audited_promotion_request,
    create_assisted_template_graph_draft,
    create_assisted_template_promotion_preflight,
    save_assisted_template_review_decisions,
)

def run_audit_preview_chain_smoke(
    *,
    package_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_package = _resolve_under_root(package_path, root)
    source_dir = source_package.parent
    source_before = _artifact_hashes(source_dir)
    out_path = _resolve_output_dir(out_dir, root)
    copied_review_dir = out_path / "assisted_template_review_copy"
    if copied_review_dir.exists():
        shutil.rmtree(copied_review_dir)
    shutil.copytree(source_dir, copied_review_dir)
    copied_before = _artifact_hashes(copied_review_dir)
    copied_package = copied_review_dir / source_package.name

    simulation = _read_json(copied_review_dir / "assisted_template_acceptance_simulation.json")
    suggestions = _read_json(copied_review_dir / "assisted_template_acceptance_suggestions.json")
    decisions = _decisions_from_simulation(simulation=simulation, suggestions=suggestions)
    review_record = save_assisted_template_review_decisions(
        _relative_path(copied_package, root),
        decisions,
        overall_decision="accepted_for_assisted_template_review" if decisions else "needs_changes",
        reviewer_note="offline smoke from acceptance simulation; not source human review",
        project_root=root,
    )
    asset = create_assisted_template_asset_candidate(_relative_path(copied_package, root), project_root=root)
    graph = create_assisted_template_graph_draft(asset["asset_candidate_path"], project_root=root)
    preflight = create_assisted_template_promotion_preflight(_relative_path(copied_package, root), project_root=root)
    audited_request: dict[str, Any] = {}
    if preflight.get("preflight_status") == "ready_for_audited_runtime_promotion_review":
        audited_request = create_assisted_template_audited_promotion_request(_relative_path(copied_package, root), project_root=root)

    source_after = _artifact_hashes(source_dir)
    copied_after = _artifact_hashes(copied_review_dir)
    copied_writes = [
        _relative_path(path, root)
        for path in sorted(copied_review_dir.glob("*.json"))
        if path.name not in source_before
    ]
    report = {
        "contract_version": "assisted_template_audit_preview_chain_smoke_v1",
        "smoke_status": "passed" if audited_request else "blocked",
        "created_at": datetime.now().isoformat(),
        "source_package_path": _relative_path(source_package, root),
        "copied_package_path": _relative_path(copied_package, root),
        "source_package_unchanged": source_before == source_after,
        "source_artifact_writes": _source_writes(source_before, source_after),
        "copied_artifact_writes": copied_writes,
        "copied_artifact_changes": _source_writes(copied_before, copied_after),
        "selected_suggestion_ids": simulation.get("selected_suggestion_ids") or [],
        "review_record": review_record,
        "asset_candidate": asset,
        "graph_draft": graph,
        "preflight": preflight,
        "audited_request": audited_request,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "interpretation": (
            "offline smoke on a copied assisted-template review directory only; does not write source review decisions, "
            "promote Runtime PathGraph, enable Execute, dispatch clicks, fill forms, or submit"
        ),
    }
    report_path = out_path / "assisted_template_audit_preview_chain_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = _relative_path(report_path, root)
    return report


def _decisions_from_simulation(*, simulation: dict[str, Any], suggestions: dict[str, Any]) -> list[dict[str, Any]]:
    selected = {str(item) for item in simulation.get("selected_suggestion_ids") or [] if str(item)}
    decisions: dict[tuple[str, str], dict[str, Any]] = {}
    for suggestion in _list_of_dicts(suggestions.get("suggestions")):
        suggestion_id = str(suggestion.get("suggestion_id") or "")
        if selected and suggestion_id not in selected:
            continue
        note = str(suggestion.get("recommended_note") or "accepted by offline simulation smoke")
        overrides = _safe_overrides(suggestion.get("overrides"))
        for item in _list_of_dicts(suggestion.get("items")):
            item_type = str(item.get("item_type") or "").strip()
            item_id = str(item.get("item_id") or "").strip()
            if not item_type or not item_id:
                continue
            decision: dict[str, Any] = {
                "item_type": item_type,
                "item_id": item_id,
                "decision": "accepted",
                "note": note,
            }
            if item_type == "action" and overrides:
                decision["overrides"] = overrides
            decisions[(item_type, item_id)] = decision
    return [decisions[key] for key in sorted(decisions)]


def _safe_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: str(value.get(key) or "").strip()
        for key in ("label", "semantic_action", "target_entity")
        if str(value.get(key) or "").strip()
    }


def _artifact_hashes(path: Path) -> dict[str, str]:
    return {
        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
        for item in sorted(path.glob("*.json"))
        if item.is_file()
    }


def _source_writes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    names = sorted(set(before) | set(after))
    return [name for name in names if before.get(name) != after.get(name)]


def _resolve_under_root(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("path must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _resolve_output_dir(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed = (root / "logs").resolve()
    if not (path == allowed or allowed in path.parents):
        raise ValueError("out_dir must be under logs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a copied assisted-template audit-preview chain smoke.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_audit_preview_chain_smoke(package_path=args.package, out_dir=args.out)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['smoke_status']}: {result['report_path']}")
    return 0 if result.get("smoke_status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
