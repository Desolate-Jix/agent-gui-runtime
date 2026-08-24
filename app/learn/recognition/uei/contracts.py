"""Offline, dependency-free validator for the deliberately small UEI schema subset."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import math
from typing import Any


UEI_CONTRACTS = (
    "trusted_provider_registration_v1", "artifact_ref_v1", "capture_lineage_v1",
    "affine_coordinate_transform_v1", "provider_manifest_v1", "screen_parse_request_v1",
    "provider_safe_result_v1", "provider_error_v1", "provider_runtime_receipt_v1",
    "hybrid_capture_context_v1", "hybrid_capture_bundle_v1",
)
_SCHEMA_DIR = Path(__file__).resolve().parents[4] / "schemas" / "uei" / "v1"
_LOCAL_SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
_NAMESPACED_PROVIDER_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)+$")


class UEIValidationError(ValueError):
    """Raised when a value does not conform to its closed UEI contract."""


class UEIOuterBoundaryError(UEIValidationError):
    """Raised before a projection has a verified request/capture context."""


class UEIProjectionFailure(UEIValidationError):
    """Represents a safe, post-precondition projection failure."""

    def __init__(self, code: str, *, stage: str = "projection") -> None:
        super().__init__(code)
        self.code = code
        self.stage = stage


def load_contract_schema(contract_version: str) -> dict[str, Any]:
    if contract_version not in UEI_CONTRACTS:
        raise UEIValidationError(f"unknown contract_version: {contract_version}")
    local_path = _LOCAL_SCHEMA_DIR / f"{contract_version}.schema.json"
    path = local_path if local_path.is_file() else _SCHEMA_DIR / f"{contract_version}.schema.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UEIValidationError(f"unable to load schema {contract_version}: {error}") from error


def is_namespaced_provider_profile_id(value: object) -> bool:
    """Return whether a provider/profile id uses the required opaque namespace."""
    return isinstance(value, str) and len(value) <= 512 and _NAMESPACED_PROVIDER_PROFILE_ID.fullmatch(value) is not None


def _is_type(value: Any, name: str) -> bool:
    checkers = {"object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
            "string": lambda: isinstance(value, str), "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda: isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": lambda: isinstance(value, bool), "null": lambda: value is None}
    if name not in checkers:
        raise UEIValidationError(f"unsupported schema type: {name}")
    return checkers[name]()


def _reject_non_json_values(value: Any, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise UEIValidationError(f"{location}: object keys must be strings")
            _reject_non_json_values(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_non_json_values(child, f"{location}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise UEIValidationError(f"{location}: finite number required")


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any], location: str) -> None:
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/$defs/"):
            raise UEIValidationError(f"{location}: unsupported $ref")
        return _validate(value, root["$defs"][reference.rsplit("/", 1)[1]], root, location)
    if "oneOf" in schema:
        matches = 0
        for choice in schema["oneOf"]:
            try:
                _validate(value, choice, root, location)
                matches += 1
            except UEIValidationError:
                pass
        if matches != 1:
            raise UEIValidationError(f"{location}: oneOf expected exactly one match")
        return
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, item) for item in types):
            raise UEIValidationError(f"{location}: type must be {expected}")
    if "const" in schema and value != schema["const"]:
        raise UEIValidationError(f"{location}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise UEIValidationError(f"{location}: enum mismatch")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise UEIValidationError(f"{location}: required property {key} missing")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise UEIValidationError(f"{location}: additionalProperties not permitted: {sorted(unknown)!r}")
        if len(value) < schema.get("minProperties", 0) or len(value) > schema.get("maxProperties", float("inf")):
            raise UEIValidationError(f"{location}: object property count out of bounds")
        for key, child in value.items():
            if key in properties:
                _validate(child, properties[key], root, f"{location}.{key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate(child, schema["additionalProperties"], root, f"{location}.{key}")
        condition = schema.get("if")
        if condition:
            try:
                _validate(value, condition, root, location)
                branch = schema.get("then")
            except UEIValidationError:
                branch = schema.get("else")
            if branch:
                _validate(value, branch, root, location)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise UEIValidationError(f"{location}: array item count out of bounds")
        if schema.get("uniqueItems"):
            try:
                unique_count = len({json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value})
            except (TypeError, ValueError) as error:
                raise UEIValidationError(f"{location}: uniqueItems requires JSON values") from error
            if unique_count != len(value):
                raise UEIValidationError(f"{location}: uniqueItems violated")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate(item, schema["items"], root, f"{location}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            raise UEIValidationError(f"{location}: string length out of bounds")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise UEIValidationError(f"{location}: pattern mismatch")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise UEIValidationError(f"{location}: number out of bounds")


def validate_contract(value: dict[str, Any], contract_version: str) -> None:
    """Validate a JSON dictionary against one named UEI v1 contract."""
    schema = load_contract_schema(contract_version)
    _reject_non_json_values(value)
    _validate(value, schema, schema, "$")
    if contract_version == "capture_lineage_v1":
        captured_at = value["captured_at"]
        if not isinstance(captured_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", captured_at):
            raise UEIValidationError("$.captured_at: RFC3339 UTC Z form required")
        try:
            parsed = datetime.fromisoformat(captured_at[:-1] + "+00:00")
        except ValueError as error:
            raise UEIValidationError("$.captured_at: invalid RFC3339 date-time") from error
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise UEIValidationError("$.captured_at: UTC offset must be zero")
    if contract_version in {"provider_safe_result_v1", "provider_error_v1"}:
        for resolution, reference in (("registration_resolution", "registration_ref"),
                                      ("manifest_resolution", "manifest_ref")):
            present = reference in value
            if (value[resolution] == "resolved") != present:
                raise UEIValidationError(f"$.{reference}: required iff {resolution}=resolved")
    if contract_version == "screen_parse_request_v1":
        pairs = [(item["provider_id"], item["profile_id"]) for item in value["requested_profiles"]]
        if len(set(pairs)) != len(pairs):
            raise UEIValidationError("$.requested_profiles: duplicate provider/profile tuple")
    if contract_version == "provider_manifest_v1":
        ids = [item["profile_id"] for item in value["profiles"]]
        if len(set(ids)) != len(ids):
            raise UEIValidationError("$.profiles: duplicate profile_id")
    if contract_version == "provider_safe_result_v1":
        if value["status"] == "success" and "error_ref" in value:
            raise UEIValidationError("$.error_ref: forbidden for successful result")
        ids = [item["source_item_id"] for item in value["items"]]
        if len(set(ids)) != len(ids):
            raise UEIValidationError("$.items: duplicate source_item_id")
        for index, item in enumerate(value["items"]):
            for name in ("source_bbox", "capture_bbox"):
                box = item[name]
                if box is not None and not (box[0] < box[2] and box[1] < box[3]):
                    raise UEIValidationError(f"$.items[{index}].{name}: invalid half-open bbox")
            confidence = item["provider_confidence"]
            if confidence is not None and not math.isfinite(confidence):
                raise UEIValidationError(f"$.items[{index}].provider_confidence: finite number required")
            source = item["source_bbox"]
            if source is not None:
                if item["source_coordinate_space"] == "image_normalized_xyxy":
                    if not all(isinstance(edge, (int, float)) and 0 <= edge <= 1 for edge in source):
                        raise UEIValidationError(f"$.items[{index}].source_bbox: normalized bounds required")
                elif not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in source):
                    raise UEIValidationError(f"$.items[{index}].source_bbox: pixel integers required")
    if contract_version == "affine_coordinate_transform_v1":
        for field in ("scale", "offset"):
            if not all(math.isfinite(value[field][axis]) for axis in ("x", "y")):
                raise UEIValidationError(f"$.{field}: finite numbers required")
