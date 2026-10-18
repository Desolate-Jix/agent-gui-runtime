from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Iterator


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_RESERVATION = ".immutable-reservation.json"
_SEAL = ".immutable-seal.json"


def resolved_review_path(value: Path) -> Path:
    resolved = Path(value).resolve()
    text = str(resolved)
    # 先解析真实目录，再统一 Win32 命名空间；并发建目录可让 pathlib 暂留扩展前缀。
    if os.name == "nt" and text.startswith("\\\\?\\"):
        plain = text[4:]
        if plain.startswith("UNC\\"):
            return Path("\\\\" + plain[4:])
        if len(plain) >= 3 and plain[0].isascii() and plain[0].isalpha() and plain[1:3] == ":\\":
            return Path(plain)
    return resolved


def validate_immutable_components(workflow_id: str, nodes: Any) -> None:
    seen = set()
    ids = [workflow_id]
    if not isinstance(nodes, list):
        raise ValueError("immutable workflow nodes must be an array")
    ids.extend(node.get("node_id") if isinstance(node, dict) else None for node in nodes)
    for index, value in enumerate(ids):
        if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value)
                or value.endswith(".") or Path(value).is_reserved()):
            raise ValueError("immutable workflow and node IDs must be safe explicit ASCII components (1-128 characters)")
        if index:
            if value.casefold() in seen:
                raise ValueError("immutable node IDs collide on a case-insensitive filesystem")
            seen.add(value.casefold())


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_links(path: Path, root: Path) -> None:
    # 不让链接、目录联接或重解析点把保存位置带出受控目录。
    current = path
    while current != root.parent:
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError(f"immutable review path must not contain links: {current}")
        if current == root:
            break
        current = current.parent
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("immutable review path escaped destination root")


@contextmanager
def review_writer_lock(root: Path) -> Iterator[None]:
    key = os.path.normcase(str(root.resolve()))
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / ".review-write.lock"
        _reject_links(lock_path, root)
        with lock_path.open("a+b") as handle:
            # 字节锁可覆盖 EOF 之外；初始化写入会与其他进程已持有的锁竞争。
            deadline = time.monotonic() + 15
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError("workflow review writer is busy; retry without changing workflow ID") from exc
                    time.sleep(0.025)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _owned_files(directory: Path) -> dict[str, str]:
    result = {}
    for path in directory.rglob("*"):
        _reject_links(path, directory)
        if path.is_file() and path != directory / _SEAL:
            result[path.relative_to(directory).as_posix()] = _digest(path)
    return result


def _input_dependencies(review: dict[str, Any], project_root: Path) -> dict[str, str | None]:
    paths: set[str] = set()
    for node in review.get("nodes", []):
        if not isinstance(node, dict):
            continue
        sources = node.get("source_paths")
        if isinstance(sources, list):
            paths.update(value for value in sources if isinstance(value, str) and value)
        evidence = node.get("evidence")
        if isinstance(evidence, dict):
            paths.update(value for key, value in evidence.items() if key.endswith("_path") and isinstance(value, str) and value)
    result = {}
    for value in paths:
        path = Path(value)
        path = (path if path.is_absolute() else project_root / path).resolve()
        result[str(path)] = _digest(path) if path.is_file() else None
    return result


def save_guarded_review(
    *, review: dict[str, Any], project_root: Path, destination_root: Path,
    workflow_dir: Path, create_only: bool, save: Callable[[], dict[str, Any]],
    registry_binding: Callable[[], dict[str, Any] | None], publish: Callable[[], None],
    verify_only: bool = False,
) -> dict[str, Any]:
    if verify_only:
        if not create_only:
            raise ValueError("read-only verification requires an immutable review")
        _reject_links(workflow_dir, destination_root)
        return _verify_existing_review(review, project_root, destination_root, workflow_dir)
    with review_writer_lock(destination_root):
        _reject_links(workflow_dir, destination_root)
        for path in (destination_root / "registry.json", destination_root / "registry.tmp"):
            _reject_links(path, destination_root)
        reservation = workflow_dir / _RESERVATION
        seal_path = workflow_dir / _SEAL
        if not create_only:
            if reservation.exists() or seal_path.exists():
                raise ValueError("immutable workflow review cannot be overwritten")
            if workflow_dir.exists():
                _owned_files(workflow_dir)
            return save()

        input_hash = hashlib.sha256(_json_bytes(review)).hexdigest()
        dependencies = _input_dependencies(review, project_root)
        if workflow_dir.exists():
            return _verify_existing_review(review, project_root, destination_root, workflow_dir)

        workflow_dir.mkdir(parents=True, exist_ok=False)
        reservation.write_bytes(_json_bytes({"input_sha256": input_hash}) + b"\n")
        result = save()
        if dependencies != _input_dependencies(review, project_root):
            raise ValueError("immutable workflow review dependency changed during save")
        binding = registry_binding()
        seal_path.write_bytes(_json_bytes({
            "contract_version": "immutable_workflow_review_v1", "input_sha256": input_hash,
            "dependencies": dependencies, "files": _owned_files(workflow_dir), "result": result,
            "registry_binding": binding,
        }) + b"\n")
        # 封存和依赖校验成功之前，旧编译器的 registry 入口始终不可见。
        publish()
        _verify_registry(destination_root, binding)
        return result


def _verify_existing_review(review: dict[str, Any], project_root: Path, destination_root: Path,
                            workflow_dir: Path) -> dict[str, Any]:
    # 只读入口复用封存校验，绝不建立目录、锁文件或补写缺失证据。
    try:
        seal_path = workflow_dir / _SEAL
        _reject_links(seal_path, workflow_dir)
        _reject_links(destination_root / "registry.json", destination_root)
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        if (seal.get("contract_version") != "immutable_workflow_review_v1"
                or seal.get("input_sha256") != hashlib.sha256(_json_bytes(review)).hexdigest()
                or seal.get("dependencies") != _input_dependencies(review, project_root)
                or seal.get("files") != _owned_files(workflow_dir)
                or not isinstance(seal.get("result"), dict)
                or seal["result"].get("path") != str((workflow_dir / "reviewed_workflow.json").resolve())):
            raise ValueError("immutable review input or persisted evidence changed")
        _verify_registry(destination_root, seal.get("registry_binding"))
        return seal["result"]
    except (OSError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("immutable workflow review is incomplete, different, or corrupt; use a new explicit revision") from exc


def _verify_registry(root: Path, binding: dict[str, Any] | None) -> None:
    if binding is None:
        return
    try:
        registry = json.loads((root / "registry.json").read_text(encoding="utf-8-sig"))
        workflow_id, identity_key = binding["workflow_id"], binding["identity_key"]
        if (registry["workflows"].get(workflow_id) != binding["record"]
                or workflow_id not in registry["applications"][identity_key]["workflow_ids"]):
            raise ValueError("immutable workflow registry lineage changed")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("immutable workflow registry lineage is missing or changed") from exc
