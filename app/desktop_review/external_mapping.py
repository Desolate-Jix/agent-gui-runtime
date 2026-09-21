"""把 Agent Link 外部暂存数据映射为只读审核草稿，不提升其来源权限。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.agent.scroll_parameters import SCROLL_SEMANTIC_ACTION
from app.agent.text_parameters import TEXT_SEMANTIC_ACTION
from app.agent_link.contracts import AgentLinkError, validate_batch
from app.learn.application_identity import normalize_application_identity
from app.learn.interface_workflow_review import (
    INTERFACE_WORKFLOW_REVIEW_CONTRACT,
)


_DANGEROUS_ACTIONS = {
    "confirm",
    "delete",
    "final_submit",
    "payment",
    "send",
    "submit",
}


class ExternalMappingError(ValueError):
    """外部工作区输入不符合原始 inbox 契约。"""


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ExternalMappingError("工作区内容不是规范 JSON") from error


def normalize_agent_link_batch(
    value: Any, *, existing_png_sha256: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """只移除服务端派生的图像字段，再复用 Agent Link 的严格校验。"""

    if not isinstance(value, dict):
        raise ExternalMappingError("审核批次必须是对象")
    candidate = deepcopy(value)
    screenshots = candidate.get("screenshots")
    if not isinstance(screenshots, list):
        raise ExternalMappingError("审核批次 screenshots 必须是数组")
    supplied_derivations: list[dict[str, Any]] = []
    for screenshot in screenshots:
        if not isinstance(screenshot, dict):
            raise ExternalMappingError("审核批次 screenshot 必须是对象")
        allowed = {"screenshot_id", "png_base64", "sha256", "width", "height"}
        if set(screenshot) - allowed:
            raise ExternalMappingError("审核批次含有未知截图权限字段")
        supplied_derivations.append(
            {
                key: screenshot[key]
                for key in ("sha256", "width", "height")
                if key in screenshot
            }
        )
        screenshot.pop("sha256", None)
        screenshot.pop("width", None)
        screenshot.pop("height", None)
    try:
        normalized = validate_batch(candidate, existing_png_sha256=existing_png_sha256)
    except AgentLinkError as error:
        raise ExternalMappingError(
            f"审核批次不满足 agent_link_v1：{error.code}"
        ) from error
    for supplied, screenshot in zip(supplied_derivations, normalized["screenshots"]):
        if any(supplied.get(key) != screenshot[key] for key in supplied):
            raise ExternalMappingError("截图派生摘要或尺寸与 PNG 证据不一致")
    return normalized


def source_ref_for_batch(batch: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(batch)).hexdigest()


def assert_source_identity(
    original: dict[str, Any], edited: dict[str, Any], *, allow_region_additions: bool = False, allow_step_additions: bool = False, allow_relationship_additions: bool = False, allow_interface_additions: bool = False
) -> None:
    """允许人工修订语义和框，但不允许替换外部证据、稳定 ID 或批次身份。"""

    for field in ("contract_version", "idempotency_key", "batch_id"):
        if edited.get(field) != original.get(field):
            raise ExternalMappingError(f"不允许修改原始批次身份：{field}")

    original_shots = [
        (item["screenshot_id"], item["png_base64"])
        for item in original["screenshots"]
    ]
    edited_shots = [
        (item["screenshot_id"], item["png_base64"])
        for item in edited["screenshots"]
    ]
    if (edited_shots != original_shots if not allow_interface_additions else edited_shots[:len(original_shots)] != original_shots):
        raise ExternalMappingError("不允许替换原始截图证据")
    if (len(original["interfaces"]) != len(edited["interfaces"]) if not allow_interface_additions else len(edited["interfaces"]) < len(original["interfaces"])):
        raise ExternalMappingError("不允许修改外部界面、截图或区域稳定身份")
    for before, after in zip(original["interfaces"], edited["interfaces"]):
        if (before["interface_id"], before["screenshot_id"]) != (after["interface_id"], after["screenshot_id"]):
            raise ExternalMappingError("不允许修改外部界面、截图或区域稳定身份")
        old_ids = [region["region_id"] for region in before["regions"]]
        new_ids = [region["region_id"] for region in after["regions"]]
        if (new_ids != old_ids if not allow_region_additions else new_ids[:len(old_ids)] != old_ids):
            raise ExternalMappingError("不允许修改外部界面、截图或区域稳定身份")
        if len(set(new_ids)) != len(new_ids):
            raise ExternalMappingError("不允许修改外部区域稳定身份")
    old_relationships = [item["relationship_id"] for item in original["relationships"]]
    new_relationships = [item["relationship_id"] for item in edited["relationships"]]
    if (new_relationships != old_relationships if not allow_relationship_additions else new_relationships[:len(old_relationships)] != old_relationships):
        raise ExternalMappingError("不允许修改外部关系稳定身份")
    original_step_ids = [item["step_id"] for item in original["steps"]]
    edited_step_ids = [item["step_id"] for item in edited["steps"]]
    if (
        len(set(original_step_ids)) != len(original_step_ids)
        or len(set(edited_step_ids)) != len(edited_step_ids)
        or (not allow_step_additions and set(edited_step_ids) != set(original_step_ids))
        or (allow_step_additions and not set(original_step_ids) <= set(edited_step_ids))
    ):
        raise ExternalMappingError("不允许修改外部步骤稳定身份")
    if [item["issue_id"] for item in edited["issues"]] != [
        item["issue_id"] for item in original["issues"]
    ]:
        raise ExternalMappingError("不允许修改外部问题稳定身份")


def source_image_relative_path(source_ref: str, screenshot: dict[str, Any]) -> str:
    stable = _safe_segment(str(screenshot["screenshot_id"]))
    return (
        Path("desktop-review")
        / "sources"
        / source_ref
        / "screenshots"
        / f"{stable}-{screenshot['sha256']}.png"
    ).as_posix()


def normalize_step_relationships(batch: dict, value: Any) -> dict[str, list[str]]:
    """统一校验显式关系绑定，不按端点替 Agent 选关系。"""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ExternalMappingError("step_relationships must be an object")
    steps = {item["step_id"]: item for item in batch["steps"]}
    relationships = {item["relationship_id"]: item for item in batch["relationships"]}
    if set(value) - set(steps):
        raise ExternalMappingError("step_relationships contains unknown step")
    seen = set()
    for step_id, relationship_ids in value.items():
        if not isinstance(relationship_ids, list) or any(
            not isinstance(item, str) for item in relationship_ids
        ):
            raise ExternalMappingError("relationship ids must be arrays")
        step = steps[step_id]
        for relationship_id in relationship_ids:
            if relationship_id not in relationships or relationship_id in seen:
                raise ExternalMappingError("relationship mapping is invalid")
            relationship = relationships[relationship_id]
            if (
                relationship["from_interface_id"] != step["start_state"]
                or relationship["to_interface_id"] != step["arrival_state"]
            ):
                raise ExternalMappingError("relationship and step endpoints differ")
            seen.add(relationship_id)
    return {key: sorted(item) for key, item in value.items()}


def build_external_workflow_review(
    *,
    batch: dict[str, Any],
    task_id: str,
    source_ref: str,
    revision: int,
    step_relationships: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """构造未批准、不可执行的既有 workflow-review 草稿。"""

    if revision < 1:
        raise ExternalMappingError("保存修订号必须为正数")
    relation_bindings = normalize_step_relationships(batch, step_relationships)
    relationships = {item["relationship_id"]: item for item in batch["relationships"]}
    screenshot_by_id = {
        item["screenshot_id"]: item for item in batch["screenshots"]
    }
    node_ids = {
        item["interface_id"]: _semantic_id("interface", item["interface_id"])
        for item in batch["interfaces"]
    }
    step_ids = {
        item["step_id"]: _semantic_id("step", item["step_id"])
        for item in batch["steps"]
    }
    source_path = (
        Path("desktop-review") / "sources" / source_ref / "original_batch.json"
    ).as_posix()
    nodes: list[dict[str, Any]] = []
    scroll_target_region_ids = {
        step["target_region_id"]
        for step in batch["steps"]
        if step["action_type"] == SCROLL_SEMANTIC_ACTION
    }
    for interface in batch["interfaces"]:
        screenshot = screenshot_by_id[interface["screenshot_id"]]
        regions = [deepcopy(region) for region in interface["regions"]]
        controls = [
            {
                "control_id": region["region_id"],
                "region_id": region["region_id"],
                "semantic_name": str(
                    region.get("name")
                    or region.get("label")
                    or region.get("meaning")
                ),
                "bbox": deepcopy(region["bbox"]),
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
            for region in regions
            if region["region_id"] not in scroll_target_region_ids
        ]
        actions = [
            {
                "action_template_id": step_ids[step["step_id"]],
                "action_id": step_ids[step["step_id"]],
                "display_name": step["step_id"],
                "external_step_id": step["step_id"],
                "semantic_action": (
                    step["action_type"]
                    if step["action_type"] in {SCROLL_SEMANTIC_ACTION, TEXT_SEMANTIC_ACTION}
                    else "unknown_action"
                ),
                "action_type": (
                    step["action_type"]
                    if step["action_type"] in {SCROLL_SEMANTIC_ACTION, TEXT_SEMANTIC_ACTION}
                    else "unknown_action"
                ),
                "external_declared_action_type": step["action_type"],
                "target_region_id": step["target_region_id"] or "",
                **(
                    {"scroll_parameters": deepcopy(step["scroll_parameters"])}
                    if step["action_type"] == SCROLL_SEMANTIC_ACTION
                    else {}
                ),
                "expected_result": step["expected_result"],
                **({"text_parameters": deepcopy(step["text_parameters"])} if step["action_type"] == TEXT_SEMANTIC_ACTION else {}),
                "stop_condition": step["stop_condition"],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
            for step in batch["steps"]
            if step["start_state"] == interface["interface_id"]
        ]
        image_path = source_image_relative_path(source_ref, screenshot)
        nodes.append(
            {
                "node_id": node_ids[interface["interface_id"]],
                "display_name": interface["meaning"],
                "external_interface_id": interface["interface_id"],
                "surface_type": "external_untrusted_interface",
                "state_signature": (
                    f"agent_link:{source_ref}:{interface['interface_id']}"
                ),
                "source_paths": [source_path],
                "observation_count": 1,
                "evidence_status": "ready",
                "evidence": {
                    "source_screenshot_path": image_path,
                    "source_screenshot_sha256": screenshot["sha256"],
                    "source_path": source_path,
                    "source_sha256": source_ref,
                    "external_source_kind": "untrusted_external",
                },
                "agent_description": interface["meaning"],
                **({"recognition_text": interface["recognition_text"]} if interface.get("recognition_text") else {}),
                "content_descriptors": [],
                "page_details": {
                    "screen": {
                        "summary": interface["meaning"],
                        "source_image_path": image_path,
                        "source_image_sha256": screenshot["sha256"],
                    }
                },
                "ui_hierarchy": {},
                "hierarchy_ownership_review": {},
                "selection_replay_provenance": {},
                "states": [],
                "regions": regions,
                "controls": controls,
                "action_candidates": actions,
                "blockers": [
                    {
                        "kind": "external_untrusted_source",
                        "message": "外部提议必须经人工逐修订审核后才能进入执行编译。",
                        # 来源提示不代表运行时危险；未经人审仍由编译与发布边界阻断。
                        "safe_stop_required": False,
                    }
                ],
                "verification_rules": [],
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
                "execution_verification_status": "not_verified",
                "manual_revision": {},
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
    edges: list[dict[str, Any]] = []
    for step in batch["steps"]:
        declared_action = str(step["action_type"]).strip().casefold()
        risk = "high" if declared_action in _DANGEROUS_ACTIONS else "medium"
        edges.append(
            {
                "edge_id": _semantic_id("edge", step["step_id"]),
                "operation_id": step_ids[step["step_id"]],
                "source_node_id": node_ids[step["start_state"]],
                "target_node_id": node_ids[step["arrival_state"]],
                "display_name": step["step_id"],
                "external_step_id": step["step_id"],
                "action_type": (
                    declared_action
                    if declared_action in {SCROLL_SEMANTIC_ACTION, TEXT_SEMANTIC_ACTION}
                    else "unknown_action"
                ),
                "semantic_action": (
                    declared_action
                    if declared_action in {SCROLL_SEMANTIC_ACTION, TEXT_SEMANTIC_ACTION}
                    else "unknown_action"
                ),
                "external_declared_action_type": step["action_type"],
                "external_stop_boundary": True,
                "target_region_id": step["target_region_id"] or "",
                **(
                    {"scroll_parameters": deepcopy(step["scroll_parameters"])}
                    if declared_action == SCROLL_SEMANTIC_ACTION
                    else {}
                ),
                "target_control_id": "",
                **({"text_parameters": deepcopy(step["text_parameters"])} if declared_action == TEXT_SEMANTIC_ACTION else {}),
                "risk_level": risk,
                "requires_user_confirmation": True,
                "preconditions": deepcopy(step["prerequisites"]),
                "success_conditions": [step["expected_result"]],
                "failure_conditions": [step["stop_condition"]],
                "gate_policy": "fresh_grounding_and_gate_required",
                "verification_evidence": {},
                "review_status": "needs_human_review",
                "reviewed_by_human": False,
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        bound_ids = relation_bindings.get(step["step_id"], [])
        if bound_ids:
            # 关联是审核来源，不提升动作权限或把自由文字当作执行条件。
            edges[-1]["external_relationships"] = [
                deepcopy(relationships[relationship_id]) for relationship_id in bound_ids
            ]
    identity = normalize_application_identity({"name": batch["title"]})
    content_ref = hashlib.sha256(canonical_json_bytes(batch)).hexdigest()[:12]
    workflow_id = _workflow_id(
        task_id=task_id,
        batch_id=batch["batch_id"],
        revision=revision,
        content_ref=content_ref,
    )
    return {
        "contract_version": INTERFACE_WORKFLOW_REVIEW_CONTRACT,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": workflow_id,
            "goal": batch["title"],
            "application_identity": identity,
            "entry_node_id": nodes[0]["node_id"] if nodes else "",
            "node_ids": [node["node_id"] for node in nodes],
            "edge_ids": [edge["edge_id"] for edge in edges],
            "review_status": "needs_human_review" if nodes else "not_covered",
            "published_memory_version": None,
        },
        "nodes": nodes,
        "edges": edges,
        "invalid_sources": [],
        "source": {
            "kind": "untrusted_external",
            "task_id": task_id,
            "batch_id": batch["batch_id"],
            "batch_sha256": source_ref,
        },
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
            "send_delete_confirm_payment_forbidden": True,
        },
    }


def _safe_segment(value: str) -> str:
    """保留旧截图路径规则，避免既有 revision 的 PNG 引用失效。"""
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._")
    if text:
        return text[:80]
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _semantic_id(prefix: str, raw_id: str) -> str:
    return f"{prefix}_{_semantic_segment(raw_id)}"


def _semantic_segment(raw_id: str) -> str:
    """语义引用保留可读前缀，并附原始 UTF-8 ID 的完整 SHA-256。"""
    raw = str(raw_id)
    return f"{_readable_prefix(raw, limit=48)}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _workflow_id(*, task_id: str, batch_id: str, revision: int, content_ref: str) -> str:
    """限制 Windows 路径组件长度，同时散列完整外部 task/batch 对。"""
    raw_pair = {"task_id": str(task_id), "batch_id": str(batch_id)}
    pair_digest = hashlib.sha256(canonical_json_bytes(raw_pair)).hexdigest()
    return (
        f"agent_link_{_readable_prefix(task_id, limit=12)}"
        f"_{_readable_prefix(batch_id, limit=12)}_{pair_digest}"
        f"_r{revision}_{content_ref}"
    )


def _readable_prefix(raw_id: str, *, limit: int) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(raw_id)).strip("._")[:limit] or "id"
