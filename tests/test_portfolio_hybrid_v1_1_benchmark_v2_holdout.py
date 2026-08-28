from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import winreg
from copy import deepcopy
from pathlib import Path

import pytest

import app.learn.hybrid.benchmark_v2_durable_claim as durable
import app.learn.hybrid.benchmark_v2_holdout as holdout
from app.learn.hybrid.benchmark_v2_contracts import PROVIDER_MANIFEST_CONTRACT

if __name__ == "__main__":
    import site

    site.addsitedir(str(Path(__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.learn.hybrid.benchmark_v2_durable_claim import (
    EXACT_ARM_ORDER,
    EXACT_HOLDOUT_COMMAND,
    EXACT_RUN_ORDER,
    IDENTITY,
    PRODUCTION_FILE_ROOT,
    PRODUCTION_REGISTRY_ROOT,
    RELEASE,
    _claim_with_backend_for_test,
    _close_handle_checked,
    _expected_claim_values,
    _named_mutex,
    _recover_with_backend_for_test,
    _registry_create,
    _sentinel_create,
    _set_file_dacl_for_test,
    _set_registry_dacl_for_test,
    _test_backend,
    _validate_authorization_for_backend,
    _write_secure_new_file,
    authorization_envelope,
    canonical_bytes,
    claim_id,
)
from app.learn.hybrid.benchmark_v2_holdout import (
    _append_for_test,
    _append_regression_event_for_test,
    _authorize_holdout_genesis_for_test,
    _chain,
)
from app.learn.hybrid.windows_process_scope import (
    WindowsProcessScope,
    observe_process_scope_cleanup,
    spawn_process_in_scope,
)


def backend(tmp: Path):
    token = uuid.uuid4().hex
    base = (tmp / "AgentGuiRuntime" / "Tests" / "PortfolioHybridBenchmarkV2" / token).resolve()
    return _test_backend(
        file_root=base / "Claims",
        registry_root=rf"Software\AgentGuiRuntime\Tests\PortfolioHybridBenchmarkV2\{token}\Claims",
        ledger_root=base / "Ledger",
        capability=token,
    )


def authorization(value, provider: str = "1" * 64) -> dict[str, object]:
    cid = claim_id(IDENTITY)
    return {
        "contract_version": "portfolio_hybrid_benchmark_v2_holdout_authorization_payload_v1",
        "claim_identity": dict(IDENTITY),
        "claim_id": cid,
        "ledger_identity": {
            "absolute_ledger_root": str(value.ledger_root),
            "holdout_events_path": str(value.ledger_root / "holdout" / "events.jsonl"),
        },
        "fixed_authorization_path": str(value.file_root / f"{cid}.authorization.json"),
        "provider_manifest_sha256": provider,
        "provider_manifest_contract_version": PROVIDER_MANIFEST_CONTRACT,
        "code_sha256_by_path": {
            "app/learn/hybrid/benchmark_v2_predictions.py": "3" * 64,
            "app/learn/hybrid/benchmark_scorer_v2.py": "4" * 64,
        },
        "config_sha256_by_path": {
            "configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json": "5" * 64,
            "configs/benchmarks/portfolio_hybrid_v1_1_gate.v2.json": "6" * 64,
        },
        "profile_sha256_by_id": {"portfolio_hybrid_v1_1_default": "7" * 64},
        "arm_order": list(EXACT_ARM_ORDER),
        "exact_holdout_command": list(EXACT_HOLDOUT_COMMAND),
        "exact_run_order": list(EXACT_RUN_ORDER),
        "absolute_owner_journal_root": str(value.owner_journal_root),
    }


def prepared(value, provider: str = "1" * 64) -> dict[str, object]:
    payload = authorization(value, provider)
    durable._publish_authorization_for_test(
        backend=value,
        authorization=payload,
        external_ref_path=_authorization_output_path(value),
    )
    return payload


def _registry_leaf_exists(value) -> bool:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            value.registry_root + "\\" + claim_id(IDENTITY),
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
    except FileNotFoundError:
        return False
    else:
        winreg.CloseKey(key)
        return True


def _registry_uuid_exists(value) -> bool:
    uuid_root = "\\".join(value.registry_root.split("\\")[:-1])
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            uuid_root,
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
    except FileNotFoundError:
        return False
    else:
        winreg.CloseKey(key)
        return True


def cleanup(value) -> None:
    cid = claim_id(IDENTITY)
    errors: list[Exception] = []
    try:
        winreg.DeleteKeyEx(
            winreg.HKEY_CURRENT_USER,
            value.registry_root + "\\" + cid,
            winreg.KEY_WOW64_64KEY,
            0,
        )
    except FileNotFoundError:
        pass
    except OSError as error:
        errors.append(error)
    parts = value.registry_root.split("\\")
    for length in range(len(parts), 4, -1):
        try:
            winreg.DeleteKeyEx(
                winreg.HKEY_CURRENT_USER,
                "\\".join(parts[:length]),
                winreg.KEY_WOW64_64KEY,
                0,
            )
        except FileNotFoundError:
            pass
        except OSError as error:
            errors.append(error)
    base = value.file_root.parent
    if base.exists():
        for path in base.rglob("*"):
            try:
                path.chmod(stat.S_IWRITE)
            except OSError:
                pass
        try:
            shutil.rmtree(base)
        except OSError as error:
            errors.append(error)
    if base.exists():
        errors.append(AssertionError(f"test file root remains: {base}"))
    if _registry_leaf_exists(value):
        errors.append(AssertionError("test claim registry leaf remains"))
    if _registry_uuid_exists(value):
        errors.append(AssertionError("test UUID registry root remains"))
    if errors:
        raise ExceptionGroup("test backend cleanup failed", errors)


@pytest.fixture
def test_backend(tmp_path: Path):
    value = backend(tmp_path)
    assert value.file_root != PRODUCTION_FILE_ROOT
    assert value.registry_root != PRODUCTION_REGISTRY_ROOT
    try:
        yield value
    finally:
        cleanup(value)


def test_two_layer_hashes_have_no_self_reference_and_stable_identity(test_backend) -> None:
    payload = authorization(test_backend)
    wrapped, digest = authorization_envelope(payload)
    assert "envelope_sha256" not in wrapped
    assert wrapped["payload_sha256"] == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert digest == hashlib.sha256(canonical_bytes(wrapped)).hexdigest()
    changed = deepcopy(payload)
    changed["provider_manifest_sha256"] = "9" * 64
    assert claim_id(changed["claim_identity"]) == claim_id(payload["claim_identity"])
    assert authorization_envelope(changed)[1] != digest


def test_authorization_hash_is_calculable_before_genesis(test_backend) -> None:
    payload = authorization(test_backend)
    assert set(payload["ledger_identity"]) == {
        "absolute_ledger_root",
        "holdout_events_path",
    }
    assert not (test_backend.ledger_root / "holdout" / "events.jsonl").exists()
    wrapped, digest = authorization_envelope(payload)
    assert wrapped["payload"] == payload
    assert wrapped["payload_sha256"] == hashlib.sha256(canonical_bytes(payload)).hexdigest()
    assert digest == hashlib.sha256(canonical_bytes(wrapped)).hexdigest()
    assert "payload_sha256" not in payload
    assert "envelope_sha256" not in wrapped
    assert not (test_backend.ledger_root / "holdout" / "events.jsonl").exists()


def test_genesis_is_derived_from_external_authorization_ref(tmp_path: Path) -> None:
    generated = []
    for provider_digest in ("1" * 64, "9" * 64):
        value = backend(tmp_path)
        payload = authorization(value, provider_digest)
        wrapped, digest = authorization_envelope(payload)
        ref = durable._authorization_ref(value, wrapped, digest)
        genesis = _authorize_holdout_genesis_for_test(
            backend=value,
            claim_identity=IDENTITY,
            authorization_ref=ref,
        )
        event = genesis["event"]
        assert event["event_payload"]["authorization_ref"] == ref
        assert genesis["event_sha256"] == hashlib.sha256(
            canonical_bytes(event)
        ).hexdigest()
        assert hashlib.sha256(canonical_bytes(genesis)).hexdigest() == hashlib.sha256(
            canonical_bytes(_chain(value.ledger_root / "holdout/events.jsonl")[0])
        ).hexdigest()
        assert "event_sha256" not in event
        generated.append((ref, genesis, claim_id(payload["claim_identity"])))
    assert generated[0][0] != generated[1][0]
    assert generated[0][1] != generated[1][1]
    assert generated[0][2] == generated[1][2] == claim_id(IDENTITY)


def test_authorization_uses_shared_provider_manifest_v2_1(tmp_path: Path) -> None:
    value = backend(tmp_path)
    payload = authorization(value)
    payload["provider_manifest_contract_version"] = PROVIDER_MANIFEST_CONTRACT
    _validate_authorization_for_backend(value, payload)

    stale = deepcopy(payload)
    stale["provider_manifest_contract_version"] = (
        "portfolio_hybrid_benchmark_v2_provider_manifest_v1"
    )
    with pytest.raises(ValueError, match="provider contract"):
        _claim_with_backend_for_test(backend=value, authorization=stale)
    assert not value.file_root.parent.exists()
    assert not value.ledger_root.exists()
    assert not _registry_leaf_exists(value)


def test_production_backend_splits_claim_anchors_from_repo_ledger(
    tmp_path: Path,
) -> None:
    production = durable._production_backend()
    project_root = Path(__file__).resolve().parents[1]
    expected_ledger = (
        project_root
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "benchmark-v2-ledger"
    ).resolve()
    assert durable.PRODUCTION_LEDGER_ROOT == expected_ledger
    assert production.file_root == PRODUCTION_FILE_ROOT
    assert production.registry_root == PRODUCTION_REGISTRY_ROOT
    assert production.ledger_root == expected_ledger
    assert production.owner_journal_root == (PRODUCTION_FILE_ROOT / "owner").resolve()

    value = backend(tmp_path)
    test_roots = (value.file_root, value.ledger_root, value.owner_journal_root)
    production_roots = (
        production.file_root,
        production.ledger_root,
        production.owner_journal_root,
    )
    assert not any(
        durable._overlaps(test_root, production_root)
        for test_root in test_roots
        for production_root in production_roots
    )
    assert not durable._registry_overlaps(
        value.registry_root, production.registry_root
    )


def test_genesis_ref_uses_explicit_claim_and_ledger_roots(test_backend) -> None:
    cid = claim_id(IDENTITY)
    ref = {
        "authorization_id": f"holdout-authorization/{cid}",
        "envelope_sha256": "1" * 64,
        "fixed_authorization_path": str(
            test_backend.file_root / f"{cid}.authorization.json"
        ),
    }
    holdout._validate_genesis_ref(
        file_root=test_backend.file_root,
        ledger_root=test_backend.ledger_root,
        authorization_ref=ref,
    )
    inferred_ref = {
        **ref,
        "fixed_authorization_path": str(
            test_backend.ledger_root.parent / "Claims" / f"{cid}.authorization.json"
        ),
    }
    explicit_file_root = test_backend.file_root.parent / "ExplicitClaims"
    with pytest.raises(ValueError, match="authorization ref"):
        holdout._validate_genesis_ref(
            file_root=explicit_file_root,
            ledger_root=test_backend.ledger_root,
            authorization_ref=inferred_ref,
        )
    assert not test_backend.file_root.parent.exists()


def test_production_holdout_rejects_alternate_ledger_identity(
    tmp_path: Path, monkeypatch
) -> None:
    expected = durable.PRODUCTION_LEDGER_ROOT
    alias = tmp_path / "project-alias"
    junction = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(durable.PROJECT_ROOT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert junction.returncode == 0, junction.stderr.decode(errors="replace")
    reparse_alias = (
        alias
        / "runtime_state"
        / "portfolio-hybrid-v1-1"
        / "benchmark-v2-ledger"
    )
    lexical_alias = expected / ".." / expected.name
    sibling = expected.parent / "benchmark-v2-ledger-sibling"
    wrong_cwd = Path("runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        holdout,
        "_authorize_holdout_genesis",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("ledger side effect reached")
        ),
    )
    before = expected.exists()
    ref = {
        "authorization_id": f"holdout-authorization/{claim_id(IDENTITY)}",
        "envelope_sha256": "1" * 64,
        "fixed_authorization_path": str(
            PRODUCTION_FILE_ROOT / f"{claim_id(IDENTITY)}.authorization.json"
        ),
    }
    try:
        for candidate in (sibling, lexical_alias, reparse_alias, wrong_cwd):
            with pytest.raises(ValueError, match="production holdout ledger root"):
                holdout.authorize_holdout_genesis(
                    ledger_root=candidate,
                    claim_identity=IDENTITY,
                    authorization_ref=ref,
                )
        assert expected.exists() is before
    finally:
        os.rmdir(alias)


def test_production_genesis_requires_exact_authorization_object(
    tmp_path: Path, monkeypatch
) -> None:
    value = backend(tmp_path)
    payload = authorization(value)
    wrapped, digest = authorization_envelope(payload)
    ref = durable._authorization_ref(value, wrapped, digest)
    monkeypatch.setattr(holdout, "_production_backend", lambda: value)
    monkeypatch.setattr(holdout, "_production_ledger_root_is_exact", lambda _path: True)
    monkeypatch.setattr(
        holdout,
        "_authorize_holdout_genesis",
        lambda **_kwargs: {"verified": True},
    )
    try:
        with pytest.raises(ValueError, match="authorization object"):
            holdout.authorize_holdout_genesis(
                ledger_root=value.ledger_root,
                claim_identity=IDENTITY,
                authorization_ref=ref,
            )
        assert not value.file_root.parent.exists()
        durable._create_authorization(value, wrapped, digest, test_control=None)
        assert holdout.authorize_holdout_genesis(
            ledger_root=value.ledger_root,
            claim_identity=IDENTITY,
            authorization_ref=ref,
        ) == {"verified": True}
    finally:
        cleanup(value)


def test_full_exact_holdout_argv_is_frozen(tmp_path: Path) -> None:
    expected = (
        "uv",
        "run",
        "python",
        "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
        "--provider-manifest",
        "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json",
        "--partition",
        "holdout",
        "--actual-models",
        "--holdout-authorization",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json",
        "--ledger-root",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
        "--output-root",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout",
    )
    assert EXACT_HOLDOUT_COMMAND == expected
    mutations = [
        expected[:-1],
        expected + ("--extra",),
        expected[:4] + (expected[5], expected[4]) + expected[6:],
        expected[:5] + ("other-provider-manifest.json",) + expected[6:],
        expected[:10] + ("other-authorization.json",) + expected[11:],
        expected[:12] + ("other-ledger",) + expected[13:],
        expected[:14] + ("other-output",),
    ]
    frozen_claim_id = claim_id(IDENTITY)
    for command in mutations:
        value = backend(tmp_path)
        payload = authorization(value)
        payload["exact_holdout_command"] = list(command)
        assert claim_id(payload["claim_identity"]) == frozen_claim_id
        with pytest.raises(ValueError, match="authorization command"):
            _claim_with_backend_for_test(backend=value, authorization=payload)
        assert not value.file_root.parent.exists()
        assert not value.ledger_root.exists()
        assert not _registry_leaf_exists(value)


def _authorization_mutations(value):
    def mutate(path: tuple[str, ...], replacement: object):
        payload = authorization(value)
        parent = payload
        for item in path[:-1]:
            parent = parent[item]  # type: ignore[index]
        parent[path[-1]] = replacement  # type: ignore[index]
        return payload

    return [
        mutate(("contract_version",), "wrong"),
        mutate(("claim_identity",), {"partition": "holdout"}),
        mutate(("claim_id",), "0" * 64),
        mutate(("ledger_identity",), {"absolute_ledger_root": str(value.ledger_root)}),
        mutate(("ledger_identity", "absolute_ledger_root"), "relative"),
        mutate(("ledger_identity", "absolute_ledger_root"), str(value.ledger_root / "other")),
        mutate(("ledger_identity", "holdout_events_path"), str(value.ledger_root / "wrong.jsonl")),
        mutate(("fixed_authorization_path",), str(value.file_root / "wrong.json")),
        mutate(("provider_manifest_sha256",), "not-sha"),
        mutate(("provider_manifest_contract_version",), "provider_manifest_v2"),
        mutate(("code_sha256_by_path",), {}),
        mutate(("code_sha256_by_path",), {str(value.file_root / "code.py"): "3" * 64}),
        mutate(("code_sha256_by_path",), {"code.py": "not-sha"}),
        mutate(("config_sha256_by_path",), {"estimand.json": 7}),
        mutate(("profile_sha256_by_id",), {"": "7" * 64}),
        mutate(("arm_order",), list(reversed(EXACT_ARM_ORDER))),
        mutate(("exact_holdout_command",), ["python", "runner.py"]),
        mutate(("exact_run_order",), ["sealed-holdout", "sealed-regression"]),
        mutate(("absolute_owner_journal_root",), "relative"),
        mutate(("absolute_owner_journal_root",), str(value.owner_journal_root / "wrong")),
    ]


@pytest.mark.parametrize("index", range(20))
def test_each_authorization_mutation_fails_before_files_or_registry(tmp_path: Path, index: int) -> None:
    value = backend(tmp_path)
    payload = _authorization_mutations(value)[index]
    with pytest.raises(ValueError, match="authorization"):
        _claim_with_backend_for_test(backend=value, authorization=payload)
    assert not value.file_root.parent.exists()
    assert not _registry_leaf_exists(value)


def test_authorization_path_binding_does_not_query_mutable_filesystem(
    test_backend, monkeypatch
) -> None:
    payload = authorization(test_backend)

    def forbidden_resolve(*_args, **_kwargs):
        raise AssertionError("authorization path binding must be lexical")

    monkeypatch.setattr(Path, "resolve", forbidden_resolve)
    _validate_authorization_for_backend(test_backend, payload)


def test_partition_ledgers_are_independent_and_holdout_genesis_is_immutable(test_backend) -> None:
    root = test_backend.ledger_root
    regression = {
        "partition": "regression",
        "sequence": 0,
        "event_type": "authorized_genesis",
        "previous_envelope_sha256": "0" * 64,
        "event_payload": {"release": RELEASE},
    }
    _append_regression_event_for_test(backend=test_backend, event=regression)
    payload = authorization(test_backend)
    _, digest = authorization_envelope(payload)
    ref = {
        "authorization_id": f"holdout-authorization/{claim_id(IDENTITY)}",
        "envelope_sha256": digest,
        "fixed_authorization_path": payload["fixed_authorization_path"],
    }
    genesis = _authorize_holdout_genesis_for_test(
        backend=test_backend, claim_identity=IDENTITY, authorization_ref=ref
    )
    assert (root / "regression/events.jsonl").read_bytes() != (
        root / "holdout/events.jsonl"
    ).read_bytes()
    assert _authorize_holdout_genesis_for_test(
        backend=test_backend, claim_identity=IDENTITY, authorization_ref=ref
    ) == genesis
    with pytest.raises(ValueError):
        _authorize_holdout_genesis_for_test(
            backend=test_backend,
            claim_identity=IDENTITY,
            authorization_ref={**ref, "envelope_sha256": "8" * 64},
        )


def _authorization_output_path(value) -> Path:
    return value.file_root.parent / "AuthorizationRef" / "holdout-authorization.json"


def test_authorization_publication_resumes_only_exact_prefix(tmp_path: Path) -> None:
    for prefix in ("empty", "authorization", "authorization_genesis"):
        value = backend(tmp_path)
        payload = authorization(value)
        wrapped, digest = authorization_envelope(payload)
        ref = durable._authorization_ref(value, wrapped, digest)
        output_path = _authorization_output_path(value)
        try:
            if prefix in {"authorization", "authorization_genesis"}:
                durable._create_authorization(
                    value, wrapped, digest, test_control=None
                )
            if prefix == "authorization_genesis":
                _authorize_holdout_genesis_for_test(
                    backend=value,
                    claim_identity=IDENTITY,
                    authorization_ref=ref,
                )
            published = durable._publish_authorization_for_test(
                backend=value,
                authorization=payload,
                external_ref_path=output_path,
            )
            assert published == ref
            assert output_path.read_bytes() == canonical_bytes(ref)
            assert Path(ref["fixed_authorization_path"]).read_bytes() == canonical_bytes(
                wrapped
            )
            chain = _chain(value.ledger_root / "holdout" / "events.jsonl")
            assert len(chain) == 1
            assert chain[0]["event"]["event_type"] == "authorized_genesis"
            assert chain[0]["event"]["event_payload"] == {
                "claim_id": claim_id(IDENTITY),
                "authorization_ref": ref,
                "safety": durable.SAFETY,
            }
            assert not list(value.file_root.glob(f"{claim_id(IDENTITY)}--*.claim"))
            assert not _registry_leaf_exists(value)
            with pytest.raises(ValueError, match="permanent_refusal"):
                durable._publish_authorization_for_test(
                    backend=value,
                    authorization=payload,
                    external_ref_path=output_path,
                )
        finally:
            cleanup(value)


def test_genesis_without_authorization_is_not_a_resumable_prefix(
    tmp_path: Path,
) -> None:
    value = backend(tmp_path)
    payload = authorization(value)
    wrapped, digest = authorization_envelope(payload)
    ref = durable._authorization_ref(value, wrapped, digest)
    output_path = _authorization_output_path(value)
    try:
        _authorize_holdout_genesis_for_test(
            backend=value,
            claim_identity=IDENTITY,
            authorization_ref=ref,
        )
        authorization_path = Path(ref["fixed_authorization_path"])
        ledger_path = value.ledger_root / "holdout/events.jsonl"
        before = {
            str(path.relative_to(value.file_root.parent)): path.read_bytes()
            for path in value.file_root.parent.rglob("*")
            if path.is_file()
        }
        assert before == {"Ledger\\holdout\\events.jsonl": ledger_path.read_bytes()}
        assert not authorization_path.exists()
        assert not output_path.exists()

        with pytest.raises(
            ValueError, match="permanent_refusal: genesis without authorization"
        ):
            durable._publish_authorization_for_test(
                backend=value,
                authorization=payload,
                external_ref_path=output_path,
            )

        after = {
            str(path.relative_to(value.file_root.parent)): path.read_bytes()
            for path in value.file_root.parent.rglob("*")
            if path.is_file()
        }
        assert after == before
        assert not authorization_path.exists()
        assert not output_path.exists()
        assert _chain(ledger_path)[0]["event"]["event_payload"][
            "authorization_ref"
        ] == ref
    finally:
        cleanup(value)


def test_authorization_publication_refuses_mismatched_prefixes(tmp_path: Path) -> None:
    cases = (
        "preexisting_event",
        "authorization_bytes",
        "genesis",
        "extra_event",
        "claim_anchor",
        "registry_anchor",
    )
    for case in cases:
        value = backend(tmp_path)
        payload = authorization(value)
        wrapped, digest = authorization_envelope(payload)
        ref = durable._authorization_ref(value, wrapped, digest)
        output_path = _authorization_output_path(value)
        try:
            if case == "preexisting_event":
                _append_for_test(
                    value.ledger_root / "holdout/events.jsonl",
                    {
                        "partition": "holdout",
                        "sequence": 0,
                        "event_type": "claim_consumed",
                        "previous_envelope_sha256": "0" * 64,
                        "event_payload": {"unexpected": True},
                    },
                )
            else:
                durable._create_authorization(
                    value, wrapped, digest, test_control=None
                )
            if case == "authorization_bytes":
                path = Path(ref["fixed_authorization_path"])
                path.chmod(stat.S_IWRITE)
                path.write_bytes(canonical_bytes(wrapped) + b" ")
            elif case == "genesis":
                _authorize_holdout_genesis_for_test(
                    backend=value,
                    claim_identity=IDENTITY,
                    authorization_ref={**ref, "envelope_sha256": "9" * 64},
                )
            elif case == "extra_event":
                _authorize_holdout_genesis_for_test(
                    backend=value,
                    claim_identity=IDENTITY,
                    authorization_ref=ref,
                )
                chain = _chain(value.ledger_root / "holdout/events.jsonl")
                _append_for_test(
                    value.ledger_root / "holdout/events.jsonl",
                    {
                        "partition": "holdout",
                        "sequence": 1,
                        "event_type": "claim_consumed",
                        "previous_envelope_sha256": hashlib.sha256(
                            canonical_bytes(chain[0])
                        ).hexdigest(),
                        "event_payload": {"unexpected": True},
                    },
                )
            elif case == "claim_anchor":
                value.file_root.mkdir(parents=True, exist_ok=True)
                (value.file_root / f"{claim_id(IDENTITY)}--{'9' * 64}.claim").touch()
            else:
                _, _, _, _, expected = _expected_claim_values(value, payload)
                _registry_create(value, claim_id(IDENTITY), expected, None)
            with pytest.raises(ValueError, match="permanent_refusal"):
                durable._publish_authorization_for_test(
                    backend=value,
                    authorization=payload,
                    external_ref_path=output_path,
                )
            assert not output_path.exists()
            if case == "preexisting_event":
                assert not Path(ref["fixed_authorization_path"]).exists()
        finally:
            cleanup(value)


def test_claim_requires_previously_published_authorization(tmp_path: Path) -> None:
    value = backend(tmp_path)
    payload = authorization(value)
    with pytest.raises(ValueError, match="permanent_refusal"):
        _claim_with_backend_for_test(backend=value, authorization=payload)
    assert not value.file_root.parent.exists()
    assert not value.ledger_root.exists()
    assert not _registry_leaf_exists(value)


def test_regression_events_do_not_consume_holdout(tmp_path: Path) -> None:
    value = backend(tmp_path)
    try:
        previous = "0" * 64
        for sequence, event_type in enumerate(
            ("authorized_genesis", "regression_attempt", "cleanup")
        ):
            event = {
                "partition": "regression",
                "sequence": sequence,
                "event_type": event_type,
                "previous_envelope_sha256": previous,
                "event_payload": {"sequence": sequence},
            }
            wrapped = _append_regression_event_for_test(backend=value, event=event)
            previous = hashlib.sha256(canonical_bytes(wrapped)).hexdigest()
        payload = authorization(value)
        durable._publish_authorization_for_test(
            backend=value,
            authorization=payload,
            external_ref_path=_authorization_output_path(value),
        )
        assert len(_chain(value.ledger_root / "regression/events.jsonl")) == 3
        holdout_chain = _chain(value.ledger_root / "holdout/events.jsonl")
        assert [item["event"]["event_type"] for item in holdout_chain] == [
            "authorized_genesis"
        ]
        assert not list(value.file_root.glob(f"{claim_id(IDENTITY)}--*.claim"))
        assert not _registry_leaf_exists(value)
    finally:
        cleanup(value)


def _write_request(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def _wait_for(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(path)
        time.sleep(0.01)


def _child_backend(document: dict[str, object]):
    spec = document["backend"]
    return _test_backend(
        file_root=Path(spec["file_root"]),
        registry_root=str(spec["registry_root"]),
        ledger_root=Path(spec["ledger_root"]),
        capability=str(spec["capability"]),
    )


def _child_entry(request_path: Path, result_path: Path) -> int:
    request = json.loads(request_path.read_text(encoding="utf-8"))
    identity_path = Path(request["identity_path"])
    _wait_for(identity_path)
    expected_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    import psutil

    actual_identity = {
        "pid": os.getpid(),
        "create_time_ns": int(round(psutil.Process().create_time() * 1_000_000_000)),
    }
    if actual_identity != expected_identity:
        sys.stderr.write(json.dumps({"actual": actual_identity, "expected": expected_identity}))
        return 61
    scope = WindowsProcessScope(str(request["scope_name"]), create=False)
    try:
        if os.getpid() not in scope.pids():
            return 62
    finally:
        scope.close()
    if request["mode"] == "early_exit":
        return 64
    if request["mode"] == "never_ready":
        time.sleep(60)
        return 65
    Path(request["ready_path"]).write_text("ready", encoding="utf-8")
    _wait_for(Path(request["start_path"]))
    try:
        if request["mode"] == "claim":
            result = _claim_with_backend_for_test(
                backend=_child_backend(request),
                authorization=request["authorization"],
                failpoint=request.get("failpoint"),
                test_control=request.get("test_control"),
            )
        elif request["mode"] == "append":
            result = _append_for_test(
                Path(request["ledger_path"]),
                request["event"],
                failpoint=request.get("failpoint"),
            )
        elif request["mode"] == "genesis":
            result = _authorize_holdout_genesis_for_test(
                backend=_child_backend(request),
                claim_identity=IDENTITY,
                authorization_ref=request["authorization_ref"],
            )
        elif request["mode"] == "authorize":
            result = durable._publish_authorization_for_test(
                backend=_child_backend(request),
                authorization=request["authorization"],
                external_ref_path=Path(request["external_ref_path"]),
                test_control=request.get("test_control"),
            )
        elif request["mode"] == "recover":
            result = _recover_with_backend_for_test(
                backend=_child_backend(request),
                authorization=request["authorization"],
            )
        else:
            return 63
    except Exception as error:
        result = {"error_type": type(error).__name__, "details": str(error)}
    result_path.write_bytes(canonical_bytes({"job_receipt": actual_identity, "result": result}))
    return 0


def _scope_name() -> str:
    return "Local\\AgentGuiHybrid-vista-" + uuid.uuid4().hex.ljust(64, "0")


def _cleanup_spawned_process(process) -> None:
    errors: list[BaseException] = []
    try:
        if process.poll() is None:
            process.kill()
    except BaseException as error:
        errors.append(error)
    try:
        process.wait(10)
    except BaseException as error:
        errors.append(error)
    try:
        process.close()
    except BaseException as error:
        errors.append(error)
    if errors:
        raise BaseExceptionGroup("spawned process cleanup failed", errors)


def _launch(
    scope_name: str,
    work: Path,
    value,
    payload,
    *,
    owned_processes,
    mode="claim",
    failpoint=None,
    test_control=None,
    event=None,
    authorization_ref=None,
    harness_failpoint=None,
):
    token = uuid.uuid4().hex
    request = work / f"{token}.request.json"
    result = work / f"{token}.result.json"
    identity = work / f"{token}.identity.json"
    ready = work / f"{token}.ready"
    start = work / f"{token}.start"
    stderr_path = work / f"{token}.stderr.txt"
    child_mode = (
        "early_exit"
        if harness_failpoint in {"early_exit", "stderr_read"}
        else "never_ready" if harness_failpoint == "ready_timeout" else mode
    )
    document = {
        "mode": child_mode,
        "backend": {
            "file_root": str(value.file_root),
            "registry_root": value.registry_root,
            "ledger_root": str(value.ledger_root),
            "capability": value.test_capability,
        },
        "authorization": payload,
        "scope_name": scope_name,
        "identity_path": str(identity),
        "ready_path": str(ready),
        "start_path": str(start),
        "failpoint": failpoint,
        "test_control": test_control,
        "ledger_path": str(value.ledger_root / "regression/events.jsonl"),
        "event": event,
        "authorization_ref": authorization_ref,
        "external_ref_path": str(_authorization_output_path(value)),
    }
    _write_request(request, document)
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(Path.cwd() / ".venv" / "Lib" / "site-packages"), str(Path.cwd())]
    )
    process = None
    registered = False
    try:
        with stderr_path.open("wb") as stderr_stream:
            process = spawn_process_in_scope(
                [sys._base_executable, str(Path(__file__).resolve()), "--holdout-child", str(request), str(result)],
                scope_name=scope_name,
                cwd=Path.cwd(),
                env=child_env,
                stderr=stderr_stream,
                creationflags=0x08000000,
            )
            owned_processes.append(process)
            registered = True
        if harness_failpoint == "identity_write":
            raise OSError(5, "injected identity publication failure")
        _write_request(identity, process.process_identity)
        deadline = time.monotonic() + (0.15 if harness_failpoint == "ready_timeout" else 20)
        while not ready.exists():
            code = process.poll()
            if code is not None:
                if harness_failpoint == "stderr_read":
                    raise OSError(5, "injected stderr read failure")
                details = stderr_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"child exited before ready: {code}: {details}")
            if time.monotonic() >= deadline:
                raise TimeoutError(ready)
            time.sleep(0.01)
    except BaseException as primary:
        cleanup_error = None
        if process is not None:
            try:
                _cleanup_spawned_process(process)
            except BaseException as error:
                cleanup_error = error
            finally:
                if registered and process in owned_processes:
                    owned_processes.remove(process)
        if cleanup_error is not None:
            raise BaseExceptionGroup(
                "launch and cleanup failed", [primary, cleanup_error]
            )
        raise
    assert process is not None
    return process, start, result


def _finish_scope(scope, name: str, processes) -> dict[str, object]:
    errors: list[BaseException] = []
    receipt = None
    try:
        for process in list(processes):
            try:
                _cleanup_spawned_process(process)
            except BaseException as error:
                errors.append(error)
            finally:
                if process in processes:
                    processes.remove(process)
        try:
            receipt = observe_process_scope_cleanup(
                name, terminate=False, stable_zero_observations=3
            )
        except BaseException as error:
            errors.append(error)
    finally:
        try:
            scope.close()
        except BaseException as error:
            errors.append(error)
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise BaseExceptionGroup("process scope cleanup failed", errors)
    assert receipt is not None
    assert receipt["cleanup_status"] == "verified"
    assert receipt["member_pids_after"] == []
    return receipt


@pytest.mark.parametrize(
    "harness_failpoint", ["identity_write", "early_exit", "ready_timeout", "stderr_read"]
)
def test_launch_pre_return_failures_close_process_and_job_members(
    tmp_path: Path, harness_failpoint: str
) -> None:
    value = backend(tmp_path)
    work = tmp_path / f"launch-{harness_failpoint}"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        with pytest.raises((OSError, RuntimeError, TimeoutError, AssertionError)):
            _launch(
                name,
                work,
                value,
                authorization(value),
                owned_processes=processes,
                harness_failpoint=harness_failpoint,
            )
        assert processes == []
        receipt = _finish_scope(scope, name, processes)
        assert receipt["cleanup_status"] == "verified"
    finally:
        if not getattr(scope, "_closed", True):
            scope.close()
        cleanup(value)


def test_finish_scope_closes_job_even_when_observation_raises(monkeypatch) -> None:
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    monkeypatch.setattr(
        sys.modules[__name__],
        "observe_process_scope_cleanup",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("observe failed")),
    )
    try:
        with pytest.raises(RuntimeError, match="observe failed"):
            _finish_scope(scope, name, [])
        assert scope._closed is True
    finally:
        if not scope._closed:
            scope.close()


def test_authorization_publication_waits_past_create_before_write(test_backend, tmp_path: Path) -> None:
    payload = authorization(test_backend)
    work = tmp_path / "processes"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    marker = work / "authorization-created"
    release = work / "authorization-release"
    try:
        creator, creator_start, creator_result = _launch(
            name,
            work,
            test_backend,
            payload,
            owned_processes=processes,
            mode="authorize",
            test_control={
                "pause_after_authorization_create": {
                    "ready_path": str(marker),
                    "release_path": str(release),
                }
            },
        )
        creator_start.write_text("start", encoding="utf-8")
        _wait_for(marker)
        loser, loser_start, loser_result = _launch(
            name,
            work,
            test_backend,
            payload,
            owned_processes=processes,
            mode="authorize",
        )
        loser_start.write_text("start", encoding="utf-8")
        time.sleep(0.15)
        assert not loser_result.exists()
        release.write_text("release", encoding="utf-8")
        _wait_for(creator_result)
        _wait_for(loser_result)
        results = [
            json.loads(path.read_text(encoding="utf-8"))["result"]
            for path in (creator_result, loser_result)
        ]
        assert sum("error_type" not in item for item in results) == 1
        assert any("already published" in item.get("details", "") for item in results)
        assert Path(payload["fixed_authorization_path"]).read_bytes() == canonical_bytes(
            authorization_envelope(payload)[0]
        )
        assert _authorization_output_path(test_backend).read_bytes() == canonical_bytes(
            durable._authorization_ref(
                test_backend,
                *authorization_envelope(payload),
            )
        )
    finally:
        _finish_scope(scope, name, processes)


def test_two_job_contained_processes_have_one_winner_and_same_attempt(test_backend, tmp_path: Path) -> None:
    payload = prepared(test_backend)
    work = tmp_path / "race"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        launched = [
            _launch(
                name, work, test_backend, payload, owned_processes=processes
            )
            for _ in range(2)
        ]
        identities = [process.process_identity for process in processes]
        assert len({(item["pid"], item["create_time_ns"]) for item in identities}) == 2
        for _, start, _ in launched:
            start.write_text("start", encoding="utf-8")
        for _, _, result in launched:
            _wait_for(result)
        documents = [json.loads(item[2].read_text(encoding="utf-8")) for item in launched]
        assert [item["job_receipt"] for item in documents] == identities
        results = [item["result"] for item in documents]
        assert all("newly_created" in item for item in results), results
        assert sum(item["newly_created"] for item in results) == 1
        assert len({item["attempt_id"] for item in results}) == 1
        assert _recover_with_backend_for_test(
            backend=test_backend, authorization=payload
        )["state"] == "consumed"
    finally:
        _finish_scope(scope, name, processes)


@pytest.mark.parametrize(
    ("failpoint", "exit_code", "expected_state"),
    [
        ("sentinel_before_flush", 89, "consumed_incomplete"),
        ("sentinel_create", 90, "consumed_incomplete"),
        ("registry_create", 91, "permanent_refusal"),
        ("registry_record", 92, "permanent_refusal"),
        ("registry_flush", 93, "consumed"),
    ],
)
def test_each_crash_phase_has_exact_recovery_state_and_job_cleanup(
    tmp_path: Path, failpoint: str, exit_code: int, expected_state: str
) -> None:
    value = backend(tmp_path)
    payload = prepared(value)
    work = tmp_path / "crash"
    work.mkdir(exist_ok=True)
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        process, start, _ = _launch(
            name,
            work,
            value,
            payload,
            owned_processes=processes,
            failpoint=failpoint,
        )
        start.write_text("start", encoding="utf-8")
        assert process.wait(20) == exit_code
        recovered = _recover_with_backend_for_test(backend=value, authorization=payload)
        assert recovered["state"] == expected_state
        assert recovered["attempt_id"] == hashlib.sha256(
            (
                "benchmark-v2-holdout-attempt\0"
                + claim_id(IDENTITY)
                + "\0"
                + authorization_envelope(payload)[1]
            ).encode()
        ).hexdigest()
        sentinel = value.file_root / (
            f"{claim_id(IDENTITY)}--{authorization_envelope(payload)[1]}.claim"
        )
        assert sentinel.exists()
        if failpoint in {"sentinel_before_flush", "sentinel_create"}:
            assert not _registry_leaf_exists(value)
        else:
            assert _registry_leaf_exists(value)
    finally:
        _finish_scope(scope, name, processes)
        cleanup(value)


def test_concurrent_chain_append_has_no_sibling_records(test_backend, tmp_path: Path) -> None:
    event = {
        "partition": "regression",
        "sequence": 0,
        "event_type": "authorized_genesis",
        "previous_envelope_sha256": "0" * 64,
        "event_payload": {"release": RELEASE},
    }
    work = tmp_path / "ledger-race"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        launched = [
            _launch(
                name,
                work,
                test_backend,
                {},
                owned_processes=processes,
                mode="append",
                event=event,
            )
            for _ in range(2)
        ]
        for _, start, _ in launched:
            start.write_text("start", encoding="utf-8")
        for _, _, result in launched:
            _wait_for(result)
        results = [
            json.loads(item[2].read_text(encoding="utf-8"))["result"]
            for item in launched
        ]
        assert sum("error_type" not in item for item in results) == 1
        assert len(_chain(test_backend.ledger_root / "regression/events.jsonl")) == 1
    finally:
        _finish_scope(scope, name, processes)


def test_concurrent_holdout_genesis_has_one_exact_record(test_backend, tmp_path: Path) -> None:
    payload = authorization(test_backend)
    _, digest = authorization_envelope(payload)
    ref = {
        "authorization_id": f"holdout-authorization/{claim_id(IDENTITY)}",
        "envelope_sha256": digest,
        "fixed_authorization_path": payload["fixed_authorization_path"],
    }
    work = tmp_path / "genesis-race"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        launched = [
            _launch(
                name,
                work,
                test_backend,
                payload,
                owned_processes=processes,
                mode="genesis",
                authorization_ref=ref,
            )
            for _ in range(2)
        ]
        for _, start, _ in launched:
            start.write_text("start", encoding="utf-8")
        for _, _, result in launched:
            _wait_for(result)
        results = [
            json.loads(item[2].read_text(encoding="utf-8"))["result"]
            for item in launched
        ]
        assert results[0] == results[1]
        assert len(_chain(test_backend.ledger_root / "holdout/events.jsonl")) == 1
    finally:
        _finish_scope(scope, name, processes)


def test_concurrent_recovery_mirrors_one_claim_record(test_backend, tmp_path: Path) -> None:
    payload = prepared(test_backend)
    _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    shutil.rmtree(test_backend.ledger_root)
    work = tmp_path / "recovery-race"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        launched = [
            _launch(
                name,
                work,
                test_backend,
                payload,
                owned_processes=processes,
                mode="recover",
            )
            for _ in range(2)
        ]
        for _, start, _ in launched:
            start.write_text("start", encoding="utf-8")
        for _, _, result in launched:
            _wait_for(result)
        results = [
            json.loads(item[2].read_text(encoding="utf-8"))["result"]
            for item in launched
        ]
        assert all(item.get("state") == "consumed" for item in results), results
        chain = _chain(test_backend.ledger_root / "holdout/events.jsonl")
        assert [item["event"]["event_type"] for item in chain] == [
            "authorized_genesis",
            "claim_consumed",
        ]
    finally:
        _finish_scope(scope, name, processes)


def test_crashed_partial_chain_never_allows_sibling_append(test_backend, tmp_path: Path) -> None:
    event = {
        "partition": "regression",
        "sequence": 0,
        "event_type": "authorized_genesis",
        "previous_envelope_sha256": "0" * 64,
        "event_payload": {"release": RELEASE},
    }
    work = tmp_path / "ledger-crash"
    work.mkdir()
    name = _scope_name()
    scope = WindowsProcessScope(name, create=True)
    processes = []
    try:
        process, start, _ = _launch(
            name,
            work,
            test_backend,
            {},
            owned_processes=processes,
            mode="append",
            event=event,
            failpoint="after_half_write",
        )
        start.write_text("start", encoding="utf-8")
        assert process.wait(20) == 94
        with pytest.raises((ValueError, json.JSONDecodeError)):
            _append_regression_event_for_test(backend=test_backend, event=event)
    finally:
        _finish_scope(scope, name, processes)


@pytest.mark.parametrize("lost", ["sentinel", "registry", "ledger_output"])
def test_anchor_or_audit_deletion_never_restores_fresh(test_backend, lost: str) -> None:
    payload = prepared(test_backend)
    result = _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    assert result["state"] == "consumed"
    sentinel = next(test_backend.file_root.glob("*.claim"))
    assert sentinel.name == (
        f"{claim_id(IDENTITY)}--{authorization_envelope(payload)[1]}.claim"
    )
    assert sentinel.stat().st_size == 0
    if lost == "sentinel":
        sentinel.chmod(stat.S_IWRITE)
        sentinel.unlink()
    elif lost == "registry":
        winreg.DeleteKeyEx(
            winreg.HKEY_CURRENT_USER,
            test_backend.registry_root + "\\" + claim_id(IDENTITY),
            winreg.KEY_WOW64_64KEY,
            0,
        )
    else:
        shutil.rmtree(test_backend.ledger_root, ignore_errors=True)
    expected = "consumed_incomplete" if lost != "ledger_output" else "consumed"
    assert _recover_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == expected


def test_anchor_attributes_are_load_bearing(test_backend) -> None:
    payload = prepared(test_backend)
    assert _claim_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "consumed"
    sentinel = next(test_backend.file_root.glob("*.claim"))
    sentinel.chmod(stat.S_IWRITE)
    assert _recover_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "permanent_refusal"


def test_reparse_sentinel_is_permanent_refusal(test_backend, tmp_path: Path) -> None:
    payload = prepared(test_backend)
    _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    sentinel = next(test_backend.file_root.glob("*.claim"))
    sentinel.chmod(stat.S_IWRITE)
    sentinel.unlink()
    target = tmp_path / "zero-target"
    target.write_bytes(b"")
    try:
        os.symlink(target, sentinel)
    except OSError:
        target.unlink()
        target.mkdir()
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(sentinel), str(target)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    try:
        assert _recover_with_backend_for_test(
            backend=test_backend, authorization=payload
        )["state"] == "permanent_refusal"
    finally:
        if sentinel.is_dir():
            os.rmdir(sentinel)


def test_file_dacl_mutation_is_permanent_refusal(test_backend) -> None:
    payload = prepared(test_backend)
    _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    sentinel = next(test_backend.file_root.glob("*.claim"))
    _set_file_dacl_for_test(sentinel, "D:P(A;;FA;;;WD)")
    assert _recover_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "permanent_refusal"


def test_registry_dacl_mutation_is_permanent_refusal(test_backend) -> None:
    payload = prepared(test_backend)
    _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    _set_registry_dacl_for_test(test_backend, claim_id(IDENTITY), "D:P(A;;KA;;;WD)")
    assert _recover_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "permanent_refusal"


def test_close_handle_failure_is_not_silently_accepted() -> None:
    class Kernel:
        @staticmethod
        def CloseHandle(handle):
            return False

    with pytest.raises(OSError, match="CloseHandle"):
        _close_handle_checked(Kernel(), 123)


def _handle_count() -> int:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    count = wintypes.DWORD()
    assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ctypes.byref(count))
    return int(count.value)


def test_authorization_and_sentinel_snapshot_create_error_before_security_cleanup(test_backend) -> None:
    payload = prepared(test_backend)
    first = _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    assert first["state"] == "consumed"
    replay = _claim_with_backend_for_test(
        backend=test_backend,
        authorization=payload,
        test_control={"security_clobber_last_error_for": "authorization"},
    )
    assert replay["state"] == "consumed"
    sentinel = next(test_backend.file_root.glob("*.claim"))
    assert _sentinel_create(
        sentinel,
        None,
        test_control={"security_clobber_last_error_for": "sentinel"},
    ) is False


@pytest.mark.parametrize("wrapper", ["authorization", "sentinel", "mutex", "registry"])
def test_actual_wrapper_closes_acquired_handle_before_security_cleanup_failure(
    test_backend, wrapper: str
) -> None:
    payload = authorization(test_backend)
    test_backend.file_root.mkdir(parents=True, exist_ok=True)
    before = _handle_count()
    control = {"security_cleanup_failure_for": wrapper}
    with pytest.raises(BaseExceptionGroup, match="wrapper cleanup"):
        if wrapper == "authorization":
            _write_secure_new_file(
                test_backend.file_root / "cleanup-auth.tmp",
                b"authorization",
                test_control=control,
            )
        elif wrapper == "sentinel":
            _sentinel_create(
                test_backend.file_root / "cleanup-sentinel.claim",
                None,
                test_control=control,
            )
        elif wrapper == "mutex":
            with _named_mutex(
                "Local\\AgentGuiBenchmarkV2-test-" + uuid.uuid4().hex,
                test_control=control,
            ):
                pass
        else:
            test_backend.file_root.mkdir(parents=True, exist_ok=True)
            _, _, _, _, values = _expected_claim_values(test_backend, payload)
            _registry_create(
                test_backend,
                claim_id(IDENTITY),
                values,
                None,
                test_control=control,
            )
    assert _handle_count() == before


def test_wrapper_aggregates_body_close_and_security_failures_without_leak(test_backend) -> None:
    test_backend.file_root.mkdir(parents=True, exist_ok=True)
    before = _handle_count()
    with pytest.raises(BaseExceptionGroup) as caught:
        _write_secure_new_file(
            test_backend.file_root / "aggregate-auth.tmp",
            b"body",
            test_control={
                "body_failure_for": "authorization",
                "close_failure_for": "authorization",
                "security_cleanup_failure_for": "authorization",
            },
        )
    flattened = str(caught.value)
    assert "wrapper cleanup failed" in flattened
    assert len(caught.value.exceptions) == 3
    assert _handle_count() == before


def test_test_backend_rejects_noncanonical_or_overlapping_roots(tmp_path: Path) -> None:
    token = uuid.uuid4().hex
    valid = backend(tmp_path)
    invalid = [
        (PRODUCTION_FILE_ROOT / "Tests" / token / "Claims", valid.registry_root, valid.ledger_root),
        (PRODUCTION_FILE_ROOT.parent, valid.registry_root, valid.ledger_root),
        (valid.file_root, PRODUCTION_REGISTRY_ROOT + rf"\Tests\{token}\Claims", valid.ledger_root),
        (valid.file_root, valid.registry_root, PRODUCTION_FILE_ROOT / "ledger" / token),
        (valid.file_root, valid.registry_root, valid.file_root),
        (tmp_path / "PortfolioHybridBenchmarkV2Tests" / token / "Claims", valid.registry_root, valid.ledger_root),
        (valid.file_root, valid.registry_root.swapcase(), valid.ledger_root),
    ]
    for file_root, registry_root, ledger_root in invalid:
        with pytest.raises(ValueError, match="test backend"):
            _test_backend(
                file_root=file_root,
                registry_root=registry_root,
                ledger_root=ledger_root,
                capability=token,
            )


def test_cleanup_rejects_extra_registry_residue_and_then_proves_uuid_absent(tmp_path: Path) -> None:
    value = backend(tmp_path)
    uuid_root = "\\".join(value.registry_root.split("\\")[:-1])
    extra = uuid_root + "\\Unexpected"
    key = winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        extra,
        0,
        winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY,
    )
    winreg.CloseKey(key)
    with pytest.raises(ExceptionGroup, match="cleanup failed"):
        cleanup(value)
    assert _registry_uuid_exists(value)
    winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, extra, winreg.KEY_WOW64_64KEY, 0)
    cleanup(value)
    assert not _registry_uuid_exists(value)


def test_private_backend_never_calls_production_backend(test_backend, monkeypatch) -> None:
    import app.learn.hybrid.benchmark_v2_durable_claim as durable

    monkeypatch.setattr(
        durable,
        "_production_backend",
        lambda: (_ for _ in ()).throw(AssertionError("production backend touched")),
    )
    payload = prepared(test_backend)
    assert _claim_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "consumed"


def test_provider_change_and_authorization_byte_drift_are_permanent(test_backend) -> None:
    payload = prepared(test_backend)
    first = _claim_with_backend_for_test(backend=test_backend, authorization=payload)
    assert first["newly_created"] is True
    with pytest.raises(ValueError, match="permanent_refusal"):
        _claim_with_backend_for_test(
            backend=test_backend,
            authorization=authorization(test_backend, "9" * 64),
        )
    auth = Path(payload["fixed_authorization_path"])
    auth.chmod(stat.S_IWRITE)
    auth.write_bytes(auth.read_bytes() + b" ")
    assert _recover_with_backend_for_test(
        backend=test_backend, authorization=payload
    )["state"] == "permanent_refusal"


def test_public_surface_has_no_reset_delete_override() -> None:
    import app.learn.hybrid.benchmark_v2_holdout as holdout

    assert set(holdout.__all__) == {
        "append_regression_event",
        "authorize_holdout_genesis",
        "claim_holdout_once",
        "recover_claim",
    }
    assert not any(
        token in name.casefold()
        for name in holdout.__all__
        for token in ("reset", "delete", "clear", "override")
    )


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--holdout-child":
    raise SystemExit(_child_entry(Path(sys.argv[2]), Path(sys.argv[3])))
