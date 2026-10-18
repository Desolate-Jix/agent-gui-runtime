"""把可信本地观察投影为未审核草稿，复用唯一收件箱与流程图。"""

import base64
from copy import deepcopy

from app.agent.fresh_learning_archive import FreshLearningObservationArchive
from app.agent.fresh_learning_observation import FreshLearningObservationPacket
from app.desktop_review.observation_timing import timed_call, timed_observation
from .contracts import AgentLinkError, canonical_hash, validate_batch
from .fresh_source_contract import validate_fresh_source_metadata
from .learning_segments import MAX_SEGMENT_OBSERVATIONS


class FreshGraphSourceOwner:
    def __init__(self, segments, facade):
        from .learning_segments import LearningSegmentOwner
        from app.desktop_review.workspace import NativeReviewFacade

        if not isinstance(segments, LearningSegmentOwner) or not isinstance(facade, NativeReviewFacade):
            raise TypeError("fresh graph source requires real segment and graph owners")
        if segments.recorder.project_root != facade._artifact_root or facade._service._store is not segments.store:
            raise ValueError("fresh graph source must share the native root and inbox")
        self.segments, self.facade = segments, facade
        self.archive = FreshLearningObservationArchive(segments.recorder.project_root)

    @timed_observation("stage")
    def stage(self, *, connection_id, task_id, segment_id, idempotency_key, title, meaning, packet,
              observation_request_sha256=None):
        if not isinstance(packet, FreshLearningObservationPacket):
            raise TypeError("packet must be a local FreshLearningObservationPacket")
        for value, limit in ((idempotency_key, 128), (title, 512), (meaning, 4000)):
            if not isinstance(value, str) or not value or len(value) > limit:
                raise AgentLinkError("invalid_arguments", "fresh graph proposal text is invalid")
        identity = {"connection_id": connection_id, "task_id": task_id, "segment_id": segment_id}
        current = timed_call("stage.load_segment", self.segments.get, **identity)
        if current["status"] != "active":
            raise AgentLinkError("learning_busy", "learning segment is not active")
        request_id = canonical_hash({**identity, "key": idempotency_key})
        batch_id = "fresh-batch-" + request_id
        if (len(current.get("observations", [])) >= MAX_SEGMENT_OBSERVATIONS
                and all(item["batch_id"] != batch_id for item in current["observations"])):
            raise AgentLinkError("learning_capacity_exceeded", "finish this segment and start another before observing more screens")
        reference = timed_call("stage.archive", self.archive.record, packet, **identity)
        source = validate_fresh_source_metadata({**identity, "reference": reference,
            **({"observation_request_sha256": observation_request_sha256} if observation_request_sha256 is not None else {})})
        batch = timed_call("stage.validate_batch", validate_batch, {
            "contract_version": "agent_link_v1", "idempotency_key": "fresh-" + request_id,
            "batch_id": batch_id, "title": title, "learning_outcome": "partial",
            "outcome_reason": "Observation only; no action or transition has been learned.",
            "screenshots": [{"screenshot_id": "capture", "png_base64": base64.b64encode(packet.png_bytes).decode("ascii")}],
            "interfaces": [{"interface_id": "observed-screen", "screenshot_id": "capture", "meaning": meaning, "regions": []}],
            "relationships": [], "steps": [], "issues": [],
        }, existing_png_sha256=frozenset({reference["screenshot_sha256"]}))
        stored = {**batch, "connection_id": connection_id, "task_id": task_id,
                  "status": "pending_review_proposal", "source": "untrusted_external", "fresh_learning_source": source}

        def commit(state):
            segment = self.segments._stored_segment(state, connection_id, task_id, segment_id)
            if segment["status"] != "active":
                raise AgentLinkError("learning_busy", "learning segment is not active")
            previous = state["batches"].get(batch_id)
            if previous is not None:
                if previous != stored:
                    raise AgentLinkError("idempotency_conflict", "fresh observation request has different content")
                return
            if len(segment.get("observations", [])) >= MAX_SEGMENT_OBSERVATIONS:
                raise AgentLinkError("learning_capacity_exceeded", "finish this segment and start another before observing more screens")
            state["batches"][batch_id] = deepcopy(stored)
            state["feedback"][batch_id] = {"revision": 0, "history": [], "issues": {}}
            segment.setdefault("observations", []).append({"batch_id": batch_id, "source": deepcopy(source)})
            segment["revision"] += 1

        timed_call("stage.store_commit", self.segments.store.mutate, commit)
        # 首批锚定同段图身份；追加失败后重试只复用已落盘来源，不重新采集。
        committed = timed_call("stage.reload_segment", self.segments.get, **identity)
        observations = committed["observations"]
        review_batch_id = observations[0]["batch_id"]
        graph = timed_call("stage.ensure_graph", self.facade.ensure_learning_graph_revision, task_id, review_batch_id)
        known_batches = {review_batch_id} | {
            item["batch_id"] for item in graph["source_refs"].get("additional_sources", [])
        }
        for observation in observations[1:]:
            if observation["batch_id"] in known_batches:
                continue
            graph = timed_call("stage.append_source", self.facade.append_fresh_graph_source,
                graph["logical_workflow_id"], task_id, observation["batch_id"],
            )
            known_batches.add(observation["batch_id"])
        timed_call("stage.verify_segment", self.segments.get, **identity)
        if committed["children"]:
            synced = self.sync_actions(**identity)
            graph = timed_call("stage.reload_graph", self.facade.load_graph_revision, synced["logical_workflow_id"])
        return {"contract_version": "fresh_learning_graph_v1", "batch_id": batch_id,
                "review_batch_id": review_batch_id,
                "logical_workflow_id": graph["logical_workflow_id"], "graph_revision": graph["revision"],
                "source": source, "artifact_is_authorization": False,
                "execute_binding_enabled": False, "action_executed": False}

    @timed_observation("sync_actions")
    def sync_actions(self, *, connection_id, task_id, segment_id):
        from app.desktop_review.action_graph_source import ActionGraphSourceReader
        from app.desktop_review.workspace import DesktopReviewError

        identity = dict(connection_id=connection_id, task_id=task_id, segment_id=segment_id)
        segment = timed_call("sync_actions.load_segment", self.segments.get, **identity)
        common = {"contract_version": "learning_graph_sync_v1", **identity,
                  "artifact_is_authorization": False, "execute_binding_enabled": False,
                  "action_executed": False}
        try:
            collected = timed_call("sync_actions.collect", ActionGraphSourceReader(self.facade).collect, **identity)
            if not segment.get("observations", []):
                if not collected["sources"]:
                    if collected["pending_events"]:
                        return {**common, "status": "pending_sources", "projected_event_count": 0,
                                "pending_events": collected["pending_events"]}
                    return {**common, "status": "missing_observation_anchor", "projected_event_count": 0,
                            "pending_events": [{"reason": "observe_learning_screen_required"}]}
                graph = timed_call("sync_actions.create_graph", self.facade.create_action_only_graph, collected["sources"][0])
                # 图锚点一经建立保持不变；每次重读全部事件，允许更早事件稍后补齐。
                for source in collected["sources"]:
                    graph = timed_call("sync_actions.append_action", self.facade.append_learning_action_source, graph["logical_workflow_id"], source)
                timed_call("sync_actions.verify_segment", self.segments.get, **identity)
                return {**common, "status": "pending_sources" if collected["pending_events"] else "synchronized",
                        "logical_workflow_id": graph["logical_workflow_id"],
                        "graph_revision": graph["revision"], "graph_sha256": graph["content_sha256"],
                        "projected_event_count": len(graph["source_refs"].get("action_sources", [])),
                        "pending_events": collected["pending_events"]}
            review_batch_id = segment["observations"][0]["batch_id"]
            graph = timed_call("sync_actions.ensure_graph", self.facade.ensure_learning_graph_revision, task_id, review_batch_id)
            # 先补齐已提交观察，再投影动作；失败后可重试，不重复执行外部动作。
            for observation in segment["observations"][1:]:
                graph = timed_call("sync_actions.append_source", self.facade.append_fresh_graph_source,
                    graph["logical_workflow_id"], task_id, observation["batch_id"])
            for source in collected["sources"]:
                graph = timed_call("sync_actions.append_action", self.facade.append_learning_action_source, graph["logical_workflow_id"], source)
            timed_call("sync_actions.verify_segment", self.segments.get, **identity)
            return {**common, "status": "pending_sources" if collected["pending_events"] else "synchronized",
                    "review_batch_id": review_batch_id, "logical_workflow_id": graph["logical_workflow_id"],
                    "graph_revision": graph["revision"], "graph_sha256": graph["content_sha256"],
                    "projected_event_count": len(graph["source_refs"].get("action_sources", [])),
                    "pending_events": collected["pending_events"]}
        except (DesktopReviewError, OSError) as error:
            raise AgentLinkError("learning_graph_sync_failed", str(error)) from error
