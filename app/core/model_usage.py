"""校验供应商或调用方明确提供的 token 计数，不推算缺失用量。"""
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: StrictInt = Field(ge=0)
    output_tokens: StrictInt = Field(ge=0)
    total_tokens: StrictInt | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_total(self):
        if self.total_tokens is not None and self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("model_usage_total_invalid")
        return self

    def counts(self):
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens if self.total_tokens is not None
                else self.input_tokens + self.output_tokens}
