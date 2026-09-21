"""逻辑流程版本的规范元数据；不规划、不执行，也不代替人工审核。"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

CONTRACT = "reviewed_workflow_versions_v1"
RECORD_CONTRACT = "reviewed_workflow_version_v1"
KEYS = {"workflow_version_contract", "workflow_versions", "current_version_by_workflow", "withdrawn_workflow_versions"}
PUBLICATION_FIELDS = {"logical_workflow_id", "graph_revision", "graph_sha256", "review_ref", "approval_revision"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LOGICAL = re.compile(r"workflow-[0-9a-f]{64}\Z")
_VERSION = re.compile(r"version-[0-9a-f]{64}\Z")


def logical_id(value: Any) -> str:
    if not isinstance(value, str) or not _LOGICAL.fullmatch(value):
        raise ValueError("logical_workflow_id must be a canonical workflow ID")
    return value


def version_id(value: Any) -> str:
    if not isinstance(value, str) or not _VERSION.fullmatch(value):
        raise ValueError("version_id must be a canonical version ID")
    return value


def make_record(publication: Any, asset_id: str, asset_sha256: str) -> dict:
    if not isinstance(publication, dict) or set(publication) != PUBLICATION_FIELDS:
        raise ValueError("workflow publication binding is invalid")
    logical_id(publication["logical_workflow_id"])
    for key in ("graph_revision", "approval_revision"):
        value = publication[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"workflow publication {key} must be a positive integer")
    for key in ("graph_sha256", "review_ref"):
        value = publication[key]
        if not isinstance(value, str) or not _SHA.fullmatch(value):
            raise ValueError(f"workflow publication {key} is invalid")
    if not isinstance(asset_id, str) or not asset_id or not isinstance(asset_sha256, str) or not _SHA.fullmatch(asset_sha256):
        raise ValueError("workflow version asset binding is invalid")
    payload = {"contract_version": RECORD_CONTRACT, **deepcopy(publication),
               "asset_id": asset_id, "asset_sha256": asset_sha256}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**payload, "version_id": "version-" + digest}


def validate_extension(registry: dict) -> None:
    present = set(registry) & KEYS
    if not present:
        return
    if present != KEYS or registry.get("workflow_version_contract") != CONTRACT:
        raise ValueError("workflow version registry extension is incomplete or unsupported")
    versions = registry["workflow_versions"]
    current = registry["current_version_by_workflow"]
    withdrawn = registry["withdrawn_workflow_versions"]
    if not isinstance(versions, dict) or not isinstance(current, dict) or not isinstance(withdrawn, list):
        raise ValueError("workflow version indexes must be objects")
    if any(not isinstance(item, str) for item in withdrawn) or withdrawn != sorted(set(withdrawn)) or set(withdrawn) - set(versions):
        raise ValueError("withdrawn workflow version index is invalid")
    graph_hashes = {}
    for identity, item in versions.items():
        version_id(identity)
        if not isinstance(item, dict):
            raise ValueError("workflow version record is invalid")
        wanted = make_record({key: item.get(key) for key in PUBLICATION_FIELDS},
                             item.get("asset_id"), item.get("asset_sha256"))
        if item != wanted or identity != wanted["version_id"]:
            raise ValueError("workflow version record hash or identity is invalid")
        graph_key = (item["logical_workflow_id"], item["graph_revision"])
        old_hash = graph_hashes.setdefault(graph_key, item["graph_sha256"])
        if old_hash != item["graph_sha256"]:
            raise ValueError("workflow revision has conflicting graph hashes")
        asset = registry["objects"].get(item["asset_sha256"])
        if not isinstance(asset, dict) or asset.get("asset_id") != item["asset_id"] or asset.get("content_sha256") != item["asset_sha256"]:
            raise ValueError("workflow version asset record is missing or changed")
    for logical, identity in current.items():
        logical_id(logical)
        version_id(identity)
        item = versions.get(identity)
        if item is None or item["logical_workflow_id"] != logical or identity in withdrawn:
            raise ValueError("current workflow version belongs to a different workflow")


def add_version(registry: dict, record: dict) -> None:
    registry.setdefault("workflow_version_contract", CONTRACT)
    versions = registry.setdefault("workflow_versions", {})
    current = registry.setdefault("current_version_by_workflow", {})
    registry.setdefault("withdrawn_workflow_versions", [])
    logical = record["logical_workflow_id"]
    old = versions.get(current.get(logical))
    if old is not None and record["graph_revision"] < old["graph_revision"]:
        raise ValueError("new publication cannot silently downgrade the current graph revision")
    versions[record["version_id"]] = deepcopy(record)
    current[logical] = record["version_id"]
    validate_extension(registry)


def view(registry: dict, record: dict, asset: dict) -> dict:
    current = registry["current_version_by_workflow"].get(record["logical_workflow_id"]) == record["version_id"]
    withdrawn = record["version_id"] in registry["withdrawn_workflow_versions"]
    return {**deepcopy(record), "status": "withdrawn" if withdrawn else "current" if current else "superseded",
            "current": current, "asset": deepcopy(asset), "registry_revision": registry["registry_revision"],
            "artifact_is_authorization": False, "execute_binding_enabled": False}
