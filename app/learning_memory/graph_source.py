"""回执图来源适配；图本体仍使用原生 GraphRevisionService。"""
from copy import deepcopy
import hashlib
import re

from app.core.json_snapshot import read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.workflow_membership import reference_node
from app.desktop_review.workspace import DesktopReviewError, _write_immutable
from .projector import project_segment, validate_event_review
from .receipt_adapter import content_hash


KIND = "execution_memory"


def bundle_segments(bundle):
    if bundle["contract_version"] == "execution_memory_graph_source_v1":
        return [{key: bundle[key] for key in ("manifest", "events", "reviews")}]
    if bundle["contract_version"] != "execution_memory_graph_source_v2":
        raise DesktopReviewError("memory_graph_source_version_invalid")
    segments = bundle.get("segments")
    if not isinstance(segments, list) or not segments:
        raise DesktopReviewError("memory_graph_segments_invalid")
    keys = [(item["manifest"]["session_id"], item["manifest"]["learning_id"]) for item in segments]
    if len(set(keys)) != len(keys):
        raise DesktopReviewError("memory_graph_duplicate_segments")
    if not any(item["manifest"] == bundle["manifest"] for item in segments):
        raise DesktopReviewError("memory_graph_current_segment_missing")
    return segments


def project_bundle(bundle):
    nodes, edges, unresolved, failures = {}, [], [], []
    for segment in bundle_segments(bundle):
        projection = project_segment(segment["manifest"], segment["events"], segment["reviews"])
        for node in projection["nodes"]:
            current = nodes.get(node["node_id"])
            if current is None:
                nodes[node["node_id"]] = deepcopy(node)
            else:
                current["observations"].extend(deepcopy(node["observations"]))
        for edge in projection["edges"]:
            # 旧版本重建保持原始结构；多段来源才显式增加事件所属段。
            if bundle["contract_version"] == "execution_memory_graph_source_v2":
                edge["evidence"].update(learning_id=segment["manifest"]["learning_id"],
                                        session_id=segment["manifest"]["session_id"])
            edges.append(edge)
        scope = ({"learning_id": segment["manifest"]["learning_id"]}
                 if bundle["contract_version"] == "execution_memory_graph_source_v2" else {})
        unresolved.extend({**row, **scope} for row in projection["unresolved"])
        failures.extend({**row, **scope} for row in projection["non_successful_events"])
    return {"nodes": list(nodes.values()), "edges": edges, "unresolved": unresolved, "non_successful_events": failures}


def logical_id(project_id):
    return "workflow-" + content_hash([KIND, project_id])


def source_path(digest):
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DesktopReviewError("memory_graph_source_digest_invalid")
    return f"desktop-review/memory-graph-sources/{digest}.json"


def read_source(facade, refs):
    fields = {"kind", "task_id", "project_id", "bundle_sha256", "interface_composition"}
    if not isinstance(refs, dict) or set(refs) != fields or refs["kind"] != KIND or refs["task_id"] != "memory-local":
        raise DesktopReviewError("memory_graph_source_invalid")
    path = facade._artifact_file(source_path(refs["bundle_sha256"]), "记忆图来源")
    bundle = read_json_snapshot(path)
    if content_hash(bundle) != refs["bundle_sha256"]:
        raise DesktopReviewError("memory_graph_source_changed")
    if (bundle["manifest"]["start_spec"].get("scope") != "workflow"
            or bundle["manifest"]["start_spec"].get("project_id") != refs["project_id"]):
        raise DesktopReviewError("memory_graph_scope_mismatch")
    for segment in bundle_segments(bundle):
        if (segment["manifest"]["start_spec"].get("scope") != "workflow"
                or segment["manifest"]["start_spec"].get("project_id") != refs["project_id"]):
            raise DesktopReviewError("memory_graph_segment_scope_mismatch")
        validate_segment(facade, segment)
    if not isinstance(refs["interface_composition"], list):
        raise DesktopReviewError("memory_graph_members_invalid")
    return bundle


def validate_segment(facade, bundle):
    ids = [event["request_id"] for event in bundle["events"]]
    if len(ids) != len(set(ids)) or set(bundle["reviews"]) != set(ids):
        raise DesktopReviewError("memory_graph_duplicate_or_missing_events")
    observations = bundle.get("target_observations", {})
    if not isinstance(observations, dict) or set(observations) - set(ids):
        raise DesktopReviewError("memory_graph_target_observations_invalid")
    for event in bundle["events"]:
        if event["learning_id"] != bundle["manifest"]["learning_id"] or event["session_id"] != bundle["manifest"]["session_id"]:
            raise DesktopReviewError("memory_graph_event_scope_mismatch")
        reference = event.get("target_observation")
        if isinstance(reference, dict) and reference.get("kind") == "learning_target_observation":
            if observations.get(event["request_id"]) != reference:
                raise DesktopReviewError("memory_graph_target_observation_missing")
            from .learning_observation_source import load_learning_observation, validate_learning_observation
            validate_learning_observation(event, load_learning_observation(facade, reference))
        elif event["request_id"] in observations:
            raise DesktopReviewError("memory_graph_target_observation_unbound")
        review = bundle["reviews"][event["request_id"]]
        if review is None:
            continue
        if content_hash({key: value for key, value in review.items() if key != "review_sha256"}) != review["review_sha256"]:
            raise DesktopReviewError("memory_graph_review_digest_mismatch")
        validate_event_review(event, review["review"])
        for view in ("before", "after"):
            identity = review["review"][view]
            if identity is None:
                continue
            image = facade._artifact_file(f"desktop-review/evidence-objects/{identity['frame_sha256']}.png", "动作原图")
            if hashlib.sha256(image.read_bytes()).hexdigest() != identity["frame_sha256"]:
                raise DesktopReviewError("memory_graph_frame_changed")


def build_graph(facade, refs, bundle=None):
    bundle = read_source(facade, refs) if bundle is None else bundle
    projection = project_bundle(bundle)
    states = projection["nodes"]
    if set(bundle["pins"]) != {state["node_id"] for state in states}:
        raise DesktopReviewError("memory_graph_state_pins_incomplete")
    nodes = []
    excluded = bundle.get("excluded_states", [])
    if not isinstance(excluded, list) or len(excluded) != len(set(excluded)) or not set(excluded) <= set(bundle["pins"]):
        raise DesktopReviewError("memory_graph_excluded_states_invalid")
    for state in states:
        pin = bundle["pins"][state["node_id"]]
        node = reference_node(facade, pin, refs["task_id"])
        content = facade.load_interface_content(pin["interface_id"], pin["version_id"])
        source = content["source"]
        if source.get("interface_key") != state["interface_key"] or source.get("state_key") != state["state_key"]:
            raise DesktopReviewError("memory_graph_interface_identity_mismatch")
        node.update(node_id=state["node_id"], memory_identity={key: state[key] for key in ("interface_key", "state_key")})
        if state["node_id"] not in excluded:
            nodes.append(node)
    for pin in refs["interface_composition"]:
        nodes.append(reference_node(facade, pin, refs["task_id"]))
    if len({node["node_id"] for node in nodes}) != len(nodes):
        raise DesktopReviewError("memory_graph_duplicate_members")
    edges = [{**deepcopy(edge), "action_type": edge["operation"], "label": edge["operation"],
              "expected_result": "Agent judged success in the recorded run", "editorial": False}
             for edge in projection["edges"]
             if edge["source_node_id"] not in excluded and edge["target_node_id"] not in excluded]
    return {"display_only": True, "artifact_is_authorization": False, "execute_binding_enabled": False,
        "workflow": {"workflow_id": logical_id(refs["project_id"]),
                     "goal": bundle["manifest"]["start_spec"]["title"],
                     "node_ids": [node["node_id"] for node in nodes],
                     "edge_ids": [edge["edge_id"] for edge in edges]},
        "nodes": nodes, "edges": edges, "source": {"kind": KIND, "task_id": refs["task_id"],
                                                    "project_id": refs["project_id"]},
        "invalid_sources": deepcopy(projection["unresolved"]),
        "editorially_excluded_states": deepcopy(excluded),
        "non_successful_events": deepcopy(projection["non_successful_events"])}


def validate_source_update(parent, child):
    before, after = parent["source_refs"], child["source_refs"]
    if (before.get("kind") != KIND or after.get("kind") != KIND
            or any(before[key] != after[key] for key in ("task_id", "project_id", "interface_composition"))
            or child["change"].get("memory_update") != before["bundle_sha256"]):
        raise DesktopReviewError("memory_graph_update_lineage_invalid")


def persist_graph(library, events, learning_id, *, expected_sha256, request_id):
    manifest = events._manifest(learning_id)
    if manifest["start_spec"]["scope"] != "workflow":
        raise ValueError("standalone interface learning does not create a workflow")
    event_ids = sorted(path.stem for path in (events._directory(learning_id) / "events").glob("*.json"))
    if len(event_ids) > 128:
        raise ValueError("draft graph supports at most 128 events per segment; split the learning segment")
    entries = [events._event(learning_id, identity) for identity in event_ids]
    reviews = {identity: events._review(learning_id, identity) for identity in event_ids}
    current = GraphRevisionService(library)._load_head(logical_id(manifest["start_spec"]["project_id"]), required=False)
    previous_bundle = read_source(library, current["source_refs"]) if current else {}
    source_manifest = {key: manifest[key] for key in ("learning_id", "session_id", "start_spec")}
    segment = {"manifest": source_manifest, "events": entries, "reviews": reviews}
    observations = {}
    for event in entries:
        reference = event.get("target_observation")
        if not isinstance(reference, dict) or reference.get("kind") != "learning_target_observation":
            continue
        from .receipt_adapter import target_observation_from_receipt
        from .learning_observation_source import archive_learning_observation
        receipt_path = events.session / "responses" / (event["request_id"] + ".json")
        observation = target_observation_from_receipt(read_json_snapshot(receipt_path), receipt_path, event["request_id"])
        observations[event["request_id"]] = archive_learning_observation(library, event=event, observation=observation)
    if observations:
        segment["target_observations"] = observations
    previous_segments = bundle_segments(previous_bundle) if current else []
    # 重复提交替换同一学习段；新段追加，不从相邻段截图推导跳转。
    segments = [row for row in previous_segments if
        (row["manifest"]["session_id"], row["manifest"]["learning_id"]) != (manifest["session_id"], learning_id)]
    segments.append(segment)
    bundle = {"contract_version": "execution_memory_graph_source_v2", "manifest": source_manifest,
              "segments": segments}
    projection = project_bundle(bundle)
    previous_pins = previous_bundle.get("pins", {})
    pins = {}
    for state in projection["nodes"]:
        if state["node_id"] in previous_pins:
            pins[state["node_id"]] = deepcopy(previous_pins[state["node_id"]])
            continue
        observation = state["observations"][0]
        from .learned_target_regions import derive_target_region
        from .learning_observation_source import load_learning_observation
        matching_segment = segment
        event = next(row for row in matching_segment["events"] if row["request_id"] == observation["event_id"])
        reference = matching_segment.get("target_observations", {}).get(event["request_id"])
        identity = matching_segment["reviews"][event["request_id"]]["review"][observation["view"]]
        region = (derive_target_region(event, load_learning_observation(library, reference), identity["frame_sha256"])
                  if reference is not None else None)
        content = library.import_observation(events, learning_id, observation["event_id"], observation["view"],
            regions=[region] if region else [], recognition_text=region["recognition_text"] if region else "")
        pins[state["node_id"]] = {key: content[key] for key in ("interface_id", "version_id", "content_sha256")}
    # 动作证据与代表界面截图可能不同；同样按摘要归档，绝不用代表图替换事后图。
    for event in entries:
        record = reviews[event["request_id"]]
        if record is None:
            continue
        events._verify_review_frames(event, record["review"])
        for view in ("before", "after"):
            if record["review"][view] is None:
                continue
            from pathlib import Path
            path = Path(event[view]["image_path"])
            path = path if path.is_absolute() else events.session / path
            raw = path.read_bytes()
            digest = record["review"][view]["frame_sha256"]
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("graph frame changed during archival")
            _write_immutable(library._artifact_root / f"desktop-review/evidence-objects/{digest}.png", raw)
    # 图来源不包含清单中的可变图头引用，避免来源摘要循环依赖。
    bundle.update(pins=pins,
        excluded_states=[identity for identity in previous_bundle.get("excluded_states", []) if identity in pins])
    return write_bundle_revision(library, bundle, expected_sha256=expected_sha256, request_id=request_id)


def write_bundle_revision(library, bundle, *, expected_sha256, request_id):
    digest = content_hash(bundle)
    _write_immutable(library._artifact_root / source_path(digest), canonical_json_bytes(bundle) + b"\n")
    project_id = bundle["manifest"]["start_spec"]["project_id"]
    graph_id = logical_id(project_id)
    graphs = GraphRevisionService(library)
    current = graphs._load_head(graph_id, required=False)
    refs = {"kind": KIND, "task_id": "memory-local", "project_id": project_id,
            "bundle_sha256": digest,
            "interface_composition": deepcopy(current["source_refs"].get("interface_composition", [])) if current else []}
    if current and current["source_refs"] == refs:
        return current
    if (current["content_sha256"] if current else None) != expected_sha256:
        raise ValueError("stale memory graph; read its current revision before replacing sources")
    graph = build_graph(library, refs)
    snapshot = graphs._snapshot(logical_id=graph_id, revision=current["revision"] + 1 if current else 1,
        parent_sha256=current["content_sha256"] if current else None, source_refs=refs, graph=graph,
        idempotency_key=request_id if current else None,
        request_sha256=content_hash([expected_sha256, refs]) if current else None)
    if current:
        snapshot["change"]["memory_update"] = current["source_refs"]["bundle_sha256"]
        snapshot["content_sha256"] = graphs._content_sha(snapshot)
    graphs._write_committed(snapshot)
    return graphs.load(graph_id, None)


def adopt_interface(library, workflow_id, node_id, *, expected_sha256, request_id):
    graphs = GraphRevisionService(library)
    current = graphs.load(workflow_id, None)
    if current["content_sha256"] != expected_sha256:
        raise ValueError("stale memory graph")
    bundle = read_source(library, current["source_refs"])
    if node_id not in bundle["pins"]:
        raise ValueError("node is not a learned interface state")
    old = bundle["pins"][node_id]
    latest = library.load_interface_content(old["interface_id"])
    bundle["pins"][node_id] = {key: latest[key] for key in ("interface_id", "version_id", "content_sha256")}
    return write_bundle_revision(library, bundle, expected_sha256=expected_sha256, request_id=request_id)


def exclude_state(library, current, node_id, request_id):
    bundle = read_source(library, current["source_refs"])
    if node_id not in bundle["pins"]:
        raise ValueError("node is not a learned state")
    bundle["excluded_states"] = sorted(set(bundle.get("excluded_states", [])) | {node_id})
    return write_bundle_revision(library, bundle, expected_sha256=current["content_sha256"], request_id=request_id)
