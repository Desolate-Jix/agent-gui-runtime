"""供协议入口与磁盘重载共用的精确桌面审核基线校验。"""

from __future__ import annotations

import copy
import hmac
from typing import Any

from .candidate_projection import (
    CandidateProjectionError,
    apply_candidate_diffs,
    index_candidate_fields,
    project_candidate_fields,
)
from .contracts import ReviewBaselineInput, canonical_hash, fail, parse, validate_batch
from .graph_contract import (
    GraphContractError, validate_graph_baseline as _validate_graph_baseline,
    validate_graph_operations, validate_graph_scope,
)


def validate_review_baseline(
    value: dict[str, Any], *, task_id: str, original_batch: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """校验血缘，并返回线上的基线和规范化有效批次。"""

    baseline = parse(ReviewBaselineInput, value, "review baseline")
    original = _public_batch(original_batch)
    if baseline["task_id"] != task_id:
        fail("invalid_baseline", "review baseline task does not match the batch owner")
    if baseline["source_ref"] != canonical_hash(original):
        fail("invalid_baseline", "review baseline source does not match the original batch")
    normalized = validate_batch(baseline["batch"], existing_png_sha256=frozenset(
        shot["sha256"] for shot in original["screenshots"]))
    if normalized["batch_id"] != original["batch_id"]:
        fail("invalid_baseline", "review baseline batch identity does not match")
    if baseline["batch_sha256"] != canonical_hash(normalized):
        fail("invalid_baseline", "review baseline batch digest does not match its content")
    _assert_stable_identity(original, normalized)
    return baseline, normalized


def validate_candidate_changes(
    candidate: dict[str, Any],
    batch: dict[str, Any],
    scope: dict[str, list[str]],
    *,
    reject_duplicate_fields: bool = True,
) -> None:
    """依据有效基线批次校验强类型候选引用。"""
    try:
        writes = project_candidate_fields(
            candidate, batch, scope,
            reject_duplicate_fields=reject_duplicate_fields,
        )
        indexed = index_candidate_fields(batch)
        diffs = [{
            "target_type": item.target_type, "target_id": item.target_id,
            "field": item.field, "baseline": copy.deepcopy(indexed.get(
                (item.target_type, item.target_id, item.field)
            )),
            "current": copy.deepcopy(indexed.get(
                (item.target_type, item.target_id, item.field)
            )),
            "proposed": copy.deepcopy(item.proposed),
        } for item in writes]
        projected = apply_candidate_diffs(batch, diffs)
        validate_batch(_batch_contract_payload(projected), existing_png_sha256=frozenset(
            shot["sha256"] for shot in batch["screenshots"]))
    except CandidateProjectionError as error:
        fail(error.code, error.message)


def candidate_content_sha256(candidate: dict[str, Any]) -> str:
    payload = {
        key: copy.deepcopy(value)
        for key, value in candidate.items()
        if key not in {"status", "candidate_sha256"}
    }
    return canonical_hash(payload)


def validate_graph_review_baseline(value: dict[str, Any], *, task_id: str, batch_id: str, original_batch: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        return _validate_graph_baseline(
            value, task_id=task_id, batch_id=batch_id,
            original_batch_sha256=canonical_hash(_public_batch(original_batch)),
        )
    except GraphContractError as error:
        fail("invalid_baseline", str(error))


def validate_graph_candidate(candidate: dict[str, Any], snapshot: dict[str, Any], issue: dict[str, Any]) -> None:
    try:
        scope = validate_graph_scope(candidate["scope"], snapshot["graph"])
        if scope != issue["scope"]:
            fail("invalid_scope", "candidate scope must match issue scope")
        validate_graph_operations(candidate["changes"], snapshot["graph"], scope)
    except GraphContractError as error:
        fail("invalid_scope" if "scope" in str(error) else "invalid_arguments", str(error))


def _assert_stable_identity(original: dict[str, Any], reviewed: dict[str, Any]) -> None:
    for field in ("contract_version", "idempotency_key", "batch_id"):
        if reviewed.get(field) != original.get(field):
            fail("invalid_baseline", f"review baseline changed stable batch field {field}")
    original_shots = [(item["screenshot_id"], item["png_base64"]) for item in original["screenshots"]]
    reviewed_shots = [(item["screenshot_id"], item["png_base64"]) for item in reviewed["screenshots"]]
    if original_shots != reviewed_shots[:len(original_shots)]:
        fail("invalid_baseline", "review baseline changed screenshot evidence")
    if len(reviewed["interfaces"]) < len(original["interfaces"]):
        fail("invalid_baseline", "review baseline changed interface or region stable ids")
    for before, after in zip(original["interfaces"], reviewed["interfaces"]):
        if (before["interface_id"], before["screenshot_id"]) != (after["interface_id"], after["screenshot_id"]):
            fail("invalid_baseline", "review baseline changed interface or region stable ids")
        old_ids = [region["region_id"] for region in before["regions"]]
        new_ids = [region["region_id"] for region in after["regions"]]
        if new_ids[:len(old_ids)] != old_ids or len(set(new_ids)) != len(new_ids):
            fail("invalid_baseline", "review baseline changed interface or region stable ids")
    original_steps = [item["step_id"] for item in original["steps"]]
    reviewed_steps = [item["step_id"] for item in reviewed["steps"]]
    if (
        len(set(original_steps)) != len(original_steps)
        or len(set(reviewed_steps)) != len(reviewed_steps)
        or not set(original_steps) <= set(reviewed_steps)
    ):
        fail("invalid_baseline", "review baseline changed stable steps ids")
    for collection, identity in (
        ("relationships", "relationship_id"), ("issues", "issue_id"),
    ):
        old_ids = [item[identity] for item in original[collection]]
        new_ids = [item[identity] for item in reviewed[collection]]
        if collection == "relationships":
            valid = new_ids[:len(old_ids)] == old_ids
        else:
            valid = new_ids == old_ids
        if not valid:
            fail("invalid_baseline", f"review baseline changed stable {collection} ids")


def hashes_equal(left: str, right: str) -> bool:
    return isinstance(left, str) and isinstance(right, str) and hmac.compare_digest(left, right)


def _public_batch(batch: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in batch.items()
        if key not in {"connection_id", "task_id", "status", "source", "fresh_learning_source"}
    }


def _batch_contract_payload(batch: dict[str, Any]) -> dict[str, Any]:
    result = _public_batch(batch)
    for screenshot in result.get("screenshots", []):
        for field in ("sha256", "width", "height"):
            screenshot.pop(field, None)
    return result
