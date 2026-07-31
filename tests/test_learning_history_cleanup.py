from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.learn.history_cleanup import (
    apply_application_history_cleanup_plan,
    build_application_history_cleanup_plan,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_text(path: Path, text: str = "evidence") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_history_roots(root: Path) -> None:
    _write_json(
        root / "artifacts/interface-assets/web_nz.seek.com/registry.json",
        {
            "application_identity_key": "web:nz.seek.com",
            "interface_ids": ["seek_list"],
        },
    )
    _write_json(
        root / "artifacts/interface-assets/web_python.org/registry.json",
        {
            "application_identity_key": "web:python.org",
            "interface_ids": ["python_home"],
        },
    )
    _write_text(
        root
        / "artifacts/interface-assets/web_nz.seek.com/interfaces/seek_list/interface.json"
    )
    _write_text(
        root
        / "artifacts/interface-assets/web_python.org/interfaces/python_home/interface.json"
    )

    _write_json(
        root / "artifacts/interface-workflow-reviews/registry.json",
        {
            "contract_version": "interface_workflow_library_registry_v1",
            "registry_revision": 4,
            "applications": {
                "web:nz.seek.com": {"workflow_ids": ["seek_flow"]},
                "web:python.org": {"workflow_ids": ["python_flow"]},
            },
            "workflows": {
                "seek_flow": {
                    "path": str(
                        root
                        / "artifacts/interface-workflow-reviews/seek_flow/reviewed_workflow.json"
                    ),
                    "application_identity_key": "web:nz.seek.com",
                },
                "python_flow": {
                    "path": str(
                        root
                        / "artifacts/interface-workflow-reviews/python_flow/reviewed_workflow.json"
                    ),
                    "application_identity_key": "web:python.org",
                },
            },
        },
    )
    _write_json(
        root / "artifacts/interface-workflow-reviews/seek_flow/reviewed_workflow.json",
        {"workflow": {"workflow_id": "seek_flow"}},
    )
    _write_json(
        root / "artifacts/interface-workflow-reviews/python_flow/reviewed_workflow.json",
        {"workflow": {"workflow_id": "python_flow"}},
    )

    seek_sha = "a" * 64
    python_sha = "b" * 64
    _write_json(
        root / "artifacts/agent-memory/registry.json",
        {
            "contract_version": "reviewed_interface_memory_registry_v1",
            "registry_revision": 2,
            "active_by_interface": {
                "seek_results_current": seek_sha,
                "python_home_current": python_sha,
            },
            "objects": {
                seek_sha: {
                    "interface_id": "seek_results_current",
                    "object_path": f"artifacts/agent-memory/objects/{seek_sha}.json",
                    "source_candidate_path": (
                        "artifacts/manual-runtime-validation/seek_candidate.json"
                    ),
                },
                python_sha: {
                    "interface_id": "python_home_current",
                    "object_path": f"artifacts/agent-memory/objects/{python_sha}.json",
                    "source_candidate_path": (
                        "artifacts/manual-runtime-validation/python_candidate.json"
                    ),
                },
            },
            "events": [
                {"interface_id": "seek_results_current", "object_sha256": seek_sha},
                {"interface_id": "python_home_current", "object_sha256": python_sha},
            ],
        },
    )
    _write_json(root / f"artifacts/agent-memory/objects/{seek_sha}.json", {})
    _write_json(root / f"artifacts/agent-memory/objects/{python_sha}.json", {})
    _write_json(
        root / "artifacts/manual-runtime-validation/seek_candidate.json",
        {"surface": "seek"},
    )
    _write_json(
        root / "artifacts/manual-runtime-validation/python_candidate.json",
        {"surface": "python"},
    )
    _write_json(
        root
        / "artifacts/agent-memory/execution-feedback/seek_results_current/feedback.json",
        {},
    )
    _write_json(
        root
        / "artifacts/agent-memory/execution-feedback/python_home_current/feedback.json",
        {},
    )

    _write_json(
        root / "artifacts/learning-runs/panel_20260728_seek_web/trial_result.json",
        {},
    )
    _write_json(
        root / "artifacts/learning-runs/panel_20260728_python_org/trial_result.json",
        {},
    )
    _write_json(
        root / "artifacts/learning-correction-memory/registry.json",
        {"rules": [{"rule_id": "employment_workflow"}]},
    )


def test_cleanup_plan_targets_seek_history_and_preserves_other_assets(
    tmp_path: Path,
) -> None:
    _seed_history_roots(tmp_path)

    plan = build_application_history_cleanup_plan(
        project_root=tmp_path,
        application_identity_keys={"web:nz.seek.com", "web:seek.co.nz"},
        interface_id_prefixes=("seek_",),
        learning_run_name_tokens=("seek", "choose_documents"),
    )

    delete_paths = set(plan["delete_paths"])
    assert "artifacts/interface-assets/web_nz.seek.com" in delete_paths
    assert "artifacts/interface-workflow-reviews/seek_flow" in delete_paths
    assert "artifacts/learning-runs/panel_20260728_seek_web" in delete_paths
    assert (
        "artifacts/agent-memory/execution-feedback/seek_results_current"
        in delete_paths
    )
    assert "artifacts/interface-assets/web_python.org" not in delete_paths
    assert "artifacts/interface-workflow-reviews/python_flow" not in delete_paths
    assert "artifacts/learning-runs/panel_20260728_python_org" not in delete_paths
    assert plan["protected_roots"] == [
        "artifacts/benchmarks",
        "artifacts/learning-correction-memory",
        "tests/fixtures",
    ]
    assert set(plan["removed_interface_ids"]) == {"seek_results_current"}
    assert set(plan["removed_workflow_ids"]) == {"seek_flow"}


def test_apply_cleanup_updates_registries_and_keeps_class_rules(
    tmp_path: Path,
) -> None:
    _seed_history_roots(tmp_path)
    rules_path = (
        tmp_path / "artifacts/learning-correction-memory/registry.json"
    )
    rules_before = rules_path.read_bytes()
    plan = build_application_history_cleanup_plan(
        project_root=tmp_path,
        application_identity_keys={"web:nz.seek.com", "web:seek.co.nz"},
        interface_id_prefixes=("seek_",),
        learning_run_name_tokens=("seek", "choose_documents"),
    )

    report = apply_application_history_cleanup_plan(
        plan,
        report_path=tmp_path / "artifacts/cleanup-audits/seek-history.json",
    )

    assert report["status"] == "applied"
    assert not (tmp_path / "artifacts/interface-assets/web_nz.seek.com").exists()
    assert (tmp_path / "artifacts/interface-assets/web_python.org").is_dir()
    assert not (
        tmp_path / "artifacts/learning-runs/panel_20260728_seek_web"
    ).exists()
    assert (
        tmp_path / "artifacts/learning-runs/panel_20260728_python_org"
    ).is_dir()
    workflow_registry = json.loads(
        (
            tmp_path / "artifacts/interface-workflow-reviews/registry.json"
        ).read_text(encoding="utf-8")
    )
    assert set(workflow_registry["applications"]) == {"web:python.org"}
    assert set(workflow_registry["workflows"]) == {"python_flow"}
    memory_registry = json.loads(
        (tmp_path / "artifacts/agent-memory/registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(memory_registry["active_by_interface"]) == {"python_home_current"}
    assert {item["interface_id"] for item in memory_registry["events"]} == {
        "python_home_current"
    }
    assert rules_path.read_bytes() == rules_before


def test_apply_cleanup_rejects_paths_outside_project_root(tmp_path: Path) -> None:
    _seed_history_roots(tmp_path)
    plan = build_application_history_cleanup_plan(
        project_root=tmp_path,
        application_identity_keys={"web:nz.seek.com"},
        interface_id_prefixes=("seek_",),
        learning_run_name_tokens=("seek",),
    )
    plan["delete_paths"].append("../outside")

    with pytest.raises(ValueError, match="outside project root"):
        apply_application_history_cleanup_plan(plan)


def test_cleanup_script_runs_directly_from_repository_root(tmp_path: Path) -> None:
    _seed_history_roots(tmp_path)
    project_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts/cleanup_learned_application_history.py"),
            "--project-root",
            str(tmp_path),
            "--application-key",
            "web:nz.seek.com",
            "--interface-prefix",
            "seek_",
            "--run-name-token",
            "seek",
            "--json",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["mode"] == "dry_run"
