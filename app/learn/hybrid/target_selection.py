"""GUIActor top-1 到已验证 Omni 候选的非授权选择适配器。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from hashlib import sha256
from typing import Any

from app.learn.hybrid.goal_binding_native_adapters import parse_gui_actor_top1
from app.learn.hybrid.goal_binding_provider import map_native_point_to_candidate
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.hybrid.qwen_binding import validate_sealed_omni_inventory

_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "final_submit_forbidden": True,
    "real_action_requires_gate": True,
    "authorization_scope": "display_and_review_only",
}


def parse_gui_actor_selection(
    raw: dict,
    *,
    capture_bundle: dict,
    omni_inventory: dict,
    target_text: str,
) -> dict:
    """仅把冻结 GUIActor top-1 关联到同一 capture 的唯一 Omni 候选。"""
    bundle = validate_current_capture_bundle(capture_bundle)
    inventory = validate_sealed_omni_inventory(omni_inventory)
    capture = bundle["capture_identity"]
    if capture != inventory["capture_identity"]:
        raise ValueError("GUIActor selection capture does not match Omni inventory")
    if not isinstance(target_text, str) or not target_text.strip():
        raise ValueError("GUIActor target_text is required")
    source = _validate_raw(raw)
    if source["capture_id"] != capture["capture_id"] or source["image_sha256"] != capture["screenshot_sha256"]:
        raise ValueError("GUIActor raw output capture identity mismatch")
    profile = source["native_profile"]
    if profile["provider_id"] != source["provider_id"]:
        raise ValueError("GUIActor provider_id does not match sealed native profile")
    image_size = capture["image_size"]
    proposal = parse_gui_actor_top1(
        source["raw_output_utf8"], goal_index=0, profile=profile
    )
    binding = map_native_point_to_candidate(
        proposal=proposal,
        image_size=(image_size["width"], image_size["height"]),
        candidates=inventory["candidates"],
        provider_id=source["provider_id"],
        capture_ref={"id": capture["capture_id"], "sha256": capture["screenshot_sha256"]},
        native_output_ref=source["native_output_ref"],
        omni_snapshot_ref=_goal_ref(inventory["provider_result_ref"]),
    )
    status = _selection_status(binding)
    candidate_id = binding["candidate_id"]
    selected_candidate = next(
        (item for item in inventory["candidates"] if item["candidate_id"] == candidate_id),
        None,
    )
    if candidate_id is not None and selected_candidate is None:
        raise ValueError("GUIActor selection candidate is absent from Omni inventory")
    return {
        "contract_version": "hybrid_target_selection_v1",
        "target_text": target_text,
        "selection_status": status,
        "candidate_id": candidate_id,
        "candidate_source": (
            {"provider_id": inventory["provider_id"], "source_item_id": selected_candidate["source_item_id"]}
            if selected_candidate is not None
            else None
        ),
        "capture": {
            "capture_id": capture["capture_id"],
            "image_sha256": capture["screenshot_sha256"],
            "image_size": deepcopy(image_size),
            "coordinate_space": capture["capture_coordinate_space"],
            "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]),
        },
        "model_proposal": {
            "provider_id": source["provider_id"],
            "native_profile": deepcopy(profile),
            "native_output_ref": deepcopy(source["native_output_ref"]),
            "raw_output_utf8": source["raw_output_utf8"],
            "source_score": source["source_score"],
            "canonical_capture_pixel_point": deepcopy(binding["canonical_capture_pixel_point"]),
            "binding_status": binding["status"],
            "binding_reason": binding["reason"],
        },
        "parent_refs": {
            "capture_lineage_ref": deepcopy(capture["capture_lineage_ref"]),
            "omni_provider_result_ref": deepcopy(inventory["provider_result_ref"]),
            "native_output_ref": deepcopy(source["native_output_ref"]),
        },
        "semantic": {"status": "missing", "provider_id": None, "facts": None},
        **_NON_AUTHORIZING,
    }


def _validate_raw(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("GUIActor raw input must be an object")
    result = deepcopy(dict(value))
    required = {"raw_output_utf8", "native_output_ref", "provider_id", "native_profile", "source_score", "capture_id", "image_sha256"}
    if set(result) != required:
        raise ValueError("GUIActor raw input is not closed")
    raw_output = result["raw_output_utf8"]
    if not isinstance(raw_output, str):
        raise ValueError("GUIActor raw_output_utf8 must be a string")
    raw_output.encode("utf-8", "strict")
    provider_id = result["provider_id"]
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError("GUIActor provider_id is invalid")
    profile = result["native_profile"]
    if not isinstance(profile, Mapping):
        raise ValueError("GUIActor native_profile is invalid")
    profile = deepcopy(dict(profile))
    if (
        profile.get("contract_version") != "goal_binding_native_profile_v1"
        or profile.get("native_shape") != "gui_actor_topk_points_v1"
        or profile.get("coordinate_space") != "normalized_0_1"
    ):
        raise ValueError("GUIActor native_profile is not the sealed top-1 profile")
    native_output_ref = _goal_ref(result["native_output_ref"])
    if native_output_ref["sha256"] != sha256(raw_output.encode("utf-8")).hexdigest():
        raise ValueError("GUIActor native_output_ref does not seal raw UTF-8 output")
    capture_id, image_sha256 = result["capture_id"], result["image_sha256"]
    if not isinstance(capture_id, str) or not capture_id or not isinstance(image_sha256, str) or len(image_sha256) != 64 or any(char not in "0123456789abcdef" for char in image_sha256):
        raise ValueError("GUIActor raw capture identity is invalid")
    score = result["source_score"]
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            raise ValueError("GUIActor source_score must be finite or null")
        score = float(score)
    return {
        "raw_output_utf8": raw_output,
        "native_output_ref": native_output_ref,
        "provider_id": provider_id,
        "native_profile": profile,
        "source_score": score,
        "capture_id": capture_id,
        "image_sha256": image_sha256,
    }


def _goal_ref(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("selection lineage reference is invalid")
    identifier = value.get("id")
    digest = value.get("sha256", value.get("content_sha256"))
    if not isinstance(identifier, str) or not identifier or not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("selection lineage reference is invalid")
    return {"id": identifier, "sha256": digest}


def _selection_status(binding: Mapping[str, object]) -> str:
    if binding.get("status") == "BOUND":
        return "selected"
    if binding.get("status") == "UNBOUND":
        return "ambiguous" if binding.get("reason") == "ambiguous_active_candidate_hit" else "unbound"
    return "provider_failure"


__all__ = ["parse_gui_actor_selection"]
