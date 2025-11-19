import asyncio
import base64
import logging
import random
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Optional
from types import SimpleNamespace

from app.core.background_tasks import create_background_task
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import FileCacheEntry, file_manager
from app.core.log_utils import Logger
from app.core.mime_utils import MimeUtils
from fastapi import HTTPException, Request, WebSocket, status
from pydantic import BaseModel


@dataclass
class FileReference:
    """指向 payload 中一个 fileData 节点的引用"""

    sha256: str
    entry: FileCacheEntry
    file_dict: dict


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.pending_responses: dict[str, asyncio.Future] = {}
        self.streaming_responses: dict[str, asyncio.Queue] = {}
        self.streaming_chunk_count: dict[str, int] = {}

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

    async def _get_file_mime_type(self, file_name: str, request_id: str) -> Optional[str]:
        """
        获取文件的正确 MIME 类型

        Args:
            file_name: 文件名
            request_id: 请求ID

        Returns:
            正确的 MIME 类型，如果无法获取则返回 None
        """
        try:
            # 查找文件的 SHA256
            sha256 = file_manager.get_sha256_by_filename(file_name)
            if not sha256:
                return None

            entry = file_manager.get_metadata_entry(sha256)
            if not entry:
                return None

            # 检查是否有完整的文件数据包含 MIME 类型
            for data in entry.replication_map.values():
                if data.get("name") == file_name and "mimeType" in data:
                    return data.get("mimeType")

            # 如果没有找到，尝试根据文件名推断
            return MimeUtils.infer_mime_type(file_name)

        except Exception as e:
            Logger.warning(f"获取文件 MIME 类型失败: {e}", file_name=file_name, request_id=request_id)
            return None

    async def _fix_payload_mime_types(self, payload: dict, request_id: str) -> dict:
        """
        修正 payload 中的 MIME 类型

        Args:
            payload: 原始 payload
            request_id: 请求ID

        Returns:
            修正后的 payload
        """
        if not isinstance(payload, dict) or "payload" not in payload:
            return payload

        contents = payload["payload"].get("contents", [])
        if not isinstance(contents, list):
            return payload

        fixed_contents = []
        for content in contents:
            if not isinstance(content, dict):
                fixed_contents.append(content)
                continue

            file_data = content.get("file_data") or content.get("fileData", {})
            if isinstance(file_data, dict) and "mime_type" in file_data:
                original_mime = file_data["mime_type"]
                file_name = file_data.get("fileName", "")

                # 如果没有 fileName，尝试从 fileUri 推断
                if not file_name:
                    file_uri = file_data.get("fileUri", "")
                    if file_uri:
                        sha256_from_uri = file_uri.split('/')[-1] if '/' in file_uri else file_uri
                        # 从文件管理器中查找原始文件名
                        cached_entry = file_manager.get_metadata_entry(sha256_from_uri)
                        if cached_entry and cached_entry.original_filename:
                            file_name = cached_entry.original_filename

                # 检查是否需要修正 MIME 类型
                if MimeUtils.should_correct_mime_type(original_mime, file_name):
                    # 尝试获取正确的 MIME 类型
                    corrected_mime = await self._get_file_mime_type(file_name, request_id)
                    if not corrected_mime:
                        # 如果无法获取，使用智能推断
                        corrected_mime = MimeUtils.infer_mime_type(file_name)

                    if corrected_mime != original_mime:
                        Logger.info(f"生成阶段 MIME 类型修正: {original_mime} -> {corrected_mime}",
                                  file_name=file_name, request_id=request_id)
                        # 创建副本以避免修改原始数据
                        new_content = content.copy()
                        new_file_data = file_data.copy()
                        new_file_data["mime_type"] = corrected_mime
                        if "fileData" in content:
                            new_content["fileData"] = new_file_data
                        else:
                            new_content["file_data"] = new_file_data
                        fixed_contents.append(new_content)
                        continue

            fixed_contents.append(content)

        # 如果有修改，返回新的 payload
        if len(fixed_contents) != len(contents):
            new_payload = payload.copy()
            new_payload["payload"] = payload["payload"].copy()
            new_payload["payload"]["contents"] = fixed_contents
            return new_payload

        return payload

    def _get_nested_value(self, data: dict, path: str) -> Optional[Any]:
        """
        从嵌套字典中获取值

        Args:
            data: 要搜索的字典
            path: 点分隔的路径，如 "fileData.fileName"

        Returns:
            找到的值，如果未找到则返回 None
        """
        keys = path.split('.')
        current = data
        try:
            for key in keys:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    return None
            return current
        except (KeyError, TypeError):
            return None

    async def handle_api_request(
        self,
        *,
        command_type: str,
        payload: Any,
        request: Optional[Request] = None,
        is_streaming: bool = False,
    ) -> Any:
        """
        处理 API 请求的统一入口 (方案 B)。
        集成了文件查找、客户端选择、回退、复制和容错逻辑。
        """
        request_id = str(uuid.uuid4())

        # 对于 generateContent 命令，首先修正 MIME 类型
        if command_type == "generateContent" or command_type == "streamGenerateContent":
            effective_payload = await self._fix_payload_mime_types(payload, request_id)
        else:
            effective_payload = payload

        # 注意：这个解析逻辑非常脆弱，仅用于演示。生产代码需要更健壮的解析器。
        original_file_name = None  # 仅用于日志展示

        # 调试：记录 payload 结构
        Logger.info(f"[调试] 原始 payload 结构: {payload}", request_id=request_id)
        Logger.info(f"[调试] 有效 payload 结构: {effective_payload}", request_id=request_id)

        # 尝试多种可能的文件名路径
        try:
            if isinstance(effective_payload, dict):
                if "payload" in effective_payload:
                    payload_contents = effective_payload["payload"]
                    if isinstance(payload_contents, dict) and "contents" in payload_contents:
                        contents = payload_contents["contents"]
                        if isinstance(contents, list) and len(contents) > 0:
                            content = contents[0]
                            if isinstance(content, dict):
                                # 检查可能的文件名位置
                                file_name = None
                                for path in ["fileData.fileName", "file_data.fileName"]:
                                    file_name = self._get_nested_value(content, path)
                                    if file_name:
                                        original_file_name = file_name
                                        Logger.info(f"[调试] 找到文件名: {file_name} (路径: {path})", request_id=request_id)
                                        break

                                # 如果没有找到 fileName，遍历 parts 查找 fileData
                                if not original_file_name:
                                    parts = content.get("parts", [])
                                    if isinstance(parts, list):
                                        for part in parts:
                                            if isinstance(part, dict):
                                                file_data = part.get("fileData") or part.get("file_data")
                                                if isinstance(file_data, dict):
                                                    file_uri = file_data.get("fileUri") or file_data.get("file_uri")
                                                    if file_uri and isinstance(file_uri, str):
                                                        # 使用 file_uri (即 file.name) 来查找完整的 SHA256
                                                        full_sha256 = file_manager.get_sha256_by_filename(file_uri)
                                                        if full_sha256:
                                                            cached_entry = file_manager.get_metadata_entry(full_sha256)
                                                            if cached_entry and cached_entry.original_filename:
                                                                original_file_name = cached_entry.original_filename
                                                                Logger.info(
                                                                    f"[调试] 从 fileUri '{file_uri}' 找到文件名: {original_file_name}",
                                                                    request_id=request_id,
                                                                )
                                                                break  # 找到后跳出 parts 循环
                                    if not original_file_name:
                                        Logger.warning(f"[调试] 无法从 payload 中提取有效的文件名或 fileUri", request_id=request_id)
                else:
                    # 直接检查顶层
                    for path in ["fileData.fileName", "file_data.fileName", "fileName"]:
                        file_name = self._get_nested_value(effective_payload, path)
                        if file_name:
                            original_file_name = file_name
                            Logger.info(f"[调试] 找到文件名: {file_name} (路径: {path})", request_id=request_id)
                            break

            Logger.info(f"[调试] 解析出的文件名: {original_file_name}", request_id=request_id)

        except Exception as e:
            Logger.warning(f"解析文件名时出错: {e}", request_id=request_id)

        client_id = self.get_next_client()  # 默认轮询

        file_refs: list[FileReference] = []
        try:
            file_refs = self._extract_file_references(effective_payload, request_id)
        except HTTPException:
            raise
        except Exception as exc:
            Logger.warning("遍历 payload 文件引用失败", exc=exc, request_id=request_id)

        if file_refs:
            required_entries = {ref.sha256: ref.entry for ref in file_refs}
            missing_for_initial = self._collect_missing_for_client(required_entries, client_id)

            if missing_for_initial:
                best_client_id, missing_for_best, initial_missing = self._select_best_client(
                    required_entries, client_id
                )

                if missing_for_best:
                    await self._replicate_files_to_client(best_client_id, missing_for_best, request_id)

                if best_client_id != client_id and initial_missing:
                    self.trigger_bulk_replication(client_id, initial_missing)

                client_id = best_client_id

            self._rewrite_file_references(file_refs, client_id, request_id)

        # 实际执行请求
        try:
            # 为方案 B 修改 monitored_proxy_request 调用
            self.request_to_client[request_id] = client_id
            if client_id not in self.client_active_requests:
                self.client_active_requests[client_id] = set()
            self.client_active_requests[client_id].add(request_id)

            try:
                return await self.proxy_request(
                    command_type=command_type,
                    payload=effective_payload,
                    request=request,
                    request_id=request_id,
                    is_streaming=is_streaming,
                )
            finally:
                # 清理请求映射
                self.request_to_client.pop(request_id, None)
                if client_id in self.client_active_requests:
                    self.client_active_requests[client_id].discard(request_id)
        except Exception as e:
            # 检查是否有可重置的错误
            if hasattr(e, 'is_resettable') and getattr(e, 'is_resettable', False):
                sha256_to_reset = None
                if original_file_name:
                    sha256_to_reset = file_manager.get_sha256_by_filename(original_file_name)

                if sha256_to_reset:
                    Logger.error("捕获到可重置的文件错误，将尝试同步重建", request_id=request_id, sha256=sha256_to_reset)
                    try:
                        # 1. 同步重建
                        new_file, new_client_id = await self._synchronously_rebuild_file(sha256_to_reset)

                        # 2. 更新 payload
                        if isinstance(payload, dict) and "payload" in payload and "contents" in payload["payload"]:
                            payload["payload"]["contents"][0]["fileData"]["fileName"] = new_file["name"]

                        # 3. 使用新的客户端和 payload 重试请求
                        Logger.event("RETRY_REQUEST", "使用重建的文件重试请求", request_id=request_id)

                        # 设置新的请求映射
                        self.request_to_client[request_id] = new_client_id
                        if new_client_id not in self.client_active_requests:
                            self.client_active_requests[new_client_id] = set()
                        self.client_active_requests[new_client_id].add(request_id)

                        try:
                            return await self.proxy_request(
                                command_type=command_type,
                                payload=payload,
                                request=request,
                                request_id=request_id,
                                is_streaming=is_streaming,
                            )
                        finally:
                            # 清理请求映射
                            self.request_to_client.pop(request_id, None)
                            if new_client_id in self.client_active_requests:
                                self.client_active_requests[new_client_id].discard(request_id)
                    except Exception as rebuild_exc:
                        Logger.error("重试请求在同步重建后失败", exc=rebuild_exc, request_id=request_id)
                        raise HTTPException(status_code=500, detail=f"File expired, and reconstruction failed: {rebuild_exc}")
            raise

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
        1. 检查请求是否存在
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
                Logger.error("发送取消信号失败", exc=e, request_id=request_id, client_id=client_id)
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

    # ========================================================================
    # 文件调度辅助方法
    # ========================================================================

    def _build_background_request(self) -> SimpleNamespace:
        async def _always_connected():
            return False

        return SimpleNamespace(is_disconnected=_always_connected)

    def _resolve_sha_from_file_dict(self, file_dict: dict) -> Optional[str]:
        for key in ("fileUri", "file_uri", "fileName", "file_name"):
            value = file_dict.get(key)
            if not value:
                continue
            sha256 = file_manager.get_sha256_by_filename(value)
            if sha256:
                return sha256
        return None

    def _extract_file_references(self, payload: Any, request_id: str) -> list[FileReference]:
        """遍历 payload，收集所有 fileData 节点"""
        references: list[FileReference] = []

        def _walk(node: Any):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("fileData", "file_data") and isinstance(value, dict):
                        sha256 = self._resolve_sha_from_file_dict(value)
                        if not sha256:
                            Logger.warning("fileData 无法解析 sha256", request_id=request_id, file_data=value)
                            continue
                        entry = file_manager.get_metadata_entry(sha256)
                        if not entry:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail=f"File {value.get('fileName') or value.get('fileUri')} not found in cache.",
                            )
                        references.append(FileReference(sha256=sha256, entry=entry, file_dict=value))
                    else:
                        _walk(value)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(payload)
        return references

    def _is_client_synced(self, entry: FileCacheEntry, client_id: str) -> bool:
        replication_data = entry.replication_map.get(client_id)
        return bool(replication_data and replication_data.get("status") == "synced")

    def _collect_missing_for_client(self, required_entries: dict[str, FileCacheEntry], client_id: str) -> list[str]:
        missing: list[str] = []
        for sha256, entry in required_entries.items():
            if not self._is_client_synced(entry, client_id):
                missing.append(sha256)
        return missing

    def _select_best_client(
        self,
        required_entries: dict[str, FileCacheEntry],
        preferred_client: str,
    ) -> tuple[str, list[str], list[str]]:
        """扫描所有客户端，选择缺失文件最少的客户端"""
        active_clients = self.get_all_clients()
        if not active_clients:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No frontend clients connected",
            )

        best_clients: list[str] = []
        best_missing_count: Optional[int] = None
        missing_map: dict[str, list[str]] = {}

        for client_id in active_clients:
            missing = self._collect_missing_for_client(required_entries, client_id)
            missing_map[client_id] = missing
            missing_count = len(missing)
            if best_missing_count is None or missing_count < best_missing_count:
                best_missing_count = missing_count
                best_clients = [client_id]
            elif missing_count == best_missing_count:
                best_clients.append(client_id)

        if not best_clients:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No frontend clients available for scheduling",
            )

        if preferred_client in best_clients:
            selected = preferred_client
        else:
            selected = random.choice(best_clients)

        return selected, missing_map.get(selected, []), missing_map.get(preferred_client, [])

    def _rewrite_file_references(self, file_refs: list[FileReference], client_id: str, request_id: str):
        """将 payload 中的 fileData 替换为客户端对应的 fileUri"""
        for ref in file_refs:
            replication_data = ref.entry.replication_map.get(client_id)
            if not replication_data or replication_data.get("status") != "synced":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Client {client_id} does not have required file {ref.sha256[:8]}",
                )

            final_file_name = replication_data.get("name")
            final_uri = replication_data.get("uri") or final_file_name
            if not final_uri:
                Logger.warning("复制数据缺少可用的 fileUri", client_id=client_id, sha256=ref.sha256)
                continue

            ref.file_dict["fileUri"] = final_uri
            ref.file_dict.pop("fileName", None)
            ref.file_dict.pop("file_name", None)
            ref.file_dict.pop("file_uri", None)

            # 记录使用，便于调试
            Logger.debug(
                "已改写 fileData 引用",
                request_id=request_id,
                client_id=client_id,
                sha256=ref.sha256,
                file_uri=final_uri,
            )

    async def _upload_file_via_client(
        self,
        sha256: str,
        client_id: str,
        *,
        request_id: Optional[str] = None,
    ) -> dict:
        """指挥指定客户端从缓存下载并上传文件"""
        entry = file_manager.get_metadata_entry(sha256)
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in cache.")

        effective_request_id = request_id or f"upload-{sha256[:8]}-{client_id}"
        file_manager.update_replication_status(sha256, client_id, "pending_replication")

        try:
            file_bytes = entry.local_path.read_bytes()
        except Exception as exc:
            file_manager.update_replication_status(sha256, client_id, "failed")
            raise HTTPException(status_code=500, detail=f"Failed to read cached file: {exc}") from exc

        encoded_data = base64.b64encode(file_bytes).decode("utf-8")
        display_name = entry.original_filename or "untitled"
        mime_type = entry.mime_type or "application/octet-stream"
        size_bytes_str = str(entry.size_bytes)

        background_request = self._build_background_request()

        try:
            initiate_payload = {
                "metadata": {
                    "file": {
                        "displayName": display_name,
                        "mimeType": mime_type,
                        "sizeBytes": size_bytes_str,
                    }
                }
            }
            initiate_response = await self._direct_proxy_request(
                command_type="initiate_resumable_upload",
                payload=initiate_payload,
                request_id=f"{effective_request_id}-init",
                client_id=client_id,
                request=background_request,
            )
            upload_url = initiate_response.get("upload_url")
            if not upload_url:
                raise ApiException(status_code=500, detail="Failed to obtain upload URL from frontend.")

            chunk_payload = {
                "upload_url": upload_url,
                "upload_offset": 0,
                "content_length": entry.size_bytes,
                "upload_command": "upload, finalize",
                "data_base64": encoded_data,
            }
            upload_response = await self._direct_proxy_request(
                command_type="upload_chunk",
                payload=chunk_payload,
                request_id=f"{effective_request_id}-chunk",
                client_id=client_id,
                request=background_request,
            )
        except Exception:
            file_manager.update_replication_status(sha256, client_id, "failed")
            raise

        gemini_file = upload_response.get("body") or upload_response.get("file")
        if isinstance(gemini_file, dict) and "file" in gemini_file and isinstance(gemini_file["file"], dict):
            gemini_file = gemini_file["file"]
        if not gemini_file:
            file_manager.update_replication_status(sha256, client_id, "failed")
            raise ApiException(status_code=500, detail="Frontend did not return a file object after upload.")

        file_manager.update_replication_status(sha256, client_id, "synced", gemini_file)
        Logger.event(
            "REPLICATION_SUCCESS",
            "文件上传/复制成功",
            sha256=sha256,
            client_id=client_id,
            request_id=effective_request_id,
        )
        return gemini_file

    async def _replicate_files_to_client(
        self,
        client_id: str,
        sha_list: list[str],
        request_id: str,
    ):
        """同步等待客户端复制所有缺失文件"""
        if not sha_list:
            return

        Logger.info(
            "同步补全缺失文件",
            client_id=client_id,
            request_id=request_id,
            files=len(sha_list),
        )
        for sha in sha_list:
            await self._upload_file_via_client(
                sha,
                client_id,
                request_id=f"replicate-{request_id}-{sha[:8]}",
            )

    # ========================================================================
    # 方案 B: 核心请求处理流程
    # ========================================================================

    def trigger_bulk_replication(self, client_id: str, sha_list: list[str]):
        """触发后台任务，批量为客户端复制缺失文件"""
        if not sha_list:
            return
        task_id = f"heal-{client_id}-{uuid.uuid4().hex[:6]}"
        create_background_task(self._bulk_replication_task(client_id, sha_list, task_id))

    async def _bulk_replication_task(self, client_id: str, sha_list: list[str], task_id: str):
        """后台批量复制任务"""
        Logger.event(
            "SELF_HEAL_START",
            "开始后台自愈复制",
            client_id=client_id,
            files=len(sha_list),
            task_id=task_id,
        )
        try:
            await self._replicate_files_to_client(client_id, sha_list, task_id)
            Logger.event(
                "SELF_HEAL_SUCCESS",
                "后台自愈复制成功",
                client_id=client_id,
                files=len(sha_list),
                task_id=task_id,
            )
        except Exception as exc:
            Logger.warning(
                "后台自愈复制失败",
                client_id=client_id,
                files=len(sha_list),
                task_id=task_id,
                exc=exc,
            )

    async def upload_file_from_cache(self, sha256: str) -> tuple[dict, str]:
        """
        供 API 调用：同步地选择客户端并上传缓存文件。
        """
        return await self._synchronously_rebuild_file(sha256)

    async def send_command_to_client(
        self,
        *,
        client_id: str,
        command_type: str,
        payload: Any,
        request_id: Optional[str] = None,
        is_streaming: bool = False,
    ) -> Any:
        """
        直接向指定客户端发送命令（供 API 或后台逻辑复用）。
        """
        effective_request_id = request_id or f"direct-{command_type}-{uuid.uuid4()}"
        return await self._direct_proxy_request(
            command_type=command_type,
            payload=payload,
            request_id=effective_request_id,
            client_id=client_id,
            request=self._build_background_request(),
            is_streaming=is_streaming,
        )

    async def _synchronously_rebuild_file(self, sha256: str) -> tuple[dict, str]:
        """
        同步重建文件：轮询选择一个客户端，阻塞式地指挥它重新上传文件。
        """
        request_id = f"rebuild-{sha256[:8]}-{uuid.uuid4()}"
        Logger.event("REBUILD_START", "开始同步文件重建", sha256=sha256)

        client_id = self.get_next_client()
        try:
            gemini_file = await self._upload_file_via_client(sha256, client_id, request_id=request_id)
            Logger.event("REBUILD_SUCCESS", "同步文件重建成功", sha256=sha256, client_id=client_id)
            return gemini_file, client_id

        except Exception as e:
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


manager = ConnectionManager()
