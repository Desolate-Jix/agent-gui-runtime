"""从既有记录器核验动作来源，再投影为待人工审核的节点与边。"""

from copy import deepcopy
import math

from app.agent.action_learning_capture_archive import ActionLearningCaptureArchiveError
from app.agent.action_learning_recorder import ActionLearningRecorderError
from app.agent_link.contracts import AgentLinkError, canonical_hash
from .workspace import DesktopReviewError


_SCOPE = ("connection_id", "task_id", "segment_id")
_FLAGS = {"artifact_is_authorization": False, "execute_binding_enabled": False,
          "action_executed": False}


def action_sequence_metadata(sources):
    """按权威收集顺序记录动作序列；没有状态连续证据时明确标记缺口。"""
    if not isinstance(sources, list):
        raise DesktopReviewError("动作序列来源无效")
    result = []
    previous = None
    seen = set()
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict) or not isinstance(source.get("event_id"), str):
            raise DesktopReviewError("动作序列事件无效")
        event_id = source["event_id"]
        if event_id in seen:
            raise DesktopReviewError("动作序列事件重复")
        seen.add(event_id)
        result.append({
            "sequence_index": index,
            "event_id": event_id,
            "previous_event_id": previous,
            "continuity_status": "recorded_sequence" if previous is None else "unknown_gap",
        })
        previous = event_id
    return result


def _scroll_transition_blocker(*, event_id, before, terminal, joined):
    """只把权威回执中已证明局部变化的滚动投影为流程跳转。"""
    evidence = terminal.get("evidence") if isinstance(terminal, dict) else None
    proof = evidence.get("scroll_verification") if isinstance(evidence, dict) else None
    spatial = proof.get("spatial") if isinstance(proof, dict) else None
    after = proof.get("after") if isinstance(proof, dict) else None
    geometry = before.get("geometry") if isinstance(before, dict) else None
    bbox = geometry.get("bbox") if isinstance(geometry, dict) else None
    expected_bbox = ({"x": bbox.get("x"), "y": bbox.get("y"),
                      "width": bbox.get("w"), "height": bbox.get("h")}
                     if isinstance(bbox, dict) else None)
    status = spatial.get("status") if isinstance(spatial, dict) else "unknown"
    verified = (
        terminal.get("outcome") == "ACTION_RECORDED"
        and isinstance(joined, dict) and joined.get("after_observation_present") is True
        and isinstance(joined.get("after"), dict)
        and isinstance(proof, dict) and isinstance(after, dict)
        and proof.get("scroll_parameters") == before.get("scroll_parameters")
        and proof.get("target_bbox") == expected_bbox
        and isinstance(spatial, dict)
        and spatial.get("available") is True
        and status == "target_visual_change"
        and spatial.get("target_changed") is True
        and spatial.get("non_target_changed") is False
        and spatial.get("non_target_stable") is True
        and spatial.get("wrong_scope_detected") is False
    )
    if verified:
        return None
    return {
        "kind": "scroll_spatial_verification_failed",
        "event_id": event_id,
        "spatial_status": status if isinstance(status, str) and status else "unknown",
        "message": "滚动未证明只改变目标容器；保留前后观察，但不生成可复用跳转。",
        "safe_stop_required": True,
    }


class ActionGraphSourceReader:
    def __init__(self, facade):
        from app.agent_link.learning_segments import LearningSegmentOwner

        owner = facade._service._learning_owner
        if (not isinstance(owner, LearningSegmentOwner)
                or owner.store is not facade._service._store
                or owner.recorder.project_root != facade._artifact_root):
            raise DesktopReviewError("动作图必须绑定同根学习段、记录器与收件箱")
        self.owner = owner

    def _segment(self, scope, *, historical=False):
        method = self.owner._stored_cleanup_segment if historical else self.owner._stored_segment
        try:
            return self.owner.store.read(lambda state: deepcopy(method(state, **scope)))
        except AgentLinkError as error:
            raise DesktopReviewError("动作来源所属学习段不可用") from error

    def _evidence(self, child):
        try:
            # 段结束或追加事件会提升会话修订；旧事件按最新权威视图重新核验。
            session = self.owner.recorder.get_learning_session(
                learning_session_id=child["learning_session_id"])
            return self.owner.capture_archive.read_session_evidence(
                learning_session_id=child["learning_session_id"],
                runtime_session_id=child["runtime_session_id"],
                expected_revision=session["revision"],
            ).evidence()
        except (ActionLearningRecorderError, ActionLearningCaptureArchiveError, OSError) as error:
            raise DesktopReviewError("动作事件及原图来源不可用，请修复记录来源后重试") from error

    @staticmethod
    def _source(scope, child, event, joined):
        required = [joined["before"]]
        if joined["after_observation_present"]:
            required.append(joined["after"])
        if any(not isinstance(item, dict) or item.get("status") != "available" for item in required):
            return None
        shots = {}
        for capture in required:
            sha = capture["screenshot_sha256"]
            viewport = capture["metadata"]["viewport_size"]
            shot = {"screenshot_id": "action-png-" + sha,
                    "path": "runtime_state/action-learning-v1/captures/blobs/" + sha + ".png",
                    "sha256": sha, "width": viewport["width"], "height": viewport["height"]}
            if shot["path"] in shots and shots[shot["path"]] != shot:
                raise DesktopReviewError("相同动作原图路径具有冲突的像素引用")
            shots[shot["path"]] = shot
        value = {"contract_version": "learning_action_graph_source_v1", **scope,
                 **{key: child[key] for key in ("child_id", "learning_session_id", "runtime_session_id")},
                 "event_id": event["event_id"], "event": deepcopy(event),
                 "event_source": deepcopy(joined), "screenshots": list(shots.values())}
        return {**value, "source_sha256": canonical_hash(value)}

    def collect(self, *, connection_id, task_id, segment_id, historical=False):
        if type(historical) is not bool:
            raise DesktopReviewError("动作来源历史读取标志无效")
        scope = dict(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        initial = self._segment(scope, historical=historical)
        sources, pending = [], []
        for child in initial["children"]:
            if child["phase"] == "cancelled":
                continue
            if child["phase"] != "bound":
                pending.append({"child_id": child["child_id"], "reason": "runtime_bind_pending"})
                continue
            evidence = self._evidence(child)
            for joined in evidence["event_sources"]:
                event = evidence["events"][joined["event_id"]]
                source = self._source(scope, child, event, joined)
                if source is None:
                    pending.append({"child_id": child["child_id"], "event_id": event["event_id"],
                                    "reason": "required_original_image_unavailable"})
                else:
                    sources.append(source)
            if evidence["recording_gaps"]:
                pending.append({"child_id": child["child_id"], "reason": "recording_gaps"})
        if self._segment(scope, historical=historical) != initial:
            raise DesktopReviewError("stale_revision: 动作来源读取期间学习段发生变化，请重试")
        return {"sources": sources, "pending_events": pending}

    def validate(self, source, scope_anchor):
        if (not isinstance(source, dict) or not isinstance(scope_anchor, dict)
                or any(not isinstance(source.get(key), str) or source[key] != scope_anchor.get(key)
                       for key in _SCOPE)):
            raise DesktopReviewError("动作来源不属于图的同一连接、任务和学习段")
        scope = {key: source[key] for key in _SCOPE}
        initial = self._segment(scope, historical=True)
        children = [child for child in initial["children"]
                    if child["child_id"] == source.get("child_id")]
        if (len(children) != 1 or children[0]["phase"] != "bound"
                or any(children[0][key] != source.get(key)
                       for key in ("learning_session_id", "runtime_session_id"))):
            raise DesktopReviewError("动作来源不属于已绑定的真实运行时")
        child = children[0]
        evidence = self._evidence(child)
        joined = [item for item in evidence["event_sources"] if item["event_id"] == source.get("event_id")]
        event = evidence["events"].get(source.get("event_id"))
        if len(joined) != 1 or event is None:
            raise DesktopReviewError("动作来源未找到权威事件")
        actual = self._source(scope, child, event, joined[0])
        if actual is None or actual != source:
            raise DesktopReviewError("action_source_rewritten: 动作来源或原图与权威记录不一致")
        if self._segment(scope, historical=True) != initial:
            raise DesktopReviewError("stale_revision: 动作来源核验期间学习段发生变化")


def project_action_source(source):
    event, joined = source["event"], source["event_source"]
    before, terminal = event["before"], event["terminal"]
    action = before["action"]
    semantic = action["semantic_action"]
    nodes, edges, invalid = [], [], []
    for side in ("before", "after"):
        capture = joined[side]
        if capture is None:
            continue
        if capture.get("status") != "available":
            raise DesktopReviewError("动作投影不得使用缺失的原图")
        sha = capture["screenshot_sha256"]
        shot = next(item for item in source["screenshots"] if item["sha256"] == sha)
        node_id = "action-node-" + canonical_hash({"event_id": event["event_id"],
                                                  "side": side, "capture_id": capture["capture_id"]})
        name = ("操作前 · " + semantic) if side == "before" else ("操作后 · " + terminal["outcome"])
        regions = []
        if side == "before":
            raw = before["geometry"]["bbox"]
            bbox = [raw[key] for key in ("x", "y", "w", "h")]
            if (any(type(value) not in (int, float) or not math.isfinite(value) for value in bbox)
                    or bbox[0] < 0 or bbox[1] < 0 or bbox[2] <= 0 or bbox[3] <= 0
                    or bbox[0] + bbox[2] > shot["width"] or bbox[1] + bbox[3] > shot["height"]):
                raise DesktopReviewError("动作区域超出其原始截图范围")
            target = before.get("target_observation")
            label = (target.get("text") or target.get("label")) if isinstance(target, dict) else ""
            regions = [{"region_id": "action-region-" + canonical_hash(event["event_id"]),
                        "name": label or semantic, "bbox": bbox, "review_status": "needs_human_review",
                        **({"target_observation": deepcopy(target)} if target is not None else {}),
                        "reviewed_by_human": False, "display_only": True, **_FLAGS}]
        nodes.append({
            "node_id": node_id, "external_interface_id": node_id, "display_name": name,
            "surface_type": "recorded_action_observation", "state_signature": node_id,
            "source_paths": [shot["path"]], "observation_count": 1, "evidence_status": "ready",
            "evidence": {"source_screenshot_path": shot["path"], "source_screenshot_sha256": sha,
                         "source_path": shot["path"], "source_sha256": source["source_sha256"],
                         "external_source_kind": "recorded_action"},
            "agent_description": name, "content_descriptors": [],
            "page_details": {"screen": {"summary": name, "source_image_path": shot["path"],
                                         "source_image_sha256": sha}},
            "ui_hierarchy": {}, "hierarchy_ownership_review": {}, "selection_replay_provenance": {},
            "states": [], "regions": regions, "controls": [], "action_candidates": [],
            "blockers": [], "verification_rules": [], "review_status": "needs_human_review",
            "reviewed_by_human": False, "execution_verification_status": "not_verified",
            "manual_revision": {}, "display_only": True, **_FLAGS,
        })
    scroll_blocker = (_scroll_transition_blocker(
        event_id=event["event_id"], before=before, terminal=terminal, joined=joined,
    ) if (semantic == "scroll_region"
          and before.get("contract_version") == "action_learning_before_v2"
          and len(nodes) == 2) else None)
    if len(nodes) == 2 and scroll_blocker is None:
        edge_id = "action-edge-" + canonical_hash(event["event_id"])
        fresh_scroll = {}
        if semantic == "scroll_region" and "scroll_parameters" in before:
            fresh_scroll = {"scroll_parameters": {**deepcopy(before["scroll_parameters"]),
                "target_container_id": nodes[0]["regions"][0]["region_id"]}}
        edges.append({
            "edge_id": edge_id, "operation_id": edge_id, "external_step_id": event["event_id"],
            "source_node_id": nodes[0]["node_id"], "target_node_id": nodes[1]["node_id"],
            "display_name": semantic + " · " + terminal["outcome"], "action_type": semantic,
            "semantic_action": semantic, "external_declared_action_type": semantic,
            "target_region_id": nodes[0]["regions"][0]["region_id"], "target_control_id": "",
            **{key: deepcopy(action[key]) for key in ("scroll_parameters", "text_parameters_ref") if key in action},
            **fresh_scroll,
            "recorded_event": {"event_id": event["event_id"], "source_sha256": source["source_sha256"],
                               **deepcopy(terminal)},
            "external_stop_boundary": True, "risk_level": "medium", "requires_user_confirmation": True,
            "preconditions": [], "success_conditions": [], "failure_conditions": [],
            "gate_policy": "fresh_grounding_and_gate_required", "verification_evidence": {},
            "review_status": "needs_human_review", "reviewed_by_human": False,
            "display_only": True, **_FLAGS,
        })
    elif len(nodes) == 2:
        nodes[0]["blockers"].append(scroll_blocker)
        invalid.append(deepcopy(scroll_blocker))
    else:
        unresolved = {"kind": "missing_after_observation", "event_id": event["event_id"],
                      "message": "没有操作后观察，不生成目标节点或成功跳转。", "safe_stop_required": True}
        nodes[0]["blockers"].append(unresolved)
        invalid.append(deepcopy(unresolved))
    return {"nodes": nodes, "edges": edges, "invalid_sources": invalid}
