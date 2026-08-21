"""Synthetic UEI v1 values used only by offline schema conformance tests."""

from dataclasses import dataclass
import json
from pathlib import Path

from app.learn.recognition.uei.canonical import deterministic_error_id, deterministic_result_id
from app.learn.recognition.uei.store import UEIObjectStore


SHA = "a" * 64


@dataclass(frozen=True)
class UEITestContext:
    """Immutable synthetic identifiers for UEI schema tests."""

    store: UEIObjectStore
    case: str
    request_ref: dict[str, str]
    registration_ref: dict[str, str] | None
    manifest_ref: dict[str, str] | None
    provider_id: str
    profile_id: str
    fixture_binding: dict[str, object]
    transform_ref: dict[str, str] | None

    def for_case(self, case: str) -> dict[str, object]:
        if case != self.case:
            raise ValueError(f"context is bound to {self.case}, not {case}")
        return {"store": self.store, "request_ref": dict(self.request_ref),
                "registration_ref": None if self.registration_ref is None else dict(self.registration_ref),
                "manifest_ref": None if self.manifest_ref is None else dict(self.manifest_ref),
                "provider_id": self.provider_id, "profile_id": self.profile_id,
                "fixture_binding": dict(self.fixture_binding),
                "transform_ref": None if self.transform_ref is None else dict(self.transform_ref)}


def load_fixture(name: str) -> dict[str, object]:
    path = Path(__file__).resolve().parent / "fixtures" / "uei-v1" / name
    if not path.is_file():
        raise FileNotFoundError(f"UEI fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_context_from_sidecar(tmp_path: Path, case: str) -> UEITestContext:
    """Seal sidecar objects in a caller-provided store and bind one static case."""
    from app.learn.recognition.uei.canonical import immutable_ref, seal_immutable
    from app.learn.recognition.uei.store import UEIObjectStore

    sidecar = load_fixture("static-projection-sidecar-v1.json")
    cases = sidecar.get("cases")
    if not isinstance(cases, dict) or case not in cases or not isinstance(cases[case], dict):
        raise ValueError(f"unknown UEI static projection case: {case}")
    data = cases[case]
    store = UEIObjectStore(root=tmp_path)
    objects = data.get("objects", [])
    if not isinstance(objects, list):
        raise ValueError(f"invalid sidecar objects for case: {case}")
    refs: dict[str, dict[str, str]] = {}
    for value in objects:
        if not isinstance(value, dict):
            raise ValueError(f"invalid sidecar object for case: {case}")
        sealed = seal_immutable(value)
        reference = store.put(sealed)
        for field in ("request_id", "registration_id", "manifest_id", "content_sha256"):
            identifier = sealed.get(field)
            if isinstance(identifier, str):
                refs[identifier] = reference
        immutable_ref(sealed, id_field=next(field for field in ("request_id", "registration_id", "manifest_id", "capture_id", "artifact_id") if field in sealed))
    required = ("request_ref", "provider_id", "profile_id", "fixture_binding")
    if any(key not in data for key in required):
        raise ValueError(f"incomplete sidecar case: {case}")
    request_ref = data["request_ref"]
    if isinstance(request_ref, str):
        request_ref = refs.get(request_ref)
    if not isinstance(request_ref, dict):
        raise ValueError(f"invalid request_ref for case: {case}")
    def optional_ref(name: str) -> dict[str, str] | None:
        value = data.get(name)
        if value is None:
            return None
        if isinstance(value, str):
            value = refs.get(value)
        if not isinstance(value, dict):
            raise ValueError(f"invalid {name} for case: {case}")
        return dict(value)
    if not isinstance(data["provider_id"], str) or not isinstance(data["profile_id"], str) or not isinstance(data["fixture_binding"], dict):
        raise ValueError(f"invalid sidecar case values: {case}")
    return UEITestContext(store=store, case=case, request_ref=dict(request_ref),
                          registration_ref=optional_ref("registration_ref"), manifest_ref=optional_ref("manifest_ref"),
                          provider_id=data["provider_id"], profile_id=data["profile_id"],
                          fixture_binding=dict(data["fixture_binding"]), transform_ref=optional_ref("transform_ref"))


def project_case(context: UEITestContext) -> dict[str, object]:
    """Dispatch the case-bound fixture to its pure projection entry point."""
    from app.learn.recognition.uei.projections import (project_ocr_result, project_screen_parser_result,
                                                        project_uia_snapshot)

    dispatch = {"ocr": (project_ocr_result, "ocr-result-static.json"),
                "uia": (project_uia_snapshot, "uia-snapshot-static.json"),
                "screen-parser": (project_screen_parser_result, "screen-parser-result-static.json")}
    if context.case not in dispatch:
        raise ValueError(f"unknown UEI static projection case: {context.case}")
    projection, fixture_name = dispatch[context.case]
    arguments = context.for_case(context.case)
    # Import and bind the deterministic production identity contract used by projections.
    deterministic_result_id(request_ref=context.request_ref, provider_id=context.provider_id,
                            profile_id=context.profile_id, fixture_kind=context.case)
    deterministic_error_id(request_ref=context.request_ref, provider_id=context.provider_id,
                           profile_id=context.profile_id, stage="projection", code="projection_failed")
    return projection(**arguments, fixture=load_fixture(fixture_name))


def load_expected(case: str) -> dict[str, object]:
    """Load one UTF-8 expected safe result from the static conformance fixtures."""
    if case not in {"ocr", "uia", "screen-parser"}:
        raise ValueError(f"unknown UEI static projection case: {case}")
    path = Path(__file__).resolve().parent / "fixtures" / "uei-v1" / "expected-safe-results" / f"{case}.json"
    if not path.is_file():
        raise FileNotFoundError(f"UEI expected result not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def minimal_provider_safe_result() -> dict[str, object]:
    ref = {"id": "synthetic/ref", "content_sha256": SHA}
    return {
        "contract_version": "provider_safe_result_v1",
        "result_id": "result/synthetic/1",
        "request_ref": ref,
        "requested_provider_id": "local.synthetic/provider",
        "requested_profile_id": "local.synthetic/provider/profile",
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": ref,
        "manifest_ref": ref,
        "provider_id": "local.synthetic/provider",
        "profile_id": "local.synthetic/provider/profile",
        "provider_version": "1.0.0",
        "capture_lineage_ref": ref,
        "status": "success",
        "review_only": False,
        "items": [{
            "source_item_id": "item-1", "source_id_origin": "provider", "kind": "text",
            "safe_text": "synthetic", "safe_role": None, "safe_states": [],
            "source_bbox": [0, 0, 1, 1], "capture_bbox": [0, 0, 1, 1],
            "source_coordinate_space": "capture_pixel_xyxy",
            "coordinate_transform_ref": None, "opaque_attributes": {},
            "provider_confidence": None,
        }],
        "redaction_summary": {"redacted_item_count": 0, "redacted_field_count": 0,
                              "secret_detected": False, "sensitive_categories": []},
        "content_sha256": SHA,
    }
