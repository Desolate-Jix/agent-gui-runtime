"""从不可变学习证据恢复显示标注；标注不授予执行权限。"""
from copy import deepcopy

from .learning_observation_source import load_learning_observation, validate_learning_observation


def derive_target_region(event, observation, screenshot_sha256):
    value = validate_learning_observation(event, observation)
    if value["frame"]["sha256"] != screenshot_sha256:
        return None
    candidate = value["candidate"]
    controls = value["uia"]["snapshot"]["controls"]
    matches = [row for row in controls if row.get("bbox") == candidate["bbox"]]
    control = matches[0] if len(matches) == 1 else {}
    name = control.get("name") or candidate.get("text") or candidate.get("name") or event.get("goal") or event["request_id"]
    kinds = {"Button": "button", "Edit": "input", "Text": "text", "Hyperlink": "link",
             "MenuItem": "menu", "Image": "image", "Pane": "container"}
    box = candidate["bbox"]
    return {"region_id": "region-learned-" + event["request_id"],
            "bbox": [box[key] for key in ("x", "y", "w", "h")],
            "name": name, "kind": kinds.get(control.get("control_type"), "control"),
            "meaning": name, "recognition_text": name,
            "learning_evidence": {"source": "derived_learning_evidence", "event_id": value["event_id"],
                "command_sha256": value["command_sha256"], "frame": deepcopy(value["frame"]),
                "candidate": deepcopy(candidate), "artifact_is_authorization": False}}


def read_learned_target_regions(library, interface_id, version_id):
    from .graph_source import KIND, bundle_segments, read_source
    from .content_source import make_source
    content = library.load_interface_content(interface_id, version_id)
    result = {"regions": [], "status": "no_matching_learning_evidence", "issues": [],
              "evidence": [], "source": "derived_learning_evidence", "artifact_is_authorization": False}
    source = content["source"]
    if source.get("kind") != "execution_memory_v1":
        result["status"] = "unsupported_source"
        return result
    if content["content"]["regions"]:
        result.update(regions=deepcopy(content["content"]["regions"]), status="persisted_annotations")
        return result
    for summary in library.list_workflow_graphs():
        graph = library.load_graph_revision(summary["logical_workflow_id"])
        if graph["source_refs"].get("kind") != KIND:
            continue
        bundle = read_source(library, graph["source_refs"])
        if not any(pin == {key: content[key] for key in ("interface_id", "version_id", "content_sha256")}
                   for pin in bundle["pins"].values()):
            continue
        for segment in bundle_segments(bundle):
            for event in segment["events"]:
                record = segment["reviews"][event["request_id"]]
                if record is None or record["review"].get(source["view"]) is None:
                    continue
                expected, _ = make_source(source["task_id"], event, record, source["view"])
                if expected != source:
                    continue
                reference = segment.get("target_observations", {}).get(event["request_id"])
                if reference is None:
                    continue
                observation = load_learning_observation(library, reference)
                region = derive_target_region(event, observation, source["screenshot_sha256"])
                if region is not None and region not in result["regions"]:
                    result["regions"].append(region)
                    result["evidence"].append({"region_id": region["region_id"], "reference": deepcopy(reference),
                        "frame": deepcopy(observation["frame"]), "candidate": deepcopy(observation["candidate"])})
    if result["regions"]:
        result["status"] = "derived_learning_evidence"
    return result
