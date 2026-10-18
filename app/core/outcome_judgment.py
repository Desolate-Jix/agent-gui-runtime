"""执行和学习共用的可选判断合同；不含供应商连接或动作授权。"""
from hashlib import sha256
import json
from time import perf_counter_ns
from typing import Annotated, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .model_usage import ModelUsage


Text = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class JudgmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_id: Text
    sha256: Digest
    window_id: Text
    role: Literal["before", "after"]
    image_ref: Text | None = None
    text: Text | None = None

    @model_validator(mode="after")
    def require_content(self):
        if self.image_ref is None and self.text is None:
            raise ValueError("judgment_evidence_content_required")
        return self


class JudgmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: Text
    mode: Literal["execution", "learning"]
    execution_request_id: Text
    condition: Text
    evidence: list[JudgmentEvidence] = Field(min_length=1, max_length=2)
    run_id: Text | None = None
    step_id: Text | None = None

    @model_validator(mode="after")
    def validate_binding(self):
        if self.mode == "learning" and (self.run_id is None or self.step_id is None):
            raise ValueError("judgment_learning_binding_required")
        if len({item.capture_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("judgment_duplicate_capture")
        if len({item.window_id for item in self.evidence}) != 1:
            raise ValueError("judgment_window_binding_mismatch")
        if [item.role for item in self.evidence].count("after") != 1:
            raise ValueError("judgment_current_evidence_required")
        return self


class JudgmentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_sha256: Digest
    answer: StrictBool | None
    probability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False, strict=True)
    usage: ModelUsage | None = None


class JudgmentProvider(Protocol):
    provider_id: str
    model_id: str
    supports_images: bool

    def judge(self, payload: dict) -> dict:
        """适配器须限制网络超时；超时抛 TimeoutError，服务/协议失败抛 OSError/ValueError。"""
        ...


class OptionalJudgment:
    def __init__(self, *, enabled: bool = False, provider: JudgmentProvider | None = None):
        if type(enabled) is not bool:
            raise ValueError("judgment_enabled_must_be_boolean")
        self.enabled, self.provider = enabled, provider

    def evaluate(self, request_factory: Callable[[], dict]) -> dict:
        result = {"status": "disabled", "verdict": "uncertain", "source": "judgment_model",
                  "probability": None, "usage": None, "authorizes_action": False,
                  "automatic_retry_allowed": False}
        # 未接入时不采图、不读证据、不探测网络，不增加业务等待。
        if not self.enabled:
            return result
        if self.provider is None:
            return {**result, "status": "not_connected"}
        request = JudgmentRequest.model_validate(request_factory())
        payload = request.model_dump(mode="json", exclude_none=True)
        digest = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":")).encode("utf-8")).hexdigest()
        result.update(request_id=request.request_id, request_sha256=digest,
                      execution_request_id=request.execution_request_id,
                      provider=self.provider.provider_id, model=self.provider.model_id)
        if any(item.image_ref is not None for item in request.evidence) and not self.provider.supports_images:
            return {**result, "status": "unsupported", "reason": "judgment_image_input_unsupported"}
        started = perf_counter_ns()
        try:
            answer = JudgmentAnswer.model_validate(self.provider.judge({**payload, "request_sha256": digest}))
            if answer.request_sha256 != digest:
                raise ValueError("judgment_reply_binding_mismatch")
        except TimeoutError:
            result.update(status="timeout", reason="judgment_provider_timeout")
        except (OSError, ValueError) as error:
            result.update(status="error", reason="judgment_provider_or_contract_error", error_type=type(error).__name__)
        else:
            result.update(status="completed", verdict="uncertain" if answer.answer is None
                          else "success" if answer.answer else "failure", probability=answer.probability,
                          usage=answer.usage.counts() if answer.usage is not None else None)
        result["elapsed_ms"] = (perf_counter_ns() - started) / 1_000_000
        return result
