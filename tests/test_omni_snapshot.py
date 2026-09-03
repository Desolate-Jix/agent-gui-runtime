from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
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


def _omni_result(_: Path) -> object:
    return {
        "items": [
            {
                "bbox": [0.1, 0.25, 0.3, 0.5],
                "type": "text",
                "content": "target",
                "interactivity": True,
            }
        ]
    }


def _identity() -> dict[str, object]:
    return {
        "provider_id": "local.runtime/omniparser",
        "profile_id": "local.runtime/omniparser/simple-native-v1",
        "model_revision": "test-revision",
        "preprocessing_revision": "test-preprocessing-v1",
    }


def _snapshot(tmp_path: Path) -> tuple[Path, list[object]]:
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot

    cases = _cases(tmp_path)
    path = create_omni_snapshot(
        cases=cases,
        omni=_omni_result,
        output_dir=tmp_path / "omni-snapshot-v1",
        provider_identity=_identity(),
    )
    return path, cases


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_canonical(path: Path, payload: dict[str, object]) -> None:
    path.write_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _seal_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    records = manifest["cases"]
    assert isinstance(records, list)
    manifest["provider_identity_sha256"] = sha256(
        json.dumps(manifest["provider_identity"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest["aggregate_snapshot_sha256"] = sha256(
        json.dumps({"provider_identity": manifest["provider_identity"], "cases": records}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    unsigned = deepcopy(manifest)
    unsigned.pop("content_sha256", None)
    manifest["content_sha256"] = sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _write_canonical(manifest_path, manifest)
    journal_path = manifest_path.parent / "creation.journal.json"
    journal = _read_json(journal_path)
    journal["manifest_content_sha256"] = manifest["content_sha256"]
    _write_canonical(journal_path, journal)


def test_snapshot_runs_omni_exactly_once_per_five_screens(tmp_path: Path) -> None:
    """A frozen snapshot executes discovery once for each of the five captures."""
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot, load_verified_omni_snapshot

    cases = _cases(tmp_path)
    calls: list[Path] = []

    def omni(image: Path) -> object:
        calls.append(image)
        return _omni_result(image)

    manifest = create_omni_snapshot(
        cases=cases, omni=omni, output_dir=tmp_path / "snapshot", provider_identity=_identity()
    )
    loaded = load_verified_omni_snapshot(manifest, expected_cases=cases, expected_provider_identity=_identity())

    assert len(calls) == 5
    assert loaded["target_count"] == 25
    assert [case["case_id"] for case in loaded["cases"]] == [f"case-{index:03d}" for index in range(1, 6)]


def test_snapshot_seals_native_and_canonical_bytes_and_candidate_order(tmp_path: Path) -> None:
    """A changed native/candidate byte or candidate order cannot pass verification."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    manifest = _read_json(manifest_path)
    first = manifest["cases"][0]
    assert isinstance(first, dict)
    native = manifest_path.parent / str(first["native_output_file"])
    candidates = manifest_path.parent / str(first["candidate_file"])
    assert sha256(native.read_bytes()).hexdigest() == first["native_output_file_sha256"]
    assert sha256(candidates.read_bytes()).hexdigest() == first["candidate_file_sha256"]
    assert first["candidate_order_sha256"] == sha256(
        json.dumps(first["candidate_ids"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    candidate_payload = _read_json(candidates)
    candidate_payload["candidates"][0]["bbox_original"] = [11, 20, 30, 40]
    _write_canonical(candidates, candidate_payload)
    with pytest.raises(ValueError, match="candidate file sha256 mismatch"):
        load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())


def test_all_arms_receive_byte_identical_candidate_files(tmp_path: Path) -> None:
    """Independent loads expose the same sealed candidate bytes without Omni reruns."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    first_arm = load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())
    second_arm = load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())
    assert first_arm == second_arm
    assert first_arm is not second_arm
    first_arm["cases"][0]["candidates"][0]["active"] = False
    third_arm = load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())
    assert third_arm["cases"][0]["candidates"][0]["active"] is True


def test_snapshot_rejects_changed_capture_sha_geometry_order_or_profile(tmp_path: Path) -> None:
    """Changing any sealed capture, geometry, order, or provider identity fails closed."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    original = _read_json(manifest_path)
    first = original["cases"][0]
    assert isinstance(first, dict)
    for field, value in (
        ("capture_sha256", "0" * 64),
        ("candidate_order_sha256", "0" * 64),
        ("provider_identity", {**_identity(), "model_revision": "changed"}),
    ):
        changed = deepcopy(original)
        if field == "provider_identity":
            changed[field] = value
        else:
            changed["cases"][0][field] = value
        _write_canonical(manifest_path, changed)
        with pytest.raises(ValueError, match="mismatch"):
            load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())
    _write_canonical(manifest_path, original)
    candidate_path = manifest_path.parent / str(first["candidate_file"])
    candidate = _read_json(candidate_path)
    candidate["candidates"][0]["bbox_original"] = [12, 20, 30, 40]
    _write_canonical(candidate_path, candidate)
    with pytest.raises(ValueError, match="candidate file sha256 mismatch"):
        load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())


def test_snapshot_contains_no_gold_holdout_or_action_authority(tmp_path: Path) -> None:
    """The reusable artifact is regression-only evidence, never scoring or action authority."""
    manifest_path, _ = _snapshot(tmp_path)
    manifest = _read_json(manifest_path)

    assert manifest["regression_only"] is True
    assert manifest["contains_holdout"] is False
    assert manifest["artifact_is_authorization"] is False
    assert "gold" not in manifest
    assert "holdout" not in manifest
    assert "action_authority" not in manifest


def test_snapshot_loader_never_constructs_an_omni_caller(tmp_path: Path) -> None:
    """Loading only validates persisted evidence and has no caller construction input."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    loaded = load_verified_omni_snapshot(manifest_path, expected_cases=cases, expected_provider_identity=_identity())
    assert loaded["contract_version"] == "omni_snapshot_v1"


def test_loader_requires_trusted_identity_and_exact_sealed_goal_order(tmp_path: Path) -> None:
    """A self-resealed provider profile or goal replacement cannot impersonate a trusted snapshot."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    forged = _read_json(manifest_path)
    forged["provider_identity"] = {**_identity(), "model_revision": "forged-revision"}
    _seal_manifest(manifest_path, forged)
    with pytest.raises(ValueError, match="trusted provider identity mismatch"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )

    manifest_path, cases = _snapshot(tmp_path / "goals")
    forged = _read_json(manifest_path)
    forged["cases"][0]["goals"][0] = "Select the button labeled 'replacement'"
    forged["cases"][0]["goals_sha256"] = sha256(
        json.dumps(forged["cases"][0]["goals"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _seal_manifest(manifest_path, forged)
    with pytest.raises(ValueError, match="goal order mismatch"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )


def test_loader_rejects_resealed_traversal_and_forbidden_semantics(tmp_path: Path) -> None:
    """A forged manifest cannot redirect sidecars or smuggle action semantics after resealing."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    forged = _read_json(manifest_path)
    forged["cases"][0]["candidate_file"] = "../case-001.candidates.json"
    _seal_manifest(manifest_path, forged)
    with pytest.raises(ValueError, match="candidate filename mismatch"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )

    manifest_path, cases = _snapshot(tmp_path / "forbidden")
    forged = _read_json(manifest_path)
    forged["cases"][0]["screenshot_path"] = "C:/gold-regression.png"
    _seal_manifest(manifest_path, forged)
    with pytest.raises(ValueError, match="forbidden semantic"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )


def test_create_refuses_existing_or_interrupted_snapshot_before_any_retry(tmp_path: Path) -> None:
    """A retry never overwrites an existing output directory or repeats a partial Omni run."""
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot

    cases = _cases(tmp_path)
    preexisting = tmp_path / "preexisting"
    preexisting.mkdir()
    calls: list[Path] = []
    with pytest.raises(ValueError, match="output directory already exists"):
        create_omni_snapshot(
            cases=cases,
            omni=lambda image: calls.append(image) or _omni_result(image),
            output_dir=preexisting,
            provider_identity=_identity(),
        )
    assert calls == []

    partial = tmp_path / "partial"

    def interrupted(image: Path) -> object:
        assert (partial / "creation.journal.json").is_file()
        calls.append(image)
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        return _omni_result(image)

    with pytest.raises(RuntimeError, match="interrupted"):
        create_omni_snapshot(cases=cases, omni=interrupted, output_dir=partial, provider_identity=_identity())
    first_attempts = len(calls)
    with pytest.raises(ValueError, match="output directory already exists"):
        create_omni_snapshot(cases=cases, omni=interrupted, output_dir=partial, provider_identity=_identity())
    assert len(calls) == first_attempts


def test_loader_rejects_symlinked_sidecar_after_resealing(tmp_path: Path) -> None:
    """A sidecar symlink is rejected even if a forged manifest updates every digest."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    manifest = _read_json(manifest_path)
    first = manifest["cases"][0]
    assert isinstance(first, dict)
    candidate = manifest_path.parent / str(first["candidate_file"])
    outside = tmp_path / "outside.candidates.json"
    candidate.replace(outside)
    try:
        os.symlink(outside, candidate)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    first["candidate_file_sha256"] = sha256(candidate.read_bytes()).hexdigest()
    _seal_manifest(manifest_path, manifest)
    with pytest.raises(ValueError, match="reparse"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )


def test_snapshot_preserves_provider_reported_inactive_candidates(tmp_path: Path) -> None:
    """A noninteractive Omni item remains a valid, explicitly inactive frozen candidate."""
    from app.learn.hybrid.omni_snapshot import create_omni_snapshot, load_verified_omni_snapshot

    cases = _cases(tmp_path)
    manifest = create_omni_snapshot(
        cases=cases,
        omni=lambda _image: {"items": [{
            "bbox": [0.1, 0.25, 0.3, 0.5], "type": "text", "content": "Submit Send Confirm Payment Action", "interactivity": False,
        }]},
        output_dir=tmp_path / "inactive",
        provider_identity=_identity(),
    )
    loaded = load_verified_omni_snapshot(
        manifest, expected_cases=cases, expected_provider_identity=_identity()
    )
    candidate = loaded["cases"][0]["candidates"][0]
    assert candidate["active"] is False
    assert candidate["inactive_reason"] == "provider_reported_inactive"


def test_loader_rejects_resealed_malformed_native_and_forbidden_key(tmp_path: Path) -> None:
    """Recomputed file and manifest digests do not bypass native parsing or authority-key rejection."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    manifest = _read_json(manifest_path)
    record = manifest["cases"][0]
    assert isinstance(record, dict)
    native_path = manifest_path.parent / str(record["native_output_file"])
    native = _read_json(native_path)
    native["raw_utf8"] = "{}"
    native["raw_output_sha256"] = sha256(b"{}").hexdigest()
    _write_canonical(native_path, native)
    record["native_output_sha256"] = native["raw_output_sha256"]
    record["native_output_file_sha256"] = sha256(native_path.read_bytes()).hexdigest()
    candidate_path = manifest_path.parent / str(record["candidate_file"])
    candidate = _read_json(candidate_path)
    candidate["native_output_file_sha256"] = record["native_output_file_sha256"]
    candidate["native_output_sha256"] = record["native_output_sha256"]
    _write_canonical(candidate_path, candidate)
    record["candidate_file_sha256"] = sha256(candidate_path.read_bytes()).hexdigest()
    _seal_manifest(manifest_path, manifest)
    with pytest.raises(ValueError, match="native output parse mismatch"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )

    manifest_path, cases = _snapshot(tmp_path / "key")
    manifest = _read_json(manifest_path)
    manifest["submit_authorized"] = False
    _seal_manifest(manifest_path, manifest)
    with pytest.raises(ValueError, match="forbidden semantic"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )


def test_snapshot_allows_ordinary_action_words_and_rejects_hardlink_alias(tmp_path: Path) -> None:
    """Visible text is inert evidence, while an aliased sidecar is not an immutable file."""
    from app.learn.hybrid.omni_snapshot import load_verified_omni_snapshot

    manifest_path, cases = _snapshot(tmp_path)
    candidate_path = manifest_path.parent / "case-001.candidates.json"
    outside = tmp_path / "candidate-alias.json"
    candidate_path.replace(outside)
    try:
        os.link(outside, candidate_path)
    except OSError as exc:
        pytest.skip(f"hardlink unavailable: {exc}")
    with pytest.raises(ValueError, match="hardlink aliases"):
        load_verified_omni_snapshot(
            manifest_path, expected_cases=cases, expected_provider_identity=_identity()
        )
