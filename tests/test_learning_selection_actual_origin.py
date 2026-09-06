from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


def _actual_payload_and_proof(root: Path) -> tuple[dict, dict]:
    """构造测试替身 proof；不代表真实模型推理。"""
    from tests.test_learning_selection_roundtrip import _payload

    _, payload = _payload(root)
    payload["execution_origin"] = "actual_model"
    payload["gui_actor_provider_state"] = "actual_ready"
    selection_input = payload["gui_actor_selection_input"]
    capture = payload["capture_bundle"]["capture_identity"]
    proof = {
        "contract_version": "gui_actor_current_source_result_v1",
        "raw_output_utf8": selection_input["raw_output_utf8"],
        "native_output_ref": deepcopy(selection_input["native_output_ref"]),
        "provider_id": selection_input["provider_id"],
        "image_sha256": capture["screenshot_sha256"],
        "target_sha256": sha256(payload["target_text"].encode("utf-8")).hexdigest(),
        "child_exit_code": 0,
        "cleanup": {
            "status": "verified_exact_child_exited",
            "exit_code": 0,
            "pid": 17,
            "create_time_ns": "1788000000000000123",
        },
        "current_source_receipt": {
            "contract_version": "gui_actor_current_source_receipt_v1",
            "source_binding": "current_source_external_v1",
            "code_identity": {"test/current-source.py": "a" * 64},
        },
    }
    return payload, proof


def test_client_actual_origin_cannot_self_promote_without_trusted_keyword(tmp_path):
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    payload, proof = _actual_payload_and_proof(tmp_path)
    stopped = run_hybrid_selection_task(payload)
    assert stopped["outcome"] == "safe_stopped"
    assert stopped["reason"] == "actual_execution_required"
    assert run_hybrid_selection_task(payload, actual_execution=proof)["outcome"] == "completed"


@pytest.mark.parametrize("field", ["raw_output_utf8", "image_sha256", "target_sha256", "cleanup"])
def test_actual_origin_rejects_mismatched_trusted_proof(tmp_path, field):
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    payload, proof = _actual_payload_and_proof(tmp_path)
    if field == "cleanup":
        proof[field]["status"] = "unverified"
    else:
        proof[field] = "mismatch"
    result = run_hybrid_selection_task(payload, actual_execution=proof)
    assert result["outcome"] == "safe_stopped"
    assert result["reason"].startswith("actual_execution_invalid:")


def test_actual_origin_persists_reloads_and_preserves_original_proposal(tmp_path):
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.recognition.uei.store import UEIObjectStore
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    payload, proof = _actual_payload_and_proof(tmp_path)
    response = run_hybrid_selection_task(payload, actual_execution=proof)
    trial = persist_selection_review_trial(
        project_root=tmp_path, payload=payload, response=response, actual_execution=proof,
    )
    initial = load_learning_draft_review(trial, project_root=tmp_path)
    stored = UEIObjectStore(root=tmp_path / "artifacts/uei-shadow-store").get(
        initial["hybrid_review_projection_ref"],
        contract_version="hybrid_selection_review_record_v1",
    )
    assert stored["actual_execution"]["cleanup"]["create_time_ns"] == "1788000000000000123"
    projection = initial["hybrid_review_projection"]
    selected = next(item for item in projection["candidates"] if item["selection"] is not None)
    original = deepcopy(selected["model_proposal"])
    decisions = [
        {"decision_id": "decision/actual-rebox", "decision_type": "rebox", "candidate_id": selected["candidate_id"], "bbox": [41, 21, 119, 51]},
        {"decision_id": "decision/actual-semantic", "decision_type": "semantic_edit", "candidate_id": selected["candidate_id"], "semantics": {"role": "button", "label": "Quick Apply", "description": "human supplied"}},
    ]
    saved = save_reviewed_template_candidate(
        trial,
        {"expected_hybrid_review_projection_ref": initial["hybrid_review_projection_ref"], "hybrid_review_decisions": decisions},
        project_root=tmp_path,
    )
    saved_path = tmp_path / saved["reviewed_template_candidate_path"]
    after = load_learning_draft_review(saved_path, project_root=tmp_path)
    revised = next(item for item in after["hybrid_review_projection"]["candidates"] if item["candidate_id"] == selected["candidate_id"])
    assert after["hybrid_review_projection"]["execution_origin"] == "actual_model"
    assert revised["model_proposal"] == original
    assert revised["reviewed_geometry"]["bbox"] == [41, 21, 119, 51]
    code = "from app.learn.draft_review import load_learning_draft_review; import json; print(json.dumps(load_learning_draft_review(r'%s', project_root=r'%s')['hybrid_review_projection'], ensure_ascii=False))" % (saved_path, tmp_path)
    fresh = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, capture_output=True, text=True, encoding="utf-8", check=True)
    reloaded = json.loads(fresh.stdout)
    assert reloaded["execution_origin"] == "actual_model"
    cross_process = next(item for item in reloaded["candidates"] if item["candidate_id"] == selected["candidate_id"])
    assert cross_process["model_proposal"] == original
