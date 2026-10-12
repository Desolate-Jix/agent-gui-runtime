"""追加只读观察：复用原 owner 与正式采集，保留原动作的 after 证据。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from math import isfinite
from pathlib import Path
import re
from time import monotonic

from PIL import Image, UnidentifiedImageError

from app.learning_memory.memory_observation import capture_memory_observation
from .task_plan_contract import validate_task_plan_target


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_CAPTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$"}
_RESERVED.update(f"{prefix}{index}" for prefix in ("COM", "LPT") for index in range(10))
_MAX_BYTES = 20 * 1024 * 1024
_MAX_PIXELS = 40_000_000


class FollowupObservationError(ValueError):
    """只暴露具名原因和异常类型，不回显采集器的私有错误文本。"""

    def __init__(self, reason, *, error_type=None):
        self.reason_code = "task_plan_observation_" + reason
        self.error_type = error_type
        super().__init__(self.reason_code)


def _identity(value, *, reason):
    try:
        return validate_task_plan_target(value)
    except (ValueError, TypeError) as error:
        raise FollowupObservationError(reason, error_type=type(error).__name__) from None


def _metadata(frame):
    if not isinstance(frame, dict):
        raise FollowupObservationError("frame_invalid")
    value = deepcopy(frame)
    capture_id = value.get("capture_id")
    digest = value.get("sha256")
    image_path = value.get("image_path")
    rect, size = value.get("window_rect"), value.get("image_size")
    if (not isinstance(capture_id, str) or not _CAPTURE_ID.fullmatch(capture_id)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(image_path, str) or not image_path or len(image_path) > 32768
            or "://" in image_path or not Path(image_path).is_absolute()
            or not isinstance(rect, (list, tuple)) or len(rect) != 4
            or any(type(item) is not int for item in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]
            or not isinstance(size, dict) or set(size) != {"width", "height"}
            or any(type(size[key]) is not int or size[key] <= 0 for key in size)
            or size != {"width": rect[2] - rect[0], "height": rect[3] - rect[1]}
            or size["width"] * size["height"] > _MAX_PIXELS):
        raise FollowupObservationError("frame_invalid")
    value["window_identity"] = _identity(value.get("window_identity"), reason="frame_invalid")
    value["window_rect"] = list(rect)
    return value


def _png(frame, *, original=False):
    try:
        source = Path(frame["image_path"])
        if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_BYTES:
            raise FollowupObservationError("capture_png_invalid")
        raw = source.read_bytes()
        if len(raw) > _MAX_BYTES or sha256(raw).hexdigest() != frame["sha256"]:
            raise FollowupObservationError("capture_hash_changed")
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise FollowupObservationError("capture_png_invalid")
        with Image.open(BytesIO(raw)) as image:
            if image.format != "PNG":
                raise FollowupObservationError("capture_png_invalid")
            if {"width": image.width, "height": image.height} != frame["image_size"]:
                raise FollowupObservationError("capture_size_changed")
            image.verify()
        return raw
    except FollowupObservationError as error:
        if not original:
            raise
        raise FollowupObservationError("original_evidence_invalid", error_type=type(error).__name__) from None
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        reason = "original_evidence_invalid" if original else "capture_png_invalid"
        raise FollowupObservationError(reason, error_type=type(error).__name__) from None


def _destination(root, observation_id, *, must_be_new=True):
    directory = root / "task-plan-observations"
    path = directory / (observation_id + ".png")
    try:
        if (root.is_symlink() or directory.is_symlink() or path.is_symlink()
                or root.exists() and not root.is_dir()
                or directory.exists() and not directory.is_dir()
                or not path.resolve().is_relative_to(root)
                or directory.resolve() != directory):
            raise FollowupObservationError("path_invalid")
        if must_be_new and path.exists():
            raise FollowupObservationError("id_duplicate")
    except OSError as error:
        raise FollowupObservationError("path_invalid", error_type=type(error).__name__) from None
    return path


def capture_followup(coordinator, *, session_dir, target_identity, original_frame,
                     observation_id, cancelled, remaining_seconds):
    """预算只能拒绝同步调用的晚返回，不能硬中断底层截图或 COM。"""
    if (not isinstance(observation_id, str) or not _IDENTIFIER.fullmatch(observation_id)
            or observation_id.upper() in _RESERVED):
        raise FollowupObservationError("id_invalid")
    if not callable(cancelled) or not callable(remaining_seconds):
        raise FollowupObservationError("callbacks_invalid")
    started = monotonic()
    deadline = None

    def check():
        nonlocal deadline
        try:
            stopped = cancelled()
        except Exception as error:
            raise FollowupObservationError("cancellation_check_failed", error_type=type(error).__name__) from None
        if type(stopped) is not bool:
            raise FollowupObservationError("cancellation_invalid")
        if stopped:
            raise FollowupObservationError("cancelled")
        try:
            remaining = remaining_seconds()
        except Exception as error:
            raise FollowupObservationError("budget_check_failed", error_type=type(error).__name__) from None
        if type(remaining) not in (int, float) or not isfinite(remaining):
            raise FollowupObservationError("budget_invalid")
        if remaining <= 0:
            raise FollowupObservationError("timeout")
        if deadline is None:
            deadline = started + remaining
        if monotonic() >= deadline:
            raise FollowupObservationError("timeout")

    check()
    identity = _identity(target_identity, reason="identity_invalid")
    original = _metadata(original_frame)
    if original["window_identity"] != identity:
        raise FollowupObservationError("identity_changed")
    original_raw = _png(original, original=True)
    try:
        if not isinstance(session_dir, (str, Path)) or not str(session_dir):
            raise FollowupObservationError("path_invalid")
        supplied_root = Path(session_dir)
        if supplied_root.is_symlink():
            raise FollowupObservationError("path_invalid")
        root = supplied_root.resolve()
        destination = _destination(root, observation_id)
    except (OSError, ValueError) as error:
        if isinstance(error, FollowupObservationError):
            raise
        raise FollowupObservationError("path_invalid", error_type=type(error).__name__) from None
    owner = getattr(coordinator, "_owner", None)
    if not callable(getattr(owner, "call", None)):
        raise FollowupObservationError("owner_unavailable")

    def capture():
        check()
        _destination(root, observation_id)
        result = capture_memory_observation(coordinator, identity["handle"], identity["process_id"], recipe=None)
        check()
        return result

    check()
    capture_started = monotonic()
    try:
        result = owner.call(capture)
    except FollowupObservationError:
        raise
    except Exception as error:
        raise FollowupObservationError("capture_failed", error_type=type(error).__name__) from None
    capture_elapsed_ms = max(0, round((monotonic() - capture_started) * 1000))
    check()
    if not isinstance(result, (list, tuple)) or len(result) != 2:
        raise FollowupObservationError("frame_invalid")
    current = _metadata(result[0])
    if current["window_identity"] != identity or current["window_identity"] != original["window_identity"]:
        raise FollowupObservationError("identity_changed")
    if current["window_rect"] != original["window_rect"] or current["image_size"] != original["image_size"]:
        raise FollowupObservationError("geometry_changed")
    if current["capture_id"] == original["capture_id"]:
        raise FollowupObservationError("capture_stale")
    raw = _png(current)
    try:
        reused = Path(current["image_path"]).samefile(original["image_path"])
    except OSError as error:
        raise FollowupObservationError("capture_png_invalid", error_type=type(error).__name__) from None
    if reused:
        raise FollowupObservationError("capture_reused")
    if _png(original, original=True) != original_raw:
        raise FollowupObservationError("original_evidence_invalid")
    check()
    _destination(root, observation_id)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _destination(root, observation_id)
        check()
        # 独占创建保留先到达的字节；失败后留下的文件不会被重试覆写。
        with destination.open("xb") as output:
            output.write(raw)
        if destination.read_bytes() != raw:
            raise FollowupObservationError("persisted_evidence_changed")
    except FileExistsError:
        raise FollowupObservationError("id_duplicate") from None
    except OSError as error:
        raise FollowupObservationError("persist_failed", error_type=type(error).__name__) from None
    check()
    _destination(root, observation_id, must_be_new=False)
    if _png(original, original=True) != original_raw:
        raise FollowupObservationError("original_evidence_invalid")
    check()
    frame = {"capture_id": current["capture_id"], "sha256": current["sha256"],
        "image_path": str(destination), "window_identity": deepcopy(current["window_identity"]), "role": "observation"}
    return {"observation_id": observation_id, "frame": frame, "capture_elapsed_ms": capture_elapsed_ms}


__all__ = ["FollowupObservationError", "capture_followup"]
