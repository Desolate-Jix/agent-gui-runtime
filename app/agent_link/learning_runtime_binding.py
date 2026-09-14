from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agent.action_learning_recorder import ActionLearningRecorder
from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_segments import LearningSegmentOwner


@dataclass(frozen=True, slots=True)
class LearningRuntimeBinding:
    """连接拥有的可信活动学习段上下文。"""

    owner: LearningSegmentOwner
    connection_id: str
    task_id: str
    segment_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.owner, LearningSegmentOwner):
            raise TypeError("owner must be LearningSegmentOwner")
        # 创建绑定前校验活动段；不能把已关闭段带入模型准备。
        segment = self.owner.get(
            connection_id=self.connection_id,
            task_id=self.task_id,
            segment_id=self.segment_id,
        )
        if segment["status"] != "active":
            raise AgentLinkError("learning_busy", "learning segment is not active")

    @property
    def project_root(self) -> Path:
        return self.owner.recorder.project_root

    @property
    def recorder(self) -> ActionLearningRecorder:
        return self.owner.recorder

    def attach_validated_runtime(self, *, runtime_session_id: str) -> dict:
        return self.owner.attach_runtime(
            connection_id=self.connection_id,
            task_id=self.task_id,
            segment_id=self.segment_id,
            runtime_session_id=runtime_session_id,
        )

    def close_unconsumed(self, *, runtime_session_id: str) -> dict:
        return self.owner.close_unconsumed_runtime(
            connection_id=self.connection_id,
            task_id=self.task_id,
            segment_id=self.segment_id,
            runtime_session_id=runtime_session_id,
        )
