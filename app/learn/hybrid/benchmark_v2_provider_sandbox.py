"""Production-owned provider bootstrap and irreversible file-open sandbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import types
from typing import Any, Mapping


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_ROOT = (_PROJECT_ROOT / "tests" / "fixtures" / "portfolio_hybrid_v1_1").resolve()
_PARENT_PATH = _FIXTURE_ROOT / "corpus-manifest.v1.json"
_GOLD_PATH = _FIXTURE_ROOT / "gold.v1.json"
_BOOTSTRAP_PATH = Path(__file__).resolve()
_CODE_PATHS = {
    "bootstrap": _BOOTSTRAP_PATH,
    "contracts": _PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_contracts.py",
    "corpus_loader": _PROJECT_ROOT / "app" / "learn" / "hybrid" / "benchmark_v2_provider_corpus.py",
}
_FORBIDDEN_FIXTURE_NAMES = {
    "benchmark-v2-manifest.template.json",
    "benchmark-v2-private-manifest.json",
    "corpus-manifest.v1.json",
    "gold.v1.json",
    "manifest.template.json",
    "reviewed_hybrid_source.json",
}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ARGV_FLAGS = (
    "--provider-manifest",
    "--provider-manifest-sha256",
    "--provider-child",
    "--provider-child-sha256",
    "--operation-root",
    "--output-root",
    "--ledger-root",
)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _contains_reparse_component(path: Path) -> bool:
    candidate = Path(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if not current.exists() and not current.is_symlink():
            continue
        details = os.lstat(current)
        attributes = getattr(details, "st_file_attributes", 0)
        if current.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            return True
    return False


def _canonical_existing(path: Path, *, kind: str) -> Path:
    raw = str(path)
    candidate = Path(raw)
    if not candidate.is_absolute() or any(token in raw for token in ("%", "$", "~")):
        raise ValueError(f"{kind} must be an exact canonical absolute path")
    if _contains_reparse_component(candidate):
        raise ValueError(f"{kind} cannot contain a symlink or reparse component")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{kind} does not exist") from exc
    if raw != str(resolved):
        raise ValueError(f"{kind} must use exact canonical path spelling")
    return resolved


def _canonical_open_path(path: Path) -> Path:
    raw = str(path)
    candidate = Path(raw)
    if not candidate.is_absolute() or _contains_reparse_component(candidate.parent):
        raise PermissionError("provider open path is relative or reparse-aliased")
    resolved = candidate.resolve(strict=False)
    if raw != str(resolved):
        raise PermissionError("provider open path is not canonical")
    return resolved


def _identity(path: Path) -> tuple[int, int, int]:
    details = os.stat(path, follow_symlinks=False)
    return (details.st_dev, details.st_ino, details.st_size)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_sha(value: str, name: str) -> str:
    if _SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def minimal_provider_environment() -> dict[str, str]:
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("SystemRoot")
    if not system_root:
        raise ValueError("SYSTEMROOT is required for the isolated Windows provider process")
    canonical_system_root = _canonical_existing(Path(system_root), kind="SYSTEMROOT")
    return {
        "SYSTEMROOT": str(canonical_system_root),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }


def _command_values(argv: tuple[str, ...]) -> dict[str, str]:
    if len(argv) != 19:
        raise ValueError("provider bootstrap argv cardinality is invalid")
    if argv[1:4] != ("-I", "-S", str(_BOOTSTRAP_PATH)):
        raise ValueError("provider bootstrap executable prefix is invalid")
    if argv[4] != "--provider-bootstrap":
        raise ValueError("provider bootstrap mode is invalid")
    values: dict[str, str] = {}
    position = 5
    for flag in _ARGV_FLAGS:
        if argv[position] != flag:
            raise ValueError("provider bootstrap argv schema is invalid")
        values[flag] = argv[position + 1]
        position += 2
    return values


def _assert_outside(path: Path, roots: tuple[Path, ...], name: str) -> None:
    if any(_inside(path, root) or _inside(root, path) for root in roots):
        raise ValueError(f"{name} exposes a forbidden root")


def validate_provider_process_projection(
    *,
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path,
    stdin: bytes,
    forbidden_roots: tuple[Path, ...],
) -> None:
    values = _command_values(argv)
    if dict(env) != minimal_provider_environment():
        raise ValueError("provider environment must match the minimal closed allowlist")
    if stdin != b"":
        raise ValueError("provider stdin must be fixed empty")
    executable = _canonical_existing(Path(argv[0]), kind="provider executable")
    if executable != _canonical_existing(Path(sys.executable), kind="current executable"):
        raise ValueError("provider executable identity is invalid")
    manifest = _canonical_existing(Path(values["--provider-manifest"]), kind="provider manifest")
    child = _canonical_existing(Path(values["--provider-child"]), kind="provider child")
    roots = tuple(
        _canonical_existing(Path(values[flag]), kind=flag)
        for flag in ("--operation-root", "--output-root", "--ledger-root")
    )
    if not all(path.is_dir() for path in roots) or len(set(roots)) != 3:
        raise ValueError("provider operation/output/ledger roots must be existing and distinct")
    if _canonical_existing(Path(cwd), kind="provider cwd") != roots[0]:
        raise ValueError("provider cwd must be the exact operation root")
    _require_sha(values["--provider-manifest-sha256"], "provider manifest SHA")
    _require_sha(values["--provider-child-sha256"], "provider child SHA")
    private_roots = tuple(
        _canonical_existing(Path(path), kind="forbidden root") for path in forbidden_roots
    )
    named = (("manifest", manifest), ("child", child), *zip(("operation", "output", "ledger"), roots, strict=True))
    for name, path in named:
        _assert_outside(path, private_roots, name)
    normalized_private = [str(path).casefold() for path in private_roots]
    for item in (*argv[4:], *env.keys(), *env.values()):
        lowered = str(item).casefold()
        if any(value in lowered for value in normalized_private):
            raise ValueError("provider process projection contains a private path")


def build_provider_bootstrap_command(
    *,
    provider_manifest_path: Path,
    expected_manifest_sha256: str,
    provider_child_path: Path,
    expected_child_sha256: str,
    operation_root: Path,
    output_root: Path,
    ledger_root: Path,
) -> tuple[str, ...]:
    executable = _canonical_existing(Path(sys.executable), kind="provider executable")
    manifest = _canonical_existing(provider_manifest_path, kind="provider manifest")
    child = _canonical_existing(provider_child_path, kind="provider child")
    operation = _canonical_existing(operation_root, kind="operation root")
    output = _canonical_existing(output_root, kind="output root")
    ledger = _canonical_existing(ledger_root, kind="ledger root")
    return (
        str(executable), "-I", "-S", str(_BOOTSTRAP_PATH), "--provider-bootstrap",
        "--provider-manifest", str(manifest),
        "--provider-manifest-sha256", _require_sha(expected_manifest_sha256, "provider manifest SHA"),
        "--provider-child", str(child),
        "--provider-child-sha256", _require_sha(expected_child_sha256, "provider child SHA"),
        "--operation-root", str(operation),
        "--output-root", str(output),
        "--ledger-root", str(ledger),
    )


@dataclass(frozen=True)
class ProviderFilePolicy:
    read_files: frozenset[Path]
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]


def _is_write(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and any(token in mode for token in ("w", "a", "x", "+")):
        return True
    if isinstance(flags, int):
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        return bool(flags & write_flags)
    return False


class _AuditState:
    def __init__(self, *, boot_reads: tuple[Path, ...], read_roots: tuple[Path, ...] = ()) -> None:
        self._phase = "boot"
        self._read_identities = {path: _identity(path) for path in boot_reads}
        self._read_roots = read_roots
        self._write_roots: tuple[Path, ...] = ()

    def add_controlled_reads(self, paths: tuple[Path, ...]) -> None:
        if self._phase != "boot":
            raise RuntimeError("provider audit can only add reads during sealed bootstrap")
        for path in paths:
            self._read_identities[path] = _identity(path)

    def tighten(
        self,
        *,
        read_files: tuple[Path, ...],
        read_roots: tuple[Path, ...],
        write_roots: tuple[Path, ...],
    ) -> ProviderFilePolicy:
        if self._phase != "boot":
            raise RuntimeError("provider audit policy is already tightened")
        allowed = set(read_files)
        if not allowed.issubset(self._read_identities):
            raise RuntimeError("tight policy contains an unverified read identity")
        self._read_identities = {path: self._read_identities[path] for path in allowed}
        self._read_roots = read_roots
        self._write_roots = write_roots
        self._phase = "tight"
        return ProviderFilePolicy(frozenset(allowed), read_roots, write_roots)

    def audit(self, event: str, args: tuple[object, ...]) -> None:
        if event != "open" or not args:
            return
        raw_path = args[0]
        if isinstance(raw_path, int):
            if raw_path in {0, 1, 2}:
                return
            raise PermissionError("provider integer fd denied without policy provenance")
        try:
            decoded = os.fsdecode(raw_path)
        except (TypeError, ValueError, OSError) as exc:
            raise PermissionError("provider open path is invalid") from exc
        writing = _is_write(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        path = _canonical_open_path(Path(decoded))
        if writing:
            if self._phase == "tight" and any(_inside(path, root) for root in self._write_roots):
                return
            raise PermissionError(f"provider write denied: {path}")
        expected = self._read_identities.get(path)
        if expected is not None:
            try:
                observed = _identity(path)
            except OSError as exc:
                raise PermissionError("provider read identity disappeared") from exc
            if observed != expected:
                raise PermissionError("provider read identity changed after sealing")
            return
        if any(_inside(path, root) for root in self._read_roots):
            return
        raise PermissionError(f"provider read denied: {path}")


def _validated_policy_paths(
    *, read_files: tuple[Path, ...], read_roots: tuple[Path, ...], write_roots: tuple[Path, ...]
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    reads = tuple(_canonical_existing(path, kind="sealed read") for path in read_files)
    roots = tuple(_canonical_existing(path, kind="read root") for path in read_roots)
    writes = tuple(_canonical_existing(path, kind="write root") for path in write_roots)
    if not reads:
        raise ValueError("provider file policy requires exact sealed read files")
    if not writes:
        raise ValueError("provider file policy requires output roots")
    if any(
        _inside(_FIXTURE_ROOT, root) or _inside(root, _PROJECT_ROOT) or _inside(_PROJECT_ROOT, root)
        for root in roots
    ):
        raise ValueError("fixture/project reads must be exact files, not broad roots")
    for path in reads:
        lowered_name = path.name.casefold()
        if any(token in lowered_name for token in ("gold", "private", "scorer")):
            raise ValueError("provider file policy cannot allow a private fixture or scorer")
        if _inside(path, _FIXTURE_ROOT) and lowered_name in _FORBIDDEN_FIXTURE_NAMES:
            raise ValueError("provider file policy cannot allow a private fixture or scorer")
    if any(_inside(root, _FIXTURE_ROOT) or _inside(_FIXTURE_ROOT, root) for root in writes):
        raise ValueError("provider process cannot write inside the fixture root")
    return reads, roots, writes


def install_provider_file_policy(
    *, read_files: tuple[Path, ...], read_roots: tuple[Path, ...], write_roots: tuple[Path, ...]
) -> object:
    reads, roots, writes = _validated_policy_paths(
        read_files=read_files, read_roots=read_roots, write_roots=write_roots
    )
    state = _AuditState(boot_reads=reads, read_roots=roots)
    sys.addaudithook(state.audit)
    return state.tighten(read_files=reads, read_roots=roots, write_roots=writes)


def _load_sealed_provider_modules() -> tuple[types.ModuleType, types.ModuleType]:
    for name in ("app", "app.learn", "app.learn.hybrid"):
        if name in sys.modules:
            raise RuntimeError("provider package imported before bootstrap audit")
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
    loaded: list[types.ModuleType] = []
    for name, path in (
        ("app.learn.hybrid.benchmark_v2_contracts", _CODE_PATHS["contracts"]),
        ("app.learn.hybrid.benchmark_v2_provider_corpus", _CODE_PATHS["corpus_loader"]),
    ):
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = name.rpartition(".")[0]
        sys.modules[name] = module
        source = path.read_bytes()
        exec(compile(source, str(path), "exec"), module.__dict__)
        loaded.append(module)
    return loaded[0], loaded[1]


def _manifest_value(path: Path, expected_sha: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("provider manifest file SHA mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider manifest is not UTF-8 JSON") from exc
    canonical = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if raw != canonical:
        raise ValueError("provider manifest bytes are not canonical")
    return value


def _prevalidate_boot_manifest(value: object, *, expected_child_sha: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "contract_version",
        "benchmark_release_id",
        "provider_corpus_ref",
        "sealed_runtime",
        "arm_order",
        "safety",
    }:
        raise ValueError("provider boot manifest is not a closed object")
    runtime = value.get("sealed_runtime")
    if not isinstance(runtime, dict) or set(runtime) != {"code_refs", "profile_refs"}:
        raise ValueError("provider boot runtime seal is invalid")
    refs = runtime.get("code_refs")
    expected = tuple(_CODE_PATHS.items())
    if not isinstance(refs, list) or len(refs) != len(expected):
        raise ValueError("provider boot code seal is incomplete")
    for item, (role, path) in zip(refs, expected, strict=True):
        if not isinstance(item, dict) or set(item) != {"role", "relative_path", "file_sha256"}:
            raise ValueError("provider boot code ref is invalid")
        relative = path.relative_to(_PROJECT_ROOT).as_posix()
        if item.get("role") != role or item.get("relative_path") != relative:
            raise ValueError("provider boot code ref identity is invalid")
        expected_sha = _require_sha(str(item.get("file_sha256")), "provider boot code SHA")
        if _file_sha(path) != expected_sha:
            raise ValueError("provider boot code SHA mismatch before import")
    child_ref = value.get("provider_corpus_ref")
    if (
        not isinstance(child_ref, dict)
        or child_ref.get("relative_path") != "provider-corpus.v2.json"
        or child_ref.get("file_sha256") != expected_child_sha
    ):
        raise ValueError("provider boot child ref is invalid")
    return value


def _verify_file_ref(path: Path, expected_sha: str, name: str) -> None:
    if _file_sha(path) != expected_sha:
        raise ValueError(f"{name} file SHA mismatch")


def _unexpected_fds() -> list[int]:
    found: list[int] = []
    for descriptor in range(3, 2048):
        try:
            os.fstat(descriptor)
        except OSError:
            continue
        found.append(descriptor)
    return found


def _expect_denied(name: str, action: Any, results: list[str]) -> None:
    try:
        action()
    except (PermissionError, NotImplementedError, OSError, TypeError, ValueError):
        results.append(name)
        return
    raise RuntimeError(f"provider boundary probe escaped audit: {name}")


def _bootstrap_argv_values(argv: tuple[str, ...]) -> dict[str, str]:
    full = (str(_canonical_existing(Path(sys.executable), kind="provider executable")), "-I", "-S", str(_BOOTSTRAP_PATH), *argv)
    return _command_values(full)


def _run_provider_bootstrap(argv: tuple[str, ...]) -> dict[str, Any]:
    values = _bootstrap_argv_values(argv)
    manifest_path = _canonical_existing(Path(values["--provider-manifest"]), kind="provider manifest")
    child_path = _canonical_existing(Path(values["--provider-child"]), kind="provider child")
    write_roots = tuple(
        _canonical_existing(Path(values[flag]), kind=flag)
        for flag in ("--operation-root", "--output-root", "--ledger-root")
    )
    boot_reads = (manifest_path, child_path, *_CODE_PATHS.values())
    state = _AuditState(boot_reads=boot_reads)
    sys.addaudithook(state.audit)
    full_argv = (str(_canonical_existing(Path(sys.executable), kind="provider executable")), "-I", "-S", str(_BOOTSTRAP_PATH), *argv)
    validate_provider_process_projection(
        argv=full_argv,
        env=dict(os.environ),
        cwd=Path.cwd(),
        stdin=b"",
        forbidden_roots=(_FIXTURE_ROOT,),
    )
    unexpected_fds = _unexpected_fds()
    if unexpected_fds:
        raise PermissionError("provider process inherited unexpected file descriptors")
    boot_manifest = _prevalidate_boot_manifest(
        _manifest_value(
            manifest_path,
            _require_sha(values["--provider-manifest-sha256"], "provider manifest SHA"),
        ),
        expected_child_sha=values["--provider-child-sha256"],
    )
    _, corpus_module = _load_sealed_provider_modules()
    manifest = corpus_module.validate_provider_manifest(boot_manifest)
    child = corpus_module.load_provider_corpus(
        child_path=child_path,
        expected_sha256=_require_sha(values["--provider-child-sha256"], "provider child SHA"),
    )
    child_ref = manifest["provider_corpus_ref"]
    if (
        child_path != manifest_path.parent / child_ref["relative_path"]
        or child_ref["file_sha256"] != values["--provider-child-sha256"]
        or child_ref["content_sha256"] != child["content_sha256"]
        or child_ref["source_parent_ref"] != child["source_parent_ref"]
    ):
        raise ValueError("provider manifest and child identity differ")
    code_paths: list[Path] = []
    for item in manifest["sealed_runtime"]["code_refs"]:
        path = _canonical_existing(_PROJECT_ROOT / item["relative_path"], kind="sealed provider code")
        if path != _CODE_PATHS[item["role"]]:
            raise ValueError("sealed provider code resolved to the wrong identity")
        code_paths.append(path)
    profile_paths = tuple(
        _canonical_existing(_PROJECT_ROOT / item["relative_path"], kind="sealed provider profile")
        for item in manifest["sealed_runtime"]["profile_refs"]
    )
    screenshot_paths = tuple(sorted({
        _canonical_existing(_PROJECT_ROOT / case["image"]["path"], kind="provider screenshot")
        for case in child["cases"]
    }))
    if len(screenshot_paths) != 24:
        raise ValueError("provider child must resolve exactly 24 screenshots")
    controlled = (*profile_paths, *screenshot_paths)
    state.add_controlled_reads(controlled)
    for item, path in zip(manifest["sealed_runtime"]["code_refs"], code_paths, strict=True):
        _verify_file_ref(path, item["file_sha256"], f"provider code {item['role']}")
    for item, path in zip(manifest["sealed_runtime"]["profile_refs"], profile_paths, strict=True):
        _verify_file_ref(path, item["file_sha256"], f"provider profile {item['role']}")
    screenshot_hashes = {case["image"]["path"]: case["image"]["sha256"] for case in child["cases"]}
    for path in screenshot_paths:
        _verify_file_ref(path, screenshot_hashes[path.relative_to(_PROJECT_ROOT).as_posix()], "provider screenshot")
    reads = (manifest_path, child_path, *code_paths, *profile_paths, *screenshot_paths)
    state.tighten(read_files=reads, read_roots=(), write_roots=write_roots)
    manifest_path.read_bytes()
    child_path.read_bytes()
    for path in code_paths:
        with open(path, "rb") as stream:
            if not stream.read(1):
                raise ValueError("sealed provider code is empty")
    for path in profile_paths:
        path.read_bytes()
    for path in screenshot_paths:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            if not os.read(descriptor, 1):
                raise ValueError("provider screenshot is empty")
        finally:
            os.close(descriptor)
    for root in write_roots:
        target = root / "provider-bootstrap-write-probe.json"
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, b"{}")
        finally:
            os.close(descriptor)
    denied: list[str] = []
    _expect_denied("builtin_parent", lambda: open(_PARENT_PATH, "rb"), denied)
    _expect_denied("pathlib_gold", lambda: _GOLD_PATH.read_bytes(), denied)
    _expect_denied("os_open_parent", lambda: os.open(_PARENT_PATH, os.O_RDONLY), denied)
    _expect_denied("relative_parent", lambda: open("corpus-manifest.v1.json", "rb"), denied)
    _expect_denied("case_alias", lambda: open(Path(str(_CODE_PATHS["contracts"]).upper()), "rb"), denied)
    alias = write_roots[0] / "provider-boundary-parent-alias" / "corpus-manifest.v1.json"
    if alias.exists():
        _expect_denied("reparse_alias", lambda: alias.read_bytes(), denied)
    _expect_denied("integer_fd", lambda: open(3, "rb", closefd=False), denied)
    _expect_denied("dir_fd", lambda: os.open("corpus-manifest.v1.json", os.O_RDONLY, dir_fd=3), denied)
    return {
        "contract_version": "portfolio_hybrid_v1_1_provider_bootstrap_receipt_v1",
        "boot_policy_installed": True,
        "tight_policy_installed": True,
        "child_case_count": len(child["cases"]),
        "screen_count": len(screenshot_paths),
        "sealed_code_count": len(code_paths),
        "sealed_profile_count": len(profile_paths),
        "allowed_read_count": len(reads),
        "allowed_write_roots": ["operation", "output", "ledger"],
        "denied_open_probes": denied,
        "unexpected_inherited_fds": unexpected_fds,
    }


def spawn_provider_bootstrap(
    *,
    provider_manifest_path: Path,
    expected_manifest_sha256: str,
    provider_child_path: Path,
    expected_child_sha256: str,
    operation_root: Path,
    output_root: Path,
    ledger_root: Path,
) -> dict[str, Any]:
    argv = build_provider_bootstrap_command(
        provider_manifest_path=provider_manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        provider_child_path=provider_child_path,
        expected_child_sha256=expected_child_sha256,
        operation_root=operation_root,
        output_root=output_root,
        ledger_root=ledger_root,
    )
    environment = minimal_provider_environment()
    operation = _canonical_existing(operation_root, kind="operation root")
    validate_provider_process_projection(
        argv=argv,
        env=environment,
        cwd=operation,
        stdin=b"",
        forbidden_roots=(_FIXTURE_ROOT,),
    )
    if _file_sha(_canonical_existing(provider_manifest_path, kind="provider manifest")) != expected_manifest_sha256:
        raise ValueError("provider manifest file SHA mismatch before spawn")
    if _file_sha(_canonical_existing(provider_child_path, kind="provider child")) != expected_child_sha256:
        raise ValueError("provider child file SHA mismatch before spawn")
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        load_provider_corpus,
        validate_provider_manifest,
    )

    manifest = validate_provider_manifest(
        _manifest_value(provider_manifest_path, expected_manifest_sha256)
    )
    child = load_provider_corpus(
        child_path=provider_child_path,
        expected_sha256=expected_child_sha256,
    )
    child_ref = manifest["provider_corpus_ref"]
    if (
        provider_child_path != provider_manifest_path.parent / child_ref["relative_path"]
        or child_ref["file_sha256"] != expected_child_sha256
        or child_ref["content_sha256"] != child["content_sha256"]
        or child_ref["source_parent_ref"] != child["source_parent_ref"]
    ):
        raise ValueError("provider manifest and child identity differ before spawn")
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": []}
    process = subprocess.Popen(
        argv,
        cwd=operation,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        close_fds=True,
        startupinfo=startupinfo,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
    if process.returncode != 0:
        raise ValueError(f"provider bootstrap failed closed: {stderr.strip()}")
    try:
        receipt = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("provider bootstrap receipt is invalid") from exc
    receipt["process_id"] = process.pid
    return receipt


def _main() -> int:
    if tuple(sys.argv[1:2]) != ("--provider-bootstrap",):
        raise ValueError("provider sandbox has one closed bootstrap entrypoint")
    if sys.stdin.buffer.read(1) != b"":
        raise ValueError("provider bootstrap stdin must be empty")
    print(json.dumps(_run_provider_bootstrap(tuple(sys.argv[1:])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
