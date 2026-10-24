"""Real maintained stdio/host lifecycle; no capture, model or desktop input."""
import asyncio
import gc
import os
from pathlib import Path

import pytest

from app.runtime_lifecycle import InstallationMaintenance, RuntimeBusyError
from app.runtime_task_ledger import _entry, assert_settled
from scripts.learning_benchmark_client import LearningBenchmarkClient

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows Runtime host required")
def test_real_stdio_host_blocks_update_until_verified_cleanup(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_GUI_DECISION_PROFILE", raising=False)
    async def run():
        client = LearningBenchmarkClient(root=ROOT, data_root=tmp_path / "data", evidence_dir=tmp_path / "evidence",
            recognition_source="agent_current", ready_timeout=40, cleanup_timeout=40, poll_interval=.05)
        async with client:
            status = await client._invoke("instant_status", {})
            assert status["phase"] == "ready" and status["host_alive"] is True
            session = Path(status["session_directory"])
            assert _entry(ROOT, session).is_file()
            with pytest.raises(RuntimeBusyError):
                with InstallationMaintenance(ROOT):
                    pass
        assert client.status["cleanup_verified"] is True
        assert not _entry(ROOT, session).exists()
    asyncio.run(run())
    gc.collect()
    with InstallationMaintenance(ROOT):
        assert assert_settled(ROOT)["settled"] is True
