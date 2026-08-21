"""Offline resolution of UEI projection preconditions and trusted policy."""

from __future__ import annotations

from app.learn.recognition.uei.contracts import UEIOuterBoundaryError, UEIValidationError, is_namespaced_provider_profile_id
from app.learn.recognition.uei.store import UEIObjectStore


_REQUIRED_CONFORMANCE_SUITE = "uei-v1-static-projection"
_RESOLUTIONS = {"resolved", "not_found", "invalid", "not_reached"}


def _outer(name: str) -> UEIOuterBoundaryError:
    """Return a deliberately non-sensitive boundary error for one stored reference."""
    return UEIOuterBoundaryError(f"{name}: invalid or unresolved")


def _stored(
    store: UEIObjectStore, reference: object, contract_version: str, name: str,
) -> dict[str, object]:
    try:
        return store.get(reference, contract_version=contract_version)  # type: ignore[arg-type]
    except (UEIValidationError, TypeError, ValueError):
        raise _outer(name) from None


def resolve_projection_context(*, store: UEIObjectStore, request_ref: dict[str, str]) -> dict[str, object]:
    """Resolve a sealed request, its capture lineage, and its exact artifact.

    This is the caller/schema boundary.  It has no durable side effects: all
    failures are outer-boundary failures, so a projection must not turn them
    into provider error or result objects.
    """
    request = _stored(store, request_ref, "screen_parse_request_v1", "request_ref")
    lineage_ref = request.get("capture_lineage_ref")
    lineage = _stored(store, lineage_ref, "capture_lineage_v1", "capture_lineage_ref")
    artifact_ref = lineage.get("artifact_ref")
    artifact = _stored(store, artifact_ref, "artifact_ref_v1", "artifact_ref")

    lineage_sha = lineage.get("artifact_sha256")
    artifact_sha = artifact.get("artifact_sha256")
    if not isinstance(lineage_sha, str) or lineage_sha != artifact_sha:
        raise _outer("artifact_sha256")
    image_size = lineage.get("image_size")
    if not isinstance(image_size, dict):
        raise _outer("image_size")
    width, height = image_size.get("width"), image_size.get("height")
    if (not isinstance(width, int) or isinstance(width, bool) or width < 1
            or not isinstance(height, int) or isinstance(height, bool) or height < 1):
        raise _outer("image_size")

    return {
        "store": store,
        "request_ref": dict(request_ref),
        "request": request,
        "capture_lineage_ref": dict(lineage_ref) if isinstance(lineage_ref, dict) else lineage_ref,
        "capture_lineage": lineage,
        "artifact_ref": dict(artifact_ref) if isinstance(artifact_ref, dict) else artifact_ref,
        "artifact": artifact,
        "artifact_sha256": lineage_sha,
        "image_size": {"width": width, "height": height},
    }


def _failure(
    *, provider_id: str, profile_id: str, registration_resolution: str,
    manifest_resolution: str, registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, stage: str, code: str,
) -> dict[str, object]:
    """Build a stage-conditional, non-persistent resolution record."""
    if registration_resolution not in _RESOLUTIONS or manifest_resolution not in _RESOLUTIONS:
        raise UEIValidationError("registry_invalid_resolution")
    record: dict[str, object] = {
        "resolved": False,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": registration_resolution,
        "manifest_resolution": manifest_resolution,
        "failure": {"stage": stage, "code": code, "reason_class": "policy"},
    }
    if registration_resolution == "resolved" and registration_ref is not None:
        record["registration_ref"] = dict(registration_ref)
    if manifest_resolution == "resolved" and manifest_ref is not None:
        record["manifest_ref"] = dict(manifest_ref)
    return record


def _get_after_precondition(
    store: UEIObjectStore, reference: dict[str, str] | None, contract_version: str,
) -> tuple[str, dict[str, object] | None]:
    """Resolve optional policy refs without converting them into outer failures."""
    if reference is None:
        return "not_found", None
    try:
        return "resolved", store.get(reference, contract_version=contract_version)
    except (UEIValidationError, TypeError, ValueError):
        return "invalid", None


def _request_profile(context: dict[str, object], provider_id: str, profile_id: str) -> dict[str, object] | None:
    request = context.get("request")
    if not isinstance(request, dict):
        raise UEIValidationError("registry_context_missing_request")
    requested = request.get("requested_profiles")
    if not isinstance(requested, list):
        raise UEIValidationError("registry_context_invalid_request")
    for item in requested:
        if isinstance(item, dict) and item.get("provider_id") == provider_id and item.get("profile_id") == profile_id:
            return item
    return None


def _policy_permits(registration: dict[str, object], requested: dict[str, object]) -> tuple[str, str] | None:
    """Return the first closed registration-policy failure, if any."""
    profile_id = requested.get("profile_id")
    mode = requested.get("mode")
    assert isinstance(profile_id, str) and isinstance(mode, str)
    if registration.get("enabled") is not True:
        return "registration", "capability_intersection_empty"
    if profile_id not in registration.get("profile_ids", []):
        return "registration", "profile_unregistered"
    if mode not in registration.get("allowed_modes", []):
        return "registration", "capability_intersection_empty"
    if registration.get("egress_policy") != "local_only":
        return "registration", "egress_disallowed"
    if registration.get("required_conformance_suite") != _REQUIRED_CONFORMANCE_SUITE:
        return "registration", "capability_intersection_empty"
    return None


def resolve_requested_profile(
    *, context: dict[str, object], registration_ref: dict[str, str] | None,
    manifest_ref: dict[str, str] | None, provider_id: str, profile_id: str,
) -> dict[str, object]:
    """Resolve and intersect exactly one requested profile with local policy.

    Unlike :func:`resolve_projection_context`, this function represents an
    already-valid request/capture context.  It therefore returns an explicit,
    non-persistent success/failure record rather than raising provider-policy
    failures or fabricating provenance references.
    """
    if not is_namespaced_provider_profile_id(provider_id) or not is_namespaced_provider_profile_id(profile_id):
        raise UEIValidationError("registry_invalid_requested_profile")
    if not isinstance(context, dict):
        raise UEIOuterBoundaryError("context: invalid or unresolved")
    store = context.get("store")
    if not isinstance(store, UEIObjectStore):
        raise UEIOuterBoundaryError("context: invalid or unresolved")
    request_ref = context.get("request_ref")
    if not isinstance(request_ref, dict):
        raise UEIOuterBoundaryError("context: invalid or unresolved")
    verified_context = resolve_projection_context(store=store, request_ref=request_ref)
    requested = _request_profile(verified_context, provider_id, profile_id)
    registration_resolution, registration = _get_after_precondition(
        store, registration_ref, "trusted_provider_registration_v1",
    )
    if registration_resolution != "resolved":
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution=registration_resolution, manifest_resolution="not_reached",
            registration_ref=None, manifest_ref=None, stage="registration", code="provider_unregistered",
        )
    assert registration is not None
    if requested is None:
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="not_reached",
            registration_ref=registration_ref, manifest_ref=None, stage="request",
            code="capability_intersection_empty",
        )
    request = verified_context["request"]
    assert isinstance(request, dict)
    if registration.get("provider_id") != provider_id:
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="not_reached",
            registration_ref=registration_ref, manifest_ref=None, stage="registration",
            code="provider_unregistered",
        )
    privacy = request.get("privacy_policy")
    if privacy not in registration.get("allowed_privacy_policies", []):
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="not_reached",
            registration_ref=registration_ref, manifest_ref=None, stage="registration",
            code="privacy_disallowed",
        )
    policy_failure = _policy_permits(registration, requested)
    if policy_failure is not None:
        stage, code = policy_failure
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="not_reached",
            registration_ref=registration_ref, manifest_ref=None, stage=stage, code=code,
        )

    manifest_resolution, manifest = _get_after_precondition(store, manifest_ref, "provider_manifest_v1")
    if manifest_resolution != "resolved":
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution=manifest_resolution,
            registration_ref=registration_ref, manifest_ref=None, stage="manifest",
            code="capability_intersection_empty",
        )
    assert manifest is not None
    if manifest.get("provider_id") != provider_id:
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="resolved",
            registration_ref=registration_ref, manifest_ref=manifest_ref, stage="manifest",
            code="capability_intersection_empty",
        )
    profiles = manifest.get("profiles")
    profile = next((item for item in profiles if isinstance(item, dict) and item.get("profile_id") == profile_id), None) if isinstance(profiles, list) else None
    if profile is None:
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="resolved",
            registration_ref=registration_ref, manifest_ref=manifest_ref, stage="manifest",
            code="capability_intersection_empty",
        )
    if (profile.get("supports_capture_artifact") is not True
            or privacy not in profile.get("privacy_capabilities", [])
            or requested.get("mode") not in profile.get("mode_allowlist", [])):
        return _failure(
            provider_id=provider_id, profile_id=profile_id,
            registration_resolution="resolved", manifest_resolution="resolved",
            registration_ref=registration_ref, manifest_ref=manifest_ref, stage="manifest",
            code="capability_intersection_empty",
        )
    limits = registration["safe_payload_limits"]
    assert isinstance(limits, dict)
    return {
        "resolved": True,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": dict(registration_ref) if registration_ref is not None else None,
        "manifest_ref": dict(manifest_ref) if manifest_ref is not None else None,
        "registration": registration,
        "manifest": manifest,
        "profile": profile,
        "safe_payload_limits": dict(limits),
    }
