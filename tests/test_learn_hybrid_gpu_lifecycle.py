from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.learn.hybrid.gpu_lifecycle import (
    assert_next_provider_safe_to_start,
    release_hybrid_provider,
)


def _lineage(run_id: str = "run-a", revision: int = 7) -> dict:
    return {
        "run_id": run_id,
        "workflow_revision": revision,
        "operation_id": "operation-a",
        "stage": "screen_understanding",
        "stage_execution_id": "run-a:screen_understanding:operation-a",
    }


class _FakeCleanupObserver:
    def __init__(self, provider: str, *, lineage: dict | None = None) -> None:
        self.provider = provider
        self.lineage = deepcopy(lineage or _lineage())
        process_identity = {"pid": 4100, "create_time_ns": 123456789}
        if provider == "omni":
            self.identity = {
                "provider_invocation_id": "invocation/omni-cleanup-1",
                "provider_receipt_ref": {
                    "id": "receipt/omni-cleanup-1",
                    "content_sha256": "a" * 64,
                },
                "process_identity": process_identity,
            }
        elif provider == "qwen":
            self.identity = {
                "lease_id": "qwen-lease-1",
                "incarnation_id": "qwen-incarnation-1",
                "profile_id": "qwen-profile",
                "server_process_identity": process_identity,
            }
        else:
            self.identity = {
                "incarnation_id": "vista-incarnation-1",
                "profile_id": "vista-profile",
                "process_identities": [process_identity],
            }
        self.release_status = "verified"
        self.provider_processes: list[dict] = []
        self.helpers: list[dict] = []
        self.descendants: list[int] = []
        self.listeners: list[dict] = []
        self.leases: list[str] = []
        self.observations = 0

    def __call__(self, provider: str) -> dict:
        self.observations += 1
        assert provider == self.provider
        return {
            "contract_version": "hybrid_provider_process_inventory_v2",
            "provider": provider,
            "observer_contract": f"hybrid_{provider}_cleanup_observer_v1",
            "release_status": self.release_status,
            "termination_reason": "completed" if self.release_status == "verified" else "cleanup_failed",
            "lineage": deepcopy(self.lineage),
            "provider_lease_identity": deepcopy(self.identity),
            "predecessor_sha256": "1" * 64,
            "provider_result_sha256": "2" * 64,
            "provider_processes_after": deepcopy(self.provider_processes),
            "helper_processes_after": deepcopy(self.helpers),
            "orphan_descendant_pids": deepcopy(self.descendants),
            "active_listeners_after": deepcopy(self.listeners),
            "lease_files_after": deepcopy(self.leases),
            "source_cleanup_evidence": {
                "contract_version": f"fake_{provider}_cleanup_evidence_v1",
                "status": "verified" if self.release_status == "verified" else "failed",
                "observed_identity": deepcopy(self.identity),
            },
        }


def _receipt(provider: str, *, lineage: dict | None = None) -> dict:
    return release_hybrid_provider(
        provider,
        process_inventory=_FakeCleanupObserver(provider, lineage=lineage),
    )


def test_next_model_cannot_start_until_previous_cleanup_is_verified() -> None:
    with pytest.raises(RuntimeError, match="previous provider cleanup is not verified"):
        assert_next_provider_safe_to_start(
            {"provider": "qwen", "cleanup_status": "indeterminate"},
            "vista",
            expected_lineage=_lineage(),
            expected_provider_result_sha256="2" * 64,
        )


def test_simultaneous_gpu_provider_residency_is_observed_and_rejected() -> None:
    observer = _FakeCleanupObserver("omni")
    observer.provider_processes = [{"pid": 4202, "create_time_ns": 333}]
    with pytest.raises(RuntimeError, match="provider process remains resident"):
        release_hybrid_provider("omni", process_inventory=observer)
    assert observer.observations == 1


def test_caller_supplied_empty_inventory_cannot_mint_receipt() -> None:
    with pytest.raises(TypeError, match="observed server-side"):
        release_hybrid_provider("omni", process_inventory={})  # type: ignore[arg-type]


def test_provider_specific_cleanup_identity_is_closed_and_exact() -> None:
    observer = _FakeCleanupObserver("vista")
    observer.identity = {
        "incarnation_id": "vista-fabricated",
        "profile_id": "vista-profile",
        "process_identities": [],
    }
    with pytest.raises(ValueError, match="VISTA cleanup identity is invalid"):
        release_hybrid_provider("vista", process_inventory=observer)


@pytest.mark.parametrize("release_status", ["timeout", "cancelled", "outer_worker_terminated", "failed"])
def test_unverified_termination_never_mints_cleanup_receipt(release_status: str) -> None:
    observer = _FakeCleanupObserver("qwen")
    observer.release_status = release_status
    with pytest.raises(RuntimeError, match="cleanup is not verified"):
        release_hybrid_provider("qwen", process_inventory=observer)


def test_orphan_descendant_helper_listener_and_lease_are_observer_failures() -> None:
    for field, value, message in (
        ("descendants", [9911], "orphan descendant"),
        ("helpers", [{"pid": 9912}], "helper process"),
        ("listeners", [{"port": 13240, "pid": 9913}], "listener"),
        ("leases", ["lease.json"], "lease file"),
    ):
        observer = _FakeCleanupObserver("vista")
        setattr(observer, field, value)
        with pytest.raises(RuntimeError, match=message):
            release_hybrid_provider("vista", process_inventory=observer)


def test_cleanup_receipt_rejects_cross_run_stale_and_result_replay() -> None:
    receipt = _receipt("omni")
    with pytest.raises(RuntimeError, match="lineage mismatch"):
        assert_next_provider_safe_to_start(
            receipt, "qwen", expected_lineage=_lineage("run-b"),
            expected_provider_result_sha256="2" * 64,
        )
    with pytest.raises(RuntimeError, match="predecessor result mismatch"):
        assert_next_provider_safe_to_start(
            receipt, "qwen", expected_lineage=_lineage(),
            expected_provider_result_sha256="3" * 64,
        )


def test_sequence_requires_active_lineage_and_exact_order() -> None:
    omni = _receipt("omni")
    with pytest.raises(RuntimeError, match="active Hybrid lineage"):
        assert_next_provider_safe_to_start(omni, "qwen")
    assert_next_provider_safe_to_start(
        omni, "qwen", expected_lineage=_lineage(),
        expected_provider_result_sha256="2" * 64,
    )
    with pytest.raises(RuntimeError, match="transition is invalid"):
        assert_next_provider_safe_to_start(
            omni, "vista", expected_lineage=_lineage(),
            expected_provider_result_sha256="2" * 64,
        )


def test_repeated_deterministic_runs_observe_exact_identity_and_zero_residue() -> None:
    for index in range(5):
        lineage = _lineage(f"run-{index}", index)
        lineage["stage_execution_id"] = f"run-{index}:screen_understanding:operation-a"
        previous = None
        for provider, next_provider in (("omni", "qwen"), ("qwen", "vista"), ("vista", "review")):
            observer = _FakeCleanupObserver(provider, lineage=lineage)
            if provider == "omni":
                observer.identity["provider_invocation_id"] = f"invocation/omni-{index}"
                observer.identity["provider_receipt_ref"] = {
                    "id": f"receipt/omni-{index}",
                    "content_sha256": f"{index:x}" * 64,
                }
            else:
                observer.identity["incarnation_id"] = f"{provider}-incarnation-{index}"
            receipt = release_hybrid_provider(provider, process_inventory=observer)
            assert observer.observations == 1
            assert receipt["provider_lease_identity"] == observer.identity
            assert_next_provider_safe_to_start(
                receipt, next_provider, expected_lineage=lineage,
                expected_provider_result_sha256="2" * 64,
            )
            previous = receipt
        assert previous["orphan_provider_pids"] == []


def test_cleanup_coordination_does_not_mutate_model_assets(tmp_path: Path) -> None:
    assets = {
        "omni": tmp_path / "omni.weights",
        "qwen": tmp_path / "qwen.gguf",
        "vista": tmp_path / "vista.weights",
    }
    for provider, path in assets.items():
        path.write_bytes(f"immutable-{provider}-asset".encode("utf-8"))
    before = {provider: path.read_bytes() for provider, path in assets.items()}

    for provider in ("omni", "qwen", "vista"):
        release_hybrid_provider(
            provider,
            process_inventory=_FakeCleanupObserver(provider),
        )

    assert {provider: path.read_bytes() for provider, path in assets.items()} == before
