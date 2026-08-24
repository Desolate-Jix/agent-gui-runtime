"""服务端截图与 Hybrid OCR/UIA 证据的不可变 UEI 封装。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import math
import os
from pathlib import Path
import stat
from typing import Any, TypeAlias

from PIL import Image

from app.learn.hybrid.contracts import validate_capture_identity
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


HybridCaptureBundle: TypeAlias = dict[str, Any]

_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_SCREENSHOT_RELATIVE_PATH = Path("artifacts") / "screenshots"
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}
_AUTHORITY_ALIASES = frozenset(
    {
        "action_authorized",
        "approved_to_click",
        "approved_to_execute",
        "click_authorized",
        "execute",
        "final_submit",
        "submit_authorized",
    }
)
_WINDOW_FIELDS = frozenset({"window_binding_id", "process_id", "process_name", "rect"})
_RECT_FIELDS = frozenset({"left", "top", "right", "bottom"})
_SOURCE_FIELDS = frozenset(
    {
        "source_kind",
        "capture_lineage_ref",
        "run_id",
        "workflow_revision",
        "window_binding",
        "evidence_contract_version",
        "evidence_ref",
    }
)
_DERIVED_INPUT_FIELDS = frozenset(
    {"target_capture_lineage_ref", "target_artifact_ref", "coordinate_transform_ref"}
)
_DERIVED_STORED_FIELDS = frozenset(
    {
        "target_capture_lineage_ref",
        "target_capture_lineage",
        "target_artifact_ref",
        "target_artifact",
        "coordinate_transform_ref",
        "coordinate_transform",
    }
)


@dataclass(frozen=True, slots=True)
class _ServerCaptureEnvelope:
    """进程内传递的不可变截图事实；不能来自面板 JSON。"""

    project_root: Path
    image_path: Path
    image_relative_path: str
    image_bytes: bytes
    artifact_sha256: str
    image_width: int
    image_height: int
    media_type: str
    capture_id: str
    captured_at: str
    run_id: str
    workflow_revision: int
    window_binding_sha256: str
    artifact_ref_id: str
    artifact_ref_sha256: str
    lineage_ref_id: str
    lineage_ref_sha256: str


class HybridCaptureIdentity(dict[str, Any]):
    """兼容既有字典契约，同时私有保存一次读取所得的服务端封套。"""

    __slots__ = ("_capture_envelope",)

    def __init__(self, value: dict[str, Any], envelope: _ServerCaptureEnvelope) -> None:
        super().__init__(value)
        self._capture_envelope = envelope

    @property
    def capture_envelope(self) -> object:
        return self._capture_envelope


def seal_hybrid_capture_identity(
    *,
    project_root: Path,
    image_path: Path,
    run_id: str,
    workflow_revision: int,
    window_binding: dict[str, object],
    captured_at: str | None = None,
) -> HybridCaptureIdentity:
    """为 ScreenshotService 已生成的文件建立唯一 UEI capture lineage。"""
    root = _project_root(project_root)
    normalized_run_id = _run_id(run_id)
    revision = _workflow_revision(workflow_revision)
    binding = _window_binding(window_binding)
    image, image_bytes = _read_server_owned_image(root=root, image_path=image_path)
    artifact_sha, image_size, media_type = _image_facts(image_bytes)
    timestamp = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    capture_id = _expected_capture_id(
        run_id=normalized_run_id,
        workflow_revision=revision,
        window_binding=binding,
        artifact_sha256=artifact_sha,
        captured_at=timestamp,
    )
    store = _store(root)
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
        "capture_id": capture_id,
        "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha,
        "image_size": image_size,
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": timestamp,
    }))
    lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    identity = _capture_identity(
        lineage=lineage,
        lineage_ref=lineage_ref,
        artifact=artifact,
        artifact_ref=artifact_ref,
        workflow_revision=revision,
    )
    envelope = _ServerCaptureEnvelope(
        project_root=root,
        image_path=image,
        image_relative_path=image.relative_to(root).as_posix(),
        image_bytes=image_bytes,
        artifact_sha256=artifact_sha,
        image_width=image_size["width"],
        image_height=image_size["height"],
        media_type=media_type,
        capture_id=capture_id,
        captured_at=timestamp,
        run_id=normalized_run_id,
        workflow_revision=revision,
        window_binding_sha256=sha256(canonical_json_bytes(binding)).hexdigest(),
        artifact_ref_id=artifact_ref["id"],
        artifact_ref_sha256=artifact_ref["content_sha256"],
        lineage_ref_id=lineage_ref["id"],
        lineage_ref_sha256=lineage_ref["content_sha256"],
    )
    return HybridCaptureIdentity(identity, envelope)


def seal_hybrid_capture_bundle(
    *,
    project_root: Path,
    image_path: Path,
    run_id: str,
    workflow_revision: int,
    window_binding: dict[str, object],
    ocr_uia_context: dict[str, object],
    capture_envelope: object,
) -> HybridCaptureBundle:
    """验证同源 OCR/UIA 证据并通过 UEIObjectStore 持久化上下文与 bundle。"""
    root = _project_root(project_root)
    normalized_run_id = _run_id(run_id)
    revision = _workflow_revision(workflow_revision)
    binding = _window_binding(window_binding)
    _reject_authority_aliases(ocr_uia_context)
    context_input = _exact_object(
        ocr_uia_context,
        fields={"capture_lineage_ref", "sources", "derived_views"},
        name="OCR/UIA context",
    )
    lineage_ref = _immutable_ref(
        context_input["capture_lineage_ref"], name="capture_lineage_ref"
    )
    store = _store(root)
    capture = _resolve_capture_envelope(
        root=root,
        image_path=image_path,
        capture_lineage_ref=lineage_ref,
        capture_envelope=capture_envelope,
    )
    lineage = capture["capture_lineage"]
    artifact_ref = capture["artifact_ref"]
    artifact = capture["artifact"]
    envelope = capture["_capture_envelope"]
    if (
        envelope.run_id != normalized_run_id
        or envelope.workflow_revision != revision
        or envelope.window_binding_sha256
        != sha256(canonical_json_bytes(binding)).hexdigest()
    ):
        raise ValueError("capture identity mismatch")
    _require_capture_identity_binding(
        lineage=lineage,
        artifact=artifact,
        run_id=normalized_run_id,
        workflow_revision=revision,
        window_binding=binding,
    )
    identity = _capture_identity(
        lineage=lineage,
        lineage_ref=lineage_ref,
        artifact=artifact,
        artifact_ref=artifact_ref,
        workflow_revision=revision,
    )

    sources = _verified_sources(
        store=store,
        value=context_input["sources"],
        capture_lineage_ref=lineage_ref,
        run_id=normalized_run_id,
        workflow_revision=revision,
        window_binding=binding,
    )
    derived_views = _verified_derived_views(
        store=store,
        value=context_input["derived_views"],
        source_lineage=lineage,
        source_artifact=artifact,
    )
    context_base: dict[str, object] = {
        "contract_version": "hybrid_capture_context_v1",
        "context_id": "",
        "run_id": normalized_run_id,
        "workflow_revision": revision,
        "capture_lineage_ref": lineage_ref,
        "window_binding": binding,
        "sources": sources,
        "derived_views": derived_views,
        **_NON_AUTHORIZING,
    }
    context_base["context_id"] = "hybrid-context/" + sha256(
        canonical_json_bytes(context_base)
    ).hexdigest()
    context = seal_immutable(context_base)
    context_ref = store.put(context)

    bundle_base: dict[str, object] = {
        "contract_version": "hybrid_capture_bundle_v1",
        "bundle_id": "",
        "run_id": normalized_run_id,
        "workflow_revision": revision,
        "capture_lineage_ref": lineage_ref,
        "artifact_ref": artifact_ref,
        "context_ref": context_ref,
        **_NON_AUTHORIZING,
    }
    bundle_base["bundle_id"] = "hybrid-capture/" + sha256(
        canonical_json_bytes(bundle_base)
    ).hexdigest()
    bundle = seal_immutable(bundle_base)
    bundle_ref = store.put(bundle)
    return {
        **deepcopy(bundle),
        "bundle_ref": bundle_ref,
        "capture_identity": identity,
        "context": context,
    }


def load_and_verify_hybrid_capture_bundle(
    *,
    project_root: Path,
    bundle_ref: dict[str, str],
    expected_run_id: str,
    expected_workflow_revision: int,
) -> dict[str, Any]:
    """按权威 run/revision 重新解析 UEI bundle 及全部父证据。"""
    root = _project_root(project_root)
    run_id = _run_id(expected_run_id)
    revision = _workflow_revision(expected_workflow_revision)
    store = _store(root)
    reference = _immutable_ref(bundle_ref, name="bundle_ref")
    bundle = store.get(reference, contract_version="hybrid_capture_bundle_v1")
    _require_non_authorizing(bundle, name="hybrid capture bundle")
    if bundle["run_id"] != run_id:
        raise ValueError("cross-run bundle")
    if bundle["workflow_revision"] != revision:
        raise ValueError("stale workflow revision")

    lineage_ref = _immutable_ref(bundle["capture_lineage_ref"], name="capture_lineage_ref")
    artifact_ref = _immutable_ref(bundle["artifact_ref"], name="artifact_ref")
    lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    if lineage["artifact_ref"] != artifact_ref:
        raise ValueError("capture lineage artifact conflict")
    context_ref = _immutable_ref(bundle["context_ref"], name="context_ref")
    context = store.get(context_ref, contract_version="hybrid_capture_context_v1")
    _require_non_authorizing(context, name="hybrid capture context")
    if (
        context["run_id"] != run_id
        or context["workflow_revision"] != revision
        or context["capture_lineage_ref"] != lineage_ref
    ):
        raise ValueError("capture context freshness mismatch")
    binding = _window_binding(context["window_binding"])
    _require_capture_identity_binding(
        lineage=lineage,
        artifact=artifact,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=binding,
    )
    _verified_sources(
        store=store,
        value=context["sources"],
        capture_lineage_ref=lineage_ref,
        run_id=run_id,
        workflow_revision=revision,
        window_binding=binding,
    )
    _verified_derived_views(
        store=store,
        value=context["derived_views"],
        source_lineage=lineage,
        source_artifact=artifact,
    )
    identity = _capture_identity(
        lineage=lineage,
        lineage_ref=lineage_ref,
        artifact=artifact,
        artifact_ref=artifact_ref,
        workflow_revision=revision,
    )
    return {**deepcopy(bundle), "capture_identity": identity, "context": context}


def resolve_server_owned_capture(
    *, project_root: Path, image_path: Path, capture_lineage_ref: dict[str, str],
    capture_envelope: object,
) -> dict[str, Any]:
    """为内置 provider 解析已封装 capture，禁止创建第二条 lineage。"""
    root = _project_root(project_root)
    return _resolve_capture_envelope(
        root=root,
        image_path=image_path,
        capture_lineage_ref=capture_lineage_ref,
        capture_envelope=capture_envelope,
    )


def read_project_owned_image(*, project_root: Path, image_path: Path) -> dict[str, Any]:
    """兼容旧 OCR：以单一描述符验证项目内服务端文件。"""
    root = _project_root(project_root)
    image, image_bytes = _read_verified_image(
        root=root,
        image_path=image_path,
        allowed_root=root,
        boundary_name="project root",
    )
    artifact_sha, image_size, media_type = _image_facts(image_bytes)
    return {
        "project_root": root,
        "image_path": image,
        "image_relative_path": image.relative_to(root).as_posix(),
        "image_bytes": image_bytes,
        "artifact_sha256": artifact_sha,
        "image_size": image_size,
        "media_type": media_type,
    }


def _resolve_capture_envelope(
    *, root: Path, image_path: Path, capture_lineage_ref: dict[str, str],
    capture_envelope: object,
) -> dict[str, Any]:
    if type(capture_envelope) is not _ServerCaptureEnvelope:
        raise ValueError("capture envelope must be server-owned")
    envelope = capture_envelope
    if envelope.project_root != root or _lexical_path(root, image_path) != envelope.image_path:
        raise ValueError("capture envelope path mismatch")
    lineage_ref = _immutable_ref(capture_lineage_ref, name="capture_lineage_ref")
    if lineage_ref != {
        "id": envelope.lineage_ref_id,
        "content_sha256": envelope.lineage_ref_sha256,
    }:
        raise ValueError("capture envelope lineage mismatch")
    store = _store(root)
    lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    artifact_ref = _immutable_ref(lineage["artifact_ref"], name="artifact_ref")
    if artifact_ref != {
        "id": envelope.artifact_ref_id,
        "content_sha256": envelope.artifact_ref_sha256,
    }:
        raise ValueError("capture envelope artifact mismatch")
    artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    artifact_sha, image_size, media_type = _image_facts(envelope.image_bytes)
    if (
        artifact_sha != envelope.artifact_sha256
        or image_size != {"width": envelope.image_width, "height": envelope.image_height}
        or media_type != envelope.media_type
        or lineage["capture_id"] != envelope.capture_id
        or lineage["captured_at"] != envelope.captured_at
        or lineage["artifact_sha256"] != artifact_sha
        or lineage["image_size"] != image_size
        or artifact["artifact_sha256"] != artifact_sha
        or artifact["byte_length"] != len(envelope.image_bytes)
        or artifact["media_type"] != media_type
    ):
        raise ValueError("server capture does not match sealed capture envelope")
    return {
        "project_root": root,
        "image_path": envelope.image_path,
        "image_relative_path": envelope.image_relative_path,
        "image_bytes": envelope.image_bytes,
        "artifact_sha256": artifact_sha,
        "image_size": image_size,
        "store": store,
        "capture_id": lineage["capture_id"],
        "captured_at": lineage["captured_at"],
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "capture_lineage_ref": lineage_ref,
        "capture_lineage": lineage,
        "_capture_envelope": envelope,
    }


def _expected_capture_id(
    *, run_id: str, workflow_revision: int, window_binding: dict[str, Any],
    artifact_sha256: str, captured_at: str,
) -> str:
    material = {
        "run_id": run_id,
        "workflow_revision": workflow_revision,
        "window_binding": window_binding,
        "artifact_sha256": artifact_sha256,
        "captured_at": captured_at,
    }
    return "capture/server-owned/" + sha256(canonical_json_bytes(material)).hexdigest()


def _require_capture_identity_binding(
    *, lineage: dict[str, Any], artifact: dict[str, Any], run_id: str,
    workflow_revision: int, window_binding: dict[str, Any],
) -> None:
    expected = _expected_capture_id(
        run_id=run_id,
        workflow_revision=workflow_revision,
        window_binding=window_binding,
        artifact_sha256=artifact["artifact_sha256"],
        captured_at=lineage["captured_at"],
    )
    if lineage["artifact_sha256"] != artifact["artifact_sha256"] or lineage["capture_id"] != expected:
        raise ValueError("capture identity mismatch")


def _lexical_path(root: Path, image_path: Path) -> Path:
    if not isinstance(image_path, Path):
        raise ValueError("image_path must be a server-owned Path")
    candidate = image_path if image_path.is_absolute() else root / image_path
    normalized = os.path.normcase(os.path.abspath(os.fspath(candidate)))
    return Path(normalized)


def _capture_identity(
    *, lineage: dict[str, Any], lineage_ref: dict[str, str], artifact: dict[str, Any],
    artifact_ref: dict[str, str], workflow_revision: int,
) -> dict[str, Any]:
    identity = {
        "contract_version": "hybrid_capture_identity_v1",
        "capture_id": lineage["capture_id"],
        "capture_lineage_ref": lineage_ref,
        "capture_lineage": lineage,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "artifact_sha256": artifact["artifact_sha256"],
        "screenshot_sha256": artifact["artifact_sha256"],
        "image_size": lineage["image_size"],
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": lineage["captured_at"],
        "workflow_revision": str(workflow_revision),
    }
    return validate_capture_identity(identity)


def _verified_sources(
    *, store: UEIObjectStore, value: object, capture_lineage_ref: dict[str, str],
    run_id: str, workflow_revision: int, window_binding: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("OCR/UIA context must contain exactly two sources")
    normalized: list[dict[str, Any]] = []
    kinds: list[str] = []
    for raw in value:
        source = _exact_object(raw, fields=_SOURCE_FIELDS, name="OCR/UIA source")
        _reject_authority_aliases(source)
        kind = source["source_kind"]
        if kind not in {"ocr", "uia"}:
            raise ValueError("OCR/UIA source kind is invalid")
        if (
            _immutable_ref(source["capture_lineage_ref"], name="source capture_lineage_ref")
            != capture_lineage_ref
            or source["run_id"] != run_id
            or source["workflow_revision"] != workflow_revision
            or _window_binding(source["window_binding"]) != window_binding
        ):
            raise ValueError("cross-capture evidence provenance")
        if source["evidence_contract_version"] != "provider_safe_result_v1":
            raise ValueError("unverified OCR/UIA evidence contract")
        evidence_ref = _immutable_ref(source["evidence_ref"], name="evidence_ref")
        evidence = store.get(evidence_ref, contract_version="provider_safe_result_v1")
        if (
            evidence["capture_lineage_ref"] != capture_lineage_ref
            or evidence["status"] != "success"
            or evidence["review_only"] is not True
        ):
            raise ValueError("cross-capture evidence")
        request = store.get(evidence["request_ref"], contract_version="screen_parse_request_v1")
        if request["capture_lineage_ref"] != capture_lineage_ref:
            raise ValueError("cross-capture evidence request")
        registration = store.get(
            evidence["registration_ref"], contract_version="trusted_provider_registration_v1"
        )
        manifest = store.get(evidence["manifest_ref"], contract_version="provider_manifest_v1")
        requested_profiles = request.get("requested_profiles")
        manifest_profiles = manifest.get("profiles")
        selected_manifest = next(
            (
                profile
                for profile in manifest_profiles
                if isinstance(profile, dict) and profile.get("profile_id") == evidence["profile_id"]
            ),
            None,
        ) if isinstance(manifest_profiles, list) else None
        expected_output_kind = "text" if kind == "ocr" else "element"
        if (
            registration["provider_id"] != evidence["provider_id"]
            or registration["enabled"] is not True
            or evidence["profile_id"] not in registration["profile_ids"]
            or manifest["provider_id"] != evidence["provider_id"]
            or evidence["requested_provider_id"] != evidence["provider_id"]
            or evidence["requested_profile_id"] != evidence["profile_id"]
            or not isinstance(requested_profiles, list)
            or not any(
                isinstance(profile, dict)
                and profile.get("provider_id") == evidence["provider_id"]
                and profile.get("profile_id") == evidence["profile_id"]
                for profile in requested_profiles
            )
            or not isinstance(selected_manifest, dict)
            or expected_output_kind not in selected_manifest.get("declared_output_kinds", [])
        ):
            raise ValueError("OCR/UIA provider provenance mismatch")
        normalized.append(deepcopy(source))
        kinds.append(kind)
    if set(kinds) != {"ocr", "uia"} or len(set(kinds)) != 2:
        raise ValueError("OCR/UIA context requires one OCR and one UIA source")
    return sorted(normalized, key=lambda source: str(source["source_kind"]))


def _verified_derived_views(
    *, store: UEIObjectStore, value: object, source_lineage: dict[str, Any],
    source_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("derived_views must be a bounded list")
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("derived view must be a closed object")
        stored_form = set(raw) == set(_DERIVED_STORED_FIELDS)
        view = _exact_object(
            raw,
            fields=_DERIVED_STORED_FIELDS if stored_form else _DERIVED_INPUT_FIELDS,
            name="derived view",
        )
        _reject_authority_aliases(view)
        target_lineage_ref = _immutable_ref(
            view["target_capture_lineage_ref"], name="target_capture_lineage_ref"
        )
        target_lineage = store.get(target_lineage_ref, contract_version="capture_lineage_v1")
        target_artifact_ref = _immutable_ref(view["target_artifact_ref"], name="target_artifact_ref")
        target_artifact = store.get(target_artifact_ref, contract_version="artifact_ref_v1")
        if (
            target_lineage["artifact_ref"] != target_artifact_ref
            or target_lineage["artifact_sha256"] != target_artifact["artifact_sha256"]
        ):
            raise ValueError("derived target artifact conflict")
        transform_ref = _immutable_ref(
            view["coordinate_transform_ref"], name="coordinate_transform_ref"
        )
        transform = store.get(transform_ref, contract_version="affine_coordinate_transform_v1")
        if stored_form and (
            canonical_json_bytes(view["target_capture_lineage"])
            != canonical_json_bytes(target_lineage)
            or canonical_json_bytes(view["target_artifact"])
            != canonical_json_bytes(target_artifact)
            or canonical_json_bytes(view["coordinate_transform"])
            != canonical_json_bytes(transform)
        ):
            raise ValueError("derived view embedded object conflict")
        expected_scale = {
            "x": target_lineage["image_size"]["width"] / source_lineage["image_size"]["width"],
            "y": target_lineage["image_size"]["height"] / source_lineage["image_size"]["height"],
        }
        if (
            transform["source_space"] != "capture_pixel_xyxy"
            or transform["target_space"] not in {"capture_pixel_xyxy", "image_pixel_xyxy"}
            or transform["source_size"] != source_lineage["image_size"]
            or transform["target_size"] != target_lineage["image_size"]
            or transform["source_capture_artifact_sha256"] != source_artifact["artifact_sha256"]
            or transform["target_capture_artifact_sha256"] != target_artifact["artifact_sha256"]
            or transform["offset"] != {"x": 0, "y": 0}
            or transform["clipping"] != "reject_if_outside"
        ):
            raise ValueError("derived affine binding mismatch")
        if not all(
            math.isclose(float(transform["scale"][axis]), expected_scale[axis], rel_tol=0, abs_tol=1e-12)
            for axis in ("x", "y")
        ):
            raise ValueError("affine scale mismatch")
        normalized.append({
            "target_capture_lineage_ref": target_lineage_ref,
            "target_capture_lineage": target_lineage,
            "target_artifact_ref": target_artifact_ref,
            "target_artifact": target_artifact,
            "coordinate_transform_ref": transform_ref,
            "coordinate_transform": transform,
        })
    return normalized


def _read_server_owned_image(*, root: Path, image_path: Path) -> tuple[Path, bytes]:
    return _read_verified_image(
        root=root,
        image_path=image_path,
        allowed_root=root / _SCREENSHOT_RELATIVE_PATH,
        boundary_name="screenshot service root",
    )


def _read_verified_image(
    *, root: Path, image_path: Path, allowed_root: Path, boundary_name: str,
) -> tuple[Path, bytes]:
    if not isinstance(image_path, Path):
        raise ValueError("image_path must be a server-owned Path")
    candidate = image_path if image_path.is_absolute() else root / image_path
    _reject_reparse_ancestors(candidate.absolute(), stop=allowed_root.parent)
    try:
        resolved_root = allowed_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as error:
        raise ValueError(f"server-owned image must be inside {boundary_name}") from error
    _reject_reparse_ancestors(resolved, stop=resolved_root.parent)
    before = os.stat(resolved, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("server-owned image must be a regular screenshot")
    descriptor = os.open(str(resolved), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        opened = os.fstat(descriptor)
        final_path = _final_handle_path(descriptor, fallback=resolved)
        try:
            final_path.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"opened image handle escaped {boundary_name}") from error
        _reject_reparse_ancestors(final_path, stop=resolved_root.parent)
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
    after_path = os.stat(final_path, follow_symlinks=False)
    if not _same_file_state(opened, after_fd) or not _same_file_state(after_fd, after_path):
        raise ValueError("server-owned image changed during read")
    if not image_bytes or len(image_bytes) != after_fd.st_size:
        raise ValueError("server-owned image read was incomplete")
    return final_path, image_bytes


def _final_handle_path(descriptor: int, *, fallback: Path) -> Path:
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes

            handle = msvcrt.get_osfhandle(descriptor)
            buffer = ctypes.create_unicode_buffer(32768)
            get_final_path = ctypes.windll.kernel32.GetFinalPathNameByHandleW
            get_final_path.argtypes = [
                wintypes.HANDLE,
                wintypes.LPWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            get_final_path.restype = wintypes.DWORD
            length = get_final_path(
                handle, buffer, len(buffer), 0
            )
            if not length or length >= len(buffer):
                raise OSError("GetFinalPathNameByHandleW failed")
            value = buffer.value
            if value.startswith("\\\\?\\UNC\\"):
                value = "\\\\" + value[8:]
            elif value.startswith("\\\\?\\"):
                value = value[4:]
            return Path(value).resolve(strict=True)
        except (ImportError, OSError, ValueError) as error:
            raise ValueError("unable to verify final screenshot handle path") from error
    proc_path = Path(f"/proc/self/fd/{descriptor}")
    return proc_path.resolve(strict=True) if proc_path.exists() else fallback.resolve(strict=True)


def _image_facts(image_bytes: bytes) -> tuple[str, dict[str, int], str]:
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            opened.verify()
        with Image.open(BytesIO(image_bytes)) as opened:
            size = {"width": int(opened.width), "height": int(opened.height)}
            image_format = str(opened.format or "").upper()
    except Exception as error:
        raise ValueError("server-owned screenshot is invalid") from error
    media_type = {"PNG": "image/png", "JPEG": "image/jpeg"}.get(image_format)
    if media_type is None:
        raise ValueError("server-owned screenshot format is unsupported")
    return sha256(image_bytes).hexdigest(), size, media_type


def _window_binding(value: object) -> dict[str, Any]:
    binding = _exact_object(value, fields=_WINDOW_FIELDS, name="window binding")
    rect = _exact_object(binding["rect"], fields=_RECT_FIELDS, name="window binding rect")
    if (
        not isinstance(binding["window_binding_id"], str)
        or not binding["window_binding_id"]
        or len(binding["window_binding_id"]) > 256
        or isinstance(binding["process_id"], bool)
        or not isinstance(binding["process_id"], int)
        or binding["process_id"] < 1
        or not isinstance(binding["process_name"], str)
        or not binding["process_name"]
        or len(binding["process_name"]) > 512
        or not all(isinstance(rect[field], int) and not isinstance(rect[field], bool) for field in _RECT_FIELDS)
        or rect["left"] >= rect["right"]
        or rect["top"] >= rect["bottom"]
    ):
        raise ValueError("window binding is invalid")
    _reject_authority_aliases(binding)
    return binding


def _exact_object(value: object, *, fields: set[str] | frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{name} must be a closed object")
    candidate = deepcopy(value)
    canonical = canonical_json_bytes(candidate)
    if len(canonical) > 1024 * 1024:
        raise ValueError(f"{name} exceeds size limit")
    return candidate


def _reject_authority_aliases(value: object, *, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("context exceeds depth limit")
    if isinstance(value, dict):
        forbidden = set(value) & _AUTHORITY_ALIASES
        if forbidden:
            raise ValueError(f"context contains authority alias: {sorted(forbidden)[0]}")
        if len(value) > 64:
            raise ValueError("context object exceeds property limit")
        for child in value.values():
            _reject_authority_aliases(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 256:
            raise ValueError("context array exceeds item limit")
        for child in value:
            _reject_authority_aliases(child, depth=depth + 1)
    elif isinstance(value, str) and len(value) > 4096:
        raise ValueError("context string exceeds length limit")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("context number must be finite")


def _immutable_ref(value: object, *, name: str) -> dict[str, str]:
    reference = _exact_object(value, fields={"id", "content_sha256"}, name=name)
    identifier, digest = reference["id"], reference["content_sha256"]
    if (
        not isinstance(identifier, str)
        or not identifier
        or len(identifier) > 512
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{name} is invalid")
    return {"id": identifier, "content_sha256": digest}


def _require_non_authorizing(value: dict[str, Any], *, name: str) -> None:
    if any(value.get(field) != expected for field, expected in _NON_AUTHORIZING.items()):
        raise ValueError(f"{name} violates non-authorizing invariant")
    _reject_authority_aliases(value)


def _run_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("run_id is required")
    return value.strip()


def _workflow_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("workflow_revision must be a non-negative integer")
    return value


def _store(root: Path) -> UEIObjectStore:
    return UEIObjectStore(root=root / _STORE_RELATIVE_PATH)


def _project_root(project_root: Path) -> Path:
    if not isinstance(project_root, Path):
        raise ValueError("project_root must be a Path")
    try:
        root = project_root.resolve(strict=True)
    except OSError as error:
        raise ValueError("project_root is unavailable") from error
    if not root.is_dir():
        raise ValueError("project_root must be a directory")
    _reject_reparse_ancestors(root)
    return root


def _reject_reparse_ancestors(path: Path, *, stop: Path | None = None) -> None:
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
        if current == current.parent or current == stop:
            return
        current = current.parent


def _same_file_state(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev, left.st_ino, left.st_size, left.st_mtime_ns
    ) == (
        right.st_dev, right.st_ino, right.st_size, right.st_mtime_ns
    )
