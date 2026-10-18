"""执行证据来源适配；只扩展现有界面库，不模拟旧 batch。"""
from copy import deepcopy
import hashlib
import re

from app.core.json_snapshot import read_json_snapshot
from .receipt_adapter import content_hash
from .projector import validate_event_review


SOURCE_KIND = "execution_memory_v1"
SOURCE_FIELDS = {"kind", "task_id", "source_ref", "external_interface_id", "screenshot_id",
                 "screenshot_sha256", "learning_id", "event_id", "view", "review_sha256",
                 "interface_key", "state_key"}


def valid_source(source):
    if not isinstance(source, dict) or set(source) != SOURCE_FIELDS or source.get("kind") != SOURCE_KIND:
        return False
    if source.get("view") not in {"before", "after"}:
        return False
    if not all(isinstance(value, str) and value.strip() for value in source.values()):
        return False
    return all(re.fullmatch(r"[0-9a-f]{64}", source[key]) for key in
               ("source_ref", "screenshot_sha256", "review_sha256"))


def image_path(source):
    if not valid_source(source):
        raise ValueError("invalid execution-memory source")
    return f"desktop-review/evidence-objects/{source['screenshot_sha256']}.png"


def descriptor_path(source):
    if not valid_source(source):
        raise ValueError("invalid execution-memory source")
    return f"desktop-review/execution-sources/{source['source_ref']}.json"


def make_source(task_id, event, review_record, view):
    review = validate_event_review(event, review_record["review"])
    identity = review[view]
    if identity is None:
        raise ValueError("assign an explicit interface identity to this observation first")
    record = {key: deepcopy(value) for key, value in review_record.items() if key != "review_sha256"}
    if (content_hash(record) != review_record["review_sha256"]
            or record.get("learning_id") != event["learning_id"]):
        raise ValueError("execution-memory review digest mismatch")
    descriptor = {"contract_version": SOURCE_KIND, "task_id": task_id, "view": view,
                  "event": deepcopy(event), "review_record": record}
    source = {"kind": SOURCE_KIND, "task_id": task_id, "source_ref": content_hash(descriptor),
        "external_interface_id": identity["interface_key"] + ":" + identity["state_key"],
        "screenshot_id": event["request_id"] + ":" + view,
        "screenshot_sha256": identity["frame_sha256"], "learning_id": event["learning_id"],
        "event_id": event["request_id"], "view": view, "review_sha256": review_record["review_sha256"],
        "interface_key": identity["interface_key"], "state_key": identity["state_key"]}
    if not valid_source(source):
        raise ValueError("execution-memory source fields are invalid")
    return source, descriptor


def validate_binding(facade, source):
    path = facade._artifact_file(descriptor_path(source), "执行来源")
    descriptor = read_json_snapshot(path)
    if content_hash(descriptor) != source["source_ref"] or descriptor.get("contract_version") != SOURCE_KIND:
        raise ValueError("execution-memory descriptor digest mismatch")
    record = descriptor["review_record"]
    expected, _ = make_source(descriptor["task_id"], descriptor["event"],
                             {**record, "review_sha256": content_hash(record)}, descriptor["view"])
    if expected != source:
        raise ValueError("execution-memory source binding mismatch")


def read_image(facade, source):
    relative = image_path(source)
    raw = facade._artifact_file(relative, "执行来源原图").read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["screenshot_sha256"]:
        raise ValueError("execution-memory image digest mismatch")
    return relative, raw
