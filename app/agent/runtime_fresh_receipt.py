"""首次学习动作的事实性 receipt，不含审核工作流。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from datetime import datetime
from typing import Any, Mapping

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
FRESH_RECEIPT_VERSIONS = frozenset({'runtime_fresh_result_receipt_v1', 'runtime_fresh_result_receipt_v2'})


class RuntimeFreshReceiptError(ValueError):
    pass


def _id(value: object, label: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise RuntimeFreshReceiptError(f"fresh receipt {label} is invalid")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise RuntimeFreshReceiptError(f"fresh receipt {label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeFreshReceiptAction:
    action_id: str
    semantic_action: str
    def model_dump(self, *, mode: str = "python") -> dict[str, str]:
        if mode not in {"python", "json"}: raise ValueError("invalid mode")
        return {"action_id": self.action_id, "semantic_action": self.semantic_action}


@dataclass(frozen=True, slots=True)
class RuntimeFreshReceiptEvidence:
    source_sha256: str; approved_preview_sha256: str; fresh_preview_sha256: str
    consume_content_sha256: str; confirmation_id: str; capture_id: str
    candidate_ref: str; gate_decision_ref: str
    _text_parameters_json: bytes | None = field(default=None, repr=False)
    _text_verification_json: bytes | None = field(default=None, repr=False)
    _scroll_verification_json: bytes | None = field(default=None, repr=False)

    @property
    def scroll_verification(self) -> dict[str, Any] | None:
        return None if self._scroll_verification_json is None else json.loads(self._scroll_verification_json.decode("utf-8"))

    @property
    def text_parameters_ref(self) -> dict[str, Any] | None:
        return None if self._text_parameters_json is None else json.loads(self._text_parameters_json.decode("utf-8"))

    @property
    def text_field_verification(self) -> dict[str, Any] | None:
        return None if self._text_verification_json is None else json.loads(self._text_verification_json.decode("utf-8"))

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        if mode not in {"python", "json"}: raise ValueError("invalid mode")
        result = {key: getattr(self, key) for key in (
            "source_sha256", "approved_preview_sha256", "fresh_preview_sha256",
            "consume_content_sha256", "confirmation_id", "capture_id",
            "candidate_ref", "gate_decision_ref",
        )}
        if self._text_parameters_json is not None:
            result["text_parameters_ref"] = self.text_parameters_ref
            result["text_field_verification"] = self.text_field_verification
        if self._scroll_verification_json is not None:
            result["scroll_verification"] = self.scroll_verification
        return result


@dataclass(frozen=True, slots=True)
class RuntimeFreshResultReceipt:
    receipt_id: str; issued_at: str; session_id: str; observation_id: str; intent_id: str
    source_sha256: str; action: RuntimeFreshReceiptAction; outcome: str; reason_code: str
    attempt_count: int; gate_status: str; dispatch_status: str; effect_status: str
    destination_status: str; evidence: RuntimeFreshReceiptEvidence; next_observation_id: str | None
    artifact_is_authorization: bool = False
    workflow: None = None

    @classmethod
    def from_dict(cls, value: object) -> "RuntimeFreshResultReceipt":
        keys = {"contract_version", "receipt_id", "issued_at", "session_id", "observation_id", "intent_id",
                "source_sha256", "action", "outcome", "reason_code", "attempt_count", "gate_status",
                "dispatch_status", "effect_status", "destination_status", "evidence", "next_observation_id",
                "artifact_is_authorization"}
        if not isinstance(value, Mapping) or set(value) != keys or value.get("contract_version") not in FRESH_RECEIPT_VERSIONS:
            raise RuntimeFreshReceiptError("fresh receipt contract is invalid")
        action, evidence = value.get("action"), value.get("evidence")
        if not isinstance(action, Mapping) or set(action) != {"action_id", "semantic_action"} or not isinstance(evidence, Mapping):
            raise RuntimeFreshReceiptError("fresh receipt action or evidence is invalid")
        evidence_keys = {"source_sha256", "approved_preview_sha256", "fresh_preview_sha256", "consume_content_sha256",
                         "confirmation_id", "capture_id", "candidate_ref", "gate_decision_ref"}
        if isinstance(action, Mapping) and action.get("semantic_action") == "fill_field":
            evidence_keys |= {"text_parameters_ref", "text_field_verification"}
        if action.get("semantic_action") == "scroll_region":
            evidence_keys.add("scroll_verification")
        if set(evidence) != evidence_keys:
            raise RuntimeFreshReceiptError("fresh receipt evidence is invalid")
        outcome = value.get("outcome")
        matrices = {
            "ACTION_RECORDED": ("backend_dispatched", "dispatched"),
            "OBSERVATION_FAILED": ("after_observation_unavailable", "dispatched"),
            "EXECUTION_FAILED": ("backend_not_started", "not_started"),
            "EXECUTION_UNKNOWN": ("backend_result_lost", "indeterminate"),
        }
        if outcome not in matrices or value.get("reason_code") != matrices[outcome][0] or value.get("dispatch_status") != matrices[outcome][1]:
            raise RuntimeFreshReceiptError("fresh receipt factual outcome is invalid")
        semantic_action = action.get("semantic_action")
        expected_gate = 'manual_confirmed' if value['contract_version'] == 'runtime_fresh_result_receipt_v2' else 'allowed'
        if (type(value.get("attempt_count")) is not int or value.get("attempt_count") != 1 or value.get("gate_status") != expected_gate
                or (value.get("effect_status") not in {"verified", "not_verified"} if semantic_action == "fill_field" else value.get("effect_status") != "not_verified")
                or value.get("destination_status") != "not_evaluated"
                or value.get("artifact_is_authorization") is not False):
            raise RuntimeFreshReceiptError("fresh receipt factual status is invalid")
        ids = {k: _id(value.get(k), k) for k in ("receipt_id", "session_id", "observation_id", "intent_id")}
        if not isinstance(value.get("issued_at"), str) or not value["issued_at"].endswith("Z"):
            raise RuntimeFreshReceiptError("fresh receipt issued time is invalid")
        try:
            datetime.fromisoformat(value["issued_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise RuntimeFreshReceiptError("fresh receipt issued time is invalid") from exc
        if value.get("next_observation_id") is not None: _id(value["next_observation_id"], "next observation")
        source = _sha(value.get("source_sha256"), "source")
        if evidence.get("source_sha256") != source:
            raise RuntimeFreshReceiptError("fresh receipt source evidence mismatch")
        for key in ("approved_preview_sha256", "fresh_preview_sha256", "consume_content_sha256"):
            _sha(evidence.get(key), key)
        _id(action.get("action_id"), "action")
        if semantic_action not in {"open_detail", "back", "close_modal", "fill_field", "scroll_region"}:
            raise RuntimeFreshReceiptError("fresh receipt semantic action is invalid")
        _id(evidence.get("capture_id"), "capture")
        for key in ("confirmation_id", "candidate_ref", "gate_decision_ref"):
            if not isinstance(evidence.get(key), str) or not evidence[key]: raise RuntimeFreshReceiptError("fresh receipt evidence ref is invalid")
        text_parameters_json = None
        text_verification_json = None
        scroll_verification_json = None
        if semantic_action == "scroll_region":
            from app.agent.fresh_scroll_region import validate_fresh_scroll_proof
            try:
                proof = validate_fresh_scroll_proof(evidence["scroll_verification"])
                if not isinstance(proof["before"], dict) or proof["before"].get("capture_id") != evidence["capture_id"]:
                    raise ValueError("scroll before capture differs from dispatch")
                if outcome != "ACTION_RECORDED" and proof["after"] is not None:
                    raise ValueError("unrecorded scroll cannot claim an after capture")
                scroll_verification_json = json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, KeyError) as exc:
                raise RuntimeFreshReceiptError("fresh scroll receipt proof is invalid") from exc
        if semantic_action == "fill_field":
            try:
                from app.agent.text_field_evidence import validate_text_field_verification_reference
                from app.agent.text_parameters import validate_text_parameter_reference

                declaration = validate_text_parameter_reference(evidence["text_parameters_ref"])
                verification = validate_text_field_verification_reference(
                    evidence["text_field_verification"], declaration
                )
                expected = verification["expected"]["before"]
                if expected.get("capture_id") != evidence["capture_id"]:
                    raise ValueError("text verification capture differs")
                actual = verification.get("actual")
                effect_status = value.get("effect_status")
                if effect_status != verification.get("status"):
                    raise ValueError("text verification effect differs")
                if verification.get("status") == "verified" and (
                    outcome != "ACTION_RECORDED"
                    or value.get("dispatch_status") != "dispatched"
                    or not isinstance(value.get("next_observation_id"), str)
                    or not value["next_observation_id"]
                ):
                    raise ValueError("verified text effect requires recorded action")
                if outcome != "ACTION_RECORDED" and actual is not None:
                    raise ValueError("unrecorded text effect cannot carry actual evidence")
                text_parameters_json = json.dumps(
                    declaration, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
                text_verification_json = json.dumps(
                    verification, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, KeyError, OverflowError, json.JSONDecodeError) as exc:
                raise RuntimeFreshReceiptError("fresh receipt text evidence is invalid") from exc
        return cls(**ids, issued_at=value["issued_at"], source_sha256=source,
                   action=RuntimeFreshReceiptAction(**dict(action)), outcome=outcome, reason_code=value["reason_code"],
                   attempt_count=1, gate_status=expected_gate, dispatch_status=value["dispatch_status"],
                   effect_status=value["effect_status"], destination_status="not_evaluated",
                   evidence=RuntimeFreshReceiptEvidence(
                       **{key: evidence[key] for key in (
                           "source_sha256", "approved_preview_sha256", "fresh_preview_sha256",
                           "consume_content_sha256", "confirmation_id", "capture_id",
                           "candidate_ref", "gate_decision_ref",
                       )},
                       _text_parameters_json=text_parameters_json,
                       _text_verification_json=text_verification_json,
                       _scroll_verification_json=scroll_verification_json,
                   ), next_observation_id=value["next_observation_id"])

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        if mode not in {"python", "json"}: raise ValueError("invalid mode")
        return {"contract_version": ('runtime_fresh_result_receipt_v2' if self.gate_status == 'manual_confirmed'
                                      else 'runtime_fresh_result_receipt_v1'), "receipt_id": self.receipt_id,
                "issued_at": self.issued_at, "session_id": self.session_id, "observation_id": self.observation_id,
                "intent_id": self.intent_id, "source_sha256": self.source_sha256, "action": self.action.model_dump(mode="json"),
                "outcome": self.outcome, "reason_code": self.reason_code, "attempt_count": self.attempt_count,
                "gate_status": self.gate_status, "dispatch_status": self.dispatch_status, "effect_status": self.effect_status,
                "destination_status": self.destination_status, "evidence": self.evidence.model_dump(mode="json"),
                "next_observation_id": self.next_observation_id, "artifact_is_authorization": False}
