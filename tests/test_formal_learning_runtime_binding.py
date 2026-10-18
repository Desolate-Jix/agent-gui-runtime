from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
from app.agent.action_learning_recorder import ActionLearningRecorder
from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from app.agent_link.learning_segments import LearningSegmentOwner
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import LocalAgentRuntimeCallsite
from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from tests.test_formal_action_learning_recorder import _controller
from tests.test_live_controller_w4 import (
    _Gate, _ObservationSource, _TargetResolver, _WindowVisibilityChecker, _asset, _intent,
)


REVIEWER = "runtime-binding-reviewer"
TASK = "runtime-binding-task"


def _fixture(root: Path):
    store = AgentLinkStore(root / "agent-link.json")
    service = AgentLinkService(store, REVIEWER)
    connection = service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": TASK, "agent_name": "runtime-binding-agent",
    })
    recorder = ActionLearningRecorder(project_root=root)
    owner = LearningSegmentOwner(
        store, recorder=recorder,
        capture_archive=ActionLearningCaptureArchive(recorder=recorder),
    )
    segment = owner.start(
        connection_id=connection["connection_id"], task_id=TASK,
        idempotency_key="start", title="Runtime binding",
    )
    return store, service, connection, recorder, owner, segment


def test_binding_uses_owner_root_and_exact_context(tmp_path: Path) -> None:
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    binding = LearningRuntimeBinding(
        owner=owner, connection_id=connection["connection_id"],
        task_id=TASK, segment_id=segment["segment_id"],
    )
    assert binding.project_root == tmp_path.resolve()
    assert binding.recorder is recorder
    attached = binding.attach_validated_runtime(runtime_session_id="session.runtime")
    assert attached["children"][0]["phase"] == "bound"
    store.close()


def test_unconsumed_runtime_is_cancelled_and_segment_finishes_empty(tmp_path: Path) -> None:
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    binding = LearningRuntimeBinding(
        owner=owner, connection_id=connection["connection_id"],
        task_id=TASK, segment_id=segment["segment_id"],
    )
    binding.attach_validated_runtime(runtime_session_id="session.empty")
    cancelled = binding.close_unconsumed(runtime_session_id="session.empty")
    assert cancelled["children"][0]["phase"] == "cancelled"
    assert recorder.get_learning_session(
        learning_session_id=cancelled["children"][0]["learning_session_id"],
    )["status"] == "finished"
    closed = owner.finish(
        connection_id=connection["connection_id"], task_id=TASK,
        segment_id=segment["segment_id"], expected_revision=cancelled["revision"],
    )
    assert closed["status"] == "closed"
    assert closed["source_status"] == "empty"
    store.close()


def test_unconsumed_close_rejects_consumed_child(tmp_path: Path) -> None:
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    binding = LearningRuntimeBinding(
        owner=owner, connection_id=connection["connection_id"],
        task_id=TASK, segment_id=segment["segment_id"],
    )
    controller, _, backend, _, _ = _controller(tmp_path, recorder)
    runtime = controller.start_session()
    binding.attach_validated_runtime(runtime_session_id=runtime.session_id)
    assert controller.submit_intent(_intent(runtime)).outcome == "VERIFIED"
    with pytest.raises(AgentLinkError) as rejected:
        binding.close_unconsumed(runtime_session_id=runtime.session_id)
    assert rejected.value.code == "learning_busy"
    assert backend.attempt_count == 1
    store.close()


def _make_callsite(root: Path, learning_binding: LearningRuntimeBinding | None):
    asset = _asset()
    assets = ReviewedWorkflowAssetStore(project_root=root)
    assets.publish(asset, expected_registry_revision=0)
    claims = RuntimeIntentClaimStore(
        project_root=root, receipt_store=RuntimeReceiptStore(project_root=root),
    )
    windows = SimpleNamespace(
        bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True),
    )
    windows.get_bound_window = lambda: windows.bound
    windows.bind_window_by_handle = lambda handle: windows.bound if handle == 4242 else None
    backend = DeterministicFakeBackend()
    controllers = []

    def build(binding):
        controller = LiveController(
            binding=binding, asset_loader=assets, observation_source=_ObservationSource(asset),
            target_resolver=_TargetResolver("resolved"), gate=_Gate(allowed=True),
            window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
            backend=backend, intent_claim_store=claims,
            grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
            verification_max_capture_attempts=1,
            verification_poll_interval_seconds=0.0,
            verification_sleeper=lambda _seconds: None,
            verification_monotonic_clock=lambda: 0.0,
        )
        controllers.append(controller)
        return controller

    selection = RuntimeSessionSelection(
        asset_id=asset["asset_id"], asset_content_sha256=content_sha256(asset),
        target_window_handle=4242, target_process_id=9001,
    )
    callsite = LocalAgentRuntimeCallsite(
        project_root=root, asset_store=assets, window_manager=windows, claim_store=claims,
        controller_factory=build,
        selection=selection, learning_binding=learning_binding,
    )
    return callsite, windows, selection, backend


def test_callsite_attaches_post_start_and_cancels_no_claim_runtime(tmp_path: Path) -> None:
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    binding = LearningRuntimeBinding(
        owner=owner, connection_id=connection["connection_id"],
        task_id=TASK, segment_id=segment["segment_id"],
    )
    callsite, _, _, backend = _make_callsite(tmp_path, binding)
    observation = callsite.start_session()
    assert callsite._controller._action_learning_recorder is recorder
    current = owner.get(
        connection_id=connection["connection_id"], task_id=TASK, segment_id=segment["segment_id"],
    )
    assert current["children"][0]["runtime_session_id"] == observation.session_id
    callsite.cancel_prepared_session(session_id=observation.session_id)
    cancelled = owner.get(
        connection_id=connection["connection_id"], task_id=TASK, segment_id=segment["segment_id"],
    )
    assert cancelled["children"][0]["phase"] == "cancelled"
    assert backend.attempt_count == 0
    store.close()


def test_callsite_rejects_wrong_binding_before_dependencies(tmp_path: Path) -> None:
    class Dependency:
        def __getattr__(self, _name):
            raise AssertionError("dependency must not be accessed")

    with pytest.raises(TypeError, match="LearningRuntimeBinding"):
        LocalAgentRuntimeCallsite(
            project_root=tmp_path, asset_store=Dependency(), window_manager=Dependency(),
            claim_store=Dependency(), learning_binding=object(),
        )
