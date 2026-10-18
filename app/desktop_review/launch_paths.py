"""区分开发解释器与可迁移安装包中的 STDIO 伴随程序。"""
from __future__ import annotations

from pathlib import Path
import sys


def agent_bridge_command() -> dict:
    if getattr(sys, "frozen", False):
        return {"command": str(Path(sys.executable).with_name("AgentReviewBridge.exe")), "args": ["--agent-link-mcp"]}
    return {"command": sys.executable, "args": [str(Path(__file__).resolve().parents[2] / "scripts/start_agent_review.py"), "--agent-link-mcp"]}
