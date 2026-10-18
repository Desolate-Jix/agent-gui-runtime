"""可选本地预期图像检查；只读观察，不重放输入。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from math import isfinite
from pathlib import Path
import re
from time import monotonic, sleep

import cv2
import numpy as np
from PIL import Image
from app.desktop_review.external_mapping import canonical_json_bytes


def validate_image_check(value) -> dict:
    fields = {"contract_version", "reference_sha256", "reference_size", "template_bbox", "search_roi", "threshold"}
    if (not isinstance(value, dict) or set(value) != fields
            or value["contract_version"] != "workflow_image_check.v1"
            or not isinstance(value["reference_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["reference_sha256"]) is None
            or type(value["threshold"]) is not float or not isfinite(value["threshold"])
            or not 0.5 <= value["threshold"] <= 1):
        raise ValueError("workflow_image_check_invalid")
    size = value["reference_size"]
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n <= 0 for n in size):
        raise ValueError("workflow_image_size_invalid")
    for name in ("template_bbox", "search_roi"):
        box = value[name]
        if (not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                or min(box[:2]) < 0 or min(box[2:]) <= 0
                or box[0] + box[2] > size[0] or box[1] + box[3] > size[1]):
            raise ValueError("workflow_image_bbox_invalid")
    if any(value["template_bbox"][i] > value["search_roi"][i] for i in (2, 3)):
        raise ValueError("workflow_image_search_roi_too_small")
    return deepcopy(value)


def _pixels(raw, check):
    if sha256(raw).hexdigest() != check["reference_sha256"]:
        raise ValueError("workflow_image_reference_sha256_changed")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or list(image.size) != check["reference_size"]:
            raise ValueError("workflow_image_reference_size_invalid")
        pixels = np.array(image.convert("RGB"))
    x, y, w, h = check["template_bbox"]
    template = pixels[y:y+h, x:x+w]
    if float(cv2.cvtColor(template, cv2.COLOR_RGB2GRAY).std()) < 5:
        raise ValueError("workflow_image_template_low_texture")
    return pixels


def load_reference_image(library, check) -> bytes:
    check = validate_image_check(check)
    root = getattr(library, "_artifact_root", None)
    if root is None:
        raise ValueError("workflow_image_artifact_root_missing")
    root = Path(root).resolve()
    path = root / "desktop-review" / "evidence-objects" / (check["reference_sha256"] + ".png")
    if not path.resolve().is_relative_to(root):
        raise ValueError("workflow_image_reference_outside_library")
    raw = path.read_bytes()
    _pixels(raw, check)
    return raw


def match_image_check(check, reference_raw, current_frame, *, current_raw=None) -> dict:
    check = validate_image_check(check)
    proof = {"contract_version": "workflow_image_match.v1", "check_sha256": sha256(canonical_json_bytes(check)).hexdigest(),
             "reference_sha256": check["reference_sha256"], "capture_id": current_frame.get("capture_id"),
             "capture_sha256": current_frame.get("sha256"), "threshold": check["threshold"],
             "template_bbox": check["template_bbox"], "search_roi": check["search_roi"],
             "matched": False, "ambiguous": False, "bbox": None, "score": None, "reason": "image_unavailable"}
    try:
        reference = _pixels(reference_raw, check)
        raw = Path(current_frame["image_path"]).read_bytes() if current_raw is None else current_raw
        if sha256(raw).hexdigest() != current_frame["sha256"]:
            raise ValueError("workflow_image_capture_sha256_changed")
        with Image.open(BytesIO(raw)) as image:
            size = current_frame["image_size"]
            if (image.format != "PNG" or list(image.size) != check["reference_size"]
                    or image.size != (size["width"], size["height"])):
                raise ValueError("workflow_image_current_size_changed")
            current = np.array(image.convert("RGB"))
        rect = current_frame["window_rect"]
        if len(rect) != 4 or [rect[2]-rect[0], rect[3]-rect[1]] != check["reference_size"]:
            raise ValueError("workflow_image_window_geometry_changed")
        x, y, w, h = check["template_bbox"]
        rx, ry, rw, rh = check["search_roi"]
        scores = cv2.matchTemplate(current[ry:ry+rh, rx:rx+rw], reference[y:y+h, x:x+w], cv2.TM_CCOEFF_NORMED)
        if not np.isfinite(scores).all():
            raise ValueError("workflow_image_score_invalid")
        _, score, _, location = cv2.minMaxLoc(scores)
        lx, ly = location
        proof.update(score=float(score), bbox=[rx+lx, ry+ly, w, h])
        # 仅合并相邻的同一峰；周期纹理中的重叠高分对象同样拒绝。
        peaks = ((scores >= check["threshold"]) & (scores >= cv2.dilate(scores, np.ones((3, 3), np.uint8)))).astype(np.uint8)
        components, _ = cv2.connectedComponents(peaks, connectivity=8)
        proof["ambiguous"] = components > 2
        proof["matched"] = score >= check["threshold"] and not proof["ambiguous"]
        proof["reason"] = "image_matched" if proof["matched"] else "image_ambiguous" if proof["ambiguous"] else "image_not_matched"
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as error:
        proof["reason"] = str(error)
    return proof


def image_proof_current(check, observation):
    check = validate_image_check(check)
    proof = observation.get("values", {}).get("image_check")
    if not isinstance(proof, dict):
        return False
    bbox = proof.get("bbox")
    roi = check["search_roi"]
    return (observation.get("source") == "image_template"
            and proof.get("contract_version") == "workflow_image_match.v1"
            and proof.get("matched") is True and proof.get("ambiguous") is False
            and proof.get("check_sha256") == sha256(canonical_json_bytes(check)).hexdigest()
            and proof.get("reference_sha256") == check["reference_sha256"]
            and proof.get("capture_id") == observation.get("capture_id")
            and proof.get("capture_sha256") == observation.get("capture_sha256")
            and proof.get("threshold") == check["threshold"]
            and proof.get("template_bbox") == check["template_bbox"] and proof.get("search_roi") == roi
            and type(proof.get("score")) is float and isfinite(proof["score"])
            and check["threshold"] <= proof["score"] <= 1.000001
            and isinstance(bbox, list) and len(bbox) == 4 and all(type(n) is int for n in bbox)
            and bbox[2:] == check["template_bbox"][2:]
            and bbox[0] >= roi[0] and bbox[1] >= roi[1]
            and bbox[0]+bbox[2] <= roi[0]+roi[2] and bbox[1]+bbox[3] <= roi[1]+roi[3])


def observe_image_check(coordinator, *, target, identity, check, reference_raw):
    from .memory_observation import capture_memory_observation
    attempts = []
    frame = None
    anchor = None
    deadline = monotonic() + 2.0
    cancel = getattr(coordinator, '_cancel_wait', None)
    while True:
        if cancel is not None and cancel.is_set():
            attempts.append({'matched': False, 'reason': 'workflow_image_observation_cancelled'})
            break
        if monotonic() >= deadline:
            break
        try:
            frame, _ = capture_memory_observation(coordinator, target["handle"], target["process_id"], recipe=None)
            if cancel is not None and cancel.is_set():
                raise ValueError('workflow_image_observation_cancelled')
            if frame["window_identity"] != identity:
                raise ValueError("workflow_image_window_identity_changed")
            geometry = {key: deepcopy(frame.get(key)) for key in ("window_rect", "image_size", "window_identity", "application")}
            if anchor is not None and geometry != anchor:
                raise ValueError("workflow_image_observation_geometry_changed")
            anchor = geometry
            proof = match_image_check(check, reference_raw, frame)
            if cancel is not None and cancel.is_set():
                raise ValueError('workflow_image_observation_cancelled')
        except (OSError, ValueError) as error:
            attempts.append({"matched": False, "reason": str(error)})
            break
        attempts.append(proof)
        if proof["matched"] or proof["reason"] != "image_not_matched":
            break
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        # 等待可被既有取消事件唤醒，不新增动作或突破两秒捕获预算。
        delay = min(0.1, remaining)
        if cancel is not None:
            if cancel.wait(delay):
                attempts.append({'matched': False, 'reason': 'workflow_image_observation_cancelled'})
                break
        else:
            sleep(delay)
    if not attempts:
        attempts.append({'matched': False, 'reason': 'workflow_image_observation_timeout'})
    matched = bool(attempts[-1].get("matched"))
    return {"frame": frame, "scope_id": "image-check:" + sha256(canonical_json_bytes(check)).hexdigest(),
            "source": "image_template", "complete": matched, "reason": attempts[-1]["reason"],
            "values": {"image_check": attempts[-1]} if matched else {}, "evidence": {"attempts": attempts}}
