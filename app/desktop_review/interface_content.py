"""独立界面内容的不可变来源、修订和人工审核记录。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any
from uuid import uuid4

from .external_mapping import (
    ExternalMappingError,
    canonical_json_bytes,
    source_image_relative_path,
    source_ref_for_batch,
)
from .workspace import DesktopReviewError, _atomic_write_bytes, _write_immutable


_CONTRACT = "desktop_interface_content_v1"
_REGISTRY = "desktop_interface_content_registry_v1"
_CURRENT = "desktop_interface_content_current_v1"
_ORIGIN = "desktop_interface_learning_origin_v1"
_INTERFACE_ID = re.compile(r"interface-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_USER_REGION_ID = re.compile(r"region-user-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
_EDITABLE_REGION_FIELDS = {"region_id", "bbox", "name", "kind", "meaning", "recognition_text"}
SUPPORTED_REGION_KINDS = ("unknown", "text", "control", "input", "button", "link", "menu", "image", "container", "other")
_REGION_KINDS = frozenset(SUPPORTED_REGION_KINDS)


class InterfaceContentService:
    """只通过 façade 锁使用；不创建图、工作流或动作。"""

    def __init__(self, facade: Any) -> None:
        self.facade = facade
        self.root = facade._workspace_root / "interface-contents"
        self.registry_path = self.root / "registry.json"

    def import_content(self, task_id: str, batch_id: str, external_interface_id: str) -> dict:
        task, batch_id, external = _text(task_id, "task_id"), _text(batch_id, "batch_id"), _text(external_interface_id, "external_interface_id")
        batch = self.facade._load_source_batch(task, batch_id)
        source_ref = source_ref_for_batch(batch)
        interface = _one(batch["interfaces"], "interface_id", external, "interface")
        shot = _one(batch["screenshots"], "screenshot_id", interface["screenshot_id"], "screenshot")
        self.facade._materialize_source(source_ref, batch)
        registry = self._registry()
        key = _source_key(task, batch_id, source_ref, external)
        interface_id = registry["sources"].get(key)
        if interface_id:
            self._require_active(interface_id, registry)
            return self.load(interface_id, None)
        interface_id = "interface-" + str(uuid4())
        source = {
            "task_id": task, "batch_id": batch_id, "source_ref": source_ref,
            "external_interface_id": external, "screenshot_id": shot["screenshot_id"],
            "screenshot_sha256": shot["sha256"],
        }
        value = self._base(interface_id, 1, source, {
            "meaning": interface["meaning"],
            "recognition_text": interface.get("recognition_text") or "",
            "regions": [_origin_region(item, interface.get("recognition_text") or "") for item in interface["regions"]],
            "application_binding": None,
        })
        self._write_version(value)
        self._commit_current(interface_id, value, {})
        registry["sources"][key] = interface_id
        registry["interface_ids"].append(interface_id)
        registry["interface_ids"].sort()
        self._write_registry(registry)
        return self._view(value)

    def list(self, reviewed_only: bool = False, task_id: str | None = None, *, include_deleted: bool = False) -> list[dict]:
        task = None if task_id is None else _text(task_id, "task_id")
        values = []
        registry = self._registry()
        for interface_id in registry["interface_ids"]:
            if not include_deleted and interface_id in registry.get("tombstones", {}):
                continue
            versions = self._versions(interface_id)
            if task is not None:
                versions = [item for item in versions if item["source"]["task_id"] == task]
            if not versions:
                continue
            if reviewed_only:
                reviewed = [item for item in versions if self._review(item) is not None]
                if not reviewed:
                    continue
                values.append(self._view(max(reviewed, key=lambda item: item["revision"])))
            else:
                values.append(self.load(interface_id, None))
        return sorted(values, key=lambda item: item["interface_id"])

    def load(self, interface_id: str, version_id: str | None) -> dict:
        interface = _interface_id(interface_id)
        if version_id is None:
            return self._view(self._versions(interface)[-1])
        version = _text(version_id, "version_id")
        matches = [item for item in self._versions(interface) if item["version_id"] == version]
        if len(matches) != 1:
            raise DesktopReviewError("interface_content_version_not_found")
        return self._view(matches[0])

    def save(self, interface_id: str, expected_revision: int, expected_sha256: str, changes: dict, idempotency_key: str) -> dict:
        interface, key = _interface_id(interface_id), _idempotency_key(idempotency_key)
        self._require_active(interface)
        manifest = self._current(interface)
        self._versions(interface)
        current = self._load_version(interface, manifest["content_sha256"])
        try:
            request = hashlib.sha256(canonical_json_bytes({"revision": expected_revision, "sha": expected_sha256, "changes": changes})).hexdigest()
        except ExternalMappingError:
            self._changed(current, changes)
            raise DesktopReviewError("interface_content_changes_invalid")
        prior = manifest["requests"].get(key)
        if prior is not None:
            if prior.get("request_sha256") != request:
                raise DesktopReviewError("idempotency_conflict")
            return self.load(interface, prior["version_id"])
        if type(expected_revision) is not int or expected_revision != current["revision"] or expected_sha256 != current["content_sha256"]:
            raise DesktopReviewError("stale_revision")
        content = self._changed(current, changes)
        value = self._base(
            interface, current["revision"] + 1, current["source"], content,
            parent_content_sha256=current["content_sha256"], request_sha256=request,
        )
        self._write_version(value)
        requests = deepcopy(manifest["requests"])
        requests[key] = {"request_sha256": request, "version_id": value["version_id"]}
        self._commit_current(interface, value, requests)
        return self._view(value)

    def _record_initial_learning_completion(self, interface_id: str, *, request_sha256: str) -> dict:
        """仅记录已核实的 Agent 首次完成，不按版本号猜测来源。"""
        interface = _interface_id(interface_id)
        versions = self._versions(interface)
        originals = [item for item in versions if item["revision"] == 1]
        completions = [item for item in versions if item["revision"] == 2 and item.get("request_sha256") == request_sha256]
        if len(originals) != 1 or len(completions) != 1:
            raise DesktopReviewError("interface_origin_marker_invalid")
        original, completion = originals[0], completions[0]
        if (original["source"].get("external_interface_id") != "observed-screen"
                or original["content"].get("regions") != []
                or completion.get("parent_content_sha256") != original["content_sha256"]
                or completion.get("revision") != 2
                or not completion["content"].get("regions")
                or completion["source"] != original["source"]
                or not _is_sha256(request_sha256)):
            raise DesktopReviewError("interface_origin_marker_invalid")
        marker = {
            "contract_version": _ORIGIN,
            "interface_id": interface,
            "original_version_id": original["version_id"],
            "original_content_sha256": original["content_sha256"],
            "completion_revision": completion["revision"],
            "completion_version_id": completion["version_id"],
            "completion_content_sha256": completion["content_sha256"],
            "source": deepcopy(original["source"]),
            "request_sha256": request_sha256,
        }
        marker["marker_sha256"] = hashlib.sha256(canonical_json_bytes(marker)).hexdigest()
        path = self._dir(interface) / "origin.json"
        if path.exists():
            existing = _json(path, "interface origin marker")
            if existing != marker:
                raise DesktopReviewError("interface_origin_marker_invalid")
        else:
            _write_immutable(path, canonical_json_bytes(marker) + b"\n")
        return self._view(completion)

    def review(self, interface_id: str, expected_revision: int, expected_sha256: str, application_binding: dict) -> dict:
        interface = _interface_id(interface_id)
        self._require_active(interface)
        self._versions(interface)
        current = self._load_version(interface, self._current(interface)["content_sha256"])
        if type(expected_revision) is not int or expected_revision != current["revision"] or expected_sha256 != current["content_sha256"]:
            raise DesktopReviewError("stale_revision")
        self._verified_evidence(current["source"])
        try:
            from .exact_review import ExactReviewError, _binding
            binding = _binding(application_binding)
        except (ExactReviewError, TypeError, ValueError) as error:
            raise DesktopReviewError("interface_content_application_binding_invalid") from error
        record = {"contract_version": _CONTRACT, "interface_id": interface, "version_id": current["version_id"], "content_sha256": current["content_sha256"], "application_binding": binding}
        record["review_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
        _write_immutable(self._dir(interface) / "reviews" / f"{current['version_id']}.json", canonical_json_bytes(record) + b"\n")
        return self._view(current)

    def evidence(self, interface_id: str, version_id: str | None) -> dict:
        value = self.load(interface_id, version_id)
        source = value["source"]
        path, _, width, height = self._verified_evidence(source)
        return {"image_path": path, "sha256": source["screenshot_sha256"], "width": width, "height": height}

    def memory(self, allowed_task_id: str, interface_id: str, version_id: str | None = None) -> dict:
        value = self.load(interface_id, None if version_id is None else _text(version_id, "version_id"))
        if value["source"]["task_id"] != _text(allowed_task_id, "allowed_task_id"):
            raise DesktopReviewError("interface_memory_not_found")
        self._verified_evidence(value["source"])
        return _memory_view(value)

    def search_memory(self, allowed_task_id: str, query: str = "") -> list[dict]:
        task = _text(allowed_task_id, "allowed_task_id")
        if not isinstance(query, str):
            raise DesktopReviewError("query must be text")
        term = query.strip().casefold()
        result = []
        for value in self.list(False, task):
            if value.get("learning_status") == "observation_only":
                continue
            searchable = " ".join((value["interface_id"], value["content"]["meaning"], value["content"].get("recognition_text", ""))).casefold()
            if not term or term in searchable:
                result.append(_memory_view(value))
        return result

    def _changed(self, current: dict, changes: Any) -> dict:
        if not isinstance(changes, dict) or not changes or set(changes) - {"meaning", "recognition_text", "regions", "application_binding"}:
            raise DesktopReviewError("interface_content_changes_invalid")
        content = deepcopy(current["content"])
        if "meaning" in changes:
            content["meaning"] = _plain_text(changes["meaning"], "meaning")
        if "recognition_text" in changes:
            text = changes["recognition_text"]
            if not isinstance(text, str):
                raise DesktopReviewError("recognition_text must be text")
            if text.strip():
                content["recognition_text"] = _plain_text(text, "recognition_text")
            else:
                content.pop("recognition_text", None)
        if "application_binding" in changes:
            content["application_binding"] = _content_binding(changes["application_binding"])
        if "regions" in changes:
            updated = changes["regions"]
            if not isinstance(updated, list) or len(updated) > 128:
                raise DesktopReviewError("interface_content_regions_invalid")
            old = {item["region_id"]: item for item in content["regions"]}
            next_regions = []
            seen = set()
            for item in updated:
                if not isinstance(item, dict) or not isinstance(item.get("region_id"), str):
                    raise DesktopReviewError("interface_content_regions_invalid")
                region_id = item["region_id"]
                if region_id in seen:
                    raise DesktopReviewError("interface_content_region_duplicate")
                seen.add(region_id)
                if region_id in old:
                    candidate = _replace_existing_region(old[region_id], item)
                else:
                    if not _USER_REGION_ID.fullmatch(region_id):
                        raise DesktopReviewError("interface_content_region_identity_changed")
                    if set(item) != _EDITABLE_REGION_FIELDS:
                        raise DesktopReviewError("interface_content_region_fields_invalid")
                    candidate = deepcopy(item)
                if not isinstance(candidate.get("kind"), str) or candidate["kind"] not in _REGION_KINDS:
                    raise DesktopReviewError("interface_content_region_kind_invalid")
                if not _valid_region(candidate) or not self._bbox(candidate["bbox"], current["source"]):
                    raise DesktopReviewError("interface_content_region_bbox_invalid")
                candidate["bbox"] = [float(value) for value in candidate["bbox"]]
                next_regions.append(candidate)
            content["regions"] = next_regions
        return content

    def _bbox(self, value: Any, source: dict) -> bool:
        if not isinstance(value, list) or len(value) != 4 or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
            return False
        _, raw = self._image_bytes(source)
        image_width, image_height = _png_dimensions(raw)
        x, y, width, height = value
        return all(math.isfinite(float(item)) for item in value) and x >= 0 and y >= 0 and width > 0 and height > 0 and x + width <= image_width and y + height <= image_height

    def _image_bytes(self, source: dict) -> tuple[str, bytes]:
        path = source_image_relative_path(
            source["source_ref"],
            {
                "screenshot_id": source["screenshot_id"],
                "sha256": source["screenshot_sha256"],
            },
        )
        file = self.facade._artifact_file(path, "独立界面截图")
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["screenshot_sha256"]:
            raise DesktopReviewError("interface_content_evidence_sha256_mismatch")
        return path, raw

    def _verified_evidence(self, source: dict) -> tuple[str, bytes, int, int]:
        path, raw = self._image_bytes(source)
        width, height = _png_dimensions(raw)
        return path, raw, width, height

    def _base(self, interface_id: str, revision: int, source: dict, content: dict,
              parent_content_sha256: str | None = None, request_sha256: str | None = None) -> dict:
        value = {"contract_version": _CONTRACT, "interface_id": interface_id, "version_id": "", "revision": revision, "content_sha256": "", "review_status": "draft", "application_binding": None, "source": deepcopy(source), "content": deepcopy(content), "parent_content_sha256": parent_content_sha256, "request_sha256": request_sha256}
        digest = hashlib.sha256(canonical_json_bytes({key: value[key] for key in ("contract_version", "interface_id", "revision", "source", "content", "parent_content_sha256", "request_sha256")})).hexdigest()
        value["content_sha256"] = digest
        value["version_id"] = "interface-version-" + digest
        return value

    def _view(self, value: dict) -> dict:
        result = {key: deepcopy(value[key]) for key in ("interface_id", "version_id", "revision", "content_sha256", "review_status", "source", "content")}
        result["storage_status"] = "saved"
        origin = self._origin_marker(value["interface_id"])
        result["origin_status"] = "new" if value["revision"] == 1 else "modified"
        if origin is not None and value["version_id"] == origin["completion_version_id"]:
            result["origin_status"] = "new"
        result["application_binding"] = deepcopy(value["content"].get("application_binding"))
        review = self._review(value)
        if review is not None:
            result["review_status"] = "reviewed"
            if result["application_binding"] is None:
                result["application_binding"] = deepcopy(review["application_binding"])
        from .learning_catalog import annotate_learning_content
        return annotate_learning_content(self.facade, result)

    def _origin_marker(self, interface_id: str) -> dict | None:
        path = self._dir(interface_id) / "origin.json"
        if not path.exists():
            return None
        marker = _json(path, "interface origin marker")
        required = {"contract_version", "interface_id", "original_version_id", "original_content_sha256",
                    "completion_revision", "completion_version_id", "completion_content_sha256", "source",
                    "request_sha256", "marker_sha256"}
        if set(marker) != required or marker.get("contract_version") != _ORIGIN or marker.get("interface_id") != interface_id:
            raise DesktopReviewError("interface_origin_marker_invalid")
        digest = marker.copy()
        digest.pop("marker_sha256")
        if not _is_sha256(marker.get("marker_sha256")) or hashlib.sha256(canonical_json_bytes(digest)).hexdigest() != marker["marker_sha256"]:
            raise DesktopReviewError("interface_origin_marker_invalid")
        if not _is_sha256(marker.get("original_content_sha256")) or not _is_sha256(marker.get("completion_content_sha256")) or not _is_sha256(marker.get("request_sha256")):
            raise DesktopReviewError("interface_origin_marker_invalid")
        try:
            original = self._load_version(interface_id, marker["original_content_sha256"])
            completion = self._load_version(interface_id, marker["completion_content_sha256"])
        except (DesktopReviewError, TypeError, ValueError):
            raise DesktopReviewError("interface_origin_marker_invalid") from None
        if (type(marker["completion_revision"]) is not int or marker["completion_revision"] != 2
                or original["revision"] != 1 or original["version_id"] != marker["original_version_id"]
                or original["source"].get("external_interface_id") != "observed-screen"
                or original["content"].get("regions") != []
                or completion["revision"] != 2 or completion.get("parent_content_sha256") != original["content_sha256"]
                or not completion["content"].get("regions")
                or completion["version_id"] != marker["completion_version_id"]
                or completion["request_sha256"] != marker["request_sha256"] or original["source"] != marker["source"]
                or completion["source"] != original["source"]):
            raise DesktopReviewError("interface_origin_marker_invalid")
        return marker

    def _review(self, value: dict) -> dict | None:
        path = self._dir(value["interface_id"]) / "reviews" / f"{value['version_id']}.json"
        if not path.exists():
            return None
        record = _json(path, "interface content review")
        if set(record) != {"contract_version", "interface_id", "version_id", "content_sha256", "application_binding", "review_sha256"} or record.get("contract_version") != _CONTRACT or record.get("interface_id") != value["interface_id"] or record.get("version_id") != value["version_id"] or record.get("content_sha256") != value["content_sha256"] or not _is_sha256(record.get("review_sha256")):
            raise DesktopReviewError("interface_content_review_invalid")
        expected = hashlib.sha256(canonical_json_bytes({key: record[key] for key in (
            "contract_version", "interface_id", "version_id", "content_sha256", "application_binding",
        )})).hexdigest()
        if expected != record["review_sha256"]:
            raise DesktopReviewError("interface_content_review_invalid")
        try:
            from app.learn.application_identity import normalize_application_identity
            if normalize_application_identity(record["application_binding"]) != record["application_binding"]:
                raise DesktopReviewError("interface_content_review_invalid")
        except (TypeError, ValueError) as error:
            raise DesktopReviewError("interface_content_review_invalid") from error
        return record

    def _versions(self, interface_id: str) -> list[dict]:
        interface = _interface_id(interface_id)
        manifest = self._current(interface)
        result = []
        seen = set()
        digest: str | None = manifest["content_sha256"]
        while digest is not None:
            if digest in seen:
                raise DesktopReviewError("interface_content_history_invalid")
            seen.add(digest)
            value = self._load_version(interface, digest)
            result.append(value)
            digest = value["parent_content_sha256"]
        values = list(reversed(result))
        for index, value in enumerate(values, start=1):
            parent = None if index == 1 else values[index - 2]["content_sha256"]
            if value["revision"] != index or value["parent_content_sha256"] != parent:
                raise DesktopReviewError("interface_content_history_invalid")
        versions_by_id = {value["version_id"]: value for value in values}
        for request in manifest["requests"].values():
            version = versions_by_id.get(request["version_id"])
            if version is None or version["request_sha256"] != request["request_sha256"]:
                raise DesktopReviewError("interface_content_current_invalid")
        return values

    def _load_version(self, interface_id: str, digest: str) -> dict:
        interface, marker = _interface_id(interface_id), _sha256(digest, "content_sha256")
        value = _json(self._dir(interface) / "revisions" / f"{marker}.json", "interface content version")
        if not _valid_version(value, interface, marker):
            raise DesktopReviewError("interface_content_version_invalid")
        self._validate_source_binding(value["source"], value["content"])
        return value

    def _write_version(self, value: dict) -> None:
        _write_immutable(self._dir(value["interface_id"]) / "revisions" / f"{value['content_sha256']}.json", canonical_json_bytes(value) + b"\n")

    def _current(self, interface_id: str) -> dict:
        current = _json(self._dir(interface_id) / "current.json", "interface content current")
        if set(current) != {"contract_version", "interface_id", "content_sha256", "requests"} or current.get("contract_version") != _CURRENT or current.get("interface_id") != interface_id or not _is_sha256(current.get("content_sha256")) or not _valid_requests(current.get("requests")):
            raise DesktopReviewError("interface_content_current_invalid")
        return current

    def _commit_current(self, interface_id: str, value: dict, requests: dict) -> None:
        _atomic_write_bytes(self._dir(interface_id) / "current.json", canonical_json_bytes({"contract_version": _CURRENT, "interface_id": interface_id, "content_sha256": value["content_sha256"], "requests": requests}) + b"\n")

    def _registry(self) -> dict:
        if not self.registry_path.exists():
            return {"contract_version": _REGISTRY, "sources": {}, "interface_ids": []}
        value = _json(self.registry_path, "interface content registry")
        if value.get("contract_version") != _REGISTRY or not isinstance(value.get("sources"), dict) or not isinstance(value.get("interface_ids"), list):
            raise DesktopReviewError("interface_content_registry_invalid")
        tombstones = value.get("tombstones", {})
        if not isinstance(tombstones, dict):
            raise DesktopReviewError("interface_content_tombstones_invalid")
        for interface_id, marker in tombstones.items():
            if (interface_id not in value["interface_ids"] or not isinstance(marker, dict)
                    or set(marker) != {"interface_id", "revision", "content_sha256", "deleted_at"}
                    or marker.get("interface_id") != interface_id
                    or type(marker.get("revision")) is not int or marker["revision"] < 1
                    or not _is_sha256(marker.get("content_sha256"))
                    or not isinstance(marker.get("deleted_at"), str) or not marker["deleted_at"]):
                raise DesktopReviewError("interface_content_tombstones_invalid")
        return value

    def _require_active(self, interface_id: str, registry: dict | None = None) -> None:
        registry = self._registry() if registry is None else registry
        if interface_id in registry.get("tombstones", {}):
            raise DesktopReviewError("interface_content_deleted: 该界面已从界面库删除，历史版本和图引用仍保留")

    def _write_registry(self, value: dict) -> None:
        _atomic_write_bytes(self.registry_path, canonical_json_bytes(value) + b"\n")

    def _dir(self, interface_id: str) -> Path:
        interface = _interface_id(interface_id)
        path = (self.root / interface).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as error:
            raise DesktopReviewError("interface_content_path_invalid") from error
        return path

    def _validate_source_binding(self, source: dict, content: dict) -> None:
        reference = Path("desktop-review") / "sources" / source["source_ref"] / "original_batch.json"
        source_file = self.facade._artifact_file(reference.as_posix(), "独立界面原始来源")
        try:
            batch = self.facade._normalize_source_copy(
                _json(source_file, "独立界面原始来源"), source["task_id"], source["batch_id"], source["source_ref"],
            )
        except ExternalMappingError as error:
            raise DesktopReviewError("interface_content_source_invalid") from error
        if source_ref_for_batch(batch) != source["source_ref"]:
            raise DesktopReviewError("interface_content_source_invalid")
        interface = _one(batch["interfaces"], "interface_id", source["external_interface_id"], "interface")
        screenshot = _one(batch["screenshots"], "screenshot_id", source["screenshot_id"], "screenshot")
        if screenshot["sha256"] != source["screenshot_sha256"] or interface["screenshot_id"] != source["screenshot_id"]:
            raise DesktopReviewError("interface_content_source_invalid")
        self._verified_evidence(source)


def _memory_view(value: dict) -> dict:
    result = {"contract_version": "agent_interface_memory_v1", "interface_id": value["interface_id"], "version_id": value["version_id"], "content_sha256": value["content_sha256"], "storage_status": value["storage_status"], "origin_status": value["origin_status"], "application_binding": deepcopy(value["application_binding"]), "source": {key: value["source"][key] for key in ("task_id", "batch_id", "source_ref", "external_interface_id", "screenshot_id", "screenshot_sha256")}, "content": deepcopy(value["content"]), "artifact_is_authorization": False, "execute_binding_enabled": False}
    result["learning_status"] = value.get("learning_status", "interface_content")
    if "learning_flow" in value:
        result["learning_flow"] = deepcopy(value["learning_flow"])
    return result


def _origin_region(value: Any, interface_recognition: str) -> dict:
    if not isinstance(value, dict):
        raise DesktopReviewError("interface_content_regions_invalid")
    result = deepcopy(value)
    result.update({
        "region_id": _text(value.get("region_id"), "region_id"),
        "bbox": deepcopy(value.get("bbox")),
        "name": _plain_text(value.get("name") or value.get("label") or value.get("meaning"), "region_name"),
        "kind": _region_kind(value.get("kind") or value.get("type") or "unknown"),
        "meaning": _plain_text(value.get("meaning"), "region_meaning"),
        "recognition_text": _optional_text(value.get("recognition_text"), "", "region_recognition_text"),
    })
    if not _valid_region(result):
        raise DesktopReviewError("interface_content_regions_invalid")
    return result


def _replace_existing_region(existing: dict, supplied: dict) -> dict:
    if set(supplied) == {"region_id", "bbox"}:
        candidate = deepcopy(existing)
        candidate["bbox"] = deepcopy(supplied["bbox"])
        return candidate
    if not _EDITABLE_REGION_FIELDS <= set(supplied):
        raise DesktopReviewError("interface_content_region_fields_invalid")
    for key in set(supplied) - _EDITABLE_REGION_FIELDS:
        if key not in existing or supplied[key] != existing[key]:
            raise DesktopReviewError("interface_content_region_preserved_field_changed")
    candidate = deepcopy(existing)
    for key in _EDITABLE_REGION_FIELDS:
        candidate[key] = deepcopy(supplied[key])
    if candidate["region_id"] != existing["region_id"]:
        raise DesktopReviewError("interface_content_region_identity_changed")
    return candidate


def _optional_text(value: Any, fallback: str, name: str) -> str:
    if value is None:
        value = fallback
    if not isinstance(value, str):
        raise DesktopReviewError(f"{name} must be text")
    text = value.strip()
    if len(text) > 4000:
        raise DesktopReviewError(f"{name} is too long")
    return text


def _region_kind(value: Any) -> str:
    if not isinstance(value, str) or value.strip() not in _REGION_KINDS:
        return "other" if isinstance(value, str) and value.strip() else "unknown"
    return value.strip()


def _content_binding(value: Any) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise DesktopReviewError("interface_content_application_binding_invalid")
    kind = value.get("kind")
    allowed = {
        "native": {"kind", "display_name", "executable_identity", "product_name"},
        "web": {"kind", "display_name", "canonical_origin"},
    }
    if kind not in allowed or set(value) - allowed[kind] or not isinstance(value.get("display_name"), str) or not value["display_name"].strip():
        raise DesktopReviewError("interface_content_application_binding_invalid")
    try:
        from app.learn.application_identity import normalize_application_identity
        normalized = normalize_application_identity(value)
    except (TypeError, ValueError) as error:
        raise DesktopReviewError("interface_content_application_binding_invalid") from error
    if not isinstance(normalized, dict) or normalized.get("kind") != kind:
        raise DesktopReviewError("interface_content_application_binding_invalid")
    return normalized


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise DesktopReviewError(f"{name} must be text")
    text = value.strip()
    if not text:
        raise DesktopReviewError(f"{name} is required")
    return text


def _plain_text(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > 4000:
        raise DesktopReviewError(f"{name} is too long")
    return text


def _interface_id(value: Any) -> str:
    identifier = _text(value, "interface_id")
    if not _INTERFACE_ID.fullmatch(identifier):
        raise DesktopReviewError("interface_content_id_invalid")
    return identifier


def _idempotency_key(value: Any) -> str:
    key = _text(value, "idempotency_key")
    if not _IDEMPOTENCY_KEY.fullmatch(key):
        raise DesktopReviewError("interface_content_idempotency_key_invalid")
    return key


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _sha256(value: Any, name: str) -> str:
    if not _is_sha256(value):
        raise DesktopReviewError(f"{name} is invalid")
    return value


def _valid_requests(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    for key, record in value.items():
        if not isinstance(key, str) or not _IDEMPOTENCY_KEY.fullmatch(key) or not isinstance(record, dict):
            return False
        if set(record) != {"request_sha256", "version_id"} or not _is_sha256(record.get("request_sha256")):
            return False
        version_id = record.get("version_id")
        if not isinstance(version_id, str) or not version_id.startswith("interface-version-") or not _is_sha256(version_id.removeprefix("interface-version-")):
            return False
    return True


def _valid_version(value: Any, interface_id: str, digest: str) -> bool:
    required = {
        "contract_version", "interface_id", "version_id", "revision", "content_sha256",
        "review_status", "application_binding", "source", "content",
        "parent_content_sha256", "request_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        return False
    if value.get("contract_version") != _CONTRACT or value.get("interface_id") != interface_id:
        return False
    revision = value.get("revision")
    if type(revision) is not int or revision < 1 or value.get("content_sha256") != digest:
        return False
    if value.get("version_id") != "interface-version-" + digest or value.get("review_status") != "draft" or value.get("application_binding") is not None:
        return False
    parent, request = value.get("parent_content_sha256"), value.get("request_sha256")
    if revision == 1:
        if parent is not None or request is not None:
            return False
    elif not _is_sha256(parent) or not _is_sha256(request):
        return False
    if not _valid_source(value.get("source")) or not _valid_content(value.get("content")):
        return False
    calculated = hashlib.sha256(canonical_json_bytes({key: value[key] for key in (
        "contract_version", "interface_id", "revision", "source", "content",
        "parent_content_sha256", "request_sha256",
    )})).hexdigest()
    return calculated == digest


def _valid_source(value: Any) -> bool:
    required = {
        "task_id", "batch_id", "source_ref", "external_interface_id",
        "screenshot_id", "screenshot_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        return False
    if not all(isinstance(value.get(name), str) and value[name].strip() for name in required - {"source_ref", "screenshot_sha256"}):
        return False
    return _is_sha256(value.get("source_ref")) and _is_sha256(value.get("screenshot_sha256"))


def _valid_content(value: Any) -> bool:
    allowed = {"meaning", "recognition_text", "regions", "application_binding"}
    if not isinstance(value, dict) or not {"meaning", "regions"} <= set(value) or set(value) - allowed:
        return False
    if not isinstance(value.get("meaning"), str) or not value["meaning"].strip() or len(value["meaning"]) > 4000:
        return False
    if "recognition_text" in value and (not isinstance(value["recognition_text"], str) or len(value["recognition_text"]) > 4000):
        return False
    if "application_binding" in value:
        binding = value["application_binding"]
        if binding is not None:
            try:
                from app.learn.application_identity import normalize_application_identity
                if not isinstance(binding, dict) or normalize_application_identity(binding) != binding:
                    return False
            except (TypeError, ValueError):
                return False
    regions = value.get("regions")
    if not isinstance(regions, list) or len(regions) > 128:
        return False
    identities = set()
    for region in regions:
        if not isinstance(region, dict) or not isinstance(region.get("region_id"), str) or not region["region_id"].strip() or region["region_id"] in identities:
            return False
        identities.add(region["region_id"])
        if not _valid_region(region):
            return False
    return True


def _valid_region(value: Any) -> bool:
    if not isinstance(value, dict) or not _EDITABLE_REGION_FIELDS <= set(value):
        return False
    if not isinstance(value["region_id"], str) or not value["region_id"].strip():
        return False
    if any(not isinstance(value[key], str) or len(value[key].strip()) > 4000 for key in ("name", "meaning", "recognition_text")):
        return False
    if not value["name"].strip() or not value["meaning"].strip() or value["kind"] not in _REGION_KINDS:
        return False
    box = value["bbox"]
    return isinstance(box, list) and len(box) == 4 and not any(
        isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
        for item in box
    )


def _one(values: Any, key: str, identity: str, label: str) -> dict:
    found = [item for item in values if isinstance(item, dict) and item.get(key) == identity] if isinstance(values, list) else []
    if len(found) != 1:
        raise DesktopReviewError(f"interface_content_{label}_not_found")
    return found[0]


def _source_key(task: str, batch: str, source_ref: str, external: str) -> str:
    return hashlib.sha256(canonical_json_bytes({"task_id": task, "batch_id": batch, "source_ref": source_ref, "external_interface_id": external})).hexdigest()


def _png_dimensions(value: bytes) -> tuple[int, int]:
    if len(value) < 24 or value[:8] != b"\x89PNG\r\n\x1a\n" or value[12:16] != b"IHDR":
        raise DesktopReviewError("interface_content_image_invalid")
    width, height = struct.unpack(">II", value[16:24])
    if width < 1 or height < 1:
        raise DesktopReviewError("interface_content_image_invalid")
    return width, height


def _json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise DesktopReviewError(f"{label}_invalid") from error
    if not isinstance(value, dict):
        raise DesktopReviewError(f"{label}_invalid")
    return value
