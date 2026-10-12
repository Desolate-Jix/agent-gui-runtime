"""追加观察图像投递只读持久原件，不触发采集或恢复。"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image

from .task_plan_observation_evidence import read_ref


def manual_observation_image(session_dir, result):
    from .task_plan_review import validate_packet
    session = Path(session_dir).resolve(strict=True)
    packet = result.get("review_packet")
    outcome = result.get("manual_observation")
    if (not isinstance(packet, dict) or packet.get("schema") != "review_packet.v3"
            or not isinstance(outcome, dict) or outcome.get("status") != "captured"):
        raise ValueError("task_plan_observation_delivery_binding_invalid")
    validate_packet(packet, result, session)
    if outcome.get("packet_sha256") != packet.get("packet_sha256"):
        # 重放旧逻辑请求只读取已认证祖先，不回退当前审核包。
        entries = result.get("manual_observations", {}).get(outcome.get("execution_request_id"), {})
        saved = entries.get("requests", {}).get(outcome.get("observation_request_id"), {})
        if (outcome.get("packet_sha256") not in packet.get("packet_ancestors", [])
                or outcome.get("execution_request_id") != packet.get("execution_request_id")
                or saved.get("result") != outcome or saved.get("status") != "captured"):
            raise ValueError("task_plan_observation_delivery_binding_invalid")
        matches = [item for item in entries.get("revisions", []) if item.get("record_ref") == saved.get("record_ref")]
        if len(matches) != 1:
            raise ValueError("task_plan_observation_delivery_binding_invalid")
        packet = read_ref(session, matches[0]["packet_ref"])
    if (outcome.get("packet_sha256") != packet.get("packet_sha256")
            or outcome.get("frame") != packet.get("latest_observation")):
        raise ValueError("task_plan_observation_delivery_binding_invalid")
    frame = packet["latest_observation"]
    if not isinstance(frame, dict) or frame.get("role") != "observation":
        raise ValueError("task_plan_observation_delivery_frame_invalid")
    source = Path(frame["image_path"])
    path = source.resolve(strict=True)
    if (source.is_symlink() or not path.is_relative_to(session / "task-plan-observations")
            or not path.is_file() or path.stat().st_size > 20 * 1024 * 1024
            or {"path": path.relative_to(session).as_posix(), "sha256": frame["sha256"]}
                not in packet["input_evidence_refs"]):
        raise ValueError("task_plan_observation_delivery_path_invalid")
    raw = path.read_bytes()
    if len(raw) > 20 * 1024 * 1024 or sha256(raw).hexdigest() != frame["sha256"]:
        raise ValueError("task_plan_observation_delivery_hash_changed")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("task_plan_observation_delivery_png_invalid")
    with Image.open(BytesIO(raw)) as image:
        if image.format != "PNG" or image.width * image.height > 40_000_000:
            raise ValueError("task_plan_observation_delivery_png_invalid")
        image.verify()
    return raw, frame


def video_playback_images(session_dir, result):
    """按审核包顺序投递整条时序原图链，不触发新截图或输入。"""
    from .task_plan_review import validate_packet
    session = Path(session_dir).resolve(strict=True)
    packet = result.get("review_packet")
    if not isinstance(packet, dict) or packet.get("schema") != "review_packet.v4":
        raise ValueError("video_playback_delivery_binding_invalid")
    validate_packet(packet, result, session)
    delivered = []
    for item in packet["video_playback"]["samples"]:
        frame = item["frame"]
        source = Path(frame["image_path"])
        path = source.resolve(strict=True)
        if (source.is_symlink() or not path.is_relative_to(session)
                or path.stat().st_size > 20 * 1024 * 1024
                or {"path": path.relative_to(session).as_posix(), "sha256": frame["sha256"]}
                    not in packet["input_evidence_refs"]):
            raise ValueError("video_playback_delivery_path_invalid")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != frame["sha256"]:
            raise ValueError("video_playback_delivery_hash_changed")
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG" or image.width * image.height > 40_000_000:
                raise ValueError("video_playback_delivery_png_invalid")
            image.verify()
        delivered.append((raw, frame, item["elapsed_ms"]))
    return delivered
