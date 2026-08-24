"""服务端拥有的 Hybrid 截图、血缘与 OCR/UIA 上下文封装。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from io import BytesIO
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, TypeAlias
from uuid import uuid4

from PIL import Image

from app.learn.hybrid.contracts import validate_capture_identity
from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    seal_immutable,
)
from app.learn.recognition.uei.contracts import validate_contract
from app.learn.recognition.uei.store import UEIObjectStore


HybridCaptureBundle: TypeAlias = dict[str, Any]

_UEI_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_BUNDLE_STORE_RELATIVE_PATH = Path("artifacts") / "hybrid-capture-store"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_PROVIDER_REF_FIELDS = frozenset(
    {"provider_result_ref", "ocr_result_ref", "uia_result_ref"}
)
_FORBIDDEN_CONTEXT_PATH_FIELDS = frozenset(
    {"image_path", "screenshot_path", "source_image_path", "artifact_path"}
)
_BUNDLE_FIELDS = frozenset(
    {
        "contract_version",
        "bundle_id",
        "capture_identity",
        "capture_lineage_ref",
        "artifact_ref",
        "context_ref",
        "context",
        "transform_refs",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "final_submit_forbidden",
        "real_action_requires_gate",
        "authorization_scope",
        "content_sha256",
    }
)
_CONTEXT_FIELDS = frozenset(
    {
        "contract_version",
        "context_id",
        "capture_lineage_ref",
        "workflow_revision",
        "window_binding",
        "ocr_uia_context",
        "transform_refs",
        "content_sha256",
    }
)


def seal_hybrid_capture_bundle(
    *,
    project_root: Path,
    image_path: Path,
    workflow_revision: object,
    window_binding: dict[str, object],
    ocr_uia_context: dict[str, object],
) -> HybridCaptureBundle:
    """读取一次服务端截图并封装不可变血缘和同源上下文。"""
    revision = _workflow_revision(workflow_revision)
    binding = _canonical_object(window_binding, name="window_binding", require_nonempty=True)
    context_input = _canonical_object(
        ocr_uia_context, name="ocr_uia_context", require_nonempty=True
    )
    _reject_untrusted_context_fields(context_input)

    capture = _seal_server_owned_capture(
        project_root=project_root,
        image_path=image_path,
    )
    root = capture["project_root"]
    store = capture["store"]
    identity = {
        "contract_version": "hybrid_capture_identity_v1",
        "capture_id": capture["capture_id"],
        "capture_lineage_ref": capture["capture_lineage_ref"],
        "capture_lineage": capture["capture_lineage"],
        "artifact_ref": capture["artifact_ref"],
        "artifact": capture["artifact"],
        "artifact_sha256": capture["artifact_sha256"],
        "screenshot_sha256": capture["artifact_sha256"],
        "image_size": capture["image_size"],
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": capture["captured_at"],
        "workflow_revision": revision,
    }
    identity = validate_capture_identity(identity)

    normalized_context, transform_refs = _seal_context_bindings(
        store=store,
        context=context_input,
        capture_lineage_ref=identity["capture_lineage_ref"],
        artifact_sha256=identity["artifact_sha256"],
        image_size=identity["image_size"],
    )
    context_base: dict[str, object] = {
        "contract_version": "hybrid_ocr_uia_context_v1",
        "context_id": "",
        "capture_lineage_ref": identity["capture_lineage_ref"],
        "workflow_revision": revision,
        "window_binding": binding,
        "ocr_uia_context": normalized_context,
        "transform_refs": transform_refs,
    }
    context_token = sha256(canonical_json_bytes(context_base)).hexdigest()
    context_base["context_id"] = f"hybrid-context/{context_token}"
    context = seal_immutable(context_base)
    context_ref = _persist_sealed_object(
        root=root,
        directory="contexts",
        value=context,
        id_field="context_id",
    )

    bundle_base: dict[str, object] = {
        "contract_version": "hybrid_capture_bundle_v1",
        "bundle_id": "",
        "capture_identity": identity,
        "capture_lineage_ref": identity["capture_lineage_ref"],
        "artifact_ref": identity["artifact_ref"],
        "context_ref": context_ref,
        "context": context,
        "transform_refs": transform_refs,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
    }
    bundle_token = sha256(canonical_json_bytes(bundle_base)).hexdigest()
    bundle_base["bundle_id"] = f"hybrid-capture/{bundle_token}"
    bundle = seal_immutable(bundle_base)
    bundle_ref = _persist_sealed_object(
        root=root,
        directory="objects",
        value=bundle,
        id_field="bundle_id",
    )
    _write_current_revision(
        root=root,
        revision=revision,
        capture_lineage_ref=identity["capture_lineage_ref"],
    )
    return {"bundle_ref": bundle_ref, **deepcopy(bundle)}


def load_and_verify_hybrid_capture_bundle(
    *, project_root: Path, bundle_ref: dict[str, str]
) -> dict[str, Any]:
    """加载并重新验证一个精确的不可变 Hybrid capture bundle。"""
    root = _project_root(project_root)
    reference = _immutable_ref(bundle_ref, name="bundle_ref")
    bundle = _load_sealed_object(
        root=root,
        directory="objects",
        reference=reference,
        id_field="bundle_id",
    )
    _closed_fields(bundle, _BUNDLE_FIELDS, name="hybrid capture bundle")
    if bundle.get("contract_version") != "hybrid_capture_bundle_v1":
        raise ValueError("hybrid capture bundle contract mismatch")
    _non_authorizing(bundle)

    identity = validate_capture_identity(_required_dict(bundle, "capture_identity"))
    lineage_ref = _immutable_ref(
        bundle.get("capture_lineage_ref"), name="capture_lineage_ref"
    )
    if lineage_ref != identity["capture_lineage_ref"]:
        raise ValueError("capture lineage conflict")
    artifact_ref = _immutable_ref(bundle.get("artifact_ref"), name="artifact_ref")
    if artifact_ref != identity["artifact_ref"]:
        raise ValueError("artifact ref conflict")

    store = UEIObjectStore(root=root / _UEI_STORE_RELATIVE_PATH)
    stored_artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    stored_lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    if canonical_json_bytes(stored_artifact) != canonical_json_bytes(identity["artifact"]):
        raise ValueError("artifact ref conflict")
    if canonical_json_bytes(stored_lineage) != canonical_json_bytes(identity["capture_lineage"]):
        raise ValueError("capture lineage conflict")

    context_ref = _immutable_ref(bundle.get("context_ref"), name="context_ref")
    context = _load_sealed_object(
        root=root,
        directory="contexts",
        reference=context_ref,
        id_field="context_id",
    )
    if canonical_json_bytes(context) != canonical_json_bytes(bundle.get("context")):
        raise ValueError("context ref conflict")
    _verify_context_envelope(
        store=store,
        context=context,
        capture_identity=identity,
        expected_transform_refs=bundle.get("transform_refs"),
    )
    current = _read_current_revision(root=root)
    if current["workflow_revision"] != identity["workflow_revision"]:
        raise ValueError("stale workflow revision")
    if current["capture_lineage_ref"] != identity["capture_lineage_ref"]:
        raise ValueError("stale capture lineage")
    return deepcopy(bundle)


def _seal_server_owned_capture(
    *,
    project_root: Path,
    image_path: Path,
    capture_id: str | None = None,
    captured_at: str | None = None,
    expected_image_sha256: str | None = None,
    expected_image_size: dict[str, int] | None = None,
) -> dict[str, Any]:
    root = _project_root(project_root)
    image, image_bytes = _read_server_owned_image(root=root, image_path=image_path)
    artifact_sha = sha256(image_bytes).hexdigest()
    image_size, media_type = _image_metadata(image_bytes)
    if expected_image_sha256 is not None and expected_image_sha256 != artifact_sha:
        raise ValueError("server-owned image SHA-256 mismatch")
    if expected_image_size is not None and expected_image_size != image_size:
        raise ValueError("server-owned image dimensions mismatch")
    timestamp = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    identifier = capture_id or f"capture/server-owned/{sha256((artifact_sha + timestamp).encode('utf-8')).hexdigest()}"
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("capture_id is required")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ValueError("captured_at is required")

    store = UEIObjectStore(root=root / _UEI_STORE_RELATIVE_PATH)
    artifact_ref = store.put(seal_immutable({
        "contract_version": "artifact_ref_v1",
        "artifact_id": f"artifact/server-owned/{artifact_sha}",
        "artifact_sha256": artifact_sha,
        "media_type": media_type,
        "byte_length": len(image_bytes),
        "restricted": True,
    }))
    artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    lineage_ref = store.put(seal_immutable({
        "contract_version": "capture_lineage_v1",
        "capture_id": identifier,
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "image_size": image_size,
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": timestamp,
    }))
    lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    return {
        "project_root": root,
        "image_path": image,
        "image_relative_path": image.relative_to(root).as_posix(),
        "image_bytes": image_bytes,
        "artifact_sha256": artifact_sha,
        "image_size": image_size,
        "media_type": media_type,
        "capture_id": identifier,
        "captured_at": timestamp,
        "store": store,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "capture_lineage_ref": lineage_ref,
        "capture_lineage": lineage,
    }


def _read_server_owned_image(*, root: Path, image_path: Path) -> tuple[Path, bytes]:
    if not isinstance(image_path, Path):
        raise ValueError("image_path must be a server-owned Path")
    candidate = image_path if image_path.is_absolute() else root / image_path
    _reject_reparse_ancestors(candidate.absolute())
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError("server-owned image must be inside project root") from error
    _reject_reparse_ancestors(resolved)
    before = os.stat(resolved, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("server-owned image must be a regular project file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    descriptor = os.open(str(resolved), flags)
    try:
        opened = os.fstat(descriptor)
        if not _same_file_state(before, opened):
            raise ValueError("server-owned image changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        image_bytes = b"".join(chunks)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after_path = os.stat(resolved, follow_symlinks=False)
    if not _same_file_state(opened, after_fd) or not _same_file_state(after_fd, after_path):
        raise ValueError("server-owned image changed during read")
    if len(image_bytes) != after_fd.st_size or not image_bytes:
        raise ValueError("server-owned image read was incomplete")
    return resolved, image_bytes


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
    )


def _image_metadata(image_bytes: bytes) -> tuple[dict[str, int], str]:
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            opened.verify()
        with Image.open(BytesIO(image_bytes)) as opened:
            width, height = int(opened.width), int(opened.height)
            image_format = str(opened.format or "").upper()
    except Exception as error:
        raise ValueError("server-owned image is not a valid supported image") from error
    media_types = {"PNG": "image/png", "JPEG": "image/jpeg"}
    if image_format not in media_types:
        raise ValueError("server-owned image format is not supported")
    return {"width": width, "height": height}, media_types[image_format]


def _seal_context_bindings(
    *,
    store: UEIObjectStore,
    context: dict[str, Any],
    capture_lineage_ref: dict[str, str],
    artifact_sha256: str,
    image_size: dict[str, int],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    normalized = deepcopy(context)
    _verify_nested_capture_and_provider_refs(
        store=store, value=normalized, capture_lineage_ref=capture_lineage_ref
    )
    raw_views = normalized.get("derived_views", [])
    if not isinstance(raw_views, list):
        raise ValueError("ocr_uia_context.derived_views must be a list")
    transform_refs: list[dict[str, str]] = []
    for index, raw_view in enumerate(raw_views):
        if not isinstance(raw_view, dict):
            raise ValueError(f"derived view {index} must be an object")
        transform = raw_view.get("coordinate_transform", raw_view.get("transform"))
        if not isinstance(transform, dict):
            raise ValueError(f"derived view {index} requires affine coordinate transform")
        validate_contract(transform, "affine_coordinate_transform_v1")
        if transform.get("content_sha256") != content_sha256(transform):
            raise ValueError("derived view transform content SHA mismatch")
        if transform.get("source_capture_artifact_sha256") != artifact_sha256:
            raise ValueError("transform source artifact SHA mismatch")
        target_sha = raw_view.get("target_artifact_sha256")
        if not isinstance(target_sha, str) or _HASH.fullmatch(target_sha) is None:
            raise ValueError("derived view target artifact SHA is required")
        if transform.get("target_capture_artifact_sha256") != target_sha:
            raise ValueError("transform target artifact SHA mismatch")
        if transform.get("source_size") != image_size:
            raise ValueError("transform source image dimensions mismatch")
        transform_ref = store.put(deepcopy(transform))
        declared_ref = raw_view.get("coordinate_transform_ref")
        if declared_ref is not None and _immutable_ref(
            declared_ref, name="coordinate_transform_ref"
        ) != transform_ref:
            raise ValueError("transform ref conflict")
        raw_view["coordinate_transform_ref"] = transform_ref
        transform_refs.append(transform_ref)
    return normalized, transform_refs


def _verify_nested_capture_and_provider_refs(
    *, store: UEIObjectStore, value: Any, capture_lineage_ref: dict[str, str]
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower().endswith("capture_lineage_ref"):
                if _immutable_ref(child, name=key) != capture_lineage_ref:
                    raise ValueError("cross-capture evidence")
            elif key in _PROVIDER_REF_FIELDS:
                result_ref = _immutable_ref(child, name=key)
                result = store.get(result_ref, contract_version="provider_safe_result_v1")
                if result.get("capture_lineage_ref") != capture_lineage_ref:
                    raise ValueError("cross-capture evidence")
            _verify_nested_capture_and_provider_refs(
                store=store, value=child, capture_lineage_ref=capture_lineage_ref
            )
    elif isinstance(value, list):
        for child in value:
            _verify_nested_capture_and_provider_refs(
                store=store, value=child, capture_lineage_ref=capture_lineage_ref
            )


def _verify_context_envelope(
    *,
    store: UEIObjectStore,
    context: dict[str, Any],
    capture_identity: dict[str, Any],
    expected_transform_refs: object,
) -> None:
    _closed_fields(context, _CONTEXT_FIELDS, name="hybrid OCR/UIA context")
    if context.get("contract_version") != "hybrid_ocr_uia_context_v1":
        raise ValueError("hybrid OCR/UIA context contract mismatch")
    if context.get("workflow_revision") != capture_identity["workflow_revision"]:
        raise ValueError("stale workflow revision")
    if context.get("capture_lineage_ref") != capture_identity["capture_lineage_ref"]:
        raise ValueError("capture lineage conflict")
    _canonical_object(context.get("window_binding"), name="window_binding", require_nonempty=True)
    nested = _canonical_object(
        context.get("ocr_uia_context"), name="ocr_uia_context", require_nonempty=True
    )
    _reject_untrusted_context_fields(nested)
    _verify_nested_capture_and_provider_refs(
        store=store,
        value=nested,
        capture_lineage_ref=capture_identity["capture_lineage_ref"],
    )
    refs = _transform_refs(context.get("transform_refs"))
    if refs != _transform_refs(expected_transform_refs):
        raise ValueError("transform ref conflict")
    raw_views = nested.get("derived_views", [])
    if not isinstance(raw_views, list) or len(raw_views) != len(refs):
        raise ValueError("derived view transform ref conflict")
    for index, (view, reference) in enumerate(zip(raw_views, refs, strict=True)):
        if not isinstance(view, dict) or view.get("coordinate_transform_ref") != reference:
            raise ValueError("derived view transform ref conflict")
        transform = store.get(reference, contract_version="affine_coordinate_transform_v1")
        embedded = view.get("coordinate_transform", view.get("transform"))
        if canonical_json_bytes(transform) != canonical_json_bytes(embedded):
            raise ValueError("derived view transform ref conflict")
        target_sha = view.get("target_artifact_sha256")
        if transform.get("source_capture_artifact_sha256") != capture_identity["artifact_sha256"]:
            raise ValueError("transform source artifact SHA mismatch")
        if transform.get("target_capture_artifact_sha256") != target_sha:
            raise ValueError("transform target artifact SHA mismatch")
        if transform.get("source_size") != capture_identity["image_size"]:
            raise ValueError("transform source image dimensions mismatch")


def _reject_untrusted_context_fields(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_CONTEXT_PATH_FIELDS:
                raise ValueError("raw client path is not accepted in OCR/UIA context")
            if normalized.endswith("_payload") and any(
                provider in normalized for provider in ("provider", "omni", "qwen")
            ):
                raise ValueError("raw provider payload is not accepted")
            if normalized in {"provider_result", "omni_result", "qwen_result"}:
                raise ValueError("raw provider payload is not accepted")
            _reject_untrusted_context_fields(child)
    elif isinstance(value, list):
        for child in value:
            _reject_untrusted_context_fields(child)


def _persist_sealed_object(
    *, root: Path, directory: str, value: dict[str, object], id_field: str
) -> dict[str, str]:
    declared = value.get("content_sha256")
    identifier = value.get(id_field)
    if not isinstance(declared, str) or declared != content_sha256(value):
        raise ValueError("sealed object content SHA mismatch")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("sealed object ID is required")
    store_root = _bundle_store_root(root)
    target_dir = store_root / directory
    _ensure_private_directory(target_dir)
    target = target_dir / f"{declared}.json"
    if target.parent != target_dir or _is_reparse(target):
        raise ValueError("hybrid capture store path escape")
    canonical = canonical_json_bytes(value)
    if target.exists():
        if target.read_bytes() != canonical:
            raise ValueError("hybrid capture digest conflict")
    else:
        temporary = target_dir / f".{declared}.{uuid4().hex}.tmp"
        descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(canonical)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(str(temporary), str(target))
            except FileExistsError:
                if target.read_bytes() != canonical:
                    raise ValueError("hybrid capture digest conflict")
        finally:
            temporary.unlink(missing_ok=True)
    return {"id": identifier, "content_sha256": declared}


def _load_sealed_object(
    *, root: Path, directory: str, reference: dict[str, str], id_field: str
) -> dict[str, Any]:
    target_dir = _bundle_store_root(root) / directory
    _ensure_private_directory(target_dir)
    target = target_dir / f"{reference['content_sha256']}.json"
    if target.parent != target_dir or _is_reparse(target):
        raise ValueError("hybrid capture store path escape")
    try:
        raw = target.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("hybrid capture object is unreadable") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError("hybrid capture object is not canonical")
    if value.get("content_sha256") != reference["content_sha256"]:
        raise ValueError("hybrid capture object content SHA mismatch")
    if content_sha256(value) != reference["content_sha256"]:
        raise ValueError("hybrid capture object content SHA mismatch")
    if value.get(id_field) != reference["id"]:
        raise ValueError("hybrid capture object ID mismatch")
    return value


def _write_current_revision(
    *, root: Path, revision: str, capture_lineage_ref: dict[str, str]
) -> None:
    store_root = _bundle_store_root(root)
    _ensure_private_directory(store_root)
    target = store_root / "current-revision.json"
    if _is_reparse(target):
        raise ValueError("hybrid capture revision path is a reparse point")
    payload = canonical_json_bytes({
        "contract_version": "hybrid_capture_current_revision_v1",
        "workflow_revision": revision,
        "capture_lineage_ref": capture_lineage_ref,
    })
    temporary = store_root / f".current-revision.{uuid4().hex}.tmp"
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _read_current_revision(*, root: Path) -> dict[str, object]:
    target = _bundle_store_root(root) / "current-revision.json"
    if _is_reparse(target):
        raise ValueError("hybrid capture revision path is a reparse point")
    try:
        raw = target.read_bytes()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("hybrid capture current revision is unavailable") from error
    if canonical_json_bytes(parsed) != raw or not isinstance(parsed, dict):
        raise ValueError("hybrid capture current revision is not canonical")
    if set(parsed) != {
        "contract_version",
        "workflow_revision",
        "capture_lineage_ref",
    }:
        raise ValueError("hybrid capture current revision is not closed")
    if parsed.get("contract_version") != "hybrid_capture_current_revision_v1":
        raise ValueError("hybrid capture current revision contract mismatch")
    return {
        "workflow_revision": _workflow_revision(parsed.get("workflow_revision")),
        "capture_lineage_ref": _immutable_ref(
            parsed.get("capture_lineage_ref"), name="current capture_lineage_ref"
        ),
    }


def _bundle_store_root(root: Path) -> Path:
    path = root / _BUNDLE_STORE_RELATIVE_PATH
    _reject_reparse_ancestors(path)
    return path


def _ensure_private_directory(path: Path) -> None:
    _reject_reparse_ancestors(path)
    path.mkdir(parents=True, exist_ok=True)
    _reject_reparse_ancestors(path)
    if not path.is_dir():
        raise ValueError("hybrid capture store is not a directory")


def _project_root(project_root: Path) -> Path:
    if not isinstance(project_root, Path):
        raise ValueError("project_root must be a Path")
    _reject_reparse_ancestors(project_root.absolute())
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise ValueError("project_root is unavailable") from error
    _reject_reparse_ancestors(root)
    if not root.is_dir():
        raise ValueError("project_root must be a directory")
    return root


def _reject_reparse_ancestors(path: Path) -> None:
    current = path
    while True:
        try:
            status = os.lstat(current)
        except FileNotFoundError:
            current = current.parent
            continue
        except OSError as error:
            raise ValueError("server-owned path is unavailable") from error
        if stat.S_ISLNK(status.st_mode) or bool(
            getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("server-owned path contains a reparse point")
        if current == current.parent:
            return
        current = current.parent


def _is_reparse(path: Path) -> bool:
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ValueError("server-owned path is unavailable") from error
    return stat.S_ISLNK(status.st_mode) or bool(
        getattr(status, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _workflow_revision(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("workflow_revision must be a string or integer")
    revision = str(value).strip()
    if not revision:
        raise ValueError("workflow_revision is required")
    return revision


def _immutable_ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"id", "content_sha256"}:
        raise ValueError(f"{name} must be an exact immutable ref")
    identifier = value.get("id")
    digest = value.get("content_sha256")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError(f"{name}.id is required")
    if not isinstance(digest, str) or _HASH.fullmatch(digest) is None:
        raise ValueError(f"{name}.content_sha256 is invalid")
    return {"id": identifier, "content_sha256": digest}


def _canonical_object(
    value: object, *, name: str, require_nonempty: bool = False
) -> dict[str, Any]:
    if not isinstance(value, dict) or (require_nonempty and not value):
        raise ValueError(f"{name} must be a non-empty object")
    candidate = deepcopy(value)
    try:
        canonical_json_bytes(candidate)
    except ValueError as error:
        raise ValueError(f"{name} must be canonical JSON") from error
    return candidate


def _required_dict(value: dict[str, Any], field: str) -> dict[str, Any]:
    child = value.get(field)
    if not isinstance(child, dict):
        raise ValueError(f"{field} must be an object")
    return deepcopy(child)


def _closed_fields(value: dict[str, Any], fields: frozenset[str], *, name: str) -> None:
    if set(value) != set(fields):
        raise ValueError(f"{name} is not closed")


def _transform_refs(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("transform_refs must be a list")
    return [_immutable_ref(child, name="transform_ref") for child in value]


def _non_authorizing(value: dict[str, Any]) -> None:
    required = {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
    }
    if any(value.get(key) != expected for key, expected in required.items()):
        raise ValueError("hybrid capture bundle violates non-authorizing invariant")
