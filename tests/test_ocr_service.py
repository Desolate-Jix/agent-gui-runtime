from __future__ import annotations

from app.core.ocr_service import OCRService


def test_parse_matches_supports_rapidocr_shape() -> None:
    service = OCRService()
    raw = [
        [
            [[10.0, 20.0], [50.0, 20.0], [50.0, 40.0], [10.0, 40.0]],
            "开始测试",
            0.93,
        ]
    ]

    matches = service._parse_matches(raw)

    assert len(matches) == 1
    assert matches[0].text == "开始测试"
    assert matches[0].score == 0.93
    assert matches[0].bbox.x == 10
    assert matches[0].bbox.y == 20
    assert matches[0].bbox.width == 40
    assert matches[0].bbox.height == 20


def test_scan_image_falls_back_to_rapidocr_when_paddle_fails(tmp_path) -> None:
    service = OCRService()
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(b"fake")

    service._scan_with_paddle = lambda path: (_ for _ in ()).throw(RuntimeError("paddle failed"))  # type: ignore[method-assign]
    service._scan_with_rapidocr = lambda path: [  # type: ignore[method-assign]
        [
            [[0.0, 0.0], [12.0, 0.0], [12.0, 10.0], [0.0, 10.0]],
            "OK",
            0.88,
        ]
    ]

    result = service.scan_image(str(image_path))

    assert result.metadata["engine"] == "rapidocr_onnxruntime"
    assert result.metadata["match_count"] == 1
    assert result.matches[0].text == "OK"
