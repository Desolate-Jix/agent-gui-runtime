from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.learn.application_identity import normalize_application_identity


SINGLE_INTERFACE_ASSET_CONTRACT = "single_interface_asset_v1"
APPLICATION_INTERFACE_LIBRARY_CONTRACT = "application_interface_library_v1"
ASSET_ROOT = Path("artifacts/interface-assets")
_RUNTIME_POINT_KEYS = {
    "actual_point",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "screen_point",
    "target_point",
}
_DYNAMIC_VALUE_KEYS = {
    "current_value",
    "observed_value",
    "value",
    "value_preview",
}
_CONTENT_BEHAVIORS = {
    "fixed_structure",
    "fixed_label",
    "dynamic_value",
    "dynamic_collection",
    "user_input",
    "ephemeral",
    "sensitive_dynamic",
    "ignore",
}
_AGENT_USAGES = {
    "identity_anchor",
    "action_target",
    "decision_signal",
    "display_only",
}
_READ_POLICIES = {
    "on_interface_match",
    "on_demand",
    "never",
}
_FIXED_CONTENT_BEHAVIORS = {"fixed_structure", "fixed_label"}
_DYNAMIC_CONTENT_BEHAVIORS = {
    "dynamic_value",
    "dynamic_collection",
    "user_input",
    "ephemeral",
    "sensitive_dynamic",
}
_SAFE_REGION_ACTION_TYPES = {
    "back",
    "click",
    "close_modal",
    "continue_next_step",
    "fill_field",
    "input",
    "open_apply_flow",
    "open_detail",
    "open_filter",
    "open_link",
    "open_modal",
    "open_search",
    "read",
    "scroll",
    "select",
    "select_option",
    "submit_search",
    "toggle_setting",
    "type_text",
    "wait",
}


def build_single_interface_asset(
    review: dict[str, Any],
    *,
    application_identity: dict[str, Any],
) -> dict[str, Any]:
    """把一个审核节点投影为独立、不可授权执行的界面资产。"""

    if not isinstance(review, dict):
        raise ValueError("single interface review must be an object")
    application = normalize_application_identity(application_identity)
    identity_key = str(application.get("identity_key") or "").strip()
    if application.get("identity_status") != "resolved" or not identity_key:
        raise ValueError("single interface asset requires a resolved application identity")

    state_signature = str(review.get("state_signature") or "").strip()
    interface_id = _safe_identifier(
        review.get("node_id")
        or review.get("interface_id")
        or f"interface_{_stable_hash(state_signature or review)[:12]}"
    )
    if not interface_id:
        raise ValueError("single interface asset requires interface_id")

    evidence = _without_runtime_points(
        review.get("evidence") if isinstance(review.get("evidence"), dict) else {}
    )
    evidence_status = str(review.get("evidence_status") or "").strip()
    if not evidence_status:
        evidence_status = (
            "ready"
            if evidence.get("source_screenshot_path")
            and (
                evidence.get("fused_overlay_path")
                or evidence.get("numbered_overlay_path")
                or evidence.get("human_review_overlay_path")
            )
            else "overlay_missing"
        )
    content_descriptors = _normalize_content_descriptors(
        review.get("content_descriptors")
    )
    regions = _dict_list(review.get("regions"))
    controls = _dict_list(review.get("controls"))
    action_candidates = _dict_list(
        review.get("action_candidates") or review.get("action_templates")
    )
    verification_rules = _dict_list(review.get("verification_rules"))
    projected = _project_human_described_regions(regions)
    controls = _merge_by_identifier(
        controls,
        projected["controls"],
        keys=("control_id", "element_id", "region_id"),
    )
    action_candidates = _merge_by_identifier(
        action_candidates,
        projected["action_candidates"],
        keys=("action_template_id", "action_id"),
    )
    verification_rules = _merge_by_identifier(
        verification_rules,
        projected["verification_rules"],
        keys=("rule_id",),
    )

    return {
        "contract_version": SINGLE_INTERFACE_ASSET_CONTRACT,
        "interface_id": interface_id,
        "application_identity_key": identity_key,
        "application_identity": deepcopy(application),
        "display_name": str(
            review.get("display_name")
            or review.get("name")
            or interface_id
        ).strip(),
        "surface_type": str(review.get("surface_type") or "unknown_surface").strip(),
        "state_signature": state_signature or interface_id,
        "evidence_status": evidence_status,
        "evidence": evidence,
        "fixed_anchors": [
            item
            for item in content_descriptors
            if item["content_behavior"] in _FIXED_CONTENT_BEHAVIORS
        ],
        "dynamic_slots": [
            item
            for item in content_descriptors
            if item["content_behavior"] in _DYNAMIC_CONTENT_BEHAVIORS
        ],
        "states": _dict_list(review.get("states")),
        "regions": regions,
        "controls": controls,
        "action_candidates": action_candidates,
        "verification_rules": verification_rules,
        "blockers": _dict_list(review.get("blockers")),
        "review": {
            "status": str(review.get("review_status") or "needs_human_review").strip(),
            "manual_revision": _without_runtime_points(
                review.get("manual_revision")
                if isinstance(review.get("manual_revision"), dict)
                else {}
            ),
        },
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety": {
            "current_capture_required": True,
            "fresh_grounding_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
    }


def _project_human_described_regions(
    regions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    controls: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    for region in regions:
        region_id = str(region.get("region_id") or "").strip()
        label = str(region.get("label") or region.get("name") or "").strip()
        description = str(
            region.get("agent_description") or region.get("description") or ""
        ).strip()
        action_type = str(
            region.get("action_type") or region.get("semantic_action") or ""
        ).strip().lower()
        human_review = region.get("human_review")
        review_status = str(region.get("review_status") or "").strip()
        has_human_semantics = (
            isinstance(human_review, dict)
            or review_status
            in {"approved", "human_confirmed", "human_reviewed", "reviewed"}
        )
        if (
            not region_id
            or not label
            or not description
            or action_type not in _SAFE_REGION_ACTION_TYPES
            or not has_human_semantics
        ):
            continue

        controls.append(
            {
                "control_id": region_id,
                "label": label,
                "role": str(region.get("role") or "control").strip(),
                "agent_description": description,
                "review_status": "human_reviewed",
                "source_region_id": region_id,
            }
        )
        verification_text = str(region.get("verification_rule") or "").strip()
        verification_rule_ids: list[str] = []
        if verification_text:
            rule_id = f"region_rule_{region_id}"
            verification_rule_ids.append(rule_id)
            rules.append(
                {
                    "rule_id": rule_id,
                    "label": verification_text,
                    "source_region_id": region_id,
                    "review_status": "human_reviewed",
                }
            )
        actions.append(
            {
                "action_template_id": f"region_action_{region_id}",
                "action_type": action_type,
                "semantic_action": action_type,
                "display_name": label,
                "agent_description": description,
                "target_control_id": region_id,
                "target_region_id": region_id,
                "risk_level": str(region.get("risk_level") or "unknown").strip(),
                "review_status": "human_reviewed",
                "verification_rule_ids": verification_rule_ids,
            }
        )
    return {
        "controls": controls,
        "action_candidates": actions,
        "verification_rules": rules,
    }


def _merge_by_identifier(
    primary: list[dict[str, Any]],
    additions: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged = deepcopy(primary)
    seen = {
        str(item.get(key) or "").strip()
        for item in merged
        for key in keys
        if str(item.get(key) or "").strip()
    }
    for item in additions:
        identifier = next(
            (
                str(item.get(key) or "").strip()
                for key in keys
                if str(item.get(key) or "").strip()
            ),
            "",
        )
        if identifier and identifier not in seen:
            merged.append(deepcopy(item))
            seen.add(identifier)
    return merged


def build_interface_agent_context(
    asset: dict[str, Any],
    *,
    live_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把界面资产与当前观察合成为 Agent 可读但不可授权执行的上下文。"""

    normalized = _validated_asset(asset)
    observation = _validated_live_observation(
        live_observation,
        interface_id=normalized["interface_id"],
    )
    values = (
        observation.get("values_by_content_id")
        if isinstance(observation, dict)
        and isinstance(observation.get("values_by_content_id"), dict)
        else {}
    )
    dynamic_content: list[dict[str, Any]] = []
    for descriptor in _normalize_content_descriptors(normalized.get("dynamic_slots")):
        item = deepcopy(descriptor)
        content_id = item["content_id"]
        if content_id not in values:
            item["observation_status"] = "requires_observation"
        elif item["content_behavior"] == "sensitive_dynamic":
            serialized = _canonical_dynamic_value(values[content_id])
            item.update(
                {
                    "observation_status": "current_redacted",
                    "value_length": len(serialized),
                    "value_sha256": hashlib.sha256(
                        serialized.encode("utf-8")
                    ).hexdigest(),
                }
            )
        else:
            item.update(
                {
                    "observation_status": "current",
                    "value": deepcopy(values[content_id]),
                }
            )
        if observation:
            item["capture_id"] = observation["capture_id"]
            item["observed_at"] = observation["observed_at"]
        dynamic_content.append(item)

    return {
        "contract_version": "single_interface_agent_context_v1",
        "interface_id": normalized["interface_id"],
        "application_identity_key": normalized["application_identity_key"],
        "surface_type": normalized["surface_type"],
        "state_signature": normalized["state_signature"],
        "fixed_anchors": deepcopy(normalized.get("fixed_anchors") or []),
        "dynamic_content": dynamic_content,
        "states": deepcopy(normalized.get("states") or []),
        "controls": deepcopy(normalized.get("controls") or []),
        "available_action_candidates": deepcopy(
            normalized.get("action_candidates") or []
        ),
        "verification_rules": deepcopy(
            normalized.get("verification_rules") or []
        ),
        "blockers": deepcopy(normalized.get("blockers") or []),
        "live_observation": {
            "status": "current" if observation else "not_provided",
            "capture_id": observation.get("capture_id") if observation else None,
            "observed_at": observation.get("observed_at") if observation else None,
        },
        "execution_contract": {
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def save_single_interface_asset(
    asset: dict[str, Any],
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """按软件身份保存单界面资产并更新软件级索引。"""

    root = Path(project_root).resolve()
    normalized = _validated_asset(asset)
    identity_key = normalized["application_identity_key"]
    interface_id = normalized["interface_id"]
    application_dir = root / ASSET_ROOT / _safe_path_segment(identity_key)
    interface_dir = application_dir / "interfaces" / _safe_path_segment(interface_id)
    asset_path = interface_dir / "interface.json"
    registry_path = application_dir / "registry.json"
    interface_dir.mkdir(parents=True, exist_ok=True)

    asset_bytes = _json_bytes(normalized)
    asset_sha256 = hashlib.sha256(asset_bytes).hexdigest()
    _atomic_write(asset_path, asset_bytes)

    registry = _load_registry(registry_path, identity_key)
    records = {
        str(item.get("interface_id") or ""): item
        for item in registry.get("records", [])
        if isinstance(item, dict) and str(item.get("interface_id") or "").strip()
    }
    records[interface_id] = {
        "interface_id": interface_id,
        "asset_path": _relative_path(root, asset_path),
        "asset_sha256": asset_sha256,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": normalized["review"]["status"],
        "evidence_status": normalized["evidence_status"],
    }
    registry.update(
        {
            "application_identity": deepcopy(normalized["application_identity"]),
            "interface_ids": sorted(records),
            "records": [records[key] for key in sorted(records)],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _atomic_write(registry_path, _json_bytes(registry))
    return {
        "contract_version": "single_interface_asset_save_result_v1",
        "status": "saved",
        "application_identity_key": identity_key,
        "interface_id": interface_id,
        "asset_path": _relative_path(root, asset_path),
        "asset_sha256": asset_sha256,
        "registry_path": _relative_path(root, registry_path),
        "artifact_is_authorization": False,
    }


def load_application_interface_library(
    application_identity_key: str,
    *,
    project_root: str | Path,
) -> dict[str, Any]:
    """加载一个软件下的全部独立界面资产。"""

    identity_key = str(application_identity_key or "").strip()
    if not identity_key:
        raise ValueError("application identity key is required")
    root = Path(project_root).resolve()
    registry_path = root / ASSET_ROOT / _safe_path_segment(identity_key) / "registry.json"
    registry = _load_registry(registry_path, identity_key, missing_allowed=False)
    interfaces: list[dict[str, Any]] = []
    for record in registry["records"]:
        asset_path = _resolve_under_root(root, str(record.get("asset_path") or ""))
        raw = asset_path.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != str(record.get("asset_sha256") or ""):
            raise ValueError(
                f"single interface asset checksum mismatch: {record.get('interface_id')}"
            )
        payload = json.loads(raw.decode("utf-8-sig"))
        normalized = _validated_asset(payload)
        if normalized["application_identity_key"] != identity_key:
            raise ValueError("single interface asset application identity mismatch")
        interfaces.append(normalized)
    return {
        **deepcopy(registry),
        "interfaces": interfaces,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _validated_asset(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("contract_version") != SINGLE_INTERFACE_ASSET_CONTRACT:
        raise ValueError("single interface asset has an unsupported contract")
    normalized = _without_runtime_points(value)
    interface_id = _safe_identifier(normalized.get("interface_id"))
    identity_key = str(normalized.get("application_identity_key") or "").strip()
    application = normalized.get("application_identity")
    if not interface_id:
        raise ValueError("single interface asset requires interface_id")
    if not identity_key or not isinstance(application, dict):
        raise ValueError("single interface asset requires application identity")
    if str(application.get("identity_key") or "") != identity_key:
        raise ValueError("single interface asset application identity is inconsistent")
    normalized["interface_id"] = interface_id
    normalized["display_only"] = True
    normalized["artifact_is_authorization"] = False
    normalized["execute_binding_enabled"] = False
    return normalized


def _load_registry(
    path: Path,
    identity_key: str,
    *,
    missing_allowed: bool = True,
) -> dict[str, Any]:
    if not path.exists():
        if not missing_allowed:
            raise ValueError(f"application interface library not found: {identity_key}")
        return {
            "contract_version": APPLICATION_INTERFACE_LIBRARY_CONTRACT,
            "application_identity_key": identity_key,
            "application_identity": {},
            "interface_ids": [],
            "records": [],
            "updated_at": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(payload, dict)
        or payload.get("contract_version") != APPLICATION_INTERFACE_LIBRARY_CONTRACT
        or payload.get("application_identity_key") != identity_key
        or not isinstance(payload.get("records"), list)
    ):
        raise ValueError("application interface library registry is invalid")
    return payload


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _without_runtime_points(item)
        for item in value
        if isinstance(item, dict)
    ]


def _normalize_content_descriptors(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("content_descriptors must be a list")
    descriptors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("content descriptor must be an object")
        content_id = _safe_identifier(raw.get("content_id"))
        if not content_id:
            raise ValueError("content descriptor requires content_id")
        if content_id in seen:
            raise ValueError(f"duplicate content descriptor: {content_id}")
        behavior = str(raw.get("content_behavior") or "").strip()
        usage = str(raw.get("agent_usage") or "").strip()
        read_policy = str(raw.get("read_policy") or "").strip()
        if behavior not in _CONTENT_BEHAVIORS:
            raise ValueError(f"unsupported content_behavior: {behavior}")
        if usage not in _AGENT_USAGES:
            raise ValueError(f"unsupported agent_usage: {usage}")
        if read_policy not in _READ_POLICIES:
            raise ValueError(f"unsupported read_policy: {read_policy}")
        descriptor = {
            str(key): _without_runtime_points(item)
            for key, item in raw.items()
            if str(key) not in _DYNAMIC_VALUE_KEYS
        }
        descriptor.update(
            {
                "content_id": content_id,
                "label": str(raw.get("label") or content_id).strip(),
                "source_kind": str(raw.get("source_kind") or "unknown").strip(),
                "source_id": str(raw.get("source_id") or "").strip(),
                "content_behavior": behavior,
                "agent_usage": usage,
                "read_policy": read_policy,
                "agent_description": str(
                    raw.get("agent_description") or ""
                ).strip(),
            }
        )
        seen.add(content_id)
        if behavior != "ignore" and read_policy != "never":
            descriptors.append(descriptor)
    return descriptors


def _validated_live_observation(
    value: dict[str, Any] | None,
    *,
    interface_id: str,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("live interface observation must be an object")
    if value.get("contract_version") != "live_interface_observation_v1":
        raise ValueError("live interface observation has an unsupported contract")
    if str(value.get("interface_id") or "") != interface_id:
        raise ValueError("live interface observation interface identity mismatch")
    capture_id = str(value.get("capture_id") or "").strip()
    observed_at = str(value.get("observed_at") or "").strip()
    if not capture_id or not observed_at:
        raise ValueError("live interface observation requires capture_id and observed_at")
    values = value.get("values_by_content_id")
    if not isinstance(values, dict):
        raise ValueError("live interface observation requires values_by_content_id")
    return {
        "contract_version": "live_interface_observation_v1",
        "interface_id": interface_id,
        "capture_id": capture_id,
        "observed_at": observed_at,
        "values_by_content_id": deepcopy(values),
    }


def _canonical_dynamic_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _without_runtime_points(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_runtime_points(item)
            for key, item in value.items()
            if str(key).replace("-", "_").casefold() not in _RUNTIME_POINT_KEYS
        }
    if isinstance(value, list):
        return [_without_runtime_points(item) for item in value]
    return deepcopy(value)


def _safe_identifier(value: Any) -> str:
    text = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    return cleaned[:96]


def _safe_path_segment(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    if not cleaned:
        raise ValueError("interface asset path segment is empty")
    return cleaned[:120]


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("single interface asset path escapes project root") from exc
    return candidate


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
