"""Privileged one-way projection from the frozen v1 parent into provider-safe cases."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
from typing import Any, Mapping

from app.learn.hybrid.benchmark_v2_contracts import (
    BENCHMARK_RELEASE_ID,
    PARENT_FILE_SHA256,
    PARENT_REF,
    PROVIDER_CORPUS_CONTRACT,
    SAFETY,
    canonical_json_bytes,
    content_sha256,
    sha256_bytes,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PARENT_CONTRACT = "portfolio_hybrid_v1_1_corpus_manifest_v1"
_SCREEN_FIELDS = {
    "screen_id",
    "partition",
    "path",
    "sha256",
    "width",
    "height",
    "layout_id",
    "title",
    "surface",
    "density",
    "precision_case",
    "source_kind",
    "source_provenance",
    "reviewer_identity_hash",
    "review_status",
    "privacy_review_status",
}
_TARGET_FIELDS = {
    "target_id",
    "screen_id",
    "partition",
    "role",
    "label",
    "goal",
    "bbox",
    "acceptable_candidate_ids",
    "acceptable_regions",
    "annotator_identity_hash",
    "reviewer_identity_hash",
    "acceptable_region_disagreement",
    "review_status",
    "important_target",
}


def _png_dimensions(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()[:24]
    if len(raw) != 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError(f"screenshot is not a valid PNG: {path}")
    return struct.unpack(">II", raw[16:24])


def _inside_project(relative: object) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("parent screenshot path must be a POSIX relative path")
    path = (_PROJECT_ROOT / relative).resolve()
    try:
        path.relative_to(_PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("parent screenshot path escapes the project root") from exc
    return path


def _load_frozen_parent(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if sha256_bytes(raw) != PARENT_FILE_SHA256:
        raise ValueError("parent manifest raw SHA does not match the frozen seal")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("parent manifest is not UTF-8 JSON") from exc
    if not isinstance(value, Mapping) or value.get("contract_version") != _PARENT_CONTRACT:
        raise ValueError("parent manifest contract is invalid")
    if value.get("content_sha256") != content_sha256(value):
        raise ValueError("parent manifest content SHA is invalid")
    if value.get("artifact_is_authorization") is not False:
        raise ValueError("parent manifest must remain non-authorizing")
    if value.get("execute_binding_enabled") is not False:
        raise ValueError("parent manifest must keep execution disabled")
    screens = value.get("screenshots")
    targets = value.get("gold_records")
    if not isinstance(screens, list) or len(screens) != 24:
        raise ValueError("frozen parent must contain exactly 24 screenshots")
    if not isinstance(targets, list) or len(targets) != 120:
        raise ValueError("frozen parent must contain exactly 120 targets")
    return dict(value)


def _validated_screens(parent: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    hashes: set[str] = set()
    for index, item in enumerate(parent["screenshots"], start=1):
        if not isinstance(item, Mapping) or set(item) != _SCREEN_FIELDS:
            raise ValueError("parent screenshot is not a closed record")
        screen = dict(item)
        expected_partition = "regression" if index <= 12 else "holdout"
        expected_id = f"case-{index:03d}"
        expected_path = (
            "tests/fixtures/portfolio_hybrid_v1_1/corpus/"
            f"{expected_partition}/{expected_id}.png"
        )
        if (
            screen["screen_id"] != expected_id
            or screen["partition"] != expected_partition
            or screen["path"] != expected_path
        ):
            raise ValueError("parent screenshot enumeration is invalid")
        image_path = _inside_project(screen["path"])
        if sha256_bytes(image_path.read_bytes()) != screen["sha256"]:
            raise ValueError("parent screenshot SHA mismatch")
        if _png_dimensions(image_path) != (screen["width"], screen["height"]):
            raise ValueError("parent screenshot dimensions mismatch")
        if (screen["width"], screen["height"]) != (1280, 720):
            raise ValueError("parent screenshot dimensions are outside the frozen corpus")
        if screen["source_kind"] != "privacy_safe_synthetic":
            raise ValueError("parent screenshot is not privacy safe")
        if screen["screen_id"] in result:
            raise ValueError("parent screenshot IDs must be unique")
        result[screen["screen_id"]] = screen
        paths.add(screen["path"])
        hashes.add(screen["sha256"])
    if len(paths) != 24 or len(hashes) != 24:
        raise ValueError("parent screenshot identities must be unique")
    return result


def _project_cases(
    parent: Mapping[str, Any], screens: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    identities: set[str] = set()
    target_counts: dict[str, int] = {screen_id: 0 for screen_id in screens}
    for item in parent["gold_records"]:
        if not isinstance(item, Mapping) or set(item) != _TARGET_FIELDS:
            raise ValueError("parent target is not a closed record")
        screen_id = item["screen_id"]
        target_id = item["target_id"]
        if screen_id not in screens or not isinstance(target_id, str) or not target_id:
            raise ValueError("parent target lineage is invalid")
        screen = screens[screen_id]
        if item["partition"] != screen["partition"]:
            raise ValueError("parent target partition differs from its screenshot")
        goal = item["goal"]
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("parent target lacks a safe goal")
        case_id = hashlib.sha256(
            f"benchmark-v2-case\0{screen_id}\0{target_id}".encode("utf-8")
        ).hexdigest()
        screen_group = hashlib.sha256(
            f"benchmark-v2-screen-group\0{screen_id}".encode("utf-8")
        ).hexdigest()
        if case_id in identities:
            raise ValueError("projected case identity is not unique")
        identities.add(case_id)
        target_counts[screen_id] += 1
        cases.append(
            {
                "case_id": case_id,
                "partition": screen["partition"],
                "screen_group": screen_group,
                "goal": goal,
                "image": {
                    "path": screen["path"],
                    "sha256": screen["sha256"],
                    "width": screen["width"],
                    "height": screen["height"],
                },
                "layout": {
                    "layout_id": screen["layout_id"],
                    "title": screen["title"],
                    "surface": screen["surface"],
                    "density": screen["density"],
                    "precision_case": screen["precision_case"],
                    "source_kind": screen["source_kind"],
                    "source_provenance": screen["source_provenance"],
                },
            }
        )
    if set(target_counts.values()) != {5}:
        raise ValueError("each parent screenshot must contribute exactly five targets")
    return cases


def project_provider_corpus(
    *, parent_manifest_path: Path, output_path: Path
) -> dict[str, str]:
    parent = _load_frozen_parent(Path(parent_manifest_path).resolve())
    screens = _validated_screens(parent)
    child: dict[str, Any] = {
        "contract_version": PROVIDER_CORPUS_CONTRACT,
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "source_parent_ref": dict(PARENT_REF),
        "provider_boundary": {
            "opaque_case_ids": True,
            "opaque_screen_groups": True,
            "filter_complete": True,
            "path_scope": "provider_safe_only",
        },
        "cases": _project_cases(parent, screens),
        "safety": dict(SAFETY),
    }
    child["content_sha256"] = content_sha256(child)
    raw = canonical_json_bytes(child, pretty=True)
    output = Path(output_path).resolve()
    if output == Path(parent_manifest_path).resolve():
        raise ValueError("provider output must not overwrite the parent manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "output_path": str(output),
        "file_sha256": sha256_bytes(raw),
        "content_sha256": child["content_sha256"],
    }
