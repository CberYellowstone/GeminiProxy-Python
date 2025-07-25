import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException, WebSocket, status
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        # 用于追踪请求和响应的字典
        self.pending_responses: dict[str, asyncio.Future] = {}
        # 用于轮询的客户端 ID 列表和索引
        self._client_ids: list[str] = []
        self._next_client_index: int = 0
        logging.info("ConnectionManager initialized.")

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self._client_ids.append(client_id)
        logging.info(f"Client connected: {client_id}. Total clients: {len(self.active_connections)}")

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self._client_ids:
            self._client_ids.remove(client_id)
        logging.info(f"Client disconnected: {client_id}. Total clients: {len(self.active_connections)}")

    async def handle_message(self, message: dict[str, Any]):
        """处理从前端收到的响应消息"""
        request_id = message.get("id")
        if request_id and request_id in self.pending_responses:
            future = self.pending_responses.pop(request_id)
            future.set_result(message.get("payload"))
            logging.info(f"Response received for request_id: {request_id}")

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

    async def proxy_request(self, command_type: str, payload: Any) -> Any:
        """
        核心代理方法：选择客户端，发送指令，并等待响应。
        """
        client_id = self.get_next_client()
        websocket = self.active_connections[client_id]

        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending_responses[request_id] = future

        # 如果 payload 是 Pydantic 模型，则序列化为字典
        if isinstance(payload, BaseModel):
            payload_to_send = payload.model_dump(by_alias=True, exclude_none=True)
        else:
            payload_to_send = payload or {}

        command: dict[str, Any] = {
            "id": request_id,
            "type": command_type,
            "payload": payload_to_send,
        }

        try:
            logging.info(f"Sending command to {client_id}: {command}")
            await websocket.send_json(command)
            # 等待响应，设置超时
            response_payload = await asyncio.wait_for(future, timeout=30.0)
            return response_payload
        except asyncio.TimeoutError:
            logging.error(f"Request timeout for request_id: {request_id}")
            self.pending_responses.pop(request_id, None)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request to frontend client timed out",
            )
        except Exception as e:
            logging.error(f"An error occurred for request_id {request_id}: {e}")
            self.pending_responses.pop(request_id, None)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Error communicating with frontend client",
            )


# 创建单例
manager = ConnectionManager()
