from __future__ import annotations

import pytest
from types import SimpleNamespace
from PIL import Image

from app.core.ocr_service import OCRService


def _line(text: str, chunks: list[str], scores: list[float] | None = None):
    quads = []
    cursor = 10
    for chunk in chunks:
        width = max(4, len(chunk) * 8)
        quads.append([[cursor, 10], [cursor + width, 10], [cursor + width, 26], [cursor, 26]])
        cursor += width + 2
    return [
        [[10, 10], [cursor, 10], [cursor, 26], [10, 26]],
        text,
        0.96,
        quads,
        chunks,
        scores or [0.9] * len(chunks),
    ]


def test_scan_words_preserves_unequal_word_boxes_and_metadata(tmp_path) -> None:
    service = OCRService()
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 96)).save(image_path)
    service._get_rapidocr_engine = lambda: lambda path, **kwargs: (  # type: ignore[method-assign]
        [_line("Wikipedia Dunedin", list("Wikipedia Dunedin"))], []
    )

    result = service.scan_words(str(image_path))

    assert [item.text for item in result.matches] == ["Wikipedia", "Dunedin"]
    assert result.matches[0].bbox.width != result.matches[1].bbox.width
    assert result.matches[0].bbox.x < result.matches[1].bbox.x
    assert result.metadata["granularity"] == "word"
    assert result.metadata["provider"] == "rapidocr_onnxruntime"


def test_scan_words_supports_unicode_and_punctuation(tmp_path) -> None:
    service = OCRService()
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 96)).save(image_path)
    service._get_rapidocr_engine = lambda: lambda path, **kwargs: (  # type: ignore[method-assign]
        [_line("你好，世界", list("你好，世界"))], []
    )

    result = service.scan_words(str(image_path))

    assert [item.text for item in result.matches] == ["你好", "世界"]


@pytest.mark.parametrize(
    "line",
    [
        _line("ab", ["a"]),
        _line("ab", ["a", "b"], [0.9]),
        [[[0, 0], [10, 0], [10, 10], [0, 10]], "ab", 0.9, None, None, None],
    ],
)
def test_scan_words_rejects_invalid_character_metadata(tmp_path, line) -> None:
    service = OCRService()
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 96)).save(image_path)
    service._get_rapidocr_engine = lambda: lambda path, **kwargs: ([line], [])  # type: ignore[method-assign]

    with pytest.raises(ValueError):
        service.scan_words(str(image_path))


def test_scan_words_empty_ocr_returns_empty(tmp_path) -> None:
    service = OCRService()
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 96)).save(image_path)
    service._get_rapidocr_engine = lambda: lambda path, **kwargs: (None, None)  # type: ignore[method-assign]

    result = service.scan_words(str(image_path))

    assert result.matches == []


def test_word_scan_keeps_existing_engine_thresholds(tmp_path):
    path = tmp_path / "frame.png"
    Image.new("RGB", (320, 96)).save(path)
    class Engine:
        text_score = .73
        text_det = SimpleNamespace(postprocess_op=SimpleNamespace(box_thresh=.61, unclip_ratio=2.0))
        def __call__(self, path, **kwargs):
            assert kwargs == {"return_word_box": True, "text_score": .73, "box_thresh": .61, "unclip_ratio": 2.0}
            return None, None
    service = OCRService()
    service._rapid_engine = Engine()
    assert service.scan_words(str(path)).matches == []


@pytest.mark.parametrize("change", ["nan", "empty_quad", "short_quad", "missing_words"])
def test_word_geometry_damage_is_explicit(tmp_path, change):
    path = tmp_path / "frame.png"
    Image.new("RGB", (320, 96)).save(path)
    row = _line("word", list("word"))
    if change == "nan":
        row[5][0] = float("nan")
    elif change == "empty_quad":
        row[3][0] = [[1, 1]] * 4
    elif change == "short_quad":
        row[3][0] = [[1, 1]]
    else:
        row = row[:3]
    service = OCRService()
    service._rapid_engine = lambda path, **kwargs: ([row], [])
    with pytest.raises(ValueError):
        service.scan_words(str(path))


def test_small_word_crop_is_upscaled_once_and_boxes_map_to_original(tmp_path):
    path = tmp_path / "small.png"
    Image.new("RGB", (320, 96)).save(path)
    original = path.read_bytes()
    calls = []
    def engine(pixels, **kwargs):
        calls.append(pixels.shape)
        assert pixels.shape == (192, 640, 3)
        return [[[[427, 86], [520, 86], [520, 122], [427, 122]],
                 "Napier", .96,
                 [[[427, 86], [520, 86], [520, 122], [427, 122]]],
                 ["Napier"], [.96]]], None
    service = OCRService()
    service._rapid_engine = engine
    result = service.scan_words(str(path))
    assert calls == [(192, 640, 3)]
    assert result.matches[0].bbox.to_dict() == {"x": 213, "y": 43, "width": 47, "height": 18}
    assert result.matches[0].text == "Napier"
    assert result.metadata["recognition_scale"] == 2
    assert result.metadata["coordinate_space"] == "source_image_pixels"
    assert path.read_bytes() == original


def test_large_word_image_is_not_expanded(tmp_path):
    path = tmp_path / "large.png"
    Image.new("RGB", (2560, 1400)).save(path)
    def engine(pixels, **kwargs):
        assert pixels.shape == (1400, 2560, 3)
        return None, None
    service = OCRService()
    service._rapid_engine = engine
    assert service.scan_words(str(path)).metadata["recognition_scale"] == 1


@pytest.mark.parametrize("separator", [".", " ", "，"])
def test_zero_width_separator_does_not_discard_neighbor_word_geometry(tmp_path, separator):
    path = tmp_path / "page.png"
    Image.new("RGB", (1200, 200)).save(path)
    row = _line("Left" + separator + "Right", ["Left", separator, "Right"])
    row[3][1] = [[44, 10], [44, 10], [44, 26], [44, 26]]
    service = OCRService()
    service._rapid_engine = lambda pixels, **kwargs: ([row], [])

    result = service.scan_words(str(path))

    assert [word.text for word in result.matches] == ["Left", "Right"]
    assert [word.bbox.to_dict() for word in result.matches] == [
        {"x": 10, "y": 10, "width": 32, "height": 16},
        {"x": 54, "y": 10, "width": 40, "height": 16},
    ]


@pytest.mark.parametrize("damage", ["nonfinite", "malformed", "confidence"])
def test_separator_metadata_errors_are_not_silently_ignored(tmp_path, damage):
    path = tmp_path / "page.png"
    Image.new("RGB", (1200, 200)).save(path)
    row = _line("a.b", ["a", ".", "b"])
    if damage == "nonfinite":
        row[3][1][0][0] = float("nan")
    elif damage == "malformed":
        row[3][1] = [[10, 10]]
    else:
        row[5][1] = float("nan")
    service = OCRService()
    service._rapid_engine = lambda pixels, **kwargs: ([row], [])

    with pytest.raises(ValueError):
        service.scan_words(str(path))
