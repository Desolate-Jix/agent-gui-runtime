from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from contextlib import contextmanager

import pytest


def _selection_trial(tmp_path):
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from tests.test_learning_selection_roundtrip import _payload

    _, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(
        project_root=tmp_path,
        payload=payload,
        response=run_hybrid_selection_task(payload),
    )
    return trial, load_learning_draft_review(trial, project_root=tmp_path)


def _decision(candidate_id: str, decision_id: str) -> dict:
    return {
        "decision_id": decision_id,
        "decision_type": "semantic_edit",
        "candidate_id": candidate_id,
        "semantics": {
            "role": "button",
            "label": "Quick Apply",
            "description": "human supplied",
        },
    }


def test_selection_save_requires_immutable_expected_projection_ref(tmp_path):
    from app.learn.draft_review import save_reviewed_template_candidate

    trial, loaded = _selection_trial(tmp_path)
    candidate = next(
        item for item in loaded["hybrid_review_projection"]["candidates"]
        if item["selection"] is not None
    )

    with pytest.raises(ValueError, match="expected_hybrid_review_projection_ref"):
        save_reviewed_template_candidate(
            trial,
            {"hybrid_review_decisions": [_decision(candidate["candidate_id"], "decision/integrity-missing-ref")]},
            project_root=tmp_path,
        )


def test_selection_save_rejects_stale_client_without_losing_head_ledger(tmp_path):
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate

    trial, loaded = _selection_trial(tmp_path)
    candidate = next(item for item in loaded["hybrid_review_projection"]["candidates"] if item["selection"] is not None)
    expected = loaded["hybrid_review_projection_ref"]
    first = _decision(candidate["candidate_id"], "decision/integrity-a")
    stale = _decision(candidate["candidate_id"], "decision/integrity-b")

    first_saved = save_reviewed_template_candidate(
        trial,
        {"expected_hybrid_review_projection_ref": expected, "hybrid_review_decisions": [first]},
        project_root=tmp_path,
    )
    with pytest.raises(ValueError, match="expected_hybrid_review_projection_ref conflict"):
        save_reviewed_template_candidate(
            trial,
            {"expected_hybrid_review_projection_ref": expected, "hybrid_review_decisions": [stale]},
            project_root=tmp_path,
        )

    saved_path = tmp_path / first_saved["reviewed_template_candidate_path"]
    after = load_learning_draft_review(saved_path, project_root=tmp_path)
    assert [item["decision_id"] for item in after["hybrid_review_projection"]["review_decisions"]] == [first["decision_id"]]

    repeated = save_reviewed_template_candidate(
        saved_path,
        {"expected_hybrid_review_projection_ref": after["hybrid_review_projection_ref"], "hybrid_review_decisions": after["hybrid_review_projection"]["review_decisions"]},
        project_root=tmp_path,
    )
    assert repeated["reviewed_template_candidate_path"] == first_saved["reviewed_template_candidate_path"]
    reloaded = load_learning_draft_review(saved_path, project_root=tmp_path)
    assert [item["decision_id"] for item in reloaded["hybrid_review_projection"]["review_decisions"]] == [first["decision_id"]]


def test_selection_lock_timeout_does_not_publish_candidate(tmp_path, monkeypatch):
    import app.learn.draft_review as draft_review

    trial, loaded = _selection_trial(tmp_path)
    candidate = next(item for item in loaded["hybrid_review_projection"]["candidates"] if item["selection"] is not None)

    @contextmanager
    def timed_out_lock(_directory):
        raise TimeoutError("selection save lock timed out")
        yield

    monkeypatch.setattr(draft_review, "selection_save_lock", timed_out_lock)
    with pytest.raises(TimeoutError, match="lock timed out"):
        draft_review.save_reviewed_template_candidate(
            trial,
            {"expected_hybrid_review_projection_ref": loaded["hybrid_review_projection_ref"], "hybrid_review_decisions": [_decision(candidate["candidate_id"], "decision/integrity-timeout")]},
            project_root=tmp_path,
        )
    assert not list((tmp_path / "artifacts" / "learning-draft-review").rglob("reviewed_template_candidate.json"))


def test_selection_save_serializes_subprocess_writers(tmp_path):
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate

    trial, loaded = _selection_trial(tmp_path)
    candidate = next(item for item in loaded["hybrid_review_projection"]["candidates"] if item["selection"] is not None)
    initial = save_reviewed_template_candidate(
        trial,
        {"expected_hybrid_review_projection_ref": loaded["hybrid_review_projection_ref"], "hybrid_review_decisions": [_decision(candidate["candidate_id"], "decision/integrity-base")]},
        project_root=tmp_path,
    )
    head = load_learning_draft_review(tmp_path / initial["reviewed_template_candidate_path"], project_root=tmp_path)
    script = """
import json, sys
from app.learn.draft_review import save_reviewed_template_candidate
root, trial, expected, candidate_id, decision_id = sys.argv[1:]
try:
    saved = save_reviewed_template_candidate(trial, {\"expected_hybrid_review_projection_ref\": json.loads(expected), \"hybrid_review_decisions\": [{\"decision_id\": decision_id, \"decision_type\": \"semantic_edit\", \"candidate_id\": candidate_id, \"semantics\": {\"role\": \"button\", \"label\": \"Quick Apply\", \"description\": \"human supplied\"}}]}, project_root=root)
    print(json.dumps({\"status\": \"saved\", \"path\": saved[\"reviewed_template_candidate_path\"]}))
except ValueError as error:
    print(json.dumps({\"status\": \"conflict\", \"error\": str(error)}))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    args = [str(tmp_path), trial, json.dumps(head["hybrid_review_projection_ref"]), candidate["candidate_id"]]
    workers = [
        subprocess.Popen([sys.executable, "-c", script, *args, decision_id], cwd=tmp_path, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for decision_id in ("decision/integrity-process-b", "decision/integrity-process-c")
    ]
    output = [worker.communicate(timeout=30) for worker in workers]
    assert all(not stderr for _, stderr in output), output
    outcomes = [json.loads(stdout) for stdout, _ in output]
    assert sorted(item["status"] for item in outcomes) == ["conflict", "saved"]
    final = load_learning_draft_review(tmp_path / initial["reviewed_template_candidate_path"], project_root=tmp_path)
    ids = [item["decision_id"] for item in final["hybrid_review_projection"]["review_decisions"]]
    assert ids[0] == "decision/integrity-base"
    assert len(ids) == 2
    assert set(ids[1:]) <= {"decision/integrity-process-b", "decision/integrity-process-c"}
