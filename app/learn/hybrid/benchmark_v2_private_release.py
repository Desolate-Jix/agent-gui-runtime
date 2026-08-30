"""Task 10 private release validation and child-only Gold projection."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

from app.learn.hybrid.benchmark_v2_contracts import (
    ARM_ORDER,
    BENCHMARK_RELEASE_ID,
    PARENT_CONTENT_SHA256,
    PARENT_FILE_SHA256,
    PARENT_REF,
    PROVIDER_CODE_REFS,
    PROVIDER_CORPUS_CONTRACT,
    PROVIDER_MANIFEST_CONTRACT,
    SAFETY,
    canonical_json_bytes,
    content_sha256,
    sha256_bytes,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    validate_preloaded_provider_corpus,
    validate_provider_manifest,
)
__all__ = [
    "validate_task10_private_release_manifest",
    "validate_task10_private_release_bundle",
    "derive_private_scoring_cases",
]

ROOT = Path(__file__).resolve().parents[3]

_PRIVATE_CONTRACT = "portfolio_hybrid_v1_1_benchmark_v2_private_manifest_v1"
_PARENT_CONTRACT = "portfolio_hybrid_v1_1_corpus_manifest_v1"
_PARENT_PATH = "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"
_GOLD_PATH = "tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json"
_PROVIDER_MANIFEST_NAME = "benchmark-v2-provider-manifest.json"
_PROVIDER_CORPUS_NAME = "provider-corpus.v2.json"
_ESTIMAND_PATH = "configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"
_GATE_PATH = "configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json"

_CODE_PATHS = (
    "app/api/panel.py",
    "app/core/model_server.py",
    "app/learn/calibration_sequence.py",
    "app/learn/hybrid/benchmark_scorer_v2.py",
    "app/learn/hybrid/benchmark_v2_private_release.py",
    "app/learn/hybrid/benchmark_v2_pathless.py",
    "app/learn/hybrid/benchmark_v2_actual.py",
    "app/learn/hybrid/benchmark_v2_contracts.py",
    "app/learn/hybrid/benchmark_v2_dispatch_attestation.py",
    "app/learn/hybrid/benchmark_v2_durable_claim.py",
    "app/learn/hybrid/benchmark_v2_holdout.py",
    "app/learn/hybrid/benchmark_v2_incumbent_operation.py",
    "app/learn/hybrid/benchmark_v2_lifecycle.py",
    "app/learn/hybrid/benchmark_v2_predictions.py",
    "app/learn/hybrid/benchmark_v2_probe_authority.py",
    "app/learn/hybrid/benchmark_v2_privileged_projector.py",
    "app/learn/hybrid/benchmark_v2_provider_corpus.py",
    "app/learn/hybrid/benchmark_v2_provider_sandbox.py",
    "app/learn/hybrid/benchmark_v2_public_score.py",
    "app/learn/hybrid/benchmark_v2_runtime.py",
    "app/learn/hybrid/benchmark_v2_window_owner.py",
    "app/learn/hybrid/benchmark_v2_worker_binding.py",
    "app/learn/hybrid/windows_process_scope.py",
    "app/learn/recognition/omniparser_provider.py",
    "app/learn/recognition/omniparser_quality.py",
    "app/learn/recognition/uei/builtin_learning_projection.py",
    "app/learn/recognition/uei/omniparser_shadow_adapter.py",
    "app/learn/recognition/uei/projections.py",
    "app/learn/workflow_service.py",
    "app/learn/workflow_worker.py",
    "app/operation/observe/screen_reader.py",
    "scripts/portfolio_hybrid_v1_1_test_window_v2.py",
    "scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py",
    "scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    "scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py",
    "scripts/run_omniparser_learn_smoke.py",
    "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
    "scripts/run_uei_omniparser_shadow_worker.py",
    "scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py",
    "scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py",
)
_CONFIG_PATHS = (
    _ESTIMAND_PATH,
    _GATE_PATH,
    "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json",
    "configs/model_profiles/learn_mode_omniparser_v2.json",
)
_TEST_PATHS = (
    "tests/test_learn_hybrid_windows_process_scope.py",
    "tests/test_learning_workflow_stage_execution.py",
    "tests/test_learning_workflow_stage_worker.py",
    "tests/test_model_request_cancellation.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent_recovery.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_pathless.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runtime_recovery.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_workflow_service_port.py",
    "tests/test_portfolio_hybrid_v1_1_release_gate_v2.py",
    "tests/test_uei_v1_projections.py",
)
_RELEASE_CODE_REFS = (
    ("panel_service", "app/api/panel.py"),
    ("model_server", "app/core/model_server.py"),
    ("calibration_sequence", "app/learn/calibration_sequence.py"),
    ("benchmark_actual", "app/learn/hybrid/benchmark_v2_actual.py"),
    ("dispatch_attestation", "app/learn/hybrid/benchmark_v2_dispatch_attestation.py"),
    ("durable_claim", "app/learn/hybrid/benchmark_v2_durable_claim.py"),
    ("holdout_ledger", "app/learn/hybrid/benchmark_v2_holdout.py"),
    ("incumbent_operation", "app/learn/hybrid/benchmark_v2_incumbent_operation.py"),
    ("lifecycle", "app/learn/hybrid/benchmark_v2_lifecycle.py"),
    ("predictions", "app/learn/hybrid/benchmark_v2_predictions.py"),
    ("benchmark_runtime", "app/learn/hybrid/benchmark_v2_runtime.py"),
    ("window_owner", "app/learn/hybrid/benchmark_v2_window_owner.py"),
    ("worker_binding", "app/learn/hybrid/benchmark_v2_worker_binding.py"),
    ("windows_process_scope", "app/learn/hybrid/windows_process_scope.py"),
    ("omniparser_provider", "app/learn/recognition/omniparser_provider.py"),
    ("omniparser_quality", "app/learn/recognition/omniparser_quality.py"),
    ("builtin_learning_projection", "app/learn/recognition/uei/builtin_learning_projection.py"),
    ("omniparser_shadow_adapter", "app/learn/recognition/uei/omniparser_shadow_adapter.py"),
    ("uei_projections", "app/learn/recognition/uei/projections.py"),
    ("workflow_service", "app/learn/workflow_service.py"),
    ("workflow_worker", "app/learn/workflow_worker.py"),
    ("screen_reader", "app/operation/observe/screen_reader.py"),
    ("test_window", "scripts/portfolio_hybrid_v1_1_test_window_v2.py"),
    ("omniparser_learn_smoke", "scripts/run_omniparser_learn_smoke.py"),
    ("benchmark_runner", "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py"),
    ("omniparser_shadow_worker", "scripts/run_uei_omniparser_shadow_worker.py"),
)
_PROFILE_REFS = (
    ("estimand", _ESTIMAND_PATH),
    ("omniparser_model_profile", "configs/model_profiles/learn_mode_omniparser_v2.json"),
)
_PRIVATE_SCORER_REFS = (
    ("private_scorer_module", "app/learn/hybrid/benchmark_scorer_v2.py"),
    ("private_scorer_entrypoint", "scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py"),
)
_PRIVATE_SAFETY = {**SAFETY, "real_action_allowed": False, "publish_allowed": False}
_PRIVATE_MANIFEST_FIELDS = {
    "contract_version",
    "benchmark_release_id",
    "holdout_partition",
    "corpus_parent",
    "provider_corpus_ref",
    "provider_manifest_ref",
    "private_scorer_refs",
    "artifact_inventory",
    "safety",
    "content_sha256",
}
_VALIDATED_RELEASE_FIELDS = {
    "private_manifest_bytes",
    "private_manifest",
    "private_manifest_ref",
    "parent",
    "corpus_parent_ref",
    "provider_manifest_bytes",
    "provider_manifest",
    "provider_manifest_ref",
    "provider_corpus_bytes",
    "provider_corpus",
    "provider_corpus_ref",
    "estimand",
    "estimand_ref",
    "gate",
    "gate_ref",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} fields are not closed")
    return deepcopy(dict(value))


def _has_reparse_component(path: Path, anchor: Path) -> bool:
    current = anchor
    for part in path.relative_to(anchor).parts:
        current /= part
        if not current.exists() and not current.is_symlink():
            continue
        details = os.lstat(current)
        if current.is_symlink() or getattr(details, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            return True
    return False


def _root() -> Path:
    root = Path(ROOT)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("private release ROOT is invalid")
    return root.resolve(strict=True)


def _root_file(relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("private release path is not POSIX-relative")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != relative_path:
        raise ValueError("private release path is an alias")
    root = _root()
    path = root / relative_path
    if _has_reparse_component(path, root) or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(f"private release file is not ordinary: {relative_path}")
    return path


def _absolute_ordinary_file(path: Path, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{name} must be an absolute ordinary file")
    anchor = Path(candidate.anchor)
    if (
        not candidate.exists()
        or _has_reparse_component(candidate, anchor)
        or candidate.is_symlink()
        or not candidate.is_file()
        or candidate.resolve(strict=True) != candidate
    ):
        raise ValueError(f"{name} has a symlink or reparse component and is not ordinary")
    return candidate


def _fixed_sibling(private_manifest_path: Path, name: str) -> Path:
    path = _absolute_ordinary_file(private_manifest_path, "private manifest")
    parent = path.parent
    sibling = parent / name
    if sibling.parent != parent:
        raise ValueError(f"required private release sibling is missing: {name}")
    return _absolute_ordinary_file(sibling, f"private release sibling {name}")


def _json_from_canonical(raw: bytes, name: str, *, pretty: bool = True) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not UTF-8 JSON") from exc
    expected = canonical_json_bytes(value, pretty=pretty)
    if not isinstance(value, Mapping) or raw != expected:
        raise ValueError(f"{name} bytes are not canonical")
    return deepcopy(dict(value))


def _ref_list(refs: tuple[tuple[str, str], ...], hashes: Mapping[str, str]) -> list[dict[str, str]]:
    return [
        {"role": role, "relative_path": path, "file_sha256": hashes[path]}
        for role, path in refs
    ]


def _validate_inventory(manifest: Mapping[str, Any]) -> None:
    inventory = _closed(
        manifest["artifact_inventory"],
        {"code_sha256_by_path", "config_sha256_by_path", "test_sha256_by_path"},
        "private artifact inventory",
    )
    for field, expected_paths in (
        ("code_sha256_by_path", _CODE_PATHS),
        ("config_sha256_by_path", _CONFIG_PATHS),
        ("test_sha256_by_path", _TEST_PATHS),
    ):
        hashes = inventory[field]
        if not isinstance(hashes, Mapping) or set(hashes) != set(expected_paths):
            raise ValueError(f"private artifact inventory keys mismatch: {field}")
        for relative_path in expected_paths:
            digest = hashes[relative_path]
            if not isinstance(digest, str) or _SHA_RE.fullmatch(digest) is None:
                raise ValueError("private artifact inventory SHA is invalid")
            if sha256_bytes(_root_file(relative_path).read_bytes()) != digest:
                raise ValueError(f"private artifact inventory byte mismatch: {relative_path}")
    expected_scorers = _ref_list(_PRIVATE_SCORER_REFS, inventory["code_sha256_by_path"])
    if manifest["private_scorer_refs"] != expected_scorers:
        raise ValueError("private scorer refs mismatch verified inventory")


def validate_task10_private_release_manifest(*, manifest_bytes: bytes) -> dict[str, object]:
    """Validate exact Task 10 manifest bytes without opening release siblings."""

    if not isinstance(manifest_bytes, bytes):
        raise TypeError("manifest_bytes must be bytes")
    manifest = _closed(
        _json_from_canonical(manifest_bytes, "Task 10 private manifest"),
        _PRIVATE_MANIFEST_FIELDS,
        "Task 10 private manifest",
    )
    if (
        manifest["contract_version"] != _PRIVATE_CONTRACT
        or manifest["benchmark_release_id"] != BENCHMARK_RELEASE_ID
        or manifest["holdout_partition"] != "holdout"
        or manifest["safety"] != _PRIVATE_SAFETY
    ):
        raise ValueError("Task 10 private manifest release boundary is invalid")
    parent = _closed(
        manifest["corpus_parent"],
        {"contract_version", "relative_path", "file_sha256", "content_sha256"},
        "Task 10 corpus parent",
    )
    if parent != {
        "contract_version": _PARENT_CONTRACT,
        "relative_path": _PARENT_PATH,
        "file_sha256": PARENT_FILE_SHA256,
        "content_sha256": PARENT_CONTENT_SHA256,
    }:
        raise ValueError("Task 10 corpus parent ref is invalid")
    corpus_ref = _closed(
        manifest["provider_corpus_ref"],
        {"contract_version", "relative_path", "file_sha256", "content_sha256", "source_parent_ref"},
        "Task 10 provider corpus ref",
    )
    if corpus_ref["contract_version"] != PROVIDER_CORPUS_CONTRACT or corpus_ref["relative_path"] != _PROVIDER_CORPUS_NAME:
        raise ValueError("Task 10 provider corpus ref is invalid")
    for key in ("file_sha256", "content_sha256"):
        if not isinstance(corpus_ref[key], str) or _SHA_RE.fullmatch(corpus_ref[key]) is None:
            raise ValueError("Task 10 provider corpus ref SHA is invalid")
    if corpus_ref["source_parent_ref"] != PARENT_REF:
        raise ValueError("Task 10 provider corpus parent ref is invalid")
    provider_ref = _closed(
        manifest["provider_manifest_ref"],
        {"contract_version", "relative_path", "file_sha256"},
        "Task 10 provider manifest ref",
    )
    if (
        provider_ref["contract_version"] != PROVIDER_MANIFEST_CONTRACT
        or provider_ref["relative_path"] != _PROVIDER_MANIFEST_NAME
        or not isinstance(provider_ref["file_sha256"], str)
        or _SHA_RE.fullmatch(provider_ref["file_sha256"]) is None
    ):
        raise ValueError("Task 10 provider manifest ref is invalid")
    _validate_inventory(manifest)
    if manifest["content_sha256"] != content_sha256(manifest):
        raise ValueError("Task 10 private manifest content SHA mismatch")
    return manifest


def _load_config(relative_path: str, expected_projection: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    path = _root_file(relative_path)
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Task 10 configuration is not UTF-8 JSON") from exc
    if (
        sha256_bytes(raw) != expected_projection["file_sha256"]
        or value.get("contract_version") != expected_projection["contract_version"]
        or value.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
    ):
        raise ValueError("Task 10 configuration projection mismatch")
    return deepcopy(value), {
        "contract_version": value["contract_version"],
        "file_sha256": sha256_bytes(raw),
    }


def _expected_provider_cases(parent: Mapping[str, Any]) -> list[dict[str, Any]]:
    screens = {item["screen_id"]: item for item in parent["screenshots"]}
    expected = []
    for target in parent["gold_records"]:
        screen = screens[target["screen_id"]]
        screen_id = screen["screen_id"]
        target_id = target["target_id"]
        expected.append(
            {
                "case_id": hashlib.sha256(
                    f"benchmark-v2-case\0{screen_id}\0{target_id}".encode("utf-8")
                ).hexdigest(),
                "partition": screen["partition"],
                "screen_group": hashlib.sha256(
                    f"benchmark-v2-screen-group\0{screen_id}".encode("utf-8")
                ).hexdigest(),
                "goal": target["goal"],
                "image": {
                    key: screen[key]
                    for key in ("path", "sha256", "width", "height")
                },
                "layout": {
                    key: screen[key]
                    for key in (
                        "layout_id",
                        "title",
                        "surface",
                        "density",
                        "precision_case",
                        "source_kind",
                        "source_provenance",
                    )
                },
            }
        )
    return expected


def validate_task10_private_release_bundle(*, private_manifest_path: Path) -> dict[str, object]:
    """Validate the private manifest and its two fixed provider-safe siblings."""

    path = _absolute_ordinary_file(private_manifest_path, "private manifest")
    private_bytes = path.read_bytes()
    manifest = validate_task10_private_release_manifest(manifest_bytes=private_bytes)

    parent_path = _root_file(_PARENT_PATH)
    parent_bytes = parent_path.read_bytes()
    if parent_bytes != canonical_json_bytes(json.loads(parent_bytes.decode("utf-8")), pretty=True):
        raise ValueError("frozen corpus parent bytes are not canonical")
    if sha256_bytes(parent_bytes) != PARENT_FILE_SHA256:
        raise ValueError("frozen corpus parent file SHA mismatch")
    parent = _json_from_canonical(parent_bytes, "frozen corpus parent")
    if (
        parent.get("content_sha256") != PARENT_CONTENT_SHA256
        or content_sha256(parent) != PARENT_CONTENT_SHA256
        or parent.get("seal_state") != "approved"
        or parent.get("prediction_counts") != {"regression": 0, "holdout": 0, "total": 0}
        or parent.get("holdout_prediction_count") != 0
        or len(parent.get("screenshots", [])) != 24
        or len(parent.get("gold_records", [])) != 120
    ):
        raise ValueError("frozen corpus parent approval boundary is invalid")
    gold_path = _root_file(_GOLD_PATH)
    gold_bytes = gold_path.read_bytes()
    gold = _json_from_canonical(gold_bytes, "frozen Gold")
    gold_ref = parent.get("artifacts", {}).get("gold", {})
    reviewer = parent.get("reviewer_identity_hash")
    if (
        gold.get("review_state") != "approved"
        or gold.get("targets") != parent["gold_records"]
        or gold_ref != {"path": _GOLD_PATH, "sha256": sha256_bytes(gold_bytes)}
        or not isinstance(reviewer, str)
        or _SHA_RE.fullmatch(reviewer) is None
        or any(
            record.get("review_status") != "approved"
            or record.get("reviewer_identity_hash") != reviewer
            or record.get("annotator_identity_hash") == reviewer
            for record in parent["gold_records"]
        )
    ):
        raise ValueError("frozen Gold approval or parent binding is invalid")
    for screen in parent["screenshots"]:
        image = _root_file(screen["path"])
        raw = image.read_bytes()
        if (
            sha256_bytes(raw) != screen.get("sha256")
            or len(raw) < 24
            or raw[:8] != b"\x89PNG\r\n\x1a\n"
            or raw[12:16] != b"IHDR"
            or int.from_bytes(raw[16:20], "big") != screen.get("width")
            or int.from_bytes(raw[20:24], "big") != screen.get("height")
            or screen.get("review_status") != "approved"
            or screen.get("privacy_review_status") != "approved"
            or screen.get("reviewer_identity_hash") != reviewer
        ):
            raise ValueError("frozen screenshot lineage is invalid")

    provider_manifest_path = _fixed_sibling(path, _PROVIDER_MANIFEST_NAME)
    provider_corpus_path = _fixed_sibling(path, _PROVIDER_CORPUS_NAME)
    provider_manifest_bytes = provider_manifest_path.read_bytes()
    provider_manifest = validate_provider_manifest(
        _json_from_canonical(provider_manifest_bytes, "Task 10 provider manifest")
    )
    provider_corpus_bytes = provider_corpus_path.read_bytes()
    provider_corpus = validate_preloaded_provider_corpus(
        raw=provider_corpus_bytes,
        expected_sha256=str(manifest["provider_corpus_ref"]["file_sha256"]),
    )
    if sha256_bytes(provider_manifest_bytes) != manifest["provider_manifest_ref"]["file_sha256"]:
        raise ValueError("Task 10 provider manifest file SHA mismatch")
    if provider_manifest["provider_corpus_ref"] != manifest["provider_corpus_ref"]:
        raise ValueError("Task 10 private/provider corpus ref mismatch")
    if provider_corpus["content_sha256"] != manifest["provider_corpus_ref"]["content_sha256"]:
        raise ValueError("Task 10 provider corpus content mismatch")
    if provider_corpus["source_parent_ref"] != PARENT_REF:
        raise ValueError("Task 10 provider corpus parent mismatch")
    if provider_corpus["cases"] != _expected_provider_cases(parent):
        raise ValueError("Task 10 provider cases differ from frozen parent projection")
    runtime = provider_manifest["sealed_runtime"]
    inventory = manifest["artifact_inventory"]
    if (
        runtime["code_refs"] != _ref_list(PROVIDER_CODE_REFS, inventory["code_sha256_by_path"])
        or runtime["release_code_refs"] != _ref_list(_RELEASE_CODE_REFS, inventory["code_sha256_by_path"])
        or runtime["profile_refs"] != _ref_list(_PROFILE_REFS, inventory["config_sha256_by_path"])
        or provider_manifest["arm_order"] != list(ARM_ORDER)
        or provider_manifest["benchmark_release_id"] != BENCHMARK_RELEASE_ID
        or provider_manifest["holdout_partition"] != "holdout"
        or provider_manifest["safety"] != SAFETY
    ):
        raise ValueError("Task 10 provider runtime refs are invalid")

    estimand, estimand_ref = _load_config(
        _ESTIMAND_PATH, provider_manifest["evaluation_projection"]["estimand"]
    )
    gate, gate_ref = _load_config(
        _GATE_PATH, provider_manifest["evaluation_projection"]["gate"]
    )
    state: dict[str, object] = {
        "private_manifest_bytes": private_bytes,
        "private_manifest": manifest,
        "private_manifest_ref": {
            "contract_version": manifest["contract_version"],
            "file_sha256": sha256_bytes(private_bytes),
            "content_sha256": manifest["content_sha256"],
        },
        "parent": parent,
        "corpus_parent_ref": deepcopy(PARENT_REF),
        "provider_manifest_bytes": provider_manifest_bytes,
        "provider_manifest": provider_manifest,
        "provider_manifest_ref": deepcopy(manifest["provider_manifest_ref"]),
        "provider_corpus_bytes": provider_corpus_bytes,
        "provider_corpus": provider_corpus,
        "provider_corpus_ref": deepcopy(manifest["provider_corpus_ref"]),
        "estimand": estimand,
        "estimand_ref": estimand_ref,
        "gate": gate,
        "gate_ref": gate_ref,
    }
    if set(state) != _VALIDATED_RELEASE_FIELDS:
        raise AssertionError("internal Task 10 release state is not closed")
    return state


def _acceptable_regions(value: object) -> list[list[int]]:
    if not isinstance(value, list) or not value:
        raise ValueError("private acceptable regions are invalid")
    regions: list[list[int]] = []
    for raw in value:
        if not isinstance(raw, list) or len(raw) != 4 or not all(type(item) is int for item in raw):
            raise ValueError("private acceptable region is invalid")
        x1, y1, x2, y2 = raw
        if x2 <= x1 or y2 <= y1:
            raise ValueError("private acceptable region is invalid")
        regions.append(list(raw))
    return regions


def derive_private_scoring_cases(
    *, validated_release: Mapping[str, object], partition: str
) -> list[dict[str, object]]:
    """Derive the minimal Gold projection for one isolated scorer partition."""

    if not isinstance(validated_release, Mapping) or set(validated_release) != _VALIDATED_RELEASE_FIELDS:
        raise ValueError("validated Task 10 release state is invalid")
    if partition not in {"regression", "holdout"}:
        raise ValueError("private scoring partition is invalid")
    parent = validated_release["parent"]
    provider = validated_release["provider_corpus"]
    if not isinstance(parent, Mapping) or not isinstance(provider, Mapping):
        raise ValueError("validated Task 10 release evidence is invalid")
    cases: list[dict[str, object]] = []
    for record in parent["gold_records"]:
        if record["partition"] != partition:
            continue
        screen_id = record["screen_id"]
        target_id = record["target_id"]
        cases.append(
            {
                "case_id": hashlib.sha256(
                    f"benchmark-v2-case\0{screen_id}\0{target_id}".encode("utf-8")
                ).hexdigest(),
                "screen_group": hashlib.sha256(
                    f"benchmark-v2-screen-group\0{screen_id}".encode("utf-8")
                ).hexdigest(),
                "partition": partition,
                "important_target": record["important_target"],
                "acceptable_regions": _acceptable_regions(record["acceptable_regions"]),
            }
        )
    expected_ids = sorted(
        case["case_id"] for case in provider["cases"] if case["partition"] == partition
    )
    groups: dict[str, int] = {}
    for case in cases:
        groups[str(case["screen_group"])] = groups.get(str(case["screen_group"]), 0) + 1
    if (
        len(cases) != 60
        or len(groups) != 12
        or set(groups.values()) != {5}
        or sorted(str(case["case_id"]) for case in cases) != expected_ids
        or any(
            set(case)
            != {"case_id", "screen_group", "partition", "important_target", "acceptable_regions"}
            for case in cases
        )
    ):
        raise ValueError("private scoring projection does not match provider corpus")
    return cases
