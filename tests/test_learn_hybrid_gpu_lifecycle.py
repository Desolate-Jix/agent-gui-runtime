from __future__ import annotations

from copy import deepcopy

import pytest

from app.learn.hybrid.gpu_lifecycle import (
    assert_next_provider_safe_to_start,
    release_hybrid_provider,
)


def _inventory(provider: str, **overrides) -> dict:
    value = {
        "contract_version": "hybrid_provider_process_inventory_v1",
        "provider": provider,
        "release_status": "verified",
        "termination_reason": "completed",
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {
            "contract_version": "deterministic_cleanup_evidence_v1",
            "status": "verified",
        },
    }
    value.update(overrides)
    return value


def test_next_model_cannot_start_until_previous_cleanup_is_verified() -> None:
    with pytest.raises(RuntimeError, match="previous provider cleanup is not verified"):
        assert_next_provider_safe_to_start(
            {"provider": "qwen", "cleanup_status": "indeterminate"},
            "vista",
        )


def test_simultaneous_gpu_provider_residency_is_rejected() -> None:
    inventory = _inventory(
        "omni",
        provider_processes_after=[{"provider": "qwen", "pid": 4202}],
    )
    with pytest.raises(RuntimeError, match="provider process remains resident"):
        release_hybrid_provider("omni", process_inventory=inventory)


@pytest.mark.parametrize(
    ("release_status", "termination_reason"),
    [
        ("timeout", "timeout"),
        ("cancelled", "cancellation"),
        ("outer_worker_terminated", "outer_worker_termination"),
        ("failed", "cleanup_failed"),
    ],
)
def test_unverified_termination_never_mints_cleanup_receipt(
    release_status: str,
    termination_reason: str,
) -> None:
    with pytest.raises(RuntimeError, match="cleanup is not verified"):
        release_hybrid_provider(
            "qwen",
            process_inventory=_inventory(
                "qwen",
                release_status=release_status,
                termination_reason=termination_reason,
            ),
        )


def test_orphan_descendant_or_helper_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="orphan descendant"):
        release_hybrid_provider(
            "vista",
            process_inventory=_inventory("vista", orphan_descendant_pids=[9911]),
        )
    with pytest.raises(RuntimeError, match="helper process remains resident"):
        release_hybrid_provider(
            "vista",
            process_inventory=_inventory(
                "vista", helper_processes_after=[{"pid": 9912}]
            ),
        )


def test_listener_or_lease_residue_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="listener remains active"):
        release_hybrid_provider(
            "qwen", process_inventory=_inventory("qwen", active_listeners_after=[13240])
        )
    with pytest.raises(RuntimeError, match="lease file remains"):
        release_hybrid_provider(
            "qwen", process_inventory=_inventory("qwen", lease_files_after=["lease.json"])
        )


def test_failed_cleanup_can_recover_without_stale_coordinator_state() -> None:
    failed = _inventory("omni", release_status="failed")
    with pytest.raises(RuntimeError):
        release_hybrid_provider("omni", process_inventory=failed)

    receipt = release_hybrid_provider("omni", process_inventory=_inventory("omni"))
    assert_next_provider_safe_to_start(receipt, "qwen")


def test_cleanup_does_not_mutate_provider_assets(tmp_path) -> None:
    asset = tmp_path / "weights.bin"
    asset.write_bytes(b"immutable-provider-assets")
    before = asset.read_bytes()
    inventory = _inventory("vista")
    snapshot = deepcopy(inventory)

    release_hybrid_provider("vista", process_inventory=inventory)

    assert asset.read_bytes() == before
    assert inventory == snapshot


def test_sequence_is_exact_and_cannot_skip_or_reverse_provider_order() -> None:
    omni = release_hybrid_provider("omni", process_inventory=_inventory("omni"))
    assert_next_provider_safe_to_start(omni, "qwen")
    with pytest.raises(RuntimeError, match="provider transition is invalid"):
        assert_next_provider_safe_to_start(omni, "vista")
    qwen = release_hybrid_provider("qwen", process_inventory=_inventory("qwen"))
    assert_next_provider_safe_to_start(qwen, "vista")
    vista = release_hybrid_provider("vista", process_inventory=_inventory("vista"))
    assert_next_provider_safe_to_start(vista, "review")


def test_repeated_deterministic_runs_leave_zero_pid_listener_or_lease() -> None:
    for _ in range(5):
        omni = release_hybrid_provider("omni", process_inventory=_inventory("omni"))
        assert_next_provider_safe_to_start(omni, "qwen")
        qwen = release_hybrid_provider("qwen", process_inventory=_inventory("qwen"))
        assert_next_provider_safe_to_start(qwen, "vista")
        vista = release_hybrid_provider("vista", process_inventory=_inventory("vista"))
        assert_next_provider_safe_to_start(vista, "review")
        for receipt in (omni, qwen, vista):
            assert receipt["orphan_provider_pids"] == []
            assert receipt["orphan_helper_pids"] == []
            assert receipt["active_listeners"] == []
            assert receipt["lease_files_remaining"] == []
