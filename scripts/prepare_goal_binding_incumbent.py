"""Explicitly record the existing read-only Qwen incumbent for the A/B runner."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "configs/model_profiles/goal_binding_qwen_incumbent.json")
    parser.add_argument("--root", type=Path, required=True, help="Existing production model-test root; only reports are written")
    args = parser.parse_args(argv)
    from app.learn.hybrid.goal_binding_model_callers import load_goal_binding_profile
    from app.learn.hybrid.goal_binding_managed_artifacts import materialize_incumbent_profile
    try:
        path = materialize_incumbent_profile(load_goal_binding_profile(args.profile), args.root)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"incumbent preparation failed: {exc}\n")
    print(json.dumps({"profile_path": str(path), "model_started": False, "assets_copied": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
