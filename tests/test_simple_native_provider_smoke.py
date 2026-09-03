from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image


def _cases(tmp_path: Path) -> list[object]:
    from app.learn.hybrid.simple_native_smoke import ProviderCase
    result = []
    for index in range(1, 6):
        image = tmp_path / "source" / f"case-{index:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 100), color=(index, 2, 3)).save(image)
        result.append(ProviderCase(
            case_id=f"case-{index:03d}",
            image_path=image,
            image_size=(100, 100),
            image_sha256=sha256(image.read_bytes()).hexdigest(),
            goals=tuple(f"goal-{index}-{item}" for item in range(5)),
        ))
    return result


def _slots():
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots
    return SimpleNativeSlots(omni=lambda image: {"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "搜索", "interactivity": True}]}, qwen=lambda image, projection: {"bindings": [{"i": item["i"], "role": "button", "label": "目标", "status": "BOUND", "confidence": .9} for item in projection["candidates"]]}, vista=lambda image, target: "[500, 500]")


def test_offline_runner_processes_exactly_five_regression_screens_and_25_targets(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=_slots(), artifact_dir=tmp_path / "out")
    assert artifact.screen_count == 5 and artifact.target_count == 25


def test_each_native_slot_can_be_replaced_independently(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic
    calls = {"omni": 0, "qwen": 0, "vista": 0}
    slots = SimpleNativeSlots(omni=lambda _: calls.__setitem__("omni", calls["omni"] + 1) or {"items": []}, qwen=lambda _, projection: calls.__setitem__("qwen", calls["qwen"] + 1) or {"bindings": [{"i": value["i"], "role": "button", "label": "x", "status": "BOUND", "confidence": 1} for value in projection["candidates"]]}, vista=lambda _, __: calls.__setitem__("vista", calls["vista"] + 1) or "[0,0]")
    run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert calls == {"omni": 5, "qwen": 5, "vista": 0}


def test_provider_runner_never_receives_gold_or_scorer_private_fields(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen: list[object] = []
    slots = _slots(); slots = type(slots)(omni=slots.omni, qwen=lambda image, projection: seen.append(projection) or {"bindings": [{"i": item["i"], "role": "button", "label": "x", "status": "BOUND", "confidence": 1} for item in projection["candidates"]]}, vista=slots.vista)
    run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert all("gold" not in json.dumps(value).lower() for value in seen)


def test_qwen_runner_preserves_full_runtime_request_but_sends_projection(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen=[]; slots=_slots(); original_qwen=slots.qwen; slots=type(slots)(omni=slots.omni, qwen=lambda _, projection: seen.append(projection) or original_qwen(_, projection), vista=slots.vista)
    artifact=run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    qwen = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "qwen")
    assert set(seen[0]) == {"image_size", "candidates"} and qwen["runtime_request_sha256"]


def test_vista_runs_only_for_uniquely_bound_grounding_eligible_targets(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    calls=[]; slots=_slots(); slots=type(slots)(omni=slots.omni,qwen=slots.qwen,vista=lambda image,target: calls.append(target) or "[500,500]")
    run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert len(calls) == 5


def test_runner_counts_schema_failures_and_abstentions_without_fallback(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    slots=_slots(); slots=type(slots)(omni=lambda _: {"items": [{"bad": True}]},qwen=slots.qwen,vista=slots.vista)
    assert run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out").metrics["omni"]["schema_invalid"] == 2


def test_report_contains_numerators_denominators_latency_and_raw_bytes(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    metrics=run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=_slots(), artifact_dir=tmp_path / "out").metrics
    assert metrics["denominator"] == 25 and "raw_output_bytes" in metrics["qwen"] and "latency_p50_ms" in metrics["omni"]


def test_report_is_regression_only_and_never_promotion_eligible(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact=run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=_slots(), artifact_dir=tmp_path / "out")
    assert artifact.regression_diagnostic_only is True and artifact.promotion_eligible is False


def test_runner_writes_raw_parsed_error_lineage_and_cleanup_receipt(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact=run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=_slots(), artifact_dir=tmp_path / "out")
    raw=json.loads(artifact.path.read_text(encoding="utf-8"))
    assert raw["cleanup_receipt"]["verified"] is False and raw["cases"][0]["trace"][0]["raw"]
