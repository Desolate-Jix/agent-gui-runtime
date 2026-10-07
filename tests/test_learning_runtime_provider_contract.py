"""共同提供者合同维持明确类型、同所有者与同库身份门禁。"""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest


def test_explicit_metaclass_virtual_registration_cannot_bind_non_nominal_provider():
    script = '''
from abc import ABCMeta
from pathlib import Path
from types import SimpleNamespace
import tempfile
from app.agent_link.contracts import AgentLinkError
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.core.learning_runtime_provider_contract import LearningRuntimeProviderContract
class Fake:
    def __init__(self, owner):
        self.owner = owner
ABCMeta.register(LearningRuntimeProviderContract, Fake)
with tempfile.TemporaryDirectory() as temporary:
    store = AgentLinkStore(Path(temporary) / 'inbox.json')
    token = 'fixture-reviewer-token-0123456789'
    service = AgentLinkService(store, token)
    owner = SimpleNamespace(store=store)
    service._learning_owner = owner
    provider = Fake(owner)
    assert isinstance(provider, LearningRuntimeProviderContract)
    assert LearningRuntimeProviderContract not in type(provider).__mro__
    rejected = False
    try:
        service.bind_learning_runtime_provider(token, provider)
    except AgentLinkError as error:
        assert error.code == 'invalid_arguments'
        rejected = True
    finally:
        store.close()
    assert rejected, 'virtual provider admitted without actual nominal inheritance'
    assert service._learning_runtime_provider is None
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _bound(tmp_path):
    from app.agent_link.service import AgentLinkService
    from app.agent_link.store import AgentLinkStore
    from app.agent_link.learning_segments import LearningSegmentOwner
    from app.agent.action_learning_recorder import ActionLearningRecorder
    from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from app.desktop_review.learning_runtime import LearningRuntimeProvider
    store = AgentLinkStore(tmp_path / "inbox.json")
    token = "fixture-reviewer-token-0123456789"
    service = AgentLinkService(store, token)
    recorder = ActionLearningRecorder(project_root=tmp_path)
    owner = LearningSegmentOwner(store, recorder=recorder,
        capture_archive=ActionLearningCaptureArchive(recorder=recorder))
    service.bind_learning_segment_owner(token, owner)
    coordinator = NativeSingleStepCoordinator(tmp_path,
        SimpleNamespace(list_reviewed_assets=lambda: []), SimpleNamespace(status=lambda: {}),
        enable_agent_learning=False)
    return service, token, owner, LearningRuntimeProvider(owner, coordinator)


def test_contract_is_abstract_and_actual_provider_implements_complete_api(tmp_path):
    from app.core.learning_runtime_provider_contract import LearningRuntimeProviderContract
    with pytest.raises(TypeError):
        LearningRuntimeProviderContract()
    class EmptyProvider(LearningRuntimeProviderContract):
        pass
    with pytest.raises(TypeError):
        EmptyProvider()
    with pytest.raises(TypeError, match="virtual_subclass_forbidden"):
        LearningRuntimeProviderContract.register(SimpleNamespace)
    service, token, _, provider = _bound(tmp_path)
    assert isinstance(provider, LearningRuntimeProviderContract)
    assert not type(provider).__abstractmethods__
    service.bind_learning_runtime_provider(token, provider)
    assert service._learning_runtime_provider is provider


@pytest.mark.parametrize("variant", ["duck", "owner", "store", "absent", "token"])
def test_provider_binding_preserves_original_rejection_boundaries(tmp_path, variant):
    from app.agent_link.contracts import AgentLinkError
    service, token, owner, provider = _bound(tmp_path)
    if variant == "duck":
        provider = SimpleNamespace(owner=owner)
    elif variant == "owner":
        provider.owner = SimpleNamespace(store=service._store)
    elif variant == "store":
        owner.store = object()
    elif variant == "absent":
        service._learning_owner = None
    else:
        token = "wrong-reviewer-token-0123456789"
    with pytest.raises(AgentLinkError):
        service.bind_learning_runtime_provider(token, provider)
    assert service._learning_runtime_provider is None


def test_learning_static_closure_excludes_complete_executor_entrypoints():
    from scripts.build_component_sources import collect_module_sources
    root = Path(__file__).resolve().parents[1]
    sources = {path.relative_to(root).as_posix() for path in
        collect_module_sources(root, ["scripts/start_learning_workbench.py"])}
    forbidden = {"app/instant_mcp.py", "app/vision/agent_command_jobs.py",
        "app/execution/input_sequence.py", "app/execution/form_fill.py",
        "app/desktop_review/learning_runtime.py", "app/desktop_review/single_step_coordinator.py"}
    assert not sources & forbidden, sorted(sources & forbidden)


def test_admission_error_shared_class_identity_and_exact_rejection_evidence():
    from app.core.vision_admission_contract import AgentCommandError, AgentCommandVisionAdmissionError
    from app.vision.agent_command_jobs import AgentCommandError as OldError
    from app.vision.agent_command_jobs import AgentCommandVisionAdmissionError as OldAdmission
    from app.vision.recognition_source import RecognitionSourceConfig, ClientVisionCapabilities
    assert OldError is AgentCommandError
    assert OldAdmission is AgentCommandVisionAdmissionError
    error = AgentCommandVisionAdmissionError("original", {"kind": "capture"},
        RecognitionSourceConfig(source="local"), ClientVisionCapabilities(), "unsupported")
    result = error.before_dispatch_result("original")
    assert result["input_attempted"] is False and result["action_executed"] is False
    assert result["reason"] == "unsupported"
    with pytest.raises(ValueError, match="vision_admission_command_id_mismatch"):
        error.before_dispatch_result("other")
