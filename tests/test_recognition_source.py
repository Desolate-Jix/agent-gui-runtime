"""识别来源与能力协商不启动模型，不将未知能力伪装为不支持。"""
import json

import pytest
from pydantic import ValidationError

from app.vision.recognition_source import (
    ClientVisionCapabilities, RecognitionSourceConfig,
    load_recognition_source, resolve_recognition_route,
)


def capabilities(**overrides):
    return ClientVisionCapabilities.model_validate({
        "image_transport": "supported", "current_vision": "supported",
        "delegation": "supported", "model_selection": "supported",
        "delegate_vision": "supported", **overrides,
    })


def test_legacy_configuration_keeps_local_source(tmp_path):
    path = tmp_path / "vision.json"
    path.write_text(json.dumps({"vision": {"mode": "local_grounding", "local": {}}}), encoding="utf-8")
    config = load_recognition_source(path)
    assert config.source == "local"
    assert resolve_recognition_route(config, capabilities()).requires_local_model is True


def test_only_explicit_recognition_section_selects_agent(tmp_path):
    path = tmp_path / "vision.json"
    path.write_text(json.dumps({"vision": {"mode": "local"},
        "recognition": {"source": "agent_current"}}), encoding="utf-8")
    config = load_recognition_source(path)
    route = resolve_recognition_route(config, capabilities())
    assert route.status == "eligible"
    assert route.source == "agent_current"
    assert route.requires_local_model is False
    assert route.dispatch_owner == "agent_client"


@pytest.mark.parametrize("value,expected", [("unknown", "capability_unknown"),
                                           ("unsupported", "vision_unsupported")])
def test_current_vision_unavailable_disables_only_selected_route(value, expected):
    config = RecognitionSourceConfig(source="agent_current")
    route = resolve_recognition_route(config, capabilities(current_vision=value))
    assert route.status == "unavailable"
    assert route.code == expected
    assert route.source == "agent_current"
    assert route.requires_local_model is False
    assert config.source == "agent_current"


def test_text_only_planner_can_use_visual_delegate():
    config = RecognitionSourceConfig(source="agent_delegate", delegate_profile="vision-luna")
    route = resolve_recognition_route(config, capabilities(current_vision="unsupported"))
    assert route.status == "eligible"
    assert route.profile == "vision-luna"
    assert route.dispatch_owner == "agent_client"
    assert route.requires_local_model is False


@pytest.mark.parametrize("field", ["image_transport", "delegation", "model_selection", "delegate_vision"])
def test_delegate_requires_actual_transport_and_client_capability(field):
    config = RecognitionSourceConfig(source="agent_delegate", delegate_profile="vision-luna")
    route = resolve_recognition_route(config, capabilities(**{field: "unsupported"}))
    assert route.status == "unavailable"
    assert route.missing_capabilities == (field,)
    assert route.source == "agent_delegate"


def test_known_unsupported_takes_priority_over_unknown():
    route = resolve_recognition_route(
        RecognitionSourceConfig(source="agent_delegate", delegate_profile="vision-luna"),
        capabilities(delegation="unknown", delegate_vision="unsupported"))
    assert route.code == "vision_unsupported"
    assert set(route.missing_capabilities) == {"delegation", "delegate_vision"}


def test_external_api_needs_no_client_vision_but_is_not_connection_proof():
    route = resolve_recognition_route(
        RecognitionSourceConfig(source="external_api", api_profile="provider-a"),
        ClientVisionCapabilities())
    assert route.status == "eligible"
    assert route.connection_verified is False
    assert route.requires_local_model is False
    assert route.dispatch_owner == "framework"
    assert route.profile == "provider-a"


@pytest.mark.parametrize("value", [
    {"source": "agent_delegate"},
    {"source": "external_api"},
    {"source": "agent_delegate", "delegate_profile": " "},
    {"source": "agent_current", "delegate_profile": "luna"},
    {"source": "local", "api_profile": "x"},
    {"source": "external_api", "api_profile": "x", "api_key": "secret"},
    {"source": "agent_current", "fallback_policy": "automatic"},
])
def test_inconsistent_or_credential_bearing_configuration_is_rejected(value):
    with pytest.raises(ValidationError):
        RecognitionSourceConfig.model_validate(value)


def test_capability_has_no_implicit_truthy_coercion():
    with pytest.raises(ValidationError):
        ClientVisionCapabilities(current_vision=True)


def test_snapshots_are_immutable():
    config = RecognitionSourceConfig(source="agent_current")
    with pytest.raises(ValidationError):
        config.source = "local"


@pytest.mark.parametrize("text", ['{"recognition":{}}', '{"recognition":null}', '{"recognition":[]}',
    '{"recognition":{"source":"agent_current","source":"local"}}', '[]'])
def test_malformed_config_never_silently_falls_back_to_local(tmp_path, text):
    path = tmp_path / "vision.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_recognition_source(path)
