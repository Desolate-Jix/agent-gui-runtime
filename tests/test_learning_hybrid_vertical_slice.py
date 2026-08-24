from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image
import pytest

from app.learn.draft_review import load_learning_draft_review
from app.learn.hybrid.contracts import stable_candidate_id
from app.learn.recognition.uei.canonical import seal_immutable


NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


def _capture_bundle(*, image_sha: str) -> dict:
    artifact = seal_immutable({
        "contract_version": "artifact_ref_v1",
        "artifact_id": f"artifact/server-owned/{image_sha}",
        "artifact_sha256": image_sha,
        "media_type": "image/png",
        "byte_length": 1234,
        "restricted": True,
    })
    artifact_ref = {"id": artifact["artifact_id"], "content_sha256": artifact["content_sha256"]}
    lineage = seal_immutable({
        "contract_version": "capture_lineage_v1",
        "capture_id": "capture/recorded-omni/current",
        "artifact_ref": artifact_ref,
        "artifact_sha256": image_sha,
        "image_size": {"width": 160, "height": 90},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-25T00:00:00Z",
    })
    lineage_ref = {"id": lineage["capture_id"], "content_sha256": lineage["content_sha256"]}
    capture_identity = {
        "contract_version": "hybrid_capture_identity_v1",
        "capture_id": lineage["capture_id"],
        "capture_lineage_ref": lineage_ref,
        "capture_lineage": lineage,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "artifact_sha256": image_sha,
        "screenshot_sha256": image_sha,
        "image_size": {"width": 160, "height": 90},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-25T00:00:00Z",
        "workflow_revision": "7",
    }
    context = seal_immutable({
        "contract_version": "hybrid_capture_context_v1",
        "context_id": "hybrid-context/recorded",
        "run_id": "run-recorded",
        "workflow_revision": 7,
        "capture_lineage_ref": lineage_ref,
        "window_binding": {
            "window_binding_id": "window:101",
            "process_id": 202,
            "process_name": "fixture.exe",
            "rect": {"left": 0, "top": 0, "right": 160, "bottom": 90},
        },
        "sources": [],
        "derived_views": [],
        **NON_AUTHORIZING,
    })
    context_ref = {"id": context["context_id"], "content_sha256": context["content_sha256"]}
    bundle = seal_immutable({
        "contract_version": "hybrid_capture_bundle_v1",
        "bundle_id": "hybrid-capture/recorded",
        "run_id": "run-recorded",
        "workflow_revision": 7,
        "capture_lineage_ref": lineage_ref,
        "artifact_ref": artifact_ref,
        "context_ref": context_ref,
        **NON_AUTHORIZING,
    })
    return {**bundle, "capture_identity": capture_identity, "context": context}


def _safe_result(capture_bundle: dict) -> dict:
    generic_ref = {"id": "fixture/ref", "content_sha256": "12" * 32}
    return seal_immutable({
        "contract_version": "provider_safe_result_v1",
        "result_id": "result/recorded-omni/current",
        "request_ref": generic_ref,
        "requested_provider_id": "local.runtime/omniparser",
        "requested_profile_id": "local.runtime/omniparser/shadow-v2",
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": generic_ref,
        "manifest_ref": generic_ref,
        "provider_id": "local.runtime/omniparser",
        "profile_id": "local.runtime/omniparser/shadow-v2",
        "provider_version": "recorded-omni-v1",
        "capture_lineage_ref": deepcopy(capture_bundle["capture_lineage_ref"]),
        "status": "success",
        "review_only": True,
        "items": [
            {
                "source_item_id": "omni/high",
                "source_id_origin": "provider",
                "kind": "element",
                "safe_text": "Quick Apply",
                "safe_role": "button",
                "safe_states": [],
                "source_bbox": [40, 20, 120, 52],
                "capture_bbox": [40, 20, 120, 52],
                "source_coordinate_space": "capture_pixel_xyxy",
                "coordinate_transform_ref": None,
                "opaque_attributes": {"recording": "fixture-a"},
                "provider_confidence": 0.91,
            },
            {
                "source_item_id": "omni/low",
                "source_id_origin": "provider",
                "kind": "icon",
                "safe_text": None,
                "safe_role": None,
                "safe_states": [],
                "source_bbox": [4, 5, 18, 19],
                "capture_bbox": [4, 5, 18, 19],
                "source_coordinate_space": "capture_pixel_xyxy",
                "coordinate_transform_ref": None,
                "opaque_attributes": {"recording": "fixture-b"},
                "provider_confidence": 0.03,
            },
        ],
        "redaction_summary": {
            "redacted_item_count": 0,
            "redacted_field_count": 0,
            "secret_detected": False,
            "sensitive_categories": [],
        },
    })


def _api():
    from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger
    from app.learn.hybrid.review_projection import project_hybrid_review

    return build_omni_candidate_ledger, project_hybrid_review


def _vertical(tmp_path: Path):
    image = tmp_path / "artifacts" / "screenshots" / "recorded.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (160, 90), color=(10, 20, 30)).save(image)
    image_sha = sha256(image.read_bytes()).hexdigest()
    bundle = _capture_bundle(image_sha=image_sha)
    safe_result = _safe_result(bundle)
    build_ledger, project_review = _api()
    ledger = build_ledger(safe_result=safe_result, capture_bundle=bundle)
    review = project_review(
        omni_inventory=ledger,
        capture_bundle=bundle,
        current_capture_lineage_ref=bundle["capture_lineage_ref"],
        displayed_image_sha256=image_sha,
        displayed_image_size={"width": 160, "height": 90},
    )
    return image, bundle, safe_result, ledger, review


def test_recorded_omni_candidates_project_into_large_review_without_authority(tmp_path: Path) -> None:
    image, bundle, _, ledger, projection = _vertical(tmp_path)

    assert len(ledger["candidates"]) == len(projection["candidates"]) == 2
    assert projection["candidates"][0]["candidate_id"].startswith("candidate/")
    assert projection["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert projection["candidates"][1]["confidence"] == 0.03
    assert projection["candidates"][1]["provider_provenance"]["raw_provider_item"]["opaque_attributes"] == {"recording": "fixture-b"}
    assert projection["capture_lineage_ref"] == bundle["capture_lineage_ref"]
    for field, expected in NON_AUTHORIZING.items():
        assert ledger[field] == projection[field] == expected
    assert projection["action_candidates"] == []

    draft_path = tmp_path / "artifacts" / "learning-runs" / "hybrid" / "trial.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(json.dumps({
        "contract_version": "learning_template_draft_v1",
        "capture_lineage_ref": bundle["capture_lineage_ref"],
        "states": [],
        "regions": [],
        "action_templates": [],
        "hybrid_review_projection": projection,
        "page_details": {"screen": {
            "source_image_path": image.relative_to(tmp_path).as_posix(),
            "source_image_sha256": bundle["capture_identity"]["screenshot_sha256"],
        }},
    }), encoding="utf-8")
    loaded = load_learning_draft_review(draft_path, project_root=tmp_path)

    assert [region["candidate_id"] for region in loaded["draft"]["regions"]] == [
        candidate["candidate_id"] for candidate in projection["candidates"]
    ]
    assert loaded["draft"]["regions"][0]["bbox_original"] == [40, 20, 120, 52]
    assert loaded["hybrid_review_projection"]["displayed_image"]["sha256"] == bundle["capture_identity"]["screenshot_sha256"]
    assert loaded["draft"]["action_templates"] == []


def test_ledger_ids_are_stable_and_input_mutation_cannot_change_built_geometry(tmp_path: Path) -> None:
    _, bundle, safe_result, ledger, _ = _vertical(tmp_path)
    build_ledger, _ = _api()
    repeated = build_ledger(safe_result=deepcopy(safe_result), capture_bundle=deepcopy(bundle))
    assert repeated == ledger
    expected = stable_candidate_id(
        provider_result_ref=ledger["provider_result_ref"], source_item_id="omni/high"
    )
    assert ledger["candidates"][0]["candidate_id"] == expected
    safe_result["items"][0]["capture_bbox"][0] = 99
    bundle["capture_identity"]["image_size"]["width"] = 999
    assert ledger["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert ledger["capture_identity"]["image_size"] == {"width": 160, "height": 90}


def test_cross_capture_and_stale_bundle_fail_closed(tmp_path: Path) -> None:
    _, bundle, safe_result, _, _ = _vertical(tmp_path)
    build_ledger, _ = _api()
    cross_capture = deepcopy(safe_result)
    cross_capture["capture_lineage_ref"] = {"id": "capture/other", "content_sha256": "34" * 32}
    cross_capture = seal_immutable(cross_capture)
    with pytest.raises(ValueError, match="capture"):
        build_ledger(safe_result=cross_capture, capture_bundle=bundle)

    stale = deepcopy(bundle)
    stale["workflow_revision"] = 8
    with pytest.raises(ValueError, match="bundle"):
        build_ledger(safe_result=safe_result, capture_bundle=stale)


@pytest.mark.parametrize("mutation", ["omission", "bbox", "missing_provider_item"])
def test_projection_rejects_candidate_ledger_mutation(tmp_path: Path, mutation: str) -> None:
    _, bundle, _, ledger, _ = _vertical(tmp_path)
    _, project_review = _api()
    changed = deepcopy(ledger)
    if mutation == "omission":
        changed["candidates"].pop()
    elif mutation == "bbox":
        changed["candidates"][0]["bbox_original"] = [41, 20, 120, 52]
    else:
        changed["provider_result"]["items"].pop()
        changed["provider_result"] = seal_immutable(changed["provider_result"])
        changed["provider_result_ref"]["content_sha256"] = changed["provider_result"]["content_sha256"]
    with pytest.raises(ValueError):
        project_review(
            omni_inventory=changed,
            capture_bundle=bundle,
            current_capture_lineage_ref=bundle["capture_lineage_ref"],
            displayed_image_sha256=bundle["capture_identity"]["screenshot_sha256"],
            displayed_image_size={"width": 160, "height": 90},
        )


@pytest.mark.parametrize("mismatch", ["hash", "dimensions", "current_capture"])
def test_projection_requires_exact_canonical_display_and_current_capture(tmp_path: Path, mismatch: str) -> None:
    _, bundle, _, ledger, _ = _vertical(tmp_path)
    _, project_review = _api()
    image_sha = bundle["capture_identity"]["screenshot_sha256"]
    size = {"width": 160, "height": 90}
    current_ref = bundle["capture_lineage_ref"]
    if mismatch == "hash":
        image_sha = "56" * 32
    elif mismatch == "dimensions":
        size = {"width": 159, "height": 90}
    else:
        current_ref = {"id": "capture/other", "content_sha256": "78" * 32}
    with pytest.raises(ValueError, match="displayed image|current capture"):
        project_review(
            omni_inventory=ledger,
            capture_bundle=bundle,
            current_capture_lineage_ref=current_ref,
            displayed_image_sha256=image_sha,
            displayed_image_size=size,
        )
