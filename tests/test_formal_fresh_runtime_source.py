from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.fresh_learning_archive import FreshLearningObservationArchiveError
from app.agent.fresh_learning_runtime_source import (
    FreshLearningRuntimeSource,
    FreshLearningRuntimeSourceError,
    load_fresh_learning_runtime_source,
    reload_fresh_learning_runtime_source,
)
from app.agent_link.contracts import AgentLinkError
from tests.test_formal_fresh_graph_source import REVIEWER, _stage
from tests.test_formal_fresh_learning_observation import _owner


def _loaded(root):
    host, connection, segment, packet, _args, staged = _stage(root)
    scope = {
        "connection_id": connection["connection_id"],
        "task_id": connection["task_id"],
        "segment_id": segment["segment_id"],
        "batch_id": staged["batch_id"],
    }
    return host, connection, segment, packet, staged, scope


def test_loads_committed_fresh_packet_with_immutable_asset_free_reference(tmp_path):
    host, _connection, _segment, packet, staged, scope = _loaded(tmp_path)
    try:
        source = load_fresh_learning_runtime_source(host.fresh_learning, **scope)
        assert isinstance(source, FreshLearningRuntimeSource)
        assert source.project_root == (tmp_path / "review").resolve()
        assert source.packet.png_bytes == packet.png_bytes
        assert source.packet.evidence_json == packet.evidence_json
        reference = source.reference()
        assert reference["contract_version"] == "fresh_learning_runtime_source_v1"
        assert reference["source_kind"] == "fresh_learning"
        assert {key: reference[key] for key in scope} == scope
        assert reference["source_metadata"] == staged["source"]
        assert reference["application_identity"] == {"kind": "web", "canonical_origin": "https://fresh.example"}
        assert reference["target_window_handle"] == 4242
        assert reference["target_process_id"] == 9001
        assert len(reference["source_sha256"]) == 64
        assert not {"asset_id", "reviewed_revision_hash", "workflow_id", "destination_status", "gate_decision"} & set(reference)
        reference["source_metadata"]["reference"]["capture_id"] = "changed"
        assert source.reference()["source_metadata"] == staged["source"]
        assert reload_fresh_learning_runtime_source(host.fresh_learning, source) == source
    finally:
        host.close()


def test_reload_rejects_archive_png_tamper(tmp_path):
    host, _connection, _segment, _packet, _staged, scope = _loaded(tmp_path)
    try:
        source = load_fresh_learning_runtime_source(host.fresh_learning, **scope)
        ref = source.reference()["source_metadata"]["reference"]
        path = host.fresh_learning.archive.png_root / f"{ref['screenshot_sha256']}.png"
        original = path.read_bytes()
        path.write_bytes(b"tampered")
        with pytest.raises(FreshLearningRuntimeSourceError, match="archive"):
            reload_fresh_learning_runtime_source(host.fresh_learning, source)
        path.write_bytes(original)
    finally:
        host.close()


def test_rejects_cross_scope_closed_revoked_and_changed_membership(tmp_path):
    host, connection, segment, _packet, _staged, scope = _loaded(tmp_path)
    try:
        with pytest.raises(FreshLearningRuntimeSourceError, match="scope|ownership"):
            load_fresh_learning_runtime_source(
                host.fresh_learning,
                connection_id="other", task_id=scope["task_id"],
                segment_id=scope["segment_id"], batch_id=scope["batch_id"],
            )
        current = host.learning_segments.get(**{key: scope[key] for key in ("connection_id", "task_id", "segment_id")})
        host.learning_segments.finish(
            connection_id=scope["connection_id"], task_id=scope["task_id"],
            segment_id=scope["segment_id"], expected_revision=current["revision"],
        )
        with pytest.raises(FreshLearningRuntimeSourceError, match="active"):
            load_fresh_learning_runtime_source(host.fresh_learning, **scope)
        other = host.learning_segments.start(
            connection_id=scope["connection_id"], task_id=scope["task_id"],
            idempotency_key="other-runtime-source-segment", title="Other fresh segment",
        )
        with pytest.raises(FreshLearningRuntimeSourceError, match="scope"):
            load_fresh_learning_runtime_source(
                host.fresh_learning,
                connection_id=scope["connection_id"], task_id=scope["task_id"],
                segment_id=other["segment_id"], batch_id=scope["batch_id"],
            )
    finally:
        host.close()

    host, connection, _segment, _packet, _staged, scope = _loaded(tmp_path / "revoked")
    try:
        host._service.reviewer_call(REVIEWER, "revoke_connection", {
            "connection_id": connection["connection_id"], "idempotency_key": "revoke-runtime-source",
        })
        with pytest.raises(FreshLearningRuntimeSourceError, match="scope|ownership"):
            load_fresh_learning_runtime_source(host.fresh_learning, **scope)
    finally:
        host.close()


def test_reload_rejects_changed_batch_source_and_removed_membership(tmp_path):
    host, connection, _segment, _packet, _staged, scope = _loaded(tmp_path)
    try:
        source = load_fresh_learning_runtime_source(host.fresh_learning, **scope)

        def mutate_batch(state):
            batch = state["batches"][scope["batch_id"]]
            changed = deepcopy(batch["fresh_learning_source"])
            changed["reference"]["capture_id"] = "fresh-capture.changed"
            batch["fresh_learning_source"] = changed
            stored = state["connections"][connection["connection_id"]]["learning_segments"][scope["segment_id"]]
            stored["observations"] = [{"batch_id": scope["batch_id"], "source": changed}]
            stored["revision"] += 1

        host.fresh_learning.segments.store.mutate(mutate_batch)
        with pytest.raises(FreshLearningRuntimeSourceError, match="membership|source"):
            reload_fresh_learning_runtime_source(host.fresh_learning, source)

        def remove_membership(state):
            stored = state["connections"][connection["connection_id"]]["learning_segments"][scope["segment_id"]]
            stored["observations"] = []
            stored["revision"] += 1
            state["batches"][scope["batch_id"]].pop("fresh_learning_source")

        host.fresh_learning.segments.store.mutate(remove_membership)
        with pytest.raises(FreshLearningRuntimeSourceError, match="membership|source"):
            load_fresh_learning_runtime_source(host.fresh_learning, **scope)
    finally:
        host.close()


def test_native_source_reference_normalizes_identity_and_reloads(tmp_path):
    packet = _owner(
        tmp_path / "native-capture",
        application={"kind": "native", "executable_path": r"c:\fresh\app.exe"},
    ).observe(target_window_handle=4242, target_process_id=9001)
    host, _connection, _segment, _packet, _args, staged = _stage(tmp_path, packet=packet)
    try:
        scope = {
            "connection_id": staged["source"]["connection_id"],
            "task_id": staged["source"]["task_id"],
            "segment_id": staged["source"]["segment_id"],
            "batch_id": staged["batch_id"],
        }
        source = load_fresh_learning_runtime_source(host.fresh_learning, **scope)
        assert source.reference()["application_identity"] == {
            "kind": "native", "executable_path": r"c:\fresh\app.exe",
        }
        assert reload_fresh_learning_runtime_source(host.fresh_learning, source) == source
    finally:
        host.close()


def test_real_owner_rechecks_mutable_root_and_store_identity(tmp_path):
    host, _connection, _segment, _packet, _staged, scope = _loaded(tmp_path)
    try:
        owner = host.fresh_learning
        facade = owner.facade
        original_root, original_store = facade._artifact_root, facade._service._store
        try:
            facade._artifact_root = tmp_path / "foreign-root"
            with pytest.raises(FreshLearningRuntimeSourceError, match="owner"):
                load_fresh_learning_runtime_source(owner, **scope)
            facade._artifact_root = original_root
            facade._service._store = object()
            with pytest.raises(FreshLearningRuntimeSourceError, match="owner"):
                load_fresh_learning_runtime_source(owner, **scope)
        finally:
            facade._artifact_root = original_root
            facade._service._store = original_store
    finally:
        host.close()
