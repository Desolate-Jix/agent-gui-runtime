from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_learning_draft_service_runs_load_save_reload_and_aggregation_without_panel(
    tmp_path: Path,
) -> None:
    script = r"""
import builtins
import json
from pathlib import Path
import sys

original_import = builtins.__import__
def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    candidates = [name, *(name + "." + item for item in (fromlist or ()))]
    for candidate in candidates:
        if candidate in {"app.main", "app.api.panel", "app.web_panel"} or candidate.startswith("app.web_panel."):
            raise AssertionError("legacy import: " + candidate)
    return original_import(name, globals, locals, fromlist, level)
builtins.__import__ = guarded_import

from app.learn.learning_draft_review_service import (
    authoritative_hybrid_workflow_expectations,
    load_interface_workflow_review_transaction,
    load_learning_draft_review_transaction,
    save_learning_draft_review_transaction,
)
from app.learn.workflow_store import LearningWorkflowRunStore
from tests.test_learning_selection_public_flow import selection_input

root = Path.cwd()
workflow_store = LearningWorkflowRunStore(state_path=None)
path, _ = selection_input(root)
loaded = load_learning_draft_review_transaction(
    source_path=path.relative_to(root).as_posix(),
    workflow_run_id=None,
    discover_related_sidecars=False,
    project_root=root,
    workflow_store=workflow_store,
)
assert loaded["prepared_from_selection_replay"] is True
projection = loaded["hybrid_review_projection"]
selected = next(item for item in projection["candidates"] if item["selection"] is not None)
decisions = [
    {"decision_id": "decision/service-rebox", "decision_type": "rebox", "candidate_id": selected["candidate_id"], "bbox": [41, 21, 119, 51]},
    {"decision_id": "decision/service-semantic", "decision_type": "semantic_edit", "candidate_id": selected["candidate_id"], "semantics": {"role": "button", "label": "Quick Apply", "description": "Synthetic service ownership fixture."}},
]
saved = save_learning_draft_review_transaction(
    source_path=loaded["trial_path"],
    review_patch={"hybrid_review_decisions": decisions, "expected_hybrid_review_projection_ref": loaded["hybrid_review_projection_ref"], "_server_hybrid_expectations": {"forged": True}},
    project_root=root,
    workflow_store=workflow_store,
)
reloaded = load_learning_draft_review_transaction(
    source_path=saved["reviewed_template_candidate_path"],
    workflow_run_id=None,
    discover_related_sidecars=False,
    project_root=root,
    workflow_store=workflow_store,
)
assert len(reloaded["hybrid_review_projection"]["review_decisions"]) == 2
aggregate = load_interface_workflow_review_transaction(
    draft_source_paths=[loaded["trial_path"], "artifacts/missing-review.json"],
    workflow_run_ids_by_source={},
    discover_related_sidecars=False,
    goal="Synthetic review source ownership check",
    application_identity={"url": "https://example.test"},
    project_root=root,
    workflow_store=workflow_store,
)
assert len(aggregate["invalid_sources"]) == 1
assert aggregate["invalid_sources"][0]["failure_category"] == "invalid_review_source"
assert authoritative_hybrid_workflow_expectations(
    "missing-run", source_path=loaded["trial_path"], project_root=root, workflow_store=workflow_store,
) == (None, None, None)
assert not {"app.main", "app.api.panel", "app.web_panel"} & sys.modules.keys()
print(json.dumps({"loaded": True, "saved": True, "reloaded": True, "aggregated_invalid": True, "unbound_fail_closed": True, "legacy_loaded": False}))
"""
    environment = dict(
        os.environ,
        PYTHONPATH=str(ROOT),
        PYTHONUTF8="1",
        PYTHONIOENCODING="utf-8",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
        QT_QPA_PLATFORM="offscreen",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1]) == {
        "loaded": True, "saved": True, "reloaded": True,
        "aggregated_invalid": True, "unbound_fail_closed": True,
        "legacy_loaded": False,
    }
