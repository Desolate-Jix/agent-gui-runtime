"""离线生成并封存 portfolio-hybrid-v1-1 合成截图语料。"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_VERSION = "portfolio_hybrid_v1_1_corpus_manifest_v1"
GOLD_CONTRACT_VERSION = "portfolio_hybrid_v1_1_gold_records_v1"
PROJECTION_CONTRACT_VERSION = "portfolio_hybrid_v1_1_provider_corpus_projection_v1"
EXPECTED_PROVIDER_REVISIONS = {
    "omni": "PINNED_OMNI_REVISION",
    "qwen": "PINNED_QWEN_REVISION",
    "vista": "PINNED_VISTA_REVISION",
}
EXPECTED_SHARED_BUDGET = {
    "max_provider_calls_per_case": 3,
    "max_output_tokens_per_case": 2048,
    "max_wall_time_ms_per_case": 120000,
}
EXPECTED_CONTEXT_POLICY = {
    "policy_version": "portfolio-hybrid-shared-uia-ocr-v1",
    "uia": "same_capture_optional",
    "ocr": "same_capture_optional",
}
ANNOTATOR_IDENTITY_HASH = hashlib.sha256(
    b"portfolio-hybrid-v1-1-synthetic-annotator-v1"
).hexdigest()
PENDING_REVIEWER_IDENTITY_HASH = hashlib.sha256(
    b"portfolio-hybrid-v1-1-independent-review-pending-v1"
).hexdigest()
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ROLES = {"button", "checkbox", "combobox", "link", "menuitem", "tab", "textbox"}


def _control(role: str, label: str, bbox: tuple[int, int, int, int]) -> dict[str, Any]:
    return {"role": role, "label": label, "bbox": list(bbox)}


_LAYOUT_CONTROLS = (
    ("project_board", "Project Board", "web_like", "standard", "normal", (
        _control("button", "New task", (48, 88, 166, 126)),
        _control("textbox", "Search board", (420, 78, 700, 118)),
        _control("tab", "Active", (282, 150, 364, 184)),
        _control("combobox", "Filter", (982, 150, 1116, 188)),
        _control("link", "Settings", (52, 648, 132, 676)),
    )),
    ("mail_inbox", "Mail Inbox", "web_like", "dense", "small", (
        _control("button", "Compose", (34, 78, 142, 114)),
        _control("textbox", "Search mail", (310, 70, 738, 108)),
        _control("tab", "Primary", (242, 140, 332, 172)),
        _control("checkbox", "Select all", (230, 194, 326, 222)),
        _control("menuitem", "More", (1160, 140, 1224, 170)),
    )),
    ("desktop_settings", "System Settings", "native_like", "standard", "normal", (
        _control("button", "Back", (28, 38, 98, 72)),
        _control("textbox", "Find a setting", (246, 38, 610, 76)),
        _control("checkbox", "Bluetooth", (330, 174, 448, 206)),
        _control("tab", "Display", (32, 126, 118, 160)),
        _control("link", "Advanced", (334, 606, 430, 634)),
    )),
    ("file_manager", "File Manager", "native_like", "dense", "small", (
        _control("button", "Back", (18, 46, 78, 76)),
        _control("textbox", "Search files", (744, 42, 1068, 78)),
        _control("button", "New folder", (102, 102, 208, 136)),
        _control("combobox", "View", (1090, 100, 1194, 134)),
        _control("tab", "Details", (872, 100, 956, 134)),
    )),
    ("calendar", "Team Calendar", "web_like", "standard", "normal", (
        _control("button", "Today", (34, 82, 112, 118)),
        _control("button", "New event", (116, 82, 232, 118)),
        _control("combobox", "Month", (536, 82, 648, 118)),
        _control("textbox", "Search calendar", (830, 80, 1086, 118)),
        _control("link", "Settings", (1148, 86, 1222, 112)),
    )),
    ("analytics_dashboard", "Analytics Dashboard", "web_like", "dense", "small", (
        _control("button", "Refresh", (880, 70, 966, 102)),
        _control("combobox", "Date range", (972, 70, 1090, 102)),
        _control("button", "Export", (1098, 70, 1178, 102)),
        _control("checkbox", "Alerts", (1042, 130, 1120, 156)),
        _control("tab", "Reports", (260, 128, 340, 158)),
    )),
    ("document_editor", "Document Editor", "web_like", "dense", "ambiguous", (
        _control("button", "Undo", (20, 82, 76, 112)),
        _control("button", "Save", (84, 82, 142, 112)),
        _control("button", "Share", (1150, 76, 1222, 112)),
        _control("combobox", "Zoom", (826, 80, 914, 112)),
        _control("link", "Comments", (1018, 84, 1104, 108)),
    )),
    ("team_chat", "Team Chat", "native_like", "standard", "normal", (
        _control("button", "New chat", (28, 76, 138, 112)),
        _control("textbox", "Search", (158, 76, 394, 112)),
        _control("tab", "Inbox", (32, 134, 102, 166)),
        _control("checkbox", "Mute", (1048, 88, 1116, 114)),
        _control("link", "Help", (1180, 88, 1222, 112)),
    )),
    ("storefront", "Sample Store", "web_like", "standard", "normal", (
        _control("textbox", "Search products", (322, 68, 744, 108)),
        _control("combobox", "Category", (758, 68, 894, 108)),
        _control("tab", "Deals", (252, 128, 320, 160)),
        _control("checkbox", "Compare", (1010, 134, 1100, 162)),
        _control("link", "Cart", (1170, 78, 1214, 104)),
    )),
    ("developer_console", "Developer Console", "native_like", "dense", "ambiguous", (
        _control("button", "Run", (22, 74, 72, 104)),
        _control("button", "Stop", (78, 74, 132, 104)),
        _control("combobox", "Environment", (842, 72, 996, 106)),
        _control("tab", "Logs", (218, 126, 274, 156)),
        _control("checkbox", "Auto scroll", (1090, 130, 1200, 158)),
    )),
    ("media_library", "Media Library", "web_like", "standard", "normal", (
        _control("button", "Upload", (34, 78, 114, 114)),
        _control("textbox", "Search media", (336, 76, 684, 114)),
        _control("tab", "Grid", (214, 138, 266, 168)),
        _control("combobox", "Sort", (1014, 136, 1108, 170)),
        _control("checkbox", "Favorites", (1122, 140, 1218, 168)),
    )),
    ("city_map", "City Map", "web_like", "standard", "small", (
        _control("button", "Zoom in", (28, 194, 104, 226)),
        _control("textbox", "Search places", (28, 78, 360, 118)),
        _control("combobox", "Layers", (1112, 78, 1218, 116)),
        _control("checkbox", "Transit", (1108, 130, 1194, 158)),
        _control("link", "Directions", (48, 136, 134, 162)),
    )),
    ("installer", "Application Installer", "native_like", "standard", "normal", (
        _control("button", "Previous", (842, 636, 936, 674)),
        _control("button", "Install", (1044, 636, 1126, 674)),
        _control("button", "Cancel", (1134, 636, 1214, 674)),
        _control("checkbox", "Desktop shortcut", (356, 402, 522, 432)),
        _control("combobox", "Install for", (356, 342, 528, 380)),
    )),
    ("traffic_report", "Traffic Report", "web_like", "dense", "small", (
        _control("tab", "Overview", (232, 128, 320, 158)),
        _control("tab", "Sources", (326, 128, 402, 158)),
        _control("combobox", "Last 30 days", (970, 72, 1104, 104)),
        _control("button", "Download", (1112, 72, 1210, 104)),
        _control("checkbox", "Compare", (1044, 132, 1132, 158)),
    )),
    ("audio_mixer", "Audio Mixer", "native_like", "dense", "ambiguous", (
        _control("button", "Mute A", (272, 568, 344, 598)),
        _control("button", "Mute B", (422, 568, 494, 598)),
        _control("button", "Mute C", (572, 568, 644, 598)),
        _control("combobox", "Output", (958, 76, 1084, 110)),
        _control("checkbox", "Monitor", (1094, 80, 1190, 108)),
    )),
    ("kanban", "Sprint Board", "web_like", "dense", "small", (
        _control("button", "Add card", (34, 86, 124, 118)),
        _control("textbox", "Search cards", (396, 80, 692, 116)),
        _control("combobox", "Assignee", (936, 82, 1058, 116)),
        _control("checkbox", "My items", (1068, 86, 1156, 114)),
        _control("menuitem", "Board menu", (1162, 82, 1240, 114)),
    )),
    ("database_admin", "Database Admin", "web_like", "dense", "ambiguous", (
        _control("button", "New query", (224, 78, 318, 110)),
        _control("button", "Run query", (326, 78, 420, 110)),
        _control("combobox", "Database", (790, 76, 920, 110)),
        _control("tab", "Results", (250, 130, 324, 160)),
        _control("checkbox", "Limit 100", (1028, 132, 1126, 160)),
    )),
    ("weather", "Weather Center", "web_like", "standard", "normal", (
        _control("textbox", "Search city", (306, 74, 630, 114)),
        _control("button", "Use location", (640, 74, 760, 114)),
        _control("tab", "Hourly", (300, 142, 374, 174)),
        _control("tab", "Ten day", (382, 142, 466, 174)),
        _control("link", "Map", (1164, 84, 1206, 110)),
    )),
    ("accessibility", "Accessibility", "native_like", "standard", "small", (
        _control("button", "Back", (26, 40, 88, 72)),
        _control("textbox", "Find option", (238, 38, 560, 76)),
        _control("checkbox", "High contrast", (340, 178, 476, 208)),
        _control("checkbox", "Screen reader", (340, 232, 476, 262)),
        _control("link", "Keyboard help", (340, 594, 472, 622)),
    )),
    ("travel_booking", "Travel Booking", "web_like", "dense", "ambiguous", (
        _control("textbox", "From", (132, 166, 356, 206)),
        _control("textbox", "To", (366, 166, 590, 206)),
        _control("combobox", "Travel date", (600, 166, 758, 206)),
        _control("checkbox", "Round trip", (770, 172, 882, 202)),
        _control("button", "Search", (1034, 164, 1142, 208)),
    )),
    ("system_monitor", "System Monitor", "native_like", "dense", "small", (
        _control("textbox", "Filter process", (324, 72, 636, 106)),
        _control("button", "End task", (1098, 72, 1190, 104)),
        _control("tab", "Processes", (218, 126, 310, 156)),
        _control("tab", "Performance", (318, 126, 426, 156)),
        _control("checkbox", "Group by app", (1018, 130, 1148, 158)),
    )),
    ("form_builder", "Form Builder", "web_like", "dense", "ambiguous", (
        _control("button", "Save", (1014, 76, 1074, 108)),
        _control("button", "Save as", (1080, 76, 1156, 108)),
        _control("button", "Preview", (926, 76, 1008, 108)),
        _control("tab", "Fields", (36, 132, 96, 162)),
        _control("checkbox", "Required", (984, 188, 1076, 216)),
    )),
    ("inventory", "Inventory", "web_like", "dense", "small", (
        _control("button", "Add item", (30, 76, 116, 108)),
        _control("textbox", "Search SKU", (324, 72, 656, 108)),
        _control("combobox", "Warehouse", (846, 74, 976, 108)),
        _control("checkbox", "Low stock", (988, 78, 1084, 106)),
        _control("button", "Export", (1094, 74, 1174, 108)),
    )),
    ("command_palette", "Command Palette", "native_like", "dense", "small", (
        _control("textbox", "Type a command", (354, 158, 926, 198)),
        _control("menuitem", "Open file", (370, 222, 910, 250)),
        _control("menuitem", "Open folder", (370, 254, 910, 282)),
        _control("menuitem", "Toggle panel", (370, 286, 910, 314)),
        _control("menuitem", "Preferences", (370, 318, 910, 346)),
    )),
)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def content_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"path is outside repository root: {path}") from error


def _inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("sealed path must be a repository-relative POSIX path")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("sealed path escapes repository root") from error
    return path


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size=size)
    except OSError:
        return ImageFont.load_default()


def _draw_control(draw: ImageDraw.ImageDraw, control: Mapping[str, Any], accent: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = control["bbox"]
    role = control["role"]
    label = control["label"]
    font = _font(13 if y2 - y1 < 34 else 15, bold=role in {"button", "tab"})
    if role == "button":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=6, fill=accent, outline=(28, 52, 88), width=1)
        color = (255, 255, 255)
        draw.text((x1 + 10, y1 + (y2 - y1 - 15) // 2), label, font=font, fill=color)
    elif role == "textbox":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=5, fill=(255, 255, 255), outline=(106, 117, 134), width=2)
        draw.ellipse((x1 + 10, y1 + 10, x1 + 22, y1 + 22), outline=(90, 100, 116), width=2)
        draw.line((x1 + 20, y1 + 20, x1 + 26, y1 + 26), fill=(90, 100, 116), width=2)
        draw.text((x1 + 34, y1 + (y2 - y1 - 14) // 2), label, font=font, fill=(68, 76, 91))
    elif role == "checkbox":
        box = min(18, y2 - y1 - 6)
        draw.rectangle((x1 + 2, y1 + 4, x1 + 2 + box, y1 + 4 + box), fill=(255, 255, 255), outline=accent, width=2)
        draw.text((x1 + box + 9, y1 + 4), label, font=font, fill=(34, 41, 54))
    elif role == "combobox":
        draw.rounded_rectangle((x1, y1, x2, y2), radius=4, fill=(255, 255, 255), outline=(104, 116, 134), width=1)
        draw.text((x1 + 9, y1 + (y2 - y1 - 14) // 2), label, font=font, fill=(35, 42, 54))
        draw.polygon(((x2 - 20, y1 + 14), (x2 - 10, y1 + 14), (x2 - 15, y1 + 20)), fill=(60, 68, 82))
    elif role == "tab":
        draw.rectangle((x1, y1, x2, y2), fill=(246, 248, 252))
        draw.text((x1 + 7, y1 + 6), label, font=font, fill=(32, 43, 62))
        draw.rectangle((x1, y2 - 3, x2, y2), fill=accent)
    elif role == "link":
        draw.text((x1 + 2, y1 + 4), label, font=font, fill=(20, 93, 190))
        draw.line((x1 + 2, y2 - 3, x2 - 2, y2 - 3), fill=(20, 93, 190), width=1)
    else:
        draw.rectangle((x1, y1, x2, y2), fill=(250, 251, 253), outline=(212, 218, 228))
        draw.text((x1 + 9, y1 + 5), label, font=font, fill=(34, 42, 56))


def _render_screen(index: int, spec: tuple[Any, ...], output: Path) -> None:
    layout_id, title, surface, density, precision, controls = spec
    accent_palette = ((40, 111, 235), (12, 132, 116), (126, 87, 194), (219, 91, 66))
    accent = accent_palette[(index - 1) % len(accent_palette)]
    image = Image.new("RGB", (1280, 720), (236, 240, 247) if surface == "web_like" else (229, 233, 239))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1279, 50), fill=(31, 40, 58) if surface == "web_like" else (48, 54, 66))
    draw.text((22, 14), title, font=_font(20, bold=True), fill=(255, 255, 255))
    draw.text((1110, 16), f"SYNTHETIC {index:02d}", font=_font(11, bold=True), fill=(191, 203, 223))
    if surface == "web_like":
        draw.rectangle((0, 50, 196, 719), fill=(247, 249, 252))
        for row in range(7):
            y = 212 + row * 54
            draw.rounded_rectangle((26, y, 170, y + 30), radius=5, fill=(232, 236, 244))
    else:
        draw.rectangle((0, 50, 198, 719), fill=(216, 221, 229))
        for row in range(8):
            y = 118 + row * 52
            draw.rectangle((24, y, 168, y + 26), fill=(202, 208, 218))
    draw.rounded_rectangle((214, 124, 1248, 688), radius=10, fill=(255, 255, 255), outline=(205, 212, 223), width=1)
    rows = 8 if density == "dense" else 5
    for row in range(rows):
        y = 222 + row * (42 if density == "dense" else 68)
        shade = 245 - (row % 2) * 4
        draw.rectangle((248, y, 1208, min(y + 28, 670)), fill=(shade, shade + 2, min(255, shade + 6)))
        draw.rectangle((266, y + 8, 438 + (row % 3) * 42, min(y + 14, 677)), fill=(195, 203, 215))
        draw.rectangle((724, y + 8, 852 + (row % 2) * 54, min(y + 14, 677)), fill=(213, 219, 228))
    if precision == "ambiguous":
        draw.text((246, 190), "Precision targets: nearby controls have distinct labels", font=_font(12), fill=(122, 82, 30))
    elif precision == "small":
        draw.text((246, 190), "Compact control layout", font=_font(12), fill=(74, 85, 102))
    for control in controls:
        _draw_control(draw, control, accent)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=False, compress_level=9)


def _screen_path(corpus_root: Path, index: int) -> Path:
    partition = "regression" if index <= 12 else "holdout"
    return corpus_root / partition / f"case-{index:03d}.png"


def _gold_records(
    reviewer_identity_hash: str = PENDING_REVIEWER_IDENTITY_HASH,
    review_status: str = "pending_independent_review",
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, spec in enumerate(_LAYOUT_CONTROLS, start=1):
        _, _, _, _, _, controls = spec
        screen_id = f"case-{index:03d}"
        partition = "regression" if index <= 12 else "holdout"
        for target_index, control in enumerate(controls, start=1):
            records.append(
                {
                    "target_id": f"{screen_id}-target-{target_index:02d}",
                    "screen_id": screen_id,
                    "partition": partition,
                    "role": control["role"],
                    "label": control["label"],
                    "goal": f"Select the {control['role']} labeled '{control['label']}'",
                    "bbox": deepcopy(control["bbox"]),
                    "acceptable_candidate_ids": [f"candidate/{screen_id}/{target_index:02d}"],
                    "acceptable_regions": [deepcopy(control["bbox"])],
                    "annotator_identity_hash": ANNOTATOR_IDENTITY_HASH,
                    "reviewer_identity_hash": reviewer_identity_hash,
                    "acceptable_region_disagreement": "none",
                    "review_status": review_status,
                    "important_target": True,
                }
            )
    return records


def generate_synthetic_corpus(
    corpus_root: str | Path,
    gold_path: str | Path,
    *,
    reviewer_identity_hash: str = PENDING_REVIEWER_IDENTITY_HASH,
    review_status: str = "pending_independent_review",
) -> dict[str, Any]:
    corpus = Path(corpus_root)
    gold = Path(gold_path)
    if review_status not in {"pending_independent_review", "approved"}:
        raise ValueError("review status must be pending_independent_review or approved")
    if _SHA_RE.fullmatch(reviewer_identity_hash) is None:
        raise ValueError("reviewer identity hash must be SHA-256")
    if reviewer_identity_hash == ANNOTATOR_IDENTITY_HASH:
        raise ValueError("annotator and reviewer identities must be independent")
    if review_status == "approved" and reviewer_identity_hash == PENDING_REVIEWER_IDENTITY_HASH:
        raise ValueError("approved review requires an independent reviewer identity")
    for index, spec in enumerate(_LAYOUT_CONTROLS, start=1):
        _render_screen(index, spec, _screen_path(corpus, index))
    document = {
        "contract_version": GOLD_CONTRACT_VERSION,
        "review_state": review_status,
        "targets": _gold_records(reviewer_identity_hash, review_status),
    }
    gold.parent.mkdir(parents=True, exist_ok=True)
    gold.write_bytes(
        (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return {
        "screen_count": len(_LAYOUT_CONTROLS),
        "target_count": len(document["targets"]),
        "regression_target_count": sum(item["partition"] == "regression" for item in document["targets"]),
        "holdout_target_count": sum(item["partition"] == "holdout" for item in document["targets"]),
        "review_state": review_status,
        "png_sha256": [_file_sha256(_screen_path(corpus, index)) for index in range(1, 25)],
        "gold_sha256": _file_sha256(gold),
    }


def png_dimensions(path: str | Path) -> tuple[int, int]:
    raw = Path(path).read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError(f"invalid PNG: {path}")
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid PNG dimensions: {path}")
    with Image.open(path) as image:
        image.verify()
    return width, height


def _artifact(path: Path, root: Path) -> dict[str, str]:
    if not path.is_file():
        raise ValueError(f"required artifact is missing: {path}")
    return {"path": _relative(path, root), "sha256": _file_sha256(path)}


def _validate_gate(path: Path, artifact_sha: str) -> dict[str, str]:
    gate = json.loads(path.read_text(encoding="utf-8"))
    declared = gate.get("config_sha256")
    unhashed = {key: value for key, value in gate.items() if key != "config_sha256"}
    if _SHA_RE.fullmatch(str(declared)) is None or declared != content_sha256(unhashed):
        raise ValueError("gate config_sha256 mismatch")
    if gate.get("config_id") != "portfolio-hybrid-v1-1-gate":
        raise ValueError("gate config_id mismatch")
    return {
        "artifact_sha256": artifact_sha,
        "config_id": gate["config_id"],
        "config_sha256": declared,
    }


def _validate_gold_document(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"contract_version", "review_state", "targets"}:
        raise ValueError("Gold artifact must be a closed object")
    if value["contract_version"] != GOLD_CONTRACT_VERSION:
        raise ValueError("Gold contract version mismatch")
    if value["review_state"] not in {"pending_independent_review", "approved"}:
        raise ValueError("Gold review state is invalid")
    if not isinstance(value["targets"], list) or not value["targets"]:
        raise ValueError("Gold targets must be a non-empty list")
    reviewer_identity_hash = value["targets"][0].get("reviewer_identity_hash", "")
    if _SHA_RE.fullmatch(str(reviewer_identity_hash)) is None:
        raise ValueError("Gold reviewer identity hash is invalid")
    if value["review_state"] == "approved" and reviewer_identity_hash in {
        PENDING_REVIEWER_IDENTITY_HASH,
        ANNOTATOR_IDENTITY_HASH,
    }:
        raise ValueError("approved review requires an independent reviewer identity")
    expected = _gold_records(
        reviewer_identity_hash,
        value["review_state"],
    )
    if value["targets"] != expected:
        raise ValueError("canonical Gold records do not match the synthetic corpus")
    return deepcopy(value)


def _screenshots(corpus_root: Path, root: Path, review_state: str, reviewer_hash: str) -> list[dict[str, Any]]:
    expected_paths = {_screen_path(corpus_root, index).resolve() for index in range(1, 25)}
    actual_paths = {path.resolve() for path in corpus_root.rglob("*.png")}
    if actual_paths != expected_paths:
        raise ValueError("corpus PNG enumeration must be exactly case-001 through case-024")
    records: list[dict[str, Any]] = []
    for index, spec in enumerate(_LAYOUT_CONTROLS, start=1):
        layout_id, title, surface, density, precision, _ = spec
        path = _screen_path(corpus_root, index)
        width, height = png_dimensions(path)
        records.append(
            {
                "screen_id": f"case-{index:03d}",
                "partition": "regression" if index <= 12 else "holdout",
                "path": _relative(path, root),
                "sha256": _file_sha256(path),
                "width": width,
                "height": height,
                "layout_id": layout_id,
                "title": title,
                "surface": surface,
                "density": density,
                "precision_case": precision,
                "source_kind": "privacy_safe_synthetic",
                "source_provenance": "existing_five_screen_regression" if index <= 5 else "public_synthetic_new",
                "reviewer_identity_hash": reviewer_hash,
                "review_status": review_state,
                "privacy_review_status": review_state,
            }
        )
    if len({item["sha256"] for item in records}) != 24:
        raise ValueError("screenshot hashes must be distinct")
    return records


def _assert_no_prediction_artifacts(corpus_root: Path) -> None:
    parent = corpus_root.parent
    for path in parent.rglob("*"):
        normalized = re.sub(r"[^a-z0-9]+", "_", path.name.casefold())
        if "prediction" in normalized or "provider_output" in normalized:
            raise ValueError(f"prediction artifact is forbidden before sealing: {path}")


def seal_corpus(
    *,
    corpus_root: str | Path,
    gold: str | Path,
    gate: str | Path,
    producer: str | Path,
    runner: str | Path,
    scorer: str | Path,
    output: str | Path,
    root: str | Path = ROOT,
    require_no_predictions: bool,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    corpus_path = Path(corpus_root).resolve()
    gold_path = Path(gold).resolve()
    gate_path = Path(gate).resolve()
    producer_path = Path(producer).resolve()
    runner_path = Path(runner).resolve()
    scorer_path = Path(scorer).resolve()
    output_path = Path(output).resolve()
    for path in (corpus_path, gold_path, gate_path, producer_path, runner_path, scorer_path, output_path.parent):
        _relative(path, root_path)
    if require_no_predictions:
        _assert_no_prediction_artifacts(corpus_path)
    gold_document = _validate_gold_document(json.loads(gold_path.read_text(encoding="utf-8")))
    reviewer_hash = gold_document["targets"][0]["reviewer_identity_hash"]
    artifacts = {
        "gold": _artifact(gold_path, root_path),
        "gate_config": _artifact(gate_path, root_path),
        "benchmark_producer": _artifact(producer_path, root_path),
        "benchmark_runner": _artifact(runner_path, root_path),
        "scorer": _artifact(scorer_path, root_path),
        "sealer": _artifact(Path(__file__).resolve(), root_path),
    }
    manifest: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "benchmark_id": "portfolio-hybrid-v1-1",
        "corpus_id": "portfolio-hybrid-v1-1-public-synthetic",
        "seal_state": gold_document["review_state"],
        "reviewer_identity_hash": reviewer_hash,
        "artifacts": artifacts,
        "gate_config_identity": _validate_gate(gate_path, artifacts["gate_config"]["sha256"]),
        "provider_revisions": deepcopy(EXPECTED_PROVIDER_REVISIONS),
        "provider_revisions_sha256": content_sha256({"provider_revisions": EXPECTED_PROVIDER_REVISIONS}),
        "shared_budget": deepcopy(EXPECTED_SHARED_BUDGET),
        "shared_budget_sha256": content_sha256({"shared_budget": EXPECTED_SHARED_BUDGET}),
        "shared_context_policy": deepcopy(EXPECTED_CONTEXT_POLICY),
        "shared_context_policy_sha256": content_sha256({"shared_context_policy": EXPECTED_CONTEXT_POLICY}),
        "screenshots": _screenshots(corpus_path, root_path, gold_document["review_state"], reviewer_hash),
        "gold_contract_version": GOLD_CONTRACT_VERSION,
        "gold_records": gold_document["targets"],
        "gold_records_sha256": content_sha256({"gold_records": gold_document["targets"]}),
        "prediction_counts": {"regression": 0, "holdout": 0, "total": 0},
        "holdout_prediction_count": 0,
        "holdout_development_policy": "sealed_not_used_for_prompt_rule_or_threshold_development",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    manifest["content_sha256"] = content_sha256(manifest)
    verify_corpus_seal(manifest, root=root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return manifest


def _closed(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return deepcopy(dict(value))


def verify_corpus_seal(manifest: Mapping[str, Any], *, root: str | Path = ROOT) -> dict[str, Any]:
    fields = {
        "contract_version", "benchmark_id", "corpus_id", "seal_state", "reviewer_identity_hash",
        "artifacts", "gate_config_identity", "provider_revisions", "provider_revisions_sha256",
        "shared_budget", "shared_budget_sha256", "shared_context_policy", "shared_context_policy_sha256",
        "screenshots", "gold_contract_version", "gold_records", "gold_records_sha256",
        "prediction_counts", "holdout_prediction_count", "holdout_development_policy",
        "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
    }
    sealed = _closed(manifest, fields, "corpus seal")
    if sealed["contract_version"] != CONTRACT_VERSION:
        raise ValueError("corpus seal contract version mismatch")
    if sealed["content_sha256"] != content_sha256({key: value for key, value in sealed.items() if key != "content_sha256"}):
        raise ValueError("corpus seal content_sha256 mismatch")
    if sealed["provider_revisions"] != EXPECTED_PROVIDER_REVISIONS:
        raise ValueError("provider revisions differ from the frozen model revisions")
    if sealed["shared_budget"] != EXPECTED_SHARED_BUDGET:
        raise ValueError("shared budget differs from the frozen budget")
    if sealed["shared_context_policy"] != EXPECTED_CONTEXT_POLICY:
        raise ValueError("shared context policy differs from the frozen context policy")
    for field in ("provider_revisions", "shared_budget", "shared_context_policy"):
        if sealed[f"{field}_sha256"] != content_sha256({field: sealed[field]}):
            raise ValueError(f"{field} SHA mismatch")
    if sealed["prediction_counts"] != {"regression": 0, "holdout": 0, "total": 0} or sealed["holdout_prediction_count"] != 0:
        raise ValueError("sealed corpus must contain zero predictions")
    if sealed["artifact_is_authorization"] is not False or sealed["execute_binding_enabled"] is not False:
        raise ValueError("corpus seal cannot grant execution authority")
    if sealed["seal_state"] not in {"pending_independent_review", "approved"}:
        raise ValueError("seal review state is invalid")
    if _SHA_RE.fullmatch(str(sealed["reviewer_identity_hash"])) is None:
        raise ValueError("reviewer identity hash is invalid")
    if sealed["seal_state"] == "approved" and sealed["reviewer_identity_hash"] in {
        PENDING_REVIEWER_IDENTITY_HASH,
        ANNOTATOR_IDENTITY_HASH,
    }:
        raise ValueError("approved seal requires an independent reviewer identity")
    root_path = Path(root).resolve()
    expected_artifact_paths = {
        "gold": "tests/fixtures/portfolio_hybrid_v1_1/gold.v1.json",
        "gate_config": "configs/benchmarks/portfolio_hybrid_v1_1_gate.json",
        "benchmark_producer": "app/learn/hybrid/benchmark.py",
        "benchmark_runner": "scripts/run_portfolio_hybrid_v1_1_benchmark.py",
        "scorer": "app/learn/hybrid/benchmark_scorer_v1.py",
        "sealer": "scripts/seal_portfolio_hybrid_v1_1_corpus.py",
    }
    artifacts = _closed(sealed["artifacts"], set(expected_artifact_paths), "artifacts")
    for name, expected_path in expected_artifact_paths.items():
        item = _closed(artifacts[name], {"path", "sha256"}, f"artifacts.{name}")
        if item["path"] != expected_path:
            raise ValueError(f"artifact path mismatch: {name}")
        if _file_sha256(_inside(root_path, item["path"])) != item["sha256"]:
            raise ValueError(f"artifact seal mismatch: {name}")
    gate_identity = _validate_gate(
        _inside(root_path, artifacts["gate_config"]["path"]), artifacts["gate_config"]["sha256"]
    )
    if sealed["gate_config_identity"] != gate_identity:
        raise ValueError("gate config identity mismatch")
    gold_document = _validate_gold_document(
        json.loads(_inside(root_path, artifacts["gold"]["path"]).read_text(encoding="utf-8"))
    )
    if sealed["gold_contract_version"] != GOLD_CONTRACT_VERSION or sealed["gold_records"] != gold_document["targets"]:
        raise ValueError("sealed Gold records differ from the canonical Gold artifact")
    if sealed["gold_records_sha256"] != content_sha256({"gold_records": sealed["gold_records"]}):
        raise ValueError("Gold records SHA mismatch")
    if gold_document["review_state"] != sealed["seal_state"]:
        raise ValueError("Gold and seal review states differ")
    if any(item["reviewer_identity_hash"] != sealed["reviewer_identity_hash"] for item in sealed["gold_records"]):
        raise ValueError("Gold reviewer identity mismatch")
    screenshots = sealed["screenshots"]
    if not isinstance(screenshots, list) or len(screenshots) != 24:
        raise ValueError("sealed corpus must contain exactly 24 screenshots")
    expected_screen_paths = [
        f"tests/fixtures/portfolio_hybrid_v1_1/corpus/{'regression' if index <= 12 else 'holdout'}/case-{index:03d}.png"
        for index in range(1, 25)
    ]
    if [item.get("path") for item in screenshots if isinstance(item, Mapping)] != expected_screen_paths:
        raise ValueError("screenshot enumeration mismatch")
    hashes: set[str] = set()
    screen_ids: set[str] = set()
    screen_fields = {
        "screen_id", "partition", "path", "sha256", "width", "height", "layout_id", "title",
        "surface", "density", "precision_case", "source_kind", "source_provenance",
        "reviewer_identity_hash", "review_status", "privacy_review_status",
    }
    for index, item in enumerate(screenshots, start=1):
        screen = _closed(item, screen_fields, "screenshot")
        path = _inside(root_path, screen["path"])
        if _file_sha256(path) != screen["sha256"]:
            raise ValueError(f"screenshot seal mismatch: {screen['screen_id']}")
        if png_dimensions(path) != (screen["width"], screen["height"]) or (screen["width"], screen["height"]) != (1280, 720):
            raise ValueError(f"screenshot dimensions mismatch: {screen['screen_id']}")
        spec = _LAYOUT_CONTROLS[index - 1]
        if (screen["layout_id"], screen["title"], screen["surface"], screen["density"], screen["precision_case"]) != spec[:5]:
            raise ValueError(f"screenshot metadata mismatch: {screen['screen_id']}")
        expected_partition = "regression" if index <= 12 else "holdout"
        if screen["screen_id"] != f"case-{index:03d}" or screen["partition"] != expected_partition:
            raise ValueError("screenshot partition identity mismatch")
        expected_provenance = "existing_five_screen_regression" if index <= 5 else "public_synthetic_new"
        if screen["source_provenance"] != expected_provenance or screen["source_kind"] != "privacy_safe_synthetic":
            raise ValueError("screenshot provenance mismatch")
        if screen["review_status"] != sealed["seal_state"] or screen["privacy_review_status"] != sealed["seal_state"]:
            raise ValueError("screenshot review state mismatch")
        if screen["reviewer_identity_hash"] != sealed["reviewer_identity_hash"]:
            raise ValueError("screenshot reviewer identity mismatch")
        hashes.add(screen["sha256"])
        screen_ids.add(screen["screen_id"])
    if len(hashes) != 24 or len(screen_ids) != 24:
        raise ValueError("screenshot paths and hashes must be disjoint")
    targets = sealed["gold_records"]
    if not 100 <= len(targets) <= 200 or sum(item["partition"] == "holdout" for item in targets) < 50:
        raise ValueError("Gold target coverage is outside the frozen gate")
    if sealed["holdout_development_policy"] != "sealed_not_used_for_prompt_rule_or_threshold_development":
        raise ValueError("holdout development policy mismatch")
    return sealed


def load_and_verify_corpus_seal(path: str | Path, *, root: str | Path = ROOT) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    value = json.loads(raw.decode("utf-8"))
    canonical = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != canonical:
        raise ValueError("manifest bytes are not canonical")
    return verify_corpus_seal(value, root=root)


def provider_manifest_projection(
    manifest: Mapping[str, Any], *, partition: str
) -> dict[str, Any]:
    if partition not in {"regression", "holdout"}:
        raise ValueError("partition must be regression or holdout")
    targets = manifest.get("gold_records")
    screens = manifest.get("screenshots")
    if not isinstance(targets, list) or not isinstance(screens, list):
        raise ValueError("verified corpus seal is required")
    by_id = {item["screen_id"]: item for item in screens}
    projection = {
        "contract_version": PROJECTION_CONTRACT_VERSION,
        "benchmark_ref": {
            "id": manifest["benchmark_id"],
            "content_sha256": manifest["content_sha256"],
        },
        "corpus_id": manifest["corpus_id"],
        "partition": partition,
        "provider_revisions": deepcopy(manifest["provider_revisions"]),
        "shared_budget": deepcopy(manifest["shared_budget"]),
        "shared_context_policy": deepcopy(manifest["shared_context_policy"]),
        "cases": [
            {
                "case_id": target["target_id"],
                "partition": partition,
                "image_ref": {
                    "path": by_id[target["screen_id"]]["path"],
                    "sha256": by_id[target["screen_id"]]["sha256"],
                },
                "goal": target["goal"],
            }
            for target in targets
            if target["partition"] == partition
        ],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    from app.learn.hybrid.benchmark import contains_gold_fields

    if contains_gold_fields(projection):
        raise ValueError("provider projection contains Gold/private fields")
    return projection


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--scorer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-no-predictions", action="store_true")
    parser.add_argument("--prepare-synthetic-corpus", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.prepare_synthetic_corpus:
            generate_synthetic_corpus(args.corpus_root, args.gold)
        manifest = seal_corpus(
            corpus_root=args.corpus_root,
            gold=args.gold,
            gate=args.gate,
            producer=args.producer,
            runner=args.runner,
            scorer=args.scorer,
            output=args.output,
            require_no_predictions=args.require_no_predictions,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"corpus seal failed: {error}") from error
    print(json.dumps({
        "status": "SEALED_PENDING_INDEPENDENT_REVIEW" if manifest["seal_state"] != "approved" else "SEALED_APPROVED",
        "content_sha256": manifest["content_sha256"],
        "screen_count": len(manifest["screenshots"]),
        "target_count": len(manifest["gold_records"]),
        "holdout_prediction_count": manifest["holdout_prediction_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
