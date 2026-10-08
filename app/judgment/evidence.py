"""仅接受会话内原始图像，读取与上传使用同一份已校验字节。"""
import base64
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re

from PIL import Image, UnidentifiedImageError


def _text(value, name, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("decision_" + name + "_invalid")
    return value


def prepare_request(session_dir, *, request_id, execution_request_id, condition, frames, mode="execution",
                    phase="after_action", run_id=None, step_id=None, action=None):
    _text(request_id, "request_id", 200)
    _text(execution_request_id, "execution_request_id", 200)
    _text(condition, "condition")
    if mode not in ("execution", "learning") or phase not in ("before_action", "after_action"):
        raise ValueError("decision_mode_or_phase_invalid")
    if mode == "learning":
        _text(run_id, "run_id", 200)
        _text(step_id, "step_id", 200)
    for name, value in (("run_id", run_id), ("step_id", step_id)):
        if value is not None:
            _text(value, name, 200)
    if not isinstance(frames, list) or not 1 <= len(frames) <= 2:
        raise ValueError("decision_frames_invalid")
    roles = [item.get("role") if isinstance(item, dict) else None for item in frames]
    if ((phase == "before_action" and roles != ["before"])
            or (phase == "after_action" and (roles.count("after") != 1 or roles.count("before") != len(frames) - 1))):
        raise ValueError("decision_frame_roles_invalid")
    root = Path(session_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("decision_session_root_invalid")
    normalized, uploaded = [], []
    for item in frames:
        if set(item) != {"capture_id", "sha256", "image_path", "window_identity", "role"}:
            raise ValueError("decision_frame_fields_invalid")
        capture_id = _text(item["capture_id"], "capture_id", 200)
        digest = item["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("decision_evidence_hash_invalid")
        identity = item["window_identity"]
        if not isinstance(identity, dict) or set(identity) != {"handle", "process_id", "process_create_time"}:
            raise ValueError("decision_window_identity_invalid")
        if any(type(identity[key]) is not int or identity[key] <= 0 for key in ("handle", "process_id")):
            raise ValueError("decision_window_identity_invalid")
        created = identity["process_create_time"]
        if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
            raise ValueError("decision_window_identity_invalid")
        image_ref = _text(item["image_path"], "image_path", 32768)
        if "://" in image_ref:
            raise ValueError("decision_external_image_rejected")
        path = Path(image_ref)
        if not path.is_absolute():
            path = root / path
        path = path.resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("decision_evidence_outside_session")
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("decision_image_too_large")
        data = path.read_bytes()
        if len(data) > 20 * 1024 * 1024 or sha256(data).hexdigest() != digest:
            raise ValueError("decision_evidence_hash_mismatch")
        try:
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG", "WEBP", "GIF") or image.width * image.height > 40_000_000:
                    raise ValueError("decision_image_format_invalid")
                mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[image.format]
                image.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
            raise ValueError("decision_image_invalid") from None
        frame = {"capture_id": capture_id, "sha256": digest, "image_path": str(path), "window_identity": dict(identity), "role": item["role"]}
        normalized.append(frame)
        uploaded.append({"capture_id": capture_id, "role": item["role"], "data_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")})
    if len({item["capture_id"] for item in normalized}) != len(normalized):
        raise ValueError("decision_capture_duplicate")
    if any(item["window_identity"] != normalized[0]["window_identity"] for item in normalized):
        raise ValueError("decision_window_binding_mismatch")
    if action is not None:
        if not isinstance(action, dict):
            raise ValueError("decision_action_context_invalid")
        try:
            encoded = json.dumps(action, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            raise ValueError("decision_action_context_invalid") from None
        if len(encoded.encode("utf-8")) > 16 * 1024:
            raise ValueError("decision_action_context_too_large")
        action = json.loads(encoded)
    binding = {"request_id": request_id, "execution_request_id": execution_request_id, "condition": condition,
               "frames": normalized, "mode": mode, "phase": phase, "run_id": run_id, "step_id": step_id, "action": action}
    return binding, uploaded
