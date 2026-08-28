from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.learn.hybrid.benchmark_v2_contracts import (
    BENCHMARK_RELEASE_ID,
    PARENT_REF,
    PROVIDER_CORPUS_CONTRACT,
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_durable_claim import IDENTITY, claim_id
from app.learn.hybrid.benchmark_v2_provider_corpus import validate_provider_manifest


ROOT = Path(__file__).resolve().parents[1]
SEALER_PATH = ROOT / "scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py"
PARENT_PATH = "tests/fixtures/portfolio_hybrid_v1_1/corpus-manifest.v1.json"
TEMPLATE_PATH = "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-manifest.template.json"
PROVIDER_PATH = "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/provider-corpus.candidate.json"

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
FUTURE_PATHS = (
    "scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "scripts/authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    "tests/test_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
    "scripts/assemble_portfolio_hybrid_v1_1_benchmark_v2_report.py",
    "tests/test_portfolio_hybrid_v1_1_release_gate_v2.py",
)
BOOT_REFS = (
    ("bootstrap", "app/learn/hybrid/benchmark_v2_provider_sandbox.py"),
    ("contracts", "app/learn/hybrid/benchmark_v2_contracts.py"),
    ("corpus_loader", "app/learn/hybrid/benchmark_v2_provider_corpus.py"),
)
RELEASE_REFS = (
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
    ("builtin_learning_projection", "app/learn/recognition/uei/builtin_learning_projection.py"),
    ("omniparser_shadow_adapter", "app/learn/recognition/uei/omniparser_shadow_adapter.py"),
    ("uei_projections", "app/learn/recognition/uei/projections.py"),
    ("workflow_service", "app/learn/workflow_service.py"),
    ("workflow_worker", "app/learn/workflow_worker.py"),
    ("screen_reader", "app/operation/observe/screen_reader.py"),
    ("test_window", "scripts/portfolio_hybrid_v1_1_test_window_v2.py"),
    ("benchmark_runner", "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py"),
)


def _load_sealer():
    assert SEALER_PATH.is_file(), "Task 10 split sealer has not been implemented"
    spec = importlib.util.spec_from_file_location("benchmark_v2_split_sealer", SEALER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def sealer():
    return _load_sealer()


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _provider_corpus(parent: dict[str, object]) -> dict[str, object]:
    screens = {item["screen_id"]: item for item in parent["screenshots"]}
    cases = []
    for target in parent["gold_records"]:
        screen = screens[target["screen_id"]]
        screen_id = screen["screen_id"]
        target_id = target["target_id"]
        cases.append(
            {
                "case_id": hashlib.sha256(
                    f"benchmark-v2-case\0{screen_id}\0{target_id}".encode()
                ).hexdigest(),
                "partition": screen["partition"],
                "screen_group": hashlib.sha256(
                    f"benchmark-v2-screen-group\0{screen_id}".encode()
                ).hexdigest(),
                "goal": target["goal"],
                "image": {
                    "path": screen["path"],
                    "sha256": screen["sha256"],
                    "width": screen["width"],
                    "height": screen["height"],
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
    child = {
        "contract_version": PROVIDER_CORPUS_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "source_parent_ref": dict(PARENT_REF),
        "provider_boundary": {
            "opaque_case_ids": True,
            "opaque_screen_groups": True,
            "filter_complete": True,
            "path_scope": "provider_safe_only",
        },
        "cases": cases,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        },
    }
    child["content_sha256"] = content_sha256(child)
    return child


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    parent = json.loads((ROOT / PARENT_PATH).read_text(encoding="utf-8"))
    source_paths = set(CODE_PATHS + CONFIG_PATHS + TEST_PATHS)
    source_paths.add(PARENT_PATH)
    source_paths.update(item["path"] for item in parent["artifacts"].values())
    source_paths.update(item["path"] for item in parent["screenshots"])
    for relative in sorted(source_paths):
        target = repo / relative
        if relative in FUTURE_PATHS:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f"future-placeholder:{relative}\n".encode("utf-8"))
        else:
            _copy(ROOT / relative, target)
    provider_path = repo / PROVIDER_PATH
    provider_path.parent.mkdir(parents=True, exist_ok=True)
    provider_path.write_bytes(canonical_json_bytes(_provider_corpus(parent), pretty=True))
    return repo


@pytest.fixture
def sealed(tmp_path: Path, sealer):
    repo = _make_repo(tmp_path)
    private_path = repo / "out/private.json"
    provider_path = repo / "out/provider.json"
    private, provider = sealer.seal_split_manifests(
        template_path=repo / TEMPLATE_PATH,
        provider_corpus_path=repo / PROVIDER_PATH,
        private_output_path=private_path,
        provider_output_path=provider_path,
        _root=repo,
    )
    return repo, private_path, provider_path, private, provider


def _verify(sealer, repo: Path, private_path: Path, provider_path: Path):
    return sealer.verify_split_manifests(
        template_path=repo / TEMPLATE_PATH,
        provider_corpus_path=repo / PROVIDER_PATH,
        private_manifest_path=private_path,
        provider_manifest_path=provider_path,
        _root=repo,
    )


def _rewrite(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value, pretty=True))


def test_generation_is_canonical_closed_idempotent_and_verifiable(sealed, sealer) -> None:
    repo, private_path, provider_path, private, provider = sealed
    assert set(provider) == {
        "contract_version",
        "benchmark_release_id",
        "provider_corpus_ref",
        "holdout_partition",
        "evaluation_projection",
        "sealed_runtime",
        "workload",
        "arm_order",
        "safety",
    }
    assert set(private) == {
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
    assert private["benchmark_release_id"] == provider["benchmark_release_id"] == BENCHMARK_RELEASE_ID
    assert private["holdout_partition"] == provider["holdout_partition"] == "holdout"
    assert private["provider_corpus_ref"] == provider["provider_corpus_ref"]
    assert private["provider_manifest_ref"]["relative_path"] == "benchmark-v2-provider-manifest.json"
    assert private["provider_manifest_ref"]["file_sha256"] == hashlib.sha256(provider_path.read_bytes()).hexdigest()
    assert len(private["artifact_inventory"]["code_sha256_by_path"]) == 33
    assert len(private["artifact_inventory"]["config_sha256_by_path"]) == 3
    assert len(private["artifact_inventory"]["test_sha256_by_path"]) == 23
    assert provider["sealed_runtime"]["code_refs"] == [
        {"role": role, "relative_path": path, "file_sha256": hashlib.sha256((repo / path).read_bytes()).hexdigest()}
        for role, path in BOOT_REFS
    ]
    assert [(item["role"], item["relative_path"]) for item in provider["sealed_runtime"]["release_code_refs"]] == list(RELEASE_REFS)
    assert validate_provider_manifest(provider) == provider
    assert private_path.read_bytes().endswith(b"\n") and not private_path.read_bytes().endswith(b"\n\n")
    assert provider_path.read_bytes().endswith(b"\n") and not provider_path.read_bytes().endswith(b"\n\n")
    first = (private_path.read_bytes(), provider_path.read_bytes())
    sealer.seal_split_manifests(
        template_path=repo / TEMPLATE_PATH,
        provider_corpus_path=repo / PROVIDER_PATH,
        private_output_path=private_path,
        provider_output_path=provider_path,
        _root=repo,
    )
    assert (private_path.read_bytes(), provider_path.read_bytes()) == first
    assert _verify(sealer, repo, private_path, provider_path) == (private, provider)


def test_both_seals_are_non_authorizing_and_provider_has_no_private_paths(sealed) -> None:
    _, _, provider_path, private, provider = sealed
    assert private["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
        "real_action_allowed": False,
        "publish_allowed": False,
    }
    assert provider["safety"]["artifact_is_authorization"] is False
    assert provider["safety"]["execute_binding_enabled"] is False
    assert provider["workload"] == {
        "contract_version": "provider_sandbox_workload_request_v1",
        "command": "validate_provider_corpus",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    text = provider_path.read_text(encoding="utf-8").casefold()
    for forbidden in (
        PARENT_PATH,
        "gold.v1.json",
        "benchmark_v2_privileged_projector.py",
        "benchmark_scorer_v2.py",
        "score_portfolio_hybrid_v1_1_benchmark_v2_private.py",
        "seal_portfolio_hybrid_v1_1_benchmark_v2.py",
        "authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
        "test_portfolio_hybrid_v1_1_benchmark_v2_seal.py",
        "private-manifest",
        "provider-corpus.candidate.json",
    ):
        assert forbidden.casefold() not in text


@pytest.mark.parametrize("relative", FUTURE_PATHS)
def test_missing_future_artifact_fails_before_either_output(tmp_path: Path, sealer, relative: str) -> None:
    repo = _make_repo(tmp_path)
    (repo / relative).unlink()
    private_path = repo / "out/private.json"
    provider_path = repo / "out/provider.json"
    with pytest.raises(ValueError, match="required file is missing"):
        sealer.seal_split_manifests(
            template_path=repo / TEMPLATE_PATH,
            provider_corpus_path=repo / PROVIDER_PATH,
            private_output_path=private_path,
            provider_output_path=provider_path,
            _root=repo,
        )
    assert not private_path.exists() and not provider_path.exists()


@pytest.mark.parametrize("relative", CODE_PATHS + CONFIG_PATHS + TEST_PATHS)
def test_any_inventory_byte_drift_breaks_verification(sealed, sealer, relative: str) -> None:
    repo, private_path, provider_path, _, _ = sealed
    with (repo / relative).open("ab") as stream:
        stream.write(b"drift")
    with pytest.raises(ValueError, match="mismatch|canonical|invalid"):
        _verify(sealer, repo, private_path, provider_path)


def _v1_paths() -> tuple[str, ...]:
    parent = json.loads((ROOT / PARENT_PATH).read_text(encoding="utf-8"))
    return tuple(item["path"] for item in parent["artifacts"].values()) + tuple(
        item["path"] for item in parent["screenshots"]
    )


@pytest.mark.parametrize("relative", _v1_paths())
def test_any_frozen_v1_artifact_or_image_drift_breaks_verification(sealed, sealer, relative: str) -> None:
    repo, private_path, provider_path, _, _ = sealed
    with (repo / relative).open("ab") as stream:
        stream.write(b"drift")
    with pytest.raises(ValueError, match="mismatch|invalid|not a valid PNG"):
        _verify(sealer, repo, private_path, provider_path)


def test_provider_corpus_raw_or_parent_lineage_drift_fails_closed(sealed, sealer) -> None:
    repo, private_path, provider_path, _, _ = sealed
    corpus_path = repo / PROVIDER_PATH
    corpus_path.write_bytes(corpus_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="canonical"):
        _verify(sealer, repo, private_path, provider_path)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["source_parent_ref"]["artifact_id"] = "different-parent"
    corpus["content_sha256"] = content_sha256(corpus)
    _rewrite(corpus_path, corpus)
    with pytest.raises(ValueError, match="parent"):
        _verify(sealer, repo, private_path, provider_path)


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("arm_order",), ["qwen_only"]),
        (("evaluation_projection", "estimand", "arms", "statistical_arm_count"), 3),
        (("evaluation_projection", "estimand", "execution_units", "hybrid_invocation_unit"), "target"),
        (("evaluation_projection", "estimand", "point_metric", "denominator"), "all_cases"),
        (("evaluation_projection", "estimand", "point_metric", "gain_numerator"), "0"),
        (("evaluation_projection", "gate", "thresholds", "min_coverage"), "0/1"),
        (("evaluation_projection", "provider_policy", "shared_budget", "max_provider_calls_per_case"), 99),
        (("evaluation_projection", "provider_policy", "shared_context_policy", "ocr"), "never"),
    ),
)
def test_provider_policy_order_metric_and_gate_drift_fails(sealed, sealer, path, value) -> None:
    repo, private_path, provider_path, _, provider = sealed
    changed = deepcopy(provider)
    cursor = changed
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    _rewrite(provider_path, changed)
    with pytest.raises(ValueError, match="invalid|mismatch"):
        _verify(sealer, repo, private_path, provider_path)


@pytest.mark.parametrize("collection", ("code_refs", "release_code_refs", "profile_refs"))
@pytest.mark.parametrize("mutation", ("remove", "duplicate", "reorder"))
def test_provider_ref_role_path_and_order_are_closed(sealed, sealer, collection: str, mutation: str) -> None:
    repo, private_path, provider_path, _, provider = sealed
    changed = deepcopy(provider)
    refs = changed["sealed_runtime"][collection]
    if mutation == "remove":
        refs.pop()
    elif mutation == "duplicate":
        refs.append(deepcopy(refs[0]))
    else:
        if len(refs) == 1:
            refs[0]["role"] = "wrong_profile_role"
        else:
            refs.reverse()
    _rewrite(provider_path, changed)
    with pytest.raises(ValueError, match="invalid|mismatch|exact|incomplete|unique"):
        _verify(sealer, repo, private_path, provider_path)


@pytest.mark.parametrize(
    "leak",
    (
        {"private_key": "secret"},
        {"note": "C:/private/host/path"},
        {"note": "tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json"},
        {"scorer_path": "app/learn/hybrid/benchmark_scorer_v2.py"},
    ),
)
def test_nested_provider_private_key_or_path_leak_fails(sealed, sealer, leak) -> None:
    repo, private_path, provider_path, _, provider = sealed
    changed = deepcopy(provider)
    changed["evaluation_projection"]["provider_policy"].update(leak)
    _rewrite(provider_path, changed)
    with pytest.raises(ValueError, match="invalid|exactly|leak|forbidden|mismatch"):
        _verify(sealer, repo, private_path, provider_path)


def test_private_scorer_direct_ref_must_equal_inventory(sealed, sealer) -> None:
    repo, private_path, provider_path, private, _ = sealed
    changed = deepcopy(private)
    changed["private_scorer_refs"][0]["file_sha256"] = "0" * 64
    changed["content_sha256"] = content_sha256(changed)
    _rewrite(private_path, changed)
    with pytest.raises(ValueError, match="private scorer|mismatch"):
        _verify(sealer, repo, private_path, provider_path)


@pytest.mark.parametrize("occupied", ("private", "provider"))
def test_different_existing_output_is_not_overwritten_or_partially_created(tmp_path: Path, sealer, occupied: str) -> None:
    repo = _make_repo(tmp_path)
    private_path = repo / "out/private.json"
    provider_path = repo / "out/provider.json"
    target = private_path if occupied == "private" else provider_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"different")
    with pytest.raises(FileExistsError, match="different bytes"):
        sealer.seal_split_manifests(
            template_path=repo / TEMPLATE_PATH,
            provider_corpus_path=repo / PROVIDER_PATH,
            private_output_path=private_path,
            provider_output_path=provider_path,
            _root=repo,
        )
    assert target.read_bytes() == b"different"
    other = provider_path if occupied == "private" else private_path
    assert not other.exists()


def test_output_traversal_outside_root_is_rejected_before_any_write(tmp_path: Path, sealer) -> None:
    repo = _make_repo(tmp_path)
    escaped = repo / "out" / ".." / ".." / "escaped-provider.json"
    private_path = repo / "out/private.json"
    with pytest.raises(ValueError, match="inside|canonical|escape"):
        sealer.seal_split_manifests(
            template_path=repo / TEMPLATE_PATH,
            provider_corpus_path=repo / PROVIDER_PATH,
            private_output_path=private_path,
            provider_output_path=escaped,
            _root=repo,
        )
    assert not private_path.exists()
    assert not (tmp_path / "escaped-provider.json").exists()


@pytest.mark.parametrize(
    ("private_relative", "provider_relative"),
    (
        ("out/same.json", "out/nested/../same.json"),
        ("out/left/../same.json", "out/right/../same.json"),
    ),
)
def test_lexical_output_aliases_to_same_destination_fail_before_write(
    tmp_path: Path,
    sealer,
    private_relative: str,
    provider_relative: str,
) -> None:
    repo = _make_repo(tmp_path)
    with pytest.raises(ValueError, match="same canonical|different files"):
        sealer.seal_split_manifests(
            template_path=repo / TEMPLATE_PATH,
            provider_corpus_path=repo / PROVIDER_PATH,
            private_output_path=repo / private_relative,
            provider_output_path=repo / provider_relative,
            _root=repo,
        )
    assert not (repo / "out/same.json").exists()


def test_provider_first_exact_partial_state_resumes_by_creating_private(sealed, sealer) -> None:
    repo, private_path, provider_path, private, provider = sealed
    provider_raw = provider_path.read_bytes()
    private_path.unlink()
    assert sealer.seal_split_manifests(
        template_path=repo / TEMPLATE_PATH,
        provider_corpus_path=repo / PROVIDER_PATH,
        private_output_path=private_path,
        provider_output_path=provider_path,
        _root=repo,
    ) == (private, provider)
    assert provider_path.read_bytes() == provider_raw
    assert private_path.read_bytes() == canonical_json_bytes(private, pretty=True)


def test_invalid_provider_input_creates_neither_output(tmp_path: Path, sealer) -> None:
    repo = _make_repo(tmp_path)
    (repo / PROVIDER_PATH).write_bytes(b"{}\n")
    private_path = repo / "out/private.json"
    provider_path = repo / "out/provider.json"
    with pytest.raises(ValueError):
        sealer.seal_split_manifests(
            template_path=repo / TEMPLATE_PATH,
            provider_corpus_path=repo / PROVIDER_PATH,
            private_output_path=private_path,
            provider_output_path=provider_path,
            _root=repo,
        )
    assert not private_path.exists() and not provider_path.exists()


def test_api_and_cli_expose_no_allow_missing_or_root_override(sealer) -> None:
    assert "allow_missing" not in inspect.signature(sealer.seal_split_manifests).parameters
    assert "allow_missing" not in inspect.signature(sealer.verify_split_manifests).parameters
    for option in ("--allow-missing", "--root"):
        result = subprocess.run(
            [
                sys.executable,
                str(SEALER_PATH),
                "--template",
                TEMPLATE_PATH,
                "--provider-corpus",
                PROVIDER_PATH,
                "--output-private",
                "private.json",
                "--output-provider",
                "provider.json",
                option,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert result.returncode != 0
        assert "unrecognized arguments" in result.stderr


def test_provider_manifest_sha_is_not_part_of_durable_claim_namespace(sealed) -> None:
    _, _, provider_path, _, _ = sealed
    before = claim_id(IDENTITY)
    changed_sha = hashlib.sha256(provider_path.read_bytes() + b"changed").hexdigest()
    assert changed_sha != hashlib.sha256(provider_path.read_bytes()).hexdigest()
    assert claim_id(IDENTITY) == before


def test_cli_receipts_hash_root_resolved_paths_from_different_cwd(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    other_cwd = tmp_path / "different-cwd"
    other_cwd.mkdir()
    command = [
        sys.executable,
        str(repo / "scripts/seal_portfolio_hybrid_v1_1_benchmark_v2.py"),
        "--template",
        TEMPLATE_PATH,
        "--provider-corpus",
        PROVIDER_PATH,
        "--output-private",
        "out/private.json",
        "--output-provider",
        "out/provider.json",
    ]
    seal_result = subprocess.run(
        command,
        cwd=other_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert seal_result.returncode == 0, seal_result.stderr
    seal_receipt = json.loads(seal_result.stdout)
    assert seal_receipt["status"] == "SEALED"
    assert seal_receipt["provider_corpus_file_sha256"] == hashlib.sha256(
        (repo / PROVIDER_PATH).read_bytes()
    ).hexdigest()
    assert seal_receipt["provider_manifest_file_sha256"] == hashlib.sha256(
        (repo / "out/provider.json").read_bytes()
    ).hexdigest()
    assert seal_receipt["private_manifest_file_sha256"] == hashlib.sha256(
        (repo / "out/private.json").read_bytes()
    ).hexdigest()

    verify_result = subprocess.run(
        [*command, "--verify-only"],
        cwd=other_cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert verify_result.returncode == 0, verify_result.stderr
    verify_receipt = json.loads(verify_result.stdout)
    assert verify_receipt == {**seal_receipt, "status": "VERIFIED"}
