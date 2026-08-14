from __future__ import annotations

from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import warnings
from typing import Any

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError


SCOPED_CAPTURE_CONTRACT_VERSION = "scoped_learning_capture_v1"

_ACCEPTED_STOP_REASONS = {
    "reached_bottom",
    "no_new_content",
    "wrong_scope",
    "blocked_surface",
    "max_captures",
    "cancelled",
}
_INCOMPLETE_STOP_REASONS = {
    "max_captures",
    "cancelled",
    "wrong_scope",
    "blocked_surface",
}
_MAX_OVERLAP_SEARCH = 512
_MIN_OVERLAP_ROWS = 16
_MIN_EVIDENCE_PIXELS = 20
_MIN_INFORMATIVE_TILE_STDDEV = 4.0
_MIN_INFORMATIVE_TILE_RATIO = 0.10
_MIN_TILE_VARIATION_FRACTION = 0.05
_INFORMATION_TILE_WIDTH = 16
_INFORMATION_TILE_HEIGHT = 16
_OVERLAP_SAMPLE_WIDTH = 128
_OVERLAP_DIAGNOSTIC_CANDIDATE_LIMIT = 4
_OVERLAP_ROW_DIGEST_SIZE = 16
_COMPOSITE_NAME = "scoped_capture_composite.png"
_MANIFEST_NAME = "scoped_capture_manifest.json"
_STAGING_PREFIX = ".scoped_capture_staging_"


class ScopedCaptureError(ValueError):
    pass


class ScopedCaptureCompositionError(RuntimeError):
    pass


def build_scoped_capture_artifact(
    *,
    segment_records: list[dict[str, Any]],
    output_dir: str | Path,
    roi: dict[str, int],
    viewport: dict[str, int],
    stop_reason: str,
) -> dict[str, Any]:
    """Build a read-only learn-mode artifact from already captured segments."""
    _validate_stop_reason(stop_reason)
    _validate_roi_and_viewport(roi, viewport)
    if not isinstance(segment_records, list) or not segment_records:
        raise ScopedCaptureError("at least one segment record is required")

    artifact_dir = _resolve_output_dir(output_dir)
    roi_manifest = _json_compatible(roi, "roi")
    viewport_manifest = _json_compatible(viewport, "viewport")
    loaded_segments = [_load_segment(index, record) for index, record in enumerate(segment_records)]
    segment_entries: list[dict[str, Any]] = []
    accepted_segments: list[tuple[int, Image.Image]] = []
    duplicate_sources: dict[str, int] = {}

    for loaded in loaded_segments:
        duplicate_of = duplicate_sources.get(loaded["sha256"])
        accepted = duplicate_of is None
        if accepted:
            duplicate_sources[loaded["sha256"]] = loaded["index"]
            accepted_segments.append((loaded["index"], loaded["image"]))
        segment_entries.append(
            {
                "index": loaded["index"],
                "image_path": str(loaded["image_path"]),
                "sha256": loaded["sha256"],
                "width": loaded["image"].width,
                "height": loaded["image"].height,
                "accepted": accepted,
                "duplicate_of": duplicate_of,
                "capture_id": _json_compatible(loaded["record"].get("capture_id"), "capture_id"),
                "scroll_trace_path": _json_compatible(loaded["record"].get("scroll_trace_path"), "scroll_trace_path"),
                "scroll_effect": _json_compatible(loaded["record"].get("scroll_effect"), "scroll_effect"),
            }
        )

    try:
        composite, overlap_evidence = _stitch_accepted_segments(accepted_segments)
    except ScopedCaptureError:
        raise
    except Exception as exc:
        raise ScopedCaptureCompositionError("failed to compose scoped capture artifact") from exc
    composite_path = artifact_dir / _COMPOSITE_NAME
    manifest_path = artifact_dir / _MANIFEST_NAME
    manifest = {
        "contract_version": SCOPED_CAPTURE_CONTRACT_VERSION,
        "capture_mode": "scoped_long",
        "roi": roi_manifest,
        "viewport": viewport_manifest,
        "segments": segment_entries,
        "overlap_evidence": overlap_evidence,
        "composite_path": str(composite_path),
        "manifest_path": str(manifest_path),
        "stop_reason": stop_reason,
        "content_completeness": _content_completeness(stop_reason),
        "historical_coordinates_are_priors": True,
        "artifact_is_authorization": False,
    }
    manifest_bytes = _serialize_manifest(manifest)
    _publish_artifact_directory(artifact_dir=artifact_dir, composite=composite, manifest_bytes=manifest_bytes)
    return manifest


def _resolve_output_dir(output_dir: str | Path) -> Path:
    try:
        return Path(output_dir).expanduser().resolve()
    except Exception as exc:
        raise ScopedCaptureCompositionError("failed to resolve scoped capture output_dir") from exc


def _serialize_manifest(manifest: dict[str, Any]) -> bytes:
    try:
        text = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        return text.encode("utf-8", errors="strict")
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ScopedCaptureError("manifest must be strictly UTF-8 JSON-serializable") from exc


def _publish_artifact_directory(*, artifact_dir: Path, composite: Image.Image, manifest_bytes: bytes) -> None:
    staging_dir: Path | None = None
    publish_error: Exception | None = None
    try:
        if artifact_dir.exists():
            raise ScopedCaptureCompositionError("output_dir must be new and must not already exist")
        artifact_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=artifact_dir.parent))
        _write_composite(staging_dir / _COMPOSITE_NAME, composite)
        _write_bytes(staging_dir / _MANIFEST_NAME, manifest_bytes)
        os.rename(staging_dir, artifact_dir)
        staging_dir = None
    except ScopedCaptureCompositionError:
        raise
    except Exception as exc:
        publish_error = exc
    if publish_error is None:
        return
    if staging_dir is not None:
        try:
            shutil.rmtree(staging_dir)
        except Exception as cleanup_error:
            raise ScopedCaptureCompositionError(
                "failed to publish scoped capture artifact; staging cleanup failed"
            ) from cleanup_error
    raise ScopedCaptureCompositionError("failed to publish scoped capture artifact") from publish_error

def _write_composite(path: Path, composite: Image.Image) -> None:
    buffer = BytesIO()
    composite.save(buffer, format="PNG")
    _write_bytes(path, buffer.getvalue())


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _json_compatible(value: Any, field_name: str, active_container_ids: set[int] | None = None) -> Any:
    active_container_ids = active_container_ids if active_container_ids is not None else set()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ScopedCaptureError(f"{field_name} must not contain NaN or infinity")
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, dict)):
        container_id = id(value)
        if container_id in active_container_ids:
            raise ScopedCaptureError(f"{field_name} must not contain cyclic containers")
        active_container_ids.add(container_id)
        try:
            if isinstance(value, list):
                return [_json_compatible(item, field_name, active_container_ids) for item in value]
            if isinstance(value, tuple):
                return [_json_compatible(item, field_name, active_container_ids) for item in value]
            if not all(isinstance(key, str) for key in value):
                raise ScopedCaptureError(f"{field_name} must use string dictionary keys")
            return {key: _json_compatible(item, field_name, active_container_ids) for key, item in value.items()}
        finally:
            active_container_ids.remove(container_id)
    raise ScopedCaptureError(f"{field_name} must be JSON-compatible")


def _load_segment(index: int, record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or "image_path" not in record or not record["image_path"]:
        raise ScopedCaptureError(f"segment {index} path <missing>: image_path is required")
    try:
        image_path = Path(record["image_path"]).expanduser().resolve()
    except (OSError, TypeError, ValueError) as exc:
        raise ScopedCaptureError(f"segment {index} path {record['image_path']!r}: invalid image path") from exc
    try:
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        raw_bytes = image_path.read_bytes()
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw_bytes)) as source:
                source.load()
                image = source.convert("RGB")
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ScopedCaptureError(f"segment {index} path {image_path}: unreadable or non-image segment") from exc

    return {
        "index": index,
        "record": record,
        "image_path": image_path,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "image": image,
    }


def _stitch_accepted_segments(accepted_segments: list[tuple[int, Image.Image]]) -> tuple[Image.Image, list[dict[str, Any]]]:
    first_index, first_image = accepted_segments[0]
    pieces: list[tuple[Image.Image, int]] = [(first_image, 0)]
    overlap_evidence: list[dict[str, Any]] = []
    previous_index = first_index
    previous_image = first_image

    for current_index, current_image in accepted_segments[1:]:
        overlap, mean_absolute_error, confidence = _estimate_vertical_overlap(previous_image, current_image)
        overlap_evidence.append(
            {
                "from_index": previous_index,
                "to_index": current_index,
                "overlap_pixels": overlap,
                "mean_absolute_error": mean_absolute_error,
                "confidence": confidence,
            }
        )
        pieces.append((current_image, overlap))
        previous_index = current_index
        previous_image = current_image

    composite_width = max(image.width for image, _ in pieces)
    composite_height = sum(image.height - overlap for image, overlap in pieces)
    composite = Image.new("RGB", (composite_width, composite_height))
    offset_y = 0
    for image, overlap in pieces:
        composite.paste(image.crop((0, overlap, image.width, image.height)), (0, offset_y))
        offset_y += image.height - overlap
    return composite, overlap_evidence


def _estimate_vertical_overlap(previous: Image.Image, current: Image.Image) -> tuple[int, float, str]:
    if previous.size != current.size:
        return 0, 0.0, "none"
    maximum_overlap = min(previous.height - _MIN_OVERLAP_ROWS, _MAX_OVERLAP_SEARCH)
    if maximum_overlap < _MIN_OVERLAP_ROWS:
        return 0, 0.0, "none"

    previous_gray = previous.convert("L")
    current_gray = current.convert("L")
    exact_candidates = _exact_overlap_candidates(
        previous,
        current,
        maximum_overlap=maximum_overlap,
    )
    if exact_candidates:
        if (
            _cannot_contain_informative_tile(previous_gray)
            or _cannot_contain_informative_tile(current_gray)
        ):
            return 0, 0.0, "none"
        plausible: list[int] = []
        for overlap in exact_candidates:
            previous_gray_strip = previous_gray.crop(
                (0, previous.height - overlap, previous.width, previous.height)
            )
            current_gray_strip = current_gray.crop((0, 0, current.width, overlap))
            if (
                previous.width * overlap >= _MIN_EVIDENCE_PIXELS
                and _informative_tile_ratio(previous_gray_strip)
                >= _MIN_INFORMATIVE_TILE_RATIO
                and _informative_tile_ratio(current_gray_strip)
                >= _MIN_INFORMATIVE_TILE_RATIO
            ):
                plausible.append(overlap)
                if len(plausible) > 1:
                    return 0, 0.0, "none"
        if plausible:
            return plausible[0], 0.0, "high"
        return 0, 0.0, "none"

    best_measured = _best_measured_overlap(
        previous_gray,
        current_gray,
        maximum_overlap=maximum_overlap,
    )
    if best_measured is None:
        return 0, 0.0, "none"
    return 0, round(float(best_measured["mean_absolute_error"]), 6), "none"


def _exact_overlap_candidates(
    previous: Image.Image,
    current: Image.Image,
    *,
    maximum_overlap: int,
) -> list[int]:
    previous_rows = _row_digests(previous)
    current_rows = _row_digests(current)
    candidates: list[int] = []
    for overlap in range(_MIN_OVERLAP_ROWS, maximum_overlap + 1):
        if previous_rows[-overlap:] != current_rows[:overlap]:
            continue
        previous_strip = previous.crop(
            (0, previous.height - overlap, previous.width, previous.height)
        )
        current_strip = current.crop((0, 0, current.width, overlap))
        if ImageChops.difference(previous_strip, current_strip).getbbox() is None:
            candidates.append(overlap)
    return candidates


def _row_digests(image: Image.Image) -> list[bytes]:
    raw = image.tobytes()
    row_stride = image.width * len(image.getbands())
    raw_view = memoryview(raw)
    return [
        hashlib.blake2b(
            raw_view[offset : offset + row_stride],
            digest_size=_OVERLAP_ROW_DIGEST_SIZE,
        ).digest()
        for offset in range(0, len(raw), row_stride)
    ]


def _best_measured_overlap(
    previous_gray: Image.Image,
    current_gray: Image.Image,
    *,
    maximum_overlap: int,
) -> dict[str, float | int] | None:
    sample_width = min(previous_gray.width, _OVERLAP_SAMPLE_WIDTH)
    if sample_width != previous_gray.width:
        previous_sample = previous_gray.resize(
            (sample_width, previous_gray.height),
            Image.Resampling.BOX,
        )
        current_sample = current_gray.resize(
            (sample_width, current_gray.height),
            Image.Resampling.BOX,
        )
    else:
        previous_sample = previous_gray
        current_sample = current_gray

    sampled: list[dict[str, float | int]] = []
    for overlap in range(_MIN_OVERLAP_ROWS, maximum_overlap + 1):
        previous_strip = previous_sample.crop(
            (0, previous_sample.height - overlap, sample_width, previous_sample.height)
        )
        current_strip = current_sample.crop((0, 0, sample_width, overlap))
        difference = ImageChops.difference(previous_strip, current_strip)
        sampled.append(
            {
                "overlap": overlap,
                "mean_absolute_error": float(ImageStat.Stat(difference).mean[0]),
            }
        )
    sampled.sort(
        key=lambda item: (
            float(item["mean_absolute_error"]),
            -int(item["overlap"]),
        )
    )

    measured: list[dict[str, float | int]] = []
    for candidate in sampled[:_OVERLAP_DIAGNOSTIC_CANDIDATE_LIMIT]:
        overlap = int(candidate["overlap"])
        previous_strip = previous_gray.crop(
            (0, previous_gray.height - overlap, previous_gray.width, previous_gray.height)
        )
        current_strip = current_gray.crop((0, 0, current_gray.width, overlap))
        difference = ImageChops.difference(previous_strip, current_strip)
        measured.append(
            {
                "overlap": overlap,
                "mean_absolute_error": float(ImageStat.Stat(difference).mean[0]),
            }
        )
    if not measured:
        return None
    return min(
        measured,
        key=lambda item: (
            float(item["mean_absolute_error"]),
            -int(item["overlap"]),
        ),
    )


def _cannot_contain_informative_tile(image: Image.Image) -> bool:
    minimum, maximum = image.getextrema()
    return (float(maximum) - float(minimum)) / 2.0 < _MIN_INFORMATIVE_TILE_STDDEV


def _informative_tile_ratio(image: Image.Image) -> float:
    total_tiles = 0
    informative_tiles = 0
    for top in range(0, image.height, _INFORMATION_TILE_HEIGHT):
        for left in range(0, image.width, _INFORMATION_TILE_WIDTH):
            tile = image.crop(
                (
                    left,
                    top,
                    min(left + _INFORMATION_TILE_WIDTH, image.width),
                    min(top + _INFORMATION_TILE_HEIGHT, image.height),
                )
            )
            total_tiles += 1
            tile_stddev = math.sqrt(float(ImageStat.Stat(tile).var[0]))
            tile_pixels = tile.width * tile.height
            dominant_pixel_count = max(tile.histogram()) if tile_pixels else 0
            variation_fraction = 1.0 - (dominant_pixel_count / tile_pixels) if tile_pixels else 0.0
            if (
                tile_stddev >= _MIN_INFORMATIVE_TILE_STDDEV
                and variation_fraction >= _MIN_TILE_VARIATION_FRACTION
            ):
                informative_tiles += 1
    return informative_tiles / total_tiles if total_tiles else 0.0


def _validate_roi_and_viewport(roi: Any, viewport: Any) -> None:
    if not isinstance(viewport, dict):
        raise ScopedCaptureError("viewport must be a dictionary")
    viewport_width = _positive_int(viewport, "width", "viewport")
    viewport_height = _positive_int(viewport, "height", "viewport")
    if not isinstance(roi, dict):
        raise ScopedCaptureError("roi must be a dictionary")
    roi_x = _nonnegative_int(roi, "x", "roi")
    roi_y = _nonnegative_int(roi, "y", "roi")
    roi_width = _positive_int(roi, "width", "roi")
    roi_height = _positive_int(roi, "height", "roi")
    if roi_x + roi_width > viewport_width or roi_y + roi_height > viewport_height:
        raise ScopedCaptureError("roi must be fully within viewport")


def _positive_int(values: dict[str, Any], key: str, label: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ScopedCaptureError(f"{label}.{key} must be a positive integer")
    return value


def _nonnegative_int(values: dict[str, Any], key: str, label: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScopedCaptureError(f"{label}.{key} must be a non-negative integer")
    return value


def _validate_stop_reason(stop_reason: str) -> None:
    if not isinstance(stop_reason, str) or stop_reason not in _ACCEPTED_STOP_REASONS:
        raise ScopedCaptureError(f"unsupported stop_reason: {stop_reason!r}")


def _content_completeness(stop_reason: str) -> dict[str, str]:
    if stop_reason == "reached_bottom":
        return {"status": "complete", "reason": stop_reason}
    if stop_reason in _INCOMPLETE_STOP_REASONS:
        return {"status": "incomplete", "reason": stop_reason}
    return {"status": "unknown", "reason": stop_reason}
