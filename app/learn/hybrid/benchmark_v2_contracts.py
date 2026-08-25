"""Benchmark v2 provider-safe contracts and immutable identities."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


BENCHMARK_RELEASE_ID = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
PROVIDER_CORPUS_CONTRACT = "portfolio_hybrid_v1_1_provider_corpus_v2"
PROVIDER_MANIFEST_CONTRACT = "portfolio_hybrid_v1_1_provider_manifest_v2"
PARENT_REF_CONTRACT = "portfolio_hybrid_v1_1_corpus_parent_ref_v1"
PARENT_ARTIFACT_ID = "portfolio-hybrid-v1-1-corpus-parent"
PARENT_FILE_SHA256 = "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
PARENT_CONTENT_SHA256 = "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93"
ARM_ORDER = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
PARENT_REF = {
    "contract_version": PARENT_REF_CONTRACT,
    "artifact_id": PARENT_ARTIFACT_ID,
    "file_sha256": PARENT_FILE_SHA256,
    "content_sha256": PARENT_CONTENT_SHA256,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: object, *, pretty: bool = False) -> bytes:
    if pretty:
        return (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_sha256(value: Mapping[str, object]) -> str:
    unhashed = {key: item for key, item in value.items() if key != "content_sha256"}
    return sha256_bytes(canonical_json_bytes(unhashed))


def closed_mapping(
    value: object,
    fields: set[str],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return deepcopy(dict(value))


def require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def require_relative_posix_path(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{name} must be a non-empty POSIX relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{name} must remain inside its declared root")
    return value


def validate_parent_ref(value: object) -> dict[str, Any]:
    parent = closed_mapping(
        value,
        {"contract_version", "artifact_id", "file_sha256", "content_sha256"},
        "source_parent_ref",
    )
    if parent != PARENT_REF:
        raise ValueError("source parent lineage does not match the frozen corpus parent")
    return parent
