"""输入组合的共享请求合同；校验回执不加载执行器。"""
from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputSequenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_goal: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1, max_length=20000)
    clear_existing: bool = True
    submit_search: bool
    target_memory: dict[str, str] | None = None
    target: dict | None = None

    @field_validator("target")
    @classmethod
    def validate_target(cls, value):
        if value is None:
            return None
        from .control_target_contract import validate_task_plan_control_target
        return validate_task_plan_control_target(value, for_input=True)

    @field_validator("target_memory")
    @classmethod
    def validate_target_memory(cls, value):
        if value is None:
            return None
        from app.learning_memory.target_recipe import validate_target_reference
        return validate_target_reference(value)
