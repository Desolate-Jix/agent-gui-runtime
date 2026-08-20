from __future__ import annotations

from app.seek.scroll_containers import SEEK_JOB_DETAIL, SEEK_RESULTS_LIST, discover_seek_scroll_containers


def _container(payload: dict, container_id: str) -> dict:
    return next(item for item in payload["containers"] if item["container_id"] == container_id)


def test_seek_results_list_width_is_capped_on_wide_windows() -> None:
    containers = discover_seek_scroll_containers(
        window_title="Software engineer Jobs in All Auckland - SEEK",
        app_name="seek",
        window_size={"width": 2560, "height": 1400},
    )

    results = _container(containers, SEEK_RESULTS_LIST)
    detail = _container(containers, SEEK_JOB_DETAIL)

    assert results["bbox"]["x"] >= 500
    assert results["safe_points"][0]["x"] >= 700
    assert results["bbox"]["w"] <= 560
    assert detail["bbox"]["x"] >= results["bbox"]["x"] + results["bbox"]["w"] + 40


def test_seek_results_list_stays_left_on_normal_windows() -> None:
    containers = discover_seek_scroll_containers(
        window_title="Software engineer Jobs in All Auckland - SEEK",
        app_name="seek",
        window_size={"width": 1200, "height": 1000},
    )

    results = _container(containers, SEEK_RESULTS_LIST)

    assert results["bbox"]["x"] == 16
    assert 180 <= results["bbox"]["y"] <= 240


def test_seek_results_list_prefers_live_card_evidence() -> None:
    containers = discover_seek_scroll_containers(
        window_title="Software engineer Jobs in All Auckland - SEEK",
        app_name="seek",
        window_size={"width": 2560, "height": 1400},
        evidence={"results_list_bbox": {"x": 612, "y": 350, "w": 460, "h": 720}},
    )

    results = _container(containers, SEEK_RESULTS_LIST)

    assert results["bbox"] == {"x": 612, "y": 350, "w": 460, "h": 720}
    assert results["sources"] == ["screen_inventory_job_card_bbox"]
    assert results["safe_points"][0]["x"] == 842
