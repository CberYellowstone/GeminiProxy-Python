import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings
from app.core.exceptions import ApiException
from fastapi import HTTPException, Request, WebSocket, status
from pydantic import BaseModel
from rich.markup import escape


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.pending_responses: dict[str, asyncio.Future] = {}
        self.streaming_responses: dict[str, asyncio.Queue] = {}
        
        # 新增：追踪 request_id 到 client_id 的映射
        self.request_to_client: dict[str, str] = {}
        
        # 新增：追踪每个 client 正在处理的请求集合
        self.client_active_requests: dict[str, set[str]] = {}
        
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
            logging.info(f"[DISCONNECT] Cancelling {len(request_ids)} requests for client {client_id}")
            
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
            logging.debug(f"DEBUG: Received message for request {request_id}. Is finished: {is_finished}.")
        
        # 检查是否为流式响应
        if request_id in self.streaming_responses:
            queue = self.streaming_responses[request_id]
            if payload.get("is_streaming"):
                if "chunk" in payload:
                    queue.put_nowait(payload["chunk"])
                if payload.get("is_finished"):
                    queue.put_nowait(None)
                    self._cleanup_request(request_id)  # 正常完成时清理
            return
        
        # 处理非流式响应
        if request_id and request_id in self.pending_responses:
            future = self.pending_responses.pop(request_id)
            if message.get("status", {}).get("error"):
                code = message["status"].get("code")
                error_payload = message["status"].get("errorPayload")
                exception = ApiException(status_code=code, detail=error_payload)
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
        logging.debug(f"Registered request {request_id} for client {client_id}")
        
        try:
            yield
        finally:
            if await request.is_disconnected():
                logging.info(f"[DISCONNECT] Client disconnected for {request_id}")
                await self.cancel_request(request_id)
            else:
                # For non-streaming requests, the future is cleaned up when the response is received.
                # For streaming, it's cleaned up when the stream ends.
                # This is a fallback for unexpected exits.
                if request_id in self.pending_responses or request_id in self.streaming_responses:
                    self._cleanup_request(request_id)

    async def proxy_request(
        self,
        command_type: str,
        payload: Any,
        request: Request,
        request_id: str,
        is_streaming: bool = False,
    ) -> Any:
        """
        Core proxy method: selects a client, sends a command, and awaits a response.
        For streaming requests, it returns an async generator.
        The actual registration and cleanup are handled by the `monitored_proxy_request` context manager.
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
        
        logging.info(
            f"[bold]Sending request[/bold] [bold cyan]{request_id}[/bold cyan] "
            f"[bold]to client[/bold] [bold cyan]{client_id}[/bold cyan]. "
            f"Payload: [grey50]{escape(str(command))}[/grey50]"
        )

        if is_streaming:
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
            raise e
        except Exception as e:
            self._cleanup_request(request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error communicating with frontend client: {str(e)}",
            )

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
                        logging.info(f"[DISCONNECT] Client disconnected during stream for {request_id}")
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
        1. 检查请求是否存在
        2. 发送取消信号给前端
        3. 清理后端资源
        
        Args:
            request_id: 要取消的请求ID
            
        Returns:
            bool: 取消操作是否成功启动
        """
        logging.debug(f"[CANCEL] Attempting to cancel request {request_id}")
        
        # 步骤 1：幂等性检查
        if request_id not in self.request_to_client:
            logging.debug(f"[CANCEL] Request {request_id} not found or already cancelled")
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
                logging.info(f"[CANCEL] Sent cancel signal for {request_id} to {client_id}")
                cancel_signal_sent = True
            except Exception as e:
                logging.error(f"[CANCEL] Failed to send cancel signal: {e}")
                # 即使发送失败，也要继续清理后端资源
        else:
            logging.warning(f"[CANCEL] Client {client_id} not connected, cannot send signal")
        
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
        
        if cleaned_items:
            logging.debug(f"[CLEANUP] Cleaned {', '.join(cleaned_items)} for {request_id}")


manager = ConnectionManager()