"""只接受维护采集器的完整超时原件；不补写条件成功或采集新证据。"""
from math import isfinite
from pathlib import Path

from PIL import Image


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return isfinite(value) and value >= 0
    except OverflowError:
        return False


def _probe(value, identity, size, *, sample=False):
    if not isinstance(value, dict) or value.get("status") not in ("absent", "matched"):
        return False
    fields = {"status", "source", "target_window_handle", "process_id"}
    if sample:
        fields.add("elapsed_ms")
        if not _number(value.get("elapsed_ms")):
            return False
    if value["status"] == "matched":
        fields.update({"runtime_id", "bbox"})
        runtime_id, bbox = value.get("runtime_id"), value.get("bbox")
        if (not isinstance(runtime_id, list) or not runtime_id
                or any(type(item) is not int for item in runtime_id)
                or not isinstance(bbox, list) or len(bbox) != 4
                or any(type(item) is not int for item in bbox)):
            return False
        x, y, width, height = bbox
        if not (0 <= x < x + width <= size[0] and 0 <= y < y + height <= size[1]):
            return False
    return (set(value) == fields and value.get("source") == "uia_exact_name"
        and type(value.get("target_window_handle")) is int
        and type(value.get("process_id")) is int
        and value["target_window_handle"] == identity["handle"]
        and value["process_id"] == identity["process_id"])


def native_mismatch_eligible(rule, effective, frame, *, condition_snapshot=None):
    """调用方已核验输入终态和原后图；此处从严绑定整段原生观察。"""
    if "condition_binding" in rule:
        from app.judgment.condition_templates import validate_condition_snapshot
        try:
            if validate_condition_snapshot(condition_snapshot)["binding"] != rule["condition_binding"]:
                return False
        except (ValueError, TypeError):
            return False
    elif not isinstance(rule.get("decision_condition"), str) or not rule["decision_condition"].strip():
        return False
    result = effective["result"]
    if effective["command"]["kind"] == "input_sequence":
        steps = result.get("steps")
        if not isinstance(steps, list) or not steps or not isinstance(steps[-1], dict):
            return False
        final = steps[-1]
        receipt = final.get("receipt")
        if (final.get("name") != "search" or final.get("operation") != "press_key"
                or final.get("action_executed") is not True or not isinstance(receipt, dict)):
            return False
        identity = receipt.get("target_identity")
        if (not isinstance(identity, dict) or type(identity.get("target_window_handle")) is not int
                or type(identity.get("process_id")) is not int
                or not _number(identity.get("process_create_time"))
                or {"handle": identity["target_window_handle"], "process_id": identity["process_id"],
                    "process_create_time": identity["process_create_time"]} != frame["window_identity"]):
            return False
        observation = receipt.get("observation")
    else:
        observation = result.get("observation")
    wait_ms = effective["command"].get("observation_wait_ms")
    if (not isinstance(observation, dict) or observation.get("status") != "captured"
            or observation.get("source") != "post_action" or observation.get("authorizes_action") is not False
            or observation.get("readiness") != "timed_out" or observation.get("automatic_retry_allowed") is not False
            or type(observation.get("render_grace_ms")) is not int or observation["render_grace_ms"] != wait_ms):
        return False
    capture, proof = observation.get("capture"), observation.get("condition")
    if not isinstance(capture, dict) or not isinstance(proof, dict):
        return False
    if (capture.get("sha256") != frame["sha256"] or capture.get("capture_id") != frame["capture_id"]
            or not isinstance(capture.get("image_path"), str)
            or capture.get("frame_id") != "after_settled" or capture.get("observation_stage") != "after_condition_wait"
            or type(capture.get("render_grace_ms")) is not int or capture["render_grace_ms"] != wait_ms
            or capture.get("render_completion_verified") is not False
            or "window_identity" in capture and capture["window_identity"] != frame["window_identity"]):
        return False
    try:
        if Path(capture["image_path"]).resolve() != Path(frame["image_path"]).resolve():
            return False
    except (OSError, ValueError):
        return False
    fields = {"status", "source", "expected", "baseline", "samples", "elapsed_ms", "timeout_ms",
        "after_sha256", "deadline_scope", "deadline_exceeded", "capture_elapsed_ms",
        "after_capture_rechecked", "task_effect_verified", "render_completion_verified", "automatic_retry_allowed"}
    if (set(proof) != fields or proof.get("status") != "timed_out"
            or proof.get("source") != "uia_exact_name" or proof.get("expected") != rule["condition"]
            or proof.get("after_sha256") != frame["sha256"]
            or proof.get("after_capture_rechecked") is not False
            or proof.get("deadline_scope") != "polling_budget_not_io_timeout"
            or type(proof.get("deadline_exceeded")) is not bool
            or proof.get("task_effect_verified") is not None
            or proof.get("render_completion_verified") is not False
            or proof.get("automatic_retry_allowed") is not False):
        return False
    elapsed, captured, timeout = proof["elapsed_ms"], proof["capture_elapsed_ms"], proof["timeout_ms"]
    if (not _number(elapsed) or not _number(captured) or type(timeout) is not int or timeout <= 0
            or timeout != wait_ms or captured > elapsed
            or elapsed < timeout):
        return False
    samples = proof["samples"]
    if not isinstance(samples, list) or not samples:
        return False
    try:
        with Image.open(frame["image_path"]) as image:
            size = image.size
    except (OSError, ValueError):
        return False
    if not _probe(proof["baseline"], frame["window_identity"], size):
        return False
    previous = 0
    for sample in samples:
        if not _probe(sample, frame["window_identity"], size, sample=True):
            return False
        at = sample["elapsed_ms"]
        if not previous <= at <= elapsed:
            return False
        previous = at
    return True
