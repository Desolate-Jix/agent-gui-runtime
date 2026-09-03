from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest


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
                goals=(
                    "Select the button labeled 'replay'",
                    *(f"Select the button labeled 'missing-{target}'" for target in range(1, 5)),
                ),
            )
        )
    return result


def _goal_response(projection: dict[str, object], *, bound_goal_indexes: set[int] | None = None) -> dict[str, object]:
    goals = projection["goals"]
    candidates = projection["candidates"]
    assert isinstance(goals, list) and isinstance(candidates, list)
    bound = bound_goal_indexes if bound_goal_indexes is not None else {0}
    return [
        {
            "goal_index": goal["goal_index"],
            "candidate_index": goal["goal_index"] if goal["goal_index"] in bound and goal["goal_index"] < len(candidates) else None,
            "status": "BOUND" if goal["goal_index"] in bound and goal["goal_index"] < len(candidates) else "UNBOUND",
            "confidence": 0.8,
        }
        for goal in goals
    ]


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
        return _goal_response(projection)

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
        {"candidate_index": 0, "bbox": [10, 20, 30, 40], "active": True}
    ]
    assert omni["provider_result"]["items"][0]["capture_bbox"] == [10, 20, 30, 40]
    assert omni["inventory"]["contract_version"] == "hybrid_omni_inventory_v1"
    assert qwen_trace["runtime_request"]["contract_version"] == "simple_native_qwen_goal_binding_request_v1"
    assert qwen_trace["wire_input"] == projections[0]
    assert qwen_trace["parsed"]["bindings"][0]["candidate_id"].startswith("candidate/")
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


def test_one_omni_item_can_bind_five_distinct_goals(tmp_path: Path) -> None:
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
        qwen=lambda _image, projection: [
            {"goal_index": goal["goal_index"], "candidate_index": 0, "status": "BOUND", "confidence": 0.9}
            for goal in projection["goals"]
        ],
        vista=lambda image, _target: vista_calls.append(image) or "[500,500]",
    )

    artifact = run_simple_native_regression_diagnostic(
        cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts"
    )
    qwen = next(
        entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "qwen"
    )
    assert "parse_error" not in qwen
    assert len(vista_calls) == 25


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
        qwen=lambda _image, projection: _goal_response(projection),
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
        return _goal_response(projection)

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
    qwen_trace = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "qwen")
    assert "sha256 mismatch" in qwen_trace["parse_error"]
    assert artifact.metrics["abstained"] >= 1


def test_capture_mutated_by_omni_is_rejected_before_qwen(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    qwen_calls: list[Path] = []

    def omni(image: Path) -> object:
        image.write_bytes(b"mutated-by-omni")
        return {"items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "replay", "interactivity": True}]}

    slots = SimpleNativeSlots(
        omni=omni,
        qwen=lambda image, _projection: qwen_calls.append(image) or {"bindings": []},
        vista=lambda _image, _target: "[500,500]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")

    assert qwen_calls == []
    assert artifact.metrics["omni"]["schema_valid"] == 0
    assert artifact.metrics["omni"]["schema_invalid"] == 2
    first = artifact.cases[0]["trace"]
    assert any(entry.get("slot") == "omni" and "sha256 mismatch" in entry.get("parse_error", "") for entry in first)
    assert len([entry for entry in first if entry.get("slot") == "vista" and entry.get("status") == "abstained"]) == 5


def test_vista_outcomes_are_goal_bounded_with_extra_and_duplicate_candidates(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    vista_calls: list[str] = []
    labels = ["replay", "replay", "missing-1", "missing-2", "missing-3", "noise"]
    slots = SimpleNativeSlots(
        omni=lambda _image: {
            "items": [
                {"bbox": [index / 10, 0.1, (index + 1) / 10, 0.2], "type": "text", "content": label, "interactivity": True}
                for index, label in enumerate(labels, start=1)
            ]
        },
        qwen=lambda _image, projection: _goal_response(projection, bound_goal_indexes={0, 1, 2, 3, 4}),
        vista=lambda _image, target: vista_calls.append(target) or "[500,500]",
    )

    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")

    assert len(vista_calls) == 25
    assert artifact.metrics["vista"]["attempted"] == 25
    for case in artifact.cases:
        outcomes = [entry for entry in case["trace"] if entry.get("slot") == "vista"]
        assert len(outcomes) == 5
        assert len({entry["goal_id"] for entry in outcomes}) == 5
        assert all(entry["goal_text"].startswith("Select the button labeled '") for entry in outcomes)


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
        qwen=lambda _image, projection: _goal_response(projection),
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
        qwen=lambda _image, projection: _goal_response(projection),
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
        qwen=lambda _image, projection: _goal_response(projection),
        vista=lambda _image, _target: "[0,0]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    trace = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")
    assert "strict candidate interior" in trace["parse_error"]
    assert "capture_point" not in trace


def test_scorer_rejects_duplicate_outcomes_and_unsealed_tampering(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic, score_simple_native_regression
    from app.learn.recognition.uei.canonical import seal_immutable

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]},
        qwen=lambda _image, projection: _goal_response(projection),
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
    with pytest.raises(ValueError, match="structure"):
        score_simple_native_regression(provider_artifact=artifact, gold_path=gold_path)

    tampered = json.loads(artifact.path.read_text(encoding="utf-8"))
    tampered["cases"][0]["trace"] = []
    artifact.path.write_text(json.dumps(tampered), encoding="utf-8")
    try:
        score_simple_native_regression(provider_artifact=artifact, gold_path=gold_path)
    except ValueError as error:
        assert "finalized sealed" in str(error)
    else:
        raise AssertionError("unsealed provider trace reached the scorer")


def test_scorer_rejects_self_sealed_extra_case_or_thirty_outcomes_before_gold(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic, score_simple_native_regression
    from app.learn.recognition.uei.canonical import seal_immutable

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "replay", "interactivity": True}]},
        qwen=lambda _image, projection: _goal_response(projection),
        vista=lambda _image, _target: "[500,500]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "artifacts")
    baseline = json.loads(artifact.path.read_text(encoding="utf-8"))

    extra_case = deepcopy(baseline)
    extra_case["cases"].append({**deepcopy(extra_case["cases"][0]), "case_id": "case-006"})
    extra_case.pop("content_sha256")
    artifact.path.write_text(json.dumps(seal_immutable(extra_case), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="structure"):
        score_simple_native_regression(provider_artifact=artifact, gold_path=tmp_path / "must-not-open.json")

    reordered = deepcopy(baseline)
    reordered["cases"][0], reordered["cases"][1] = reordered["cases"][1], reordered["cases"][0]
    reordered.pop("content_sha256")
    artifact.path.write_text(json.dumps(seal_immutable(reordered), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="structure"):
        score_simple_native_regression(provider_artifact=artifact, gold_path=tmp_path / "must-not-open.json")

    thirty_outcomes = deepcopy(baseline)
    for case in thirty_outcomes["cases"]:
        case["trace"].append(deepcopy(next(entry for entry in case["trace"] if entry.get("slot") == "vista")))
    thirty_outcomes.pop("content_sha256")
    artifact.path.write_text(json.dumps(seal_immutable(thirty_outcomes), ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="structure"):
        score_simple_native_regression(provider_artifact=artifact, gold_path=tmp_path / "must-not-open.json")
