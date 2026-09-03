"""Canonical, non-authorizing goal-binding evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math


_CONTRACT_VERSION = "goal_binding_provider_result_v1"
_COORDINATE_SPACES = frozenset({"normalized_0_1", "normalized_0_1000", "capture_pixels"})
_RESULT_FIELDS = frozenset(
    {
        "contract_version",
        "goal_index",
        "candidate_index",
        "candidate_id",
        "status",
        "binding_basis",
        "confidence",
        "canonical_capture_pixel_point",
        "provider_id",
        "native_output_ref",
        "omni_snapshot_ref",
        "capture_ref",
        "artifact_is_authorization",
    }
)


@dataclass(frozen=True)
class NativePointProposal:
    goal_index: int
    point: tuple[float, float] | None
    coordinate_space: str
    confidence: float | None
    status: str
    failure_reason: str | None


def _is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _require_number(value: object, *, field: str, low: float, high: float) -> float:
    if not _is_finite_number(value):
        raise ValueError(f"{field} must be finite")
    result = float(value)
    if not low <= result <= high:
        raise ValueError(f"{field} is outside allowed range")
    return result


def _require_image_size(value: object) -> tuple[int, int]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(isinstance(part, bool) or not isinstance(part, int) or part <= 0 for part in value)
    ):
        raise ValueError("image_size is invalid")
    return value


def _require_ref(value: object, *, field: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "sha256"}:
        raise ValueError(f"{field} lineage is invalid")
    identifier, digest = value["id"], value["sha256"]
    if (
        not isinstance(identifier, str)
        or not identifier.strip()
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field} lineage is invalid")
    return {"id": identifier, "sha256": digest}


def _require_provider_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("provider_id is invalid")
    return value


def _provider_failure(
    *,
    goal_index: int,
    provider_id: str,
    native_output_ref: dict[str, str],
    omni_snapshot_ref: dict[str, str],
    capture_ref: dict[str, str],
) -> dict[str, object]:
    return _result(
        goal_index=goal_index,
        candidate_index=None,
        candidate_id=None,
        status="PROVIDER_FAILURE",
        binding_basis="native_point",
        confidence=None,
        point=None,
        provider_id=provider_id,
        native_output_ref=native_output_ref,
        omni_snapshot_ref=omni_snapshot_ref,
        capture_ref=capture_ref,
    )


def _result(
    *,
    goal_index: int,
    candidate_index: int | None,
    candidate_id: str | None,
    status: str,
    binding_basis: str,
    confidence: float | None,
    point: tuple[float, float] | None,
    provider_id: str,
    native_output_ref: dict[str, str],
    omni_snapshot_ref: dict[str, str],
    capture_ref: dict[str, str],
) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": _CONTRACT_VERSION,
        "goal_index": goal_index,
        "candidate_index": candidate_index,
        "candidate_id": candidate_id,
        "status": status,
        "binding_basis": binding_basis,
        "confidence": confidence,
        "canonical_capture_pixel_point": list(point) if point is not None else None,
        "provider_id": provider_id,
        "native_output_ref": native_output_ref,
        "omni_snapshot_ref": omni_snapshot_ref,
        "capture_ref": capture_ref,
        "artifact_is_authorization": False,
    }
    return validate_goal_binding_provider_result(value)


def _validated_candidates(
    candidates: Sequence[Mapping[str, object]], *, image_size: tuple[int, int]
) -> list[Mapping[str, object]]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("candidates are invalid")
    width, height = image_size
    seen_ids: set[str] = set()
    validated: list[Mapping[str, object]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"candidate[{index}] is invalid")
        candidate_id = candidate.get("candidate_id")
        bbox = candidate.get("bbox_original")
        active = candidate.get("active")
        if not isinstance(candidate_id, str) or not candidate_id.strip() or candidate_id in seen_ids:
            raise ValueError(f"candidate[{index}] identity is invalid")
        if not isinstance(active, bool) or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise ValueError(f"candidate[{index}] geometry is invalid")
        x1, y1, x2, y2 = (
            _require_number(part, field=f"candidate[{index}] geometry", low=0.0, high=float(max(width, height)))
            for part in bbox
        )
        if not x1 < x2 <= width or not y1 < y2 <= height:
            raise ValueError(f"candidate[{index}] geometry is invalid")
        seen_ids.add(candidate_id)
        validated.append(candidate)
    return validated


def _proposal_goal_index(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("proposal goal_index is invalid")
    return value


def _capture_point(
    point: object, *, coordinate_space: str, image_size: tuple[int, int]
) -> tuple[float, float]:
    if not isinstance(point, tuple) or len(point) != 2:
        raise ValueError("proposal point is invalid")
    width, height = image_size
    if coordinate_space == "normalized_0_1":
        x = _require_number(point[0], field="normalized x", low=0.0, high=1.0) * width
        y = _require_number(point[1], field="normalized y", low=0.0, high=1.0) * height
    elif coordinate_space == "normalized_0_1000":
        x = _require_number(point[0], field="normalized x", low=0.0, high=1000.0) * width / 1000.0
        y = _require_number(point[1], field="normalized y", low=0.0, high=1000.0) * height / 1000.0
    else:
        x = _require_number(point[0], field="capture x", low=0.0, high=float(width))
        y = _require_number(point[1], field="capture y", low=0.0, high=float(height))
    if not 0.0 <= x < width or not 0.0 <= y < height:
        raise ValueError("proposal point is outside capture")
    return x, y


def map_native_point_to_candidate(
    *,
    proposal: NativePointProposal,
    image_size: tuple[int, int],
    candidates: Sequence[Mapping[str, object]],
    provider_id: str,
    capture_ref: Mapping[str, str],
    native_output_ref: Mapping[str, str],
    omni_snapshot_ref: Mapping[str, str],
) -> dict[str, object]:
    """Map one provider-native point to exactly one active frozen candidate."""
    image_size = _require_image_size(image_size)
    provider_id = _require_provider_id(provider_id)
    capture_ref = _require_ref(capture_ref, field="capture_ref")
    native_output_ref = _require_ref(native_output_ref, field="native_output_ref")
    omni_snapshot_ref = _require_ref(omni_snapshot_ref, field="omni_snapshot_ref")
    candidates = _validated_candidates(candidates, image_size=image_size)
    if not isinstance(proposal, NativePointProposal):
        raise ValueError("proposal is invalid")
    goal_index = _proposal_goal_index(proposal.goal_index)
    if (
        not isinstance(proposal.coordinate_space, str)
        or proposal.coordinate_space not in _COORDINATE_SPACES
    ):
        raise ValueError("coordinate_space is unsupported")
    if proposal.status == "PROVIDER_FAILURE":
        return _provider_failure(
            goal_index=goal_index,
            provider_id=provider_id,
            native_output_ref=native_output_ref,
            omni_snapshot_ref=omni_snapshot_ref,
            capture_ref=capture_ref,
        )
    if proposal.status != "OK":
        return _provider_failure(
            goal_index=goal_index,
            provider_id=provider_id,
            native_output_ref=native_output_ref,
            omni_snapshot_ref=omni_snapshot_ref,
            capture_ref=capture_ref,
        )
    try:
        confidence = (
            None
            if proposal.confidence is None
            else _require_number(proposal.confidence, field="proposal confidence", low=0.0, high=1.0)
        )
        point = _capture_point(
            proposal.point, coordinate_space=proposal.coordinate_space, image_size=image_size
        )
    except ValueError:
        return _provider_failure(
            goal_index=goal_index,
            provider_id=provider_id,
            native_output_ref=native_output_ref,
            omni_snapshot_ref=omni_snapshot_ref,
            capture_ref=capture_ref,
        )
    hits: list[tuple[int, Mapping[str, object]]] = []
    for candidate_index, candidate in enumerate(candidates):
        if not candidate["active"]:
            continue
        x1, y1, x2, y2 = candidate["bbox_original"]  # type: ignore[misc]
        if x1 < point[0] < x2 and y1 < point[1] < y2:
            hits.append((candidate_index, candidate))
    if len(hits) != 1:
        return _result(
            goal_index=goal_index,
            candidate_index=None,
            candidate_id=None,
            status="UNBOUND",
            binding_basis="native_point",
            confidence=confidence,
            point=point,
            provider_id=provider_id,
            native_output_ref=native_output_ref,
            omni_snapshot_ref=omni_snapshot_ref,
            capture_ref=capture_ref,
        )
    candidate_index, candidate = hits[0]
    return _result(
        goal_index=goal_index,
        candidate_index=candidate_index,
        candidate_id=candidate["candidate_id"],  # type: ignore[arg-type]
        status="BOUND",
        binding_basis="native_point",
        confidence=confidence,
        point=point,
        provider_id=provider_id,
        native_output_ref=native_output_ref,
        omni_snapshot_ref=omni_snapshot_ref,
        capture_ref=capture_ref,
    )


def validate_goal_binding_provider_result(value: object) -> dict[str, object]:
    """Validate and copy the closed runtime-owned binding evidence contract."""
    if not isinstance(value, Mapping) or set(value) != _RESULT_FIELDS:
        raise ValueError("goal binding provider result is not closed")
    if value["contract_version"] != _CONTRACT_VERSION:
        raise ValueError("goal binding provider result version is invalid")
    goal_index = _proposal_goal_index(value["goal_index"])
    status = value["status"]
    binding_basis = value["binding_basis"]
    if status not in {"BOUND", "UNBOUND", "PROVIDER_FAILURE"}:
        raise ValueError("goal binding provider result status is invalid")
    if binding_basis not in {"native_point", "direct_candidate_index"}:
        raise ValueError("goal binding provider result binding_basis is invalid")
    candidate_index, candidate_id, point = (
        value["candidate_index"],
        value["candidate_id"],
        value["canonical_capture_pixel_point"],
    )
    if value["artifact_is_authorization"] is not False:
        raise ValueError("goal binding provider result must be non-authorizing")
    if not isinstance(value["provider_id"], str) or not value["provider_id"].strip():
        raise ValueError("goal binding provider result provider_id is invalid")
    confidence = value["confidence"]
    if confidence is not None:
        confidence = _require_number(confidence, field="result confidence", low=0.0, high=1.0)
    lineage = {
        "native_output_ref": _require_ref(value["native_output_ref"], field="native_output_ref"),
        "omni_snapshot_ref": _require_ref(value["omni_snapshot_ref"], field="omni_snapshot_ref"),
        "capture_ref": _require_ref(value["capture_ref"], field="capture_ref"),
    }
    if status == "BOUND":
        if isinstance(candidate_index, bool) or not isinstance(candidate_index, int) or candidate_index < 0:
            raise ValueError("bound result candidate_index is invalid")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ValueError("bound result candidate_id is invalid")
        if binding_basis == "native_point":
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("native_point bound result point is invalid")
            canonical_point = [
                _require_number(part, field="canonical capture point", low=0.0, high=float("inf"))
                for part in point
            ]
        else:
            if point is not None:
                raise ValueError("direct_candidate_index must not invent a canonical point")
            canonical_point = None
    else:
        if binding_basis != "native_point":
            raise ValueError("only bound results may use direct_candidate_index")
        if candidate_index is not None or candidate_id is not None:
            raise ValueError("unbound or provider failure result carries a candidate")
        if status == "PROVIDER_FAILURE":
            if point is not None:
                raise ValueError("provider failure result carries a point")
            canonical_point = None
        else:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("unbound native_point result point is invalid")
            canonical_point = [
                _require_number(part, field="canonical capture point", low=0.0, high=float("inf"))
                for part in point
            ]
    return {
        "contract_version": _CONTRACT_VERSION,
        "goal_index": goal_index,
        "candidate_index": candidate_index,
        "candidate_id": candidate_id,
        "status": status,
        "binding_basis": binding_basis,
        "confidence": confidence,
        "canonical_capture_pixel_point": canonical_point,
        "provider_id": value["provider_id"],
        "native_output_ref": lineage["native_output_ref"],
        "omni_snapshot_ref": lineage["omni_snapshot_ref"],
        "capture_ref": lineage["capture_ref"],
        "artifact_is_authorization": False,
    }
