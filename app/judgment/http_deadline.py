"""同步调用外壳复用异步连接池，整次传输共用单调截止时间。"""
import asyncio
import math
from threading import Thread
from time import monotonic

import httpx


class DeadlineHTTPTransport(httpx.BaseTransport):
    def __init__(self, *, max_response_bytes=64 * 1024, error_prefix="decision", thread_name="decision-http", limits=None):
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("http_response_limit_invalid")
        if error_prefix not in {"decision", "api"}:
            raise ValueError("http_error_prefix_invalid")
        if not isinstance(thread_name, str) or not thread_name or len(thread_name) > 64:
            raise ValueError("http_thread_name_invalid")
        self._max_response_bytes = max_response_bytes
        self._error_prefix = error_prefix
        options = {"retries": 0, "trust_env": False}
        if limits is not None:
            options["limits"] = limits
        self._transport = httpx.AsyncHTTPTransport(**options)
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._loop.run_forever, name=thread_name, daemon=True)
        self._closed = False
        self._tasks = set()
        self._thread.start()

    async def _exchange(self, request, deadline):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(self._error_prefix + "_provider_budget_expired")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with asyncio.timeout(remaining):
                response = await self._transport.handle_async_request(request)
                try:
                    if response.status_code != 200:
                        # 错误正文不得掩盖已知状态；关闭流后交回原始状态和响应头。
                        return httpx.Response(response.status_code, headers=response.headers, content=b"")
                    # 拒绝压缩扩张，读取和解码都不能突破响应体上限。
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise ValueError(self._error_prefix + "_content_encoding_unsupported")
                    chunks, size = [], 0
                    async for chunk in response.aiter_raw():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise ValueError(self._error_prefix + "_response_too_large")
                        chunks.append(chunk)
                    # 网络流只能留在所属事件循环；外层收到完整、有界的字节体。
                    return httpx.Response(response.status_code, headers=response.headers,
                                          content=b"".join(chunks))
                finally:
                    await response.aclose()
        finally:
            self._tasks.discard(task)

    def handle_request(self, request):
        if self._closed:
            raise OSError(self._error_prefix + "_transport_closed")
        timeout = request.extensions["timeout"]["read"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(self._error_prefix + "_timeout_invalid")
        deadline = monotonic() + timeout
        if "total_deadline" in request.extensions:
            absolute = request.extensions["total_deadline"]
            if type(absolute) not in (int, float) or not math.isfinite(absolute):
                raise ValueError(self._error_prefix + "_deadline_invalid")
            # 图片准备已耗去的预算不能在进入网络层时重新开始。
            deadline = min(deadline, absolute)
        if deadline <= monotonic():
            raise TimeoutError(self._error_prefix + "_provider_timeout")
        future = asyncio.run_coroutine_threadsafe(self._exchange(request, deadline), self._loop)
        try:
            return future.result(timeout=max(0, deadline - monotonic()))
        except TimeoutError:
            # 到点撤销同一请求，不重派；服务层保留发送标记及不确定结果。
            future.cancel()
            raise TimeoutError(self._error_prefix + "_provider_timeout") from None

    async def _shutdown(self):
        pending = list(self._tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._transport.aclose()

    def close(self):
        if self._closed:
            return
        self._closed = True
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=2)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
            if not self._thread.is_alive():
                self._loop.close()
