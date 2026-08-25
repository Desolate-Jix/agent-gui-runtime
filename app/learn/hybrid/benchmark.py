"""Immutable Portfolio Hybrid v1.1 benchmark, run and prediction contracts."""

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
PREDICTION_RUN_CONTRACT = "portfolio_hybrid_v1_1_prediction_run_v1"
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
_PRIVATE_FIELD_MARKERS = (
    "gold",
    "expected",
    "acceptable",
    "annotator",
    "reviewer",
    "scorer_only",
    "private_evidence",
    "ground_truth",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}
_VERIFIED_FILE_CACHE: dict[tuple[str, str], tuple[int, int, str]] = {}
_VERIFIED_MANIFESTS: set[str] = set()


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError(f"value is not canonical JSON: {error}") from error


def content_sha256(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("content_sha256", None)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def contains_gold_fields(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold())
            if any(marker in normalized for marker in _PRIVATE_FIELD_MARKERS):
                return True
            if contains_gold_fields(child):
                return True
    elif isinstance(value, list):
        return any(contains_gold_fields(child) for child in value)
    return False


def seal_benchmark_manifest(
    manifest: Mapping[str, Any], *, root: str | Path
) -> dict[str, Any]:
    template = _closed(
        manifest,
        "benchmark manifest template",
        {
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
    _string(template["benchmark_id"], "benchmark_id")
    _string(template["corpus_id"], "corpus_id")
    root_path = Path(root).resolve()
    artifact_paths = _closed(template["artifact_paths"], "artifact_paths", _ARTIFACT_NAMES)
    artifact_seals: dict[str, dict[str, str]] = {}
    for name in sorted(_ARTIFACT_NAMES):
        relative = _relative(artifact_paths[name], f"artifact_paths.{name}")
        artifact_seals[name] = {
            "path": relative,
            "sha256": _file_sha(_inside(root_path, relative)),
        }
    revisions = _closed(
        template["provider_revisions"], "provider_revisions", {"omni", "qwen", "vista"}
    )
    for provider_id, revision in revisions.items():
        _string(revision, f"provider_revisions.{provider_id}")
    budget = _budget(template["shared_budget"], "shared_budget")
    context = _context(template["shared_context_policy"], "shared_context_policy")
    arms = _arms(template["arms"], budget, context)
    cases = _seal_cases(template["cases"], root_path)
    coverage = _corpus_coverage(cases)
    evidence_policy = _closed(
        template["evidence_policy"], "evidence_policy", {"public", "private"}
    )
    if evidence_policy != {
        "public": "aggregate_metrics_only",
        "private": "case_level_gold_and_predictions",
    }:
        raise ValueError("evidence_policy must separate public and private evidence")
    sealed = {
        "contract_version": MANIFEST_CONTRACT,
        "benchmark_id": template["benchmark_id"],
        "corpus_id": template["corpus_id"],
        "artifact_seals": artifact_seals,
        "provider_revisions": revisions,
        "provider_revisions_sha256": _hash(revisions),
        "shared_budget": budget,
        "shared_budget_sha256": _hash(budget),
        "shared_context_policy": context,
        "shared_context_policy_sha256": _hash(context),
        "arms": arms,
        "cases": cases,
        "corpus_coverage": coverage,
        "evidence_policy": evidence_policy,
        **_NON_AUTHORIZING,
    }
    sealed["content_sha256"] = content_sha256(sealed)
    return verify_benchmark_manifest(sealed, root=root_path)


def verify_benchmark_manifest(
    manifest: Mapping[str, Any], *, root: str | Path | None = None
) -> dict[str, Any]:
    sealed = _closed(
        manifest,
        "sealed benchmark manifest",
        {
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
            "corpus_coverage",
            "evidence_policy",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if sealed["contract_version"] != MANIFEST_CONTRACT:
        raise ValueError(f"contract_version must be {MANIFEST_CONTRACT}")
    _non_authorizing(sealed, "sealed benchmark manifest")
    declared_manifest_sha = _sha(sealed["content_sha256"], "content_sha256")
    if declared_manifest_sha != content_sha256(sealed):
        raise ValueError("benchmark manifest content_sha256 mismatch")
    if declared_manifest_sha in _VERIFIED_MANIFESTS:
        _verify_current_manifest_files(sealed, root)
        return sealed
    revisions = _closed(
        sealed["provider_revisions"], "provider_revisions", {"omni", "qwen", "vista"}
    )
    if _sha(sealed["provider_revisions_sha256"], "provider_revisions_sha256") != _hash(revisions):
        raise ValueError("provider_revisions_sha256 mismatch")
    budget = _budget(sealed["shared_budget"], "shared_budget")
    if _sha(sealed["shared_budget_sha256"], "shared_budget_sha256") != _hash(budget):
        raise ValueError("shared_budget_sha256 mismatch")
    context = _context(sealed["shared_context_policy"], "shared_context_policy")
    if _sha(sealed["shared_context_policy_sha256"], "shared_context_policy_sha256") != _hash(context):
        raise ValueError("shared_context_policy_sha256 mismatch")
    _arms(sealed["arms"], budget, context)
    _validate_sealed_cases(sealed["cases"])
    if sealed["corpus_coverage"] != _corpus_coverage(sealed["cases"]):
        raise ValueError("corpus_coverage mismatch")
    artifacts = _closed(sealed["artifact_seals"], "artifact_seals", _ARTIFACT_NAMES)
    for name, value in artifacts.items():
        item = _closed(value, f"artifact_seals.{name}", {"path", "sha256"})
        _relative(item["path"], f"artifact_seals.{name}.path")
        _sha(item["sha256"], f"artifact_seals.{name}.sha256")
    _VERIFIED_MANIFESTS.add(declared_manifest_sha)
    _verify_current_manifest_files(sealed, root)
    return sealed


def seal_prediction_run(
    sealed_manifest: Mapping[str, Any], *, run_id: str, partition: str, root: str | Path
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest, root=root)
    _string(run_id, "run_id")
    if partition not in {"regression", "holdout"}:
        raise ValueError("prediction run partition must be regression or holdout")
    case_ids = sorted(
        case["case_id"] for case in manifest["cases"] if case["partition"] == partition
    )
    if not case_ids:
        raise ValueError("prediction run partition has no sealed cases")
    run = {
        "contract_version": PREDICTION_RUN_CONTRACT,
        "run_id": run_id,
        "benchmark_ref": _benchmark_ref(manifest),
        "partition": partition,
        "artifact_seals": deepcopy(manifest["artifact_seals"]),
        "provider_revisions": deepcopy(manifest["provider_revisions"]),
        "provider_revisions_sha256": manifest["provider_revisions_sha256"],
        "budget": deepcopy(manifest["shared_budget"]),
        "budget_sha256": manifest["shared_budget_sha256"],
        "context_policy": deepcopy(manifest["shared_context_policy"]),
        "context_policy_sha256": manifest["shared_context_policy_sha256"],
        "arm_identities": {
            arm["arm_id"]: arm["statistical_identity_sha256"] for arm in manifest["arms"]
        },
        "case_ids": case_ids,
        **_NON_AUTHORIZING,
    }
    run["content_sha256"] = content_sha256(run)
    return verify_prediction_run(run, manifest)


def verify_prediction_run(
    prediction_run: Mapping[str, Any], sealed_manifest: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest)
    run = _closed(
        prediction_run,
        "prediction run",
        {
            "contract_version",
            "run_id",
            "benchmark_ref",
            "partition",
            "artifact_seals",
            "provider_revisions",
            "provider_revisions_sha256",
            "budget",
            "budget_sha256",
            "context_policy",
            "context_policy_sha256",
            "arm_identities",
            "case_ids",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if run["contract_version"] != PREDICTION_RUN_CONTRACT:
        raise ValueError("prediction run contract_version mismatch")
    _non_authorizing(run, "prediction run")
    if _sha(run["content_sha256"], "prediction run content_sha256") != content_sha256(run):
        raise ValueError("prediction run content_sha256 mismatch")
    _string(run["run_id"], "prediction run run_id")
    if _ref(run["benchmark_ref"], "prediction run benchmark_ref") != _benchmark_ref(manifest):
        raise ValueError("prediction run benchmark_ref mismatch")
    if run["partition"] not in {"regression", "holdout"}:
        raise ValueError("prediction run partition is invalid")
    expected_cases = sorted(
        case["case_id"] for case in manifest["cases"] if case["partition"] == run["partition"]
    )
    expected_arms = {
        arm["arm_id"]: arm["statistical_identity_sha256"] for arm in manifest["arms"]
    }
    comparisons = (
        ("artifact seals", run["artifact_seals"], manifest["artifact_seals"]),
        ("provider revisions", run["provider_revisions"], manifest["provider_revisions"]),
        ("provider revisions SHA", run["provider_revisions_sha256"], manifest["provider_revisions_sha256"]),
        ("budget", run["budget"], manifest["shared_budget"]),
        ("budget SHA", run["budget_sha256"], manifest["shared_budget_sha256"]),
        ("context policy", run["context_policy"], manifest["shared_context_policy"]),
        ("context policy SHA", run["context_policy_sha256"], manifest["shared_context_policy_sha256"]),
        ("statistical arm identities", run["arm_identities"], expected_arms),
        ("case IDs", run["case_ids"], expected_cases),
    )
    for label, actual, expected in comparisons:
        if actual != expected:
            raise ValueError(f"prediction run {label} mismatch")
    return run


def provider_manifest_projection(
    sealed_manifest: Mapping[str, Any], arm_id: str | None = None, *, root: str | Path
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest, root=root)
    arms = manifest["arms"]
    if arm_id is not None:
        arms = [arm for arm in arms if arm["arm_id"] == arm_id]
        if len(arms) != 1:
            raise ValueError(f"unknown arm_id: {arm_id}")
    projection = {
        "contract_version": PROJECTION_CONTRACT,
        "benchmark_ref": _benchmark_ref(manifest),
        "corpus_id": manifest["corpus_id"],
        "provider_revisions": deepcopy(manifest["provider_revisions"]),
        "shared_budget": deepcopy(manifest["shared_budget"]),
        "shared_context_policy": deepcopy(manifest["shared_context_policy"]),
        "arms": deepcopy(arms),
        "cases": [
            {
                "case_id": case["case_id"],
                "partition": case["partition"],
                "image_ref": {"path": case["image_path"], "sha256": case["image_sha256"]},
                "goal": case["goal"],
            }
            for case in manifest["cases"]
        ],
        **_NON_AUTHORIZING,
    }
    if contains_gold_fields(projection):
        raise ValueError("provider projection contains scorer-private fields")
    return projection


def build_prediction_request(
    sealed_manifest: Mapping[str, Any],
    arm_id: str,
    case_id: str,
    *,
    root: str | Path,
    prediction_run: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest, root=root)
    run = verify_prediction_run(prediction_run, manifest)
    arms = [arm for arm in manifest["arms"] if arm["arm_id"] == arm_id]
    cases = [case for case in manifest["cases"] if case["case_id"] == case_id]
    if len(arms) != 1:
        raise ValueError(f"unknown arm_id: {arm_id}")
    if len(cases) != 1 or cases[0]["partition"] != run["partition"] or case_id not in run["case_ids"]:
        raise ValueError(f"case_id is not in prediction run: {case_id}")
    arm = arms[0]
    safe_case = {
        "case_id": cases[0]["case_id"],
        "partition": cases[0]["partition"],
        "image_ref": {"path": cases[0]["image_path"], "sha256": cases[0]["image_sha256"]},
        "goal": cases[0]["goal"],
    }
    required_provider_ids = list(arm["producer_stages"])
    request_identity = {
        "run_ref": _run_ref(run),
        "arm_id": arm_id,
        "case_id": case_id,
        "statistical_identity_sha256": arm["statistical_identity_sha256"],
    }
    request = {
        "contract_version": PREDICTION_REQUEST_CONTRACT,
        "request_id": "request/" + hashlib.sha256(canonical_json_bytes(request_identity)).hexdigest(),
        "benchmark_ref": _benchmark_ref(manifest),
        "run_ref": _run_ref(run),
        "arm_id": arm_id,
        "statistical_identity_sha256": arm["statistical_identity_sha256"],
        "case": safe_case,
        "producer_stages": deepcopy(arm["producer_stages"]),
        "required_provider_ids": required_provider_ids,
        "producer_artifact_ref": deepcopy(manifest["artifact_seals"]["benchmark_producer"]),
        "provider_revisions": deepcopy(manifest["provider_revisions"]),
        "provider_revisions_sha256": manifest["provider_revisions_sha256"],
        "budget": deepcopy(arm["budget"]),
        "budget_sha256": manifest["shared_budget_sha256"],
        "context_policy": deepcopy(arm["context_policy"]),
        "context_policy_sha256": manifest["shared_context_policy_sha256"],
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
    request["content_sha256"] = content_sha256(request)
    return validate_prediction_request(request, manifest, run)


def validate_prediction_request(
    value: Mapping[str, Any],
    sealed_manifest: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest)
    run = verify_prediction_run(prediction_run, manifest)
    request = _closed(
        value,
        "prediction request",
        {
            "contract_version",
            "request_id",
            "benchmark_ref",
            "run_ref",
            "arm_id",
            "statistical_identity_sha256",
            "case",
            "producer_stages",
            "required_provider_ids",
            "producer_artifact_ref",
            "provider_revisions",
            "provider_revisions_sha256",
            "budget",
            "budget_sha256",
            "context_policy",
            "context_policy_sha256",
            "vista_payload",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if request["contract_version"] != PREDICTION_REQUEST_CONTRACT:
        raise ValueError("prediction request contract_version mismatch")
    _non_authorizing(request, "prediction request")
    if _sha(request["content_sha256"], "prediction request content_sha256") != content_sha256(request):
        raise ValueError("prediction request content_sha256 mismatch")
    if _ref(request["benchmark_ref"], "request benchmark_ref") != _benchmark_ref(manifest):
        raise ValueError("prediction request benchmark_ref mismatch")
    if _ref(request["run_ref"], "request run_ref") != _run_ref(run):
        raise ValueError("prediction request run_ref mismatch")
    arm_by_id = {arm["arm_id"]: arm for arm in manifest["arms"]}
    arm = arm_by_id.get(request["arm_id"])
    if arm is None:
        raise ValueError("prediction request arm_id mismatch")
    case_by_id = {case["case_id"]: case for case in manifest["cases"]}
    case = case_by_id.get(request["case"].get("case_id") if isinstance(request["case"], Mapping) else None)
    if case is None or case["partition"] != run["partition"]:
        raise ValueError("prediction request case mismatch")
    expected_case = {
        "case_id": case["case_id"],
        "partition": case["partition"],
        "image_ref": {"path": case["image_path"], "sha256": case["image_sha256"]},
        "goal": case["goal"],
    }
    expected = {
        "statistical_identity_sha256": arm["statistical_identity_sha256"],
        "producer_stages": arm["producer_stages"],
        "required_provider_ids": arm["producer_stages"],
        "producer_artifact_ref": manifest["artifact_seals"]["benchmark_producer"],
        "provider_revisions": manifest["provider_revisions"],
        "provider_revisions_sha256": manifest["provider_revisions_sha256"],
        "budget": arm["budget"],
        "budget_sha256": manifest["shared_budget_sha256"],
        "context_policy": arm["context_policy"],
        "context_policy_sha256": manifest["shared_context_policy_sha256"],
        "case": expected_case,
    }
    for field, expected_value in expected.items():
        if request[field] != expected_value:
            raise ValueError(f"prediction request {field} mismatch")
    identity = {
        "run_ref": _run_ref(run),
        "arm_id": request["arm_id"],
        "case_id": case["case_id"],
        "statistical_identity_sha256": arm["statistical_identity_sha256"],
    }
    if request["request_id"] != "request/" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest():
        raise ValueError("prediction request request_id mismatch")
    vista = request["vista_payload"]
    if not isinstance(vista, Mapping) or vista.get("enabled") is not (request["arm_id"] == "omni_to_qwen_vista"):
        raise ValueError("prediction request VISTA payload mismatch")
    if contains_gold_fields(request):
        raise ValueError("prediction request contains scorer-private fields")
    return request


def validate_prediction_record(
    value: Mapping[str, Any],
    sealed_manifest: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
    prediction_request: Mapping[str, Any],
    lifecycle_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest)
    run = verify_prediction_run(prediction_run, manifest)
    request = validate_prediction_request(prediction_request, manifest, run)
    record = _closed(
        value,
        "prediction",
        {
            "contract_version",
            "benchmark_ref",
            "run_ref",
            "request_ref",
            "arm_id",
            "statistical_identity_sha256",
            "case_id",
            "partition",
            "producer_artifact_ref",
            "provider_revisions_sha256",
            "budget_sha256",
            "context_policy_sha256",
            "pre_review",
            "post_review",
            "vista",
            "provider_evidence",
            "cleanup_evidence_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if record["contract_version"] != PREDICTION_CONTRACT:
        raise ValueError("prediction contract_version mismatch")
    _non_authorizing(record, "prediction")
    if _sha(record["content_sha256"], "prediction content_sha256") != content_sha256(record):
        raise ValueError("prediction content_sha256 mismatch")
    expected_fields = {
        "benchmark_ref": request["benchmark_ref"],
        "run_ref": request["run_ref"],
        "request_ref": {"id": request["request_id"], "content_sha256": request["content_sha256"]},
        "arm_id": request["arm_id"],
        "statistical_identity_sha256": request["statistical_identity_sha256"],
        "case_id": request["case"]["case_id"],
        "partition": request["case"]["partition"],
        "producer_artifact_ref": request["producer_artifact_ref"],
        "provider_revisions_sha256": request["provider_revisions_sha256"],
        "budget_sha256": request["budget_sha256"],
        "context_policy_sha256": request["context_policy_sha256"],
    }
    labels = {"statistical_identity_sha256": "statistical identity"}
    for field, expected in expected_fields.items():
        if record[field] != expected:
            raise ValueError(f"prediction {labels.get(field, field)} mismatch")
    record["pre_review"] = _selection(record["pre_review"], "pre_review")
    post = _closed(record["post_review"], "post_review", {"status", "selected", "candidate_id", "point"})
    if post["status"] not in {"approved", "not_reviewed", "review_required", "rejected"}:
        raise ValueError("post_review status is invalid")
    post_selection = _selection(
        {key: post[key] for key in ("selected", "candidate_id", "point")}, "post_review"
    )
    record["post_review"] = {"status": post["status"], **post_selection}
    record["vista"] = _vista(record["vista"], is_vista=record["arm_id"] == "omni_to_qwen_vista")
    evidence = record["provider_evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("prediction provider evidence is required")
    provider_ids: list[str] = []
    for index, item in enumerate(evidence):
        child = _closed(item, f"provider_evidence[{index}]", {"provider_id", "evidence_ref"})
        provider_ids.append(_string(child["provider_id"], "provider evidence provider_id"))
        _ref(child["evidence_ref"], "provider evidence ref")
    if provider_ids != request["required_provider_ids"] or len(provider_ids) != len(set(provider_ids)):
        raise ValueError("prediction provider evidence does not match request providers")
    lifecycle_ref = {
        "id": lifecycle_evidence.get("evidence_id"),
        "content_sha256": lifecycle_evidence.get("content_sha256"),
    }
    if record["cleanup_evidence_ref"] != lifecycle_ref:
        raise ValueError("prediction cleanup_evidence_ref mismatch")
    if contains_gold_fields(record):
        raise ValueError("prediction contains scorer-private fields")
    return record


def _seal_cases(value: Any, root: Path) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("cases must be a list")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    image_seals: dict[str, str] = {}
    image_reviews: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(value):
        case = _closed(
            item,
            f"cases[{index}]",
            {"case_id", "partition", "image_path", "image_review", "goal", "gold"},
        )
        case_id = _string(case["case_id"], "case_id")
        if case_id in seen:
            raise ValueError("duplicate case_id")
        seen.add(case_id)
        if case["partition"] not in {"regression", "holdout"}:
            raise ValueError("case partition must be regression or holdout")
        image_path = _relative(case["image_path"], "image_path")
        image_sha = _file_sha(_inside(root, image_path))
        image_review = _image_review(case["image_review"])
        if image_path in image_seals and image_seals[image_path] != image_sha:
            raise ValueError("conflicting image seal")
        if image_path in image_reviews and image_reviews[image_path] != image_review:
            raise ValueError("conflicting image review")
        image_seals[image_path] = image_sha
        image_reviews[image_path] = image_review
        gold = _gold(case["gold"], f"cases[{index}].gold")
        results.append(
            {
                "case_id": case_id,
                "partition": case["partition"],
                "image_path": image_path,
                "image_sha256": image_sha,
                "image_review": image_review,
                "goal": _string(case["goal"], "goal"),
                "gold": gold,
                "gold_sha256": _hash(gold),
            }
        )
    return results


def _validate_sealed_cases(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("cases must be a list")
    seen: set[str] = set()
    for item in value:
        case = _closed(
            item,
            "sealed case",
            {"case_id", "partition", "image_path", "image_sha256", "image_review", "goal", "gold", "gold_sha256"},
        )
        case_id = _string(case["case_id"], "case_id")
        if case_id in seen:
            raise ValueError("duplicate case_id")
        seen.add(case_id)
        if case["partition"] not in {"regression", "holdout"}:
            raise ValueError("case partition must be regression or holdout")
        _relative(case["image_path"], "image_path")
        _sha(case["image_sha256"], "image_sha256")
        _image_review(case["image_review"])
        _string(case["goal"], "goal")
        gold = _gold(case["gold"], "gold")
        if _sha(case["gold_sha256"], "gold_sha256") != _hash(gold):
            raise ValueError(f"gold_sha256 mismatch: {case_id}")
    return deepcopy(value)


def _corpus_coverage(cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    target_count = len(cases)
    if not 100 <= target_count <= 200:
        raise ValueError("sealed corpus must contain 100 to 200 important targets")
    paths = {case["image_path"] for case in cases}
    hashes = {case["image_sha256"] for case in cases}
    if not 20 <= len(paths) <= 30 or len(paths) != len(hashes):
        raise ValueError("sealed corpus must contain 20 to 30 distinct screenshots")
    partition_target_counts = {
        partition: sum(case["partition"] == partition for case in cases)
        for partition in ("holdout", "regression")
    }
    partition_image_counts = {
        partition: len({case["image_path"] for case in cases if case["partition"] == partition})
        for partition in ("holdout", "regression")
    }
    if any(count <= 0 for count in (*partition_target_counts.values(), *partition_image_counts.values())):
        raise ValueError("sealed corpus must cover regression and holdout partitions")
    image_review_complete = all(
        case["image_review"]["review_status"] == "approved"
        and case["image_review"]["privacy_review_status"] == "approved"
        for case in cases
    )
    target_review_complete = all(
        case["gold"]["review_status"] == "approved"
        and case["gold"]["important_target"] is True
        for case in cases
    )
    if not image_review_complete:
        raise ValueError("sealed corpus image review is incomplete")
    if not target_review_complete:
        if any(case["gold"]["important_target"] is not True for case in cases):
            raise ValueError("sealed corpus contains a non-important target")
        raise ValueError("sealed corpus target review is incomplete")
    return {
        "distinct_image_count": len(paths),
        "target_count": target_count,
        "partition_image_counts": partition_image_counts,
        "partition_target_counts": partition_target_counts,
        "image_review_complete": image_review_complete,
        "target_review_complete": target_review_complete,
    }


def _image_review(value: Any) -> dict[str, Any]:
    review = _closed(
        value,
        "image_review",
        {"reviewer_identity_hash", "review_status", "privacy_review_status"},
    )
    _sha(review["reviewer_identity_hash"], "image reviewer_identity_hash")
    if review["review_status"] != "approved" or review["privacy_review_status"] != "approved":
        raise ValueError("image review must be approved and privacy complete")
    return review


def _gold(value: Any, name: str) -> dict[str, Any]:
    gold = _closed(
        value,
        name,
        {
            "acceptable_candidate_ids",
            "acceptable_regions",
            "annotator_identity_hash",
            "reviewer_identity_hash",
            "acceptable_region_disagreement",
            "review_status",
            "important_target",
        },
    )
    if not isinstance(gold["acceptable_candidate_ids"], list) or not all(
        isinstance(item, str) and item for item in gold["acceptable_candidate_ids"]
    ):
        raise ValueError(f"{name}.acceptable_candidate_ids must be a string list")
    if not isinstance(gold["acceptable_regions"], list) or not gold["acceptable_regions"]:
        raise ValueError(f"{name}.acceptable_regions must be non-empty")
    gold["acceptable_regions"] = [_bbox(item, name) for item in gold["acceptable_regions"]]
    _sha(gold["annotator_identity_hash"], f"{name}.annotator_identity_hash")
    _sha(gold["reviewer_identity_hash"], f"{name}.reviewer_identity_hash")
    if gold["annotator_identity_hash"] == gold["reviewer_identity_hash"]:
        raise ValueError("annotator and reviewer identities must be independent")
    if gold["acceptable_region_disagreement"] not in {
        "none",
        "resolved_by_independent_review",
        "retained_as_multiple_acceptable_regions",
    }:
        raise ValueError("acceptable region disagreement is invalid")
    if gold["review_status"] != "approved":
        raise ValueError("target review must be approved")
    if gold["important_target"] is not True:
        raise ValueError("case must be an independently reviewed important target")
    return gold


def _arms(value: Any, budget: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("arms must be a list")
    results: list[dict[str, Any]] = []
    signatures: set[str] = set()
    ids: list[str] = []
    for index, item in enumerate(value):
        fields = {"arm_id", "phase", "producer_stages", "budget", "context_policy"}
        if isinstance(item, Mapping) and "statistical_identity_sha256" in item:
            fields.add("statistical_identity_sha256")
        arm = _closed(item, f"arms[{index}]", fields)
        arm_id = _string(arm["arm_id"], "arm_id")
        ids.append(arm_id)
        arm_budget = _budget(arm["budget"], "arm budget")
        if arm_budget != budget:
            raise ValueError("all statistical arms must use equal budgets")
        arm_context = _context(arm["context_policy"], "arm context_policy")
        if arm_id != "omni_only_discovery" and arm_context != context:
            raise ValueError("all non-Omni arms must use the shared UIA/OCR context policy")
        signature = _hash(
            {"producer_stages": arm["producer_stages"], "budget": arm_budget, "context_policy": arm_context}
        )
        if signature in signatures:
            raise ValueError("duplicate statistical arm")
        signatures.add(signature)
        if "statistical_identity_sha256" in arm and arm["statistical_identity_sha256"] != signature:
            raise ValueError("statistical arm identity mismatch")
        results.append(
            {
                "arm_id": arm_id,
                "phase": arm["phase"],
                "producer_stages": deepcopy(arm["producer_stages"]),
                "budget": arm_budget,
                "context_policy": arm_context,
                "statistical_identity_sha256": signature,
            }
        )
    if ids != list(ARM_IDS):
        raise ValueError(f"arms must be ordered exactly as {list(ARM_IDS)}")
    for arm in results:
        phase, stages = _ARM_DEFINITIONS[arm["arm_id"]]
        if arm["phase"] != phase or arm["producer_stages"] != stages:
            raise ValueError(f"arm definition mismatch: {arm['arm_id']}")
    return results


def _budget(value: Any, name: str) -> dict[str, int]:
    budget = _closed(
        value,
        name,
        {"max_provider_calls_per_case", "max_output_tokens_per_case", "max_wall_time_ms_per_case"},
    )
    for field, child in budget.items():
        if isinstance(child, bool) or not isinstance(child, int) or child <= 0:
            raise ValueError(f"{name}.{field} must be a positive integer")
    return budget


def _context(value: Any, name: str) -> dict[str, str]:
    policy = _closed(value, name, {"policy_version", "uia", "ocr"})
    _string(policy["policy_version"], f"{name}.policy_version")
    for field in ("uia", "ocr"):
        if policy[field] not in {"same_capture_optional", "same_capture_required", "disabled"}:
            raise ValueError(f"{name}.{field} is invalid")
    return policy


def _selection(value: Any, name: str) -> dict[str, Any]:
    selection = _closed(value, name, {"selected", "candidate_id", "point"})
    if not isinstance(selection["selected"], bool):
        raise ValueError(f"{name}.selected must be a boolean")
    if selection["selected"]:
        _string(selection["candidate_id"], f"{name}.candidate_id")
        selection["point"] = _point(selection["point"], f"{name}.point")
    elif selection["candidate_id"] is not None or selection["point"] is not None:
        raise ValueError(f"{name} unselected record cannot carry candidate or point")
    return selection


def _vista(value: Any, *, is_vista: bool) -> dict[str, Any]:
    vista = _closed(
        value,
        "vista",
        {"requested", "status", "candidate_id", "candidate_bbox_ref", "roi_ref", "affine_transform_ref", "canonical_point"},
    )
    if vista["requested"] is not is_vista:
        raise ValueError("prediction VISTA requested flag mismatch")
    statuses = {"not_requested", "succeeded", "failed", "review_required", "out_of_bounds", "transform_invalid"}
    if vista["status"] not in statuses:
        raise ValueError("vista status is invalid")
    if not is_vista and vista["status"] != "not_requested":
        raise ValueError("pre-VISTA arm cannot contain VISTA result")
    evidence_fields = ("candidate_bbox_ref", "roi_ref", "affine_transform_ref")
    if vista["status"] == "succeeded":
        _string(vista["candidate_id"], "vista candidate_id")
        for field in evidence_fields:
            if vista[field] is None:
                raise ValueError("succeeded prediction requires bounded VISTA evidence")
            vista[field] = _ref(vista[field], f"vista {field}")
        vista["canonical_point"] = _point(vista["canonical_point"], "vista canonical_point")
    else:
        if any(vista[field] is not None for field in ("candidate_id", *evidence_fields, "canonical_point")):
            raise ValueError("non-succeeded VISTA result cannot carry refinement evidence")
    return vista


def _closed(value: Any, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = dict(value)
    actual = set(result)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        parts = []
        if missing:
            parts.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise ValueError(f"{name} is not closed ({'; '.join(parts)})")
    return result


def _ref(value: Any, name: str) -> dict[str, str]:
    result = _closed(value, name, {"id", "content_sha256"})
    _string(result["id"], f"{name}.id")
    _sha(result["content_sha256"], f"{name}.content_sha256")
    return result


def _benchmark_ref(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {"id": manifest["benchmark_id"], "content_sha256": manifest["content_sha256"]}


def _run_ref(run: Mapping[str, Any]) -> dict[str, str]:
    return {"id": run["run_id"], "content_sha256": run["content_sha256"]}


def _bbox(value: Any, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{name} must contain xyxy boxes")
    result = [_number(item, name) for item in value]
    if result[0] >= result[2] or result[1] >= result[3]:
        raise ValueError(f"{name} must use x1 < x2 and y1 < y2")
    return result


def _point(value: Any, name: str) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{name} must be an xy point")
    return [_number(item, name) for item in value]


def _number(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must contain finite numbers")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _relative(value: Any, name: str) -> str:
    path = _string(value, name).replace("\\", "/")
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{name} must be a repository-relative path")
    return path


def _inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError("sealed path escapes benchmark root")
    return target


def _file_sha(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"sealed file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_file_sha(path: Path, manifest_sha256: str) -> str:
    stat = path.stat()
    key = (manifest_sha256, str(path))
    cached = _VERIFIED_FILE_CACHE.get(key)
    state = (stat.st_size, stat.st_mtime_ns)
    if cached is not None and cached[:2] == state:
        return cached[2]
    digest = _file_sha(path)
    _VERIFIED_FILE_CACHE[key] = (state[0], state[1], digest)
    return digest


def _verify_current_manifest_files(sealed: Mapping[str, Any], root: str | Path | None) -> None:
    if root is None:
        return
    root_path = Path(root).resolve()
    for name, item in sealed["artifact_seals"].items():
        if _verified_file_sha(_inside(root_path, item["path"]), sealed["content_sha256"]) != item["sha256"]:
            raise ValueError(f"artifact seal mismatch: {name}")
    checked_images: set[str] = set()
    for case in sealed["cases"]:
        if case["image_path"] in checked_images:
            continue
        checked_images.add(case["image_path"])
        if _verified_file_sha(
            _inside(root_path, case["image_path"]), sealed["content_sha256"]
        ) != case["image_sha256"]:
            raise ValueError(f"image seal mismatch: {case['case_id']}")


def _non_authorizing(value: Mapping[str, Any], name: str) -> None:
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
    "seal_prediction_run",
    "validate_prediction_record",
    "validate_prediction_request",
    "verify_benchmark_manifest",
    "verify_prediction_run",
]
