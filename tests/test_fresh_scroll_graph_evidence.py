"""滚动只有通过当前容器空间核验后，才可进入可复用图边。"""

from __future__ import annotations

import pytest

from app.agent.live_controller import LiveControllerDecision
from app.desktop_review.action_graph_source import ActionGraphSourceReader, project_action_source
from tests.test_fresh_scroll_dispatch import _scroll_runtime


@pytest.mark.parametrize(
    "mode, expected_status, reusable",
    [
        ("target", "target_visual_change", True),
        ("outside", "non_target_visual_change", False),
        ("none", "no_visual_change", False),
    ],
)
def test_scroll_graph_requires_verified_target_only_change(
    tmp_path, mode, expected_status, reusable,
):
    with _scroll_runtime(tmp_path, mode) as (
        host, _owner, runtime, _claims, native_input, session, scope, intent,
    ):
        claim = runtime.request_grounded_confirmation(
            intent.to_dict(), target_process_id=9001,
        )
        assert not isinstance(claim, LiveControllerDecision), claim
        confirmation_id = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision="approved",
        )
        receipt = runtime.consume_grounded_confirmation(
            confirmation_id=confirmation_id,
        )
        assert not isinstance(receipt, LiveControllerDecision), receipt
        assert receipt.evidence.scroll_verification["spatial"]["status"] == expected_status
        assert len(native_input.calls) == 1

        collected = ActionGraphSourceReader(host.facade).collect(**scope)
        assert len(collected["sources"]) == 1
        projected = project_action_source(collected["sources"][0])
        assert len(projected["nodes"]) == 2

        synced = host.fresh_learning.sync_actions(**scope)
        graph = host.facade.load_graph_revision(synced["logical_workflow_id"])["graph"]
        action_nodes = [
            node for node in graph["nodes"]
            if node.get("surface_type") == "recorded_action_observation"
        ]
        assert len(action_nodes) == 2

        if reusable:
            assert len(projected["edges"]) == 1
            assert projected["invalid_sources"] == []
            assert action_nodes[0]["blockers"] == []
            assert len(graph["edges"]) == 1
            edge = graph["edges"][0]
            assert edge["scroll_parameters"]["direction"] == "down"
            assert edge["scroll_parameters"]["wheel_clicks"] == 3
            assert edge["scroll_parameters"]["target_container_id"] == edge["target_region_id"]
        else:
            assert projected["edges"] == []
            assert len(projected["invalid_sources"]) == 1
            invalid = projected["invalid_sources"][0]
            assert invalid["kind"] == "scroll_spatial_verification_failed"
            assert invalid["spatial_status"] == expected_status
            assert invalid["safe_stop_required"] is True
            assert action_nodes[0]["blockers"] == [invalid]
            assert graph["edges"] == []
            assert graph["invalid_sources"] == [invalid]


def test_scroll_graph_rejects_missing_after_spatial_capture_without_hiding_observations(
    tmp_path, monkeypatch,
):
    from app.agent import fresh_scroll_region

    with _scroll_runtime(tmp_path) as (
        host, _owner, runtime, _claims, _native_input, _session, scope, intent,
    ):
        original_read = fresh_scroll_region.read_fresh_scroll_capture
        reads = 0

        def lose_after_capture(*args, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise OSError("synthetic after spatial capture loss")
            return original_read(*args, **kwargs)

        monkeypatch.setattr(
            fresh_scroll_region, "read_fresh_scroll_capture", lose_after_capture,
        )
        claim = runtime.request_grounded_confirmation(
            intent.to_dict(), target_process_id=9001,
        )
        confirmation_id = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision="approved",
        )
        receipt = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert not isinstance(receipt, LiveControllerDecision), receipt
        assert receipt.evidence.scroll_verification["after"] is None
        assert receipt.evidence.scroll_verification["spatial"]["status"] == "unknown"

        source = ActionGraphSourceReader(host.facade).collect(**scope)["sources"][0]
        projected = project_action_source(source)
        assert len(projected["nodes"]) == 2
        assert projected["edges"] == []
        assert projected["invalid_sources"][0]["spatial_status"] == "unknown"
        assert projected["nodes"][0]["blockers"] == projected["invalid_sources"]

        synced = host.fresh_learning.sync_actions(**scope)
        graph = host.facade.load_graph_revision(synced["logical_workflow_id"])["graph"]
        action_nodes = [
            node for node in graph["nodes"]
            if node.get("surface_type") == "recorded_action_observation"
        ]
        assert len(action_nodes) == 2
        assert graph["edges"] == []
        assert graph["invalid_sources"] == projected["invalid_sources"]
        assert action_nodes[0]["blockers"] == projected["invalid_sources"]
