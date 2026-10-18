from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts.build_native_installer import InstallerPreparationError, prepare_installer
import scripts.build_native_installer as native
from scripts.build_native_windows import _write_output_hashes


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_native_windows_result(tmp_path: Path) -> tuple[Path, Path]:
    output_root = tmp_path / "native-build"
    package_root = output_root / "dist" / "AgentReview"
    (package_root / "_internal").mkdir(parents=True)
    (package_root / "AgentReview.exe").write_bytes(b"gui")
    (package_root / "AgentReviewBridge.exe").write_bytes(b"bridge")
    (package_root / "_internal" / "runtime.bin").write_bytes(b"runtime")
    separator = chr(92)
    prefix = separator.join(("dist", "AgentReview")) + separator
    artifacts = _write_output_hashes(package_root.parent, output_root)
    manifest = output_root / "build-result.json"
    manifest.write_text(
        json.dumps(
            {
                "artifacts": artifacts,
                "duration_seconds": 1.25,
                "ended_at_epoch": 2.0,
                "expected_artifacts": [
                    prefix + "AgentReview.exe",
                    prefix + "AgentReviewBridge.exe",
                ],
                "missing_artifacts": [],
                "returncode": 0,
                "started_at_epoch": 0.75,
                "succeeded": True,
            }
        ),
        encoding="utf-8",
    )
    return package_root, manifest


def test_prepare_accepts_native_windows_build_result_without_rewriting_it(tmp_path: Path) -> None:
    package_root, manifest = _build_native_windows_result(tmp_path)
    original_bytes = manifest.read_bytes()

    result = prepare_installer(package_root, manifest, tmp_path / "prepared", "0.3.0")

    assert manifest.read_bytes() == original_bytes
    assert result["manifest_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert result["package_root"] == str(package_root.resolve())
    assert result["artifacts"] == [
        {"path": "_internal" + chr(92) + "runtime.bin", "sha256": _sha256(package_root / "_internal" / "runtime.bin"), "size": 7},
        {"path": "AgentReview.exe", "sha256": _sha256(package_root / "AgentReview.exe"), "size": 3},
        {"path": "AgentReviewBridge.exe", "sha256": _sha256(package_root / "AgentReviewBridge.exe"), "size": 6},
    ]


@pytest.mark.parametrize("mutate", ["mixed", "nonzero", "missing", "wrong-prefix", "unknown"])
def test_prepare_rejects_invalid_native_windows_result_before_output(tmp_path: Path, mutate: str) -> None:
    package_root, manifest = _build_native_windows_result(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if mutate == "mixed":
        document["complete"] = True
    elif mutate == "nonzero":
        document["returncode"] = 1
    elif mutate == "missing":
        document["missing_artifacts"] = [chr(92).join(("dist", "AgentReview", "AgentReview.exe"))]
    elif mutate == "wrong-prefix":
        document["artifacts"][0]["path"] = chr(92).join(("dist", "Other", "AgentReview.exe"))
    else:
        document["unknown"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package_root, manifest, tmp_path / "prepared", "0.3.0")
    assert not (tmp_path / "prepared").exists()


def test_prepare_rejects_native_build_result_with_unbound_package_root(tmp_path: Path) -> None:
    package_root, manifest = _build_native_windows_result(tmp_path)

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package_root.parent, manifest, tmp_path / "prepared", "0.3.0")


@pytest.mark.parametrize("mutation", [
    "failed", "boolean-returncode", "wrong-expected", "missing-field", "extra-item-field",
    "traversal", "duplicate", "changed", "missing-file", "extra-file", "reparse-file",
])
def test_native_build_manifest_preserves_payload_and_success_guards(tmp_path, monkeypatch, mutation):
    package, manifest = _build_native_windows_result(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    target = package / "AgentReview.exe"
    if mutation == "failed":
        document["succeeded"] = False
    elif mutation == "boolean-returncode":
        document["returncode"] = False
    elif mutation == "wrong-expected":
        document["expected_artifacts"] = []
    elif mutation == "missing-field":
        document.pop("duration_seconds")
    elif mutation == "extra-item-field":
        document["artifacts"][0]["size"] = 3
    elif mutation == "traversal":
        document["artifacts"][0]["path"] = "dist\\AgentReview\\..\\outside.exe"
    elif mutation == "duplicate":
        duplicate = dict(document["artifacts"][0])
        duplicate["path"] = "dist\\AgentReview\\" + duplicate["path"].split("AgentReview\\", 1)[1].upper()
        document["artifacts"].append(duplicate)
    elif mutation == "changed":
        target.write_bytes(b"replacement")
    elif mutation == "missing-file":
        target.unlink()
    elif mutation == "extra-file":
        (package / "_internal/extra.bin").write_bytes(b"unlisted")
    elif mutation == "reparse-file":
        original = native._is_reparse
        monkeypatch.setattr(native, "_is_reparse", lambda path: path == target or original(path))
    manifest.write_text(json.dumps(document), encoding="utf-8")
    manifest_before = manifest.read_bytes()
    output = tmp_path / "prepared"
    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, output, "0.3.0")
    assert not output.exists()
    assert manifest.read_bytes() == manifest_before


@pytest.mark.parametrize("drift", ["manifest", "payload"])
def test_native_build_refuses_original_input_drift_before_compiler(tmp_path, monkeypatch, drift):
    package, manifest = _build_native_windows_result(tmp_path)
    prepared = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    if drift == "manifest":
        manifest.write_bytes(manifest.read_bytes() + b" ")
    else:
        (package / "AgentReview.exe").write_bytes(b"changed")
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: pytest.fail("compiler started"))
    with pytest.raises(InstallerPreparationError):
        native.build_installer(prepared, Path(sys.executable))


@pytest.mark.parametrize("drift", [None, "manifest", "payload"])
def test_native_build_rechecks_original_input_after_compiler(tmp_path, monkeypatch, drift):
    package, manifest = _build_native_windows_result(tmp_path)
    original = manifest.read_bytes()
    prepared = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    output = Path(prepared["output_root"])

    def compile_fixture(*args, **kwargs):
        (output / f"AgentReview-{prepared['release_id']}.exe").write_bytes(b"synthetic-installer")
        if drift == "manifest":
            manifest.write_bytes(original + b" ")
        elif drift == "payload":
            (package / "AgentReview.exe").write_bytes(b"changed")
        return SimpleNamespace(returncode=0, stdout=b"fixture compiler", stderr=b"")

    monkeypatch.setattr(native.subprocess, "run", compile_fixture)
    code = native.build_installer(prepared, Path(sys.executable))
    result = json.loads((output / "compiler-result.json").read_text(encoding="utf-8"))
    assert code == (0 if drift is None else 1)
    assert result["source_unchanged_after_compile"] is (drift is None)
    assert prepared["manifest_sha256"] == hashlib.sha256(original).hexdigest()
    assert len(result["artifacts"]) == 1
