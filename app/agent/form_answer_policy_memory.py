from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RECORD_CONTRACT = "form_answer_policy_memory_record_v1"
REGISTRY_CONTRACT = "form_answer_policy_memory_registry_v1"
AGENT_CONTEXT_CONTRACT = "form_answer_policy_agent_context_v1"
MEMORY_ROOT = Path("artifacts") / "agent-memory" / "form-answer-policies"
SUPPORTED_SCOPES = ("one_time", "workflow_class", "site", "global_profile")
_SCOPE_RANK = {scope: len(SUPPORTED_SCOPES) - index for index, scope in enumerate(SUPPORTED_SCOPES)}
_OPAQUE_REFERENCE_PATTERN = re.compile(r"^(?:evidence|profile|reviewed|derived|vault):[A-Za-z0-9_.:/-]{3,155}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_LOCK = threading.RLock()


class FormAnswerPolicyMemoryStore:
    """保存人工审核后的答案策略引用，不保存答案正文或历史坐标。"""

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.memory_root = self.project_root / MEMORY_ROOT
        self.records_root = self.memory_root / "records"
        self.registry_path = self.memory_root / "registry.json"

    def record_review(
        self,
        *,
        question_understanding: dict[str, Any],
        review_decision: str,
        scope_type: str,
        scope_key: str,
        answer_reference: str,
        evidence_hash: str,
        reviewed_at: datetime,
        expires_at: datetime,
    ) -> dict[str, Any]:
        intent, polarity = _validated_semantics(question_understanding)
        decision = str(review_decision or "").strip().casefold()
        if decision not in {"approved", "rejected"}:
            raise ValueError("review_decision must be approved or rejected")
        scope = _validated_scope(scope_type, scope_key)
        reference = str(answer_reference or "").strip()
        if not _OPAQUE_REFERENCE_PATTERN.fullmatch(reference) or "@" in reference:
            raise ValueError("answer_reference must be an opaque evidence reference")
        normalized_hash = str(evidence_hash or "").strip().casefold()
        if not _SHA256_PATTERN.fullmatch(normalized_hash):
            raise ValueError("evidence_hash must be a lowercase sha256 digest")
        reviewed = _as_utc(reviewed_at, field_name="reviewed_at")
        expires = _as_utc(expires_at, field_name="expires_at")
        if expires <= reviewed:
            raise ValueError("expires_at must be later than reviewed_at")

        payload = {
            "contract_version": RECORD_CONTRACT,
            "intent": intent,
            "polarity": polarity,
            "scope": scope,
            "review_decision": decision,
            "answer_reference": reference,
            "evidence_hash": normalized_hash,
            "reviewed_at": reviewed.isoformat(),
            "expires_at": expires.isoformat(),
            "pii_redacted": True,
            "artifact_is_authorization": False,
        }
        record_bytes = _canonical_json_bytes(payload)
        record_id = hashlib.sha256(record_bytes).hexdigest()
        record_path = self.records_root / f"{record_id}.json"
        registry_record = {
            "record_id": record_id,
            "record_path": _relative_path(record_path, root=self.project_root),
            "intent": intent,
            "polarity": polarity,
            "scope": scope,
            "review_decision": decision,
            "reviewed_at": reviewed.isoformat(),
            "expires_at": expires.isoformat(),
            "artifact_is_authorization": False,
        }

        with _LOCK:
            if not record_path.exists():
                _atomic_write(record_path, record_bytes)
            elif hashlib.sha256(record_path.read_bytes()).hexdigest() != record_id:
                raise ValueError("form answer policy record checksum mismatch")
            registry = self._load_registry()
            records = registry.setdefault("records", {})
            records[record_id] = registry_record
            registry["registry_revision"] = int(registry.get("registry_revision") or 0) + 1
            _atomic_write(self.registry_path, _canonical_json_bytes(registry))

        return {
            "contract_version": "form_answer_policy_memory_record_result_v1",
            "status": "recorded",
            "record_id": record_id,
            "record_path": _relative_path(record_path, root=self.project_root),
            "registry_revision": registry["registry_revision"],
            "artifact_is_authorization": False,
        }

    def resolve(
        self,
        *,
        question_understanding: dict[str, Any],
        scope_context: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        intent = str(question_understanding.get("intent") or "").strip().casefold()
        polarity = str(question_understanding.get("polarity") or "").strip().casefold()
        confidence = float(question_understanding.get("confidence") or 0.0)
        if not intent or intent.startswith("unknown") or not polarity or polarity == "unknown" or confidence <= 0.0:
            return _resolution(
                status="needs_user_review",
                reason="unknown_or_ambiguous_question_intent",
                intent=intent or None,
                polarity=polarity or None,
            )

        context = {
            str(key).strip().casefold(): str(value).strip()
            for key, value in (scope_context or {}).items()
            if str(key).strip() and str(value).strip()
        }
        intent_records = [record for record in self._load_records() if record.get("intent") == intent]
        scoped_records = [record for record in intent_records if _scope_matches(record.get("scope"), context)]
        if not scoped_records:
            return _resolution(
                status="needs_user_review",
                reason="no_matching_reviewed_scope",
                intent=intent,
                polarity=polarity,
            )

        same_polarity = [record for record in scoped_records if record.get("polarity") == polarity]
        if not same_polarity:
            return _resolution(
                status="requires_re_evaluation",
                reason="semantic_polarity_changed",
                intent=intent,
                polarity=polarity,
            )

        current_time = _as_utc(now or datetime.now(timezone.utc), field_name="now")
        active = [record for record in same_polarity if _parse_datetime(record.get("expires_at")) > current_time]
        if not active:
            return _resolution(
                status="needs_user_review",
                reason="reviewed_evidence_expired",
                intent=intent,
                polarity=polarity,
            )

        selected = max(
            active,
            key=lambda record: (
                _SCOPE_RANK.get(str((record.get("scope") or {}).get("type") or ""), 0),
                _parse_datetime(record.get("reviewed_at")),
            ),
        )
        scope = deepcopy(selected.get("scope"))
        if selected.get("review_decision") == "rejected":
            return _resolution(
                status="blocked_by_human_review",
                reason="matching_strategy_was_rejected",
                intent=intent,
                polarity=polarity,
                scope=scope,
            )
        return _resolution(
            status="reviewed_strategy_available",
            reason="matching_reviewed_strategy_found",
            intent=intent,
            polarity=polarity,
            scope=scope,
            answer_reference=str(selected.get("answer_reference") or "") or None,
            evidence_hash=str(selected.get("evidence_hash") or "") or None,
        )

    def agent_context(
        self,
        *,
        question_understanding: dict[str, Any],
        scope_context: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return {
            "contract_version": AGENT_CONTEXT_CONTRACT,
            "resolution": self.resolve(
                question_understanding=question_understanding,
                scope_context=scope_context,
                now=now,
            ),
            "execution_contract": {
                "current_inventory_required": True,
                "current_target_resolution_required": True,
                "policy_gate_required": True,
                "action_gate_required": True,
                "artifact_is_authorization": False,
            },
        }

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {
                "contract_version": REGISTRY_CONTRACT,
                "registry_revision": 0,
                "records": {},
            }
        payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("contract_version") != REGISTRY_CONTRACT:
            raise ValueError("form answer policy registry has an invalid contract")
        return payload

    def _load_records(self) -> list[dict[str, Any]]:
        registry = self._load_registry()
        records: list[dict[str, Any]] = []
        for record_id, index_record in (registry.get("records") or {}).items():
            if not isinstance(index_record, dict):
                raise ValueError("form answer policy registry record is invalid")
            path = _resolve_file(
                str(index_record.get("record_path") or ""),
                root=self.project_root,
            )
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record_id:
                raise ValueError("form answer policy record checksum mismatch")
            record = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(record, dict) or record.get("contract_version") != RECORD_CONTRACT:
                raise ValueError("form answer policy record has an invalid contract")
            records.append(record)
        return records


def _validated_semantics(question_understanding: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(question_understanding, dict):
        raise ValueError("question_understanding must be a normalized object")
    intent = str(question_understanding.get("intent") or "").strip().casefold()
    polarity = str(question_understanding.get("polarity") or "").strip().casefold()
    if not intent or intent.startswith("unknown") or not polarity or polarity == "unknown":
        raise ValueError("reviewed answer policy requires known intent and polarity")
    return intent, polarity


def _validated_scope(scope_type: str, scope_key: str) -> dict[str, str]:
    normalized_type = str(scope_type or "").strip().casefold()
    normalized_key = str(scope_key or "").strip()
    if normalized_type not in SUPPORTED_SCOPES:
        raise ValueError(f"unsupported answer policy scope: {normalized_type}")
    if not normalized_key:
        raise ValueError("answer policy scope key is required")
    return {"type": normalized_type, "key": normalized_key}


def _scope_matches(scope: Any, context: dict[str, str]) -> bool:
    if not isinstance(scope, dict):
        return False
    scope_type = str(scope.get("type") or "")
    scope_key = str(scope.get("key") or "")
    if scope_type == "global_profile":
        return True
    return context.get(scope_type) == scope_key


def _resolution(
    *,
    status: str,
    reason: str,
    intent: str | None,
    polarity: str | None,
    scope: dict[str, Any] | None = None,
    answer_reference: str | None = None,
    evidence_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": "form_answer_policy_resolution_v1",
        "status": status,
        "reason": reason,
        "intent": intent,
        "polarity": polarity,
        "scope": deepcopy(scope),
        "answer_reference": answer_reference,
        "evidence_hash": evidence_hash,
        "requires_user_review": status != "reviewed_strategy_available",
        "fill_authorized": False,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def _as_utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("form answer policy timestamp is invalid") from exc
    return _as_utc(parsed, field_name="stored timestamp")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _relative_path(path: Path, *, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("form answer policy path escapes project root") from exc


def _resolve_file(value: str, *, root: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("form answer policy path escapes project root") from exc
    if not resolved.is_file():
        raise ValueError(f"form answer policy file not found: {value}")
    return resolved
