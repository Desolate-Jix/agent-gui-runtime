"""Benchmark v2 public-safe score validation and leakage scanning authority."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote


BENCHMARK_RELEASE_ID = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}

MAX_CONTAINER_DEPTH = 32
MAX_VISITED_NODES = 100_000
MAX_STRING_UTF8_BYTES = 16_777_216
MAX_BASE64_DECODE_DEPTH = 8
MAX_DECODED_BYTES = 67_108_864
MAX_PERCENT_DECODE_DEPTH = 32

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_RE = re.compile(
    r"^tests/fixtures/portfolio_hybrid_v1_1/corpus/(regression|holdout)/case-[0-9]{3}\.png$"
)
_URI_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
_DRIVE_RE = re.compile(r"^[a-z]:[\\/]", re.IGNORECASE)
_RELATIVE_FILE_RE = re.compile(r"(?:^|/)[^/\s]+\.[a-z0-9]{1,16}(?:$|[?#])", re.IGNORECASE)

_FORBIDDEN_FIELDS = {
    "acceptable_regions",
    "annotator_identity_hash",
    "gold",
    "gold_path",
    "private_manifest_path",
    "private_output",
    "reviewer_identity_hash",
    "target_id",
}
_FORBIDDEN_TEXT = (
    "gold.v1.json",
    "corpus-manifest.v1.json",
    "benchmark_v2_privileged_projector.py",
)
_INPUT_BINDING_FIELDS = {"contract_version", "benchmark_release_id", "partition", "private_manifest_ref", "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref", "accepted_run_ref", "attempt_ref", "attempt_ledger_ref", "automatic_prediction_ref", "selected_lifecycle_ref", "estimand_ref", "gate_ref", "safety"}
_PUBLIC_SCORE_FIELDS = {"status", "score_ref", "content_sha256", "contract_version", "score_input_binding", "binding", "launch_receipt", "cleanup_receipt", "safety"}
_PROVIDER_CODE_REFS = (
    ("bootstrap", "app/learn/hybrid/benchmark_v2_provider_sandbox.py"),
    ("contracts", "app/learn/hybrid/benchmark_v2_contracts.py"),
    ("corpus_loader", "app/learn/hybrid/benchmark_v2_provider_corpus.py"),
)
_ROLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PARENT_REF = {
    "contract_version": "portfolio_hybrid_v1_1_corpus_parent_ref_v1",
    "artifact_id": "portfolio-hybrid-v1-1-corpus-parent",
    "file_sha256": "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757",
    "content_sha256": "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93",
}
_EVALUATION_PROJECTION_SHA256 = "68138312ef3f372357357d5bcdc23034cb4c1e658827dc74f5495727562f63e7"
_PROVIDER_FORBIDDEN_KEY_PARTS = ("gold", "private", "target_id", "screen_id", "acceptable", "bbox", "reviewer", "annotator", "scorer", "coordinate", "click", "point", "action")
_PROVIDER_FORBIDDEN_PATH_PARTS = ("corpus-manifest.v1.json", "gold.v1.json", "/gold/", "benchmark_scorer")
_ALLOWED_SAFETY_KEYS = {"artifact_is_authorization", "execute_binding_enabled", "display_only"}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def content_sha256(value: object) -> str:
    return sha256_bytes(canonical_bytes(value))


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} not closed")
    return dict(value)


def _exact_ref(value: object, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "content_sha256"}:
        raise ValueError(f"{name} must be exact ref")
    result = dict(value)
    if not isinstance(result["id"], str) or not result["id"] or not isinstance(result["content_sha256"], str) or len(result["content_sha256"]) != 64:
        raise ValueError(f"{name} invalid")
    return result


def _normalized_relative_posix(value: object) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if value.startswith(("/", "\\")) or "\\" in value or _URI_RE.match(value) or _DRIVE_RE.match(value):
        return None
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part != part.strip() for part in parts):
        return None
    if unquote(value) != value:
        return None
    return value


def _exact_parent_ref(value: object) -> bool:
    return isinstance(value, Mapping) and dict(value) == _PARENT_REF


def _provider_private_content_safe(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or key not in _ALLOWED_SAFETY_KEYS and any(token in key.casefold() for token in _PROVIDER_FORBIDDEN_KEY_PARTS) or not _provider_private_content_safe(child):
                return False
    elif isinstance(value, list):
        return all(_provider_private_content_safe(child) for child in value)
    elif isinstance(value, str):
        normalized = value.casefold().replace("\\", "/")
        return not any(token in normalized for token in _PROVIDER_FORBIDDEN_PATH_PARTS)
    return True


def _exact_json_value(value: object) -> bool:
    if type(value) is dict:
        return all(type(key) is str and _exact_json_value(child) for key, child in value.items())
    if type(value) is list:
        return all(_exact_json_value(child) for child in value)
    return value is None or type(value) in {str, int, bool, float}


def _provider_corpus_snapshot_valid(value: Mapping[str, object]) -> bool:
    if set(value) != {"contract_version", "benchmark_release_id", "source_parent_ref", "provider_boundary", "cases", "safety", "content_sha256"} or value.get("contract_version") != "portfolio_hybrid_v1_1_provider_corpus_v2" or value.get("benchmark_release_id") != BENCHMARK_RELEASE_ID or value.get("safety") != SAFETY or not _exact_parent_ref(value.get("source_parent_ref")):
        return False
    if not _provider_private_content_safe(value) or value.get("provider_boundary") != {"opaque_case_ids": True, "opaque_screen_groups": True, "filter_complete": True, "path_scope": "provider_safe_only"}:
        return False
    cases = value.get("cases")
    if not isinstance(cases, list) or len(cases) != 120:
        return False
    groups: dict[str, list[Mapping[str, object]]] = {}
    case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != {"case_id", "partition", "screen_group", "goal", "image", "layout"} or not _is_sha(case.get("case_id")) or not _is_sha(case.get("screen_group")) or case.get("partition") not in {"regression", "holdout"} or not isinstance(case.get("goal"), str) or not case["goal"].strip():
            return False
        if case["case_id"] in case_ids:
            return False
        case_ids.add(case["case_id"])
        image = case.get("image")
        if not isinstance(image, Mapping) or set(image) != {"path", "sha256", "width", "height"}:
            return False
        path = image.get("path")
        match = _IMAGE_RE.fullmatch(path) if isinstance(path, str) else None
        if match is None or match.group(1) != case["partition"] or _normalized_relative_posix(path) != path or not _is_sha(image.get("sha256")) or (image.get("width"), image.get("height")) != (1280, 720):
            return False
        layout = case.get("layout")
        layout_fields = {"layout_id", "title", "surface", "density", "precision_case", "source_kind", "source_provenance"}
        if not isinstance(layout, Mapping) or set(layout) != layout_fields or not all(isinstance(item, str) and item for item in layout.values()) or layout.get("source_kind") != "privacy_safe_synthetic":
            return False
        groups.setdefault(str(case["screen_group"]), []).append(case)
    if len(groups) != 24 or {len(items) for items in groups.values()} != {5}:
        return False
    partition_groups = {"regression": 0, "holdout": 0}
    image_identities = set()
    for items in groups.values():
        partitions = {str(item["partition"]) for item in items}
        images = {canonical_bytes(item["image"]) for item in items}
        layouts = {canonical_bytes(item["layout"]) for item in items}
        if len(partitions) != 1 or len(images) != 1 or len(layouts) != 1:
            return False
        partition_groups[next(iter(partitions))] += 1
        image_identities.add(next(iter(images)))
    return partition_groups == {"regression": 12, "holdout": 12} and len(image_identities) == 24 and _is_sha(value.get("content_sha256")) and value["content_sha256"] == content_sha256({key: child for key, child in value.items() if key != "content_sha256"})


def _closed_runtime_ref(value: object) -> bool:
    return isinstance(value, Mapping) and set(value) == {"role", "relative_path", "file_sha256"} and isinstance(value.get("role"), str) and _ROLE_RE.fullmatch(value["role"]) is not None and _normalized_relative_posix(value.get("relative_path")) == value.get("relative_path") and _is_sha(value.get("file_sha256"))


def _provider_manifest_snapshot_valid(value: Mapping[str, object]) -> bool:
    if set(value) != {"contract_version", "benchmark_release_id", "provider_corpus_ref", "holdout_partition", "evaluation_projection", "sealed_runtime", "workload", "arm_order", "safety"} or value.get("contract_version") != "portfolio_hybrid_v1_1_provider_manifest_v2_1" or value.get("benchmark_release_id") != BENCHMARK_RELEASE_ID or value.get("holdout_partition") != "holdout" or value.get("arm_order") != ["qwen_only", "omni_only_discovery", "omni_to_qwen", "omni_to_qwen_vista"] or value.get("safety") != SAFETY:
        return False
    corpus_ref = value.get("provider_corpus_ref")
    if not isinstance(corpus_ref, Mapping) or set(corpus_ref) != {"contract_version", "relative_path", "file_sha256", "content_sha256", "source_parent_ref"} or corpus_ref.get("contract_version") != "portfolio_hybrid_v1_1_provider_corpus_v2" or corpus_ref.get("relative_path") != "provider-corpus.v2.json" or not _is_sha(corpus_ref.get("file_sha256")) or not _is_sha(corpus_ref.get("content_sha256")) or not _exact_parent_ref(corpus_ref.get("source_parent_ref")):
        return False
    projection = value.get("evaluation_projection")
    private_checked = {key: child for key, child in value.items() if key != "evaluation_projection"}
    if not _provider_private_content_safe(private_checked) or not isinstance(projection, Mapping) or set(projection) != {"provider_policy", "estimand", "gate"} or not _exact_json_value(projection):
        return False
    try:
        if sha256_bytes(canonical_bytes(projection)) != _EVALUATION_PROJECTION_SHA256:
            return False
    except (TypeError, ValueError):
        return False
    if value.get("workload") != {"contract_version": "provider_sandbox_workload_request_v1", "command": "validate_provider_corpus", "artifact_is_authorization": False, "execute_binding_enabled": False}:
        return False
    runtime = value.get("sealed_runtime")
    if not isinstance(runtime, Mapping) or set(runtime) != {"code_refs", "release_code_refs", "profile_refs"}:
        return False
    code_refs = runtime.get("code_refs")
    if not isinstance(code_refs, list) or len(code_refs) != len(_PROVIDER_CODE_REFS) or any(not _closed_runtime_ref(item) or (item["role"], item["relative_path"]) != expected for item, expected in zip(code_refs, _PROVIDER_CODE_REFS, strict=True)):
        return False
    release_refs = runtime.get("release_code_refs")
    if not isinstance(release_refs, list) or len(release_refs) < 2 or any(not _closed_runtime_ref(item) for item in release_refs):
        return False
    release_roles = [item["role"] for item in release_refs]
    release_paths = [item["relative_path"] for item in release_refs]
    if len(set(release_roles)) != len(release_roles) or len(set(release_paths)) != len(release_paths):
        return False
    boot_paths = {path for _, path in _PROVIDER_CODE_REFS}
    for path in release_paths:
        components = path.casefold().split("/")
        if not (path.startswith("app/") or path.startswith("scripts/")) or not path.endswith(".py") or path in boot_paths or any(token in path for token in ("%", "$", "~", ":")) or any(forbidden in component for component in components for forbidden in ("private", "gold", "scorer")):
            return False
    profile_refs = runtime.get("profile_refs")
    if not isinstance(profile_refs, list) or not 1 <= len(profile_refs) <= 16 or any(not _closed_runtime_ref(item) for item in profile_refs):
        return False
    profile_roles = [item["role"] for item in profile_refs]
    profile_paths = [item["relative_path"] for item in profile_refs]
    return len(set(profile_roles)) == len(profile_roles) and len(set(profile_paths)) == len(profile_paths) and all(path.startswith("configs/") and path.endswith(".json") for path in profile_paths)


def _provider_path_exceptions(value: object) -> dict[tuple[object, ...], str]:
    allowed: dict[tuple[object, ...], str] = {}
    if not isinstance(value, Mapping):
        return allowed
    contract = value.get("contract_version")
    if contract == "portfolio_hybrid_v1_1_provider_corpus_v2" and _provider_corpus_snapshot_valid(value):
        cases = value.get("cases")
        if not isinstance(cases, list):
            return allowed
        for index, case in enumerate(cases):
            if not isinstance(case, Mapping) or not isinstance(case.get("image"), Mapping):
                continue
            path = case["image"].get("path")
            match = _IMAGE_RE.fullmatch(path) if isinstance(path, str) else None
            if match is not None and match.group(1) == case.get("partition") and _normalized_relative_posix(path) == path:
                allowed[("cases", index, "image", "path")] = path
    elif contract == "portfolio_hybrid_v1_1_provider_manifest_v2_1" and _provider_manifest_snapshot_valid(value):
        allowed[("provider_corpus_ref", "relative_path")] = "provider-corpus.v2.json"
        runtime = value.get("sealed_runtime")
        if not isinstance(runtime, Mapping):
            return allowed
        for group in ("code_refs", "release_code_refs", "profile_refs"):
            refs = runtime.get(group)
            if not isinstance(refs, list):
                continue
            for index, ref in enumerate(refs):
                path = ref.get("relative_path") if isinstance(ref, Mapping) else None
                if _normalized_relative_posix(path) == path:
                    allowed[("sealed_runtime", group, index, "relative_path")] = path
    return allowed


def _binding_shape_valid(value: object) -> bool:
    if not isinstance(value, Mapping) or set(value) != _INPUT_BINDING_FIELDS or value.get("contract_version") != "private_scorer_input_binding_v1" or value.get("benchmark_release_id") != BENCHMARK_RELEASE_ID or value.get("partition") != "regression" or value.get("safety") != SAFETY:
        return False
    schemas = (("private_manifest_ref", {"contract_version", "file_sha256", "content_sha256"}), ("corpus_parent_ref", {"contract_version", "artifact_id", "file_sha256", "content_sha256"}), ("provider_manifest_ref", {"contract_version", "relative_path", "file_sha256"}), ("provider_corpus_ref", {"contract_version", "relative_path", "file_sha256", "content_sha256", "source_parent_ref"}), ("accepted_run_ref", {"contract_version", "file_sha256", "content_sha256"}), ("estimand_ref", {"contract_version", "file_sha256"}), ("gate_ref", {"contract_version", "file_sha256"}))
    for name, fields in schemas:
        ref = value.get(name)
        if not isinstance(ref, Mapping) or set(ref) != fields or any(key.endswith("sha256") and not _is_sha(child) for key, child in ref.items()):
            return False
    if value["provider_manifest_ref"].get("relative_path") != "benchmark-v2-provider-manifest.json" or value["provider_corpus_ref"].get("relative_path") != "provider-corpus.v2.json" or value["accepted_run_ref"].get("contract_version") != "benchmark_v2_accepted_regression_score_input_v2":
        return False
    return all(_exact_ref_shape(value.get(name)) for name in ("attempt_ref", "attempt_ledger_ref", "automatic_prediction_ref", "selected_lifecycle_ref"))


def _exact_ref_shape(value: object) -> bool:
    return isinstance(value, Mapping) and set(value) == {"id", "content_sha256"} and isinstance(value.get("id"), str) and bool(value["id"]) and isinstance(value.get("content_sha256"), str) and len(value["content_sha256"]) == 64


def _decode_canonical_envelope(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping) or set(value) != {"ref", "canonical_bytes_b64"} or not isinstance(value.get("canonical_bytes_b64"), str):
        return None
    encoded = value["canonical_bytes_b64"]
    try:
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            return None
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, Mapping) and canonical_bytes(decoded) == raw else None


def _score_ref_path_exceptions(value: object) -> dict[tuple[object, ...], str]:
    allowed: dict[tuple[object, ...], str] = {}
    prefixes: list[tuple[object, ...]] = []
    if _binding_shape_valid(value):
        prefixes.append(())
    elif isinstance(value, Mapping) and set(value) == _PUBLIC_SCORE_FIELDS and value.get("contract_version") == "private_scorer_public_ref_v3" and value.get("status") in {"PASS", "FAIL"} and value.get("safety") == SAFETY and _is_sha(value.get("content_sha256")) and value["content_sha256"] == content_sha256({key: child for key, child in value.items() if key != "content_sha256"}):
        top = value.get("score_input_binding")
        binding = value.get("binding")
        launch = _decode_canonical_envelope(value.get("launch_receipt"))
        if _binding_shape_valid(top) and isinstance(binding, Mapping) and set(binding) == {"contract_version", "child_score_ref", "score_input_binding", "launch_receipt_ref", "cleanup_receipt_ref", "safety", "content_sha256"} and binding.get("contract_version") == "private_scorer_final_binding_v2" and binding.get("score_input_binding") == top and _is_sha(binding.get("content_sha256")) and binding["content_sha256"] == content_sha256({key: child for key, child in binding.items() if key != "content_sha256"}) and isinstance(launch, Mapping) and set(launch) == {"contract_version", "launcher_process_id", "launcher_process_identity", "child_process_id", "child_process_identity", "pipe_capability_sha256", "argv_sha256", "env_sha256", "cwd_sha256", "job_identity_sha256", "child_execution_receipt_sha256", "child_score_ref", "score_input_binding", "safety", "content_sha256"} and launch.get("contract_version") == "private_scorer_launch_receipt_v2" and launch.get("score_input_binding") == top:
            prefixes.extend((("score_input_binding",), ("binding", "score_input_binding"), ("launch_receipt", "canonical_bytes_b64", "score_input_binding")))
    for prefix in prefixes:
        allowed[prefix + ("provider_manifest_ref", "relative_path")] = "benchmark-v2-provider-manifest.json"
        allowed[prefix + ("provider_corpus_ref", "relative_path")] = "provider-corpus.v2.json"
    return allowed


def _percent_decoded_variants(value: str) -> tuple[str, ...]:
    current = value
    variants = [value]
    for _ in range(MAX_PERCENT_DECODE_DEPTH):
        decoded = unquote(current)
        if decoded == current:
            return tuple(variants)
        variants.append(decoded)
        current = decoded
    if unquote(current) != current:
        raise ValueError("benchmark v2 public leakage failure: percent decode depth bound exceeded")
    return tuple(variants)


def _looks_like_path(value: str, key_name: str) -> bool:
    lowered_key = key_name.casefold()
    if lowered_key == "path" or lowered_key.endswith("_path"):
        return True
    for decoded in _percent_decoded_variants(value):
        if decoded.startswith(("/", "\\\\")) or "\\" in decoded or _DRIVE_RE.match(decoded) or _URI_RE.match(decoded):
            return True
        if any(part in {".", ".."} for part in decoded.replace("\\", "/").split("/")):
            return True
        if "/" in decoded and _RELATIVE_FILE_RE.search(decoded) is not None:
            return True
    return False


def scan_benchmark_v2_public_value(value: object) -> None:
    """Fail closed when a public value contains private evidence or path leakage."""

    allowed = _provider_path_exceptions(value)
    allowed.update(_score_ref_path_exceptions(value))
    state = {"nodes": 0, "decoded_bytes": 0}
    decoder = json.JSONDecoder()

    def fail(reason: str) -> None:
        raise ValueError(f"benchmark v2 public leakage failure: {reason}")

    def visit(item: object, *, path: tuple[object, ...], depth: int, decode_depth: int, key_name: str = "") -> None:
        state["nodes"] += 1
        if state["nodes"] > MAX_VISITED_NODES:
            fail("visited node bound exceeded")
        if isinstance(item, (Mapping, list)) and depth > MAX_CONTAINER_DEPTH:
            fail("container depth bound exceeded")
        if isinstance(item, Mapping):
            for key in sorted(item, key=lambda child: str(child)):
                if not isinstance(key, str):
                    fail("mapping key is not text")
                visit(key, path=path + (key, "<key>"), depth=depth + 1, decode_depth=decode_depth)
                lowered = key.casefold()
                if lowered in _FORBIDDEN_FIELDS:
                    fail("forbidden field name")
                child = item[key]
                child_path = path + (key,)
                if key == "canonical_bytes_b64" or key.endswith("_bytes_b64"):
                    if not isinstance(child, str):
                        fail("encoded envelope is not text")
                    state["nodes"] += 1
                    if state["nodes"] > MAX_VISITED_NODES:
                        fail("visited node bound exceeded")
                    if len(child.encode("utf-8")) > MAX_STRING_UTF8_BYTES:
                        fail("string byte bound exceeded")
                    if decode_depth >= MAX_BASE64_DECODE_DEPTH:
                        fail("base64 decode depth bound exceeded")
                    try:
                        raw = base64.b64decode(child, validate=True)
                    except (ValueError, binascii.Error) as error:
                        raise ValueError("benchmark v2 public leakage failure: invalid base64 envelope") from error
                    if base64.b64encode(raw).decode("ascii") != child:
                        fail("noncanonical base64 envelope")
                    state["decoded_bytes"] += len(raw)
                    if state["decoded_bytes"] > MAX_DECODED_BYTES:
                        fail("decoded byte bound exceeded")
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise ValueError("benchmark v2 public leakage failure: decoded envelope is not UTF-8") from error
                    visit_decoded_text(text, path=child_path, depth=depth + 1, decode_depth=decode_depth + 1)
                else:
                    visit(child, path=child_path, depth=depth + 1, decode_depth=decode_depth, key_name=key)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, path=path + (index,), depth=depth + 1, decode_depth=decode_depth, key_name=key_name)
        elif isinstance(item, str):
            raw_size = len(item.encode("utf-8"))
            if raw_size > MAX_STRING_UTF8_BYTES:
                fail("string byte bound exceeded")
            variants = _percent_decoded_variants(item)
            if any(fragment in variant.casefold() for variant in variants for fragment in _FORBIDDEN_TEXT):
                fail("forbidden text fragment")
            exception = allowed.get(path)
            if _looks_like_path(item, key_name) and exception != item:
                fail("filesystem or logical path")
        elif item is not None and type(item) not in {bool, int, float}:
            fail("non-JSON value")

    def visit_decoded_text(text: str, *, path: tuple[object, ...], depth: int, decode_depth: int) -> None:
        if len(text.encode("utf-8")) > MAX_STRING_UTF8_BYTES:
            fail("decoded string byte bound exceeded")
        stripped = text.lstrip()
        if stripped:
            try:
                parsed, end = decoder.raw_decode(stripped)
            except json.JSONDecodeError:
                visit(text, path=path, depth=depth, decode_depth=decode_depth)
                return
            if stripped[end:].strip():
                fail("trailing JSON data")
            visit(parsed, path=path, depth=depth, decode_depth=decode_depth)
            return
        visit(text, path=path, depth=depth, decode_depth=decode_depth)

    visit(value, path=(), depth=0, decode_depth=0)


def _reject_s3_score_leakage(value: object) -> None:
    forbidden_keys = {"target_id", "label", "goal", "acceptable_regions", "reviewer", "annotator", "artifact_inventory", "error", "errors", "error_text", "error_message", "screenshot", "screenshot_path", "path", "gold", "gold_ref", "gold_records", "private_path", "private_manifest_path", "inventory"}

    def scan(item: object) -> None:
        if isinstance(item, Mapping):
            lowered = {str(key).casefold() for key in item}
            if forbidden_keys & lowered:
                raise ValueError("private scorer artifact leaks private evidence")
            for child in item.values():
                scan(child)
        elif isinstance(item, list):
            for child in item:
                scan(child)
        elif isinstance(item, str):
            lowered = item.casefold()
            normalized = lowered.replace("\\", "/")
            if lowered.startswith(("file:", "/", "\\\\")) or (len(item) >= 3 and item[0].isalpha() and item[1] == ":" and item[2] in "\\/"):
                raise ValueError("private scorer artifact leaks an absolute path")
            safe_score_ref = re.fullmatch(r"private-score(?:-final)?/[0-9a-f]{64}", normalized) is not None
            path_component = re.search(r"(?<![a-z0-9_-])(?:private|gold|errors?)(?=$|[/\.\s:=;,\)\]}])", normalized) is not None
            if not safe_score_ref and path_component:
                raise ValueError("private scorer artifact leaks private evidence")

    scan(value)


def validate_private_scorer_input_binding_v1(value: object) -> dict[str, object]:
    fields = {"contract_version", "benchmark_release_id", "partition", "private_manifest_ref", "corpus_parent_ref", "provider_manifest_ref", "provider_corpus_ref", "accepted_run_ref", "attempt_ref", "attempt_ledger_ref", "automatic_prediction_ref", "selected_lifecycle_ref", "estimand_ref", "gate_ref", "safety"}
    binding = _closed(value, fields, "private scorer input binding")
    if binding["contract_version"] != "private_scorer_input_binding_v1" or binding["benchmark_release_id"] != BENCHMARK_RELEASE_ID or binding["partition"] != "regression" or binding["safety"] != SAFETY:
        raise ValueError("private scorer input binding invalid")
    schemas = (("private_manifest_ref", {"contract_version", "file_sha256", "content_sha256"}), ("corpus_parent_ref", {"contract_version", "artifact_id", "file_sha256", "content_sha256"}), ("provider_manifest_ref", {"contract_version", "relative_path", "file_sha256"}), ("provider_corpus_ref", {"contract_version", "relative_path", "file_sha256", "content_sha256", "source_parent_ref"}), ("accepted_run_ref", {"contract_version", "file_sha256", "content_sha256"}), ("estimand_ref", {"contract_version", "file_sha256"}), ("gate_ref", {"contract_version", "file_sha256"}))
    for name, schema in schemas:
        if not isinstance(binding[name], Mapping) or set(binding[name]) != schema:
            raise ValueError("private scorer input binding ref invalid")
        for key, child in binding[name].items():
            if key.endswith("sha256") and not _is_sha(child):
                raise ValueError("private scorer input binding SHA invalid")
    if binding["accepted_run_ref"]["contract_version"] != "benchmark_v2_accepted_regression_score_input_v2":
        raise ValueError("private scorer accepted ref invalid")
    for name in ("attempt_ref", "attempt_ledger_ref", "automatic_prediction_ref", "selected_lifecycle_ref"):
        _exact_ref(binding[name], name)
    _reject_s3_score_leakage(binding)
    scan_benchmark_v2_public_value(binding)
    return binding


def validate_private_scorer_public_ref_v3(public: object) -> dict[str, object]:
    fields = {"status", "score_ref", "content_sha256", "contract_version", "score_input_binding", "binding", "launch_receipt", "cleanup_receipt", "safety"}
    _reject_s3_score_leakage(public)
    try:
        scan_benchmark_v2_public_value(public)
    except ValueError as error:
        raise ValueError("private scorer public leakage failure") from error
    if not isinstance(public, Mapping) or set(public) != fields or public["contract_version"] != "private_scorer_public_ref_v3" or public.get("status") not in {"PASS", "FAIL"} or public["safety"] != SAFETY or not _is_sha(public.get("content_sha256")) or public["content_sha256"] != content_sha256({key: child for key, child in public.items() if key != "content_sha256"}):
        raise ValueError("private scorer public chain invalid")
    decoded = []
    for name, contract, kind in (("launch_receipt", "private_scorer_launch_receipt_v2", "private-scorer-launch"), ("cleanup_receipt", "private_scorer_cleanup_receipt_v1", "private-scorer-cleanup")):
        envelope = public[name]
        if not isinstance(envelope, Mapping) or set(envelope) != {"ref", "canonical_bytes_b64"}:
            raise ValueError("private scorer receipt envelope invalid")
        try:
            raw = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
            if base64.b64encode(raw).decode("ascii") != envelope["canonical_bytes_b64"]:
                raise ValueError("noncanonical base64")
            receipt = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as error:
            raise ValueError("private scorer receipt encoding invalid") from error
        _reject_s3_score_leakage(receipt)
        digest = receipt.get("content_sha256") if name == "launch_receipt" else sha256_bytes(raw)
        if canonical_bytes(receipt) != raw or envelope["ref"] != {"id": f"{kind}/{digest}", "content_sha256": digest} or receipt.get("contract_version") != contract or receipt.get("safety") != SAFETY:
            raise ValueError("private scorer receipt invalid")
        if name == "launch_receipt" and digest != content_sha256({key: child for key, child in receipt.items() if key != "content_sha256"}):
            raise ValueError("private scorer receipt invalid")
        decoded.append(receipt)
    launch, cleanup = decoded
    binding = public["binding"]
    score_input_binding = validate_private_scorer_input_binding_v1(public["score_input_binding"])
    child_score = binding.get("child_score_ref") if isinstance(binding, Mapping) else None
    launch_fields = {"contract_version", "launcher_process_id", "launcher_process_identity", "child_process_id", "child_process_identity", "pipe_capability_sha256", "argv_sha256", "env_sha256", "cwd_sha256", "job_identity_sha256", "child_execution_receipt_sha256", "child_score_ref", "score_input_binding", "safety", "content_sha256"}
    cleanup_fields = {"contract_version", "launch_receipt_ref", "child_returncode", "job_active_processes_after", "job_stable_zero", "pipe_handles_closed", "process_pipes_closed", "job_handle_closed", "safety"}
    sha_fields = ("pipe_capability_sha256", "argv_sha256", "env_sha256", "cwd_sha256", "job_identity_sha256", "child_execution_receipt_sha256")
    binding_fields = {"contract_version", "child_score_ref", "score_input_binding", "launch_receipt_ref", "cleanup_receipt_ref", "safety", "content_sha256"}
    if set(launch) != launch_fields or set(cleanup) != cleanup_fields or not isinstance(launch.get("launcher_process_id"), int) or not isinstance(launch.get("child_process_id"), int) or launch["launcher_process_id"] <= 0 or launch["child_process_id"] <= 0 or launch["launcher_process_id"] == launch["child_process_id"] or any(not _is_sha(launch.get(key)) for key in sha_fields) or not isinstance(child_score, Mapping) or set(child_score) != {"status", "score_ref", "content_sha256"} or child_score.get("status") not in {"PASS", "FAIL"} or not _is_sha(child_score.get("content_sha256")) or not isinstance(child_score.get("score_ref"), str) or re.fullmatch(r"private-score/[0-9a-f]{64}", child_score["score_ref"]) is None or launch["child_score_ref"] != child_score or not isinstance(binding, Mapping) or set(binding) != binding_fields or binding.get("contract_version") != "private_scorer_final_binding_v2" or binding.get("child_score_ref") != child_score or binding.get("score_input_binding") != score_input_binding or launch.get("score_input_binding") != score_input_binding or binding.get("launch_receipt_ref") != public["launch_receipt"]["ref"] or binding.get("cleanup_receipt_ref") != public["cleanup_receipt"]["ref"] or binding.get("safety") != SAFETY or not _is_sha(binding.get("content_sha256")) or binding.get("content_sha256") != content_sha256({key: child for key, child in binding.items() if key != "content_sha256"}) or cleanup.get("launch_receipt_ref") != public["launch_receipt"]["ref"] or cleanup.get("child_returncode") != 0 or cleanup.get("job_active_processes_after") != 0 or any(cleanup.get(key) is not True for key in ("job_stable_zero", "pipe_handles_closed", "process_pipes_closed", "job_handle_closed")):
        raise ValueError("private scorer launch/cleanup chain invalid")
    expected = {"status": binding["child_score_ref"]["status"], "score_ref": f"private-score-final/{binding['content_sha256']}", "content_sha256": public["content_sha256"]}
    if any(public[key] != child for key, child in expected.items()):
        raise ValueError("private scorer final ref invalid")
    return dict(public)
