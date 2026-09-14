"""候选字段的唯一纯投影定义，供入口、比较与采用共用。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any


CHANGE_TYPES = (
    "geometry", "regions_add", "interfaces_add", "steps_add", "relationships_add", "relationship", "relationship_flow", "semantic",
    "step", "step_flow", "step_order",
)
FLOW_CHANGE_TYPES = frozenset({"relationship_flow", "step_flow", "step_order"})
STEP_FIELDS = (
    "action_type", "target_region_id", "start_state", "arrival_state",
    "prerequisites", "expected_result", "stop_condition",
)
RELATIONSHIP_FIELDS = ("from_interface_id", "to_interface_id", "kind")
_OPTIONAL_TARGET_ACTIONS = frozenset({"observe", "safe_stop"})


class CandidateProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class ProjectedField:
    change_index: int
    target_type: str
    target_id: str
    field: str
    proposed: Any


def project_candidate_fields(
    candidate: dict[str, Any],
    baseline_batch: dict[str, Any],
    scope: dict[str, list[str]],
    *,
    reject_duplicate_fields: bool = True,
) -> list[ProjectedField]:
    """校验范围并把每种候选变化展开为不可变字段写入。"""

    interfaces = {item["interface_id"]: item for item in baseline_batch["interfaces"]}
    baseline_interface_ids = set(interfaces)
    # 先登记新增区域，以便后续步骤无须依赖 change 顺序。
    additions: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for change in candidate["changes"]:
        if change["change_type"] != "regions_add":
            continue
        parent = interfaces.get(change["interface_id"])
        if parent is None or parent["interface_id"] not in set(scope["interface_ids"]):
            raise CandidateProjectionError("invalid_reference", "region additions are outside scope")
        for region in change["regions"]:
            if region["region_id"] in additions:
                raise CandidateProjectionError("invalid_reference", "added region ids must be unique")
            additions[region["region_id"]] = (parent, region)
    
    regions = {
        region["region_id"]: (interface, region)
        for interface in baseline_batch["interfaces"]
        for region in interface["regions"]
    }
    if set(additions) & set(regions):
        raise CandidateProjectionError("invalid_reference", "added region id already exists")
    baseline_region_ids = set(regions)
    regions.update(additions)
    # 新证据按完整集合校验，先登记以支持任意 change 顺序。
    from .contracts import AgentLinkError
    from .interface_additions import validate_interface_evidence
    interface_additions: dict[str, tuple[str, dict[str, Any]]] = {}
    screenshot_additions: dict[str, dict[str, Any]] = {}
    occupied = deepcopy(baseline_batch)
    for change in candidate["changes"]:
        if change["change_type"] != "interfaces_add":
            continue
        if "review_baseline_sha256" not in candidate:
            raise CandidateProjectionError("invalid_baseline", "new interfaces require an exact human baseline")
        anchor = change["anchor_interface_id"]
        if not isinstance(anchor, str) or anchor not in baseline_interface_ids or anchor not in set(scope["interface_ids"]):
            raise CandidateProjectionError("invalid_reference", "interface anchor is outside scope")
        try:
            shots, views = validate_interface_evidence(occupied, change["screenshots"], change["interfaces"])
        except AgentLinkError as error:
            raise CandidateProjectionError(error.code, error.message) from error
        for interface in views:
            if any(region["region_id"] in regions for region in interface["regions"]):
                raise CandidateProjectionError("invalid_reference", "new interface region id collides")
            interface_additions[interface["interface_id"]] = (anchor, interface)
        screenshot_additions.update({shot["screenshot_id"]: shot for shot in shots})
        occupied["screenshots"].extend(shots)
        occupied["interfaces"].extend(views)
    interfaces.update({identifier: interface for identifier, (_, interface) in interface_additions.items()})
    regions.update({region["region_id"]: (interface, region) for _, interface in interface_additions.values() for region in interface["regions"]})
    relationships = {
        item["relationship_id"]: item for item in baseline_batch["relationships"]
    }
    steps = {item["step_id"]: item for item in baseline_batch["steps"]}
    baseline_step_ids = set(steps)
    baseline_relationship_ids = set(relationships)
    if any(change["change_type"] == "steps_add" for change in candidate["changes"]) and any(change["change_type"] == "step_order" for change in candidate["changes"]):
        raise CandidateProjectionError("invalid_reference", "steps_add and step_order cannot be combined")
    interface_scope = set(scope["interface_ids"])
    effective_interface_scope = interface_scope | set(interface_additions)
    relationship_scope = set(scope["relationship_ids"])
    exact_baseline = "review_baseline_sha256" in candidate
    writes: list[ProjectedField] = []
    seen: set[tuple[str, str, str]] = set()

    for change_index, change in enumerate(candidate["changes"]):
        change_type = change["change_type"]
        if (change_type in FLOW_CHANGE_TYPES or change_type in {"regions_add", "steps_add", "relationships_add"}) and not exact_baseline:
            raise CandidateProjectionError(
                "invalid_baseline", "flow changes require an exact human review baseline"
            )
        if change_type == "interfaces_add":
            proposed=[]
            for shot in change["screenshots"]:
                proposed.append(("screenshot",shot["screenshot_id"],"entity",screenshot_additions[shot["screenshot_id"]]))
            for interface in change["interfaces"]:
                proposed.append(("interface",interface["interface_id"],"entity",{"anchor_interface_id":change["anchor_interface_id"],"interface":interface}))
        elif change_type == "steps_add":
            anchor = change.get("after_step_id")
            if anchor is not None and (anchor not in baseline_step_ids or steps[anchor]["start_state"] not in interface_scope):
                raise CandidateProjectionError("invalid_reference", "step insertion anchor is outside scope")
            proposed = []
            for step in change["steps"]:
                target = regions.get(step.get("target_region_id")) if step.get("target_region_id") is not None else None
                action = step["action_type"].strip().casefold()
                optional = action in _OPTIONAL_TARGET_ACTIONS
                if (step["step_id"] in baseline_step_ids or step["start_state"] not in effective_interface_scope or step["arrival_state"] not in effective_interface_scope
                    or (not optional and (target is None or target[0]["interface_id"] != step["start_state"]))
                    or (optional and step.get("target_region_id") is not None and target is None)):
                    raise CandidateProjectionError("invalid_reference", "added step is invalid or outside scope")
                proposed.append(("step", step["step_id"], "entity", {"after_step_id": anchor, "step": step}))
        elif change_type == "relationships_add":
            proposed=[]
            for relation in change["relationships"]:
                if (relation["relationship_id"] in baseline_relationship_ids or relation["from_interface_id"] not in effective_interface_scope or relation["to_interface_id"] not in effective_interface_scope):
                    raise CandidateProjectionError("invalid_reference", "added relationship is outside scope")
                proposed.append(("relationship", relation["relationship_id"], "entity", relation))
        elif change_type == "regions_add":
            parent = interfaces.get(change["interface_id"])
            if parent is None or parent["interface_id"] not in interface_scope:
                raise CandidateProjectionError("invalid_reference", "region additions are outside scope")
            screenshot = next(item for item in baseline_batch["screenshots"] if item["screenshot_id"] == parent["screenshot_id"])
            proposed = []
            for region in change["regions"]:
                x, y, width, height = region["bbox"]
                if x + width > screenshot["width"] or y + height > screenshot["height"]:
                    raise CandidateProjectionError("invalid_bbox", "added region bbox is outside screenshot")
                proposed.append(("region", region["region_id"], "entity", {"interface_id": parent["interface_id"], "region": region}))
        elif change_type == "geometry":
            if change["region_id"] not in baseline_region_ids:
                raise CandidateProjectionError("invalid_reference", "geometry cannot modify an added region")
            parent, _ = regions.get(change["region_id"], (None, None))
            if parent is None or parent["interface_id"] not in interface_scope:
                raise CandidateProjectionError("invalid_reference", "geometry change is outside scope")
            screenshot = next(
                item for item in baseline_batch["screenshots"]
                if item["screenshot_id"] == parent["screenshot_id"]
            )
            x, y, width, height = change["bbox"]
            if (
                not all(math.isfinite(number) for number in change["bbox"])
                or x < 0 or y < 0 or width <= 0 or height <= 0
                or x + width > screenshot["width"] or y + height > screenshot["height"]
            ):
                raise CandidateProjectionError("invalid_bbox", "candidate bbox is outside screenshot")
            proposed = [("region", change["region_id"], "bbox", change["bbox"])]
        elif change_type == "semantic":
            target_type, target_id = change["target_type"], change["target_id"]
            if target_type == "interface":
                valid, field = target_id in baseline_interface_ids and target_id in interface_scope, "meaning"
            elif target_type == "region":
                valid = target_id in baseline_region_ids and regions[target_id][0]["interface_id"] in interface_scope
                field = "meaning"
            elif target_type == "relationship":
                valid, field = target_id in relationships and target_id in relationship_scope, "kind"
            else:
                valid = target_id in steps and steps[target_id]["start_state"] in interface_scope
                field = "expected_result"
            if not valid:
                raise CandidateProjectionError("invalid_reference", "semantic target is outside scope")
            proposed = [(target_type, target_id, field, change["meaning"])]
            if target_type == "interface" and "recognition_text" in change:
                proposed.append((target_type, target_id, "recognition_text", change["recognition_text"]))
        elif change_type == "relationship":
            identifier = change["relationship_id"]
            if identifier not in baseline_relationship_ids or identifier not in relationship_scope:
                raise CandidateProjectionError("invalid_reference", "relationship change is outside scope")
            proposed = [("relationship", identifier, "kind", change["kind"])]
        elif change_type == "relationship_flow":
            identifier = change["relationship_id"]
            original = relationships.get(identifier)
            endpoints = {change["from_interface_id"], change["to_interface_id"]}
            if original is not None:
                endpoints.update((
                    original["from_interface_id"], original["to_interface_id"]
                ))
            if (
                original is None or identifier not in relationship_scope
                or not endpoints <= effective_interface_scope
            ):
                raise CandidateProjectionError(
                    "invalid_reference", "relationship flow is invalid or outside scope"
                )
            proposed = [
                ("relationship", identifier, field, change[field])
                for field in RELATIONSHIP_FIELDS
            ]
        elif change_type in {"step", "step_flow"}:
            identifier = change["step_id"]
            original = steps.get(identifier) if identifier in baseline_step_ids else None
            start = change.get("start_state") if change_type == "step_flow" else (
                original.get("start_state") if original else None
            )
            target = regions.get(change["target_region_id"]) if change.get("target_region_id") is not None else None
            valid = original is not None and original["start_state"] in interface_scope
            if change_type == "step_flow":
                valid = bool(
                    valid
                    and original["arrival_state"] in interface_scope
                    and change["start_state"] in effective_interface_scope
                    and change["arrival_state"] in effective_interface_scope
                )
            action = change["action_type"].strip().casefold()
            if change_type == "step_flow" and action in _OPTIONAL_TARGET_ACTIONS:
                valid = bool(valid and (change.get("target_region_id") is None or target is not None))
            else:
                valid = bool(valid and target is not None and target[0]["interface_id"] == start)
            if not valid:
                raise CandidateProjectionError("invalid_reference", "step change is invalid or outside scope")
            fields = STEP_FIELDS if change_type == "step_flow" else (
                "action_type", "target_region_id", "expected_result"
            )
            if action == "scroll_region" or "scroll_parameters" in original:
                fields = (*fields, "scroll_parameters")
            if action == "fill_field" or "text_parameters" in original:
                fields = (*fields, "text_parameters")
            proposed = [
                ("step", identifier, field, change.get(field))
                for field in fields
            ]
        elif change_type == "step_order":
            baseline_steps = baseline_batch["steps"]
            scoped = [
                step["step_id"] for step in baseline_steps
                if step["start_state"] in interface_scope
            ]
            requested = change["step_ids"]
            if len(scoped) < 2 or len(requested) != len(scoped) or set(requested) != set(scoped):
                raise CandidateProjectionError(
                    "invalid_reference", "step order must exactly permute all baseline scoped steps"
                )
            iterator = iter(requested)
            full_order = [
                next(iterator) if step["start_state"] in interface_scope else step["step_id"]
                for step in baseline_steps
            ]
            proposed = [("batch", baseline_batch["batch_id"], "step_order", full_order)]
        else:
            raise CandidateProjectionError("invalid_arguments", "candidate change type is unsupported")

        for target_type, target_id, field, value in proposed:
            key = (target_type, target_id, field)
            if key in seen:
                if reject_duplicate_fields:
                    raise CandidateProjectionError(
                        "duplicate_change", "candidate contains a duplicate target field"
                    )
                continue
            seen.add(key)
            writes.append(ProjectedField(
                change_index, target_type, target_id, field, deepcopy(value)
            ))
    return writes


def index_candidate_fields(batch: dict[str, Any]) -> dict[tuple[str, str, str], Any]:
    """索引所有可候选修改字段，包括完整步骤顺序。"""

    result: dict[tuple[str, str, str], Any] = {
        ("batch", batch["batch_id"], "step_order"): [
            step["step_id"] for step in batch["steps"]
        ]
    }
    for screenshot in batch["screenshots"]:
        result[("screenshot", screenshot["screenshot_id"], "entity")] = deepcopy(screenshot)
    for interface in batch["interfaces"]:
        result[("interface", interface["interface_id"], "entity")] = deepcopy(interface)
        result[("interface", interface["interface_id"], "meaning")] = interface["meaning"]
        result[("interface", interface["interface_id"], "recognition_text")] = interface.get("recognition_text")
        for region in interface["regions"]:
            result[("region", region["region_id"], "bbox")] = region["bbox"]
            result[("region", region["region_id"], "meaning")] = region["meaning"]
            result[("region", region["region_id"], "entity")] = {"interface_id": interface["interface_id"], "region": deepcopy(region)}
    for relationship in batch["relationships"]:
        result[("relationship", relationship["relationship_id"], "entity")] = deepcopy(relationship)
        for field in RELATIONSHIP_FIELDS:
            result[("relationship", relationship["relationship_id"], field)] = relationship[field]
    for step in batch["steps"]:
        result[("step", step["step_id"], "entity")] = deepcopy(step)
        for field in STEP_FIELDS:
            result[("step", step["step_id"], field)] = step[field]
        result[("step", step["step_id"], "scroll_parameters")] = deepcopy(
            step.get("scroll_parameters")
        )
        result[("step", step["step_id"], "text_parameters")] = deepcopy(step.get("text_parameters"))
    return result


def apply_candidate_diffs(
    batch: dict[str, Any], diffs: list[dict[str, Any]]
) -> dict[str, Any]:
    """严格校验三方差异的当前值并无副作用地应用。"""

    if not isinstance(diffs, list):
        raise CandidateProjectionError("invalid_diff", "candidate diffs must be a list")
    result = deepcopy(batch)
    baseline_interface_ids = {item["interface_id"] for item in batch["interfaces"]}
    baseline_region_ids = {region["region_id"] for view in batch["interfaces"] for region in view["regions"]}
    from .contracts import AgentLinkError
    from .interface_additions import interface_entities_from_diffs
    try:
        screenshots, added_interfaces = interface_entities_from_diffs(batch, diffs)
    except AgentLinkError as error:
        raise CandidateProjectionError("invalid_diff", error.message) from error
    result["screenshots"].extend(screenshots)
    result["interfaces"].extend(added_interfaces)
    interfaces = {item["interface_id"]: item for item in result["interfaces"]}
    regions = {
        region["region_id"]: region
        for interface in result["interfaces"] for region in interface["regions"]
    }
    relationships = {item["relationship_id"]: item for item in result["relationships"]}
    steps = {item["step_id"]: item for item in result["steps"]}
    baseline_step_ids = set(steps)
    baseline_relationship_ids = set(relationships)
    collections = {
        "interface": interfaces, "region": regions,
        "relationship": relationships, "step": steps,
    }
    allowed = {
        "interface": {"meaning", "recognition_text"}, "region": {"bbox", "meaning"},
        "relationship": set(RELATIONSHIP_FIELDS), "step": set(STEP_FIELDS),
    }
    # 创建仅接受明确的 entity 差异，先于其它字段应用。
    entity_diffs = []
    for diff in diffs:
        if isinstance(diff, dict) and diff.get("target_type") == "region" and diff.get("field") == "entity":
            if set(diff) != {"target_type", "target_id", "field", "baseline", "current", "proposed"} or not isinstance(diff.get("target_id"), str) or not diff["target_id"]:
                raise CandidateProjectionError("invalid_diff", "candidate entity diff shape is invalid")
            if diff["baseline"] is not None or diff["current"] is not None or diff["target_id"] in regions:
                raise CandidateProjectionError("invalid_diff", "candidate entity creation is not absent")
            proposed = diff["proposed"]
            parent_id = proposed.get("interface_id") if isinstance(proposed, dict) else None
            if (not isinstance(proposed, dict) or set(proposed) != {"interface_id", "region"}
                    or not isinstance(parent_id, str) or not parent_id or parent_id not in baseline_interface_ids):
                raise CandidateProjectionError("invalid_diff", "candidate entity creation target is invalid")
            try:
                from pydantic import ValidationError
                from .contracts import RegionInput
                region = RegionInput.model_validate(proposed["region"]).model_dump(mode="json")
            except (ValidationError, TypeError, ValueError) as error:
                raise CandidateProjectionError("invalid_diff", "candidate entity region is invalid") from error
            if region["region_id"] != diff["target_id"]:
                raise CandidateProjectionError("invalid_diff", "candidate entity id is inconsistent")
            parent = interfaces[parent_id]
            screenshot = next(item for item in result["screenshots"] if item["screenshot_id"] == parent["screenshot_id"])
            x, y, width, height = region["bbox"]
            if x + width > screenshot["width"] or y + height > screenshot["height"]:
                raise CandidateProjectionError("invalid_diff", "candidate entity region is outside limits")
            entity_diffs.append((diff, parent, region))
    if len({diff["target_id"] for diff, _, _ in entity_diffs}) != len(entity_diffs):
        raise CandidateProjectionError("invalid_diff", "candidate entity ids are duplicate")
    additions_by_parent: dict[str, int] = {}
    for _, parent, _ in entity_diffs:
        identifier = parent["interface_id"]
        additions_by_parent[identifier] = additions_by_parent.get(identifier, 0) + 1
    if any(len(interfaces[identifier]["regions"]) + count > 128 for identifier, count in additions_by_parent.items()):
        raise CandidateProjectionError("invalid_diff", "candidate entity region exceeds interface limit")
    for _, parent, region in entity_diffs:
        parent["regions"].append(deepcopy(region)); regions[region["region_id"]] = parent["regions"][-1]
    step_additions: list[tuple[str | None, dict[str, Any]]] = []
    relationship_additions: list[dict[str, Any]] = []
    for diff in diffs:
        if not isinstance(diff, dict) or diff.get("field") != "entity" or diff.get("target_type") not in {"step", "relationship"}:
            continue
        if set(diff) != {"target_type", "target_id", "field", "baseline", "current", "proposed"} or diff.get("baseline") is not None or diff.get("current") is not None:
            raise CandidateProjectionError("invalid_diff", "candidate entity creation is not absent")
        if diff["target_type"] == "step":
            proposed = diff.get("proposed")
            if (not isinstance(diff.get("target_id"), str) or not diff["target_id"]
                    or not isinstance(proposed, dict) or set(proposed) != {"after_step_id", "step"} or diff["target_id"] in steps):
                raise CandidateProjectionError("invalid_diff", "candidate step entity is invalid")
            try:
                from .contracts import StepInput
                step = StepInput.model_validate(proposed["step"]).model_dump(mode="json")
            except (TypeError, ValueError) as error:
                raise CandidateProjectionError("invalid_diff", "candidate step entity is invalid") from error
            anchor = proposed["after_step_id"]
            target = regions.get(step.get("target_region_id")) if step.get("target_region_id") is not None else None
            optional = step["action_type"].strip().casefold() in _OPTIONAL_TARGET_ACTIONS
            if (step["step_id"] != diff["target_id"] or not (anchor is None or isinstance(anchor, str))
                    or (anchor is not None and anchor not in baseline_step_ids) or step["start_state"] not in interfaces or step["arrival_state"] not in interfaces
                    or (not optional and (target is None or target["region_id"] not in regions or next(item["interface_id"] for item in result["interfaces"] if any(r["region_id"] == step["target_region_id"] for r in item["regions"])) != step["start_state"]))
                    or (optional and step.get("target_region_id") is not None and target is None)):
                raise CandidateProjectionError("invalid_diff", "candidate step entity is invalid")
            step_additions.append((anchor, step)); steps[step["step_id"]] = step
        else:
            try:
                from .contracts import RelationshipInput
                relation = RelationshipInput.model_validate(diff.get("proposed")).model_dump(mode="json")
            except (TypeError, ValueError) as error:
                raise CandidateProjectionError("invalid_diff", "candidate relationship entity is invalid") from error
            if relation["relationship_id"] != diff["target_id"] or relation["relationship_id"] in relationships or relation["from_interface_id"] not in interfaces or relation["to_interface_id"] not in interfaces:
                raise CandidateProjectionError("invalid_diff", "candidate relationship entity is invalid")
            relationship_additions.append(relation); relationships[relation["relationship_id"]] = relation
    if len(result["steps"]) + len(step_additions) > 256 or len(result["relationships"]) + len(relationship_additions) > 256:
        raise CandidateProjectionError("invalid_diff", "candidate entity limit exceeded")
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    for anchor, step in step_additions: grouped.setdefault(anchor, []).append(step)
    rebuilt = list(grouped.get(None, []))
    for old in result["steps"]:
        rebuilt.append(old); rebuilt.extend(grouped.get(old["step_id"], []))
    result["steps"] = rebuilt
    result["relationships"].extend(deepcopy(relationship_additions))
    seen: set[tuple[str, str, str]] = set()
    for diff in diffs:
        if not isinstance(diff, dict) or set(diff) != {
            "target_type", "target_id", "field", "baseline", "current", "proposed"
        }:
            raise CandidateProjectionError("invalid_diff", "candidate diff shape is invalid")
        target_type, target_id, field = (
            diff["target_type"], diff["target_id"], diff["field"]
        )
        if not all(isinstance(item, str) and item for item in (target_type, target_id, field)):
            raise CandidateProjectionError("invalid_diff", "candidate diff identity is invalid")
        key = (target_type, target_id, field)
        if key in seen:
            raise CandidateProjectionError("invalid_diff", "candidate diffs contain duplicate fields")
        seen.add(key)
        if not _exact_equal(diff["baseline"], diff["current"]):
            raise CandidateProjectionError("stale_diff", "candidate diff baseline and current differ")
        if field == "entity" and target_type in {"screenshot", "interface", "region", "step", "relationship"}:
            continue
        if ((target_type == "step" and target_id not in baseline_step_ids)
                or (target_type == "relationship" and target_id not in baseline_relationship_ids)
                or (target_type == "interface" and target_id not in baseline_interface_ids)
                or (target_type == "region" and target_id not in baseline_region_ids)):
            raise CandidateProjectionError("invalid_diff", "ordinary fields cannot modify a newly added entity")
        if target_type == "batch":
            if target_id != result["batch_id"] or field != "step_order":
                raise CandidateProjectionError("invalid_diff", "candidate batch diff is unknown")
            current = [step["step_id"] for step in result["steps"]]
            proposed = diff["proposed"]
            if not _exact_equal(current, diff["current"]):
                raise CandidateProjectionError("stale_diff", "candidate step order current value differs")
            if (
                not isinstance(proposed, list) or len(proposed) != len(current)
                or any(not isinstance(item, str) or not item for item in proposed)
                or len(set(proposed)) != len(proposed) or set(proposed) != set(current)
            ):
                raise CandidateProjectionError("invalid_diff", "candidate full step order is invalid")
            by_id = {step["step_id"]: step for step in result["steps"]}
            result["steps"] = [by_id[identifier] for identifier in proposed]
            continue
        target = collections.get(target_type, {}).get(target_id)
        if target is None or (
            field not in allowed.get(target_type, set())
            and not (target_type == "step" and field in {"scroll_parameters", "text_parameters"})
        ):
            raise CandidateProjectionError("invalid_diff", "candidate diff target or field is unknown")
        current_value = target.get(field)
        if not _exact_equal(current_value, diff["current"]):
            raise CandidateProjectionError("stale_diff", "candidate diff current value differs")
        if ((target_type == "step" and field in {"scroll_parameters", "text_parameters"})
                or (target_type == "interface" and field == "recognition_text")) and diff["proposed"] is None:
            target.pop(field, None)
        else:
            target[field] = deepcopy(diff["proposed"])
    return result


def _exact_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _exact_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _exact_equal(left[key], right[key]) for key in left
        )
    return left == right
