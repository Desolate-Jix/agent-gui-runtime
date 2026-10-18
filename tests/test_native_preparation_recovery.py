from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import AgentRuntimeCallsiteError, LocalAgentRuntimeCallsite
from app.desktop_review.single_step_coordinator import (
    NativeSingleStepCoordinator,
    NativeSingleStepCoordinatorError,
)
from tests.test_agent_runtime_api_v1 import _Assets, _Claims, _WindowManager, _workflow
from tests.test_agent_runtime_session_selection import _selection
from tests.test_live_controller_w4 import _controller


class _Facade:
    def list_reviewed_assets(self):
        return []


class _Windows:
    def __init__(self) -> None:
        self.window = SimpleNamespace(
            handle=77,
            process_id=1234,
            is_active=True,
            title="Editor",
            process_name="editor.exe",
        )

    def bind_window_by_handle(self, handle):
        assert handle == self.window.handle
        return self.window

    def get_bound_window(self):
        return self.window

    def list_visible_windows(self):
        return [self.window]


class _Host:
    def __init__(self, events: list[str] | None = None) -> None:
        self.single_step = None
        self.close_calls = 0
        self.events = events if events is not None else []

    def status(self):
        return {
            "contract_version": "native_review_host_v1",
            "phase": "ready",
            "base_url": "http://127.0.0.1:1",
            "staging_only": True,
        }

    def close(self):
        self.close_calls += 1
        self.events.append("host.close")


def _cleanup(selection: RuntimeSessionSelection) -> dict:
    return {
        "contract_version": "local_preparation_cleanup_v1",
        "selection": {
            "asset_id": selection.asset_id,
            "asset_content_sha256": selection.asset_content_sha256,
            "target_window_handle": selection.target_window_handle,
            "target_process_id": selection.target_process_id,
        },
        "cleanup_verified": True,
        "artifact_is_authorization": False,
    }


def _coordinator(runtime, *, host=None, events=None):
    windows = _Windows()

    def factory(**_kwargs):
        return runtime

    factory.window_manager = windows
    return NativeSingleStepCoordinator(
        Path("."),
        _Facade(),
        host or _Host(events),
        runtime_factory=factory,
        thread_initializer=lambda: None,
        thread_finalizer=lambda: None,
        foreground_timeout=0.2,
    )


def _prepare(coordinator):
    return coordinator.prepare(
        asset_id="portfolio.seek1",
        asset_content_sha256="a" * 64,
        target_window_handle=77,
        target_process_id=1234,
    )


def _observation():
    return SimpleNamespace(
        session_id="session.prepared",
        observation_id="observation.prepared",
        workflow=SimpleNamespace(workflow_id="workflow", asset_id="portfolio.seek1"),
        available_actions=(
            SimpleNamespace(
                action_id="action.apply",
                semantic_action="open_apply_flow",
                target_state_id="state.apply",
            ),
        ),
    )


@pytest.mark.parametrize("factory_result", ["raises", "none", "non_callable_start"])
def test_factory_failure_retains_unknown_owner_and_blocks_false_cleanup_or_retry(
    factory_result,
):
    windows = _Windows()
    host = _Host()
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs["selection"])
        if factory_result == "raises":
            raise RuntimeError("factory outcome unknown after resource creation")
        if factory_result == "none":
            return None
        return SimpleNamespace(start_session="not callable")

    factory.window_manager = windows
    coordinator = NativeSingleStepCoordinator(
        Path("."),
        _Facade(),
        host,
        runtime_factory=factory,
        thread_initializer=lambda: None,
        thread_finalizer=lambda: None,
        foreground_timeout=0.2,
    )
    expected = RuntimeSessionSelection("portfolio.seek1", "a" * 64, 77, 1234)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as failed:
            _prepare(coordinator)
        assert failed.value.result_unknown is True
        assert failed.value.retry_preparation is False
        assert factory_calls == [expected]
        assert coordinator._selection == expected
        assert coordinator._phase == "prepare_recovery_required"
        assert coordinator._runtime is None
        assert coordinator._factory_outcome_unknown is True
        owner_thread = coordinator._owner.thread_id
        assert isinstance(owner_thread, int)

        with pytest.raises(NativeSingleStepCoordinatorError) as cancelled:
            coordinator.cancel()
        assert cancelled.value.code == "runtime_cleanup_pending"
        assert cancelled.value.result_unknown is True

        with pytest.raises(NativeSingleStepCoordinatorError) as same_retry:
            _prepare(coordinator)
        assert same_retry.value.result_unknown is True
        assert same_retry.value.retry_preparation is False
        with pytest.raises(NativeSingleStepCoordinatorError) as changed_retry:
            coordinator.prepare(
                asset_id="portfolio.other",
                asset_content_sha256="b" * 64,
                target_window_handle=77,
                target_process_id=1234,
            )
        assert changed_retry.value.result_unknown is True
        assert changed_retry.value.retry_preparation is False
        assert factory_calls == [expected]

        with pytest.raises(NativeSingleStepCoordinatorError) as stopped:
            coordinator.shutdown()
        assert stopped.value.code == "shutdown_cleanup_pending"
        assert stopped.value.result_unknown is True
        assert host.status()["phase"] == "ready"
        assert host.close_calls == 0
        assert coordinator._owner.thread_id == owner_thread
    finally:
        coordinator._owner.close()


def test_real_managed_start_failure_has_idempotent_zero_lease_cleanup(tmp_path, monkeypatch):
    controller, source, _, _, backend = _controller(
        tmp_path / "first", target_window_handle=76101
    )
    contender, _, _, _, contender_backend = _controller(
        tmp_path / "second", target_window_handle=76101
    )

    monkeypatch.setattr(
        source,
        "create_initial",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("capture failed")),
    )
    with pytest.raises(RuntimeError, match="capture failed"):
        controller.start_session_preparation(preparation_id="preparation.capture")

    controller.cancel_session_preparation(preparation_id="preparation.capture")
    controller.cancel_session_preparation(preparation_id="preparation.capture")
    session = contender.start_session()
    contender.abandon_session(session_id=session.session_id)
    assert backend.attempt_count == contender_backend.attempt_count == 0


def test_managed_preparation_rejects_unknown_attempt_and_active_start(tmp_path):
    controller, _, _, _, _ = _controller(tmp_path, target_window_handle=76102)
    session = controller.start_session_preparation(preparation_id="preparation.active")
    try:
        with pytest.raises(ValueError, match="unknown|owned"):
            controller.cancel_session_preparation(preparation_id="preparation.foreign")
        with pytest.raises(ValueError, match="active|starting"):
            controller.start_session_preparation(preparation_id="preparation.second")
    finally:
        controller.cancel_session_preparation(preparation_id="preparation.active")
    controller.cancel_session_preparation(preparation_id="preparation.active")
    assert session.session_id


def test_managed_preparation_refuses_claimed_session_without_releasing_owner(
    tmp_path, monkeypatch
):
    controller, _, _, _, _ = _controller(tmp_path, target_window_handle=76103)
    session = controller.start_session_preparation(preparation_id="preparation.claimed")
    lookup = controller._intent_claim_store.find_for_observation
    monkeypatch.setattr(
        controller._intent_claim_store,
        "find_for_observation",
        lambda **_kwargs: object(),
    )
    with pytest.raises(ValueError, match="durable intent claim"):
        controller.cancel_session_preparation(preparation_id="preparation.claimed")
    assert session.session_id in controller._sessions
    monkeypatch.setattr(controller._intent_claim_store, "find_for_observation", lookup)
    controller.cancel_session_preparation(preparation_id="preparation.claimed")


def test_callsite_cleanup_retries_exact_managed_attempt_without_new_factory(tmp_path):
    assets = _Assets(count=2)
    claims = _Claims()
    windows = _WindowManager()
    controllers = []

    class Managed:
        def __init__(self, binding):
            self.binding = binding
            self.cancel_calls = []
            self.fail_cancel = True

        def start_session_preparation(self, *, preparation_id):
            self.preparation_id = preparation_id
            windows.bound.process_id = 4321
            return SimpleNamespace(
                session_id="session.managed",
                workflow=_workflow(
                    asset_id=self.binding.asset_id,
                    asset=assets.assets[self.binding.asset_id],
                ),
                target_window_handle=self.binding.target_window_handle,
                current_observation=_observation(),
            )

        def cancel_session_preparation(self, *, preparation_id):
            self.cancel_calls.append(preparation_id)
            assert preparation_id == self.preparation_id
            if self.fail_cancel:
                self.fail_cancel = False
                raise RuntimeError("cleanup blocked")

    def build(binding):
        controller = Managed(binding)
        controllers.append(controller)
        return controller

    selection = _selection(assets)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=windows,
        claim_store=claims,
        controller_factory=build,
        selection=selection,
    )

    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        service.start_session()
    assert raised.value.code == "agent_runtime_cleanup_required"
    assert raised.value.retry_preparation is True
    assert len(controllers) == 1

    proof = service.cancel_local_preparation()
    assert proof == _cleanup(selection)
    assert service.cancel_local_preparation() == proof
    assert len(controllers) == 1
    assert controllers[0].cancel_calls == [
        controllers[0].preparation_id,
        controllers[0].preparation_id,
    ]


def test_legacy_start_failure_is_unknown_and_cannot_be_restarted_or_cleared(tmp_path):
    assets = _Assets(count=2)
    calls = []

    class Legacy:
        def start_session(self):
            raise RuntimeError("unknown partial start")

    def build(_binding):
        calls.append("factory")
        return Legacy()

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=_Claims(),
        controller_factory=build,
        selection=_selection(assets),
    )
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        service.start_session()
    assert raised.value.retry_preparation is False
    with pytest.raises(AgentRuntimeCallsiteError) as cleanup:
        service.cancel_local_preparation()
    assert cleanup.value.code == "agent_runtime_cleanup_required"
    with pytest.raises(AgentRuntimeCallsiteError):
        service.start_session()
    assert calls == ["factory"]


def test_initial_safe_stop_returns_idempotent_public_cleanup_proof(
    tmp_path, monkeypatch
):
    from tests.test_live_controller_w4 import (
        _asset,
        _current_observation,
        _projected_agent_observation,
    )

    asset = _asset()
    digest = content_sha256(asset)
    controller, source, _, _, backend = _controller(
        tmp_path / "safe", target_window_handle=76104
    )
    contender, _, _, _, contender_backend = _controller(
        tmp_path / "contender", target_window_handle=76104
    )

    def safe_stop(**kwargs):
        current = _current_observation(asset, anchors=("anchor_apply_entry",))
        return _projected_agent_observation(
            asset, kwargs["session_id"], kwargs["workflow"], current
        )

    monkeypatch.setattr(source, "create_initial", safe_stop)
    selection = RuntimeSessionSelection(asset["asset_id"], digest, 76104, 9001)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=SimpleNamespace(
            registry=lambda: {"active_by_asset": {asset["asset_id"]: digest}},
            load_active=lambda _asset_id: deepcopy(asset),
        ),
        window_manager=SimpleNamespace(
            get_bound_window=lambda: SimpleNamespace(
                handle=76104, process_id=9001, is_active=True
            )
        ),
        claim_store=controller._intent_claim_store,
        controller_factory=lambda _binding: controller,
        selection=selection,
    )

    observation = service.start_session()
    assert observation.safe_stop.required is True
    proof = service.cancel_local_preparation()
    assert proof == _cleanup(selection)
    assert service.cancel_local_preparation() == proof
    restarted = contender.start_session()
    contender.abandon_session(session_id=restarted.session_id)
    assert backend.attempt_count == contender_backend.attempt_count == 0


def test_managed_start_retains_exact_lease_when_failure_cleanup_must_retry(
    tmp_path, monkeypatch
):
    controller, source, _, _, _ = _controller(
        tmp_path / "owner", target_window_handle=76105
    )
    contender, _, _, _, _ = _controller(
        tmp_path / "contender", target_window_handle=76105
    )
    release = controller._release_window_lease
    release_calls = 0

    def fail_once(lease):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            raise RuntimeError("release unavailable")
        return release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    monkeypatch.setattr(
        source,
        "create_initial",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("capture failed")),
    )
    with pytest.raises(RuntimeError, match="preparation cleanup"):
        controller.start_session_preparation(preparation_id="preparation.retry")
    with pytest.raises(RuntimeError, match="lease"):
        contender.start_session()

    controller.cancel_session_preparation(preparation_id="preparation.retry")
    restarted = contender.start_session()
    contender.abandon_session(session_id=restarted.session_id)
    assert release_calls == 2


def test_explicit_same_selection_retry_cleans_before_starting_again():
    selection = RuntimeSessionSelection("portfolio.seek1", "a" * 64, 77, 1234)

    class Runtime:
        def __init__(self):
            self.starts = 0
            self.cleanups = 0

        def start_session(self):
            self.starts += 1
            if self.starts == 1:
                raise AgentRuntimeCallsiteError(
                    status_code=503,
                    code="agent_runtime_cleanup_required",
                    message="injected",
                    retry_preparation=True,
                )
            return _observation()

        def cancel_local_preparation(self):
            self.cleanups += 1
            return _cleanup(selection)

    runtime = Runtime()
    coordinator = _coordinator(runtime)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as first:
            _prepare(coordinator)
        assert first.value.retry_preparation is True
        assert runtime.starts == 1 and runtime.cleanups == 0

        assert _prepare(coordinator)["phase"] == "observed"
        assert runtime.cleanups == 1 and runtime.starts == 2
    finally:
        try:
            coordinator.cancel()
            coordinator.shutdown()
        finally:
            coordinator._owner.close()


def test_cancel_partial_preparation_requires_exact_proof_and_keeps_host_ready_on_failure():
    selection = RuntimeSessionSelection("portfolio.seek1", "a" * 64, 77, 1234)

    class Runtime:
        def __init__(self):
            self.fail_cleanup = True

        def start_session(self):
            raise AgentRuntimeCallsiteError(
                status_code=503,
                code="agent_runtime_cleanup_required",
                message="injected",
                retry_preparation=True,
            )

        def cancel_local_preparation(self):
            if self.fail_cleanup:
                raise RuntimeError("cleanup unavailable")
            return _cleanup(selection)

    host = _Host()
    runtime = Runtime()
    coordinator = _coordinator(runtime, host=host)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            _prepare(coordinator)
        with pytest.raises(NativeSingleStepCoordinatorError) as pending:
            coordinator.cancel()
        assert pending.value.code == "runtime_cleanup_pending"
        assert host.status()["phase"] == "ready" and host.close_calls == 0

        runtime.fail_cleanup = False
        assert coordinator.cancel() == {"phase": "idle", "cleanup_verified": True}
        assert host.close_calls == 0
        coordinator.shutdown()
        assert host.close_calls == 1
    finally:
        coordinator._owner.close()


def test_shutdown_cleans_unattached_preparation_before_stopping_host():
    events: list[str] = []
    selection = RuntimeSessionSelection("portfolio.seek1", "a" * 64, 77, 1234)

    class Runtime:
        def start_session(self):
            raise AgentRuntimeCallsiteError(
                status_code=503,
                code="agent_runtime_cleanup_required",
                message="injected",
                retry_preparation=True,
            )

        def cancel_local_preparation(self):
            events.append("runtime.cleanup")
            return _cleanup(selection)

    host = _Host(events)
    coordinator = _coordinator(Runtime(), host=host)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            _prepare(coordinator)
        coordinator.shutdown()
        assert events == ["runtime.cleanup", "host.close"]
    finally:
        coordinator._owner.close()


@pytest.mark.parametrize("tamper", ["selection", "bool", "extra"])
def test_coordinator_rejects_forged_local_cleanup_proof_and_retains_owner(tamper):
    selection = RuntimeSessionSelection("portfolio.seek1", "a" * 64, 77, 1234)

    class Runtime:
        valid = False

        def start_session(self):
            raise AgentRuntimeCallsiteError(
                status_code=503,
                code="agent_runtime_cleanup_required",
                message="injected",
                retry_preparation=True,
            )

        def cancel_local_preparation(self):
            proof = _cleanup(selection)
            if not self.valid:
                if tamper == "selection":
                    proof["selection"]["target_process_id"] = 4321
                elif tamper == "bool":
                    proof["cleanup_verified"] = 1
                else:
                    proof["extra"] = "forged"
            return proof

    runtime = Runtime()
    coordinator = _coordinator(runtime)
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            _prepare(coordinator)
        with pytest.raises(NativeSingleStepCoordinatorError) as rejected:
            coordinator.cancel()
        assert rejected.value.code == "runtime_cleanup_pending"
        runtime.valid = True
        assert coordinator.cancel()["cleanup_verified"] is True
        coordinator.shutdown()
    finally:
        coordinator._owner.close()
