"""只读核验识别前截图失败，不授予输入或恢复权限。"""
from hashlib import sha256
import json


CONTRACT = "pre_grounding_capture_failure.v1"


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def pre_capture_failure_verified(receipt, operation=None):
    from app.agent.native_identity import validate_native_identity_fact
    try:
        if (not isinstance(receipt, dict) or receipt.get("contract_version") != CONTRACT
                or receipt.get("operation") != "execute_recognition_plan"
                or operation not in (None, "execute_recognition_plan")
                or receipt.get("phase") != "not_dispatched" or receipt.get("status") != "failed"
                or receipt.get("action_executed") is not False or receipt.get("capture") is not None
                or "response" in receipt or receipt.get("local_input_scope_closed") is not True
                or receipt.get("automatic_retry_allowed") is not False
                or not isinstance(receipt.get("step_id"), str) or not receipt["step_id"]
                or not isinstance(receipt.get("finished_at"), str) or not receipt["finished_at"]):
            return False
        identity = receipt["target_identity"]
        if validate_native_identity_fact(identity, target_window_handle=identity["target_window_handle"],
                expected_process_id=identity["process_id"]) is None:
            return False
        geometry = receipt["target_window_geometry"]
        rect = geometry.get("rect")
        if (geometry.get("coordinate_space") != "screen_pixels" or geometry.get("rect_format") != "ltrb"
                or not isinstance(rect, list) or len(rect) != 4 or any(type(v) is not int for v in rect)
                or rect[2] <= rect[0] or rect[3] <= rect[1]):
            return False
        request, error, proof = receipt["request"], receipt["error"], receipt["pre_dispatch_failure"]
        if (not isinstance(request, dict) or not isinstance(request.get("goal"), str) or not request["goal"]
                or not isinstance(error, dict) or error.get("type") != "CaptureVisibilityError"
                or not isinstance(error.get("code"), str) or not error["code"]
                or not isinstance(proof, dict) or set(proof) != {"schema", "stage", "command_id",
                    "grounding_request_created", "input_dispatch_started", "receipt_sha256"}
                or proof.get("schema") != CONTRACT or proof.get("stage") != "before_grounding_capture"
                or not isinstance(proof.get("command_id"), str) or not proof["command_id"]
                or proof.get("grounding_request_created") is not False
                or proof.get("input_dispatch_started") is not False):
            return False
        return proof["receipt_sha256"] == _digest({k: v for k, v in receipt.items() if k != "pre_dispatch_failure"})
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False
