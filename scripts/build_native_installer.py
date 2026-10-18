"""Validate a native onedir payload and compile the per-user Inno Setup package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

PRODUCT_APP_ID = "AgentGuiRuntime.AgentReview.PerUser"
PRODUCT_NAME = "Agent Review"
_REQUIRED_EXECUTABLES = {"agentreview.exe", "agentreviewbridge.exe"}
_ALLOWED_BUILD_RESULT_KEYS = {
    "started_at", "command", "parent_spec_sha256", "derived_spec_sha256", "source_before",
    "old_package", "package", "complete", "deleted_paths", "build_exit_code",
    "dependency_mismatches", "finished_at", "linked_dependency_files", "copied_dependency_files",
    "dependency_review", "artifacts", "source_after",
}
_DRIVE_PATH = re.compile(r"^[A-Za-z]:")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_NATIVE_WINDOWS_BUILD_RESULT_KEYS = {
    "artifacts", "duration_seconds", "ended_at_epoch", "expected_artifacts",
    "missing_artifacts", "returncode", "started_at_epoch", "succeeded",
}
_NATIVE_WINDOWS_EXPECTED_ARTIFACTS = [
    "dist\\AgentReview\\AgentReview.exe",
    "dist\\AgentReview\\AgentReviewBridge.exe",
]
_NATIVE_WINDOWS_PACKAGE_PREFIX = "dist\\AgentReview\\"


class InstallerPreparationError(ValueError):
    """The proposed installer input cannot be proven safe and exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(os.lstat(path).st_file_attributes & 0x400)
    except AttributeError:
        return path.is_symlink()


def _normalise_manifest_path(value: Any) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InstallerPreparationError("artifact path must be a non-empty Windows relative path")
    canonical = value.replace("/", "\\")
    if canonical.startswith("\\") or _DRIVE_PATH.match(canonical):
        raise InstallerPreparationError(f"artifact path is not relative: {value!r}")
    parts = canonical.split("\\")
    for part in parts:
        if (not part or part in {".", ".."} or any(token in part for token in ('{', '}', '"', '\r', '\n'))
                or ':' in part or part[-1] in {".", " "} or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED):
            raise InstallerPreparationError(f"artifact path is unsafe for Windows/Inno Setup: {value!r}")
    return "\\".join(parts), Path(*parts)


def _assert_nonreparse_ancestors(root: Path, candidate: Path | None = None) -> None:
    target = candidate or root
    chain: list[Path] = []
    current = target
    while True:
        if current.exists():
            chain.append(current)
        if current == current.parent:
            break
        current = current.parent
    for item in chain:
        if _is_reparse(item):
            raise InstallerPreparationError(f"reparse point is not allowed: {item}")


def _load_native_windows_build_result(
    document: dict[str, Any],
    *,
    manifest: Path,
    package_root: Path,
) -> dict[str, Any]:
    if (
        document.get("succeeded") is not True
        or type(document.get("returncode")) is not int
        or document["returncode"] != 0
        or document.get("missing_artifacts") != []
        or document.get("expected_artifacts") != _NATIVE_WINDOWS_EXPECTED_ARTIFACTS
        or not isinstance(document.get("artifacts"), list)
    ):
        raise InstallerPreparationError("native Windows build result is not a successful complete build")
    for key in ("started_at_epoch", "ended_at_epoch", "duration_seconds"):
        if type(document.get(key)) not in {int, float}:
            raise InstallerPreparationError("native Windows build result has invalid timing fields")
    expected_package_root = manifest.parent / "dist" / "AgentReview"
    if package_root.resolve() != expected_package_root.resolve():
        raise InstallerPreparationError("package root is not bound to native Windows build result dist/AgentReview")
    if not package_root.is_dir():
        raise InstallerPreparationError("package root must be a directory")
    _assert_nonreparse_ancestors(package_root)
    artifacts: list[dict[str, Any]] = []
    for item in document["artifacts"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise InstallerPreparationError("native Windows build artifact must contain only path and sha256")
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path.startswith(_NATIVE_WINDOWS_PACKAGE_PREFIX):
            raise InstallerPreparationError("native Windows build artifact path must use dist\\AgentReview prefix")
        path_text, relative = _normalise_manifest_path(
            raw_path[len(_NATIVE_WINDOWS_PACKAGE_PREFIX):]
        )
        digest = item.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise InstallerPreparationError(f"invalid artifact sha256: {raw_path}")
        target = package_root / relative
        _assert_nonreparse_ancestors(package_root, target)
        if not target.is_file() or _is_reparse(target):
            raise InstallerPreparationError(f"missing regular artifact: {raw_path}")
        artifacts.append({"path": path_text, "sha256": digest, "size": target.stat().st_size})
    return {"complete": True, "artifacts": artifacts}


def _load_manifest(package_root: Path, manifest: Path) -> tuple[dict[str, Any], str]:
    if not manifest.is_file() or _is_reparse(manifest):
        raise InstallerPreparationError("package manifest must be a regular non-reparse file")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerPreparationError(f"invalid UTF-8 JSON manifest: {error}") from error
    if not isinstance(document, dict):
        raise InstallerPreparationError("manifest must be a JSON object")
    manifest_sha256 = _sha256(manifest)
    keys = set(document)
    if keys <= _ALLOWED_BUILD_RESULT_KEYS:
        if document.get("complete") is not True or not isinstance(document.get("artifacts"), list):
            raise InstallerPreparationError("manifest must be complete with an artifacts list")
        return document, manifest_sha256
    if keys == _NATIVE_WINDOWS_BUILD_RESULT_KEYS:
        return _load_native_windows_build_result(
            document, manifest=manifest, package_root=package_root
        ), manifest_sha256
    raise InstallerPreparationError("manifest does not match a supported strict schema")


def _validate_payload(package_root: Path, document: dict[str, Any]) -> list[dict[str, Any]]:
    if not package_root.is_dir():
        raise InstallerPreparationError("package root must be a directory")
    _assert_nonreparse_ancestors(package_root)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    expected: set[str] = set()
    for item in document["artifacts"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            raise InstallerPreparationError("each artifact must contain only path, sha256, and size")
        path_text, relative = _normalise_manifest_path(item["path"])
        key = path_text.casefold()
        if key in seen:
            raise InstallerPreparationError(f"duplicate artifact path: {path_text}")
        seen.add(key)
        if type(item["size"]) is not int or item["size"] < 0:
            raise InstallerPreparationError(f"invalid artifact size: {path_text}")
        if not isinstance(item["sha256"], str) or not _SHA256.fullmatch(item["sha256"]):
            raise InstallerPreparationError(f"invalid artifact sha256: {path_text}")
        target = package_root / relative
        _assert_nonreparse_ancestors(package_root, target)
        if not target.is_file() or _is_reparse(target):
            raise InstallerPreparationError(f"missing regular artifact: {path_text}")
        if target.stat().st_size != item["size"] or _sha256(target) != item["sha256"]:
            raise InstallerPreparationError(f"artifact bytes differ from manifest: {path_text}")
        expected.add(key)
        entries.append({"path": path_text, "sha256": item["sha256"], "size": item["size"]})
    if not entries:
        raise InstallerPreparationError("manifest must list at least one artifact")
    actual: set[str] = set()
    for item in package_root.rglob("*"):
        _assert_nonreparse_ancestors(package_root, item)
        if item.is_file():
            actual.add("\\".join(item.relative_to(package_root).parts).casefold())
        elif not item.is_dir():
            raise InstallerPreparationError(f"unsupported payload entry: {item}")
    if actual != expected:
        raise InstallerPreparationError("payload has missing or unlisted files")
    root_executables = {entry["path"].casefold() for entry in entries if "\\" not in entry["path"]}
    if root_executables != _REQUIRED_EXECUTABLES or any(
        "\\" in entry["path"] and not entry["path"].casefold().startswith("_internal\\")
        for entry in entries
    ):
        raise InstallerPreparationError("payload must contain exactly both root EXEs and only _internal dependencies")
    return sorted(entries, key=lambda entry: entry["path"].casefold())


def _payload_sha256(artifacts: list[dict[str, Any]]) -> str:
    canonical = json.dumps(artifacts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _release_id(version: str, payload_sha256: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}(?:[-+][0-9A-Za-z.-]+)?", version):
        raise InstallerPreparationError("version must be a conservative semantic version")
    return f"{version}-{payload_sha256[:16]}"


def _assert_new_output(package_root: Path, manifest: Path, output_root: Path) -> None:
    if output_root.exists():
        raise InstallerPreparationError("output directory must not already exist")
    resolved_output = output_root.resolve(strict=False)
    for protected in (package_root.resolve(), manifest.resolve()):
        try:
            resolved_output.relative_to(protected)
        except ValueError:
            try:
                protected.relative_to(resolved_output)
            except ValueError:
                continue
        raise InstallerPreparationError("output directory must not overlap package or manifest")
    parent = output_root.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    _assert_nonreparse_ancestors(parent)


def prepare_installer(package_root: Path, package_manifest: Path, output_root: Path, version: str) -> dict[str, Any]:
    """Validate full payload bytes and create a fresh compiler input directory."""
    package_root, package_manifest, output_root = Path(package_root), Path(package_manifest), Path(output_root)
    _assert_new_output(package_root, package_manifest, output_root)
    document, manifest_sha256 = _load_manifest(package_root, package_manifest)
    artifacts = _validate_payload(package_root, document)
    payload_sha256 = _payload_sha256(artifacts)
    release_id = _release_id(version, payload_sha256)
    output_root.mkdir(parents=True, exist_ok=False)
    include = output_root / "installer-files.iss"
    include_lines = [
        "; Generated from verified manifest. Do not edit.",
        f"#define PayloadBytes {sum(item['size'] for item in artifacts)}",
    ]
    for item in artifacts:
        relative = item["path"]
        directory = "\\".join(relative.split("\\")[:-1])
        suffix = "" if not directory else "\\" + directory
        include_lines.append(f'Source: "{{#SourceRoot}}\\{relative}"; DestDir: "{{app}}\\versions\\{{#ReleaseId}}{suffix}"; Flags: ignoreversion')
    include.write_text("\n".join(include_lines) + "\n", encoding="utf-8", newline="\n")
    metadata = {
        "version": version, "release_id": release_id, "package_root": str(package_root.resolve()),
        "package_manifest": str(package_manifest.resolve()), "manifest_sha256": manifest_sha256,
        "payload_sha256": payload_sha256, "payload_bytes": sum(item["size"] for item in artifacts), "artifacts": artifacts,
        "include_file": str(include.resolve()), "include_sha256": _sha256(include), "output_root": str(output_root.resolve()),
    }
    (output_root / "release-metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return metadata


def _validate_macro_path(value: str, label: str) -> None:
    if not value or any(token in value for token in ('{', '}', '"', '\r', '\n')):
        raise InstallerPreparationError(f"{label} is unsafe for an Inno preprocessor argument")


def build_installer(preparation: dict[str, Any], compiler: Path, template: Path | None = None, *, timeout_seconds: float = 1800) -> int:
    """Run ISCC once, preserving raw output and refusing input drift."""
    if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
        raise InstallerPreparationError("timeout_seconds must be a positive number")
    compiler = Path(compiler)
    output_root = Path(preparation["output_root"])
    template = Path(template) if template else Path(__file__).resolve().parents[1] / "packaging" / "agent_review.iss"
    if not compiler.is_file() or not template.is_file() or _is_reparse(compiler) or _is_reparse(template):
        raise InstallerPreparationError("compiler and template must be regular non-reparse files")
    _assert_nonreparse_ancestors(compiler)
    _assert_nonreparse_ancestors(template)
    document, manifest_sha256 = _load_manifest(Path(preparation["package_root"]), Path(preparation["package_manifest"]))
    if manifest_sha256 != preparation["manifest_sha256"]:
        raise InstallerPreparationError("manifest changed after preparation")
    artifacts = _validate_payload(Path(preparation["package_root"]), document)
    if artifacts != preparation["artifacts"] or _sha256(Path(preparation["include_file"])) != preparation["include_sha256"]:
        raise InstallerPreparationError("prepared payload or generated include changed before compilation")
    for value, label in ((str(preparation["package_root"]), "package path"), (str(output_root), "output path"),
                         (str(preparation["include_file"]), "include path"), (str(preparation["release_id"]), "release id"),
                         (str(preparation["version"]), "version")):
        _validate_macro_path(value, label)
    command = [str(compiler), f'/DSourceRoot={preparation["package_root"]}', f'/DReleaseId={preparation["release_id"]}', f'/DProductVersion={preparation["version"]}', f'/DBuildOutputDir={output_root}', f'/DIncludeFile={preparation["include_file"]}', f'/DProductAppId={PRODUCT_APP_ID}', f'/DProductAppName={PRODUCT_NAME}', str(template)]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(command, capture_output=True, check=False, timeout=timeout_seconds, creationflags=creationflags)
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as error:
        timed_out, exit_code = True, 124
        stdout, stderr = error.stdout or b"", error.stderr or b""
    (output_root / "compiler-stdout.bin").write_bytes(stdout)
    (output_root / "compiler-stderr.bin").write_bytes(stderr)
    expected = output_root / f'AgentReview-{preparation["release_id"]}.exe'
    artifacts_out = []
    if expected.is_file() and expected.stat().st_size > 0:
        artifacts_out.append({"path": expected.name, "sha256": _sha256(expected), "size": expected.stat().st_size})
    try:
        post_document, post_manifest_sha256 = _load_manifest(Path(preparation["package_root"]), Path(preparation["package_manifest"]))
        post_artifacts = _validate_payload(Path(preparation["package_root"]), post_document)
        source_unchanged = post_manifest_sha256 == preparation["manifest_sha256"] and post_artifacts == preparation["artifacts"]
    except InstallerPreparationError:
        source_unchanged = False
    result = {"command": command, "exit_code": exit_code, "timed_out": timed_out,
              "elapsed_seconds": time.monotonic() - started, "artifacts": artifacts_out,
              "source_unchanged_after_compile": source_unchanged}
    (output_root / "compiler-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if exit_code == 0 and not timed_out and source_unchanged and artifacts_out else (exit_code or 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    args = parser.parse_args()
    try:
        preparation = prepare_installer(args.package, args.manifest, args.output, args.version)
        return build_installer(preparation, args.compiler, args.template, timeout_seconds=args.timeout_seconds)
    except InstallerPreparationError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
