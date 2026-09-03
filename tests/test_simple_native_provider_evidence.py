from __future__ import annotations

from copy import deepcopy
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


def test_vista_receives_persisted_candidate_crop_with_capture_lineage(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.simple_native_smoke import (
        SimpleNativeSlots,
        run_simple_native_regression_diagnostic,
    )

    seen: list[tuple[Path, tuple[int, int]]] = []

    def vista(path: Path, _target: str) -> str:
        with Image.open(path) as opened:
            seen.append((path, opened.size))
        return "[500,500]"

    slots = SimpleNativeSlots(
        omni=lambda _image: {
            "items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]
        },
        qwen=lambda _image, projection: {
            "bindings": [{"i": item["i"], "role": "button", "label": "replay", "status": "BOUND", "confidence": 0.8} for item in projection["candidates"]]
        },
        vista=vista,
    )

    artifact = run_simple_native_regression_diagnostic(
        cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts"
    )
    trace = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")
    source = Path(artifact.cases[0]["capture"]["capture_path"])
    crop = trace["roi_crop"]

    assert seen[0][0].is_file() and seen[0][0] != source
    assert seen[0][1] == (20, 20)
    assert crop["capture_id"] == artifact.cases[0]["capture"]["capture_id"]
    assert crop["capture_sha256"] == artifact.cases[0]["capture"]["screenshot_sha256"]
    assert crop["candidate_id"] == trace["candidate_id"]
    assert crop["roi_xyxy"] == [10, 20, 30, 40]
    assert crop["crop_size"] == {"width": 20, "height": 20}
    assert crop["crop_sha256"] == sha256(seen[0][0].read_bytes()).hexdigest()


def test_vista_bad_capture_sha_and_boundary_point_abstain_without_correction(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.simple_native_smoke import (
        SimpleNativeSlots,
        run_simple_native_regression_diagnostic,
    )

    vista_calls: list[Path] = []

    def qwen(image: Path, projection: dict[str, object]) -> object:
        image.write_bytes(b"tampered-after-capture")
        return {
            "bindings": [{"i": item["i"], "role": "button", "label": "replay", "status": "BOUND", "confidence": 0.8} for item in projection["candidates"]]
        }

    slots = SimpleNativeSlots(
        omni=lambda _image: {
            "items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "replay", "interactivity": True}]
        },
        qwen=qwen,
        vista=lambda image, _target: vista_calls.append(image) or "[0,0]",
    )
    artifact = run_simple_native_regression_diagnostic(
        cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts"
    )

    assert vista_calls == []
    vista_trace = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")
    assert "sha256 mismatch" in vista_trace["parse_error"]
    assert artifact.metrics["abstained"] >= 1


def test_vista_rejects_inactive_and_ambiguous_candidates_before_dispatch(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    vista_calls: list[Path] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [
            {"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "a", "interactivity": False},
            {"bbox": [0.3, 0.3, 0.4, 0.4], "type": "text", "content": "b", "interactivity": True},
            {"bbox": [0.5, 0.5, 0.6, 0.6], "type": "text", "content": "c", "interactivity": True},
        ]},
        qwen=lambda _image, projection: {"bindings": [
            {"i": item["i"], "role": "button", "label": "inactive" if item["i"] == 0 else "duplicate", "status": "BOUND", "confidence": 0.8}
            for item in projection["candidates"]
        ]},
        vista=lambda image, _target: vista_calls.append(image) or "[500,500]",
    )

    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    assert vista_calls == []
    assert artifact.metrics["abstained"] >= 3


def test_scorer_joins_finalized_trace_by_exact_role_and_label(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import (
        SimpleNativeSlots,
        run_simple_native_regression_diagnostic,
        score_simple_native_regression,
    )

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]},
        qwen=lambda _image, projection: {"bindings": [{"i": item["i"], "role": "button", "label": "replay", "status": "BOUND", "confidence": 0.8} for item in projection["candidates"]]},
        vista=lambda _image, _target: "[500,500]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    gold_targets = []
    for case_index in range(1, 6):
        for target_index in range(4):
            gold_targets.append({"partition": "regression", "screen_id": f"case-{case_index:03d}", "role": "button", "label": f"other-{target_index}", "bbox": [70, 60, 90, 75]})
        gold_targets.append({"partition": "regression", "screen_id": f"case-{case_index:03d}", "role": "button", "label": "replay", "bbox": [10, 20, 30, 40]})
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps({"targets": gold_targets}), encoding="utf-8")

    report = score_simple_native_regression(provider_artifact=artifact, gold_path=gold_path)
    assert (report.correct_selected, report.wrong_selected, report.abstained) == (5, 0, 20)


def test_vista_crop_rejects_non_integer_and_outside_geometry(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import _persist_vista_roi_crop

    image = tmp_path / "capture.png"
    Image.new("RGB", (20, 20)).save(image)
    capture = {
        "capture_path": str(image),
        "capture_id": "capture/test",
        "screenshot_sha256": sha256(image.read_bytes()).hexdigest(),
        "image_size": {"width": 20, "height": 20},
    }
    for bbox in ([1.5, 1, 3, 3], [-1, 1, 3, 3], [1, 1, 21, 3]):
        try:
            _persist_vista_roi_crop(
                capture=capture,
                candidate={"candidate_id": "candidate/test", "bbox_original": bbox},
                artifact_dir=tmp_path,
            )
        except ValueError as error:
            assert "integer in-capture" in str(error)
        else:
            raise AssertionError("invalid candidate geometry reached VISTA crop persistence")


def test_vista_strict_boundary_point_is_not_clipped_or_scored(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]},
        qwen=lambda _image, projection: {"bindings": [{"i": item["i"], "role": "button", "label": "replay", "status": "BOUND", "confidence": 0.8} for item in projection["candidates"]]},
        vista=lambda _image, _target: "[0,0]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    trace = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")
    assert "strict candidate interior" in trace["parse_error"]
    assert "capture_point" not in trace


def test_scorer_abstains_duplicate_semantics_and_rejects_unsealed_tampering(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic, score_simple_native_regression
    from app.learn.recognition.uei.canonical import seal_immutable

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]},
        qwen=lambda _image, projection: {"bindings": [{"i": item["i"], "role": "button", "label": "replay", "status": "BOUND", "confidence": 0.8} for item in projection["candidates"]]},
        vista=lambda _image, _target: "[500,500]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    gold = {"targets": [
        {"partition": "regression", "screen_id": f"case-{case_index:03d}", "role": "button", "label": label, "bbox": [10, 20, 30, 40]}
        for case_index in range(1, 6)
        for label in ("replay", "missing-1", "missing-2", "missing-3", "missing-4")
    ]}
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    first_vista = next(entry for entry in payload["cases"][0]["trace"] if entry.get("capture_point"))
    payload["cases"][0]["trace"].append(deepcopy(first_vista))
    payload.pop("content_sha256")
    artifact.path.write_text(json.dumps(seal_immutable(payload), ensure_ascii=False), encoding="utf-8")
    report = score_simple_native_regression(provider_artifact=artifact, gold_path=gold_path)
    assert (report.correct_selected, report.abstained) == (4, 21)

    tampered = json.loads(artifact.path.read_text(encoding="utf-8"))
    tampered["cases"][0]["trace"] = []
    artifact.path.write_text(json.dumps(tampered), encoding="utf-8")
    try:
        score_simple_native_regression(provider_artifact=artifact, gold_path=gold_path)
    except ValueError as error:
        assert "finalized sealed" in str(error)
    else:
        raise AssertionError("unsealed provider trace reached the scorer")
