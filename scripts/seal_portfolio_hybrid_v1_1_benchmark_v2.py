"""Create or verify the closed Benchmark v2 private/provider split seals."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.hybrid.benchmark_v2_contracts import (
    ARM_ORDER,
    BENCHMARK_RELEASE_ID,
    EVALUATION_PROJECTION,
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
from scripts.seal_portfolio_hybrid_v1_1_corpus import load_and_verify_corpus_seal


PRIVATE_CONTRACT = "portfolio_hybrid_v1_1_benchmark_v2_private_manifest_v1"
TEMPLATE_CONTRACT = "portfolio_hybrid_v1_1_benchmark_v2_manifest_template_v1"
PARENT_CONTRACT = "portfolio_hybrid_v1_1_corpus_manifest_v1"
PARENT_PATH = "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"
TEMPLATE_PATH = "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json"
PROVIDER_CANDIDATE_PATH = (
    "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-corpus.candidate.json"
)
PROVIDER_LOGICAL_PATH = "provider-corpus.v2.json"
PROVIDER_MANIFEST_LOGICAL_PATH = "benchmark-v2-provider-manifest.json"

CODE_PATHS = (
    "app/api/panel.py",
    "app/core/model_server.py",
    "app/learn/calibration_sequence.py",
    "app/learn/hybrid/benchmark_scorer_v2.py",
    "app/learn/hybrid/benchmark_v2_actual.py",
    "app/learn/hybrid/benchmark_v2_contracts.py",
    "app/learn/hybrid/benchmark_v2_dispatch_attestation.py",
    "app/learn/hybrid/benchmark_v2_durable_claim.py",
    "app/learn/hybrid/benchmark_v2_holdout.py",
    "app/learn/hybrid/benchmark_v2_incumbent_operation.py",
    "app/learn/hybrid/benchmark_v2_lifecycle.py",
    "app/learn/hybrid/benchmark_v2_predictions.py",
    "app/learn/hybrid/benchmark_v2_privileged_projector.py",
    "app/learn/hybrid/benchmark_v2_provider_corpus.py",
    "app/learn/hybrid/benchmark_v2_provider_sandbox.py",
    "app/learn/hybrid/benchmark_v2_runtime.py",
    "app/learn/hybrid/benchmark_v2_window_owner.py",
    "app/learn/hybrid/benchmark_v2_worker_binding.py",
    "app/learn/hybrid/windows_process_scope.py",
    "app/learn/recognition/uei/builtin_learning_projection.py",
    "app/learn/recognition/uei/omniparser_shadow_adapter.py",
    "app/learn/recognition/uei/projections.py",
    "app/learn/workflow_service.py",
    "app/learn/workflow_worker.py",
    "app/operation/observe/screen_reader.py",
    "scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py",
    "scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    "scripts/portfolio_hybrid_v1_1_test_window_v2.py",
    "scripts/project_portfolio_hybrid_v1_1_provider_corpus_v2.py",
    "scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
    "scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py",
    "scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py",
)
CONFIG_PATHS = (
    "configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json",
    "configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json",
    TEMPLATE_PATH,
)
TEST_PATHS = (
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
RELEASE_CODE_REFS = (
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
    (
        "builtin_learning_projection",
        "app/learn/recognition/uei/builtin_learning_projection.py",
    ),
    (
        "omniparser_shadow_adapter",
        "app/learn/recognition/uei/omniparser_shadow_adapter.py",
    ),
    ("uei_projections", "app/learn/recognition/uei/projections.py"),
    ("workflow_service", "app/learn/workflow_service.py"),
    ("workflow_worker", "app/learn/workflow_worker.py"),
    ("screen_reader", "app/operation/observe/screen_reader.py"),
    ("test_window", "scripts/portfolio_hybrid_v1_1_test_window_v2.py"),
    ("benchmark_runner", "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py"),
)
PROFILE_REFS = (
    ("estimand", "configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"),
)
PRIVATE_SCORER_REFS = (
    ("private_scorer_module", "app/learn/hybrid/benchmark_scorer_v2.py"),
    (
        "private_scorer_entrypoint",
        "scripts/score_portfolio_hybrid_v1_1_benchmark_v2_private.py",
    ),
)

_TEMPLATE = {
    "benchmark_release_id": BENCHMARK_RELEASE_ID,
    "contract_version": TEMPLATE_CONTRACT,
    "corpus_parent": {
        "contract_version": PARENT_CONTRACT,
        "file_sha256": PARENT_FILE_SHA256,
        "relative_path": PARENT_PATH,
    },
    "provider_corpus_output": PROVIDER_CANDIDATE_PATH,
    "safety": dict(SAFETY),
}
_PRIVATE_SAFETY = {
    **SAFETY,
    "real_action_allowed": False,
    "publish_allowed": False,
}
_PRIVATE_PATH_FRAGMENTS = (
    "corpus-manifest.v1.json",
    "gold.v1.json",
    "benchmark_v2_privileged_projector.py",
    "benchmark_scorer_v2.py",
    "score_portfolio_hybrid_v1_1_benchmark_v2_private.py",
    "seal_portfolio_hybrid_v1_1_benchmark_v2.py",
    "review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    "private-manifest",
)


def _canonical_pretty_bytes(value: object) -> bytes:
    return canonical_json_bytes(value, pretty=True)


def _canonical_compact_bytes(value: object) -> bytes:
    return canonical_json_bytes(value)


def _file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _has_reparse_component(path: Path, root: Path) -> bool:
    current = root
    relative = path.relative_to(root)
    for part in relative.parts:
        current /= part
        if not current.exists() and not current.is_symlink():
            continue
        details = os.lstat(current)
        if current.is_symlink() or getattr(details, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ):
            return True
    return False


def _root_path(root: Path) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
        raise ValueError("repository root must be an existing ordinary absolute directory")
    return candidate.resolve(strict=True)


def _require_file(root: Path, relative_path: str) -> Path:
    if not relative_path or "\\" in relative_path:
        raise ValueError(f"required file path is not POSIX-relative: {relative_path}")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != relative_path:
        raise ValueError(f"required file path escapes the repository: {relative_path}")
    path = root / relative_path
    if _has_reparse_component(path, root):
        raise ValueError(f"required file uses a symlink or reparse alias: {relative_path}")
    if not path.is_file():
        raise ValueError(f"required file is missing: {relative_path}")
    if path.resolve(strict=True) != path:
        raise ValueError(f"required file path is not canonical: {relative_path}")
    return path


def _checked_input(path: Path, root: Path, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{name} must remain inside the repository root") from exc
    return _require_file(root, relative)


def _checked_output(path: Path, root: Path, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} must remain inside the repository root") from exc
    canonical = candidate.resolve(strict=False)
    try:
        canonical.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{name} normalization escapes the repository root") from exc
    if (
        canonical == root
        or _has_reparse_component(candidate, root)
        or _has_reparse_component(canonical.parent, root)
    ):
        raise ValueError(f"{name} uses a symlink, reparse, or invalid output path")
    return canonical


def _inventory_sha_map(root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    return {relative: _file_sha256(_require_file(root, relative)) for relative in paths}


def _load_canonical_json(
    path: Path, name: str, *, sorted_keys: bool = True
) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is invalid UTF-8 JSON") from exc
    canonical = (
        _canonical_pretty_bytes(value)
        if sorted_keys
        else (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )
    if not isinstance(value, Mapping) or raw != canonical:
        raise ValueError(f"{name} bytes are not canonical")
    return deepcopy(dict(value))


def _validate_template(template_path: Path, root: Path) -> dict[str, Any]:
    required = _require_file(root, TEMPLATE_PATH)
    if template_path != required:
        raise ValueError(f"template must be the frozen repository path: {TEMPLATE_PATH}")
    template = _load_canonical_json(required, "benchmark v2 template")
    if template != _TEMPLATE:
        raise ValueError("benchmark v2 template value is invalid")
    return template


def _assert_projected(source: Mapping[str, Any], expected: Mapping[str, Any], name: str) -> None:
    for key, expected_value in expected.items():
        if key == "file_sha256":
            continue
        if key not in source:
            raise ValueError(f"{name} is missing projected field: {key}")
        actual_value = source[key]
        if isinstance(expected_value, Mapping):
            if not isinstance(actual_value, Mapping):
                raise ValueError(f"{name} projected field is invalid: {key}")
            _assert_projected(actual_value, expected_value, f"{name}.{key}")
        elif actual_value != expected_value:
            raise ValueError(f"{name} projected field is invalid: {key}")


def _evaluation_projection(root: Path, parent: Mapping[str, Any]) -> dict[str, Any]:
    projection = deepcopy(EVALUATION_PROJECTION)
    for key in (
        "provider_revisions",
        "provider_revisions_sha256",
        "shared_budget",
        "shared_budget_sha256",
        "shared_context_policy",
        "shared_context_policy_sha256",
    ):
        if parent.get(key) != projection["provider_policy"][key]:
            raise ValueError(f"frozen parent provider policy mismatch: {key}")
    for role, relative in (
        ("estimand", CONFIG_PATHS[0]),
        ("gate", CONFIG_PATHS[1]),
    ):
        path = _require_file(root, relative)
        document = _load_canonical_json(
            path, f"benchmark v2 {role}", sorted_keys=False
        )
        expected = projection[role]
        if _file_sha256(path) != expected["file_sha256"]:
            raise ValueError(f"benchmark v2 {role} file SHA mismatch")
        if document.get("benchmark_release_id") != BENCHMARK_RELEASE_ID:
            raise ValueError(f"benchmark v2 {role} release is invalid")
        _assert_projected(document, expected, f"benchmark v2 {role}")
    return projection


def _validate_provider_images(
    provider_corpus: Mapping[str, Any], parent: Mapping[str, Any], root: Path
) -> None:
    parent_by_path = {item["path"]: item for item in parent["screenshots"]}
    counts = {path: 0 for path in parent_by_path}
    for case in provider_corpus["cases"]:
        image = case["image"]
        path = image["path"]
        if path not in parent_by_path:
            raise ValueError("provider corpus image is outside the frozen v1 image set")
        parent_image = parent_by_path[path]
        if image != {
            "path": parent_image["path"],
            "sha256": parent_image["sha256"],
            "width": parent_image["width"],
            "height": parent_image["height"],
        }:
            raise ValueError("provider corpus image lineage mismatch")
        if _file_sha256(_require_file(root, path)) != image["sha256"]:
            raise ValueError("provider corpus image file SHA mismatch")
        counts[path] += 1
    if set(counts.values()) != {5}:
        raise ValueError("provider corpus must bind five cases to every frozen image")


def _load_inputs(
    *, template_path: Path, provider_corpus_path: Path, root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    _validate_template(_checked_input(template_path, root, "template"), root)
    parent_path = _require_file(root, PARENT_PATH)
    if _file_sha256(parent_path) != PARENT_FILE_SHA256:
        raise ValueError("frozen v1 parent file SHA mismatch")
    try:
        parent = load_and_verify_corpus_seal(parent_path, root=root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"frozen v1 parent is invalid: {exc}") from exc
    if parent.get("content_sha256") != PARENT_CONTENT_SHA256:
        raise ValueError("frozen v1 parent content SHA mismatch")
    child_path = _checked_input(provider_corpus_path, root, "provider corpus")
    child_raw = child_path.read_bytes()
    child_file_sha256 = sha256_bytes(child_raw)
    child = validate_preloaded_provider_corpus(
        raw=child_raw,
        expected_sha256=child_file_sha256,
    )
    if child["source_parent_ref"] != PARENT_REF:
        raise ValueError("provider corpus frozen parent lineage mismatch")
    _validate_provider_images(child, parent, root)
    projection = _evaluation_projection(root, parent)
    return parent, child, projection, child_file_sha256


def _ref_list(
    refs: tuple[tuple[str, str], ...], hashes: Mapping[str, str]
) -> list[dict[str, str]]:
    return [
        {"role": role, "relative_path": path, "file_sha256": hashes[path]}
        for role, path in refs
    ]


def _build_provider_manifest(
    *,
    provider_corpus: Mapping[str, Any],
    provider_corpus_file_sha256: str,
    code_hashes: Mapping[str, str],
    config_hashes: Mapping[str, str],
    evaluation_projection: Mapping[str, Any],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_corpus_ref": {
            "contract_version": PROVIDER_CORPUS_CONTRACT,
            "relative_path": PROVIDER_LOGICAL_PATH,
            "file_sha256": provider_corpus_file_sha256,
            "content_sha256": provider_corpus["content_sha256"],
            "source_parent_ref": deepcopy(provider_corpus["source_parent_ref"]),
        },
        "holdout_partition": "holdout",
        "evaluation_projection": deepcopy(evaluation_projection),
        "sealed_runtime": {
            "code_refs": _ref_list(PROVIDER_CODE_REFS, code_hashes),
            "release_code_refs": _ref_list(RELEASE_CODE_REFS, code_hashes),
            "profile_refs": _ref_list(PROFILE_REFS, config_hashes),
        },
        "workload": {
            "contract_version": "provider_sandbox_workload_request_v1",
            "command": "validate_provider_corpus",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "arm_order": list(ARM_ORDER),
        "safety": dict(SAFETY),
    }
    return validate_provider_manifest(manifest)


def _reject_provider_private_paths(value: object) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _reject_provider_private_paths(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_provider_private_paths(nested)
    elif isinstance(value, str):
        lowered = value.casefold().replace("\\", "/")
        if any(fragment in lowered for fragment in _PRIVATE_PATH_FRAGMENTS):
            raise ValueError("provider manifest contains a private path leak")


def _verify_provider_file_refs(
    manifest: Mapping[str, Any],
    code_hashes: Mapping[str, str],
    config_hashes: Mapping[str, str],
) -> None:
    runtime = manifest["sealed_runtime"]
    expected_boot = _ref_list(PROVIDER_CODE_REFS, code_hashes)
    expected_release = _ref_list(RELEASE_CODE_REFS, code_hashes)
    expected_profiles = _ref_list(PROFILE_REFS, config_hashes)
    if runtime["code_refs"] != expected_boot:
        raise ValueError("provider bootstrap code refs mismatch")
    if runtime["release_code_refs"] != expected_release:
        raise ValueError("provider release code refs mismatch")
    if runtime["profile_refs"] != expected_profiles:
        raise ValueError("provider profile refs mismatch")
    _reject_provider_private_paths(manifest)


def _build_private_manifest(
    *,
    parent: Mapping[str, Any],
    provider_corpus_ref: Mapping[str, Any],
    provider_manifest_file_sha256: str,
    code_hashes: Mapping[str, str],
    config_hashes: Mapping[str, str],
    test_hashes: Mapping[str, str],
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "contract_version": PRIVATE_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "holdout_partition": "holdout",
        "corpus_parent": {
            "contract_version": parent["contract_version"],
            "relative_path": PARENT_PATH,
            "file_sha256": PARENT_FILE_SHA256,
            "content_sha256": parent["content_sha256"],
        },
        "provider_corpus_ref": deepcopy(provider_corpus_ref),
        "provider_manifest_ref": {
            "contract_version": PROVIDER_MANIFEST_CONTRACT,
            "relative_path": PROVIDER_MANIFEST_LOGICAL_PATH,
            "file_sha256": provider_manifest_file_sha256,
        },
        "private_scorer_refs": _ref_list(PRIVATE_SCORER_REFS, code_hashes),
        "artifact_inventory": {
            "code_sha256_by_path": dict(code_hashes),
            "config_sha256_by_path": dict(config_hashes),
            "test_sha256_by_path": dict(test_hashes),
        },
        "safety": dict(_PRIVATE_SAFETY),
    }
    manifest["content_sha256"] = content_sha256(manifest)
    return manifest


def _verify_private_inventory(
    manifest: Mapping[str, Any],
    code_hashes: Mapping[str, str],
    config_hashes: Mapping[str, str],
    test_hashes: Mapping[str, str],
) -> None:
    inventory = manifest["artifact_inventory"]
    if inventory != {
        "code_sha256_by_path": dict(code_hashes),
        "config_sha256_by_path": dict(config_hashes),
        "test_sha256_by_path": dict(test_hashes),
    }:
        raise ValueError("private artifact inventory mismatch")
    if manifest["private_scorer_refs"] != _ref_list(PRIVATE_SCORER_REFS, code_hashes):
        raise ValueError("private scorer refs mismatch the inventory")
    if manifest.get("content_sha256") != content_sha256(manifest):
        raise ValueError("private manifest content SHA mismatch")


def _build_pair(
    *, template_path: Path, provider_corpus_path: Path, root: Path
) -> tuple[dict[str, object], dict[str, object], bytes, bytes]:
    parent, provider_corpus, projection, provider_corpus_sha = _load_inputs(
        template_path=template_path,
        provider_corpus_path=provider_corpus_path,
        root=root,
    )
    code_hashes = _inventory_sha_map(root, CODE_PATHS)
    config_hashes = _inventory_sha_map(root, CONFIG_PATHS)
    test_hashes = _inventory_sha_map(root, TEST_PATHS)
    provider = _build_provider_manifest(
        provider_corpus=provider_corpus,
        provider_corpus_file_sha256=provider_corpus_sha,
        code_hashes=code_hashes,
        config_hashes=config_hashes,
        evaluation_projection=projection,
    )
    _verify_provider_file_refs(provider, code_hashes, config_hashes)
    provider_raw = _canonical_pretty_bytes(provider)
    private = _build_private_manifest(
        parent=parent,
        provider_corpus_ref=provider["provider_corpus_ref"],
        provider_manifest_file_sha256=sha256_bytes(provider_raw),
        code_hashes=code_hashes,
        config_hashes=config_hashes,
        test_hashes=test_hashes,
    )
    _verify_private_inventory(private, code_hashes, config_hashes, test_hashes)
    private_raw = _canonical_pretty_bytes(private)
    if private["provider_corpus_ref"] != provider["provider_corpus_ref"]:
        raise ValueError("private/provider corpus refs mismatch")
    if private["benchmark_release_id"] != provider["benchmark_release_id"]:
        raise ValueError("private/provider release IDs mismatch")
    if private["holdout_partition"] != provider["holdout_partition"]:
        raise ValueError("private/provider holdout partitions mismatch")
    return private, provider, private_raw, provider_raw


def _preflight_output(path: Path, raw: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.is_symlink():
            raise FileExistsError(f"output exists but is not an ordinary file: {path}")
        if path.read_bytes() != raw:
            raise FileExistsError(f"output exists with different bytes: {path}")


def _write_new_or_exact(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.read_bytes() != raw:
            raise FileExistsError(f"output exists with different bytes: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def seal_split_manifests(
    *,
    template_path: Path,
    provider_corpus_path: Path,
    private_output_path: Path,
    provider_output_path: Path,
    _root: Path = ROOT,
) -> tuple[dict[str, object], dict[str, object]]:
    root = _root_path(_root)
    private_path = _checked_output(private_output_path, root, "private output")
    provider_path = _checked_output(provider_output_path, root, "provider output")
    if private_path == provider_path:
        raise ValueError("private and provider outputs resolve to the same canonical file")
    private, provider, private_raw, provider_raw = _build_pair(
        template_path=template_path,
        provider_corpus_path=provider_corpus_path,
        root=root,
    )
    _preflight_output(provider_path, provider_raw)
    _preflight_output(private_path, private_raw)
    _write_new_or_exact(provider_path, provider_raw)
    _write_new_or_exact(private_path, private_raw)
    return private, provider


def verify_split_manifests(
    *,
    template_path: Path,
    provider_corpus_path: Path,
    private_manifest_path: Path,
    provider_manifest_path: Path,
    _root: Path = ROOT,
) -> tuple[dict[str, object], dict[str, object]]:
    root = _root_path(_root)
    expected_private, expected_provider, _, _ = _build_pair(
        template_path=template_path,
        provider_corpus_path=provider_corpus_path,
        root=root,
    )
    provider_path = _checked_input(provider_manifest_path, root, "provider manifest")
    private_path = _checked_input(private_manifest_path, root, "private manifest")
    provider = _load_canonical_json(provider_path, "provider manifest")
    private = _load_canonical_json(private_path, "private manifest")
    provider = validate_provider_manifest(provider)
    if provider != expected_provider:
        raise ValueError("provider manifest mismatch")
    if private != expected_private:
        raise ValueError("private manifest mismatch")
    if private["provider_manifest_ref"]["file_sha256"] != _file_sha256(provider_path):
        raise ValueError("private provider manifest file SHA mismatch")
    _verify_private_inventory(
        private,
        expected_private["artifact_inventory"]["code_sha256_by_path"],
        expected_private["artifact_inventory"]["config_sha256_by_path"],
        expected_private["artifact_inventory"]["test_sha256_by_path"],
    )
    return private, provider


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--provider-corpus", type=Path, required=True)
    parser.add_argument("--output-private", type=Path, required=True)
    parser.add_argument("--output-provider", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    return parser


def _receipt(
    *, status: str, private_path: Path, provider_path: Path, provider_corpus_path: Path
) -> dict[str, object]:
    return {
        "status": status,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_corpus_file_sha256": _file_sha256(provider_corpus_path),
        "provider_manifest_file_sha256": _file_sha256(provider_path),
        "private_manifest_file_sha256": _file_sha256(private_path),
        "code_inventory_count": len(CODE_PATHS),
        "config_inventory_count": len(CONFIG_PATHS),
        "test_inventory_count": len(TEST_PATHS),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        root = _root_path(ROOT)
        template_path = _checked_input(args.template, root, "template")
        provider_corpus_path = _checked_input(
            args.provider_corpus, root, "provider corpus"
        )
        if args.verify_only:
            private_path = _checked_input(
                args.output_private, root, "private manifest"
            )
            provider_path = _checked_input(
                args.output_provider, root, "provider manifest"
            )
            verify_split_manifests(
                template_path=template_path,
                provider_corpus_path=provider_corpus_path,
                private_manifest_path=private_path,
                provider_manifest_path=provider_path,
            )
            status = "VERIFIED"
        else:
            private_path = _checked_output(args.output_private, root, "private output")
            provider_path = _checked_output(
                args.output_provider, root, "provider output"
            )
            seal_split_manifests(
                template_path=template_path,
                provider_corpus_path=provider_corpus_path,
                private_output_path=private_path,
                provider_output_path=provider_path,
            )
            status = "SEALED"
        print(
            json.dumps(
                _receipt(
                    status=status,
                    private_path=private_path,
                    provider_path=provider_path,
                    provider_corpus_path=provider_corpus_path,
                ),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        parser.exit(1, f"benchmark v2 split seal failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
