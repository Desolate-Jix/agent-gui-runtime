from __future__ import annotations

from app.api.vision import _learn_target_candidate_is_browser_chrome


def _image_size() -> dict[str, int]:
    return {"width": 1200, "height": 800}


def test_learning_target_filter_does_not_infer_browser_chrome_from_app_name_and_top_position() -> None:
    candidate = {
        "candidate_id": "page_search",
        "label": "Search",
        "role": "button",
        "bbox": {"x": 900, "y": 20, "w": 100, "h": 32},
    }

    assert _learn_target_candidate_is_browser_chrome(
        candidate,
        image_size=_image_size(),
        screen_map={"app_name": "Microsoft Edge"},
    ) is False


def test_learning_target_filter_uses_adapter_evidence_scope_without_fixed_height_guess() -> None:
    decision = {
        "contract_version": "learning_surface_adapter_decision_v1",
        "adapter_id": "browser",
        "status": "selected_from_visible_evidence",
        "excluded_zones": ["browser_chrome"],
        "excluded_item_ids": ["address_bar"],
        "final_geometry_allowed": False,
    }
    address_bar = {
        "candidate_id": "stage2:root:address_bar",
        "source_item_id": "address_bar",
        "label": "Address",
        "role": "input",
        "bbox": {"x": 100, "y": 20, "w": 700, "h": 36},
    }
    page_button = {
        "candidate_id": "stage2:root:page_search",
        "source_item_id": "page_search",
        "label": "Search",
        "role": "button",
        "bbox": {"x": 900, "y": 20, "w": 100, "h": 32},
    }
    screen_map = {"surface_adapter_decision": decision}

    assert _learn_target_candidate_is_browser_chrome(
        address_bar,
        image_size=_image_size(),
        screen_map=screen_map,
    ) is True
    assert _learn_target_candidate_is_browser_chrome(
        page_button,
        image_size=_image_size(),
        screen_map=screen_map,
    ) is False
