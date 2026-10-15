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


def _prepare_frame(root, item, *, static_png=False):
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
            if static_png and (image.format != "PNG" or getattr(image, "is_animated", False)
                    or getattr(image, "n_frames", 1) != 1):
                raise ValueError("decision_temporal_static_png_required")
            mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}[image.format]
            dimensions = image.size
            image.verify()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError):
        raise ValueError("decision_image_invalid") from None
    frame = {"capture_id": capture_id, "sha256": digest, "image_path": str(path), "window_identity": dict(identity), "role": item["role"]}
    return frame, data, mime, dimensions


def prepare_request(session_dir, *, request_id, execution_request_id, condition, frames, mode="execution",
                    phase="after_action", run_id=None, step_id=None, action=None, review_context=None, assessment_context=None,
                    condition_snapshot=None, temporal_context=None, request_budget_seconds=None, include_upload=True):
    if type(include_upload) is not bool:
        raise ValueError("decision_upload_option_invalid")
    _text(request_id, "request_id", 200)
    _text(execution_request_id, "execution_request_id", 200)
    _text(condition, "condition")
    if condition_snapshot is not None:
        from .condition_templates import validate_condition_snapshot
        condition_snapshot = validate_condition_snapshot(condition_snapshot)
        if condition != condition_snapshot["condition"]:
            raise ValueError("decision_condition_snapshot_condition_mismatch")
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
    if assessment_context is not None:
        from .adaptive_policy import normalize_assessment_context
        if phase != "after_action":
            raise ValueError("decision_assessment_phase_invalid")
        assessment_context = normalize_assessment_context(assessment_context)
        expected_roles = ["after"] if assessment_context["assessment_round"] == 0 else ["after", "observation"]
        if roles != expected_roles:
            raise ValueError("decision_assessment_frame_roles_invalid")
    elif phase == "before_action" and roles == ["before", "observation"]:
        context = action.get("freshness_context") if isinstance(action, dict) else None
        region = context.get("changed_region") if isinstance(context, dict) else None
        if (not isinstance(context, dict) or set(context) != {"schema", "changed_region"}
                or context["schema"] != "action_freshness.v1" or not isinstance(region, dict)
                or set(region) != {"x", "y", "w", "h"}
                or any(type(region[key]) is not int for key in region)
                or min(region["x"], region["y"]) < 0 or min(region["w"], region["h"]) <= 0
                or frames[0].get("image_path") == frames[1].get("image_path")):
            raise ValueError("decision_freshness_context_invalid")
    elif ((phase == "before_action" and roles != ["before"])
            or (phase == "after_action" and (roles.count("after") != 1 or roles.count("before") != len(frames) - 1))):
        raise ValueError("decision_frame_roles_invalid")
    root = Path(session_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("decision_session_root_invalid")
    normalized, uploaded = [], []
    if (isinstance(action, dict) and action.get("operation") == "step_result_check"
            and (phase != "after_action" or roles != ["after"] or temporal_context is not None
                or "executed_click" not in action)):
        raise ValueError("decision_step_result_annotation_required")
    from .field_roi import field_roi_requested
    if field_roi_requested(action) and (phase != "after_action" or temporal_context is not None):
        raise ValueError("decision_field_roi_phase_invalid")
    annotate = phase == "before_action" and isinstance(action, dict) and action.get("review_scope") == "candidate"
    for index, item in enumerate(frames):
        frame, data, mime, dimensions = _prepare_frame(
            root, item, static_png=(annotate and index == len(frames) - 1)
                or isinstance(action, dict) and "executed_click" in action)
        normalized.append(frame)
        executed_annotation = None
        if isinstance(action, dict) and "executed_click" in action:
            from .executed_click_annotation import executed_click_metadata
            if phase != "after_action" or temporal_context is not None:
                raise ValueError("decision_executed_click_annotation_phase_invalid")
            executed_annotation = executed_click_metadata(frame, dimensions, action)
        # 采用端仍重读原图并验证哈希与格式，仅省略不会发送的上传编码。
        if include_upload and temporal_context is None:
            uploaded.append({"capture_id": frame["capture_id"], "role": frame["role"], "data_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")})
            if executed_annotation is not None:
                uploaded[-1]["executed_click_annotation"] = {"metadata": executed_annotation}
    if len({item["capture_id"] for item in normalized}) != len(normalized):
        raise ValueError("decision_capture_duplicate")
    if any(item["window_identity"] != normalized[0]["window_identity"] for item in normalized):
        raise ValueError("decision_window_binding_mismatch")
    if (assessment_context is not None and assessment_context["assessment_round"] > 0
            and normalized[0]["image_path"] == normalized[1]["image_path"]):
        raise ValueError("decision_observation_image_reused")
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
    if annotate:
        from .candidate_annotation import candidate_annotation_metadata
        annotation = candidate_annotation_metadata(normalized[-1], dimensions, action.get("candidate"))
        if include_upload:
            # 先验证完整像素解码；整窗标记仅在实际上传该视图时编码。
            try:
                with Image.open(BytesIO(data)) as image:
                    image.convert("RGBA")
            except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
                raise ValueError("decision_candidate_annotation_image_invalid") from None
            uploaded[-1]["candidate_annotation"] = {"metadata": annotation}
    if review_context is not None:
        from .adaptive_policy import normalize_review_context
        binding["review_context"] = normalize_review_context(review_context)
    if assessment_context is not None:
        binding["assessment_context"] = assessment_context
    if condition_snapshot is not None:
        context = binding.get("review_context")
        if context is None or context["allowed_states"] != condition_snapshot["allowed_states"]:
            raise ValueError("decision_condition_snapshot_scope_mismatch")
        if (condition_snapshot["review_policy"] == "always_main"
                and context.get("review_policy", "adaptive") != "always_main"):
            raise ValueError("decision_condition_snapshot_policy_weakened")
        binding["condition_snapshot"] = condition_snapshot
    if temporal_context is not None:
        from .temporal_playback import prepare_temporal_context
        if phase != "after_action":
            raise ValueError("decision_temporal_phase_invalid")
        binding["temporal_context"], uploaded = prepare_temporal_context(
            root, temporal_context, normalized, _prepare_frame, include_upload=include_upload)
    if request_budget_seconds is not None:
        if (type(request_budget_seconds) not in {int, float} or not math.isfinite(request_budget_seconds)
                or not 0 < request_budget_seconds <= 60):
            raise ValueError("decision_request_budget_invalid")
        binding["request_budget_seconds"] = request_budget_seconds
    return binding, uploaded
