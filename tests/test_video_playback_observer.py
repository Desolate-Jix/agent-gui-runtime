"""播放器观察只读像素和绑定文件，不采集桌面。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.execution import video_playback_observer as observer


def frame(root, name="frame", *, pause=True):
    path = root / (name + ".png")
    image = Image.new("RGB", (400, 300), "black")
    if pause:
        draw = ImageDraw.Draw(image)
        draw.rectangle((25, 252, 29, 268), fill="white")
        draw.rectangle((35, 252, 39, 268), fill="white")
    image.save(path)
    return {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "capture_id": name, "window_identity": {"handle": 1, "process_id": 2},
            "image_size": {"width": 400, "height": 300},
            "window_rect": {"x": 0, "y": 0, "width": 400, "height": 300}}


class Grounder:
    def __init__(self):
        self.calls = []

    def ground(self, **kw):
        self.calls.append(kw)
        return {"action_executed": False, "provider": {}, "result": {
            "schema_version": "grounding.v1", "request_id": kw["request_id"],
            "capture_id": kw["capture"]["capture_id"], "status": "found",
            "coordinate_space": "capture_image_pixels", "image_size": {"width": 400, "height": 300},
            "selected_candidate_id": "player", "candidates": [{"id": "player", "label": "player",
            "bbox": {"x": 10, "y": 10, "width": 380, "height": 280},
            "click_point": {"x": 200, "y": 150}, "evidence_source": "api_visual"}]}}


def locate(root, original, grounder=None):
    return observer.locate_player(SimpleNamespace(), original, goal="The intended video plays",
        session_dir=root, remaining_seconds=5.0, api_grounder=grounder or Grounder())


def test_locator_once_and_per_call_budget(tmp_path):
    original, grounder = frame(tmp_path), Grounder()
    value = locate(tmp_path, original, grounder)
    assert len(grounder.calls) == 1
    assert 0 < grounder.calls[0]["timeout_seconds"] <= 5
    assert value["region"]["bbox"] == [10, 10, 380, 280]
    assert value["evidence"]["source_frame"] == original
    assert value["refs"]


def test_pixels_progress_and_cache_replay(tmp_path, monkeypatch):
    original = frame(tmp_path)
    locator = locate(tmp_path, original)
    calls = []
    def ocr(image):
        calls.append(image.size)
        return [{"text": "00:03 / 02:00", "score": .99, "bbox": [60, 244, 140, 25]}]
    monkeypatch.setattr(observer, "_ocr_rows", ocr)
    first = observer.observe_player_frame(original, locator, session_dir=tmp_path)
    assert first == {"capture_id": "frame", "position_seconds": 3.0, "state": "playing"}
    assert observer.observe_player_frame(original, locator, session_dir=tmp_path) == first
    assert len(calls) == 1


@pytest.mark.parametrize("text,state", [("Advertisement", "ad"), ("Loading", "loading"),
    ("Paused", "paused"), ("Playback error", "error"), ("Video ended", "ended")])
def test_blocker_overrides_progress(tmp_path, monkeypatch, text, state):
    original = frame(tmp_path)
    locator = locate(tmp_path, original)
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: [
        {"text": "00:03 / 02:00", "score": .99, "bbox": [60, 244, 140, 25]},
        {"text": text, "score": .99, "bbox": [100, 90, 150, 30]}])
    assert observer.observe_player_frame(original, locator, session_dir=tmp_path)["state"] == state


def test_missing_controls_and_ocr_error_are_unknown(tmp_path, monkeypatch):
    original = frame(tmp_path, pause=False)
    locator = locate(tmp_path, original)
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: [])
    assert observer.observe_player_frame(original, locator, session_dir=tmp_path)["state"] == "unknown"
    fresh = frame(tmp_path, "other", pause=False)
    def failed(_):
        raise RuntimeError("ocr unavailable")
    monkeypatch.setattr(observer, "_ocr_rows", failed)
    assert observer.observe_player_frame(fresh, locator, session_dir=tmp_path)["state"] == "unknown"


@pytest.mark.parametrize("change", ["hash", "window", "geometry", "region", "outside"])
def test_tamper_rejected_before_ocr(tmp_path, monkeypatch, change):
    original = frame(tmp_path)
    locator = locate(tmp_path, original)
    current = deepcopy(original)
    if change == "hash":
        Path(current["image_path"]).write_bytes(b"changed")
    elif change == "window":
        current["window_identity"]["handle"] = 2
    elif change == "geometry":
        current["window_rect"]["x"] = 10
    elif change == "region":
        locator["region"]["bbox"][0] = 300
    else:
        current["image_path"] = str(tmp_path.parent / "outside.png")
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: pytest.fail("OCR before binding validation"))
    with pytest.raises(ValueError, match="video_playback"):
        observer.observe_player_frame(current, locator, session_dir=tmp_path)


def test_progress_without_playing_control_is_not_trusted(tmp_path, monkeypatch):
    original = frame(tmp_path, pause=False)
    locator = locate(tmp_path, original)
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: pytest.fail("无播放控件不能取得本地证明，不应运行OCR"))
    assert observer.observe_player_frame(original, locator, session_dir=tmp_path)["state"] == "unknown"


@pytest.mark.parametrize("text", ["Advertisement", "Paused", "Playback error"])
def test_hidden_controls_with_negative_text_remain_unknown_for_semantic_review(tmp_path, monkeypatch, text):
    original = frame(tmp_path, pause=False)
    path = Path(original["image_path"])
    with Image.open(path) as image:
        image = image.copy()
        ImageDraw.Draw(image).text((100, 100), text, fill="white")
        image.save(path)
    original["sha256"] = sha256(path.read_bytes()).hexdigest()
    locator = locate(tmp_path, original)
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: pytest.fail("无控件负例只能保留未知，不能伪称本地识别"))
    value = observer.observe_player_frame(original, locator, session_dir=tmp_path)
    assert value == {"capture_id": "frame", "state": "unknown", "position_seconds": None}


def test_layout_change_cannot_reuse_player_region(tmp_path, monkeypatch):
    original = frame(tmp_path)
    locator = locate(tmp_path, original)
    current = frame(tmp_path, "scrolled")
    path = Path(current["image_path"])
    with Image.open(path) as image:
        image = image.copy()
        ImageDraw.Draw(image).rectangle((0, 0, 399, 8), fill="white")
        image.save(path)
    current["sha256"] = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: pytest.fail("页面边缘变化后不能继续信任原区域"))
    value = observer.observe_player_frame(current, locator, session_dir=tmp_path)
    assert value["state"] == "unknown" and value["position_seconds"] is None


def test_white_page_with_browser_chrome_waits_without_ocr_or_grounding(tmp_path, monkeypatch):
    original = frame(tmp_path)
    path = Path(original["image_path"])
    image = Image.new("RGB", (400, 300), "white")
    ImageDraw.Draw(image).rectangle((0, 0, 399, 49), fill="gray")
    image.save(path)
    original["sha256"] = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(observer, "_ocr_rows", lambda _: pytest.fail("就绪检查不能启动OCR"))
    assert observer.page_loading(original, session_dir=tmp_path) is True


@pytest.mark.parametrize("color", ["black", "navy"])
def test_dark_player_surface_is_left_for_localization(tmp_path, color):
    original = frame(tmp_path)
    path = Path(original["image_path"])
    Image.new("RGB", (400, 300), color).save(path)
    original["sha256"] = sha256(path.read_bytes()).hexdigest()
    assert observer.page_loading(original, session_dir=tmp_path) is False


def test_absent_locator_preserves_provider_timing_diagnostic(tmp_path):
    import json
    class AbsentGrounder(Grounder):
        def ground(self, **kw):
            value = super().ground(**kw)
            value["result"].update(status="absent", candidates=[], selected_candidate_id=None)
            value["provider"] = {"http_trace": {"total_ms": 123.0, "request_bytes": 100}}
            return value
    with pytest.raises(ValueError, match="player_ambiguous"):
        locate(tmp_path, frame(tmp_path), AbsentGrounder())
    paths = list((tmp_path / "video-playback-observer").glob("*-diagnostic.json"))
    assert len(paths) == 1
    diagnostic = json.loads(paths[0].read_text(encoding="utf-8"))
    assert diagnostic["grounding_result"]["status"] == "absent"
    assert diagnostic["provider"]["http_trace"]["total_ms"] == 123.0
