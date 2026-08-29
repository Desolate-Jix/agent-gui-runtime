from __future__ import annotations

import importlib.util
import ast
import hashlib
import json
import base64
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.learn.hybrid.benchmark_v2_contracts import (
    BENCHMARK_RELEASE_ID,
    PROVIDER_MANIFEST_CONTRACT,
)
from app.learn.hybrid.benchmark_v2_durable_claim import (
    EXACT_ARM_ORDER,
    EXACT_HOLDOUT_COMMAND,
    EXACT_RUN_ORDER,
    IDENTITY,
    _test_backend,
    canonical_bytes,
    claim_id,
)


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task11_scripts_export_closed_contract_builders() -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")

    assert callable(review.build_leakage_review)
    assert callable(review.validate_leakage_review)
    assert callable(authorize.build_authorization_payload)
    assert callable(authorize.authorize_holdout)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _refs() -> tuple[dict[str, str], dict[str, object], dict[str, str]]:
    provider = {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "relative_path": "benchmark-v2-provider-manifest.json",
        "file_sha256": _sha("provider"),
    }
    corpus = {
        "contract_version": "portfolio_hybrid_v1_1_provider_corpus_v2",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": _sha("corpus-file"),
        "content_sha256": _sha("corpus-content"),
        "source_parent_ref": {
            "contract_version": "portfolio_hybrid_v1_1_corpus_v1",
            "artifact_id": "portfolio-hybrid-v1-1-corpus-v1",
            "file_sha256": _sha("parent-file"),
            "content_sha256": _sha("parent-content"),
        },
    }
    accepted = {
        "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
        "file_sha256": _sha("accepted-file"),
        "content_sha256": _sha("accepted-content"),
    }
    return provider, corpus, accepted


def test_leakage_review_contract_hash_order_and_pretty_lf_publication(
    tmp_path: Path,
) -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    provider, corpus, accepted = _refs()
    artifact = review.build_leakage_review(
        provider_manifest_ref=provider,
        provider_corpus_ref=corpus,
        accepted_run_ref=accepted,
        finding_codes=["FORBIDDEN_TEXT_FRAGMENT", "ABSOLUTE_PATH"],
    )

    assert list(artifact) == [
        "contract_version",
        "benchmark_release_id",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "accepted_run_ref",
        "finding_codes",
        "status",
        "safety",
        "content_sha256",
    ]
    assert artifact["finding_codes"] == [
        "ABSOLUTE_PATH",
        "FORBIDDEN_TEXT_FRAGMENT",
    ]
    assert artifact["status"] == "FAIL"
    assert artifact["content_sha256"] == hashlib.sha256(
        canonical_bytes({key: value for key, value in artifact.items() if key != "content_sha256"})
    ).hexdigest()

    output = tmp_path / "review.json"
    summary = review.publish_leakage_review(output_path=output, review=artifact)
    expected = json.dumps(
        artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    assert output.read_bytes() == expected
    assert summary == {
        "content_sha256": artifact["content_sha256"],
        "review_ref": {
            "contract_version": "benchmark_v2_leakage_review_v1",
            "file_sha256": hashlib.sha256(expected).hexdigest(),
            "content_sha256": artifact["content_sha256"],
        },
        "status": "FAIL",
    }
    assert review.publish_leakage_review(output_path=output, review=artifact) == summary
    output.write_bytes(b"different\n")
    with pytest.raises(FileExistsError, match="different bytes"):
        review.publish_leakage_review(output_path=output, review=artifact)


@pytest.mark.parametrize(
    ("codes", "status"),
    [([], "FAIL"), (["UNKNOWN"], "FAIL"), (["ABSOLUTE_PATH"] * 2, "FAIL")],
)
def test_leakage_review_rejects_status_enum_order_and_duplicates(
    codes: list[str], status: str
) -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    provider, corpus, accepted = _refs()
    artifact = review.build_leakage_review(
        provider_manifest_ref=provider,
        provider_corpus_ref=corpus,
        accepted_run_ref=accepted,
        finding_codes=[],
    )
    artifact["finding_codes"] = codes
    artifact["status"] = status
    artifact["content_sha256"] = hashlib.sha256(
        canonical_bytes({key: value for key, value in artifact.items() if key != "content_sha256"})
    ).hexdigest()
    with pytest.raises(ValueError, match="leakage review"):
        review.validate_leakage_review(artifact)


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ({"gold": "x"}, "FORBIDDEN_FIELD_NAME"),
        ({"value": "GOLD.V1.JSON"}, "FORBIDDEN_TEXT_FRAGMENT"),
        ({"value": r"C:\\private\\score.json"}, "ABSOLUTE_PATH"),
        ({"value": "private/evidence.json"}, "FORBIDDEN_LOGICAL_PATH"),
        ({"payload_bytes_b64": "%%%"}, "INVALID_BASE64_PAYLOAD"),
    ],
)
def test_shared_scanner_findings_are_mapped_to_exact_task11_codes(
    value: object, code: str
) -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    assert review.find_public_leakage_codes(value) == [code]


def _backend(tmp_path: Path):
    token = "a" * 32
    base = (
        tmp_path
        / "AgentGuiRuntime"
        / "Tests"
        / "PortfolioHybridBenchmarkV2"
        / token
    ).resolve()
    return _test_backend(
        file_root=base / "Claims",
        registry_root=rf"Software\AgentGuiRuntime\Tests\PortfolioHybridBenchmarkV2\{token}\Claims",
        ledger_root=base / "Ledger",
        capability=token,
    )


def _validated_provider_manifest() -> dict[str, object]:
    return {
        "contract_version": PROVIDER_MANIFEST_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "sealed_runtime": {
            "code_refs": [
                {
                    "role": "bootstrap",
                    "relative_path": "app/learn/hybrid/bootstrap.py",
                    "file_sha256": _sha("boot"),
                }
            ],
            "release_code_refs": [
                {
                    "role": "release",
                    "relative_path": "scripts/release.py",
                    "file_sha256": _sha("release"),
                }
            ],
            "profile_refs": [
                {
                    "role": "portfolio_hybrid_v1_1_default",
                    "relative_path": "configs/profiles/default.json",
                    "file_sha256": _sha("profile"),
                }
            ],
        },
        "arm_order": list(EXACT_ARM_ORDER),
    }


def _probe_authority_ref() -> dict[str, str]:
    return {
        "id": "probe-authority/" + "a" * 64,
        "content_sha256": _sha("probe authority"),
    }


def _runtime_profile_map() -> dict[str, str]:
    return {
        "omni-runtime": _sha("omni runtime profile"),
        "qwen-runtime": _sha("qwen runtime profile"),
        "vista-runtime": _sha("vista runtime profile"),
    }


def test_authorization_payload_v2_uses_only_probe_runtime_profiles_and_frozen_identity(
    tmp_path: Path,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    backend = _backend(tmp_path)
    payload = authorize.build_authorization_payload(
        validated_provider_manifest=_validated_provider_manifest(),
        provider_manifest_sha256=_sha("provider bytes"),
        regression_probe_authority_ref=_probe_authority_ref(),
        profile_sha256_by_id=_runtime_profile_map(),
        backend=backend,
    )

    cid = claim_id(IDENTITY)
    assert payload["claim_identity"] == IDENTITY
    assert payload["claim_id"] == cid
    assert payload["contract_version"] == (
        "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v2"
    )
    assert payload["profile_sha256_by_id"] == _runtime_profile_map()
    assert "portfolio_hybrid_v1_1_default" not in payload["profile_sha256_by_id"]
    assert payload["config_sha256_by_path"] == {
        "configs/profiles/default.json": _sha("profile")
    }
    assert payload["regression_probe_authority_ref"] == _probe_authority_ref()
    assert payload["code_sha256_by_path"] == {
        "app/learn/hybrid/bootstrap.py": _sha("boot"),
        "scripts/release.py": _sha("release"),
    }
    assert payload["fixed_authorization_path"] == str(
        backend.file_root / f"{cid}.authorization.json"
    )
    assert payload["exact_holdout_command"] == list(EXACT_HOLDOUT_COMMAND)
    assert payload["exact_run_order"] == list(EXACT_RUN_ORDER)


def test_authorization_payload_v2_does_not_conflate_manifest_roles_with_runtime_profiles(
    tmp_path: Path,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    backend = _backend(tmp_path)
    manifest = _validated_provider_manifest()
    manifest["sealed_runtime"]["profile_refs"].append(
        {
            "role": "portfolio_hybrid_v1_1_default",
            "relative_path": "configs/profiles/alternate.json",
            "file_sha256": _sha("alternate"),
        }
    )
    payload = authorize.build_authorization_payload(
        validated_provider_manifest=manifest,
        provider_manifest_sha256=_sha("provider bytes"),
        regression_probe_authority_ref=_probe_authority_ref(),
        profile_sha256_by_id=_runtime_profile_map(),
        backend=backend,
    )
    assert payload["profile_sha256_by_id"] == _runtime_profile_map()
    assert payload["config_sha256_by_path"] == {
        "configs/profiles/default.json": _sha("profile"),
        "configs/profiles/alternate.json": _sha("alternate"),
    }


def test_review_stdout_is_one_pathless_three_field_canonical_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    summary = {
        "content_sha256": _sha("review"),
        "review_ref": {
            "contract_version": "benchmark_v2_leakage_review_v1",
            "file_sha256": _sha("review-file"),
            "content_sha256": _sha("review"),
        },
        "status": "PASS",
    }
    monkeypatch.setattr(review, "review_leakage", lambda **_: summary)
    assert review.main(
        [
            "--provider-manifest",
            "provider.json",
            "--regression-run-ref",
            "accepted.json",
            "--output",
            "review.json",
        ]
    ) == 0
    captured = capsys.readouterr()
    expected = json.dumps(
        summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    assert captured.out == expected and captured.err == ""
    assert not any(marker in captured.out for marker in (":\\", "/tmp/", "fixed_authorization_path"))


def test_task11_scripts_never_import_private_score_or_release_authorities() -> None:
    forbidden = {
        "app.learn.hybrid.benchmark_scorer_v2",
        "app.learn.hybrid.benchmark_v2_private_release",
        "scripts.seal_portfolio_hybrid_v1_1_benchmark_v2",
    }
    for name in (
        "review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py",
        "authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py",
    ):
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        assert imports.isdisjoint(forbidden)


def test_authorizer_requires_pass_and_exact_public_score_lineage() -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    provider, corpus, accepted = _refs()
    private_sha = _sha("opaque private bytes")
    binding = {
        "private_manifest_ref": {"file_sha256": private_sha},
        "corpus_parent_ref": corpus["source_parent_ref"],
        "provider_manifest_ref": provider,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted,
    }
    score = {"status": "PASS", "score_input_binding": binding}

    authorize._validate_score_lineage(
        score=score,
        private_manifest_sha256=private_sha,
        provider_manifest_ref=provider,
        provider_corpus_ref=corpus,
        accepted_run_ref=accepted,
    )
    for mutation in ("status", "private", "provider", "accepted"):
        changed = json.loads(json.dumps(score))
        if mutation == "status":
            changed["status"] = "FAIL"
        elif mutation == "private":
            changed["score_input_binding"]["private_manifest_ref"]["file_sha256"] = "0" * 64
        elif mutation == "provider":
            changed["score_input_binding"]["provider_manifest_ref"]["file_sha256"] = "0" * 64
        else:
            changed["score_input_binding"]["accepted_run_ref"]["file_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="score|private|lineage"):
            authorize._validate_score_lineage(
                score=changed,
                private_manifest_sha256=private_sha,
                provider_manifest_ref=provider,
                provider_corpus_ref=corpus,
                accepted_run_ref=accepted,
            )


def test_provider_drift_never_changes_stable_claim_namespace(tmp_path: Path) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    backend = _backend(tmp_path)
    first = authorize.build_authorization_payload(
        validated_provider_manifest=_validated_provider_manifest(),
        provider_manifest_sha256=_sha("provider one"),
        regression_probe_authority_ref=_probe_authority_ref(),
        profile_sha256_by_id=_runtime_profile_map(),
        backend=backend,
    )
    second = authorize.build_authorization_payload(
        validated_provider_manifest=_validated_provider_manifest(),
        provider_manifest_sha256=_sha("provider two"),
        regression_probe_authority_ref=_probe_authority_ref(),
        profile_sha256_by_id=_runtime_profile_map(),
        backend=backend,
    )
    assert first["claim_id"] == second["claim_id"] == claim_id(IDENTITY)
    assert first["claim_identity"] == second["claim_identity"] == IDENTITY
    assert first["provider_manifest_sha256"] != second["provider_manifest_sha256"]


def test_authorizer_resolves_only_frozen_production_ledger_token() -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    expected = (
        ROOT
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "benchmark-v2-ledger"
    ).resolve()
    assert authorize._resolve_production_ledger_root(
        Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger")
    ) == expected
    with pytest.raises(ValueError, match="token"):
        authorize._resolve_production_ledger_root(
            Path("runtime_state/portfolio-hybrid-v1-1/BENCHMARK-v2-ledger")
        )


def test_self_hashed_synthetic_accepted_root_is_rejected() -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    provider, corpus, _ = _refs()
    synthetic: dict[str, object] = {
        "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": "regression",
        "corpus_parent_ref": corpus["source_parent_ref"],
        "provider_manifest_ref": provider,
        "provider_corpus_ref": corpus,
        "selection_policy": "first_complete_lifecycle_verified_attempt",
        "attempt_ref": {"id": "attempt/synthetic", "content_sha256": "1" * 64},
        "attempt_ledger_ref": {"id": "ledger/synthetic", "content_sha256": "2" * 64},
        "automatic_prediction_ref": {"id": "automatic/synthetic", "content_sha256": "3" * 64},
        "selected_lifecycle_ref": {"id": "lifecycle/synthetic", "content_sha256": "4" * 64},
        "verified_parent_projections": {},
        "prediction_run_envelope": {
            "ref": {"id": "prediction/synthetic", "content_sha256": "5" * 64},
            "canonical_bytes_b64": base64.b64encode(b"{}").decode("ascii"),
        },
        "lifecycle_bundle_envelope": {
            "ref": {"id": "lifecycle-bundle/synthetic", "content_sha256": "6" * 64},
            "canonical_bytes_b64": base64.b64encode(b"{}").decode("ascii"),
        },
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        },
    }
    synthetic["content_sha256"] = hashlib.sha256(
        canonical_bytes(synthetic)
    ).hexdigest()
    raw = canonical_bytes(synthetic) + b"\n"
    with pytest.raises(ValueError, match="accepted regression"):
        review._validate_accepted_run(synthetic, raw)


@pytest.mark.parametrize(
    "field",
    [
        "attempt_ref",
        "attempt_ledger_ref",
        "automatic_prediction_ref",
        "selected_lifecycle_ref",
        "estimand_ref",
        "gate_ref",
        "corpus_parent_ref",
    ],
)
def test_score_binding_requires_every_public_ref(field: str) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    provider, corpus, accepted_ref = _refs()
    accepted = {
        "attempt_ref": {"id": "attempt/exact", "content_sha256": "1" * 64},
        "attempt_ledger_ref": {"id": "ledger/exact", "content_sha256": "2" * 64},
        "automatic_prediction_ref": {"id": "automatic/exact", "content_sha256": "3" * 64},
        "selected_lifecycle_ref": {"id": "lifecycle/exact", "content_sha256": "4" * 64},
    }
    manifest = {
        "evaluation_projection": {
            "estimand": {"contract_version": "estimand-v2", "file_sha256": "5" * 64},
            "gate": {"contract_version": "gate-v2", "file_sha256": "6" * 64},
        }
    }
    private_sha = _sha("private")
    binding = {
        "private_manifest_ref": {"file_sha256": private_sha},
        "corpus_parent_ref": corpus["source_parent_ref"],
        "provider_manifest_ref": provider,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted_ref,
        **accepted,
        "estimand_ref": manifest["evaluation_projection"]["estimand"],
        "gate_ref": manifest["evaluation_projection"]["gate"],
    }
    binding[field] = {"id": "forged", "content_sha256": "0" * 64}
    with pytest.raises(ValueError, match="lineage"):
        authorize._validate_score_lineage(
            score={"status": "PASS", "score_input_binding": binding},
            private_manifest_sha256=private_sha,
            provider_manifest_ref=provider,
            provider_corpus_ref=corpus,
            accepted_run_ref=accepted_ref,
            accepted=accepted,
            validated_provider_manifest=manifest,
        )


def _probe_authority_validation():
    provider, corpus, accepted = _refs()
    matrix = [
        [provider_id, probe_kind]
        for provider_id in ("omni", "qwen", "vista")
        for probe_kind in ("cancel", "timeout")
    ]
    bundle = {
        "contract_version": "benchmark_v2_regression_probe_authority_bundle_v1",
        "artifact_id": _probe_authority_ref()["id"],
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": "regression",
        "provider_manifest_ref": provider,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted,
        "selection_policy": "first_complete_verified_attempt_per_cell",
        "required_matrix": matrix,
        "probe_ledger_horizon_refs": [],
        "probe_cells": [
            {"provider_id": provider_id, "probe_kind": probe_kind, "status": "PASS"}
            for provider_id, probe_kind in matrix
        ],
        "status": "PASS",
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        },
        "content_sha256": _probe_authority_ref()["content_sha256"],
    }
    return SimpleNamespace(
        bundle=bundle,
        profile_sha256_by_id=_runtime_profile_map(),
    )


def _probe_join_inputs():
    provider, corpus, accepted = _refs()
    score = {
        "score_input_binding": {
            "provider_manifest_ref": provider,
            "provider_corpus_ref": corpus,
            "corpus_parent_ref": corpus["source_parent_ref"],
            "accepted_run_ref": accepted,
        }
    }
    review = {
        "provider_manifest_ref": provider,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted,
    }
    return provider, corpus, accepted, score, review


def test_probe_authority_join_accepts_exact_six_pass_cells_and_runtime_profiles() -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    provider, corpus, accepted, score, review = _probe_join_inputs()
    ref, profiles = authorize._validate_probe_authority_join(
        _probe_authority_validation(),
        provider_manifest_ref=provider,
        provider_corpus_ref=corpus,
        accepted_run_ref=accepted,
        score=score,
        review=review,
    )
    assert ref == _probe_authority_ref()
    assert profiles == _runtime_profile_map()


@pytest.mark.parametrize(
    "drift",
    [
        "release",
        "provider",
        "corpus_parent",
        "accepted_file",
        "matrix_order",
        "missing_cell",
        "cell_fail",
        "private_path",
        "missing_profile",
        "score",
        "review",
    ],
)
def test_probe_authority_join_drift_fails_closed_before_publisher(
    drift: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    validation = _probe_authority_validation()
    provider, corpus, accepted, score, review = _probe_join_inputs()
    if drift == "release":
        validation.bundle["benchmark_release_id"] = "other-release"
    elif drift == "provider":
        validation.bundle["provider_manifest_ref"]["file_sha256"] = "0" * 64
    elif drift == "corpus_parent":
        validation.bundle["provider_corpus_ref"]["source_parent_ref"]["file_sha256"] = "0" * 64
    elif drift == "accepted_file":
        validation.bundle["accepted_run_ref"]["file_sha256"] = "0" * 64
    elif drift == "matrix_order":
        validation.bundle["required_matrix"] = list(
            reversed(validation.bundle["required_matrix"])
        )
    elif drift == "missing_cell":
        validation.bundle["probe_cells"].pop()
    elif drift == "cell_fail":
        validation.bundle["probe_cells"][0]["status"] = "FAIL"
    elif drift == "private_path":
        validation.bundle["path"] = "private/probe.json"
    elif drift == "missing_profile":
        validation.profile_sha256_by_id.pop("vista-runtime")
    elif drift == "score":
        score["score_input_binding"]["accepted_run_ref"] = {**accepted, "file_sha256": "0" * 64}
    else:
        review["accepted_run_ref"] = {**accepted, "content_sha256": "0" * 64}
    called: list[bool] = []
    monkeypatch.setattr(authorize, "_publish_authorization", lambda **_: called.append(True))
    with pytest.raises(ValueError, match="probe authority"):
        authorize._validate_probe_authority_join(
            validation,
            provider_manifest_ref=provider,
            provider_corpus_ref=corpus,
            accepted_run_ref=accepted,
            score=score,
            review=review,
        )
    assert called == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"GOLD.V1.JSON": "value"}, "FORBIDDEN_TEXT_FRAGMENT"),
        (
            {
                "canonical_bytes_b64": base64.b64encode(
                    json.dumps({"nested": "GOLD.V1.JSON"}).encode("utf-8")
                ).decode("ascii")
            },
            "FORBIDDEN_TEXT_FRAGMENT",
        ),
        ({"value": "%2525252525252525252fetc%252fpasswd"}, "ABSOLUTE_PATH"),
    ],
)
def test_finding_mapper_covers_keys_nested_base64_and_deep_percent_alias(
    value: object, expected: str
) -> None:
    review = _load_script("review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py")
    assert expected in review.find_public_leakage_codes(value)


def test_production_alias_fails_before_any_publisher_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    called = []
    monkeypatch.setattr(authorize, "_publish_authorization", lambda **_: called.append(True))
    with pytest.raises(ValueError, match="canonical Task14 path"):
        authorize.authorize_holdout(
            private_manifest_path=Path("tests/fixtures/portfolio_hybrid_v1_1/../portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json"),
            provider_manifest_path=Path("tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json"),
            regression_run_ref_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json"),
            score_ref_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json"),
            leakage_review_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json"),
            probe_authority_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json"),
            ledger_root="runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
            output_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json"),
        )
    assert called == []


def test_probe_authority_cli_is_required_and_fixed() -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    assert authorize._TASK14_PATH_TOKENS["probe_authority_path"] == (
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json"
    )
    with pytest.raises(SystemExit):
        authorize._parser().parse_args([])


@pytest.mark.parametrize(
    "flag",
    [
        "--private-manifest",
        "--provider-manifest",
        "--regression-run-ref",
        "--score-ref",
        "--leakage-review",
        "--probe-authority",
        "--ledger-root",
        "--output",
    ],
)
@pytest.mark.parametrize("form", ["separated", "equals", "mixed"])
def test_probe_authority_duplicate_guard_rejects_every_fixed_flag_and_form_without_values(
    flag: str,
    form: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    flags = [
        "--private-manifest",
        "--provider-manifest",
        "--regression-run-ref",
        "--score-ref",
        "--leakage-review",
        "--probe-authority",
        "--ledger-root",
        "--output",
    ]
    tokens: list[str] = []
    for item in flags:
        if item != flag:
            tokens.extend([item, "ordinary-value"])
    if form == "separated":
        tokens.extend([flag, "secret-one", flag, "secret-two"])
    elif form == "equals":
        tokens.extend([f"{flag}=secret-one", f"{flag}=secret-two"])
    else:
        tokens.extend([flag, "secret-one", f"{flag}=secret-two"])
    called: list[bool] = []
    monkeypatch.setattr(
        authorize,
        "authorize_holdout",
        lambda **_kwargs: called.append(True)
        or {
            "authorization_id": "holdout-authorization/" + "a" * 64,
            "envelope_sha256": "b" * 64,
        },
    )
    with pytest.raises(SystemExit):
        authorize.main(tokens)
    captured = capsys.readouterr()
    assert called == []
    assert f"argument {flag}: may not be repeated" in captured.err
    assert "secret-one" not in captured.err
    assert "secret-two" not in captured.err


def test_probe_authority_alias_path_fails_before_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    published: list[bool] = []
    monkeypatch.setattr(authorize, "_publish_authorization", lambda **_: published.append(True))
    with pytest.raises(ValueError, match="canonical Task14 path"):
        authorize.authorize_holdout(
            private_manifest_path=Path("tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json"),
            provider_manifest_path=Path("tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json"),
            regression_run_ref_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json"),
            score_ref_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json"),
            leakage_review_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json"),
            probe_authority_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/../regression/probe-authority.json"),
            ledger_root="runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
            output_path=Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json"),
        )
    assert published == []


@pytest.mark.parametrize(
    "failure",
    [
        "probe authority candidate differs from authoritative bytes",
        "cancel probe ledger fixed file is missing",
        "first complete lifecycle probe receipt is invalid",
    ],
)
def test_probe_authority_candidate_or_raw_parent_failure_precedes_publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    value = _backend(tmp_path)
    calls: list[bool] = []

    def reject_candidate(**_kwargs):
        calls.append(True)
        raise ValueError(failure)

    published: list[bool] = []
    monkeypatch.setattr(
        authorize,
        "validate_benchmark_v2_regression_probe_authority_candidate",
        reject_candidate,
    )
    monkeypatch.setattr(
        authorize, "_publish_authorization_for_test", lambda **_: published.append(True)
    )
    with pytest.raises(ValueError, match="candidate differs|ledger fixed file|receipt"):
        authorize.authorize_holdout(
            private_manifest_path=tmp_path / "private.json",
            provider_manifest_path=tmp_path / "provider.json",
            regression_run_ref_path=tmp_path / "accepted.json",
            score_ref_path=tmp_path / "score.json",
            leakage_review_path=tmp_path / "review.json",
            probe_authority_path=tmp_path / "probe-authority.json",
            ledger_root=value.ledger_root,
            output_path=value.file_root.parent / "AuthorizationRef" / "holdout-authorization.json",
            _backend=value,
        )
    assert calls == [True]
    assert published == []


def test_probe_authority_consumer_receives_real_pretty_accepted_bytes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = _load_script("authorize_portfolio_hybrid_v1_1_benchmark_v2_holdout.py")
    value = _backend(tmp_path)
    provider_path = tmp_path / "benchmark-v2-provider-manifest.json"
    corpus_path = tmp_path / "provider-corpus.v2.json"
    accepted_path = tmp_path / "accepted-run-ref.json"
    score_path = tmp_path / "score-ref.json"
    review_path = tmp_path / "leakage-review.json"
    private_path = tmp_path / "private.json"
    probe_path = tmp_path / "probe-authority.json"
    provider, corpus, _accepted_ref_placeholder = _refs()
    manifest = _validated_provider_manifest()
    manifest["provider_corpus_ref"] = corpus
    manifest["evaluation_projection"] = {
        "estimand": {"contract_version": "estimand-v2", "file_sha256": "5" * 64},
        "gate": {"contract_version": "gate-v2", "file_sha256": "6" * 64},
    }
    provider_raw = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    provider_path.write_bytes(provider_raw)
    corpus_path.write_bytes(b"provider corpus bytes")
    manifest_ref = authorize._provider_manifest_ref(provider_raw)
    accepted = {
        "content_sha256": _sha("accepted content"),
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "provider_manifest_ref": manifest_ref,
        "provider_corpus_ref": corpus,
        "corpus_parent_ref": corpus["source_parent_ref"],
        "attempt_ref": {"id": "runner-attempt/accepted", "content_sha256": "1" * 64},
        "attempt_ledger_ref": {"id": "ledger/accepted", "content_sha256": "2" * 64},
        "automatic_prediction_ref": {"id": "prediction/accepted", "content_sha256": "3" * 64},
        "selected_lifecycle_ref": {"id": "lifecycle/accepted", "content_sha256": "4" * 64},
    }
    accepted_raw = json.dumps(
        accepted, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ).encode("utf-8") + b"\n"
    accepted_path.write_bytes(accepted_raw)
    accepted_ref = authorize._accepted_run_ref(accepted, accepted_raw)
    private_path.write_bytes(b"opaque private bytes")
    private_sha = hashlib.sha256(private_path.read_bytes()).hexdigest()
    binding = {
        "private_manifest_ref": {"file_sha256": private_sha},
        "corpus_parent_ref": corpus["source_parent_ref"],
        "provider_manifest_ref": manifest_ref,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted_ref,
        "attempt_ref": accepted["attempt_ref"],
        "attempt_ledger_ref": accepted["attempt_ledger_ref"],
        "automatic_prediction_ref": accepted["automatic_prediction_ref"],
        "selected_lifecycle_ref": accepted["selected_lifecycle_ref"],
        "estimand_ref": manifest["evaluation_projection"]["estimand"],
        "gate_ref": manifest["evaluation_projection"]["gate"],
    }
    score = {"status": "PASS", "score_input_binding": binding}
    score_path.write_bytes(canonical_bytes(score) + b"\n")
    review = {
        "status": "PASS",
        "finding_codes": [],
        "provider_manifest_ref": manifest_ref,
        "provider_corpus_ref": corpus,
        "accepted_run_ref": accepted_ref,
    }
    review_path.write_bytes(
        json.dumps(
            review, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )
    validation = _probe_authority_validation()
    validation.bundle["provider_manifest_ref"] = manifest_ref
    validation.bundle["provider_corpus_ref"] = corpus
    validation.bundle["accepted_run_ref"] = accepted_ref
    validation.bundle["artifact_id"] = _probe_authority_ref()["id"]
    validation.bundle["content_sha256"] = _probe_authority_ref()["content_sha256"]
    calls: list[bytes] = []

    def validate_candidate(**kwargs):
        assert kwargs["regression_run_ref_path"] == accepted_path
        raw = accepted_path.read_bytes()
        assert raw == accepted_raw and raw.startswith(b"{\n")
        calls.append(raw)
        return validation

    published: list[dict[str, object]] = []
    monkeypatch.setattr(
        authorize,
        "validate_benchmark_v2_regression_probe_authority_candidate",
        validate_candidate,
    )
    monkeypatch.setattr(authorize, "validate_provider_manifest", lambda _value: manifest)
    monkeypatch.setattr(
        authorize,
        "validate_preloaded_provider_corpus",
        lambda **_kwargs: {"content_sha256": corpus["content_sha256"]},
    )
    monkeypatch.setattr(
        authorize, "validate_private_scorer_public_ref_v3", lambda _value: score
    )
    monkeypatch.setattr(authorize, "validate_leakage_review", lambda _value: review)
    monkeypatch.setattr(
        authorize,
        "_publish_authorization_for_test",
        lambda **kwargs: published.append(kwargs["authorization"])
        or {
            "authorization_id": "holdout-authorization/" + claim_id(IDENTITY),
            "envelope_sha256": "f" * 64,
            "fixed_authorization_path": str(
                value.file_root / f"{claim_id(IDENTITY)}.authorization.json"
            ),
        },
    )
    authorize.authorize_holdout(
        private_manifest_path=private_path,
        provider_manifest_path=provider_path,
        regression_run_ref_path=accepted_path,
        score_ref_path=score_path,
        leakage_review_path=review_path,
        probe_authority_path=probe_path,
        ledger_root=value.ledger_root,
        output_path=value.file_root.parent / "AuthorizationRef" / "holdout-authorization.json",
        _backend=value,
    )
    assert calls == [accepted_raw]
    assert len(published) == 1
    assert published[0]["profile_sha256_by_id"] == _runtime_profile_map()
    assert published[0]["regression_probe_authority_ref"] == _probe_authority_ref()


def test_leakage_cli_redacts_operator_paths(tmp_path: Path) -> None:
    secret = tmp_path / "operator-private-secret.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/review_portfolio_hybrid_v1_1_benchmark_v2_leakage.py"),
            "--provider-manifest",
            str(secret),
            "--regression-run-ref",
            str(tmp_path / "run.json"),
            "--output",
            str(tmp_path / "review.json"),
        ],
        cwd=tmp_path,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 1 and completed.stdout == ""
    assert str(tmp_path) not in completed.stderr
    assert "operator-private-secret" not in completed.stderr
