from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


REGISTRY_CONTRACT = "learning_surface_rule_registry_v1"
RULE_ROOT = Path("artifacts") / "learning-correction-memory"
_ALLOWED_TRANSITIONS = {
    "candidate": {"regression_verified"},
    "regression_verified": {"human_approved"},
    "human_approved": {"active"},
    "active": {"rolled_back"},
    "rolled_back": set(),
}


def load_surface_rule_registry(*, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = root / RULE_ROOT / "registry.json"
    if not path.exists():
        return _empty_registry()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("contract_version") != REGISTRY_CONTRACT:
        raise ValueError("surface rule registry has an unsupported contract")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not all(isinstance(item, dict) for item in rules):
        raise ValueError("surface rule registry rules must be a list of objects")
    return payload


def build_surface_rule_registry_panel_view(*, project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    registry = load_surface_rule_registry(project_root=root)
    statuses = ["candidate", "regression_verified", "human_approved", "active", "rolled_back"]
    status_counts = {status: 0 for status in statuses}
    rules: list[dict[str, Any]] = []
    for rule in registry["rules"]:
        status = str(rule.get("status") or "candidate")
        if status in status_counts:
            status_counts[status] += 1
        evidence = _surface_rule_panel_evidence(root, rule)
        surface = rule.get("surface") if isinstance(rule.get("surface"), dict) else {}
        history = rule.get("transition_history") if isinstance(rule.get("transition_history"), list) else []
        rules.append(
            {
                "rule_id": str(rule.get("rule_id") or ""),
                "status": status,
                "production_eligible": rule.get("production_eligible") is True,
                "surface": {
                    "adapter_id": str(surface.get("adapter_id") or "generic"),
                    "decision_status": str(surface.get("decision_status") or "surface_evidence_not_available"),
                },
                "edit_types": evidence["edit_types"],
                "correction_count": evidence["correction_count"],
                "evidence_status": evidence["evidence_status"],
                "created_at": rule.get("created_at"),
                "updated_at": rule.get("updated_at"),
                "transition_count": len([item for item in history if isinstance(item, dict)]),
                "requires_regression_verification": rule.get("requires_regression_verification") is True,
                "requires_human_approval": rule.get("requires_human_approval") is True,
                "model_activation_allowed": rule.get("model_activation_allowed") is True,
                "artifact_is_authorization": rule.get("artifact_is_authorization") is True,
                "execute_binding_enabled": rule.get("execute_binding_enabled") is True,
            }
        )
    rules.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {
        "contract_version": "panel_surface_rule_registry_v1",
        "updated_at": registry.get("updated_at"),
        "status_counts": status_counts,
        "rules": rules,
        "production_rule_policy": "active_only",
        "candidate_rules_affect_production": False,
        "model_activation_allowed": False,
        "no_click_authorization": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _surface_rule_panel_evidence(root: Path, rule: dict[str, Any]) -> dict[str, Any]:
    try:
        entry_path = _resolve_under_root(root, str(rule.get("correction_entry_path") or ""))
    except ValueError:
        return {"edit_types": [], "correction_count": 0, "evidence_status": "invalid_path"}
    if not entry_path.is_file():
        return {"edit_types": [], "correction_count": 0, "evidence_status": "missing"}
    raw = entry_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != str(rule.get("correction_sha256") or ""):
        return {"edit_types": [], "correction_count": 0, "evidence_status": "checksum_mismatch"}
    try:
        entry = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"edit_types": [], "correction_count": 0, "evidence_status": "invalid_json"}
    if not isinstance(entry, dict):
        return {"edit_types": [], "correction_count": 0, "evidence_status": "invalid_json"}
    corrections = [item for item in entry.get("corrections", []) if isinstance(item, dict)]
    return {
        "edit_types": sorted(
            {
                str(item.get("edit_type") or "").strip()
                for item in corrections
                if str(item.get("edit_type") or "").strip()
            }
        ),
        "correction_count": len(corrections),
        "evidence_status": "valid",
    }


def register_surface_rule_candidate(
    *,
    rule_id: str,
    correction_entry_path: str,
    correction_sha256: str,
    surface: dict[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    registry = load_surface_rule_registry(project_root=root)
    existing = next((item for item in registry["rules"] if item.get("rule_id") == rule_id), None)
    if existing:
        if (
            existing.get("correction_entry_path") != correction_entry_path
            or existing.get("correction_sha256") != correction_sha256
        ):
            raise ValueError("surface rule id already exists with different evidence")
        return deepcopy(existing)

    now = datetime.now().isoformat()
    record = {
        "rule_id": rule_id,
        "status": "candidate",
        "production_eligible": False,
        "correction_entry_path": correction_entry_path,
        "correction_sha256": correction_sha256,
        "surface": deepcopy(surface),
        "created_at": now,
        "updated_at": now,
        "transition_history": [
            {
                "from_status": None,
                "to_status": "candidate",
                "actor_type": "system",
                "actor_id": "human_review_correction_recorder",
                "evidence": {"source_type": "human_review_patch"},
                "changed_at": now,
            }
        ],
        "requires_regression_verification": True,
        "requires_human_approval": True,
        "model_activation_allowed": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    registry["rules"].append(record)
    registry["updated_at"] = now
    _write_registry(root, registry)
    return deepcopy(record)


def transition_surface_rule(
    rule_id: str,
    *,
    to_status: str,
    actor_type: str,
    actor_id: str,
    evidence: dict[str, Any],
    project_root: str | Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    registry = load_surface_rule_registry(project_root=root)
    rule = next((item for item in registry["rules"] if item.get("rule_id") == rule_id), None)
    if rule is None:
        raise ValueError(f"unknown surface rule: {rule_id}")
    current = str(rule.get("status") or "")
    target = str(to_status or "").strip()
    if target not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid surface rule transition: {current} -> {target}")
    normalized_actor_type = str(actor_type or "").strip().lower()
    normalized_actor_id = str(actor_id or "").strip()
    if not normalized_actor_id:
        raise ValueError("surface rule transition requires actor_id")
    transition_evidence = deepcopy(evidence) if isinstance(evidence, dict) else {}
    _validate_transition(
        target,
        actor_type=normalized_actor_type,
        evidence=transition_evidence,
    )

    now = datetime.now().isoformat()
    rule["status"] = target
    rule["production_eligible"] = target == "active"
    rule["updated_at"] = now
    rule.setdefault("transition_history", []).append(
        {
            "from_status": current,
            "to_status": target,
            "actor_type": normalized_actor_type,
            "actor_id": normalized_actor_id,
            "evidence": transition_evidence,
            "changed_at": now,
        }
    )
    registry["updated_at"] = now
    _write_registry(root, registry)
    return deepcopy(rule)


def load_active_surface_rules(*, project_root: str | Path) -> list[dict[str, Any]]:
    root = Path(project_root).resolve()
    registry = load_surface_rule_registry(project_root=root)
    active: list[dict[str, Any]] = []
    for rule in registry["rules"]:
        if rule.get("status") != "active" or rule.get("production_eligible") is not True:
            continue
        entry_path = _resolve_under_root(root, str(rule.get("correction_entry_path") or ""))
        if not entry_path.is_file():
            raise ValueError(f"active surface rule evidence is missing: {rule.get('rule_id')}")
        raw = entry_path.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != str(rule.get("correction_sha256") or ""):
            raise ValueError(f"active surface rule evidence checksum mismatch: {rule.get('rule_id')}")
        entry = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(entry, dict):
            raise ValueError(f"active surface rule evidence is invalid: {rule.get('rule_id')}")
        active.append({**deepcopy(rule), "correction_entry": entry})
    return active


def _validate_transition(target: str, *, actor_type: str, evidence: dict[str, Any]) -> None:
    if target == "regression_verified":
        manifests = evidence.get("manifest_paths")
        if (
            evidence.get("regression_status") != "passed"
            or int(evidence.get("failed") or 0) != 0
            or not isinstance(manifests, list)
            or not manifests
        ):
            raise ValueError("regression verification requires a passing manifest result")
    elif target == "human_approved":
        if actor_type != "human":
            raise ValueError("human approval requires a human actor")
        if evidence.get("decision") != "approve":
            raise ValueError("human approval requires decision=approve")
        if not str(evidence.get("scope") or "").strip():
            raise ValueError("human approval requires an explicit scope")
    elif target == "active":
        if actor_type != "human":
            raise ValueError("surface rule activation requires a human actor")
        if not str(evidence.get("activation_reason") or "").strip():
            raise ValueError("surface rule activation requires activation_reason")
        counterexample_status = str(evidence.get("counterexample_status") or "").strip()
        if counterexample_status not in {"covered", "not_applicable"}:
            raise ValueError("surface rule activation requires counterexample coverage")
        if counterexample_status == "not_applicable" and not str(
            evidence.get("counterexample_reason") or ""
        ).strip():
            raise ValueError("counterexample not_applicable requires a reason")
    elif target == "rolled_back":
        if actor_type != "human":
            raise ValueError("surface rule rollback requires a human actor")
        if not str(evidence.get("rollback_reason") or "").strip():
            raise ValueError("surface rule rollback requires rollback_reason")


def _empty_registry() -> dict[str, Any]:
    return {
        "contract_version": REGISTRY_CONTRACT,
        "updated_at": None,
        "rules": [],
        "production_rule_source": "active_only",
        "candidate_rules_affect_production": False,
        "model_activation_allowed": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _write_registry(root: Path, registry: dict[str, Any]) -> None:
    path = root / RULE_ROOT / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    if not relative_path.strip():
        raise ValueError("surface rule correction_entry_path is required")
    candidate = Path(relative_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("surface rule evidence path escapes project root") from exc
    return resolved
