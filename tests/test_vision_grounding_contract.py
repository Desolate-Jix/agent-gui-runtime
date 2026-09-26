import copy
import json

import pytest
from pydantic import ValidationError

from app.vision.grounding_contract import GroundingResult, validate_grounding_result


def found_payload():
    return {
        "schema_version": "grounding.v1",
        "request_id": "request-1",
        "capture_id": "capture-1",
        "status": "found",
        "coordinate_space": "capture_image_pixels",
        "image_size": {"width": 100, "height": 80},
        "candidates": [{
            "id": "target-1", "label": "Search",
            "bbox": {"x": 10, "y": 20, "width": 30, "height": 10},
            "click_point": {"x": 20, "y": 25},
            "evidence_source": "agent_visual", "confidence": None,
        }],
        "selected_candidate_id": "target-1",
    }


def validate(payload):
    return validate_grounding_result(
        payload, request_id="request-1", capture_id="capture-1", image_size=(100, 80)
    )


def test_found_result_accepts_strict_valid_payload_and_json():
    payload = found_payload()
    assert validate(payload).selected_candidate_id == "target-1"
    assert validate(json.dumps(payload)).candidates[0].bbox.width == 30
    assert isinstance(validate(payload), GroundingResult)


@pytest.mark.parametrize("field,value", [
    ("request_id", "other"), ("capture_id", "other"),
    ("image_size", {"width": 101, "height": 80}),
])
def test_authoritative_identity_and_dimensions_must_match(field, value):
    payload = found_payload()
    payload[field] = value
    with pytest.raises(ValueError, match=field):
        validate(payload)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(schema_version="grounding.v2"),
    lambda p: p.update(coordinate_space="screen_pixels"),
    lambda p: p.update(extra="untrusted"),
    lambda p: p["candidates"][0]["bbox"].update(x=True),
    lambda p: p["candidates"][0]["click_point"].update(y=25.0),
    lambda p: p["image_size"].update(width=0),
    lambda p: p["image_size"].update(width=True),
    lambda p: p["candidates"][0]["bbox"].update(width=0),
    lambda p: p["candidates"][0]["bbox"].update(x=90),
    lambda p: p["candidates"][0]["click_point"].update(x=40),
    lambda p: p["candidates"][0].update(confidence=float("nan")),
    lambda p: p["candidates"][0].update(confidence=1.1),
])
def test_rejects_untrusted_or_invalid_geometry(mutation):
    payload = found_payload()
    mutation(payload)
    with pytest.raises(ValueError):
        validate(payload)


def test_duplicate_candidate_ids_rejected():
    payload = found_payload()
    payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))
    with pytest.raises(ValueError, match="candidate"):
        validate(payload)


@pytest.mark.parametrize("status,candidates,selected,valid", [
    ("found", [], None, False),
    ("found", ["one"], "missing", False),
    ("absent", [], None, True),
    ("unsupported", [], None, True),
    ("error", [], None, True),
    ("absent", ["one"], None, False),
    ("unsupported", [], "target-1", False),
    ("error", ["one"], "target-1", False),
    ("ambiguous", ["one"], None, False),
    ("ambiguous", ["one", "two"], None, True),
    ("ambiguous", ["one", "two"], "target-1", False),
])
def test_status_candidate_invariants(status, candidates, selected, valid):
    payload = found_payload()
    payload["status"] = status
    payload["candidates"] = [
        {**copy.deepcopy(found_payload()["candidates"][0]), "id": candidate}
        for candidate in candidates
    ]
    payload["selected_candidate_id"] = selected
    if valid:
        assert validate(payload).status == status
    else:
        with pytest.raises(ValueError):
            validate(payload)


@pytest.mark.parametrize("raw", [
    "not-json",
    json.dumps(found_payload()) + " trailing",
    '{"request_id":"first","request_id":"second"}',
    json.dumps(found_payload()).replace('"confidence": null', '"confidence": NaN'),
])
def test_raw_json_rejects_malformed_duplicate_or_nonfinite_values(raw):
    with pytest.raises(ValueError) as error:
        validate(raw)
    assert raw not in str(error.value)


def test_non_dict_non_json_input_rejected():
    with pytest.raises(ValueError):
        validate([found_payload()])
