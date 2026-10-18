from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent.runtime_grounded_consume import (
    RuntimeGroundedConsumeError,
    _validate_fresh_text_field_expectation,
)
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.text_field_evidence import (
    TextFieldIdentity,
    TextFieldSnapshot,
    prepare_text_field_expectation,
)
from app.agent.text_parameters import (
    ReviewedTextParameters,
    ReviewedTextSource,
    ResolvedTextParameters,
    text_parameter_reference,
)


class _Preview:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return deepcopy(self._payload)


def _parameters(*, clear_existing: bool = False) -> ResolvedTextParameters:
    reviewed = ReviewedTextParameters(
        target_field_id="field-1",
        content=ReviewedTextSource("literal", "X"),
        clear_existing=clear_existing,
        sensitive=False,
    )
    return ResolvedTextParameters(reviewed=reviewed, text="X")


def _expectation(*, capture_id: str, read_id: str, observed_at_ns: int, clear_existing: bool = False) -> dict:
    identity = TextFieldIdentity(
        target_field_id="field-1",
        window_handle=4242,
        process_id=9001,
        process_create_time=1.0,
        runtime_id=(1, 2),
        window_rect=(0, 0, 320, 200),
        control_bbox=(40, 50, 120, 40),
    )
    before = TextFieldSnapshot(
        identity=identity,
        capture_id=capture_id,
        read_id=read_id,
        observed_at_ns=observed_at_ns,
        source="uia_value",
        value="A",
        selection=(1, 1),
    )
    return prepare_text_field_expectation(
        before, _parameters(clear_existing=clear_existing)
    ).to_reference()


def _fill_preview(expectation: dict, *, capture_id: str, clear_existing: bool = False) -> _Preview:
    return _Preview({
        "current_observation": {"current_capture": {"capture_id": capture_id}},
        "review_selection": {
            "semantic_action": "fill_field",
            "text_parameters_ref": text_parameter_reference(_parameters(clear_existing=clear_existing).reviewed),
        },
        "text_execution_ref": expectation["text_execution_ref"],
        "text_field_expectation_ref": expectation,
    })


def _checkpoint_inputs(expectation: dict) -> tuple[dict, dict, dict, dict, dict]:
    reference = text_parameter_reference(_parameters().reviewed)
    selection = {
        "semantic_action": "fill_field",
        "text_parameters_ref": reference,
    }
    grounding = {
        "semantic_action": "fill_field",
        "text_parameters_ref": reference,
        "viewport_size": {"width": 320, "height": 200},
        "bbox": {"x": 50, "y": 55, "w": 100, "h": 30},
        "click_point": {"x": 60, "y": 60},
    }
    gate = {
        "semantic_action": "fill_field",
        "text_parameters_ref": reference,
        "selected_click_point": deepcopy(grounding["click_point"]),
    }
    current = {"capture_id": expectation["before"]["capture_id"]}
    base = {"server_binding": SimpleNamespace(target_window_handle=4242)}
    return base, current, selection, grounding, gate


def test_fresh_fill_expectation_allows_only_a_new_same_field_read() -> None:
    approved = _expectation(capture_id="capture-old", read_id="read-old", observed_at_ns=10)
    fresh = _expectation(capture_id="capture-new", read_id="read-new", observed_at_ns=11)

    _validate_fresh_text_field_expectation(
        _fill_preview(approved, capture_id="capture-old"),
        _fill_preview(fresh, capture_id="capture-new"),
        fresh_capture_id="capture-new",
    )


def test_fresh_clear_existing_allows_only_selection_to_change() -> None:
    approved = _expectation(
        capture_id="capture-old", read_id="read-old", observed_at_ns=10, clear_existing=True
    )
    fresh = _expectation(
        capture_id="capture-new", read_id="read-new", observed_at_ns=11, clear_existing=True
    )
    fresh["before"]["selection"] = [0, 0]

    _validate_fresh_text_field_expectation(
        _fill_preview(approved, capture_id="capture-old", clear_existing=True),
        _fill_preview(fresh, capture_id="capture-new", clear_existing=True),
        fresh_capture_id="capture-new",
    )


@pytest.mark.parametrize("mutation", ["missing", "text_execution", "selection"])
def test_fresh_fill_expectation_rejects_missing_or_mutated_reference(mutation: str) -> None:
    approved = _expectation(capture_id="capture-old", read_id="read-old", observed_at_ns=10)
    fresh = _expectation(capture_id="capture-new", read_id="read-new", observed_at_ns=11)
    payload = _fill_preview(fresh, capture_id="capture-new").to_dict()
    if mutation == "missing":
        del payload["text_field_expectation_ref"]
    elif mutation == "text_execution":
        payload["text_field_expectation_ref"]["text_execution_ref"]["text_sha256"] = "f" * 64
        payload["text_execution_ref"] = payload["text_field_expectation_ref"]["text_execution_ref"]
    else:
        payload["text_field_expectation_ref"]["before"]["selection"] = [0, 0]

    with pytest.raises(RuntimeGroundedConsumeError):
        _validate_fresh_text_field_expectation(
            _fill_preview(approved, capture_id="capture-old"),
            _Preview(payload),
            fresh_capture_id="capture-new",
        )


def test_checkpoint_accepts_only_matching_fill_expectation() -> None:
    expectation = _expectation(capture_id="capture-current", read_id="read-current", observed_at_ns=10)
    base, current, selection, grounding, gate = _checkpoint_inputs(expectation)

    result = RuntimeIntentClaimStore._validate_text_field_checkpoint_reference(
        expectation,
        base=base,
        current_observation=current,
        selection=selection,
        grounding=grounding,
        gate=gate,
        target_process_id=9001,
    )

    assert result == expectation
    assert result is not expectation


@pytest.mark.parametrize("mutation", ["missing", "capture", "expected_length"])
def test_checkpoint_rejects_missing_or_mutated_fill_expectation(mutation: str) -> None:
    expectation = _expectation(capture_id="capture-current", read_id="read-current", observed_at_ns=10)
    base, current, selection, grounding, gate = _checkpoint_inputs(expectation)
    value = None if mutation == "missing" else deepcopy(expectation)
    if mutation == "capture":
        value["before"]["capture_id"] = "other-capture"
    elif mutation == "expected_length":
        value["expected_value_length"] = True

    with pytest.raises(RuntimeIntentClaimStoreError):
        RuntimeIntentClaimStore._validate_text_field_checkpoint_reference(
            value,
            base=base,
            current_observation=current,
            selection=selection,
            grounding=grounding,
            gate=gate,
            target_process_id=9001,
        )


def test_click_and_scroll_checkpoints_remain_text_reference_free() -> None:
    for semantic in ("open_detail", "scroll_region"):
        assert RuntimeIntentClaimStore._validate_text_field_checkpoint_reference(
            None,
            base={},
            current_observation={},
            selection={"semantic_action": semantic},
            grounding={},
            gate={},
            target_process_id=9001,
        ) is None
        with pytest.raises(RuntimeIntentClaimStoreError, match="non-fill"):
            RuntimeIntentClaimStore._validate_text_field_checkpoint_reference(
                {},
                base={},
                current_observation={},
                selection={"semantic_action": semantic},
                grounding={},
                gate={},
                target_process_id=9001,
            )
