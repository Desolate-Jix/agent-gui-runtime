"""原子投递单条本地命令并返回紧凑结果；不会超时重发。"""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--payload-base64", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if not args.id.isascii() or any(c not in "0123456789abcdefghijklmnopqrstuvwxyz-_" for c in args.id):
        raise ValueError("command id must contain ASCII lowercase letters, digits, dash or underscore")
    payload = json.loads(base64.b64decode(args.payload_base64).decode("utf-8"))
    source = args.session / "commands" / (args.id + ".json")
    destination = args.session / "responses" / (args.id + ".json")
    if source.exists():
        if json.loads(source.read_text(encoding="utf-8")) != payload:
            raise ValueError("command id already used for a different payload")
    else:
        temp = source.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(source)
    started = time.perf_counter()
    deadline = started + args.timeout
    while not destination.exists():
        if time.perf_counter() >= deadline:
            raise TimeoutError("command still pending; inspect the same id, do not resubmit input")
        time.sleep(.02)
    response = json.loads(destination.read_text(encoding="utf-8"))
    result = response.get("result", {})
    compact = {"id": args.id, "status": response["status"], "command_wall_ms": response["command_wall_ms"],
        "phase": result.get("phase"), "result_status": result.get("status"),
        "error": response.get("error"), "observation": response.get("observation"),
        "response_success": (result.get("response") or {}).get("success"),
        "response_error": (result.get("response") or {}).get("error"),
        "invocation_timings": result.get("invocation_timings"), "timings": result.get("timings"),
        "ocr": result.get("ocr"), "response_path": str(destination.resolve()),
        "client_result_read_at": datetime.now(timezone.utc).isoformat(),
        "client_wait_ms": round((time.perf_counter() - started) * 1000, 3)}
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
