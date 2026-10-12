"""交付预检用新合成图与真实 DPAPI 核验依赖，不访问用户凭据。"""
from pathlib import Path
import json
import os
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_execution_resources_include_decision_example_and_usage_documents():
    from scripts.build_execution_component import RESOURCES
    assert {"configs/decision-profile.example.json", "docs/development/DECISION_API.md",
            "configs/decision-profile.adaptive.example.json",
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
    adaptive = result["adaptive_v2"]
    assert adaptive["passed"] is True and adaptive["dpapi_authenticated"] is True
    assert adaptive["profile_contract"] == "decision_profile.v2"
    assert adaptive["result_schema"] == "decision_assessment.v2"
    assert adaptive["dispositions"] == ["observe", "continue", "review_required"]
    assert adaptive["review_success_not_adopted"] is True
    assert adaptive["always_main_zero_request"] is True
    assert adaptive["cached_replay_zero_request"] is True
    assert adaptive["tampered_result_rejected"] is True
    assert adaptive["review_context_mismatch_rejected"] is True
    assert adaptive["assessment_context_mismatch_rejected"] is True
    assert adaptive["observation_frame_binding_rejected"] is True
    assert adaptive["readonly_source_unchanged"] is True
    assert adaptive["synthetic_provider_calls"] == 3


def test_decision_closure_fails_if_real_dpapi_dependency_is_unavailable(monkeypatch):
    from app.judgment import service
    from scripts import check_execution_component

    def unavailable(*args, **kwargs):
        raise OSError("synthetic_dpapi_unavailable")

    monkeypatch.setattr(service, "_protect", unavailable)
    with pytest.raises(ValueError, match="decision dependency"):
        check_execution_component.check_decision_dependencies()


def test_offline_probe_rejects_v2_success_that_bypasses_proactive_review(monkeypatch):
    from app.judgment import DecisionService
    from scripts.check_execution_component import check_decision_dependencies
    original = DecisionService.evaluate

    def wrong_adoption(self, **kwargs):
        result = original(self, **kwargs)
        if (self.profile.contract_version == "decision_profile.v2"
                and result.get("verdict") == "success" and result.get("disposition") == "review_required"):
            result = {**result, "adopted": True}
        return result

    monkeypatch.setattr(DecisionService, "evaluate", wrong_adoption)
    with pytest.raises(ValueError, match="adaptive decision dependency"):
        check_decision_dependencies()


def test_copied_payload_runs_actual_v2_probe_in_isolated_interpreter(tmp_path):
    from scripts.build_component_sources import copy_component_sources
    from scripts.build_execution_component import collect_execution_sources
    entries, resources, _ = collect_execution_sources(ROOT)
    payload = tmp_path / "isolated-payload"
    copy_component_sources(ROOT, payload, entries, resources=resources)
    # 只运行临时依赖探针，不生成组件、启动宿主或创建网络 provider。
    code = """
import json, os
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
original_get = os.environ.get
def guarded_get(name, *args):
    if name in {'OPENAI_API_KEY', 'AGENT_GUI_DECISION_PROFILE', 'DECISION_CLOSURE_KEY_UNUSED'}:
        raise AssertionError('credential/configuration lookup forbidden')
    return original_get(name, *args)
os.environ.get = guarded_get
from app.judgment import OpenAIDecisionsProvider
def forbidden(*args, **kwargs):
    raise AssertionError('network provider construction forbidden')
OpenAIDecisionsProvider.__init__ = forbidden
from scripts.check_execution_component import check_decision_dependencies
result = check_decision_dependencies()
assert result['adaptive_v2']['passed']
loaded = {}
for name, module in tuple(sys.modules.items()):
    if name.startswith(('app.', 'modules.', 'scripts.')) and getattr(module, '__file__', None):
        path = Path(module.__file__).resolve()
        assert path.is_relative_to(root), (name, str(path))
        loaded[name] = path.relative_to(root).as_posix()
assert not any(name.startswith(('PySide', 'PyQt')) for name in sys.modules)
result.update(python_isolated=bool(sys.flags.isolated), loaded_modules=loaded)
print(json.dumps(result, ensure_ascii=False))
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(payload)],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["python_isolated"] is True
    assert evidence["adaptive_v2"]["synthetic_provider_calls"] == 3
    assert {"app.judgment.adaptive_policy", "app.judgment.service", "app.judgment.evidence",
            "app.judgment.openai_decisions"} <= set(evidence["loaded_modules"])
    assert evidence["network_used"] is False and evidence["key_required"] is False
