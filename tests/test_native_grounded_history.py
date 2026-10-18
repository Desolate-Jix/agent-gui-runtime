from types import SimpleNamespace

import pytest

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_agent_runtime_grounded_preview import live
from tests.test_agent_runtime_grounded_recovery import _checkpoint, _pending, _reopen, _release_test_processes
from tests.test_native_single_step_coordinator import _Facade, _Host


def _native(live, tmp_path):
    created = []
    bindings = []

    def bind(handle):
        bindings.append(handle)
        assert handle == live.windows.bound.handle
        return live.windows.bound

    live.windows.bind_window_by_handle = bind

    def factory(*, project_root, selection, window_manager):
        runtime, claims, built = _reopen(live, project_root, selection=selection)
        created.append((runtime, claims, built))
        return runtime

    factory.window_manager = live.windows
    coordinator = NativeSingleStepCoordinator(
        tmp_path, _Facade(), _Host(), runtime_factory=factory,
        thread_initializer=lambda: None, thread_finalizer=lambda: None,
        foreground_timeout=.01,
    )
    return coordinator, created, bindings


def test_native_reopened_history_discovers_checkpoint_and_recovers_exact_target(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    co, created, bindings = _native(live, tmp_path)
    try:
        history = co.history()
        assert history["contract_version"] == "native_grounded_history_v1"
        assert history["artifact_is_authorization"] is False
        item = history["items"][0]
        assert item["confirmation_id"] == cid
        assert item["operation"] == "verify_postcheck"
        assert not created and not bindings
        result = co.recover_history(confirmation_id=cid)
        assert result["item"]["phase"] == "terminal"
        assert result["owner_retained"] is False
        assert result["item"]["receipt"]["attempt_count"] == 1
        assert created[0][2][0][1].attempt_count == 0
        assert bindings == [88401]
        again = co.recover_history(confirmation_id=cid)
        assert again["item"] == result["item"]
        assert len(created) == 1
        assert co._host.single_step is None
    finally:
        co._owner.close()


@pytest.mark.parametrize("approve", [False, True])
def test_native_history_closes_old_approval_without_runtime(live, tmp_path, approve):
    cid = _pending(live, approve=approve)
    co, created, bindings = _native(live, tmp_path)
    try:
        assert co.history()["items"][0]["operation"] == "close_unexecuted"
        result = co.recover_history(confirmation_id=cid)
        assert result["item"]["phase"] == "grounded_confirmation_closed"
        assert result["item"]["reason_code"] == "grounded_confirmation_restarted"
        assert not created and not bindings
        assert live.backends[0].attempt_count == 0
    finally:
        co._owner.close()


@pytest.mark.parametrize("fail_at", ["mark_grounded_dispatch_started", "mark_grounded_verification_pending"])
def test_native_indeterminate_history_never_constructs_or_inputs(live, tmp_path, monkeypatch, fail_at):
    cid = _checkpoint(live, monkeypatch, fail_at=fail_at)
    co, created, bindings = _native(live, tmp_path)
    try:
        item = co.history()["items"][0]
        assert item["operation"] == "indeterminate"
        assert co.recover_history(confirmation_id=cid)["item"] == item
        assert not created and not bindings
    finally:
        co._owner.close()


def test_native_recovery_rejects_changed_process_before_factory(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    co, created, _ = _native(live, tmp_path)
    live.windows.bound.process_id += 1
    try:
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.recover_history(confirmation_id=cid)
        assert error.value.code == "target_window_changed"
        assert not created
    finally:
        co._owner.close()


def test_native_active_normal_session_cannot_open_history(live, tmp_path):
    _pending(live)
    co, _, _ = _native(live, tmp_path)
    co._phase = "approved"
    try:
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.history()
    finally:
        co._owner.close()


def test_native_terminal_cleanup_retry_retains_exact_owner_without_recapture(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    co, created, bindings = _native(live, tmp_path)
    factory = co._runtime_factory
    releases = []

    def failing_factory(**kwargs):
        runtime = factory(**kwargs)
        build = runtime._controller_factory

        def build_with_cleanup_failure(binding):
            controller = build(binding)
            release = controller._release_window_lease

            def fail_once(lease):
                releases.append(lease)
                if len(releases) == 1:
                    raise RuntimeError("synthetic native cleanup failure")
                return release(lease)

            monkeypatch.setattr(controller, "_release_window_lease", fail_once)
            return controller

        runtime._controller_factory = build_with_cleanup_failure
        return runtime

    co._runtime_factory = failing_factory
    try:
        first = co.recover_history(confirmation_id=cid)
        assert first["owner_retained"] is True
        assert first["item"]["phase"] == "terminal"
        assert co.history()["retained_confirmation_id"] == cid
        captured = live.sources[0].projected_calls
        for action in (co.cancel, co.shutdown):
            with pytest.raises(NativeSingleStepCoordinatorError) as error:
                action()
            assert error.value.code == "grounded_recovery_owner_busy"
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.recover_history(confirmation_id="grounded-confirmation." + "0" * 64)
        assert error.value.code == "grounded_recovery_owner_busy"
        live.windows.bound = None
        second = co.recover_history(confirmation_id=cid)
        assert second["owner_retained"] is False
        assert len(created) == 1 and len(releases) == 2 and len(bindings) == 1
        assert live.sources[0].projected_calls == captured
        assert created[0][2][0][1].attempt_count == 0
        co.shutdown()
    finally:
        co._owner.close()


def test_native_factory_failure_retains_unknown_owner_and_never_recreates(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    co, created, bindings = _native(live, tmp_path)
    attempts = []

    def fail(**kwargs):
        attempts.append(kwargs)
        raise RuntimeError("synthetic unknown native factory")

    co._runtime_factory = fail
    try:
        for _ in range(2):
            with pytest.raises(NativeSingleStepCoordinatorError):
                co.recover_history(confirmation_id=cid)
        assert len(attempts) == 1
        assert co.history()["retained_confirmation_id"] == cid
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.cancel()
    finally:
        co._owner.close()


def test_native_history_rejects_corrupt_request_instead_of_showing_unverified_record(live, tmp_path):
    _pending(live)
    co, created, bindings = _native(live, tmp_path)
    try:
        paths = list(live.claims.grounded_requests_root.glob("*.json"))
        assert paths
        paths[0].write_text("{}", encoding="utf-8")
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co.history()
        assert error.value.code == "grounded_history_unavailable"
        assert not created and not bindings
    finally:
        co._owner.close()
