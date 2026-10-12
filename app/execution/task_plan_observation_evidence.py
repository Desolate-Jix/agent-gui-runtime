"""观察证据的纯文件引用与审核包重建，不导入桌面采集。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from app.core.json_snapshot import read_json_snapshot
from .task_plan_review import digest


def reference(session, path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(session):
        raise ValueError("task_plan_observation_evidence_outside_session")
    return {"path": path.relative_to(session).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


def _entries(state, execution_id):
    return state.get("manual_observations", {}).get(execution_id, {"requests": {}, "revisions": []})


def read_ref(session, ref):
    if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or Path(ref["path"]).is_absolute()):
        raise ValueError("task_plan_manual_artifact_invalid")
    path = session / ref["path"]
    if path.is_symlink() or reference(session, path) != ref:
        raise ValueError("task_plan_manual_artifact_changed")
    return read_json_snapshot(path)


def _extend(refs, additions):
    value = deepcopy(refs)
    for item in additions:
        if item not in value:
            value.append(deepcopy(item))
    return value


def _revision(previous, record, record_ref, previous_ref):
    inputs = _extend(previous.get("input_evidence_refs", previous["evidence_refs"]), [record["image_ref"]])
    refs = _extend(previous["evidence_refs"], [previous_ref, record["image_ref"], record_ref])
    packet = deepcopy(previous)
    packet.pop("packet_sha256")
    packet.update(schema="review_packet.v3", latest_observation=deepcopy(record["frame"]),
        packet_revision=previous.get("packet_revision", 0) + 1,
        previous_packet_sha256=previous["packet_sha256"],
        packet_ancestors=[*previous.get("packet_ancestors", []), previous["packet_sha256"]],
        assessment_basis=deepcopy(previous.get("assessment_basis", {
            "packet_sha256": previous["packet_sha256"], "evidence_set_sha256": previous["evidence_set_sha256"],
            "assessment_round": previous["assessment_round"]})),
        input_evidence_refs=inputs, evidence_set_sha256=digest(inputs), evidence_refs=refs,
        artifact_refs=deepcopy(refs), artifact_set_sha256=digest(refs),
        manual_observation_budget=deepcopy(record["capture_budget"]),
        allowed_controls=["review", *(["observe"] if record["capture_budget"]["remaining"] else []), "cancel"])
    packet["packet_sha256"] = digest(packet)
    return packet


def project_packet(state, base, session):
    """从不可变记录重建每版审核包；仅做文件读取，不采集或判断。"""
    execution_id = base["execution_request_id"]
    entries = _entries(state, execution_id)
    previous = deepcopy(base)
    for item in entries["revisions"]:
        record = read_ref(session, item["record_ref"])
        packet = read_ref(session, item["packet_ref"])
        old = read_ref(session, item["previous_packet_ref"])
        request = record.get("request", {})
        saved = entries["requests"].get(request.get("observation_request_id"), {})
        frame = record.get("frame", {})
        if (old != previous or record.get("schema") != "task_plan_manual_observation_record.v1"
                or saved.get("request") != request or saved.get("request_sha256") != digest(request)
                or saved.get("status") != "captured" or saved.get("record_ref") != item["record_ref"]
                or record.get("capture_budget") != saved.get("capture_budget")
                or record["capture_budget"] not in ({"limit": 2, "used": 1, "remaining": 1},
                    {"limit": 2, "used": 2, "remaining": 0})
                or request.get("review_packet_sha256") != previous["packet_sha256"]
                or request.get("evidence_set_sha256") != previous["evidence_set_sha256"]
                or request.get("assessment_round") != previous["assessment_round"]
                or any(request.get(key) != previous[key] for key in
                    ("run_id", "step_id", "execution_request_id", "wait_id"))
                or set(frame) != {"capture_id", "image_path", "sha256", "window_identity", "role"}
                or frame.get("role") != "observation" or frame.get("window_identity") != state["target_identity"]
                or reference(session, frame["image_path"]) != record.get("image_ref")
                or frame.get("sha256") != record["image_ref"]["sha256"]
                or type(record.get("elapsed_ns")) is not int or not 0 <= record["elapsed_ns"] < 12_000_000_000
                or packet != _revision(previous, record, item["record_ref"], item["previous_packet_ref"])
                or saved.get("result", {}).get("packet_sha256") != packet["packet_sha256"]):
            raise ValueError("task_plan_manual_revision_binding_invalid")
        previous = packet
    return previous


def validate_manual_packet(packet, state, session):
    bases = [value["review_packet"] for value in state.get("verification_results", {}).values()
        if value.get("execution_request_id") == packet.get("execution_request_id") and value.get("review_packet")]
    if not bases or any(item != bases[0] for item in bases) or project_packet(state, bases[0], session) != packet:
        raise ValueError("task_plan_manual_revision_binding_invalid")
