from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_portfolio_v1_controlled_live_gif.py"


def _load_builder_module():
    spec = importlib.util.spec_from_file_location("portfolio_controlled_live_builder", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BUILDER_MODULE = _load_builder_module()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = Path(r"C:\Windows\Fonts\arial.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    pre = Image.new("RGB", (1390, 1211), "white")
    pre_draw = ImageDraw.Draw(pre)
    pre_draw.rectangle((190, 680, 1120, 1070), fill="#f7f8fb")
    pre_draw.text((260, 720), "Entry-Level Sales & Recruitment", fill="#12264a", font=_font(38))
    pre_draw.rounded_rectangle((266, 975, 411, 1022), radius=9, fill="#e6007e")
    pre_draw.text((285, 986), "Quick apply", fill="white", font=_font(22))
    pre_path = tmp_path / "pre.png"
    pre.save(pre_path)

    post = Image.new("RGB", (1390, 1211), "white")
    post_draw = ImageDraw.Draw(post)
    post_draw.text((220, 225), "Applying for", fill="#314267", font=_font(24))
    post_draw.text((220, 420), "Choose documents", fill="#12264a", font=_font(28))
    post_draw.rectangle((180, 548, 1200, 1211), fill="#ff00ff")
    post_draw.text((220, 590), "PERSON NAME +64 person@example.test private_resume.pdf", fill="black", font=_font(24))
    post_path = tmp_path / "post.png"
    post.save(post_path)
    return pre_path, post_path


def _receipt_payload(post_sha256: str) -> dict[str, object]:
    backend_ref = "backend-receipt:test-controlled-live"
    capture = {
        "capture_id": "runtime-capture.test-post",
        "screenshot_sha256": post_sha256,
        "viewport_size": {"height": 1211, "width": 1390},
    }
    return {
        "backend_receipt": {
            "reason_code": "none",
            "receipt_ref": backend_ref,
            "status": "dispatched",
        },
        "runtime_receipt": {
            "receipt_id": "receipt.test-controlled-live",
            "contract_version": "runtime_result_receipt_v1",
            "attempt_count": 1,
            "action": {
                "action_id": "transition.test-open-apply-flow",
                "semantic_action": "open_apply_flow",
            },
            "gate_status": "allowed",
            "dispatch_status": "dispatched",
            "effect_status": "verified",
            "destination_status": "verified",
            "outcome": "SAFE_STOP",
            "reason_code": "stop_boundary",
            "safe_stop": {"reason_code": "stop_boundary", "required": True},
            "evidence": {"backend_receipt_ref": backend_ref},
            "workflow": {
                "asset_content_sha256": "a" * 64,
                "workflow_id": "portfolio_v1_seek_apply_entry",
            },
        },
        "next_observation": {
            "current_capture": {
                "capture_id": capture["capture_id"],
                "screenshot_sha256": post_sha256,
            },
            "state": {
                "display_name": "Choose documents",
                "state_availability": "stop_boundary",
                "status": "stop_boundary",
                "surface_type": "application_entry",
            },
            "safe_stop": {"reason_code": "stop_boundary", "required": True},
            "available_actions": [
                {
                    "action_id": "runtime.safe_stop",
                    "semantic_action": "safe_stop",
                }
            ],
        },
        "verification_evidence": {
            "status": "verified",
            "state_advanced": True,
            "post_capture_lineage": copy.deepcopy(capture),
            "post_state_resolution": {
                "status": "resolved",
                "state_availability": "stop_boundary",
                "capture_lineage": copy.deepcopy(capture),
            },
        },
    }


def _write_receipt(tmp_path: Path, post_sha256: str) -> Path:
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(_receipt_payload(post_sha256)), encoding="utf-8")
    return path


def _set_nested(payload: dict[str, object], dotted_path: str, value: object) -> None:
    current: object = payload
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        assert isinstance(current, dict)
        current = current[part]
    assert isinstance(current, dict)
    current[parts[-1]] = value


def test_builder_creates_post_receipt_bound_public_safe_replay(tmp_path: Path) -> None:
    pre, post = _write_sources(tmp_path)
    receipt = _write_receipt(tmp_path, _sha256(post))
    output = tmp_path / "controlled-live.gif"
    manifest = tmp_path / "controlled-live.manifest.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--pre",
            str(pre),
            "--post",
            str(post),
            "--receipt",
            str(receipt),
            "--output",
            str(output),
            "--manifest",
            str(manifest),
            "--forbidden-token",
            "SecretName",
        ],
        cwd=ROOT,
        capture_output=True,
        text=False,
        check=False,
    )

    assert completed.returncode == 0, (completed.stderr or completed.stdout).decode("utf-8", errors="replace")
    assert completed.stderr == b""
    assert output.is_file()
    assert manifest.is_file()

    manifest_text = manifest.read_text(encoding="utf-8")
    payload = json.loads(manifest_text)
    for private_input in (str(tmp_path), pre.name, post.name, receipt.name):
        assert private_input not in manifest_text
    assert payload["artifact_kind"] == "post-receipt-bound controlled-live replay"
    assert payload["continuous_recording"] is False
    assert "real_runtime_capture" not in payload
    assert "post capture is cryptographically bound" in payload["claim_boundary"].lower()
    assert "pre capture is separately hashed and is not receipt-bound" in payload["claim_boundary"].lower()
    assert payload["receipt"]["receipt_id"] == "receipt.test-controlled-live"
    assert payload["receipt"]["content_ref"] == f"sha256:{_sha256(receipt)}"
    assert payload["receipt"]["availability"] == "not_published"
    assert "path" not in payload["receipt"]
    assert payload["sources"]["pre"]["content_ref"] == f"sha256:{_sha256(pre)}"
    assert payload["sources"]["pre"]["receipt_binding"] == "unbound_supplemental_capture"
    assert payload["sources"]["post"]["content_ref"] == f"sha256:{_sha256(post)}"
    assert payload["sources"]["post"]["receipt_binding"] == "bound_by_receipt_screenshot_sha256"
    assert all(source["availability"] == "not_published" and "path" not in source for source in payload["sources"].values())
    assert payload["receipt"]["validated_claims"] == {
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
    assert payload["privacy"]["post_crop_excludes_y_at_or_below"] <= 548
    assert payload["privacy"]["source_masks"]
    assert "excluded_classes" not in payload["privacy"]
    assert payload["privacy"]["source_mask_intent"] == [
        "operator identity regions",
        "contact and profile details",
        "resume filenames",
        "account identifiers",
    ]
    assert payload["privacy"]["automated_scan_scope"] == [
        "required_denylist_token",
        "email",
        "new_zealand_phone_+64",
        "new_zealand_phone_local_02x",
        "pdf_or_resume_filename",
    ]

    with Image.open(output) as gif:
        frames = [frame.convert("RGB") for frame in ImageSequence.Iterator(gif)]
        durations = [int(frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(gif)]
        assert gif.size == (960, 540)
        assert len(frames) == 120
        assert durations == [100] * 120
        assert sum(durations) == 12_000
        assert all(pixel != (255, 0, 255) for frame in frames for pixel in frame.get_flattened_data())

    assert payload["render"]["canvas_size"] == [960, 540]
    assert payload["render"]["frame_count"] == 120
    assert payload["render"]["frame_duration_ms"] == 100
    assert payload["render"]["duration_ms"] == 12_000
    assert payload["render"]["transition"]["label"] == "editorial crossfade — not continuous recording"
    assert not Path(payload["output"]["path"]).is_absolute()
    assert payload["output"]["sha256"] == _sha256(output)
    assert payload["privacy"]["frame_scan"]["frames_scanned"] == 120
    assert payload["privacy"]["frame_scan"]["forbidden_matches"] == []


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("runtime_receipt.attempt_count", 2),
        ("runtime_receipt.action.semantic_action", "fill_field"),
        ("runtime_receipt.gate_status", "blocked"),
        ("backend_receipt.status", "indeterminate"),
        ("runtime_receipt.evidence.backend_receipt_ref", "backend-receipt:different"),
        ("runtime_receipt.effect_status", "failed"),
        ("next_observation.state.display_name", "Job Detail"),
        ("next_observation.state.surface_type", "detail"),
        ("next_observation.safe_stop.required", False),
        (
            "next_observation.available_actions",
            [{"action_id": "runtime.continue", "semantic_action": "continue_next_step"}],
        ),
        ("verification_evidence.status", "failed"),
        ("verification_evidence.state_advanced", False),
    ],
)
def test_receipt_claim_validation_rejects_mismatches(field: str, bad_value: object) -> None:
    post_sha256 = "b" * 64
    payload = _receipt_payload(post_sha256)
    _set_nested(payload, field, bad_value)

    with pytest.raises(ValueError):
        BUILDER_MODULE._validate_receipt(payload, post_sha256)


@pytest.mark.parametrize(
    "field",
    [
        "next_observation.current_capture.screenshot_sha256",
        "verification_evidence.post_capture_lineage.screenshot_sha256",
        "verification_evidence.post_state_resolution.capture_lineage.screenshot_sha256",
    ],
)
def test_receipt_claim_validation_rejects_post_capture_hash_mismatch(field: str) -> None:
    post_sha256 = "b" * 64
    payload = _receipt_payload(post_sha256)
    _set_nested(payload, field, "c" * 64)

    with pytest.raises(ValueError):
        BUILDER_MODULE._validate_receipt(payload, post_sha256)


def test_audit_rejects_crop_inside_private_identifiers(tmp_path: Path) -> None:
    image = Image.new("RGB", (960, 540), "white")
    draw = ImageDraw.Draw(image)
    font = _font(36)
    lines = [
        "person@example.test",
        "+64 21 123 4567",
        "021 123 4567",
        "SecretName_resume.pdf",
    ]
    for index, line in enumerate(lines):
        draw.text((50, 50 + 85 * index), line, fill="black", font=font)
    path = tmp_path / "private.gif"
    image.save(path, format="GIF", duration=100, loop=0)

    audit = BUILDER_MODULE.audit_public_gif(path, ["SecretName"])
    categories = {match["category"] for match in audit.forbidden_matches}

    assert categories == {
        "required_denylist_token",
        "email",
        "new_zealand_phone_+64",
        "new_zealand_phone_local_02x",
        "pdf_or_resume_filename",
    }


def test_builder_requires_at_least_one_forbidden_token() -> None:
    args = argparse.Namespace(
        pre="missing-pre.png",
        post="missing-post.png",
        receipt="missing-receipt.json",
        output="missing-output.gif",
        manifest="missing-manifest.json",
        forbidden_token=[],
    )

    with pytest.raises(ValueError, match="forbidden-token"):
        BUILDER_MODULE.build(args)
