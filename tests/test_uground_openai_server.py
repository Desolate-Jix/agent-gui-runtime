from __future__ import annotations

from scripts.model_servers import uground_openai_server


def test_uground_point_payload_parses_parenthesized_normalized_point() -> None:
    payload = uground_openai_server._point_payload("(456, 123)")

    assert payload["contract_version"] == "uground_point_v1"
    assert payload["status"] == "ready"
    assert payload["point"] == {
        "x": 456.0,
        "y": 123.0,
        "coordinate_space": "normalized_0_1000",
    }
    assert "x/1000*width" in payload["coordinate_note"]


def test_uground_point_payload_parses_bracketed_normalized_point() -> None:
    payload = uground_openai_server._point_payload("[12.5, 999]")

    assert payload["status"] == "ready"
    assert payload["point"]["x"] == 12.5
    assert payload["point"]["y"] == 999.0
    assert payload["point"]["coordinate_space"] == "normalized_0_1000"


def test_uground_prompt_wraps_plain_description_once() -> None:
    prompt = uground_openai_server._uground_prompt("Search button")

    assert "Description: Search button" in prompt
    assert "Answer:" in prompt
    assert uground_openai_server._uground_prompt(prompt) == prompt
