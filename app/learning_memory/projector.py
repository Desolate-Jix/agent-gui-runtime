"""把执行事实与 Agent 判读分开；只生成投影视图，不创建第二套图存储。"""
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .receipt_adapter import content_hash


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ObservationIdentity(_Strict):
    interface_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    state_key: str = Field(default="default", pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    frame_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    meaning: str = Field(min_length=1, max_length=4000)


class InputBinding(_Strict):
    kind: Literal["variable", "constant"]
    name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def shape(self):
        if self.kind == "variable" and (self.name is None or self.value is not None):
            raise ValueError("variable requires name, not an example value")
        if self.kind == "constant" and (self.value is None or self.name is not None):
            raise ValueError("constant requires an explicit value, not name")
        return self


class EventReview(_Strict):
    event_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_review_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["success", "failure", "uncertain"]
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    before: ObservationIdentity | None = None
    after: ObservationIdentity | None = None
    input_binding: InputBinding | None = None


def validate_review(value):
    return EventReview.model_validate(value).model_dump()


def validate_event_review(event, review):
    """摘要绑定不等于效果验证；success 仍明确归于 Agent。"""
    review = validate_review(review)
    if review["event_id"] != event["request_id"] or review["event_sha256"] != content_hash(event):
        raise ValueError("review refers to a different event or event revision")
    for view in ("before", "after"):
        identity = review[view]
        if identity is None:
            continue
        frame = event.get(view) or {}
        if frame.get("status") != "referenced" or frame.get("sha256") != identity["frame_sha256"]:
            raise ValueError(f"{view} identity must name this event's exact frame")
        if not identity["meaning"].strip():
            raise ValueError("interface meaning must not be blank")
    if not review["reason"].strip() or not review["reviewer"].strip():
        raise ValueError("reviewer and reason must not be blank")
    binding = review["input_binding"]
    if binding is not None:
        recorded = event.get("input_text")
        if not recorded:
            raise ValueError("input binding requires recorded text input")
        if binding["kind"] == "constant":
            import hashlib
            if hashlib.sha256(binding["value"].encode("utf-8")).hexdigest() != recorded["sha256"]:
                raise ValueError("constant does not match the actual recorded input")
    return review


def project_segment(manifest, events, reviews):
    """同界面同状态按显式身份合并；只读采集永远不能证明跳转。"""
    nodes, edges, unresolved, observations, failures = {}, [], [], [], []
    workflow = manifest["start_spec"]["scope"] == "workflow"
    for event in events:
        event_id = event["request_id"]
        record = reviews.get(event_id)
        if record is None:
            unresolved.append({"event_id": event_id, "reason": "awaiting_agent_review"})
            continue
        review = validate_event_review(event, record["review"])
        ids = {}
        for view in ("before", "after"):
            identity = review[view]
            if identity is None:
                continue
            key = (identity["interface_key"], identity["state_key"])
            node_id = "state-" + content_hash(list(key))[:32]
            ids[view] = node_id
            node = nodes.setdefault(key, {"node_id": node_id,
                "interface_key": key[0], "state_key": key[1], "meanings": [], "observations": []})
            if identity["meaning"] not in node["meanings"]:
                node["meanings"].append(identity["meaning"])
            reference = {"event_id": event_id, "view": view,
                         "frame_sha256": identity["frame_sha256"],
                         "review_sha256": record["review_sha256"]}
            node["observations"].append(reference)
            observations.append({**reference, "node_id": node_id})
        if review["verdict"] != "success":
            failures.append({"event_id": event_id, "verdict": review["verdict"], "reason": review["reason"]})
            continue
        if not workflow or event["kind"] not in {"step", "input_sequence"}:
            continue
        if event.get("action_executed") is not True:
            unresolved.append({"event_id": event_id, "reason": "input_dispatch_not_proven"})
            continue
        if event["kind"] == "input_sequence" and (event.get("interrupted_at") is not None
                                                    or event.get("sequence_status") != "completed"):
            unresolved.append({"event_id": event_id, "reason": "sequence_not_completed"})
            continue
        if set(ids) != {"before", "after"}:
            unresolved.append({"event_id": event_id, "reason": "transition_identity_incomplete"})
            continue
        # 关系来自同一个动作的两端，不从前后排列的截图补边。
        edges.append({"edge_id": "transition-" + content_hash([manifest["learning_id"], event_id])[:32],
            "source_node_id": ids["before"], "target_node_id": ids["after"],
            "kind": "same_state_action" if ids["before"] == ids["after"] else "observed_transition",
            "operation": event.get("operation") or event["kind"],
            "input_binding": deepcopy(review["input_binding"]),
            "input_binding_required": bool(event.get("input_text")) and review["input_binding"] is None,
            "evidence": {"event_id": event_id, "event_sha256": content_hash(event),
                         "review_sha256": record["review_sha256"],
                         "before_sha256": review["before"]["frame_sha256"],
                         "after_sha256": review["after"]["frame_sha256"]},
            "judged_by": review["reviewer"], "verdict": "success",
            "task_effect_verified_by_framework": None})
    return {"contract_version": "instant_learning_projection_v1", "learning_id": manifest["learning_id"],
        "scope": manifest["start_spec"]["scope"], "project_id": manifest["start_spec"].get("project_id"),
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]), "edges": edges,
        "observations": observations, "unresolved": unresolved, "non_successful_events": failures,
        "graph_persisted": False, "projection_only": True, "execute_binding_enabled": False,
        "automatic_retry_allowed": False}
