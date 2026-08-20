"""Reviewed Workflow Asset v2 的规范合同、校验器和独立 CAS 注册表。

这个模块只负责把人工审核后的语义资产变成不可变对象；它不读取 v1
memory、不执行动作，也不把历史截图坐标当作运行时授权。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping


ASSET_CONTRACT = "reviewed_workflow_asset_v2"
REGISTRY_CONTRACT = "reviewed_workflow_asset_registry_v2"
ASSET_ROOT = Path("runtime_state") / "reviewed-workflow-assets-v2"
_REGISTRY_LOCK = threading.RLock()

_FORBIDDEN_ACTIONS = {
    "finalsubmit",
    "submitapplication",
    "submit",
    "send",
    "confirm",
    "payment",
    "purchase",
    "delete",
    "openexternalapply",
}
_ALLOWED_ACTIONS = {
    "open_detail",
    "open_apply_flow",
    "read",
    "scroll",
    "back",
    "close_modal",
    "fill_field",
    "continue_next_step",
}
_DANGEROUS_REFERENCE_PHRASES = (
    ("final", "submit"),
    ("submit", "application"),
    ("open", "external", "apply"),
)
_DANGEROUS_REFERENCE_TOKENS = {
    "delete",
    "payment",
    "purchase",
    "send",
    "confirm",
    "submit",
}
_ACTION_REFERENCE_TOKENS = {
    "action",
    "account",
    "application",
    "btn",
    "button",
    "command",
    "control",
    "dialog",
    "flow",
    "form",
    "link",
    "modal",
    "operation",
    "request",
    "trigger",
}
_READ_ONLY_REFERENCE_TOKENS = {
    "dashboard",
    "detail",
    "details",
    "field",
    "history",
    "info",
    "information",
    "label",
    "list",
    "log",
    "logs",
    "panel",
    "profile",
    "record",
    "records",
    "row",
    "section",
    "status",
    "summary",
    "table",
    "text",
    "value",
    "view",
}
_REFERENCE_WRAPPER_TOKENS = {
    "actionref",
    "anchor",
    "element",
    "id",
    "locator",
    "memory",
    "ref",
    "reviewed",
    "v1",
    "v2",
}
_RUNTIME_IDENTITY_KEYS = {
    "windowhandle",
    "hwnd",
    "pid",
    "processid",
    "processhandle",
    "windowpid",
    "actualpoint",
    "screenpoint",
    "currentpoint",
    "selectedpoint",
    "clickpoint",
    "coordinate",
    "coordinates",
    "position",
    "currenttargetbbox",
    "targetbbox",
    "boundingbox",
    "rect",
    "currentbbox",
}
_REFERENCE_BOX_KEYS = {"bbox", "referencebbox", "roi", "referenceroi"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LINEAGE_SHA_FIELDS = (
    "source_workflow_sha256",
    "current_revision_hash",
    "reviewed_revision_hash",
    "evidence_sha256",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _text(value).casefold())


def _sort_identified(items: Any, *, id_keys: tuple[str, ...]) -> Any:
    if not isinstance(items, list):
        return items

    def key(item: Any) -> tuple[str, str]:
        if isinstance(item, dict):
            for id_key in id_keys:
                value = _text(item.get(id_key))
                if value:
                    return (value, json.dumps(item, ensure_ascii=False, sort_keys=True))
        return ("", json.dumps(item, ensure_ascii=False, sort_keys=True))

    return sorted(items, key=key)


def _canonicalize_rule_lists(value: Any) -> Any:
    if isinstance(value, dict):
        canonical: dict[str, Any] = {}
        for key, child in value.items():
            normalized_child = _canonicalize_rule_lists(child)
            if key in {
                "verification_rules",
                "semantic_success_rules",
                "post_action_verification_rules",
            }:
                normalized_child = _sort_identified(
                    normalized_child,
                    id_keys=("rule_id", "verification_rule_id", "id"),
                )
            canonical[key] = normalized_child
        return canonical
    if isinstance(value, list):
        return [_canonicalize_rule_lists(item) for item in value]
    return value


def canonicalize_reviewed_workflow_asset(asset: Mapping[str, Any]) -> dict[str, Any]:
    """返回不含运行时元数据、且数组按稳定 ID 排序的规范对象。"""

    if not isinstance(asset, Mapping):
        raise ValueError("reviewed workflow asset must be an object")
    value = deepcopy(dict(asset))
    # 这些字段属于 registry/object metadata，不能改变资产内容 hash。
    for key in ("created_at", "registry_revision", "content_sha256", "object_sha256"):
        value.pop(key, None)
    lineage = value.get("source_review_lineage")
    if isinstance(lineage, dict):
        for field in _LINEAGE_SHA_FIELDS:
            if isinstance(lineage.get(field), str):
                lineage[field] = lineage[field].lower()
        approved_node_ids = lineage.get("human_approved_node_ids")
        if isinstance(approved_node_ids, list):
            lineage["human_approved_node_ids"] = sorted(
                {_text(item) for item in approved_node_ids if _text(item)}
            )
    value["states"] = _sort_identified(value.get("states", []), id_keys=("state_id", "id"))
    value["transitions"] = _sort_identified(
        value.get("transitions", []), id_keys=("transition_id", "id")
    )
    for state in value.get("states", []):
        if not isinstance(state, dict):
            continue
        state["identity_anchors"] = _sort_identified(
            state.get("identity_anchors", []), id_keys=("anchor_id", "identity_anchor_id", "id")
        )
        state["allowed_transition_ids"] = sorted(
            {_text(item) for item in state.get("allowed_transition_ids", []) if _text(item)}
        )
    for transition in value.get("transitions", []):
        if not isinstance(transition, dict):
            continue
        canonical_transition = _canonicalize_rule_lists(transition)
        reviewed_constraints = canonical_transition.get("reviewed_semantic_constraints")
        if isinstance(reviewed_constraints, dict):
            for constraint_key in ("preconditions", "failure_conditions"):
                if constraint_key in reviewed_constraints:
                    reviewed_constraints[constraint_key] = _sort_identified(
                        reviewed_constraints[constraint_key],
                        id_keys=("rule_id",),
                    )
        transition.clear()
        transition.update(canonical_transition)
    return value


def canonical_json_bytes(asset: Mapping[str, Any]) -> bytes:
    """使用固定 UTF-8、紧凑 separators 和 sort_keys 序列化。"""

    canonical = canonicalize_reviewed_workflow_asset(asset)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(asset: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(asset)).hexdigest()


# 兼容后续编译器更直观的命名。
canonical_content_bytes = canonical_json_bytes
compute_content_sha256 = content_sha256


def _walk_runtime_fields(value: Any, *, path: tuple[str, ...] = ()) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_key(key)
            child_path = (*path, str(key))
            normalized_path = tuple(_normalized_key(item) for item in child_path)
            # 唯一例外是 transition grounding 中两个闭合的 required policy 声明。
            current_grounding_policy = (
                normalized in {"clickpoint", "currenttargetbbox"}
                and len(normalized_path) == 5
                and normalized_path[0] == "transitions"
                and normalized_path[1].isdigit()
                and normalized_path[2:4] == ("preconditions", "grounding")
                and normalized_path[4] == normalized
            )
            if normalized in _RUNTIME_IDENTITY_KEYS and not current_grounding_policy:
                errors.append(
                    f"runtime coordinate or window identity field is forbidden: {'.'.join(child_path)}"
                )
            if normalized in _REFERENCE_BOX_KEYS:
                parent = value
                if parent.get("reference_only") is not True:
                    errors.append(
                        f"reference bbox/ROI requires reference_only=true: {'.'.join(child_path)}"
                    )
            errors.extend(_walk_runtime_fields(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_walk_runtime_fields(child, path=(*path, str(index))))
    return errors


def _required(container: Any, key: str, *, label: str, allow_object: bool = False) -> str | None:
    if not isinstance(container, dict) or key not in container:
        return f"{label}.{key} is required"
    value = container[key]
    if isinstance(value, dict):
        if not allow_object and value.get("required") is not True:
            return f"{label}.{key}.required must be true"
    elif value is not True:
        return f"{label}.{key} is required"
    return None


def _nonempty(value: Any, label: str) -> str | None:
    if not _text(value):
        return f"{label} is required"
    return None


def _closed_policy_errors(
    value: Any,
    *,
    label: str,
    allowed_keys: set[str],
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be a closed policy object"]
    unexpected = sorted(set(value) - allowed_keys)
    if unexpected:
        return [f"{label} has unexpected closed policy keys: {','.join(unexpected)}"]
    return []


def _is_normalized_project_relative_path(value: Any) -> bool:
    text = _text(value)
    if not text or "\\" in text:
        return False
    posix_path = PurePosixPath(text)
    windows_path = PureWindowsPath(text)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return False
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        return False
    return posix_path.as_posix() == text and not text.startswith("//")


def _contains_forbidden_semantic_reference(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    tokens = re.findall(r"[a-z0-9]+", separated.casefold())
    for phrase in _DANGEROUS_REFERENCE_PHRASES:
        phrase_length = len(phrase)
        if any(
            tuple(tokens[index : index + phrase_length]) == phrase
            for index in range(len(tokens) - phrase_length + 1)
        ):
            return True
    semantic_tokens = [
        token
        for token in tokens
        if token not in _REFERENCE_WRAPPER_TOKENS and not token.isdigit()
    ]
    for index, token in enumerate(semantic_tokens):
        if token not in _DANGEROUS_REFERENCE_TOKENS:
            continue
        context = semantic_tokens[:index] + semantic_tokens[index + 1 :]
        if not context:
            return True
        if any(item in _ACTION_REFERENCE_TOKENS for item in context):
            return True
        if all(item in _READ_ONLY_REFERENCE_TOKENS for item in context):
            continue
        return True
    return False


def _normalized_filesystem_path(path: Path) -> str:
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif text.startswith("\\\\?\\"):
        text = text[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(text)))


def _validate_asset_errors(asset: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        canonical = canonicalize_reviewed_workflow_asset(asset)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, [str(exc)]

    if canonical.get("contract_version") != ASSET_CONTRACT:
        errors.append(f"contract_version must be {ASSET_CONTRACT}")
    for field in ("asset_id", "entry_state_id"):
        error = _nonempty(canonical.get(field), field)
        if error:
            errors.append(error)
    if not _ID_RE.fullmatch(_text(canonical.get("asset_id"))):
        errors.append("asset_id has invalid stable identity")

    application = canonical.get("application")
    if not isinstance(application, dict):
        errors.append("application is required")
    else:
        if application.get("identity_status") != "resolved":
            errors.append("application identity_status must be resolved")
        kind = _text(application.get("kind") or application.get("type")).casefold()
        if kind == "web":
            if not _text(application.get("canonical_origin") or application.get("canonical_domain")):
                errors.append("web application canonical origin/domain is required")
            if type(application.get("allow_external_sites")) is not bool:
                errors.append("web application allow_external_sites must be an explicit boolean")
        elif kind == "native":
            if not _text(application.get("executable") or application.get("product_identity")):
                errors.append("native application executable/product identity is required")
        else:
            errors.append("application kind must be web or native")

    lineage = canonical.get("source_review_lineage")
    if not isinstance(lineage, dict):
        errors.append("source_review_lineage is required")
    else:
        for field in (
            "source_workflow_path",
            "source_workflow_sha256",
            "current_revision_hash",
            "reviewed_revision_hash",
            "evidence_sha256",
        ):
            if not _text(lineage.get(field)):
                errors.append(f"source_review_lineage.{field} is required")
        if not _is_normalized_project_relative_path(lineage.get("source_workflow_path")):
            errors.append(
                "source_review_lineage.source_workflow_path must be normalized project-relative"
            )
        for field in _LINEAGE_SHA_FIELDS:
            if not _SHA256_RE.fullmatch(_text(lineage.get(field))):
                errors.append(
                    f"source_review_lineage.{field} must be exactly 64 hexadecimal characters"
                )
        if lineage.get("reviewed_by_human") is not True:
            errors.append("source_review_lineage.reviewed_by_human must be true")
        if _text(lineage.get("reviewed_revision_hash")) != _text(
            lineage.get("current_revision_hash")
        ):
            errors.append("reviewed_revision_hash must equal current_revision_hash")
        approved_nodes = lineage.get("human_approved_node_ids")
        if not isinstance(approved_nodes, list) or not approved_nodes:
            errors.append("source_review_lineage.human_approved_node_ids is required")

    states = canonical.get("states")
    if not isinstance(states, list) or not states:
        errors.append("states is required")
        states = []
    state_ids: set[str] = set()
    anchor_ids: set[str] = set()
    reviewed_state_ids: set[str] = set()
    for index, state in enumerate(states):
        label = f"states[{index}]"
        if not isinstance(state, dict):
            errors.append(f"{label} must be an object")
            continue
        state_id = _text(state.get("state_id"))
        if not state_id:
            errors.append(f"{label}.state_id is required")
        elif state_id in state_ids:
            errors.append(f"duplicate state_id: {state_id}")
        else:
            state_ids.add(state_id)
        source_node = _text(state.get("source_node_id"))
        if not source_node:
            errors.append(f"{label}.source_node_id is required")
        availability = _text(state.get("availability"))
        if availability not in {"reviewed", "stop_boundary"}:
            errors.append(f"{label}.availability must be reviewed or stop_boundary")
        if availability == "reviewed":
            reviewed_state_ids.add(state_id)
            if not isinstance(state.get("grounding_profile"), dict):
                errors.append(f"{label}.grounding_profile is required")
        elif availability == "stop_boundary" and state.get("allowed_transition_ids"):
            errors.append(f"{label}.stop_boundary allowed_transition_ids must be empty")
        anchors = state.get("identity_anchors")
        if not isinstance(anchors, list) or not anchors:
            errors.append(f"{label}.identity_anchors is required")
            anchors = []
        for anchor_index, anchor in enumerate(anchors):
            anchor_label = f"{label}.identity_anchors[{anchor_index}]"
            if not isinstance(anchor, dict):
                errors.append(f"{anchor_label} must be an object")
                continue
            anchor_id = _text(anchor.get("anchor_id") or anchor.get("identity_anchor_id") or anchor.get("id"))
            if not anchor_id:
                errors.append(f"{anchor_label}.anchor_id is required")
            elif anchor_id in anchor_ids:
                errors.append(f"duplicate anchor_id: {anchor_id}")
            else:
                anchor_ids.add(anchor_id)
            if not _text(anchor.get("label") or anchor.get("value")):
                errors.append(f"{anchor_label}.label is required")
        for transition_id in state.get("allowed_transition_ids") or []:
            if not _text(transition_id):
                errors.append(f"{label}.allowed_transition_ids contains an empty ID")

    transitions = canonical.get("transitions")
    if not isinstance(transitions, list):
        errors.append("transitions is required")
        transitions = []
    transition_ids: set[str] = set()
    reviewed_constraint_rule_ids: set[str] = set()
    for index, transition in enumerate(transitions):
        label = f"transitions[{index}]"
        if not isinstance(transition, dict):
            errors.append(f"{label} must be an object")
            continue
        transition_id = _text(transition.get("transition_id"))
        if not transition_id:
            errors.append(f"{label}.transition_id is required")
        elif transition_id in transition_ids:
            errors.append(f"duplicate transition_id: {transition_id}")
        else:
            transition_ids.add(transition_id)
        source_id = _text(transition.get("source_state_id"))
        target_id = _text(transition.get("target_state_id"))
        if source_id not in state_ids:
            errors.append(f"unknown source_state_id: {source_id}")
        if target_id not in state_ids:
            errors.append(f"unknown target_state_id: {target_id}")
        action = _text(transition.get("semantic_action"))
        action_normalized = _normalized_key(action)
        if action_normalized in _FORBIDDEN_ACTIONS:
            errors.append(f"forbidden semantic action: {action}")
        elif action not in _ALLOWED_ACTIONS:
            errors.append(f"unsupported semantic action: {action}")
        reference_fields = ("element_ref", "action_ref", "memory_ref", "locator_anchor")
        if not _text(next((transition.get(key) for key in reference_fields if transition.get(key)), "")):
            errors.append(f"{label}.element/action/locator reference is required")
        for reference_field in reference_fields:
            reference = transition.get(reference_field)
            if _contains_forbidden_semantic_reference(reference):
                errors.append(
                    f"forbidden semantic reference in {reference_field}: {_text(reference)}"
                )
        element_ref = _text(transition.get("element_ref"))
        if element_ref and element_ref not in anchor_ids:
            declared_elements = canonical.get("elements")
            declared_element_ids = {
                _text(item.get("element_id") or item.get("id"))
                for item in (declared_elements if isinstance(declared_elements, list) else [])
                if isinstance(item, dict)
            }
            if element_ref not in declared_element_ids:
                errors.append(f"unknown element_ref: {element_ref}")

        source_state = next((state for state in states if isinstance(state, dict) and state.get("state_id") == source_id), None)
        if source_state and source_state.get("availability") != "reviewed":
            errors.append(f"{label}.source_state must be reviewed")
        preconditions = transition.get("preconditions")
        if not isinstance(preconditions, dict):
            errors.append(f"{label}.preconditions is required")
        else:
            errors.extend(
                _closed_policy_errors(
                    preconditions,
                    label=f"{label}.preconditions",
                    allowed_keys={
                        "current_observation",
                        "capture",
                        "grounding",
                        "source_state_unique",
                        "gate",
                        "approved_plan_capture_lineage",
                    },
                )
            )
            for required_key in (
                "current_observation",
                "capture",
                "grounding",
                "source_state_unique",
                "gate",
                "approved_plan_capture_lineage",
            ):
                error = _required(
                    preconditions,
                    required_key,
                    label=f"{label}.preconditions",
                    allow_object=required_key in {"capture", "grounding"},
                )
                if error:
                    errors.append(error)
            for policy_key in (
                "current_observation",
                "source_state_unique",
                "approved_plan_capture_lineage",
            ):
                errors.extend(
                    _closed_policy_errors(
                        preconditions.get(policy_key),
                        label=f"{label}.preconditions.{policy_key}",
                        allowed_keys={"required"},
                    )
                )
            capture = preconditions.get("capture")
            if isinstance(capture, dict):
                errors.extend(
                    _closed_policy_errors(
                        capture,
                        label=f"{label}.preconditions.capture",
                        allowed_keys={"capture_id", "screenshot_sha256", "viewport_size"},
                    )
                )
                for required_key in ("capture_id", "screenshot_sha256", "viewport_size"):
                    error = _required(capture, required_key, label=f"{label}.preconditions.capture")
                    if error:
                        errors.append(error)
                    errors.extend(
                        _closed_policy_errors(
                            capture.get(required_key),
                            label=f"{label}.preconditions.capture.{required_key}",
                            allowed_keys={"required"},
                        )
                    )
            grounding = preconditions.get("grounding")
            if isinstance(grounding, dict):
                errors.extend(
                    _closed_policy_errors(
                        grounding,
                        label=f"{label}.preconditions.grounding",
                        allowed_keys={
                            "required",
                            "current_target_bbox",
                            "click_point",
                            "confidence",
                            "score_margin",
                        },
                    )
                )
                if grounding.get("required") is not True:
                    errors.append(f"{label}.preconditions.grounding.required must be true")
                for required_key in ("current_target_bbox", "click_point", "confidence", "score_margin"):
                    error = _required(grounding, required_key, label=f"{label}.preconditions.grounding")
                    if error:
                        errors.append(error)
                    errors.extend(
                        _closed_policy_errors(
                            grounding.get(required_key),
                            label=f"{label}.preconditions.grounding.{required_key}",
                            allowed_keys={"required"},
                        )
                    )
            gate = preconditions.get("gate")
            if isinstance(gate, dict):
                errors.extend(
                    _closed_policy_errors(
                        gate,
                        label=f"{label}.preconditions.gate",
                        allowed_keys={"required", "endpoint"},
                    )
                )
                endpoint = _text(gate.get("endpoint"))
                if not endpoint:
                    errors.append(f"{label}.preconditions.gate.endpoint is required")
                elif endpoint != "POST /action/execute_recognition_plan":
                    errors.append(f"{label}.preconditions.gate endpoint is invalid")

        reviewed_constraints = transition.get("reviewed_semantic_constraints")
        constraints_label = f"{label}.reviewed_semantic_constraints"
        if not isinstance(reviewed_constraints, dict):
            errors.append(f"{constraints_label} is required")
        else:
            errors.extend(
                _closed_policy_errors(
                    reviewed_constraints,
                    label=constraints_label,
                    allowed_keys={"preconditions", "failure_conditions"},
                )
            )
            for constraint_key, expected_rule_type in (
                ("preconditions", "source_semantic_precondition"),
                ("failure_conditions", "source_semantic_failure_condition"),
            ):
                rules = reviewed_constraints.get(constraint_key)
                rules_label = f"{constraints_label}.{constraint_key}"
                if not isinstance(rules, list):
                    errors.append(f"{rules_label} must be a list")
                    continue
                for rule_index, rule in enumerate(rules):
                    rule_label = f"{rules_label}[{rule_index}]"
                    if not isinstance(rule, dict):
                        errors.append(f"{rule_label} constraint rule must be an object")
                        continue
                    errors.extend(
                        _closed_policy_errors(
                            rule,
                            label=f"{rule_label} constraint rule",
                            allowed_keys={"rule_id", "type", "condition"},
                        )
                    )
                    rule_id = _text(rule.get("rule_id"))
                    if not rule_id or not _ID_RE.fullmatch(rule_id):
                        errors.append(f"{rule_label} constraint rule_id is invalid")
                    elif rule_id in reviewed_constraint_rule_ids:
                        errors.append(f"duplicate reviewed constraint rule_id: {rule_id}")
                    else:
                        reviewed_constraint_rule_ids.add(rule_id)
                    if rule.get("type") != expected_rule_type:
                        errors.append(
                            f"{rule_label} constraint rule type must be {expected_rule_type}"
                        )
                    condition = rule.get("condition")
                    if not isinstance(condition, str) or not condition.strip():
                        errors.append(f"{rule_label} constraint rule condition is required")

        expected = transition.get("expected_effect")
        if not isinstance(expected, dict) or not (
            expected.get("semantic_success") or expected.get("semantic_success_rules")
        ):
            errors.append(f"{label}.expected_effect semantic success is required")
        post = transition.get("post_action_verification")
        if not isinstance(post, dict):
            errors.append(f"{label}.post_action_verification is required")
        else:
            if post.get("requires_new_capture") is not True:
                errors.append(f"{label}.post_action_verification.requires_new_capture is required")
            rules = post.get("semantic_success_rules") or post.get("verification_rules")
            if not isinstance(rules, list) or not rules:
                errors.append(f"{label}.post_action_verification semantic success rules are required")
            else:
                seen_rules: set[str] = set()
                for rule in rules:
                    if not isinstance(rule, dict):
                        errors.append(f"{label}.post_action_verification rule must be an object")
                        continue
                    rule_id = _text(rule.get("rule_id") or rule.get("verification_rule_id") or rule.get("id"))
                    if not rule_id:
                        errors.append(f"{label}.post_action_verification rule_id is required")
                    elif rule_id in seen_rules:
                        errors.append(f"duplicate verification rule_id: {rule_id}")
                    seen_rules.add(rule_id)
        recovery = transition.get("recovery_policy")
        if not isinstance(recovery, dict):
            errors.append(f"{label}.recovery_policy is required")
        else:
            if recovery.get("max_attempts") != 1:
                errors.append(f"{label}.recovery_policy.max_attempts must be 1")
            for key in ("stale_capture", "target_not_found", "post_action_failure", "destination_mismatch", "foreground_change", "unexpected_origin"):
                if not _text(recovery.get(key)):
                    errors.append(f"{label}.recovery_policy.{key} is required")
        risk = transition.get("risk_policy")
        if not isinstance(risk, dict) or risk.get("requires_gate") is not True or risk.get("final_submit_forbidden") is not True:
            errors.append(f"{label}.risk_policy safety gate is required")
        if isinstance(risk, dict):
            requires_confirmation = risk.get("requires_user_confirmation")
            if type(requires_confirmation) is not bool:
                errors.append(
                    f"{label}.risk_policy.requires_user_confirmation must be boolean"
                )
            elif requires_confirmation is True:
                if risk.get("automatic_execution_allowed") is not False:
                    errors.append(
                        f"{label}.risk_policy.automatic_execution_allowed must be false "
                        "when user confirmation is required"
                    )
            elif "automatic_execution_allowed" in risk and type(
                risk.get("automatic_execution_allowed")
            ) is not bool:
                errors.append(
                    f"{label}.risk_policy.automatic_execution_allowed must be boolean"
                )
        if action in {"fill_field", "continue_next_step"} and isinstance(risk, dict) and risk.get("automatic_execution_allowed") is True:
            errors.append(f"{label}.blocked semantic action cannot be automatically executed")

    for state in states:
        if not isinstance(state, dict):
            continue
        state_id = _text(state.get("state_id"))
        for transition_id in state.get("allowed_transition_ids") or []:
            if _text(transition_id) not in transition_ids:
                errors.append(f"unknown allowed_transition_id: {_text(transition_id)}")
                continue
            declared_transition = next(
                (
                    item
                    for item in transitions
                    if isinstance(item, dict)
                    and _text(item.get("transition_id")) == _text(transition_id)
                ),
                None,
            )
            if declared_transition is not None and _text(
                declared_transition.get("source_state_id")
            ) != state_id:
                errors.append(
                    f"allowed_transition_id {_text(transition_id)} belongs to a different source state"
                )
    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        transition_id = _text(transition.get("transition_id"))
        source_id = _text(transition.get("source_state_id"))
        source_state = next(
            (
                state
                for state in states
                if isinstance(state, dict) and _text(state.get("state_id")) == source_id
            ),
            None,
        )
        if source_state is not None and transition_id not in {
            _text(item) for item in source_state.get("allowed_transition_ids") or []
        }:
            errors.append(
                f"source state {source_id} must declare transition {transition_id}"
            )
    if _text(canonical.get("entry_state_id")) not in state_ids:
        errors.append(f"unknown entry_state_id: {_text(canonical.get('entry_state_id'))}")
    if not reviewed_state_ids:
        errors.append("at least one reviewed state is required")
    if isinstance(lineage, dict):
        approved_nodes = {_text(item) for item in lineage.get("human_approved_node_ids") or []}
        missing = [
            _text(state.get("source_node_id"))
            for state in states
            if isinstance(state, dict)
            and state.get("availability") == "reviewed"
            and _text(state.get("source_node_id")) not in approved_nodes
        ]
        if missing:
            errors.append(f"reviewed state source nodes are not human approved: {','.join(missing)}")

    safety = canonical.get("safety")
    if not isinstance(safety, dict):
        errors.append("safety is required")
    else:
        required_false = ("artifact_is_authorization", "execute_binding_enabled", "historical_coordinates_used")
        for field in required_false:
            if safety.get(field) is not False:
                errors.append(f"safety.{field} must be false")
        required_true = ("final_submit_forbidden", "real_action_requires_gate", "fresh_grounding_required", "post_action_verification_required")
        for field in required_true:
            if safety.get(field) is not True:
                errors.append(f"safety.{field} must be true")
    if not isinstance(canonical.get("lifecycle"), dict):
        errors.append("lifecycle is required")
    errors.extend(_walk_runtime_fields(canonical))
    return canonical, errors


def validate_reviewed_workflow_asset(asset: Mapping[str, Any]) -> dict[str, Any]:
    canonical, errors = _validate_asset_errors(asset)
    if errors:
        raise ValueError("; ".join(errors))
    assert canonical is not None
    return canonical


def validate_asset(asset: Mapping[str, Any]) -> dict[str, Any]:
    return validate_reviewed_workflow_asset(asset)


def reviewed_workflow_asset_validation_errors(asset: Mapping[str, Any]) -> list[str]:
    _, errors = _validate_asset_errors(asset)
    return errors


@contextmanager
def _exclusive_file_lock(lock_path: Path, *, timeout_seconds: float = 10.0):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    handle = lock_path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            while not locked:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "reviewed workflow asset registry lock timed out"
                        )
                    time.sleep(0.025)
        else:
            import fcntl

            while not locked:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except (BlockingIOError, OSError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "reviewed workflow asset registry lock timed out"
                        )
                    time.sleep(0.025)
        yield
    finally:
        try:
            if locked:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class ReviewedWorkflowAssetStore:
    """reviewed-workflow-assets-v2 的 content-addressed CAS registry。"""

    def __init__(self, *, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / ASSET_ROOT
        self.objects_root = self.root / "objects"
        self.registry_path = self.root / "registry.json"
        self.lock_path = self.root / ".registry.lock"

    def _assert_storage_layout(self) -> None:
        try:
            runtime_root = (self.project_root / "runtime_state").resolve(strict=False)
            runtime_root.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError("runtime_state redirection resolves outside project root") from exc
        expected_root = runtime_root / "reviewed-workflow-assets-v2"
        if _normalized_filesystem_path(
            self.root.resolve(strict=False)
        ) != _normalized_filesystem_path(expected_root):
            raise ValueError("reviewed workflow asset root redirection is forbidden")
        for path, expected in (
            (self.objects_root, expected_root / "objects"),
            (self.registry_path, expected_root / "registry.json"),
            (self.lock_path, expected_root / ".registry.lock"),
        ):
            resolved = path.resolve(strict=False)
            if _normalized_filesystem_path(resolved) != _normalized_filesystem_path(expected):
                raise ValueError(
                    "reviewed workflow asset storage redirection is forbidden: "
                    f"{path} resolved to {resolved}, expected {expected}"
                )

    def _assert_object_path(self, path: Path, object_sha: str) -> None:
        self._assert_storage_layout()
        expected = self.objects_root.resolve(strict=False) / f"{object_sha}.json"
        if _normalized_filesystem_path(
            path.resolve(strict=False)
        ) != _normalized_filesystem_path(expected):
            raise ValueError("reviewed workflow asset object redirection is forbidden")

    def _relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.project_root).as_posix()

    def _load_registry(self) -> dict[str, Any]:
        self._assert_storage_layout()
        if not self.registry_path.exists():
            return {"contract_version": REGISTRY_CONTRACT, "registry_revision": 0, "objects": {}, "active_by_asset": {}, "events": []}
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid reviewed workflow asset registry") from exc
        if not isinstance(registry, dict) or registry.get("contract_version") != REGISTRY_CONTRACT:
            raise ValueError("invalid registry contract; v1 migration is not supported")
        if not isinstance(registry.get("registry_revision"), int) or registry["registry_revision"] < 0:
            raise ValueError("invalid reviewed workflow asset registry revision")
        for key in ("objects", "active_by_asset", "events"):
            if not isinstance(registry.get(key), (dict if key != "events" else list)):
                raise ValueError(f"invalid reviewed workflow asset registry {key}")
        return registry

    def registry(self) -> dict[str, Any]:
        with _REGISTRY_LOCK:
            return deepcopy(self._load_registry())

    def publish(
        self,
        asset: Mapping[str, Any] | None = None,
        *,
        expected_registry_revision: int,
        reviewed_workflow_asset: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        candidate = asset if asset is not None else reviewed_workflow_asset
        if candidate is None:
            raise ValueError("reviewed workflow asset is required")
        canonical = validate_reviewed_workflow_asset(candidate)
        object_bytes = canonical_json_bytes(canonical)
        object_sha = hashlib.sha256(object_bytes).hexdigest()
        asset_id = _text(canonical["asset_id"])
        object_path = self.objects_root / f"{object_sha}.json"

        with _REGISTRY_LOCK:
            self._assert_storage_layout()
            with _exclusive_file_lock(self.lock_path):
                self._assert_storage_layout()
                self._assert_object_path(object_path, object_sha)
                registry = self._load_registry()
                revision = int(registry["registry_revision"])
                active_sha = _text(registry.get("active_by_asset", {}).get(asset_id))
                # 同一 hash 的重复 publish 是无副作用幂等操作，不消耗 CAS revision。
                if active_sha == object_sha:
                    self._verify_object(object_path, object_sha, canonical)
                    return self._publish_result(
                        status="already_published",
                        asset_id=asset_id,
                        object_sha=object_sha,
                        object_path=object_path,
                        registry_revision=revision,
                    )
                if revision != int(expected_registry_revision):
                    raise ValueError(
                        f"registry revision mismatch: expected {expected_registry_revision}, actual {revision}"
                    )
                if object_path.exists():
                    self._verify_object(object_path, object_sha, canonical)
                else:
                    _atomic_write(object_path, object_bytes)
                next_revision = revision + 1
                registry.setdefault("objects", {})[object_sha] = {
                    "asset_id": asset_id,
                    "object_path": self._relative_path(object_path),
                    "content_sha256": object_sha,
                    "status": "active",
                }
                registry.setdefault("active_by_asset", {})[asset_id] = object_sha
                registry.setdefault("events", []).append(
                    {
                        "event_id": f"publish_{next_revision}",
                        "event_type": "publish",
                        "registry_revision": next_revision,
                        "asset_id": asset_id,
                        "content_sha256": object_sha,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "artifact_is_authorization": False,
                    }
                )
                registry["registry_revision"] = next_revision
                _atomic_write(
                    self.registry_path,
                    json.dumps(
                        registry,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
        return self._publish_result(
            status="published",
            asset_id=asset_id,
            object_sha=object_sha,
            object_path=object_path,
            registry_revision=next_revision,
        )

    def _publish_result(self, *, status: str, asset_id: str, object_sha: str, object_path: Path, registry_revision: int) -> dict[str, Any]:
        return {
            "contract_version": "reviewed_workflow_asset_publish_v2",
            "status": status,
            "asset_id": asset_id,
            "content_sha256": object_sha,
            "object_sha256": object_sha,
            "object_path": self._relative_path(object_path),
            "registry_path": self._relative_path(self.registry_path),
            "registry_revision": registry_revision,
            "active": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    def _verify_object(self, object_path: Path, object_sha: str, expected: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._assert_object_path(object_path, object_sha)
        if not object_path.exists():
            raise ValueError("reviewed workflow asset object is missing")
        actual = hashlib.sha256(object_path.read_bytes()).hexdigest()
        if actual != object_sha:
            raise ValueError("reviewed workflow asset object checksum mismatch")
        try:
            payload = json.loads(object_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("reviewed workflow asset object is invalid JSON") from exc
        validated = validate_reviewed_workflow_asset(payload)
        if content_sha256(validated) != object_sha:
            raise ValueError("reviewed workflow asset content checksum mismatch")
        if expected is not None and canonical_json_bytes(expected) != object_path.read_bytes():
            raise ValueError("reviewed workflow asset object hash collision")
        return validated

    def load_active(self, asset_id: str) -> dict[str, Any]:
        requested = _text(asset_id)
        if not requested:
            raise ValueError("asset_id is required")
        with _REGISTRY_LOCK:
            registry = self._load_registry()
            object_sha = _text(registry.get("active_by_asset", {}).get(requested))
            if not object_sha:
                raise ValueError(f"active reviewed workflow asset not found: {requested}")
            record = registry.get("objects", {}).get(object_sha)
            if not isinstance(record, dict):
                raise ValueError("active reviewed workflow asset registry record is missing")
            if record.get("asset_id") != requested or record.get("content_sha256") != object_sha:
                raise ValueError("reviewed workflow asset registry identity mismatch")
            declared_path = _text(record.get("object_path"))
            expected_path = self._relative_path(self.objects_root / f"{object_sha}.json")
            if declared_path != expected_path:
                raise ValueError("reviewed workflow asset object path is invalid")
            payload = self._verify_object(
                self.objects_root / f"{object_sha}.json",
                object_sha,
            )
            if _text(payload.get("asset_id")) != requested:
                raise ValueError("reviewed workflow asset payload asset identity mismatch")
            return deepcopy(payload)

    def load(self, asset_id: str) -> dict[str, Any]:
        return self.load_active(asset_id)

    def load_published(self, asset_id: str) -> dict[str, Any]:
        return self.load_active(asset_id)


ContentAddressedWorkflowAssetStore = ReviewedWorkflowAssetStore
ReviewedWorkflowAssetCAS = ReviewedWorkflowAssetStore
