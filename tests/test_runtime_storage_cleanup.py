from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.runtime_storage_cleanup import apply_cleanup_plan, build_cleanup_plan


NOW = datetime(2026, 7, 27, tzinfo=timezone.utc)


def _write(path: Path, text: str = "artifact") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _age(path: Path, *, days: int) -> None:
    timestamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_plan_removes_only_old_unreferenced_runtime_outputs(tmp_path: Path) -> None:
    stale_trace = _write(tmp_path / "logs" / "traces" / "observe" / "stale.json")
    current_trace = _write(tmp_path / "logs" / "traces" / "observe" / "current.json")
    learning_run = _write(
        tmp_path / "artifacts" / "learning-runs" / "reviewed" / "trial_result.json",
        json.dumps({"overlay_path": "artifacts/review-overlays/learning-run.png"}),
    )
    stale_overlay = _write(tmp_path / "artifacts" / "review-overlays" / "stale.png")
    learning_run_overlay = _write(
        tmp_path / "artifacts" / "review-overlays" / "learning-run.png"
    )
    referenced_overlay = _write(tmp_path / "artifacts" / "review-overlays" / "referenced.png")
    stale_tmp = _write(tmp_path / "logs" / "tmp" / "stale.txt")
    model_file = _write(tmp_path / "models" / "model.gguf")
    for path in (
        stale_trace,
        learning_run,
        stale_overlay,
        learning_run_overlay,
        referenced_overlay,
        stale_tmp,
        model_file,
    ):
        _age(path, days=30)
    _age(current_trace, days=1)

    manifest = {
        "screenshot_path": "artifacts/review-overlays/referenced.png",
    }
    _write(
        tmp_path / "artifacts" / "benchmarks" / "golden.json",
        json.dumps(manifest),
    )

    plan = build_cleanup_plan(
        root=tmp_path,
        now=NOW,
        older_than_days=14,
        keep_latest_per_directory=0,
    )

    candidates = {item["relative_path"] for item in plan["delete_candidates"]}
    assert candidates == {
        "artifacts/review-overlays/stale.png",
        "logs/tmp/stale.txt",
    }
    assert "artifacts/review-overlays/referenced.png" in plan["protected_paths"]
    assert "artifacts/review-overlays/learning-run.png" in plan["protected_paths"]
    assert "models/model.gguf" not in candidates
    assert "logs/traces/observe/stale.json" not in candidates
    assert "logs/traces/observe/current.json" not in candidates
    assert "artifacts/learning-runs/reviewed/trial_result.json" not in candidates
    assert "logs/traces" not in plan["target_roots"]
    assert "artifacts/learning-runs" not in plan["target_roots"]


def test_cleanup_plan_protects_latest_file_per_directory(tmp_path: Path) -> None:
    older = _write(tmp_path / "artifacts" / "review-overlays" / "actions" / "older.png")
    latest = _write(tmp_path / "artifacts" / "review-overlays" / "actions" / "latest.png")
    _age(older, days=40)
    _age(latest, days=30)

    plan = build_cleanup_plan(
        root=tmp_path,
        now=NOW,
        older_than_days=14,
        keep_latest_per_directory=1,
    )

    candidates = {item["relative_path"] for item in plan["delete_candidates"]}
    assert candidates == {"artifacts/review-overlays/actions/older.png"}
    assert "artifacts/review-overlays/actions/latest.png" in plan["protected_paths"]


def test_learning_run_protects_its_old_evidence(tmp_path: Path) -> None:
    overlay = _write(tmp_path / "artifacts" / "review-overlays" / "evidence.png")
    learning_run = _write(
        tmp_path / "artifacts" / "learning-runs" / "reviewed" / "trial_result.json",
        json.dumps({"overlay_path": "artifacts/review-overlays/evidence.png"}),
    )
    _age(overlay, days=40)
    _age(learning_run, days=40)

    plan = build_cleanup_plan(
        root=tmp_path,
        now=NOW,
        older_than_days=14,
        keep_latest_per_directory=1,
    )

    candidates = {item["relative_path"] for item in plan["delete_candidates"]}
    assert "artifacts/review-overlays/evidence.png" not in candidates
    assert "artifacts/review-overlays/evidence.png" in plan["protected_paths"]


def test_apply_cleanup_plan_preserves_references_and_writes_report(tmp_path: Path) -> None:
    stale = _write(tmp_path / "logs" / "tmp" / "old" / "stale.txt")
    protected = _write(tmp_path / "artifacts" / "review-overlays" / "kept.png")
    _age(stale, days=40)
    _age(protected, days=40)
    _write(
        tmp_path / "CURRENT_STATE.md",
        "Evidence: `artifacts/review-overlays/kept.png`.",
    )

    plan = build_cleanup_plan(
        root=tmp_path,
        now=NOW,
        older_than_days=14,
        keep_latest_per_directory=0,
    )
    report_path = tmp_path / "logs" / "cleanup" / "report.json"
    report = apply_cleanup_plan(plan, report_path=report_path)

    assert report["status"] == "applied"
    assert report["deleted_files"] == 1
    assert report["removed_directories"] >= 1
    assert not stale.exists()
    assert not stale.parent.exists()
    assert protected.exists()
    assert report_path.exists()


def test_cleanup_rejects_trace_and_learning_asset_targets(tmp_path: Path) -> None:
    for protected_root in ("logs/traces", "artifacts/learning-runs"):
        with pytest.raises(ValueError, match="protected cleanup root"):
            build_cleanup_plan(
                root=tmp_path,
                now=NOW,
                older_than_days=14,
                keep_latest_per_directory=0,
                target_roots=(protected_root,),
            )


def test_dry_run_never_deletes_files(tmp_path: Path) -> None:
    stale = _write(tmp_path / "logs" / "tmp" / "stale.txt")
    _age(stale, days=40)
    plan = build_cleanup_plan(
        root=tmp_path,
        now=NOW,
        older_than_days=14,
        keep_latest_per_directory=0,
    )

    assert plan["mode"] == "dry_run"
    assert stale.exists()
