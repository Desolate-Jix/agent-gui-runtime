from scripts.model_servers.vista_openai_server import _point_payload


def test_vista_point_payload_respects_requested_roi_local_coordinate_space():
    payload = _point_payload("[57,46]", instruction="Return coordinate_space=roi_local_point.")

    assert payload["point"] == {"x": 57.0, "y": 46.0, "coordinate_space": "roi_local_point"}


def test_vista_point_payload_keeps_legacy_normalized_default():
    payload = _point_payload("[500,500]", instruction="Locate target.")

    assert payload["point"] == {"x": 500.0, "y": 500.0, "coordinate_space": "normalized_0_1000"}
