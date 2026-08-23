from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_portfolio_v1_controlled_live_gif.py"


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


def _write_receipt(tmp_path: Path) -> Path:
    receipt = {
        "runtime_receipt": {
            "receipt_id": "receipt.test-controlled-live",
            "contract_version": "runtime_result_receipt_v1",
            "dispatch_status": "dispatched",
            "effect_status": "verified",
            "destination_status": "verified",
            "outcome": "SAFE_STOP",
            "reason_code": "stop_boundary",
            "workflow": {
                "asset_content_sha256": "a" * 64,
                "workflow_id": "portfolio_v1_seek_apply_entry",
            },
        },
        "next_observation": {
            "state": {
                "display_name": "Choose documents",
                "state_availability": "stop_boundary",
            }
        },
    }
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_builder_creates_receipt_backed_public_safe_replay(tmp_path: Path) -> None:
    pre, post = _write_sources(tmp_path)
    receipt = _write_receipt(tmp_path)
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
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert output.is_file()
    assert manifest.is_file()

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["artifact_kind"] == "receipt-backed controlled-live replay"
    assert payload["continuous_recording"] is False
    assert payload["real_runtime_capture"] is True
    assert payload["receipt"]["receipt_id"] == "receipt.test-controlled-live"
    assert payload["receipt"]["object_sha256"] == _sha256(receipt)
    assert payload["sources"]["pre"]["sha256"] == _sha256(pre)
    assert payload["sources"]["post"]["sha256"] == _sha256(post)
    assert payload["privacy"]["post_crop_excludes_y_at_or_below"] <= 548
    assert payload["privacy"]["source_masks"]

    with Image.open(output) as gif:
        frames = [frame.convert("RGB") for frame in ImageSequence.Iterator(gif)]
        durations = [int(frame.info.get("duration", 0)) for frame in ImageSequence.Iterator(gif)]
        assert gif.size == (960, 540)
        assert 100 <= len(frames) <= 150
        assert 10_000 <= sum(durations) <= 15_000
        assert all(pixel != (255, 0, 255) for frame in frames for pixel in frame.get_flattened_data())

    assert payload["render"]["frame_count"] == len(frames)
    assert payload["render"]["duration_ms"] == sum(durations)
    assert payload["render"]["transition"]["label"] == "editorial crossfade — not continuous recording"
    assert payload["output"]["sha256"] == _sha256(output)
    assert payload["privacy"]["frame_scan"]["frames_scanned"] == len(frames)
    assert payload["privacy"]["frame_scan"]["forbidden_matches"] == []
