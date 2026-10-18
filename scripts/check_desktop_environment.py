"""无需第三方依赖即可报告原生桌面与执行环境的已知缺项。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.runtime_environment import PROFILE_NAMES, inspect_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect native desktop dependency metadata without importing backends.")
    parser.add_argument("--profile", choices=PROFILE_NAMES, default="all")
    arguments = parser.parse_args()
    report = inspect_environment(profile=arguments.profile)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
