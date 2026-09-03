from __future__ import annotations

from copy import deepcopy

import pytest


def _runtime_request() -> dict[str, object]:
    return {
        "contract_version": "hybrid_qwen_binding_request_v1",
        "screenshot": {"image_size": {"width": 1280, "height": 720}},
        "candidates": [
            {"candidate_id": "candidate/one", "bbox_original": [1, 2, 30, 40], "active": True},
            {"candidate_id": "candidate/two", "bbox_original": [50, 60, 80, 90], "active": False},
        ],
        "capture_identity": {"capture_id": "capture/test"},
        "context_ref": {"id": "ctx/test", "content_sha256": "1" * 64},
    }


def test_omni_native_contract_accepts_only_official_minimal_fields() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output

    parsed = parse_omni_native_output({"items": [{"bbox": [0.1, 0.2, 0.3, 0.4], "type": "text", "content": "搜索", "interactivity": True}]})
    assert parsed[0].content == "搜索"
    assert parsed[0].bbox == (0.1, 0.2, 0.3, 0.4)


def test_omni_native_contract_rejects_invalid_normalized_boxes_and_extra_fields() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output

    with pytest.raises(ValueError, match="bbox"):
        parse_omni_native_output({"items": [{"bbox": [0, 0, 1.1, 1], "type": "text", "content": "x", "interactivity": False}]})
    with pytest.raises(ValueError, match="closed"):
        parse_omni_native_output({"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "x", "interactivity": False, "source_item_id": "bad"}]})


def test_qwen_projection_keeps_full_runtime_request_unchanged() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection

    request = _runtime_request(); before = deepcopy(request)
    projection = build_qwen_model_projection(request)
    assert request == before
    assert projection is not request


def test_qwen_projection_uses_short_ordinals_and_exact_geometry() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection

    assert build_qwen_model_projection(_runtime_request()) == {"image_size": [1280, 720], "candidates": [{"i": 0, "box": [1, 2, 30, 40], "active": True}, {"i": 1, "box": [50, 60, 80, 90], "active": False}]}


def test_qwen_expansion_restores_stable_ids_and_existing_contract() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection, expand_qwen_model_response

    request = _runtime_request(); projection = build_qwen_model_projection(request)
    result = expand_qwen_model_response({"bindings": [{"i": 0, "role": "button", "label": "新建", "status": "BOUND", "confidence": .9}, {"i": 1, "role": "button", "label": "取消", "status": "UNBOUND", "confidence": .1}]}, projection=projection, runtime_request=request)
    assert result["contract_version"] == "hybrid_qwen_bindings_v1"
    assert [item["candidate_id"] for item in result["bindings"]] == ["candidate/one", "candidate/two"]


def test_qwen_expansion_rejects_missing_duplicate_unknown_and_reordered_ordinals() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection, expand_qwen_model_response

    request = _runtime_request(); projection = build_qwen_model_projection(request)
    base = [{"i": 0, "role": "button", "label": "a", "status": "BOUND", "confidence": .9}, {"i": 1, "role": "button", "label": "b", "status": "BOUND", "confidence": .9}]
    for bindings in (base[:1], [base[0], base[0]], [{**base[0], "i": 3}, base[1]], list(reversed(base))):
        with pytest.raises(ValueError, match="ordinal"):
            expand_qwen_model_response({"bindings": bindings}, projection=projection, runtime_request=request)


def test_vista_contract_accepts_only_bare_normalized_pair() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_vista_normalized_point

    assert parse_vista_normalized_point("[437, 612]\n") == (437.0, 612.0)
    for raw in ('{"x": 1}', '[1,2,3]', '[NaN, 2]', '[1, 2] prose'):
        with pytest.raises(ValueError):
            parse_vista_normalized_point(raw)


def test_vista_restore_rejects_outside_roi_without_clipping() -> None:
    from app.learn.hybrid.simple_native_contracts import restore_vista_point_to_capture

    assert restore_vista_point_to_capture((0, 1000), roi_xyxy=(10, 20, 110, 220)) == (10, 220)
    with pytest.raises(ValueError, match="outside"):
        restore_vista_point_to_capture((1001, 0), roi_xyxy=(10, 20, 110, 220))


def test_native_contracts_preserve_utf8_text() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output, parse_vista_normalized_point

    assert parse_omni_native_output({"items": [{"bbox": [0, 0, 1, 1], "type": "文本", "content": "申请职位", "interactivity": False}]})[0].content == "申请职位"
    assert parse_vista_normalized_point("[1, 2]") == (1.0, 2.0)
