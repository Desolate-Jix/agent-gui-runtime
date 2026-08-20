from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from statistics import median
from typing import Any

import cv2


CARD_ROLES = {
    "card",
    "media_card_group",
    "news_card",
    "recommendation_item",
    "tile_card",
    "tile_card_parent",
}


def apply_card_layout_review_enhancement(
    *,
    image_path: str | Path,
    numbered_regions: list[dict[str, Any]],
    minimum_group_size: int = 3,
    stage2_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把重复卡片布局证据写回学习候选，且始终保持只读和待审核。"""

    enhanced_regions = deepcopy(numbered_regions)
    candidate_locations: dict[str, tuple[int, str, int]] = {}
    candidates: list[dict[str, Any]] = []
    duplicate_candidate_ids: list[str] = []
    for region_index, region in enumerate(enhanced_regions):
        for collection_name in ("subregion_groups", "numbered_items"):
            collection = region.get(collection_name)
            if not isinstance(collection, list):
                continue
            for item_index, item in enumerate(collection):
                if not isinstance(item, dict):
                    continue
                if item.get("layout_neighbor_proposal") is True:
                    continue
                role = str(item.get("role") or item.get("box_type") or "").casefold()
                if role not in CARD_ROLES or not _bbox(item.get("bbox")):
                    continue
                candidate_id = _candidate_id(item)
                if candidate_id in candidate_locations:
                    duplicate_candidate_ids.append(candidate_id)
                    continue
                candidate_locations[candidate_id] = (
                    region_index,
                    collection_name,
                    item_index,
                )
                candidates.append(deepcopy(item))

    if not candidates:
        return _layout_review_enhancement_result(
            regions=enhanced_regions,
            status="no_eligible_card_evidence",
            eligible_candidate_count=0,
            normalized_existing_card_count=0,
            neighbor_proposal_count=0,
            duplicate_candidate_ids=duplicate_candidate_ids,
            regularization=None,
            neighbor_inference=None,
            stage2_policy=stage2_policy,
        )

    try:
        regularization = regularize_repeated_card_layout(
            image_path=image_path,
            candidates=candidates,
            minimum_group_size=minimum_group_size,
        )
    except ValueError as exc:
        result = _layout_review_enhancement_result(
            regions=enhanced_regions,
            status="image_unavailable",
            eligible_candidate_count=len(candidates),
            normalized_existing_card_count=0,
            neighbor_proposal_count=0,
            duplicate_candidate_ids=duplicate_candidate_ids,
            regularization=None,
            neighbor_inference=None,
            stage2_policy=stage2_policy,
        )
        result["report"]["error"] = str(exc)
        return result
    normalized_candidate_ids: list[str] = []
    for alignment_group in regularization.get("alignment_groups") or []:
        for item in alignment_group.get("items") or []:
            candidate_id = str(item.get("source_candidate_id") or "")
            location = candidate_locations.get(candidate_id)
            normalized_bbox = _bbox(item.get("layout_normalized_bbox"))
            if location is None or normalized_bbox is None:
                continue
            region_index, collection_name, item_index = location
            target = enhanced_regions[region_index][collection_name][item_index]
            target.setdefault("source_bbox", deepcopy(target.get("bbox")))
            target["bbox"] = normalized_bbox
            target["layout_review_regularized"] = True
            target["layout_review_group_id"] = str(alignment_group.get("group_id") or "")
            target["layout_review_geometry_source"] = str(
                alignment_group.get("geometry_source") or ""
            )
            target["layout_review_adjustment_px"] = deepcopy(
                item.get("adjustment_px") or {}
            )
            target["review_required"] = True
            target["display_only"] = True
            target["execute_binding_enabled"] = False
            target["artifact_is_authorization"] = False
            normalized_candidate_ids.append(candidate_id)

    updated_candidates = [
        deepcopy(enhanced_regions[region_index][collection_name][item_index])
        for region_index, collection_name, item_index in candidate_locations.values()
    ]
    neighbor_inference = infer_neighbor_card_candidates(
        image_path=image_path,
        candidates=updated_candidates,
        minimum_group_size=minimum_group_size,
    )
    proposal_ids: list[str] = []
    for proposal in neighbor_inference.get("proposals") or []:
        proposal_bbox = _bbox(proposal.get("bbox"))
        if proposal_bbox is None:
            continue
        destination_index = _smallest_containing_region_index(
            enhanced_regions,
            proposal_bbox,
        )
        if destination_index is None:
            continue
        destination = enhanced_regions[destination_index]
        subregion_groups = destination.setdefault("subregion_groups", [])
        if not isinstance(subregion_groups, list):
            continue
        if _proposal_duplicates_existing_group(proposal_bbox, subregion_groups):
            continue
        proposal_id = _unique_proposal_id(
            str(proposal.get("proposal_id") or "neighbor_card"),
            enhanced_regions,
        )
        subregion_groups.append(
            {
                "group_id": proposal_id,
                "label": "Nearby repeated card candidate",
                "role": str(proposal.get("role_candidate") or "tile_card_parent"),
                "bbox": proposal_bbox,
                "source_bbox": deepcopy(proposal_bbox),
                "member_item_ids": [],
                "parent_region_id": str(destination.get("region_id") or ""),
                "candidate_only": True,
                "review_required": True,
                "render_in_main_overlay": True,
                "layout_neighbor_proposal": True,
                "inference_source": str(proposal.get("inference_source") or ""),
                "source_seed_candidate_ids": deepcopy(
                    proposal.get("source_seed_candidate_ids") or []
                ),
                "score": float(proposal.get("score") or 0.0),
                "status": "needs_human_review",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        proposal_ids.append(proposal_id)

    status = (
        "review_geometry_and_neighbor_candidates_generated"
        if normalized_candidate_ids and proposal_ids
        else "review_geometry_generated"
        if normalized_candidate_ids
        else "neighbor_candidates_generated"
        if proposal_ids
        else "insufficient_repeated_layout_evidence"
    )
    return _layout_review_enhancement_result(
        regions=enhanced_regions,
        status=status,
        eligible_candidate_count=len(candidates),
        normalized_existing_card_count=len(normalized_candidate_ids),
        neighbor_proposal_count=len(proposal_ids),
        duplicate_candidate_ids=duplicate_candidate_ids,
        regularization=regularization,
        neighbor_inference=neighbor_inference,
        normalized_candidate_ids=normalized_candidate_ids,
        proposal_ids=proposal_ids,
        stage2_policy=stage2_policy,
    )


def regularize_repeated_card_layout(
    *,
    image_path: str | Path,
    candidates: list[dict[str, Any]],
    minimum_group_size: int = 3,
) -> dict[str, Any]:
    source = Path(image_path)
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError(f"cannot read layout regularization image: {source}")
    image_height, image_width = image.shape[:2]
    minimum_group_size = max(3, int(minimum_group_size))

    source_candidates = [
        deepcopy(item)
        for item in candidates
        if _candidate_is_eligible(item, image_width=image_width, image_height=image_height)
    ]
    visual_rectangles = _detect_visual_rectangles(image)
    size_clusters = _cluster_rectangles_by_size(
        visual_rectangles,
        minimum_group_size=minimum_group_size,
    )
    inferred_grid_slots = _infer_repeated_grid_slots(
        visual_rectangles,
        minimum_group_size=minimum_group_size,
    )
    repeated_rectangles = {
        rectangle["visual_id"]: rectangle
        for rectangle in [
            *(rectangle for cluster in size_clusters for rectangle in cluster),
            *inferred_grid_slots,
        ]
    }

    assignments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unregularized: list[dict[str, Any]] = []
    for candidate in source_candidates:
        visual = _best_visual_rectangle(candidate, repeated_rectangles.values())
        candidate_id = _candidate_id(candidate)
        if visual is None:
            unregularized.append(
                {
                    "source_candidate_id": candidate_id,
                    "source_candidate_bbox": deepcopy(candidate["bbox"]),
                    "reason": "no_repeated_size_cluster",
                }
            )
            continue
        assignments[visual["visual_id"]].append(candidate)

    assigned_rectangles = [
        {
            **deepcopy(rectangle),
            "source_candidates": assignments[rectangle["visual_id"]],
        }
        for rectangle in repeated_rectangles.values()
        if assignments.get(rectangle["visual_id"])
    ]
    row_groups = _cluster_assigned_rectangles_by_row(
        assigned_rectangles,
        minimum_group_size=minimum_group_size,
    )

    aligned_visual_ids: set[str] = set()
    alignment_groups: list[dict[str, Any]] = []
    for group_index, row in enumerate(row_groups, start=1):
        canonical_y = round(median(rectangle["bbox"]["y"] for rectangle in row))
        canonical_h = round(median(rectangle["bbox"]["h"] for rectangle in row))
        canonical_w = round(median(rectangle["bbox"]["w"] for rectangle in row))
        items: list[dict[str, Any]] = []
        for rectangle in sorted(row, key=lambda item: item["bbox"]["x"]):
            aligned_visual_ids.add(rectangle["visual_id"])
            source_candidates_for_rect = rectangle["source_candidates"]
            primary = source_candidates_for_rect[0]
            raw_bbox = deepcopy(rectangle["bbox"])
            normalized_bbox = {
                "x": raw_bbox["x"],
                "y": canonical_y,
                "w": canonical_w,
                "h": canonical_h,
            }
            items.append(
                {
                    "source_candidate_id": _candidate_id(primary),
                    "source_candidate_ids": [
                        _candidate_id(candidate) for candidate in source_candidates_for_rect
                    ],
                    "source_candidate_bbox": deepcopy(primary["bbox"]),
                    "raw_bbox": raw_bbox,
                    "layout_normalized_bbox": normalized_bbox,
                    "adjustment_px": _bbox_adjustment(raw_bbox, normalized_bbox),
                    "visual_evidence_sources": list(rectangle["sources"]),
                }
            )
        alignment_groups.append(
            {
                "group_id": f"layout_row_{group_index}",
                "status": "layout_normalized_for_review",
                "geometry_source": _row_geometry_source(row),
                "support_count": len(items),
                "canonical_geometry": {
                    "y": canonical_y,
                    "w": canonical_w,
                    "h": canonical_h,
                },
                "items": items,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )

    for rectangle in assigned_rectangles:
        if rectangle["visual_id"] in aligned_visual_ids:
            continue
        for candidate in rectangle["source_candidates"]:
            unregularized.append(
                {
                    "source_candidate_id": _candidate_id(candidate),
                    "source_candidate_bbox": deepcopy(candidate["bbox"]),
                    "raw_visual_bbox": deepcopy(rectangle["bbox"]),
                    "reason": "insufficient_row_support",
                }
            )

    normalized_card_count = sum(group["support_count"] for group in alignment_groups)
    return {
        "contract_version": "learn_layout_regularization_experiment_v1",
        "status": (
            "layout_groups_generated"
            if alignment_groups
            else "insufficient_repeated_layout_evidence"
        ),
        "source_image_path": str(source),
        "image_size": {"width": image_width, "height": image_height},
        "eligible_candidate_count": len(source_candidates),
        "visual_rectangle_count": len(visual_rectangles),
        "repeated_size_cluster_count": len(size_clusters),
        "inferred_grid_slot_count": len(inferred_grid_slots),
        "alignment_group_count": len(alignment_groups),
        "normalized_card_count": normalized_card_count,
        "alignment_groups": alignment_groups,
        "unregularized_candidates": unregularized,
        "policy": {
            "minimum_group_size": minimum_group_size,
            "raw_bbox_preserved": True,
            "normalization_scope": "repeated_visual_card_rows_only",
            "no_group_no_change": True,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def infer_neighbor_card_candidates(
    *,
    image_path: str | Path,
    candidates: list[dict[str, Any]],
    minimum_group_size: int = 3,
    minimum_visual_support: float = 0.45,
) -> dict[str, Any]:
    source = Path(image_path)
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError(f"cannot read neighbor card inference image: {source}")
    image_height, image_width = image.shape[:2]
    minimum_group_size = max(3, int(minimum_group_size))
    minimum_visual_support = min(1.0, max(0.0, float(minimum_visual_support)))

    source_candidates = [
        deepcopy(item)
        for item in candidates
        if _candidate_is_eligible(item, image_width=image_width, image_height=image_height)
    ]
    visual_rectangles = _detect_visual_rectangles(image)
    inferred_grid_slots = _infer_repeated_grid_slots(
        visual_rectangles,
        minimum_group_size=minimum_group_size,
    )
    rows = _grid_slots_by_row(inferred_grid_slots)

    slot_seeds: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in source_candidates:
        slot = _best_visual_rectangle(candidate, inferred_grid_slots)
        if slot is not None:
            slot_seeds[slot["visual_id"]].append(candidate)

    proposals: list[dict[str, Any]] = []
    rejected_neighbor_slots: list[dict[str, Any]] = []
    supported_row_count = 0
    for row_index, row in enumerate(rows, start=1):
        ordered = sorted(row, key=lambda item: item["bbox"]["x"])
        seed_columns = [
            index
            for index, slot in enumerate(ordered)
            if slot_seeds.get(slot["visual_id"])
        ]
        if not _has_adjacent_seed_pair(seed_columns):
            continue
        supported_row_count += 1
        seed_ids = [
            _candidate_id(candidate)
            for slot in ordered
            for candidate in slot_seeds.get(slot["visual_id"], [])
        ]
        for column_index, slot in enumerate(ordered):
            if slot_seeds.get(slot["visual_id"]):
                continue
            neighbor_distance = min(abs(column_index - seed) for seed in seed_columns)
            if neighbor_distance != 1:
                continue
            wide_semantic_candidate = _wide_semantic_candidate_covering_slot(
                slot["bbox"],
                source_candidates,
            )
            if wide_semantic_candidate is not None:
                rejected_neighbor_slots.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index + 1,
                        "bbox": deepcopy(slot["bbox"]),
                        "source_candidate_id": _candidate_id(wide_semantic_candidate),
                        "reason": "existing_wide_semantic_card_covers_slot",
                    }
                )
                continue
            visual_support, supporting_rectangle = _slot_direct_visual_evidence(
                slot["bbox"],
                visual_rectangles,
            )
            if (
                supporting_rectangle is not None
                and supporting_rectangle["bbox"]["w"] > slot["bbox"]["w"] * 1.35
                and _wide_parent_covers_seed_slot(
                    supporting_rectangle["bbox"],
                    ordered,
                    slot_seeds,
                    excluded_slot_id=slot["visual_id"],
                )
            ):
                rejected_neighbor_slots.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index + 1,
                        "bbox": deepcopy(slot["bbox"]),
                        "visual_support": round(visual_support, 4),
                        "reason": "shared_wide_parent_already_has_seed",
                    }
                )
                continue
            if visual_support < minimum_visual_support:
                rejected_neighbor_slots.append(
                    {
                        "row_index": row_index,
                        "column_index": column_index + 1,
                        "bbox": deepcopy(slot["bbox"]),
                        "visual_support": round(visual_support, 4),
                        "reason": "insufficient_direct_visual_support",
                    }
                )
                continue
            score_components = {
                "adjacent_confirmed_seed_pair": 1.0,
                "one_hop_neighbor": 1.0,
                "direct_visual_support": round(visual_support, 4),
                "repeated_grid_structure": 1.0,
            }
            score = (
                score_components["adjacent_confirmed_seed_pair"] * 0.35
                + score_components["one_hop_neighbor"] * 0.25
                + score_components["direct_visual_support"] * 0.30
                + score_components["repeated_grid_structure"] * 0.10
            )
            proposals.append(
                {
                    "proposal_id": (
                        f"neighbor_card_row_{row_index}_column_{column_index + 1}"
                    ),
                    "bbox": deepcopy(slot["bbox"]),
                    "role_candidate": "tile_card_parent",
                    "inference_source": "one_hop_same_class_neighbor_prior",
                    "source_seed_candidate_ids": seed_ids,
                    "neighbor_distance_columns": neighbor_distance,
                    "score": round(score, 4),
                    "score_components": score_components,
                    "status": "needs_human_review",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )

    proposals.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
    return {
        "contract_version": "learn_neighbor_card_inference_experiment_v1",
        "status": (
            "neighbor_card_candidates_generated"
            if proposals
            else "insufficient_neighbor_card_evidence"
        ),
        "source_image_path": str(source),
        "image_size": {"width": image_width, "height": image_height},
        "eligible_candidate_count": len(source_candidates),
        "seed_candidate_count": sum(len(items) for items in slot_seeds.values()),
        "seed_slot_count": len(slot_seeds),
        "visual_rectangle_count": len(visual_rectangles),
        "inferred_grid_slot_count": len(inferred_grid_slots),
        "supported_row_count": supported_row_count,
        "proposal_count": len(proposals),
        "proposals": proposals,
        "rejected_neighbor_slots": rejected_neighbor_slots,
        "policy": {
            "minimum_group_size": minimum_group_size,
            "minimum_visual_support": minimum_visual_support,
            "requires_adjacent_confirmed_seed_pair": True,
            "maximum_neighbor_distance_columns": 1,
            "inferred_proposals_can_seed_more_proposals": False,
            "empty_grid_slots_without_visual_support_are_rejected": True,
        },
        "interpretation": (
            "review-only one-hop same-class neighbor proposals; this does not establish "
            "card recognition reliability and does not authorize Execute"
        ),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _candidate_is_eligible(
    item: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
) -> bool:
    if not isinstance(item, dict) or item.get("render_in_main_overlay") is False:
        return False
    if item.get("layout_neighbor_proposal") is True:
        return False
    role = str(item.get("role") or item.get("box_type") or "").casefold()
    if role not in CARD_ROLES:
        return False
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    return _inside_image(bbox, width=image_width, height=image_height)


def _layout_review_enhancement_result(
    *,
    regions: list[dict[str, Any]],
    status: str,
    eligible_candidate_count: int,
    normalized_existing_card_count: int,
    neighbor_proposal_count: int,
    duplicate_candidate_ids: list[str],
    regularization: dict[str, Any] | None,
    neighbor_inference: dict[str, Any] | None,
    normalized_candidate_ids: list[str] | None = None,
    proposal_ids: list[str] | None = None,
    stage2_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repeated_layout_policy = (
        stage2_policy.get("repeated_peer_layout_review")
        if isinstance(stage2_policy, dict)
        and isinstance(stage2_policy.get("repeated_peer_layout_review"), dict)
        else {}
    )
    visual_evidence_triggered = (
        normalized_existing_card_count > 0 or neighbor_proposal_count > 0
    )
    return {
        "contract_version": "learn_card_layout_review_enhancement_v1",
        "regions": regions,
        "report": {
            "status": status,
            "eligible_candidate_count": eligible_candidate_count,
            "normalized_existing_card_count": normalized_existing_card_count,
            "neighbor_proposal_count": neighbor_proposal_count,
            "normalized_candidate_ids": normalized_candidate_ids or [],
            "neighbor_proposal_ids": proposal_ids or [],
            "duplicate_candidate_ids": duplicate_candidate_ids,
            "regularization": deepcopy(regularization),
            "neighbor_inference": deepcopy(neighbor_inference),
            "class_rule_context": {
                "content_adapter_id": (
                    str(stage2_policy.get("content_adapter_id") or "")
                    if isinstance(stage2_policy, dict)
                    else ""
                ),
                "class_prior": str(
                    repeated_layout_policy.get("class_prior") or "not_declared"
                ),
                "peer_item_family": str(
                    repeated_layout_policy.get("peer_item_family") or ""
                ),
                "activation": str(
                    repeated_layout_policy.get("activation")
                    or "current_visual_repetition_required"
                ),
                "can_create_without_visual_support": False,
                "triggered_by_current_visual_evidence": visual_evidence_triggered,
            },
            "interpretation": (
                "Repeated-layout geometry and one-hop neighbor candidates are review evidence only; "
                "they do not establish recognition reliability or authorize Execute."
            ),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _smallest_containing_region_index(
    regions: list[dict[str, Any]],
    bbox: dict[str, int],
) -> int | None:
    matches: list[tuple[int, int]] = []
    for index, region in enumerate(regions):
        region_bbox = _bbox(
            region.get("input_region_bbox")
            or region.get("bbox")
            or region.get("parent_region_bbox")
        )
        if region_bbox is None or not _contains_center(region_bbox, bbox):
            continue
        matches.append((region_bbox["w"] * region_bbox["h"], index))
    return min(matches)[1] if matches else None


def _proposal_duplicates_existing_group(
    proposal_bbox: dict[str, int],
    groups: list[dict[str, Any]],
) -> bool:
    return any(
        isinstance(group, dict)
        and (group_bbox := _bbox(group.get("bbox"))) is not None
        and _bbox_iou(proposal_bbox, group_bbox) >= 0.72
        for group in groups
    )


def _unique_proposal_id(
    source_id: str,
    regions: list[dict[str, Any]],
) -> str:
    existing_ids = {
        str(group.get("group_id") or "")
        for region in regions
        for group in (
            region.get("subregion_groups")
            if isinstance(region.get("subregion_groups"), list)
            else []
        )
        if isinstance(group, dict)
    }
    base = f"layout_review_{source_id}"
    if base not in existing_ids:
        return base
    suffix = 2
    while f"{base}_{suffix}" in existing_ids:
        suffix += 1
    return f"{base}_{suffix}"


def _detect_visual_rectangles(image: Any) -> list[dict[str, Any]]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    masks = {
        "bright_region": cv2.inRange(gray, 232, 255),
        "edge_region": cv2.dilate(
            cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120),
            None,
            iterations=1,
        ),
    }
    rectangles: list[dict[str, Any]] = []
    for source, mask in masks.items():
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, rect_w, rect_h = cv2.boundingRect(contour)
            bbox = {"x": int(x), "y": int(y), "w": int(rect_w), "h": int(rect_h)}
            if not _credible_visual_rectangle(
                bbox,
                contour_area=float(cv2.contourArea(contour)),
                image_width=width,
                image_height=height,
            ):
                continue
            rectangles.append(
                {
                    "visual_id": f"{source}_{len(rectangles) + 1}",
                    "bbox": bbox,
                    "sources": [source],
                }
            )
    return _dedupe_visual_rectangles(rectangles)


def _credible_visual_rectangle(
    bbox: dict[str, int],
    *,
    contour_area: float,
    image_width: int,
    image_height: int,
) -> bool:
    width = bbox["w"]
    height = bbox["h"]
    area = width * height
    image_area = image_width * image_height
    if width < max(80, round(image_width * 0.035)):
        return False
    if height < max(60, round(image_height * 0.04)):
        return False
    if width > image_width * 0.45 or height > image_height * 0.55:
        return False
    if area < image_area * 0.003 or area > image_area * 0.2:
        return False
    rectangularity = contour_area / max(1.0, float(area))
    return rectangularity >= 0.55


def _dedupe_visual_rectangles(rectangles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for rectangle in sorted(
        rectangles,
        key=lambda item: item["bbox"]["w"] * item["bbox"]["h"],
        reverse=True,
    ):
        duplicate = next(
            (
                existing
                for existing in kept
                if _bbox_iou(existing["bbox"], rectangle["bbox"]) >= 0.82
            ),
            None,
        )
        if duplicate is None:
            kept.append(deepcopy(rectangle))
            continue
        duplicate["sources"] = sorted(
            set(duplicate.get("sources", [])) | set(rectangle.get("sources", []))
        )
    for index, rectangle in enumerate(kept, start=1):
        rectangle["visual_id"] = f"visual_rect_{index}"
    return kept


def _cluster_rectangles_by_size(
    rectangles: list[dict[str, Any]],
    *,
    minimum_group_size: int,
) -> list[list[dict[str, Any]]]:
    pending = sorted(
        rectangles,
        key=lambda item: item["bbox"]["w"] * item["bbox"]["h"],
        reverse=True,
    )
    clusters: list[list[dict[str, Any]]] = []
    while pending:
        seed = pending.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            canonical_w = median(item["bbox"]["w"] for item in cluster)
            canonical_h = median(item["bbox"]["h"] for item in cluster)
            for item in list(pending):
                if _relative_delta(item["bbox"]["w"], canonical_w) > 0.18:
                    continue
                if _relative_delta(item["bbox"]["h"], canonical_h) > 0.18:
                    continue
                cluster.append(item)
                pending.remove(item)
                changed = True
        if len(cluster) >= minimum_group_size:
            clusters.append(cluster)
    return clusters


def _infer_repeated_grid_slots(
    rectangles: list[dict[str, Any]],
    *,
    minimum_group_size: int,
) -> list[dict[str, Any]]:
    width_clusters = _cluster_rectangles_by_width(rectangles)
    slots: list[dict[str, Any]] = []
    grid_index = 0
    for cluster in width_clusters:
        canonical_w = round(median(item["bbox"]["w"] for item in cluster))
        canonical_h = round(median(item["bbox"]["h"] for item in cluster))
        x_anchors = _cluster_axis_values(
            [item["bbox"]["x"] for item in cluster],
            tolerance=max(6.0, canonical_w * 0.08),
        )
        y_anchors = _cluster_axis_values(
            [item["bbox"]["y"] for item in cluster],
            tolerance=max(6.0, canonical_h * 0.12),
        )
        if len(x_anchors) < minimum_group_size or len(y_anchors) < 2:
            continue
        x_steps = [
            right - left
            for left, right in zip(x_anchors, x_anchors[1:])
            if right - left > canonical_w * 0.65
        ]
        y_steps = [
            bottom - top
            for top, bottom in zip(y_anchors, y_anchors[1:])
            if bottom - top > canonical_h * 0.65
        ]
        if not _steps_are_regular(x_steps) or not _steps_are_regular(y_steps):
            continue
        x_pitch = median(x_steps)
        y_pitch = median(y_steps)
        gutter = max(2.0, x_pitch - canonical_w)
        inferred_h = round(max(canonical_h, y_pitch - gutter))
        if inferred_h <= 0 or inferred_h > y_pitch * 1.05:
            continue
        grid_index += 1
        for row_index, y in enumerate(y_anchors, start=1):
            for column_index, x in enumerate(x_anchors, start=1):
                slots.append(
                    {
                        "visual_id": (
                            f"inferred_grid_{grid_index}_"
                            f"row_{row_index}_column_{column_index}"
                        ),
                        "bbox": {
                            "x": round(x),
                            "y": round(y),
                            "w": canonical_w,
                            "h": inferred_h,
                        },
                        "sources": ["inferred_repeated_grid_slots"],
                        "geometry_source": "inferred_repeated_grid_slots",
                    }
                )
    return _dedupe_visual_rectangles(slots)


def _cluster_rectangles_by_width(
    rectangles: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    pending = sorted(rectangles, key=lambda item: item["bbox"]["w"], reverse=True)
    clusters: list[list[dict[str, Any]]] = []
    while pending:
        seed = pending.pop(0)
        cluster = [seed]
        changed = True
        while changed:
            changed = False
            canonical_w = median(item["bbox"]["w"] for item in cluster)
            for item in list(pending):
                if _relative_delta(item["bbox"]["w"], canonical_w) > 0.08:
                    continue
                cluster.append(item)
                pending.remove(item)
                changed = True
        clusters.append(cluster)
    return clusters


def _cluster_axis_values(values: list[int], *, tolerance: float) -> list[float]:
    clusters: list[list[int]] = []
    for value in sorted(values):
        target = next(
            (
                cluster
                for cluster in clusters
                if abs(value - median(cluster)) <= tolerance
            ),
            None,
        )
        if target is None:
            clusters.append([value])
        else:
            target.append(value)
    return [float(median(cluster)) for cluster in clusters]


def _grid_slots_by_row(
    slots: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for slot in sorted(slots, key=lambda item: item["bbox"]["y"]):
        target = next(
            (
                row
                for row in rows
                if abs(slot["bbox"]["y"] - median(item["bbox"]["y"] for item in row))
                <= max(4.0, slot["bbox"]["h"] * 0.08)
            ),
            None,
        )
        if target is None:
            rows.append([slot])
        else:
            target.append(slot)
    return rows


def _has_adjacent_seed_pair(seed_columns: list[int]) -> bool:
    ordered = sorted(set(seed_columns))
    return any(right - left == 1 for left, right in zip(ordered, ordered[1:]))


def _slot_direct_visual_evidence(
    slot_bbox: dict[str, int],
    rectangles: list[dict[str, Any]],
) -> tuple[float, dict[str, Any] | None]:
    slot_area = slot_bbox["w"] * slot_bbox["h"]
    best_support = 0.0
    best_rectangle: dict[str, Any] | None = None
    for rectangle in rectangles:
        visual_bbox = rectangle["bbox"]
        width_ratio = visual_bbox["w"] / max(1.0, slot_bbox["w"])
        height_ratio = visual_bbox["h"] / max(1.0, slot_bbox["h"])
        if not 0.55 <= width_ratio <= 2.2:
            continue
        if not 0.35 <= height_ratio <= 1.2:
            continue
        if abs(visual_bbox["y"] - slot_bbox["y"]) > slot_bbox["h"] * 0.18:
            continue
        intersection = _bbox_intersection_area(slot_bbox, visual_bbox)
        support = intersection / max(1.0, slot_area)
        if support > best_support:
            best_support = support
            best_rectangle = rectangle
    return min(1.0, best_support), best_rectangle


def _wide_parent_covers_seed_slot(
    parent_bbox: dict[str, int],
    row_slots: list[dict[str, Any]],
    slot_seeds: dict[str, list[dict[str, Any]]],
    *,
    excluded_slot_id: str,
) -> bool:
    for slot in row_slots:
        if slot["visual_id"] == excluded_slot_id:
            continue
        if not slot_seeds.get(slot["visual_id"]):
            continue
        slot_bbox = slot["bbox"]
        overlap = _bbox_intersection_area(parent_bbox, slot_bbox)
        if overlap / max(1.0, slot_bbox["w"] * slot_bbox["h"]) >= 0.45:
            return True
    return False


def _wide_semantic_candidate_covering_slot(
    slot_bbox: dict[str, int],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    slot_center_y = slot_bbox["y"] + slot_bbox["h"] / 2.0
    for candidate in candidates:
        candidate_bbox = _bbox(candidate.get("bbox"))
        if not candidate_bbox or candidate_bbox["w"] <= slot_bbox["w"] * 1.35:
            continue
        candidate_center_y = candidate_bbox["y"] + candidate_bbox["h"] / 2.0
        if abs(candidate_center_y - slot_center_y) > slot_bbox["h"] * 0.5:
            continue
        horizontal_overlap = max(
            0,
            min(
                slot_bbox["x"] + slot_bbox["w"],
                candidate_bbox["x"] + candidate_bbox["w"],
            )
            - max(slot_bbox["x"], candidate_bbox["x"]),
        )
        if horizontal_overlap / max(1.0, slot_bbox["w"]) >= 0.6:
            return candidate
    return None


def _steps_are_regular(steps: list[float]) -> bool:
    if not steps:
        return False
    canonical = median(steps)
    return all(_relative_delta(step, canonical) <= 0.16 for step in steps)


def _best_visual_rectangle(
    candidate: dict[str, Any],
    rectangles: Any,
) -> dict[str, Any] | None:
    candidate_bbox = _bbox(candidate.get("bbox"))
    if not candidate_bbox:
        return None
    candidate_area = candidate_bbox["w"] * candidate_bbox["h"]
    matches: list[dict[str, Any]] = []
    for rectangle in rectangles:
        visual_bbox = rectangle["bbox"]
        if not _contains_center(visual_bbox, candidate_bbox):
            continue
        if (
            "inferred_repeated_grid_slots" in rectangle.get("sources", [])
            and candidate_bbox["w"] > visual_bbox["w"] * 1.35
        ):
            continue
        visual_area = visual_bbox["w"] * visual_bbox["h"]
        if visual_area > max(candidate_area * 40, candidate_area + 1):
            continue
        matches.append(rectangle)
    if not matches:
        return None
    return max(matches, key=lambda item: item["bbox"]["w"] * item["bbox"]["h"])


def _cluster_assigned_rectangles_by_row(
    rectangles: list[dict[str, Any]],
    *,
    minimum_group_size: int,
) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for rectangle in sorted(rectangles, key=lambda item: _center_y(item["bbox"])):
        best_row: list[dict[str, Any]] | None = None
        best_delta = float("inf")
        for row in rows:
            row_center = median(_center_y(item["bbox"]) for item in row)
            row_height = median(item["bbox"]["h"] for item in row)
            delta = abs(_center_y(rectangle["bbox"]) - row_center)
            if delta <= max(12.0, row_height * 0.22) and delta < best_delta:
                best_row = row
                best_delta = delta
        if best_row is None:
            rows.append([rectangle])
        else:
            best_row.append(rectangle)
    return [
        row
        for row in rows
        if len({item["visual_id"] for item in row}) >= minimum_group_size
    ]


def _row_geometry_source(row: list[dict[str, Any]]) -> str:
    sources = {
        source
        for rectangle in row
        for source in rectangle.get("sources", [])
    }
    if sources == {"inferred_repeated_grid_slots"}:
        return "inferred_repeated_grid_slots"
    return "detected_repeated_visual_rectangles"


def _candidate_id(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("group_id")
        or candidate.get("item_id")
        or candidate.get("number")
        or candidate.get("id")
        or candidate.get("label")
        or "candidate"
    )


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: int(round(float(value.get(key) or 0))) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return bbox if bbox["w"] > 0 and bbox["h"] > 0 else None


def _inside_image(bbox: dict[str, int], *, width: int, height: int) -> bool:
    return (
        bbox["x"] >= 0
        and bbox["y"] >= 0
        and bbox["x"] + bbox["w"] <= width
        and bbox["y"] + bbox["h"] <= height
    )


def _contains_center(container: dict[str, int], child: dict[str, int]) -> bool:
    center_x = child["x"] + child["w"] / 2.0
    center_y = child["y"] + child["h"] / 2.0
    return (
        container["x"] <= center_x <= container["x"] + container["w"]
        and container["y"] <= center_y <= container["y"] + container["h"]
    )


def _center_y(bbox: dict[str, int]) -> float:
    return bbox["y"] + bbox["h"] / 2.0


def _relative_delta(value: float, reference: float) -> float:
    return abs(float(value) - float(reference)) / max(1.0, abs(float(reference)))


def _bbox_iou(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    left_area = left["w"] * left["h"]
    right_area = right["w"] * right["h"]
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _bbox_intersection_area(left: dict[str, int], right: dict[str, int]) -> int:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _bbox_adjustment(raw: dict[str, int], normalized: dict[str, int]) -> dict[str, int]:
    return {
        key: int(normalized[key] - raw[key])
        for key in ("x", "y", "w", "h")
    }
