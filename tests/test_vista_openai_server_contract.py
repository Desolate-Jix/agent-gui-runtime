from scripts.model_servers.vista_openai_server import (
    _coordinate_output_complete,
    _point_payload,
    _request_timeout_seconds,
    _vista_prompt,
)


def test_vista_point_payload_respects_requested_roi_local_coordinate_space():
    payload = _point_payload("[57,46]", instruction="Return coordinate_space=roi_local_point.")

    assert payload["point"] == {"x": 57.0, "y": 46.0, "coordinate_space": "roi_local_point"}


def test_vista_point_payload_keeps_legacy_normalized_default():
    payload = _point_payload("[500,500]", instruction="Locate target.")

    assert payload["point"] == {"x": 500.0, "y": 500.0, "coordinate_space": "normalized_0_1000"}


def test_vista_point_payload_repairs_only_missing_closing_bracket():
    payload = _point_payload("[499, 500", instruction="Locate target.")

    assert payload["status"] == "ready"
    assert payload["point"] == {"x": 499.0, "y": 500.0, "coordinate_space": "normalized_0_1000"}
    assert payload["parse_repair"] == {
        "applied": True,
        "reason": "missing_closing_bracket",
    }


def test_vista_point_payload_does_not_repair_incomplete_number_pair():
    payload = _point_payload("[499,", instruction="Locate target.")

    assert payload["status"] == "unparsed"
    assert payload["point"] is None
    assert payload["parse_repair"]["applied"] is False


def test_vista_prompt_extracts_goal_from_pipeline_context():
    prompt = _vista_prompt(
        "Locate the requested GUI target in the screenshot.\n"
        "Goal: Home button in the left navigation sidebar\n"
        "Candidates:\n"
        "- candidate_1: label='Home', bbox=[40,29,41,23]"
    )

    assert prompt == (
        "Output the center point of the position corresponding to the instruction: "
        "Home button in the left navigation sidebar. "
        "The output should just be the coordinates of a point, in the format [x,y]."
    )
    assert "Candidates" not in prompt


def test_vista_prompt_preserves_official_prompt():
    prompt = (
        "Output the center point of the position corresponding to the instruction: Click Search. "
        "The output should just be the coordinates of a point, in the format [x,y]."
    )

    assert _vista_prompt(prompt) == prompt


def test_vista_coordinate_output_stops_after_complete_point():
    assert _coordinate_output_complete("[321, 456]") is True
    assert _coordinate_output_complete("thinking [321,") is False
    assert _coordinate_output_complete("no point") is False


def test_vista_request_timeout_is_bounded_and_optional():
    assert _request_timeout_seconds({"request_timeout_seconds": 12}, default=30) == 12.0
    assert _request_timeout_seconds({"request_timeout_seconds": 0}, default=30) == 30.0
    assert _request_timeout_seconds({"request_timeout_seconds": 999}, default=30) == 300.0
