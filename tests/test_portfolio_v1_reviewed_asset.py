from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def _portfolio_v1_review() -> dict:
    return {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {
            "workflow_id": "portfolio_v1_reviewed_two_state",
            "goal": "Open the application flow from an already-open job detail.",
            "application_identity": {"url": "https://nz.seek.com/jobs"},
            "entry_node_id": "job_detail",
            "node_ids": ["job_detail", "apply_entry"],
            "edge_ids": ["detail_to_apply_entry"],
            "review_status": "human_approved",
        },
        "nodes": [
            {
                "node_id": "job_detail",
                "display_name": "Job Detail",
                "surface_type": "detail",
                "state_signature": "portfolio-v1-job-detail",
                "source_paths": [],
                "evidence": {},
                "controls": [{"control_id": "apply", "label": "Apply"}],
                "regions": [],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
            },
            {
                "node_id": "apply_entry",
                "display_name": "Apply Entry",
                "surface_type": "application",
                "state_signature": "portfolio-v1-apply-entry",
                "source_paths": [],
                "evidence": {},
                "controls": [],
                "regions": [],
                "review_status": "needs_learning",
                "reviewed_by_human": False,
            },
        ],
        "edges": [
            {
                "edge_id": "detail_to_apply_entry",
                "operation_id": "open_apply_flow",
                "source_node_id": "job_detail",
                "target_node_id": "apply_entry",
                "action_type": "open_apply_flow",
                "target_control_id": "apply",
                "target_region_id": "",
                "risk_level": "medium",
                "requires_user_confirmation": True,
                "preconditions": ["Job Detail identity is uniquely visible"],
                "success_conditions": ["Apply Entry identity is visible"],
                "failure_conditions": ["An unexpected destination is visible"],
                "review_status": "human_approved",
            }
        ],
        "safety": {},
    }


def _save_integrity_reviewed_source(project_root: Path) -> tuple[Path, str]:
    from app.learn.interface_workflow_review import (
        build_interface_node_review_revision,
        save_interface_workflow_review_candidate,
    )

    initial = save_interface_workflow_review_candidate(
        _portfolio_v1_review(), project_root=project_root
    )
    source = Path(initial["path"])
    review = json.loads(source.read_text(encoding="utf-8"))
    detail = next(node for node in review["nodes"] if node["node_id"] == "job_detail")
    detail["review_status"] = "human_approved"
    detail["reviewed_by_human"] = True
    detail["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": build_interface_node_review_revision(
            review, node_id="job_detail"
        ),
    }
    saved = save_interface_workflow_review_candidate(review, project_root=project_root)
    saved_source = Path(saved["path"])
    return saved_source, hashlib.sha256(saved_source.read_bytes()).hexdigest()


def _assert_no_stored_runtime_authority(value: object) -> None:
    if isinstance(value, list):
        for item in value:
            _assert_no_stored_runtime_authority(item)
        return
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        normalized = str(key).casefold()
        assert normalized not in {"x", "y", "bbox", "hwnd", "window_handle"}
        if normalized.endswith("_bbox"):
            assert normalized == "current_target_bbox"
            assert item == {"required": True}
        _assert_no_stored_runtime_authority(item)


def test_portfolio_v1_two_state_reviewed_asset_survives_publish_and_fresh_process_load(
    tmp_path: Path,
) -> None:
    from app.agent.reviewed_workflow_asset import (
        ReviewedWorkflowAssetStore,
        content_sha256,
    )
    from app.agent.reviewed_workflow_compiler import (
        compile_reviewed_workflow_asset_v2,
    )

    source, source_sha256 = _save_integrity_reviewed_source(tmp_path)
    persisted_review = json.loads(source.read_text(encoding="utf-8"))
    persisted_detail = next(
        node
        for node in persisted_review["nodes"]
        if node["node_id"] == "job_detail"
    )
    persisted_apply_entry = next(
        node
        for node in persisted_review["nodes"]
        if node["node_id"] == "apply_entry"
    )
    assert persisted_detail["review_status"] == "human_approved"
    assert persisted_detail["reviewed_by_human"] is True
    assert persisted_detail["reviewed_revision_hash"]
    assert (
        persisted_detail["reviewed_revision_hash"]
        == persisted_detail["current_revision_hash"]
    )
    assert persisted_apply_entry["review_status"] == "needs_learning"
    assert persisted_apply_entry["reviewed_by_human"] is False

    compiled = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=source_sha256,
    )
    assert compiled["status"] == "compiled"
    assert compiled["blocked_reasons"] == []
    asset = compiled["asset"]
    assert asset["source_review_lineage"]["source_workflow_sha256"] == source_sha256
    assert asset["source_review_lineage"]["human_approved_node_ids"] == [
        "job_detail"
    ]
    assert asset["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "fresh_grounding_required": True,
        "post_action_verification_required": True,
        "historical_coordinates_used": False,
    }

    assert len(asset["states"]) == 2
    states_by_source = {state["source_node_id"]: state for state in asset["states"]}
    assert set(states_by_source) == {"job_detail", "apply_entry"}
    assert len(asset["transitions"]) == 1
    transition = asset["transitions"][0]
    assert states_by_source["job_detail"]["display_name"] == "Job Detail"
    assert states_by_source["apply_entry"]["display_name"] == "Apply Entry"
    assert asset["entry_state_id"] == states_by_source["job_detail"]["state_id"]
    assert states_by_source["job_detail"]["availability"] == "reviewed"
    assert states_by_source["job_detail"]["allowed_transition_ids"] == [
        transition["transition_id"]
    ]
    assert states_by_source["apply_entry"]["availability"] == "stop_boundary"
    assert states_by_source["apply_entry"]["allowed_transition_ids"] == []
    assert transition["semantic_action"] == "open_apply_flow"
    assert transition["source_state_id"] == states_by_source["job_detail"]["state_id"]
    assert transition["target_state_id"] == states_by_source["apply_entry"]["state_id"]
    assert transition["risk_policy"] == {
        "risk_level": "medium",
        "requires_gate": True,
        "final_submit_forbidden": True,
        "requires_user_confirmation": True,
        "automatic_execution_allowed": False,
    }
    assert transition["post_action_verification"]["requires_new_capture"] is True
    post_rules = transition["post_action_verification"]["semantic_success_rules"]
    assert len(post_rules) == 1
    assert post_rules[0]["type"] == "target_state_identity"
    assert post_rules[0]["rule_id"].startswith("rule_")
    _assert_no_stored_runtime_authority(asset)

    store_root = tmp_path / "runtime_state" / "reviewed-workflow-assets-v2"
    assert not store_root.exists()
    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    first_publish = store.publish(asset, expected_registry_revision=0)
    repeated_publish = store.publish(asset, expected_registry_revision=0)
    expected_object_bytes = json.dumps(
        asset,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected_content_sha256 = hashlib.sha256(expected_object_bytes).hexdigest()
    assert content_sha256(asset) == expected_content_sha256
    assert first_publish["status"] == "published"
    assert repeated_publish["status"] == "already_published"
    assert first_publish["content_sha256"] == expected_content_sha256
    assert repeated_publish["content_sha256"] == expected_content_sha256
    assert first_publish["registry_revision"] == repeated_publish["registry_revision"] == 1
    assert first_publish["artifact_is_authorization"] is False
    assert first_publish["execute_binding_enabled"] is False
    assert repeated_publish["artifact_is_authorization"] is False
    assert repeated_publish["execute_binding_enabled"] is False

    repo_root = Path(__file__).resolve().parents[1]
    child_script = """
import json
from pathlib import Path
import sys

from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256

root = Path(sys.argv[1]).resolve()
asset_id = sys.argv[2]
store = ReviewedWorkflowAssetStore(project_root=root)
first = store.load_active(asset_id)
second = store.load_active(asset_id)
registry = store.registry()
object_sha = registry["active_by_asset"][asset_id]
record = registry["objects"][object_sha]
print(json.dumps({
    "asset": first,
    "asset_content_sha256": content_sha256(first),
    "repeat_equal": first == second,
    "registry_revision": registry["registry_revision"],
    "registry_path": str(store.registry_path.resolve()),
    "object_path": str((root / record["object_path"]).resolve()),
    "artifact_is_authorization": first["safety"]["artifact_is_authorization"],
    "execute_binding_enabled": first["safety"]["execute_binding_enabled"],
}, ensure_ascii=False, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", child_script, str(tmp_path), asset["asset_id"]],
        cwd=repo_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    restarted = json.loads(completed.stdout)
    assert completed.stderr == ""
    assert restarted["asset"] == asset
    assert restarted["asset_content_sha256"] == expected_content_sha256
    assert restarted["repeat_equal"] is True
    assert restarted["registry_revision"] == 1
    assert restarted["artifact_is_authorization"] is False
    assert restarted["execute_binding_enabled"] is False

    resolved_root = tmp_path.resolve()
    registry_path = Path(restarted["registry_path"])
    object_path = Path(restarted["object_path"])
    assert registry_path.is_relative_to(resolved_root)
    assert object_path.is_relative_to(resolved_root)
    assert registry_path == (store_root / "registry.json").resolve()
    assert object_path == (tmp_path / first_publish["object_path"]).resolve()
    assert object_path.read_bytes() == expected_object_bytes
