"""开发运行与安装包共用的原生入口。"""
from __future__ import annotations

from multiprocessing import freeze_support
from pathlib import Path
import sys


if __name__ == "__main__":
    freeze_support()
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.desktop_review.entrypoint import main
    raise SystemExit(main())
