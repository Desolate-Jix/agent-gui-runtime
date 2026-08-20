from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_inventory_layout_graph(
    items: list[dict[str, Any]],
    *,
    screen_size: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把候选框整理成只读页面布局图，供学习草稿和面板展示使用。"""

    valid_items = [deepcopy(item) for item in items if isinstance(item, dict)]
    screen = screen_size if isinstance(screen_size, dict) else {}
    nodes: dict[str, dict[str, Any]] = {}
    zones = _empty_zones()
    reading_order = sorted(valid_items, key=lambda item: (_bbox_top(item), _bbox_left(item), _item_id(item)))

    for index, item in enumerate(reading_order):
        item_id = _item_id(item) or f"layout_item_{index + 1}"
        zone_id = _surface_zone(item, screen)
        nodes[item_id] = {
            "item_id": item_id,
            "label": str(item.get("label") or item.get("text") or ""),
            "role": str(item.get("role") or ""),
            "item_type": str(item.get("item_type") or ""),
            "surface_zone": zone_id,
            "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
            "review_only": bool(item.get("review_only")),
            "grounding_eligible": bool(item.get("grounding_eligible")),
            "split_roi_required": False,
            "parent_ids": [],
            "child_ids": [],
        }
        zones.setdefault(zone_id, _zone_entry(zone_id))["item_ids"].append(item_id)

    _attach_parent_child(nodes)
    overlap_clusters = _overlap_clusters(nodes)

    return {
        "contract_version": "learn_layout_graph_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "node_count": len(nodes),
        "zone_count": sum(1 for zone in zones.values() if zone["item_ids"]),
        "zones": zones,
        "nodes": nodes,
        "reading_order": [_item_id(item) or f"layout_item_{index + 1}" for index, item in enumerate(reading_order)],
        "overlap_clusters": overlap_clusters,
        "interpretation": (
            "layout graph groups parser candidates for review and ROI planning only; it is not click permission, "
            "Execute authorization, or a recognition accuracy metric"
        ),
    }


def _empty_zones() -> dict[str, dict[str, Any]]:
    return {
        "browser_chrome": _zone_entry("browser_chrome"),
        "page_header": _zone_entry("page_header"),
        "main_content": _zone_entry("main_content"),
        "lower_content": _zone_entry("lower_content"),
        "floating_overlay": _zone_entry("floating_overlay"),
        "unknown": _zone_entry("unknown"),
    }


def _zone_entry(zone_id: str) -> dict[str, Any]:
    return {"zone_id": zone_id, "item_ids": []}


def _surface_zone(item: dict[str, Any], screen_size: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    explicit = str(item.get("surface_zone") or metadata.get("surface_zone") or "").strip()
    if explicit:
        return explicit
    role = str(item.get("role") or "").casefold()
    if role in {"address_bar", "browser_tab", "browser_toolbar", "extension_button"}:
        return "browser_chrome"
    label = str(item.get("label") or item.get("text") or "").strip().casefold()
    if label.startswith(("http://", "https://", "www.")) or label.endswith(
        (" - microsoft edge", " - google chrome", " - mozilla firefox")
    ):
        return "browser_chrome"
    height = _float(screen_size.get("height"))
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    y = _float(bbox.get("y"))
    if height <= 0:
        return "unknown"
    if y < height * 0.12:
        return "page_header"
    if y < height * 0.32:
        return "page_header"
    if y < height * 0.9:
        return "main_content"
    return "lower_content"


def _attach_parent_child(nodes: dict[str, dict[str, Any]]) -> None:
    node_items = list(nodes.items())
    for parent_id, parent in node_items:
        for child_id, child in node_items:
            if parent_id == child_id:
                continue
            if _bbox_area(parent.get("bbox")) <= _bbox_area(child.get("bbox")):
                continue
            if _contains(parent.get("bbox"), child.get("bbox")) >= 0.92:
                parent["child_ids"].append(child_id)
                child["parent_ids"].append(parent_id)
    for node in nodes.values():
        node["child_ids"] = sorted(set(node["child_ids"]))
        node["parent_ids"] = sorted(set(node["parent_ids"]))


def _overlap_clusters(nodes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    node_items = list(nodes.items())
    for left_index, (left_id, left) in enumerate(node_items):
        for right_id, right in node_items[left_index + 1 :]:
            if left_id == right_id:
                continue
            pair = tuple(sorted((left_id, right_id)))
            if pair in seen:
                continue
            seen.add(pair)
            if _same_label(left, right):
                continue
            if _overlap_ratio(left.get("bbox"), right.get("bbox")) < 0.45:
                continue
            left["split_roi_required"] = True
            right["split_roi_required"] = True
            clusters.append(
                {
                    "cluster_id": f"overlap_cluster_{len(clusters) + 1}",
                    "item_ids": [left_id, right_id],
                    "reason": "overlapping_distinct_items",
                    "split_roi_required": True,
                }
            )
    return clusters


def _same_label(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return " ".join(str(left.get("label") or "").casefold().split()) == " ".join(str(right.get("label") or "").casefold().split())


def _item_id(item: dict[str, Any]) -> str:
    return str(item.get("item_id") or item.get("id") or "").strip()


def _bbox_left(item: dict[str, Any]) -> float:
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    return _float(bbox.get("x"))


def _bbox_top(item: dict[str, Any]) -> float:
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    return _float(bbox.get("y"))


def _bbox_area(value: Any) -> float:
    bbox = value if isinstance(value, dict) else {}
    return max(0.0, _float(bbox.get("w"))) * max(0.0, _float(bbox.get("h")))


def _contains(outer: Any, inner: Any) -> float:
    intersection = _intersection_area(outer, inner)
    inner_area = _bbox_area(inner)
    return 0.0 if inner_area <= 0 else intersection / inner_area


def _overlap_ratio(left: Any, right: Any) -> float:
    intersection = _intersection_area(left, right)
    smaller = min(_bbox_area(left), _bbox_area(right))
    return 0.0 if smaller <= 0 else intersection / smaller


def _intersection_area(left: Any, right: Any) -> float:
    lb = left if isinstance(left, dict) else {}
    rb = right if isinstance(right, dict) else {}
    lx1 = _float(lb.get("x"))
    ly1 = _float(lb.get("y"))
    lx2 = lx1 + max(0.0, _float(lb.get("w")))
    ly2 = ly1 + max(0.0, _float(lb.get("h")))
    rx1 = _float(rb.get("x"))
    ry1 = _float(rb.get("y"))
    rx2 = rx1 + max(0.0, _float(rb.get("w")))
    ry2 = ry1 + max(0.0, _float(rb.get("h")))
    return max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(0.0, min(ly2, ry2) - max(ly1, ry1))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
