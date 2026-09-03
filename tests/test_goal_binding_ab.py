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


def _clean() -> dict[str, object]:
    return {
        "contract_version": "simple_native_provider_cleanup_v1",
        "provider": "binder",
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

    return GoalBindingArm("challenger", "ui_venus_1_5_2b_f16", call, adapt, cleanup)


def _native_adapter(raw: object, goal_index: int, context: dict[str, object]) -> dict[str, object]:
    from app.learn.hybrid.goal_binding_ab import make_native_point_adapter
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    return make_native_point_adapter(
        parse_ui_venus_point,
        {"contract_version": "goal_binding_native_profile_v1", "provider_id": "ui_venus_1_5_2b_f16", "native_shape": "ui_venus_point_v1", "coordinate_space": "normalized_0_1"},
    )(raw, goal_index, context)


def _run(tmp_path: Path, *, arm, manifest: Path | None = None, cases: list[object] | None = None, vista=lambda _image, _target: "[500,500]"):
    from app.learn.hybrid.goal_binding_ab import run_goal_binding_arm

    if manifest is None or cases is None:
        manifest, cases, _ = _snapshot(tmp_path)
    return run_goal_binding_arm(cases=cases, snapshot_path=manifest, arm=arm, vista=vista, artifact_dir=tmp_path / "arm")


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
    assert len(binders) == 25 and {entry["binding"]["status"] for entry in binders} == {"PROVIDER_FAILURE"}
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
    assert binder["binding"]["omni_snapshot_ref"] == binder["parent_omni_snapshot_ref"]


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
    arm = type(arm)("incumbent", "qwen3_vl_8b_q4_k_m", arm.call, arm.adapt, arm.cleanup)
    artifact = _run(tmp_path, arm=arm)
    binder = next(entry for entry in artifact.cases[0]["trace"] if entry["slot"] == "binder")
    assert binder["binding"]["binding_basis"] == "direct_candidate_index"
    assert binder["binding"]["canonical_capture_pixel_point"] is None


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
