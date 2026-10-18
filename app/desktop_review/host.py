"""原生审核与 Agent Link 接收服务的共享宿主。"""

from __future__ import annotations

import math
import hashlib
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
import secrets
import time
from threading import RLock, Thread
from typing import Any
from uuid import uuid4

from app.agent_link.contracts import AgentLinkError
from app.agent_link.host import AgentLinkHttpHostError, OwnedAgentLinkHttpHost
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore

from .connections import NativeConnectionController
from .single_step import (
    NativeSingleStepController,
    NativeSingleStepError,
    OwnedSingleStepClient,
)
from .workspace import DesktopReviewError, NativeReviewFacade


class DesktopHostError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _RuntimeCleanupWork:
    confirmation_id: str
    future: Future[None]
    thread: Thread


class DesktopReviewHost:
    def __init__(
        self,
        state_path: Path,
        review_root: Path,
        reviewer_token: str,
        *,
        port: int = 0,
    ) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise DesktopHostError("invalid_port", "port must be 0 or in 1..65535")
        self._guard = RLock()
        self._lifecycle_guard = RLock()
        self._phase = "created"
        self._host_id = "host-" + uuid4().hex
        self._base_url: str | None = None
        self._resources_closed = False
        self._execution_token: str | None = secrets.token_urlsafe(32)
        self._single_step_controller = NativeSingleStepController()
        self._execution_enabled = False
        self._runtime_releasing = False
        self._runtime_cleanup_confirmation_id: str | None = None
        self._runtime_cleanup_work: _RuntimeCleanupWork | None = None
        self.single_step: OwnedSingleStepClient | None = None
        self._store: AgentLinkStore | None = None
        self._http: OwnedAgentLinkHttpHost | None = None
        self.facade: NativeReviewFacade
        self.connections: NativeConnectionController
        try:
            self._store = AgentLinkStore(state_path)
            service = AgentLinkService(self._store, reviewer_token)
            self._service = service
            self._reviewer_token = reviewer_token
            self.facade = NativeReviewFacade(service, reviewer_token, review_root)
            service.bind_workflow_memory_reader(reviewer_token, self.facade)
            service.bind_interface_content_gateway(reviewer_token, self.facade)
            from app.agent.action_learning_recorder import ActionLearningRecorder
            from app.agent.action_learning_capture_archive import ActionLearningCaptureArchive
            from app.agent_link.learning_segments import LearningSegmentOwner

            recorder = ActionLearningRecorder(project_root=review_root)
            self.learning_segments = LearningSegmentOwner(
                self._store, recorder=recorder,
                capture_archive=ActionLearningCaptureArchive(recorder=recorder),
            )
            service.bind_learning_segment_owner(reviewer_token, self.learning_segments)
            self.learning_runtime = None
            self.application_startup = None
            from app.agent_link.fresh_graph_source import FreshGraphSourceOwner

            self.fresh_learning = FreshGraphSourceOwner(self.learning_segments, self.facade)
            from app.desktop_review.learning_observation import LearningObservationProvider

            self.learning_observation = LearningObservationProvider(self.fresh_learning)
            service.bind_learning_observation_provider(reviewer_token, self.learning_observation)
            assert self._execution_token is not None
            self._http = OwnedAgentLinkHttpHost(
                service,
                port=port,
                execution_controller=self._single_step_controller,
                execution_token_digest=hashlib.sha256(
                    self._execution_token.encode("utf-8")
                ).hexdigest(),
            )
            self.connections = NativeConnectionController(
                service, reviewer_token, self.status,
                lifecycle_guard=self._lifecycle_guard,
            )
        except AgentLinkHttpHostError as error:
            self._release_partial()
            raise DesktopHostError(error.code, error.message) from error
        except AgentLinkError as error:
            self._release_partial()
            raise DesktopHostError(error.code, "Agent Link state could not be opened") from error
        except DesktopReviewError as error:
            self._release_partial()
            code = "workspace_in_use" if "占用" in str(error) else "workspace_open_failed"
            raise DesktopHostError(code, "desktop review workspace could not be opened") from error
        except (OSError, TypeError, ValueError) as error:
            self._release_partial()
            raise DesktopHostError("construction_failed", "desktop host could not be created") from error

    def enable_learning_runtime(self, coordinator: Any) -> None:
        """复用既有协调器；能力只在真实准备入口安装后公开。"""
        from .learning_runtime import LearningRuntimeProvider

        with self._guard:
            if self.learning_runtime is not None:
                raise DesktopHostError("learning_busy", "learning runtime is already installed")
            provider = LearningRuntimeProvider(self.learning_segments, coordinator)
            observer = getattr(coordinator, "observe_learning_target_passively", None)
            if not callable(observer):
                raise DesktopHostError("learning_runtime_unavailable", "managed targeted observation is unavailable")
            self.learning_observation.bind_managed_observer(observer)
            self._service.bind_learning_runtime_provider(self._reviewer_token, provider)
            from .application_startup import ApplicationStartupProvider
            startup = ApplicationStartupProvider(self._store, coordinator)
            self._service.bind_application_startup_provider(self._reviewer_token, startup)
            self.learning_runtime = provider
            self.application_startup = startup

    def start(self, *, timeout: float = 5.0) -> dict[str, Any]:
        wait = _timeout(timeout)
        with self._lifecycle_guard:
            with self._guard:
                self._reconcile_http_locked()
                if self._phase == "ready":
                    return self._status_locked()
                if self._phase in {"starting", "stopping"}:
                    raise DesktopHostError("lifecycle_busy", "desktop host lifecycle is busy")
                if self._phase != "created":
                    raise DesktopHostError("invalid_phase", "desktop host cannot be restarted")
                self._phase = "starting"

        try:
            assert self._http is not None
            base_url = self._http.start(timeout=wait)
        except AgentLinkHttpHostError as error:
            terminal = False
            try:
                assert self._http is not None
                self._http.close(timeout=wait)
                terminal = True
            except AgentLinkHttpHostError as cleanup_error:
                if cleanup_error.code != "shutdown_timeout":
                    error = cleanup_error
            with self._lifecycle_guard:
                with self._guard:
                    self._base_url = None
                    self._phase = "failed" if terminal else "stopping"
                if terminal:
                    self._release_resources()
            raise DesktopHostError(error.code, error.message) from error

        with self._lifecycle_guard:
            with self._guard:
                if self._phase != "starting":
                    raise DesktopHostError("lifecycle_busy", "desktop host lifecycle changed")
                self._base_url = base_url
                self._phase = "ready"
                self._single_step_controller.set_accepting(True)
                return self._status_locked()

    def attach_grounded_runtime(
        self,
        callsite: Any,
        *,
        confirmation_id: str,
    ) -> dict[str, Any]:
        """附加同进程的确切 grounded owner，不接受 UI 自报目标。"""
        with self._lifecycle_guard:
            with self._guard:
                if self._runtime_releasing or self._runtime_cleanup_confirmation_id is not None:
                    raise DesktopHostError("lifecycle_busy", "grounded runtime is releasing")
                self._reconcile_http_locked()
                if self._phase != "ready" or self._base_url is None:
                    raise DesktopHostError(
                        "host_not_ready", "desktop host is not ready"
                    )
                base_url = self._base_url
                token = self._execution_token
            if token is None:
                raise DesktopHostError(
                    "execution_role_unavailable", "execution role is unavailable"
                )
            try:
                attachment = self._single_step_controller.attach(
                    callsite,
                    confirmation_id=confirmation_id,
                )
                client = self.single_step
                if client is None:
                    client = OwnedSingleStepClient(
                        base_url=base_url,
                        token=token,
                        confirmation_id=attachment.confirmation_id,
                    )
            except NativeSingleStepError as error:
                raise DesktopHostError(error.code, error.message) from None
            with self._guard:
                if self._phase != "ready" or self._base_url != base_url:
                    raise DesktopHostError(
                        "lifecycle_busy", "desktop host lifecycle changed"
                    )
                self.single_step = client
                self._execution_enabled = True
                return self._status_locked()

    def release_grounded_runtime(
        self,
        *,
        confirmation_id: str,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """释放 exact grounded owner，但保持 Agent Link 收件服务。"""
        wait = _timeout(timeout)
        deadline = time.monotonic() + wait
        with self._lifecycle_guard:
            with self._guard:
                self._reconcile_http_locked()
                if self._phase != "ready" or self._base_url is None:
                    raise DesktopHostError("host_not_ready", "desktop host is not ready")
                if self._runtime_releasing:
                    raise DesktopHostError("lifecycle_busy", "grounded runtime is releasing")
                pending_id = self._runtime_cleanup_confirmation_id
                if pending_id is not None and pending_id != confirmation_id:
                    raise DesktopHostError(
                        "confirmation_not_attached",
                        "the grounded confirmation is not attached to this host",
                    )
                attachment = self._single_step_controller.attachment_snapshot()
                if pending_id is None and (
                    attachment is None or attachment.confirmation_id != confirmation_id
                ):
                    raise DesktopHostError(
                        "confirmation_not_attached",
                        "the grounded confirmation is not attached to this host",
                    )
                client = self.single_step
                if client is None:
                    raise DesktopHostError(
                        "execution_role_unavailable", "execution role is unavailable"
                    )
                self._runtime_releasing = True
                self._runtime_cleanup_confirmation_id = confirmation_id
                client.invalidate()
                self._single_step_controller.set_accepting(False)
        try:
            client.wait_for_drain(_remaining(deadline))
            self._single_step_controller.wait_for_drain(_remaining(deadline))
            cleanup = self._cleanup_work(
                confirmation_id=confirmation_id,
                deadline=deadline,
            )
            self._wait_cleanup_work(cleanup, deadline=deadline)
        except NativeSingleStepError as error:
            with self._guard:
                self._runtime_releasing = False
            raise DesktopHostError(error.code, error.message) from None
        with self._lifecycle_guard:
            with self._guard:
                if self._phase != "ready":
                    self._runtime_releasing = False
                    raise DesktopHostError("lifecycle_busy", "desktop host lifecycle changed")
                self.single_step = None
                self._execution_enabled = False
                self._runtime_releasing = False
                self._runtime_cleanup_confirmation_id = None
                self._runtime_cleanup_work = None
                self._single_step_controller.set_accepting(True)
                return self._status_locked()

    def status(self) -> dict[str, Any]:
        with self._guard:
            self._reconcile_http_locked()
            return self._status_locked()

    def close(self, *, timeout: float = 5.0) -> None:
        wait = _timeout(timeout)
        deadline = time.monotonic() + wait
        with self._lifecycle_guard:
            with self._guard:
                if self._runtime_releasing:
                    raise DesktopHostError("lifecycle_busy", "grounded runtime is releasing")
                if self._phase == "stopped":
                    return
                if self._phase == "starting":
                    raise DesktopHostError("lifecycle_busy", "desktop host is starting")
                self._phase = "stopping"
                self._base_url = None
                client = self.single_step
                if client is not None:
                    client.invalidate()
        if not self._resources_closed:
            try:
                if client is not None:
                    client.wait_for_drain(_remaining(deadline))
                self._single_step_controller.set_accepting(False)
                assert self._http is not None
                self._http.close(timeout=_remaining(deadline))
                self._single_step_controller.wait_for_drain(_remaining(deadline))
                with self._guard:
                    cleanup_id = self._runtime_cleanup_confirmation_id
                    if cleanup_id is None:
                        attachment = self._single_step_controller.attachment_snapshot()
                        cleanup_id = (
                            attachment.confirmation_id
                            if attachment is not None
                            else None
                        )
                        self._runtime_cleanup_confirmation_id = cleanup_id
                if cleanup_id is not None:
                    cleanup = self._cleanup_work(
                        confirmation_id=cleanup_id,
                        deadline=deadline,
                    )
                    self._wait_cleanup_work(
                        cleanup,
                        deadline=deadline,
                    )
            except AgentLinkHttpHostError as error:
                with self._guard:
                    self._phase = "stopping"
                raise DesktopHostError(error.code, error.message) from error
            except NativeSingleStepError as error:
                with self._guard:
                    self._phase = "stopping"
                raise DesktopHostError(error.code, error.message) from None
            self._release_resources()
            self.single_step = None
            self._execution_token = None
            self._runtime_cleanup_confirmation_id = None
            self._runtime_cleanup_work = None
        with self._lifecycle_guard:
            with self._guard:
                self._phase = "stopped"

    def _status_locked(self) -> dict[str, Any]:
        common = {
            "host_id": self._host_id,
            "phase": self._phase,
            "base_url": self._base_url if self._phase == "ready" else None,
        }
        if self._execution_enabled:
            return {
                "contract_version": "native_review_host_v2",
                **common,
                "staging_only": False,
                "agent_link_staging_only": True,
                "reviewed_single_step_enabled": True,
                "automatic_execution_enabled": False,
            }
        return {
            "contract_version": "native_review_host_v1",
            **common,
            "staging_only": True,
        }

    def _cleanup_work(
        self,
        *,
        confirmation_id: str,
        deadline: float,
    ) -> _RuntimeCleanupWork:
        with self._guard:
            work = self._runtime_cleanup_work
            if work is not None and work.confirmation_id != confirmation_id:
                raise NativeSingleStepError(
                    "confirmation_not_attached",
                    "the grounded confirmation is not attached to this host",
                )
        if work is not None and work.future.done():
            work.thread.join(_remaining(deadline))
            if work.thread.is_alive():
                raise NativeSingleStepError(
                    "shutdown_timeout", "grounded runtime cleanup is still stopping",
                    result_unknown=True,
                )
            if work.future.exception() is None:
                return work
            # 上一次明确失败后，只有新的显式调用才创建下一次尝试。
            with self._guard:
                if self._runtime_cleanup_work is work:
                    self._runtime_cleanup_work = None
                    work = None
        if work is not None:
            return work
        future: Future[None] = Future()
        thread = Thread(
            target=self._run_cleanup_work,
            args=(confirmation_id, future),
            name="desktop-grounded-runtime-cleanup",
            daemon=False,
        )
        created = _RuntimeCleanupWork(confirmation_id, future, thread)
        with self._guard:
            current = self._runtime_cleanup_work
            if current is not None:
                if current.confirmation_id != confirmation_id:
                    raise NativeSingleStepError(
                        "confirmation_not_attached",
                        "the grounded confirmation is not attached to this host",
                    )
                return current
            self._runtime_cleanup_work = created
            thread.start()
            return created

    def _run_cleanup_work(
        self,
        confirmation_id: str,
        future: Future[None],
    ) -> None:
        try:
            self._single_step_controller.cleanup_attachment(
                confirmation_id=confirmation_id
            )
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(None)

    @staticmethod
    def _wait_cleanup_work(
        work: _RuntimeCleanupWork,
        *,
        deadline: float,
    ) -> None:
        try:
            work.future.result(timeout=_remaining(deadline))
        except FutureTimeoutError:
            raise NativeSingleStepError(
                "shutdown_timeout", "grounded runtime cleanup is still active",
                result_unknown=True,
            ) from None
        except BaseException:
            work.thread.join(_remaining(deadline))
            if work.thread.is_alive():
                raise NativeSingleStepError(
                    "shutdown_timeout", "grounded runtime cleanup is still stopping",
                    result_unknown=True,
                ) from None
            raise
        work.thread.join(_remaining(deadline))
        if work.thread.is_alive():
            raise NativeSingleStepError(
                "shutdown_timeout", "grounded runtime cleanup is still stopping",
                result_unknown=True,
            )

    def _reconcile_http_locked(self) -> None:
        if self._phase != "ready":
            return
        http = self._http
        if (
            http is None
            or http.phase != "ready"
            or http.base_url != self._base_url
        ):
            self._phase = "failed"
            self._base_url = None
            if self.single_step is not None:
                self.single_step.invalidate()
            self._single_step_controller.set_accepting(False)

    def _release_resources(self) -> None:
        if self._resources_closed:
            return
        self.facade.close()
        assert self._store is not None
        self._store.close()
        self._resources_closed = True

    def _release_partial(self) -> None:
        facade = getattr(self, "facade", None)
        if facade is not None:
            facade.close()
        store = self._store
        if store is not None:
            store.close()
        self._resources_closed = True


def _timeout(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DesktopHostError("invalid_timeout", "timeout must be positive")
    return float(value)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NativeSingleStepError(
            "shutdown_timeout", "grounded runtime release timed out",
            result_unknown=True,
        )
    return remaining
