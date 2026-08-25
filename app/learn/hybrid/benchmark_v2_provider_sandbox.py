"""Provider-process path projection and irreversible file-open policy."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_ROOT = (
    _PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "portfolio_hybrid_v1_1"
).resolve()
_FORBIDDEN_FIXTURE_NAMES = {
    "benchmark-v2-manifest.template.json",
    "benchmark-v2-private-manifest.json",
    "corpus-manifest.v1.json",
    "gold.v1.json",
    "manifest.template.json",
    "reviewed_hybrid_source.json",
}


def _resolved(path: Path) -> Path:
    return Path(path).resolve(strict=False)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalized_text(value: object) -> str:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("provider process projection must be UTF-8") from exc
    return str(value)


def validate_provider_process_projection(
    *,
    argv: tuple[str, ...],
    env: Mapping[str, str],
    cwd: Path,
    stdin: bytes,
    forbidden_roots: tuple[Path, ...],
) -> None:
    roots = tuple(_resolved(path) for path in forbidden_roots)
    if not roots:
        raise ValueError("provider projection requires at least one private root")
    if any(argument == "--purpose" or argument.startswith("--purpose=") for argument in argv):
        raise ValueError("purpose labels are not a process-isolation boundary")
    if not argv:
        raise ValueError("provider process projection requires an executable")
    projected = [*argv[1:], *env.keys(), *env.values(), _normalized_text(stdin)]
    normalized_roots = [str(root).casefold().replace("\\", "/") for root in roots]
    for item in projected:
        normalized = _normalized_text(item).casefold().replace("\\", "/")
        if any(root in normalized for root in normalized_roots):
            raise ValueError("provider process projection exposes a private root")
    resolved_cwd = _resolved(cwd)
    if any(
        _inside(resolved_cwd, root)
        or _inside(root, resolved_cwd)
        for root in roots
    ):
        raise ValueError("provider cwd exposes a private root")


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


def install_provider_file_policy(
    *,
    read_files: tuple[Path, ...],
    read_roots: tuple[Path, ...],
    write_roots: tuple[Path, ...],
) -> object:
    exact_reads = frozenset(_resolved(path) for path in read_files)
    resolved_read_roots = tuple(_resolved(path) for path in read_roots)
    resolved_write_roots = tuple(_resolved(path) for path in write_roots)
    if not exact_reads:
        raise ValueError("provider file policy requires exact sealed read files")
    if not resolved_write_roots:
        raise ValueError("provider file policy requires output roots")
    if any(_inside(_FIXTURE_ROOT, root) for root in resolved_read_roots):
        raise ValueError("fixture reads must be exact files, not a broad root")
    if any(
        _inside(root, _PROJECT_ROOT) or _inside(_PROJECT_ROOT, root)
        for root in resolved_read_roots
    ):
        raise ValueError("project code and profiles must be exact sealed read files")
    for path in exact_reads:
        lowered_name = path.name.casefold()
        if any(token in lowered_name for token in ("gold", "private", "scorer")):
            raise ValueError("provider file policy cannot allow a private fixture or scorer")
        if not _inside(path, _FIXTURE_ROOT):
            continue
        relative = path.relative_to(_FIXTURE_ROOT)
        if (
            lowered_name in _FORBIDDEN_FIXTURE_NAMES
            or "gold" in {part.casefold() for part in relative.parts}
        ):
            raise ValueError("provider file policy cannot allow a private fixture or scorer")
    if any(_inside(root, _FIXTURE_ROOT) or _inside(_FIXTURE_ROOT, root) for root in resolved_write_roots):
        raise ValueError("provider process cannot write inside the fixture root")
    policy = ProviderFilePolicy(
        read_files=exact_reads,
        read_roots=resolved_read_roots,
        write_roots=resolved_write_roots,
    )

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event != "open" or not args:
            return
        raw_path = args[0]
        if isinstance(raw_path, int):
            return
        try:
            path = _resolved(Path(os.fsdecode(raw_path)))
        except (TypeError, ValueError, OSError) as exc:
            raise PermissionError("provider file policy rejected an invalid path") from exc
        writing = _is_write(
            args[1] if len(args) > 1 else None,
            args[2] if len(args) > 2 else None,
        )
        if writing:
            if any(_inside(path, root) for root in policy.write_roots):
                return
            raise PermissionError(f"provider write denied: {path}")
        if path in policy.read_files:
            return
        if _inside(path, _FIXTURE_ROOT):
            raise PermissionError(f"provider fixture read denied: {path}")
        if any(_inside(path, root) for root in policy.read_roots):
            return
        raise PermissionError(f"provider read denied: {path}")

    sys.addaudithook(audit)
    return policy
