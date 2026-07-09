from __future__ import annotations

from app.learn.recognition.layout_graph import build_inventory_layout_graph


def test_layout_graph_groups_surface_zones_and_reading_order() -> None:
    items = [
        {
            "item_id": "address_bar",
            "label": "Address and search bar",
            "item_type": "actionable",
            "role": "address_bar",
            "bbox": {"x": 120, "y": 32, "w": 700, "h": 32},
            "metadata": {"surface_zone": "browser_chrome"},
        },
        {
            "item_id": "search_button",
            "label": "Search",
            "item_type": "actionable",
            "role": "button",
            "bbox": {"x": 980, "y": 145, "w": 80, "h": 36},
            "grounding_eligible": True,
        },
        {
            "item_id": "go_button",
            "label": "Go",
            "item_type": "actionable",
            "role": "button",
            "bbox": {"x": 1010, "y": 150, "w": 72, "h": 34},
            "grounding_eligible": True,
        },
        {
            "item_id": "latest_news",
            "label": "Latest News",
            "item_type": "readable",
            "role": "text",
            "bbox": {"x": 90, "y": 520, "w": 320, "h": 90},
            "review_only": True,
        },
    ]

    graph = build_inventory_layout_graph(items, screen_size={"width": 1280, "height": 720})

    assert graph["contract_version"] == "learn_layout_graph_v1"
    assert graph["node_count"] == 4
    assert graph["zones"]["browser_chrome"]["item_ids"] == ["address_bar"]
    assert graph["zones"]["page_header"]["item_ids"] == ["search_button", "go_button"]
    assert graph["zones"]["main_content"]["item_ids"] == ["latest_news"]
    assert graph["reading_order"] == ["address_bar", "search_button", "go_button", "latest_news"]
    assert graph["overlap_clusters"] == [
        {
            "cluster_id": "overlap_cluster_1",
            "item_ids": ["search_button", "go_button"],
            "reason": "overlapping_distinct_items",
            "split_roi_required": True,
        }
    ]
    assert graph["nodes"]["search_button"]["split_roi_required"] is True
    assert graph["nodes"]["address_bar"]["surface_zone"] == "browser_chrome"
    assert graph["display_only"] is True
    assert graph["execute_binding_enabled"] is False
