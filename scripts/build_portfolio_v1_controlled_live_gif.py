from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_KIND = "post-receipt-bound controlled-live replay"
CANVAS_SIZE = (960, 540)
FRAME_DURATION_MS = 100
FRAME_COUNT = 120
PRE_CROP = (190, 680, 1120, 1070)
POST_CROP = (180, 200, 1200, 535)
PRE_MASKS = (
    (0, 0, 1390, 210),
)
POST_MASKS = (
    (0, 0, 1390, 200),
    (1120, 120, 1250, 200),
    (180, 545, 930, 720),
    (180, 720, 980, 1211),
)
FORBIDDEN_PATTERNS = (
    ("email", re.compile(r"[a-z0-9._%+\-]+\s*@\s*[a-z0-9.\-]+\s*\.\s*[a-z]{2,}", re.IGNORECASE)),
    ("new_zealand_phone_+64", re.compile(r"(?:\+|＋)\s*64\b", re.IGNORECASE)),
    ("new_zealand_phone_local_02x", re.compile(r"(?<!\d)02\d(?:[\s().-]*\d){6,8}(?!\d)", re.IGNORECASE)),
    ("pdf_or_resume_filename", re.compile(r"(?:\.\s*pdf\b|\b(?:resume|resum[eé]|cv)(?:[\s_.-]|$))", re.IGNORECASE)),
)


@dataclass(frozen=True)
class PublicFrameAudit:
    frames_scanned: int
    unique_visuals_ocr_scanned: int
    forbidden_matches: tuple[dict[str, object], ...]
    engine: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    filename = "arialbd.ttf" if bold else "arial.ttf"
    path = Path(r"C:\Windows\Fonts") / filename
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _mask_source(image: Image.Image, masks: Sequence[tuple[int, int, int, int]]) -> Image.Image:
    masked = image.convert("RGB").copy()
    draw = ImageDraw.Draw(masked)
    for box in masks:
        draw.rectangle(box, fill="#091831")
    return masked


def _fit_crop(image: Image.Image, crop: tuple[int, int, int, int]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    cropped = image.crop(crop)
    contained = ImageOps.contain(cropped, (900, 365), method=Image.Resampling.LANCZOS)
    x = (CANVAS_SIZE[0] - contained.width) // 2
    y = 102 + (365 - contained.height) // 2
    return contained, (x, y, x + contained.width, y + contained.height)


def _draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, width: int, font: ImageFont.ImageFont, fill: str) -> None:
    words = text.split()
    line = ""
    y = xy[1]
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            draw.text((xy[0], y), line, font=font, fill=fill)
            line = word
            y += int(getattr(font, "size", 18) * 1.25)
        else:
            line = candidate
    if line:
        draw.text((xy[0], y), line, font=font, fill=fill)


def _compose_scene(source: Image.Image, *, phase: str, crop: tuple[int, int, int, int], masks: Sequence[tuple[int, int, int, int]]) -> Image.Image:
    canvas = Image.new("RGB", CANVAS_SIZE, "#f5f7fb")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 960, 90), fill="#081a3b")
    draw.text((30, 17), "CONTROLLED-LIVE EVIDENCE REPLAY", font=_font(17, bold=True), fill="#8ee6d2")
    phase_text = (
        "1  PRE — supplemental target (not receipt-bound)"
        if phase == "pre"
        else "2  POST — receipt-bound state: Choose documents"
    )
    draw.text((30, 45), phase_text, font=_font(25, bold=True), fill="white")

    masked = _mask_source(source, masks)
    fitted, box = _fit_crop(masked, crop)
    draw.rounded_rectangle((box[0] - 6, box[1] - 6, box[2] + 6, box[3] + 6), radius=14, fill="white", outline="#cbd5e7", width=2)
    canvas.paste(fitted, (box[0], box[1]))

    if phase == "pre":
        source_box = (266, 975, 411, 1022)
        line = "Reviewed semantic action: open_apply_flow"
        accent = "#e6007e"
    else:
        source_box = (210, 408, 420, 500)
        line = "Fresh observation: stop_boundary → SAFE_STOP"
        accent = "#1367d1"

    scale = min(900 / (crop[2] - crop[0]), 365 / (crop[3] - crop[1]))
    left = box[0] + int((source_box[0] - crop[0]) * scale)
    top = box[1] + int((source_box[1] - crop[1]) * scale)
    right = box[0] + int((source_box[2] - crop[0]) * scale)
    bottom = box[1] + int((source_box[3] - crop[1]) * scale)
    draw.rounded_rectangle((left - 7, top - 7, right + 7, bottom + 7), radius=9, outline=accent, width=5)

    draw.rectangle((0, 476, 960, 540), fill="#081a3b")
    draw.text((30, 489), line, font=_font(19, bold=True), fill="white")
    draw.text((30, 516), "Not a continuous recording • one bounded action • no form mutation", font=_font(15), fill="#c6d4ee")
    return canvas


def _compose_verified(post_scene: Image.Image, receipt_id: str) -> Image.Image:
    frame = post_scene.copy()
    draw = ImageDraw.Draw(frame, "RGBA")
    draw.rounded_rectangle((510, 370, 930, 463), radius=16, fill=(8, 26, 59, 238), outline=(142, 230, 210, 255), width=3)
    draw.text((534, 388), "1 DISPATCH  →  VERIFIED  →  SAFE STOP", font=_font(17, bold=True), fill="#8ee6d2")
    short_id = receipt_id if len(receipt_id) <= 42 else f"{receipt_id[:34]}…"
    draw.text((534, 420), short_id, font=_font(15), fill="white")
    return frame.convert("RGB")


def _compose_transition(pre_scene: Image.Image, post_scene: Image.Image, alpha: float) -> Image.Image:
    frame = Image.blend(pre_scene, post_scene, alpha)
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, 960, 90), fill="#081a3b")
    draw.text((30, 17), "CONTROLLED-LIVE EVIDENCE REPLAY", font=_font(17, bold=True), fill="#8ee6d2")
    draw.text((30, 45), "TRANSITION — one bounded semantic action", font=_font(25, bold=True), fill="white")
    draw.rectangle((0, 476, 960, 540), fill="#081a3b")
    draw.text((30, 489), "PRE: separately hashed/unbound  →  POST: receipt-bound", font=_font(19, bold=True), fill="white")
    draw.text((30, 516), "Editorial crossfade • not continuous recording or elapsed real-time footage", font=_font(15), fill="#c6d4ee")
    return frame


def _render_frames(pre: Image.Image, post: Image.Image, receipt_id: str) -> list[Image.Image]:
    pre_scene = _compose_scene(pre, phase="pre", crop=PRE_CROP, masks=PRE_MASKS)
    post_scene = _compose_scene(post, phase="post", crop=POST_CROP, masks=POST_MASKS)
    verified_scene = _compose_verified(post_scene, receipt_id)
    frames: list[Image.Image] = []
    for index in range(FRAME_COUNT):
        if index < 45:
            frame = pre_scene.copy()
        elif index < 60:
            alpha = (index - 44) / 16
            frame = _compose_transition(pre_scene, post_scene, alpha)
        elif index < 100:
            frame = post_scene.copy()
        else:
            frame = verified_scene.copy()
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, 536, 960, 540), fill="#16345f")
        draw.rectangle((0, 536, max(1, int(960 * (index + 1) / FRAME_COUNT)), 540), fill="#8ee6d2")
        frames.append(frame)
    return frames


def _save_gif(frames: Sequence[Image.Image], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    palette_frames = [
        frame.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        for frame in frames
    ]
    palette_frames[0].save(
        output,
        save_all=True,
        append_images=palette_frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
        optimize=False,
        disposal=2,
        comment=ARTIFACT_KIND.encode("ascii"),
    )


def _extract_ocr_text(engine: RapidOCR, image: Image.Image) -> str:
    result, _ = engine(np.asarray(image.convert("RGB")))
    return "\n".join(str(item[1]) for item in (result or []))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def audit_public_gif(path: Path, extra_forbidden_tokens: Iterable[str] = ()) -> PublicFrameAudit:
    engine = RapidOCR()
    cache: dict[str, str] = {}
    matches: list[dict[str, object]] = []
    frames_scanned = 0
    token_hashes = [(hashlib.sha256(token.casefold().encode("utf-8")).hexdigest(), token.casefold()) for token in extra_forbidden_tokens if token.strip()]
    with Image.open(path) as gif:
        for frame_index, raw_frame in enumerate(ImageSequence.Iterator(gif)):
            frames_scanned += 1
            frame = raw_frame.convert("RGB")
            scan_region = frame.crop((0, 0, frame.width, 536))
            key = hashlib.sha256(scan_region.tobytes()).hexdigest()
            text = cache.get(key)
            if text is None:
                text = _normalized(_extract_ocr_text(engine, scan_region))
                cache[key] = text
            for category, pattern in FORBIDDEN_PATTERNS:
                if pattern.search(text):
                    matches.append({"frame": frame_index, "category": category})
            for token_sha256, token in token_hashes:
                if token and token in text:
                    matches.append({"frame": frame_index, "category": "required_denylist_token", "token_sha256": token_sha256})
    return PublicFrameAudit(
        frames_scanned=frames_scanned,
        unique_visuals_ocr_scanned=len(cache),
        forbidden_matches=tuple(matches),
        engine="rapidocr_onnxruntime",
    )


def _source_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.name


def _required_dict(parent: dict[str, object], field: str) -> dict[str, object]:
    value = parent.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"receipt {field} must be an object")
    return value


def _required_text(parent: dict[str, object], field: str) -> str:
    value = parent.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"receipt {field} must be a non-empty string")
    return value


def _verification_ref(verification: dict[str, object]) -> str:
    """与 RuntimeReceiptStore 的 canonical verification 引用算法保持一致。"""

    try:
        canonical = json.dumps(
            verification,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("verification evidence must be canonical JSON") from exc
    return f"verification:{hashlib.sha256(canonical).hexdigest()}"


def _validate_receipt(
    payload: dict[str, object],
    expected_post_sha256: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    runtime = payload.get("runtime_receipt")
    observation = payload.get("next_observation")
    backend = payload.get("backend_receipt")
    verification = payload.get("verification_evidence")
    if not all(isinstance(value, dict) for value in (runtime, observation, backend, verification)):
        raise ValueError("receipt must contain backend_receipt, runtime_receipt, next_observation, and verification_evidence objects")
    assert isinstance(runtime, dict)
    assert isinstance(observation, dict)
    assert isinstance(backend, dict)
    assert isinstance(verification, dict)
    required = {
        "contract_version": "runtime_result_receipt_v1",
        "attempt_count": 1,
        "gate_status": "allowed",
        "dispatch_status": "dispatched",
        "effect_status": "verified",
        "destination_status": "verified",
        "outcome": "SAFE_STOP",
        "reason_code": "stop_boundary",
    }
    for field, expected in required.items():
        if runtime.get(field) != expected:
            raise ValueError(f"receipt {field} must equal {expected!r}")

    action = _required_dict(runtime, "action")
    if action.get("semantic_action") != "open_apply_flow":
        raise ValueError("receipt semantic_action must equal 'open_apply_flow'")

    if backend.get("status") != "dispatched":
        raise ValueError("backend receipt status must equal 'dispatched'")
    backend_ref = backend.get("receipt_ref")
    evidence = _required_dict(runtime, "evidence")
    if not isinstance(backend_ref, str) or not backend_ref or evidence.get("backend_receipt_ref") != backend_ref:
        raise ValueError("runtime receipt must bind the single dispatched backend receipt")

    # 与 RuntimeReceiptStore._validate_semantic_evidence / _validate_verification_lineage
    # 保持同一组最小跨对象绑定，防止只凭状态字段生成伪造的 receipt-backed claim。
    if evidence.get("verification_ref") != _verification_ref(verification):
        raise ValueError("runtime receipt verification reference mismatch")

    runtime_session_id = _required_text(runtime, "session_id")
    if _required_text(observation, "session_id") != runtime_session_id:
        raise ValueError("next observation session mismatch")
    next_observation_id = _required_text(runtime, "next_observation_id")
    observation_id = _required_text(observation, "observation_id")
    if observation_id != next_observation_id:
        raise ValueError("next observation identity mismatch")
    if _required_text(runtime, "observation_id") == observation_id:
        raise ValueError("next observation ID must be new")

    runtime_workflow = _required_dict(runtime, "workflow")
    observation_workflow = _required_dict(observation, "workflow")
    if observation_workflow != runtime_workflow:
        raise ValueError("next observation workflow mismatch")
    asset_content_sha256 = _required_text(runtime_workflow, "asset_content_sha256")
    if verification.get("asset_content_sha256") != asset_content_sha256:
        raise ValueError("verification workflow mismatch")
    if verification.get("transition_id") != action.get("action_id"):
        raise ValueError("verification transition mismatch")

    verification_required = {
        "contract_version": "transition_verification_v1",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    for field, expected in verification_required.items():
        if verification.get(field) != expected:
            raise ValueError(f"verification evidence {field} must equal {expected!r}")

    state = _required_dict(observation, "state")
    expected_state = {
        "display_name": "Choose documents",
        "state_availability": "stop_boundary",
        "status": "stop_boundary",
        "surface_type": "application_entry",
    }
    for field, expected in expected_state.items():
        if state.get(field) != expected:
            raise ValueError(f"next observation state {field} must equal {expected!r}")
    state_id = _required_text(state, "state_id")
    if verification.get("target_state_id") != state_id:
        raise ValueError("verification destination mismatch")

    for owner, safe_stop in (
        ("runtime receipt", _required_dict(runtime, "safe_stop")),
        ("next observation", _required_dict(observation, "safe_stop")),
    ):
        if safe_stop.get("required") is not True or safe_stop.get("reason_code") != "stop_boundary":
            raise ValueError(f"{owner} must require stop_boundary SAFE_STOP")

    available_actions = observation.get("available_actions")
    if not isinstance(available_actions, list) or len(available_actions) != 1:
        raise ValueError("next observation must expose exactly one safe_stop action")
    available_action = available_actions[0]
    if not isinstance(available_action, dict) or available_action.get("semantic_action") != "safe_stop":
        raise ValueError("next observation must expose safe_stop only")

    if verification.get("status") != "verified" or verification.get("state_advanced") is not True:
        raise ValueError("verification evidence must prove the state advanced")
    post_resolution = _required_dict(verification, "post_state_resolution")
    if post_resolution.get("status") != "resolved" or post_resolution.get("state_availability") != "stop_boundary":
        raise ValueError("post state resolution must resolve the stop boundary")
    if post_resolution.get("state_id") != state_id:
        raise ValueError("post state resolution destination mismatch")

    capture_lineages = (
        _required_dict(observation, "current_capture"),
        _required_dict(verification, "post_capture_lineage"),
        _required_dict(post_resolution, "capture_lineage"),
    )
    for capture in capture_lineages:
        if capture.get("screenshot_sha256") != expected_post_sha256:
            raise ValueError("receipt post capture lineage must match the supplied post screenshot SHA-256")
    capture_ids = {capture.get("capture_id") for capture in capture_lineages}
    if len(capture_ids) != 1 or None in capture_ids:
        raise ValueError("receipt post capture lineage must bind one capture_id")

    if not isinstance(runtime.get("receipt_id"), str) or not runtime["receipt_id"]:
        raise ValueError("receipt_id is required")
    validated_claims: dict[str, object] = {
        "attempt_count": 1,
        "semantic_action": "open_apply_flow",
        "gate_status": "allowed",
        "backend_dispatch_count": 1,
        "effect_status": "verified",
        "destination": "Choose documents / application_entry",
        "safe_stop_required": True,
        "next_action_projection": ["safe_stop"],
        "form_mutation_or_followup_dispatch_evidenced": False,
    }
    return runtime, state, validated_claims


def build(args: argparse.Namespace) -> dict[str, object]:
    forbidden_tokens = [token.strip() for token in args.forbidden_token if token.strip()]
    if not forbidden_tokens:
        raise ValueError("at least one non-empty --forbidden-token is required")

    pre_path = Path(args.pre).resolve()
    post_path = Path(args.post).resolve()
    receipt_path = Path(args.receipt).resolve()
    output_path = Path(args.output).resolve()
    manifest_path = Path(args.manifest).resolve()

    post_sha256 = _sha256(post_path)
    receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    runtime, state, validated_claims = _validate_receipt(receipt_payload, post_sha256)
    with Image.open(pre_path) as pre_image, Image.open(post_path) as post_image:
        frames = _render_frames(pre_image.convert("RGB"), post_image.convert("RGB"), str(runtime["receipt_id"]))
    _save_gif(frames, output_path)
    audit = audit_public_gif(output_path, forbidden_tokens)
    if audit.forbidden_matches:
        output_path.unlink(missing_ok=True)
        raise ValueError(f"public GIF privacy scan failed: {audit.forbidden_matches}")

    workflow = runtime.get("workflow") if isinstance(runtime.get("workflow"), dict) else {}
    manifest: dict[str, object] = {
        "schema_version": "portfolio_controlled_live_media_manifest_v1",
        "artifact_kind": ARTIFACT_KIND,
        "continuous_recording": False,
        "claim_boundary": (
            "Deterministic editorial replay: the post capture is cryptographically bound by one verified receipt; "
            "the pre capture is separately hashed and is not receipt-bound. The receipt proves one allowed "
            "open_apply_flow backend dispatch, verified arrival at Choose documents, and a SAFE_STOP-only next "
            "action projection. It is not a continuous recording, proof of out-of-band behavior, or a general reliability claim."
        ),
        "sources": {
            "pre": {
                "content_ref": f"sha256:{_sha256(pre_path)}",
                "availability": "not_published",
                "provenance_claim": "operator-provided runtime pre-dispatch capture",
                "receipt_binding": "unbound_supplemental_capture",
                "crop_xyxy": list(PRE_CROP),
                "source_masks_xyxy": [list(box) for box in PRE_MASKS],
                "semantic_label": "Reviewed target: Quick Apply",
            },
            "post": {
                "content_ref": f"sha256:{post_sha256}",
                "availability": "not_published",
                "provenance_claim": "runtime post-action capture bound by receipt screenshot_sha256",
                "receipt_binding": "bound_by_receipt_screenshot_sha256",
                "crop_xyxy": list(POST_CROP),
                "source_masks_xyxy": [list(box) for box in POST_MASKS],
                "semantic_label": "Choose documents / stop_boundary",
            },
        },
        "receipt": {
            "content_ref": f"sha256:{_sha256(receipt_path)}",
            "availability": "not_published",
            "receipt_id": runtime["receipt_id"],
            "contract_version": runtime.get("contract_version"),
            "workflow_id": workflow.get("workflow_id"),
            "asset_content_sha256": workflow.get("asset_content_sha256"),
            "dispatch_status": runtime.get("dispatch_status"),
            "effect_status": runtime.get("effect_status"),
            "destination_status": runtime.get("destination_status"),
            "outcome": runtime.get("outcome"),
            "reason_code": runtime.get("reason_code"),
            "post_state": state.get("display_name"),
            "validated_claims": validated_claims,
        },
        "render": {
            "canvas_size": list(CANVAS_SIZE),
            "frame_count": FRAME_COUNT,
            "frame_duration_ms": FRAME_DURATION_MS,
            "duration_ms": FRAME_COUNT * FRAME_DURATION_MS,
            "transition": {
                "kind": "crossfade",
                "start_frame": 45,
                "end_frame": 59,
                "label": "editorial crossfade — not continuous recording",
            },
        },
        "privacy": {
            "method": "deterministic source masking followed by allowlisted semantic crops",
            "post_crop_excludes_y_at_or_below": POST_CROP[3],
            "source_masks": {
                "pre": [list(box) for box in PRE_MASKS],
                "post": [list(box) for box in POST_MASKS],
            },
            "source_mask_intent": [
                "operator identity regions",
                "contact and profile details",
                "resume filenames",
                "account identifiers",
            ],
            "automated_scan_scope": [
                "required_denylist_token",
                "email",
                "new_zealand_phone_+64",
                "new_zealand_phone_local_02x",
                "pdf_or_resume_filename",
            ],
            "extra_forbidden_token_sha256": [hashlib.sha256(token.casefold().encode("utf-8")).hexdigest() for token in forbidden_tokens],
            "frame_scan": {
                "engine": audit.engine,
                "frames_scanned": audit.frames_scanned,
                "unique_visuals_ocr_scanned": audit.unique_visuals_ocr_scanned,
                "forbidden_matches": list(audit.forbidden_matches),
            },
        },
        "output": {
            "path": _source_ref(output_path),
            "sha256": _sha256(output_path),
            "media_type": "image/gif",
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the public-safe Portfolio v1 receipt-backed controlled-live replay GIF.")
    parser.add_argument("--pre", required=True, help="Real pre-dispatch runtime PNG")
    parser.add_argument("--post", required=True, help="Real post-action runtime PNG")
    parser.add_argument("--receipt", required=True, help="Verified runtime receipt object JSON")
    parser.add_argument("--output", required=True, help="Output GIF path")
    parser.add_argument("--manifest", required=True, help="Output sidecar manifest path")
    parser.add_argument("--forbidden-token", action="append", default=[], help="Additional private token to scan; only its SHA-256 is persisted")
    return parser.parse_args()


if __name__ == "__main__":
    manifest = build(parse_args())
    print(json.dumps({"output": manifest["output"], "render": manifest["render"], "privacy": manifest["privacy"]["frame_scan"]}, ensure_ascii=False))
