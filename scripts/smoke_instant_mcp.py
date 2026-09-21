"""真实 STDIO 客户端验证；只启动宿主和读取窗口目录，不点击、不截图、不加载模型。"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time


async def run(root, model, data, administrator=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    entry = "start_instant_mcp_admin.py" if administrator else "start_instant_mcp.py"
    params = StdioServerParameters(command=sys.executable, args=[str(root / "scripts" / entry),
        "--data-dir", str(data), "--model-directory", str(model), "--allow-local-input"], env=env, cwd=str(root))
    evidence = {"actual_input_executed": False, "model_inference_tested": False,
                "administrator_requested": administrator}
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as client:
            initialized = await client.initialize()
            evidence["server_version"] = initialized.server_info.version
            assert evidence["server_version"] == "0.1.0-test.4"
            tools = await client.list_tools()
            evidence["tools"] = [t.name for t in tools.tools]
            assert len(evidence["tools"]) == 6

            async def call(name, args=None):
                result = await client.call_tool(name, args or {})
                if result.is_error:
                    raise RuntimeError(str(result.content))
                texts = [b.text for b in result.content if b.type == "text"]
                return json.loads(texts[0])

            try:
                await call("instant_start", {"new_session": True})
                deadline = time.monotonic() + 90
                while True:
                    status = await call("instant_status")
                    if status["phase"] == "ready":
                        break
                    if not status["host_alive"] or time.monotonic() > deadline:
                        raise RuntimeError(str(status))
                    await asyncio.sleep(1)
                evidence["host_is_admin"] = status.get("host_is_admin")
                if administrator:
                    assert evidence["host_is_admin"] is True, status
                # 故意缺少输入必填项，只验入队前错误；随后复用同一 ID 读取目录。
                session_directory = Path(status["session_directory"])
                initial_identity = json.loads((data / "latest-session.json").read_text(encoding="utf-8"))["host_identity"]
                invalid = await client.call_tool("instant_submit", {"request_id": "discovery-smoke",
                    "command": {"kind": "step", "operation": "type_text",
                                "request": {"unexpected_field": "REDACTION_TEST_SENTINEL"}}})
                assert invalid.is_error
                error_text = next(b.text for b in invalid.content if b.type == "text")
                rejected = json.loads(error_text)
                assert rejected["status"] == "validation_rejected" and rejected["accepted"] is False
                assert rejected["action_executed"] is False
                assert rejected["error"]["unknown_fields"] == ["unexpected_field"]
                assert "REDACTION_TEST_SENTINEL" not in error_text
                assert not list((session_directory / "commands").glob("*.json"))
                error_log = (session_directory / "validation-errors.jsonl").read_text(encoding="utf-8")
                assert "unexpected_field" in error_log and "REDACTION_TEST_SENTINEL" not in error_log
                recovered = await call("instant_status")
                assert recovered["host_alive"] and recovered["phase"] == "ready"
                assert recovered["session_directory"] == str(session_directory) and not recovered["pending_ids"]
                assert json.loads((data / "latest-session.json").read_text(encoding="utf-8"))["host_identity"] == initial_identity
                evidence["validation_error_recovery"] = {
                    "error_status": rejected["status"], "unknown_fields": rejected["error"]["unknown_fields"],
                    "input_value_redacted": True, "rejected_before_queue": True,
                    "same_host_identity": True, "same_connection": True}
                sent = await call("instant_submit", {"request_id": "discovery-smoke", "command": {"kind": "discover"}})
                assert sent["status"] == "pending"
                deadline = time.monotonic() + 60
                while True:
                    response = await call("instant_result", {"request_id": "discovery-smoke"})
                    if response["status"] != "pending":
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("query discovery-smoke; do not replay")
                    await asyncio.sleep(1)
                assert response["operation_succeeded"], response
                evidence["discovery"] = {"applications": len(response["result"]["apps"]),
                    "windows": len(response["result"]["running_windows"])}
                replay = await call("instant_submit", {"request_id": "discovery-smoke", "command": {"kind": "discover"}})
                assert replay == response
                evidence["same_id_returned_same_receipt"] = True
            finally:
                await call("instant_stop")
                deadline = time.monotonic() + 60
                while True:
                    status = await call("instant_status")
                    if status["cleanup_verified"]:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("cleanup not verified: " + str(status))
                    await asyncio.sleep(1)
                evidence["cleanup_verified"] = True
                # 已停止宿主上的新查询必须明确拒绝，而不是触发 SDK 内部异常。
                stopped_request = await client.call_tool("instant_submit", {
                    "request_id": "after-stop", "command": {"kind": "discover"}})
                assert stopped_request.is_error
                stopped_value = json.loads(next(b.text for b in stopped_request.content if b.type == "text"))
                assert stopped_value["status"] == "state_rejected"
                assert stopped_value["error"]["code"] == "host_not_ready"
                assert stopped_value["accepted"] is False and stopped_value["action_executed"] is False
                assert stopped_value["next"] == {"tool": "instant_status", "arguments": {}}
                assert not (session_directory / "commands" / "after-stop.json").exists()
                evidence["stopped_host_rejection_returned_over_stdio"] = True
    # 重连只读取旧回执，不启动第二个宿主或重放命令。
    async with stdio_client(params) as streams:
        async with ClientSession(*streams) as client:
            await client.initialize()
            attached = await client.call_tool("instant_start", {})
            assert not attached.is_error
            status = json.loads(next(b.text for b in attached.content if b.type == "text"))
            assert status["cleanup_verified"] and not status["host_alive"]
            old = await client.call_tool("instant_result", {"request_id": "discovery-smoke"})
            assert not old.is_error
            assert json.loads(next(b.text for b in old.content if b.type == "text")) == response
            evidence["reconnect_preserved_original_receipt"] = True
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--administrator", action="store_true", help="Use UAC bridge; reconnection prompts again")
    args = parser.parse_args()
    result = asyncio.run(run(Path(__file__).resolve().parents[1], args.model_directory.resolve(), args.data_dir.resolve(), args.administrator))
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
