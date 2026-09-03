from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest


def _cases(tmp_path: Path) -> list[object]:
    from app.learn.hybrid.simple_native_smoke import ProviderCase

    cases: list[object] = []
    for index in range(1, 6):
        image = tmp_path / "public-regression" / f"case-{index:03d}.png"
        image.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (100, 80), color=(index, 20, 30)).save(image)
        cases.append(ProviderCase(
            case_id=f"case-{index:03d}",
            image_path=image,
            image_size=(100, 80),
            image_sha256=sha256(image.read_bytes()).hexdigest(),
            goals=tuple(f"Select the button labeled 'target-{goal}'" for goal in range(1, 6)),
        ))
    return cases


def _identity() -> dict[str, object]:
    return {
        "provider_id": "local.runtime/omniparser",
        "profile_id": "local.runtime/omniparser/simple-native-v1",
        "model_revision": "test-revision",
        "preprocessing_revision": "test-preprocessing-v1",
    }


def _snapshot(tmp_path: Path, *, items: list[dict[str, object]] | None = None) -> tuple[Path, list[object], list[Path]]:
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot

    calls: list[Path] = []
    result = items or [{
        "bbox": [0.1, 0.25, 0.3, 0.5],
        "type": "text",
        "content": "target",
        "interactivity": True,
    }]
    manifest = create_omni_snapshot(
        cases=_cases(tmp_path),
        omni=lambda image: calls.append(image) or {"items": result},
        output_dir=tmp_path / "omni-snapshot-v1",
        provider_identity=_identity(),
    )
    return manifest, _cases(tmp_path), calls


def _clean(provider: str = "ui_venus_1_5_2b_f16") -> dict[str, object]:
    return {
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


def _arm(*, call, adapt, cleanup=_clean):
    from app.learn.hybrid.goal_binding_ab import GoalBindingArm

    provider = "ui_venus_1_5_2b_f16"
    return GoalBindingArm(
        "challenger", provider, call, adapt,
        (lambda: _clean(provider)) if cleanup is _clean else cleanup,
    )


def _native_adapter(raw: object, goal_index: int, context: dict[str, object]) -> dict[str, object]:
    from app.learn.hybrid.goal_binding_ab import make_native_point_adapter
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    return make_native_point_adapter(
        parse_ui_venus_point,
        {"contract_version": "goal_binding_native_profile_v1", "provider_id": "ui_venus_1_5_2b_f16", "native_shape": "ui_venus_point_v1", "coordinate_space": "normalized_0_1"},
    )(raw, goal_index, context)


def _run(tmp_path: Path, *, arm, manifest: Path | None = None, cases: list[object] | None = None, vista=lambda _image, _target: "[500,500]", expected_omni_provider_identity: dict[str, object] | None = None):
    from app.learn.hybrid.goal_binding_ab import run_goal_binding_arm

    if manifest is None or cases is None:
        manifest, cases, _ = _snapshot(tmp_path)
    return run_goal_binding_arm(
        cases=cases,
        snapshot_path=manifest,
        arm=arm,
        vista=vista,
        artifact_dir=tmp_path / "arm",
        expected_omni_provider_identity=_identity() if expected_omni_provider_identity is None else expected_omni_provider_identity,
    )


def test_arm_runner_never_calls_omni_and_verifies_snapshot_first(tmp_path: Path) -> None:
    manifest, cases, omni_calls = _snapshot(tmp_path)
    calls: list[Path] = []
    arm = _arm(call=lambda image, _request: calls.append(image) or {"point": [0.2, 0.375]}, adapt=_native_adapter)
    _run(tmp_path, arm=arm, manifest=manifest, cases=cases)
    assert len(omni_calls) == 5
    assert len(calls) == 25

    payload = json.loads((manifest.parent / "case-001.candidates.json").read_text(encoding="utf-8"))
    payload["candidates"][0]["active"] = False
    (manifest.parent / "case-001.candidates.json").write_text(json.dumps(payload), encoding="utf-8")
    calls.clear()
    with pytest.raises(ValueError, match="snapshot"):
        _run(tmp_path / "tampered", arm=arm, manifest=manifest, cases=cases)
    assert calls == []


def test_arm_runner_calls_binder_once_for_each_of_25_goals(tmp_path: Path) -> None:
    calls: list[tuple[Path, object]] = []
    arm = _arm(call=lambda image, request: calls.append((image, request)) or {"point": [0.2, 0.375]}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm)
    assert artifact.target_count == 25
    assert len(calls) == 25
    assert all(isinstance(request, dict) and request["goal"]["semantic_label"].startswith("target-") for _, request in calls)


def test_malformed_native_output_is_provider_failure_not_fallback(tmp_path: Path) -> None:
    vista_calls: list[str] = []
    arm = _arm(call=lambda _image, _request: {"not": "a point"}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm, vista=lambda _image, target: vista_calls.append(target) or "[500,500]")
    binders = [entry for case in artifact.cases for entry in case["trace"] if entry["slot"] == "binder"]
    assert len(binders) == 25 and {entry["canonical_binding"]["status"] for entry in binders} == {"PROVIDER_FAILURE"}
    assert vista_calls == []


@pytest.mark.parametrize("items,point", [
    ([{"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "target", "interactivity": True}], [0.9, 0.9]),
    ([
        {"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "target", "interactivity": True},
        {"bbox": [0.15, 0.3, 0.35, 0.55], "type": "text", "content": "target-2", "interactivity": True},
    ], [0.2, 0.375]),
])
def test_zero_or_multiple_candidate_hit_is_safe_abstain_before_vista(tmp_path: Path, items: list[dict[str, object]], point: list[float]) -> None:
    manifest, cases, _ = _snapshot(tmp_path, items=items)
    vista_calls: list[str] = []
    arm = _arm(call=lambda _image, _request: {"point": point}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm, manifest=manifest, cases=cases, vista=lambda _image, target: vista_calls.append(target) or "[500,500]")
    assert vista_calls == []
    assert artifact.metrics["abstained"] == 25


def test_vista_receives_only_legal_bound_candidate_roi(tmp_path: Path) -> None:
    seen: list[tuple[Path, str]] = []
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm, vista=lambda image, target: seen.append((image, target)) or "[500,500]")
    first = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")
    assert len(seen) == 25
    assert first["status"] == "selected" and first["roi_xyxy"] == [10, 20, 30, 40]
    assert Image.open(seen[0][0]).size == (20, 20)


def test_runner_records_native_raw_parsed_error_and_parent_hashes(tmp_path: Path) -> None:
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm)
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    binder = next(entry for entry in payload["cases"][0]["trace"] if entry["slot"] == "binder")
    assert binder["native_raw_sha256"] and binder["native_parsed_sha256"] and binder["native_error_sha256"] is None
    assert binder["canonical_binding"]["omni_snapshot_ref"] == binder["parent_omni_snapshot_ref"]


def test_runner_preserves_role_label_by_deterministic_goal_inheritance(tmp_path: Path) -> None:
    targets: list[str] = []
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm, vista=lambda _image, target: targets.append(target) or "[500,500]")
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["semantic_role"] == "button" and binder["semantic_label"] == "target-1"
    assert targets[0] == "button: target-1"


def test_incumbent_control_uses_existing_index_parser_without_fake_point(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab import adapt_incumbent_candidate_index

    arm = _arm(
        call=lambda _image, _request: [{"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 0.9}],
        adapt=adapt_incumbent_candidate_index,
    )
    arm = type(arm)("incumbent", "qwen3_vl_8b_q4_k_m", arm.call, arm.adapt, lambda: _clean("qwen3_vl_8b_q4_k_m"))
    artifact = _run(tmp_path, arm=arm)
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["canonical_binding"]["binding_basis"] == "direct_candidate_index"
    assert binder["canonical_binding"]["canonical_capture_pixel_point"] is None


def test_runner_is_regression_only_non_authorizing_and_has_zero_actions(tmp_path: Path) -> None:
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm)
    payload = json.loads(artifact.path.read_text(encoding="utf-8"))
    assert payload["regression_diagnostic_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["action_candidates"] == []
    assert payload["artifact_is_authorization"] is False and payload["execute_binding"] is False


def test_cleanup_failure_blocks_arm_finalization_and_next_model(tmp_path: Path) -> None:
    failed = _clean() | {"verified": False, "cleanup_status": "failed"}
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter, cleanup=lambda: failed)
    with pytest.raises(RuntimeError, match="cleanup"):
        _run(tmp_path, arm=arm)
    assert not (tmp_path / "arm" / "provider-diagnostic.json").exists()


def test_runner_runs_cleanup_after_all_binders_and_before_any_vista(tmp_path: Path) -> None:
    events: list[str] = []
    arm = _arm(
        call=lambda _image, _request: events.append("binder") or {"point": [0.2, 0.375]},
        adapt=_native_adapter,
        cleanup=lambda: events.append("cleanup") or _clean(),
    )
    _run(tmp_path, arm=arm, vista=lambda _image, _target: events.append("vista") or "[500,500]")
    assert events == ["binder"] * 25 + ["cleanup"] + ["vista"] * 25


def test_cleanup_failure_prevents_all_vista_dispatch(tmp_path: Path) -> None:
    vista_calls: list[str] = []
    arm = _arm(
        call=lambda _image, _request: {"point": [0.2, 0.375]},
        adapt=_native_adapter,
        cleanup=lambda: _clean() | {"verified": False, "cleanup_status": "failed"},
    )
    with pytest.raises(RuntimeError, match="cleanup"):
        _run(tmp_path, arm=arm, vista=lambda _image, target: vista_calls.append(target) or "[500,500]")
    assert vista_calls == []


def test_fully_resealed_provider_identity_substitution_is_rejected(tmp_path: Path) -> None:
    manifest, cases, _ = _snapshot(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["provider_identity"] = _identity() | {"model_revision": "forged"}
    document["provider_identity_sha256"] = sha256(json.dumps(document["provider_identity"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    document["aggregate_snapshot_sha256"] = sha256(json.dumps({"provider_identity": document["provider_identity"], "cases": document["cases"]}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    unsigned = dict(document); unsigned.pop("content_sha256")
    document["content_sha256"] = sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    manifest.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    journal = json.loads((manifest.parent / "creation.journal.json").read_text(encoding="utf-8"))
    journal["manifest_content_sha256"] = document["content_sha256"]
    (manifest.parent / "creation.journal.json").write_text(json.dumps(journal, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    calls: list[Path] = []
    arm = _arm(call=lambda image, _request: calls.append(image) or {"point": [0.2, 0.375]}, adapt=_native_adapter)
    with pytest.raises(ValueError, match="trusted provider identity"):
        _run(tmp_path, arm=arm, manifest=manifest, cases=cases)
    assert calls == []


def test_provider_failure_does_not_count_as_schema_valid(tmp_path: Path) -> None:
    arm = _arm(call=lambda _image, _request: {"bad": True}, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm)
    assert artifact.metrics["binder"]["schema_valid"] == 0
    assert artifact.metrics["binder"]["schema_invalid"] == 25


def test_runner_hashes_the_exact_persisted_native_raw_and_parsed_values(tmp_path: Path) -> None:
    raw = '{"point":[0.2,0.375]}'
    arm = _arm(call=lambda _image, _request: raw, adapt=_native_adapter)
    artifact = _run(tmp_path, arm=arm)
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["native_raw"] == raw
    assert binder["native_raw_sha256"] == sha256(raw.encode("utf-8")).hexdigest()
    assert binder["native_parsed_sha256"] == sha256(json.dumps(binder["native_parsed"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert binder["canonical_binding_sha256"] == sha256(json.dumps(binder["canonical_binding"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_mutating_adapter_copy_or_forging_a_bound_candidate_cannot_change_authority(tmp_path: Path) -> None:
    vista_calls: list[str] = []

    def malicious(raw: object, goal_index: int, context: dict[str, object]) -> dict[str, object]:
        result = _native_adapter(raw, goal_index, context)
        context["candidates"][0]["bbox_original"] = [0, 0, 1, 1]
        context["candidates"][0]["active"] = False
        return result

    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=malicious)
    artifact = _run(tmp_path, arm=arm, vista=lambda _image, target: vista_calls.append(target) or "[500,500]")
    assert len(vista_calls) == 25
    assert next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "vista")["roi_xyxy"] == [10, 20, 30, 40]

    overlapping = [
        {"bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "target", "interactivity": True},
        {"bbox": [0.15, 0.3, 0.35, 0.55], "type": "text", "content": "target-2", "interactivity": True},
    ]
    manifest, cases, _ = _snapshot(tmp_path / "forged", items=overlapping)

    def forged(raw: object, goal_index: int, context: dict[str, object]) -> dict[str, object]:
        context["candidates"].pop()
        return _native_adapter(raw, goal_index, context)

    forged_arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=forged)
    forged_artifact = _run(tmp_path / "forged", arm=forged_arm, manifest=manifest, cases=cases)
    assert forged_artifact.metrics["binder"]["schema_invalid"] == 25


def test_cleanup_provider_must_match_arm_provider(tmp_path: Path) -> None:
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter, cleanup=lambda: _clean("wrong-provider"))
    with pytest.raises(RuntimeError, match="provider"):
        _run(tmp_path, arm=arm)


def test_incumbent_bound_record_keeps_frozen_scoring_geometry_when_vista_fails(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab import adapt_incumbent_candidate_index

    arm = _arm(
        call=lambda _image, _request: [{"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 0.9}],
        adapt=adapt_incumbent_candidate_index,
    )
    arm = type(arm)("incumbent", "qwen3_vl_8b_q4_k_m", arm.call, arm.adapt, lambda: _clean("qwen3_vl_8b_q4_k_m"))
    artifact = _run(tmp_path, arm=arm, vista=lambda _image, _target: "not-a-point")
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["selected_candidate"]["bbox_original"] == [10, 20, 30, 40]
    assert binder["selected_candidate"]["center_capture_pixel"] == [20.0, 30.0]


def test_incumbent_legal_unbound_is_schema_valid_safe_abstention(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab import adapt_incumbent_candidate_index

    arm = _arm(
        call=lambda _image, _request: [{"goal_index": 0, "candidate_index": None, "status": "UNBOUND", "confidence": 0.4}],
        adapt=adapt_incumbent_candidate_index,
    )
    arm = type(arm)("incumbent", "qwen3_vl_8b_q4_k_m", arm.call, arm.adapt, lambda: _clean("qwen3_vl_8b_q4_k_m"))
    artifact = _run(tmp_path, arm=arm)
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["canonical_binding"]["status"] == "UNBOUND"
    assert binder["canonical_binding"]["binding_basis"] == "direct_candidate_index"
    assert artifact.metrics["binder"]["schema_valid"] == 25
    assert artifact.metrics["binder"]["schema_invalid"] == 0


def test_malformed_incumbent_unbound_is_schema_invalid(tmp_path: Path) -> None:
    from app.learn.hybrid.goal_binding_ab import adapt_incumbent_candidate_index

    arm = _arm(
        call=lambda _image, _request: [{"goal_index": 0, "candidate_index": 0, "status": "UNBOUND", "confidence": 0.4}],
        adapt=adapt_incumbent_candidate_index,
    )
    arm = type(arm)("incumbent", "qwen3_vl_8b_q4_k_m", arm.call, arm.adapt, lambda: _clean("qwen3_vl_8b_q4_k_m"))
    artifact = _run(tmp_path, arm=arm)
    assert artifact.metrics["binder"]["schema_invalid"] == 25


def test_binder_capture_drift_propagates_after_cleanup_without_more_calls(tmp_path: Path) -> None:
    manifest, cases, _ = _snapshot(tmp_path)
    calls: list[int] = []
    cleanup: list[str] = []
    vista_calls: list[str] = []

    def drift(_image: Path, _request: object) -> object:
        calls.append(1)
        cases[0].image_path.write_bytes(b"capture-drift")
        return {"point": [0.2, 0.375]}

    arm = _arm(call=drift, adapt=_native_adapter, cleanup=lambda: cleanup.append("cleanup") or _clean())
    with pytest.raises(ValueError, match="capture"):
        _run(tmp_path, arm=arm, manifest=manifest, cases=cases, vista=lambda _image, target: vista_calls.append(target) or "[500,500]")
    assert calls == [1] and cleanup == ["cleanup"] and vista_calls == []
    assert not (tmp_path / "arm" / "provider-diagnostic.json").exists()


def test_vista_capture_drift_and_roi_tampering_fail_the_arm(tmp_path: Path) -> None:
    manifest, cases, _ = _snapshot(tmp_path)
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)

    def drift(_image: Path, _target: str) -> str:
        cases[0].image_path.write_bytes(b"capture-drift")
        return "[500,500]"

    with pytest.raises(ValueError, match="capture"):
        _run(tmp_path, arm=arm, manifest=manifest, cases=cases, vista=drift)
    assert not (tmp_path / "arm" / "provider-diagnostic.json").exists()

    manifest, cases, _ = _snapshot(tmp_path / "roi")
    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=_native_adapter)
    with pytest.raises(ValueError, match="ROI"):
        _run(tmp_path / "roi", arm=arm, manifest=manifest, cases=cases, vista=lambda image, _target: image.unlink() or "[500,500]")


def test_forged_native_unbound_against_removed_candidate_is_schema_invalid(tmp_path: Path) -> None:
    def forged(raw: object, goal_index: int, context: dict[str, object]) -> dict[str, object]:
        context["candidates"].clear()
        return _native_adapter(raw, goal_index, context)

    arm = _arm(call=lambda _image, _request: {"point": [0.2, 0.375]}, adapt=forged)
    artifact = _run(tmp_path, arm=arm)
    assert artifact.metrics["binder"]["schema_invalid"] == 25
    assert artifact.metrics["abstained"] == 25
