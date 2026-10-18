from app.desktop_review.action_graph_source import action_sequence_metadata
from app.desktop_review.workspace import DesktopReviewError
import pytest


def test_action_sequence_records_order_without_claiming_transition():
    sources = [{"event_id": "event.1"}, {"event_id": "event.2"}]

    assert action_sequence_metadata(sources) == [
        {"sequence_index": 1, "event_id": "event.1", "previous_event_id": None,
         "continuity_status": "recorded_sequence"},
        {"sequence_index": 2, "event_id": "event.2", "previous_event_id": "event.1",
         "continuity_status": "unknown_gap"},
    ]


def test_action_sequence_does_not_deduplicate_or_infer_same_sha_transition():
    sources = [{"event_id": "event.1", "source_sha256": "a" * 64},
               {"event_id": "event.2", "source_sha256": "a" * 64}]

    result = action_sequence_metadata(sources)
    assert [item["event_id"] for item in result] == ["event.1", "event.2"]
    assert result[1]["continuity_status"] == "unknown_gap"


def test_action_sequence_rejects_duplicate_authoritative_events():
    with pytest.raises(DesktopReviewError, match="动作序列事件重复"):
        action_sequence_metadata([{"event_id": "event.1"}, {"event_id": "event.1"}])
