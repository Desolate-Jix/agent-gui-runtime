from __future__ import annotations

import ast
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Mapping

import pytest

from scripts import run_portfolio_hybrid_v1_1_benchmark_v2 as runner


ZERO = "0" * 64
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


def test_runner_cli_help_bootstraps_project_root_without_pythonpath() -> None:
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "scripts/run_portfolio_hybrid_v1_1_benchmark_v2.py",
            "--help",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Run Portfolio Hybrid v1.1 Benchmark-v2" in completed.stdout


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sealed(value: Mapping[str, object]) -> dict[str, object]:
    result = dict(value)
    result["content_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _probe_receipt(
    *,
    attempt_ref: Mapping[str, object],
    provider: str,
    probe_kind: str,
    cleanup_receipt: Mapping[str, object],
) -> dict[str, object]:
    return _sealed(
        {
            "contract_version": "benchmark_v2_lifecycle_probe_receipt_v2",
            "benchmark_release_id": runner.BENCHMARK_RELEASE_ID,
            "partition": "regression",
            "probe_id": f"probe/{provider}/{probe_kind}/{attempt_ref['content_sha256']}",
            "attempt_ref": dict(attempt_ref),
            "provider": {
                "provider_id": provider,
                "provider_revision": f"{provider}-revision-v1",
                "profile_id": f"{provider}-profile-v1",
                "profile_sha256": "5" * 64,
            },
            "probe_kind": probe_kind,
            "operation_ref": {"runtime_owned": "operation"},
            "request_in_flight_ref": {"runtime_owned": "request"},
            "trigger_observation": {"runtime_owned": "trigger"},
            "body_completion_observation": {"runtime_owned": "body"},
            "termination_observation": {"runtime_owned": "termination"},
            "stable_zero_observation": {"runtime_owned": "stable-zero"},
            "cleanup_receipt_ref": {
                "content_sha256": cleanup_receipt["content_sha256"]
            },
            "observer_identity": {"runtime_owned": "observer"},
            "status": "PASS",
            **SAFETY,
        }
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_chain(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _rewrite_chain(path: Path, values: list[dict[str, object]]) -> None:
    previous = ZERO
    encoded: list[bytes] = []
    for sequence, source in enumerate(values):
        envelope = deepcopy(source)
        event = envelope["event"]
        event["sequence"] = sequence
        event["previous_envelope_sha256"] = previous
        envelope["event_sha256"] = hashlib.sha256(_canonical(event)).hexdigest()
        raw = _canonical(envelope)
        encoded.append(raw)
        previous = hashlib.sha256(raw).hexdigest()
    path.write_bytes(b"\n".join(encoded) + b"\n")


def _pre_result_ref(raw_prefix: bytes, chain: list[dict[str, object]]) -> dict[str, object]:
    cleanup_envelope = chain[-2]
    return {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": "runner-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": cleanup_envelope["event"]["event_payload"]["attempt_ref"],
        "terminal_sequence": cleanup_envelope["event"]["sequence"],
        "terminal_envelope_sha256": hashlib.sha256(
            _canonical(cleanup_envelope)
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }


class _OwnedGroups:
    def __init__(self, groups: list[dict[str, object]]) -> None:
        self._groups = groups
        self.closed = False

    def __enter__(self) -> "_OwnedGroups":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.closed = True

    def __iter__(self):
        return iter(self._groups)

    def close(self) -> None:
        self.closed = True


class _DeterministicRuntime:
    def __init__(
        self,
        *,
        fail_actual: bool = False,
        group_variant: str = "exact",
        cleanup_mutation: str | None = None,
        projection_mismatch: bool = False,
        receipt_mutation: str | None = None,
        finalize_failure: bool = False,
    ) -> None:
        self.fail_actual = fail_actual
        self.group_variant = group_variant
        self.cleanup_mutation = cleanup_mutation
        self.projection_mismatch = projection_mismatch
        self.receipt_mutation = receipt_mutation
        self.finalize_failure = finalize_failure
        self.calls: list[tuple[str, object]] = []
        self.owned_groups: list[_OwnedGroups] = []
        self.probe_dirs: dict[str, Path] = {}
        self.probe_cells: dict[str, tuple[str, str]] = {}

    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]:
        self.calls.append(("load_provider_manifest", Path(path)))
        return {
            "contract_version": "test_provider_manifest_v1",
            "provider_manifest_id": "manifest-1",
            "provider_corpus_ref": {
                "contract_version": "test_provider_manifest_corpus_ref_v1",
                "relative_path": "provider-corpus.v2.json",
                "file_sha256": "a" * 64,
                "content_sha256": "b" * 64,
                "source_parent_ref": _sealed({"kind": "source-parent"}),
            },
        }

    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> _OwnedGroups:
        self.calls.append(
            (
                "prepare_screen_groups",
                {
                    "provider_manifest": dict(provider_manifest),
                    "partition": partition,
                    "attempt_ref": dict(attempt_ref),
                    "attempt_dir": Path(attempt_dir),
                },
            )
        )
        count = {"empty": 0, "two": 2, "missing": 11}.get(self.group_variant, 12)
        values = []
        provider_corpus_ref = dict(provider_manifest["provider_corpus_ref"])
        provider_corpus_ref["contract_version"] = "test_provider_corpus_file_ref_v1"
        for group_index in range(count):
            case_refs = [
                {
                    "case_id": f"case-{group_index * 5 + case_index:03d}",
                    "case_content_sha256": hashlib.sha256(
                        f"case-{group_index * 5 + case_index:03d}".encode("utf-8")
                    ).hexdigest(),
                }
                for case_index in range(5)
            ]
            values.append(
                _sealed(
                    {
                        "screen_group": (
                            "screen-group-same-id"
                            if self.group_variant == "same_id_different_hash"
                            else f"screen-group-{group_index + 1:02d}"
                        ),
                        "partition": partition,
                        "attempt_ref": dict(attempt_ref),
                        "provider_corpus_ref": provider_corpus_ref,
                        "case_refs": case_refs,
                        "request_ref": _sealed(
                            {"request_id": f"request-{group_index + 1:02d}"}
                        ),
                    }
                )
            )
        if self.group_variant == "duplicate":
            values[-1] = dict(values[0])
        groups = _OwnedGroups(values)
        self.owned_groups.append(groups)
        return groups

    def run_actual_screen_group(
        self,
        *,
        provider_group: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]:
        ledger = next(Path(attempt_dir).parents[1].rglob("*.jsonl"))
        chain = _read_chain(ledger)
        assert chain[-1]["event"]["event_type"] == "regression_attempt"
        assert chain[-1]["event"]["event_payload"]["status"] == "opened"
        self.calls.append(("run_actual_screen_group", provider_group["screen_group"]))
        if self.fail_actual:
            raise RuntimeError("deterministic actual failure")
        screen_group = str(provider_group["screen_group"])
        if self.projection_mismatch:
            screen_group += "-stale"
        rows = [
            {
                "case_ref": dict(case_ref),
                "arm_id": arm_id,
                "shared_parent_refs": {
                    "screen_group_ref": {
                        "id": screen_group,
                        "content_sha256": provider_group["content_sha256"],
                    }
                },
            }
            for case_ref in provider_group["case_refs"]
            for arm_id in (
                "qwen_only",
                "omni_only_discovery",
                "omni_to_qwen",
                "omni_to_qwen_vista",
            )
        ]
        return _sealed(
            {
                "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
                "partition": "regression",
                "screen_group": screen_group,
                "request_ref": dict(provider_group["request_ref"]),
                "shared_parent_refs": {
                    "screen_group_ref": {
                        "id": screen_group,
                        "content_sha256": provider_group["content_sha256"],
                    }
                },
                "rows": rows,
                "attempt_dir": str(Path(attempt_dir)),
                **SAFETY,
            }
        )

    def begin_probe(
        self,
        *,
        provider_id: str,
        probe_kind: str,
        provider_manifest: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]:
        ledger = next(Path(attempt_dir).parents[1].rglob("*.jsonl"))
        assert _read_chain(ledger)[-1]["event"]["event_payload"]["status"] == "opened"
        self.calls.append(("begin_probe", (provider_id, probe_kind)))
        self.probe_dirs[str(attempt_ref["content_sha256"])] = Path(attempt_dir)
        self.probe_cells[str(attempt_ref["content_sha256"])] = (provider_id, probe_kind)
        return _sealed(
            {
                "contract_version": "test_probe_context_v1",
                "provider_id": provider_id,
                "probe_kind": probe_kind,
                "attempt_ref": dict(attempt_ref),
                "manifest_ref": {"content_sha256": "f" * 64},
                **SAFETY,
            }
        )

    def read_server_journal(
        self, *, probe_context: Mapping[str, object]
    ) -> Mapping[str, object]:
        self.calls.append(("read_server_journal", probe_context["provider_id"]))
        return _sealed(
            {
                "contract_version": "test_request_in_flight_v1",
                "provider_id": probe_context["provider_id"],
                "request_state": "request_in_flight",
                **SAFETY,
            }
        )

    def trigger_probe(
        self,
        *,
        probe_context: Mapping[str, object],
        probe_kind: str,
        request_in_flight_journal: Mapping[str, object],
    ) -> Mapping[str, object]:
        assert request_in_flight_journal["request_state"] == "request_in_flight"
        self.calls.append(("trigger_probe", (probe_context["provider_id"], probe_kind)))
        return _sealed(
            {
                "contract_version": "test_probe_trigger_v1",
                "provider_id": probe_context["provider_id"],
                "probe_kind": probe_kind,
                "outcome": "safe_stopped",
                **SAFETY,
            }
        )

    def cleanup_attempt(
        self, *, attempt: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        self.calls.append(("cleanup_attempt", (attempt["attempt_id"], reason)))
        receipt = _sealed(
            {
                "contract_version": "benchmark_v2_attempt_cleanup_receipt_v1",
                "attempt_ref": dict(attempt),
                "reason": reason,
                "service_terminal_ref": _sealed({"kind": "service-terminal"}),
                "window_cleanup_ref": _sealed({"kind": "window-cleanup"}),
                "provider_cleanup_refs": [
                    _sealed({"kind": "provider-cleanup"})
                ],
                "cleanup_status": "stable_zero",
                "lost_response_policy": "fresh_reconcile_safe_stop_no_blind_retry",
                "resource_counts": {
                    "service_operations": 0,
                    "windows": 0,
                    "providers": 0,
                    "listeners": 0,
                    "leases": 0,
                },
                **SAFETY,
            }
        )
        if self.cleanup_mutation == "bogus":
            return _sealed({"arbitrary": True})
        if self.cleanup_mutation == "attempt_mismatch":
            receipt["attempt_ref"] = _sealed({"attempt_id": "attempt-other"})
        elif self.cleanup_mutation == "missing_status":
            receipt.pop("cleanup_status")
        elif self.cleanup_mutation == "missing_refs":
            receipt["service_terminal_ref"] = None
            receipt["window_cleanup_ref"] = None
            receipt["provider_cleanup_refs"] = []
        if self.cleanup_mutation is not None:
            receipt["content_sha256"] = hashlib.sha256(
                _canonical(
                    {
                        name: value
                        for name, value in receipt.items()
                        if name != "content_sha256"
                    }
                )
            ).hexdigest()
        return receipt

    def finalize_probe_lifecycle_receipt(self, *, provider_manifest, attempt_ref, cleanup_receipt):
        del provider_manifest
        self.calls.append(("finalize_probe_lifecycle_receipt", attempt_ref["attempt_id"]))
        if self.finalize_failure:
            raise RuntimeError("deterministic finalize failure")
        provider, probe_kind = self.probe_cells[str(attempt_ref["content_sha256"])]
        receipt = _probe_receipt(
            attempt_ref=attempt_ref,
            provider=provider,
            probe_kind=probe_kind,
            cleanup_receipt=cleanup_receipt,
        )
        if self.receipt_mutation == "provider":
            receipt["provider"]["provider_id"] = "qwen" if provider != "qwen" else "vista"
        elif self.receipt_mutation == "kind":
            receipt["probe_kind"] = "timeout" if probe_kind == "cancel" else "cancel"
        elif self.receipt_mutation == "probe_id":
            receipt["probe_id"] = "probe/cross-attempt"
        elif self.receipt_mutation == "cleanup":
            receipt["cleanup_receipt_ref"] = {"content_sha256": "9" * 64}
        elif self.receipt_mutation == "top_extra":
            receipt["unexpected"] = True
        elif self.receipt_mutation == "release":
            receipt["benchmark_release_id"] = "different-release"
        elif self.receipt_mutation == "d2_owned_semantics":
            receipt["observer_identity"] = {"runtime_owned": True}
            receipt["trigger_observation"] = {"runtime_owned": "trigger"}
            receipt["stable_zero_observation"] = {"runtime_owned": "stable-zero"}
        elif self.receipt_mutation == "returned_file_mismatch":
            persisted = deepcopy(receipt)
            persisted["status"] = "FAIL"
            persisted["content_sha256"] = runner._content_sha256(persisted)
        else:
            persisted = receipt
        if self.receipt_mutation not in {None, "returned_file_mismatch"}:
            receipt["content_sha256"] = runner._content_sha256(receipt)
            persisted = receipt
        path = self.probe_dirs[str(attempt_ref["content_sha256"])] / "lifecycle-probe-receipt.json"
        path.write_bytes(json.dumps(persisted, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
        return receipt

    def resource_counts(self) -> Mapping[str, int]:
        self.calls.append(("resource_counts", None))
        return {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }


def _install_runtime(monkeypatch: pytest.MonkeyPatch, runtime: object) -> None:
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: runtime,
    )


def _manifest(tmp_path: Path) -> Path:
    path = tmp_path / "provider-manifest.json"
    path.write_text("{}\n", encoding="utf-8")
    return path


def _run_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime: object,
    *,
    probe_kind: str = "cancel",
    providers: str = "omni,qwen,vista",
    suffix: str = "run",
) -> tuple[dict[str, object], Path]:
    monkeypatch.setattr(runner, "_PROJECT_ROOT", tmp_path)
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / f"{probe_kind}-{suffix}.jsonl"
    result = runner.run_cli(
        [
            "--provider-manifest",
            str(_manifest(tmp_path)),
            "--partition",
            "regression",
            f"--run-{probe_kind}-probe",
            "--providers",
            providers,
            "--attempt-ledger",
            str(ledger),
            "--output-root",
            str(tmp_path / suffix),
        ]
    )
    return result, ledger


def test_dry_run_loads_the_public_facade_and_never_prepares_or_dispatches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    output = tmp_path / "dry-run.json"

    result = runner.run_cli(
        [
            "--provider-manifest",
            str(_manifest(tmp_path)),
            "--partition",
            "regression",
            "--dry-run",
            "--output",
            str(output),
        ]
    )

    assert result == _read_json(output)
    assert result["contract_version"] == "benchmark_v2_runner_dry_run_v1"
    assert result["partition"] == "regression"
    assert result["provider_manifest_ref"] == {
        "content_sha256": "3d1e18d198c6fdd80e778f0aa5c4ebba5df87fcc8fcde79f09aec2a317c3b490"
    }
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert [name for name, _ in runtime.calls] == ["load_provider_manifest"]


def test_actual_reserves_unique_attempts_before_dispatch_and_preserves_both_chains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "regression" / "events.jsonl"
    output_root = tmp_path / "attempts"
    argv = [
        "--provider-manifest",
        str(_manifest(tmp_path)),
        "--partition",
        "regression",
        "--actual-models",
        "--attempt-ledger",
        str(ledger),
        "--output-root",
        str(output_root),
    ]

    first = runner.run_cli(argv)
    second = runner.run_cli(argv)

    assert first["attempt_ref"] != second["attempt_ref"]
    assert Path(first["attempt_dir"]).parent == output_root.resolve()
    assert Path(second["attempt_dir"]).parent == output_root.resolve()
    assert Path(first["attempt_dir"]).is_dir()
    assert Path(second["attempt_dir"]).is_dir()
    chain = _read_chain(ledger)
    assert [item["contract_version"] for item in chain] == [
        "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2"
    ] * 8
    assert [item["event"]["sequence"] for item in chain] == list(range(8))
    assert [item["event"]["event_type"] for item in chain] == [
        "regression_attempt",
        "regression_attempt",
        "cleanup",
        "result",
        "regression_attempt",
        "regression_attempt",
        "cleanup",
        "result",
    ]
    assert [item["event"]["event_payload"]["status"] for item in chain] == [
        "opened",
        "body_complete",
        "terminal",
        "terminal",
        "opened",
        "body_complete",
        "terminal",
        "terminal",
    ]
    for result, start in ((first, 0), (second, 4)):
        attempt_dir = Path(result["attempt_dir"])
        body_path = attempt_dir / "body.json"
        cleanup_path = attempt_dir / "cleanup.json"
        result_path = attempt_dir / "result.json"
        assert cleanup_path.is_file()
        assert result_path.is_file()
        assert result == _read_json(result_path)
        assert result["contract_version"] == "benchmark_v2_runner_actual_result_v2"
        assert set(result) == {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "body_ref",
            "cleanup_receipt_ref",
            "attempt_ledger_pre_result_ref",
            "screen_group_count",
            "status",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        body = _read_json(body_path)
        cleanup = _read_json(cleanup_path)
        assert result["body_ref"] == {
            "path": str(body_path.resolve()),
            "file_sha256": hashlib.sha256(body_path.read_bytes()).hexdigest(),
            "content_sha256": body["content_sha256"],
        }
        assert result["cleanup_receipt_ref"] == {
            "path": str(cleanup_path.resolve()),
            "file_sha256": hashlib.sha256(cleanup_path.read_bytes()).hexdigest(),
            "content_sha256": cleanup["content_sha256"],
        }
        prefix = b"".join(
            _canonical(item) + b"\n" for item in chain[: start + 3]
        )
        assert result["attempt_ledger_pre_result_ref"] == _pre_result_ref(
            prefix, chain[: start + 4]
        )
        result_event = chain[start + 3]["event"]["event_payload"]
        assert result_event["contract_version"] == "benchmark_v2_runner_result_payload_v1"
        assert result_event["output_ref"] == {
            "path": str(result_path.resolve()),
            "file_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "content_sha256": result["content_sha256"],
        }
    assert all(group.closed for group in runtime.owned_groups)
    assert all(value == 0 for value in runtime.resource_counts().values())


def _materializer_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    attempt_count: int = 1,
    prior_incomplete: bool = False,
) -> tuple[list[str], Path, Path, Path, dict[str, object]]:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    provider_manifest = tmp_path / "benchmark-v2-provider-manifest.json"
    provider_manifest.write_bytes(b"{}\n")
    provider_corpus = tmp_path / "provider-corpus.v2.json"
    provider_corpus.write_bytes(b"{}\n")
    ledger = tmp_path / "ledger" / "regression" / "events.jsonl"
    output_root = tmp_path / "attempts"
    if prior_incomplete:
        runner._reserve_attempt(
            ledger_path=ledger,
            output_root=output_root,
            mode="actual_models",
            provider_id=None,
        )
    results = []
    for _index in range(attempt_count):
        results.append(
            runner.run_cli(
                [
                    "--provider-manifest",
                    str(provider_manifest),
                    "--partition",
                    "regression",
                    "--actual-models",
                    "--attempt-ledger",
                    str(ledger),
                    "--output-root",
                    str(output_root),
                ]
            )
        )
    calls: dict[str, object] = {"accepted": []}
    project_root = tmp_path / "project-root"
    monkeypatch.setattr(runner, "_PROJECT_ROOT", project_root)
    for result in results:
        attempt = result["attempt_ref"]
        journal = (
            project_root
            / "runtime_state"
            / "benchmark-v2-attempts"
            / f"{attempt['content_sha256']}.jsonl"
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_bytes(b"{}\n")

    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_cleanup_lifecycle",
        lambda **kwargs: {"kind": "cleanup", "attempt_ref": kwargs["attempt_ref"]},
    )
    monkeypatch.setattr(
        runner,
        "read_benchmark_v2_attempt_journal",
        lambda **kwargs: [{"kind": "journal", "path": str(kwargs["journal_path"])}],
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_attempt_journal_terminal_event",
        lambda **kwargs: {"kind": "terminal"},
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_attempt_journal",
        lambda **kwargs: {"kind": "journal-projection"},
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_screen_group_lifecycles",
        lambda **kwargs: [{"kind": "screen", "index": index} for index in range(12)],
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_attempt_lifecycle",
        lambda **kwargs: {"kind": "attempt-lifecycle"},
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_runner_events",
        lambda **kwargs: [
            {"kind": "runner-event", "sequence": index}
            for index, _item in enumerate(kwargs["runner_ledger_events"])
        ],
    )
    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_attempt_ledger_projections",
        lambda **kwargs: SimpleNamespace(
            runner_ledger_prefix_projection={"kind": "prefix"},
            projected_attempt_ledger={"kind": "projected-ledger"},
        ),
    )
    monkeypatch.setattr(
        runner,
        "compose_benchmark_v2_lifecycle_bundle_v3",
        lambda **kwargs: {"kind": "lifecycle-bundle"},
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_actual_body",
        lambda **kwargs: {"kind": "body-projection"},
    )
    monkeypatch.setattr(
        runner,
        "project_benchmark_v2_actual_result",
        lambda **kwargs: {"kind": "result-projection"},
    )

    def _accepted(**kwargs: object) -> dict[str, object]:
        calls["accepted"].append(kwargs)
        return _sealed(
            {
                "contract_version": "benchmark_v2_accepted_regression_score_input_v2",
                "selected_attempt_sha256": results[0]["attempt_ref"]["content_sha256"],
            }
        )

    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_accepted_regression_score_input_v2",
        _accepted,
    )
    argv = [
        "--provider-manifest",
        str(provider_manifest),
        "--partition",
        "regression",
        "--materialize-score-input",
        "--attempt-ledger",
        str(ledger),
        "--output-root",
        str(output_root),
        "--output",
        str(tmp_path / "accepted-run-ref.json"),
    ]
    return argv, ledger, output_root, provider_manifest, calls


def test_materialize_score_input_is_offline_and_passes_fixed_trusted_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    getter_calls = 0

    def _forbid_runtime() -> object:
        nonlocal getter_calls
        getter_calls += 1
        raise AssertionError("offline materializer acquired Runtime")

    monkeypatch.setattr(runner, "get_production_benchmark_v2_runtime", _forbid_runtime)

    first = runner.run_cli(argv)
    second = runner.run_cli(argv)

    assert getter_calls == 0
    assert first == second == _read_json(Path(argv[-1]))
    assert Path(argv[-1]).read_bytes() == (
        json.dumps(first, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        + b"\n"
    )
    assert len(calls["accepted"]) == 2
    trusted = calls["accepted"][0]
    chain = _read_chain(ledger)
    selected_dir = Path(chain[0]["event"]["event_payload"]["attempt_dir"])
    assert trusted["actual_body_bytes"] == (selected_dir / "body.json").read_bytes()
    assert trusted["actual_result_bytes"] == (selected_dir / "result.json").read_bytes()
    assert trusted["cleanup_receipt_bytes"] == (selected_dir / "cleanup.json").read_bytes()
    assert trusted["expected_attempt_dir"] == selected_dir.resolve()
    assert trusted["provider_manifest_bytes"] == provider_manifest.read_bytes()
    assert trusted["provider_corpus_bytes"] == (
        provider_manifest.parent / "provider-corpus.v2.json"
    ).read_bytes()


def test_materialize_score_input_true_offline_producer_is_deterministic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.learn.hybrid.benchmark_v2_privileged_projector import (
        project_provider_corpus,
    )
    from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_isolation import (
        PARENT_PATH,
        _canonical_bytes as canonical_pretty_bytes,
        _provider_manifest_value,
    )
    from tests.test_portfolio_hybrid_v1_1_benchmark_v2_lifecycle import (
        _s13_attempt,
        _s13_cleanup,
        _s13_journal,
        _s13_screen_projection,
    )

    provider_corpus_path = tmp_path / "provider-corpus.v2.json"
    project_provider_corpus(
        parent_manifest_path=PARENT_PATH,
        output_path=provider_corpus_path,
    )
    provider_corpus = _read_json(provider_corpus_path)
    provider_manifest = _provider_manifest_value(
        provider_corpus,
        hashlib.sha256(provider_corpus_path.read_bytes()).hexdigest(),
    )
    provider_manifest_path = tmp_path / "benchmark-v2-provider-manifest.json"
    provider_manifest_path.write_bytes(canonical_pretty_bytes(provider_manifest))

    cases_by_group: dict[str, list[dict[str, str]]] = {}
    for case in provider_corpus["cases"]:
        if case["partition"] != "regression":
            continue
        cases_by_group.setdefault(str(case["screen_group"]), []).append(
            {
                "case_id": str(case["case_id"]),
                "case_content_sha256": content_sha256(case),
            }
        )
    assert len(cases_by_group) == 12
    assert {len(values) for values in cases_by_group.values()} == {5}

    attempt = _s13_attempt(attempt_id="attempt-regression-true-offline")
    output_root = tmp_path / "attempts"
    attempt_dir = output_root / str(attempt["attempt_id"])
    attempt_dir.mkdir(parents=True)
    screens: list[dict[str, object]] = []
    for screen_index, (screen_group, case_refs) in enumerate(
        sorted(cases_by_group.items())
    ):
        screen = _s13_screen_projection(
            attempt=attempt,
            screen_group=screen_group,
            case_refs_override=case_refs,
            evidence_width=1280 + screen_index,
        )
        for row in screen["rows"]:
            if row["arm_id"] == "qwen_only":
                row["observation"]["response"] = {
                    "screen_reading": {
                        "screen_inventory": {"available_actions": []}
                    }
                }
            elif row["arm_id"] == "omni_to_qwen_vista":
                row["observation"]["review_projection"] = {"proposals": []}
        screen.pop("content_sha256")
        screens.append(seal_immutable(screen))
    body = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_body_v1",
            "attempt_ref": attempt,
            "partition": "regression",
            "screen_group_results": screens,
            "body_status": "complete",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    cleanup = _s13_cleanup(attempt)
    body_path = attempt_dir / "body.json"
    cleanup_path = attempt_dir / "cleanup.json"
    body_path.write_bytes(_canonical(body) + b"\n")
    cleanup_path.write_bytes(_canonical(cleanup) + b"\n")
    ledger = tmp_path / "ledger" / "regression" / "events.jsonl"
    runner._append_ledger_event(
        ledger,
        event_type="regression_attempt",
        payload=runner._attempt_payload(
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            status="opened",
            output_ref=None,
        ),
    )
    runner._append_ledger_event(
        ledger,
        event_type="regression_attempt",
        payload=runner._attempt_payload(
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            status="body_complete",
            output_ref=runner._file_ref(body_path, body),
        ),
    )
    runner._append_ledger_event(
        ledger,
        event_type="cleanup",
        payload=runner._cleanup_payload(
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            cleanup_receipt_ref=runner._file_ref(cleanup_path, cleanup),
            resource_counts=cleanup["resource_counts"],
        ),
    )
    pre_result_ref = runner._pre_result_ref_from_ledger(
        ledger, attempt_ref=attempt
    )
    result = runner._seal(
        {
            "contract_version": "benchmark_v2_runner_actual_result_v2",
            "attempt_ref": attempt,
            "attempt_dir": str(attempt_dir.resolve()),
            "body_ref": runner._file_ref(body_path, body),
            "cleanup_receipt_ref": runner._file_ref(cleanup_path, cleanup),
            "attempt_ledger_pre_result_ref": pre_result_ref,
            "screen_group_count": 12,
            "status": "terminal",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    runner._append_result_file_event(
        ledger_path=ledger,
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
        result=result,
    )

    project_root = tmp_path / "project-root"
    monkeypatch.setattr(runner, "_PROJECT_ROOT", project_root)
    journal_path = (
        project_root
        / "runtime_state"
        / "benchmark-v2-attempts"
        / f"{attempt['content_sha256']}.jsonl"
    )
    journal_path.parent.mkdir(parents=True)
    journal_path.write_bytes(
        b"".join(
            _canonical(event) + b"\n"
            for event in _s13_journal(attempt=attempt, cleanup=cleanup)
        )
    )
    getter_calls = 0

    def forbid_runtime() -> object:
        nonlocal getter_calls
        getter_calls += 1
        raise AssertionError("offline materializer acquired Runtime")

    monkeypatch.setattr(runner, "get_production_benchmark_v2_runtime", forbid_runtime)
    output_path = tmp_path / "accepted-run-ref.json"
    argv = [
        "--provider-manifest",
        str(provider_manifest_path),
        "--partition",
        "regression",
        "--materialize-score-input",
        "--attempt-ledger",
        str(ledger),
        "--output-root",
        str(output_root),
        "--output",
        str(output_path),
    ]

    first = runner.run_cli(argv)
    first_bytes = output_path.read_bytes()
    second = runner.run_cli(argv)

    assert getter_calls == 0
    assert first == second == _read_json(output_path)
    assert output_path.read_bytes() == first_bytes
    assert first["contract_version"] == (
        "benchmark_v2_accepted_regression_score_input_v2"
    )
    assert all(value == 0 for value in cleanup["resource_counts"].values())


def test_materialize_score_input_ignores_selected_suffix_artifact_damage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path, attempt_count=2
    )
    chain = _read_chain(ledger)
    suffix_dir = Path(chain[4]["event"]["event_payload"]["attempt_dir"])
    (suffix_dir / "body.json").write_bytes(b"damaged suffix")
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("Runtime acquired")),
    )

    runner.run_cli(argv)

    assert len(calls["accepted"]) == 1


def test_materialize_score_input_skips_prior_incomplete_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path, prior_incomplete=True
    )

    result = runner.run_cli(argv)

    chain = _read_chain(ledger)
    assert chain[0]["event"]["event_payload"]["status"] == "opened"
    assert result["selected_attempt_sha256"] == chain[1]["event"]["event_payload"][
        "attempt_ref"
    ]["content_sha256"]
    assert len(calls["accepted"]) == 1


def test_materialize_score_input_rejects_corrupt_structural_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path, attempt_count=2
    )
    chain = _read_chain(ledger)
    chain[-1]["event_sha256"] = "f" * 64
    ledger.write_bytes(b"\n".join(_canonical(item) for item in chain) + b"\n")

    with pytest.raises(ValueError, match="hash chain"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_never_replaces_selected_complete_with_missing_journal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path, attempt_count=2
    )
    selected = _read_chain(ledger)[0]["event"]["event_payload"]["attempt_ref"]
    journal = (
        runner._PROJECT_ROOT
        / "runtime_state"
        / "benchmark-v2-attempts"
        / f"{selected['content_sha256']}.jsonl"
    )
    journal.unlink()

    with pytest.raises(ValueError, match="selected attempt journal fixed file is missing"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_rejects_attempt_directory_outside_immediate_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    chain = _read_chain(ledger)
    outside = tmp_path / "outside" / chain[0]["event"]["event_payload"][
        "attempt_ref"
    ]["attempt_id"]
    outside.mkdir(parents=True)
    for envelope in chain:
        payload = envelope["event"]["event_payload"]
        payload["attempt_dir"] = str(outside.resolve())
        envelope["event"]["event_payload"] = _sealed(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    _rewrite_chain(ledger, chain)

    with pytest.raises(ValueError, match="immediate fixed child"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_requires_fixed_provider_corpus_sibling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    (provider_manifest.parent / "provider-corpus.v2.json").rename(
        provider_manifest.parent / "alternate-corpus.json"
    )

    with pytest.raises(ValueError, match="provider corpus fixed file is missing"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_requires_fixed_provider_manifest_basename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    renamed = provider_manifest.with_name("renamed-provider-manifest.json")
    renamed.write_bytes(provider_manifest.read_bytes())
    argv[argv.index(str(provider_manifest))] = str(renamed)

    with pytest.raises(ValueError, match="benchmark-v2-provider-manifest.json"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_accepts_forward_slash_relative_cli_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    monkeypatch.chdir(tmp_path)
    path_option_indexes = (
        argv.index("--provider-manifest") + 1,
        argv.index("--attempt-ledger") + 1,
        argv.index("--output-root") + 1,
        argv.index("--output") + 1,
    )
    for index in path_option_indexes:
        argv[index] = Path(argv[index]).relative_to(tmp_path).as_posix()

    accepted = runner.run_cli(argv)

    assert accepted["contract_version"] == (
        "benchmark_v2_accepted_regression_score_input_v2"
    )
    assert len(calls["accepted"]) == 1


def test_materialize_score_input_rejects_lexical_root_alias_before_dereference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    argv[argv.index(str(output_root))] = str(output_root) + "\\."

    with pytest.raises(ValueError, match="lexical alias"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_rejects_output_alias_of_selected_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    selected_dir = Path(
        _read_chain(ledger)[0]["event"]["event_payload"]["attempt_dir"]
    )
    argv[-1] = str(selected_dir / "body.json")

    with pytest.raises(ValueError, match="selected evidence path"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_rejects_provider_manifest_reparse_point(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    original = runner._is_reparse
    monkeypatch.setattr(
        runner,
        "_is_reparse",
        lambda path: Path(path) == provider_manifest.resolve() or original(path),
    )

    with pytest.raises(ValueError, match="symlink|reparse"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


def test_materialize_score_input_conflicting_publication_does_not_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, _provider_manifest, _calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    output = Path(argv[-1])
    output.write_bytes(b"different\n")
    before = output.read_bytes()

    with pytest.raises(ValueError, match="differs from authoritative bytes"):
        runner.run_cli(argv)

    assert output.read_bytes() == before


def test_materialize_score_input_rejects_empty_forbidden_option_presence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _ledger, _output_root, _provider_manifest, calls = _materializer_fixture(
        monkeypatch, tmp_path
    )
    argv.extend(["--providers", ""])

    with pytest.raises(ValueError, match="not valid for this action"):
        runner.run_cli(argv)

    assert calls["accepted"] == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--partition", "holdout"],
        ["--providers", "omni"],
        ["--ledger-root", "forbidden"],
        ["--holdout-authorization", "forbidden"],
    ],
)
def test_materialize_score_input_rejects_non_regression_or_mixed_action_inputs_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]
) -> None:
    argv = [
        "--provider-manifest",
        str(_manifest(tmp_path)),
        "--partition",
        "regression",
        "--materialize-score-input",
        "--attempt-ledger",
        str(tmp_path / "events.jsonl"),
        "--output-root",
        str(tmp_path / "attempts"),
        "--output",
        str(tmp_path / "accepted.json"),
    ]
    if extra[0] == "--partition":
        argv[argv.index("regression")] = "holdout"
    else:
        argv.extend(extra)
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("Runtime acquired")),
    )

    with pytest.raises(ValueError):
        runner.run_cli(argv)


def test_actual_consumer_failure_closes_owner_then_cleans_and_remains_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime(fail_actual=True)
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"

    with pytest.raises(RuntimeError, match="deterministic actual failure"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--actual-models",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "attempts"),
            ]
        )

    assert runtime.owned_groups[0].closed is True
    names = [name for name, _ in runtime.calls]
    assert names.index("run_actual_screen_group") < names.index("cleanup_attempt")
    assert _read_chain(ledger)[-1]["event"]["event_type"] == "cleanup"
    assert all(value == 0 for value in runtime.resource_counts().values())


def test_cleanup_receipt_is_create_new_or_byte_identical_before_ledger_append(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    ledger = tmp_path / "ledger" / "events.jsonl"
    attempt, attempt_dir = runner._reserve_attempt(
        ledger_path=ledger,
        output_root=tmp_path / "attempts",
        mode="actual_models",
        provider_id=None,
    )
    original_append = runner._append_ledger_event

    def _fail_cleanup_append(path, *, event_type, payload):
        if event_type == "cleanup":
            raise OSError("simulated append interruption")
        return original_append(path, event_type=event_type, payload=payload)

    monkeypatch.setattr(runner, "_append_ledger_event", _fail_cleanup_append)
    with pytest.raises(OSError, match="append interruption"):
        runner._finish_attempt(
            runtime,
            ledger_path=ledger,
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            reason="benchmark_v2_actual_runner_finished",
            require_effect_refs=True,
        )

    cleanup_path = attempt_dir / "cleanup.json"
    first_bytes = cleanup_path.read_bytes()
    assert first_bytes.endswith(b"\n")
    monkeypatch.setattr(runner, "_append_ledger_event", original_append)

    cleanup = runner._finish_attempt(
        runtime,
        ledger_path=ledger,
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
        reason="benchmark_v2_actual_runner_finished",
        require_effect_refs=True,
    )

    assert cleanup_path.read_bytes() == first_bytes
    assert cleanup == _read_json(cleanup_path)
    cleanup_payload = _read_chain(ledger)[-1]["event"]["event_payload"]
    assert cleanup_payload["cleanup_receipt_ref"] == {
        "path": str(cleanup_path.resolve()),
        "file_sha256": hashlib.sha256(first_bytes).hexdigest(),
        "content_sha256": cleanup["content_sha256"],
    }


def test_cleanup_receipt_rejects_preexisting_different_bytes(
    tmp_path: Path,
) -> None:
    runtime = _DeterministicRuntime()
    ledger = tmp_path / "ledger" / "events.jsonl"
    attempt, attempt_dir = runner._reserve_attempt(
        ledger_path=ledger,
        output_root=tmp_path / "attempts",
        mode="actual_models",
        provider_id=None,
    )
    cleanup_path = attempt_dir / "cleanup.json"
    cleanup_path.write_bytes(b"{}\n")

    with pytest.raises(ValueError, match="cleanup.json.*differs"):
        runner._finish_attempt(
            runtime,
            ledger_path=ledger,
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            reason="benchmark_v2_actual_runner_finished",
            require_effect_refs=True,
        )

    assert cleanup_path.read_bytes() == b"{}\n"
    assert [item["event"]["event_payload"]["status"] for item in _read_chain(ledger)] == [
        "opened"
    ]


@pytest.mark.parametrize(
    "mutation", ["indeterminate", "nonzero", "missing_effect_refs"]
)
def test_ledger_rejects_reminted_non_authoritative_cleanup_receipt(
    tmp_path: Path, mutation: str
) -> None:
    runtime = _DeterministicRuntime()
    ledger = tmp_path / "ledger" / "events.jsonl"
    attempt, attempt_dir = runner._reserve_attempt(
        ledger_path=ledger,
        output_root=tmp_path / "attempts",
        mode="actual_models",
        provider_id=None,
    )
    body = _sealed(
        {
            "contract_version": "test_actual_body_v1",
            "attempt_ref": attempt,
            **SAFETY,
        }
    )
    body_path = attempt_dir / "body.json"
    body_path.write_bytes(_canonical(body) + b"\n")
    runner._append_ledger_event(
        ledger,
        event_type="regression_attempt",
        payload=runner._attempt_payload(
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
            status="body_complete",
            output_ref=runner._file_ref(body_path, body),
        ),
    )
    runner._finish_attempt(
        runtime,
        ledger_path=ledger,
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
        reason="benchmark_v2_actual_runner_finished",
        require_effect_refs=True,
    )
    cleanup_path = attempt_dir / "cleanup.json"
    cleanup = _read_json(cleanup_path)
    if mutation == "indeterminate":
        cleanup["cleanup_status"] = "indeterminate"
    elif mutation == "nonzero":
        cleanup["resource_counts"]["providers"] = 1
    else:
        cleanup["service_terminal_ref"] = None
        cleanup["window_cleanup_ref"] = None
        cleanup["provider_cleanup_refs"] = []
    cleanup = _sealed(
        {name: value for name, value in cleanup.items() if name != "content_sha256"}
    )
    cleanup_path.write_bytes(_canonical(cleanup) + b"\n")
    chain = _read_chain(ledger)
    payload = chain[-1]["event"]["event_payload"]
    payload["cleanup_receipt_ref"] = {
        "path": str(cleanup_path.resolve()),
        "file_sha256": hashlib.sha256(cleanup_path.read_bytes()).hexdigest(),
        "content_sha256": cleanup["content_sha256"],
    }
    chain[-1]["event"]["event_payload"] = _sealed(
        {name: value for name, value in payload.items() if name != "content_sha256"}
    )
    _rewrite_chain(ledger, chain)

    with pytest.raises(ValueError, match="authoritative cleanup receipt"):
        runner._read_ledger(ledger)


def test_cleanup_open_attempts_recovers_after_cleanup_file_fsync_before_append(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "regression" / "events.jsonl"
    attempts_root = tmp_path / "attempts"
    original_append = runner._append_ledger_event
    failed = False

    def _fail_first_cleanup_append(path, *, event_type, payload):
        nonlocal failed
        if event_type == "cleanup" and not failed:
            failed = True
            raise OSError("simulated cleanup ledger append interruption")
        return original_append(path, event_type=event_type, payload=payload)

    monkeypatch.setattr(runner, "_append_ledger_event", _fail_first_cleanup_append)
    with pytest.raises(OSError, match="cleanup ledger append interruption"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--actual-models",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(attempts_root),
            ]
        )
    attempt_dir = next(path for path in attempts_root.iterdir() if path.is_dir())
    cleanup_path = attempt_dir / "cleanup.json"
    cleanup_bytes = cleanup_path.read_bytes()
    assert [item["event"]["event_payload"]["status"] for item in _read_chain(ledger)] == [
        "opened",
        "body_complete",
    ]
    monkeypatch.setattr(runner, "_append_ledger_event", original_append)

    summary = runner.run_cli(
        [
            "--cleanup-open-attempts",
            "--partition",
            "regression",
            "--ledger-root",
            str(ledger_root),
            "--output-root",
            str(tmp_path / "cleanup-output"),
        ]
    )

    assert summary["cleaned_attempt_count"] == 1
    assert cleanup_path.read_bytes() == cleanup_bytes
    assert [item["event"]["event_payload"]["status"] for item in _read_chain(ledger)] == [
        "opened",
        "body_complete",
        "terminal",
    ]
    cleanup_calls = [
        value for name, value in runtime.calls if name == "cleanup_attempt"
    ]
    assert len(cleanup_calls) == 2
    assert cleanup_calls[0][1] == cleanup_calls[1][1]
    assert all(value == 0 for value in runtime.resource_counts().values())


@pytest.mark.parametrize("mutation", ["v1", "noncanonical", "torn"])
def test_ledger_v2_rejects_old_noncanonical_or_torn_jsonl(
    tmp_path: Path, mutation: str
) -> None:
    ledger = tmp_path / f"{mutation}.jsonl"
    runner._reserve_attempt(
        ledger_path=ledger,
        output_root=tmp_path / f"attempts-{mutation}",
        mode="actual_models",
        provider_id=None,
    )
    envelope = _read_chain(ledger)[0]
    if mutation == "v1":
        envelope["contract_version"] = (
            "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v1"
        )
        ledger.write_bytes(_canonical(envelope) + b"\n")
    elif mutation == "noncanonical":
        ledger.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    else:
        ledger.write_bytes(ledger.read_bytes()[:-1])

    with pytest.raises(ValueError, match="canonical|envelope"):
        runner._read_ledger(ledger)


@pytest.mark.parametrize("mutation", ["duplicate", "reordered", "cross_ref"])
def test_ledger_v2_rejects_duplicate_reordered_or_cross_referenced_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"
    runner.run_cli(
        [
            "--provider-manifest",
            str(_manifest(tmp_path)),
            "--partition",
            "regression",
            "--actual-models",
            "--attempt-ledger",
            str(ledger),
            "--output-root",
            str(tmp_path / "attempts"),
        ]
    )
    chain = _read_chain(ledger)
    if mutation == "duplicate":
        chain.insert(1, deepcopy(chain[0]))
    elif mutation == "reordered":
        chain[0], chain[1] = chain[1], chain[0]
    else:
        payload = chain[-1]["event"]["event_payload"]
        payload["output_ref"] = deepcopy(
            chain[1]["event"]["event_payload"]["output_ref"]
        )
        chain[-1]["event"]["event_payload"] = _sealed(
            {name: value for name, value in payload.items() if name != "content_sha256"}
        )
    _rewrite_chain(ledger, chain)

    with pytest.raises(ValueError, match="state|duplicate|lineage|result"):
        runner._read_ledger(ledger)


def test_ledger_v2_rejects_old_actual_result_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"
    result = runner.run_cli(
        [
            "--provider-manifest",
            str(_manifest(tmp_path)),
            "--partition",
            "regression",
            "--actual-models",
            "--attempt-ledger",
            str(ledger),
            "--output-root",
            str(tmp_path / "attempts"),
        ]
    )
    result_path = Path(result["attempt_dir"]) / "result.json"
    old_result = _sealed(
        {
            name: value
            for name, value in result.items()
            if name not in {"contract_version", "content_sha256"}
        }
        | {"contract_version": "benchmark_v2_runner_actual_result_v1"}
    )
    result_path.write_bytes(_canonical(old_result) + b"\n")
    chain = _read_chain(ledger)
    result_payload = chain[-1]["event"]["event_payload"]
    result_payload["output_ref"] = {
        "path": str(result_path.resolve()),
        "file_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "content_sha256": old_result["content_sha256"],
    }
    chain[-1]["event"]["event_payload"] = _sealed(
        {
            name: value
            for name, value in result_payload.items()
            if name != "content_sha256"
        }
    )
    _rewrite_chain(ledger, chain)

    with pytest.raises(ValueError, match="actual result lineage"):
        runner._read_ledger(ledger)


@pytest.mark.parametrize(
    "variant", ["empty", "two", "missing", "duplicate", "same_id_different_hash"]
)
def test_actual_rejects_incomplete_or_duplicate_regression_screen_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variant: str
) -> None:
    runtime = _DeterministicRuntime(group_variant=variant)
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"

    with pytest.raises(ValueError, match="12 unique regression screen groups"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--actual-models",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "attempts"),
            ]
        )

    statuses = [
        item["event"]["event_payload"]["status"] for item in _read_chain(ledger)
    ]
    assert statuses == ["opened", "terminal"]
    assert runtime.owned_groups[0].closed is True


def test_actual_rejects_projection_that_does_not_bind_the_returned_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime(projection_mismatch=True)
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"

    with pytest.raises(ValueError, match="projection lineage"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--actual-models",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "attempts"),
            ]
        )

    assert [
        item["event"]["event_payload"]["status"] for item in _read_chain(ledger)
    ] == ["opened", "terminal"]


@pytest.mark.parametrize(
    "mutation", ["bogus", "attempt_mismatch", "missing_status", "missing_refs"]
)
def test_actual_rejects_malformed_or_mismatched_authoritative_cleanup_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    runtime = _DeterministicRuntime(cleanup_mutation=mutation)
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / "events.jsonl"

    with pytest.raises(ValueError, match="cleanup receipt"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--actual-models",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "attempts"),
            ]
        )

    assert _read_chain(ledger)[-1]["event"]["event_type"] == "regression_attempt"
    assert _read_chain(ledger)[-1]["event"]["event_payload"]["status"] == "body_complete"


@pytest.mark.parametrize(
    ("flag", "probe_kind"),
    [("--run-cancel-probe", "cancel"), ("--run-timeout-probe", "timeout")],
)
def test_probe_result_v2_receipt_ref_and_probe_summary_v2_receipt_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    probe_kind: str,
) -> None:
    monkeypatch.setattr(runner, "_PROJECT_ROOT", tmp_path)
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger = tmp_path / "ledger" / f"{probe_kind}.jsonl"

    result = runner.run_cli(
        [
            "--provider-manifest",
            str(_manifest(tmp_path)),
            "--partition",
            "regression",
            flag,
            "--providers",
            "omni,qwen,vista",
            "--attempt-ledger",
            str(ledger),
            "--output-root",
            str(tmp_path / probe_kind),
        ]
    )

    assert result["probe_kind"] == probe_kind
    assert result["contract_version"] == "benchmark_v2_runner_probe_summary_v2"
    assert result["benchmark_release_id"] == runner.BENCHMARK_RELEASE_ID
    assert result["collection_policy"] == "one_requested_attempt_per_provider"
    assert result["status"] == "terminal"
    assert "selection_policy" not in result
    assert [item["provider_id"] for item in result["attempts"]] == [
        "omni",
        "qwen",
        "vista",
    ]
    names = [name for name, _ in runtime.calls]
    assert names.count("begin_probe") == 3
    assert names.count("read_server_journal") == 3
    assert names.count("trigger_probe") == 3
    for provider in ("omni", "qwen", "vista"):
        begin = runtime.calls.index(("begin_probe", (provider, probe_kind)))
        read = runtime.calls.index(("read_server_journal", provider))
        trigger = runtime.calls.index(("trigger_probe", (provider, probe_kind)))
        item = next(value for value in result["attempts"] if value["provider_id"] == provider)
        attempt_id = item["attempt_ref"]["attempt_id"]
        cleanup = runtime.calls.index(
            (
                "cleanup_attempt",
                (attempt_id, f"benchmark_v2_{probe_kind}_probe_finished"),
            )
        )
        finalize = runtime.calls.index(("finalize_probe_lifecycle_receipt", attempt_id))
        assert begin < read < trigger < cleanup < finalize
        assert item["contract_version"] == "benchmark_v2_runner_probe_result_v2"
        assert item["status"] == "terminal"
        receipt_path = Path(item["attempt_dir"]) / "lifecycle-probe-receipt.json"
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes.decode("utf-8"))
        assert item["lifecycle_probe_receipt_ref"] == {
            "contract_version": "benchmark_v2_lifecycle_probe_receipt_v2",
            "file_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "content_sha256": receipt["content_sha256"],
        }
        assert receipt["probe_kind"] == probe_kind
        assert receipt["provider"]["provider_id"] == provider
    summary_path = (
        tmp_path
        / f"runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/{probe_kind}-probes/{probe_kind}-probes.json"
    )
    assert _read_json(summary_path) == result
    assert not (tmp_path / probe_kind / f"{probe_kind}-probes.json").exists()
    assert all(value == 0 for value in runtime.resource_counts().values())


def test_probe_summary_v2_receipt_results_preserve_requested_subset_order_and_fresh_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, ledger = _run_probe(
        monkeypatch,
        tmp_path,
        _DeterministicRuntime(),
        providers="vista,omni",
    )

    assert [item["provider_id"] for item in result["attempts"]] == ["vista", "omni"]
    assert len({item["attempt_ref"]["content_sha256"] for item in result["attempts"]}) == 2
    assert [
        row["event"]["event_payload"]["provider_id"]
        for row in _read_chain(ledger)
        if row["event"]["event_type"] == "result"
    ] == ["vista", "omni"]


@pytest.mark.parametrize(
    "mutation", ["provider", "kind", "probe_id", "cleanup", "top_extra", "release"]
)
def test_probe_result_v2_receipt_ref_rejects_receipt_mismatch_matrix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    with pytest.raises(ValueError, match="lifecycle probe"):
        _run_probe(
            monkeypatch,
            tmp_path,
            _DeterministicRuntime(receipt_mutation=mutation),
            providers="omni",
        )

    summary = (
        tmp_path
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/cancel-probes/cancel-probes.json"
    )
    assert not summary.exists()


def test_probe_result_v2_receipt_ref_defers_d2_semantics_to_production_finalizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, _ = _run_probe(
        monkeypatch,
        tmp_path,
        _DeterministicRuntime(receipt_mutation="d2_owned_semantics"),
        providers="omni",
    )

    assert result["attempts"][0]["provider_id"] == "omni"


@pytest.mark.parametrize(
    "mutation", ["returned_file_mismatch", "missing", "tampered", "noncanonical"]
)
def test_probe_result_v2_receipt_ref_rejects_returned_file_or_byte_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    runtime = _DeterministicRuntime(
        receipt_mutation=("returned_file_mismatch" if mutation == "returned_file_mismatch" else None)
    )
    original = runtime.finalize_probe_lifecycle_receipt

    def finalize(**kwargs):
        receipt = original(**kwargs)
        if mutation != "returned_file_mismatch":
            path = runtime.probe_dirs[str(kwargs["attempt_ref"]["content_sha256"])] / "lifecycle-probe-receipt.json"
            if mutation == "missing":
                path.unlink()
            elif mutation == "tampered":
                path.write_bytes(path.read_bytes().replace(b'"status": "PASS"', b'"status": "FAIL"'))
            else:
                path.write_bytes(_canonical(receipt) + b"\n")
        return receipt

    runtime.finalize_probe_lifecycle_receipt = finalize  # type: ignore[method-assign]
    with pytest.raises((FileNotFoundError, ValueError)):
        _run_probe(monkeypatch, tmp_path, runtime, providers="omni")


@pytest.mark.parametrize("failure", ["finalize", "cleanup"])
def test_probe_summary_v2_receipt_results_failure_cuts_emit_no_result_or_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    runtime = _DeterministicRuntime(
        finalize_failure=failure == "finalize",
        cleanup_mutation="bogus" if failure == "cleanup" else None,
    )
    with pytest.raises((RuntimeError, ValueError)):
        _run_probe(monkeypatch, tmp_path, runtime, providers="omni")

    attempts = list((tmp_path / "run").rglob("attempt-*"))
    assert attempts
    assert not any((path / "result.json").exists() for path in attempts)
    assert not (
        tmp_path
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/cancel-probes/cancel-probes.json"
    ).exists()


def test_probe_summary_v2_receipt_results_fixed_path_is_create_identical_never_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, _ = _run_probe(
        monkeypatch, tmp_path, _DeterministicRuntime(), providers="omni"
    )
    summary = (
        tmp_path
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/cancel-probes/cancel-probes.json"
    )
    before = summary.read_bytes()

    runner._write_json_create_or_identical(summary, result)
    assert summary.read_bytes() == before
    with pytest.raises(ValueError, match="differs from authoritative bytes"):
        runner._write_json_create_or_identical(summary, _sealed({"different": True}))
    assert summary.read_bytes() == before


@pytest.mark.parametrize("mutation", ["v1", "ref_path", "bad_sha"])
def test_probe_result_v2_receipt_ref_rejects_v1_path_or_bad_sha_on_replay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    result, _ = _run_probe(
        monkeypatch, tmp_path, _DeterministicRuntime(), providers="omni"
    )
    probe_result = deepcopy(result["attempts"][0])
    attempt_dir = Path(probe_result["attempt_dir"])
    body = _read_json(attempt_dir / "body.json")
    cleanup = _read_json(attempt_dir / "cleanup.json")
    if mutation == "v1":
        probe_result["contract_version"] = "benchmark_v2_runner_probe_result_v1"
    elif mutation == "ref_path":
        probe_result["lifecycle_probe_receipt_ref"]["path"] = str(attempt_dir)
    else:
        probe_result["lifecycle_probe_receipt_ref"]["file_sha256"] = "A" * 64
    probe_result["content_sha256"] = runner._content_sha256(probe_result)

    with pytest.raises(ValueError, match="probe result"):
        runner._validate_probe_result(
            probe_result,
            attempt_ref=probe_result["attempt_ref"],
            attempt_dir=attempt_dir,
            body_ref=body,
            cleanup_ref=cleanup,
        )


def test_probe_summary_v2_receipt_results_validator_rejects_order_or_old_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, _ = _run_probe(
        monkeypatch,
        tmp_path,
        _DeterministicRuntime(),
        providers="omni,qwen",
    )
    reversed_summary = deepcopy(result)
    reversed_summary["attempts"] = list(reversed(reversed_summary["attempts"]))
    reversed_summary["content_sha256"] = runner._content_sha256(reversed_summary)

    with pytest.raises(ValueError, match="summary"):
        runner._validate_probe_summary(
            reversed_summary,
            probe_kind="cancel",
            requested_providers=("omni", "qwen"),
            expected_results=result["attempts"],
        )


def test_probe_summary_v2_receipt_results_never_reuses_prior_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first, ledger = _run_probe(
        monkeypatch,
        tmp_path,
        _DeterministicRuntime(),
        providers="omni",
        suffix="shared",
    )
    first_attempt = first["attempts"][0]["attempt_ref"]
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)

    with pytest.raises(ValueError, match="differs from authoritative bytes"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--run-cancel-probe",
                "--providers",
                "qwen",
                "--attempt-ledger",
                str(ledger),
                "--output-root",
                str(tmp_path / "shared"),
            ]
        )

    results = [
        row["event"]["event_payload"]["attempt_ref"]
        for row in _read_chain(ledger)
        if row["event"]["event_type"] == "result"
    ]
    assert len(results) == 2
    assert results[0] == first_attempt
    assert results[1] != first_attempt


def test_holdout_probe_is_rejected_before_the_facade_can_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)

    with pytest.raises(ValueError, match="holdout"):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "holdout",
                "--run-cancel-probe",
                "--providers",
                "omni",
                "--attempt-ledger",
                str(tmp_path / "ledger.jsonl"),
                "--output-root",
                str(tmp_path / "attempts"),
            ]
        )

    assert not any(name == "begin_probe" for name, _ in runtime.calls)


def test_cleanup_recovers_open_attempt_from_ledger_when_output_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime()
    _install_runtime(monkeypatch, runtime)
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "regression" / "events.jsonl"
    attempt = _sealed(
        {
            "contract_version": "benchmark_v2_runner_attempt_ref_v1",
            "attempt_id": "attempt-crashed",
            "partition": "regression",
            "mode": "actual_models",
            "provider_id": None,
            **SAFETY,
        }
    )
    attempt_dir = tmp_path / "attempts" / "attempt-crashed"
    attempt_dir.mkdir(parents=True)
    payload = _sealed(
        {
            "contract_version": "benchmark_v2_runner_regression_attempt_payload_v1",
            "attempt_ref": attempt,
            "attempt_dir": str(attempt_dir.resolve()),
            "mode": "actual_models",
            "provider_id": None,
            "status": "opened",
            "output_ref": None,
            **SAFETY,
        }
    )
    event = {
        "partition": "regression",
        "sequence": 0,
        "event_type": "regression_attempt",
        "previous_envelope_sha256": ZERO,
        "event_payload": payload,
    }
    envelope = {
        "contract_version": "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2",
        "event": event,
        "event_sha256": hashlib.sha256(_canonical(event)).hexdigest(),
    }
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(_canonical(envelope) + b"\n")

    result = runner.run_cli(
        [
            "--cleanup-open-attempts",
            "--partition",
            "regression",
            "--ledger-root",
            str(ledger_root),
            "--output-root",
            str(tmp_path / "cleanup-output"),
        ]
    )

    assert result["cleaned_attempt_count"] == 1
    assert result["cleaned_attempt_refs"] == [
        {"content_sha256": attempt["content_sha256"]}
    ]
    assert _read_chain(ledger)[-1]["event"]["event_type"] == "cleanup"
    assert not (attempt_dir / "body.json").exists()
    assert all(value == 0 for value in runtime.resource_counts().values())


def test_cleanup_open_attempts_rejects_mismatched_authoritative_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _DeterministicRuntime(cleanup_mutation="attempt_mismatch")
    _install_runtime(monkeypatch, runtime)
    ledger_root = tmp_path / "ledger-root"
    ledger = ledger_root / "regression" / "events.jsonl"
    attempt = _sealed(
        {
            "contract_version": "benchmark_v2_runner_attempt_ref_v1",
            "attempt_id": "attempt-open-mismatch",
            "partition": "regression",
            "mode": "actual_models",
            "provider_id": None,
            **SAFETY,
        }
    )
    attempt_dir = tmp_path / "attempts" / "attempt-open-mismatch"
    attempt_dir.mkdir(parents=True)
    payload = _sealed(
        {
            "contract_version": "benchmark_v2_runner_regression_attempt_payload_v1",
            "attempt_ref": attempt,
            "attempt_dir": str(attempt_dir.resolve()),
            "mode": "actual_models",
            "provider_id": None,
            "status": "opened",
            "output_ref": None,
            **SAFETY,
        }
    )
    event = {
        "partition": "regression",
        "sequence": 0,
        "event_type": "regression_attempt",
        "previous_envelope_sha256": ZERO,
        "event_payload": payload,
    }
    envelope = {
        "contract_version": "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2",
        "event": event,
        "event_sha256": hashlib.sha256(_canonical(event)).hexdigest(),
    }
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(_canonical(envelope) + b"\n")

    with pytest.raises(ValueError, match="cleanup receipt"):
        runner.run_cli(
            [
                "--cleanup-open-attempts",
                "--partition",
                "regression",
                "--ledger-root",
                str(ledger_root),
                "--output-root",
                str(tmp_path / "cleanup-output"),
            ]
        )

    assert len(_read_chain(ledger)) == 1


@pytest.mark.parametrize("flag", ["--private-manifest", "--project-root", "--gold-path", "--fake-runtime"])
def test_cli_rejects_private_or_fake_execution_inputs(
    tmp_path: Path, flag: str
) -> None:
    with pytest.raises(SystemExit):
        runner.run_cli(
            [
                "--provider-manifest",
                str(_manifest(tmp_path)),
                "--partition",
                "regression",
                "--dry-run",
                "--output",
                str(tmp_path / "dry.json"),
                flag,
                "forbidden",
            ]
        )


def test_runner_production_import_surface_is_explicit_and_provider_safe() -> None:
    source_path = Path(runner.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    app_imports: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app."):
            app_imports.append((node.module or "", tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    app_imports.append((alias.name, ()))
    assert app_imports == [
        (
            "app.learn.hybrid.benchmark_v2_contracts",
            ("BENCHMARK_RELEASE_ID",),
        ),
        (
            "app.learn.hybrid.benchmark_v2_lifecycle",
            (
                "compose_benchmark_v2_lifecycle_bundle_v3",
                "materialize_benchmark_v2_attempt_ledger_projections",
                "project_benchmark_v2_attempt_journal",
                "project_benchmark_v2_attempt_journal_terminal_event",
                "project_benchmark_v2_attempt_lifecycle",
                "project_benchmark_v2_cleanup_lifecycle",
                "project_benchmark_v2_runner_events",
                "project_benchmark_v2_screen_group_lifecycles",
                "read_benchmark_v2_attempt_journal",
                "select_benchmark_v2_attempt_ledger_horizon",
            ),
        ),
        (
            "app.learn.hybrid.benchmark_v2_predictions",
            (
                "materialize_benchmark_v2_accepted_holdout_score_input_v1",
                "materialize_benchmark_v2_accepted_regression_score_input_v2",
                "project_benchmark_v2_actual_body",
                "project_benchmark_v2_actual_result",
            ),
        ),
        (
            "app.learn.hybrid.benchmark_v2_probe_authority",
            ("materialize_benchmark_v2_regression_probe_authority",),
        ),
        (
            "app.learn.hybrid.benchmark_v2_runtime",
            ("get_production_benchmark_v2_runtime",),
        ),
        (
            "app.learn.hybrid.benchmark_v2_durable_claim",
            (
                "EXACT_HOLDOUT_COMMAND",
                "IDENTITY",
                "PRODUCTION_LEDGER_ROOT",
                "SAFETY",
            ),
        ),
        (
            "app.learn.hybrid.benchmark_v2_holdout",
            (
                "AUTHORIZED_HOLDOUT_OUTPUT_ROOT",
                "_classify_holdout_attempt_events_structure_read_only",
                "_derive_holdout_cleanup_authority_read_only",
                "append_holdout_attempt_body_complete",
                "append_holdout_attempt_cleanup",
                "append_holdout_attempt_opened",
                "append_holdout_attempt_recovery_cleanup",
                "append_holdout_attempt_result",
                "claim_holdout_once",
                "holdout_attempt_events_path",
                "validate_holdout_attempt_events",
                "verify_holdout_claim_anchors_for_public_projection",
            ),
        ),
    ]


def test_probe_authority_cli_uses_exact_offline_arguments_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    bundle = {
        "artifact_id": "probe-authority/" + "a" * 64,
        "content_sha256": "b" * 64,
    }

    def materialize(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return bundle

    monkeypatch.setattr(
        runner, "materialize_benchmark_v2_regression_probe_authority", materialize
    )
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("offline action acquired Runtime")),
    )
    monkeypatch.setattr(runner, "_PROJECT_ROOT", tmp_path)
    manifest = tmp_path / "benchmark-v2-provider-manifest.json"
    accepted = tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json"
    ledger_root = tmp_path / "ledger"
    output = tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json"
    result = runner.run_cli(
        [
            "--provider-manifest", str(manifest),
            "--partition", "regression",
            "--materialize-probe-authority",
            "--regression-run-ref", str(accepted),
            "--ledger-root", str(ledger_root),
            "--output", str(output),
        ]
    )
    assert calls == [
        {
            "provider_manifest_path": manifest,
            "regression_run_ref_path": accepted,
            "ledger_root": ledger_root,
            "output_path": output,
        }
    ]
    assert result == {
        "probe_authority_ref": {
            "id": bundle["artifact_id"],
            "content_sha256": bundle["content_sha256"],
        },
        "status": "PASS",
    }
    assert "path" not in _canonical(result).decode("utf-8").casefold()


@pytest.mark.parametrize(
    "extra",
    [
        ["--providers", "omni"],
        ["--attempt-ledger", ""],
        ["--output-root", "private"],
        ["--holdout-authorization", "authorization.json"],
    ],
)
def test_probe_authority_cli_rejects_noncanonical_options_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, extra: list[str]
) -> None:
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("invalid action acquired Runtime")),
    )
    monkeypatch.setattr(runner, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_regression_probe_authority",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("invalid action materialized")),
    )
    with pytest.raises(ValueError, match="not valid"):
        runner.run_cli(
            [
                "--provider-manifest", str(tmp_path / "benchmark-v2-provider-manifest.json"),
                "--partition", "regression",
                "--materialize-probe-authority",
                "--regression-run-ref", str(tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json"),
                "--ledger-root", str(tmp_path / "ledger"),
                "--output", str(tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json"),
                *extra,
            ]
        )


def test_probe_authority_cli_rejects_holdout_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("holdout action acquired Runtime")),
    )
    monkeypatch.setattr(runner, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_regression_probe_authority",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("holdout action materialized")),
    )
    with pytest.raises(ValueError, match="regression"):
        runner.run_cli(
            [
                "--provider-manifest", str(tmp_path / "benchmark-v2-provider-manifest.json"),
                "--partition", "holdout",
                "--materialize-probe-authority",
                "--regression-run-ref", str(tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/accepted-run-ref.json"),
                "--ledger-root", str(tmp_path / "ledger"),
                "--output", str(tmp_path / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/probe-authority.json"),
            ]
        )


def _holdout_h2_input_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[str], dict[str, str], dict[str, Path]]:
    project_root = (tmp_path / "project").resolve()
    provider_manifest = (
        project_root
        / "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json"
    )
    authorization_ref_path = (
        project_root
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json"
    )
    ledger_root = (
        project_root
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger"
    )
    output_root = (
        project_root
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout"
    )
    provider_manifest.parent.mkdir(parents=True)
    provider_manifest.write_bytes(b"{}")
    authorization_ref_path.parent.mkdir(parents=True)
    ledger_root.mkdir(parents=True)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    native_ref = {
        "authorization_id": f"holdout-authorization/{claim_id}",
        "envelope_sha256": "a" * 64,
        "fixed_authorization_path": str(
            (tmp_path / "claim-root" / f"{claim_id}.authorization.json").resolve()
        ),
    }
    authorization_ref_path.write_bytes(_canonical(native_ref))
    monkeypatch.setattr(runner, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(runner, "PRODUCTION_LEDGER_ROOT", ledger_root)
    monkeypatch.setattr(runner, "AUTHORIZED_HOLDOUT_OUTPUT_ROOT", output_root)
    return (
        list(runner.EXACT_HOLDOUT_COMMAND[4:]),
        native_ref,
        {
            "project_root": project_root,
            "provider_manifest": provider_manifest,
            "authorization_ref_path": authorization_ref_path,
            "ledger_root": ledger_root,
            "output_root": output_root,
        },
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda argv: argv[:-1],
        lambda argv: argv + ["--output-root", argv[-1]],
        lambda argv: [argv[2], argv[3], *argv[:2], *argv[4:]],
        lambda argv: [*argv[:-2], "--output-root=" + argv[-1]],
        lambda argv: [*argv[:-1], argv[-1] + "/."],
        lambda argv: [*argv[:-1], str((Path.cwd() / argv[-1]).resolve())],
        lambda argv: [*argv[:-1], argv[-1].upper()],
        lambda argv: [*argv[:-1], argv[-1].replace("/", "\\")],
        lambda argv: [*argv[:-1], "%CD%/" + argv[-1]],
    ],
)
def test_holdout_h2_raw_vector_mutations_fail_before_claim_or_append(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate,
) -> None:
    argv, _, _ = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(runner, "claim_holdout_once", lambda **_kwargs: calls.append("claim"))
    monkeypatch.setattr(
        runner, "append_holdout_attempt_opened", lambda **_kwargs: calls.append("append")
    )

    with pytest.raises(ValueError, match="exact raw token vector"):
        runner._validate_holdout_actual_models_input(mutate(argv))

    assert calls == []


def test_holdout_h2_exact_raw_vector_is_cwd_independent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    unrelated_cwd = tmp_path / "unrelated-cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    assert not paths["output_root"].exists()

    validated = runner._validate_holdout_actual_models_input(argv)

    assert validated.provider_manifest_path == paths["provider_manifest"]
    assert validated.authorization_ref_path == paths["authorization_ref_path"]
    assert validated.ledger_root == paths["ledger_root"]
    assert validated.output_root == paths["output_root"]
    assert validated.authorization_ref == native_ref
    assert not paths["output_root"].exists()


def test_holdout_h2_existing_exact_ordinary_output_root_is_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, _, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    paths["output_root"].mkdir()

    validated = runner._validate_holdout_actual_models_input(argv)

    assert validated.output_root == paths["output_root"]
    assert list(paths["output_root"].iterdir()) == []


@pytest.mark.parametrize(
    "raw_builder",
    [
        lambda ref: _canonical(ref) + b"\n",
        lambda ref: json.dumps(ref, indent=2).encode("utf-8"),
        lambda ref: _canonical({**ref, "extra": "forbidden"}),
        lambda ref: b"\xff",
        lambda ref: _canonical({**ref, "envelope_sha256": "A" * 64}),
        lambda ref: _canonical({**ref, "fixed_authorization_path": "relative.json"}),
        lambda ref: _canonical(
            {
                **ref,
                "fixed_authorization_path": str(
                    Path(ref["fixed_authorization_path"]).with_name("wrong.json")
                ),
            }
        ),
    ],
)
def test_holdout_h2_authorization_ref_requires_exact_native_canonical_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_builder
) -> None:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    paths["authorization_ref_path"].write_bytes(raw_builder(native_ref))

    with pytest.raises(ValueError, match="authorization ref"):
        runner._validate_holdout_actual_models_input(argv)


def _expected_holdout_h2_open(
    *, authorization_ref: Mapping[str, str], claim_id: str, claim_ref: Mapping[str, str], attempt_dir: Path
) -> tuple[str, dict[str, object], dict[str, object]]:
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + authorization_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    attempt_ref = _sealed(
        {
            "contract_version": "benchmark_v2_holdout_attempt_ref_v1",
            "attempt_id": attempt_id,
            "authorization_ref": dict(authorization_ref),
            "claim_ref": dict(claim_ref),
            "partition": "holdout",
            "mode": "actual_models",
            "provider_id": None,
            "safety": deepcopy(runner.HOLDOUT_SAFETY),
        }
    )
    opened_payload = _sealed(
        {
            "contract_version": "benchmark_v2_holdout_attempt_opened_payload_v1",
            "attempt_ref": attempt_ref,
            "attempt_dir": str(attempt_dir),
            "status": "opened",
            "safety": deepcopy(runner.HOLDOUT_SAFETY),
        }
    )
    event = {
        "partition": "holdout",
        "sequence": 0,
        "event_kind": "opened",
        "previous_envelope_sha256": ZERO,
        "event_payload": opened_payload,
    }
    envelope = {
        "contract_version": "benchmark_v2_holdout_attempt_event_envelope_v1",
        "event": event,
        "event_sha256": hashlib.sha256(_canonical(event)).hexdigest(),
    }
    return attempt_id, attempt_ref, envelope


def test_holdout_h2_first_claim_creates_exact_attempt_and_reopens_opened_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    validated = runner._validate_holdout_actual_models_input(argv)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    claim_ref = {"id": f"holdout-claim/{claim_id}", "envelope_sha256": "b" * 64}
    expected_attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + native_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    expected_dir = paths["output_root"] / expected_attempt_id
    _, expected_ref, expected_envelope = _expected_holdout_h2_open(
        authorization_ref=native_ref,
        claim_id=claim_id,
        claim_ref=claim_ref,
        attempt_dir=expected_dir,
    )
    calls: list[str] = []

    def claim(**kwargs: object) -> dict[str, object]:
        calls.append("claim")
        assert not paths["output_root"].exists()
        assert kwargs == {
            "ledger_root": paths["ledger_root"],
            "claim_identity": runner.IDENTITY,
            "authorization_ref": native_ref,
        }
        return {
            "state": "consumed",
            "claim_id": claim_id,
            "attempt_id": expected_attempt_id,
            "claim_ref": claim_ref,
            "newly_created": True,
            "safety": runner.HOLDOUT_SAFETY,
        }

    def append(**kwargs: object) -> dict[str, object]:
        calls.append("append")
        assert expected_dir.is_dir()
        assert kwargs == {
            "ledger_root": paths["ledger_root"],
            "authorization_ref": native_ref,
            "claim_ref": claim_ref,
            "event_payload": expected_envelope["event"]["event_payload"],
        }
        return deepcopy(expected_envelope)

    def reopen(**kwargs: object) -> list[dict[str, object]]:
        calls.append("reopen")
        assert kwargs == {
            "ledger_root": paths["ledger_root"],
            "authorization_ref": native_ref,
            "claim_ref": claim_ref,
        }
        return [deepcopy(expected_envelope)]

    monkeypatch.setattr(runner, "claim_holdout_once", claim)
    monkeypatch.setattr(runner, "append_holdout_attempt_opened", append)
    monkeypatch.setattr(runner, "validate_holdout_attempt_events", reopen)
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("H2 acquired Runtime")),
    )

    opened = runner._open_holdout_actual_models_attempt(validated)

    assert calls == ["claim", "append", "reopen"]
    assert opened.validated is validated
    assert opened.attempt_ref == expected_ref
    assert opened.attempt_dir == expected_dir
    assert sorted(path.name for path in paths["output_root"].iterdir()) == [
        expected_attempt_id
    ]


@pytest.mark.parametrize(
    "claim_mutation",
    [
        {"newly_created": False},
        {"claim_ref": None},
        {"claim_ref": {"id": "holdout-claim/wrong", "envelope_sha256": "b" * 64}},
        {"attempt_id": "f" * 64},
        {"claim_id": "e" * 64},
    ],
)
def test_holdout_h2_nonunique_or_mismatched_claim_fails_before_mkdir_and_append(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    claim_mutation: dict[str, object],
) -> None:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    validated = runner._validate_holdout_actual_models_input(argv)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + native_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    claim_result: dict[str, object] = {
        "state": "consumed",
        "claim_id": claim_id,
        "attempt_id": attempt_id,
        "claim_ref": {
            "id": f"holdout-claim/{claim_id}",
            "envelope_sha256": "b" * 64,
        },
        "newly_created": True,
        "safety": runner.HOLDOUT_SAFETY,
    }
    claim_result.update(claim_mutation)
    appended: list[object] = []
    monkeypatch.setattr(runner, "claim_holdout_once", lambda **_kwargs: claim_result)
    monkeypatch.setattr(
        runner,
        "append_holdout_attempt_opened",
        lambda **kwargs: appended.append(kwargs),
    )

    with pytest.raises(ValueError, match="claim"):
        runner._open_holdout_actual_models_attempt(validated)

    assert appended == []
    assert not paths["output_root"].exists()


@pytest.mark.parametrize("mismatch_stage", ["append", "reopen"])
def test_holdout_h2_append_or_reopen_mismatch_fails_closed_without_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mismatch_stage: str
) -> None:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    validated = runner._validate_holdout_actual_models_input(argv)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    claim_ref = {"id": f"holdout-claim/{claim_id}", "envelope_sha256": "b" * 64}
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + native_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    _, _, envelope = _expected_holdout_h2_open(
        authorization_ref=native_ref,
        claim_id=claim_id,
        claim_ref=claim_ref,
        attempt_dir=paths["output_root"] / attempt_id,
    )
    monkeypatch.setattr(
        runner,
        "claim_holdout_once",
        lambda **_kwargs: {
            "state": "consumed",
            "claim_id": claim_id,
            "attempt_id": attempt_id,
            "claim_ref": claim_ref,
            "newly_created": True,
            "safety": runner.HOLDOUT_SAFETY,
        },
    )
    monkeypatch.setattr(
        runner,
        "append_holdout_attempt_opened",
        lambda **_kwargs: {} if mismatch_stage == "append" else deepcopy(envelope),
    )
    monkeypatch.setattr(
        runner,
        "validate_holdout_attempt_events",
        lambda **_kwargs: [] if mismatch_stage == "reopen" else [deepcopy(envelope)],
    )
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: (_ for _ in ()).throw(AssertionError("H2 acquired Runtime")),
    )

    with pytest.raises(ValueError, match="opened"):
        runner._open_holdout_actual_models_attempt(validated)


class _HoldoutH3Runtime(_DeterministicRuntime):
    def run_actual_screen_group(
        self,
        *,
        provider_group: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]:
        del attempt_ref
        self.calls.append(("run_actual_screen_group", provider_group["screen_group"]))
        if self.fail_actual:
            raise RuntimeError("deterministic actual failure")
        screen_group = str(provider_group["screen_group"])
        if self.projection_mismatch:
            screen_group += "-stale"
        rows = [
            {
                "case_ref": dict(case_ref),
                "arm_id": arm_id,
                "shared_parent_refs": {
                    "screen_group_ref": {
                        "id": screen_group,
                        "content_sha256": provider_group["content_sha256"],
                    }
                },
            }
            for case_ref in provider_group["case_refs"]
            for arm_id in (
                "qwen_only",
                "omni_only_discovery",
                "omni_to_qwen",
                "omni_to_qwen_vista",
            )
        ]
        return _sealed(
            {
                "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
                "partition": "holdout",
                "screen_group": screen_group,
                "request_ref": dict(provider_group["request_ref"]),
                "shared_parent_refs": {
                    "screen_group_ref": {
                        "id": screen_group,
                        "content_sha256": provider_group["content_sha256"],
                    }
                },
                "rows": rows,
                "attempt_dir": str(Path(attempt_dir)),
                **SAFETY,
            }
        )


def _install_holdout_h3_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime: _HoldoutH3Runtime,
) -> tuple[list[str], dict[str, Path], list[dict[str, object]]]:
    argv, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    claim_ref = {
        "id": f"holdout-claim/{claim_id}",
        "envelope_sha256": "b" * 64,
    }
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + native_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    ledger = paths["ledger_root"] / "holdout" / "attempt-events.jsonl"
    chain: list[dict[str, object]] = []
    order: list[str] = []
    original_load = runtime.load_provider_manifest
    original_prepare = runtime.prepare_screen_groups
    original_dispatch = runtime.run_actual_screen_group
    original_cleanup = runtime.cleanup_attempt
    original_counts = runtime.resource_counts

    def load(**kwargs: object) -> Mapping[str, object]:
        order.append("manifest_load")
        return original_load(**kwargs)

    def prepare(**kwargs: object) -> _OwnedGroups:
        order.append("prepare")
        return original_prepare(**kwargs)

    def dispatch(**kwargs: object) -> Mapping[str, object]:
        order.append("dispatch")
        return original_dispatch(**kwargs)

    def cleanup(**kwargs: object) -> Mapping[str, object]:
        order.append("cleanup_runtime")
        return original_cleanup(**kwargs)

    def counts() -> Mapping[str, int]:
        order.append("resource_counts")
        return original_counts()

    runtime.load_provider_manifest = load
    runtime.prepare_screen_groups = prepare
    runtime.run_actual_screen_group = dispatch
    runtime.cleanup_attempt = cleanup
    runtime.resource_counts = counts
    runtime.h3_order = order

    def claim(**_kwargs: object) -> dict[str, object]:
        order.append("claim")
        return {
            "state": "consumed",
            "claim_id": claim_id,
            "attempt_id": attempt_id,
            "claim_ref": claim_ref,
            "newly_created": True,
            "safety": runner.HOLDOUT_SAFETY,
        }

    def append(kind: str, **kwargs: object) -> dict[str, object]:
        order.append(f"append_{kind}")
        payload = deepcopy(kwargs["event_payload"])
        assert payload["status"] == kind
        expected_fields = {
            "opened": {"contract_version", "attempt_ref", "attempt_dir", "status", "safety", "content_sha256"},
            "body_complete": {"contract_version", "attempt_ref", "attempt_dir", "status", "body_file_ref", "safety", "content_sha256"},
            "cleanup": {"contract_version", "attempt_ref", "attempt_dir", "status", "cleanup_receipt_ref", "resource_counts", "safety", "content_sha256"},
            "result": {"contract_version", "attempt_ref", "attempt_dir", "status", "result_file_ref", "attempt_ledger_pre_result_ref", "safety", "content_sha256"},
        }
        assert set(payload) == expected_fields[kind]
        assert payload["safety"] == runner.HOLDOUT_SAFETY
        if kind in {"body_complete", "result"}:
            ref = payload[f"{kind.removesuffix('_complete')}_file_ref"]
            assert Path(ref["path"]).read_bytes()[-1:] != b"\n"
        previous = ZERO if not chain else hashlib.sha256(_canonical(chain[-1])).hexdigest()
        event = {
            "partition": "holdout",
            "sequence": len(chain),
            "event_kind": kind,
            "previous_envelope_sha256": previous,
            "event_payload": payload,
        }
        envelope = {
            "contract_version": "benchmark_v2_holdout_attempt_event_envelope_v1",
            "event": event,
            "event_sha256": hashlib.sha256(_canonical(event)).hexdigest(),
        }
        chain.append(envelope)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_bytes(b"".join(_canonical(item) + b"\n" for item in chain))
        return deepcopy(envelope)

    def reopen(**_kwargs: object) -> list[dict[str, object]]:
        order.append("reopen")
        return deepcopy(chain)

    monkeypatch.setattr(runner, "get_production_benchmark_v2_runtime", lambda: order.append("runtime_getter") or runtime)
    monkeypatch.setattr(runner, "claim_holdout_once", claim)
    monkeypatch.setattr(runner, "append_holdout_attempt_opened", lambda **kwargs: append("opened", **kwargs))
    monkeypatch.setattr(runner, "append_holdout_attempt_body_complete", lambda **kwargs: append("body_complete", **kwargs), raising=False)
    monkeypatch.setattr(runner, "append_holdout_attempt_cleanup", lambda **kwargs: append("cleanup", **kwargs), raising=False)
    monkeypatch.setattr(runner, "append_holdout_attempt_result", lambda **kwargs: append("result", **kwargs), raising=False)
    monkeypatch.setattr(runner, "validate_holdout_attempt_events", reopen)
    monkeypatch.setattr(runner, "holdout_attempt_events_path", lambda **_kwargs: ledger, raising=False)
    paths["attempt_dir"] = paths["output_root"] / attempt_id
    paths["attempt_ledger"] = ledger
    return argv, paths, chain


def test_holdout_h3_cli_validates_before_runtime_and_runs_exact_normal_chain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)

    result = runner.run_cli(argv)

    assert result == {"status": "terminal"}
    assert [item["event"]["event_kind"] for item in chain] == [
        "opened", "body_complete", "cleanup", "result"
    ]
    assert runtime.h3_order[:6] == [
        "runtime_getter", "manifest_load", "claim", "append_opened", "reopen", "prepare"
    ]
    assert runtime.h3_order.index("dispatch") > runtime.h3_order.index("prepare")
    assert runtime.h3_order.index("cleanup_runtime") < runtime.h3_order.index("resource_counts")
    assert runtime.h3_order.index("resource_counts") < runtime.h3_order.index("append_cleanup")
    assert runtime.h3_order.index("append_cleanup") < runtime.h3_order.index("append_result")
    assert [name for name, _ in runtime.calls].count("run_actual_screen_group") == 12
    prepare = next(value for name, value in runtime.calls if name == "prepare_screen_groups")
    assert prepare["partition"] == "holdout"
    body = _read_json(paths["attempt_dir"] / "body.json")
    assert body["contract_version"] == "benchmark_v2_holdout_runner_actual_body_v1"
    assert body["partition"] == "holdout"
    assert len(body["screen_group_results"]) == 12
    assert all(len(item["rows"]) == 20 for item in body["screen_group_results"])
    assert (paths["attempt_dir"] / "body.json").read_bytes() == _canonical(body)
    result_file = _read_json(paths["attempt_dir"] / "result.json")
    assert (paths["attempt_dir"] / "result.json").read_bytes() == _canonical(result_file)
    assert result_file["screen_group_count"] == 12
    assert result_file["body_ref"] == {
        "content_sha256": body["content_sha256"]
    }
    assert set(chain[2]["event"]["event_payload"]["cleanup_receipt_ref"]) == {
        "content_sha256"
    }
    raw_prefix = b"".join(_canonical(item) + b"\n" for item in chain[:3])
    expected_pre_result = {
        "contract_version": "benchmark_v2_holdout_attempt_ledger_pre_result_ref_v1",
        "id": "holdout-attempt-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-holdout-attempt-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": chain[0]["event"]["event_payload"]["attempt_ref"],
        "terminal_sequence": 2,
        "terminal_envelope_sha256": hashlib.sha256(_canonical(chain[2])).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }
    assert result_file["attempt_ledger_pre_result_ref"] == expected_pre_result
    assert chain[-1]["event"]["event_payload"]["attempt_ledger_pre_result_ref"] == expected_pre_result


def test_holdout_h3_wrong_tokens_and_invalid_manifest_precede_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, _ = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    calls: list[str] = []
    monkeypatch.setattr(runner, "get_production_benchmark_v2_runtime", lambda: calls.append("runtime"))
    with pytest.raises(ValueError, match="exact raw token vector"):
        runner.run_cli([argv[2], argv[3], *argv[:2], *argv[4:]])
    assert calls == []

    runtime.load_provider_manifest = lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid manifest"))
    monkeypatch.setattr(runner, "get_production_benchmark_v2_runtime", lambda: runtime)
    with pytest.raises(ValueError, match="invalid manifest"):
        runner.run_cli(argv)
    assert not paths["output_root"].exists()

    runtime.load_provider_manifest = lambda **_kwargs: {}
    with pytest.raises(ValueError, match="corpus lineage"):
        runner.run_cli(argv)
    assert not paths["output_root"].exists()


@pytest.mark.parametrize("mutation", ["missing_partition", "changed_partition"])
def test_holdout_h3_authorization_marker_forces_exact_validation_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, _, _ = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    if mutation == "missing_partition":
        mutated = [*argv[:2], *argv[4:]]
    else:
        mutated = list(argv)
        mutated[mutated.index("holdout")] = "regression"
    runtime_getters: list[str] = []
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: runtime_getters.append("runtime") or runtime,
    )

    with pytest.raises(ValueError, match="exact raw token vector"):
        runner.run_cli(mutated)

    assert runtime_getters == []


@pytest.mark.parametrize(
    "variant",
    ["duplicate", "duplicate_case", "missing", "cross_partition", "projection"],
)
def test_holdout_h3_rejects_group_case_partition_or_projection_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variant: str
) -> None:
    runtime = _HoldoutH3Runtime(
        group_variant="duplicate" if variant == "duplicate" else "missing" if variant == "missing" else "exact",
        projection_mismatch=variant == "projection",
    )
    if variant == "cross_partition":
        original = runtime.prepare_screen_groups
        def prepare(**kwargs: object) -> _OwnedGroups:
            groups = original(**kwargs)
            groups._groups[0] = _sealed({**groups._groups[0], "partition": "regression", "content_sha256": "discarded"})
            return groups
        runtime.prepare_screen_groups = prepare
    elif variant == "duplicate_case":
        original = runtime.prepare_screen_groups
        def prepare(**kwargs: object) -> _OwnedGroups:
            groups = original(**kwargs)
            second = deepcopy(groups._groups[1])
            second["case_refs"][0] = deepcopy(groups._groups[0]["case_refs"][0])
            second["content_sha256"] = runner._content_sha256(second)
            groups._groups[1] = second
            return groups
        runtime.prepare_screen_groups = prepare
    argv, _, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)

    with pytest.raises(ValueError):
        runner.run_cli(argv)

    assert [item["event"]["event_kind"] for item in chain] == ["opened"]
    assert any(name == "cleanup_attempt" for name, _ in runtime.calls)


@pytest.mark.parametrize("failure", ["provider", "owner_exit", "body_write", "body_append"])
def test_holdout_h3_body_path_failures_cleanup_without_normal_cleanup_or_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    runtime = _HoldoutH3Runtime(fail_actual=failure == "provider")
    if failure == "owner_exit":
        original_prepare = runtime.prepare_screen_groups
        def prepare_with_failing_exit(**kwargs: object) -> _OwnedGroups:
            owner = original_prepare(**kwargs)
            def fail_exit(*_args: object) -> None:
                raise RuntimeError("owner exit failed")
            owner.__class__ = type(
                "_FailingOwnedGroups",
                (_OwnedGroups,),
                {"__exit__": fail_exit},
            )
            return owner
        runtime.prepare_screen_groups = prepare_with_failing_exit
    argv, paths, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    if failure == "body_write":
        monkeypatch.setattr(
            runner,
            "_write_holdout_compact_json_create",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("body write failed")),
            raising=False,
        )
    elif failure == "body_append":
        monkeypatch.setattr(
            runner,
            "append_holdout_attempt_body_complete",
            lambda **_kwargs: (_ for _ in ()).throw(OSError("body append failed")),
            raising=False,
        )

    with pytest.raises((RuntimeError, OSError)):
        runner.run_cli(argv)

    assert [item["event"]["event_kind"] for item in chain] == ["opened"]
    assert (paths["attempt_dir"] / "cleanup.json").is_file()
    assert any(name == "cleanup_attempt" for name, _ in runtime.calls)


def test_holdout_h3_body_and_cleanup_failure_are_grouped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime(fail_actual=True)
    runtime.cleanup_attempt = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup failed"))
    argv, _, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)

    with pytest.raises(BaseExceptionGroup) as raised:
        runner.run_cli(argv)

    assert len(raised.value.exceptions) == 2
    assert [item["event"]["event_kind"] for item in chain] == ["opened"]


def test_holdout_h3_nonzero_or_cleanup_append_failure_blocks_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, _, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    runtime.resource_counts = lambda: {**runner._ZERO_COUNTS, "providers": 1}
    with pytest.raises(RuntimeError, match="stable zero"):
        runner.run_cli(argv)
    assert [item["event"]["event_kind"] for item in chain] == ["opened", "body_complete"]


def test_holdout_h3_cleanup_append_failure_writes_no_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    monkeypatch.setattr(
        runner,
        "append_holdout_attempt_cleanup",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("cleanup append failed")),
        raising=False,
    )
    with pytest.raises(OSError, match="cleanup append failed"):
        runner.run_cli(argv)
    assert [item["event"]["event_kind"] for item in chain] == ["opened", "body_complete"]
    assert not (paths["attempt_dir"] / "result.json").exists()


def test_holdout_h3_cleanup_receipt_wrong_reason_blocks_cleanup_and_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    original_cleanup = runtime.cleanup_attempt

    def wrong_reason_cleanup(**kwargs: object) -> Mapping[str, object]:
        receipt = dict(original_cleanup(**kwargs))
        receipt["reason"] = "different_nonempty_reason"
        receipt["content_sha256"] = runner._content_sha256(receipt)
        return receipt

    runtime.cleanup_attempt = wrong_reason_cleanup
    argv, paths, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)

    with pytest.raises(ValueError, match="reason"):
        runner.run_cli(argv)

    assert [item["event"]["event_kind"] for item in chain] == [
        "opened", "body_complete"
    ]
    assert not (paths["attempt_dir"] / "cleanup.json").exists()
    assert not (paths["attempt_dir"] / "result.json").exists()


@pytest.mark.parametrize("failure", ["write", "append", "reopen"])
def test_holdout_h3_result_failures_are_closed_without_retry_or_alternate_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain = _install_holdout_h3_boundary(monkeypatch, tmp_path, runtime)
    if failure == "write":
        original_write = runner._write_holdout_compact_json_create
        def fail_result_write(path: Path, value: Mapping[str, object]) -> None:
            if Path(path).name == "result.json":
                raise OSError("result write failed")
            original_write(path, value)
        monkeypatch.setattr(runner, "_write_holdout_compact_json_create", fail_result_write)
    elif failure == "append":
        monkeypatch.setattr(
            runner,
            "append_holdout_attempt_result",
            lambda **_kwargs: (_ for _ in ()).throw(OSError("result append failed")),
        )
    else:
        original_reopen = runner.validate_holdout_attempt_events
        def mismatched_reopen(**kwargs: object) -> list[dict[str, object]]:
            reopened = original_reopen(**kwargs)
            return reopened[:-1] if reopened and reopened[-1]["event"]["event_kind"] == "result" else reopened
        monkeypatch.setattr(runner, "validate_holdout_attempt_events", mismatched_reopen)

    with pytest.raises((OSError, ValueError)):
        runner.run_cli(argv)

    assert sorted(path.name for path in paths["output_root"].iterdir()) == [
        paths["attempt_dir"].name
    ]
    if failure != "reopen":
        assert [item["event"]["event_kind"] for item in chain] == [
            "opened", "body_complete", "cleanup"
        ]


def _holdout_h4_input_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[str], dict[str, str], dict[str, Path]]:
    _, native_ref, paths = _holdout_h2_input_fixture(monkeypatch, tmp_path)
    return (
        [
            "--cleanup-only",
            "--holdout-authorization",
            "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json",
            "--ledger-root",
            "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
        ],
        native_ref,
        paths,
    )


def _install_holdout_h4_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime: _HoldoutH3Runtime,
    *,
    tail: str = "opened",
    structure: str = "canonical",
) -> tuple[list[str], dict[str, Path], list[dict[str, object]], dict[str, object]]:
    argv, native_ref, paths = _holdout_h4_input_fixture(monkeypatch, tmp_path)
    claim_id = hashlib.sha256(_canonical(runner.IDENTITY)).hexdigest()
    claim_ref = {
        "id": f"holdout-claim/{claim_id}",
        "envelope_sha256": "b" * 64,
    }
    attempt_id = hashlib.sha256(
        (
            "benchmark-v2-holdout-attempt\0"
            + claim_id
            + "\0"
            + native_ref["envelope_sha256"]
        ).encode("utf-8")
    ).hexdigest()
    attempt_dir = paths["output_root"] / attempt_id
    attempt_dir.mkdir(parents=True)
    _, attempt_ref, opened_envelope = _expected_holdout_h2_open(
        authorization_ref=native_ref,
        claim_id=claim_id,
        claim_ref=claim_ref,
        attempt_dir=attempt_dir,
    )
    chain = [opened_envelope]

    def add(kind: str, payload: Mapping[str, object]) -> dict[str, object]:
        event = {
            "partition": "holdout",
            "sequence": len(chain),
            "event_kind": kind,
            "previous_envelope_sha256": hashlib.sha256(_canonical(chain[-1])).hexdigest(),
            "event_payload": deepcopy(dict(payload)),
        }
        envelope = {
            "contract_version": "benchmark_v2_holdout_attempt_event_envelope_v1",
            "event": event,
            "event_sha256": hashlib.sha256(_canonical(event)).hexdigest(),
        }
        chain.append(envelope)
        return envelope

    if tail == "body_complete":
        add(
            "body_complete",
            _sealed(
                {
                    "contract_version": "benchmark_v2_holdout_attempt_body_complete_payload_v1",
                    "attempt_ref": attempt_ref,
                    "attempt_dir": str(attempt_dir),
                    "status": "body_complete",
                    "body_file_ref": {
                        "path": str(attempt_dir / "body.json"),
                        "file_sha256": "c" * 64,
                        "content_sha256": "d" * 64,
                    },
                    "safety": deepcopy(runner.HOLDOUT_SAFETY),
                }
            ),
        )
    elif tail in {"cleanup", "result", "recovery_cleanup"}:
        if tail != "recovery_cleanup":
            add(
                "body_complete",
                _sealed(
                    {
                        "contract_version": "benchmark_v2_holdout_attempt_body_complete_payload_v1",
                        "attempt_ref": attempt_ref,
                        "attempt_dir": str(attempt_dir),
                        "status": "body_complete",
                        "body_file_ref": {
                            "path": str(attempt_dir / "body.json"),
                            "file_sha256": "c" * 64,
                            "content_sha256": "d" * 64,
                        },
                        "safety": deepcopy(runner.HOLDOUT_SAFETY),
                    }
                ),
            )
        add(
            tail,
            _sealed(
                {
                    "contract_version": f"benchmark_v2_holdout_attempt_{tail}_payload_v1",
                    "attempt_ref": attempt_ref,
                    "attempt_dir": str(attempt_dir),
                    "status": tail,
                    **(
                        {
                            "cleanup_receipt_ref": {"content_sha256": "e" * 64},
                            "resource_counts": deepcopy(runner._ZERO_COUNTS),
                            "recovery_reason": "cleanup_only_after_interrupted_holdout_attempt",
                        }
                        if tail == "recovery_cleanup"
                        else {}
                    ),
                    "safety": deepcopy(runner.HOLDOUT_SAFETY),
                }
            ),
        )

    ledger = paths["ledger_root"] / "holdout" / "attempt-events.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_bytes(b"".join(_canonical(item) + b"\n" for item in chain))
    calls: list[str] = []
    authority = {
        "authorization_ref": native_ref,
        "claim_ref": claim_ref,
        "attempt_ref": attempt_ref,
        "attempt_dir": attempt_dir,
    }

    def derive(**kwargs: object) -> dict[str, object]:
        calls.append("derive")
        assert kwargs == {
            "ledger_root": paths["ledger_root"],
            "authorization_ref": native_ref,
        }
        return deepcopy(authority)

    def validate(**kwargs: object) -> list[dict[str, object]]:
        calls.append("validate")
        assert kwargs["authorization_ref"] == native_ref
        assert kwargs["claim_ref"] == claim_ref
        return deepcopy(chain)

    def append_recovery(**kwargs: object) -> dict[str, object]:
        calls.append("append_recovery")
        payload = deepcopy(kwargs["event_payload"])
        assert payload["attempt_ref"] == attempt_ref
        assert payload["attempt_dir"] == str(attempt_dir)
        assert payload["status"] == "recovery_cleanup"
        assert payload["recovery_reason"] == "cleanup_only_after_interrupted_holdout_attempt"
        if chain[-1]["event"]["event_kind"] == "recovery_cleanup":
            assert chain[-1]["event"]["event_payload"] == payload
            return deepcopy(chain[-1])
        appended = add("recovery_cleanup", payload)
        ledger.write_bytes(b"".join(_canonical(item) + b"\n" for item in chain))
        return deepcopy(appended)

    monkeypatch.setattr(
        runner,
        "_derive_holdout_cleanup_authority_read_only",
        derive,
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "_classify_holdout_attempt_events_structure_read_only",
        lambda **_kwargs: structure,
        raising=False,
    )
    monkeypatch.setattr(runner, "validate_holdout_attempt_events", validate)
    monkeypatch.setattr(
        runner,
        "append_holdout_attempt_recovery_cleanup",
        append_recovery,
        raising=False,
    )
    monkeypatch.setattr(runner, "holdout_attempt_events_path", lambda **_kwargs: ledger)
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: calls.append("runtime_getter") or runtime,
    )
    paths["attempt_dir"] = attempt_dir
    paths["attempt_ledger"] = ledger
    runtime.h4_calls = calls
    return argv, paths, chain, authority


@pytest.mark.parametrize(
    "mutate",
    [
        lambda argv: argv[:-1],
        lambda argv: argv + ["--partition", "holdout"],
        lambda argv: [*argv[1:3], argv[0], *argv[3:]],
    ],
)
def test_holdout_h4_cleanup_only_exact_tokens_fail_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutate
) -> None:
    argv, _, _ = _holdout_h4_input_fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        lambda: calls.append("runtime"),
    )

    with pytest.raises((ValueError, SystemExit)):
        runner.run_cli(mutate(argv))

    assert calls == []


@pytest.mark.parametrize("tail", ["opened", "body_complete"])
def test_holdout_h4_cleanup_only_recovers_exact_authority_and_appends_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tail: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain, authority = _install_holdout_h4_boundary(
        monkeypatch, tmp_path, runtime, tail=tail
    )

    result = runner.run_cli(argv)

    assert result == {"status": "recovery_cleanup"}
    assert [item["event"]["event_kind"] for item in chain][-1] == "recovery_cleanup"
    cleanup_call = next(value for name, value in runtime.calls if name == "cleanup_attempt")
    assert cleanup_call == (
        authority["attempt_ref"]["attempt_id"],
        "cleanup_only_after_interrupted_holdout_attempt",
    )
    assert (paths["attempt_dir"] / "cleanup.json").is_file()
    assert runtime.h4_calls.index("derive") < runtime.h4_calls.index("runtime_getter")
    assert runtime.h4_calls.count("append_recovery") == 1


def test_holdout_h4_reinvocation_keeps_attempt_ledger_byte_identical(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain, _ = _install_holdout_h4_boundary(monkeypatch, tmp_path, runtime)
    runner.run_cli(argv)
    first = paths["attempt_ledger"].read_bytes()
    chain[:] = deepcopy(chain)

    runner.run_cli(argv)

    assert paths["attempt_ledger"].read_bytes() == first
    assert [item["event"]["event_kind"] for item in chain] == [
        "opened", "recovery_cleanup"
    ]


@pytest.mark.parametrize("tail", ["cleanup", "result"])
def test_holdout_h4_normal_terminal_tails_refuse_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tail: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, _, _, _ = _install_holdout_h4_boundary(
        monkeypatch, tmp_path, runtime, tail=tail
    )

    with pytest.raises(ValueError, match="terminal"):
        runner.run_cli(argv)

    assert not any(name == "cleanup_attempt" for name, _ in runtime.calls)


@pytest.mark.parametrize("failure", ["authority", "event"])
def test_holdout_h4_authority_or_event_mismatch_refuses_before_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, _, _, _ = _install_holdout_h4_boundary(monkeypatch, tmp_path, runtime)
    target = (
        "_derive_holdout_cleanup_authority_read_only"
        if failure == "authority"
        else "validate_holdout_attempt_events"
    )
    monkeypatch.setattr(
        runner,
        target,
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("authority mismatch")),
    )

    with pytest.raises(ValueError, match="authority mismatch"):
        runner.run_cli(argv)

    assert not any(name == "cleanup_attempt" for name, _ in runtime.calls)


@pytest.mark.parametrize("mutation", ["reason", "attempt", "nonzero", "error"])
def test_holdout_h4_cleanup_failure_blocks_event_and_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    runtime = _HoldoutH3Runtime()
    if mutation in {"reason", "attempt"}:
        original = runtime.cleanup_attempt
        def cleanup(**kwargs: object) -> Mapping[str, object]:
            receipt = dict(original(**kwargs))
            if mutation == "reason":
                receipt["reason"] = "wrong_reason"
            else:
                receipt["attempt_ref"] = _sealed({"attempt_id": "wrong"})
            receipt["content_sha256"] = runner._content_sha256(receipt)
            return receipt
        runtime.cleanup_attempt = cleanup
    elif mutation == "nonzero":
        runtime.resource_counts = lambda: {**runner._ZERO_COUNTS, "providers": 1}
    else:
        runtime.cleanup_attempt = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("cleanup API failed"))
    argv, paths, chain, _ = _install_holdout_h4_boundary(monkeypatch, tmp_path, runtime)

    with pytest.raises((ValueError, RuntimeError)):
        runner.run_cli(argv)

    assert [item["event"]["event_kind"] for item in chain] == ["opened"]
    assert not (paths["attempt_dir"] / "result.json").exists()


@pytest.mark.parametrize("structure", ["missing", "partial", "noncanonical", "hash_invalid"])
def test_holdout_h4_damaged_ledger_cleanup_is_nonreleasing_and_preserves_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, structure: str
) -> None:
    runtime = _HoldoutH3Runtime()
    argv, paths, chain, _ = _install_holdout_h4_boundary(
        monkeypatch, tmp_path, runtime, structure=structure
    )
    if structure == "missing":
        paths["attempt_ledger"].unlink()
        before = None
    else:
        damaged = {
            "partial": b'{"partial":',
            "noncanonical": b'{}\n',
            "hash_invalid": b'{"event_sha256":"bad"}\n',
        }[structure]
        paths["attempt_ledger"].write_bytes(damaged)
        before = damaged

    result = runner.run_cli(argv)

    assert result == {"status": "cleanup_indeterminate"}
    assert (
        not paths["attempt_ledger"].exists()
        if before is None
        else paths["attempt_ledger"].read_bytes() == before
    )
    assert chain == [chain[0]]
    assert not (paths["attempt_dir"] / "cleanup.json").exists()
    assert not (paths["attempt_dir"] / "result.json").exists()


def test_holdout_h4_nonfinite_json_ledger_runs_exact_cleanup_without_repair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.learn.hybrid import benchmark_v2_holdout as holdout

    runtime = _HoldoutH3Runtime()
    argv, paths, chain, authority = _install_holdout_h4_boundary(
        monkeypatch, tmp_path, runtime, structure="noncanonical"
    )
    damaged = b'{"contract_version":NaN}\n'
    paths["attempt_ledger"].write_bytes(damaged)
    monkeypatch.setattr(
        runner,
        "_classify_holdout_attempt_events_structure_read_only",
        lambda **_kwargs: holdout._classify_holdout_attempt_events_structure(
            paths["attempt_ledger"]
        ),
    )

    result = runner.run_cli(argv)

    assert result == {"status": "cleanup_indeterminate"}
    assert paths["attempt_ledger"].read_bytes() == damaged
    assert chain == [chain[0]]
    assert runtime.h4_calls.count("runtime_getter") == 1
    assert next(value for name, value in runtime.calls if name == "cleanup_attempt") == (
        authority["attempt_ref"]["attempt_id"],
        "cleanup_only_after_interrupted_holdout_attempt",
    )
    assert "append_recovery" not in runtime.h4_calls
    assert not (paths["attempt_dir"] / "cleanup.json").exists()
    assert not (paths["attempt_dir"] / "result.json").exists()


def test_holdout_h4_damaged_ledger_without_independent_runtime_proof_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _HoldoutH3Runtime()
    runtime.cleanup_attempt = lambda **_kwargs: (_ for _ in ()).throw(
        RuntimeError("journal proof unavailable")
    )
    argv, paths, chain, _ = _install_holdout_h4_boundary(
        monkeypatch, tmp_path, runtime, structure="partial"
    )
    damaged = b'{"partial":'
    paths["attempt_ledger"].write_bytes(damaged)

    with pytest.raises(RuntimeError, match="cleanup_indeterminate"):
        runner.run_cli(argv)

    assert paths["attempt_ledger"].read_bytes() == damaged
    assert chain == [chain[0]]
    assert not (paths["attempt_dir"] / "cleanup.json").exists()


def _install_holdout_h7_materialize_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[str], dict[str, Path], dict[str, object]]:
    runtime = _HoldoutH3Runtime()
    actual_argv, paths, chain = _install_holdout_h3_boundary(
        monkeypatch, tmp_path, runtime
    )
    runner.run_cli(actual_argv)
    attempt_ref = deepcopy(chain[0]["event"]["event_payload"]["attempt_ref"])
    claim_ref = deepcopy(attempt_ref["claim_ref"])
    provider_corpus = paths["provider_manifest"].parent / "provider-corpus.v2.json"
    provider_corpus.write_bytes(b"provider-corpus-exact-bytes")
    regression_score = _sealed(
        {
            "contract_version": "private_scorer_public_ref_v3",
            "status": "PASS",
            "score_ref": "private-score-final/" + "d" * 64,
        }
    )
    regression_score_path = (
        paths["project_root"]
        / "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json"
    )
    regression_score_path.parent.mkdir(parents=True)
    regression_score_path.write_bytes(_canonical(regression_score) + b"\n")
    journal_path = (
        paths["project_root"]
        / "runtime_state/benchmark-v2-attempts"
        / f"{attempt_ref['content_sha256']}.jsonl"
    )
    journal_path.parent.mkdir(parents=True)
    journal_event = {"phase": "terminal", "event_kind": "cleanup_complete"}
    journal_bytes = _canonical(journal_event) + b"\n"
    journal_path.write_bytes(journal_bytes)
    anchor = {
        "contract_version": "benchmark_v2_holdout_anchor_verification_result_v1",
        "authorization_ref": {
            "authorization_id": attempt_ref["authorization_ref"]["authorization_id"],
            "envelope_sha256": attempt_ref["authorization_ref"]["envelope_sha256"],
        },
        "claim_ref": claim_ref,
        "attempt_id": attempt_ref["attempt_id"],
        "authority_projection_envelopes": {"read_only": True},
        "safety": deepcopy(runner.HOLDOUT_SAFETY),
        "content_sha256": "e" * 64,
    }
    accepted = _sealed(
        {
            "contract_version": "benchmark_v2_accepted_holdout_score_input_v1",
            "partition": "holdout",
            "status": "materialized",
            **SAFETY,
        }
    )
    calls: dict[str, object] = {
        "anchor": [],
        "materializer": [],
        "journal": [],
        "forbidden": [],
        "accepted": accepted,
    }

    def verify(**kwargs: object) -> dict[str, object]:
        calls["anchor"].append(kwargs)
        return deepcopy(anchor)

    def read_journal(**kwargs: object) -> list[dict[str, object]]:
        calls["journal"].append(kwargs)
        return [deepcopy(journal_event)]

    def materialize(**kwargs: object) -> dict[str, object]:
        calls["materializer"].append(kwargs)
        return deepcopy(calls["accepted"])

    def forbidden(name: str):
        def fail(**_kwargs: object) -> object:
            calls["forbidden"].append(name)
            raise AssertionError(f"forbidden H7 call: {name}")

        return fail

    monkeypatch.setattr(
        runner,
        "verify_holdout_claim_anchors_for_public_projection",
        verify,
        raising=False,
    )
    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_accepted_holdout_score_input_v1",
        materialize,
        raising=False,
    )
    monkeypatch.setattr(
        runner, "read_benchmark_v2_attempt_journal", read_journal
    )
    monkeypatch.setattr(
        runner,
        "get_production_benchmark_v2_runtime",
        forbidden("runtime"),
    )
    for name in (
        "claim_holdout_once",
        "append_holdout_attempt_opened",
        "append_holdout_attempt_body_complete",
        "append_holdout_attempt_cleanup",
        "append_holdout_attempt_recovery_cleanup",
        "append_holdout_attempt_result",
    ):
        monkeypatch.setattr(runner, name, forbidden(name), raising=False)

    output_path = paths["output_root"] / "run-ref.json"
    argv = [
        "--provider-manifest",
        "tests/fixtures/portfolio_hybrid_v1_1/benchmark-v2-provider-manifest.json",
        "--partition",
        "holdout",
        "--materialize-score-input",
        "--holdout-authorization",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout-authorization.json",
        "--regression-score-ref",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/regression/score-ref.json",
        "--ledger-root",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2-ledger",
        "--output",
        "runtime_state/portfolio-hybrid-v1-1/benchmark-v2/holdout/run-ref.json",
    ]
    paths.update(
        {
            "provider_corpus": provider_corpus,
            "regression_score": regression_score_path,
            "journal": journal_path,
            "output": output_path,
        }
    )
    calls["attempt_ref"] = attempt_ref
    calls["anchor_result"] = anchor
    return argv, paths, calls


def _h7_evidence_snapshot(paths: Mapping[str, Path]) -> dict[str, bytes]:
    names = (
        "provider_manifest",
        "provider_corpus",
        "authorization_ref_path",
        "attempt_ledger",
        "regression_score",
        "journal",
    )
    result = {name: paths[name].read_bytes() for name in names}
    for name in ("body.json", "cleanup.json", "result.json"):
        result[name] = (paths["attempt_dir"] / name).read_bytes()
    return result


def test_holdout_h7_materialize_is_read_only_raw_exact_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    before = _h7_evidence_snapshot(paths)

    first = runner.run_cli(argv)
    first_bytes = paths["output"].read_bytes()
    second = runner.run_cli(argv)

    assert first == second == calls["accepted"]
    assert first_bytes == _canonical(first) + b"\n"
    assert paths["output"].read_bytes() == first_bytes
    assert _h7_evidence_snapshot(paths) == before
    assert calls["forbidden"] == []
    assert len(calls["anchor"]) == 2
    assert calls["anchor"][0] == {
        "authorization_ref": calls["attempt_ref"]["authorization_ref"],
        "ledger_root": paths["ledger_root"],
    }
    assert len(calls["materializer"]) == 2
    trusted = calls["materializer"][0]
    assert trusted["attempt_events_jsonl_bytes"] == before["attempt_ledger"]
    assert trusted["attempt_events"] == _read_chain(paths["attempt_ledger"])
    assert trusted["attempt_journal_jsonl_bytes"] == before["journal"]
    assert trusted["attempt_journal_events"] == [
        {"phase": "terminal", "event_kind": "cleanup_complete"}
    ]
    assert trusted["actual_body_bytes"] == before["body.json"]
    assert trusted["cleanup_receipt_bytes"] == before["cleanup.json"]
    assert trusted["actual_result_bytes"] == before["result.json"]
    assert trusted["provider_manifest_bytes"] == before["provider_manifest"]
    assert trusted["provider_corpus_bytes"] == before["provider_corpus"]
    assert trusted["native_authorization_ref"] == calls["attempt_ref"][
        "authorization_ref"
    ]
    assert trusted["holdout_anchor_verification_result"] == calls["anchor_result"]
    score_raw = before["regression_score"]
    assert trusted["regression_score_precondition_envelope"] == {
        "ref": {
            "contract_version": "private_scorer_public_ref_v3",
            "file_sha256": hashlib.sha256(score_raw).hexdigest(),
            "content_sha256": _read_json(paths["regression_score"])[
                "content_sha256"
            ],
        },
        "canonical_bytes_b64": base64.b64encode(score_raw[:-1]).decode("ascii"),
    }
    serialized = json.dumps(first, sort_keys=True)
    assert str(paths["project_root"]) not in serialized
    assert "fixed_authorization_path" not in serialized


def test_holdout_h7_emitted_compact_bytes_pass_h6_accepted_input_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from app.learn.hybrid import benchmark_scorer_v2 as scorer
    from tests import test_portfolio_hybrid_v1_1_benchmark_v2_scoring as scoring

    release_inputs = scoring.task10_release_inputs.__wrapped__(tmp_path_factory)
    h5_accepted = scoring.h5_accepted_holdout.__wrapped__(
        tmp_path_factory, release_inputs
    )
    accepted, release = scoring.h6_accepted_holdout.__wrapped__(
        h5_accepted, release_inputs
    )
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    calls["accepted"] = accepted

    emitted = runner.run_cli(argv)
    raw = paths["output"].read_bytes()

    assert emitted == accepted
    assert raw == _canonical(accepted) + b"\n"
    validated, _, _ = scorer._validate_accepted_score_input(
        json.loads(raw.decode("utf-8")), raw=raw, release=release
    )
    assert validated == accepted


@pytest.mark.parametrize(
    "mutation",
    (
        "attempt_ledger",
        "output_root",
        "alternate_output",
        "provider_absolute",
        "ledger_backslash",
        "output_dot",
        "missing_partition",
        "changed_partition",
        "authorization_case",
        "score_dot",
    ),
)
def test_holdout_h7_materialize_rejects_forbidden_or_path_alias_before_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    changed = list(argv)
    if mutation == "attempt_ledger":
        changed += ["--attempt-ledger", str(paths["attempt_ledger"])]
    elif mutation == "output_root":
        changed += ["--output-root", str(paths["output_root"])]
    elif mutation == "alternate_output":
        changed[-1] = changed[-1].replace("run-ref.json", "other.json")
    elif mutation == "provider_absolute":
        changed[1] = str(paths["provider_manifest"])
    elif mutation == "ledger_backslash":
        changed[-3] = changed[-3].replace("/", "\\")
    elif mutation == "output_dot":
        changed[-1] += "/."
    elif mutation == "missing_partition":
        changed = [*changed[:2], *changed[4:]]
    elif mutation == "changed_partition":
        changed[3] = "regression"
    elif mutation == "authorization_case":
        changed[6] = changed[6].upper()
    else:
        changed[8] += "/."
    before = _h7_evidence_snapshot(paths)

    with pytest.raises(ValueError, match="exact raw token vector"):
        runner.run_cli(changed)

    assert calls["anchor"] == []
    assert calls["materializer"] == []
    assert calls["forbidden"] == []
    assert not paths["output"].exists()
    assert _h7_evidence_snapshot(paths) == before


@pytest.mark.parametrize(
    "unknown_flag", ("--actual-body", "--actual-result", "--attempt-journal")
)
def test_holdout_h7_materialize_unknown_evidence_path_flags_remain_argparse_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, unknown_flag: str
) -> None:
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    before = _h7_evidence_snapshot(paths)

    with pytest.raises(SystemExit):
        runner.run_cli([*argv, unknown_flag, str(tmp_path / "injected")])

    assert calls["anchor"] == []
    assert calls["materializer"] == []
    assert calls["forbidden"] == []
    assert not paths["output"].exists()
    assert _h7_evidence_snapshot(paths) == before


def test_holdout_h7_materialize_validation_failure_is_zero_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    before = _h7_evidence_snapshot(paths)
    monkeypatch.setattr(
        runner,
        "materialize_benchmark_v2_accepted_holdout_score_input_v1",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid raw evidence")),
        raising=False,
    )

    with pytest.raises(ValueError, match="invalid raw evidence"):
        runner.run_cli(argv)

    assert len(calls["anchor"]) == 1
    assert calls["forbidden"] == []
    assert not paths["output"].exists()
    assert _h7_evidence_snapshot(paths) == before


def test_holdout_h7_materialize_conflicting_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, paths, _ = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    runner.run_cli(argv)
    paths["output"].write_bytes(b"conflicting-existing-bytes")
    before = _h7_evidence_snapshot(paths)

    with pytest.raises(ValueError, match="differs from authoritative bytes"):
        runner.run_cli(argv)

    assert paths["output"].read_bytes() == b"conflicting-existing-bytes"
    assert _h7_evidence_snapshot(paths) == before


def test_holdout_h7_materialize_does_not_select_alternate_attempt_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, paths, calls = _install_holdout_h7_materialize_boundary(
        monkeypatch, tmp_path
    )
    alternate = paths["output_root"] / ("f" * 64)
    alternate.mkdir()
    for name in ("body.json", "cleanup.json", "result.json"):
        (alternate / name).write_bytes((paths["attempt_dir"] / name).read_bytes())
    for name in ("body.json", "cleanup.json", "result.json"):
        (paths["attempt_dir"] / name).unlink()

    with pytest.raises(ValueError, match="fixed file is missing"):
        runner.run_cli(argv)

    assert calls["materializer"] == []
    assert calls["forbidden"] == []
    assert not paths["output"].exists()


def test_holdout_h7_materialize_static_call_surface_is_read_only_h5_only() -> None:
    source_path = Path(runner.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_materialize_holdout_score_input"
    )
    calls = {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "materialize_benchmark_v2_accepted_holdout_score_input_v1" in calls
    assert "verify_holdout_claim_anchors_for_public_projection" in calls
    assert "holdout_attempt_events_path" in calls
    assert "validate_holdout_attempt_events" in calls
    assert "read_benchmark_v2_attempt_journal" in calls
    assert calls.isdisjoint(
        {
            "get_production_benchmark_v2_runtime",
            "claim_holdout_once",
            "append_holdout_attempt_opened",
            "append_holdout_attempt_body_complete",
            "append_holdout_attempt_cleanup",
            "append_holdout_attempt_recovery_cleanup",
            "append_holdout_attempt_result",
        }
    )
    assert not any(name.startswith("project_benchmark_v2_") for name in calls)
