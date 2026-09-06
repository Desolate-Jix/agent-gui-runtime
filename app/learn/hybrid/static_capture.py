"""固定公开截图的只读 capture 封装；不伪造实时窗口或 OCR/UIA。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from app.learn.hybrid import capture
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


_CONTEXT_CONTRACT = "hybrid_static_capture_context_v1"
_BUNDLE_CONTRACT = "hybrid_static_capture_bundle_v1"
_BUNDLE_PREFIX = "hybrid-static-capture/"
FROZEN_SELECTION_CATALOG_SHA256 = "bb09975c8042f72a59e41fa9f22969cf5104c8419deb5e9d62804ee855a35d92"
_FIXED_SELECTION_DATASET = "portfolio_hybrid_v1_1"
_FIXED_SELECTION_CATALOG = Path("configs") / "benchmarks" / "learning_selection_acceptance_v1.json"
_AVAILABILITY = {
    "ocr": {"status": "not_collected_static"},
    "uia": {"status": "not_applicable_static", "reason": "no_live_window"},
}


def seal_static_capture_bundle(
    *,
    project_root: Path,
    image_path: Path,
    run_id: str,
    workflow_revision: int,
    static_asset: dict[str, object],
) -> dict[str, Any]:
    """封存固定公开图片的真实身份，并返回复验后的静态 bundle。"""
    root = capture._project_root(project_root)
    normalized_run_id = capture._run_id(run_id)
    revision = capture._workflow_revision(workflow_revision)
    asset, record = _verified_static_asset(root, static_asset)
    image, raw = capture._read_server_owned_image(root=root, image_path=image_path)
    artifact_sha, image_size, media_type = capture._image_facts(raw)
    _require_manifest_image(record, artifact_sha=artifact_sha, image_size=image_size, byte_length=len(raw))
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    capture_id = _expected_capture_id(
        run_id=normalized_run_id, workflow_revision=revision, static_asset=asset,
        artifact_sha256=artifact_sha, captured_at=timestamp,
    )
    store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
    artifact_ref = store.put(seal_immutable({
        "contract_version": "artifact_ref_v1",
        "artifact_id": f"artifact/static/{artifact_sha}",
        "artifact_sha256": artifact_sha,
        "media_type": media_type,
        "byte_length": len(raw),
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
    context_base: dict[str, object] = {
        "contract_version": _CONTEXT_CONTRACT,
        "context_id": "",
        "run_id": normalized_run_id,
        "workflow_revision": revision,
        "capture_lineage_ref": lineage_ref,
        "window_binding": None,
        "static_asset": asset,
        "availability": deepcopy(_AVAILABILITY),
        "sources": [],
        "derived_views": [],
        **capture._NON_AUTHORIZING,
    }
    context_base["context_id"] = "hybrid-static-context/" + sha256(
        canonical_json_bytes(context_base)
    ).hexdigest()
    context_ref = store.put(seal_immutable(context_base))
    bundle_base: dict[str, object] = {
        "contract_version": _BUNDLE_CONTRACT,
        "bundle_id": "",
        "run_id": normalized_run_id,
        "workflow_revision": revision,
        "capture_lineage_ref": lineage_ref,
        "artifact_ref": artifact_ref,
        "context_ref": context_ref,
        **capture._NON_AUTHORIZING,
    }
    bundle_base["bundle_id"] = _BUNDLE_PREFIX + sha256(canonical_json_bytes(bundle_base)).hexdigest()
    bundle_ref = store.put(seal_immutable(bundle_base))
    return load_static_capture_bundle(
        project_root=root, bundle_ref=bundle_ref, expected_run_id=normalized_run_id,
        expected_workflow_revision=revision,
    )


def load_static_capture_bundle(
    *,
    project_root: Path,
    bundle_ref: dict[str, str],
    expected_run_id: str,
    expected_workflow_revision: int,
) -> dict[str, Any]:
    """重验静态 bundle、内嵌清单父证据和真实图片身份。"""
    root = capture._project_root(project_root)
    run_id = capture._run_id(expected_run_id)
    revision = capture._workflow_revision(expected_workflow_revision)
    reference = capture._immutable_ref(bundle_ref, name="bundle_ref")
    if not reference["id"].startswith(_BUNDLE_PREFIX):
        raise ValueError("static capture bundle ref prefix is invalid")
    store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
    bundle = store.get(reference, contract_version=_BUNDLE_CONTRACT)
    capture._require_non_authorizing(bundle, name="hybrid static capture bundle")
    bundle_base = deepcopy(bundle)
    bundle_base.pop("content_sha256", None)
    bundle_base["bundle_id"] = ""
    if bundle["bundle_id"] != _BUNDLE_PREFIX + sha256(canonical_json_bytes(bundle_base)).hexdigest():
        raise ValueError("static capture bundle identity mismatch")
    if bundle["run_id"] != run_id:
        raise ValueError("cross-run bundle")
    if bundle["workflow_revision"] != revision:
        raise ValueError("stale workflow revision")
    lineage_ref = capture._immutable_ref(bundle["capture_lineage_ref"], name="capture_lineage_ref")
    artifact_ref = capture._immutable_ref(bundle["artifact_ref"], name="artifact_ref")
    context_ref = capture._immutable_ref(bundle["context_ref"], name="context_ref")
    lineage = store.get(lineage_ref, contract_version="capture_lineage_v1")
    artifact = store.get(artifact_ref, contract_version="artifact_ref_v1")
    context = store.get(context_ref, contract_version=_CONTEXT_CONTRACT)
    capture._require_non_authorizing(context, name="hybrid static capture context")
    _verify_context(
        context=context, context_ref=context_ref, bundle=bundle, lineage_ref=lineage_ref,
        artifact_ref=artifact_ref, run_id=run_id, workflow_revision=revision,
    )
    asset, record = _verified_static_asset(root, context["static_asset"])
    _require_manifest_image(
        record, artifact_sha=str(artifact["artifact_sha256"]),
        image_size=dict(lineage["image_size"]), byte_length=int(artifact["byte_length"]),
    )
    if (
        lineage["artifact_ref"] != artifact_ref
        or lineage["artifact_sha256"] != artifact["artifact_sha256"]
        or lineage["image_size"] != _manifest_image_size(record)
        or lineage["capture_id"] != _expected_capture_id(
            run_id=run_id, workflow_revision=revision, static_asset=asset,
            artifact_sha256=str(artifact["artifact_sha256"]), captured_at=str(lineage["captured_at"]),
        )
    ):
        raise ValueError("static capture identity mismatch")
    identity = capture._capture_identity(
        lineage=lineage, lineage_ref=lineage_ref, artifact=artifact,
        artifact_ref=artifact_ref, workflow_revision=revision,
    )
    return {**deepcopy(bundle), "bundle_ref": reference, "capture_identity": identity, "context": deepcopy(context)}


def _verify_context(
    *,
    context: Mapping[str, object],
    context_ref: Mapping[str, str],
    bundle: Mapping[str, object],
    lineage_ref: Mapping[str, str],
    artifact_ref: Mapping[str, str],
    run_id: str,
    workflow_revision: int,
) -> None:
    required = {
        "contract_version", "context_id", "run_id", "workflow_revision",
        "capture_lineage_ref", "window_binding", "static_asset", "availability",
        "sources", "derived_views", "artifact_is_authorization",
        "execute_binding_enabled", "final_submit_forbidden", "real_action_requires_gate",
        "authorization_scope", "content_sha256",
    }
    if set(context) != required or context.get("contract_version") != _CONTEXT_CONTRACT:
        raise ValueError("static capture context is invalid")
    if (
        context.get("run_id") != run_id
        or context.get("workflow_revision") != workflow_revision
        or context.get("capture_lineage_ref") != lineage_ref
        or context.get("window_binding") is not None
        or context.get("sources") != []
        or context.get("derived_views") != []
        or context.get("availability") != _AVAILABILITY
        or bundle.get("capture_lineage_ref") != lineage_ref
        or bundle.get("artifact_ref") != artifact_ref
        or bundle.get("context_ref") != context_ref
    ):
        raise ValueError("static capture context provenance mismatch")
    base = deepcopy(dict(context))
    declared = base.pop("content_sha256", None)
    context_id = base.get("context_id")
    base["context_id"] = ""
    if (
        not isinstance(declared, str)
        or context_ref != {"id": context_id, "content_sha256": declared}
        or context_id != "hybrid-static-context/" + sha256(canonical_json_bytes(base)).hexdigest()
    ):
        raise ValueError("static capture context identity mismatch")


def _verified_static_asset(root: Path, value: object) -> tuple[dict[str, object], dict[str, object]]:
    if not isinstance(value, Mapping) or set(value) != {
        "case_id", "dataset", "revision", "source_manifest_ref",
    }:
        raise ValueError("static asset is invalid")
    asset = deepcopy(dict(value))
    case_id, dataset, revision = asset["case_id"], asset["dataset"], asset["revision"]
    reference = asset["source_manifest_ref"]
    if (
        not isinstance(case_id, str) or not case_id or len(case_id) > 256
        or not isinstance(revision, str)
        or not isinstance(reference, Mapping) or set(reference) != {"relative_path", "sha256"}
    ):
        raise ValueError("static asset is invalid")
    relative_path, manifest_sha = reference["relative_path"], reference["sha256"]
    if (
        not isinstance(relative_path, str) or not relative_path
        or not isinstance(manifest_sha, str) or len(manifest_sha) != 64
        or any(char not in "0123456789abcdef" for char in manifest_sha)
    ):
        raise ValueError("static asset manifest ref is invalid")
    relative = Path(relative_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("static asset manifest path is invalid")
    candidate = root / relative
    capture._reject_reparse_ancestors(candidate, stop=root.parent)
    manifest_path = candidate.resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as error:
        raise ValueError("static asset manifest path escapes project root") from error
    if not manifest_path.is_file():
        raise ValueError("static asset manifest is unavailable")
    raw = manifest_path.read_bytes()
    if sha256(raw).hexdigest() != manifest_sha:
        raise ValueError("static asset manifest hash mismatch")
    manifest = _json_object(raw, name="static asset manifest")
    if dataset == _FIXED_SELECTION_DATASET:
        return _verified_fixed_selection_asset(root=root, asset=asset, manifest=manifest)
    if (
        dataset != "OS-Copilot/ScreenSpot-v2"
        or len(revision) != 40
        or any(char not in "0123456789abcdef" for char in revision)
    ):
        raise ValueError("static asset is invalid")
    records = manifest.get("records")
    if (
        manifest.get("schema") != "public_screenspot_v2_regression_manifest_v1"
        or manifest.get("dataset") != dataset
        or manifest.get("revision") != revision
        or not isinstance(records, list)
    ):
        raise ValueError("static asset manifest is invalid")
    matching = [record for record in records if isinstance(record, Mapping) and record.get("case_id") == case_id]
    if len(matching) != 1:
        raise ValueError("static asset case is missing or duplicated")
    record = deepcopy(dict(matching[0]))
    if not _manifest_record_valid(record):
        raise ValueError("static asset manifest record is invalid")
    return asset, record


def _verified_fixed_selection_asset(
    *, root: Path, asset: dict[str, object], manifest: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """只允许固定25推理目录的图片身份，绝不读取评分或 gold 数据。"""
    revision = asset["revision"]
    required_manifest = {
        "schema", "dataset", "revision", "source_catalog_sha256", "records",
    }
    if (
        revision != FROZEN_SELECTION_CATALOG_SHA256
        or set(manifest) != required_manifest
        or manifest.get("schema") != "learning_selection_fixed_capture_manifest_v1"
        or manifest.get("dataset") != _FIXED_SELECTION_DATASET
        or manifest.get("revision") != FROZEN_SELECTION_CATALOG_SHA256
        or manifest.get("source_catalog_sha256") != FROZEN_SELECTION_CATALOG_SHA256
        or not isinstance(manifest.get("records"), list)
        or not manifest["records"]
    ):
        raise ValueError("fixed static asset manifest is invalid")
    records = manifest["records"]
    if any(
        not isinstance(item, Mapping)
        or set(item) != {"case_id", "image_sha256", "image_bytes", "width", "height"}
        or not _manifest_record_valid(item)
        for item in records
    ):
        raise ValueError("fixed static asset manifest record is invalid")
    case_ids = [str(item["case_id"]) for item in records]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("fixed static asset manifest has duplicate cases")
    catalog_path = root / _FIXED_SELECTION_CATALOG
    capture._reject_reparse_ancestors(catalog_path, stop=root.parent)
    if not catalog_path.is_file():
        raise ValueError("fixed selection catalog is unavailable")
    catalog_raw = catalog_path.read_bytes()
    if sha256(catalog_raw).hexdigest() != FROZEN_SELECTION_CATALOG_SHA256:
        raise ValueError("fixed selection catalog hash mismatch")
    catalog = _json_object(catalog_raw, name="fixed selection catalog")
    inference_rows = catalog.get("inference_rows")
    if not isinstance(inference_rows, list):
        raise ValueError("fixed selection catalog inference rows are invalid")
    for item in records:
        _require_fixed_catalog_identity(record=item, inference_rows=inference_rows)
    matching = [item for item in records if item["case_id"] == asset["case_id"]]
    if len(matching) != 1:
        raise ValueError("fixed static asset case is missing or duplicated")
    record = deepcopy(dict(matching[0]))
    return asset, record


def _require_fixed_catalog_identity(*, record: Mapping[str, object], inference_rows: list[object]) -> None:
    """仅从固定25 inference_rows 核验 case 的图片摘要和尺寸。"""
    identities: set[tuple[str, int, int]] = set()
    for row in inference_rows:
        if not isinstance(row, Mapping) or row.get("suite") != "fixed25" or row.get("case_id") != record["case_id"]:
            continue
        image_sha = row.get("image_sha256")
        image_size = row.get("image_size")
        if (
            not isinstance(image_sha, str)
            or not isinstance(image_size, list)
            or len(image_size) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size)
        ):
            raise ValueError("fixed selection catalog image identity is invalid")
        identities.add((image_sha, image_size[0], image_size[1]))
    expected = (str(record["image_sha256"]), int(record["width"]), int(record["height"]))
    if identities != {expected}:
        raise ValueError("fixed static asset does not match fixed25 inference image")


def _manifest_record_valid(record: Mapping[str, object]) -> bool:
    return (
        isinstance(record.get("image_sha256"), str)
        and len(str(record.get("image_sha256"))) == 64
        and all(char in "0123456789abcdef" for char in str(record.get("image_sha256")))
        and isinstance(record.get("image_bytes"), int)
        and not isinstance(record.get("image_bytes"), bool)
        and int(record["image_bytes"]) > 0
        and isinstance(record.get("width"), int)
        and isinstance(record.get("height"), int)
        and not isinstance(record.get("width"), bool)
        and not isinstance(record.get("height"), bool)
        and int(record["width"]) > 0
        and int(record["height"]) > 0
    )


def _require_manifest_image(
    record: Mapping[str, object], *, artifact_sha: str, image_size: Mapping[str, int], byte_length: int
) -> None:
    if (
        record["image_sha256"] != artifact_sha
        or record["image_bytes"] != byte_length
        or _manifest_image_size(record) != dict(image_size)
    ):
        raise ValueError("static asset manifest image identity mismatch")


def _manifest_image_size(record: Mapping[str, object]) -> dict[str, int]:
    return {"width": int(record["width"]), "height": int(record["height"])}


def _json_object(raw: bytes, *, name: str) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{name} is invalid") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _expected_capture_id(
    *,
    run_id: str,
    workflow_revision: int,
    static_asset: Mapping[str, object],
    artifact_sha256: str,
    captured_at: str,
) -> str:
    return "capture/static/" + sha256(canonical_json_bytes({
        "run_id": run_id,
        "workflow_revision": workflow_revision,
        "static_asset": deepcopy(dict(static_asset)),
        "artifact_sha256": artifact_sha256,
        "captured_at": captured_at,
    })).hexdigest()


__all__ = ["load_static_capture_bundle", "seal_static_capture_bundle"]
