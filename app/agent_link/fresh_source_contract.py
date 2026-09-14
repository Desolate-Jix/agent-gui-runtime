"""仅服务端写入的无资产采集来源引用，不授予审核或执行权限。"""

from copy import deepcopy
import re


def validate_fresh_source_metadata(value):
    optional = {"observation_request_sha256"} if isinstance(value, dict) and "observation_request_sha256" in value else set()
    if not isinstance(value, dict) or set(value) != {"connection_id", "task_id", "segment_id", "reference"} | optional:
        raise ValueError("fresh source scope is invalid")
    if optional and (not isinstance(value["observation_request_sha256"], str)
                     or re.fullmatch(r"[0-9a-f]{64}", value["observation_request_sha256"]) is None):
        raise ValueError("fresh observation request digest is invalid")
    if any(not isinstance(value[key], str) or not value[key] or len(value[key]) > limit
           for key, limit in (("connection_id", 160), ("task_id", 4000), ("segment_id", 128))):
        raise ValueError("fresh source identity is invalid")
    reference = value["reference"]
    if not isinstance(reference, dict) or set(reference) != {
        "contract_version", "source_id", "content_sha256", "capture_id", "screenshot_sha256",
    } or reference["contract_version"] != "fresh_learning_source_ref_v1":
        raise ValueError("fresh source reference is invalid")
    for key in ("source_id", "capture_id"):
        if not isinstance(reference[key], str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", reference[key]) is None:
            raise ValueError("fresh source identifier is invalid")
    for key in ("content_sha256", "screenshot_sha256"):
        if not isinstance(reference[key], str) or re.fullmatch(r"[0-9a-f]{64}", reference[key]) is None:
            raise ValueError("fresh source digest is invalid")
    return deepcopy(value)
