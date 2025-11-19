import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Optional

from app.core.background_tasks import create_background_task
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import Logger
from fastapi import HTTPException, Request, WebSocket, status
from pydantic import BaseModel


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.pending_responses: dict[str, asyncio.Future] = {}
        self.streaming_responses: dict[str, asyncio.Queue] = {}

        # 新增：追踪 request_id 到 client_id 的映射
        self.request_to_client: dict[str, str] = {}

        # 新增：追踪每个 client 正在处理的请求集合
        self.client_active_requests: dict[str, set[str]] = {}

        # 新增：追踪流式请求的包计数（用于日志优化）
        self.streaming_chunk_count: dict[str, int] = {}

        self._client_ids: list[str] = []
        self._next_client_index: int = 0

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self._client_ids.append(client_id)
        self.client_active_requests[client_id] = set()

    async def disconnect(self, client_id: str):
        """断开客户端连接，清理所有活跃请求"""
        # 清理该客户端的所有活跃请求
        if client_id in self.client_active_requests:
            request_ids = list(self.client_active_requests[client_id])
            Logger.event("DISCONNECT", f"取消 {len(request_ids)} 个请求", client_id=client_id)

            # 使用 cancel_request 统一清理
            for request_id in request_ids:
                await self.cancel_request(request_id)

            # 确保客户端条目被删除
            self.client_active_requests.pop(client_id, None)

        # 清理连接
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self._client_ids:
            self._client_ids.remove(client_id)


    async def handle_message(self, message: dict[str, Any]):
        """处理从前端收到的响应消息"""
        payload = message.get("payload", {})
        request_id = message.get("id")
        
        if request_id:
            is_finished = payload.get("is_finished", "N/A")
            status = message.get("status", {})
            Logger.debug(f"接收消息 {request_id} | 完成: {is_finished} | 状态: {status}")
            Logger.debug(f"完整消息内容: {message}")

        # 检查是否为流式响应
        if request_id in self.streaming_responses:
            queue = self.streaming_responses[request_id]
            if payload.get("is_streaming"):
                if request_id not in self.streaming_chunk_count:
                    self.streaming_chunk_count[request_id] = 0
                self.streaming_chunk_count[request_id] += 1
                chunk_num = self.streaming_chunk_count[request_id]

                if "chunk" in payload:
                    queue.put_nowait(payload["chunk"])

                client_id = self.request_to_client.get(request_id, "unknown")

                if payload.get("is_finished"):
                    queue.put_nowait(None)
                    Logger.ws_receive(request_id, client_id, is_stream_end=True, total_chunks=chunk_num, data=message)
                    self._cleanup_request(request_id)
                elif chunk_num == 1:
                    Logger.ws_receive(request_id, client_id, is_stream_start=True, data=message)
                else:
                    Logger.ws_receive(request_id, client_id, is_stream_middle=True, data=message)
            return

        # 处理非流式响应
        if request_id and request_id in self.pending_responses:
            client_id = self.request_to_client.get(request_id, "unknown")
            Logger.ws_receive(request_id, client_id, data=message)
            future = self.pending_responses.pop(request_id)
            error_info = message.get("status", {}).get("error")
            if error_info:
                # 增加健壮性，处理 error_info 不是字典的情况
                if isinstance(error_info, dict):
                    code = error_info.get("code", 500)
                    detail = error_info
                else:
                    code = 500
                    detail = {"message": str(error_info)}
                
                exception = ApiException(status_code=code, detail=detail)
                future.set_exception(exception)
            else:
                future.set_result(payload)

    def get_next_client(self) -> str:
        """轮询算法，获取下一个健康的客户端ID"""
        if not self._client_ids:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No frontend clients connected",
            )
        client_id = self._client_ids[self._next_client_index]
        self._next_client_index = (self._next_client_index + 1) % len(self._client_ids)
        return client_id

    def get_all_clients(self) -> list[str]:
        """获取所有连接的客户端ID列表"""
        return list(self.active_connections.keys())

    @asynccontextmanager
    async def monitored_proxy_request(self, request_id: str, request: Request):
        """
        An async context manager to monitor and clean up a proxy request.
        It handles request registration and cancellation/cleanup upon exit.
        """
        client_id = self.get_next_client()
        self.request_to_client[request_id] = client_id
        self.client_active_requests[client_id].add(request_id)
        Logger.debug(f"注册请求 {request_id} → {client_id}")

        try:
            yield client_id
        finally:
            if await request.is_disconnected():
                Logger.event("DISCONNECT", "客户端断开连接", request_id=request_id)
                await self.cancel_request(request_id)
            else:
                # For non-streaming requests, the future is cleaned up when the response is received.
                # For streaming, it's cleaned up when the stream ends.
                # This is a fallback for unexpected exits.
                if request_id in self.pending_responses or request_id in self.streaming_responses:
                    self._cleanup_request(request_id)


    async def _direct_proxy_request(
        self,
        command_type: str,
        payload: Any,
        request_id: str,
        client_id: str,
        request: Optional[Request] = None,
        is_streaming: bool = False,
    ) -> Any:
        """
        直接代理方法：指定客户端发送命令，用于后台任务。
        不通过 monitored_proxy_request 上下文管理器。
        """
        if client_id not in self.active_connections:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Client {client_id} not connected.")

        websocket = self.active_connections[client_id]

        if isinstance(payload, BaseModel):
            payload_to_send = payload.model_dump(by_alias=True, exclude_none=True)
        else:
            payload_to_send = payload or {}

        command: dict[str, Any] = {
            "id": request_id,
            "type": command_type,
            "payload": payload_to_send,
        }

        Logger.ws_send(request_id, client_id, command_type, command=command)

        if is_streaming:
            if not request:
                raise ValueError("Streaming requests require a 'request' object.")
            return await self._handle_streaming_request(websocket, command, request_id, request)

        return await self._handle_non_streaming_request(websocket, command, request_id)

    async def proxy_request(
        self,
        command_type: str,
        payload: Any,
        request: Request,
        request_id: str,
        is_streaming: bool = False,
    ) -> Any:
        """
        核心代理方法：选择一个客户端，发送命令，并等待响应。
        对于流式请求，返回异步生成器。
        实际的注册和清理由 `monitored_proxy_request` 上下文管理器处理。
        """
        client_id = self.request_to_client[request_id]
        websocket = self.active_connections[client_id]

        if isinstance(payload, BaseModel):
            payload_to_send = payload.model_dump(by_alias=True, exclude_none=True)
        else:
            payload_to_send = payload or {}

        command: dict[str, Any] = {
            "id": request_id,
            "type": command_type,
            "payload": payload_to_send,
        }

        Logger.ws_send(request_id, client_id, command_type, command=command)

        if is_streaming:
            if not request:
                raise ValueError("Streaming requests require a 'request' object.")
            return await self._handle_streaming_request(websocket, command, request_id, request)

        return await self._handle_non_streaming_request(websocket, command, request_id)

    async def _handle_non_streaming_request(
        self, websocket: WebSocket, command: dict[str, Any], request_id: str
    ) -> Any:
        """Handles a non-streaming request."""
        future = asyncio.get_running_loop().create_future()
        self.pending_responses[request_id] = future
        try:
            await websocket.send_json(command)
            response_payload = await asyncio.wait_for(
                future, timeout=settings.WEBSOCKET_TIMEOUT
            )
            # Cleanup is handled when the response is received in `handle_message`
            return response_payload
        except asyncio.TimeoutError:
            self._cleanup_request(request_id)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request to frontend client timed out",
            )
        except ApiException as e:
            self._cleanup_request(request_id)
            # 在这里实现全局重置逻辑
            error_detail = e.detail or {}
            error_message = error_detail.get("message", "").lower()

            # 检查是否是文件未找到的特定错误
            if "not found" in error_message or "file not found" in error_message:
                # 尝试从命令的 payload 中找到 file_name
                file_name = command.get("payload", {}).get("fileName")
                if file_name:
                    sha256 = file_manager.get_sha256_by_filename(file_name)
                    if sha256:
                        Logger.warning("检测到文件过期/未找到，触发全局重置", file_name=file_name, sha256=sha256)
                        file_manager.reset_replication_map(sha256)
                        # 标记异常，以便上层进行同步重建
                        e.is_resettable = True

            # 重新抛出更详细的HTTP异常
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        except Exception as e:
            self._cleanup_request(request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error communicating with frontend client: {str(e)}",
            )

    async def handle_api_request(
        self,
        *,
        command_type: str,
        payload: Any,
        request: Optional[Request] = None,
        is_streaming: bool = False,
    ) -> Any:
        """
        处理API请求的包装方法，向后兼容原有代码

        Args:
            command_type: 命令类型
            payload: 负载数据
            request: HTTP请求对象
            is_streaming: 是否为流式请求

        Returns:
            响应数据
        """
        request_id = str(uuid.uuid4())

        async with self.monitored_proxy_request(request_id, request):
            try:
                return await self.proxy_request(
                    command_type=command_type,
                    payload=payload,
                    request=request,
                    request_id=request_id,
                    is_streaming=is_streaming,
                )
            except HTTPException as e:
                raise e

    async def _handle_streaming_request(
        self,
        websocket: WebSocket,
        command: dict[str, Any],
        request_id: str,
        request: Request,
    ) -> AsyncGenerator[Any, None]:
        """Handles a streaming request and returns an async generator."""
        queue: asyncio.Queue = asyncio.Queue()
        self.streaming_responses[request_id] = queue

        async def stream_generator() -> AsyncGenerator[Any, None]:
            try:
                await websocket.send_json(command)
                while True:
                    # Check for disconnect before waiting for the next item
                    if await request.is_disconnected():
                        Logger.event("DISCONNECT", "流式传输中断", request_id=request_id)
                        # No need to call cancel_request here, the context manager will handle it
                        break

                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Timeout allows us to re-check the disconnect status
                        continue

                    if item is None:  # End of stream signal
                        break
                    yield item
            finally:
                # The context manager will ultimately handle the final cleanup
                pass

        return stream_generator()

    async def cancel_request(self, request_id: str) -> bool:
        """
        取消指定的请求（唯一入口点）

        职责：
        1. 检查请��是否存在
        2. 发送取消信号给前端
        3. 清理后端资源

        Args:
            request_id: 要取消的请求ID

        Returns:
            bool: 取消操作是否成功启动
        """
        Logger.debug(f"尝试取消请求 {request_id}")

        # 步骤 1：幂等性检查
        if request_id not in self.request_to_client:
            Logger.debug(f"请求 {request_id} 未找到或已取消")
            return False

        # 步骤 2：获取处理该请求的客户端
        client_id = self.request_to_client[request_id]

        # 步骤 3：发送取消信号（best effort）
        cancel_signal_sent = False
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            cancel_message = {
                "type": "cancel_task",
                "id": request_id
            }
            try:
                await websocket.send_json(cancel_message)
                Logger.event("CANCEL", "发送取消信号", request_id=request_id, client_id=client_id)
                cancel_signal_sent = True
            except Exception as e:
                Logger.error("发送取消信号失���", exc=e, request_id=request_id, client_id=client_id)
                # 即使发送失败，也要继续清理后端资源
        else:
            Logger.warning("客户端未连接，无法发送取消信号", client_id=client_id)

        # 步骤 4：清理后端资源（必须执行）
        self._cleanup_request(request_id)

        return True

    def _cleanup_request(self, request_id: str):
        """
        清理与请求相关的所有内部资源（内部方法）

        注意：此方法是幂等的，可以安全地多次调用
        """
        cleaned_items = []

        # 清理 1：流式响应队列
        if request_id in self.streaming_responses:
            queue = self.streaming_responses.pop(request_id)
            # 确保队列中的等待者被释放
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
            cleaned_items.append("queue")

        # 清理 2：请求映射关系
        if request_id in self.request_to_client:
            client_id = self.request_to_client.pop(request_id)
            if client_id in self.client_active_requests:
                self.client_active_requests[client_id].discard(request_id)
            cleaned_items.append("mapping")

        # 清理 3：非流式响应的 Future
        if request_id in self.pending_responses:
            future = self.pending_responses.pop(request_id)
            if not future.done():
                future.cancel()
            cleaned_items.append("future")

        # 清理 4：流式包计数
        if request_id in self.streaming_chunk_count:
            self.streaming_chunk_count.pop(request_id)
            cleaned_items.append("chunk_count")

        if cleaned_items:
            Logger.debug(f"清理资源 {request_id} | {', '.join(cleaned_items)}")



    def trigger_async_replication(self, sha256: str, client_id: str):
        """触发一个后台任务来异步复制文件"""
        create_background_task(self._replicate_file_task(sha256, client_id))

    async def _replicate_file_task(self, sha256: str, client_id: str):
        """异步复制文件的实际后台任务"""
        request_id = f"replication-{sha256[:8]}-{client_id}"
        Logger.event("REPLICATION_START", "开始异步文件复制", sha256=sha256, client_id=client_id)

        entry = file_manager.get_metadata_entry(sha256)
        if not entry:
            Logger.warning("异��复制失败：找不到文件元数据", sha256=sha256)
            return

        # 简单的令牌机制，未来可以增强
        token = "placeholder_token"
        download_url = f"{settings.PROXY_BASE_URL}/files/internal/{sha256}/{token}:download"

        try:
            # 创建一个虚拟的 Request 对象，因为这是后台任务
            from unittest.mock import Mock
            mock_request = Mock()
            mock_request.is_disconnected = asyncio.coroutine(lambda: False)

            # 指挥客户端上传
            response_payload = await self._direct_proxy_request(
                command_type="upload_from_url",
                payload={
                    "download_url": download_url,
                    "file_metadata": {
                        "name": entry.original_filename,
                        "displayName": entry.original_filename,
                        "mimeType": entry.mime_type,
                    },
                },
                request_id=request_id,
                client_id=client_id,
                request=mock_request,
            )
            gemini_file = response_payload.get("file")
            if not gemini_file:
                raise ApiException(status_code=500, detail="Frontend did not return a file object.")

            # 更新元数据
            file_manager.update_replication_status(
                sha256, client_id, "synced", gemini_file
            )
            Logger.event("REPLICATION_SUCCESS", "异步文件复制成功", sha256=sha256, client_id=client_id)

        except Exception as e:
            file_manager.update_replication_status(sha256, client_id, "failed")
            Logger.error("异步文件复制失败", exc=e, sha256=sha256, client_id=client_id)

    async def _synchronously_rebuild_file(self, sha256: str) -> tuple[dict, str]:
        """
        同步重建文件：轮询选择一个客户端，阻塞式地指挥它重新上传文件。
        """
        request_id = f"rebuild-{sha256[:8]}-{uuid.uuid4()}"
        Logger.event("REBUILD_START", "开始同步文件重建", sha256=sha256)

        entry = file_manager.get_metadata_entry(sha256)
        if not entry:
            raise ValueError(f"Cannot rebuild file: metadata not found for sha256 {sha256}")

        client_id = self.get_next_client()

        token = "placeholder_token"
        download_url = f"{settings.PROXY_BASE_URL}/files/internal/{sha256}/{token}:download"

        try:
            # 创建一个虚拟的 Request 对象，因为这是后台任务
            from unittest.mock import Mock
            mock_request = Mock()
            mock_request.is_disconnected = asyncio.coroutine(lambda: False)

            response_payload = await self._direct_proxy_request(
                command_type="upload_from_url",
                payload={
                    "download_url": download_url,
                    "file_metadata": {
                        "name": entry.original_filename,
                        "displayName": entry.original_filename,
                        "mimeType": entry.mime_type,
                    },
                },
                request_id=request_id,
                client_id=client_id,
                request=mock_request,
            )
            gemini_file = response_payload.get("file")
            if not gemini_file:
                raise ApiException(status_code=500, detail="Frontend did not return a file object during rebuild.")

            file_manager.update_replication_status(sha256, client_id, "synced", gemini_file)
            Logger.event("REBUILD_SUCCESS", "同步文件重建成功", sha256=sha256, client_id=client_id)
            return gemini_file, client_id

        except Exception as e:
            file_manager.update_replication_status(sha256, client_id, "failed")
            Logger.error("同步文件重建失败", exc=e, sha256=sha256, client_id=client_id)
            raise  # 将异常向上抛出

    def trigger_delete_task(self, client_id: str, file_name: str):
        """触发一个后台任务来异步删除远程文件"""
        create_background_task(self._delete_file_task(client_id, file_name))

    async def _delete_file_task(self, client_id: str, file_name: str):
        """异步删除远程文件的实际后台任务"""
        request_id = f"delete-{file_name.replace('/', '-')}"
        Logger.event("DELETE_START", "开始异步远程文件删除", client_id=client_id, file_name=file_name)
        try:
            # 创建一个虚拟的 Request 对象，因为这是后台任务
            from unittest.mock import Mock
            mock_request = Mock()
            mock_request.is_disconnected = asyncio.coroutine(lambda: False)

            await self._direct_proxy_request(
                command_type="delete_file",
                payload={"file_name": file_name},
                request_id=request_id,
                client_id=client_id,
                request=mock_request,
            )
            Logger.event("DELETE_SUCCESS", "异步远程文件删除成功", client_id=client_id, file_name=file_name)
        except Exception as e:
            # 忽略错误，因为最终文件会被 TTL 清理
            Logger.warning("异步远程文件删除失败", exc=e, client_id=client_id, file_name=file_name)

    async def handle_api_request(
        self,
        *,
        command_type: str,
        payload: Any,
        request: Optional[Request] = None,
        is_streaming: bool = False,
    ) -> Any:
        """
        处理API请求的包装方法，向后兼容原有代码

        Args:
            command_type: 命令类型
            payload: 负��数据
            request: HTTP请求对象
            is_streaming: 是否为流式请求

        Returns:
            响应数据
        """
        request_id = str(uuid.uuid4())

        async with self.monitored_proxy_request(request_id, request) as client_id:
            try:
                return await self.proxy_request(
                    command_type=command_type,
                    payload=payload,
                    request=request,
                    request_id=request_id,
                    is_streaming=is_streaming,
                )
            except HTTPException as e:
                raise e


manager = ConnectionManager()
