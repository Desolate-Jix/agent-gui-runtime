"""Immutable Portfolio Hybrid v1.1 benchmark and prediction interfaces."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


MANIFEST_TEMPLATE_CONTRACT = "portfolio_hybrid_v1_1_benchmark_manifest_template_v1"
MANIFEST_CONTRACT = "portfolio_hybrid_v1_1_benchmark_manifest_v1"
PROJECTION_CONTRACT = "portfolio_hybrid_v1_1_provider_projection_v1"
PREDICTION_REQUEST_CONTRACT = "portfolio_hybrid_v1_1_prediction_request_v1"
PREDICTION_CONTRACT = "portfolio_hybrid_v1_1_prediction_v1"
ARM_IDS = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
PRE_VISTA_ARM_IDS = ARM_IDS[:3]
_ARM_DEFINITIONS = {
    "qwen_only": ("pre-vista", ["qwen"]),
    "omni_only_discovery": ("pre-vista", ["omni"]),
    "omni_to_qwen": ("pre-vista", ["omni", "qwen"]),
    "omni_to_qwen_vista": ("post-vista", ["omni", "qwen", "vista"]),
}
_ARTIFACT_NAMES = {
    "gate_config",
    "benchmark_producer",
    "benchmark_runner",
    "scorer",
    "corpus_manifest",
    "gold",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_FIELD_MARKERS = (
    "gold",
    "expected_candidate",
    "acceptable_bbox",
    "acceptable_region",
    "annotator",
    "reviewer",
    "correct_selection",
    "case_result",
)
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


def canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"value is not canonical JSON: {error}") from error
    return encoded.encode("utf-8")


def content_sha256(value: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(value))
    payload.pop("content_sha256", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def contains_gold_fields(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if any(marker in normalized for marker in _PRIVATE_FIELD_MARKERS):
                return True
            if contains_gold_fields(child):
                return True
    elif isinstance(value, list):
        return any(contains_gold_fields(child) for child in value)
    return False


def seal_benchmark_manifest(
    manifest: Mapping[str, Any], *, root: str | Path | None = None
) -> dict[str, Any]:
    template = _closed_object(
        manifest,
        name="benchmark manifest template",
        fields={
            "contract_version",
            "benchmark_id",
            "corpus_id",
            "artifact_paths",
            "provider_revisions",
            "shared_budget",
            "shared_context_policy",
            "arms",
            "cases",
            "evidence_policy",
        },
    )
    if template["contract_version"] != MANIFEST_TEMPLATE_CONTRACT:
        raise ValueError(f"contract_version must be {MANIFEST_TEMPLATE_CONTRACT}")
    _non_empty_string(template["benchmark_id"], name="benchmark_id")
    _non_empty_string(template["corpus_id"], name="corpus_id")
    root_path = Path.cwd() if root is None else Path(root)
    root_path = root_path.resolve()

    artifact_paths = _closed_object(
        template["artifact_paths"], name="artifact_paths", fields=_ARTIFACT_NAMES
    )
    artifact_seals: dict[str, dict[str, str]] = {}
    for name in sorted(_ARTIFACT_NAMES):
        relative = _safe_relative_path(artifact_paths[name], name=f"artifact_paths.{name}")
        artifact_seals[name] = {
            "path": relative,
            "sha256": _sha256_file(_resolve_inside(root_path, relative)),
        }

    provider_revisions = _closed_object(
        template["provider_revisions"],
        name="provider_revisions",
        fields={"omni", "qwen", "vista"},
    )
    for provider, revision in provider_revisions.items():
        _non_empty_string(revision, name=f"provider_revisions.{provider}")

    shared_budget = _validate_budget(template["shared_budget"], name="shared_budget")
    shared_context = _validate_context_policy(
        template["shared_context_policy"], name="shared_context_policy"
    )
    arms = _validate_arms(
        template["arms"],
        shared_budget=shared_budget,
        shared_context=shared_context,
    )
    cases = _validate_and_seal_cases(template["cases"], root_path=root_path)
    evidence_policy = _closed_object(
        template["evidence_policy"],
        name="evidence_policy",
        fields={"public", "private"},
    )
    if evidence_policy != {
        "public": "aggregate_metrics_only",
        "private": "case_level_gold_and_predictions",
    }:
        raise ValueError("evidence_policy must separate aggregate public and private case evidence")

    sealed = {
        "contract_version": MANIFEST_CONTRACT,
        "benchmark_id": template["benchmark_id"],
        "corpus_id": template["corpus_id"],
        "artifact_seals": artifact_seals,
        "provider_revisions": provider_revisions,
        "provider_revisions_sha256": _mapping_sha(provider_revisions),
        "shared_budget": shared_budget,
        "shared_budget_sha256": _mapping_sha(shared_budget),
        "shared_context_policy": shared_context,
        "shared_context_policy_sha256": _mapping_sha(shared_context),
        "arms": arms,
        "cases": cases,
        "evidence_policy": evidence_policy,
        **_NON_AUTHORIZING,
    }
    sealed["content_sha256"] = content_sha256(sealed)
    return verify_benchmark_manifest(sealed, root=root_path)


def verify_benchmark_manifest(
    manifest: Mapping[str, Any], *, root: str | Path | None = None
) -> dict[str, Any]:
    sealed = _closed_object(
        manifest,
        name="sealed benchmark manifest",
        fields={
            "contract_version",
            "benchmark_id",
            "corpus_id",
            "artifact_seals",
            "provider_revisions",
            "provider_revisions_sha256",
            "shared_budget",
            "shared_budget_sha256",
            "shared_context_policy",
            "shared_context_policy_sha256",
            "arms",
            "cases",
            "evidence_policy",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if sealed["contract_version"] != MANIFEST_CONTRACT:
        raise ValueError(f"contract_version must be {MANIFEST_CONTRACT}")
    _require_non_authorizing(sealed, name="sealed benchmark manifest")
    declared = _sha256(sealed["content_sha256"], name="content_sha256")
    if declared != content_sha256(sealed):
        raise ValueError("benchmark manifest content_sha256 mismatch")
    if _sha256(sealed["provider_revisions_sha256"], name="provider_revisions_sha256") != _mapping_sha(
        sealed["provider_revisions"]
    ):
        raise ValueError("provider_revisions_sha256 mismatch")
    if _sha256(sealed["shared_budget_sha256"], name="shared_budget_sha256") != _mapping_sha(
        sealed["shared_budget"]
    ):
        raise ValueError("shared_budget_sha256 mismatch")
    if _sha256(
        sealed["shared_context_policy_sha256"], name="shared_context_policy_sha256"
    ) != _mapping_sha(sealed["shared_context_policy"]):
        raise ValueError("shared_context_policy_sha256 mismatch")
    shared_budget = _validate_budget(sealed["shared_budget"], name="shared_budget")
    shared_context = _validate_context_policy(
        sealed["shared_context_policy"], name="shared_context_policy"
    )
    _validate_arms(
        sealed["arms"], shared_budget=shared_budget, shared_context=shared_context
    )
    _validate_sealed_cases(sealed["cases"])
    artifact_seals = _closed_object(
        sealed["artifact_seals"], name="artifact_seals", fields=_ARTIFACT_NAMES
    )
    for name, item in artifact_seals.items():
        record = _closed_object(
            item, name=f"artifact_seals.{name}", fields={"path", "sha256"}
        )
        _safe_relative_path(record["path"], name=f"artifact_seals.{name}.path")
        _sha256(record["sha256"], name=f"artifact_seals.{name}.sha256")
    if root is not None:
        root_path = Path(root).resolve()
        for name, item in artifact_seals.items():
            actual = _sha256_file(_resolve_inside(root_path, item["path"]))
            if actual != item["sha256"]:
                raise ValueError(f"artifact seal mismatch: {name}")
        for case in sealed["cases"]:
            actual = _sha256_file(_resolve_inside(root_path, case["image_path"]))
            if actual != case["image_sha256"]:
                raise ValueError(f"image seal mismatch: {case['case_id']}")
    return sealed


def provider_manifest_projection(
    sealed_manifest: Mapping[str, Any], arm_id: str | None = None
) -> dict[str, Any]:
    sealed = verify_benchmark_manifest(sealed_manifest)
    selected_arms = sealed["arms"]
    if arm_id is not None:
        selected_arms = [arm for arm in selected_arms if arm["arm_id"] == arm_id]
        if len(selected_arms) != 1:
            raise ValueError(f"unknown arm_id: {arm_id}")
    projection = {
        "contract_version": PROJECTION_CONTRACT,
        "benchmark_ref": {
            "id": sealed["benchmark_id"],
            "content_sha256": sealed["content_sha256"],
        },
        "corpus_id": sealed["corpus_id"],
        "provider_revisions": deepcopy(sealed["provider_revisions"]),
        "shared_budget": deepcopy(sealed["shared_budget"]),
        "shared_context_policy": deepcopy(sealed["shared_context_policy"]),
        "arms": deepcopy(selected_arms),
        "cases": [
            {
                "case_id": case["case_id"],
                "partition": case["partition"],
                "image_ref": {
                    "path": case["image_path"],
                    "sha256": case["image_sha256"],
                },
                "goal": case["goal"],
            }
            for case in sealed["cases"]
        ],
        **_NON_AUTHORIZING,
    }
    if contains_gold_fields(projection):
        raise ValueError("provider projection contains scorer-private fields")
    return projection


def build_prediction_request(
    sealed_manifest: Mapping[str, Any], arm_id: str, case_id: str
) -> dict[str, Any]:
    projection = provider_manifest_projection(sealed_manifest, arm_id)
    cases = [case for case in projection["cases"] if case["case_id"] == case_id]
    if len(cases) != 1:
        raise ValueError(f"unknown case_id: {case_id}")
    arm = projection["arms"][0]
    request = {
        "contract_version": PREDICTION_REQUEST_CONTRACT,
        "benchmark_ref": deepcopy(projection["benchmark_ref"]),
        "arm_id": arm_id,
        "case": deepcopy(cases[0]),
        "producer_stages": deepcopy(arm["producer_stages"]),
        "provider_revisions": deepcopy(projection["provider_revisions"]),
        "budget": deepcopy(arm["budget"]),
        "context_policy": deepcopy(arm["context_policy"]),
        "vista_payload": {
            "enabled": arm_id == "omni_to_qwen_vista",
            "proposal_contract_version": "hybrid_vista_proposals_v1",
            "candidate_id": None,
            "candidate_bbox_ref": None,
            "roi_ref": None,
            "affine_transform_ref": None,
            "canonical_point": None,
        },
        **_NON_AUTHORIZING,
    }
    if contains_gold_fields(request):
        raise ValueError("prediction request contains scorer-private fields")
    return request


def validate_prediction_record(
    prediction: Mapping[str, Any], sealed_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    sealed = verify_benchmark_manifest(sealed_manifest)
    record = _closed_object(
        prediction,
        name="prediction",
        fields={
            "contract_version",
            "benchmark_ref",
            "arm_id",
            "case_id",
            "partition",
            "producer_revision_sha256",
            "pre_review",
            "post_review",
            "vista",
            "provider_evidence_refs",
            "cleanup_evidence_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
        },
    )
    if record["contract_version"] != PREDICTION_CONTRACT:
        raise ValueError(f"prediction contract_version must be {PREDICTION_CONTRACT}")
    _require_non_authorizing(record, name="prediction")
    reference = _validate_ref(record["benchmark_ref"], name="benchmark_ref")
    if reference != {
        "id": sealed["benchmark_id"],
        "content_sha256": sealed["content_sha256"],
    }:
        raise ValueError("prediction benchmark_ref mismatch")
    if record["arm_id"] not in ARM_IDS:
        raise ValueError("prediction arm_id is invalid")
    matches = [case for case in sealed["cases"] if case["case_id"] == record["case_id"]]
    if len(matches) != 1 or matches[0]["partition"] != record["partition"]:
        raise ValueError("prediction case or partition mismatch")
    _sha256(record["producer_revision_sha256"], name="producer_revision_sha256")
    record["pre_review"] = _validate_selection(record["pre_review"], name="pre_review")
    post = _closed_object(
        record["post_review"],
        name="post_review",
        fields={"status", "selected", "candidate_id", "point"},
    )
    if post["status"] not in {"not_reviewed", "reviewed", "review_required", "rejected"}:
        raise ValueError("post_review.status is invalid")
    selection = _validate_selection(
        {key: post[key] for key in ("selected", "candidate_id", "point")},
        name="post_review",
    )
    record["post_review"] = {"status": post["status"], **selection}
    vista = _closed_object(
        record["vista"],
        name="vista",
        fields={
            "status",
            "candidate_id",
            "candidate_bbox_ref",
            "roi_ref",
            "affine_transform_ref",
            "canonical_point",
        },
    )
    if vista["status"] not in {
        "not_requested",
        "succeeded",
        "failed",
        "review_required",
        "out_of_bounds",
        "transform_invalid",
    }:
        raise ValueError("vista.status is invalid")
    if record["arm_id"] != "omni_to_qwen_vista" and vista["status"] != "not_requested":
        raise ValueError("pre-VISTA arm cannot contain a VISTA result")
    if vista["candidate_id"] is not None:
        _non_empty_string(vista["candidate_id"], name="vista.candidate_id")
    for field in ("candidate_bbox_ref", "roi_ref", "affine_transform_ref"):
        if vista[field] is not None:
            vista[field] = _validate_ref(vista[field], name=f"vista.{field}")
    if vista["canonical_point"] is not None:
        vista["canonical_point"] = _point(vista["canonical_point"], name="vista.canonical_point")
    if not isinstance(record["provider_evidence_refs"], list):
        raise ValueError("provider_evidence_refs must be a list")
    record["provider_evidence_refs"] = [
        _validate_ref(value, name="provider_evidence_ref")
        for value in record["provider_evidence_refs"]
    ]
    if record["cleanup_evidence_ref"] is not None:
        record["cleanup_evidence_ref"] = _validate_ref(
            record["cleanup_evidence_ref"], name="cleanup_evidence_ref"
        )
    if contains_gold_fields(record):
        raise ValueError("prediction contains scorer-private fields")
    return record


def _validate_arms(
    value: Any, *, shared_budget: dict[str, Any], shared_context: dict[str, Any]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("arms must be a list")
    arms: list[dict[str, Any]] = []
    statistical_signatures: set[str] = set()
    arm_ids: list[str] = []
    for index, item in enumerate(value):
        arm_fields = {"arm_id", "phase", "producer_stages", "budget", "context_policy"}
        if isinstance(item, Mapping) and "statistical_identity_sha256" in item:
            arm_fields.add("statistical_identity_sha256")
        arm = _closed_object(
            item,
            name=f"arms[{index}]",
            fields=arm_fields,
        )
        arm_id = _non_empty_string(arm["arm_id"], name=f"arms[{index}].arm_id")
        arm_ids.append(arm_id)
        budget = _validate_budget(arm["budget"], name=f"arms[{index}].budget")
        if budget != shared_budget:
            raise ValueError("all statistical arms must use equal budgets")
        context = _validate_context_policy(
            arm["context_policy"], name=f"arms[{index}].context_policy"
        )
        if arm_id != "omni_only_discovery" and context != shared_context:
            raise ValueError("all non-Omni arms must use the shared UIA/OCR context policy")
        if not isinstance(arm["producer_stages"], list) or not all(
            isinstance(stage, str) and stage for stage in arm["producer_stages"]
        ):
            raise ValueError("producer_stages must be a non-empty string list")
        signature = hashlib.sha256(
            canonical_json_bytes(
                {
                    "phase": arm["phase"],
                    "producer_stages": arm["producer_stages"],
                    "budget": budget,
                    "context_policy": context,
                }
            )
        ).hexdigest()
        if signature in statistical_signatures:
            raise ValueError("duplicate statistical arm")
        statistical_signatures.add(signature)
        if "statistical_identity_sha256" in arm and arm["statistical_identity_sha256"] != signature:
            raise ValueError(f"statistical arm identity mismatch: {arm_id}")
        arms.append(
            {
                "arm_id": arm_id,
                "phase": arm["phase"],
                "producer_stages": deepcopy(arm["producer_stages"]),
                "budget": budget,
                "context_policy": context,
                "statistical_identity_sha256": signature,
            }
        )
    if arm_ids != list(ARM_IDS):
        raise ValueError(f"arms must be ordered exactly as {list(ARM_IDS)}")
    for arm in arms:
        expected_phase, expected_stages = _ARM_DEFINITIONS[arm["arm_id"]]
        if arm["phase"] != expected_phase or arm["producer_stages"] != expected_stages:
            raise ValueError(f"arm definition mismatch: {arm['arm_id']}")
    return arms


def _validate_and_seal_cases(value: Any, *, root_path: Path) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("cases must be a non-empty list")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        case = _closed_object(
            item,
            name=f"cases[{index}]",
            fields={"case_id", "partition", "image_path", "goal", "gold"},
        )
        case_id = _non_empty_string(case["case_id"], name=f"cases[{index}].case_id")
        if case_id in seen:
            raise ValueError("duplicate case_id")
        seen.add(case_id)
        if case["partition"] not in {"regression", "holdout"}:
            raise ValueError("case partition must be regression or holdout")
        image_path = _safe_relative_path(case["image_path"], name="case.image_path")
        goal = _non_empty_string(case["goal"], name="case.goal")
        gold = _validate_gold(case["gold"], name=f"cases[{index}].gold")
        results.append(
            {
                "case_id": case_id,
                "partition": case["partition"],
                "image_path": image_path,
                "image_sha256": _sha256_file(_resolve_inside(root_path, image_path)),
                "goal": goal,
                "gold": gold,
                "gold_sha256": _mapping_sha(gold),
            }
        )
    return results


def _validate_sealed_cases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("cases must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(value):
        case = _closed_object(
            item,
            name=f"cases[{index}]",
            fields={
                "case_id",
                "partition",
                "image_path",
                "image_sha256",
                "goal",
                "gold",
                "gold_sha256",
            },
        )
        case_id = _non_empty_string(case["case_id"], name="case_id")
        if case_id in seen:
            raise ValueError("duplicate case_id")
        seen.add(case_id)
        if case["partition"] not in {"regression", "holdout"}:
            raise ValueError("case partition must be regression or holdout")
        _safe_relative_path(case["image_path"], name="image_path")
        _sha256(case["image_sha256"], name="image_sha256")
        _non_empty_string(case["goal"], name="goal")
        gold = _validate_gold(case["gold"], name="gold")
        if _sha256(case["gold_sha256"], name="gold_sha256") != _mapping_sha(gold):
            raise ValueError(f"gold_sha256 mismatch: {case_id}")
    return deepcopy(value)


def _validate_gold(value: Any, *, name: str) -> dict[str, Any]:
    gold = _closed_object(
        value,
        name=name,
        fields={
            "acceptable_candidate_ids",
            "acceptable_regions",
            "annotator_identity_hash",
            "reviewer_identity_hash",
            "acceptable_region_disagreement",
        },
    )
    if not isinstance(gold["acceptable_candidate_ids"], list) or not all(
        isinstance(candidate_id, str) and candidate_id
        for candidate_id in gold["acceptable_candidate_ids"]
    ):
        raise ValueError(f"{name}.acceptable_candidate_ids must be a string list")
    if not isinstance(gold["acceptable_regions"], list) or not gold["acceptable_regions"]:
        raise ValueError(f"{name}.acceptable_regions must be non-empty")
    gold["acceptable_regions"] = [
        _bbox(region, name=f"{name}.acceptable_regions")
        for region in gold["acceptable_regions"]
    ]
    _sha256(gold["annotator_identity_hash"], name=f"{name}.annotator_identity_hash")
    _sha256(gold["reviewer_identity_hash"], name=f"{name}.reviewer_identity_hash")
    if gold["annotator_identity_hash"] == gold["reviewer_identity_hash"]:
        raise ValueError("annotator and reviewer identities must be independent")
    if gold["acceptable_region_disagreement"] not in {
        "none",
        "resolved_by_independent_review",
        "retained_as_multiple_acceptable_regions",
    }:
        raise ValueError(f"{name}.acceptable_region_disagreement is invalid")
    return gold


def _validate_budget(value: Any, *, name: str) -> dict[str, int]:
    budget = _closed_object(
        value,
        name=name,
        fields={
            "max_provider_calls_per_case",
            "max_output_tokens_per_case",
            "max_wall_time_ms_per_case",
        },
    )
    for field, child in budget.items():
        if isinstance(child, bool) or not isinstance(child, int) or child <= 0:
            raise ValueError(f"{name}.{field} must be a positive integer")
    return budget


def _validate_context_policy(value: Any, *, name: str) -> dict[str, str]:
    policy = _closed_object(
        value, name=name, fields={"policy_version", "uia", "ocr"}
    )
    _non_empty_string(policy["policy_version"], name=f"{name}.policy_version")
    for field in ("uia", "ocr"):
        if policy[field] not in {"same_capture_optional", "same_capture_required", "disabled"}:
            raise ValueError(f"{name}.{field} is invalid")
    return policy


def _validate_selection(value: Any, *, name: str) -> dict[str, Any]:
    selection = _closed_object(
        value, name=name, fields={"selected", "candidate_id", "point"}
    )
    if not isinstance(selection["selected"], bool):
        raise ValueError(f"{name}.selected must be a boolean")
    if selection["selected"]:
        _non_empty_string(selection["candidate_id"], name=f"{name}.candidate_id")
        selection["point"] = _point(selection["point"], name=f"{name}.point")
    elif selection["candidate_id"] is not None or selection["point"] is not None:
        raise ValueError(f"{name} unselected record cannot carry candidate or point")
    return selection


def _closed_object(value: Any, *, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = deepcopy(dict(value))
    actual = set(result)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        detail = []
        if missing:
            detail.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            detail.append(f"unknown fields: {', '.join(unknown)}")
        raise ValueError(f"{name} is not closed ({'; '.join(detail)})")
    return result


def _validate_ref(value: Any, *, name: str) -> dict[str, str]:
    reference = _closed_object(value, name=name, fields={"id", "content_sha256"})
    _non_empty_string(reference["id"], name=f"{name}.id")
    _sha256(reference["content_sha256"], name=f"{name}.content_sha256")
    return reference


def _bbox(value: Any, *, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must contain xyxy boxes")
    result = [_finite_number(child, name=name) for child in value]
    if result[0] >= result[2] or result[1] >= result[3]:
        raise ValueError(f"{name} must use x1 < x2 and y1 < y2")
    return result


def _point(value: Any, *, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be an xy point")
    return [_finite_number(child, name=name) for child in value]


def _finite_number(value: Any, *, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must contain finite numbers")
    return value


def _non_empty_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha256(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _mapping_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _safe_relative_path(value: Any, *, name: str) -> str:
    path = _non_empty_string(value, name=name).replace("\\", "/")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{name} must be a repository-relative path")
    return path


def _resolve_inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError("sealed path escapes benchmark root")
    return target


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"sealed file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_non_authorizing(value: Mapping[str, Any], *, name: str) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) is not expected:
            raise ValueError(f"{name} violates non-authorizing invariant: {field}")


__all__ = [
    "ARM_IDS",
    "PRE_VISTA_ARM_IDS",
    "build_prediction_request",
    "canonical_json_bytes",
    "contains_gold_fields",
    "content_sha256",
    "provider_manifest_projection",
    "seal_benchmark_manifest",
    "validate_prediction_record",
    "verify_benchmark_manifest",
]
