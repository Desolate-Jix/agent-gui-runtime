from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any

from app.learn.agent_evidence import PersistedReviewRevision
from app.learn.application_interface_graph import save_workflow_review_as_application_assets
from app.learn.interface_workflow_lock import interface_workflow_lock
from app.learn.interface_workflow_review import (
    build_interface_node_review_revision,
    evaluate_interface_workflow_node_integrity,
    load_interface_workflow_library_registry,
    load_interface_workflow_review_context,
    save_interface_workflow_review_candidate,
)


def restore_unchanged_interface_review_confirmations(
    review: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, Any]:
    """仅用服务端已验证的同一修订续存人工审核事实。"""

    prepared = deepcopy(review)
    workflow = prepared.get("workflow") if isinstance(prepared, dict) else None
    workflow_id = str(workflow.get("workflow_id") or "").strip() if isinstance(workflow, dict) else ""
    if not workflow_id:
        return prepared

    registry = load_interface_workflow_library_registry(project_root=project_root)
    record = registry.get("workflows", {}).get(workflow_id)
    if not isinstance(record, dict):
        return prepared
    identity_key = str(record.get("application_identity_key") or "").strip()
    if not identity_key:
        return prepared
    persisted = load_interface_workflow_review_context(
        project_root=project_root,
        application_identity_key=identity_key,
        workflow_id=workflow_id,
    )
    persisted_nodes = {
        str(node.get("node_id") or "").strip(): node
        for node in persisted.get("nodes") or []
        if isinstance(node, dict) and str(node.get("node_id") or "").strip()
    }
    reviewed_statuses = {
        "approved",
        "human_approved",
        "human_confirmed",
        "human_reviewed",
        "reviewed",
    }
    for node in prepared.get("nodes") or []:
        if not isinstance(node, dict) or node.get("reviewed_by_human") is not True:
            continue
        if str(node.get("review_status") or "").strip().casefold() not in reviewed_statuses:
            continue
        node_id = str(node.get("node_id") or "").strip()
        previous = persisted_nodes.get(node_id)
        if not isinstance(previous, dict) or previous.get("reviewed_by_human") is not True:
            continue
        if str(previous.get("review_status") or "").strip().casefold() not in reviewed_statuses:
            continue
        persisted_path = Path(str(record.get("path") or ""))
        persisted_path = (
            persisted_path.resolve()
            if persisted_path.is_absolute()
            else (project_root / persisted_path).resolve()
        )
        persisted_source_asset_sha256 = hashlib.sha256(
            persisted_path.read_bytes()
        ).hexdigest()
        integrity = evaluate_interface_workflow_node_integrity(
            review=persisted,
            node=previous,
            record=record,
            project_root=project_root,
            source_asset_sha256=persisted_source_asset_sha256,
        )
        if not (
            integrity["eligibility"]["agent_usable"]
            and integrity["integrity_verified"]
        ):
            continue
        previous_revision = integrity["canonical_revision"]
        current_revision = build_interface_node_review_revision(
            prepared,
            node_id=node_id,
        )
        if current_revision != previous_revision:
            continue
        node["human_review_confirmation"] = {
            "contract_version": "interface_node_human_review_confirmation_v1",
            "revision": current_revision,
        }
    return prepared


def _interface_workflow_save_lock(review: dict[str, Any]) -> Lock:
    workflow = review.get("workflow") if isinstance(review, dict) else None
    workflow_id = str(workflow.get("workflow_id") or "").strip() if isinstance(workflow, dict) else ""
    lock_key = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in workflow_id
    ).strip("._") or "__invalid_workflow__"
    return interface_workflow_lock(workflow_id)


def save_interface_workflow_review_transaction(
    review: dict[str, Any],
    *,
    project_root: Path,
    out_dir: str | None,
) -> dict[str, Any]:
    """串行化同一流程的审核重算、落盘与只读投影。"""

    with _interface_workflow_save_lock(review):
        prepared_review = restore_unchanged_interface_review_confirmations(review, project_root=project_root)
        result = save_interface_workflow_review_candidate(
            prepared_review,
            project_root=project_root,
            out_dir=out_dir,
        )
        saved_review_path = Path(result["path"])
        saved_review_bytes = saved_review_path.read_bytes()
        normalized_review = json.loads(saved_review_bytes.decode("utf-8-sig"))
        result["saved_review"] = normalized_review
        if result["node_count"] > 0:
            registry = load_interface_workflow_library_registry(project_root=project_root)
            workflow_record = registry.get("workflows", {}).get(result["workflow_id"])
            trusted_revisions: dict[str, PersistedReviewRevision] = {}
            if isinstance(workflow_record, dict):
                source_asset_sha256 = hashlib.sha256(saved_review_bytes).hexdigest()
                for node in normalized_review.get("nodes") or []:
                    if not isinstance(node, dict):
                        continue
                    node_id = str(node.get("node_id") or "").strip()
                    integrity = evaluate_interface_workflow_node_integrity(
                        review=normalized_review,
                        node=node,
                        record=workflow_record,
                        project_root=project_root,
                        source_asset_sha256=source_asset_sha256,
                    )
                    if (
                        integrity["integrity_verified"]
                        and integrity["eligibility"]["agent_usable"]
                    ):
                        trusted_revisions[node_id] = PersistedReviewRevision(
                            revision=integrity["canonical_revision"],
                            revision_hash=integrity["canonical_revision_hash"],
                            source_asset_sha256=source_asset_sha256,
                        )
            result["interface_asset_projection"] = save_workflow_review_as_application_assets(
                normalized_review,
                project_root=project_root,
                persisted_review_revisions=trusted_revisions,
            )
        else:
            result["interface_asset_projection"] = {
                "status": "not_covered",
                "reason": "workflow_has_no_interface_nodes",
                "saved_interface_count": 0,
                "saved_transition_count": 0,
                "artifact_is_authorization": False,
            }
        return result


