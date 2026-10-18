from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent_link.http_app import create_agent_link_app
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the loopback-only Agent Link staging inbox.")
    parser.add_argument("--state-path", required=True, help="Explicit persistent JSON inbox path.")
    parser.add_argument("--port", type=int, required=True, help="Explicit loopback TCP port.")
    arguments = parser.parse_args()
    token = os.environ.get("AGENT_LINK_REVIEWER_TOKEN")
    if not token:
        parser.error("AGENT_LINK_REVIEWER_TOKEN environment variable is required")
    if not 1 <= arguments.port <= 65535:
        parser.error("--port must be in 1..65535")
    store = AgentLinkStore(arguments.state_path)
    try:
        import uvicorn
        uvicorn.run(create_agent_link_app(AgentLinkService(store, reviewer_token=token)), host="127.0.0.1", port=arguments.port, workers=1, access_log=False, log_level="warning")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
