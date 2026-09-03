from __future__ import annotations

import json
from pathlib import Path


def _cases() -> list[object]:
    from app.learn.hybrid.simple_native_smoke import ProviderCase
    return [ProviderCase(case_id=f"case-{index:03d}", image_path=Path(f"case-{index:03d}.png"), image_size=(100, 100), targets=tuple(f"target-{index}-{item}" for item in range(5)), runtime_request={"screenshot": {"image_size": {"width": 100, "height": 100}}, "candidates": [{"candidate_id": f"candidate/{index}-{item}", "bbox_original": [10, 10, 20, 20], "active": True} for item in range(5)]}) for index in range(1, 6)]


def _slots():
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots
    return SimpleNativeSlots(omni=lambda image: {"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "搜索", "interactivity": True}]}, qwen=lambda image, projection: {"bindings": [{"i": item["i"], "role": "button", "label": "目标", "status": "BOUND", "confidence": .9} for item in projection["candidates"]]}, vista=lambda image, target: "[500, 500]")


def test_offline_runner_processes_exactly_five_regression_screens_and_25_targets(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact = run_simple_native_regression_diagnostic(cases=_cases(), slots=_slots(), artifact_dir=tmp_path)
    assert artifact.screen_count == 5 and artifact.target_count == 25


def test_each_native_slot_can_be_replaced_independently(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic
    calls = {"omni": 0, "qwen": 0, "vista": 0}
    slots = SimpleNativeSlots(omni=lambda _: calls.__setitem__("omni", calls["omni"] + 1) or {"items": []}, qwen=lambda _, projection: calls.__setitem__("qwen", calls["qwen"] + 1) or {"bindings": [{"i": value["i"], "role": "button", "label": "x", "status": "BOUND", "confidence": 1} for value in projection["candidates"]]}, vista=lambda _, __: calls.__setitem__("vista", calls["vista"] + 1) or "[0,0]")
    run_simple_native_regression_diagnostic(cases=_cases(), slots=slots, artifact_dir=tmp_path)
    assert calls == {"omni": 5, "qwen": 5, "vista": 25}


def test_provider_runner_never_receives_gold_or_scorer_private_fields(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen: list[object] = []
    slots = _slots(); slots = type(slots)(omni=slots.omni, qwen=lambda image, projection: seen.append(projection) or {"bindings": [{"i": item["i"], "role": "button", "label": "x", "status": "BOUND", "confidence": 1} for item in projection["candidates"]]}, vista=slots.vista)
    run_simple_native_regression_diagnostic(cases=_cases(), slots=slots, artifact_dir=tmp_path)
    assert all("gold" not in json.dumps(value).lower() for value in seen)


def test_qwen_runner_preserves_full_runtime_request_but_sends_projection(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen=[]; slots=_slots(); slots=type(slots)(omni=slots.omni, qwen=lambda _, projection: seen.append(projection) or slots.qwen(_, projection), vista=slots.vista)
    artifact=run_simple_native_regression_diagnostic(cases=_cases(), slots=slots, artifact_dir=tmp_path)
    assert set(seen[0]) == {"image_size", "candidates"} and artifact.cases[0]["runtime_request_sha256"]


def test_vista_runs_only_for_uniquely_bound_grounding_eligible_targets(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    calls=[]; slots=_slots(); slots=type(slots)(omni=slots.omni,qwen=slots.qwen,vista=lambda image,target: calls.append(target) or "[500,500]")
    run_simple_native_regression_diagnostic(cases=_cases(), slots=slots, artifact_dir=tmp_path)
    assert len(calls) == 25


def test_runner_counts_schema_failures_and_abstentions_without_fallback(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    slots=_slots(); slots=type(slots)(omni=lambda _: {"items": [{"bad": True}]},qwen=slots.qwen,vista=slots.vista)
    assert run_simple_native_regression_diagnostic(cases=_cases(), slots=slots, artifact_dir=tmp_path).metrics["omni"]["schema_invalid"] == 2


def test_report_contains_numerators_denominators_latency_and_raw_bytes(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    metrics=run_simple_native_regression_diagnostic(cases=_cases(), slots=_slots(), artifact_dir=tmp_path).metrics
    assert metrics["denominator"] == 25 and "raw_output_bytes" in metrics["qwen"] and "latency_p50_ms" in metrics["omni"]


def test_report_is_regression_only_and_never_promotion_eligible(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact=run_simple_native_regression_diagnostic(cases=_cases(), slots=_slots(), artifact_dir=tmp_path)
    assert artifact.regression_diagnostic_only is True and artifact.promotion_eligible is False


def test_runner_writes_raw_parsed_error_lineage_and_cleanup_receipt(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact=run_simple_native_regression_diagnostic(cases=_cases(), slots=_slots(), artifact_dir=tmp_path)
    raw=json.loads(artifact.path.read_text(encoding="utf-8"))
    assert raw["cleanup_receipt"]["verified"] is True and raw["cases"][0]["trace"][0]["raw"]
