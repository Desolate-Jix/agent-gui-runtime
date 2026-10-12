"""固定 JSONL 调用方的图片交付与总等待预算离线回归。"""
import asyncio
import base64
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
from types import SimpleNamespace

from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image
import pytest

from scripts import execution_client, learning_benchmark_client
from tests.test_execution_client import client
from tests.test_learning_benchmark_client import FakeSDK, ToolResult


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # 假连接只接收空环境，不读取本机 API 密钥。
    monkeypatch.setattr(learning_benchmark_client, "os", SimpleNamespace(environ={}))


def png_bytes(color="blue"):
    stream = io.BytesIO()
    Image.new("RGB", (3, 2), color).save(stream, format="PNG")
    return stream.getvalue()


class ImageSDK(FakeSDK):
    def __init__(self, pixels, *, digest=None, encoded=None, mime_type="image/png", content_index=1):
        super().__init__()
        self.pixels = pixels
        self.digest = digest or sha256(pixels).hexdigest()
        self.encoded = encoded if encoded is not None else base64.b64encode(pixels).decode("ascii")
        self.mime_type = mime_type
        self.content_index = content_index

    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name not in {"instant_image", "instant_result"}:
                return await original(name, args)
            self.calls.append((name, deepcopy(args)))
            image = ImageContent(type="image", data=self.encoded, mimeType=self.mime_type)
            if name == "instant_image":
                return CallToolResult(content=[image])
            value = {"request_id": args["request_id"], "status": "returned", "result": {
                "contract_version": "input_sequence_v1", "status": "completed", "steps": []},
                "image_delivery": [{"view": "after", "status": "included", "sha256": self.digest,
                    "content_index": self.content_index, "original_pixels": True, "capture_id": "fresh-capture"}]}
            return CallToolResult(structuredContent=value, content=[
                TextContent(type="text", text=json.dumps(value)), image])

        session.call_tool = call_tool
        return session


def test_jsonl_image_only_and_compact_mixed_responses_save_exact_original_png(tmp_path):
    pixels = png_bytes()
    sdk = ImageSDK(pixels)
    opened = client(tmp_path, sdk)
    outgoing = io.StringIO()
    exit_code = asyncio.run(execution_client.serve_jsonl(opened, input_stream=io.StringIO(
        '{"tool":"instant_image","arguments":{"request_id":"original","view":"before"}}\n'
        '{"tool":"instant_result","arguments":{"request_id":"original","detail":"compact","images":"after"}}\n'
        '{"action":"finish"}\n'), output_stream=outgoing))
    rows = [json.loads(line) for line in outgoing.getvalue().splitlines()]
    assert exit_code == 0
    assert [row["event"] for row in rows] == ["ready", "result", "result", "finished"]
    pure, mixed = rows[1]["response"], rows[2]["response"]
    assert pure["request_id"] == "original" and pure["view"] == "before" and pure["read_only"] is True
    assert mixed["receipt_detail"] == "compact"
    for response, index, view in ((pure, 0, "before"), (mixed, 1, "after")):
        delivery = response["image_delivery"][0]
        assert delivery["status"] == "saved" and delivery["view"] == view
        assert delivery["source_content_index"] == index and "content_index" not in delivery
        assert delivery["sha256"] == sha256(pixels).hexdigest()
        assert delivery["mime_type"] == "image/png" and delivery["bytes"] == len(pixels)
        path = Path(delivery["image_path"])
        assert path.is_absolute() and path.read_bytes() == pixels
        assert path.parent.parent == opened.data_root / "caller-images"
        assert len(path.parent.name) == 32 and path.parent.name.isascii()
    assert mixed["image_delivery"][0]["capture_id"] == "fresh-capture"
    assert sdk.encoded not in outgoing.getvalue()
    assert rows[-1]["cleanup_verified"] is True


@pytest.mark.parametrize("detail", ["compact", "full"])
def test_mixed_response_rejects_wrong_upstream_image_hash_without_saving(tmp_path, detail):
    sdk = ImageSDK(png_bytes(), digest="0" * 64)

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="execution_client_image_hash_mismatch"):
                await opened.execute({"tool": "instant_result", "arguments": {
                    "request_id": "original", "detail": detail, "images": "after"}})

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.png"))


@pytest.mark.parametrize("options,code", [
    ({"encoded": "not-valid-base64!"}, "execution_client_image_base64_invalid"),
    ({"mime_type": "image/jpeg"}, "execution_client_image_type_invalid"),
    ({"content_index": 0}, "execution_client_image_binding_invalid"),
])
def test_invalid_image_transport_is_explicit_and_never_saves_pixels(tmp_path, options, code):
    sdk = ImageSDK(png_bytes(), **options)

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match=code):
                await opened.execute({"tool": "instant_result", "arguments": {
                    "request_id": "original", "detail": "full", "images": "after"}})

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.png"))


def test_image_size_limit_rejects_before_writing(tmp_path, monkeypatch):
    pixels = png_bytes()
    monkeypatch.setattr(execution_client, "_MAX_CALLER_IMAGE_BYTES", len(pixels) - 1, raising=False)
    sdk = ImageSDK(pixels)

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="execution_client_image_too_large"):
                await opened.execute({"tool": "instant_image", "arguments": {"request_id": "original"}})

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.png"))


def test_each_client_uses_its_own_image_directory_and_never_overwrites_prior_files(tmp_path):
    pixels = png_bytes()

    async def read_image():
        async with client(tmp_path, ImageSDK(pixels)) as opened:
            result = await opened.execute({"tool": "instant_image", "arguments": {"request_id": "original"}})
            return Path(result["image_delivery"][0]["image_path"])

    first = asyncio.run(read_image())
    first.write_bytes(b"previous-session-file")
    second = asyncio.run(read_image())
    assert first.parent != second.parent
    assert first.read_bytes() == b"previous-session-file" and second.read_bytes() == pixels


def test_image_directory_escape_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    try:
        (data / "caller-images").symlink_to(outside, target_is_directory=True)
    except OSError:
        import _winapi
        _winapi.CreateJunction(str(outside), str(data / "caller-images"))

    async def scenario():
        async with client(tmp_path, ImageSDK(png_bytes())) as opened:
            with pytest.raises(ValueError, match="execution_client_image_path_invalid"):
                await opened.execute({"tool": "instant_image", "arguments": {"request_id": "original"}})

    asyncio.run(scenario())
    assert not list(outside.rglob("*.png"))


class DelayedSDK(FakeSDK):
    def __init__(self, stage):
        super().__init__()
        self.stage = stage
        self.delayed = False
        self.cancelled = False

    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name not in {"instant_run", "instant_result"}:
                return await original(name, args)
            self.calls.append((name, deepcopy(args)))
            is_status = (args.get("command") or {}).get("kind") == "agent_command_status"
            should_delay = ((self.stage == "initial" and name == "instant_run")
                or (self.stage == "receipt" and name == "instant_result")
                or (self.stage == "agent_status" and is_status)
                or (self.stage == "agent_receipt" and name == "instant_result"))
            if should_delay and not self.delayed:
                self.delayed = True
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            if self.delayed:
                return ToolResult({"request_id": args["request_id"], "status": "returned",
                    "operation_succeeded": True})
            if self.stage.startswith("agent"):
                return ToolResult({"request_id": args["request_id"], "status": "pending"} if is_status else
                    self.agent_receipt(args["request_id"], "original", "running"))
            return ToolResult({"request_id": args["request_id"], "status": "pending"})

        session.call_tool = call_tool
        return session


@pytest.mark.parametrize("stage", ["initial", "receipt", "agent_status", "agent_receipt"])
def test_total_timeout_bounds_every_mcp_wait_and_original_receipt_can_be_read(tmp_path, stage):
    sdk = DelayedSDK(stage)

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            result = await asyncio.wait_for(opened.execute({"request_id": "original",
                "command": {"kind": "discover"}, "total_timeout": .1}), timeout=.8)
            assert result["status"] == "result_unknown" and result["client_state"] == "pending"
            assert result["original_request_id"] == "original" and result["no_replay"] is True
            assert result["wait_expired"] is True and result["command_cancelled"] is False
            assert "operation_succeeded" not in result and "action_executed" not in result
            next_read = result["next"]
            assert next_read["tool"] == "instant_result"
            assert next_read["arguments"]["request_id"] == result["request_id"]
            recovered = await opened.execute(next_read)
            assert recovered["request_id"] == result["request_id"] and recovered["status"] == "returned"
            return result

    result = asyncio.run(scenario())
    assert sdk.cancelled is True
    submitted = [args for name, args in sdk.calls if name == "instant_run"]
    assert [args["request_id"] for args in submitted].count("original") == 1
    assert not any((args.get("command") or {}).get("kind") == "agent_command_cancel" for _, args in sdk.calls)
    if stage.startswith("agent"):
        assert result["command_id"] == "original"
        assert result["request_id"] != "original"


def test_zero_budget_does_not_submit_or_invent_receipts_and_same_id_can_later_submit(tmp_path):
    sdk = FakeSDK()

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            request = {"request_id": "not-issued", "command": {"kind": "discover"}, "total_timeout": 0}
            result = await opened.execute(request)
            assert result["status"] == result["client_state"] == "not_submitted"
            assert result["accepted"] is False and result["action_executed"] is False
            assert not any(name in {"instant_run", "instant_submit", "instant_result"} for name, _ in sdk.calls)
            assert not {"original_receipt", "current_receipt", "full_receipt", "images", "next"} & set(result)
            recovered = await opened.execute({**request, "total_timeout": 1})
            assert recovered["status"] == "returned" and recovered["original_request_id"] == "not-issued"

    asyncio.run(scenario())
    assert [name for name, _ in sdk.calls].count("instant_run") == 1


def test_zero_budget_for_previously_issued_id_preserves_unknown_and_command_binding(tmp_path):
    sdk = DelayedSDK("initial")

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            request = {"request_id": "original", "command": {"kind": "discover"}}
            await asyncio.wait_for(opened.execute({**request, "total_timeout": .1}), timeout=.8)
            count = len(sdk.calls)
            result = await opened.execute({**request, "total_timeout": 0})
            assert result["status"] == "result_unknown" and result["client_state"] == "pending"
            assert result["no_replay"] is True and result["original_request_id"] == "original"
            assert result["next"]["arguments"]["request_id"] == "original"
            assert "accepted" not in result and "action_executed" not in result
            assert len(sdk.calls) == count
            with pytest.raises(ValueError, match="execution_client_request_id_conflict"):
                await opened.execute({"request_id": "original", "command": {"kind": "capture"},
                    "total_timeout": 0})

    asyncio.run(scenario())
