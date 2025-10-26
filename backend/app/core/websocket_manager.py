import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator

from app.core.exceptions import ApiException
from fastapi import HTTPException, WebSocket, status
from pydantic import BaseModel


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        # 用于追踪请求和响应的字典
        self.pending_responses: dict[str, asyncio.Future] = {}
        # 新增：用于处理流式响应的队列
        self.streaming_responses: dict[str, asyncio.Queue] = {}
        # 用于轮询的客户端 ID 列表和索引
        self._client_ids: list[str] = []
        self._next_client_index: int = 0

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self._client_ids.append(client_id)

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self._client_ids:
            self._client_ids.remove(client_id)

    async def handle_message(self, message: dict[str, Any]):
        """处理从前端收到的响应消息"""
        logging.info(f"Received WebSocket message from client: {message}")
        request_id = message.get("id")
        payload = message.get("payload", {})

        # 检查是否为流式响应
        if request_id in self.streaming_responses:
            queue = self.streaming_responses[request_id]
            if payload.get("is_streaming"):
                # 只有当 chunk 存在时才放入队列
                if "chunk" in payload:
                    queue.put_nowait(payload["chunk"])
                # 当流结束时，发送 None 信号
                if payload.get("is_finished"):
                    queue.put_nowait(None)  # 发送流结束信号
                    del self.streaming_responses[request_id]
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

        # 简单的轮询
        client_id = self._client_ids[self._next_client_index]
        self._next_client_index = (self._next_client_index + 1) % len(self._client_ids)
        return client_id

    def get_all_clients(self) -> list[str]:
        """获取所有连接的客户端ID列表"""
        return list(self.active_connections.keys())

    async def proxy_request(self, command_type: str, payload: Any, is_streaming: bool = False) -> Any:
        """
        核心代理方法：选择客户端，发送指令，并等待响应。
        对于流式请求，返回一个异步生成器。
        """
        client_id = self.get_next_client()
        websocket = self.active_connections[client_id]
        request_id = str(uuid.uuid4())

        if isinstance(payload, BaseModel):
            payload_to_send = payload.model_dump(by_alias=True, exclude_none=True)
        else:
            payload_to_send = payload or {}

        command: dict[str, Any] = {
            "id": request_id,
            "type": command_type,
            "payload": payload_to_send,
        }
        logging.info(f"Sending WebSocket message to client: {command}")

        # 处理流式请求
        if is_streaming:
            queue: asyncio.Queue = asyncio.Queue()
            self.streaming_responses[request_id] = queue

            async def stream_generator() -> AsyncGenerator[Any, None]:
                try:
                    await websocket.send_json(command)
                    while True:
                        item = await queue.get()
                        if item is None:
                            break
                        yield item
                finally:
                    # 确保队列被清理
                    self.streaming_responses.pop(request_id, None)

            return stream_generator()

        # 处理非流式请求 (现有逻辑)
        future = asyncio.get_running_loop().create_future()
        self.pending_responses[request_id] = future

        try:
            await websocket.send_json(command)
            response_payload = await asyncio.wait_for(future, timeout=30.0)
            return response_payload
        except asyncio.TimeoutError:
            self.pending_responses.pop(request_id, None)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request to frontend client timed out",
            )
        except ApiException as e:
            raise e
        except Exception:
            self.pending_responses.pop(request_id, None)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error communicating with frontend client",
            )


# 创建单例
manager = ConnectionManager()
