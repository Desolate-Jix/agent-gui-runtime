"""OCR 有界线程避免小裁图线程调度开销，不修改模型和识别参数。"""
import sys
from types import SimpleNamespace

import pytest

from app.core.ocr_service import OCRService


@pytest.mark.parametrize("cpus, expected", [(28, 8), (4, 4), (None, 1)])
def test_default_thread_budget_is_bounded_and_engine_is_reused(monkeypatch, cpus, expected):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    calls = []
    engine = object()
    def create(**kwargs):
        calls.append(kwargs)
        return engine
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", SimpleNamespace(RapidOCR=create))
    service = OCRService()
    assert service._get_rapidocr_engine() is engine
    assert service._get_rapidocr_engine() is engine
    assert calls == [{"intra_op_num_threads": expected, "inter_op_num_threads": 1}]


@pytest.mark.parametrize("cpus, requested, expected", [(28, 4, 4), (2, 4, 2)])
def test_explicit_thread_budget_is_available_for_other_machines(monkeypatch, cpus, requested, expected):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: cpus)
    calls = []
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime",
        SimpleNamespace(RapidOCR=lambda **kwargs: calls.append(kwargs) or object()))
    OCRService(cpu_threads=requested)._get_rapidocr_engine()
    assert calls[0] == {"intra_op_num_threads": expected, "inter_op_num_threads": 1}


@pytest.mark.parametrize("invalid", [0, -1, True, 2.5, "8"])
def test_invalid_explicit_thread_budget_fails_before_loading(invalid):
    with pytest.raises(ValueError, match="cpu_threads"):
        OCRService(cpu_threads=invalid)
