"""VISTA 直接定位默认图像策略的原生契约。"""

from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRResult


def _request(*, agent_mode="execute", metadata=None):
    return vision.VisionRecognitionPlanRequestModel(
        image_path="synthetic.png",
        task="locate_element",
        goal="帮助(H)",
        provider_mode="local_grounding",
        agent_mode=agent_mode,
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata=metadata or {},
    )


def test_direct_defaults_prefer_full_resolution_single_pass():
    options = vision._vista_direct_grounding_options(_request())

    assert options["enabled"] is True
    assert options["max_edge"] == 1024
    assert options["refine"] is False


def test_unrelated_direct_options_keep_full_resolution_single_pass_defaults():
    options = vision._vista_direct_grounding_options(
        _request(metadata={"vista_direct_grounding": {"timeout_seconds": 9}})
    )

    assert options["enabled"] is True
    assert options["timeout_seconds"] == 9.0
    assert options["max_edge"] == 1024
    assert options["refine"] is False


def test_explicit_direct_image_and_refine_options_are_preserved():
    options = vision._vista_direct_grounding_options(
        _request(
            metadata={
                "vista_direct_grounding": {
                    "max_edge": 640,
                    "refine": True,
                    "refine_roi_size": 333,
                    "refine_max_edge": 400,
                }
            }
        )
    )

    assert options["max_edge"] == 640
    assert options["refine"] is True
    assert options["refine_roi_size"] == 333
    assert options["refine_max_edge"] == 400


def test_disabled_and_non_execute_direct_eligibility_stay_disabled():
    assert vision._vista_direct_grounding_options(
        _request(metadata={"vista_direct_grounding": {"enabled": False}})
    )["enabled"] is False
    assert vision._vista_direct_grounding_options(_request(agent_mode="learn"))["enabled"] is False


def test_direct_preprocess_never_upscales_small_capture(tmp_path):
    image_path = tmp_path / "small.png"
    Image.new("RGB", (500, 300), "white").save(image_path)

    with pinned_runtime_output_root(tmp_path):
        prepared = vision._prepare_vista_direct_image(
            image_path,
            ImageSize(width=500, height=300),
            max_edge=1024,
        )

    assert prepared["status"] == "identity"
    assert prepared["processed_image_path"] == str(image_path)
    assert prepared["processed_size"] == {"width": 500, "height": 300}


def test_actual_direct_producer_uses_1024_single_coarse_and_original_point(tmp_path, monkeypatch):
    image_path = tmp_path / "fresh-full-window.png"
    Image.new("RGB", (1487, 1001), "white").save(image_path)
    calls = []

    def model_reply(**kwargs):
        calls.append(
            {
                "vista_stage": kwargs["vista_stage"],
                "image_size": kwargs["image_size"].to_dict(),
                "original_image_size": kwargs["original_image_size"].to_dict(),
            }
        )
        return {
            "point": {"x": 254, "y": 41},
            "provider": "synthetic-vista-boundary",
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model_reply)
    monkeypatch.setattr(
        vision.ocr_service,
        "scan_image",
        lambda path: OCRResult(image_path=str(path), matches=[]),
    )
    request = _request()
    request.image_path = str(image_path)
    request.app_name = "notepad.exe"
    with pinned_uia_snapshot({"provider": "windows_uia", "status": "ok", "controls": []}), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(
            request=request,
            timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated-test-vista"},
            image_path=image_path,
            input_image_size=ImageSize(width=1487, height=1001),
            goal=request.goal,
            observe_reuse={},
            path_graph_recall={"status": "not_requested", "candidates": []},
        )

    assert response.success is True
    result = response.data["result"]
    payload = result["parse_result"]["vista_point_grounding"]
    candidate = result["candidate_result"]["candidates"][0]
    assert calls == [
        {
            "vista_stage": "coarse_full",
            "image_size": {"width": 1024, "height": 689},
            "original_image_size": {"width": 1487, "height": 1001},
        }
    ]
    assert payload["image_preprocess"]["processed_size"] == {"width": 1024, "height": 689}
    assert payload["point"] == {"x": 254, "y": 41}
    assert candidate["element"]["click_point"] == {"x": 254, "y": 41}
