"""将操作方明确选定的 PNG 打包；只返回引用，不生成或提交学习语义。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_link.artifact_packaging import prepare_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a connection-bound PNG transport bundle; no Agent request is sent.")
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--image", required=True, action="append", metavar="ARTIFACT_ID=PNG_PATH")
    args = parser.parse_args()
    images = {}
    for entry in args.image:
        identity, separator, filename = entry.partition("=")
        if not separator or not identity or not filename or identity in images:
            parser.error("each image needs a unique ARTIFACT_ID=PNG_PATH")
        images[identity] = Path(filename)
    try:
        result = prepare_bundle(images, connection_id=args.connection_id, task_id=args.task_id, output=args.output)
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"error": "artifact_bundle_preparation_failed", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
