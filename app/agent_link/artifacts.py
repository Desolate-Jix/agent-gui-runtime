from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

from pydantic import Field, ValidationError

from .contracts import (
    AgentLinkError,
    BatchInput,
    CandidateInput,
    GraphCandidateInput,
    GeometryChange,
    InterfacesAddChange,
    MAX_PNG_BYTES,
    RegionsAddChange,
    RelationshipChange,
    RelationshipFlowChange,
    RelationshipsAddChange,
    SemanticChange,
    ScreenshotInput,
    StepChange,
    StepFlowChange,
    StepOrderChange,
    StepsAddChange,
    StrictModel,
    validate_batch,
)

ARTIFACT_BUNDLE_VERSION = "agent_link_artifact_bundle_v1"
MAX_ARTIFACT_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_ARTIFACTS = 32
MAX_ARTIFACT_PNG_BYTES = 8 * 1024 * 1024


class ArtifactBundleError(AgentLinkError, ValueError):
    pass


def _artifact_fail(code: str, message: str) -> None:
    raise ArtifactBundleError(code, message)


class ArtifactInput(StrictModel):
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    png_base64: str = Field(min_length=1, max_length=MAX_PNG_BYTES * 2)


class ArtifactBundleInput(StrictModel):
    contract_version: Literal["agent_link_artifact_bundle_v1"]
    connection_id: str = Field(min_length=1, max_length=160)
    task_id: str = Field(min_length=1, max_length=4000)
    artifacts: list[ArtifactInput] = Field(min_length=1, max_length=MAX_ARTIFACTS)


class ScreenshotReferenceInput(StrictModel):
    screenshot_id: str = Field(min_length=1, max_length=160)
    artifact_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


BridgeScreenshotInput = ScreenshotInput | ScreenshotReferenceInput


class BridgeBatchInput(BatchInput):
    screenshots: list[BridgeScreenshotInput] = Field(max_length=32)


class BridgeInterfacesAddChange(InterfacesAddChange):
    screenshots: list[BridgeScreenshotInput] = Field(min_length=1, max_length=32)


class BridgeCandidateInput(CandidateInput):
    changes: list[
        GeometryChange | RegionsAddChange | BridgeInterfacesAddChange | StepsAddChange
        | RelationshipsAddChange | SemanticChange | RelationshipChange | StepChange
        | StepFlowChange | RelationshipFlowChange | StepOrderChange
    ] = Field(min_length=1, max_length=128)


class BridgeGraphCandidateInput(GraphCandidateInput):
    pass


@dataclass(frozen=True)
class _Artifact:
    sha256: str
    png_base64: str


@dataclass(frozen=True)
class ArtifactCatalog:
    connection_id: str
    task_id: str
    _artifacts: Mapping[str, _Artifact]

    def resolve(self, reference: ScreenshotReferenceInput | dict[str, Any]) -> dict[str, str]:
        try:
            parsed = (
                reference if isinstance(reference, ScreenshotReferenceInput)
                else ScreenshotReferenceInput.model_validate(reference)
            )
        except ValidationError:
            _artifact_fail("invalid_arguments", "artifact reference does not satisfy the contract")
        artifact = self._artifacts.get(parsed.artifact_id)
        if artifact is None:
            _artifact_fail("invalid_reference", "artifact reference is unknown")
        if artifact.sha256 != parsed.sha256:
            _artifact_fail("invalid_reference", "artifact reference digest does not match")
        return {"screenshot_id": parsed.screenshot_id, "png_base64": artifact.png_base64}


def _validate_png(artifact: ArtifactInput) -> tuple[str, str, int]:
    try:
        raw = base64.b64decode(artifact.png_base64, validate=True)
    except (ValueError, TypeError):
        _artifact_fail("invalid_png", "artifact must contain a readable PNG within limits")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != artifact.sha256:
        _artifact_fail("invalid_reference", "artifact digest does not match PNG bytes")
    dummy = {
        "contract_version": "agent_link_v1",
        "idempotency_key": "artifact-validation",
        "batch_id": "artifact-validation",
        "title": "artifact validation",
        "learning_outcome": "partial",
        "outcome_reason": "validating artifact",
        "screenshots": [{"screenshot_id": artifact.artifact_id, "png_base64": artifact.png_base64}],
        "interfaces": [], "relationships": [], "steps": [], "issues": [],
    }
    try:
        validate_batch(dummy)
    except AgentLinkError as error:
        raise ArtifactBundleError(error.code, "artifact must contain a readable PNG within limits") from error
    return artifact.artifact_id, artifact.png_base64, len(raw)


def validate_artifact_bundle(value: dict[str, Any], *, connection_id: str, task_id: str) -> ArtifactCatalog:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(encoded) > MAX_ARTIFACT_BUNDLE_BYTES:
            _artifact_fail("invalid_arguments", "artifact bundle exceeds limit")
        bundle = ArtifactBundleInput.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        _artifact_fail("invalid_arguments", "artifact bundle does not satisfy the contract")
    if bundle.connection_id != connection_id or bundle.task_id != task_id:
        _artifact_fail("invalid_reference", "artifact bundle binding does not match connection and task")
    artifacts: dict[str, _Artifact] = {}
    total_png_bytes = 0
    for item in bundle.artifacts:
        artifact_id, png_base64, size = _validate_png(item)
        if artifact_id in artifacts:
            _artifact_fail("invalid_arguments", "artifact ids must be unique")
        total_png_bytes += size
        if total_png_bytes > MAX_ARTIFACT_PNG_BYTES:
            _artifact_fail("invalid_arguments", "artifact PNG bytes exceed limit")
        artifacts[artifact_id] = _Artifact(sha256=item.sha256, png_base64=png_base64)
    return ArtifactCatalog(bundle.connection_id, bundle.task_id, MappingProxyType(artifacts))


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _artifact_fail("invalid_arguments", "artifact bundle contains duplicate JSON keys")
        value[key] = item
    return value


def load_artifact_catalog(path: Path, *, connection_id: str, task_id: str) -> ArtifactCatalog:
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_ARTIFACT_BUNDLE_BYTES + 1)
    except OSError as error:
        raise ArtifactBundleError("invalid_arguments", "artifact bundle cannot be read") from error
    if len(raw) > MAX_ARTIFACT_BUNDLE_BYTES:
        _artifact_fail("invalid_arguments", "artifact bundle exceeds limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except ArtifactBundleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _artifact_fail("invalid_arguments", "artifact bundle is not valid UTF-8 JSON")
    if not isinstance(value, dict):
        _artifact_fail("invalid_arguments", "artifact bundle must be an object")
    return validate_artifact_bundle(value, connection_id=connection_id, task_id=task_id)


def _expand_screenshot(item: BridgeScreenshotInput, catalog: ArtifactCatalog | None) -> dict[str, Any]:
    if isinstance(item, ScreenshotReferenceInput):
        if catalog is None:
            _artifact_fail("invalid_reference", "artifact catalog is required for references")
        return catalog.resolve(item)
    return item.model_dump(mode="json")


def expand_batch(batch: BridgeBatchInput, catalog: ArtifactCatalog | None) -> dict[str, Any]:
    expanded = batch.model_dump(mode="json")
    expanded["screenshots"] = [_expand_screenshot(item, catalog) for item in batch.screenshots]
    return expanded


def expand_candidate(candidate: BridgeCandidateInput | BridgeGraphCandidateInput, catalog: ArtifactCatalog | None) -> dict[str, Any]:
    expanded = candidate.model_dump(mode="json", exclude_none=True)
    for raw, change in zip(expanded["changes"], candidate.changes, strict=True):
        if isinstance(change, BridgeInterfacesAddChange):
            raw["screenshots"] = [_expand_screenshot(item, catalog) for item in change.screenshots]
    return expanded
