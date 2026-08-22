from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace

from app.operation.screen_reading import uia_provider as provider_module


def _snapshot(handle: int) -> dict:
    return {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": "ok",
        "window": {
            "handle": handle,
            "process_id": handle + 100,
            "bbox": {"x": 0, "y": 0, "w": 320, "h": 200},
        },
        "control_count": 1,
        "controls": [{"control_id": f"control-{handle}"}],
    }


def test_pinned_snapshot_is_private_deep_copied_and_restores_fallback(monkeypatch) -> None:
    provider = provider_module.WindowsUIAProvider()
    fallback = _snapshot(99)
    monkeypatch.setattr(
        provider_module.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(handle=99),
    )
    monkeypatch.setattr(provider, "snapshot_window", lambda *_args, **_kwargs: deepcopy(fallback))
    supplied = _snapshot(42)

    with provider_module.pinned_uia_snapshot(supplied):
        supplied["controls"][0]["control_id"] = "caller-mutated"
        first = provider.snapshot_bound_window()
        first["controls"][0]["control_id"] = "consumer-mutated"
        second = provider.snapshot_bound_window()

    assert second["controls"][0]["control_id"] == "control-42"
    assert provider.snapshot_bound_window() == fallback


def test_pinned_snapshot_is_isolated_between_concurrent_contexts() -> None:
    provider = provider_module.WindowsUIAProvider()
    barrier = Barrier(2)

    def read(handle: int) -> int:
        with provider_module.pinned_uia_snapshot(_snapshot(handle)):
            barrier.wait()
            return int(provider.snapshot_bound_window()["window"]["handle"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(read, [11, 22])) == [11, 22]
