"""首次学习会话的显式来源与被动观察，不提供动作权限。"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.fresh_learning_observation import FreshLearningObservationPacket
    from app.agent.fresh_learning_runtime_source import FreshLearningRuntimeSource


@dataclass(frozen=True, slots=True)
class ServerFreshLearningBinding:
    source: FreshLearningRuntimeSource

    def __post_init__(self):
        from app.agent.fresh_learning_runtime_source import FreshLearningRuntimeSource

        if not isinstance(self.source, FreshLearningRuntimeSource):
            raise TypeError("fresh learning binding requires a verified runtime source")

    @property
    def target_window_handle(self):
        return self.source.reference()["target_window_handle"]


@dataclass(frozen=True, slots=True)
class FreshLearningRuntimeObservation:
    observation_id: str
    packet: FreshLearningObservationPacket = field(repr=False)
    payload_json: bytes = field(repr=False)

    def to_dict(self):
        return json.loads(self.payload_json.decode("utf-8"))


@dataclass(frozen=True, slots=True)
class FreshLearningSessionSnapshot:
    session_id: str
    source: FreshLearningRuntimeSource
    current_observation: FreshLearningRuntimeObservation
    target_window_handle: int
    target_process_id: int


def validate_fresh_runtime_owners(source, source_owner, observation_owner, project_root):
    from app.agent.fresh_learning_observation import FreshLearningObservationOwner
    from app.agent_link.fresh_graph_source import FreshGraphSourceOwner

    if not isinstance(source_owner, FreshGraphSourceOwner):
        raise TypeError("fresh learning session requires its actual source owner")
    if not isinstance(observation_owner, FreshLearningObservationOwner):
        raise TypeError("fresh learning session requires its actual passive observation owner")
    if (source.project_root != project_root or source_owner.archive.project_root != project_root
            or observation_owner.project_root != project_root):
        raise ValueError("fresh learning runtime owners must share the claim store project root")
    if observation_owner.application != source.reference()["application_identity"]:
        raise ValueError("fresh learning observation application does not match source")


def observe_fresh_runtime_session(*, source, source_owner, observation_owner, session_id):
    from app.agent.fresh_learning_runtime_source import reload_fresh_learning_runtime_source

    reference = source.reference()
    packet = observation_owner.observe(
        target_window_handle=reference["target_window_handle"],
        target_process_id=reference["target_process_id"], goal=None,
    )
    evidence = packet.evidence()
    # 新截图可改变界面，但不可换应用、进程实例或目标窗口。
    if (evidence["application"] != source.packet.evidence()["application"]
            or evidence["target"]["window_handle"] != reference["target_window_handle"]
            or evidence["target"]["process_id"] != reference["target_process_id"]):
        raise ValueError("fresh learning target application or process changed")
    if evidence["capture"]["capture_id"] == source.packet.evidence()["capture"]["capture_id"]:
        raise ValueError("fresh learning session requires a new passive capture")
    reload_fresh_learning_runtime_source(source_owner, source)
    capture_source = source_owner.archive.record(packet,
        connection_id=reference["connection_id"], task_id=reference["task_id"],
        segment_id=reference["segment_id"])
    reload_fresh_learning_runtime_source(source_owner, source)
    observation_id = "observation." + evidence["capture"]["capture_id"]
    payload = {
        "contract_version": "fresh_learning_runtime_observation_v1",
        "session_id": session_id, "observation_id": observation_id,
        "source": reference, "capture_source": capture_source,
        "capture": evidence["capture"], "application": evidence["application"],
        "state": "unreviewed", "available_actions": [], "execution_ready": False,
        "artifact_is_authorization": False, "execute_binding_enabled": False,
        "action_executed": False,
    }
    observation = FreshLearningRuntimeObservation(observation_id, packet,
        json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8"))
    return FreshLearningSessionSnapshot(session_id, source, observation,
        reference["target_window_handle"], reference["target_process_id"])
