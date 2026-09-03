from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from PIL import Image
import pytest


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
            goals=(
                "Select the button labeled '\u76ee\u6807'",
                *(f"Select the button labeled 'other-{index}-{item}'" for item in range(1, 5)),
            ),
        ))
    return result


def _verified_cleanup(provider: str, **changes: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "contract_version": "simple_native_provider_cleanup_v1",
        "provider": provider,
        "verified": True,
        "cleanup_status": "verified",
        "owned_processes": [],
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
    }
    receipt.update(changes)
    return receipt


def _goal_response(projection: dict[str, object], *, bound_goal_indexes: set[int] | None = None) -> dict[str, object]:
    goals = projection["goals"]
    candidates = projection["candidates"]
    assert isinstance(goals, list) and isinstance(candidates, list)
    bound = bound_goal_indexes if bound_goal_indexes is not None else {0}
    return {"bindings": [
        {
            "goal_index": goal["goal_index"],
            "candidate_index": goal["goal_index"] if goal["goal_index"] in bound and goal["goal_index"] < len(candidates) else None,
            "status": "BOUND" if goal["goal_index"] in bound and goal["goal_index"] < len(candidates) else "UNBOUND",
            "confidence": 0.9,
        }
        for goal in goals
    ]}


def _slots():
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots
    return SimpleNativeSlots(omni=lambda image: {"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "搜索", "interactivity": True}]}, qwen=lambda image, projection: _goal_response(projection), vista=lambda image, target: "[500, 500]")


def test_offline_runner_processes_exactly_five_regression_screens_and_25_targets(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=_slots(), artifact_dir=tmp_path / "out")
    assert artifact.screen_count == 5 and artifact.target_count == 25


def test_each_native_slot_can_be_replaced_independently(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic
    calls = {"omni": 0, "qwen": 0, "vista": 0}
    slots = SimpleNativeSlots(omni=lambda _: calls.__setitem__("omni", calls["omni"] + 1) or {"items": []}, qwen=lambda _, projection: calls.__setitem__("qwen", calls["qwen"] + 1) or _goal_response(projection), vista=lambda _, __: calls.__setitem__("vista", calls["vista"] + 1) or "[0,0]")
    run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert calls == {"omni": 5, "qwen": 5, "vista": 0}


def test_provider_runner_never_receives_gold_or_scorer_private_fields(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen: list[object] = []
    slots = _slots(); slots = type(slots)(omni=slots.omni, qwen=lambda image, projection: seen.append(projection) or _goal_response(projection), vista=slots.vista)
    run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert all("gold" not in json.dumps(value).lower() for value in seen)


def test_qwen_runner_preserves_full_runtime_request_but_sends_projection(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic
    seen=[]; slots=_slots(); original_qwen=slots.qwen; slots=type(slots)(omni=slots.omni, qwen=lambda _, projection: seen.append(projection) or original_qwen(_, projection), vista=slots.vista)
    artifact=run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    qwen = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "qwen")
    assert set(seen[0]) == {"image_size", "goals", "candidates"} and qwen["runtime_request_sha256"]


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


def test_provider_batches_release_before_the_next_provider_acquires(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    events: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: events.append("omni") or {"items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "x", "interactivity": True}]},
        qwen=lambda _image, projection: events.append("qwen") or _goal_response(projection),
        vista=lambda _image, _target: events.append("vista") or "[500,500]",
        release_provider=lambda provider: events.append(f"release:{provider}") or _verified_cleanup(provider),
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")

    assert events == ["omni"] * 5 + ["release:omni"] + ["qwen"] * 5 + ["release:qwen"] + ["vista"] * 5 + ["release:vista"]
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert [item["provider"] for item in payload["provider_phase_cleanup"]] == ["omni", "qwen", "vista"]


def test_unverified_provider_release_blocks_the_next_provider_phase(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    events: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: events.append("omni") or {"items": []},
        qwen=lambda _image, _projection: events.append("qwen") or {"bindings": []},
        vista=lambda _image, _target: events.append("vista") or "[500,500]",
        release_provider=lambda provider: events.append(f"release:{provider}") or _verified_cleanup(
            provider, verified=False, cleanup_status="failed"
        ),
    )

    with pytest.raises(RuntimeError, match="omni cleanup observation is not clean"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert events == ["omni"] * 5 + ["release:omni"]


def test_cleanup_claim_with_live_pid_and_failed_status_blocks_qwen(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    qwen_calls: list[Path] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": []},
        qwen=lambda image, _projection: qwen_calls.append(image) or {"bindings": []},
        vista=lambda _image, _target: "[500,500]",
        release_provider=lambda provider: _verified_cleanup(
            provider,
            cleanup_status="failed",
            owned_processes=[4242],
        ),
    )

    with pytest.raises(RuntimeError, match="cleanup observation"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert qwen_calls == []


def test_cleanup_observation_rejects_unknown_fields(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": []},
        qwen=lambda _image, _projection: {"bindings": []},
        vista=lambda _image, _target: "[500,500]",
        release_provider=lambda provider: {**_verified_cleanup(provider), "optimistic_note": "clean"},
    )

    with pytest.raises(ValueError, match="cleanup observation is invalid"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")


def test_provider_goal_parser_rejects_non_frozen_grammar_before_dispatch(tmp_path: Path) -> None:
    from dataclasses import replace
    from app.learn.hybrid.simple_native_smoke import run_simple_native_regression_diagnostic

    cases = _cases(tmp_path)
    cases[0] = replace(cases[0], goals=("click anything", *cases[0].goals[1:]))

    with pytest.raises(ValueError, match="closed grammar"):
        run_simple_native_regression_diagnostic(cases=cases, slots=_slots(), artifact_dir=tmp_path / "out")


def test_omni_runtime_error_releases_once_and_never_advances_to_qwen(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    events: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: events.append("omni") or (_ for _ in ()).throw(RuntimeError("omni crashed")),
        qwen=lambda _image, _projection: events.append("qwen") or {"bindings": []},
        vista=lambda _image, _target: events.append("vista") or "[500,500]",
        release_provider=lambda provider: events.append(f"release:{provider}") or _verified_cleanup(provider),
    )

    with pytest.raises(RuntimeError, match="omni crashed"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert events == ["omni", "release:omni"]


def test_qwen_runtime_error_releases_once_and_never_advances_to_vista(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    events: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: events.append("omni") or {"items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "\u76ee\u6807", "interactivity": True}]},
        qwen=lambda _image, _projection: events.append("qwen") or (_ for _ in ()).throw(RuntimeError("qwen crashed")),
        vista=lambda _image, _target: events.append("vista") or "[500,500]",
        release_provider=lambda provider: events.append(f"release:{provider}") or _verified_cleanup(provider),
    )

    with pytest.raises(RuntimeError, match="qwen crashed"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert events == ["omni"] * 5 + ["release:omni", "qwen", "release:qwen"]


def test_cleanup_failure_is_chained_from_unexpected_provider_error(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    releases: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: (_ for _ in ()).throw(RuntimeError("omni crashed")),
        qwen=lambda _image, _projection: {"bindings": []},
        vista=lambda _image, _target: "[500,500]",
        release_provider=lambda provider: releases.append(provider) or _verified_cleanup(
            provider, cleanup_status="failed", owned_processes=[4242]
        ),
    )

    with pytest.raises(RuntimeError, match="cleanup observation is not clean") as raised:
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert releases == ["omni"]
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "omni crashed"


def test_vista_base_exception_releases_once(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    class ProviderAbort(BaseException):
        pass

    events: list[str] = []

    def abort_vista(_image: Path, _target: str) -> str:
        events.append("vista")
        raise ProviderAbort("vista aborted")

    slots = SimpleNativeSlots(
        omni=lambda _image: events.append("omni") or {"items": [{"bbox": [0.1, 0.1, 0.2, 0.2], "type": "text", "content": "\u76ee\u6807", "interactivity": True}]},
        qwen=lambda _image, projection: events.append("qwen") or _goal_response(projection),
        vista=abort_vista,
        release_provider=lambda provider: events.append(f"release:{provider}") or _verified_cleanup(provider),
    )

    with pytest.raises(ProviderAbort, match="vista aborted"):
        run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")
    assert events == ["omni"] * 5 + ["release:omni"] + ["qwen"] * 5 + ["release:qwen", "vista", "release:vista"]


def test_inactive_goal_bound_candidate_abstains_before_vista(tmp_path: Path) -> None:
    from app.learn.hybrid.simple_native_smoke import SimpleNativeSlots, run_simple_native_regression_diagnostic

    vista_calls: list[str] = []
    slots = SimpleNativeSlots(
        omni=lambda _image: {"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "target", "interactivity": False}]},
        qwen=lambda _image, projection: {"bindings": [
            {"goal_index": goal["goal_index"], "candidate_index": 0 if goal["goal_index"] == 0 else None, "status": "BOUND" if goal["goal_index"] == 0 else "UNBOUND", "confidence": 1}
            for goal in projection["goals"]
        ]},
        vista=lambda _image, target: vista_calls.append(target) or "[500,500]",
    )
    artifact = run_simple_native_regression_diagnostic(cases=_cases(tmp_path), slots=slots, artifact_dir=tmp_path / "out")

    assert vista_calls == []
    outcomes = [entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista"]
    assert outcomes[0]["reason"] == "goal_bound_candidate_inactive"
