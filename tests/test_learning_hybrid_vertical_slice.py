from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from PIL import Image

from app.learn.draft_review import load_learning_draft_review
from app.learn.hybrid.review_projection import validate_hybrid_review_projection
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore
from tests.test_learn_hybrid_capture import _context, _identity, _window


NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


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
                "source_item_id": "omni/high", "source_id_origin": "provider",
                "kind": "element", "safe_text": "Quick Apply", "safe_role": "button",
                "safe_states": [], "source_bbox": [40, 20, 120, 52],
                "capture_bbox": [40, 20, 120, 52],
                "source_coordinate_space": "capture_pixel_xyxy",
                "coordinate_transform_ref": None,
                "opaque_attributes": {"recording": "fixture-a"}, "provider_confidence": 0.91,
            },
            {
                "source_item_id": "omni/low", "source_id_origin": "provider",
                "kind": "icon", "safe_text": None, "safe_role": None, "safe_states": [],
                "source_bbox": [4, 5, 18, 19], "capture_bbox": [4, 5, 18, 19],
                "source_coordinate_space": "capture_pixel_xyxy",
                "coordinate_transform_ref": None,
                "opaque_attributes": {"recording": "fixture-b"}, "provider_confidence": 0.03,
            },
        ],
        "redaction_summary": {
            "redacted_item_count": 0, "redacted_field_count": 0,
            "secret_detected": False, "sensitive_categories": [],
        },
    })


def _vertical(tmp_path: Path) -> dict:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle
    from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger
    from app.learn.hybrid.review_projection import project_hybrid_review

    image, identity = _identity(
        tmp_path, run_id="run-recorded", revision=7,
        name="recorded.png", size=(160, 90),
    )
    bundle = seal_hybrid_capture_bundle(
        project_root=tmp_path, image_path=image, run_id="run-recorded",
        workflow_revision=7, window_binding=_window(),
        ocr_uia_context=_context(
            tmp_path, identity, run_id="run-recorded", revision=7,
        ),
        capture_envelope=identity.capture_envelope,
    )
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    provider_ref = store.put(_safe_result(bundle))
    safe_result = store.get(provider_ref, contract_version="provider_safe_result_v1")
    ledger = build_omni_candidate_ledger(safe_result=safe_result, capture_bundle=bundle)
    projected = project_hybrid_review(
        project_root=tmp_path, omni_ledger=ledger,
        displayed_image_sha256=identity["screenshot_sha256"],
        displayed_image_size=identity["image_size"],
    )
    return {
        "image": image, "bundle": bundle, "safe_result": safe_result,
        "provider_ref": provider_ref, "ledger": ledger, "projected": projected,
    }


def _write_draft(
    root: Path, facts: dict, *, projection_ref: object | None = None,
    embedded_projection: object | None = None, case: str = "valid",
) -> Path:
    draft: dict[str, object] = {
        "contract_version": "learning_template_draft_v1",
        "capture_lineage_ref": facts["bundle"]["capture_lineage_ref"],
        "states": [], "regions": [], "action_templates": [],
        "page_details": {"screen": {
            "source_image_path": facts["image"].relative_to(root).as_posix(),
            "source_image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"],
        }},
    }
    if projection_ref is not None:
        draft["hybrid_review_projection_ref"] = projection_ref
    if embedded_projection is not None:
        draft["hybrid_review_projection"] = embedded_projection
    path = root / "artifacts" / "learning-runs" / case / "trial.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    return path


def _load(root: Path, path: Path, *, expectations: bool = True) -> dict:
    kwargs = (
        {"expected_hybrid_run_id": "run-recorded", "expected_hybrid_workflow_revision": 7}
        if expectations else {}
    )
    return load_learning_draft_review(path, project_root=root, **kwargs)


def _reidentify_and_reseal_projection(value: dict) -> dict:
    forged = deepcopy(value)
    forged.pop("content_sha256", None)
    forged["projection_id"] = ""
    forged["projection_id"] = "hybrid-review-projection/" + sha256(
        canonical_json_bytes(forged)
    ).hexdigest()
    forged = seal_immutable(forged)
    assert validate_hybrid_review_projection(forged) == forged
    return forged


def test_persisted_omni_projection_loads_all_candidates_without_authority(tmp_path: Path) -> None:
    facts = _vertical(tmp_path)
    projected, ledger = facts["projected"], facts["ledger"]
    assert projected["projection_ref"]["id"].startswith("hybrid-review-projection/")
    assert ledger["hybrid_capture_bundle_ref"] == facts["bundle"]["bundle_ref"]
    assert ledger["provider_result_ref"] == facts["provider_ref"]
    assert len(ledger["candidates"]) == len(projected["candidates"]) == 2
    assert projected["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert projected["candidates"][1]["confidence"] == 0.03
    for field, expected in NON_AUTHORIZING.items():
        assert ledger[field] == projected[field] == expected

    path = _write_draft(tmp_path, facts, projection_ref=projected["projection_ref"])
    loaded = _load(tmp_path, path)
    assert [item["candidate_id"] for item in loaded["draft"]["regions"]] == [
        item["candidate_id"] for item in projected["candidates"]
    ]
    raw = loaded["draft"]["regions"][1]["provider_provenance"]["raw_provider_item"]
    assert raw["opaque_attributes"] == {"recording": "fixture-b"}
    assert loaded["draft"]["action_templates"] == []
    assert loaded["hybrid_review_projection_ref"] == projected["projection_ref"]


def test_hybrid_ref_requires_authoritative_run_and_revision(tmp_path: Path) -> None:
    facts = _vertical(tmp_path)
    path = _write_draft(tmp_path, facts, projection_ref=facts["projected"]["projection_ref"])
    loaded = _load(tmp_path, path, expectations=False)
    assert loaded["draft"]["regions"] == []
    assert loaded["hybrid_review_projection_status"]["reason"] == "hybrid_expectations_missing"


@pytest.mark.parametrize("source", ["embedded", "embedded_with_ref", "nonexistent"])
def test_draft_cannot_supply_hybrid_evidence_without_a_valid_store_ref(tmp_path: Path, source: str) -> None:
    facts = _vertical(tmp_path)
    if source in {"embedded", "embedded_with_ref"}:
        path = _write_draft(
            tmp_path, facts,
            projection_ref=(
                facts["projected"]["projection_ref"]
                if source == "embedded_with_ref" else None
            ),
            embedded_projection=deepcopy(facts["projected"]), case=source,
        )
    else:
        path = _write_draft(
            tmp_path, facts,
            projection_ref={"id": "hybrid-review-projection/missing", "content_sha256": "ab" * 32},
            case=source,
        )
    loaded = _load(tmp_path, path)
    assert loaded["draft"]["regions"] == []
    assert loaded["hybrid_review_projection_status"]["status"] == "rejected"


@pytest.mark.parametrize(
    "mutation", ["omission", "bbox", "provider_ref", "candidate_ref", "raw_provider_item"]
)
def test_resealed_projection_mutations_fail_closed(tmp_path: Path, mutation: str) -> None:
    facts = _vertical(tmp_path)
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    stored = store.get(
        facts["projected"]["projection_ref"], contract_version="hybrid_review_projection_v1",
    )
    if mutation == "omission":
        stored["candidates"].pop()
    elif mutation == "bbox":
        stored["candidates"][0]["bbox_original"] = [41, 20, 120, 52]
    elif mutation == "provider_ref":
        stored["provider_result_ref"] = {"id": "result/other", "content_sha256": "34" * 32}
    elif mutation == "candidate_ref":
        stored["candidates"][0]["provider_result_ref"] = {
            "id": "result/other", "content_sha256": "34" * 32,
        }
    else:
        provider = store.get(
            facts["provider_ref"], contract_version="provider_safe_result_v1"
        )
        provider["items"][0]["opaque_attributes"]["recording"] = "resealed-mutation"
        stored["provider_result_ref"] = store.put(seal_immutable(provider))
    forged_ref = store.put(_reidentify_and_reseal_projection(stored))
    path = _write_draft(tmp_path, facts, projection_ref=forged_ref, case=mutation)
    loaded = _load(tmp_path, path)
    assert loaded["draft"]["regions"] == []
    assert loaded["hybrid_review_projection_status"]["reason"] == "hybrid_projection_evidence_mismatch"


def test_stale_or_cross_run_bundle_fails_closed(tmp_path: Path) -> None:
    facts = _vertical(tmp_path)
    path = _write_draft(tmp_path, facts, projection_ref=facts["projected"]["projection_ref"])
    for run_id, revision in (("run-other", 7), ("run-recorded", 8)):
        loaded = load_learning_draft_review(
            path, project_root=tmp_path, expected_hybrid_run_id=run_id,
            expected_hybrid_workflow_revision=revision,
        )
        assert loaded["draft"]["regions"] == []
        assert loaded["hybrid_review_projection_status"]["status"] == "rejected"


def test_same_run_cross_capture_bundle_fails_closed(tmp_path: Path) -> None:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle, seal_hybrid_capture_identity

    facts = _vertical(tmp_path)
    cross_image = tmp_path / "artifacts" / "screenshots" / "cross.png"
    Image.new("RGB", (160, 90), color=(90, 80, 70)).save(cross_image)
    cross_identity = seal_hybrid_capture_identity(
        project_root=tmp_path, image_path=cross_image, run_id="run-recorded",
        workflow_revision=7, window_binding=_window(),
        captured_at="2026-08-25T00:00:00Z",
    )
    cross_bundle = seal_hybrid_capture_bundle(
        project_root=tmp_path, image_path=cross_image, run_id="run-recorded",
        workflow_revision=7, window_binding=_window(),
        ocr_uia_context=_context(
            tmp_path, cross_identity, run_id="run-recorded", revision=7,
        ),
        capture_envelope=cross_identity.capture_envelope,
    )
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    stored = store.get(
        facts["projected"]["projection_ref"], contract_version="hybrid_review_projection_v1"
    )
    stored["hybrid_capture_bundle_ref"] = cross_bundle["bundle_ref"]
    forged_ref = store.put(_reidentify_and_reseal_projection(stored))
    path = _write_draft(tmp_path, facts, projection_ref=forged_ref, case="cross-capture")
    loaded = _load(tmp_path, path)
    assert loaded["draft"]["regions"] == []
    assert loaded["hybrid_review_projection_status"]["reason"] == "hybrid_projection_evidence_mismatch"


def test_returned_review_projection_regions_and_input_do_not_alias(tmp_path: Path) -> None:
    facts = _vertical(tmp_path)
    original_projection = deepcopy(facts["projected"])
    path = _write_draft(tmp_path, facts, projection_ref=facts["projected"]["projection_ref"])
    loaded = _load(tmp_path, path)
    loaded["draft"]["regions"][0]["bbox_original"][0] = 999
    loaded["hybrid_review_projection"]["candidates"][0]["bbox_original"][0] = 998
    facts["projected"]["candidates"][0]["bbox_original"][0] = 997

    reloaded = _load(tmp_path, path)
    assert reloaded["draft"]["regions"][0]["bbox_original"] == [40, 20, 120, 52]
    assert reloaded["hybrid_review_projection"]["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert original_projection["candidates"][0]["bbox_original"] == [40, 20, 120, 52]


def test_ledger_rejects_cross_capture_provider_and_stale_bundle_mutation(tmp_path: Path) -> None:
    from app.learn.hybrid.omni_candidates import build_omni_candidate_ledger

    facts = _vertical(tmp_path)
    cross = deepcopy(facts["safe_result"])
    cross["capture_lineage_ref"] = {"id": "capture/other", "content_sha256": "56" * 32}
    with pytest.raises(ValueError, match="capture"):
        build_omni_candidate_ledger(
            safe_result=seal_immutable(cross), capture_bundle=facts["bundle"],
        )
    stale = deepcopy(facts["bundle"])
    stale["workflow_revision"] = 8
    with pytest.raises(ValueError, match="bundle"):
        build_omni_candidate_ledger(safe_result=facts["safe_result"], capture_bundle=stale)
