from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.agent.fresh_learning_archive import (
    FreshLearningObservationArchive,
    FreshLearningObservationArchiveError,
)
from test_formal_fresh_learning_observation import _owner


def _packet(root: Path):
    return _owner(root).observe(target_window_handle=4242, target_process_id=9001)


def _scope() -> dict[str, str]:
    return {"connection_id": "fresh-connection", "task_id": "fresh-task", "segment_id": "fresh-segment"}


def test_record_reopen_returns_the_exact_owner_packet_and_private_reference(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture")
    archive = FreshLearningObservationArchive(tmp_path / "archive")
    scope = _scope()

    reference = archive.record(packet, **scope)
    reopened = FreshLearningObservationArchive(tmp_path / "archive").read(reference, **scope)

    assert reference["contract_version"] == "fresh_learning_source_ref_v1"
    assert set(reference) == {"contract_version", "source_id", "content_sha256", "capture_id", "screenshot_sha256"}
    assert all("path" not in key for key in reference)
    assert reopened.png_bytes == packet.png_bytes
    assert reopened.evidence_json == packet.evidence_json
    assert reopened.evidence()["capture"]["viewport_size"] == {"width": 160, "height": 100}


def test_archive_rejects_scope_reference_and_packet_evidence_mismatch(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture")
    archive = FreshLearningObservationArchive(tmp_path / "archive")
    scope = _scope()
    reference = archive.record(packet, **scope)

    with pytest.raises(FreshLearningObservationArchiveError, match="scope"):
        archive.read(reference, connection_id="other", task_id=scope["task_id"], segment_id=scope["segment_id"])
    changed = json.loads(packet.evidence_json.decode("utf-8"))
    changed["capture"]["screenshot_sha256"] = "0" * 64
    from app.agent.fresh_learning_observation import FreshLearningObservationPacket
    bad_packet = FreshLearningObservationPacket(
        png_bytes=packet.png_bytes,
        evidence_json=json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    )
    with pytest.raises(FreshLearningObservationArchiveError, match="screenshot"):
        archive.record(bad_packet, **scope)


def test_archive_detects_corrupt_source_and_png_on_read(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture")
    archive = FreshLearningObservationArchive(tmp_path / "archive")
    scope = _scope()
    reference = archive.record(packet, **scope)
    root = archive.project_root / "runtime_state" / "fresh-learning-v1"
    (root / "records" / f"{reference['source_id']}.json").write_bytes(b"{}")
    with pytest.raises(FreshLearningObservationArchiveError, match="record"):
        archive.read(reference, **scope)

    archive = FreshLearningObservationArchive(tmp_path / "archive-png")
    reference = archive.record(packet, **scope)
    png = archive.project_root / "runtime_state" / "fresh-learning-v1" / "png" / f"{reference['screenshot_sha256']}.png"
    png.write_bytes(b"not a png")
    with pytest.raises(FreshLearningObservationArchiveError, match="PNG"):
        archive.read(reference, **scope)


def test_archive_enforces_png_and_total_budget_without_eviction(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture")
    scope = _scope()
    with pytest.raises(FreshLearningObservationArchiveError, match="PNG budget"):
        FreshLearningObservationArchive(tmp_path / "small-png", max_png_bytes=len(packet.png_bytes) - 1).record(packet, **scope)

    archive = FreshLearningObservationArchive(tmp_path / "small-total", max_total_bytes=len(packet.png_bytes) - 1)
    with pytest.raises(FreshLearningObservationArchiveError, match="total budget"):
        archive.record(packet, **scope)
    assert not list((archive.project_root / "runtime_state" / "fresh-learning-v1" / "png").glob("*.png"))


def _committed_payload_bytes(archive: FreshLearningObservationArchive) -> int:
    return sum(
        path.stat().st_size
        for directory in (archive.png_root, archive.records_root)
        for path in directory.iterdir()
        if path.is_file()
    )


def test_total_budget_counts_the_immutable_evidence_envelope_on_first_write(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture")
    assert len(packet.evidence_json) > len(packet.png_bytes)
    archive = FreshLearningObservationArchive(
        tmp_path / "archive", max_total_bytes=len(packet.png_bytes) + 1,
    )

    with pytest.raises(FreshLearningObservationArchiveError, match="total budget"):
        archive.record(packet, **_scope())

    assert _committed_payload_bytes(archive) == 0


def test_total_budget_counts_a_new_record_when_png_is_already_present(tmp_path: Path) -> None:
    packet = _packet(tmp_path / "capture-one")
    same_png_new_source = _packet(tmp_path / "capture-two")
    assert packet.png_bytes == same_png_new_source.png_bytes
    archive = FreshLearningObservationArchive(tmp_path / "archive")
    scope = _scope()
    reference = archive.record(packet, **scope)
    committed = _committed_payload_bytes(archive)
    capped = FreshLearningObservationArchive(tmp_path / "archive", max_total_bytes=committed + 1)

    assert capped.record(packet, **scope) == reference
    with pytest.raises(FreshLearningObservationArchiveError, match="total budget"):
        capped.record(
            same_png_new_source,
            connection_id=scope["connection_id"],
            task_id=scope["task_id"],
            segment_id="fresh-segment-two",
        )
    assert _committed_payload_bytes(capped) == committed
