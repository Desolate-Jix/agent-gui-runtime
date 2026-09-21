"""现有应用目录启动的唯一进程调用缝。"""
from __future__ import annotations

import subprocess
from typing import Sequence, Any


def launch_process(command: Sequence[str]) -> Any:
    """按既有列表参数语义启动，不经过 shell。"""
    return subprocess.Popen(list(command))
