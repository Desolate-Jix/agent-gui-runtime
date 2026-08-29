"""Authorize the one sealed Benchmark-v2 holdout attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.hybrid.benchmark_v2_contracts import (  # noqa: E402
    BENCHMARK_RELEASE_ID,
    PROVIDER_MANIFEST_CONTRACT,
)
from app.learn.hybrid.benchmark_v2_durable_claim import (  # noqa: E402
    EXACT_ARM_ORDER,
    EXACT_HOLDOUT_COMMAND,
    EXACT_RUN_ORDER,
    IDENTITY,
    PRODUCTION_LEDGER_ROOT,
    _production_backend,
    _production_ledger_root_is_exact,
    _publish_authorization,
    _publish_authorization_for_test,
    _validate_authorization_for_backend,
    claim_id,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (  # noqa: E402
    canonical_json_bytes,
    validate_preloaded_provider_corpus,
    validate_provider_manifest,
)
from app.learn.hybrid.benchmark_v2_public_score import (  # noqa: E402
    validate_private_scorer_public_ref_v3,
)
from app.learn.hybrid.benchmark_v2_probe_authority import (  # noqa: E402
    BenchmarkV2ProbeAuthorityValidation,
    validate_benchmark_v2_regression_probe_authority_candidate,
)
from scripts.review_portfolio_hybrid_v1_1_benchmark_v2_leakage import (  # noqa: E402
    _accepted_run_ref,
    _canonical_bytes,
    _provider_manifest_ref,
    _sha256,
    validate_leakage_review,
)


_SHA_LENGTH = 64
_LEDGER_ROOT_TOKEN = "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger"
_TASK14_PATH_TOKENS = {
    "private_manifest_path": "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-private-manifest.json",
    "provider_manifest_path": "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json",
    "regression_run_ref_path": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json",
    "score_ref_path": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json",
    "leakage_review_path": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/leakage-review.json",
    "probe_authority_path": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json",
    "ledger_root": _LEDGER_ROOT_TOKEN,
    "output_path": "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json",
}


def _has_reparse_ancestor(path: Path) -> bool:
    current = path
    while True:
        if current.exists():
            information = os.lstat(current)
            if stat.S_ISLNK(information.st_mode) or bool(
                getattr(information, "st_file_attributes", 0)
                & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                return True
        if current == current.parent:
            return False
        current = current.parent


def _validate_production_task14_paths(**paths: str | Path) -> dict[str, Path]:
    if set(paths) != set(_TASK14_PATH_TOKENS):
        raise ValueError("canonical Task14 path set differs")
    resolved: dict[str, Path] = {}
    for name, token in _TASK14_PATH_TOKENS.items():
        raw = os.fspath(paths[name])
        if raw != token:
            raise ValueError("canonical Task14 path token differs")
        target = (ROOT / token).resolve()
        if target != ROOT / Path(token) or _has_reparse_ancestor(target):
            raise ValueError("canonical Task14 path authority differs")
        resolved[name] = target
    for name in (
        "private_manifest_path",
        "provider_manifest_path",
        "regression_run_ref_path",
        "score_ref_path",
        "leakage_review_path",
        "probe_authority_path",
    ):
        target = resolved[name]
        if not target.is_file() or target.is_symlink():
            raise ValueError("canonical Task14 input is unavailable")
    output = resolved["output_path"]
    if output.exists() and (not output.is_file() or output.is_symlink()):
        raise ValueError("canonical Task14 output authority differs")
    return resolved


def _resolve_production_ledger_root(value: str | Path) -> Path:
    if isinstance(value, str) and not Path(value).is_absolute() and value != _LEDGER_ROOT_TOKEN:
        raise ValueError("production holdout ledger root token is fixed")
    raw = Path(value)
    if raw.is_absolute():
        if not _production_ledger_root_is_exact(raw):
            raise ValueError("production holdout ledger root is fixed")
        return raw.resolve()
    if raw.as_posix() != _LEDGER_ROOT_TOKEN:
        raise ValueError("production holdout ledger root token is fixed")
    resolved = (ROOT / raw).resolve()
    if resolved != PRODUCTION_LEDGER_ROOT:
        raise ValueError("production holdout ledger root is fixed")
    return resolved


def _read_json(path: Path, *, pretty: bool) -> tuple[dict[str, object], bytes]:
    raw = Path(path).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("authorization input is not UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("authorization input is not an object")
    expected = (
        canonical_json_bytes(value, pretty=True)
        if pretty
        else _canonical_bytes(value) + b"\n"
    )
    if raw != expected:
        raise ValueError("authorization input bytes are not canonical")
    return value, raw


def _read_private_manifest_sha256_once(path: Path) -> str:
    """Treat the private manifest as one opaque byte snapshot."""

    with Path(path).open("rb") as stream:
        raw = stream.read()
    return hashlib.sha256(raw).hexdigest()


def _unique_ref_map(
    refs: object, *, key_field: str, duplicate_name: str
) -> dict[str, str]:
    if not isinstance(refs, list) or not refs:
        raise ValueError(f"provider {duplicate_name} refs are invalid")
    result: dict[str, str] = {}
    for item in refs:
        if not isinstance(item, Mapping):
            raise ValueError(f"provider {duplicate_name} ref is invalid")
        key = item.get(key_field)
        digest = item.get("file_sha256")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(digest, str)
            or len(digest) != _SHA_LENGTH
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"provider {duplicate_name} ref is invalid")
        if key in result:
            raise ValueError(f"provider {duplicate_name} {key_field} is duplicated")
        result[key] = digest
    return result


def build_authorization_payload(
    *,
    validated_provider_manifest: Mapping[str, object],
    provider_manifest_sha256: str,
    regression_probe_authority_ref: Mapping[str, object],
    profile_sha256_by_id: Mapping[str, object],
    backend: object,
) -> dict[str, object]:
    manifest = deepcopy(dict(validated_provider_manifest))
    if (
        manifest.get("contract_version") != PROVIDER_MANIFEST_CONTRACT
        or manifest.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or manifest.get("arm_order") != list(EXACT_ARM_ORDER)
        or not isinstance(provider_manifest_sha256, str)
        or len(provider_manifest_sha256) != _SHA_LENGTH
        or any(
            character not in "0123456789abcdef"
            for character in provider_manifest_sha256
        )
    ):
        raise ValueError("provider authorization binding is invalid")
    runtime = manifest.get("sealed_runtime")
    if not isinstance(runtime, Mapping):
        raise ValueError("provider sealed runtime is invalid")
    code_refs: list[object] = []
    for field in ("code_refs", "release_code_refs"):
        refs = runtime.get(field)
        if not isinstance(refs, list) or not refs:
            raise ValueError("provider code refs are invalid")
        code_refs.extend(refs)
    code_sha256_by_path = _unique_ref_map(
        code_refs, key_field="relative_path", duplicate_name="code path"
    )
    profile_refs = runtime.get("profile_refs")
    config_sha256_by_path = _unique_ref_map(
        profile_refs, key_field="relative_path", duplicate_name="config path"
    )
    cid = claim_id(IDENTITY)
    payload: dict[str, object] = {
        "contract_version": "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v2",
        "claim_identity": dict(IDENTITY),
        "claim_id": cid,
        "ledger_identity": {
            "absolute_ledger_root": str(Path(backend.ledger_root)),
            "holdout_events_path": str(
                Path(backend.ledger_root) / "holdout" / "events.jsonl"
            ),
        },
        "fixed_authorization_path": str(
            Path(backend.file_root) / f"{cid}.authorization.json"
        ),
        "provider_manifest_sha256": provider_manifest_sha256,
        "provider_manifest_contract_version": PROVIDER_MANIFEST_CONTRACT,
        "code_sha256_by_path": code_sha256_by_path,
        "config_sha256_by_path": config_sha256_by_path,
        "profile_sha256_by_id": deepcopy(dict(profile_sha256_by_id)),
        "regression_probe_authority_ref": deepcopy(
            dict(regression_probe_authority_ref)
        ),
        "arm_order": list(EXACT_ARM_ORDER),
        "exact_holdout_command": list(EXACT_HOLDOUT_COMMAND),
        "exact_run_order": list(EXACT_RUN_ORDER),
        "absolute_owner_journal_root": str(Path(backend.owner_journal_root)),
    }
    _validate_authorization_for_backend(backend, payload)
    return payload


def _validate_probe_authority_join(
    validation: BenchmarkV2ProbeAuthorityValidation,
    *,
    provider_manifest_ref: Mapping[str, object],
    provider_corpus_ref: Mapping[str, object],
    accepted_run_ref: Mapping[str, object],
    score: Mapping[str, object],
    review: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, str]]:
    bundle = validation.bundle
    fields = {
        "contract_version",
        "artifact_id",
        "benchmark_release_id",
        "partition",
        "provider_manifest_ref",
        "provider_corpus_ref",
        "accepted_run_ref",
        "selection_policy",
        "required_matrix",
        "probe_ledger_horizon_refs",
        "probe_cells",
        "status",
        "safety",
        "content_sha256",
    }
    matrix = [
        [provider_id, probe_kind]
        for provider_id in ("omni", "qwen", "vista")
        for probe_kind in ("cancel", "timeout")
    ]
    cells = bundle.get("probe_cells") if isinstance(bundle, Mapping) else None
    if (
        not isinstance(bundle, Mapping)
        or set(bundle) != fields
        or bundle.get("contract_version")
        != "benchmark_v2_regression_probe_authority_bundle_v1"
        or bundle.get("benchmark_release_id") != BENCHMARK_RELEASE_ID
        or bundle.get("partition") != "regression"
        or bundle.get("provider_manifest_ref") != dict(provider_manifest_ref)
        or bundle.get("provider_corpus_ref") != dict(provider_corpus_ref)
        or bundle.get("accepted_run_ref") != dict(accepted_run_ref)
        or bundle.get("selection_policy")
        != "first_complete_verified_attempt_per_cell"
        or bundle.get("required_matrix") != matrix
        or bundle.get("status") != "PASS"
        or not isinstance(cells, list)
        or len(cells) != len(matrix)
        or any(
            not isinstance(cell, Mapping)
            or [cell.get("provider_id"), cell.get("probe_kind")] != matrix[index]
            or cell.get("status") != "PASS"
            for index, cell in enumerate(cells)
        )
    ):
        raise ValueError("probe authority release, parent, matrix, or PASS join differs")
    artifact_id = bundle.get("artifact_id")
    content_sha256 = bundle.get("content_sha256")
    if (
        not isinstance(artifact_id, str)
        or not artifact_id.startswith("probe-authority/")
        or len(artifact_id) != len("probe-authority/") + _SHA_LENGTH
        or any(character not in "0123456789abcdef" for character in artifact_id.removeprefix("probe-authority/"))
        or not isinstance(content_sha256, str)
        or len(content_sha256) != _SHA_LENGTH
        or any(character not in "0123456789abcdef" for character in content_sha256)
    ):
        raise ValueError("probe authority pathless ref is invalid")
    profiles = validation.profile_sha256_by_id
    if (
        not isinstance(profiles, Mapping)
        or len(profiles) != 3
        or any(
            not isinstance(profile_id, str)
            or not profile_id
            or profile_id != profile_id.strip()
            or not isinstance(digest, str)
            or len(digest) != _SHA_LENGTH
            or any(character not in "0123456789abcdef" for character in digest)
            for profile_id, digest in profiles.items()
        )
    ):
        raise ValueError("probe authority runtime profile map is invalid")
    binding = score.get("score_input_binding")
    expected = {
        "provider_manifest_ref": dict(provider_manifest_ref),
        "provider_corpus_ref": deepcopy(dict(provider_corpus_ref)),
        "corpus_parent_ref": deepcopy(provider_corpus_ref.get("source_parent_ref")),
        "accepted_run_ref": dict(accepted_run_ref),
    }
    if (
        not isinstance(binding, Mapping)
        or any(binding.get(key) != value for key, value in expected.items())
        or review.get("provider_manifest_ref") != expected["provider_manifest_ref"]
        or review.get("provider_corpus_ref") != expected["provider_corpus_ref"]
        or review.get("accepted_run_ref") != expected["accepted_run_ref"]
    ):
        raise ValueError("probe authority score or leakage review join differs")
    return (
        {"id": artifact_id, "content_sha256": content_sha256},
        deepcopy(dict(profiles)),
    )


def _validate_score_lineage(
    *,
    score: Mapping[str, object],
    private_manifest_sha256: str,
    provider_manifest_ref: Mapping[str, object],
    provider_corpus_ref: Mapping[str, object],
    accepted_run_ref: Mapping[str, object],
    accepted: Mapping[str, object] | None = None,
    validated_provider_manifest: Mapping[str, object] | None = None,
) -> None:
    if score.get("status") != "PASS":
        raise ValueError("regression public score must PASS")
    binding = score.get("score_input_binding")
    if (
        not isinstance(binding, Mapping)
        or binding.get("contract_version") != "private_scorer_input_binding_v1"
        or binding.get("partition") != "regression"
    ):
        raise ValueError("regression public score binding is missing or differs")
    private_ref = binding.get("private_manifest_ref")
    if (
        not isinstance(private_ref, Mapping)
        or private_ref.get("file_sha256") != private_manifest_sha256
    ):
        raise ValueError("opaque private manifest SHA differs from public binding")
    expected = {
        "corpus_parent_ref": deepcopy(provider_corpus_ref.get("source_parent_ref")),
        "provider_manifest_ref": dict(provider_manifest_ref),
        "provider_corpus_ref": dict(provider_corpus_ref),
        "accepted_run_ref": dict(accepted_run_ref),
    }
    if any(binding.get(key) != value for key, value in expected.items()):
        raise ValueError("regression public score release lineage differs")
    if accepted is not None:
        for field in (
            "attempt_ref",
            "attempt_ledger_ref",
            "automatic_prediction_ref",
            "selected_lifecycle_ref",
        ):
            if binding.get(field) != accepted.get(field):
                raise ValueError("regression public score lineage differs")
    if validated_provider_manifest is not None:
        projection = validated_provider_manifest.get("evaluation_projection")
        if not isinstance(projection, Mapping):
            raise ValueError("regression public score lineage differs")
        for field in ("estimand", "gate"):
            item = projection.get(field)
            if not isinstance(item, Mapping):
                raise ValueError("regression public score lineage differs")
            expected_ref = {
                "contract_version": item.get("contract_version"),
                "file_sha256": item.get("file_sha256"),
            }
            if binding.get(f"{field}_ref") != expected_ref:
                raise ValueError("regression public score lineage differs")


def authorize_holdout(
    *,
    private_manifest_path: Path,
    provider_manifest_path: Path,
    regression_run_ref_path: Path,
    score_ref_path: Path,
    leakage_review_path: Path,
    probe_authority_path: Path,
    ledger_root: str | Path,
    output_path: Path,
    _backend: object | None = None,
) -> dict[str, str]:
    if _backend is None:
        canonical = _validate_production_task14_paths(
            private_manifest_path=private_manifest_path,
            provider_manifest_path=provider_manifest_path,
            regression_run_ref_path=regression_run_ref_path,
            score_ref_path=score_ref_path,
            leakage_review_path=leakage_review_path,
            probe_authority_path=probe_authority_path,
            ledger_root=ledger_root,
            output_path=output_path,
        )
        private_manifest_path = canonical["private_manifest_path"]
        provider_manifest_path = canonical["provider_manifest_path"]
        regression_run_ref_path = canonical["regression_run_ref_path"]
        score_ref_path = canonical["score_ref_path"]
        leakage_review_path = canonical["leakage_review_path"]
        probe_authority_path = canonical["probe_authority_path"]
        ledger_root = canonical["ledger_root"]
        output_path = canonical["output_path"]
    backend = _production_backend() if _backend is None else _backend
    resolved_ledger_root = (
        _resolve_production_ledger_root(Path(ledger_root))
        if _backend is None
        else Path(ledger_root).resolve()
    )
    if resolved_ledger_root != Path(backend.ledger_root):
        raise ValueError("holdout ledger root differs from durable authority")

    probe_validation = validate_benchmark_v2_regression_probe_authority_candidate(
        provider_manifest_path=Path(provider_manifest_path),
        regression_run_ref_path=Path(regression_run_ref_path),
        ledger_root=resolved_ledger_root,
        probe_authority_path=Path(probe_authority_path),
    )

    provider_value, provider_raw = _read_json(Path(provider_manifest_path), pretty=True)
    provider = validate_provider_manifest(provider_value)
    manifest_ref = _provider_manifest_ref(provider_raw)
    corpus_ref = deepcopy(provider["provider_corpus_ref"])
    corpus_path = Path(provider_manifest_path).parent / str(corpus_ref["relative_path"])
    if _backend is None and (
        corpus_path != (ROOT / "tests/fixtures/portfolio_hybrid_v1_1/provider-corpus.v2.json")
        or _has_reparse_ancestor(corpus_path)
        or not corpus_path.is_file()
        or corpus_path.is_symlink()
    ):
        raise ValueError("canonical Task14 provider corpus is unavailable")
    corpus_raw = corpus_path.read_bytes()
    corpus = validate_preloaded_provider_corpus(
        raw=corpus_raw,
        expected_sha256=str(corpus_ref["file_sha256"]),
    )
    if corpus.get("content_sha256") != corpus_ref.get("content_sha256"):
        raise ValueError("provider corpus content lineage differs")
    accepted_value, accepted_raw = _read_json(
        Path(regression_run_ref_path), pretty=True
    )
    accepted = accepted_value
    accepted_ref = _accepted_run_ref(accepted, accepted_raw)
    if (
        accepted["provider_manifest_ref"] != manifest_ref
        or accepted["provider_corpus_ref"] != corpus_ref
        or accepted["corpus_parent_ref"] != corpus_ref["source_parent_ref"]
    ):
        raise ValueError("accepted regression release lineage differs")

    score_value, _ = _read_json(Path(score_ref_path), pretty=False)
    score = validate_private_scorer_public_ref_v3(score_value)
    private_sha = _read_private_manifest_sha256_once(Path(private_manifest_path))
    _validate_score_lineage(
        score=score,
        private_manifest_sha256=private_sha,
        provider_manifest_ref=manifest_ref,
        provider_corpus_ref=corpus_ref,
        accepted_run_ref=accepted_ref,
        accepted=accepted,
        validated_provider_manifest=provider,
    )

    review_value, review_raw = _read_json(Path(leakage_review_path), pretty=True)
    review = validate_leakage_review(review_value)
    if (
        review["status"] != "PASS"
        or review["finding_codes"] != []
        or review["provider_manifest_ref"] != manifest_ref
        or review["provider_corpus_ref"] != corpus_ref
        or review["accepted_run_ref"] != accepted_ref
    ):
        raise ValueError("leakage review does not authorize this regression lineage")
    del review_raw
    probe_ref, runtime_profiles = _validate_probe_authority_join(
        probe_validation,
        provider_manifest_ref=manifest_ref,
        provider_corpus_ref=corpus_ref,
        accepted_run_ref=accepted_ref,
        score=score,
        review=review,
    )

    payload = build_authorization_payload(
        validated_provider_manifest=provider,
        provider_manifest_sha256=manifest_ref["file_sha256"],
        regression_probe_authority_ref=probe_ref,
        profile_sha256_by_id=runtime_profiles,
        backend=backend,
    )
    if _backend is None:
        return _publish_authorization(
            backend=backend,
            authorization=payload,
            external_ref_path=Path(output_path).resolve(),
        )
    return _publish_authorization_for_test(
        backend=backend,
        authorization=payload,
        external_ref_path=Path(output_path).resolve(),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--private-manifest", required=True)
    parser.add_argument("--provider-manifest", required=True)
    parser.add_argument("--regression-run-ref", required=True)
    parser.add_argument("--score-ref", required=True)
    parser.add_argument("--leakage-review", required=True)
    parser.add_argument("--probe-authority", required=True)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def _fixed_flag_count(tokens: list[str], flag: str) -> int:
    return sum(token == flag or token.startswith(flag + "=") for token in tokens)


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    flags = (
        "--private-manifest",
        "--provider-manifest",
        "--regression-run-ref",
        "--score-ref",
        "--leakage-review",
        "--probe-authority",
        "--ledger-root",
        "--output",
    )
    for flag in flags:
        if _fixed_flag_count(tokens, flag) > 1:
            _parser().error(f"argument {flag}: may not be repeated")
    args = _parser().parse_args(tokens)
    result = authorize_holdout(
        private_manifest_path=Path(args.private_manifest),
        provider_manifest_path=Path(args.provider_manifest),
        regression_run_ref_path=Path(args.regression_run_ref),
        score_ref_path=Path(args.score_ref),
        leakage_review_path=Path(args.leakage_review),
        probe_authority_path=Path(args.probe_authority),
        ledger_root=args.ledger_root,
        output_path=Path(args.output),
    )
    print(
        _canonical_bytes(
            {
                "authorization_id": result["authorization_id"],
                "envelope_sha256": result["envelope_sha256"],
                "status": "AUTHORIZED",
            }
        ).decode("utf-8")
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("holdout authorization failed", file=sys.stderr)
        raise SystemExit(1) from None
