from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

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

    def __init__(
        self,
        *,
        fail: bool = False,
        items: tuple[NormalizedProviderItem, ...] | None = None,
    ) -> None:
        self.fail = fail
        self.items = items

    def invoke(self, *, capture: object, budget: object, invocation_id: str) -> NormalizedScreenParseOutput:
        del capture, budget, invocation_id
        if self.fail:
            raise RuntimeError(
                "RAW_NATIVE_SECRET_DIAGNOSTIC provider-native diagnostic must not reach Review"
            )
        return NormalizedScreenParseOutput(
            items=self.items or (
                NormalizedProviderItem(
                    source_item_id="omni-recorded-1",
                    kind="text",
                    safe_text="Sanitized recorded control",
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
    items: tuple[NormalizedProviderItem, ...] | None = None,
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
        "provider_version": "recorded-shadow-v1",
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
    adapter = _RecordedShadowAdapter(fail=fail, items=items)
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
    reply = runtime.invoke(request_ref=request_ref, capture_lease=lease)
    reply["_test_source_image_path"] = image_path
    return reply


_AUTO_SOURCE_IMAGE = object()


def _load_review(
    *, root: Path, case: str, result_ref: dict[str, str], capture_ref: dict[str, str],
    regions: list[dict[str, object]] | None = None,
    uia_support_items: list[dict[str, object]] | None = None,
    source_image_path: Path | None | object = _AUTO_SOURCE_IMAGE,
    declared_source_sha256: str | None = None,
    wrapper: bool = False,
    top_level_capture_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    if source_image_path is _AUTO_SOURCE_IMAGE:
        store = UEIObjectStore(root=root / "artifacts" / "uei-shadow-store")
        capture = store.get(capture_ref, contract_version="capture_lineage_v1")
        expected_sha = capture["artifact_sha256"]
        source_image_path = next(
            (
                candidate
                for candidate in root.glob("fixed-shadow-*.png")
                if sha256(candidate.read_bytes()).hexdigest() == expected_sha
            ),
            None,
        )
    screen: dict[str, object] = {}
    if isinstance(source_image_path, Path):
        screen = {
            "source_image_path": source_image_path.relative_to(root).as_posix(),
            "source_image_sha256": (
                declared_source_sha256
                or sha256(source_image_path.read_bytes()).hexdigest()
            ),
        }
    result = {
        "learning_draft": {
            "contract_version": "learning_template_draft_v1",
            "states": [],
            "regions": list(regions or []),
            "action_templates": [],
            "provider_summary": {
                "contract_version": "learning_recognition_provider_summary_v1",
                "provider": "omniparser",
                "execution_authorized": False,
            },
            "page_details": {
                "screen": screen,
                "grounding_candidates": list(uia_support_items or []),
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
    payload = {"learning_draft": draft} if wrapper else draft
    if wrapper and top_level_capture_ref is not None:
        payload["capture_lineage_ref"] = top_level_capture_ref
    source_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return load_learning_draft_review(source_path, project_root=root)


def test_omni_review_enriches_role_from_one_current_uia_support_without_authority(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="uia-role-enrichment",
        fail=False,
        items=(
            NormalizedProviderItem(
                source_item_id="omni/search",
                kind="icon",
                safe_text="Search",
                safe_role="icon",
                safe_states=("interactable",),
                source_bbox=(0, 0, 1, 1),
                source_coordinate_space="capture_pixel_xyxy",
            ),
        ),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    review = _load_review(
        root=tmp_path,
        case="uia-role-enrichment",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        uia_support_items=[
            {
                "item_id": "uia/search",
                "label": "Search",
                "item_type": "actionable",
                "role": "button",
                "bbox": {"x": 0, "y": 0, "w": 1, "h": 1},
                "source_evidence": ["uia"],
            }
        ],
    )

    region = review["draft"]["regions"][0]
    assert region["role"] == "review_only"
    assert region["provider_evidence"]["safe_role"] == "icon"
    assert region["provider_evidence"]["canonical_role"] == "button"
    assert region["provider_evidence"]["cross_evidence"]["status"] == "uia_supported"
    assert region["provider_evidence"]["cross_evidence"]["support_item_id"] == "uia/search"
    assert region["grounding_eligible"] is False
    assert region["artifact_is_authorization"] is False
    assert region["execute_binding_enabled"] is False
    assert region["action_candidates"] == []


def test_omni_review_does_not_promote_ambiguous_uia_roles(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="uia-role-ambiguous",
        fail=False,
        items=(
            NormalizedProviderItem(
                source_item_id="omni/search",
                kind="icon",
                safe_text="Search",
                safe_role="icon",
                source_bbox=(0, 0, 1, 1),
                source_coordinate_space="capture_pixel_xyxy",
            ),
        ),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    review = _load_review(
        root=tmp_path,
        case="uia-role-ambiguous",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        uia_support_items=[
            {
                "item_id": f"uia/{role}",
                "label": "Search",
                "item_type": "actionable",
                "role": role,
                "bbox": {"x": 0, "y": 0, "w": 1, "h": 1},
                "source_evidence": ["uia"],
            }
            for role in ("button", "link")
        ],
    )

    evidence = review["draft"]["regions"][0]["provider_evidence"]
    assert evidence["cross_evidence"] == {"status": "ambiguous"}
    assert "canonical_role" not in evidence
    assert review["draft"]["regions"][0]["role"] == "review_only"


def _recorded_item(
    *,
    source_item_id: str,
    text: str = "Quick Apply",
    role: str = "button",
    bbox: tuple[int, int, int, int] | None = (0, 0, 1, 1),
    confidence: float | None = 0.91,
    states: tuple[str, ...] = (),
) -> NormalizedProviderItem:
    return NormalizedProviderItem(
        source_item_id=source_item_id,
        kind="element",
        safe_text=text,
        safe_role=role,
        safe_states=states,
        source_bbox=bbox,
        source_coordinate_space="capture_pixel_xyxy",
        provider_confidence=confidence,
    )


def _builtin_static_ocr_with_identity_grounding(
    *, root: Path, store: UEIObjectStore, suffix: str,
) -> dict[str, object]:
    from app.learn.recognition.uei.builtin_learning_projection import seal_builtin_ocr_evidence
    from app.learn.recognition.uei.projections import project_ocr_result

    image_path = root / f"fixed-builtin-{suffix}.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image_path)
    result_ref = seal_builtin_ocr_evidence(
        project_root=root,
        image_path=image_path,
        capture_id=f"capture/builtin-static/{suffix}",
        captured_at="2026-08-23T00:00:00Z",
        ocr_result={
            "matches": [{
                "text": "Quick Apply",
                "score": 0.88,
                "bbox": {"x": 1, "y": 1, "width": 4, "height": 2},
            }],
            "metadata": {"engine": "recorded-built-in"},
        },
    )
    result = store.get(result_ref, contract_version="provider_safe_result_v1")
    capture_ref = result["capture_lineage_ref"]
    capture = store.get(capture_ref, contract_version="capture_lineage_v1")
    artifact_sha = capture["artifact_sha256"]
    transform = seal_immutable({
        "contract_version": "affine_coordinate_transform_v1",
        "source_space": "image_pixel_xyxy",
        "target_space": "capture_pixel_xyxy",
        "source_size": {"width": 8, "height": 6},
        "target_size": {"width": 8, "height": 6},
        "scale": {"x": 1, "y": 1},
        "offset": {"x": 0, "y": 0},
        "rounding": "none",
        "clipping": "reject_if_outside",
        "source_capture_artifact_sha256": artifact_sha,
        "target_capture_artifact_sha256": artifact_sha,
    })
    transform_ref = store.put(transform)
    projected = project_ocr_result(
        store=store,
        request_ref=result["request_ref"],
        registration_ref=result["registration_ref"],
        manifest_ref=result["manifest_ref"],
        provider_id=result["provider_id"],
        profile_id=result["profile_id"],
        fixture={
            "image_path": image_path.relative_to(root).as_posix(),
            "matches": [{
                "text": "Quick Apply",
                "score": 0.88,
                "bbox": {"x": 1, "y": 1, "width": 4, "height": 2},
            }],
            "metadata": {"engine": "recorded-built-in"},
        },
        fixture_binding={
            "artifact_sha256": artifact_sha,
            "image_size": {"width": 8, "height": 6},
        },
        transform_ref=transform_ref,
    )
    assert projected["capture_lineage_ref"] == capture_ref
    assert projected["items"][0]["capture_bbox"] == [1, 1, 5, 3]
    assert projected["items"][0]["coordinate_transform_ref"] == transform_ref
    return projected


class _RecordedOmniProcess:
    pid = 1
    _uei_fake_process = True

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.returncode = 0

    def poll(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float) -> int:
        del timeout
        return self.returncode


def _recorded_omni_popen(process: _RecordedOmniProcess):
    def spawn(command: list[str], **_kwargs: object) -> _RecordedOmniProcess:
        output_path = Path(command[command.index("--output-json") + 1])
        output_path.write_text(json.dumps(process.payload), encoding="utf-8")
        return process

    return spawn


def _real_recorded_omni_result(
    *, root: Path, store: UEIObjectStore, monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        PROFILE_ID,
        PROVIDER_ID,
        PROVIDER_VERSION,
        TrustedOmniParserConfiguration,
    )

    image_path = root / "fixed-real-omni.png"
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image_path)
    image_bytes = image_path.read_bytes()
    image_hash = sha256(image_bytes).hexdigest()
    interpreter = root / "recorded-python.exe"
    worker = root / "recorded-worker.py"
    code, weights, cache = root / "code", root / "weights", root / "cache"
    interpreter.write_text("recorded", encoding="utf-8")
    worker.write_text("recorded", encoding="utf-8")
    for directory in (code, weights, cache):
        directory.mkdir()
    configuration = TrustedOmniParserConfiguration(
        interpreter=interpreter,
        worker_script=worker,
        code_path=code,
        weights_path=weights,
        cache_path=cache,
        minimum_free_gpu_gib=0,
    )
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1",
        "artifact_id": "artifact/real-recorded-omni",
        "artifact_sha256": image_hash,
        "media_type": "image/png",
        "byte_length": len(image_bytes),
        "restricted": True,
    })
    capture_ref = _put(store, {
        "contract_version": "capture_lineage_v1",
        "capture_id": "capture/real-recorded-omni",
        "artifact_ref": artifact_ref,
        "artifact_sha256": image_hash,
        "image_size": {"width": 8, "height": 6},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-23T00:00:00Z",
    })
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1",
        "request_id": "request/real-recorded-omni",
        "capture_lineage_ref": capture_ref,
        "requested_profiles": [{
            "provider_id": PROVIDER_ID,
            "profile_id": PROFILE_ID,
            "mode": "Shadow",
        }],
        "privacy_policy": "restricted",
        "requester_id": "server",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": "registration/real-recorded-omni",
        "provider_id": PROVIDER_ID,
        "profile_ids": [PROFILE_ID],
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
        "manifest_id": "manifest/real-recorded-omni",
        "provider_id": PROVIDER_ID,
        "provider_version": PROVIDER_VERSION,
        "profiles": [{
            "profile_id": PROFILE_ID,
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
    adapter = OmniParserShadowAdapter(configuration=configuration, gpu_free_gib=lambda: 99)
    runtime = ShadowProviderRuntime(
        store=store,
        registry=TrustedProviderAdapterRegistry([adapter]),
        trusted_profiles={(PROVIDER_ID, PROFILE_ID): (registration_ref, manifest_ref)},
        budget=ProviderRunBudget(
            timeout_ms=100,
            max_output_bytes=4096,
            max_element_count=16,
            max_string_length=256,
            resource_group="real-recorded-omni",
        ),
    )
    lease = RestrictedCaptureLease(
        request_ref=request_ref,
        capture_lineage_ref=capture_ref,
        artifact_ref=artifact_ref,
        capture_id="capture/real-recorded-omni",
        artifact_sha256=image_hash,
        image_size={"width": 8, "height": 6},
        local_path=image_path,
    )
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "uei-v1" / "portfolio-v1-omniparser-recorded-success.json")
        .read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        "app.learn.recognition.uei.omniparser_shadow_adapter.subprocess.Popen",
        _recorded_omni_popen(_RecordedOmniProcess(payload)),
    )
    reply = runtime.invoke(request_ref=request_ref, capture_lease=lease)
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    assert result["provider_version"] == PROVIDER_VERSION
    assert result["items"][0]["source_item_id"] == "recorded/quick-apply"
    return result


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
            assert review["uei_shadow_review_projection"]["status"] == "rejected"
            assert review["uei_shadow_review_projection"]["reason"] == "result_not_success"
            assert review["draft"]["regions"] == []
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
        if case == "shadow-success":
            assert "Sanitized recorded control" in serialized
        else:
            assert "Sanitized recorded control" not in serialized
        assert "RAW_NATIVE_SECRET_DIAGNOSTIC" not in serialized
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


def test_current_success_result_projects_safe_items_into_review_regions(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="review-region",
        fail=False,
        items=(_recorded_item(source_item_id="provider-quick-apply"),),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    existing = {
        "region_id": "existing-region",
        "label": "Existing",
        "role": "content",
        "bbox": {"x": 1, "y": 1, "w": 1, "h": 1},
    }

    review = _load_review(
        root=tmp_path,
        case="review-region",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        regions=[existing],
    )

    assert review["draft"]["regions"][0] == existing
    assert len(review["draft"]["regions"]) == 2
    projected = review["draft"]["regions"][1]
    assert projected["region_id"].startswith("uei_review_region_")
    assert projected["label"] == "Quick Apply"
    assert projected["role"] == "review_only"
    assert projected["kind"] == "element"
    assert projected["bbox"] == {"x": 0, "y": 0, "w": 1, "h": 1}
    assert projected["provider_evidence"] == {
        "provider_id": _OMNI_PROVIDER_ID,
        "profile_id": _OMNI_PROFILE_ID,
        "provider_version": "recorded-shadow-v1",
        "confidence": 0.91,
        "safe_role": "button",
        "safe_states": [],
    }
    assert projected["candidate_only"] is True
    assert projected["requires_human_review"] is True
    assert projected["final_submit_forbidden"] is True
    assert projected["real_action_requires_gate"] is True
    assert projected["review_only"] is True
    assert projected["grounding_eligible"] is False
    assert projected["artifact_is_authorization"] is False
    assert projected["execute_binding_enabled"] is False
    assert projected["action_candidates"] == []
    assert review["draft"]["action_templates"] == []
    projection = review["uei_shadow_review_projection"]
    assert projection == {
        "contract_version": "uei_shadow_review_projection_v1",
        "status": "projected",
        "reason": None,
        "provider_id": _OMNI_PROVIDER_ID,
        "profile_id": _OMNI_PROFILE_ID,
        "provider_version": "recorded-shadow-v1",
        "capture_match_status": "match",
        "region_count": 1,
        "skipped_item_count": 0,
        "safe_reason_counts": {},
        "display_only": True,
        "review_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "action_candidates": [],
    }
    serialized = json.dumps(review, ensure_ascii=False)
    for forbidden in (
        reply["result_ref"]["content_sha256"],
        result["result_id"],
        "source_bbox",
        "capture_bbox",
        "coordinate_transform_ref",
        "opaque_attributes",
        str(tmp_path),
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("case", "items", "reason"),
    [
        (
            "out-of-range-capture-bbox",
            (_recorded_item(source_item_id="outside", bbox=(0, 0, 3, 3)),),
            "item_review_box_out_of_range",
        ),
        (
            "ambiguous-duplicate",
            (
                _recorded_item(source_item_id="duplicate-a"),
                _recorded_item(source_item_id="duplicate-b"),
            ),
            "ambiguous_duplicate_semantic_box",
        ),
    ],
)
def test_review_region_projection_fails_closed_for_unsafe_items(
    tmp_path: Path,
    case: str,
    items: tuple[NormalizedProviderItem, ...],
    reason: str,
) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix=case,
        fail=False,
        items=items,
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")

    review = _load_review(
        root=tmp_path,
        case=case,
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
    )

    assert review["draft"]["regions"] == []
    assert review["draft"]["action_templates"] == []
    assert review["uei_shadow_review_projection"]["status"] == "rejected"
    assert review["uei_shadow_review_projection"]["reason"] == reason
    assert review["uei_shadow_review_projection"]["region_count"] == 0
    assert review["uei_shadow_review_projection"]["action_candidates"] == []


def test_review_region_projection_rejects_capture_mismatch_and_region_id_collision(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="collision-source",
        fail=False,
        items=(_recorded_item(source_item_id="collision-source"),),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    other_reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="other-capture",
        fail=False,
        items=(_recorded_item(source_item_id="other"),),
    )
    other_result = store.get(other_reply["result_ref"], contract_version="provider_safe_result_v1")

    mismatch = _load_review(
        root=tmp_path,
        case="capture-mismatch",
        result_ref=reply["result_ref"],
        capture_ref=other_result["capture_lineage_ref"],
    )
    assert mismatch["draft"]["regions"] == []
    assert mismatch["uei_shadow_review_projection"]["reason"] == "capture_lineage_mismatch"

    first = _load_review(
        root=tmp_path,
        case="collision-first",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
    )
    generated_id = first["draft"]["regions"][0]["region_id"]
    existing = {
        "region_id": generated_id,
        "label": "Human-owned existing region",
        "bbox": {"x": 1, "y": 1, "w": 1, "h": 1},
    }
    collision = _load_review(
        root=tmp_path,
        case="collision-second",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        regions=[existing],
    )
    assert collision["draft"]["regions"] == [existing]
    assert collision["uei_shadow_review_projection"]["reason"] == "region_id_collision"


def test_builtin_projection_and_real_recorded_omni_adapter_share_safe_semantic_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    built_result = _builtin_static_ocr_with_identity_grounding(
        root=tmp_path,
        store=store,
        suffix="provider-equivalence",
    )
    omni_result = _real_recorded_omni_result(
        root=tmp_path,
        store=store,
        monkeypatch=monkeypatch,
    )

    first = built_result["items"][0]
    second = omni_result["items"][0]
    semantic_fields = ("safe_text", "safe_role", "safe_states", "kind")
    first_core = {field: first[field] for field in semantic_fields}
    second_core = {field: second[field] for field in semantic_fields}
    assert first_core == second_core == {
        "safe_text": "Quick Apply",
        "safe_role": None,
        "safe_states": [],
        "kind": "text",
    }
    assert built_result["provider_id"] == "local.runtime/builtin-ocr"
    assert omni_result["provider_id"] == _OMNI_PROVIDER_ID
    assert built_result["provider_version"] == "built-in-v1"
    assert omni_result["provider_version"] != built_result["provider_version"]
    assert first["provider_confidence"] == 0.88
    assert second["provider_confidence"] == 0.9
    assert first["capture_bbox"] == [1, 1, 5, 3]
    assert second["capture_bbox"] == [1, 1, 5, 3]
    assert omni_result["review_only"] is True


@pytest.mark.parametrize(
    ("case", "source_kind", "reason"),
    [
        ("missing-display", "missing", "displayed_source_image_missing"),
        ("wrong-display", "wrong_hash", "displayed_source_image_hash_mismatch"),
        ("wrong-dimensions", "wrong_dimensions", "displayed_source_image_dimensions_mismatch"),
    ],
)
def test_projection_requires_exact_displayed_image_binding(
    tmp_path: Path,
    case: str,
    source_kind: str,
    reason: str,
) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix=case,
        fail=False,
        items=(_recorded_item(source_item_id=case),),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    source_image: Path | None = None
    if source_kind == "wrong_hash":
        source_image = tmp_path / "wrong-source.png"
        Image.new("RGB", (2, 2), color=(90, 80, 70)).save(source_image)
    elif source_kind == "wrong_dimensions":
        source_image = tmp_path / "wrong-dimensions.png"
        Image.new("RGB", (3, 2), color=(10, 20, 30)).save(source_image)
    capture = store.get(
        result["capture_lineage_ref"],
        contract_version="capture_lineage_v1",
    )

    review = _load_review(
        root=tmp_path,
        case=case,
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        source_image_path=source_image,
        declared_source_sha256=(
            capture["artifact_sha256"]
            if source_kind == "wrong_hash"
            else None
        ),
    )

    assert review["draft"]["regions"] == []
    assert review["uei_shadow_review_projection"]["status"] == "rejected"
    assert review["uei_shadow_review_projection"]["reason"] == reason


def test_nested_learning_draft_preserves_current_capture_lineage(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="nested-wrapper",
        fail=False,
        items=(_recorded_item(source_item_id="nested-wrapper"),),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")

    review = _load_review(
        root=tmp_path,
        case="nested-wrapper",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        wrapper=True,
    )

    assert review["uei_shadow_review_projection"]["status"] == "projected"
    assert review["uei_shadow_review_projection"]["capture_match_status"] == "match"
    assert len(review["draft"]["regions"]) == 1


def test_ungrounded_items_are_skipped_without_hiding_grounded_regions(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="mixed-grounding",
        fail=False,
        items=(
            _recorded_item(source_item_id="ungrounded", bbox=None, text="Unlocated label"),
            _recorded_item(source_item_id="grounded", text="Quick Apply"),
        ),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")

    review = _load_review(
        root=tmp_path,
        case="mixed-grounding",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
    )

    assert [region["label"] for region in review["draft"]["regions"]] == ["Quick Apply"]
    projection = review["uei_shadow_review_projection"]
    assert projection["status"] == "projected"
    assert projection["region_count"] == 1
    assert projection["skipped_item_count"] == 1
    assert projection["safe_reason_counts"] == {"ungrounded_item": 1}


def test_region_identity_is_bound_to_capture_lineage_without_exposing_it(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    region_ids: list[str] = []
    for suffix in ("capture-a", "capture-b"):
        reply = _invoke_recorded_shadow(
            root=tmp_path,
            store=store,
            suffix=suffix,
            fail=False,
            items=(_recorded_item(source_item_id="same-provider-item"),),
        )
        result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
        review = _load_review(
            root=tmp_path,
            case=suffix,
            result_ref=reply["result_ref"],
            capture_ref=result["capture_lineage_ref"],
            source_image_path=reply["_test_source_image_path"],
        )
        region_ids.append(review["draft"]["regions"][0]["region_id"])
        serialized = json.dumps(review, ensure_ascii=False)
        assert result["capture_lineage_ref"]["id"] not in serialized
        assert result["capture_lineage_ref"]["content_sha256"] not in serialized

    assert region_ids[0] != region_ids[1]


def test_projected_region_binds_panel_to_immutable_content_addressed_source(tmp_path: Path) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    reply = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="mutable-panel-source",
        fail=False,
        items=(_recorded_item(source_item_id="mutable-panel-source"),),
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    mutable_source = reply["_test_source_image_path"]
    original_bytes = mutable_source.read_bytes()
    original_sha256 = sha256(original_bytes).hexdigest()

    review = _load_review(
        root=tmp_path,
        case="mutable-panel-source",
        result_ref=reply["result_ref"],
        capture_ref=result["capture_lineage_ref"],
        source_image_path=mutable_source,
    )
    screen = review["draft"]["page_details"]["screen"]
    panel_source = tmp_path / screen["source_image_path"]

    assert review["uei_shadow_review_projection"]["status"] == "projected"
    assert panel_source != mutable_source
    assert panel_source.stem == original_sha256
    assert screen["source_image_sha256"] == original_sha256
    assert screen["source_image_materialized_for_panel"] is True
    Image.new("RGB", (2, 2), color=(200, 100, 50)).save(mutable_source)
    assert panel_source.read_bytes() == original_bytes
    assert sha256(panel_source.read_bytes()).hexdigest() == original_sha256


def test_conflicting_valid_capture_lineage_refs_fail_closed_without_priority(
    tmp_path: Path,
) -> None:
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    current = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="lineage-current",
        fail=False,
        items=(_recorded_item(source_item_id="lineage-current"),),
    )
    other = _invoke_recorded_shadow(
        root=tmp_path,
        store=store,
        suffix="lineage-other",
        fail=False,
        items=(_recorded_item(source_item_id="lineage-other"),),
    )
    current_result = store.get(current["result_ref"], contract_version="provider_safe_result_v1")
    other_result = store.get(other["result_ref"], contract_version="provider_safe_result_v1")

    review = _load_review(
        root=tmp_path,
        case="lineage-conflict",
        result_ref=current["result_ref"],
        capture_ref=other_result["capture_lineage_ref"],
        source_image_path=current["_test_source_image_path"],
        wrapper=True,
        top_level_capture_ref=current_result["capture_lineage_ref"],
    )

    assert review["draft"]["regions"] == []
    assert review["uei_shadow_review_projection"]["status"] == "rejected"
    assert review["uei_shadow_review_projection"]["reason"] == "current_capture_lineage_ambiguous"
