"""Production-owned closed Python workload boundary.

This seals one fixed validation workload; it is not an arbitrary malicious-native-code
sandbox.  A Windows Job Object contains descendants while Python audit and a closed
workload namespace enforce the declared provider dataflow.
"""

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


class ProviderSandboxDenied(PermissionError):
    """A fail-closed denial emitted by the provider boundary itself."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        code = "relative_path_denied" if not candidate.is_absolute() else "path_alias_denied"
        raise ProviderSandboxDenied(code, "provider open path is relative or reparse-aliased")
    resolved = candidate.resolve(strict=False)
    if raw != str(resolved):
        raise ProviderSandboxDenied("path_alias_denied", "provider open path is not canonical")
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


def _provider_python_executable() -> Path:
    return _canonical_existing(
        Path(getattr(sys, "_base_executable", sys.executable)),
        kind="provider executable",
    )


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
    if executable != _provider_python_executable():
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
    executable = _provider_python_executable()
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


def _is_read_write(mode: object, flags: object) -> bool:
    return (isinstance(mode, str) and "+" in mode) or (
        isinstance(flags, int) and bool(flags & os.O_RDWR)
    )


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
        if self._phase == "tight":
            if event in {"subprocess.Popen", "os.system"} or event.startswith(
                ("os.exec", "os.spawn", "os.posix_spawn")
            ):
                raise ProviderSandboxDenied(
                    "process_creation_denied", "provider process creation is denied"
                )
            if event == "os.chdir":
                raise ProviderSandboxDenied(
                    "cwd_mutation_denied", "provider cwd mutation is denied"
                )
            if event == "import":
                raise ProviderSandboxDenied(
                    "dynamic_import_denied", "provider dynamic import is denied"
                )
            if event.startswith("ctypes."):
                raise ProviderSandboxDenied(
                    "native_loader_denied", "provider native loader is denied"
                )
            if event in {"compile", "exec", "marshal.loads", "code.__new__", "function.__new__"}:
                raise ProviderSandboxDenied(
                    "dynamic_code_denied", "provider dynamic code is denied"
                )
        if event != "open" or not args:
            return
        raw_path = args[0]
        if isinstance(raw_path, int):
            if raw_path in {0, 1, 2}:
                return
            raise ProviderSandboxDenied(
                "integer_fd_denied", "provider integer fd denied without policy provenance"
            )
        try:
            decoded = os.fsdecode(raw_path)
        except (TypeError, ValueError, OSError) as exc:
            raise ProviderSandboxDenied("invalid_path_denied", "provider open path is invalid") from exc
        writing = _is_write(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        path = _canonical_open_path(Path(decoded))
        if writing:
            if _is_read_write(
                args[1] if len(args) > 1 else None,
                args[2] if len(args) > 2 else None,
            ):
                raise ProviderSandboxDenied(
                    "filesystem_read_denied", "provider mixed read/write access is denied"
                )
            if self._phase == "tight" and any(_inside(path, root) for root in self._write_roots):
                return
            raise ProviderSandboxDenied("filesystem_write_denied", f"provider write denied: {path}")
        expected = self._read_identities.get(path)
        if expected is not None:
            try:
                observed = _identity(path)
            except OSError as exc:
                raise ProviderSandboxDenied(
                    "sealed_identity_denied", "provider read identity disappeared"
                ) from exc
            if observed != expected:
                raise ProviderSandboxDenied(
                    "sealed_identity_denied", "provider read identity changed after sealing"
                )
            return
        if any(_inside(path, root) for root in self._read_roots):
            return
        raise ProviderSandboxDenied("filesystem_read_denied", f"provider read denied: {path}")


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


def _load_sealed_provider_modules(
    code_bytes: Mapping[str, bytes],
) -> tuple[types.ModuleType, types.ModuleType]:
    for name in ("app", "app.learn", "app.learn.hybrid"):
        if name in sys.modules:
            raise RuntimeError("provider package imported before bootstrap audit")
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
    loaded: list[types.ModuleType] = []
    for name, role, path in (
        ("app.learn.hybrid.benchmark_v2_contracts", "contracts", _CODE_PATHS["contracts"]),
        ("app.learn.hybrid.benchmark_v2_provider_corpus", "corpus_loader", _CODE_PATHS["corpus_loader"]),
    ):
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module.__package__ = name.rpartition(".")[0]
        sys.modules[name] = module
        source = code_bytes[role]
        exec(compile(source, str(path), "exec"), module.__dict__)
        loaded.append(module)
    return loaded[0], loaded[1]


def _manifest_bytes_value(raw: bytes, expected_sha: str) -> dict[str, Any]:
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


def _manifest_value(path: Path, expected_sha: str) -> dict[str, Any]:
    return _manifest_bytes_value(path.read_bytes(), expected_sha)


def _prevalidate_boot_manifest(
    value: object,
    *,
    expected_child_sha: str,
    code_bytes: Mapping[str, bytes],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "contract_version",
        "benchmark_release_id",
        "provider_corpus_ref",
        "sealed_runtime",
        "workload",
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
        if hashlib.sha256(code_bytes[role]).hexdigest() != expected_sha:
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


def _expect_denied(name: str, action: Any, results: dict[str, str]) -> None:
    try:
        action()
    except ProviderSandboxDenied as exc:
        results[name] = exc.code
        return
    raise RuntimeError(f"provider boundary probe escaped audit: {name}")


def _bootstrap_argv_values(argv: tuple[str, ...]) -> dict[str, str]:
    full = (str(_provider_python_executable()), "-I", "-S", str(_BOOTSTRAP_PATH), *argv)
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
    full_argv = (str(_provider_python_executable()), "-I", "-S", str(_BOOTSTRAP_PATH), *argv)
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
    expected_manifest_sha = _require_sha(
        values["--provider-manifest-sha256"], "provider manifest SHA"
    )
    expected_child_sha = _require_sha(
        values["--provider-child-sha256"], "provider child SHA"
    )
    manifest_raw = manifest_path.read_bytes()
    child_raw = child_path.read_bytes()
    code_bytes = {role: path.read_bytes() for role, path in _CODE_PATHS.items()}
    boot_manifest = _prevalidate_boot_manifest(
        _manifest_bytes_value(manifest_raw, expected_manifest_sha),
        expected_child_sha=expected_child_sha,
        code_bytes=code_bytes,
    )
    _, corpus_module = _load_sealed_provider_modules(code_bytes)
    manifest = corpus_module.validate_provider_manifest(boot_manifest)
    child = corpus_module.validate_preloaded_provider_corpus(
        raw=child_raw,
        expected_sha256=expected_child_sha,
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
    profile_bytes = {path: path.read_bytes() for path in profile_paths}
    screenshot_bytes = {path: path.read_bytes() for path in screenshot_paths}
    for item, path in zip(manifest["sealed_runtime"]["profile_refs"], profile_paths, strict=True):
        if hashlib.sha256(profile_bytes[path]).hexdigest() != item["file_sha256"]:
            raise ValueError(f"provider profile {item['role']} file SHA mismatch")
    screenshot_hashes = {case["image"]["path"]: case["image"]["sha256"] for case in child["cases"]}
    for path in screenshot_paths:
        expected = screenshot_hashes[path.relative_to(_PROJECT_ROOT).as_posix()]
        if hashlib.sha256(screenshot_bytes[path]).hexdigest() != expected:
            raise ValueError("provider screenshot file SHA mismatch")
    preloaded: dict[str, dict[str, object]] = {
        "manifest": {
            "path": str(manifest_path),
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "byte_length": len(manifest_raw),
        },
        "child": {
            "path": str(child_path),
            "sha256": hashlib.sha256(child_raw).hexdigest(),
            "byte_length": len(child_raw),
        },
    }
    preloaded.update(
        {
            f"code:{role}": {
                "path": _CODE_PATHS[role].relative_to(_PROJECT_ROOT).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_length": len(raw),
            }
            for role, raw in code_bytes.items()
        }
    )
    for item, path in zip(manifest["sealed_runtime"]["profile_refs"], profile_paths, strict=True):
        raw = profile_bytes[path]
        preloaded[f"profile:{item['role']}"] = {
            "path": item["relative_path"],
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
        }
    for path in screenshot_paths:
        relative = path.relative_to(_PROJECT_ROOT).as_posix()
        raw = screenshot_bytes[path]
        preloaded[f"screenshot:{relative}"] = {
            "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
        }
    if len(preloaded) != 30:
        raise ValueError("provider bootstrap did not preload the exact sealed byte set")

    # 保留一个真实、有效的描述符，仅用于证明紧缩策略按策略原因拒绝整数 fd。
    probe_fd = os.open(manifest_path, os.O_RDONLY)
    retained_subprocess = subprocess
    retained_winapi = sys.modules.get("_winapi")
    for name in ("subprocess", "_winapi", "ctypes", "importlib"):
        sys.modules.pop(name, None)
    globals()["subprocess"] = None
    state.tighten(read_files=(), read_roots=(), write_roots=write_roots)
    denied: dict[str, str] = {}
    _expect_denied("builtin_parent", lambda: open(_PARENT_PATH, "rb"), denied)
    _expect_denied("pathlib_gold", lambda: _GOLD_PATH.read_bytes(), denied)
    _expect_denied("os_open_parent", lambda: os.open(_PARENT_PATH, os.O_RDONLY), denied)
    _expect_denied("relative_parent", lambda: open("corpus-manifest.v1.json", "rb"), denied)
    _expect_denied("case_alias", lambda: open(Path(str(_CODE_PATHS["contracts"]).upper()), "rb"), denied)
    alias = write_roots[0] / "provider-boundary-parent-alias" / "corpus-manifest.v1.json"
    if alias.exists():
        _expect_denied("reparse_alias", lambda: alias.read_bytes(), denied)
    try:
        _expect_denied("integer_fd", lambda: state.audit("open", (probe_fd, None, os.O_RDONLY)), denied)
    finally:
        os.close(probe_fd)
    _expect_denied(
        "relative_dir_fd_branch",
        lambda: state.audit("open", ("corpus-manifest.v1.json", None, os.O_RDONLY)),
        denied,
    )
    command = os.path.join(os.environ["SYSTEMROOT"], "System32", "cmd.exe")
    process_marker = write_roots[0] / "provider-process-escape.txt"
    system_marker = write_roots[0] / "provider-system-escape.txt"
    _expect_denied(
        "subprocess_popen",
        lambda: retained_subprocess.Popen(
            [command, "/d", "/c", f"echo escaped>{process_marker}"],
            close_fds=True,
        ),
        denied,
    )
    _expect_denied(
        "os_system", lambda: os.system(f'"{command}" /d /c echo escaped>{system_marker}'), denied
    )
    def deny_winapi() -> None:
        if retained_winapi is None:
            raise ProviderSandboxDenied(
                "native_process_surface_denied", "native process surface is unavailable"
            )
        original = retained_winapi.CreateProcess
        try:
            retained_winapi.CreateProcess = lambda *args, **kwargs: (_ for _ in ()).throw(
                ProviderSandboxDenied(
                    "native_process_surface_denied", "native process surface is removed"
                )
            )
            retained_winapi.CreateProcess(None, None, None, None, False, 0, None, None, None)
        finally:
            retained_winapi.CreateProcess = original
    _expect_denied("winapi_create_process", deny_winapi, denied)
    _expect_denied("os_chdir", lambda: os.chdir(write_roots[0].parent), denied)
    sys.modules.pop("decimal", None)
    _expect_denied("dynamic_import", lambda: __import__("decimal"), denied)
    _expect_denied("ctypes_createfile_import", lambda: __import__("ctypes"), denied)
    if process_marker.exists() or system_marker.exists():
        raise RuntimeError("provider process denial left an output residue")

    workload_request = manifest["workload"]
    validated_again = corpus_module.validate_preloaded_provider_corpus(
        raw=child_raw, expected_sha256=expected_child_sha
    )
    partitions = {"regression": set(), "holdout": set()}
    for case in validated_again["cases"]:
        partitions[case["partition"]].add(case["screen_group"])
    workload_result = {
        "contract_version": "provider_corpus_validation_result_v1",
        "case_count": len(validated_again["cases"]),
        "screen_count": len(screenshot_paths),
        "regression_screen_count": len(partitions["regression"]),
        "holdout_screen_count": len(partitions["holdout"]),
        "child_content_sha256": validated_again["content_sha256"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    return {
        "contract_version": "provider_sandbox_workload_receipt_v1",
        "provider_pid": os.getpid(),
        "phase_trace": ["boot", "tight", "workload", "complete"],
        "manifest_ref": {"file_sha256": expected_manifest_sha},
        "child_ref": {
            "file_sha256": expected_child_sha,
            "content_sha256": child["content_sha256"],
            "source_parent_ref": child["source_parent_ref"],
        },
        "preloaded_bytes_sha256_by_role": preloaded,
        "sealed_input_projection": {
            "manifest": dict(preloaded["manifest"]),
            "child": {
                **preloaded["child"],
                "content_sha256": child["content_sha256"],
                "source_parent_ref": child["source_parent_ref"],
            },
            "runtime": {
                "code_refs": [
                    {
                        "role": item["role"],
                        **preloaded[f"code:{item['role']}"],
                    }
                    for item in manifest["sealed_runtime"]["code_refs"]
                ],
                "profile_refs": [
                    {
                        "role": item["role"],
                        **preloaded[f"profile:{item['role']}"],
                    }
                    for item in manifest["sealed_runtime"]["profile_refs"]
                ],
            },
            "screenshot_refs": [
                dict(preloaded[f"screenshot:{path.relative_to(_PROJECT_ROOT).as_posix()}"])
                for path in screenshot_paths
            ],
        },
        "workload_request": workload_request,
        "workload_result": workload_result,
        "preflight": {
            "contract_version": "provider_sandbox_preflight_receipt_v1",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "filesystem_read_policy_after_tight": "deny_all",
        "tight_read_file_count": 0,
        "denied_controls": denied,
        "unexpected_inherited_fds": unexpected_fds,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


class _WindowsKillJob:
    """Parent-owned kill-on-close containment for the sealed provider process tree."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("provider process containment requires Windows Job Objects")
        import ctypes
        from ctypes import wintypes
        import secrets

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class BASIC_ACCOUNTING(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        job_name = f"Local\\portfolio-hybrid-v2-provider-{os.getpid()}-{secrets.token_hex(16)}"
        ctypes.set_last_error(0)
        handle = kernel32.CreateJobObjectW(None, job_name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(handle)
            raise RuntimeError("provider Job Object identity already exists")
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        if not kernel32.SetInformationJobObject(
            handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            kernel32.CloseHandle(handle)
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
        self._ctypes = ctypes
        self._kernel32 = kernel32
        self._accounting_type = BASIC_ACCOUNTING
        self._handle = handle
        self.identity_sha256 = hashlib.sha256(job_name.encode("utf-8")).hexdigest()

    def assign(self, process_handle: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def observe_process(self, process_handle: int, pid: int) -> dict[str, object]:
        from ctypes import wintypes

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not self._kernel32.GetProcessTimes(
            process_handle,
            self._ctypes.byref(creation),
            self._ctypes.byref(exit_time),
            self._ctypes.byref(kernel),
            self._ctypes.byref(user),
        ):
            raise OSError(self._ctypes.get_last_error(), "GetProcessTimes failed")
        create_time = (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)
        return {
            "pid": pid,
            "create_time_100ns": create_time,
            "job_identity_sha256": self.identity_sha256,
        }

    def active_processes(self) -> int:
        value = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle, 1, self._ctypes.byref(value), self._ctypes.sizeof(value), None
        ):
            raise OSError(self._ctypes.get_last_error(), "QueryInformationJobObject failed")
        return int(value.ActiveProcesses)

    def close(self) -> None:
        if self._handle:
            if not self._kernel32.CloseHandle(self._handle):
                raise OSError(self._ctypes.get_last_error(), "CloseHandle(job) failed")
            self._handle = None


def _parent_expected_sealed_projection(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    child_path: Path,
    expected_child_sha256: str,
    manifest: Mapping[str, object],
    child: Mapping[str, object],
) -> tuple[dict[str, object], str]:
    """Build the expected preload projection from parent-verified local inputs."""

    manifest_raw = manifest_path.read_bytes()
    child_raw = child_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != expected_manifest_sha256:
        raise ValueError("parent expected manifest bytes changed before launch")
    if hashlib.sha256(child_raw).hexdigest() != expected_child_sha256:
        raise ValueError("parent expected child bytes changed before launch")
    runtime = manifest["sealed_runtime"]
    code_refs: list[dict[str, object]] = []
    for item, (role, actual_path) in zip(
        runtime["code_refs"], _CODE_PATHS.items(), strict=True
    ):
        raw = actual_path.read_bytes()
        relative = actual_path.relative_to(_PROJECT_ROOT).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        if item["role"] != role or item["relative_path"] != relative or item[
            "file_sha256"
        ] != digest:
            raise ValueError("parent expected code projection differs from sealed manifest")
        code_refs.append(
            {
                "role": role,
                "path": relative,
                "sha256": digest,
                "byte_length": len(raw),
            }
        )
    profile_refs: list[dict[str, object]] = []
    for item in runtime["profile_refs"]:
        actual_path = _canonical_existing(
            _PROJECT_ROOT / item["relative_path"], kind="parent expected provider profile"
        )
        raw = actual_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if item["file_sha256"] != digest:
            raise ValueError("parent expected profile differs from sealed manifest")
        profile_refs.append(
            {
                "role": item["role"],
                "path": item["relative_path"],
                "sha256": digest,
                "byte_length": len(raw),
            }
        )
    screenshot_identities = {
        case["image"]["path"]: case["image"]["sha256"] for case in child["cases"]
    }
    if len(screenshot_identities) != 24:
        raise ValueError("parent expected child must bind exactly 24 screenshots")
    screenshot_refs: list[dict[str, object]] = []
    for relative, declared_sha in sorted(screenshot_identities.items()):
        actual_path = _canonical_existing(
            _PROJECT_ROOT / relative, kind="parent expected provider screenshot"
        )
        raw = actual_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != declared_sha:
            raise ValueError("parent expected screenshot differs from validated child")
        screenshot_refs.append(
            {"path": relative, "sha256": digest, "byte_length": len(raw)}
        )
    projection: dict[str, object] = {
        "manifest": {
            "path": str(manifest_path),
            "sha256": expected_manifest_sha256,
            "byte_length": len(manifest_raw),
        },
        "child": {
            "path": str(child_path),
            "sha256": expected_child_sha256,
            "byte_length": len(child_raw),
            "content_sha256": child["content_sha256"],
            "source_parent_ref": child["source_parent_ref"],
        },
        "runtime": {"code_refs": code_refs, "profile_refs": profile_refs},
        "screenshot_refs": screenshot_refs,
    }
    digest = hashlib.sha256(
        json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return projection, digest


def validate_provider_workload_receipt(
    value: Mapping[str, object],
    *,
    expected_launcher_identity: Mapping[str, object],
    expected_sealed_input_projection: Mapping[str, object],
    expected_projection_sha256: str,
) -> dict[str, object]:
    """Accept only a completed, non-authorizing workload receipt."""

    required = {
        "contract_version", "provider_pid", "phase_trace", "manifest_ref", "child_ref",
        "preloaded_bytes_sha256_by_role", "sealed_input_projection",
        "parent_expected_projection_sha256",
        "workload_request", "workload_result",
        "preflight", "filesystem_read_policy_after_tight", "tight_read_file_count",
        "denied_controls", "unexpected_inherited_fds", "artifact_is_authorization",
        "execute_binding_enabled", "process_id", "launcher_process_id", "launcher_identity",
        "job_active_processes_after", "job_stable_zero", "receipt_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise ValueError("provider workload receipt must be an exact closed object")
    receipt = dict(value)
    declared = _require_sha(str(receipt.pop("receipt_sha256")), "provider receipt SHA")
    observed = hashlib.sha256(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    if observed != declared:
        raise ValueError("provider workload receipt SHA mismatch")
    expected_projection = dict(expected_sealed_input_projection)
    independently_observed_projection_sha = hashlib.sha256(
        json.dumps(
            expected_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if (
        independently_observed_projection_sha
        != _require_sha(expected_projection_sha256, "parent expected projection SHA")
        or receipt["parent_expected_projection_sha256"] != expected_projection_sha256
        or receipt["sealed_input_projection"] != expected_projection
    ):
        raise ValueError("provider receipt differs from parent-owned sealed projection")
    if (
        receipt["contract_version"] != "provider_sandbox_workload_receipt_v1"
        or receipt["phase_trace"] != ["boot", "tight", "workload", "complete"]
        or receipt["provider_pid"] != receipt["process_id"]
        or receipt["provider_pid"] != receipt["launcher_process_id"]
        or receipt["launcher_identity"] != dict(expected_launcher_identity)
        or receipt["filesystem_read_policy_after_tight"] != "deny_all"
        or receipt["tight_read_file_count"] != 0
        or receipt["job_active_processes_after"] != 0
        or receipt["job_stable_zero"] is not True
        or receipt["unexpected_inherited_fds"] != []
        or receipt["artifact_is_authorization"] is not False
        or receipt["execute_binding_enabled"] is not False
    ):
        raise ValueError("provider workload receipt completion boundary is invalid")
    request = receipt["workload_request"]
    if request != {
        "contract_version": "provider_sandbox_workload_request_v1",
        "command": "validate_provider_corpus",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }:
        raise ValueError("provider workload receipt request is invalid")
    if receipt["preflight"] != {
        "contract_version": "provider_sandbox_preflight_receipt_v1",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }:
        raise ValueError("provider preflight receipt cannot authorize a workload")
    expected_denials = {
        "builtin_parent": "filesystem_read_denied",
        "pathlib_gold": "filesystem_read_denied",
        "os_open_parent": "filesystem_read_denied",
        "relative_parent": "relative_path_denied",
        "case_alias": "path_alias_denied",
        "integer_fd": "integer_fd_denied",
        "relative_dir_fd_branch": "relative_path_denied",
        "subprocess_popen": "process_creation_denied",
        "os_system": "process_creation_denied",
        "winapi_create_process": "native_process_surface_denied",
        "os_chdir": "cwd_mutation_denied",
        "dynamic_import": "dynamic_import_denied",
        "ctypes_createfile_import": "dynamic_import_denied",
    }
    observed_denials = receipt["denied_controls"]
    if not isinstance(observed_denials, Mapping) or any(
        observed_denials.get(name) != code for name, code in expected_denials.items()
    ) or set(observed_denials) - {*expected_denials, "reparse_alias"} or (
        "reparse_alias" in observed_denials
        and observed_denials["reparse_alias"] != "path_alias_denied"
    ):
        raise ValueError("provider workload receipt negative controls are incomplete")
    result = receipt["workload_result"]
    if (
        not isinstance(result, Mapping)
        or set(result) != {
            "contract_version", "case_count", "screen_count",
            "regression_screen_count", "holdout_screen_count",
            "child_content_sha256", "artifact_is_authorization",
            "execute_binding_enabled",
        }
        or result.get("contract_version") != "provider_corpus_validation_result_v1"
        or result.get("case_count") != 120
        or result.get("screen_count") != 24
        or result.get("regression_screen_count") != 12
        or result.get("holdout_screen_count") != 12
        or result.get("artifact_is_authorization") is not False
        or result.get("execute_binding_enabled") is not False
    ):
        raise ValueError("provider workload receipt result is invalid")
    child_ref = receipt["child_ref"]
    if (
        not isinstance(child_ref, Mapping)
        or set(child_ref) != {"file_sha256", "content_sha256", "source_parent_ref"}
        or result.get("child_content_sha256") != child_ref.get("content_sha256")
    ):
        raise ValueError("provider workload receipt child binding is invalid")
    _require_sha(str(child_ref["file_sha256"]), "provider receipt child file SHA")
    _require_sha(str(child_ref["content_sha256"]), "provider receipt child content SHA")
    manifest_ref = receipt["manifest_ref"]
    if not isinstance(manifest_ref, Mapping) or set(manifest_ref) != {"file_sha256"}:
        raise ValueError("provider workload receipt manifest binding is invalid")
    _require_sha(str(manifest_ref["file_sha256"]), "provider receipt manifest SHA")
    launcher_identity = receipt["launcher_identity"]
    if (
        not isinstance(launcher_identity, Mapping)
        or set(launcher_identity) != {"pid", "create_time_100ns", "job_identity_sha256"}
        or launcher_identity["pid"] != receipt["launcher_process_id"]
        or not isinstance(launcher_identity["create_time_100ns"], int)
        or launcher_identity["create_time_100ns"] <= 0
    ):
        raise ValueError("provider workload launcher identity is invalid")
    _require_sha(
        str(launcher_identity["job_identity_sha256"]), "provider Job identity SHA"
    )

    def exact_entry(item: object, name: str) -> dict[str, object]:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256", "byte_length"}:
            raise ValueError(f"{name} must be an exact preload entry")
        entry = dict(item)
        if not isinstance(entry["path"], str) or not entry["path"]:
            raise ValueError(f"{name} path is invalid")
        _require_sha(str(entry["sha256"]), f"{name} SHA")
        if not isinstance(entry["byte_length"], int) or entry["byte_length"] <= 0:
            raise ValueError(f"{name} byte length is invalid")
        return entry

    projection = expected_projection
    if not isinstance(projection, Mapping) or set(projection) != {
        "manifest", "child", "runtime", "screenshot_refs"
    }:
        raise ValueError("provider sealed input projection is invalid")
    expected_preloaded: dict[str, dict[str, object]] = {
        "manifest": exact_entry(projection["manifest"], "manifest preload"),
    }
    projected_child = projection["child"]
    if not isinstance(projected_child, Mapping) or set(projected_child) != {
        "path", "sha256", "byte_length", "content_sha256", "source_parent_ref"
    }:
        raise ValueError("provider projected child ref is invalid")
    expected_preloaded["child"] = exact_entry(
        {key: projected_child[key] for key in ("path", "sha256", "byte_length")},
        "child preload",
    )
    if (
        projected_child["sha256"] != child_ref["file_sha256"]
        or projected_child["content_sha256"] != child_ref["content_sha256"]
        or projected_child["source_parent_ref"] != child_ref["source_parent_ref"]
        or projection["manifest"]["sha256"] != manifest_ref["file_sha256"]
    ):
        raise ValueError("provider sealed projection ref binding is invalid")
    runtime = projection["runtime"]
    if not isinstance(runtime, Mapping) or set(runtime) != {"code_refs", "profile_refs"}:
        raise ValueError("provider sealed runtime projection is invalid")
    code_refs = runtime["code_refs"]
    if not isinstance(code_refs, list) or len(code_refs) != len(_CODE_PATHS):
        raise ValueError("provider sealed code projection is invalid")
    for item, (role, path) in zip(code_refs, _CODE_PATHS.items(), strict=True):
        if not isinstance(item, Mapping) or set(item) != {
            "role", "path", "sha256", "byte_length"
        } or item["role"] != role or item["path"] != path.relative_to(
            _PROJECT_ROOT
        ).as_posix():
            raise ValueError("provider sealed code role/path is invalid")
        expected_preloaded[f"code:{role}"] = exact_entry(
            {key: item[key] for key in ("path", "sha256", "byte_length")},
            f"code preload {role}",
        )
    profile_refs = runtime["profile_refs"]
    if not isinstance(profile_refs, list) or len(profile_refs) != 1:
        raise ValueError("provider sealed profile projection is invalid")
    for item in profile_refs:
        if not isinstance(item, Mapping) or set(item) != {
            "role", "path", "sha256", "byte_length"
        } or not isinstance(item["role"], str) or not item["role"]:
            raise ValueError("provider sealed profile role is invalid")
        role = str(item["role"])
        if role != "estimand" or item["path"] != (
            "configs/benchmarks/portfolio_hybrid_v1_1_estimand.v2.json"
        ):
            raise ValueError("provider sealed profile identity is invalid")
        expected_preloaded[f"profile:{role}"] = exact_entry(
            {key: item[key] for key in ("path", "sha256", "byte_length")},
            f"profile preload {role}",
        )
    screenshots = projection["screenshot_refs"]
    if not isinstance(screenshots, list) or len(screenshots) != 24:
        raise ValueError("provider sealed screenshot projection is invalid")
    screenshot_partitions = {"regression": 0, "holdout": 0}
    screenshot_pattern = re.compile(
        r"^tests/fixtures/portfolio_hybrid_v1_1/corpus/"
        r"(regression|holdout)/case-[0-9]{3}\.png$"
    )
    for item in screenshots:
        entry = exact_entry(item, "screenshot preload")
        match = screenshot_pattern.fullmatch(str(entry["path"]))
        if match is None:
            raise ValueError("provider sealed screenshot path is invalid")
        screenshot_partitions[match.group(1)] += 1
        role = f"screenshot:{entry['path']}"
        if role in expected_preloaded:
            raise ValueError("provider sealed screenshot roles must be unique")
        expected_preloaded[role] = entry
    if screenshot_partitions != {"regression": 12, "holdout": 12}:
        raise ValueError("provider sealed screenshot projection must be 12+12")
    preloaded = receipt["preloaded_bytes_sha256_by_role"]
    if preloaded != expected_preloaded or len(expected_preloaded) != 30:
        raise ValueError("provider workload receipt preload map is not exact")
    receipt["receipt_sha256"] = declared
    return receipt


def _bind_provider_receipt_to_launcher(
    child_receipt: Mapping[str, object],
    *,
    observed_process_id: int,
    launcher_identity: Mapping[str, object],
    job_active_processes_after: int,
    expected_sealed_input_projection: Mapping[str, object],
    expected_projection_sha256: str,
) -> dict[str, object]:
    receipt = dict(child_receipt)
    if receipt.get("contract_version") != "provider_sandbox_workload_receipt_v1":
        raise ValueError("provider bootstrap did not return a workload receipt")
    if receipt.get("artifact_is_authorization") is not False or receipt.get(
        "execute_binding_enabled"
    ) is not False:
        raise ValueError("provider workload receipt attempted to authorize execution")
    provider_pid = receipt.get("provider_pid")
    if not isinstance(provider_pid, int) or provider_pid <= 0:
        raise ValueError("provider workload receipt PID is invalid")
    if provider_pid != observed_process_id:
        raise ValueError("provider workload receipt PID differs from the observed launcher")
    receipt["process_id"] = observed_process_id
    receipt["launcher_process_id"] = observed_process_id
    receipt["launcher_identity"] = dict(launcher_identity)
    receipt["parent_expected_projection_sha256"] = expected_projection_sha256
    receipt["job_active_processes_after"] = job_active_processes_after
    receipt["job_stable_zero"] = job_active_processes_after == 0
    if not receipt["job_stable_zero"]:
        raise RuntimeError("provider Job Object did not reach stable zero")
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return validate_provider_workload_receipt(
        receipt,
        expected_launcher_identity=launcher_identity,
        expected_sealed_input_projection=expected_sealed_input_projection,
        expected_projection_sha256=expected_projection_sha256,
    )


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
    expected_projection, expected_projection_sha = _parent_expected_sealed_projection(
        manifest_path=_canonical_existing(
            provider_manifest_path, kind="parent expected provider manifest"
        ),
        expected_manifest_sha256=expected_manifest_sha256,
        child_path=_canonical_existing(provider_child_path, kind="parent expected provider child"),
        expected_child_sha256=expected_child_sha256,
        manifest=manifest,
        child=child,
    )
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": []}
    job = _WindowsKillJob()
    process = None
    stdout = ""
    stderr = ""
    active_after: int | None = None
    launcher_identity: dict[str, object] | None = None
    try:
        process = subprocess.Popen(
            argv,
            executable=str(
                _canonical_existing(
                    Path(getattr(sys, "_base_executable", sys.executable)),
                    kind="provider base executable",
                )
            ),
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
        job.assign(int(process._handle))
        launcher_identity = job.observe_process(int(process._handle), process.pid)
        stdout, stderr = process.communicate(timeout=30)
    finally:
        try:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                finally:
                    try:
                        process.wait(timeout=10)
                    finally:
                        for stream in (process.stdout, process.stderr):
                            if stream is not None:
                                try:
                                    stream.close()
                                except OSError:
                                    pass
            active_after = job.active_processes()
        finally:
            job.close()
    if process is None:
        raise RuntimeError("provider process was not created")
    if process.returncode != 0:
        raise ValueError(f"provider bootstrap failed closed: {stderr.strip()}")
    try:
        receipt = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("provider bootstrap receipt is invalid") from exc
    if launcher_identity is None:
        raise RuntimeError("provider launcher identity was not observed")
    if active_after is None:
        raise RuntimeError("provider Job Object state was not observed")
    return _bind_provider_receipt_to_launcher(
        receipt,
        observed_process_id=process.pid,
        launcher_identity=launcher_identity,
        job_active_processes_after=active_after,
        expected_sealed_input_projection=expected_projection,
        expected_projection_sha256=expected_projection_sha,
    )


def _main() -> int:
    if tuple(sys.argv[1:2]) != ("--provider-bootstrap",):
        raise ValueError("provider sandbox has one closed bootstrap entrypoint")
    if sys.stdin.buffer.read(1) != b"":
        raise ValueError("provider bootstrap stdin must be empty")
    print(json.dumps(_run_provider_bootstrap(tuple(sys.argv[1:])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
