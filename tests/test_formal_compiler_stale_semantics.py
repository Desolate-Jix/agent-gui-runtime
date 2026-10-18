from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from app.desktop_review import exact_review
from test_formal_graph_source_ownership import _facade, _batch


def _fresh_compilable_review(tmp_path):
    batch = _batch()
    batch["interfaces"] = batch["interfaces"][:1]
    batch["steps"][0]["arrival_state"] = "interface-a"
    batch["relationships"][0]["to_interface_id"] = "interface-a"
    facade, store, _, root = _facade(tmp_path, batch)
    try:
        workspace = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        facade.save_revision(workspace["task_id"], workspace["batch_id"], 0, workspace["batch"])
        prepared = facade.prepare_exact_review(workspace["task_id"], workspace["batch_id"], 1,
            {"kind": "native", "display_name": "Fresh isolated test",
             "executable_identity": "notepad.exe", "product_name": "Notepad"},
            step_relationships={"step-a-b": ["relation-a-b"]})
        approved = facade.record_review_decisions(prepared["review_ref"], 0,
                     [item["subject_id"] for item in prepared["subjects"]])
        compiled = facade.compile_exact_review(prepared["review_ref"], approved["approval_revision"])
        assert compiled["status"] == "compiled", compiled
        record_path = next((root / "desktop-review/exact-reviews").glob("*/current.json"))
        record = json.loads(record_path.read_text(encoding="utf-8"))
        receipt = json.loads((record_path.parent / f"receipt-{compiled['compile_receipt_id']}.json").read_text(encoding="utf-8"))
        final = json.loads((root / receipt["final_path"]).read_text(encoding="utf-8"))
        return root, final, record
    finally:
        facade.close()
        store.close()


@pytest.mark.parametrize("location", ["edge", "candidate", "relationship"])
@pytest.mark.parametrize("marker", [
    {"requires_semantic_review": True},
    {"target_semantics_status": "stale_after_retarget"},
])
def test_compiler_rejects_unresolved_retarget_semantics_even_with_human_confirmation(tmp_path, location, marker):
    root, final, record = _fresh_compilable_review(tmp_path)
    subject = {
        "edge": final["edges"][0],
        "candidate": final["nodes"][0]["action_candidates"][0],
        "relationship": final["edges"][0]["external_relationships"][0],
    }[location]
    subject.update(marker)
    final["workflow"]["workflow_id"] += "-stale"
    final = exact_review._approve(final, record)
    saved = exact_review.save_interface_workflow_review_candidate(final, project_root=root, create_only=True)
    relative = exact_review._result_relative_path(root, saved, "test")
    source = root / relative
    persisted = json.loads(source.read_text(encoding="utf-8"))
    assert marker.items() <= ({
        "edge": persisted["edges"][0],
        "candidate": persisted["nodes"][0]["action_candidates"][0],
        "relationship": persisted["edges"][0]["external_relationships"][0],
    }[location]).items()
    result = exact_review.compile_reviewed_workflow_asset_v2(
        project_root=root, source_workflow_path=relative,
        expected_source_workflow_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    assert result["status"] == "blocked", result
    assert "unresolved_target_semantics" in {item["code"] for item in result["blocked_reasons"]}

