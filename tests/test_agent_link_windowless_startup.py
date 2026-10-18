from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


_PROBE = r'''
import json
from pathlib import Path
import socket
import sys
import traceback
from urllib.request import ProxyHandler, Request, build_opener
from app.desktop_review.host import DesktopReviewHost

root, mode = Path(sys.argv[1]), sys.argv[2]
host = None
result = {}
if mode in {"no_stdout", "no_stdio"}:
    sys.stdout = None
if mode == "no_stdio":
    sys.stderr = None
try:
    host = DesktopReviewHost(root / "inbox.json", root / "reviews", "windowless-test-reviewer")
    ready = host.start(timeout=3)
    grant = host.connections.create_connection("windowless-task", "windowless-test")
    request = Request(ready["base_url"] + "/agent/status", data=b"{}",
        headers={"Authorization": "Bearer " + grant["token"], "Content-Type": "application/json"}, method="POST")
    with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
        status = json.loads(response.read().decode("utf-8"))
    result = {"phase": ready["phase"], "task_id": status["task_id"], "staging_only": status["staging_only"]}
    port = int(ready["base_url"].rsplit(":", 1)[1])
    host.connections.revoke_connection(grant["connection_id"], "windowless-revoke")
    host.close()
    result["closed"] = host.status()["phase"] == "stopped"
    with socket.socket() as probe:
        probe.settimeout(0.2)
        result["port_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
except Exception:
    result["traceback"] = traceback.format_exc()
finally:
    if host is not None:
        host.close()
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
'''


@pytest.mark.parametrize("mode", ["console", "no_stdout", "no_stdio"])
def test_real_desktop_host_does_not_require_console_streams(tmp_path, mode):
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(tmp_path), mode],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    observed = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert observed == {
        "phase": "ready", "task_id": "windowless-task", "staging_only": True,
        "closed": True, "port_closed": True,
    }, observed.get("traceback", observed)
