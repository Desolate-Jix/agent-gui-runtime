from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.input_controller import InputController
from app.core.window_manager import window_manager


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class FixedFlowPreset:
    name: str
    composer_point: Point
    send_point: Point
    remove_first_point: Point
    remove_gap_x: int
    remove_slots: int
    min_window_width: int
    min_window_height: int
    description: str


FIXED_FLOW_PRESETS: dict[str, FixedFlowPreset] = {
    "codex_split_20260708": FixedFlowPreset(
        name="codex_split_20260708",
        composer_point=Point(1105, 1117),
        send_point=Point(1310, 1108),
        remove_first_point=Point(1029, 598),
        remove_gap_x=64,
        remove_slots=4,
        min_window_width=1330,
        min_window_height=1140,
        description=(
            "Local Codex split layout calibrated on 2026-07-08: click GPT composer, "
            "paste text, click GPT composer before each image paste, then click GPT send."
        ),
    )
}


def _parse_point(value: str) -> Point:
    try:
        x_text, y_text = value.split(",", 1)
        return Point(x=int(x_text.strip()), y=int(y_text.strip()))
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"point must be 'x,y', got {value!r}") from exc


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return str(args.prompt)
    raise ValueError("Either --prompt or --prompt-file is required")


def _resolve_codex_handle(args: argparse.Namespace) -> int:
    if args.window_handle:
        return int(args.window_handle)
    candidates = window_manager.list_visible_windows()
    for candidate in candidates:
        title = str(candidate.get("title") or "")
        process_name = str(candidate.get("process_name") or "")
        if title == "Codex" and process_name.lower() == "codex.exe":
            handle = candidate.get("handle")
            if handle:
                return int(handle)
    raise ValueError("Could not find a visible Codex window. Pass --window-handle explicitly.")


def _attachment_remove_points(*, first: Point, gap_x: int, count: int) -> list[Point]:
    points = [Point(first.x + gap_x * index, first.y) for index in range(max(0, count))]
    return list(reversed(points))


def _apply_flow_preset(args: argparse.Namespace) -> FixedFlowPreset | None:
    if not args.flow_preset:
        return None
    preset = FIXED_FLOW_PRESETS[args.flow_preset]
    args.composer_point = preset.composer_point
    args.send_point = preset.send_point
    args.remove_first_point = preset.remove_first_point
    args.remove_gap_x = preset.remove_gap_x
    args.remove_slots = preset.remove_slots
    args.refocus_before_each_image = True
    return preset


def _fixed_flow_steps(*, send: bool) -> list[str]:
    steps = [
        "bind visible Codex window",
        "framework click GPT composer before any paste",
        "clear stale text and attachment slots",
        "framework click GPT composer again",
        "paste prompt text through InputController.type_text without hidden retargeting",
        "for each image: framework click GPT composer, then paste image through InputController.paste_image",
    ]
    if send:
        steps.append("framework click calibrated GPT send button and mark send_click_attempted only")
    else:
        steps.append("leave composed GPT message unsent for visible review")
    return steps


def _planned_action_sequence(*, image_count: int, clear_attachments: bool, send: bool) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = [
        {
            "step": "click_gpt_composer_before_prompt",
            "target": "gpt_composer",
            "required_before": "paste_prompt_text",
        }
    ]
    if clear_attachments:
        sequence.append(
            {
                "step": "clear_existing_attachment_slots",
                "target": "attachment_remove_slots",
                "order": "right_to_left",
            }
        )
        sequence.append(
            {
                "step": "click_gpt_composer_after_attachment_clear",
                "target": "gpt_composer",
                "required_before": "paste_prompt_text",
            }
        )
    sequence.append(
        {
            "step": "paste_prompt_text",
            "target": "current_focus",
            "hidden_click_before_typing": False,
            "must_follow": "click_gpt_composer_before_prompt",
        }
    )
    for index in range(1, max(0, int(image_count)) + 1):
        sequence.append(
            {
                "step": "click_gpt_composer_before_image",
                "target": "gpt_composer",
                "image_index": index,
                "required_before": "paste_image",
            }
        )
        sequence.append(
            {
                "step": "paste_image",
                "target": "current_focus",
                "image_index": index,
                "focus_bound_window": False,
                "must_follow": "click_gpt_composer_before_image",
            }
        )
    if send:
        sequence.append(
            {
                "step": "click_gpt_send",
                "target": "gpt_send_button",
                "post_send_verified": False,
            }
        )
    return sequence


def _actual_action_sequence(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    for action in actions:
        step = str(action.get("step") or "")
        if step == "focus_composer_before_prompt":
            sequence.append({"step": "click_gpt_composer_before_prompt", "target": "gpt_composer"})
        elif step == "remove_attachment_slot":
            sequence.append(
                {
                    "step": "clear_existing_attachment_slot",
                    "target": "attachment_remove_slot",
                    "point": action.get("point"),
                }
            )
        elif step == "refocus_composer_after_attachment_clear":
            sequence.append({"step": "click_gpt_composer_after_attachment_clear", "target": "gpt_composer"})
        elif step == "paste_prompt_after_framework_composer_click":
            result = action.get("result") if isinstance(action.get("result"), dict) else {}
            sequence.append(
                {
                    "step": "paste_prompt_text",
                    "target": "current_focus",
                    "hidden_click_before_typing": bool(result.get("click_before_typing")),
                }
            )
        elif step == "refocus_composer_before_image":
            sequence.append(
                {
                    "step": "click_gpt_composer_before_image",
                    "target": "gpt_composer",
                    "image_index": action.get("image_index"),
                }
            )
        elif step == "paste_image":
            result = action.get("result") if isinstance(action.get("result"), dict) else {}
            sequence.append(
                {
                    "step": "paste_image",
                    "target": "current_focus",
                    "image_index": action.get("image_index"),
                    "focus_bound_window": bool(result.get("focus_bound_window")),
                    "image_path": action.get("image_path"),
                }
            )
        elif step == "click_send":
            sequence.append({"step": "click_gpt_send", "target": "gpt_send_button", "post_send_verified": False})
    return sequence


def _delivery_status(*, send: bool, dry_run: bool = False) -> str:
    if dry_run and send:
        return "would_attempt_send_click_unverified"
    if dry_run:
        return "would_compose_not_send"
    if send:
        return "send_click_attempted_unverified"
    return "composed_not_sent"


def _verification_contract(*, expected_images: int | None) -> dict[str, Any]:
    return {
        "post_send_verified": False,
        "verification_required": True,
        "expected_latest_user_image_count": expected_images,
        "verification_methods": [
            "ChatGPT DOM latest user message contains the prompt token and expected image count",
            "visible ChatGPT thread shows the newly submitted user message",
        ],
        "false_positive_guard": (
            "A calibrated send click is not proof that GPT received the message; do not treat "
            "send_click_attempted as reviewed or delivered without a post-send check."
        ),
    }


def _focus_contract(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "strict_composer_focus": bool(args.flow_preset),
        "prompt": "framework_click_composer_then_clipboard_paste_text",
        "prompt_hidden_click_before_typing": False,
        "images": "framework_click_composer_before_each_clipboard_image_paste"
        if args.refocus_before_each_image
        else "clipboard_image_paste_without_refocus",
        "fixed_flow_refocus_before_each_image_forced": bool(args.flow_preset),
        "send": "explicit_calibrated_send_point_required",
        "delivery": "send_click_attempted_requires_external_chatgpt_dom_or_visible_thread_verification",
    }


def _bound_window_size(bound: Any) -> tuple[int, int] | None:
    rect = getattr(bound, "rect", None)
    if rect is None:
        return None
    try:
        width = int(getattr(rect, "right")) - int(getattr(rect, "left"))
        height = int(getattr(rect, "bottom")) - int(getattr(rect, "top"))
    except Exception:
        return None
    return width, height


def _validate_preset_window_layout(*, preset: FixedFlowPreset | None, bound: Any) -> None:
    if preset is None:
        return
    size = _bound_window_size(bound)
    if size is None:
        return
    width, height = size
    if width < preset.min_window_width or height < preset.min_window_height:
        raise ValueError(
            "Fixed ChatGPT visual-audit flow layout mismatch: "
            f"preset={preset.name}, required_window_size>={preset.min_window_width}x{preset.min_window_height}, "
            f"actual_window_size={width}x{height}. Restore/maximize the calibrated Codex split window "
            "or pass custom --composer-point/--send-point without --flow-preset after recalibration."
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    preset = _apply_flow_preset(args)
    prompt = _read_prompt(args)
    image_paths = [Path(path) for path in args.image]
    missing = [str(path) for path in image_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing image paths: {missing}")
    if args.expected_images is not None and len(image_paths) != args.expected_images:
        raise ValueError(f"Expected {args.expected_images} images, got {len(image_paths)}")
    if args.send and args.send_point is None:
        raise ValueError(
            "--send requires an explicit --send-point calibrated for the current Codex/ChatGPT split layout. "
            "Pass --flow-preset codex_split_20260708 for the current scripted fixed flow, or omit --send "
            "to paste only and verify/send through the visible ChatGPT UI."
        )
    if preset is not None and not args.refocus_before_each_image:
        raise ValueError(
            "Fixed ChatGPT visual-audit flow requires refocus-before-each-image. "
            "The preset forces a framework click on the GPT composer before every image paste."
        )

    handle = _resolve_codex_handle(args)
    if args.dry_run:
        return {
            "dry_run": True,
            "window_handle": handle,
            "delivery_status": _delivery_status(send=bool(args.send), dry_run=True),
            "send_click_attempted": False,
            "sent": False,
            "sent_field_semantics": "true only after an external post-send verification; fixed-point click alone is not sent",
            "post_send_verification": _verification_contract(expected_images=args.expected_images),
            "prompt_length": len(prompt),
            "image_count": len(image_paths),
            "flow_preset": preset.name if preset is not None else None,
            "flow_preset_description": preset.description if preset is not None else None,
            "composer_point": asdict(args.composer_point),
            "send_point": asdict(args.send_point) if args.send_point is not None else None,
            "send_requires_explicit_point": args.send_point is None,
            "fixed_flow_steps": _fixed_flow_steps(send=bool(args.send)),
            "planned_action_sequence": _planned_action_sequence(
                image_count=len(image_paths),
                clear_attachments=bool(args.clear_attachments),
                send=bool(args.send),
            ),
            "focus_contract": _focus_contract(args),
            "remove_points": [asdict(point) for point in _attachment_remove_points(
                first=args.remove_first_point,
                gap_x=args.remove_gap_x,
                count=args.remove_slots,
            )],
            "would_send": bool(args.send),
        }

    bound = window_manager.bind_window_by_handle(handle)
    _validate_preset_window_layout(preset=preset, bound=bound)
    controller = InputController()
    actions: list[dict[str, Any]] = []

    actions.append(
        {
            "step": "focus_composer_before_prompt",
            "result": controller.click_point(
                args.composer_point.x,
                args.composer_point.y,
                settle_ms=args.click_settle_ms,
                hold_ms=80,
            ),
        }
    )
    time.sleep(args.after_click_sleep)

    if args.clear_attachments:
        for point in _attachment_remove_points(first=args.remove_first_point, gap_x=args.remove_gap_x, count=args.remove_slots):
            result = controller.click_point(point.x, point.y, settle_ms=args.click_settle_ms, hold_ms=60)
            actions.append({"step": "remove_attachment_slot", "point": asdict(point), "result": result})
            time.sleep(args.after_remove_sleep)
        actions.append(
            {
                "step": "refocus_composer_after_attachment_clear",
                "result": controller.click_point(
                    args.composer_point.x,
                    args.composer_point.y,
                    settle_ms=args.click_settle_ms,
                    hold_ms=80,
                ),
            }
        )
        time.sleep(args.after_click_sleep)

    actions.append(
        {
            "step": "paste_prompt_after_framework_composer_click",
            "result": controller.type_text(
                prompt,
                click_before_typing=False,
                clear_existing=args.clear_existing,
                restore_clipboard=False,
            ),
        }
    )
    time.sleep(args.after_text_sleep)

    for index, image_path in enumerate(image_paths, start=1):
        if args.refocus_before_each_image:
            actions.append(
                {
                    "step": "refocus_composer_before_image",
                    "image_index": index,
                    "result": controller.click_point(
                        args.composer_point.x,
                        args.composer_point.y,
                        settle_ms=args.click_settle_ms,
                        hold_ms=80,
                    ),
                }
            )
            time.sleep(args.after_click_sleep)
        result = controller.paste_image(str(image_path), focus_bound_window=False, settle_ms=args.image_settle_ms)
        actions.append({"step": "paste_image", "image_index": index, "image_path": str(image_path), "result": result})
        time.sleep(args.after_image_sleep)

    if args.send:
        assert args.send_point is not None
        actions.append({"step": "click_send", "result": controller.click_point(args.send_point.x, args.send_point.y, settle_ms=args.click_settle_ms, hold_ms=80)})

    return {
        "dry_run": False,
        "delivery_status": _delivery_status(send=bool(args.send), dry_run=False),
        "send_click_attempted": bool(args.send),
        "sent": False,
        "sent_field_semantics": "true only after an external post-send verification; fixed-point click alone is not sent",
        "post_send_verification": _verification_contract(expected_images=args.expected_images),
        "window": asdict(bound),
        "prompt_length": len(prompt),
        "image_count": len(image_paths),
        "flow_preset": preset.name if preset is not None else None,
        "fixed_flow_steps": _fixed_flow_steps(send=bool(args.send)),
        "planned_action_sequence": _planned_action_sequence(
            image_count=len(image_paths),
            clear_attachments=bool(args.clear_attachments),
            send=bool(args.send),
        ),
        "actual_action_sequence": _actual_action_sequence(actions),
        "actions": actions,
        "postcondition": (
            "Use ChatGPT DOM/status check to verify latest user message prompt token and image count. "
            "This script handles fixed-point click/paste/send-click flow only."
        ),
        "focus_contract": _focus_contract(args),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send a fixed-point ChatGPT visual-audit prompt through the Codex in-app browser.")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--prompt-file", default=None)
    parser.add_argument("--image", action="append", default=[], required=True)
    parser.add_argument("--expected-images", type=int, default=None)
    parser.add_argument(
        "--flow-preset",
        choices=sorted(FIXED_FLOW_PRESETS),
        default=None,
        help="Use a fully scripted fixed-point flow. The preset overrides composer/send/remove points.",
    )
    parser.add_argument("--window-handle", type=int, default=None)
    parser.add_argument("--composer-point", type=_parse_point, default=Point(1105, 1117), help="Codex-window-relative x,y point inside the ChatGPT composer.")
    parser.add_argument("--send-point", type=_parse_point, default=None, help="Codex-window-relative x,y point on the ChatGPT send button. Required when --send is used.")
    parser.add_argument("--remove-first-point", type=_parse_point, default=Point(1029, 598), help="Codex-window-relative x,y point on the first attachment remove button.")
    parser.add_argument("--remove-gap-x", type=int, default=64)
    parser.add_argument("--remove-slots", type=int, default=4)
    parser.add_argument("--clear-existing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--clear-attachments", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refocus-before-each-image", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--click-settle-ms", type=int, default=250)
    parser.add_argument("--image-settle-ms", type=int, default=1500)
    parser.add_argument("--after-click-sleep", type=float, default=0.5)
    parser.add_argument("--after-clear-sleep", type=float, default=0.3)
    parser.add_argument("--after-remove-sleep", type=float, default=0.4)
    parser.add_argument("--after-text-sleep", type=float, default=1.0)
    parser.add_argument("--after-image-sleep", type=float, default=1.2)
    parser.add_argument("--out", default=None, help="Optional UTF-8 JSON evidence path for the fixed-flow run result.")
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run(args)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
