from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_NAME = "scripts.assemble_portfolio_hybrid_v1_1_benchmark_v2_report"


def _module():
    return importlib.import_module(MODULE_NAME)


def _synthetic_snapshot(module, tmp_path: Path):
    production_paths = ("production/a.py", "production/b.py")
    test_paths = ("tests/test_a.py",)
    for relative_path, payload in (
        (production_paths[0], b"alpha\n"),
        (production_paths[1], b"beta\n"),
        (test_paths[0], b"test\n"),
    ):
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    snapshot = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    return production_paths, test_paths, snapshot


def _synthetic_evidence(module, snapshot):
    result_receipts = {}
    result_refs = {}
    review_receipts = {}
    review_refs = {}
    for suite_id in module.DEPENDENCY_ORDER:
        result = module.build_dependency_result_receipt(
            suite_id=suite_id,
            pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id],
            pre_source_snapshot=snapshot,
            post_source_snapshot=snapshot,
            exit_code=0,
            collected_count=3,
            failed_count=0,
        )
        result_ref = module.artifact_ref(result)
        review = module.build_dependency_review_receipt(
            suite_id=suite_id,
            result_receipt=result,
            result_receipt_ref=result_ref,
            review_name=module.REVIEW_NAME_BY_SUITE_ID[suite_id],
            review_file_sha256="a" * 64,
            reviewer_identity_sha256="b" * 64,
            reviewer_independent=True,
            unresolved_findings={"critical": 0, "important": 0},
        )
        result_receipts[suite_id] = result
        result_refs[suite_id] = result_ref
        review_receipts[suite_id] = review
        review_refs[suite_id] = module.artifact_ref(review)
    return result_receipts, result_refs, review_receipts, review_refs


def _configured_plugin(module, tmp_path: Path, *, suite_id: str, addopts=()):
    output = tmp_path / "receipt.json"

    class Invocation:
        args = (
            "-p",
            module.PYTEST_PLUGIN_NAME,
            module.PYTEST_SUITE_OPTION,
            suite_id,
            module.PYTEST_RECEIPT_OPTION,
            str(output),
            *module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id][1:],
        )

    class PluginManager:
        @staticmethod
        def list_plugin_distinfo():
            return []

        @staticmethod
        def get_plugins():
            return set()

    class Config:
        invocation_params = Invocation()
        pluginmanager = PluginManager()

        @staticmethod
        def getoption(name):
            return {
                module.PYTEST_SUITE_OPTION: suite_id,
                module.PYTEST_RECEIPT_OPTION: str(output),
            }.get(name)

        @staticmethod
        def getini(name):
            return list(addopts) if name == "addopts" else []

    config = Config()
    module.pytest_configure(config)
    return config, output


def _probe_bound_public_report_inputs(module):
    digest = lambda value: f"{value % 16:x}" * 64
    release = "portfolio-hybrid-v1-1-benchmark-v2"
    safety = deepcopy(module.SAFETY)
    manifest_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_manifest_v2_1",
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": "1" * 64,
    }
    source_parent_ref = {
        "contract_version": "portfolio_hybrid_v1_1_corpus_manifest_v1",
        "artifact_id": "provider-corpus-parent/" + "2" * 64,
        "file_sha256": "3" * 64,
        "content_sha256": "4" * 64,
    }
    corpus_ref = {
        "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": "5" * 64,
        "content_sha256": "6" * 64,
        "source_parent_ref": deepcopy(source_parent_ref),
    }
    accepted_ref = {
        "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
        "file_sha256": "7" * 64,
        "content_sha256": "8" * 64,
    }
    profiles = {
        "omni-profile": "a" * 64,
        "qwen-profile": "b" * 64,
        "vista-profile": "c" * 64,
    }
    matrix = [
        [provider, kind]
        for provider in ("omni", "qwen", "vista")
        for kind in ("cancel", "timeout")
    ]
    horizon_refs = {
        kind: {
            "id": "verified-probe-horizon/" + digest(value),
            "content_sha256": digest(value),
        }
        for kind, value in (("cancel", 13), ("timeout", 14))
    }
    cells = []
    for index, (provider, kind) in enumerate(matrix, 1):
        cells.append(
            {
                "provider_id": provider,
                "probe_kind": kind,
                "attempt_ref": {
                    "id": f"runner-attempt/{index:032x}",
                    "content_sha256": digest(index),
                },
                "run_id": f"run-{index}",
                "operation_id": f"operation-{index}",
                "model_request_id": f"request-{index}",
                "runner_probe_result_ref": {
                    "contract_version": "benchmark_v2_runner_probe_result_v2",
                    "file_sha256": digest(index + 1),
                    "content_sha256": digest(index + 2),
                },
                "lifecycle_probe_receipt_ref": {
                    "contract_version": "benchmark_v2_lifecycle_probe_receipt_v2",
                    "file_sha256": digest(index + 3),
                    "content_sha256": digest(index + 4),
                },
                "cleanup_receipt_ref": {"content_sha256": digest(index + 5)},
                "stable_zero_ref": {"content_sha256": digest(index + 6)},
                "ledger_pre_result_ref": {
                    "id": "verified-probe-pre-result/" + digest(index + 7),
                    "content_sha256": digest(index + 8),
                },
                "ledger_horizon_ref": deepcopy(horizon_refs[kind]),
                "deadline_expiration_ref": (
                    None
                    if kind == "cancel"
                    else {"content_sha256": digest(index + 11)}
                ),
                "body_completion_state": "not_complete",
                "termination_outcome": "same_incarnations_exited",
                "stable_zero_observations": 3,
                "status": "PASS",
            }
        )
    semantic = {
        "contract_version": "benchmark_v2_regression_probe_authority_bundle_v1",
        "benchmark_release_id": release,
        "partition": "regression",
        "provider_manifest_ref": deepcopy(manifest_ref),
        "provider_corpus_ref": deepcopy(corpus_ref),
        "accepted_run_ref": deepcopy(accepted_ref),
        "selection_policy": "first_complete_verified_attempt_per_cell",
        "required_matrix": deepcopy(matrix),
        "probe_ledger_horizon_refs": [
            {
                "probe_kind": kind,
                "ledger_horizon_ref": deepcopy(horizon_refs[kind]),
            }
            for kind in ("cancel", "timeout")
        ],
        "probe_cells": cells,
        "status": "PASS",
        "safety": deepcopy(safety),
    }
    semantic_sha256 = hashlib.sha256(
        b"benchmark_v2_regression_probe_authority_bundle_v1\0"
        + module.compact_json_bytes(semantic)
    ).hexdigest()
    bundle = {
        "artifact_id": "probe-authority/" + semantic_sha256,
        **semantic,
    }
    bundle["content_sha256"] = module.content_sha256(bundle)
    probe_validation = SimpleNamespace(
        bundle=bundle,
        profile_sha256_by_id=profiles,
    )
    probe_ref = {
        "id": bundle["artifact_id"],
        "content_sha256": bundle["content_sha256"],
    }
    shared_binding = {
        "benchmark_release_id": release,
        "private_manifest_ref": {
            "contract_version": "portfolio_hybrid_v1_1_private_manifest_v2",
            "file_sha256": "f" * 64,
            "content_sha256": "0" * 64,
        },
        "corpus_parent_ref": deepcopy(source_parent_ref),
        "provider_manifest_ref": deepcopy(manifest_ref),
        "provider_corpus_ref": deepcopy(corpus_ref),
        "attempt_ref": {"id": "attempt/" + "1" * 64, "content_sha256": "2" * 64},
        "attempt_ledger_ref": {
            "id": "ledger/" + "3" * 64,
            "content_sha256": "4" * 64,
        },
        "automatic_prediction_ref": {
            "id": "prediction/" + "5" * 64,
            "content_sha256": "6" * 64,
        },
        "selected_lifecycle_ref": {
            "id": "lifecycle/" + "7" * 64,
            "content_sha256": "8" * 64,
        },
        "estimand_ref": {
            "contract_version": "benchmark_v2_estimand_v1",
            "file_sha256": "9" * 64,
        },
        "gate_ref": {
            "contract_version": "benchmark_v2_gate_v1",
            "file_sha256": "a" * 64,
        },
        "safety": deepcopy(safety),
    }
    regression_binding = {
        "contract_version": "private_scorer_input_binding_v1",
        "partition": "regression",
        "accepted_run_ref": deepcopy(accepted_ref),
        **deepcopy(shared_binding),
    }
    authorization_ref = {
        "authorization_id": "holdout-authorization/" + "b" * 64,
        "envelope_sha256": "c" * 64,
    }
    claim_ref = {"id": "holdout-claim/" + "b" * 64, "envelope_sha256": "e" * 64}
    holdout_run = {
        "contract_version": "benchmark_v2_accepted_holdout_score_input_v1",
        "benchmark_release_id": release,
        "partition": "holdout",
        "corpus_parent_ref": deepcopy(source_parent_ref),
        "provider_manifest_ref": deepcopy(manifest_ref),
        "provider_corpus_ref": deepcopy(corpus_ref),
        "selection_policy": "unique_claim_bound_holdout_attempt",
        "attempt_ref": {"id": "holdout-attempt/" + "1" * 64, "content_sha256": "2" * 64},
        "attempt_ledger_ref": {"id": "holdout-ledger/" + "3" * 64, "content_sha256": "4" * 64},
        "automatic_prediction_ref": {"id": "holdout-prediction/" + "5" * 64, "content_sha256": "6" * 64},
        "selected_lifecycle_ref": {"id": "holdout-lifecycle/" + "7" * 64, "content_sha256": "8" * 64},
        "verified_parent_projections": {
            "runner_ledger_prefix_projection_envelope": {"ref": {"id": "r/1", "content_sha256": "1" * 64}, "canonical_bytes_b64": "e30="},
            "attempt_journal_projection_envelope": {"ref": {"id": "r/2", "content_sha256": "2" * 64}, "canonical_bytes_b64": "e30="},
            "actual_body_projection_envelope": {"ref": {"id": "r/3", "content_sha256": "3" * 64}, "canonical_bytes_b64": "e30="},
            "actual_result_projection_envelope": {"ref": {"id": "r/4", "content_sha256": "4" * 64}, "canonical_bytes_b64": "e30="},
        },
        "prediction_run_envelope": {"ref": {"id": "r/5", "content_sha256": "5" * 64}, "canonical_bytes_b64": "e30="},
        "lifecycle_bundle_envelope": {"ref": {"id": "r/6", "content_sha256": "6" * 64}, "canonical_bytes_b64": "e30="},
        "regression_score_precondition_envelope": {"ref": {"id": "r/7", "content_sha256": "7" * 64}, "canonical_bytes_b64": "e30="},
        "holdout_authority_evidence": {
            name: {"ref": {"id": f"r/{index}", "content_sha256": f"{index:x}" * 64}, "canonical_bytes_b64": "e30="}
            for index, name in enumerate(
                (
                    "authorization_public_projection_envelope",
                    "claim_public_projection_envelope",
                    "file_anchor_public_projection_envelope",
                    "registry_anchor_public_projection_envelope",
                ),
                8,
            )
        },
        "holdout_authorization_ref": deepcopy(authorization_ref),
        "holdout_claim_ref": deepcopy(claim_ref),
        "safety": deepcopy(safety),
    }
    holdout_run["content_sha256"] = module.content_sha256(holdout_run)
    holdout_run_ref = {
        "contract_version": holdout_run["contract_version"],
        "file_sha256": "f" * 64,
        "content_sha256": holdout_run["content_sha256"],
    }
    regression_score_ref = {
        "contract_version": "private_scorer_public_ref_v3",
        "file_sha256": "1" * 64,
        "content_sha256": "2" * 64,
    }
    holdout_binding = {
        "contract_version": "private_scorer_holdout_input_binding_v1",
        "partition": "holdout",
        "accepted_run_ref": deepcopy(holdout_run_ref),
        "regression_score_precondition_ref": deepcopy(regression_score_ref),
        "holdout_authorization_ref": deepcopy(authorization_ref),
        "holdout_claim_ref": deepcopy(claim_ref),
        **deepcopy(shared_binding),
    }
    holdout_score_ref = {
        "contract_version": "private_scorer_public_ref_v3",
        "file_sha256": "3" * 64,
        "content_sha256": "4" * 64,
    }
    leakage_review = {
        "contract_version": "benchmark_v2_leakage_review_v1",
        "benchmark_release_id": release,
        "provider_manifest_ref": deepcopy(manifest_ref),
        "provider_corpus_ref": deepcopy(corpus_ref),
        "accepted_run_ref": deepcopy(accepted_ref),
        "finding_codes": [],
        "status": "PASS",
        "safety": deepcopy(safety),
        "content_sha256": "5" * 64,
    }
    leakage_review_ref = {
        "contract_version": leakage_review["contract_version"],
        "file_sha256": "6" * 64,
        "content_sha256": leakage_review["content_sha256"],
    }
    authorization_payload = {
        "contract_version": "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v2",
        "claim_identity": {"release": release},
        "claim_id": "b" * 64,
        "ledger_identity": {
            "absolute_ledger_root": "C:/private/ledger",
            "holdout_events_path": "C:/private/ledger/holdout/events.jsonl",
        },
        "fixed_authorization_path": "C:/private/authorization.json",
        "provider_manifest_sha256": manifest_ref["file_sha256"],
        "provider_manifest_contract_version": manifest_ref["contract_version"],
        "code_sha256_by_path": {"code.py": "1" * 64},
        "config_sha256_by_path": {"config.json": "2" * 64},
        "profile_sha256_by_id": deepcopy(profiles),
        "regression_probe_authority_ref": deepcopy(probe_ref),
        "arm_order": ["omni", "qwen", "hybrid", "hybrid_vista"],
        "exact_holdout_command": ["python", "runner.py"],
        "exact_run_order": ["sealed-regression", "sealed-holdout"],
        "absolute_owner_journal_root": "C:/private/owner",
    }
    return {
        "probe_validation": probe_validation,
        "regression_score_status": "PASS",
        "holdout_score_status": "PASS",
        "regression_score_binding": regression_binding,
        "holdout_score_binding": holdout_binding,
        "regression_score_ref": regression_score_ref,
        "holdout_score_ref": holdout_score_ref,
        "holdout_run": holdout_run,
        "holdout_run_ref": holdout_run_ref,
        "leakage_review": leakage_review,
        "leakage_review_ref": leakage_review_ref,
        "authorization_payload": authorization_payload,
        "authorization_envelope_contract": "portfolio_hybrid_benchmark_v2_holdout_authorization_envelope_v2",
        "authorization_ref": authorization_ref,
    }


def test_public_report_propagates_exact_probe_authority_ref_without_private_parents() -> None:
    module = _module()
    inputs = _probe_bound_public_report_inputs(module)

    report = module._assemble_probe_bound_public_report(**inputs)

    bundle = inputs["probe_validation"].bundle
    assert report["regression_probe_authority_ref"] == {
        "id": bundle["artifact_id"],
        "content_sha256": bundle["content_sha256"],
    }
    assert report["regression_probe_authority_ref"] == inputs["authorization_payload"][
        "regression_probe_authority_ref"
    ]
    assert set(report) == module._FINAL_REPORT_FIELDS
    rendered = module.compact_json_bytes(report).decode("utf-8")
    for forbidden in (
        "probe_cells",
        "profile_sha256_by_id",
        "fixed_authorization_path",
        "absolute_ledger_root",
        "attempt_dir",
        "observer_identity",
        "process_identities",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    "mutation",
    [
        "probe_fail",
        "score_fail",
        "missing_cell",
        "cell_fail",
        "cell_raw_parent",
        "path_bearing_bundle",
        "release_drift",
        "provider_drift",
        "corpus_drift",
        "accepted_drift",
        "authorization_v1",
        "authorization_envelope_v1",
        "authorization_probe_ref_drift",
        "authorization_profile_drift",
    ],
)
def test_public_report_rejects_probe_authority_or_authorization_drift(
    mutation: str,
) -> None:
    module = _module()
    inputs = _probe_bound_public_report_inputs(module)
    bundle = inputs["probe_validation"].bundle
    if mutation == "probe_fail":
        bundle["status"] = "FAIL"
    elif mutation == "score_fail":
        inputs["holdout_score_status"] = "FAIL"
    elif mutation == "missing_cell":
        bundle["probe_cells"].pop()
    elif mutation == "cell_fail":
        bundle["probe_cells"][0]["status"] = "FAIL"
    elif mutation == "cell_raw_parent":
        bundle["probe_cells"][0]["raw_parent"] = {"pid": 42}
    elif mutation == "path_bearing_bundle":
        bundle["probe_cells"][0]["stable_zero_ref"]["path"] = "C:/private/raw.json"
    elif mutation == "release_drift":
        bundle["benchmark_release_id"] = "other-release"
    elif mutation == "provider_drift":
        inputs["regression_score_binding"]["provider_manifest_ref"]["file_sha256"] = "0" * 64
    elif mutation == "corpus_drift":
        inputs["holdout_score_binding"]["corpus_parent_ref"]["file_sha256"] = "0" * 64
    elif mutation == "accepted_drift":
        inputs["leakage_review"]["accepted_run_ref"]["content_sha256"] = "0" * 64
    elif mutation == "authorization_v1":
        inputs["authorization_payload"]["contract_version"] = (
            "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v1"
        )
    elif mutation == "authorization_envelope_v1":
        inputs["authorization_envelope_contract"] = (
            "portfolio_hybrid_benchmark_v2_holdout_authorization_envelope_v1"
        )
    elif mutation == "authorization_probe_ref_drift":
        inputs["authorization_payload"]["regression_probe_authority_ref"][
            "content_sha256"
        ] = "0" * 64
    else:
        inputs["authorization_payload"]["profile_sha256_by_id"]["omni-profile"] = (
            "0" * 64
        )

    with pytest.raises(ValueError):
        module._assemble_probe_bound_public_report(**inputs)


def test_probe_authority_validator_is_called_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    calls = []
    sentinel = object()

    class ProbeModule:
        @staticmethod
        def validate_benchmark_v2_regression_probe_authority_candidate(**kwargs):
            calls.append(kwargs)
            return sentinel

    monkeypatch.setattr(
        module,
        "import_module",
        lambda name: ProbeModule
        if name == "app.learn.hybrid.benchmark_v2_probe_authority"
        else importlib.import_module(name),
    )

    result = module._validate_probe_authority_candidate_once(
        provider_manifest_path=Path("provider.json"),
        regression_run_ref_path=Path("accepted.json"),
        ledger_root=Path("ledger"),
        probe_authority_path=Path("probe-authority.json"),
    )

    assert result is sentinel
    assert len(calls) == 1


def test_public_report_cli_requires_canonical_probe_authority_position_and_guards_duplicates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    flags = module.FINAL_REPORT_FLAG_ORDER
    regression_index = flags.index("--regression-score-ref")
    assert flags[regression_index + 1] == "--probe-authority"
    tokens = [
        item
        for flag in flags
        for item in (flag, module.FINAL_REPORT_PATH_TOKENS[flag])
    ]
    args = module._parse_cli_tokens(tokens)
    assert args.probe_authority == module.FINAL_REPORT_PATH_TOKENS["--probe-authority"]

    missing = tokens[: 2 * (regression_index + 1)] + tokens[
        2 * (regression_index + 2) :
    ]
    with pytest.raises(SystemExit):
        module._parse_cli_tokens(missing)
    capsys.readouterr()

    secret = "C:/private/do-not-leak.json"
    for duplicate in (
        ["--probe-authority", secret],
        [f"--probe-authority={secret}"],
        ["--probe-authority", secret, f"--probe-authority={secret}"],
    ):
        with pytest.raises(SystemExit):
            module._parse_cli_tokens(tokens + duplicate)
        captured = capsys.readouterr()
        assert secret not in captured.err
        assert secret not in captured.out


def test_public_report_cli_requires_dependency_manifest_before_ledger_root() -> None:
    module = _module()
    flags = module.FINAL_REPORT_FLAG_ORDER

    leakage_index = flags.index("--leakage-review")
    assert flags[leakage_index + 1] == "--dependency-manifest"
    assert flags[leakage_index + 2] == "--ledger-root"
    assert module.FINAL_REPORT_PATH_TOKENS["--dependency-manifest"] == (
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/"
        "release-dependency-manifest.json"
    )


@pytest.mark.parametrize("ordering", ["reversed", "adjacent_swap"])
def test_public_report_cli_rejects_reordered_fixed_flags_without_value_leakage(
    ordering: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    flags = list(module.FINAL_REPORT_FLAG_ORDER)
    if ordering == "reversed":
        flags.reverse()
    else:
        score_index = flags.index("--regression-score-ref")
        flags[score_index], flags[score_index + 1] = (
            flags[score_index + 1],
            flags[score_index],
        )
    tokens = [
        item
        for flag in flags
        for item in (flag, module.FINAL_REPORT_PATH_TOKENS[flag])
    ]

    with pytest.raises(SystemExit):
        module._parse_cli_tokens(tokens)

    captured = capsys.readouterr()
    for value in module.FINAL_REPORT_PATH_TOKENS.values():
        assert value not in captured.err
        assert value not in captured.out


@pytest.mark.parametrize("style", ["separated", "equals", "mixed"])
def test_public_report_cli_accepts_canonical_sequence_in_all_value_forms(
    style: str,
) -> None:
    module = _module()
    tokens = []
    for index, flag in enumerate(module.FINAL_REPORT_FLAG_ORDER):
        value = module.FINAL_REPORT_PATH_TOKENS[flag]
        use_equals = style == "equals" or (style == "mixed" and index % 2 == 1)
        tokens.extend((f"{flag}={value}",) if use_equals else (flag, value))

    args = module._parse_cli_tokens(tokens)

    for flag in module.FINAL_REPORT_FLAG_ORDER:
        destination = flag.removeprefix("--").replace("-", "_")
        assert getattr(args, destination) == module.FINAL_REPORT_PATH_TOKENS[flag]


def _duplicate_flag_tokens(
    *, prefix: list[str], pairs: list[tuple[str, str]], target: str, style: str
) -> list[str]:
    result = list(prefix)
    for flag, value in pairs:
        if flag != target:
            result.extend((flag, value))
        elif style == "separated":
            result.extend((flag, value, flag, value))
        elif style == "equals":
            result.extend((f"{flag}={value}", f"{flag}={value}"))
        else:
            result.extend((flag, value, f"{flag}={value}"))
    return result


@pytest.mark.parametrize("flag", _module().FINAL_REPORT_FLAG_ORDER)
@pytest.mark.parametrize("style", ["separated", "equals", "mixed"])
def test_public_report_cli_redacts_duplicate_values_for_every_fixed_flag(
    flag: str,
    style: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    pairs = [
        (candidate, module.FINAL_REPORT_PATH_TOKENS[candidate])
        for candidate in module.FINAL_REPORT_FLAG_ORDER
    ]
    value = module.FINAL_REPORT_PATH_TOKENS[flag]
    tokens = _duplicate_flag_tokens(
        prefix=[], pairs=pairs, target=flag, style=style
    )

    with pytest.raises(SystemExit):
        module._parse_cli_tokens(tokens)

    captured = capsys.readouterr()
    assert value not in captured.err
    assert value not in captured.out


@pytest.mark.parametrize(
    ("prefix", "pairs", "target"),
    [
        (
            ["--build-dependency-manifest"],
            [("--benchmark-release-id", "release-secret"), ("--output", "output-secret")],
            "--benchmark-release-id",
        ),
        (
            ["--build-dependency-manifest"],
            [("--benchmark-release-id", "release-secret"), ("--output", "output-secret")],
            "--output",
        ),
        (
            ["--validate-final-report-dependency"],
            [("--dependency-manifest", "manifest-secret")],
            "--dependency-manifest",
        ),
    ],
)
@pytest.mark.parametrize("style", ["separated", "equals", "mixed"])
def test_dependency_manifest_modes_redact_duplicate_fixed_flag_values(
    prefix: list[str],
    pairs: list[tuple[str, str]],
    target: str,
    style: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _module()
    value = dict(pairs)[target]
    tokens = _duplicate_flag_tokens(
        prefix=prefix, pairs=pairs, target=target, style=style
    )

    with pytest.raises(SystemExit):
        module._parse_cli_tokens(tokens)

    captured = capsys.readouterr()
    assert value not in captured.err
    assert value not in captured.out


@pytest.mark.parametrize(
    "mode", ["--build-dependency-manifest", "--validate-final-report-dependency"]
)
def test_dependency_manifest_mode_flag_cannot_be_repeated(
    mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()

    with pytest.raises(SystemExit):
        module._parse_cli_tokens([mode, mode])

    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "secret" not in captured.out


def test_public_report_production_api_accepts_paths_only() -> None:
    module = _module()

    assert set(
        inspect.signature(module.assemble_benchmark_v2_public_report).parameters
    ) == {
        "provider_manifest_path",
        "regression_run_ref_path",
        "holdout_run_ref_path",
        "regression_score_ref_path",
        "probe_authority_path",
        "holdout_score_ref_path",
        "leakage_review_path",
        "dependency_manifest_path",
        "ledger_root",
        "output_path",
    }


def test_public_report_validates_dependency_manifest_before_probe_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    calls: list[str] = []
    canonical = {
        flag.removeprefix("--").replace("-", "_"): Path(value)
        for flag, value in module.FINAL_REPORT_PATH_TOKENS.items()
    }

    monkeypatch.setattr(
        module,
        "_validate_production_final_report_paths",
        lambda **_kwargs: canonical,
    )
    monkeypatch.setattr(
        module,
        "_load_pretty_artifact",
        lambda path, name: calls.append(f"load:{name}") or {"build_mode": "release"},
    )

    def reject_dependency(_manifest: object) -> None:
        calls.append("validate:dependency")
        raise ValueError("dependency manifest rejected")

    monkeypatch.setattr(
        module,
        "validate_dependency_manifest_for_final_report",
        reject_dependency,
    )
    monkeypatch.setattr(
        module,
        "_validate_probe_authority_candidate_once",
        lambda **_kwargs: calls.append("validate:probe"),
    )
    monkeypatch.setattr(
        module,
        "write_create_new_or_byte_identical",
        lambda *_args, **_kwargs: calls.append("write:report"),
    )

    with pytest.raises(ValueError, match="dependency manifest rejected"):
        module.assemble_benchmark_v2_public_report(
            provider_manifest_path=Path("provider.json"),
            regression_run_ref_path=Path("regression-run.json"),
            holdout_run_ref_path=Path("holdout-run.json"),
            regression_score_ref_path=Path("regression-score.json"),
            probe_authority_path=Path("probe-authority.json"),
            holdout_score_ref_path=Path("holdout-score.json"),
            leakage_review_path=Path("leakage-review.json"),
            dependency_manifest_path=Path("dependency-manifest.json"),
            ledger_root=Path("ledger"),
            output_path=Path("report.json"),
        )

    assert calls == ["load:dependency manifest", "validate:dependency"]


def test_dependency_manifest_release_mismatch_blocks_public_report_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    writes: list[tuple[object, object]] = []
    monkeypatch.setattr(
        module,
        "write_create_new_or_byte_identical",
        lambda path, payload: writes.append((path, payload)),
    )

    with pytest.raises(
        ValueError, match="dependency manifest release differs from final report"
    ):
        module._write_dependency_bound_public_report(
            dependency_manifest={"benchmark_release_id": "release-a"},
            report={"benchmark_release_id": "release-b"},
            output_path=Path("report.json"),
        )

    assert writes == []


def test_matching_dependency_manifest_release_writes_public_report_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    writes: list[tuple[object, object]] = []
    monkeypatch.setattr(
        module,
        "write_create_new_or_byte_identical",
        lambda path, payload: writes.append((path, payload)),
    )
    report = {"benchmark_release_id": "release-a"}

    module._write_dependency_bound_public_report(
        dependency_manifest={"benchmark_release_id": "release-a"},
        report=report,
        output_path=Path("report.json"),
    )

    assert writes == [(Path("report.json"), module.pretty_json_bytes(report))]


@pytest.mark.parametrize("mutation", ["missing", "extra", "malformed"])
def test_source_snapshot_validation_rejects_missing_extra_or_malformed_maps(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    changed = deepcopy(snapshot)
    if mutation == "missing":
        changed["production_source_sha256_by_path"].pop(production_paths[0])
    elif mutation == "extra":
        changed["test_source_sha256_by_path"]["tests/extra.py"] = "0" * 64
    else:
        changed["production_source_sha256_by_path"][production_paths[0]] = "BAD"

    with pytest.raises(ValueError, match="source snapshot"):
        module.validate_source_snapshot(
            changed,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_dependency_result_receipt_fails_on_pre_post_source_drift(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, pre_snapshot = _synthetic_snapshot(module, tmp_path)
    (tmp_path / production_paths[0]).write_bytes(b"changed\n")
    post_snapshot = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    receipt = module.build_dependency_result_receipt(
        suite_id="task05_worker_binding_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
            "task05_worker_binding_v1"
        ],
        pre_source_snapshot=pre_snapshot,
        post_source_snapshot=post_snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )

    assert receipt["source_snapshot_sha256"] == module.source_snapshot_sha256(
        pre_snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    assert receipt["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "extra", "malformed"])
def test_dependency_result_receipt_rejects_source_snapshot_digest_field_drift(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    receipt = module.build_dependency_result_receipt(
        suite_id="task05_worker_binding_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
            "task05_worker_binding_v1"
        ],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )
    changed = deepcopy(receipt)
    if mutation == "missing":
        changed.pop("source_snapshot_sha256")
    elif mutation == "extra":
        changed["post_source_snapshot_sha256"] = receipt["source_snapshot_sha256"]
    else:
        changed["source_snapshot_sha256"] = "BAD"

    with pytest.raises(ValueError, match="dependency result receipt"):
        module.validate_dependency_result_receipt(changed)


def test_manifest_rejects_result_receipt_snapshot_that_differs_from_current_maps(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    (tmp_path / production_paths[0]).write_bytes(b"current drift\n")
    current = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    with pytest.raises(ValueError, match="current source snapshot"):
        module._build_synthetic_dependency_manifest_for_test(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            source_snapshot=current,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_manifest_rejects_mixed_dependency_receipt_snapshots(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    result_receipts, result_refs, review_receipts, review_refs = (
        _synthetic_evidence(module, snapshot)
    )
    mixed_suite = module.DEPENDENCY_ORDER[-1]
    mixed_result = deepcopy(result_receipts[mixed_suite])
    mixed_result["source_snapshot_sha256"] = "c" * 64
    mixed_result["content_sha256"] = module.content_sha256(mixed_result)
    result_receipts[mixed_suite] = mixed_result
    result_refs[mixed_suite] = module.artifact_ref(mixed_result)
    mixed_review = deepcopy(review_receipts[mixed_suite])
    mixed_review["result_receipt_ref"] = result_refs[mixed_suite]
    mixed_review["content_sha256"] = module.content_sha256(mixed_review)
    review_receipts[mixed_suite] = mixed_review
    review_refs[mixed_suite] = module.artifact_ref(mixed_review)

    with pytest.raises(ValueError, match="current source snapshot"):
        module._build_synthetic_dependency_manifest_for_test(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=result_receipts,
            result_receipt_refs_by_suite=result_refs,
            review_receipts_by_suite=review_receipts,
            review_receipt_refs_by_suite=review_refs,
            source_snapshot=snapshot,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_final_seal_validation_rejects_current_source_mismatch(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    task12 = module.build_dependency_result_receipt(
        suite_id="task12_release_gate_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID["task12_release_gate_v1"],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )
    (tmp_path / test_paths[0]).write_bytes(b"post seal drift\n")
    current = module.capture_source_snapshot(
        root=tmp_path,
        production_paths=production_paths,
        test_paths=test_paths,
    )

    with pytest.raises(ValueError, match="final seal source snapshot"):
        module._validate_synthetic_final_seal_source_binding_for_test(
            sealed_production_sha256_by_path=manifest[
                "production_sha256_by_path"
            ],
            sealed_test_sha256_by_path=manifest["test_sha256_by_path"],
            dependency_manifest=manifest,
            dependency_result_receipts_by_suite=evidence[0],
            task12_result_receipt=task12,
            current_source_snapshot=current,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_stable_synthetic_dependency_manifest_is_pass_and_byte_stable(
    tmp_path: Path,
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)

    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    output = tmp_path / "manifest.json"
    module.write_create_new_or_byte_identical(output, module.pretty_json_bytes(manifest))
    module.write_create_new_or_byte_identical(output, module.pretty_json_bytes(manifest))

    assert manifest["dependency_order"] == list(module.DEPENDENCY_ORDER)
    assert manifest["build_mode"] == "synthetic_test"
    assert output.read_bytes() == module.pretty_json_bytes(manifest)
    with pytest.raises(ValueError, match="release build mode"):
        module.validate_dependency_manifest_for_final_report(manifest)


def test_release_builder_rejects_an_injected_repository_root(tmp_path: Path) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)

    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            root=tmp_path,
            build_mode="release",
        )


def test_release_builder_rejects_caller_fabricated_receipt_objects() -> None:
    module = _module()
    snapshot = module.capture_source_snapshot()
    evidence = _synthetic_evidence(module, snapshot)

    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="synthetic-release",
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            root=module.ROOT,
            build_mode="release",
        )


def test_semantic_pytest_argv_strips_only_plugin_transport_options() -> None:
    module = _module()
    suite_id = "task05_worker_binding_v1"
    args = [
        "-p",
        module.PYTEST_PLUGIN_NAME,
        "--benchmark-v2-suite-id",
        suite_id,
        "--benchmark-v2-receipt-output=tmp/receipt.json",
        *module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[suite_id][1:],
    ]

    assert module.semantic_pytest_argv(args) == module.FROZEN_PYTEST_ARGV_BY_SUITE_ID[
        suite_id
    ]


def test_plugin_transport_options_cannot_activate_an_implicitly_loaded_plugin() -> None:
    module = _module()

    class Invocation:
        args = (
            module.PYTEST_SUITE_OPTION,
            "task05_worker_binding_v1",
            module.PYTEST_RECEIPT_OPTION,
            "receipt.json",
        )

    class Config:
        invocation_params = Invocation()

        @staticmethod
        def getoption(name):
            return {
                module.PYTEST_SUITE_OPTION: "task05_worker_binding_v1",
                module.PYTEST_RECEIPT_OPTION: "receipt.json",
            }[name]

    with pytest.raises(ValueError, match="explicitly loaded"):
        module.pytest_configure(Config())


def test_explicit_plugin_load_requires_both_transport_options() -> None:
    module = _module()

    class Invocation:
        args = ("-p", module.PYTEST_PLUGIN_NAME)

    class Config:
        invocation_params = Invocation()

        @staticmethod
        def getoption(_name):
            return None

    with pytest.raises(ValueError, match="both transport options"):
        module.pytest_configure(Config())


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("PYTEST_ADDOPTS", "--ignore=tests"),
        ("PYTEST_PLUGINS", "foreign_plugin"),
    ],
)
def test_plugin_rejects_environment_semantic_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    module = _module()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=variable):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
        )


def test_plugin_requires_external_plugin_autoload_to_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.delenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)

    with pytest.raises(ValueError, match="autoload"):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
        )


def test_plugin_rejects_configured_addopts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)

    with pytest.raises(ValueError, match="addopts"):
        _configured_plugin(
            module,
            tmp_path,
            suite_id="task06a_completed_result_identity_v1",
            addopts=("--ignore=tests",),
        )


def test_plugin_rejects_premature_success_without_closed_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setattr(module, "capture_source_snapshot", lambda: deepcopy(snapshot))
    config, output = _configured_plugin(
        module,
        tmp_path,
        suite_id="task06a_completed_result_identity_v1",
    )

    class Item:
        nodeid = "tests/test_learning_workflow_stage_worker.py::test_one"

    class Session:
        items = [Item()]
        testsfailed = 0

        def __init__(self, configured):
            self.config = configured

    session = Session(config)
    module.pytest_sessionstart(session)
    module.pytest_sessionfinish(session, 0)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert receipt["status"] == "FAIL"


def test_plugin_stable_in_process_session_can_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _, _, snapshot = _synthetic_snapshot(module, tmp_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTEST_PLUGINS", raising=False)
    monkeypatch.setattr(module, "capture_source_snapshot", lambda: deepcopy(snapshot))
    config, output = _configured_plugin(
        module,
        tmp_path,
        suite_id="task06a_completed_result_identity_v1",
    )

    class Item:
        nodeid = "tests/test_learning_workflow_stage_worker.py::test_one"

    class Session:
        items = [Item()]
        testsfailed = 0

        def __init__(self, configured):
            self.config = configured

    class Report:
        nodeid = Item.nodeid
        when = "call"
        passed = True
        failed = False
        skipped = False

    session = Session(config)
    module.pytest_sessionstart(session)
    module.pytest_collection_finish(session)
    module.pytest_runtest_logreport(Report())
    module.pytest_sessionfinish(session, 0)
    receipt = json.loads(output.read_text(encoding="utf-8"))

    assert receipt["status"] == "PASS"


def test_final_seal_production_api_rejects_synthetic_bypass(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    task12 = module.build_dependency_result_receipt(
        suite_id="task12_release_gate_v1",
        pytest_argv=module.FROZEN_PYTEST_ARGV_BY_SUITE_ID["task12_release_gate_v1"],
        pre_source_snapshot=snapshot,
        post_source_snapshot=snapshot,
        exit_code=0,
        collected_count=1,
        failed_count=0,
    )

    with pytest.raises(ValueError, match="release dependency manifest"):
        module.validate_final_seal_source_binding(
            sealed_production_sha256_by_path=manifest[
                "production_sha256_by_path"
            ],
            sealed_test_sha256_by_path=manifest["test_sha256_by_path"],
            dependency_manifest=manifest,
        )


def test_release_manifest_validator_has_no_synthetic_bypass_parameter() -> None:
    module = _module()

    assert "allow_synthetic_test" not in inspect.signature(
        module.validate_release_dependency_manifest
    ).parameters


def test_production_builder_has_no_evidence_injection_or_capability_routes(
    tmp_path: Path,
) -> None:
    module = _module()

    assert set(inspect.signature(module.build_release_dependency_manifest).parameters) == {
        "benchmark_release_id"
    }
    assert not hasattr(module, "_ReleaseDependencyEvidence")
    assert not hasattr(module, "_Task12AcceptanceEvidence")
    assert not hasattr(module, "_PRODUCTION_CAPABILITY_TOKEN")
    assert not hasattr(module, "load_release_dependency_evidence")
    with pytest.raises(TypeError):
        module.build_release_dependency_manifest(
            benchmark_release_id="release",
            result_receipt_paths_by_suite={"fabricated": tmp_path / "receipt.json"},
        )


def test_current_production_builder_fails_closed_on_absent_canonical_evidence() -> None:
    module = _module()

    with pytest.raises(ValueError, match="result receipt.*missing"):
        module.build_release_dependency_manifest(benchmark_release_id="release")


def test_synthetic_builder_deep_copies_all_caller_inputs(tmp_path: Path) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    frozen = module.pretty_json_bytes(manifest)

    evidence[0][module.DEPENDENCY_ORDER[0]]["status"] = "FAIL"
    evidence[1][module.DEPENDENCY_ORDER[0]]["file_sha256"] = "0" * 64
    evidence[2][module.DEPENDENCY_ORDER[0]]["reviewer_independent"] = False
    snapshot["production_source_sha256_by_path"][production_paths[0]] = "0" * 64

    assert module.pretty_json_bytes(manifest) == frozen


@pytest.mark.parametrize(
    "hook_name", ["pytest_runtest_makereport", "pytest_sessionfinish"]
)
def test_any_foreign_pytest_hook_is_rejected(hook_name: str) -> None:
    module = _module()

    class ForeignPlugin:
        pass

    setattr(ForeignPlugin, hook_name, lambda *args, **kwargs: None)

    class PluginManager:
        @staticmethod
        def get_plugins():
            return {ForeignPlugin()}

    class Config:
        pluginmanager = PluginManager()

    assert module._foreign_collection_hook_present(Config()) is True


@pytest.mark.parametrize(
    "mutation",
    ["content_hash", "safety", "dag", "result_ref", "review_ref"],
)
def test_synthetic_validator_rejects_full_manifest_and_receipt_ref_drift(
    tmp_path: Path, mutation: str
) -> None:
    module = _module()
    production_paths, test_paths, snapshot = _synthetic_snapshot(module, tmp_path)
    evidence = _synthetic_evidence(module, snapshot)
    manifest = module._build_synthetic_dependency_manifest_for_test(
        benchmark_release_id="synthetic-release",
        result_receipts_by_suite=evidence[0],
        result_receipt_refs_by_suite=evidence[1],
        review_receipts_by_suite=evidence[2],
        review_receipt_refs_by_suite=evidence[3],
        source_snapshot=snapshot,
        production_paths=production_paths,
        test_paths=test_paths,
    )
    changed = deepcopy(manifest)
    if mutation == "content_hash":
        changed["content_sha256"] = "0" * 64
    elif mutation == "safety":
        changed["safety"]["display_only"] = False
        changed["content_sha256"] = module.content_sha256(changed)
    elif mutation == "dag":
        changed["dependency_order"].reverse()
        changed["content_sha256"] = module.content_sha256(changed)
    elif mutation == "result_ref":
        changed["result_receipt_refs"][module.DEPENDENCY_ORDER[0]][
            "file_sha256"
        ] = "0" * 64
        changed["content_sha256"] = module.content_sha256(changed)
    else:
        changed["review_receipt_refs"][module.DEPENDENCY_ORDER[0]][
            "file_sha256"
        ] = "0" * 64
        changed["content_sha256"] = module.content_sha256(changed)

    with pytest.raises(ValueError, match="manifest|receipt"):
        module._validate_synthetic_dependency_manifest_for_test(
            changed,
            result_receipts_by_suite=evidence[0],
            result_receipt_refs_by_suite=evidence[1],
            review_receipts_by_suite=evidence[2],
            review_receipt_refs_by_suite=evidence[3],
            current_source_snapshot=snapshot,
            production_paths=production_paths,
            test_paths=test_paths,
        )


def test_final_report_and_seal_apis_have_no_evidence_injection() -> None:
    module = _module()

    assert set(
        inspect.signature(module.validate_dependency_manifest_for_final_report).parameters
    ) == {"manifest"}
    assert set(inspect.signature(module.validate_final_seal_source_binding).parameters) == {
        "sealed_production_sha256_by_path",
        "sealed_test_sha256_by_path",
        "dependency_manifest",
    }


def test_source_snapshot_rejects_root_symlink_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_root = tmp_path / "real"
    source = real_root / "production/a.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"alpha\n")
    test_source = real_root / "tests/test_a.py"
    test_source.parent.mkdir(parents=True)
    test_source.write_bytes(b"test\n")
    alias_root = tmp_path / "alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        alias_root.mkdir()
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == alias_root or original_is_symlink(self),
        )

    with pytest.raises(ValueError, match="alias"):
        module.capture_source_snapshot(
            root=alias_root,
            production_paths=("production/a.py",),
            test_paths=("tests/test_a.py",),
        )



def test_source_snapshot_rejects_hard_link_alias(tmp_path: Path) -> None:
    module = _module()
    real_root = tmp_path / "real"
    source = real_root / "production/a.py"
    source.parent.mkdir(parents=True)
    test_source = real_root / "tests/test_a.py"
    test_source.parent.mkdir(parents=True)
    test_source.write_bytes(b"test\n")
    outside = tmp_path / "outside.py"
    outside.write_bytes(b"alpha\n")
    os.link(outside, source)
    with pytest.raises(ValueError, match="hard-link"):
        module.capture_source_snapshot(
            root=real_root,
            production_paths=("production/a.py",),
            test_paths=("tests/test_a.py",),
        )


def test_output_rejects_alias_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    real_root = tmp_path / "real"
    real_root.mkdir()
    alias_root = tmp_path / "alias"
    try:
        alias_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        alias_root.mkdir()
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == alias_root or original_is_symlink(self),
        )

    with pytest.raises(ValueError, match="alias"):
        module.write_create_new_or_byte_identical(alias_root / "artifact.json", b"{}\n")



def test_output_rejects_existing_hard_link(tmp_path: Path) -> None:
    module = _module()
    real_root = tmp_path / "real"
    real_root.mkdir()
    original = tmp_path / "original.json"
    original.write_bytes(b"{}\n")
    hard_link = real_root / "artifact.json"
    os.link(original, hard_link)
    with pytest.raises(FileExistsError, match="hard-link"):
        module.write_create_new_or_byte_identical(hard_link, b"{}\n")


def test_module_has_no_launcher_or_runtime_dependency() -> None:
    module = _module()
    source_path = Path(module.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "subprocess" not in imported_roots
    assert "app" not in imported_roots
    assert not hasattr(module, "run_pytest")
    assert not hasattr(module, "launch_provider")
