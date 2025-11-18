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
        self.streaming_chunk_count: dict[str, int] = {}

        self._client_ids: list[str] = []
        self._next_client_index: int = 0

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self._client_ids.append(client_id)

    async def disconnect(self, client_id: str):
        """断开客户端连接"""
        # TODO: 在方案B中，我们可能需要在这里触发对该客户端相关文件的状态更新
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self._client_ids:
            self._client_ids.remove(client_id)
        Logger.event("DISCONNECT", "客户端断开连接", client_id=client_id)


    async def handle_message(self, message: dict[str, Any]):
        """处理从前端收到的响应消息"""
        payload = message.get("payload", {})
        request_id = message.get("id")
        client_id = message.get("client_id", "unknown") # 假设响应中会包含client_id

        if request_id:
            is_finished = payload.get("is_finished", "N/A")
            Logger.debug(f"接收消息 {request_id} | 完成: {is_finished}")

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
    async def monitored_proxy_request(self, request_id: str, request: Request, client_id: str):
        """
        一个简化的上下文管理器，用于监控API请求的生命周期并确保清理。
        """
        try:
            yield
        finally:
            # 核心清理逻辑现在由请求处理函数负责
            # 这个管理器主要确保在请求意外断开时，能有一个记录
            if await request.is_disconnected():
                Logger.event("DISCONNECT", "API客户端在请求处理中断开连接", request_id=request_id)


    async def proxy_request(
        self,
        *,
        command_type: str,
        payload: Any,
        request_id: str,
        client_id: str,
        is_streaming: bool = False,
        request: Optional[Request] = None,
    ) -> Any:
        """
        核心代理方法：向指定的客户端发送命令，并等待响应。
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

    def _cleanup_request(self, request_id: str):
        """清理与请求相关的所有内部资源"""
        self.pending_responses.pop(request_id, None)
        self.streaming_responses.pop(request_id, None)
        self.streaming_chunk_count.pop(request_id, None)
        Logger.debug(f"清理请求资源 {request_id}")

    # ========================================================================
    # 方案 B: 核心请求处理流程
    # ========================================================================

    async def handle_api_request(self, *, command_type: str, payload: Any, is_streaming: bool, request: Request):
        """
        处理 API 请求的统一入口 (方案 B)。
        集成了文件查找、客户端选择、回退、复制和容错逻辑。
        """
        request_id = str(uuid.uuid4())
        
        # 注意：这个解析逻辑非常脆弱，仅用于演示。生产代码需要更健壮的解析器。
        original_file_name = None
        try:
            original_file_name = payload["payload"]["contents"][0]["fileData"]["fileName"]
        except (KeyError, IndexError):
            pass

        client_id = self.get_next_client()  # 默认轮询
        effective_payload = payload

        if original_file_name:
            sha256 = file_manager.get_sha256_by_filename(original_file_name)
            if sha256:
                entry = file_manager.get_metadata_entry(sha256)
                if entry:
                    # a. 检查轮询选中的客户端是否就绪
                    if client_id in entry.replication_map and entry.replication_map[client_id].get("status") == "synced":
                        pass  # 完美命中，直接使用
                    else:
                        # b. 未命中，执行即时回退
                        found_synced = False
                        for cid, data in entry.replication_map.items():
                            if data.get("status") == "synced" and cid in self.active_connections:
                                Logger.debug(f"即时回退: {client_id} -> {cid}", request_id=request_id)
                                self.trigger_async_replication(sha256, client_id)
                                client_id = cid  # 切换到已同步的客户端
                                found_synced = True
                                break

                        if not found_synced:
                            # c. 没有找到任何已同步的客户端，执行同步重建
                            Logger.warning("找不到任何已同步的客户端，执行同步重建", sha256=sha256, request_id=request_id)
                            try:
                                new_file, new_client_id = await self._synchronously_rebuild_file(sha256)
                                client_id = new_client_id
                                # 更新 payload 以使用新的文件名
                                payload["payload"]["contents"][0]["fileData"]["fileName"] = new_file["name"]
                            except Exception as rebuild_exc:
                                Logger.error("同步重建失败", exc=rebuild_exc, sha256=sha256)
                                raise ApiException(
                                    status_code=503, detail="No available client has the required file, and rebuild failed."
                                )

                    # d. 改写 payload
                    final_file_name = entry.replication_map[client_id].get("name")
                    effective_payload["payload"]["contents"][0]["fileData"]["fileName"] = final_file_name

        # 实际执行请求
        try:
            async with self.monitored_proxy_request(request_id, request, client_id):
                return await self.proxy_request(
                    command_type=command_type,
                    payload=effective_payload,
                    request_id=request_id,
                    client_id=client_id,
                    is_streaming=is_streaming,
                    request=request,
                )
        except ApiException as e:
            if sha256_to_reset := getattr(e, "sha256_to_reset", None):
                Logger.error("捕获到可重置的文件错误，将尝试同步重建", request_id=request_id, sha256=sha256_to_reset)
                try:
                    # 1. 同步重建
                    new_file, new_client_id = await self._synchronously_rebuild_file(sha256_to_reset)

                    # 2. 更新 payload
                    effective_payload["payload"]["contents"][0]["fileData"]["fileName"] = new_file["name"]

                    # 3. 使用新的客户端和 payload 重试请求
                    Logger.event("RETRY_REQUEST", "使用重建的文件重试请求", request_id=request_id)
                    async with self.monitored_proxy_request(request_id, request, new_client_id):
                        return await self.proxy_request(
                            command_type=command_type,
                            payload=effective_payload,
                            request_id=request_id,
                            client_id=new_client_id,
                            is_streaming=is_streaming,
                            request=request,
                        )
                except Exception as rebuild_exc:
                    Logger.error("重试请求在同步重建后失败", exc=rebuild_exc, request_id=request_id)
                    raise HTTPException(status_code=500, detail=f"File expired, and reconstruction failed: {rebuild_exc}")
            raise


    def trigger_async_replication(self, sha256: str, client_id: str):
        """触发一个后台任务来异步复制文件"""
        create_background_task(self._replicate_file_task(sha256, client_id))

    async def _replicate_file_task(self, sha256: str, client_id: str):
        """异步复制文件的实际后台任务"""
        request_id = f"replication-{sha256[:8]}-{client_id}"
        Logger.event("REPLICATION_START", "开始异步文件复制", sha256=sha256, client_id=client_id)

        entry = file_manager.get_metadata_entry(sha256)
        if not entry:
            Logger.warning("异步复制失败：找不到文件元数据", sha256=sha256)
            return

        # 简单的令牌机制，未来可以增强
        token = "placeholder_token"
        download_url = f"{settings.PROXY_BASE_URL}/files/internal/{sha256}/{token}:download"

        try:
            # 指挥客户端上传
            response_payload = await self.proxy_request(
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
            response_payload = await self.proxy_request(
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
            await self.proxy_request(
                command_type="delete_file",
                payload={"file_name": file_name},
                request_id=request_id,
                client_id=client_id,
            )
            Logger.event("DELETE_SUCCESS", "异步远程文件删除成功", client_id=client_id, file_name=file_name)
        except Exception as e:
            # 忽略错误，因为最终文件会被 TTL 清理
            Logger.warning("异步远程文件删除失败", exc=e, client_id=client_id, file_name=file_name)


manager = ConnectionManager()
