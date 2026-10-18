from copy import deepcopy

import pytest

from tests.test_live_runtime_composition_w3b import _RecognitionRunner, _WindowManager, _bound, _entry_payloads, _recognition, _role
from tests.test_text_formal_review_flow import text_preview_inputs


def _post_inputs(tmp_path):
    asset, adapter, _, before, _, selection, _, _ = text_preview_inputs(tmp_path)
    anchor = next(
        item for state in asset["states"] for item in state["identity_anchors"]
        if item["anchor_id"] == selection["element_ref"]
    )
    payloads = _entry_payloads(asset)
    payloads[anchor["label"]] = _recognition(
        anchor["label"], role=_role(anchor["kind"]), bbox=(80, 90, 100, 30), candidate_id="post-field",
    )
    adapter._recognition_runner = _RecognitionRunner(payloads)
    adapter._window_manager = _WindowManager(*[_bound() for _ in range(3)])
    after = adapter.capture_current(session_id="text-review", asset=asset, target_window_handle=4242)
    reader = adapter._text_field_reader
    return adapter, before, after, deepcopy(selection), reader


def test_post_read_uses_new_capture_recognition_bbox_without_reselecting_source_transition(tmp_path):
    adapter, before, after, selection, reader = _post_inputs(tmp_path)
    adapter.resolve = lambda **_kwargs: (_ for _ in ()).throw(AssertionError("post read must not reselect old transition"))

    actual = adapter.read_text_field_after(
        session_id="text-review", current_observation=after, previous_selection=selection,
    )

    assert after["capture_id"] != before["capture_id"]
    assert actual.capture_id == after["capture_id"]
    assert reader.calls[-1]["target_bbox"] == (80, 90, 100, 30)
    assert reader.calls[-1]["click_point"] == (130, 105)


@pytest.mark.parametrize("change", ["transition", "field"])
def test_post_read_rejects_mismatched_original_transition_or_field_reference(tmp_path, change):
    adapter, _, after, selection, reader = _post_inputs(tmp_path)
    if change == "transition":
        selection["transition_id"] = "unknown-transition"
    else:
        selection["text_parameters_ref"]["target_field_id"] = "other-field"

    with pytest.raises(ValueError):
        adapter.read_text_field_after(
            session_id="text-review", current_observation=after, previous_selection=selection,
        )
    assert reader.calls == []


def test_post_read_rejects_stale_current_observation(tmp_path):
    adapter, _, after, selection, reader = _post_inputs(tmp_path)
    stale = deepcopy(after)
    stale["capture_id"] = "stale-capture"

    with pytest.raises(ValueError):
        adapter.read_text_field_after(
            session_id="text-review", current_observation=stale, previous_selection=selection,
        )
    assert reader.calls == []
