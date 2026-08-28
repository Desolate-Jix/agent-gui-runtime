"""Validate and assemble Benchmark v2 dependency-bound public evidence."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]

RESULT_RECEIPT_CONTRACT = "benchmark_v2_dependency_result_receipt_v1"
REVIEW_RECEIPT_CONTRACT = "benchmark_v2_dependency_review_receipt_v1"
DEPENDENCY_MANIFEST_CONTRACT = "benchmark_v2_release_dependency_manifest_v1"

SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}

PYTEST_PLUGIN_NAME = "scripts.assemble_portfolio_hybrid_v1_1_benchmark_v2_report"
PYTEST_SUITE_OPTION = "--benchmark-v2-suite-id"
PYTEST_RECEIPT_OPTION = "--benchmark-v2-receipt-output"

DEPENDENCY_ORDER = (
    "task05_worker_binding_v1",
    "task06a_completed_result_identity_v1",
    "task06b1_outer_worker_supervision_v1",
    "task06b2_qwen_cleanup_sidecar_v1",
    "task06c_incumbent_cut_point_v1",
)

FROZEN_PYTEST_ARGV_BY_SUITE_ID: dict[str, list[str]] = {
    "task05_worker_binding_v1": [
        "pytest",
        "-q",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py",
        "tests/test_learning_workflow_stage_worker.py",
        "-k",
        "vision_observe_screen or benchmark_v2 or incumbent",
    ],
    "task06a_completed_result_identity_v1": [
        "pytest",
        "-q",
        "tests/test_learning_workflow_stage_worker.py",
        "-k",
        "completed_result_identity or adopt_result or read_adopted_result",
    ],
    "task06b1_outer_worker_supervision_v1": [
        "pytest",
        "-q",
        "tests/test_learn_hybrid_windows_process_scope.py",
        "tests/test_learning_workflow_stage_worker.py",
        "-k",
        "benchmark_worker or exact_process_identity_to_scope or handler_payload_source or payload_projection or managed_qwen_mode",
    ],
    "task06b2_qwen_cleanup_sidecar_v1": [
        "pytest",
        "-q",
        "tests/test_model_request_cancellation.py",
        "tests/test_learning_workflow_stage_worker.py",
        "-k",
        "qwen_cleanup_sidecar or benchmark_provider_cleanup",
    ],
    "task06c_incumbent_cut_point_v1": [
        "pytest",
        "-q",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py",
        "tests/test_learning_workflow_stage_worker.py",
        "tests/test_model_request_cancellation.py",
        "tests/test_learning_workflow_stage_execution.py",
        "-k",
        "benchmark_v2 or incumbent or hybrid or qwen or payload_projection or managed_qwen_mode",
    ],
    "task12_release_gate_v1": [
        "pytest",
        "-q",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_estimand.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_isolation.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_scoring.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_window.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py",
        "tests/test_learning_workflow_stage_worker.py",
        "tests/test_learn_hybrid_windows_process_scope.py",
        "tests/test_model_request_cancellation.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py",
        "tests/test_learning_workflow_stage_execution.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_actual.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_runner.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_seal.py",
        "tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
        "tests/test_portfolio_hybrid_v1_1_release_gate_v2.py",
    ],
}

REVIEW_NAME_BY_SUITE_ID = {
    "task05_worker_binding_v1": "task-10b-slice-5-review.md",
    "task06a_completed_result_identity_v1": "task-10b-slice-6-prerequisite-a-review.md",
    "task06b1_outer_worker_supervision_v1": "task-10b-slice-6-prerequisite-b1-review.md",
    "task06b2_qwen_cleanup_sidecar_v1": "task-10b-slice-6-prerequisite-b2-review.md",
    "task06c_incumbent_cut_point_v1": "task-10b-slice-6-review.md",
    "task12_release_gate_v1": "task-10b-slice-12-review.md",
}

_CANONICAL_EVIDENCE_ROOT = (
    ROOT / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/dependency-evidence"
)
_CANONICAL_REVIEW_ROOT = (
    ROOT
    / ".superpowers/sdd/2026-08-25-portfolio-hybrid-v1-1-implementation-plan"
)

PRODUCTION_SOURCE_PATHS = (
    "app/learn/hybrid/benchmark_v2_worker_binding.py",
    "app/learn/workflow_worker.py",
    "app/learn/hybrid/windows_process_scope.py",
    "app/core/model_server.py",
    "app/learn/hybrid/benchmark_v2_provider_corpus.py",
    "app/learn/hybrid/benchmark_v2_incumbent_operation.py",
    "app/learn/workflow_service.py",
    "app/api/panel.py",
)

TEST_SOURCE_PATHS = (
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding.py",
    "tests/test_learning_workflow_stage_worker.py",
    "tests/test_learn_hybrid_windows_process_scope.py",
    "tests/test_model_request_cancellation.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_incumbent.py",
    "tests/test_learning_workflow_stage_execution.py",
)

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SNAPSHOT_KEYS = {
    "production_source_sha256_by_path",
    "test_source_sha256_by_path",
}
_RESULT_KEYS = {
    "contract_version",
    "suite_id",
    "pytest_argv",
    "source_snapshot_sha256",
    "exit_code",
    "collected_count",
    "failed_count",
    "status",
    "safety",
    "content_sha256",
}
_REVIEW_KEYS = {
    "contract_version",
    "suite_id",
    "result_receipt_ref",
    "review_name",
    "review_file_sha256",
    "reviewer_identity_sha256",
    "reviewer_independent",
    "unresolved_findings",
    "status",
    "safety",
    "content_sha256",
}
_MANIFEST_KEYS = {
    "contract_version",
    "benchmark_release_id",
    "build_mode",
    "dependency_order",
    "result_receipt_refs",
    "review_receipt_refs",
    "production_sha256_by_path",
    "test_sha256_by_path",
    "safety",
    "content_sha256",
}
_REF_KEYS = {"contract_version", "file_sha256", "content_sha256"}
_ACTIVE_PLUGIN_CONFIG: Any | None = None


def compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def pretty_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def content_sha256(value: Mapping[str, Any]) -> str:
    body = {key: deepcopy(item) for key, item in value.items() if key != "content_sha256"}
    return hashlib.sha256(compact_json_bytes(body)).hexdigest()


def _sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result["content_sha256"] = content_sha256(result)
    return result


def artifact_ref(value: Mapping[str, Any]) -> dict[str, str]:
    contract_version = value.get("contract_version")
    digest = value.get("content_sha256")
    if not isinstance(contract_version, str) or not contract_version:
        raise ValueError("artifact contract_version is invalid")
    if not _is_sha256(digest) or digest != content_sha256(value):
        raise ValueError("artifact content_sha256 is invalid")
    return {
        "contract_version": contract_version,
        "file_sha256": hashlib.sha256(pretty_json_bytes(value)).hexdigest(),
        "content_sha256": digest,
    }


def write_create_new_or_byte_identical(path: Path, raw: bytes) -> None:
    output = _absolute_unresolved_path(path)
    _reject_alias_ancestors(output.parent, "output")
    if output.exists() or output.is_symlink():
        details = os.lstat(output)
        if (
            not stat.S_ISREG(details.st_mode)
            or output.is_symlink()
            or _is_reparse(details)
        ):
            raise FileExistsError("output exists but is not an ordinary file")
        if details.st_nlink != 1:
            raise FileExistsError("output exists as a hard-link alias")
        if output.read_bytes() != raw:
            raise FileExistsError("output exists with different bytes")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _HEX_SHA256.fullmatch(value) is not None


def _is_reparse(details: os.stat_result) -> bool:
    return bool(
        getattr(details, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _absolute_unresolved_path(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate


def _reject_alias_ancestors(path: Path, name: str) -> None:
    candidate = _absolute_unresolved_path(path)
    lineage = list(reversed((candidate, *candidate.parents)))
    for current in lineage:
        if not current.exists() and not current.is_symlink():
            continue
        details = os.lstat(current)
        if current.is_symlink() or _is_reparse(details):
            raise ValueError(f"{name} uses a symlink, junction, or reparse alias")


def _validated_root(root: Path) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute():
        raise ValueError("source root must be an absolute ordinary directory")
    _reject_alias_ancestors(candidate, "source root")
    details = os.lstat(candidate)
    if not stat.S_ISDIR(details.st_mode):
        raise ValueError("source root must be an ordinary directory")
    resolved = candidate.resolve(strict=True)
    if resolved != candidate:
        raise ValueError("source root is an alias before resolution")
    return candidate


def _closed_mapping(value: object, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{name} must have exactly the frozen fields")
    return value


def _canonical_nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative canonical integer")
    return value


def _normalized_paths(paths: Sequence[str], name: str) -> tuple[str, ...]:
    result = tuple(paths)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} contains duplicate paths")
    for item in result:
        parsed = PurePosixPath(item)
        if (
            not isinstance(item, str)
            or not item
            or "\\" in item
            or parsed.is_absolute()
            or parsed.as_posix() != item
            or any(part in {"", ".", ".."} for part in parsed.parts)
        ):
            raise ValueError(f"{name} contains a noncanonical relative POSIX path")
    return result


def _ordinary_file(root: Path, relative_path: str) -> Path:
    root_path = _validated_root(root)
    parsed = PurePosixPath(relative_path)
    candidate = root_path.joinpath(*parsed.parts)
    current = root_path
    for part in parsed.parts:
        current = current / part
        try:
            details = os.lstat(current)
        except OSError as exc:
            raise ValueError(f"source snapshot file is missing: {relative_path}") from exc
        if current.is_symlink() or _is_reparse(details):
            raise ValueError(f"source snapshot file uses an alias: {relative_path}")
    if not stat.S_ISREG(os.lstat(candidate).st_mode):
        raise ValueError(f"source snapshot path is not an ordinary file: {relative_path}")
    if os.lstat(candidate).st_nlink != 1:
        raise ValueError(f"source snapshot file is a hard-link alias: {relative_path}")
    return candidate


def capture_source_snapshot(
    *,
    root: Path = ROOT,
    production_paths: Sequence[str] = PRODUCTION_SOURCE_PATHS,
    test_paths: Sequence[str] = TEST_SOURCE_PATHS,
) -> dict[str, dict[str, str]]:
    production = _normalized_paths(production_paths, "production source paths")
    tests = _normalized_paths(test_paths, "test source paths")
    return {
        "production_source_sha256_by_path": {
            path: hashlib.sha256(_ordinary_file(root, path).read_bytes()).hexdigest()
            for path in production
        },
        "test_source_sha256_by_path": {
            path: hashlib.sha256(_ordinary_file(root, path).read_bytes()).hexdigest()
            for path in tests
        },
    }


def _validate_sha_map(value: object, paths: Sequence[str], name: str) -> dict[str, str]:
    expected = _normalized_paths(paths, f"{name} paths")
    if not isinstance(value, Mapping) or set(value) != set(expected):
        raise ValueError(f"source snapshot {name} map has key drift")
    result: dict[str, str] = {}
    for path in expected:
        digest = value[path]
        if not _is_sha256(digest):
            raise ValueError(f"source snapshot {name} digest is malformed")
        result[path] = digest
    return result


def validate_source_snapshot(
    source_snapshot: object,
    *,
    production_paths: Sequence[str] = PRODUCTION_SOURCE_PATHS,
    test_paths: Sequence[str] = TEST_SOURCE_PATHS,
) -> dict[str, dict[str, str]]:
    snapshot = _closed_mapping(source_snapshot, _SOURCE_SNAPSHOT_KEYS, "source snapshot")
    return {
        "production_source_sha256_by_path": _validate_sha_map(
            snapshot["production_source_sha256_by_path"],
            production_paths,
            "production",
        ),
        "test_source_sha256_by_path": _validate_sha_map(
            snapshot["test_source_sha256_by_path"],
            test_paths,
            "test",
        ),
    }


def source_snapshot_sha256(
    source_snapshot: object,
    *,
    production_paths: Sequence[str] = PRODUCTION_SOURCE_PATHS,
    test_paths: Sequence[str] = TEST_SOURCE_PATHS,
) -> str:
    validated = validate_source_snapshot(
        source_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    return hashlib.sha256(compact_json_bytes(validated)).hexdigest()


def _snapshot_paths(source_snapshot: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    snapshot = _closed_mapping(source_snapshot, _SOURCE_SNAPSHOT_KEYS, "source snapshot")
    production = snapshot["production_source_sha256_by_path"]
    tests = snapshot["test_source_sha256_by_path"]
    if not isinstance(production, Mapping) or not isinstance(tests, Mapping):
        raise ValueError("source snapshot maps are invalid")
    return tuple(production), tuple(tests)


def build_dependency_result_receipt(
    *,
    suite_id: str,
    pytest_argv: Sequence[str],
    pre_source_snapshot: Mapping[str, Any] | None,
    post_source_snapshot: Mapping[str, Any] | None,
    exit_code: int,
    collected_count: int,
    failed_count: int,
    session_integrity_passed: bool = True,
) -> dict[str, Any]:
    if suite_id not in FROZEN_PYTEST_ARGV_BY_SUITE_ID:
        raise ValueError("dependency result suite_id is unknown")
    _canonical_nonnegative_int(collected_count, "collected_count")
    _canonical_nonnegative_int(failed_count, "failed_count")
    if type(exit_code) is not int:
        raise ValueError("exit_code must be a canonical integer")
    if type(session_integrity_passed) is not bool:
        raise ValueError("session_integrity_passed must be boolean")

    pre_digest = "0" * 64
    snapshots_stable = False
    if pre_source_snapshot is not None and post_source_snapshot is not None:
        production_paths, test_paths = _snapshot_paths(pre_source_snapshot)
        try:
            pre_digest = source_snapshot_sha256(
                pre_source_snapshot,
                production_paths=production_paths,
                test_paths=test_paths,
            )
            post_digest = source_snapshot_sha256(
                post_source_snapshot,
                production_paths=production_paths,
                test_paths=test_paths,
            )
            snapshots_stable = pre_digest == post_digest
        except (KeyError, TypeError, ValueError):
            pre_digest = "0" * 64
            snapshots_stable = False

    argv = list(pytest_argv)
    passed = (
        argv == FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id]
        and snapshots_stable
        and exit_code == 0
        and collected_count > 0
        and failed_count == 0
        and session_integrity_passed
    )
    return _sealed(
        {
            "contract_version": RESULT_RECEIPT_CONTRACT,
            "suite_id": suite_id,
            "pytest_argv": argv,
            "source_snapshot_sha256": pre_digest,
            "exit_code": exit_code,
            "collected_count": collected_count,
            "failed_count": failed_count,
            "status": "PASS" if passed else "FAIL",
            "safety": deepcopy(SAFETY),
        }
    )


def validate_dependency_result_receipt(
    receipt: object,
    *,
    expected_suite_id: str | None = None,
    expected_ref: object | None = None,
    current_source_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    value = _closed_mapping(receipt, _RESULT_KEYS, "dependency result receipt")
    if value["contract_version"] != RESULT_RECEIPT_CONTRACT:
        raise ValueError("dependency result receipt contract is invalid")
    suite_id = value["suite_id"]
    if suite_id not in FROZEN_PYTEST_ARGV_BY_SUITE_ID or (
        expected_suite_id is not None and suite_id != expected_suite_id
    ):
        raise ValueError("dependency result receipt suite_id is invalid")
    argv = value["pytest_argv"]
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ValueError("dependency result receipt pytest_argv is invalid")
    if argv != FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id]:
        if value["status"] == "PASS":
            raise ValueError("PASS dependency result receipt pytest_argv is not frozen")
    if not _is_sha256(value["source_snapshot_sha256"]):
        raise ValueError("dependency result receipt source_snapshot_sha256 is malformed")
    if current_source_snapshot_sha256 is not None and (
        not _is_sha256(current_source_snapshot_sha256)
        or value["source_snapshot_sha256"] != current_source_snapshot_sha256
    ):
        raise ValueError("dependency result receipt differs from current source snapshot")
    exit_code = value["exit_code"]
    if type(exit_code) is not int:
        raise ValueError("dependency result receipt exit_code is invalid")
    collected = _canonical_nonnegative_int(value["collected_count"], "collected_count")
    failed = _canonical_nonnegative_int(value["failed_count"], "failed_count")
    if value["safety"] != SAFETY:
        raise ValueError("dependency result receipt safety is invalid")
    if value["status"] not in {"PASS", "FAIL"}:
        raise ValueError("dependency result receipt status is invalid")
    basic_pass = argv == FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id] and exit_code == 0 and collected > 0 and failed == 0
    if value["status"] == "PASS" and not basic_pass:
        raise ValueError("dependency result receipt PASS status is inconsistent")
    if value["content_sha256"] != content_sha256(value):
        raise ValueError("dependency result receipt content_sha256 is invalid")
    result = deepcopy(dict(value))
    if expected_ref is not None:
        _validate_ref(expected_ref, artifact_ref(result), "dependency result receipt ref")
    return result


def _validate_ref(value: object, expected: Mapping[str, str], name: str) -> dict[str, str]:
    ref = _closed_mapping(value, _REF_KEYS, name)
    if any(not isinstance(ref[key], str) for key in _REF_KEYS) or dict(ref) != dict(expected):
        raise ValueError(f"{name} is invalid")
    return deepcopy(dict(ref))


def build_dependency_review_receipt(
    *,
    suite_id: str,
    result_receipt: Mapping[str, Any],
    result_receipt_ref: Mapping[str, str],
    review_name: str,
    review_file_sha256: str,
    reviewer_identity_sha256: str,
    reviewer_independent: bool,
    unresolved_findings: Mapping[str, int],
) -> dict[str, Any]:
    result = validate_dependency_result_receipt(
        result_receipt,
        expected_suite_id=suite_id,
        expected_ref=result_receipt_ref,
    )
    if review_name != REVIEW_NAME_BY_SUITE_ID.get(suite_id):
        raise ValueError("dependency review receipt review_name is invalid")
    if not _is_sha256(review_file_sha256) or not _is_sha256(reviewer_identity_sha256):
        raise ValueError("dependency review receipt SHA-256 is invalid")
    findings = _closed_mapping(
        unresolved_findings,
        {"critical", "important"},
        "unresolved_findings",
    )
    critical = _canonical_nonnegative_int(findings["critical"], "critical")
    important = _canonical_nonnegative_int(findings["important"], "important")
    if type(reviewer_independent) is not bool:
        raise ValueError("reviewer_independent must be boolean")
    passed = (
        result["status"] == "PASS"
        and reviewer_independent
        and critical == 0
        and important == 0
    )
    return _sealed(
        {
            "contract_version": REVIEW_RECEIPT_CONTRACT,
            "suite_id": suite_id,
            "result_receipt_ref": deepcopy(dict(result_receipt_ref)),
            "review_name": review_name,
            "review_file_sha256": review_file_sha256,
            "reviewer_identity_sha256": reviewer_identity_sha256,
            "reviewer_independent": reviewer_independent,
            "unresolved_findings": {"critical": critical, "important": important},
            "status": "PASS" if passed else "FAIL",
            "safety": deepcopy(SAFETY),
        }
    )


def validate_dependency_review_receipt(
    receipt: object,
    *,
    expected_suite_id: str,
    expected_result_receipt: Mapping[str, Any],
    expected_result_ref: Mapping[str, str],
    expected_ref: object | None = None,
) -> dict[str, Any]:
    value = _closed_mapping(receipt, _REVIEW_KEYS, "dependency review receipt")
    if value["contract_version"] != REVIEW_RECEIPT_CONTRACT or value["suite_id"] != expected_suite_id:
        raise ValueError("dependency review receipt identity is invalid")
    result = validate_dependency_result_receipt(
        expected_result_receipt,
        expected_suite_id=expected_suite_id,
        expected_ref=expected_result_ref,
    )
    _validate_ref(value["result_receipt_ref"], expected_result_ref, "review result receipt ref")
    if value["review_name"] != REVIEW_NAME_BY_SUITE_ID[expected_suite_id]:
        raise ValueError("dependency review receipt review_name is invalid")
    if not _is_sha256(value["review_file_sha256"]) or not _is_sha256(value["reviewer_identity_sha256"]):
        raise ValueError("dependency review receipt SHA-256 is invalid")
    if type(value["reviewer_independent"]) is not bool:
        raise ValueError("dependency review receipt reviewer_independent is invalid")
    findings = _closed_mapping(value["unresolved_findings"], {"critical", "important"}, "unresolved_findings")
    critical = _canonical_nonnegative_int(findings["critical"], "critical")
    important = _canonical_nonnegative_int(findings["important"], "important")
    expected_status = "PASS" if result["status"] == "PASS" and value["reviewer_independent"] and critical == 0 and important == 0 else "FAIL"
    if value["status"] != expected_status or value["safety"] != SAFETY:
        raise ValueError("dependency review receipt status or safety is invalid")
    if value["content_sha256"] != content_sha256(value):
        raise ValueError("dependency review receipt content_sha256 is invalid")
    result_value = deepcopy(dict(value))
    if expected_ref is not None:
        _validate_ref(expected_ref, artifact_ref(result_value), "dependency review receipt ref")
    return result_value


def _exact_suite_map(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(DEPENDENCY_ORDER):
        raise ValueError(f"{name} must have the exact five dependency keys")
    return value


def _assemble_dependency_manifest(
    *,
    benchmark_release_id: str,
    result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    result_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    review_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    review_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    current: Mapping[str, Any],
    production_paths: Sequence[str],
    test_paths: Sequence[str],
    build_mode: str,
) -> dict[str, Any]:
    if not isinstance(benchmark_release_id, str) or not benchmark_release_id:
        raise ValueError("benchmark_release_id is invalid")
    current = validate_source_snapshot(
        deepcopy(current),
        production_paths=production_paths,
        test_paths=test_paths,
    )
    current_digest = source_snapshot_sha256(current, production_paths=production_paths, test_paths=test_paths)
    results = deepcopy(dict(_exact_suite_map(result_receipts_by_suite, "result receipts")))
    result_refs = deepcopy(dict(_exact_suite_map(result_receipt_refs_by_suite, "result receipt refs")))
    reviews = deepcopy(dict(_exact_suite_map(review_receipts_by_suite, "review receipts")))
    review_refs = deepcopy(dict(_exact_suite_map(review_receipt_refs_by_suite, "review receipt refs")))
    for suite_id in DEPENDENCY_ORDER:
        result = validate_dependency_result_receipt(
            results[suite_id],
            expected_suite_id=suite_id,
            expected_ref=result_refs[suite_id],
            current_source_snapshot_sha256=current_digest,
        )
        if result["status"] != "PASS":
            raise ValueError("dependency result receipt is not PASS")
        review = validate_dependency_review_receipt(
            reviews[suite_id],
            expected_suite_id=suite_id,
            expected_result_receipt=result,
            expected_result_ref=result_refs[suite_id],
            expected_ref=review_refs[suite_id],
        )
        if review["status"] != "PASS":
            raise ValueError("dependency review receipt is not PASS")
    manifest = _sealed(
        {
            "contract_version": DEPENDENCY_MANIFEST_CONTRACT,
            "benchmark_release_id": benchmark_release_id,
            "build_mode": build_mode,
            "dependency_order": list(DEPENDENCY_ORDER),
            "result_receipt_refs": deepcopy(dict(result_refs)),
            "review_receipt_refs": deepcopy(dict(review_refs)),
            "production_sha256_by_path": deepcopy(current["production_source_sha256_by_path"]),
            "test_sha256_by_path": deepcopy(current["test_source_sha256_by_path"]),
            "safety": deepcopy(SAFETY),
        }
    )
    validator = (
        validate_release_dependency_manifest
        if build_mode == "release"
        else _validate_synthetic_dependency_manifest_for_test
    )
    return validator(
        manifest,
        result_receipts_by_suite=results,
        result_receipt_refs_by_suite=result_refs,
        review_receipts_by_suite=reviews,
        review_receipt_refs_by_suite=review_refs,
        current_source_snapshot=current,
        production_paths=production_paths,
        test_paths=test_paths,
    )


def _build_synthetic_dependency_manifest_for_test(
    *,
    benchmark_release_id: str,
    result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    result_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    review_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    review_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    source_snapshot: Mapping[str, Any],
    production_paths: Sequence[str],
    test_paths: Sequence[str],
) -> dict[str, Any]:
    return _assemble_dependency_manifest(
        benchmark_release_id=benchmark_release_id,
        result_receipts_by_suite=result_receipts_by_suite,
        result_receipt_refs_by_suite=result_receipt_refs_by_suite,
        review_receipts_by_suite=review_receipts_by_suite,
        review_receipt_refs_by_suite=review_receipt_refs_by_suite,
        current=source_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
        build_mode="synthetic_test",
    )


def build_release_dependency_manifest(*, benchmark_release_id: str) -> dict[str, Any]:
    results, result_refs, reviews, review_refs = (
        _load_canonical_release_dependency_evidence()
    )
    return _assemble_dependency_manifest(
        benchmark_release_id=benchmark_release_id,
        result_receipts_by_suite=results,
        result_receipt_refs_by_suite=result_refs,
        review_receipts_by_suite=reviews,
        review_receipt_refs_by_suite=review_refs,
        current=capture_source_snapshot(),
        production_paths=PRODUCTION_SOURCE_PATHS,
        test_paths=TEST_SOURCE_PATHS,
        build_mode="release",
    )


def _validate_dependency_manifest(
    manifest: object,
    *,
    result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    result_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    review_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    review_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    current_source_snapshot: Mapping[str, Any],
    production_paths: Sequence[str] = PRODUCTION_SOURCE_PATHS,
    test_paths: Sequence[str] = TEST_SOURCE_PATHS,
    required_build_mode: str,
) -> dict[str, Any]:
    value = _closed_mapping(manifest, _MANIFEST_KEYS, "dependency manifest")
    if value["contract_version"] != DEPENDENCY_MANIFEST_CONTRACT:
        raise ValueError("dependency manifest contract is invalid")
    if not isinstance(value["benchmark_release_id"], str) or not value["benchmark_release_id"]:
        raise ValueError("dependency manifest release is invalid")
    if value["build_mode"] != required_build_mode:
        raise ValueError("dependency manifest requires release build mode")
    if value["dependency_order"] != list(DEPENDENCY_ORDER):
        raise ValueError("dependency manifest DAG is invalid")
    current = validate_source_snapshot(current_source_snapshot, production_paths=production_paths, test_paths=test_paths)
    if value["production_sha256_by_path"] != current["production_source_sha256_by_path"] or value["test_sha256_by_path"] != current["test_source_sha256_by_path"]:
        raise ValueError("dependency manifest current source snapshot mismatch")
    current_digest = source_snapshot_sha256(current, production_paths=production_paths, test_paths=test_paths)
    results = _exact_suite_map(result_receipts_by_suite, "result receipts")
    result_refs = _exact_suite_map(result_receipt_refs_by_suite, "result receipt refs")
    reviews = _exact_suite_map(review_receipts_by_suite, "review receipts")
    review_refs = _exact_suite_map(review_receipt_refs_by_suite, "review receipt refs")
    if value["result_receipt_refs"] != result_refs or value["review_receipt_refs"] != review_refs:
        raise ValueError("dependency manifest receipt-ref map mismatch")
    for suite_id in DEPENDENCY_ORDER:
        result = validate_dependency_result_receipt(
            results[suite_id],
            expected_suite_id=suite_id,
            expected_ref=result_refs[suite_id],
            current_source_snapshot_sha256=current_digest,
        )
        if result["status"] != "PASS":
            raise ValueError("dependency result receipt is not PASS")
        review = validate_dependency_review_receipt(
            reviews[suite_id],
            expected_suite_id=suite_id,
            expected_result_receipt=result,
            expected_result_ref=result_refs[suite_id],
            expected_ref=review_refs[suite_id],
        )
        if review["status"] != "PASS":
            raise ValueError("dependency review receipt is not PASS")
    if value["safety"] != SAFETY or value["content_sha256"] != content_sha256(value):
        raise ValueError("dependency manifest safety or content hash is invalid")
    return deepcopy(dict(value))


def validate_release_dependency_manifest(
    manifest: object,
    *,
    result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    result_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    review_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    review_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    current_source_snapshot: Mapping[str, Any],
    production_paths: Sequence[str] = PRODUCTION_SOURCE_PATHS,
    test_paths: Sequence[str] = TEST_SOURCE_PATHS,
) -> dict[str, Any]:
    return _validate_dependency_manifest(
        manifest,
        result_receipts_by_suite=result_receipts_by_suite,
        result_receipt_refs_by_suite=result_receipt_refs_by_suite,
        review_receipts_by_suite=review_receipts_by_suite,
        review_receipt_refs_by_suite=review_receipt_refs_by_suite,
        current_source_snapshot=current_source_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
        required_build_mode="release",
    )


def _validate_synthetic_dependency_manifest_for_test(
    manifest: object,
    *,
    result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    result_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    review_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    review_receipt_refs_by_suite: Mapping[str, Mapping[str, str]],
    current_source_snapshot: Mapping[str, Any],
    production_paths: Sequence[str],
    test_paths: Sequence[str],
) -> dict[str, Any]:
    return _validate_dependency_manifest(
        manifest,
        result_receipts_by_suite=result_receipts_by_suite,
        result_receipt_refs_by_suite=result_receipt_refs_by_suite,
        review_receipts_by_suite=review_receipts_by_suite,
        review_receipt_refs_by_suite=review_receipt_refs_by_suite,
        current_source_snapshot=current_source_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
        required_build_mode="synthetic_test",
    )


def validate_dependency_manifest_for_final_report(
    manifest: object,
) -> dict[str, Any]:
    if isinstance(manifest, Mapping) and manifest.get("build_mode") != "release":
        raise ValueError("final report requires dependency manifest release build mode")
    results, result_refs, reviews, review_refs = (
        _load_canonical_release_dependency_evidence()
    )
    return validate_release_dependency_manifest(
        manifest,
        result_receipts_by_suite=results,
        result_receipt_refs_by_suite=result_refs,
        review_receipts_by_suite=reviews,
        review_receipt_refs_by_suite=review_refs,
        current_source_snapshot=capture_source_snapshot(),
    )


def validate_final_seal_source_binding(
    *,
    sealed_production_sha256_by_path: Mapping[str, str],
    sealed_test_sha256_by_path: Mapping[str, str],
    dependency_manifest: Mapping[str, Any],
) -> None:
    if dependency_manifest.get("build_mode") != "release":
        raise ValueError("final seal requires a release dependency manifest")
    results, result_refs, reviews, review_refs = (
        _load_canonical_release_dependency_evidence()
    )
    task12, task12_ref, task12_review, task12_review_ref = (
        _load_canonical_task12_acceptance_evidence()
    )
    current = capture_source_snapshot()
    validate_release_dependency_manifest(
        dependency_manifest,
        result_receipts_by_suite=results,
        result_receipt_refs_by_suite=result_refs,
        review_receipts_by_suite=reviews,
        review_receipt_refs_by_suite=review_refs,
        current_source_snapshot=current,
    )
    expected_production = current["production_source_sha256_by_path"]
    expected_tests = current["test_source_sha256_by_path"]
    if dict(sealed_production_sha256_by_path) != expected_production or dict(sealed_test_sha256_by_path) != expected_tests:
        raise ValueError("final seal source snapshot differs from current source")
    current_digest = source_snapshot_sha256(current)
    task12 = validate_dependency_result_receipt(
        task12,
        expected_suite_id="task12_release_gate_v1",
        expected_ref=task12_ref,
        current_source_snapshot_sha256=current_digest,
    )
    if task12["status"] != "PASS":
        raise ValueError("final seal Task 12 result is not PASS")
    review = validate_dependency_review_receipt(
        task12_review,
        expected_suite_id="task12_release_gate_v1",
        expected_result_receipt=task12,
        expected_result_ref=task12_ref,
        expected_ref=task12_review_ref,
    )
    if review["status"] != "PASS":
        raise ValueError("final seal Task 12 review is not PASS")


def _validate_synthetic_final_seal_source_binding_for_test(
    *,
    sealed_production_sha256_by_path: Mapping[str, str],
    sealed_test_sha256_by_path: Mapping[str, str],
    dependency_manifest: Mapping[str, Any],
    dependency_result_receipts_by_suite: Mapping[str, Mapping[str, Any]],
    task12_result_receipt: Mapping[str, Any],
    current_source_snapshot: Mapping[str, Any],
    production_paths: Sequence[str],
    test_paths: Sequence[str],
) -> None:
    current = validate_source_snapshot(
        current_source_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    expected_production = current["production_source_sha256_by_path"]
    expected_tests = current["test_source_sha256_by_path"]
    if dict(sealed_production_sha256_by_path) != expected_production or dict(
        sealed_test_sha256_by_path
    ) != expected_tests:
        raise ValueError("final seal source snapshot differs from current source")
    if dependency_manifest.get("build_mode") != "synthetic_test":
        raise ValueError("synthetic final-seal test requires synthetic_test mode")
    if dependency_manifest.get("production_sha256_by_path") != expected_production or dependency_manifest.get("test_sha256_by_path") != expected_tests:
        raise ValueError("final seal source snapshot differs from dependency manifest")
    current_digest = source_snapshot_sha256(
        current,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    for suite_id, result in _exact_suite_map(
        dependency_result_receipts_by_suite, "dependency result receipts"
    ).items():
        validated = validate_dependency_result_receipt(
            result,
            expected_suite_id=suite_id,
            current_source_snapshot_sha256=current_digest,
        )
        if validated["status"] != "PASS":
            raise ValueError("final seal dependency result is not PASS")
    task12 = validate_dependency_result_receipt(
        task12_result_receipt,
        expected_suite_id="task12_release_gate_v1",
        current_source_snapshot_sha256=current_digest,
    )
    if task12["status"] != "PASS":
        raise ValueError("final seal Task 12 result is not PASS")


def semantic_pytest_argv(pytest_arguments: Sequence[str]) -> list[str]:
    arguments = list(pytest_arguments)
    semantic: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "-p" and index + 1 < len(arguments) and arguments[index + 1] == PYTEST_PLUGIN_NAME:
            index += 2
            continue
        if token == f"-p={PYTEST_PLUGIN_NAME}":
            index += 1
            continue
        if token in {PYTEST_SUITE_OPTION, PYTEST_RECEIPT_OPTION}:
            if index + 1 >= len(arguments):
                raise ValueError(f"missing value for plugin transport option: {token}")
            index += 2
            continue
        if token.startswith(PYTEST_SUITE_OPTION + "=") or token.startswith(PYTEST_RECEIPT_OPTION + "="):
            index += 1
            continue
        semantic.append(token)
        index += 1
    return ["pytest", *semantic]


def _explicit_plugin_transport_present(pytest_arguments: Sequence[str]) -> bool:
    arguments = list(pytest_arguments)
    return any(
        token == f"-p={PYTEST_PLUGIN_NAME}"
        or (
            token == "-p"
            and index + 1 < len(arguments)
            and arguments[index + 1] == PYTEST_PLUGIN_NAME
        )
        for index, token in enumerate(arguments)
    )


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("benchmark-v2-dependency-receipt")
    group.addoption(PYTEST_SUITE_OPTION, action="store", default=None)
    group.addoption(PYTEST_RECEIPT_OPTION, action="store", default=None)


def pytest_configure(config: Any) -> None:
    global _ACTIVE_PLUGIN_CONFIG
    suite_id = config.getoption(PYTEST_SUITE_OPTION)
    output = config.getoption(PYTEST_RECEIPT_OPTION)
    explicitly_loaded = _explicit_plugin_transport_present(config.invocation_params.args)
    if suite_id is None and output is None:
        if explicitly_loaded:
            raise ValueError("Benchmark v2 receipt plugin requires both transport options")
        config._benchmark_v2_dependency_receipt_active = False
        return
    if suite_id is None or output is None:
        raise ValueError("Benchmark v2 receipt plugin requires both transport options")
    if not explicitly_loaded:
        raise ValueError("Benchmark v2 receipt plugin must be explicitly loaded with -p")
    if suite_id not in FROZEN_PYTEST_ARGV_BY_SUITE_ID:
        raise ValueError("Benchmark v2 receipt plugin suite ID is unknown")
    if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1":
        raise ValueError("Benchmark v2 receipt plugin requires external plugin autoload disabled")
    if os.environ.get("PYTEST_ADDOPTS"):
        raise ValueError("PYTEST_ADDOPTS cannot alter the frozen pytest semantics")
    if os.environ.get("PYTEST_PLUGINS"):
        raise ValueError("PYTEST_PLUGINS cannot alter the frozen pytest semantics")
    configured_addopts = config.getini("addopts")
    if configured_addopts:
        raise ValueError("configured pytest addopts cannot alter the frozen suite")
    if config.pluginmanager.list_plugin_distinfo():
        raise ValueError("foreign pytest distribution plugins are forbidden")
    config._benchmark_v2_dependency_receipt_active = True
    config._benchmark_v2_dependency_suite_id = suite_id
    config._benchmark_v2_dependency_output = Path(output)
    config._benchmark_v2_dependency_pytest_argv = semantic_pytest_argv(
        config.invocation_params.args
    )
    config._benchmark_v2_dependency_pre_snapshot = None
    config._benchmark_v2_dependency_pre_error = None
    config._benchmark_v2_dependency_collection_closed = False
    config._benchmark_v2_dependency_collection_valid = False
    config._benchmark_v2_dependency_collection_nodeids = set()
    config._benchmark_v2_dependency_terminal_nodeids = set()
    config._benchmark_v2_dependency_unexpected_deselection = False
    _ACTIVE_PLUGIN_CONFIG = config


def pytest_sessionstart(session: Any) -> None:
    config = session.config
    if not getattr(config, "_benchmark_v2_dependency_receipt_active", False):
        return
    try:
        config._benchmark_v2_dependency_pre_snapshot = capture_source_snapshot()
    except (OSError, TypeError, ValueError) as exc:
        config._benchmark_v2_dependency_pre_error = f"{type(exc).__name__}: {exc}"


def _frozen_test_files(suite_id: str) -> set[str]:
    return {
        token
        for token in FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id]
        if token.startswith("tests/") and token.endswith(".py")
    }


def _foreign_collection_hook_present(config: Any) -> bool:
    current_module = sys.modules[__name__]
    pytest_core = sys.modules.get("_pytest")
    pytest_core_root = (
        Path(pytest_core.__file__).resolve(strict=True).parent
        if pytest_core is not None and getattr(pytest_core, "__file__", None)
        else None
    )
    canonical_conftest = (ROOT / "tests/conftest.py").resolve(strict=True)
    for plugin in config.pluginmanager.get_plugins():
        if plugin is current_module:
            continue
        hook_names = {
            name
            for name in dir(plugin)
            if name.startswith("pytest_") and callable(getattr(plugin, name, None))
        }
        if not hook_names:
            continue
        plugin_module_name = (
            getattr(plugin, "__name__", "")
            if isinstance(plugin, type(sys))
            else getattr(type(plugin), "__module__", "")
        )
        origin_module = sys.modules.get(plugin_module_name)
        origin_file = getattr(origin_module, "__file__", None)
        if (
            plugin_module_name.startswith("_pytest.")
            and origin_module is not None
            and origin_file is not None
            and pytest_core_root is not None
        ):
            origin_path = Path(origin_file).resolve(strict=True)
            origin_identity_valid = (
                plugin is origin_module
                if isinstance(plugin, type(sys))
                else getattr(origin_module, type(plugin).__name__, None) is type(plugin)
            )
            if origin_identity_valid and (
                origin_path == pytest_core_root or pytest_core_root in origin_path.parents
            ):
                continue
        if origin_file is not None and Path(origin_file).resolve(strict=True) == canonical_conftest:
            return True
        return True
    return False


def pytest_collection_finish(session: Any) -> None:
    config = session.config
    if not getattr(config, "_benchmark_v2_dependency_receipt_active", False):
        return
    nodeids = [str(getattr(item, "nodeid", "")) for item in session.items]
    nodeid_set = set(nodeids)
    expected_files = _frozen_test_files(config._benchmark_v2_dependency_suite_id)
    actual_files = {
        nodeid.split("::", 1)[0].replace("\\", "/")
        for nodeid in nodeids
        if nodeid
    }
    config._benchmark_v2_dependency_collection_nodeids = nodeid_set
    config._benchmark_v2_dependency_collection_valid = (
        bool(nodeids)
        and len(nodeids) == len(nodeid_set)
        and actual_files == expected_files
        and not _foreign_collection_hook_present(config)
        and not config._benchmark_v2_dependency_unexpected_deselection
    )
    config._benchmark_v2_dependency_collection_closed = True


def pytest_deselected(items: Sequence[Any]) -> None:
    config = _ACTIVE_PLUGIN_CONFIG
    if config is None or not getattr(
        config, "_benchmark_v2_dependency_receipt_active", False
    ):
        return
    frozen = FROZEN_PYTEST_ARGV_BY_SUITE_ID[config._benchmark_v2_dependency_suite_id]
    if items and "-k" not in frozen:
        config._benchmark_v2_dependency_unexpected_deselection = True


def pytest_runtest_logreport(report: Any) -> None:
    config = _ACTIVE_PLUGIN_CONFIG
    if config is None or not getattr(
        config, "_benchmark_v2_dependency_receipt_active", False
    ):
        return
    terminal = report.when == "call" or (
        report.when == "setup" and (report.failed or report.skipped)
    )
    if terminal:
        config._benchmark_v2_dependency_terminal_nodeids.add(str(report.nodeid))


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    global _ACTIVE_PLUGIN_CONFIG
    config = session.config
    if not getattr(config, "_benchmark_v2_dependency_receipt_active", False):
        return
    post_snapshot = None
    try:
        post_snapshot = capture_source_snapshot()
    except (OSError, TypeError, ValueError):
        post_snapshot = None
    collection_nodeids = config._benchmark_v2_dependency_collection_nodeids
    session_integrity_passed = (
        config._benchmark_v2_dependency_collection_closed
        and config._benchmark_v2_dependency_collection_valid
        and collection_nodeids
        == config._benchmark_v2_dependency_terminal_nodeids
    )
    receipt = build_dependency_result_receipt(
        suite_id=config._benchmark_v2_dependency_suite_id,
        pytest_argv=config._benchmark_v2_dependency_pytest_argv,
        pre_source_snapshot=config._benchmark_v2_dependency_pre_snapshot,
        post_source_snapshot=post_snapshot,
        exit_code=int(exitstatus),
        collected_count=len(getattr(session, "items", ())),
        failed_count=int(getattr(session, "testsfailed", 0)),
        session_integrity_passed=bool(session_integrity_passed),
    )
    write_create_new_or_byte_identical(
        config._benchmark_v2_dependency_output,
        pretty_json_bytes(receipt),
    )
    _ACTIVE_PLUGIN_CONFIG = None


def _load_pretty_artifact(path: Path, name: str) -> dict[str, Any]:
    artifact_path = _ordinary_artifact_path(path, name)
    raw = artifact_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not UTF-8 JSON") from exc
    if not isinstance(value, dict) or raw != pretty_json_bytes(value):
        raise ValueError(f"{name} bytes are not canonical pretty UTF-8 JSON plus LF")
    return value


def _ordinary_artifact_path(path: Path, name: str) -> Path:
    candidate = _absolute_unresolved_path(path)
    _reject_alias_ancestors(candidate.parent, name)
    try:
        details = os.lstat(candidate)
    except OSError as exc:
        raise ValueError(f"{name} is missing") from exc
    if (
        candidate.is_symlink()
        or _is_reparse(details)
        or not stat.S_ISREG(details.st_mode)
    ):
        raise ValueError(f"{name} is not an ordinary file")
    if details.st_nlink != 1:
        raise ValueError(f"{name} is a hard-link alias")
    return candidate


def _validate_actual_review_file(
    *, suite_id: str, review_receipt: Mapping[str, Any], review_file_path: Path
) -> None:
    path = _ordinary_artifact_path(review_file_path, f"actual review file {suite_id}")
    if path.name != REVIEW_NAME_BY_SUITE_ID[suite_id]:
        raise ValueError("actual review file basename is invalid")
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("actual review file is not UTF-8") from exc
    if not text or hashlib.sha256(raw).hexdigest() != review_receipt.get(
        "review_file_sha256"
    ):
        raise ValueError("actual review file bytes do not match the review receipt")


def _load_canonical_release_dependency_evidence() -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, str]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, str]],
]:
    current = capture_source_snapshot()
    current_digest = source_snapshot_sha256(current)
    results: dict[str, Mapping[str, Any]] = {}
    result_refs: dict[str, Mapping[str, str]] = {}
    reviews: dict[str, Mapping[str, Any]] = {}
    review_refs: dict[str, Mapping[str, str]] = {}
    for suite_id in DEPENDENCY_ORDER:
        result = _load_pretty_artifact(
            _CANONICAL_EVIDENCE_ROOT / suite_id / "result-receipt.json",
            f"result receipt {suite_id}",
        )
        result_ref = artifact_ref(result)
        result = validate_dependency_result_receipt(
            result,
            expected_suite_id=suite_id,
            expected_ref=result_ref,
            current_source_snapshot_sha256=current_digest,
        )
        if result["status"] != "PASS":
            raise ValueError("loaded production dependency result is not PASS")
        review = _load_pretty_artifact(
            _CANONICAL_EVIDENCE_ROOT / suite_id / "review-receipt.json",
            f"review receipt {suite_id}",
        )
        review_ref = artifact_ref(review)
        review = validate_dependency_review_receipt(
            review,
            expected_suite_id=suite_id,
            expected_result_receipt=result,
            expected_result_ref=result_ref,
            expected_ref=review_ref,
        )
        if review["status"] != "PASS":
            raise ValueError("loaded production dependency review is not PASS")
        _validate_actual_review_file(
            suite_id=suite_id,
            review_receipt=review,
            review_file_path=_CANONICAL_REVIEW_ROOT
            / REVIEW_NAME_BY_SUITE_ID[suite_id],
        )
        results[suite_id] = result
        result_refs[suite_id] = result_ref
        reviews[suite_id] = review
        review_refs[suite_id] = review_ref
    return results, result_refs, reviews, review_refs


def _load_canonical_task12_acceptance_evidence() -> tuple[
    Mapping[str, Any],
    Mapping[str, str],
    Mapping[str, Any],
    Mapping[str, str],
]:
    suite_id = "task12_release_gate_v1"
    current_digest = source_snapshot_sha256(capture_source_snapshot())
    result = _load_pretty_artifact(
        _CANONICAL_EVIDENCE_ROOT / suite_id / "result-receipt.json",
        "Task 12 result receipt",
    )
    result_ref = artifact_ref(result)
    result = validate_dependency_result_receipt(
        result,
        expected_suite_id="task12_release_gate_v1",
        expected_ref=result_ref,
        current_source_snapshot_sha256=current_digest,
    )
    if result["status"] != "PASS":
        raise ValueError("Task 12 result receipt is not PASS")
    review = _load_pretty_artifact(
        _CANONICAL_EVIDENCE_ROOT / suite_id / "review-receipt.json",
        "Task 12 review receipt",
    )
    review_ref = artifact_ref(review)
    review = validate_dependency_review_receipt(
        review,
        expected_suite_id="task12_release_gate_v1",
        expected_result_receipt=result,
        expected_result_ref=result_ref,
        expected_ref=review_ref,
    )
    if review["status"] != "PASS":
        raise ValueError("Task 12 review receipt is not PASS")
    _validate_actual_review_file(
        suite_id="task12_release_gate_v1",
        review_receipt=review,
        review_file_path=_CANONICAL_REVIEW_ROOT / REVIEW_NAME_BY_SUITE_ID[suite_id],
    )
    return result, result_ref, review, review_ref


def _cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--build-dependency-manifest", action="store_true")
    modes.add_argument("--validate-final-report-dependency", action="store_true")
    parser.add_argument("--benchmark-release-id")
    parser.add_argument("--dependency-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _cli_parser().parse_args(argv)
    if args.build_dependency_manifest:
        if args.dependency_manifest is not None or args.benchmark_release_id is None or args.output is None:
            raise ValueError("build mode requires release ID and output only")
        manifest = build_release_dependency_manifest(
            benchmark_release_id=args.benchmark_release_id,
        )
        write_create_new_or_byte_identical(args.output, pretty_json_bytes(manifest))
        sys.stdout.write(compact_json_bytes({"dependency_manifest_ref": artifact_ref(manifest), "status": "PASS"}).decode("utf-8") + "\n")
        return 0
    if args.dependency_manifest is None or args.output is not None or args.benchmark_release_id is not None:
        raise ValueError("final-report dependency validation requires --dependency-manifest only")
    manifest = _load_pretty_artifact(args.dependency_manifest, "dependency manifest")
    validate_dependency_manifest_for_final_report(
        manifest,
    )
    sys.stdout.write(compact_json_bytes({"dependency_manifest_ref": artifact_ref(manifest), "status": "PASS"}).decode("utf-8") + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(2) from exc
