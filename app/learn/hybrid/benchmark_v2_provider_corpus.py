"""Load only the sealed provider-safe Benchmark v2 child corpus."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.learn.hybrid.benchmark_v2_contracts import (
    ARM_ORDER,
    BENCHMARK_RELEASE_ID,
    PROVIDER_CORPUS_CONTRACT,
    PROVIDER_CODE_REFS,
    PROVIDER_MANIFEST_CONTRACT,
    SAFETY,
    canonical_json_bytes,
    closed_mapping,
    content_sha256,
    require_relative_posix_path,
    require_sha256,
    sha256_bytes,
    validate_parent_ref,
)


_OPAQUE_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(
    r"^tests/fixtures/portfolio_hybrid_v1_1/corpus/(regression|holdout)/case-[0-9]{3}\.png$"
)
_FORBIDDEN_KEY_PARTS = (
    "gold",
    "private",
    "target_id",
    "screen_id",
    "acceptable",
    "bbox",
    "reviewer",
    "annotator",
    "scorer",
    "coordinate",
    "click",
    "point",
    "action",
)
_ALLOWED_SAFETY_KEYS = {
    "artifact_is_authorization",
    "execute_binding_enabled",
    "display_only",
}
_FORBIDDEN_PATH_PARTS = (
    "corpus-manifest.v1.json",
    "gold.v1.json",
    "/gold/",
    "benchmark_scorer",
)


def _reject_private_content(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("provider objects require string keys")
            lowered = key.casefold()
            if key not in _ALLOWED_SAFETY_KEYS and any(
                token in lowered for token in _FORBIDDEN_KEY_PARTS
            ):
                raise ValueError(f"provider object contains forbidden key: {key}")
            _reject_private_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_content(nested)
    elif isinstance(value, str):
        normalized = value.casefold().replace("\\", "/")
        if any(token in normalized for token in _FORBIDDEN_PATH_PARTS):
            raise ValueError("provider object contains a private or Gold path")


def _validate_case(value: object) -> dict[str, Any]:
    case = closed_mapping(
        value,
        {"case_id", "partition", "screen_group", "goal", "image", "layout"},
        "provider case",
    )
    if _OPAQUE_RE.fullmatch(str(case["case_id"])) is None:
        raise ValueError("case_id must be opaque SHA-256")
    if _OPAQUE_RE.fullmatch(str(case["screen_group"])) is None:
        raise ValueError("screen_group must be opaque SHA-256")
    if case["partition"] not in {"regression", "holdout"}:
        raise ValueError("provider case partition is invalid")
    if not isinstance(case["goal"], str) or not case["goal"].strip():
        raise ValueError("provider safe goal must be non-empty")
    image = closed_mapping(
        case["image"],
        {"path", "sha256", "width", "height"},
        "provider image",
    )
    path = require_relative_posix_path(image["path"], "provider image path")
    match = _IMAGE_RE.fullmatch(path)
    if match is None or match.group(1) != case["partition"]:
        raise ValueError("provider image path is outside the sealed screenshot set")
    require_sha256(image["sha256"], "provider image sha256")
    if (image["width"], image["height"]) != (1280, 720):
        raise ValueError("provider image dimensions are invalid")
    layout = closed_mapping(
        case["layout"],
        {
            "layout_id",
            "title",
            "surface",
            "density",
            "precision_case",
            "source_kind",
            "source_provenance",
        },
        "provider layout",
    )
    if not all(isinstance(item, str) and item for item in layout.values()):
        raise ValueError("provider layout metadata must be non-empty strings")
    if layout["source_kind"] != "privacy_safe_synthetic":
        raise ValueError("provider image source is not privacy safe")
    case["image"] = image
    case["layout"] = layout
    return case


def _validate_provider_corpus(value: object) -> dict[str, Any]:
    corpus = closed_mapping(
        value,
        {
            "contract_version",
            "benchmark_release_id",
            "source_parent_ref",
            "provider_boundary",
            "cases",
            "safety",
            "content_sha256",
        },
        "provider corpus",
    )
    _reject_private_content(corpus)
    if corpus["contract_version"] != PROVIDER_CORPUS_CONTRACT:
        raise ValueError("provider corpus contract_version is invalid")
    if corpus["benchmark_release_id"] != BENCHMARK_RELEASE_ID:
        raise ValueError("provider corpus release is invalid")
    corpus["source_parent_ref"] = validate_parent_ref(corpus["source_parent_ref"])
    boundary = closed_mapping(
        corpus["provider_boundary"],
        {
            "opaque_case_ids",
            "opaque_screen_groups",
            "filter_complete",
            "path_scope",
        },
        "provider boundary",
    )
    if boundary != {
        "opaque_case_ids": True,
        "opaque_screen_groups": True,
        "filter_complete": True,
        "path_scope": "provider_safe_only",
    }:
        raise ValueError("provider boundary declaration is invalid")
    if corpus["safety"] != SAFETY:
        raise ValueError("provider corpus safety boundary is invalid")
    if not isinstance(corpus["cases"], list) or len(corpus["cases"]) != 120:
        raise ValueError("provider corpus must contain exactly 120 cases")
    cases = [_validate_case(item) for item in corpus["cases"]]
    case_ids = [item["case_id"] for item in cases]
    if len(set(case_ids)) != 120:
        raise ValueError("provider case IDs must be globally unique")
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in cases:
        groups.setdefault(item["screen_group"], []).append(item)
    if len(groups) != 24 or {len(items) for items in groups.values()} != {5}:
        raise ValueError("provider corpus must contain 24 five-case screen groups")
    partition_groups: dict[str, set[str]] = {"regression": set(), "holdout": set()}
    image_identity: dict[str, tuple[object, ...]] = {}
    for group_id, items in groups.items():
        partitions = {item["partition"] for item in items}
        images = {
            (
                item["image"]["path"],
                item["image"]["sha256"],
                item["image"]["width"],
                item["image"]["height"],
            )
            for item in items
        }
        layouts = {json.dumps(item["layout"], sort_keys=True) for item in items}
        if len(partitions) != 1 or len(images) != 1 or len(layouts) != 1:
            raise ValueError("screen group members must share partition, image, and layout")
        partition_groups[next(iter(partitions))].add(group_id)
        image_identity[group_id] = next(iter(images))
    if {key: len(items) for key, items in partition_groups.items()} != {
        "regression": 12,
        "holdout": 12,
    }:
        raise ValueError("provider corpus must contain 12+12 screen groups")
    if len(set(image_identity.values())) != 24:
        raise ValueError("each screen group must bind one distinct screenshot")
    require_sha256(corpus["content_sha256"], "provider corpus content_sha256")
    if corpus["content_sha256"] != content_sha256(corpus):
        raise ValueError("provider corpus content SHA mismatch")
    corpus["provider_boundary"] = boundary
    corpus["cases"] = cases
    return corpus


def load_provider_corpus(*, child_path: Path, expected_sha256: str) -> dict[str, object]:
    raw = Path(child_path).read_bytes()
    return validate_preloaded_provider_corpus(raw=raw, expected_sha256=expected_sha256)


def validate_preloaded_provider_corpus(
    *, raw: bytes, expected_sha256: str
) -> dict[str, object]:
    """Validate one immutable child snapshot without reopening its source path."""

    require_sha256(expected_sha256, "expected provider child file SHA")
    if sha256_bytes(raw) != expected_sha256:
        raise ValueError("provider child file SHA mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider child is not UTF-8 JSON") from exc
    if raw != canonical_json_bytes(value, pretty=True):
        raise ValueError("provider child bytes are not canonical")
    return _validate_provider_corpus(value)


def validate_provider_manifest(value: Mapping[str, object]) -> dict[str, object]:
    manifest = closed_mapping(
        value,
        {
            "contract_version",
            "benchmark_release_id",
            "provider_corpus_ref",
            "sealed_runtime",
            "workload",
            "arm_order",
            "safety",
        },
        "provider manifest",
    )
    _reject_private_content(manifest)
    if manifest["contract_version"] != PROVIDER_MANIFEST_CONTRACT:
        raise ValueError("provider manifest contract_version is invalid")
    if manifest["benchmark_release_id"] != BENCHMARK_RELEASE_ID:
        raise ValueError("provider manifest release is invalid")
    ref = closed_mapping(
        manifest["provider_corpus_ref"],
        {
            "contract_version",
            "relative_path",
            "file_sha256",
            "content_sha256",
            "source_parent_ref",
        },
        "provider corpus ref",
    )
    if ref["contract_version"] != PROVIDER_CORPUS_CONTRACT:
        raise ValueError("provider corpus ref contract is invalid")
    relative_path = require_relative_posix_path(ref["relative_path"], "provider corpus path")
    if relative_path != "provider-corpus.v2.json":
        raise ValueError("provider corpus path is not the sealed provider-safe child")
    require_sha256(ref["file_sha256"], "provider corpus file SHA")
    require_sha256(ref["content_sha256"], "provider corpus content SHA")
    ref["source_parent_ref"] = validate_parent_ref(ref["source_parent_ref"])
    runtime = closed_mapping(
        manifest["sealed_runtime"],
        {"code_refs", "profile_refs"},
        "provider sealed runtime",
    )
    code_refs = runtime["code_refs"]
    if not isinstance(code_refs, list) or len(code_refs) != len(PROVIDER_CODE_REFS):
        raise ValueError("provider manifest must seal the exact bootstrap code set")
    validated_code: list[dict[str, Any]] = []
    for item, expected in zip(code_refs, PROVIDER_CODE_REFS, strict=True):
        code = closed_mapping(
            item,
            {"role", "relative_path", "file_sha256"},
            "provider code ref",
        )
        if (code["role"], code["relative_path"]) != expected:
            raise ValueError("provider code ref role/path is invalid")
        require_relative_posix_path(code["relative_path"], "provider code path")
        require_sha256(code["file_sha256"], "provider code file SHA")
        validated_code.append(code)
    profile_refs = runtime["profile_refs"]
    if not isinstance(profile_refs, list) or not 1 <= len(profile_refs) <= 16:
        raise ValueError("provider manifest profile refs are invalid")
    validated_profiles: list[dict[str, Any]] = []
    seen_profiles: set[str] = set()
    for item in profile_refs:
        profile = closed_mapping(
            item,
            {"role", "relative_path", "file_sha256"},
            "provider profile ref",
        )
        path = require_relative_posix_path(
            profile["relative_path"], "provider profile path"
        )
        if (
            not path.startswith("configs/")
            or not path.endswith(".json")
            or path in seen_profiles
            or not isinstance(profile["role"], str)
            or not profile["role"]
        ):
            raise ValueError("provider profile ref is invalid")
        require_sha256(profile["file_sha256"], "provider profile file SHA")
        seen_profiles.add(path)
        validated_profiles.append(profile)
    runtime["code_refs"] = validated_code
    runtime["profile_refs"] = validated_profiles
    workload = closed_mapping(
        manifest["workload"],
        {
            "contract_version",
            "command",
            "artifact_is_authorization",
            "execute_binding_enabled",
        },
        "provider workload request",
    )
    if workload != {
        "contract_version": "provider_sandbox_workload_request_v1",
        "command": "validate_provider_corpus",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }:
        raise ValueError("provider workload request is invalid")
    if manifest["arm_order"] != list(ARM_ORDER):
        raise ValueError("provider manifest arm order is invalid")
    if manifest["safety"] != SAFETY:
        raise ValueError("provider manifest safety boundary is invalid")
    manifest["provider_corpus_ref"] = ref
    manifest["sealed_runtime"] = runtime
    manifest["workload"] = workload
    return manifest
