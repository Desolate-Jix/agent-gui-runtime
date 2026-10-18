"""连接范围内的首次观察入口，复用来源与图所有者而不执行动作。"""

import base64
from copy import deepcopy
import json
from threading import Lock

from app.agent.fresh_learning_observation import (
    FreshLearningObservationOwner, _application_identity, _goal,
)
from app.agent_link.contracts import AgentLinkError, canonical_hash, MAX_LOCAL_IMAGE_RESPONSE_BYTES
from app.agent_link.fresh_graph_source import FreshGraphSourceOwner
from app.agent_link.learning_segments import MAX_SEGMENT_OBSERVATIONS
from .observation_timing import timed_observation, timed_call


OBSERVATION_CAPABILITY = {
    "contract_version": "agent_learning_observation_v1",
    "operations": ["observe_learning_screen", "submit_observed_interface_learning"],
}
MAX_OBSERVATION_RESPONSE_BYTES = MAX_LOCAL_IMAGE_RESPONSE_BYTES


class LearningObservationProvider:
    def __init__(self, source_owner: FreshGraphSourceOwner):
        if not isinstance(source_owner, FreshGraphSourceOwner):
            raise TypeError("fresh observation requires the native source owner")
        self.source_owner = source_owner
        self._capture_guard = Lock()
        self._managed_observer = None
        from .learning_content import LearningContentProvider
        self.content = LearningContentProvider(self)

    def bind_managed_observer(self, observer) -> None:
        """绑定协调器的被动目标观察；未安装时必须显式拒绝模型请求。"""
        if not callable(observer):
            raise TypeError("managed observer must be callable")
        self._managed_observer = observer

    def submit_observed_interface_learning(self, **kwargs):
        from .observed_interface_learning import submit_observed_interface_learning
        return submit_observed_interface_learning(self.source_owner.facade, **kwargs)

    @timed_observation('observe_learning_screen')
    def observe(self, *, connection_id, task_id, segment_id, idempotency_key,
                application_identity, target_window_handle, target_process_id,
                title, meaning, goal=None):
        request = _checked_request(application_identity, target_window_handle,
            target_process_id, title, meaning, goal, idempotency_key)
        identity = {"connection_id": connection_id, "task_id": task_id, "segment_id": segment_id}
        request_sha256 = canonical_hash({**identity, **request})
        if not self._capture_guard.acquire(blocking=False):
            raise AgentLinkError("learning_busy", "another learning observation is in progress")
        try:
            current = self.source_owner.segments.get(**identity)
            if current["status"] != "active":
                raise AgentLinkError("learning_busy", "learning segment is not active")
            request_id = canonical_hash({**identity, "key": idempotency_key})
            batch_id = "fresh-batch-" + request_id
            previous = self.source_owner.segments.store.read(lambda state: state["batches"].get(batch_id))
            if previous is not None:
                source = previous.get("fresh_learning_source", {})
                if (source.get("observation_request_sha256") != request_sha256
                        or any(source.get(key) != value for key, value in identity.items())):
                    raise AgentLinkError("idempotency_conflict", "observation key was used with another request")
                try:
                    packet = self.source_owner.archive.read(source["reference"], **identity)
                except (ValueError, OSError, KeyError) as error:
                    raise AgentLinkError("learning_source_unavailable", "committed observation source is unavailable") from error
            else:
                if len(current.get("observations", [])) >= MAX_SEGMENT_OBSERVATIONS:
                    raise AgentLinkError("learning_capacity_exceeded", "finish this segment before observing more screens")
                try:
                    if goal is not None:
                        observer = self._managed_observer
                        if observer is None:
                            raise AgentLinkError(
                                "learning_runtime_unavailable",
                                "targeted observation requires the managed learning runtime",
                            )
                        packet = observer(
                            application_identity=request["application_identity"],
                            target_window_handle=target_window_handle,
                            target_process_id=target_process_id,
                            goal=goal,
                        )
                    else:
                        from app.agent.fresh_learning_factory import create_fresh_learning_observation_owner

                        owner = create_fresh_learning_observation_owner(
                            project_root=self.source_owner.archive.project_root,
                            application_identity=request["application_identity"],
                            target_window_handle=target_window_handle, target_process_id=target_process_id)
                        if (not isinstance(owner, FreshLearningObservationOwner)
                                or owner.project_root != self.source_owner.archive.project_root
                                or owner.application != request["application_identity"]):
                            raise ValueError("observation owner binding is invalid")
                        bundle = timed_call('observation.capture', owner.observe_with_uia, target_window_handle=target_window_handle,
                            target_process_id=target_process_id)
                        packet = bundle.packet
                        self.content.record_source_context(packet, bundle.uia_snapshot())
                except AgentLinkError:
                    raise
                except (OSError, ValueError, TypeError, RuntimeError) as error:
                    reason = _safe_visibility_reason(error)
                    if reason is not None:
                        raise AgentLinkError(reason,
                            "请恢复并露出目标窗口后重试；未产生学习结果或输入。 / Restore and uncover the target window before retrying; no learning result or input was produced.") from error
                    raise AgentLinkError("observation_failed", "the explicit target could not be observed") from error
            staged = self.source_owner.stage(**identity, idempotency_key=idempotency_key,
                title=title, meaning=meaning, packet=packet,
                observation_request_sha256=request_sha256)
            interface_memory = self.source_owner.facade.import_interface_content(
                task_id, staged["batch_id"], "observed-screen"
            )
            evidence = packet.evidence()
            from .scroll_container_discovery import discover_scroll_containers
            response = {
                **deepcopy(staged), "contract_version": OBSERVATION_CAPABILITY["contract_version"],
                "segment_id": segment_id, "observation": evidence,
                "interface_memory": deepcopy(interface_memory),
                "scroll_containers": discover_scroll_containers(packet, self.content._source_context),
                "screenshot": {"mime_type": "image/png",
                    "sha256": evidence["capture"]["screenshot_sha256"],
                    **evidence["capture"]["viewport_size"],
                    "png_base64": base64.b64encode(packet.png_bytes).decode("ascii")},
            }
            if len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_OBSERVATION_RESPONSE_BYTES:
                raise AgentLinkError("observation_too_large", "the observation exceeds the response limit")
            return response
        finally:
            self._capture_guard.release()


def _safe_visibility_reason(error):
    from app.core.screenshot import CaptureVisibilityError

    # 只识别受控异常类型；未知异常文字不能伪装成可以恢复窗口的原因。
    current = error
    for _ in range(8):
        if isinstance(current, CaptureVisibilityError):
            return current.reason if current.reason in {"capture_window_minimized", "capture_window_occluded"} else None
        current = getattr(current, "__cause__", None)
        if current is None:
            break
    return None


def _checked_request(application_identity, handle, process_id, title, meaning, goal, key):
    try:
        application = _application_identity(application_identity)
        checked_goal = _goal(goal)
        if any(type(value) is not int or value < 1 for value in (handle, process_id)):
            raise ValueError("target must be a positive integer")
        for value, limit in ((key, 128), (title, 512), (meaning, 4000)):
            if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
                raise ValueError("observation text is invalid")
    except (TypeError, ValueError) as error:
        raise AgentLinkError("invalid_arguments", "observation target, application or text is invalid") from error
    return {"application_identity": application, "target_window_handle": handle,
            "target_process_id": process_id, "title": title, "meaning": meaning,
            "goal": checked_goal, "idempotency_key": key}
