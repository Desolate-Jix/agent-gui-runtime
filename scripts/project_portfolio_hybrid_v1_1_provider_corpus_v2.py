"""Project the frozen Benchmark v1 parent into a provider-safe v2 child."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.hybrid.benchmark_v2_privileged_projector import project_provider_corpus


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    receipt = project_provider_corpus(
        parent_manifest_path=args.parent_manifest,
        output_path=args.output,
    )
    print(json.dumps({**receipt, "process_id": os.getpid()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
