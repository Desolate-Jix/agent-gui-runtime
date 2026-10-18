from __future__ import annotations

import pytest

from tests.test_desktop_exact_review import _batch, _complete, _new_runtime, _prepare
from tests.test_live_runtime_composition_w3b import _recognition
from tests.test_text_formal_execution import formal_text


def test_exact_review_blocks_external_text_field_only_state_without_interface_identity(tmp_path):
    batch = _batch(action_type="fill_field")
    batch["steps"][0]["text_parameters"] = {
        "contract_version": "reviewed_text_parameters_v1",
        "target_field_id": "open",
        "content": {"kind": "literal", "text": "fixed"},
        "clear_existing": True,
        "sensitive": False,
        "submit": False,
        "clipboard_policy": "restore_previous",
    }
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace)
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "blocked"
        assert any(
            item["code"] == "recognition_text_required"
            and item["detail"] == "missing_observable_interface_identity"
            for item in compiled["blocked_reasons"]
        )
    finally:
        facade.close()
        store.close()


@pytest.mark.parametrize("identity_payload", [None, "Wrong interface"])
def test_runtime_rejects_missing_or_mismatched_interface_identity_before_text_input(formal_text, identity_payload):
    fixture = formal_text(variable=False, clear=True, start=False)
    state = next(item for item in fixture.asset["states"] if item["state_id"] == fixture.asset["entry_state_id"])
    interface_anchor = next(item for item in state["identity_anchors"] if not item.get("text_field_id"))
    field_anchor = next(item for item in state["identity_anchors"] if item.get("text_field_id") == "open")
    runner = fixture.adapter._recognition_runner
    payloads = {field_anchor["label"]: runner.payloads[field_anchor["label"]]}
    if identity_payload is not None:
        payloads[interface_anchor["label"]] = _recognition(identity_payload, role="text")
    runner.payloads = payloads

    observation = fixture.service.start_session()

    assert observation.state.status == "unknown"
    assert [action.semantic_action for action in observation.available_actions] == ["safe_stop"]
    assert fixture.state.pasted == []
