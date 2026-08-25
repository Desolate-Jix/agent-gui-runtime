"""Closed, non-authorizing Benchmark-v2 prediction records."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Mapping

SAFETY = {"artifact_is_authorization": False, "execute_binding_enabled": False, "display_only": True}
ARMS = {"qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista"}
SHA_FIELDS = {"id", "content_sha256"}


def _bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _ref(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != SHA_FIELDS:
        raise ValueError(f"{name} must be an exact sealed ref")
    result = dict(value)
    if not all(isinstance(result[k], str) and result[k] for k in SHA_FIELDS) or len(result["content_sha256"]) != 64:
        raise ValueError(f"{name} is invalid")
    return result


def _validate_row(value: object) -> dict[str, Any]:
    required = {"case_id", "arm_id", "selected_target_id", "candidate_id", "target_binding_ref", "eligibility", "fusion_ref", "capture_ref", "bbox_ref", "bbox"}
    if not isinstance(value, Mapping) or not required.issubset(value):
        raise ValueError("prediction row is missing an exact binding field")
    row = deepcopy(dict(value))
    if row["arm_id"] not in ARMS or not all(isinstance(row[k], str) and row[k] for k in required - {"bbox"}):
        raise ValueError("prediction row identity is invalid")
    bbox = row["bbox"]
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(x, (int, float)) for x in bbox):
        raise ValueError("prediction bbox is invalid")
    eligibility = row["eligibility"]
    if eligibility == "ELIGIBLE":
        if not isinstance(row.get("vista_request_ref"), str) or not row["vista_request_ref"]:
            raise ValueError("eligible prediction requires exact VISTA request ref")
        if row.get("submission_status") != "SUBMITTED":
            raise ValueError("eligible prediction request must be submitted")
        if "ineligible_reason" in row:
            raise ValueError("eligible prediction cannot have ineligible reason")
    elif eligibility == "INELIGIBLE":
        if "vista_request_ref" in row or "submission_status" in row:
            raise ValueError("ineligible prediction must have zero VISTA requests")
        if not isinstance(row.get("ineligible_reason"), str) or not row["ineligible_reason"]:
            raise ValueError("ineligible prediction requires reason")
    else:
        raise ValueError("prediction eligibility is invalid")
    allowed = required | {"vista_request_ref", "submission_status", "ineligible_reason", "vista_result"}
    if set(row) - allowed:
        raise ValueError("prediction row has undeclared fields")
    return row


def _revision(record: Mapping[str, object]) -> dict[str, str]:
    value = {k: v for k, v in record.items() if k != "revision_ref"}
    return {"id": f"prediction-revision/{len(record['decisions'])}", "content_sha256": _sha(value)}


def seal_automatic_prediction(*, request_ref: Mapping[str, str], pre_review: Mapping[str, object], execution_refs: list[Mapping[str, str]], lifecycle_ref: Mapping[str, str]) -> dict[str, object]:
    if not isinstance(pre_review, Mapping) or set(pre_review) != {"contract_version", "prediction_id", "rows", "safety"}:
        raise ValueError("pre_review must be a closed object")
    if pre_review["contract_version"] != "benchmark_v2_pre_review_v1" or pre_review["safety"] != SAFETY:
        raise ValueError("pre_review contract or safety is invalid")
    if not isinstance(pre_review["prediction_id"], str) or not pre_review["prediction_id"]:
        raise ValueError("prediction_id is invalid")
    rows = pre_review["rows"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("pre_review rows cannot be empty")
    validated_pre = deepcopy(dict(pre_review)); validated_pre["rows"] = [_validate_row(row) for row in rows]
    row_keys = [(row["case_id"], row["arm_id"]) for row in validated_pre["rows"]]
    if len(set(row_keys)) != len(row_keys):
        raise ValueError("pre_review contains duplicate or ambiguous arm/case rows")
    if not isinstance(execution_refs, list) or not execution_refs:
        raise ValueError("execution refs cannot be empty")
    validated_execution_refs = [_ref(item, "execution_ref") for item in execution_refs]
    if len({item["id"] for item in validated_execution_refs}) != len(validated_execution_refs):
        raise ValueError("execution refs must be unique")
    record: dict[str, object] = {
        "contract_version": "benchmark_v2_prediction_record_v1",
        "prediction_id": validated_pre["prediction_id"],
        "request_ref": _ref(request_ref, "request_ref"),
        "pre_review_ref": {"id": f"pre-review/{validated_pre['prediction_id']}", "content_sha256": _sha(validated_pre)},
        "pre_review": validated_pre,
        "execution_refs": validated_execution_refs,
        "lifecycle_ref": _ref(lifecycle_ref, "lifecycle_ref"),
        "decisions": [],
        "post_review": deepcopy(validated_pre),
        "safety": deepcopy(SAFETY),
    }
    record["revision_ref"] = _revision(record)
    return record


def _validate_record(record: Mapping[str, object]) -> dict[str, object]:
    required = {"contract_version", "prediction_id", "request_ref", "pre_review_ref", "pre_review", "execution_refs", "lifecycle_ref", "decisions", "post_review", "safety", "revision_ref"}
    if not isinstance(record, Mapping) or set(record) != required:
        raise ValueError("prediction record is not closed")
    value = deepcopy(dict(record))
    if value["contract_version"] != "benchmark_v2_prediction_record_v1" or value["safety"] != SAFETY:
        raise ValueError("prediction record contract is invalid")
    expected_pre = {"id": f"pre-review/{value['prediction_id']}", "content_sha256": _sha(value["pre_review"])}
    if value["pre_review_ref"] != expected_pre:
        raise ValueError("immutable pre_review_ref mismatch")
    if not isinstance(value["decisions"], list):
        raise ValueError("prediction decisions must be append-only list")
    expected_post = deepcopy(value["pre_review"])
    reconstructed = deepcopy(value)
    reconstructed["decisions"] = []
    reconstructed["post_review"] = deepcopy(expected_post)
    reconstructed["revision_ref"] = _revision(reconstructed)
    seen: set[str] = set()
    for decision in value["decisions"]:
        if not isinstance(decision, Mapping) or set(decision) != {"decision_id", "predecessor_ref", "target_binding_ref", "disposition", "replacement_candidate_id"}:
            raise ValueError("stored review decision is not closed")
        if decision["decision_id"] in seen or decision["predecessor_ref"] != reconstructed["revision_ref"]:
            raise ValueError("stored review predecessor chain mismatch")
        seen.add(decision["decision_id"])
        matches = [row for row in expected_post["rows"] if row["target_binding_ref"] == decision["target_binding_ref"]]
        if not matches:
            raise ValueError("stored review target binding is missing")
        for row in matches:
            row["candidate_id"] = decision["replacement_candidate_id"]
        reconstructed["decisions"].append(deepcopy(dict(decision)))
        reconstructed["post_review"] = deepcopy(expected_post)
        reconstructed["revision_ref"] = _revision(reconstructed)
    if value["post_review"] != expected_post or value["revision_ref"] != reconstructed["revision_ref"]:
        raise ValueError("derived post_review or revision ref mismatch")
    return value


def append_review_decisions(record: Mapping[str, object], decisions: list[Mapping[str, object]]) -> dict[str, object]:
    value = _validate_record(record)
    if not isinstance(decisions, list):
        raise ValueError("decisions must be a list")
    existing_by_id = {item["decision_id"]: item for item in value["decisions"]}
    new_items = []
    for item in decisions:
        if not isinstance(item, Mapping):
            raise ValueError("review decision must be an object")
        candidate = deepcopy(dict(item))
        prior = existing_by_id.get(candidate.get("decision_id"))
        if prior is not None:
            if prior != candidate:
                raise ValueError("review decision ID cannot be rewritten")
            continue
        new_items.append(candidate)
    if not new_items:
        return value
    current = value["revision_ref"]
    rows = deepcopy(value["post_review"]["rows"])
    for decision in new_items:
        if set(decision) != {"decision_id", "predecessor_ref", "target_binding_ref", "disposition", "replacement_candidate_id"}:
            raise ValueError("review decision is not closed")
        if decision["predecessor_ref"] != current:
            raise ValueError("review predecessor chain mismatch")
        matches = [row for row in rows if row["target_binding_ref"] == decision["target_binding_ref"]]
        if not matches:
            raise ValueError("review decision target binding is missing")
        for row in matches:
            row["candidate_id"] = decision["replacement_candidate_id"]
        value["decisions"].append(decision)
        value["post_review"]["rows"] = rows
        value["revision_ref"] = _revision(value)
        current = value["revision_ref"]
    return value
