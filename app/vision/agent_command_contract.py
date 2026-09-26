"""组合动作的显式续行协议，不接受替换坐标或重新提交原始输入。"""
from pydantic import BaseModel, ConfigDict, Field


class AgentCommandReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")


class AgentCommandContinue(AgentCommandReference):
    grounding_request_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")


AGENT_COMMANDS = {
    'agent_command_status': AgentCommandReference,
    'agent_command_cancel': AgentCommandReference,
    'agent_command_continue': AgentCommandContinue,
}
