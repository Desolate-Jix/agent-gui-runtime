"""保持单一 MCP 会话的 UTF-8 JSONL 执行入口；复用原计划轮询与输入门禁。"""
from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
from copy import deepcopy
from hashlib import sha256
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.learning_benchmark_client import BenchmarkCallError, LearningBenchmarkClient


_MAX_CALLER_IMAGE_BYTES = 20 * 1024 * 1024


class ExecutionClient(LearningBenchmarkClient):
    def __init__(self, *, root: Path, data_root: Path, prepare_models: bool = False, **options):
        if type(prepare_models) is not bool:
            raise ValueError("execution_client_prepare_models_invalid")
        super().__init__(root=root, data_root=data_root, evidence_dir=data_root, **options)
        self._issued_commands = {}
        self._image_directory = self.data_root / "caller-images" / uuid4().hex
        self.prepare_models = prepare_models
        if prepare_models and self.recognition_source != "local":
            raise ValueError("execution_client_prepare_models_requires_local")
        self.models_prepared = False
        self.preparation_request_id = None

    def _journal(self, *args):
        # 日常入口不生成基准计时、临时脚本或独立证据目录。
        return None

    def _decode_response(self, response, tool, args):
        blocks = list(getattr(response, "content", ()) or ())
        images = {index: block for index, block in enumerate(blocks) if block.type == "image"}
        image_only = (tool == "instant_image" and images
            and not isinstance(getattr(response, "structuredContent", None), dict)
            and not any(block.type == "text" for block in blocks))
        value = ({"request_id": args["request_id"], "view": args.get("view", "after"),
            "status": "returned", "read_only": True, "automatic_retry_allowed": False} if image_only
            else deepcopy(super()._decode_response(response, tool, args)))
        deliveries = value.get("image_delivery", [])
        if not images and not any(row.get("status") == "included" for row in deliveries):
            return value
        decoded = {}
        for index, block in images.items():
            if block.mime_type != "image/png":
                raise ValueError("execution_client_image_type_invalid")
            if len(block.data) > ((_MAX_CALLER_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError("execution_client_image_too_large")
            try:
                pixels = base64.b64decode(block.data, validate=True)
            except (ValueError, binascii.Error):
                raise ValueError("execution_client_image_base64_invalid") from None
            if len(pixels) > _MAX_CALLER_IMAGE_BYTES:
                raise ValueError("execution_client_image_too_large")
            if not pixels.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("execution_client_image_png_invalid")
            decoded[index] = (pixels, sha256(pixels).hexdigest())
        if image_only:
            deliveries = [{"view": value["view"], "status": "included", "content_index": index,
                "sha256": digest, "original_pixels": True} for index, (_, digest) in decoded.items()]
        if not isinstance(deliveries, list) or any(not isinstance(row, dict) for row in deliveries):
            raise ValueError("execution_client_image_binding_invalid")
        included = [row for row in deliveries if row.get("status") == "included"]
        indices = [row.get("content_index") for row in included]
        if (any(type(index) is not int or index not in decoded for index in indices)
                or len(set(indices)) != len(indices) or set(indices) != set(decoded)):
            raise ValueError("execution_client_image_binding_invalid")
        for row in included:
            if row.get("sha256") != decoded[row["content_index"]][1]:
                raise ValueError("execution_client_image_hash_mismatch")
        # 所有块与上游摘要核对后才落盘，路径仅由本地 UUID 和内容摘要生成。
        root, directory = self.data_root.resolve(), self._image_directory.resolve()
        if not directory.is_relative_to(root) or directory == root:
            raise ValueError("execution_client_image_path_invalid")
        directory.mkdir(parents=True, exist_ok=True)
        if self._image_directory.resolve() != directory:
            raise ValueError("execution_client_image_path_invalid")
        for row in included:
            index = row.pop("content_index")
            pixels, digest = decoded[index]
            path = directory / (digest + ".png")
            if path.resolve().parent != directory:
                raise ValueError("execution_client_image_path_invalid")
            try:
                with path.open("xb") as stream:
                    stream.write(pixels)
            except FileExistsError:
                if path.read_bytes() != pixels:
                    raise ValueError("execution_client_image_file_conflict") from None
            row.update(status="saved", image_path=str(path), sha256=digest, mime_type="image/png",
                bytes=len(pixels), source_content_index=index)
        value["image_delivery"] = deliveries
        return value

    def _unsubmitted_result(self, request_id, command, status_request_id, command_id):
        if request_id not in self._issued_commands:
            return super()._unsubmitted_result(request_id, command, status_request_id, command_id)
        self._adopt_command(request_id, self._normalize_command(request_id, command),
            existing_command=self._issued_commands[request_id])
        # 本次没有等待预算，不可覆盖此前已发出请求的未知输入事实。
        return self._result({"request_id": request_id, "status": "result_unknown",
            "wait_expired": True, "command_cancelled": False}, request_id, status_request_id, command_id, "pending")

    async def _invoke(self, tool, args):
        if tool == "instant_start":
            # new_session 成功才拥有宿主；拒绝启动不能关闭既有会话。
            self._start_attempted = False
        value = await super()._invoke(tool, args)
        if tool == "instant_start":
            if value.get("status") == "start_rejected":
                raise BenchmarkCallError(tool, "start_rejected", None, response=value)
            self._start_attempted = True
        return value

    async def __aenter__(self):
        await super().__aenter__()
        try:
            if self.prepare_models:
                self.preparation_request_id = "prepare-models-" + uuid4().hex
                response = await self.run(self.preparation_request_id, {"kind": "prepare_models"},
                    total_timeout=self.ready_timeout)
                prepared = (response.get("result") or {}).get("status")
                if (response.get("status") != "returned" or response.get("operation_succeeded") is not True
                        or prepared not in {"ready", "model_not_required"}):
                    raise BenchmarkCallError("instant_run", str(response.get("status")),
                        self.preparation_request_id, response=response)
                self.models_prepared = prepared == "ready"
            return self
        except BaseException as error:
            await super().__aexit__(type(error), error, error.__traceback__)
            raise

    def _check_command(self, tool, args):
        if args.get("command") == {"kind": "prepare_models"}:
            # 显式准备仅加载资源，不授予任何真实输入权限。
            if self.recognition_source != "local":
                raise ValueError("execution_client_prepare_models_requires_local")
            return
        return super()._check_command(tool, args)

    @staticmethod
    def _normalize_command(request_id, command):
        from app.core.instant_attachment_transport import _validate_request_id
        from app.instant_mcp import InstantCommand
        _validate_request_id(request_id)
        return InstantCommand.model_validate(command).command()

    def _session_path(self):
        if not self.session_directory or not Path(self.session_directory).is_absolute():
            return None
        directory = Path(self.session_directory).resolve()
        if not directory.is_relative_to(self.data_root) or directory == self.data_root:
            raise ValueError("execution_client_session_path_invalid")
        return directory

    def _adopt_command(self, request_id, command, *, existing_command=None):
        from app.execution.public_input_defaults import (
            adopt_public_input_command, learning_recording_enabled, needs_visual_input_default)
        try:
            return adopt_public_input_command(request_id, command, existing_command=existing_command,
                learning_recording=existing_command is None and needs_visual_input_default(command)
                    and learning_recording_enabled(self._session_path()))
        except ValueError as error:
            if existing_command is not None:
                raise ValueError("execution_client_request_id_conflict") from error
            raise

    async def call(self, name: str, args: dict | None = None):
        arguments = deepcopy(args) if args is not None else {}
        if name in {"instant_run", "instant_submit"}:
            if not isinstance(arguments, dict):
                raise ValueError("execution_client_arguments_invalid")
            request_id = arguments.get("request_id")
            command = self._normalize_command(request_id, arguments.get("command"))
            if request_id in self._issued_commands:
                self._adopt_command(request_id, command, existing_command=self._issued_commands[request_id])
                # 即使上次传输失败，也只读原票据，不再提交动作。
                return await super().call("instant_result", {"request_id": request_id,
                    "detail": "full", "images": "none"})
            directory = self._session_path()
            path = directory / "commands" / (request_id + ".json") if directory is not None else None
            if path is not None and path.is_file():
                from app.core.json_snapshot import read_json_snapshot
                command = self._adopt_command(request_id, command, existing_command=read_json_snapshot(path))
                self._issued_commands[request_id] = deepcopy(command)
                return await super().call("instant_result", {"request_id": request_id,
                    "detail": "full", "images": "none"})
            command = self._adopt_command(request_id, command)
            arguments["command"] = command
            self._check_command(name, arguments)
            self._issued_commands[request_id] = deepcopy(command)
        return await super().call(name, arguments)

    @staticmethod
    def _compact_response(response):
        from app.instant_receipt import compact_receipt
        if response.get("status") == "not_submitted":
            return {**deepcopy(response), "receipt_detail": "compact"}
        if "execution_receipts" in response or response.get("receipt_detail") == "compact":
            # 计划投影已验证原始绑定；审核包和哈希不得再次裁剪或重算。
            value = deepcopy(response)
            value["receipt_detail"] = "compact"
        else:
            value = compact_receipt(response)
        for key in ("original_request_id", "current_status_request_id", "command_id", "client_state", "no_replay", "image_delivery"):
            if key in response:
                value[key] = deepcopy(response[key])
        original_id = response.get("original_request_id", response.get("request_id"))
        if original_id is not None:
            value.setdefault("original_request_id", original_id)
            value.setdefault("original_receipt", ExecutionClient._receipt_reference(original_id))
            current_id = response.get("request_id")
            if current_id is not None:
                value.setdefault("current_receipt", ExecutionClient._receipt_reference(current_id))
                value.setdefault("full_receipt", deepcopy(value["current_receipt"]))
            else:
                value["full_receipt"] = deepcopy(value.get("current_receipt", value["original_receipt"]))
            value.setdefault("images", [{"tool": "instant_image", "arguments": {
                "request_id": response.get("command_id") or original_id, "view": "after"}}])
        return value

    async def execute(self, message: dict):
        if not isinstance(message, dict):
            raise ValueError("execution_client_message_invalid")
        if "tool" in message:
            if set(message) != {"tool", "arguments"} or not isinstance(message["arguments"], dict):
                raise ValueError("execution_client_tool_message_invalid")
            tool, arguments = message["tool"], message["arguments"]
            if tool == "instant_run":
                if (not {"request_id", "command"} <= set(arguments)
                        or set(arguments) - {"request_id", "command", "wait_ms", "detail", "images"}
                        or arguments.get("detail", "compact") not in ("compact", "full")
                        or arguments.get("images", "none") != "none"):
                    raise ValueError("execution_client_run_arguments_invalid")
                wait_ms = arguments.get("wait_ms", 120000)
                if type(wait_ms) is not int or not 0 <= wait_ms <= 120000:
                    raise ValueError("execution_client_wait_ms_invalid")
                return await self.execute({"request_id": arguments["request_id"],
                    "command": arguments["command"], "total_timeout": wait_ms / 1000,
                    "detail": arguments.get("detail", "compact")})
            if tool not in {"instant_status", "instant_result", "instant_image", "instant_submit"}:
                raise ValueError("execution_client_tool_invalid")
            if tool == "instant_result":
                arguments = deepcopy(arguments)
                arguments.setdefault("detail", "compact")
                arguments.setdefault("images", "none")
            response = await self.call(tool, arguments)
            return (self._compact_response(response) if tool == "instant_submit"
                or tool == "instant_result" and arguments["detail"] == "compact" else response)
        if (not {"request_id", "command"} <= set(message)
                or set(message) - {"request_id", "command", "total_timeout", "detail"}):
            raise ValueError("execution_client_command_message_invalid")
        detail = message.get("detail", "compact")
        if detail not in ("compact", "full"):
            raise ValueError("execution_client_detail_invalid")
        timeout = message.get("total_timeout", 120)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("execution_client_total_timeout_invalid")
        command = self._normalize_command(message["request_id"], message["command"])
        runner = self.run_plan if command["kind"] == "task_plan" else self.run
        response = await runner(message["request_id"], command, total_timeout=timeout)
        return self._compact_response(response) if detail == "compact" else response


def _emit(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    stream.flush()


def _error(error, *, request_id=None):
    # 验证异常可能包含原输入；只输出受控代码与异常类别，不回显载荷或环境。
    code = "execution_client_command_failed"
    if isinstance(error, json.JSONDecodeError):
        code = "execution_client_json_invalid"
    elif isinstance(error, BenchmarkCallError):
        response = error.response or {}
        candidate = (response.get("error") or {}).get("code")
        if isinstance(candidate, str) and candidate.isascii() and candidate.replace("_", "").isalnum():
            code = candidate
    elif isinstance(error, ValueError):
        candidate = str(error)
        if candidate.isascii() and candidate.replace("_", "").isalnum():
            code = candidate
    value = {"event": "error", "error": {"code": code, "type": type(error).__name__},
        "automatic_retry_allowed": False}
    if isinstance(error, BenchmarkCallError) and error.request_id is not None:
        request_id = error.request_id
    if request_id is not None:
        value["request_id"] = request_id
        value["original_receipt"] = {"tool": "instant_result", "arguments": {
            "request_id": request_id, "detail": "full", "images": "none"}}
    return value


def _message_request_id(message):
    if not isinstance(message, dict):
        return None
    arguments = message.get("arguments") if "tool" in message else message
    if not isinstance(arguments, dict):
        return None
    request_id = arguments.get("request_id")
    if not isinstance(request_id, str):
        return None
    from app.core.instant_attachment_transport import _validate_request_id
    try:
        _validate_request_id(request_id)
    except ValueError:
        return None
    return request_id


async def serve_jsonl(client: ExecutionClient, *, input_stream=None, output_stream=None):
    incoming = input_stream if input_stream is not None else sys.stdin
    outgoing = output_stream if output_stream is not None else sys.stdout
    try:
        async with client as opened:
            _emit(outgoing, {"event": "ready", "session_directory": opened.session_directory,
                "recognition_source": opened.recognition_source, "actions_enabled": opened.allow_actions,
                "models_prepared": opened.models_prepared,
                "model_state": ("prepared" if opened.models_prepared else "cold")
                    if opened.recognition_source == "local" else "not_required",
                "preparation_request_id": opened.preparation_request_id})
            while True:
                line = await asyncio.to_thread(incoming.readline)
                if not line:
                    break
                if not line.strip():
                    continue
                message = None
                try:
                    message = json.loads(line)
                    if message == {"action": "finish"}:
                        break
                    response = await opened.execute(message)
                    _emit(outgoing, {"event": "result", "response": response})
                except Exception as error:
                    _emit(outgoing, _error(error, request_id=_message_request_id(message)))
        _emit(outgoing, {"event": "finished", "cleanup_verified": client.status.get("cleanup_verified") is True})
        return 0
    except Exception as error:
        _emit(outgoing, _error(error))
        return 1


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("execution_client_arguments_invalid")


def main(argv=None, *, input_stream=None, output_stream=None, client_factory=ExecutionClient):
    parser = _Parser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--recognition-source", choices=["local", "agent_current", "agent_delegate", "external_api"])
    parser.add_argument("--luna-api", action="store_true",
        help="Explicitly use external_api with the repository Luna example profile; credentials stay in the environment")
    parser.add_argument("--delegate-profile")
    parser.add_argument("--api-profile", type=Path)
    parser.add_argument("--decision-profile", type=Path)
    parser.add_argument("--allow-actions", action="store_true")
    parser.add_argument("--prepare-models", action="store_true",
        help="Explicitly prepare the configured local models once before ready; existing runtime OCR policy applies")
    parser.add_argument("--administrator", action="store_true")
    outgoing = output_stream if output_stream is not None else sys.stdout
    try:
        args = parser.parse_args(argv)
        if args.luna_api:
            profile = args.root.resolve() / "configs/vision-api-openai-luna.example.json"
            if (args.recognition_source not in {None, "external_api"} or args.model_directory is not None
                    or args.delegate_profile is not None or args.prepare_models
                    or args.api_profile is not None and args.api_profile.resolve() != profile):
                raise ValueError("execution_client_luna_api_conflict")
            args.recognition_source, args.api_profile = "external_api", profile
        else:
            args.recognition_source = args.recognition_source or "local"
        opened = client_factory(root=args.root, data_root=args.data_dir, model_directory=args.model_directory,
            recognition_source=args.recognition_source, delegate_profile=args.delegate_profile,
            api_profile=args.api_profile, decision_profile=args.decision_profile,
            allow_actions=args.allow_actions, administrator=args.administrator, prepare_models=args.prepare_models)
        return asyncio.run(serve_jsonl(opened, input_stream=input_stream, output_stream=outgoing))
    except Exception as error:
        _emit(outgoing, _error(error))
        return 1


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
