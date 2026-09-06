"""一次显式无动作的 GUIActor 当前源码调用。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.learn.hybrid.gui_actor_current_source import run_gui_actor_child, run_gui_actor_once


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    parser.add_argument("--goal")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--artifact-root", type=Path, default=Path("E:/") / "\u6a21\u578b\u6d4b\u8bd5")
    parser.add_argument("--storage-limit-bytes", type=int, default=32_212_254_720)
    parser.add_argument("--operator-approved-model-start", action="store_true")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--invocation", type=Path)
    parser.add_argument("--child-result", type=Path)
    args = parser.parse_args(argv)
    if args.child:
        if args.invocation is None or args.child_result is None:
            parser.error("--child requires --invocation and --child-result")
        run_gui_actor_child(invocation_path=args.invocation, child_result_path=args.child_result)
        return
    if args.image is None or args.goal is None or args.out is None:
        parser.error("--image, --goal, and --out are required")
    run_gui_actor_once(project_root=ROOT, image_path=args.image, target_text=args.goal, artifact_root=args.artifact_root, out_dir=args.out, storage_limit_bytes=args.storage_limit_bytes)


if __name__ == "__main__":
    main()
