from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

import scripts.bind_learn_recognition_support_to_manifest as binder
from scripts.bind_learn_recognition_support_to_manifest import bind_support_to_manifest


def test_bind_support_to_manifest_writes_new_manifest_when_checksum_matches(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (40, 30), "white").save(screenshot)
    support = tmp_path / "support.json"
    support.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_same_screenshot_support_v1",
                "screenshot_sha256": _sha256_file(screenshot),
                "sources": {"uia": {"controls": []}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "blocked_case",
                        "screenshot_path": str(screenshot),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "manifest.bound.json"

    result = bind_support_to_manifest(
        manifest_path=manifest,
        case_id="blocked_case",
        support_path=support,
        out_path=out,
    )

    assert result["status"] == "bound"
    assert result["case_id"] == "blocked_case"
    assert result["validity"]["status"] == "checksum_match"
    updated = json.loads(out.read_text(encoding="utf-8"))
    assert updated["cases"][0]["supplemental_sources_path"] == str(support)
    original = json.loads(manifest.read_text(encoding="utf-8"))
    assert "supplemental_sources_path" not in original["cases"][0]


def test_bind_support_to_manifest_validate_only_does_not_write_manifest(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (40, 30), "white").save(screenshot)
    support = tmp_path / "support.json"
    support.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_same_screenshot_support_v1",
                "screenshot_sha256": _sha256_file(screenshot),
                "sources": {"uia": {"controls": []}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "blocked_case", "screenshot_path": str(screenshot)}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    out = tmp_path / "manifest.bound.json"

    result = bind_support_to_manifest(
        manifest_path=manifest,
        case_id="blocked_case",
        support_path=support,
        out_path=out,
        validate_only=True,
    )

    assert result["status"] == "validated"
    assert result["bindable"] is True
    assert result["validity"]["status"] == "checksum_match"
    assert result["safety"]["artifact_is_authorization"] is False
    assert not out.exists()
    original = json.loads(manifest.read_text(encoding="utf-8"))
    assert "supplemental_sources_path" not in original["cases"][0]


def test_bind_support_to_manifest_rejects_stale_checksum(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen.png"
    Image.new("RGB", (40, 30), "white").save(screenshot)
    support = tmp_path / "support.json"
    support.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_same_screenshot_support_v1",
                "screenshot_sha256": "0" * 64,
                "sources": {"uia": {"controls": []}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "blocked_case", "screenshot_path": str(screenshot)}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = bind_support_to_manifest(
        manifest_path=manifest,
        case_id="blocked_case",
        support_path=support,
        out_path=tmp_path / "manifest.bound.json",
    )

    assert result["status"] == "rejected"
    assert result["failure_category"] == "stale_supplemental_sources"
    assert not (tmp_path / "manifest.bound.json").exists()


def test_bind_support_to_manifest_resolves_repo_relative_screenshot_paths(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    screenshot = repo_root / "artifacts" / "learning-runs" / "site" / "screen.png"
    screenshot.parent.mkdir(parents=True)
    Image.new("RGB", (40, 30), "white").save(screenshot)
    support = tmp_path / "support.json"
    support.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_same_screenshot_support_v1",
                "screenshot_sha256": _sha256_file(screenshot),
                "sources": {"calibrated_targets": {"targets": []}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    manifest_dir = repo_root / "artifacts" / "benchmarks"
    manifest_dir.mkdir(parents=True)
    manifest = manifest_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "repo_relative_case",
                        "screenshot_path": "artifacts/learning-runs/site/screen.png",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(binder, "PROJECT_ROOT", repo_root)

    result = bind_support_to_manifest(
        manifest_path=manifest,
        case_id="repo_relative_case",
        support_path=support,
        out_path=tmp_path / "bound.json",
    )

    assert result["status"] == "bound"
    assert result["validity"]["screenshot_path"] == str(screenshot.resolve())


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
