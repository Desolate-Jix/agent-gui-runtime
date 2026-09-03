from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image


def _cases(tmp_path: Path) -> list[object]:
    from app.learn.hybrid.simple_native_smoke import ProviderCase

    result = []
    for index in range(1, 6):
        path = tmp_path / "public-regression" / f"case-{index:03d}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 80), color=(index, 10, 20)).save(path)
        result.append(
            ProviderCase(
                case_id=f"case-{index:03d}",
                image_path=path,
                image_size=(100, 80),
                image_sha256=sha256(path.read_bytes()).hexdigest(),
                goals=tuple(f"goal-{index}-{target}" for target in range(5)),
            )
        )
    return result


def test_runner_seals_omni_geometry_then_uses_authoritative_qwen_parser(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.simple_native_smoke import (
        SimpleNativeSlots,
        run_simple_native_regression_diagnostic,
    )

    projections: list[dict[str, object]] = []

    def qwen(_image: Path, projection: dict[str, object]) -> object:
        projections.append(projection)
        return {
            "bindings": [
                {
                    "i": candidate["i"],
                    "role": "button",
                    "label": "replay",
                    "status": "BOUND",
                    "confidence": 0.8,
                }
                for candidate in projection["candidates"]
            ]
        }

    slots = SimpleNativeSlots(
        omni=lambda _image: {
            "items": [
                {
                    "bbox": [0.1, 0.25, 0.3, 0.5],
                    "type": "text",
                    "content": "replay",
                    "interactivity": True,
                }
            ]
        },
        qwen=qwen,
        vista=lambda _image, _target: "[500,500]",
    )

    artifact = run_simple_native_regression_diagnostic(
        cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts"
    )
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    first = payload["cases"][0]
    omni = next(entry for entry in first["trace"] if entry["slot"] == "omni")
    qwen_trace = next(entry for entry in first["trace"] if entry["slot"] == "qwen")

    assert projections[0]["candidates"] == [
        {"i": 0, "box": [10, 20, 30, 40], "active": True}
    ]
    assert omni["provider_result"]["items"][0]["capture_bbox"] == [10, 20, 30, 40]
    assert omni["inventory"]["contract_version"] == "hybrid_omni_inventory_v1"
    assert qwen_trace["runtime_request"]["contract_version"] == "hybrid_qwen_binding_request_v1"
    assert qwen_trace["wire_input"] == projections[0]
    assert qwen_trace["parsed"]["contract_version"] == "hybrid_qwen_bindings_v1"
    assert qwen_trace["runtime_request_sha256"] == sha256(
        json.dumps(
            qwen_trace["runtime_request"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert first["capture"]["screenshot_sha256"] == _cases(tmp_path)[0].image_sha256
    assert first["capture"]["context_availability"] == {
        "ocr": "unavailable_empty",
        "uia": "unavailable_empty",
    }


def test_one_omni_item_cannot_consume_five_qwen_bindings(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import (
        SimpleNativeSlots,
        run_simple_native_regression_diagnostic,
    )

    vista_calls: list[Path] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: {
            "items": [
                {
                    "bbox": [0.1, 0.1, 0.2, 0.2],
                    "type": "text",
                    "content": "only",
                    "interactivity": True,
                }
            ]
        },
        qwen=lambda _image, _projection: {
            "bindings": [
                {
                    "i": index,
                    "role": "button",
                    "label": "invented",
                    "status": "BOUND",
                    "confidence": 0.9,
                }
                for index in range(5)
            ]
        },
        vista=lambda image, _target: vista_calls.append(image) or "[500,500]",
    )

    artifact = run_simple_native_regression_diagnostic(
        cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts"
    )
    qwen = next(
        entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "qwen"
    )
    assert "ordinal" in qwen["parse_error"]
    assert vista_calls == []
