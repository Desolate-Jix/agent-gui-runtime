from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace

from scripts import send_chatgpt_visual_audit as sender


def test_parse_point_accepts_window_relative_coordinates():
    assert sender._parse_point("1105,1117") == sender.Point(1105, 1117)


def test_attachment_remove_points_clicks_right_to_left():
    points = sender._attachment_remove_points(first=sender.Point(1029, 598), gap_x=64, count=4)

    assert points == [
        sender.Point(1221, 598),
        sender.Point(1157, 598),
        sender.Point(1093, 598),
        sender.Point(1029, 598),
    ]


def test_dry_run_reports_fixed_flow_without_clicking(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "overlay.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            raise AssertionError("dry-run must not bind or click")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--json",
        ]
    )

    result = sender.run(args)

    assert result["dry_run"] is True
    assert result["prompt_length"] == len("review this")
    assert result["image_count"] == 1
    assert result["delivery_status"] == "would_compose_not_send"
    assert result["send_click_attempted"] is False
    assert result["sent"] is False
    assert result["post_send_verification"]["post_send_verified"] is False
    assert result["post_send_verification"]["expected_latest_user_image_count"] == 1
    assert result["composer_point"] == {"x": 1105, "y": 1117}
    assert result["send_point"] is None
    assert result["send_requires_explicit_point"] is True
    assert result["remove_points"][0] == {"x": 1221, "y": 598}
    assert result["focus_contract"]["strict_composer_focus"] is False
    assert result["focus_contract"]["prompt_hidden_click_before_typing"] is False
    assert [item["step"] for item in result["planned_action_sequence"]] == [
        "click_gpt_composer_before_prompt",
        "clear_existing_attachment_slots",
        "click_gpt_composer_after_attachment_clear",
        "paste_prompt_text",
        "click_gpt_composer_before_image",
        "paste_image",
    ]
    assert result["planned_action_sequence"][3]["hidden_click_before_typing"] is False
    assert result["planned_action_sequence"][5]["focus_bound_window"] is False


def test_send_requires_explicit_calibrated_send_point(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "overlay.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            raise AssertionError("validation should fail before binding")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--no-dry-run",
            "--send",
        ]
    )

    try:
        sender.run(args)
    except ValueError as exc:
        assert "--send requires an explicit --send-point" in str(exc)
    else:
        raise AssertionError("expected --send without --send-point to fail")


def test_fixed_flow_preset_supplies_current_split_send_point(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "overlay.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            raise AssertionError("dry-run must not bind or click")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--flow-preset",
            "codex_split_20260708",
            "--send",
            "--json",
        ]
    )

    result = sender.run(args)

    assert result["dry_run"] is True
    assert result["flow_preset"] == "codex_split_20260708"
    assert result["delivery_status"] == "would_attempt_send_click_unverified"
    assert result["composer_point"] == {"x": 1105, "y": 1117}
    assert result["send_point"] == {"x": 1310, "y": 1108}
    assert result["send_requires_explicit_point"] is False
    assert result["fixed_flow_steps"][-1] == "framework click calibrated GPT send button and mark send_click_attempted only"
    assert result["focus_contract"]["strict_composer_focus"] is True
    assert result["focus_contract"]["fixed_flow_refocus_before_each_image_forced"] is True
    assert result["focus_contract"]["images"] == "framework_click_composer_before_each_clipboard_image_paste"


def test_no_dry_run_clicks_composer_before_text_and_each_image(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_one = tmp_path / "one.png"
    image_two = tmp_path / "two.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_one.write_bytes(b"fake png bytes 1")
    image_two.write_bytes(b"fake png bytes 2")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            @dataclass
            class Bound:
                handle: int
                title: str
                rect: object

            return Bound(
                handle=handle,
                title="Codex",
                rect=SimpleNamespace(left=0, top=0, right=1600, bottom=1200),
            )

    calls = []

    class FakeController:
        def click_point(self, x, y, **kwargs):
            calls.append(("click_point", x, y))
            return {"clicked": True, "x": x, "y": y}

        def type_text(self, text, **kwargs):
            calls.append(("type_text", text, kwargs))
            return {"typed": True, "text_length": len(text), **kwargs}

        def paste_image(self, image_path, **kwargs):
            calls.append(("paste_image", Path(image_path).name, kwargs))
            return {"pasted": True, "image_path": image_path, **kwargs}

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())
    monkeypatch.setattr(sender, "InputController", FakeController)
    monkeypatch.setattr(sender.time, "sleep", lambda _seconds: None)

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_one),
            "--image",
            str(image_two),
            "--expected-images",
            "2",
            "--no-dry-run",
            "--no-clear-attachments",
            "--composer-point",
            "100,200",
        ]
    )

    result = sender.run(args)

    assert result["delivery_status"] == "composed_not_sent"
    assert result["send_click_attempted"] is False
    assert result["sent"] is False
    assert calls[0] == ("click_point", 100, 200)
    assert calls[1][0] == "type_text"
    assert calls[1][2]["click_before_typing"] is False
    assert "x" not in calls[1][2]
    assert "y" not in calls[1][2]
    assert calls[1][2]["clear_existing"] is True
    assert calls[2] == ("click_point", 100, 200)
    assert calls[3][0:2] == ("paste_image", "one.png")
    assert calls[3][2]["focus_bound_window"] is False
    assert calls[4] == ("click_point", 100, 200)
    assert calls[5][0:2] == ("paste_image", "two.png")
    assert [item["step"] for item in result["planned_action_sequence"]] == [
        "click_gpt_composer_before_prompt",
        "paste_prompt_text",
        "click_gpt_composer_before_image",
        "paste_image",
        "click_gpt_composer_before_image",
        "paste_image",
    ]
    assert [item["step"] for item in result["actual_action_sequence"]] == [
        "click_gpt_composer_before_prompt",
        "paste_prompt_text",
        "click_gpt_composer_before_image",
        "paste_image",
        "click_gpt_composer_before_image",
        "paste_image",
    ]
    assert result["actual_action_sequence"][1]["hidden_click_before_typing"] is False
    assert result["actual_action_sequence"][3]["focus_bound_window"] is False
    assert result["actual_action_sequence"][5]["focus_bound_window"] is False
    assert result["focus_contract"]["prompt"] == "framework_click_composer_then_clipboard_paste_text"
    assert result["focus_contract"]["prompt_hidden_click_before_typing"] is False
    assert result["focus_contract"]["images"] == "framework_click_composer_before_each_clipboard_image_paste"


def test_fixed_flow_preset_real_run_clicks_send_after_images(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "one.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            @dataclass
            class Bound:
                handle: int
                title: str

            return Bound(handle=handle, title="Codex")

    calls = []

    class FakeController:
        def click_point(self, x, y, **kwargs):
            calls.append(("click_point", x, y))
            return {"clicked": True, "x": x, "y": y}

        def type_text(self, text, **kwargs):
            calls.append(("type_text", text, kwargs))
            return {"typed": True, "text_length": len(text), **kwargs}

        def paste_image(self, image_path, **kwargs):
            calls.append(("paste_image", Path(image_path).name, kwargs))
            return {"pasted": True, "image_path": image_path, **kwargs}

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())
    monkeypatch.setattr(sender, "InputController", FakeController)
    monkeypatch.setattr(sender.time, "sleep", lambda _seconds: None)

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--flow-preset",
            "codex_split_20260708",
            "--no-dry-run",
            "--no-clear-attachments",
            "--send",
        ]
    )

    result = sender.run(args)

    assert result["delivery_status"] == "send_click_attempted_unverified"
    assert result["send_click_attempted"] is True
    assert result["sent"] is False
    assert result["post_send_verification"]["post_send_verified"] is False
    assert "A calibrated send click is not proof" in result["post_send_verification"]["false_positive_guard"]
    assert result["flow_preset"] == "codex_split_20260708"
    assert calls[0] == ("click_point", 1105, 1117)
    assert calls[1][0] == "type_text"
    assert calls[1][2]["click_before_typing"] is False
    assert calls[2] == ("click_point", 1105, 1117)
    assert calls[3][0:2] == ("paste_image", "one.png")
    assert calls[-1] == ("click_point", 1310, 1108)
    assert [item["step"] for item in result["actual_action_sequence"]] == [
        "click_gpt_composer_before_prompt",
        "paste_prompt_text",
        "click_gpt_composer_before_image",
        "paste_image",
        "click_gpt_send",
    ]
    assert result["actual_action_sequence"][-1]["post_send_verified"] is False


def test_fixed_flow_preset_forces_refocus_even_if_flag_disables_it(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "one.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            raise AssertionError("dry-run must not bind or click")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--flow-preset",
            "codex_split_20260708",
            "--no-refocus-before-each-image",
            "--json",
        ]
    )

    result = sender.run(args)

    assert result["focus_contract"]["strict_composer_focus"] is True
    assert result["focus_contract"]["fixed_flow_refocus_before_each_image_forced"] is True
    assert result["focus_contract"]["images"] == "framework_click_composer_before_each_clipboard_image_paste"


def test_fixed_flow_preset_rejects_wrong_sized_codex_window_before_click(monkeypatch, tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "one.png"
    prompt_file.write_text("review this", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            @dataclass
            class Bound:
                handle: int
                title: str
                rect: object

            return Bound(
                handle=handle,
                title="Codex",
                rect=SimpleNamespace(left=0, top=0, right=199, bottom=34),
            )

    class FakeController:
        def click_point(self, *_args, **_kwargs):
            raise AssertionError("layout mismatch must fail before any click")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())
    monkeypatch.setattr(sender, "InputController", FakeController)

    args = sender.build_parser().parse_args(
        [
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--flow-preset",
            "codex_split_20260708",
            "--no-dry-run",
            "--send",
        ]
    )

    try:
        sender.run(args)
    except ValueError as exc:
        assert "Fixed ChatGPT visual-audit flow layout mismatch" in str(exc)
        assert "actual_window_size=199x34" in str(exc)
    else:
        raise AssertionError("expected fixed-flow layout mismatch to fail")


def test_main_writes_utf8_json_evidence_file(monkeypatch, tmp_path, capsys):
    prompt_file = tmp_path / "prompt.txt"
    image_path = tmp_path / "overlay.png"
    out_path = tmp_path / "evidence" / "result.json"
    prompt_file.write_text("请审核这张图", encoding="utf-8")
    image_path.write_bytes(b"fake png bytes")

    class FakeWindowManager:
        def list_visible_windows(self):
            return [{"handle": 123, "title": "Codex", "process_name": "Codex.exe"}]

        def bind_window_by_handle(self, handle):
            raise AssertionError("dry-run must not bind or click")

    monkeypatch.setattr(sender, "window_manager", FakeWindowManager())
    monkeypatch.setattr(
        "sys.argv",
        [
            "send_chatgpt_visual_audit.py",
            "--prompt-file",
            str(prompt_file),
            "--image",
            str(image_path),
            "--expected-images",
            "1",
            "--out",
            str(out_path),
            "--json",
        ],
    )

    assert sender.main() == 0
    stdout = capsys.readouterr().out
    assert '"prompt_length"' in stdout

    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["dry_run"] is True
    assert result["prompt_length"] == len("请审核这张图")
    assert result["image_count"] == 1
