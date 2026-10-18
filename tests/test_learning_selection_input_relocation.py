from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts import run_learning_selection_acceptance as runner


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOG_SOURCE = REPOSITORY_ROOT / "configs" / "benchmarks" / "learning_selection_acceptance_v1.json"


def _copy_frozen_catalog(root: Path) -> dict[str, object]:
    destination = root / "configs" / "benchmarks" / CATALOG_SOURCE.name
    destination.parent.mkdir(parents=True)
    destination.write_bytes(CATALOG_SOURCE.read_bytes())
    return json.loads(destination.read_text(encoding="utf-8"))


def _fixed_row(catalog: dict[str, object]) -> dict[str, object]:
    rows = catalog["inference_rows"]
    assert isinstance(rows, list)
    row = next(item for item in rows if item["suite"] == "fixed25" and item["case_id"] == "case-001")
    assert isinstance(row, dict)
    return row


def test_fixed25_legacy_path_requires_maintained_root_fixture_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _copy_frozen_catalog(tmp_path)
    row = _fixed_row(catalog)
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(FileNotFoundError, match="maintained fixed25 input is unavailable"):
        runner._static(row, "legacy-input-no-fallback")


_FIXTURE_ROOT = Path("tests") / "fixtures" / "portfolio_hybrid_v1_1" / "corpus" / "regression"
_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL1mQAAAABJRU5ErkJggg=="
)


def _maintained_fixture(root: Path, case_name: str, *, raw: bytes | None = None) -> Path:
    destination = root / _FIXTURE_ROOT / case_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        source = REPOSITORY_ROOT / _FIXTURE_ROOT / case_name
        raw = source.read_bytes()
    destination.write_bytes(raw)
    return destination


def test_fixed25_legacy_path_seals_bundle_from_maintained_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _copy_frozen_catalog(tmp_path)
    row = _fixed_row(catalog)
    maintained = _maintained_fixture(tmp_path, "case-001.png")
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    image, bundle = runner._static(row, "legacy-input-primary")

    assert image.read_bytes() == maintained.read_bytes()
    assert image.name == row["image_sha256"] + ".png"
    assert bundle["capture_identity"]["artifact_sha256"] == row["image_sha256"]
    assert bundle["capture_identity"]["capture_id"].startswith("capture/static/")


def test_fixed25_legacy_path_keeps_sha_check_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _copy_frozen_catalog(tmp_path)
    row = _fixed_row(catalog)
    _maintained_fixture(tmp_path, "case-001.png", raw=_MINIMAL_PNG)
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="pinned SHA differs"):
        runner._static(row, "legacy-input-hash-drift")


def test_legacy_namespace_rejects_suffix_escape_and_wrong_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _copy_frozen_catalog(tmp_path)
    row = _fixed_row(catalog)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    escaped = dict(row, image_path=str(Path(str(row["image_path"])).parent / ".." / "case-001.png"))

    with pytest.raises(ValueError, match="exact regression namespace"):
        runner._catalog_image_input(escaped)
    with pytest.raises(ValueError, match="outside fixed25"):
        runner._catalog_image_input(dict(row, suite="public10"))


def test_fixed25_legacy_path_rejects_maintained_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _copy_frozen_catalog(tmp_path)
    row = _fixed_row(catalog)
    fixture = tmp_path / _FIXTURE_ROOT / "case-001.png"
    fixture.parent.parent.mkdir(parents=True)
    target = tmp_path / "junction-target"
    target.mkdir()
    (target / fixture.name).write_bytes((REPOSITORY_ROOT / _FIXTURE_ROOT / fixture.name).read_bytes())
    # 隐藏的 cmd 会使用本地代码页；改用显式 UTF-8 的原生目录链接命令。
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference = 'Stop'; "
         "$utf8 = [Text.UTF8Encoding]::new($false); "
         "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
         "New-Item -ItemType Junction -Path $env:JUNCTION_PATH -Target $env:JUNCTION_TARGET | Out-Null"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "JUNCTION_PATH": str(fixture.parent), "JUNCTION_TARGET": str(target)},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="reparse point"):
        runner._static(row, "legacy-input-reparse")


def test_nonlegacy_input_path_is_not_relocated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "ordinary" / "fixture.png"
    source.parent.mkdir()
    source.write_bytes(_MINIMAL_PNG)
    monkeypatch.setattr(runner, "ROOT", tmp_path)

    assert runner._catalog_image_input({"suite": "fixed25", "case_id": "case-001", "image_path": str(source)}) == source
