import hashlib
import json
from pathlib import Path
import sys

import pytest

import scripts.build_native_installer as native
from scripts.build_native_installer import InstallerPreparationError, build_installer, prepare_installer


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_package(tmp_path: Path) -> tuple[Path, Path]:
    package = tmp_path / "package"
    (package / "_internal").mkdir(parents=True)
    (package / "AgentReview.exe").write_bytes(b"gui!")
    (package / "AgentReviewBridge.exe").write_bytes(b"bridge")
    (package / "_internal" / "base_library.zip").write_bytes(b"runtime")
    artifacts = []
    for file in sorted(package.rglob("*")):
        if file.is_file():
            artifacts.append({"path": str(file.relative_to(package)).replace("/", "\\"), "sha256": sha256(file), "size": file.stat().st_size})
    manifest = tmp_path / "build-result.json"
    manifest.write_text(json.dumps({"complete": True, "artifacts": artifacts}), encoding="utf-8")
    return package, manifest


def test_prepare_emits_exact_include_and_content_derived_release_metadata(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    result = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    output = Path(result["output_root"])

    assert output.is_dir()
    assert result["release_id"] == f"0.3.0-{result['payload_sha256'][:16]}"
    assert result["payload_bytes"] == 17
    assert result["artifacts"] == [
        {"path": "_internal\\base_library.zip", "sha256": sha256(package / "_internal" / "base_library.zip"), "size": 7},
        {"path": "AgentReview.exe", "sha256": sha256(package / "AgentReview.exe"), "size": 4},
        {"path": "AgentReviewBridge.exe", "sha256": sha256(package / "AgentReviewBridge.exe"), "size": 6},
    ]
    assert 'DestDir: "{app}\\versions\\{#ReleaseId}"' in (output / "installer-files.iss").read_text(encoding="utf-8")
    metadata = json.loads((output / "release-metadata.json").read_text(encoding="utf-8"))
    assert metadata["manifest_sha256"] == sha256(manifest)
    assert metadata["artifacts"] == result["artifacts"]


@pytest.mark.parametrize("mutation", ["changed", "missing", "extra"])
def test_prepare_rejects_payload_that_does_not_exactly_match_manifest(tmp_path: Path, mutation: str) -> None:
    package, manifest = make_package(tmp_path)
    target = package / "_internal" / "base_library.zip"
    if mutation == "changed":
        target.write_bytes(b"changed")
    elif mutation == "missing":
        target.unlink()
    else:
        (package / "unlisted.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")


@pytest.mark.parametrize("bad_path", ["..\\escape.txt", "C:\\outside.txt", "_internal\\..\\AgentReview.exe", "AgentReview.exe"])
def test_prepare_rejects_escaping_and_duplicate_case_insensitive_manifest_paths(tmp_path: Path, bad_path: str) -> None:
    package, manifest = make_package(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if bad_path == "AgentReview.exe":
        document["artifacts"].append({"path": "agentreview.EXE", "sha256": "0" * 64, "size": 1})
    else:
        document["artifacts"][0]["path"] = bad_path
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")


def test_prepare_refuses_existing_or_overlapping_output_without_side_effects(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "sentinel.txt").write_text("preserve", encoding="utf-8")

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, existing, "0.3.0")
    assert (existing / "sentinel.txt").read_text(encoding="utf-8") == "preserve"

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, package / "prepared", "0.3.0")


def test_prepare_rejects_unknown_manifest_top_level_field(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["untrusted_note"] = "not part of the verified build result schema"
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InstallerPreparationError):
        prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")


def test_prepare_preserves_dotted_dependency_directory_in_generated_include(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    dotted = package / "_internal" / "example-1.2.dist-info"
    dotted.mkdir()
    metadata = dotted / "METADATA"
    metadata.write_bytes(b"metadata")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["artifacts"].append({"path": "_internal\\example-1.2.dist-info\\METADATA", "sha256": sha256(metadata), "size": 8})
    manifest.write_text(json.dumps(document), encoding="utf-8")

    result = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    include = Path(result["include_file"]).read_text(encoding="utf-8")
    assert ('Source: "{#SourceRoot}\\_internal\\example-1.2.dist-info\\METADATA"; '
            'DestDir: "{app}\\versions\\{#ReleaseId}\\_internal\\example-1.2.dist-info"; Flags: ignoreversion') in include


@pytest.mark.parametrize("bad_path", [
    "_internal\\bad{name}.txt", "_internal\\bad\"name.txt", "_internal\\bad" + chr(10) + "name.txt",
    "_internal\\name:stream", "_internal\\trailing.", "_internal\\CON.txt",
])
def test_normalise_rejects_windows_or_inno_unsafe_artifact_paths(bad_path: str) -> None:
    with pytest.raises(InstallerPreparationError, match="unsafe"):
        native._normalise_manifest_path(bad_path)


def test_prepare_rejects_boolean_artifact_size(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["artifacts"][0]["size"] = True
    manifest.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(InstallerPreparationError, match="invalid artifact size"):
        prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")


@pytest.mark.parametrize("drift", ["manifest", "source", "include"])
def test_build_refuses_precompile_drift_without_starting_compiler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str) -> None:
    package, manifest = make_package(tmp_path)
    preparation = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    if drift == "manifest":
        manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif drift == "source":
        (package / "AgentReview.exe").write_bytes(b"drift")
    else:
        Path(preparation["include_file"]).write_text("drift", encoding="utf-8")

    def compiler_must_not_start(*args: object, **kwargs: object) -> None:
        raise AssertionError("compiler started despite precompile drift")

    monkeypatch.setattr(native.subprocess, "run", compiler_must_not_start)
    with pytest.raises(InstallerPreparationError):
        build_installer(preparation, Path(sys.executable))


@pytest.mark.parametrize("timeout_seconds", [0, -1, True])
def test_build_rejects_nonpositive_or_boolean_timeout_before_compiler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout_seconds: object) -> None:
    package, manifest = make_package(tmp_path)
    preparation = prepare_installer(package, manifest, tmp_path / "prepared", "0.3.0")
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: pytest.fail("compiler started"))
    with pytest.raises(InstallerPreparationError, match="timeout_seconds"):
        build_installer(preparation, Path(sys.executable), timeout_seconds=timeout_seconds)  # type: ignore[arg-type]


def test_release_identity_is_stable_for_manifest_format_and_metadata_changes(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    first = prepare_installer(package, manifest, tmp_path / "first", "0.3.0")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["started_at"] = 123.5
    document["command"] = ["same-payload", "different-audit-metadata"]
    manifest.write_text(json.dumps(document, ensure_ascii=False, indent=4, sort_keys=True) + "\n", encoding="utf-8")
    second = prepare_installer(package, manifest, tmp_path / "second", "0.3.0")

    assert first["manifest_sha256"] != second["manifest_sha256"]
    assert first["payload_sha256"] == second["payload_sha256"]
    assert first["release_id"] == second["release_id"]


def test_release_identity_changes_when_verified_payload_changes(tmp_path: Path) -> None:
    package, manifest = make_package(tmp_path)
    first = prepare_installer(package, manifest, tmp_path / "first", "0.3.0")
    executable = package / "AgentReview.exe"
    executable.write_bytes(b"new-gui!")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    for artifact in document["artifacts"]:
        if artifact["path"] == "AgentReview.exe":
            artifact["size"] = executable.stat().st_size
            artifact["sha256"] = sha256(executable)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    second = prepare_installer(package, manifest, tmp_path / "second", "0.3.0")

    assert first["payload_sha256"] != second["payload_sha256"]
    assert first["release_id"] != second["release_id"]
