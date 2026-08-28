from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest

from scripts import run_portfolio_hybrid_v1_1_benchmark_v2 as runner


ZERO = "0" * 64
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


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
    ) -> None:
        self.fail_actual = fail_actual
        self.group_variant = group_variant
        self.cleanup_mutation = cleanup_mutation
        self.projection_mismatch = projection_mismatch
        self.calls: list[tuple[str, object]] = []
        self.owned_groups: list[_OwnedGroups] = []

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
def test_lifecycle_probe_waits_for_request_in_flight_then_triggers_and_cleans(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    flag: str,
    probe_kind: str,
) -> None:
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
        assert begin < read < trigger
    assert all(value == 0 for value in runtime.resource_counts().values())


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


def test_runner_production_import_surface_is_only_the_runtime_getter() -> None:
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
            "app.learn.hybrid.benchmark_v2_runtime",
            ("get_production_benchmark_v2_runtime",),
        )
    ]
