from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

import pytest


def _facts(tmp_path):
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(tmp_path)
    return facts["bundle"], omni_inventory_from_ledger(facts["ledger"])


def _raw(capture_bundle: dict, **changes: object) -> dict[str, object]:
    raw_output_utf8 = str(changes.pop("raw_output_utf8", '{"topk_points":[[0.5,0.4]]}'))
    value: dict[str, object] = {
        "raw_output_utf8": raw_output_utf8,
        "native_output_ref": {"id": "native/gui-actor/case-1", "sha256": sha256(raw_output_utf8.encode("utf-8")).hexdigest()},
        "provider_id": "gui_actor_3b_bf16",
        "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"},
        "source_score": None,
        "capture_id": capture_bundle["capture_identity"]["capture_id"],
        "image_sha256": capture_bundle["capture_identity"]["screenshot_sha256"],
    }
    value.update(changes)
    return value


def test_gui_actor_top1_selection_preserves_raw_evidence_and_missing_semantics(tmp_path) -> None:
    from app.learn.hybrid.target_selection import parse_gui_actor_selection

    capture_bundle, inventory = _facts(tmp_path)
    result = parse_gui_actor_selection(
        _raw(capture_bundle),
        capture_bundle=capture_bundle,
        omni_inventory=inventory,
        target_text="Quick Apply",
    )

    candidate = inventory["candidates"][0]
    assert result["contract_version"] == "hybrid_target_selection_v1"
    assert result["selection_status"] == "selected"
    assert result["candidate_id"] == candidate["candidate_id"]
    assert result["capture"]["capture_id"] == capture_bundle["capture_identity"]["capture_id"]
    assert result["capture"]["image_sha256"] == capture_bundle["capture_identity"]["screenshot_sha256"]
    assert result["model_proposal"]["raw_output_utf8"] == _raw(capture_bundle)["raw_output_utf8"]
    assert result["model_proposal"]["source_score"] is None
    assert result["semantic"] == {"status": "missing", "provider_id": None, "facts": None}
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False


def test_gui_actor_selection_rejects_cross_capture_and_never_uses_top2(tmp_path) -> None:
    from app.learn.hybrid.target_selection import parse_gui_actor_selection

    capture_bundle, inventory = _facts(tmp_path)
    cross = deepcopy(inventory)
    cross["capture_identity"] = deepcopy(capture_bundle["capture_identity"])
    cross["capture_identity"]["capture_id"] = "capture/other"
    with pytest.raises(ValueError):
        parse_gui_actor_selection(_raw(capture_bundle), capture_bundle=capture_bundle, omni_inventory=cross, target_text="Quick Apply")

    result = parse_gui_actor_selection(
        _raw(capture_bundle, raw_output_utf8='{"topk_points":[[1.0,1.0],[0.5,0.4]]}'),
        capture_bundle=capture_bundle,
        omni_inventory=inventory,
        target_text="Quick Apply",
    )
    assert result["selection_status"] == "provider_failure"
    assert result["candidate_id"] is None
