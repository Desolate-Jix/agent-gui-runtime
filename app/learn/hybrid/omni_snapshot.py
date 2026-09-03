"""Create and verify the sealed, regression-only Omni candidate snapshot."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

from app.learn.hybrid.simple_native_contracts import parse_omni_native_output
from app.learn.hybrid.simple_native_smoke import (
    OmniNativeCaller,
    ProviderCase,
    _prepare_capture,
    _verify_capture_freshness,
    build_omni_evidence_from_native,
)


_CASE_IDS = tuple(f"case-{index:03d}" for index in range(1, 6))
_IDENTITY_KEYS = frozenset({"provider_id", "profile_id", "model_revision", "preprocessing_revision"})
_FORBIDDEN_KEYS = frozenset({"gold", "holdout", "action_authority", "click_authority", "review_authority"})


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _value_sha256(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _read_canonical_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, dict) or raw != _canonical_bytes(decoded):
        raise ValueError(f"{label} is not canonical JSON")
    return decoded


def _validate_cases(cases: Sequence[ProviderCase]) -> tuple[ProviderCase, ...]:
    normalized = tuple(cases)
    if len(normalized) != 5 or tuple(case.case_id for case in normalized) != _CASE_IDS:
        raise ValueError("Omni snapshot requires exactly case-001 through case-005")
    if sum(len(case.goals) for case in normalized) != 25:
        raise ValueError("Omni snapshot requires exactly 25 goals")
    return normalized


def _validate_provider_identity(identity: Mapping[str, object]) -> dict[str, object]:
    copied = deepcopy(dict(identity))
    if set(copied) != _IDENTITY_KEYS or not all(isinstance(copied[key], str) and copied[key] for key in _IDENTITY_KEYS):
        raise ValueError("Omni snapshot provider identity is incomplete")
    _reject_authority_fields(copied, label="provider identity")
    return copied


def _reject_authority_fields(value: object, *, label: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"{label} includes forbidden authority field")
            _reject_authority_fields(nested, label=label)
    elif isinstance(value, list):
        for nested in value:
            _reject_authority_fields(nested, label=label)


def _native_text(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    return _canonical_bytes(raw).decode("utf-8")


def _candidate_geometry(candidates: list[object]) -> list[dict[str, object]]:
    geometry: list[dict[str, object]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("Omni snapshot candidate is invalid")
        candidate_id = candidate.get("candidate_id")
        bbox = candidate.get("bbox_original")
        active = candidate.get("active")
        if (
            not isinstance(candidate_id, str)
            or not isinstance(bbox, list)
            or len(bbox) != 4
            or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
            or not isinstance(active, bool)
        ):
            raise ValueError("Omni snapshot candidate geometry is invalid")
        geometry.append({"candidate_id": candidate_id, "bbox_original": list(bbox), "active": active})
    return geometry


def _candidate_payload(
    *, case: ProviderCase, capture: Mapping[str, object], inventory: Mapping[str, object], native_file: str, native_file_sha256: str,
    native_output_sha256: str,
) -> dict[str, object]:
    candidates = inventory.get("candidates")
    content_sha256 = inventory.get("content_sha256")
    if not isinstance(candidates, list) or not isinstance(content_sha256, str):
        raise ValueError("Omni canonical inventory is invalid")
    copied_candidates = deepcopy(candidates)
    _candidate_geometry(copied_candidates)
    return {
        "contract_version": "omni_snapshot_candidates_v1",
        "case_id": case.case_id,
        "capture": {
            "capture_id": capture["capture_id"],
            "screenshot_sha256": capture["screenshot_sha256"],
            "image_size": deepcopy(capture["image_size"]),
            "capture_lineage_ref": deepcopy(capture["bundle"]["capture_lineage_ref"]),
        },
        "native_output_file": native_file,
        "native_output_file_sha256": native_file_sha256,
        "native_output_sha256": native_output_sha256,
        "canonical_inventory_sha256": content_sha256,
        "candidates": copied_candidates,
        "artifact_is_authorization": False,
    }


def _manifest_content_sha256(manifest: Mapping[str, object]) -> str:
    sealed = deepcopy(dict(manifest))
    sealed.pop("content_sha256", None)
    return _value_sha256(sealed)


def _aggregate_sha256(records: list[dict[str, object]]) -> str:
    return _value_sha256(records)


def create_omni_snapshot(
    *, cases: Sequence[ProviderCase], omni: OmniNativeCaller, output_dir: Path,
    provider_identity: Mapping[str, object],
) -> Path:
    """Run Omni once per configured capture and seal its shared candidate inventory."""
    validated_cases = _validate_cases(cases)
    identity = _validate_provider_identity(provider_identity)
    snapshot_dir = output_dir.resolve()
    manifest_path = snapshot_dir / "manifest.json"
    if manifest_path.exists():
        raise ValueError("Omni snapshot manifest already exists")
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for case in validated_cases:
        capture = _prepare_capture(case, snapshot_dir)
        capture_path = _verify_capture_freshness(capture, "Omni snapshot")
        raw = omni(capture_path)
        _verify_capture_freshness(capture, "Omni snapshot")
        native_text = _native_text(raw)
        native_payload = {
            "contract_version": "omni_snapshot_native_output_v1",
            "case_id": case.case_id,
            "raw_utf8": native_text,
            "raw_output_sha256": _sha256_bytes(native_text.encode("utf-8")),
            "artifact_is_authorization": False,
        }
        native_file = f"{case.case_id}.native.json"
        native_path = snapshot_dir / native_file
        native_path.write_bytes(_canonical_bytes(native_payload))
        native_file_sha256 = _sha256_bytes(native_path.read_bytes())
        parsed = parse_omni_native_output(raw)
        evidence = build_omni_evidence_from_native(
            case=case, capture=capture, parsed=parsed, artifact_dir=snapshot_dir
        )
        inventory = evidence["inventory"]
        if not isinstance(inventory, Mapping):
            raise ValueError("Omni canonical inventory is unavailable")
        candidate_file = f"{case.case_id}.candidates.json"
        payload = _candidate_payload(
            case=case,
            capture=capture,
            inventory=inventory,
            native_file=native_file,
            native_file_sha256=native_file_sha256,
            native_output_sha256=native_payload["raw_output_sha256"],
        )
        candidate_path = snapshot_dir / candidate_file
        candidate_path.write_bytes(_canonical_bytes(payload))
        candidate_file_sha256 = _sha256_bytes(candidate_path.read_bytes())
        candidates = payload["candidates"]
        assert isinstance(candidates, list)
        candidate_ids = [candidate["candidate_id"] for candidate in candidates if isinstance(candidate, Mapping)]
        if len(candidate_ids) != len(candidates):
            raise ValueError("Omni snapshot candidate order is invalid")
        geometry = _candidate_geometry(candidates)
        records.append({
            "case_id": case.case_id,
            "screenshot_path": str(case.image_path.resolve()),
            "image_size": {"width": case.image_size[0], "height": case.image_size[1]},
            "capture_sha256": case.image_sha256,
            "capture_id": capture["capture_id"],
            "capture_lineage_sha256": _value_sha256(capture["bundle"]["capture_lineage_ref"]),
            "native_output_file": native_file,
            "native_output_file_sha256": native_file_sha256,
            "native_output_sha256": native_payload["raw_output_sha256"],
            "candidate_file": candidate_file,
            "candidate_file_sha256": candidate_file_sha256,
            "canonical_inventory_sha256": payload["canonical_inventory_sha256"],
            "candidate_ids": candidate_ids,
            "candidate_order_sha256": _value_sha256(candidate_ids),
            "candidate_geometry_sha256": _value_sha256(geometry),
        })
    manifest: dict[str, object] = {
        "contract_version": "omni_snapshot_v1",
        "provider_identity": identity,
        "provider_identity_sha256": _value_sha256(identity),
        "regression_only": True,
        "contains_holdout": False,
        "artifact_is_authorization": False,
        "screen_count": 5,
        "target_count": 25,
        "cases": records,
        "aggregate_snapshot_sha256": _aggregate_sha256(records),
    }
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    manifest_path.write_bytes(_canonical_bytes(manifest))
    return manifest_path


def _verify_expected_case(record: Mapping[str, object], case: ProviderCase) -> None:
    if record.get("case_id") != case.case_id:
        raise ValueError("Omni snapshot case order mismatch")
    if record.get("screenshot_path") != str(case.image_path.resolve()):
        raise ValueError("Omni snapshot capture path mismatch")
    if record.get("capture_sha256") != case.image_sha256:
        raise ValueError("Omni snapshot capture sha256 mismatch")
    if record.get("image_size") != {"width": case.image_size[0], "height": case.image_size[1]}:
        raise ValueError("Omni snapshot capture geometry mismatch")
    if not case.image_path.is_file() or _sha256_bytes(case.image_path.read_bytes()) != case.image_sha256:
        raise ValueError("Omni snapshot expected capture sha256 mismatch")


def _verify_case_files(snapshot_dir: Path, record: Mapping[str, object]) -> dict[str, object]:
    native_file = record.get("native_output_file")
    candidate_file = record.get("candidate_file")
    if not isinstance(native_file, str) or not isinstance(candidate_file, str):
        raise ValueError("Omni snapshot case files are invalid")
    native_path = snapshot_dir / native_file
    candidate_path = snapshot_dir / candidate_file
    if _sha256_bytes(native_path.read_bytes()) != record.get("native_output_file_sha256"):
        raise ValueError("Omni snapshot native file sha256 mismatch")
    if _sha256_bytes(candidate_path.read_bytes()) != record.get("candidate_file_sha256"):
        raise ValueError("Omni snapshot candidate file sha256 mismatch")
    native = _read_canonical_json(native_path, label="Omni snapshot native file")
    candidates_file = _read_canonical_json(candidate_path, label="Omni snapshot candidate file")
    native_text = native.get("raw_utf8")
    if (
        not isinstance(native_text, str)
        or _sha256_bytes(native_text.encode("utf-8")) != native.get("raw_output_sha256")
        or native.get("raw_output_sha256") != record.get("native_output_sha256")
    ):
        raise ValueError("Omni snapshot native output sha256 mismatch")
    if native.get("artifact_is_authorization") is not False or candidates_file.get("artifact_is_authorization") is not False:
        raise ValueError("Omni snapshot artifact authority is invalid")
    if candidates_file.get("case_id") != record.get("case_id"):
        raise ValueError("Omni snapshot candidate case mismatch")
    if candidates_file.get("native_output_file") != native_file or candidates_file.get("native_output_file_sha256") != record.get("native_output_file_sha256"):
        raise ValueError("Omni snapshot native reference mismatch")
    candidates = candidates_file.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Omni snapshot candidate file is invalid")
    geometry = _candidate_geometry(candidates)
    ids = [item["candidate_id"] for item in candidates if isinstance(item, Mapping)]
    if ids != record.get("candidate_ids") or _value_sha256(ids) != record.get("candidate_order_sha256"):
        raise ValueError("Omni snapshot candidate order mismatch")
    if _value_sha256(geometry) != record.get("candidate_geometry_sha256"):
        raise ValueError("Omni snapshot candidate geometry mismatch")
    capture = candidates_file.get("capture")
    if not isinstance(capture, Mapping) or capture.get("screenshot_sha256") != record.get("capture_sha256"):
        raise ValueError("Omni snapshot candidate capture mismatch")
    if candidates_file.get("canonical_inventory_sha256") != record.get("canonical_inventory_sha256"):
        raise ValueError("Omni snapshot canonical inventory mismatch")
    return {"case_id": record["case_id"], "capture": deepcopy(dict(capture)), "candidates": deepcopy(candidates), "candidate_file": str(candidate_path)}


def load_verified_omni_snapshot(
    path: Path, *, expected_cases: Sequence[ProviderCase]
) -> dict[str, object]:
    """Verify every immutable snapshot boundary without constructing or calling Omni."""
    expected = _validate_cases(expected_cases)
    manifest_path = path.resolve()
    manifest = _read_canonical_json(manifest_path, label="Omni snapshot manifest")
    identity = manifest.get("provider_identity")
    if not isinstance(identity, Mapping) or _value_sha256(identity) != manifest.get("provider_identity_sha256"):
        raise ValueError("Omni snapshot provider identity mismatch")
    _validate_provider_identity(identity)
    if (
        manifest.get("contract_version") != "omni_snapshot_v1"
        or manifest.get("regression_only") is not True
        or manifest.get("contains_holdout") is not False
        or manifest.get("artifact_is_authorization") is not False
        or manifest.get("screen_count") != 5
        or manifest.get("target_count") != 25
    ):
        raise ValueError("Omni snapshot manifest boundary is invalid")
    _reject_authority_fields(manifest, label="snapshot manifest")
    if _manifest_content_sha256(manifest) != manifest.get("content_sha256"):
        raise ValueError("Omni snapshot manifest sha256 mismatch")
    records = manifest.get("cases")
    if not isinstance(records, list) or len(records) != 5:
        raise ValueError("Omni snapshot case records are invalid")
    if _aggregate_sha256(records) != manifest.get("aggregate_snapshot_sha256"):
        raise ValueError("Omni snapshot aggregate sha256 mismatch")
    verified_cases = []
    for record, case in zip(records, expected, strict=True):
        if not isinstance(record, Mapping):
            raise ValueError("Omni snapshot case record is invalid")
        _verify_expected_case(record, case)
        verified_cases.append(_verify_case_files(manifest_path.parent, record))
    return {
        "contract_version": "omni_snapshot_v1",
        "provider_identity": deepcopy(dict(identity)),
        "snapshot_sha256": manifest["aggregate_snapshot_sha256"],
        "screen_count": 5,
        "target_count": 25,
        "cases": verified_cases,
        "regression_only": True,
        "contains_holdout": False,
        "artifact_is_authorization": False,
    }
