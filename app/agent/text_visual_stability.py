"""仅为已审核文本字段提供局部像素稳定性证明，不授予输入权限。"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import math
import re
from typing import Any, Mapping

from PIL import Image, ImageChops

from app.agent.text_field_evidence import (
    TextFieldExpectation,
    TextFieldIdentity,
    TextFieldSnapshot,
    validate_text_field_snapshot_reference,
)
from app.agent.text_parameters import (
    ResolvedTextParameters,
    ReviewedTextParameters,
    ReviewedTextSource,
)
from app.agent.automatic_safety_policy import validate_automatic_safety_interception


_POLICY = "fill_field_protected_pixels_v1"
_BORDER = 8
_MAX_CHANGED_PIXELS = 128
_MAX_CHANGED_EXTENT = 24
_MIN_DISTANCE = 64
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ATTESTATION_SEAL = object()


class TextVisualPixelsChanged(ValueError):
    """身份与图像完整性有效，但像素变化不满足文本字段局部策略。"""


class TextVisualStabilityAttestation:
    """只能由成功完成像素校验的 scope 签发。"""

    __slots__ = (
        "policy",
        "field_expectation_sha256",
        "before_evidence_sha256",
        "after_evidence_sha256",
        "before_screenshot_sha256",
        "after_screenshot_sha256",
        "protected_bbox",
        "protected_before_sha256",
        "protected_after_sha256",
        "changed_pixels",
        "changed_bbox",
        "_sealed",
        "automatic_safety_interception",
        "_uia_stability_json",
    )

    def __init__(
        self,
        *,
        _seal: object,
        field_expectation_sha256: str,
        before_evidence_sha256: str,
        after_evidence_sha256: str,
        before_screenshot_sha256: str,
        after_screenshot_sha256: str,
        protected_bbox: tuple[int, int, int, int],
        protected_before_sha256: str,
        protected_after_sha256: str,
        changed_pixels: int,
        changed_bbox: tuple[int, int, int, int] | None,
        automatic_safety_interception=True,
        uia_stability=None,
    ) -> None:
        if _seal is not _ATTESTATION_SEAL:
            raise TypeError("text visual stability attestation cannot be constructed directly")
        strict = validate_automatic_safety_interception(automatic_safety_interception)
        values = {
            "policy": _POLICY if strict else 'fill_field_pixels_observation_v1',
            "automatic_safety_interception": strict,
            "field_expectation_sha256": field_expectation_sha256,
            "before_evidence_sha256": before_evidence_sha256,
            "after_evidence_sha256": after_evidence_sha256,
            "before_screenshot_sha256": before_screenshot_sha256,
            "after_screenshot_sha256": after_screenshot_sha256,
            "protected_bbox": protected_bbox,
            "protected_before_sha256": protected_before_sha256,
            "protected_after_sha256": protected_after_sha256,
            "changed_pixels": changed_pixels,
            "changed_bbox": changed_bbox,
            "_sealed": _ATTESTATION_SEAL,
            "_uia_stability_json": _canonical_bytes(uia_stability),
        }
        for key, value in values.items():
            object.__setattr__(self, key, value)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("text visual stability attestation is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("text visual stability attestation is immutable")

    def to_reference(self) -> dict[str, Any]:
        self._require_sealed()
        uia_stability = self.uia_stability_reference
        return {
            "contract_version": ("text_visual_stability_attestation_v3" if uia_stability is not None else
                "text_visual_stability_attestation_v1" if self.automatic_safety_interception else "text_visual_stability_attestation_v2"),
            **({"uia_stability": uia_stability} if uia_stability is not None else {}),
            **({} if self.automatic_safety_interception else {'automatic_safety_interception': False}),
            "policy": self.policy,
            "field_expectation_sha256": self.field_expectation_sha256,
            "before_evidence_sha256": self.before_evidence_sha256,
            "after_evidence_sha256": self.after_evidence_sha256,
            "before_screenshot_sha256": self.before_screenshot_sha256,
            "after_screenshot_sha256": self.after_screenshot_sha256,
            "protected_bbox": list(self.protected_bbox),
            "protected_before_sha256": self.protected_before_sha256,
            "protected_after_sha256": self.protected_after_sha256,
            "changed_pixels": self.changed_pixels,
            "changed_bbox": list(self.changed_bbox) if self.changed_bbox is not None else None,
        }

    @property
    def uia_stability_reference(self):
        self._require_sealed()
        return json.loads(self._uia_stability_json)

    def validate_binding(
        self,
        original_evidence: Mapping[str, Any],
        current_evidence: Mapping[str, Any],
        field_expectation_reference: Mapping[str, Any],
        *, automatic_safety_interception=True,
    ) -> None:
        self._require_sealed()
        if validate_automatic_safety_interception(automatic_safety_interception) != self.automatic_safety_interception:
            raise ValueError('text visual stability mode differs from approved preview')
        if _digest(_stable_evidence(original_evidence)) != self.before_evidence_sha256:
            raise ValueError("text visual stability original evidence binding changed")
        if _digest(_stable_evidence(current_evidence)) != self.after_evidence_sha256:
            raise ValueError("text visual stability current evidence binding changed")
        if _digest_mapping(field_expectation_reference) != self.field_expectation_sha256:
            raise ValueError("text visual stability field expectation binding changed")

    def _require_sealed(self) -> None:
        if getattr(self, "_sealed", None) is not _ATTESTATION_SEAL:
            raise TypeError("text visual stability attestation is not trusted")


class TextVisualStabilityScope:
    """冻结批准帧和真实字段身份，并据此校验后续帧。"""

    __slots__ = (
        "_expectation",
        "_expectation_json",
        "_original_evidence_json",
        "_original_png_bytes",
        "automatic_safety_interception",
        "_original_uia_json",
    )

    def __init__(
        self,
        *,
        expectation: TextFieldExpectation,
        original_evidence: Mapping[str, Any],
        original_png_bytes: bytes,
        automatic_safety_interception=True,
        original_uia_snapshot=None,
    ) -> None:
        _validate_typed_expectation(expectation)
        object.__setattr__(self, 'automatic_safety_interception',
            validate_automatic_safety_interception(automatic_safety_interception))
        if type(original_png_bytes) is not bytes:
            raise TypeError("text visual stability original PNG must be immutable bytes")
        stable = _stable_evidence(original_evidence)
        _validate_field_binding(expectation, stable)
        _load_bound_png(original_png_bytes, stable)
        if original_uia_snapshot is not None:
            _uia_transition(expectation.before.identity, stable, stable,
                original_uia_snapshot, original_uia_snapshot)
        object.__setattr__(self, "_expectation", expectation)
        object.__setattr__(
            self,
            "_expectation_json",
            _canonical_bytes(expectation.to_reference()),
        )
        object.__setattr__(self, "_original_evidence_json", _canonical_bytes(stable))
        object.__setattr__(self, "_original_png_bytes", bytes(original_png_bytes))
        object.__setattr__(self, "_original_uia_json", _canonical_bytes(original_uia_snapshot))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("text visual stability scope is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("text visual stability scope is immutable")

    @property
    def expectation_reference(self) -> dict[str, Any]:
        self._revalidate_original()
        return json.loads(self._expectation_json.decode("utf-8"))

    def validate(
        self,
        *,
        current_evidence: Mapping[str, Any],
        current_png_bytes: bytes,
        current_uia_snapshot=None,
    ) -> TextVisualStabilityAttestation:
        original, original_image = self._revalidate_original()
        if type(current_png_bytes) is not bytes:
            raise TypeError("text visual stability current PNG must be immutable bytes")
        current = _stable_evidence(current_evidence)
        uia_stability = _validate_transition_binding(self._expectation, original, current,
            original_uia_snapshot=json.loads(self._original_uia_json), current_uia_snapshot=current_uia_snapshot)
        current_image = _load_bound_png(current_png_bytes, current)

        protected = _protected_bbox(
            self._expectation.before.identity.control_bbox,
            original_image.size,
        )
        crop_box = _xywh_to_box(protected)
        before_crop = original_image.crop(crop_box)
        after_crop = current_image.crop(crop_box)
        before_protected_sha = _pixel_sha256(before_crop)
        after_protected_sha = _pixel_sha256(after_crop)
        if self.automatic_safety_interception and ImageChops.difference(before_crop, after_crop).getbbox() is not None:
            raise TextVisualPixelsChanged("text visual stability protected field pixels changed")

        changed_pixels, changed_bbox = _bounded_background_delta(
            original_image,
            current_image,
            protected,
            automatic_safety_interception=self.automatic_safety_interception,
        )
        original_sha = sha256(self._original_png_bytes).hexdigest()
        current_sha = sha256(current_png_bytes).hexdigest()
        return TextVisualStabilityAttestation(
            _seal=_ATTESTATION_SEAL,
            field_expectation_sha256=sha256(self._expectation_json).hexdigest(),
            before_evidence_sha256=_digest(original),
            after_evidence_sha256=_digest(current),
            before_screenshot_sha256=original_sha,
            after_screenshot_sha256=current_sha,
            protected_bbox=protected,
            protected_before_sha256=before_protected_sha,
            protected_after_sha256=after_protected_sha,
            changed_pixels=changed_pixels,
            changed_bbox=changed_bbox,
            automatic_safety_interception=self.automatic_safety_interception,
            uia_stability=uia_stability,
        )

    def _revalidate_original(self) -> tuple[dict[str, Any], Image.Image]:
        _validate_typed_expectation(self._expectation)
        if _canonical_bytes(self._expectation.to_reference()) != self._expectation_json:
            raise ValueError("text visual stability typed field expectation changed")
        original = json.loads(self._original_evidence_json.decode("utf-8"))
        _validate_field_binding(self._expectation, original)
        image = _load_bound_png(self._original_png_bytes, original)
        return original, image


def verify_text_visual_stability_reference(
    reference: Mapping[str, Any],
    *,
    original_evidence: Mapping[str, Any],
    current_evidence: Mapping[str, Any],
    field_expectation_reference: Mapping[str, Any],
    original_png_bytes: bytes,
    current_png_bytes: bytes,
    automatic_safety_interception=True,
    original_uia_snapshot=None,
    current_uia_snapshot=None,
) -> None:
    """只读重算已封存证明；不会恢复可用于实时比较的强类型对象。"""

    if not isinstance(reference, Mapping):
        raise TypeError("text visual stability reference must be a mapping")
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    field_reference, identity, before_capture_id = _verified_field_reference(
        field_expectation_reference
    )
    original = _stable_evidence(original_evidence)
    current = _stable_evidence(current_evidence)
    _validate_reference_field_binding(identity, before_capture_id, original)
    uia_stability = _validate_reference_transition(identity, before_capture_id, original, current,
        original_uia_snapshot=original_uia_snapshot, current_uia_snapshot=current_uia_snapshot)
    if type(original_png_bytes) is not bytes or type(current_png_bytes) is not bytes:
        raise TypeError("text visual stability verification requires immutable PNG bytes")
    original_image = _load_bound_png(original_png_bytes, original)
    current_image = _load_bound_png(current_png_bytes, current)
    protected = _protected_bbox(identity.control_bbox, original_image.size)
    crop_box = _xywh_to_box(protected)
    before_crop = original_image.crop(crop_box)
    after_crop = current_image.crop(crop_box)
    if strict and ImageChops.difference(before_crop, after_crop).getbbox() is not None:
        raise TextVisualPixelsChanged("text visual stability protected field pixels changed")
    changed_pixels, changed_bbox = _bounded_background_delta(
        original_image, current_image, protected, automatic_safety_interception=strict,
    )
    expected = {
        "contract_version": ("text_visual_stability_attestation_v3" if uia_stability is not None else
            "text_visual_stability_attestation_v1" if strict else "text_visual_stability_attestation_v2"),
        **({"uia_stability": uia_stability} if uia_stability is not None else {}),
        **({} if strict else {'automatic_safety_interception': False}),
        "policy": _POLICY if strict else 'fill_field_pixels_observation_v1',
        "field_expectation_sha256": _digest(field_reference),
        "before_evidence_sha256": _digest(original),
        "after_evidence_sha256": _digest(current),
        "before_screenshot_sha256": sha256(original_png_bytes).hexdigest(),
        "after_screenshot_sha256": sha256(current_png_bytes).hexdigest(),
        "protected_bbox": list(protected),
        "protected_before_sha256": _pixel_sha256(before_crop),
        "protected_after_sha256": _pixel_sha256(after_crop),
        "changed_pixels": changed_pixels,
        "changed_bbox": list(changed_bbox) if changed_bbox is not None else None,
    }
    if _canonical_bytes(dict(reference)) != _canonical_bytes(expected):
        raise ValueError("text visual stability persisted reference differs from recomputed proof")


def _validate_typed_expectation(expectation: object) -> None:
    if type(expectation) is not TextFieldExpectation:
        raise TypeError("text visual stability requires a typed field expectation")
    before = expectation.before
    if type(before) is not TextFieldSnapshot or type(before.identity) is not TextFieldIdentity:
        raise TypeError("text visual stability requires a typed field snapshot")
    parameters = expectation.parameters
    if (
        type(parameters) is not ResolvedTextParameters
        or type(parameters.reviewed) is not ReviewedTextParameters
        or type(parameters.reviewed.content) is not ReviewedTextSource
    ):
        raise TypeError("text visual stability requires typed reviewed text parameters")
    if before.identity.target_field_id != parameters.reviewed.target_field_id:
        raise ValueError("text visual stability field identity differs from reviewed parameters")
    # 重新执行公共构造校验，避免仅凭对象类型信任被篡改的实例。
    identity = before.identity
    TextFieldIdentity(
        target_field_id=identity.target_field_id,
        window_handle=identity.window_handle,
        process_id=identity.process_id,
        process_create_time=identity.process_create_time,
        runtime_id=tuple(identity.runtime_id),
        window_rect=tuple(identity.window_rect),
        control_bbox=tuple(identity.control_bbox),
    )
    TextFieldSnapshot(
        identity=before.identity,
        capture_id=before.capture_id,
        read_id=before.read_id,
        observed_at_ns=before.observed_at_ns,
        source=before.source,
        value=before.value,
        selection=before.selection,
    )
    content = parameters.reviewed.content
    reviewed = ReviewedTextParameters(
        target_field_id=parameters.reviewed.target_field_id,
        content=ReviewedTextSource(kind=content.kind, value=content.value),
        clear_existing=parameters.reviewed.clear_existing,
        sensitive=parameters.reviewed.sensitive,
        submit=parameters.reviewed.submit,
        clipboard_policy=parameters.reviewed.clipboard_policy,
    )
    resolved = ResolvedTextParameters(reviewed=reviewed, text=parameters.text)
    TextFieldExpectation(before, resolved, expectation.expected_value)


def _stable_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise TypeError("text visual stability evidence must be a mapping")
    target = evidence.get("target")
    application = evidence.get("application")
    uia = evidence.get("uia")
    capture = evidence.get("capture")
    if not all(isinstance(value, Mapping) for value in (target, application, uia, capture)):
        raise ValueError("text visual stability evidence identity is incomplete")

    if set(target) != {"window_handle", "process_id", "rect"}:
        raise ValueError("text visual stability target identity is invalid")
    handle = _positive_int(target.get("window_handle"), "window handle")
    process_id = _positive_int(target.get("process_id"), "process ID")
    rect = _rect_mapping(target.get("rect"), "window rectangle")

    kind = application.get("kind")
    application_keys = {"kind", "executable_path", "process_create_time"}
    if kind == "web":
        application_keys.add("canonical_origin")
    elif kind != "native":
        raise ValueError("text visual stability application kind is invalid")
    if set(application) != application_keys:
        raise ValueError("text visual stability application identity is invalid")
    executable = application.get("executable_path")
    created = application.get("process_create_time")
    if not isinstance(executable, str) or not executable:
        raise ValueError("text visual stability executable identity is invalid")
    if type(created) not in (int, float) or not math.isfinite(created) or created <= 0:
        raise ValueError("text visual stability process creation time is invalid")
    app = dict(application)

    uia_keys = {"provider", "provider_version", "status", "control_count", "snapshot_sha256"}
    if set(uia) != uia_keys:
        raise ValueError("text visual stability UIA identity is invalid")
    if any(not isinstance(uia.get(key), str) or not uia[key] for key in ("provider", "provider_version", "status")):
        raise ValueError("text visual stability UIA identity is invalid")
    if type(uia.get("control_count")) is not int or uia["control_count"] < 0:
        raise ValueError("text visual stability UIA control count is invalid")
    _sha_value(uia.get("snapshot_sha256"), "UIA snapshot")

    capture_keys = {
        "capture_id",
        "capture_started_ns",
        "capture_clock_id",
        "viewport_size",
        "screenshot_sha256",
    }
    if not capture_keys.issubset(capture):
        raise ValueError("text visual stability capture identity is incomplete")
    capture_id = capture.get("capture_id")
    clock_id = capture.get("capture_clock_id")
    if not isinstance(capture_id, str) or not capture_id or len(capture_id) > 256:
        raise ValueError("text visual stability capture ID is invalid")
    if not isinstance(clock_id, str) or not clock_id or len(clock_id) > 128:
        raise ValueError("text visual stability capture clock is invalid")
    started = _positive_int(capture.get("capture_started_ns"), "capture start")
    viewport = _viewport(capture.get("viewport_size"))
    screenshot = _sha_value(capture.get("screenshot_sha256"), "screenshot")
    return {
        "target": {"window_handle": handle, "process_id": process_id, "rect": rect},
        "application": app,
        "uia": dict(uia),
        "capture": {
            "capture_id": capture_id,
            "capture_started_ns": started,
            "capture_clock_id": clock_id,
            "viewport_size": viewport,
            "screenshot_sha256": screenshot,
        },
    }


def _validate_field_binding(expectation: TextFieldExpectation, evidence: Mapping[str, Any]) -> None:
    identity = expectation.before.identity
    target = evidence["target"]
    application = evidence["application"]
    capture = evidence["capture"]
    rect = target["rect"]
    window_rect = (rect["x"], rect["y"], rect["width"], rect["height"])
    if (
        target["window_handle"] != identity.window_handle
        or target["process_id"] != identity.process_id
        or window_rect != identity.window_rect
        or application["process_create_time"] != identity.process_create_time
        or capture["capture_id"] != expectation.before.capture_id
        or (capture["viewport_size"]["width"], capture["viewport_size"]["height"])
        != identity.window_rect[2:]
    ):
        raise ValueError("text visual stability field does not bind to the original capture")


def _validate_transition_binding(
    expectation: TextFieldExpectation,
    original: Mapping[str, Any],
    current: Mapping[str, Any],
    *, original_uia_snapshot=None, current_uia_snapshot=None,
):
    _validate_field_binding(expectation, original)
    if current["target"] != original["target"]:
        raise ValueError("text visual stability target identity changed")
    if current["application"] != original["application"]:
        raise ValueError("text visual stability application identity changed")
    uia_stability = _uia_transition(expectation.before.identity, original, current,
        original_uia_snapshot, current_uia_snapshot)
    before, after = original["capture"], current["capture"]
    if (
        after["capture_id"] == before["capture_id"]
        or after["capture_started_ns"] <= before["capture_started_ns"]
        or after["capture_clock_id"] != before["capture_clock_id"]
        or after["viewport_size"] != before["viewport_size"]
    ):
        raise ValueError("text visual stability capture binding changed")
    return uia_stability


def _uia_transition(identity, original, current, original_uia, current_uia):
    if original_uia is None and current_uia is None:
        if current['uia'] != original['uia']:
            raise ValueError('text visual stability UIA identity changed')
        return None
    if original_uia is None or current_uia is None:
        raise ValueError('text visual stability requires both full UIA snapshots')
    from app.agent.text_uia_stability import compare_fill_uia_context
    return compare_fill_uia_context(field_identity=identity, original_evidence=original,
        original_uia=original_uia, current_evidence=current, current_uia=current_uia)


def _verified_field_reference(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], TextFieldIdentity, str]:
    if not isinstance(value, Mapping):
        raise TypeError("text visual stability field reference must be a mapping")
    try:
        result = json.loads(_canonical_bytes(dict(value)).decode("utf-8"))
        if set(result) != {
            "contract_version",
            "before",
            "text_execution_ref",
            "expected_value_sha256",
            "expected_value_length",
        } or result["contract_version"] != "text_field_expectation_reference_v1":
            raise ValueError()
        before = validate_text_field_snapshot_reference(result["before"])
        execution = result["text_execution_ref"]
        if (
            not isinstance(execution, dict)
            or set(execution)
            != {"contract_version", "parameters_sha256", "text_sha256", "text_length"}
            or execution["contract_version"] != "text_execution_reference_v1"
        ):
            raise ValueError()
        for item, hash_key, length_key in (
            (execution, "text_sha256", "text_length"),
            (result, "expected_value_sha256", "expected_value_length"),
        ):
            _sha_value(item.get(hash_key), hash_key)
            if type(item.get(length_key)) is not int or not 0 <= item[length_key] <= 32768:
                raise ValueError()
            if item[length_key] == 0 and item[hash_key] != sha256(b"").hexdigest():
                raise ValueError()
        _sha_value(execution.get("parameters_sha256"), "text parameters")
        identity_value = before["identity"]
        identity = TextFieldIdentity(
            target_field_id=identity_value["target_field_id"],
            window_handle=identity_value["window_handle"],
            process_id=identity_value["process_id"],
            process_create_time=identity_value["process_create_time"],
            runtime_id=tuple(identity_value["runtime_id"]),
            window_rect=tuple(identity_value["window_rect"]),
            control_bbox=tuple(identity_value["control_bbox"]),
        )
        result["before"] = before
        return result, identity, before["capture_id"]
    except (KeyError, TypeError, ValueError, OverflowError, json.JSONDecodeError):
        raise ValueError("text visual stability field reference is invalid") from None


def _validate_reference_field_binding(
    identity: TextFieldIdentity,
    before_capture_id: str,
    evidence: Mapping[str, Any],
) -> None:
    target = evidence["target"]
    application = evidence["application"]
    capture = evidence["capture"]
    rect = target["rect"]
    if (
        target["window_handle"] != identity.window_handle
        or target["process_id"] != identity.process_id
        or (rect["x"], rect["y"], rect["width"], rect["height"])
        != identity.window_rect
        or application["process_create_time"] != identity.process_create_time
        or capture["capture_id"] != before_capture_id
        or (capture["viewport_size"]["width"], capture["viewport_size"]["height"])
        != identity.window_rect[2:]
    ):
        raise ValueError("text visual stability reference field does not bind to original capture")


def _validate_reference_transition(
    identity: TextFieldIdentity,
    before_capture_id: str,
    original: Mapping[str, Any],
    current: Mapping[str, Any],
    *, original_uia_snapshot=None, current_uia_snapshot=None,
):
    _validate_reference_field_binding(identity, before_capture_id, original)
    if (
        current["target"] != original["target"]
        or current["application"] != original["application"]
    ):
        raise ValueError("text visual stability persisted identity changed")
    uia_stability = _uia_transition(identity, original, current,
        original_uia_snapshot, current_uia_snapshot)
    before, after = original["capture"], current["capture"]
    if (
        after["capture_id"] == before["capture_id"]
        or after["capture_started_ns"] <= before["capture_started_ns"]
        or after["capture_clock_id"] != before["capture_clock_id"]
        or after["viewport_size"] != before["viewport_size"]
    ):
        raise ValueError("text visual stability persisted capture binding changed")
    return uia_stability


def _load_bound_png(png_bytes: bytes, evidence: Mapping[str, Any]) -> Image.Image:
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("text visual stability image must be PNG")
    actual_sha = sha256(png_bytes).hexdigest()
    if actual_sha != evidence["capture"]["screenshot_sha256"]:
        raise ValueError("text visual stability PNG hash differs from evidence")
    try:
        with Image.open(BytesIO(png_bytes)) as opened:
            if opened.format != "PNG":
                raise ValueError("text visual stability image must be PNG")
            image = opened.convert("RGB")
            image.load()
    except (OSError, ValueError) as error:
        raise ValueError("text visual stability PNG is invalid") from error
    viewport = evidence["capture"]["viewport_size"]
    if image.size != (viewport["width"], viewport["height"]):
        raise ValueError("text visual stability image size differs from viewport")
    return image


def _protected_bbox(
    field_bbox: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x, y, width, height = field_bbox
    left = max(0, x - _BORDER)
    top = max(0, y - _BORDER)
    right = min(image_size[0], x + width + _BORDER)
    bottom = min(image_size[1], y + height + _BORDER)
    if right <= left or bottom <= top:
        raise ValueError("text visual stability protected field geometry is invalid")
    return left, top, right - left, bottom - top


def _bounded_background_delta(
    before: Image.Image,
    after: Image.Image,
    protected: tuple[int, int, int, int],
    *, automatic_safety_interception=True,
) -> tuple[int, tuple[int, int, int, int] | None]:
    strict = validate_automatic_safety_interception(automatic_safety_interception)
    difference = ImageChops.difference(before, after)
    union = difference.getbbox()
    if union is None:
        return 0, None
    left, top, right, bottom = union
    width, height = right - left, bottom - top
    if not strict:
        channels = difference.split()
        mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        return before.width * before.height - mask.histogram()[0], (left, top, width, height)
    if width > _MAX_CHANGED_EXTENT or height > _MAX_CHANGED_EXTENT:
        raise TextVisualPixelsChanged("text visual stability background change is too dispersed")
    changed = []
    for offset_y, row_y in enumerate(range(top, bottom)):
        for offset_x, row_x in enumerate(range(left, right)):
            if difference.getpixel((row_x, row_y)) != (0, 0, 0):
                changed.append((offset_x, offset_y))
    if not changed or len(changed) > _MAX_CHANGED_PIXELS:
        raise TextVisualPixelsChanged("text visual stability background change is too large")
    if _component_count(changed) != 1:
        raise TextVisualPixelsChanged("text visual stability background change has multiple regions")
    if _rectangle_distance((left, top, right, bottom), _xywh_to_box(protected)) < _MIN_DISTANCE:
        raise TextVisualPixelsChanged("text visual stability background change is too near the field")
    return len(changed), (left, top, width, height)


def _component_count(points: list[tuple[int, int]]) -> int:
    remaining = set(points)
    count = 0
    while remaining:
        count += 1
        pending = [remaining.pop()]
        while pending:
            x, y = pending.pop()
            for adjacent_y in range(y - 1, y + 2):
                for adjacent_x in range(x - 1, x + 2):
                    point = (adjacent_x, adjacent_y)
                    if point in remaining:
                        remaining.remove(point)
                        pending.append(point)
    return count


def _rectangle_distance(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> float:
    horizontal = max(second[0] - first[2], first[0] - second[2], 0)
    vertical = max(second[1] - first[3], first[1] - second[3], 0)
    return math.hypot(horizontal, vertical)


def _pixel_sha256(image: Image.Image) -> str:
    width, height = image.size
    header = f"RGB:{width}x{height}:".encode("ascii")
    return sha256(header + image.tobytes()).hexdigest()


def _xywh_to_box(value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    return value[0], value[1], value[0] + value[2], value[1] + value[3]


def _rect_mapping(value: object, label: str) -> dict[str, int]:
    keys = {"x", "y", "width", "height"}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"text visual stability {label} is invalid")
    result = {key: value[key] for key in ("x", "y", "width", "height")}
    if any(type(item) is not int for item in result.values()) or result["width"] <= 0 or result["height"] <= 0:
        raise ValueError(f"text visual stability {label} is invalid")
    return result


def _viewport(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"width", "height"}:
        raise ValueError("text visual stability viewport is invalid")
    result = {key: value[key] for key in ("width", "height")}
    if any(type(item) is not int or item <= 0 for item in result.values()):
        raise ValueError("text visual stability viewport is invalid")
    return result


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"text visual stability {label} is invalid")
    return value


def _sha_value(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise ValueError(f"text visual stability {label} SHA is invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("text visual stability value is not canonical JSON") from error


def _digest(value: Mapping[str, Any]) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _digest_mapping(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise TypeError("text visual stability field reference must be a mapping")
    return _digest(dict(value))


__all__ = [
    "TextVisualPixelsChanged",
    "TextVisualStabilityAttestation",
    "TextVisualStabilityScope",
    "verify_text_visual_stability_reference",
]
