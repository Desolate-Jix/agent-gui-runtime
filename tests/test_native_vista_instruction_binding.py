"""定位模型只接收用户图像任务，不把传输层格式说明当成目标。"""

import base64
from io import BytesIO

from PIL import Image
import pytest

from app.vision.model_workers.vista_openai_server import _message_text_and_image, _vista_prompt


def _image(color):
    buffer = BytesIO()
    Image.new("RGB", (32, 24), color).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@pytest.mark.parametrize("control_role", ["system", "developer"])
def test_transport_format_instruction_does_not_contaminate_visual_goal(control_role):
    instruction, image = _message_text_and_image([
        {"role": control_role, "content": "You are a strict GUI screenshot parser. Return one JSON object."},
        {"role": "user", "content": [
            {"type": "text", "text": "Click 帮助(H)"},
            {"type": "image_url", "image_url": {"url": _image("white")}},
        ]},
    ])
    assert instruction == "Click 帮助(H)"
    assert image.size == (32, 24)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert _vista_prompt(instruction) == (
        "Output the center point of the position corresponding to the instruction: "
        "Click 帮助(H). The output should just be the coordinates of a point, in the format [x,y]."
    )


def test_non_user_image_cannot_replace_the_target_image():
    instruction, image = _message_text_and_image([
        {"role": "user", "content": [
            {"type": "text", "text": "Click 帮助(H)"},
            {"type": "image_url", "image_url": {"url": _image("white")}},
        ]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Earlier unrelated analysis"},
            {"type": "image_url", "image_url": {"url": _image("black")}},
        ]},
    ])
    assert instruction == "Click 帮助(H)"
    assert image.getpixel((0, 0)) == (255, 255, 255)


def test_user_goal_lines_and_coordinate_directive_remain_intact():
    text = "Goal: 帮助(H)\ncoordinate_space=normalized_0_1000"
    instruction, image = _message_text_and_image([
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": [
            {"type": "image", "image": _image("white")},
            {"type": "text", "text": text},
        ]},
    ])
    assert instruction == text
    assert image.size == (32, 24)
    assert "帮助(H)" in _vista_prompt(instruction)


def test_format_instruction_alone_does_not_become_an_image_task():
    instruction, image = _message_text_and_image([
        {"role": "system", "content": "Return JSON only."},
    ])
    assert instruction == ""
    assert image is None


def test_point_grounding_disables_sampling_independent_of_generic_parser_default(tmp_path, monkeypatch):
    from app.api import vision
    from app.vision.schemas import ImageSize

    sent = {}

    class Provider:
        def __init__(self, **kwargs):
            pass

        def _call_openai_compatible_endpoint(self, image, prompt, **kwargs):
            sent.update(kwargs)
            return {}

        def _extract_message_text(self, response):
            return "[500, 500]"

    monkeypatch.setattr(vision, "LocalVisionProvider", Provider)
    result = vision._call_vista_point_prompt(
        local_config={"endpoint": "http://127.0.0.1:12345/v1/chat/completions"},
        image_path=tmp_path / "new-frame.png", goal="帮助(H)", prompt="Click 帮助(H)",
        image_size=ImageSize(width=100, height=80), timeout_seconds=15,
        max_tokens=32, provider_name="vista_point_grounding",
    )
    assert result["point"] == {"x": 50, "y": 40}
    assert sent.get("temperature") == 0.0
