"""固定控件的局部图像记忆；只返回绑定截图的定位结果，不派发输入。"""
from io import BytesIO
from pathlib import Path
import hashlib
import math
import re

from app.core.json_snapshot import read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from .receipt_adapter import content_hash


def validate_request(request):
    common = {"action", "learning_id"}
    fields = {"save": {"interface_id", "version_id", "region_id", "padding", "radius"},
              "list": {"interface_id", "version_id"},
              "locate": {"template_id", "event_id", "view", "frame_sha256",
                         "interface_key", "state_key"}}
    action = request.get("action")
    if not isinstance(action, str) or action not in fields or set(request) - common - fields[action]:
        raise ValueError("invalid learning_template action or fields")
    if action in {"save", "list"}:
        for field, pattern in (("interface_id", r"interface-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"),
                               ("version_id", r"interface-version-[0-9a-f]{64}")):
            if not isinstance(request.get(field), str) or not re.fullmatch(pattern, request[field]):
                raise ValueError(field + " must identify a pinned interface version")
    if action == "save":
        if not isinstance(request.get("region_id"), str) or not request["region_id"].strip():
            raise ValueError("region_id is required")
        for field, default, lower, upper in (("padding", 6, 0, 32), ("radius", 80, 0, 512)):
            value = request.get(field, default)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{field} must be {lower}..{upper} pixels")
    if action == "locate":
        for field, pattern in (("template_id", r"template-[0-9a-f]{64}"),
                               ("event_id", r"[a-z0-9][a-z0-9_-]{0,79}"),
                               ("frame_sha256", r"[0-9a-f]{64}"),
                               ("interface_key", r"[a-z0-9][a-z0-9_-]{0,79}"),
                               ("state_key", r"[a-z0-9][a-z0-9_-]{0,79}")):
            if not isinstance(request.get(field), str) or not re.fullmatch(pattern, request[field]):
                raise ValueError("invalid " + field)
        if request.get("view") not in {"before", "after"}:
            raise ValueError("view must be before or after")
    return request


def _root(library):
    return library._artifact_root / "desktop-review" / "control-templates"


def _load(library, identity):
    if not re.fullmatch(r"template-[0-9a-f]{64}", identity):
        raise ValueError("invalid template_id")
    value = read_json_snapshot(_root(library) / (identity + ".json"))
    if "template-" + content_hash(value) != identity:
        raise ValueError("template descriptor digest mismatch")
    return value


def save_template(library, request):
    from PIL import Image
    from app.desktop_review.interface_content import InterfaceContentService
    InterfaceContentService(library)._require_active(request["interface_id"])
    content = library.load_interface_content(request["interface_id"], request["version_id"])
    if content["source"].get("kind") != "execution_memory_v1":
        raise ValueError("template learning requires receipt-backed interface content")
    matches = [row for row in content["content"]["regions"] if row["region_id"] == request["region_id"]]
    if len(matches) != 1:
        raise ValueError("region is absent or ambiguous in this interface version")
    evidence = library.load_interface_content_evidence(content["interface_id"], content["version_id"])
    raw = library._artifact_file(evidence["image_path"], "模板原图").read_bytes()
    if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
        raise ValueError("template source image changed")
    x, y, w, h = matches[0]["bbox"]
    x0, y0, x1, y1 = math.floor(x), math.floor(y), math.ceil(x+w), math.ceil(y+h)
    with Image.open(BytesIO(raw)) as image:
        image = image.convert("RGB")
        if not (0 <= x0 < x1 <= image.width and 0 <= y0 < y1 <= image.height):
            raise ValueError("target region is outside its source image")
        pad = request.get("padding", 6)
        left, top = max(0, x0-pad), max(0, y0-pad)
        right, bottom = min(image.width, x1+pad), min(image.height, y1+pad)
        cropped = image.crop((left, top, right, bottom))
        stream = BytesIO()
        cropped.save(stream, format="PNG")
        png = stream.getvalue()
        value = {"contract_version": "memory_control_template_v1",
            "interface_id": content["interface_id"], "version_id": content["version_id"],
            "content_sha256": content["content_sha256"], "region_id": request["region_id"],
            "interface_key": content["source"]["interface_key"], "state_key": content["source"]["state_key"],
            "label": matches[0]["name"], "source_image_sha256": evidence["sha256"],
            "viewport_size": {"width": image.width, "height": image.height},
            "crop_bbox": [left, top, right-left, bottom-top],
            "target_offset": [x0-left, y0-top, x1-x0, y1-y0],
            "radius": request.get("radius", 80), "min_score": 0.92,
            "png_sha256": hashlib.sha256(png).hexdigest()}
    identity = "template-" + content_hash(value)
    _write_immutable(_root(library) / (value["png_sha256"] + ".png"), png)
    _write_immutable(_root(library) / (identity + ".json"), canonical_json_bytes(value) + b"\n")
    return {"template_id": identity, **value, "input_executed": False}


def list_templates(library, request):
    values = []
    for path in sorted(_root(library).glob("template-*.json")):
        value = _load(library, path.stem)
        if (value["interface_id"], value["version_id"]) == (request["interface_id"], request["version_id"]):
            values.append({"template_id": path.stem, "region_id": value["region_id"], "label": value["label"]})
    return {"templates": values, "input_executed": False}


def template_evidence(library, identity):
    value = _load(library, identity)
    content = library.load_interface_content(value["interface_id"], value["version_id"])
    if (content["content_sha256"] != value["content_sha256"]
            or content["source"]["screenshot_sha256"] != value["source_image_sha256"]):
        raise ValueError("template source version no longer matches its descriptor")
    digest = value["png_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("invalid template image digest")
    path = _root(library) / (digest + ".png")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("template PNG changed or is invalid")
    return {"template_id": identity, **value,
            "image_path": path.relative_to(library._artifact_root).as_posix()}


def locate_template(library, events, learning_id, request):
    event = events._event(learning_id, request["event_id"])
    frame = event[request["view"]]
    if not frame.get("image_path"):
        raise ValueError("selected event has no image")
    path = Path(frame["image_path"])
    path = (path if path.is_absolute() else events.session / path).resolve()
    path.relative_to(events.session.resolve())
    return match_template_frame(library, request, path, frame)


def match_template_frame(library, request, path, frame):
    from PIL import Image
    import cv2
    import numpy as np
    from app.operation.visual_asset_matching import match_visual_asset
    from app.desktop_review.interface_content import InterfaceContentService
    value = _load(library, request["template_id"])
    InterfaceContentService(library)._require_active(value["interface_id"])
    content = library.load_interface_content(value["interface_id"], value["version_id"])
    if content["content_sha256"] != value["content_sha256"]:
        raise ValueError("template pinned content digest mismatch")
    base = {"template_id": request["template_id"], "label": value["label"], "input_executed": False,
            "can_authorize_click": False, "coordinate_space": "capture_image_pixels",
            "interface_identity_verified": False, "identity_basis": "agent_supplied",
            "search_scope": "near_recorded_window_position", "automatic_retry_allowed": False}
    if (value["interface_key"], value["state_key"]) != (request["interface_key"], request["state_key"]):
        return {**base, "status": "interface_mismatch", "candidate": None}
    if frame.get("sha256") != request["frame_sha256"] or not frame.get("image_path"):
        raise ValueError("frame binding is missing or differs from selected evidence")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != request["frame_sha256"]:
        raise ValueError("current frame digest mismatch")
    template_path = _root(library) / (value["png_sha256"] + ".png")
    png = template_path.read_bytes()
    if hashlib.sha256(png).hexdigest() != value["png_sha256"]:
        raise ValueError("template PNG digest mismatch")
    with Image.open(BytesIO(raw)) as image:
        size = {"width": image.width, "height": image.height}
    base.update(frame_sha256=request["frame_sha256"], event_id=request.get("event_id"), viewport_size=size)
    if size != value["viewport_size"]:
        return {**base, "status": "viewport_changed_relearn_required", "candidate": None}
    gray = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None or float(gray.std()) < 5.0:
        return {**base, "status": "template_has_insufficient_detail", "candidate": None}
    x, y, w, h = value["crop_bbox"]
    radius = value["radius"]
    left, top = max(0, x-radius), max(0, y-radius)
    roi = {"x": left, "y": top, "w": min(size["width"], x+w+radius)-left,
           "h": min(size["height"], y+h+radius)-top}
    result = match_visual_asset(asset_id=request["template_id"], template_path=template_path,
        target_image_path=path, label=value["label"], semantic_action="locate_control",
        allowed_region=roi, scales=(1.0,), methods=("gray_template",),
        min_score=value["min_score"], min_score_gap=0.04, viewport_size=size)
    # 匹配函数重开文件后再核对摘要，避免把更换后的图片绑定到原事件。
    if hashlib.sha256(path.read_bytes()).hexdigest() != request["frame_sha256"]:
        raise ValueError("frame changed during matching")
    if hashlib.sha256(template_path.read_bytes()).hexdigest() != value["png_sha256"]:
        raise ValueError("template changed during matching")
    candidates = result.get("top_candidates", [])
    ambiguous = result.get("ambiguous", False) or sum(row["score"] >= value["min_score"] for row in candidates) > 1
    candidate = None
    if result.get("matched") and not ambiguous:
        box = result["bbox"]
        ox, oy, tw, th = value["target_offset"]
        bbox = {"x": box["x"]+ox, "y": box["y"]+oy, "w": tw, "h": th}
        candidate = {"bbox": bbox, "click_point": {"x": bbox["x"]+tw//2, "y": bbox["y"]+th//2},
            "capture_id": frame.get("capture_id") or frame.get("frame_id") or request["frame_sha256"],
            "viewport_size": size, "source": "memory_control_template_v1",
            "freshness": "recorded_capture_requires_live_recheck", "score": result["match_score"]}
    return {**base, "status": "matched" if candidate else "ambiguous" if ambiguous else "not_found",
        "candidate": candidate, "diagnostics": {key: result.get(key) for key in
            ("match_score", "score_gap_to_second", "top_candidates", "failure_reason", "elapsed_ms")},
        "next": "Agent must confirm current interface and recheck capture/window freshness before using the existing executor. No match: inspect evidence and decide whether fresh recognition is needed; never click stored coordinates."}
