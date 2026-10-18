from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.agent.live_runtime_composition import _parse_candidate, _parse_recognition
from tests import test_vision_route as vision_route_tests


def _capture_existing_route_response(
    monkeypatch: pytest.MonkeyPatch,
    route_test: Callable[..., None],
    tmp_path: Any,
) -> dict[str, Any]:
    """复用现有自包含路由夹具，并截获它实际返回的候选。"""
    responses: list[dict[str, Any]] = []
    original_post = vision_route_tests.TestClient.post

    def recording_post(self: Any, url: str, *args: Any, **kwargs: Any) -> Any:
        response = original_post(self, url, *args, **kwargs)
        if url == "/vision/recognition_plan":
            responses.append(response.json())
        return response

    monkeypatch.setattr(vision_route_tests.TestClient, "post", recording_post)
    route_test(tmp_path, monkeypatch)
    assert len(responses) == 1
    return responses[0]["data"]["result"]


@pytest.mark.parametrize(
    "route_test",
    [
        vision_route_tests.test_vision_recognition_plan_uses_vista_point_grounding_with_path_graph,
        vision_route_tests.test_vision_recognition_plan_visual_asset_fast_lane_skips_vista,
        vision_route_tests.test_operational_memory_fast_grounding_uses_unique_current_uia_candidate_without_vista,
    ],
    ids=["vista_inside_candidate", "reviewed_seed_fast_lane", "current_uia_fast_lane"],
)
def test_recognition_plan_candidates_obey_strict_score_contract(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    route_test: Callable[..., None],
) -> None:
    """实际路由输出必须能被原生严格消费者解析。"""
    result = _capture_existing_route_response(monkeypatch, route_test, tmp_path)
    candidate = result["candidate_result"]["candidates"][0]

    _parse_candidate(candidate)
    _parse_recognition(result)
