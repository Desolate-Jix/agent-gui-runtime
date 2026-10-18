from __future__ import annotations

import sys
from types import SimpleNamespace

from app.core.ocr_service import OCRService


def test_ocr_prepare_reuses_one_service_engine_and_reports_cold_reuse_timing(monkeypatch) -> None:
    calls: list[dict[str, int]] = []
    engine = object()

    def create(**kwargs):
        calls.append(kwargs)
        return engine

    monkeypatch.setitem(
        sys.modules,
        "rapidocr_onnxruntime",
        SimpleNamespace(RapidOCR=create),
    )
    service = OCRService(cpu_threads=2)

    cold = service.prepare()
    reused = service.prepare()

    assert cold["status"] == "ready"
    assert cold["engine"] == "rapidocr_onnxruntime"
    assert cold["cold"] is True
    assert cold["reused"] is False
    assert cold["timing"]["mode"] == "cold"
    assert cold["timing"]["engine_acquisition_seconds"] >= 0
    assert cold["timing"]["prepare_seconds"] >= 0

    assert reused["status"] == "ready"
    assert reused["engine"] == "rapidocr_onnxruntime"
    assert reused["cold"] is False
    assert reused["reused"] is True
    assert reused["timing"]["mode"] == "reuse"
    assert reused["timing"]["engine_acquisition_seconds"] >= 0
    assert reused["timing"]["prepare_seconds"] >= 0
    assert calls == [{"intra_op_num_threads": 2, "inter_op_num_threads": 1}]


def test_ocr_prepare_preserves_fallback_error_in_ready_result(monkeypatch) -> None:
    service = OCRService()
    paddle_engine = object()

    def fail_rapid():
        raise RuntimeError("rapid unavailable")

    monkeypatch.setattr(service, "_get_rapidocr_engine", fail_rapid)
    monkeypatch.setattr(service, "_get_paddle_engine", lambda: paddle_engine)

    result = service.prepare()

    assert result["status"] == "ready"
    assert result["engine"] == "rapidocr_paddle"
    assert result["cold"] is True
    assert result["backend_errors"] == ["rapidocr_onnxruntime: rapid unavailable"]


def test_ocr_prepare_raises_when_all_backends_fail(monkeypatch) -> None:
    service = OCRService()
    monkeypatch.setattr(
        service,
        "_get_rapidocr_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("rapid unavailable")),
    )
    monkeypatch.setattr(
        service,
        "_get_paddle_engine",
        lambda: (_ for _ in ()).throw(RuntimeError("paddle unavailable")),
    )

    try:
        service.prepare()
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover - assertion below is the intended path
        raise AssertionError("prepare should fail when every backend fails")

    assert "rapidocr_onnxruntime: rapid unavailable" in message
    assert "rapidocr_paddle: paddle unavailable" in message
