"""首次学习动作意图的无资产不可变契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from typing import Any, Mapping


INTENT_CONTRACT_VERSION = "fresh_learning_action_intent_v1"
OBSERVATION_CONTRACT_VERSION = "fresh_learning_runtime_observation_v1"
CLAIM_CONTRACT_VERSION = "runtime_fresh_learning_intent_claim_v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")


class FreshLearningActionContractError(ValueError):
    """首次学习动作契约不完整或越过无授权边界。"""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(dict(value), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise FreshLearningActionContractError("fresh learning contract is not canonical JSON") from exc


def payload_sha256(value: Mapping[str, Any]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise FreshLearningActionContractError(f"fresh learning {label} is invalid")
    return value


def _source_sha(value: object) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise FreshLearningActionContractError("fresh learning source digest is invalid")
    return value


def validate_source_reference(value: object) -> dict[str, Any]:
    from app.agent.fresh_learning_runtime_source import _validated_reference

    try:
        return _validated_reference(value)
    except ValueError as exc:
        raise FreshLearningActionContractError("fresh learning source reference is invalid") from exc


@dataclass(frozen=True, slots=True)
class FreshLearningIntent:
    intent_id: str
    session_id: str
    observation_id: str
    source_sha256: str
    action_id: str
    semantic_action: str
    goal: str
    _text_parameters_json: bytes | None = field(default=None, repr=False)
    _learned_control_json: bytes | None = field(default=None, repr=False)
    _scroll_parameters_json: bytes | None = field(default=None, repr=False)

    def __post_init__(self):
        from app.agent.text_parameters import validate_text_parameter_reference

        if self._learned_control_json is not None:
            from app.agent.learned_control_reference import validate_learned_control_binding
            validate_learned_control_binding(json.loads(self._learned_control_json.decode('utf-8')))

        if self.semantic_action == "fill_field":
            if type(self._text_parameters_json) is not bytes:
                raise FreshLearningActionContractError("fresh fill intent requires text declaration reference")
            validate_text_parameter_reference(json.loads(self._text_parameters_json.decode("utf-8")))
        elif self._text_parameters_json is not None:
            raise FreshLearningActionContractError("non-text intent cannot carry text declaration")

        if self.semantic_action == "scroll_region":
            if type(self._scroll_parameters_json) is not bytes:
                raise FreshLearningActionContractError("fresh scroll intent requires reviewed scroll parameters")
            try:
                from app.agent.scroll_parameters import ReviewedScrollParameters

                ReviewedScrollParameters.from_payload(
                    json.loads(self._scroll_parameters_json.decode("utf-8"))
                )
            except (TypeError, ValueError, UnicodeDecodeError) as exc:
                raise FreshLearningActionContractError("fresh scroll parameters are invalid") from exc
        elif self._scroll_parameters_json is not None:
            raise FreshLearningActionContractError("non-scroll intent cannot carry scroll parameters")

    @property
    def text_parameters_ref(self):
        return json.loads(self._text_parameters_json.decode("utf-8")) if self._text_parameters_json is not None else None

    @property
    def learned_control(self):
        return json.loads(self._learned_control_json.decode('utf-8')) if self._learned_control_json is not None else None

    @property
    def scroll_parameters(self):
        return json.loads(self._scroll_parameters_json.decode("utf-8")) if self._scroll_parameters_json is not None else None

    @classmethod
    def from_dict(cls, value: object) -> "FreshLearningIntent":
        required = {"contract_version", "intent_id", "session_id", "observation_id",
                    "source_sha256", "action_id", "semantic_action", "goal"}
        if isinstance(value, Mapping) and value.get("semantic_action") == "fill_field":
            required.add("text_parameters_ref")
        if isinstance(value, Mapping) and 'learned_control' in value:
            required.add('learned_control')
        if isinstance(value, Mapping) and value.get("semantic_action") == "scroll_region":
            required.add("scroll_parameters")
        if not isinstance(value, Mapping) or set(value) != required:
            raise FreshLearningActionContractError("fresh learning intent must have exact fields")
        if value.get("contract_version") != INTENT_CONTRACT_VERSION:
            raise FreshLearningActionContractError("fresh learning intent contract is invalid")
        semantic_action = value.get("semantic_action")
        if semantic_action not in {"open_detail", "back", "close_modal", "fill_field", "scroll_region"}:
            raise FreshLearningActionContractError("fresh learning semantic action is invalid")
        text_ref = None
        if semantic_action == "fill_field":
            from app.agent.text_parameters import validate_text_parameter_reference

            text_ref = canonical_json_bytes(validate_text_parameter_reference(value["text_parameters_ref"]))
        scroll_ref = None
        if semantic_action == "scroll_region":
            try:
                from app.agent.scroll_parameters import ReviewedScrollParameters

                scroll_ref = canonical_json_bytes(
                    ReviewedScrollParameters.from_payload(value["scroll_parameters"]).to_payload()
                )
            except (TypeError, ValueError) as exc:
                raise FreshLearningActionContractError("fresh scroll parameters are invalid") from exc
        goal = value.get("goal")
        if (not isinstance(goal, str) or not goal.strip() or goal != goal.strip()
                or len(goal) > 512 or "\x00" in goal):
            raise FreshLearningActionContractError("fresh learning goal is invalid")
        return cls(_id(value.get("intent_id"), "intent ID"),
                   _id(value.get("session_id"), "session ID"),
                   _id(value.get("observation_id"), "observation ID"),
                   _source_sha(value.get("source_sha256")),
                   _id(value.get("action_id"), "action ID"), semantic_action, goal, text_ref,
                   canonical_json_bytes(value['learned_control']) if 'learned_control' in value else None,
                   scroll_ref)

    def to_dict(self) -> dict[str, Any]:
        result = {"contract_version": INTENT_CONTRACT_VERSION, "intent_id": self.intent_id,
                "session_id": self.session_id, "observation_id": self.observation_id,
                "source_sha256": self.source_sha256, "action_id": self.action_id,
                "semantic_action": self.semantic_action, "goal": self.goal}
        if self._text_parameters_json is not None:
            result["text_parameters_ref"] = self.text_parameters_ref
        if self._learned_control_json is not None:
            result['learned_control'] = self.learned_control
        if self._scroll_parameters_json is not None:
            result["scroll_parameters"] = self.scroll_parameters
        return result

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        if mode not in {"python", "json"}:
            raise ValueError("fresh learning intent model_dump mode is invalid")
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class FreshLearningClaimObservation:
    _payload_json: bytes = field(repr=False)

    @classmethod
    def from_dict(cls, value: object) -> "FreshLearningClaimObservation":
        required = {"contract_version", "session_id", "observation_id", "source",
                    "capture_source", "capture", "application", "state",
                    "available_actions", "execution_ready", "artifact_is_authorization",
                    "execute_binding_enabled", "action_executed"}
        if not isinstance(value, Mapping) or set(value) != required:
            raise FreshLearningActionContractError("fresh learning observation must have exact fields")
        if value.get("contract_version") != OBSERVATION_CONTRACT_VERSION:
            raise FreshLearningActionContractError("fresh learning observation contract is invalid")
        _id(value.get("session_id"), "session ID")
        _id(value.get("observation_id"), "observation ID")
        source = validate_source_reference(value.get("source"))
        capture_source = value.get("capture_source")
        capture = value.get("capture")
        application = value.get("application")
        if not isinstance(capture_source, Mapping) or not isinstance(capture, Mapping) or not isinstance(application, Mapping):
            raise FreshLearningActionContractError("fresh learning capture evidence is invalid")
        try:
            from app.agent.fresh_learning_archive import _reference
            _reference(capture_source)
            from app.agent.fresh_learning_runtime_source import _application_identity_from_evidence
            if _application_identity_from_evidence({"application": application}) != source["application_identity"]:
                raise FreshLearningActionContractError("fresh learning application does not match source")
        except FreshLearningActionContractError:
            raise
        except (TypeError, ValueError) as exc:
            raise FreshLearningActionContractError("fresh learning capture evidence is invalid") from exc
        if (capture_source.get("capture_id") != capture.get("capture_id")
                or capture_source.get("screenshot_sha256") != capture.get("screenshot_sha256")):
            raise FreshLearningActionContractError("fresh learning capture source does not match capture")
        if (value.get("state") != "unreviewed" or value.get("available_actions") != []
                or any(value.get(key) is not False for key in (
                    "execution_ready", "artifact_is_authorization",
                    "execute_binding_enabled", "action_executed"))):
            raise FreshLearningActionContractError("fresh learning observation crosses authorization boundary")
        checked = dict(value)
        checked["source"] = source
        raw = canonical_json_bytes(checked)
        return cls(raw)

    @property
    def session_id(self) -> str:
        return self.to_dict()["session_id"]

    @property
    def observation_id(self) -> str:
        return self.to_dict()["observation_id"]

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._payload_json.decode("utf-8"))
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class FreshLearningServerBinding:
    source_sha256: str
    application_identity: dict[str, str] = field(repr=False)
    target_window_handle: int
    target_process_id: int

    @classmethod
    def from_source(cls, source_reference: Mapping[str, Any]) -> "FreshLearningServerBinding":
        source = validate_source_reference(source_reference)
        return cls(source["source_sha256"], dict(source["application_identity"]),
                   source["target_window_handle"], source["target_process_id"])

    def to_dict(self) -> dict[str, Any]:
        return {"source_sha256": self.source_sha256,
                "application_identity": dict(self.application_identity),
                "target_window_handle": self.target_window_handle,
                "target_process_id": self.target_process_id}


@dataclass(frozen=True, slots=True)
class RuntimeFreshLearningClaimSnapshot:
    claim_id: str
    claim_content_sha256: str
    phase: str
    observation: FreshLearningClaimObservation
    intent: FreshLearningIntent
    server_binding: FreshLearningServerBinding
    grounded_confirmation: object | None = None
    grounded_consume: object | None = None
    terminal_receipt_id: str | None = None
    recovery_required: bool = True
    grants_action_authority: bool = False
    artifact_is_authorization: bool = False


__all__ = ["CLAIM_CONTRACT_VERSION", "FreshLearningActionContractError",
           "FreshLearningClaimObservation", "FreshLearningIntent",
           "FreshLearningServerBinding", "RuntimeFreshLearningClaimSnapshot",
           "canonical_json_bytes", "payload_sha256",
           "validate_source_reference"]
