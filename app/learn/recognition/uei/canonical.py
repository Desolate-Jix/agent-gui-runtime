"""Dependency-free RFC 8785/JCS canonical JSON primitives for UEI v1."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import math
import struct
from app.learn.recognition.uei.contracts import UEIValidationError


_MAX_EXACT_BINARY64_INTEGER = (1 << 53)


def _invalid(message: str) -> UEIValidationError:
    return UEIValidationError(message)


def _validate_unicode(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _invalid("jcs_lone_surrogate")


def _utf16_sort_key(value: str) -> bytes:
    _validate_unicode(value)
    return value.encode("utf-16-be")


def _quote_string(value: str) -> str:
    _validate_unicode(value)
    escaped: list[str] = ['"']
    short_escapes = {"\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}
    for character in value:
        if character == '"':
            escaped.append('\\"')
        elif character == "\\":
            escaped.append("\\\\")
        elif character in short_escapes:
            escaped.append(short_escapes[character])
        elif ord(character) < 0x20:
            escaped.append(f"\\u{ord(character):04x}")
        else:
            escaped.append(character)
    escaped.append('"')
    return "".join(escaped)


def _same_binary64(left: float, right: float) -> bool:
    return struct.pack(">d", left) == struct.pack(">d", right)


def _format_exponent(exponent: str) -> str:
    sign = ""
    if exponent.startswith(("+", "-")):
        sign, exponent = exponent[0], exponent[1:]
    exponent = exponent.lstrip("0") or "0"
    return ("+" if sign == "+" else "-" if sign == "-" else "") + exponent


def _jcs_lexical_candidate(value: float, lexical: str) -> str:
    if "e" in lexical or "E" in lexical:
        mantissa, exponent = lexical.lower().split("e", 1)
        if 1e-6 <= abs(value) < 1e21:
            plain = format(Decimal(lexical), "f")
            return plain[:-2] if plain.endswith(".0") else plain
        return mantissa + "e" + _format_exponent(exponent)
    return lexical[:-2] if lexical.endswith(".0") else lexical


def _format_binary64(value: float) -> str:
    if not math.isfinite(value):
        raise _invalid("jcs_nonfinite_number")
    if value == 0.0:
        return "0"

    shortest_round_trip = repr(value)
    try:
        reparsed = float(shortest_round_trip)
    except ValueError as error:
        raise _invalid("jcs_binary64_unsupported") from error
    if not _same_binary64(value, reparsed):
        raise _invalid("jcs_binary64_unsupported")

    for precision in range(1, 18):
        candidate = format(value, f".{precision}g")
        try:
            if _same_binary64(value, float(candidate)):
                return _jcs_lexical_candidate(value, candidate)
        except ValueError:
            continue
    raise _invalid("jcs_binary64_unsupported")


def _format_integer(value: int) -> str:
    if abs(value) <= _MAX_EXACT_BINARY64_INTEGER:
        return str(value)
    try:
        as_float = float(value)
    except OverflowError as error:
        raise _invalid("jcs_integer_not_binary64") from error
    if not math.isfinite(as_float) or int(as_float) != value:
        raise _invalid("jcs_integer_not_binary64")
    return _format_binary64(as_float)


def _canonical_json_text(value: object, active_containers: set[int]) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return _format_integer(value)
    if isinstance(value, float):
        return _format_binary64(value)
    if isinstance(value, (list, dict)):
        identity = id(value)
        if identity in active_containers:
            raise _invalid("jcs_cyclic_value")
        active_containers.add(identity)
        try:
            if isinstance(value, list):
                return "[" + ",".join(
                    _canonical_json_text(item, active_containers) for item in value
                ) + "]"
            keys: list[str] = []
            for key in value:
                if not isinstance(key, str):
                    raise _invalid("jcs_object_key_not_string")
                _validate_unicode(key)
                keys.append(key)
            keys.sort(key=_utf16_sort_key)
            return "{" + ",".join(
                _quote_string(key) + ":" + _canonical_json_text(value[key], active_containers)
                for key in keys
            ) + "}"
        finally:
            active_containers.remove(identity)
    raise _invalid("jcs_unsupported_json_value")


def canonical_json_bytes(value: object) -> bytes:
    """Return the RFC 8785/JCS UTF-8 serialization of one JSON value."""
    try:
        return _canonical_json_text(value, set()).encode("utf-8")
    except UnicodeEncodeError as error:
        raise _invalid("jcs_lone_surrogate") from error


def content_sha256(value: dict[str, object]) -> str:
    """Hash an immutable object after removing only its top-level self hash."""
    if not isinstance(value, dict):
        raise _invalid("jcs_hash_value_not_object")
    unhashed = {key: child for key, child in value.items() if key != "content_sha256"}
    return hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()


def seal_immutable(value: dict[str, object]) -> dict[str, object]:
    """Deep-copy an immutable object and attach its content-addressed hash."""
    if not isinstance(value, dict):
        raise _invalid("jcs_seal_value_not_object")
    sealed = deepcopy(value)
    sealed["content_sha256"] = content_sha256(sealed)
    return sealed


def immutable_ref(value: dict[str, object], *, id_field: str) -> dict[str, str]:
    """Return the sole permitted two-field immutable object reference."""
    if not isinstance(value, dict) or not isinstance(id_field, str):
        raise _invalid("immutable_ref_invalid_value")
    identifier = value.get(id_field)
    if not isinstance(identifier, str) or not identifier:
        raise _invalid("immutable_ref_invalid_id")
    declared_hash = value.get("content_sha256")
    if not isinstance(declared_hash, str) or declared_hash != content_sha256(value):
        raise _invalid("immutable_ref_invalid_content_sha256")
    return {"id": identifier, "content_sha256": declared_hash}


def deterministic_result_id(
    *, request_ref: dict[str, str], provider_id: str, profile_id: str, fixture_kind: str
) -> str:
    """Derive a stable result ID from the immutable projection identity tuple."""
    digest = content_sha256(
        {
            "request_ref": request_ref,
            "provider_id": provider_id,
            "profile_id": profile_id,
            "fixture_kind": fixture_kind,
        }
    )
    return f"result/{digest}"


def deterministic_error_id(
    *, request_ref: dict[str, str], provider_id: str, profile_id: str, stage: str, code: str
) -> str:
    """Derive a stable error ID from the immutable failure identity tuple."""
    digest = content_sha256(
        {
            "request_ref": request_ref,
            "provider_id": provider_id,
            "profile_id": profile_id,
            "stage": stage,
            "code": code,
        }
    )
    return f"error/{digest}"
