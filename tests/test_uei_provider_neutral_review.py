from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image

from app.learn.draft_review import load_learning_draft_review
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.provider_adapters import (
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
    ProviderRunBudget,
    RestrictedCaptureLease,
    TrustedProviderAdapterRegistry,
)
from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime
from app.learn.recognition.uei.store import UEIObjectStore
from app.learn.workflow_tasks.recognition import _attach_uei_shadow_result_ref_to_draft
from tests.uei_v1_helpers import build_context_from_sidecar, project_case


_SUMMARY_KEYS = {
    "contract_version",
    "status",
    "provider_id",
    "profile_id",
    "provider_version",
    "item_count",
    "registration_resolution",
    "manifest_resolution",
    "capture_match_status",
    "redaction",
    "safe_error",
    "immutable_identity",
    "display_only",
    "review_only",
    "execution_authorized",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "action_candidates",
}
_OMNI_PROVIDER_ID = "local.runtime/omniparser"
_OMNI_PROFILE_ID = "local.runtime/omniparser/shadow-v2"


class _RecordedShadowAdapter:
    provider_id = _OMNI_PROVIDER_ID
    profile_id = _OMNI_PROFILE_ID
    provider_version = "recorded-shadow-v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def invoke(self, *, capture: object, budget: object, invocation_id: str) -> NormalizedScreenParseOutput:
        del capture, budget, invocation_id
        if self.fail:
            raise RuntimeError("provider-native diagnostic must not reach Review")
        return NormalizedScreenParseOutput(
            items=(
                NormalizedProviderItem(
                    source_item_id="omni-recorded-1",
                    kind="text",
                    safe_text="Shadow private item text",
                    source_bbox=(0, 0, 1, 1),
                    source_coordinate_space="capture_pixel_xyxy",
                    provider_confidence=0.8,
                ),
            ),
            duration_ms=3,
            resource_units=1,
        )


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _invoke_recorded_shadow(
    *, root: Path, store: UEIObjectStore, suffix: str, fail: bool,
) -> dict[str, object]:
    image_path = root / f"fixed-shadow-{suffix}.png"
    Image.new("RGB", (2, 2), color=(10, 20, 30)).save(image_path)
    image_bytes = image_path.read_bytes()
    digest = sha256(image_bytes).hexdigest()
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1",
        "artifact_id": f"artifact/recorded-shadow/{suffix}",
        "artifact_sha256": digest,
        "media_type": "image/png",
        "byte_length": len(image_bytes),
        "restricted": True,
    })
    capture_ref = _put(store, {
        "contract_version": "capture_lineage_v1",
        "capture_id": f"capture/recorded-shadow/{suffix}",
        "artifact_ref": artifact_ref,
        "artifact_sha256": digest,
        "image_size": {"width": 2, "height": 2},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-22T00:00:00Z",
    })
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/recorded-shadow/{suffix}",
        "capture_lineage_ref": capture_ref,
        "requested_profiles": [{
            "provider_id": _OMNI_PROVIDER_ID,
            "profile_id": _OMNI_PROFILE_ID,
            "mode": "Shadow",
        }],
        "privacy_policy": "restricted",
        "requester_id": "server",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": "registration/recorded-shadow/v1",
        "provider_id": _OMNI_PROVIDER_ID,
        "profile_ids": [_OMNI_PROFILE_ID],
        "enabled": True,
        "allowed_modes": ["Shadow"],
        "allowed_privacy_policies": ["restricted"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": {
            "max_json_bytes": 4096,
            "max_depth": 8,
            "max_array_items": 16,
            "max_object_properties": 32,
            "max_string_chars": 256,
            "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"],
        },
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1",
        "manifest_id": "manifest/recorded-shadow/v1",
        "provider_id": _OMNI_PROVIDER_ID,
        "provider_version": _RecordedShadowAdapter.provider_version,
        "profiles": [{
            "profile_id": _OMNI_PROFILE_ID,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"],
            "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["restricted"],
            "mode_allowlist": ["Shadow"],
        }],
    })
    adapter = _RecordedShadowAdapter(fail=fail)
    runtime = ShadowProviderRuntime(
        store=store,
        registry=TrustedProviderAdapterRegistry([adapter]),
        trusted_profiles={(_OMNI_PROVIDER_ID, _OMNI_PROFILE_ID): (registration_ref, manifest_ref)},
        budget=ProviderRunBudget(
            timeout_ms=100,
            max_output_bytes=4096,
            max_element_count=16,
            max_string_length=256,
            resource_group="recorded-test",
        ),
    )
    lease = RestrictedCaptureLease(
        request_ref=request_ref,
        capture_lineage_ref=capture_ref,
        artifact_ref=artifact_ref,
        capture_id=f"capture/recorded-shadow/{suffix}",
        artifact_sha256=digest,
        image_size={"width": 2, "height": 2},
        local_path=image_path,
    )
    return runtime.invoke(request_ref=request_ref, capture_lease=lease)


def _load_review(
    *, root: Path, case: str, result_ref: dict[str, str], capture_ref: dict[str, str],
) -> dict[str, object]:
    result = {
        "learning_draft": {
            "contract_version": "learning_template_draft_v1",
            "states": [],
            "regions": [],
            "action_templates": [],
            "provider_summary": {
                "contract_version": "learning_recognition_provider_summary_v1",
                "provider": "omniparser",
                "execution_authorized": False,
            },
            "page_details": {
                "provider_summary": {
                    "contract_version": "learning_recognition_provider_summary_v1",
                    "provider": "omniparser",
                    "execution_authorized": False,
                },
            },
        },
    }
    _attach_uei_shadow_result_ref_to_draft(
        result,
        {"uei_shadow_result_ref": result_ref},
    )
    draft = result["learning_draft"]
    draft["capture_lineage_ref"] = capture_ref
    source_path = root / "artifacts" / "learning-runs" / case / "trial.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return load_learning_draft_review(source_path, project_root=root)


def test_built_in_and_omni_results_share_one_canonical_review_model(tmp_path: Path) -> None:
    store_root = tmp_path / "artifacts" / "uei-shadow-store"
    cases: list[tuple[str, UEIObjectStore, dict[str, str], dict[str, str]]] = []
    for case in ("ocr", "uia", "screen-parser"):
        context = build_context_from_sidecar(store_root, case)
        projected = project_case(context)
        result_ref = {
            "id": projected["result_id"],
            "content_sha256": projected["content_sha256"],
        }
        cases.append((case, context.store, result_ref, projected["capture_lineage_ref"]))

    shadow_store = UEIObjectStore(root=store_root)
    success_reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=shadow_store,
        suffix="success",
        fail=False,
    )
    failed_reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=shadow_store,
        suffix="failure",
        fail=True,
    )
    for name, reply, expected_status in (
        ("shadow-success", success_reply, "succeeded"),
        ("shadow-failure", failed_reply, "failed"),
    ):
        receipt = shadow_store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
        result = shadow_store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
        assert receipt["status"] == expected_status
        assert receipt["result_ref"] == reply["result_ref"]
        assert str(tmp_path) not in json.dumps(
            {"receipt": receipt, "result": result},
            ensure_ascii=False,
        )
        if expected_status == "failed":
            assert receipt["error_ref"] == reply["error_ref"]
            shadow_store.get(reply["error_ref"], contract_version="provider_error_v1")
        cases.append((name, shadow_store, reply["result_ref"], result["capture_lineage_ref"]))

    summaries: list[dict[str, object]] = []
    for case, store, result_ref, capture_ref in cases:
        stored = store.get(result_ref, contract_version="provider_safe_result_v1")
        review = _load_review(
            root=tmp_path,
            case=case,
            result_ref=result_ref,
            capture_ref=capture_ref,
        )
        summary = review["uei_shadow_provider_summary"]
        summaries.append(summary)
        assert set(summary) == _SUMMARY_KEYS
        assert summary["contract_version"] == "uei_shadow_provider_summary_v1"
        assert summary["capture_match_status"] == "match"
        assert summary["display_only"] is True
        assert summary["review_only"] is True
        assert summary["execution_authorized"] is False
        assert summary["artifact_is_authorization"] is False
        assert summary["execute_binding_enabled"] is False
        assert summary["action_candidates"] == []
        if case == "shadow-failure":
            assert summary["status"] == "failed"
            assert summary["safe_error"] == {
                "stage": "projection",
                "code": "projection_failed",
            }
        else:
            assert summary["status"] == "success"
            assert summary["safe_error"] is None
        assert "provider_summary" not in review["draft"]
        assert "provider_summary" not in review["draft"].get("page_details", {})
        serialized = json.dumps(review, ensure_ascii=False)
        assert result_ref["content_sha256"] not in serialized
        assert stored["result_id"] not in serialized
        for ref_name in (
            "request_ref",
            "capture_lineage_ref",
            "registration_ref",
            "manifest_ref",
            "error_ref",
        ):
            reference = stored.get(ref_name)
            if isinstance(reference, dict):
                assert reference["id"] not in serialized
                assert reference["content_sha256"] not in serialized
        assert str(tmp_path) not in serialized
        assert str(tmp_path) not in json.dumps(stored, ensure_ascii=False)
        assert "Synthetic Search" not in serialized
        assert "Shadow private item text" not in serialized
        assert "provider-native diagnostic" not in serialized
        for forbidden in (
            "source_bbox",
            "capture_bbox",
            "coordinate_transform_ref",
            "opaque_attributes",
            "uei_shadow_result_ref",
        ):
            assert forbidden not in serialized
        assert stored["contract_version"] == "provider_safe_result_v1"

    assert {summary["provider_id"] for summary in summaries} == {
        "local.runtime/ocr",
        "local.runtime/windows-uia",
        "local.runtime/omniparser",
    }
