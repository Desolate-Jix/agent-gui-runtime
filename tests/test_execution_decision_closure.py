"""交付预检用新合成图与真实 DPAPI 核验依赖，不访问用户凭据。"""
from pathlib import Path
import os

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_execution_resources_include_decision_example_and_usage_documents():
    from scripts.build_execution_component import RESOURCES
    assert {"configs/decision-profile.example.json", "docs/development/DECISION_API.md",
            "docs/OPTIONAL_JUDGMENT_AND_MODEL_USAGE.md"} <= set(RESOURCES)
    assert all((ROOT / name).is_file() for name in RESOURCES)


def test_offline_decision_closure_authenticates_without_key_or_http(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    from scripts import check_execution_component
    original_get = os.environ.get

    def guarded_get(name, *args):
        if name in {"OPENAI_API_KEY", "AGENT_GUI_DECISION_PROFILE", "DECISION_CLOSURE_KEY_UNUSED"}:
            pytest.fail("offline dependency check cannot read credentials or caller configuration")
        return original_get(name, *args)

    def forbidden(*args, **kwargs):
        pytest.fail("offline dependency check cannot create the network provider")

    monkeypatch.setattr(os.environ, "get", guarded_get)
    monkeypatch.setattr(OpenAIDecisionsProvider, "__init__", forbidden)
    result = check_execution_component.check_decision_dependencies()
    assert result["passed"] is True and result["dpapi_authenticated"] is True
    assert result["tampered_result_rejected"] is True and result["binding_mismatch_rejected"] is True
    assert result["readonly_source_unchanged"] is True
    assert result["synthetic_provider_calls"] == 1 and result["network_used"] is False
    assert result["key_required"] is False and result["input_executed"] is False


def test_decision_closure_fails_if_real_dpapi_dependency_is_unavailable(monkeypatch):
    from app.judgment import service
    from scripts import check_execution_component

    def unavailable(*args, **kwargs):
        raise OSError("synthetic_dpapi_unavailable")

    monkeypatch.setattr(service, "_protect", unavailable)
    with pytest.raises(ValueError, match="decision dependency"):
        check_execution_component.check_decision_dependencies()
